"""Deterministic alpha-beta search with quiescence and transposition records."""
from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass
from enum import IntEnum

from .constants import PIECE_VALUES, WHITE, piece_type
from .evaluate import evaluate
from .hashing import compact_key64, repetition_key, state_sha256
from .move import Move
from .position import Position
from .rules import apply_move, in_check, legal_moves, move_gives_check, move_to_san, position_status

INF = 1_000_000
MATE_SCORE = 100_000
MATE_THRESHOLD = 90_000


class Bound(IntEnum):
    EXACT = 0
    LOWER = 1
    UPPER = 2


@dataclass(slots=True)
class TTEntry:
    depth: int
    score: int
    bound: Bound
    best_move: Move | None


@dataclass(frozen=True, slots=True)
class SearchResult:
    best_move: Move | None
    score: int
    depth: int
    nodes: int
    qnodes: int
    tt_hits: int
    elapsed_seconds: float
    principal_variation: tuple[Move, ...]
    completed: bool
    root_hash: str

    @property
    def nps(self) -> int:
        elapsed = max(self.elapsed_seconds, 1e-9)
        return int((self.nodes + self.qnodes) / elapsed)

    def score_text(self) -> str:
        if abs(self.score) >= MATE_THRESHOLD:
            plies = MATE_SCORE - abs(self.score)
            moves = (plies + 1) // 2
            return f"mate {'+' if self.score > 0 else '-'}{moves}"
        return f"{self.score / 100:.2f} pawns"

    def to_dict(self, root: Position | None = None) -> dict[str, object]:
        pv_uci = [move.uci() for move in self.principal_variation]
        pv_san: list[str] = []
        if root is not None:
            current = root
            try:
                for move in self.principal_variation:
                    pv_san.append(move_to_san(current, move))
                    current = apply_move(current, move)
            except ValueError:
                pv_san = []
        return {
            "best_move": None if self.best_move is None else self.best_move.uci(),
            "score": self.score,
            "score_text": self.score_text(),
            "depth": self.depth,
            "nodes": self.nodes,
            "qnodes": self.qnodes,
            "tt_hits": self.tt_hits,
            "elapsed_seconds": self.elapsed_seconds,
            "nodes_per_second": self.nps,
            "principal_variation_uci": pv_uci,
            "principal_variation_san": pv_san,
            "completed": self.completed,
            "root_hash": self.root_hash,
        }


class SearchTimeout(RuntimeError):
    pass


