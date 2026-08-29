#include "packed_kernels.cuh"

#include <cuda_runtime.h>

#include <algorithm>
#include <charconv>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <exception>
#include <iomanip>
#include <iostream>
#include <limits>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <utility>
#include <vector>

namespace {

constexpr std::uint64_t kLeftCanary = UINT64_C(0x13579bdf2468ace0);
constexpr std::uint64_t kRightCanary = UINT64_C(0xfdb97531eca86420);
constexpr std::uint64_t kOutputFill = UINT64_C(0xa55aa55a5aa55aa5);
constexpr std::size_t kMaximumProtocolCases = 1'024U;
constexpr std::size_t kMaximumProtocolWords = 10'000'000U;
constexpr std::size_t kGuardWords = 2U;
constexpr std::size_t kGridStrideExtraWords = 257U;
constexpr std::size_t kProductionGridCapacityWords =
    ugts_go19::cuda::kEmptyMaskMaximumBlocks *
    ugts_go19::cuda::kEmptyMaskThreadsPerBlock;
constexpr std::size_t kGridStrideRegressionWords =
    kProductionGridCapacityWords + kGridStrideExtraWords;
static_assert(kGridStrideRegressionWords > kProductionGridCapacityWords);

struct Fixture {
  std::string id;
  std::size_t states = 0;
  std::size_t words_per_state = 0;
  std::uint64_t tail_mask = 0;
  std::string mode;
  std::vector<std::uint64_t> black;
  std::vector<std::uint64_t> white;
};

void CheckCuda(cudaError_t status, const char *operation) {
  if (status != cudaSuccess) {
    throw std::runtime_error(std::string(operation) +
                             " failed: " + cudaGetErrorString(status));
  }
}

class DeviceWords {
public:
  DeviceWords() = default;
  DeviceWords(const DeviceWords &) = delete;
  DeviceWords &operator=(const DeviceWords &) = delete;

  ~DeviceWords() {
    if (data_ == nullptr)
      return;
    const cudaError_t status = cudaFree(data_);
    if (status != cudaSuccess) {
      std::cerr << "cudaFree during cleanup failed: "
                << cudaGetErrorString(status) << "\n";
      std::abort();
    }
  }

  void Allocate(std::size_t words) {
    if (data_ != nullptr || words == 0U ||
        words >
            std::numeric_limits<std::size_t>::max() / sizeof(std::uint64_t)) {
      throw std::invalid_argument("invalid device-buffer allocation");
    }
    CheckCuda(cudaMalloc(reinterpret_cast<void **>(&data_),
                         words * sizeof(std::uint64_t)),
              "cudaMalloc");
  }

  void Release() {
    std::uint64_t *value = data_;
    data_ = nullptr;
    if (value != nullptr)
      CheckCuda(cudaFree(value), "cudaFree");
  }

  [[nodiscard]] std::uint64_t *get() const { return data_; }

private:
  std::uint64_t *data_ = nullptr;
};

class PinnedWords {
public:
  PinnedWords() = default;
  PinnedWords(const PinnedWords &) = delete;
  PinnedWords &operator=(const PinnedWords &) = delete;

  ~PinnedWords() {
    if (data_ == nullptr)
      return;
    const cudaError_t status = cudaFreeHost(data_);
    if (status != cudaSuccess) {
      std::cerr << "cudaFreeHost during cleanup failed: "
                << cudaGetErrorString(status) << "\n";
      std::abort();
    }
  }

  void Allocate(std::size_t words) {
    if (data_ != nullptr || words == 0U ||
        words >
            std::numeric_limits<std::size_t>::max() / sizeof(std::uint64_t)) {
      throw std::invalid_argument("invalid pinned-buffer allocation");
    }
    CheckCuda(cudaMallocHost(reinterpret_cast<void **>(&data_),
                             words * sizeof(std::uint64_t)),
              "cudaMallocHost");
  }

