#include "ugts_go19/cuda_verified_expander.hpp"
#include "ugts_go19/sha256.hpp"

#include <cuda_runtime.h>

#include <algorithm>
#include <charconv>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <exception>
#include <iomanip>
#include <iostream>
#include <limits>
#include <locale>
#include <map>
#include <optional>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <system_error>
#include <utility>
#include <vector>

namespace {

constexpr std::uint64_t kDefaultTargetUniqueCorpusSlots = 10'000'000ULL;
constexpr std::size_t kDefaultBatchStates = 16U;
constexpr std::uint64_t kDefaultSeed = 0x507019C0FFEEULL;
constexpr std::size_t kMinimumDenseRandomStateCount = 320U;
constexpr std::size_t kStructuralCampaignEpisodes = 8U;
constexpr std::size_t kStructuralCampaignSnapshots = 4U;
constexpr std::size_t kScaleCampaignEpisodes = 128U;
constexpr std::size_t kScaleCampaignSnapshots = 12U;

struct Options {
  std::uint64_t target_unique_corpus_slots =
      kDefaultTargetUniqueCorpusSlots;
  std::size_t batch_states = kDefaultBatchStates;
  std::uint64_t seed = kDefaultSeed;
};

struct SplitMix64 {
  std::uint64_t state;

