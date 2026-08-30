from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "packed_polar_gpu_lab_3d"


class PackedPolarGpuLabExampleTests(unittest.TestCase):
    def test_real_ecs_variants_and_evidence_boundary_stay_verified(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(EXAMPLE / "verify_example.py")],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(
            completed.returncode, 0, completed.stdout + completed.stderr
        )
        report = json.loads(completed.stdout)
        self.assertEqual(report["status"], "PASS")
        variants = report["variants"]
        self.assertEqual(
            [row["real_ecs_movers"] for row in variants],
            [64, 256, 1024],
        )
        self.assertTrue(all(row["graph_definitions"] == 1 for row in variants))
        self.assertEqual(
            [row["graph_bindings"] for row in variants],
            [64, 256, 1024],
        )
        self.assertTrue(all(row["render_pack_bytes"] == 32 for row in variants))
        self.assertEqual(
            variants[1]["kcpk_bytes"] - variants[0]["kcpk_bytes"],
            (256 - 64) * 24,
        )
        self.assertEqual(
            variants[2]["kcpk_bytes"] - variants[1]["kcpk_bytes"],
            (1024 - 256) * 24,
        )
        self.assertEqual(report["desktop_semantic_runtime"]["query_count"], 64)
        self.assertIn("requires", report["not_yet_proven"])


if __name__ == "__main__":
    unittest.main()
