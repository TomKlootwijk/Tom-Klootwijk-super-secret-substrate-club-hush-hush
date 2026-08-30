"""Desktop Grove runtime for authoritative chrono-video observation bundles.

This module deliberately shares the compiled ``UGCVPTS1`` and ``UGCVLUT1``
contracts with the Android runtime.  It does not infer geometry, fill hidden
surfaces, or promote proposal data.  The desktop path decodes the embedded,
byte-identical source media, validates every decoded PTS, and applies the same
Q8 integer bilinear operator used by the compiler and specified for GLES.

The returned polar raster is exact.  Its eventual presentation by Qt and the
desktop compositor is downstream display work and is therefore reported as
unverified physical timing rather than silently conflated with PTS selection.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from fractions import Fraction
import hashlib
from pathlib import Path
import time
from typing import Any, Iterator, Mapping

from .chrono_video import (
    CVPTS_APPLY_UGCVLUT1_Q8,
    CVPTS_LOOP,
    CVPTS_MEDIA_ORIGINAL_SOURCE,
    ChronoVideoError,
    _decode_video_pts_cache,
    _iter_pyav_frames,
    _select_remapper,
    remap_rgb_q8_numpy,
    verify_chrono_bundle,
)


@dataclass(frozen=True)
class ChronoDesktopTimelineEntry:
    """One exact, half-open source-clock presentation interval."""

    media_index: int
    source_frame_index: int
    source_pts: int
    display_until_source_pts: int


@dataclass(frozen=True)
class ChronoDesktopTimeline:
    """Validated desktop view of the platform-neutral ``UGCVPTS1`` ledger."""

    flags: int
    media_width: int
    media_height: int
    source_frame_count: int
    first_source_pts: int
    end_source_pts_exclusive: int
    time_base_num: int
    time_base_den: int
    source_sha256: str
    profile_sha256: str
    media_sha256: str
    content_sha256: str
    entries: tuple[ChronoDesktopTimelineEntry, ...]

    @property
    def loops(self) -> bool:
        return bool(self.flags & CVPTS_LOOP)

    @property
    def duration_ticks(self) -> int:
        return self.end_source_pts_exclusive - self.first_source_pts

    def source_offset_for_elapsed_nanoseconds(self, elapsed_nanoseconds: int) -> int:
        """Mirror native signed-128 integer clock conversion without floats."""

        if type(elapsed_nanoseconds) is not int or elapsed_nanoseconds < 0:
            raise ValueError("elapsed_nanoseconds must be a nonnegative integer")
        offset = (
            elapsed_nanoseconds * self.time_base_den
        ) // (1_000_000_000 * self.time_base_num)
        if self.loops:
            return offset % self.duration_ticks
        return min(offset, self.duration_ticks)

    def completed_cycles_for_elapsed_nanoseconds(self, elapsed_nanoseconds: int) -> int:
        if not self.loops:
            return 0
        if type(elapsed_nanoseconds) is not int or elapsed_nanoseconds < 0:
            raise ValueError("elapsed_nanoseconds must be a nonnegative integer")
        offset = (
            elapsed_nanoseconds * self.time_base_den
        ) // (1_000_000_000 * self.time_base_num)
        return offset // self.duration_ticks

    def select_for_elapsed_nanoseconds(self, elapsed_nanoseconds: int) -> int:
        """Select exactly as Android: integer clock and half-open intervals."""

        offset = self.source_offset_for_elapsed_nanoseconds(elapsed_nanoseconds)
        if not self.loops and offset >= self.duration_ticks:
            return len(self.entries) - 1
        target = self.first_source_pts + offset
        ends = tuple(entry.display_until_source_pts for entry in self.entries)
        return min(bisect_right(ends, target), len(self.entries) - 1)


def decode_chrono_desktop_timeline(data: bytes) -> ChronoDesktopTimeline:
    """Validate and expose a source-role ``UGCVPTS1`` cache for desktop play."""

    report, raw_entries = _decode_video_pts_cache(data)
    expected_flags = CVPTS_MEDIA_ORIGINAL_SOURCE | CVPTS_APPLY_UGCVLUT1_Q8
    if report["flags"] & ~CVPTS_LOOP != expected_flags:
        raise ChronoVideoError(
            "desktop authoritative playback requires an ORIGINAL_SOURCE/APPLY_UGCVLUT1_Q8 timeline"
        )
    entries = tuple(
        ChronoDesktopTimelineEntry(
            media_index=int(entry["media_index"]),
            source_frame_index=int(entry["source_frame_index"]),
            source_pts=int(entry["source_pts"]),
            display_until_source_pts=int(entry["display_until_source_pts"]),
        )
        for entry in raw_entries
    )
    return ChronoDesktopTimeline(
        flags=int(report["flags"]),
        media_width=int(report["media_width"]),
        media_height=int(report["media_height"]),
        source_frame_count=int(report["source_frame_count"]),
        first_source_pts=int(report["first_source_pts"]),
        end_source_pts_exclusive=int(report["end_source_pts_exclusive"]),
        time_base_num=int(report["time_base_num"]),
        time_base_den=int(report["time_base_den"]),
        source_sha256=str(report["source_sha256"]),
        profile_sha256=str(report["profile_sha256"]),
        media_sha256=str(report["media_sha256"]),
        content_sha256=str(report["content_sha256"]),
        entries=entries,
    )


def load_chrono_desktop_timeline(path: str | Path) -> ChronoDesktopTimeline:
    return decode_chrono_desktop_timeline(Path(path).read_bytes())


@dataclass(frozen=True)
class ChronoDesktopFrame:
    """One exact pre-presentation polar raster and its authority receipt."""

    ordinal: int
    source_frame_index: int
    source_pts: int
    display_until_source_pts: int
    rgb: Any
    rgb_sha256: str
    backend: str
    logical_pts_exact: bool
    physical_display_timing_verified: bool
    late_boundary: bool


class ChronoDesktopPlayer:
    """Two-slot, source-authoritative desktop player for a compiled bundle.

    Decoding and remapping are synchronous so the editor remains a simple
    bounded reference runtime.  Ordinal zero and one are primed before the
    steady clock starts; subsequent ordinals are explicitly prefetched after
    the selected raster has been published.  If a prefetch misses, the player
    returns the correct target only after decoding it and records a late
    boundary.  It never labels such a frame as physically on-time.
    """

    def __init__(
        self,
        bundle_dir: str | Path,
        *,
        backend: str = "auto",
        max_vram_mib: int = 1536,
        verify: bool = True,
        verify_every_frame: bool = False,
    ) -> None:
        if type(max_vram_mib) is not int or max_vram_mib < 1:
            raise ValueError("max_vram_mib must be a positive integer")
        if type(verify_every_frame) is not bool:
            raise ValueError("verify_every_frame must be boolean")
        self.bundle_dir = Path(bundle_dir).resolve()
        self.source_path = self.bundle_dir / "source_media.mp4"
        self.timeline_path = self.bundle_dir / "source_timeline.ugcvpts1"
        self.lut_path = self.bundle_dir / "polar_lut.ugcv1"
        if verify:
            self.bundle_verification = verify_chrono_bundle(
                self.bundle_dir, verify_source_bytes=False
            )
        else:
            self.bundle_verification = None
        for path in (self.source_path, self.timeline_path, self.lut_path):
            if not path.is_file():
                raise ChronoVideoError(f"desktop runtime asset is missing: {path.name}")
        self.timeline = load_chrono_desktop_timeline(self.timeline_path)
        if self.timeline.media_sha256 != self.timeline.source_sha256:
            raise ChronoVideoError("desktop source timeline does not bind byte-identical media")
        source_sha256 = self._sha256_file(self.source_path)
        if source_sha256 != self.timeline.source_sha256:
            raise ChronoVideoError("desktop source media SHA-256 disagrees with UGCVPTS1")
        lut_data = self.lut_path.read_bytes()
        self.backend, self._remapper, self.backend_info = _select_remapper(
            backend, lut_data, max_vram_mib
        )
        inspection = self._remapper.inspection
        self._output_shape = (
            int(inspection["rho_bins"]),
            int(inspection["theta_bins"]),
            3,
        )
        self._lut_data = lut_data
        self._max_vram_mib = max_vram_mib
        self._verify_every_frame = verify_every_frame
        self._oracle_checked_frame_count = 0
        self._oracle_max_byte_difference = 0
        self._cuda_peak_allocated_mib: float | None = None
        self._decoder: Iterator[tuple[int, Fraction, Any]] | None = None
        self._next_decode_ordinal = 0
        self._slots: dict[int, ChronoDesktopFrame] = {}
        self._selected_ordinal: int | None = None
        self._start_nanoseconds: int | None = None
        self._previous_cycle = 0
        self._decoded_frame_count = 0
        self._remapped_frame_count = 0
        self._prefetched_frame_count = 0
        self._late_boundary_count = 0
        self._first_frame_max_byte_difference: int | None = None
        self._closed = False

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @property
    def started(self) -> bool:
        return self._start_nanoseconds is not None and not self._closed

    @property
    def output_shape(self) -> tuple[int, int, int]:
        return self._output_shape

    def _reset_decoder(self) -> None:
        decoder = self._decoder
        if decoder is not None:
            close = getattr(decoder, "close", None)
            if close is not None:
                close()
        self._decoder = iter(_iter_pyav_frames(self.source_path))
        self._next_decode_ordinal = 0
        self._slots.clear()

    def _decode_one(self, *, remap: bool, late_boundary: bool) -> ChronoDesktopFrame | None:
        if self._decoder is None:
            self._reset_decoder()
        assert self._decoder is not None
        ordinal = self._next_decode_ordinal
        if ordinal >= len(self.timeline.entries):
            raise ChronoVideoError("desktop decoder produced more frames than UGCVPTS1")
        try:
            pts, time_base, source_rgb = next(self._decoder)
        except StopIteration as exc:
            raise ChronoVideoError("desktop decoder ended before UGCVPTS1") from exc
        entry = self.timeline.entries[ordinal]
        expected_time_base = Fraction(
            self.timeline.time_base_num, self.timeline.time_base_den
        )
        if pts != entry.source_pts or time_base != expected_time_base:
            raise ChronoVideoError(
                f"desktop decoded PTS mismatch at ordinal {ordinal}: "
                f"got {pts}@{time_base}, expected {entry.source_pts}@{expected_time_base}"
            )
        self._next_decode_ordinal += 1
        self._decoded_frame_count += 1
        if not remap:
            return None
        polar_rgb = self._remapper.remap([source_rgb])[0]
        self._remapped_frame_count += 1
        peak_mib = self._remapper.peak_mib
        if peak_mib is not None:
            self._cuda_peak_allocated_mib = float(peak_mib)
            if self._cuda_peak_allocated_mib > self._max_vram_mib:
                raise ChronoVideoError(
                    "desktop CUDA Q8 runtime exceeded its declared workspace limit: "
                    f"{self._cuda_peak_allocated_mib:.3f} MiB > {self._max_vram_mib} MiB"
                )
        if ordinal == 0 or self._verify_every_frame:
            try:
                import numpy as np
            except ImportError as exc:
                raise ChronoVideoError("desktop runtime parity check requires NumPy") from exc
            oracle = remap_rgb_q8_numpy(source_rgb, self._lut_data)
            maximum = int(
                np.abs(polar_rgb.astype(np.int16) - oracle.astype(np.int16)).max(
                    initial=0
                )
            )
            if ordinal == 0:
                self._first_frame_max_byte_difference = maximum
            self._oracle_checked_frame_count += 1
            self._oracle_max_byte_difference = max(
                self._oracle_max_byte_difference, maximum
            )
            if maximum != 0:
                raise ChronoVideoError(
                    f"desktop selected backend disagrees with Q8 CPU oracle by {maximum}"
                )
        frame = ChronoDesktopFrame(
            ordinal=ordinal,
            source_frame_index=entry.source_frame_index,
            source_pts=entry.source_pts,
            display_until_source_pts=entry.display_until_source_pts,
            rgb=polar_rgb,
            rgb_sha256=hashlib.sha256(polar_rgb.tobytes()).hexdigest(),
            backend=self.backend,
            logical_pts_exact=True,
            physical_display_timing_verified=False,
            late_boundary=late_boundary,
        )
        self._slots[ordinal] = frame
        return frame

    def _decode_through(self, target_ordinal: int, *, late_boundary: bool) -> ChronoDesktopFrame:
        if target_ordinal < self._next_decode_ordinal and target_ordinal not in self._slots:
            self._reset_decoder()
        result = self._slots.get(target_ordinal)
        while self._next_decode_ordinal <= target_ordinal:
            ordinal = self._next_decode_ordinal
            decoded = self._decode_one(
                remap=ordinal == target_ordinal,
                late_boundary=late_boundary,
            )
            if decoded is not None:
                result = decoded
        if result is None:
            raise ChronoVideoError("desktop target frame was not staged")
        return result

    def _retain_pair(self, selected: int, prefetched: int | None = None) -> None:
        keep = {selected}
        if prefetched is not None:
            keep.add(prefetched)
        self._slots = {
            ordinal: frame for ordinal, frame in self._slots.items() if ordinal in keep
        }

    def start(self, now_nanoseconds: int | None = None) -> ChronoDesktopFrame:
        """Prime ordinal zero plus one lookahead, then start the steady clock."""

        if self._closed:
            raise ChronoVideoError("desktop chrono player is closed")
        self._reset_decoder()
        first = self._decode_through(0, late_boundary=False)
        prefetched: int | None = None
        if len(self.timeline.entries) > 1:
            self._decode_through(1, late_boundary=False)
            self._prefetched_frame_count += 1
            prefetched = 1
        self._retain_pair(0, prefetched)
        self._selected_ordinal = 0
        self._previous_cycle = 0
        self._start_nanoseconds = (
            time.perf_counter_ns() if now_nanoseconds is None else now_nanoseconds
        )
        if type(self._start_nanoseconds) is not int or self._start_nanoseconds < 0:
            raise ValueError("now_nanoseconds must be a nonnegative integer")
        return first

    def tick(self, now_nanoseconds: int | None = None) -> ChronoDesktopFrame:
        """Return the exact selected raster; late work is recorded, never hidden."""

        if not self.started:
            raise ChronoVideoError("desktop chrono player has not started")
        now = time.perf_counter_ns() if now_nanoseconds is None else now_nanoseconds
        if type(now) is not int or now < 0:
            raise ValueError("now_nanoseconds must be a nonnegative integer")
        assert self._start_nanoseconds is not None
        elapsed = max(0, now - self._start_nanoseconds)
        cycle = self.timeline.completed_cycles_for_elapsed_nanoseconds(elapsed)
        target = self.timeline.select_for_elapsed_nanoseconds(elapsed)
        if self.timeline.loops and cycle != self._previous_cycle:
            self._reset_decoder()
            self._previous_cycle = cycle
        frame = self._slots.get(target)
        if frame is None:
            self._late_boundary_count += 1
            frame = self._decode_through(target, late_boundary=True)
        self._selected_ordinal = target
        staged_successor = target + 1
        self._retain_pair(
            target,
            staged_successor if staged_successor in self._slots else None,
        )
        return frame

    def prefetch_next(self) -> ChronoDesktopFrame | None:
        """Stage one verified successor after the selected raster is published."""

        if not self.started or self._selected_ordinal is None:
            raise ChronoVideoError("desktop chrono player has not started")
        successor = self._selected_ordinal + 1
        if successor >= len(self.timeline.entries):
            if not self.timeline.loops:
                return None
            successor = 0
        if successor in self._slots:
            return self._slots[successor]
        if successor == 0:
            self._reset_decoder()
        frame = self._decode_through(successor, late_boundary=False)
        self._prefetched_frame_count += 1
        self._retain_pair(self._selected_ordinal, successor)
        return frame

    def receipt(self) -> dict[str, Any]:
        selected = (
            None
            if self._selected_ordinal is None
            else self._slots.get(self._selected_ordinal)
        )
        return {
            "schema": "ugts-chrono-desktop-runtime-receipt-0.1",
            "bundle": str(self.bundle_dir),
            "mode": "AUTHORITATIVE_SOURCE_LUT_Q8",
            "backend": self.backend,
            "backend_info": dict(self.backend_info),
            "decode_backend": "pyav-cpu-exact-pts",
            "video_decode_gpu_accelerated": False,
            "q8_compute_gpu_accelerated": self.backend == "torch-cuda-q8",
            "gpu_native_presentation": False,
            "gpu_to_cpu_readback": self.backend == "torch-cuda-q8",
            "workspace_limit_mib": self._max_vram_mib,
            "workspace_limit_enforced_after_each_remap": True,
            "cuda_peak_allocated_mib": self._cuda_peak_allocated_mib,
            "timeline_content_sha256": self.timeline.content_sha256,
            "source_sha256": self.timeline.source_sha256,
            "profile_sha256": self.timeline.profile_sha256,
            "entry_count": len(self.timeline.entries),
            "output_shape": list(self.output_shape),
            "first_frame_max_byte_difference": self._first_frame_max_byte_difference,
            "oracle_checked_frame_count": self._oracle_checked_frame_count,
            "oracle_max_byte_difference": self._oracle_max_byte_difference,
            "verify_every_frame": self._verify_every_frame,
            "selected_ordinal": None if selected is None else selected.ordinal,
            "selected_source_pts": None if selected is None else selected.source_pts,
            "selected_rgb_sha256": None if selected is None else selected.rgb_sha256,
            "decoded_frame_count": self._decoded_frame_count,
            "remapped_frame_count": self._remapped_frame_count,
            "prefetched_frame_count": self._prefetched_frame_count,
            "late_boundary_count": self._late_boundary_count,
            "logical_pts_selection": "EXACT_INTEGER_HALF_OPEN",
            "pixel_operator": "UGCVLUT1_Q8_INTEGER_EXACT",
            "physical_display_timing_verified": False,
            "cross_platform_color_byte_equal": False,
            "cross_platform_color_status": "UNVERIFIED_DECODER_YUV_TO_RGB",
            "presentation": "PYSIDE6_QGRAPHICSVIEW_DOWNSTREAM_RASTER",
            "geometry_status": "UNBOUNDED_UNKNOWN",
        }

    def close(self) -> None:
        if self._closed:
            return
        decoder = self._decoder
        if decoder is not None:
            close = getattr(decoder, "close", None)
            if close is not None:
                close()
        self._decoder = None
        self._slots.clear()
        remapper = self._remapper
        self._remapper = None
        torch = getattr(remapper, "torch", None)
        del remapper
        if torch is not None:
            torch.cuda.empty_cache()
        self._closed = True

    def __enter__(self) -> "ChronoDesktopPlayer":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def chrono_bundle_from_project(
    project: Any, project_path: str | Path | None
) -> Path | None:
    """Resolve a bound chrono bundle without guessing from ordinary projects."""

    metadata = getattr(project, "metadata", None)
    if not isinstance(metadata, Mapping):
        return None
    binding = metadata.get("chrono_scene_observation")
    if not isinstance(binding, Mapping):
        return None
    if binding.get("authority") != "OBSERVATION_ONLY":
        raise ChronoVideoError("desktop chrono project authority is not OBSERVATION_ONLY")
    if binding.get("geometry_status") != "UNBOUNDED_UNKNOWN":
        raise ChronoVideoError("desktop chrono project promoted unbounded geometry")
    chrono_owner_node_id(project)
    if project_path is None:
        raise ChronoVideoError("desktop chrono project must be saved inside its bundle")
    bundle = Path(project_path).resolve().parent
    manifest_path = bundle / str(binding.get("manifest", ""))
    if manifest_path.name != "manifest.json" or manifest_path.parent != bundle:
        raise ChronoVideoError("desktop chrono manifest binding is unsafe")
    declared = str(binding.get("manifest_sha256", ""))
    if ChronoDesktopPlayer._sha256_file(manifest_path) != declared:
        raise ChronoVideoError("desktop chrono manifest binding SHA-256 mismatch")
    return bundle


def chrono_owner_node_id(project: Any) -> str | None:
    """Return the sole authored node that owns a project chrono binding.

    Project metadata carries the asset ledger for exporters, but it may not
    conjure a global player without an ordinary editable node component.  This
    mirrors the bundle compiler's ``chrono_observation_root`` ownership model
    and rejects ambiguous or drifted copies.
    """

    metadata = getattr(project, "metadata", None)
    if not isinstance(metadata, Mapping):
        return None
    project_binding = metadata.get("chrono_scene_observation")
    if not isinstance(project_binding, Mapping):
        return None
    nodes = getattr(project, "nodes", None)
    if not isinstance(nodes, (tuple, list)):
        raise ChronoVideoError("desktop chrono project has no editable node collection")
    owners: list[tuple[str, Mapping[str, Any]]] = []
    for node in nodes:
        node_metadata = getattr(node, "metadata", None)
        if not isinstance(node_metadata, Mapping):
            continue
        binding = node_metadata.get("chrono_observation_binding")
        if isinstance(binding, Mapping):
            owners.append((str(getattr(node, "id", "")), binding))
    if len(owners) != 1:
        raise ChronoVideoError(
            "desktop chrono project must have exactly one editable owner node"
        )
    owner_id, owner = owners[0]
    if not owner_id:
        raise ChronoVideoError("desktop chrono owner node has no ID")
    expected = {
        "authority": "OBSERVATION_ONLY",
        "manifest": project_binding.get("manifest"),
        "manifest_sha256": project_binding.get("manifest_sha256"),
        "schema": project_binding.get("schema"),
        "materialization": "PROXY_ONLY",
        "writer_owner": "chrono_scene_observation",
    }
    for field, value in expected.items():
        if owner.get(field) != value:
            raise ChronoVideoError(
                f"desktop chrono owner binding disagrees with project: {field}"
            )
    return owner_id


__all__ = [
    "ChronoDesktopFrame",
    "ChronoDesktopPlayer",
    "ChronoDesktopTimeline",
    "ChronoDesktopTimelineEntry",
    "chrono_bundle_from_project",
    "chrono_owner_node_id",
    "decode_chrono_desktop_timeline",
    "load_chrono_desktop_timeline",
]
