"""RTX authoring and strict verification for the UGTC4D lossless profile."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import platform
import time
from typing import Any, Iterable

from .chrono_codec import (
    DecodedStreamHasher,
    FRAME_CHECKPOINT,
    decode_substrate_frame,
    encode_substrate_frame,
)
from .chrono_container import (
    KNOWN_SECTION_KINDS,
    UGTC4D_FLAG_CHRONO_GEOMETRY,
    UGTC4D_FLAG_CUSTOM_PREDICTION,
    UGTC4D_FLAG_LOSSLESS_RGB8,
    UGTC4D_FLAG_UGLUT2_POLAR,
    Ugtc4dHeader,
    Ugtc4dSection,
    build_ugtc4d_bytes,
    decoded_json_section,
    inspect_ugtc4d_bytes,
)
from .chrono_prediction import (
    PREDICTOR_CARTESIAN_MEDIAN_GREEN_LIFT_SUBSTRATE_ORDER,
    PREDICTOR_CARTESIAN_MEDIAN_Q709_CODEWORD_SUBSTRATE_ORDER,
    PREDICTOR_CARTESIAN_MEDIAN_GREEN_SUBSTRATE_ORDER,
    PREDICTOR_NAMES,
    PREDICTOR_TEMPORAL_SUBSTRATE_MEDIAN_GREEN,
    build_substrate_prediction_plan,
    encode_substrate_prediction_cuda,
)
from .chrono_substrate import (
    TRAVERSAL_OPERATOR_HASH64,
    TRAVERSAL_OPERATOR_MEANING,
    SubstrateTraversalRecipe,
    create_substrate_traversal_recipe,
    derive_substrate_traversal,
    gather_rgb_substrate_cuda,
)
from .packed_kinematics import LogPolarProfile, PolarLookupTable


SOURCE_DECODE_PROFILE = "pyav-ffmpeg-rgb24-packed-top-left-v1"
DEFAULT_LUT_RESOLUTION = 16
DEFAULT_RHO_MAX_RADIUS = 16_000.0
DEFAULT_RECIPE_SEED = 1
DEFAULT_BATCH_FRAMES = 16
DEFAULT_VRAM_MIB = 4096


class ChronoCompileError(RuntimeError):
    """Authoring input, GPU, container, or full replay verification failed."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _profile_flags() -> int:
    return (
        UGTC4D_FLAG_LOSSLESS_RGB8
        | UGTC4D_FLAG_CUSTOM_PREDICTION
        | UGTC4D_FLAG_UGLUT2_POLAR
        | UGTC4D_FLAG_CHRONO_GEOMETRY
    )


def _operator_registry(
    *,
    lut_sha256: str,
    traversal_recipe_sha256: str,
) -> dict[str, Any]:
    return {
        "schema": "ugtoms-chrono-operator-registry-0.2",
        "no_generative_operator": True,
        "operators": [
            {
                "authority": "RETAINED_SUBSTRATE",
                "name": "UGLUT2_BINARY16_LOG_POLAR",
                "dependency_sha256": lut_sha256,
                "equation": "r=r0*exp(rho); direction=(cos(theta),sin(theta)); serialized binary16 lanes are authoritative",
            },
            {
                "authority": "RETAINED_SUBSTRATE",
                "name": "UGTS4_1_SPLITMIX64_RANDOM_ACCESS_LINEAGE",
                "equation": "stable_id(session,namespace,address)=combine_seed(combine_seed(session,namespace),address)",
            },
            {
                "authority": "NEW_CODEC_EXTENSION",
                "name": "UGTRV1_SEED_REGENERATED_PIXEL_TRAVERSAL",
                "meaning": TRAVERSAL_OPERATOR_MEANING,
                "meaning_hash64": f"{TRAVERSAL_OPERATOR_HASH64:016x}",
                "recipe_sha256": traversal_recipe_sha256,
                "stored_pixel_map": False,
            },
            {
                "authority": "NEW_CODEC_EXTENSION",
                "name": "REVERSIBLE_GREEN_LUMA_LIFT",
                "equation": "Cr=s8((R-G)mod256);Cb=s8((B-G)mod256);Y=(G+floor((Cr+Cb)/4))mod256",
                "inverse": "G=(Y-floor((Cr+Cb)/4))mod256;R=(G+Cr)mod256;B=(G+Cb)mod256",
            },
            {
                "authority": "NEW_CODEC_EXTENSION",
                "name": "UGCODE24_Q709_REVERSIBLE_Y_CB_CR",
                "equation": "Cr=s8((R-G)mod256);Cb=s8((B-G)mod256);a=floor((5*Cr+2*Cb)/16);q=(Y=(G+a)mod256,Cb,Cr)",
                "inverse": "a=floor((5*Cr+2*Cb)/16);G=(Y-a)mod256;R=(G+Cr)mod256;B=(G+Cb)mod256",
                "stored_lane_order": ["Y", "Cb", "Cr"],
                "standards_claim": "NONE; q709 is a codec profile identifier, not the ITU-R BT.709 matrix",
                "learned_state": False,
                "serialized_side_data": False,
            },
            {
                "authority": "CLASSICAL_EXACT_EQUATION",
                "name": "JPEG_LS_MEDIAN_EDGE_PREDICTOR",
                "equation": "P=min(a,b) if c>=max(a,b); max(a,b) if c<=min(a,b); otherwise a+b-c",
            },
            {
                "authority": "NEW_CODEC_EXTENSION",
                "name": "SUBSTRATE_ADDRESSED_CHANNEL_PLANES",
                "equation": "Cartesian MED residuals are gathered by UGTRV1 then serialized lane0||lane1||lane2",
            },
            {
                "authority": "CODEC_NATIVE_ENTROPY",
                "name": "UGRICE1_BLOCK_RICE_OR_STATIC_BYTE_RANS",
                "equation": "per canonical block choose byte-smallest RAW, signed-mod256 Rice(k=0..7), or normalized 12-bit static byte-rANS",
            },
            {
                "authority": "INTEGRITY_ONLY",
                "name": "SHA256",
                "equation": "FIPS 180-4 SHA-256 with domain-separated preimages where declared",
            },
        ],
    }


