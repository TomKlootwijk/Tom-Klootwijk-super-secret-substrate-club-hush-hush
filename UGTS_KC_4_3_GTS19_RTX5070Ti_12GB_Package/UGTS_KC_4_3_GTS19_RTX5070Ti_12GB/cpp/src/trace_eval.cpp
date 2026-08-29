#include "ugts_go19/go_state.hpp"

#include <algorithm>
#include <charconv>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {

constexpr std::string_view kProtocol = "UGTS_TRACE_V1";

struct Request {
  std::uint64_t id = 0;
  ugts_go19::Rules rules;
  ugts_go19::State state;
};

std::vector<std::string> Split(const std::string& value, char delimiter) {
  std::vector<std::string> fields;
  std::size_t begin = 0;
  while (true) {
    const std::size_t end = value.find(delimiter, begin);
    if (end == std::string::npos) {
      fields.push_back(value.substr(begin));
      return fields;
    }
    fields.push_back(value.substr(begin, end - begin));
    begin = end + 1;
  }
}

int ParseInt(const std::string& value, const char* label) {
  int parsed = 0;
  const char* begin = value.data();
  const char* end = begin + value.size();
  const auto result = std::from_chars(begin, end, parsed);
  if (result.ec != std::errc{} || result.ptr != end) {
    throw std::invalid_argument(std::string("invalid ") + label);
  }
  return parsed;
}

std::uint64_t ParseUint64(const std::string& value, const char* label) {
  std::uint64_t parsed = 0;
  const char* begin = value.data();
  const char* end = begin + value.size();
  const auto result = std::from_chars(begin, end, parsed);
  if (result.ec != std::errc{} || result.ptr != end) {
    throw std::invalid_argument(std::string("invalid ") + label);
  }
  return parsed;
}

bool ParseBool(const std::string& value, const char* label) {
  if (value == "0") return false;
  if (value == "1") return true;
  throw std::invalid_argument(std::string("invalid ") + label);
}

std::uint8_t HexDigit(char value) {
  if (value >= '0' && value <= '9') {
    return static_cast<std::uint8_t>(value - '0');
  }
  if (value >= 'a' && value <= 'f') {
    return static_cast<std::uint8_t>(value - 'a' + 10);
  }
  if (value >= 'A' && value <= 'F') {
    return static_cast<std::uint8_t>(value - 'A' + 10);
  }
  throw std::invalid_argument("invalid hexadecimal byte string");
}

std::vector<std::uint8_t> ParseHex(const std::string& value) {
  if (value.size() % 2 != 0) {
    throw std::invalid_argument("hexadecimal byte string has odd length");
  }
  std::vector<std::uint8_t> bytes(value.size() / 2);
  for (std::size_t index = 0; index < bytes.size(); ++index) {
    const auto high = HexDigit(value[2 * index]);
    const auto low = HexDigit(value[2 * index + 1]);
    bytes[index] = static_cast<std::uint8_t>((high << 4U) | low);
  }
  return bytes;
}

std::string Hex(const std::vector<std::uint8_t>& bytes) {
  constexpr char digits[] = "0123456789abcdef";
  std::string output(bytes.size() * 2, '0');
  for (std::size_t index = 0; index < bytes.size(); ++index) {
    output[2 * index] = digits[bytes[index] >> 4U];
    output[2 * index + 1] = digits[bytes[index] & 0x0fU];
  }
  return output;
}

Request ParseRequest(const std::string& line) {
  const auto fields = Split(line, '|');
  if (fields.size() != 12 || fields[0] != kProtocol) {
    throw std::invalid_argument(
        "expected 12-field UGTS_TRACE_V1 request");
  }

  Request request;
  request.id = ParseUint64(fields[1], "request id");
  request.rules.size = ParseInt(fields[2], "board size");
  request.rules.komi2 = ParseInt(fields[3], "komi2");
  request.rules.allow_suicide = ParseBool(fields[4], "allow_suicide");
  request.rules.passes_to_end = ParseInt(fields[5], "passes_to_end");

  request.state.size = request.rules.size;
  const int to_play = ParseInt(fields[6], "player to move");
  if (to_play < 0 || to_play > 255) {
    throw std::invalid_argument("player to move is outside uint8 range");
  }
  request.state.to_play = static_cast<std::uint8_t>(to_play);
  request.state.passes = ParseInt(fields[7], "pass count");
  request.state.ply = ParseUint64(fields[8], "ply");
  request.state.board = ParseHex(fields[9]);
  if (fields[10] != "-") {
    request.state.previous_board = ParseHex(fields[10]);
  }
  if (fields[11] != "-") {
    for (const auto& seen : Split(fields[11], ',')) {
      if (seen.empty()) {
        throw std::invalid_argument("empty seen-board field");
      }
      request.state.seen_boards.push_back(ParseHex(seen));
    }
  }
  return request;
}

