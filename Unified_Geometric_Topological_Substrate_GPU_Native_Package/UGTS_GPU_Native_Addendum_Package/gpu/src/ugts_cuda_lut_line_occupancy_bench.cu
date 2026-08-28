#include <cuda_runtime.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <numeric>
#include <sstream>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <vector>

namespace fs = std::filesystem;

namespace {

constexpr std::uint32_t kSteps = 512;
constexpr std::uint32_t kWarpSize = 32;
constexpr std::uint32_t kLineBytes = 128;
constexpr std::uint32_t kLineWords = kLineBytes / sizeof(std::uint32_t);
constexpr std::uint32_t kMaximumCodesPerLine = 170;
constexpr std::uint32_t kCpuValidatedThreads = 32;
constexpr std::uint32_t kLineLcgMul = 1664525u;
constexpr std::uint32_t kLineLcgAdd = 1013904223u;
constexpr std::uint32_t kSlotLcgMul = 22695477u;
constexpr std::uint32_t kSlotLcgAdd = 1u;

void cuda_check(cudaError_t result, const char *what) {
  if (result != cudaSuccess)
    throw std::runtime_error(std::string(what) + ": " +
                             cudaGetErrorString(result));
}

struct Args {
  fs::path out_dir = "cuda_lut_line_occupancy_out";
  std::vector<std::uint32_t> table_mib = {28, 32, 36, 37, 38, 39, 40, 48};
  std::vector<std::uint32_t> codes_per_line = {1,  2,  4,  8, 16,
                                               32, 64, 128, 170};
  std::vector<int> warps = {184, 1104};
  std::size_t eviction_mib = 256;
  int warmup = 3;
  int samples = 12;
  int order = 0;
};

template <typename T>
std::vector<T> parse_list(const std::string &text) {
  std::stringstream stream(text);
  std::string part;
  std::vector<T> result;
  while (std::getline(stream, part, ',')) {
    if (part.empty())
      continue;
    if constexpr (std::is_same_v<T, int>)
      result.push_back(std::stoi(part));
    else
      result.push_back(T(std::stoull(part)));
  }
  if (result.empty())
    throw std::runtime_error("empty numeric list");
  return result;
}

Args parse_args(int argc, char **argv) {
  Args args;
  for (int i = 1; i < argc; ++i) {
    const std::string arg = argv[i];
    auto value = [&](const char *name) {
      if (i + 1 >= argc)
        throw std::runtime_error(std::string("missing value for ") + name);
      return std::string(argv[++i]);
    };
    if (arg == "--out-dir")
      args.out_dir = value("--out-dir");
    else if (arg == "--table-mib")
      args.table_mib = parse_list<std::uint32_t>(value("--table-mib"));
    else if (arg == "--codes-per-line")
      args.codes_per_line =
          parse_list<std::uint32_t>(value("--codes-per-line"));
    else if (arg == "--warps")
      args.warps = parse_list<int>(value("--warps"));
    else if (arg == "--eviction-mib")
      args.eviction_mib = std::stoull(value("--eviction-mib"));
    else if (arg == "--warmup")
      args.warmup = std::stoi(value("--warmup"));
    else if (arg == "--samples")
      args.samples = std::stoi(value("--samples"));
    else if (arg == "--order")
      args.order = std::stoi(value("--order"));
    else
      throw std::runtime_error("unknown argument: " + arg);
  }
  if (args.warmup < 0 || args.samples < 1 || args.eviction_mib < 64 ||
      args.order < 0 || args.order > 1)
    throw std::runtime_error("invalid line-occupancy run parameters");
  for (auto table_mib : args.table_mib)
    if (table_mib < 1 || table_mib > 128)
      throw std::runtime_error("table MiB must be in [1, 128]");
  for (auto codes : args.codes_per_line)
    if (codes < 1 || codes > kMaximumCodesPerLine)
      throw std::runtime_error("codes per line must be in [1, 170]");
  for (auto warps : args.warps)
    if (warps < 1 || warps > 4096)
      throw std::runtime_error("warp count must be in [1, 4096]");
  return args;
}

__host__ __device__ std::uint32_t mix32(std::uint32_t x) {
  x ^= x >> 16;
  x *= 0x7feb352du;
  x ^= x >> 15;
  x *= 0x846ca68bu;
  x ^= x >> 16;
  return x;
}

__host__ __device__ __forceinline__ std::uint32_t code_for(
    std::uint32_t line, std::uint32_t slot) {
  return (line * 13u + (line >> 6u) + slot * 29u) & 63u;
}

__host__ __device__ __forceinline__ std::uint32_t roll_checksum(
    std::uint32_t checksum, std::uint32_t code, std::uint32_t line,
    std::uint32_t slot) {
  return (checksum ^ code ^ (line * 0x9e3779b9u) ^ (slot * 0x85ebca6bu)) *
             16777619u +
         0x27d4eb2du;
}

__device__ __forceinline__ std::uint32_t load_global_l2(
    const std::uint32_t *address) {
  std::uint32_t value;
  asm volatile("ld.global.cg.u32 %0, [%1];" : "=r"(value) : "l"(address));
  return value;
}

__global__ void initialize_packed_lines(std::uint32_t *words,
                                        std::uint32_t lines,
                                        std::uint32_t codes_per_line,
                                        std::uint32_t seed) {
  const std::uint32_t line = threadIdx.x + blockIdx.x * blockDim.x;
  if (line >= lines)
    return;
  const std::uint32_t base = line * kLineWords;
  for (std::uint32_t word = 0; word < kLineWords; ++word)
    words[base + word] =
        mix32(seed ^ (line * 0x9e3779b9u) ^ (word * 0x85ebca6bu));
  for (std::uint32_t slot = 0; slot < codes_per_line; ++slot) {
    const std::uint32_t value = code_for(line, slot);
    const std::uint32_t bit = slot * 6u;
    const std::uint32_t word = bit >> 5u;
    const std::uint32_t shift = bit & 31u;
    if (shift <= 26u) {
      const std::uint32_t mask = 63u << shift;
      words[base + word] =
          (words[base + word] & ~mask) | (value << shift);
    } else {
      const std::uint32_t low_bits = 32u - shift;
      const std::uint32_t low_value_mask = (1u << low_bits) - 1u;
      const std::uint32_t low_mask = low_value_mask << shift;
      const std::uint32_t high_bits = 6u - low_bits;
      const std::uint32_t high_mask = (1u << high_bits) - 1u;
      words[base + word] =
          (words[base + word] & ~low_mask) |
          ((value & low_value_mask) << shift);
      words[base + word + 1u] =
          (words[base + word + 1u] & ~high_mask) |
          ((value >> low_bits) & high_mask);
    }
  }
}

struct alignas(16) LookupResult {
  unsigned long long started;
  unsigned long long finished;
  std::uint32_t final_line_state;
  std::uint32_t final_slot_state;
  std::uint32_t checksum;
  std::uint32_t mismatch_count;
  std::uint32_t seed;
  std::uint32_t steps;
};
static_assert(sizeof(LookupResult) == 48, "lookup result ABI");

__host__ __device__ __forceinline__ std::uint32_t initial_seed(
    std::uint32_t lane, std::uint32_t warp, std::uint32_t sample_seed) {
  return mix32(sample_seed ^ (warp * 0x9e3779b9u) ^
               (lane * 0x85ebca6bu));
}

template <bool Texture>
__device__ __forceinline__ std::uint32_t load_word(
    const std::uint32_t *global_words, cudaTextureObject_t texture,
    std::uint32_t index) {
  if constexpr (Texture)
    return tex1Dfetch<std::uint32_t>(texture, int(index));
  else
    return load_global_l2(global_words + index);
}

template <bool Texture>
__device__ __forceinline__ std::uint32_t decode_line_code(
    const std::uint32_t *global_words, cudaTextureObject_t texture,
    std::uint32_t line, std::uint32_t slot) {
  const std::uint32_t bit = slot * 6u;
  const std::uint32_t word = bit >> 5u;
  const std::uint32_t shift = bit & 31u;
  const std::uint32_t address = line * kLineWords + word;
  const std::uint32_t low =
      load_word<Texture>(global_words, texture, address);
  if (shift <= 26u)
    return (low >> shift) & 63u;
  const std::uint32_t high =
      load_word<Texture>(global_words, texture, address + 1u);
  return ((low >> shift) | (high << (32u - shift))) & 63u;
}

template <int Steps, bool Texture>
__global__ void lookup_line_codes(const std::uint32_t *global_words,
                                  cudaTextureObject_t texture,
                                  std::uint32_t lines,
                                  std::uint32_t codes_per_line,
                                  std::uint32_t sample_seed,
                                  LookupResult *results) {
  const std::uint32_t lane = threadIdx.x;
  const std::uint32_t warp = blockIdx.x;
  const std::uint32_t output = warp * kWarpSize + lane;
  const std::uint32_t seed = initial_seed(lane, warp, sample_seed);
  std::uint32_t line_state = seed;
  std::uint32_t slot_state = seed ^ 0xa5a5a5a5u;
  std::uint32_t checksum = seed ^ 0x3c6ef372u;
  std::uint32_t mismatches = 0u;
  asm volatile("" ::: "memory");
  const unsigned long long started = clock64();
#pragma unroll 1
  for (int step = 0; step < Steps; ++step) {
    line_state = line_state * kLineLcgMul + kLineLcgAdd;
    slot_state = slot_state * kSlotLcgMul + kSlotLcgAdd;
    const std::uint32_t line = __umulhi(line_state, lines);
    const std::uint32_t slot = __umulhi(slot_state, codes_per_line);
    const std::uint32_t code =
        decode_line_code<Texture>(global_words, texture, line, slot);
    mismatches += std::uint32_t(code != code_for(line, slot));
    checksum = roll_checksum(checksum, code, line, slot);
  }
  const unsigned long long finished = clock64();
  asm volatile("" ::: "memory");
  LookupResult result{};
  result.started = started;
  result.finished = finished;
  result.final_line_state = line_state;
  result.final_slot_state = slot_state;
  result.checksum = checksum;
  result.mismatch_count = mismatches;
  result.seed = seed;
  result.steps = Steps;
  results[output] = result;
}

__global__ void evict_global(const std::uint32_t *data, std::size_t entries,
                             std::uint32_t *sink) {
  const std::size_t thread = threadIdx.x + std::size_t(blockIdx.x) * blockDim.x;
  const std::size_t stride = std::size_t(blockDim.x) * gridDim.x;
  std::uint32_t value = std::uint32_t(thread);
  for (std::size_t i = thread; i < entries; i += stride)
    value ^= load_global_l2(data + i);
  sink[thread] = value;
}

__global__ void evict_texture(cudaTextureObject_t texture,
                              std::size_t entries, std::uint32_t *sink) {
  const std::size_t thread = threadIdx.x + std::size_t(blockIdx.x) * blockDim.x;
  const std::size_t stride = std::size_t(blockDim.x) * gridDim.x;
  std::uint32_t value = std::uint32_t(thread);
  for (std::size_t i = thread; i < entries; i += stride)
    value ^= tex1Dfetch<std::uint32_t>(texture, int(i));
  sink[thread] = value;
}

cudaTextureObject_t make_linear_texture(std::uint32_t *data,
                                        std::size_t bytes) {
  cudaResourceDesc resource{};
  resource.resType = cudaResourceTypeLinear;
  resource.res.linear.devPtr = data;
  resource.res.linear.desc = cudaCreateChannelDesc<std::uint32_t>();
  resource.res.linear.sizeInBytes = bytes;
  cudaTextureDesc description{};
  description.readMode = cudaReadModeElementType;
  cudaTextureObject_t texture = 0;
  cuda_check(cudaCreateTextureObject(&texture, &resource, &description, nullptr),
             "cudaCreateTextureObject");
  return texture;
}

std::uint32_t multiply_high(std::uint32_t left, std::uint32_t right) {
  return std::uint32_t((std::uint64_t(left) * right) >> 32u);
}

double percentile(std::vector<double> values, double q) {
  std::sort(values.begin(), values.end());
  const double position = q * double(values.size() - 1);
  const auto low = std::size_t(std::floor(position));
  const auto high = std::size_t(std::ceil(position));
  const double fraction = position - double(low);
  return values[low] * (1.0 - fraction) + values[high] * fraction;
}

struct Distribution {
  double minimum = 0, mean = 0, p50 = 0, p95 = 0, p99 = 0, maximum = 0;
};

Distribution summarize(const std::vector<double> &values) {
  if (values.empty())
    throw std::runtime_error("cannot summarize an empty measurement set");
  return {*std::min_element(values.begin(), values.end()),
          std::accumulate(values.begin(), values.end(), 0.0) /
              double(values.size()),
          percentile(values, 0.50), percentile(values, 0.95),
          percentile(values, 0.99), *std::max_element(values.begin(), values.end())};
}

struct Accumulator {
  std::vector<double> control_cycles, cold_cycles, hot_cycles, cold_us, hot_us;
  std::size_t valid_control = 0, valid_cold = 0, valid_hot = 0;
};

struct Mode {
  const char *path;
  bool texture;
};

constexpr Mode kModes[2] = {{"global_cg", false},
                            {"texture_object", true}};
constexpr int kOrders[2][2] = {{0, 1}, {1, 0}};

struct Expected {
  std::uint32_t final_line_state;
  std::uint32_t final_slot_state;
  std::uint32_t checksum;
};

Expected replay(std::uint32_t seed, std::uint32_t lines,
                std::uint32_t codes_per_line, std::uint32_t steps) {
  std::uint32_t line_state = seed;
  std::uint32_t slot_state = seed ^ 0xa5a5a5a5u;
  std::uint32_t checksum = seed ^ 0x3c6ef372u;
  for (std::uint32_t step = 0; step < steps; ++step) {
    line_state = line_state * kLineLcgMul + kLineLcgAdd;
    slot_state = slot_state * kSlotLcgMul + kSlotLcgAdd;
    const std::uint32_t line = multiply_high(line_state, lines);
    const std::uint32_t slot = multiply_high(slot_state, codes_per_line);
    checksum =
        roll_checksum(checksum, code_for(line, slot), line, slot);
  }
  return {line_state, slot_state, checksum};
}

void validate_results(const std::vector<LookupResult> &results,
                      std::uint32_t sample_seed, std::uint32_t lines,
                      std::uint32_t codes_per_line, std::uint32_t steps,
                      std::vector<double> &cycles, std::size_t &validated) {
  for (std::size_t output = 0; output < results.size(); ++output) {
    const std::uint32_t warp = std::uint32_t(output / kWarpSize);
    const std::uint32_t lane = std::uint32_t(output % kWarpSize);
    const std::uint32_t seed = initial_seed(lane, warp, sample_seed);
    const Expected expected = replay(seed, lines, codes_per_line, steps);
    const auto &actual = results[output];
    if (actual.final_line_state == expected.final_line_state &&
        actual.final_slot_state == expected.final_slot_state &&
        actual.checksum == expected.checksum && actual.mismatch_count == 0u &&
        actual.seed == seed && actual.steps == steps &&
        actual.finished >= actual.started)
      ++validated;
    cycles.push_back(double(actual.finished - actual.started));
  }
}

template <int Steps>
void launch_mode(int mode, int warps, const std::uint32_t *words,
                 cudaTextureObject_t texture, std::uint32_t lines,
                 std::uint32_t codes_per_line, std::uint32_t seed,
                 LookupResult *output) {
  if (mode == 0)
    lookup_line_codes<Steps, false><<<warps, kWarpSize>>>(
        words, 0, lines, codes_per_line, seed, output);
  else if (mode == 1)
    lookup_line_codes<Steps, true><<<warps, kWarpSize>>>(
        words, texture, lines, codes_per_line, seed, output);
  else
    throw std::runtime_error("invalid lookup mode");
}

struct Row {
  std::string path;
  std::uint32_t table_mib = 0, lines = 0, codes_per_line = 0;
  std::uint64_t table_bytes = 0, active_codes = 0;
  int warps = 0, threads = 0, samples = 0;
  double effective_bytes_per_active_code = 0;
  double code_bit_utilization = 0;
  double expected_words_per_lookup = 0;
  std::size_t validated_control = 0, validated_cold = 0, validated_hot = 0;
  Distribution control_cycles, cold_cycles, hot_cycles, cold_kernel_us,
      hot_kernel_us;
  double cold_net_cycles_per_lookup = 0, hot_net_cycles_per_lookup = 0;
  double cold_glookups_s = 0, hot_glookups_s = 0;
  double cold_requested_word_gloads_s = 0, hot_requested_word_gloads_s = 0;
  bool valid = false;
};

double expected_word_requests(std::uint32_t codes_per_line) {
  std::uint32_t straddles = 0;
  for (std::uint32_t slot = 0; slot < codes_per_line; ++slot)
    if (((slot * 6u) & 31u) > 26u)
      ++straddles;
  return 1.0 + double(straddles) / codes_per_line;
}

Row finalize_row(const Args &args, const Mode &mode, std::uint32_t table_mib,
                 std::uint32_t lines, std::uint32_t codes_per_line, int warps,
                 const Accumulator &data) {
  Row row{};
  row.path = mode.path;
  row.table_mib = table_mib;
  row.table_bytes = std::uint64_t(table_mib) * 1024 * 1024;
  row.lines = lines;
  row.codes_per_line = codes_per_line;
  row.active_codes = std::uint64_t(lines) * codes_per_line;
  row.warps = warps;
  row.threads = warps * int(kWarpSize);
  row.samples = args.samples;
  row.effective_bytes_per_active_code = double(kLineBytes) / codes_per_line;
  row.code_bit_utilization = double(codes_per_line * 6u) / (kLineBytes * 8u);
  row.expected_words_per_lookup = expected_word_requests(codes_per_line);
  row.validated_control = data.valid_control;
  row.validated_cold = data.valid_cold;
  row.validated_hot = data.valid_hot;
  row.control_cycles = summarize(data.control_cycles);
  row.cold_cycles = summarize(data.cold_cycles);
  row.hot_cycles = summarize(data.hot_cycles);
  row.cold_kernel_us = summarize(data.cold_us);
  row.hot_kernel_us = summarize(data.hot_us);
  row.cold_net_cycles_per_lookup =
      (row.cold_cycles.p50 - row.control_cycles.p50) / kSteps;
  row.hot_net_cycles_per_lookup =
      (row.hot_cycles.p50 - row.control_cycles.p50) / kSteps;
  const double lookups = double(row.threads) * kSteps;
  row.cold_glookups_s = lookups / (row.cold_kernel_us.p50 * 1000.0);
  row.hot_glookups_s = lookups / (row.hot_kernel_us.p50 * 1000.0);
  row.cold_requested_word_gloads_s =
      row.cold_glookups_s * row.expected_words_per_lookup;
  row.hot_requested_word_gloads_s =
      row.hot_glookups_s * row.expected_words_per_lookup;
  const std::size_t expected = std::size_t(args.samples) *
                               std::min<std::size_t>(row.threads,
                                                     kCpuValidatedThreads);
  row.valid = data.valid_control == expected && data.valid_cold == expected &&
              data.valid_hot == expected;
  return row;
}

std::vector<Row> run_case(const Args &args, std::uint32_t table_mib,
                          std::uint32_t codes_per_line, int warps,
                          const std::uint32_t *eviction,
                          std::size_t eviction_entries,
                          cudaTextureObject_t eviction_texture,
                          std::uint32_t *eviction_sink, int eviction_blocks) {
  const std::size_t table_bytes = std::size_t(table_mib) * 1024 * 1024;
  const std::uint32_t lines = std::uint32_t(table_bytes / kLineBytes);
  const std::size_t threads = std::size_t(warps) * kWarpSize;
  const std::size_t copied_threads =
      std::min<std::size_t>(threads, kCpuValidatedThreads);
  std::uint32_t *words = nullptr;
  LookupResult *device_control = nullptr, *device_cold = nullptr,
               *device_hot = nullptr;
  cuda_check(cudaMalloc(&words, table_bytes), "cudaMalloc(occupancy table)");
  cuda_check(cudaMalloc(&device_control, threads * sizeof(LookupResult)),
             "cudaMalloc(control output)");
  cuda_check(cudaMalloc(&device_cold, threads * sizeof(LookupResult)),
             "cudaMalloc(cold output)");
  cuda_check(cudaMalloc(&device_hot, threads * sizeof(LookupResult)),
             "cudaMalloc(hot output)");
  initialize_packed_lines<<<int((std::uint64_t(lines) + 255) / 256), 256>>>(
      words, lines, codes_per_line,
      mix32(table_mib * 0x9e3779b9u ^ codes_per_line));
  cuda_check(cudaGetLastError(), "line table initialization launch");
  cuda_check(cudaDeviceSynchronize(), "line table initialization sync");
  const cudaTextureObject_t texture = make_linear_texture(words, table_bytes);
  cudaEvent_t cold_start{}, cold_end{}, hot_start{}, hot_end{};
  cuda_check(cudaEventCreate(&cold_start), "cudaEventCreate(cold start)");
  cuda_check(cudaEventCreate(&cold_end), "cudaEventCreate(cold end)");
  cuda_check(cudaEventCreate(&hot_start), "cudaEventCreate(hot start)");
  cuda_check(cudaEventCreate(&hot_end), "cudaEventCreate(hot end)");
  std::vector<LookupResult> control(copied_threads), cold(copied_threads),
      hot(copied_threads);
  Accumulator accumulators[2];
  for (int sample = -args.warmup; sample < args.samples; ++sample) {
    const std::uint32_t sample_seed =
        mix32(std::uint32_t(sample + args.warmup + 1) * 0xc2b2ae35u);
    for (int position = 0; position < 2; ++position) {
      const int mode = kOrders[args.order][position];
      evict_global<<<eviction_blocks, 256>>>(eviction, eviction_entries,
                                             eviction_sink);
      if (kModes[mode].texture)
        evict_texture<<<eviction_blocks, 256>>>(
            eviction_texture, eviction_entries, eviction_sink);
      launch_mode<0>(mode, warps, words, texture, lines, codes_per_line,
                     sample_seed, device_control);
      cuda_check(cudaEventRecord(cold_start), "cudaEventRecord(cold start)");
      launch_mode<kSteps>(mode, warps, words, texture, lines, codes_per_line,
                          sample_seed, device_cold);
      cuda_check(cudaEventRecord(cold_end), "cudaEventRecord(cold end)");
      cuda_check(cudaEventRecord(hot_start), "cudaEventRecord(hot start)");
      launch_mode<kSteps>(mode, warps, words, texture, lines, codes_per_line,
                          sample_seed, device_hot);
      cuda_check(cudaEventRecord(hot_end), "cudaEventRecord(hot end)");
      cuda_check(cudaGetLastError(), "line occupancy lookup launch");
      cuda_check(cudaMemcpy(control.data(), device_control,
                            copied_threads * sizeof(LookupResult),
                            cudaMemcpyDeviceToHost),
                 "cudaMemcpy(control result)");
      cuda_check(cudaMemcpy(cold.data(), device_cold,
                            copied_threads * sizeof(LookupResult),
                            cudaMemcpyDeviceToHost),
                 "cudaMemcpy(cold result)");
      cuda_check(cudaMemcpy(hot.data(), device_hot,
                            copied_threads * sizeof(LookupResult),
                            cudaMemcpyDeviceToHost),
                 "cudaMemcpy(hot result)");
      float cold_ms = 0, hot_ms = 0;
      cuda_check(cudaEventElapsedTime(&cold_ms, cold_start, cold_end),
                 "cudaEventElapsedTime(cold)");
      cuda_check(cudaEventElapsedTime(&hot_ms, hot_start, hot_end),
                 "cudaEventElapsedTime(hot)");
      if (sample >= 0) {
        auto &data = accumulators[mode];
        validate_results(control, sample_seed, lines, codes_per_line, 0,
                         data.control_cycles, data.valid_control);
        validate_results(cold, sample_seed, lines, codes_per_line, kSteps,
                         data.cold_cycles, data.valid_cold);
        validate_results(hot, sample_seed, lines, codes_per_line, kSteps,
                         data.hot_cycles, data.valid_hot);
        data.cold_us.push_back(double(cold_ms) * 1000.0);
        data.hot_us.push_back(double(hot_ms) * 1000.0);
      }
    }
  }
  std::vector<Row> rows;
  for (int mode = 0; mode < 2; ++mode)
    rows.push_back(finalize_row(args, kModes[mode], table_mib, lines,
                                codes_per_line, warps, accumulators[mode]));
  cudaEventDestroy(cold_start);
  cudaEventDestroy(cold_end);
  cudaEventDestroy(hot_start);
  cudaEventDestroy(hot_end);
  cudaDestroyTextureObject(texture);
  cudaFree(device_hot);
  cudaFree(device_cold);
  cudaFree(device_control);
  cudaFree(words);
  return rows;
}

void write_distribution(std::ostream &out, const Distribution &d) {
  out << "{\"min\": " << d.minimum << ", \"mean\": " << d.mean
      << ", \"p50\": " << d.p50 << ", \"p95\": " << d.p95
      << ", \"p99\": " << d.p99 << ", \"max\": " << d.maximum << '}';
}

void write_results(const Args &args, const cudaDeviceProp &properties,
                   const int occupancy[2], const std::vector<Row> &rows) {
  fs::create_directories(args.out_dir);
  std::ofstream json(args.out_dir / "cuda_lut_line_occupancy_results.json");
  json << std::fixed << std::setprecision(6)
       << "{\n  \"schema\": \"UGTS-CUDA-LUT-LINE-OCCUPANCY-1.0\",\n"
          "  \"runtime\": \"CUDA sm_120 packed6 occupancy per 128-byte "
          "region through matched LDG and TLD\",\n"
          "  \"device\": {\"name\": \""
       << properties.name << "\", \"compute_capability\": \""
       << properties.major << '.' << properties.minor << "\", \"l2_bytes\": "
       << properties.l2CacheSize << ", \"multiprocessors\": "
       << properties.multiProcessorCount
       << ", \"max_texture_1d_linear_elements\": "
       << properties.maxTexture1DLinear
       << ", \"occupancy_blocks_per_sm\": {\"global_cg\": "
       << occupancy[0] << ", \"texture_object\": " << occupancy[1]
       << "}},\n  \"run_parameters\": {\"warmup_sets\": " << args.warmup
       << ", \"measured_sets\": " << args.samples
       << ", \"lookups_per_thread\": " << kSteps
       << ", \"eviction_bytes\": " << args.eviction_mib * 1024 * 1024
       << ", \"path_order\": " << args.order
       << "},\n  \"semantics\": \"Each aligned 128-byte region contains the "
          "declared number of useful packed 6-bit codes and deterministic "
          "mixed filler everywhere else. Independent LCGs select a random "
          "region and useful slot. Every code is checked in the timed kernel; "
          "the first 32 lanes per sample are fully replayed on CPU. Rates are "
          "logical decoded-code lookups, not physical cache transactions.\",\n"
          "  \"results\": [\n";
  for (std::size_t i = 0; i < rows.size(); ++i) {
    const auto &row = rows[i];
    json << "    {\"path\": \"" << row.path
         << "\", \"table_mib\": " << row.table_mib
         << ", \"table_bytes\": " << row.table_bytes
         << ", \"l2_fraction\": "
         << double(row.table_bytes) / properties.l2CacheSize
         << ", \"regions_128b\": " << row.lines
         << ", \"codes_per_128b_region\": " << row.codes_per_line
         << ", \"active_codes\": " << row.active_codes
         << ", \"effective_bytes_per_active_code\": "
         << row.effective_bytes_per_active_code
         << ", \"code_bit_utilization\": " << row.code_bit_utilization
         << ", \"expected_words_per_lookup\": "
         << row.expected_words_per_lookup << ", \"warps\": " << row.warps
         << ", \"warps_per_sm\": "
         << double(row.warps) / properties.multiProcessorCount
         << ", \"threads\": " << row.threads << ", \"samples\": "
         << row.samples << ", \"control_cycles\": ";
    write_distribution(json, row.control_cycles);
    json << ", \"cold_cycles\": ";
    write_distribution(json, row.cold_cycles);
    json << ", \"hot_cycles\": ";
    write_distribution(json, row.hot_cycles);
    json << ", \"cold_kernel_us\": ";
    write_distribution(json, row.cold_kernel_us);
    json << ", \"hot_kernel_us\": ";
    write_distribution(json, row.hot_kernel_us);
    json << ", \"cold_net_cycles_per_lookup\": "
         << row.cold_net_cycles_per_lookup
         << ", \"hot_net_cycles_per_lookup\": "
         << row.hot_net_cycles_per_lookup
         << ", \"cold_glookups_s\": " << row.cold_glookups_s
         << ", \"hot_glookups_s\": " << row.hot_glookups_s
         << ", \"cold_requested_word_gloads_s\": "
         << row.cold_requested_word_gloads_s
         << ", \"hot_requested_word_gloads_s\": "
         << row.hot_requested_word_gloads_s
         << ", \"validated_control\": " << row.validated_control
         << ", \"validated_cold\": " << row.validated_cold
         << ", \"validated_hot\": " << row.validated_hot
         << ", \"validation\": " << (row.valid ? "true" : "false") << '}'
         << (i + 1 == rows.size() ? "\n" : ",\n");
  }
  json << "  ]\n}\n";
  std::ofstream csv(args.out_dir / "cuda_lut_line_occupancy_results.csv");
  csv << "path,table_mib,table_bytes,l2_fraction,regions_128b,"
         "codes_per_128b_region,active_codes,effective_bytes_per_active_code,"
         "code_bit_utilization,expected_words_per_lookup,warps,warps_per_sm,"
         "threads,samples,control_p50_cycles,cold_p50_cycles,hot_p50_cycles,"
         "cold_net_cycles_per_lookup,hot_net_cycles_per_lookup,"
         "cold_kernel_p50_us,hot_kernel_p50_us,cold_glookups_s,hot_glookups_s,"
         "cold_requested_word_gloads_s,hot_requested_word_gloads_s,"
         "validated_control,validated_cold,validated_hot,validation\n"
      << std::fixed << std::setprecision(6);
  for (const auto &row : rows)
    csv << row.path << ',' << row.table_mib << ',' << row.table_bytes << ','
        << double(row.table_bytes) / properties.l2CacheSize << ',' << row.lines
        << ',' << row.codes_per_line << ',' << row.active_codes << ','
        << row.effective_bytes_per_active_code << ',' << row.code_bit_utilization
        << ',' << row.expected_words_per_lookup << ',' << row.warps << ','
        << double(row.warps) / properties.multiProcessorCount << ','
        << row.threads << ',' << row.samples << ',' << row.control_cycles.p50
        << ',' << row.cold_cycles.p50 << ',' << row.hot_cycles.p50 << ','
        << row.cold_net_cycles_per_lookup << ','
        << row.hot_net_cycles_per_lookup << ',' << row.cold_kernel_us.p50 << ','
        << row.hot_kernel_us.p50 << ',' << row.cold_glookups_s << ','
        << row.hot_glookups_s << ',' << row.cold_requested_word_gloads_s << ','
        << row.hot_requested_word_gloads_s << ',' << row.validated_control << ','
        << row.validated_cold << ',' << row.validated_hot << ','
        << (row.valid ? 1 : 0) << '\n';
}

} // namespace

