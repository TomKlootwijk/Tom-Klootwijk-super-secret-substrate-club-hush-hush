#include "packed_kernels.cuh"

#include <cuda_runtime.h>

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

constexpr std::size_t kBoardSize = 19U;
constexpr std::size_t kPoints = 361U;
constexpr std::size_t kWords = 6U;
constexpr std::uint64_t kTailMask = (UINT64_C(1) << 41U) - 1U;
constexpr std::size_t kGridCapacityCandidates =
    ugts_go19::cuda::kLocalPointMaximumBlocks *
    (ugts_go19::cuda::kLocalPointThreadsPerBlock / 32U);
constexpr std::size_t kGridStrideStates =
    kGridCapacityCandidates / kPoints + 1U;
constexpr std::size_t kGridStrideCandidates = kGridStrideStates * kPoints;
static_assert(kGridStrideCandidates > kGridCapacityCandidates);

void CheckCuda(cudaError_t status, const char *operation) {
  if (status != cudaSuccess) {
    throw std::runtime_error(std::string(operation) + ": " +
                             cudaGetErrorString(status));
  }
}

template <typename T>
constexpr T LeftCanary() {
  return static_cast<T>(0xa5U);
}

template <>
constexpr std::uint64_t LeftCanary<std::uint64_t>() {
  return UINT64_C(0x13579bdf2468ace0);
}

template <typename T>
constexpr T RightCanary() {
  return static_cast<T>(0x5aU);
}

template <>
constexpr std::uint64_t RightCanary<std::uint64_t>() {
  return UINT64_C(0xfdb97531eca86420);
}

template <typename T>
class GuardedBuffer {
 public:
  GuardedBuffer(std::size_t count, T fill) : count_(count) {
    if (count == 0U || count >
                           std::numeric_limits<std::size_t>::max() /
                               sizeof(T) - 2U) {
      throw std::invalid_argument("invalid guarded-buffer size");
    }
    const std::size_t bytes = (count + 2U) * sizeof(T);
    CheckCuda(cudaMalloc(reinterpret_cast<void **>(&device_), bytes),
              "cudaMalloc guarded buffer");
    try {
      CheckCuda(cudaMallocHost(reinterpret_cast<void **>(&host_), bytes),
                "cudaMallocHost guarded buffer");
    } catch (...) {
      static_cast<void>(cudaFree(device_));
      device_ = nullptr;
      throw;
    }
    std::fill(host_, host_ + count + 2U, fill);
    host_[0] = LeftCanary<T>();
    host_[count + 1U] = RightCanary<T>();
  }

  GuardedBuffer(const GuardedBuffer &) = delete;
  GuardedBuffer &operator=(const GuardedBuffer &) = delete;

  ~GuardedBuffer() {
    if (device_ != nullptr && cudaFree(device_) != cudaSuccess) std::abort();
    if (host_ != nullptr && cudaFreeHost(host_) != cudaSuccess) std::abort();
  }

  [[nodiscard]] T *device_data() const { return device_ + 1U; }
  [[nodiscard]] T *host_data() const { return host_ + 1U; }
  [[nodiscard]] std::size_t count() const { return count_; }

  void Upload(cudaStream_t stream) {
    CheckCuda(cudaMemcpyAsync(device_, host_, (count_ + 2U) * sizeof(T),
                              cudaMemcpyHostToDevice, stream),
              "cudaMemcpyAsync guarded upload");
  }

  void Download(cudaStream_t stream) {
    CheckCuda(cudaMemcpyAsync(host_, device_, (count_ + 2U) * sizeof(T),
                              cudaMemcpyDeviceToHost, stream),
              "cudaMemcpyAsync guarded download");
  }

  void CheckCanaries(std::size_t *checks) const {
    if (host_[0] != LeftCanary<T>() ||
        host_[count_ + 1U] != RightCanary<T>()) {
      throw std::runtime_error("guard canary changed");
    }
    *checks += 2U;
  }

