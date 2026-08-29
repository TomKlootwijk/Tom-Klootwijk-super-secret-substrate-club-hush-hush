"""Procedural audio cue contracts for browser export and deterministic tooling."""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
from typing import Any, Iterable, Mapping

_NOTE_RE = re.compile(r"^([A-Ga-g])([#b]?)(-?\d+)$")
_NOTE_INDEX = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def note_frequency(note: str, a4: float = 440.0) -> float:
    match = _NOTE_RE.match(note.strip())
    if not match:
        raise ValueError(f"invalid note name: {note}")
    name, accidental, octave_text = match.groups()
    semitone = _NOTE_INDEX[name.upper()] + (1 if accidental == "#" else -1 if accidental == "b" else 0)
    octave = int(octave_text)
    midi = (octave + 1) * 12 + semitone
    return float(a4) * (2.0 ** ((midi - 69) / 12.0))


@dataclass(frozen=True)
class Envelope:
    attack: float = 0.005
    decay: float = 0.04
    sustain: float = 0.55
    release: float = 0.08

    def validate(self) -> None:
        if any(not math.isfinite(value) or value < 0 for value in (self.attack, self.decay, self.release)):
            raise ValueError("envelope times must be finite and non-negative")
        if not 0.0 <= self.sustain <= 1.0:
            raise ValueError("envelope sustain must be in [0, 1]")

    def to_dict(self) -> dict[str, float]:
        return {"attack": self.attack, "decay": self.decay, "sustain": self.sustain, "release": self.release}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Envelope":
        envelope = cls(
            float(data.get("attack", 0.005)),
            float(data.get("decay", 0.04)),
            float(data.get("sustain", 0.55)),
            float(data.get("release", 0.08)),
        )
        envelope.validate()
        return envelope