  void Release() {
    std::uint64_t *value = data_;
    data_ = nullptr;
    if (value != nullptr)
      CheckCuda(cudaFreeHost(value), "cudaFreeHost");
  }

  [[nodiscard]] std::uint64_t *get() const { return data_; }

private:
  std::uint64_t *data_ = nullptr;
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
    if (stream_ == nullptr)
      return;
    const cudaError_t status = cudaStreamDestroy(stream_);
    if (status != cudaSuccess) {
      std::cerr << "cudaStreamDestroy during cleanup failed: "
                << cudaGetErrorString(status) << "\n";
      std::abort();
    }
  }

  void Release() {
    const cudaStream_t value = stream_;
    stream_ = nullptr;
    if (value != nullptr) {
      CheckCuda(cudaStreamDestroy(value), "cudaStreamDestroy");
    }
  }

  [[nodiscard]] cudaStream_t get() const { return stream_; }

private:
  cudaStream_t stream_ = nullptr;
};

[[nodiscard]] std::string ReadToken(std::istream &input,
                                    const char *description) {
  std::string token;
  if (!(input >> token)) {
    throw std::runtime_error(std::string("missing ") + description);
  }
  return token;
}

template <typename Unsigned>
[[nodiscard]] Unsigned ParseDecimal(const std::string &token,
                                    const char *description) {
  static_assert(std::is_unsigned_v<Unsigned>);
  if (token.empty() || (token.size() > 1U && token.front() == '0') ||
      !std::all_of(token.begin(), token.end(),
                   [](char value) { return value >= '0' && value <= '9'; })) {
    throw std::runtime_error(std::string("invalid ") + description);
  }
  Unsigned value = 0;
  const auto parsed =
      std::from_chars(token.data(), token.data() + token.size(), value, 10);
  if (parsed.ec != std::errc{} || parsed.ptr != token.data() + token.size()) {
    throw std::runtime_error(std::string("out-of-range ") + description);
  }
  return value;
}

[[nodiscard]] std::uint64_t ParseHexWord(const std::string &token,
                                         const char *description) {
  if (token.size() != 16U ||
      !std::all_of(token.begin(), token.end(), [](char value) {
        return (value >= '0' && value <= '9') || (value >= 'a' && value <= 'f');
      })) {
    throw std::runtime_error(std::string("invalid ") + description);
  }
  std::uint64_t value = 0;
  const auto parsed =
      std::from_chars(token.data(), token.data() + token.size(), value, 16);
  if (parsed.ec != std::errc{} || parsed.ptr != token.data() + token.size()) {
    throw std::runtime_error(std::string("out-of-range ") + description);
  }
  return value;
}

[[nodiscard]] std::size_t CheckedWords(std::size_t states,
                                       std::size_t words_per_state) {
  if (states == 0U || words_per_state == 0U ||
      states > std::numeric_limits<std::size_t>::max() / words_per_state) {
    throw std::runtime_error("invalid fixture shape");
  }
  return states * words_per_state;
}