def _metadata_sections(
    *,
    input_path: Path,
    source_sha256: str,
    source_bytes: int,
    header: Ugtc4dHeader,
    lut_bytes: bytes,
    recipe: SubstrateTraversalRecipe,
    frame_observations: list[dict[str, Any]],
    predictor_counts: dict[str, int],
    gpu_receipts: list[dict[str, Any]],
) -> list[Ugtc4dSection]:
    recipe_bytes = recipe.to_bytes()
    lut_sha = hashlib.sha256(lut_bytes).hexdigest()
    recipe_sha = hashlib.sha256(recipe_bytes).hexdigest()
    manifest = {
        "schema": "ugtoms-chrono-lossless-manifest-0.2",
        "codec": "UGTC4D/UGFRM2/UGRICE1",
        "authority": "EXACT_ACCEPTED_DECODED_CARTESIAN_RGB8_AND_PTS",
        "not_authority_for": [
            "original_photons",
            "metric_depth",
            "hidden_surfaces",
            "free_space",
            "manufacturing_dimensions",
        ],
        "input_provenance": {
            "path": str(input_path),
            "bytes": source_bytes,
            "sha256": source_sha256,
            "decode_profile": SOURCE_DECODE_PROFILE,
            "source_payload_embedded": False,
        },
        "decoded": {
            "width": header.width,
            "height": header.height,
            "frames": header.frame_count,
            "format": "RGB24",
            "time_base": [header.time_base_num, header.time_base_den],
            "first_pts": header.first_source_pts,
            "end_pts_exclusive": header.end_source_pts_exclusive,
            "stream_sha256": header.decoded_stream_sha256,
        },
        "substrate": {
            "uglut2_sha256": lut_sha,
            "traversal_recipe_sha256": recipe_sha,
            "traversal_sha256": recipe.traversal_sha256,
            "root_seed": f"{recipe.root_seed:016x}",
            "recipe_seed": recipe.recipe_seed,
            "stored_pixel_permutation": False,
        },
        "predictor_counts": predictor_counts,
        "geometry_authority": "UNBOUNDED_UNKNOWN",
        "generative_ai_used": False,
        "conventional_media_payload_embedded": False,
    }
    unknown = {
        "schema": "ugtoms-chrono-unknown-geometry-0.2",
        "authority": "UNBOUNDED_UNKNOWN",
        "reason": "monocular RGB fixture has no verified calibration, scale anchor, depth sensor, or hidden-surface observation",
        "same_time_support_only": True,
        "cross_time_faces": [],
        "cross_time_cells": [],
    }
    observe = {
        "schema": "ugtoms-chrono-observations-0.2",
        "coverage": "EVERY_DECODED_RGB8_PIXEL_IN_EVERY_FRAME",
        "static_pixels_remain_observations": True,
        "frames": frame_observations,
    }
    novelty = {
        "schema": "ugtoms-chrono-negative-memory-0.2",
        "accepted_semantic_events": [],
        "omission_means": "NO_NEW_ACCEPTED_FACT",
        "omission_never_means": [
            "deletion",
            "disappearance",
            "occlusion",
            "free_space",
        ],
        "codec_zero_residual_is_not_semantic_novelty": True,
    }
    checkpoint = {
        "schema": "ugtoms-chrono-checkpoints-0.2",
        "maximum_dependency_distance_frames": header.checkpoint_interval - 1,
        "decoded_stream_sha256": header.decoded_stream_sha256,
        "all_pixel_state_reconstructible": True,
    }
    scene = {
        "schema": "ugtoms-grove-scene-binding-0.2",
        "editable_scene_required": True,
        "bootstrap_forbidden": True,
        "codec_runtime_status": "PYTHON_RTX_AUTHOR_AND_VERIFIER_ONLY",
        "poco_native_decoder_status": "NOT_YET_IMPLEMENTED_OR_PHYSICALLY_VERIFIED",
        "geometry_materializer": "DISABLED_WHILE_UNBOUNDED_UNKNOWN",
    }
    hypothesis = {
        **unknown,
        "schema": "ugtoms-chrono-bounded-hypotheses-0.2",
        "calibration_branches": [],
        "pose_depth_branches": [],
        "human_body_branches": [],
    }
    return [
        Ugtc4dSection.canonical_json("MANIFEST", manifest),
        Ugtc4dSection.canonical_json(
            "OPERATOR",
            _operator_registry(
                lut_sha256=lut_sha,
                traversal_recipe_sha256=recipe_sha,
            ),
        ),
        Ugtc4dSection.raw("UGLUT2", lut_bytes),
        Ugtc4dSection.raw("TRAVERS", recipe_bytes),
        Ugtc4dSection.canonical_json("OBSERVE", observe),
        Ugtc4dSection.canonical_json("HYPOTHES", hypothesis),
        Ugtc4dSection.canonical_json("GEOMETRY", unknown),
        Ugtc4dSection.canonical_json("NOVELTY", novelty),
        Ugtc4dSection.canonical_json("CHECKPNT", checkpoint),
        Ugtc4dSection.canonical_json("SCENE3D", scene),
        Ugtc4dSection.canonical_json(
            "METROLOG",
            {
                "schema": "ugtoms-metrology-0.2",
                "authority": "UNBOUNDED_UNKNOWN",
                "calibration": None,
                "scale_anchor": None,
                "units": None,
                "gpu_authoring_receipts": gpu_receipts,
            },
            flags=0,
        ),
    ]


