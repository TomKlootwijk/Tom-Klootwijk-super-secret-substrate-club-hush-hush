from __future__ import annotations

from copy import deepcopy
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator, ValidationError

import ugts_chess.gpu_qualification as gpu_qualification
from ugts_chess.cli import main
from ugts_chess.gpu_qualification import (
    GPUQualificationRecordError,
    QUALIFICATION_PROFILE,
    QUALIFICATION_SCHEMA,
    QUALIFICATION_FIXTURES,
    build_qualification_corpus,
    corpus_sha256,
    parse_backend_evidence,
    qualify_gpu_move_generator,
    validate_gpu_qualification_record_structure,
    verify_gpu_qualification_record,
)
from ugts_chess.gpu_protocol import (
    MAX_MOVES,
    OUTPUT_HEADER,
    OUTPUT_MAGIC,
    encode_move16,
    encode_position_batch,
)
from ugts_chess.rules import legal_moves


def artifact_evidence(position_count: int, backend_flag: int = 1) -> dict[str, object]:
    invocation_id = "a" * 32
    invocation_dir = Path("C:/qualified/work") / f"run-{invocation_id}"
    return {
        "invocation_id": invocation_id,
        "invocation_dir": str(invocation_dir),
        "input_sha256": "1" * 64,
        "input": {
            "path": str(invocation_dir / "positions.ugcb"),
            "count": position_count,
            "record_size": 64,
            "sha256": "1" * 64,
        },
        "output_sha256": "2" * 64,
        "output_semantic_payload_sha256": "3" * 64,
        "output_backend_flag": backend_flag,
        "output": {
            "path": str(invocation_dir / "moves.ugmv"),
            "count": position_count,
            "backend_flag": backend_flag,
            "backend": "cuda" if backend_flag == 1 else "cpu",
            "bytes": 1024,
            "sha256": "2" * 64,
            "semantic_payload_sha256": "3" * 64,
        },
        "executable": executable_evidence(),
    }


def executable_evidence(sha256: str = "4" * 64) -> dict[str, object]:
    return {
        "path": str(Path("C:/qualified/ugts-chess-gpu.exe")),
        "sha256": sha256,
        "size_bytes": 123456,
    }


