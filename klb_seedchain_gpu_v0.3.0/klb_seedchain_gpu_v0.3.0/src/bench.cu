#include <cuda_runtime.h>

#include "klb/format.hpp"

#include <algorithm>
#include <bit>
#include <cmath>
#include <cstring>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <numeric>
#include <stdexcept>
#include <string>
#include <string_view>
#include <type_traits>
#include <utility>
#include <vector>

namespace {

#define CUDA_CHECK(call)                                                                                               \
    do {                                                                                                               \
        const cudaError_t klb_cuda_error = (call);                                                                     \
        if (klb_cuda_error != cudaSuccess) {                                                                           \
            throw std::runtime_error(std::string("CUDA error at ") + __FILE__ + ":" + std::to_string(__LINE__) + \
                                     ": " + cudaGetErrorString(klb_cuda_error));                                      \
        }                                                                                                              \
    } while (false)

struct alignas(16) FloatRecord {
    float x;
    float y;
    float z;
    std::uint32_t meta;
};
static_assert(sizeof(FloatRecord) == 16);

struct QueryResult {
    float value;
    std::uint32_t hash;
};
static_assert(sizeof(QueryResult) == 8);

struct BenchParams {
    klb::DecodeParams decode;
    std::uint64_t domain;
    std::uint64_t node_cycle;
    std::uint32_t width;
    std::uint32_t height;
    std::uint32_t depth;
    std::uint32_t seed;
    float time;
    float delta;
    float delta_delta;
};

struct Options {
    std::filesystem::path input;
    std::filesystem::path csv;
    std::uint64_t queries = 1u << 20u;
    std::uint32_t depth = 12u;
    std::uint32_t repeats = 20u;
    std::uint32_t warmup = 3u;
    std::uint32_t verify = 4096u;
    std::uint32_t seed = 0x1234abcdu;
    int device = 0;
    float time = 0.0f;
    float delta = 1.0f / 60.0f;
    float delta_delta = 1.0e-4f;
    std::string mode = "all";
};

template <typename T>
class DeviceBuffer {
public:
    DeviceBuffer() = default;
    explicit DeviceBuffer(std::size_t count) : count_(count) {
        if (count_ != 0u) {
            CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&ptr_), count_ * sizeof(T)));
        }
    }

    ~DeviceBuffer() {
        if (ptr_ != nullptr) {
            (void)cudaFree(ptr_);
        }
    }

    DeviceBuffer(const DeviceBuffer&) = delete;
    DeviceBuffer& operator=(const DeviceBuffer&) = delete;

    DeviceBuffer(DeviceBuffer&& other) noexcept : ptr_(other.ptr_), count_(other.count_) {
        other.ptr_ = nullptr;
        other.count_ = 0u;
    }

    DeviceBuffer& operator=(DeviceBuffer&& other) noexcept {
        if (this != &other) {
            if (ptr_ != nullptr) {
                (void)cudaFree(ptr_);
            }
            ptr_ = other.ptr_;
            count_ = other.count_;
            other.ptr_ = nullptr;
            other.count_ = 0u;
        }
        return *this;
    }

    T* get() { return ptr_; }
    const T* get() const { return ptr_; }
    std::size_t size() const { return count_; }

    void upload(const std::vector<T>& host) {
        if (host.size() != count_) {
            throw std::runtime_error("device upload size mismatch");
        }
        if (!host.empty()) {
            CUDA_CHECK(cudaMemcpy(ptr_, host.data(), host.size() * sizeof(T), cudaMemcpyHostToDevice));
        }
    }

    std::vector<T> download() const {
        std::vector<T> host(count_);
        if (count_ != 0u) {
            CUDA_CHECK(cudaMemcpy(host.data(), ptr_, count_ * sizeof(T), cudaMemcpyDeviceToHost));
        }
        return host;
    }

private:
    T* ptr_{};
    std::size_t count_{};
};

