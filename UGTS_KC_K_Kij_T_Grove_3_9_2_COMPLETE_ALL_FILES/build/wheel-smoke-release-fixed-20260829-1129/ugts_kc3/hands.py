"""Typed left/right hand input and bimanual transform calculus."""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Mapping

from .math3d import (
    EPS,
    add,
    compose_trs,
    distance,
    mat4_mul,
    mat4_translation,
    matrix_translation,
    norm,
    normalize,
    quat_from_axis_angle,
    quat_from_two_vectors,
    quat_inverse,
    quat_mul,
    quat_nlerp,
    signed_twist_angle,
    scale,
    sub,
)

Vec3 = tuple[float, float, float]
Quat = tuple[float, float, float, float]


@dataclass(frozen=True)
class HandPose:
    side: str
    wrist_position: Vec3
    wrist_orientation: Quat = (1.0, 0.0, 0.0, 0.0)
    joints: Mapping[str, Vec3] = field(default_factory=dict, compare=False)
    joint_radii: Mapping[str, float] = field(default_factory=dict, compare=False)
    confidence: float = 1.0
    tracked: bool = True
    source: str = "synthetic"
    timestamp: float = 0.0

    def validate(self):
        if self.side not in {"left", "right"}:
            raise ValueError("hand side must be left or right")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0,1]")
        if any(r < 0 for r in self.joint_radii.values()):
            raise ValueError("joint radii must be nonnegative")

    def joint(self, name: str, fallback_to_wrist: bool = False) -> Vec3:
        if name in self.joints:
            return self.joints[name]
        if fallback_to_wrist:
            return self.wrist_position
        raise KeyError(name)

    def pinch_distance(self, thumb: str = "thumb_tip", index: str = "index_tip") -> float:
        return distance(self.joint(thumb), self.joint(index))


@dataclass(frozen=True)
class PinchUpdate:
    side: str
    active: bool
    changed: bool
    distance: float
    reason: str
    timestamp: float


class PinchDetector:
    def __init__(self, side: str, enter_distance: float = 0.025, exit_distance: float = 0.035, confidence_floor: float = 0.5):
        if side not in {"left", "right"}:
            raise ValueError("invalid side")
        if enter_distance <= 0 or exit_distance <= enter_distance:
            raise ValueError("pinch hysteresis requires 0 < enter < exit")
        self.side = side
        self.enter_distance = enter_distance
        self.exit_distance = exit_distance
        self.confidence_floor = confidence_floor
        self.active = False

    def update(self, pose: HandPose) -> PinchUpdate:
        pose.validate()
        if pose.side != self.side:
            raise ValueError("pose side does not match detector")
        if not pose.tracked or pose.confidence < self.confidence_floor:
            changed = self.active
            self.active = False
            return PinchUpdate(self.side, False, changed, float("inf"), "tracking_unavailable", pose.timestamp)
        try:
            d = pose.pinch_distance()
        except KeyError:
            changed = self.active
            self.active = False
            return PinchUpdate(self.side, False, changed, float("inf"), "missing_joint", pose.timestamp)
        previous = self.active
        if not self.active and d <= self.enter_distance:
            self.active = True
        elif self.active and d >= self.exit_distance:
            self.active = False
        reason = "pinch_enter" if self.active and not previous else "pinch_exit" if previous and not self.active else "pinch_hold" if self.active else "open_hold"
        return PinchUpdate(self.side, self.active, previous != self.active, d, reason, pose.timestamp)


@dataclass(frozen=True)
class BimanualAnchor:
    left: HandPose
    right: HandPose
    object_initial_world: tuple

    def validate(self, confidence_floor: float = 0.5):
        self.left.validate()
        self.right.validate()
        if self.left.side != "left" or self.right.side != "right":
            raise ValueError("anchor requires left and right poses")
        if not self.left.tracked or not self.right.tracked:
            raise ValueError("both anchor hands must be tracked")
        if min(self.left.confidence, self.right.confidence) < confidence_floor:
            raise ValueError("anchor confidence below floor")
        if distance(self.left.wrist_position, self.right.wrist_position) <= EPS:
            raise ValueError("anchor hand separation is degenerate")


@dataclass(frozen=True)
class BimanualResult:
    world_transform: tuple
    translation: Vec3
    rotation: Quat
    scale: float
    twist_radians: float
    confidence: float
    status: str


def midpoint(a: Vec3, b: Vec3) -> Vec3:
    return scale(add(a, b), 0.5)


