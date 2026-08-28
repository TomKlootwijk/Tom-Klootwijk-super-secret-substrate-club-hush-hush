"""Bounded Dutch number-word profile used by UGTS-KC 3.6.

This module is deliberately limited to integers 0..99.  The segmentation is a
versioned engineering profile for pronunciation-like pulses; it is not an IPA
transcription and is not claimed to settle every dialectal syllabification.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class NumberLexemeNL:
    value: int
    orthography: str
    pronunciation_segments: tuple[str, ...]
    morphemes: tuple[str, ...]
    syllable_count: int
    place_order: tuple[Any, ...]
    spoken_order: tuple[Any, ...]
    hinge_kind: str
    hinge_count: int
    binary: str
    popcount: int

    @property
    def pulse_match(self) -> bool:
        """Whether syllable-pulse count equals binary Hamming weight.

        This is a comparison of two feature counts.  It is never numeric
        equality between the number word and the active-bit string.
        """

        return self.syllable_count == self.popcount

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["pronunciation_segments"] = list(self.pronunciation_segments)
        out["morphemes"] = list(self.morphemes)
        out["place_order"] = list(self.place_order)
        out["spoken_order"] = list(self.spoken_order)
        out["pulse_match"] = self.pulse_match
        return out


_UNITS: dict[int, tuple[str, tuple[str, ...]]] = {
    0: ("nul", ("nul",)),
    1: ("een", ("een",)),
    2: ("twee", ("twee",)),
    3: ("drie", ("drie",)),
    4: ("vier", ("vier",)),
    5: ("vijf", ("vijf",)),
    6: ("zes", ("zes",)),
    7: ("zeven", ("ze", "ven")),
    8: ("acht", ("acht",)),
    9: ("negen", ("ne", "gen")),
}

_TEENS: dict[int, tuple[str, tuple[str, ...], tuple[str, ...], str]] = {
    10: ("tien", ("tien",), ("tien",), "none"),
    11: ("elf", ("elf",), ("elf",), "irregular"),
    12: ("twaalf", ("twaalf",), ("twaalf",), "irregular"),
    13: ("dertien", ("der", "tien"), ("drie", "tien"), "teen_suffix"),
    14: ("veertien", ("veer", "tien"), ("vier", "tien"), "teen_suffix"),
    15: ("vijftien", ("vijf", "tien"), ("vijf", "tien"), "teen_suffix"),
    16: ("zestien", ("zes", "tien"), ("zes", "tien"), "teen_suffix"),
    17: ("zeventien", ("ze", "ven", "tien"), ("zeven", "tien"), "teen_suffix"),
    18: ("achttien", ("acht", "tien"), ("acht", "tien"), "teen_suffix"),
    19: ("negentien", ("ne", "gen", "tien"), ("negen", "tien"), "teen_suffix"),
}

_TENS: dict[int, tuple[str, tuple[str, ...]]] = {
    20: ("twintig", ("twin", "tig")),
    30: ("dertig", ("der", "tig")),
    40: ("veertig", ("veer", "tig")),
    50: ("vijftig", ("vijf", "tig")),
    60: ("zestig", ("zes", "tig")),
    70: ("zeventig", ("ze", "ven", "tig")),
    80: ("tachtig", ("tach", "tig")),
    90: ("negentig", ("ne", "gen", "tig")),
}

# Orthographic prefixes before a tens word.  Diaeresis marks a new syllable.
_COMPOUND_PREFIX: dict[int, str] = {
    1: "eenen",
    2: "tweeën",
    3: "drieën",
    4: "vieren",
    5: "vijfen",
    6: "zesen",
    7: "zevenen",
    8: "achten",
    9: "negenen",
}


def _validate_value(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("Dutch number profile expects an integer")
    if not 0 <= value <= 99:
        raise ValueError("Dutch number profile is bounded to 0..99")


def lexeme(value: int) -> NumberLexemeNL:
    _validate_value(value)

    if value < 10:
        orth, seg = _UNITS[value]
        morphemes = (orth,)
        place = (value,)
        spoken = (value,)
        hinge_kind = "none"
        hinge_count = 0
    elif value < 20:
        orth, seg, morphemes, hinge_kind = _TEENS[value]
        if value in (10, 11, 12):
            place = (value,)
            spoken = (value,)
            hinge_count = 0
        else:
            unit = value - 10
            # Decimal place semantics are ten plus unit; Dutch morphology puts
            # the unit root before the teen suffix.
            place = (10, unit)
            spoken = (unit, "tien")
            hinge_count = 1
    elif value % 10 == 0:
        orth, seg = _TENS[value]
        morphemes = (orth,)
        place = (value,)
        spoken = (value,)
        hinge_kind = "none"
        hinge_count = 0
    else:
        ten_value = (value // 10) * 10
        unit = value % 10
        orth = _COMPOUND_PREFIX[unit] + _TENS[ten_value][0]
        seg = _UNITS[unit][1] + ("en",) + _TENS[ten_value][1]
        morphemes = (_UNITS[unit][0], "en", _TENS[ten_value][0])
        place = (ten_value, unit)
        spoken = (unit, "en", ten_value)
        hinge_kind = "en_connector"
        hinge_count = 1

    return NumberLexemeNL(
        value=value,
        orthography=orth,
        pronunciation_segments=seg,
        morphemes=morphemes,
        syllable_count=len(seg),
        place_order=place,
        spoken_order=spoken,
        hinge_kind=hinge_kind,
        hinge_count=hinge_count,
        binary=format(value, "b"),
        popcount=value.bit_count(),
    )


def generate_lexicon(start: int = 0, stop: int = 99) -> list[NumberLexemeNL]:
    if start > stop:
        raise ValueError("start must be <= stop")
    return [lexeme(value) for value in range(start, stop + 1)]


def pulse_match_values(values: Iterable[int] = range(100)) -> list[int]:
    return [value for value in values if lexeme(value).pulse_match]


def phonetic_pulses(value: int) -> tuple[int, ...]:
    """Return one active pulse per pronunciation segment."""

    return tuple(1 for _ in lexeme(value).pronunciation_segments)