class Searcher:
    def __init__(self, *, claim_draws: bool = True, tt_capacity: int = 500_000) -> None:
        self.claim_draws = claim_draws
        self.tt_capacity = max(1_000, tt_capacity)
        self.tt: dict[int, TTEntry] = {}
        self.nodes = 0
        self.qnodes = 0
        self.tt_hits = 0
        self.deadline: float | None = None

    def _check_time(self) -> None:
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise SearchTimeout

    @staticmethod
    def _score_to_tt(score: int, ply: int) -> int:
        if score >= MATE_THRESHOLD:
            return score + ply
        if score <= -MATE_THRESHOLD:
            return score - ply
        return score

    @staticmethod
    def _score_from_tt(score: int, ply: int) -> int:
        if score >= MATE_THRESHOLD:
            return score - ply
        if score <= -MATE_THRESHOLD:
            return score + ply
        return score

    def _terminal_score(self, position: Position, ply: int, history: Counter[str]) -> int | None:
        status = position_status(position, history_keys=history.elements(), claim_draws=self.claim_draws)
        if not status.terminal:
            return None
        if status.code == "checkmate":
            return -MATE_SCORE + ply
        return 0

    @staticmethod
    def _capture_score(position: Position, move: Move) -> int:
        if not move.is_capture:
            return 0
        victim = position.board[move.to_sq]
        if move.is_en_passant:
            victim = "p" if position.turn == WHITE else "P"
        attacker = position.board[move.from_sq]
        return 10 * PIECE_VALUES.get(piece_type(victim), 0) - PIECE_VALUES[piece_type(attacker)]

    def _ordered_moves(self, position: Position, moves: list[Move], tt_move: Move | None = None) -> list[Move]:
        def key(move: Move) -> tuple[int, int, int, str]:
            return (
                1 if tt_move is not None and move == tt_move else 0,
                1 if move.promotion else 0,
                self._capture_score(position, move),
                move.uci(),
            )

        return sorted(moves, key=key, reverse=True)

    def _quiescence(self, position: Position, alpha: int, beta: int, ply: int, history: Counter[str]) -> tuple[int, list[Move]]:
        self._check_time()
        self.qnodes += 1
        terminal = self._terminal_score(position, ply, history)
        if terminal is not None:
            return terminal, []

        checked = in_check(position)
        stand_pat = evaluate(position)
        if not checked:
            if stand_pat >= beta:
                return beta, []
            if stand_pat > alpha:
                alpha = stand_pat

        moves = legal_moves(position)
        if not checked:
            moves = [move for move in moves if move.is_capture or move.promotion]
        moves = self._ordered_moves(position, moves)
        best_line: list[Move] = []
        for move in moves:
            child = apply_move(position, move)
            key = repetition_key(child)
            history[key] += 1
            score, line = self._quiescence(child, -beta, -alpha, ply + 1, history)
            history[key] -= 1
            if history[key] == 0:
                del history[key]
            score = -score
            if score >= beta:
                return beta, [move] + line
            if score > alpha:
                alpha = score
                best_line = [move] + line
        return alpha, best_line

    def _negamax(
        self,
        position: Position,
        depth: int,
        alpha: int,
        beta: int,
        ply: int,
        history: Counter[str],
    ) -> tuple[int, list[Move]]:
        self._check_time()
        self.nodes += 1
        terminal = self._terminal_score(position, ply, history)
        if terminal is not None:
            return terminal, []
        if depth <= 0:
            return self._quiescence(position, alpha, beta, ply, history)

        key64 = compact_key64(position)
        entry = self.tt.get(key64)
        original_alpha = alpha
        tt_move: Move | None = None
        if entry is not None:
            tt_move = entry.best_move
            if entry.depth >= depth:
                self.tt_hits += 1
                score = self._score_from_tt(entry.score, ply)
                if entry.bound == Bound.EXACT:
                    return score, []
                if entry.bound == Bound.LOWER:
                    alpha = max(alpha, score)
                else:
                    beta = min(beta, score)
                if alpha >= beta:
                    return score, []

        moves = self._ordered_moves(position, legal_moves(position), tt_move)
        best_score = -INF
        best_move: Move | None = None
        best_line: list[Move] = []
        for move in moves:
            child = apply_move(position, move)
            child_key = repetition_key(child)
            history[child_key] += 1
            score, line = self._negamax(child, depth - 1, -beta, -alpha, ply + 1, history)
            history[child_key] -= 1
            if history[child_key] == 0:
                del history[child_key]
            score = -score
            if score > best_score:
                best_score = score
                best_move = move
                best_line = [move] + line
            if score > alpha:
                alpha = score
            if alpha >= beta:
                break

        bound = Bound.EXACT
        if best_score <= original_alpha:
            bound = Bound.UPPER
        elif best_score >= beta:
            bound = Bound.LOWER
        if len(self.tt) >= self.tt_capacity:
            # Deterministic coarse eviction: discard the shallowest quarter.
            shallow = sorted(self.tt.items(), key=lambda kv: (kv[1].depth, kv[0]))[: self.tt_capacity // 4]
            for evict_key, _ in shallow:
                self.tt.pop(evict_key, None)
        self.tt[key64] = TTEntry(depth, self._score_to_tt(best_score, ply), bound, best_move)
        return best_score, best_line

    def search(
        self,
        position: Position,
        *,
        max_depth: int = 5,
        time_limit: float | None = None,
        history_keys: list[str] | None = None,
    ) -> SearchResult:
        if max_depth < 1:
            raise ValueError("max_depth must be at least 1")
        self.nodes = self.qnodes = self.tt_hits = 0
        self.deadline = None if time_limit is None else time.monotonic() + max(0.001, time_limit)
        start = time.monotonic()
        history = Counter(history_keys or [])
        history[repetition_key(position)] += 1

        best_score = 0
        best_line: list[Move] = []
        completed_depth = 0
        completed = True
        for depth in range(1, max_depth + 1):
            try:
                score, line = self._negamax(position, depth, -INF, INF, 0, history)
            except SearchTimeout:
                completed = False
                break
            best_score, best_line = score, line
            completed_depth = depth
            if abs(score) >= MATE_THRESHOLD and (MATE_SCORE - abs(score)) < depth:
                break
        elapsed = time.monotonic() - start
        return SearchResult(
            best_move=best_line[0] if best_line else None,
            score=best_score,
            depth=completed_depth,
            nodes=self.nodes,
            qnodes=self.qnodes,
            tt_hits=self.tt_hits,
            elapsed_seconds=elapsed,
            principal_variation=tuple(best_line),
            completed=completed,
            root_hash=state_sha256(position),
        )
