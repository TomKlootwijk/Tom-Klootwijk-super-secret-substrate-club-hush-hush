"""Seed-regenerated UGTOMS log-polar traversal for exact raster evidence.

The traversal is not a stored pixel lookup table.  One small operator recipe
addresses every Cartesian pixel as a bounded, random-access substrate member.
The retained UGTS SplitMix64 lineage schedule supplies deterministic tie
breaking and phase.  The shared UGLUT2 binary16 radius and direction lanes
classify those members into packed rho20/theta18 order.  A decoder regenerates
the same traversal from the recipe and the shared UGLUT2 dependency.

This is a new chrono-raster operator assembled from existing substrate
primitives; it is not claimed to be an older UGLUT2 feature.  UGLUT2 remains a
kinematic lookup table and does not itself contain pixels.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import math
import struct
from typing import Any, Sequence

from .packed_kinematics import PolarLookupTable
from .scatter import combine_seed, hash64, seed_unit_float, stable_id


TRAVERSAL_MAGIC = b"UGTRV1\0\0"
TRAVERSAL_MAJOR = 1
TRAVERSAL_MINOR = 0
TRAVERSAL_RECIPE_BYTES = 128
_TRAVERSAL_RECIPE = struct.Struct("<8sHHIIIQQ32sQ32sII8s")
_UGLUT2_HEADER = struct.Struct("<6sHddddd")

TRAVERSAL_CENTER_PIXEL_GRID = 1
TRAVERSAL_FLAG_SEEDED_PHASE = 1 << 0
TRAVERSAL_FLAG_SEEDED_COLLISION_ORDER = 1 << 1
TRAVERSAL_FLAGS = (
    TRAVERSAL_FLAG_SEEDED_PHASE | TRAVERSAL_FLAG_SEEDED_COLLISION_ORDER
)
MAX_TRAVERSAL_PIXELS = 1 << 30
MAX_TRAVERSAL_RESOLUTION = 4096

TRAVERSAL_OPERATOR_MEANING = (
    "ugts.kc392.chrono.seeded-log-polar-traversal.v1:"
    "NEW-codec-operator;pixel-address-members;top-left-image-math-up;"
    "canonical-half-pixel-grid-center;"
    "UGTS4.1-splitmix64-lineage(root,recipe,namespace,address);"
    "UGLUT2-binary16-radius-q16-exact-midpoint-ring;"
    "UGLUT2-binary16-direction-q30-exact-cross-wedge;"
    "packed-rho20-closed;packed-theta18-periodic-seeded-origin-direction;"
    "sort=core,rho20,theta18,radius2,sector-cross,lineage,cartesian-address"
)
TRAVERSAL_OPERATOR_HASH64 = hash64(TRAVERSAL_OPERATOR_MEANING)
TRAVERSAL_NAMESPACE = hash64("ugtoms:chrono-seeded-log-polar-traversal:v1")


class ChronoSubstrateError(ValueError):
    """Malformed or non-reproducible chrono substrate traversal data."""


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def _valid_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _half_word_to_fixed(word: int, fractional_bits: int) -> int:
    """Decode one finite IEEE-754 binary16 word to a signed fixed integer.

    Ties are rounded to nearest-even only when the requested fixed domain has
    fewer fractional bits than the binary16 value.  UGLUT2 direction Q30 and
    the chrono raster's bounded radius Q16 path are exact for accepted input.
    """

    word = int(word)
    sign = -1 if word & 0x8000 else 1
    exponent = (word >> 10) & 0x1F
    fraction = word & 0x03FF
    if exponent == 0x1F:
        raise ChronoSubstrateError("UGLUT2 contains a non-finite binary16 lane")
    if exponent == 0:
        mantissa = fraction
        power = -24 + int(fractional_bits)
    else:
        mantissa = 1024 + fraction
        power = exponent - 25 + int(fractional_bits)
    if mantissa == 0:
        return 0
    if power >= 0:
        magnitude = mantissa << power
    else:
        shift = -power
        quotient, remainder = divmod(mantissa, 1 << shift)
        halfway = 1 << (shift - 1)
        magnitude = quotient + int(
            remainder > halfway or (remainder == halfway and quotient & 1)
        )
    return sign * magnitude


def _uglut2_words(data: bytes) -> tuple[PolarLookupTable, tuple[int, ...], tuple[int, ...], tuple[int, ...]]:
    raw = bytes(data)
    if len(raw) < _UGLUT2_HEADER.size:
        raise ChronoSubstrateError("UGLUT2 dependency is truncated")
    try:
        lut = PolarLookupTable.from_bytes(raw)
    except ValueError as error:
        raise ChronoSubstrateError(f"invalid UGLUT2 dependency: {error}") from error
    if raw[:6] != b"UGLUT2":
        raise ChronoSubstrateError("chrono traversal requires UGLUT2, not UGLUT1")
    if lut.resolution > MAX_TRAVERSAL_RESOLUTION:
        raise ChronoSubstrateError(
            f"chrono traversal UGLUT2 resolution exceeds {MAX_TRAVERSAL_RESOLUTION}"
        )
    _magic, resolution, _r0, _rho_min, _rho_max, _core, radius_scale = (
        _UGLUT2_HEADER.unpack_from(raw)
    )
    if radius_scale != 1.0:
        raise ChronoSubstrateError(
            "chrono traversal requires an exact unit UGLUT2 radius scale"
        )
    offset = _UGLUT2_HEADER.size
    words = tuple(item[0] for item in struct.iter_unpack("<H", raw[offset:]))
    if len(words) != resolution * 3:
        raise ChronoSubstrateError("UGLUT2 binary16 lane count mismatch")
    sine = words[:resolution]
    cosine = words[resolution : resolution * 2]
    radius = words[resolution * 2 :]
    return lut, sine, cosine, radius


def _splitmix64_numpy(value: Any, np: Any) -> Any:
    golden = np.uint64(0x9E3779B97F4A7C15)
    with np.errstate(over="ignore"):
        value = value.astype(np.uint64, copy=False) + golden
        value = (value ^ (value >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
        value = (value ^ (value >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
        return value ^ (value >> np.uint64(31))


def _combine_seed_numpy(seed: int, value: Any, np: Any) -> Any:
    seed_value = np.uint64(int(seed) & ((1 << 64) - 1))
    golden = np.uint64(0x9E3779B97F4A7C15)
    with np.errstate(over="ignore"):
        mixed = (
            _splitmix64_numpy(value, np)
            + golden
            + (seed_value << np.uint64(6))
            + (seed_value >> np.uint64(2))
        )
        return _splitmix64_numpy(seed_value ^ mixed, np)


def _stable_id_numpy(session_seed: int, namespace: int, address: Any, np: Any) -> Any:
    prefix = combine_seed(session_seed, namespace)
    return _combine_seed_numpy(prefix, address, np)


@dataclass(frozen=True)
class SubstrateTraversalRecipe:
    """Fixed-size seed/operator recipe; it contains no pixel permutation."""

    width: int
    height: int
    root_seed: int
    recipe_seed: int
    uglut2_sha256: str
    traversal_sha256: str
    center_mode: int = TRAVERSAL_CENTER_PIXEL_GRID
    flags: int = TRAVERSAL_FLAGS

    @property
    def pixel_count(self) -> int:
        return int(self.width) * int(self.height)

    @property
    def session_seed(self) -> int:
        return combine_seed(self.root_seed, self.recipe_seed)

    @property
    def phase18(self) -> int:
        lineage = stable_id(self.session_seed, TRAVERSAL_NAMESPACE, 0)
        unit = seed_unit_float(combine_seed(lineage, 0))
        return int(math.floor(unit * (1 << 18))) & ((1 << 18) - 1)

    def seeded_sector_schedule(self, resolution: int) -> tuple[int, bool]:
        """Return the new operator's origin sector and traversal direction."""

        if resolution < 1 or resolution & (resolution - 1):
            raise ChronoSubstrateError("seeded sector schedule requires power-of-two resolution")
        lineage = stable_id(self.session_seed, TRAVERSAL_NAMESPACE, 0)
        schedule = combine_seed(lineage, 0)
        return int(schedule) & (resolution - 1), bool((int(schedule) >> 63) & 1)

    def validate(self, *, allow_unbound_traversal: bool = False) -> None:
        if not 1 <= int(self.width) <= 65_535 or not 1 <= int(self.height) <= 65_535:
            raise ChronoSubstrateError("traversal dimensions must fit uint16")
        if self.pixel_count > MAX_TRAVERSAL_PIXELS:
            raise ChronoSubstrateError("traversal pixel count exceeds its safety limit")
        maximum_r2 = (int(self.width) - 1) ** 2 + (int(self.height) - 1) ** 2
        if maximum_r2 > ((1 << 63) - 1) >> 32:
            raise ChronoSubstrateError("traversal dimensions exceed exact Q32 radius safety")
        for label, value in (("root", self.root_seed), ("recipe", self.recipe_seed)):
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < (1 << 64):
                raise ChronoSubstrateError(f"traversal {label} seed must fit uint64")
        if not _valid_sha256(self.uglut2_sha256):
            raise ChronoSubstrateError("traversal UGLUT2 dependency must be lowercase SHA-256")
        if allow_unbound_traversal and self.traversal_sha256 == "0" * 64:
            pass
        elif not _valid_sha256(self.traversal_sha256):
            raise ChronoSubstrateError("derived traversal digest must be lowercase SHA-256")
        if self.center_mode != TRAVERSAL_CENTER_PIXEL_GRID:
            raise ChronoSubstrateError("unsupported traversal center convention")
        if self.flags != TRAVERSAL_FLAGS:
            raise ChronoSubstrateError("unsupported traversal operator flags")

    def to_bytes(self) -> bytes:
        self.validate()
        result = _TRAVERSAL_RECIPE.pack(
            TRAVERSAL_MAGIC,
            TRAVERSAL_MAJOR,
            TRAVERSAL_MINOR,
            TRAVERSAL_RECIPE_BYTES,
            int(self.width),
            int(self.height),
            int(self.root_seed),
            int(self.recipe_seed),
            bytes.fromhex(self.uglut2_sha256),
            TRAVERSAL_OPERATOR_HASH64,
            bytes.fromhex(self.traversal_sha256),
            int(self.center_mode),
            int(self.flags),
            bytes(8),
        )
        if len(result) != TRAVERSAL_RECIPE_BYTES:
            raise AssertionError("UGTRV1 ABI size changed")
        return result

    @classmethod
    def from_bytes(
        cls,
        data: bytes | bytearray | memoryview,
        *,
        uglut2_bytes: bytes | None = None,
        verify_derived_traversal: bool = False,
    ) -> "SubstrateTraversalRecipe":
        raw = bytes(data)
        if len(raw) != TRAVERSAL_RECIPE_BYTES:
            raise ChronoSubstrateError(
                f"UGTRV1 length mismatch: expected {TRAVERSAL_RECIPE_BYTES}, got {len(raw)}"
            )
        (
            magic,
            major,
            minor,
            header_bytes,
            width,
            height,
            root_seed,
            recipe_seed,
            uglut2_digest,
            operator_hash,
            traversal_digest,
            center_mode,
            flags,
            reserved,
        ) = _TRAVERSAL_RECIPE.unpack(raw)
        if magic != TRAVERSAL_MAGIC or (major, minor) != (
            TRAVERSAL_MAJOR,
            TRAVERSAL_MINOR,
        ):
            raise ChronoSubstrateError("unsupported UGTRV1 magic/version")
        if header_bytes != TRAVERSAL_RECIPE_BYTES or reserved != bytes(8):
            raise ChronoSubstrateError("UGTRV1 header/reserved bytes are invalid")
        if operator_hash != TRAVERSAL_OPERATOR_HASH64:
            raise ChronoSubstrateError("UGTRV1 operator meaning hash mismatch")
        result = cls(
            width,
            height,
            root_seed,
            recipe_seed,
            uglut2_digest.hex(),
            traversal_digest.hex(),
            center_mode,
            flags,
        )
        result.validate()
        if uglut2_bytes is not None and _sha256(bytes(uglut2_bytes)) != uglut2_digest:
            raise ChronoSubstrateError("UGTRV1 UGLUT2 dependency hash mismatch")
        if verify_derived_traversal:
            if uglut2_bytes is None:
                raise ChronoSubstrateError("UGTRV1 traversal verification requires UGLUT2 bytes")
            derive_substrate_traversal(result, uglut2_bytes, verify_digest=True)
        if result.to_bytes() != raw:
            raise ChronoSubstrateError("UGTRV1 is not canonical")
        return result


