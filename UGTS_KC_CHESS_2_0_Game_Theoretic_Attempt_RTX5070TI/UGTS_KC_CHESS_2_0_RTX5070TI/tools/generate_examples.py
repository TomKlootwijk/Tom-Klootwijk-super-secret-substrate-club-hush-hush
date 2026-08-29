from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

from ugts_chess.hashing import state_sha256
from ugts_chess.position import Position
from ugts_chess.proof import MateProver, verify_mate_certificate
from ugts_chess.rules import parse_uci_move
from ugts_chess.search import Searcher
from ugts_chess.tablebase import KXKTablebase
from ugts_chess.ugts import commit_move

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
EXAMPLES.mkdir(exist_ok=True)

mate_fen = "8/8/8/8/8/k7/8/1QK5 w - - 0 1"
mate_position = Position.from_fen(mate_fen)
proof = MateProver(node_budget=100_000).prove(mate_position, max_plies=3).certificate
verify_mate_certificate(proof)
(EXAMPLES / "mate_in_two_proof.json").write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")

search = Searcher().search(mate_position, max_depth=4)
(EXAMPLES / "mate_in_two_search.json").write_text(json.dumps(search.to_dict(mate_position), indent=2, sort_keys=True) + "\n", encoding="utf-8")

with resources.as_file(resources.files("ugts_chess.resources").joinpath("kqk.tb.gz")) as path:
    kqk = KXKTablebase.load(path)
probe = kqk.probe(mate_position).to_dict()
probe["best_moves"] = kqk.best_moves(mate_position)
(EXAMPLES / "kqk_probe.json").write_text(json.dumps(probe, indent=2, sort_keys=True) + "\n", encoding="utf-8")

opening = Position.initial()
current = opening
events = []
for sequence, uci in enumerate(("e2e4", "e7e5", "g1f3", "b8c6", "f1b5"), 1):
    current, event = commit_move(current, parse_uci_move(current, uci), sequence=sequence)
    events.append(event.to_dict())
replay_record = {
    "schema": "ugts-kc-chess-replay-1.0",
    "initial_fen": opening.to_fen(),
    "initial_hash": state_sha256(opening),
    "events": events,
    "final_fen": current.to_fen(),
    "final_hash": state_sha256(current),
}
(EXAMPLES / "ruy_lopez_replay.json").write_text(json.dumps(replay_record, indent=2, sort_keys=True) + "\n", encoding="utf-8")

positions = {
    "schema_version": "1.0.0",
    "project_id": "ugts-chess-reference-project",
    "solver_policy": {"deterministic": True, "claim_draws": True, "max_depth": 5, "max_plies": 7},
    "positions": [
        {"id": "initial-perft", "fen": Position.initial().to_fen(), "task": "perft", "depth": 4},
        {"id": "kiwipete-perft", "fen": "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", "task": "perft", "depth": 3},
        {"id": "mate-in-two-proof", "fen": mate_fen, "task": "prove_mate", "max_plies": 3},
        {"id": "kqk-tablebase", "fen": mate_fen, "task": "tablebase_probe"},
        {"id": "balanced-search", "fen": "6k1/5ppp/8/8/8/8/5PPP/6K1 w - - 0 1", "task": "search", "max_depth": 4}
    ]
}
(EXAMPLES / "project.json").write_text(json.dumps(positions, indent=2, sort_keys=True) + "\n", encoding="utf-8")

summary = {
    "proof": {"status": proof["status"], "root_hash": proof["root_hash"], "explored_nodes": proof["explored_nodes"]},
    "search": search.to_dict(mate_position),
    "tablebase": probe,
    "replay": {"events": len(events), "final_hash": replay_record["final_hash"]},
}
(EXAMPLES / "demo_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(summary, indent=2, sort_keys=True))