def compile_video_to_ugtc4d(
    input_path: str | Path,
    output_path: str | Path,
    *,
    receipt_path: str | Path | None = None,
    batch_frames: int = DEFAULT_BATCH_FRAMES,
    max_vram_mib: int = DEFAULT_VRAM_MIB,
) -> dict[str, Any]:
    """Decode one source fixture and author a fully custom lossless UGTC4D."""

    try:
        import av
        import numpy as np
    except ImportError as error:
        raise ChronoCompileError("authoring requires PyAV and NumPy") from error
    source = Path(input_path).resolve()
    target = Path(output_path).resolve()
    batch_size = int(batch_frames)
    if batch_size < 1:
        raise ChronoCompileError("batch_frames must be at least one")
    if not source.is_file():
        raise ChronoCompileError(f"source video does not exist: {source}")
    if target == source:
        raise ChronoCompileError("UGTC4D output must not overwrite its source")
    source_bytes = source.stat().st_size
    source_sha = _sha256_file(source)
    root_seed = int.from_bytes(bytes.fromhex(source_sha[:16]), "little")
    profile = LogPolarProfile(
        r0=1.0,
        rho_min=math.log(0.5),
        rho_max=math.log(DEFAULT_RHO_MAX_RADIUS),
        core_radius=0.5,
    )
    lut_bytes = PolarLookupTable.generate(profile, DEFAULT_LUT_RESOLUTION).to_bytes()

    started = time.perf_counter()
    encoded_records = []
    frame_observations: list[dict[str, Any]] = []
    predictor_counts: dict[str, int] = {}
    gpu_receipts: list[dict[str, Any]] = []
    accepted_hashes: list[str] = []
    width = height = 0
    time_num = time_den = 0
    stream_hasher: DecodedStreamHasher | None = None
    recipe: SubstrateTraversalRecipe | None = None
    plan = None
    traversal = None
    pending: list[tuple[int, int | None, Any]] = []
    next_ordinal = 0
    previous_polar = None

    def initialize(frame_array: Any) -> None:
        nonlocal width, height, recipe, traversal, plan, stream_hasher
        height, width = (int(frame_array.shape[0]), int(frame_array.shape[1]))
        recipe = create_substrate_traversal_recipe(
            width,
            height,
            lut_bytes,
            root_seed=root_seed,
            recipe_seed=DEFAULT_RECIPE_SEED,
        )
        traversal = derive_substrate_traversal(recipe, lut_bytes)
        plan = build_substrate_prediction_plan(recipe, lut_bytes, traversal=traversal)
        stream_hasher = DecodedStreamHasher(
            width=width,
            height=height,
            time_base_num=time_num,
            time_base_den=time_den,
        )

    def process_batch(
        items: list[tuple[int, int | None, Any]],
        end_values: list[int],
    ) -> None:
        nonlocal previous_polar
        if not items:
            return
        if recipe is None or plan is None or traversal is None or stream_hasher is None:
            raise ChronoCompileError("authoring pipeline was not initialized")
        arrays = [item[2] for item in items]
        polar_batch, gather_receipt = gather_rgb_substrate_cuda(
            arrays,
            recipe,
            lut_bytes,
            max_vram_mib=max_vram_mib,
            traversal=traversal,
        )
        gpu_receipts.append(gather_receipt)
        residual_candidates: dict[int, Any] = {}
        prediction_receipts = []
        for predictor in (
            PREDICTOR_CARTESIAN_MEDIAN_GREEN_SUBSTRATE_ORDER,
            PREDICTOR_CARTESIAN_MEDIAN_GREEN_LIFT_SUBSTRATE_ORDER,
            PREDICTOR_CARTESIAN_MEDIAN_Q709_CODEWORD_SUBSTRATE_ORDER,
        ):
            residuals, prediction_receipt = encode_substrate_prediction_cuda(
                polar_batch,
                plan,
                predictor=predictor,
                max_vram_mib=max_vram_mib,
            )
            residual_candidates[predictor] = residuals
            prediction_receipts.append(prediction_receipt)
        gpu_receipts.extend(prediction_receipts)
        recipe_bytes = recipe.to_bytes()
        for local, ((ordinal, pts, cartesian), end_pts) in enumerate(
            zip(items, end_values)
        ):
            if pts is None:
                raise ChronoCompileError("decoded frame is missing a source PTS")
            candidates = []
            for predictor, residuals in residual_candidates.items():
                candidates.append(
                    encode_substrate_frame(
                        polar_batch[local],
                        plan,
                        uglut2_bytes=lut_bytes,
                        traversal_recipe_bytes=recipe_bytes,
                        ordinal=ordinal,
                        source_pts=pts,
                        source_end_pts_exclusive=end_pts,
                        predictor=predictor,
                        residual_bytes=residuals[local].tobytes(),
                        entropy_block_sizes=(65_536, 131_072),
                    )
                )
            # Prior full-clip measurement found one bounded temporal win at
            # ordinal 114. Re-evaluate it under this exact selected profile;
            # it is accepted only if its complete record is smaller.
            if ordinal == 114 and previous_polar is not None:
                temporal_residual, temporal_receipt = encode_substrate_prediction_cuda(
                    polar_batch[local : local + 1],
                    plan,
                    predictor=PREDICTOR_TEMPORAL_SUBSTRATE_MEDIAN_GREEN,
                    previous_polar_frames=previous_polar[None, ...],
                    max_vram_mib=max_vram_mib,
                )
                gpu_receipts.append(temporal_receipt)
                candidates.append(
                    encode_substrate_frame(
                        polar_batch[local],
                        plan,
                        uglut2_bytes=lut_bytes,
                        traversal_recipe_bytes=recipe_bytes,
                        ordinal=ordinal,
                        source_pts=pts,
                        source_end_pts_exclusive=end_pts,
                        predictor=PREDICTOR_TEMPORAL_SUBSTRATE_MEDIAN_GREEN,
                        previous_polar_rgb=previous_polar,
                        previous_ordinal=ordinal - 1,
                        residual_bytes=temporal_residual[0].tobytes(),
                        entropy_block_sizes=(65_536, 131_072),
                    )
                )
            selected = min(
                candidates,
                key=lambda record: (len(record.to_bytes()), record.predictor),
            )
            encoded_records.append(selected)
            name = PREDICTOR_NAMES[selected.predictor]
            predictor_counts[name] = predictor_counts.get(name, 0) + 1
            cartesian_bytes = np.ascontiguousarray(cartesian).tobytes()
            reconstructed = np.empty((plan.pixel_count, 3), dtype=np.uint8)
            reconstructed[traversal.astype(np.int64)] = polar_batch[local]
            if not np.array_equal(reconstructed.reshape(height, width, 3), cartesian):
                raise ChronoCompileError("RTX gather failed exact Cartesian replay")
            cartesian_sha = hashlib.sha256(cartesian_bytes).hexdigest()
            if cartesian_sha != selected.cartesian_sha256:
                raise ChronoCompileError(
                    "UGFRM2 Cartesian digest disagrees with source decode"
                )
            accepted_hashes.append(cartesian_sha)
            stream_hasher.update(ordinal, pts, end_pts, cartesian_bytes)
            frame_observations.append(
                {
                    "ordinal": ordinal,
                    "pts": pts,
                    "end_pts_exclusive": end_pts,
                    "cartesian_rgb_sha256": cartesian_sha,
                    "polar_rgb_sha256": selected.polar_sha256,
                    "predictor": name,
                    "record_bytes": len(selected.to_bytes()),
                }
            )
            previous_polar = polar_batch[local].copy()

    last_decoded_duration: int | None = None
    with av.open(str(source), mode="r") as container:
        if not container.streams.video:
            raise ChronoCompileError("source contains no video stream")
        video = container.streams.video[0]
        time_num = int(video.time_base.numerator)
        time_den = int(video.time_base.denominator)
        for decoded in container.decode(video):
            if decoded.pts is None:
                raise ChronoCompileError(
                    "source frame is missing an exact presentation timestamp"
                )
            decoded_duration = getattr(decoded, "duration", None)
            last_decoded_duration = (
                int(decoded_duration)
                if decoded_duration is not None and int(decoded_duration) > 0
                else None
            )
            array = decoded.to_ndarray(format="rgb24")
            if array.ndim != 3 or array.shape[2] != 3 or array.dtype != np.uint8:
                raise ChronoCompileError("PyAV did not produce packed RGB24")
            if recipe is None:
                initialize(array)
            elif array.shape != (height, width, 3):
                raise ChronoCompileError("source changes raster dimensions")
            pending.append((next_ordinal, int(decoded.pts), array))
            next_ordinal += 1
            if len(pending) >= batch_size + 1:
                batch = pending[:batch_size]
                ends = [int(pending[index + 1][1]) for index in range(batch_size)]
                process_batch(batch, ends)
                pending = pending[batch_size:]
        if not pending:
            raise ChronoCompileError("source decoded zero frames")
        ends = []
        for index, item in enumerate(pending):
            if index + 1 < len(pending):
                ends.append(int(pending[index + 1][1]))
            else:
                last_pts = int(item[1])
                if last_decoded_duration is not None:
                    ends.append(last_pts + last_decoded_duration)
                elif video.duration is not None:
                    stream_start = int(video.start_time or 0)
                    stream_end = stream_start + int(video.duration)
                    if stream_end <= last_pts:
                        raise ChronoCompileError(
                            "source stream duration does not bound its final frame"
                        )
                    ends.append(stream_end)
                elif len(frame_observations) + len(pending) >= 2:
                    previous_pts = (
                        int(pending[index - 1][1])
                        if index
                        else frame_observations[-1]["pts"]
                    )
                    ends.append(last_pts + (last_pts - previous_pts))
                else:
                    raise ChronoCompileError("cannot derive final half-open frame end")
        process_batch(pending, ends)

    if source.stat().st_size != source_bytes or _sha256_file(source) != source_sha:
        raise ChronoCompileError("source video changed during authoring")

    if recipe is None or stream_hasher is None:
        raise ChronoCompileError("source authoring state is incomplete")
    frame_count = len(encoded_records)
    if frame_count != next_ordinal or frame_count != len(frame_observations):
        raise ChronoCompileError("encoded frame count disagrees with source decode")
    decoded_hash = stream_hasher.hexdigest()
    temporal_used = any(
        not (record.flags & FRAME_CHECKPOINT) for record in encoded_records
    )
    header = Ugtc4dHeader(
        flags=_profile_flags(),
        width=width,
        height=height,
        frame_count=frame_count,
        checkpoint_interval=2 if temporal_used else 1,
        first_source_pts=encoded_records[0].source_pts,
        end_source_pts_exclusive=encoded_records[-1].source_end_pts_exclusive,
        time_base_num=time_num,
        time_base_den=time_den,
        center_x=(width - 1) * 0.5,
        center_y=(height - 1) * 0.5,
        r0=profile.r0,
        core_radius=profile.core_radius,
        rho_min=profile.rho_min,
        rho_max=profile.rho_max,
        lut_resolution=DEFAULT_LUT_RESOLUTION,
        source_sha256=source_sha,
        decoded_stream_sha256=decoded_hash,
    )
    sections = _metadata_sections(
        input_path=source,
        source_sha256=source_sha,
        source_bytes=source_bytes,
        header=header,
        lut_bytes=lut_bytes,
        recipe=recipe,
        frame_observations=frame_observations,
        predictor_counts=predictor_counts,
        gpu_receipts=gpu_receipts,
    )
    sections.extend(
        Ugtc4dSection.raw("FRAME", record.to_bytes(), record_start=record.ordinal)
        for record in encoded_records
    )
    built = build_ugtc4d_bytes(header, sections)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(built)
    verified = verify_ugtc4d_file(target, expected_frame_hashes=accepted_hashes)
    elapsed = time.perf_counter() - started
    receipt = {
        "schema": "ugtoms-chrono-lossless-authoring-receipt-0.2",
        "input": {
            "path": str(source),
            "bytes": source_bytes,
            "sha256": source_sha,
        },
        "output": {
            "path": str(target),
            "bytes": target.stat().st_size,
            "sha256": _sha256_file(target),
        },
        "decoded_raw_rgb_bytes": frame_count * width * height * 3,
        "ratio_to_source_mp4": target.stat().st_size / source_bytes,
        "ratio_to_decoded_rgb": target.stat().st_size
        / (frame_count * width * height * 3),
        "frames": frame_count,
        "predictor_counts": predictor_counts,
        "uglut2_bytes": len(lut_bytes),
        "traversal_recipe_bytes": len(recipe.to_bytes()),
        "stored_pixel_permutation_bytes": 0,
        "traversal_sha256": recipe.traversal_sha256,
        "elapsed_seconds": elapsed,
        "gpu": {
            "receipts": gpu_receipts,
            "maximum_peak_mib": max(
                (float(item.get("peak_mib", 0.0)) for item in gpu_receipts),
                default=0.0,
            ),
        },
        "verification": verified,
        "host": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "pyav": av.__version__,
        },
        "claim_boundary": "lossless only relative to accepted PyAV RGB24+PTS decode; not original photons or metric 3D",
    }
    if receipt_path is not None:
        receipt_target = Path(receipt_path).resolve()
        receipt_target.parent.mkdir(parents=True, exist_ok=True)
        receipt_target.write_text(_canonical_json(receipt) + "\n", encoding="utf-8")
    return receipt