@dataclass(frozen=True)
class SoundCue:
    id: str
    waveform: str = "sine"
    frequency: float = 440.0
    duration: float = 0.15
    volume: float = 0.2
    detune: float = 0.0
    sweep_to: float | None = None
    envelope: Envelope = field(default_factory=Envelope)
    noise: float = 0.0

    def validate(self) -> None:
        if not self.id:
            raise ValueError("sound cue id is required")
        if self.waveform not in {"sine", "square", "sawtooth", "triangle"}:
            raise ValueError("unsupported oscillator waveform")
        if not math.isfinite(self.frequency) or self.frequency <= 0:
            raise ValueError("sound frequency must be positive and finite")
        if self.sweep_to is not None and (not math.isfinite(self.sweep_to) or self.sweep_to <= 0):
            raise ValueError("sweep_to must be positive and finite")
        if not math.isfinite(self.duration) or self.duration <= 0:
            raise ValueError("sound duration must be positive and finite")
        if not 0 <= self.volume <= 1:
            raise ValueError("sound volume must be in [0, 1]")
        if not math.isfinite(self.detune):
            raise ValueError("detune must be finite")
        if not 0 <= self.noise <= 1:
            raise ValueError("noise must be in [0, 1]")
        self.envelope.validate()

    @classmethod
    def from_note(cls, cue_id: str, note: str, **kwargs: Any) -> "SoundCue":
        return cls(cue_id, frequency=note_frequency(note), **kwargs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "waveform": self.waveform,
            "frequency": self.frequency,
            "duration": self.duration,
            "volume": self.volume,
            "detune": self.detune,
            "sweep_to": self.sweep_to,
            "envelope": self.envelope.to_dict(),
            "noise": self.noise,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SoundCue":
        cue = cls(
            str(data["id"]),
            str(data.get("waveform", "sine")),
            float(data.get("frequency", 440.0)),
            float(data.get("duration", 0.15)),
            float(data.get("volume", 0.2)),
            float(data.get("detune", 0.0)),
            None if data.get("sweep_to") is None else float(data["sweep_to"]),
            Envelope.from_dict(data.get("envelope", {})),
            float(data.get("noise", 0.0)),
        )
        cue.validate()
        return cue


@dataclass(frozen=True)
class SequenceNote:
    beat: float
    cue_id: str
    pitch_ratio: float = 1.0
    gain: float = 1.0

    def validate(self) -> None:
        if not math.isfinite(self.beat) or self.beat < 0:
            raise ValueError("sequence beat must be non-negative and finite")
        if not self.cue_id:
            raise ValueError("sequence cue id is required")
        if not math.isfinite(self.pitch_ratio) or self.pitch_ratio <= 0:
            raise ValueError("pitch_ratio must be positive and finite")
        if not 0 <= self.gain <= 1:
            raise ValueError("sequence gain must be in [0, 1]")

    def to_dict(self) -> dict[str, Any]:
        return {"beat": self.beat, "cue_id": self.cue_id, "pitch_ratio": self.pitch_ratio, "gain": self.gain}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SequenceNote":
        note = cls(float(data["beat"]), str(data["cue_id"]), float(data.get("pitch_ratio", 1.0)), float(data.get("gain", 1.0)))
        note.validate()
        return note


@dataclass(frozen=True)
class MusicSequence:
    id: str
    bpm: float
    length_beats: float
    notes: tuple[SequenceNote, ...]
    loop: bool = True

    def validate(self) -> None:
        if not self.id:
            raise ValueError("music sequence id is required")
        if not math.isfinite(self.bpm) or self.bpm <= 0:
            raise ValueError("bpm must be positive and finite")
        if not math.isfinite(self.length_beats) or self.length_beats <= 0:
            raise ValueError("length_beats must be positive and finite")
        for note in self.notes:
            note.validate()
            if note.beat >= self.length_beats:
                raise ValueError("sequence note lies outside sequence length")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "bpm": self.bpm,
            "length_beats": self.length_beats,
            "notes": [note.to_dict() for note in sorted(self.notes, key=lambda n: (n.beat, n.cue_id))],
            "loop": self.loop,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MusicSequence":
        sequence = cls(
            str(data["id"]),
            float(data["bpm"]),
            float(data["length_beats"]),
            tuple(SequenceNote.from_dict(note) for note in data.get("notes", [])),
            bool(data.get("loop", True)),
        )
        sequence.validate()
        return sequence


class AudioBank:
    def __init__(self, cues: Iterable[SoundCue] = (), sequences: Iterable[MusicSequence] = ()):
        self.cues: dict[str, SoundCue] = {}
        self.sequences: dict[str, MusicSequence] = {}
        for cue in cues:
            self.add_cue(cue)
        for sequence in sequences:
            self.add_sequence(sequence)

    def add_cue(self, cue: SoundCue, replace_existing: bool = False) -> None:
        cue.validate()
        if cue.id in self.cues and not replace_existing:
            raise ValueError(f"sound cue already exists: {cue.id}")
        self.cues[cue.id] = cue

    def add_sequence(self, sequence: MusicSequence, replace_existing: bool = False) -> None:
        sequence.validate()
        missing = sorted({note.cue_id for note in sequence.notes if note.cue_id not in self.cues})
        if missing:
            raise KeyError(f"sequence references unknown cues: {', '.join(missing)}")
        if sequence.id in self.sequences and not replace_existing:
            raise ValueError(f"music sequence already exists: {sequence.id}")
        self.sequences[sequence.id] = sequence

    def validate(self) -> None:
        for cue in self.cues.values():
            cue.validate()
        for sequence in self.sequences.values():
            sequence.validate()
            for note in sequence.notes:
                if note.cue_id not in self.cues:
                    raise KeyError(note.cue_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cues": [self.cues[name].to_dict() for name in sorted(self.cues)],
            "sequences": [self.sequences[name].to_dict() for name in sorted(self.sequences)],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AudioBank":
        cues = [SoundCue.from_dict(item) for item in data.get("cues", [])]
        bank = cls(cues)
        for item in data.get("sequences", []):
            bank.add_sequence(MusicSequence.from_dict(item))
        return bank
