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

void cuda_check(cudaError_t result, const char *what) {
  if (result != cudaSuccess)
    throw std::runtime_error(std::string(what) + ": " +
                             cudaGetErrorString(result));
}

struct Args {
  fs::path out_dir = "cuda_l2_mlp_out";
  std::vector<std::size_t> table_mib = {4, 36, 40, 64, 128};
  std::vector<int> warps = {1,  2,   4,   8,   16,  32,
                            46, 92, 184, 368, 736, 1104};
  std::size_t eviction_mib = 256;
  int warmup = 3;
  int samples = 15;
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
    else
      throw std::runtime_error("unknown argument: " + arg);
  }
  if (args.warmup < 0 || args.samples < 1 || args.eviction_mib < 64)
    throw std::runtime_error("invalid CUDA L2-MLP run parameters");
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

template <int Steps>
__global__ void concurrent_dependent_chase(const std::uint32_t *next,
                                           std::uint32_t entries,
                                           std::uint32_t sample_seed,
                                           ClockResult *results) {
  const std::uint32_t lane = threadIdx.x;
  const std::uint32_t warp = blockIdx.x;
  const std::uint32_t output = warp * kWarpSize + lane;
  const std::uint32_t seed = mix32(sample_seed ^ (warp * 0x9e3779b9u));
  std::uint32_t index = mix32(lane ^ mix32(seed)) % entries;
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

__global__ void evict_l2(const std::uint32_t *data, std::size_t entries,
                         std::uint32_t *sink) {
  const std::size_t thread = threadIdx.x + std::size_t(blockIdx.x) * blockDim.x;
  const std::size_t stride = std::size_t(blockDim.x) * gridDim.x;
  std::uint32_t value = std::uint32_t(thread);
  for (std::size_t i = thread; i < entries; i += stride)
    value ^= load_global_l2(data + i);
  sink[thread] = value;
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
  Distribution result{};
  result.minimum = *std::min_element(values.begin(), values.end());
  result.mean = std::accumulate(values.begin(), values.end(), 0.0) /
                double(values.size());
  result.p50 = percentile(values, 0.50);
  result.p95 = percentile(values, 0.95);
  result.p99 = percentile(values, 0.99);
  result.maximum = *std::max_element(values.begin(), values.end());
  return result;
}

struct Row {
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
  double cold_to_hot_ratio = 0;
  double cold_requested_gloads_s = 0;
  double hot_requested_gloads_s = 0;
  double cold_logical_gib_s = 0;
  double hot_logical_gib_s = 0;
  double cold_ns_per_warp_step = 0;
  double hot_ns_per_warp_step = 0;
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

Row run_case(const Args &args, std::size_t table_mib, int warps,
             const std::uint32_t *eviction, std::size_t eviction_entries,
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
  cudaEvent_t cold_start{}, cold_end{}, hot_start{}, hot_end{};
  cuda_check(cudaEventCreate(&cold_start), "cudaEventCreate(cold start)");
  cuda_check(cudaEventCreate(&cold_end), "cudaEventCreate(cold end)");
  cuda_check(cudaEventCreate(&hot_start), "cudaEventCreate(hot start)");
  cuda_check(cudaEventCreate(&hot_end), "cudaEventCreate(hot end)");
  std::vector<double> control_cycles, cold_cycles, hot_cycles, cold_us, hot_us;
  std::vector<ClockResult> control(threads), cold(threads), hot(threads);
  std::size_t valid_control = 0, valid_cold = 0, valid_hot = 0;
  for (int sample = -args.warmup; sample < args.samples; ++sample) {
    const std::uint32_t sample_seed =
        mix32(std::uint32_t(sample + args.warmup + 1) * 0x85ebca6bu);
    evict_l2<<<eviction_blocks, 256>>>(eviction, eviction_entries,
                                      eviction_sink);
    concurrent_dependent_chase<0><<<warps, kWarpSize>>>(
        device_next, std::uint32_t(entries), sample_seed, device_control);
    cuda_check(cudaEventRecord(cold_start), "cudaEventRecord(cold start)");
    concurrent_dependent_chase<kSteps><<<warps, kWarpSize>>>(
        device_next, std::uint32_t(entries), sample_seed, device_cold);
    cuda_check(cudaEventRecord(cold_end), "cudaEventRecord(cold end)");
    cuda_check(cudaEventRecord(hot_start), "cudaEventRecord(hot start)");
    concurrent_dependent_chase<kSteps><<<warps, kWarpSize>>>(
        device_next, std::uint32_t(entries), sample_seed, device_hot);
    cuda_check(cudaEventRecord(hot_end), "cudaEventRecord(hot end)");
    cuda_check(cudaGetLastError(), "CUDA kernel launch");
    cuda_check(cudaMemcpy(control.data(), device_control,
                          threads * sizeof(ClockResult), cudaMemcpyDeviceToHost),
               "cudaMemcpy(control result)");
    cuda_check(cudaMemcpy(cold.data(), device_cold,
                          threads * sizeof(ClockResult), cudaMemcpyDeviceToHost),
               "cudaMemcpy(cold result)");
    cuda_check(cudaMemcpy(hot.data(), device_hot,
                          threads * sizeof(ClockResult), cudaMemcpyDeviceToHost),
               "cudaMemcpy(hot result)");
    float cold_ms = 0, hot_ms = 0;
    cuda_check(cudaEventElapsedTime(&cold_ms, cold_start, cold_end),
               "cudaEventElapsedTime(cold)");
    cuda_check(cudaEventElapsedTime(&hot_ms, hot_start, hot_end),
               "cudaEventElapsedTime(hot)");
    if (sample >= 0) {
      validate_results(control, host_table, sample_seed, 0, control_cycles,
                       valid_control);
      validate_results(cold, host_table, sample_seed, kSteps, cold_cycles,
                       valid_cold);
      validate_results(hot, host_table, sample_seed, kSteps, hot_cycles,
                       valid_hot);
      cold_us.push_back(double(cold_ms) * 1000.0);
      hot_us.push_back(double(hot_ms) * 1000.0);
    }
  }
  Row row{};
  row.table_bytes = table_bytes;
  row.entries = entries;
  row.warps = warps;
  row.threads = int(threads);
  row.samples = args.samples;
  row.validated_control = valid_control;
  row.validated_cold = valid_cold;
  row.validated_hot = valid_hot;
  row.control_cycles = summarize(control_cycles);
  row.cold_cycles = summarize(cold_cycles);
  row.hot_cycles = summarize(hot_cycles);
  row.cold_kernel_us = summarize(cold_us);
  row.hot_kernel_us = summarize(hot_us);
  row.cold_net_cycles_per_step =
      (row.cold_cycles.p50 - row.control_cycles.p50) / kSteps;
  row.hot_net_cycles_per_step =
      (row.hot_cycles.p50 - row.control_cycles.p50) / kSteps;
  row.cold_to_hot_ratio =
      row.cold_net_cycles_per_step / row.hot_net_cycles_per_step;
  const double requested_loads = double(threads) * kSteps;
  row.cold_requested_gloads_s =
      requested_loads / (row.cold_kernel_us.p50 * 1000.0);
  row.hot_requested_gloads_s =
      requested_loads / (row.hot_kernel_us.p50 * 1000.0);
  constexpr double bytes_per_gib = 1024.0 * 1024.0 * 1024.0;
  row.cold_logical_gib_s = row.cold_requested_gloads_s * 1e9 * 4.0 /
                           bytes_per_gib;
  row.hot_logical_gib_s = row.hot_requested_gloads_s * 1e9 * 4.0 /
                          bytes_per_gib;
  row.cold_ns_per_warp_step =
      row.cold_kernel_us.p50 * 1000.0 / (double(warps) * kSteps);
  row.hot_ns_per_warp_step =
      row.hot_kernel_us.p50 * 1000.0 / (double(warps) * kSteps);
  const std::size_t expected = std::size_t(args.samples) * threads;
  row.valid = valid_control == expected && valid_cold == expected &&
              valid_hot == expected;
  cudaEventDestroy(cold_start);
  cudaEventDestroy(cold_end);
  cudaEventDestroy(hot_start);
  cudaEventDestroy(hot_end);
  cudaFree(device_hot);
  cudaFree(device_cold);
  cudaFree(device_control);
  cudaFree(device_next);
  return row;
}

void write_distribution(std::ostream &out, const Distribution &d) {
  out << "{\"min\": " << d.minimum << ", \"mean\": " << d.mean
      << ", \"p50\": " << d.p50 << ", \"p95\": " << d.p95
      << ", \"p99\": " << d.p99 << ", \"max\": " << d.maximum << '}';
}

void write_results(const Args &args, const cudaDeviceProp &properties,
                   int resident_blocks_per_sm, const std::vector<Row> &rows) {
  fs::create_directories(args.out_dir);
  std::ofstream json(args.out_dir / "cuda_l2_mlp_results.json");
  json << std::fixed << std::setprecision(6)
       << "{\n  \"schema\": \"UGTS-CUDA-L2-MLP-1.0\",\n"
          "  \"runtime\": \"CUDA sm_120 / clock64 / ld.global.cg.u32 / "
          "one-warp blocks\",\n"
          "  \"device\": {\"name\": \""
       << properties.name << "\", \"compute_capability\": \""
       << properties.major << '.' << properties.minor << "\", \"l2_bytes\": "
       << properties.l2CacheSize << ", \"multiprocessors\": "
       << properties.multiProcessorCount << ", \"reported_clock_khz\": "
       << properties.clockRate << ", \"resident_one_warp_blocks_per_sm\": "
       << resident_blocks_per_sm << "},\n"
          "  \"run_parameters\": {\"warmup_pairs\": "
       << args.warmup << ", \"measured_pairs\": " << args.samples
       << ", \"threads_per_warp\": 32, \"dependent_loads_per_thread\": "
       << kSteps << ", \"eviction_bytes\": "
       << args.eviction_mib * 1024 * 1024 << "},\n"
          "  \"semantics\": \"Each one-warp block runs 32 lane-local, "
          "strictly dependent pointer chains. clock64 exposes per-thread "
          "elapsed SM cycles including scheduling. CUDA events expose total "
          "kernel throughput. ld.global.cg bypasses L1 and requests the "
          "L2/global path. Cold follows L2 eviction; hot immediately repeats "
          "the same seeds and chains.\",\n"
          "  \"results\": [\n";
  for (std::size_t i = 0; i < rows.size(); ++i) {
    const auto &row = rows[i];
    json << "    {\"table_bytes\": " << row.table_bytes
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
         << ", \"cold_to_hot_ratio\": " << row.cold_to_hot_ratio
         << ", \"cold_requested_gloads_s\": "
         << row.cold_requested_gloads_s
         << ", \"hot_requested_gloads_s\": " << row.hot_requested_gloads_s
         << ", \"cold_logical_gib_s\": " << row.cold_logical_gib_s
         << ", \"hot_logical_gib_s\": " << row.hot_logical_gib_s
         << ", \"cold_ns_per_warp_step\": " << row.cold_ns_per_warp_step
         << ", \"hot_ns_per_warp_step\": " << row.hot_ns_per_warp_step
         << ", \"validated_control\": " << row.validated_control
         << ", \"validated_cold\": " << row.validated_cold
         << ", \"validated_hot\": " << row.validated_hot
         << ", \"validation\": " << (row.valid ? "true" : "false") << '}'
         << (i + 1 == rows.size() ? "\n" : ",\n");
  }
  json << "  ]\n}\n";
  std::ofstream csv(args.out_dir / "cuda_l2_mlp_results.csv");
  csv << "table_bytes,table_mib,l2_fraction,warps,warps_per_sm,threads,"
         "samples,control_p50_cycles,cold_p50_cycles,hot_p50_cycles,"
         "cold_net_cycles_per_step,hot_net_cycles_per_step,cold_to_hot_ratio,"
         "cold_kernel_p50_us,hot_kernel_p50_us,cold_requested_gloads_s,"
         "hot_requested_gloads_s,cold_logical_gib_s,hot_logical_gib_s,"
         "cold_ns_per_warp_step,hot_ns_per_warp_step,validated_control,"
         "validated_cold,validated_hot,validation\n"
      << std::fixed << std::setprecision(6);
  for (const auto &row : rows)
    csv << row.table_bytes << ',' << row.table_bytes / (1024 * 1024) << ','
        << double(row.table_bytes) / properties.l2CacheSize << ',' << row.warps
        << ',' << double(row.warps) / properties.multiProcessorCount << ','
        << row.threads << ',' << row.samples << ',' << row.control_cycles.p50
        << ',' << row.cold_cycles.p50 << ',' << row.hot_cycles.p50 << ','
        << row.cold_net_cycles_per_step << ',' << row.hot_net_cycles_per_step
        << ',' << row.cold_to_hot_ratio << ',' << row.cold_kernel_us.p50 << ','
        << row.hot_kernel_us.p50 << ',' << row.cold_requested_gloads_s << ','
        << row.hot_requested_gloads_s << ',' << row.cold_logical_gib_s << ','
        << row.hot_logical_gib_s << ',' << row.cold_ns_per_warp_step << ','
        << row.hot_ns_per_warp_step << ',' << row.validated_control << ','
        << row.validated_cold << ',' << row.validated_hot << ','
        << (row.valid ? 1 : 0) << '\n';
}

} // namespace

int main(int argc, char **argv) {
  try {
    const Args args = parse_args(argc, argv);
    int device = 0;
    cuda_check(cudaSetDevice(device), "cudaSetDevice");
    cudaDeviceProp properties{};
    cuda_check(cudaGetDeviceProperties(&properties, device),
               "cudaGetDeviceProperties");
    int resident_blocks_per_sm = 0;
    cuda_check(cudaOccupancyMaxActiveBlocksPerMultiprocessor(
                   &resident_blocks_per_sm,
                   concurrent_dependent_chase<kSteps>, kWarpSize, 0),
               "cudaOccupancyMaxActiveBlocksPerMultiprocessor");
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
    std::cout << "CUDA L2 MLP device: " << properties.name << " sm_"
              << properties.major << properties.minor << " L2="
              << properties.l2CacheSize << " bytes SMs="
              << properties.multiProcessorCount << " one-warp blocks/SM="
              << resident_blocks_per_sm << '\n';
    std::vector<Row> rows;
    for (auto table_mib : args.table_mib) {
      for (auto warps : args.warps) {
        auto row = run_case(args, table_mib, warps, eviction, eviction_entries,
                            eviction_sink, eviction_blocks);
        std::cout << std::setw(4) << table_mib << " MiB " << std::setw(4)
                  << warps << " warps cold=" << std::fixed
                  << std::setprecision(3) << row.cold_requested_gloads_s
                  << " Gload/s hot=" << row.hot_requested_gloads_s
                  << " Gload/s exposed=" << row.cold_net_cycles_per_step << '/'
                  << row.hot_net_cycles_per_step << " cyc valid="
                  << (row.valid ? "yes" : "no") << '\n';
        rows.push_back(row);
      }
    }
    write_results(args, properties, resident_blocks_per_sm, rows);
    cudaFree(eviction_sink);
    cudaFree(eviction);
    const bool valid = std::all_of(rows.begin(), rows.end(),
                                   [](const Row &row) { return row.valid; });
    return valid ? 0 : 2;
  } catch (const std::exception &error) {
    std::cerr << "UGTS CUDA L2 MLP benchmark error: " << error.what() << '\n';
    return 1;
  }
}