 private:
  std::size_t count_ = 0;
  T *device_ = nullptr;
  T *host_ = nullptr;
};

class OwnedStream {
 public:
  OwnedStream() {
    CheckCuda(cudaStreamCreateWithFlags(&stream_, cudaStreamNonBlocking),
              "cudaStreamCreateWithFlags");
  }
  OwnedStream(const OwnedStream &) = delete;
  OwnedStream &operator=(const OwnedStream &) = delete;
  ~OwnedStream() {
    if (stream_ != nullptr && cudaStreamDestroy(stream_) != cudaSuccess) {
      std::abort();
    }
  }
  [[nodiscard]] cudaStream_t get() const { return stream_; }

 private:
  cudaStream_t stream_ = nullptr;
};

struct RawBatch {
  explicit RawBatch(std::size_t state_count)
      : states(state_count),
        candidates(state_count * kPoints),
        state_words(state_count * kWords),
        child_words(candidates * kWords),
        black(state_words, UINT64_C(0)),
        white(state_words, UINT64_C(0)),
        to_play(states, static_cast<std::uint8_t>(0)),
        empty(state_words, UINT64_C(0xcccccccccccccccc)),
        status(candidates, static_cast<std::uint8_t>(0xcc)),
        captured(candidates, static_cast<std::uint16_t>(0xcccc)),
        self_captured(candidates, static_cast<std::uint16_t>(0xcccc)),
        child_black(child_words, UINT64_C(0xcccccccccccccccc)),
        child_white(child_words, UINT64_C(0xcccccccccccccccc)),
        errors(1U, UINT32_C(0xcccccccc)) {
    if (state_count == 0U) throw std::invalid_argument("empty raw batch");
  }

  void Upload(cudaStream_t stream) {
    black.Upload(stream);
    white.Upload(stream);
    to_play.Upload(stream);
    empty.Upload(stream);
    status.Upload(stream);
    captured.Upload(stream);
    self_captured.Upload(stream);
    child_black.Upload(stream);
    child_white.Upload(stream);
    errors.Upload(stream);
  }

  void Launch(cudaStream_t stream, bool alias_inputs = false) {
    ugts_go19::cuda::LaunchLocalPointTransitions(
        black.device_data(),
        alias_inputs ? black.device_data() : white.device_data(),
        to_play.device_data(), empty.device_data(), status.device_data(),
        captured.device_data(), self_captured.device_data(),
        child_black.device_data(), child_white.device_data(),
        errors.device_data(), states, static_cast<int>(kBoardSize), stream);
  }

  void Download(cudaStream_t stream) {
    black.Download(stream);
    white.Download(stream);
    to_play.Download(stream);
    empty.Download(stream);
    status.Download(stream);
    captured.Download(stream);
    self_captured.Download(stream);
    child_black.Download(stream);
    child_white.Download(stream);
    errors.Download(stream);
  }

  void CheckAllCanaries(std::size_t *checks) const {
    black.CheckCanaries(checks);
    white.CheckCanaries(checks);
    to_play.CheckCanaries(checks);
    empty.CheckCanaries(checks);
    status.CheckCanaries(checks);
    captured.CheckCanaries(checks);
    self_captured.CheckCanaries(checks);
    child_black.CheckCanaries(checks);
    child_white.CheckCanaries(checks);
    errors.CheckCanaries(checks);
  }

  std::size_t states;
  std::size_t candidates;
  std::size_t state_words;
  std::size_t child_words;
  GuardedBuffer<std::uint64_t> black;
  GuardedBuffer<std::uint64_t> white;
  GuardedBuffer<std::uint8_t> to_play;
  GuardedBuffer<std::uint64_t> empty;
  GuardedBuffer<std::uint8_t> status;
  GuardedBuffer<std::uint16_t> captured;
  GuardedBuffer<std::uint16_t> self_captured;
  GuardedBuffer<std::uint64_t> child_black;
  GuardedBuffer<std::uint64_t> child_white;
  GuardedBuffer<std::uint32_t> errors;
};