[[nodiscard]] std::vector<Fixture> ReadFixtures(std::istream &input) {
  if (ReadToken(input, "protocol header") != "UGTS_EMPTY_MASK_INPUT_V1") {
    throw std::runtime_error("unsupported input protocol");
  }
  const std::size_t case_count =
      ParseDecimal<std::size_t>(ReadToken(input, "case count"), "case count");
  if (case_count == 0U || case_count > kMaximumProtocolCases) {
    throw std::runtime_error("case count is outside protocol bounds");
  }

  std::vector<Fixture> fixtures;
  fixtures.reserve(case_count);
  std::set<std::string> identifiers;
  std::size_t aggregate_words = 0;
  for (std::size_t case_index = 0; case_index < case_count; ++case_index) {
    if (ReadToken(input, "CASE marker") != "CASE") {
      throw std::runtime_error("expected CASE marker");
    }
    Fixture fixture;
    fixture.id = ReadToken(input, "case identifier");
    if (fixture.id.empty() ||
        !std::all_of(fixture.id.begin(), fixture.id.end(),
                     [](char value) {
                       return (value >= 'a' && value <= 'z') ||
                              (value >= '0' && value <= '9') || value == '_';
                     }) ||
        !identifiers.insert(fixture.id).second) {
      throw std::runtime_error("invalid or duplicate case identifier");
    }
    fixture.states = ParseDecimal<std::size_t>(ReadToken(input, "state count"),
                                               "state count");
    fixture.words_per_state = ParseDecimal<std::size_t>(
        ReadToken(input, "words per state"), "words per state");
    fixture.tail_mask =
        ParseHexWord(ReadToken(input, "tail mask"), "tail mask");
    fixture.mode = ReadToken(input, "stream mode");
    if (fixture.mode != "default" && fixture.mode != "nondefault" &&
        fixture.mode != "dual") {
      throw std::runtime_error("invalid stream mode");
    }

    const std::size_t words =
        CheckedWords(fixture.states, fixture.words_per_state);
    if (words > kMaximumProtocolWords ||
        aggregate_words > kMaximumProtocolWords - words) {
      throw std::runtime_error("fixture words exceed protocol bound");
    }
    aggregate_words += words;
    fixture.black.reserve(words);
    fixture.white.reserve(words);
    for (std::size_t index = 0; index < words; ++index) {
      if (ReadToken(input, "WORD marker") != "WORD") {
        throw std::runtime_error("expected WORD marker");
      }
      fixture.black.push_back(
          ParseHexWord(ReadToken(input, "black word"), "black word"));
      fixture.white.push_back(
          ParseHexWord(ReadToken(input, "white word"), "white word"));
    }
    fixtures.push_back(std::move(fixture));
  }
  if (ReadToken(input, "END marker") != "END") {
    throw std::runtime_error("expected END marker");
  }
  std::string trailing;
  if (input >> trailing)
    throw std::runtime_error("trailing protocol data");

  for (std::size_t index = 0; index < fixtures.size(); ++index) {
    if (fixtures[index].mode == "dual") {
      if (index + 1U >= fixtures.size() ||
          fixtures[index + 1U].mode != "dual") {
        throw std::runtime_error("dual cases must occur in adjacent pairs");
      }
      ++index;
    }
  }
  return fixtures;
}

[[nodiscard]] std::uint64_t ExpectedWord(const Fixture &fixture,
                                         std::size_t index) {
  std::uint64_t result = ~(fixture.black[index] | fixture.white[index]);
  if (index % fixture.words_per_state == fixture.words_per_state - 1U) {
    result &= fixture.tail_mask;
  }
  return result;
}

class PendingFixture {
public:
  explicit PendingFixture(const Fixture &fixture) : fixture_(fixture) {
    const std::size_t words = fixture_.black.size();
    if (words == 0U || fixture_.white.size() != words ||
        words > std::numeric_limits<std::size_t>::max() - kGuardWords) {
      throw std::invalid_argument("invalid pending fixture shape");
    }
    guarded_words_ = words + kGuardWords;
    host_black_.Allocate(guarded_words_);
    host_white_.Allocate(guarded_words_);
    host_output_.Allocate(guarded_words_);
    device_black_.Allocate(guarded_words_);
    device_white_.Allocate(guarded_words_);
    device_output_.Allocate(guarded_words_);

    std::fill_n(host_black_.get(), guarded_words_, kOutputFill);
    std::fill_n(host_white_.get(), guarded_words_, kOutputFill);
    std::fill_n(host_output_.get(), guarded_words_, kOutputFill);
    for (std::uint64_t *buffer :
         {host_black_.get(), host_white_.get(), host_output_.get()}) {
      buffer[0] = kLeftCanary;
      buffer[guarded_words_ - 1U] = kRightCanary;
    }
    std::copy(fixture_.black.begin(), fixture_.black.end(),
              host_black_.get() + 1);
    std::copy(fixture_.white.begin(), fixture_.white.end(),
              host_white_.get() + 1);
  }

