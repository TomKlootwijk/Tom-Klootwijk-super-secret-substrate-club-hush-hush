from __future__ import annotations

import compileall
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from importlib import resources
from pathlib import Path

import jsonschema

from ugts_chess.position import Position
from ugts_chess.proof import verify_mate_certificate
from ugts_chess.rules import perft
from ugts_chess.search import Searcher
from ugts_chess.tablebase import KXKTablebase

ROOT = Path(__file__).resolve().parents[1]
VAL = ROOT / "validation"
VAL.mkdir(exist_ok=True)

summary: dict[str, object] = {"schema": "ugts-kc-chess-validation-1.0", "version": "1.0.0", "generated": "2026-08-29"}

# Compile
compile_ok = compileall.compile_dir(ROOT / "src", quiet=1)
summary["python_compile"] = {"ok": compile_ok}
if not compile_ok:
    raise SystemExit("compileall failed")

# Tests
start = time.perf_counter()
proc = subprocess.run(
    [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
    cwd=ROOT,
    env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
)
elapsed = time.perf_counter() - start
(VAL / "test_results.txt").write_text(proc.stdout, encoding="utf-8")
match = re.search(r"Ran (\d+) tests", proc.stdout)
test_count = int(match.group(1)) if match else 0
summary["tests"] = {"ok": proc.returncode == 0, "count": test_count, "seconds": elapsed}
if proc.returncode:
    print(proc.stdout)
    raise SystemExit("tests failed")

# Perft fixtures
fixtures = [
    ("initial", Position.initial(), {1: 20, 2: 400, 3: 8902, 4: 197281}),
    ("kiwipete", Position.from_fen("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"), {1: 48, 2: 2039, 3: 97862}),
    ("position_3", Position.from_fen("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1"), {1: 14, 2: 191, 3: 2812}),
    ("position_4", Position.from_fen("r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1"), {1: 6, 2: 264, 3: 9467}),
    ("position_5", Position.from_fen("rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8"), {1: 44, 2: 1486, 3: 62379}),
    ("position_6", Position.from_fen("r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10"), {1: 46, 2: 2079, 3: 89890}),
]
perft_rows = []
for name, pos, expected in fixtures:
    for depth, target in expected.items():
        t0 = time.perf_counter()
        actual = perft(pos, depth)
        seconds = time.perf_counter() - t0
        perft_rows.append({"fixture": name, "depth": depth, "expected": target, "actual": actual, "match": actual == target, "seconds": seconds})
(VAL / "perft_results.json").write_text(json.dumps(perft_rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")
summary["perft"] = {"ok": all(row["match"] for row in perft_rows), "checks": len(perft_rows), "largest_nodes": max(row["actual"] for row in perft_rows)}

# Proof and schemas
proof = json.loads((ROOT / "examples" / "mate_in_two_proof.json").read_text(encoding="utf-8"))
proof_check = verify_mate_certificate(proof)
proof_schema = json.loads((ROOT / "spec" / "ugts_kc_chess_proof.schema.json").read_text(encoding="utf-8"))
project_schema = json.loads((ROOT / "spec" / "ugts_kc_chess_project.schema.json").read_text(encoding="utf-8"))
project = json.loads((ROOT / "examples" / "project.json").read_text(encoding="utf-8"))
jsonschema.validate(proof, proof_schema)
jsonschema.validate(project, project_schema)
schema_result = {"proof_schema": "pass", "project_schema": "pass", "proof_verifier": proof_check}
(VAL / "schema_results.json").write_text(json.dumps(schema_result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
summary["proof"] = {"ok": True, "verified_nodes": proof_check["verified_nodes"], "explored_nodes": proof["explored_nodes"]}
summary["schemas"] = {"ok": True, "count": 2}

# Tablebase integrity and metrics
meta = {}
for piece, name in (("Q", "kqk.tb.gz"), ("R", "krk.tb.gz")):
    path = ROOT / "data" / name
    tb = KXKTablebase.load(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != tb.metadata.get("sha256"):
        raise SystemExit(f"tablebase hash mismatch: {name}")
    meta[piece] = tb.metadata
(VAL / "tablebase_metrics.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
summary["tablebases"] = {
    "ok": True,
    "count": 2,
    "kqk_max_dtm": meta["Q"]["max_dtm_plies"],
    "krk_max_dtm": meta["R"]["max_dtm_plies"],
    "compressed_bytes": meta["Q"]["file_bytes"] + meta["R"]["file_bytes"],
}

# Deterministic benchmark snapshot
mate = Position.from_fen("8/8/8/8/8/k7/8/1QK5 w - - 0 1")
t0 = time.perf_counter()
search = Searcher().search(mate, max_depth=4)
search_seconds = time.perf_counter() - t0
benchmark = {
    "environment": {"python": sys.version.split()[0], "platform": sys.platform},
    "mate_search": search.to_dict(mate),
    "wall_seconds": search_seconds,
    "interpretation": "Reference-environment timing only; not a cross-device performance claim."
}
(VAL / "benchmark.json").write_text(json.dumps(benchmark, indent=2, sort_keys=True) + "\n", encoding="utf-8")
summary["benchmark"] = {"mate_score": search.score_text(), "nodes": search.nodes + search.qnodes, "seconds": search_seconds}

# Package build
build_dir = VAL / "dist"
build_dir.mkdir(exist_ok=True)
build_proc = subprocess.run(
    [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "--no-build-isolation", "-w", str(build_dir)],
    cwd=ROOT,
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
)
(VAL / "package_build.txt").write_text(build_proc.stdout, encoding="utf-8")
summary["wheel_build"] = {"ok": build_proc.returncode == 0, "files": [p.name for p in build_dir.glob("*.whl")]}
if build_proc.returncode:
    print(build_proc.stdout)
    raise SystemExit("wheel build failed")

(VAL / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(summary, indent=2, sort_keys=True))
