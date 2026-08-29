"""UGTS-KC 4.3 exactness-first Go search foundation."""

from .constants import BLACK, EMPTY, PASS, WHITE
from .rules import Rules
from .state import State
from .engine import IllegalMove, apply_move, legal_moves
from .score import area_score2

__all__ = [
    "BLACK",
    "EMPTY",
    "PASS",
    "WHITE",
    "Rules",
    "State",
    "IllegalMove",
    "apply_move",
    "legal_moves",
    "area_score2",
]

__version__ = "4.3.0"
