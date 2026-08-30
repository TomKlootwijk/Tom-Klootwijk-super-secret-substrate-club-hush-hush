"""Keyframe clips, easing, playback, crossfades and lightweight state machines."""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Iterable, Mapping, Sequence

AnimValue = float | tuple[float, ...]


def _finite_value(value: Any) -> AnimValue:
    if isinstance(value, (int, float)):
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("animation values must be finite")
        return value
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        result = tuple(float(v) for v in value)
        if not result or not all(math.isfinite(v) for v in result):
            raise ValueError("animation vector values must be finite and non-empty")
        return result
    raise TypeError("animation values must be numbers or numeric sequences")


def easing(name: str, t: float) -> float:
    t = max(0.0, min(1.0, float(t)))
    if name == "linear":
        return t
    if name == "step":
        return 0.0
    if name == "ease_in":
        return t * t
    if name == "ease_out":
        return 1.0 - (1.0 - t) * (1.0 - t)
    if name == "ease_in_out":
        return 2 * t * t if t < 0.5 else 1 - ((-2 * t + 2) ** 2) / 2
    if name == "smoothstep":
        return t * t * (3.0 - 2.0 * t)
    if name == "smootherstep":
        return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)
    if name == "back_out":
        c1 = 1.70158
        c3 = c1 + 1.0
        x = t - 1.0
        return 1.0 + c3 * x * x * x + c1 * x * x
    if name == "elastic_out":
        if t in {0.0, 1.0}:
            return t
        c4 = (2.0 * math.pi) / 3.0
        return (2.0 ** (-10.0 * t)) * math.sin((t * 10.0 - 0.75) * c4) + 1.0
    raise ValueError(f"unsupported easing: {name}")


def interpolate(a: AnimValue, b: AnimValue, t: float) -> AnimValue:
    if isinstance(a, tuple) != isinstance(b, tuple):
        raise TypeError("animation keyframe value types must match")
    if isinstance(a, tuple):
        if len(a) != len(b):  # type: ignore[arg-type]
            raise ValueError("animation vector dimensions must match")
        return tuple(x + (y - x) * t for x, y in zip(a, b))  # type: ignore[arg-type]
    return a + (b - a) * t  # type: ignore[operator]


@dataclass(frozen=True)
class Keyframe:
    time: float
    value: AnimValue
    easing: str = "linear"

    def __post_init__(self) -> None:
        time = float(self.time)
        if not math.isfinite(time) or time < 0:
            raise ValueError("keyframe time must be finite and non-negative")
        object.__setattr__(self, "time", time)
        object.__setattr__(self, "value", _finite_value(self.value))
        easing(self.easing, 0.5)

    def to_dict(self) -> dict[str, Any]:
        value: Any = list(self.value) if isinstance(self.value, tuple) else self.value
        return {"time": self.time, "value": value, "easing": self.easing}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Keyframe":
        return cls(float(data["time"]), _finite_value(data["value"]), str(data.get("easing", "linear")))


@dataclass(frozen=True)
class AnimationTrack:
    target: str
    keyframes: tuple[Keyframe, ...]

    def validate(self) -> None:
        if not self.target:
            raise ValueError("animation track target is required")
        if not self.keyframes:
            raise ValueError("animation track requires keyframes")
        times = [frame.time for frame in self.keyframes]
        if times != sorted(times):
            raise ValueError("keyframes must be ordered by time")
        if len(set(times)) != len(times):
            raise ValueError("keyframe times must be unique")
        first_type = isinstance(self.keyframes[0].value, tuple)
        first_len = len(self.keyframes[0].value) if first_type else None  # type: ignore[arg-type]
        for frame in self.keyframes:
            if isinstance(frame.value, tuple) != first_type:
                raise TypeError("all keyframe value types must match")
            if first_type and len(frame.value) != first_len:  # type: ignore[arg-type]
                raise ValueError("all keyframe vector dimensions must match")

    @property
    def duration(self) -> float:
        return self.keyframes[-1].time

    def sample(self, time: float) -> AnimValue:
        self.validate()
        if time <= self.keyframes[0].time:
            return self.keyframes[0].value
        if time >= self.keyframes[-1].time:
            return self.keyframes[-1].value
        for left, right in zip(self.keyframes, self.keyframes[1:]):
            if left.time <= time <= right.time:
                span = right.time - left.time
                local = 0.0 if span <= 0 else (time - left.time) / span
                return interpolate(left.value, right.value, easing(right.easing, local))
        return self.keyframes[-1].value

    def to_dict(self) -> dict[str, Any]:
        return {"target": self.target, "keyframes": [frame.to_dict() for frame in self.keyframes]}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AnimationTrack":
        track = cls(str(data["target"]), tuple(Keyframe.from_dict(frame) for frame in data["keyframes"]))
        track.validate()
        return track


