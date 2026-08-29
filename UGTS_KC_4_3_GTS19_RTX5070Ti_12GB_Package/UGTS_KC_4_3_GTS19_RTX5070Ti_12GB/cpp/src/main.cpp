#include "ugts_go19/go_state.hpp"

#include <exception>
#include <iostream>

int main() {
  try {
    ugts_go19::Rules rules;
    rules.size = 5;
    rules.komi2 = 1;
    auto state = ugts_go19::State::Initial(rules);
    const auto initial_legal = ugts_go19::LegalMoves(state, rules).size();
    state = ugts_go19::ApplyMove(state, 12, rules).state;
    state = ugts_go19::ApplyMove(state, 7, rules).state;
    const auto black = ugts_go19::PackBlackBitplane(state);
    const auto white = ugts_go19::PackWhiteBitplane(state);
    std::cout << "{\n"
              << "  \"ok\": true,\n"
              << "  \"board_size\": 5,\n"
              << "  \"initial_legal_including_pass\": " << initial_legal << ",\n"
              << "  \"black_bitplane_words\": " << black.size() << ",\n"
              << "  \"white_bitplane_words\": " << white.size() << ",\n"
              << "  \"board_digest_diagnostic\": \""
              << ugts_go19::BoardDigestHex(state) << "\",\n"
              << "  \"score2_if_scored_now\": "
              << ugts_go19::AreaScore2(state, rules) << "\n"
              << "}\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "ugts_go19_smoke: " << error.what() << "\n";
    return 1;
  }
}