  std::uint64_t Next() {
    state += 0x9e3779b97f4a7c15ULL;
    std::uint64_t value = state;
    value = (value ^ (value >> 30U)) * 0xbf58476d1ce4e5b9ULL;
    value = (value ^ (value >> 27U)) * 0x94d049bb133111ebULL;
    return value ^ (value >> 31U);
  }
};

struct CorpusEntry {
  std::size_t id = 0;
  std::string label;
  std::string category;
  ugts_go19::Rules rules;
  ugts_go19::State state;
  std::string canonical_state;
};

struct BatchSpec {
  int board_size = 0;
  std::vector<std::size_t> corpus_ids;
};

struct Aggregate {
  std::uint64_t states = 0;
  std::uint64_t point_slots = 0;
  std::uint64_t occupied = 0;
  std::uint64_t suicides = 0;
  std::uint64_t local_candidates = 0;
  std::uint64_t superko_rejections = 0;
  std::uint64_t globally_legal_children = 0;
  std::uint64_t compared_child_words = 0;
  std::uint64_t capture_slots = 0;
  std::uint64_t captured_stones = 0;
  std::uint64_t batch_calls = 0;
  std::uint64_t high_water_requested_device_bytes = 0;
  std::uint64_t minimum_free_device_bytes_before_batch =
      std::numeric_limits<std::uint64_t>::max();
  std::uint64_t minimum_adapter_workspace_budget_bytes =
      std::numeric_limits<std::uint64_t>::max();
  std::uint16_t maximum_capture = 0;
  std::map<int, std::uint64_t> slots_by_board_size;
  std::map<std::string, std::uint64_t> slots_by_category;
  std::string result_sha256;
  double elapsed_seconds = 0.0;
};

void CheckCuda(cudaError_t status, const char* operation) {
  if (status != cudaSuccess) {
    throw std::runtime_error(std::string(operation) + ": " +
                             cudaGetErrorString(status));
  }
}

template <typename T>
T ParseInteger(std::string_view text, const char* label) {
  T value{};
  const char* begin = text.data();
  const char* end = begin + text.size();
  const auto result = std::from_chars(begin, end, value);
  if (text.empty() || result.ec != std::errc{} || result.ptr != end) {
    throw std::invalid_argument(std::string("invalid ") + label);
  }
  return value;
}

Options ParseOptions(int argc, char** argv) {
  Options options;
  for (int index = 1; index < argc; index += 2) {
    if (index + 1 >= argc) {
      throw std::invalid_argument("option is missing its value");
    }
    const std::string_view option = argv[index];
    const std::string_view value = argv[index + 1];
    if (option == "--target-unique-corpus-slots") {
      options.target_unique_corpus_slots =
          ParseInteger<std::uint64_t>(value, "target-unique-corpus-slots");
    } else if (option == "--batch-states") {
      options.batch_states = ParseInteger<std::size_t>(value, "batch-states");
    } else if (option == "--seed") {
      options.seed = ParseInteger<std::uint64_t>(value, "seed");
    } else {
      throw std::invalid_argument("unknown option: " + std::string(option));
    }
  }
  if (options.target_unique_corpus_slots == 0U ||
      options.target_unique_corpus_slots > 1'000'000'000ULL) {
    throw std::invalid_argument(
        "target-unique-corpus-slots must be in 1..1000000000");
  }
  if (options.batch_states == 0U || options.batch_states > 4096U) {
    throw std::invalid_argument("batch-states must be in 1..4096");
  }
  return options;
}

ugts_go19::Rules RulesFor(int size) {
  ugts_go19::Rules rules;
  rules.size = size;
  rules.komi2 = size == 19 ? 15 : 1;
  rules.allow_suicide = false;
  rules.passes_to_end = 2;
  return rules;
}

ugts_go19::State ExplicitState(
    const ugts_go19::Rules& rules, std::vector<std::uint8_t> board,
    std::uint8_t to_play,
    std::optional<std::vector<std::vector<std::uint8_t>>> seen = std::nullopt,
    std::optional<std::vector<std::uint8_t>> previous = std::nullopt,
    int passes = 0, std::uint64_t ply = 0) {
  ugts_go19::State state;
  state.size = rules.size;
  state.board = std::move(board);
  state.to_play = to_play;
  state.passes = passes;
  state.seen_boards = seen.has_value()
                          ? std::move(*seen)
                          : std::vector<std::vector<std::uint8_t>>{state.board};
  state.previous_board = std::move(previous);
  state.ply = ply;
  static_cast<void>(ugts_go19::CanonicalStateJson(state, rules));
  return state;
}

ugts_go19::State PlaySequence(ugts_go19::State state,
                              const std::vector<int>& moves,
                              const ugts_go19::Rules& rules) {
  for (int move : moves) state = ugts_go19::ApplyMove(state, move, rules).state;
  return state;
}

void AddEntry(std::vector<CorpusEntry>* corpus, std::string label,
              std::string category, const ugts_go19::Rules& rules,
              ugts_go19::State state) {
  const std::string canonical = ugts_go19::CanonicalStateJson(state, rules);
  corpus->push_back({corpus->size(), std::move(label), std::move(category),
                     rules, std::move(state), canonical});
}

std::vector<CorpusEntry> BuildCorpus(std::uint64_t seed,
                                     std::uint64_t target_unique_slots) {
  using ugts_go19::kBlack;
  using ugts_go19::kEmpty;
  using ugts_go19::kPass;
  using ugts_go19::kWhite;

  std::vector<CorpusEntry> corpus;
  const auto rules1 = RulesFor(1);
  AddEntry(&corpus, "one-point-suicide", "adversarial-small", rules1,
           ugts_go19::State::Initial(rules1));

  const auto rules2 = RulesFor(2);
  AddEntry(&corpus, "two-by-two-empty", "adversarial-small", rules2,
           ugts_go19::State::Initial(rules2));

  const auto rules3 = RulesFor(3);
  AddEntry(&corpus, "three-empty", "adversarial-small", rules3,
           ugts_go19::State::Initial(rules3));
  AddEntry(&corpus, "single-capture", "capture-fixture", rules3,
           ExplicitState(rules3,
                         {kEmpty, kEmpty, kEmpty, kWhite, kBlack, kWhite,
                          kEmpty, kWhite, kEmpty},
                         kWhite));
  AddEntry(&corpus, "multi-capture", "capture-fixture", rules3,
           ExplicitState(rules3,
                         {kBlack, kWhite, kBlack, kWhite, kEmpty, kEmpty,
                          kBlack, kEmpty, kEmpty},
                         kBlack));
  AddEntry(&corpus, "suicide-cross", "suicide-fixture", rules3,
           ExplicitState(rules3,
                         {kEmpty, kWhite, kEmpty, kWhite, kEmpty, kWhite,
                          kEmpty, kWhite, kEmpty},
                         kBlack));
  AddEntry(&corpus, "same-group-four-adjacencies", "adversarial-small",
           rules3,
           ExplicitState(rules3,
                         {kWhite, kWhite, kWhite, kWhite, kEmpty, kWhite,
                          kWhite, kWhite, kWhite},
                         kBlack));
  const auto initial3 = ugts_go19::State::Initial(rules3);
  const auto repeated_child = ugts_go19::ApplyMove(initial3, 1, rules3).state;
  AddEntry(&corpus, "poisoned-history", "ko-psk-fixture", rules3,
           ExplicitState(rules3, initial3.board, kBlack,
                         std::vector<std::vector<std::uint8_t>>{
                             initial3.board, repeated_child.board}));
  AddEntry(&corpus, "one-pass-nonterminal", "pass-metadata-fixture", rules3,
           ugts_go19::ApplyMove(initial3, kPass, rules3).state);
  const auto snapback_before =
      PlaySequence(initial3, {0, 3, 5, 4, 7, 2}, rules3);
  AddEntry(&corpus, "snapback-before", "capture-fixture", rules3,
           snapback_before);
  AddEntry(&corpus, "snapback-after", "capture-fixture", rules3,
           ugts_go19::ApplyMove(snapback_before, 1, rules3).state);

  const auto rules5 = RulesFor(5);
  const auto initial5 = ugts_go19::State::Initial(rules5);
  const auto ko_before =
      PlaySequence(initial5, {1, 2, 3, 6, 20, 8, 24, 12}, rules5);
  AddEntry(&corpus, "ko-before", "ko-psk-fixture", rules5, ko_before);
  AddEntry(&corpus, "ko-after-psk", "ko-psk-fixture", rules5,
           ugts_go19::ApplyMove(ko_before, 7, rules5).state);
  std::vector<std::uint8_t> four_capture(25U, kEmpty);
  for (int point : {7, 11, 13, 17}) four_capture[point] = kWhite;
  for (int point : {2, 6, 8, 10, 14, 16, 18, 22}) {
    four_capture[point] = kBlack;
  }
  AddEntry(&corpus, "four-distinct-groups", "capture-fixture", rules5,
           ExplicitState(rules5, std::move(four_capture), kBlack));

  const auto rules9 = RulesFor(9);
  AddEntry(&corpus, "nine-empty", "adversarial-medium", rules9,
           ugts_go19::State::Initial(rules9));

  const auto rules19 = RulesFor(19);
  AddEntry(&corpus, "nineteen-empty", "adversarial-19x19", rules19,
           ugts_go19::State::Initial(rules19));
  std::vector<std::uint8_t> max_capture(361U, kWhite);
  max_capture[360] = kEmpty;
  AddEntry(&corpus, "capture-360-tail-point", "capture-fixture-19x19",
           rules19, ExplicitState(rules19, std::move(max_capture), kBlack));
  std::vector<std::uint8_t> max_suicide(361U, kBlack);
  max_suicide[360] = kEmpty;
  AddEntry(&corpus, "suicide-361-group", "suicide-fixture-19x19", rules19,
           ExplicitState(rules19, std::move(max_suicide), kBlack));
  std::vector<std::uint8_t> boundaries(361U, kEmpty);
  for (int point : {0, 63, 64, 127, 128, 319, 320, 360}) {
    boundaries[static_cast<std::size_t>(point)] = kBlack;
  }
  for (int point : {1, 62, 65, 126, 129, 318, 321, 359}) {
    boundaries[static_cast<std::size_t>(point)] = kWhite;
  }
  AddEntry(&corpus, "word-and-tail-boundaries", "word-tail-fixture-19x19",
           rules19, ExplicitState(rules19, std::move(boundaries), kWhite));

  SplitMix64 random{seed};
  const bool full_scale =
      target_unique_slots >= kDefaultTargetUniqueCorpusSlots;
  const std::size_t campaign_episodes =
      full_scale ? kScaleCampaignEpisodes : kStructuralCampaignEpisodes;
  const std::size_t campaign_snapshots =
      full_scale ? kScaleCampaignSnapshots : kStructuralCampaignSnapshots;
  const std::size_t snapshot_interval = full_scale ? 4U : 8U;
  for (std::size_t episode = 0; episode < campaign_episodes; ++episode) {
    ugts_go19::State state = ugts_go19::State::Initial(rules19);
    SplitMix64 episode_random{
        random.Next() ^ (0x9e3779b97f4a7c15ULL * (episode + 1U))};
    std::size_t accepted = 0;
    while (accepted < snapshot_interval * campaign_snapshots) {
      bool moved = false;
      for (std::size_t attempt = 0; attempt < 361U * 2U; ++attempt) {
        const int move = static_cast<int>(episode_random.Next() % 361U);
        try {
          state = ugts_go19::ApplyMove(state, move, rules19).state;
          moved = true;
          break;
        } catch (const ugts_go19::IllegalMove&) {
        }
      }
      if (!moved) {
        throw std::runtime_error("campaign generator exhausted point attempts");
      }
      ++accepted;
      if (accepted % snapshot_interval == 0U) {
        AddEntry(&corpus,
                 "campaign-" + std::to_string(episode) + "-ply-" +
                     std::to_string(accepted),
                 "campaign-shaped-19x19", rules19, state);
      }
    }
  }

  std::uint64_t base_slots = 0;
  for (const auto& entry : corpus) {
    base_slots += static_cast<std::uint64_t>(entry.rules.size) *
                  static_cast<std::uint64_t>(entry.rules.size);
  }
  const std::uint64_t deficit =
      target_unique_slots > base_slots ? target_unique_slots - base_slots : 0U;
  const std::uint64_t needed_dense = (deficit + 360U) / 361U;
  const std::uint64_t dense_count =
      std::max<std::uint64_t>(kMinimumDenseRandomStateCount, needed_dense);
  for (std::uint64_t index = 0; index < dense_count; ++index) {
    std::vector<std::uint8_t> board(361U, kEmpty);
    for (std::size_t point = 0; point < board.size(); ++point) {
      const std::uint64_t draw = random.Next() % 100U;
      board[point] = draw < 46U ? kBlack : (draw < 92U ? kWhite : kEmpty);
    }
    // Exercise packed-word boundaries and the tail without dirty padding.
    const std::size_t forced_empty =
        static_cast<std::size_t>((index * 64U) % board.size());
    board[forced_empty] = kEmpty;
    board[360] = (index % 3U == 0U) ? kEmpty : board[360];
    // Twenty exact base-3 digits make the randomized board bytes injective for
    // every accepted CLI target (3^20 > 1e9 / 361). Canonical-byte duplicate
    // rejection below remains the independent exact accounting authority.
    std::uint64_t ordinal = index + 1U;
    for (std::size_t digit = 0; digit < 20U; ++digit) {
      board[32U + digit] = static_cast<std::uint8_t>(ordinal % 3U);
      ordinal /= 3U;
    }
    if (ordinal != 0U) {
      throw std::runtime_error("randomized state ordinal encoding overflow");
    }
    AddEntry(&corpus, "random-ordinal-dense-" + std::to_string(index),
             index % 64U == 0U ? "randomized-ordinal-psk-19x19"
                               : "randomized-ordinal-dense-19x19",
             rules19,
             [&] {
               auto state = ExplicitState(
                   rules19, std::move(board),
                   (random.Next() & 1U) == 0U ? kBlack : kWhite);
               if (index % 64U != 0U) return state;
               for (int move = 0; move < 361; ++move) {
                 try {
                   const auto child =
                       ugts_go19::ApplyMove(state, move, rules19).state.board;
                   state.seen_boards.push_back(child);
                   static_cast<void>(
                       ugts_go19::CanonicalStateJson(state, rules19));
                   return state;
                 } catch (const ugts_go19::IllegalMove&) {
                 }
               }
               throw std::runtime_error(
                   "randomized PSK state has no poisonable local child");
             }());
  }

  std::set<std::string> exact_states;
  for (const auto& entry : corpus) {
    if (!exact_states.insert(entry.canonical_state).second) {
      throw std::runtime_error("corpus contains a duplicate semantic state");
    }
  }
  if (base_slots + dense_count * 361U < target_unique_slots) {
    throw std::runtime_error("unique corpus did not reach its slot target");
  }
  return corpus;
}

void AppendU64(std::string* output, std::uint64_t value) {
  for (unsigned int shift = 0; shift < 64U; shift += 8U) {
    output->push_back(static_cast<char>((value >> shift) & 0xffU));
  }
}

std::string CorpusSha256(const std::vector<CorpusEntry>& corpus,
                         std::uint64_t seed) {
  std::string material = "UGTS-CUDA-LOCAL-SCALE-CORPUS-v1";
  AppendU64(&material, seed);
  AppendU64(&material, static_cast<std::uint64_t>(corpus.size()));
  for (const auto& entry : corpus) {
    AppendU64(&material, static_cast<std::uint64_t>(entry.id));
    AppendU64(&material, static_cast<std::uint64_t>(entry.label.size()));
    material.append(entry.label);
    AppendU64(&material, static_cast<std::uint64_t>(entry.category.size()));
    material.append(entry.category);
    AppendU64(&material,
              static_cast<std::uint64_t>(entry.canonical_state.size()));
    material.append(entry.canonical_state);
  }
  return ugts_go19::Sha256Hex(material);
}

std::uint64_t CorpusSlots(const std::vector<CorpusEntry>& corpus) {
  std::uint64_t slots = 0;
  for (const auto& entry : corpus) {
    const auto points = static_cast<std::uint64_t>(entry.rules.size) *
                        static_cast<std::uint64_t>(entry.rules.size);
    if (slots > std::numeric_limits<std::uint64_t>::max() - points) {
      throw std::overflow_error("corpus point-slot count overflow");
    }
    slots += points;
  }
  return slots;
}

std::vector<BatchSpec> BuildWorkload(const std::vector<CorpusEntry>& corpus,
                                     std::size_t batch_states) {
  std::map<int, std::vector<std::size_t>> groups;
  for (const auto& entry : corpus) groups[entry.rules.size].push_back(entry.id);
  std::vector<BatchSpec> workload;
  for (const auto& [size, ids] : groups) {
    for (std::size_t begin = 0; begin < ids.size(); begin += batch_states) {
      const std::size_t end = std::min(ids.size(), begin + batch_states);
      BatchSpec batch;
      batch.board_size = size;
      batch.corpus_ids.assign(ids.begin() + static_cast<std::ptrdiff_t>(begin),
                              ids.begin() + static_cast<std::ptrdiff_t>(end));
      workload.push_back(std::move(batch));
    }
  }
  return workload;
}

std::size_t FractionFloor(std::size_t value, std::size_t numerator,
                          std::size_t denominator) {
  return (value / denominator) * numerator +
         ((value % denominator) * numerator) / denominator;
}

std::uint64_t WorkspaceBudget(std::size_t free_bytes) {
  const std::size_t reserve = FractionFloor(free_bytes, 18U, 100U);
  return static_cast<std::uint64_t>(
      FractionFloor(free_bytes - reserve, 16U, 100U));
}

void CheckBatchInvariants(
    const BatchSpec& spec, const std::vector<CorpusEntry>& corpus,
    const ugts_go19::cuda::VerifiedExpansionBatch& batch,
    std::uint64_t batch_ordinal, Aggregate* aggregate) {
  const std::size_t points = static_cast<std::size_t>(
      spec.board_size * spec.board_size);
  const std::size_t words = (points + 63U) / 64U;
  const std::uint64_t expected_slots =
      static_cast<std::uint64_t>(spec.corpus_ids.size()) * points;
  const auto& stats = batch.stats;
  if (stats.states != spec.corpus_ids.size() ||
      stats.point_slots != expected_slots ||
      batch.slots.size() != expected_slots ||
      stats.occupied + stats.suicides + stats.local_candidates !=
          expected_slots ||
      stats.superko_rejections + stats.globally_legal_children !=
          stats.local_candidates ||
      stats.compared_child_words != stats.local_candidates * 2U * words ||
      batch.legal_children.size() != stats.globally_legal_children) {
    throw std::runtime_error("adapter batch summary invariant failed");
  }

  std::uint64_t occupied = 0;
  std::uint64_t suicides = 0;
  std::uint64_t candidates = 0;
  std::uint64_t superko = 0;
  std::uint64_t legal = 0;
  std::size_t legal_cursor = 0;
  std::string material;
  material.reserve(128U + batch.slots.size() * 16U);
  AppendU64(&material, batch_ordinal);
  AppendU64(&material, static_cast<std::uint64_t>(spec.board_size));
  AppendU64(&material, static_cast<std::uint64_t>(spec.corpus_ids.size()));
  for (std::size_t parent = 0; parent < spec.corpus_ids.size(); ++parent) {
    AppendU64(&material, static_cast<std::uint64_t>(spec.corpus_ids[parent]));
    const auto& entry = corpus[spec.corpus_ids[parent]];
    aggregate->slots_by_category[entry.category] += points;
    for (std::size_t move = 0; move < points; ++move) {
      const std::size_t slot_index = parent * points + move;
      const auto& slot = batch.slots[slot_index];
      if (slot.parent_index != parent ||
          slot.move != static_cast<int>(move)) {
        throw std::runtime_error("adapter slot ordering invariant failed");
      }
      AppendU64(&material, static_cast<std::uint64_t>(move));
      material.push_back(static_cast<char>(slot.local_status));
      AppendU64(&material, slot.captured);
      AppendU64(&material, slot.self_captured);
      material.push_back(slot.superko_rejected ? '\1' : '\0');
      material.push_back(slot.globally_legal ? '\1' : '\0');

      if (slot.local_status ==
          ugts_go19::cuda::LocalPointStatus::kOccupied) {
        if (slot.captured != 0U || slot.self_captured != 0U ||
            !slot.local_child_board.empty() || slot.superko_rejected ||
            slot.globally_legal) {
          throw std::runtime_error("occupied slot payload invariant failed");
        }
        ++occupied;
      } else if (slot.local_status ==
                 ugts_go19::cuda::LocalPointStatus::kSuicide) {
        if (slot.captured != 0U || slot.self_captured != 0U ||
            !slot.local_child_board.empty() || slot.superko_rejected ||
            slot.globally_legal) {
          throw std::runtime_error("suicide slot payload invariant failed");
        }
        ++suicides;
      } else if (slot.local_status ==
                 ugts_go19::cuda::LocalPointStatus::kCandidateNeedsSuperko) {
        if (slot.local_child_board.size() != points ||
            slot.self_captured != 0U ||
            slot.superko_rejected == slot.globally_legal) {
          throw std::runtime_error("candidate slot payload invariant failed");
        }
        material.append(
            reinterpret_cast<const char*>(slot.local_child_board.data()),
            slot.local_child_board.size());
        ++candidates;
        aggregate->maximum_capture =
            std::max(aggregate->maximum_capture, slot.captured);
        if (slot.captured != 0U) {
          ++aggregate->capture_slots;
          aggregate->captured_stones += slot.captured;
        }
        if (slot.superko_rejected) {
          ++superko;
        } else {
          if (legal_cursor >= batch.legal_children.size()) {
            throw std::runtime_error("legal-child stream is truncated");
          }
          const auto& child = batch.legal_children[legal_cursor++];
          if (child.parent_index != parent || child.move != static_cast<int>(move) ||
              child.result.state.board != slot.local_child_board ||
              child.result.captured != slot.captured ||
              child.result.self_captured != slot.self_captured) {
            throw std::runtime_error("legal-child payload invariant failed");
          }
          ++legal;
        }
      } else {
        throw std::runtime_error("fatal or unknown status crossed adapter");
      }
    }
  }
  if (occupied != stats.occupied || suicides != stats.suicides ||
      candidates != stats.local_candidates ||
      superko != stats.superko_rejections ||
      legal != stats.globally_legal_children ||
      legal_cursor != batch.legal_children.size()) {
    throw std::runtime_error("adapter slot/detail totals differ from summary");
  }

  aggregate->states += stats.states;
  aggregate->point_slots += stats.point_slots;
  aggregate->occupied += stats.occupied;
  aggregate->suicides += stats.suicides;
  aggregate->local_candidates += stats.local_candidates;
  aggregate->superko_rejections += stats.superko_rejections;
  aggregate->globally_legal_children += stats.globally_legal_children;
  aggregate->compared_child_words += stats.compared_child_words;
  aggregate->slots_by_board_size[spec.board_size] += stats.point_slots;
  aggregate->result_sha256 = ugts_go19::Sha256Hex(
      aggregate->result_sha256 + material);
}

Aggregate RunMode(const std::vector<BatchSpec>& workload,
                  const std::vector<CorpusEntry>& corpus,
                  bool nondefault_stream) {
  Aggregate aggregate;
  aggregate.result_sha256 =
      ugts_go19::Sha256Hex("UGTS-CUDA-LOCAL-SCALE-RESULT-v1");
  cudaStream_t stream = nullptr;
  if (nondefault_stream) {
    CheckCuda(cudaStreamCreateWithFlags(&stream, cudaStreamNonBlocking),
              "cudaStreamCreateWithFlags");
  }
  const auto started = std::chrono::steady_clock::now();
  try {
    for (std::size_t ordinal = 0; ordinal < workload.size(); ++ordinal) {
      const auto& spec = workload[ordinal];
      const auto rules = RulesFor(spec.board_size);
      std::vector<ugts_go19::State> states;
      states.reserve(spec.corpus_ids.size());
      for (std::size_t id : spec.corpus_ids) states.push_back(corpus[id].state);

      std::size_t free_bytes = 0;
      std::size_t total_bytes = 0;
      CheckCuda(cudaMemGetInfo(&free_bytes, &total_bytes), "cudaMemGetInfo");
      if (total_bytes == 0U || free_bytes > total_bytes) {
        throw std::runtime_error("cudaMemGetInfo returned inconsistent totals");
      }
      const std::uint64_t requested =
          static_cast<std::uint64_t>(
              ugts_go19::cuda::LocalPointDeviceBytesPerState(spec.board_size)) *
              static_cast<std::uint64_t>(states.size()) +
          sizeof(std::uint32_t);
      const std::uint64_t budget = WorkspaceBudget(free_bytes);
      if (requested > budget) {
        throw std::runtime_error(
            "scale batch exceeds adapter workspace budget before launch");
      }
      aggregate.high_water_requested_device_bytes =
          std::max(aggregate.high_water_requested_device_bytes, requested);
      aggregate.minimum_free_device_bytes_before_batch =
          std::min(aggregate.minimum_free_device_bytes_before_batch,
                   static_cast<std::uint64_t>(free_bytes));
      aggregate.minimum_adapter_workspace_budget_bytes =
          std::min(aggregate.minimum_adapter_workspace_budget_bytes, budget);

      const auto verified =
          ugts_go19::cuda::VerifyCudaLocalPointTransitions(states, rules, stream);
      CheckBatchInvariants(spec, corpus, verified,
                           static_cast<std::uint64_t>(ordinal), &aggregate);
      ++aggregate.batch_calls;
    }
    if (stream != nullptr) {
      CheckCuda(cudaStreamDestroy(stream), "cudaStreamDestroy");
      stream = nullptr;
    }
  } catch (...) {
    if (stream != nullptr) static_cast<void>(cudaStreamDestroy(stream));
    throw;
  }
  const auto stopped = std::chrono::steady_clock::now();
  aggregate.elapsed_seconds =
      std::chrono::duration<double>(stopped - started).count();
  if (!(aggregate.elapsed_seconds > 0.0)) {
    throw std::runtime_error("non-positive elapsed time");
  }
  return aggregate;
}

template <typename Function>
void ExpectFailure(Function&& function, const char* label,
                   std::uint64_t* checks) {
  try {
    function();
  } catch (const std::exception&) {
    ++*checks;
    return;
  }
  throw std::runtime_error(std::string("negative check did not fail: ") + label);
}

std::uint64_t RunNegativeChecks() {
  const auto rules = RulesFor(3);
  const auto initial = ugts_go19::State::Initial(rules);
  std::uint64_t checks = 0;
  ExpectFailure(
      [&] {
        static_cast<void>(ugts_go19::cuda::VerifyCudaLocalPointTransitions(
            {}, rules));
      },
      "empty batch", &checks);
  auto suicide_rules = rules;
  suicide_rules.allow_suicide = true;
  ExpectFailure(
      [&] {
        static_cast<void>(ugts_go19::cuda::VerifyCudaLocalPointTransitions(
            {initial}, suicide_rules));
      },
      "suicide rules", &checks);
  auto terminal = initial;
  terminal.passes = rules.passes_to_end;
  ExpectFailure(
      [&] {
        static_cast<void>(ugts_go19::cuda::VerifyCudaLocalPointTransitions(
            {terminal}, rules));
      },
      "terminal state", &checks);
  auto exhausted = initial;
  exhausted.ply = std::numeric_limits<std::uint64_t>::max();
  ExpectFailure(
      [&] {
        static_cast<void>(ugts_go19::cuda::VerifyCudaLocalPointTransitions(
            {exhausted}, rules));
      },
      "ply exhaustion", &checks);
  auto invalid_player = initial;
  invalid_player.to_play = 7;
  ExpectFailure(
      [&] {
        static_cast<void>(ugts_go19::cuda::VerifyCudaLocalPointTransitions(
            {invalid_player}, rules));
      },
      "invalid player", &checks);
  auto duplicate_history = initial;
  duplicate_history.seen_boards.push_back(initial.board);
  ExpectFailure(
      [&] {
        static_cast<void>(ugts_go19::cuda::VerifyCudaLocalPointTransitions(
            {duplicate_history}, rules));
      },
      "duplicate history", &checks);
  auto missing_current = initial;
  missing_current.seen_boards.clear();
  ExpectFailure(
      [&] {
        static_cast<void>(ugts_go19::cuda::VerifyCudaLocalPointTransitions(
            {missing_current}, rules));
      },
      "missing current board", &checks);
  return checks;
}

bool SameExactTotals(const Aggregate& left, const Aggregate& right) {
  return left.states == right.states &&
         left.point_slots == right.point_slots &&
         left.occupied == right.occupied && left.suicides == right.suicides &&
         left.local_candidates == right.local_candidates &&
         left.superko_rejections == right.superko_rejections &&
         left.globally_legal_children == right.globally_legal_children &&
         left.compared_child_words == right.compared_child_words &&
         left.capture_slots == right.capture_slots &&
         left.captured_stones == right.captured_stones &&
         left.batch_calls == right.batch_calls &&
         left.maximum_capture == right.maximum_capture &&
         left.slots_by_board_size == right.slots_by_board_size &&
         left.slots_by_category == right.slots_by_category &&
         left.result_sha256 == right.result_sha256;
}

std::string JsonEscape(std::string_view value) {
  std::string output;
  for (unsigned char byte : value) {
    switch (byte) {
      case '"':
        output += "\\\"";
        break;
      case '\\':
        output += "\\\\";
        break;
      case '\b':
        output += "\\b";
        break;
      case '\f':
        output += "\\f";
        break;
      case '\n':
        output += "\\n";
        break;
      case '\r':
        output += "\\r";
        break;
      case '\t':
        output += "\\t";
        break;
      default:
        if (byte < 0x20U) {
          constexpr char digits[] = "0123456789abcdef";
          output += "\\u00";
          output.push_back(digits[byte >> 4U]);
          output.push_back(digits[byte & 0x0fU]);
        } else {
          output.push_back(static_cast<char>(byte));
        }
    }
  }
  return output;
}

template <typename Key>
void PrintMap(const std::map<Key, std::uint64_t>& values) {
  std::cout << '{';
  bool first = true;
  for (const auto& [key, value] : values) {
    if (!first) std::cout << ',';
    first = false;
    std::ostringstream key_stream;
    key_stream.imbue(std::locale::classic());
    key_stream << key;
    std::cout << '"' << JsonEscape(key_stream.str()) << "\":" << value;
  }
  std::cout << '}';
}

std::string HostCompiler() {
#if defined(_MSC_FULL_VER)
  return "MSVC-" + std::to_string(_MSC_FULL_VER);
#elif defined(__clang__)
  return "Clang-" + std::to_string(__clang_major__) + "." +
         std::to_string(__clang_minor__) + "." +
         std::to_string(__clang_patchlevel__);
#elif defined(__GNUC__)
  return "GCC-" + std::to_string(__GNUC__) + "." +
         std::to_string(__GNUC_MINOR__) + "." +
         std::to_string(__GNUC_PATCHLEVEL__);
#else
  return "unknown";
#endif
}

std::string CudaCompiler() {
#if defined(__CUDACC_VER_MAJOR__) && defined(__CUDACC_VER_MINOR__) && \
    defined(__CUDACC_VER_BUILD__)
  return "NVCC-" + std::to_string(__CUDACC_VER_MAJOR__) + "." +
         std::to_string(__CUDACC_VER_MINOR__) + "." +
         std::to_string(__CUDACC_VER_BUILD__);
#else
  return "unknown";
#endif
}

void PrintMode(std::string_view name, const Aggregate& aggregate) {
  std::cout << '"' << name << "\":{\"adapter_batch_calls\":"
            << aggregate.batch_calls
            << ",\"capture_slots\":" << aggregate.capture_slots
            << ",\"captured_stones\":" << aggregate.captured_stones
            << ",\"compared_child_words\":"
            << aggregate.compared_child_words
            << ",\"elapsed_seconds\":" << std::fixed
            << std::setprecision(6) << aggregate.elapsed_seconds
            << ",\"globally_legal_children\":"
            << aggregate.globally_legal_children
            << ",\"high_water_requested_device_bytes\":"
            << aggregate.high_water_requested_device_bytes
            << ",\"local_candidates\":" << aggregate.local_candidates
            << ",\"maximum_capture\":" << aggregate.maximum_capture
            << ",\"minimum_adapter_workspace_budget_bytes\":"
            << aggregate.minimum_adapter_workspace_budget_bytes
            << ",\"minimum_free_device_bytes_before_batch\":"
            << aggregate.minimum_free_device_bytes_before_batch
            << ",\"occupied_slots\":" << aggregate.occupied
            << ",\"point_slots\":" << aggregate.point_slots
            << ",\"result_sha256\":\"" << aggregate.result_sha256
            << "\",\"semantic_state_visits\":" << aggregate.states
            << ",\"slots_by_board_size\":";
  PrintMap(aggregate.slots_by_board_size);
  std::cout << ",\"slots_by_category\":";
  PrintMap(aggregate.slots_by_category);
  std::cout << ",\"slots_per_second\":" << std::fixed
            << std::setprecision(3)
            << static_cast<double>(aggregate.point_slots) /
                   aggregate.elapsed_seconds
            << ",\"suicide_slots\":" << aggregate.suicides
            << ",\"superko_rejections\":"
            << aggregate.superko_rejections << '}';
}

}  // namespace

