from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ugts_chess.cli import main
from ugts_chess.gpu_qualification import (
    QUALIFICATION_FIXTURES,
    build_qualification_corpus,
    corpus_sha256,
    parse_backend_evidence,
    qualify_gpu_move_generator,
)


class GPUQualificationTests(unittest.TestCase):
    def test_01_corpus_is_deterministic_and_fixture_first(self) -> None:
        first = build_qualification_corpus(seed=7, random_positions=5, max_plies=8)
        second = build_qualification_corpus(seed=7, random_positions=5, max_plies=8)
        different = build_qualification_corpus(seed=8, random_positions=5, max_plies=8)

        self.assertEqual([item.position.to_fen() for item in first], [item.position.to_fen() for item in second])
        self.assertNotEqual([item.position.to_fen() for item in first], [item.position.to_fen() for item in different])
        self.assertEqual(len(first), len(QUALIFICATION_FIXTURES) + 5)
        self.assertEqual(first[0].label, "perft_initial")
        self.assertTrue(all(item.source == "seeded_random_reachable" for item in first[len(QUALIFICATION_FIXTURES) :]))
        self.assertEqual(corpus_sha256(first), "0a27d35af12f252a2919a40be3000afdcae3c0953456a6fa3858ce8ba9aad37d")

    def test_02_backend_parser_is_conservative(self) -> None:
        cuda = parse_backend_evidence('{"backend":"cuda","cuda_fallback_reason":""}')
        self.assertTrue(cuda["cuda_backend"])
        self.assertFalse(cuda["fallback_detected"])

        cpu = parse_backend_evidence('{"backend":"cpu","cuda_fallback_reason":"no device"}')
        self.assertFalse(cpu["cuda_backend"])
        self.assertTrue(cpu["fallback_detected"])

        malformed = parse_backend_evidence("not-json")
        self.assertTrue(malformed["fallback_detected"])
        self.assertIsNotNone(malformed["parse_error"])

        incomplete = parse_backend_evidence('{"backend":"cuda"}')
        self.assertTrue(incomplete["fallback_detected"])
        self.assertIn("fallback-reason", str(incomplete["parse_error"]))

    @patch("ugts_chess.gpu_qualification.run_batch")
    def test_03_chunk_metrics_fallback_and_global_mismatch_index(self, mocked_run_batch) -> None:
        calls = 0

        def fake_run_batch(_executable, positions, _work_dir):
            nonlocal calls
            batch_index = calls
            calls += 1
            backend = ("cuda", "cuda-packed-candidate-sm-runtime", "cpu")[batch_index]
            fallback = "no CUDA device" if batch_index == 2 else ""
            mismatches = []
            if batch_index == 1:
                mismatches = [{"index": 2, "fen": positions[2].to_fen(), "missing": ["e1g1"], "extra": []}]
            return {
                "executable_stdout": json.dumps({"backend": backend, "cuda_fallback_reason": fallback}),
                "proposal_move_count": len(positions) * 2,
                "verified_move_count": len(positions) * 2,
                "mismatches": mismatches,
            }

        mocked_run_batch.side_effect = fake_run_batch
        ticks = iter((0.0, 0.1, 0.1, 0.3, 0.3, 0.7))
        with tempfile.TemporaryDirectory() as temp:
            result = qualify_gpu_move_generator(
                "fake-gpu",
                temp,
                seed=1,
                random_positions=0,
                max_plies=1,
                chunk_size=6,
                clock=lambda: next(ticks),
            )

        self.assertFalse(result["qualified"])
        self.assertEqual(result["batch_count"], 3)
        self.assertEqual(result["batch_latency_ms"], {
            "p50": 200.0,
            "p95": 380.0,
            "p99": 396.0,
            "measurement": "end_to_end_run_batch_wall",
        })
        self.assertEqual(result["fallback_batches"][0]["batch_index"], 2)
        self.assertEqual(result["mismatch_count"], 1)
        mismatch = result["mismatches"][0]
        self.assertEqual(mismatch["batch_local_index"], 2)
        self.assertEqual(mismatch["global_index"], 8)
        self.assertEqual(mismatch["index"], 8)
        self.assertEqual(mismatch["corpus_label"], "castle_through_attack")
        self.assertEqual(result["failure_reasons"], ["move_set_mismatch", "non_cuda_or_fallback_batch"])

    @patch("ugts_chess.gpu_qualification.run_batch")
    def test_04_all_cuda_and_exact_qualifies(self, mocked_run_batch) -> None:
        def fake_run_batch(_executable, positions, _work_dir):
            return {
                "executable_stdout": '{"backend":"cuda","cuda_fallback_reason":""}',
                "proposal_move_count": len(positions) * 3,
                "verified_move_count": len(positions) * 3,
                "mismatches": [],
            }

        mocked_run_batch.side_effect = fake_run_batch
        ticks = iter((2.0, 2.5))
        result = qualify_gpu_move_generator(
            Path("fake-gpu"),
            Path("work"),
            random_positions=0,
            max_plies=1,
            chunk_size=64,
            clock=lambda: next(ticks),
        )
        self.assertTrue(result["qualified"])
        self.assertTrue(result["all_batches_cuda"])
        self.assertEqual(result["mismatches"], [])
        self.assertEqual(result["positions_per_second"], 32.0)
        self.assertEqual(result["moves_per_second"], 96.0)

    @patch("ugts_chess.cli.qualify_gpu_move_generator")
    def test_05_cli_returns_nonzero_when_gate_fails(self, mocked_qualify) -> None:
        mocked_qualify.return_value = {"qualified": False, "failure_reasons": ["non_cuda_or_fallback_batch"]}
        stream = io.StringIO()
        with redirect_stdout(stream):
            code = main([
                "gpu-qualify",
                "--executable",
                "fake-gpu",
                "--seed",
                "0x2a",
                "--random-count",
                "3",
                "--max-plies",
                "4",
                "--chunk-size",
                "2",
            ])
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(stream.getvalue())["qualified"])
        self.assertEqual(mocked_qualify.call_args.kwargs["seed"], 42)
        self.assertEqual(mocked_qualify.call_args.kwargs["random_positions"], 3)


if __name__ == "__main__":
    unittest.main()
