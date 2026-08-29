"""Command-line interface for the UGTS Chess 2.0 proof campaign."""
from __future__ import annotations

import argparse
import json
import sys
from importlib import resources
from pathlib import Path
from typing import Any

from . import __version__
from .campaign import (
    campaign_status,
    export_campaign,
    init_campaign,
    lease_next,
    mark_verified,
    record_candidate,
    reject_candidate,
    verify_campaign,
)
from .constants import BLACK, WHITE
from .game_state import HistoryContext, automatic_status, current_claim_actions, game_state_sha256
from .game_theory import root_obligations
from .gpu_protocol import recommended_rtx5070ti_config, run_batch
from .gpu_qualification import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_MAX_PLIES,
    DEFAULT_RANDOM_POSITIONS,
    DEFAULT_SEED,
    qualify_gpu_move_generator,
)
from .hashing import compact_key64, state_sha256
from .position import Position, START_FEN
from .proof import MateProver, verify_mate_certificate
from .rules import legal_moves, move_to_san, perft, perft_divide, position_status
from .search import Searcher
from .tablebase import KXKTablebase, generate_tablebase, normalize_kxk_position
from .wdl import BoundedWDLSolver, verify_wdl_certificate


def _json_dump(value: object, path: str | None = None) -> None:
    text = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


def _load_position(fen: str) -> Position:
    return Position.from_fen(fen)


def _resource_tablebase(piece: str) -> KXKTablebase:
    name = "kqk.tb.gz" if piece.upper() == "Q" else "krk.tb.gz"
    ref = resources.files("ugts_chess.resources").joinpath(name)
    with resources.as_file(ref) as path:
        return KXKTablebase.load(path)


def cmd_info(_: argparse.Namespace) -> int:
    _json_dump(
        {
            "name": "UGTS Application / Chess Game-Theoretic Solver",
            "legacy_alias": "UGTS-KC Chess 2.0",
            "version": __version__,
            "canonical_component": "ugts.application.chess.game-theoretic-solver@2.0.0",
            "schema": "ugts-chess-solver-2.0",
            "capabilities": [
                "strict FEN and complete legal-move kernel",
                "castling, en-passant, promotion and king-safety guards",
                "history-correct automatic terminals and optional draw-claim actions",
                "deterministic heuristic alpha-beta kept outside proof authority",
                "proof-carrying bounded mate and WDL search",
                "independent WDL certificate-bundle verifier",
                "exact compressed KQK and KRK DTM tablebases",
                "independent complete KQK/KRK ranked-partition replay verifier",
                "hash-chained initial-position proof campaign with 20 root obligations",
                "64-byte position / 16-bit move CUDA proposal protocol",
                "C++20 legal kernel and generic CPU/CUDA retrograde fixed point",
            ],
            "evidence_boundary": (
                "The classical initial position remains UNKNOWN. This package is an executable, "
                "proof-oriented attempt and Codex handoff, not a completed game-theoretic solution."
            ),
        }
    )
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    position = _load_position(args.fen)
    status = position_status(position)
    moves = legal_moves(position)
    _json_dump(
        {
            "valid": True,
            "fen": position.to_fen(),
            "position_sha256": state_sha256(position),
            "compact_key64": f"0x{compact_key64(position):016x}",
            "status": status.to_dict(),
            "legal_move_count": len(moves),
            "legal_moves": [{"uci": move.uci(), "san": move_to_san(position, move)} for move in moves],
        },
        args.out,
    )
    return 0


def cmd_perft(args: argparse.Namespace) -> int:
    position = _load_position(args.fen)
    result: object
    if args.divide:
        result = {"fen": position.to_fen(), "depth": args.depth, "divide": perft_divide(position, args.depth)}
    else:
        result = {"fen": position.to_fen(), "depth": args.depth, "nodes": perft(position, args.depth)}
    _json_dump(result, args.out)
    return 0


def cmd_solve(args: argparse.Namespace) -> int:
    position = _load_position(args.fen)
    result = Searcher(claim_draws=not args.ignore_claimable_draws, tt_capacity=args.tt_capacity).search(
        position, max_depth=args.depth, time_limit=args.time
    )
    record = result.to_dict(position)
    record["authority"] = "heuristic-estimate-not-proof"
    _json_dump(record, args.out)
    return 0


def cmd_prove_mate(args: argparse.Namespace) -> int:
    position = _load_position(args.fen)
    attacker = None if not args.attacker else (WHITE if args.attacker == "white" else BLACK)
    result = MateProver(node_budget=args.node_budget).prove(position, max_plies=args.plies, attacker=attacker)
    _json_dump(result.to_dict(), args.out)
    return 0 if result.status == "proved" else 2