def compute_bimanual_transform(
    anchor: BimanualAnchor,
    left: HandPose,
    right: HandPose,
    confidence_floor: float = 0.5,
    min_scale: float = 0.05,
    max_scale: float = 20.0,
) -> BimanualResult:
    anchor.validate(confidence_floor)
    left.validate()
    right.validate()
    if left.side != "left" or right.side != "right":
        raise ValueError("current poses must be left/right")
    confidence = min(left.confidence, right.confidence)
    if not left.tracked or not right.tracked or confidence < confidence_floor:
        return BimanualResult(anchor.object_initial_world, (0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0), 1.0, 0.0, confidence, "tracking_rejected")

    a0 = sub(anchor.right.wrist_position, anchor.left.wrist_position)
    a1 = sub(right.wrist_position, left.wrist_position)
    d0, d1 = norm(a0), norm(a1)
    if d0 <= EPS or d1 <= EPS:
        return BimanualResult(anchor.object_initial_world, (0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0), 1.0, 0.0, confidence, "separation_degenerate")

    m0 = midpoint(anchor.left.wrist_position, anchor.right.wrist_position)
    m1 = midpoint(left.wrist_position, right.wrist_position)
    translation = sub(m1, m0)
    scale_value = max(min_scale, min(max_scale, d1 / d0))

    q_align = quat_from_two_vectors(a0, a1)
    q_left_delta = quat_mul(left.wrist_orientation, quat_inverse(anchor.left.wrist_orientation))
    q_right_delta = quat_mul(right.wrist_orientation, quat_inverse(anchor.right.wrist_orientation))
    q_average = quat_nlerp(q_left_delta, q_right_delta, 0.5)
    current_axis = normalize(a1)
    twist_angle = signed_twist_angle(q_average, current_axis)
    q_twist = quat_from_axis_angle(current_axis, twist_angle)
    rotation = quat_mul(q_twist, q_align)

    # Delta maps the original two-hand midpoint to the current midpoint, then transforms the object.
    delta = mat4_mul(
        mat4_translation(m1),
        mat4_mul(compose_trs(rotation=rotation, scale_value=scale_value), mat4_translation(scale(m0, -1.0))),
    )
    world = mat4_mul(delta, anchor.object_initial_world)
    return BimanualResult(world, translation, rotation, scale_value, twist_angle, confidence, "ok")


@dataclass(frozen=True)
class HandInteractionEvent:
    event_type: str
    object_id: str
    hands: tuple[str, ...]
    timestamp: float
    lineage_label: str


class CooperativeGrab:
    """Small ownership state machine for one- and two-hand grabs and handovers."""

    def __init__(self, object_id: str):
        self.object_id = object_id
        self.owners: set[str] = set()
        self.sequence = 0

    def _event(self, kind: str, timestamp: float) -> HandInteractionEvent:
        self.sequence += 1
        return HandInteractionEvent(kind, self.object_id, tuple(sorted(self.owners)), timestamp, f"grab:{self.object_id}:{self.sequence}")

    def update(self, left_active: bool, right_active: bool, timestamp: float) -> tuple[HandInteractionEvent, ...]:
        desired = {side for side, active in (("left", left_active), ("right", right_active)) if active}
        previous = set(self.owners)
        if desired == previous:
            return ()
        events: list[HandInteractionEvent] = []
        if not previous and desired:
            self.owners = desired
            events.append(self._event("grab_start" if len(desired) == 1 else "bimanual_grab_start", timestamp))
        elif previous and not desired:
            self.owners = set()
            events.append(self._event("grab_release", timestamp))
        elif len(previous) == 1 and len(desired) == 2:
            self.owners = desired
            events.append(self._event("second_hand_join", timestamp))
        elif len(previous) == 2 and len(desired) == 1:
            self.owners = desired
            events.append(self._event("handover", timestamp))
        else:
            self.owners = desired
            events.append(self._event("ownership_change", timestamp))
        return tuple(events)


def emulate_hand_from_cursor(side: str, cursor_xy: tuple[float, float], pinch: bool, timestamp: float = 0.0) -> HandPose:
    """Desktop fallback that maps a cursor to a planar synthetic hand pose."""
    x, y = cursor_xy
    gap = 0.012 if pinch else 0.06
    wrist = (x, y, 0.0)
    joints = {
        "thumb_tip": (x - gap * 0.5, y, 0.0),
        "index_tip": (x + gap * 0.5, y, 0.0),
    }
    return HandPose(side, wrist, joints=joints, confidence=1.0, tracked=True, source="desktop_emulation", timestamp=timestamp)
