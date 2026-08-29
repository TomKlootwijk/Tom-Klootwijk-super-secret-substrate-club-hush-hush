from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import ugts_chess.gpu_qualification as gpu_qualification
from ugts_chess.cli import main
from ugts_chess.gpu_qualification import (
    QUALIFICATION_FIXTURES,
    build_qualification_corpus,
    corpus_sha256,
    parse_backend_evidence,
    qualify_gpu_move_generator,
)


def artifact_evidence(backend_flag: int = 1) -> dict[str, object]:
    return {
        "input_sha256": "1" * 64,
        "output_sha256": "2" * 64,
        "output_semantic_payload_sha256": "3" * 64,
        "output_backend_flag": backend_flag,
        "executable": executable_evidence(),
    }


def executable_evidence(sha256: str = "4" * 64) -> dict[str, object]:
    return {
        "path": str(Path("C:/qualified/ugts-chess-gpu.exe")),
        "sha256": sha256,
        "size_bytes": 123456,
    }


def device_evidence(*, valid: bool = True) -> dict[str, object]:
    return {
        "valid": valid,
        "validation_failures": [] if valid else ["cuda_device_unavailable"],
        "device_index": 0,
        "payload": {
            "cuda_compiled": True,
            "device_available": valid,
            "device_index": 0,
            "name": "Test CUDA Device",
            "compute_capability": "12.0",
            "total_memory_bytes": 1024,
            "multiprocessors": 1,
            "error": "" if valid else "unavailable",
        },
        "executable": executable_evidence(),
        "claim_source": "same_executable_self_report",
        "independent_hardware_attestation": False,
    }


