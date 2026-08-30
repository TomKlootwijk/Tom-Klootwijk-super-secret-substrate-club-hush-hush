"""Independent fixed-integer oracle for UGYUVS1 camera profile 2.

The program regenerates every operator state from a 64-bit seed, the literal
UGLUT2 dependency, dimensions, and frame ordinal.  Camera bytes are never
inferred: exact modulo-256 residuals remain the authority.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import struct
from typing import Any, Iterable

from .chrono_substrate import (
    SubstrateTraversalRecipe,
    derive_substrate_coordinate_codes,
    derive_substrate_traversal,
)
from .gsp4_camera_codeword import (
    DenseYuv420Frame,
    codeword_lineage,
    pack_codeword420,
    unpack_codeword420,
)


PROFILE_ID = 2
PROFILE_NAME = "UGCAMNODE_FX1_CAMERA_EXACT"
RADIX_DEPTH = 16
KLB37_BITS = 37
KLB37_MASK = (1 << KLB37_BITS) - 1
U32_MASK = (1 << 32) - 1
U64_MASK = (1 << 64) - 1
RHO20_MASK = (1 << 20) - 1
THETA18_MASK = (1 << 18) - 1
PYTHAGOREAN_DELTA_T_LUT = (
    (3, 4, 5),
    (5, 12, 13),
    (8, 15, 17),
    (7, 24, 25),
    (20, 21, 29),
    (12, 35, 37),
    (9, 40, 41),
    (28, 45, 53),
)

OPERATOR_BLOCK_DOMAIN = b"UGCAMNODE-FX1-block-receipts-v0.1.0\0"
OPERATOR_FRAME_DOMAIN = b"UGCAMNODE-FX1-frame-receipts-v0.1.0\0"
OPERATOR_MEANING = (
    b"UGCAMNODE-FX1-v0.1.0;profile=2;rho=UGLUT2-rho20;theta=UGLUT2-theta18;"
    b"key64=rho20|theta18|frame14|lowercase-phi12;morton=msb-round-robin;"
    b"klb37=rho11|theta12|elevation10|symbol3|even-parity;radix-depth=16;"
    b"node=2n+1+branch;klein=y-seam-x-reflection;sclp-odd-wrap=reflect-negate;"
    b"gsp4-lineage=SplitMix64(root,recipe,namespace,address)+routed-mix32;"
    b"guards=integer-index-pythagorean-delta-T-filled-triangle-segments+"
    b"paired-sphere+euclidean-apex;"
    b"cone-LUT=(3,4,5),(5,12,13),(8,15,17),(7,24,25),(20,21,29),"
    b"(12,35,37),(9,40,41),(28,45,53);cone-index=G16&7;"
    b"cone-scale=256+(G17&255);T^2=R^2+h^2;"
    b"predictors=previous-same,klein-left,klein-up,klein-med;residual=mod256\0"
)


class FullSubstrateCameraError(ValueError):
    """Profile-2 parameters or exact residual evidence are invalid."""


def operator_meaning_digest() -> bytes:
    """Return the native static executable-program digest."""

    return hashlib.sha256(OPERATOR_MEANING).digest()


def _u32(value: int) -> int:
    return int(value) & U32_MASK


def rotl32(value: int, amount: int) -> int:
    value = _u32(value)
    amount = int(amount) & 31
    if amount == 0:
        return value
    return _u32((value << amount) | (value >> (32 - amount)))


def mix32(value: int) -> int:
    value = _u32(value)
    value ^= value >> 16
    value = _u32(value * 0x7FEB352D)
    value ^= value >> 15
    value = _u32(value * 0x846CA68B)
    value ^= value >> 16
    return _u32(value)


def seed_word(root_seed: int, index: int) -> int:
    if not 0 <= int(root_seed) <= U64_MASK:
        raise FullSubstrateCameraError("root seed must be uint64")
    if int(index) < 0:
        raise FullSubstrateCameraError("seed word index must be nonnegative")
    low = int(root_seed) & U32_MASK
    high = (int(root_seed) >> 32) & U32_MASK
    golden = _u32((int(index) + 1) * 0x9E3779B9)
    return mix32(low ^ rotl32(high, int(index) & 31) ^ golden)


def parity32(value: int) -> int:
    value = _u32(value)
    value ^= value >> 16
    value ^= value >> 8
    value ^= value >> 4
    return (0x6996 >> (value & 15)) & 1


def parity64(value: int) -> int:
    value = int(value) & U64_MASK
    return parity32(value ^ (value >> 32))


def floor_div(value: int, divisor: int) -> int:
    if int(divisor) <= 0:
        raise FullSubstrateCameraError("floor divisor must be positive")
    return int(value) // int(divisor)


def floor_mod(value: int, divisor: int) -> int:
    return int(value) - floor_div(value, divisor) * int(divisor)


def trunc_div(value: int, divisor: int) -> int:
    """Signed integer division with C/C++ truncation toward zero."""

    if int(divisor) <= 0:
        raise FullSubstrateCameraError("truncating divisor must be positive")
    magnitude = abs(int(value)) // int(divisor)
    return -magnitude if int(value) < 0 else magnitude


def klein_address(
    x: int,
    y: int,
    width: int,
    height: int,
) -> tuple[int, bool]:
    """Return KLB's exact discrete Klein quotient address and reflection."""

    width = int(width)
    height = int(height)
    if width <= 0 or height <= 0:
        raise FullSubstrateCameraError("Klein dimensions must be positive")
    y_wrap = floor_div(int(y), height)
    yy = floor_mod(int(y), height)
    xx = int(x)
    reflected = bool(y_wrap & 1)
    if reflected:
        xx = width - 1 - xx
    xx = floor_mod(xx, width)
    return yy * width + xx, reflected


