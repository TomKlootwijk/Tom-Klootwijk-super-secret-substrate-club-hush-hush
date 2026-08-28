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
constexpr std::uint32_t kAddressRegionBytes = 32;
constexpr std::uint32_t kCpuValidatedThreads = 32;
constexpr std::uint32_t kLcgMul = 1664525u;
constexpr std::uint32_t kLcgAdd = 1013904223u;

void cuda_check(cudaError_t result, const char *what) {
  if (result != cudaSuccess)
    throw std::runtime_error(std::string(what) + ": " +
                             cudaGetErrorString(result));
}

struct Args {
  fs::path out_dir = "cuda_lut_sparse_address_out";
  std::vector<std::uint32_t> target_mib = {
      4, 8, 9, 10, 11, 12, 13, 14, 15, 16,
      18, 20, 24, 28, 32, 36, 40, 48};
  std::vector<std::uint32_t> stride_bytes = {32, 64, 128, 256};
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
    else if (arg == "--target-mib")
      args.target_mib = parse_list<std::uint32_t>(value("--target-mib"));
    else if (arg == "--stride-bytes")
      args.stride_bytes =
          parse_list<std::uint32_t>(value("--stride-bytes"));
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
    throw std::runtime_error("invalid sparse-address run parameters");
  for (auto target : args.target_mib)
    if (target < 1 || target > 64)
      throw std::runtime_error("target MiB must be in [1, 64]");
  for (auto stride : args.stride_bytes)
    if (stride < 32 || stride > 4096 || stride % 32u != 0)
      throw std::runtime_error(
          "stride must be a multiple of 32 in [32, 4096]");
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
    std::uint32_t region) {
  return mix32(region ^ 0x6a09e667u) & 63u;
}

__host__ __device__ __forceinline__ std::uint32_t roll_checksum(
    std::uint32_t checksum, std::uint32_t code, std::uint32_t region) {
  return (checksum ^ code ^ (region * 0x9e3779b9u)) * 16777619u +
         0x27d4eb2du;
}

__device__ __forceinline__ std::uint32_t load_global_l2(
    const std::uint32_t *address) {
  std::uint32_t value;
  asm volatile("ld.global.cg.u32 %0, [%1];" : "=r"(value) : "l"(address));
  return value;
}

__global__ void initialize_filler(std::uint32_t *words,
                                  std::uint64_t word_count,
                                  std::uint32_t seed) {
  const std::uint64_t word =
      threadIdx.x + std::uint64_t(blockIdx.x) * blockDim.x;
  if (word < word_count)
    words[word] = mix32(seed ^ std::uint32_t(word)) ^
                  mix32(std::uint32_t(word >> 32) + 0x9e3779b9u);
}

__global__ void initialize_codes(std::uint32_t *words,
                                 std::uint32_t regions,
                                 std::uint32_t stride_words) {
  const std::uint32_t region = threadIdx.x + blockIdx.x * blockDim.x;
  if (region >= regions)
    return;
  const std::uint64_t address = std::uint64_t(region) * stride_words;
  words[address] = (words[address] & ~63u) | code_for(region);
}

struct alignas(16) LookupResult {
  unsigned long long started;
  unsigned long long finished;
  std::uint32_t final_state;
  std::uint32_t checksum;
  std::uint32_t mismatch_count;
  std::uint32_t seed;
  std::uint32_t steps;
  std::uint32_t reserved;
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
    std::uint64_t index) {
  if constexpr (Texture)
    return tex1Dfetch<std::uint32_t>(texture, int(index));
  else
    return load_global_l2(global_words + index);
}