KLB_HD KLB_INLINE std::uint32_t branch_bit(std::uint32_t key, std::uint32_t meta, std::uint32_t level) {
    const std::uint32_t stored_parity = (meta >> 3u) & 1u;
    const std::uint32_t symbol = meta & 7u;
    return (klb::parity32(key ^ meta ^ (level * 0x9e3779b9u)) ^ stored_parity ^ (symbol >> 2u)) & 1u;
}

struct HostU64Loader {
    const std::uint64_t* codes;
    klb::DecodeParams params;

    KLB_HD KLB_INLINE klb::DecodedRecord operator()(std::uint64_t logical) const {
        return klb::decode_record(codes[logical], params);
    }
};

struct DeviceU64Loader {
    const std::uint64_t* codes;
    klb::DecodeParams params;

    KLB_HD KLB_INLINE klb::DecodedRecord operator()(std::uint64_t logical) const {
        return klb::decode_record(codes[logical], params);
    }
};

struct DevicePackedLoader {
    const std::uint32_t* words;
    klb::DecodeParams params;
    std::uint32_t swizzled;

    KLB_HD KLB_INLINE klb::DecodedRecord operator()(std::uint64_t logical) const {
        const std::uint64_t physical = swizzled != 0u ? klb::xor_swizzle_16x16(logical) : logical;
        return klb::decode_record(klb::read_bits37(words, physical), params);
    }
};

struct DeviceFloatLoader {
    const FloatRecord* records;

    KLB_HD KLB_INLINE klb::DecodedRecord operator()(std::uint64_t logical) const {
        const FloatRecord record = records[logical];
        return {{record.x, record.y, record.z}, record.meta};
    }
};

template <typename Loader>
KLB_HD KLB_INLINE QueryResult run_query(std::uint64_t query_id, const Loader& loader, const BenchParams& params) {
    std::uint32_t key = klb::mix32(static_cast<std::uint32_t>(query_id) ^ params.seed) ^
                        klb::mix32(static_cast<std::uint32_t>(query_id >> 32u));
    std::uint64_t node = (static_cast<std::uint64_t>(key) + query_id * 0x9e3779b97f4a7c15ull) % params.node_cycle;

    float phase = params.time + static_cast<float>(key & 0xffffu) * 1.0e-5f;
    float velocity = params.delta;
    float acceleration = params.delta_delta;
    float heading = 0.0f;
    float turtle_x = 0.0f;
    float turtle_z = 0.0f;
    float turtle_step = 1.0f;
    float accumulator = 0.0f;
    std::uint32_t hash = klb::mix32(key ^ 0xa5a5a5a5u);

    for (std::uint32_t level = 0u; level < params.depth; ++level) {
        const std::int32_t x_jitter = static_cast<std::int32_t>((key >> 24u) & 31u) - 16;
        const std::uint32_t seam_shift = (level * 2u) & 30u;
        const std::int32_t seam_jump = static_cast<std::int32_t>((key >> seam_shift) & 3u) - 1;
        const std::int64_t x = static_cast<std::int64_t>(node % params.width) + x_jitter;
        const std::int64_t y = static_cast<std::int64_t>(node / params.width) +
                               static_cast<std::int64_t>(seam_jump) * static_cast<std::int64_t>(params.height);
        const std::uint64_t logical = klb::klein_index(x, y, params.width, params.height);
        const klb::DecodedRecord record = loader(logical);

        const std::uint32_t symbol = record.meta & 7u;
        const std::uint32_t branch = branch_bit(key, record.meta, level);
        const float branch_sign = branch != 0u ? 1.0f : -1.0f;

        const float local_x = record.position.x - params.decode.center_x;
        const float local_y = record.position.y - params.decode.center_y;
        const float local_z = record.position.z - params.decode.center_z;
        const float radial = ::sqrtf(local_x * local_x + local_z * local_z);

        // Infinite cone signed field. phi is swept by time, delta, and delta-delta.
        const float cone_phi = 0.34f + 0.17f * ::sinf(phase + 0.11f * static_cast<float>(symbol) +
                                                     branch_sign * 0.07f);
        const float cone_field = radial * ::cosf(cone_phi) - local_y * ::sinf(cone_phi);

        // A compact turtle-state interpretation of an L-system branch.
        heading += branch_sign * (0.10f + 0.018f * static_cast<float>(symbol));
        turtle_x += ::cosf(heading) * turtle_step;
        turtle_z += ::sinf(heading) * turtle_step;
        turtle_step *= 0.94f;

        accumulator += cone_field * (1.0f + 0.015f * static_cast<float>(symbol)) +
                       0.0005f * (turtle_x * local_x + turtle_z * local_z);
        hash = klb::mix32(hash ^ record.meta ^ (branch << (level & 15u)) ^ static_cast<std::uint32_t>(logical));
        key = klb::mix32(key ^ record.meta ^ (branch * 0x85ebca6bu) ^ level);

        const std::uint64_t child = node * 2u + 1u + branch + static_cast<std::uint64_t>(symbol) * 3u + key;
        node = child % params.node_cycle;
        phase += velocity;
        velocity += acceleration;
    }
    return {accumulator, hash};
}

