"""Bounded proof-number search over immutable positional-superko roots.

This module is a deliberately small host-RAM integration slice.  It consumes
``PersistentState`` values directly and asks ``PersistentHistory`` for exact
membership through :mod:`ugts_go19.persistent_engine`; it never converts a
history root to a flat ``frozenset``.  The implementation is a tree PNS for
1x1 and 2x2 validation fixtures.  It is not production DFPN, a checkpoint
format, or evidence that 19x19 Go is solved.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from time import monotonic
from typing import Any, Iterable

from .constants import BLACK
from .digests import canonical_json_bytes, sha256_hex
from .persistent_engine import (
    PersistentState,
    initial_state,
    ordered_children,
)
from .persistent_history import PersistentHistory
from .rules import Rules
from .score import area_score2, possible_area_score2_bounds


UINT64_MAX = (1 << 64) - 1
INF = UINT64_MAX
INT64_MIN = -(1 << 63)
INT64_MAX = (1 << 63) - 1
PROOF_ARITHMETIC = {
    "bits": 64,
    "endianness": "little",
    "infinity": str(INF),
    "kind": "saturating_uint64",
}
RESULT_FORMAT = "UGTS-PY-PERSISTENT-PNS-BOUNDED-RUN-v1"
TARGET_FORMAT = "UGTS-PY-PERSISTENT-PNS-TARGET-v1"
BUDGET_KIND = "node_expansions"
_TARGET_PROPOSITION = "black_can_force_terminal_score2_at_least_threshold2"


def _decode_canonical_object(
    raw: bytes, *, newline: bool, label: str
) -> dict[str, Any]:
    """Decode an exact canonical JSON object without accepting JSON aliases."""

    if type(raw) is not bytes:
        raise TypeError(f"{label} must be immutable bytes")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> Any:
        raise ValueError(f"non-finite JSON constant: {value}")

    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_constant,
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        ValueError,
    ) as exc:
        raise ValueError(f"{label} is not valid canonical JSON") from exc
    if type(payload) is not dict:
        raise ValueError(f"{label} must be a JSON object")
    expected = canonical_json_bytes(payload) + (b"\n" if newline else b"")
    if expected != raw:
        raise ValueError(f"{label} is not in canonical form")
    return payload


def _require_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != expected:
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


def _require_exact_hex(value: Any, byte_count: int, label: str) -> bytes:
    if type(value) is not str:
        raise ValueError(f"{label} must be lowercase hexadecimal text")
    try:
        raw = bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be lowercase hexadecimal text") from exc
    if len(raw) != byte_count or raw.hex() != value:
        raise ValueError(f"{label} must encode exactly {byte_count} bytes")
    return raw


def _validate_target_payload(payload: dict[str, Any], threshold2: int) -> None:
    """Validate the strict, exact target envelope embedded in each result."""

    _require_keys(
        payload,
        {"format", "proposition", "root_state", "rules"},
        "proof target",
    )
    if payload["format"] != TARGET_FORMAT:
        raise ValueError("unsupported persistent PNS target format")
    proposition = _require_keys(
        payload["proposition"], {"kind", "threshold2"}, "target proposition"
    )
    if proposition["kind"] != _TARGET_PROPOSITION:
        raise ValueError("unknown persistent PNS target proposition")
    if (
        _require_int(
            proposition["threshold2"],
            "target threshold2",
            minimum=INT64_MIN,
            maximum=INT64_MAX,
        )
        != threshold2
    ):
        raise ValueError("result threshold2 does not match its exact target")

    rules_payload = _require_keys(
        payload["rules"],
        {
            "allow_suicide",
            "komi2",
            "passes_to_end",
            "profile_id",
            "scoring",
            "size",
            "superko",
        },
        "target rules",
    )
    rules = Rules.from_dict(rules_payload)
    root_state = _require_keys(
        payload["root_state"],
        {
            "board_hex",
            "history_artifact",
            "passes",
            "ply",
            "previous_board_hex",
            "to_play",
        },
        "target root state",
    )
    board_bytes = rules.size * rules.size
    board = _require_exact_hex(root_state["board_hex"], board_bytes, "root board")
    if any(point not in (0, 1, 2) for point in board):
        raise ValueError("root board contains an invalid point value")
    _require_int(root_state["to_play"], "root to_play", minimum=1, maximum=2)
    _require_int(
        root_state["passes"],
        "root passes",
        minimum=0,
        maximum=rules.passes_to_end,
    )
    _require_int(root_state["ply"], "root ply", minimum=0, maximum=UINT64_MAX)
    previous = root_state["previous_board_hex"]
    if previous is not None:
        previous_raw = _require_exact_hex(previous, board_bytes, "root previous board")
        if any(point not in (0, 1, 2) for point in previous_raw):
            raise ValueError("root previous board contains an invalid point value")

    # The embedded object is the complete canonical artifact emitted by
    # PersistentHistory.serialize_root: exact boards and trie records remain
    # present.  Its hashes are checked here as verification metadata, never as
    # a replacement for that exact content.
    history_artifact = _require_keys(
        root_state["history_artifact"],
        {
            "artifact_sha256",
            "board_bytes",
            "board_record_count",
            "board_size",
            "boards",
            "digest_index",
            "format",
            "member_count",
            "node_record_count",
            "nodes",
            "root_ref",
            "root_sha256",
        },
        "target history artifact",
    )
    if _require_int(history_artifact["board_size"], "history board_size") != rules.size:
        raise ValueError("target history board size does not match the rules")
    if (
        _require_int(history_artifact["board_bytes"], "history board_bytes")
        != board_bytes
    ):
        raise ValueError("target history board width does not match the rules")
    supplied_hash = history_artifact["artifact_sha256"]
    if (
        type(supplied_hash) is not str
        or len(supplied_hash) != 64
        or supplied_hash != supplied_hash.lower()
    ):
        raise ValueError("history artifact hash must be lowercase SHA-256 text")
    try:
        bytes.fromhex(supplied_hash)
    except ValueError as exc:
        raise ValueError(
            "history artifact hash must be lowercase SHA-256 text"
        ) from exc
    unhashed = dict(history_artifact)
    unhashed.pop("artifact_sha256")
    if supplied_hash != sha256_hex(canonical_json_bytes(unhashed)):
        raise ValueError("history artifact content hash mismatch")
    board_records = history_artifact["boards"]
    if type(board_records) is not list:
        raise ValueError("history artifact boards must be an array")
    exact_members: set[bytes] = set()
    for record in board_records:
        record = _require_keys(
            record,
            {"content_sha256", "id", "index_digest", "raw_hex"},
            "history board record",
        )
        exact_members.add(
            _require_exact_hex(record["raw_hex"], board_bytes, "history board")
        )
    if board not in exact_members:
        raise ValueError("target history artifact does not contain the root board")
    if previous is not None and bytes.fromhex(previous) not in exact_members:
        raise ValueError("target history artifact does not contain the previous board")


def _proof_target_bytes(
    rules: Rules,
    threshold2: int,
    state: PersistentState,
    history: PersistentHistory,
) -> bytes:
    serialized_history = history.serialize_root(state.history_root)
    history_payload = _decode_canonical_object(
        serialized_history,
        newline=True,
        label="persistent history artifact",
    )
    payload = {
        "format": TARGET_FORMAT,
        "proposition": {
            "kind": _TARGET_PROPOSITION,
            "threshold2": threshold2,
        },
        "root_state": {
            "board_hex": state.board.hex(),
            "history_artifact": history_payload,
            "passes": state.passes,
            "ply": state.ply,
            "previous_board_hex": (
                None if state.previous_board is None else state.previous_board.hex()
            ),
            "to_play": state.to_play,
        },
        "rules": rules.as_dict(),
    }
    serialized = canonical_json_bytes(payload)
    _validate_target_payload(payload, threshold2)
    return serialized


def _sat_add(values: Iterable[int]) -> int:
    """Add proof numbers with the proof-format's unsigned-64 saturation."""

    total = 0
    for value in values:
        if type(value) is not int or not 0 <= value <= INF:
            raise ValueError("proof number is outside uint64")
        if total > INF - value:
            total = INF
        else:
            total += value
    return total