template <int Steps, bool Texture>
__global__ void lookup_sparse_codes(const std::uint32_t *global_words,
                                    cudaTextureObject_t texture,
                                    std::uint32_t regions,
                                    std::uint32_t stride_words,
                                    std::uint32_t sample_seed,
                                    LookupResult *results) {
  const std::uint32_t lane = threadIdx.x;
  const std::uint32_t warp = blockIdx.x;
  const std::uint32_t output = warp * kWarpSize + lane;
  const std::uint32_t seed = initial_seed(lane, warp, sample_seed);
  std::uint32_t state = seed;
  std::uint32_t checksum = seed ^ 0x3c6ef372u;
  std::uint32_t mismatches = 0u;
  asm volatile("" ::: "memory");
  const unsigned long long started = clock64();
#pragma unroll 1
  for (int step = 0; step < Steps; ++step) {
    state = state * kLcgMul + kLcgAdd;
    const std::uint32_t region = __umulhi(state, regions);
    const std::uint64_t address = std::uint64_t(region) * stride_words;
    const std::uint32_t code =
        load_word<Texture>(global_words, texture, address) & 63u;
    mismatches += std::uint32_t(code != code_for(region));
    checksum = roll_checksum(checksum, code, region);
  }
  const unsigned long long finished = clock64();
  asm volatile("" ::: "memory");
  LookupResult result{};
  result.started = started;
  result.finished = finished;
  result.final_state = state;
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
  cudaTextureDesc descriptor{};
  descriptor.readMode = cudaReadModeElementType;
  cudaTextureObject_t texture = 0;
  cuda_check(cudaCreateTextureObject(&texture, &resource, &descriptor, nullptr),
             "cudaCreateTextureObject");
  return texture;
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
    throw std::runtime_error("empty distribution");
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

struct Expected {
  std::uint32_t final_state = 0;
  std::uint32_t checksum = 0;
};

Expected replay(std::uint32_t seed, std::uint32_t regions,
                std::uint32_t steps) {
  std::uint32_t state = seed;
  std::uint32_t checksum = seed ^ 0x3c6ef372u;
  for (std::uint32_t step = 0; step < steps; ++step) {
    state = state * kLcgMul + kLcgAdd;
    const std::uint32_t region =
        std::uint32_t((std::uint64_t(state) * regions) >> 32u);
    checksum = roll_checksum(checksum, code_for(region), region);
  }
  return {state, checksum};
}

void validate_results(const std::vector<LookupResult> &results,
                      std::uint32_t sample_seed, std::uint32_t regions,
                      std::uint32_t steps, std::vector<double> &cycles,
                      std::size_t &validated) {
  const std::size_t count =
      std::min<std::size_t>(results.size(), kCpuValidatedThreads);
  for (std::size_t output = 0; output < count; ++output) {
    const std::uint32_t warp = std::uint32_t(output / kWarpSize);
    const std::uint32_t lane = std::uint32_t(output % kWarpSize);
    const std::uint32_t seed = initial_seed(lane, warp, sample_seed);
    const Expected expected = replay(seed, regions, steps);
    const auto &actual = results[output];
    if (actual.final_state == expected.final_state &&
        actual.checksum == expected.checksum && actual.mismatch_count == 0u &&
        actual.seed == seed && actual.steps == steps &&
        actual.finished >= actual.started)
      ++validated;
    cycles.push_back(double(actual.finished - actual.started));
  }
}

enum class Mode { Global, Texture };

template <int Steps>
void launch_mode(Mode mode, int warps, const std::uint32_t *words,
                 cudaTextureObject_t texture, std::uint32_t regions,
                 std::uint32_t stride_words, std::uint32_t seed,
                 LookupResult *output) {
  if (mode == Mode::Global)
    lookup_sparse_codes<Steps, false><<<warps, kWarpSize>>>(
        words, 0, regions, stride_words, seed, output);
  else
    lookup_sparse_codes<Steps, true><<<warps, kWarpSize>>>(
        words, texture, regions, stride_words, seed, output);
}

struct Row {
  std::string path;
  std::uint32_t target_mib = 0, stride_bytes = 0, regions = 0;
  std::uint64_t allocation_bytes = 0, hypothetical_128b_bytes = 0;
  int warps = 0, threads = 0, samples = 0;
  std::size_t validated_control = 0, validated_cold = 0, validated_hot = 0;
  Distribution control_cycles, cold_cycles, hot_cycles, cold_us, hot_us;
  double cold_net_cycles_per_lookup = 0, hot_net_cycles_per_lookup = 0;
  double cold_glookups_s = 0, hot_glookups_s = 0;
  bool valid = false;
};

Row make_row(const Args &args, Mode mode, std::uint32_t target_mib,
             std::uint32_t stride_bytes, std::uint32_t regions, int warps,
             const Accumulator &data) {
  Row row{};
  row.path = mode == Mode::Global ? "global_cg" : "texture_object";
  row.target_mib = target_mib;
  row.stride_bytes = stride_bytes;
  row.regions = regions;
  row.allocation_bytes = std::uint64_t(regions) * stride_bytes;
  row.hypothetical_128b_bytes =
      std::uint64_t(regions) * std::min<std::uint32_t>(stride_bytes, 128u);
  row.warps = warps;
  row.threads = warps * int(kWarpSize);
  row.samples = args.samples;
  row.validated_control = data.valid_control;
  row.validated_cold = data.valid_cold;
  row.validated_hot = data.valid_hot;
  row.control_cycles = summarize(data.control_cycles);
  row.cold_cycles = summarize(data.cold_cycles);
  row.hot_cycles = summarize(data.hot_cycles);
  row.cold_us = summarize(data.cold_us);
  row.hot_us = summarize(data.hot_us);
  row.cold_net_cycles_per_lookup =
      (row.cold_cycles.p50 - row.control_cycles.p50) / kSteps;
  row.hot_net_cycles_per_lookup =
      (row.hot_cycles.p50 - row.control_cycles.p50) / kSteps;
  const double lookups = double(row.threads) * kSteps;
  row.cold_glookups_s = lookups / (row.cold_us.p50 * 1e-6) / 1e9;
  row.hot_glookups_s = lookups / (row.hot_us.p50 * 1e-6) / 1e9;
  const std::size_t expected = std::size_t(args.samples) *
                               std::min<std::size_t>(row.threads,
                                                     kCpuValidatedThreads);
  row.valid = data.valid_control == expected && data.valid_cold == expected &&
              data.valid_hot == expected;
  return row;
}

Row run_case(const Args &args, Mode mode, std::uint32_t target_mib,
             std::uint32_t stride_bytes, int warps,
             const std::uint32_t *eviction,
             cudaTextureObject_t eviction_texture,
             std::size_t eviction_entries, std::uint32_t *eviction_sink,
             int eviction_blocks, std::size_t max_texture_words) {
  const std::uint64_t target_bytes = std::uint64_t(target_mib) * 1024 * 1024;
  const std::uint32_t regions =
      std::uint32_t(target_bytes / kAddressRegionBytes);
  const std::uint32_t stride_words = stride_bytes / sizeof(std::uint32_t);
  const std::uint64_t allocation_bytes = std::uint64_t(regions) * stride_bytes;
  const std::uint64_t allocation_words = allocation_bytes / sizeof(std::uint32_t);
  if (allocation_words > max_texture_words)
    throw std::runtime_error("allocation exceeds maxTexture1DLinear");
  const std::size_t threads = std::size_t(warps) * kWarpSize;
  std::uint32_t *table = nullptr;
  LookupResult *device_control = nullptr, *device_cold = nullptr,
               *device_hot = nullptr;
  cuda_check(cudaMalloc(&table, allocation_bytes), "cudaMalloc(sparse table)");
  cuda_check(cudaMalloc(&device_control, threads * sizeof(LookupResult)),
             "cudaMalloc(control output)");
  cuda_check(cudaMalloc(&device_cold, threads * sizeof(LookupResult)),
             "cudaMalloc(cold output)");
  cuda_check(cudaMalloc(&device_hot, threads * sizeof(LookupResult)),
             "cudaMalloc(hot output)");
  initialize_filler<<<int((allocation_words + 255) / 256), 256>>>(
      table, allocation_words,
      mix32(target_mib * 0x9e3779b9u ^ stride_bytes));
  initialize_codes<<<int((std::uint64_t(regions) + 255) / 256), 256>>>(
      table, regions, stride_words);
  cuda_check(cudaGetLastError(), "sparse-address initialization launch");
  cuda_check(cudaDeviceSynchronize(), "sparse-address initialization sync");
  const cudaTextureObject_t texture =
      make_linear_texture(table, std::size_t(allocation_bytes));
  cudaEvent_t cold_start{}, cold_end{}, hot_start{}, hot_end{};
  cuda_check(cudaEventCreate(&cold_start), "cudaEventCreate(cold start)");
  cuda_check(cudaEventCreate(&cold_end), "cudaEventCreate(cold end)");
  cuda_check(cudaEventCreate(&hot_start), "cudaEventCreate(hot start)");
  cuda_check(cudaEventCreate(&hot_end), "cudaEventCreate(hot end)");
  const std::size_t copied_threads =
      std::min<std::size_t>(threads, kCpuValidatedThreads);
  std::vector<LookupResult> control(copied_threads), cold(copied_threads),
      hot(copied_threads);
  Accumulator data;
  for (int sample = -args.warmup; sample < args.samples; ++sample) {
    const std::uint32_t sample_seed =
        mix32(std::uint32_t(sample + args.warmup + 1) * 0xc2b2ae35u ^
              target_mib * 0x27d4eb2du ^ stride_bytes);
    if (mode == Mode::Global)
      evict_global<<<eviction_blocks, 256>>>(eviction, eviction_entries,
                                             eviction_sink);
    else
      evict_texture<<<eviction_blocks, 256>>>(
          eviction_texture, eviction_entries, eviction_sink);
    launch_mode<0>(mode, warps, table, texture, regions, stride_words,
                   sample_seed, device_control);
    cuda_check(cudaEventRecord(cold_start), "cudaEventRecord(cold start)");
    launch_mode<kSteps>(mode, warps, table, texture, regions, stride_words,
                        sample_seed, device_cold);
    cuda_check(cudaEventRecord(cold_end), "cudaEventRecord(cold end)");
    cuda_check(cudaEventRecord(hot_start), "cudaEventRecord(hot start)");
    launch_mode<kSteps>(mode, warps, table, texture, regions, stride_words,
                        sample_seed, device_hot);
    cuda_check(cudaEventRecord(hot_end), "cudaEventRecord(hot end)");
    cuda_check(cudaGetLastError(), "sparse-address lookup launch");
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
      validate_results(control, sample_seed, regions, 0, data.control_cycles,
                       data.valid_control);
      validate_results(cold, sample_seed, regions, kSteps, data.cold_cycles,
                       data.valid_cold);
      validate_results(hot, sample_seed, regions, kSteps, data.hot_cycles,
                       data.valid_hot);
      data.cold_us.push_back(double(cold_ms) * 1000.0);
      data.hot_us.push_back(double(hot_ms) * 1000.0);
    }
  }
  cudaEventDestroy(cold_start);
  cudaEventDestroy(cold_end);
  cudaEventDestroy(hot_start);
  cudaEventDestroy(hot_end);
  cudaDestroyTextureObject(texture);
  cudaFree(device_control);
  cudaFree(device_cold);
  cudaFree(device_hot);
  cudaFree(table);
  return make_row(args, mode, target_mib, stride_bytes, regions, warps, data);
}

