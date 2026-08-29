#include "ugts_go19/cuda_verified_expander.hpp"

#include <cuda_runtime.h>

#include <algorithm>
#include <charconv>
#include <cstdint>
#include <exception>
#include <iostream>
#include <limits>
#include <locale>
#include <stdexcept>
#include <string>
#include <string_view>
#include <system_error>
#include <utility>
#include <vector>

namespace {

constexpr std::string_view kInputProtocol = "UGTS_CUDA_LOCAL_INPUT_V1";
constexpr std::string_view kOutputProtocol = "UGTS_CUDA_LOCAL_OUTPUT_V1";

struct Request {
  std::uint64_t id = 0;
  ugts_go19::State state;
};

struct InputBatch {
  ugts_go19::Rules rules;
  std::vector<Request> requests;
};

void CheckCuda(cudaError_t status, const char *operation) {
  if (status != cudaSuccess) {
    throw std::runtime_error(std::string(operation) + ": " +
                             cudaGetErrorString(status));
  }
}

std::vector<std::string> Split(const std::string &value, char delimiter) {
  std::vector<std::string> fields;
  std::size_t begin = 0;
  while (true) {
    const std::size_t end = value.find(delimiter, begin);
    if (end == std::string::npos) {
      fields.push_back(value.substr(begin));
      return fields;
    }
    fields.push_back(value.substr(begin, end - begin));
    begin = end + 1U;
  }
}

template <typename T>
T ParseInteger(const std::string &value, const char *label) {
  T parsed{};
  const char *begin = value.data();
  const char *end = begin + value.size();
  const auto result = std::from_chars(begin, end, parsed);
  if (value.empty() || result.ec != std::errc{} || result.ptr != end) {
    throw std::invalid_argument(std::string("invalid ") + label);
  }
  return parsed;
}

std::uint8_t HexDigit(char value) {
  if (value >= '0' && value <= '9') {
    return static_cast<std::uint8_t>(value - '0');
  }
  if (value >= 'a' && value <= 'f') {
    return static_cast<std::uint8_t>(value - 'a' + 10);
  }
  throw std::invalid_argument("invalid lowercase hexadecimal input");
}

std::vector<std::uint8_t> ParseHex(const std::string &value) {
  if (value.size() % 2U != 0U) {
    throw std::invalid_argument("hexadecimal board has odd length");
  }
  std::vector<std::uint8_t> result(value.size() / 2U);
  for (std::size_t index = 0; index < result.size(); ++index) {
    result[index] = static_cast<std::uint8_t>(
        (HexDigit(value[2U * index]) << 4U) |
        HexDigit(value[2U * index + 1U]));
  }
  return result;
}

std::string Hex(const std::vector<std::uint8_t> &bytes) {
  constexpr char digits[] = "0123456789abcdef";
  std::string result(bytes.size() * 2U, '0');
  for (std::size_t index = 0; index < bytes.size(); ++index) {
    result[2U * index] = digits[bytes[index] >> 4U];
    result[2U * index + 1U] = digits[bytes[index] & 0x0fU];
  }
  return result;
}

std::string HexBytes(const char *value) {
  const auto *bytes = reinterpret_cast<const unsigned char *>(value);
  std::vector<std::uint8_t> data;
  while (*bytes != 0U) {
    data.push_back(*bytes);
    ++bytes;
  }
  return Hex(data);
}

std::string TakeLine(const char *label) {
  std::string line;
  if (!std::getline(std::cin, line)) {
    throw std::invalid_argument(std::string("truncated input at ") + label);
  }
  if (!line.empty() && line.back() == '\r') line.pop_back();
  return line;
}

InputBatch ReadBatch() {
  if (TakeLine("header") != kInputProtocol) {
    throw std::invalid_argument("unexpected local-transition input header");
  }
  const auto rules_fields = Split(TakeLine("rules"), ' ');
  if (rules_fields.size() != 4U || rules_fields[0] != "RULES") {
    throw std::invalid_argument("invalid RULES record");
  }
  InputBatch batch;
  batch.rules.size = ParseInteger<int>(rules_fields[1], "board size");
  batch.rules.komi2 = ParseInteger<int>(rules_fields[2], "komi2");
  batch.rules.allow_suicide = false;
  batch.rules.passes_to_end =
      ParseInteger<int>(rules_fields[3], "passes-to-end");

  const auto count_fields = Split(TakeLine("count"), ' ');
  if (count_fields.size() != 2U || count_fields[0] != "COUNT") {
    throw std::invalid_argument("invalid COUNT record");
  }
  const std::size_t count =
      ParseInteger<std::size_t>(count_fields[1], "state count");
  if (count == 0U || count > 4096U) {
    throw std::invalid_argument("state count must be in 1..4096");
  }
  batch.requests.reserve(count);
  for (std::size_t index = 0; index < count; ++index) {
    const auto fields = Split(TakeLine("state"), ' ');
    if (fields.size() != 8U || fields[0] != "STATE") {
      throw std::invalid_argument("invalid STATE record");
    }
    Request request;
    request.id = ParseInteger<std::uint64_t>(fields[1], "state id");
    request.state.size = batch.rules.size;
    const int player = ParseInteger<int>(fields[2], "player");
    if (player < 0 || player > 255) {
      throw std::invalid_argument("player does not fit uint8");
    }
    request.state.to_play = static_cast<std::uint8_t>(player);
    request.state.passes = ParseInteger<int>(fields[3], "passes");
    request.state.ply = ParseInteger<std::uint64_t>(fields[4], "ply");
    request.state.board = ParseHex(fields[5]);
    if (fields[6] != "-") {
      request.state.previous_board = ParseHex(fields[6]);
    }
    if (fields[7] != "-") {
      for (const auto &seen : Split(fields[7], ',')) {
        if (seen.empty()) throw std::invalid_argument("empty seen board");
        request.state.seen_boards.push_back(ParseHex(seen));
      }
    }
    batch.requests.push_back(std::move(request));
  }
  if (TakeLine("terminator") != "END") {
    throw std::invalid_argument("invalid input terminator");
  }
  std::string trailing;
  if (std::getline(std::cin, trailing)) {
    if (!trailing.empty() && trailing.back() == '\r') trailing.pop_back();
    if (!trailing.empty()) throw std::invalid_argument("trailing input data");
  }
  return batch;
}

template <typename Function>
void ExpectFailure(Function &&function, const char *label,
                   std::size_t *checks) {
  try {
    function();
  } catch (const std::exception &) {
    ++*checks;
    return;
  }
  throw std::runtime_error(std::string("negative check did not fail: ") + label);
}

std::size_t RunNegativeChecks() {
  using ugts_go19::cuda::LaunchLocalPointTransitions;
  const auto *word1 = reinterpret_cast<const std::uint64_t *>(0x100000U);
  const auto *word2 = reinterpret_cast<const std::uint64_t *>(0x200000U);
  const auto *player = reinterpret_cast<const std::uint8_t *>(0x300000U);
  auto *empty = reinterpret_cast<std::uint64_t *>(0x400000U);
  auto *status = reinterpret_cast<std::uint8_t *>(0x500000U);
  auto *captured = reinterpret_cast<std::uint16_t *>(0x600000U);
  auto *self_captured = reinterpret_cast<std::uint16_t *>(0x700000U);
  auto *child_black = reinterpret_cast<std::uint64_t *>(0x800000U);
  auto *child_white = reinterpret_cast<std::uint64_t *>(0x900000U);
  auto *errors = reinterpret_cast<std::uint32_t *>(0xa00000U);
  std::size_t checks = 0;

  ExpectFailure(
      [&] {
        LaunchLocalPointTransitions(
            nullptr, word2, player, empty, status, captured, self_captured,
            child_black, child_white, errors, 1U, 19, nullptr);
      },
      "null input", &checks);
  ExpectFailure(
      [&] {
        LaunchLocalPointTransitions(
            word1, word2, player, empty, status, captured, self_captured,
            child_black, child_white, errors, 0U, 19, nullptr);
      },
      "zero states", &checks);
  ExpectFailure(
      [&] {
        LaunchLocalPointTransitions(
            word1, word2, player, empty, status, captured, self_captured,
            child_black, child_white, errors, 1U, 0, nullptr);
      },
      "zero board size", &checks);
  ExpectFailure(
      [&] {
        LaunchLocalPointTransitions(
            word1, word2, player, empty, status, captured, self_captured,
            child_black, child_white, errors, 1U, 20, nullptr);
      },
      "oversized board", &checks);
  ExpectFailure(
      [&] {
        LaunchLocalPointTransitions(
            word1, word2, player, empty, status, captured, self_captured,
            child_black, child_white, errors,
            std::numeric_limits<std::size_t>::max(), 19, nullptr);
      },
      "count overflow", &checks);
  ExpectFailure(
      [&] {
        LaunchLocalPointTransitions(
            word1, word2, player, const_cast<std::uint64_t *>(word1), status,
            captured, self_captured, child_black, child_white, errors, 1U, 1,
            nullptr);
      },
      "input-output alias", &checks);
  ExpectFailure(
      [&] {
        LaunchLocalPointTransitions(
            word1, word2, player, empty, status,
            reinterpret_cast<std::uint16_t *>(status), self_captured,
            child_black, child_white, errors, 1U, 1, nullptr);
      },
      "output-output alias", &checks);

  ugts_go19::Rules rules;
  rules.size = 3;
  rules.komi2 = 1;
  ugts_go19::State initial = ugts_go19::State::Initial(rules);
  ugts_go19::Rules suicide_rules = rules;
  suicide_rules.allow_suicide = true;
  ExpectFailure(
      [&] {
        static_cast<void>(ugts_go19::cuda::VerifyCudaLocalPointTransitions(
            {initial}, suicide_rules));
      },
      "allow-suicide profile", &checks);
  ugts_go19::State terminal = initial;
  terminal.passes = rules.passes_to_end;
  ExpectFailure(
      [&] {
        static_cast<void>(ugts_go19::cuda::VerifyCudaLocalPointTransitions(
            {terminal}, rules));
      },
      "terminal state", &checks);
  ugts_go19::State exhausted = initial;
  exhausted.ply = std::numeric_limits<std::uint64_t>::max();
  ExpectFailure(
      [&] {
        static_cast<void>(ugts_go19::cuda::VerifyCudaLocalPointTransitions(
            {exhausted}, rules));
      },
      "ply exhaustion", &checks);
  return checks;
}

bool SameState(const ugts_go19::State &left, const ugts_go19::State &right) {
  return left.size == right.size && left.board == right.board &&
         left.to_play == right.to_play && left.passes == right.passes &&
         left.seen_boards == right.seen_boards &&
         left.previous_board == right.previous_board && left.ply == right.ply;
}

bool SameApplyResult(const ugts_go19::ApplyResult &left,
                     const ugts_go19::ApplyResult &right) {
  return SameState(left.state, right.state) && left.captured == right.captured &&
         left.self_captured == right.self_captured;
}

bool SameStats(const ugts_go19::cuda::VerifiedExpansionStats &left,
               const ugts_go19::cuda::VerifiedExpansionStats &right) {
  return left.states == right.states && left.point_slots == right.point_slots &&
         left.occupied == right.occupied && left.suicides == right.suicides &&
         left.local_candidates == right.local_candidates &&
         left.superko_rejections == right.superko_rejections &&
         left.globally_legal_children == right.globally_legal_children &&
         left.compared_child_words == right.compared_child_words;
}

bool SameBatch(const ugts_go19::cuda::VerifiedExpansionBatch &left,
               const ugts_go19::cuda::VerifiedExpansionBatch &right) {
  if (!SameStats(left.stats, right.stats) ||
      left.slots.size() != right.slots.size() ||
      left.legal_children.size() != right.legal_children.size()) {
    return false;
  }
  for (std::size_t index = 0; index < left.slots.size(); ++index) {
    const auto &a = left.slots[index];
    const auto &b = right.slots[index];
    if (a.parent_index != b.parent_index || a.move != b.move ||
        a.local_status != b.local_status || a.captured != b.captured ||
        a.self_captured != b.self_captured ||
        a.local_child_board != b.local_child_board ||
        a.superko_rejected != b.superko_rejected ||
        a.globally_legal != b.globally_legal) {
      return false;
    }
  }
  for (std::size_t index = 0; index < left.legal_children.size(); ++index) {
    const auto &a = left.legal_children[index];
    const auto &b = right.legal_children[index];
    if (a.parent_index != b.parent_index || a.move != b.move ||
        !SameApplyResult(a.result, b.result)) {
      return false;
    }
  }
  return true;
}

}  // namespace