template <typename Loader>
__global__ void benchmark_kernel(Loader loader, BenchParams params, QueryResult* output, std::uint64_t query_count) {
    const std::uint64_t index = static_cast<std::uint64_t>(blockIdx.x) * blockDim.x + threadIdx.x;
    if (index < query_count) {
        output[index] = run_query(index, loader, params);
    }
}

struct ModeResult {
    std::string mode;
    double milliseconds{};
    double queries_per_second{};
    double nominal_gbps{};
    double upper_load_gbps{};
    double value_sum{};
    std::uint32_t result_hash{};
    std::uint64_t nonfinite{};
    std::vector<QueryResult> outputs;
};

template <typename Loader>
ModeResult run_benchmark(
    const std::string& name,
    Loader loader,
    const BenchParams& params,
    std::uint64_t query_count,
    std::uint32_t warmup,
    std::uint32_t repeats,
    double nominal_bytes_per_record,
    double upper_load_bytes_per_record,
    DeviceBuffer<QueryResult>& output) {
    constexpr std::uint32_t kBlock = 256u;
    const std::uint64_t blocks64 = (query_count + kBlock - 1u) / kBlock;
    if (blocks64 > static_cast<std::uint64_t>(std::numeric_limits<unsigned int>::max())) {
        throw std::runtime_error("query count exceeds one-dimensional CUDA grid limit");
    }
    const dim3 grid(static_cast<unsigned int>(blocks64));
    const dim3 block(kBlock);

    for (std::uint32_t i = 0u; i < warmup; ++i) {
        benchmark_kernel<<<grid, block>>>(loader, params, output.get(), query_count);
    }
    CUDA_CHECK(cudaGetLastError());
    CUDA_CHECK(cudaDeviceSynchronize());

    cudaEvent_t start{};
    cudaEvent_t stop{};
    CUDA_CHECK(cudaEventCreate(&start));
    CUDA_CHECK(cudaEventCreate(&stop));
    CUDA_CHECK(cudaEventRecord(start));
    for (std::uint32_t i = 0u; i < repeats; ++i) {
        benchmark_kernel<<<grid, block>>>(loader, params, output.get(), query_count);
    }
    CUDA_CHECK(cudaEventRecord(stop));
    CUDA_CHECK(cudaEventSynchronize(stop));
    float elapsed_ms = 0.0f;
    CUDA_CHECK(cudaEventElapsedTime(&elapsed_ms, start, stop));
    CUDA_CHECK(cudaEventDestroy(start));
    CUDA_CHECK(cudaEventDestroy(stop));
    CUDA_CHECK(cudaGetLastError());

    ModeResult result{};
    result.mode = name;
    result.milliseconds = static_cast<double>(elapsed_ms) / static_cast<double>(repeats);
    const double seconds = result.milliseconds * 1.0e-3;
    result.queries_per_second = static_cast<double>(query_count) / seconds;
    const double visits = static_cast<double>(query_count) * static_cast<double>(params.depth);
    result.nominal_gbps = visits * nominal_bytes_per_record / seconds / 1.0e9;
    result.upper_load_gbps = visits * upper_load_bytes_per_record / seconds / 1.0e9;
    result.outputs = output.download();

    double sum = 0.0;
    std::uint32_t aggregate_hash = 0x811c9dc5u;
    std::uint64_t nonfinite = 0u;
    for (std::size_t i = 0; i < result.outputs.size(); ++i) {
        const QueryResult& query = result.outputs[i];
        if (std::isfinite(query.value)) {
            sum += static_cast<double>(query.value);
        } else {
            ++nonfinite;
        }
        aggregate_hash = klb::mix32(aggregate_hash ^ query.hash ^ static_cast<std::uint32_t>(i));
    }
    result.value_sum = sum;
    result.result_hash = aggregate_hash;
    result.nonfinite = nonfinite;
    return result;
}