int main(int argc, char** argv) {
  std::ios::sync_with_stdio(false);
  std::cout.imbue(std::locale::classic());
  std::cerr.imbue(std::locale::classic());
  try {
    const Options options = ParseOptions(argc, argv);
    int device_count = 0;
    CheckCuda(cudaGetDeviceCount(&device_count), "cudaGetDeviceCount");
    if (device_count < 1) throw std::runtime_error("no CUDA device available");
    CheckCuda(cudaSetDevice(0), "cudaSetDevice");
    cudaDeviceProp properties{};
    CheckCuda(cudaGetDeviceProperties(&properties, 0),
              "cudaGetDeviceProperties");
    int runtime_version = 0;
    int driver_version = 0;
    CheckCuda(cudaRuntimeGetVersion(&runtime_version), "cudaRuntimeGetVersion");
    CheckCuda(cudaDriverGetVersion(&driver_version), "cudaDriverGetVersion");

    const std::uint64_t negative_checks = RunNegativeChecks();
    const auto corpus =
        BuildCorpus(options.seed, options.target_unique_corpus_slots);
    const std::uint64_t corpus_slots = CorpusSlots(corpus);
    if (corpus_slots < options.target_unique_corpus_slots) {
      throw std::runtime_error("unique corpus did not reach requested slots");
    }
    const auto workload = BuildWorkload(corpus, options.batch_states);
    const Aggregate default_mode = RunMode(workload, corpus, false);
    const Aggregate nondefault_mode = RunMode(workload, corpus, true);
    if (!SameExactTotals(default_mode, nondefault_mode)) {
      throw std::runtime_error("default/nondefault exact scale totals differ");
    }
    const std::uint64_t total_slots =
        default_mode.point_slots + nondefault_mode.point_slots;
    if (default_mode.point_slots != corpus_slots ||
        nondefault_mode.point_slots != corpus_slots) {
      throw std::runtime_error("a stream mode did not traverse the unique corpus");
    }
    if (default_mode.occupied == 0U || default_mode.suicides == 0U ||
        default_mode.local_candidates == 0U ||
        default_mode.superko_rejections == 0U ||
        default_mode.globally_legal_children == 0U ||
        default_mode.maximum_capture != 360U) {
      throw std::runtime_error("required adversarial status coverage is absent");
    }
    if (options.target_unique_corpus_slots >=
            kDefaultTargetUniqueCorpusSlots &&
        (default_mode.slots_by_category.at("campaign-shaped-19x19") <
             500'000U ||
         default_mode.slots_by_category.at(
             "randomized-ordinal-dense-19x19") < 9'000'000U)) {
      throw std::runtime_error("full-scale corpus breadth categories are too small");
    }

    std::cout << '{'
              << "\"batch_state_limit\":" << options.batch_states
#ifdef NDEBUG
              << ",\"build_configuration\":\"Release\""
#else
              << ",\"build_configuration\":\"Debug\""
#endif
              << ",\"compiler\":{\"cuda\":\""
              << JsonEscape(CudaCompiler()) << "\",\"host\":\""
              << JsonEscape(HostCompiler()) << "\"}"
              << ",\"corpus_entries\":" << corpus.size()
              << ",\"unique_corpus_point_slots\":" << corpus_slots
              << ",\"corpus_sha256\":\"" << CorpusSha256(corpus, options.seed)
              << "\",\"cuda_driver_version\":" << driver_version
              << ",\"cuda_runtime_version\":" << runtime_version
              << ",\"device\":{\"compute_capability\":\""
              << properties.major << '.' << properties.minor
              << "\",\"name\":\"" << JsonEscape(properties.name)
              << "\",\"total_global_memory_bytes\":"
              << static_cast<std::uint64_t>(properties.totalGlobalMem) << '}'
              << ",\"format\":\"ugts-go19-cuda-local-transition-scale-v1\""
              << ",\"measurement_label\":\"hardware-specific non-proof "
                 "end-to-end adapter verification and summary consumption\""
              << ",\"mismatches\":0,\"modes\":{";
    PrintMode("default", default_mode);
    std::cout << ',';
    PrintMode("nondefault", nondefault_mode);
    std::cout << "},\"negative_fail_closed_checks\":" << negative_checks
              << ",\"python_compared_point_slots\":0"
              << ",\"root_status\":\"UNKNOWN\""
              << ",\"scope\":\"C++/CUDA pre-superko local point transitions; "
                 "CPU ApplyMove authority; no proof-search integration\""
              << ",\"seed\":" << options.seed
              << ",\"stream_modes\":[\"default\",\"nondefault\"]"
              << ",\"target_unique_corpus_point_slots\":"
              << options.target_unique_corpus_slots
              << ",\"primary_unique_mode_cpp_cuda_cpu_recomputed_point_slots\":"
              << default_mode.point_slots
              << ",\"additional_stream_mode_recomputed_point_slots\":"
              << nondefault_mode.point_slots
              << ",\"total_cpp_cuda_cpu_recomputed_point_slots_across_modes\":"
              << total_slots
              << ",\"unique_semantic_states\":" << corpus.size() << "}\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "ugts_go_cuda_local_transition_scale: " << error.what()
              << '\n';
    return 1;
  }
}
