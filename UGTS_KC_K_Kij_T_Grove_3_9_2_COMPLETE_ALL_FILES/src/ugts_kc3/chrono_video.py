"""Deterministic chrono-spatial observation compiler for ordinary video.

The compiler does not infer hidden geometry.  It binds exact source bytes and
presentation timestamps, builds a separately versioned log-polar sampling LUT,
and emits proposal-only motion diagnostics.  The current UGLUT2 kinematics
format is deliberately not reused or changed.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
import math
import platform
from pathlib import Path
import shutil
import struct
import subprocess
import time
from typing import Any, Iterator, Mapping, Sequence

from .version import __version__


CHRONO_PROFILE = "UGTOMS-CSO-CHRONO-VIDEO-0.1-PROPOSAL"
CHRONO_MANIFEST_SCHEMA = "ugts-chrono-video-observation-manifest-0.1"
CHRONO_PROFILE_SCHEMA = "ugts-chrono-video-profile-0.1"
CHRONO_PROFILE_RECEIPT_SCHEMA = "ugts-chrono-video-profile-receipt-0.1"
CHRONO_IMPLEMENTATION_RECEIPT_SCHEMA = (
    "ugts-chrono-video-implementation-receipt-0.1"
)
CVLUT_MAGIC = b"UGCVLUT1"
CVLUT_MAJOR = 1
CVLUT_MINOR = 0
# magic, version, source dimensions, polar dimensions, chart parameters,
# payload digest.  The payload is little-endian RGBA16UI, rho-major.
_CVLUT_HEADER = struct.Struct("<8sHHIIII6d32s")
_CVLUT_TEXEL = struct.Struct("<HHHH")

CVPTS_MAGIC = b"UGCVPTS1"
CVPTS_MAJOR = 1
CVPTS_MINOR = 0
CVPTS_HEADER_BYTES = 208
CVPTS_ENTRY_BYTES = 32
CVPTS_MEDIA_ORIGINAL_SOURCE = 1 << 0
CVPTS_MEDIA_DERIVED_POLAR_PREVIEW = 1 << 1
CVPTS_APPLY_UGCVLUT1_Q8 = 1 << 2
CVPTS_ALREADY_LOG_POLAR = 1 << 3
CVPTS_LOOP = 1 << 4
# Fixed 208-byte header. The content digest is SHA-256 over the complete file
# with its own 32-byte field zeroed, so header and entries are bound together.
_CVPTS_HEADER = struct.Struct("<8sHHIIIIIIIIqqQQ32s32s32s32sI")
_CVPTS_ENTRY = struct.Struct("<IIqqII")


class ChronoVideoError(RuntimeError):
    """A fail-closed compiler or format error."""


@dataclass(frozen=True)
class ChronoVideoProfile:
    """Bounded deterministic execution and sampling profile."""

    theta_bins: int = 1024
    rho_bins: int = 512
    sample_stride: int = 4
    tile_size: int = 64
    batch_size: int = 8
    max_vram_mib: int = 1536
    r0_pixels: float = 1.0
    core_radius_pixels: float = 0.5
    proposal_dynamic_fraction: float = 0.20
    proposal_mad_multiplier: float = 3.0
    target_kind: str = "scene"
    embed_source_for_phone: bool = False

    def validate(self) -> None:
        if not 16 <= self.theta_bins <= 8192 or self.theta_bins % 2:
            raise ValueError("theta_bins must be even and in [16, 8192]")
        if not 16 <= self.rho_bins <= 4096 or self.rho_bins % 2:
            raise ValueError("rho_bins must be even and in [16, 4096]")
        if self.theta_bins * self.rho_bins > 16_777_216:
            raise ValueError("polar LUT exceeds the 16,777,216 texel profile limit")
        if self.sample_stride < 1:
            raise ValueError("sample_stride must be at least 1")
        if not 8 <= self.tile_size <= 1024:
            raise ValueError("tile_size must be in [8, 1024]")
        if not 1 <= self.batch_size <= 64:
            raise ValueError("batch_size must be in [1, 64]")
        if not 128 <= self.max_vram_mib <= 10_240:
            raise ValueError("max_vram_mib must be in [128, 10240]")
        if not math.isfinite(self.r0_pixels) or self.r0_pixels <= 0:
            raise ValueError("r0_pixels must be finite and positive")
        if not math.isfinite(self.core_radius_pixels) or self.core_radius_pixels <= 0:
            raise ValueError("core_radius_pixels must be finite and positive")
        if not 0 < self.proposal_dynamic_fraction <= 1:
            raise ValueError("proposal_dynamic_fraction must be in (0, 1]")
        if not math.isfinite(self.proposal_mad_multiplier) or self.proposal_mad_multiplier <= 0:
            raise ValueError("proposal_mad_multiplier must be finite and positive")
        if self.target_kind not in {"scene", "human"}:
            raise ValueError("target_kind must be scene or human")
        if not isinstance(self.embed_source_for_phone, bool):
            raise ValueError("embed_source_for_phone must be boolean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CHRONO_PROFILE_SCHEMA,
            "profile": CHRONO_PROFILE,
            "theta_bins": self.theta_bins,
            "rho_bins": self.rho_bins,
            "sample_stride": self.sample_stride,
            "tile_size": self.tile_size,
            "batch_size": self.batch_size,
            "max_vram_mib": self.max_vram_mib,
            "r0_pixels": self.r0_pixels,
            "core_radius_pixels": self.core_radius_pixels,
            "proposal_dynamic_fraction": self.proposal_dynamic_fraction,
            "proposal_mad_multiplier": self.proposal_mad_multiplier,
            "target_kind": self.target_kind,
            "embed_source_for_phone": self.embed_source_for_phone,
        }

    def content_hash(self) -> str:
        return hashlib.sha256(_canonical_json_bytes(self.to_dict())).hexdigest()


@dataclass(frozen=True)
class ChronoCompileResult:
    output_dir: Path
    manifest: Path
    project: Path
    preview: Path
    source_sha256: str
    manifest_sha256: str
    decoded_frames: int
    analyzed_frames: int
    compute_backend: str
    decode_backend: str
    elapsed_seconds: float
    cuda_peak_mib: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "ugts-chrono-video-compile-result-0.1",
            "output_dir": str(self.output_dir),
            "manifest": str(self.manifest),
            "project": str(self.project),
            "preview": str(self.preview),
            "source_sha256": self.source_sha256,
            "manifest_sha256": self.manifest_sha256,
            "decoded_frames": self.decoded_frames,
            "analyzed_frames": self.analyzed_frames,
            "compute_backend": self.compute_backend,
            "decode_backend": self.decode_backend,
            "elapsed_seconds": self.elapsed_seconds,
            "cuda_peak_mib": self.cuda_peak_mib,
        }


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _write_jsonl_line(stream: Any, value: Mapping[str, Any]) -> None:
    stream.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")


def _sha256_file(path: Path, chunk_bytes: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            block = stream.read(chunk_bytes)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _tool_version_line(name: str) -> str:
    """Return the executable's own first version line without normalizing it."""
    try:
        completed = subprocess.run(
            [_tool_path(name), "-version"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ChronoVideoError(f"could not record {name} implementation version") from exc
    line = next(
        (item.strip() for item in completed.stdout.splitlines() if item.strip()),
        "",
    )
    if not line:
        raise ChronoVideoError(f"{name} returned no implementation version")
    return line


def _module_version(module: Any, label: str) -> str:
    value = getattr(module, "__version__", None)
    if not isinstance(value, str) or not value.strip():
        raise ChronoVideoError(f"{label} does not expose a usable __version__")
    return value


def _implementation_receipt(compute_backend: str) -> dict[str, Any]:
    """Capture only versions selected by this compiler invocation."""
    try:
        import av
        import cv2
        import numpy as np
    except ImportError as exc:
        raise ChronoVideoError(
            "cannot record selected NumPy/PyAV/OpenCV implementation versions"
        ) from exc

    torch_version: str | None = None
    torch_cuda_runtime: str | None = None
    if compute_backend == "torch-cuda-q8":
        try:
            import torch
        except ImportError as exc:
            raise ChronoVideoError(
                "cannot record the selected PyTorch CUDA implementation version"
            ) from exc
        torch_version = _module_version(torch, "PyTorch")
        cuda_value = getattr(torch.version, "cuda", None)
        if not isinstance(cuda_value, str) or not cuda_value.strip():
            raise ChronoVideoError(
                "selected PyTorch CUDA backend exposes no CUDA runtime version"
            )
        torch_cuda_runtime = cuda_value
    elif compute_backend != "numpy-cpu-q8":
        raise ChronoVideoError(f"unknown selected compute backend: {compute_backend}")

    return {
        "schema": CHRONO_IMPLEMENTATION_RECEIPT_SCHEMA,
        "ugts_kc3": {
            "version": __version__,
            "chrono_video_module_sha256": _sha256_file(Path(__file__).resolve()),
        },
        "python": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
        },
        "dependencies": {
            "numpy": _module_version(np, "NumPy"),
            "pyav": _module_version(av, "PyAV"),
            "opencv": _module_version(cv2, "OpenCV"),
            "torch": torch_version,
            "torch_cuda_runtime": torch_cuda_runtime,
        },
        "executables": {
            "ffmpeg": _tool_version_line("ffmpeg"),
            "ffprobe": _tool_version_line("ffprobe"),
        },
        "selected": {
            "compute_backend": compute_backend,
            "decode_backend": "pyav-cpu-exact-pts",
            "preview_encoder": "ffmpeg-libx264",
        },
    }


def _exact_mapping_keys(
    value: object, expected: set[str], label: str
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ChronoVideoError(f"{label} must be an object")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        detail = []
        if missing:
            detail.append(f"missing {', '.join(missing)}")
        if extra:
            detail.append(f"unexpected {', '.join(extra)}")
        raise ChronoVideoError(f"{label} fields are not canonical: {'; '.join(detail)}")
    return value


def _profile_from_mapping(value: object) -> ChronoVideoProfile:
    expected_keys = set(ChronoVideoProfile().to_dict())
    profile_value = _exact_mapping_keys(value, expected_keys, "canonical profile")
    if profile_value.get("schema") != CHRONO_PROFILE_SCHEMA:
        raise ChronoVideoError("canonical profile schema mismatch")
    if profile_value.get("profile") != CHRONO_PROFILE:
        raise ChronoVideoError("canonical profile identity mismatch")
    integer_fields = (
        "theta_bins",
        "rho_bins",
        "sample_stride",
        "tile_size",
        "batch_size",
        "max_vram_mib",
    )
    float_fields = (
        "r0_pixels",
        "core_radius_pixels",
        "proposal_dynamic_fraction",
        "proposal_mad_multiplier",
    )
    if any(type(profile_value[field]) is not int for field in integer_fields):
        raise ChronoVideoError("canonical profile integer field has the wrong type")
    if any(type(profile_value[field]) is not float for field in float_fields):
        raise ChronoVideoError("canonical profile floating field has the wrong type")
    if type(profile_value.get("target_kind")) is not str:
        raise ChronoVideoError("canonical profile target_kind has the wrong type")
    if type(profile_value.get("embed_source_for_phone")) is not bool:
        raise ChronoVideoError(
            "canonical profile embed_source_for_phone has the wrong type"
        )
    profile = ChronoVideoProfile(
        **{
            field: profile_value[field]
            for field in expected_keys - {"schema", "profile"}
        }
    )
    try:
        profile.validate()
    except ValueError as exc:
        raise ChronoVideoError(f"canonical profile is invalid: {exc}") from exc
    if profile.to_dict() != dict(profile_value):
        raise ChronoVideoError("canonical profile does not round-trip exactly")
    return profile


def inspect_chrono_profile_receipt(receipt: object) -> dict[str, Any]:
    """Recompute and validate a canonical profile/implementation receipt."""
    root = _exact_mapping_keys(
        receipt,
        {"schema", "canonical_profile", "profile_sha256", "implementation"},
        "profile receipt",
    )
    if root.get("schema") != CHRONO_PROFILE_RECEIPT_SCHEMA:
        raise ChronoVideoError("profile receipt schema mismatch")
    profile = _profile_from_mapping(root.get("canonical_profile"))
    canonical_profile = profile.to_dict()
    actual_hash = hashlib.sha256(_canonical_json_bytes(canonical_profile)).hexdigest()
    declared_hash = root.get("profile_sha256")
    _digest_bytes(declared_hash, "profile receipt profile_sha256")
    if declared_hash != actual_hash:
        raise ChronoVideoError("profile receipt SHA-256 mismatch")

    implementation = _exact_mapping_keys(
        root.get("implementation"),
        {"schema", "ugts_kc3", "python", "dependencies", "executables", "selected"},
        "implementation receipt",
    )
    if implementation.get("schema") != CHRONO_IMPLEMENTATION_RECEIPT_SCHEMA:
        raise ChronoVideoError("implementation receipt schema mismatch")
    package = _exact_mapping_keys(
        implementation.get("ugts_kc3"),
        {"version", "chrono_video_module_sha256"},
        "implementation ugts_kc3",
    )
    runtime = _exact_mapping_keys(
        implementation.get("python"),
        {"implementation", "version"},
        "implementation python",
    )
    dependencies = _exact_mapping_keys(
        implementation.get("dependencies"),
        {"numpy", "pyav", "opencv", "torch", "torch_cuda_runtime"},
        "implementation dependencies",
    )
    executables = _exact_mapping_keys(
        implementation.get("executables"),
        {"ffmpeg", "ffprobe"},
        "implementation executables",
    )
    selected = _exact_mapping_keys(
        implementation.get("selected"),
        {"compute_backend", "decode_backend", "preview_encoder"},
        "implementation selection",
    )
    for label, value in (
        ("ugts_kc3 version", package.get("version")),
        ("Python implementation", runtime.get("implementation")),
        ("Python version", runtime.get("version")),
        ("NumPy version", dependencies.get("numpy")),
        ("PyAV version", dependencies.get("pyav")),
        ("OpenCV version", dependencies.get("opencv")),
        ("ffmpeg version", executables.get("ffmpeg")),
        ("ffprobe version", executables.get("ffprobe")),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ChronoVideoError(f"{label} must be a nonempty recorded string")
    _digest_bytes(
        package.get("chrono_video_module_sha256"),
        "implementation chrono_video_module_sha256",
    )
    if not str(executables["ffmpeg"]).startswith("ffmpeg version "):
        raise ChronoVideoError("implementation ffmpeg version line is malformed")
    if not str(executables["ffprobe"]).startswith("ffprobe version "):
        raise ChronoVideoError("implementation ffprobe version line is malformed")
    compute_backend = selected.get("compute_backend")
    if compute_backend not in {"numpy-cpu-q8", "torch-cuda-q8"}:
        raise ChronoVideoError("implementation compute backend is unsupported")
    if selected.get("decode_backend") != "pyav-cpu-exact-pts":
        raise ChronoVideoError("implementation decode backend is unsupported")
    if selected.get("preview_encoder") != "ffmpeg-libx264":
        raise ChronoVideoError("implementation preview encoder is unsupported")
    torch_values = (dependencies.get("torch"), dependencies.get("torch_cuda_runtime"))
    if compute_backend == "torch-cuda-q8":
        if any(not isinstance(value, str) or not value.strip() for value in torch_values):
            raise ChronoVideoError("selected CUDA implementation versions are missing")
    elif torch_values != (None, None):
        raise ChronoVideoError("unselected CUDA dependency versions must be null")
    return {
        "schema": CHRONO_PROFILE_RECEIPT_SCHEMA,
        "canonical_profile": canonical_profile,
        "profile_sha256": actual_hash,
        "implementation": json.loads(json.dumps(implementation)),
    }


def _tool_path(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise ChronoVideoError(f"required executable is unavailable: {name}")
    return path


def _run_json(command: Sequence[str]) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            list(command), check=True, capture_output=True, text=True, encoding="utf-8"
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        stderr = getattr(exc, "stderr", "") or ""
        detail = stderr.strip()[-2000:]
        raise ChronoVideoError(
            f"command failed: {' '.join(command[:2])}{': ' + detail if detail else ''}"
        ) from exc
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ChronoVideoError("tool returned malformed JSON") from exc
    if not isinstance(value, dict):
        raise ChronoVideoError("tool JSON root must be an object")
    return value


def _fraction(text: str, field: str) -> Fraction:
    try:
        value = Fraction(text)
    except (ValueError, ZeroDivisionError) as exc:
        raise ChronoVideoError(f"invalid {field}: {text!r}") from exc
    if value.denominator == 0:
        raise ChronoVideoError(f"invalid {field}: zero denominator")
    return value


def probe_video(source: str | Path) -> dict[str, Any]:
    """Return a strict one-stream probe with every presentation timestamp."""
    source_path = Path(source).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    command = [
        _tool_path("ffprobe"),
        "-v", "error",
        "-select_streams", "v:0",
        "-show_streams",
        "-show_frames",
        "-show_entries",
        (
            "stream=index,codec_name,codec_long_name,profile,pix_fmt,width,height,"
            "level,has_b_frames,r_frame_rate,avg_frame_rate,time_base,start_pts,duration_ts,"
            "duration,nb_frames,color_range,color_space,color_transfer,color_primaries,"
            "sample_aspect_ratio,display_aspect_ratio:"
            "frame=media_type,stream_index,key_frame,pts,best_effort_timestamp,"
            "pkt_duration,pict_type,width,height,pix_fmt"
        ),
        "-of", "json",
        str(source_path),
    ]
    raw = _run_json(command)
    streams = raw.get("streams", [])
    if not isinstance(streams, list) or len(streams) != 1:
        raise ChronoVideoError("ffprobe did not return exactly one selected video stream")
    stream = streams[0]
    if not isinstance(stream, dict):
        raise ChronoVideoError("video stream probe is malformed")
    width = int(stream.get("width", 0))
    height = int(stream.get("height", 0))
    if not 1 <= width <= 65_535 or not 1 <= height <= 65_535:
        raise ChronoVideoError("source dimensions exceed the CVLUT1 uint16 address profile")
    time_base = _fraction(str(stream.get("time_base", "0/0")), "time_base")
    frames: list[dict[str, Any]] = []
    for raw_frame in raw.get("frames", []):
        if not isinstance(raw_frame, dict) or raw_frame.get("media_type") != "video":
            continue
        pts_value = raw_frame.get("best_effort_timestamp", raw_frame.get("pts"))
        if pts_value is None:
            raise ChronoVideoError("video frame lacks a presentation timestamp")
        pts = int(pts_value)
        frames.append(
            {
                "decode_index": len(frames),
                "pts": pts,
                "duration_ticks": (
                    int(raw_frame["pkt_duration"])
                    if raw_frame.get("pkt_duration") is not None
                    else None
                ),
                "key_frame": bool(int(raw_frame.get("key_frame", 0))),
                "picture_type": str(raw_frame.get("pict_type", "")),
            }
        )
    if not frames:
        raise ChronoVideoError("source has no video frames")
    if any(b["pts"] <= a["pts"] for a, b in zip(frames, frames[1:])):
        raise ChronoVideoError(
            "presentation timestamps are not strictly increasing; exact half-open "
            "runtime intervals cannot be formed"
        )
    return {
        "stream": dict(stream),
        "width": width,
        "height": height,
        "time_base_num": time_base.numerator,
        "time_base_den": time_base.denominator,
        "frames": frames,
    }


def _lut_parameters(
    width: int, height: int, profile: ChronoVideoProfile
) -> tuple[float, float, float, float, float, float]:
    center_x = (width - 1) * 0.5
    center_y = (height - 1) * 0.5
    far_x = max(center_x, (width - 1) - center_x)
    far_y = max(center_y, (height - 1) - center_y)
    far_radius = math.hypot(far_x, far_y)
    rho_min = math.log(profile.core_radius_pixels / profile.r0_pixels)
    rho_max = math.log(far_radius / profile.r0_pixels)
    return (
        center_x,
        center_y,
        profile.r0_pixels,
        profile.core_radius_pixels,
        rho_min,
        rho_max,
    )


def generate_video_polar_lut(
    width: int, height: int, profile: ChronoVideoProfile = ChronoVideoProfile()
) -> bytes:
    """Generate a CVLUT1 integer sampling texture.

    Each RGBA16UI texel contains ``x0, y0, fx | (fy << 8), valid``.  ``fx``
    and ``fy`` are Q8 bilinear fractions.  This supports byte-identical CPU and
    integer-CUDA sampling of 8-bit source frames.
    """
    profile.validate()
    if not 1 <= width <= 65_535 or not 1 <= height <= 65_535:
        raise ValueError("source width and height must fit uint16")
    try:
        import numpy as np
    except ImportError as exc:
        raise ChronoVideoError("CVLUT1 generation requires NumPy") from exc
    center_x, center_y, r0, core, rho_min, rho_max = _lut_parameters(
        width, height, profile
    )
    rho = np.linspace(rho_min, rho_max, profile.rho_bins, dtype=np.float64)
    theta = (
        np.arange(profile.theta_bins, dtype=np.float64)
        * (2.0 * math.pi / profile.theta_bins)
    )
    radius = r0 * np.exp(rho)[:, None]
    x = center_x + radius * np.cos(theta)[None, :]
    y = center_y + radius * np.sin(theta)[None, :]
    # Canonical round-to-nearest for non-negative in-range pixel coordinates.
    xq = np.floor(np.clip(x, 0.0, width - 1) * 256.0 + 0.5).astype(np.int64)
    yq = np.floor(np.clip(y, 0.0, height - 1) * 256.0 + 0.5).astype(np.int64)
    # A valid Q8 bilinear address owns a complete four-neighbour footprint.
    # Border coordinates that would require clamping are explicit invalid
    # samples, keeping Python/CUDA/native GLES semantics identical.
    valid = (
        (x >= 0.0)
        & (x <= width - 1)
        & (y >= 0.0)
        & (y <= height - 1)
        & ((xq >> 8) + 1 < width)
        & ((yq >> 8) + 1 < height)
    )
    lanes = np.zeros((profile.rho_bins, profile.theta_bins, 4), dtype="<u2")
    lanes[..., 0] = np.minimum(xq >> 8, width - 1).astype(np.uint16)
    lanes[..., 1] = np.minimum(yq >> 8, height - 1).astype(np.uint16)
    lanes[..., 2] = (
        ((xq & 255) | ((yq & 255) << 8)).astype(np.uint16)
    )
    lanes[..., 3] = valid.astype(np.uint16)
    payload = lanes.tobytes(order="C")
    payload_hash = hashlib.sha256(payload).digest()
    header = _CVLUT_HEADER.pack(
        CVLUT_MAGIC,
        CVLUT_MAJOR,
        CVLUT_MINOR,
        width,
        height,
        profile.theta_bins,
        profile.rho_bins,
        center_x,
        center_y,
        r0,
        core,
        rho_min,
        rho_max,
        payload_hash,
    )
    return header + payload


def inspect_video_polar_lut(data: bytes) -> dict[str, Any]:
    """Validate a complete CVLUT1 byte string and return its header receipt."""
    if len(data) < _CVLUT_HEADER.size:
        raise ChronoVideoError("CVLUT1 is truncated before its header")
    unpacked = _CVLUT_HEADER.unpack_from(data)
    (
        magic,
        major,
        minor,
        width,
        height,
        theta_bins,
        rho_bins,
        center_x,
        center_y,
        r0,
        core,
        rho_min,
        rho_max,
        expected_hash,
    ) = unpacked
    if magic != CVLUT_MAGIC:
        raise ChronoVideoError("CVLUT1 magic mismatch")
    if (major, minor) != (CVLUT_MAJOR, CVLUT_MINOR):
        raise ChronoVideoError(f"unsupported CVLUT version {major}.{minor}")
    if not width or not height or not theta_bins or not rho_bins:
        raise ChronoVideoError("CVLUT1 dimensions must be nonzero")
    expected_bytes = theta_bins * rho_bins * _CVLUT_TEXEL.size
    payload = data[_CVLUT_HEADER.size :]
    if len(payload) != expected_bytes:
        raise ChronoVideoError(
            f"CVLUT1 payload length mismatch: expected {expected_bytes}, got {len(payload)}"
        )
    actual_hash = hashlib.sha256(payload).digest()
    if actual_hash != expected_hash:
        raise ChronoVideoError("CVLUT1 payload SHA-256 mismatch")
    for x0, y0, _fractions, valid in struct.iter_unpack("<4H", payload):
        if valid > 1:
            raise ChronoVideoError("CVLUT1 valid lane is not boolean")
        if x0 >= width or y0 >= height:
            raise ChronoVideoError("CVLUT1 source address is out of range")
        if valid and (x0 + 1 >= width or y0 + 1 >= height):
            raise ChronoVideoError(
                "CVLUT1 valid bilinear footprint exceeds the source raster"
            )
    return {
        "schema": "ugts-chrono-video-lut-inspection-0.1",
        "magic": magic.decode("ascii"),
        "version": f"{major}.{minor}",
        "source_width": width,
        "source_height": height,
        "theta_bins": theta_bins,
        "rho_bins": rho_bins,
        "center_x": center_x,
        "center_y": center_y,
        "r0_pixels": r0,
        "core_radius_pixels": core,
        "rho_min": rho_min,
        "rho_max": rho_max,
        "payload_bytes": len(payload),
        "payload_sha256": actual_hash.hex(),
        "texture_format": "RGBA16UI",
        "lane_contract": ["x0", "y0", "fx_q8|(fy_q8<<8)", "valid"],
        "interpolation": "explicit Q8 bilinear integer accumulation with +32768 then >>16",
    }


def _digest_bytes(value: str, field: str) -> bytes:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ChronoVideoError(f"{field} must be lowercase SHA-256 hex")
    try:
        result = bytes.fromhex(value)
    except ValueError as exc:
        raise ChronoVideoError(f"{field} must be lowercase SHA-256 hex") from exc
    if len(result) != 32:
        raise ChronoVideoError(f"{field} must be lowercase SHA-256 hex")
    return result


def _exact_android_media_time_us(
    source_pts: int, time_base_num: int, time_base_den: int
) -> int:
    """Map source PTS to MediaCodec microseconds without rounding."""
    if source_pts < 0:
        raise ChronoVideoError("embedded Android source PTS must be non-negative")
    numerator = source_pts * time_base_num * 1_000_000
    value, remainder = divmod(numerator, time_base_den)
    if remainder:
        raise ChronoVideoError(
            "embedded Android source PTS is not exactly representable in "
            "MediaCodec microseconds"
        )
    if value > (1 << 63) - 1:
        raise ChronoVideoError("embedded Android source PTS exceeds int64 microseconds")
    return value


def _validate_pts_entries(
    entries: Sequence[Mapping[str, Any]], source_frame_count: int
) -> list[dict[str, int]]:
    if not 1 <= len(entries) <= 1_000_000:
        raise ChronoVideoError("UGCVPTS1 entry count must be in [1, 1000000]")
    if not 1 <= source_frame_count <= 10_000_000:
        raise ChronoVideoError("UGCVPTS1 source frame count is outside its profile")
    normalized: list[dict[str, int]] = []
    previous_frame = -1
    previous_pts: int | None = None
    previous_end: int | None = None
    for media_index, raw in enumerate(entries):
        try:
            declared_index = int(raw["media_index"])
            source_frame_index = int(raw["source_frame_index"])
            source_pts = int(raw["source_pts"])
            display_until = int(raw["display_until_source_pts"])
            entry_flags = int(raw.get("flags", 0))
        except (KeyError, TypeError, ValueError) as exc:
            raise ChronoVideoError(f"UGCVPTS1 entry {media_index} is malformed") from exc
        if declared_index != media_index:
            raise ChronoVideoError("UGCVPTS1 media indices must be dense from zero")
        if not 0 <= declared_index <= 0xFFFFFFFF:
            raise ChronoVideoError("UGCVPTS1 media index exceeds uint32")
        if not previous_frame < source_frame_index < source_frame_count:
            raise ChronoVideoError("UGCVPTS1 source frame indices must increase strictly")
        if source_frame_index > 0xFFFFFFFF:
            raise ChronoVideoError("UGCVPTS1 source frame index exceeds uint32")
        if not -(1 << 63) <= source_pts < (1 << 63):
            raise ChronoVideoError("UGCVPTS1 source PTS exceeds int64")
        if not -(1 << 63) <= display_until < (1 << 63):
            raise ChronoVideoError("UGCVPTS1 interval end exceeds int64")
        if previous_pts is not None and source_pts <= previous_pts:
            raise ChronoVideoError("UGCVPTS1 source PTS values must increase strictly")
        if display_until <= source_pts:
            raise ChronoVideoError("UGCVPTS1 intervals must be positive")
        if previous_end is not None and previous_end != source_pts:
            raise ChronoVideoError("UGCVPTS1 intervals must be contiguous")
        if entry_flags != 0:
            raise ChronoVideoError("UGCVPTS1 entry flags are reserved in version 1")
        normalized.append(
            {
                "media_index": media_index,
                "source_frame_index": source_frame_index,
                "source_pts": source_pts,
                "display_until_source_pts": display_until,
                "flags": 0,
            }
        )
        previous_frame = source_frame_index
        previous_pts = source_pts
        previous_end = display_until
    if normalized[0]["source_frame_index"] != 0:
        raise ChronoVideoError("UGCVPTS1 first entry must bind source frame zero")
    if normalized[-1]["source_frame_index"] != source_frame_count - 1:
        raise ChronoVideoError("UGCVPTS1 final entry must bind the final source frame")
    return normalized


def generate_video_pts_cache(
    *,
    entries: Sequence[Mapping[str, Any]],
    source_frame_count: int,
    media_width: int,
    media_height: int,
    time_base_num: int,
    time_base_den: int,
    source_sha256: str,
    profile_sha256: str,
    media_sha256: str,
    flags: int,
) -> bytes:
    """Build a strict ordinal-to-exact-source-PTS runtime cache."""
    if _CVPTS_HEADER.size != CVPTS_HEADER_BYTES or _CVPTS_ENTRY.size != CVPTS_ENTRY_BYTES:
        raise AssertionError("UGCVPTS1 Python ABI constants disagree")
    if not 1 <= media_width <= 65_535 or not 1 <= media_height <= 65_535:
        raise ChronoVideoError("UGCVPTS1 media dimensions are outside its profile")
    # Match the native API-26 reader's signed-__int128 clock profile exactly.
    if not 1 <= time_base_num <= (1 << 63) - 1:
        raise ChronoVideoError("UGCVPTS1 time-base numerator is invalid")
    if not 1 <= time_base_den <= (1 << 63) - 1:
        raise ChronoVideoError("UGCVPTS1 time-base denominator is invalid")
    known_flags = (
        CVPTS_MEDIA_ORIGINAL_SOURCE
        | CVPTS_MEDIA_DERIVED_POLAR_PREVIEW
        | CVPTS_APPLY_UGCVLUT1_Q8
        | CVPTS_ALREADY_LOG_POLAR
        | CVPTS_LOOP
    )
    if flags & ~known_flags:
        raise ChronoVideoError("UGCVPTS1 has unknown header flags")
    original = bool(flags & CVPTS_MEDIA_ORIGINAL_SOURCE)
    preview = bool(flags & CVPTS_MEDIA_DERIVED_POLAR_PREVIEW)
    apply_lut = bool(flags & CVPTS_APPLY_UGCVLUT1_Q8)
    already_polar = bool(flags & CVPTS_ALREADY_LOG_POLAR)
    if original == preview or apply_lut == already_polar:
        raise ChronoVideoError("UGCVPTS1 media/raster flags are contradictory")
    if original != apply_lut or preview != already_polar:
        raise ChronoVideoError("UGCVPTS1 media/raster flags do not match")
    normalized = _validate_pts_entries(entries, source_frame_count)
    first_pts = normalized[0]["source_pts"]
    end_pts = normalized[-1]["display_until_source_pts"]
    if end_pts <= first_pts:
        raise ChronoVideoError("UGCVPTS1 exclusive end must follow its first PTS")
    payload = b"".join(
        _CVPTS_ENTRY.pack(
            item["media_index"],
            item["source_frame_index"],
            item["source_pts"],
            item["display_until_source_pts"],
            item["flags"],
            0,
        )
        for item in normalized
    )
    source_digest = _digest_bytes(source_sha256, "source_sha256")
    profile_digest = _digest_bytes(profile_sha256, "profile_sha256")
    media_digest = _digest_bytes(media_sha256, "media_sha256")
    zero_digest = bytes(32)
    header = _CVPTS_HEADER.pack(
        CVPTS_MAGIC,
        CVPTS_MAJOR,
        CVPTS_MINOR,
        CVPTS_HEADER_BYTES,
        CVPTS_ENTRY_BYTES,
        flags,
        len(normalized),
        media_width,
        media_height,
        source_frame_count,
        0,
        first_pts,
        end_pts,
        time_base_num,
        time_base_den,
        source_digest,
        profile_digest,
        media_digest,
        zero_digest,
        0,
    )
    unsigned = header + payload
    content_digest = hashlib.sha256(unsigned).digest()
    header = _CVPTS_HEADER.pack(
        CVPTS_MAGIC,
        CVPTS_MAJOR,
        CVPTS_MINOR,
        CVPTS_HEADER_BYTES,
        CVPTS_ENTRY_BYTES,
        flags,
        len(normalized),
        media_width,
        media_height,
        source_frame_count,
        0,
        first_pts,
        end_pts,
        time_base_num,
        time_base_den,
        source_digest,
        profile_digest,
        media_digest,
        content_digest,
        0,
    )
    return header + payload


def _decode_video_pts_cache(data: bytes) -> tuple[dict[str, Any], list[dict[str, int]]]:
    if len(data) < CVPTS_HEADER_BYTES:
        raise ChronoVideoError("UGCVPTS1 header is truncated")
    try:
        (
            magic,
            major,
            minor,
            header_bytes,
            entry_bytes,
            flags,
            entry_count,
            media_width,
            media_height,
            source_frame_count,
            reserved0,
            first_pts,
            end_pts,
            time_base_num,
            time_base_den,
            source_digest,
            profile_digest,
            media_digest,
            content_digest,
            reserved1,
        ) = _CVPTS_HEADER.unpack_from(data)
    except struct.error as exc:
        raise ChronoVideoError("UGCVPTS1 header is malformed") from exc
    if magic != CVPTS_MAGIC:
        raise ChronoVideoError("UGCVPTS1 magic mismatch")
    if (major, minor) != (CVPTS_MAJOR, CVPTS_MINOR):
        raise ChronoVideoError(f"unsupported UGCVPTS1 version {major}.{minor}")
    if header_bytes != CVPTS_HEADER_BYTES or entry_bytes != CVPTS_ENTRY_BYTES:
        raise ChronoVideoError("UGCVPTS1 header or entry ABI mismatch")
    if reserved0 or reserved1:
        raise ChronoVideoError("UGCVPTS1 reserved fields must be zero")
    expected_bytes = header_bytes + entry_count * entry_bytes
    if len(data) != expected_bytes:
        raise ChronoVideoError(
            f"UGCVPTS1 length mismatch: expected {expected_bytes}, got {len(data)}"
        )
    unsigned = bytearray(data)
    unsigned[172:204] = bytes(32)
    if hashlib.sha256(unsigned).digest() != content_digest:
        raise ChronoVideoError("UGCVPTS1 content SHA-256 mismatch")
    entries: list[dict[str, int]] = []
    offset = header_bytes
    for index in range(entry_count):
        media_index, source_index, pts, display_until, entry_flags, reserved = (
            _CVPTS_ENTRY.unpack_from(data, offset)
        )
        if reserved:
            raise ChronoVideoError("UGCVPTS1 entry reserved field must be zero")
        entries.append(
            {
                "media_index": media_index,
                "source_frame_index": source_index,
                "source_pts": pts,
                "display_until_source_pts": display_until,
                "flags": entry_flags,
            }
        )
        offset += entry_bytes
    normalized = _validate_pts_entries(entries, source_frame_count)
    if normalized[0]["source_pts"] != first_pts:
        raise ChronoVideoError("UGCVPTS1 header first PTS mismatch")
    if normalized[-1]["display_until_source_pts"] != end_pts:
        raise ChronoVideoError("UGCVPTS1 header exclusive end mismatch")
    # Reuse the writer's flag and bound checks without accepting different bytes.
    regenerated = generate_video_pts_cache(
        entries=normalized,
        source_frame_count=source_frame_count,
        media_width=media_width,
        media_height=media_height,
        time_base_num=time_base_num,
        time_base_den=time_base_den,
        source_sha256=source_digest.hex(),
        profile_sha256=profile_digest.hex(),
        media_sha256=media_digest.hex(),
        flags=flags,
    )
    if regenerated != data:
        raise ChronoVideoError("UGCVPTS1 is not in canonical form")
    report = {
        "schema": "ugts-chrono-video-pts-cache-inspection-0.1",
        "magic": magic.decode("ascii"),
        "version": f"{major}.{minor}",
        "header_bytes": header_bytes,
        "entry_bytes": entry_bytes,
        "flags": flags,
        "entry_count": entry_count,
        "media_width": media_width,
        "media_height": media_height,
        "source_frame_count": source_frame_count,
        "first_source_pts": first_pts,
        "end_source_pts_exclusive": end_pts,
        "time_base_num": time_base_num,
        "time_base_den": time_base_den,
        "source_sha256": source_digest.hex(),
        "profile_sha256": profile_digest.hex(),
        "media_sha256": media_digest.hex(),
        "content_sha256": content_digest.hex(),
        "media_role": "ORIGINAL_SOURCE" if flags & CVPTS_MEDIA_ORIGINAL_SOURCE else "DERIVED_POLAR_PREVIEW",
        "raster_mode": "APPLY_UGCVLUT1_Q8" if flags & CVPTS_APPLY_UGCVLUT1_Q8 else "ALREADY_LOG_POLAR",
        "playback_mode": "LOOP_EXPLICIT_INTEGER_MODULO" if flags & CVPTS_LOOP else "ONCE_HOLD_LAST",
    }
    return report, normalized


def inspect_video_pts_cache(data: bytes) -> dict[str, Any]:
    """Validate a complete UGCVPTS1 cache and return its bounded receipt."""
    report, _entries = _decode_video_pts_cache(data)
    return report


def _lut_arrays(data: bytes) -> tuple[dict[str, Any], Any]:
    inspection = inspect_video_polar_lut(data)
    try:
        import numpy as np
    except ImportError as exc:
        raise ChronoVideoError("CVLUT1 sampling requires NumPy") from exc
    payload = data[_CVLUT_HEADER.size :]
    lanes = np.frombuffer(payload, dtype="<u2").reshape(
        inspection["rho_bins"], inspection["theta_bins"], 4
    )
    return inspection, lanes


def remap_rgb_q8_numpy(frame: Any, lut_data: bytes) -> Any:
    """Apply CVLUT1 to one RGB8 frame with the reference integer oracle."""
    try:
        import numpy as np
    except ImportError as exc:
        raise ChronoVideoError("CPU CVLUT1 sampling requires NumPy") from exc
    inspection, lanes = _lut_arrays(lut_data)
    array = np.asarray(frame)
    expected_shape = (
        inspection["source_height"], inspection["source_width"], 3
    )
    if array.shape != expected_shape or array.dtype != np.uint8:
        raise ValueError(f"frame must be RGB uint8 with shape {expected_shape}")
    x0 = lanes[..., 0].astype(np.int64)
    y0 = lanes[..., 1].astype(np.int64)
    packed = lanes[..., 2].astype(np.int64)
    fx = packed & 255
    fy = packed >> 8
    x1 = np.minimum(x0 + 1, inspection["source_width"] - 1)
    y1 = np.minimum(y0 + 1, inspection["source_height"] - 1)
    flat = array.reshape(-1, 3).astype(np.int32)
    width = inspection["source_width"]
    p00 = flat[(y0 * width + x0).reshape(-1)].reshape(*x0.shape, 3)
    p10 = flat[(y0 * width + x1).reshape(-1)].reshape(*x0.shape, 3)
    p01 = flat[(y1 * width + x0).reshape(-1)].reshape(*x0.shape, 3)
    p11 = flat[(y1 * width + x1).reshape(-1)].reshape(*x0.shape, 3)
    w00 = ((256 - fx) * (256 - fy))[..., None]
    w10 = (fx * (256 - fy))[..., None]
    w01 = ((256 - fx) * fy)[..., None]
    w11 = (fx * fy)[..., None]
    output = (p00 * w00 + p10 * w10 + p01 * w01 + p11 * w11 + 32768) >> 16
    output[lanes[..., 3] == 0] = 0
    return output.astype(np.uint8)


class _CudaQ8Remapper:
    def __init__(self, lut_data: bytes, max_vram_mib: int):
        try:
            import numpy as np
            import torch
        except ImportError as exc:
            raise ChronoVideoError("CUDA CVLUT1 sampling requires NumPy and PyTorch") from exc
        if not torch.cuda.is_available():
            raise ChronoVideoError("PyTorch reports no CUDA device")
        inspection, lanes = _lut_arrays(lut_data)
        properties = torch.cuda.get_device_properties(0)
        if max_vram_mib * 1024 * 1024 > properties.total_memory:
            raise ChronoVideoError("declared VRAM workspace exceeds physical CUDA memory")
        self.np = np
        self.torch = torch
        self.inspection = inspection
        self.device = torch.device("cuda:0")
        x0 = lanes[..., 0].astype(np.int64).reshape(-1)
        y0 = lanes[..., 1].astype(np.int64).reshape(-1)
        packed = lanes[..., 2].astype(np.int64).reshape(-1)
        fx = packed & 255
        fy = packed >> 8
        x1 = np.minimum(x0 + 1, inspection["source_width"] - 1)
        y1 = np.minimum(y0 + 1, inspection["source_height"] - 1)
        width = inspection["source_width"]
        self.indices = tuple(
            torch.as_tensor(index, device=self.device, dtype=torch.int64)
            for index in (
                y0 * width + x0,
                y0 * width + x1,
                y1 * width + x0,
                y1 * width + x1,
            )
        )
        self.weights = tuple(
            torch.as_tensor(weight, device=self.device, dtype=torch.int32).view(1, -1, 1)
            for weight in (
                (256 - fx) * (256 - fy),
                fx * (256 - fy),
                (256 - fx) * fy,
                fx * fy,
            )
        )
        self.valid = torch.as_tensor(
            lanes[..., 3].reshape(-1) != 0, device=self.device
        ).view(1, -1, 1)
        self.device_name = torch.cuda.get_device_name(0)
        self.capability = list(torch.cuda.get_device_capability(0))
        self.total_memory = int(properties.total_memory)
        torch.cuda.reset_peak_memory_stats(self.device)

    def remap(self, frames: Sequence[Any]) -> Any:
        if not frames:
            return self.np.empty((0, 0, 0, 3), dtype=self.np.uint8)
        source = self.np.stack(frames, axis=0)
        expected = (
            len(frames),
            self.inspection["source_height"],
            self.inspection["source_width"],
            3,
        )
        if source.shape != expected or source.dtype != self.np.uint8:
            raise ValueError(f"CUDA source batch must be RGB uint8 with shape {expected}")
        torch = self.torch
        tensor = torch.as_tensor(source, device=self.device).reshape(len(frames), -1, 3).to(torch.int32)
        terms = [tensor[:, index, :] * weight for index, weight in zip(self.indices, self.weights)]
        output = ((terms[0] + terms[1] + terms[2] + terms[3] + 32768) >> 16)
        output = torch.where(self.valid, output, torch.zeros((), device=self.device, dtype=torch.int32))
        output = output.clamp_(0, 255).to(torch.uint8)
        output = output.reshape(
            len(frames), self.inspection["rho_bins"], self.inspection["theta_bins"], 3
        )
        result = output.cpu().numpy()
        torch.cuda.synchronize(self.device)
        return result

    @property
    def peak_mib(self) -> float:
        return self.torch.cuda.max_memory_allocated(self.device) / (1024 * 1024)


class _CpuQ8Remapper:
    def __init__(self, lut_data: bytes):
        self.lut_data = lut_data
        self.inspection = inspect_video_polar_lut(lut_data)

    def remap(self, frames: Sequence[Any]) -> Any:
        try:
            import numpy as np
        except ImportError as exc:
            raise ChronoVideoError("CPU remapping requires NumPy") from exc
        return np.stack([remap_rgb_q8_numpy(frame, self.lut_data) for frame in frames])

    @property
    def peak_mib(self) -> None:
        return None


def _select_remapper(
    backend: str, lut_data: bytes, max_vram_mib: int
) -> tuple[str, Any, dict[str, Any]]:
    if backend not in {"auto", "cuda", "cpu"}:
        raise ValueError("backend must be auto, cuda, or cpu")
    cuda_error: str | None = None
    if backend in {"auto", "cuda"}:
        try:
            remapper = _CudaQ8Remapper(lut_data, max_vram_mib)
            info = {
                "backend": "torch-cuda-q8",
                "device": remapper.device_name,
                "compute_capability": remapper.capability,
                "physical_vram_bytes": remapper.total_memory,
                "workspace_limit_mib": max_vram_mib,
                "integer_contract": True,
            }
            return "torch-cuda-q8", remapper, info
        except (ChronoVideoError, OSError, RuntimeError, ValueError) as exc:
            cuda_error = str(exc)
            if backend == "cuda":
                raise ChronoVideoError(f"requested CUDA backend unavailable: {exc}") from exc
    remapper = _CpuQ8Remapper(lut_data)
    return "numpy-cpu-q8", remapper, {
        "backend": "numpy-cpu-q8",
        "workspace_limit_mib": None,
        "integer_contract": True,
        "cuda_fallback_reason": cuda_error,
    }


def _tile_extents(width: int, height: int, tile_size: int) -> list[tuple[int, int, int, int]]:
    return [
        (x0, y0, min(width, x0 + tile_size), min(height, y0 + tile_size))
        for y0 in range(0, height, tile_size)
        for x0 in range(0, width, tile_size)
    ]


def verify_tile_partition(width: int, height: int, tile_size: int) -> dict[str, Any]:
    """Prove rectangular tiles cover each source pixel exactly once."""
    if width < 1 or height < 1 or tile_size < 1:
        raise ValueError("width, height, and tile_size must be positive")
    extents = _tile_extents(width, height, tile_size)
    area = sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in extents)
    if area != width * height:
        raise AssertionError("tile partition area mismatch")
    return {
        "partition": "half-open-raster-tiles-row-major",
        "tile_count": len(extents),
        "covered_pixels": area,
        "source_pixels": width * height,
        "coverage_multiplicity": 1,
        "canonical_state": "UNKNOWN",
    }


def _dynamic_tile_components(
    tiles: Sequence[Mapping[str, Any]], width: int, height: int, tile_size: int
) -> list[dict[str, Any]]:
    """Return canonical 4-neighbor components of dynamic-candidate tiles."""
    columns = (width + tile_size - 1) // tile_size
    rows = (height + tile_size - 1) // tile_size
    dynamic = {
        int(tile["tile_index"])
        for tile in tiles
        if tile.get("proposal") == "DYNAMIC_CANDIDATE"
    }
    components: list[dict[str, Any]] = []
    while dynamic:
        seed = min(dynamic)
        dynamic.remove(seed)
        queue = [seed]
        members: list[int] = []
        while queue:
            index = queue.pop(0)
            members.append(index)
            x = index % columns
            y = index // columns
            neighbors = []
            if x > 0:
                neighbors.append(index - 1)
            if x + 1 < columns:
                neighbors.append(index + 1)
            if y > 0:
                neighbors.append(index - columns)
            if y + 1 < rows:
                neighbors.append(index + columns)
            for neighbor in sorted(neighbors):
                if neighbor in dynamic:
                    dynamic.remove(neighbor)
                    queue.append(neighbor)
        members.sort()
        bounds = [tiles[index]["bounds_xyxy"] for index in members]
        components.append(
            {
                "chart_candidate": f"motion_chart_{len(components):04d}",
                "tile_indices": members,
                "bounds_xyxy": [
                    min(bound[0] for bound in bounds),
                    min(bound[1] for bound in bounds),
                    max(bound[2] for bound in bounds),
                    max(bound[3] for bound in bounds),
                ],
                "authority": "PROPOSAL_ONLY",
                "semantic_part": "UNKNOWN",
                "cross_time_identity": "UNKNOWN",
            }
        )
    return components


def _motion_proposal(
    previous_rgb: Any,
    current_rgb: Any,
    extents: Sequence[tuple[int, int, int, int]],
    profile: ChronoVideoProfile,
) -> dict[str, Any]:
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise ChronoVideoError("motion proposals require OpenCV and NumPy") from exc
    cv2.setNumThreads(1)
    cv2.setRNGSeed(392)
    previous_gray = cv2.cvtColor(previous_rgb, cv2.COLOR_RGB2GRAY)
    current_gray = cv2.cvtColor(current_rgb, cv2.COLOR_RGB2GRAY)
    points0 = cv2.goodFeaturesToTrack(
        previous_gray,
        maxCorners=1200,
        qualityLevel=0.01,
        minDistance=7,
        blockSize=7,
    )
    track_count = 0
    inlier_count = 0
    transform: Any = None
    if points0 is not None and len(points0) >= 8:
        points1, status, _errors = cv2.calcOpticalFlowPyrLK(
            previous_gray,
            current_gray,
            points0,
            None,
            winSize=(21, 21),
            maxLevel=3,
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
        )
        if points1 is not None and status is not None:
            keep = status.reshape(-1) != 0
            p0 = points0.reshape(-1, 2)[keep]
            p1 = points1.reshape(-1, 2)[keep]
            finite = np.isfinite(p0).all(axis=1) & np.isfinite(p1).all(axis=1)
            p0 = p0[finite]
            p1 = p1[finite]
            track_count = int(len(p0))
            if track_count >= 8:
                transform, inliers = cv2.findHomography(
                    p0,
                    p1,
                    method=cv2.RANSAC,
                    ransacReprojThreshold=2.0,
                    maxIters=2000,
                    confidence=0.995,
                )
                if inliers is not None:
                    inlier_count = int(inliers.reshape(-1).sum())
    if transform is not None and np.isfinite(transform).all():
        aligned = cv2.warpPerspective(
            previous_gray,
            transform,
            (current_gray.shape[1], current_gray.shape[0]),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        )
        alignment = "HOMOGRAPHY_PROPOSAL"
        transform_list = [[float(value) for value in row] for row in transform]
    else:
        aligned = previous_gray
        alignment = "UNALIGNED_DIFFERENCE_PROPOSAL"
        transform_list = None
    residual = cv2.absdiff(current_gray, aligned)
    residual_f64 = residual.astype(np.float64)
    median = float(np.median(residual_f64))
    mad = float(np.median(np.abs(residual_f64 - median)))
    threshold = min(
        255.0,
        median + max(8.0, profile.proposal_mad_multiplier * 1.4826 * mad),
    )
    tiles: list[dict[str, Any]] = []
    labels: list[str] = []
    for tile_index, (x0, y0, x1, y1) in enumerate(extents):
        region = residual_f64[y0:y1, x0:x1]
        fraction = float(np.mean(region > threshold))
        p90 = float(np.percentile(region, 90))
        if fraction >= profile.proposal_dynamic_fraction:
            label = "DYNAMIC_CANDIDATE"
        elif p90 <= threshold:
            label = "STATIC_CANDIDATE"
        else:
            label = "AMBIGUOUS_CANDIDATE"
        labels.append(label)
        tiles.append(
            {
                "tile_index": tile_index,
                "bounds_xyxy": [x0, y0, x1, y1],
                "canonical_state": "UNKNOWN",
                "proposal": label,
                "mean_residual_u8": float(region.mean()),
                "p90_residual_u8": p90,
                "above_threshold_fraction": fraction,
            }
        )
    state_hash = hashlib.sha256(_canonical_json_bytes(labels)).hexdigest()
    components = _dynamic_tile_components(
        tiles, current_rgb.shape[1], current_rgb.shape[0], profile.tile_size
    )
    return {
        "authority": "PROPOSAL_ONLY",
        "geometry_commit": False,
        "static_commit": False,
        "alignment": alignment,
        "alignment_matrix": transform_list,
        "tracked_features": track_count,
        "alignment_inliers": inlier_count,
        "residual_median_u8": median,
        "residual_mad_u8": mad,
        "residual_threshold_u8": threshold,
        "proposal_state_sha256": state_hash,
        "motion_chart_candidates": components,
        "tiles": tiles,
    }


def _iter_pyav_frames(source: Path) -> Iterator[tuple[int, Fraction, Any]]:
    try:
        import av
    except ImportError as exc:
        raise ChronoVideoError("exact video decoding requires PyAV") from exc
    try:
        with av.open(str(source)) as container:
            streams = list(container.streams.video)
            if not streams:
                raise ChronoVideoError("PyAV found no video stream")
            stream = streams[0]
            stream.thread_type = "AUTO"
            for frame in container.decode(stream):
                if frame.pts is None or frame.time_base is None:
                    raise ChronoVideoError("decoded frame lacks exact PTS/time base")
                yield int(frame.pts), Fraction(frame.time_base), frame.to_ndarray(format="rgb24")
    except ChronoVideoError:
        raise
    except Exception as exc:
        raise ChronoVideoError(f"PyAV decode failed: {exc}") from exc


class _PreviewEncoder:
    def __init__(self, path: Path, width: int, height: int, frame_rate: Fraction):
        command = [
            _tool_path("ffmpeg"),
            "-hide_banner", "-loglevel", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-video_size", f"{width}x{height}",
            "-framerate", f"{frame_rate.numerator}/{frame_rate.denominator}",
            "-i", "pipe:0",
            "-an", "-c:v", "libx264", "-profile:v", "baseline",
            "-preset", "medium", "-crf", "18", "-bf", "0",
            "-g", "60", "-keyint_min", "60", "-sc_threshold", "0",
            "-x264-params", (
                "bframes=0:scenecut=0:keyint=60:min-keyint=60:"
                "colorprim=bt709:transfer=bt709:colormatrix=bt709:fullrange=off"
            ),
            "-vf", "scale=in_range=full:out_range=tv:out_color_matrix=bt709,format=yuv420p",
            "-color_range", "tv", "-colorspace", "bt709",
            "-color_primaries", "bt709", "-color_trc", "bt709",
            "-movflags", "+faststart", str(path),
        ]
        try:
            self.process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            raise ChronoVideoError(f"could not start preview encoder: {exc}") from exc
        self.path = path
        self.frame_count = 0

    def write(self, frame: Any) -> None:
        if self.process.stdin is None:
            raise ChronoVideoError("preview encoder stdin is unavailable")
        try:
            self.process.stdin.write(frame.tobytes(order="C"))
        except (BrokenPipeError, OSError) as exc:
            raise ChronoVideoError("preview encoder stopped while receiving frames") from exc
        self.frame_count += 1

    def close(self) -> None:
        if self.process.stdin is not None:
            self.process.stdin.close()
            self.process.stdin = None
        stderr = self.process.stderr.read() if self.process.stderr is not None else b""
        code = self.process.wait()
        if code != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()[-2000:]
            raise ChronoVideoError(f"preview encoder failed ({code}): {detail}")
        if self.frame_count < 1 or not self.path.is_file():
            raise ChronoVideoError("preview encoder produced no output")


def _validate_mobile_preview(
    preview_probe: Mapping[str, Any],
    *,
    expected_width: int,
    expected_height: int,
    expected_frames: int,
) -> None:
    stream = preview_probe.get("stream", {})
    if (
        preview_probe.get("width") != expected_width
        or preview_probe.get("height") != expected_height
    ):
        raise ChronoVideoError("encoded polar preview dimensions disagree")
    if len(preview_probe.get("frames", [])) != expected_frames:
        raise ChronoVideoError("encoded polar preview frame count disagrees")
    if stream.get("codec_name") != "h264":
        raise ChronoVideoError("encoded polar preview is not H.264")
    if stream.get("profile") not in {"Baseline", "Constrained Baseline"}:
        raise ChronoVideoError("encoded polar preview is not H.264 Baseline")
    if int(stream.get("has_b_frames", -1)) != 0:
        raise ChronoVideoError("encoded polar preview contains B-frames")
    if stream.get("pix_fmt") != "yuv420p":
        raise ChronoVideoError("encoded polar preview is not yuv420p")
    expected_color = {
        "color_range": "tv",
        "color_space": "bt709",
        "color_transfer": "bt709",
        "color_primaries": "bt709",
    }
    for field, expected in expected_color.items():
        if stream.get(field) != expected:
            raise ChronoVideoError(
                f"encoded polar preview {field} is {stream.get(field)!r}, expected {expected!r}"
            )


def _selected_indices(frame_count: int, stride: int) -> set[int]:
    selected = set(range(0, frame_count, stride))
    selected.add(frame_count - 1)
    return selected


def _asset_receipt(path: Path, root: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def _write_inspector_project(
    output_dir: Path,
    manifest_sha256: str,
    source_sha256: str,
    asset_receipts: Sequence[Mapping[str, Any]],
    duration_seconds: float,
    target_kind: str,
) -> Path:
    """Create one ordinary editable Grove scene root bound to the sidecar."""
    from .mobile3d import (
        AndroidTargetProfile,
        Camera3DRecord,
        Collider3DRecord,
        DirectionalLight3DRecord,
        Material3DRecord,
        Mobile3DProject,
        Node3DRecord,
        QualityTier3D,
        Transform3DRecord,
        World3DSettings,
        cube_mesh3d,
    )

    project = Mobile3DProject(
        id="chrono_video_observation_inspector",
        title="Chrono Video Observation Inspector",
        author="Tom Klootwijk",
        meshes={"observation_volume": cube_mesh3d("observation_volume")},
        materials={
            "unknown_evidence": Material3DRecord(
                "unknown_evidence",
                (0.10, 0.52, 0.95, 0.82),
                0.05,
                0.32,
                (0.02, 0.12, 0.28),
                True,
            )
        },
        nodes=(
            Node3DRecord(
                "chrono_observation_root",
                "observation_volume",
                "unknown_evidence",
                Transform3DRecord((0.0, 1.8, 0.0), scale=(5.6, 3.15, 0.08)),
                collider=Collider3DRecord("none"),
                dynamic=False,
                tags=("decorative",),
                metadata={
                    "chrono_observation_binding": {
                        "schema": CHRONO_MANIFEST_SCHEMA,
                        "manifest": "manifest.json",
                        "manifest_sha256": manifest_sha256,
                        "authority": "OBSERVATION_ONLY",
                        "materialization": "PROXY_ONLY",
                        "writer_owner": "chrono_scene_observation",
                    }
                },
            ),
        ),
        camera=Camera3DRecord(
            position=(0.0, 2.0, 8.5),
            target=(0.0, 1.8, 0.0),
            vertical_fov_degrees=48.0,
            near=0.05,
            far=40.0,
        ),
        light=DirectionalLight3DRecord(
            direction=(-0.4, -1.0, -0.25),
            color=(0.82, 0.92, 1.0),
            intensity=1.0,
            ambient=0.25,
        ),
        quality_tiers=(
            QualityTier3D("chrono_view_60", 60, 0.82, 512, 0, False, 0),
            QualityTier3D("chrono_view_safe", 45, 0.68, 256, 0, False, 0),
        ),
        target_profiles=(
            AndroidTargetProfile(
                "poco_x7_pro_12gb",
                "POCO X7 Pro 12 GB Chrono Viewer",
                preferred_abis=("arm64-v8a",),
                target_refresh_hz=60,
                memory_floor_mb=8192,
                device_hints=("POCO X7 Pro",),
                gpu_hints=("Mali-G720",),
                default_quality="chrono_view_60",
            ),
        ),
        world=World3DSettings(
            gravity=(0.0, 0.0, 0.0),
            floor_y=-4.0,
            bounds_min=(-12.0, -6.0, -12.0),
            bounds_max=(12.0, 10.0, 12.0),
            fixed_dt=1.0 / 60.0,
            player_speed=0.0,
            jump_speed=0.0,
        ),
        start_quality="chrono_view_60",
        background=(0.005, 0.009, 0.022, 1.0),
        metadata={
            "chrono_scene_observation": {
                "schema": CHRONO_MANIFEST_SCHEMA,
                "manifest": "manifest.json",
                "manifest_sha256": manifest_sha256,
                "source_sha256": source_sha256,
                "target_kind": target_kind,
                "authority": "OBSERVATION_ONLY",
                "geometry_status": "UNBOUNDED_UNKNOWN",
                "source_duration_seconds": duration_seconds,
                "runtime_assets": list(asset_receipts),
                "phone_role": "compact exact-PTS evidence viewer and downstream rasterizer",
                "phone_compile_status": "EXTERNAL_PHYSICAL_RECEIPT_REQUIRED",
            }
        },
    )
    project.validate()
    return project.write(output_dir / "project.json")


def compile_chrono_video(
    source: str | Path,
    output_dir: str | Path,
    profile: ChronoVideoProfile = ChronoVideoProfile(),
    backend: str = "auto",
) -> ChronoCompileResult:
    """Compile a source video into evidence, proposals, LUT, and an editable scene."""
    started = time.perf_counter()
    profile.validate()
    source_path = Path(source).resolve()
    output = Path(output_dir).resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    probe = probe_video(source_path)
    width = probe["width"]
    height = probe["height"]
    source_hash = _sha256_file(source_path)
    source_bytes = source_path.stat().st_size
    profile_hash = profile.content_hash()

    lut_data = generate_video_polar_lut(width, height, profile)
    lut_path = output / "polar_lut.ugcv1"
    lut_path.write_bytes(lut_data)
    lut_receipt = inspect_video_polar_lut(lut_data)
    _write_json(output / "polar_lut_inspection.json", lut_receipt)

    compute_backend, remapper, compute_receipt = _select_remapper(
        backend, lut_data, profile.max_vram_mib
    )
    frames = probe["frames"]
    time_base = Fraction(probe["time_base_num"], probe["time_base_den"])
    avg_rate = _fraction(str(probe["stream"].get("avg_frame_rate", "0/1")), "avg_frame_rate")
    if avg_rate <= 0:
        raise ChronoVideoError("source average frame rate must be positive")
    raw_duration_ticks = probe["stream"].get("duration_ts")
    if raw_duration_ticks is not None:
        duration_ticks = int(raw_duration_ticks)
    else:
        final_duration = frames[-1]["duration_ticks"] or 0
        duration_ticks = frames[-1]["pts"] - frames[0]["pts"] + final_duration
    duration = Fraction(duration_ticks, 1) * time_base
    if duration <= 0:
        raise ChronoVideoError("source duration must be positive")
    source_end_pts = frames[0]["pts"] + duration_ticks
    if source_end_pts <= frames[-1]["pts"]:
        raise ChronoVideoError(
            "source duration does not provide a positive final half-open frame interval"
        )
    selected = _selected_indices(len(frames), profile.sample_stride)
    selected_order = sorted(selected)
    preview_rate = Fraction(len(selected_order), 1) / duration
    preview_timeline_path = output / "preview_timeline.json"
    timeline_entries: list[dict[str, int]] = []
    for preview_index, frame_index in enumerate(selected_order):
        source_frame = frames[frame_index]
        next_pts = (
            frames[selected_order[preview_index + 1]]["pts"]
            if preview_index + 1 < len(selected_order)
            else source_end_pts
        )
        timeline_entries.append(
            {
                "preview_index": preview_index,
                "source_frame_index": frame_index,
                "source_pts": source_frame["pts"],
                "display_until_source_pts": next_pts,
            }
        )
    preview_path = output / "polar_preview.mp4"
    encoder = _PreviewEncoder(
        preview_path, profile.theta_bins, profile.rho_bins, preview_rate
    )
    observation_path = output / "observations.jsonl"
    proposal_path = output / "proposals.jsonl"
    hypothesis_path = output / "joint_hypotheses.jsonl"
    novelty_path = output / "novelty.jsonl"
    coverage = verify_tile_partition(width, height, profile.tile_size)
    extents = _tile_extents(width, height, profile.tile_size)
    batch_frames: list[Any] = []
    first_sample: Any | None = None
    first_gpu_polar: Any | None = None
    previous_sample: Any | None = None
    previous_labels: list[str] | None = None
    sampled_count = 0
    decoded_count = 0

    def flush_batch() -> None:
        nonlocal first_gpu_polar
        if not batch_frames:
            return
        outputs = remapper.remap(batch_frames)
        for remapped in outputs:
            if first_gpu_polar is None:
                first_gpu_polar = remapped.copy()
            encoder.write(remapped)
        batch_frames.clear()

    try:
        with observation_path.open("w", encoding="utf-8", newline="\n") as observations, proposal_path.open(
            "w", encoding="utf-8", newline="\n"
        ) as proposals, hypothesis_path.open(
            "w", encoding="utf-8", newline="\n"
        ) as hypotheses, novelty_path.open("w", encoding="utf-8", newline="\n") as novelty:
            _write_jsonl_line(
                novelty,
                {
                    "event_type": "SOURCE_BIND",
                    "commit_seq": 0,
                    "knowledge_index": 0,
                    "effective_pts": frames[0]["pts"],
                    "authority": "SOURCE_RECEIPT",
                    "source_sha256": source_hash,
                    "profile_sha256": profile_hash,
                },
            )
            for decode_index, (decoded_pts, decoded_tb, rgb) in enumerate(
                _iter_pyav_frames(source_path)
            ):
                if decode_index >= len(frames):
                    raise ChronoVideoError("decoder produced more frames than ffprobe")
                expected = frames[decode_index]
                if decoded_pts != expected["pts"] or decoded_tb != time_base:
                    raise ChronoVideoError(
                        "PyAV/ffprobe PTS disagreement at frame "
                        f"{decode_index}: {decoded_pts}@{decoded_tb} != "
                        f"{expected['pts']}@{time_base}"
                    )
                if rgb.shape != (height, width, 3):
                    raise ChronoVideoError(
                        f"decoded frame {decode_index} shape changed to {rgb.shape}"
                    )
                decoded_count += 1
                effective = Fraction(decoded_pts) * time_base
                _write_jsonl_line(
                    observations,
                    {
                        "schema": "ugts-chrono-video-observation-0.1",
                        "decode_index": decode_index,
                        "commit_seq": decode_index + 1,
                        "knowledge_index": decode_index,
                        "effective_pts": decoded_pts,
                        "time_base_num": time_base.numerator,
                        "time_base_den": time_base.denominator,
                        "effective_seconds_num": effective.numerator,
                        "effective_seconds_den": effective.denominator,
                        "duration_ticks": expected["duration_ticks"],
                        "key_frame": expected["key_frame"],
                        "picture_type": expected["picture_type"],
                        "raster_domain": [0, 0, width, height],
                        "covered_pixels": width * height,
                        "canonical_scene_class": "UNKNOWN",
                        "geometry_status": "UNBOUNDED_UNKNOWN",
                        "visibility_status": "UNKNOWN",
                    },
                )
                if decode_index not in selected:
                    continue
                sampled_count += 1
                if first_sample is None:
                    first_sample = rgb.copy()
                if previous_sample is not None:
                    proposal = _motion_proposal(previous_sample, rgb, extents, profile)
                    labels = [tile["proposal"] for tile in proposal["tiles"]]
                    proposal_record = {
                        "schema": "ugts-chrono-video-proposals-0.1",
                        "frame_index": decode_index,
                        "previous_analyzed_frame": max(i for i in selected if i < decode_index),
                        "effective_pts": decoded_pts,
                        "time_base_num": time_base.numerator,
                        "time_base_den": time_base.denominator,
                        **proposal,
                    }
                    _write_jsonl_line(proposals, proposal_record)
                    label_counts = {
                        label: sum(tile["proposal"] == label for tile in proposal["tiles"])
                        for label in (
                            "STATIC_CANDIDATE",
                            "DYNAMIC_CANDIDATE",
                            "AMBIGUOUS_CANDIDATE",
                        )
                    }
                    human_specialization: dict[str, Any] | None = None
                    if profile.target_kind == "human":
                        human_specialization = {
                            "target_kind": "HUMAN",
                            "target_kind_authority": "USER_DECLARED_COMPILER_ARGUMENT",
                            "human_specialization_status": "DECLARED_TARGET_ONLY_NO_ACCEPTED_HCO",
                            "observation_container": "one ordinary Grove chrono_observation_root",
                            "persistent_object": "UNESTABLISHED",
                            "cross_time_identity": "UNKNOWN",
                            "motion_charts": proposal["motion_chart_candidates"],
                            "semantic_joints": "UNKNOWN",
                            "articulated_pose": "UNKNOWN",
                            "body_surface": "UNBOUNDED_UNKNOWN",
                            "hidden_body_completion": False,
                            "learned_identity_or_shape_prior": False,
                            "static_scene_is_still_observed": True,
                        }
                    _write_jsonl_line(
                        hypotheses,
                        {
                            "schema": "ugts-chrono-video-joint-hypothesis-0.1",
                            "frame_index": decode_index,
                            "effective_pts": decoded_pts,
                            "time_base_num": time_base.numerator,
                            "time_base_den": time_base.denominator,
                            "knowledge_index": decode_index,
                            "joint_variables": [
                                "camera_calibration_and_pose",
                                "static_or_dynamic_class",
                                "object_association",
                                "scale_gauge",
                                "scene_object_and_chart_motion",
                                "visibility",
                                "deformation_class",
                                "exposure_timing_interval",
                                "depth_interval",
                            ],
                            "camera_branch": {
                                "alignment": proposal["alignment"],
                                "matrix": proposal["alignment_matrix"],
                                "authority": "PROPOSAL_ONLY",
                            },
                            "calibration_bounds": "UNBOUNDED_UNKNOWN",
                            "depth_interval": [0.0, None],
                            "metric_scale": "UNFIXED",
                            "raster_branch_counts": label_counts,
                            "motion_chart_candidates": proposal["motion_chart_candidates"],
                            "human_specialization": human_specialization,
                            "physical_support_status": "UNBOUNDED_UNKNOWN",
                            "rasterization_status": "DOWNSTREAM_ONLY",
                            "cross_time_faces_or_cells": False,
                            "promotion": False,
                        },
                    )
                    if previous_labels is None:
                        changes = [
                            {"tile_index": index, "before": None, "after": label}
                            for index, label in enumerate(labels)
                        ]
                        event_type = "PROPOSAL_CHECKPOINT"
                        pre_hash = None
                    else:
                        changes = [
                            {
                                "tile_index": index,
                                "before": previous_labels[index],
                                "after": label,
                            }
                            for index, label in enumerate(labels)
                            if label != previous_labels[index]
                        ]
                        event_type = "PROPOSAL_LABEL_NOVELTY"
                        pre_hash = hashlib.sha256(
                            _canonical_json_bytes(previous_labels)
                        ).hexdigest()
                    if changes:
                        _write_jsonl_line(
                            novelty,
                            {
                                "event_type": event_type,
                                "commit_seq": decode_index + 1,
                                "knowledge_index": decode_index,
                                "effective_pts": decoded_pts,
                                "time_base_num": time_base.numerator,
                                "time_base_den": time_base.denominator,
                                "authority": "PROPOSAL_ONLY",
                                "negative_memory_semantics": "NOVELTY_ONLY_NO_IMPLICIT_RETRACTION",
                                "pre_state_sha256": pre_hash,
                                "post_state_sha256": proposal["proposal_state_sha256"],
                                "changes": changes,
                            },
                        )
                    previous_labels = labels
                previous_sample = rgb.copy()
                batch_frames.append(rgb.copy())
                if len(batch_frames) >= profile.batch_size:
                    flush_batch()
            if decoded_count != len(frames):
                raise ChronoVideoError(
                    f"decoder produced {decoded_count} frames; ffprobe reported {len(frames)}"
                )
            flush_batch()
    except Exception:
        if encoder.process.poll() is None:
            encoder.process.kill()
        raise
    encoder.close()
    if first_sample is None or first_gpu_polar is None:
        raise ChronoVideoError("no analyzed frame was materialized")

    preview_probe = probe_video(preview_path)
    _validate_mobile_preview(
        preview_probe,
        expected_width=profile.theta_bins,
        expected_height=profile.rho_bins,
        expected_frames=len(selected_order),
    )
    preview_hash = _sha256_file(preview_path)
    preview_cache_entries = [
        {
            "media_index": item["preview_index"],
            "source_frame_index": item["source_frame_index"],
            "source_pts": item["source_pts"],
            "display_until_source_pts": item["display_until_source_pts"],
        }
        for item in timeline_entries
    ]
    preview_pts_data = generate_video_pts_cache(
        entries=preview_cache_entries,
        source_frame_count=len(frames),
        media_width=profile.theta_bins,
        media_height=profile.rho_bins,
        time_base_num=time_base.numerator,
        time_base_den=time_base.denominator,
        source_sha256=source_hash,
        profile_sha256=profile_hash,
        media_sha256=preview_hash,
        flags=CVPTS_MEDIA_DERIVED_POLAR_PREVIEW | CVPTS_ALREADY_LOG_POLAR,
    )
    preview_pts_path = output / "preview_timeline.ugcvpts1"
    preview_pts_path.write_bytes(preview_pts_data)
    preview_pts_inspection_path = output / "preview_timeline_inspection.json"
    preview_pts_inspection = inspect_video_pts_cache(preview_pts_data)
    _write_json(preview_pts_inspection_path, preview_pts_inspection)
    _write_json(
        preview_timeline_path,
        {
            "schema": "ugts-chrono-video-preview-timeline-0.1",
            "source_sha256": source_hash,
            "profile_sha256": profile_hash,
            "media_path": preview_path.name,
            "media_sha256": preview_hash,
            "media_width": profile.theta_bins,
            "media_height": profile.rho_bins,
            "media_role": "DERIVED_POLAR_PREVIEW",
            "raster_mode": "ALREADY_LOG_POLAR_DO_NOT_APPLY_LUT_AGAIN",
            "playback_mode": "ONCE_HOLD_LAST",
            "time_base_num": time_base.numerator,
            "time_base_den": time_base.denominator,
            "first_source_pts": frames[0]["pts"],
            "end_source_pts_exclusive": source_end_pts,
            "source_duration_ticks": duration_ticks,
            "source_frame_count": len(frames),
            "constant_preview_rate_num": preview_rate.numerator,
            "constant_preview_rate_den": preview_rate.denominator,
            "entries": timeline_entries,
            "authority": "DERIVED_MEDIA_ORDINAL_TO_EXACT_SOURCE_PTS",
            "runtime_cache": preview_pts_path.name,
            "runtime_cache_content_sha256": preview_pts_inspection["content_sha256"],
        },
    )

    source_media_path: Path | None = None
    source_pts_path: Path | None = None
    source_pts_inspection_path: Path | None = None
    if profile.embed_source_for_phone:
        if source_path.suffix.lower() != ".mp4":
            raise ChronoVideoError(
                "--embed-source-for-phone currently requires an MP4 source so the "
                "byte-identical source_media.mp4 asset is honestly labelled"
            )
        if int(probe["stream"].get("has_b_frames", -1)) != 0:
            raise ChronoVideoError(
                "--embed-source-for-phone requires a no-B-frame source because "
                "UGCVPTS1 v1 binds MediaExtractor ordinals to presentation order"
            )
        source_media_path = output / "source_media.mp4"
        shutil.copyfile(source_path, source_media_path)
        if (
            source_media_path.stat().st_size != source_bytes
            or _sha256_file(source_media_path) != source_hash
        ):
            raise ChronoVideoError("embedded source_media.mp4 is not byte-identical")
        source_cache_entries = [
            {
                "media_index": frame_index,
                "source_frame_index": frame_index,
                "source_pts": frame["pts"],
                "display_until_source_pts": (
                    frames[frame_index + 1]["pts"]
                    if frame_index + 1 < len(frames)
                    else source_end_pts
                ),
            }
            for frame_index, frame in enumerate(frames)
        ]
        for entry in source_cache_entries:
            _exact_android_media_time_us(
                entry["source_pts"], time_base.numerator, time_base.denominator
            )
        source_pts_data = generate_video_pts_cache(
            entries=source_cache_entries,
            source_frame_count=len(frames),
            media_width=width,
            media_height=height,
            time_base_num=time_base.numerator,
            time_base_den=time_base.denominator,
            source_sha256=source_hash,
            profile_sha256=profile_hash,
            media_sha256=source_hash,
            flags=CVPTS_MEDIA_ORIGINAL_SOURCE | CVPTS_APPLY_UGCVLUT1_Q8,
        )
        source_pts_path = output / "source_timeline.ugcvpts1"
        source_pts_path.write_bytes(source_pts_data)
        source_pts_inspection_path = output / "source_timeline_inspection.json"
        _write_json(
            source_pts_inspection_path,
            inspect_video_pts_cache(source_pts_data),
        )

    cpu_oracle = remap_rgb_q8_numpy(first_sample, lut_data)
    parity_max_difference = int(abs(cpu_oracle.astype("int16") - first_gpu_polar.astype("int16")).max())
    cpu_sha = hashlib.sha256(cpu_oracle.tobytes(order="C")).hexdigest()
    backend_sha = hashlib.sha256(first_gpu_polar.tobytes(order="C")).hexdigest()
    if parity_max_difference != 0 or cpu_sha != backend_sha:
        raise ChronoVideoError("selected remap backend diverged from the CPU integer oracle")

    source_receipt_path = output / "source_receipt.json"
    _write_json(
        source_receipt_path,
        {
            "schema": "ugts-chrono-video-source-receipt-0.1",
            "source_path": str(source_path),
            "source_file_name": source_path.name,
            "source_bytes": source_bytes,
            "source_sha256": source_hash,
            "video_stream": probe["stream"],
            "frame_count": len(frames),
            "time_base_num": time_base.numerator,
            "time_base_den": time_base.denominator,
            "first_pts": frames[0]["pts"],
            "last_pts": frames[-1]["pts"],
            "end_pts_exclusive": source_end_pts,
            "authoritative_media": True,
            "embedded_media": source_media_path is not None,
            "embedded_path": source_media_path.name if source_media_path else None,
            "embedded_sha256": source_hash if source_media_path else None,
            "embedded_byte_identical": source_media_path is not None,
            "decode_backend": "PyAV CPU decode with exact PTS",
        },
    )
    reconstruction_path = output / "reconstruction_receipt.json"
    cuda_peak = remapper.peak_mib
    _write_json(
        reconstruction_path,
        {
            "schema": "ugts-chrono-video-reconstruction-receipt-0.1",
            "profile": CHRONO_PROFILE,
            "profile_sha256": profile_hash,
            "source_sha256": source_hash,
            "compute": compute_receipt,
            "decode_backend": "pyav-cpu-exact-pts",
            "decode_frame_count": decoded_count,
            "analyzed_frame_count": sampled_count,
            "cuda_peak_allocated_mib": cuda_peak,
            "first_sample_cpu_oracle_sha256": cpu_sha,
            "first_sample_selected_backend_sha256": backend_sha,
            "first_sample_max_byte_difference": parity_max_difference,
            "polar_reconstruction_claim": "NONE",
            "source_roundtrip": (
                "EMBEDDED_BYTE_IDENTICAL_SHA256"
                if source_media_path is not None
                else "BY_REFERENCE_SHA256_ONLY"
            ),
            "runtime_timelines": {
                "preview": preview_pts_inspection,
                "source": (
                    inspect_video_pts_cache(source_pts_path.read_bytes())
                    if source_pts_path is not None
                    else None
                ),
            },
            "physical_camera_calibration": "ABSENT",
            "metric_scale": "ABSENT",
            "accepted_static_geometry": False,
            "accepted_dynamic_geometry": False,
            "accepted_human_geometry": False,
            "target_kind": profile.target_kind,
            "geometry_status": "UNBOUNDED_UNKNOWN",
            "proposal_warning": (
                "Homography-compensated residuals are deterministic motion/static "
                "proposals only; they cannot certify object identity, rigidity, depth, "
                "empty space, occlusion, or literal 3D."
            ),
        },
    )

    profile_path = output / "profile.json"
    profile_receipt = inspect_chrono_profile_receipt(
        {
            "schema": CHRONO_PROFILE_RECEIPT_SCHEMA,
            "canonical_profile": profile.to_dict(),
            "profile_sha256": profile_hash,
            "implementation": _implementation_receipt(compute_backend),
        }
    )
    _write_json(profile_path, profile_receipt)

    asset_paths = [
        profile_path,
        source_receipt_path,
        observation_path,
        proposal_path,
        hypothesis_path,
        novelty_path,
        lut_path,
        output / "polar_lut_inspection.json",
        preview_path,
        preview_timeline_path,
        preview_pts_path,
        preview_pts_inspection_path,
        reconstruction_path,
    ]
    if source_media_path is not None:
        assert source_pts_path is not None and source_pts_inspection_path is not None
        asset_paths.extend(
            [source_media_path, source_pts_path, source_pts_inspection_path]
        )
    asset_receipts = [_asset_receipt(path, output) for path in asset_paths]
    manifest_path = output / "manifest.json"
    manifest = {
        "schema": CHRONO_MANIFEST_SCHEMA,
        "profile": CHRONO_PROFILE,
        "profile_asset": profile_path.name,
        "profile_sha256": profile_hash,
        "target_kind": profile.target_kind,
        "source": {
            "path": str(source_path),
            "sha256": source_hash,
            "bytes": source_bytes,
            "authority": "ORIGINAL_MEDIA",
            "embedded_media": source_media_path is not None,
            "embedded_path": source_media_path.name if source_media_path else None,
            "embedded_byte_identical": source_media_path is not None,
        },
        "chronology": {
            "frame_count": len(frames),
            "time_base_num": time_base.numerator,
            "time_base_den": time_base.denominator,
            "first_pts": frames[0]["pts"],
            "last_pts": frames[-1]["pts"],
            "duration_ticks": duration_ticks,
            "end_pts_exclusive": source_end_pts,
            "duration_seconds_num": duration.numerator,
            "duration_seconds_den": duration.denominator,
            "ordering": "effective_pts_then_decode_index",
            "knowledge_axis": "commit_seq",
        },
        "spatial_observation": {
            "raster_domain": [0, 0, width, height],
            "coverage": coverage,
            "pixel_to_chart": {
                "center": [lut_receipt["center_x"], lut_receipt["center_y"]],
                "radius": "sqrt((u-cx)^2+(v-cy)^2)",
                "theta": "atan2(v-cy,u-cx) mod 2pi",
                "rho": "log(radius/r0)",
                "core": f"radius < {profile.core_radius_pixels}",
            },
            "geometry_status": "UNBOUNDED_UNKNOWN",
            "reason": (
                "The source provides no verified intrinsics, distortion, exposure/rolling "
                "shutter bounds, camera poses, or metric scale."
            ),
        },
        "authority": {
            "source_media": "AUTHORITATIVE_BYTES",
            "observations": "AUTHORITATIVE_DECODE_AND_PTS_RECEIPTS",
            "polar_lut": "DETERMINISTIC_DERIVED_GPU_CACHE",
            "polar_preview": "DERIVED_RASTER_PREVIEW",
            "preview_timeline": "DERIVED_MEDIA_ORDINAL_TO_EXACT_SOURCE_PTS",
            "embedded_source_media": (
                "AUTHORITATIVE_BYTE_IDENTICAL_COPY"
                if source_media_path is not None
                else "ABSENT"
            ),
            "motion_static_tiles": "PROPOSAL_ONLY",
            "joint_hypotheses": "PROPOSAL_ONLY_OR_UNBOUNDED_UNKNOWN",
            "scene_3d": "UNBOUNDED_UNKNOWN",
            "negative_memory": "NOVELTY_ONLY_NO_IMPLICIT_RETRACTION",
        },
        "desktop_profile": {
            "role": "authoritative compiler and proposal tier",
            "compute_backend": compute_backend,
            "decode_backend": "pyav-cpu-exact-pts",
            "workspace_limit_mib": profile.max_vram_mib,
            "cuda_peak_allocated_mib": cuda_peak,
        },
        "phone_profile": {
            "target": "POCO X7 Pro / Mali-G720 / ARM64 / GLES 3.0",
            "role": "compact evidence viewer and downstream rasterizer",
            "target_fps": 60,
            "source_time_authority": "exact PTS, never display frame count",
            "playback_mode": "ONCE_HOLD_LAST",
            "preview_media": preview_path.name,
            "preview_timeline": preview_pts_path.name,
            "preview_raster_mode": "ALREADY_LOG_POLAR_DO_NOT_APPLY_LUT_AGAIN",
            "source_media_mode": (
                "EMBEDDED_BYTE_IDENTICAL"
                if source_media_path is not None
                else "EXTERNAL_BY_PATH_AND_SHA256"
            ),
            "source_media": source_media_path.name if source_media_path else None,
            "source_timeline": source_pts_path.name if source_pts_path else None,
            "source_raster_mode": (
                "APPLY_UGCVLUT1_Q8"
                if source_media_path is not None
                else "UNAVAILABLE"
            ),
            "compile_on_phone": False,
            "physical_device_verification": "EXTERNAL_PHYSICAL_RECEIPT_REQUIRED",
        },
        "assets": asset_receipts,
    }
    _write_json(manifest_path, manifest)
    manifest_hash = _sha256_file(manifest_path)
    project_path = _write_inspector_project(
        output,
        manifest_hash,
        source_hash,
        asset_receipts + [_asset_receipt(manifest_path, output)],
        float(duration),
        profile.target_kind,
    )
    readme_path = output / "README.md"
    source_storage_note = (
        "A byte-identical `source_media.mp4` copy is embedded and hash-bound for "
        "on-phone source decode; it remains the original-media authority."
        if source_media_path is not None
        else "The original MP4 remains authoritative by external path and SHA-256."
    )
    readme_path.write_text(
        "# Chrono Video Observation Inspector\n\n"
        "This directory is a deterministic UGTOMS observation/proposal fixture. "
        f"Open `project.json` in UGTS Studio. {source_storage_note} "
        "`profile.json` contains the canonical hash preimage and exact selected "
        "implementation versions. "
        "`polar_preview.mp4` is an already-log-polar downstream diagnostic and must "
        "not be passed through `UGCVLUT1` again. Playback is finite and holds the "
        "last frame; it does not infer a chronology loop.\n\n"
        "```powershell\n"
        "python -m ugts_kc3 validate-3d project.json\n"
        "python -m ugts_kc3 build-android project.json android --profile poco_x7_pro_12gb --debug-assets\n"
        "```\n\n"
        "No accepted physical 3D is present because the source has no verified camera "
        "calibration, timing bounds, pose, or metric scale.\n",
        encoding="utf-8",
    )
    elapsed = time.perf_counter() - started
    return ChronoCompileResult(
        output,
        manifest_path,
        project_path,
        preview_path,
        source_hash,
        manifest_hash,
        decoded_count,
        sampled_count,
        compute_backend,
        "pyav-cpu-exact-pts",
        elapsed,
        cuda_peak,
    )


def verify_chrono_bundle(
    bundle_dir: str | Path, verify_source_bytes: bool = True
) -> dict[str, Any]:
    """Fail closed over a compiled bundle and return a machine-readable receipt."""
    root = Path(bundle_dir).resolve()
    manifest_path = root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ChronoVideoError(f"cannot read manifest: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ChronoVideoError("manifest root must be an object")
    if manifest.get("schema") != CHRONO_MANIFEST_SCHEMA:
        raise ChronoVideoError("manifest schema mismatch")
    if manifest.get("profile") != CHRONO_PROFILE:
        raise ChronoVideoError("manifest profile mismatch")
    assets = manifest.get("assets")
    if not isinstance(assets, list) or not assets:
        raise ChronoVideoError("manifest assets must be a nonempty list")
    seen: set[str] = set()
    verified_assets: list[dict[str, Any]] = []
    for index, item in enumerate(assets):
        if not isinstance(item, dict):
            raise ChronoVideoError(f"asset {index} must be an object")
        relative_text = str(item.get("path", ""))
        relative = Path(relative_text)
        if not relative_text or relative.is_absolute() or ".." in relative.parts:
            raise ChronoVideoError(f"asset {index} path is unsafe")
        if relative_text in seen:
            raise ChronoVideoError(f"duplicate asset path: {relative_text}")
        seen.add(relative_text)
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ChronoVideoError(f"asset is missing or escapes bundle: {relative_text}")
        expected_bytes = int(item.get("bytes", -1))
        expected_hash = str(item.get("sha256", ""))
        _digest_bytes(expected_hash, f"asset {index} sha256")
        actual_hash = _sha256_file(path)
        if path.stat().st_size != expected_bytes:
            raise ChronoVideoError(f"asset byte count mismatch: {relative_text}")
        if actual_hash != expected_hash:
            raise ChronoVideoError(f"asset SHA-256 mismatch: {relative_text}")
        verified_assets.append(
            {"path": relative_text, "bytes": expected_bytes, "sha256": actual_hash}
        )
    required = {
        "profile.json",
        "source_receipt.json",
        "observations.jsonl",
        "proposals.jsonl",
        "joint_hypotheses.jsonl",
        "novelty.jsonl",
        "polar_lut.ugcv1",
        "polar_lut_inspection.json",
        "polar_preview.mp4",
        "preview_timeline.json",
        "preview_timeline.ugcvpts1",
        "preview_timeline_inspection.json",
        "reconstruction_receipt.json",
    }
    if manifest.get("profile_asset") != "profile.json":
        raise ChronoVideoError("manifest profile_asset must be profile.json")
    try:
        raw_profile_receipt = json.loads(
            (root / "profile.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ChronoVideoError(f"cannot read profile receipt: {exc}") from exc
    profile_receipt = inspect_chrono_profile_receipt(raw_profile_receipt)
    profile_hash = str(manifest.get("profile_sha256", ""))
    _digest_bytes(profile_hash, "manifest profile_sha256")
    if profile_receipt["profile_sha256"] != profile_hash:
        raise ChronoVideoError("manifest/profile receipt SHA-256 mismatch")
    canonical_profile = profile_receipt["canonical_profile"]
    if manifest.get("target_kind") != canonical_profile["target_kind"]:
        raise ChronoVideoError("manifest target kind disagrees with canonical profile")
    source_manifest = manifest.get("source")
    if not isinstance(source_manifest, dict):
        raise ChronoVideoError("manifest source must be an object")
    source_hash = str(source_manifest.get("sha256", ""))
    _digest_bytes(source_hash, "manifest source sha256")
    embedded = source_manifest.get("embedded_media") is True
    if embedded != canonical_profile["embed_source_for_phone"]:
        raise ChronoVideoError(
            "manifest embedded-source state disagrees with canonical profile"
        )
    if embedded:
        required.update(
            {
                "source_media.mp4",
                "source_timeline.ugcvpts1",
                "source_timeline_inspection.json",
            }
        )
        if (
            source_manifest.get("embedded_path") != "source_media.mp4"
            or source_manifest.get("embedded_byte_identical") is not True
        ):
            raise ChronoVideoError("manifest embedded-source declaration is inconsistent")
    elif (
        source_manifest.get("embedded_path") is not None
        or source_manifest.get("embedded_byte_identical") is not False
    ):
        raise ChronoVideoError("manifest claims partial embedded-source state")
    missing = sorted(required - seen)
    if missing:
        raise ChronoVideoError(f"manifest omits required assets: {', '.join(missing)}")
    lut_report = inspect_video_polar_lut((root / "polar_lut.ugcv1").read_bytes())
    chronology = manifest.get("chronology")
    if not isinstance(chronology, dict):
        raise ChronoVideoError("manifest chronology must be an object")
    try:
        expected_frames = int(chronology["frame_count"])
        time_base_num = int(chronology["time_base_num"])
        time_base_den = int(chronology["time_base_den"])
        chronology_first_pts = int(chronology["first_pts"])
        chronology_last_pts = int(chronology["last_pts"])
        duration_ticks = int(chronology["duration_ticks"])
        end_pts_exclusive = int(chronology["end_pts_exclusive"])
        raster_domain = manifest["spatial_observation"]["raster_domain"]
        expected_width, expected_height = map(int, raster_domain[2:4])
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise ChronoVideoError("manifest chronology/raster domain is malformed") from exc
    if (
        expected_frames < 1
        or time_base_num < 1
        or time_base_den < 1
        or duration_ticks < 1
        or end_pts_exclusive != chronology_first_pts + duration_ticks
        or end_pts_exclusive <= chronology_last_pts
    ):
        raise ChronoVideoError("manifest chronology is internally inconsistent")
    if (
        lut_report["source_width"] != expected_width
        or lut_report["source_height"] != expected_height
    ):
        raise ChronoVideoError("CVLUT1/source raster dimensions disagree")
    expected_lut_profile = {
        "theta_bins": canonical_profile["theta_bins"],
        "rho_bins": canonical_profile["rho_bins"],
        "r0_pixels": canonical_profile["r0_pixels"],
        "core_radius_pixels": canonical_profile["core_radius_pixels"],
    }
    for field, expected_value in expected_lut_profile.items():
        if lut_report.get(field) != expected_value:
            raise ChronoVideoError(f"CVLUT1/canonical profile field disagrees: {field}")
    spatial_observation = manifest.get("spatial_observation")
    if not isinstance(spatial_observation, dict):
        raise ChronoVideoError("manifest spatial_observation must be an object")
    expected_coverage = verify_tile_partition(
        expected_width, expected_height, canonical_profile["tile_size"]
    )
    if spatial_observation.get("coverage") != expected_coverage:
        raise ChronoVideoError("manifest coverage disagrees with canonical profile")
    desktop_profile = manifest.get("desktop_profile")
    if not isinstance(desktop_profile, dict):
        raise ChronoVideoError("manifest desktop_profile must be an object")
    selected_implementation = profile_receipt["implementation"]["selected"]
    expected_desktop_fields = {
        "compute_backend": selected_implementation["compute_backend"],
        "decode_backend": selected_implementation["decode_backend"],
        "workspace_limit_mib": canonical_profile["max_vram_mib"],
    }
    for field, expected_value in expected_desktop_fields.items():
        if desktop_profile.get(field) != expected_value:
            raise ChronoVideoError(
                f"desktop implementation/canonical profile field disagrees: {field}"
            )
    try:
        source_receipt = json.loads(
            (root / "source_receipt.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ChronoVideoError(f"cannot read source receipt: {exc}") from exc
    if not isinstance(source_receipt, dict):
        raise ChronoVideoError("source receipt must be an object")
    expected_source_receipt = {
        "source_sha256": source_hash,
        "source_bytes": int(source_manifest.get("bytes", -1)),
        "frame_count": expected_frames,
        "time_base_num": time_base_num,
        "time_base_den": time_base_den,
        "first_pts": chronology_first_pts,
        "last_pts": chronology_last_pts,
        "end_pts_exclusive": end_pts_exclusive,
        "embedded_media": embedded,
        "embedded_path": "source_media.mp4" if embedded else None,
        "embedded_sha256": source_hash if embedded else None,
        "embedded_byte_identical": embedded,
    }
    for field, expected_value in expected_source_receipt.items():
        if source_receipt.get(field) != expected_value:
            raise ChronoVideoError(f"source receipt field disagrees: {field}")
    observation_count = 0
    previous_pts: int | None = None
    first_pts: int | None = None
    last_pts: int | None = None
    observation_pts: list[int] = []
    with (root / "observations.jsonl").open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ChronoVideoError(
                    f"observations.jsonl line {line_number} is invalid JSON"
                ) from exc
            try:
                pts = int(record["effective_pts"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ChronoVideoError(
                    f"observation line {line_number} has malformed PTS"
                ) from exc
            if previous_pts is not None and pts <= previous_pts:
                raise ChronoVideoError("observation PTS order is not strictly increasing")
            if int(record.get("decode_index", -1)) != observation_count:
                raise ChronoVideoError("observation decode indices are not dense")
            if (
                int(record.get("time_base_num", -1)) != time_base_num
                or int(record.get("time_base_den", -1)) != time_base_den
            ):
                raise ChronoVideoError("observation/manifest time bases disagree")
            if record.get("canonical_scene_class") != "UNKNOWN":
                raise ChronoVideoError("an observation promoted scene class without a gate")
            if record.get("geometry_status") != "UNBOUNDED_UNKNOWN":
                raise ChronoVideoError("an observation promoted unbounded geometry")
            if int(record.get("covered_pixels", -1)) != expected_width * expected_height:
                raise ChronoVideoError("an observation does not cover the full source raster")
            first_pts = pts if first_pts is None else first_pts
            last_pts = pts
            previous_pts = pts
            observation_pts.append(pts)
            observation_count += 1
    if observation_count != expected_frames:
        raise ChronoVideoError(
            f"observation count mismatch: expected {expected_frames}, got {observation_count}"
        )
    if first_pts != chronology_first_pts or last_pts != chronology_last_pts:
        raise ChronoVideoError("manifest/observation PTS endpoints disagree")

    try:
        preview_timeline = json.loads(
            (root / "preview_timeline.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ChronoVideoError(f"cannot read preview timeline: {exc}") from exc
    if not isinstance(preview_timeline, dict):
        raise ChronoVideoError("preview timeline must be an object")
    preview_hash = _sha256_file(root / "polar_preview.mp4")
    expected_preview_fields = {
        "schema": "ugts-chrono-video-preview-timeline-0.1",
        "source_sha256": source_hash,
        "profile_sha256": profile_hash,
        "media_path": "polar_preview.mp4",
        "media_sha256": preview_hash,
        "media_width": lut_report["theta_bins"],
        "media_height": lut_report["rho_bins"],
        "media_role": "DERIVED_POLAR_PREVIEW",
        "raster_mode": "ALREADY_LOG_POLAR_DO_NOT_APPLY_LUT_AGAIN",
        "playback_mode": "ONCE_HOLD_LAST",
        "time_base_num": time_base_num,
        "time_base_den": time_base_den,
        "first_source_pts": chronology_first_pts,
        "end_source_pts_exclusive": end_pts_exclusive,
        "source_duration_ticks": duration_ticks,
        "source_frame_count": expected_frames,
        "authority": "DERIVED_MEDIA_ORDINAL_TO_EXACT_SOURCE_PTS",
        "runtime_cache": "preview_timeline.ugcvpts1",
    }
    for field, expected_value in expected_preview_fields.items():
        if preview_timeline.get(field) != expected_value:
            raise ChronoVideoError(f"preview timeline field disagrees: {field}")
    raw_preview_entries = preview_timeline.get("entries")
    if not isinstance(raw_preview_entries, list):
        raise ChronoVideoError("preview timeline entries must be an array")
    preview_entries: list[dict[str, int]] = []
    for preview_index, raw_entry in enumerate(raw_preview_entries):
        if not isinstance(raw_entry, dict):
            raise ChronoVideoError("preview timeline entry must be an object")
        try:
            if int(raw_entry["preview_index"]) != preview_index:
                raise ChronoVideoError("preview indices must be dense from zero")
            preview_entries.append(
                {
                    "media_index": preview_index,
                    "source_frame_index": int(raw_entry["source_frame_index"]),
                    "source_pts": int(raw_entry["source_pts"]),
                    "display_until_source_pts": int(
                        raw_entry["display_until_source_pts"]
                    ),
                }
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ChronoVideoError("preview timeline entry is malformed") from exc
    normalized_preview_entries = _validate_pts_entries(
        preview_entries, expected_frames
    )
    expected_selected_indices = sorted(
        _selected_indices(expected_frames, canonical_profile["sample_stride"])
    )
    if [item["source_frame_index"] for item in normalized_preview_entries] != (
        expected_selected_indices
    ):
        raise ChronoVideoError(
            "preview sampling stride disagrees with canonical profile"
        )
    for item in normalized_preview_entries:
        if observation_pts[item["source_frame_index"]] != item["source_pts"]:
            raise ChronoVideoError("preview timeline PTS does not bind its source frame")
    if (
        normalized_preview_entries[0]["source_pts"] != chronology_first_pts
        or normalized_preview_entries[-1]["display_until_source_pts"]
        != end_pts_exclusive
    ):
        raise ChronoVideoError("preview timeline interval endpoints disagree")
    expected_preview_rate = Fraction(len(normalized_preview_entries), duration_ticks)
    try:
        declared_preview_rate = Fraction(
            int(preview_timeline.get("constant_preview_rate_num", 0)),
            int(preview_timeline.get("constant_preview_rate_den", 0)),
        )
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        raise ChronoVideoError("preview constant frame rate is malformed") from exc
    # The encoder rate is frames / source duration in seconds, not frames / ticks.
    expected_preview_rate /= Fraction(time_base_num, time_base_den)
    if declared_preview_rate != expected_preview_rate:
        raise ChronoVideoError("preview constant frame rate disagrees with source duration")

    preview_pts_report, cached_preview_entries = _decode_video_pts_cache(
        (root / "preview_timeline.ugcvpts1").read_bytes()
    )
    if preview_pts_report["flags"] != (
        CVPTS_MEDIA_DERIVED_POLAR_PREVIEW | CVPTS_ALREADY_LOG_POLAR
    ):
        raise ChronoVideoError("preview UGCVPTS1 flags are not finite already-polar mode")
    expected_preview_cache_fields = {
        "entry_count": len(normalized_preview_entries),
        "media_width": lut_report["theta_bins"],
        "media_height": lut_report["rho_bins"],
        "source_frame_count": expected_frames,
        "first_source_pts": chronology_first_pts,
        "end_source_pts_exclusive": end_pts_exclusive,
        "time_base_num": time_base_num,
        "time_base_den": time_base_den,
        "source_sha256": source_hash,
        "profile_sha256": profile_hash,
        "media_sha256": preview_hash,
        "playback_mode": "ONCE_HOLD_LAST",
    }
    for field, expected_value in expected_preview_cache_fields.items():
        if preview_pts_report.get(field) != expected_value:
            raise ChronoVideoError(f"preview UGCVPTS1 field disagrees: {field}")
    if cached_preview_entries != normalized_preview_entries:
        raise ChronoVideoError("preview JSON and UGCVPTS1 entries disagree")
    if (
        preview_timeline.get("runtime_cache_content_sha256")
        != preview_pts_report["content_sha256"]
    ):
        raise ChronoVideoError("preview timeline/cache content hashes disagree")
    try:
        preview_inspection = json.loads(
            (root / "preview_timeline_inspection.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ChronoVideoError(f"cannot read preview timeline inspection: {exc}") from exc
    if preview_inspection != preview_pts_report:
        raise ChronoVideoError("stored preview timeline inspection disagrees")
    preview_probe = probe_video(root / "polar_preview.mp4")
    _validate_mobile_preview(
        preview_probe,
        expected_width=lut_report["theta_bins"],
        expected_height=lut_report["rho_bins"],
        expected_frames=len(normalized_preview_entries),
    )

    source_pts_report: dict[str, Any] | None = None
    if embedded:
        embedded_path = root / "source_media.mp4"
        if (
            embedded_path.stat().st_size != int(source_manifest["bytes"])
            or _sha256_file(embedded_path) != source_hash
        ):
            raise ChronoVideoError("embedded source_media.mp4 is not byte-identical")
        embedded_probe = probe_video(embedded_path)
        if int(embedded_probe["stream"].get("has_b_frames", -1)) != 0:
            raise ChronoVideoError(
                "embedded Android source contains B-frames unsupported by UGCVPTS1 v1"
            )
        if (
            embedded_probe["width"] != expected_width
            or embedded_probe["height"] != expected_height
            or len(embedded_probe["frames"]) != expected_frames
            or embedded_probe["time_base_num"] != time_base_num
            or embedded_probe["time_base_den"] != time_base_den
            or [frame["pts"] for frame in embedded_probe["frames"]]
            != observation_pts
        ):
            raise ChronoVideoError(
                "embedded Android source stream disagrees with the exact observation ledger"
            )
        source_pts_report, cached_source_entries = _decode_video_pts_cache(
            (root / "source_timeline.ugcvpts1").read_bytes()
        )
        expected_source_entries = [
            {
                "media_index": frame_index,
                "source_frame_index": frame_index,
                "source_pts": pts,
                "display_until_source_pts": (
                    observation_pts[frame_index + 1]
                    if frame_index + 1 < expected_frames
                    else end_pts_exclusive
                ),
                "flags": 0,
            }
            for frame_index, pts in enumerate(observation_pts)
        ]
        if source_pts_report["flags"] != (
            CVPTS_MEDIA_ORIGINAL_SOURCE | CVPTS_APPLY_UGCVLUT1_Q8
        ):
            raise ChronoVideoError("source UGCVPTS1 flags are not finite live-LUT mode")
        expected_source_cache_fields = {
            "entry_count": expected_frames,
            "media_width": expected_width,
            "media_height": expected_height,
            "source_frame_count": expected_frames,
            "first_source_pts": chronology_first_pts,
            "end_source_pts_exclusive": end_pts_exclusive,
            "time_base_num": time_base_num,
            "time_base_den": time_base_den,
            "source_sha256": source_hash,
            "profile_sha256": profile_hash,
            "media_sha256": source_hash,
            "playback_mode": "ONCE_HOLD_LAST",
        }
        for field, expected_value in expected_source_cache_fields.items():
            if source_pts_report.get(field) != expected_value:
                raise ChronoVideoError(f"source UGCVPTS1 field disagrees: {field}")
        if cached_source_entries != expected_source_entries:
            raise ChronoVideoError("source UGCVPTS1 does not cover every exact source PTS")
        for entry in cached_source_entries:
            _exact_android_media_time_us(
                entry["source_pts"], time_base_num, time_base_den
            )
        try:
            source_inspection = json.loads(
                (root / "source_timeline_inspection.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise ChronoVideoError(f"cannot read source timeline inspection: {exc}") from exc
        if source_inspection != source_pts_report:
            raise ChronoVideoError("stored source timeline inspection disagrees")
    elif {
        "source_media.mp4",
        "source_timeline.ugcvpts1",
        "source_timeline_inspection.json",
    } & seen:
        raise ChronoVideoError("unembedded manifest lists source runtime assets")

    phone_profile = manifest.get("phone_profile")
    if not isinstance(phone_profile, dict):
        raise ChronoVideoError("manifest phone_profile must be an object")
    expected_phone_fields = {
        "playback_mode": "ONCE_HOLD_LAST",
        "preview_media": "polar_preview.mp4",
        "preview_timeline": "preview_timeline.ugcvpts1",
        "preview_raster_mode": "ALREADY_LOG_POLAR_DO_NOT_APPLY_LUT_AGAIN",
        "source_media_mode": (
            "EMBEDDED_BYTE_IDENTICAL" if embedded else "EXTERNAL_BY_PATH_AND_SHA256"
        ),
        "source_media": "source_media.mp4" if embedded else None,
        "source_timeline": "source_timeline.ugcvpts1" if embedded else None,
        "source_raster_mode": "APPLY_UGCVLUT1_Q8" if embedded else "UNAVAILABLE",
    }
    for field, expected_value in expected_phone_fields.items():
        if phone_profile.get(field) != expected_value:
            raise ChronoVideoError(f"phone profile field disagrees: {field}")

    proposal_count = 0
    with (root / "proposals.jsonl").open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            record = json.loads(line)
            if record.get("authority") != "PROPOSAL_ONLY":
                raise ChronoVideoError(f"proposal line {line_number} has wrong authority")
            if record.get("geometry_commit") or record.get("static_commit"):
                raise ChronoVideoError(f"proposal line {line_number} asserts a commit")
            for tile in record.get("tiles", []):
                if tile.get("canonical_state") != "UNKNOWN":
                    raise ChronoVideoError("proposal tile changed canonical UNKNOWN state")
            proposal_count += 1
    hypothesis_count = 0
    with (root / "joint_hypotheses.jsonl").open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            record = json.loads(line)
            if record.get("physical_support_status") != "UNBOUNDED_UNKNOWN":
                raise ChronoVideoError(
                    f"joint hypothesis line {line_number} promoted physical support"
                )
            if record.get("promotion") or record.get("cross_time_faces_or_cells"):
                raise ChronoVideoError(
                    f"joint hypothesis line {line_number} violates promotion/time guards"
                )
            hypothesis_count += 1
    if hypothesis_count != proposal_count:
        raise ChronoVideoError("proposal and joint-hypothesis counts disagree")
    novelty_count = 0
    with (root / "novelty.jsonl").open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            record = json.loads(line)
            if line_number > 1 and record.get("negative_memory_semantics") != (
                "NOVELTY_ONLY_NO_IMPLICIT_RETRACTION"
            ):
                raise ChronoVideoError("novelty event lacks negative-memory semantics")
            novelty_count += 1
    reconstruction = json.loads(
        (root / "reconstruction_receipt.json").read_text(encoding="utf-8")
    )
    if reconstruction.get("first_sample_max_byte_difference") != 0:
        raise ChronoVideoError("CPU/selected-backend remap parity is not exact")
    if reconstruction.get("geometry_status") != "UNBOUNDED_UNKNOWN":
        raise ChronoVideoError("reconstruction receipt overclaims geometry")
    if reconstruction.get("profile_sha256") != profile_hash:
        raise ChronoVideoError("reconstruction/profile hashes disagree")
    runtime_timelines = reconstruction.get("runtime_timelines")
    if not isinstance(runtime_timelines, dict):
        raise ChronoVideoError("reconstruction runtime timeline receipt is missing")
    if runtime_timelines.get("preview") != preview_pts_report:
        raise ChronoVideoError("reconstruction preview timeline receipt disagrees")
    if runtime_timelines.get("source") != source_pts_report:
        raise ChronoVideoError("reconstruction source timeline receipt disagrees")
    project = json.loads((root / "project.json").read_text(encoding="utf-8"))
    binding = project.get("metadata", {}).get("chrono_scene_observation", {})
    manifest_hash = _sha256_file(manifest_path)
    if binding.get("manifest_sha256") != manifest_hash:
        raise ChronoVideoError("editable project manifest binding hash mismatch")
    if binding.get("source_sha256") != source_hash:
        raise ChronoVideoError("editable project source binding hash mismatch")
    runtime_assets = binding.get("runtime_assets")
    if not isinstance(runtime_assets, list):
        raise ChronoVideoError("editable project runtime asset ledger is missing")
    project_asset_map = {
        str(item.get("path")): (item.get("bytes"), item.get("sha256"))
        for item in runtime_assets
        if isinstance(item, dict)
    }
    for item in verified_assets:
        if project_asset_map.get(item["path"]) != (item["bytes"], item["sha256"]):
            raise ChronoVideoError(
                f"editable project runtime asset binding disagrees: {item['path']}"
            )
    source_verified: bool | None = None
    source_path = Path(str(source_manifest["path"]))
    if verify_source_bytes:
        if not source_path.is_file():
            raise ChronoVideoError(f"authoritative source is unavailable: {source_path}")
        if source_path.stat().st_size != int(source_manifest["bytes"]):
            raise ChronoVideoError("authoritative source byte count mismatch")
        if _sha256_file(source_path) != source_hash:
            raise ChronoVideoError("authoritative source SHA-256 mismatch")
        source_verified = True
    return {
        "schema": "ugts-chrono-video-bundle-verification-0.1",
        "passed": True,
        "bundle": str(root),
        "manifest_sha256": manifest_hash,
        "profile_sha256": profile_hash,
        "profile_receipt": profile_receipt,
        "source_sha256": source_hash,
        "source_bytes_verified": source_verified,
        "asset_count": len(verified_assets),
        "asset_bytes": sum(item["bytes"] for item in verified_assets),
        "observation_count": observation_count,
        "proposal_count": proposal_count,
        "joint_hypothesis_count": hypothesis_count,
        "novelty_event_count": novelty_count,
        "cvlut": lut_report,
        "preview_pts_cache": preview_pts_report,
        "source_pts_cache": source_pts_report,
        "embedded_source_verified": embedded,
        "geometry_status": "UNBOUNDED_UNKNOWN",
        "cpu_backend_max_byte_difference": 0,
    }


__all__ = [
    "CHRONO_MANIFEST_SCHEMA",
    "CHRONO_PROFILE",
    "CVLUT_MAGIC",
    "CVPTS_MAGIC",
    "CVPTS_MEDIA_ORIGINAL_SOURCE",
    "CVPTS_MEDIA_DERIVED_POLAR_PREVIEW",
    "CVPTS_APPLY_UGCVLUT1_Q8",
    "CVPTS_ALREADY_LOG_POLAR",
    "CVPTS_LOOP",
    "ChronoCompileResult",
    "ChronoVideoError",
    "ChronoVideoProfile",
    "compile_chrono_video",
    "generate_video_polar_lut",
    "generate_video_pts_cache",
    "inspect_video_polar_lut",
    "inspect_video_pts_cache",
    "probe_video",
    "remap_rgb_q8_numpy",
    "verify_chrono_bundle",
    "verify_tile_partition",
]
