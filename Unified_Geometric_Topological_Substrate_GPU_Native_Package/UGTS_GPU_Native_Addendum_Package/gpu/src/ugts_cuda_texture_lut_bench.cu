#include <cuda_runtime.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
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

void cuda_check(cudaError_t result, const char *what) {
  if (result != cudaSuccess)
    throw std::runtime_error(std::string(what) + ": " +
                             cudaGetErrorString(result));
}

struct Args {
  fs::path out_dir = "cuda_texture_lut_out";
  std::vector<std::size_t> table_mib = {4, 32, 36, 38, 40, 48, 64, 128};
  std::vector<int> warps = {1, 46, 184, 1104};
  std::size_t eviction_mib = 256;
  int warmup = 3;
  int samples = 12;
  bool texture_first = false;
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
      result.push_back(std::stoull(part));
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
      args.table_mib = parse_list<std::size_t>(value("--table-mib"));
    else if (arg == "--warps")
      args.warps = parse_list<int>(value("--warps"));
    else if (arg == "--eviction-mib")
      args.eviction_mib = std::stoull(value("--eviction-mib"));
    else if (arg == "--warmup")
      args.warmup = std::stoi(value("--warmup"));
    else if (arg == "--samples")
      args.samples = std::stoi(value("--samples"));
    else if (arg == "--texture-first")
      args.texture_first = true;
    else
      throw std::runtime_error("unknown argument: " + arg);
  }
  if (args.warmup < 0 || args.samples < 1 || args.eviction_mib < 64)
    throw std::runtime_error("invalid CUDA texture-LUT run parameters");
  for (auto size : args.table_mib)
    if (!size || size > 1024)
      throw std::runtime_error("table MiB must be in [1, 1024]");
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

__device__ __forceinline__ std::uint32_t load_global_l2(
    const std::uint32_t *address) {
  std::uint32_t value;
  asm volatile("ld.global.cg.u32 %0, [%1];" : "=r"(value) : "l"(address));
  return value;
}

struct alignas(16) ClockResult {
  unsigned long long started;
  unsigned long long finished;
  std::uint32_t final_index;
  std::uint32_t checksum;
  std::uint32_t seed;
  std::uint32_t steps;
};
static_assert(sizeof(ClockResult) == 32, "clock result ABI");

__device__ __forceinline__ std::uint32_t initial_index(
    std::uint32_t lane, std::uint32_t warp, std::uint32_t sample_seed,
    std::uint32_t entries, std::uint32_t &seed) {
  seed = mix32(sample_seed ^ (warp * 0x9e3779b9u));
  return mix32(lane ^ mix32(seed)) % entries;
}

template <int Steps>
__global__ void chase_global(const std::uint32_t *next, std::uint32_t entries,
                             std::uint32_t sample_seed,
                             ClockResult *results) {
  const std::uint32_t lane = threadIdx.x;
  const std::uint32_t warp = blockIdx.x;
  const std::uint32_t output = warp * kWarpSize + lane;
  std::uint32_t seed = 0;
  std::uint32_t index =
      initial_index(lane, warp, sample_seed, entries, seed);
  asm volatile("" ::: "memory");
  const unsigned long long started = clock64();
#pragma unroll 1
  for (int step = 0; step < Steps; ++step)
    index = load_global_l2(next + index);
  const unsigned long long finished = clock64();
  asm volatile("" ::: "memory");
  ClockResult result{};
  result.started = started;
  result.finished = finished;
  result.final_index = index;
  result.checksum = mix32(index ^ lane ^ seed);
  result.seed = seed;
  result.steps = Steps;
  results[output] = result;
}

template <int Steps>
__global__ void chase_texture(cudaTextureObject_t texture,
                              std::uint32_t entries,
                              std::uint32_t sample_seed,
                              ClockResult *results) {
  const std::uint32_t lane = threadIdx.x;
  const std::uint32_t warp = blockIdx.x;
  const std::uint32_t output = warp * kWarpSize + lane;
  std::uint32_t seed = 0;
  std::uint32_t index =
      initial_index(lane, warp, sample_seed, entries, seed);
  asm volatile("" ::: "memory");
  const unsigned long long started = clock64();
#pragma unroll 1
  for (int step = 0; step < Steps; ++step)
    index = tex1Dfetch<std::uint32_t>(texture, int(index));
  const unsigned long long finished = clock64();
  asm volatile("" ::: "memory");
  ClockResult result{};
  result.started = started;
  result.finished = finished;
  result.final_index = index;
  result.checksum = mix32(index ^ lane ^ seed);
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
  cudaTextureDesc texture_desc{};
  texture_desc.readMode = cudaReadModeElementType;
  cudaTextureObject_t texture = 0;
  cuda_check(cudaCreateTextureObject(&texture, &resource, &texture_desc, nullptr),
             "cudaCreateTextureObject");
  return texture;
}