def device_evidence(*, valid: bool = True) -> dict[str, object]:
    payload = {
        "cuda_compiled": True,
        "device_available": valid,
        "device_index": 0,
        "name": "Test CUDA Device",
        "compute_capability": "12.0",
        "total_memory_bytes": 1024,
        "multiprocessors": 1,
        "error": "" if valid else "unavailable",
    }
    stdout = json.dumps(payload, separators=(",", ":"))
    return {
        "valid": valid,
        "validation_failures": [] if valid else ["cuda_device_unavailable"],
        "device_index": 0,
        "payload": payload,
        "parse_error": None,
        "returncode": 0,
        "stdout": stdout,
        "stdout_sha256": hashlib.sha256(stdout.encode("utf-8")).hexdigest(),
        "stderr": "",
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
                **artifact_evidence(len(positions)),
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
                **artifact_evidence(len(positions)),
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
        self.assertEqual(result["schema"], QUALIFICATION_SCHEMA)
        self.assertEqual(result["profile"], QUALIFICATION_PROFILE)
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
                **artifact_evidence(len(positions)),
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
                **artifact_evidence(len(positions), backend_flag=0),
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
            evidence = artifact_evidence(len(positions))
            evidence["input_sha256"] = "not-a-hash"
            evidence["input"]["sha256"] = "not-a-hash"
            evidence["output_sha256"] = None
            evidence["output_semantic_payload_sha256"] = "A" * 64
            evidence["output"]["sha256"] = None
            evidence["output"]["semantic_payload_sha256"] = "A" * 64
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
                **artifact_evidence(len(positions)),
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
            evidence = artifact_evidence(len(positions))
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
                **artifact_evidence(len(positions)),
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

    @patch("ugts_chess.gpu_qualification.run_batch")
    def test_12_runtime_gate_rejects_downgrade_and_forged_batch_flags(self, mocked_run_batch) -> None:
        def fake_run_batch(_executable, positions, work_dir):
            invocation_id = "b" * 32
            invocation_dir = Path(work_dir) / f"run-{invocation_id}"
            invocation_dir.mkdir(parents=True)
            input_path = invocation_dir / "positions.ugcb"
            output_path = invocation_dir / "moves.ugmv"
            input_bytes = encode_position_batch(positions)
            input_path.write_bytes(input_bytes)

            move_lists = [sorted(move.uci() for move in legal_moves(position)) for position in positions]
            counts = [len(moves) for moves in move_lists]
            slots: list[int] = []
            for moves in move_lists:
                slots.extend(encode_move16(move) for move in moves)
                slots.extend([0] * (MAX_MOVES - len(moves)))
            output_bytes = (
                OUTPUT_HEADER.pack(OUTPUT_MAGIC, 1, 2, MAX_MOVES, len(positions), 1)
                + struct.pack(f"<{len(counts)}H", *counts)
                + struct.pack(f"<{len(slots)}H", *slots)
            )
            output_path.write_bytes(output_bytes)
            input_sha256 = hashlib.sha256(input_bytes).hexdigest()
            output_sha256 = hashlib.sha256(output_bytes).hexdigest()
            semantic_sha256 = hashlib.sha256(output_bytes[OUTPUT_HEADER.size :]).hexdigest()
            moves = sum(counts)
            return {
                "invocation_id": invocation_id,
                "invocation_dir": str(invocation_dir),
                "input_sha256": input_sha256,
                "input": {
                    "path": str(input_path),
                    "count": len(positions),
                    "record_size": 64,
                    "sha256": input_sha256,
                },
                "output_sha256": output_sha256,
                "output_semantic_payload_sha256": semantic_sha256,
                "output_backend_flag": 1,
                "output": {
                    "path": str(output_path),
                    "count": len(positions),
                    "backend_flag": 1,
                    "backend": "cuda",
                    "bytes": len(output_bytes),
                    "sha256": output_sha256,
                    "semantic_payload_sha256": semantic_sha256,
                },
                "executable": executable_evidence(),
                "positions": len(positions),
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
        with tempfile.TemporaryDirectory() as temp:
            record = qualify_gpu_move_generator(
                "fake-gpu",
                temp,
                random_positions=0,
                max_plies=1,
                chunk_size=64,
                clock=lambda: next(ticks),
            )

            self.assertTrue(validate_gpu_qualification_record_structure(record))
            self.assertTrue(verify_gpu_qualification_record(record, "fake-gpu", fresh_device_probe=False))

            downgraded = deepcopy(record)
            downgraded["schema"] = "ugts-chess-cuda-movegen-qualification-v1"
            with self.assertRaisesRegex(GPUQualificationRecordError, "unsupported qualification schema"):
                validate_gpu_qualification_record_structure(downgraded)

            forged = deepcopy(record)
            forged["batches"][0]["executable_stdout"] = (
                '{"backend":"cpu","positions":16,"moves":320,'
                '"seconds":0.125,"cuda_fallback_reason":"no CUDA"}'
            )
            with self.assertRaisesRegex(GPUQualificationRecordError, "stdout contradicts backend"):
                validate_gpu_qualification_record_structure(forged)

            forged_device = deepcopy(record)
            forged_device["device_probe"]["payload"]["device_available"] = False
            with self.assertRaisesRegex(GPUQualificationRecordError, "CUDA is unavailable"):
                validate_gpu_qualification_record_structure(forged_device)

            output_path = Path(record["batches"][0]["output"]["path"])
            output_path.write_bytes(output_path.read_bytes() + b"tampered")
            with self.assertRaisesRegex(GPUQualificationRecordError, "retained output hash differs"):
                verify_gpu_qualification_record(record, "fake-gpu", fresh_device_probe=False)

    @patch("ugts_chess.gpu_qualification.run_batch")
    def test_13_v2_json_schema_rejects_downgrade_and_removed_artifact_metadata(self, mocked_run_batch) -> None:
        def fake_run_batch(_executable, positions, _work_dir):
            moves = len(positions) * 3
            return {
                **artifact_evidence(len(positions)),
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
        record = qualify_gpu_move_generator(
            "fake-gpu",
            "work",
            random_positions=0,
            max_plies=1,
            chunk_size=64,
            clock=lambda: next(ticks),
        )
        schema_path = Path(__file__).resolve().parents[1] / "spec" / "ugts_chess_gpu_qualification.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        validator.validate(record)

        downgraded = deepcopy(record)
        downgraded["schema"] = "ugts-chess-cuda-movegen-qualification-v1"
        with self.assertRaises(ValidationError):
            validator.validate(downgraded)

        for removed_field in ("invocation_id", "invocation_dir", "input", "output"):
            with self.subTest(removed_field=removed_field):
                stripped = deepcopy(record)
                del stripped["batches"][0][removed_field]
                with self.assertRaises(ValidationError):
                    validator.validate(stripped)

        forged_passing_flags = deepcopy(record)
        forged_passing_flags["batches"][0]["output_backend_flag"] = 0
        forged_passing_flags["batches"][0]["output"]["backend_flag"] = 0
        forged_passing_flags["batches"][0]["output"]["backend"] = "cpu"
        with self.assertRaises(ValidationError):
            validator.validate(forged_passing_flags)


if __name__ == "__main__":
    unittest.main()
