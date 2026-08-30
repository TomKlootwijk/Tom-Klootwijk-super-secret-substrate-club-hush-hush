"""Build and measure the packed-polar render matrix on an attached POCO.

The harness is intentionally evidence-first.  A case is only valid when the
native ``UGTS-KC392`` log proves that the requested polar and Bayer paths were
actually selected.  Build products and every device attempt are append-only so
an interrupted USB connection can be resumed without deleting prior evidence.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import importlib.util
import inspect
import json
import math
from numbers import Real
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
AUTHORED_LAB_GENERATOR = (
    ROOT / "examples" / "packed_polar_gpu_lab_3d" / "generate_variants.py"
)
RECIPE_LAB_GENERATOR = (
    ROOT / "examples" / "packed_polar_gpu_lab_3d" / "generate_recipe_variants.py"
)
LAB_GENERATOR = AUTHORED_LAB_GENERATOR
WORKLOAD_KINDS = ("authored", "recipe", "burst", "glow", "grow")
DEFAULT_OUTPUT_ROOT = ROOT / "build" / "poco-polar-render-benchmarks"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ugts_kc3.androidbuild import (  # noqa: E402
    AndroidDevice,
    AndroidToolchain,
    build_apk,
    install_apk,
    launch_android_app,
    list_android_devices,
    profile_android_app,
    select_android_device,
)
from ugts_kc3.androidexport import build_android_project  # noqa: E402


WORKLOAD_COUNTS = (64, 256, 1024)
GLOW_WORKLOAD_COUNTS = WORKLOAD_COUNTS
GROW_WORKLOAD_COUNTS = WORKLOAD_COUNTS
BURST_WORKLOAD_COUNTS = (32, 128, 384)
ALL_WORKLOAD_COUNTS = tuple(sorted({*WORKLOAD_COUNTS, *BURST_WORKLOAD_COUNTS}))
DEFAULT_WARMUP_SECONDS = 5.0
DEFAULT_PROFILE_SECONDS = 30.0
DEFAULT_SEED = 0x5EED3920C0DEC0DE
MODE_MATRIX = (
    ("direct", "off"),
    ("lut", "off"),
    ("direct", "subtle"),
    ("lut", "subtle"),
)
CPU_CASE = ("cpu", "off")
CPU_BAYER_CASES = (("cpu", "off"), ("cpu", "subtle"))
SCHEMA = "ugts-kc-poco-polar-render-benchmark-1"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_CASE_NAME = re.compile(
    r"^polar-(0032|0064|0128|0256|0384|1024)-"
    r"(direct|lut|cpu)-(off|subtle)$"
)
_RUNTIME_LINE = re.compile(
    r"render substrate\s+"
    r"polar_requested=(?P<requested>[a-z]+)\s+"
    r"polar_effective=(?P<effective>[a-z]+)\s+"
    r"gpu_instances=(?P<instances>\d+)\s+"
    r"gpu_profiles=(?P<profiles>\d+)\s+"
    r"gpu_batches=(?P<batches>\d+)\s+"
    r"cpu_fallbacks=(?P<fallbacks>\d+)\s+"
    r"animation_fallbacks=(?P<animation_fallbacks>\d+)\s+"
    r"polar_recipes=(?P<polar_recipes>\d+)\s+"
    r"generated=(?P<generated>\d+)\s+"
    r"generated_gpu=(?P<generated_gpu>\d+)\s+"
    r"generated_cpu=(?P<generated_cpu>\d+)\s+"
    r"reason=(?P<reason>\S+)\s+"
    r"(?:polar_material=(?P<polar_material>off|bands)\s+"
    r"material_bands=(?P<material_bands>\d+)\s+"
    r"material_strength=(?P<material_strength>[0-9]+(?:\.[0-9]+)?)\s+)?"
    r"bayer=(?P<bayer>[a-z]+)\s+"
    r"levels=(?P<levels>\d+)\s+"
    r"strength=(?P<strength>[0-9]+(?:\.[0-9]+)?)"
)
_POPULATION_RUNTIME_LINE = re.compile(
    r"polar population\s+"
    r"generated_total=(?P<generated_total>\d+)\s+"
    r"generated_visible=(?P<generated_visible>\d+)\s+"
    r"visible_gpu=(?P<visible_gpu>\d+)\s+"
    r"visible_cpu=(?P<visible_cpu>\d+)\s+"
    r"materialized=(?P<materialized>\d+)\s+"
    r"cartesian_composed=(?P<cartesian_composed>\d+)"
)
_POPULATION_FORMAT_RUNTIME_LINE = re.compile(
    r"polar population\s+"
    r"format_version=(?P<format_version>\d+)\s+"
    r"recipes=(?P<recipes>\d+)\s+"
    r"generated=(?P<generated>\d+)\s+"
    r"glow_recipes=(?P<glow_recipes>\d+)\s+"
    r"glow_instances=(?P<glow_instances>\d+)\s+"
    r"(?:grow_recipes=(?P<grow_recipes>\d+)\s+"
    r"grow_instances=(?P<grow_instances>\d+)\s+)?"
    r"gpu_instance_stride_bytes=(?P<gpu_instance_stride_bytes>\d+)\s+"
    r"ecs_generated=(?P<ecs_generated>true|false)(?=\r?$)",
    flags=re.MULTILINE,
)
_GLOW_OPERATOR_BUILD_PROOF = {
    0x0050: (9, 3, "log_radius_pulse", "564ed3e6ad87ef6a"),
    0x0051: (10, 2, "seeded_material_phase", "1d7fceba2fb0deb3"),
    0x0052: (11, 3, "polar_material_glow", "f3fde5381d6703a6"),
}
_GROW_OPERATOR_BUILD_PROOF = {
    0x0053: (
        12,
        2,
        "polar_display_scale_from_glow",
        "1d558c07b7a6796b",
    ),
}
_RUNTIME_FALLBACK_LINE = re.compile(
    r"render substrate polar runtime fallback", flags=re.IGNORECASE
)
_ADB_LOSS = re.compile(
    r"(?:device\s+(?:offline|not found)|no devices?|disconnected|transport error|"
    r"closed|cannot connect|connection reset|more than one device)",
    flags=re.IGNORECASE,
)


class DeviceUnavailableError(RuntimeError):
    """The selected ADB transport disappeared during a resumable run."""


@dataclass(frozen=True)
class BenchmarkCase:
    count: int
    polar_mode: str
    bayer_mode: str

    @property
    def name(self) -> str:
        return case_name(self.count, self.polar_mode, self.bayer_mode)

    @property
    def expected_levels(self) -> int:
        return 2 if self.bayer_mode == "off" else 64

    @property
    def expected_strength(self) -> float:
        return 0.0 if self.bayer_mode == "off" else 0.30

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "count": self.count,
            "polar_mode": self.polar_mode,
            "bayer_mode": self.bayer_mode,
            "levels": self.expected_levels,
            "strength": self.expected_strength,
        }


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def case_name(count: int, polar_mode: str, bayer_mode: str) -> str:
    """Return a stable, path-safe case name or reject an unsupported case."""

    if isinstance(count, bool) or int(count) not in ALL_WORKLOAD_COUNTS:
        raise ValueError(f"count must be one of {ALL_WORKLOAD_COUNTS}")
    if polar_mode not in {"direct", "lut", "cpu"}:
        raise ValueError("polar mode must be direct, lut, or cpu")
    if bayer_mode not in {"off", "subtle"}:
        raise ValueError("benchmark Bayer mode must be off or subtle")
    result = f"polar-{int(count):04d}-{polar_mode}-{bayer_mode}"
    if _CASE_NAME.fullmatch(result) is None:  # pragma: no cover - invariant
        raise ValueError(f"unsafe benchmark case name: {result}")
    return result


def benchmark_cases(
    counts: Iterable[int],
    *,
    include_cpu: bool = False,
    workload: str = "authored",
) -> tuple[BenchmarkCase, ...]:
    """Expand counts into the fixed deterministic A/B order."""

    if workload not in WORKLOAD_KINDS:
        raise ValueError(f"workload must be one of {', '.join(WORKLOAD_KINDS)}")
    allowed_counts = BURST_WORKLOAD_COUNTS if workload == "burst" else WORKLOAD_COUNTS
    raw_counts = tuple(counts)
    if not raw_counts or any(isinstance(value, bool) for value in raw_counts):
        raise ValueError(f"counts must be selected from {allowed_counts}")
    try:
        requested = {int(value) for value in raw_counts}
    except (TypeError, ValueError) as exc:
        raise ValueError(f"counts must be selected from {allowed_counts}") from exc
    if any(value not in allowed_counts for value in requested):
        raise ValueError(f"counts must be selected from {allowed_counts}")
    ordered_counts = tuple(value for value in allowed_counts if value in requested)
    result = [
        BenchmarkCase(count, polar_mode, bayer_mode)
        for count in ordered_counts
        for polar_mode, bayer_mode in MODE_MATRIX
    ]
    if include_cpu:
        cpu_cases = CPU_BAYER_CASES if workload == "burst" else (CPU_CASE,)
        result.extend(
            BenchmarkCase(count, *mode)
            for count in ordered_counts
            for mode in cpu_cases
        )
    return tuple(result)


def validate_timings(
    warmup_seconds: float, profile_seconds: float
) -> tuple[float, float]:
    """Validate timings against this harness and ``profile_android_app`` bounds."""

    warmup = float(warmup_seconds)
    profile = float(profile_seconds)
    if not 0.0 <= warmup <= 60.0:
        raise ValueError("warmup duration must be between 0 and 60 seconds")
    if not 5.0 <= profile <= 900.0:
        raise ValueError("profile duration must be between 5 and 900 seconds")
    return warmup, profile


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_record(path: str | Path, *, relative_to: str | Path) -> dict[str, object]:
    """Describe exact on-disk evidence without loading large APKs into JSON."""

    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    root = Path(relative_to).resolve()
    try:
        relative = resolved.relative_to(root).as_posix()
    except ValueError:
        relative = None
    return {
        "path": str(resolved),
        "relative_path": relative,
        "bytes": resolved.stat().st_size,
        "sha256": sha256_file(resolved),
    }


def _json_text(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def write_json(path: str | Path, value: Any) -> Path:
    """Atomically update a small state/evidence JSON file."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(_json_text(value), encoding="utf-8")
    temporary.replace(destination)
    return destination