def cmd_verify_proof(args: argparse.Namespace) -> int:
    certificate = json.loads(Path(args.proof).read_text(encoding="utf-8"))
    _json_dump(verify_mate_certificate(certificate), args.out)
    return 0


def _detect_piece(position: Position) -> str:
    for piece in ("Q", "R"):
        if normalize_kxk_position(position, piece) is not None:
            return piece
    raise ValueError("position is not a supported KQK or KRK tablebase position")


def cmd_probe(args: argparse.Namespace) -> int:
    position = _load_position(args.fen)
    piece = args.piece or _detect_piece(position)
    tablebase = KXKTablebase.load(args.tablebase) if args.tablebase else _resource_tablebase(piece)
    data = tablebase.probe(position).to_dict()
    data["best_moves"] = tablebase.best_moves(position)
    _json_dump(data, args.out)
    return 0


def cmd_generate_tablebase(args: argparse.Namespace) -> int:
    _json_dump(generate_tablebase(args.piece, args.out), args.metadata_out)
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    examples: list[dict[str, Any]] = []
    for name, fen in (
        ("initial", START_FEN),
        ("mate_in_two", "8/8/8/8/8/k7/8/1QK5 w - - 0 1"),
        ("kqk_probe", "8/8/8/8/8/k7/8/1QK5 w - - 0 1"),
    ):
        position = Position.from_fen(fen)
        item: dict[str, Any] = {"name": name, "fen": fen, "hash": state_sha256(position), "legal_moves": len(legal_moves(position))}
        if name == "initial":
            item["perft_depth_3"] = perft(position, 3)
        elif name == "mate_in_two":
            proof = MateProver(node_budget=100_000).prove(position, max_plies=3)
            item["mate_proof_status"] = proof.status
            item["mate_proof_nodes"] = proof.explored_nodes
        else:
            tb = _resource_tablebase("Q")
            item["tablebase"] = tb.probe(position).to_dict()
            item["best_moves"] = tb.best_moves(position)
        examples.append(item)
    _json_dump({"version": __version__, "examples": examples}, args.out)
    return 0


def cmd_game_status(args: argparse.Namespace) -> int:
    position = _load_position(args.fen)
    history = HistoryContext.initial(position)
    _json_dump(
        {
            "fen": position.to_fen(),
            "rule_profile": "fide-classical-2023-claims-as-actions-v2",
            "game_state_sha256": game_state_sha256(position, history),
            "history_counts": history.record(),
            "automatic_status": automatic_status(position, history).record(),
            "claim_actions": list(current_claim_actions(position, history)),
        },
        args.out,
    )
    return 0


def cmd_bounded_wdl(args: argparse.Namespace) -> int:
    position = _load_position(args.fen)
    result = BoundedWDLSolver(node_budget=args.node_budget, time_limit=args.time).solve(position, max_plies=args.plies)
    _json_dump(result.record(), args.out)
    return 0 if result.root.exact else 2


def cmd_verify_wdl(args: argparse.Namespace) -> int:
    raw = json.loads(Path(args.certificate).read_text(encoding="utf-8"))
    bundle = raw.get("certificate_bundle", raw) if isinstance(raw, dict) else raw
    result = verify_wdl_certificate(bundle, allow_unknown_root=args.allow_unknown)
    _json_dump(result, args.out)
    return 0 if result["root_exact"] or args.allow_unknown else 2


def cmd_root_shards(args: argparse.Namespace) -> int:
    payload = {
        "schema": "ugts-chess-root-obligations-2.0",
        "root_fen": args.fen,
        "obligations": [item.to_dict() for item in root_obligations(Position.from_fen(args.fen))],
        "aggregate": "unknown",
    }
    _json_dump(payload, args.out)
    return 0


def cmd_campaign_init(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir)
    db = out_dir / "classical_root.sqlite3"
    shards = out_dir / "root_shards"
    payload = init_campaign(db, shards, root_fen=args.fen, force=args.force)
    export_meta = export_campaign(db, out_dir / "campaign_checkpoint.json")
    payload["checkpoint"] = export_meta
    _json_dump(payload, args.out)
    return 0


def cmd_campaign_status(args: argparse.Namespace) -> int:
    _json_dump(campaign_status(args.campaign), args.out)
    return 0


def cmd_campaign_verify(args: argparse.Namespace) -> int:
    result = verify_campaign(args.campaign)
    _json_dump(result, args.out)
    return 0 if result["valid"] else 2