@dataclass(slots=True)
class PersistentPNSNode:
    """One tree-PNS node retaining its immutable full-history root."""

    state: PersistentState
    parent: "PersistentPNSNode | None" = None
    move: int | None = None
    children: list["PersistentPNSNode"] = field(default_factory=list)
    expanded: bool = False
    proof: int = 1
    disproof: int = 1

    @property
    def is_or(self) -> bool:
        # Proposition: Black can force final score2 >= threshold2.
        return self.state.to_play == BLACK


@dataclass(frozen=True, slots=True)
class PersistentPNSResult:
    """Outcome of one bounded run; never a portable proof certificate."""

    status: str
    threshold2: int
    proof_number: int
    disproof_number: int
    expanded_nodes: int
    generated_nodes: int
    max_ply: int
    elapsed_seconds: float
    expansion_budget: int
    budget_kind: str
    budget_exhausted: bool
    _proof_target_json: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.status) is not str or self.status not in {
            "PROVEN",
            "DISPROVEN",
            "UNKNOWN",
        }:
            raise ValueError("status must be PROVEN, DISPROVEN, or UNKNOWN")
        _require_int(
            self.threshold2,
            "threshold2",
            minimum=INT64_MIN,
            maximum=INT64_MAX,
        )
        _require_int(
            self.proof_number,
            "proof_number",
            minimum=0,
            maximum=(1 << 64) - 1,
        )
        _require_int(
            self.disproof_number,
            "disproof_number",
            minimum=0,
            maximum=(1 << 64) - 1,
        )
        _require_int(
            self.expanded_nodes,
            "expanded_nodes",
            minimum=0,
            maximum=(1 << 64) - 1,
        )
        _require_int(
            self.generated_nodes,
            "generated_nodes",
            minimum=1,
            maximum=(1 << 64) - 1,
        )
        _require_int(self.max_ply, "max_ply", minimum=0, maximum=(1 << 64) - 1)
        if (
            type(self.elapsed_seconds) is not float
            or not math.isfinite(self.elapsed_seconds)
            or self.elapsed_seconds < 0.0
        ):
            raise ValueError("elapsed_seconds must be a finite nonnegative float")
        _require_int(
            self.expansion_budget,
            "expansion_budget",
            minimum=1,
            maximum=(1 << 64) - 1,
        )
        if self.expanded_nodes > self.expansion_budget:
            raise ValueError("expanded_nodes exceeds the expansion budget")
        if type(self.budget_kind) is not str or self.budget_kind != BUDGET_KIND:
            raise ValueError(f"budget_kind must be {BUDGET_KIND!r}")
        if type(self.budget_exhausted) is not bool:
            raise ValueError("budget_exhausted must be boolean")
        if self.status == "PROVEN" and self.proof_number != 0:
            raise ValueError("PROVEN requires a zero proof number")
        if self.status == "DISPROVEN" and self.disproof_number != 0:
            raise ValueError("DISPROVEN requires a zero disproof number")
        if self.status == "UNKNOWN" and (
            self.proof_number == 0 or self.disproof_number == 0
        ):
            raise ValueError("UNKNOWN requires live proof and disproof numbers")
        if self.budget_exhausted and (
            self.status != "UNKNOWN" or self.expanded_nodes != self.expansion_budget
        ):
            raise ValueError(
                "budget_exhausted requires an unresolved target at the exact limit"
            )
        target = _decode_canonical_object(
            self._proof_target_json,
            newline=False,
            label="persistent PNS target",
        )
        _validate_target_payload(target, self.threshold2)

    @property
    def proof_target(self) -> dict[str, Any]:
        """Return a fresh exact target object, including the history artifact."""

        return _decode_canonical_object(
            self._proof_target_json,
            newline=False,
            label="persistent PNS target",
        )

    @property
    def proof_target_sha256(self) -> str:
        """Verification hash accompanying, but never replacing, exact target bytes."""

        return sha256_hex(self._proof_target_json)

    def canonical_proof_target_bytes(self) -> bytes:
        """Return deterministic target bytes independent of run timing."""

        return self._proof_target_json

    def as_dict(self) -> dict[str, object]:
        return {
            "budget_exhausted": self.budget_exhausted,
            "budget_kind": self.budget_kind,
            "disproof_number": self.disproof_number,
            "elapsed_seconds": self.elapsed_seconds,
            "expanded_nodes": self.expanded_nodes,
            "expansion_budget": self.expansion_budget,
            "format": RESULT_FORMAT,
            "generated_nodes": self.generated_nodes,
            "is_portable_proof_certificate": False,
            "max_ply": self.max_ply,
            "proof_arithmetic": dict(PROOF_ARITHMETIC),
            "proof_number": self.proof_number,
            "proof_target": self.proof_target,
            "proof_target_sha256": self.proof_target_sha256,
            "result_kind": "bounded_run_result",
            "scope": "bounded-host-ram-psk-1x1-2x2",
            "status": self.status,
            "threshold2": self.threshold2,
        }


