#include <cuda_runtime.h>

#include "klb/seedchain.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <string_view>
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

struct alignas(16) GpuPoint {
    float x;
    float y;
    float z;
    std::uint32_t lineage;
};
static_assert(sizeof(GpuPoint) == 16u);

struct alignas(16) CompactEvent {
    std::uint32_t point_index;
    std::uint32_t lineage;
    float sdf;
    float guard;
};
static_assert(sizeof(CompactEvent) == 16u);

struct QueryParams {
    klb::Vec3 center;
    klb::Vec3 axis;
    float support_radius;
    float cone_cos;
    float sphere_radius;
    float epsilon;
    std::uint32_t route_filter;
};

struct Options {
    std::filesystem::path input;
    std::filesystem::path csv;
    std::uint32_t frame = std::numeric_limits<std::uint32_t>::max();
    std::uint32_t repeats = 30u;
    std::uint32_t warmup = 5u;
    std::uint32_t verify = 4096u;
    std::uint32_t verify_events = 1048576u;
    int device = 0;
    std::string mode = "all";
    float support_ratio = 1.10f;
    float cone_cos = -0.35f;
    float sphere_ratio = 0.62f;
    float epsilon_ratio = 0.035f;
    std::uint32_t route_filter = 2u;
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
        if (ptr_ != nullptr) (void)cudaFree(ptr_);
    }
    DeviceBuffer(const DeviceBuffer&) = delete;
    DeviceBuffer& operator=(const DeviceBuffer&) = delete;
    DeviceBuffer(DeviceBuffer&& other) noexcept : ptr_(other.ptr_), count_(other.count_) {
        other.ptr_ = nullptr;
        other.count_ = 0u;
    }
    DeviceBuffer& operator=(DeviceBuffer&& other) noexcept {
        if (this != &other) {
            if (ptr_ != nullptr) (void)cudaFree(ptr_);
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
        if (host.size() != count_) throw std::runtime_error("device upload size mismatch");
        if (!host.empty()) {
            CUDA_CHECK(cudaMemcpy(ptr_, host.data(), host.size() * sizeof(T), cudaMemcpyHostToDevice));
        }
    }
    std::vector<T> download() const {
        return download_prefix(count_);
    }
    std::vector<T> download_prefix(std::size_t count) const {
        if (count > count_) throw std::runtime_error("device download prefix exceeds allocation");
        std::vector<T> host(count);
        if (count != 0u) {
            CUDA_CHECK(cudaMemcpy(host.data(), ptr_, count * sizeof(T), cudaMemcpyDeviceToHost));
        }
        return host;
    }
private:
    T* ptr_{};
    std::size_t count_{};
};

KLB_HD KLB_INLINE bool evaluate_event(
    const klb::Vec3& position,
    std::uint32_t route,
    const QueryParams& params,
    float& sdf,
    float& guard) {
    const klb::Vec3 local = position - params.center;
    const float radius = klb::length(local);
    const float axis_dot = klb::dot(local, params.axis);
    const float cosine = radius > 1.0e-20f ? axis_dot / radius : 1.0f;
    const bool support = radius <= params.support_radius && cosine >= params.cone_cos;
    const bool compatible = params.route_filter > 1u || route == params.route_filter;
    sdf = radius - params.sphere_radius;
    guard = ::fabsf(sdf) - params.epsilon;
    return support && compatible && guard <= 0.0f;
}

__global__ void reconstruct_kernel(
    klb::SeedChainView view,
    std::uint32_t frame,
    GpuPoint* output,
    std::uint32_t point_count) {
    const std::uint32_t point = blockIdx.x * blockDim.x + threadIdx.x;
    if (point < point_count) {
        const klb::SeedDecodedRecord record = klb::reconstruct_seedchain_point(view, frame, point);
        const std::uint32_t packed_meta = (record.lineage & 0xfffffffeu) | record.route;
        output[point] = {record.position.x, record.position.y, record.position.z, packed_meta};
    }
}

__global__ void query_seed_kernel(
    klb::SeedChainView view,
    std::uint32_t frame,
    QueryParams params,
    CompactEvent* events,
    std::uint32_t* event_count,
    std::uint32_t point_count) {
    const std::uint32_t point = blockIdx.x * blockDim.x + threadIdx.x;
    if (point < point_count) {
        const klb::SeedDecodedRecord record = klb::reconstruct_seedchain_point(view, frame, point);
        float sdf = 0.0f;
        float guard = 0.0f;
        if (evaluate_event(record.position, record.route, params, sdf, guard)) {
            const std::uint32_t slot = atomicAdd(event_count, 1u);
            events[slot] = {point, (record.lineage & 0xfffffffeu) | record.route, sdf, guard};
        }
    }
}