def cmd_campaign_lease(args: argparse.Namespace) -> int:
    result = lease_next(args.campaign, args.worker, seconds=args.seconds)
    _json_dump({"leased": result is not None, "job": result}, args.out)
    return 0 if result is not None else 3


def cmd_campaign_candidate(args: argparse.Namespace) -> int:
    result = record_candidate(args.campaign, args.obligation, args.wdl, args.certificate, worker=args.worker)
    _json_dump(result, args.out)
    return 0


def cmd_campaign_mark_verified(args: argparse.Namespace) -> int:
    result = mark_verified(args.campaign, args.obligation, verifier=args.verifier, checker_record=args.checker)
    _json_dump(result, args.out)
    return 0


def cmd_campaign_reject(args: argparse.Namespace) -> int:
    result = reject_candidate(args.campaign, args.obligation, verifier=args.verifier, reason=args.reason)
    _json_dump(result, args.out)
    return 0


def cmd_campaign_export(args: argparse.Namespace) -> int:
    _json_dump(export_campaign(args.campaign, args.output), args.out)
    return 0


def cmd_gpu_config(args: argparse.Namespace) -> int:
    _json_dump(recommended_rtx5070ti_config(), args.out)
    return 0


def cmd_gpu_batch(args: argparse.Namespace) -> int:
    positions = [_load_position(fen) for fen in args.fen]
    result = run_batch(args.executable, positions, args.work_dir)
    _json_dump(result, args.out)
    return 0 if not result["mismatches"] else 2


