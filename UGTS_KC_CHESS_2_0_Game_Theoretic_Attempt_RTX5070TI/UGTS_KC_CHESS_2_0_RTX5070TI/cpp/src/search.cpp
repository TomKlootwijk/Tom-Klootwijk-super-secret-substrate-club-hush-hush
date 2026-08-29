#include "ugts_chess2/search.hpp"

#include <algorithm>
#include <array>
#include <limits>
#include <stdexcept>
#include <unordered_map>

namespace ugts::chess2 {
namespace {
constexpr int INF = 1'000'000;
constexpr int MATE = 900'000;

int piece_value(char piece) noexcept {
    switch (piece_type(piece)) {
        case 'P': return 100;
        case 'N': return 320;
        case 'B': return 330;
        case 'R': return 500;
        case 'Q': return 900;
        default: return 0;
    }
}

struct NodeBudgetExceeded : std::runtime_error { using std::runtime_error::runtime_error; };

struct SearchContext {
    std::uint64_t nodes = 0;
    std::uint64_t budget = 0;
    std::unordered_map<std::uint64_t, std::pair<int, int>> tt;  // key -> (depth, score), heuristic cache only.
};

std::vector<Move> ordered_moves(const Position& position) {
    auto moves = legal_moves(position);
    std::stable_sort(moves.begin(), moves.end(), [&](const Move& a, const Move& b) {
        auto score = [&](const Move& move) {
            int s = 0;
            if (move.is_capture()) {
                char victim = position.board[move.to];
                if (move.is_en_passant()) victim = position.turn == Color::White ? 'p' : 'P';
                s += 10'000 + piece_value(victim) - piece_value(position.board[move.from]) / 10;
            }
            if (move.is_promotion()) s += 8'000 + piece_value(move.promotion);
            if (move.is_castle()) s += 100;
            return s;
        };
        return score(a) > score(b);
    });
    return moves;
}

int negamax(const Position& position, int depth, int ply, int alpha, int beta,
            SearchContext& ctx, std::vector<Move>& pv) {
    if (++ctx.nodes > ctx.budget) throw NodeBudgetExceeded("search node budget exceeded");
    const auto status = position_status(position, nullptr, true);
    if (status.terminal) {
        if (status.code == "checkmate") return -MATE + ply;
        return 0;
    }
    if (depth == 0) return static_evaluate(position);

    const auto key = cache_key64(position);
    if (const auto it = ctx.tt.find(key); it != ctx.tt.end() && it->second.first >= depth) return it->second.second;

    int best = -INF;
    std::vector<Move> best_pv;
    for (const Move& move : ordered_moves(position)) {
        std::vector<Move> child_pv;
        const int score = -negamax(apply_move(position, move), depth - 1, ply + 1, -beta, -alpha, ctx, child_pv);
        if (score > best) {
            best = score;
            best_pv.clear();
            best_pv.push_back(move);
            best_pv.insert(best_pv.end(), child_pv.begin(), child_pv.end());
        }
        alpha = std::max(alpha, score);
        if (alpha >= beta) break;
    }
    pv = std::move(best_pv);
    ctx.tt[key] = {depth, best};
    return best;
}

bool mate_rec(const Position& position, Color attacker, int plies_left,
              std::uint64_t budget, std::uint64_t& nodes, std::vector<Move>& line) {
    if (++nodes > budget) throw NodeBudgetExceeded("mate proof node budget exceeded");
    const auto status = position_status(position, nullptr, false);
    if (status.terminal) return status.code == "checkmate" && status.winner && *status.winner == attacker;
    if (plies_left <= 0) return false;

    const auto moves = legal_moves(position);
    if (position.turn == attacker) {
        for (const Move& move : moves) {
            std::vector<Move> child_line;
            if (mate_rec(apply_move(position, move), attacker, plies_left - 1, budget, nodes, child_line)) {
                line.clear();
                line.push_back(move);
                line.insert(line.end(), child_line.begin(), child_line.end());
                return true;
            }
        }
        return false;
    }

    // Defender node: every legal reply must preserve the forced mate. Keep the longest representative line.
    std::vector<Move> representative;
    for (const Move& move : moves) {
        std::vector<Move> child_line;
        if (!mate_rec(apply_move(position, move), attacker, plies_left - 1, budget, nodes, child_line)) return false;
        std::vector<Move> candidate;
        candidate.push_back(move);
        candidate.insert(candidate.end(), child_line.begin(), child_line.end());
        if (candidate.size() > representative.size()) representative = std::move(candidate);
    }
    line = std::move(representative);
    return true;
}
}  // namespace

int static_evaluate(const Position& position) {
    int score = 0;
    for (int sq = 0; sq < 64; ++sq) {
        const char piece = position.board[sq];
        const auto color = piece_color(piece);
        if (!color) continue;
        int value = piece_value(piece);
        const int center_distance = std::abs(file_of(sq) * 2 - 7) + std::abs(rank_of(sq) * 2 - 7);
        if (piece_type(piece) == 'N' || piece_type(piece) == 'B') value += 14 - center_distance;
        score += *color == Color::White ? value : -value;
    }
    return position.turn == Color::White ? score : -score;
}

SearchResult search_position(const Position& root, int depth, std::uint64_t node_budget) {
    if (depth < 1) throw std::invalid_argument("search depth must be positive");
    SearchResult result;
    result.depth = depth;
    SearchContext ctx;
    ctx.budget = node_budget;
    try {
        result.score_cp = negamax(root, depth, 0, -INF, INF, ctx, result.principal_variation);
        result.status = "completed_estimate";
    } catch (const NodeBudgetExceeded&) {
        result.status = "budget_exhausted_estimate";
    }
    result.nodes = ctx.nodes;
    result.exact_mate_score = std::abs(result.score_cp) > MATE - 10'000;
    return result;
}

MateProofResult prove_forced_mate(const Position& root, int max_plies, std::uint64_t node_budget) {
    if (max_plies < 0) throw std::invalid_argument("max plies must be non-negative");
    MateProofResult result;
    result.max_plies = max_plies;
    try {
        result.proved = mate_rec(root, root.turn, max_plies, node_budget, result.nodes, result.principal_line);
        result.status = result.proved ? "proved" : "not_forced_within_horizon";
    } catch (const NodeBudgetExceeded&) {
        result.status = "node_budget_exhausted";
    }
    return result;
}

}  // namespace ugts::chess2
