from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any

import torch
from torch import nn
import torch.nn.functional as F


@dataclass(frozen=True)
class ModelConfig:
    input_dim: int
    teacher_dim: int
    edge_dim: int = 4
    num_node_types: int = 7
    num_relations: int = 16
    hidden_dim: int = 128
    num_heads: int = 4
    num_layers: int = 3
    dropout: float = 0.10
    time_frequencies: int = 4

    def validate(self) -> None:
        if self.input_dim <= 0:
            raise ValueError("input_dim must be positive")
        if self.teacher_dim < 0:
            raise ValueError("teacher_dim must be nonnegative")
        if self.edge_dim <= 0:
            raise ValueError("edge_dim must be positive")
        if self.num_node_types <= 0 or self.num_relations <= 0:
            raise ValueError("type and relation counts must be positive")
        if self.hidden_dim <= 0 or self.num_heads <= 0:
            raise ValueError("hidden_dim and num_heads must be positive")
        if self.hidden_dim % self.num_heads:
            raise ValueError("hidden_dim must be divisible by num_heads")
        if self.num_layers <= 0:
            raise ValueError("num_layers must be positive")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("dropout must be in [0,1)")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ModelConfig":
        config = cls(**value)
        config.validate()
        return config


class TypedLinear(nn.Module):
    """A node-type-specific dense map without Python loops over rows."""

    def __init__(self, num_types: int, in_features: int, out_features: int, bias: bool = True):
        super().__init__()
        self.num_types = num_types
        self.in_features = in_features
        self.out_features = out_features
        self.weight = nn.Parameter(torch.empty(num_types, in_features, out_features))
        self.bias = nn.Parameter(torch.empty(num_types, out_features)) if bias else None
        self.reset_parameters()

    def reset_parameters(self) -> None:
        for weight in self.weight:
            nn.init.xavier_uniform_(weight)
        if self.bias is not None:
            nn.init.zeros_(self.bias)

    def forward(self, x: torch.Tensor, node_type: torch.Tensor) -> torch.Tensor:
        weight = self.weight[node_type]
        result = torch.bmm(x.unsqueeze(1), weight).squeeze(1)
        if self.bias is not None:
            result = result + self.bias[node_type]
        return result


class RelativeTimeEncoding(nn.Module):
    def __init__(self, frequencies: int):
        super().__init__()
        if frequencies <= 0:
            raise ValueError("frequencies must be positive")
        base = torch.logspace(-4, 0, frequencies)
        self.log_frequency = nn.Parameter(torch.log(base))

    @property
    def output_dim(self) -> int:
        return int(self.log_frequency.numel()) * 2 + 2

    def forward(self, delta_time: torch.Tensor) -> torch.Tensor:
        scaled = torch.sign(delta_time) * torch.log1p(delta_time.abs())
        frequency = self.log_frequency.exp().to(dtype=scaled.dtype, device=scaled.device)
        angle = scaled.unsqueeze(-1) * frequency.unsqueeze(0)
        return torch.cat(
            (
                torch.sin(angle),
                torch.cos(angle),
                scaled.unsqueeze(-1),
                torch.sign(delta_time).unsqueeze(-1),
            ),
            dim=-1,
        )


def normalize_edge_attr(edge_attr: torch.Tensor) -> torch.Tensor:
    """Normalize the fixed UGKG edge-attribute contract for the neural path."""
    if edge_attr.shape[-1] != 4:
        raise ValueError("edge_attr must end in four UGKG spatial fields")
    distance = torch.log1p(edge_attr[..., 0].clamp_min(0.0)) / 12.0
    bearing_sin = edge_attr[..., 1].clamp(-1.0, 1.0)
    bearing_cos = edge_attr[..., 2].clamp(-1.0, 1.0)
    delta_time = torch.log1p(edge_attr[..., 3].clamp_min(0.0)) / 20.0
    return torch.stack((distance, bearing_sin, bearing_cos, delta_time), dim=-1)


