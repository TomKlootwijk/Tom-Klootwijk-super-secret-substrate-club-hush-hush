"""Deterministic, non-generative two-view chrono-geometry hypotheses.

This module is intentionally narrower than a reconstruction system.  It binds
observations to source SHA-256 and exact integer presentation timestamps, uses
only classical OpenCV/projective operators, and emits bounded *hypotheses*.
It never promotes monocular scale, an intrinsics candidate, an unobserved
surface, or cross-time topology to physical truth.

Projective estimation is performed in the original pinhole camera-pixel chart.
The UGLUT2/UGPXLUT1 lossless polar ordering (and the older UGCVLUT1 resampling
chart) are substrate sampling/storage charts, but lines in the source image
are generally curves in either polar chart.  A polar sample must therefore
retain or recover its exact source-pixel address before the epipolar equations
below are applied.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import threading
from typing import Any, Sequence

import cv2
import numpy as np


CHRONO_GEOMETRY_SCHEMA = "ugts-chrono-geometry-hypothesis-0.1"
CHRONO_TRACK_SCHEMA = "ugts-chrono-klt-tracks-0.1"
PHYSICAL_GEOMETRY_UNKNOWN = "UNBOUNDED_UNKNOWN"
NO_CROSS_TIME_FACES = "POINT_SUPPORT_AND_TEMPORAL_LINEAGE_ONLY"
SOURCE_PIXEL_CHART = "SOURCE_RASTER_PIXELS_PRIOR_TO_LOG_POLAR_RESAMPLING"

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_CV_RNG_LOCK = threading.Lock()


class ChronoGeometryError(RuntimeError):
    """A malformed input or unavailable deterministic geometry operation."""


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _json_safe(value: Any) -> Any:
    """Convert NumPy scalars/arrays and non-finite diagnostics to strict JSON."""
    if isinstance(value, np.ndarray):
        return _json_safe(value.tolist())
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        value = float(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _finalize_report(report: dict[str, Any]) -> dict[str, Any]:
    result = _json_safe(report)
    result.pop("report_sha256", None)
    result["report_sha256"] = hashlib.sha256(
        _canonical_json_bytes(result)
    ).hexdigest()
    return result


def _sha256_file(path: Path, chunk_bytes: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(chunk_bytes):
            digest.update(block)
    return digest.hexdigest()


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


@dataclass(frozen=True)
class FrameAddress:
    """An exact decoded-frame address; no floating timestamp is substituted."""

    source_sha256: str
    source_frame_index: int
    source_pts: int
    time_base_num: int
    time_base_den: int
    width: int
    height: int

    def validate(self) -> None:
        if not _SHA256_RE.fullmatch(self.source_sha256):
            raise ValueError("source_sha256 must be 64 lowercase hexadecimal digits")
        integer_fields = (
            self.source_frame_index,
            self.source_pts,
            self.time_base_num,
            self.time_base_den,
            self.width,
            self.height,
        )
        if not all(_is_int(value) for value in integer_fields):
            raise ValueError("frame address fields must be exact integers")
        if self.source_frame_index < 0:
            raise ValueError("source_frame_index must be nonnegative")
        if self.time_base_num <= 0 or self.time_base_den <= 0:
            raise ValueError("time base must be a positive rational")
        if self.width < 2 or self.height < 2:
            raise ValueError("frame dimensions must both be at least two")

    @property
    def key(self) -> str:
        self.validate()
        payload = _canonical_json_bytes(self.to_dict(include_key=False))
        return "ugts-frame:" + hashlib.sha256(payload).hexdigest()

    def to_dict(self, *, include_key: bool = True) -> dict[str, Any]:
        self.validate()
        result: dict[str, Any] = {
            "source_sha256": self.source_sha256,
            "source_frame_index": self.source_frame_index,
            "source_pts": self.source_pts,
            "time_base_num": self.time_base_num,
            "time_base_den": self.time_base_den,
            "width": self.width,
            "height": self.height,
            "timestamp_representation": "EXACT_INTEGER_PTS_AND_RATIONAL_TIME_BASE",
        }
        if include_key:
            result["frame_address_key"] = self.key
        return result

    @classmethod
    def from_source_file(
        cls,
        source_path: Path,
        *,
        source_frame_index: int,
        source_pts: int,
        time_base_num: int,
        time_base_den: int,
        width: int,
        height: int,
    ) -> FrameAddress:
        return cls(
            source_sha256=_sha256_file(Path(source_path)),
            source_frame_index=source_frame_index,
            source_pts=source_pts,
            time_base_num=time_base_num,
            time_base_den=time_base_den,
            width=width,
            height=height,
        )


@dataclass(frozen=True)
class IntrinsicsCandidate:
    """A bounded K branch.  Supplying it is not a calibration assertion."""

    branch_id: str
    fx: float
    fy: float
    cx: float
    cy: float
    skew: float = 0.0
    origin: str = "CALLER_SUPPLIED_CANDIDATE"

    def validate(self) -> None:
        if not self.branch_id or not isinstance(self.branch_id, str):
            raise ValueError("intrinsics branch_id must be a nonempty string")
        values = (self.fx, self.fy, self.cx, self.cy, self.skew)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("intrinsics values must be finite")
        if self.fx <= 0 or self.fy <= 0:
            raise ValueError("candidate focal lengths must be positive")
        if not self.origin or not isinstance(self.origin, str):
            raise ValueError("intrinsics origin must be a nonempty string")

    def matrix(self) -> np.ndarray:
        self.validate()
        return np.array(
            [
                [self.fx, self.skew, self.cx],
                [0.0, self.fy, self.cy],
                [0.0, 0.0, 1.0],
            ],
            dtype=np.float64,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "branch_id": self.branch_id,
            "K": self.matrix().tolist(),
            "origin": self.origin,
            "calibration_state": "CANDIDATE_UNVERIFIED_NOT_PHYSICAL_TRUTH",
        }


@dataclass(frozen=True)
class ChronoGeometryConfig:
    """Finite robust-estimation and acceptance bounds."""

    rng_seed: int = 3920301
    max_corners: int = 2000
    gftt_quality_level: float = 0.01
    gftt_min_distance_pixels: float = 7.0
    gftt_block_size: int = 7
    klt_window_pixels: int = 21
    klt_max_level: int = 3
    klt_iterations: int = 30
    klt_epsilon: float = 0.01
    klt_fb_max_error_pixels: float = 1.0
    min_correspondences: int = 16
    min_fundamental_inliers: int = 12
    ransac_fundamental_threshold_pixels: float = 1.5
    ransac_homography_threshold_pixels: float = 2.0
    ransac_confidence: float = 0.999
    ransac_max_iterations: int = 5000
    homography_dominance_ratio: float = 0.95
    max_fundamental_design_condition: float = 1.0e6
    max_essential_projection_residual: float = 0.25
    min_positive_depth_fraction: float = 0.70
    min_cheirality_margin: int = 1
    min_parallax_degrees: float = 1.0
    max_median_reprojection_pixels: float = 2.0
    max_triangulation_condition: float = 1.0e6
    motion_component_spatial_radius_pixels: float = 48.0
    motion_component_flow_radius_pixels: float = 8.0
    motion_component_min_support: int = 3

    def validate(self) -> None:
        integer_positive = (
            self.max_corners,
            self.gftt_block_size,
            self.klt_window_pixels,
            self.klt_iterations,
            self.min_correspondences,
            self.min_fundamental_inliers,
            self.ransac_max_iterations,
            self.motion_component_min_support,
        )
        if not all(_is_int(value) and value > 0 for value in integer_positive):
            raise ValueError("integer geometry bounds must be positive")
        if self.min_correspondences < 8:
            raise ValueError("min_correspondences must be at least eight")
        if not 8 <= self.min_fundamental_inliers <= self.min_correspondences:
            raise ValueError(
                "min_fundamental_inliers must be in [8, min_correspondences]"
            )
        if self.max_corners < self.min_correspondences:
            raise ValueError("max_corners cannot be smaller than min_correspondences")
        if self.gftt_block_size < 3 or self.gftt_block_size % 2 == 0:
            raise ValueError("gftt_block_size must be odd and at least three")
        if self.klt_window_pixels < 3 or self.klt_window_pixels % 2 == 0:
            raise ValueError("klt_window_pixels must be odd and at least three")
        if not _is_int(self.klt_max_level) or self.klt_max_level < 0:
            raise ValueError("klt_max_level must be a nonnegative integer")
        if not _is_int(self.rng_seed) or not -(2**31) <= self.rng_seed < 2**31:
            raise ValueError("rng_seed must be a signed 32-bit integer")
        finite_positive = (
            self.gftt_quality_level,
            self.gftt_min_distance_pixels,
            self.klt_epsilon,
            self.klt_fb_max_error_pixels,
            self.ransac_fundamental_threshold_pixels,
            self.ransac_homography_threshold_pixels,
            self.max_fundamental_design_condition,
            self.max_essential_projection_residual,
            self.min_parallax_degrees,
            self.max_median_reprojection_pixels,
            self.max_triangulation_condition,
            self.motion_component_spatial_radius_pixels,
            self.motion_component_flow_radius_pixels,
        )
        if not all(math.isfinite(value) and value > 0 for value in finite_positive):
            raise ValueError("floating geometry bounds must be finite and positive")
        if not 0 < self.ransac_confidence < 1:
            raise ValueError("ransac_confidence must be in (0, 1)")
        if not 0 < self.gftt_quality_level <= 1:
            raise ValueError("gftt_quality_level must be in (0, 1]")
        if not 0 < self.homography_dominance_ratio <= 1:
            raise ValueError("homography_dominance_ratio must be in (0, 1]")
        if not 0 < self.min_positive_depth_fraction <= 1:
            raise ValueError("min_positive_depth_fraction must be in (0, 1]")
        if not _is_int(self.min_cheirality_margin) or self.min_cheirality_margin < 0:
            raise ValueError("min_cheirality_margin must be a nonnegative integer")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return dict(self.__dict__)


def operator_provenance_registry() -> dict[str, Any]:
    """Return exact non-learned operators and equations used by this module."""
    operators: dict[str, Any] = {
        "exact_frame_address": {
            "implementation": "Python integer + hashlib.sha256",
            "operator": "(source_sha256, frame_index, pts, time_base_num/den)",
            "learned_or_generative": False,
        },
        "gftt_shi_tomasi": {
            "implementation": "cv2.goodFeaturesToTrack",
            "operator": "corner response min(lambda_1, lambda_2)",
            "learned_or_generative": False,
        },
        "klt_forward_backward": {
            "implementation": "cv2.calcOpticalFlowPyrLK twice",
            "operator": "p1=KLT(I0,I1,p0); p0_back=KLT(I1,I0,p1); ||p0_back-p0||",
            "learned_or_generative": False,
        },
        "homography_ransac": {
            "implementation": "cv2.findHomography(..., cv2.RANSAC)",
            "operator": "x1 ~ H x0 with seeded finite-iteration RANSAC",
            "learned_or_generative": False,
        },
        "fundamental_ransac": {
            "implementation": "cv2.findFundamentalMat(..., cv2.FM_RANSAC)",
            "operator": "x1^T F x0 = 0 with seeded finite-iteration RANSAC",
            "learned_or_generative": False,
        },
        "sampson_residual": {
            "implementation": "NumPy explicit equation",
            "operator": "(x1^T F x0)^2 / ((F x0)_0^2+(F x0)_1^2+(F^T x1)_0^2+(F^T x1)_1^2)",
            "learned_or_generative": False,
        },
        "symmetric_transfer_residual": {
            "implementation": "NumPy explicit equation",
            "operator": "||x1-pi(Hx0)||^2 + ||x0-pi(H^-1 x1)||^2",
            "learned_or_generative": False,
        },
        "essential_candidate_projection": {
            "implementation": "numpy.linalg.svd",
            "operator": "E_raw=K^T F K; E=U diag((s0+s1)/2,(s0+s1)/2,0) V^T",
            "learned_or_generative": False,
        },
        "four_pose_hypotheses": {
            "implementation": "NumPy SVD decomposition",
            "operator": "(R1,+t),(R1,-t),(R2,+t),(R2,-t), selected by explicit cheirality gates",
            "learned_or_generative": False,
        },
        "linear_triangulation": {
            "implementation": "cv2.triangulatePoints",
            "operator": "homogeneous two-view DLT in the unit-baseline relative gauge",
            "learned_or_generative": False,
        },
        "motion_components": {
            "implementation": "deterministic radius graph connected components",
            "operator": "F-residual proposals joined by bounded image-space and flow-space radii",
            "learned_or_generative": False,
        },
    }
    registry = {
        "schema": "ugts-classical-operator-provenance-0.1",
        "opencv_version": cv2.__version__,
        "opencv_build_information_sha256": hashlib.sha256(
            cv2.getBuildInformation().encode("utf-8")
        ).hexdigest(),
        "numpy_version": np.__version__,
        "chrono_geometry_module_sha256": _sha256_file(Path(__file__).resolve()),
        "coordinate_chart": SOURCE_PIXEL_CHART,
        "operators": operators,
    }
    registry["registry_sha256"] = hashlib.sha256(
        _canonical_json_bytes(registry)
    ).hexdigest()
    return registry


def _validate_frame_pair(first: FrameAddress, second: FrameAddress) -> None:
    first.validate()
    second.validate()
    if first.source_sha256 != second.source_sha256:
        raise ValueError("frame pair must bind the same exact source SHA-256")
    if first.time_base_num != second.time_base_num or first.time_base_den != second.time_base_den:
        raise ValueError("frame pair must use one exact rational time base")
    if first.width != second.width or first.height != second.height:
        raise ValueError("frame pair dimensions must match")
    if second.source_pts <= first.source_pts:
        raise ValueError("second frame PTS must be strictly later")
    if second.source_frame_index <= first.source_frame_index:
        raise ValueError("second source frame index must be strictly later")


def _as_gray_u8(frame: np.ndarray, color_order: str) -> np.ndarray:
    value = np.asarray(frame)
    if value.ndim == 2:
        gray = value
    elif value.ndim == 3 and value.shape[2] == 3:
        if color_order == "RGB":
            gray = cv2.cvtColor(value, cv2.COLOR_RGB2GRAY)
        elif color_order == "BGR":
            gray = cv2.cvtColor(value, cv2.COLOR_BGR2GRAY)
        else:
            raise ValueError("color_order must be RGB or BGR")
    else:
        raise ValueError("frame must be HxW grayscale or HxWx3 RGB/BGR")
    if gray.dtype != np.uint8:
        raise ValueError("tracking frames must be uint8")
    return np.ascontiguousarray(gray)


def _track_id(
    source_sha256: str,
    first: FrameAddress,
    second: FrameAddress,
    point0: Sequence[float],
    point1: Sequence[float],
) -> str:
    payload = {
        "source_sha256": source_sha256,
        "from_pts": first.source_pts,
        "to_pts": second.source_pts,
        "point0_float64_hex": [float(value).hex() for value in point0],
        "point1_float64_hex": [float(value).hex() for value in point1],
    }
    return "track:" + hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def track_gftt_klt(
    frame0: np.ndarray,
    frame1: np.ndarray,
    address0: FrameAddress,
    address1: FrameAddress,
    *,
    config: ChronoGeometryConfig = ChronoGeometryConfig(),
    color_order: str = "RGB",
) -> dict[str, Any]:
    """Track GFTT points with a forward/backward KLT consistency gate."""
    config.validate()
    _validate_frame_pair(address0, address1)
    gray0 = _as_gray_u8(frame0, color_order)
    gray1 = _as_gray_u8(frame1, color_order)
    expected_shape = (address0.height, address0.width)
    if gray0.shape != expected_shape or gray1.shape != expected_shape:
        raise ValueError("decoded frame shape does not match exact frame address")

    corners = cv2.goodFeaturesToTrack(
        gray0,
        maxCorners=config.max_corners,
        qualityLevel=config.gftt_quality_level,
        minDistance=config.gftt_min_distance_pixels,
        blockSize=config.gftt_block_size,
        useHarrisDetector=False,
    )
    correspondence_rows: list[dict[str, Any]] = []
    if corners is not None and len(corners):
        criteria = (
            cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
            config.klt_iterations,
            config.klt_epsilon,
        )
        window = (config.klt_window_pixels, config.klt_window_pixels)
        forward, status_forward, _ = cv2.calcOpticalFlowPyrLK(
            gray0,
            gray1,
            corners,
            None,
            winSize=window,
            maxLevel=config.klt_max_level,
            criteria=criteria,
        )
        if forward is not None and status_forward is not None:
            backward, status_backward, _ = cv2.calcOpticalFlowPyrLK(
                gray1,
                gray0,
                forward,
                None,
                winSize=window,
                maxLevel=config.klt_max_level,
                criteria=criteria,
            )
            if backward is not None and status_backward is not None:
                p0 = corners.reshape(-1, 2).astype(np.float64)
                p1 = forward.reshape(-1, 2).astype(np.float64)
                p0_back = backward.reshape(-1, 2).astype(np.float64)
                good = status_forward.reshape(-1).astype(bool)
                good &= status_backward.reshape(-1).astype(bool)
                good &= np.isfinite(p0).all(axis=1)
                good &= np.isfinite(p1).all(axis=1)
                good &= np.isfinite(p0_back).all(axis=1)
                fb = np.linalg.norm(p0_back - p0, axis=1)
                good &= fb <= config.klt_fb_max_error_pixels
                good &= (p1[:, 0] >= 0) & (p1[:, 0] < address1.width)
                good &= (p1[:, 1] >= 0) & (p1[:, 1] < address1.height)
                accepted = np.flatnonzero(good)
                accepted = accepted[
                    np.lexsort(
                        (
                            p1[accepted, 1],
                            p1[accepted, 0],
                            p0[accepted, 1],
                            p0[accepted, 0],
                        )
                    )
                ]
                for index in accepted.tolist():
                    track_id = _track_id(
                        address0.source_sha256,
                        address0,
                        address1,
                        p0[index],
                        p1[index],
                    )
                    correspondence_rows.append(
                        {
                            "track_id": track_id,
                            "from_pixel": p0[index].tolist(),
                            "to_pixel": p1[index].tolist(),
                            "forward_backward_error_pixels": float(fb[index]),
                            "lineage_only": True,
                        }
                    )

    state = (
        "BOUNDED_TRACK_SUPPORT"
        if len(correspondence_rows) >= config.min_correspondences
        else "REJECTED_INSUFFICIENT_TRACK_SUPPORT"
    )
    report = {
        "schema": CHRONO_TRACK_SCHEMA,
        "state": state,
        "physical_geometry_state": PHYSICAL_GEOMETRY_UNKNOWN,
        "coordinate_chart": SOURCE_PIXEL_CHART,
        "frames": [address0.to_dict(), address1.to_dict()],
        "correspondence_count": len(correspondence_rows),
        "correspondences": correspondence_rows,
        "topology_state": NO_CROSS_TIME_FACES,
        "cross_time_faces": [],
        "operator_provenance": operator_provenance_registry(),
        "parameters": config.to_dict(),
    }
    return _finalize_report(report)


def _as_points(points: Sequence[Sequence[float]], label: str) -> np.ndarray:
    result = np.asarray(points, dtype=np.float64)
    if result.ndim != 2 or result.shape[1] != 2:
        raise ValueError(f"{label} must have shape Nx2")
    if not np.isfinite(result).all():
        raise ValueError(f"{label} contains non-finite coordinates")
    return np.ascontiguousarray(result)


def _validate_points_in_frame(
    points: np.ndarray, address: FrameAddress, label: str
) -> None:
    if len(points) and (
        np.any(points[:, 0] < 0.0)
        or np.any(points[:, 0] >= address.width)
        or np.any(points[:, 1] < 0.0)
        or np.any(points[:, 1] >= address.height)
    ):
        raise ValueError(f"{label} contains coordinates outside its source raster")


def _homogeneous(points: np.ndarray) -> np.ndarray:
    return np.column_stack((points, np.ones(len(points), dtype=np.float64)))


def _canonicalize_projective_matrix(matrix: np.ndarray) -> np.ndarray:
    result = np.asarray(matrix, dtype=np.float64).reshape(3, 3)
    if not np.isfinite(result).all():
        raise ChronoGeometryError("projective matrix contains non-finite values")
    scale = float(np.linalg.norm(result))
    if scale <= np.finfo(np.float64).eps:
        raise ChronoGeometryError("projective matrix has zero norm")
    result = result / scale
    pivot = int(np.argmax(np.abs(result.reshape(-1))))
    if result.reshape(-1)[pivot] < 0:
        result = -result
    return result


def sampson_residuals(
    fundamental: Sequence[Sequence[float]],
    points0: Sequence[Sequence[float]],
    points1: Sequence[Sequence[float]],
) -> np.ndarray:
    """Return explicit squared Sampson residuals in source-pixel units."""
    matrix = np.asarray(fundamental, dtype=np.float64).reshape(3, 3)
    p0 = _as_points(points0, "points0")
    p1 = _as_points(points1, "points1")
    if len(p0) != len(p1):
        raise ValueError("point arrays must have equal length")
    x0 = _homogeneous(p0)
    x1 = _homogeneous(p1)
    fx0 = (matrix @ x0.T).T
    ftx1 = (matrix.T @ x1.T).T
    numerator = np.sum(x1 * fx0, axis=1) ** 2
    denominator = (
        fx0[:, 0] ** 2
        + fx0[:, 1] ** 2
        + ftx1[:, 0] ** 2
        + ftx1[:, 1] ** 2
    )
    result = np.full(len(p0), np.inf, dtype=np.float64)
    valid = denominator > np.finfo(np.float64).eps
    result[valid] = numerator[valid] / denominator[valid]
    return result


def symmetric_transfer_residuals(
    homography: Sequence[Sequence[float]],
    points0: Sequence[Sequence[float]],
    points1: Sequence[Sequence[float]],
) -> np.ndarray:
    """Return explicit bidirectional squared homography transfer residuals."""
    matrix = np.asarray(homography, dtype=np.float64).reshape(3, 3)
    p0 = _as_points(points0, "points0")
    p1 = _as_points(points1, "points1")
    if len(p0) != len(p1):
        raise ValueError("point arrays must have equal length")
    try:
        inverse = np.linalg.inv(matrix)
    except np.linalg.LinAlgError:
        return np.full(len(p0), np.inf, dtype=np.float64)
    x0 = _homogeneous(p0)
    x1 = _homogeneous(p1)
    forward_h = (matrix @ x0.T).T
    backward_h = (inverse @ x1.T).T
    valid = (np.abs(forward_h[:, 2]) > 1.0e-15) & (
        np.abs(backward_h[:, 2]) > 1.0e-15
    )
    result = np.full(len(p0), np.inf, dtype=np.float64)
    forward = forward_h[valid, :2] / forward_h[valid, 2, None]
    backward = backward_h[valid, :2] / backward_h[valid, 2, None]
    result[valid] = np.sum((forward - p1[valid]) ** 2, axis=1) + np.sum(
        (backward - p0[valid]) ** 2, axis=1
    )
    return result


def _hartley_normalize(points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    centroid = np.mean(points, axis=0)
    centered = points - centroid
    mean_distance = float(np.mean(np.linalg.norm(centered, axis=1)))
    if mean_distance <= 1.0e-12:
        raise ChronoGeometryError("point normalization is degenerate")
    scale = math.sqrt(2.0) / mean_distance
    transform = np.array(
        [
            [scale, 0.0, -scale * centroid[0]],
            [0.0, scale, -scale * centroid[1]],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )
    normalized_h = (transform @ _homogeneous(points).T).T
    return normalized_h[:, :2], transform


def _fundamental_design_metrics(
    points0: np.ndarray, points1: np.ndarray
) -> tuple[int, float, list[float]]:
    normalized0, _ = _hartley_normalize(points0)
    normalized1, _ = _hartley_normalize(points1)
    x0, y0 = normalized0[:, 0], normalized0[:, 1]
    x1, y1 = normalized1[:, 0], normalized1[:, 1]
    design = np.column_stack(
        (x1 * x0, x1 * y0, x1, y1 * x0, y1 * y0, y1, x0, y0, np.ones(len(x0)))
    )
    singular = np.linalg.svd(design, compute_uv=False)
    tolerance = singular[0] * max(design.shape) * np.finfo(np.float64).eps
    rank = int(np.count_nonzero(singular > tolerance))
    identifiable = singular[-2] if len(singular) >= 2 else 0.0
    condition = math.inf if identifiable <= tolerance else float(singular[0] / identifiable)
    return rank, condition, singular.tolist()


def _estimate_seeded_models(
    points0: np.ndarray,
    points1: np.ndarray,
    config: ChronoGeometryConfig,
) -> tuple[np.ndarray | None, np.ndarray, np.ndarray | None, np.ndarray]:
    with _CV_RNG_LOCK:
        cv2.setRNGSeed(config.rng_seed)
        try:
            homography, homography_mask = cv2.findHomography(
                points0,
                points1,
                method=cv2.RANSAC,
                ransacReprojThreshold=config.ransac_homography_threshold_pixels,
                maxIters=config.ransac_max_iterations,
                confidence=config.ransac_confidence,
            )
        except cv2.error:
            homography, homography_mask = None, None
        cv2.setRNGSeed(config.rng_seed ^ 0x13579B)
        try:
            fundamental, fundamental_mask = cv2.findFundamentalMat(
                points0,
                points1,
                method=cv2.FM_RANSAC,
                ransacReprojThreshold=config.ransac_fundamental_threshold_pixels,
                confidence=config.ransac_confidence,
                maxIters=config.ransac_max_iterations,
            )
        except cv2.error:
            fundamental, fundamental_mask = None, None
    hmask = (
        np.zeros(len(points0), dtype=bool)
        if homography_mask is None
        else homography_mask.reshape(-1).astype(bool)
    )
    fmask = (
        np.zeros(len(points0), dtype=bool)
        if fundamental_mask is None
        else fundamental_mask.reshape(-1).astype(bool)
    )
    if homography is None or np.asarray(homography).shape != (3, 3):
        homography = None
    if fundamental is None or np.asarray(fundamental).shape != (3, 3):
        fundamental = None
    return homography, hmask, fundamental, fmask


def _project_fundamental_rank_two(matrix: np.ndarray) -> tuple[np.ndarray, list[float]]:
    u, singular, vt = np.linalg.svd(np.asarray(matrix, dtype=np.float64))
    projected = u @ np.diag((singular[0], singular[1], 0.0)) @ vt
    return _canonicalize_projective_matrix(projected), singular.tolist()


def _essential_projection(
    fundamental: np.ndarray, intrinsic: np.ndarray
) -> tuple[np.ndarray, dict[str, Any]]:
    raw = intrinsic.T @ fundamental @ intrinsic
    raw_norm = raw / max(float(np.linalg.norm(raw)), np.finfo(np.float64).eps)
    u, singular, vt = np.linalg.svd(raw_norm)
    if np.linalg.det(u) < 0:
        u[:, -1] *= -1
    if np.linalg.det(vt) < 0:
        vt[-1, :] *= -1
    average = float((singular[0] + singular[1]) * 0.5)
    projected = u @ np.diag((average, average, 0.0)) @ vt
    projected_norm = projected / max(
        float(np.linalg.norm(projected)), np.finfo(np.float64).eps
    )
    if float(np.sum(raw_norm * projected_norm)) < 0:
        projected_norm = -projected_norm
    residual = float(np.linalg.norm(raw_norm - projected_norm))
    projected_norm = _canonicalize_projective_matrix(projected_norm)
    return projected_norm, {
        "raw_singular_values": singular.tolist(),
        "projection_frobenius_residual": residual,
        "projected_singular_values": [average, average, 0.0],
    }


def _pose_hypotheses(essential: np.ndarray) -> list[tuple[np.ndarray, np.ndarray]]:
    u, _, vt = np.linalg.svd(essential)
    if np.linalg.det(u) < 0:
        u[:, -1] *= -1
    if np.linalg.det(vt) < 0:
        vt[-1, :] *= -1
    w = np.array(((0.0, -1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)))
    rotations = (u @ w @ vt, u @ w.T @ vt)
    fixed_rotations: list[np.ndarray] = []
    for rotation in rotations:
        if np.linalg.det(rotation) < 0:
            rotation = -rotation
        fixed_rotations.append(rotation)
    translation = u[:, 2]
    translation /= np.linalg.norm(translation)
    return [
        (fixed_rotations[0], translation.copy()),
        (fixed_rotations[0], -translation.copy()),
        (fixed_rotations[1], translation.copy()),
        (fixed_rotations[1], -translation.copy()),
    ]


def _project_points(
    points: np.ndarray, rotation: np.ndarray, translation: np.ndarray, intrinsic: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    camera = (rotation @ points.T).T + translation
    image_h = (intrinsic @ camera.T).T
    valid = np.abs(image_h[:, 2]) > 1.0e-15
    image = np.full((len(points), 2), np.nan, dtype=np.float64)
    image[valid] = image_h[valid, :2] / image_h[valid, 2, None]
    return image, camera[:, 2]


def _triangulation_design_condition(
    point0: np.ndarray,
    point1: np.ndarray,
    projection0: np.ndarray,
    projection1: np.ndarray,
) -> tuple[int, float]:
    design = np.stack(
        (
            point0[0] * projection0[2] - projection0[0],
            point0[1] * projection0[2] - projection0[1],
            point1[0] * projection1[2] - projection1[0],
            point1[1] * projection1[2] - projection1[1],
        )
    )
    singular = np.linalg.svd(design, compute_uv=False)
    tolerance = singular[0] * max(design.shape) * np.finfo(np.float64).eps
    constraint_rank = int(np.count_nonzero(singular[:-1] > tolerance))
    condition = (
        math.inf
        if singular[2] <= tolerance
        else float(singular[0] / singular[2])
    )
    return constraint_rank, condition


def _evaluate_pose(
    rotation: np.ndarray,
    translation: np.ndarray,
    intrinsic: np.ndarray,
    points0: np.ndarray,
    points1: np.ndarray,
    config: ChronoGeometryConfig,
) -> dict[str, Any]:
    inverse_intrinsic = np.linalg.inv(intrinsic)
    normalized0_h = (inverse_intrinsic @ _homogeneous(points0).T).T
    normalized1_h = (inverse_intrinsic @ _homogeneous(points1).T).T
    normalized0 = normalized0_h[:, :2] / normalized0_h[:, 2, None]
    normalized1 = normalized1_h[:, :2] / normalized1_h[:, 2, None]
    projection0 = np.column_stack((np.eye(3), np.zeros(3)))
    projection1 = np.column_stack((rotation, translation))
    homogeneous_points = cv2.triangulatePoints(
        projection0,
        projection1,
        normalized0.T,
        normalized1.T,
    ).T
    valid_w = np.abs(homogeneous_points[:, 3]) > 1.0e-15
    points3d = np.full((len(points0), 3), np.nan, dtype=np.float64)
    points3d[valid_w] = (
        homogeneous_points[valid_w, :3] / homogeneous_points[valid_w, 3, None]
    )
    finite = np.isfinite(points3d).all(axis=1)
    projected0, depth0 = _project_points(
        points3d, np.eye(3), np.zeros(3), intrinsic
    )
    projected1, depth1 = _project_points(points3d, rotation, translation, intrinsic)
    reprojection = np.full(len(points0), np.inf, dtype=np.float64)
    reprojection[finite] = np.sqrt(
        0.5
        * (
            np.sum((projected0[finite] - points0[finite]) ** 2, axis=1)
            + np.sum((projected1[finite] - points1[finite]) ** 2, axis=1)
        )
    )

    camera1_center = -rotation.T @ translation
    rays0 = points3d
    rays1 = points3d - camera1_center
    ray_norms = np.linalg.norm(rays0, axis=1) * np.linalg.norm(rays1, axis=1)
    parallax = np.full(len(points0), np.nan, dtype=np.float64)
    valid_rays = finite & (ray_norms > 1.0e-15)
    cosine = np.clip(
        np.sum(rays0[valid_rays] * rays1[valid_rays], axis=1)
        / ray_norms[valid_rays],
        -1.0,
        1.0,
    )
    parallax[valid_rays] = np.degrees(np.arccos(cosine))

    ranks = np.zeros(len(points0), dtype=np.int32)
    conditions = np.full(len(points0), np.inf, dtype=np.float64)
    for index, (point0, point1) in enumerate(zip(normalized0, normalized1)):
        ranks[index], conditions[index] = _triangulation_design_condition(
            point0, point1, projection0, projection1
        )
    positive = (
        finite
        & (depth0 > 1.0e-9)
        & (depth1 > 1.0e-9)
        & (ranks >= 3)
        & (conditions <= config.max_triangulation_condition)
    )
    accepted_point = (
        positive
        & np.isfinite(parallax)
        & (parallax >= config.min_parallax_degrees)
        & (reprojection <= config.max_median_reprojection_pixels)
    )
    positive_values = np.flatnonzero(positive)
    median_parallax = (
        float(np.median(parallax[positive_values]))
        if len(positive_values)
        else 0.0
    )
    median_reprojection = (
        float(np.median(reprojection[positive_values]))
        if len(positive_values)
        else math.inf
    )
    median_condition = (
        float(np.median(conditions[positive_values]))
        if len(positive_values)
        else math.inf
    )
    return {
        "rotation": rotation.tolist(),
        "translation_direction_unit_gauge": translation.tolist(),
        "positive_depth_count": int(np.count_nonzero(positive)),
        "positive_depth_fraction": float(np.mean(positive)),
        "accepted_point_count": int(np.count_nonzero(accepted_point)),
        "median_parallax_degrees": median_parallax,
        "median_reprojection_pixels": median_reprojection,
        "median_triangulation_condition": median_condition,
        "point_state": {
            "positions": points3d,
            "depth0": depth0,
            "depth1": depth1,
            "parallax_degrees": parallax,
            "reprojection_pixels": reprojection,
            "triangulation_rank": ranks,
            "triangulation_condition": conditions,
            "positive": positive,
            "accepted": accepted_point,
        },
    }


def propose_residual_motion_components(
    points0: Sequence[Sequence[float]],
    points1: Sequence[Sequence[float]],
    residual_mask: Sequence[bool],
    address0: FrameAddress,
    address1: FrameAddress,
    *,
    track_ids: Sequence[str] | None = None,
    config: ChronoGeometryConfig = ChronoGeometryConfig(),
) -> dict[str, Any]:
    """Group residual tracks into bounded, non-semantic motion proposals."""
    config.validate()
    _validate_frame_pair(address0, address1)
    p0 = _as_points(points0, "points0")
    p1 = _as_points(points1, "points1")
    residual = np.asarray(residual_mask, dtype=bool).reshape(-1)
    if len(p0) != len(p1) or len(p0) != len(residual):
        raise ValueError("points and residual_mask must have equal length")
    _validate_points_in_frame(p0, address0, "points0")
    _validate_points_in_frame(p1, address1, "points1")
    if track_ids is None:
        ids = [
            _track_id(address0.source_sha256, address0, address1, a, b)
            for a, b in zip(p0, p1)
        ]
    else:
        ids = list(track_ids)
        if len(ids) != len(p0) or len(set(ids)) != len(ids):
            raise ValueError("track_ids must be unique and match point count")

    selected = np.flatnonzero(residual).tolist()
    parent = {index: index for index in selected}

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        root_left, root_right = find(left), find(right)
        if root_left == root_right:
            return
        if root_left < root_right:
            parent[root_right] = root_left
        else:
            parent[root_left] = root_right

    midpoint = 0.5 * (p0 + p1)
    flow = p1 - p0
    for offset, left in enumerate(selected):
        for right in selected[offset + 1 :]:
            if (
                np.linalg.norm(midpoint[left] - midpoint[right])
                <= config.motion_component_spatial_radius_pixels
                and np.linalg.norm(flow[left] - flow[right])
                <= config.motion_component_flow_radius_pixels
            ):
                union(left, right)

    groups: dict[int, list[int]] = {}
    for index in selected:
        groups.setdefault(find(index), []).append(index)
    components: list[dict[str, Any]] = []
    grouped: set[int] = set()
    for indices in sorted(groups.values(), key=lambda value: tuple(value)):
        if len(indices) < config.motion_component_min_support:
            continue
        grouped.update(indices)
        component_payload = {
            "from_pts": address0.source_pts,
            "to_pts": address1.source_pts,
            "track_ids": sorted(ids[index] for index in indices),
        }
        component_id = "motion-proposal:" + hashlib.sha256(
            _canonical_json_bytes(component_payload)
        ).hexdigest()
        components.append(
            {
                "proposal_id": component_id,
                "classification_state": "RESIDUAL_MOTION_COMPONENT_CANDIDATE",
                "semantic_identity_state": "UNKNOWN_NOT_INFERRED",
                "support_count": len(indices),
                "track_ids": sorted(ids[index] for index in indices),
                "from_frame_address_key": address0.key,
                "to_frame_address_key": address1.key,
                "temporal_relation": "LINEAGE_ONLY_NO_CROSS_TIME_SURFACE",
            }
        )
    return {
        "components": components,
        "ungrouped_residual_track_ids": sorted(
            ids[index] for index in selected if index not in grouped
        ),
        "classification_claim": "PROPOSAL_ONLY_NOT_OBJECT_IDENTITY",
    }


def _base_geometry_report(
    address0: FrameAddress,
    address1: FrameAddress,
    config: ChronoGeometryConfig,
    observation_layers: list[dict[str, Any]],
    temporal_lineage: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema": CHRONO_GEOMETRY_SCHEMA,
        "state": "REJECTED_UNBOUNDED_UNKNOWN",
        "physical_geometry_state": PHYSICAL_GEOMETRY_UNKNOWN,
        "metric_scale_state": "UNKNOWN_MONOCULAR_GAUGE",
        "hidden_surface_state": "UNOBSERVED_UNKNOWN",
        "coordinate_chart": SOURCE_PIXEL_CHART,
        "log_polar_relation": (
            "UGLUT2_UGPXLUT1_OR_UGCVLUT1_MUST_RETAIN_OR_RECOVER_EXACT_"
            "SOURCE_PIXEL_ADDRESSES"
        ),
        "frames": [address0.to_dict(), address1.to_dict()],
        "observation_layers": observation_layers,
        "temporal_lineage": temporal_lineage,
        "topology_state": NO_CROSS_TIME_FACES,
        "cross_time_faces": [],
        "rejection_reasons": [],
        "projective_models": {},
        "intrinsics_branches": [],
        "static_background_proposal": {},
        "residual_motion_proposals": {},
        "operator_provenance": operator_provenance_registry(),
        "parameters": config.to_dict(),
    }


def estimate_two_view_geometry(
    address0: FrameAddress,
    address1: FrameAddress,
    points0: Sequence[Sequence[float]],
    points1: Sequence[Sequence[float]],
    *,
    intrinsics_candidates: Sequence[IntrinsicsCandidate] = (),
    track_ids: Sequence[str] | None = None,
    config: ChronoGeometryConfig = ChronoGeometryConfig(),
) -> dict[str, Any]:
    """Estimate bounded projective/relative hypotheses and fail closed.

    Even a passing branch remains unit-baseline relative geometry associated
    with an unverified K candidate.  It is not metric physical truth.
    """
    config.validate()
    _validate_frame_pair(address0, address1)
    p0_input = _as_points(points0, "points0")
    p1_input = _as_points(points1, "points1")
    if len(p0_input) != len(p1_input):
        raise ValueError("point arrays must have equal length")
    _validate_points_in_frame(p0_input, address0, "points0")
    _validate_points_in_frame(p1_input, address1, "points1")
    if track_ids is not None and (
        len(track_ids) != len(p0_input) or len(set(track_ids)) != len(track_ids)
    ):
        raise ValueError("track_ids must be unique and match point count")
    branch_ids = [candidate.branch_id for candidate in intrinsics_candidates]
    if len(branch_ids) != len(set(branch_ids)):
        raise ValueError("intrinsics branch IDs must be unique")
    for candidate in intrinsics_candidates:
        candidate.validate()

    order = np.lexsort(
        (p1_input[:, 1], p1_input[:, 0], p0_input[:, 1], p0_input[:, 0])
    )
    p0 = p0_input[order]
    p1 = p1_input[order]
    if track_ids is None:
        ids = [
            _track_id(address0.source_sha256, address0, address1, a, b)
            for a, b in zip(p0, p1)
        ]
    else:
        ids = [str(track_ids[index]) for index in order]

    observation0: list[dict[str, Any]] = []
    observation1: list[dict[str, Any]] = []
    temporal_lineage: list[dict[str, Any]] = []
    for index, (point0, point1, track_id) in enumerate(zip(p0, p1, ids)):
        first_id = f"{address0.key}:point:{index}"
        second_id = f"{address1.key}:point:{index}"
        observation0.append(
            {
                "observation_id": first_id,
                "track_id": track_id,
                "pixel": point0.tolist(),
                "support_time": "EXACT_SOURCE_PTS",
            }
        )
        observation1.append(
            {
                "observation_id": second_id,
                "track_id": track_id,
                "pixel": point1.tolist(),
                "support_time": "EXACT_SOURCE_PTS",
            }
        )
        temporal_lineage.append(
            {
                "track_id": track_id,
                "from_observation_id": first_id,
                "to_observation_id": second_id,
                "relation": "TEMPORAL_LINEAGE_ONLY",
            }
        )
    observation_layers = [
        {
            "frame_address_key": address0.key,
            "source_pts": address0.source_pts,
            "topology": "SAME_TIME_POINTS_ONLY",
            "points": observation0,
        },
        {
            "frame_address_key": address1.key,
            "source_pts": address1.source_pts,
            "topology": "SAME_TIME_POINTS_ONLY",
            "points": observation1,
        },
    ]
    report = _base_geometry_report(
        address0, address1, config, observation_layers, temporal_lineage
    )
    report["correspondence_count"] = len(p0)
    if len(p0) < config.min_correspondences:
        report["rejection_reasons"] = ["INSUFFICIENT_CORRESPONDENCES"]
        return _finalize_report(report)

    homography_raw, hmask_cv, fundamental_raw, fmask_cv = _estimate_seeded_models(
        p0, p1, config
    )
    if fundamental_raw is None:
        report["rejection_reasons"] = ["FUNDAMENTAL_ESTIMATION_FAILED"]
        return _finalize_report(report)
    fundamental, fundamental_raw_singular = _project_fundamental_rank_two(
        fundamental_raw
    )
    sampson = sampson_residuals(fundamental, p0, p1)
    fmask = fmask_cv & (
        sampson <= config.ransac_fundamental_threshold_pixels**2
    )
    f_indices = np.flatnonzero(fmask)

    homography: np.ndarray | None = None
    symmetric = np.full(len(p0), np.inf, dtype=np.float64)
    hmask = np.zeros(len(p0), dtype=bool)
    if homography_raw is not None:
        homography = _canonicalize_projective_matrix(homography_raw)
        symmetric = symmetric_transfer_residuals(homography, p0, p1)
        hmask = hmask_cv & (
            symmetric <= 2.0 * config.ransac_homography_threshold_pixels**2
        )
    h_indices = np.flatnonzero(hmask)

    design_rank = 0
    design_condition = math.inf
    design_singular: list[float] = []
    if len(f_indices) >= 8:
        try:
            design_rank, design_condition, design_singular = (
                _fundamental_design_metrics(p0[fmask], p1[fmask])
            )
        except ChronoGeometryError:
            pass
    homography_dominant = (
        len(h_indices) >= config.min_fundamental_inliers
        and len(h_indices)
        >= math.ceil(config.homography_dominance_ratio * max(len(f_indices), 1))
    )
    report["projective_models"] = {
        "fundamental": {
            "matrix_rank2_canonical": fundamental.tolist(),
            "raw_singular_values": fundamental_raw_singular,
            "inlier_count": len(f_indices),
            "inlier_track_ids": [ids[index] for index in f_indices],
            "sampson_squared_pixels": sampson.tolist(),
            "design_rank": design_rank,
            "design_condition_excluding_null": design_condition,
            "design_singular_values": design_singular,
            "claim_state": "PROJECTIVE_EPIPOLAR_HYPOTHESIS",
        },
        "homography": {
            "matrix_canonical": None if homography is None else homography.tolist(),
            "inlier_count": len(h_indices),
            "inlier_track_ids": [ids[index] for index in h_indices],
            "symmetric_transfer_squared_pixels": symmetric.tolist(),
            "dominates_fundamental_support": homography_dominant,
            "claim_state": "PLANAR_OR_ROTATIONAL_HYPOTHESIS_ONLY",
        },
    }
    report["static_background_proposal"] = {
        "classification_state": "STATIC_BACKGROUND_EPIPOLAR_INLIER_CANDIDATE",
        "semantic_identity_state": "UNKNOWN_NOT_INFERRED",
        "support_count": len(f_indices),
        "track_ids": [ids[index] for index in f_indices],
    }
    report["residual_motion_proposals"] = propose_residual_motion_components(
        p0,
        p1,
        ~fmask,
        address0,
        address1,
        track_ids=ids,
        config=config,
    )

    rejection_reasons: list[str] = []
    if len(f_indices) < config.min_fundamental_inliers:
        rejection_reasons.append("INSUFFICIENT_FUNDAMENTAL_INLIERS")
    if design_rank < 8:
        rejection_reasons.append("FUNDAMENTAL_DESIGN_RANK_DEGENERATE")
    if design_condition > config.max_fundamental_design_condition:
        rejection_reasons.append("FUNDAMENTAL_DESIGN_CONDITION_EXCEEDED")
    if homography_dominant:
        rejection_reasons.append("PLANAR_OR_PURE_ROTATION_HOMOGRAPHY_DOMINANT")
    if rejection_reasons:
        report["rejection_reasons"] = rejection_reasons
        return _finalize_report(report)

    accepted_branches = 0
    branch_reports: list[dict[str, Any]] = []
    for candidate in intrinsics_candidates:
        intrinsic = candidate.matrix()
        essential, essential_metrics = _essential_projection(fundamental, intrinsic)
        pose_evaluations = [
            _evaluate_pose(rotation, translation, intrinsic, p0[fmask], p1[fmask], config)
            for rotation, translation in _pose_hypotheses(essential)
        ]
        ranking = sorted(
            range(4),
            key=lambda index: (
                -pose_evaluations[index]["positive_depth_count"],
                pose_evaluations[index]["median_reprojection_pixels"],
                index,
            ),
        )
        selected_index = ranking[0]
        selected = pose_evaluations[selected_index]
        second_positive = pose_evaluations[ranking[1]]["positive_depth_count"]
        cheirality_margin = selected["positive_depth_count"] - second_positive
        branch_rejections: list[str] = []
        if (
            essential_metrics["projection_frobenius_residual"]
            > config.max_essential_projection_residual
        ):
            branch_rejections.append("ESSENTIAL_MANIFOLD_PROJECTION_RESIDUAL_EXCEEDED")
        if selected["positive_depth_count"] < config.min_fundamental_inliers:
            branch_rejections.append("INSUFFICIENT_POSITIVE_DEPTH_SUPPORT")
        if selected["positive_depth_fraction"] < config.min_positive_depth_fraction:
            branch_rejections.append("POSITIVE_DEPTH_FRACTION_BELOW_BOUND")
        if cheirality_margin < config.min_cheirality_margin:
            branch_rejections.append("CHEIRALITY_SELECTION_AMBIGUOUS")
        if selected["median_parallax_degrees"] < config.min_parallax_degrees:
            branch_rejections.append("LOW_PARALLAX")
        if (
            selected["median_reprojection_pixels"]
            > config.max_median_reprojection_pixels
        ):
            branch_rejections.append("REPROJECTION_RESIDUAL_EXCEEDED")
        if (
            selected["median_triangulation_condition"]
            > config.max_triangulation_condition
        ):
            branch_rejections.append("TRIANGULATION_CONDITION_EXCEEDED")

        point_state = selected.pop("point_state")
        for index, evaluation in enumerate(pose_evaluations):
            if index != selected_index:
                evaluation.pop("point_state")
        point_hypotheses: list[dict[str, Any]] = []
        if not branch_rejections:
            accepted_branches += 1
            for local_index in np.flatnonzero(point_state["accepted"]).tolist():
                global_index = int(f_indices[local_index])
                point_hypotheses.append(
                    {
                        "point_hypothesis_id": (
                            f"{candidate.branch_id}:relative-point:{local_index}"
                        ),
                        "position_unit_baseline_relative_gauge": point_state[
                            "positions"
                        ][local_index].tolist(),
                        "depth0_relative_gauge": float(
                            point_state["depth0"][local_index]
                        ),
                        "depth1_relative_gauge": float(
                            point_state["depth1"][local_index]
                        ),
                        "parallax_degrees": float(
                            point_state["parallax_degrees"][local_index]
                        ),
                        "reprojection_pixels": float(
                            point_state["reprojection_pixels"][local_index]
                        ),
                        "triangulation_rank": int(
                            point_state["triangulation_rank"][local_index]
                        ),
                        "triangulation_condition": float(
                            point_state["triangulation_condition"][local_index]
                        ),
                        "track_id": ids[global_index],
                        "same_time_support_by_frame": [
                            {
                                "frame_address_key": address0.key,
                                "source_pts": address0.source_pts,
                                "observation_id": observation0[global_index][
                                    "observation_id"
                                ],
                            },
                            {
                                "frame_address_key": address1.key,
                                "source_pts": address1.source_pts,
                                "observation_id": observation1[global_index][
                                    "observation_id"
                                ],
                            },
                        ],
                        "claim_state": "RELATIVE_PROJECTIVE_POINT_HYPOTHESIS",
                    }
                )
        serial_pose_evaluations = []
        for index, evaluation in enumerate(pose_evaluations):
            serial_pose_evaluations.append(
                {
                    "hypothesis_index": index,
                    **evaluation,
                    "selected_by_cheirality": index == selected_index,
                }
            )
        branch_reports.append(
            {
                **candidate.to_dict(),
                "state": (
                    "BOUNDED_RELATIVE_POSE_HYPOTHESIS"
                    if not branch_rejections
                    else "REJECTED_INTRINSICS_BRANCH"
                ),
                "essential_matrix_projected": essential.tolist(),
                "essential_projection": essential_metrics,
                "four_pose_hypotheses": serial_pose_evaluations,
                "selected_pose_hypothesis_index": selected_index,
                "cheirality_margin": cheirality_margin,
                "rejection_reasons": branch_rejections,
                "relative_point_hypotheses": point_hypotheses,
                "metric_claim": "NONE_SCALE_AND_CALIBRATION_UNVERIFIED",
            }
        )
    report["intrinsics_branches"] = branch_reports
    if not intrinsics_candidates:
        report["rejection_reasons"] = ["NO_INTRINSICS_CANDIDATE_BRANCHES"]
    elif not accepted_branches:
        report["rejection_reasons"] = ["ALL_INTRINSICS_BRANCHES_REJECTED"]
    else:
        report["state"] = "BOUNDED_RELATIVE_PROJECTIVE_HYPOTHESES"
        report["rejection_reasons"] = []
    report["accepted_intrinsics_branch_count"] = accepted_branches
    report["intrinsics_selection_state"] = (
        "BOUNDED_JOINT_HYPOTHESES_NO_CALIBRATION_BRANCH_PROMOTED"
    )
    return _finalize_report(report)


def analyze_frame_pair(
    frame0: np.ndarray,
    frame1: np.ndarray,
    address0: FrameAddress,
    address1: FrameAddress,
    *,
    intrinsics_candidates: Sequence[IntrinsicsCandidate] = (),
    config: ChronoGeometryConfig = ChronoGeometryConfig(),
    color_order: str = "RGB",
) -> dict[str, Any]:
    """Run exact-address GFTT/KLT and then bounded two-view geometry."""
    tracks = track_gftt_klt(
        frame0,
        frame1,
        address0,
        address1,
        config=config,
        color_order=color_order,
    )
    correspondences = tracks["correspondences"]
    if len(correspondences) < config.min_correspondences:
        return {
            "schema": CHRONO_GEOMETRY_SCHEMA,
            "state": "REJECTED_UNBOUNDED_UNKNOWN",
            "physical_geometry_state": PHYSICAL_GEOMETRY_UNKNOWN,
            "rejection_reasons": ["INSUFFICIENT_FORWARD_BACKWARD_TRACKS"],
            "tracking": tracks,
            "topology_state": NO_CROSS_TIME_FACES,
            "cross_time_faces": [],
        }
    result = estimate_two_view_geometry(
        address0,
        address1,
        [item["from_pixel"] for item in correspondences],
        [item["to_pixel"] for item in correspondences],
        intrinsics_candidates=intrinsics_candidates,
        track_ids=[item["track_id"] for item in correspondences],
        config=config,
    )
    result["tracking"] = tracks
    return _finalize_report(result)
