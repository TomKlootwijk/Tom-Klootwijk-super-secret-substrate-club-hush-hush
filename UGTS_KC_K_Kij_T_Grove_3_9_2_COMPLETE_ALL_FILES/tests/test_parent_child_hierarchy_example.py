from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "parent_child_hierarchy_3d"


class ParentChildHierarchyExampleTests(unittest.TestCase):
    def test_example_verifier_and_manual_project_stay_in_sync(self) -> None:
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
        self.assertEqual(
            report["status"], "source-level-desktop-and-native-pack-verified"
        )
        self.assertEqual(report["hierarchy"]["link_count"], 3)
        self.assertEqual(report["hierarchy"]["max_depth"], 2)
        self.assertEqual(report["packs"]["KCHI"]["bytes"], 48)
        self.assertIn("No physical phone", report["evidence_boundary"])


if __name__ == "__main__":
    unittest.main()