void WriteMoves(const std::vector<int>& moves) {
  std::cout << '[';
  for (std::size_t index = 0; index < moves.size(); ++index) {
    if (index != 0) std::cout << ',';
    std::cout << moves[index];
  }
  std::cout << ']';
}

void WriteSeenBoards(const ugts_go19::State& state) {
  auto seen = state.seen_boards;
  std::sort(seen.begin(), seen.end());
  seen.erase(std::unique(seen.begin(), seen.end()), seen.end());
  std::cout << '[';
  for (std::size_t index = 0; index < seen.size(); ++index) {
    if (index != 0) std::cout << ',';
    std::cout << '"' << Hex(seen[index]) << '"';
  }
  std::cout << ']';
}

void WriteStateRecord(const Request& request,
                      const std::vector<int>& legal_moves) {
  std::cout << "{\"protocol\":\"" << kProtocol
            << "\",\"kind\":\"state\",\"id\":" << request.id
            << ",\"terminal\":"
            << (request.state.Terminal(request.rules) ? "true" : "false")
            << ",\"score2\":"
            << ugts_go19::AreaScore2(request.state, request.rules)
            << ",\"legal\":";
  WriteMoves(legal_moves);
  std::cout << "}\n";
}

void WriteMoveRecord(std::uint64_t id, int move,
                     const ugts_go19::ApplyResult& result,
                     const ugts_go19::Rules& rules) {
  const auto& state = result.state;
  std::cout << "{\"protocol\":\"" << kProtocol
            << "\",\"kind\":\"move\",\"id\":" << id
            << ",\"move\":" << move << ",\"board\":\""
            << Hex(state.board) << "\",\"captured\":" << result.captured
            << ",\"self_captured\":" << result.self_captured
            << ",\"to_play\":" << static_cast<int>(state.to_play)
            << ",\"passes\":" << state.passes
            << ",\"previous_board\":";
  if (state.previous_board.has_value()) {
    std::cout << '"' << Hex(*state.previous_board) << '"';
  } else {
    std::cout << "null";
  }
  std::cout << ",\"seen\":";
  WriteSeenBoards(state);
  std::cout << ",\"ply\":" << state.ply << ",\"terminal\":"
            << (state.Terminal(rules) ? "true" : "false")
            << ",\"score2\":" << ugts_go19::AreaScore2(state, rules)
            << "}\n";
}

void Evaluate(const Request& request) {
  const auto legal_moves =
      ugts_go19::LegalMoves(request.state, request.rules, true);
  WriteStateRecord(request, legal_moves);
  for (int move : legal_moves) {
    const auto result =
        ugts_go19::ApplyMove(request.state, move, request.rules);
    WriteMoveRecord(request.id, move, result, request.rules);
  }
}

void PrintUsage() {
  std::cout
      << "Read one UGTS_TRACE_V1 state per line from stdin and emit JSONL state "
         "and move records. See cpp/tests/TRACE_PROTOCOL.md.\n";
}

}  // namespace

int main(int argc, char** argv) {
  if (argc == 2 && std::string_view(argv[1]) == "--help") {
    PrintUsage();
    return 0;
  }
  if (argc != 1) {
    PrintUsage();
    return 2;
  }

  std::ios::sync_with_stdio(false);
  std::string line;
  std::size_t line_number = 0;
  try {
    while (std::getline(std::cin, line)) {
      ++line_number;
      if (!line.empty() && line.back() == '\r') line.pop_back();
      if (line.empty()) continue;
      Evaluate(ParseRequest(line));
    }
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "ugts_go_trace_eval: line " << line_number << ": "
              << error.what() << '\n';
    return 1;
  }
}
