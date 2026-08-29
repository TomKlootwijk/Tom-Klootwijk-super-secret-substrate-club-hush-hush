from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from _bootstrap import ROOT
from ugts5.canonical import canonical_bytes, content_hash, load_json, sha256_hex, write_json


class CanonicalTests(unittest.TestCase):
    def test_key_order_does_not_change_bytes(self):
        self.assertEqual(canonical_bytes({"b": 2, "a": 1}), canonical_bytes({"a": 1, "b": 2}))

    def test_unicode_is_not_ascii_escaped(self):
        data = canonical_bytes({"literal": "∈"})
        self.assertIn("∈".encode("utf-8"), data)
        self.assertNotIn(b"\\u2208", data)

    def test_content_hash_excludes_hash_field(self):
        record = {"id": "x", "value": 3}
        h = content_hash(record)
        record["content_hash"] = h
        self.assertEqual(content_hash(record), h)

    def test_sha256_matches_hashlib(self):
        value = {"x": [1, 2, 3]}
        self.assertEqual(sha256_hex(value), hashlib.sha256(canonical_bytes(value)).hexdigest())

    def test_write_and_load_json(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "x.json"
            write_json(path, {"literal": "∋", "n": 1})
            self.assertEqual(load_json(path)["literal"], "∋")

    def test_release_record_identity(self):
        release = load_json(ROOT / "spec" / "release_record.json")
        self.assertEqual(release["canonical_identity"], "ugts.foundation.unicode-set-field-klein-converse@5.0.0")


if __name__ == "__main__":
    unittest.main()
