"""Canonical receipts binding campaign obligations to compact v2 WDL facts.

This module is deliberately not a campaign promotion API.  A projection is a
small, externally retainable receipt which names one exact campaign child and
the authoritative journal prefixes needed to replay its WDL fact.  The proof
remains in the append-only ProofDAG frontier and v2 fact journal; SQLite rows,
receipt fields, and campaign scheduler state are comparison data only.

The embedded fact head ends exactly at the selected fact.  Verification fully
replays both live authorities, requires both embedded heads as exact prefixes,
and additionally proves that every DAG occurrence needed by the selected fact
prefix lies inside the *embedded* DAG head.  This last relationship prevents a
receipt from pairing an old valid DAG head with facts that depend on a later,
uncommitted DAG extension.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Final

from .campaign import ROOT_IDENTITY_SCHEMA
from .game_state import (
    RULE_PROFILE_ID,
    HistoryContext,
    automatic_status,
    game_state_sha256,
    validate_history_reachability,
)
from .game_theory import ProofObligation, WDL, root_obligations
from .hashing import canonical_json_bytes, state_sha256
from .position import Position
from .proof_dag import DAG_NODE_SCHEMA, ProofDAG, node_identity_sha256
from .proof_dag_commitment import (
    ProofDAGHead,
    audit_proof_dag_head,
    require_external_dag_head,
)
from .wdl_fact_journal import (
    FactEntry,
    FactJournalHead,
    FactScanResult,
    WDLFactJournal,
    WDLFactRollbackError,
)


CAMPAIGN_FACT_PROJECTION_SCHEMA: Final = (
    "ugts-chess-campaign-wdl-fact-projection-1.0"
)
MAX_CAMPAIGN_FACT_PROJECTION_BYTES: Final = 64 * 1024

_OBLIGATION_ID = re.compile(
    r"^root-(?:0[1-9]|[1-9][0-9]+)-[a-h][1-8][a-h][1-8][nbrq]?$"
)
_PROJECTION_KEYS: Final = frozenset(
    {
        "schema",
        "campaign_root_identity_schema",
        "campaign_root_identity_sha256",
        "obligation_id",
        "rule_profile_id",
        "child_node_schema",
        "child_node_sha256",
        "child_game_state_sha256",
        "claimed_wdl",
        "proof_dag_head",
        "fact_journal_head",
    }
)


class CampaignFactProjectionError(Exception):
    """Base class for projection construction and verification failures."""


class CampaignFactProjectionMismatchError(CampaignFactProjectionError):
    """Raised when a receipt does not bind the supplied exact obligation."""


class CampaignFactProjectionAuthorityError(CampaignFactProjectionError):
    """Raised when replayed authorities do not satisfy a receipt binding."""


def _is_sha256_hex(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _require_sha256(value: object, *, label: str) -> str:
    if not _is_sha256_hex(value):
        raise ValueError(f"{label} must be lowercase SHA-256 hex")
    return value


@dataclass(frozen=True, slots=True)
class CampaignWDLFactProjection:
    """Canonical compact binding to one exact v2 fact-journal prefix."""

    campaign_root_identity_schema: str
    campaign_root_identity_sha256: str
    obligation_id: str
    rule_profile_id: str
    child_node_schema: str
    child_node_sha256: str
    child_game_state_sha256: str
    claimed_wdl: WDL
    proof_dag_head: ProofDAGHead
    fact_journal_head: FactJournalHead

    def __post_init__(self) -> None:
        if self.campaign_root_identity_schema != ROOT_IDENTITY_SCHEMA:
            raise ValueError("projection campaign-root identity schema mismatch")
        _require_sha256(
            self.campaign_root_identity_sha256,
            label="campaign root identity",
        )
        if not isinstance(self.obligation_id, str) or not _OBLIGATION_ID.fullmatch(
            self.obligation_id
        ):
            raise ValueError("projection obligation id is not canonical")
        if self.rule_profile_id != RULE_PROFILE_ID:
            raise ValueError("projection rule profile mismatch")
        if self.child_node_schema != DAG_NODE_SCHEMA:
            raise ValueError("projection child-node schema mismatch")
        _require_sha256(self.child_node_sha256, label="projection child node")
        _require_sha256(
            self.child_game_state_sha256,
            label="projection child game state",
        )
        if not isinstance(self.claimed_wdl, WDL) or self.claimed_wdl == WDL.UNKNOWN:
            raise ValueError("projection WDL must be exact WIN, DRAW, or LOSS")
        if not isinstance(self.proof_dag_head, ProofDAGHead):
            raise TypeError("projection proof_dag_head must be a ProofDAGHead")
        canonical_dag_head = ProofDAGHead.from_bytes(
            self.proof_dag_head.canonical_bytes()
        )
        if canonical_dag_head != self.proof_dag_head:
            raise ValueError("projection ProofDAG head is not canonical")
        if not isinstance(self.fact_journal_head, FactJournalHead):
            raise TypeError("projection fact_journal_head must be a FactJournalHead")
        canonical_fact_head = FactJournalHead.from_bytes(
            self.fact_journal_head.canonical_bytes()
        )
        if canonical_fact_head != self.fact_journal_head:
            raise ValueError("projection fact-journal head is not canonical")
        if canonical_fact_head.record_count <= 0:
            raise ValueError("projection fact-journal head must select one fact")

    def record(self) -> dict[str, object]:
        return {
            "schema": CAMPAIGN_FACT_PROJECTION_SCHEMA,
            "campaign_root_identity_schema": self.campaign_root_identity_schema,
            "campaign_root_identity_sha256": self.campaign_root_identity_sha256,
            "obligation_id": self.obligation_id,
            "rule_profile_id": self.rule_profile_id,
            "child_node_schema": self.child_node_schema,
            "child_node_sha256": self.child_node_sha256,
            "child_game_state_sha256": self.child_game_state_sha256,
            "claimed_wdl": self.claimed_wdl.value,
            "proof_dag_head": self.proof_dag_head.record(),
            "fact_journal_head": self.fact_journal_head.record(),
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.record())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    @classmethod
    def from_bytes(
        cls,
        value: bytes | bytearray | memoryview,
    ) -> "CampaignWDLFactProjection":
        if not isinstance(value, (bytes, bytearray, memoryview)):
            raise TypeError("campaign fact projection must be bytes-like")
        snapshot = bytes(value)
        if not snapshot or len(snapshot) > MAX_CAMPAIGN_FACT_PROJECTION_BYTES:
            raise ValueError("campaign fact projection size is outside the supported range")
        try:
            raw = json.loads(snapshot)
            reconstructed = canonical_json_bytes(raw)
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            RecursionError,
            TypeError,
            ValueError,
        ) as exc:
            raise ValueError(
                f"campaign fact projection is not canonical UTF-8 JSON: {exc}"
            ) from exc
        if not isinstance(raw, dict) or reconstructed != snapshot:
            raise ValueError("campaign fact projection is not a canonical JSON object")
        if set(raw) != _PROJECTION_KEYS:
            raise ValueError("campaign fact projection has missing or unexpected fields")
        if raw.get("schema") != CAMPAIGN_FACT_PROJECTION_SCHEMA:
            raise ValueError("campaign fact projection schema mismatch")
        raw_dag_head = raw.get("proof_dag_head")
        raw_fact_head = raw.get("fact_journal_head")
        if not isinstance(raw_dag_head, dict) or not isinstance(raw_fact_head, dict):
            raise ValueError("campaign fact projection heads must be JSON objects")
        try:
            claimed_wdl = WDL(raw.get("claimed_wdl"))
        except (TypeError, ValueError) as exc:
            raise ValueError("campaign fact projection WDL is invalid") from exc
        result = cls(
            campaign_root_identity_schema=raw.get(  # type: ignore[arg-type]
                "campaign_root_identity_schema"
            ),
            campaign_root_identity_sha256=raw.get(  # type: ignore[arg-type]
                "campaign_root_identity_sha256"
            ),
            obligation_id=raw.get("obligation_id"),  # type: ignore[arg-type]
            rule_profile_id=raw.get("rule_profile_id"),  # type: ignore[arg-type]
            child_node_schema=raw.get("child_node_schema"),  # type: ignore[arg-type]
            child_node_sha256=raw.get("child_node_sha256"),  # type: ignore[arg-type]
            child_game_state_sha256=raw.get(  # type: ignore[arg-type]
                "child_game_state_sha256"
            ),
            claimed_wdl=claimed_wdl,
            proof_dag_head=ProofDAGHead.from_bytes(
                canonical_json_bytes(raw_dag_head)
            ),
            fact_journal_head=FactJournalHead.from_bytes(
                canonical_json_bytes(raw_fact_head)
            ),
        )
        if result.canonical_bytes() != snapshot:
            raise ValueError("campaign fact projection differs from exact reconstruction")
        return result


@dataclass(frozen=True, slots=True)
class CampaignFactProjectionVerification:
    """Evidence returned only after both exact authorities replay successfully."""

    projection: CampaignWDLFactProjection
    fact_record_index: int
    fact_content_sha256: str
    fact_kind: str
    proof_height: int
    current_proof_dag_head: ProofDAGHead
    current_fact_journal_head: FactJournalHead

    @property
    def claimed_wdl(self) -> WDL:
        return self.projection.claimed_wdl


@dataclass(frozen=True, slots=True)
class _ExactObligationContext:
    root_identity_sha256: str
    obligation: ProofObligation
    child_position: Position
    child_history: HistoryContext
    child_node_sha256: str


def _campaign_root_identity_sha256(
    root: Position,
    history: HistoryContext,
) -> str:
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "schema": ROOT_IDENTITY_SCHEMA,
                "rules_profile": RULE_PROFILE_ID,
                "fen": root.to_fen(),
                "history_counts": history.record(),
            }
        )
    ).hexdigest()


def _exact_obligation_context(
    root: Position,
    root_history: HistoryContext,
    obligation: ProofObligation,
) -> _ExactObligationContext:
    if not isinstance(root, Position):
        raise TypeError("campaign root must be a Position")
    if not isinstance(root_history, HistoryContext):
        raise TypeError("campaign root history must be a HistoryContext")
    if not isinstance(obligation, ProofObligation):
        raise TypeError("campaign obligation must be a ProofObligation")
    validate_history_reachability(root, root_history)
    if root_history != HistoryContext.initial(root):
        raise ValueError("campaign root history is not canonical initial history")
    if automatic_status(root, root_history).terminal:
        raise ValueError("an automatically terminal campaign root has no move obligations")
    expected_by_id = {
        item.obligation_id: item for item in root_obligations(root, root_history)
    }
    expected = expected_by_id.get(obligation.obligation_id)
    if expected is None or obligation != expected:
        raise ValueError("campaign obligation is not the exact canonical root obligation")
    child_position = Position.from_fen(expected.child_fen, strict=True)
    child_history = HistoryContext(expected.child_history_counts)
    validate_history_reachability(child_position, child_history)
    if state_sha256(child_position) != expected.child_position_sha256:
        raise ValueError("canonical obligation child position hash mismatch")
    if game_state_sha256(child_position, child_history) != expected.child_game_state_sha256:
        raise ValueError("canonical obligation child game-state hash mismatch")
    return _ExactObligationContext(
        root_identity_sha256=_campaign_root_identity_sha256(root, root_history),
        obligation=expected,
        child_position=child_position,
        child_history=child_history,
        child_node_sha256=node_identity_sha256(
            child_position,
            child_history,
            rule_profile_id=RULE_PROFILE_ID,
        ),
    )


def _require_open_authorities(dag: ProofDAG, journal: WDLFactJournal) -> None:
    if not isinstance(dag, ProofDAG) or dag.closed:
        raise TypeError("dag must be an open ProofDAG")
    if not isinstance(journal, WDLFactJournal) or journal.closed:
        raise TypeError("journal must be an open WDLFactJournal")
    if journal.dag is not dag:
        raise ValueError("fact journal is not bound to the supplied ProofDAG")
    if dag.rule_profile_id != RULE_PROFILE_ID:
        raise ValueError("projection requires the canonical rule profile")


def _fact_head_at(entry: FactEntry) -> FactJournalHead:
    head = FactJournalHead(
        rule_profile_id=RULE_PROFILE_ID,
        record_count=entry.record_index + 1,
        head_content_sha256=entry.content_sha256,
        file_size=entry.frame_end_offset,
    )
    return FactJournalHead.from_bytes(head.canonical_bytes())


def _require_fact_head_in_report(
    required: FactJournalHead,
    report: FactScanResult,
) -> FactEntry:
    report.require_valid()
    canonical = FactJournalHead.from_bytes(required.canonical_bytes())
    if canonical.record_count <= 0:
        raise WDLFactRollbackError("projection fact head does not select a fact")
    if canonical.record_count > report.record_count:
        raise WDLFactRollbackError("fact journal is shorter than the projection head")
    target = report.entries[canonical.record_count - 1]
    if (
        target.content_sha256 != canonical.head_content_sha256
        or target.frame_end_offset != canonical.file_size
    ):
        raise WDLFactRollbackError(
            "projection fact head is not the exact live journal prefix"
        )
    return target


def _require_fact_prefix_inside_dag_head(
    dag: ProofDAG,
    report: FactScanResult,
    fact_head: FactJournalHead,
    dag_head: ProofDAGHead,
) -> None:
    """Cross-bind every DAG occurrence used through the selected fact."""

    _require_fact_head_in_report(fact_head, report)
    boundary_count = dag_head.frontier_record_count
    boundary_size = dag_head.frontier_size
    for entry in report.entries[: fact_head.record_count]:
        fact = entry.fact
        first = dag.get_edge(fact.first_frontier_content_sha256)
        if first is None or first.child_node_sha256 != fact.node_sha256:
            raise CampaignFactProjectionAuthorityError(
                "fact first frontier occurrence is absent or names another node"
            )
        if (
            first.frontier_record_index >= boundary_count
            or first.frame_end_offset > boundary_size
        ):
            raise CampaignFactProjectionAuthorityError(
                "fact first frontier occurrence lies beyond the embedded DAG head"
            )
        if fact.kind != "derivation":
            continue
        evidence = fact.evidence
        if not isinstance(evidence, Mapping):
            raise CampaignFactProjectionAuthorityError(
                "replayed derivation evidence is not an object"
            )
        dependencies = evidence.get("move_dependencies")
        if not isinstance(dependencies, tuple):
            raise CampaignFactProjectionAuthorityError(
                "replayed derivation dependencies are not canonical"
            )
        for dependency in dependencies:
            if not isinstance(dependency, Mapping):
                raise CampaignFactProjectionAuthorityError(
                    "replayed derivation dependency is not an object"
                )
            edge_index = dependency.get("dag_edge_record_index")
            edge_sha256 = dependency.get("dag_edge_content_sha256")
            if (
                isinstance(edge_index, bool)
                or not isinstance(edge_index, int)
                or edge_index < 0
                or not _is_sha256_hex(edge_sha256)
            ):
                raise CampaignFactProjectionAuthorityError(
                    "replayed derivation dependency has an invalid DAG address"
                )
            edge = dag.get_edge(edge_sha256)
            if edge is None or edge.frontier_record_index != edge_index:
                raise CampaignFactProjectionAuthorityError(
                    "replayed derivation dependency DAG address is absent"
                )
            if edge_index >= boundary_count or edge.frame_end_offset > boundary_size:
                raise CampaignFactProjectionAuthorityError(
                    "derivation dependency lies beyond the embedded DAG head"
                )


def _require_projection_matches_target(
    projection: CampaignWDLFactProjection,
    context: _ExactObligationContext,
    target: FactEntry,
    dag: ProofDAG,
) -> None:
    obligation = context.obligation
    mismatches: list[str] = []
    if projection.campaign_root_identity_sha256 != context.root_identity_sha256:
        mismatches.append("campaign root identity")
    if projection.obligation_id != obligation.obligation_id:
        mismatches.append("obligation id")
    if projection.child_node_sha256 != context.child_node_sha256:
        mismatches.append("child node identity")
    if projection.child_game_state_sha256 != obligation.child_game_state_sha256:
        mismatches.append("child game-state identity")

    fact = target.fact
    expected_history = context.child_history.counts
    if fact.node_sha256 != context.child_node_sha256:
        mismatches.append("fact child node")
    if fact.rule_profile_id != RULE_PROFILE_ID:
        mismatches.append("fact rule profile")
    if fact.fen != obligation.child_fen:
        mismatches.append("fact child FEN")
    if fact.history_counts != expected_history:
        mismatches.append("fact child history")
    if fact.position_sha256 != obligation.child_position_sha256:
        mismatches.append("fact child position")
    if fact.game_state_sha256 != obligation.child_game_state_sha256:
        mismatches.append("fact child game state")
    if fact.claimed_wdl == WDL.UNKNOWN or fact.claimed_wdl != projection.claimed_wdl:
        mismatches.append("fact WDL")

    node = dag.get_node(context.child_node_sha256)
    if node is None:
        mismatches.append("DAG child node presence")
    elif (
        node.position != context.child_position
        or node.fen != obligation.child_fen
        or node.history != context.child_history
        or node.rule_profile_id != RULE_PROFILE_ID
        or node.game_state_sha256 != obligation.child_game_state_sha256
    ):
        mismatches.append("DAG child node reconstruction")
    if mismatches:
        raise CampaignFactProjectionMismatchError(
            "projection does not match the exact campaign obligation: "
            + ", ".join(mismatches)
        )


def parse_campaign_fact_projection(
    value: bytes | bytearray | memoryview,
) -> CampaignWDLFactProjection:
    """Parse one strict canonical projection receipt."""

    return CampaignWDLFactProjection.from_bytes(value)


def verify_campaign_fact_projection(
    projection: CampaignWDLFactProjection | bytes | bytearray | memoryview,
    *,
    campaign_root: Position,
    campaign_root_history: HistoryContext,
    obligation: ProofObligation,
    dag: ProofDAG,
    journal: WDLFactJournal,
) -> CampaignFactProjectionVerification:
    """Replay and bind a receipt without changing campaign or proof state."""

    _require_open_authorities(dag, journal)
    canonical = (
        CampaignWDLFactProjection.from_bytes(projection.canonical_bytes())
        if isinstance(projection, CampaignWDLFactProjection)
        else CampaignWDLFactProjection.from_bytes(projection)
    )
    context = _exact_obligation_context(
        campaign_root,
        campaign_root_history,
        obligation,
    )

    # Both comparisons perform complete stable source audits.  The fact audit
    # then supplies the exact selected entry and all prior dependencies needed
    # for the explicit cross-head relationship check.
    require_external_dag_head(dag, canonical.proof_dag_head)
    journal.require_external_head(canonical.fact_journal_head)
    report = journal.audit().require_valid()
    target = _require_fact_head_in_report(canonical.fact_journal_head, report)
    _require_fact_prefix_inside_dag_head(
        dag,
        report,
        canonical.fact_journal_head,
        canonical.proof_dag_head,
    )
    _require_projection_matches_target(canonical, context, target, dag)

    # Recheck after all cross-source reads.  Normal append-only extensions are
    # accepted because each required head is compared as a prefix.
    current_fact_head = journal.require_external_head(
        canonical.fact_journal_head
    )
    current_dag_head = require_external_dag_head(
        dag,
        canonical.proof_dag_head,
    )
    return CampaignFactProjectionVerification(
        projection=canonical,
        fact_record_index=target.record_index,
        fact_content_sha256=target.content_sha256,
        fact_kind=target.fact.kind,
        proof_height=target.fact.proof_height,
        current_proof_dag_head=current_dag_head,
        current_fact_journal_head=current_fact_head,
    )


def create_campaign_fact_projection(
    *,
    campaign_root: Position,
    campaign_root_history: HistoryContext,
    obligation: ProofObligation,
    dag: ProofDAG,
    journal: WDLFactJournal,
) -> CampaignWDLFactProjection:
    """Capture and reverify a receipt whose fact head ends at the target."""

    _require_open_authorities(dag, journal)
    context = _exact_obligation_context(
        campaign_root,
        campaign_root_history,
        obligation,
    )
    report = journal.audit().require_valid()
    matches = tuple(
        entry
        for entry in report.entries
        if entry.fact.node_sha256 == context.child_node_sha256
    )
    if len(matches) != 1:
        raise CampaignFactProjectionAuthorityError(
            "the fact journal does not contain exactly one fact for the obligation child"
        )
    target = matches[0]
    if target.fact.claimed_wdl == WDL.UNKNOWN:
        raise CampaignFactProjectionAuthorityError(
            "UNKNOWN cannot be captured in a campaign fact projection"
        )

    # The fact existed before this DAG head was captured, so every occurrence
    # on which it depends must already be part of this committed DAG prefix.
    dag_head = audit_proof_dag_head(dag)
    fact_head = _fact_head_at(target)
    projection = CampaignWDLFactProjection(
        campaign_root_identity_schema=ROOT_IDENTITY_SCHEMA,
        campaign_root_identity_sha256=context.root_identity_sha256,
        obligation_id=context.obligation.obligation_id,
        rule_profile_id=RULE_PROFILE_ID,
        child_node_schema=DAG_NODE_SCHEMA,
        child_node_sha256=context.child_node_sha256,
        child_game_state_sha256=context.obligation.child_game_state_sha256,
        claimed_wdl=target.fact.claimed_wdl,
        proof_dag_head=dag_head,
        fact_journal_head=fact_head,
    )
    # Construction is not authority.  Return only after the ordinary public
    # verifier has replayed and cross-bound the completed canonical receipt.
    return verify_campaign_fact_projection(
        projection,
        campaign_root=campaign_root,
        campaign_root_history=campaign_root_history,
        obligation=obligation,
        dag=dag,
        journal=journal,
    ).projection


__all__ = [
    "CAMPAIGN_FACT_PROJECTION_SCHEMA",
    "MAX_CAMPAIGN_FACT_PROJECTION_BYTES",
    "CampaignFactProjectionAuthorityError",
    "CampaignFactProjectionError",
    "CampaignFactProjectionMismatchError",
    "CampaignFactProjectionVerification",
    "CampaignWDLFactProjection",
    "create_campaign_fact_projection",
    "parse_campaign_fact_projection",
    "verify_campaign_fact_projection",
]
