"""Pinned rules profiles used by proof searches."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Rules:
    """Fully serialized rule choices.

    The canonical 19x19 proof target is area scoring, 7.5 komi,
    positional superko, illegal suicide, and termination after two passes.
    Komi is stored in half-point units to avoid floating-point ambiguity.
    """

    size: int = 19
    komi2: int = 15
    superko: str = "positional_superko"
    allow_suicide: bool = False
    scoring: str = "area"
    passes_to_end: int = 2
    profile_id: str = "UGTS-GO19-AREA-PSK-K7.5-v1"

    def __post_init__(self) -> None:
        if not 1 <= self.size <= 19:
            raise ValueError("reference engine supports board sizes 1..19")
        if self.superko not in {
            "none",
            "simple_ko",
            "positional_superko",
            "situational_superko",
        }:
            raise ValueError(f"unsupported repetition rule: {self.superko}")
        if self.scoring != "area":
            raise ValueError("version 4.3 proof core supports deterministic area scoring")
        if self.passes_to_end < 1:
            raise ValueError("passes_to_end must be positive")

    @classmethod
    def canonical_19x19(cls) -> "Rules":
        return cls()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Rules":
        return cls(**data)
