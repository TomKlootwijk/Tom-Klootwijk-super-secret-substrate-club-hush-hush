"""UGTS-KC Chess 2.0: game-theoretic proof campaign and CUDA handoff."""
from .constants import BLACK, WHITE
from .move import Move
from .position import Position, START_FEN
from .proof import MateProver, verify_mate_certificate
from .rules import apply_move, legal_moves, move_to_san, parse_uci_move, perft, position_status
from .search import Searcher
from .game_state import HistoryContext, automatic_status, current_claim_actions, game_state_sha256
from .wdl import BoundedWDLSolver, WDL

__all__ = [
    "BLACK", "WHITE", "Move", "Position", "START_FEN",
    "MateProver", "verify_mate_certificate", "apply_move", "legal_moves",
    "move_to_san", "parse_uci_move", "perft", "position_status", "Searcher",
    "HistoryContext", "automatic_status", "current_claim_actions",
    "game_state_sha256", "BoundedWDLSolver", "WDL",
]

__version__ = "2.0.0"