def _derive_order(
    recipe: SubstrateTraversalRecipe,
    uglut2_bytes: bytes,
    *,
    include_coordinate_codes: bool = False,
) -> Any:
    try:
        import numpy as np
    except ImportError as error:
        raise ChronoSubstrateError("chrono traversal derivation requires NumPy") from error
    recipe.validate(allow_unbound_traversal=True)
    if _sha256(bytes(uglut2_bytes)).hex() != recipe.uglut2_sha256:
        raise ChronoSubstrateError("traversal recipe references a different UGLUT2")
    lut, sine_words, cosine_words, radius_words = _uglut2_words(bytes(uglut2_bytes))
    resolution = lut.resolution
    if resolution & (resolution - 1):
        raise ChronoSubstrateError("chrono traversal requires power-of-two UGLUT2 resolution")

    count = recipe.pixel_count
    cartesian = np.arange(count, dtype=np.uint64)
    x = (cartesian % np.uint64(recipe.width)).astype(np.int64)
    y = (cartesian // np.uint64(recipe.width)).astype(np.int64)
    # Twice-pixel coordinates make the canonical (width-1)/2, (height-1)/2
    # chart center exact for both odd and even rasters.
    dx2 = x * 2 - (recipe.width - 1)
    dy2 = (recipe.height - 1) - y * 2
    target_radius_squared = dx2 * dx2 + dy2 * dy2

    radius_q16 = np.asarray(
        [_half_word_to_fixed(word, 16) for word in radius_words], dtype=np.int64
    )
    if np.any(radius_q16 <= 0) or np.any(radius_q16[1:] < radius_q16[:-1]):
        raise ChronoSubstrateError("UGLUT2 radius lane is not positive monotone Q16")
    if int(radius_q16[-1]) * 2 > math.isqrt((1 << 63) - 1):
        raise ChronoSubstrateError("UGLUT2 radii exceed exact int64 Q32 safety")
    if radius_q16[0] != int(round(lut.profile.core_radius * (1 << 16))):
        raise ChronoSubstrateError(
            "chrono profile requires its first literal UGLUT2 radius to equal the explicit core"
        )
    # target_radius_squared is four times Cartesian radius squared.  A pixel
    # belongs to lower ring k at an exact tie with the radial midpoint:
    #   r2 <= (R[k] + R[k+1])^2.
    # Q16 makes that comparison an integer Q32 operation.
    sample_radius_squared = (radius_q16 * 2) ** 2
    target_q32 = target_radius_squared << 32
    radial_midpoints = (radius_q16[:-1] + radius_q16[1:]) ** 2
    ring = np.searchsorted(radial_midpoints, target_q32, side="left").astype(np.uint32)

    sine_q30 = np.asarray(
        [_half_word_to_fixed(word, 30) for word in sine_words], dtype=np.int64
    )
    cosine_q30 = np.asarray(
        [_half_word_to_fixed(word, 30) for word in cosine_words], dtype=np.int64
    )
    if np.any((sine_q30 == 0) & (cosine_q30 == 0)):
        raise ChronoSubstrateError("UGLUT2 direction lane contains a zero vector")
    adjacent_cross = (
        cosine_q30[:-1] * sine_q30[1:]
        - sine_q30[:-1] * cosine_q30[1:]
    )
    seam_cross = cosine_q30[-1] * sine_q30[0] - sine_q30[-1] * cosine_q30[0]
    if np.any(adjacent_cross <= 0) or seam_cross <= 0:
        raise ChronoSubstrateError("UGLUT2 direction rays are not strictly counter-clockwise")
    if cosine_q30[0] <= 0 or sine_q30[0] != 0:
        raise ChronoSubstrateError("UGLUT2 direction ray zero is not canonical +X")

    # Exact vectorized upper-bound search over the cyclic UGLUT2 ray order.
    # Half 0 is [0,pi), half 1 is [pi,2pi); within one half, cross(ray,v)>=0
    # means ray angle <= vector angle.  A pixel exactly on a ray is assigned to
    # that lower wedge.  No atan2, normalization, or float comparison occurs.
    vector_half = ((dy2 < 0) | ((dy2 == 0) & (dx2 < 0))).astype(np.uint8)
    ray_half = (
        (sine_q30 < 0) | ((sine_q30 == 0) & (cosine_q30 < 0))
    ).astype(np.uint8)
    low = np.zeros(count, dtype=np.int64)
    high = np.full(count, resolution, dtype=np.int64)
    while np.any(low < high):
        active = low < high
        middle = (low + high) // 2
        probe = np.minimum(middle, resolution - 1)
        ray_x = cosine_q30[probe]
        ray_y = sine_q30[probe]
        half = ray_half[probe]
        cross = ray_x * dy2 - ray_y * dx2
        less_or_equal = (half < vector_half) | (
            (half == vector_half) & (cross >= 0)
        )
        low = np.where(active & less_or_equal, middle + 1, low)
        high = np.where(active & ~less_or_equal, middle, high)
    sector = ((low - 1) & (resolution - 1)).astype(np.uint32)

    # The explicit core uses the first literal UGLUT2 radius as an exact
    # threshold; no logarithm or log(0) is evaluated.
    core = target_q32 < sample_radius_squared[0]
    ring[core] = 0
    sector[core] = 0
    rho20 = (
        (ring.astype(np.uint64) * np.uint64((1 << 20) - 1) + (resolution - 1) // 2)
        // np.uint64(resolution - 1)
    ).astype(np.uint32)
    origin_sector, reverse = recipe.seeded_sector_schedule(resolution)
    if reverse:
        seeded_sector = (origin_sector - sector) & np.uint32(resolution - 1)
    else:
        seeded_sector = (sector - origin_sector) & np.uint32(resolution - 1)
    theta18 = (
        (seeded_sector.astype(np.uint64) << np.uint64(18)) // np.uint64(resolution)
    ).astype(np.uint32)
    theta18[core] = 0
    sector_cross = (
        cosine_q30[sector.astype(np.int64)] * dy2
        - sine_q30[sector.astype(np.int64)] * dx2
    )

    lineage = _stable_id_numpy(
        recipe.session_seed,
        TRAVERSAL_NAMESPACE,
        cartesian,
        np,
    )
    order = np.lexsort(
        (
            cartesian,
            lineage,
            sector_cross,
            target_radius_squared,
            theta18,
            rho20,
            (~core).astype(np.uint8),
        )
    ).astype(np.uint32)
    if order.size != count or np.unique(order).size != count:
        raise ChronoSubstrateError("derived substrate traversal is not a full bijection")
    if include_coordinate_codes:
        return order, rho20, theta18
    return order


def derive_substrate_coordinate_codes(
    recipe: SubstrateTraversalRecipe,
    uglut2_bytes: bytes,
    *,
    verify_digest: bool = True,
) -> tuple[Any, Any]:
    """Regenerate the authoritative per-pixel ``rho20/theta18`` codes.

    This executes the same integer UGLUT2 midpoint/wedge program as the
    traversal derivation.  The arrays are runtime state, never a serialized
    per-pixel lookup table.
    """

    order, rho20, theta18 = _derive_order(
        recipe,
        bytes(uglut2_bytes),
        include_coordinate_codes=True,
    )
    if verify_digest:
        digest = _sha256(order.astype("<u4", copy=False).tobytes()).hex()
        if digest != recipe.traversal_sha256:
            raise ChronoSubstrateError("regenerated traversal SHA-256 mismatch")
    return rho20, theta18


def create_substrate_traversal_recipe(
    width: int,
    height: int,
    uglut2_bytes: bytes,
    *,
    root_seed: int,
    recipe_seed: int,
) -> SubstrateTraversalRecipe:
    """Create a fixed-size recipe and bind its regenerated traversal digest."""

    provisional = SubstrateTraversalRecipe(
        int(width),
        int(height),
        int(root_seed),
        int(recipe_seed),
        _sha256(bytes(uglut2_bytes)).hex(),
        "0" * 64,
    )
    provisional.validate(allow_unbound_traversal=True)
    order = _derive_order(provisional, bytes(uglut2_bytes))
    bound = replace(
        provisional,
        traversal_sha256=_sha256(order.astype("<u4", copy=False).tobytes()).hex(),
    )
    return SubstrateTraversalRecipe.from_bytes(
        bound.to_bytes(),
        uglut2_bytes=bytes(uglut2_bytes),
        # The digest was computed from the order immediately above.  Readers
        # independently regenerate it; avoiding a second authoring sort here
        # does not weaken the stored receipt.
        verify_derived_traversal=False,
    )


def derive_substrate_traversal(
    recipe: SubstrateTraversalRecipe,
    uglut2_bytes: bytes,
    *,
    verify_digest: bool = True,
) -> Any:
    """Regenerate the polar-ordinal -> Cartesian-pixel traversal in memory."""

    order = _derive_order(recipe, bytes(uglut2_bytes))
    if verify_digest:
        digest = _sha256(order.astype("<u4", copy=False).tobytes()).hex()
        if digest != recipe.traversal_sha256:
            raise ChronoSubstrateError("regenerated traversal SHA-256 mismatch")
    return order


def gather_rgb_substrate_numpy(
    frame: Any,
    recipe: SubstrateTraversalRecipe,
    uglut2_bytes: bytes,
    *,
    traversal: Any | None = None,
) -> Any:
    """Gather Cartesian RGB8 into regenerated substrate traversal order."""

    try:
        import numpy as np
    except ImportError as error:
        raise ChronoSubstrateError("substrate RGB gather requires NumPy") from error
    array = np.asarray(frame)
    expected = (recipe.height, recipe.width, 3)
    if array.shape != expected or array.dtype != np.uint8:
        raise ChronoSubstrateError(f"frame must be RGB uint8 with shape {expected}")
    order = (
        derive_substrate_traversal(recipe, uglut2_bytes)
        if traversal is None
        else np.asarray(traversal, dtype=np.uint32)
    )
    if order.shape != (recipe.pixel_count,):
        raise ChronoSubstrateError("supplied substrate traversal has the wrong shape")
    return array.reshape(-1, 3)[order.astype(np.int64)].copy()


def scatter_rgb_substrate_numpy(
    polar: Any,
    recipe: SubstrateTraversalRecipe,
    uglut2_bytes: bytes,
    *,
    traversal: Any | None = None,
) -> Any:
    """Scatter substrate-ordered RGB8 back to exact Cartesian pixel order."""

    try:
        import numpy as np
    except ImportError as error:
        raise ChronoSubstrateError("substrate RGB scatter requires NumPy") from error
    array = np.asarray(polar)
    expected = (recipe.pixel_count, 3)
    if array.shape != expected or array.dtype != np.uint8:
        raise ChronoSubstrateError(f"polar frame must be RGB uint8 with shape {expected}")
    order = (
        derive_substrate_traversal(recipe, uglut2_bytes)
        if traversal is None
        else np.asarray(traversal, dtype=np.uint32)
    )
    if order.shape != (recipe.pixel_count,):
        raise ChronoSubstrateError("supplied substrate traversal has the wrong shape")
    result = np.empty(expected, dtype=np.uint8)
    result[order.astype(np.int64)] = array
    return result.reshape(recipe.height, recipe.width, 3)


def gather_rgb_substrate_cuda(
    frames: Sequence[Any],
    recipe: SubstrateTraversalRecipe,
    uglut2_bytes: bytes,
    *,
    max_vram_mib: int,
    traversal: Any | None = None,
) -> tuple[Any, dict[str, Any]]:
    """RTX gather using a traversal regenerated from substrate state."""

    try:
        import numpy as np
        import torch
    except ImportError as error:
        raise ChronoSubstrateError("CUDA substrate gather requires NumPy and PyTorch") from error
    if not torch.cuda.is_available():
        raise ChronoSubstrateError("PyTorch reports no CUDA device")
    order = (
        derive_substrate_traversal(recipe, uglut2_bytes)
        if traversal is None
        else np.asarray(traversal, dtype=np.uint32)
    )
    if not frames:
        return np.empty((0, recipe.pixel_count, 3), dtype=np.uint8), {
            "backend": "torch-cuda-seed-regenerated-uglut2-traversal",
            "batch_frames": 0,
            "peak_mib": 0.0,
        }
    source = np.stack([np.asarray(frame) for frame in frames], axis=0)
    expected = (len(frames), recipe.height, recipe.width, 3)
    if source.shape != expected or source.dtype != np.uint8:
        raise ChronoSubstrateError(f"CUDA frame batch must be RGB uint8 with shape {expected}")
    device = torch.device("cuda:0")
    properties = torch.cuda.get_device_properties(device)
    workspace_limit = int(max_vram_mib) * 1024 * 1024
    if workspace_limit <= 0 or workspace_limit > int(properties.total_memory):
        raise ChronoSubstrateError("CUDA workspace limit is invalid for the selected device")
    estimate = source.nbytes * 2 + recipe.pixel_count * 8
    if estimate > workspace_limit:
        raise ChronoSubstrateError("CUDA substrate gather exceeds the declared workspace")
    torch.cuda.reset_peak_memory_stats(device)
    tensor = torch.as_tensor(source, device=device).reshape(len(frames), -1, 3)
    indices = torch.as_tensor(order.astype(np.int64), device=device)
    output = tensor[:, indices, :].contiguous()
    result = output.cpu().numpy()
    torch.cuda.synchronize(device)
    peak = float(torch.cuda.max_memory_allocated(device)) / (1024 * 1024)
    if peak > max_vram_mib:
        raise ChronoSubstrateError("CUDA substrate gather exceeded its workspace")
    return result, {
        "backend": "torch-cuda-seed-regenerated-uglut2-traversal",
        "device": torch.cuda.get_device_name(device),
        "compute_capability": list(torch.cuda.get_device_capability(device)),
        "batch_frames": len(frames),
        "workspace_limit_mib": int(max_vram_mib),
        "peak_mib": peak,
        "integer_byte_exact": True,
        "stored_pixel_permutation": False,
        "recipe_bytes": TRAVERSAL_RECIPE_BYTES,
    }


__all__ = [
    "ChronoSubstrateError",
    "SubstrateTraversalRecipe",
    "TRAVERSAL_MAGIC",
    "TRAVERSAL_OPERATOR_HASH64",
    "TRAVERSAL_OPERATOR_MEANING",
    "TRAVERSAL_RECIPE_BYTES",
    "create_substrate_traversal_recipe",
    "derive_substrate_coordinate_codes",
    "derive_substrate_traversal",
    "gather_rgb_substrate_cuda",
    "gather_rgb_substrate_numpy",
    "scatter_rgb_substrate_numpy",
]