def q15_pixel_center(index: int, extent: int, *, invert: bool = False) -> int:
    """Native ABI's normalized Q15 pixel-center coordinate."""

    index = int(index)
    extent = int(extent)
    if extent <= 0 or not 0 <= index < extent:
        raise FullSubstrateCameraError("pixel center is outside its extent")
    value = trunc_div(((2 * index + 1) - extent) * 32767, extent)
    return -value if invert else value


def triangular32(frame_ordinal: int) -> int:
    """Return ``f*(f-1)/2 mod 2^32`` without requiring a wide product."""

    frame = _u32(frame_ordinal)
    prior = _u32(frame - 1)
    if frame & 1:
        prior >>= 1
    else:
        frame >>= 1
    return _u32(frame * prior)


@dataclass(frozen=True)
class KinematicState:
    phi: int
    omega: int
    alpha: int


def frame_kinematics(root_seed: int, frame_ordinal: int) -> KinematicState:
    frame = _u32(frame_ordinal)
    phi0 = seed_word(root_seed, 20)
    omega0 = seed_word(root_seed, 21)
    alpha = seed_word(root_seed, 22)
    omega = _u32(omega0 + _u32(frame * alpha))
    phi = _u32(
        phi0
        + _u32(frame * omega0)
        + _u32(triangular32(frame) * alpha)
    )
    return KinematicState(phi, omega, alpha)


def corrected_morton_key(
    rho20: int,
    theta18: int,
    frame14: int,
    phi12: int,
) -> int:
    values = {
        "rho": int(rho20),
        "theta": int(theta18),
        "time": int(frame14),
        "phi": int(phi12),
    }
    widths = {"rho": 20, "theta": 18, "time": 14, "phi": 12}
    for name, width in widths.items():
        if not 0 <= values[name] < (1 << width):
            raise FullSubstrateCameraError(f"{name} exceeds its Morton field")
    key = 0
    for round_index in range(20):
        for name in ("rho", "theta", "time", "phi"):
            bit_index = widths[name] - 1 - round_index
            if bit_index >= 0:
                key = (key << 1) | ((values[name] >> bit_index) & 1)
    if key > U64_MASK:
        raise AssertionError("corrected Morton schedule exceeded 64 bits")
    return key