def cmd_gpu_qualify(args: argparse.Namespace) -> int:
    result = qualify_gpu_move_generator(
        args.executable,
        args.work_dir,
        seed=args.seed,
        random_positions=args.random_positions,
        max_plies=args.max_plies,
        chunk_size=args.chunk_size,
    )
    _json_dump(result, args.out)
    return 0 if result["qualified"] else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ugts-chess", description="UGTS Chess 2.0 proof-oriented classical-chess solver")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("info", help="print version, capabilities and evidence boundary").set_defaults(func=cmd_info)

    p = sub.add_parser("validate", help="validate a FEN and enumerate legal moves")
    p.add_argument("--fen", default=START_FEN); p.add_argument("--out"); p.set_defaults(func=cmd_validate)

    p = sub.add_parser("perft", help="count legal move paths")
    p.add_argument("--fen", default=START_FEN); p.add_argument("--depth", type=int, required=True)
    p.add_argument("--divide", action="store_true"); p.add_argument("--out"); p.set_defaults(func=cmd_perft)

    p = sub.add_parser("solve", help="run bounded deterministic heuristic alpha-beta search")
    p.add_argument("--fen", default=START_FEN); p.add_argument("--depth", type=int, default=5); p.add_argument("--time", type=float)
    p.add_argument("--tt-capacity", type=int, default=500_000); p.add_argument("--ignore-claimable-draws", action="store_true")
    p.add_argument("--out"); p.set_defaults(func=cmd_solve)

    p = sub.add_parser("prove-mate", help="prove a forced mate within a finite ply horizon")
    p.add_argument("--fen", required=True); p.add_argument("--plies", type=int, required=True)
    p.add_argument("--attacker", choices=("white", "black")); p.add_argument("--node-budget", type=int, default=2_000_000)
    p.add_argument("--out"); p.set_defaults(func=cmd_prove_mate)

    p = sub.add_parser("verify-proof", help="independently verify a mate proof JSON")
    p.add_argument("proof"); p.add_argument("--out"); p.set_defaults(func=cmd_verify_proof)

    p = sub.add_parser("probe", help="probe the bundled exact KQK/KRK tablebase")
    p.add_argument("--fen", required=True); p.add_argument("--piece", choices=("Q", "R")); p.add_argument("--tablebase")
    p.add_argument("--out"); p.set_defaults(func=cmd_probe)

    p = sub.add_parser("generate-tablebase", help="rebuild a KQK or KRK tablebase")
    p.add_argument("--piece", choices=("Q", "R"), required=True); p.add_argument("--out", required=True); p.add_argument("--metadata-out")
    p.set_defaults(func=cmd_generate_tablebase)

    p = sub.add_parser("demo", help="run deterministic built-in evidence examples")
    p.add_argument("--out"); p.set_defaults(func=cmd_demo)

    p = sub.add_parser("game-status", help="show forced terminal status and optional draw claims")
    p.add_argument("--fen", default=START_FEN); p.add_argument("--out"); p.set_defaults(func=cmd_game_status)

    p = sub.add_parser("bounded-wdl", help="attempt an exact bounded WDL certificate; open cutoffs remain UNKNOWN")
    p.add_argument("--fen", default=START_FEN); p.add_argument("--plies", type=int, required=True)
    p.add_argument("--node-budget", type=int, default=1_000_000); p.add_argument("--time", type=float); p.add_argument("--out")
    p.set_defaults(func=cmd_bounded_wdl)

    p = sub.add_parser("verify-wdl", help="independently verify a WDL certificate bundle")
    p.add_argument("certificate"); p.add_argument("--allow-unknown", action="store_true"); p.add_argument("--out")
    p.set_defaults(func=cmd_verify_wdl)

    p = sub.add_parser("root-shards", help="emit the 20 exact initial-position root obligations")
    p.add_argument("--fen", default=START_FEN); p.add_argument("--out"); p.set_defaults(func=cmd_root_shards)

    p = sub.add_parser("campaign-init", help="create the hash-chained initial-position campaign database and root shards")
    p.add_argument("--out-dir", required=True); p.add_argument("--fen", default=START_FEN); p.add_argument("--force", action="store_true")
    p.add_argument("--out"); p.set_defaults(func=cmd_campaign_init)

    p = sub.add_parser("campaign-status", help="show aggregate proof-campaign state")
    p.add_argument("campaign"); p.add_argument("--out"); p.set_defaults(func=cmd_campaign_status)

    p = sub.add_parser("campaign-verify", help="recompute root obligations, file hashes and event chain")
    p.add_argument("campaign"); p.add_argument("--out"); p.set_defaults(func=cmd_campaign_verify)

    p = sub.add_parser("campaign-lease", help="lease one unresolved root obligation")
    p.add_argument("campaign"); p.add_argument("--worker", required=True); p.add_argument("--seconds", type=int, default=900)
    p.add_argument("--out"); p.set_defaults(func=cmd_campaign_lease)

    p = sub.add_parser("campaign-candidate", help="attach a candidate WDL certificate; it remains unverified")
    p.add_argument("campaign"); p.add_argument("--obligation", required=True); p.add_argument("--wdl", choices=("win", "draw", "loss"), required=True)
    p.add_argument("--certificate", required=True); p.add_argument("--worker", required=True); p.add_argument("--out")
    p.set_defaults(func=cmd_campaign_candidate)

    p = sub.add_parser("campaign-mark-verified", help="record an independent checker result for a candidate")
    p.add_argument("campaign"); p.add_argument("--obligation", required=True); p.add_argument("--verifier", required=True)
    p.add_argument("--checker", required=True); p.add_argument("--out"); p.set_defaults(func=cmd_campaign_mark_verified)

    p = sub.add_parser("campaign-reject", help="reject a candidate or lease with a reason-coded event")
    p.add_argument("campaign"); p.add_argument("--obligation", required=True); p.add_argument("--verifier", required=True)
    p.add_argument("--reason", required=True); p.add_argument("--out"); p.set_defaults(func=cmd_campaign_reject)

    p = sub.add_parser("campaign-export", help="export a canonical JSON checkpoint from the SQLite campaign")
    p.add_argument("campaign"); p.add_argument("--output", required=True); p.add_argument("--out"); p.set_defaults(func=cmd_campaign_export)

    p = sub.add_parser("gpu-config", help="print the conservative RTX 5070 Ti Laptop 12 GB CUDA profile")
    p.add_argument("--out"); p.set_defaults(func=cmd_gpu_config)

    p = sub.add_parser("gpu-batch", help="run the C++/CUDA proposal expander and independently verify every legal move")
    p.add_argument("--executable", required=True); p.add_argument("--fen", action="append", required=True)
    p.add_argument("--work-dir", default="validation/gpu_batch"); p.add_argument("--out"); p.set_defaults(func=cmd_gpu_batch)

    p = sub.add_parser("gpu-qualify", help="proof-gate CUDA move generation on deterministic fixtures and reachable positions")
    p.add_argument("--executable", required=True)
    p.add_argument("--seed", type=lambda value: int(value, 0), default=DEFAULT_SEED)
    p.add_argument("--random-positions", "--random-count", dest="random_positions", type=int, default=DEFAULT_RANDOM_POSITIONS)
    p.add_argument("--max-plies", type=int, default=DEFAULT_MAX_PLIES)
    p.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    p.add_argument("--work-dir", default="validation/gpu_qualification"); p.add_argument("--out")
    p.set_defaults(func=cmd_gpu_qualify)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (ValueError, RuntimeError, OSError, KeyError, PermissionError) as exc:
        parser.exit(1, f"error: {exc}\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
