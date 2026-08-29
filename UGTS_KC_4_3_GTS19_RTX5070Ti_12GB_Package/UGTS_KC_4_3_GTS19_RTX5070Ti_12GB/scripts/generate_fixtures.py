#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from ugts_go19.certificate import make_certificate, save_certificate, verify_certificate
from ugts_go19.exact import ExactSolver
from ugts_go19.rules import Rules
from ugts_go19.state import State


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"


def main() -> int:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    summary = []
    for size, budget in ((1, 20_000), (2, 20_000)):
        rules = Rules(size=size, komi2=1, profile_id=f"UGTS-FIXTURE-{size}x{size}")
        state = State.initial(rules)
        result = ExactSolver(rules, node_budget=budget).solve(state)
        cert = make_certificate(rules, state, node_budget=budget)
        cert_path = FIXTURES / f"empty_{size}x{size}_certificate.json"
        save_certificate(cert_path, cert)
        verification = verify_certificate(cert, node_budget=budget)
        result_path = FIXTURES / f"empty_{size}x{size}_result.json"
        result_path.write_text(
            json.dumps(
                {
                    "status": "EXACT",
                    "rules": rules.as_dict(),
                    "result": result.as_dict(rules),
                    "certificate": cert_path.name,
                    "verification": verification,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        summary.append({"size": size, "value2": result.value2, "certificate": cert_path.name})
    (FIXTURES / "SUMMARY.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