void FillEmptyBoards(RawBatch *batch, std::uint8_t first_player) {
  for (std::size_t state = 0; state < batch->states; ++state) {
    batch->to_play.host_data()[state] =
        static_cast<std::uint8_t>(first_player == 1U ? 1U + (state & 1U) : 2U);
  }
}

void VerifyInputUnchanged(const RawBatch &batch,
                          const std::vector<std::uint64_t> &black,
                          const std::vector<std::uint64_t> &white,
                          const std::vector<std::uint8_t> &players,
                          std::size_t *comparisons) {
  if (!std::equal(black.begin(), black.end(), batch.black.host_data()) ||
      !std::equal(white.begin(), white.end(), batch.white.host_data()) ||
      !std::equal(players.begin(), players.end(), batch.to_play.host_data())) {
    throw std::runtime_error("local transition modified an input buffer");
  }
  *comparisons += black.size() + white.size() + players.size();
}

void VerifyEmptyBatch(const RawBatch &batch, bool alias_inputs,
                      std::size_t *word_comparisons) {
  if (batch.errors.host_data()[0] != 0U) {
    throw std::runtime_error("valid empty batch reported error bits");
  }
  for (std::size_t candidate = 0; candidate < batch.candidates; ++candidate) {
    if (batch.status.host_data()[candidate] !=
            static_cast<std::uint8_t>(
                ugts_go19::cuda::LocalPointStatus::kCandidateNeedsSuperko) ||
        batch.captured.host_data()[candidate] != 0U ||
        batch.self_captured.host_data()[candidate] != 0U) {
      throw std::runtime_error("empty-board local candidate metadata mismatch");
    }
    const std::size_t move = candidate % kPoints;
    const std::size_t state = candidate / kPoints;
    const std::size_t base = candidate * kWords;
    const std::size_t move_word = move / 64U;
    const std::uint64_t move_bit = UINT64_C(1) << (move % 64U);
    const std::uint8_t player = batch.to_play.host_data()[state];
    for (std::size_t word = 0; word < kWords; ++word) {
      const std::uint64_t expected = word == move_word ? move_bit : 0U;
      const std::uint64_t expected_black = player == 1U ? expected : 0U;
      const std::uint64_t expected_white = player == 2U ? expected : 0U;
      if (batch.child_black.host_data()[base + word] != expected_black ||
          batch.child_white.host_data()[base + word] != expected_white) {
        throw std::runtime_error("empty-board child plane mismatch");
      }
      *word_comparisons += 2U;
    }
  }
  if (alias_inputs && batch.states != 1U) {
    throw std::runtime_error("aliased-input fixture shape changed");
  }
}

void VerifyInvalidBatch(const RawBatch &batch) {
  if ((batch.errors.host_data()[0] &
       ugts_go19::cuda::kLocalPointInvalidInputError) == 0U) {
    throw std::runtime_error("invalid batch omitted its fatal error bit");
  }
  for (std::size_t candidate = 0; candidate < batch.candidates; ++candidate) {
    if (batch.status.host_data()[candidate] !=
            static_cast<std::uint8_t>(
                ugts_go19::cuda::LocalPointStatus::kInvalidInput) ||
        batch.captured.host_data()[candidate] != 0U ||
        batch.self_captured.host_data()[candidate] != 0U) {
      throw std::runtime_error("invalid batch did not fail every slot closed");
    }
  }
  if (std::any_of(batch.child_black.host_data(),
                  batch.child_black.host_data() + batch.child_words,
                  [](std::uint64_t value) { return value != 0U; }) ||
      std::any_of(batch.child_white.host_data(),
                  batch.child_white.host_data() + batch.child_words,
                  [](std::uint64_t value) { return value != 0U; })) {
    throw std::runtime_error("invalid batch emitted child payload");
  }
}

