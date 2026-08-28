#include <cuda.h>
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
#include <utility>
#include <vector>

namespace fs = std::filesystem;

namespace {

constexpr std::uint32_t kSteps = 512;
constexpr std::uint32_t kWarpSize = 32;
constexpr std::uint32_t kCpuValidatedThreads = 32;
constexpr std::uint32_t kLcgMul = 1664525u;
constexpr std::uint32_t kLcgAdd = 1013904223u;

void cuda_check(cudaError_t result, const char *what) {
  if (result != cudaSuccess)
    throw std::runtime_error(std::string(what) + ": " +
                             cudaGetErrorString(result));
}

void cu_check(CUresult result, const char *what) {
  if (result == CUDA_SUCCESS)
    return;
  const char *name = nullptr;
  const char *message = nullptr;
  cuGetErrorName(result, &name);
  cuGetErrorString(result, &message);
  throw std::runtime_error(std::string(what) + ": " +
                           (name ? name : "unknown") + " (" +
                           (message ? message : "no message") + ")");
}

struct CaseSpec {
  std::uint32_t aliases = 0;
  std::uint32_t pitch_mib = 0;
};

struct Args {
  fs::path out_dir = "cuda_vmm_alias_out";
  std::vector<CaseSpec> cases = {
      {32, 2},  {32, 4},  {32, 6},  {32, 8},  {64, 2},  {64, 4},
      {64, 6},  {64, 8},  {96, 2},  {112, 2}, {120, 2}, {124, 2},
      {126, 2}, {127, 2}, {128, 2}, {129, 2}, {130, 2}, {132, 2},
      {136, 2}, {144, 2}, {160, 2}, {192, 2}, {128, 4}};
  std::vector<int> warps = {184, 1104};
  std::size_t eviction_mib = 256;
  int warmup = 2;
  int samples = 10;
  int order = 0;
};

template <typename T>
std::vector<T> parse_numeric_list(const std::string &text) {
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

std::vector<CaseSpec> parse_cases(const std::string &text) {
  std::stringstream stream(text);
  std::string part;
  std::vector<CaseSpec> result;
  while (std::getline(stream, part, ',')) {
    if (part.empty())
      continue;
    const auto separator = part.find_first_of("xX:");
    if (separator == std::string::npos)
      throw std::runtime_error("case must be ALIASESxPITCH_MIB: " + part);
    result.push_back({std::uint32_t(std::stoul(part.substr(0, separator))),
                      std::uint32_t(std::stoul(part.substr(separator + 1)))});
  }
  if (result.empty())
    throw std::runtime_error("empty case list");
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
    else if (arg == "--cases")
      args.cases = parse_cases(value("--cases"));
    else if (arg == "--warps")
      args.warps = parse_numeric_list<int>(value("--warps"));
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
    throw std::runtime_error("invalid VMM-alias run parameters");
  for (const auto &item : args.cases) {
    if (item.aliases < 2 || item.aliases > 512)
      throw std::runtime_error("alias count must be in [2, 512]");
    if (item.pitch_mib < 2 || item.pitch_mib > 64)
      throw std::runtime_error("pitch MiB must be in [2, 64]");
  }
  for (const int warps : args.warps)
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

__host__ __device__ __forceinline__ std::uint32_t code_for_offset(
    std::uint32_t offset) {
  return mix32(offset ^ 0x6a09e667u) & 63u;
}

__host__ __device__ __forceinline__ std::uint32_t roll_checksum(
    std::uint32_t checksum, std::uint32_t code, std::uint32_t alias,
    std::uint32_t offset) {
  return (checksum ^ code ^ (alias * 0x9e3779b9u) ^ offset) * 16777619u +
         0x27d4eb2du;
}

__device__ __forceinline__ std::uint32_t load_global_l2(
    const std::uint32_t *address) {
  std::uint32_t value;
  asm volatile("ld.global.cg.u32 %0, [%1];" : "=r"(value) : "l"(address));
  return value;
}

__global__ void initialize_physical_words(std::uint32_t *words,
                                          std::uint32_t word_count) {
  const std::uint32_t word = threadIdx.x + blockIdx.x * blockDim.x;
  if (word < word_count)
    words[word] = code_for_offset(word);
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
__global__ void lookup_vmm_aliases(const std::uint32_t *global_words,
                                   cudaTextureObject_t texture,
                                   std::uint32_t aliases,
                                   std::uint64_t pitch_words,
                                   std::uint32_t physical_word_mask,
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
    const std::uint32_t alias = __umulhi(state, aliases);
    const std::uint32_t offset =
        mix32(state ^ std::uint32_t(step * 0x9e3779b9u)) & physical_word_mask;
    const std::uint64_t index = std::uint64_t(alias) * pitch_words + offset;
    const std::uint32_t code =
        load_word<Texture>(global_words, texture, index) & 63u;
    mismatches += std::uint32_t(code != code_for_offset(offset));
    checksum = roll_checksum(checksum, code, alias, offset);
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

cudaTextureObject_t make_linear_texture(const std::uint32_t *data,
                                        std::size_t bytes) {
  cudaResourceDesc resource{};
  resource.resType = cudaResourceTypeLinear;
  resource.res.linear.devPtr = const_cast<std::uint32_t *>(data);
  resource.res.linear.desc = cudaCreateChannelDesc<std::uint32_t>();
  resource.res.linear.sizeInBytes = bytes;
  cudaTextureDesc descriptor{};
  descriptor.readMode = cudaReadModeElementType;
  cudaTextureObject_t texture = 0;
  cuda_check(cudaCreateTextureObject(&texture, &resource, &descriptor, nullptr),
             "cudaCreateTextureObject");
  return texture;
}

class AliasedVmmMapping {
 public:
  AliasedVmmMapping(CUdevice device, std::size_t granularity,
                    std::size_t mapped_bytes)
      : granularity_(granularity), mapped_bytes_(mapped_bytes) {
    if (mapped_bytes_ == 0 || mapped_bytes_ % granularity_ != 0)
      throw std::runtime_error("VMM span is not allocation-granularity aligned");
    CUmemAllocationProp properties{};
    properties.type = CU_MEM_ALLOCATION_TYPE_PINNED;
    properties.requestedHandleTypes = CU_MEM_HANDLE_TYPE_NONE;
    properties.location.type = CU_MEM_LOCATION_TYPE_DEVICE;
    properties.location.id = device;
    cu_check(cuMemAddressReserve(&base_, mapped_bytes_, granularity_, 0, 0),
             "cuMemAddressReserve");
    try {
      cu_check(cuMemCreate(&handle_, granularity_, &properties, 0),
               "cuMemCreate");
      for (std::size_t offset = 0; offset < mapped_bytes_;
           offset += granularity_) {
        cu_check(cuMemMap(base_ + offset, granularity_, 0, handle_, 0),
                 "cuMemMap(alias)");
        ++mapped_slots_;
      }
      CUmemAccessDesc access{};
      access.location.type = CU_MEM_LOCATION_TYPE_DEVICE;
      access.location.id = device;
      access.flags = CU_MEM_ACCESS_FLAGS_PROT_READWRITE;
      cu_check(cuMemSetAccess(base_, mapped_bytes_, &access, 1),
               "cuMemSetAccess");
    } catch (...) {
      cleanup();
      throw;
    }
  }

  AliasedVmmMapping(const AliasedVmmMapping &) = delete;
  AliasedVmmMapping &operator=(const AliasedVmmMapping &) = delete;
  ~AliasedVmmMapping() { cleanup(); }

  std::uint32_t *data() const {
    return reinterpret_cast<std::uint32_t *>(base_);
  }
  std::size_t mapped_bytes() const { return mapped_bytes_; }
  std::size_t physical_bytes() const { return granularity_; }
  std::size_t mapped_slots() const { return mapped_slots_; }
  std::uint64_t base_address() const { return std::uint64_t(base_); }

 private:
  void cleanup() noexcept {
    if (base_ != 0) {
      for (std::size_t slot = 0; slot < mapped_slots_; ++slot)
        cuMemUnmap(base_ + slot * granularity_, granularity_);
    }
    mapped_slots_ = 0;
    if (handle_ != 0)
      cuMemRelease(handle_);
    handle_ = 0;
    if (base_ != 0)
      cuMemAddressFree(base_, mapped_bytes_);
    base_ = 0;
  }

  CUdeviceptr base_ = 0;
  CUmemGenericAllocationHandle handle_ = 0;
  std::size_t granularity_ = 0;
  std::size_t mapped_bytes_ = 0;
  std::size_t mapped_slots_ = 0;
};

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

struct Expected {
  std::uint32_t final_state = 0;
  std::uint32_t checksum = 0;
};

Expected replay(std::uint32_t seed, std::uint32_t aliases,
                std::uint32_t physical_word_mask, std::uint32_t steps) {
  std::uint32_t state = seed;
  std::uint32_t checksum = seed ^ 0x3c6ef372u;
  for (std::uint32_t step = 0; step < steps; ++step) {
    state = state * kLcgMul + kLcgAdd;
    const std::uint32_t alias =
        std::uint32_t((std::uint64_t(state) * aliases) >> 32u);
    const std::uint32_t offset = mix32(state ^ (step * 0x9e3779b9u)) &
                                 physical_word_mask;
    checksum =
        roll_checksum(checksum, code_for_offset(offset), alias, offset);
  }
  return {state, checksum};
}

struct ValidationCounts {
  std::size_t cpu_payloads = 0;
  std::size_t zero_mismatch_payloads = 0;
};

void validate_results(const std::vector<LookupResult> &results,
                      std::uint32_t sample_seed, std::uint32_t aliases,
                      std::uint32_t physical_word_mask, std::uint32_t steps,
                      std::vector<double> &cycles, ValidationCounts &counts) {
  for (const auto &actual : results) {
    if (actual.mismatch_count == 0u && actual.steps == steps &&
        actual.finished >= actual.started)
      ++counts.zero_mismatch_payloads;
    cycles.push_back(double(actual.finished - actual.started));
  }
  const std::size_t cpu_count =
      std::min<std::size_t>(results.size(), kCpuValidatedThreads);
  for (std::size_t output = 0; output < cpu_count; ++output) {
    const std::uint32_t warp = std::uint32_t(output / kWarpSize);
    const std::uint32_t lane = std::uint32_t(output % kWarpSize);
    const std::uint32_t seed = initial_seed(lane, warp, sample_seed);
    const Expected expected =
        replay(seed, aliases, physical_word_mask, steps);
    const auto &actual = results[output];
    if (actual.final_state == expected.final_state &&
        actual.checksum == expected.checksum && actual.mismatch_count == 0u &&
        actual.seed == seed && actual.steps == steps &&
        actual.finished >= actual.started)
      ++counts.cpu_payloads;
  }
}

enum class Mode { Global, Texture };

template <int Steps>
void launch_mode(Mode mode, int warps, const std::uint32_t *words,
                 cudaTextureObject_t texture, std::uint32_t aliases,
                 std::uint64_t pitch_words,
                 std::uint32_t physical_word_mask, std::uint32_t seed,
                 LookupResult *output) {
  if (mode == Mode::Global)
    lookup_vmm_aliases<Steps, false><<<warps, kWarpSize>>>(
        words, 0, aliases, pitch_words, physical_word_mask, seed, output);
  else
    lookup_vmm_aliases<Steps, true><<<warps, kWarpSize>>>(
        words, texture, aliases, pitch_words, physical_word_mask, seed, output);
}

struct Accumulator {
  std::vector<double> control_cycles, cold_cycles, hot_cycles, cold_us, hot_us;
  ValidationCounts control_validation, cold_validation, hot_validation;
};

struct Row {
  std::string path;
  CaseSpec spec{};
  std::uint64_t pitch_bytes = 0, virtual_span_bytes = 0;
  std::uint64_t virtual_base_address = 0;
  std::uint64_t physical_backing_bytes = 0, accessed_physical_bytes = 0;
  std::uint32_t mapped_slots = 0;
  int warps = 0, threads = 0, samples = 0;
  ValidationCounts control_validation, cold_validation, hot_validation;
  Distribution control_cycles, cold_cycles, hot_cycles, cold_us, hot_us;
  double cold_net_cycles_per_lookup = 0, hot_net_cycles_per_lookup = 0;
  double cold_glookups_s = 0, hot_glookups_s = 0;
  bool valid = false;
};

Row make_row(const Args &args, Mode mode, CaseSpec spec,
             std::uint64_t pitch_bytes, const AliasedVmmMapping &mapping,
             int warps, const Accumulator &data) {
  Row row{};
  row.path = mode == Mode::Global ? "global_cg" : "texture_object";
  row.spec = spec;
  row.pitch_bytes = pitch_bytes;
  row.virtual_span_bytes = mapping.mapped_bytes();
  row.virtual_base_address = mapping.base_address();
  row.physical_backing_bytes = mapping.physical_bytes();
  row.accessed_physical_bytes = mapping.physical_bytes();
  row.mapped_slots = std::uint32_t(mapping.mapped_slots());
  row.warps = warps;
  row.threads = warps * int(kWarpSize);
  row.samples = args.samples;
  row.control_validation = data.control_validation;
  row.cold_validation = data.cold_validation;
  row.hot_validation = data.hot_validation;
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
  const std::size_t expected_cpu =
      std::size_t(args.samples) *
      std::min<std::size_t>(row.threads, kCpuValidatedThreads);
  const std::size_t expected_gpu = std::size_t(args.samples) * row.threads;
  row.valid =
      data.control_validation.cpu_payloads == expected_cpu &&
      data.cold_validation.cpu_payloads == expected_cpu &&
      data.hot_validation.cpu_payloads == expected_cpu &&
      data.control_validation.zero_mismatch_payloads == expected_gpu &&
      data.cold_validation.zero_mismatch_payloads == expected_gpu &&
      data.hot_validation.zero_mismatch_payloads == expected_gpu;
  return row;
}

Row run_case(const Args &args, const AliasedVmmMapping &mapping,
             cudaTextureObject_t texture, Mode mode, CaseSpec spec, int warps,
             const std::uint32_t *eviction,
             cudaTextureObject_t eviction_texture,
             std::size_t eviction_entries, std::uint32_t *eviction_sink,
             int eviction_blocks) {
  const std::uint64_t pitch_bytes =
      std::uint64_t(spec.pitch_mib) * 1024ull * 1024ull;
  const std::uint32_t physical_words =
      std::uint32_t(mapping.physical_bytes() / sizeof(std::uint32_t));
  if ((physical_words & (physical_words - 1u)) != 0u)
    throw std::runtime_error("physical VMM word count is not a power of two");
  const int threads = warps * int(kWarpSize);
  LookupResult *device_control = nullptr, *device_cold = nullptr,
               *device_hot = nullptr;
  cuda_check(cudaMalloc(&device_control, std::size_t(threads) *
                                             sizeof(LookupResult)),
             "cudaMalloc(control results)");
  cuda_check(cudaMalloc(&device_cold,
                        std::size_t(threads) * sizeof(LookupResult)),
             "cudaMalloc(cold results)");
  cuda_check(cudaMalloc(&device_hot,
                        std::size_t(threads) * sizeof(LookupResult)),
             "cudaMalloc(hot results)");
  std::vector<LookupResult> control(threads), cold(threads), hot(threads);
  cudaEvent_t cold_start{}, cold_end{}, hot_start{}, hot_end{};
  cuda_check(cudaEventCreate(&cold_start), "cudaEventCreate(cold start)");
  cuda_check(cudaEventCreate(&cold_end), "cudaEventCreate(cold end)");
  cuda_check(cudaEventCreate(&hot_start), "cudaEventCreate(hot start)");
  cuda_check(cudaEventCreate(&hot_end), "cudaEventCreate(hot end)");
  Accumulator data;
  const std::uint64_t pitch_words = pitch_bytes / sizeof(std::uint32_t);
  const std::uint32_t physical_word_mask = physical_words - 1u;
  for (int sample = -args.warmup; sample < args.samples; ++sample) {
    const std::uint32_t sample_seed =
        0x243f6a88u ^ std::uint32_t((sample + args.warmup + 1) * 0x9e3779b9u);
    launch_mode<0>(mode, warps, mapping.data(), texture, spec.aliases,
                   pitch_words, physical_word_mask, sample_seed,
                   device_control);
    if (mode == Mode::Global)
      evict_global<<<eviction_blocks, 256>>>(eviction, eviction_entries,
                                             eviction_sink);
    else
      evict_texture<<<eviction_blocks, 256>>>(eviction_texture,
                                              eviction_entries, eviction_sink);
    cuda_check(cudaEventRecord(cold_start), "cudaEventRecord(cold start)");
    launch_mode<kSteps>(mode, warps, mapping.data(), texture, spec.aliases,
                        pitch_words, physical_word_mask, sample_seed,
                        device_cold);
    cuda_check(cudaEventRecord(cold_end), "cudaEventRecord(cold end)");
    cuda_check(cudaEventRecord(hot_start), "cudaEventRecord(hot start)");
    launch_mode<kSteps>(mode, warps, mapping.data(), texture, spec.aliases,
                        pitch_words, physical_word_mask, sample_seed,
                        device_hot);
    cuda_check(cudaEventRecord(hot_end), "cudaEventRecord(hot end)");
    cuda_check(cudaGetLastError(), "VMM-alias lookup launch");
    cuda_check(cudaMemcpy(control.data(), device_control,
                          control.size() * sizeof(LookupResult),
                          cudaMemcpyDeviceToHost),
               "cudaMemcpy(control results)");
    cuda_check(cudaMemcpy(cold.data(), device_cold,
                          cold.size() * sizeof(LookupResult),
                          cudaMemcpyDeviceToHost),
               "cudaMemcpy(cold results)");
    cuda_check(cudaMemcpy(hot.data(), device_hot,
                          hot.size() * sizeof(LookupResult),
                          cudaMemcpyDeviceToHost),
               "cudaMemcpy(hot results)");
    float cold_ms = 0, hot_ms = 0;
    cuda_check(cudaEventElapsedTime(&cold_ms, cold_start, cold_end),
               "cudaEventElapsedTime(cold)");
    cuda_check(cudaEventElapsedTime(&hot_ms, hot_start, hot_end),
               "cudaEventElapsedTime(hot)");
    if (sample >= 0) {
      validate_results(control, sample_seed, spec.aliases,
                       physical_word_mask, 0, data.control_cycles,
                       data.control_validation);
      validate_results(cold, sample_seed, spec.aliases, physical_word_mask,
                       kSteps, data.cold_cycles, data.cold_validation);
      validate_results(hot, sample_seed, spec.aliases, physical_word_mask,
                       kSteps, data.hot_cycles, data.hot_validation);
      data.cold_us.push_back(double(cold_ms) * 1000.0);
      data.hot_us.push_back(double(hot_ms) * 1000.0);
    }
  }
  cudaEventDestroy(cold_start);
  cudaEventDestroy(cold_end);
  cudaEventDestroy(hot_start);
  cudaEventDestroy(hot_end);
  cudaFree(device_control);
  cudaFree(device_cold);
  cudaFree(device_hot);
  return make_row(args, mode, spec, pitch_bytes, mapping, warps, data);
}

void write_distribution(std::ostream &stream, const Distribution &value) {
  stream << "{\"min\": " << value.minimum << ", \"mean\": " << value.mean
         << ", \"p50\": " << value.p50 << ", \"p95\": " << value.p95
         << ", \"p99\": " << value.p99 << ", \"max\": " << value.maximum
         << '}';
}

void write_results(const Args &args, const cudaDeviceProp &properties,
                   std::size_t granularity, int compression_supported,
                   int global_occupancy, int texture_occupancy,
                   const std::vector<Row> &rows) {
  fs::create_directories(args.out_dir);
  std::ofstream json(args.out_dir / "cuda_vmm_alias_results.json");
  json << std::fixed << std::setprecision(6);
  json << "{\n  \"schema\": \"UGTS-CUDA-VMM-ALIAS-1.0\",\n"
          "  \"device\": {\"name\": \""
       << properties.name << "\", \"compute_capability\": \""
       << properties.major << '.' << properties.minor << "\", \"l2_bytes\": "
       << properties.l2CacheSize << ", \"multiprocessors\": "
       << properties.multiProcessorCount
       << ", \"max_texture_1d_linear_elements\": "
       << properties.maxTexture1DLinear
       << ", \"generic_compression_supported\": "
       << (compression_supported ? "true" : "false")
       << ", \"occupancy_blocks_per_sm\": {\"global_cg\": "
       << global_occupancy << ", \"texture_object\": " << texture_occupancy
       << "}},\n  \"run_parameters\": {\"lookups_per_thread\": " << kSteps
       << ", \"physical_backing_bytes\": " << granularity
       << ", \"vmm_mapping_granularity_bytes\": " << granularity
       << ", \"eviction_bytes\": " << args.eviction_mib * 1024 * 1024
       << ", \"warmup_sets\": " << args.warmup
       << ", \"measured_sets\": " << args.samples
       << ", \"path_and_case_order\": " << args.order
       << ", \"paired_paths_share_mapping\": true"
       << "},\n  \"semantics\": \"Every granularity-sized virtual slot maps the same single device-local physical allocation. Each lookup selects one tested virtual alias and a word offset inside the shared physical allocation. Physical backing and physical payload stay constant while alias count, virtual pitch and virtual span vary; both paths and both warp loads share the exact mapping for each case within a process.\",\n"
          "  \"scope_note\": \"CUDA VMM granularity is a driver allocation property, not a claim about hardware page size or TLB organization.\",\n"
          "  \"results\": [\n";
  for (std::size_t i = 0; i < rows.size(); ++i) {
    const auto &row = rows[i];
    json << "    {\"path\": \"" << row.path << "\", \"aliases\": "
         << row.spec.aliases << ", \"pitch_mib\": " << row.spec.pitch_mib
         << ", \"pitch_bytes\": " << row.pitch_bytes
         << ", \"virtual_span_bytes\": " << row.virtual_span_bytes
         << ", \"virtual_span_mib\": "
         << double(row.virtual_span_bytes) / (1024.0 * 1024.0)
         << ", \"virtual_base_address\": " << row.virtual_base_address
         << ", \"mapped_slots\": " << row.mapped_slots
         << ", \"physical_backing_bytes\": " << row.physical_backing_bytes
         << ", \"accessed_physical_bytes\": " << row.accessed_physical_bytes
         << ", \"virtual_to_physical_ratio\": "
         << double(row.virtual_span_bytes) / row.physical_backing_bytes
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
         << row.hot_glookups_s << ", \"validated_cpu_payloads\": {\"control\": "
         << row.control_validation.cpu_payloads << ", \"cold\": "
         << row.cold_validation.cpu_payloads << ", \"hot\": "
         << row.hot_validation.cpu_payloads
         << "}, \"zero_mismatch_gpu_payloads\": {\"control\": "
         << row.control_validation.zero_mismatch_payloads << ", \"cold\": "
         << row.cold_validation.zero_mismatch_payloads << ", \"hot\": "
         << row.hot_validation.zero_mismatch_payloads
         << "}, \"validation\": " << (row.valid ? "true" : "false") << '}'
         << (i + 1 == rows.size() ? "\n" : ",\n");
  }
  json << "  ]\n}\n";

  std::ofstream csv(args.out_dir / "cuda_vmm_alias_results.csv");
  csv << "path,aliases,pitch_mib,pitch_bytes,virtual_span_bytes,"
         "virtual_span_mib,virtual_base_address,mapped_slots,physical_backing_bytes,"
         "accessed_physical_bytes,virtual_to_physical_ratio,warps,"
         "warps_per_sm,threads,samples,control_p50_cycles,cold_p50_cycles,"
         "hot_p50_cycles,cold_net_cycles_per_lookup,"
         "hot_net_cycles_per_lookup,cold_p50_us,hot_p50_us,cold_glookups_s,"
         "hot_glookups_s,validated_cpu_control,validated_cpu_cold,"
         "validated_cpu_hot,zero_mismatch_gpu_control,"
         "zero_mismatch_gpu_cold,zero_mismatch_gpu_hot,validation\n"
      << std::fixed << std::setprecision(6);
  for (const auto &row : rows)
    csv << row.path << ',' << row.spec.aliases << ',' << row.spec.pitch_mib
        << ',' << row.pitch_bytes << ',' << row.virtual_span_bytes << ','
        << double(row.virtual_span_bytes) / (1024.0 * 1024.0) << ','
        << row.virtual_base_address << ',' << row.mapped_slots << ','
        << row.physical_backing_bytes << ','
        << row.accessed_physical_bytes << ','
        << double(row.virtual_span_bytes) / row.physical_backing_bytes << ','
        << row.warps << ','
        << double(row.warps) / properties.multiProcessorCount << ','
        << row.threads << ',' << row.samples << ',' << row.control_cycles.p50
        << ',' << row.cold_cycles.p50 << ',' << row.hot_cycles.p50 << ','
        << row.cold_net_cycles_per_lookup << ','
        << row.hot_net_cycles_per_lookup << ',' << row.cold_us.p50 << ','
        << row.hot_us.p50 << ',' << row.cold_glookups_s << ','
        << row.hot_glookups_s << ',' << row.control_validation.cpu_payloads
        << ',' << row.cold_validation.cpu_payloads << ','
        << row.hot_validation.cpu_payloads << ','
        << row.control_validation.zero_mismatch_payloads << ','
        << row.cold_validation.zero_mismatch_payloads << ','
        << row.hot_validation.zero_mismatch_payloads << ','
        << (row.valid ? 1 : 0) << '\n';
}

}  // namespace

int main(int argc, char **argv) {
  try {
    const Args args = parse_args(argc, argv);
    cu_check(cuInit(0), "cuInit");
    cuda_check(cudaSetDevice(0), "cudaSetDevice");
    cuda_check(cudaFree(nullptr), "cuda primary-context initialization");
    CUdevice driver_device{};
    cu_check(cuDeviceGet(&driver_device, 0), "cuDeviceGet");
    int vmm_supported = 0, compression_supported = 0;
    cu_check(cuDeviceGetAttribute(
                 &vmm_supported,
                 CU_DEVICE_ATTRIBUTE_VIRTUAL_MEMORY_MANAGEMENT_SUPPORTED,
                 driver_device),
             "cuDeviceGetAttribute(VMM)");
    cu_check(cuDeviceGetAttribute(
                 &compression_supported,
                 CU_DEVICE_ATTRIBUTE_GENERIC_COMPRESSION_SUPPORTED,
                 driver_device),
             "cuDeviceGetAttribute(compression)");
    if (!vmm_supported)
      throw std::runtime_error("CUDA VMM is not supported on device 0");
    CUmemAllocationProp allocation_properties{};
    allocation_properties.type = CU_MEM_ALLOCATION_TYPE_PINNED;
    allocation_properties.requestedHandleTypes = CU_MEM_HANDLE_TYPE_NONE;
    allocation_properties.location.type = CU_MEM_LOCATION_TYPE_DEVICE;
    allocation_properties.location.id = driver_device;
    std::size_t granularity = 0;
    cu_check(cuMemGetAllocationGranularity(
                 &granularity, &allocation_properties,
                 CU_MEM_ALLOC_GRANULARITY_MINIMUM),
             "cuMemGetAllocationGranularity");
    cudaDeviceProp properties{};
    cuda_check(cudaGetDeviceProperties(&properties, 0),
               "cudaGetDeviceProperties");
    int global_occupancy = 0, texture_occupancy = 0;
    cuda_check(cudaOccupancyMaxActiveBlocksPerMultiprocessor(
                   &global_occupancy, lookup_vmm_aliases<kSteps, false>,
                   kWarpSize, 0),
               "cudaOccupancy(global)");
    cuda_check(cudaOccupancyMaxActiveBlocksPerMultiprocessor(
                   &texture_occupancy, lookup_vmm_aliases<kSteps, true>,
                   kWarpSize, 0),
               "cudaOccupancy(texture)");
    const std::size_t eviction_entries =
        args.eviction_mib * 1024ull * 1024ull / sizeof(std::uint32_t);
    std::uint32_t *eviction = nullptr, *eviction_sink = nullptr;
    cuda_check(cudaMalloc(&eviction, eviction_entries * sizeof(std::uint32_t)),
               "cudaMalloc(eviction)");
    cuda_check(cudaMemset(eviction, 0x5a,
                          eviction_entries * sizeof(std::uint32_t)),
               "cudaMemset(eviction)");
    const int eviction_blocks = properties.multiProcessorCount * 8;
    cuda_check(cudaMalloc(&eviction_sink,
                          std::size_t(eviction_blocks) * 256 *
                              sizeof(std::uint32_t)),
               "cudaMalloc(eviction sink)");
    const cudaTextureObject_t eviction_texture = make_linear_texture(
        eviction, eviction_entries * sizeof(std::uint32_t));
    std::vector<Row> rows;
    std::vector<CaseSpec> ordered_cases = args.cases;
    if (args.order == 1)
      std::reverse(ordered_cases.begin(), ordered_cases.end());
    const std::vector<Mode> modes =
        args.order == 0 ? std::vector<Mode>{Mode::Global, Mode::Texture}
                        : std::vector<Mode>{Mode::Texture, Mode::Global};
    std::cout << "CUDA VMM-alias LUT device: " << properties.name << " sm_"
              << properties.major << properties.minor
              << " L2=" << properties.l2CacheSize
              << " bytes VMM-granularity=" << granularity
              << " occupancy=" << global_occupancy << '/'
              << texture_occupancy << '\n';
    for (const auto spec : ordered_cases) {
      const std::uint64_t pitch_bytes =
          std::uint64_t(spec.pitch_mib) * 1024ull * 1024ull;
      if (pitch_bytes % granularity != 0)
        throw std::runtime_error("pitch is not a multiple of VMM granularity");
      const std::uint64_t virtual_span_bytes =
          std::uint64_t(spec.aliases - 1) * pitch_bytes + granularity;
      if (virtual_span_bytes / sizeof(std::uint32_t) >
          std::size_t(properties.maxTexture1DLinear))
        throw std::runtime_error("VMM virtual span exceeds linear-texture limit");
      AliasedVmmMapping mapping(driver_device, granularity,
                                std::size_t(virtual_span_bytes));
      const std::uint32_t physical_words =
          std::uint32_t(granularity / sizeof(std::uint32_t));
      initialize_physical_words<<<int((physical_words + 255u) / 256u), 256>>>(
          mapping.data(), physical_words);
      cuda_check(cudaGetLastError(), "VMM physical initialization launch");
      cuda_check(cudaDeviceSynchronize(), "VMM physical initialization sync");
      const cudaTextureObject_t texture =
          make_linear_texture(mapping.data(), mapping.mapped_bytes());
      for (const int warps : args.warps)
        for (const Mode mode : modes) {
          rows.push_back(run_case(args, mapping, texture, mode, spec, warps,
                                  eviction, eviction_texture, eviction_entries,
                                  eviction_sink, eviction_blocks));
          const auto &row = rows.back();
          std::cout << "aliases=" << std::setw(3) << spec.aliases
                    << " pitch=" << std::setw(2) << spec.pitch_mib
                    << " MiB span=" << std::setw(3)
                    << row.virtual_span_bytes / (1024 * 1024)
                    << " MiB base=0x" << std::hex << row.virtual_base_address
                    << std::dec << " warps=" << std::setw(4) << warps << ' '
                    << std::setw(14) << row.path << " hot=" << std::fixed
                    << std::setprecision(3) << row.hot_glookups_s
                    << " Glookup/s valid=" << (row.valid ? "yes" : "NO")
                    << '\n';
        }
      cudaDestroyTextureObject(texture);
    }
    write_results(args, properties, granularity, compression_supported,
                  global_occupancy, texture_occupancy, rows);
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
