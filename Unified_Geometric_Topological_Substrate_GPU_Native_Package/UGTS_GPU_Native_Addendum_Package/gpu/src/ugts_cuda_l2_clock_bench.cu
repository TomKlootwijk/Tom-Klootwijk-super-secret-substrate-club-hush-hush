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
#include <vector>

namespace fs = std::filesystem;

namespace {

void cuda_check(cudaError_t result, const char *what) {
  if (result != cudaSuccess)
    throw std::runtime_error(std::string(what) + ": " +
                             cudaGetErrorString(result));
}

struct Args {
  fs::path out_dir = "cuda_l2_clock_out";
  std::vector<std::size_t> table_mib = {4, 36, 40, 64, 128};
  std::size_t eviction_mib = 256;
  int warmup = 5;
  int samples = 50;
};

std::vector<std::size_t> parse_sizes(const std::string &text) {
  std::stringstream stream(text);
  std::string part;
  std::vector<std::size_t> result;
  while (std::getline(stream, part, ','))
    if (!part.empty())
      result.push_back(std::stoull(part));
  if (result.empty())
    throw std::runtime_error("empty table-size list");
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
      args.table_mib = parse_sizes(value("--table-mib"));
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
    throw std::runtime_error("invalid CUDA L2-clock run parameters");
  for (auto size : args.table_mib)
    if (!size || size > 1024)
      throw std::runtime_error("table MiB must be in [1, 1024]");
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
__global__ void dependent_chase(const std::uint32_t *next,
                                std::uint32_t entries, std::uint32_t seed,
                                ClockResult *results) {
  const std::uint32_t lane = threadIdx.x + blockIdx.x * blockDim.x;
  if (lane >= 32)
    return;
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
  results[lane] = result;
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

std::vector<std::uint32_t> make_pointer_table(std::size_t entries) {
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
  std::vector<std::uint32_t> next(entries);
  for (std::size_t i = 0; i < entries; ++i)
    next[i] = std::uint32_t((multiplier * i + increment) % entries);
  return next;
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
  int samples = 0;
  std::size_t validated_control = 0;
  std::size_t validated_cold = 0;
  std::size_t validated_hot = 0;
  Distribution control_cycles;
  Distribution cold_cycles;
  Distribution hot_cycles;
  Distribution cold_kernel_us;
  Distribution hot_kernel_us;
  double cold_net_cycles_per_load = 0;
  double hot_net_cycles_per_load = 0;
  double cold_to_hot_ratio = 0;
  bool valid = false;
};

void validate_results(const std::vector<ClockResult> &results,
                      const std::vector<std::uint32_t> &next,
                      std::uint32_t seed, std::uint32_t steps,
                      std::vector<double> &cycles, std::size_t &validated) {
  for (std::uint32_t lane = 0; lane < 32; ++lane) {
    std::uint32_t expected = mix32(lane ^ mix32(seed)) % next.size();
    for (std::uint32_t step = 0; step < steps; ++step)
      expected = next[expected];
    const auto &actual = results[lane];
    if (actual.final_index == expected &&
        actual.checksum == mix32(expected ^ lane ^ seed) &&
        actual.seed == seed && actual.steps == steps)
      ++validated;
    cycles.push_back(double(actual.finished - actual.started));
  }
}

Row run_table(const Args &args, std::size_t table_mib,
              const std::uint32_t *eviction, std::size_t eviction_entries,
              std::uint32_t *eviction_sink, int eviction_blocks) {
  constexpr std::uint32_t steps = 512;
  const std::size_t table_bytes = table_mib * 1024 * 1024;
  const std::size_t entries = table_bytes / sizeof(std::uint32_t);
  auto host_next = make_pointer_table(entries);
  std::uint32_t *device_next = nullptr;
  ClockResult *device_control = nullptr, *device_cold = nullptr,
              *device_hot = nullptr;
  cuda_check(cudaMalloc(&device_next, table_bytes), "cudaMalloc(table)");
  cuda_check(cudaMalloc(&device_control, 32 * sizeof(ClockResult)),
             "cudaMalloc(control output)");
  cuda_check(cudaMalloc(&device_cold, 32 * sizeof(ClockResult)),
             "cudaMalloc(cold output)");
  cuda_check(cudaMalloc(&device_hot, 32 * sizeof(ClockResult)),
             "cudaMalloc(hot output)");
  cuda_check(cudaMemcpy(device_next, host_next.data(), table_bytes,
                        cudaMemcpyHostToDevice),
             "cudaMemcpy(table upload)");
  cudaEvent_t cold_start{}, cold_end{}, hot_start{}, hot_end{};
  cuda_check(cudaEventCreate(&cold_start), "cudaEventCreate(cold start)");
  cuda_check(cudaEventCreate(&cold_end), "cudaEventCreate(cold end)");
  cuda_check(cudaEventCreate(&hot_start), "cudaEventCreate(hot start)");
  cuda_check(cudaEventCreate(&hot_end), "cudaEventCreate(hot end)");
  std::vector<double> control_cycles, cold_cycles, hot_cycles, cold_us, hot_us;
  std::vector<ClockResult> control(32), cold(32), hot(32);
  std::size_t valid_control = 0, valid_cold = 0, valid_hot = 0;
  for (int sample = -args.warmup; sample < args.samples; ++sample) {
    const std::uint32_t seed =
        mix32(std::uint32_t(sample + args.warmup + 1) * 0x9e3779b9u);
    evict_l2<<<eviction_blocks, 256>>>(eviction, eviction_entries,
                                      eviction_sink);
    dependent_chase<0><<<1, 32>>>(device_next, std::uint32_t(entries), seed,
                                  device_control);
    cuda_check(cudaEventRecord(cold_start), "cudaEventRecord(cold start)");
    dependent_chase<steps><<<1, 32>>>(device_next, std::uint32_t(entries), seed,
                                      device_cold);
    cuda_check(cudaEventRecord(cold_end), "cudaEventRecord(cold end)");
    cuda_check(cudaEventRecord(hot_start), "cudaEventRecord(hot start)");
    dependent_chase<steps><<<1, 32>>>(device_next, std::uint32_t(entries), seed,
                                      device_hot);
    cuda_check(cudaEventRecord(hot_end), "cudaEventRecord(hot end)");
    cuda_check(cudaGetLastError(), "CUDA kernel launch");
    cuda_check(cudaMemcpy(control.data(), device_control,
                          control.size() * sizeof(ClockResult),
                          cudaMemcpyDeviceToHost),
               "cudaMemcpy(control result)");
    cuda_check(cudaMemcpy(cold.data(), device_cold,
                          cold.size() * sizeof(ClockResult),
                          cudaMemcpyDeviceToHost),
               "cudaMemcpy(cold result)");
    cuda_check(cudaMemcpy(hot.data(), device_hot,
                          hot.size() * sizeof(ClockResult),
                          cudaMemcpyDeviceToHost),
               "cudaMemcpy(hot result)");
    float cold_ms = 0, hot_ms = 0;
    cuda_check(cudaEventElapsedTime(&cold_ms, cold_start, cold_end),
               "cudaEventElapsedTime(cold)");
    cuda_check(cudaEventElapsedTime(&hot_ms, hot_start, hot_end),
               "cudaEventElapsedTime(hot)");
    if (sample >= 0) {
      validate_results(control, host_next, seed, 0, control_cycles,
                       valid_control);
      validate_results(cold, host_next, seed, steps, cold_cycles, valid_cold);
      validate_results(hot, host_next, seed, steps, hot_cycles, valid_hot);
      cold_us.push_back(double(cold_ms) * 1000.0);
      hot_us.push_back(double(hot_ms) * 1000.0);
    }
  }
  Row row{};
  row.table_bytes = table_bytes;
  row.entries = entries;
  row.samples = args.samples;
  row.validated_control = valid_control;
  row.validated_cold = valid_cold;
  row.validated_hot = valid_hot;
  row.control_cycles = summarize(control_cycles);
  row.cold_cycles = summarize(cold_cycles);
  row.hot_cycles = summarize(hot_cycles);
  row.cold_kernel_us = summarize(cold_us);
  row.hot_kernel_us = summarize(hot_us);
  row.cold_net_cycles_per_load =
      (row.cold_cycles.p50 - row.control_cycles.p50) / steps;
  row.hot_net_cycles_per_load =
      (row.hot_cycles.p50 - row.control_cycles.p50) / steps;
  row.cold_to_hot_ratio =
      row.cold_net_cycles_per_load / row.hot_net_cycles_per_load;
  const std::size_t expected = std::size_t(args.samples) * 32;
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
                   const std::vector<Row> &rows) {
  fs::create_directories(args.out_dir);
  std::ofstream json(args.out_dir / "cuda_l2_clock_results.json");
  json << std::fixed << std::setprecision(6)
       << "{\n  \"schema\": \"UGTS-CUDA-L2-CLOCK64-1.0\",\n"
          "  \"runtime\": \"CUDA sm_120 / clock64 / ld.global.cg.u32\",\n"
          "  \"device\": {\"name\": \""
       << properties.name << "\", \"compute_capability\": \""
       << properties.major << '.' << properties.minor << "\", \"l2_bytes\": "
       << properties.l2CacheSize << ", \"multiprocessors\": "
       << properties.multiProcessorCount << ", \"reported_clock_khz\": "
       << properties.clockRate << "},\n"
          "  \"run_parameters\": {\"warmup_pairs\": "
       << args.warmup << ", \"measured_pairs\": " << args.samples
       << ", \"threads\": 32, \"dependent_loads_per_thread\": 512, "
          "\"eviction_bytes\": "
       << args.eviction_mib * 1024 * 1024 << "},\n"
          "  \"semantics\": \"clock64 is a per-SM cycle counter, but elapsed "
          "thread time can include time slicing. ld.global.cg bypasses L1 and "
          "uses the L2/global path. Cold rows follow a 256 MiB L2 eviction "
          "pass; hot rows immediately repeat the identical chain.\",\n"
          "  \"results\": [\n";
  for (std::size_t i = 0; i < rows.size(); ++i) {
    const auto &row = rows[i];
    json << "    {\"table_bytes\": " << row.table_bytes
         << ", \"table_mib\": " << row.table_bytes / (1024 * 1024)
         << ", \"l2_fraction\": "
         << double(row.table_bytes) / properties.l2CacheSize
         << ", \"entries\": " << row.entries << ", \"samples\": "
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
    json << ", \"cold_net_cycles_per_load\": "
         << row.cold_net_cycles_per_load
         << ", \"hot_net_cycles_per_load\": " << row.hot_net_cycles_per_load
         << ", \"cold_to_hot_ratio\": " << row.cold_to_hot_ratio
         << ", \"validated_control\": " << row.validated_control
         << ", \"validated_cold\": " << row.validated_cold
         << ", \"validated_hot\": " << row.validated_hot
         << ", \"validation\": " << (row.valid ? "true" : "false") << '}'
         << (i + 1 == rows.size() ? "\n" : ",\n");
  }
  json << "  ]\n}\n";
  std::ofstream csv(args.out_dir / "cuda_l2_clock_results.csv");
  csv << "table_bytes,table_mib,l2_fraction,samples,control_p50_cycles,"
         "cold_p50_cycles,hot_p50_cycles,cold_net_cycles_per_load,"
         "hot_net_cycles_per_load,cold_to_hot_ratio,cold_kernel_p50_us,"
         "hot_kernel_p50_us,validated_control,validated_cold,validated_hot,"
         "validation\n"
      << std::fixed << std::setprecision(6);
  for (const auto &row : rows)
    csv << row.table_bytes << ',' << row.table_bytes / (1024 * 1024) << ','
        << double(row.table_bytes) / properties.l2CacheSize << ',' << row.samples
        << ',' << row.control_cycles.p50 << ',' << row.cold_cycles.p50 << ','
        << row.hot_cycles.p50 << ',' << row.cold_net_cycles_per_load << ','
        << row.hot_net_cycles_per_load << ',' << row.cold_to_hot_ratio << ','
        << row.cold_kernel_us.p50 << ',' << row.hot_kernel_us.p50 << ','
        << row.validated_control << ',' << row.validated_cold << ','
        << row.validated_hot << ',' << (row.valid ? 1 : 0) << '\n';
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
    if (properties.major != 12)
      std::cerr << "warning: benchmark was designed for the local sm_120 "
                   "device; selected compute capability is "
                << properties.major << '.' << properties.minor << '\n';
    const std::size_t eviction_bytes = args.eviction_mib * 1024 * 1024,
                      eviction_entries =
                          eviction_bytes / sizeof(std::uint32_t);
    constexpr int eviction_blocks = 2048;
    std::uint32_t *eviction = nullptr, *eviction_sink = nullptr;
    cuda_check(cudaMalloc(&eviction, eviction_bytes), "cudaMalloc(eviction)");
    cuda_check(cudaMalloc(&eviction_sink,
                          std::size_t(eviction_blocks) * 256 *
                              sizeof(std::uint32_t)),
               "cudaMalloc(eviction sink)");
    cuda_check(cudaMemset(eviction, 0xa5, eviction_bytes),
               "cudaMemset(eviction)");
    std::cout << "CUDA L2 clock device: " << properties.name << " sm_"
              << properties.major << properties.minor << " L2="
              << properties.l2CacheSize << " bytes\n";
    std::vector<Row> rows;
    for (auto table_mib : args.table_mib) {
      auto row = run_table(args, table_mib, eviction, eviction_entries,
                           eviction_sink, eviction_blocks);
      std::cout << std::setw(4) << table_mib << " MiB cold=" << std::fixed
                << std::setprecision(2) << row.cold_net_cycles_per_load
                << " cycles/load hot=" << row.hot_net_cycles_per_load
                << " cycles/load ratio=" << row.cold_to_hot_ratio
                << "x valid=" << (row.valid ? "yes" : "no") << '\n';
      rows.push_back(row);
    }
    write_results(args, properties, rows);
    cudaFree(eviction_sink);
    cudaFree(eviction);
    const bool valid = std::all_of(rows.begin(), rows.end(),
                                   [](const Row &row) { return row.valid; });
    return valid ? 0 : 2;
  } catch (const std::exception &error) {
    std::cerr << "UGTS CUDA L2 clock benchmark error: " << error.what()
              << '\n';
    return 1;
  }
}