class GPUQualificationTests(unittest.TestCase):
    def setUp(self) -> None:
        identity_patcher = patch.object(
            gpu_qualification,
            "executable_identity",
            return_value=executable_evidence(),
        )
        device_patcher = patch.object(
            gpu_qualification,
            "probe_cuda_device",
            return_value=device_evidence(),
        )
        self.mocked_identity = identity_patcher.start()
        self.mocked_device_probe = device_patcher.start()
        self.addCleanup(identity_patcher.stop)
        self.addCleanup(device_patcher.stop)

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

        oracle_legal_moves = gpu_qualification.legal_moves
        with patch.object(
            gpu_qualification,
            "legal_moves",
            side_effect=lambda position: list(reversed(oracle_legal_moves(position))),
        ):
            reversed_oracle = build_qualification_corpus(seed=7, random_positions=5, max_plies=8)
        self.assertEqual(corpus_sha256(reversed_oracle), corpus_sha256(first))

    def test_02_backend_parser_is_conservative(self) -> None:
        cuda = parse_backend_evidence(
            '{"backend":"cuda","positions":2,"moves":5,"seconds":0.25,"cuda_fallback_reason":""}'
        )
        self.assertTrue(cuda["cuda_backend"])
        self.assertFalse(cuda["fallback_detected"])
        self.assertEqual(cuda["native_positions"], 2)
        self.assertEqual(cuda["native_moves"], 5)
        self.assertEqual(cuda["native_seconds"], 0.25)

        cpu = parse_backend_evidence(
            '{"backend":"cpu","positions":2,"moves":5,"seconds":0.1,"cuda_fallback_reason":"no device"}'
        )
        self.assertFalse(cpu["cuda_backend"])
        self.assertTrue(cpu["fallback_detected"])

        cuda_with_fallback = parse_backend_evidence(
            '{"backend":"cuda","positions":2,"moves":5,"seconds":0.1,'
            '"cuda_fallback_reason":"kernel launch failed"}'
        )
        self.assertTrue(cuda_with_fallback["cuda_backend"])
        self.assertTrue(cuda_with_fallback["fallback_detected"])

        malformed = parse_backend_evidence("not-json")
        self.assertTrue(malformed["fallback_detected"])
        self.assertIsNotNone(malformed["parse_error"])

        incomplete = parse_backend_evidence('{"backend":"cuda"}')
        self.assertTrue(incomplete["fallback_detected"])
        self.assertIn("fallback-reason", str(incomplete["parse_error"]))

        invented_cuda_prefix = parse_backend_evidence(
            '{"backend":"cuda-impostor","positions":2,"moves":5,"seconds":0.1,"cuda_fallback_reason":""}'
        )
        self.assertFalse(invented_cuda_prefix["cuda_backend"])
        self.assertTrue(invented_cuda_prefix["fallback_detected"])

        zero_time = parse_backend_evidence(
            '{"backend":"cuda","positions":2,"moves":5,"seconds":0,"cuda_fallback_reason":""}'
        )
        self.assertTrue(zero_time["fallback_detected"])
        self.assertIn("must be positive", str(zero_time["parse_error"]))

    @patch("ugts_chess.gpu_qualification.run_batch")
    def test_03_chunk_metrics_fallback_and_global_mismatch_index(self, mocked_run_batch) -> None:
        calls = 0

        def fake_run_batch(_executable, positions, _work_dir):
            nonlocal calls
            batch_index = calls
            calls += 1
            backend = ("cuda", "cuda-packed-candidate-sm-runtime", "cuda")[batch_index]
            fallback = "no CUDA device" if batch_index == 2 else ""
            native_seconds = (0.01, 0.02, 0.04)[batch_index]
            mismatches = []
            if batch_index == 1:
                mismatches = [{"index": 2, "fen": positions[2].to_fen(), "missing": ["e1g1"], "extra": []}]
            return {
                **artifact_evidence(),
                "executable_stdout": json.dumps(
                    {
                        "backend": backend,
                        "positions": len(positions),
                        "moves": len(positions) * 2,
                        "seconds": native_seconds,
                        "cuda_fallback_reason": fallback,
                    }
                ),
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
        self.assertEqual(result["end_to_end_batch_latency_ms"], {
            "p50": 200.0,
            "p95": 380.0,
            "p99": 396.0,
            "measurement": "end_to_end_run_batch_wall",
        })
        self.assertEqual(result["native_cuda_latency_ms"], {
            "p50": 15.0,
            "p95": 19.5,
            "p99": 19.9,
            "measurement": "native_executable_reported_cuda_expand_batch",
        })
        self.assertEqual(result["native_cuda_positions_per_second"], 400.0)
        self.assertEqual(result["native_cuda_moves_per_second"], 800.0)
        self.assertFalse(result["native_cuda_metrics_complete"])
        self.assertEqual(result["batches"][0]["native_positions"], 6)
        self.assertEqual(result["batches"][0]["native_moves"], 12)
        self.assertEqual(result["batches"][0]["native_seconds"], 0.01)
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
                **artifact_evidence(),
                "executable_stdout": json.dumps(
                    {
                        "backend": "cuda",
                        "positions": len(positions),
                        "moves": len(positions) * 3,
                        "seconds": 0.125,
                        "cuda_fallback_reason": "",
                    }
                ),
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
        self.assertEqual(result["end_to_end_positions_per_second"], 32.0)
        self.assertEqual(result["end_to_end_moves_per_second"], 96.0)
        self.assertEqual(result["native_cuda_positions_per_second"], 128.0)
        self.assertEqual(result["native_cuda_moves_per_second"], 384.0)
        self.assertTrue(result["native_cuda_metrics_complete"])
        self.assertTrue(result["backend_evidence_count_consistent"])
        self.assertTrue(result["artifact_evidence_consistent"])
        self.assertTrue(result["device_probe_valid"])
        self.assertTrue(result["executable_identity_stable"])
        self.assertEqual(result["executable"], executable_evidence())
        self.assertFalse(result["gpu_execution_independently_attested"])
        self.assertIn("does not independently prove", result["attestation_boundary"])
        self.assertEqual(result["batches"][0]["input_sha256"], "1" * 64)
        self.assertEqual(result["batches"][0]["output_sha256"], "2" * 64)
        self.assertEqual(result["batches"][0]["output_semantic_payload_sha256"], "3" * 64)
        self.assertEqual(result["batches"][0]["output_backend_flag"], 1)
        self.assertTrue(result["batches"][0]["native_positions_match_batch_size"])
        self.assertTrue(result["batches"][0]["native_moves_match_proposal_count"])
        self.assertTrue(result["batches"][0]["native_moves_match_verified_count"])

    @patch("ugts_chess.gpu_qualification.run_batch")
    def test_05_inconsistent_native_counts_fail_and_do_not_contribute_throughput(self, mocked_run_batch) -> None:
        def fake_run_batch(_executable, positions, _work_dir):
            proposal_moves = len(positions) * 3
            return {
                **artifact_evidence(),
                "executable_stdout": json.dumps(
                    {
                        "backend": "cuda",
                        "positions": len(positions) + 1,
                        "moves": proposal_moves + 1,
                        "seconds": 0.25,
                        "cuda_fallback_reason": "",
                    }
                ),
                "proposal_move_count": proposal_moves,
                "verified_move_count": proposal_moves,
                "mismatches": [],
            }

        mocked_run_batch.side_effect = fake_run_batch
        ticks = iter((4.0, 5.0))
        result = qualify_gpu_move_generator(
            "fake-gpu",
            "work",
            random_positions=0,
            max_plies=1,
            chunk_size=64,
            clock=lambda: next(ticks),
        )

        self.assertFalse(result["qualified"])
        self.assertTrue(result["all_batches_cuda"])
        self.assertEqual(result["failure_reasons"], ["backend_evidence_count_mismatch"])
        self.assertFalse(result["backend_evidence_count_consistent"])
        self.assertEqual(result["backend_evidence_failure_count"], 1)
        self.assertEqual(
            result["backend_evidence_failures"][0]["failures"],
            [
                "native_positions_vs_batch_size",
                "native_moves_vs_proposal_count",
                "native_moves_vs_verified_count",
            ],
        )
        batch = result["batches"][0]
        self.assertFalse(batch["native_positions_match_batch_size"])
        self.assertFalse(batch["native_moves_match_proposal_count"])
        self.assertFalse(batch["native_moves_match_verified_count"])
        self.assertFalse(batch["native_count_consistent"])
        self.assertEqual(result["native_cuda_batch_count"], 0)
        self.assertEqual(result["native_cuda_position_count"], 0)
        self.assertEqual(result["native_cuda_move_count"], 0)
        self.assertEqual(result["native_cuda_positions_per_second"], 0.0)
        self.assertEqual(result["native_cuda_moves_per_second"], 0.0)

    @patch("ugts_chess.gpu_qualification.run_batch")
    def test_06_stdout_cuda_with_cpu_output_flag_fails_gate(self, mocked_run_batch) -> None:
        def fake_run_batch(_executable, positions, _work_dir):
            moves = len(positions) * 2
            return {
                **artifact_evidence(backend_flag=0),
                "executable_stdout": json.dumps(
                    {
                        "backend": "cuda",
                        "positions": len(positions),
                        "moves": moves,
                        "seconds": 0.125,
                        "cuda_fallback_reason": "",
                    }
                ),
                "proposal_move_count": moves,
                "verified_move_count": moves,
                "mismatches": [],
            }

        mocked_run_batch.side_effect = fake_run_batch
        ticks = iter((0.0, 0.5))
        result = qualify_gpu_move_generator(
            "fake-gpu",
            "work",
            random_positions=0,
            max_plies=1,
            chunk_size=64,
            clock=lambda: next(ticks),
        )

        self.assertFalse(result["qualified"])
        self.assertTrue(result["all_batches_cuda"])
        self.assertEqual(result["failure_reasons"], ["backend_artifact_evidence_mismatch"])
        self.assertFalse(result["artifact_evidence_consistent"])
        self.assertEqual(
            result["artifact_evidence_failures"][0]["failures"],
            ["output_backend_flag_vs_stdout"],
        )
        self.assertEqual(result["native_cuda_batch_count"], 0)

    @patch("ugts_chess.gpu_qualification.run_batch")
    def test_07_missing_or_malformed_artifact_hashes_fail_gate(self, mocked_run_batch) -> None:
        def fake_run_batch(_executable, positions, _work_dir):
            moves = len(positions) * 2
            return {
                "input_sha256": "not-a-hash",
                "output_sha256": None,
                "output_semantic_payload_sha256": "A" * 64,
                "output_backend_flag": 1,
                "executable": executable_evidence(),
                "executable_stdout": json.dumps(
                    {
                        "backend": "cuda",
                        "positions": len(positions),
                        "moves": moves,
                        "seconds": 0.125,
                        "cuda_fallback_reason": "",
                    }
                ),
                "proposal_move_count": moves,
                "verified_move_count": moves,
                "mismatches": [],
            }

        mocked_run_batch.side_effect = fake_run_batch
        ticks = iter((0.0, 0.5))
        result = qualify_gpu_move_generator(
            "fake-gpu",
            "work",
            random_positions=0,
            max_plies=1,
            chunk_size=64,
            clock=lambda: next(ticks),
        )

        self.assertFalse(result["qualified"])
        self.assertEqual(result["failure_reasons"], ["backend_artifact_evidence_mismatch"])
        self.assertEqual(
            result["artifact_evidence_failures"][0]["failures"],
            [
                "input_sha256_missing_or_invalid",
                "output_sha256_missing_or_invalid",
                "output_semantic_payload_sha256_missing_or_invalid",
            ],
        )

    @patch("ugts_chess.gpu_qualification.run_batch")
    def test_08_unavailable_device_probe_fails_otherwise_exact_gate(self, mocked_run_batch) -> None:
        self.mocked_device_probe.return_value = device_evidence(valid=False)

        def fake_run_batch(_executable, positions, _work_dir):
            moves = len(positions) * 2
            return {
                **artifact_evidence(),
                "executable_stdout": json.dumps(
                    {
                        "backend": "cuda",
                        "positions": len(positions),
                        "moves": moves,
                        "seconds": 0.125,
                        "cuda_fallback_reason": "",
                    }
                ),
                "proposal_move_count": moves,
                "verified_move_count": moves,
                "mismatches": [],
            }

        mocked_run_batch.side_effect = fake_run_batch
        ticks = iter((0.0, 0.5))
        result = qualify_gpu_move_generator(
            "fake-gpu",
            "work",
            random_positions=0,
            max_plies=1,
            chunk_size=64,
            clock=lambda: next(ticks),
        )

        self.assertFalse(result["qualified"])
        self.assertEqual(result["failure_reasons"], ["cuda_device_probe_failed"])
        self.assertFalse(result["device_probe_valid"])
        self.assertEqual(result["native_cuda_batch_count"], 0)

    @patch("ugts_chess.gpu_qualification.run_batch")
    def test_09_changed_executable_identity_fails_otherwise_exact_gate(self, mocked_run_batch) -> None:
        def fake_run_batch(_executable, positions, _work_dir):
            moves = len(positions) * 2
            evidence = artifact_evidence()
            evidence["executable"] = executable_evidence("5" * 64)
            return {
                **evidence,
                "executable_stdout": json.dumps(
                    {
                        "backend": "cuda",
                        "positions": len(positions),
                        "moves": moves,
                        "seconds": 0.125,
                        "cuda_fallback_reason": "",
                    }
                ),
                "proposal_move_count": moves,
                "verified_move_count": moves,
                "mismatches": [],
            }

        mocked_run_batch.side_effect = fake_run_batch
        ticks = iter((0.0, 0.5))
        result = qualify_gpu_move_generator(
            "fake-gpu",
            "work",
            random_positions=0,
            max_plies=1,
            chunk_size=64,
            clock=lambda: next(ticks),
        )

        self.assertFalse(result["qualified"])
        self.assertEqual(result["failure_reasons"], ["executable_identity_mismatch"])
        self.assertFalse(result["executable_identity_stable"])
        self.assertEqual(result["executable_identity_failure_count"], 1)
        self.assertEqual(result["native_cuda_batch_count"], 0)

    @patch("ugts_chess.gpu_qualification.run_batch")
    def test_10_executable_replaced_after_batches_fails_final_identity_check(self, mocked_run_batch) -> None:
        self.mocked_identity.side_effect = [executable_evidence(), executable_evidence("5" * 64)]

        def fake_run_batch(_executable, positions, _work_dir):
            moves = len(positions) * 2
            return {
                **artifact_evidence(),
                "executable_stdout": json.dumps(
                    {
                        "backend": "cuda",
                        "positions": len(positions),
                        "moves": moves,
                        "seconds": 0.125,
                        "cuda_fallback_reason": "",
                    }
                ),
                "proposal_move_count": moves,
                "verified_move_count": moves,
                "mismatches": [],
            }

        mocked_run_batch.side_effect = fake_run_batch
        ticks = iter((0.0, 0.5))
        result = qualify_gpu_move_generator(
            "fake-gpu",
            "work",
            random_positions=0,
            max_plies=1,
            chunk_size=64,
            clock=lambda: next(ticks),
        )

        self.assertFalse(result["qualified"])
        self.assertEqual(result["failure_reasons"], ["executable_identity_mismatch"])
        self.assertEqual(result["executable_identity_failures"][0]["stage"], "qualification_end")
        self.assertEqual(result["final_executable"]["sha256"], "5" * 64)

    @patch("ugts_chess.cli.qualify_gpu_move_generator")
    def test_11_cli_returns_nonzero_when_gate_fails(self, mocked_qualify) -> None:
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
