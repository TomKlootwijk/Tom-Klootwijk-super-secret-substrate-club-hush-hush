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
constexpr std::uint32_t kLcgMul = 1664525u;
constexpr std::uint32_t kLcgAdd = 1013904223u;

void cuda_check(cudaError_t result, const char *what) {
  if (result != cudaSuccess)
    throw std::runtime_error(std::string(what) + ": " +
                             cudaGetErrorString(result));
}

struct Args {
  fs::path out_dir = "cuda_packed_log_lut_out";
  std::vector<std::uint32_t> entries = {
      2097152u,  14680064u, 16777216u, 18874368u, 20971520u, 25165824u,
      33554432u, 39146832u, 50331648u, 55924048u, 67108864u};
  std::vector<int> warps = {1, 46, 184, 1104};
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
    else if (arg == "--entries")
      args.entries = parse_list<std::uint32_t>(value("--entries"));
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
      args.order < 0 || args.order > 3)
    throw std::runtime_error("invalid packed log-LUT run parameters");
  for (auto entries : args.entries)
    if (entries < 16 || (entries % 16) != 0)
      throw std::runtime_error("every entry count must be a multiple of 16");
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

__host__ __device__ std::uint32_t code_for(std::uint32_t index) {
  return index & 63u;
}

__device__ __forceinline__ std::uint32_t load_global_l2(
    const std::uint32_t *address) {
  std::uint32_t value;
  asm volatile("ld.global.cg.u32 %0, [%1];" : "=r"(value) : "l"(address));
  return value;
}

__global__ void initialize_slot16(std::uint32_t *words,
                                  std::uint32_t entries) {
  const std::uint32_t word = threadIdx.x + blockIdx.x * blockDim.x;
  const std::uint32_t first = word * 2u;
  if (first >= entries)
    return;
  const std::uint32_t low = code_for(first);
  const std::uint32_t high = first + 1u < entries ? code_for(first + 1u) : 0u;
  words[word] = low | (high << 16u);
}

__global__ void initialize_packed6(std::uint32_t *words,
                                   std::uint32_t entries) {
  const std::uint32_t group = threadIdx.x + blockIdx.x * blockDim.x;
  const std::uint32_t first = group * 16u;
  if (first >= entries)
    return;
  std::uint32_t output[3] = {0u, 0u, 0u};
#pragma unroll
  for (std::uint32_t i = 0; i < 16u; ++i) {
    const std::uint32_t value = code_for(first + i);
    const std::uint32_t bit = i * 6u;
    const std::uint32_t word = bit >> 5u;
    const std::uint32_t shift = bit & 31u;
    output[word] |= value << shift;
    if (shift > 26u)
      output[word + 1u] |= value >> (32u - shift);
  }
  words[group * 3u + 0u] = output[0];
  words[group * 3u + 1u] = output[1];
  words[group * 3u + 2u] = output[2];
}

struct alignas(16) LookupResult {
  unsigned long long started;
  unsigned long long finished;
  std::uint32_t final_state;
  std::uint32_t mismatch_count;
  std::uint32_t seed;
  std::uint32_t steps;
};
static_assert(sizeof(LookupResult) == 32, "lookup result ABI");