void write_distribution(std::ostream &stream, const Distribution &value) {
  stream << "{\"min\": " << value.minimum << ", \"mean\": " << value.mean
         << ", \"p50\": " << value.p50 << ", \"p95\": " << value.p95
         << ", \"p99\": " << value.p99 << ", \"max\": " << value.maximum
         << '}';
}

void write_results(const Args &args, const cudaDeviceProp &properties,
                   int global_occupancy, int texture_occupancy,
                   const std::vector<Row> &rows) {
  fs::create_directories(args.out_dir);
  std::ofstream json(args.out_dir / "cuda_lut_sparse_address_results.json");
  json << std::fixed << std::setprecision(6);
  json << "{\n  \"schema\": \"UGTS-CUDA-LUT-SPARSE-ADDRESS-1.0\",\n"
          "  \"device\": {\"name\": \""
       << properties.name << "\", \"compute_capability\": \""
       << properties.major << '.' << properties.minor << "\", \"l2_bytes\": "
       << properties.l2CacheSize << ", \"multiprocessors\": "
       << properties.multiProcessorCount
       << ", \"max_texture_1d_linear_elements\": "
       << properties.maxTexture1DLinear
       << ", \"occupancy_blocks_per_sm\": {\"global_cg\": "
       << global_occupancy << ", \"texture_object\": " << texture_occupancy
       << "}},\n  \"run_parameters\": {\"address_region_bytes\": "
       << kAddressRegionBytes << ", \"lookups_per_thread\": " << kSteps
       << ", \"eviction_bytes\": " << args.eviction_mib * 1024 * 1024
       << ", \"warmup_sets\": " << args.warmup
       << ", \"measured_sets\": " << args.samples
       << ", \"path_order\": " << args.order
       << "},\n  \"semantics\": \"Each independently selected region contributes one packed6 code in its first word; all gaps contain deterministic mixed filler. target_mib equals regions times 32 address bytes, while allocation_bytes records actual spacing.\",\n"
          "  \"results\": [\n";
  for (std::size_t i = 0; i < rows.size(); ++i) {
    const auto &row = rows[i];
    json << "    {\"path\": \"" << row.path << "\", \"target_mib\": "
         << row.target_mib << ", \"address_region_bytes\": "
         << kAddressRegionBytes << ", \"stride_bytes\": " << row.stride_bytes
         << ", \"regions\": " << row.regions
         << ", \"unique_code_bytes\": " << std::uint64_t(row.regions)
         << ", \"unique_word_bytes\": " << std::uint64_t(row.regions) * 4u
         << ", \"address_span_32b_bytes\": "
         << std::uint64_t(row.regions) * kAddressRegionBytes
         << ", \"hypothetical_128b_residency_bytes\": "
         << row.hypothetical_128b_bytes << ", \"allocation_bytes\": "
         << row.allocation_bytes << ", \"allocation_mib\": "
         << double(row.allocation_bytes) / (1024.0 * 1024.0)
         << ", \"warps\": " << row.warps << ", \"warps_per_sm\": "
         << double(row.warps) / properties.multiProcessorCount
         << ", \"threads\": " << row.threads << ", \"samples\": "
         << row.samples << ", \"control_cycles\": ";
    write_distribution(json, row.control_cycles);
    json << ", \"cold_cycles\": ";
    write_distribution(json, row.cold_cycles);
    json << ", \"hot_cycles\": ";
    write_distribution(json, row.hot_cycles);
    json << ", \"cold_kernel_us\": ";
    write_distribution(json, row.cold_us);
    json << ", \"hot_kernel_us\": ";
    write_distribution(json, row.hot_us);
    json << ", \"cold_net_cycles_per_lookup\": "
         << row.cold_net_cycles_per_lookup
         << ", \"hot_net_cycles_per_lookup\": "
         << row.hot_net_cycles_per_lookup << ", \"cold_glookups_s\": "
         << row.cold_glookups_s << ", \"hot_glookups_s\": "
         << row.hot_glookups_s << ", \"validated_control\": "
         << row.validated_control << ", \"validated_cold\": "
         << row.validated_cold << ", \"validated_hot\": "
         << row.validated_hot << ", \"validation\": "
         << (row.valid ? "true" : "false") << '}'
         << (i + 1 == rows.size() ? "\n" : ",\n");
  }
  json << "  ]\n}\n";

  std::ofstream csv(args.out_dir / "cuda_lut_sparse_address_results.csv");
  csv << "path,target_mib,address_region_bytes,stride_bytes,regions,"
         "unique_code_bytes,unique_word_bytes,address_span_32b_bytes,"
         "hypothetical_128b_residency_bytes,allocation_bytes,allocation_mib,"
         "warps,warps_per_sm,threads,samples,control_p50_cycles,"
         "cold_p50_cycles,hot_p50_cycles,cold_net_cycles_per_lookup,"
         "hot_net_cycles_per_lookup,cold_p50_us,hot_p50_us,cold_glookups_s,"
         "hot_glookups_s,validated_control,validated_cold,validated_hot,"
         "validation\n"
      << std::fixed << std::setprecision(6);
  for (const auto &row : rows)
    csv << row.path << ',' << row.target_mib << ',' << kAddressRegionBytes
        << ',' << row.stride_bytes << ',' << row.regions << ','
        << std::uint64_t(row.regions) << ',' << std::uint64_t(row.regions) * 4u
        << ',' << std::uint64_t(row.regions) * kAddressRegionBytes << ','
        << row.hypothetical_128b_bytes << ',' << row.allocation_bytes << ','
        << double(row.allocation_bytes) / (1024.0 * 1024.0) << ','
        << row.warps << ','
        << double(row.warps) / properties.multiProcessorCount << ','
        << row.threads << ',' << row.samples << ',' << row.control_cycles.p50
        << ',' << row.cold_cycles.p50 << ',' << row.hot_cycles.p50 << ','
        << row.cold_net_cycles_per_lookup << ','
        << row.hot_net_cycles_per_lookup << ',' << row.cold_us.p50 << ','
        << row.hot_us.p50 << ',' << row.cold_glookups_s << ','
        << row.hot_glookups_s << ',' << row.validated_control << ','
        << row.validated_cold << ',' << row.validated_hot << ','
        << (row.valid ? 1 : 0) << '\n';
}

}  // namespace

