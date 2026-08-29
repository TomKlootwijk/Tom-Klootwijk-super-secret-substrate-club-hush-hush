"""Command-line interface for validation and solver campaigns."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from .certificate import (
    load_certificate,
    make_certificate,
    save_certificate,
    verify_certificate,
)
from .codec import pack_board_2bit, unpack_board_2bit
from .digests import state_digest
from .exact import ExactSolver, SearchBudgetExceeded
from .frontier import canonical_frontier
from .memory import GIB, plan_memory
from .pndag import ProofNumberDAG
from .pns import ProofNumberSearch
from .rules import Rules
from .state import State


def _write_or_print(payload: dict, output: str | None) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(text, encoding="utf-8")
    print(text, end="")


def _paths_alias(left: Path, right: Path) -> bool:
    """Return whether two publication paths name the same filesystem object."""

    if left.resolve(strict=False) == right.resolve(strict=False):
        return True
    try:
        return left.samefile(right)
    except (FileNotFoundError, OSError):
        return False


def cmd_selftest(_args: argparse.Namespace) -> int:
    rules = Rules(size=19)
    state = State.initial(rules)
    packed = pack_board_2bit(state.board)
    assert len(packed) == 91
    assert unpack_board_2bit(packed, 361) == state.board
    frontier, summary = canonical_frontier(rules, depth=1)
    # 361 points have 55 D4 orbits on an odd 19x19 grid; pass adds one.
    assert summary.canonical_states == 56, summary
    payload = {
        "ok": True,
        "version": "4.3.0",
        "packed_empty_board_bytes": len(packed),
        "opening_d4_classes_including_pass": len(frontier),
        "root_digest": state_digest(state, rules),
    }
    _write_or_print(payload, None)
    return 0


def _tiny_rules(size: int, komi2: int) -> Rules:
    return Rules(
        size=size,
        komi2=komi2,
        profile_id=f"UGTS-TINY-{size}x{size}-AREA-PSK-K{komi2}/2",
    )


def cmd_solve_tiny(args: argparse.Namespace) -> int:
    rules = _tiny_rules(args.size, args.komi2)
    state = State.initial(rules)
    try:
        result = ExactSolver(
            rules,
            node_budget=args.node_budget,
            time_budget_seconds=args.time_budget,
            use_symmetry=args.symmetry,
        ).solve(state)
    except SearchBudgetExceeded as exc:
        _write_or_print(
            {
                "status": "UNKNOWN",
                "reason": str(exc),
                "rules": rules.as_dict(),
                "root_digest": state_digest(state, rules),
            },
            args.output,
        )
        return 2
    payload = {
        "status": "EXACT",
        "rules": rules.as_dict(),
        "root_digest": state_digest(state, rules),
        "result": result.as_dict(rules),
    }
    if args.certificate:
        cert = make_certificate(rules, state, node_budget=args.node_budget)
        save_certificate(args.certificate, cert)
        payload["certificate"] = str(args.certificate)
        payload["certificate_sha256"] = cert["certificate_sha256"]
    _write_or_print(payload, args.output)
    return 0


def cmd_attempt19(args: argparse.Namespace) -> int:
    rules = Rules.canonical_19x19()
    root = State.initial(rules)
    result = ProofNumberSearch(
        rules=rules,
        threshold2=args.threshold2,
        node_budget=args.node_budget,
    ).run(root)
    payload = {
        "campaign": "unrestricted mathematical game; bounded execution attempt",
        "claim_boundary": (
            "PROVEN/DISPROVEN is an exact threshold result only if reached; "
            "UNKNOWN is not evidence for either player."
        ),
        "rules": rules.as_dict(),
        "root_digest": state_digest(root, rules),
        "result": result.as_dict(),
    }
    _write_or_print(payload, args.output)
    return 0


def cmd_pndag_tiny(args: argparse.Namespace) -> int:
    """Advance the bounded, restartable 1x1/2x2 proof-DAG slice."""

    rules = _tiny_rules(args.size, args.komi2)
    root = State.initial(rules)
    checkpoint = Path(args.checkpoint)
    output = Path(args.output) if args.output is not None else None
    if output is not None and _paths_alias(checkpoint, output):
        raise SystemExit("--output must not refer to the checkpoint path")
    if args.resume:
        if not checkpoint.is_file():
            raise SystemExit(f"checkpoint does not exist: {checkpoint}")
        dag = ProofNumberDAG.load_checkpoint(
            checkpoint,
            expected_rules=rules,
            expected_root_state=root,
            expected_threshold2=args.threshold2,
        )
    else:
        if checkpoint.exists() and not args.overwrite:
            raise SystemExit(
                f"checkpoint already exists (use --resume or --overwrite): {checkpoint}"
            )
        dag = ProofNumberDAG(rules, args.threshold2, root)
    result = dag.advance(args.additional_expansions)
    if args.expect_status is not None and result.status != args.expect_status:
        return 2
    dag.save_checkpoint(checkpoint)
    checkpoint_payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    _write_or_print(
        {
            "campaign": "bounded tiny exact PNDAG persistence validation",
            "checkpoint": str(checkpoint),
            "checkpoint_sha256": checkpoint_payload["checkpoint_sha256"],
            "claim_boundary": (
                "This host-local checkpoint is not a standalone certificate and "
                "does not establish any 19x19 result."
            ),
            "result": result.as_dict(),
            "root_digest": state_digest(root, rules),
            "rules": rules.as_dict(),
        },
        str(output) if output is not None else None,
    )
    return 0


def cmd_frontier(args: argparse.Namespace) -> int:
    rules = Rules.canonical_19x19()
    states, summary = canonical_frontier(rules, args.depth)
    payload = {
        "rules": rules.as_dict(),
        "summary": summary.as_dict(),
        "state_digests": [state_digest(state, rules) for state in states[: args.limit]],
        "digests_truncated": len(states) > args.limit,
    }
    _write_or_print(payload, args.output)
    return 0


def cmd_plan_memory(args: argparse.Namespace) -> int:
    free_bytes = int(args.free_vram_gib * GIB)
    _write_or_print(plan_memory(free_bytes).as_dict(), args.output)
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    certificate = load_certificate(args.certificate)
    result = verify_certificate(certificate, node_budget=args.node_budget)
    _write_or_print(result, args.output)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ugts-go19",
        description="UGTS-KC 4.3 exactness-first Go solver foundation",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    selftest = sub.add_parser("selftest", help="run deterministic internal checks")
    selftest.set_defaults(func=cmd_selftest)

    tiny = sub.add_parser("solve-tiny", help="exactly solve a tiny empty board")
    tiny.add_argument("--size", type=int, default=2)
    tiny.add_argument("--komi2", type=int, default=1, help="komi in half-points")
    tiny.add_argument("--node-budget", type=int, default=2_000_000)
    tiny.add_argument("--time-budget", type=float, default=None)
    tiny.add_argument("--symmetry", action="store_true")
    tiny.add_argument("--certificate")
    tiny.add_argument("--output")
    tiny.set_defaults(func=cmd_solve_tiny)

    attempt = sub.add_parser(
        "attempt19", help="run a bounded threshold-proof attempt on empty 19x19"
    )
    attempt.add_argument("--threshold2", type=int, default=1)
    attempt.add_argument("--node-budget", type=int, default=64)
    attempt.add_argument("--output")
    attempt.set_defaults(func=cmd_attempt19)

    pndag = sub.add_parser(
        "pndag-tiny",
        help="advance/resume the bounded exact 1x1/2x2 proof-DAG slice",
    )
    pndag.add_argument("--size", type=int, choices=(1, 2), default=2)
    pndag.add_argument("--komi2", type=int, default=1, help="komi in half-points")
    pndag.add_argument("--threshold2", type=int, default=1)
    pndag.add_argument("--additional-expansions", type=int, default=64)
    pndag.add_argument("--checkpoint", required=True)
    pndag.add_argument("--resume", action="store_true")
    pndag.add_argument("--overwrite", action="store_true")
    pndag.add_argument(
        "--expect-status", choices=("PROVEN", "DISPROVEN", "UNKNOWN")
    )
    pndag.add_argument("--output")
    pndag.set_defaults(func=cmd_pndag_tiny)

    frontier = sub.add_parser("frontier", help="generate D4-canonical opening states")
    frontier.add_argument("--depth", type=int, default=1)
    frontier.add_argument("--limit", type=int, default=64)
    frontier.add_argument("--output")
    frontier.set_defaults(func=cmd_frontier)

    memory = sub.add_parser("plan-memory", help="derive a conservative VRAM budget")
    memory.add_argument("--free-vram-gib", type=float, default=10.0)
    memory.add_argument("--output")
    memory.set_defaults(func=cmd_plan_memory)

    verify = sub.add_parser("verify", help="recompute and verify a tiny certificate")
    verify.add_argument("certificate")
    verify.add_argument("--node-budget", type=int, default=2_000_000)
    verify.add_argument("--output")
    verify.set_defaults(func=cmd_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