  void Enqueue(cudaStream_t stream) {
    if (enqueued_) {
      throw std::logic_error("pending fixture was enqueued more than once");
    }
    const std::size_t guarded_bytes =
        guarded_words_ * sizeof(std::uint64_t);
    CheckCuda(cudaMemcpyAsync(device_black_.get(), host_black_.get(),
                              guarded_bytes, cudaMemcpyHostToDevice, stream),
              "cudaMemcpyAsync black H2D");
    CheckCuda(cudaMemcpyAsync(device_white_.get(), host_white_.get(),
                              guarded_bytes, cudaMemcpyHostToDevice, stream),
              "cudaMemcpyAsync white H2D");
    CheckCuda(cudaMemcpyAsync(device_output_.get(), host_output_.get(),
                              guarded_bytes, cudaMemcpyHostToDevice, stream),
              "cudaMemcpyAsync output initializer H2D");
    ugts_go19::cuda::LaunchEmptyMask(
        device_black_.get() + 1, device_white_.get() + 1,
        device_output_.get() + 1,
        fixture_.states, fixture_.words_per_state, fixture_.tail_mask,
        reinterpret_cast<void *>(stream));
    CheckCuda(cudaMemcpyAsync(host_output_.get(), device_output_.get(),
                              guarded_bytes, cudaMemcpyDeviceToHost, stream),
              "cudaMemcpyAsync output D2H");
    // Copy both const inputs back after the kernel. Exact comparison against
    // the immutable Fixture catches accidental writes as well as guard damage.
    CheckCuda(cudaMemcpyAsync(host_black_.get(), device_black_.get(),
                              guarded_bytes, cudaMemcpyDeviceToHost, stream),
              "cudaMemcpyAsync black D2H");
    CheckCuda(cudaMemcpyAsync(host_white_.get(), device_white_.get(),
                              guarded_bytes, cudaMemcpyDeviceToHost, stream),
              "cudaMemcpyAsync white D2H");
    enqueued_ = true;
  }

  [[nodiscard]] std::vector<std::uint64_t> ValidateAndRelease() {
    if (!enqueued_) {
      throw std::logic_error("pending fixture was not enqueued");
    }
    const auto check_canaries = [&](const std::uint64_t *buffer,
                                    const char *description) {
      if (buffer[0] != kLeftCanary ||
          buffer[guarded_words_ - 1U] != kRightCanary) {
        throw std::runtime_error(std::string(description) +
                                 " canary mismatch for " + fixture_.id);
      }
    };
    check_canaries(host_black_.get(), "black input");
    check_canaries(host_white_.get(), "white input");
    check_canaries(host_output_.get(), "output");

    const std::size_t words = fixture_.black.size();
    for (std::size_t index = 0; index < words; ++index) {
      if (host_black_.get()[index + 1U] != fixture_.black[index] ||
          host_white_.get()[index + 1U] != fixture_.white[index]) {
        throw std::runtime_error("input mutation for " + fixture_.id +
                                 " at index " + std::to_string(index));
      }
    }
    std::vector<std::uint64_t> result(host_output_.get() + 1,
                                      host_output_.get() + 1 + words);
    for (std::size_t index = 0; index < result.size(); ++index) {
      if (result[index] != ExpectedWord(fixture_, index)) {
        throw std::runtime_error("CPU/CUDA word mismatch for " + fixture_.id +
                                 " at index " + std::to_string(index));
      }
    }
    device_output_.Release();
    device_white_.Release();
    device_black_.Release();
    host_output_.Release();
    host_white_.Release();
    host_black_.Release();
    enqueued_ = false;
    return result;
  }

private:
  const Fixture &fixture_;
  std::size_t guarded_words_ = 0;
  bool enqueued_ = false;
  PinnedWords host_black_;
  PinnedWords host_white_;
  PinnedWords host_output_;
  DeviceWords device_black_;
  DeviceWords device_white_;
  DeviceWords device_output_;
};