__host__ __device__ __forceinline__ std::uint32_t initial_state(
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

template <bool Packed, bool Texture>
__device__ __forceinline__ std::uint32_t decode_code(
    const std::uint32_t *global_words, cudaTextureObject_t texture,
    std::uint32_t index) {
  if constexpr (!Packed) {
    const std::uint32_t word =
        load_word<Texture>(global_words, texture, index >> 1u);
    return (word >> ((index & 1u) * 16u)) & 63u;
  } else {
    const std::uint32_t bit = index * 6u;
    const std::uint32_t word_index = bit >> 5u;
    const std::uint32_t shift = bit & 31u;
    const std::uint32_t low =
        load_word<Texture>(global_words, texture, word_index);
    if (shift <= 26u)
      return (low >> shift) & 63u;
    const std::uint32_t high =
        load_word<Texture>(global_words, texture, word_index + 1u);
    return ((low >> shift) | (high << (32u - shift))) & 63u;
  }
}

template <int Steps, bool Packed, bool Texture>
__global__ void lookup_codes(const std::uint32_t *global_words,
                             cudaTextureObject_t texture,
                             std::uint32_t entries,
                             std::uint32_t sample_seed,
                             LookupResult *results) {
  const std::uint32_t lane = threadIdx.x;
  const std::uint32_t warp = blockIdx.x;
  const std::uint32_t output = warp * kWarpSize + lane;
  const std::uint32_t seed = initial_state(lane, warp, sample_seed);
  std::uint32_t state = seed;
  std::uint32_t mismatches = 0u;
  asm volatile("" ::: "memory");
  const unsigned long long started = clock64();
#pragma unroll 1
  for (int step = 0; step < Steps; ++step) {
    state = state * kLcgMul + kLcgAdd;
    const std::uint32_t index =
        std::uint32_t((std::uint64_t(state) * entries) >> 32u);
    const std::uint32_t code =
        decode_code<Packed, Texture>(global_words, texture, index);
    mismatches += std::uint32_t(code != code_for(index));
  }
  const unsigned long long finished = clock64();
  asm volatile("" ::: "memory");
  LookupResult result{};
  result.started = started;
  result.finished = finished;
  result.final_state = state;
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

std::uint32_t advance_lcg(std::uint32_t state, std::uint32_t steps) {
  std::uint32_t acc_mul = 1u, acc_add = 0u;
  std::uint32_t cur_mul = kLcgMul, cur_add = kLcgAdd;
  while (steps) {
    if (steps & 1u) {
      acc_add = cur_mul * acc_add + cur_add;
      acc_mul = cur_mul * acc_mul;
    }
    cur_add = cur_mul * cur_add + cur_add;
    cur_mul = cur_mul * cur_mul;
    steps >>= 1u;
  }
  return acc_mul * state + acc_add;
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
  const char *representation;
  bool texture;
  bool packed;
};

constexpr Mode kModes[4] = {
    {"global_cg", "slot16", false, false},
    {"global_cg", "packed6", false, true},
    {"texture_object", "slot16", true, false},
    {"texture_object", "packed6", true, true}};

constexpr int kOrders[4][4] = {
    {0, 1, 2, 3}, {3, 2, 1, 0}, {1, 0, 3, 2}, {2, 3, 0, 1}};

struct Row {
  std::string path, representation;
  std::uint32_t entries = 0;
  std::size_t table_bytes = 0;
  int warps = 0, threads = 0, samples = 0;
  double bytes_per_code = 0, expected_words_per_lookup = 0;
  std::size_t validated_control = 0, validated_cold = 0, validated_hot = 0;
  Distribution control_cycles, cold_cycles, hot_cycles, cold_kernel_us,
      hot_kernel_us;
  double cold_net_cycles_per_lookup = 0, hot_net_cycles_per_lookup = 0;
  double cold_glookups_s = 0, hot_glookups_s = 0;
  double cold_requested_word_gloads_s = 0, hot_requested_word_gloads_s = 0;
  bool valid = false;
};

void validate_results(const std::vector<LookupResult> &results,
                      std::uint32_t sample_seed, std::uint32_t steps,
                      std::vector<double> &cycles, std::size_t &validated) {
  for (std::size_t output = 0; output < results.size(); ++output) {
    const std::uint32_t warp = std::uint32_t(output / kWarpSize);
    const std::uint32_t lane = std::uint32_t(output % kWarpSize);
    const std::uint32_t seed = initial_state(lane, warp, sample_seed);
    const auto &actual = results[output];
    if (actual.final_state == advance_lcg(seed, steps) &&
        actual.mismatch_count == 0 && actual.seed == seed &&
        actual.steps == steps && actual.finished >= actual.started)
      ++validated;
    cycles.push_back(double(actual.finished - actual.started));
  }
}

template <int Steps>
void launch_mode(int mode, int warps, const std::uint32_t *slot_words,
                 const std::uint32_t *packed_words,
                 cudaTextureObject_t slot_texture,
                 cudaTextureObject_t packed_texture, std::uint32_t entries,
                 std::uint32_t seed, LookupResult *output) {
  switch (mode) {
  case 0:
    lookup_codes<Steps, false, false><<<warps, kWarpSize>>>(
        slot_words, 0, entries, seed, output);
    break;
  case 1:
    lookup_codes<Steps, true, false><<<warps, kWarpSize>>>(
        packed_words, 0, entries, seed, output);
    break;
  case 2:
    lookup_codes<Steps, false, true><<<warps, kWarpSize>>>(
        slot_words, slot_texture, entries, seed, output);
    break;
  case 3:
    lookup_codes<Steps, true, true><<<warps, kWarpSize>>>(
        packed_words, packed_texture, entries, seed, output);
    break;
  default:
    throw std::runtime_error("invalid mode");
  }
}

void launch_measurement(int mode, int warps, const std::uint32_t *slot_words,
                        const std::uint32_t *packed_words,
                        cudaTextureObject_t slot_texture,
                        cudaTextureObject_t packed_texture,
                        std::uint32_t entries, std::uint32_t seed,
                        LookupResult *control, LookupResult *cold,
                        LookupResult *hot, cudaEvent_t cold_start,
                        cudaEvent_t cold_end, cudaEvent_t hot_start,
                        cudaEvent_t hot_end) {
  launch_mode<0>(mode, warps, slot_words, packed_words, slot_texture,
                 packed_texture, entries, seed, control);
  cuda_check(cudaEventRecord(cold_start), "cudaEventRecord(cold start)");
  launch_mode<kSteps>(mode, warps, slot_words, packed_words, slot_texture,
                      packed_texture, entries, seed, cold);
  cuda_check(cudaEventRecord(cold_end), "cudaEventRecord(cold end)");
  cuda_check(cudaEventRecord(hot_start), "cudaEventRecord(hot start)");
  launch_mode<kSteps>(mode, warps, slot_words, packed_words, slot_texture,
                      packed_texture, entries, seed, hot);
  cuda_check(cudaEventRecord(hot_end), "cudaEventRecord(hot end)");
  cuda_check(cudaGetLastError(), "lookup kernel launch");
}

Row finalize_row(const Args &args, const Mode &mode, std::uint32_t entries,
                 std::size_t table_bytes, int warps,
                 const Accumulator &data) {
  Row row{};
  row.path = mode.path;
  row.representation = mode.representation;
  row.entries = entries;
  row.table_bytes = table_bytes;
  row.warps = warps;
  row.threads = warps * int(kWarpSize);
  row.samples = args.samples;
  row.bytes_per_code = double(table_bytes) / entries;
  row.expected_words_per_lookup = mode.packed ? 1.125 : 1.0;
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
  const std::size_t expected =
      std::size_t(args.samples) * std::size_t(row.threads);
  row.valid = data.valid_control == expected && data.valid_cold == expected &&
              data.valid_hot == expected;
  return row;
}

std::vector<Row> run_case(const Args &args, std::uint32_t entries, int warps,
                          const std::uint32_t *eviction,
                          std::size_t eviction_entries,
                          cudaTextureObject_t eviction_texture,
                          std::uint32_t *eviction_sink, int eviction_blocks) {
  const std::size_t slot_words_count = entries / 2u;
  const std::size_t packed_words_count = std::size_t(entries / 16u) * 3u;
  const std::size_t slot_bytes = slot_words_count * sizeof(std::uint32_t);
  const std::size_t packed_bytes = packed_words_count * sizeof(std::uint32_t);
  const std::size_t threads = std::size_t(warps) * kWarpSize;
  std::uint32_t *slot_words = nullptr, *packed_words = nullptr;
  LookupResult *device_control = nullptr, *device_cold = nullptr,
               *device_hot = nullptr;
  cuda_check(cudaMalloc(&slot_words, slot_bytes), "cudaMalloc(slot16 table)");
  cuda_check(cudaMalloc(&packed_words, packed_bytes), "cudaMalloc(packed6 table)");
  cuda_check(cudaMalloc(&device_control, threads * sizeof(LookupResult)),
             "cudaMalloc(control output)");
  cuda_check(cudaMalloc(&device_cold, threads * sizeof(LookupResult)),
             "cudaMalloc(cold output)");
  cuda_check(cudaMalloc(&device_hot, threads * sizeof(LookupResult)),
             "cudaMalloc(hot output)");
  initialize_slot16<<<int((slot_words_count + 255) / 256), 256>>>(slot_words,
                                                                  entries);
  initialize_packed6<<<int((entries / 16u + 255) / 256), 256>>>(packed_words,
                                                                entries);
  cuda_check(cudaGetLastError(), "table initialization launch");
  cuda_check(cudaDeviceSynchronize(), "table initialization sync");
  const cudaTextureObject_t slot_texture =
      make_linear_texture(slot_words, slot_bytes);
  const cudaTextureObject_t packed_texture =
      make_linear_texture(packed_words, packed_bytes);
  cudaEvent_t cold_start{}, cold_end{}, hot_start{}, hot_end{};
  cuda_check(cudaEventCreate(&cold_start), "cudaEventCreate(cold start)");
  cuda_check(cudaEventCreate(&cold_end), "cudaEventCreate(cold end)");
  cuda_check(cudaEventCreate(&hot_start), "cudaEventCreate(hot start)");
  cuda_check(cudaEventCreate(&hot_end), "cudaEventCreate(hot end)");
  std::vector<LookupResult> control(threads), cold(threads), hot(threads);
  Accumulator accumulators[4];
  for (int sample = -args.warmup; sample < args.samples; ++sample) {
    const std::uint32_t sample_seed =
        mix32(std::uint32_t(sample + args.warmup + 1) * 0xc2b2ae35u);
    for (int position = 0; position < 4; ++position) {
      const int mode = kOrders[args.order][position];
      evict_global<<<eviction_blocks, 256>>>(eviction, eviction_entries,
                                             eviction_sink);
      if (kModes[mode].texture)
        evict_texture<<<eviction_blocks, 256>>>(
            eviction_texture, eviction_entries, eviction_sink);
      launch_measurement(mode, warps, slot_words, packed_words, slot_texture,
                         packed_texture, entries, sample_seed, device_control,
                         device_cold, device_hot, cold_start, cold_end,
                         hot_start, hot_end);
      cuda_check(cudaMemcpy(control.data(), device_control,
                            threads * sizeof(LookupResult),
                            cudaMemcpyDeviceToHost),
                 "cudaMemcpy(control result)");
      cuda_check(cudaMemcpy(cold.data(), device_cold,
                            threads * sizeof(LookupResult),
                            cudaMemcpyDeviceToHost),
                 "cudaMemcpy(cold result)");
      cuda_check(cudaMemcpy(hot.data(), device_hot,
                            threads * sizeof(LookupResult),
                            cudaMemcpyDeviceToHost),
                 "cudaMemcpy(hot result)");
      float cold_ms = 0, hot_ms = 0;
      cuda_check(cudaEventElapsedTime(&cold_ms, cold_start, cold_end),
                 "cudaEventElapsedTime(cold)");
      cuda_check(cudaEventElapsedTime(&hot_ms, hot_start, hot_end),
                 "cudaEventElapsedTime(hot)");
      if (sample >= 0) {
        auto &data = accumulators[mode];
        validate_results(control, sample_seed, 0, data.control_cycles,
                         data.valid_control);
        validate_results(cold, sample_seed, kSteps, data.cold_cycles,
                         data.valid_cold);
        validate_results(hot, sample_seed, kSteps, data.hot_cycles,
                         data.valid_hot);
        data.cold_us.push_back(double(cold_ms) * 1000.0);
        data.hot_us.push_back(double(hot_ms) * 1000.0);
      }
    }
  }
  std::vector<Row> rows;
  for (int mode = 0; mode < 4; ++mode)
    rows.push_back(finalize_row(args, kModes[mode], entries,
                                kModes[mode].packed ? packed_bytes : slot_bytes,
                                warps, accumulators[mode]));
  cudaEventDestroy(cold_start);
  cudaEventDestroy(cold_end);
  cudaEventDestroy(hot_start);
  cudaEventDestroy(hot_end);
  cudaDestroyTextureObject(slot_texture);
  cudaDestroyTextureObject(packed_texture);
  cudaFree(device_hot);
  cudaFree(device_cold);
  cudaFree(device_control);
  cudaFree(packed_words);
  cudaFree(slot_words);
  return rows;
}

void write_distribution(std::ostream &out, const Distribution &d) {
  out << "{\"min\": " << d.minimum << ", \"mean\": " << d.mean
      << ", \"p50\": " << d.p50 << ", \"p95\": " << d.p95
      << ", \"p99\": " << d.p99 << ", \"max\": " << d.maximum << '}';
}

void write_results(const Args &args, const cudaDeviceProp &properties,
                   const int occupancy[4], const std::vector<Row> &rows) {
  fs::create_directories(args.out_dir);
  std::ofstream json(args.out_dir / "cuda_packed_log_lut_results.json");
  json << std::fixed << std::setprecision(6)
       << "{\n  \"schema\": \"UGTS-CUDA-PACKED-LOG-LUT-1.0\",\n"
          "  \"runtime\": \"CUDA sm_120 matched 16-bit-slot and dense "
          "6-bit log-code lookups through LDG and TLD\",\n"
          "  \"device\": {\"name\": \""
       << properties.name << "\", \"compute_capability\": \""
       << properties.major << '.' << properties.minor << "\", \"l2_bytes\": "
       << properties.l2CacheSize << ", \"multiprocessors\": "
       << properties.multiProcessorCount
       << ", \"max_texture_1d_linear_elements\": "
       << properties.maxTexture1DLinear
       << ", \"occupancy_blocks_per_sm\": {\"global_slot16\": "
       << occupancy[0] << ", \"global_packed6\": " << occupancy[1]
       << ", \"texture_slot16\": " << occupancy[2]
       << ", \"texture_packed6\": " << occupancy[3] << "}},\n"
          "  \"run_parameters\": {\"warmup_sets\": "
       << args.warmup << ", \"measured_sets\": " << args.samples
       << ", \"lookups_per_thread\": " << kSteps
       << ", \"eviction_bytes\": " << args.eviction_mib * 1024 * 1024
       << ", \"latin_order\": " << args.order << "},\n"
          "  \"semantics\": \"slot16 stores two 6-bit codes in 16-bit slots "
          "per u32; packed6 stores sixteen codes in exactly three u32 words. "
          "Every loaded code is checked on-GPU against index mod 64 and every "
          "final LCG state is independently validated on CPU. Rates count "
          "logical decoded codes; requested word rates are representation-level "
          "u32 requests, not physical cache transactions.\",\n"
          "  \"results\": [\n";
  for (std::size_t i = 0; i < rows.size(); ++i) {
    const auto &row = rows[i];
    json << "    {\"path\": \"" << row.path
         << "\", \"representation\": \"" << row.representation
         << "\", \"entries\": " << row.entries
         << ", \"table_bytes\": " << row.table_bytes
         << ", \"table_mib\": " << double(row.table_bytes) / (1024 * 1024)
         << ", \"l2_fraction\": "
         << double(row.table_bytes) / properties.l2CacheSize
         << ", \"bytes_per_code\": " << row.bytes_per_code
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
  std::ofstream csv(args.out_dir / "cuda_packed_log_lut_results.csv");
  csv << "path,representation,entries,table_bytes,table_mib,l2_fraction,"
         "bytes_per_code,expected_words_per_lookup,warps,warps_per_sm,threads,"
         "samples,control_p50_cycles,cold_p50_cycles,hot_p50_cycles,"
         "cold_net_cycles_per_lookup,hot_net_cycles_per_lookup,"
         "cold_kernel_p50_us,hot_kernel_p50_us,cold_glookups_s,hot_glookups_s,"
         "cold_requested_word_gloads_s,hot_requested_word_gloads_s,"
         "validated_control,validated_cold,validated_hot,validation\n"
      << std::fixed << std::setprecision(6);
  for (const auto &row : rows)
    csv << row.path << ',' << row.representation << ',' << row.entries << ','
        << row.table_bytes << ',' << double(row.table_bytes) / (1024 * 1024)
        << ',' << double(row.table_bytes) / properties.l2CacheSize << ','
        << row.bytes_per_code << ',' << row.expected_words_per_lookup << ','
        << row.warps << ','
        << double(row.warps) / properties.multiProcessorCount << ','
        << row.threads << ',' << row.samples << ',' << row.control_cycles.p50
        << ',' << row.cold_cycles.p50 << ',' << row.hot_cycles.p50 << ','
        << row.cold_net_cycles_per_lookup << ',' << row.hot_net_cycles_per_lookup
        << ',' << row.cold_kernel_us.p50 << ',' << row.hot_kernel_us.p50 << ','
        << row.cold_glookups_s << ',' << row.hot_glookups_s << ','
        << row.cold_requested_word_gloads_s << ','
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
    for (auto entries : args.entries) {
      const std::size_t slot_words = entries / 2u;
      const std::size_t packed_words = std::size_t(entries / 16u) * 3u;
      if (slot_words > std::size_t(properties.maxTexture1DLinear) ||
          packed_words > std::size_t(properties.maxTexture1DLinear))
        throw std::runtime_error("table exceeds maxTexture1DLinear");
    }
    int occupancy[4]{};
    cuda_check(cudaOccupancyMaxActiveBlocksPerMultiprocessor(
                   &occupancy[0], lookup_codes<kSteps, false, false>, kWarpSize,
                   0),
               "global slot16 occupancy query");
    cuda_check(cudaOccupancyMaxActiveBlocksPerMultiprocessor(
                   &occupancy[1], lookup_codes<kSteps, true, false>, kWarpSize,
                   0),
               "global packed6 occupancy query");
    cuda_check(cudaOccupancyMaxActiveBlocksPerMultiprocessor(
                   &occupancy[2], lookup_codes<kSteps, false, true>, kWarpSize,
                   0),
               "texture slot16 occupancy query");
    cuda_check(cudaOccupancyMaxActiveBlocksPerMultiprocessor(
                   &occupancy[3], lookup_codes<kSteps, true, true>, kWarpSize,
                   0),
               "texture packed6 occupancy query");
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
    std::cout << "CUDA packed log-LUT device: " << properties.name << " sm_"
              << properties.major << properties.minor << " L2="
              << properties.l2CacheSize << " bytes SMs="
              << properties.multiProcessorCount << " occupancy="
              << occupancy[0] << '/' << occupancy[1] << '/' << occupancy[2]
              << '/' << occupancy[3] << " order=" << args.order << '\n';
    std::vector<Row> rows;
    for (auto entries : args.entries) {
      for (auto warps : args.warps) {
        auto group = run_case(args, entries, warps, eviction, eviction_entries,
                              eviction_texture, eviction_sink, eviction_blocks);
        const Row &gs = group[0], &gp = group[1], &ts = group[2], &tp = group[3];
        std::cout << std::setw(9) << entries << " codes " << std::setw(4)
                  << warps << " warps hot packed/slot global=" << std::fixed
                  << std::setprecision(3) << gp.hot_glookups_s << '/'
                  << gs.hot_glookups_s << '='
                  << gp.hot_glookups_s / gs.hot_glookups_s << " texture="
                  << tp.hot_glookups_s << '/' << ts.hot_glookups_s << '='
                  << tp.hot_glookups_s / ts.hot_glookups_s << " valid="
                  << (std::all_of(group.begin(), group.end(),
                                  [](const Row &row) { return row.valid; })
                          ? "yes"
                          : "no")
                  << '\n';
        rows.insert(rows.end(), group.begin(), group.end());
      }
    }
    write_results(args, properties, occupancy, rows);
    cudaDestroyTextureObject(eviction_texture);
    cudaFree(eviction_sink);
    cudaFree(eviction);
    const bool valid = std::all_of(rows.begin(), rows.end(),
                                   [](const Row &row) { return row.valid; });
    return valid ? 0 : 2;
  } catch (const std::exception &error) {
    std::cerr << "UGTS CUDA packed log-LUT benchmark error: " << error.what()
              << '\n';
    return 1;
  }
}
