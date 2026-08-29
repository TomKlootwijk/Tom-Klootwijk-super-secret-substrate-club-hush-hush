from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.claim_gate import (
    CANONICAL_ROOT_DIGEST,
    CANONICAL_RULES,
    validate_unknown_preflight,
)


def canonical_unknown_payload() -> dict:
    return {
        "rules": dict(CANONICAL_RULES),
        "root_digest": CANONICAL_ROOT_DIGEST,
        "result": {
            "status": "UNKNOWN",
            "threshold2": 1,
            "proof_number": 1,
            "disproof_number": 362,
            "proof_arithmetic": {
                "bits": 64,
                "endianness": "little",
                "infinity": "18446744073709551615",
                "kind": "saturating_uint64",
            },
        },
    }


class ClaimGateTests(unittest.TestCase):
    def test_accepts_only_the_canonical_unknown_envelope(self) -> None:
        validate_unknown_preflight(canonical_unknown_payload())

    def test_rejects_noncanonical_rules_root_and_threshold(self) -> None:
        cases: list[tuple[str, tuple[str, ...], object]] = [
            ("rules", ("rules", "komi2"), 13),
            ("root", ("root_digest",), "0" * 64),
            ("threshold", ("result", "threshold2"), 3),
            ("arithmetic", ("result", "proof_arithmetic", "bits"), 60),
        ]
        for name, path, value in cases:
            with self.subTest(name=name):
                payload = copy.deepcopy(canonical_unknown_payload())
                target = payload
                for part in path[:-1]:
                    target = target[part]
                target[path[-1]] = value
                with self.assertRaises(ValueError):
                    validate_unknown_preflight(payload)

    def test_rejects_final_or_internally_solved_unknown_status(self) -> None:
        cases: list[tuple[str, object]] = [
            ("status", "PROVEN"),
            ("proof_number", 0),
            ("disproof_number", 0),
            ("proof_number", True),
            ("disproof_number", None),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                payload = copy.deepcopy(canonical_unknown_payload())
                payload["result"][field] = value
                with self.assertRaises(ValueError):
                    validate_unknown_preflight(payload)


if __name__ == "__main__":
    unittest.main()