int main(int argc, char **argv) {
  try {
    const Args args = parse_args(argc, argv);
    int device = 0;
    cuda_check(cudaGetDevice(&device), "cudaGetDevice");
    cudaDeviceProp properties{};
    cuda_check(cudaGetDeviceProperties(&properties, device),
               "cudaGetDeviceProperties");
    int global_occupancy = 0, texture_occupancy = 0;
    cuda_check(cudaOccupancyMaxActiveBlocksPerMultiprocessor(
                   &global_occupancy, lookup_sparse_codes<kSteps, false>,
                   kWarpSize, 0),
               "cudaOccupancy(global)");
    cuda_check(cudaOccupancyMaxActiveBlocksPerMultiprocessor(
                   &texture_occupancy, lookup_sparse_codes<kSteps, true>,
                   kWarpSize, 0),
               "cudaOccupancy(texture)");
    const std::size_t eviction_entries =
        args.eviction_mib * 1024ull * 1024ull / sizeof(std::uint32_t);
    std::uint32_t *eviction = nullptr, *eviction_sink = nullptr;
    cuda_check(cudaMalloc(&eviction, eviction_entries * sizeof(std::uint32_t)),
               "cudaMalloc(eviction)");
    const int eviction_blocks = properties.multiProcessorCount * 8;
    cuda_check(cudaMalloc(&eviction_sink,
                          std::size_t(eviction_blocks) * 256 *
                              sizeof(std::uint32_t)),
               "cudaMalloc(eviction sink)");
    initialize_filler<<<int((eviction_entries + 255) / 256), 256>>>(
        eviction, eviction_entries, 0x510e527fu);
    cuda_check(cudaGetLastError(), "eviction initialization launch");
    cuda_check(cudaDeviceSynchronize(), "eviction initialization sync");
    const cudaTextureObject_t eviction_texture = make_linear_texture(
        eviction, eviction_entries * sizeof(std::uint32_t));
    std::vector<Row> rows;
    const std::vector<Mode> modes =
        args.order == 0 ? std::vector<Mode>{Mode::Global, Mode::Texture}
                        : std::vector<Mode>{Mode::Texture, Mode::Global};
    std::cout << "CUDA sparse-address LUT device: " << properties.name
              << " sm_" << properties.major << properties.minor
              << " L2=" << properties.l2CacheSize
              << " bytes SMs=" << properties.multiProcessorCount
              << " occupancy=" << global_occupancy << '/'
              << texture_occupancy << '\n';
    for (auto target_mib : args.target_mib)
      for (auto stride_bytes : args.stride_bytes)
        for (int warps : args.warps)
          for (Mode mode : modes) {
            rows.push_back(run_case(
                args, mode, target_mib, stride_bytes, warps, eviction,
                eviction_texture, eviction_entries, eviction_sink,
                eviction_blocks, properties.maxTexture1DLinear));
            const auto &row = rows.back();
            std::cout << std::setw(2) << target_mib << " target MiB stride="
                      << std::setw(3) << stride_bytes << " B alloc="
                      << std::setw(3) << row.allocation_bytes / (1024 * 1024)
                      << " MiB warps=" << std::setw(4) << warps << ' '
                      << std::setw(14) << row.path << " hot=" << std::fixed
                      << std::setprecision(3) << row.hot_glookups_s
                      << " Glookup/s valid=" << (row.valid ? "yes" : "NO")
                      << '\n';
          }
    write_results(args, properties, global_occupancy, texture_occupancy, rows);
    cudaDestroyTextureObject(eviction_texture);
    cudaFree(eviction_sink);
    cudaFree(eviction);
    return std::all_of(rows.begin(), rows.end(),
                       [](const Row &row) { return row.valid; })
               ? 0
               : 2;
  } catch (const std::exception &error) {
    std::cerr << "error: " << error.what() << '\n';
    return 1;
  }
}