__global__ void query_dense_kernel(
    const GpuPoint* points,
    QueryParams params,
    CompactEvent* events,
    std::uint32_t* event_count,
    std::uint32_t point_count) {
    const std::uint32_t point = blockIdx.x * blockDim.x + threadIdx.x;
    if (point < point_count) {
        const GpuPoint packed = points[point];
        const klb::Vec3 position{packed.x, packed.y, packed.z};
        const std::uint32_t route = packed.lineage & 1u;
        float sdf = 0.0f;
        float guard = 0.0f;
        if (evaluate_event(position, route, params, sdf, guard)) {
            const std::uint32_t slot = atomicAdd(event_count, 1u);
            events[slot] = {point, packed.lineage, sdf, guard};
        }
    }
}

struct Result {
    std::string mode;
    double milliseconds{};
    double candidates_per_second{};
    std::uint32_t verified_events{};
    double event_yield{};
};

template <typename Launch>
double time_cuda(Launch&& launch, std::uint32_t warmup, std::uint32_t repeats) {
    for (std::uint32_t i = 0u; i < warmup; ++i) launch();
    CUDA_CHECK(cudaGetLastError());
    CUDA_CHECK(cudaDeviceSynchronize());

    cudaEvent_t start{};
    cudaEvent_t stop{};
    CUDA_CHECK(cudaEventCreate(&start));
    CUDA_CHECK(cudaEventCreate(&stop));
    CUDA_CHECK(cudaEventRecord(start));
    for (std::uint32_t i = 0u; i < repeats; ++i) launch();
    CUDA_CHECK(cudaEventRecord(stop));
    CUDA_CHECK(cudaEventSynchronize(stop));
    float elapsed_ms = 0.0f;
    CUDA_CHECK(cudaEventElapsedTime(&elapsed_ms, start, stop));
    CUDA_CHECK(cudaEventDestroy(start));
    CUDA_CHECK(cudaEventDestroy(stop));
    CUDA_CHECK(cudaGetLastError());
    return static_cast<double>(elapsed_ms) / static_cast<double>(repeats);
}

[[noreturn]] void usage(const char* executable, int exit_code) {
    std::ostream& out = exit_code == 0 ? std::cout : std::cerr;
    out << "KLB SeedChain CUDA deployment benchmark\n\n"
        << "Usage:\n"
        << "  " << executable << " <input.klsc> [options]\n\n"
        << "Options:\n"
        << "  --frame N            Target frame; default is the final frame\n"
        << "  --mode NAME          all, decode, seed, or dense (default all)\n"
        << "  --repeats N          Timed launches per mode (default 30)\n"
        << "  --warmup N           Untimed launches per mode (default 5)\n"
        << "  --verify N           CPU/GPU point comparisons (default 4096; 0 disables)\n"
        << "  --verify-events N    Exact compressed/dense event-set comparison up to N events\n"
        << "                       (default 1048576; 0 disables)\n"
        << "  --device N           CUDA device ordinal (default 0)\n"
        << "  --support-ratio X    Cone support radius / base radius (default 1.10)\n"
        << "  --cone-cos X         Cone cosine threshold (default -0.35)\n"
        << "  --sphere-ratio X     SDF sphere radius / base radius (default 0.62)\n"
        << "  --epsilon-ratio X    Guard half-width / base radius (default 0.035)\n"
        << "  --route VALUE        any, 0, or 1 (default any)\n"
        << "  --csv PATH           Append benchmark rows to CSV\n";
    std::exit(exit_code);
}

std::uint64_t parse_u64(std::string_view text, const char* name) {
    std::size_t consumed = 0u;
    const std::uint64_t value = std::stoull(std::string(text), &consumed, 0);
    if (consumed != text.size()) throw std::invalid_argument(std::string(name) + " must be an integer");
    return value;
}

float parse_float(std::string_view text, const char* name) {
    std::size_t consumed = 0u;
    const float value = std::stof(std::string(text), &consumed);
    if (consumed != text.size() || !std::isfinite(value)) {
        throw std::invalid_argument(std::string(name) + " must be finite");
    }
    return value;
}

