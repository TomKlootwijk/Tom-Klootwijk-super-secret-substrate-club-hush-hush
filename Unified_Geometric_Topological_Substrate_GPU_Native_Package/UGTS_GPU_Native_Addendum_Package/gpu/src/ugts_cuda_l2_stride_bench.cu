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
constexpr std::uint32_t kCpuValidatedThreads = 64;

void cuda_check(cudaError_t result, const char *what) {
  if (result != cudaSuccess)
    throw std::runtime_error(std::string(what) + ": " +
                             cudaGetErrorString(result));
}

struct Args {
  fs::path out_dir = "cuda_l2_stride_out";
  std::vector<std::uint32_t> target_mib = {
      4, 8, 9, 10, 11, 12, 16, 17, 18, 19, 20, 21, 22, 23,
      24, 28, 32, 36, 37, 38, 39, 40, 48, 56, 64};
  std::vector<std::uint32_t> stride_bytes = {4, 8, 16, 32, 64, 128, 256};
  std::vector<int> warps = {184, 1104};
  std::size_t eviction_mib = 256;
  int warmup = 3;
  int samples = 12;
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
    else
      throw std::runtime_error("unknown argument: " + arg);
  }
  if (args.warmup < 0 || args.samples < 1 || args.eviction_mib < 64)
    throw std::runtime_error("invalid L2-stride run parameters");
  for (auto target : args.target_mib)
    if (target < 1 || target > 256)
      throw std::runtime_error("target MiB must be in [1, 256]");
  for (auto stride : args.stride_bytes)
    if (stride < 4 || stride > 1024 || (stride & (stride - 1u)) != 0)
      throw std::runtime_error("stride must be a power of two in [4, 1024]");
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

__host__ __device__ std::uint32_t permute_once(std::uint32_t x,
                                               std::uint32_t key,
                                               std::uint32_t mask) {
  x ^= key & mask;
  x ^= x >> 16;
  x = (x * 0x7feb352du) & mask;
  x ^= (x << 13) & mask;
  x = (x * 0x846ca68bu + (key | 1u)) & mask;
  x ^= x >> 15;
  return x & mask;
}

