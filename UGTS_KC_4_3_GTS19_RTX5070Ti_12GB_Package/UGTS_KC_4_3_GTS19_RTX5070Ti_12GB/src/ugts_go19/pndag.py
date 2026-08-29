"""Small, exact, restartable proof-number DAG for PSK oracle tests.

This module is deliberately bounded to 1x1 and 2x2 positional-superko games.
It is a correctness vertical slice for durable DAG semantics, not a production
19x19 solver.  The graph is authoritative: proof numbers and status are
derived caches and are independently recomputed when a checkpoint is loaded.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Callable, Iterable

from .constants import BLACK
from .digests import (
    PROOF_STATE_FORMAT,
    canonical_json_bytes,
    canonical_proof_state_payload,
    sha256_hex,
    state_digest,
)
from .engine import ordered_children
from .rules import Rules
from .score import area_score2
from .state import State


UINT64_MAX = (1 << 64) - 1
INT64_MIN = -(1 << 63)
INT64_MAX = (1 << 63) - 1
PROOF_ARITHMETIC = {
    "bits": 64,
    "endianness": "little",
    "infinity": str(UINT64_MAX),
    "kind": "saturating_uint64",
}
CHECKPOINT_FORMAT = "UGTS-GO-PNDAG-CHECKPOINT-v1"
GRAPH_FORMAT = "UGTS-GO-PNDAG-GRAPH-v1"
ALGORITHM_ID = "bounded-exact-pndag-v1"
SELECTION_ID = "pns-pn-dn-move-statebytes-v1"
MOVE_ORDER_ID = "numeric-pass-minus-one-v1"
SYMMETRY_MODE = "none"

_UNEXPANDED = "unexpanded"
_EXPANDED = "expanded"
_TERMINAL = "terminal"
_EXPANSION_STATES = {_UNEXPANDED, _EXPANDED, _TERMINAL}
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")

DigestFunction = Callable[[bytes], bytes | str]


@dataclass(slots=True)
class _ProofNode:
    node_id: int
    digest: str
    state_bytes: bytes
    state: State
    rank: int
    expansion: str
    children: tuple[tuple[int, int], ...] = ()
    parents: set[int] = field(default_factory=set)
    proof: int = 1
    disproof: int = 1


@dataclass(frozen=True, slots=True)
class PNDAGResult:
    """Result of one bounded increment of DAG expansion."""

    status: str
    threshold2: int
    proof_number: int
    disproof_number: int
    expanded_this_call: int
    committed_expansions: int
    node_count: int
    edge_count: int
    graph_sha256: str

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["proof_arithmetic"] = dict(PROOF_ARITHMETIC)
        return payload


def _sat_add(values: Iterable[int]) -> int:
    total = 0
    for value in values:
        if value < 0 or value > UINT64_MAX:
            raise ValueError("proof number is outside uint64")
        if total > UINT64_MAX - value:
            return UINT64_MAX
        total += value
    return total


def _rank(state: State) -> int:
    # Under PSK with two-pass termination, placements add a new history token
    # and passes increase the pass count.  Therefore every legal edge strictly
    # increases this rank, making reverse-rank recomputation well founded.
    return 2 * len(state.seen) + state.passes


def _require_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"{label} has a noncanonical shape")
    return value


def _require_int(
    value: Any,
    label: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if type(value) is not int:
        raise ValueError(f"{label} must be an integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{label} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{label} must be at most {maximum}")
    return value


def _semantic_rules_payload(rules: Rules) -> dict[str, Any]:
    return {
        "allow_suicide": rules.allow_suicide,
        "komi2": rules.komi2,
        "passes_to_end": rules.passes_to_end,
        "scoring": rules.scoring,
        "size": rules.size,
        "superko": rules.superko,
    }


def _canonical_state_bytes(state: State, rules: Rules) -> bytes:
    return canonical_json_bytes(canonical_proof_state_payload(state, rules))


def _state_from_canonical_bytes(data: bytes, rules: Rules) -> State:
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("state bytes are not valid canonical JSON") from exc
    payload = _require_keys(
        payload,
        {
            "board_hex",
            "format",
            "passes",
            "previous_board_hex",
            "rules",
            "seen_hex",
            "to_play",
        },
        "state payload",
    )
    if payload["format"] != PROOF_STATE_FORMAT:
        raise ValueError("unsupported proof-state format")
    if payload["rules"] != _semantic_rules_payload(rules):
        raise ValueError("state semantic rules do not match the run envelope")
    if type(payload["board_hex"]) is not str:
        raise ValueError("state board_hex must be a string")
    _require_int(payload["to_play"], "state to_play")
    _require_int(payload["passes"], "state passes", minimum=0)
    seen_hex = payload["seen_hex"]
    if not isinstance(seen_hex, list) or any(type(item) is not str for item in seen_hex):
        raise ValueError("state seen_hex must be a string array")
    if seen_hex != sorted(set(seen_hex)):
        raise ValueError("state seen_hex must be sorted and unique")
    previous_hex = payload["previous_board_hex"]
    if previous_hex is not None and type(previous_hex) is not str:
        raise ValueError("state previous_board_hex must be a string or null")
    try:
        state = State(
            board=bytes.fromhex(payload["board_hex"]),
            to_play=payload["to_play"],
            passes=payload["passes"],
            previous_board=(
                bytes.fromhex(previous_hex) if previous_hex is not None else None
            ),
            seen=frozenset(bytes.fromhex(item) for item in seen_hex),
            # Ply is deliberately absent from exact semantic identity.
            ply=0,
        )
    except ValueError as exc:
        raise ValueError("state payload contains invalid hexadecimal bytes") from exc
    state.validate(rules)
    if _canonical_state_bytes(state, rules) != data:
        raise ValueError("state bytes are not in canonical form")
    return state


class ProofNumberDAG:
    """Exact, restartable PNS DAG restricted to tiny positional-superko games.

    ``advance(n)`` means at most *n additional committed expansions*, including
    after checkpoint restore.  A root with nonzero proof and disproof numbers is
    always reported as ``UNKNOWN``.
    """

    def __init__(
        self,
        rules: Rules,
        threshold2: int,
        root_state: State | None = None,
        *,
        digest_fn: DigestFunction | None = None,
        digest_name: str | None = None,
    ) -> None:
        self._initialize_empty(rules, threshold2, digest_fn, digest_name)
        root = root_state if root_state is not None else State.initial(rules)
        self.root_id = self._intern_state(root)
        if self.root_id != 0:
            raise AssertionError("root must be the first interned state")
        self._recompute_all()

    def _initialize_empty(
        self,
        rules: Rules,
        threshold2: int,
        digest_fn: DigestFunction | None,
        digest_name: str | None,
    ) -> None:
        if not isinstance(rules, Rules):
            raise TypeError("rules must be a Rules instance")
        if rules.superko != "positional_superko":
            raise ValueError("ProofNumberDAG supports positional superko only")
        if rules.size not in (1, 2):
            raise ValueError("ProofNumberDAG is bounded to 1x1 and 2x2 boards")
        if rules.passes_to_end != 2:
            raise ValueError("ProofNumberDAG requires two-pass termination")
        if type(threshold2) is not int:
            raise TypeError("threshold2 must be an integer")
        if not INT64_MIN <= threshold2 <= INT64_MAX:
            raise ValueError("threshold2 must fit signed 64-bit interchange")
        if not INT64_MIN <= rules.komi2 <= INT64_MAX:
            raise ValueError("komi2 must fit signed 64-bit interchange")
        if digest_fn is None:
            if digest_name not in (None, "sha256"):
                raise ValueError("a non-sha256 digest name requires digest_fn")
            self._raw_digest_fn: DigestFunction = (
                lambda data: hashlib.sha256(data).digest()
            )
            self.digest_name = "sha256"
        else:
            if not callable(digest_fn):
                raise TypeError("digest_fn must be callable")
            if digest_name is None:
                digest_name = "injected"
            if type(digest_name) is not str or not digest_name:
                raise ValueError("digest_name must be a nonempty string")
            self._raw_digest_fn = digest_fn
            self.digest_name = digest_name
        self.rules = rules
        self.threshold2 = threshold2
        self.root_id = 0
        self.committed_expansions = 0
        self._nodes: list[_ProofNode] = []
        self._digest_index: dict[str, list[int]] = {}
        self._exact_index: dict[bytes, int] = {}

    def _digest(self, state_bytes: bytes) -> str:
        value = self._raw_digest_fn(state_bytes)
        if type(value) is bytes:
            if len(value) != 32:
                raise ValueError("digest_fn must return exactly 32 bytes")
            result = value.hex()
        elif type(value) is str:
            result = value.lower()
        else:
            raise TypeError("digest_fn must return bytes or hexadecimal text")
        if _HEX64.fullmatch(result) is None:
            raise ValueError("digest_fn must return a 256-bit hexadecimal digest")
        return result

    def _intern_state(self, state: State) -> int:
        state.validate(self.rules)
        state_bytes = _canonical_state_bytes(state, self.rules)
        existing_id = self._exact_index.get(state_bytes)
        if existing_id is not None:
            return existing_id
        normalized = _state_from_canonical_bytes(state_bytes, self.rules)
        digest = self._digest(state_bytes)
        bucket = self._digest_index.get(digest)
        if bucket is not None:
            for node_id in bucket:
                if self._nodes[node_id].state_bytes == state_bytes:
                    return node_id
        node_id = len(self._nodes)
        terminal = normalized.is_terminal(self.rules)
        node = _ProofNode(
            node_id=node_id,
            digest=digest,
            state_bytes=state_bytes,
            state=normalized,
            rank=_rank(normalized),
            expansion=_TERMINAL if terminal else _UNEXPANDED,
        )
        self._initialize_leaf(node)
        self._nodes.append(node)
        try:
            if bucket is None:
                self._digest_index[digest] = [node_id]
            else:
                bucket.append(node_id)
            self._exact_index[state_bytes] = node_id
        except BaseException:
            self._nodes.pop()
            self._exact_index.pop(state_bytes, None)
            current = self._digest_index.get(digest)
            if current is not None and node_id in current:
                current.remove(node_id)
                if not current:
                    del self._digest_index[digest]
            raise
        return node_id

    def lookup_state_id(self, state: State) -> int | None:
        state.validate(self.rules)
        state_bytes = _canonical_state_bytes(state, self.rules)
        return self._exact_index.get(state_bytes)

    def state_for_id(self, node_id: int) -> State:
        return self._nodes[node_id].state

    def parent_ids_for(self, node_id: int) -> tuple[int, ...]:
        """Return the exact reverse edges for audit and checkpoint tests."""

        return tuple(sorted(self._nodes[node_id].parents))

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def edge_count(self) -> int:
        return sum(len(node.children) for node in self._nodes)

    def collision_bucket_sizes(self) -> tuple[int, ...]:
        return tuple(sorted(len(bucket) for bucket in self._digest_index.values()))

    def _initialize_leaf(self, node: _ProofNode) -> None:
        if node.state.is_terminal(self.rules):
            if area_score2(node.state.board, self.rules) >= self.threshold2:
                node.proof, node.disproof = 0, UINT64_MAX
            else:
                node.proof, node.disproof = UINT64_MAX, 0
        else:
            node.proof = node.disproof = 1

    def _canonical_children(self, state: State) -> list[tuple[int, bytes, State]]:
        children = [
            (move, _canonical_state_bytes(child, self.rules), child)
            for move, child, _priority in ordered_children(state, self.rules)
        ]
        children.sort(key=lambda item: (item[0], item[1]))
        return children

    def _expand_node(self, node_id: int) -> None:
        node = self._nodes[node_id]
        if node.expansion != _UNEXPANDED:
            raise ValueError("only an unexpanded nonterminal node can be expanded")
        original_node_count = len(self._nodes)
        original_committed_expansions = self.committed_expansions
        parents_published: list[int] = []
        edge_list: list[tuple[int, int]] = []
        try:
            for move, _state_bytes, child_state in self._canonical_children(node.state):
                child_id = self._intern_state(child_state)
                child = self._nodes[child_id]
                if child.rank <= node.rank:
                    raise ValueError("PSK edge did not strictly increase semantic rank")
                edge_list.append((move, child_id))
            if not edge_list:
                raise ValueError("a nonterminal Go state must have the pass edge")
            if len({move for move, _child_id in edge_list}) != len(edge_list):
                raise ValueError("generated child moves are not unique")
            # Publish only after every child has been interned and checked.
            node.children = tuple(edge_list)
            for _move, child_id in node.children:
                self._nodes[child_id].parents.add(node_id)
                parents_published.append(child_id)
            node.expansion = _EXPANDED
            self.committed_expansions += 1
        except BaseException:
            # Expansion is a transaction: an interruption before the final
            # commit must not strand unreachable interned nodes or partial
            # reverse-parent links that poison a later checkpoint.
            node.children = ()
            node.expansion = _UNEXPANDED
            self.committed_expansions = original_committed_expansions
            for child_id in parents_published:
                if child_id < len(self._nodes):
                    self._nodes[child_id].parents.discard(node_id)
            if len(self._nodes) > original_node_count:
                for orphan_id in range(
                    len(self._nodes) - 1, original_node_count - 1, -1
                ):
                    orphan = self._nodes[orphan_id]
                    self._exact_index.pop(orphan.state_bytes, None)
                    bucket = self._digest_index[orphan.digest]
                    if bucket and bucket[-1] == orphan_id:
                        bucket.pop()
                    elif orphan_id in bucket:
                        bucket.remove(orphan_id)
                    if not bucket:
                        del self._digest_index[orphan.digest]
                del self._nodes[original_node_count:]
            raise

    def _recompute_all(self) -> None:
        for node in sorted(self._nodes, key=lambda item: (item.rank, item.node_id), reverse=True):
            if node.expansion in {_UNEXPANDED, _TERMINAL}:
                self._initialize_leaf(node)
                continue
            if not node.children:
                raise ValueError("expanded node has no complete edge set")
            children = [self._nodes[child_id] for _move, child_id in node.children]
            if node.state.to_play == BLACK:
                node.proof = min(child.proof for child in children)
                node.disproof = _sat_add(child.disproof for child in children)
            else:
                node.proof = _sat_add(child.proof for child in children)
                node.disproof = min(child.disproof for child in children)
            if node.proof == 0 and node.disproof == 0:
                raise ValueError("invalid proof state: both root alternatives are solved")

    @staticmethod
    def _status(proof: int, disproof: int) -> str:
        if proof == 0 and disproof == 0:
            raise ValueError("proof and disproof numbers cannot both be zero")
        if proof == 0:
            return "PROVEN"
        if disproof == 0:
            return "DISPROVEN"
        return "UNKNOWN"

    def _select_most_proving(self) -> int:
        node = self._nodes[self.root_id]
        while node.expansion == _EXPANDED and node.proof and node.disproof:
            if not node.children:
                raise ValueError("expanded node has no children")
            if node.state.to_play == BLACK:
                move, child_id = min(
                    node.children,
                    key=lambda edge: (
                        self._nodes[edge[1]].proof,
                        self._nodes[edge[1]].disproof,
                        edge[0],
                        self._nodes[edge[1]].state_bytes,
                    ),
                )
            else:
                move, child_id = min(
                    node.children,
                    key=lambda edge: (
                        self._nodes[edge[1]].disproof,
                        self._nodes[edge[1]].proof,
                        edge[0],
                        self._nodes[edge[1]].state_bytes,
                    ),
                )
            del move
            node = self._nodes[child_id]
        if node.expansion != _UNEXPANDED:
            raise ValueError("most-proving traversal did not reach an open frontier")
        return node.node_id

    def advance(self, additional_expansions: int) -> PNDAGResult:
        """Commit at most ``additional_expansions`` beyond the current graph."""

        if type(additional_expansions) is not int or additional_expansions < 0:
            raise ValueError("additional_expansions must be a nonnegative integer")
        self._recompute_all()
        expanded = 0
        root = self._nodes[self.root_id]
        while root.proof and root.disproof and expanded < additional_expansions:
            leaf_id = self._select_most_proving()
            self._expand_node(leaf_id)
            expanded += 1
            self._recompute_all()
            root = self._nodes[self.root_id]
        return PNDAGResult(
            status=self._status(root.proof, root.disproof),
            threshold2=self.threshold2,
            proof_number=root.proof,
            disproof_number=root.disproof,
            expanded_this_call=expanded,
            committed_expansions=self.committed_expansions,
            node_count=self.node_count,
            edge_count=self.edge_count,
            graph_sha256=self.graph_sha256(),
        )

    def _reachable_ids(self) -> set[int]:
        reachable: set[int] = set()
        stack = [self.root_id]
        while stack:
            node_id = stack.pop()
            if node_id in reachable:
                continue
            if not 0 <= node_id < len(self._nodes):
                raise ValueError("edge references an unknown node")
            reachable.add(node_id)
            stack.extend(child_id for _move, child_id in self._nodes[node_id].children)
        return reachable

    def _validate_structure(self, *, require_reachable: bool) -> None:
        if not self._nodes or self.root_id != 0:
            raise ValueError("checkpoint root must be node zero")
        seen_states: dict[bytes, int] = {}
        expected_parents: list[set[int]] = [set() for _node in self._nodes]
        expanded_count = 0
        for expected_id, node in enumerate(self._nodes):
            if node.node_id != expected_id:
                raise ValueError("node identifiers must be contiguous and ordered")
            node.state.validate(self.rules)
            if _canonical_state_bytes(node.state, self.rules) != node.state_bytes:
                raise ValueError("node state bytes do not match its decoded state")
            if node.digest != self._digest(node.state_bytes):
                raise ValueError("node digest does not match canonical state bytes")
            if node.state_bytes in seen_states:
                raise ValueError("duplicate exact state records are not permitted")
            seen_states[node.state_bytes] = node.node_id
            if node.rank != _rank(node.state):
                raise ValueError("node semantic rank mismatch")
            if node.expansion not in _EXPANSION_STATES:
                raise ValueError("unknown node expansion marker")
            terminal = node.state.is_terminal(self.rules)
            if terminal != (node.expansion == _TERMINAL):
                raise ValueError("terminal state has an invalid expansion marker")
            if node.expansion != _EXPANDED:
                if node.children:
                    raise ValueError("only expanded nodes may contain edges")
                continue
            expanded_count += 1
            actual_semantic: list[tuple[int, bytes]] = []
            moves: set[int] = set()
            for move, child_id in node.children:
                if type(move) is not int:
                    raise ValueError("edge move must be an integer")
                if move in moves:
                    raise ValueError("expanded node has duplicate move edges")
                moves.add(move)
                if type(child_id) is not int or not 0 <= child_id < len(self._nodes):
                    raise ValueError("edge references an unknown node")
                child = self._nodes[child_id]
                if child.rank <= node.rank:
                    raise ValueError("edge violates strict PSK rank ordering")
                expected_parents[child_id].add(node.node_id)
                actual_semantic.append((move, child.state_bytes))
            expected_semantic = [
                (move, state_bytes)
                for move, state_bytes, _state in self._canonical_children(node.state)
            ]
            if actual_semantic != expected_semantic:
                raise ValueError("expanded node does not contain its complete legal edge set")
        if expanded_count != self.committed_expansions:
            raise ValueError("committed expansion count does not match the DAG")
        for node, parents in zip(self._nodes, expected_parents, strict=True):
            if node.parents != parents:
                raise ValueError("reverse-parent index does not match the edge set")
        if self._exact_index != seen_states:
            raise ValueError("exact-state index does not match the node records")
        if require_reachable and self._reachable_ids() != set(range(len(self._nodes))):
            raise ValueError("checkpoint contains nodes unreachable from the root")

    def _graph_payload(self) -> dict[str, Any]:
        root = self._nodes[self.root_id]
        return {
            "algorithm": ALGORITHM_ID,
            "claim_root_digest": state_digest(root.state, self.rules),
            "format": GRAPH_FORMAT,
            "move_order": MOVE_ORDER_ID,
            "proof_arithmetic": dict(PROOF_ARITHMETIC),
            "root_id": self.root_id,
            "root_state_object_id": sha256_hex(root.state_bytes),
            "rules_sha256": sha256_hex(canonical_json_bytes(self.rules.as_dict())),
            "selection": SELECTION_ID,
            "symmetry": SYMMETRY_MODE,
            "threshold2": self.threshold2,
            "nodes": [
                {
                    "children": [
                        {"child_id": child_id, "move": move}
                        for move, child_id in node.children
                    ],
                    "disproof": node.disproof,
                    "expansion": node.expansion,
                    "id": node.node_id,
                    "proof": node.proof,
                    "state_hex": node.state_bytes.hex(),
                }
                for node in self._nodes
            ],
        }

    def graph_sha256(self) -> str:
        self._recompute_all()
        return sha256_hex(canonical_json_bytes(self._graph_payload()))

    def _checkpoint_payload_without_hash(self) -> dict[str, Any]:
        self._validate_structure(require_reachable=True)
        self._recompute_all()
        root = self._nodes[self.root_id]
        return {
            "algorithm": ALGORITHM_ID,
            "claim_root_digest": state_digest(root.state, self.rules),
            "committed_expansions": self.committed_expansions,
            "digest_index": {
                "collision_checked": True,
                "name": self.digest_name,
            },
            "edge_count": self.edge_count,
            "format": CHECKPOINT_FORMAT,
            "graph_sha256": self.graph_sha256(),
            "move_order": MOVE_ORDER_ID,
            "node_count": self.node_count,
            "nodes": [
                {
                    "cached_disproof": node.disproof,
                    "cached_proof": node.proof,
                    "children": [
                        {"child_id": child_id, "move": move}
                        for move, child_id in node.children
                    ],
                    "digest": node.digest,
                    "expansion": node.expansion,
                    "id": node.node_id,
                    "rank": node.rank,
                    "state_hex": node.state_bytes.hex(),
                }
                for node in self._nodes
            ],
            "proof_arithmetic": dict(PROOF_ARITHMETIC),
            "root_disproof_number": root.disproof,
            "root_id": self.root_id,
            "root_proof_number": root.proof,
            "root_state_object_id": sha256_hex(root.state_bytes),
            "rules": self.rules.as_dict(),
            "rules_sha256": sha256_hex(canonical_json_bytes(self.rules.as_dict())),
            "selection": SELECTION_ID,
            "state_format": PROOF_STATE_FORMAT,
            "status": self._status(root.proof, root.disproof),
            "symmetry": SYMMETRY_MODE,
            "threshold2": self.threshold2,
        }

    def save_checkpoint(self, path: str | Path) -> None:
        """Publish a deterministic, self-hashed checkpoint for one writer."""

        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = self._checkpoint_payload_without_hash()
        payload["checkpoint_sha256"] = sha256_hex(canonical_json_bytes(payload))
        serialized = canonical_json_bytes(payload) + b"\n"
        descriptor, temporary_name = tempfile.mkstemp(
            dir=destination.parent,
            prefix=f".{destination.name}.tmp-{os.getpid()}-",
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
            if os.name == "posix":
                directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                directory_fd = os.open(destination.parent, directory_flags)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temporary.exists():
                temporary.unlink()

    @classmethod
    def load_checkpoint(
        cls,
        path: str | Path,
        *,
        digest_fn: DigestFunction | None = None,
        digest_name: str | None = None,
        expected_rules: Rules | None = None,
        expected_root_state: State | None = None,
        expected_threshold2: int | None = None,
    ) -> "ProofNumberDAG":
        """Load only after independently validating graph and derived caches."""

        raw = Path(path).read_bytes()
        try:
            payload = json.loads(
                raw.decode("utf-8"),
                parse_constant=lambda value: (_ for _ in ()).throw(
                    ValueError(f"non-finite JSON constant {value}")
                ),
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            RecursionError,
            ValueError,
        ) as exc:
            raise ValueError("checkpoint is not valid canonical JSON") from exc
        payload = _require_keys(
            payload,
            {
                "algorithm",
                "checkpoint_sha256",
                "claim_root_digest",
                "committed_expansions",
                "digest_index",
                "edge_count",
                "format",
                "graph_sha256",
                "move_order",
                "node_count",
                "nodes",
                "proof_arithmetic",
                "root_disproof_number",
                "root_id",
                "root_proof_number",
                "root_state_object_id",
                "rules",
                "rules_sha256",
                "selection",
                "state_format",
                "status",
                "symmetry",
                "threshold2",
            },
            "checkpoint",
        )
        try:
            canonical_checkpoint = canonical_json_bytes(payload) + b"\n"
        except (TypeError, UnicodeEncodeError, ValueError) as exc:
            raise ValueError("checkpoint is not valid canonical JSON") from exc
        if canonical_checkpoint != raw:
            raise ValueError("checkpoint file is not in canonical form")
        provided_hash = payload["checkpoint_sha256"]
        if type(provided_hash) is not str:
            raise ValueError("checkpoint_sha256 must be a string")
        unhashed = dict(payload)
        unhashed.pop("checkpoint_sha256")
        if provided_hash != sha256_hex(canonical_json_bytes(unhashed)):
            raise ValueError("checkpoint content hash mismatch")
        if payload["format"] != CHECKPOINT_FORMAT:
            raise ValueError("unsupported checkpoint format")
        if payload["state_format"] != PROOF_STATE_FORMAT:
            raise ValueError("unsupported checkpoint state format")
        if payload["proof_arithmetic"] != PROOF_ARITHMETIC:
            raise ValueError("checkpoint proof arithmetic mismatch")
        if payload["algorithm"] != ALGORITHM_ID:
            raise ValueError("checkpoint algorithm mismatch")
        if payload["selection"] != SELECTION_ID:
            raise ValueError("checkpoint selection policy mismatch")
        if payload["move_order"] != MOVE_ORDER_ID:
            raise ValueError("checkpoint move order mismatch")
        if payload["symmetry"] != SYMMETRY_MODE:
            raise ValueError("checkpoint symmetry mode mismatch")

        rules = Rules.from_dict(payload["rules"])
        if expected_rules is not None:
            if not isinstance(expected_rules, Rules):
                raise TypeError("expected_rules must be a Rules instance")
            if rules != expected_rules:
                raise ValueError("checkpoint rules do not match the expected run")
        expected_rules_hash = sha256_hex(canonical_json_bytes(rules.as_dict()))
        if payload["rules_sha256"] != expected_rules_hash:
            raise ValueError("checkpoint rules digest mismatch")
        threshold2 = _require_int(
            payload["threshold2"],
            "threshold2",
            minimum=INT64_MIN,
            maximum=INT64_MAX,
        )
        if expected_threshold2 is not None:
            if type(expected_threshold2) is not int:
                raise TypeError("expected_threshold2 must be an integer")
            if threshold2 != expected_threshold2:
                raise ValueError("checkpoint threshold does not match the expected run")
        digest_index = _require_keys(
            payload["digest_index"],
            {"collision_checked", "name"},
            "digest_index",
        )
        if digest_index["collision_checked"] is not True:
            raise ValueError("checkpoint requires collision-checked indexing")
        stored_digest_name = digest_index["name"]
        if type(stored_digest_name) is not str or not stored_digest_name:
            raise ValueError("checkpoint digest name must be nonempty text")
        if digest_fn is None:
            if stored_digest_name != "sha256":
                raise ValueError("checkpoint requires its injected digest function")
            configured_name: str | None = "sha256"
        else:
            configured_name = digest_name if digest_name is not None else "injected"
            if configured_name != stored_digest_name:
                raise ValueError("checkpoint digest function name mismatch")

        obj = cls.__new__(cls)
        obj._initialize_empty(rules, threshold2, digest_fn, configured_name)
        root_id = _require_int(
            payload["root_id"], "root_id", minimum=0, maximum=UINT64_MAX
        )
        if root_id != 0:
            raise ValueError("checkpoint root must be node zero")
        obj.root_id = root_id
        obj.committed_expansions = _require_int(
            payload["committed_expansions"],
            "committed_expansions",
            minimum=0,
            maximum=UINT64_MAX,
        )

        records = payload["nodes"]
        if not isinstance(records, list) or not records:
            raise ValueError("checkpoint nodes must be a nonempty array")
        cached_values: list[tuple[int, int]] = []
        raw_children: list[Any] = []
        exact_states: set[bytes] = set()
        for expected_id, raw_record in enumerate(records):
            record = _require_keys(
                raw_record,
                {
                    "cached_disproof",
                    "cached_proof",
                    "children",
                    "digest",
                    "expansion",
                    "id",
                    "rank",
                    "state_hex",
                },
                "node record",
            )
            node_id = _require_int(
                record["id"], "node id", minimum=0, maximum=UINT64_MAX
            )
            if node_id != expected_id:
                raise ValueError("checkpoint node ids must be contiguous and ordered")
            if type(record["state_hex"]) is not str:
                raise ValueError("node state_hex must be a string")
            try:
                state_bytes = bytes.fromhex(record["state_hex"])
            except ValueError as exc:
                raise ValueError("node state_hex is invalid") from exc
            if record["state_hex"] != state_bytes.hex():
                raise ValueError("node state_hex must be canonical lowercase hex")
            state = _state_from_canonical_bytes(state_bytes, rules)
            if state_bytes in exact_states:
                raise ValueError("duplicate exact state records are not permitted")
            exact_states.add(state_bytes)
            digest = record["digest"]
            if type(digest) is not str or digest != obj._digest(state_bytes):
                raise ValueError("node digest mismatch")
            rank = _require_int(
                record["rank"], "node rank", minimum=0, maximum=UINT64_MAX
            )
            if rank != _rank(state):
                raise ValueError("node semantic rank mismatch")
            expansion = record["expansion"]
            if expansion not in _EXPANSION_STATES:
                raise ValueError("unknown node expansion marker")
            proof = _require_int(
                record["cached_proof"],
                "cached proof",
                minimum=0,
                maximum=UINT64_MAX,
            )
            disproof = _require_int(
                record["cached_disproof"],
                "cached disproof",
                minimum=0,
                maximum=UINT64_MAX,
            )
            node = _ProofNode(
                node_id=node_id,
                digest=digest,
                state_bytes=state_bytes,
                state=state,
                rank=rank,
                expansion=expansion,
                proof=proof,
                disproof=disproof,
            )
            obj._nodes.append(node)
            obj._digest_index.setdefault(digest, []).append(node_id)
            obj._exact_index[state_bytes] = node_id
            cached_values.append((proof, disproof))
            raw_children.append(record["children"])

        for node, child_records in zip(obj._nodes, raw_children, strict=True):
            if not isinstance(child_records, list):
                raise ValueError("node children must be an array")
            edges: list[tuple[int, int]] = []
            for raw_edge in child_records:
                edge = _require_keys(raw_edge, {"child_id", "move"}, "edge")
                move = _require_int(edge["move"], "edge move")
                child_id = _require_int(
                    edge["child_id"],
                    "edge child_id",
                    minimum=0,
                    maximum=UINT64_MAX,
                )
                if not 0 <= child_id < len(obj._nodes):
                    raise ValueError("edge references an unknown node")
                edges.append((move, child_id))
                obj._nodes[child_id].parents.add(node.node_id)
            node.children = tuple(edges)

        declared_nodes = _require_int(
            payload["node_count"],
            "node_count",
            minimum=1,
            maximum=UINT64_MAX,
        )
        declared_edges = _require_int(
            payload["edge_count"],
            "edge_count",
            minimum=0,
            maximum=UINT64_MAX,
        )
        if declared_nodes != obj.node_count or declared_edges != obj.edge_count:
            raise ValueError("checkpoint node or edge count mismatch")
        root = obj._nodes[obj.root_id]
        if type(payload["root_state_object_id"]) is not str or payload[
            "root_state_object_id"
        ] != sha256_hex(obj._nodes[obj.root_id].state_bytes):
            raise ValueError("checkpoint root state object ID mismatch")
        if type(payload["claim_root_digest"]) is not str or payload[
            "claim_root_digest"
        ] != state_digest(root.state, rules):
            raise ValueError("checkpoint claim-root digest mismatch")
        if expected_root_state is not None:
            if not isinstance(expected_root_state, State):
                raise TypeError("expected_root_state must be a State instance")
            expected_root_state.validate(rules)
            if _canonical_state_bytes(expected_root_state, rules) != root.state_bytes:
                raise ValueError("checkpoint root does not match the expected run")

        # This reconstructs legal edges and reverse parents from semantic state,
        # before any saved proof/status field is consulted as a claim.
        obj._validate_structure(require_reachable=True)
        obj._recompute_all()
        for node, cached in zip(obj._nodes, cached_values, strict=True):
            if (node.proof, node.disproof) != cached:
                raise ValueError("cached proof numbers fail independent recomputation")
        root = obj._nodes[obj.root_id]
        saved_root_proof = _require_int(
            payload["root_proof_number"],
            "root_proof_number",
            minimum=0,
            maximum=UINT64_MAX,
        )
        saved_root_disproof = _require_int(
            payload["root_disproof_number"],
            "root_disproof_number",
            minimum=0,
            maximum=UINT64_MAX,
        )
        if (saved_root_proof, saved_root_disproof) != (root.proof, root.disproof):
            raise ValueError("checkpoint root proof cache mismatch")
        saved_status = payload["status"]
        if type(saved_status) is not str or saved_status != obj._status(
            root.proof, root.disproof
        ):
            raise ValueError("checkpoint status fails independent recomputation")
        saved_graph_hash = payload["graph_sha256"]
        if type(saved_graph_hash) is not str or saved_graph_hash != obj.graph_sha256():
            raise ValueError("checkpoint graph digest mismatch")
        return obj


__all__ = [
    "ALGORITHM_ID",
    "CHECKPOINT_FORMAT",
    "MOVE_ORDER_ID",
    "PNDAGResult",
    "PROOF_ARITHMETIC",
    "ProofNumberDAG",
    "SELECTION_ID",
    "SYMMETRY_MODE",
    "INT64_MAX",
    "INT64_MIN",
    "UINT64_MAX",
]