def read_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _copy_exact(source: str | Path, destination: str | Path) -> Path:
    """Copy once; never overwrite different evidence from an earlier run."""

    source_path = Path(source).resolve()
    destination_path = Path(destination)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if destination_path.exists():
        if not destination_path.is_file() or sha256_file(
            destination_path
        ) != sha256_file(source_path):
            raise FileExistsError(
                f"refusing to overwrite different evidence: {destination_path}"
            )
        return destination_path.resolve()
    shutil.copy2(source_path, destination_path)
    return destination_path.resolve()


def load_lab_builder(
    generator_path: str | Path = LAB_GENERATOR,
) -> Callable[..., Any]:
    """Load the example generator by path and validate its public contract."""

    path = Path(generator_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"packed-polar lab generator is missing: {path}")
    module_name = "_ugts_packed_polar_gpu_lab_generator"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load packed-polar lab generator: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    builder = getattr(module, "build_project", None)
    if not callable(builder):
        raise AttributeError(f"{path} has no callable build_project")
    parameters = inspect.signature(builder).parameters
    required = {"count", "polar_mode", "bayer_mode", "seed"}
    missing = sorted(required.difference(parameters))
    if missing:
        raise TypeError(
            "packed-polar build_project is missing parameter(s): " + ", ".join(missing)
        )
    return builder


def build_project_for_case(
    builder: Callable[..., Any],
    case: BenchmarkCase,
    *,
    seed: int,
    workload: str = "authored",
) -> Any:
    """Call the inspected lab builder without assuming optional tuning arguments."""

    if workload not in WORKLOAD_KINDS:
        raise ValueError(f"workload must be one of {', '.join(WORKLOAD_KINDS)}")
    signature = inspect.signature(builder)
    keywords: dict[str, object] = {
        "polar_mode": case.polar_mode,
        "bayer_mode": case.bayer_mode,
        "seed": seed,
    }
    if "levels" in signature.parameters:
        keywords["levels"] = case.expected_levels
    if "strength" in signature.parameters:
        keywords["strength"] = case.expected_strength
    if workload == "burst":
        if "preset" not in signature.parameters:
            raise TypeError("Burst lab builder has no preset parameter")
        keywords["preset"] = "burst"
    elif workload in {"glow", "grow"}:
        required_glow_parameters = {
            "preset",
            "glow_by_distance",
            "glow_start_distance",
            "glow_end_distance",
            "glow_strength",
        }
        missing = sorted(required_glow_parameters.difference(signature.parameters))
        if missing:
            raise TypeError(
                f"{workload.title()} lab builder is missing parameter(s): "
                + ", ".join(missing)
            )
        keywords.update(
            {
                "preset": "ring",
                "glow_by_distance": True,
                "glow_start_distance": 0.0,
                "glow_end_distance": 4.0,
                "glow_strength": 1.25,
            }
        )
        if workload == "grow":
            if "grow_glowing_copies" not in signature.parameters:
                raise TypeError(
                    "Grow lab builder is missing parameter: grow_glowing_copies"
                )
            keywords["grow_glowing_copies"] = True
    return builder(case.count, **keywords)


def parse_runtime_proof(log_text: str) -> dict[str, object] | None:
    """Return the last complete native render-substrate proof line."""

    matches = tuple(_RUNTIME_LINE.finditer(str(log_text)))
    if not matches:
        return None
    values = matches[-1].groupdict()
    return {
        "requested": values["requested"],
        "effective": values["effective"],
        "gpu_instances": int(values["instances"]),
        "gpu_profiles": int(values["profiles"]),
        "gpu_batches": int(values["batches"]),
        "cpu_fallbacks": int(values["fallbacks"]),
        "animation_fallbacks": int(values["animation_fallbacks"]),
        "polar_recipes": int(values["polar_recipes"]),
        "generated": int(values["generated"]),
        "generated_gpu": int(values["generated_gpu"]),
        "generated_cpu": int(values["generated_cpu"]),
        "reason": values["reason"],
        "polar_material": values["polar_material"],
        "material_bands": (
            int(values["material_bands"])
            if values["material_bands"] is not None
            else None
        ),
        "material_strength": (
            float(values["material_strength"])
            if values["material_strength"] is not None
            else None
        ),
        "bayer": values["bayer"],
        "levels": int(values["levels"]),
        "strength": float(values["strength"]),
        "line": matches[-1].group(0),
    }


def parse_population_runtime_proof(log_text: str) -> dict[str, int] | None:
    """Return the last visible-only polar-population proof line."""

    matches = tuple(_POPULATION_RUNTIME_LINE.finditer(str(log_text)))
    if not matches:
        return None
    values = matches[-1].groupdict()
    return {key: int(value) for key, value in values.items()}


def parse_population_format_runtime_proof(
    log_text: str,
) -> dict[str, object] | None:
    """Return the last exact KCPR representation/Glow proof line."""

    matches = tuple(_POPULATION_FORMAT_RUNTIME_LINE.finditer(str(log_text)))
    if not matches:
        return None
    values = matches[-1].groupdict()
    result: dict[str, object] = {
        "format_version": int(values["format_version"]),
        "recipes": int(values["recipes"]),
        "generated": int(values["generated"]),
        "glow_recipes": int(values["glow_recipes"]),
        "glow_instances": int(values["glow_instances"]),
        "gpu_instance_stride_bytes": int(values["gpu_instance_stride_bytes"]),
        "ecs_generated": values["ecs_generated"] == "true",
        "line": matches[-1].group(0),
    }
    if values["grow_recipes"] is not None and values["grow_instances"] is not None:
        result["grow_recipes"] = int(values["grow_recipes"])
        result["grow_instances"] = int(values["grow_instances"])
    return result