@dataclass(frozen=True)
class AnimationClip:
    id: str
    tracks: tuple[AnimationTrack, ...]
    duration: float | None = None
    loop_mode: str = "once"
    speed: float = 1.0

    def validate(self) -> None:
        if not self.id:
            raise ValueError("clip id is required")
        if not self.tracks:
            raise ValueError("clip requires tracks")
        if self.loop_mode not in {"once", "loop", "pingpong"}:
            raise ValueError("loop_mode must be once, loop or pingpong")
        if not math.isfinite(self.speed) or self.speed <= 0:
            raise ValueError("clip speed must be positive and finite")
        targets: set[str] = set()
        for track in self.tracks:
            track.validate()
            if track.target in targets:
                raise ValueError(f"duplicate animation target: {track.target}")
            targets.add(track.target)
        duration = self.resolved_duration
        if duration <= 0:
            raise ValueError("clip duration must be positive")

    @property
    def resolved_duration(self) -> float:
        inferred = max((track.duration for track in self.tracks), default=0.0)
        return inferred if self.duration is None else float(self.duration)

    def local_time(self, time: float) -> tuple[float, bool]:
        duration = self.resolved_duration
        scaled = max(0.0, time * self.speed)
        if self.loop_mode == "once":
            return min(duration, scaled), scaled >= duration
        if self.loop_mode == "loop":
            return scaled % duration, False
        period = duration * 2.0
        phase = scaled % period
        return (phase if phase <= duration else period - phase), False

    def sample(self, time: float) -> dict[str, AnimValue]:
        local, _ = self.local_time(time)
        return {track.target: track.sample(local) for track in self.tracks}

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tracks": [track.to_dict() for track in self.tracks],
            "duration": self.duration,
            "loop_mode": self.loop_mode,
            "speed": self.speed,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AnimationClip":
        clip = cls(
            str(data["id"]),
            tuple(AnimationTrack.from_dict(track) for track in data["tracks"]),
            None if data.get("duration") is None else float(data["duration"]),
            str(data.get("loop_mode", "once")),
            float(data.get("speed", 1.0)),
        )
        clip.validate()
        return clip


def blend_samples(a: Mapping[str, AnimValue], b: Mapping[str, AnimValue], t: float) -> dict[str, AnimValue]:
    t = max(0.0, min(1.0, float(t)))
    result: dict[str, AnimValue] = {}
    for key in sorted(set(a) | set(b)):
        if key in a and key in b:
            result[key] = interpolate(a[key], b[key], t)
        elif key in b:
            result[key] = b[key]
        else:
            result[key] = a[key]
    return result


