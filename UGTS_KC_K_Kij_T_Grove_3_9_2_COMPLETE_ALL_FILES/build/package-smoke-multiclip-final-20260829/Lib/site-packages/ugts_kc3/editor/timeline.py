"""Child-friendly transform-animation timeline for UGTS Studio.

The panel is deliberately independent from :class:`EditorDocument`.  It emits
plain values and dictionaries so the main window can record every authored
change through its shared undo stack while scrubbing remains presentation-only.
"""
from __future__ import annotations

import copy
import math
from typing import Any, Mapping, Sequence

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


TRANSFORM_ANIMATION_SCHEMA = "ugts-studio-transform-animation-view-1"

_LOOP_CHOICES = (
    ("Once", "once"),
    ("Repeat", "loop"),
    ("Back and forth", "pingpong"),
)
_EASING_CHOICES = (
    ("Straight", "linear"),
    ("Start gently", "ease_in"),
    ("Stop gently", "ease_out"),
    ("Gently at both ends", "ease_in_out"),
    ("Smooth", "smoothstep"),
    ("Extra smooth", "smootherstep"),
    ("Slight overshoot", "back_out"),
    ("Springy", "elastic_out"),
    ("Jump", "step"),
)
_SLIDER_STEPS = 2000
_TIME_EPSILON = 1.0e-6


def _spin(
    *,
    minimum: float,
    maximum: float,
    step: float,
    decimals: int,
    value: float,
    accessible_name: str,
) -> QDoubleSpinBox:
    widget = QDoubleSpinBox()
    widget.setRange(minimum, maximum)
    widget.setSingleStep(step)
    widget.setDecimals(decimals)
    widget.setValue(value)
    widget.setKeyboardTracking(False)
    widget.setAccelerated(True)
    widget.setAccessibleName(accessible_name)
    return widget