def sclp64_contiguous(
    rho20: int,
    theta18: int,
    frame14: int,
    phi12: int,
) -> int:
    if not 0 <= int(rho20) < (1 << 20):
        raise FullSubstrateCameraError("rho20 is outside its field")
    if not 0 <= int(theta18) < (1 << 18):
        raise FullSubstrateCameraError("theta18 is outside its field")
    if not 0 <= int(frame14) < (1 << 14):
        raise FullSubstrateCameraError("frame14 is outside its field")
    if not 0 <= int(phi12) < (1 << 12):
        raise FullSubstrateCameraError("lowercase phi12 is outside its field")
    return (
        (int(rho20) << 44)
        | (int(theta18) << 26)
        | (int(frame14) << 12)
        | int(phi12)
    )


def round_half_up(numerator: int, denominator: int) -> int:
    if int(numerator) < 0 or int(denominator) <= 0:
        raise FullSubstrateCameraError("round-half-up requires n>=0,d>0")
    return (2 * int(numerator) + int(denominator)) // (2 * int(denominator))


def make_klb37(
    rho20: int,
    theta18: int,
    elevation10: int,
    symbol3: int,
) -> int:
    q_rho11 = round_half_up(int(rho20) * 2047, RHO20_MASK)
    q_theta12 = int(theta18) >> 6
    if not 0 <= int(elevation10) < (1 << 10):
        raise FullSubstrateCameraError("elevation10 is outside its field")
    if not 0 <= int(symbol3) < 8:
        raise FullSubstrateCameraError("symbol3 is outside its field")
    lower = (
        q_rho11
        | (q_theta12 << 11)
        | (int(elevation10) << 23)
        | (int(symbol3) << 33)
    )
    return lower | (parity64(lower) << 36)


def klb37_even_parity(code: int) -> bool:
    return 0 <= int(code) <= KLB37_MASK and parity64(int(code)) == 0


def median_predictor(left: int, up: int, up_left: int) -> int:
    gradient = max(0, min(255, int(left) + int(up) - int(up_left)))
    return sorted((int(left), int(up), gradient))[1]


@dataclass(frozen=True)
class GuardState:
    inside_cone: bool
    near_cone: bool
    inside_sphere: bool
    near_sphere: bool
    apex_guard: bool
    cone_triple_index: int


@dataclass(frozen=True)
class OperatorState:
    address: int
    source_rho20: int
    source_theta18: int
    wrapped_rho20: int
    topological_theta18: int
    contiguous_key: int
    morton_key: int
    klb37: int
    phi_final: int
    omega_final: int
    alpha: int
    node: int
    prefix: int
    selector: int
    elevation10: int
    symbol3: int
    odd_radial_wrap: bool
    orientation: bool
    klein_left: int
    klein_up: int
    klein_up_left: int
    left_reflected: bool
    up_reflected: bool
    up_left_reflected: bool
    guards: GuardState
    tag: int

    @property
    def branch_word(self) -> int:
        return (int(self.node) & 0xFFFF) | (int(self.prefix) << 16)

    @property
    def packed_state(self) -> int:
        guard = self.guards
        return (
            int(self.elevation10)
            | (int(self.symbol3) << 10)
            | (int(self.selector) << 13)
            | (int(self.odd_radial_wrap) << 15)
            | (int(self.orientation) << 16)
            | (int(self.left_reflected) << 17)
            | (int(self.up_reflected) << 18)
            | (int(self.up_left_reflected) << 19)
            | (int(guard.inside_cone) << 20)
            | (int(guard.near_cone) << 21)
            | (int(guard.inside_sphere) << 22)
            | (int(guard.near_sphere) << 23)
            | (int(guard.apex_guard) << 24)
            | (((int(self.node) >> 16) & 1) << 25)
            | (int(guard.cone_triple_index) << 26)
        )

    def receipt_words(self) -> tuple[int, ...]:
        return (
            self.address,
            self.source_rho20,
            self.source_theta18,
            self.wrapped_rho20,
            self.topological_theta18,
            self.contiguous_key & U32_MASK,
            self.contiguous_key >> 32,
            self.morton_key & U32_MASK,
            self.morton_key >> 32,
            self.klb37 & U32_MASK,
            self.klb37 >> 32,
            self.phi_final,
            self.omega_final,
            self.alpha,
            self.branch_word,
            self.packed_state,
            self.klein_left,
            self.klein_up,
            self.klein_up_left,
            self.tag,
        )


