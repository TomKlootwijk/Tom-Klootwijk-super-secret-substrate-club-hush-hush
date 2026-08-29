from __future__ import annotations

import json
from pathlib import Path
import shutil

from ugts_chess import Position
from ugts_chess.campaign import campaign_status, init_campaign, verify_campaign
from ugts_chess.game_theory import root_obligations
from ugts_chess.gpu_protocol import recommended_rtx5070ti_config, run_batch
from ugts_chess.rules import perft
from ugts_chess.wdl import BoundedWDLSolver

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "campaign"
VALIDATION = ROOT / "validation"
GPU_EXE = ROOT / "cpp" / "build" / "host-release" / "ugts-chess-gpu"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    if EXAMPLES.exists():
        shutil.rmtree(EXAMPLES)
    EXAMPLES.mkdir(parents=True)
    db = EXAMPLES / "initial.sqlite3"
    shards = EXAMPLES / "root_shards"
    init = init_campaign(db, shards, force=True)
    status = campaign_status(db)
    verification = verify_campaign(db)
    write_json(EXAMPLES / "campaign_init.json", init)
    write_json(EXAMPLES / "campaign_status.json", status)
    write_json(EXAMPLES / "campaign_verify.json", verification)

    root = Position.initial()
    workloads = []
    for obligation in root_obligations(root):
        child = Position.from_fen(obligation.child_fen)
        leaf_paths = perft(child, 3)
        workloads.append({
            "obligation_id": obligation.obligation_id,
            "move_uci": obligation.move_uci,
            "child_position_sha256": obligation.child_position_sha256,
            "child_game_state_sha256": obligation.child_game_state_sha256,
            "remaining_depth": 3,
            "exact_depth4_leaf_paths": leaf_paths,
            "wdl": "unknown",
        })
    workload_record = {
        "schema": "ugts-chess-root-workloads-2.0",
        "root_fen": root.to_fen(),
        "root_obligations": len(workloads),
        "depth": 4,
        "total_exact_leaf_paths": sum(row["exact_depth4_leaf_paths"] for row in workloads),
        "shards": workloads,
        "root_game_theoretic_value": "unknown",
    }
    write_json(EXAMPLES / "initial_depth4_workloads.json", workload_record)

    mate_claim = Position.from_fen("8/8/8/1Q6/8/8/k7/2K5 w - - 100 2")
    write_json(EXAMPLES / "bounded_wdl_mate_over_claim.json", BoundedWDLSolver(node_budget=100_000).solve(mate_claim, max_plies=1).record())
    write_json(EXAMPLES / "bounded_wdl_initial_depth2.json", BoundedWDLSolver(node_budget=2_000_000).solve(root, max_plies=2).record())
    write_json(EXAMPLES / "rtx5070ti_profile.json", recommended_rtx5070ti_config())

    if GPU_EXE.exists():
        positions = [
            root,
            Position.from_fen("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"),
            mate_claim,
            Position.from_fen("8/8/8/8/8/8/R3k3/K7 w - - 99 1"),
        ]
        result = run_batch(GPU_EXE, positions, VALIDATION / "gpu_protocol")
        write_json(VALIDATION / "gpu_protocol_differential.json", result)
    print(json.dumps({"campaign": str(db), "workloads": workload_record["total_exact_leaf_paths"], "verified": verification["valid"]}, sort_keys=True))


if __name__ == "__main__":
    main()
