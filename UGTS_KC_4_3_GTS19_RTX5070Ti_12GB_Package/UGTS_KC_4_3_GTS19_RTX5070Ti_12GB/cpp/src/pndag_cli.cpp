#include "ugts_go19/go_state.hpp"
#include "ugts_go19/pndag.hpp"
#include "ugts_go19/pndag_checkpoint.hpp"
#include "ugts_go19/sha256.hpp"

#include <charconv>
#include <climits>
#include <cstdint>
#include <filesystem>
#include <iostream>
#include <locale>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <system_error>
#include <vector>

#ifdef _WIN32
#define NOMINMAX
#include <windows.h>
#endif

namespace {

constexpr std::string_view kResultFormat = "UGTS-CPP-PNDAG-RESULT-v1";
constexpr std::string_view kCheckpointResultFormat =
    "UGTS-CPP-PNDAG-CHECKPOINT-RESULT-v1";
constexpr std::string_view kAlgorithm = "exact-pndag-bounded-v1";

void PrintUsage(std::ostream& stream) {
  stream << "Usage: ugts_go_pndag <size> <komi2> <threshold2> "
            "<expansion-budget> [--checkpoint-dir <directory>] "
            "[--resume-checkpoint <file> "
            "--expected-checkpoint-sha256 <sha256>]\n";
}

template <typename Integer>
Integer ParseInteger(std::string_view text, const char* label) {
  if (text.empty()) {
    throw std::invalid_argument(std::string(label) + " must not be empty");
  }
  const std::size_t digits_begin = text.front() == '-' ? 1U : 0U;
  if (digits_begin == text.size()) {
    throw std::invalid_argument(std::string(label) +
                                " must be a canonical decimal integer");
  }
  for (std::size_t index = digits_begin; index < text.size(); ++index) {
    if (text[index] < '0' || text[index] > '9') {
      throw std::invalid_argument(std::string(label) +
                                  " must be a canonical decimal integer");
    }
  }
  if ((text[digits_begin] == '0' && text.size() - digits_begin > 1U) ||
      (digits_begin == 1U && text.size() == 2U && text[1] == '0')) {
    throw std::invalid_argument(std::string(label) +
                                " must be a canonical decimal integer");
  }
  Integer value = 0;
  const char* const begin = text.data();
  const char* const end = begin + text.size();
  const auto parsed = std::from_chars(begin, end, value);
  if (parsed.ec == std::errc::result_out_of_range) {
    throw std::out_of_range(std::string(label) + " is outside its integer range");
  }
  if (parsed.ec != std::errc{} || parsed.ptr != end) {
    throw std::invalid_argument(std::string(label) +
                                " must be a canonical decimal integer");
  }
  return value;
}

void WriteJsonString(std::ostream& stream, std::string_view value) {
  constexpr char kHexDigits[] = "0123456789abcdef";
  stream << '"';
  for (const unsigned char byte : value) {
    switch (byte) {
      case '"':
        stream << "\\\"";
        break;
      case '\\':
        stream << "\\\\";
        break;
      case '\b':
        stream << "\\b";
        break;
      case '\f':
        stream << "\\f";
        break;
      case '\n':
        stream << "\\n";
        break;
      case '\r':
        stream << "\\r";
        break;
      case '\t':
        stream << "\\t";
        break;
      default:
        if (byte < 0x20U) {
          stream << "\\u00" << kHexDigits[byte >> 4U]
                 << kHexDigits[byte & 0x0fU];
        } else {
          stream << static_cast<char>(byte);
        }
        break;
    }
  }
  stream << '"';
}

struct CheckpointOptions {
  std::optional<std::filesystem::path> directory;
  std::optional<std::filesystem::path> resume_path;
  std::optional<std::string> expected_sha256;
};

CheckpointOptions ParseCheckpointOptions(int argc, char** argv) {
  CheckpointOptions options;
  for (int index = 5; index < argc; index += 2) {
    if (index + 1 >= argc) {
      throw std::invalid_argument("checkpoint option is missing its value");
    }
    const std::string_view option = argv[index];
    if (option == "--checkpoint-dir") {
      if (options.directory.has_value()) {
        throw std::invalid_argument("--checkpoint-dir was repeated");
      }
      options.directory = std::filesystem::u8path(argv[index + 1]);
      if (options.directory->empty()) {
        throw std::invalid_argument("--checkpoint-dir must not be empty");
      }
    } else if (option == "--resume-checkpoint") {
      if (options.resume_path.has_value()) {
        throw std::invalid_argument("--resume-checkpoint was repeated");
      }
      options.resume_path = std::filesystem::u8path(argv[index + 1]);
      if (options.resume_path->empty()) {
        throw std::invalid_argument("--resume-checkpoint must not be empty");
      }
    } else if (option == "--expected-checkpoint-sha256") {
      if (options.expected_sha256.has_value()) {
        throw std::invalid_argument(
            "--expected-checkpoint-sha256 was repeated");
      }
      options.expected_sha256 = argv[index + 1];
    } else {
      throw std::invalid_argument("unknown checkpoint option");
    }
  }
  if (!options.directory.has_value()) {
    throw std::invalid_argument(
        "extended checkpoint mode requires --checkpoint-dir");
  }
  if (options.resume_path.has_value() != options.expected_sha256.has_value()) {
    throw std::invalid_argument(
        "resume requires both checkpoint path and external SHA-256 pin");
  }
  return options;
}

void WriteResult(const ugts_go19::ProofNumberDAG& dag,
                 const ugts_go19::ProofNumberDAGResult& result,
                 std::uint64_t requested_expansions) {
  const auto& rules = dag.rules();
  const std::string root_state =
      ugts_go19::CanonicalStateJson(dag.StateForId(dag.root_id()), rules);
  const std::string root_state_object_id = ugts_go19::Sha256Hex(root_state);

  // Top-level and nested object keys are emitted in lexical order with no
  // insignificant whitespace, yielding one deterministic canonical JSON line.
  std::cout
      << "{\"algorithm\":\"" << kAlgorithm
      << "\",\"claim_boundary\":{\"certificate\":false,"
         "\"expansion_budget_stop_status\":\"UNKNOWN\","
         "\"scope\":\"host-memory-exact-bounded-attempt\"}"
      << ",\"committed_expansions\":" << result.committed_expansions
      << ",\"disproof_number\":" << result.disproof_number
      << ",\"edge_count\":" << result.edge_count
      << ",\"expanded_this_call\":" << result.expanded_this_call
      << ",\"format\":\"" << kResultFormat << "\",\"graph_sha256\":\""
      << result.graph_sha256 << "\",\"node_count\":" << result.node_count
      << ",\"proof_arithmetic\":{\"bits\":64,\"endianness\":\"little\","
         "\"infinity\":\""
      << ugts_go19::kProofInfinity << "\",\"kind\":\"saturating_uint64\"}"
      << ",\"proof_number\":" << result.proof_number
      << ",\"requested_expansions\":" << requested_expansions
      << ",\"root_state\":" << root_state
      << ",\"root_state_object_id\":\"" << root_state_object_id
      << "\",\"rules\":{\"allow_suicide\":"
      << (rules.allow_suicide ? "true" : "false")
      << ",\"komi2\":" << rules.komi2
      << ",\"passes_to_end\":" << rules.passes_to_end
      << ",\"scoring\":\"area\",\"size\":" << rules.size
      << ",\"superko\":\"positional_superko\"},\"status\":\""
      << ugts_go19::ProofStatusName(result.status)
      << "\",\"threshold2\":" << result.threshold2 << "}\n";
}

void WriteCheckpointTip(const ugts_go19::NativePNDAGCheckpointTip& tip) {
  std::cout << "{\"byte_length\":" << tip.byte_length
            << ",\"checkpoint_file_sha256\":\""
            << tip.checkpoint_file_sha256
            << "\",\"checkpoint_payload_sha256\":\""
            << tip.checkpoint_payload_sha256
            << "\",\"committed_expansions\":" << tip.committed_expansions
            << ",\"edge_count\":" << tip.edge_count << ",\"format\":\""
            << ugts_go19::kNativePNDAGCheckpointTipFormat
            << "\",\"generation\":" << tip.generation
            << ",\"graph_sha256\":\"" << tip.graph_sha256
            << "\",\"node_count\":" << tip.node_count << ",\"path\":";
  WriteJsonString(std::cout, tip.path.generic_u8string());
  std::cout << ",\"previous_checkpoint_file_sha256\":";
  if (tip.previous_checkpoint_file_sha256.has_value()) {
    std::cout << '"' << *tip.previous_checkpoint_file_sha256 << '"';
  } else {
    std::cout << "null";
  }
  std::cout << ",\"root_state_object_id\":\"" << tip.root_state_object_id
            << "\",\"run_sha256\":\"" << tip.run_sha256
            << "\",\"status\":\"" << ugts_go19::ProofStatusName(tip.status)
            << "\"}";
}

void WriteCheckpointResult(
    const ugts_go19::ProofNumberDAG& dag,
    const ugts_go19::ProofNumberDAGResult& result,
    std::uint64_t requested_expansions,
    const ugts_go19::NativePNDAGCheckpointTip& tip) {
  const auto& rules = dag.rules();
  const std::string root_state =
      ugts_go19::CanonicalStateJson(dag.StateForId(dag.root_id()), rules);
  const std::string root_state_object_id = ugts_go19::Sha256Hex(root_state);

  std::cout << "{\"algorithm\":\"" << kAlgorithm << "\",\"checkpoint_tip\":";
  WriteCheckpointTip(tip);
  std::cout
      << ",\"claim_boundary\":{\"certificate\":false,"
         "\"expansion_budget_stop_status\":\"UNKNOWN\","
         "\"scope\":\"host-memory-exact-bounded-checkpoint-attempt\"}"
      << ",\"committed_expansions\":" << result.committed_expansions
      << ",\"disproof_number\":" << result.disproof_number
      << ",\"edge_count\":" << result.edge_count
      << ",\"expanded_this_call\":" << result.expanded_this_call
      << ",\"format\":\"" << kCheckpointResultFormat
      << "\",\"graph_sha256\":\"" << result.graph_sha256
      << "\",\"node_count\":" << result.node_count
      << ",\"proof_arithmetic\":{\"bits\":64,\"endianness\":\"little\","
         "\"infinity\":\""
      << ugts_go19::kProofInfinity << "\",\"kind\":\"saturating_uint64\"}"
      << ",\"proof_number\":" << result.proof_number
      << ",\"requested_expansions\":" << requested_expansions
      << ",\"root_state\":" << root_state
      << ",\"root_state_object_id\":\"" << root_state_object_id
      << "\",\"rules\":{\"allow_suicide\":"
      << (rules.allow_suicide ? "true" : "false")
      << ",\"komi2\":" << rules.komi2
      << ",\"passes_to_end\":" << rules.passes_to_end
      << ",\"scoring\":\"area\",\"size\":" << rules.size
      << ",\"superko\":\"positional_superko\"},\"status\":\""
      << ugts_go19::ProofStatusName(result.status)
      << "\",\"threshold2\":" << result.threshold2 << "}\n";
}

}  // namespace