struct PointerTable {
  std::vector<std::uint32_t> values;
  std::uint64_t multiplier = 0;
  std::uint64_t increment = 0;
};

PointerTable make_pointer_table(std::size_t entries) {
  std::uint64_t prime_product = 1, remainder = entries;
  for (std::uint64_t prime = 2; prime * prime <= remainder; ++prime) {
    if (remainder % prime)
      continue;
    prime_product *= prime;
    while (remainder % prime == 0)
      remainder /= prime;
  }
  if (remainder > 1)
    prime_product *= remainder;
  if ((entries % 4) == 0 && (prime_product % 4) != 0)
    prime_product *= 2;
  const std::uint64_t multiplier =
      1 + prime_product * std::max<std::uint64_t>(1, 1664524 / prime_product);
  std::uint64_t increment = 1013904223u % entries;
  if (!increment)
    increment = 1;
  while (std::gcd(increment, std::uint64_t(entries)) != 1)
    ++increment;
  PointerTable table;
  table.multiplier = multiplier;
  table.increment = increment;
  table.values.resize(entries);
  for (std::size_t i = 0; i < entries; ++i)
    table.values[i] =
        std::uint32_t((multiplier * i + increment) % entries);
  return table;
}

std::uint32_t advance_affine(std::uint32_t index, std::uint64_t multiplier,
                             std::uint64_t increment, std::uint64_t modulus,
                             std::uint32_t steps) {
  std::uint64_t acc_mul = 1, acc_add = 0;
  std::uint64_t cur_mul = multiplier % modulus, cur_add = increment % modulus;
  while (steps) {
    if (steps & 1u) {
      acc_add = (cur_mul * acc_add + cur_add) % modulus;
      acc_mul = (cur_mul * acc_mul) % modulus;
    }
    cur_add = (cur_mul * cur_add + cur_add) % modulus;
    cur_mul = (cur_mul * cur_mul) % modulus;
    steps >>= 1u;
  }
  return std::uint32_t((acc_mul * index + acc_add) % modulus);
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
  double minimum = 0;
  double mean = 0;
  double p50 = 0;
  double p95 = 0;
  double p99 = 0;
  double maximum = 0;
};

Distribution summarize(const std::vector<double> &values) {
  if (values.empty())
    throw std::runtime_error("cannot summarize an empty measurement set");
  return {*std::min_element(values.begin(), values.end()),
          std::accumulate(values.begin(), values.end(), 0.0) /
              double(values.size()),
          percentile(values, 0.50), percentile(values, 0.95),
          percentile(values, 0.99),
          *std::max_element(values.begin(), values.end())};
}

struct Accumulator {
  std::vector<double> control_cycles;
  std::vector<double> cold_cycles;
  std::vector<double> hot_cycles;
  std::vector<double> cold_us;
  std::vector<double> hot_us;
  std::size_t valid_control = 0;
  std::size_t valid_cold = 0;
  std::size_t valid_hot = 0;
};

struct Row {
  std::string path;
  std::size_t table_bytes = 0;
  std::size_t entries = 0;
  int warps = 0;
  int threads = 0;
  int samples = 0;
  std::size_t validated_control = 0;
  std::size_t validated_cold = 0;
  std::size_t validated_hot = 0;
  Distribution control_cycles;
  Distribution cold_cycles;
  Distribution hot_cycles;
  Distribution cold_kernel_us;
  Distribution hot_kernel_us;
  double cold_net_cycles_per_step = 0;
  double hot_net_cycles_per_step = 0;
  double cold_requested_gloads_s = 0;
  double hot_requested_gloads_s = 0;
  double cold_logical_gib_s = 0;
  double hot_logical_gib_s = 0;
  bool valid = false;
};

