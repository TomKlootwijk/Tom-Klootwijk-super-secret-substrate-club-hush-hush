"""Action-oriented keyboard, pointer, gamepad and touch input contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


@dataclass(frozen=True)
class InputBinding:
    kind: str
    code: str
    scale: float = 1.0
    device: int = 0

    def validate(self) -> None:
        if self.kind not in {"key", "pointer_button", "gamepad_button", "gamepad_axis", "touch_axis"}:
            raise ValueError(f"unsupported input binding kind: {self.kind}")
        if not self.code:
            raise ValueError("input binding code is required")
        if not math.isfinite(self.scale):
            raise ValueError("input binding scale must be finite")
        if self.device < 0:
            raise ValueError("device index must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "code": self.code, "scale": self.scale, "device": self.device}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "InputBinding":
        binding = cls(str(data["kind"]), str(data["code"]), float(data.get("scale", 1.0)), int(data.get("device", 0)))
        binding.validate()
        return binding


@dataclass(frozen=True)
class ActionDefinition:
    name: str
    bindings: tuple[InputBinding, ...]
    deadzone: float = 0.15
    threshold: float = 0.5
    combine: str = "sum"

    def validate(self) -> None:
        if not self.name:
            raise ValueError("action name is required")
        if not self.bindings:
            raise ValueError(f"action {self.name} requires at least one binding")
        if not 0 <= self.deadzone < 1:
            raise ValueError("deadzone must be in [0, 1)")
        if not 0 < self.threshold <= 1:
            raise ValueError("threshold must be in (0, 1]")
        if self.combine not in {"sum", "max"}:
            raise ValueError("combine must be sum or max")
        for binding in self.bindings:
            binding.validate()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "bindings": [b.to_dict() for b in self.bindings],
            "deadzone": self.deadzone,
            "threshold": self.threshold,
            "combine": self.combine,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ActionDefinition":
        action = cls(
            str(data["name"]),
            tuple(InputBinding.from_dict(b) for b in data["bindings"]),
            float(data.get("deadzone", 0.15)),
            float(data.get("threshold", 0.5)),
            str(data.get("combine", "sum")),
        )
        action.validate()
        return action


@dataclass(frozen=True)
class RawInputState:
    keys: frozenset[str] = frozenset()
    pointer_buttons: frozenset[str] = frozenset()
    gamepad_buttons: Mapping[str, float] = field(default_factory=dict)
    gamepad_axes: Mapping[str, float] = field(default_factory=dict)
    touch_axes: Mapping[str, float] = field(default_factory=dict)
    pointer_position: tuple[float, float] = (0.0, 0.0)

    def value_for(self, binding: InputBinding) -> float:
        if binding.kind == "key":
            value = 1.0 if binding.code in self.keys else 0.0
        elif binding.kind == "pointer_button":
            value = 1.0 if binding.code in self.pointer_buttons else 0.0
        elif binding.kind == "gamepad_button":
            value = float(self.gamepad_buttons.get(f"{binding.device}:{binding.code}", self.gamepad_buttons.get(binding.code, 0.0)))
        elif binding.kind == "gamepad_axis":
            value = float(self.gamepad_axes.get(f"{binding.device}:{binding.code}", self.gamepad_axes.get(binding.code, 0.0)))
        else:
            value = float(self.touch_axes.get(binding.code, 0.0))
        if not math.isfinite(value):
            return 0.0
        return max(-1.0, min(1.0, value)) * binding.scale


@dataclass(frozen=True)
class InputFrame:
    values: Mapping[str, float] = field(default_factory=dict)
    previous_values: Mapping[str, float] = field(default_factory=dict)
    thresholds: Mapping[str, float] = field(default_factory=dict)
    pointer_position: tuple[float, float] = (0.0, 0.0)
    frame_index: int = 0

    def value(self, action: str, default: float = 0.0) -> float:
        return float(self.values.get(action, default))

    def down(self, action: str) -> bool:
        threshold = float(self.thresholds.get(action, 0.5))
        return abs(self.value(action)) >= threshold

    def pressed(self, action: str) -> bool:
        threshold = float(self.thresholds.get(action, 0.5))
        return abs(self.value(action)) >= threshold and abs(float(self.previous_values.get(action, 0.0))) < threshold

    def released(self, action: str) -> bool:
        threshold = float(self.thresholds.get(action, 0.5))
        return abs(self.value(action)) < threshold and abs(float(self.previous_values.get(action, 0.0))) >= threshold

    def vector(self, x_action: str, y_action: str, normalize: bool = True) -> tuple[float, float]:
        x, y = self.value(x_action), self.value(y_action)
        magnitude = math.hypot(x, y)
        if normalize and magnitude > 1.0:
            return x / magnitude, y / magnitude
        return x, y

    def to_dict(self) -> dict[str, Any]:
        return {
            "values": {k: float(v) for k, v in sorted(self.values.items())},
            "previous_values": {k: float(v) for k, v in sorted(self.previous_values.items())},
            "thresholds": {k: float(v) for k, v in sorted(self.thresholds.items())},
            "pointer_position": list(self.pointer_position),
            "frame_index": self.frame_index,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "InputFrame":
        return cls(
            {str(k): float(v) for k, v in data.get("values", {}).items()},
            {str(k): float(v) for k, v in data.get("previous_values", {}).items()},
            {str(k): float(v) for k, v in data.get("thresholds", {}).items()},
            tuple(float(v) for v in data.get("pointer_position", (0, 0))),  # type: ignore[arg-type]
            int(data.get("frame_index", 0)),
        )


class InputMap:
    def __init__(self, actions: Iterable[ActionDefinition] = ()):
        self.actions: dict[str, ActionDefinition] = {}
        for action in actions:
            self.add_action(action)

    def add_action(self, action: ActionDefinition, replace_existing: bool = False) -> None:
        action.validate()
        if action.name in self.actions and not replace_existing:
            raise ValueError(f"action already exists: {action.name}")
        self.actions[action.name] = action

    def bind(
        self,
        action: str,
        kind: str,
        code: str,
        scale: float = 1.0,
        device: int = 0,
        *,
        deadzone: float = 0.15,
        threshold: float = 0.5,
        combine: str = "sum",
    ) -> None:
        binding = InputBinding(kind, code, scale, device)
        binding.validate()
        existing = self.actions.get(action)
        if existing is None:
            definition = ActionDefinition(action, (binding,), deadzone, threshold, combine)
        else:
            definition = ActionDefinition(action, existing.bindings + (binding,), existing.deadzone, existing.threshold, existing.combine)
        self.add_action(definition, replace_existing=True)

    def evaluate(self, raw: RawInputState, previous: InputFrame | None = None, frame_index: int | None = None) -> InputFrame:
        values: dict[str, float] = {}
        thresholds: dict[str, float] = {}
        for name in sorted(self.actions):
            action = self.actions[name]
            samples = [raw.value_for(binding) for binding in action.bindings]
            if action.combine == "max":
                value = max(samples, key=abs, default=0.0)
            else:
                value = max(-1.0, min(1.0, sum(samples)))
            if abs(value) < action.deadzone:
                value = 0.0
            else:
                # Rescale after the deadzone for a smooth full-range axis.
                sign = 1.0 if value >= 0 else -1.0
                value = sign * min(1.0, (abs(value) - action.deadzone) / (1.0 - action.deadzone))
            values[name] = value
            thresholds[name] = action.threshold
        previous_values = {} if previous is None else dict(previous.values)
        index = (0 if previous is None else previous.frame_index + 1) if frame_index is None else int(frame_index)
        return InputFrame(values, previous_values, thresholds, raw.pointer_position, index)

    def frame_from_actions(self, values: Mapping[str, float], previous: InputFrame | None = None) -> InputFrame:
        thresholds = {name: action.threshold for name, action in self.actions.items()}
        normalized = {name: max(-1.0, min(1.0, float(values.get(name, 0.0)))) for name in self.actions}
        previous_values = {} if previous is None else dict(previous.values)
        return InputFrame(normalized, previous_values, thresholds, frame_index=0 if previous is None else previous.frame_index + 1)

    def validate(self) -> None:
        if not self.actions:
            raise ValueError("input map requires at least one action")
        for action in self.actions.values():
            action.validate()

    def to_dict(self) -> dict[str, Any]:
        return {"actions": [self.actions[name].to_dict() for name in sorted(self.actions)]}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "InputMap":
        return cls(ActionDefinition.from_dict(item) for item in data.get("actions", []))


class InputRecorder:
    """Deterministic recording for tests, replays and tool-assisted input."""

    def __init__(self):
        self.frames: list[InputFrame] = []

    def append(self, frame: InputFrame) -> None:
        expected = len(self.frames)
        if frame.frame_index != expected:
            frame = InputFrame(frame.values, frame.previous_values, frame.thresholds, frame.pointer_position, expected)
        self.frames.append(frame)

    def frame(self, index: int) -> InputFrame:
        return self.frames[index]

    def to_dict(self) -> dict[str, Any]:
        return {"schema": "ugts-kc-input-recording-1", "frames": [frame.to_dict() for frame in self.frames]}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "InputRecorder":
        if data.get("schema") != "ugts-kc-input-recording-1":
            raise ValueError("unsupported input recording schema")
        recorder = cls()
        recorder.frames = [InputFrame.from_dict(frame) for frame in data.get("frames", [])]
        return recorder

    def write(self, path: str | Path) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return output