int RunMain(int argc, char** argv) {
  std::cout.imbue(std::locale::classic());
  std::cerr.imbue(std::locale::classic());
  if (argc == 2 && std::string_view(argv[1]) == "--help") {
    PrintUsage(std::cout);
    return 0;
  }
  if (argc < 5 || (argc > 5 && (argc - 5) % 2 != 0)) {
    PrintUsage(std::cerr);
    return 2;
  }

  try {
    ugts_go19::Rules rules;
    rules.size = ParseInteger<int>(argv[1], "size");
    rules.komi2 = ParseInteger<int>(argv[2], "komi2");
    rules.allow_suicide = false;
    rules.passes_to_end = 2;
    const std::int64_t threshold2 =
        ParseInteger<std::int64_t>(argv[3], "threshold2");
    const std::uint64_t expansion_budget =
        ParseInteger<std::uint64_t>(argv[4], "expansion budget");

    if (argc == 5) {
      ugts_go19::ProofNumberDAG dag(rules, threshold2);
      const auto result = dag.Advance(expansion_budget);
      WriteResult(dag, result, expansion_budget);
    } else {
      const CheckpointOptions options = ParseCheckpointOptions(argc, argv);
      const ugts_go19::State expected_root = ugts_go19::State::Initial(rules);
      std::optional<ugts_go19::NativePNDAGCheckpointTip> previous_tip;
      std::optional<ugts_go19::ProofNumberDAG> dag;
      if (options.resume_path.has_value()) {
        auto loaded = ugts_go19::NativePNDAGCheckpointCodec::Load(
            *options.resume_path, *options.expected_sha256, rules, threshold2,
            expected_root);
        previous_tip = loaded.tip;
        dag.emplace(std::move(loaded.dag));
      } else {
        dag.emplace(rules, threshold2);
      }
      const auto result = dag->Advance(expansion_budget);
      ugts_go19::NativePNDAGCheckpointTip tip;
      if (previous_tip.has_value() && result.expanded_this_call == 0) {
        tip = *previous_tip;
      } else {
        tip = ugts_go19::NativePNDAGCheckpointCodec::Publish(
            *options.directory, *dag, previous_tip);
      }
      WriteCheckpointResult(*dag, result, expansion_budget, tip);
    }
    std::cout.flush();
    if (!std::cout) {
      throw std::runtime_error("failed to write result to stdout");
    }
    return 0;
  } catch (const std::invalid_argument& error) {
    std::cerr << "ugts_go_pndag: " << error.what() << '\n';
    return 2;
  } catch (const std::out_of_range& error) {
    std::cerr << "ugts_go_pndag: " << error.what() << '\n';
    return 2;
  } catch (const std::exception& error) {
    std::cerr << "ugts_go_pndag: " << error.what() << '\n';
    return 1;
  }
}