def validate_runtime_proof(
    case: BenchmarkCase, log_text: str, *, workload: str = "authored"
) -> dict[str, object]:
    """Fail closed when runtime logs do not prove the exact requested path."""

    if workload not in WORKLOAD_KINDS:
        raise ValueError(f"workload must be one of {', '.join(WORKLOAD_KINDS)}")

    observed = parse_runtime_proof(log_text)
    population_observed = parse_population_runtime_proof(log_text)
    population_format_observed = parse_population_format_runtime_proof(log_text)
    errors: list[str] = []
    if observed is None:
        errors.append("missing UGTS-KC392 render-substrate proof line")
        return {"valid": False, "errors": errors, "observed": None}

    expected_gpu = case.count if case.polar_mode != "cpu" else 0
    expected_profiles = 1 if case.polar_mode != "cpu" else 0
    expected_batches = (
        2
        if workload == "burst" and case.polar_mode != "cpu"
        else 1
        if case.polar_mode != "cpu"
        else 0
    )
    expected_fallbacks = 0 if case.polar_mode != "cpu" else case.count
    recipe_workload = workload in {"recipe", "burst", "glow", "grow"}
    expected_recipes = 1 if recipe_workload else 0
    expected_generated = case.count - 1 if recipe_workload else 0
    expected_generated_gpu = expected_generated if case.polar_mode != "cpu" else 0
    expected_generated_cpu = expected_generated if case.polar_mode == "cpu" else 0
    expected = {
        "requested": case.polar_mode,
        "effective": case.polar_mode,
        "gpu_instances": expected_gpu,
        "gpu_profiles": expected_profiles,
        "gpu_batches": expected_batches,
        "cpu_fallbacks": expected_fallbacks,
        "animation_fallbacks": 0,
        "polar_recipes": expected_recipes,
        "generated": expected_generated,
        "generated_gpu": expected_generated_gpu,
        "generated_cpu": expected_generated_cpu,
        "reason": "requested_cpu" if case.polar_mode == "cpu" else "none",
        "bayer": case.bayer_mode,
        "levels": case.expected_levels,
        "strength": case.expected_strength,
    }
    for key, value in expected.items():
        actual = observed[key]
        if key == "strength":
            matches = abs(float(actual) - float(value)) <= 0.001
        else:
            matches = actual == value
        if not matches:
            errors.append(f"{key}: requested {value!r}, runtime reported {actual!r}")
    if observed["polar_material"] is not None:
        expected_material = {
            "polar_material": "off",
            "material_bands": 1,
            "material_strength": 0.0,
        }
        for key, value in expected_material.items():
            actual = observed[key]
            if key == "material_strength":
                matches = abs(float(actual) - float(value)) <= 0.001
            else:
                matches = actual == value
            if not matches:
                errors.append(
                    f"{key}: requested {value!r}, runtime reported {actual!r}"
                )
    population_expected = None
    if recipe_workload:
        population_expected = {
            "generated_total": expected_generated,
            "generated_visible": expected_generated,
            "visible_gpu": expected_generated_gpu,
            "visible_cpu": expected_generated_cpu,
            "materialized": expected_generated,
            "cartesian_composed": expected_generated_cpu,
        }
        if population_observed is None:
            errors.append("missing visible-only polar-population proof line")
        else:
            for key, value in population_expected.items():
                actual = population_observed[key]
                if actual != value:
                    errors.append(
                        f"population {key}: requested {value!r}, "
                        f"runtime reported {actual!r}"
                    )
    population_format_expected = None
    if workload in {"glow", "grow"}:
        population_format_expected = {
            "format_version": 4 if workload == "grow" else 3,
            "recipes": 1,
            "generated": expected_generated,
            "glow_recipes": 1,
            "glow_instances": case.count,
            "gpu_instance_stride_bytes": 36,
            "ecs_generated": False,
        }
        if workload == "grow":
            population_format_expected["grow_recipes"] = 1
            population_format_expected["grow_instances"] = expected_generated
        if population_format_observed is None:
            errors.append(
                f"missing KCPR v{population_format_expected['format_version']} "
                f"{workload.title()} representation proof line"
            )
        else:
            for key, value in population_format_expected.items():
                actual = population_format_observed.get(key)
                if actual != value:
                    errors.append(
                        f"population format {key}: requested {value!r}, "
                        f"runtime reported {actual!r}"
                    )
    if case.polar_mode != "cpu" and _RUNTIME_FALLBACK_LINE.search(str(log_text)):
        errors.append("native renderer reported a post-startup polar runtime fallback")
    return {
        "valid": not errors,
        "errors": errors,
        "expected": expected,
        "observed": observed,
        "population_expected": population_expected,
        "population_observed": population_observed,
        "population_format_expected": population_format_expected,
        "population_format_observed": population_format_observed,
    }


def _metric_delta(
    baseline: Mapping[str, object], candidate: Mapping[str, object], key: str
) -> float | int | None:
    left = baseline.get(key)
    right = candidate.get(key)
    if (
        isinstance(left, bool)
        or isinstance(right, bool)
        or not isinstance(left, Real)
        or not isinstance(right, Real)
    ):
        return None
    difference = float(right) - float(left)
    if isinstance(left, int) and isinstance(right, int):
        return int(difference)
    return round(difference, 6)


_COMPARISON_METRICS = (
    "effective_fps",
    "frame_ms_p50",
    "frame_ms_p95",
    "frame_ms_p99",
    "intervals_over_1_5_vsync",
    "pss_kib_max",
    "rss_kib_max",
    "cpu_total_capacity_pct_mean",
    "cpu_total_capacity_pct_max",
    "cpu_one_core_pct_mean",
    "cpu_one_core_pct_max",
    "gpu_render_ms_mean_since_renderer_start",
    "gpu_render_ms_max_since_renderer_start",
    "gpu_c_max",
    "battery_c_max",
    "thermal_status_max",
)


def _comparison(
    kind: str,
    baseline: Mapping[str, Any] | None,
    candidate: Mapping[str, Any] | None,
) -> dict[str, object]:
    baseline_valid = bool(baseline and baseline.get("valid"))
    candidate_valid = bool(candidate and candidate.get("valid"))
    left_profile = baseline.get("profile") if baseline else None
    right_profile = candidate.get("profile") if candidate else None
    available = (
        baseline_valid
        and candidate_valid
        and isinstance(left_profile, Mapping)
        and isinstance(right_profile, Mapping)
    )
    deltas = (
        {
            key: _metric_delta(left_profile, right_profile, key)
            for key in _COMPARISON_METRICS
        }
        if available
        else {}
    )
    return {
        "kind": kind,
        "available": available,
        "baseline": baseline.get("case") if baseline else None,
        "candidate": candidate.get("case") if candidate else None,
        "delta_candidate_minus_baseline": deltas,
    }


