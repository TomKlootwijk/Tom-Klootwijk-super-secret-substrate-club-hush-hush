"""Canonical KCPR392 sidecar for content-addressed polar display recipes."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import struct
from typing import Any, Mapping

from .polar_population import (
    MAX_POLAR_BURST_INSTANCES_PER_RECIPE,
    MAX_POLAR_BURST_RECIPES,
    MAX_POLAR_BURST_TOTAL_INSTANCES,
    MAX_POLAR_POPULATION_RECIPES,
    MAX_POLAR_POPULATION_TOTAL_INSTANCES,
    POLAR_BURST_MATH_SCHEDULE,
    POLAR_GLOW_MATH_SCHEDULE,
    POLAR_GLOW_OPERATOR_MASK,
    POLAR_GROW_COPIES_MATH_SCHEDULE,
    POLAR_GROW_COPIES_OPERATOR_MASK,
    POLAR_POPULATION_MATH_SCHEDULE,
    POLAR_POPULATION_OPERATORS,
    POLAR_POPULATION_PRESETS,
    POLAR_POPULATION_PRESET_LABELS,
    POLAR_POPULATION_V1_OPERATOR_CODES,
    POLAR_POPULATION_V2_OPERATOR_CODES,
    POLAR_POPULATION_V3_OPERATOR_CODES,
    POLAR_POPULATION_V4_OPERATOR_CODES,
    PolarPopulationError,
    collect_polar_population_project_spec,
    operator_mask_for_preset,
    polar_recipe_record_addresses,
    validate_polar_glow_operator_parameters,
    validate_polar_population_operator_parameters,
)


POLAR_POPULATION_PACK_ASSET = "polar_populations.kcpr"
POLAR_POPULATION_PACK_MAGIC = b"KCPR392\0"
POLAR_POPULATION_PACK_ENDIAN = 0x01020304
POLAR_POPULATION_PACK_LEGACY_VERSION = 1
POLAR_POPULATION_PACK_BURST_VERSION = 2
POLAR_POPULATION_PACK_GLOW_VERSION = 3
POLAR_POPULATION_PACK_VERSION = 4
POLAR_POPULATION_HEADER_BYTES = 32
POLAR_POPULATION_OPERATOR_BYTES = 16
POLAR_POPULATION_RECIPE_BYTES = 128
MAX_POLAR_POPULATION_PACK_BYTES = 64 * 1024

_HEADER = struct.Struct("<8sIIHHIQ")
_OPERATOR = struct.Struct("<HBBIQ")
_RECIPE = struct.Struct("<IHHIQ16s16s16s16s8f12s")
_PARAMETERS = struct.Struct("<8f")
_GLOW_PARAMETERS = struct.Struct("<3f")
_ZERO_RESERVED = bytes(12)
_SAVED_SCENE_METADATA_KEYS = frozenset({"saved_scenes", "saved_scene_instances"})

if _HEADER.size != POLAR_POPULATION_HEADER_BYTES:  # pragma: no cover
    raise RuntimeError("KCPR392 header layout changed")
if _OPERATOR.size != POLAR_POPULATION_OPERATOR_BYTES:  # pragma: no cover
    raise RuntimeError("KCPR392 operator layout changed")
if _RECIPE.size != POLAR_POPULATION_RECIPE_BYTES:  # pragma: no cover
    raise RuntimeError("KCPR392 recipe layout changed")


class PolarPopulationPackError(PolarPopulationError):
    """Invalid polar-population authoring or malformed KCPR392 bytes."""


def _materialized_project(project: Any) -> Any:
    metadata = getattr(project, "metadata", {})
    if not isinstance(metadata, Mapping) or not any(
        key in metadata for key in _SAVED_SCENE_METADATA_KEYS
    ):
        return project
    from .saved_scene import materialize_saved_scenes

    return materialize_saved_scenes(project)


def compile_polar_population_pack_bytes(project: Any) -> bytes:
    """Compile optional render-only recipes; no generated ECS rows are written."""

    project = _materialized_project(project)
    project.validate()
    spec = collect_polar_population_project_spec(project)
    if not spec.groups:
        return b""
    used_mask = 0
    has_burst = False
    has_glow = False
    has_grow_copies = False
    for group in spec.groups:
        used_mask |= group.recipe.operator_mask
        has_burst = has_burst or group.recipe.preset == "burst"
        has_glow = has_glow or group.glow_parameters is not None
        has_grow_copies = has_grow_copies or (
            group.recipe.glow_by_distance is not None
            and group.recipe.glow_by_distance.grow_copies
        )
    version = (
        POLAR_POPULATION_PACK_VERSION
        if has_grow_copies
        else (
            POLAR_POPULATION_PACK_GLOW_VERSION
            if has_glow
            else (
                POLAR_POPULATION_PACK_BURST_VERSION
                if has_burst
                else POLAR_POPULATION_PACK_LEGACY_VERSION
            )
        )
    )
    operators = tuple(
        operator
        for operator in POLAR_POPULATION_OPERATORS
        if used_mask & operator.mask
    )
    output = bytearray(
        _HEADER.pack(
            POLAR_POPULATION_PACK_MAGIC,
            POLAR_POPULATION_PACK_ENDIAN,
            version,
            len(operators),
            len(spec.groups),
            spec.total_instances,
            spec.root_seed,
        )
    )
    for operator in operators:
        output.extend(
            _OPERATOR.pack(
                operator.code,
                operator.slot,
                operator.arity,
                0,
                operator.meaning_hash,
            )
        )
    for group in spec.groups:
        recipe = group.recipe
        preset_code = POLAR_POPULATION_PRESETS.index(recipe.preset) + 1
        output.extend(
            _RECIPE.pack(
                group.prototype_node_index,
                preset_code,
                recipe.operator_mask,
                recipe.instance_count,
                recipe.seed,
                group.content_address,
                group.lineage_namespace,
                group.profile_address,
                group.prototype_address,
                *group.operator_parameters,
                (
                    _ZERO_RESERVED
                    if group.glow_parameters is None
                    else _GLOW_PARAMETERS.pack(*group.glow_parameters)
                ),
            )
        )
    result = bytes(output)
    if len(result) > MAX_POLAR_POPULATION_PACK_BYTES:
        raise PolarPopulationPackError(
            f"polar population pack is {len(result)} bytes; limit is "
            f"{MAX_POLAR_POPULATION_PACK_BYTES}"
        )
    inspect_polar_population_pack(result, node_count=len(getattr(project, "nodes", ())))
    return result


def write_polar_population_pack(project: Any, path: str | Path) -> Path | None:
    data = compile_polar_population_pack_bytes(project)
    if not data:
        return None
    result = Path(path)
    result.parent.mkdir(parents=True, exist_ok=True)
    result.write_bytes(data)
    return result


def inspect_polar_population_pack(
    data_or_path: bytes | bytearray | memoryview | str | Path,
    *,
    node_count: int | None = None,
) -> dict[str, Any]:
    """Independently validate canonical structure, meanings, and addresses."""

    data = (
        Path(data_or_path).read_bytes()
        if isinstance(data_or_path, (str, Path))
        else bytes(data_or_path)
    )
    if len(data) > MAX_POLAR_POPULATION_PACK_BYTES:
        raise PolarPopulationPackError("polar population asset exceeds its byte limit")
    if len(data) < POLAR_POPULATION_HEADER_BYTES:
        raise PolarPopulationPackError("truncated polar population asset")
    (
        magic,
        endian,
        version,
        operator_count,
        recipe_count,
        total_instances,
        root_seed,
    ) = _HEADER.unpack_from(data)
    if magic != POLAR_POPULATION_PACK_MAGIC:
        raise PolarPopulationPackError("polar population magic mismatch")
    if endian != POLAR_POPULATION_PACK_ENDIAN:
        raise PolarPopulationPackError("polar population endian marker mismatch")
    if version not in (
        POLAR_POPULATION_PACK_LEGACY_VERSION,
        POLAR_POPULATION_PACK_BURST_VERSION,
        POLAR_POPULATION_PACK_GLOW_VERSION,
        POLAR_POPULATION_PACK_VERSION,
    ):
        raise PolarPopulationPackError("unsupported polar population version")
    allowed_operator_codes = (
        POLAR_POPULATION_V1_OPERATOR_CODES
        if version == POLAR_POPULATION_PACK_LEGACY_VERSION
        else (
            POLAR_POPULATION_V2_OPERATOR_CODES
            if version == POLAR_POPULATION_PACK_BURST_VERSION
            else (
                POLAR_POPULATION_V3_OPERATOR_CODES
                if version == POLAR_POPULATION_PACK_GLOW_VERSION
                else POLAR_POPULATION_V4_OPERATOR_CODES
            )
        )
    )
    maximum_operators = len(allowed_operator_codes)
    if not 1 <= operator_count <= maximum_operators:
        raise PolarPopulationPackError("polar population operator count is invalid")
    if not 1 <= recipe_count <= MAX_POLAR_POPULATION_RECIPES:
        raise PolarPopulationPackError("polar population recipe count is invalid")
    expected_size = (
        POLAR_POPULATION_HEADER_BYTES
        + operator_count * POLAR_POPULATION_OPERATOR_BYTES
        + recipe_count * POLAR_POPULATION_RECIPE_BYTES
    )
    if len(data) < expected_size:
        raise PolarPopulationPackError("truncated polar population record")
    if len(data) > expected_size:
        raise PolarPopulationPackError(
            f"polar population asset has {len(data) - expected_size} trailing bytes"
        )

    expected_by_code = {
        operator.code: operator for operator in POLAR_POPULATION_OPERATORS
    }
    operators: list[dict[str, Any]] = []
    present_mask = 0
    previous_code: int | None = None
    offset = POLAR_POPULATION_HEADER_BYTES
    for _ in range(operator_count):
        code, slot, arity, flags, meaning_hash = _OPERATOR.unpack_from(data, offset)
        offset += POLAR_POPULATION_OPERATOR_BYTES
        if previous_code is not None and code <= previous_code:
            raise PolarPopulationPackError("polar population operators are not canonical")
        expected = expected_by_code.get(code)
        if expected is None or code not in allowed_operator_codes:
            raise PolarPopulationPackError(f"unknown polar population operator 0x{code:04x}")
        if (
            slot != expected.slot
            or arity != expected.arity
            or flags != 0
            or meaning_hash != expected.meaning_hash
        ):
            raise PolarPopulationPackError(
                f"polar population operator 0x{code:04x} meaning mismatch"
            )
        present_mask |= expected.mask
        previous_code = code
        operators.append(
            {
                "code": code,
                "code_hex": f"0x{code:04x}",
                "slot": slot,
                "arity": arity,
                "name": expected.name,
                "meaning_hash": f"{meaning_hash:016x}",
                "meaning": expected.meaning,
            }
        )

    recipes: list[dict[str, Any]] = []
    counted_instances = 0
    counted_burst_instances = 0
    counted_burst_recipes = 0
    counted_glow_recipes = 0
    counted_grow_copies_recipes = 0
    used_mask = 0
    previous_prototype: int | None = None
    for _ in range(recipe_count):
        unpacked = _RECIPE.unpack_from(data, offset)
        offset += POLAR_POPULATION_RECIPE_BYTES
        (
            prototype,
            preset_code,
            operator_mask,
            instance_count,
            recipe_seed,
            content_address,
            lineage_namespace,
            profile_address,
            prototype_address,
            *tail,
        ) = unpacked
        parameters = tuple(tail[:8])
        reserved = tail[8]
        if previous_prototype is not None and prototype <= previous_prototype:
            raise PolarPopulationPackError("polar population recipes are not sparse-canonical")
        if node_count is not None and prototype >= node_count:
            raise PolarPopulationPackError("polar population has an invalid prototype node")
        maximum_preset_code = (
            3
            if version == POLAR_POPULATION_PACK_LEGACY_VERSION
            else len(POLAR_POPULATION_PRESETS)
        )
        if not 1 <= preset_code <= maximum_preset_code:
            raise PolarPopulationPackError("polar population preset code is invalid")
        preset = POLAR_POPULATION_PRESETS[preset_code - 1]
        glow_parameters: tuple[float, float, float] | None = None
        if version in (
            POLAR_POPULATION_PACK_GLOW_VERSION,
            POLAR_POPULATION_PACK_VERSION,
        ) and reserved != _ZERO_RESERVED:
            raw_glow_parameters = _GLOW_PARAMETERS.unpack(reserved)
            if any(not math.isfinite(value) for value in raw_glow_parameters):
                raise PolarPopulationPackError("polar Glow parameters must be finite")
            try:
                glow_parameters = validate_polar_glow_operator_parameters(
                    raw_glow_parameters
                )
            except PolarPopulationError as error:
                raise PolarPopulationPackError(
                    f"polar population Glow modifier is invalid: {error}"
                ) from error
            if reserved != _GLOW_PARAMETERS.pack(*glow_parameters):
                raise PolarPopulationPackError(
                    "polar Glow parameters are not canonical binary32"
                )
        elif version not in (
            POLAR_POPULATION_PACK_GLOW_VERSION,
            POLAR_POPULATION_PACK_VERSION,
        ) and reserved != _ZERO_RESERVED:
            raise PolarPopulationPackError(
                "polar population recipe reserved bytes are nonzero"
            )
        grow_copies = bool(operator_mask & POLAR_GROW_COPIES_OPERATOR_MASK)
        if grow_copies and glow_parameters is None:
            raise PolarPopulationPackError(
                "Grow glowing copies requires Glow by distance parameters"
            )
        expected_operator_mask = operator_mask_for_preset(preset) | (
            POLAR_GLOW_OPERATOR_MASK if glow_parameters is not None else 0
        ) | (
            POLAR_GROW_COPIES_OPERATOR_MASK if grow_copies else 0
        )
        if operator_mask != expected_operator_mask:
            raise PolarPopulationPackError("polar population preset operator mask is invalid")
        if operator_mask & ~present_mask:
            raise PolarPopulationPackError("polar population recipe references a missing operator")
        if any(not math.isfinite(value) for value in parameters):
            raise PolarPopulationPackError("polar population parameters must be finite")
        try:
            canonical_parameters = validate_polar_population_operator_parameters(
                preset, parameters
            )
            if _PARAMETERS.pack(*parameters) != _PARAMETERS.pack(
                *canonical_parameters
            ):
                raise PolarPopulationPackError(
                    "polar population parameters are not canonical binary32"
                )
            expected_namespace, expected_content = polar_recipe_record_addresses(
                preset=preset,
                instance_count=instance_count,
                recipe_seed=recipe_seed,
                operator_parameters=canonical_parameters,
                profile_address=profile_address,
                prototype_address=prototype_address,
                root_seed=root_seed,
                glow_parameters=glow_parameters,
                grow_copies=grow_copies,
            )
        except PolarPopulationError as error:
            raise PolarPopulationPackError(
                f"polar population recipe is invalid: {error}"
            ) from error
        if lineage_namespace != expected_namespace:
            raise PolarPopulationPackError("polar population lineage namespace mismatch")
        if content_address != expected_content:
            raise PolarPopulationPackError("polar population content address mismatch")
        previous_prototype = prototype
        counted_instances += instance_count
        if preset == "burst":
            counted_burst_recipes += 1
            counted_burst_instances += instance_count
            if instance_count > MAX_POLAR_BURST_INSTANCES_PER_RECIPE:
                raise PolarPopulationPackError(
                    "Radial Burst instance count exceeds its safety limit"
                )
        if glow_parameters is not None:
            counted_glow_recipes += 1
        if grow_copies:
            counted_grow_copies_recipes += 1
        used_mask |= operator_mask
        parameter_labels = (
            (
                "core_aware_log_start_distance",
                "log_end_distance",
                "duration_ticks",
                "angle_step_turns",
                "angle_jitter_turns",
                "height_arc",
                "scale_min",
                "scale_max",
            )
            if preset == "burst"
            else (
                "radius_min_log_offset",
                "radius_max_log_offset",
                "radial_rate",
                "angle_step_turns",
                "angle_jitter_turns",
                "height_spread",
                "scale_min",
                "scale_max",
            )
        )
        recipes.append(
            {
                "prototype_node_index": prototype,
                "preset": preset,
                "preset_label": POLAR_POPULATION_PRESET_LABELS[preset],
                "operator_mask": operator_mask,
                "instance_count": instance_count,
                "generated_copy_count": instance_count - 1,
                "recipe_seed": recipe_seed,
                "root_seed": root_seed,
                "content_address": content_address.hex(),
                "lineage_namespace": lineage_namespace.hex(),
                "profile_semantics_address": profile_address.hex(),
                "prototype_semantics_address": prototype_address.hex(),
                "operator_parameters": dict(
                    zip(parameter_labels, canonical_parameters)
                ),
                "glow_by_distance": (
                    None
                    if glow_parameters is None
                    else dict(
                        {
                            "center_rho": glow_parameters[0],
                            "inv_half_width": glow_parameters[1],
                            "strength": glow_parameters[2],
                        },
                        **({"grow_copies": True} if grow_copies else {}),
                    )
                ),
            }
        )
    if offset != len(data):  # pragma: no cover - exact size already checked
        raise PolarPopulationPackError("polar population reader did not consume the asset")
    if used_mask != present_mask:
        raise PolarPopulationPackError("polar population operator table is not minimal-canonical")
    if (
        version == POLAR_POPULATION_PACK_BURST_VERSION
        and counted_burst_recipes == 0
    ):
        raise PolarPopulationPackError(
            "polar population version 2 requires a Radial Burst recipe"
        )
    if (
        version == POLAR_POPULATION_PACK_GLOW_VERSION
        and counted_glow_recipes == 0
    ):
        raise PolarPopulationPackError(
            "polar population version 3 requires a Glow by distance modifier"
        )
    if (
        version == POLAR_POPULATION_PACK_VERSION
        and counted_grow_copies_recipes == 0
    ):
        raise PolarPopulationPackError(
            "polar population version 4 requires Grow glowing copies"
        )
    if counted_burst_recipes > MAX_POLAR_BURST_RECIPES:
        raise PolarPopulationPackError(
            "Radial Burst recipe count exceeds its safety limit"
        )
    if counted_burst_instances > MAX_POLAR_BURST_TOTAL_INSTANCES:
        raise PolarPopulationPackError(
            "Radial Burst instance total exceeds its safety limit"
        )
    if counted_instances != total_instances:
        raise PolarPopulationPackError("polar population total does not match its recipes")
    if total_instances > MAX_POLAR_POPULATION_TOTAL_INSTANCES:
        raise PolarPopulationPackError("polar population total exceeds its safety limit")
    return {
        "schema": "ugts-kc-polar-population-inspection-3.9.2",
        "format_version": version,
        "byte_length": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "root_seed": root_seed,
        "operator_count": operator_count,
        "recipe_count": recipe_count,
        "total_instances": total_instances,
        "generated_copy_count": total_instances - recipe_count,
        "ecs_prototype_count": recipe_count,
        "generated_members_are_ecs_entities": False,
        "native_consumer_wired": True,
        "native_consumer": f"android-kcpr392-v{version}",
        "native_modes": ["cpu", "direct", "lut"],
        "math_schedule": POLAR_POPULATION_MATH_SCHEDULE,
        "burst_math_schedule": (
            POLAR_BURST_MATH_SCHEDULE
            if counted_burst_recipes
            else None
        ),
        "glow_math_schedule": (
            POLAR_GLOW_MATH_SCHEDULE if counted_glow_recipes else None
        ),
        "grow_copies_math_schedule": (
            POLAR_GROW_COPIES_MATH_SCHEDULE
            if counted_grow_copies_recipes
            else None
        ),
        "operators": operators,
        "recipes": recipes,
    }


__all__ = [
    "MAX_POLAR_POPULATION_PACK_BYTES",
    "POLAR_POPULATION_HEADER_BYTES",
    "POLAR_POPULATION_OPERATOR_BYTES",
    "POLAR_POPULATION_PACK_ASSET",
    "POLAR_POPULATION_PACK_ENDIAN",
    "POLAR_POPULATION_PACK_MAGIC",
    "POLAR_POPULATION_PACK_BURST_VERSION",
    "POLAR_POPULATION_PACK_GLOW_VERSION",
    "POLAR_POPULATION_PACK_LEGACY_VERSION",
    "POLAR_POPULATION_PACK_VERSION",
    "POLAR_POPULATION_RECIPE_BYTES",
    "PolarPopulationPackError",
    "compile_polar_population_pack_bytes",
    "inspect_polar_population_pack",
    "write_polar_population_pack",
]
