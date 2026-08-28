from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from ugts_spatial.novelty import NoveltyLog
from ugts_spatial.schema import RelationType


class NoveltyTests(unittest.TestCase):
    def test_hash_linked_append_and_tamper_detection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.ugnl"
            log = NoveltyLog(path, seed=1234)
            log.create()
            first = log.append_verified(
                timestamp=1.0,
                relation=int(RelationType.NEAR),
                source_id=10,
                target_id=20,
                value=12.5,
                confidence=0.9,
                lineage_hash=111,
            )
            second = log.append_verified(
                timestamp=2.0,
                relation=int(RelationType.CROSSED_GUARD),
                source_id=20,
                target_id=30,
                value=-0.25,
                confidence=0.95,
                lineage_hash=222,
            )
            self.assertEqual(first.sequence, 0)
            self.assertEqual(second.prev_hash, first.self_hash)
            summary = log.validate()
            self.assertTrue(summary["valid"])
            self.assertEqual(summary["records"], 2)
            rows = list(log)
            self.assertEqual([row.sequence for row in rows], [0, 1])

            payload = bytearray(path.read_bytes())
            payload[-10] ^= 0x20
            tampered = Path(directory) / "tampered.ugnl"
            tampered.write_bytes(payload)
            with self.assertRaises(ValueError):
                NoveltyLog(tampered).validate()


if __name__ == "__main__":
    unittest.main()