int main(int argc, char **argv) {
  std::ios::sync_with_stdio(false);
  std::cout.imbue(std::locale::classic());
  std::cerr.imbue(std::locale::classic());
  try {
    std::string mode = "default";
    if (argc == 3 && std::string_view(argv[1]) == "--stream") {
      mode = argv[2];
    } else if (argc != 1) {
      throw std::invalid_argument("usage: evaluator [--stream default|nondefault]");
    }
    if (mode != "default" && mode != "nondefault") {
      throw std::invalid_argument("stream mode must be default or nondefault");
    }

    int device_count = 0;
    CheckCuda(cudaGetDeviceCount(&device_count), "cudaGetDeviceCount");
    if (device_count < 1) throw std::runtime_error("no CUDA device is available");
    CheckCuda(cudaSetDevice(0), "cudaSetDevice");
    cudaDeviceProp properties{};
    CheckCuda(cudaGetDeviceProperties(&properties, 0),
              "cudaGetDeviceProperties");

    const std::size_t negative_checks = RunNegativeChecks();
    InputBatch input = ReadBatch();
    std::vector<ugts_go19::State> states;
    states.reserve(input.requests.size());
    for (const auto &request : input.requests) states.push_back(request.state);

    cudaStream_t stream = nullptr;
    if (mode == "nondefault") {
      CheckCuda(cudaStreamCreateWithFlags(&stream, cudaStreamNonBlocking),
                "cudaStreamCreateWithFlags");
    }
    ugts_go19::cuda::VerifiedExpansionBatch first;
    ugts_go19::cuda::VerifiedExpansionBatch repeat;
    try {
      first = ugts_go19::cuda::VerifyCudaLocalPointTransitions(
          states, input.rules, stream);
      repeat = ugts_go19::cuda::VerifyCudaLocalPointTransitions(
          states, input.rules, stream);
      if (!SameBatch(first, repeat)) {
        throw std::runtime_error("repeat local-transition batch mismatch");
      }
      if (stream != nullptr) {
        CheckCuda(cudaStreamDestroy(stream), "cudaStreamDestroy");
        stream = nullptr;
      }
    } catch (...) {
      if (stream != nullptr) static_cast<void>(cudaStreamDestroy(stream));
      throw;
    }

    std::cout << kOutputProtocol << '\n';
    std::cout << "DEVICE " << properties.major << ' ' << properties.minor << ' '
              << HexBytes(properties.name) << '\n';
    std::cout << "MODE " << mode << '\n';
    const std::size_t points = static_cast<std::size_t>(
        input.rules.size * input.rules.size);
    for (std::size_t index = 0; index < first.slots.size(); ++index) {
      const auto &slot = first.slots[index];
      const std::size_t request_index = index / points;
      std::cout << "SLOT " << input.requests[request_index].id << ' '
                << slot.move << ' '
                << static_cast<unsigned int>(slot.local_status) << ' '
                << slot.captured << ' ' << slot.self_captured << ' '
                << (slot.superko_rejected ? 1 : 0) << ' '
                << (slot.globally_legal ? 1 : 0) << ' ';
      if (slot.local_child_board.empty()) {
        std::cout << '-';
      } else {
        std::cout << Hex(slot.local_child_board);
      }
      std::cout << '\n';
    }
    const auto &stats = first.stats;
    std::cout << "SUMMARY " << stats.states << ' ' << stats.point_slots << ' '
              << stats.occupied << ' ' << stats.suicides << ' '
              << stats.local_candidates << ' ' << stats.superko_rejections
              << ' ' << stats.globally_legal_children << ' '
              << stats.compared_child_words << ' ' << negative_checks
              << " 0\nEND\n";
    return 0;
  } catch (const std::exception &error) {
    std::cerr << "ugts_go_cuda_local_transition_eval: " << error.what() << '\n';
    return 1;
  }
}
