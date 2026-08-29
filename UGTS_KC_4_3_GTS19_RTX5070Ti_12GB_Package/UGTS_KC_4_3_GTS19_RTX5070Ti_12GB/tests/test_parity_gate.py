from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.parity_gate import validate_parity_evidence


ARCHIVED_EVIDENCE = (
    ROOT / "evidence" / "local_m1_cpp_python_parity_v2_1m.json"
)
GATE = ROOT / "scripts" / "parity_gate.py"


def archived_payload() -> dict:
    return json.loads(ARCHIVED_EVIDENCE.read_text(encoding="utf-8"))


class ParityGateTests(unittest.TestCase):
    def assert_rejected(self, payload: object) -> None:
        with self.assertRaises(ValueError):
            validate_parity_evidence(payload)

    def test_accepts_archived_m1_campaign(self) -> None:
        validate_parity_evidence(archived_payload())

    def test_rejects_non_object_and_noncanonical_top_level_keys(self) -> None:
        self.assert_rejected([])

        missing = archived_payload()
        del missing["protocol"]
        self.assert_rejected(missing)

        extra = archived_payload()
        extra["claim"] = "solved"
        self.assert_rejected(extra)

    def test_rejects_wrong_pinned_metadata(self) -> None:
        cases = {
            "evidence_format": "UGTS-M1-PARITY-EVIDENCE-v1",
            "generator": "random",
            "hash_role": "state identity",
            "mode": "quick",
            "protocol": "UGTS_TRACE_V1",
            "root_status": "PROVEN",
            "state_object_id": "board-only-fnv",
            "seeds": [0x5EED19, 0xC0FFEF],
        }
        for field, value in cases.items():
            with self.subTest(field=field):
                payload = archived_payload()
                payload[field] = value
                self.assert_rejected(payload)

    def test_rejects_bool_as_integer(self) -> None:
        integer_fields = (
            "chunk_size",
            "chunks",
            "comparisons",
            "field_comparisons",
            "max_seen_boards",
            "mismatches",
            "states",
            "target_transitions",
            "transitions",
        )
        for field in integer_fields:
            with self.subTest(field=field):
                payload = archived_payload()
                payload[field] = True
                self.assert_rejected(payload)

        for field in ("elapsed_seconds", "transitions_per_second"):
            with self.subTest(field=field):
                payload = archived_payload()
                payload[field] = True
                self.assert_rejected(payload)

        payload = archived_payload()
        payload["cases_by_size"]["3"] = True
        self.assert_rejected(payload)

        payload = archived_payload()
        payload["seeds"][0] = True
        self.assert_rejected(payload)

    def test_rejects_missing_or_extra_board_sizes(self) -> None:
        for size in ("1", "3", "5", "9", "19"):
            with self.subTest(size=size):
                payload = archived_payload()
                del payload["cases_by_size"][size]
                self.assert_rejected(payload)

        payload = archived_payload()
        payload["cases_by_size"]["13"] = 1
        self.assert_rejected(payload)

    def test_rejects_nonpositive_counts_and_rates(self) -> None:
        fields = (
            "chunk_size",
            "chunks",
            "comparisons",
            "elapsed_seconds",
            "field_comparisons",
            "max_seen_boards",
            "states",
            "target_transitions",
            "transitions",
            "transitions_per_second",
        )
        for field in fields:
            for value in (0, -1):
                with self.subTest(field=field, value=value):
                    payload = archived_payload()
                    payload[field] = value
                    self.assert_rejected(payload)

        payload = archived_payload()
        payload["cases_by_size"]["19"] = 0
        self.assert_rejected(payload)

    def test_rejects_target_below_million_or_unmet(self) -> None:
        payload = archived_payload()
        payload["target_transitions"] = 999_999
        self.assert_rejected(payload)

        payload = archived_payload()
        payload["target_met"] = False
        self.assert_rejected(payload)

        payload = archived_payload()
        payload["transitions"] = payload["target_transitions"] - 1
        payload["comparisons"] = payload["states"] + payload["transitions"]
        self.assert_rejected(payload)

    def test_rejects_nonzero_mismatches(self) -> None:
        payload = archived_payload()
        payload["mismatches"] = 1
        self.assert_rejected(payload)

    def test_rejects_inconsistent_comparison_and_case_counts(self) -> None:
        payload = archived_payload()
        payload["comparisons"] += 1
        self.assert_rejected(payload)

        payload = archived_payload()
        payload["cases_by_size"]["3"] += 1
        self.assert_rejected(payload)

        payload = archived_payload()
        payload["field_comparisons"] += 1
        self.assert_rejected(payload)

    def test_rejects_invalid_corpus_sha256(self) -> None:
        for value in (None, "0" * 63, "G" * 64, "A" * 64):
            with self.subTest(value=value):
                payload = archived_payload()
                payload["corpus_sha256"] = value
                self.assert_rejected(payload)

    def test_cli_accepts_archive_without_making_a_solved_claim(self) -> None:
        process = subprocess.run(
            [sys.executable, str(GATE), str(ARCHIVED_EVIDENCE)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("root status remains UNKNOWN", process.stdout)
        self.assertNotIn("solved", process.stdout.lower())

    def test_cli_rejects_duplicate_json_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text('{"protocol":"a","protocol":"b"}', encoding="utf-8")
            process = subprocess.run(
                [sys.executable, str(GATE), str(path)],
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("duplicate JSON key", process.stderr)


if __name__ == "__main__":
    unittest.main()
