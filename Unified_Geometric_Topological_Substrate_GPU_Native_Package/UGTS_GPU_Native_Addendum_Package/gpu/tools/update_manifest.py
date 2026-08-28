#!/usr/bin/env python3
"""Regenerate the package SHA-256 manifest, excluding transient build caches."""
from __future__ import annotations

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "MANIFEST.sha256"
INVENTORY = ROOT / "PACKAGE_INVENTORY.csv"
EXCLUDED_DIRECTORIES = {
    "build",
    "build-windows",
    "__pycache__",
    "compact_smoke",
    "compact_collision_check",
    "subgroup_smoke",
    "semantic_hash_verification",
    "l2_latency_smoke",
    "l2_latency_smoke_exact",
    "cuda_l2_clock_smoke",
    "cuda_l2_mlp_smoke",
    "cuda_l2_mlp_smoke_memcheck",
    "cuda_texture_lut_smoke",
    "cuda_texture_lut_smoke_memcheck",
    "cuda_packed_log_lut_smoke",
    "cuda_packed_log_lut_smoke_memcheck",
    "cuda_l2_stride_smoke",
    "cuda_l2_stride_smoke_memcheck",
    "cuda_l2_stride_smoke_final",
    "cuda_lut_line_occupancy_smoke",
    "cuda_lut_line_occupancy_smoke_memcheck",
    "cuda_lut_sparse_address_smoke",
    "cuda_lut_sparse_address_smoke_memcheck",
    "cuda_vmm_alias_smoke",
    "cuda_vmm_compression_lut_smoke",
    "cuda_vmm_compression_constant_control_smoke",
    "cuda_vmm_compression_texture_nonzero_alignment_smoke",
}
EXCLUDED_RELATIVE_PATHS = {
    Path("benchmarks/cuda_vmm_compression_ones_global_isolated/artifacts/ugts_cuda_vmm_compression_lut_bench.exe"),
    Path("benchmarks/cuda_vmm_compression_ones_global_isolated/artifacts/ugts_cuda_vmm_compression_lut_bench.exp"),
    Path("benchmarks/cuda_vmm_compression_ones_global_isolated/artifacts/ugts_cuda_vmm_compression_lut_bench.lib"),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def included(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    return (
        path != MANIFEST
        and relative not in EXCLUDED_RELATIVE_PATHS
        and not any(part in EXCLUDED_DIRECTORIES for part in relative.parts)
        and not any(part.startswith("smoke") for part in relative.parts)
    )


def main() -> None:
    inventory_files = sorted(
        (
            path
            for path in ROOT.rglob("*")
            if path.is_file()
            and path not in {MANIFEST, INVENTORY}
            and included(path)
        ),
        key=lambda path: path.relative_to(ROOT).as_posix(),
    )
    inventory_lines = ["path,bytes,sha256"] + [
        f"{path.relative_to(ROOT).as_posix()},{path.stat().st_size},{sha256(path)}"
        for path in inventory_files
    ]
    INVENTORY.write_text("\n".join(inventory_lines) + "\n", encoding="utf-8", newline="\n")

    files = sorted(
        (path for path in ROOT.rglob("*") if path.is_file() and included(path)),
        key=lambda path: path.relative_to(ROOT).as_posix(),
    )
    lines = [f"{sha256(path)}  {path.relative_to(ROOT).as_posix()}" for path in files]
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"{INVENTORY}: {len(inventory_files)} files")
    print(f"{MANIFEST}: {len(files)} files")


if __name__ == "__main__":
    main()
