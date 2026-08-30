"""Read-only full-clip benchmark for reversible UGLUT2-addressed RGB codewords.

This is deliberately a temporary benchmark, not a production codec change.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import itertools
import json
import os
from pathlib import Path
import time

import av
import numpy as np

from ugts_kc3.chrono_codec import FRAME_HEADER_BYTES, _FRAME_HEADER
from ugts_kc3.chrono_container import inspect_ugtc4d_bytes
from ugts_kc3.chrono_entropy import (
    UGRICE_HEADER_BYTES,
    decode_adaptive_rice,
    encode_adaptive_rice,
)
from ugts_kc3.chrono_prediction import _decode_cartesian_prediction_numba
from ugts_kc3.chrono_substrate import (
    SubstrateTraversalRecipe,
    TRAVERSAL_NAMESPACE,
    _stable_id_numpy,
    derive_substrate_traversal,
)


SOURCE = Path(r"C:\Users\Tom\Videos\KasiaDansGedicht\sam_2353410928515192.mp4")
BASELINE = Path(
    r"C:\Tom Klootwijk super secret substrate club hush hush"
    r"\sam_2353410928515192.ugtoms-lossless.ugtc4d"
)
WORK = Path(__file__).resolve().parent
ORDER_PATH = WORK / "polar_codeword_order.npy"
CONFIG_PATH = WORK / "polar_codeword_config.json"
RESULT_PATH = WORK / "polar_codeword_bench_result.json"
BLOCK_SIZES = (65_536, 131_072)


COLOR_TRANSFORMS = {
    "baseline_green_luma_q4": ("green_lift", (1, 1, 2)),
    "green_delta": ("green_lift", (0, 0, 0)),
    "raw_rgb": ("identity", (0, 0, 0)),
    "ycocg_r": ("ycocg", (0, 0, 0)),
    "green_luma_q2": ("green_lift", (1, 1, 1)),
    "green_luma_q8": ("green_lift", (1, 1, 3)),
    "green_luma_709_q16": ("green_lift", (5, 2, 4)),
    "green_luma_3_1_q8": ("green_lift", (3, 1, 3)),
    "green_xor": ("green_xor", (0, 0, 0)),
    "gray_baseline_signal": ("gray_green_lift", (1, 1, 2)),
}


def _gray_encode(value: np.ndarray) -> np.ndarray:
    return value ^ (value >> np.uint8(1))


def _gray_decode(value: np.ndarray) -> np.ndarray:
    result = value.copy()
    result ^= result >> np.uint8(1)
    result ^= result >> np.uint8(2)
    result ^= result >> np.uint8(4)
    return result


def _signed_byte(value: np.ndarray) -> np.ndarray:
    lane = value.astype(np.int16)
    return ((lane + 128) & 255) - 128


def _green_lift(rgb: np.ndarray, wr: int, wb: int, shift: int) -> np.ndarray:
    signed = rgb.astype(np.int16)
    cr = ((signed[..., 0] - signed[..., 1] + 128) & 255) - 128
    cb = ((signed[..., 2] - signed[..., 1] + 128) & 255) - 128
    if shift:
        adjustment = np.floor_divide(wr * cr + wb * cb, 1 << shift)
    else:
        adjustment = np.zeros_like(cr)
    result = np.empty_like(rgb)
    result[..., 0] = (signed[..., 1] + adjustment) & 255
    result[..., 1] = cr & 255
    result[..., 2] = cb & 255
    return result


def _green_unlift(lanes: np.ndarray, wr: int, wb: int, shift: int) -> np.ndarray:
    raw = lanes.astype(np.int16)
    cr = ((raw[..., 1] + 128) & 255) - 128
    cb = ((raw[..., 2] + 128) & 255) - 128
    if shift:
        adjustment = np.floor_divide(wr * cr + wb * cb, 1 << shift)
    else:
        adjustment = np.zeros_like(cr)
    green = (raw[..., 0] - adjustment) & 255
    result = np.empty_like(lanes)
    result[..., 1] = green
    result[..., 0] = (green + cr) & 255
    result[..., 2] = (green + cb) & 255
    return result


def _ycocg(rgb: np.ndarray) -> np.ndarray:
    raw = rgb.astype(np.int16)
    co = ((raw[..., 0] - raw[..., 2] + 128) & 255) - 128
    t = (raw[..., 2] + np.floor_divide(co, 2)) & 255
    cg = ((raw[..., 1] - t + 128) & 255) - 128
    y = (t + np.floor_divide(cg, 2)) & 255
    result = np.empty_like(rgb)
    result[..., 0] = y
    result[..., 1] = co & 255
    result[..., 2] = cg & 255
    return result


def _inverse_ycocg(lanes: np.ndarray) -> np.ndarray:
    raw = lanes.astype(np.int16)
    co = ((raw[..., 1] + 128) & 255) - 128
    cg = ((raw[..., 2] + 128) & 255) - 128
    t = (raw[..., 0] - np.floor_divide(cg, 2)) & 255
    green = (cg + t) & 255
    blue = (t - np.floor_divide(co, 2)) & 255
    red = (co + blue) & 255
    result = np.empty_like(lanes)
    result[..., 0] = red
    result[..., 1] = green
    result[..., 2] = blue
    return result


def _transform_color(rgb: np.ndarray, name: str) -> np.ndarray:
    kind, parameters = COLOR_TRANSFORMS[name]
    if kind == "identity":
        return rgb.copy()
    if kind == "green_lift":
        return _green_lift(rgb, *parameters)
    if kind == "ycocg":
        return _ycocg(rgb)
    if kind == "green_xor":
        result = np.empty_like(rgb)
        result[..., 0] = rgb[..., 1]
        result[..., 1] = rgb[..., 0] ^ rgb[..., 1]
        result[..., 2] = rgb[..., 2] ^ rgb[..., 1]
        return result
    if kind == "gray_green_lift":
        return _gray_encode(_green_lift(rgb, *parameters))
    raise AssertionError(name)


def _inverse_color(lanes: np.ndarray, name: str) -> np.ndarray:
    kind, parameters = COLOR_TRANSFORMS[name]
    if kind == "identity":
        return lanes.copy()
    if kind == "green_lift":
        return _green_unlift(lanes, *parameters)
    if kind == "ycocg":
        return _inverse_ycocg(lanes)
    if kind == "green_xor":
        result = np.empty_like(lanes)
        result[..., 1] = lanes[..., 0]
        result[..., 0] = lanes[..., 1] ^ lanes[..., 0]
        result[..., 2] = lanes[..., 2] ^ lanes[..., 0]
        return result
    if kind == "gray_green_lift":
        return _green_unlift(_gray_decode(lanes), *parameters)
    raise AssertionError(name)


def _median_residual(values: np.ndarray) -> np.ndarray:
    a = np.zeros_like(values, dtype=np.int16)
    b = np.zeros_like(values, dtype=np.int16)
    c = np.zeros_like(values, dtype=np.int16)
    a[:, 1:] = values[:, :-1]
    b[1:, :] = values[:-1, :]
    c[1:, 1:] = values[:-1, :-1]
    low = np.minimum(a, b)
    high = np.maximum(a, b)
    prediction = np.maximum(low, np.minimum(high, a + b - c)).astype(np.uint8)
    prediction[0, 0] = 0
    prediction[0, 1:] = values[0, :-1]
    prediction[1:, 0] = values[:-1, 0]
    return values - prediction


def _bit_transpose_lane(data: np.ndarray) -> np.ndarray:
    if data.size % 8:
        raise AssertionError("benchmark raster lane is not divisible by eight")
    groups = data.reshape(-1, 8)
    bits = np.unpackbits(groups[..., None], axis=2, bitorder="little")
    return np.packbits(bits.transpose(0, 2, 1), axis=2, bitorder="little").reshape(-1)


def _nibble_transpose(data: np.ndarray) -> np.ndarray:
    if data.size % 2:
        raise AssertionError("benchmark raster lane is not divisible by two")
    pairs = data.reshape(-1, 2)
    result = np.empty_like(pairs)
    result[:, 0] = (pairs[:, 0] & 15) | ((pairs[:, 1] & 15) << 4)
    result[:, 1] = (pairs[:, 0] >> 4) | (pairs[:, 1] & 0xF0)
    return result.reshape(-1)


def _bitplane24_pack(polar: np.ndarray) -> np.ndarray:
    if polar.shape[0] % 8:
        raise AssertionError("benchmark codeword count is not divisible by eight")
    groups = polar.reshape(-1, 8, 3)
    bits = np.unpackbits(groups[..., None], axis=3, bitorder="little")
    return np.packbits(
        bits.transpose(0, 3, 2, 1), axis=3, bitorder="little"
    ).reshape(-1)


def _bitplane24_unpack(data: np.ndarray) -> np.ndarray:
    groups = data.reshape(-1, 8, 3)
    bits = np.unpackbits(groups[..., None], axis=3, bitorder="little")
    return np.packbits(
        bits.transpose(0, 3, 2, 1), axis=3, bitorder="little"
    ).reshape(-1, 3)


def _zigzag_encode(value: np.ndarray) -> np.ndarray:
    signed = _signed_byte(value)
    return ((signed << 1) ^ (signed >> 7)).astype(np.uint8)


def _zigzag_decode(value: np.ndarray) -> np.ndarray:
    raw = value.astype(np.int16)
    signed = (raw >> 1) ^ -(raw & 1)
    return (signed & 255).astype(np.uint8)


def _address_mask(config: dict, order: np.ndarray) -> np.ndarray:
    count = order.size
    polar_address = np.arange(count, dtype=np.uint64)
    lineage = _stable_id_numpy(
        int(config["session_seed"]), TRAVERSAL_NAMESPACE, polar_address, np
    )
    polar_mask = np.empty((count, 3), dtype=np.uint8)
    polar_mask[:, 0] = lineage & np.uint64(255)
    polar_mask[:, 1] = (lineage >> np.uint64(8)) & np.uint64(255)
    polar_mask[:, 2] = (lineage >> np.uint64(16)) & np.uint64(255)
    cartesian = np.empty_like(polar_mask)
    cartesian[order] = polar_mask
    return cartesian.reshape(int(config["height"]), int(config["width"]), 3)


def _candidate_spec(name: str) -> tuple[str, str, tuple[int, int, int]]:
    if name.startswith("q709_perm_"):
        return (
            "green_luma_709_q16",
            "planar",
            tuple(int(v) for v in name.removeprefix("q709_perm_")),
        )
    if name.startswith("perm_"):
        return "baseline_green_luma_q4", "planar", tuple(int(v) for v in name[5:])
    if name.startswith("baseline_layout_"):
        return "baseline_green_luma_q4", name.removeprefix("baseline_layout_"), (0, 1, 2)
    if name == "baseline_residual_gray":
        return "baseline_green_luma_q4", "residual_gray", (0, 1, 2)
    if name == "baseline_residual_zigzag":
        return "baseline_green_luma_q4", "residual_zigzag", (0, 1, 2)
    if name == "baseline_residual_delta":
        return "baseline_green_luma_q4", "residual_delta", (0, 1, 2)
    if name == "baseline_residual_xor":
        return "baseline_green_luma_q4", "residual_xor", (0, 1, 2)
    if name == "address_xor_baseline":
        return "baseline_green_luma_q4", "address_xor", (0, 1, 2)
    return name, "planar", (0, 1, 2)


def _pack_residual(
    residual: np.ndarray,
    order: np.ndarray,
    layout: str,
    permutation: tuple[int, int, int],
) -> bytes:
    polar = residual.reshape(-1, 3)[order]
    if layout == "planar":
        return np.ascontiguousarray(polar[:, permutation].T).tobytes()
    if layout == "interleaved":
        return np.ascontiguousarray(polar).tobytes()
    if layout == "nibble_lane":
        return b"".join(_nibble_transpose(polar[:, lane]).tobytes() for lane in range(3))
    if layout == "bitplane_lane":
        return b"".join(_bit_transpose_lane(polar[:, lane]).tobytes() for lane in range(3))
    if layout == "bitplane24":
        return _bitplane24_pack(polar).tobytes()
    if layout == "residual_gray":
        return np.ascontiguousarray(_gray_encode(polar).T).tobytes()
    if layout == "residual_zigzag":
        return np.ascontiguousarray(_zigzag_encode(polar).T).tobytes()
    if layout == "residual_delta":
        lifted = np.empty_like(polar)
        lifted[:, 0] = polar[:, 0]
        lifted[:, 1] = polar[:, 1] - polar[:, 0]
        lifted[:, 2] = polar[:, 2] - polar[:, 0]
        return np.ascontiguousarray(lifted.T).tobytes()
    if layout == "residual_xor":
        lifted = np.empty_like(polar)
        lifted[:, 0] = polar[:, 0]
        lifted[:, 1] = polar[:, 1] ^ polar[:, 0]
        lifted[:, 2] = polar[:, 2] ^ polar[:, 0]
        return np.ascontiguousarray(lifted.T).tobytes()
    raise AssertionError(layout)


def _unpack_residual(
    raw: bytes,
    order: np.ndarray,
    height: int,
    width: int,
    layout: str,
    permutation: tuple[int, int, int],
) -> np.ndarray:
    count = order.size
    data = np.frombuffer(raw, dtype=np.uint8)
    if layout == "planar":
        selected = data.reshape(3, count).T
        polar = np.empty_like(selected)
        polar[:, permutation] = selected
    elif layout == "interleaved":
        polar = data.reshape(count, 3)
    elif layout == "nibble_lane":
        polar = np.stack(
            [_nibble_transpose(data[lane * count : (lane + 1) * count]) for lane in range(3)],
            axis=1,
        )
    elif layout == "bitplane_lane":
        polar = np.stack(
            [_bit_transpose_lane(data[lane * count : (lane + 1) * count]) for lane in range(3)],
            axis=1,
        )
    elif layout == "bitplane24":
        polar = _bitplane24_unpack(data)
    elif layout in ("residual_gray", "residual_zigzag", "residual_delta", "residual_xor"):
        coded = data.reshape(3, count).T
        if layout == "residual_gray":
            polar = _gray_decode(coded)
        elif layout == "residual_zigzag":
            polar = _zigzag_decode(coded)
        else:
            polar = np.empty_like(coded)
            polar[:, 0] = coded[:, 0]
            if layout == "residual_delta":
                polar[:, 1] = coded[:, 1] + coded[:, 0]
                polar[:, 2] = coded[:, 2] + coded[:, 0]
            else:
                polar[:, 1] = coded[:, 1] ^ coded[:, 0]
                polar[:, 2] = coded[:, 2] ^ coded[:, 0]
    else:
        raise AssertionError(layout)
    cartesian = np.empty((count, 3), dtype=np.uint8)
    cartesian[order] = polar
    return cartesian.reshape(height, width, 3)


def _run_candidate(name: str) -> dict:
    started = time.perf_counter()
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    order = np.load(ORDER_PATH).astype(np.int64, copy=False)
    height = int(config["height"])
    width = int(config["width"])
    color_name, layout, permutation = _candidate_spec(name)
    address_mask = _address_mask(config, order) if layout == "address_xor" else None
    if layout == "address_xor":
        layout = "planar"

    total = 0
    inner_total = 0
    block_counts = {str(size): 0 for size in BLOCK_SIZES}
    source_hash = hashlib.sha256()
    replay_hash = hashlib.sha256()
    frame_sizes: list[int] = []
    frames = 0
    with av.open(str(SOURCE), mode="r") as container:
        video = container.streams.video[0]
        for ordinal, decoded in enumerate(container.decode(video)):
            rgb = decoded.to_ndarray(format="rgb24")
            if rgb.shape != (height, width, 3) or rgb.dtype != np.uint8:
                raise AssertionError("accepted source decode changed shape/type")
            lanes = _transform_color(rgb, color_name)
            if address_mask is not None:
                lanes ^= address_mask
            residual = _median_residual(lanes)
            packed = _pack_residual(residual, order, layout, permutation)
            encoded = [encode_adaptive_rice(packed, block_bytes=size) for size in BLOCK_SIZES]
            selected = min(zip(BLOCK_SIZES, encoded), key=lambda pair: (len(pair[1]), pair[0]))
            block_size, stream = selected
            block_counts[str(block_size)] += 1
            recovered_packed = decode_adaptive_rice(stream, require_canonical=False)
            if recovered_packed != packed:
                raise AssertionError(f"UGRICE1 replay mismatch at frame {ordinal}")
            recovered_residual = _unpack_residual(
                recovered_packed, order, height, width, layout, permutation
            )
            recovered_lanes = _decode_cartesian_prediction_numba(recovered_residual)
            if address_mask is not None:
                recovered_lanes ^= address_mask
            recovered_rgb = _inverse_color(recovered_lanes, color_name)
            if not np.array_equal(recovered_rgb, rgb):
                raise AssertionError(f"RGB round trip mismatch at frame {ordinal}")
            source_hash.update(np.ascontiguousarray(rgb).tobytes())
            replay_hash.update(np.ascontiguousarray(recovered_rgb).tobytes())
            size = len(stream)
            total += size
            inner_total += size - UGRICE_HEADER_BYTES
            frame_sizes.append(size)
            frames += 1

    if frames != int(config["frames"]) or source_hash.digest() != replay_hash.digest():
        raise AssertionError("full-clip replay receipt mismatch")
    result = {
        "candidate": name,
        "color_transform": color_name,
        "layout": layout,
        "lane_permutation": list(permutation),
        "frames": frames,
        "ugrice1_stream_bytes": total,
        "ugrice1_inner_payload_bytes": inner_total,
        "block_size_frame_counts": block_counts,
        "minimum_frame_bytes": min(frame_sizes),
        "maximum_frame_bytes": max(frame_sizes),
        "source_rgb_concat_sha256": source_hash.hexdigest(),
        "replayed_rgb_concat_sha256": replay_hash.hexdigest(),
        "exact_round_trip": True,
        "elapsed_seconds": time.perf_counter() - started,
        "process_id": os.getpid(),
    }
    return result


def _prepare() -> dict:
    raw = BASELINE.read_bytes()
    inspected = inspect_ugtc4d_bytes(raw)
    lut = inspected.sections_of_kind("UGLUT2")[0].logical()
    recipe = SubstrateTraversalRecipe.from_bytes(
        inspected.sections_of_kind("TRAVERS")[0].logical(),
        uglut2_bytes=lut,
        verify_derived_traversal=True,
    )
    order = derive_substrate_traversal(recipe, lut).astype(np.uint32, copy=False)
    np.save(ORDER_PATH, order)

    frame_sections = inspected.sections_of_kind("FRAME")
    current_payloads = []
    predictors: dict[str, int] = {}
    for section in frame_sections:
        fields = _FRAME_HEADER.unpack_from(section.stored)
        predictor = str(fields[6])
        payload_bytes = int(fields[10])
        if len(section.stored) != FRAME_HEADER_BYTES + payload_bytes:
            raise AssertionError("baseline frame length mismatch")
        current_payloads.append(payload_bytes)
        predictors[predictor] = predictors.get(predictor, 0) + 1
    config = {
        "width": recipe.width,
        "height": recipe.height,
        "frames": inspected.header.frame_count,
        "root_seed": recipe.root_seed,
        "recipe_seed": recipe.recipe_seed,
        "session_seed": recipe.session_seed,
        "traversal_sha256": recipe.traversal_sha256,
        "baseline_file_bytes": len(raw),
        "baseline_selected_ugrice1_stream_bytes": sum(current_payloads),
        "baseline_measured_non_payload_bytes": len(raw) - sum(current_payloads),
        "baseline_predictor_counts": predictors,
        "source_bytes": SOURCE.stat().st_size,
        "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
    }
    CONFIG_PATH.write_text(json.dumps(config, sort_keys=True), encoding="utf-8")
    return config


def main() -> None:
    started = time.perf_counter()
    config = _prepare()
    candidates = list(COLOR_TRANSFORMS)
    candidates.extend(
        "perm_" + "".join(str(lane) for lane in permutation)
        for permutation in itertools.permutations(range(3))
        if permutation != (0, 1, 2)
    )
    candidates.extend(
        (
            "baseline_layout_interleaved",
            "baseline_layout_nibble_lane",
            "baseline_layout_bitplane_lane",
            "baseline_layout_bitplane24",
            "baseline_residual_gray",
            "baseline_residual_zigzag",
            "baseline_residual_delta",
            "baseline_residual_xor",
            "address_xor_baseline",
        )
    )
    results = []
    failures = []
    workers = min(4, os.cpu_count() or 1)
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_run_candidate, name): name for name in candidates}
        for future in as_completed(futures):
            name = futures[future]
            try:
                result = future.result()
            except Exception as error:
                failures.append({"candidate": name, "error": repr(error)})
                print("FAIL", name, repr(error), flush=True)
            else:
                results.append(result)
                print(
                    "PASS",
                    name,
                    result["ugrice1_stream_bytes"],
                    f"{result['elapsed_seconds']:.2f}s",
                    flush=True,
                )
    ordered = sorted(results, key=lambda item: (item["ugrice1_stream_bytes"], item["candidate"]))
    for item in ordered:
        item["delta_vs_all_p13_bytes"] = item["ugrice1_stream_bytes"] - next(
            result["ugrice1_stream_bytes"]
            for result in results
            if result["candidate"] == "baseline_green_luma_q4"
        )
        item["delta_vs_current_selected_bytes"] = (
            item["ugrice1_stream_bytes"]
            - config["baseline_selected_ugrice1_stream_bytes"]
        )
        item["projected_ugtc4d_bytes_constant_measured_overhead"] = (
            item["ugrice1_stream_bytes"]
            + config["baseline_measured_non_payload_bytes"]
        )
    output = {
        "schema": "ugtoms-polar-codeword-benchmark-0.1",
        "benchmark_scope": (
            "full 229-frame accepted PyAV RGB24 decode; exact reversible 24-bit "
            "codewords addressed by the existing seed-regenerated UGLUT2 traversal"
        ),
        "config": config,
        "workers": workers,
        "candidate_count": len(candidates),
        "results": ordered,
        "failures": failures,
        "elapsed_seconds": time.perf_counter() - started,
    }
    RESULT_PATH.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(output, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