__host__ __device__ std::uint32_t permute_index(std::uint32_t x,
                                                std::uint32_t nodes,
                                                std::uint32_t mask,
                                                std::uint32_t key) {
  do {
    x = permute_once(x, key, mask);
  } while (x >= nodes);
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

__global__ void initialize_sparse(std::uint32_t *data, std::uint32_t nodes,
                                  std::uint32_t stride_words,
                                  std::uint32_t mask, std::uint32_t key) {
  const std::uint32_t node = threadIdx.x + blockIdx.x * blockDim.x;
  if (node < nodes)
    data[std::uint64_t(node) * stride_words] =
        permute_index(node, nodes, mask, key);
}

__global__ void initialize_filler(std::uint32_t *data, std::uint64_t words,
                                  std::uint32_t key) {
  const std::uint64_t word = threadIdx.x + std::uint64_t(blockIdx.x) * blockDim.x;
  if (word < words)
    data[word] = mix32(std::uint32_t(word) ^ key) ^
                 mix32(std::uint32_t(word >> 32) + 0x9e3779b9u);
}

__device__ __forceinline__ std::uint32_t initial_index(
    std::uint32_t lane, std::uint32_t warp, std::uint32_t sample_seed,
    std::uint32_t nodes, std::uint32_t &seed) {
  seed = mix32(sample_seed ^ (warp * 0x9e3779b9u));
  return mix32(lane ^ mix32(seed)) % nodes;
}

template <int Steps>
__global__ void chase_sparse(const std::uint32_t *data, std::uint32_t nodes,
                             std::uint32_t stride_words,
                             std::uint32_t sample_seed,
                             ClockResult *results) {
  const std::uint32_t lane = threadIdx.x;
  const std::uint32_t warp = blockIdx.x;
  const std::uint32_t output = warp * kWarpSize + lane;
  std::uint32_t seed = 0;
  std::uint32_t index =
      initial_index(lane, warp, sample_seed, nodes, seed);
  asm volatile("" ::: "memory");
  const unsigned long long started = clock64();
#pragma unroll 1
  for (int step = 0; step < Steps; ++step)
    index = load_global_l2(data + std::uint64_t(index) * stride_words);
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

struct Row {
  std::uint32_t target_mib = 0, stride_bytes = 0, nodes = 0;
  std::uint64_t allocation_bytes = 0;
  int warps = 0, threads = 0, samples = 0;
  std::size_t validated_control = 0, validated_cold = 0, validated_hot = 0;
  Distribution control_cycles, cold_cycles, hot_cycles, cold_us, hot_us;
  double cold_net_cycles_per_step = 0, hot_net_cycles_per_step = 0;
  double cold_gloads_s = 0, hot_gloads_s = 0;
  bool valid = false;
};

void validate(const std::vector<ClockResult> &results,
              std::uint32_t nodes, std::uint32_t mask, std::uint32_t key,
              std::uint32_t sample_seed, std::uint32_t steps,
              std::vector<double> &cycles, std::size_t &validated) {
  const std::size_t output_count =
      std::min<std::size_t>(results.size(), kCpuValidatedThreads);
  for (std::size_t output = 0; output < output_count; ++output) {
    const std::uint32_t warp = std::uint32_t(output / kWarpSize);
    const std::uint32_t lane = std::uint32_t(output % kWarpSize);
    const std::uint32_t seed = mix32(sample_seed ^ (warp * 0x9e3779b9u));
    const std::uint32_t initial = mix32(lane ^ mix32(seed)) % nodes;
    std::uint32_t expected = initial;
    for (std::uint32_t step = 0; step < steps; ++step)
      expected = permute_index(expected, nodes, mask, key);
    const auto &actual = results[output];
    if (actual.final_index == expected &&
        actual.checksum == mix32(expected ^ lane ^ seed) &&
        actual.seed == seed && actual.steps == steps &&
        actual.finished >= actual.started)
      ++validated;
    cycles.push_back(double(actual.finished - actual.started));
  }
}

Row run_case(const Args &args, std::uint32_t target_mib,
             std::uint32_t stride_bytes, int warps,
             const std::uint32_t *eviction, std::size_t eviction_entries,
             std::uint32_t *eviction_sink, int eviction_blocks) {
  const std::uint64_t target_bytes = std::uint64_t(target_mib) * 1024 * 1024;
  const std::uint32_t assumed_unit = std::min<std::uint32_t>(stride_bytes, 32u);
  const std::uint32_t nodes = std::uint32_t(target_bytes / assumed_unit);
  const std::uint32_t stride_words = stride_bytes / sizeof(std::uint32_t);
  const std::uint64_t allocation_bytes = std::uint64_t(nodes) * stride_bytes;
  const std::size_t threads = std::size_t(warps) * kWarpSize;
  std::uint32_t mask = 1u;
  while (mask < nodes - 1u)
    mask = (mask << 1u) | 1u;
  const std::uint32_t permutation_key = mix32(target_mib * 0x9e3779b9u);
  std::uint32_t *table = nullptr;
  ClockResult *control_out = nullptr, *cold_out = nullptr, *hot_out = nullptr;
  cuda_check(cudaMalloc(&table, allocation_bytes), "cudaMalloc(stride table)");
  cuda_check(cudaMalloc(&control_out, threads * sizeof(ClockResult)),
             "cudaMalloc(control output)");
  cuda_check(cudaMalloc(&cold_out, threads * sizeof(ClockResult)),
             "cudaMalloc(cold output)");
  cuda_check(cudaMalloc(&hot_out, threads * sizeof(ClockResult)),
             "cudaMalloc(hot output)");
  const std::uint64_t allocation_words = allocation_bytes / sizeof(std::uint32_t);
  initialize_filler<<<int((allocation_words + 255) / 256), 256>>>(
      table, allocation_words, permutation_key ^ 0xa5a5a5a5u);
  initialize_sparse<<<int((std::uint64_t(nodes) + 255) / 256), 256>>>(
      table, nodes, stride_words, mask, permutation_key);
  cuda_check(cudaGetLastError(), "sparse initialization launch");
  cuda_check(cudaDeviceSynchronize(), "sparse initialization sync");
  cudaEvent_t cold_start{}, cold_end{}, hot_start{}, hot_end{};
  cuda_check(cudaEventCreate(&cold_start), "cudaEventCreate(cold start)");
  cuda_check(cudaEventCreate(&cold_end), "cudaEventCreate(cold end)");
  cuda_check(cudaEventCreate(&hot_start), "cudaEventCreate(hot start)");
  cuda_check(cudaEventCreate(&hot_end), "cudaEventCreate(hot end)");
  std::vector<ClockResult> control(threads), cold(threads), hot(threads);
  std::vector<double> control_cycles, cold_cycles, hot_cycles, cold_us, hot_us;
  std::size_t valid_control = 0, valid_cold = 0, valid_hot = 0;
  for (int sample = -args.warmup; sample < args.samples; ++sample) {
    const std::uint32_t seed =
        mix32(std::uint32_t(sample + args.warmup + 1) * 0xc2b2ae35u);
    evict_global<<<eviction_blocks, 256>>>(eviction, eviction_entries,
                                           eviction_sink);
    chase_sparse<0><<<warps, kWarpSize>>>(table, nodes, stride_words, seed,
                                           control_out);
    cuda_check(cudaEventRecord(cold_start), "cudaEventRecord(cold start)");
    chase_sparse<kSteps><<<warps, kWarpSize>>>(table, nodes, stride_words, seed,
                                                cold_out);
    cuda_check(cudaEventRecord(cold_end), "cudaEventRecord(cold end)");
    cuda_check(cudaEventRecord(hot_start), "cudaEventRecord(hot start)");
    chase_sparse<kSteps><<<warps, kWarpSize>>>(table, nodes, stride_words, seed,
                                                hot_out);
    cuda_check(cudaEventRecord(hot_end), "cudaEventRecord(hot end)");
    cuda_check(cudaGetLastError(), "stride chase launch");
    cuda_check(cudaMemcpy(control.data(), control_out,
                          threads * sizeof(ClockResult), cudaMemcpyDeviceToHost),
               "cudaMemcpy(control)");
    cuda_check(cudaMemcpy(cold.data(), cold_out, threads * sizeof(ClockResult),
                          cudaMemcpyDeviceToHost),
               "cudaMemcpy(cold)");
    cuda_check(cudaMemcpy(hot.data(), hot_out, threads * sizeof(ClockResult),
                          cudaMemcpyDeviceToHost),
               "cudaMemcpy(hot)");
    float cold_ms = 0, hot_ms = 0;
    cuda_check(cudaEventElapsedTime(&cold_ms, cold_start, cold_end),
               "cudaEventElapsedTime(cold)");
    cuda_check(cudaEventElapsedTime(&hot_ms, hot_start, hot_end),
               "cudaEventElapsedTime(hot)");
    if (sample >= 0) {
      validate(control, nodes, mask, permutation_key, seed, 0, control_cycles,
               valid_control);
      validate(cold, nodes, mask, permutation_key, seed, kSteps, cold_cycles,
               valid_cold);
      validate(hot, nodes, mask, permutation_key, seed, kSteps, hot_cycles,
               valid_hot);
      cold_us.push_back(double(cold_ms) * 1000.0);
      hot_us.push_back(double(hot_ms) * 1000.0);
    }
  }
  Row row{};
  row.target_mib = target_mib;
  row.stride_bytes = stride_bytes;
  row.nodes = nodes;
  row.allocation_bytes = allocation_bytes;
  row.warps = warps;
  row.threads = int(threads);
  row.samples = args.samples;
  row.validated_control = valid_control;
  row.validated_cold = valid_cold;
  row.validated_hot = valid_hot;
  row.control_cycles = summarize(control_cycles);
  row.cold_cycles = summarize(cold_cycles);
  row.hot_cycles = summarize(hot_cycles);
  row.cold_us = summarize(cold_us);
  row.hot_us = summarize(hot_us);
  row.cold_net_cycles_per_step =
      (row.cold_cycles.p50 - row.control_cycles.p50) / kSteps;
  row.hot_net_cycles_per_step =
      (row.hot_cycles.p50 - row.control_cycles.p50) / kSteps;
  const double loads = double(row.threads) * kSteps;
  row.cold_gloads_s = loads / (row.cold_us.p50 * 1000.0);
  row.hot_gloads_s = loads / (row.hot_us.p50 * 1000.0);
  const std::size_t expected = std::size_t(args.samples) *
                               std::min<std::size_t>(threads,
                                                     kCpuValidatedThreads);
  row.valid = valid_control == expected && valid_cold == expected &&
              valid_hot == expected;
  cudaEventDestroy(cold_start);
  cudaEventDestroy(cold_end);
  cudaEventDestroy(hot_start);
  cudaEventDestroy(hot_end);
  cudaFree(hot_out);
  cudaFree(cold_out);
  cudaFree(control_out);
  cudaFree(table);
  return row;
}

void write_distribution(std::ostream &out, const Distribution &d) {
  out << "{\"min\": " << d.minimum << ", \"mean\": " << d.mean
      << ", \"p50\": " << d.p50 << ", \"p95\": " << d.p95
      << ", \"p99\": " << d.p99 << ", \"max\": " << d.maximum << '}';
}

void write_results(const Args &args, const cudaDeviceProp &properties,
                   int occupancy, const std::vector<Row> &rows) {
  fs::create_directories(args.out_dir);
  std::ofstream json(args.out_dir / "cuda_l2_stride_results.json");
  json << std::fixed << std::setprecision(6)
       << "{\n  \"schema\": \"UGTS-CUDA-L2-STRIDE-1.0\",\n"
          "  \"runtime\": \"CUDA sm_120 sparse-stride ld.global.cg dependent chains\",\n"
          "  \"device\": {\"name\": \""
       << properties.name << "\", \"compute_capability\": \""
       << properties.major << '.' << properties.minor << "\", \"l2_bytes\": "
       << properties.l2CacheSize << ", \"multiprocessors\": "
       << properties.multiProcessorCount
       << ", \"one_warp_blocks_per_sm\": " << occupancy << "},\n"
          "  \"run_parameters\": {\"warmup_pairs\": "
       << args.warmup << ", \"measured_pairs\": " << args.samples
       << ", \"dependent_loads_per_thread\": " << kSteps
       << ", \"eviction_bytes\": " << args.eviction_mib * 1024 * 1024
       << "},\n"
          "  \"semantics\": \"Each logical node stores one nonlinear cycle-walked permutation next-index at byte offset node*stride. Every gap word is filled with deterministic mixed data before pointer fields are written, preventing zero-filled sparse lines from inflating effective capacity. target_mib chooses node_count*min(stride,32); raw node count, stride and allocation bytes are authoritative. The first 64 output lanes per sample are independently replayed on CPU. The sweep tests which assumed per-node cache unit collapses the capacity boundary.\",\n"
          "  \"results\": [\n";
  for (std::size_t i = 0; i < rows.size(); ++i) {
    const auto &row = rows[i];
    json << "    {\"target_mib\": " << row.target_mib
         << ", \"stride_bytes\": " << row.stride_bytes
         << ", \"nodes\": " << row.nodes
         << ", \"allocation_bytes\": " << row.allocation_bytes
         << ", \"allocation_mib\": "
         << double(row.allocation_bytes) / (1024 * 1024)
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
    json << ", \"cold_net_cycles_per_step\": "
         << row.cold_net_cycles_per_step
         << ", \"hot_net_cycles_per_step\": "
         << row.hot_net_cycles_per_step << ", \"cold_gloads_s\": "
         << row.cold_gloads_s << ", \"hot_gloads_s\": " << row.hot_gloads_s
         << ", \"validated_control\": " << row.validated_control
         << ", \"validated_cold\": " << row.validated_cold
         << ", \"validated_hot\": " << row.validated_hot
         << ", \"validation\": " << (row.valid ? "true" : "false") << '}'
         << (i + 1 == rows.size() ? "\n" : ",\n");
  }
  json << "  ]\n}\n";
  std::ofstream csv(args.out_dir / "cuda_l2_stride_results.csv");
  csv << "target_mib,stride_bytes,nodes,allocation_bytes,allocation_mib,warps,"
         "warps_per_sm,threads,samples,control_p50_cycles,cold_p50_cycles,"
         "hot_p50_cycles,cold_net_cycles_per_step,hot_net_cycles_per_step,"
         "cold_kernel_p50_us,hot_kernel_p50_us,cold_gloads_s,hot_gloads_s,"
         "validated_control,validated_cold,validated_hot,validation\n"
      << std::fixed << std::setprecision(6);
  for (const auto &row : rows)
    csv << row.target_mib << ',' << row.stride_bytes << ',' << row.nodes << ','
        << row.allocation_bytes << ','
        << double(row.allocation_bytes) / (1024 * 1024) << ',' << row.warps
        << ',' << double(row.warps) / properties.multiProcessorCount << ','
        << row.threads << ',' << row.samples << ',' << row.control_cycles.p50
        << ',' << row.cold_cycles.p50 << ',' << row.hot_cycles.p50 << ','
        << row.cold_net_cycles_per_step << ',' << row.hot_net_cycles_per_step
        << ',' << row.cold_us.p50 << ',' << row.hot_us.p50 << ','
        << row.cold_gloads_s << ',' << row.hot_gloads_s << ','
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
    int occupancy = 0;
    cuda_check(cudaOccupancyMaxActiveBlocksPerMultiprocessor(
                   &occupancy, chase_sparse<kSteps>, kWarpSize, 0),
               "stride occupancy query");
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
    std::cout << "CUDA L2-stride device: " << properties.name << " sm_"
              << properties.major << properties.minor << " L2="
              << properties.l2CacheSize << " bytes SMs="
              << properties.multiProcessorCount << " occupancy=" << occupancy
              << '\n';
    std::vector<Row> rows;
    for (auto target : args.target_mib)
      for (auto stride : args.stride_bytes)
        for (auto warps : args.warps) {
          Row row = run_case(args, target, stride, warps, eviction,
                             eviction_entries, eviction_sink, eviction_blocks);
          std::cout << std::setw(3) << target << " target MiB stride="
                    << std::setw(3) << stride << " allocation=" << std::setw(3)
                    << row.allocation_bytes / (1024 * 1024) << " MiB warps="
                    << std::setw(4) << warps << " hot=" << std::fixed
                    << std::setprecision(3) << row.hot_gloads_s
                    << " Gload/s valid=" << (row.valid ? "yes" : "no") << '\n';
          rows.push_back(row);
        }
    write_results(args, properties, occupancy, rows);
    cudaFree(eviction_sink);
    cudaFree(eviction);
    return std::all_of(rows.begin(), rows.end(),
                       [](const Row &row) { return row.valid; })
               ? 0
               : 2;
  } catch (const std::exception &error) {
    std::cerr << "UGTS CUDA L2-stride benchmark error: " << error.what() << '\n';
    return 1;
  }
}
