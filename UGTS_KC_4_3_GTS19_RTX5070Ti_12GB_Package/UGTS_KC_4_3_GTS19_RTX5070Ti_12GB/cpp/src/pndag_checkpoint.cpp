#include "ugts_go19/pndag_checkpoint.hpp"

#include "ugts_go19/sha256.hpp"

#include <algorithm>
#include <array>
#include <atomic>
#include <cerrno>
#include <climits>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <limits>
#include <map>
#include <optional>
#include <set>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#ifdef _WIN32
#define NOMINMAX
#include <windows.h>
#else
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>
#endif

namespace ugts_go19 {

struct NativePNDAGEncodedCheckpoint {
  std::string bytes;
  NativePNDAGCheckpointTip tip;
};

namespace {

constexpr std::string_view kCheckpointMagic =
    "UGTS-CPP-PNDAG-CHECKPOINT-v1";
constexpr std::string_view kRunMagic = "UGTS-CPP-PNDAG-RUN-v1";
constexpr std::string_view kAlgorithmId = "exact-pndag-bounded-v1";
constexpr std::string_view kSelectionId =
    "unresolved-pns-pn-dn-move-statebytes-v1";
constexpr std::string_view kMoveOrderId =
    "numeric-pass-minus-one-statebytes-v1";
constexpr std::string_view kStateFormat = "UGTS-GO-STATE-v1";
constexpr std::string_view kGraphFormat = "UGTS-CPP-PNDAG-GRAPH-v1";

constexpr std::uint8_t kLittleEndianTag = 1;
constexpr std::uint8_t kAreaScoringTag = 1;
constexpr std::uint8_t kPositionalSuperkoTag = 1;
constexpr std::uint8_t kNoSymmetryTag = 0;
constexpr std::size_t kSha256Bytes = 32;
constexpr std::size_t kFixedNodeBytesWithoutBoard =
    8U + 1U + 4U + 1U + 8U + 8U + 1U + 8U + 8U + 8U;
constexpr std::size_t kEdgeBytes = 4U + 8U;

[[noreturn]] void ThrowFilesystem(const std::string& message,
                                  const std::filesystem::path& path) {
  throw std::runtime_error(message + ": " + path.string());
}

void CheckedAdd(std::uint64_t& total, std::uint64_t value,
                 const char* label) {
  if (total > std::numeric_limits<std::uint64_t>::max() - value) {
    throw std::overflow_error(std::string(label) + " exceeds uint64");
  }
  total += value;
}

std::uint64_t CheckedMultiply(std::uint64_t count, std::uint64_t width,
                              const char* label) {
  if (width != 0 && count > std::numeric_limits<std::uint64_t>::max() / width) {
    throw std::overflow_error(std::string(label) + " exceeds uint64");
  }
  return count * width;
}

std::size_t CheckedSize(std::uint64_t value, const char* label) {
  if (value > static_cast<std::uint64_t>(
                  std::numeric_limits<std::size_t>::max())) {
    throw std::overflow_error(std::string(label) + " exceeds size_t");
  }
  return static_cast<std::size_t>(value);
}

std::size_t CheckedByteProduct(std::uint64_t count, std::size_t width,
                               const char* label) {
  if (width != 0 &&
      count > static_cast<std::uint64_t>(
                  std::numeric_limits<std::size_t>::max() / width)) {
    throw std::length_error(std::string(label) + " exceeds size_t");
  }
  return static_cast<std::size_t>(count) * width;
}

std::uint64_t SizeAsUint64(std::size_t value, const char* label) {
  if (value > static_cast<std::size_t>(
                  std::numeric_limits<std::uint64_t>::max())) {
    throw std::overflow_error(std::string(label) + " exceeds uint64");
  }
  return static_cast<std::uint64_t>(value);
}

void AppendU8(std::string& output, std::uint8_t value) {
  output.push_back(static_cast<char>(value));
}

void AppendU16(std::string& output, std::uint16_t value) {
  for (unsigned int shift = 0; shift < 16U; shift += 8U) {
    AppendU8(output, static_cast<std::uint8_t>((value >> shift) & 0xffU));
  }
}

void AppendU32(std::string& output, std::uint32_t value) {
  for (unsigned int shift = 0; shift < 32U; shift += 8U) {
    AppendU8(output, static_cast<std::uint8_t>((value >> shift) & 0xffU));
  }
}

void AppendU64(std::string& output, std::uint64_t value) {
  for (unsigned int shift = 0; shift < 64U; shift += 8U) {
    AppendU8(output, static_cast<std::uint8_t>((value >> shift) & 0xffU));
  }
}

std::uint32_t SignedBits(std::int32_t value) {
  if (value >= 0) return static_cast<std::uint32_t>(value);
  const auto magnitude = static_cast<std::uint32_t>(-(value + 1));
  return std::numeric_limits<std::uint32_t>::max() - magnitude;
}

std::uint64_t SignedBits(std::int64_t value) {
  if (value >= 0) return static_cast<std::uint64_t>(value);
  const auto magnitude = static_cast<std::uint64_t>(-(value + 1));
  return std::numeric_limits<std::uint64_t>::max() - magnitude;
}

void AppendI32(std::string& output, std::int32_t value) {
  AppendU32(output, SignedBits(value));
}

void AppendI64(std::string& output, std::int64_t value) {
  AppendU64(output, SignedBits(value));
}

void AppendMagic(std::string& output, std::string_view magic) {
  output.append(magic);
  AppendU8(output, 0);
}

void AppendLengthPrefixed(std::string& output, std::string_view value) {
  AppendU64(output, SizeAsUint64(value.size(), "string length"));
  output.append(value);
}

std::uint8_t HexNibble(char value) {
  if (value >= '0' && value <= '9') {
    return static_cast<std::uint8_t>(value - '0');
  }
  if (value >= 'a' && value <= 'f') {
    return static_cast<std::uint8_t>(value - 'a' + 10);
  }
  throw std::invalid_argument("SHA-256 must be lowercase hexadecimal text");
}

std::array<std::uint8_t, kSha256Bytes> DecodeSha256(
    const std::string& value) {
  if (value.size() != kSha256Bytes * 2U) {
    throw std::invalid_argument("SHA-256 must contain 64 lowercase hex digits");
  }
  std::array<std::uint8_t, kSha256Bytes> result{};
  for (std::size_t index = 0; index < result.size(); ++index) {
    const std::uint8_t high = HexNibble(value[index * 2U]);
    const std::uint8_t low = HexNibble(value[index * 2U + 1U]);
    result[index] = static_cast<std::uint8_t>((high << 4U) | low);
  }
  return result;
}

std::string EncodeSha256(const std::uint8_t* bytes) {
  constexpr char kHex[] = "0123456789abcdef";
  std::string result(kSha256Bytes * 2U, '0');
  for (std::size_t index = 0; index < kSha256Bytes; ++index) {
    result[index * 2U] = kHex[bytes[index] >> 4U];
    result[index * 2U + 1U] = kHex[bytes[index] & 0x0fU];
  }
  return result;
}

void AppendSha256(std::string& output, const std::string& value) {
  const auto bytes = DecodeSha256(value);
  output.append(reinterpret_cast<const char*>(bytes.data()), bytes.size());
}

class Reader {
 public:
  explicit Reader(std::string_view input) : input_(input) {}

