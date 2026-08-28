"""Pure-PyTorch heterogeneous temporal graph student.

No PyTorch Geometric or custom CUDA extension is required. Edges are sparse COO
arrays, attention is normalized per destination node, node/relation types are
explicit, and event memory is aggregated from a variable-length event stream.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any

import torch
from torch import nn
from torch.nn import functional as F


def scatter_sum(src: torch.Tensor, index: torch.Tensor, dim_size: int) -> torch.Tensor:
    out = torch.zeros((dim_size,) + src.shape[1:], device=src.device, dtype=src.dtype)
    out.index_add_(0, index, src)
    return out


def scatter_mean(src: torch.Tensor, index: torch.Tensor, dim_size: int) -> torch.Tensor:
    total = scatter_sum(src, index, dim_size)
    count = torch.zeros(dim_size, device=src.device, dtype=src.dtype)
    count.index_add_(0, index, torch.ones_like(index, dtype=src.dtype))
    shape = (dim_size,) + (1,) * (src.ndim - 1)
    return total / count.clamp_min(1.0).view(shape)


def scatter_max(src: torch.Tensor, index: torch.Tensor, dim_size: int) -> torch.Tensor:
    out = torch.full((dim_size,) + src.shape[1:], -torch.inf, device=src.device, dtype=src.dtype)
    expanded = index.view(-1, *([1] * (src.ndim - 1))).expand_as(src)
    out.scatter_reduce_(0, expanded, src, reduce="amax", include_self=True)
    return torch.where(torch.isfinite(out), out, torch.zeros_like(out))


def segment_softmax(logits: torch.Tensor, index: torch.Tensor, dim_size: int) -> torch.Tensor:
    """Softmax over all rows sharing a destination index, independently per head."""
    maxima = torch.full((dim_size, logits.shape[1]), -torch.inf, device=logits.device, dtype=logits.dtype)
    expanded = index[:, None].expand_as(logits)
    maxima.scatter_reduce_(0, expanded, logits, reduce="amax", include_self=True)
    shifted = logits - maxima[index]
    exp = torch.exp(shifted)
    denom = torch.zeros_like(maxima)
    denom.scatter_add_(0, expanded, exp)
    return exp / denom[index].clamp_min(torch.finfo(exp.dtype).tiny)


class TypeLinear(nn.Module):
    def __init__(self, num_types: int, in_features: int, out_features: int, bias: bool = True):
        super().__init__()
        self.num_types = num_types
        self.in_features = in_features
        self.out_features = out_features
        self.weight = nn.Parameter(torch.empty(num_types, out_features, in_features))
        self.bias = nn.Parameter(torch.empty(num_types, out_features)) if bias else None
        self.reset_parameters()

    def reset_parameters(self) -> None:
        nn.init.kaiming_uniform_(self.weight, a=math.sqrt(5))
        if self.bias is not None:
            bound = 1.0 / math.sqrt(max(1, self.in_features))
            nn.init.uniform_(self.bias, -bound, bound)

    def forward(self, x: torch.Tensor, node_type: torch.Tensor) -> torch.Tensor:
        out = x.new_zeros((x.shape[0], self.out_features))
        # Small fixed type loop avoids materializing one dense matrix per node.
        for type_id in range(self.num_types):
            mask = node_type == type_id
            if torch.any(mask):
                out[mask] = F.linear(x[mask], self.weight[type_id], None if self.bias is None else self.bias[type_id])
        return out


class TemporalEventEncoder(nn.Module):
    """TGN-style message aggregation over an irregular event stream.

    The module has no frame dimension. It maps each event to a message, aggregates
    messages per persistent entity and applies one GRU update. The same GRUCell is
    exposed for incremental streaming updates after deployment.
    """

    def __init__(self, num_event_types: int, memory_dim: int, event_type_dim: int = 16):
        super().__init__()
        self.num_event_types = num_event_types
        self.memory_dim = memory_dim
        self.event_type_embedding = nn.Embedding(num_event_types, event_type_dim)
        self.message = nn.Sequential(
            nn.Linear(event_type_dim + 4 + 4, memory_dim),
            nn.GELU(),
            nn.Linear(memory_dim, memory_dim),
        )
        self.gru = nn.GRUCell(memory_dim * 2, memory_dim)

    @staticmethod
    def _time_features(age: torch.Tensor) -> torch.Tensor:
        age = age.clamp_min(0.0)
        log_age = torch.log1p(age)
        return torch.stack((log_age, torch.sin(log_age), torch.cos(log_age), 1.0 / (1.0 + age)), dim=-1)

    def encode_messages(
        self,
        event_type: torch.Tensor,
        event_time: torch.Tensor,
        event_value: torch.Tensor,
        query_time: float | torch.Tensor,
    ) -> torch.Tensor:
        qt = torch.as_tensor(query_time, dtype=event_time.dtype, device=event_time.device)
        age = qt - event_time
        x = torch.cat((self.event_type_embedding(event_type), event_value, self._time_features(age)), dim=-1)
        return self.message(x)

    def forward(
        self,
        num_nodes: int,
        event_entity: torch.Tensor,
        event_type: torch.Tensor,
        event_time: torch.Tensor,
        event_value: torch.Tensor,
        query_time: float | torch.Tensor,
        initial_memory: torch.Tensor | None = None,
    ) -> torch.Tensor:
        if initial_memory is None:
            initial_memory = event_value.new_zeros((num_nodes, self.memory_dim))
        if event_entity.numel() == 0:
            return initial_memory
        messages = self.encode_messages(event_type, event_time, event_value, query_time)
        mean = scatter_mean(messages, event_entity, num_nodes)
        maximum = scatter_max(messages, event_entity, num_nodes)
        return self.gru(torch.cat((mean, maximum), dim=-1), initial_memory)

    @torch.no_grad()
    def update_stream(
        self,
        memory: torch.Tensor,
        event_entity: torch.Tensor,
        event_type: torch.Tensor,
        event_time: torch.Tensor,
        event_value: torch.Tensor,
        query_time: float | torch.Tensor,
    ) -> torch.Tensor:
        return self.forward(memory.shape[0], event_entity, event_type, event_time, event_value, query_time, memory)


class HGTSpatialLayer(nn.Module):
    def __init__(
        self,
        hidden_dim: int,
        heads: int,
        num_node_types: int,
        num_relations: int,
        dropout: float,
    ):
        super().__init__()
        if hidden_dim % heads:
            raise ValueError("hidden_dim must be divisible by heads")
        self.hidden_dim = hidden_dim
        self.heads = heads
        self.head_dim = hidden_dim // heads
        self.q = TypeLinear(num_node_types, hidden_dim, hidden_dim)
        self.k = TypeLinear(num_node_types, hidden_dim, hidden_dim)
        self.v = TypeLinear(num_node_types, hidden_dim, hidden_dim)
        self.out = TypeLinear(num_node_types, hidden_dim, hidden_dim)
        self.rel_att = nn.Parameter(torch.empty(num_relations, heads, self.head_dim))
        self.rel_msg = nn.Parameter(torch.empty(num_relations, heads, self.head_dim))
        self.rel_value = nn.Parameter(torch.empty(num_relations, heads, self.head_dim))
        self.rel_bias = nn.Parameter(torch.zeros(num_relations, heads))
        self.time_mlp = nn.Sequential(nn.Linear(4, heads), nn.Tanh())
        self.norm1 = nn.LayerNorm(hidden_dim)
        self.norm2 = nn.LayerNorm(hidden_dim)
        self.ffn = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim * 4), nn.GELU(), nn.Dropout(dropout),
            nn.Linear(hidden_dim * 4, hidden_dim), nn.Dropout(dropout),
        )
        self.dropout = nn.Dropout(dropout)
        self.reset_parameters()

    def reset_parameters(self) -> None:
        nn.init.normal_(self.rel_att, mean=1.0, std=0.02)
        nn.init.normal_(self.rel_msg, mean=1.0, std=0.02)
        nn.init.normal_(self.rel_value, std=0.02)

    @staticmethod
    def _edge_time_features(edge_age: torch.Tensor) -> torch.Tensor:
        signed = torch.sign(edge_age)
        a = torch.log1p(edge_age.abs())
        return torch.stack((a, torch.sin(a), torch.cos(a), signed), dim=-1)

    def forward(
        self,
        h: torch.Tensor,
        node_type: torch.Tensor,
        edge_src: torch.Tensor,
        edge_dst: torch.Tensor,
        edge_type: torch.Tensor,
        edge_weight: torch.Tensor,
        edge_age: torch.Tensor,
    ) -> torch.Tensor:
        n = h.shape[0]
        if edge_src.numel() == 0:
            return self.norm2(self.norm1(h) + self.ffn(self.norm1(h)))
        q = self.q(h, node_type).view(n, self.heads, self.head_dim)
        k = self.k(h, node_type).view(n, self.heads, self.head_dim)
        v = self.v(h, node_type).view(n, self.heads, self.head_dim)
        rel_att = self.rel_att[edge_type]
        logits = (q[edge_dst] * k[edge_src] * rel_att).sum(dim=-1) / math.sqrt(self.head_dim)
        logits = logits + self.rel_bias[edge_type] + self.time_mlp(self._edge_time_features(edge_age))
        logits = logits + torch.log(edge_weight.clamp_min(1e-6))[:, None]
        alpha = segment_softmax(logits.float(), edge_dst, n).to(v.dtype)
        message = v[edge_src] * self.rel_msg[edge_type] + self.rel_value[edge_type]
        message = message * alpha[..., None]
        aggregate = scatter_sum(message, edge_dst, n).reshape(n, self.hidden_dim)
        out = self.out(aggregate, node_type)
        h = self.norm1(h + self.dropout(out))
        h = self.norm2(h + self.ffn(h))
        return h


@dataclass(frozen=True)
class ModelConfig:
    feature_dim: int
    num_node_types: int
    num_relations: int
    num_event_types: int
    hidden_dim: int = 128
    heads: int = 8
    layers: int = 3
    memory_dim: int = 64
    teacher_dim: int = 64
    dropout: float = 0.1
    max_distance_m: float = 100_000.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class UGTSSpatialStudent(nn.Module):
    def __init__(self, config: ModelConfig):
        super().__init__()
        self.config = config
        self.temporal = TemporalEventEncoder(config.num_event_types, config.memory_dim)
        self.input = TypeLinear(config.num_node_types, config.feature_dim + config.memory_dim, config.hidden_dim)
        self.type_embedding = nn.Embedding(config.num_node_types, config.hidden_dim)
        self.layers = nn.ModuleList([
            HGTSpatialLayer(config.hidden_dim, config.heads, config.num_node_types, config.num_relations, config.dropout)
            for _ in range(config.layers)
        ])
        self.rel_diag = nn.Parameter(torch.empty(config.num_relations, config.hidden_dim))
        self.rel_bias = nn.Parameter(torch.zeros(config.num_relations))
        self.pair_mlp = nn.Sequential(
            nn.Linear(6, config.hidden_dim // 2), nn.GELU(), nn.Linear(config.hidden_dim // 2, 1)
        )
        relation_pair_dim = max(8, config.hidden_dim // 4)
        self.relation_pair_embedding = nn.Embedding(config.num_relations, relation_pair_dim)
        self.semantic_pair_mlp = nn.Sequential(
            nn.Linear(config.hidden_dim * 2 + relation_pair_dim, config.hidden_dim),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.hidden_dim, 1),
        )
        self.teacher_projection = nn.Linear(config.hidden_dim, config.teacher_dim)
        nn.init.normal_(self.rel_diag, mean=0.0, std=1.0 / math.sqrt(config.hidden_dim))

    @staticmethod
    def pair_features(distance_m: torch.Tensor, example_age: torch.Tensor, max_distance_m: float) -> torch.Tensor:
        d = (distance_m / max_distance_m).clamp_min(0.0)
        ld = torch.log1p(distance_m.clamp_min(0.0)) / math.log1p(max_distance_m)
        a = torch.log1p(example_age.abs())
        return torch.stack((d, ld, torch.sin(ld * math.pi), torch.cos(ld * math.pi), a, torch.sign(example_age)), dim=-1)

    def encode(
        self,
        node_features: torch.Tensor,
        node_type: torch.Tensor,
        edge_src: torch.Tensor,
        edge_dst: torch.Tensor,
        edge_type: torch.Tensor,
        edge_time: torch.Tensor,
        edge_weight: torch.Tensor,
        event_entity: torch.Tensor,
        event_type: torch.Tensor,
        event_time: torch.Tensor,
        event_value: torch.Tensor,
        query_time: float | torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        memory = self.temporal(node_features.shape[0], event_entity, event_type, event_time, event_value, query_time)
        h = self.input(torch.cat((node_features, memory), dim=-1), node_type) + self.type_embedding(node_type)
        h_input = h
        qt = torch.as_tensor(query_time, dtype=edge_time.dtype, device=edge_time.device)
        edge_age = qt - edge_time
        for layer in self.layers:
            h = layer(h, node_type, edge_src, edge_dst, edge_type, edge_weight, edge_age)
        h = h + 0.5 * h_input
        return h, memory

    def decode_links(
        self,
        h: torch.Tensor,
        src: torch.Tensor,
        dst: torch.Tensor,
        relation: torch.Tensor,
        distance_m: torch.Tensor,
        example_time: torch.Tensor,
        query_time: float | torch.Tensor,
    ) -> torch.Tensor:
        qt = torch.as_tensor(query_time, dtype=example_time.dtype, device=example_time.device)
        age = qt - example_time
        hs = h[src]
        hd = h[dst]
        score = (hs * self.rel_diag[relation] * hd).sum(dim=-1) / math.sqrt(self.config.hidden_dim)
        score = score + self.rel_bias[relation]
        score = score + self.pair_mlp(self.pair_features(distance_m, age, self.config.max_distance_m)).squeeze(-1)
        semantic = torch.cat((torch.abs(hs - hd), hs * hd, self.relation_pair_embedding(relation)), dim=-1)
        score = score + self.semantic_pair_mlp(semantic).squeeze(-1)
        return score

    def forward(self, batch: dict[str, torch.Tensor], query_time: float | torch.Tensor) -> dict[str, torch.Tensor]:
        h, memory = self.encode(
            batch["node_features"], batch["node_type"], batch["edge_src"], batch["edge_dst"],
            batch["edge_type"], batch["edge_time"], batch["edge_weight"], batch["event_entity"],
            batch["event_type"], batch["event_time"], batch["event_value"], query_time,
        )
        logits = self.decode_links(
            h, batch["ex_src"], batch["ex_dst"], batch["ex_relation"], batch["ex_distance_m"],
            batch["ex_time"], query_time,
        )
        return {"node_embedding": h, "temporal_memory": memory, "link_logits": logits, "teacher_embedding": self.teacher_projection(h)}