def comparison_summary(
    results: Sequence[Mapping[str, Any]],
    *,
    generated_at: str | None = None,
) -> dict[str, object]:
    """Build an honest partial-or-complete comparison from recorded results."""

    indexed: dict[tuple[int, str, str], Mapping[str, Any]] = {}
    rows: list[dict[str, object]] = []
    for result in results:
        spec = result.get("case")
        if not isinstance(spec, Mapping):
            continue
        try:
            key = (
                int(spec["count"]),
                str(spec["polar_mode"]),
                str(spec["bayer_mode"]),
            )
        except (KeyError, TypeError, ValueError):
            continue
        indexed[key] = result
        profile = result.get("profile")
        rows.append(
            {
                "name": spec.get("name"),
                "count": key[0],
                "polar_mode": key[1],
                "bayer_mode": key[2],
                "status": result.get("status"),
                "valid": result.get("valid"),
                "effective_fps": (
                    profile.get("effective_fps")
                    if isinstance(profile, Mapping)
                    else None
                ),
                "frame_ms_p95": (
                    profile.get("frame_ms_p95")
                    if isinstance(profile, Mapping)
                    else None
                ),
            }
        )

    comparisons: list[dict[str, object]] = []
    counts = tuple(sorted({int(row["count"]) for row in rows}))
    for count in counts:
        for bayer in ("off", "subtle"):
            comparison = _comparison(
                "lut_minus_direct",
                indexed.get((count, "direct", bayer)),
                indexed.get((count, "lut", bayer)),
            )
            comparison.update({"count": count, "bayer_mode": bayer})
            comparisons.append(comparison)
        for polar in ("direct", "lut"):
            comparison = _comparison(
                "subtle_minus_off",
                indexed.get((count, polar, "off")),
                indexed.get((count, polar, "subtle")),
            )
            comparison.update({"count": count, "polar_mode": polar})
            comparisons.append(comparison)

    status_counts: dict[str, int] = {}
    for row in rows:
        status = str(row["status"] or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "schema": SCHEMA,
        "kind": "comparison-summary",
        "generated_at": generated_at or utc_now(),
        "status_counts": status_counts,
        "cases": rows,
        "comparisons": comparisons,
        "interpretation": (
            "Deltas are candidate minus baseline and exist only when both cases "
            "have a profile and passed native runtime-path proof."
        ),
    }


