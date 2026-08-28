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
#include <vector>

namespace fs = std::filesystem;

namespace {

#ifndef UGTS_GROUP_TRIM
#define UGTS_GROUP_TRIM 0
#endif

static_assert(UGTS_GROUP_TRIM >= 0, "UGTS_GROUP_TRIM must be non-negative");

constexpr std::uint32_t kSteps = 512;
constexpr std::uint32_t kWarpSize = 32;
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

enum class Pattern : int {
  Zero = 0,
  Periodic = 1,
  Entropy = 2,
  Ones = 3,
  ConstOne = 4,
  Sparse4096 = 5,
  Sparse1024 = 6,
  Sparse256 = 7,
  Sparse64 = 8,
  Sparse16 = 9,
  Binary = 10,
  Quaternary = 11,
  Nibble = 12,
  Sparse2048 = 13,
  Sparse512 = 14,
  Sparse128 = 15,
  Sparse640 = 16,
  Sparse768 = 17,
  Sparse896 = 18,
  Sparse544 = 19,
  Sparse576 = 20,
  Sparse608 = 21,
  Sparse672 = 22,
  Sparse704 = 23,
  Sparse736 = 24,
  UgtsG24Floor70 = 25
};
enum class Path : int { Global = 0, Texture = 1 };
enum class Compression : int { None = 0, Generic = 1 };

const char *pattern_name(Pattern pattern) {
  switch (pattern) {
  case Pattern::Zero:
    return "zero6";
  case Pattern::Periodic:
    return "periodic6";
  case Pattern::Entropy:
    return "entropy6";
  case Pattern::Ones:
    return "ones6";
  case Pattern::ConstOne:
    return "const1";
  case Pattern::Sparse4096:
    return "sparse1_4096";
  case Pattern::Sparse1024:
    return "sparse1_1024";
  case Pattern::Sparse256:
    return "sparse1_256";
  case Pattern::Sparse64:
    return "sparse1_64";
  case Pattern::Sparse16:
    return "sparse1_16";
  case Pattern::Binary:
    return "binary1";
  case Pattern::Quaternary:
    return "quaternary2";
  case Pattern::Nibble:
    return "nibble4";
  case Pattern::Sparse2048:
    return "sparse1_2048";
  case Pattern::Sparse512:
    return "sparse1_512";
  case Pattern::Sparse128:
    return "sparse1_128";
  case Pattern::Sparse640:
    return "sparse1_640";
  case Pattern::Sparse768:
    return "sparse1_768";
  case Pattern::Sparse896:
    return "sparse1_896";
  case Pattern::Sparse544:
    return "sparse1_544";
  case Pattern::Sparse576:
    return "sparse1_576";
  case Pattern::Sparse608:
    return "sparse1_608";
  case Pattern::Sparse672:
    return "sparse1_672";
  case Pattern::Sparse704:
    return "sparse1_704";
  case Pattern::Sparse736:
    return "sparse1_736";
  case Pattern::UgtsG24Floor70:
    return "ugts_g24_floor70_code8";
  }
  return "invalid";
}

const char *path_name(Path path) {
  return path == Path::Global ? "global_cg" : "texture_object";
}

const char *compression_name(Compression compression) {
  return compression == Compression::None ? "non_compressible"
                                           : "generic_compressible";
}

struct Args {
  fs::path out_dir = "cuda_vmm_compression_lut_out";
  std::vector<std::uint32_t> size_mib = {4, 28, 32, 36, 38,
                                         40, 48, 64, 96, 128};
  std::vector<int> warps = {184, 1104};
  std::vector<Pattern> patterns = {Pattern::Zero, Pattern::Periodic,
                                   Pattern::Entropy};
  std::vector<Path> paths = {Path::Global, Path::Texture};
  std::size_t eviction_mib = 256;
  int warmup = 2;
  int samples = 10;
  int order = 0;
};

std::vector<Path> parse_paths(const std::string &text) {
  std::stringstream stream(text);
  std::string part;
  std::vector<Path> result;
  while (std::getline(stream, part, ',')) {
    if (part == "global_cg")
      result.push_back(Path::Global);
    else if (part == "texture_object")
      result.push_back(Path::Texture);
    else if (!part.empty())
      throw std::runtime_error("unknown path: " + part);
  }
  if (result.empty())
    throw std::runtime_error("empty path list");
  return result;
}

std::vector<Pattern> parse_patterns(const std::string &text) {
  std::stringstream stream(text);
  std::string part;
  std::vector<Pattern> result;
  while (std::getline(stream, part, ',')) {
    if (part == "zero6")
      result.push_back(Pattern::Zero);
    else if (part == "periodic6")
      result.push_back(Pattern::Periodic);
    else if (part == "entropy6")
      result.push_back(Pattern::Entropy);
    else if (part == "ones6")
      result.push_back(Pattern::Ones);
    else if (part == "const1")
      result.push_back(Pattern::ConstOne);
    else if (part == "sparse1_4096")
      result.push_back(Pattern::Sparse4096);
    else if (part == "sparse1_1024")
      result.push_back(Pattern::Sparse1024);
    else if (part == "sparse1_256")
      result.push_back(Pattern::Sparse256);
    else if (part == "sparse1_64")
      result.push_back(Pattern::Sparse64);
    else if (part == "sparse1_16")
      result.push_back(Pattern::Sparse16);
    else if (part == "binary1")
      result.push_back(Pattern::Binary);
    else if (part == "quaternary2")
      result.push_back(Pattern::Quaternary);
    else if (part == "nibble4")
      result.push_back(Pattern::Nibble);
    else if (part == "sparse1_2048")
      result.push_back(Pattern::Sparse2048);
    else if (part == "sparse1_512")
      result.push_back(Pattern::Sparse512);
    else if (part == "sparse1_128")
      result.push_back(Pattern::Sparse128);
    else if (part == "sparse1_640")
      result.push_back(Pattern::Sparse640);
    else if (part == "sparse1_768")
      result.push_back(Pattern::Sparse768);
    else if (part == "sparse1_896")
      result.push_back(Pattern::Sparse896);
    else if (part == "sparse1_544")
      result.push_back(Pattern::Sparse544);
    else if (part == "sparse1_576")
      result.push_back(Pattern::Sparse576);
    else if (part == "sparse1_608")
      result.push_back(Pattern::Sparse608);
    else if (part == "sparse1_672")
      result.push_back(Pattern::Sparse672);
    else if (part == "sparse1_704")
      result.push_back(Pattern::Sparse704);
    else if (part == "sparse1_736")
      result.push_back(Pattern::Sparse736);
    else if (part == "ugts_g24_floor70_code8")
      result.push_back(Pattern::UgtsG24Floor70);
    else if (!part.empty())
      throw std::runtime_error("unknown pattern: " + part);
  }
  if (result.empty())
    throw std::runtime_error("empty pattern list");
  return result;
}

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
    else if (arg == "--size-mib")
      args.size_mib = parse_list<std::uint32_t>(value("--size-mib"));
    else if (arg == "--warps")
      args.warps = parse_list<int>(value("--warps"));
    else if (arg == "--patterns")
      args.patterns = parse_patterns(value("--patterns"));
    else if (arg == "--paths")
      args.paths = parse_paths(value("--paths"));
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
    throw std::runtime_error("invalid compression-LUT run parameters");
  for (const auto size : args.size_mib)
    if (size < 2 || size > 512 || (size & 1u) != 0u)
      throw std::runtime_error("size MiB must be even and in [2, 512]");
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

__host__ __device__ __forceinline__ std::uint32_t code_for(
    int pattern, std::uint32_t index) {
  if (pattern == int(Pattern::Zero))
    return 0u;
  if (pattern == int(Pattern::Ones))
    return 63u;
  if (pattern == int(Pattern::Periodic))
    return index & 63u;
  if (pattern == int(Pattern::ConstOne))
    return 1u;
  // The package's current G24 producer stores confidence_floor=0.70.  After
  // binary16 rounding and the declared 0..0.125 log-distance quantization,
  // that value is code 8 for every generated candidate.
  if (pattern == int(Pattern::UgtsG24Floor70))
    return 8u;
  if (pattern == int(Pattern::Sparse4096))
    return (index & 4095u) == 0u ? 1u : 0u;
  if (pattern == int(Pattern::Sparse2048))
    return (index & 2047u) == 0u ? 1u : 0u;
  if (pattern == int(Pattern::Sparse1024))
    return (index & 1023u) == 0u ? 1u : 0u;
  if (pattern == int(Pattern::Sparse512))
    return (index & 511u) == 0u ? 1u : 0u;
  if (pattern == int(Pattern::Sparse256))
    return (index & 255u) == 0u ? 1u : 0u;
  if (pattern == int(Pattern::Sparse128))
    return (index & 127u) == 0u ? 1u : 0u;
  if (pattern == int(Pattern::Sparse640))
    return index % 640u == 0u ? 1u : 0u;
  if (pattern == int(Pattern::Sparse768))
    return index % 768u == 0u ? 1u : 0u;
  if (pattern == int(Pattern::Sparse896))
    return index % 896u == 0u ? 1u : 0u;
  if (pattern == int(Pattern::Sparse544))
    return index % 544u == 0u ? 1u : 0u;
  if (pattern == int(Pattern::Sparse576))
    return index % 576u == 0u ? 1u : 0u;
  if (pattern == int(Pattern::Sparse608))
    return index % 608u == 0u ? 1u : 0u;
  if (pattern == int(Pattern::Sparse672))
    return index % 672u == 0u ? 1u : 0u;
  if (pattern == int(Pattern::Sparse704))
    return index % 704u == 0u ? 1u : 0u;
  if (pattern == int(Pattern::Sparse736))
    return index % 736u == 0u ? 1u : 0u;
  if (pattern == int(Pattern::Sparse64))
    return (index & 63u) == 0u ? 1u : 0u;
  if (pattern == int(Pattern::Sparse16))
    return (index & 15u) == 0u ? 1u : 0u;
  const std::uint32_t mixed = mix32(index ^ 0x6a09e667u);
  if (pattern == int(Pattern::Binary))
    return mixed & 1u;
  if (pattern == int(Pattern::Quaternary))
    return mixed & 3u;
  if (pattern == int(Pattern::Nibble))
    return mixed & 15u;
  return mixed & 63u;
}

__device__ __forceinline__ std::uint32_t load_global_l2(
    const std::uint32_t *address) {
  std::uint32_t value;
  asm volatile("ld.global.cg.u32 %0, [%1];" : "=r"(value) : "l"(address));
  return value;
}

__global__ void initialize_packed6(std::uint32_t *words,
                                   std::uint32_t groups, int pattern) {
  const std::uint32_t group = threadIdx.x + blockIdx.x * blockDim.x;
  if (group >= groups)
    return;
  const std::uint32_t first = group * 16u;
  std::uint32_t output[3] = {0u, 0u, 0u};
#pragma unroll
  for (std::uint32_t i = 0; i < 16u; ++i) {
    const std::uint32_t value = code_for(pattern, first + i);
    const std::uint32_t bit = i * 6u;
    const std::uint32_t word = bit >> 5u;
    const std::uint32_t shift = bit & 31u;
    output[word] |= value << shift;
    if (shift > 26u)
      output[word + 1u] |= value >> (32u - shift);
  }
  words[group * 3u] = output[0];
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

template <bool Texture>
__device__ __forceinline__ std::uint32_t decode_packed6(
    const std::uint32_t *global_words, cudaTextureObject_t texture,
    std::uint32_t index) {
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

template <int Steps, bool Texture>
__global__ void lookup_packed6(const std::uint32_t *global_words,
                               cudaTextureObject_t texture,
                               std::uint32_t entries, int pattern,
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
        decode_packed6<Texture>(global_words, texture, index);
    mismatches += std::uint32_t(code != code_for(pattern, index));
  }
  const unsigned long long finished = clock64();
  asm volatile("" ::: "memory");
  results[output] =
      {started, finished, state, mismatches, seed, std::uint32_t(Steps)};
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

class VmmAllocation {
 public:
  VmmAllocation(CUdevice device, std::size_t bytes, Compression compression)
      : bytes_(bytes), requested_compression_(int(compression)) {
    CUmemAllocationProp properties{};
    properties.type = CU_MEM_ALLOCATION_TYPE_PINNED;
    properties.requestedHandleTypes = CU_MEM_HANDLE_TYPE_NONE;
    properties.location.type = CU_MEM_LOCATION_TYPE_DEVICE;
    properties.location.id = device;
    properties.allocFlags.compressionType =
        compression == Compression::None ? CU_MEM_ALLOCATION_COMP_NONE
                                         : CU_MEM_ALLOCATION_COMP_GENERIC;
    std::size_t granularity = 0;
    cu_check(cuMemGetAllocationGranularity(
                 &granularity, &properties, CU_MEM_ALLOC_GRANULARITY_MINIMUM),
             "cuMemGetAllocationGranularity");
    if (bytes_ == 0 || bytes_ % granularity != 0)
      throw std::runtime_error("VMM size is not granularity aligned");
    cu_check(cuMemAddressReserve(&base_, bytes_, granularity, 0, 0),
             "cuMemAddressReserve");
    try {
      cu_check(cuMemCreate(&handle_, bytes_, &properties, 0), "cuMemCreate");
      CUmemAllocationProp effective{};
      cu_check(cuMemGetAllocationPropertiesFromHandle(&effective, handle_),
               "cuMemGetAllocationPropertiesFromHandle");
      effective_compression_ = effective.allocFlags.compressionType;
      cu_check(cuMemMap(base_, bytes_, 0, handle_, 0), "cuMemMap");
      mapped_ = true;
      CUmemAccessDesc access{};
      access.location.type = CU_MEM_LOCATION_TYPE_DEVICE;
      access.location.id = device;
      access.flags = CU_MEM_ACCESS_FLAGS_PROT_READWRITE;
      cu_check(cuMemSetAccess(base_, bytes_, &access, 1), "cuMemSetAccess");
    } catch (...) {
      cleanup();
      throw;
    }
  }
  VmmAllocation(const VmmAllocation &) = delete;
  VmmAllocation &operator=(const VmmAllocation &) = delete;
  ~VmmAllocation() { cleanup(); }
  std::uint32_t *data() const {
    return reinterpret_cast<std::uint32_t *>(base_);
  }
  std::uint64_t base_address() const { return std::uint64_t(base_); }
  std::size_t bytes() const { return bytes_; }
  int requested_compression() const { return requested_compression_; }
  int effective_compression() const { return effective_compression_; }

 private:
  void cleanup() noexcept {
    if (mapped_)
      cuMemUnmap(base_, bytes_);
    mapped_ = false;
    if (handle_ != 0)
      cuMemRelease(handle_);
    handle_ = 0;
    if (base_ != 0)
      cuMemAddressFree(base_, bytes_);
    base_ = 0;
  }
  CUdeviceptr base_ = 0;
  CUmemGenericAllocationHandle handle_ = 0;
  std::size_t bytes_ = 0;
  int requested_compression_ = -1;
  int effective_compression_ = -1;
  bool mapped_ = false;
};

std::uint32_t advance_lcg(std::uint32_t state, std::uint32_t steps) {
  std::uint32_t acc_mul = 1u, acc_add = 0u;
  std::uint32_t cur_mul = kLcgMul, cur_add = kLcgAdd;
  while (steps) {
    if (steps & 1u) {
      acc_add = cur_mul * acc_add + cur_add;
      acc_mul = cur_mul * acc_mul;
    }
    cur_add = cur_mul * cur_add + cur_add;
    cur_mul *= cur_mul;
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
    throw std::runtime_error("empty measurement distribution");
  return {*std::min_element(values.begin(), values.end()),
          std::accumulate(values.begin(), values.end(), 0.0) /
              double(values.size()),
          percentile(values, 0.50), percentile(values, 0.95),
          percentile(values, 0.99), *std::max_element(values.begin(), values.end())};
}

struct Validation {
  std::size_t valid_payloads = 0;
  std::uint64_t mismatch_total = 0;
};

void validate_results(const std::vector<LookupResult> &results,
                      std::uint32_t sample_seed, std::uint32_t steps,
                      std::vector<double> &cycles, Validation &validation) {
  for (std::size_t output = 0; output < results.size(); ++output) {
    const std::uint32_t warp = std::uint32_t(output / kWarpSize);
    const std::uint32_t lane = std::uint32_t(output % kWarpSize);
    const std::uint32_t seed = initial_state(lane, warp, sample_seed);
    const auto &actual = results[output];
    validation.mismatch_total += actual.mismatch_count;
    if (actual.final_state == advance_lcg(seed, steps) &&
        actual.mismatch_count == 0u && actual.seed == seed &&
        actual.steps == steps && actual.finished >= actual.started)
      ++validation.valid_payloads;
    cycles.push_back(double(actual.finished - actual.started));
  }
}

template <int Steps>
void launch(Path path, int warps, const std::uint32_t *words,
            cudaTextureObject_t texture, std::uint32_t entries,
            Pattern pattern, std::uint32_t seed, LookupResult *output) {
  if (path == Path::Global)
    lookup_packed6<Steps, false><<<warps, kWarpSize>>>(
        words, 0, entries, int(pattern), seed, output);
  else
    lookup_packed6<Steps, true><<<warps, kWarpSize>>>(
        words, texture, entries, int(pattern), seed, output);
}

struct Accumulator {
  std::vector<double> control_cycles, cold_cycles, hot_cycles, cold_us, hot_us;
  Validation control_validation, cold_validation, hot_validation;
};

struct Row {
  std::string path, pattern, compression;
  std::uint32_t size_mib = 0, entries = 0, groups = 0;
  std::uint64_t allocation_bytes = 0, table_bytes = 0, base_address = 0;
  int requested_compression = -1, effective_compression = -1;
  int warps = 0, threads = 0, samples = 0;
  Validation control_validation, cold_validation, hot_validation;
  Distribution control_cycles, cold_cycles, hot_cycles, cold_us, hot_us;
  double hot_net_cycles_per_lookup = 0, cold_net_cycles_per_lookup = 0;
  double hot_glookups_s = 0, cold_glookups_s = 0;
  bool valid = false;
};

Row make_row(const Args &args, const VmmAllocation &allocation,
             Compression compression, Pattern pattern, Path path,
             std::uint32_t size_mib, std::uint32_t groups, int warps,
             const Accumulator &data) {
  Row row{};
  row.path = path_name(path);
  row.pattern = pattern_name(pattern);
  row.compression = compression_name(compression);
  row.size_mib = size_mib;
  row.groups = groups;
  row.entries = groups * 16u;
  row.allocation_bytes = allocation.bytes();
  row.table_bytes = std::uint64_t(groups) * 12u;
  row.base_address = allocation.base_address();
  row.requested_compression = allocation.requested_compression();
  row.effective_compression = allocation.effective_compression();
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
  const std::size_t expected = std::size_t(args.samples) * row.threads;
  row.valid = row.control_validation.valid_payloads == expected &&
              row.cold_validation.valid_payloads == expected &&
              row.hot_validation.valid_payloads == expected &&
              ((compression == Compression::None &&
                row.effective_compression == CU_MEM_ALLOCATION_COMP_NONE) ||
               (compression == Compression::Generic &&
                row.effective_compression == CU_MEM_ALLOCATION_COMP_GENERIC));
  return row;
}

std::vector<Row> run_compression_pair(
    const Args &args, const VmmAllocation &non_compressible,
    cudaTextureObject_t non_compressible_texture,
    const VmmAllocation &generic_compressible,
    cudaTextureObject_t generic_compressible_texture, Pattern pattern,
    Path path, std::uint32_t size_mib, std::uint32_t groups, int warps,
    const std::uint32_t *eviction, cudaTextureObject_t eviction_texture,
    std::size_t eviction_entries, std::uint32_t *eviction_sink,
    int eviction_blocks) {
  const int threads = warps * int(kWarpSize);
  LookupResult *device_control = nullptr, *device_cold = nullptr,
               *device_hot = nullptr;
  cuda_check(cudaMalloc(&device_control,
                        std::size_t(threads) * sizeof(LookupResult)),
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
  Accumulator data[2];
  const std::uint32_t entries = groups * 16u;
  for (int sample = -args.warmup; sample < args.samples; ++sample) {
    const std::uint32_t sample_seed =
        mix32(std::uint32_t(sample + args.warmup + 1) * 0xc2b2ae35u);
    const int first = (sample + args.warmup + args.order) & 1;
    for (int position = 0; position < 2; ++position) {
      const int compression_index = first ^ position;
      const VmmAllocation &allocation =
          compression_index == 0 ? non_compressible : generic_compressible;
      const cudaTextureObject_t texture =
          compression_index == 0 ? non_compressible_texture
                                 : generic_compressible_texture;
      launch<0>(path, warps, allocation.data(), texture, entries, pattern,
                sample_seed, device_control);
      if (path == Path::Global)
        evict_global<<<eviction_blocks, 256>>>(eviction, eviction_entries,
                                               eviction_sink);
      else
        evict_texture<<<eviction_blocks, 256>>>(
            eviction_texture, eviction_entries, eviction_sink);
      cuda_check(cudaEventRecord(cold_start), "cudaEventRecord(cold start)");
      launch<kSteps>(path, warps, allocation.data(), texture, entries, pattern,
                     sample_seed, device_cold);
      cuda_check(cudaEventRecord(cold_end), "cudaEventRecord(cold end)");
      cuda_check(cudaEventRecord(hot_start), "cudaEventRecord(hot start)");
      launch<kSteps>(path, warps, allocation.data(), texture, entries, pattern,
                     sample_seed, device_hot);
      cuda_check(cudaEventRecord(hot_end), "cudaEventRecord(hot end)");
      cuda_check(cudaGetLastError(), "compression-LUT lookup launch");
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
        validate_results(control, sample_seed, 0,
                         data[compression_index].control_cycles,
                         data[compression_index].control_validation);
        validate_results(cold, sample_seed, kSteps,
                         data[compression_index].cold_cycles,
                         data[compression_index].cold_validation);
        validate_results(hot, sample_seed, kSteps,
                         data[compression_index].hot_cycles,
                         data[compression_index].hot_validation);
        data[compression_index].cold_us.push_back(double(cold_ms) * 1000.0);
        data[compression_index].hot_us.push_back(double(hot_ms) * 1000.0);
      }
    }
  }
  cudaEventDestroy(cold_start);
  cudaEventDestroy(cold_end);
  cudaEventDestroy(hot_start);
  cudaEventDestroy(hot_end);
  cudaFree(device_control);
  cudaFree(device_cold);
  cudaFree(device_hot);
  return {
      make_row(args, non_compressible, Compression::None, pattern, path,
               size_mib, groups, warps, data[0]),
      make_row(args, generic_compressible, Compression::Generic, pattern, path,
               size_mib, groups, warps, data[1])};
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
  std::ofstream json(args.out_dir / "cuda_vmm_compression_lut_results.json");
  json << std::fixed << std::setprecision(6);
  json << "{\n  \"schema\": \"UGTS-CUDA-VMM-COMPRESSION-LUT-1.0\",\n"
          "  \"device\": {\"name\": \""
       << properties.name << "\", \"compute_capability\": \""
       << properties.major << '.' << properties.minor << "\", \"l2_bytes\": "
       << properties.l2CacheSize << ", \"multiprocessors\": "
       << properties.multiProcessorCount
       << ", \"generic_compression_supported\": "
       << (compression_supported ? "true" : "false")
       << ", \"occupancy_blocks_per_sm\": {\"global_cg\": "
       << global_occupancy << ", \"texture_object\": " << texture_occupancy
       << "}},\n  \"run_parameters\": {\"lookups_per_thread\": " << kSteps
       << ", \"vmm_granularity_bytes\": " << granularity
       << ", \"eviction_bytes\": " << args.eviction_mib * 1024 * 1024
       << ", \"warmup_sets\": " << args.warmup
       << ", \"measured_sets\": " << args.samples
       << ", \"order\": " << args.order
       << ", \"paired_paths_share_mapping\": true"
       << ", \"compression_modes_alternate_per_sample\": true},\n"
          "  \"semantics\": \"Dense packed6 code tables compare explicit non-compressible and driver-confirmed generic-compressible VMM allocations. zero6, periodic6, entropy6, optional all-one ones6, and the exact uniform code-8 stream produced by the current G24 confidence_floor=0.70 generator are checked inside every timed kernel.\",\n"
          "  \"scope_note\": \"Throughput and capacity curves can reveal a workload-level benefit or lack thereof, but do not expose achieved hardware compression ratio, compressed L2 bytes, DRAM traffic or compression counters.\",\n"
          "  \"results\": [\n";
  for (std::size_t index = 0; index < rows.size(); ++index) {
    const auto &row = rows[index];
    json << "    {\"path\": \"" << row.path << "\", \"pattern\": \""
         << row.pattern << "\", \"compression\": \"" << row.compression
         << "\", \"requested_compression\": " << row.requested_compression
         << ", \"effective_compression\": " << row.effective_compression
         << ", \"size_mib\": " << row.size_mib
         << ", \"allocation_bytes\": " << row.allocation_bytes
         << ", \"table_bytes\": " << row.table_bytes
         << ", \"groups\": " << row.groups << ", \"entries\": "
         << row.entries << ", \"bytes_per_code\": "
         << double(row.table_bytes) / row.entries
         << ", \"base_address\": " << row.base_address
         << ", \"warps\": " << row.warps << ", \"threads\": "
         << row.threads << ", \"samples\": " << row.samples
         << ", \"control_cycles\": ";
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
         << row.hot_glookups_s
         << ", \"validated_payloads\": {\"control\": "
         << row.control_validation.valid_payloads << ", \"cold\": "
         << row.cold_validation.valid_payloads << ", \"hot\": "
         << row.hot_validation.valid_payloads
         << "}, \"mismatch_totals\": {\"control\": "
         << row.control_validation.mismatch_total << ", \"cold\": "
         << row.cold_validation.mismatch_total << ", \"hot\": "
         << row.hot_validation.mismatch_total << "}, \"validation\": "
         << (row.valid ? "true" : "false") << '}'
         << (index + 1 == rows.size() ? "\n" : ",\n");
  }
  json << "  ]\n}\n";

  std::ofstream csv(args.out_dir / "cuda_vmm_compression_lut_results.csv");
  csv << "path,pattern,compression,requested_compression,"
         "effective_compression,size_mib,allocation_bytes,table_bytes,groups,"
         "entries,bytes_per_code,base_address,warps,threads,samples,"
         "control_p50_cycles,cold_p50_cycles,hot_p50_cycles,"
         "cold_net_cycles_per_lookup,hot_net_cycles_per_lookup,cold_p50_us,"
         "hot_p50_us,cold_glookups_s,hot_glookups_s,validated_control,"
         "validated_cold,validated_hot,mismatches_control,mismatches_cold,"
         "mismatches_hot,validation\n"
      << std::fixed << std::setprecision(6);
  for (const auto &row : rows)
    csv << row.path << ',' << row.pattern << ',' << row.compression << ','
        << row.requested_compression << ',' << row.effective_compression << ','
        << row.size_mib << ',' << row.allocation_bytes << ',' << row.table_bytes
        << ',' << row.groups << ',' << row.entries << ','
        << double(row.table_bytes) / row.entries << ',' << row.base_address
        << ',' << row.warps << ',' << row.threads << ',' << row.samples << ','
        << row.control_cycles.p50 << ',' << row.cold_cycles.p50 << ','
        << row.hot_cycles.p50 << ',' << row.cold_net_cycles_per_lookup << ','
        << row.hot_net_cycles_per_lookup << ',' << row.cold_us.p50 << ','
        << row.hot_us.p50 << ',' << row.cold_glookups_s << ','
        << row.hot_glookups_s << ','
        << row.control_validation.valid_payloads << ','
        << row.cold_validation.valid_payloads << ','
        << row.hot_validation.valid_payloads << ','
        << row.control_validation.mismatch_total << ','
        << row.cold_validation.mismatch_total << ','
        << row.hot_validation.mismatch_total << ','
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
    int compression_supported = 0;
    cu_check(cuDeviceGetAttribute(
                 &compression_supported,
                 CU_DEVICE_ATTRIBUTE_GENERIC_COMPRESSION_SUPPORTED,
                 driver_device),
             "cuDeviceGetAttribute(compression)");
    if (!compression_supported)
      throw std::runtime_error("generic compression is not supported");
    CUmemAllocationProp probe{};
    probe.type = CU_MEM_ALLOCATION_TYPE_PINNED;
    probe.location.type = CU_MEM_LOCATION_TYPE_DEVICE;
    probe.location.id = driver_device;
    std::size_t granularity = 0;
    cu_check(cuMemGetAllocationGranularity(
                 &granularity, &probe, CU_MEM_ALLOC_GRANULARITY_MINIMUM),
             "cuMemGetAllocationGranularity");
    cudaDeviceProp properties{};
    cuda_check(cudaGetDeviceProperties(&properties, 0),
               "cudaGetDeviceProperties");
    int global_occupancy = 0, texture_occupancy = 0;
    cuda_check(cudaOccupancyMaxActiveBlocksPerMultiprocessor(
                   &global_occupancy, lookup_packed6<kSteps, false>, kWarpSize,
                   0),
               "cudaOccupancy(global)");
    cuda_check(cudaOccupancyMaxActiveBlocksPerMultiprocessor(
                   &texture_occupancy, lookup_packed6<kSteps, true>, kWarpSize,
                   0),
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
    std::vector<std::uint32_t> sizes = args.size_mib;
    std::vector<Pattern> patterns = args.patterns;
    std::vector<Path> paths = args.paths;
    if (args.order == 1) {
      std::reverse(sizes.begin(), sizes.end());
      std::reverse(patterns.begin(), patterns.end());
      std::reverse(paths.begin(), paths.end());
    }
    std::vector<Row> rows;
    std::cout << "CUDA VMM compression-LUT device: " << properties.name
              << " sm_" << properties.major << properties.minor
              << " L2=" << properties.l2CacheSize
              << " VMM-granularity=" << granularity
              << " occupancy=" << global_occupancy << '/'
              << texture_occupancy << '\n';
    for (const auto size_mib : sizes) {
      const std::size_t allocation_bytes =
          std::size_t(size_mib) * 1024ull * 1024ull;
      if (allocation_bytes % granularity != 0)
        throw std::runtime_error("size is not VMM-granularity aligned");
      const std::uint64_t untrimmed_groups = allocation_bytes / 12u;
      if (untrimmed_groups <= std::uint64_t(UGTS_GROUP_TRIM))
        throw std::runtime_error("packed group trim exceeds table capacity");
      const std::uint32_t groups = std::uint32_t(
          untrimmed_groups - std::uint64_t(UGTS_GROUP_TRIM));
      if (std::uint64_t(groups) * 16u > UINT32_MAX)
        throw std::runtime_error("packed entry count exceeds u32");
      for (const auto pattern : patterns) {
          VmmAllocation non_compressible(
              driver_device, allocation_bytes, Compression::None);
          VmmAllocation generic_compressible(
              driver_device, allocation_bytes, Compression::Generic);
          initialize_packed6<<<int((groups + 255u) / 256u), 256>>>(
              non_compressible.data(), groups, int(pattern));
          initialize_packed6<<<int((groups + 255u) / 256u), 256>>>(
              generic_compressible.data(), groups, int(pattern));
          cuda_check(cudaGetLastError(), "packed6 initialization launch");
          cuda_check(cudaDeviceSynchronize(), "packed6 initialization sync");
          const cudaTextureObject_t non_compressible_texture =
              make_linear_texture(non_compressible.data(),
                                  std::uint64_t(groups) * 12u);
          const cudaTextureObject_t generic_compressible_texture =
              make_linear_texture(generic_compressible.data(),
                                  std::uint64_t(groups) * 12u);
          for (const int warps : args.warps)
            for (const auto path : paths) {
              const auto pair = run_compression_pair(
                  args, non_compressible, non_compressible_texture,
                  generic_compressible, generic_compressible_texture, pattern,
                  path, size_mib, groups, warps, eviction, eviction_texture,
                  eviction_entries, eviction_sink, eviction_blocks);
              for (const auto &row : pair) {
                rows.push_back(row);
                std::cout << std::setw(3) << size_mib << " MiB "
                          << std::setw(20) << row.compression << ' '
                          << std::setw(9) << row.pattern << " warps="
                          << std::setw(4) << warps << ' ' << std::setw(14)
                          << row.path << " effective="
                          << row.effective_compression << " hot=" << std::fixed
                          << std::setprecision(3) << row.hot_glookups_s
                          << " Glookup/s valid="
                          << (row.valid ? "yes" : "NO") << '\n';
              }
            }
          cudaDestroyTextureObject(non_compressible_texture);
          cudaDestroyTextureObject(generic_compressible_texture);
        }
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
