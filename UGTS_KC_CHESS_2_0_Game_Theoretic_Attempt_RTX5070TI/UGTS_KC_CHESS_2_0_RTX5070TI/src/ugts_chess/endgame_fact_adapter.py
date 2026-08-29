"""Proof-preserving KQK/KRK tablebase adapter for v2 WDL facts.

The bundled retrograde tables are useful search indexes, but a bare probe is
not journal authority: it omits the exact history and the FIDE 50/75-move and
repetition actions represented by :mod:`ugts_chess.game_state`.  This adapter
uses a probe only to choose a deterministic bounded-search horizon.  A fact is
appended only after the ordinary history-aware WDL solver emits a canonical
exact certificate, that certificate independently verifies, and its root is
bound field-by-field to the exact ProofDAG node.  ``WDLFactJournal`` then
performs its own independent replay before committing the seed.

This is intentionally conservative.  KQK/KRK wins and losses with short DTM
often yield small certificates.  Tablebase draws are cyclic and the current
certificate language has no tablebase-lemma or cycle rule, so most nonterminal
draw probes remain UNKNOWN within practical bounds.  The adapter never turns
that resource limitation into a draw fact.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
from importlib import resources
import json
from pathlib import Path

from .constants import color_name
from .game_state import (
    RULE_PROFILE_ID,
    automatic_status,
    current_claim_actions,
    game_state_sha256,
    validate_history_reachability,
)
from .game_theory import WDL
from .hashing import canonical_json_bytes
from .proof_dag import DAGNode, ProofDAG, node_identity_sha256
from .tablebase import (
    ADDRESS_COUNT,
    KXKTablebase,
    TablebaseProbe,
    encode_state,
    normalize_kxk_position,
)
from .verified_overlay import MAX_CERTIFICATE_BYTES
from .wdl import BoundedWDLSolver, WDLResult, verify_wdl_certificate
from .wdl_fact_journal import (
    FactEntry,
    WDLFactConflictError,
    WDLFactJournal,
)


ENDGAME_FACT_RESULT_SCHEMA = "ugts-chess-endgame-fact-adapter-result-1.0"
TABLEBASE_SCHEMA = "ugts-kc-chess-kxk-tablebase-1.0"
DEFAULT_NODE_BUDGET = 250_000
DEFAULT_MAX_PLIES = 32
DEFAULT_MAX_CERTIFICATE_BYTES = 64 * 1024 * 1024
MAX_NODE_BUDGET = 2_000_000
MAX_PLIES = 128


class EndgameFactAdapterError(Exception):
    """Base error for invalid adapter use or an internal invariant failure."""


class EndgameTablebaseError(EndgameFactAdapterError):
    """Raised internally when a bundled tablebase fails transport validation."""


def _require_positive_int(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _require_nonnegative_int(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


@dataclass(frozen=True, slots=True)
class EndgameFactLimits:
    """Deterministic certificate-generation limits.

    No wall-clock cutoff is used: the node budget and ply horizon give the
    same cutoff boundary for the same code and inputs.
    """

    node_budget: int = DEFAULT_NODE_BUDGET
    max_plies: int = DEFAULT_MAX_PLIES
    max_certificate_bytes: int = DEFAULT_MAX_CERTIFICATE_BYTES

    def __post_init__(self) -> None:
        budget = _require_positive_int(self.node_budget, label="node_budget")
        if budget > MAX_NODE_BUDGET:
            raise ValueError(f"node_budget exceeds adapter maximum {MAX_NODE_BUDGET}")
        plies = _require_nonnegative_int(self.max_plies, label="max_plies")
        if plies > MAX_PLIES:
            raise ValueError(f"max_plies exceeds adapter maximum {MAX_PLIES}")
        size = _require_positive_int(
            self.max_certificate_bytes,
            label="max_certificate_bytes",
        )
        if size > MAX_CERTIFICATE_BYTES:
            raise ValueError(
                "max_certificate_bytes exceeds the journal certificate maximum"
            )


@dataclass(frozen=True, slots=True)
class EndgameFactResult:
    """Structured exact promotion, idempotent hit, or conservative UNKNOWN."""

    node_sha256: str
    status: str  # promoted | already_verified | unknown
    value: WDL
    reason: str
    detail: str
    promoted: bool
    material: str | None = None
    automatic_code: str | None = None
    current_claim_actions: tuple[str, ...] = ()
    tablebase_outcome: str | None = None
    tablebase_dtm_plies: int | None = None
    tablebase_key: int | None = None
    tablebase_transport_sha256: str | None = None
    search_max_plies: int | None = None
    node_budget: int | None = None
    nodes_searched: int | None = None
    cache_hits: int | None = None
    cutoffs: int | None = None
    certificate_size: int | None = None
    certificate_sha256: str | None = None
    root_certificate_hash: str | None = None
    fact_record_index: int | None = None
    fact_content_sha256: str | None = None
    fact_evidence_sha256: str | None = None
    proof_height: int | None = None

    @property
    def exact(self) -> bool:
        return self.value != WDL.UNKNOWN

    def record(self) -> dict[str, object]:
        return {
            "schema": ENDGAME_FACT_RESULT_SCHEMA,
            "node_sha256": self.node_sha256,
            "status": self.status,
            "value": self.value.value,
            "reason": self.reason,
            "detail": self.detail,
            "promoted": self.promoted,
            "material": self.material,
            "automatic_code": self.automatic_code,
            "current_claim_actions": list(self.current_claim_actions),
            "tablebase_outcome": self.tablebase_outcome,
            "tablebase_dtm_plies": self.tablebase_dtm_plies,
            "tablebase_key": self.tablebase_key,
            "tablebase_transport_sha256": self.tablebase_transport_sha256,
            "search_max_plies": self.search_max_plies,
            "node_budget": self.node_budget,
            "nodes_searched": self.nodes_searched,
            "cache_hits": self.cache_hits,
            "cutoffs": self.cutoffs,
            "certificate_size": self.certificate_size,
            "certificate_sha256": self.certificate_sha256,
            "root_certificate_hash": self.root_certificate_hash,
            "fact_record_index": self.fact_record_index,
            "fact_content_sha256": self.fact_content_sha256,
            "fact_evidence_sha256": self.fact_evidence_sha256,
            "proof_height": self.proof_height,
        }


@dataclass(frozen=True, slots=True)
class _LoadedTablebase:
    tablebase: KXKTablebase
    transport_sha256: str


def _material_piece(node: DAGNode) -> str | None:
    for piece in ("Q", "R"):
        if normalize_kxk_position(node.position, piece) is not None:
            return piece
    return None


@lru_cache(maxsize=2)
def _load_bundled_tablebase(piece: str) -> _LoadedTablebase:
    piece = piece.upper()
    if piece not in ("Q", "R"):
        raise ValueError("piece must be Q or R")
    resource_name = "kqk.tb.gz" if piece == "Q" else "krk.tb.gz"
    package = resources.files("ugts_chess.resources")
    reference = package.joinpath(resource_name)
    metadata_reference = package.joinpath(resource_name.removesuffix(".gz") + ".json")
    try:
        decoded_metadata = json.loads(metadata_reference.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EndgameTablebaseError(
            f"bundled K{piece}K metadata cannot be decoded: {exc}"
        ) from exc
    if not isinstance(decoded_metadata, dict):
        raise EndgameTablebaseError("bundled tablebase metadata is not an object")
    with resources.as_file(reference) as materialized:
        path = Path(materialized)
        transport = path.read_bytes()
        transport_sha256 = hashlib.sha256(transport).hexdigest()
        loaded = KXKTablebase.load(path)
    tablebase = KXKTablebase(
        loaded.piece,
        loaded.outcomes,
        loaded.dtm,
        decoded_metadata,
    )

    metadata = tablebase.metadata
    expected = {
        "schema": TABLEBASE_SCHEMA,
        "piece": piece,
        "material": f"K{piece}K",
        "address_count": ADDRESS_COUNT,
        "sha256": transport_sha256,
    }
    for key, value in expected.items():
        if metadata.get(key) != value:
            raise EndgameTablebaseError(
                f"bundled K{piece}K metadata field {key!r} does not match transport"
            )
    if tablebase.piece != piece:
        raise EndgameTablebaseError("bundled tablebase piece code is inconsistent")
    if len(tablebase.outcomes) != ADDRESS_COUNT or len(tablebase.dtm) != ADDRESS_COUNT:
        raise EndgameTablebaseError("bundled tablebase payload has the wrong size")
    maximum = metadata.get("max_dtm_plies")
    if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 0:
        raise EndgameTablebaseError("bundled tablebase maximum DTM is invalid")
    return _LoadedTablebase(tablebase, transport_sha256)


def _probe_is_strict(probe: object, node: DAGNode, piece: str) -> bool:
    if not isinstance(probe, TablebaseProbe):
        return False
    normalized = normalize_kxk_position(node.position, piece)
    if normalized is None:
        return False
    strong_king, strong_piece, weak_king, side, strong_color = normalized
    expected_key = encode_state(strong_king, strong_piece, weak_king, side)
    if (
        probe.material != f"K{piece}K"
        or probe.outcome not in {"win", "loss", "draw"}
        or probe.side_to_move != color_name(node.position.turn)
        or probe.strong_side != color_name(strong_color)
        or not probe.exact
        or isinstance(probe.key, bool)
        or not isinstance(probe.key, int)
        or probe.key != expected_key
    ):
        return False
    if probe.outcome in {"win", "loss"}:
        return (
            not isinstance(probe.dtm_plies, bool)
            and isinstance(probe.dtm_plies, int)
            and probe.dtm_plies >= 0
        )
    return probe.dtm_plies is None


def _exact_node(dag: ProofDAG, node_sha256: str) -> DAGNode:
    node = dag.get_node(node_sha256)
    if node is None:
        raise ValueError("unknown ProofDAG node")
    if node.rule_profile_id != RULE_PROFILE_ID or node.wdl != WDL.UNKNOWN:
        raise EndgameFactAdapterError("target DAG node is not canonical UNKNOWN")
    validate_history_reachability(node.position, node.history)
    if node.position.to_fen() != node.fen:
        raise EndgameFactAdapterError("target node FEN is not canonical")
    if game_state_sha256(node.position, node.history) != node.game_state_sha256:
        raise EndgameFactAdapterError("target node game-state identity is inconsistent")
    if (
        node_identity_sha256(
            node.position,
            node.history,
            rule_profile_id=node.rule_profile_id,
        )
        != node.node_sha256
    ):
        raise EndgameFactAdapterError("target node full identity is inconsistent")
    return node


def _unknown(
    node: DAGNode,
    *,
    reason: str,
    detail: str,
    material: str | None,
    automatic_code: str | None = None,
    claims: tuple[str, ...] = (),
    probe: TablebaseProbe | None = None,
    transport_sha256: str | None = None,
    search_max_plies: int | None = None,
    limits: EndgameFactLimits | None = None,
    search: WDLResult | None = None,
    certificate_bytes: bytes | None = None,
) -> EndgameFactResult:
    return EndgameFactResult(
        node_sha256=node.node_sha256,
        status="unknown",
        value=WDL.UNKNOWN,
        reason=reason,
        detail=detail,
        promoted=False,
        material=material,
        automatic_code=automatic_code,
        current_claim_actions=claims,
        tablebase_outcome=None if probe is None else probe.outcome,
        tablebase_dtm_plies=None if probe is None else probe.dtm_plies,
        tablebase_key=None if probe is None else probe.key,
        tablebase_transport_sha256=transport_sha256,
        search_max_plies=search_max_plies,
        node_budget=None if limits is None else limits.node_budget,
        nodes_searched=None if search is None else search.nodes,
        cache_hits=None if search is None else search.cache_hits,
        cutoffs=None if search is None else search.cutoffs,
        certificate_size=None if certificate_bytes is None else len(certificate_bytes),
        certificate_sha256=(
            None
            if certificate_bytes is None
            else hashlib.sha256(certificate_bytes).hexdigest()
        ),
    )


def _from_entry(
    entry: FactEntry,
    *,
    appended: bool,
    reason: str,
    detail: str,
    material: str | None,
    automatic_code: str | None,
    claims: tuple[str, ...],
    probe: TablebaseProbe | None = None,
    transport_sha256: str | None = None,
    search_max_plies: int | None = None,
    limits: EndgameFactLimits | None = None,
    search: WDLResult | None = None,
    certificate_bytes: bytes | None = None,
    root_certificate_hash: str | None = None,
) -> EndgameFactResult:
    fact = entry.fact
    seed_bytes = certificate_bytes
    if seed_bytes is None:
        seed_bytes = fact.seed_certificate_bytes
    return EndgameFactResult(
        node_sha256=fact.node_sha256,
        status="promoted" if appended else "already_verified",
        value=fact.claimed_wdl,
        reason=reason,
        detail=detail,
        promoted=appended,
        material=material,
        automatic_code=automatic_code,
        current_claim_actions=claims,
        tablebase_outcome=None if probe is None else probe.outcome,
        tablebase_dtm_plies=None if probe is None else probe.dtm_plies,
        tablebase_key=None if probe is None else probe.key,
        tablebase_transport_sha256=transport_sha256,
        search_max_plies=search_max_plies,
        node_budget=None if limits is None else limits.node_budget,
        nodes_searched=None if search is None else search.nodes,
        cache_hits=None if search is None else search.cache_hits,
        cutoffs=None if search is None else search.cutoffs,
        certificate_size=None if seed_bytes is None else len(seed_bytes),
        certificate_sha256=(
            None if seed_bytes is None else hashlib.sha256(seed_bytes).hexdigest()
        ),
        root_certificate_hash=root_certificate_hash,
        fact_record_index=entry.record_index,
        fact_content_sha256=entry.content_sha256,
        fact_evidence_sha256=fact.evidence_sha256,
        proof_height=fact.proof_height,
    )


def _bind_verified_bundle(
    node: DAGNode,
    bundle: dict[str, object],
    verification: dict[str, object],
) -> str:
    if verification.get("valid") is not True or verification.get("root_exact") is not True:
        raise ValueError("bounded certificate verifier did not accept an exact root")
    if verification.get("unreferenced_nodes") != 0:
        raise ValueError("bounded certificate contains unreferenced nodes")
    root_hash = verification.get("root_certificate_hash")
    if not isinstance(root_hash, str) or len(root_hash) != 64:
        raise ValueError("bounded certificate verifier returned an invalid root hash")
    nodes = bundle.get("nodes")
    if not isinstance(nodes, list):
        raise ValueError("bounded certificate contains no node list")
    roots = [
        candidate
        for candidate in nodes
        if isinstance(candidate, dict)
        and candidate.get("certificate_hash") == root_hash
    ]
    if len(roots) != 1:
        raise ValueError("bounded certificate root is missing or ambiguous")
    root = roots[0]
    checks = {
        "fen": node.fen,
        "history_counts": node.history.record(),
        "state_hash": node.game_state_sha256,
        "exact": True,
        "value": verification.get("root_value"),
    }
    for key, value in checks.items():
        if root.get(key) != value:
            raise ValueError(f"bounded certificate root {key} does not match DAG node")
    if bundle.get("rules_profile") != node.rule_profile_id:
        raise ValueError("bounded certificate rule profile does not match DAG node")
    if bundle.get("root_state_hash") != node.game_state_sha256:
        raise ValueError("bounded certificate summary state does not match DAG node")
    if bundle.get("root_certificate_hash") != root_hash:
        raise ValueError("bounded certificate summary root hash mismatch")
    if bundle.get("root_value") != verification.get("root_value"):
        raise ValueError("bounded certificate summary WDL mismatch")
    return root_hash


class BundledEndgameFactAdapter:
    """Generate independently replayable v2 seed facts from bundled KXK hints."""

    def __init__(
        self,
        dag: ProofDAG,
        journal: WDLFactJournal,
        *,
        limits: EndgameFactLimits | None = None,
    ) -> None:
        if not isinstance(dag, ProofDAG) or dag.closed:
            raise TypeError("dag must be an open ProofDAG")
        if not isinstance(journal, WDLFactJournal) or journal.closed:
            raise TypeError("journal must be an open WDLFactJournal")
        if journal.dag is not dag:
            raise ValueError("fact journal is not bound to the supplied ProofDAG")
        if limits is None:
            limits = EndgameFactLimits()
        if not isinstance(limits, EndgameFactLimits):
            raise TypeError("limits must be an EndgameFactLimits instance or None")
        self.dag = dag
        self.journal = journal
        self.limits = limits

    def adapt(self, node_sha256: str) -> EndgameFactResult:
        """Attempt one safe seed append; ordinary incompleteness is UNKNOWN."""

        node = _exact_node(self.dag, node_sha256)
        material_piece = _material_piece(node)
        material = None if material_piece is None else f"K{material_piece}K"
        automatic = automatic_status(node.position, node.history)
        claims = current_claim_actions(node.position, node.history)

        entries = tuple(self.journal.iter_entries())
        entry = next(
            (
                item
                for item in entries
                if item.fact.node_sha256 == node.node_sha256
            ),
            None,
        )
        if entry is not None:
            return _from_entry(
                entry,
                appended=False,
                reason="target_already_verified",
                detail="the v2 journal already binds this exact DAG node",
                material=material,
                automatic_code=automatic.code,
                claims=claims,
            )

        if material_piece is None:
            return _unknown(
                node,
                reason="unsupported_material",
                detail="only exact KQK and KRK DAG nodes are supported",
                material=None,
                automatic_code=automatic.code,
                claims=claims,
                limits=self.limits,
            )

        loaded: _LoadedTablebase | None = None
        probe: TablebaseProbe | None = None
        search_depth = 0
        if not automatic.terminal:
            try:
                loaded = _load_bundled_tablebase(material_piece)
                probe = loaded.tablebase.probe(node.position)
            except (
                OSError,
                ValueError,
                TypeError,
                KeyError,
                AttributeError,
                EndgameTablebaseError,
            ) as exc:
                return _unknown(
                    node,
                    reason="tablebase_unavailable",
                    detail=f"bundled tablebase could not be validated/probed: {exc}",
                    material=material,
                    automatic_code=automatic.code,
                    claims=claims,
                    limits=self.limits,
                )
            if not _probe_is_strict(probe, node, material_piece):
                return _unknown(
                    node,
                    reason="invalid_tablebase_probe",
                    detail="bundled tablebase returned a malformed or inexact probe",
                    material=material,
                    automatic_code=automatic.code,
                    claims=claims,
                    transport_sha256=loaded.transport_sha256,
                    limits=self.limits,
                )
            if probe.outcome in {"win", "loss"}:
                assert probe.dtm_plies is not None
                required_depth = probe.dtm_plies
                maximum = loaded.tablebase.metadata.get("max_dtm_plies")
                if (
                    isinstance(maximum, bool)
                    or not isinstance(maximum, int)
                    or required_depth > maximum
                ):
                    return _unknown(
                        node,
                        reason="invalid_tablebase_probe",
                        detail="probe DTM exceeds the validated bundled maximum",
                        material=material,
                        automatic_code=automatic.code,
                        claims=claims,
                        probe=probe,
                        transport_sha256=loaded.transport_sha256,
                        limits=self.limits,
                    )
                if required_depth > self.limits.max_plies:
                    return _unknown(
                        node,
                        reason="ply_limit",
                        detail=(
                            f"tablebase DTM {required_depth} exceeds deterministic "
                            f"ply limit {self.limits.max_plies}"
                        ),
                        material=material,
                        automatic_code=automatic.code,
                        claims=claims,
                        probe=probe,
                        transport_sha256=loaded.transport_sha256,
                        limits=self.limits,
                    )
                search_depth = required_depth
            else:
                search_depth = self.limits.max_plies

        solver = BoundedWDLSolver(node_budget=self.limits.node_budget)
        try:
            search = solver.solve(
                node.position,
                max_plies=search_depth,
                history=node.history,
            )
        except RecursionError as exc:
            return _unknown(
                node,
                reason="search_recursion_limit",
                detail=f"bounded certificate search exceeded recursion capacity: {exc}",
                material=material,
                automatic_code=automatic.code,
                claims=claims,
                probe=probe,
                transport_sha256=(
                    None if loaded is None else loaded.transport_sha256
                ),
                search_max_plies=search_depth,
                limits=self.limits,
            )
        if not search.root.exact or search.root.value == WDL.UNKNOWN:
            exhausted = search.nodes >= self.limits.node_budget
            return _unknown(
                node,
                reason=(
                    "node_budget_exhausted"
                    if exhausted
                    else "bounded_certificate_unknown"
                ),
                detail=(
                    "deterministic node budget ended before an exact certificate"
                    if exhausted
                    else "the bounded verifier language could not close this tablebase probe"
                ),
                material=material,
                automatic_code=automatic.code,
                claims=claims,
                probe=probe,
                transport_sha256=(
                    None if loaded is None else loaded.transport_sha256
                ),
                search_max_plies=search_depth,
                limits=self.limits,
                search=search,
            )

        try:
            bundle = search.certificate_bundle()
            verification = verify_wdl_certificate(bundle, allow_unknown_root=False)
            root_certificate_hash = _bind_verified_bundle(
                node,
                bundle,
                verification,
            )
            certificate_bytes = canonical_json_bytes(bundle)
        except (TypeError, ValueError, RecursionError) as exc:
            return _unknown(
                node,
                reason="certificate_verification_failed",
                detail=f"generated certificate failed independent replay/binding: {exc}",
                material=material,
                automatic_code=automatic.code,
                claims=claims,
                probe=probe,
                transport_sha256=(
                    None if loaded is None else loaded.transport_sha256
                ),
                search_max_plies=search_depth,
                limits=self.limits,
                search=search,
            )

        if len(certificate_bytes) > self.limits.max_certificate_bytes:
            return _unknown(
                node,
                reason="certificate_size_limit",
                detail=(
                    f"canonical certificate is {len(certificate_bytes)} bytes; "
                    f"adapter limit is {self.limits.max_certificate_bytes}"
                ),
                material=material,
                automatic_code=automatic.code,
                claims=claims,
                probe=probe,
                transport_sha256=(
                    None if loaded is None else loaded.transport_sha256
                ),
                search_max_plies=search_depth,
                limits=self.limits,
                search=search,
                certificate_bytes=certificate_bytes,
            )

        try:
            appended = self.journal.append_seed_certificate(
                node.node_sha256,
                certificate_bytes,
            )
        except WDLFactConflictError:
            entry = next(
                (
                    item
                    for item in self.journal.iter_entries()
                    if item.fact.node_sha256 == node.node_sha256
                ),
                None,
            )
            if entry is None:
                raise
            return _from_entry(
                entry,
                appended=False,
                reason="concurrent_fact_won",
                detail="another exact fact won the one-fact-per-node race",
                material=material,
                automatic_code=automatic.code,
                claims=claims,
                probe=probe,
                transport_sha256=(
                    None if loaded is None else loaded.transport_sha256
                ),
                search_max_plies=search_depth,
                limits=self.limits,
                search=search,
            )
        except ValueError as exc:
            return _unknown(
                node,
                reason="journal_rejected_certificate",
                detail=f"v2 journal independently rejected the seed: {exc}",
                material=material,
                automatic_code=automatic.code,
                claims=claims,
                probe=probe,
                transport_sha256=(
                    None if loaded is None else loaded.transport_sha256
                ),
                search_max_plies=search_depth,
                limits=self.limits,
                search=search,
                certificate_bytes=certificate_bytes,
            )

        rule_adjusted = probe is not None and probe.outcome != search.root.value.value
        detail = "canonical bounded certificate independently replayed and committed"
        if rule_adjusted:
            detail += "; history-aware FIDE rules changed the bare tablebase outcome"
        return _from_entry(
            appended.entry,
            appended=appended.appended,
            reason="certificate_promoted" if appended.appended else "certificate_already_present",
            detail=detail,
            material=material,
            automatic_code=automatic.code,
            claims=claims,
            probe=probe,
            transport_sha256=None if loaded is None else loaded.transport_sha256,
            search_max_plies=search_depth,
            limits=self.limits,
            search=search,
            certificate_bytes=certificate_bytes,
            root_certificate_hash=root_certificate_hash,
        )


def append_bundled_endgame_fact(
    dag: ProofDAG,
    journal: WDLFactJournal,
    node_sha256: str,
    *,
    limits: EndgameFactLimits | None = None,
) -> EndgameFactResult:
    """One-shot public adapter wrapper."""

    return BundledEndgameFactAdapter(dag, journal, limits=limits).adapt(
        node_sha256
    )


__all__ = [
    "DEFAULT_MAX_CERTIFICATE_BYTES",
    "DEFAULT_MAX_PLIES",
    "DEFAULT_NODE_BUDGET",
    "ENDGAME_FACT_RESULT_SCHEMA",
    "MAX_NODE_BUDGET",
    "MAX_PLIES",
    "BundledEndgameFactAdapter",
    "EndgameFactAdapterError",
    "EndgameFactLimits",
    "EndgameFactResult",
    "EndgameTablebaseError",
    "append_bundled_endgame_fact",
]