def _finite_triplet(value: Any, label: str) -> tuple[float, float, float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 3:
        raise ValueError(f"{label} must contain X, Y and Z values")
    result = tuple(float(item) for item in value)
    if not all(math.isfinite(item) for item in result):
        raise ValueError(f"{label} values must be finite")
    return result  # type: ignore[return-value]


def _euler_to_quaternion(
    rotation: Sequence[float],
) -> tuple[float, float, float, float]:
    roll, pitch, yaw = (math.radians(float(value)) * 0.5 for value in rotation)
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    values = (
        cr * cp * cy + sr * sp * sy,
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
    )
    length = math.sqrt(sum(value * value for value in values))
    return tuple(value / length for value in values)  # type: ignore[return-value]


def _quaternion_to_euler(
    rotation: Sequence[float],
) -> tuple[float, float, float]:
    w, x, y, z = rotation
    sinr_cosp = 2.0 * (w * x + y * z)
    cosr_cosp = 1.0 - 2.0 * (x * x + y * y)
    roll = math.atan2(sinr_cosp, cosr_cosp)
    sinp = max(-1.0, min(1.0, 2.0 * (w * y - z * x)))
    pitch = math.asin(sinp)
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    yaw = math.atan2(siny_cosp, cosy_cosp)
    return tuple(math.degrees(value) for value in (roll, pitch, yaw))  # type: ignore[return-value]


def _rotation_nlerp(
    left: Sequence[float], right: Sequence[float], amount: float
) -> tuple[float, float, float]:
    first = _euler_to_quaternion(left)
    second = _euler_to_quaternion(right)
    if sum(a * b for a, b in zip(first, second)) < 0.0:
        second = tuple(-value for value in second)
    blended = tuple(
        a + (b - a) * amount for a, b in zip(first, second)
    )
    length = math.sqrt(sum(value * value for value in blended))
    if length <= 1.0e-12:
        return _quaternion_to_euler(first)
    return _quaternion_to_euler(tuple(value / length for value in blended))


class AnimationTimelinePanel(QWidget):
    """One compact, accessible transform-animation authoring surface.

    Clip dictionaries use this intentionally small schema::

        {
          "schema": "ugts-studio-transform-animation-view-1",
          "duration": 2.0,
          "loop_mode": "once",
          "keys": [{
            "time": 0.0,
            "translation": [0.0, 0.0, 0.0],
            "rotation": [0.0, 0.0, 0.0],
            "scale": [1.0, 1.0, 1.0],
            "easing": "smoothstep"
          }]
        }

    Translation and rotation are relative offsets from the authored pose;
    scale is a component-wise multiplier.  The panel does not mutate the clip
    supplied to :meth:`set_clip`.
    """

    createRequested = Signal()
    deleteRequested = Signal()
    clipSelected = Signal(str)
    newClipRequested = Signal()
    duplicateClipRequested = Signal()
    renameClipRequested = Signal()
    deleteClipRequested = Signal()
    autoplayEdited = Signal(object)
    durationEdited = Signal(float)
    loopModeEdited = Signal(str)
    playRequested = Signal()
    stopRequested = Signal()
    playheadEdited = Signal(float)
    posePreviewed = Signal(object)
    poseKeyRequested = Signal(object)
    keySelected = Signal(object)
    keyEasingEdited = Signal(object)
    removeKeyRequested = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("AnimationTimelinePanel")
        self.setAccessibleName("Animation timeline")
        self._updating = False
        self._clip: dict[str, Any] | None = None
        self._keys: tuple[dict[str, Any], ...] = ()
        self._playing = False
        self._clip_id: str | None = None
        self._library_clips: tuple[dict[str, Any], ...] = ()
        self._playheads: dict[tuple[str, str], float] = {}
        self._autoplay_clip_id: str | None = None
        self._owner_key = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(7)

        heading = QHBoxLayout()
        self.title = QLabel("Animation")
        self.title.setObjectName("PanelTitle")
        self.owner_label = QLabel("No object selected")
        self.owner_label.setObjectName("MutedLabel")
        self.owner_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.owner_label.setAccessibleName("Animated object")
        heading.addWidget(self.title)
        heading.addWidget(self.owner_label, 1)
        outer.addLayout(heading)

        self.pages = QStackedWidget()
        outer.addWidget(self.pages, 1)
        self._create_guidance_page()
        self._create_editor_page()
        self.pages.addWidget(self.guidance_page)
        self.pages.addWidget(self.editor_page)

        self._connect_signals()
        self.set_guidance("Choose a static 3D object to animate.")

    def _create_guidance_page(self) -> None:
        self.guidance_page = QFrame()
        layout = QVBoxLayout(self.guidance_page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        self.guidance_label = QLabel()
        self.guidance_label.setObjectName("MutedLabel")
        self.guidance_label.setWordWrap(True)
        self.guidance_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.guidance_label.setAccessibleName("Animation guidance")
        self.create_button = QPushButton("Create Animation")
        self.create_button.setObjectName("CreateAnimationButton")
        self.create_button.setAccessibleName("Create animation for the selected object")
        self.create_button.setToolTip(
            "Start a two-second animation from this object's current pose"
        )
        layout.addStretch(1)
        layout.addWidget(self.guidance_label)
        layout.addWidget(self.create_button, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)

    def _create_editor_page(self) -> None:
        self.editor_page = QWidget()
        root = QVBoxLayout(self.editor_page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(7)

        clips = QHBoxLayout()
        clips.setSpacing(6)
        clips.addWidget(QLabel("Clip"))
        self.clip_selector = QComboBox()
        self.clip_selector.setObjectName("AnimationClipChooser")
        self.clip_selector.setAccessibleName("Animation clip")
        self.clip_selector.setToolTip("Choose which animation clip to work on")
        self.new_clip_button = QPushButton("New")
        self.new_clip_button.setAccessibleName("Create a new animation clip")
        self.duplicate_clip_button = QPushButton("Duplicate")
        self.duplicate_clip_button.setAccessibleName("Duplicate this animation clip")
        self.rename_clip_button = QPushButton("Rename")
        self.rename_clip_button.setAccessibleName("Rename this animation clip")
        self.delete_clip_button = QPushButton("Delete Clip")
        self.delete_clip_button.setAccessibleName("Delete this animation clip")
        clips.addWidget(self.clip_selector, 1)
        clips.addWidget(self.new_clip_button)
        clips.addWidget(self.duplicate_clip_button)
        clips.addWidget(self.rename_clip_button)
        clips.addWidget(self.delete_clip_button)
        root.addLayout(clips)

        self.autoplay_checkbox = QCheckBox("Play this clip when the game starts")
        self.autoplay_checkbox.setObjectName("AnimationAutoplayCheckBox")
        self.autoplay_checkbox.setAccessibleName(
            "Play this animation clip when the game starts"
        )
        self.autoplay_checkbox.setToolTip(
            "Only one clip on this object can start automatically"
        )
        root.addWidget(self.autoplay_checkbox)

        settings = QHBoxLayout()
        settings.setSpacing(6)
        duration_label = QLabel("Length")
        self.duration = _spin(
            minimum=0.1,
            maximum=120.0,
            step=0.1,
            decimals=2,
            value=2.0,
            accessible_name="Animation length in seconds",
        )
        self.duration.setSuffix(" s")
        self.duration.setToolTip("How long the animation lasts")
        repeat_label = QLabel("Repeat")
        self.loop_mode = QComboBox()
        self.loop_mode.setAccessibleName("Animation repeat mode")
        self.loop_mode.setToolTip("Choose what happens when the animation reaches the end")
        for label, value in _LOOP_CHOICES:
            self.loop_mode.addItem(label, value)
        self.delete_button = QPushButton("Delete Animation")
        self.delete_button.setAccessibleName("Delete this animation")
        self.delete_button.setToolTip("Remove this animation; Undo can bring it back")
        settings.addWidget(duration_label)
        settings.addWidget(self.duration)
        settings.addWidget(repeat_label)
        settings.addWidget(self.loop_mode)
        settings.addStretch(1)
        settings.addWidget(self.delete_button)
        root.addLayout(settings)

        playback = QHBoxLayout()
        playback.setSpacing(6)
        self.play_button = QPushButton("Play Animation")
        self.play_button.setObjectName("PlayButton")
        self.play_button.setAccessibleName("Play animation preview")
        self.play_button.setToolTip("Preview only this object's animation")
        self.stop_button = QPushButton("Stop")
        self.stop_button.setObjectName("StopButton")
        self.stop_button.setAccessibleName("Stop animation preview")
        self.stop_button.setToolTip("Stop the preview and return to the starting pose")
        self.time = _spin(
            minimum=0.0,
            maximum=2.0,
            step=0.05,
            decimals=3,
            value=0.0,
            accessible_name="Animation playhead time",
        )
        self.time.setSuffix(" s")
        self.time.setToolTip("The exact time shown in the scene")
        self.playhead = QSlider(Qt.Orientation.Horizontal)
        self.playhead.setRange(0, _SLIDER_STEPS)
        self.playhead.setAccessibleName("Animation playhead")
        self.playhead.setToolTip("Drag to see the animation at another time")
        playback.addWidget(self.play_button)
        playback.addWidget(self.stop_button)
        playback.addWidget(QLabel("Time"))
        playback.addWidget(self.time)
        playback.addWidget(self.playhead, 1)
        root.addLayout(playback)

        self.pose_box = QGroupBox("Pose at this time")
        self.pose_box.setToolTip(
            "Position and Turn are changes from the starting pose; Size is a multiplier"
        )
        pose_grid = QGridLayout(self.pose_box)
        pose_grid.setContentsMargins(8, 12, 8, 8)
        pose_grid.setHorizontalSpacing(6)
        pose_grid.setVerticalSpacing(5)
        for column, axis in enumerate(("X", "Y", "Z"), 1):
            axis_label = QLabel(axis)
            axis_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            axis_label.setObjectName("MutedLabel")
            pose_grid.addWidget(axis_label, 0, column)

        self.translation_spins = tuple(
            _spin(
                minimum=-4096.0,
                maximum=4096.0,
                step=0.1,
                decimals=3,
                value=0.0,
                accessible_name=f"Relative position {axis}",
            )
            for axis in ("X", "Y", "Z")
        )
        self.rotation_spins = tuple(
            _spin(
                minimum=-36_000.0,
                maximum=36_000.0,
                step=1.0,
                decimals=2,
                value=0.0,
                accessible_name=f"Relative turn {axis} in degrees",
            )
            for axis in ("X", "Y", "Z")
        )
        self.scale_spins = tuple(
            _spin(
                minimum=0.001,
                maximum=64.0,
                step=0.05,
                decimals=3,
                value=1.0,
                accessible_name=f"Size multiplier {axis}",
            )
            for axis in ("X", "Y", "Z")
        )
        for row, (label, widgets, tooltip) in enumerate(
            (
                ("Position offset", self.translation_spins, "Distance from the starting position"),
                ("Turn (degrees)", self.rotation_spins, "Turn from the starting rotation"),
                ("Size multiplier", self.scale_spins, "1 keeps the starting size; 2 is twice as large"),
            ),
            1,
        ):
            row_label = QLabel(label)
            row_label.setToolTip(tooltip)
            pose_grid.addWidget(row_label, row, 0)
            for column, widget in enumerate(widgets, 1):
                widget.setToolTip(tooltip)
                pose_grid.addWidget(widget, row, column)
        root.addWidget(self.pose_box)

        key_row = QHBoxLayout()
        key_row.setSpacing(6)
        self.key_selector = QComboBox()
        self.key_selector.setAccessibleName("Selected animation key")
        self.key_selector.setToolTip("Choose a saved pose key")
        self.easing = QComboBox()
        self.easing.setAccessibleName("How the selected key arrives")
        self.easing.setToolTip(
            "Choose how the object approaches this key; Smooth is a friendly default"
        )
        for label, value in _EASING_CHOICES:
            self.easing.addItem(label, value)
        self.easing.setCurrentIndex(self.easing.findData("smoothstep"))
        self.key_button = QPushButton("Add whole-pose key")
        self.key_button.setObjectName("AddPoseKeyButton")
        self.key_button.setAccessibleName("Add or update whole-pose key")
        self.key_button.setToolTip(
            "Keep Position, Turn and Size together at the current time"
        )
        self.remove_key_button = QPushButton("Remove key")
        self.remove_key_button.setAccessibleName("Remove selected animation key")
        self.remove_key_button.setToolTip("Remove this saved pose; Undo can bring it back")
        key_row.addWidget(QLabel("Saved key"))
        key_row.addWidget(self.key_selector, 1)
        key_row.addWidget(QLabel("Arrival"))
        key_row.addWidget(self.easing)
        key_row.addWidget(self.key_button)
        key_row.addWidget(self.remove_key_button)
        root.addLayout(key_row)

        self.relative_hint = QLabel(
            "Position and Turn are relative to the object's starting pose. "
            "Size 1 × keeps its starting size."
        )
        self.relative_hint.setObjectName("MutedLabel")
        self.relative_hint.setWordWrap(True)
        self.relative_hint.setAccessibleName("Relative animation help")
        root.addWidget(self.relative_hint)

    def _connect_signals(self) -> None:
        self.create_button.clicked.connect(self.createRequested)
        self.delete_button.clicked.connect(self.deleteRequested)
        self.clip_selector.currentIndexChanged.connect(self._clip_selection_changed)
        self.new_clip_button.clicked.connect(self.newClipRequested)
        self.duplicate_clip_button.clicked.connect(self.duplicateClipRequested)
        self.rename_clip_button.clicked.connect(self.renameClipRequested)
        self.delete_clip_button.clicked.connect(self.deleteClipRequested)
        self.autoplay_checkbox.toggled.connect(self._autoplay_toggled)
        self.duration.valueChanged.connect(self._duration_edited)
        self.loop_mode.currentIndexChanged.connect(self._loop_mode_edited)
        self.play_button.clicked.connect(self.playRequested)
        self.stop_button.clicked.connect(self.stopRequested)
        self.time.valueChanged.connect(self._time_edited)
        self.playhead.valueChanged.connect(self._slider_edited)
        self.key_selector.currentIndexChanged.connect(self._key_selection_changed)
        self.easing.currentIndexChanged.connect(self._easing_edited)
        self.key_button.clicked.connect(self._request_pose_key)
        self.remove_key_button.clicked.connect(self._request_remove_key)
        for widget in (*self.translation_spins, *self.rotation_spins, *self.scale_spins):
            widget.valueChanged.connect(self._pose_edited)

    @staticmethod
    def _normalize_key(raw: Mapping[str, Any], duration: float) -> dict[str, Any]:
        try:
            time = float(raw["time"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("every animation key needs a numeric time") from exc
        if not math.isfinite(time) or time < 0.0 or time > duration + _TIME_EPSILON:
            raise ValueError("animation key time must be inside the clip")
        translation = _finite_triplet(raw.get("translation", (0.0, 0.0, 0.0)), "translation")
        rotation = _finite_triplet(raw.get("rotation", (0.0, 0.0, 0.0)), "rotation")
        scale = _finite_triplet(raw.get("scale", (1.0, 1.0, 1.0)), "scale")
        if any(value <= 0.0 for value in scale):
            raise ValueError("size multipliers must be greater than zero")
        easing = str(raw.get("easing", "smoothstep"))
        if easing not in {value for _, value in _EASING_CHOICES}:
            raise ValueError(f"unsupported animation easing: {easing}")
        return {
            "time": min(duration, time),
            "translation": list(translation),
            "rotation": list(rotation),
            "scale": list(scale),
            "easing": easing,
        }

    @classmethod
    def _normalize_clip(cls, raw: Mapping[str, Any]) -> dict[str, Any]:
        try:
            duration = float(raw.get("duration", 2.0))
        except (TypeError, ValueError) as exc:
            raise ValueError("animation length must be a number") from exc
        if not math.isfinite(duration) or duration <= 0.0 or duration > 120.0:
            raise ValueError("animation length must be between 0 and 120 seconds")
        loop_mode = str(raw.get("loop_mode", "once"))
        if loop_mode not in {value for _, value in _LOOP_CHOICES}:
            raise ValueError(f"unsupported animation repeat mode: {loop_mode}")
        raw_keys = raw.get("keys", ())
        if not isinstance(raw_keys, Sequence) or isinstance(raw_keys, (str, bytes)):
            raise ValueError("animation keys must be a list")
        keys: list[dict[str, Any]] = []
        for raw_key in raw_keys:
            if not isinstance(raw_key, Mapping):
                raise ValueError("every animation key must be an object")
            keys.append(cls._normalize_key(raw_key, duration))
        keys.sort(key=lambda item: float(item["time"]))
        for left, right in zip(keys, keys[1:]):
            if math.isclose(
                float(left["time"]), float(right["time"]), rel_tol=0.0, abs_tol=_TIME_EPSILON
            ):
                raise ValueError("animation key times must be unique")
        return {
            "schema": str(raw.get("schema", TRANSFORM_ANIMATION_SCHEMA)),
            "duration": duration,
            "loop_mode": loop_mode,
            "keys": keys,
        }

    def clip_dict(self) -> dict[str, Any] | None:
        """Return a detached copy of the currently displayed clip."""

        return None if self._clip is None else copy.deepcopy(self._clip)

    def selected_clip_id(self) -> str | None:
        """Return the stable ID of the clip currently shown in the panel."""

        return self._clip_id

    def library_clips(self) -> tuple[dict[str, Any], ...]:
        """Return detached timeline-view entries for all displayed clips."""

        return copy.deepcopy(self._library_clips)

    def clear(self, message: str = "Choose a static 3D object to animate.") -> None:
        """Clear the clip and show non-actionable guidance."""

        self.set_guidance(message, can_create=False)

    def set_guidance(
        self,
        message: str,
        *,
        can_create: bool = False,
        object_name: str | None = None,
    ) -> None:
        """Show a selection hint or a friendly disabled reason."""

        self._updating = True
        try:
            self._clip = None
            self._keys = ()
            self._playing = False
            self._clip_id = None
            self._library_clips = ()
            self._autoplay_clip_id = None
            self.guidance_label.setText(str(message))
            self.create_button.setVisible(bool(can_create))
            self.create_button.setEnabled(bool(can_create))
            self.owner_label.setText(str(object_name) if object_name else "No animation")
            self.pages.setCurrentWidget(self.guidance_page)
        finally:
            self._updating = False

    def set_disabled_reason(self, reason: str, *, object_name: str | None = None) -> None:
        """Convenience wrapper for an object that cannot safely be animated."""

        self.set_guidance(reason, can_create=False, object_name=object_name)

    def set_clip(self, clip: Mapping[str, Any], *, object_name: str | None = None) -> None:
        """Display one detached legacy clip without emitting edit signals."""

        self.set_library(
            ({"id": "main", "label": "Main", "clip": clip},),
            selected_clip_id="main",
            autoplay_clip_id="main",
            object_name=object_name,
            owner_key=object_name,
        )

    def set_library(
        self,
        clips: Sequence[Mapping[str, Any]],
        *,
        selected_clip_id: str | None = None,
        autoplay_clip_id: str | None = None,
        object_name: str | None = None,
        owner_key: str | None = None,
    ) -> None:
        """Display a transform clip library without emitting authoring signals.

        Each entry contains ``id``, ``label`` and a timeline ``clip`` mapping.
        The stable ID is deliberately separate from the child-facing label.
        """

        normalized_entries: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in clips:
            clip_id = str(raw.get("id", "")).strip()
            if not clip_id or clip_id in seen:
                raise ValueError("every animation clip needs a unique ID")
            seen.add(clip_id)
            label = str(raw.get("label", clip_id)).strip() or clip_id
            raw_clip = raw.get("clip")
            if not isinstance(raw_clip, Mapping):
                raise ValueError(f"animation clip {label!r} has no timeline data")
            normalized_entries.append(
                {
                    "id": clip_id,
                    "label": label,
                    "clip": self._normalize_clip(raw_clip),
                }
            )
        if not normalized_entries:
            raise ValueError("an animation library needs at least one clip")
        if len(normalized_entries) > 16:
            raise ValueError("an object can have at most 16 animation clips")
        ids = {str(entry["id"]) for entry in normalized_entries}
        chosen = str(selected_clip_id or "")
        if chosen not in ids:
            chosen = str(normalized_entries[0]["id"])
        if self._clip_id is not None and self._clip is not None:
            self._playheads[(self._owner_key, self._clip_id)] = float(
                self.time.value()
            )

        self._updating = True
        try:
            self._owner_key = str(owner_key if owner_key is not None else object_name or "")
            self._library_clips = tuple(copy.deepcopy(normalized_entries))
            self._clip_id = chosen
            self._autoplay_clip_id = autoplay_clip_id
            self._playing = False
            self.owner_label.setText(str(object_name) if object_name else "Selected object")
            with QSignalBlocker(self.clip_selector):
                self.clip_selector.clear()
                for entry in normalized_entries:
                    self.clip_selector.addItem(str(entry["label"]), str(entry["id"]))
                self.clip_selector.setCurrentIndex(self.clip_selector.findData(chosen))
            self._display_clip(chosen)
        finally:
            self._updating = False

    def _display_clip(self, clip_id: str) -> None:
        entry = next(
            (item for item in self._library_clips if item["id"] == clip_id), None
        )
        if entry is None:
            return
        normalized = copy.deepcopy(entry["clip"])
        self._clip_id = clip_id
        self._clip = normalized
        self._keys = tuple(copy.deepcopy(normalized["keys"]))
        with QSignalBlocker(self.autoplay_checkbox):
            self.autoplay_checkbox.setChecked(clip_id == self._autoplay_clip_id)
        blockers = (
            QSignalBlocker(self.duration),
            QSignalBlocker(self.loop_mode),
            QSignalBlocker(self.time),
            QSignalBlocker(self.playhead),
            QSignalBlocker(self.key_selector),
            QSignalBlocker(self.easing),
        )
        _ = blockers
        last_key_time = max((float(key["time"]) for key in self._keys), default=0.0)
        self.duration.setMinimum(max(0.1, last_key_time))
        self.duration.setValue(float(normalized["duration"]))
        self.time.setMaximum(float(normalized["duration"]))
        self.loop_mode.setCurrentIndex(self.loop_mode.findData(normalized["loop_mode"]))
        self._populate_key_selector()
        self.pages.setCurrentWidget(self.editor_page)
        playhead = self._playheads.get((self._owner_key, clip_id), 0.0)
        self._set_playhead_internal(min(playhead, float(normalized["duration"])))
        self._set_playing_controls(self._playing)

    def set_playhead(
        self, seconds: float, pose: Mapping[str, Any] | None = None
    ) -> None:
        """Move the visible playhead without emitting authoring signals."""

        if self._clip is None:
            return
        self._updating = True
        try:
            self._set_playhead_internal(seconds, pose)
        finally:
            self._updating = False

    def set_pose(self, pose: Mapping[str, Any]) -> None:
        """Replace the visible relative pose without emitting preview signals."""

        normalized = self._normalize_pose(pose)
        self._updating = True
        try:
            self._set_pose_fields(normalized)
        finally:
            self._updating = False

    def pose_at(self, seconds: float) -> dict[str, Any]:
        """Return a detached sampled relative pose for viewport preview."""

        if self._clip is None:
            return {
                "translation": [0.0, 0.0, 0.0],
                "rotation": [0.0, 0.0, 0.0],
                "scale": [1.0, 1.0, 1.0],
            }
        duration = float(self._clip["duration"])
        seconds = max(0.0, min(duration, float(seconds)))
        return copy.deepcopy(self._sample_pose(seconds))

    def set_playing(self, playing: bool) -> None:
        """Update preview controls without recursively requesting play or stop."""

        self._updating = True
        try:
            self._playing = bool(playing)
            self._set_playing_controls(self._playing)
        finally:
            self._updating = False

    def _normalize_pose(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        translation = _finite_triplet(raw.get("translation", (0.0, 0.0, 0.0)), "translation")
        rotation = _finite_triplet(raw.get("rotation", (0.0, 0.0, 0.0)), "rotation")
        scale = _finite_triplet(raw.get("scale", (1.0, 1.0, 1.0)), "scale")
        if any(value <= 0.0 for value in scale):
            raise ValueError("size multipliers must be greater than zero")
        return {
            "translation": list(translation),
            "rotation": list(rotation),
            "scale": list(scale),
        }

    def _populate_key_selector(self) -> None:
        with QSignalBlocker(self.key_selector):
            self.key_selector.clear()
            self.key_selector.addItem("Between saved keys", None)
            for key in self._keys:
                time = float(key["time"])
                self.key_selector.addItem(f"Key at {time:.3f} s", time)

    def _set_playing_controls(self, playing: bool) -> None:
        has_clip = self._clip is not None
        self.play_button.setEnabled(has_clip and not playing)
        self.stop_button.setEnabled(has_clip and playing)
        for widget in (
            self.clip_selector,
            self.new_clip_button,
            self.duplicate_clip_button,
            self.rename_clip_button,
            self.delete_clip_button,
            self.autoplay_checkbox,
            self.duration,
            self.loop_mode,
            self.delete_button,
            self.pose_box,
            self.key_selector,
            self.easing,
            self.key_button,
            self.remove_key_button,
        ):
            widget.setEnabled(has_clip and not playing)
        self.new_clip_button.setEnabled(has_clip and not playing and len(self._library_clips) < 16)
        self.delete_clip_button.setEnabled(
            has_clip and not playing and len(self._library_clips) > 1
        )
        self.time.setEnabled(has_clip and not playing)
        self.playhead.setEnabled(has_clip and not playing)
        if not playing:
            self._sync_key_controls(self.time.value())

    def _duration_value(self) -> float:
        if self._clip is not None:
            return float(self._clip["duration"])
        return max(0.1, float(self.duration.value()))

    def _slider_from_time(self, seconds: float) -> int:
        duration = self._duration_value()
        return round(max(0.0, min(duration, seconds)) / duration * _SLIDER_STEPS)

    def _time_from_slider(self, value: int) -> float:
        return self._duration_value() * max(0, min(_SLIDER_STEPS, int(value))) / _SLIDER_STEPS

    def _key_at(self, seconds: float) -> dict[str, Any] | None:
        for key in self._keys:
            if math.isclose(float(key["time"]), seconds, rel_tol=0.0, abs_tol=_TIME_EPSILON):
                return key
        return None

    @staticmethod
    def _ease(name: str, value: float) -> float:
        value = max(0.0, min(1.0, float(value)))
        if name == "linear":
            return value
        if name == "step":
            return 0.0
        if name == "ease_in":
            return value * value
        if name == "ease_out":
            return 1.0 - (1.0 - value) * (1.0 - value)
        if name == "ease_in_out":
            return (
                2.0 * value * value
                if value < 0.5
                else 1.0 - ((-2.0 * value + 2.0) ** 2) / 2.0
            )
        if name == "smoothstep":
            return value * value * (3.0 - 2.0 * value)
        if name == "smootherstep":
            return value * value * value * (
                value * (value * 6.0 - 15.0) + 10.0
            )
        if name == "back_out":
            c1 = 1.70158
            shifted = value - 1.0
            return 1.0 + (c1 + 1.0) * shifted**3 + c1 * shifted**2
        if name == "elastic_out":
            if value in {0.0, 1.0}:
                return value
            c4 = (2.0 * math.pi) / 3.0
            return (
                2.0 ** (-10.0 * value)
                * math.sin((value * 10.0 - 0.75) * c4)
                + 1.0
            )
        raise ValueError(f"unsupported animation easing: {name}")

    def _sample_pose(self, seconds: float) -> dict[str, Any]:
        if not self._keys:
            return {
                "translation": [0.0, 0.0, 0.0],
                "rotation": [0.0, 0.0, 0.0],
                "scale": [1.0, 1.0, 1.0],
            }
        if seconds <= float(self._keys[0]["time"]) + _TIME_EPSILON:
            return self._normalize_pose(self._keys[0])
        if seconds >= float(self._keys[-1]["time"]) - _TIME_EPSILON:
            return self._normalize_pose(self._keys[-1])
        for left, right in zip(self._keys, self._keys[1:]):
            right_time = float(right["time"])
            if math.isclose(seconds, right_time, rel_tol=0.0, abs_tol=_TIME_EPSILON):
                return self._normalize_pose(right)
            if seconds < right_time:
                left_time = float(left["time"])
                amount = self._ease(
                    str(right["easing"]), (seconds - left_time) / (right_time - left_time)
                )
                result = {
                    name: [
                        float(a) + (float(b) - float(a)) * amount
                        for a, b in zip(left[name], right[name])
                    ]
                    for name in ("translation", "scale")
                }
                result["rotation"] = list(
                    _rotation_nlerp(left["rotation"], right["rotation"], amount)
                )
                return result
        return self._normalize_pose(self._keys[-1])

    def _set_pose_fields(self, pose: Mapping[str, Any]) -> None:
        blockers = tuple(
            QSignalBlocker(widget)
            for widget in (*self.translation_spins, *self.rotation_spins, *self.scale_spins)
        )
        _ = blockers
        for widgets, name in (
            (self.translation_spins, "translation"),
            (self.rotation_spins, "rotation"),
            (self.scale_spins, "scale"),
        ):
            for widget, value in zip(widgets, pose[name]):
                widget.setValue(float(value))

    def _set_playhead_internal(
        self, seconds: float, pose: Mapping[str, Any] | None = None
    ) -> None:
        duration = self._duration_value()
        seconds = max(0.0, min(duration, float(seconds)))
        if not math.isfinite(seconds):
            seconds = 0.0
        with QSignalBlocker(self.time):
            self.time.setValue(seconds)
        with QSignalBlocker(self.playhead):
            self.playhead.setValue(self._slider_from_time(seconds))
        self._set_pose_fields(
            self._sample_pose(seconds) if pose is None else self._normalize_pose(pose)
        )
        self._sync_key_controls(seconds)

    def _sync_key_controls(self, seconds: float) -> None:
        key = self._key_at(seconds)
        with QSignalBlocker(self.key_selector):
            index = 0 if key is None else self.key_selector.findData(float(key["time"]))
            self.key_selector.setCurrentIndex(max(0, index))
        if key is not None:
            with QSignalBlocker(self.easing):
                self.easing.setCurrentIndex(self.easing.findData(str(key["easing"])))
        self.key_button.setText(
            "Update whole-pose key" if key is not None else "Add whole-pose key"
        )
        selected_key = self._selected_key()
        removable = (
            selected_key is not None
            and float(selected_key["time"]) > _TIME_EPSILON
            and len(self._keys) > 1
            and not self._playing
        )
        self.remove_key_button.setEnabled(removable)
        if selected_key is not None and float(selected_key["time"]) <= _TIME_EPSILON:
            self.remove_key_button.setToolTip(
                "The starting key keeps the object's starting pose and cannot be removed."
            )
        else:
            self.remove_key_button.setToolTip("Remove this saved pose; Undo can bring it back")

    def _selected_key(self) -> dict[str, Any] | None:
        value = self.key_selector.currentData()
        if value is None:
            return None
        return self._key_at(float(value))

    def _pose_payload(self) -> dict[str, Any]:
        return {
            "time": float(self.time.value()),
            "translation": [widget.value() for widget in self.translation_spins],
            "rotation": [widget.value() for widget in self.rotation_spins],
            "scale": [widget.value() for widget in self.scale_spins],
            "easing": str(self.easing.currentData() or "smoothstep"),
        }

    def _duration_edited(self, value: float) -> None:
        if self._updating or self._clip is None:
            return
        self._clip["duration"] = float(value)
        self.time.setMaximum(float(value))
        self._set_playhead_internal(min(self.time.value(), float(value)))
        self.durationEdited.emit(float(value))

    def _clip_selection_changed(self, _index: int) -> None:
        if self._updating or self._playing:
            return
        clip_id = self.clip_selector.currentData()
        if clip_id is None or str(clip_id) == self._clip_id:
            return
        if self._clip_id is not None and self._clip is not None:
            self._playheads[(self._owner_key, self._clip_id)] = float(
                self.time.value()
            )
        self._updating = True
        try:
            self._display_clip(str(clip_id))
        finally:
            self._updating = False
        self.clipSelected.emit(str(clip_id))

    def _autoplay_toggled(self, checked: bool) -> None:
        if self._updating or self._clip_id is None:
            return
        self._autoplay_clip_id = self._clip_id if checked else None
        self.autoplayEdited.emit(self._clip_id if checked else None)

    def _loop_mode_edited(self, _index: int) -> None:
        if self._updating or self._clip is None:
            return
        value = str(self.loop_mode.currentData() or "once")
        self._clip["loop_mode"] = value
        self.loopModeEdited.emit(value)

    def _time_edited(self, value: float) -> None:
        if self._updating or self._clip is None:
            return
        self._updating = True
        try:
            self._set_playhead_internal(float(value))
        finally:
            self._updating = False
        self.playheadEdited.emit(float(self.time.value()))
        self.posePreviewed.emit(self._pose_payload())

    def _slider_edited(self, value: int) -> None:
        if self._updating or self._clip is None:
            return
        seconds = self._time_from_slider(value)
        self._updating = True
        try:
            self._set_playhead_internal(seconds)
        finally:
            self._updating = False
        self.playheadEdited.emit(float(self.time.value()))
        self.posePreviewed.emit(self._pose_payload())

    def _pose_edited(self, _value: float) -> None:
        if self._updating or self._clip is None or self._playing:
            return
        self.posePreviewed.emit(self._pose_payload())

    def _key_selection_changed(self, _index: int) -> None:
        if self._updating or self._clip is None:
            return
        key = self._selected_key()
        if key is None:
            self.keySelected.emit(None)
            self._sync_key_controls(self.time.value())
            return
        self._updating = True
        try:
            self._set_playhead_internal(float(key["time"]), key)
        finally:
            self._updating = False
        payload = copy.deepcopy(key)
        self.keySelected.emit(payload)
        self.playheadEdited.emit(float(key["time"]))
        self.posePreviewed.emit(self._pose_payload())

    def _easing_edited(self, _index: int) -> None:
        if self._updating or self._clip is None or self._playing:
            return
        key = self._selected_key()
        if key is None:
            return
        self.keyEasingEdited.emit(
            {
                "time": float(key["time"]),
                "easing": str(self.easing.currentData() or "smoothstep"),
            }
        )

    def _request_pose_key(self) -> None:
        if self._clip is None or self._playing:
            return
        self.poseKeyRequested.emit(self._pose_payload())

    def _request_remove_key(self) -> None:
        if self._clip is None or self._playing:
            return
        key = self._selected_key()
        if (
            key is not None
            and float(key["time"]) > _TIME_EPSILON
            and len(self._keys) > 1
        ):
            self.removeKeyRequested.emit(float(key["time"]))


__all__ = ["AnimationTimelinePanel", "TRANSFORM_ANIMATION_SCHEMA"]