@dataclass(frozen=True)
class OperatorBlockReceipt:
    first_luma_ordinal: int
    luma_count: int
    selector_counts: tuple[int, int, int, int]
    operator_state_sha256: bytes


class FullSubstrateCameraProgram:
    """Seed-regenerated profile-2 predictor and receipt oracle."""

    def __init__(
        self,
        recipe: SubstrateTraversalRecipe,
        uglut2_bytes: bytes,
    ) -> None:
        if not 2 <= recipe.width <= 65_534 or not 2 <= recipe.height <= 65_534:
            raise FullSubstrateCameraError(
                "profile 2 dimensions must be in the bounded uint16 range"
            )
        if recipe.width & 1 or recipe.height & 1:
            raise FullSubstrateCameraError("profile 2 requires even dimensions")
        self.recipe = recipe
        self.width = int(recipe.width)
        self.height = int(recipe.height)
        self.root_seed = int(recipe.root_seed)
        self.traversal = tuple(
            int(value)
            for value in derive_substrate_traversal(recipe, uglut2_bytes)
        )
        rho20, theta18 = derive_substrate_coordinate_codes(recipe, uglut2_bytes)
        self._rho20 = tuple(int(value) for value in rho20)
        self._theta18 = tuple(int(value) for value in theta18)
        self._seed_words = tuple(seed_word(self.root_seed, i) for i in range(48))

    def _guards(self, x: int, y: int) -> GuardState:
        qx = q15_pixel_center(x, self.width)
        qy = q15_pixel_center(y, self.height, invert=True)
        apex_x = (self._seed_words[8] & 8191) - 4096
        apex_y = 16_384 + (self._seed_words[9] & 4095)
        triple_index = self._seed_words[16] & 7
        radius_unit, height_unit, slant_unit = PYTHAGOREAN_DELTA_T_LUT[
            triple_index
        ]
        scale = 256 + (self._seed_words[17] & 255)
        radius = scale * radius_unit
        cone_height = scale * height_unit
        slant_t = scale * slant_unit
        if radius * radius + cone_height * cone_height != slant_t * slant_t:
            raise AssertionError("Pythagorean delta-T LUT lost its exact identity")
        guard = 32 + (self._seed_words[12] & 127)
        radial = abs(qx - apex_x)
        down = apex_y - qy
        inside_cone = (
            0 <= down <= cone_height
            and radial * cone_height <= down * radius
        )

        def within_squared_guard(dx: int, dy: int) -> bool:
            return (
                dx <= guard
                and dy <= guard
                and dx * dx + dy * dy <= guard * guard
            )

        apex_guard = within_squared_guard(radial, abs(down))
        corner_dx = abs(radial - radius)
        corner_dy = abs(down - cone_height)
        corner_near = within_squared_guard(corner_dx, corner_dy)
        dot = radial * radius + down * cone_height
        cross = radial * cone_height - down * radius
        if dot < 0:
            side_near = apex_guard
        elif dot > slant_t * slant_t:
            side_near = corner_near
        else:
            side_near = abs(cross) <= guard * slant_t
        base_near = (
            abs(down - cone_height) <= guard
            if radial <= radius
            else corner_near
        )
        near_cone = side_near or base_near

        radius = 3072 + (self._seed_words[13] & 2047)
        center_y = (self._seed_words[14] & 8191) - 4096
        offset = radius + 2048 + (self._seed_words[15] & 2047)
        radius2 = radius * radius
        lower2 = (radius - guard) * (radius - guard)
        upper2 = (radius + guard) * (radius + guard)
        sphere_states = []
        for center_x in (apex_x - offset, apex_x + offset):
            distance2 = (qx - center_x) ** 2 + (qy - center_y) ** 2
            sphere_states.append(
                (distance2 <= radius2, lower2 <= distance2 <= upper2)
            )
        return GuardState(
            inside_cone=inside_cone,
            near_cone=near_cone,
            inside_sphere=sphere_states[0][0] or sphere_states[1][0],
            near_sphere=sphere_states[0][1] or sphere_states[1][1],
            apex_guard=apex_guard,
            cone_triple_index=triple_index,
        )

    def operator_state(self, address: int, frame_ordinal: int) -> OperatorState:
        address = int(address)
        if not 0 <= address < self.width * self.height:
            raise FullSubstrateCameraError("operator address is outside luma")
        frame = _u32(frame_ordinal)
        y, x = divmod(address, self.width)
        source_rho = self._rho20[address]
        source_theta = self._theta18[address]
        unwrapped = source_rho + (self._seed_words[3] & 0x1FFFFF)
        wrapped_rho = unwrapped & RHO20_MASK
        odd = bool((unwrapped >> 20) & 1)
        theta32 = _u32(source_theta << 14)
        if odd:
            theta32 = _u32(0x80000000 - theta32)
        topological_theta = (theta32 >> 14) & THETA18_MASK

        kinematic = frame_kinematics(self.root_seed, frame)
        phi = kinematic.phi
        omega = kinematic.omega
        alpha = kinematic.alpha
        if odd:
            phi = _u32(-phi)
            omega = _u32(-omega)
            alpha = _u32(-alpha)
        phi12 = phi >> 20
        frame14 = frame & 0x3FFF
        contiguous = sclp64_contiguous(
            wrapped_rho,
            topological_theta,
            frame14,
            phi12,
        )
        morton = corrected_morton_key(
            wrapped_rho,
            topological_theta,
            frame14,
            phi12,
        )
        elevation = round_half_up((self.height - 1 - y) * 1023, self.height - 1)
        symbol = mix32(
            self._seed_words[2]
            ^ address
            ^ _u32(frame * 0x85EBCA6B)
        ) & 7
        klb37 = make_klb37(
            wrapped_rho,
            topological_theta,
            elevation,
            symbol,
        )
        klb_low = klb37 & U32_MASK
        klb_high = (klb37 >> 32) & U32_MASK
        lineage_seed, routed_hash = codeword_lineage(
            root_seed=self.root_seed,
            recipe_seed=self.recipe.recipe_seed,
            cartesian_address=address,
            frame_ordinal=frame,
        )
        tag = mix32(
            klb_low
            ^ rotl32(klb_high, 7)
            ^ address
            ^ self._seed_words[4]
            ^ lineage_seed
            ^ rotl32(routed_hash, 11)
        )
        guards = self._guards(x, y)
        left, left_reflected = klein_address(x - 1, y, self.width, self.height)
        up, up_reflected = klein_address(x, y - 1, self.width, self.height)
        up_left, up_left_reflected = klein_address(
            x - 1,
            y - 1,
            self.width,
            self.height,
        )
        topology = (
            int(odd)
            ^ int(guards.inside_cone)
            ^ int(guards.near_cone)
            ^ int(guards.inside_sphere)
            ^ int(guards.near_sphere)
            ^ int(guards.apex_guard)
        )
        node = 0
        prefix = 0
        for depth in range(RADIX_DEPTH):
            radix = (morton >> (63 - depth)) & 1
            route = parity32(
                klb_low
                ^ klb_high
                ^ tag
                ^ self._seed_words[32 + depth]
                ^ node
            )
            branch = radix ^ route ^ topology
            prefix = ((prefix << 1) | branch) & 0xFFFF
            node = 2 * node + 1 + branch
            phi = _u32(phi + omega)
            omega = _u32(omega + alpha)
        selector = (
            node
            ^ tag
            ^ (phi >> 24)
            ^ (omega >> 16)
            ^ (alpha >> 8)
            ^ int(guards.inside_cone)
            ^ int(guards.near_cone)
            ^ int(guards.inside_sphere)
            ^ int(guards.near_sphere)
            ^ int(guards.apex_guard)
        ) & 3
        return OperatorState(
            address=address,
            source_rho20=source_rho,
            source_theta18=source_theta,
            wrapped_rho20=wrapped_rho,
            topological_theta18=topological_theta,
            contiguous_key=contiguous,
            morton_key=morton,
            klb37=klb37,
            phi_final=phi,
            omega_final=omega,
            alpha=alpha,
            node=node,
            prefix=prefix,
            selector=selector,
            elevation10=elevation,
            symbol3=symbol,
            odd_radial_wrap=odd,
            orientation=odd,
            klein_left=left,
            klein_up=up,
            klein_up_left=up_left,
            left_reflected=left_reflected,
            up_reflected=up_reflected,
            up_left_reflected=up_left_reflected,
            guards=guards,
            tag=tag,
        )

    @staticmethod
    def _select(
        plane: bytes,
        address: int,
        left: int,
        up: int,
        up_left: int,
        selector: int,
    ) -> int:
        same_value = plane[address]
        left_value = plane[left]
        up_value = plane[up]
        candidates = (
            same_value,
            left_value,
            up_value,
            median_predictor(left_value, up_value, plane[up_left]),
        )
        return candidates[int(selector)]

    def predictor_packed(
        self,
        previous: DenseYuv420Frame | None,
        frame_ordinal: int,
        *,
        checkpoint: bool,
    ) -> bytes:
        if checkpoint:
            previous_y = bytes(self.width * self.height)
            previous_u = bytes(self.width * self.height // 4)
            previous_v = previous_u
        else:
            if previous is None:
                raise FullSubstrateCameraError("non-checkpoint needs a prior frame")
            if previous.width != self.width or previous.height != self.height:
                raise FullSubstrateCameraError("prior frame dimensions mismatch")
            previous_y, previous_u, previous_v = previous.y, previous.u, previous.v
        output = bytearray(self.width * self.height * 3 // 2)
        write = 0
        chroma_width = self.width // 2
        chroma_height = self.height // 2
        for address in self.traversal:
            state = self.operator_state(address, frame_ordinal)
            output[write] = self._select(
                previous_y,
                address,
                state.klein_left,
                state.klein_up,
                state.klein_up_left,
                state.selector,
            )
            write += 1
            row, column = divmod(address, self.width)
            if row & 1 or column & 1:
                continue
            chroma = (row // 2) * chroma_width + column // 2
            left, _ = klein_address(
                column // 2 - 1,
                row // 2,
                chroma_width,
                chroma_height,
            )
            up, _ = klein_address(
                column // 2,
                row // 2 - 1,
                chroma_width,
                chroma_height,
            )
            up_left, _ = klein_address(
                column // 2 - 1,
                row // 2 - 1,
                chroma_width,
                chroma_height,
            )
            output[write] = self._select(
                previous_u,
                chroma,
                left,
                up,
                up_left,
                state.selector,
            )
            output[write + 1] = self._select(
                previous_v,
                chroma,
                left,
                up,
                up_left,
                state.selector,
            )
            write += 2
        if write != len(output):
            raise AssertionError("profile-2 owner packing changed")
        return bytes(output)

    def residual_for(
        self,
        observed: DenseYuv420Frame,
        previous: DenseYuv420Frame | None,
        frame_ordinal: int,
        *,
        checkpoint: bool,
    ) -> bytes:
        if observed.width != self.width or observed.height != self.height:
            raise FullSubstrateCameraError("observed frame dimensions mismatch")
        observed_packed = pack_codeword420(observed, self.traversal)
        predicted = self.predictor_packed(
            previous,
            frame_ordinal,
            checkpoint=checkpoint,
        )
        return bytes((value - guess) & 255 for value, guess in zip(observed_packed, predicted))

    def reconstruct(
        self,
        residual: bytes,
        previous: DenseYuv420Frame | None,
        *,
        frame_ordinal: int,
        sensor_timestamp_ns: int,
        checkpoint: bool,
    ) -> DenseYuv420Frame:
        if len(residual) != self.width * self.height * 3 // 2:
            raise FullSubstrateCameraError("profile-2 residual length mismatch")
        predicted = self.predictor_packed(
            previous,
            frame_ordinal,
            checkpoint=checkpoint,
        )
        packed = bytes((guess + value) & 255 for guess, value in zip(predicted, residual))
        return unpack_codeword420(
            packed,
            width=self.width,
            height=self.height,
            sensor_timestamp_ns=sensor_timestamp_ns,
            traversal=self.traversal,
        )

    def operator_block_digest(
        self,
        frame_ordinal: int,
        first_traversal_ordinal: int,
        luma_count: int,
    ) -> bytes:
        first = int(first_traversal_ordinal)
        count = int(luma_count)
        if first < 0 or count < 1 or first + count > len(self.traversal):
            raise FullSubstrateCameraError("operator receipt block escapes traversal")
        digest = hashlib.sha256()
        digest.update(OPERATOR_BLOCK_DOMAIN)
        digest.update(struct.pack("<III", _u32(frame_ordinal), first, count))
        for address in self.traversal[first : first + count]:
            words = self.operator_state(address, frame_ordinal).receipt_words()
            digest.update(struct.pack("<20I", *words))
        return digest.digest()

    def operator_blocks(
        self,
        frame_ordinal: int,
        block_luma_addresses: int,
    ) -> tuple[OperatorBlockReceipt, ...]:
        block_size = int(block_luma_addresses)
        if not 1 <= block_size <= 65_536:
            raise FullSubstrateCameraError(
                "operator block luma-address count is invalid"
            )
        blocks = []
        for first in range(0, len(self.traversal), block_size):
            count = min(block_size, len(self.traversal) - first)
            selector_counts = [0, 0, 0, 0]
            for address in self.traversal[first : first + count]:
                selector_counts[
                    self.operator_state(address, frame_ordinal).selector
                ] += 1
            blocks.append(
                OperatorBlockReceipt(
                    first_luma_ordinal=first,
                    luma_count=count,
                    selector_counts=tuple(selector_counts),
                    operator_state_sha256=self.operator_block_digest(
                        frame_ordinal,
                        first,
                        count,
                    ),
                )
            )
        return tuple(blocks)

    def operator_frame_digest(
        self,
        frame_ordinal: int,
        block_luma_addresses: int,
    ) -> bytes:
        blocks = self.operator_blocks(frame_ordinal, block_luma_addresses)
        digest = hashlib.sha256()
        digest.update(OPERATOR_FRAME_DOMAIN)
        digest.update(
            struct.pack(
                "<IIIII",
                self.width,
                self.height,
                _u32(frame_ordinal),
                int(block_luma_addresses),
                len(blocks),
            )
        )
        for block in blocks:
            digest.update(
                struct.pack(
                    "<IIIIII",
                    block.first_luma_ordinal,
                    block.luma_count,
                    *block.selector_counts,
                )
            )
            digest.update(block.operator_state_sha256)
        return digest.digest()

    def receipt_words(
        self,
        frame_ordinal: int,
        addresses: Iterable[int],
    ) -> tuple[tuple[int, ...], ...]:
        return tuple(
            self.operator_state(address, frame_ordinal).receipt_words()
            for address in addresses
        )


__all__ = [
    "FullSubstrateCameraError",
    "FullSubstrateCameraProgram",
    "GuardState",
    "KLB37_BITS",
    "KinematicState",
    "OPERATOR_BLOCK_DOMAIN",
    "OPERATOR_FRAME_DOMAIN",
    "OPERATOR_MEANING",
    "OperatorBlockReceipt",
    "OperatorState",
    "PROFILE_ID",
    "PROFILE_NAME",
    "RADIX_DEPTH",
    "PYTHAGOREAN_DELTA_T_LUT",
    "corrected_morton_key",
    "floor_div",
    "floor_mod",
    "frame_kinematics",
    "klein_address",
    "klb37_even_parity",
    "make_klb37",
    "median_predictor",
    "mix32",
    "operator_meaning_digest",
    "q15_pixel_center",
    "rotl32",
    "sclp64_contiguous",
    "seed_word",
    "triangular32",
    "trunc_div",
]