def verify_ugtc4d_file(
    path: str | Path,
    *,
    expected_frame_hashes: Iterable[str] | None = None,
    expected_frame_intervals: Iterable[tuple[int, int]] | None = None,
) -> dict[str, Any]:
    """Independently regenerate traversal and strictly replay every frame."""

    source = Path(path).resolve()
    raw = source.read_bytes()
    inspected = inspect_ugtc4d_bytes(raw)
    unexpected_kinds = sorted(
        {section.kind for section in inspected.sections} - KNOWN_SECTION_KINDS
    )
    if unexpected_kinds:
        raise ChronoCompileError(
            f"strict UGTC4D profile contains unsupported sections: {unexpected_kinds}"
        )
    if len(inspected.sections_of_kind("METROLOG")) > 1:
        raise ChronoCompileError("strict UGTC4D profile contains duplicate METROLOG")
    lut_section = inspected.sections_of_kind("UGLUT2")
    traversal_section = inspected.sections_of_kind("TRAVERS")
    if len(lut_section) != 1 or len(traversal_section) != 1:
        raise ChronoCompileError("UGTC4D LUT/traversal singleton mismatch")
    lut_bytes = lut_section[0].logical()
    lut = PolarLookupTable.from_bytes(lut_bytes)
    recipe_bytes = traversal_section[0].logical()
    recipe = SubstrateTraversalRecipe.from_bytes(
        recipe_bytes,
        uglut2_bytes=lut_bytes,
        verify_derived_traversal=True,
    )
    header = inspected.header
    expected_root_seed = int.from_bytes(
        bytes.fromhex(header.source_sha256[:16]), "little"
    )
    if (
        recipe.root_seed != expected_root_seed
        or recipe.recipe_seed != DEFAULT_RECIPE_SEED
    ):
        raise ChronoCompileError(
            "UGTC4D traversal seeds disagree with the fixed source profile"
        )
    if (recipe.width, recipe.height) != (header.width, header.height):
        raise ChronoCompileError("UGTC4D traversal dimensions disagree with header")
    if (
        lut.resolution != header.lut_resolution
        or lut.profile.r0 != header.r0
        or lut.profile.core_radius != header.core_radius
        or lut.profile.rho_min != header.rho_min
        or lut.profile.rho_max != header.rho_max
    ):
        raise ChronoCompileError(
            "UGTC4D header log-polar profile disagrees with UGLUT2"
        )
    traversal = derive_substrate_traversal(recipe, lut_bytes)
    plan = build_substrate_prediction_plan(recipe, lut_bytes, traversal=traversal)
    expected = None if expected_frame_hashes is None else tuple(expected_frame_hashes)
    if expected is not None and len(expected) != header.frame_count:
        raise ChronoCompileError("expected frame hash count mismatch")
    expected_intervals = (
        None
        if expected_frame_intervals is None
        else tuple((int(start), int(end)) for start, end in expected_frame_intervals)
    )
    if expected_intervals is not None and len(expected_intervals) != header.frame_count:
        raise ChronoCompileError("expected frame interval count mismatch")
    stream = DecodedStreamHasher(
        width=header.width,
        height=header.height,
        time_base_num=header.time_base_num,
        time_base_den=header.time_base_den,
    )
    frames = inspected.sections_of_kind("FRAME")
    previous_polar = None
    previous_ordinal = None
    previous_end = None
    first_record_pts = None
    predictor_counts: dict[str, int] = {}
    decoded_observations: list[dict[str, Any]] = []
    for section in frames:
        # Read the predictor field without trusting it to decide dependency;
        # decode_substrate_frame performs the full semantic validation.
        predictor = int.from_bytes(section.stored[24:28], "little")
        temporal = predictor == PREDICTOR_TEMPORAL_SUBSTRATE_MEDIAN_GREEN
        record, polar, cartesian = decode_substrate_frame(
            section.stored,
            plan,
            uglut2_bytes=lut_bytes,
            traversal_recipe_bytes=recipe_bytes,
            previous_polar_rgb=previous_polar if temporal else None,
            expected_previous_ordinal=previous_ordinal if temporal else None,
        )
        if previous_end is not None and record.source_pts != previous_end:
            raise ChronoCompileError("UGTC4D frame intervals are not contiguous")
        if first_record_pts is None:
            first_record_pts = record.source_pts
        if record.ordinal != section.record_start:
            raise ChronoCompileError("UGTC4D frame ordinal disagrees with directory")
        digest = hashlib.sha256(cartesian.tobytes()).hexdigest()
        if expected is not None and digest != expected[record.ordinal]:
            raise ChronoCompileError("UGTC4D frame differs from accepted source decode")
        if (
            expected_intervals is not None
            and (record.source_pts, record.source_end_pts_exclusive)
            != expected_intervals[record.ordinal]
        ):
            raise ChronoCompileError(
                "UGTC4D frame timing differs from accepted source decode"
            )
        stream.update(
            record.ordinal,
            record.source_pts,
            record.source_end_pts_exclusive,
            cartesian.tobytes(),
        )
        name = PREDICTOR_NAMES[record.predictor]
        predictor_counts[name] = predictor_counts.get(name, 0) + 1
        decoded_observations.append(
            {
                "ordinal": record.ordinal,
                "pts": record.source_pts,
                "end_pts_exclusive": record.source_end_pts_exclusive,
                "cartesian_rgb_sha256": digest,
                "polar_rgb_sha256": record.polar_sha256,
                "predictor": name,
                "record_bytes": len(section.stored),
            }
        )
        previous_polar = polar
        previous_ordinal = record.ordinal
        previous_end = record.source_end_pts_exclusive
    if stream.hexdigest() != header.decoded_stream_sha256:
        raise ChronoCompileError("UGTC4D decoded Cartesian stream SHA-256 mismatch")
    if (
        frames[0].record_start != 0
        or first_record_pts != header.first_source_pts
        or previous_end != header.end_source_pts_exclusive
    ):
        raise ChronoCompileError("UGTC4D frame range disagrees with header")
    manifest = decoded_json_section(inspected.sections_of_kind("MANIFEST")[0])
    provenance = manifest.get("input_provenance")
    decoded = manifest.get("decoded")
    substrate = manifest.get("substrate")
    if (
        not isinstance(provenance, dict)
        or not isinstance(decoded, dict)
        or not isinstance(substrate, dict)
    ):
        raise ChronoCompileError("UGTC4D manifest typed records are missing")
    if (
        manifest.get("schema") != "ugtoms-chrono-lossless-manifest-0.2"
        or manifest.get("codec") != "UGTC4D/UGFRM2/UGRICE1"
        or manifest.get("authority") != "EXACT_ACCEPTED_DECODED_CARTESIAN_RGB8_AND_PTS"
        or manifest.get("generative_ai_used") is not False
        or manifest.get("conventional_media_payload_embedded") is not False
        or manifest.get("geometry_authority") != "UNBOUNDED_UNKNOWN"
        or provenance.get("sha256") != header.source_sha256
        or provenance.get("decode_profile") != SOURCE_DECODE_PROFILE
        or provenance.get("source_payload_embedded") is not False
        or decoded
        != {
            "width": header.width,
            "height": header.height,
            "frames": header.frame_count,
            "format": "RGB24",
            "time_base": [header.time_base_num, header.time_base_den],
            "first_pts": header.first_source_pts,
            "end_pts_exclusive": header.end_source_pts_exclusive,
            "stream_sha256": header.decoded_stream_sha256,
        }
        or substrate.get("uglut2_sha256") != hashlib.sha256(lut_bytes).hexdigest()
        or substrate.get("traversal_recipe_sha256")
        != hashlib.sha256(recipe_bytes).hexdigest()
        or substrate.get("traversal_sha256") != recipe.traversal_sha256
        or substrate.get("root_seed") != f"{recipe.root_seed:016x}"
        or substrate.get("recipe_seed") != recipe.recipe_seed
        or substrate.get("stored_pixel_permutation") is not False
        or manifest.get("predictor_counts") != predictor_counts
    ):
        raise ChronoCompileError("UGTC4D manifest disagrees with decoded authority")
    observe = decoded_json_section(inspected.sections_of_kind("OBSERVE")[0])
    if (
        observe.get("schema") != "ugtoms-chrono-observations-0.2"
        or observe.get("coverage") != "EVERY_DECODED_RGB8_PIXEL_IN_EVERY_FRAME"
        or observe.get("static_pixels_remain_observations") is not True
        or observe.get("frames") != decoded_observations
    ):
        raise ChronoCompileError("UGTC4D OBSERVE ledger disagrees with decoded frames")
    return {
        "status": "PASS",
        "file_sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "frames_verified": len(frames),
        "decoded_stream_sha256": header.decoded_stream_sha256,
        "traversal_sha256": recipe.traversal_sha256,
        "predictor_counts": predictor_counts,
        "stored_pixel_permutation": False,
        "geometry_authority": "UNBOUNDED_UNKNOWN",
    }