void validate_results(const std::vector<ClockResult> &results,
                      const PointerTable &table, std::uint32_t sample_seed,
                      std::uint32_t steps, std::vector<double> &cycles,
                      std::size_t &validated) {
  const auto entries = std::uint64_t(table.values.size());
  for (std::size_t output = 0; output < results.size(); ++output) {
    const std::uint32_t warp = std::uint32_t(output / kWarpSize);
    const std::uint32_t lane = std::uint32_t(output % kWarpSize);
    const std::uint32_t seed = mix32(sample_seed ^ (warp * 0x9e3779b9u));
    const std::uint32_t initial = mix32(lane ^ mix32(seed)) % entries;
    const std::uint32_t expected =
        advance_affine(initial, table.multiplier, table.increment, entries,
                       steps);
    const auto &actual = results[output];
    if (actual.final_index == expected &&
        actual.checksum == mix32(expected ^ lane ^ seed) &&
        actual.seed == seed && actual.steps == steps &&
        actual.finished >= actual.started)
      ++validated;
    cycles.push_back(double(actual.finished - actual.started));
  }
}

void launch_path(bool texture_path, int warps, std::uint32_t entries,
                 std::uint32_t seed, const std::uint32_t *device_next,
                 cudaTextureObject_t texture, ClockResult *control,
                 ClockResult *cold, ClockResult *hot, cudaEvent_t cold_start,
                 cudaEvent_t cold_end, cudaEvent_t hot_start,
                 cudaEvent_t hot_end) {
  if (texture_path) {
    chase_texture<0><<<warps, kWarpSize>>>(texture, entries, seed, control);
    cuda_check(cudaEventRecord(cold_start), "cudaEventRecord(cold start)");
    chase_texture<kSteps><<<warps, kWarpSize>>>(texture, entries, seed, cold);
    cuda_check(cudaEventRecord(cold_end), "cudaEventRecord(cold end)");
    cuda_check(cudaEventRecord(hot_start), "cudaEventRecord(hot start)");
    chase_texture<kSteps><<<warps, kWarpSize>>>(texture, entries, seed, hot);
  } else {
    chase_global<0><<<warps, kWarpSize>>>(device_next, entries, seed, control);
    cuda_check(cudaEventRecord(cold_start), "cudaEventRecord(cold start)");
    chase_global<kSteps><<<warps, kWarpSize>>>(device_next, entries, seed, cold);
    cuda_check(cudaEventRecord(cold_end), "cudaEventRecord(cold end)");
    cuda_check(cudaEventRecord(hot_start), "cudaEventRecord(hot start)");
    chase_global<kSteps><<<warps, kWarpSize>>>(device_next, entries, seed, hot);
  }
  cuda_check(cudaEventRecord(hot_end), "cudaEventRecord(hot end)");
  cuda_check(cudaGetLastError(), "CUDA path kernel launch");
}

Row finalize_row(const std::string &path, const Args &args,
                 std::size_t table_bytes, std::size_t entries, int warps,
                 const Accumulator &data) {
  Row row{};
  row.path = path;
  row.table_bytes = table_bytes;
  row.entries = entries;
  row.warps = warps;
  row.threads = warps * int(kWarpSize);
  row.samples = args.samples;
  row.validated_control = data.valid_control;
  row.validated_cold = data.valid_cold;
  row.validated_hot = data.valid_hot;
  row.control_cycles = summarize(data.control_cycles);
  row.cold_cycles = summarize(data.cold_cycles);
  row.hot_cycles = summarize(data.hot_cycles);
  row.cold_kernel_us = summarize(data.cold_us);
  row.hot_kernel_us = summarize(data.hot_us);
  row.cold_net_cycles_per_step =
      (row.cold_cycles.p50 - row.control_cycles.p50) / kSteps;
  row.hot_net_cycles_per_step =
      (row.hot_cycles.p50 - row.control_cycles.p50) / kSteps;
  const double loads = double(row.threads) * kSteps;
  row.cold_requested_gloads_s =
      loads / (row.cold_kernel_us.p50 * 1000.0);
  row.hot_requested_gloads_s = loads / (row.hot_kernel_us.p50 * 1000.0);
  constexpr double bytes_per_gib = 1024.0 * 1024.0 * 1024.0;
  row.cold_logical_gib_s =
      row.cold_requested_gloads_s * 4e9 / bytes_per_gib;
  row.hot_logical_gib_s = row.hot_requested_gloads_s * 4e9 / bytes_per_gib;
  const std::size_t expected =
      std::size_t(args.samples) * std::size_t(row.threads);
  row.valid = data.valid_control == expected && data.valid_cold == expected &&
              data.valid_hot == expected;
  return row;
}