[[noreturn]] void usage(const char* executable, int code) {
    std::ostream& out = code == 0 ? std::cout : std::cerr;
    out << "KLB37 CUDA architecture benchmark\n\n"
        << "Usage:\n"
        << "  " << executable << " <input.klb> [options]\n\n"
        << "Options:\n"
        << "  --queries N       Query count (default 1048576)\n"
        << "  --depth N         Parity/BST traversal depth, 1..32 (default 12)\n"
        << "  --repeats N       Timed launches per mode (default 20)\n"
        << "  --warmup N        Untimed launches per mode (default 3)\n"
        << "  --verify N        CPU-reference queries; 0 disables (default 4096)\n"
        << "  --mode NAME       all, float, u64, or packed (default all)\n"
        << "  --device N        CUDA device ordinal (default 0)\n"
        << "  --seed N          Query seed (default 0x1234abcd)\n"
        << "  --time X          Initial cone sweep time\n"
        << "  --delta X         First time difference (default 1/60)\n"
        << "  --delta-delta X   Second time difference (default 1e-4)\n"
        << "  --csv PATH        Write one result row per mode\n";
    std::exit(code);
}

std::uint64_t parse_u64(std::string_view text, const char* name) {
    std::size_t consumed = 0;
    const std::uint64_t value = std::stoull(std::string(text), &consumed, 0);
    if (consumed != text.size()) {
        throw std::invalid_argument(std::string(name) + " is not an integer");
    }
    return value;
}

float parse_float(std::string_view text, const char* name) {
    std::size_t consumed = 0;
    const float value = std::stof(std::string(text), &consumed);
    if (consumed != text.size() || !std::isfinite(value)) {
        throw std::invalid_argument(std::string(name) + " must be finite");
    }
    return value;
}