Options parse_options(int argc, char** argv) {
    if (argc < 2) usage(argv[0], 2);
    if (std::string_view(argv[1]) == "--help" || std::string_view(argv[1]) == "-h") usage(argv[0], 0);
    Options options{};
    options.input = argv[1];
    for (int i = 2; i < argc; ++i) {
        const std::string arg = argv[i];
        auto value = [&]() -> const char* {
            if (++i >= argc) throw std::invalid_argument(arg + " requires a value");
            return argv[i];
        };
        if (arg == "--frame") {
            options.frame = static_cast<std::uint32_t>(parse_u64(value(), "--frame"));
        } else if (arg == "--mode") {
            options.mode = value();
        } else if (arg == "--repeats") {
            options.repeats = static_cast<std::uint32_t>(parse_u64(value(), "--repeats"));
        } else if (arg == "--warmup") {
            options.warmup = static_cast<std::uint32_t>(parse_u64(value(), "--warmup"));
        } else if (arg == "--verify") {
            options.verify = static_cast<std::uint32_t>(parse_u64(value(), "--verify"));
        } else if (arg == "--verify-events") {
            options.verify_events = static_cast<std::uint32_t>(parse_u64(value(), "--verify-events"));
        } else if (arg == "--device") {
            options.device = static_cast<int>(parse_u64(value(), "--device"));
        } else if (arg == "--support-ratio") {
            options.support_ratio = parse_float(value(), "--support-ratio");
        } else if (arg == "--cone-cos") {
            options.cone_cos = parse_float(value(), "--cone-cos");
        } else if (arg == "--sphere-ratio") {
            options.sphere_ratio = parse_float(value(), "--sphere-ratio");
        } else if (arg == "--epsilon-ratio") {
            options.epsilon_ratio = parse_float(value(), "--epsilon-ratio");
        } else if (arg == "--route") {
            const std::string route = value();
            if (route == "any") options.route_filter = 2u;
            else if (route == "0") options.route_filter = 0u;
            else if (route == "1") options.route_filter = 1u;
            else throw std::invalid_argument("--route must be any, 0, or 1");
        } else if (arg == "--csv") {
            options.csv = value();
        } else if (arg == "--help" || arg == "-h") {
            usage(argv[0], 0);
        } else {
            throw std::invalid_argument("unknown option: " + arg);
        }
    }
    if (options.repeats == 0u) throw std::invalid_argument("--repeats must be non-zero");
    if (options.mode != "all" && options.mode != "decode" &&
        options.mode != "seed" && options.mode != "dense") {
        throw std::invalid_argument("--mode must be all, decode, seed, or dense");
    }
    if (!(options.support_ratio > 0.0f) || !(options.sphere_ratio > 0.0f) ||
        options.epsilon_ratio < 0.0f || options.cone_cos < -1.0f || options.cone_cos > 1.0f) {
        throw std::invalid_argument(
            "support/sphere ratios must be positive, epsilon non-negative, and cone cosine in [-1,1]");
    }
    return options;
}

struct EventComparison {
    bool performed{};
    std::size_t compared{};
    double maximum_sdf_difference{};
    double maximum_guard_difference{};
};

EventComparison compare_event_sets(
    std::vector<CompactEvent> compressed,
    std::vector<CompactEvent> dense,
    double scalar_tolerance) {
    if (compressed.size() != dense.size()) {
        throw std::runtime_error("compressed and dense event-set sizes differ");
    }
    auto order = [](const CompactEvent& a, const CompactEvent& b) {
        return a.point_index < b.point_index;
    };
    std::sort(compressed.begin(), compressed.end(), order);
    std::sort(dense.begin(), dense.end(), order);

    EventComparison result{};
    result.performed = true;
    result.compared = compressed.size();
    for (std::size_t i = 0u; i < compressed.size(); ++i) {
        const CompactEvent& a = compressed[i];
        const CompactEvent& b = dense[i];
        if (a.point_index != b.point_index || a.lineage != b.lineage) {
            throw std::runtime_error(
                "compressed and dense event sets differ in point identity or lineage");
        }
        const double sdf_difference = std::abs(static_cast<double>(a.sdf) - b.sdf);
        const double guard_difference = std::abs(static_cast<double>(a.guard) - b.guard);
        result.maximum_sdf_difference = std::max(result.maximum_sdf_difference, sdf_difference);
        result.maximum_guard_difference = std::max(result.maximum_guard_difference, guard_difference);
        if (sdf_difference > scalar_tolerance || guard_difference > scalar_tolerance) {
            throw std::runtime_error(
                "compressed and dense event scalar values exceed the comparison tolerance");
        }
    }
    return result;
}