std::vector<Row> run_case(const Args &args, std::size_t table_mib, int warps,
                          const std::uint32_t *eviction,
                          std::size_t eviction_entries,
                          cudaTextureObject_t eviction_texture,
                          std::uint32_t *eviction_sink, int eviction_blocks) {
  const std::size_t table_bytes = table_mib * 1024 * 1024;
  const std::size_t entries = table_bytes / sizeof(std::uint32_t);
  const std::size_t threads = std::size_t(warps) * kWarpSize;
  auto host_table = make_pointer_table(entries);
  std::uint32_t *device_next = nullptr;
  ClockResult *device_control = nullptr, *device_cold = nullptr,
              *device_hot = nullptr;
  cuda_check(cudaMalloc(&device_next, table_bytes), "cudaMalloc(table)");
  cuda_check(cudaMalloc(&device_control, threads * sizeof(ClockResult)),
             "cudaMalloc(control output)");
  cuda_check(cudaMalloc(&device_cold, threads * sizeof(ClockResult)),
             "cudaMalloc(cold output)");
  cuda_check(cudaMalloc(&device_hot, threads * sizeof(ClockResult)),
             "cudaMalloc(hot output)");
  cuda_check(cudaMemcpy(device_next, host_table.values.data(), table_bytes,
                        cudaMemcpyHostToDevice),
             "cudaMemcpy(table upload)");
  const cudaTextureObject_t texture =
      make_linear_texture(device_next, table_bytes);
  cudaEvent_t cold_start{}, cold_end{}, hot_start{}, hot_end{};
  cuda_check(cudaEventCreate(&cold_start), "cudaEventCreate(cold start)");
  cuda_check(cudaEventCreate(&cold_end), "cudaEventCreate(cold end)");
  cuda_check(cudaEventCreate(&hot_start), "cudaEventCreate(hot start)");
  cuda_check(cudaEventCreate(&hot_end), "cudaEventCreate(hot end)");
  std::vector<ClockResult> control(threads), cold(threads), hot(threads);
  Accumulator global_data, texture_data;
  for (int sample = -args.warmup; sample < args.samples; ++sample) {
    const std::uint32_t sample_seed =
        mix32(std::uint32_t(sample + args.warmup + 1) * 0xc2b2ae35u);
    for (int order_index = 0; order_index < 2; ++order_index) {
      const bool texture_path =
          args.texture_first ? order_index == 0 : order_index == 1;
      evict_global<<<eviction_blocks, 256>>>(eviction, eviction_entries,
                                             eviction_sink);
      if (texture_path)
        evict_texture<<<eviction_blocks, 256>>>(
            eviction_texture, eviction_entries, eviction_sink);
      launch_path(texture_path, warps, std::uint32_t(entries), sample_seed,
                  device_next, texture, device_control, device_cold, device_hot,
                  cold_start, cold_end, hot_start, hot_end);
      cuda_check(cudaMemcpy(control.data(), device_control,
                            threads * sizeof(ClockResult),
                            cudaMemcpyDeviceToHost),
                 "cudaMemcpy(control result)");
      cuda_check(cudaMemcpy(cold.data(), device_cold,
                            threads * sizeof(ClockResult),
                            cudaMemcpyDeviceToHost),
                 "cudaMemcpy(cold result)");
      cuda_check(cudaMemcpy(hot.data(), device_hot,
                            threads * sizeof(ClockResult),
                            cudaMemcpyDeviceToHost),
                 "cudaMemcpy(hot result)");
      float cold_ms = 0, hot_ms = 0;
      cuda_check(cudaEventElapsedTime(&cold_ms, cold_start, cold_end),
                 "cudaEventElapsedTime(cold)");
      cuda_check(cudaEventElapsedTime(&hot_ms, hot_start, hot_end),
                 "cudaEventElapsedTime(hot)");
      if (sample >= 0) {
        auto &data = texture_path ? texture_data : global_data;
        validate_results(control, host_table, sample_seed, 0,
                         data.control_cycles, data.valid_control);
        validate_results(cold, host_table, sample_seed, kSteps,
                         data.cold_cycles, data.valid_cold);
        validate_results(hot, host_table, sample_seed, kSteps, data.hot_cycles,
                         data.valid_hot);
        data.cold_us.push_back(double(cold_ms) * 1000.0);
        data.hot_us.push_back(double(hot_ms) * 1000.0);
      }
    }
  }
  std::vector<Row> rows;
  rows.push_back(finalize_row("global_cg", args, table_bytes, entries, warps,
                              global_data));
  rows.push_back(finalize_row("texture_object", args, table_bytes, entries,
                              warps, texture_data));
  cudaEventDestroy(cold_start);
  cudaEventDestroy(cold_end);
  cudaEventDestroy(hot_start);
  cudaEventDestroy(hot_end);
  cudaDestroyTextureObject(texture);
  cudaFree(device_hot);
  cudaFree(device_cold);
  cudaFree(device_control);
  cudaFree(device_next);
  return rows;
}

