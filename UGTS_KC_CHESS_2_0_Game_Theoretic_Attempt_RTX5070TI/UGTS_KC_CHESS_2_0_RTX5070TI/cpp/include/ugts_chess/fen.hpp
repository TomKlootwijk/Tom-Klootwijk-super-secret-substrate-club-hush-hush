#pragma once

#include <string>
#include <string_view>
#include <vector>

#include "ugts_chess/packed_chess.hpp"

namespace ugts::chess {

bool parse_fen(std::string_view fen, PackedPosition& out, std::string& error);
std::string to_fen(const PackedPosition& position);
std::string move_to_uci(std::uint16_t move);
bool parse_uci(std::string_view uci, std::uint16_t& move, std::string& error);
std::vector<std::string> legal_uci_moves(const PackedPosition& position);

}  // namespace ugts::chess
