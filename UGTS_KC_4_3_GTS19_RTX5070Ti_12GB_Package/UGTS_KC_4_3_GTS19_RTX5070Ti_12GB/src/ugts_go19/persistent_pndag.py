"""Restartable proof-number DAG over exact persistent PSK roots.

This module is a bounded correctness vertical slice for 1x1 and 2x2 games.
It is deliberately not a production DFPN implementation and provides no
evidence that 19x19 Go is solved.  A resource stop with a live frontier is
always ``UNKNOWN``.

Every live node identity contains the complete canonical ``PersistentState``
and its compact immutable history-root handle.  No node retains a serialized
history artifact.  SHA-256 (or an injected digest in tests) only selects a
collision bucket; exact scalar fields and collision-independent trie comparison
decide equality.  The legacy v2 state bytes remain the exact interchange,
checkpoint, graph, and external-root-pin representation and are regenerated on
demand.  Transitions operate directly on immutable roots and never flatten a
history with :meth:`PersistentHistory.members`.
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
from .digests import canonical_json_bytes, sha256_hex
from .persistent_engine import PersistentState, initial_state, ordered_children
from .persistent_history import (
    SERIALIZATION_FORMAT as HISTORY_SERIALIZATION_FORMAT,
    HistoryRoot,
    PersistentHistory,
)
from .rules import Rules
from .score import area_score2, possible_area_score2_bounds


UINT64_MAX = (1 << 64) - 1
INT64_MIN = -(1 << 63)
INT64_MAX = (1 << 63) - 1
PROOF_ARITHMETIC = {
    "bits": 64,
    "endianness": "little",
    "infinity": str(UINT64_MAX),
    "kind": "saturating_uint64",
}
PERSISTENT_STATE_FORMAT = "UGTS-GO-PERSISTENT-STATE-v2"
CHECKPOINT_FORMAT = "UGTS-GO-PERSISTENT-PNDAG-CHECKPOINT-v2"
GRAPH_FORMAT = "UGTS-GO-PERSISTENT-PNDAG-GRAPH-v2"
ALGORITHM_ID = "bounded-exact-persistent-pndag-v2"
SELECTION_ID = "unresolved-pns-pn-dn-move-semantic-state-v2"
MOVE_ORDER_ID = "numeric-pass-minus-one-semantic-state-v2"
SYMMETRY_MODE = "none"
SCOPE = "bounded-host-ram-persistent-pndag-psk-1x1-2x2"

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
    state: PersistentState
    rank: int
    expansion: str
    children: tuple[tuple[int, int], ...] = ()
    parents: set[int] = field(default_factory=set)
    proof: int = 1
    disproof: int = 1


@dataclass(frozen=True, slots=True)
class PersistentPNDAGResult:
    """Result of one bounded increment of persistent-DAG expansion."""

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
        payload["scope"] = SCOPE
        return payload


def _sat_add(values: Iterable[int]) -> int:
    """Add proof numbers using unsigned-64 saturation, never wraparound."""

    total = 0
    for value in values:
        if type(value) is not int or not 0 <= value <= UINT64_MAX:
            raise ValueError("proof number is outside uint64")
        if total > UINT64_MAX - value:
            total = UINT64_MAX
        else:
            total += value
    return total


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


def _decode_json_object(raw: bytes, label: str) -> dict[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> Any:
        raise ValueError(f"non-finite JSON constant {value}")

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_constant,
        )
    except (
        UnicodeDecodeError,
        UnicodeEncodeError,
        json.JSONDecodeError,
        RecursionError,
        ValueError,
    ) as exc:
        raise ValueError(f"{label} is not valid canonical JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    try:
        canonical = canonical_json_bytes(value)
    except (TypeError, UnicodeEncodeError, ValueError) as exc:
        raise ValueError(f"{label} is not valid canonical JSON") from exc
    if canonical != raw:
        raise ValueError(f"{label} is not in canonical form")
    return value


def canonical_persistent_state_bytes(
    state: PersistentState,
    rules: Rules,
    history: PersistentHistory,
) -> bytes:
    """Serialize a complete state with its exact canonical history artifact.

    The embedded root artifact, rather than its Merkle digest, participates in
    equality. As in ``UGTS-GO-STATE-v1``, ``ply`` is excluded because it is
    campaign metadata rather than part of the game-theoretic state.
    """

    if not isinstance(state, PersistentState):
        raise TypeError("state must be a PersistentState")
    state.validate(rules, history)
    history_artifact = history.serialize_root(state.history_root)
    return canonical_json_bytes(
        {
            "board_hex": state.board.hex(),
            "format": PERSISTENT_STATE_FORMAT,
            "history_artifact_hex": history_artifact.hex(),
            "history_artifact_sha256": sha256_hex(history_artifact),
            "history_root_sha256": state.history_root.root_sha256,
            "passes": state.passes,
            "previous_board_hex": (
                state.previous_board.hex() if state.previous_board is not None else None
            ),
            "rules": _semantic_rules_payload(rules),
            "to_play": state.to_play,
        }
    )


def _state_from_canonical_bytes(
    data: bytes,
    rules: Rules,
    history: PersistentHistory,
) -> PersistentState:
    payload = _decode_json_object(data, "persistent state bytes")
    payload = _require_keys(
        payload,
        {
            "board_hex",
            "format",
            "history_artifact_hex",
            "history_artifact_sha256",
            "history_root_sha256",
            "passes",
            "previous_board_hex",
            "rules",
            "to_play",
        },
        "persistent state payload",
    )
    if payload["format"] != PERSISTENT_STATE_FORMAT:
        raise ValueError("unsupported persistent-state format")
    if payload["rules"] != _semantic_rules_payload(rules):
        raise ValueError("persistent-state rules do not match the run envelope")
    for field_name in ("board_hex", "history_artifact_hex"):
        if type(payload[field_name]) is not str:
            raise ValueError(f"state {field_name} must be a string")
    previous_hex = payload["previous_board_hex"]
    if previous_hex is not None and type(previous_hex) is not str:
        raise ValueError("state previous_board_hex must be a string or null")
    root_hash = payload["history_root_sha256"]
    artifact_hash = payload["history_artifact_sha256"]
    if type(root_hash) is not str or _HEX64.fullmatch(root_hash) is None:
        raise ValueError("history root hash must be lowercase SHA-256")
    if type(artifact_hash) is not str or _HEX64.fullmatch(artifact_hash) is None:
        raise ValueError("history artifact hash must be lowercase SHA-256")
    try:
        board = bytes.fromhex(payload["board_hex"])
        artifact = bytes.fromhex(payload["history_artifact_hex"])
        previous = bytes.fromhex(previous_hex) if previous_hex is not None else None
    except ValueError as exc:
        raise ValueError("persistent state contains invalid hexadecimal bytes") from exc
    if payload["board_hex"] != board.hex():
        raise ValueError("state board_hex must be canonical lowercase hex")
    if payload["history_artifact_hex"] != artifact.hex():
        raise ValueError("history artifact hex must be canonical lowercase hex")
    if previous_hex is not None and previous_hex != previous.hex():
        raise ValueError("previous_board_hex must be canonical lowercase hex")
    if sha256_hex(artifact) != artifact_hash:
        raise ValueError("history artifact hash mismatch")
    to_play = _require_int(payload["to_play"], "state to_play")
    passes = _require_int(
        payload["passes"],
        "state passes",
        minimum=0,
        maximum=rules.passes_to_end,
    )
    root = history.deserialize_root(artifact, expected_root_sha256=root_hash)
    state = PersistentState(
        board=board,
        to_play=to_play,
        passes=passes,
        history_root=root,
        previous_board=previous,
        # Campaign depth is deliberately normalized on restart and does not
        # participate in proof-authoritative identity.
        ply=0,
    )
    state.validate(rules, history)
    if canonical_persistent_state_bytes(state, rules, history) != data:
        raise ValueError("persistent state bytes are not canonical")
    return state


def _rank(state: PersistentState) -> int:
    # A placement adds a new exact PSK member; a pass increments passes.  With
    # two-pass termination every legal edge therefore increases this rank.
    rank = 2 * state.history_root.count + state.passes
    if not 0 <= rank <= UINT64_MAX:
        raise ValueError("persistent-state rank is outside uint64")
    return rank


class PersistentProofNumberDAG:
    """Exact restartable DAG for tiny PSK fixtures using immutable histories.

    ``advance(n)`` commits at most *n* new expansions.  Proof and disproof
    numbers are derived from the complete graph and are recomputed on load.
    Loading requires an exact externally supplied root-state byte pin.
    """

    def __init__(
        self,
        rules: Rules,
        threshold2: int,
        history: PersistentHistory,
        root_state: PersistentState | None = None,
        *,
        digest_fn: DigestFunction | None = None,
        digest_name: str | None = None,
    ) -> None:
        self._initialize_empty(rules, threshold2, history, digest_fn, digest_name)
        root = root_state if root_state is not None else initial_state(rules, history)
        self.root_id = self._intern_state(root)
        if self.root_id != 0:
            raise AssertionError("root must be the first interned state")
        self._recompute_all()

    def _initialize_empty(
        self,
        rules: Rules,
        threshold2: int,
        history: PersistentHistory,
        digest_fn: DigestFunction | None,
        digest_name: str | None,
    ) -> None:
        if not isinstance(rules, Rules):
            raise TypeError("rules must be a Rules instance")
        if rules.superko != "positional_superko":
            raise ValueError("persistent PNDAG requires positional superko")
        if rules.size not in (1, 2):
            raise ValueError("persistent PNDAG is bounded to 1x1 and 2x2 boards")
        if rules.passes_to_end != 2:
            raise ValueError("persistent PNDAG requires two-pass termination")
        if not isinstance(history, PersistentHistory):
            raise TypeError("history must be a PersistentHistory")
        if history.board_size != rules.size:
            raise ValueError("history board size does not match rules")
        if type(threshold2) is not int:
            raise TypeError("threshold2 must be an integer")
        if not INT64_MIN <= threshold2 <= INT64_MAX:
            raise ValueError("threshold2 must fit signed 64-bit interchange")
        if not INT64_MIN <= rules.komi2 <= INT64_MAX:
            raise ValueError("komi2 must fit signed 64-bit interchange")
        score2_min, score2_max = possible_area_score2_bounds(rules)
        if score2_min < INT64_MIN or score2_max > INT64_MAX:
            raise ValueError(
                "possible score2 range must fit signed 64-bit interchange"
            )
        if digest_fn is None:
            if digest_name not in (None, "sha256"):
                raise ValueError("a non-sha256 state digest name requires digest_fn")
            self._raw_digest_fn: DigestFunction = lambda data: hashlib.sha256(
                data
            ).digest()
            self.digest_name = "sha256"
        else:
            if not callable(digest_fn):
                raise TypeError("digest_fn must be callable")
            configured_name = "injected" if digest_name is None else digest_name
            if type(configured_name) is not str or not configured_name:
                raise ValueError("digest_name must be a nonempty string")
            self._raw_digest_fn = digest_fn
            self.digest_name = configured_name
        self.rules = rules
        self.threshold2 = threshold2
        self.history = history
        self.root_id = 0
        self.committed_expansions = 0
        self._nodes: list[_ProofNode] = []
        self._digest_index: dict[str, list[int]] = {}

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

    def _state_bytes(self, state: PersistentState) -> bytes:
        """Regenerate the exact legacy v2 interchange bytes on demand."""

        return canonical_persistent_state_bytes(state, self.rules, self.history)

    def _states_exactly_equal(
        self,
        first: PersistentState,
        second: PersistentState,
    ) -> bool:
        """Compare proof-authoritative fields through exact history handles."""

        return (
            first.board == second.board
            and first.to_play == second.to_play
            and first.passes == second.passes
            and first.previous_board == second.previous_board
            and self.history.roots_equal(
                first.history_root,
                second.history_root,
            )
        )

    def _find_exact_state_id(
        self,
        digest: str,
        state: PersistentState,
    ) -> int | None:
        """Search one digest bucket and verify exact state/root equality."""

        for node_id in self._digest_index.get(digest, ()):
            if self._states_exactly_equal(self._nodes[node_id].state, state):
                return node_id
        return None

    def _intern_state(self, state: PersistentState) -> int:
        state.validate(self.rules, self.history)
        # Keep the existing digest callback input and every wire hash stable,
        # but discard these potentially large bytes after this operation.
        state_bytes = self._state_bytes(state)
        digest = self._digest(state_bytes)
        existing_id = self._find_exact_state_id(digest, state)
        if existing_id is not None:
            return existing_id
        bucket = self._digest_index.get(digest)
        node_id = len(self._nodes)
        if node_id > UINT64_MAX:
            raise ValueError("node identifier exceeds uint64")
        terminal = state.is_terminal(self.rules)
        node = _ProofNode(
            node_id=node_id,
            digest=digest,
            state=state,
            rank=_rank(state),
            expansion=_TERMINAL if terminal else _UNEXPANDED,
        )
        self._initialize_leaf(node)
        self._nodes.append(node)
        try:
            if bucket is None:
                self._digest_index[digest] = [node_id]
            else:
                bucket.append(node_id)
        except BaseException:
            self._nodes.pop()
            current = self._digest_index.get(digest)
            if current is not None and node_id in current:
                current.remove(node_id)
                if not current:
                    del self._digest_index[digest]
            raise
        return node_id

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def edge_count(self) -> int:
        return sum(len(node.children) for node in self._nodes)

    @property
    def root_state_bytes(self) -> bytes:
        """Exact bytes suitable for the mandatory checkpoint root pin."""

        return self._state_bytes(self._nodes[self.root_id].state)

    @property
    def retained_state_artifact_bytes(self) -> int:
        """Serialized state/history bytes retained by live proof nodes.

        The value is deliberately exposed as a bounded acceptance metric.  The
        DAG still retains boards, immutable trie nodes, and Python metadata, and
        may materialize legacy bytes transiently for hashing or checkpoints.
        """

        return 0

    def state_for_id(self, node_id: int) -> PersistentState:
        return self._nodes[node_id].state

    def lookup_state_id(self, state: PersistentState) -> int | None:
        state.validate(self.rules, self.history)
        state_bytes = self._state_bytes(state)
        return self._find_exact_state_id(self._digest(state_bytes), state)

    def parent_ids_for(self, node_id: int) -> tuple[int, ...]:
        return tuple(sorted(self._nodes[node_id].parents))

    def child_edges_for(self, node_id: int) -> tuple[tuple[int, int], ...]:
        return self._nodes[node_id].children

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

    def _canonical_children(
        self, state: PersistentState
    ) -> list[tuple[int, PersistentState]]:
        children = [
            (move, child)
            for move, child, _priority in ordered_children(
                state, self.rules, self.history
            )
        ]
        # Legal moves are unique.  The previous state-byte tie-break therefore
        # never affected this ordering and need not materialize every child's
        # complete history artifact.
        children.sort(key=lambda item: item[0])
        return children

    def _expand_node(self, node_id: int) -> None:
        node = self._nodes[node_id]
        if node.expansion != _UNEXPANDED:
            raise ValueError("only an unexpanded nonterminal node can be expanded")
        original_node_count = len(self._nodes)
        original_expansions = self.committed_expansions
        edge_list: list[tuple[int, int]] = []
        history_transaction: object | None = None
        try:
            history_transaction = self.history._begin_intern_transaction()
            for move, child_state in self._canonical_children(node.state):
                child_id = self._intern_state(child_state)
                child = self._nodes[child_id]
                if child.rank <= node.rank:
                    raise ValueError("PSK edge did not strictly increase semantic rank")
                edge_list.append((move, child_id))
            if not edge_list:
                raise ValueError("a nonterminal Go state must have the pass edge")
            if len({move for move, _child in edge_list}) != len(edge_list):
                raise ValueError("generated child moves are not unique")
            if self.committed_expansions >= UINT64_MAX:
                raise ValueError("committed expansion count exceeds uint64")
            node.children = tuple(edge_list)
            for _move, child_id in node.children:
                self._nodes[child_id].parents.add(node_id)
            node.expansion = _EXPANDED
            self.committed_expansions += 1
            self.history._commit_intern_transaction(history_transaction)
            history_transaction = None
        except BaseException:
            node.children = ()
            node.expansion = _UNEXPANDED
            self.committed_expansions = original_expansions
            # Cover even an add() that mutates its set and then raises.  The
            # complete speculative edge list already exists, so no auxiliary
            # journal allocation is needed during reverse-edge publication.
            for _move, child_id in edge_list:
                if child_id < len(self._nodes):
                    self._nodes[child_id].parents.discard(node_id)
            if len(self._nodes) > original_node_count:
                for orphan_id in range(
                    len(self._nodes) - 1, original_node_count - 1, -1
                ):
                    orphan = self._nodes[orphan_id]
                    bucket = self._digest_index[orphan.digest]
                    if bucket and bucket[-1] == orphan_id:
                        bucket.pop()
                    elif orphan_id in bucket:
                        bucket.remove(orphan_id)
                    if not bucket:
                        del self._digest_index[orphan.digest]
                del self._nodes[original_node_count:]
            if history_transaction is not None:
                self.history._rollback_intern_transaction(history_transaction)
            raise

    def _recompute_all(self) -> None:
        for node in sorted(
            self._nodes,
            key=lambda item: (item.rank, item.node_id),
            reverse=True,
        ):
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
                raise ValueError(
                    "invalid proof state: proof and disproof are both zero"
                )

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
            unresolved = [
                edge
                for edge in node.children
                if self._nodes[edge[1]].proof and self._nodes[edge[1]].disproof
            ]
            if not unresolved:
                raise ValueError("unresolved parent has no unresolved child")
            if node.state.to_play == BLACK:
                _move, child_id = min(
                    unresolved,
                    key=lambda edge: (
                        self._nodes[edge[1]].proof,
                        self._nodes[edge[1]].disproof,
                        edge[0],
                        edge[1],
                    ),
                )
            else:
                _move, child_id = min(
                    unresolved,
                    key=lambda edge: (
                        self._nodes[edge[1]].disproof,
                        self._nodes[edge[1]].proof,
                        edge[0],
                        edge[1],
                    ),
                )
            node = self._nodes[child_id]
        if node.expansion != _UNEXPANDED:
            raise ValueError("most-proving traversal did not reach an open frontier")
        return node.node_id

    def advance(self, additional_expansions: int) -> PersistentPNDAGResult:
        """Commit bounded work; an unfinished frontier remains ``UNKNOWN``."""

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
        return PersistentPNDAGResult(
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
            stack.extend(child for _move, child in self._nodes[node_id].children)
        return reachable

    def _validate_structure(self, *, require_reachable: bool) -> None:
        if not self._nodes or self.root_id != 0:
            raise ValueError("checkpoint root must be node zero")
        expected_digest_index: dict[str, list[int]] = {}
        expected_parents: list[set[int]] = [set() for _node in self._nodes]
        expanded_count = 0
        for expected_id, node in enumerate(self._nodes):
            if node.node_id != expected_id:
                raise ValueError("node identifiers must be contiguous and ordered")
            node.state.validate(self.rules, self.history)
            state_bytes = self._state_bytes(node.state)
            digest = self._digest(state_bytes)
            if node.digest != digest:
                raise ValueError("node digest does not match exact state bytes")
            expected_bucket = expected_digest_index.setdefault(digest, [])
            if any(
                self._states_exactly_equal(
                    self._nodes[seen_id].state,
                    node.state,
                )
                for seen_id in expected_bucket
            ):
                raise ValueError("duplicate exact state records are not permitted")
            expected_bucket.append(node.node_id)
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
            moves: set[int] = set()
            for move, child_id in node.children:
                if type(move) is not int or not INT64_MIN <= move <= INT64_MAX:
                    raise ValueError("edge move must fit signed 64-bit interchange")
                if move in moves:
                    raise ValueError("expanded node has duplicate move edges")
                moves.add(move)
                if type(child_id) is not int or not 0 <= child_id < len(self._nodes):
                    raise ValueError("edge references an unknown node")
                child = self._nodes[child_id]
                if child.rank <= node.rank:
                    raise ValueError("edge violates strict PSK rank ordering")
                expected_parents[child_id].add(node.node_id)
            expected_semantic = self._canonical_children(node.state)
            if len(node.children) != len(expected_semantic) or any(
                actual_move != expected_move
                or not self._states_exactly_equal(
                    self._nodes[child_id].state,
                    expected_state,
                )
                for (actual_move, child_id), (expected_move, expected_state) in zip(
                    node.children,
                    expected_semantic,
                    strict=True,
                )
            ):
                raise ValueError(
                    "expanded node lacks its complete exact legal edge set"
                )
        if expanded_count != self.committed_expansions:
            raise ValueError("committed expansion count does not match the DAG")
        for node, parents in zip(self._nodes, expected_parents, strict=True):
            if node.parents != parents:
                raise ValueError("reverse-parent index does not match the edge set")
        if self._digest_index != expected_digest_index:
            raise ValueError("state digest index does not match node records")
        if require_reachable and self._reachable_ids() != set(range(len(self._nodes))):
            raise ValueError("checkpoint contains nodes unreachable from the root")

    def _clone_with_validated_history_roots(
        self,
        history: PersistentHistory,
        roots: Iterable[HistoryRoot],
    ) -> "PersistentProofNumberDAG":
        """Clone this validated graph onto an ordered exact history forest.

        The source is never mutated.  All candidate nodes and indexes are built
        in a new unpublished object, then the complete edge set, reverse-parent
        relation, rank, proof caches, status, and graph identity are validated
        again.  Allocation failure can therefore only discard the candidate.
        """

        if not isinstance(history, PersistentHistory):
            raise TypeError("history must be a PersistentHistory")
        if history.board_size != self.rules.size:
            raise ValueError("replacement history board size does not match rules")
        if history.digest_name != self.history.digest_name:
            raise ValueError("replacement history digest function mismatch")
        try:
            ordered_roots = tuple(roots)
        except TypeError as exc:
            raise TypeError("replacement history roots must be iterable") from exc
        if len(ordered_roots) != len(self._nodes):
            raise ValueError("replacement history root count does not match nodes")

        source_graph_sha256 = self.graph_sha256()
        source_cached = tuple(
            (node.proof, node.disproof) for node in self._nodes
        )
        clone = type(self).__new__(type(self))
        clone._initialize_empty(
            self.rules,
            self.threshold2,
            history,
            self._raw_digest_fn,
            self.digest_name,
        )
        clone.root_id = self.root_id
        clone.committed_expansions = self.committed_expansions

        for source, root in zip(self._nodes, ordered_roots, strict=True):
            state = PersistentState(
                board=source.state.board,
                to_play=source.state.to_play,
                passes=source.state.passes,
                history_root=root,
                previous_board=source.state.previous_board,
                ply=source.state.ply,
            )
            state.validate(self.rules, history)
            source_bytes = self._state_bytes(source.state)
            candidate_bytes = clone._state_bytes(state)
            if candidate_bytes != source_bytes:
                raise ValueError(
                    "replacement history root changes exact state identity"
                )
            digest = clone._digest(candidate_bytes)
            if digest != source.digest:
                raise ValueError("replacement state digest mismatch")
            if clone._find_exact_state_id(digest, state) is not None:
                raise ValueError(
                    "replacement history roots create a duplicate exact state"
                )
            node = _ProofNode(
                node_id=source.node_id,
                digest=digest,
                state=state,
                rank=source.rank,
                expansion=source.expansion,
                children=source.children,
                proof=source.proof,
                disproof=source.disproof,
            )
            clone._nodes.append(node)
            clone._digest_index.setdefault(digest, []).append(node.node_id)

        for node in clone._nodes:
            for _move, child_id in node.children:
                if not 0 <= child_id < len(clone._nodes):
                    raise ValueError("replacement edge references an unknown node")
                clone._nodes[child_id].parents.add(node.node_id)

        clone._validate_structure(require_reachable=True)
        clone._recompute_all()
        if tuple((node.proof, node.disproof) for node in clone._nodes) != source_cached:
            raise ValueError("replacement proof caches fail exact recomputation")
        if clone.graph_sha256() != source_graph_sha256:
            raise ValueError("replacement history roots change graph identity")
        return clone

    def _graph_payload(self) -> dict[str, Any]:
        root = self._nodes[self.root_id]
        return {
            "algorithm": ALGORITHM_ID,
            "format": GRAPH_FORMAT,
            "move_order": MOVE_ORDER_ID,
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
                    "state_hex": self._state_bytes(node.state).hex(),
                }
                for node in self._nodes
            ],
            "proof_arithmetic": dict(PROOF_ARITHMETIC),
            "root_id": self.root_id,
            "root_state_object_id": sha256_hex(self._state_bytes(root.state)),
            "rules_sha256": sha256_hex(canonical_json_bytes(self.rules.as_dict())),
            "selection": SELECTION_ID,
            "state_format": PERSISTENT_STATE_FORMAT,
            "symmetry": SYMMETRY_MODE,
            "threshold2": self.threshold2,
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
            "committed_expansions": self.committed_expansions,
            "digest_index": {
                "collision_checked": True,
                "name": self.digest_name,
            },
            "edge_count": self.edge_count,
            "format": CHECKPOINT_FORMAT,
            "graph_sha256": self.graph_sha256(),
            "history_digest_index": {
                "collision_checked": True,
                "name": self.history.digest_name,
            },
            "history_format": HISTORY_SERIALIZATION_FORMAT,
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
                    "state_hex": self._state_bytes(node.state).hex(),
                }
                for node in self._nodes
            ],
            "proof_arithmetic": dict(PROOF_ARITHMETIC),
            "root_disproof_number": root.disproof,
            "root_id": self.root_id,
            "root_proof_number": root.proof,
            "root_state_object_id": sha256_hex(self._state_bytes(root.state)),
            "rules": self.rules.as_dict(),
            "rules_sha256": sha256_hex(canonical_json_bytes(self.rules.as_dict())),
            "scope": SCOPE,
            "selection": SELECTION_ID,
            "state_format": PERSISTENT_STATE_FORMAT,
            "status": self._status(root.proof, root.disproof),
            "symmetry": SYMMETRY_MODE,
            "threshold2": self.threshold2,
        }

    def save_checkpoint(self, path: str | Path) -> None:
        """Atomically publish a canonical self-hashed checkpoint."""

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
                flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                directory_fd = os.open(destination.parent, flags)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    @classmethod
    def load_checkpoint(
        cls,
        path: str | Path,
        *,
        expected_rules: Rules,
        expected_threshold2: int,
        expected_root_state_bytes: bytes,
        digest_fn: DigestFunction | None = None,
        digest_name: str | None = None,
        history_digest_fn: DigestFunction | None = None,
        history_digest_name: str | None = None,
    ) -> "PersistentProofNumberDAG":
        """Load after strict validation and an exact mandatory root target pin."""

        if not isinstance(expected_rules, Rules):
            raise TypeError("expected_rules must be a Rules instance")
        if type(expected_threshold2) is not int:
            raise TypeError("expected_threshold2 must be an integer")
        if (
            type(expected_root_state_bytes) is not bytes
            or not expected_root_state_bytes
        ):
            raise TypeError("expected_root_state_bytes must be nonempty bytes")
        raw = Path(path).read_bytes()
        if not raw.endswith(b"\n"):
            raise ValueError("checkpoint is not in canonical form")
        payload = _decode_json_object(raw[:-1], "checkpoint")
        payload = _require_keys(
            payload,
            {
                "algorithm",
                "checkpoint_sha256",
                "committed_expansions",
                "digest_index",
                "edge_count",
                "format",
                "graph_sha256",
                "history_digest_index",
                "history_format",
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
                "scope",
                "selection",
                "state_format",
                "status",
                "symmetry",
                "threshold2",
            },
            "checkpoint",
        )
        provided_hash = payload["checkpoint_sha256"]
        if type(provided_hash) is not str or _HEX64.fullmatch(provided_hash) is None:
            raise ValueError("checkpoint hash must be lowercase SHA-256")
        unhashed = dict(payload)
        unhashed.pop("checkpoint_sha256")
        if provided_hash != sha256_hex(canonical_json_bytes(unhashed)):
            raise ValueError("checkpoint content hash mismatch")
        if payload["format"] != CHECKPOINT_FORMAT:
            raise ValueError("unsupported checkpoint format")
        if payload["state_format"] != PERSISTENT_STATE_FORMAT:
            raise ValueError("unsupported checkpoint state format")
        if payload["history_format"] != HISTORY_SERIALIZATION_FORMAT:
            raise ValueError("unsupported checkpoint history format")
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
        if payload["scope"] != SCOPE:
            raise ValueError("checkpoint scope mismatch")

        rules = Rules.from_dict(payload["rules"])
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
        if threshold2 != expected_threshold2:
            raise ValueError("checkpoint threshold does not match the expected run")

        digest_index = _require_keys(
            payload["digest_index"], {"collision_checked", "name"}, "digest_index"
        )
        if digest_index["collision_checked"] is not True:
            raise ValueError("checkpoint requires collision-checked state indexing")
        stored_digest_name = digest_index["name"]
        if type(stored_digest_name) is not str or not stored_digest_name:
            raise ValueError("checkpoint state digest name must be nonempty text")
        if digest_fn is None:
            if stored_digest_name != "sha256":
                raise ValueError("checkpoint requires its injected state digest")
            configured_digest_name: str | None = "sha256"
        else:
            configured_digest_name = "injected" if digest_name is None else digest_name
            if configured_digest_name != stored_digest_name:
                raise ValueError("checkpoint state digest function name mismatch")

        history_index = _require_keys(
            payload["history_digest_index"],
            {"collision_checked", "name"},
            "history_digest_index",
        )
        if history_index["collision_checked"] is not True:
            raise ValueError("checkpoint requires collision-checked history indexing")
        stored_history_name = history_index["name"]
        if type(stored_history_name) is not str or not stored_history_name:
            raise ValueError("checkpoint history digest name must be nonempty text")
        if history_digest_fn is None:
            if stored_history_name != "sha256":
                raise ValueError("checkpoint requires its injected history digest")
            configured_history_name: str | None = "sha256"
        else:
            configured_history_name = (
                "injected" if history_digest_name is None else history_digest_name
            )
            if configured_history_name != stored_history_name:
                raise ValueError("checkpoint history digest function name mismatch")
        history = PersistentHistory(
            rules.size,
            digest_fn=history_digest_fn,
            digest_name=configured_history_name,
        )

        obj = cls.__new__(cls)
        obj._initialize_empty(
            rules,
            threshold2,
            history,
            digest_fn,
            configured_digest_name,
        )
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
            state_hex = record["state_hex"]
            if type(state_hex) is not str:
                raise ValueError("node state_hex must be a string")
            try:
                state_bytes = bytes.fromhex(state_hex)
            except ValueError as exc:
                raise ValueError("node state_hex is invalid") from exc
            if state_hex != state_bytes.hex():
                raise ValueError("node state_hex must be canonical lowercase hex")
            state = _state_from_canonical_bytes(state_bytes, rules, history)
            digest = record["digest"]
            if type(digest) is not str or digest != obj._digest(state_bytes):
                raise ValueError("node digest mismatch")
            if obj._find_exact_state_id(digest, state) is not None:
                raise ValueError("duplicate exact state records are not permitted")
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
                state=state,
                rank=rank,
                expansion=expansion,
                proof=proof,
                disproof=disproof,
            )
            obj._nodes.append(node)
            obj._digest_index.setdefault(digest, []).append(node_id)
            cached_values.append((proof, disproof))
            raw_children.append(record["children"])

        for node, child_records in zip(obj._nodes, raw_children, strict=True):
            if not isinstance(child_records, list):
                raise ValueError("node children must be an array")
            edges: list[tuple[int, int]] = []
            for raw_edge in child_records:
                edge = _require_keys(raw_edge, {"child_id", "move"}, "edge")
                move = _require_int(
                    edge["move"],
                    "edge move",
                    minimum=INT64_MIN,
                    maximum=INT64_MAX,
                )
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
            payload["node_count"], "node_count", minimum=1, maximum=UINT64_MAX
        )
        declared_edges = _require_int(
            payload["edge_count"], "edge_count", minimum=0, maximum=UINT64_MAX
        )
        if declared_nodes != obj.node_count or declared_edges != obj.edge_count:
            raise ValueError("checkpoint node or edge count mismatch")
        root = obj._nodes[obj.root_id]
        root_state_bytes = obj._state_bytes(root.state)
        root_object_id = payload["root_state_object_id"]
        if type(root_object_id) is not str or root_object_id != sha256_hex(
            root_state_bytes
        ):
            raise ValueError("checkpoint root state object ID mismatch")
        if root_state_bytes != expected_root_state_bytes:
            raise ValueError("checkpoint root does not match the exact expected target")

        # Regenerate every expanded legal edge and independently recompute all
        # proof caches before accepting any saved status as authoritative.
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
    "GRAPH_FORMAT",
    "INT64_MAX",
    "INT64_MIN",
    "MOVE_ORDER_ID",
    "PERSISTENT_STATE_FORMAT",
    "PROOF_ARITHMETIC",
    "PersistentPNDAGResult",
    "PersistentProofNumberDAG",
    "SCOPE",
    "SELECTION_ID",
    "SYMMETRY_MODE",
    "UINT64_MAX",
    "canonical_persistent_state_bytes",
]