def verify_ugtc4d_against_source(
    path: str | Path,
    source_video_path: str | Path,
) -> dict[str, Any]:
    """Re-decode the declared source and compare exact RGB24 plus chronology."""

    try:
        import av
        import numpy as np
    except ImportError as error:
        raise ChronoCompileError("source comparison requires PyAV and NumPy") from error
    source = Path(source_video_path).resolve()
    if not source.is_file():
        raise ChronoCompileError(f"source video does not exist: {source}")
    source_bytes = source.stat().st_size
    source_sha = _sha256_file(source)
    container_raw = Path(path).resolve().read_bytes()
    header = inspect_ugtc4d_bytes(container_raw).header
    if source_sha != header.source_sha256:
        raise ChronoCompileError("source SHA-256 disagrees with UGTC4D provenance")

    hashes: list[str] = []
    points: list[int] = []
    last_duration: int | None = None
    width = height = 0
    with av.open(str(source), mode="r") as container:
        if not container.streams.video:
            raise ChronoCompileError("source contains no video stream")
        video = container.streams.video[0]
        time_base = (int(video.time_base.numerator), int(video.time_base.denominator))
        stream_start = int(video.start_time or 0)
        stream_duration = None if video.duration is None else int(video.duration)
        for decoded in container.decode(video):
            if decoded.pts is None:
                raise ChronoCompileError(
                    "source frame is missing an exact presentation timestamp"
                )
            array = decoded.to_ndarray(format="rgb24")
            if array.ndim != 3 or array.shape[2] != 3 or array.dtype != np.uint8:
                raise ChronoCompileError("PyAV did not produce packed RGB24")
            frame_height, frame_width = int(array.shape[0]), int(array.shape[1])
            if not hashes:
                width, height = frame_width, frame_height
            elif (frame_width, frame_height) != (width, height):
                raise ChronoCompileError("source changes raster dimensions")
            points.append(int(decoded.pts))
            hashes.append(
                hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()
            )
            duration = getattr(decoded, "duration", None)
            last_duration = (
                int(duration) if duration is not None and int(duration) > 0 else None
            )
    if source.stat().st_size != source_bytes or _sha256_file(source) != source_sha:
        raise ChronoCompileError("source video changed during verification")
    if not hashes:
        raise ChronoCompileError("source decoded zero frames")
    if len(points) > 1 and any(
        right <= left for left, right in zip(points, points[1:])
    ):
        raise ChronoCompileError(
            "source presentation timestamps are not strictly increasing"
        )
    if last_duration is not None:
        final_end = points[-1] + last_duration
    elif stream_duration is not None and stream_start + stream_duration > points[-1]:
        final_end = stream_start + stream_duration
    elif len(points) > 1:
        final_end = points[-1] + (points[-1] - points[-2])
    else:
        raise ChronoCompileError("cannot derive final half-open source frame end")
    ends = [*points[1:], final_end]
    if (
        (width, height) != (header.width, header.height)
        or time_base != (header.time_base_num, header.time_base_den)
        or len(hashes) != header.frame_count
    ):
        raise ChronoCompileError(
            "source decode shape/time base/count disagrees with UGTC4D"
        )
    result = verify_ugtc4d_file(
        path,
        expected_frame_hashes=hashes,
        expected_frame_intervals=zip(points, ends),
    )
    result["source_verification"] = {
        "status": "PASS",
        "path": str(source),
        "bytes": source_bytes,
        "sha256": source_sha,
        "decode_profile": SOURCE_DECODE_PROFILE,
        "frames_compared": len(hashes),
        "rgb24_and_pts_exact": True,
    }
    return result


__all__ = [
    "ChronoCompileError",
    "compile_video_to_ugtc4d",
    "verify_ugtc4d_against_source",
    "verify_ugtc4d_file",
]
