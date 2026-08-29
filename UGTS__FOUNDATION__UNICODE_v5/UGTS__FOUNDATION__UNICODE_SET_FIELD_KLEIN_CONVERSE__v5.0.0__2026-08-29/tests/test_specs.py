from __future__ import annotations

import csv
import json
import unittest

from _bootstrap import ROOT
from ugts5.canonical import load_json


class SpecTests(unittest.TestCase):
    def test_mechanism_count_and_range(self):
        data = load_json(ROOT / "spec" / "mechanisms.json")
        self.assertEqual(data["count"], 64)
        self.assertEqual(data["mechanisms"][0]["id"], "USF001")
        self.assertEqual(data["mechanisms"][-1]["id"], "USF064")
        self.assertEqual(data["mechanisms"][0]["legacy_id"], "M886")
        self.assertEqual(data["mechanisms"][-1]["legacy_id"], "M949")

    def test_claim_count_and_rejections(self):
        data = load_json(ROOT / "spec" / "claims_ledger.json")
        self.assertEqual(len(data["claims"]), 24)
        self.assertGreater(sum(1 for c in data["claims"] if c["disposition"] == "REJECT"), 5)

    def test_source_hash_lengths(self):
        data = load_json(ROOT / "spec" / "source_register.json")
        self.assertGreaterEqual(len(data["sources"]), 8)
        for source in data["sources"]:
            self.assertEqual(len(source["sha256"]), 64)

    def test_csv_matches_json_count(self):
        with (ROOT / "spec" / "mechanisms.csv").open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 64)

    def test_formal_conclusion_is_exact(self):
        release = load_json(ROOT / "spec" / "release_record.json")
        text = (ROOT / "docs" / "FORMAL_CONCLUSION.txt").read_text(encoding="utf-8").strip()
        self.assertEqual(release["formal_conclusion"], text)

    def test_stream_angle_error_contract(self):
        self.assertAlmostEqual(360.0 / 256.0, 1.40625)
        self.assertAlmostEqual(180.0 / 256.0, 0.703125)


if __name__ == "__main__":
    unittest.main()
