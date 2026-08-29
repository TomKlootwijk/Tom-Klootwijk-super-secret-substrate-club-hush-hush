"""History-correct bounded WDL proof search and independent verification.

The module is deliberately conservative:

* WIN is exact only when one legal move reaches an exact child LOSS.
* LOSS is exact only when every legal move reaches an exact child WIN and no
  draw-claim action is available.
* DRAW is exact only when at least one exact draw action exists and every legal
  move has been closed without finding a win.
* A horizon, time limit, node limit, missing child, or heuristic score is
  UNKNOWN.  UNKNOWN is never silently promoted to DRAW.

Claimable FIDE draws are modeled as optional actions.  The normal move remains
available even when the player could instead claim a draw by declaring it.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import time
from typing import Iterable, Mapping

from .game_state import (
    HistoryContext,
    RULE_PROFILE_ID,
    automatic_status,
    current_claim_actions,
    game_state_sha256,
    intended_move_claims,
    validate_history_reachability,
)
from .game_theory import WDL
from .hashing import canonical_json_bytes
from .position import Position
from .rules import apply_move, legal_moves, move_to_san, parse_uci_move

NODE_SCHEMA = "ugts-chess-wdl-node-2.0"
BUNDLE_SCHEMA = "ugts-chess-wdl-certificate-bundle-2.0"
RESULT_SCHEMA = "ugts-chess-bounded-wdl-result-2.0"


def invert_child(value: WDL) -> WDL:
    if value == WDL.WIN:
        return WDL.LOSS
    if value == WDL.LOSS:
        return WDL.WIN
    return value


def _certificate_hash(payload: Mapping[str, object]) -> str:
    clean = dict(payload)
    clean.pop("certificate_hash", None)
    return hashlib.sha256(canonical_json_bytes(clean)).hexdigest()


@dataclass(frozen=True, slots=True)
class ChildObligation:
    """One move or draw-claim action owned by the current player."""

    action_id: str
    kind: str  # move | claim
    move: str | None = None
    san: str | None = None
    claim_code: str | None = None
    child_state_hash: str | None = None
    child_value: WDL = WDL.UNKNOWN
    value_for_parent: WDL = WDL.UNKNOWN
    child_certificate_hash: str | None = None
    exact: bool = False

    def record(self) -> dict[str, object]:
        return {
            "action_id": self.action_id,
            "kind": self.kind,
            "move": self.move,
            "san": self.san,
            "claim_code": self.claim_code,
            "child_state_hash": self.child_state_hash,
            "child_value": self.child_value.value,
            "value_for_parent": self.value_for_parent.value,
            "child_certificate_hash": self.child_certificate_hash,
            "exact": self.exact,
        }


def _canonical_claim_obligation(
    code: str,
    *,
    move: str | None = None,
    san: str | None = None,
) -> ChildObligation:
    suffix = "current" if move is None else move
    return ChildObligation(
        action_id=f"claim:{code}:{suffix}",
        kind="claim",
        move=move,
        san=san,
        claim_code=code,
        child_value=WDL.DRAW,
        value_for_parent=WDL.DRAW,
        exact=True,
    )


@dataclass(frozen=True, slots=True)
class WDLNode:
    state_hash: str
    fen: str
    history_counts: tuple[tuple[str, int], ...]
    depth_remaining: int
    value: WDL
    terminal_code: str
    current_claim_actions: tuple[str, ...]
    legal_move_count: int
    coverage: str  # terminal | witness | complete | cutoff
    children: tuple[ChildObligation, ...]
    exact: bool
    certificate_hash: str

    def record(self) -> dict[str, object]:
        return {
            "schema": NODE_SCHEMA,
            "state_hash": self.state_hash,
            "fen": self.fen,
            "history_counts": [[key, count] for key, count in self.history_counts],
            "depth_remaining": self.depth_remaining,
            "value": self.value.value,
            "terminal_code": self.terminal_code,
            "current_claim_actions": list(self.current_claim_actions),
            "legal_move_count": self.legal_move_count,
            "coverage": self.coverage,
            "children": [child.record() for child in self.children],
            "exact": self.exact,
            "certificate_hash": self.certificate_hash,
        }


@dataclass(frozen=True, slots=True)
class WDLResult:
    root: WDLNode
    nodes: int
    cache_hits: int
    cutoffs: int
    elapsed_seconds: float
    max_plies: int
    node_store: tuple[WDLNode, ...]

    @property
    def completed(self) -> bool:
        return self.root.exact

    def certificate_bundle(self) -> dict[str, object]:
        # Search may explore several losing branches before it discovers the
        # single witness retained by an exact WIN root.  Those abandoned nodes
        # are not certificate evidence and must not be serialized as trusted
        # extras.  Emit exactly the root-reachable closure, failing closed if
        # the in-memory store is duplicate or a retained edge is dangling.
        by_hash: dict[str, WDLNode] = {}
        for node in self.node_store:
            if node.certificate_hash in by_hash:
                raise ValueError("WDL node store contains a duplicate certificate hash")
            by_hash[node.certificate_hash] = node
        if by_hash.get(self.root.certificate_hash) != self.root:
            raise ValueError("WDL root certificate is missing from the node store")

        reachable: set[str] = set()
        active: set[str] = set()
        pending: list[tuple[str, bool]] = [(self.root.certificate_hash, False)]
        while pending:
            certificate_hash, exiting = pending.pop()
            if exiting:
                active.remove(certificate_hash)
                reachable.add(certificate_hash)
                continue
            if certificate_hash in reachable:
                continue
            if certificate_hash in active:
                raise ValueError("cycle in WDL certificate graph")
            node = by_hash.get(certificate_hash)
            if node is None:
                raise ValueError("WDL certificate graph references a missing node")
            active.add(certificate_hash)
            pending.append((certificate_hash, True))
            for child in reversed(node.children):
                child_hash = child.child_certificate_hash
                if child_hash is not None:
                    if child_hash not in by_hash:
                        raise ValueError(
                            "WDL certificate graph references a missing child node"
                        )
                    if child_hash in active:
                        raise ValueError("cycle in WDL certificate graph")
                    if child_hash not in reachable:
                        pending.append((child_hash, False))

        ordered = [by_hash[key] for key in sorted(reachable)]
        return {
            "schema": BUNDLE_SCHEMA,
            "rules_profile": RULE_PROFILE_ID,
            "root_certificate_hash": self.root.certificate_hash,
            "root_state_hash": self.root.state_hash,
            "root_value": self.root.value.value,
            "root_exact": self.root.exact,
            "max_plies": self.max_plies,
            "nodes": [node.record() for node in ordered],
        }

    def record(self) -> dict[str, object]:
        return {
            "schema": RESULT_SCHEMA,
            "root": self.root.record(),
            "nodes_searched": self.nodes,
            "cache_hits": self.cache_hits,
            "cutoffs": self.cutoffs,
            "elapsed_seconds": self.elapsed_seconds,
            "completed": self.completed,
            "max_plies": self.max_plies,
            "certificate_bundle": self.certificate_bundle(),
        }


class BoundedWDLSolver:
    """Deterministic depth-bounded proof search.

    The solver is not a strength engine.  It emits a content-addressed proof
    graph, and returns UNKNOWN whenever a proof obligation remains open.
    """

    def __init__(self, *, node_budget: int = 1_000_000, time_limit: float | None = None) -> None:
        self.node_budget = max(1, int(node_budget))
        self.time_limit = time_limit
        self.nodes = 0
        self.cache_hits = 0
        self.cutoffs = 0
        self.deadline: float | None = None
        self.cache: dict[tuple[str, int], WDLNode] = {}
        self.store: dict[str, WDLNode] = {}

    def _budget_available(self) -> bool:
        if self.nodes >= self.node_budget:
            return False
        if self.deadline is not None and time.monotonic() >= self.deadline:
            return False
        return True

    def _register(self, node: WDLNode) -> WDLNode:
        self.store[node.certificate_hash] = node
        return node

    def _make_node(
        self,
        *,
        position: Position,
        history: HistoryContext,
        depth: int,
        value: WDL,
        terminal_code: str,
        current_claims: tuple[str, ...],
        legal_move_count: int,
        coverage: str,
        children: Iterable[ChildObligation],
        exact: bool,
    ) -> WDLNode:
        child_tuple = tuple(children)
        payload: dict[str, object] = {
            "schema": NODE_SCHEMA,
            "state_hash": game_state_sha256(position, history),
            "fen": position.to_fen(),
            "history_counts": history.record(),
            "depth_remaining": depth,
            "value": value.value,
            "terminal_code": terminal_code,
            "current_claim_actions": list(current_claims),
            "legal_move_count": legal_move_count,
            "coverage": coverage,
            "children": [child.record() for child in child_tuple],
            "exact": exact,
        }
        cert_hash = _certificate_hash(payload)
        return self._register(
            WDLNode(
                state_hash=str(payload["state_hash"]),
                fen=position.to_fen(),
                history_counts=history.counts,
                depth_remaining=depth,
                value=value,
                terminal_code=terminal_code,
                current_claim_actions=current_claims,
                legal_move_count=legal_move_count,
                coverage=coverage,
                children=child_tuple,
                exact=exact,
                certificate_hash=cert_hash,
            )
        )

    @staticmethod
    def _claim_obligation(code: str, *, move: str | None = None, san: str | None = None) -> ChildObligation:
        return _canonical_claim_obligation(code, move=move, san=san)

    def _cutoff_node(
        self,
        position: Position,
        history: HistoryContext,
        depth: int,
        code: str,
        claims: tuple[str, ...] | None = None,
        legal_count: int | None = None,
    ) -> WDLNode:
        self.cutoffs += 1
        if claims is None:
            claims = current_claim_actions(position, history)
        if legal_count is None:
            legal_count = len(legal_moves(position))
        children = tuple(self._claim_obligation(code_) for code_ in claims)
        return self._make_node(
            position=position,
            history=history,
            depth=depth,
            value=WDL.UNKNOWN,
            terminal_code=code,
            current_claims=claims,
            legal_move_count=legal_count,
            coverage="cutoff",
            children=children,
            exact=False,
        )

    def _solve(self, position: Position, history: HistoryContext, depth: int) -> WDLNode:
        state_hash = game_state_sha256(position, history)
        cache_key = (state_hash, depth)
        cached = self.cache.get(cache_key)
        if cached is not None:
            self.cache_hits += 1
            return cached

        if not self._budget_available():
            return self._cutoff_node(position, history, depth, "budget_cutoff")
        self.nodes += 1

        moves = sorted(legal_moves(position), key=lambda move: move.uci())
        automatic = automatic_status(position, history)
        claims = current_claim_actions(position, history)
        if automatic.terminal:
            value = WDL.LOSS if automatic.code == "checkmate" else WDL.DRAW
            node = self._make_node(
                position=position,
                history=history,
                depth=depth,
                value=value,
                terminal_code=automatic.code,
                current_claims=claims,
                legal_move_count=0,
                coverage="terminal",
                children=(),
                exact=True,
            )
            self.cache[cache_key] = node
            return node

        if depth <= 0:
            node = self._cutoff_node(position, history, depth, "ply_horizon", claims, len(moves))
            self.cache[cache_key] = node
            return node

        obligations: list[ChildObligation] = [self._claim_obligation(code) for code in claims]
        move_values: list[WDL] = []
        all_move_children_exact = True

        for move in moves:
            child = apply_move(position, move)
            child_history = history.push(child)
            san = move_to_san(position, move)

            # A correct pre-move claim is a separate draw action.  The ordinary
            # move remains available and must still be explored.
            for code in intended_move_claims(child, child_history):
                obligations.append(self._claim_obligation(code, move=move.uci(), san=san))

            child_node = self._solve(child, child_history, depth - 1)
            converted = invert_child(child_node.value)
            move_values.append(converted)
            all_move_children_exact = all_move_children_exact and child_node.exact
            obligation = ChildObligation(
                action_id=f"move:{move.uci()}",
                kind="move",
                move=move.uci(),
                san=san,
                child_state_hash=child_node.state_hash,
                child_value=child_node.value,
                value_for_parent=converted,
                child_certificate_hash=child_node.certificate_hash,
                exact=child_node.exact,
            )
            obligations.append(obligation)

            if child_node.exact and converted == WDL.WIN:
                node = self._make_node(
                    position=position,
                    history=history,
                    depth=depth,
                    value=WDL.WIN,
                    terminal_code="winning_move_witness",
                    current_claims=claims,
                    legal_move_count=len(moves),
                    coverage="witness",
                    children=(obligation,),
                    exact=True,
                )
                self.cache[cache_key] = node
                return node

        has_draw_action = any(item.kind == "claim" for item in obligations) or any(
            value == WDL.DRAW for value in move_values
        )
        if all_move_children_exact and move_values and all(value == WDL.LOSS for value in move_values) and not has_draw_action:
            value = WDL.LOSS
            code = "all_legal_moves_lose"
            exact = True
        elif all_move_children_exact and move_values and not any(value == WDL.WIN for value in move_values) and has_draw_action:
            value = WDL.DRAW
            code = "draw_action_and_no_winning_move"
            exact = True
        else:
            value = WDL.UNKNOWN
            code = "open_proof_obligation"
            exact = False

        node = self._make_node(
            position=position,
            history=history,
            depth=depth,
            value=value,
            terminal_code=code,
            current_claims=claims,
            legal_move_count=len(moves),
            coverage="complete" if all_move_children_exact else "cutoff",
            children=obligations,
            exact=exact,
        )
        self.cache[cache_key] = node
        return node

    def solve(
        self,
        position: Position,
        *,
        max_plies: int,
        history: HistoryContext | None = None,
    ) -> WDLResult:
        if max_plies < 0:
            raise ValueError("max_plies must be non-negative")
        if history is not None and not isinstance(history, HistoryContext):
            raise TypeError("history must be a HistoryContext")
        root_history = HistoryContext.initial(position) if history is None else history
        canonical_history = _history_from_record(root_history.record())
        if canonical_history != root_history:
            raise ValueError("history context is not canonical")
        validate_history_reachability(position, root_history)
        self.nodes = 0
        self.cache_hits = 0
        self.cutoffs = 0
        self.cache.clear()
        self.store.clear()
        self.deadline = None if self.time_limit is None else time.monotonic() + max(0.001, self.time_limit)
        start = time.monotonic()
        root = self._solve(position, root_history, max_plies)
        return WDLResult(
            root=root,
            nodes=self.nodes,
            cache_hits=self.cache_hits,
            cutoffs=self.cutoffs,
            elapsed_seconds=time.monotonic() - start,
            max_plies=max_plies,
            node_store=tuple(self.store.values()),
        )


class WDLVerificationError(ValueError):
    pass


def _history_from_record(record: object) -> HistoryContext:
    if not isinstance(record, list):
        raise WDLVerificationError("history_counts must be a list")
    pairs: list[tuple[str, int]] = []
    for item in record:
        if not isinstance(item, list) or len(item) != 2 or not isinstance(item[0], str):
            raise WDLVerificationError("malformed history count entry")
        if len(item[0]) != 64 or any(character not in "0123456789abcdef" for character in item[0]):
            raise WDLVerificationError("history repetition key must be a lowercase SHA-256 digest")
        count = item[1]
        if isinstance(count, bool) or not isinstance(count, int):
            raise WDLVerificationError("history occurrence count must be an integer")
        if count <= 0 or count > 5:
            raise WDLVerificationError("history occurrence count must be in 1..5")
        pairs.append((item[0], count))
    if pairs != sorted(pairs) or len({key for key, _ in pairs}) != len(pairs):
        raise WDLVerificationError("history counts must be unique and sorted")
    return HistoryContext(tuple(pairs))


def verify_wdl_certificate(bundle: Mapping[str, object], *, allow_unknown_root: bool = True) -> dict[str, object]:
    """Independently verify a bounded WDL certificate bundle.

    The verifier recomputes legal moves, repetition state, claim actions,
    child transitions, WDL aggregation, and every content hash.  A structurally
    valid UNKNOWN bundle may be accepted for checkpointing when
    ``allow_unknown_root`` is true, but it is never reported as a solve.
    """

    if bundle.get("schema") != BUNDLE_SCHEMA:
        raise WDLVerificationError("unsupported WDL bundle schema")
    if bundle.get("rules_profile") != RULE_PROFILE_ID:
        raise WDLVerificationError("unsupported WDL rules profile")
    max_plies = bundle.get("max_plies")
    if isinstance(max_plies, bool) or not isinstance(max_plies, int) or max_plies < 0:
        raise WDLVerificationError("bundle max_plies must be a non-negative integer")
    raw_nodes = bundle.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise WDLVerificationError("bundle contains no nodes")

    store: dict[str, Mapping[str, object]] = {}
    for raw in raw_nodes:
        if not isinstance(raw, Mapping):
            raise WDLVerificationError("node record is not an object")
        if raw.get("schema") != NODE_SCHEMA:
            raise WDLVerificationError("unsupported node schema")
        cert_hash = raw.get("certificate_hash")
        if not isinstance(cert_hash, str) or len(cert_hash) != 64:
            raise WDLVerificationError("invalid node certificate hash")
        expected = _certificate_hash(raw)
        if cert_hash != expected:
            raise WDLVerificationError(f"node certificate hash mismatch: {cert_hash}")
        if cert_hash in store:
            raise WDLVerificationError("duplicate node certificate hash")
        store[cert_hash] = raw

    root_hash = bundle.get("root_certificate_hash")
    if not isinstance(root_hash, str) or root_hash not in store:
        raise WDLVerificationError("root certificate is missing")

    active: set[str] = set()
    verified: set[str] = set()
    exact_count = 0
    unknown_count = 0

    def verify_node(cert_hash: str) -> WDL:
        nonlocal exact_count, unknown_count
        if cert_hash in verified:
            return WDL(str(store[cert_hash]["value"]))
        if cert_hash in active:
            raise WDLVerificationError("cycle in depth-bounded certificate graph")
        active.add(cert_hash)
        record = store[cert_hash]

        try:
            position = Position.from_fen(str(record["fen"]))
            history = _history_from_record(record["history_counts"])
            depth_remaining = record["depth_remaining"]
            if isinstance(depth_remaining, bool) or not isinstance(depth_remaining, int) or depth_remaining < 0:
                raise ValueError("depth_remaining must be a non-negative integer")
            value = WDL(str(record["value"]))
            exact_value = record["exact"]
            if not isinstance(exact_value, bool):
                raise ValueError("exact must be a boolean")
            exact = exact_value
            legal_count_value = record["legal_move_count"]
            if isinstance(legal_count_value, bool) or not isinstance(legal_count_value, int):
                raise ValueError("legal_move_count must be an integer")
            legal_count = legal_count_value
            coverage = str(record["coverage"])
        except (KeyError, TypeError, ValueError) as exc:
            raise WDLVerificationError(f"malformed node {cert_hash}: {exc}") from exc

        expected_state_hash = game_state_sha256(position, history)
        if record.get("state_hash") != expected_state_hash:
            raise WDLVerificationError(f"state hash mismatch in node {cert_hash}")
        try:
            validate_history_reachability(position, history)
        except ValueError as exc:
            raise WDLVerificationError(str(exc)) from exc

        moves = sorted(legal_moves(position), key=lambda move: move.uci())
        automatic = automatic_status(position, history)
        claims = current_claim_actions(position, history)
        if record.get("current_claim_actions") != list(claims):
            raise WDLVerificationError("current claim-action list mismatch")
        if legal_count != (0 if automatic.terminal else len(moves)):
            raise WDLVerificationError("legal move count mismatch")

        raw_children = record.get("children")
        if not isinstance(raw_children, list):
            raise WDLVerificationError("children must be a list")

        if automatic.terminal:
            expected_value = WDL.LOSS if automatic.code == "checkmate" else WDL.DRAW
            if not exact or coverage != "terminal" or raw_children or value != expected_value:
                raise WDLVerificationError("invalid terminal WDL node")
            if record.get("terminal_code") != automatic.code:
                raise WDLVerificationError("terminal reason mismatch")
            exact_count += 1
            active.remove(cert_hash)
            verified.add(cert_hash)
            return value

        move_records: dict[str, Mapping[str, object]] = {}
        supplied_claim_records: list[dict[str, object]] = []
        action_ids: set[str] = set()
        for child in raw_children:
            if not isinstance(child, Mapping):
                raise WDLVerificationError("malformed child obligation")
            action_id = child.get("action_id")
            if not isinstance(action_id, str) or action_id in action_ids:
                raise WDLVerificationError("duplicate or invalid action id")
            action_ids.add(action_id)
            kind = child.get("kind")
            if kind == "claim":
                code = child.get("claim_code")
                move_text = child.get("move")
                if not isinstance(code, str) or (move_text is not None and not isinstance(move_text, str)):
                    raise WDLVerificationError("malformed claim action")
                if (
                    child.get("child_value") != WDL.DRAW.value
                    or child.get("value_for_parent") != WDL.DRAW.value
                    or child.get("exact") is not True
                ):
                    raise WDLVerificationError("claim action must be an exact draw")
                supplied_claim_records.append(dict(child))
            elif kind == "move":
                move_text = child.get("move")
                if not isinstance(move_text, str) or move_text in move_records:
                    raise WDLVerificationError("duplicate or malformed move action")
                move_records[move_text] = child
            else:
                raise WDLVerificationError("unknown child action kind")

        expected_claim_records = [
            _canonical_claim_obligation(code).record() for code in claims
        ]
        by_uci = {move.uci(): move for move in moves}
        for move in moves:
            child_position = apply_move(position, move)
            child_history = history.push(child_position)
            san = move_to_san(position, move)
            for code in intended_move_claims(child_position, child_history):
                expected_claim_records.append(
                    _canonical_claim_obligation(
                        code,
                        move=move.uci(),
                        san=san,
                    ).record()
                )

        expected_claims_by_id = {
            str(record["action_id"]): record for record in expected_claim_records
        }

        def verify_claim_records(*, complete: bool) -> None:
            expected_indices: list[int] = []
            for supplied in supplied_claim_records:
                action_id = supplied.get("action_id")
                expected = expected_claims_by_id.get(str(action_id))
                if expected is None or supplied != expected:
                    raise WDLVerificationError(
                        "claim action does not match its canonical record"
                    )
                expected_indices.append(expected_claim_records.index(expected))
            if expected_indices != sorted(expected_indices):
                raise WDLVerificationError("claim actions are not in canonical order")
            if complete and supplied_claim_records != expected_claim_records:
                raise WDLVerificationError("claim-action coverage mismatch")

        def verify_move_record(move_text: str, child_record: Mapping[str, object]) -> WDL:
            if move_text not in by_uci:
                raise WDLVerificationError(f"illegal move obligation {move_text}")
            move = parse_uci_move(position, move_text)
            child_position = apply_move(position, move)
            child_history = history.push(child_position)
            child_cert = child_record.get("child_certificate_hash")
            if not isinstance(child_cert, str) or child_cert not in store:
                raise WDLVerificationError("move obligation references a missing child certificate")
            child_value = verify_node(child_cert)
            child_node = store[child_cert]
            if depth_remaining <= 0 or child_node.get("depth_remaining") != depth_remaining - 1:
                raise WDLVerificationError("child certificate depth does not decrement by one ply")
            if child_node.get("fen") != child_position.to_fen():
                raise WDLVerificationError("child FEN mismatch")
            if child_node.get("history_counts") != child_history.record():
                raise WDLVerificationError("child history mismatch")
            if child_record.get("child_state_hash") != game_state_sha256(child_position, child_history):
                raise WDLVerificationError("child state-hash mismatch")
            if child_record.get("child_value") != child_value.value:
                raise WDLVerificationError("declared child WDL mismatch")
            converted = invert_child(child_value)
            if child_record.get("value_for_parent") != converted.value:
                raise WDLVerificationError("parent-converted WDL mismatch")
            if not isinstance(child_record.get("exact"), bool):
                raise WDLVerificationError("child exactness must be a boolean")
            if child_record.get("exact") != child_node.get("exact"):
                raise WDLVerificationError("child exactness mismatch")
            return converted

        derived = WDL.UNKNOWN
        if exact:
            if value == WDL.WIN:
                if coverage != "witness" or len(move_records) != 1:
                    raise WDLVerificationError("WIN certificate must contain one move witness")
                if supplied_claim_records:
                    raise WDLVerificationError(
                        "WIN witness coverage must not contain claim-action records"
                    )
                converted = verify_move_record(*next(iter(move_records.items())))
                if converted != WDL.WIN:
                    raise WDLVerificationError("WIN witness does not reach an exact child LOSS")
                derived = WDL.WIN
            else:
                if coverage != "complete" or set(move_records) != set(by_uci):
                    raise WDLVerificationError("LOSS/DRAW certificate lacks complete legal-move coverage")
                verify_claim_records(complete=True)
                values = [verify_move_record(move_text, move_records[move_text]) for move_text in sorted(move_records)]
                if any(item == WDL.UNKNOWN for item in values):
                    raise WDLVerificationError("exact certificate references an unknown child")
                has_draw = bool(expected_claim_records) or any(item == WDL.DRAW for item in values)
                if values and all(item == WDL.LOSS for item in values) and not has_draw:
                    derived = WDL.LOSS
                elif values and not any(item == WDL.WIN for item in values) and has_draw:
                    derived = WDL.DRAW
                else:
                    derived = WDL.UNKNOWN
                if value != derived or value == WDL.UNKNOWN:
                    raise WDLVerificationError("complete WDL aggregation does not match the node value")
            exact_count += 1
        else:
            if value != WDL.UNKNOWN or coverage not in ("cutoff", "complete"):
                raise WDLVerificationError("non-exact node must be an UNKNOWN cutoff/open obligation")
            # Referenced children still have to be valid.  Sparse cutoff nodes are
            # allowed, but any supplied move must be legal and internally sound.
            for move_text, child_record in move_records.items():
                verify_move_record(move_text, child_record)
            verify_claim_records(complete=False)
            unknown_count += 1

        active.remove(cert_hash)
        verified.add(cert_hash)
        return value

    root_value = verify_node(root_hash)
    root_record = store[root_hash]
    if root_record.get("depth_remaining") != max_plies:
        raise WDLVerificationError("bundle max_plies does not match root depth")
    root_exact = root_record["exact"]
    if not root_exact and not allow_unknown_root:
        raise WDLVerificationError("root is UNKNOWN, not a completed proof")
    if bundle.get("root_state_hash") != root_record.get("state_hash"):
        raise WDLVerificationError("bundle root-state hash mismatch")
    if not isinstance(bundle.get("root_exact"), bool):
        raise WDLVerificationError("bundle root_exact must be a boolean")
    if bundle.get("root_value") != root_value.value or bundle.get("root_exact") != root_exact:
        raise WDLVerificationError("bundle root summary mismatch")

    return {
        "valid": True,
        "root_value": root_value.value,
        "root_exact": root_exact,
        "verified_reachable_nodes": len(verified),
        "exact_nodes": exact_count,
        "unknown_nodes": unknown_count,
        "unreferenced_nodes": len(store) - len(verified),
        "root_certificate_hash": root_hash,
    }
