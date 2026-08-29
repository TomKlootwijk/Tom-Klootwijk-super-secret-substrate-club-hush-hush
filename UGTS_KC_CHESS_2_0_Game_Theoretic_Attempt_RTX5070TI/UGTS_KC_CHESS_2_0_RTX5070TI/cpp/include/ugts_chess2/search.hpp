#pragma once

#include "ugts_chess2/core.hpp"

#include <cstdint>
#include <string>
#include <vector>

namespace ugts::chess2 {

struct SearchResult {
    int depth = 0;
    std::uint64_t nodes = 0;
    int score_cp = 0;
    bool exact_mate_score = false;
    std::vector<Move> principal_variation;
    std::string status = "estimate";
};

[[nodiscard]] int static_evaluate(const Position& position);
[[nodiscard]] SearchResult search_position(const Position& root, int depth,
                                           std::uint64_t node_budget = 10'000'000);

struct MateProofResult {
    bool proved = false;
    int max_plies = 0;
    std::uint64_t nodes = 0;
    std::vector<Move> principal_line;
    std::string status;
};

[[nodiscard]] MateProofResult prove_forced_mate(const Position& root, int max_plies,
                                                std::uint64_t node_budget = 2'000'000);

}  // namespace ugts::chess2
