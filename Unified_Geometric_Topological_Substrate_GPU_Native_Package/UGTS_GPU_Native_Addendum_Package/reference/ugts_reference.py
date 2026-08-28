#!/usr/bin/env python3
"""Dependency-free reference oracle for UGTS-GN 1.1.

This module is intentionally small and deterministic. It mirrors the bundled
compute shader semantics, supplies binary G64/E32 and G32/E16 packers, and
contains the source-defined glyph encoder as an explicitly versioned transform.
It is a validation oracle, not a replacement for the native Vulkan runtime.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import math
import struct
from typing import Iterable, Sequence

UGTS_ABI_MAJOR = 1
UGTS_ABI_MINOR = 1
G64_BYTES = 64
E32_BYTES = 32
G32_BYTES = 32
E16_BYTES = 16

EVENT_VERIFIED_BIT = 1 << 0
EVENT_ROUTE_BIT = 1 << 1
EVENT_SHEET_SHIFT = 2
EVENT_IN_SUPPORT_BIT = 1 << 10
EVENT_COMPATIBLE_BIT = 1 << 11


@dataclass(frozen=True)
class Query:
    target_sheet: int = 1
    target_orientation: int = 0
    mode_bit: int = 2
    commit: bool = False

    def validate(self) -> None:
        if not 0 <= self.target_sheet <= 255:
            raise ValueError("target_sheet must be in [0,255]")
        if self.target_orientation not in (0, 1):
            raise ValueError("target_orientation must be 0 or 1")
        if not 0 <= self.mode_bit <= 15:
            raise ValueError("mode_bit must be in [0,15]")


@dataclass(frozen=True)
class State:
    position: tuple[float, float, float]
    time: float
    axis: tuple[float, float, float]
    radius: float
    cone_cos: float
    phase: float
    guard_epsilon: float
    confidence_floor: float
    sheet: int
    orientation: int
    compatibility_mask: int
    lineage_seed: int

    def validate(self) -> None:
        if len(self.position) != 3 or len(self.axis) != 3:
            raise ValueError("position and axis must have three components")
        if not all(math.isfinite(v) for v in (*self.position, self.time, *self.axis,
                                               self.radius, self.cone_cos, self.phase,
                                               self.guard_epsilon, self.confidence_floor)):
            raise ValueError("floating fields must be finite")
        if self.radius <= 0:
            raise ValueError("radius must be positive")
        if not -1.0 <= self.cone_cos <= 1.0:
            raise ValueError("cone_cos must be in [-1,1]")
        if self.guard_epsilon < 0:
            raise ValueError("guard_epsilon must be nonnegative")
        if not 0.0 <= self.confidence_floor <= 1.0:
            raise ValueError("confidence_floor must be in [0,1]")
        if not 0 <= self.sheet <= 255 or self.orientation not in (0, 1):
            raise ValueError("topology fields out of range")
        if not 0 <= self.compatibility_mask <= 0xFFFF:
            raise ValueError("compatibility_mask must be 16-bit")
        if not 0 <= self.lineage_seed <= 0xFFFFFFFF:
            raise ValueError("lineage_seed must be 32-bit")


@dataclass(frozen=True)
class Event:
    sdf: float
    guard: float
    confidence: float
    event_time: float
    verified: bool
    route: int
    lineage_hash: int
    in_support: bool
    compatible: bool
    sheet: int
    state_flags: int

    def to_dict(self) -> dict:
        return asdict(self)


def normalize3(v: Sequence[float]) -> tuple[float, float, float]:
    n2 = float(v[0]) ** 2 + float(v[1]) ** 2 + float(v[2]) ** 2
    if n2 <= 0.0 or not math.isfinite(n2):
        return (0.0, 0.0, 1.0)
    inv = 1.0 / math.sqrt(n2)
    return (float(v[0]) * inv, float(v[1]) * inv, float(v[2]) * inv)


def mix32(x: int) -> int:
    """Same 32-bit avalanche mixer used by the shaders."""
    x &= 0xFFFFFFFF
    x ^= x >> 16
    x = (x * 0x7FEB352D) & 0xFFFFFFFF
    x ^= x >> 15
    x = (x * 0x846CA68B) & 0xFFFFFFFF
    x ^= x >> 16
    return x & 0xFFFFFFFF


def evaluate(state: State, query: Query, candidate_index: int = 0) -> Event:
    state.validate()
    query.validate()
    x, y, z = state.position
    r = math.sqrt(x*x + y*y + z*z)
    axis = normalize3(state.axis)
    if r > 0.0:
        cos_to_axis = (x*axis[0] + y*axis[1] + z*axis[2]) / r
    else:
        cos_to_axis = 1.0
    in_support = r <= state.radius and cos_to_axis >= state.cone_cos
    mode_ok = bool(state.compatibility_mask & (1 << query.mode_bit))
    compatible = (mode_ok and state.sheet == query.target_sheet and
                  state.orientation == query.target_orientation)
    sdf = r - state.radius
    guard = abs(sdf) - state.guard_epsilon
    confidence = math.pow(2.0, -32.0 * abs(sdf))
    verified = bool(in_support and compatible and guard <= 0.0 and
                    confidence >= state.confidence_floor)
    route = state.orientation ^ int(verified)
    lineage_hash = mix32(state.lineage_seed ^ int(candidate_index))
    flags = ((int(verified) * EVENT_VERIFIED_BIT) |
             (int(route) * EVENT_ROUTE_BIT) |
             ((state.sheet & 0xFF) << EVENT_SHEET_SHIFT) |
             (int(in_support) * EVENT_IN_SUPPORT_BIT) |
             (int(compatible) * EVENT_COMPATIBLE_BIT))
    return Event(sdf, guard, confidence, state.time, verified, route,
                 lineage_hash, in_support, compatible, state.sheet, flags)


def evaluate_many(states: Iterable[State], query: Query) -> tuple[list[Event], dict[str, int]]:
    events: list[Event] = []
    counters = {"candidates": 0, "supported": 0, "compatible": 0, "verified": 0}
    for i, state in enumerate(states):
        event = evaluate(state, query, i)
        events.append(event)
        counters["candidates"] += 1
        counters["supported"] += int(event.in_support)
        counters["compatible"] += int(event.in_support and event.compatible)
        counters["verified"] += int(event.verified)
    return events, counters


def pack_g64(state: State) -> bytes:
    state.validate()
    floats = (*state.position, state.time, *state.axis, state.radius,
              state.cone_cos, state.phase, state.guard_epsilon,
              state.confidence_floor)
    meta = (state.sheet, state.orientation, state.compatibility_mask,
            state.lineage_seed)
    payload = struct.pack("<12f4I", *floats, *meta)
    assert len(payload) == G64_BYTES
    return payload


def unpack_g64(payload: bytes) -> State:
    if len(payload) != G64_BYTES:
        raise ValueError("G64 payload must be 64 bytes")
    values = struct.unpack("<12f4I", payload)
    return State(position=tuple(values[0:3]), time=values[3], axis=tuple(values[4:7]),
                 radius=values[7], cone_cos=values[8], phase=values[9],
                 guard_epsilon=values[10], confidence_floor=values[11],
                 sheet=values[12], orientation=values[13],
                 compatibility_mask=values[14], lineage_seed=values[15])


def pack_e32(event: Event) -> bytes:
    payload = struct.pack("<4f4I", event.sdf, event.guard, event.confidence,
                          event.event_time, int(event.verified), event.route,
                          event.lineage_hash, event.state_flags)
    assert len(payload) == E32_BYTES
    return payload


def pack_g32(state: State) -> bytes:
    """Pack twelve scalar fields as binary16 plus topology and lineage words."""
    state.validate()
    scalars = (*state.position, state.time, *state.axis, state.radius,
               state.cone_cos, state.phase, state.guard_epsilon,
               state.confidence_floor)
    half_bytes = struct.pack("<12e", *scalars)
    half_words = struct.unpack("<6I", half_bytes)
    topology = ((state.sheet & 0xFF) |
                ((state.orientation & 1) << 8) |
                ((state.compatibility_mask & 0xFFFF) << 9)) & 0xFFFFFFFF
    payload = struct.pack("<8I", *half_words, topology, state.lineage_seed)
    assert len(payload) == G32_BYTES
    return payload


def unpack_g32(payload: bytes) -> State:
    if len(payload) != G32_BYTES:
        raise ValueError("G32 payload must be 32 bytes")
    words = struct.unpack("<8I", payload)
    scalars = struct.unpack("<12e", struct.pack("<6I", *words[:6]))
    topology = words[6]
    return State(position=tuple(float(v) for v in scalars[0:3]), time=float(scalars[3]),
                 axis=tuple(float(v) for v in scalars[4:7]), radius=float(scalars[7]),
                 cone_cos=float(scalars[8]), phase=float(scalars[9]),
                 guard_epsilon=float(scalars[10]), confidence_floor=float(scalars[11]),
                 sheet=topology & 0xFF, orientation=(topology >> 8) & 1,
                 compatibility_mask=(topology >> 9) & 0xFFFF,
                 lineage_seed=words[7])


def pack_e16(event: Event) -> bytes:
    guard_conf = struct.pack("<2e", event.guard, event.confidence)
    guard_conf_word = struct.unpack("<I", guard_conf)[0]
    payload = struct.pack("<f3I", event.sdf, guard_conf_word,
                          event.state_flags, event.lineage_hash)
    assert len(payload) == E16_BYTES
    return payload


def glyph_encode_100_percent(variant: str = "glyph-100100-v1") -> dict:
    """Versioned source-defined visual encoder; never ordinary percentage arithmetic."""
    if variant == "standard":
        return {"variant": variant, "bits": "1", "decimal": 1,
                "expression": "1 << 0", "semantic_scope": "ordinary arithmetic"}
    if variant == "glyph-100101-v0":
        bits = "100101"
    elif variant == "glyph-100100-v1":
        bits = "100100"
    else:
        raise ValueError(f"unknown encoder variant: {variant}")
    value = int(bits, 2)
    active = [i for i, bit in enumerate(reversed(bits)) if bit == "1"]
    expression = " | ".join(f"(1 << {i})" for i in reversed(active))
    return {"variant": variant, "bits": bits, "decimal": value,
            "expression": expression,
            "semantic_scope": "source-defined glyph-to-bit encoding"}


def memory_model(candidates: int, verified: int) -> dict[str, int]:
    if candidates < 0 or verified < 0 or verified > candidates:
        raise ValueError("invalid candidate/event counts")
    return {
        "G64_E32_dense": candidates * (G64_BYTES + E32_BYTES),
        "G32_E16_dense": candidates * (G32_BYTES + E16_BYTES),
        "G32_plus_compact_E16": candidates * G32_BYTES + verified * E16_BYTES,
        "compact_E16_log_only": verified * E16_BYTES,
        "one_bit_support_mask": (candidates + 7) // 8,
    }


def pythagorean_cup_step(level: float, inflow: float, threshold: float,
                         reset_level: float = 0.0, hysteresis: float = 0.0,
                         latched: bool = False) -> tuple[float, bool, bool]:
    """A bounded threshold/reset abstraction, not a vacuum or energy source."""
    if threshold <= reset_level or hysteresis < 0:
        raise ValueError("invalid threshold/reset parameters")
    level = max(reset_level, level + inflow)
    triggered = False
    if not latched and level >= threshold:
        latched = True
        triggered = True
        level = reset_level
    elif latched and level <= reset_level + hysteresis:
        latched = False
    return level, latched, triggered


if __name__ == "__main__":
    import json
    demo = glyph_encode_100_percent()
    print(json.dumps(demo, indent=2))