int main(int argc, char **argv) {
  try {
    const Args args = parse_args(argc, argv);
    cuda_check(cudaSetDevice(0), "cudaSetDevice");
    cudaDeviceProp properties{};
    cuda_check(cudaGetDeviceProperties(&properties, 0),
               "cudaGetDeviceProperties");
    int occupancy[2] = {};
    cuda_check(cudaOccupancyMaxActiveBlocksPerMultiprocessor(
                   &occupancy[0], lookup_line_codes<kSteps, false>, kWarpSize,
                   0),
               "global occupancy query");
    cuda_check(cudaOccupancyMaxActiveBlocksPerMultiprocessor(
                   &occupancy[1], lookup_line_codes<kSteps, true>, kWarpSize,
                   0),
               "texture occupancy query");
    const std::size_t eviction_bytes = args.eviction_mib * 1024 * 1024;
    const std::size_t eviction_entries = eviction_bytes / sizeof(std::uint32_t);
    constexpr int eviction_blocks = 2048;
    std::uint32_t *eviction = nullptr, *eviction_sink = nullptr;
    cuda_check(cudaMalloc(&eviction, eviction_bytes), "cudaMalloc(eviction)");
    cuda_check(cudaMalloc(&eviction_sink,
                          std::size_t(eviction_blocks) * 256 *
                              sizeof(std::uint32_t)),
               "cudaMalloc(eviction sink)");
    cuda_check(cudaMemset(eviction, 0xa5, eviction_bytes),
               "cudaMemset(eviction)");
    const cudaTextureObject_t eviction_texture =
        make_linear_texture(eviction, eviction_bytes);
    std::cout << "CUDA LUT line-occupancy device: " << properties.name
              << " sm_" << properties.major << properties.minor
              << " L2=" << properties.l2CacheSize << " bytes SMs="
              << properties.multiProcessorCount << " occupancy="
              << occupancy[0] << '/' << occupancy[1] << '\n';
    std::vector<Row> rows;
    for (auto table_mib : args.table_mib)
      for (auto codes_per_line : args.codes_per_line)
        for (auto warps : args.warps) {
          auto case_rows = run_case(
              args, table_mib, codes_per_line, warps, eviction,
              eviction_entries, eviction_texture, eviction_sink,
              eviction_blocks);
          for (const auto &row : case_rows) {
            std::cout << std::setw(2) << table_mib << " MiB codes/128B="
                      << std::setw(3) << codes_per_line << " warps="
                      << std::setw(4) << warps << ' ' << std::setw(14)
                      << row.path << " hot=" << std::fixed
                      << std::setprecision(3) << row.hot_glookups_s
                      << " Glookup/s valid=" << (row.valid ? "yes" : "no")
                      << '\n';
            rows.push_back(row);
          }
        }
    write_results(args, properties, occupancy, rows);
    cudaDestroyTextureObject(eviction_texture);
    cudaFree(eviction_sink);
    cudaFree(eviction);
    return std::all_of(rows.begin(), rows.end(),
                       [](const Row &row) { return row.valid; })
               ? 0
               : 2;
  } catch (const std::exception &error) {
    std::cerr << "UGTS CUDA LUT line-occupancy benchmark error: "
              << error.what() << '\n';
    return 1;
  }
}
