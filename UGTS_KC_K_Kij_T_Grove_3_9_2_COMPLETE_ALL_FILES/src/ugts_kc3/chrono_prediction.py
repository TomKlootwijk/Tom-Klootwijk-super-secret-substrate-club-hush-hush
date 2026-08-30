"""Reversible substrate-neighborhood prediction for UGTC4D RGB observations.

The prediction graph is regenerated from the seed/UGLUT2 traversal and the
ordinary eight-neighbor pixel lattice.  It is not serialized as a per-pixel
map.  For each traversal ordinal, already-decoded neighbors select either the
JPEG-LS median edge predictor or the most recent available neighbor.  A
reversible green/difference transform and planar residual layout expose the
result to the codec-native entropy operator.

JPEG-LS supplies only the exact median equation.  The predecessor selection,
seed-regenerated traversal, transform, and ABI are UGTOMS chrono operators.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .chrono_substrate import (
    SubstrateTraversalRecipe,
    derive_substrate_traversal,
)


PREDICTOR_SUBSTRATE_MEDIAN_GREEN = 10
PREDICTOR_TEMPORAL_SUBSTRATE_MEDIAN_GREEN = 11
PREDICTOR_CARTESIAN_MEDIAN_GREEN_SUBSTRATE_ORDER = 12
PREDICTOR_CARTESIAN_MEDIAN_GREEN_LIFT_SUBSTRATE_ORDER = 13
PREDICTOR_NAMES = {
    PREDICTOR_SUBSTRATE_MEDIAN_GREEN: "SUBSTRATE_MEDIAN_GREEN_PLANAR_MOD256",
    PREDICTOR_TEMPORAL_SUBSTRATE_MEDIAN_GREEN: (
        "TEMPORAL_THEN_SUBSTRATE_MEDIAN_GREEN_PLANAR_MOD256"
    ),
    PREDICTOR_CARTESIAN_MEDIAN_GREEN_SUBSTRATE_ORDER: (
        "CARTESIAN_MEDIAN_GREEN_SUBSTRATE_ADDRESSED_PLANAR_MOD256"
    ),
    PREDICTOR_CARTESIAN_MEDIAN_GREEN_LIFT_SUBSTRATE_ORDER: (
        "CARTESIAN_MEDIAN_GREEN_LUMA_LIFT_SUBSTRATE_ADDRESSED_PLANAR_MOD256"
    ),
}


class ChronoPredictionError(ValueError):
    """Invalid prediction topology, frame, or replay dependency."""


@dataclass(frozen=True)
class SubstratePredictionPlan:
    """In-memory predecessor plan regenerated from one traversal."""

    width: int
    height: int
    traversal_sha256: str
    traversal: Any
    parent: Any
    a: Any
    b: Any
    c: Any
    use_median: Any

    @property
    def pixel_count(self) -> int:
        return int(self.width) * int(self.height)

    @property
    def ram_bytes(self) -> int:
        return sum(
            int(value.nbytes)
            for value in (
                self.traversal,
                self.parent,
                self.a,
                self.b,
                self.c,
                self.use_median,
            )
        )


def build_substrate_prediction_plan(
    recipe: SubstrateTraversalRecipe,
    uglut2_bytes: bytes,
    *,
    traversal: Any | None = None,
) -> SubstratePredictionPlan:
    """Regenerate the exact predecessor graph; no graph bytes enter the stream."""

    try:
        import numpy as np
    except ImportError as error:
        raise ChronoPredictionError("substrate prediction planning requires NumPy") from error
    order = (
        derive_substrate_traversal(recipe, uglut2_bytes)
        if traversal is None
        else np.asarray(traversal, dtype=np.uint32)
    )
    if order.shape != (recipe.pixel_count,):
        raise ChronoPredictionError("substrate prediction traversal shape mismatch")
    if np.unique(order).size != recipe.pixel_count:
        raise ChronoPredictionError("substrate prediction traversal is not bijective")
    order64 = order.astype(np.int64)
    inverse = np.empty(recipe.pixel_count, dtype=np.int32)
    inverse[order64] = np.arange(recipe.pixel_count, dtype=np.int32)
    x = order64 % recipe.width
    y = order64 // recipe.width
    current = np.arange(recipe.pixel_count, dtype=np.int32)

    offsets = (
        (-1, 0),
        (1, 0),
        (0, -1),
        (0, 1),
        (-1, -1),
        (1, -1),
        (-1, 1),
        (1, 1),
    )
    predecessor: dict[tuple[int, int], Any] = {}
    for dx, dy in offsets:
        neighbor_x = x + dx
        neighbor_y = y + dy
        inside = (
            (neighbor_x >= 0)
            & (neighbor_x < recipe.width)
            & (neighbor_y >= 0)
            & (neighbor_y < recipe.height)
        )
        cartesian = np.where(
            inside, neighbor_y * recipe.width + neighbor_x, 0
        ).astype(np.int64)
        ordinal = inverse[cartesian]
        predecessor[(dx, dy)] = np.where(
            inside & (ordinal < current), ordinal, -1
        ).astype(np.int32)

    neighbor_ordinals = np.stack(
        [predecessor[offset] for offset in offsets], axis=1
    )
    parent = np.max(neighbor_ordinals, axis=1).astype(np.int32)
    triples = (
        ((-1, 0), (0, -1), (-1, -1)),
        ((1, 0), (0, -1), (1, -1)),
        ((-1, 0), (0, 1), (-1, 1)),
        ((1, 0), (0, 1), (1, 1)),
    )
    scores = np.stack(
        [
            np.where(
                (predecessor[left] >= 0)
                & (predecessor[vertical] >= 0)
                & (predecessor[diagonal] >= 0),
                np.minimum(
                    np.minimum(predecessor[left], predecessor[vertical]),
                    predecessor[diagonal],
                ),
                -1,
            )
            for left, vertical, diagonal in triples
        ],
        axis=1,
    )
    choice = np.argmax(scores, axis=1)
    use_median = np.max(scores, axis=1) >= 0
    selected = []
    for lane in range(3):
        selected.append(
            np.choose(
                choice,
                [predecessor[triple[lane]] for triple in triples],
            ).astype(np.int32)
        )
    return SubstratePredictionPlan(
        recipe.width,
        recipe.height,
        recipe.traversal_sha256,
        order.astype(np.uint32, copy=False),
        parent,
        selected[0],
        selected[1],
        selected[2],
        use_median.astype(np.bool_),
    )


def _require_polar_rgb(value: Any, plan: SubstratePredictionPlan) -> Any:
    try:
        import numpy as np
    except ImportError as error:
        raise ChronoPredictionError("substrate prediction requires NumPy") from error
    array = np.asarray(value)
    expected = (plan.pixel_count, 3)
    if array.shape != expected or array.dtype != np.uint8:
        raise ChronoPredictionError(f"polar RGB must be uint8 with shape {expected}")
    return array


def _green_delta_numpy(rgb: Any) -> Any:
    import numpy as np

    result = np.empty_like(rgb)
    result[:, 0] = rgb[:, 1]
    result[:, 1] = rgb[:, 0] - rgb[:, 1]
    result[:, 2] = rgb[:, 2] - rgb[:, 1]
    return result


def _inverse_green_delta_numpy(transformed: Any) -> Any:
    import numpy as np

    result = np.empty_like(transformed)
    result[:, 1] = transformed[:, 0]
    result[:, 0] = transformed[:, 1] + transformed[:, 0]
    result[:, 2] = transformed[:, 2] + transformed[:, 0]
    return result


def _green_luma_lift_numpy(rgb: Any) -> Any:
    """Exact new codec lift: Y=G+floor((s8(R-G)+s8(B-G))/4)."""

    import numpy as np

    signed = rgb.astype(np.int16)
    cr = ((signed[:, 0] - signed[:, 1] + 128) & 255) - 128
    cb = ((signed[:, 2] - signed[:, 1] + 128) & 255) - 128
    quarter = np.floor_divide(cr + cb, 4)
    result = np.empty_like(rgb)
    result[:, 0] = (signed[:, 1] + quarter) & 255
    result[:, 1] = cr & 255
    result[:, 2] = cb & 255
    return result


def _inverse_green_luma_lift_numpy(transformed: Any) -> Any:
    import numpy as np

    lanes = transformed.astype(np.int16)
    cr = ((lanes[:, 1] + 128) & 255) - 128
    cb = ((lanes[:, 2] + 128) & 255) - 128
    quarter = np.floor_divide(cr + cb, 4)
    green = (lanes[:, 0] - quarter) & 255
    result = np.empty_like(transformed)
    result[:, 1] = green
    result[:, 0] = (green + cr) & 255
    result[:, 2] = (green + cb) & 255
    return result


def _median_prediction_numpy(values: Any, plan: SubstratePredictionPlan) -> Any:
    import numpy as np

    prediction = np.zeros_like(values)
    has_parent = plan.parent >= 0
    prediction[has_parent] = values[plan.parent[has_parent]]
    use = plan.use_median
    a = values[plan.a[use]].astype(np.int16)
    b = values[plan.b[use]].astype(np.int16)
    c = values[plan.c[use]].astype(np.int16)
    low = np.minimum(a, b)
    high = np.maximum(a, b)
    prediction[use] = np.maximum(low, np.minimum(high, a + b - c)).astype(
        np.uint8
    )
    return prediction


def _cartesian_median_residual_numpy(
    polar_rgb: Any,
    plan: SubstratePredictionPlan,
    *,
    lifted: bool,
) -> Any:
    import numpy as np

    cartesian_rgb = np.empty((plan.pixel_count, 3), dtype=np.uint8)
    cartesian_rgb[plan.traversal.astype(np.int64)] = polar_rgb
    values = (
        _green_luma_lift_numpy(cartesian_rgb)
        if lifted
        else _green_delta_numpy(cartesian_rgb)
    ).reshape(plan.height, plan.width, 3)
    a = np.zeros_like(values, dtype=np.int16)
    b = np.zeros_like(values, dtype=np.int16)
    c = np.zeros_like(values, dtype=np.int16)
    a[:, 1:] = values[:, :-1]
    b[1:, :] = values[:-1, :]
    c[1:, 1:] = values[:-1, :-1]
    low = np.minimum(a, b)
    high = np.maximum(a, b)
    prediction = np.maximum(low, np.minimum(high, a + b - c)).astype(np.uint8)
    # Canonical one-dimensional boundary rules retain causality at the top
    # row and left edge without inventing samples outside the raster.
    prediction[0, 0] = 0
    prediction[0, 1:] = values[0, :-1]
    prediction[1:, 0] = values[:-1, 0]
    residual = values - prediction
    return residual.reshape(-1, 3)[plan.traversal.astype(np.int64)]


def encode_substrate_prediction_numpy(
    polar_rgb: Any,
    plan: SubstratePredictionPlan,
    *,
    predictor: int,
    previous_polar_rgb: Any | None = None,
) -> bytes:
    """Return channel-planar modulo-256 residual bytes."""

    import numpy as np

    current = _green_delta_numpy(_require_polar_rgb(polar_rgb, plan))
    if predictor in (
        PREDICTOR_CARTESIAN_MEDIAN_GREEN_SUBSTRATE_ORDER,
        PREDICTOR_CARTESIAN_MEDIAN_GREEN_LIFT_SUBSTRATE_ORDER,
    ):
        residual = _cartesian_median_residual_numpy(
            _require_polar_rgb(polar_rgb, plan),
            plan,
            lifted=(
                predictor
                == PREDICTOR_CARTESIAN_MEDIAN_GREEN_LIFT_SUBSTRATE_ORDER
            ),
        )
        return np.ascontiguousarray(residual.T).tobytes()
    if predictor == PREDICTOR_SUBSTRATE_MEDIAN_GREEN:
        values = current
    elif predictor == PREDICTOR_TEMPORAL_SUBSTRATE_MEDIAN_GREEN:
        if previous_polar_rgb is None:
            raise ChronoPredictionError("temporal substrate predictor requires a previous frame")
        previous = _green_delta_numpy(_require_polar_rgb(previous_polar_rgb, plan))
        values = current - previous
    else:
        raise ChronoPredictionError(f"unsupported substrate predictor {predictor}")
    prediction = _median_prediction_numpy(values, plan)
    residual = values - prediction
    return np.ascontiguousarray(residual.T).tobytes()


try:
    import numpy as _np
    from numba import njit as _njit
except ImportError:  # pragma: no cover
    _np = None
    _njit = None


if _njit is not None:

    @_njit(cache=True)
    def _decode_prediction_numba(  # pragma: no cover - JIT body
        residual, parent, a_index, b_index, c_index, use_median
    ):
        count = residual.shape[0]
        values = _np.empty((count, 3), dtype=_np.uint8)
        for ordinal in range(count):
            for channel in range(3):
                if use_median[ordinal]:
                    a = _np.int64(values[a_index[ordinal], channel])
                    b = _np.int64(values[b_index[ordinal], channel])
                    c = _np.int64(values[c_index[ordinal], channel])
                    low = min(a, b)
                    high = max(a, b)
                    prediction = max(low, min(high, a + b - c))
                elif parent[ordinal] >= 0:
                    prediction = _np.int64(values[parent[ordinal], channel])
                else:
                    prediction = _np.int64(0)
                total = _np.int64(residual[ordinal, channel]) + prediction
                values[ordinal, channel] = total % 256
        return values

    @_njit(cache=True)
    def _decode_cartesian_prediction_numba(residual):  # pragma: no cover
        height, width, _channels = residual.shape
        values = _np.empty((height, width, 3), dtype=_np.uint8)
        for y in range(height):
            for x in range(width):
                for channel in range(3):
                    if y == 0 and x == 0:
                        prediction = _np.int64(0)
                    elif y == 0:
                        prediction = _np.int64(values[y, x - 1, channel])
                    elif x == 0:
                        prediction = _np.int64(values[y - 1, x, channel])
                    else:
                        a = _np.int64(values[y, x - 1, channel])
                        b = _np.int64(values[y - 1, x, channel])
                        c = _np.int64(values[y - 1, x - 1, channel])
                        low = min(a, b)
                        high = max(a, b)
                        prediction = max(low, min(high, a + b - c))
                    total = _np.int64(residual[y, x, channel]) + prediction
                    values[y, x, channel] = total % 256
        return values


def decode_substrate_prediction_numpy(
    residual_bytes: bytes | bytearray | memoryview,
    plan: SubstratePredictionPlan,
    *,
    predictor: int,
    previous_polar_rgb: Any | None = None,
) -> Any:
    """Replay one residual plane to exact polar-ordered RGB8."""

    try:
        import numpy as np
    except ImportError as error:
        raise ChronoPredictionError("substrate prediction decode requires NumPy") from error
    raw = bytes(residual_bytes)
    expected = plan.pixel_count * 3
    if len(raw) != expected:
        raise ChronoPredictionError(
            f"substrate residual length mismatch: expected {expected}, got {len(raw)}"
        )
    residual = np.frombuffer(raw, dtype=np.uint8).reshape(3, plan.pixel_count).T
    if predictor in (
        PREDICTOR_CARTESIAN_MEDIAN_GREEN_SUBSTRATE_ORDER,
        PREDICTOR_CARTESIAN_MEDIAN_GREEN_LIFT_SUBSTRATE_ORDER,
    ):
        cartesian_residual = np.empty((plan.pixel_count, 3), dtype=np.uint8)
        cartesian_residual[plan.traversal.astype(np.int64)] = residual
        cartesian_residual = cartesian_residual.reshape(plan.height, plan.width, 3)
        if _njit is not None:
            values = _decode_cartesian_prediction_numba(cartesian_residual)
        else:  # pragma: no cover
            values = np.empty_like(cartesian_residual)
            for y in range(plan.height):
                for x in range(plan.width):
                    if y == 0 and x == 0:
                        prediction = np.zeros(3, dtype=np.int16)
                    elif y == 0:
                        prediction = values[y, x - 1].astype(np.int16)
                    elif x == 0:
                        prediction = values[y - 1, x].astype(np.int16)
                    else:
                        aa = values[y, x - 1].astype(np.int16)
                        bb = values[y - 1, x].astype(np.int16)
                        cc = values[y - 1, x - 1].astype(np.int16)
                        prediction = np.maximum(
                            np.minimum(aa, bb),
                            np.minimum(np.maximum(aa, bb), aa + bb - cc),
                        )
                    values[y, x] = (
                        cartesian_residual[y, x].astype(np.int16) + prediction
                    ) & 255
        transformed = values.reshape(plan.pixel_count, 3)
        rgb_cartesian = (
            _inverse_green_luma_lift_numpy(transformed)
            if predictor
            == PREDICTOR_CARTESIAN_MEDIAN_GREEN_LIFT_SUBSTRATE_ORDER
            else _inverse_green_delta_numpy(transformed)
        )
        return rgb_cartesian[plan.traversal.astype(np.int64)].copy()
    if _njit is not None:
        values = _decode_prediction_numba(
            residual,
            plan.parent,
            plan.a,
            plan.b,
            plan.c,
            plan.use_median,
        )
    else:  # pragma: no cover - minimal installation fallback.
        values = np.empty((plan.pixel_count, 3), dtype=np.uint8)
        for ordinal in range(plan.pixel_count):
            if plan.use_median[ordinal]:
                aa = values[plan.a[ordinal]].astype(np.int16)
                bb = values[plan.b[ordinal]].astype(np.int16)
                cc = values[plan.c[ordinal]].astype(np.int16)
                low = np.minimum(aa, bb)
                high = np.maximum(aa, bb)
                prediction = np.maximum(low, np.minimum(high, aa + bb - cc))
            elif plan.parent[ordinal] >= 0:
                prediction = values[plan.parent[ordinal]].astype(np.int16)
            else:
                prediction = np.zeros(3, dtype=np.int16)
            values[ordinal] = (residual[ordinal].astype(np.int16) + prediction) & 255
    if predictor == PREDICTOR_TEMPORAL_SUBSTRATE_MEDIAN_GREEN:
        if previous_polar_rgb is None:
            raise ChronoPredictionError("temporal substrate decode requires a previous frame")
        previous = _green_delta_numpy(_require_polar_rgb(previous_polar_rgb, plan))
        values = values + previous
    elif predictor != PREDICTOR_SUBSTRATE_MEDIAN_GREEN:
        raise ChronoPredictionError(f"unsupported substrate predictor {predictor}")
    return _inverse_green_delta_numpy(values)


def encode_substrate_prediction_cuda(
    polar_frames: Any,
    plan: SubstratePredictionPlan,
    *,
    predictor: int,
    previous_polar_frames: Any | None = None,
    max_vram_mib: int,
) -> tuple[Any, dict[str, Any]]:
    """RTX batch encoder for the exact CPU-oracle prediction equation."""

    try:
        import numpy as np
        import torch
    except ImportError as error:
        raise ChronoPredictionError("CUDA substrate prediction requires NumPy and PyTorch") from error
    if not torch.cuda.is_available():
        raise ChronoPredictionError("PyTorch reports no CUDA device")
    source = np.asarray(polar_frames)
    if source.ndim != 3 or source.shape[1:] != (plan.pixel_count, 3) or source.dtype != np.uint8:
        raise ChronoPredictionError(
            f"CUDA polar frames must be uint8 with shape (N,{plan.pixel_count},3)"
        )
    if predictor == PREDICTOR_TEMPORAL_SUBSTRATE_MEDIAN_GREEN:
        previous_source = np.asarray(previous_polar_frames)
        if previous_source.shape != source.shape or previous_source.dtype != np.uint8:
            raise ChronoPredictionError("CUDA temporal previous-frame batch shape mismatch")
    elif predictor in (
        PREDICTOR_SUBSTRATE_MEDIAN_GREEN,
        PREDICTOR_CARTESIAN_MEDIAN_GREEN_SUBSTRATE_ORDER,
        PREDICTOR_CARTESIAN_MEDIAN_GREEN_LIFT_SUBSTRATE_ORDER,
    ):
        previous_source = None
    else:
        raise ChronoPredictionError(f"unsupported substrate predictor {predictor}")
    device = torch.device("cuda:0")
    properties = torch.cuda.get_device_properties(device)
    limit = int(max_vram_mib) * 1024 * 1024
    estimate = source.nbytes * 8 + plan.ram_bytes * 2
    if limit <= 0 or limit > int(properties.total_memory) or estimate > limit:
        raise ChronoPredictionError("CUDA substrate prediction workspace is invalid or too small")
    torch.cuda.reset_peak_memory_stats(device)

    def transform(array: Any) -> Any:
        tensor = torch.as_tensor(array, device=device)
        if predictor == PREDICTOR_CARTESIAN_MEDIAN_GREEN_LIFT_SUBSTRATE_ORDER:
            signed = tensor.to(torch.int16)
            cr = torch.bitwise_and(
                signed[:, :, 0] - signed[:, :, 1] + 128, 255
            ) - 128
            cb = torch.bitwise_and(
                signed[:, :, 2] - signed[:, :, 1] + 128, 255
            ) - 128
            quarter = torch.div(cr + cb, 4, rounding_mode="floor")
            result = torch.empty_like(tensor)
            result[:, :, 0] = torch.bitwise_and(
                signed[:, :, 1] + quarter, 255
            ).to(torch.uint8)
            result[:, :, 1] = torch.bitwise_and(cr, 255).to(torch.uint8)
            result[:, :, 2] = torch.bitwise_and(cb, 255).to(torch.uint8)
            return result
        result = torch.empty_like(tensor)
        result[:, :, 0] = tensor[:, :, 1]
        result[:, :, 1] = tensor[:, :, 0] - tensor[:, :, 1]
        result[:, :, 2] = tensor[:, :, 2] - tensor[:, :, 1]
        return result

    values = transform(source)
    if predictor in (
        PREDICTOR_CARTESIAN_MEDIAN_GREEN_SUBSTRATE_ORDER,
        PREDICTOR_CARTESIAN_MEDIAN_GREEN_LIFT_SUBSTRATE_ORDER,
    ):
        traversal = torch.as_tensor(
            plan.traversal.astype(np.int64), device=device
        )
        cartesian = torch.empty_like(values)
        cartesian[:, traversal, :] = values
        cartesian = cartesian.reshape(
            source.shape[0], plan.height, plan.width, 3
        )
        aa = torch.zeros_like(cartesian, dtype=torch.int16)
        bb = torch.zeros_like(cartesian, dtype=torch.int16)
        cc = torch.zeros_like(cartesian, dtype=torch.int16)
        aa[:, :, 1:, :] = cartesian[:, :, :-1, :]
        bb[:, 1:, :, :] = cartesian[:, :-1, :, :]
        cc[:, 1:, 1:, :] = cartesian[:, :-1, :-1, :]
        prediction = torch.maximum(
            torch.minimum(aa, bb),
            torch.minimum(torch.maximum(aa, bb), aa + bb - cc),
        ).to(torch.uint8)
        prediction[:, 0, 0, :] = 0
        prediction[:, 0, 1:, :] = cartesian[:, 0, :-1, :]
        prediction[:, 1:, 0, :] = cartesian[:, :-1, 0, :]
        residual_cartesian = (cartesian - prediction).reshape(
            source.shape[0], plan.pixel_count, 3
        )
        residual = residual_cartesian[:, traversal, :].permute(0, 2, 1).contiguous()
        result = residual.cpu().numpy()
        torch.cuda.synchronize(device)
        peak = float(torch.cuda.max_memory_allocated(device)) / (1024 * 1024)
        if peak > max_vram_mib:
            raise ChronoPredictionError("CUDA substrate prediction exceeded its workspace")
        return result, {
            "backend": "torch-cuda-cartesian-median-substrate-addressed",
            "device": torch.cuda.get_device_name(device),
            "compute_capability": list(torch.cuda.get_device_capability(device)),
            "batch_frames": int(source.shape[0]),
            "predictor": PREDICTOR_NAMES[predictor],
            "peak_mib": peak,
            "workspace_limit_mib": int(max_vram_mib),
            "integer_byte_exact": True,
        }
    if previous_source is not None:
        values = values - transform(previous_source)
    parent = torch.as_tensor(plan.parent.astype(np.int64), device=device)
    a_index = torch.as_tensor(plan.a.astype(np.int64), device=device)
    b_index = torch.as_tensor(plan.b.astype(np.int64), device=device)
    c_index = torch.as_tensor(plan.c.astype(np.int64), device=device)
    use = torch.as_tensor(plan.use_median, device=device)
    prediction = torch.zeros_like(values)
    has_parent = parent >= 0
    prediction[:, has_parent, :] = values[:, parent[has_parent], :]
    aa = values[:, a_index[use], :].to(torch.int16)
    bb = values[:, b_index[use], :].to(torch.int16)
    cc = values[:, c_index[use], :].to(torch.int16)
    median = torch.maximum(
        torch.minimum(aa, bb),
        torch.minimum(torch.maximum(aa, bb), aa + bb - cc),
    ).to(torch.uint8)
    prediction[:, use, :] = median
    residual = (values - prediction).permute(0, 2, 1).contiguous()
    result = residual.cpu().numpy()
    torch.cuda.synchronize(device)
    peak = float(torch.cuda.max_memory_allocated(device)) / (1024 * 1024)
    if peak > max_vram_mib:
        raise ChronoPredictionError("CUDA substrate prediction exceeded its workspace")
    return result, {
        "backend": "torch-cuda-substrate-neighborhood-prediction",
        "device": torch.cuda.get_device_name(device),
        "compute_capability": list(torch.cuda.get_device_capability(device)),
        "batch_frames": int(source.shape[0]),
        "predictor": PREDICTOR_NAMES[predictor],
        "peak_mib": peak,
        "workspace_limit_mib": int(max_vram_mib),
        "integer_byte_exact": True,
    }


__all__ = [
    "ChronoPredictionError",
    "PREDICTOR_NAMES",
    "PREDICTOR_CARTESIAN_MEDIAN_GREEN_LIFT_SUBSTRATE_ORDER",
    "PREDICTOR_CARTESIAN_MEDIAN_GREEN_SUBSTRATE_ORDER",
    "PREDICTOR_SUBSTRATE_MEDIAN_GREEN",
    "PREDICTOR_TEMPORAL_SUBSTRATE_MEDIAN_GREEN",
    "SubstratePredictionPlan",
    "build_substrate_prediction_plan",
    "decode_substrate_prediction_numpy",
    "encode_substrate_prediction_cuda",
    "encode_substrate_prediction_numpy",
]