void VerifyOccupiedGridBatch(const RawBatch &batch,
                             std::size_t *slot_comparisons) {
  if (batch.errors.host_data()[0] != 0U) {
    throw std::runtime_error("grid-stride occupied batch reported error bits");
  }
  for (std::size_t candidate = 0; candidate < batch.candidates; ++candidate) {
    if (batch.status.host_data()[candidate] !=
            static_cast<std::uint8_t>(
                ugts_go19::cuda::LocalPointStatus::kOccupied) ||
        batch.captured.host_data()[candidate] != 0U ||
        batch.self_captured.host_data()[candidate] != 0U) {
      throw std::runtime_error("grid-stride occupied slot mismatch");
    }
    ++*slot_comparisons;
  }
  if (std::any_of(batch.child_black.host_data(),
                  batch.child_black.host_data() + batch.child_words,
                  [](std::uint64_t value) { return value != 0U; }) ||
      std::any_of(batch.child_white.host_data(),
                  batch.child_white.host_data() + batch.child_words,
                  [](std::uint64_t value) { return value != 0U; })) {
    throw std::runtime_error("grid-stride occupied batch emitted child payload");
  }
}

std::vector<std::uint64_t> CopyWords(const GuardedBuffer<std::uint64_t> &buffer) {
  return std::vector<std::uint64_t>(buffer.host_data(),
                                    buffer.host_data() + buffer.count());
}

std::vector<std::uint8_t> CopyBytes(const GuardedBuffer<std::uint8_t> &buffer) {
  return std::vector<std::uint8_t>(buffer.host_data(),
                                   buffer.host_data() + buffer.count());
}

}  // namespace