void write_distribution(std::ostream &out, const Distribution &d) {
  out << "{\"min\": " << d.minimum << ", \"mean\": " << d.mean
      << ", \"p50\": " << d.p50 << ", \"p95\": " << d.p95
      << ", \"p99\": " << d.p99 << ", \"max\": " << d.maximum << '}';
}

void write_results(const Args &args, const cudaDeviceProp &properties,
                   int global_blocks_per_sm, int texture_blocks_per_sm,
                   const std::vector<Row> &rows) {
  fs::create_directories(args.out_dir);
  std::ofstream json(args.out_dir / "cuda_texture_lut_results.json");
  json << std::fixed << std::setprecision(6)
       << "{\n  \"schema\": \"UGTS-CUDA-TEXTURE-LUT-1.0\",\n"
          "  \"runtime\": \"CUDA sm_120 matched texture-object and "
          "ld.global.cg dependent chains\",\n"
          "  \"device\": {\"name\": \""
       << properties.name << "\", \"compute_capability\": \""
       << properties.major << '.' << properties.minor << "\", \"l2_bytes\": "
       << properties.l2CacheSize << ", \"multiprocessors\": "
       << properties.multiProcessorCount << ", \"max_texture_1d_linear_elements\": "
       << properties.maxTexture1DLinear
       << ", \"global_one_warp_blocks_per_sm\": " << global_blocks_per_sm
       << ", \"texture_one_warp_blocks_per_sm\": " << texture_blocks_per_sm
       << "},\n"
          "  \"run_parameters\": {\"warmup_pairs\": "
       << args.warmup << ", \"measured_pairs\": " << args.samples
       << ", \"threads_per_warp\": 32, \"dependent_loads_per_thread\": "
       << kSteps << ", \"eviction_bytes\": "
       << args.eviction_mib * 1024 * 1024 << ", \"path_order\": \""
       << (args.texture_first ? "texture_first" : "global_first")
       << "\"},\n"
          "  \"semantics\": \"Both paths read the same cudaMalloc bytes and "
          "execute identical seed/index/output logic. global_cg uses inline "
          "ld.global.cg.u32; texture_object uses integer tex1Dfetch from a "
          "linear CUDA texture object. Each path receives an independent "
          "eviction and exact CPU endpoint validation.\",\n"
          "  \"results\": [\n";
  for (std::size_t i = 0; i < rows.size(); ++i) {
    const auto &row = rows[i];
    json << "    {\"path\": \"" << row.path
         << "\", \"table_bytes\": " << row.table_bytes
         << ", \"table_mib\": " << row.table_bytes / (1024 * 1024)
         << ", \"l2_fraction\": "
         << double(row.table_bytes) / properties.l2CacheSize
         << ", \"entries\": " << row.entries << ", \"warps\": "
         << row.warps << ", \"warps_per_sm\": "
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
    json << ", \"cold_net_cycles_per_step\": "
         << row.cold_net_cycles_per_step
         << ", \"hot_net_cycles_per_step\": "
         << row.hot_net_cycles_per_step
         << ", \"cold_requested_gloads_s\": "
         << row.cold_requested_gloads_s
         << ", \"hot_requested_gloads_s\": " << row.hot_requested_gloads_s
         << ", \"cold_logical_gib_s\": " << row.cold_logical_gib_s
         << ", \"hot_logical_gib_s\": " << row.hot_logical_gib_s
         << ", \"validated_control\": " << row.validated_control
         << ", \"validated_cold\": " << row.validated_cold
         << ", \"validated_hot\": " << row.validated_hot
         << ", \"validation\": " << (row.valid ? "true" : "false") << '}'
         << (i + 1 == rows.size() ? "\n" : ",\n");
  }
  json << "  ]\n}\n";
  std::ofstream csv(args.out_dir / "cuda_texture_lut_results.csv");
  csv << "path,table_bytes,table_mib,l2_fraction,warps,warps_per_sm,threads,"
         "samples,control_p50_cycles,cold_p50_cycles,hot_p50_cycles,"
         "cold_net_cycles_per_step,hot_net_cycles_per_step,cold_kernel_p50_us,"
         "hot_kernel_p50_us,cold_requested_gloads_s,hot_requested_gloads_s,"
         "cold_logical_gib_s,hot_logical_gib_s,validated_control,"
         "validated_cold,validated_hot,validation\n"
      << std::fixed << std::setprecision(6);
  for (const auto &row : rows)
    csv << row.path << ',' << row.table_bytes << ','
        << row.table_bytes / (1024 * 1024) << ','
        << double(row.table_bytes) / properties.l2CacheSize << ',' << row.warps
        << ',' << double(row.warps) / properties.multiProcessorCount << ','
        << row.threads << ',' << row.samples << ',' << row.control_cycles.p50
        << ',' << row.cold_cycles.p50 << ',' << row.hot_cycles.p50 << ','
        << row.cold_net_cycles_per_step << ',' << row.hot_net_cycles_per_step
        << ',' << row.cold_kernel_us.p50 << ',' << row.hot_kernel_us.p50 << ','
        << row.cold_requested_gloads_s << ',' << row.hot_requested_gloads_s
        << ',' << row.cold_logical_gib_s << ',' << row.hot_logical_gib_s << ','
        << row.validated_control << ',' << row.validated_cold << ','
        << row.validated_hot << ',' << (row.valid ? 1 : 0) << '\n';
}

} // namespace

