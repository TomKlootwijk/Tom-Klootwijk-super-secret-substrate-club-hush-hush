"""Move record and UCI representation."""
from __future__ import annotations

from dataclasses import dataclass

from .constants import square_name

FLAG_CAPTURE = 1 << 0
FLAG_EN_PASSANT = 1 << 1
FLAG_CASTLE = 1 << 2
FLAG_PROMOTION = 1 << 3
FLAG_DOUBLE_PAWN = 1 << 4


@dataclass(frozen=True, slots=True, order=True)
class Move:
    from_sq: int
    to_sq: int
    promotion: str = ""
    flags: int = 0

    @property
    def is_capture(self) -> bool:
        return bool(self.flags & FLAG_CAPTURE)

    @property
    def is_en_passant(self) -> bool:
        return bool(self.flags & FLAG_EN_PASSANT)

    @property
    def is_castle(self) -> bool:
        return bool(self.flags & FLAG_CASTLE)

    @property
    def is_promotion(self) -> bool:
        return bool(self.flags & FLAG_PROMOTION)

    @property
    def is_double_pawn(self) -> bool:
        return bool(self.flags & FLAG_DOUBLE_PAWN)

    def uci(self) -> str:
        suffix = self.promotion.lower() if self.promotion else ""
        return f"{square_name(self.from_sq)}{square_name(self.to_sq)}{suffix}"

    def to_dict(self) -> dict[str, object]:
        return {
            "from": square_name(self.from_sq),
            "to": square_name(self.to_sq),
            "promotion": self.promotion.lower() or None,
            "flags": self.flags,
            "uci": self.uci(),
        }

    def __str__(self) -> str:
        return self.uci()