class AnimationPlayer:
    def __init__(self, clips: Iterable[AnimationClip] = ()):
        self.clips: dict[str, AnimationClip] = {}
        for clip in clips:
            self.add_clip(clip)
        self.current: str | None = None
        self.time = 0.0
        self.playing = False
        self._fade_from: str | None = None
        self._fade_from_time = 0.0
        self._fade_duration = 0.0
        self._fade_elapsed = 0.0

    def add_clip(self, clip: AnimationClip, replace_existing: bool = False) -> None:
        clip.validate()
        if clip.id in self.clips and not replace_existing:
            raise ValueError(f"clip already exists: {clip.id}")
        self.clips[clip.id] = clip

    def play(self, clip_id: str, restart: bool = True, fade: float = 0.0) -> None:
        if clip_id not in self.clips:
            raise KeyError(clip_id)
        if fade < 0:
            raise ValueError("fade must be non-negative")
        if self.current == clip_id and not restart:
            self.playing = True
            return
        if fade > 0 and self.current is not None:
            self._fade_from = self.current
            self._fade_from_time = self.time
            self._fade_duration = float(fade)
            self._fade_elapsed = 0.0
        else:
            self._fade_from = None
        self.current = clip_id
        self.time = 0.0 if restart else self.time
        self.playing = True

    def stop(self, reset: bool = False) -> None:
        self.playing = False
        if reset:
            self.time = 0.0

    @property
    def finished(self) -> bool:
        if self.current is None:
            return True
        _, finished = self.clips[self.current].local_time(self.time)
        return finished

    def update(self, dt: float) -> dict[str, AnimValue]:
        if dt < 0 or not math.isfinite(dt):
            raise ValueError("animation dt must be finite and non-negative")
        if self.current is None:
            return {}
        if self.playing:
            self.time += dt
            if self.clips[self.current].loop_mode == "once" and self.finished:
                self.playing = False
        sample = self.clips[self.current].sample(self.time)
        if self._fade_from is not None:
            self._fade_elapsed += dt
            from_sample = self.clips[self._fade_from].sample(self._fade_from_time + self._fade_elapsed)
            t = 1.0 if self._fade_duration <= 0 else min(1.0, self._fade_elapsed / self._fade_duration)
            sample = blend_samples(from_sample, sample, easing("smoothstep", t))
            if t >= 1.0:
                self._fade_from = None
        return sample

    def snapshot(self) -> dict[str, Any]:
        return {
            "current": self.current,
            "time": self.time,
            "playing": self.playing,
            "fade_from": self._fade_from,
            "fade_from_time": self._fade_from_time,
            "fade_duration": self._fade_duration,
            "fade_elapsed": self._fade_elapsed,
        }

    def restore(self, state: Mapping[str, Any]) -> None:
        current = state.get("current")
        if current is not None and current not in self.clips:
            raise KeyError(current)
        self.current = current
        self.time = float(state.get("time", 0.0))
        self.playing = bool(state.get("playing", False))
        self._fade_from = state.get("fade_from")
        self._fade_from_time = float(state.get("fade_from_time", 0.0))
        self._fade_duration = float(state.get("fade_duration", 0.0))
        self._fade_elapsed = float(state.get("fade_elapsed", 0.0))


@dataclass(frozen=True)
class AnimationTransition:
    source: str
    target: str
    parameter: str
    operator: str
    value: float | bool | str
    fade: float = 0.1

    def matches(self, parameters: Mapping[str, Any]) -> bool:
        current = parameters.get(self.parameter)
        if self.operator == "==":
            return current == self.value
        if self.operator == "!=":
            return current != self.value
        if self.operator == ">":
            return current is not None and float(current) > float(self.value)
        if self.operator == ">=":
            return current is not None and float(current) >= float(self.value)
        if self.operator == "<":
            return current is not None and float(current) < float(self.value)
        if self.operator == "<=":
            return current is not None and float(current) <= float(self.value)
        if self.operator == "truthy":
            return bool(current)
        raise ValueError(f"unsupported transition operator: {self.operator}")


class AnimationStateMachine:
    def __init__(self, player: AnimationPlayer, initial_state: str, transitions: Iterable[AnimationTransition] = ()):
        if initial_state not in player.clips:
            raise KeyError(initial_state)
        self.player = player
        self.state = initial_state
        self.transitions = tuple(transitions)
        self.parameters: dict[str, Any] = {}
        self.player.play(initial_state)

    def set(self, name: str, value: Any) -> None:
        self.parameters[name] = value

    def update(self, dt: float) -> dict[str, AnimValue]:
        for transition in self.transitions:
            if transition.source in {self.state, "*"} and transition.matches(self.parameters):
                self.state = transition.target
                self.player.play(transition.target, fade=transition.fade)
                break
        return self.player.update(dt)


def apply_animation_sample(target: dict[str, Any], sample: Mapping[str, AnimValue]) -> None:
    """Apply dotted-path animation values to nested dictionaries in place."""
    for path, value in sample.items():
        parts = path.split(".")
        cursor: dict[str, Any] = target
        for part in parts[:-1]:
            existing = cursor.get(part)
            if not isinstance(existing, dict):
                existing = {}
                cursor[part] = existing
            cursor = existing
        cursor[parts[-1]] = list(value) if isinstance(value, tuple) else value
