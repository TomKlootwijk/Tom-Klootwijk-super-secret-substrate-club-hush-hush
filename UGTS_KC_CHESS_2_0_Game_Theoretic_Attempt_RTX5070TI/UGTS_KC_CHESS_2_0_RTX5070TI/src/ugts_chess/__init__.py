"""UGTS-KC Chess 2.0: game-theoretic proof campaign and CUDA handoff."""
from .constants import BLACK, WHITE
from .move import Move
from .position import Position, START_FEN
from .proof import MateProver, verify_mate_certificate
from .rules import apply_move, legal_moves, move_to_san, parse_uci_move, perft, position_status
from .search import Searcher
from .game_state import (
    HistoryContext,
    automatic_status,
    current_claim_actions,
    game_state_sha256,
    validate_history_reachability,
)
from .wdl import BoundedWDLSolver, WDL
from .verified_overlay import (
    AuditedOverlaySnapshot,
    OverlayHeadCommitment,
    OverlayRecordCommitment,
    VerifiedCertificateBinding,
    VerifiedCertificateOverlay,
    recover_verified_overlay,
    verify_verified_overlay,
)
from .proof_dag import (
    DAGMoveAppendRequest,
    DAGMoveBatchAppendResult,
    MAX_MOVE_APPEND_BATCH,
    MAX_MOVE_APPEND_BATCH_BYTES,
    node_identity_sha256,
)
from .proof_dag_commitment import (
    PROOF_DAG_HEAD_SCHEMA,
    PROOF_DAG_MANIFEST_SCHEMA,
    ProofDAGCommitmentError,
    ProofDAGConcurrentMutationError,
    ProofDAGHead,
    ProofDAGHeadMismatchError,
    ProofDAGRollbackError,
    audit_proof_dag_head,
    require_external_dag_head,
)
from .campaign_fact_projection import (
    CAMPAIGN_FACT_PROJECTION_SCHEMA,
    MAX_CAMPAIGN_FACT_PROJECTION_BYTES,
    CampaignFactProjectionAuthorityError,
    CampaignFactProjectionError,
    CampaignFactProjectionMismatchError,
    CampaignFactProjectionVerification,
    CampaignWDLFactProjection,
    create_campaign_fact_projection,
    parse_campaign_fact_projection,
    verify_campaign_fact_projection,
)
from .wdl_propagation import (
    WDLPropagationResult,
    propagate_wdl_one_hop,
)
from .wdl_fact_journal import (
    FactAppendResult,
    FactEntry,
    FactJournalHead,
    VerifiedWDLFact,
    WDLFactJournal,
    canonical_derivation_evidence_bytes,
    migrate_verified_overlay_v1,
    recover_wdl_fact_journal,
    verify_wdl_fact_journal,
)
from .wdl_fact_propagation import (
    FactPropagationResult,
    propagate_wdl_fact_one_hop,
)
from .wdl_worklist import (
    DAGHead,
    DeterministicWDLWorklist,
    WorklistLimits,
    WorklistRunReport,
    WorklistStepResult,
    WorklistStepStatus,
    WorklistStopReason,
    run_wdl_worklist,
)
from .wdl_expansion import (
    ExpansionConcurrentMutationError,
    ExpansionDAGHead,
    ExpansionLimits,
    ExpansionReport,
    ExpansionStopReason,
    ParentExpansionResult,
    expand_proof_dag,
)
from .endgame_fact_adapter import (
    BundledEndgameFactAdapter,
    EndgameFactAdapterError,
    EndgameFactLimits,
    EndgameFactResult,
    EndgameTablebaseError,
    append_bundled_endgame_fact,
)

__all__ = [
    "BLACK", "WHITE", "Move", "Position", "START_FEN",
    "MateProver", "verify_mate_certificate", "apply_move", "legal_moves",
    "move_to_san", "parse_uci_move", "perft", "position_status", "Searcher",
    "HistoryContext", "automatic_status", "current_claim_actions",
    "validate_history_reachability",
    "game_state_sha256", "BoundedWDLSolver", "WDL",
    "AuditedOverlaySnapshot", "OverlayHeadCommitment",
    "OverlayRecordCommitment", "VerifiedCertificateBinding",
    "VerifiedCertificateOverlay",
    "recover_verified_overlay", "verify_verified_overlay",
    "WDLPropagationResult", "propagate_wdl_one_hop",
    "FactAppendResult", "FactEntry", "FactJournalHead", "VerifiedWDLFact",
    "WDLFactJournal", "canonical_derivation_evidence_bytes",
    "migrate_verified_overlay_v1", "recover_wdl_fact_journal",
    "verify_wdl_fact_journal", "FactPropagationResult",
    "propagate_wdl_fact_one_hop",
    "DAGHead", "DeterministicWDLWorklist", "WorklistLimits",
    "WorklistRunReport", "WorklistStepResult", "WorklistStepStatus",
    "WorklistStopReason", "run_wdl_worklist",
    "ExpansionConcurrentMutationError", "ExpansionDAGHead",
    "ExpansionLimits", "ExpansionReport", "ExpansionStopReason",
    "ParentExpansionResult", "expand_proof_dag",
    "BundledEndgameFactAdapter", "EndgameFactAdapterError",
    "EndgameFactLimits", "EndgameFactResult", "EndgameTablebaseError",
    "append_bundled_endgame_fact",
    "DAGMoveAppendRequest", "DAGMoveBatchAppendResult",
    "MAX_MOVE_APPEND_BATCH", "MAX_MOVE_APPEND_BATCH_BYTES",
    "node_identity_sha256",
    "PROOF_DAG_HEAD_SCHEMA", "PROOF_DAG_MANIFEST_SCHEMA",
    "ProofDAGCommitmentError", "ProofDAGConcurrentMutationError",
    "ProofDAGHead", "ProofDAGHeadMismatchError", "ProofDAGRollbackError",
    "audit_proof_dag_head", "require_external_dag_head",
    "CAMPAIGN_FACT_PROJECTION_SCHEMA",
    "MAX_CAMPAIGN_FACT_PROJECTION_BYTES",
    "CampaignFactProjectionAuthorityError", "CampaignFactProjectionError",
    "CampaignFactProjectionMismatchError",
    "CampaignFactProjectionVerification", "CampaignWDLFactProjection",
    "create_campaign_fact_projection", "parse_campaign_fact_projection",
    "verify_campaign_fact_projection",
]

__version__ = "2.0.0"