#ifdef _WIN32
std::string WideToUtf8(std::wstring_view value) {
  if (value.empty()) return {};
  if (value.size() > static_cast<std::size_t>(INT_MAX)) {
    throw std::length_error("command-line argument is too long");
  }
  const int required = WideCharToMultiByte(
      CP_UTF8, WC_ERR_INVALID_CHARS, value.data(),
      static_cast<int>(value.size()), nullptr, 0, nullptr, nullptr);
  if (required <= 0) {
    throw std::invalid_argument("command-line argument is not valid Unicode");
  }
  std::string result(static_cast<std::size_t>(required), '\0');
  if (WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, value.data(),
                          static_cast<int>(value.size()), result.data(), required,
                          nullptr, nullptr) != required) {
    throw std::invalid_argument("command-line UTF-8 conversion failed");
  }
  return result;
}

int wmain(int argc, wchar_t** wide_argv) {
  try {
    std::vector<std::string> arguments;
    arguments.reserve(static_cast<std::size_t>(argc));
    for (int index = 0; index < argc; ++index) {
      arguments.push_back(WideToUtf8(wide_argv[index]));
    }
    std::vector<char*> pointers;
    pointers.reserve(arguments.size());
    for (auto& argument : arguments) pointers.push_back(argument.data());
    return RunMain(argc, pointers.data());
  } catch (const std::exception& error) {
    std::cerr << "ugts_go_pndag: " << error.what() << '\n';
    return 2;
  }
}
#else
int main(int argc, char** argv) { return RunMain(argc, argv); }
#endif
