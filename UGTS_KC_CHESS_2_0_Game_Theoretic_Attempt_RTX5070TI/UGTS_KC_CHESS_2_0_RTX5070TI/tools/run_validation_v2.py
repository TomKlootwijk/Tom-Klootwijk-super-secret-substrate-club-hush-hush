from __future__ import annotations

import compileall
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import jsonschema

from ugts_chess.campaign import campaign_status, verify_campaign
from ugts_chess.game_state import HistoryContext, game_state_sha256
from ugts_chess.gpu_protocol import recommended_rtx5070ti_config, run_batch
from ugts_chess.position import Position
from ugts_chess.proof import verify_mate_certificate
from ugts_chess.rules import perft
from ugts_chess.tablebase import KXKTablebase
from ugts_chess.wdl import verify_wdl_certificate

ROOT = Path(__file__).resolve().parents[1]
VAL = ROOT / "validation"
VAL.mkdir(exist_ok=True)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run(cmd: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None, log: Path | None = None, allow: set[int] = {0}) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        cmd,
        cwd=cwd,
        env={**os.environ, **(env or {})},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if log is not None:
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(completed.stdout, encoding="utf-8")
    if completed.returncode not in allow:
        print(completed.stdout)
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(cmd)}")
    return completed


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    summary: dict[str, object] = {
        "schema": "ugts-kc-chess-validation-2.0",
        "version": "2.0.0",
        "generated": "2026-08-29",
        "root_game_theoretic_value": "unknown",
        "claim_boundary": "This validates the supplied attempt and proof machinery; it does not solve the 32-piece initial position.",
    }

    # Python source and exact test suite.
    compile_ok = compileall.compile_dir(ROOT / "src", quiet=1)
    summary["python_compile"] = {"ok": compile_ok}
    if not compile_ok:
        raise RuntimeError("Python compileall failed")

    host_gpu = ROOT / "cpp" / "build" / "host-release" / "ugts-chess-gpu"
    test_start = time.perf_counter()
    tests = run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        env={"PYTHONPATH": str(ROOT / "src"), "UGTS_GPU_HOST_EXE": str(host_gpu)},
        log=VAL / "test_results_v2.txt",
    )
    test_seconds = time.perf_counter() - test_start
    match = re.search(r"Ran (\d+) tests", tests.stdout)
    test_count = int(match.group(1)) if match else 0
    summary["python_tests"] = {"ok": True, "count": test_count, "seconds": test_seconds}

    # Independent Python perft fixtures (19 exact checks).
    fixtures = [
        ("initial", Position.initial(), {1: 20, 2: 400, 3: 8902, 4: 197281}),
        ("kiwipete", Position.from_fen("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"), {1: 48, 2: 2039, 3: 97862}),
        ("position_3", Position.from_fen("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1"), {1: 14, 2: 191, 3: 2812, 4: 43238}),
        ("position_4", Position.from_fen("r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1"), {1: 6, 2: 264, 3: 9467}),
        ("position_5", Position.from_fen("rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8"), {1: 44, 2: 1486, 3: 62379}),
        ("position_6", Position.from_fen("r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10"), {1: 46, 2: 2079, 3: 89890}),
    ]
    perft_rows: list[dict[str, object]] = []
    for name, position, expected in fixtures:
        for depth, target in expected.items():
            started = time.perf_counter()
            actual = perft(position, depth)
            perft_rows.append({
                "fixture": name,
                "depth": depth,
                "expected": target,
                "actual": actual,
                "match": actual == target,
                "seconds": time.perf_counter() - started,
            })
    write_json(VAL / "perft_results_v2.json", perft_rows)
    if not all(bool(row["match"]) for row in perft_rows):
        raise RuntimeError("perft mismatch")
    summary["python_perft"] = {"ok": True, "checks": len(perft_rows), "largest_nodes": max(int(row["actual"]) for row in perft_rows)}

    # Clean independent C++20 host build and CTest.
    native_build = VAL / "native_build_v2"
    shutil.rmtree(native_build, ignore_errors=True)
    configure = run([
        "cmake", "-S", "cpp", "-B", str(native_build), "-G", "Ninja",
        "-DCMAKE_BUILD_TYPE=Release", "-DUGTS_ENABLE_CUDA=OFF", "-DBUILD_TESTING=ON",
    ], log=VAL / "native_configure_v2.txt")
    build = run(["cmake", "--build", str(native_build), "-j", "2"], log=VAL / "native_build_v2.txt")
    ctest = run(["ctest", "--test-dir", str(native_build), "--output-on-failure"], log=VAL / "native_ctest_v2.txt")
    ctest_match = re.search(r"(\d+)% tests passed, (\d+) tests failed out of (\d+)", ctest.stdout)
    native_test_total = int(ctest_match.group(3)) if ctest_match else 0
    native_test_failed = int(ctest_match.group(2)) if ctest_match else 0
    summary["native_build"] = {
        "ok": True,
        "configure_returncode": configure.returncode,
        "build_returncode": build.returncode,
        "ctest_total": native_test_total,
        "ctest_failed": native_test_failed,
        "cuda_compiled": False,
    }

    native_solver = native_build / "ugts-chess2"
    native_gpu = native_build / "ugts-chess-gpu"
    solver_self = run([str(native_solver), "selftest"], log=VAL / "native_solver_selftest_v2.json")
    gpu_self = run([str(native_gpu), "self-test"], log=VAL / "native_gpu_selftest_v2.json")
    device = run([str(native_gpu), "device-info"], log=VAL / "native_device_info_v2.json", allow={0, 2})
    summary["native_selftests"] = {
        "ok": True,
        "solver": json.loads(solver_self.stdout),
        "packed": json.loads(gpu_self.stdout),
        "device_info_returncode": device.returncode,
        "device_info": json.loads(device.stdout),
    }

    # Packed batch differential against Python exact authority.
    differential_positions = [
        Position.initial(),
        Position.from_fen("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"),
        Position.from_fen("8/8/8/8/8/k7/8/1QK5 w - - 0 1"),
        Position.from_fen("8/8/8/8/8/8/R3k3/K7 w - - 99 1"),
    ]
    differential = run_batch(native_gpu, differential_positions, VAL / "gpu_protocol_v2")
    write_json(VAL / "gpu_protocol_differential_v2.json", differential)
    if differential["mismatches"]:
        raise RuntimeError("packed mover differential mismatch")
    summary["packed_differential"] = {
        "ok": True,
        "positions": differential["positions"],
        "proposed_moves": differential["proposal_move_count"],
        "verified_moves": differential["verified_move_count"],
        "mismatches": 0,
        "backend": "CPU fallback; CUDA device build pending",
    }

    # Schemas and exact certificate verification.
    schema_pairs: list[tuple[Path, Path]] = [
        (ROOT / "spec" / "ugts_kc_chess_project.schema.json", ROOT / "examples" / "project.json"),
        (ROOT / "spec" / "ugts_kc_chess_proof.schema.json", ROOT / "examples" / "mate_in_two_proof.json"),
        (ROOT / "spec" / "ugts_chess_wdl.schema.json", ROOT / "examples" / "campaign" / "bounded_wdl_mate_over_claim.json"),
        (ROOT / "spec" / "ugts_chess_wdl.schema.json", ROOT / "examples" / "campaign" / "bounded_wdl_initial_depth2.json"),
        (ROOT / "spec" / "ugts_chess_rtx5070ti_profile.schema.json", ROOT / "spec" / "rtx5070ti_profile.json"),
        (ROOT / "spec" / "ugts_chess_rtx5070ti_profile.schema.json", ROOT / "examples" / "campaign" / "rtx5070ti_profile.json"),
    ]
    for shard in sorted((ROOT / "examples" / "campaign" / "root_shards").glob("*.json")):
        schema_pairs.append((ROOT / "spec" / "ugts_chess_proof_obligation.schema.json", shard))
    schema_records: list[dict[str, object]] = []
    for schema_path, record_path in schema_pairs:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        instance = json.loads(record_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.validate(instance, schema)
        schema_records.append({"schema": schema_path.name, "record": str(record_path.relative_to(ROOT)), "status": "pass"})
    write_json(VAL / "schema_results_v2.json", schema_records)

    mate_proof = json.loads((ROOT / "examples" / "mate_in_two_proof.json").read_text(encoding="utf-8"))
    mate_verify = verify_mate_certificate(mate_proof)
    wdl_mate = json.loads((ROOT / "examples" / "campaign" / "bounded_wdl_mate_over_claim.json").read_text(encoding="utf-8"))
    wdl_initial = json.loads((ROOT / "examples" / "campaign" / "bounded_wdl_initial_depth2.json").read_text(encoding="utf-8"))
    wdl_mate_verify = verify_wdl_certificate(wdl_mate["certificate_bundle"])
    wdl_initial_verify = verify_wdl_certificate(wdl_initial["certificate_bundle"], allow_unknown_root=True)
    proof_results = {
        "mate_certificate": mate_verify,
        "wdl_mate_over_claim": wdl_mate_verify,
        "wdl_initial_depth2": wdl_initial_verify,
    }
    write_json(VAL / "proof_verification_v2.json", proof_results)
    summary["schemas_and_proofs"] = {
        "ok": True,
        "schema_documents": len(schema_pairs),
        "schema_files": len({path.name for path, _ in schema_pairs}),
        "mate_verified_nodes": mate_verify["verified_nodes"],
        "wdl_mate_value": wdl_mate_verify["root_value"],
        "wdl_initial_depth2_value": wdl_initial_verify["root_value"],
    }

    # Campaign ledger and exact first-move decomposition.
    campaign_db = ROOT / "examples" / "campaign" / "initial.sqlite3"
    campaign_audit = verify_campaign(campaign_db)
    campaign_current = campaign_status(campaign_db)
    workload = json.loads((ROOT / "examples" / "campaign" / "initial_depth4_workloads.json").read_text(encoding="utf-8"))
    if not campaign_audit["valid"] or campaign_audit["job_count"] != 20:
        raise RuntimeError(f"campaign invalid: {campaign_audit['errors']}")
    if workload["root_obligations"] != 20 or workload["total_exact_leaf_paths"] != 197281:
        raise RuntimeError("root workload decomposition mismatch")
    campaign_record = {"audit": campaign_audit, "status": campaign_current, "workload": workload}
    write_json(VAL / "campaign_validation_v2.json", campaign_record)
    summary["campaign"] = {
        "ok": True,
        "root_obligations": 20,
        "root_wdl": campaign_current["root_wdl"],
        "verified_children": campaign_current["verified_children"],
        "event_chain_valid": campaign_audit["valid"],
        "depth4_leaf_paths": workload["total_exact_leaf_paths"],
    }

    # Tablebase transport, counts and exact maxima.
    tablebase_metrics: dict[str, object] = {}
    for piece, name in (("Q", "kqk.tb.gz"), ("R", "krk.tb.gz")):
        path = ROOT / "data" / name
        tb = KXKTablebase.load(path)
        actual = sha256(path)
        if actual != tb.metadata.get("sha256"):
            raise RuntimeError(f"tablebase hash mismatch: {name}")
        tablebase_metrics[piece] = tb.metadata
    write_json(VAL / "tablebase_metrics_v2.json", tablebase_metrics)
    summary["tablebases"] = {
        "ok": True,
        "count": 2,
        "kqk_max_dtm": tablebase_metrics["Q"]["max_dtm_plies"],
        "krk_max_dtm": tablebase_metrics["R"]["max_dtm_plies"],
        "compressed_bytes": tablebase_metrics["Q"]["file_bytes"] + tablebase_metrics["R"]["file_bytes"],
    }

    # Mechanism catalog continuity and parity.
    csv_rows = list(csv.DictReader((ROOT / "spec" / "chess_mechanisms.csv").open(encoding="utf-8", newline="")))
    json_rows = json.loads((ROOT / "spec" / "chess_mechanisms.json").read_text(encoding="utf-8"))
    expected_ids = [f"C{index:03d}" for index in range(1, len(csv_rows) + 1)]
    if [row["id"] for row in csv_rows] != expected_ids or csv_rows != json_rows:
        raise RuntimeError("mechanism catalog continuity/parity failure")
    summary["mechanism_catalog"] = {"ok": True, "entries": len(csv_rows), "range": f"{expected_ids[0]}-{expected_ids[-1]}"}

    # RTX profile sanity.
    profile = recommended_rtx5070ti_config()
    if profile["solver_budget_mib"] + profile["reserved_headroom_mib"] != profile["nominal_vram_mib"]:
        raise RuntimeError("RTX memory budget does not sum to nominal VRAM")
    if sum(profile["allocation_mib"].values()) != profile["solver_budget_mib"]:
        raise RuntimeError("RTX allocation sum mismatch")
    summary["rtx_profile"] = {
        "ok": True,
        "profile_id": profile["profile_id"],
        "nominal_vram_mib": profile["nominal_vram_mib"],
        "solver_budget_mib": profile["solver_budget_mib"],
        "reserved_headroom_mib": profile["reserved_headroom_mib"],
        "compile_architecture": profile["compile_architecture"],
        "physical_device_run": False,
    }

    # Wheel build and truly isolated import/CLI check.
    dist = VAL / "dist_v2"
    shutil.rmtree(dist, ignore_errors=True)
    dist.mkdir(parents=True)
    wheel_build = run(
        [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "--no-build-isolation", "-w", str(dist)],
        log=VAL / "package_build_v2.txt",
    )
    wheels = sorted(dist.glob("*.whl"))
    if len(wheels) != 1:
        raise RuntimeError("expected exactly one wheel")
    clean = VAL / "clean_install_v2"
    shutil.rmtree(clean, ignore_errors=True)
    run([sys.executable, "-m", "venv", str(clean)], log=VAL / "clean_install_venv_v2.txt")
    python_exe = clean / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    cli_exe = clean / ("Scripts/ugts-chess.exe" if os.name == "nt" else "bin/ugts-chess")
    install = run([str(python_exe), "-m", "pip", "install", "--force-reinstall", "--ignore-installed", "--no-deps", str(wheels[0])], log=VAL / "clean_install_v2.txt")
    clean_info = run([str(cli_exe), "info"], cwd=Path("/tmp"), log=VAL / "clean_install_info_v2.json")
    clean_record = json.loads(clean_info.stdout)
    if clean_record["version"] != "2.0.0":
        raise RuntimeError("clean-installed CLI version mismatch")
    summary["wheel"] = {"ok": True, "file": wheels[0].name, "bytes": wheels[0].stat().st_size, "clean_install": True}

    # CUDA status is deliberately evidence-gated in this environment.
    nvcc = shutil.which("nvcc")
    summary["cuda_device_validation"] = {
        "status": "deferred_no_nvcc" if nvcc is None else "toolkit_present_not_device_tested",
        "nvcc": nvcc,
        "physical_rtx5070ti_run": False,
        "claim": "No CUDA throughput, VRAM, thermal, power or laptop speed result is claimed by this host validation.",
    }

    write_json(VAL / "summary_v2.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