int main(int argc, char **argv) {
  try {
    const Args args = parse_args(argc, argv);
    cuda_check(cudaSetDevice(0), "cudaSetDevice");
    cudaDeviceProp properties{};
    cuda_check(cudaGetDeviceProperties(&properties, 0),
               "cudaGetDeviceProperties");
    for (auto size : args.table_mib) {
      const std::size_t entries = size * 1024 * 1024 / sizeof(std::uint32_t);
      if (entries > properties.maxTexture1DLinear)
        throw std::runtime_error("table exceeds maxTexture1DLinear");
    }
    int global_blocks_per_sm = 0, texture_blocks_per_sm = 0;
    cuda_check(cudaOccupancyMaxActiveBlocksPerMultiprocessor(
                   &global_blocks_per_sm, chase_global<kSteps>, kWarpSize, 0),
               "global occupancy query");
    cuda_check(cudaOccupancyMaxActiveBlocksPerMultiprocessor(
                   &texture_blocks_per_sm, chase_texture<kSteps>, kWarpSize,
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
    std::cout << "CUDA texture-LUT device: " << properties.name << " sm_"
              << properties.major << properties.minor << " L2="
              << properties.l2CacheSize << " bytes SMs="
              << properties.multiProcessorCount << " occupancy global/texture="
              << global_blocks_per_sm << '/' << texture_blocks_per_sm << '\n';
    std::vector<Row> rows;
    for (auto table_mib : args.table_mib) {
      for (auto warps : args.warps) {
        auto pair = run_case(args, table_mib, warps, eviction,
                             eviction_entries, eviction_texture, eviction_sink,
                             eviction_blocks);
        const auto &global = pair[0];
        const auto &texture = pair[1];
        std::cout << std::setw(4) << table_mib << " MiB " << std::setw(4)
                  << warps << " warps hot texture/global=" << std::fixed
                  << std::setprecision(3) << texture.hot_requested_gloads_s
                  << '/' << global.hot_requested_gloads_s << " Gload/s ratio="
                  << texture.hot_requested_gloads_s /
                         global.hot_requested_gloads_s
                  << " valid="
                  << (global.valid && texture.valid ? "yes" : "no") << '\n';
        rows.insert(rows.end(), pair.begin(), pair.end());
      }
    }
    write_results(args, properties, global_blocks_per_sm,
                  texture_blocks_per_sm, rows);
    cudaDestroyTextureObject(eviction_texture);
    cudaFree(eviction_sink);
    cudaFree(eviction);
    const bool valid = std::all_of(rows.begin(), rows.end(),
                                   [](const Row &row) { return row.valid; });
    return valid ? 0 : 2;
  } catch (const std::exception &error) {
    std::cerr << "UGTS CUDA texture-LUT benchmark error: " << error.what()
              << '\n';
    return 1;
  }
}