Options parse_options(int argc, char** argv) {
    if (argc < 2) {
        usage(argv[0], 2);
    }
    if (std::string_view(argv[1]) == "--help" || std::string_view(argv[1]) == "-h") {
        usage(argv[0], 0);
    }

    Options options{};
    options.input = argv[1];
    for (int i = 2; i < argc; ++i) {
        const std::string arg = argv[i];
        auto require_value = [&]() -> const char* {
            if (++i >= argc) {
                throw std::invalid_argument(arg + " requires a value");
            }
            return argv[i];
        };

        if (arg == "--queries") {
            options.queries = parse_u64(require_value(), "--queries");
        } else if (arg == "--depth") {
            options.depth = static_cast<std::uint32_t>(parse_u64(require_value(), "--depth"));
        } else if (arg == "--repeats") {
            options.repeats = static_cast<std::uint32_t>(parse_u64(require_value(), "--repeats"));
        } else if (arg == "--warmup") {
            options.warmup = static_cast<std::uint32_t>(parse_u64(require_value(), "--warmup"));
        } else if (arg == "--verify") {
            options.verify = static_cast<std::uint32_t>(parse_u64(require_value(), "--verify"));
        } else if (arg == "--mode") {
            options.mode = require_value();
        } else if (arg == "--device") {
            options.device = static_cast<int>(parse_u64(require_value(), "--device"));
        } else if (arg == "--seed") {
            options.seed = static_cast<std::uint32_t>(parse_u64(require_value(), "--seed"));
        } else if (arg == "--time") {
            options.time = parse_float(require_value(), "--time");
        } else if (arg == "--delta") {
            options.delta = parse_float(require_value(), "--delta");
        } else if (arg == "--delta-delta") {
            options.delta_delta = parse_float(require_value(), "--delta-delta");
        } else if (arg == "--csv") {
            options.csv = require_value();
        } else if (arg == "--help" || arg == "-h") {
            usage(argv[0], 0);
        } else {
            throw std::invalid_argument("unknown option: " + arg);
        }
    }

    if (options.queries == 0u) {
        throw std::invalid_argument("--queries must be greater than zero");
    }
    if (options.depth == 0u || options.depth > 32u) {
        throw std::invalid_argument("--depth must be in 1..32");
    }
    if (options.repeats == 0u) {
        throw std::invalid_argument("--repeats must be greater than zero");
    }
    if (options.mode != "all" && options.mode != "float" && options.mode != "u64" && options.mode != "packed") {
        throw std::invalid_argument("--mode must be all, float, u64, or packed");
    }
    return options;
}

bool mode_enabled(const Options& options, std::string_view mode) {
    return options.mode == "all" || options.mode == mode;
}

void print_mode(const ModeResult& result) {
    std::cout << std::left << std::setw(10) << result.mode << std::right
              << "  " << std::fixed << std::setprecision(4) << std::setw(10) << result.milliseconds << " ms"
              << "  " << std::setprecision(3) << std::setw(10) << result.queries_per_second / 1.0e6 << " Mquery/s"
              << "  nominal " << std::setw(9) << result.nominal_gbps << " GB/s"
              << "  load-ceil " << std::setw(9) << result.upper_load_gbps << " GB/s"
              << "  hash 0x" << std::hex << result.result_hash << std::dec;
    if (result.nonfinite != 0u) {
        std::cout << "  NONFINITE=" << result.nonfinite;
    }
    std::cout << '\n';
}

void verify_results(
    const std::vector<std::uint64_t>& logical_codes,
    const BenchParams& params,
    std::uint32_t verify_count,
    const std::vector<ModeResult>& modes) {
    if (verify_count == 0u) {
        std::cout << "Verification disabled.\n";
        return;
    }
    const std::uint64_t count = std::min<std::uint64_t>(verify_count, modes.empty() ? 0u : modes.front().outputs.size());
    HostU64Loader host_loader{logical_codes.data(), params.decode};

    std::uint64_t cpu_hash_mismatches = 0u;
    std::uint64_t cpu_value_mismatches = 0u;
    double max_cpu_error = 0.0;
    std::uint64_t packed_u64_hash_mismatches = 0u;
    std::uint64_t packed_u64_value_mismatches = 0u;

    const ModeResult* u64_mode = nullptr;
    const ModeResult* packed_mode = nullptr;
    for (const ModeResult& mode : modes) {
        if (mode.mode == "u64") {
            u64_mode = &mode;
        } else if (mode.mode == "packed") {
            packed_mode = &mode;
        }
    }

    for (std::uint64_t i = 0; i < count; ++i) {
        const QueryResult cpu = run_query(i, host_loader, params);
        for (const ModeResult& mode : modes) {
            const QueryResult gpu = mode.outputs[static_cast<std::size_t>(i)];
            if (gpu.hash != cpu.hash) {
                ++cpu_hash_mismatches;
            }
            const double error = std::abs(static_cast<double>(gpu.value) - static_cast<double>(cpu.value));
            max_cpu_error = std::max(max_cpu_error, error);
            const double tolerance = 2.5e-3 * (1.0 + std::abs(static_cast<double>(cpu.value)));
            if (!(error <= tolerance)) {
                ++cpu_value_mismatches;
            }
        }
        if (u64_mode != nullptr && packed_mode != nullptr) {
            const QueryResult a = u64_mode->outputs[static_cast<std::size_t>(i)];
            const QueryResult b = packed_mode->outputs[static_cast<std::size_t>(i)];
            if (a.hash != b.hash) {
                ++packed_u64_hash_mismatches;
            }
            std::uint32_t a_bits = 0u;
            std::uint32_t b_bits = 0u;
            std::memcpy(&a_bits, &a.value, sizeof(a_bits));
            std::memcpy(&b_bits, &b.value, sizeof(b_bits));
            if (a_bits != b_bits) {
                ++packed_u64_value_mismatches;
            }
        }
    }

    std::cout << "Verification queries      : " << count << '\n'
              << "CPU/GPU hash mismatches  : " << cpu_hash_mismatches << '\n'
              << "CPU/GPU value mismatches : " << cpu_value_mismatches
              << " (max abs error " << max_cpu_error << ")\n";
    if (u64_mode != nullptr && packed_mode != nullptr) {
        std::cout << "u64/packed hash mismatch : " << packed_u64_hash_mismatches << '\n'
                  << "u64/packed bit mismatch  : " << packed_u64_value_mismatches << '\n';
    }
    if (cpu_hash_mismatches != 0u || cpu_value_mismatches != 0u ||
        packed_u64_hash_mismatches != 0u || packed_u64_value_mismatches != 0u) {
        throw std::runtime_error("verification failed; see mismatch counts above");
    }
}