def _adb_run(
    adb: Path,
    serial: str,
    arguments: Sequence[str],
    *,
    timeout: float = 30.0,
    binary: bool = False,
) -> str | bytes:
    completed = subprocess.run(
        [str(adb), "-s", serial, *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        message = (
            (completed.stderr + b"\n" + completed.stdout)
            .decode("utf-8", errors="replace")
            .strip()
        )
        raise RuntimeError(message or "ADB command failed")
    if binary:
        return completed.stdout
    return completed.stdout.decode("utf-8", errors="replace")


def _runtime_logcat_arguments(pid: int) -> tuple[str, ...]:
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise ValueError("profile PID must be a positive integer")
    return (
        "logcat",
        f"--pid={pid}",
        "-d",
        "-v",
        "threadtime",
        "-s",
        "UGTS-KC392:I",
        "*:S",
    )


def _device_check(toolchain: AndroidToolchain, serial: str) -> AndroidDevice:
    try:
        devices = list_android_devices(toolchain)
        return select_android_device(devices, serial=serial)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        raise DeviceUnavailableError(
            f"ADB device {serial} is unavailable: {exc}"
        ) from exc


def _device_action(
    label: str,
    toolchain: AndroidToolchain,
    serial: str,
    action: Callable[[], Any],
) -> Any:
    _device_check(toolchain, serial)
    try:
        value = action()
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        if _ADB_LOSS.search(str(exc)):
            raise DeviceUnavailableError(
                f"ADB disappeared while {label} on {serial}: {exc}"
            ) from exc
        try:
            _device_check(toolchain, serial)
        except DeviceUnavailableError as missing:
            raise DeviceUnavailableError(
                f"ADB disappeared while {label} on {serial}: {missing}"
            ) from exc
        raise
    _device_check(toolchain, serial)
    return value


def _next_attempt_dir(case_dir: Path) -> Path:
    numbers = [
        int(match.group(1))
        for path in case_dir.glob("attempt-*")
        if path.is_dir() and (match := re.fullmatch(r"attempt-(\d{3})", path.name))
    ]
    result = case_dir / f"attempt-{max(numbers, default=0) + 1:03d}"
    result.mkdir(parents=False, exist_ok=False)
    return result


def _next_build_attempt_dir(case_dir: Path) -> Path:
    numbers = [
        int(match.group(1))
        for path in case_dir.glob("build-attempt-*")
        if path.is_dir()
        and (match := re.fullmatch(r"build-attempt-(\d{3})", path.name))
    ]
    result = case_dir / f"build-attempt-{max(numbers, default=0) + 1:03d}"
    result.mkdir(parents=False, exist_ok=False)
    return result


def _validate_glow_project_proof(
    project: Any,
    case: BenchmarkCase,
    *,
    grow_copies: bool = False,
) -> None:
    """Reject a builder that did not author the frozen one-prototype workload."""

    metadata = getattr(project, "metadata", None)
    lab = metadata.get("polar_recipe_lab") if isinstance(metadata, Mapping) else None
    expected_glow = {
        "start_distance": 0.0,
        "end_distance": 4.0,
        "strength": 1.25,
    } | ({"grow_copies": True} if grow_copies else {})
    workload_label = "Grow" if grow_copies else "Glow"
    if not isinstance(lab, Mapping) or (
        lab.get("ecs_prototype_count") != 1
        or lab.get("display_instance_count") != case.count
        or lab.get("generated_copy_count") != case.count - 1
        or lab.get("preset") != "ring"
        or lab.get("generated_members_are_ecs_entities") is not False
        or lab.get("glow_by_distance") != expected_glow
    ):
        raise RuntimeError(
            f"{workload_label} lab metadata does not prove one ECS prototype and "
            "the exact 0..4 / 1.25 modifier"
        )
    recipe_mappings = []
    for node in tuple(getattr(project, "nodes", ())):
        node_metadata = getattr(node, "metadata", None)
        if isinstance(node_metadata, Mapping) and "polar_population" in node_metadata:
            recipe_mappings.append(node_metadata["polar_population"])
    if len(recipe_mappings) != 1 or not isinstance(recipe_mappings[0], Mapping):
        raise RuntimeError(
            f"{workload_label} workload must contain exactly one KCPR prototype"
        )
    authored_recipe = recipe_mappings[0]
    if (
        authored_recipe.get("preset") != "ring"
        or authored_recipe.get("instance_count") != case.count
        or authored_recipe.get("glow_by_distance") != expected_glow
    ):
        raise RuntimeError(
            f"{workload_label} prototype does not contain the exact Ring modifier "
            "metadata"
        )


def _validate_grow_project_proof(project: Any, case: BenchmarkCase) -> None:
    """Require the v4 flag in both lab and authoritative recipe metadata."""

    _validate_glow_project_proof(project, case, grow_copies=True)


def _validate_recipe_build_report(
    recipe_report: object,
    case: BenchmarkCase,
    workload: str,
) -> None:
    """Require canonical KCPR inspection evidence for one recipe workload."""

    if not isinstance(recipe_report, Mapping):
        raise RuntimeError("recipe build report has no KCPR inspection")
    if (
        recipe_report.get("recipe_count") != 1
        or recipe_report.get("total_instances") != case.count
        or recipe_report.get("generated_copy_count") != case.count - 1
        or recipe_report.get("ecs_prototype_count") != 1
        or recipe_report.get("generated_members_are_ecs_entities") is not False
        or recipe_report.get("native_consumer_wired") is not True
    ):
        raise RuntimeError(
            "build report does not prove the requested native recipe workload"
        )
    recipes = recipe_report.get("recipes")
    if not isinstance(recipes, list) or len(recipes) != 1:
        raise RuntimeError("build report does not contain exactly one KCPR recipe")
    recipe = recipes[0]
    if not isinstance(recipe, Mapping):
        raise RuntimeError("build report contains an invalid KCPR recipe inspection")
    if workload == "burst":
        if recipe_report.get("format_version") != 2 or recipe.get("preset") != "burst":
            raise RuntimeError(
                "build report does not prove a KCPR v2 Radial Burst workload"
            )
        return
    if workload not in {"glow", "grow"}:
        return

    is_grow = workload == "grow"
    glow = recipe.get("glow_by_distance")
    expected_glow_fields = {
        "center_rho",
        "inv_half_width",
        "strength",
    } | ({"grow_copies"} if is_grow else set())
    if not isinstance(glow, Mapping) or set(glow) != expected_glow_fields:
        raise RuntimeError(
            f"KCPR v{4 if is_grow else 3} recipe has no canonical "
            f"{workload.title()} parameter metadata"
        )
    try:
        center_rho = float(glow["center_rho"])
        inv_half_width = float(glow["inv_half_width"])
        glow_strength = float(glow["strength"])
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"KCPR v{4 if is_grow else 3} Glow parameters are not numeric"
        ) from exc
    if (
        not math.isfinite(center_rho)
        or not math.isfinite(inv_half_width)
        or inv_half_width <= 0.0
        or abs(glow_strength - 1.25) > 1.0e-6
    ):
        raise RuntimeError(
            f"KCPR v{4 if is_grow else 3} Glow parameters do not match the workload"
        )
    if is_grow and glow.get("grow_copies") is not True:
        raise RuntimeError("KCPR v4 recipe does not enable Grow glowing copies")
    expected_version = 4 if is_grow else 3
    expected_mask = 0x1E3B if is_grow else 0x0E3B
    expected_operator_count = 9 if is_grow else 8
    if (
        recipe_report.get("format_version") != expected_version
        or recipe_report.get("native_consumer")
        != f"android-kcpr392-v{expected_version}"
        or recipe_report.get("operator_count") != expected_operator_count
        or not isinstance(recipe_report.get("glow_math_schedule"), str)
        or (
            is_grow
            and not isinstance(recipe_report.get("grow_copies_math_schedule"), str)
        )
        or recipe.get("preset") != "ring"
        or recipe.get("operator_mask") != expected_mask
        or recipe.get("instance_count") != case.count
        or recipe.get("generated_copy_count") != case.count - 1
    ):
        raise RuntimeError(
            f"build report does not prove the exact KCPR v{expected_version} "
            f"Ring {workload.title()} workload"
        )
    operators = recipe_report.get("operators")
    if not isinstance(operators, list):
        raise RuntimeError(
            f"KCPR v{expected_version} build report has no operator inspection"
        )
    observed_glow_operators: dict[int, tuple[object, ...]] = {}
    for operator in operators:
        if not isinstance(operator, Mapping):
            raise RuntimeError(
                f"KCPR v{expected_version} build report contains an invalid operator"
            )
        code = operator.get("code")
        if code in _GLOW_OPERATOR_BUILD_PROOF:
            observed_glow_operators[int(code)] = (
                operator.get("slot"),
                operator.get("arity"),
                operator.get("name"),
                operator.get("meaning_hash"),
            )
    if observed_glow_operators != _GLOW_OPERATOR_BUILD_PROOF:
        raise RuntimeError(
            f"KCPR v{expected_version} Glow operator meanings do not match the "
            "benchmark"
        )
    if is_grow:
        observed_grow_operators: dict[int, tuple[object, ...]] = {}
        for operator in operators:
            if not isinstance(operator, Mapping):
                continue
            code = operator.get("code")
            if code in _GROW_OPERATOR_BUILD_PROOF:
                observed_grow_operators[int(code)] = (
                    operator.get("slot"),
                    operator.get("arity"),
                    operator.get("name"),
                    operator.get("meaning_hash"),
                )
        if observed_grow_operators != _GROW_OPERATOR_BUILD_PROOF:
            raise RuntimeError(
                "KCPR v4 Grow operator meaning does not match the benchmark"
            )


def _build_case(
    run_dir: Path,
    case: BenchmarkCase,
    builder: Callable[..., Any],
    *,
    seed: int,
    workload: str = "authored",
) -> dict[str, Any]:
    case_dir = run_dir / "cases" / case.name
    stage_path = case_dir / "build-stage.json"
    if stage_path.is_file():
        stage = read_json(stage_path)
        required_artifacts = [
            "apk",
            "kcpk",
            "kcrp",
            "build_report",
            "gradle_output",
            "project",
        ]
        if workload in {"recipe", "burst", "glow", "grow"}:
            required_artifacts.append("kcpr")
        for label in required_artifacts:
            record = stage.get("artifacts", {}).get(label)
            if not isinstance(record, Mapping):
                raise RuntimeError(f"resume evidence is missing {label}: {stage_path}")
            relative = record.get("relative_path")
            if not isinstance(relative, str):
                raise RuntimeError(f"resume evidence has no relative path: {label}")
            artifact = run_dir / Path(relative)
            if (
                not artifact.is_file()
                or artifact.stat().st_size != record.get("bytes")
                or sha256_file(artifact) != record.get("sha256")
            ):
                raise RuntimeError(
                    f"resume evidence changed or disappeared: {artifact}"
                )
        return stage

    case_dir.mkdir(parents=True, exist_ok=True)
    attempt_dir = _next_build_attempt_dir(case_dir)
    attempt_path = attempt_dir / "build-attempt.json"
    attempt: dict[str, Any] = {
        "schema": SCHEMA,
        "kind": "build-attempt",
        "number": int(attempt_dir.name.rsplit("-", 1)[1]),
        "case": case.to_dict(),
        "workload": workload,
        "started_at": utc_now(),
        "status": "building",
        "workspace_strategy": "short-system-temporary-directory",
    }
    write_json(attempt_path, attempt)

    source_build = None
    apk_build = None
    partial_artifacts: dict[str, dict[str, object]] = {}
    try:
        project = build_project_for_case(builder, case, seed=seed, workload=workload)
        if workload == "glow":
            _validate_glow_project_proof(project, case)
        elif workload == "grow":
            _validate_grow_project_proof(project, case)
        attempt_project = attempt_dir / "project.json"
        project.write(attempt_project)
        partial_artifacts["project"] = artifact_record(
            attempt_project, relative_to=run_dir
        )

        # CMake/NDK object paths expand far beyond the authored output path on
        # Windows. Build under the system temp root with a one-character Android
        # project directory, then retain only durable evidence below run_dir.
        with tempfile.TemporaryDirectory(
            prefix="kc392-", ignore_cleanup_errors=True
        ) as temporary:
            workspace = Path(temporary).resolve()
            android_dir = workspace / "a"
            attempt["temporary_workspace"] = {
                "path": str(workspace),
                "android_project_name": android_dir.name,
                "path_characters": len(str(android_dir)),
                "retained": False,
            }
            write_json(attempt_path, attempt)
            try:
                source_build = build_android_project(
                    project,
                    android_dir,
                    profile_hint="auto",
                    clean=False,
                    include_authoring_assets=False,
                )
                if (
                    source_build.polar_pack is None
                    or source_build.render_substrate_pack is None
                ):
                    raise RuntimeError(
                        "lab export did not produce both KCPK and KCRP assets"
                    )
                apk_build = build_apk(android_dir, variant="poco-debug", clean=False)
                if not apk_build.application_id:
                    raise RuntimeError(
                        "poco-debug build did not report an Android application id"
                    )

                report_data = read_json(source_build.build_report)
                polar_report = report_data.get("packed_kinematic_runtime")
                render_report = report_data.get("render_substrate_runtime")
                if not isinstance(polar_report, Mapping):
                    raise RuntimeError(
                        "build report has no packed-kinematic runtime inspection"
                    )
                expected_components = case.count if workload == "authored" else 1
                if (
                    polar_report.get("profile_count") != 1
                    or polar_report.get("component_count") != expected_components
                ):
                    raise RuntimeError(
                        "build report does not contain the requested packed workload"
                    )
                recipe_report = report_data.get("polar_population_recipe_asset")
                if workload in {"recipe", "burst", "glow", "grow"}:
                    _validate_recipe_build_report(recipe_report, case, workload)
                elif recipe_report is not None:
                    raise RuntimeError(
                        "authored-ECS benchmark unexpectedly contains a KCPR recipe"
                    )
                if not isinstance(render_report, Mapping):
                    raise RuntimeError(
                        "build report has no render-substrate runtime inspection"
                    )
                if (
                    render_report.get("polar_mode") != case.polar_mode
                    or render_report.get("bayer_mode") != case.bayer_mode
                    or render_report.get("levels") != case.expected_levels
                    or abs(
                        float(render_report.get("strength", -1.0))
                        - case.expected_strength
                    )
                    > 1.0e-6
                ):
                    raise RuntimeError(
                        "build report render settings do not match the benchmark case"
                    )
                base_application_id = report_data.get("application_id")
                if (
                    not isinstance(base_application_id, str)
                    or apk_build.application_id != f"{base_application_id}.pocox7pro"
                ):
                    raise RuntimeError(
                        "build report base application id and Poco APK metadata differ"
                    )

                evidence = case_dir / "evidence"
                project_path = _copy_exact(attempt_project, case_dir / "project.json")
                apk = _copy_exact(
                    apk_build.apk, evidence / f"{case.name}-poco-debug.apk"
                )
                kcpk = _copy_exact(
                    source_build.polar_pack,
                    evidence / "packed_kinematics.kcpk",
                )
                kcrp = _copy_exact(
                    source_build.render_substrate_pack,
                    evidence / "render_substrate.kcrp",
                )
                kcpr = None
                if workload in {"recipe", "burst", "glow", "grow"}:
                    if source_build.polar_population_pack is None:
                        raise RuntimeError(
                            "recipe lab export did not produce a KCPR asset"
                        )
                    kcpr = _copy_exact(
                        source_build.polar_population_pack,
                        evidence / "polar_populations.kcpr",
                    )
                build_report = _copy_exact(
                    source_build.build_report, evidence / "build-report.json"
                )
                attempt_gradle_output = attempt_dir / "gradle-output.txt"
                attempt_gradle_output.write_text(apk_build.output, encoding="utf-8")
                gradle_output = _copy_exact(
                    attempt_gradle_output, evidence / "gradle-output.txt"
                )
            except Exception:
                diagnostic_sources = {
                    "source_project": (
                        source_build.project_file if source_build is not None else None
                    ),
                    "build_report": (
                        source_build.build_report if source_build is not None else None
                    ),
                    "kcpk": (
                        source_build.polar_pack if source_build is not None else None
                    ),
                    "kcrp": (
                        source_build.render_substrate_pack
                        if source_build is not None
                        else None
                    ),
                    "kcpr": (
                        source_build.polar_population_pack
                        if source_build is not None
                        else None
                    ),
                    "apk": apk_build.apk if apk_build is not None else None,
                }
                diagnostic_dir = attempt_dir / "partial-evidence"
                for label, source in diagnostic_sources.items():
                    if source is None or not Path(source).is_file():
                        continue
                    copied = _copy_exact(source, diagnostic_dir / Path(source).name)
                    partial_artifacts[label] = artifact_record(
                        copied, relative_to=run_dir
                    )
                if apk_build is not None:
                    diagnostic_output = diagnostic_dir / "gradle-output.txt"
                    diagnostic_output.write_text(apk_build.output, encoding="utf-8")
                    partial_artifacts["gradle_output"] = artifact_record(
                        diagnostic_output, relative_to=run_dir
                    )
                raise
    except Exception as exc:
        error_path = attempt_dir / "error.txt"
        error_path.write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
        partial_artifacts["error"] = artifact_record(error_path, relative_to=run_dir)
        attempt.update(
            {
                "updated_at": utc_now(),
                "status": "failed",
                "error": str(exc),
                "artifacts": partial_artifacts,
            }
        )
        write_json(attempt_path, attempt)
        raise

    stage = {
        "schema": SCHEMA,
        "kind": "build-stage",
        "created_at": utc_now(),
        "case": case.to_dict(),
        "workload": workload,
        "application_id": apk_build.application_id,
        "source_project_hash": source_build.project_hash,
        "android_source": {
            "file_count": source_build.file_count,
            "total_bytes": source_build.total_bytes,
            "profile_hint": source_build.profile_hint,
            "retained": False,
            "workspace_strategy": "short-system-temporary-directory",
        },
        "build_report_data": report_data,
        "artifacts": {
            "project": artifact_record(project_path, relative_to=run_dir),
            "apk": artifact_record(apk, relative_to=run_dir),
            "kcpk": artifact_record(kcpk, relative_to=run_dir),
            "kcrp": artifact_record(kcrp, relative_to=run_dir),
            "build_report": artifact_record(build_report, relative_to=run_dir),
            "gradle_output": artifact_record(gradle_output, relative_to=run_dir),
        },
    }
    if kcpr is not None:
        stage["artifacts"]["kcpr"] = artifact_record(kcpr, relative_to=run_dir)
    write_json(stage_path, stage)
    attempt.update(
        {
            "updated_at": utc_now(),
            "status": "complete",
            "build_stage": stage_path.relative_to(run_dir).as_posix(),
        }
    )
    write_json(attempt_path, attempt)
    return stage


def _artifact_from_stage(run_dir: Path, stage: Mapping[str, Any], label: str) -> Path:
    record = stage["artifacts"][label]
    return run_dir / Path(record["relative_path"])


def _case_result_path(run_dir: Path, case: BenchmarkCase) -> Path:
    return run_dir / "cases" / case.name / "case-result.json"


def _built_only_result(case: BenchmarkCase, stage: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "kind": "case-result",
        "updated_at": utc_now(),
        "case": case.to_dict(),
        "status": "built_only",
        "valid": None,
        "build": stage,
        "runtime_proof": None,
        "profile": None,
        "device_attempt": None,
    }


def _run_device_case(
    run_dir: Path,
    case: BenchmarkCase,
    stage: Mapping[str, Any],
    toolchain: AndroidToolchain,
    serial: str,
    *,
    warmup_seconds: float,
    profile_seconds: float,
) -> dict[str, Any]:
    case_dir = run_dir / "cases" / case.name
    attempt_dir = _next_attempt_dir(case_dir)
    application_id = str(stage["application_id"])
    apk = _artifact_from_stage(run_dir, stage, "apk")
    attempt = {
        "number": int(attempt_dir.name.rsplit("-", 1)[1]),
        "path": attempt_dir.relative_to(run_dir).as_posix(),
        "started_at": utc_now(),
        "serial": serial,
        "warmup_seconds": warmup_seconds,
        "profile_seconds": profile_seconds,
    }

    try:
        _device_action(
            "clearing UGTS-KC392 logcat",
            toolchain,
            serial,
            lambda: _adb_run(toolchain.adb, serial, ("logcat", "-c")),
        )
        installed = _device_action(
            "installing the benchmark APK",
            toolchain,
            serial,
            lambda: install_apk(apk, serial=serial),
        )
        (attempt_dir / "install.txt").write_text(installed.output, encoding="utf-8")
        launched = _device_action(
            "launching the benchmark APK",
            toolchain,
            serial,
            lambda: launch_android_app(application_id, serial=serial),
        )
        (attempt_dir / "launch.txt").write_text(launched.output, encoding="utf-8")

        if warmup_seconds:
            time.sleep(warmup_seconds)
        _device_check(toolchain, serial)
        screenshot = _device_action(
            "capturing the benchmark screenshot",
            toolchain,
            serial,
            lambda: _adb_run(
                toolchain.adb,
                serial,
                ("exec-out", "screencap", "-p"),
                timeout=60.0,
                binary=True,
            ),
        )
        if not isinstance(screenshot, bytes) or not screenshot.startswith(
            PNG_SIGNATURE
        ):
            raise RuntimeError("ADB screencap did not return a PNG")
        screenshot_path = attempt_dir / "screenshot.png"
        screenshot_path.write_bytes(screenshot)

        profile = _device_action(
            "profiling the benchmark",
            toolchain,
            serial,
            lambda: profile_android_app(
                application_id,
                serial=serial,
                seconds=profile_seconds,
                sample_seconds=min(5.0, profile_seconds),
            ),
        )
        profile_data = profile.to_dict()
        profile_path = write_json(attempt_dir / "profile.json", profile_data)
        profile_pid = profile.pid
        logcat_arguments = _runtime_logcat_arguments(profile_pid)
        log_text = _device_action(
            "capturing UGTS-KC392 logcat",
            toolchain,
            serial,
            lambda: _adb_run(
                toolchain.adb,
                serial,
                logcat_arguments,
                timeout=60.0,
            ),
        )
        if not isinstance(log_text, str):  # pragma: no cover - typing invariant
            raise TypeError("text logcat command returned bytes")
        log_path = attempt_dir / "UGTS-KC392.logcat.txt"
        log_path.write_text(log_text, encoding="utf-8")
        proof = validate_runtime_proof(
            case, log_text, workload=str(stage.get("workload", "authored"))
        )
        attempt.update(
            {
                "completed_at": utc_now(),
                "artifacts": {
                    "screenshot": artifact_record(screenshot_path, relative_to=run_dir),
                    "profile": artifact_record(profile_path, relative_to=run_dir),
                    "logcat": artifact_record(log_path, relative_to=run_dir),
                    "install_output": artifact_record(
                        attempt_dir / "install.txt", relative_to=run_dir
                    ),
                    "launch_output": artifact_record(
                        attempt_dir / "launch.txt", relative_to=run_dir
                    ),
                },
            }
        )
        result = {
            "schema": SCHEMA,
            "kind": "case-result",
            "updated_at": utc_now(),
            "case": case.to_dict(),
            "status": "profiled" if proof["valid"] else "invalid_runtime_proof",
            "valid": bool(proof["valid"]),
            "build": stage,
            "runtime_proof": proof,
            "profile": profile_data,
            "device_attempt": attempt,
        }
        write_json(attempt_dir / "attempt-result.json", result)
        write_json(_case_result_path(run_dir, case), result)
        return result
    except DeviceUnavailableError as exc:
        interrupted = {
            "schema": SCHEMA,
            "kind": "case-result",
            "updated_at": utc_now(),
            "case": case.to_dict(),
            "status": "interrupted_adb",
            "valid": None,
            "build": stage,
            "runtime_proof": None,
            "profile": None,
            "device_attempt": {
                **attempt,
                "interrupted_at": utc_now(),
                "error": str(exc),
            },
        }
        write_json(attempt_dir / "attempt-result.json", interrupted)
        write_json(_case_result_path(run_dir, case), interrupted)
        raise
    except Exception as exc:
        failed = {
            "schema": SCHEMA,
            "kind": "case-result",
            "updated_at": utc_now(),
            "case": case.to_dict(),
            "status": "failed_device_stage",
            "valid": None,
            "build": stage,
            "runtime_proof": None,
            "profile": None,
            "device_attempt": {**attempt, "failed_at": utc_now(), "error": str(exc)},
        }
        write_json(attempt_dir / "attempt-result.json", failed)
        write_json(_case_result_path(run_dir, case), failed)
        raise


def _load_results(
    run_dir: Path, cases: Sequence[BenchmarkCase]
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for case in cases:
        path = _case_result_path(run_dir, case)
        if path.is_file():
            results.append(read_json(path))
    return results


def _write_summary(run_dir: Path, cases: Sequence[BenchmarkCase]) -> dict[str, object]:
    summary = comparison_summary(_load_results(run_dir, cases))
    write_json(run_dir / "comparison-summary.json", summary)
    return summary


def _new_run_dir(output_root: Path, seed: int) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = output_root / f"{timestamp}-seed-{seed:016x}"
    candidate = base
    suffix = 1
    while candidate.exists():
        candidate = output_root / f"{base.name}-{suffix:02d}"
        suffix += 1
    candidate.mkdir(parents=True, exist_ok=False)
    return candidate.resolve()


def _resume_command(run_dir: Path, serial: str | None) -> str:
    command = f'{sys.executable} "{Path(__file__).resolve()}" --resume "{run_dir}"'
    return command if not serial else command + f' --serial "{serial}"'


def _discover_device_toolchain() -> AndroidToolchain:
    """Find ADB without requiring any retained generated Android project."""

    roots: list[Path] = []
    for name in ("ANDROID_SDK_ROOT", "ANDROID_HOME"):
        if value := os.environ.get(name):
            roots.append(Path(value))
    if local_app_data := os.environ.get("LOCALAPPDATA"):
        roots.append(Path(local_app_data) / "Android" / "Sdk")
    try:
        home = Path.home()
    except RuntimeError:
        home = None
    if home is not None:
        roots.extend(
            (
                home / "AppData" / "Local" / "Android" / "Sdk",
                home / "Android" / "Sdk",
            )
        )
    roots.append(Path("/opt/android-sdk"))

    adb_candidates: list[tuple[Path, Path]] = []
    if located := shutil.which("adb"):
        adb = Path(located).resolve()
        sdk_root = (
            adb.parent.parent if adb.parent.name == "platform-tools" else adb.parent
        )
        adb_candidates.append((sdk_root, adb))
    for root in roots:
        expanded = root.expanduser()
        adb_candidates.extend(
            (expanded, expanded / "platform-tools" / name)
            for name in ("adb.exe", "adb")
        )

    seen: set[Path] = set()
    for sdk_root, adb in adb_candidates:
        resolved_adb = adb.resolve()
        if resolved_adb in seen:
            continue
        seen.add(resolved_adb)
        if not resolved_adb.is_file():
            continue
        java_path = shutil.which("java")
        return AndroidToolchain(
            sdk_root.expanduser().resolve(),
            resolved_adb,
            (),
            Path(java_path).resolve() if java_path else None,
        )
    raise FileNotFoundError(
        "ADB was not found; set ANDROID_SDK_ROOT/ANDROID_HOME or add adb to PATH"
    )


def _manifest_cases(manifest: Mapping[str, Any]) -> tuple[BenchmarkCase, ...]:
    result = []
    raw_cases = manifest.get("cases")
    if not isinstance(raw_cases, list):
        raise ValueError("run manifest has no cases list")
    for raw in raw_cases:
        if not isinstance(raw, Mapping):
            raise ValueError("run manifest contains an invalid case")
        case = BenchmarkCase(
            int(raw["count"]), str(raw["polar_mode"]), str(raw["bayer_mode"])
        )
        if raw.get("name") != case.name:
            raise ValueError("run manifest case name does not match its settings")
        result.append(case)
    return tuple(result)


def run_benchmark(
    *,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    counts: Sequence[int] | None = None,
    serial: str | None = None,
    warmup_seconds: float = DEFAULT_WARMUP_SECONDS,
    profile_seconds: float = DEFAULT_PROFILE_SECONDS,
    seed: int = DEFAULT_SEED,
    include_cpu: bool = False,
    workload: str = "authored",
    build_only: bool = False,
    resume: str | Path | None = None,
) -> tuple[Path, dict[str, object]]:
    """Execute or resume the matrix and return its directory and latest summary."""

    warmup_seconds, profile_seconds = validate_timings(warmup_seconds, profile_seconds)
    if isinstance(seed, bool) or not 0 <= int(seed) <= 0xFFFFFFFFFFFFFFFF:
        raise ValueError("seed must be an unsigned 64-bit integer")
    seed = int(seed)
    if workload not in WORKLOAD_KINDS:
        raise ValueError(f"workload must be one of {', '.join(WORKLOAD_KINDS)}")

    if resume is None:
        selected_counts = (
            BURST_WORKLOAD_COUNTS
            if counts is None and workload == "burst"
            else WORKLOAD_COUNTS
            if counts is None
            else counts
        )
        cases = benchmark_cases(
            selected_counts, include_cpu=include_cpu, workload=workload
        )
        run_dir = _new_run_dir(Path(output_root).resolve(), seed)
        manifest = {
            "schema": SCHEMA,
            "kind": "run-manifest",
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "status": "building",
            "run_dir": str(run_dir),
            "seed": seed,
            "workload": workload,
            "counts": [
                case.count
                for case in cases
                if case.polar_mode == "direct" and case.bayer_mode == "off"
            ],
            "include_cpu": include_cpu,
            "warmup_seconds": warmup_seconds,
            "profile_seconds": profile_seconds,
            "cases": [case.to_dict() for case in cases],
            "requested_serial": serial,
            "build_only": build_only,
        }
        write_json(run_dir / "run-manifest.json", manifest)
    else:
        run_dir = Path(resume).resolve()
        manifest_path = run_dir / "run-manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(f"resume manifest is missing: {manifest_path}")
        manifest = read_json(manifest_path)
        if manifest.get("schema") != SCHEMA or manifest.get("kind") != "run-manifest":
            raise ValueError(f"not a polar-render benchmark run: {manifest_path}")
        cases = _manifest_cases(manifest)
        seed = int(manifest["seed"])
        workload = str(manifest.get("workload", "authored"))
        if workload not in WORKLOAD_KINDS:
            raise ValueError("run manifest has an unsupported workload")
        warmup_seconds = float(manifest["warmup_seconds"])
        profile_seconds = float(manifest["profile_seconds"])
        validate_timings(warmup_seconds, profile_seconds)
        if serial is None:
            requested = manifest.get("requested_serial")
            serial = str(requested) if requested else None
        manifest["build_only"] = build_only
        manifest["updated_at"] = utc_now()
        manifest["status"] = "resumed"
        write_json(manifest_path, manifest)

    generator = (
        AUTHORED_LAB_GENERATOR if workload == "authored" else RECIPE_LAB_GENERATOR
    )
    builder = load_lab_builder(generator)
    stages: dict[str, dict[str, Any]] = {}
    try:
        for case in cases:
            stages[case.name] = _build_case(
                run_dir, case, builder, seed=seed, workload=workload
            )
            result_path = _case_result_path(run_dir, case)
            if not result_path.is_file():
                write_json(result_path, _built_only_result(case, stages[case.name]))
            _write_summary(run_dir, cases)
    except Exception as exc:
        manifest.update(
            {
                "updated_at": utc_now(),
                "status": "build_failed",
                "interruption": str(exc),
                "resume_command": _resume_command(run_dir, serial),
            }
        )
        write_json(run_dir / "run-manifest.json", manifest)
        _write_summary(run_dir, cases)
        raise

    if build_only:
        manifest.update({"updated_at": utc_now(), "status": "built_only"})
        write_json(run_dir / "run-manifest.json", manifest)
        return run_dir, _write_summary(run_dir, cases)

    toolchain = _discover_device_toolchain()
    try:
        selected = select_android_device(list_android_devices(toolchain), serial=serial)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        resume_command = _resume_command(run_dir, serial)
        manifest.update(
            {
                "updated_at": utc_now(),
                "status": "interrupted_adb",
                "interruption": str(exc),
                "resume_command": resume_command,
            }
        )
        write_json(run_dir / "run-manifest.json", manifest)
        _write_summary(run_dir, cases)
        raise DeviceUnavailableError(
            f"No selected ADB device is ready: {exc}\n"
            "All build evidence was preserved. Reconnect the phone and resume with:\n"
            f"{resume_command}"
        ) from exc
    serial = selected.serial
    manifest.update(
        {
            "updated_at": utc_now(),
            "status": "profiling",
            "selected_device": {
                "serial": selected.serial,
                "model": selected.model,
                "product": selected.product,
                "transport_id": selected.transport_id,
            },
        }
    )
    write_json(run_dir / "run-manifest.json", manifest)

    try:
        for case in cases:
            result_path = _case_result_path(run_dir, case)
            existing = read_json(result_path) if result_path.is_file() else {}
            if existing.get("status") in {"profiled", "invalid_runtime_proof"}:
                continue
            _run_device_case(
                run_dir,
                case,
                stages[case.name],
                toolchain,
                serial,
                warmup_seconds=warmup_seconds,
                profile_seconds=profile_seconds,
            )
            _write_summary(run_dir, cases)
    except DeviceUnavailableError as exc:
        manifest.update(
            {
                "updated_at": utc_now(),
                "status": "interrupted_adb",
                "interruption": str(exc),
                "resume_command": _resume_command(run_dir, serial),
            }
        )
        write_json(run_dir / "run-manifest.json", manifest)
        _write_summary(run_dir, cases)
        raise DeviceUnavailableError(
            f"{exc}\nAll evidence was preserved. Reconnect the phone and resume with:\n"
            f"{manifest['resume_command']}"
        ) from exc

    summary = _write_summary(run_dir, cases)
    invalid = sum(
        result.get("valid") is False for result in _load_results(run_dir, cases)
    )
    manifest.update(
        {
            "updated_at": utc_now(),
            "status": "complete" if invalid == 0 else "complete_with_invalid_cases",
            "invalid_cases": invalid,
        }
    )
    write_json(run_dir / "run-manifest.json", manifest)
    return run_dir, summary


def _uint64(text: str) -> int:
    value = int(text, 0)
    if not 0 <= value <= 0xFFFFFFFFFFFFFFFF:
        raise argparse.ArgumentTypeError("seed must fit unsigned 64-bit")
    return value


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build and profile deterministic direct/LUT and Bayer off/subtle "
            "packed-polar cases on an attached POCO."
        )
    )
    parser.add_argument(
        "--count",
        dest="counts",
        type=int,
        choices=ALL_WORKLOAD_COUNTS,
        nargs="+",
        default=None,
        help=(
            "one or more display workload counts (defaults: 64/256/1024 for "
            "authored/recipe/glow/grow; 32/128/384 for burst)"
        ),
    )
    parser.add_argument(
        "--workload",
        choices=WORKLOAD_KINDS,
        default="authored",
        help=(
            "authored stores one KCPK component per mover; recipe keeps one ECS "
            "prototype and derives orbit copies from KCPR; burst compounds a "
            "looping local log-encoded polar LUT displacement around one prototype; "
            "glow uses a KCPR v3 Ring field at distances 0..4 with strength 1.25; "
            "grow uses KCPR v4 to reuse that field for bounded 1x..5x generated "
            "display scale without growing the ECS prototype"
        ),
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--serial", help="optional exact ADB serial")
    parser.add_argument("--warmup-seconds", type=float, default=DEFAULT_WARMUP_SECONDS)
    parser.add_argument(
        "--profile-seconds", type=float, default=DEFAULT_PROFILE_SECONDS
    )
    parser.add_argument("--seed", type=_uint64, default=DEFAULT_SEED)
    parser.add_argument(
        "--include-cpu",
        action="store_true",
        help=(
            "also include CPU; Burst covers both Bayer off/subtle for the full "
            "18-case matrix, while Glow and Grow add CPU/Bayer Off only"
        ),
    )
    parser.add_argument(
        "--build-only",
        action="store_true",
        help="generate source and poco-debug APK evidence without touching ADB",
    )
    parser.add_argument(
        "--resume",
        type=Path,
        help="resume a preserved run directory (matrix/timings/seed come from its manifest)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = argument_parser().parse_args(argv)
    try:
        run_dir, summary = run_benchmark(
            output_root=args.output_root,
            counts=args.counts,
            serial=args.serial,
            warmup_seconds=args.warmup_seconds,
            profile_seconds=args.profile_seconds,
            seed=args.seed,
            include_cpu=args.include_cpu,
            workload=args.workload,
            build_only=args.build_only,
            resume=args.resume,
        )
    except DeviceUnavailableError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(
        _json_text(
            {
                "run_dir": str(run_dir),
                "summary": str(run_dir / "comparison-summary.json"),
                "status_counts": summary["status_counts"],
            }
        ),
        end="",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
