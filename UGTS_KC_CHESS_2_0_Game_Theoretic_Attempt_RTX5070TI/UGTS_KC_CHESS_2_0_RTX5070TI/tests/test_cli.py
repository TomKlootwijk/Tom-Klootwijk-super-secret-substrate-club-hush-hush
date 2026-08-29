from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from ugts_chess.cli import main


class CLITests(unittest.TestCase):
    def capture(self, argv: list[str]) -> tuple[int, dict[str, object]]:
        stream = io.StringIO()
        with redirect_stdout(stream):
            code = main(argv)
        return code, json.loads(stream.getvalue())

    def test_01_info(self) -> None:
        code, data = self.capture(["info"])
        self.assertEqual(code, 0)
        self.assertEqual(data["version"], "2.0.0")

    def test_02_perft(self) -> None:
        code, data = self.capture(["perft", "--depth", "2"])
        self.assertEqual(code, 0)
        self.assertEqual(data["nodes"], 400)

    def test_03_probe(self) -> None:
        code, data = self.capture(["probe", "--fen", "8/8/8/8/8/k7/8/1QK5 w - - 0 1"])
        self.assertEqual(code, 0)
        self.assertEqual(data["dtm_plies"], 3)

    def test_04_proof_file_and_verify(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proof = Path(tmp) / "proof.json"
            code = main([
                "prove-mate",
                "--fen",
                "8/8/8/8/8/k7/8/1QK5 w - - 0 1",
                "--plies",
                "3",
                "--out",
                str(proof),
            ])
            self.assertEqual(code, 0)
            code, data = self.capture(["verify-proof", str(proof)])
            self.assertEqual(code, 0)
            self.assertTrue(data["valid"])


if __name__ == "__main__":
    unittest.main()