void write_csv(
    const std::filesystem::path& path,
    const std::string& device_name,
    int major,
    int minor,
    const klb::PackedData& packed,
    const Options& options,
    const std::vector<ModeResult>& results) {
    std::ofstream output(path, std::ios::trunc);
    if (!output) {
        throw std::runtime_error("failed to create CSV file: " + path.string());
    }
    output << "device,compute_capability,dataset,records,padded_records,record_bits,queries,depth,mode,ms,queries_per_second,nominal_gbps,upper_load_gbps,value_sum,result_hash,nonfinite\n";
    for (const ModeResult& result : results) {
        output << '"' << device_name << "\"," << major << '.' << minor << ",\"" << options.input.filename().string()
               << "\"," << packed.header.record_count << ',' << packed.header.padded_count << ','
               << packed.header.record_bits << ',' << options.queries << ',' << options.depth << ",\""
               << result.mode << "\"," << std::setprecision(10) << result.milliseconds << ','
               << result.queries_per_second << ',' << result.nominal_gbps << ',' << result.upper_load_gbps << ','
               << result.value_sum << ',' << result.result_hash << ',' << result.nonfinite << '\n';
    }
}

} // namespace

int main(int argc, char** argv) {
    try {
        const Options options = parse_options(argc, argv);
        CUDA_CHECK(cudaSetDevice(options.device));

        cudaDeviceProp device{};
        CUDA_CHECK(cudaGetDeviceProperties(&device, options.device));
        int driver_version = 0;
        int runtime_version = 0;
        CUDA_CHECK(cudaDriverGetVersion(&driver_version));
        CUDA_CHECK(cudaRuntimeGetVersion(&runtime_version));

        const klb::PackedData packed = klb::load_packed(options.input);
        const std::vector<std::uint64_t> logical_codes = klb::unpack_logical_codes(packed);
        const klb::DecodeParams decode = klb::decode_params_from_header(packed.header);

        if (packed.header.padded_count > static_cast<std::uint64_t>(std::numeric_limits<std::size_t>::max()) ||
            options.queries > static_cast<std::uint64_t>(std::numeric_limits<std::size_t>::max())) {
            throw std::runtime_error("dataset or query count is too large for this host");
        }
        const std::uint64_t height64 = packed.header.padded_count / packed.header.grid_width;
        if (height64 == 0u || height64 > std::numeric_limits<std::uint32_t>::max()) {
            throw std::runtime_error("KLB grid height is unsupported");
        }

        BenchParams params{};
        params.decode = decode;
        params.domain = packed.header.padded_count;
        params.node_cycle = packed.header.padded_count * 4u;
        params.width = packed.header.grid_width;
        params.height = static_cast<std::uint32_t>(height64);
        params.depth = options.depth;
        params.seed = options.seed;
        params.time = options.time;
        params.delta = options.delta;
        params.delta_delta = options.delta_delta;

        std::vector<FloatRecord> float_records;
        if (mode_enabled(options, "float")) {
            float_records.reserve(logical_codes.size());
            for (const std::uint64_t code : logical_codes) {
                const klb::DecodedRecord decoded = klb::decode_record(code, decode);
                float_records.push_back({decoded.position.x, decoded.position.y, decoded.position.z, decoded.meta});
            }
        }

        DeviceBuffer<std::uint32_t> d_words(packed.words.size());
        d_words.upload(packed.words);
        DeviceBuffer<std::uint64_t> d_codes(logical_codes.size());
        d_codes.upload(logical_codes);
        DeviceBuffer<FloatRecord> d_float(float_records.size());
        if (!float_records.empty()) {
            d_float.upload(float_records);
        }
        DeviceBuffer<QueryResult> d_output(static_cast<std::size_t>(options.queries));

        const klb::PackStats stats = klb::inspect_packed(packed, std::filesystem::file_size(options.input));
        std::cout << "Device                    : " << device.name << '\n'
                  << "Compute capability        : " << device.major << '.' << device.minor << '\n'
                  << "CUDA driver/runtime       : " << driver_version << " / " << runtime_version << '\n'
                  << "VRAM                      : " << std::fixed << std::setprecision(2)
                  << static_cast<double>(device.totalGlobalMem) / (1024.0 * 1024.0 * 1024.0) << " GiB\n"
                  << "Dataset records           : " << packed.header.record_count << " (padded "
                  << packed.header.padded_count << ")\n"
                  << "KLB container             : " << stats.file_bytes << " bytes, " << stats.bytes_per_point
                  << " payload bytes/input point\n"
                  << "Quantization RMS/max      : " << packed.header.rms_error << " / " << packed.header.max_error
                  << '\n'
                  << "Queries/depth/repeats     : " << options.queries << " / " << options.depth << " / "
                  << options.repeats << "\n\n";
        if (device.major != 12) {
            std::cout << "Note: this executable was designed for consumer Blackwell sm_120; results on this device remain valid\n"
                         "as an algorithm comparison but are not RTX 5070 Ti Laptop measurements.\n\n";
        }

        std::vector<ModeResult> results;
        if (mode_enabled(options, "float")) {
            DeviceFloatLoader loader{d_float.get()};
            results.push_back(run_benchmark(
                "float", loader, params, options.queries, options.warmup, options.repeats,
                16.0, 16.0, d_output));
            print_mode(results.back());
        }
        if (mode_enabled(options, "u64")) {
            DeviceU64Loader loader{d_codes.get(), decode};
            results.push_back(run_benchmark(
                "u64", loader, params, options.queries, options.warmup, options.repeats,
                8.0, 8.0, d_output));
            print_mode(results.back());
        }
        if (mode_enabled(options, "packed")) {
            DevicePackedLoader loader{
                d_words.get(),
                decode,
                (packed.header.flags & klb::kFlagXorSwizzle) != 0u ? 1u : 0u,
            };
            results.push_back(run_benchmark(
                "packed", loader, params, options.queries, options.warmup, options.repeats,
                static_cast<double>(klb::kRecordBits) / 8.0, 12.0, d_output));
            print_mode(results.back());
        }
        std::cout << '\n';

        verify_results(logical_codes, params, options.verify, results);
        if (!options.csv.empty()) {
            write_csv(options.csv, device.name, device.major, device.minor, packed, options, results);
            std::cout << "Wrote CSV: " << options.csv << '\n';
        }
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "error: " << error.what() << '\n';
        return 1;
    }
}