  void RequireMagic(std::string_view expected) {
    const std::string_view actual = ReadBytes(expected.size() + 1U, "magic");
    if (actual.substr(0, expected.size()) != expected || actual.back() != '\0') {
      throw std::invalid_argument("native PNDAG checkpoint magic mismatch");
    }
  }

  std::uint8_t ReadU8(const char* label) {
    const auto bytes = ReadBytes(1, label);
    return static_cast<std::uint8_t>(
        static_cast<unsigned char>(bytes.front()));
  }

  std::uint16_t ReadU16(const char* label) {
    std::uint16_t value = 0;
    for (unsigned int shift = 0; shift < 16U; shift += 8U) {
      value |= static_cast<std::uint16_t>(ReadU8(label)) << shift;
    }
    return value;
  }

  std::uint32_t ReadU32(const char* label) {
    std::uint32_t value = 0;
    for (unsigned int shift = 0; shift < 32U; shift += 8U) {
      value |= static_cast<std::uint32_t>(ReadU8(label)) << shift;
    }
    return value;
  }

  std::uint64_t ReadU64(const char* label) {
    std::uint64_t value = 0;
    for (unsigned int shift = 0; shift < 64U; shift += 8U) {
      value |= static_cast<std::uint64_t>(ReadU8(label)) << shift;
    }
    return value;
  }

  std::int32_t ReadI32(const char* label) {
    const std::uint32_t bits = ReadU32(label);
    if (bits <= static_cast<std::uint32_t>(INT32_MAX)) {
      return static_cast<std::int32_t>(bits);
    }
    const std::uint32_t magnitude =
        std::numeric_limits<std::uint32_t>::max() - bits;
    return -static_cast<std::int32_t>(magnitude) - 1;
  }

  std::int64_t ReadI64(const char* label) {
    const std::uint64_t bits = ReadU64(label);
    if (bits <= static_cast<std::uint64_t>(INT64_MAX)) {
      return static_cast<std::int64_t>(bits);
    }
    const std::uint64_t magnitude =
        std::numeric_limits<std::uint64_t>::max() - bits;
    return -static_cast<std::int64_t>(magnitude) - 1;
  }

  std::string ReadSha256(const char* label) {
    const auto bytes = ReadBytes(kSha256Bytes, label);
    return EncodeSha256(reinterpret_cast<const std::uint8_t*>(bytes.data()));
  }

  std::string_view ReadBytes(std::size_t count, const char* label) {
    if (count > input_.size() - position_) {
      throw std::invalid_argument(std::string("truncated ") + label);
    }
    const std::string_view result = input_.substr(position_, count);
    position_ += count;
    return result;
  }

  void RequireEnd() const {
    if (position_ != input_.size()) {
      throw std::invalid_argument("native PNDAG checkpoint has trailing bytes");
    }
  }

  [[nodiscard]] std::size_t Remaining() const {
    return input_.size() - position_;
  }