[[nodiscard]] std::vector<std::uint64_t> RunSingleOnce(const Fixture &fixture) {
  PendingFixture pending(fixture);
  if (fixture.mode == "default") {
    pending.Enqueue(nullptr);
    CheckCuda(cudaStreamSynchronize(nullptr), "cudaStreamSynchronize default");
    return pending.ValidateAndRelease();
  }
  OwnedStream stream;
  pending.Enqueue(stream.get());
  CheckCuda(cudaStreamSynchronize(stream.get()),
            "cudaStreamSynchronize nondefault");
  std::vector<std::uint64_t> result = pending.ValidateAndRelease();
  stream.Release();
  return result;
}

[[nodiscard]] std::pair<std::vector<std::uint64_t>, std::vector<std::uint64_t>>
RunDualOnce(const Fixture &first, const Fixture &second) {
  OwnedStream first_stream;
  OwnedStream second_stream;
  // Allocate all device and pinned-host storage before either stream receives
  // work. This avoids legacy allocation synchronization and ensures both
  // independent batches are enqueued before either synchronization below.
  PendingFixture first_pending(first);
  PendingFixture second_pending(second);
  first_pending.Enqueue(first_stream.get());
  second_pending.Enqueue(second_stream.get());
  // Synchronize in reverse enqueue order to detect accidental output/stream
  // coupling between independent batches.
  CheckCuda(cudaStreamSynchronize(second_stream.get()),
            "cudaStreamSynchronize dual second");
  CheckCuda(cudaStreamSynchronize(first_stream.get()),
            "cudaStreamSynchronize dual first");
  auto second_result = second_pending.ValidateAndRelease();
  auto first_result = first_pending.ValidateAndRelease();
  second_stream.Release();
  first_stream.Release();
  return {std::move(first_result), std::move(second_result)};
}

struct DirectRegressionStats {
  std::size_t grid_stride_launches = 0;
  std::size_t grid_stride_words = 0;
  std::size_t aliased_input_launches = 0;
  std::size_t input_immutability_words = 0;
  std::size_t canary_checks = 0;
};

[[nodiscard]] std::uint64_t GridStridePattern(std::size_t index) {
  std::uint64_t value =
      static_cast<std::uint64_t>(index) + UINT64_C(0x9e3779b97f4a7c15);
  value = (value ^ (value >> 30U)) * UINT64_C(0xbf58476d1ce4e5b9);
  value = (value ^ (value >> 27U)) * UINT64_C(0x94d049bb133111eb);
  return value ^ (value >> 31U);
}