int main() {
  try {
    int device_count = 0;
    CheckCuda(cudaGetDeviceCount(&device_count), "cudaGetDeviceCount");
    if (device_count < 1) throw std::runtime_error("no CUDA device is available");
    CheckCuda(cudaSetDevice(0), "cudaSetDevice");
    cudaDeviceProp properties{};
    CheckCuda(cudaGetDeviceProperties(&properties, 0),
              "cudaGetDeviceProperties");

    std::size_t canary_checks = 0;
    std::size_t input_immutability_comparisons = 0;
    std::size_t child_word_comparisons = 0;
    std::size_t grid_stride_slot_comparisons = 0;

    OwnedStream first_stream;
    OwnedStream second_stream;
    RawBatch first(2U);
    RawBatch second(2U);
    FillEmptyBoards(&first, 1U);
    FillEmptyBoards(&second, 2U);
    const auto first_black = CopyWords(first.black);
    const auto first_white = CopyWords(first.white);
    const auto first_players = CopyBytes(first.to_play);
    const auto second_black = CopyWords(second.black);
    const auto second_white = CopyWords(second.white);
    const auto second_players = CopyBytes(second.to_play);
    first.Upload(first_stream.get());
    second.Upload(second_stream.get());
    first.Launch(first_stream.get());
    second.Launch(second_stream.get());
    first.Download(first_stream.get());
    second.Download(second_stream.get());
    // Deliberately synchronize in reverse launch order.
    CheckCuda(cudaStreamSynchronize(second_stream.get()),
              "cudaStreamSynchronize second");
    CheckCuda(cudaStreamSynchronize(first_stream.get()),
              "cudaStreamSynchronize first");
    first.CheckAllCanaries(&canary_checks);
    second.CheckAllCanaries(&canary_checks);
    VerifyInputUnchanged(first, first_black, first_white, first_players,
                         &input_immutability_comparisons);
    VerifyInputUnchanged(second, second_black, second_white, second_players,
                         &input_immutability_comparisons);
    VerifyEmptyBatch(first, false, &child_word_comparisons);
    VerifyEmptyBatch(second, false, &child_word_comparisons);

    OwnedStream invalid_stream;
    RawBatch invalid(3U);
    invalid.to_play.host_data()[0] = 1U;
    invalid.to_play.host_data()[1] = 2U;
    invalid.to_play.host_data()[2] = 3U;
    invalid.black.host_data()[5] = UINT64_C(1) << 63U;
    invalid.black.host_data()[6] = 1U;
    invalid.white.host_data()[6] = 1U;
    const auto invalid_black = CopyWords(invalid.black);
    const auto invalid_white = CopyWords(invalid.white);
    const auto invalid_players = CopyBytes(invalid.to_play);
    invalid.Upload(invalid_stream.get());
    invalid.Launch(invalid_stream.get());
    invalid.Download(invalid_stream.get());
    CheckCuda(cudaStreamSynchronize(invalid_stream.get()),
              "cudaStreamSynchronize invalid");
    invalid.CheckAllCanaries(&canary_checks);
    VerifyInputUnchanged(invalid, invalid_black, invalid_white, invalid_players,
                         &input_immutability_comparisons);
    VerifyInvalidBatch(invalid);

    OwnedStream alias_stream;
    RawBatch aliased(1U);
    aliased.to_play.host_data()[0] = 1U;
    const auto alias_black = CopyWords(aliased.black);
    const auto alias_white = CopyWords(aliased.white);
    const auto alias_players = CopyBytes(aliased.to_play);
    aliased.Upload(alias_stream.get());
    aliased.Launch(alias_stream.get(), true);
    aliased.Download(alias_stream.get());
    CheckCuda(cudaStreamSynchronize(alias_stream.get()),
              "cudaStreamSynchronize alias");
    aliased.CheckAllCanaries(&canary_checks);
    VerifyInputUnchanged(aliased, alias_black, alias_white, alias_players,
                         &input_immutability_comparisons);
    VerifyEmptyBatch(aliased, true, &child_word_comparisons);

    OwnedStream grid_stream;
    RawBatch grid(kGridStrideStates);
    for (std::size_t state = 0; state < grid.states; ++state) {
      const std::size_t base = state * kWords;
      for (std::size_t word = 0; word + 1U < kWords; ++word) {
        grid.black.host_data()[base + word] = UINT64_MAX;
      }
      grid.black.host_data()[base + kWords - 1U] = kTailMask;
      grid.to_play.host_data()[state] = 2U;
    }
    const auto grid_black = CopyWords(grid.black);
    const auto grid_white = CopyWords(grid.white);
    const auto grid_players = CopyBytes(grid.to_play);
    grid.Upload(grid_stream.get());
    grid.Launch(grid_stream.get());
    grid.Download(grid_stream.get());
    CheckCuda(cudaStreamSynchronize(grid_stream.get()),
              "cudaStreamSynchronize grid stride");
    grid.CheckAllCanaries(&canary_checks);
    VerifyInputUnchanged(grid, grid_black, grid_white, grid_players,
                         &input_immutability_comparisons);
    VerifyOccupiedGridBatch(grid, &grid_stride_slot_comparisons);

    std::cout
        << "{\"aliased_input_launches\":1,\"canary_checks\":"
        << canary_checks << ",\"child_word_comparisons\":"
        << child_word_comparisons
        << ",\"compute_capability\":\"" << properties.major << '.'
        << properties.minor
        << "\",\"dirty_tail_states\":1,\"dual_stream_launches\":2,"
           "\"grid_stride_candidates\":"
        << kGridStrideCandidates << ",\"grid_stride_extra_candidates\":"
        << kGridStrideCandidates - kGridCapacityCandidates
        << ",\"grid_stride_slot_comparisons\":"
        << grid_stride_slot_comparisons
        << ",\"input_immutability_comparisons\":"
        << input_immutability_comparisons
        << ",\"invalid_player_states\":1,\"mismatches\":0,"
           "\"overlapping_plane_states\":1,\"reverse_sync_checks\":1,"
           "\"production_grid_capacity_candidates\":"
        << kGridCapacityCandidates << ",\"root_status\":\"UNKNOWN\"}\n";
    return 0;
  } catch (const std::exception &error) {
    std::cerr << "ugts_go_cuda_local_transition_guards: " << error.what()
              << '\n';
    return 1;
  }
}