def segment_softmax(scores: torch.Tensor, destinations: torch.Tensor, num_nodes: int) -> torch.Tensor:
    """Softmax over incoming edges for every destination and attention head."""
    if scores.ndim != 2:
        raise ValueError("scores must have shape [edges, heads]")
    edges, heads = scores.shape
    if edges == 0:
        return scores
    head_ids = torch.arange(heads, device=scores.device, dtype=destinations.dtype)
    groups = destinations.unsqueeze(1) * heads + head_ids.unsqueeze(0)
    flat_groups = groups.reshape(-1)
    flat_scores = scores.reshape(-1)
    group_count = num_nodes * heads
    max_values = torch.full(
        (group_count,),
        -torch.inf,
        device=scores.device,
        dtype=scores.dtype,
    )
    max_values.scatter_reduce_(0, flat_groups, flat_scores, reduce="amax", include_self=True)
    stabilized = flat_scores - max_values[flat_groups]
    exponent = torch.exp(stabilized)
    sums = torch.zeros(group_count, device=scores.device, dtype=scores.dtype)
    sums.index_add_(0, flat_groups, exponent)
    alpha = exponent / sums[flat_groups].clamp_min(torch.finfo(scores.dtype).tiny)
    return alpha.reshape(edges, heads)


class HeterogeneousAttentionLayer(nn.Module):
    """HGT-style typed attention with explicit spatial and temporal edge data.

    Stored graph relations are directed. Message propagation is internally
    bidirectional so an entity can learn from a concept/cell it points to without
    polluting the externally versioned relation vocabulary with inverse IDs.
    """

    def __init__(self, config: ModelConfig):
        super().__init__()
        self.hidden_dim = config.hidden_dim
        self.num_heads = config.num_heads
        self.head_dim = config.hidden_dim // config.num_heads
        self.query = TypedLinear(config.num_node_types, config.hidden_dim, config.hidden_dim)
        self.key = TypedLinear(config.num_node_types, config.hidden_dim, config.hidden_dim)
        self.value = TypedLinear(config.num_node_types, config.hidden_dim, config.hidden_dim)
        self.output = TypedLinear(config.num_node_types, config.hidden_dim, config.hidden_dim)
        self.relation_key = nn.Parameter(
            torch.empty(config.num_relations, config.num_heads, self.head_dim)
        )
        self.relation_value = nn.Parameter(
            torch.empty(config.num_relations, config.num_heads, self.head_dim)
        )
        self.relation_prior = nn.Parameter(torch.zeros(config.num_relations, config.num_heads))
        self.direction_key = nn.Parameter(torch.empty(2, config.num_heads, self.head_dim))
        self.direction_value = nn.Parameter(torch.empty(2, config.num_heads, self.head_dim))
        self.direction_prior = nn.Parameter(torch.zeros(2, config.num_heads))
        self.time_encoding = RelativeTimeEncoding(config.time_frequencies)
        self.time_attention = nn.Linear(self.time_encoding.output_dim, config.num_heads, bias=False)
        self.edge_attention = nn.Linear(config.edge_dim, config.num_heads, bias=False)
        self.edge_value = nn.Linear(config.edge_dim, config.hidden_dim, bias=False)
        self.norm1 = nn.LayerNorm(config.hidden_dim)
        self.norm2 = nn.LayerNorm(config.hidden_dim)
        self.ffn = nn.Sequential(
            nn.Linear(config.hidden_dim, config.hidden_dim * 2),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.hidden_dim * 2, config.hidden_dim),
        )
        self.dropout = nn.Dropout(config.dropout)
        self.reset_parameters()

    def reset_parameters(self) -> None:
        nn.init.ones_(self.relation_key)
        nn.init.ones_(self.relation_value)
        nn.init.normal_(self.direction_key, mean=1.0, std=0.02)
        nn.init.normal_(self.direction_value, mean=1.0, std=0.02)
        nn.init.zeros_(self.relation_prior)
        nn.init.zeros_(self.direction_prior)
        nn.init.xavier_uniform_(self.time_attention.weight)
        nn.init.xavier_uniform_(self.edge_attention.weight)
        nn.init.xavier_uniform_(self.edge_value.weight)

    @staticmethod
    def _bidirectional_edges(
        edge_index: torch.Tensor,
        edge_type: torch.Tensor,
        edge_time: torch.Tensor,
        edge_weight: torch.Tensor,
        edge_attr: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        source = edge_index[0]
        target = edge_index[1]
        expanded_index = torch.cat((edge_index, torch.stack((target, source), dim=0)), dim=1)
        expanded_type = torch.cat((edge_type, edge_type), dim=0)
        expanded_time = torch.cat((edge_time, edge_time), dim=0)
        expanded_weight = torch.cat((edge_weight, edge_weight), dim=0)
        reverse_attr = edge_attr.clone()
        # Reverse bearing by pi. Distance and absolute delta-time are unchanged.
        reverse_attr[:, 1:3] = -reverse_attr[:, 1:3]
        expanded_attr = torch.cat((edge_attr, reverse_attr), dim=0)
        direction = torch.cat(
            (
                torch.zeros(edge_type.shape[0], dtype=torch.long, device=edge_type.device),
                torch.ones(edge_type.shape[0], dtype=torch.long, device=edge_type.device),
            )
        )
        return expanded_index, expanded_type, expanded_time, expanded_weight, expanded_attr, direction

    def forward(
        self,
        x: torch.Tensor,
        node_type: torch.Tensor,
        node_time: torch.Tensor,
        edge_index: torch.Tensor,
        edge_type: torch.Tensor,
        edge_time: torch.Tensor,
        edge_weight: torch.Tensor,
        edge_attr: torch.Tensor,
    ) -> torch.Tensor:
        num_nodes = x.shape[0]
        if edge_index.shape[1] == 0:
            residual = self.norm1(x)
            return self.norm2(residual + self.dropout(self.ffn(residual)))

        (
            edge_index,
            edge_type,
            edge_time,
            edge_weight,
            edge_attr,
            direction,
        ) = self._bidirectional_edges(edge_index, edge_type, edge_time, edge_weight, edge_attr)
        source = edge_index[0]
        destination = edge_index[1]
        q = self.query(x, node_type).view(num_nodes, self.num_heads, self.head_dim)
        k = self.key(x, node_type).view(num_nodes, self.num_heads, self.head_dim)
        v = self.value(x, node_type).view(num_nodes, self.num_heads, self.head_dim)

        normalized_attr = normalize_edge_attr(edge_attr.to(x.dtype))
        q_edge = q[destination]
        k_edge = k[source] * self.relation_key[edge_type] * self.direction_key[direction]
        score = (q_edge * k_edge).sum(dim=-1) / math.sqrt(self.head_dim)
        delta_time = edge_time.to(x.dtype) - node_time[destination].to(x.dtype)
        score = (
            score
            + self.relation_prior[edge_type]
            + self.direction_prior[direction]
            + self.time_attention(self.time_encoding(delta_time))
            + self.edge_attention(normalized_attr)
        )
        alpha = segment_softmax(score, destination, num_nodes)

        spatial_value = self.edge_value(normalized_attr).view(-1, self.num_heads, self.head_dim)
        message = (
            v[source] * self.relation_value[edge_type] * self.direction_value[direction]
            + spatial_value
        )
        message = message * alpha.unsqueeze(-1) * edge_weight.to(x.dtype).view(-1, 1, 1)
        aggregated = torch.zeros_like(v)
        aggregated.index_add_(0, destination, message)
        mixed = self.output(aggregated.reshape(num_nodes, self.hidden_dim), node_type)
        hidden = self.norm1(x + self.dropout(mixed))
        return self.norm2(hidden + self.dropout(self.ffn(hidden)))


class TemporalMemory(nn.Module):
    """TGN-style node memory updated by arbitrary-length timed edge events."""

    def __init__(self, config: ModelConfig):
        super().__init__()
        self.hidden_dim = config.hidden_dim
        self.relation = nn.Embedding(config.num_relations, config.hidden_dim)
        self.time_encoding = RelativeTimeEncoding(config.time_frequencies)
        self.time_projection = nn.Linear(self.time_encoding.output_dim, config.hidden_dim)
        self.value_projection = nn.Linear(1, config.hidden_dim)
        self.edge_projection = nn.Linear(config.edge_dim, config.hidden_dim)
        self.message_projection = nn.Sequential(
            nn.Linear(config.hidden_dim * 4, config.hidden_dim),
            nn.GELU(),
            nn.Linear(config.hidden_dim, config.hidden_dim),
        )
        self.gru = nn.GRUCell(config.hidden_dim, config.hidden_dim)

    def forward(
        self,
        node_state: torch.Tensor,
        memory: torch.Tensor,
        event_index: torch.Tensor,
        event_type: torch.Tensor,
        event_time: torch.Tensor,
        event_value: torch.Tensor,
        event_attr: torch.Tensor,
        reference_time: torch.Tensor | float,
    ) -> torch.Tensor:
        if event_index.numel() == 0:
            return memory
        source = event_index[0]
        target = event_index[1]
        reference = torch.as_tensor(reference_time, dtype=event_time.dtype, device=event_time.device)
        dt = event_time - reference
        temporal = self.time_projection(self.time_encoding(dt.to(node_state.dtype)))
        relation = self.relation(event_type)
        value = self.value_projection(event_value.to(node_state.dtype).view(-1, 1))
        edge = self.edge_projection(normalize_edge_attr(event_attr.to(node_state.dtype)))

        forward_message = self.message_projection(
            torch.cat((node_state[source], relation + temporal, value, edge), dim=-1)
        )
        reverse_message = self.message_projection(
            torch.cat((node_state[target], relation + temporal, value, edge), dim=-1)
        )
        aggregate = torch.zeros_like(memory)
        aggregate.index_add_(0, target, forward_message)
        aggregate.index_add_(0, source, reverse_message)
        touched = torch.unique(torch.cat((source, target)))
        updated = memory.clone()
        updated[touched] = self.gru(aggregate[touched], memory[touched])
        return updated


class UGTSSpatialModel(nn.Module):
    """Typed HGT-style encoder plus TGN-style memory and distillation heads."""

    def __init__(self, config: ModelConfig):
        super().__init__()
        config.validate()
        self.config = config
        self.input_projection = TypedLinear(
            config.num_node_types, config.input_dim, config.hidden_dim
        )
        self.node_type_embedding = nn.Embedding(config.num_node_types, config.hidden_dim)
        self.layers = nn.ModuleList(
            HeterogeneousAttentionLayer(config) for _ in range(config.num_layers)
        )
        self.temporal_memory = TemporalMemory(config)
        self.relation_diagonal = nn.Parameter(
            torch.empty(config.num_relations, config.hidden_dim)
        )
        self.relation_bias = nn.Parameter(torch.zeros(config.num_relations))
        self.edge_score_bias = nn.Sequential(
            nn.Linear(config.edge_dim, config.hidden_dim // 2),
            nn.GELU(),
            nn.Linear(config.hidden_dim // 2, config.num_relations),
        )
        self.type_head = nn.Linear(config.hidden_dim, config.num_node_types)
        self.teacher_head = (
            nn.Linear(config.hidden_dim, config.teacher_dim) if config.teacher_dim > 0 else None
        )
        self.input_norm = nn.LayerNorm(config.hidden_dim)
        self.reset_parameters()

    def reset_parameters(self) -> None:
        nn.init.normal_(self.node_type_embedding.weight, std=0.02)
        nn.init.normal_(self.relation_diagonal, mean=1.0, std=0.02)
        nn.init.zeros_(self.relation_bias)

    def encode(
        self,
        x: torch.Tensor,
        node_type: torch.Tensor,
        node_time: torch.Tensor,
        edge_index: torch.Tensor,
        edge_type: torch.Tensor,
        edge_time: torch.Tensor,
        edge_weight: torch.Tensor,
        edge_attr: torch.Tensor,
    ) -> torch.Tensor:
        hidden = self.input_projection(x, node_type) + self.node_type_embedding(node_type)
        hidden = self.input_norm(hidden)
        for layer in self.layers:
            hidden = layer(
                hidden,
                node_type,
                node_time,
                edge_index,
                edge_type,
                edge_time,
                edge_weight,
                edge_attr,
            )
        return hidden

    def update_memory(
        self,
        node_state: torch.Tensor,
        memory: torch.Tensor | None,
        event_index: torch.Tensor,
        event_type: torch.Tensor,
        event_time: torch.Tensor,
        event_value: torch.Tensor,
        event_attr: torch.Tensor,
        reference_time: torch.Tensor | float,
    ) -> torch.Tensor:
        if memory is None:
            memory = torch.zeros_like(node_state)
        return self.temporal_memory(
            node_state,
            memory,
            event_index,
            event_type,
            event_time,
            event_value,
            event_attr,
            reference_time,
        )

    def score_all_relations(
        self,
        node_state: torch.Tensor,
        edge_index: torch.Tensor,
        edge_attr: torch.Tensor | None = None,
    ) -> torch.Tensor:
        source = node_state[edge_index[0]]
        target = node_state[edge_index[1]]
        pair = source * target
        scores = pair @ self.relation_diagonal.transpose(0, 1)
        scores = scores / math.sqrt(self.config.hidden_dim) + self.relation_bias
        if edge_attr is not None:
            scores = scores + self.edge_score_bias(normalize_edge_attr(edge_attr.to(node_state.dtype)))
        return scores

    def score_edges(
        self,
        node_state: torch.Tensor,
        edge_index: torch.Tensor,
        edge_type: torch.Tensor,
        edge_attr: torch.Tensor | None = None,
    ) -> torch.Tensor:
        scores = self.score_all_relations(node_state, edge_index, edge_attr)
        return scores.gather(1, edge_type.view(-1, 1)).squeeze(1)

    def predict_teacher(self, node_state: torch.Tensor) -> torch.Tensor:
        if self.teacher_head is None:
            return node_state.new_zeros((node_state.shape[0], 0))
        return F.normalize(self.teacher_head(node_state), dim=-1)

    def forward(self, graph: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
        node_state = self.encode(
            graph["x"],
            graph["node_type"],
            graph["node_time"],
            graph["edge_index"],
            graph["edge_type"],
            graph["edge_time"],
            graph["edge_weight"],
            graph["edge_attr"],
        )
        return {
            "node_state": node_state,
            "type_logits": self.type_head(node_state),
            "teacher_embedding": self.predict_teacher(node_state),
        }

    def checkpoint(self, *, schema_hash: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "format": "UGTS-SPATIAL-MODEL-1",
            "config": self.config.to_dict(),
            "schema_hash": schema_hash,
            "state_dict": self.state_dict(),
            "extra": dict(extra or {}),
        }

    @classmethod
    def from_checkpoint(
        cls,
        checkpoint: dict[str, Any],
        *,
        expected_schema_hash: str | None = None,
    ) -> "UGTSSpatialModel":
        if checkpoint.get("format") != "UGTS-SPATIAL-MODEL-1":
            raise ValueError("unsupported model checkpoint format")
        if expected_schema_hash is not None and checkpoint.get("schema_hash") != expected_schema_hash:
            raise ValueError("model/graph schema hash mismatch")
        model = cls(ModelConfig.from_dict(checkpoint["config"]))
        model.load_state_dict(checkpoint["state_dict"])
        return model