class PersistentProofNumberSearch:
    """Exact bounded PNS using persistent roots instead of flat history sets.

    The search deliberately has no transposition table: every node owns the
    complete proof-authoritative state through its immutable ``history_root``.
    The supplied history store may use an injected index digest; exact board
    bytes still decide positional-superko membership.
    """

    def __init__(
        self,
        rules: Rules,
        threshold2: int,
        history: PersistentHistory,
        node_budget: int = 10_000,
    ) -> None:
        if not isinstance(rules, Rules):
            raise TypeError("rules must be a Rules instance")
        if rules.superko != "positional_superko":
            raise ValueError(
                "persistent proof-number search requires positional superko"
            )
        if rules.size not in (1, 2):
            raise ValueError(
                "bounded persistent proof-number search supports only 1x1 and 2x2"
            )
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
        if type(node_budget) is not int:
            raise TypeError("node_budget must be an integer")
        if node_budget < 1:
            raise ValueError("node_budget must be positive")
        if node_budget > UINT64_MAX:
            raise ValueError("node_budget must fit unsigned 64-bit interchange")

        self.rules = rules
        self.threshold2 = threshold2
        self.history = history
        self.node_budget = node_budget
        self.expanded_nodes = 0
        self.generated_nodes = 1
        self.max_ply = 0
        self._last_root: PersistentPNSNode | None = None

    @property
    def last_root(self) -> PersistentPNSNode | None:
        """Return the most recent in-memory tree root for bounded inspection."""

        return self._last_root

    def _initialize(self, node: PersistentPNSNode) -> None:
        if node.state.is_terminal(self.rules):
            if area_score2(node.state.board, self.rules) >= self.threshold2:
                node.proof, node.disproof = 0, INF
            else:
                node.proof, node.disproof = INF, 0
        else:
            node.proof = node.disproof = 1

    def _recompute(self, node: PersistentPNSNode) -> None:
        if not node.expanded or not node.children:
            self._initialize(node)
            return
        if node.is_or:
            node.proof = min(child.proof for child in node.children)
            node.disproof = _sat_add(child.disproof for child in node.children)
        else:
            node.proof = _sat_add(child.proof for child in node.children)
            node.disproof = min(child.disproof for child in node.children)

    def _select_most_proving(self, root: PersistentPNSNode) -> PersistentPNSNode:
        node = root
        while node.expanded and node.children and node.proof and node.disproof:
            unresolved = [
                child
                for child in node.children
                if child.proof > 0 and child.disproof > 0
            ]
            if not unresolved:
                raise AssertionError("an unresolved parent has no unresolved child")
            if node.is_or:
                node = min(
                    unresolved,
                    key=lambda child: (
                        child.proof,
                        child.disproof,
                        child.move if child.move is not None else -2,
                    ),
                )
            else:
                node = min(
                    unresolved,
                    key=lambda child: (
                        child.disproof,
                        child.proof,
                        child.move if child.move is not None else -2,
                    ),
                )
        return node

    def _expand(self, node: PersistentPNSNode) -> None:
        if node.expanded:
            raise AssertionError("most-proving selection returned an expanded node")
        if node.state.is_terminal(self.rules):
            self._initialize(node)
            node.expanded = True
            return

        children: list[PersistentPNSNode] = []
        for move, child_state, _priority in ordered_children(
            node.state, self.rules, self.history
        ):
            child = PersistentPNSNode(state=child_state, parent=node, move=move)
            self._initialize(child)
            children.append(child)
            self.max_ply = max(self.max_ply, child_state.ply)
        node.children = children
        node.expanded = True
        self.expanded_nodes += 1
        self.generated_nodes += len(children)
        self._recompute(node)

    def _update_ancestors(self, node: PersistentPNSNode) -> None:
        current: PersistentPNSNode | None = node
        while current is not None:
            self._recompute(current)
            current = current.parent

    def run(self, state: PersistentState | None = None) -> PersistentPNSResult:
        """Run until truth is established or the expansion budget is spent."""

        self.expanded_nodes = 0
        self.generated_nodes = 1
        self.max_ply = 0
        root_state = (
            state if state is not None else initial_state(self.rules, self.history)
        )
        if not isinstance(root_state, PersistentState):
            raise TypeError("state must be a PersistentState")
        root_state.validate(self.rules, self.history)
        if root_state.ply > UINT64_MAX:
            raise ValueError("root ply must fit unsigned 64-bit interchange")
        target_json = _proof_target_bytes(
            self.rules,
            self.threshold2,
            root_state,
            self.history,
        )
        root = PersistentPNSNode(state=root_state)
        self._last_root = root
        self._initialize(root)
        start = monotonic()
        root_ply = root.state.ply
        self.max_ply = root_ply

        while root.proof and root.disproof and self.expanded_nodes < self.node_budget:
            leaf = self._select_most_proving(root)
            self._expand(leaf)
            self._update_ancestors(leaf)

        elapsed = monotonic() - start
        if root.proof == 0:
            status = "PROVEN"
        elif root.disproof == 0:
            status = "DISPROVEN"
        else:
            status = "UNKNOWN"
        budget_exhausted = (
            status == "UNKNOWN" and self.expanded_nodes == self.node_budget
        )
        return PersistentPNSResult(
            status=status,
            threshold2=self.threshold2,
            proof_number=root.proof,
            disproof_number=root.disproof,
            expanded_nodes=self.expanded_nodes,
            generated_nodes=self.generated_nodes,
            max_ply=self.max_ply - root_ply,
            elapsed_seconds=elapsed,
            expansion_budget=self.node_budget,
            budget_kind=BUDGET_KIND,
            budget_exhausted=budget_exhausted,
            _proof_target_json=target_json,
        )


__all__ = [
    "BUDGET_KIND",
    "INF",
    "INT64_MAX",
    "INT64_MIN",
    "PROOF_ARITHMETIC",
    "RESULT_FORMAT",
    "TARGET_FORMAT",
    "UINT64_MAX",
    "PersistentPNSNode",
    "PersistentPNSResult",
    "PersistentProofNumberSearch",
]