 private:
  std::string_view input_;
  std::size_t position_ = 0;
};

std::vector<std::uint8_t> BytesToBoard(std::string_view bytes) {
  std::vector<std::uint8_t> board(bytes.size());
  for (std::size_t index = 0; index < bytes.size(); ++index) {
    board[index] = static_cast<std::uint8_t>(
        static_cast<unsigned char>(bytes[index]));
    if (board[index] != kEmpty && board[index] != kBlack &&
        board[index] != kWhite) {
      throw std::invalid_argument(
          "checkpoint board contains an invalid point value");
    }
  }
  return board;
}

void AppendBoard(std::string& output,
                 const std::vector<std::uint8_t>& board) {
  output.append(reinterpret_cast<const char*>(board.data()), board.size());
}

std::string RunPayload(const Rules& rules, std::int64_t threshold2,
                       const std::string& root_state_bytes) {
  std::string output;
  AppendMagic(output, kRunMagic);
  AppendLengthPrefixed(output, kAlgorithmId);
  AppendLengthPrefixed(output, kSelectionId);
  AppendLengthPrefixed(output, kMoveOrderId);
  AppendLengthPrefixed(output, kStateFormat);
  AppendLengthPrefixed(output, kGraphFormat);
  AppendU8(output, 64);
  AppendU8(output, kLittleEndianTag);
  AppendU64(output, kProofInfinity);
  AppendU32(output, static_cast<std::uint32_t>(rules.size));
  AppendI32(output, static_cast<std::int32_t>(rules.komi2));
  AppendU8(output, rules.allow_suicide ? 1U : 0U);
  AppendU8(output, kAreaScoringTag);
  AppendU8(output, kPositionalSuperkoTag);
  AppendU8(output, kNoSymmetryTag);
  AppendU32(output, static_cast<std::uint32_t>(rules.passes_to_end));
  AppendI64(output, threshold2);
  AppendLengthPrefixed(output, root_state_bytes);
  return output;
}

}  // namespace

ProofStatus NativePNDAGCheckpointCodec::RootStatus(
    const ProofNumberDAG& dag) {
  const auto& root = dag.nodes_.at(dag.root_id_);
  return ProofNumberDAG::Status(root.proof, root.disproof);
}

std::uint8_t ExpansionTag(NodeExpansion expansion) {
  switch (expansion) {
    case NodeExpansion::kUnexpanded:
      return 0;
    case NodeExpansion::kExpanded:
      return 1;
    case NodeExpansion::kTerminal:
      return 2;
  }
  throw std::invalid_argument("unknown node expansion marker");
}

NodeExpansion DecodeExpansion(std::uint8_t value) {
  switch (value) {
    case 0:
      return NodeExpansion::kUnexpanded;
    case 1:
      return NodeExpansion::kExpanded;
    case 2:
      return NodeExpansion::kTerminal;
    default:
      throw std::invalid_argument("unknown checkpoint node expansion marker");
  }
}

void NativePNDAGCheckpointCodec::ValidateStructureAndEdges(
    ProofNumberDAG& dag) {
  if (dag.nodes_.empty() || dag.root_id_ != 0) {
    throw std::invalid_argument("checkpoint graph root must be node zero");
  }

  std::map<std::string, std::size_t> exact_states;
  std::vector<std::set<std::size_t>> expected_parents(dag.nodes_.size());
  std::uint64_t expanded_count = 0;
  std::uint64_t edges = 0;

  for (std::size_t expected_id = 0; expected_id < dag.nodes_.size();
       ++expected_id) {
    auto& node = dag.nodes_[expected_id];
    if (node.node_id != expected_id) {
      throw std::invalid_argument(
          "checkpoint node identifiers are not contiguous");
    }
    if (node.state.ply != 0) {
      throw std::invalid_argument("checkpoint state contains campaign-only ply");
    }
    const std::string state_bytes = CanonicalStateJson(node.state, dag.rules_);
    if (state_bytes != node.state_bytes) {
      throw std::invalid_argument(
          "checkpoint node state bytes are not canonical");
    }
    if (!exact_states.emplace(state_bytes, expected_id).second) {
      throw std::invalid_argument("checkpoint contains duplicate exact states");
    }
    if (node.rank != dag.Rank(node.state)) {
      throw std::invalid_argument("checkpoint node semantic rank mismatch");
    }
    const bool terminal = node.state.Terminal(dag.rules_);
    if (terminal != (node.expansion == NodeExpansion::kTerminal)) {
      throw std::invalid_argument("checkpoint terminal marker mismatch");
    }
    if (node.expansion != NodeExpansion::kExpanded) {
      if (!node.children.empty()) {
        throw std::invalid_argument(
            "only expanded checkpoint nodes may contain edges");
      }
      continue;
    }

    CheckedAdd(expanded_count, 1, "expanded node count");
    if (node.children.empty()) {
      throw std::invalid_argument("expanded checkpoint node has no edges");
    }
    int previous_move = std::numeric_limits<int>::min();
    bool first_move = true;
    for (const auto& edge : node.children) {
      if (!first_move && edge.first <= previous_move) {
        throw std::invalid_argument(
            "checkpoint child moves are not strictly ordered");
      }
      first_move = false;
      previous_move = edge.first;
      if (edge.second >= dag.nodes_.size()) {
        throw std::invalid_argument("checkpoint edge references unknown node");
      }
      const auto& child = dag.nodes_[edge.second];
      if (child.rank <= node.rank) {
        throw std::invalid_argument("checkpoint edge violates PSK rank order");
      }
      expected_parents[edge.second].insert(expected_id);
      CheckedAdd(edges, 1, "edge count");
    }

    auto expected_moves = LegalMoves(node.state, dag.rules_, true);
    std::sort(expected_moves.begin(), expected_moves.end());
    if (expected_moves.size() != node.children.size()) {
      throw std::invalid_argument(
          "expanded checkpoint node omits or adds legal edges");
    }
    for (std::size_t index = 0; index < expected_moves.size(); ++index) {
      const auto& actual = node.children[index];
      if (actual.first != expected_moves[index]) {
        throw std::invalid_argument(
            "expanded checkpoint edge fails exact legal regeneration");
      }
      State expected_state =
          ApplyMove(node.state, expected_moves[index], dag.rules_).state;
      std::sort(expected_state.seen_boards.begin(),
                expected_state.seen_boards.end());
      expected_state.ply = 0;
      if (dag.nodes_[actual.second].state_bytes !=
          CanonicalStateJson(expected_state, dag.rules_)) {
        throw std::invalid_argument(
            "expanded checkpoint edge fails exact legal regeneration");
      }
    }
  }

  if (expanded_count != dag.committed_expansions_) {
    throw std::invalid_argument(
        "checkpoint committed expansion count mismatch");
  }
  if (edges != dag.edge_count()) {
    throw std::invalid_argument("checkpoint edge count mismatch");
  }
  for (std::size_t node_id = 0; node_id < dag.nodes_.size(); ++node_id) {
    if (dag.nodes_[node_id].parents != expected_parents[node_id]) {
      throw std::invalid_argument("checkpoint reverse-parent index mismatch");
    }
  }
  if (dag.exact_index_ != exact_states) {
    throw std::invalid_argument("checkpoint exact-state index mismatch");
  }

  std::vector<bool> reachable(dag.nodes_.size(), false);
  std::vector<std::size_t> pending{dag.root_id_};
  while (!pending.empty()) {
    const std::size_t node_id = pending.back();
    pending.pop_back();
    if (reachable[node_id]) continue;
    reachable[node_id] = true;
    for (const auto& edge : dag.nodes_[node_id].children) {
      pending.push_back(edge.second);
    }
  }
  if (std::find(reachable.begin(), reachable.end(), false) != reachable.end()) {
    throw std::invalid_argument(
        "checkpoint contains nodes unreachable from the root");
  }
}

void NativePNDAGCheckpointCodec::ValidateForSave(ProofNumberDAG& dag) {
  ValidateStructureAndEdges(dag);
  dag.RecomputeAll();
  const auto& root = dag.nodes_.at(dag.root_id_);
  static_cast<void>(ProofNumberDAG::Status(root.proof, root.disproof));
}

void NativePNDAGCheckpointCodec::ValidateExtension(
    const ProofNumberDAG& previous, const ProofNumberDAG& newer) {
  if (previous.rules_.size != newer.rules_.size ||
      previous.rules_.komi2 != newer.rules_.komi2 ||
      previous.rules_.allow_suicide != newer.rules_.allow_suicide ||
      previous.rules_.passes_to_end != newer.rules_.passes_to_end ||
      previous.threshold2_ != newer.threshold2_ ||
      previous.root_id_ != newer.root_id_) {
    throw std::invalid_argument("checkpoint extension changed the exact run");
  }
  if (newer.committed_expansions_ <= previous.committed_expansions_) {
    throw std::invalid_argument(
        "checkpoint extension did not increase committed work");
  }
  if (RootStatus(previous) != ProofStatus::kUnknown) {
    throw std::invalid_argument("a solved checkpoint is a final generation");
  }
  if (newer.nodes_.size() < previous.nodes_.size()) {
    throw std::invalid_argument("checkpoint extension dropped graph nodes");
  }
  for (std::size_t node_id = 0; node_id < previous.nodes_.size(); ++node_id) {
    const auto& old_node = previous.nodes_[node_id];
    const auto& new_node = newer.nodes_[node_id];
    if (old_node.node_id != new_node.node_id ||
        old_node.state_bytes != new_node.state_bytes ||
        old_node.rank != new_node.rank) {
      throw std::invalid_argument(
          "checkpoint extension changed an existing exact node");
    }
    if (old_node.expansion == NodeExpansion::kExpanded ||
        old_node.expansion == NodeExpansion::kTerminal) {
      if (old_node.expansion != new_node.expansion ||
          old_node.children != new_node.children) {
        throw std::invalid_argument(
            "checkpoint extension changed committed node edges");
      }
    } else if (new_node.expansion != NodeExpansion::kUnexpanded &&
               new_node.expansion != NodeExpansion::kExpanded) {
      throw std::invalid_argument(
          "checkpoint extension changed an open node incompatibly");
    }
  }
}

std::uint64_t NativePNDAGCheckpointCodec::TotalHistoryMembers(
    const ProofNumberDAG& dag) {
  std::uint64_t total = 0;
  for (const auto& node : dag.nodes_) {
    CheckedAdd(total, SizeAsUint64(node.state.seen_boards.size(),
                                   "history member count"),
               "total history member count");
  }
  return total;
}

NativePNDAGEncodedCheckpoint NativePNDAGCheckpointCodec::EncodeCheckpoint(
    ProofNumberDAG& dag, std::uint64_t generation,
    const std::optional<NativePNDAGCheckpointTip>& previous_tip,
    const NativePNDAGCheckpointLimits& limits) {
  ValidateForSave(dag);
  if (generation == 0) {
    throw std::invalid_argument("checkpoint generation must be positive");
  }
  if ((generation == 1) != !previous_tip.has_value()) {
    throw std::invalid_argument(
        "checkpoint generation/predecessor relationship is invalid");
  }

  const std::uint64_t node_count = dag.node_count();
  const std::uint64_t edge_count = dag.edge_count();
  const std::uint64_t history_count = TotalHistoryMembers(dag);
  if (node_count > limits.max_nodes || edge_count > limits.max_edges ||
      history_count > limits.max_history_members) {
    throw std::length_error("native PNDAG checkpoint exceeds configured limits");
  }

  const std::uint64_t points = static_cast<std::uint64_t>(
      dag.rules_.size * dag.rules_.size);
  std::uint64_t previous_board_count = 0;
  for (const auto& node : dag.nodes_) {
    if (node.state.previous_board.has_value()) {
      CheckedAdd(previous_board_count, 1, "previous-board count");
    }
  }
  std::uint64_t predicted_file_bytes =
      SizeAsUint64(kCheckpointMagic.size() + 1U, "checkpoint magic length");
  CheckedAdd(predicted_file_bytes,
             5U * 4U + 8U + 8U + 1U,
             "checkpoint header length");
  if (previous_tip.has_value()) {
    CheckedAdd(predicted_file_bytes, kSha256Bytes,
               "checkpoint predecessor length");
  }
  CheckedAdd(predicted_file_bytes, 5U * 8U + 3U * kSha256Bytes,
             "checkpoint header length");
  CheckedAdd(predicted_file_bytes,
             CheckedMultiply(node_count,
                             kFixedNodeBytesWithoutBoard + points,
                             "checkpoint node bytes"),
             "checkpoint byte length");
  CheckedAdd(predicted_file_bytes,
             CheckedMultiply(previous_board_count, points,
                             "checkpoint previous-board bytes"),
             "checkpoint byte length");
  CheckedAdd(predicted_file_bytes,
             CheckedMultiply(history_count, points,
                             "checkpoint history bytes"),
             "checkpoint byte length");
  CheckedAdd(predicted_file_bytes,
             CheckedMultiply(edge_count, kEdgeBytes,
                             "checkpoint edge bytes"),
             "checkpoint byte length");
  CheckedAdd(predicted_file_bytes, kSha256Bytes, "checkpoint footer length");
  if (predicted_file_bytes > limits.max_file_bytes) {
    throw std::length_error("native PNDAG checkpoint exceeds file-byte limit");
  }

  const auto& root = dag.nodes_.at(dag.root_id_);
  const std::string root_object_id = Sha256Hex(root.state_bytes);
  const std::string run_sha256 =
      Sha256Hex(RunPayload(dag.rules_, dag.threshold2_, root.state_bytes));
  const std::string graph_sha256 = dag.GraphSha256();

  if (previous_tip.has_value()) {
    const auto& previous = *previous_tip;
    static_cast<void>(DecodeSha256(previous.checkpoint_file_sha256));
    if (previous.generation == std::numeric_limits<std::uint64_t>::max() ||
        generation != previous.generation + 1U) {
      throw std::overflow_error("checkpoint generation counter exhausted");
    }
    if (previous.run_sha256 != run_sha256 ||
        previous.root_state_object_id != root_object_id) {
      throw std::invalid_argument("checkpoint continuation changed the exact run");
    }
    if (previous.status != ProofStatus::kUnknown) {
      throw std::invalid_argument("a solved checkpoint is a final generation");
    }
    if (dag.committed_expansions_ <= previous.committed_expansions) {
      throw std::invalid_argument(
          "checkpoint continuation did not increase committed work");
    }
  }

  std::string payload;
  payload.reserve(CheckedSize(predicted_file_bytes - kSha256Bytes,
                              "checkpoint payload length"));
  AppendMagic(payload, kCheckpointMagic);
  AppendU8(payload, kLittleEndianTag);
  AppendU8(payload, 0);  // flags
  AppendU16(payload, 0);  // reserved
  AppendU32(payload, static_cast<std::uint32_t>(dag.rules_.size));
  AppendI32(payload, static_cast<std::int32_t>(dag.rules_.komi2));
  AppendU8(payload, dag.rules_.allow_suicide ? 1U : 0U);
  AppendU8(payload, kAreaScoringTag);
  AppendU8(payload, kPositionalSuperkoTag);
  AppendU8(payload, kNoSymmetryTag);
  AppendU32(payload, static_cast<std::uint32_t>(dag.rules_.passes_to_end));
  AppendI64(payload, dag.threshold2_);
  AppendU64(payload, generation);
  AppendU8(payload, previous_tip.has_value() ? 1U : 0U);
  if (previous_tip.has_value()) {
    AppendSha256(payload, previous_tip->checkpoint_file_sha256);
  }
  AppendU64(payload, dag.committed_expansions_);
  AppendU64(payload, SizeAsUint64(dag.root_id_, "root ID"));
  AppendU64(payload, node_count);
  AppendU64(payload, edge_count);
  AppendU64(payload, history_count);
  AppendSha256(payload, run_sha256);
  AppendSha256(payload, root_object_id);
  AppendSha256(payload, graph_sha256);

  const std::size_t point_count = CheckedSize(points, "board point count");
  for (const auto& node : dag.nodes_) {
    AppendU64(payload, SizeAsUint64(node.node_id, "node ID"));
    if (node.state.board.size() != point_count) {
      throw std::invalid_argument("checkpoint board length changed during save");
    }
    AppendBoard(payload, node.state.board);
    AppendU8(payload, node.state.to_play);
    AppendU32(payload, static_cast<std::uint32_t>(node.state.passes));
    AppendU8(payload, node.state.previous_board.has_value() ? 1U : 0U);
    if (node.state.previous_board.has_value()) {
      AppendBoard(payload, *node.state.previous_board);
    }
    auto canonical_seen = node.state.seen_boards;
    std::sort(canonical_seen.begin(), canonical_seen.end());
    AppendU64(payload, SizeAsUint64(canonical_seen.size(), "history size"));
    for (const auto& seen : canonical_seen) AppendBoard(payload, seen);
    AppendU64(payload, node.rank);
    AppendU8(payload, ExpansionTag(node.expansion));
    AppendU64(payload, node.proof);
    AppendU64(payload, node.disproof);
    AppendU64(payload, SizeAsUint64(node.children.size(), "child count"));
    for (const auto& edge : node.children) {
      if (edge.first < INT32_MIN || edge.first > INT32_MAX) {
        throw std::overflow_error("edge move exceeds int32");
      }
      AppendI32(payload, static_cast<std::int32_t>(edge.first));
      AppendU64(payload, SizeAsUint64(edge.second, "child ID"));
    }
  }

  const std::string payload_sha256 = Sha256Hex(payload);
  std::string file_bytes = std::move(payload);
  AppendSha256(file_bytes, payload_sha256);
  if (SizeAsUint64(file_bytes.size(), "checkpoint byte length") !=
      predicted_file_bytes) {
    throw std::logic_error("native checkpoint encoded length prediction failed");
  }
  if (SizeAsUint64(file_bytes.size(), "checkpoint byte length") >
      limits.max_file_bytes) {
    throw std::length_error("native PNDAG checkpoint exceeds file-byte limit");
  }
  const std::string file_sha256 = Sha256Hex(file_bytes);

  NativePNDAGCheckpointTip tip;
  tip.generation = generation;
  if (previous_tip.has_value()) {
    tip.previous_checkpoint_file_sha256 =
        previous_tip->checkpoint_file_sha256;
  }
  tip.checkpoint_file_sha256 = file_sha256;
  tip.checkpoint_payload_sha256 = payload_sha256;
  tip.run_sha256 = run_sha256;
  tip.root_state_object_id = root_object_id;
  tip.graph_sha256 = graph_sha256;
  tip.committed_expansions = dag.committed_expansions_;
  tip.node_count = node_count;
  tip.edge_count = edge_count;
  tip.byte_length = SizeAsUint64(file_bytes.size(), "checkpoint byte length");
  tip.status = RootStatus(dag);
  return NativePNDAGEncodedCheckpoint{std::move(file_bytes), std::move(tip)};
}

namespace {

#ifdef _WIN32
std::wstring ExtendedWindowsPath(const std::filesystem::path& path);
#endif

std::string ReadFileBytes(const std::filesystem::path& path,
                          std::uint64_t maximum_bytes) {
#ifdef _WIN32
  const std::filesystem::path io_path(ExtendedWindowsPath(path));
#else
  const std::filesystem::path& io_path = path;
#endif
  std::error_code error;
  const auto status = std::filesystem::status(io_path, error);
  if (error || !std::filesystem::is_regular_file(status)) {
    ThrowFilesystem("checkpoint is missing or is not a regular file", path);
  }
  const std::uintmax_t size = std::filesystem::file_size(io_path, error);
  if (error) ThrowFilesystem("cannot inspect checkpoint size", path);
  if (size > maximum_bytes ||
      size > static_cast<std::uintmax_t>(
                 std::numeric_limits<std::size_t>::max()) ||
      size > static_cast<std::uintmax_t>(
                 std::numeric_limits<std::streamsize>::max())) {
    throw std::length_error("checkpoint exceeds configured file-byte limit");
  }
  std::ifstream input(io_path, std::ios::binary);
  if (!input) ThrowFilesystem("cannot open checkpoint", path);
  std::string bytes(static_cast<std::size_t>(size), '\0');
  if (!bytes.empty()) {
    input.read(bytes.data(), static_cast<std::streamsize>(bytes.size()));
  }
  if (!input || input.peek() != std::char_traits<char>::eof()) {
    ThrowFilesystem("cannot read checkpoint exactly", path);
  }
  return bytes;
}

void WriteFileBytes(const std::filesystem::path& path,
                    const std::string& bytes) {
  std::ofstream output(path, std::ios::binary | std::ios::trunc);
  if (!output) ThrowFilesystem("cannot create checkpoint temporary", path);
  output.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
  output.flush();
  if (!output) ThrowFilesystem("cannot write checkpoint temporary", path);
  output.close();
  if (!output) ThrowFilesystem("cannot close checkpoint temporary", path);
}

#ifdef _WIN32
std::wstring ExtendedWindowsPath(const std::filesystem::path& path) {
  std::wstring native = std::filesystem::absolute(path).native();
  if (native.rfind(L"\\\\?\\", 0) == 0) return native;
  if (native.rfind(L"\\\\", 0) == 0) {
    return L"\\\\?\\UNC\\" + native.substr(2);
  }
  return L"\\\\?\\" + native;
}
#endif

void FlushFile(const std::filesystem::path& path) {
#ifdef _WIN32
  const std::wstring extended = ExtendedWindowsPath(path);
  HANDLE handle = CreateFileW(extended.c_str(), GENERIC_WRITE,
                              FILE_SHARE_READ | FILE_SHARE_WRITE |
                                  FILE_SHARE_DELETE,
                              nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL,
                              nullptr);
  if (handle == INVALID_HANDLE_VALUE) {
    ThrowFilesystem("cannot open checkpoint for durability flush", path);
  }
  const BOOL flushed = FlushFileBuffers(handle);
  const DWORD flush_error = flushed ? ERROR_SUCCESS : GetLastError();
  CloseHandle(handle);
  if (!flushed) {
    throw std::runtime_error("cannot durably flush checkpoint: Windows error " +
                             std::to_string(flush_error));
  }
#else
  const int descriptor = open(path.c_str(), O_RDONLY | O_CLOEXEC);
  if (descriptor < 0) ThrowFilesystem("cannot open checkpoint for fsync", path);
  const int result = fsync(descriptor);
  const int saved_errno = errno;
  close(descriptor);
  if (result != 0) {
    throw std::runtime_error("cannot fsync checkpoint: errno " +
                             std::to_string(saved_errno));
  }
#endif
}

void FlushDirectory(const std::filesystem::path& path) {
#ifdef _WIN32
  // Same-volume MoveFileExW with MOVEFILE_WRITE_THROUGH is the available
  // portable Windows publication barrier. Directory FlushFileBuffers support
  // is filesystem-dependent and is not claimed by this bounded slice.
  static_cast<void>(path);
#else
  const int descriptor =
      open(path.c_str(), O_RDONLY | O_CLOEXEC | O_DIRECTORY);
  if (descriptor < 0) ThrowFilesystem("cannot open checkpoint directory", path);
  const int result = fsync(descriptor);
  const int saved_errno = errno;
  close(descriptor);
  if (result != 0) {
    throw std::runtime_error("cannot fsync checkpoint directory: errno " +
                             std::to_string(saved_errno));
  }
#endif
}

std::uint64_t ProcessId() {
#ifdef _WIN32
  return static_cast<std::uint64_t>(GetCurrentProcessId());
#else
  return static_cast<std::uint64_t>(getpid());
#endif
}

std::filesystem::path NewTemporaryPath(
    const std::filesystem::path& directory) {
  static std::atomic<std::uint64_t> counter{0};
  for (int attempt = 0; attempt < 1000; ++attempt) {
    const auto serial = counter.fetch_add(1, std::memory_order_relaxed);
    const auto path = directory /
                      (".checkpoint.tmp-" + std::to_string(ProcessId()) + "-" +
                       std::to_string(serial));
    if (!std::filesystem::exists(path)) return path;
  }
  throw std::runtime_error("cannot allocate a unique checkpoint temporary");
}

bool ExactFileEquals(const std::filesystem::path& path,
                     const std::string& expected) {
  try {
    return ReadFileBytes(path, SizeAsUint64(expected.size(), "file size")) ==
           expected;
  } catch (const std::length_error&) {
    return false;
  }
}

void InstallImmutable(const std::filesystem::path& temporary,
                      const std::filesystem::path& destination,
                      const std::string& exact_bytes) {
#ifdef _WIN32
  const std::wstring extended_temporary = ExtendedWindowsPath(temporary);
  const std::wstring extended_destination = ExtendedWindowsPath(destination);
  if (!MoveFileExW(extended_temporary.c_str(), extended_destination.c_str(),
                   MOVEFILE_WRITE_THROUGH)) {
    const DWORD move_error = GetLastError();
    if (!ExactFileEquals(destination, exact_bytes)) {
      throw std::runtime_error(
          "cannot install immutable checkpoint: Windows error " +
          std::to_string(move_error));
    }
    std::error_code remove_error;
    std::filesystem::remove(temporary, remove_error);
  }
#else
  if (link(temporary.c_str(), destination.c_str()) != 0) {
    const int link_error = errno;
    if (link_error != EEXIST || !ExactFileEquals(destination, exact_bytes)) {
      throw std::runtime_error("cannot install immutable checkpoint: errno " +
                               std::to_string(link_error));
    }
  }
  std::error_code remove_error;
  std::filesystem::remove(temporary, remove_error);
#endif
}

}  // namespace

NativePNDAGLoadedCheckpoint NativePNDAGCheckpointCodec::DecodeCheckpoint(
    std::string bytes, const std::filesystem::path& path,
    const std::string& expected_file_sha256, const Rules& expected_rules,
    std::int64_t expected_threshold2, const State& expected_root_state,
    const NativePNDAGCheckpointLimits& limits) {
  static_cast<void>(DecodeSha256(expected_file_sha256));
  if (SizeAsUint64(bytes.size(), "checkpoint byte length") >
      limits.max_file_bytes) {
    throw std::length_error("checkpoint exceeds configured file-byte limit");
  }
  if (bytes.size() < kCheckpointMagic.size() + 1U + kSha256Bytes) {
    throw std::invalid_argument("native PNDAG checkpoint is truncated");
  }
  if (Sha256Hex(bytes) != expected_file_sha256) {
    throw std::invalid_argument(
        "native PNDAG checkpoint does not match the external file hash pin");
  }
  const std::size_t payload_size = bytes.size() - kSha256Bytes;
  const std::string_view payload(bytes.data(), payload_size);
  const std::string footer_sha256 = EncodeSha256(
      reinterpret_cast<const std::uint8_t*>(bytes.data() + payload_size));
  if (Sha256Hex(payload) != footer_sha256) {
    throw std::invalid_argument("native PNDAG checkpoint payload hash mismatch");
  }

  Reader reader(payload);
  reader.RequireMagic(kCheckpointMagic);
  if (reader.ReadU8("endianness") != kLittleEndianTag ||
      reader.ReadU8("flags") != 0 || reader.ReadU16("reserved fields") != 0) {
    throw std::invalid_argument(
        "checkpoint encoding tags or reserved fields are unsupported");
  }
  const std::uint32_t size = reader.ReadU32("board size");
  const std::int32_t komi2 = reader.ReadI32("komi2");
  const std::uint8_t allow_suicide = reader.ReadU8("suicide rule");
  const std::uint8_t scoring = reader.ReadU8("scoring rule");
  const std::uint8_t superko = reader.ReadU8("superko rule");
  const std::uint8_t symmetry = reader.ReadU8("symmetry mode");
  const std::uint32_t passes_to_end = reader.ReadU32("passes to end");
  const std::int64_t threshold2 = reader.ReadI64("threshold2");
  if (size != static_cast<std::uint32_t>(expected_rules.size) ||
      komi2 != expected_rules.komi2 ||
      allow_suicide != (expected_rules.allow_suicide ? 1U : 0U) ||
      scoring != kAreaScoringTag || superko != kPositionalSuperkoTag ||
      symmetry != kNoSymmetryTag ||
      passes_to_end !=
          static_cast<std::uint32_t>(expected_rules.passes_to_end) ||
      threshold2 != expected_threshold2) {
    throw std::invalid_argument(
        "checkpoint does not match the exact expected run parameters");
  }

  const std::uint64_t generation = reader.ReadU64("generation");
  if (generation == 0) {
    throw std::invalid_argument("checkpoint generation must be positive");
  }
  if (generation > limits.max_lineage_generations) {
    throw std::length_error(
        "checkpoint generation exceeds the configured lineage limit");
  }
  const std::uint8_t previous_present = reader.ReadU8("predecessor marker");
  if (previous_present > 1) {
    throw std::invalid_argument("checkpoint predecessor marker is noncanonical");
  }
  std::optional<std::string> previous_sha256;
  if (previous_present != 0) {
    previous_sha256 = reader.ReadSha256("previous checkpoint hash");
  }
  if ((generation == 1) != !previous_sha256.has_value()) {
    throw std::invalid_argument(
        "checkpoint generation/predecessor relationship is invalid");
  }

  const std::uint64_t committed_expansions =
      reader.ReadU64("committed expansions");
  const std::uint64_t root_id = reader.ReadU64("root ID");
  const std::uint64_t node_count = reader.ReadU64("node count");
  const std::uint64_t edge_count = reader.ReadU64("edge count");
  const std::uint64_t history_count =
      reader.ReadU64("total history member count");
  if (root_id != 0 || node_count == 0) {
    throw std::invalid_argument("checkpoint root must be node zero");
  }
  if (node_count > limits.max_nodes || edge_count > limits.max_edges ||
      history_count > limits.max_history_members) {
    throw std::length_error("checkpoint exceeds configured decode limits");
  }
  const std::size_t decoded_node_count = CheckedSize(node_count, "node count");
  static_cast<void>(CheckedSize(edge_count, "edge count"));
  static_cast<void>(CheckedSize(history_count, "history member count"));

  const std::string stored_run_sha256 = reader.ReadSha256("run hash");
  const std::string stored_root_object_id =
      reader.ReadSha256("root object ID");
  const std::string stored_graph_sha256 = reader.ReadSha256("graph hash");

  const std::string expected_root_bytes =
      CanonicalStateJson(expected_root_state, expected_rules);
  const std::string calculated_run_sha256 = Sha256Hex(
      RunPayload(expected_rules, expected_threshold2, expected_root_bytes));
  if (stored_run_sha256 != calculated_run_sha256) {
    throw std::invalid_argument("checkpoint exact run hash mismatch");
  }

  const std::size_t points =
      static_cast<std::size_t>(expected_rules.size * expected_rules.size);
  // A node with no previous board, history members, or edges still needs this
  // fixed framing. Reject impossible declarations before any reserve based on
  // untrusted counts, so a tiny file cannot amplify into a large allocation.
  if (points > std::numeric_limits<std::size_t>::max() -
                   kFixedNodeBytesWithoutBoard) {
    throw std::length_error("checkpoint minimum node width exceeds size_t");
  }
  const std::size_t minimum_node_bytes = CheckedByteProduct(
      node_count, points + kFixedNodeBytesWithoutBoard, "minimum node bytes");
  const std::size_t minimum_history_bytes = CheckedByteProduct(
      history_count, points, "minimum history bytes");
  const std::size_t minimum_edge_bytes =
      CheckedByteProduct(edge_count, kEdgeBytes, "minimum edge bytes");
  if (minimum_node_bytes > reader.Remaining() ||
      minimum_history_bytes > reader.Remaining() - minimum_node_bytes ||
      minimum_edge_bytes >
          reader.Remaining() - minimum_node_bytes - minimum_history_bytes) {
    throw std::invalid_argument(
        "checkpoint declared records cannot fit in the remaining payload");
  }

  ProofNumberDAG dag(expected_rules, expected_threshold2, expected_root_state);
  dag.nodes_.clear();
  dag.exact_index_.clear();
  dag.root_id_ = 0;
  dag.committed_expansions_ = committed_expansions;

  std::uint64_t actual_edges = 0;
  std::uint64_t actual_histories = 0;
  std::vector<std::pair<std::uint64_t, std::uint64_t>> saved_caches;

  for (std::size_t expected_id = 0; expected_id < decoded_node_count;
       ++expected_id) {
    const std::uint64_t wire_id = reader.ReadU64("node ID");
    if (wire_id != SizeAsUint64(expected_id, "node ID")) {
      throw std::invalid_argument(
          "checkpoint node identifiers are not contiguous");
    }
    State state;
    state.size = expected_rules.size;
    state.board = BytesToBoard(reader.ReadBytes(points, "node board"));
    state.to_play = reader.ReadU8("player to move");
    if (state.to_play != kBlack && state.to_play != kWhite) {
      throw std::invalid_argument("checkpoint player to move is invalid");
    }
    const std::uint32_t passes = reader.ReadU32("pass count");
    if (passes > static_cast<std::uint32_t>(INT_MAX) ||
        passes > static_cast<std::uint32_t>(expected_rules.passes_to_end)) {
      throw std::invalid_argument("checkpoint pass count is invalid");
    }
    state.passes = static_cast<int>(passes);
    const std::uint8_t previous_marker =
        reader.ReadU8("previous-board marker");
    if (previous_marker > 1) {
      throw std::invalid_argument(
          "checkpoint previous-board marker is noncanonical");
    }
    if (previous_marker != 0) {
      state.previous_board =
          BytesToBoard(reader.ReadBytes(points, "previous board"));
    }
    const std::uint64_t seen_count = reader.ReadU64("history size");
    CheckedAdd(actual_histories, seen_count, "history member count");
    if (actual_histories > history_count ||
        actual_histories > limits.max_history_members) {
      throw std::length_error("checkpoint history count exceeds declared limit");
    }
    const std::size_t decoded_seen = CheckedSize(seen_count, "history size");
    const std::size_t history_bytes =
        CheckedByteProduct(seen_count, points, "history board bytes");
    if (history_bytes > reader.Remaining()) {
      throw std::invalid_argument(
          "checkpoint history boards cannot fit in the remaining payload");
    }
    for (std::size_t index = 0; index < decoded_seen; ++index) {
      state.seen_boards.push_back(
          BytesToBoard(reader.ReadBytes(points, "history board")));
      if (index > 0 &&
          !(state.seen_boards[index - 1] < state.seen_boards[index])) {
        throw std::invalid_argument(
            "checkpoint history boards are not strictly ordered");
      }
    }
    state.ply = 0;
    const std::string state_bytes = CanonicalStateJson(state, expected_rules);
    if (expected_id == 0 && state_bytes != expected_root_bytes) {
      throw std::invalid_argument(
          "checkpoint root does not match the exact expected target");
    }
    if (dag.exact_index_.find(state_bytes) != dag.exact_index_.end()) {
      throw std::invalid_argument("checkpoint contains duplicate exact states");
    }

    const std::uint64_t rank = reader.ReadU64("node rank");
    if (rank != dag.Rank(state)) {
      throw std::invalid_argument("checkpoint node semantic rank mismatch");
    }
    const NodeExpansion expansion =
        DecodeExpansion(reader.ReadU8("node expansion"));
    if (state.Terminal(expected_rules) !=
        (expansion == NodeExpansion::kTerminal)) {
      throw std::invalid_argument("checkpoint terminal marker mismatch");
    }
    const std::uint64_t proof = reader.ReadU64("cached proof");
    const std::uint64_t disproof = reader.ReadU64("cached disproof");
    if (proof == 0 && disproof == 0) {
      throw std::invalid_argument(
          "checkpoint proof and disproof cannot both be zero");
    }
    const std::uint64_t child_count = reader.ReadU64("child count");
    CheckedAdd(actual_edges, child_count, "edge count");
    if (actual_edges > edge_count || actual_edges > limits.max_edges) {
      throw std::length_error("checkpoint edge count exceeds declared limit");
    }
    if (child_count > static_cast<std::uint64_t>(points + 1U)) {
      throw std::invalid_argument("checkpoint node has too many child moves");
    }
    const std::size_t decoded_children = CheckedSize(child_count, "child count");
    if (decoded_children > reader.Remaining() / kEdgeBytes) {
      throw std::invalid_argument(
          "checkpoint edges cannot fit in the remaining payload");
    }
    std::vector<std::pair<int, std::size_t>> children;
    children.reserve(decoded_children);
    std::int32_t previous_move = INT32_MIN;
    bool first_move = true;
    for (std::size_t index = 0; index < decoded_children; ++index) {
      const std::int32_t move = reader.ReadI32("edge move");
      const std::uint64_t child_id = reader.ReadU64("edge child ID");
      if (move < kPass || move >= static_cast<std::int32_t>(points) ||
          (!first_move && move <= previous_move)) {
        throw std::invalid_argument(
            "checkpoint edge moves are invalid or noncanonical");
      }
      first_move = false;
      previous_move = move;
      if (child_id >= node_count) {
        throw std::invalid_argument("checkpoint edge references unknown node");
      }
      children.emplace_back(static_cast<int>(move),
                            CheckedSize(child_id, "edge child ID"));
    }
    if (expansion == NodeExpansion::kExpanded) {
      if (children.empty()) {
        throw std::invalid_argument("expanded checkpoint node has no edges");
      }
    } else if (!children.empty()) {
      throw std::invalid_argument(
          "only expanded checkpoint nodes may contain edges");
    }

    ProofNumberDAG::Node node;
    node.node_id = expected_id;
    node.state_bytes = state_bytes;
    node.state = std::move(state);
    node.rank = rank;
    node.expansion = expansion;
    node.children = std::move(children);
    node.proof = proof;
    node.disproof = disproof;
    dag.nodes_.push_back(std::move(node));
    dag.exact_index_.emplace(state_bytes, expected_id);
    saved_caches.emplace_back(proof, disproof);
  }
  reader.RequireEnd();
  if (actual_edges != edge_count || actual_histories != history_count) {
    throw std::invalid_argument("checkpoint aggregate counts mismatch");
  }
  for (const auto& node : dag.nodes_) {
    for (const auto& edge : node.children) {
      dag.nodes_[edge.second].parents.insert(node.node_id);
    }
  }

  ValidateStructureAndEdges(dag);
  dag.RecomputeAll();
  for (std::size_t node_id = 0; node_id < dag.nodes_.size(); ++node_id) {
    if (saved_caches[node_id] !=
        std::make_pair(dag.nodes_[node_id].proof,
                       dag.nodes_[node_id].disproof)) {
      throw std::invalid_argument(
          "checkpoint proof caches fail independent recomputation");
    }
  }
  if (stored_root_object_id != Sha256Hex(dag.nodes_[0].state_bytes) ||
      stored_root_object_id != Sha256Hex(expected_root_bytes)) {
    throw std::invalid_argument("checkpoint root state object ID mismatch");
  }
  const std::string calculated_graph_sha256 = dag.GraphSha256();
  if (stored_graph_sha256 != calculated_graph_sha256) {
    throw std::invalid_argument("checkpoint graph hash mismatch");
  }

  NativePNDAGCheckpointTip tip;
  tip.generation = generation;
  tip.previous_checkpoint_file_sha256 = previous_sha256;
  tip.checkpoint_file_sha256 = expected_file_sha256;
  tip.checkpoint_payload_sha256 = footer_sha256;
  tip.run_sha256 = stored_run_sha256;
  tip.root_state_object_id = stored_root_object_id;
  tip.graph_sha256 = stored_graph_sha256;
  tip.committed_expansions = committed_expansions;
  tip.node_count = node_count;
  tip.edge_count = edge_count;
  tip.byte_length = SizeAsUint64(bytes.size(), "checkpoint byte length");
  tip.status = RootStatus(dag);
  tip.path = path;
  return NativePNDAGLoadedCheckpoint{std::move(dag), std::move(tip)};
}

NativePNDAGCheckpointTip NativePNDAGCheckpointCodec::Publish(
    const std::filesystem::path& store_root, ProofNumberDAG& dag,
    const std::optional<NativePNDAGCheckpointTip>& previous_tip,
    const NativePNDAGCheckpointLimits& limits) {
  if (previous_tip.has_value() &&
      previous_tip->generation == std::numeric_limits<std::uint64_t>::max()) {
    throw std::overflow_error("checkpoint generation counter exhausted");
  }
  if (store_root.empty()) {
    throw std::invalid_argument("checkpoint store root must not be empty");
  }
  const std::filesystem::path absolute_store_root =
      std::filesystem::absolute(store_root).lexically_normal();
  const std::filesystem::path checkpoint_directory =
      absolute_store_root / "checkpoints";
  if (previous_tip.has_value()) {
    static_cast<void>(DecodeSha256(previous_tip->checkpoint_file_sha256));
    const std::filesystem::path canonical_predecessor_path =
        checkpoint_directory /
        (previous_tip->checkpoint_file_sha256 + ".pndag");
    if (std::filesystem::absolute(previous_tip->path).lexically_normal() !=
        canonical_predecessor_path) {
      throw std::invalid_argument(
          "checkpoint continuation must remain in the pinned predecessor store");
    }
    const State exact_root = dag.StateForId(dag.root_id());
    NativePNDAGLoadedCheckpoint verified_previous = Load(
        previous_tip->path, previous_tip->checkpoint_file_sha256, dag.rules(),
        dag.threshold2(), exact_root, limits);
    const auto& actual = verified_previous.tip;
    if (actual.generation != previous_tip->generation ||
        actual.previous_checkpoint_file_sha256 !=
            previous_tip->previous_checkpoint_file_sha256 ||
        actual.checkpoint_payload_sha256 !=
            previous_tip->checkpoint_payload_sha256 ||
        actual.run_sha256 != previous_tip->run_sha256 ||
        actual.root_state_object_id != previous_tip->root_state_object_id ||
        actual.graph_sha256 != previous_tip->graph_sha256 ||
        actual.committed_expansions != previous_tip->committed_expansions ||
        actual.node_count != previous_tip->node_count ||
        actual.edge_count != previous_tip->edge_count ||
        actual.byte_length != previous_tip->byte_length ||
        actual.status != previous_tip->status) {
      throw std::invalid_argument(
          "checkpoint predecessor tip disagrees with its exact file");
    }
    ValidateExtension(verified_previous.dag, dag);
  }
  const std::uint64_t generation =
      previous_tip.has_value() ? previous_tip->generation + 1U : 1U;
  if (generation > limits.max_lineage_generations) {
    throw std::length_error(
        "checkpoint generation exceeds the configured lineage limit");
  }
  NativePNDAGEncodedCheckpoint encoded =
      EncodeCheckpoint(dag, generation, previous_tip, limits);

  std::error_code error;
  const bool store_root_existed =
      std::filesystem::is_directory(absolute_store_root, error);
  if (error) error.clear();
  const bool checkpoint_directory_existed =
      std::filesystem::is_directory(checkpoint_directory, error);
  if (error) error.clear();
  std::filesystem::create_directories(checkpoint_directory, error);
  if (error || !std::filesystem::is_directory(checkpoint_directory)) {
    ThrowFilesystem("cannot create checkpoint directory", checkpoint_directory);
  }
  const std::filesystem::path destination =
      checkpoint_directory /
      (encoded.tip.checkpoint_file_sha256 + ".pndag");
  const std::filesystem::path temporary =
      NewTemporaryPath(checkpoint_directory);
  try {
    WriteFileBytes(temporary, encoded.bytes);
    FlushFile(temporary);
    InstallImmutable(temporary, destination, encoded.bytes);
    FlushFile(destination);
    FlushDirectory(checkpoint_directory);
    if (!checkpoint_directory_existed) FlushDirectory(absolute_store_root);
    if (!store_root_existed) {
      const auto parent = absolute_store_root.parent_path();
      if (!parent.empty()) FlushDirectory(parent);
    }
  } catch (...) {
    std::error_code cleanup_error;
    std::filesystem::remove(temporary, cleanup_error);
    throw;
  }

  encoded.tip.path = destination;
  const State exact_root = dag.StateForId(dag.root_id());
  NativePNDAGLoadedCheckpoint reopened = Load(
      destination, encoded.tip.checkpoint_file_sha256, dag.rules(),
      dag.threshold2(), exact_root, limits);
  if (reopened.tip.generation != encoded.tip.generation ||
      reopened.tip.previous_checkpoint_file_sha256 !=
          encoded.tip.previous_checkpoint_file_sha256 ||
      reopened.tip.checkpoint_file_sha256 !=
          encoded.tip.checkpoint_file_sha256 ||
      reopened.tip.checkpoint_payload_sha256 !=
          encoded.tip.checkpoint_payload_sha256 ||
      reopened.tip.run_sha256 != encoded.tip.run_sha256 ||
      reopened.tip.root_state_object_id != encoded.tip.root_state_object_id ||
      reopened.tip.graph_sha256 != encoded.tip.graph_sha256 ||
      reopened.tip.committed_expansions != encoded.tip.committed_expansions ||
      reopened.tip.node_count != encoded.tip.node_count ||
      reopened.tip.edge_count != encoded.tip.edge_count ||
      reopened.tip.byte_length != encoded.tip.byte_length ||
      reopened.tip.status != encoded.tip.status) {
    throw std::runtime_error(
        "published checkpoint failed exact reopen verification");
  }
  return encoded.tip;
}

NativePNDAGLoadedCheckpoint NativePNDAGCheckpointCodec::Load(
    const std::filesystem::path& checkpoint_path,
    const std::string& expected_checkpoint_file_sha256,
    const Rules& expected_rules, std::int64_t expected_threshold2,
    const State& expected_root_state,
    const NativePNDAGCheckpointLimits& limits) {
  if (checkpoint_path.empty()) {
    throw std::invalid_argument("checkpoint path must not be empty");
  }
  const std::filesystem::path absolute_checkpoint_path =
      std::filesystem::absolute(checkpoint_path).lexically_normal();
  NativePNDAGLoadedCheckpoint current = DecodeCheckpoint(
      ReadFileBytes(absolute_checkpoint_path, limits.max_file_bytes),
      absolute_checkpoint_path,
      expected_checkpoint_file_sha256, expected_rules, expected_threshold2,
      expected_root_state, limits);

  const ProofNumberDAG* descendant = &current.dag;
  std::uint64_t descendant_generation = current.tip.generation;
  std::optional<std::string> predecessor_sha256 =
      current.tip.previous_checkpoint_file_sha256;
  std::optional<NativePNDAGLoadedCheckpoint> retained_descendant;
  const std::filesystem::path checkpoint_directory =
      absolute_checkpoint_path.parent_path();
  while (predecessor_sha256.has_value()) {
    if (descendant_generation <= 1) {
      throw std::invalid_argument("checkpoint lineage generation underflow");
    }
    const std::filesystem::path predecessor_path =
        checkpoint_directory / (*predecessor_sha256 + ".pndag");
    NativePNDAGLoadedCheckpoint predecessor = DecodeCheckpoint(
        ReadFileBytes(predecessor_path, limits.max_file_bytes), predecessor_path,
        *predecessor_sha256, expected_rules, expected_threshold2,
        expected_root_state, limits);
    if (predecessor.tip.generation + 1U != descendant_generation ||
        predecessor.tip.run_sha256 != current.tip.run_sha256 ||
        predecessor.tip.root_state_object_id !=
            current.tip.root_state_object_id) {
      throw std::invalid_argument(
          "checkpoint lineage generation or exact-run metadata mismatch");
    }
    ValidateExtension(predecessor.dag, *descendant);
    descendant_generation = predecessor.tip.generation;
    predecessor_sha256 = predecessor.tip.previous_checkpoint_file_sha256;
    retained_descendant = std::move(predecessor);
    descendant = &retained_descendant->dag;
  }
  if (descendant_generation != 1) {
    throw std::invalid_argument("checkpoint lineage does not terminate at generation one");
  }
  return current;
}

}  // namespace ugts_go19