void write_csv(
    const std::filesystem::path& path,
    const cudaDeviceProp& device,
    std::uint32_t frame,
    const klb::SeedChainStats& stats,
    const Result& result) {
    const bool exists = std::filesystem::exists(path);
    std::ofstream output(path, std::ios::app);
    if (!output) throw std::runtime_error("failed to open CSV output: " + path.string());
    if (!exists) {
        output << "device,compute_capability,frame,mode,milliseconds,candidates_per_second,verified_events,event_yield,container_bytes,dense_float3_sequence_bytes,ratio_vs_float3\n";
    }
    output << '"' << device.name << '"' << ','
           << device.major << '.' << device.minor << ','
           << frame << ',' << result.mode << ','
           << std::setprecision(12) << result.milliseconds << ','
           << result.candidates_per_second << ','
           << result.verified_events << ','
           << result.event_yield << ','
           << stats.file_bytes << ','
           << stats.dense_float3_sequence_bytes << ','
           << stats.ratio_vs_float3_sequence << '\n';
}

} // namespace

int main(int argc, char** argv) {
    try {
        const Options options = parse_options(argc, argv);
        const klb::SeedChainData chain = klb::load_seedchain(options.input);
        const klb::SeedChainStats stats = klb::inspect_seedchain(
            chain, std::filesystem::file_size(options.input));
        const std::uint32_t frame = options.frame == std::numeric_limits<std::uint32_t>::max()
            ? static_cast<std::uint32_t>(chain.nodes.size() - 1u)
            : options.frame;
        if (frame >= chain.nodes.size()) throw std::out_of_range("target frame is out of range");
        if (chain.header.base_header.record_count > std::numeric_limits<std::uint32_t>::max()) {
            throw std::runtime_error("CUDA benchmark currently requires at most UINT32_MAX points");
        }
        const std::uint32_t point_count = static_cast<std::uint32_t>(chain.header.base_header.record_count);

        CUDA_CHECK(cudaSetDevice(options.device));
        cudaDeviceProp device{};
        CUDA_CHECK(cudaGetDeviceProperties(&device, options.device));
        int driver_version = 0;
        int runtime_version = 0;
        CUDA_CHECK(cudaDriverGetVersion(&driver_version));
        CUDA_CHECK(cudaRuntimeGetVersion(&runtime_version));

        DeviceBuffer<std::uint32_t> d_words(chain.base_words.size());
        DeviceBuffer<klb::SeedChainNodeDisk> d_nodes(chain.nodes.size());
        DeviceBuffer<klb::SeedNoveltyDisk> d_novelties(chain.novelties.size());
        DeviceBuffer<GpuPoint> d_points(point_count);
        DeviceBuffer<CompactEvent> d_events(point_count);
        DeviceBuffer<std::uint32_t> d_event_count(1u);
        d_words.upload(chain.base_words);
        d_nodes.upload(chain.nodes);
        d_novelties.upload(chain.novelties);

        klb::SeedChainView view = klb::make_seedchain_view(chain);
        view.base_words = d_words.get();
        view.nodes = d_nodes.get();
        view.novelties = d_novelties.get();

        const float radius = chain.header.base_header.radius_scale;
        QueryParams query{};
        query.center = {
            chain.header.base_header.center[0],
            chain.header.base_header.center[1],
            chain.header.base_header.center[2],
        };
        query.axis = {0.0f, 1.0f, 0.0f};
        query.support_radius = radius * options.support_ratio;
        query.cone_cos = options.cone_cos;
        query.sphere_radius = radius * options.sphere_ratio;
        query.epsilon = radius * options.epsilon_ratio;
        query.route_filter = options.route_filter;

        constexpr std::uint32_t kBlock = 256u;
        const std::uint32_t blocks = (point_count + kBlock - 1u) / kBlock;
        const dim3 grid(blocks);
        const dim3 block(kBlock);

        std::cout << std::fixed << std::setprecision(3)
                  << "Device                     : " << device.name << '\n'
                  << "Compute capability         : " << device.major << '.' << device.minor << '\n'
                  << "CUDA driver/runtime        : " << driver_version << " / " << runtime_version << '\n'
                  << "Global memory              : " << (device.totalGlobalMem / (1024.0 * 1024.0)) << " MiB\n"
                  << "L2 cache reported          : " << (device.l2CacheSize / 1024.0) << " KiB\n"
                  << "SM count                   : " << device.multiProcessorCount << '\n'
                  << "Memory bus width           : " << device.memoryBusWidth << " bits\n"
                  << "Input container            : " << stats.file_bytes << " bytes\n"
                  << "Dense float3 full sequence : " << stats.dense_float3_sequence_bytes << " bytes\n"
                  << "Sequence compression       : " << stats.ratio_vs_float3_sequence << "x\n"
                  << "Target frame               : " << frame << " / " << (chain.nodes.size() - 1u) << '\n'
                  << "Points                     : " << point_count << '\n'
                  << "Linked depth               : " << chain.nodes[frame].depth_from_checkpoint << '\n';

        std::vector<Result> results;
        std::vector<CompactEvent> compressed_events_for_compare;
        bool compressed_events_captured = false;
        EventComparison event_comparison{};
        bool event_comparison_skipped_for_limit = false;

        auto run_decode = [&]() {
            Result result{};
            result.mode = "decode";
            result.milliseconds = time_cuda([&]() {
                reconstruct_kernel<<<grid, block>>>(view, frame, d_points.get(), point_count);
            }, options.warmup, options.repeats);
            result.candidates_per_second =
                static_cast<double>(point_count) / (result.milliseconds * 1.0e-3);
            results.push_back(result);
        };

        auto run_query_seed = [&]() {
            Result result{};
            result.mode = "query_seedchain";
            result.milliseconds = time_cuda([&]() {
                CUDA_CHECK(cudaMemsetAsync(d_event_count.get(), 0, sizeof(std::uint32_t)));
                query_seed_kernel<<<grid, block>>>(
                    view, frame, query, d_events.get(), d_event_count.get(), point_count);
            }, options.warmup, options.repeats);
            CUDA_CHECK(cudaMemset(d_event_count.get(), 0, sizeof(std::uint32_t)));
            query_seed_kernel<<<grid, block>>>(
                view, frame, query, d_events.get(), d_event_count.get(), point_count);
            CUDA_CHECK(cudaDeviceSynchronize());
            CUDA_CHECK(cudaMemcpy(&result.verified_events, d_event_count.get(),
                                  sizeof(std::uint32_t), cudaMemcpyDeviceToHost));
            result.candidates_per_second =
                static_cast<double>(point_count) / (result.milliseconds * 1.0e-3);
            result.event_yield = static_cast<double>(result.verified_events) / point_count;
            if (options.mode == "all" && options.verify_events != 0u) {
                if (result.verified_events <= options.verify_events) {
                    compressed_events_for_compare = d_events.download_prefix(result.verified_events);
                    compressed_events_captured = true;
                } else {
                    event_comparison_skipped_for_limit = true;
                }
            }
            results.push_back(result);
        };

        auto ensure_dense = [&]() {
            reconstruct_kernel<<<grid, block>>>(view, frame, d_points.get(), point_count);
            CUDA_CHECK(cudaGetLastError());
            CUDA_CHECK(cudaDeviceSynchronize());
        };

        auto run_query_dense = [&]() {
            ensure_dense();
            Result result{};
            result.mode = "query_dense_frame";
            result.milliseconds = time_cuda([&]() {
                CUDA_CHECK(cudaMemsetAsync(d_event_count.get(), 0, sizeof(std::uint32_t)));
                query_dense_kernel<<<grid, block>>>(
                    d_points.get(), query, d_events.get(), d_event_count.get(), point_count);
            }, options.warmup, options.repeats);
            CUDA_CHECK(cudaMemset(d_event_count.get(), 0, sizeof(std::uint32_t)));
            query_dense_kernel<<<grid, block>>>(
                d_points.get(), query, d_events.get(), d_event_count.get(), point_count);
            CUDA_CHECK(cudaDeviceSynchronize());
            CUDA_CHECK(cudaMemcpy(&result.verified_events, d_event_count.get(),
                                  sizeof(std::uint32_t), cudaMemcpyDeviceToHost));
            result.candidates_per_second =
                static_cast<double>(point_count) / (result.milliseconds * 1.0e-3);
            result.event_yield = static_cast<double>(result.verified_events) / point_count;
            if (compressed_events_captured) {
                if (result.verified_events <= options.verify_events) {
                    const std::vector<CompactEvent> dense_events =
                        d_events.download_prefix(result.verified_events);
                    const double tolerance = std::max(1.0e-6, static_cast<double>(radius) * 1.0e-5);
                    event_comparison = compare_event_sets(
                        compressed_events_for_compare, dense_events, tolerance);
                } else {
                    event_comparison_skipped_for_limit = true;
                }
            }
            results.push_back(result);
        };

        if (options.mode == "all" || options.mode == "decode") run_decode();
        if (options.mode == "all" || options.mode == "seed") run_query_seed();
        if (options.mode == "all" || options.mode == "dense") run_query_dense();

        if (options.verify != 0u) {
            ensure_dense();
            const std::vector<GpuPoint> gpu_points = d_points.download();
            const std::vector<klb::Vec3> cpu_points = klb::reconstruct_seedchain_frame(chain, frame);
            const std::uint32_t verify_count = std::min<std::uint32_t>(options.verify, point_count);
            long double squared_sum = 0.0L;
            double max_error = 0.0;
            std::uint32_t lineage_mismatches = 0u;
            const klb::SeedChainView host_view = klb::make_seedchain_view(chain);
            for (std::uint32_t i = 0u; i < verify_count; ++i) {
                const klb::Vec3 gpu{gpu_points[i].x, gpu_points[i].y, gpu_points[i].z};
                const double error = klb::length(gpu - cpu_points[i]);
                squared_sum += error * error;
                max_error = std::max(max_error, error);
                const klb::SeedDecodedRecord expected =
                    klb::reconstruct_seedchain_point(host_view, frame, i);
                const std::uint32_t expected_meta =
                    (expected.lineage & 0xfffffffeu) | expected.route;
                if (gpu_points[i].lineage != expected_meta) ++lineage_mismatches;
            }
            const double rms = std::sqrt(static_cast<double>(squared_sum / verify_count));
            std::cout << "CPU/GPU verification       : " << verify_count << " points\n"
                      << "CPU/GPU RMS difference     : " << rms << '\n'
                      << "CPU/GPU maximum difference : " << max_error << '\n'
                      << "Lineage mismatches         : " << lineage_mismatches << '\n';
            if (lineage_mismatches != 0u || max_error > std::max(1.0e-5, radius * 2.0e-4)) {
                throw std::runtime_error("CPU/GPU reconstruction verification failed");
            }
        }

        std::cout << std::setprecision(6);
        for (const Result& result : results) {
            std::cout << "\nMode                       : " << result.mode << '\n'
                      << "Device time                : " << result.milliseconds << " ms\n"
                      << "Candidate rate             : "
                      << (result.candidates_per_second / 1.0e6) << " M/s\n";
            if (result.mode != "decode") {
                std::cout << "Verified events            : " << result.verified_events << '\n'
                          << "Event yield                : " << (100.0 * result.event_yield) << "%\n"
                          << "Compact output bytes       : "
                          << static_cast<std::uint64_t>(result.verified_events) * sizeof(CompactEvent) << '\n';
            }
            if (!options.csv.empty()) write_csv(options.csv, device, frame, stats, result);
        }

        const auto seed_it = std::find_if(results.begin(), results.end(), [](const Result& r) {
            return r.mode == "query_seedchain";
        });
        const auto dense_it = std::find_if(results.begin(), results.end(), [](const Result& r) {
            return r.mode == "query_dense_frame";
        });
        if (seed_it != results.end() && dense_it != results.end()) {
            std::cout << "\nSeed decode/query penalty  : "
                      << (seed_it->milliseconds / dense_it->milliseconds)
                      << "x vs materialized frame\n"
                      << "Compressed/dense event match: "
                      << (seed_it->verified_events == dense_it->verified_events ? "yes" : "NO") << '\n';
            if (seed_it->verified_events != dense_it->verified_events) {
                throw std::runtime_error(
                    "compressed and dense query modes produced different verified-event counts");
            }
            if (event_comparison.performed) {
                std::cout << "Exact event-set comparison  : " << event_comparison.compared
                          << " events matched\n"
                          << "Maximum SDF difference      : "
                          << event_comparison.maximum_sdf_difference << '\n'
                          << "Maximum guard difference    : "
                          << event_comparison.maximum_guard_difference << '\n';
            } else if (options.verify_events == 0u) {
                std::cout << "Exact event-set comparison  : disabled\n";
            } else if (event_comparison_skipped_for_limit) {
                std::cout << "Exact event-set comparison  : skipped; event count exceeds --verify-events "
                          << options.verify_events << '\n';
            }
        }
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "error: " << error.what() << '\n';
        return 1;
    }
}