[[nodiscard]] DirectRegressionStats RunGridStrideAliasedRegression() {
  // The protocol remains small, while this direct fixture crosses the exact
  // production launch cap by 257 words. Threads 0..256 must therefore execute
  // a second grid-stride iteration. Black and white intentionally use the same
  // device range, which is an allowed input alias in the public contract.
  constexpr std::size_t words = kGridStrideRegressionWords;
  constexpr std::size_t guarded_words = words + kGuardWords;
  static_assert(guarded_words > words);
  const std::size_t guarded_bytes = guarded_words * sizeof(std::uint64_t);

  std::vector<std::uint64_t> input(guarded_words, kOutputFill);
  std::vector<std::uint64_t> output(guarded_words, kOutputFill);
  input.front() = kLeftCanary;
  input.back() = kRightCanary;
  output.front() = kLeftCanary;
  output.back() = kRightCanary;
  for (std::size_t index = 0; index < words; ++index) {
    input[index + 1U] = GridStridePattern(index);
  }

  DeviceWords device_input;
  DeviceWords device_output;
  device_input.Allocate(guarded_words);
  device_output.Allocate(guarded_words);
  CheckCuda(cudaMemcpy(device_input.get(), input.data(), guarded_bytes,
                       cudaMemcpyHostToDevice),
            "cudaMemcpy grid-stride input H2D");
  CheckCuda(cudaMemcpy(device_output.get(), output.data(), guarded_bytes,
                       cudaMemcpyHostToDevice),
            "cudaMemcpy grid-stride output initializer H2D");

  OwnedStream stream;
  ugts_go19::cuda::LaunchEmptyMask(
      device_input.get() + 1, device_input.get() + 1,
      device_output.get() + 1, words, 1U, UINT64_MAX,
      reinterpret_cast<void *>(stream.get()));
  CheckCuda(cudaStreamSynchronize(stream.get()),
            "cudaStreamSynchronize grid-stride regression");
  CheckCuda(cudaMemcpy(output.data(), device_output.get(), guarded_bytes,
                       cudaMemcpyDeviceToHost),
            "cudaMemcpy grid-stride output D2H");
  CheckCuda(cudaMemcpy(input.data(), device_input.get(), guarded_bytes,
                       cudaMemcpyDeviceToHost),
            "cudaMemcpy grid-stride input D2H");

  if (input.front() != kLeftCanary || input.back() != kRightCanary) {
    throw std::runtime_error("grid-stride input canary mismatch");
  }
  if (output.front() != kLeftCanary || output.back() != kRightCanary) {
    throw std::runtime_error("grid-stride output canary mismatch");
  }
  for (std::size_t index = 0; index < words; ++index) {
    const std::uint64_t expected_input = GridStridePattern(index);
    if (input[index + 1U] != expected_input) {
      throw std::runtime_error("grid-stride aliased input mutation at index " +
                               std::to_string(index));
    }
    if (output[index + 1U] != ~expected_input) {
      throw std::runtime_error("grid-stride output mismatch at index " +
                               std::to_string(index));
    }
  }

  device_output.Release();
  device_input.Release();
  stream.Release();
  return DirectRegressionStats{1U, words, 1U, words, 4U};
}

template <typename Exception, typename Callable>
void ExpectException(Callable &&callable, const char *description) {
  try {
    callable();
  } catch (const Exception &) {
    return;
  } catch (const std::exception &error) {
    throw std::runtime_error(std::string(description) +
                             " threw the wrong exception: " + error.what());
  }
  throw std::runtime_error(std::string(description) + " did not throw");
}

[[nodiscard]] std::size_t RunNegativeArgumentChecks() {
  auto *fake = reinterpret_cast<std::uint64_t *>(std::uintptr_t{1U});
  const auto *const_fake = static_cast<const std::uint64_t *>(fake);
  ExpectException<std::invalid_argument>(
      [&] {
        ugts_go19::cuda::LaunchEmptyMask(nullptr, const_fake, fake, 1, 1,
                                         UINT64_MAX, nullptr);
      },
      "null black pointer");
  ExpectException<std::invalid_argument>(
      [&] {
        ugts_go19::cuda::LaunchEmptyMask(const_fake, nullptr, fake, 1, 1,
                                         UINT64_MAX, nullptr);
      },
      "null white pointer");
  ExpectException<std::invalid_argument>(
      [&] {
        ugts_go19::cuda::LaunchEmptyMask(const_fake, const_fake, nullptr, 1, 1,
                                         UINT64_MAX, nullptr);
      },
      "null output pointer");
  ExpectException<std::invalid_argument>(
      [&] {
        ugts_go19::cuda::LaunchEmptyMask(const_fake, const_fake, fake, 0, 1,
                                         UINT64_MAX, nullptr);
      },
      "zero states");
  ExpectException<std::invalid_argument>(
      [&] {
        ugts_go19::cuda::LaunchEmptyMask(const_fake, const_fake, fake, 1, 0,
                                         UINT64_MAX, nullptr);
      },
      "zero words per state");
  ExpectException<std::overflow_error>(
      [&] {
        ugts_go19::cuda::LaunchEmptyMask(
            const_fake, const_fake, fake,
            std::numeric_limits<std::size_t>::max(), 2, UINT64_MAX, nullptr);
      },
      "word-count overflow");
  return 6U;
}

