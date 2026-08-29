#pragma once

#include <cstddef>
#include <cstdint>

namespace ugts_go19::cuda {

// These launch-shape constants are public so the exact differential gate can
// exercise the production grid-stride boundary rather than a test-only copy.
inline constexpr std::size_t kEmptyMaskThreadsPerBlock = 256U;
inline constexpr std::size_t kEmptyMaskMaximumBlocks = 65'535U;

inline constexpr std::size_t kLocalPointMaximumBoardSize = 19U;
inline constexpr std::size_t kLocalPointMaximumWords = 6U;
inline constexpr std::size_t kLocalPointThreadsPerBlock = 256U;
inline constexpr std::size_t kLocalPointMaximumBlocks = 65'535U;

// These values are a versioned device/host ABI.  In particular,
// kCandidateNeedsSuperko is deliberately not named "legal": positional
// superko, pass handling, metadata commit, and all proof updates remain on the
// exact CPU path.
enum class LocalPointStatus : std::uint8_t {
  kInvalidInput = 0,
  kOccupied = 1,
  kSuicide = 2,
  kCandidateNeedsSuperko = 3,
  kInternalFailure = 254,
  kUnwritten = 255,
};

inline constexpr std::uint32_t kLocalPointInvalidInputError = 1U << 0U;
inline constexpr std::uint32_t kLocalPointInternalError = 1U << 1U;

// Produce exact empty-point bitmasks from black/white bitplanes. This is only
// the occupancy stage. Capture, suicide, and superko guards remain mandatory
// before any candidate becomes a proof-authoritative move.
//
// `black`, `white`, and `empty` are device pointers. Words are state-major:
// state 0's `words_per_state` words come first, followed by state 1, and so on.
// Within a word, bit n represents point (word_index * 64 + n). `tail_mask` is
// applied only to the final word of every state; for a 19x19 board it is
// (UINT64_C(1) << 41) - 1. Input and output arrays must each contain at least
// `states * words_per_state` words. The output range must not overlap either
// input range; the two read-only input ranges may alias each other.
//
// The launch is asynchronous on the supplied CUDA stream (`nullptr` selects
// the default stream). Returning successfully means only that the launch was
// accepted. A caller must successfully synchronize the stream before trusting
// any output, and no output may affect proof state before that synchronization.
// `stream` is an opaque cudaStream_t value kept as void* so this public header
// does not require CUDA headers.
void LaunchEmptyMask(const std::uint64_t *black, const std::uint64_t *white,
                     std::uint64_t *empty, std::size_t states,
                     std::size_t words_per_state, std::uint64_t tail_mask,
                     void *stream);

// Produce deterministic, dense point-move transition candidates for boards of
// one through nineteen lines under the canonical no-suicide policy.  This
// launch performs only transition steps 1--6: occupancy, provisional
// placement, opponent-group capture, and the post-capture own-liberty guard.
// It does not process pass, terminal metadata, ply exhaustion, history, or
// positional superko.  A kCandidateNeedsSuperko result is therefore not a
// proof-authoritative legal move.
//
// The input black/white bitplanes and `empty_workspace` are state-major, using
// ceil(board_size*board_size/64) words per state. `to_play` contains one value
// per state (1 for Black, 2 for White). Output slots are fixed and state-major:
// slot = state * points + move. `status`, `captured`, and `self_captured` each
// contain one element per slot. Child planes are candidate-major, so slot q's
// words begin at q * words_per_state. Rejected slots have zero counts and zero
// child planes. `self_captured` is always zero because suicide is rejected.
// `batch_error_bits` contains the OR of fatal input/internal error flags.
//
// All pointers are device pointers. Every writable range must be disjoint from
// every other range and from all input ranges. The launch is asynchronous on
// `stream`; success means only that memset/occupancy/transition launches were
// accepted. The caller must successfully synchronize, require zero error bits,
// reject every kUnwritten/kInvalidInput/kInternalFailure slot, and perform
// exact CPU replay including raw-history superko before trusting any result.
void LaunchLocalPointTransitions(
    const std::uint64_t *black, const std::uint64_t *white,
    const std::uint8_t *to_play, std::uint64_t *empty_workspace,
    std::uint8_t *status, std::uint16_t *captured,
    std::uint16_t *self_captured, std::uint64_t *child_black,
    std::uint64_t *child_white, std::uint32_t *batch_error_bits,
    std::size_t states, int board_size, void *stream);

} // namespace ugts_go19::cuda
