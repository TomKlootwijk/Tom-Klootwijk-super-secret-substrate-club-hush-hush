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
        if type(self.size) is not int:
            raise TypeError("size must be an integer")
        if type(self.komi2) is not int:
            raise TypeError("komi2 must be an integer")
        if type(self.superko) is not str:
            raise TypeError("superko must be a string")
        if type(self.allow_suicide) is not bool:
            raise TypeError("allow_suicide must be boolean")
        if type(self.scoring) is not str:
            raise TypeError("scoring must be a string")
        if type(self.passes_to_end) is not int:
            raise TypeError("passes_to_end must be an integer")
        if type(self.profile_id) is not str or not self.profile_id:
            raise TypeError("profile_id must be a nonempty string")
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
        if self.profile_id == "UGTS-GO19-AREA-PSK-K7.5-v1":
            canonical = (
                self.size == 19
                and self.komi2 == 15
                and self.superko == "positional_superko"
                and self.allow_suicide is False
                and self.scoring == "area"
                and self.passes_to_end == 2
            )
            if not canonical:
                raise ValueError("canonical profile_id requires its pinned rule tuple")

    @classmethod
    def canonical_19x19(cls) -> "Rules":
        return cls()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Rules":
        expected = {
            "size",
            "komi2",
            "superko",
            "allow_suicide",
            "scoring",
            "passes_to_end",
            "profile_id",
        }
        if not isinstance(data, dict) or set(data) != expected:
            raise ValueError("rules object has a noncanonical shape")
        return cls(**data)