[[nodiscard]] std::string HexWord(std::uint64_t value) {
  std::ostringstream output;
  output << std::hex << std::setfill('0') << std::setw(16) << value;
  return output.str();
}

[[nodiscard]] std::string HexBytes(const char *text) {
  std::ostringstream output;
  output << std::hex << std::setfill('0');
  for (const unsigned char value : std::string(text)) {
    output << std::setw(2) << static_cast<unsigned int>(value);
  }
  return output.str();
}

} // namespace

int main() {
  try {
    int device_count = 0;
    CheckCuda(cudaGetDeviceCount(&device_count), "cudaGetDeviceCount");
    if (device_count < 1) {
      throw std::runtime_error("no CUDA device is available");
    }
    CheckCuda(cudaSetDevice(0), "cudaSetDevice");
    cudaDeviceProp properties{};
    CheckCuda(cudaGetDeviceProperties(&properties, 0),
              "cudaGetDeviceProperties");

    const std::vector<Fixture> fixtures = ReadFixtures(std::cin);
    const std::size_t negative_checks = RunNegativeArgumentChecks();
    const DirectRegressionStats direct = RunGridStrideAliasedRegression();
    std::vector<std::vector<std::uint64_t>> results(fixtures.size());
    for (std::size_t index = 0; index < fixtures.size(); ++index) {
      if (fixtures[index].mode == "dual") {
        const auto first = RunDualOnce(fixtures[index], fixtures[index + 1U]);
        const auto repeat = RunDualOnce(fixtures[index], fixtures[index + 1U]);
        if (first != repeat) {
          throw std::runtime_error("dual-stream repeat mismatch");
        }
        results[index] = first.first;
        results[index + 1U] = first.second;
        ++index;
      } else {
        const auto first = RunSingleOnce(fixtures[index]);
        const auto repeat = RunSingleOnce(fixtures[index]);
        if (first != repeat) {
          throw std::runtime_error("single-stream repeat mismatch");
        }
        results[index] = first;
      }
    }

    std::size_t compared_words = 0;
    std::cout << "UGTS_EMPTY_MASK_OUTPUT_V2\n";
    std::cout << "DEVICE " << properties.major << ' ' << properties.minor << ' '
              << HexBytes(properties.name) << "\n";
    for (std::size_t case_index = 0; case_index < fixtures.size();
         ++case_index) {
      const Fixture &fixture = fixtures[case_index];
      std::cout << "CASE " << fixture.id << ' ' << fixture.states << ' '
                << fixture.words_per_state << ' ' << HexWord(fixture.tail_mask)
                << ' ' << fixture.mode << "\n";
      for (std::size_t word_index = 0; word_index < results[case_index].size();
           ++word_index) {
        std::cout << "RESULT " << fixture.id << ' ' << word_index << ' '
                  << HexWord(results[case_index][word_index]) << "\n";
      }
      compared_words += results[case_index].size();
    }
    // Every protocol case ran twice and both executions were checked
    // word-for-word against the independent host formula before one exact
    // result was emitted. The direct grid-stride fixture is checked internally
    // and summarized without serializing its 16M+ words.
    const std::size_t input_immutability_words =
        compared_words * 4U + direct.input_immutability_words;
    const std::size_t canary_checks =
        fixtures.size() * 12U + direct.canary_checks;
    std::cout << "SUMMARY " << fixtures.size() << ' ' << compared_words << ' '
              << compared_words * 2U << " 0 0 0 " << negative_checks << ' '
              << direct.grid_stride_launches << ' ' << direct.grid_stride_words
              << ' ' << direct.aliased_input_launches << ' '
              << input_immutability_words << ' ' << canary_checks
              << "\nEND\n";
    return 0;
  } catch (const std::exception &error) {
    std::cerr << "ugts_go_cuda_empty_mask_eval: " << error.what() << "\n";
    return 1;
  }
}
