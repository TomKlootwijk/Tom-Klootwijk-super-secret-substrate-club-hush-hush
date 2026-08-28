#include <cuda_runtime.h>

#include "klb/orbit.hpp"

#include <algorithm>
#include <cmath>
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

constexpr std::uint32_t kBlockSize = 256u;
constexpr std::uint32_t kMaxSeeds = klb::kOrbitMaxGpuSeeds;
constexpr std::uint32_t kMaxNodes = klb::kOrbitMaxGpuNodes;

__constant__ klb::OrbitSeedDisk g_orbit_seeds[kMaxSeeds];
__constant__ klb::OrbitTimelineNodeDisk g_orbit_nodes[kMaxNodes];

struct alignas(16) DensePosition {
    float x;
    float y;
    float z;
    float radius;
};
static_assert(sizeof(DensePosition) == 16u);

struct alignas(16) CompactOrbitEvent {
    std::uint32_t epoch_index;
    std::uint32_t norad_id;
    float crossing_seconds;
    std::uint32_t lineage_and_type;
};
static_assert(sizeof(CompactOrbitEvent) == 16u);

struct alignas(16) OrbitCounters {
    unsigned long long candidate;
    unsigned long long supported;
    unsigned long long compatible;
    unsigned long long verified;
};
static_assert(sizeof(OrbitCounters) == 32u);

struct alignas(16) DeviceQuery {
    klb::Vec3 station_ecef_km;
    float elevation_mask_sin;

    float crossing_band_sin;
    float maximum_slant_range_km;
    float start_seconds;
    float step_seconds;

    float wrap_seconds;
    float reference_gmst_rad;
    float earth_rotation_rad_s;
    float timeline_start_seconds;

    float timeline_duration_seconds;
    float node_tile_seconds;
    std::uint32_t seed_count;
    std::uint32_t node_count;

    std::uint32_t route_filter;
    std::uint32_t query_kind; // 0 visibility state, 1 guard crossing
    std::uint32_t reserved0;
    std::uint32_t reserved1;
};
static_assert(sizeof(DeviceQuery) == 80u);

struct CandidateEvaluation {
    std::uint32_t active{};
    std::uint32_t supported{};
    std::uint32_t compatible{};
    std::uint32_t verified{};
    std::uint32_t acquisition{};
    float event_seconds{};
};

struct Options {
    std::filesystem::path input;
    std::filesystem::path csv;
    std::string preset = "laptop";
    std::string mode = "all";
    std::string query = "crossing";
    std::uint64_t epochs = 0u;
    float step_seconds = 0.0f;
    float start_seconds = 0.0f;
    float wrap_seconds = -1.0f;
    float latitude_degrees = 52.0f;
    float longitude_degrees = 5.0f;
    float altitude_km = 0.05f;
    float elevation_degrees = 10.0f;
    float crossing_band_degrees = 0.25f;
    float maximum_slant_range_km = 33000.0f;
    std::uint32_t route_filter = 0xffffffffu;
    std::uint32_t warmup = 2u;
    std::uint32_t samples = 9u;
    float minimum_sample_ms = 150.0f;
    std::uint32_t verify_epochs = 4096u;
    std::uint64_t event_capacity = 1000000u;
    bool write_events = false;
    int device = 0;
};

template <typename T>
class DeviceBuffer {
public:
    DeviceBuffer() = default;
    explicit DeviceBuffer(std::size_t count) : count_(count) {
        if (count_ != 0u) CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&pointer_), count_ * sizeof(T)));
    }
    ~DeviceBuffer() {
        if (pointer_ != nullptr) (void)cudaFree(pointer_);
    }
    DeviceBuffer(const DeviceBuffer&) = delete;
    DeviceBuffer& operator=(const DeviceBuffer&) = delete;
    DeviceBuffer(DeviceBuffer&& other) noexcept : pointer_(other.pointer_), count_(other.count_) {
        other.pointer_ = nullptr;
        other.count_ = 0u;
    }
    DeviceBuffer& operator=(DeviceBuffer&& other) noexcept {
        if (this != &other) {
            if (pointer_ != nullptr) (void)cudaFree(pointer_);
            pointer_ = other.pointer_;
            count_ = other.count_;
            other.pointer_ = nullptr;
            other.count_ = 0u;
        }
        return *this;
    }
    T* get() { return pointer_; }
    const T* get() const { return pointer_; }
    std::size_t size() const { return count_; }
    std::vector<T> download_prefix(std::size_t count) const {
        if (count > count_) throw std::runtime_error("device download exceeds allocation");
        std::vector<T> host(count);
        if (count != 0u) {
            CUDA_CHECK(cudaMemcpy(host.data(), pointer_, count * sizeof(T), cudaMemcpyDeviceToHost));
        }
        return host;
    }
private:
    T* pointer_{};
    std::size_t count_{};
};

__device__ __forceinline__ float wrapped_sample_seconds(std::uint64_t epoch_index, const DeviceQuery& query) {
    const float unwrapped = query.start_seconds + static_cast<float>(epoch_index) * query.step_seconds;
    if (query.wrap_seconds > 0.0f) {
        const float local = unwrapped - query.start_seconds;
        return query.start_seconds + (local - ::floorf(local / query.wrap_seconds) * query.wrap_seconds);
    }
    return unwrapped;
}

__device__ __forceinline__ bool crossing_hits_wrap_seam(std::uint64_t epoch_index, const DeviceQuery& query) {
    if (!(query.wrap_seconds > 0.0f)) return false;
    const float local0 = static_cast<float>(epoch_index) * query.step_seconds;
    const float local1 = static_cast<float>(epoch_index + 1u) * query.step_seconds;
    return ::floorf(local0 / query.wrap_seconds) != ::floorf(local1 / query.wrap_seconds);
}

__device__ __forceinline__ std::uint32_t timeline_node_for_seconds(float seconds, const DeviceQuery& query) {
    if (query.node_count == 0u) return 0u;
    float local = seconds - query.timeline_start_seconds;
    if (query.timeline_duration_seconds > 0.0f) {
        local -= ::floorf(local / query.timeline_duration_seconds) * query.timeline_duration_seconds;
    }
    const std::uint32_t estimated = query.node_tile_seconds > 0.0f
        ? static_cast<std::uint32_t>(local / query.node_tile_seconds)
        : 0u;
    return estimated < query.node_count ? estimated : query.node_count - 1u;
}

__device__ __forceinline__ klb::OrbitGroundStation make_device_station(const DeviceQuery& query) {
    return {
        query.station_ecef_km,
        query.elevation_mask_sin,
        query.crossing_band_sin,
        query.maximum_slant_range_km,
        query.route_filter,
    };
}

__device__ __forceinline__ CandidateEvaluation evaluate_seed_candidate(
    std::uint64_t linear_index,
    std::uint64_t total_candidates,
    const DeviceQuery& query,
    CompactOrbitEvent* optional_event) {
    CandidateEvaluation result{};
    if (linear_index >= total_candidates) return result;
    result.active = 1u;
    const std::uint32_t satellite_index = static_cast<std::uint32_t>(linear_index % query.seed_count);
    const std::uint64_t epoch_index = linear_index / query.seed_count;
    const klb::OrbitSeedDisk seed = g_orbit_seeds[satellite_index];
    const klb::OrbitGroundStation station = make_device_station(query);

    if (query.query_kind == 0u) {
        const float seconds = wrapped_sample_seconds(epoch_index, query);
        const klb::Vec3 position = klb::propagate_orbit_seed(seed, seconds);
        const klb::OrbitEvaluation evaluation = klb::evaluate_orbit_visibility(
            position, seconds, station, query.reference_gmst_rad,
            query.earth_rotation_rad_s, seed.route_sector);
        result.supported = evaluation.supported;
        result.compatible = evaluation.supported != 0u && evaluation.compatible != 0u ? 1u : 0u;
        result.verified = result.compatible != 0u && evaluation.guard <= 0.0f ? 1u : 0u;
        result.acquisition = 1u;
        result.event_seconds = seconds;
    } else {
        if (crossing_hits_wrap_seam(epoch_index, query)) return result;
        const float previous_seconds = wrapped_sample_seconds(epoch_index, query);
        const float current_seconds = wrapped_sample_seconds(epoch_index + 1u, query);
        const klb::Vec3 previous_position = klb::propagate_orbit_seed(seed, previous_seconds);
        const klb::Vec3 current_position = klb::propagate_orbit_seed(seed, current_seconds);
        const klb::OrbitEvaluation previous = klb::evaluate_orbit_visibility(
            previous_position, previous_seconds, station, query.reference_gmst_rad,
            query.earth_rotation_rad_s, seed.route_sector);
        const klb::OrbitEvaluation current = klb::evaluate_orbit_visibility(
            current_position, current_seconds, station, query.reference_gmst_rad,
            query.earth_rotation_rad_s, seed.route_sector);
        const klb::OrbitCrossing crossing = klb::evaluate_orbit_crossing(
            previous, current, previous_seconds, current_seconds, query.crossing_band_sin);
        result.supported = previous.supported != 0u || current.supported != 0u ? 1u : 0u;
        result.compatible = result.supported != 0u && previous.compatible != 0u &&
                            current.compatible != 0u ? 1u : 0u;
        result.verified = crossing.verified;
        result.acquisition = crossing.acquisition;
        result.event_seconds = crossing.crossing_seconds;
    }

    if (optional_event != nullptr && result.verified != 0u) {
        const std::uint32_t node_index = timeline_node_for_seconds(result.event_seconds, query);
        const klb::OrbitTimelineNodeDisk node = g_orbit_nodes[node_index];
        const std::uint32_t lineage = klb::orbit_lineage(
            seed, node, epoch_index, result.acquisition != 0u ? 1u : 2u);
        *optional_event = {
            static_cast<std::uint32_t>(epoch_index),
            seed.norad_id,
            result.event_seconds,
            (lineage & 0xfffffffeu) | (result.acquisition & 1u),
        };
    }
    return result;
}

__device__ __forceinline__ CandidateEvaluation evaluate_dense_candidate(
    std::uint64_t linear_index,
    std::uint64_t total_candidates,
    const DensePosition* positions,
    const DeviceQuery& query,
    CompactOrbitEvent* optional_event) {
    CandidateEvaluation result{};
    if (linear_index >= total_candidates) return result;
    result.active = 1u;
    const std::uint32_t satellite_index = static_cast<std::uint32_t>(linear_index % query.seed_count);
    const std::uint64_t epoch_index = linear_index / query.seed_count;
    const klb::OrbitSeedDisk seed = g_orbit_seeds[satellite_index];
    const klb::OrbitGroundStation station = make_device_station(query);

    if (query.query_kind == 0u) {
        const float seconds = wrapped_sample_seconds(epoch_index, query);
        const DensePosition dense = positions[linear_index];
        const klb::Vec3 position{dense.x, dense.y, dense.z};
        const klb::OrbitEvaluation evaluation = klb::evaluate_orbit_visibility(
            position, seconds, station, query.reference_gmst_rad,
            query.earth_rotation_rad_s, seed.route_sector);
        result.supported = evaluation.supported;
        result.compatible = evaluation.supported != 0u && evaluation.compatible != 0u ? 1u : 0u;
        result.verified = result.compatible != 0u && evaluation.guard <= 0.0f ? 1u : 0u;
        result.acquisition = 1u;
        result.event_seconds = seconds;
    } else {
        if (crossing_hits_wrap_seam(epoch_index, query)) return result;
        const std::uint64_t previous_index = epoch_index * query.seed_count + satellite_index;
        const std::uint64_t current_index = (epoch_index + 1u) * query.seed_count + satellite_index;
        const DensePosition previous_dense = positions[previous_index];
        const DensePosition current_dense = positions[current_index];
        const float previous_seconds = wrapped_sample_seconds(epoch_index, query);
        const float current_seconds = wrapped_sample_seconds(epoch_index + 1u, query);
        const klb::OrbitEvaluation previous = klb::evaluate_orbit_visibility(
            {previous_dense.x, previous_dense.y, previous_dense.z}, previous_seconds,
            station, query.reference_gmst_rad, query.earth_rotation_rad_s, seed.route_sector);
        const klb::OrbitEvaluation current = klb::evaluate_orbit_visibility(
            {current_dense.x, current_dense.y, current_dense.z}, current_seconds,
            station, query.reference_gmst_rad, query.earth_rotation_rad_s, seed.route_sector);
        const klb::OrbitCrossing crossing = klb::evaluate_orbit_crossing(
            previous, current, previous_seconds, current_seconds, query.crossing_band_sin);
        result.supported = previous.supported != 0u || current.supported != 0u ? 1u : 0u;
        result.compatible = result.supported != 0u && previous.compatible != 0u &&
                            current.compatible != 0u ? 1u : 0u;
        result.verified = crossing.verified;
        result.acquisition = crossing.acquisition;
        result.event_seconds = crossing.crossing_seconds;
    }

    if (optional_event != nullptr && result.verified != 0u) {
        const std::uint32_t node_index = timeline_node_for_seconds(result.event_seconds, query);
        const klb::OrbitTimelineNodeDisk node = g_orbit_nodes[node_index];
        const std::uint32_t lineage = klb::orbit_lineage(
            seed, node, epoch_index, result.acquisition != 0u ? 1u : 2u);
        *optional_event = {
            static_cast<std::uint32_t>(epoch_index),
            seed.norad_id,
            result.event_seconds,
            (lineage & 0xfffffffeu) | (result.acquisition & 1u),
        };
    }
    return result;
}

__device__ __forceinline__ void commit_block_counters(
    const CandidateEvaluation& evaluation,
    OrbitCounters* counters) {
    constexpr std::uint32_t warps_per_block = kBlockSize / 32u;
    __shared__ std::uint32_t warp_counts[4][warps_per_block];
    const std::uint32_t lane = threadIdx.x & 31u;
    const std::uint32_t warp = threadIdx.x >> 5u;
    const unsigned active_mask = __activemask();
    const unsigned candidate_mask = __ballot_sync(active_mask, evaluation.active != 0u);
    const unsigned support_mask = __ballot_sync(active_mask, evaluation.supported != 0u);
    const unsigned compatible_mask = __ballot_sync(active_mask, evaluation.compatible != 0u);
    const unsigned verified_mask = __ballot_sync(active_mask, evaluation.verified != 0u);
    if (lane == 0u) {
        warp_counts[0][warp] = static_cast<std::uint32_t>(__popc(candidate_mask));
        warp_counts[1][warp] = static_cast<std::uint32_t>(__popc(support_mask));
        warp_counts[2][warp] = static_cast<std::uint32_t>(__popc(compatible_mask));
        warp_counts[3][warp] = static_cast<std::uint32_t>(__popc(verified_mask));
    }
    __syncthreads();
    if (threadIdx.x < 4u) {
        unsigned long long total = 0u;
        for (std::uint32_t index = 0u; index < warps_per_block; ++index) {
            total += warp_counts[threadIdx.x][index];
        }
        auto* words = reinterpret_cast<unsigned long long*>(counters);
        atomicAdd(words + threadIdx.x, total);
    }
}

__device__ __forceinline__ void compact_warp_event(
    const CandidateEvaluation& evaluation,
    const CompactOrbitEvent& event,
    CompactOrbitEvent* events,
    unsigned long long* event_count,
    unsigned long long capacity) {
    const unsigned active_mask = __activemask();
    const unsigned event_mask = __ballot_sync(active_mask, evaluation.verified != 0u);
    if (event_mask == 0u) return;
    const std::uint32_t lane = threadIdx.x & 31u;
    const std::uint32_t leader = static_cast<std::uint32_t>(__ffs(static_cast<int>(event_mask)) - 1);
    const std::uint32_t count = static_cast<std::uint32_t>(__popc(event_mask));
    unsigned long long base = 0u;
    if (lane == leader) base = atomicAdd(event_count, static_cast<unsigned long long>(count));
    base = __shfl_sync(active_mask, base, static_cast<int>(leader));
    if (evaluation.verified != 0u) {
        const unsigned lower_mask = lane == 0u ? 0u : ((1u << lane) - 1u);
        const std::uint32_t prefix = static_cast<std::uint32_t>(__popc(event_mask & lower_mask));
        const unsigned long long slot = base + prefix;
        if (slot < capacity) events[slot] = event;
    }
}

__global__ void materialize_orbits_kernel(
    DensePosition* positions,
    std::uint64_t position_count,
    DeviceQuery query) {
    const std::uint64_t index = static_cast<std::uint64_t>(blockIdx.x) * blockDim.x + threadIdx.x;
    if (index >= position_count) return;
    const std::uint32_t satellite_index = static_cast<std::uint32_t>(index % query.seed_count);
    const std::uint64_t epoch_index = index / query.seed_count;
    const float seconds = wrapped_sample_seconds(epoch_index, query);
    const klb::Vec3 position = klb::propagate_orbit_seed(g_orbit_seeds[satellite_index], seconds);
    positions[index] = {position.x, position.y, position.z, klb::length(position)};
}

__global__ void query_seed_count_kernel(
    std::uint64_t total_candidates,
    DeviceQuery query,
    OrbitCounters* counters) {
    const std::uint64_t index = static_cast<std::uint64_t>(blockIdx.x) * blockDim.x + threadIdx.x;
    const CandidateEvaluation evaluation = evaluate_seed_candidate(
        index, total_candidates, query, nullptr);
    commit_block_counters(evaluation, counters);
}

__global__ void query_dense_count_kernel(
    const DensePosition* positions,
    std::uint64_t total_candidates,
    DeviceQuery query,
    OrbitCounters* counters) {
    const std::uint64_t index = static_cast<std::uint64_t>(blockIdx.x) * blockDim.x + threadIdx.x;
    const CandidateEvaluation evaluation = evaluate_dense_candidate(
        index, total_candidates, positions, query, nullptr);
    commit_block_counters(evaluation, counters);
}

__global__ void query_seed_compact_kernel(
    std::uint64_t total_candidates,
    DeviceQuery query,
    OrbitCounters* counters,
    CompactOrbitEvent* events,
    unsigned long long* event_count,
    unsigned long long event_capacity) {
    const std::uint64_t index = static_cast<std::uint64_t>(blockIdx.x) * blockDim.x + threadIdx.x;
    CompactOrbitEvent event{};
    const CandidateEvaluation evaluation = evaluate_seed_candidate(
        index, total_candidates, query, &event);
    commit_block_counters(evaluation, counters);
    compact_warp_event(evaluation, event, events, event_count, event_capacity);
}

__global__ void query_dense_compact_kernel(
    const DensePosition* positions,
    std::uint64_t total_candidates,
    DeviceQuery query,
    OrbitCounters* counters,
    CompactOrbitEvent* events,
    unsigned long long* event_count,
    unsigned long long event_capacity) {
    const std::uint64_t index = static_cast<std::uint64_t>(blockIdx.x) * blockDim.x + threadIdx.x;
    CompactOrbitEvent event{};
    const CandidateEvaluation evaluation = evaluate_dense_candidate(
        index, total_candidates, positions, query, &event);
    commit_block_counters(evaluation, counters);
    compact_warp_event(evaluation, event, events, event_count, event_capacity);
}

struct TimingStats {
    double p50_ms{};
    double p95_ms{};
    double p99_ms{};
    double mean_ms{};
    std::uint32_t inner_repeats{};
};

struct Result {
    std::string mode;
    TimingStats timing{};
    OrbitCounters counters{};
    double candidates_per_second{};
    double logical_gigabytes_per_second{};
    std::uint64_t logical_bytes_per_candidate{};
    std::uint64_t event_count{};
    bool event_truncated{};
};

template <typename Launch>
TimingStats measure_cuda(
    Launch&& launch,
    std::uint32_t warmup,
    std::uint32_t samples,
    float minimum_sample_ms) {
    for (std::uint32_t index = 0u; index < warmup; ++index) launch();
    CUDA_CHECK(cudaGetLastError());
    CUDA_CHECK(cudaDeviceSynchronize());

    cudaEvent_t start{};
    cudaEvent_t stop{};
    CUDA_CHECK(cudaEventCreate(&start));
    CUDA_CHECK(cudaEventCreate(&stop));
    CUDA_CHECK(cudaEventRecord(start));
    launch();
    CUDA_CHECK(cudaEventRecord(stop));
    CUDA_CHECK(cudaEventSynchronize(stop));
    float probe_ms = 0.0f;
    CUDA_CHECK(cudaEventElapsedTime(&probe_ms, start, stop));
    probe_ms = std::max(probe_ms, 0.001f);
    const std::uint32_t inner = static_cast<std::uint32_t>(std::clamp(
        std::ceil(static_cast<double>(minimum_sample_ms) / probe_ms), 1.0, 4096.0));

    std::vector<double> values;
    values.reserve(samples);
    for (std::uint32_t sample = 0u; sample < samples; ++sample) {
        CUDA_CHECK(cudaEventRecord(start));
        for (std::uint32_t repeat = 0u; repeat < inner; ++repeat) launch();
        CUDA_CHECK(cudaEventRecord(stop));
        CUDA_CHECK(cudaEventSynchronize(stop));
        float elapsed_ms = 0.0f;
        CUDA_CHECK(cudaEventElapsedTime(&elapsed_ms, start, stop));
        values.push_back(static_cast<double>(elapsed_ms) / inner);
    }
    CUDA_CHECK(cudaEventDestroy(start));
    CUDA_CHECK(cudaEventDestroy(stop));
    CUDA_CHECK(cudaGetLastError());

    std::sort(values.begin(), values.end());
    const auto percentile = [&](double quantile) {
        const std::size_t index = static_cast<std::size_t>(std::ceil(
            quantile * static_cast<double>(values.size()))) - 1u;
        return values[std::min(index, values.size() - 1u)];
    };
    TimingStats stats{};
    stats.p50_ms = percentile(0.50);
    stats.p95_ms = percentile(0.95);
    stats.p99_ms = percentile(0.99);
    stats.mean_ms = std::accumulate(values.begin(), values.end(), 0.0) /
                    static_cast<double>(values.size());
    stats.inner_repeats = inner;
    return stats;
}

[[noreturn]] void usage(const char* executable, int exit_code) {
    std::ostream& output = exit_code == 0 ? std::cout : std::cerr;
    output
        << "KLB OrbitSeed sustained CUDA benchmark\n\n"
        << "Usage:\n  " << executable << " <input.kloc> [options]\n\n"
        << "Workload:\n"
        << "  --preset NAME          file, smoke, laptop, or vram (default laptop)\n"
        << "  --epochs N             Override candidate epochs/intervals\n"
        << "  --step-seconds X       Override timeline step\n"
        << "  --start-seconds X      Start relative to KLOC1 reference epoch\n"
        << "  --wrap-seconds X       Repeat a bounded timeline for stress; 0 disables\n"
        << "  --query NAME           crossing or visibility (default crossing)\n"
        << "  --mode NAME            all, seed, materialize, dense, or end-to-end\n\n"
        << "Ground query:\n"
        << "  --lat X --lon X        Station latitude/longitude degrees (default 52,5)\n"
        << "  --alt-km X             Station altitude kilometres (default 0.05)\n"
        << "  --elevation-deg X      Elevation guard threshold (default 10)\n"
        << "  --crossing-band-deg X  Accepted sampled crossing band (default 0.25)\n"
        << "  --max-range-km X       Analytic support radius (default 33000)\n"
        << "  --route any|0..5       Compatibility route sector (default any)\n\n"
        << "Measurement:\n"
        << "  --warmup N             Untimed samples (default 2)\n"
        << "  --samples N            Timed distribution samples (default 9)\n"
        << "  --min-sample-ms X      Auto-repeat each sample to this duration (default 150)\n"
        << "  --verify-epochs N      CPU/GPU oracle prefix (default 4096; 0 disables)\n"
        << "  --write-events         Benchmark warp-compacted event output\n"
        << "  --event-capacity N     Maximum retained events (default 1000000)\n"
        << "  --device N             CUDA device ordinal\n"
        << "  --csv PATH             Append benchmark rows\n\n"
        << "The predictor is deliberately coarse Kepler+J2, not SGP4/navigation.\n";
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
    for (int index = 2; index < argc; ++index) {
        const std::string argument = argv[index];
        auto value = [&]() -> const char* {
            if (++index >= argc) throw std::invalid_argument(argument + " requires a value");
            return argv[index];
        };
        if (argument == "--preset") options.preset = value();
        else if (argument == "--epochs") options.epochs = parse_u64(value(), "--epochs");
        else if (argument == "--step-seconds") options.step_seconds = parse_float(value(), "--step-seconds");
        else if (argument == "--start-seconds") options.start_seconds = parse_float(value(), "--start-seconds");
        else if (argument == "--wrap-seconds") options.wrap_seconds = parse_float(value(), "--wrap-seconds");
        else if (argument == "--query") options.query = value();
        else if (argument == "--mode") options.mode = value();
        else if (argument == "--lat") options.latitude_degrees = parse_float(value(), "--lat");
        else if (argument == "--lon") options.longitude_degrees = parse_float(value(), "--lon");
        else if (argument == "--alt-km") options.altitude_km = parse_float(value(), "--alt-km");
        else if (argument == "--elevation-deg") options.elevation_degrees = parse_float(value(), "--elevation-deg");
        else if (argument == "--crossing-band-deg") options.crossing_band_degrees = parse_float(value(), "--crossing-band-deg");
        else if (argument == "--max-range-km") options.maximum_slant_range_km = parse_float(value(), "--max-range-km");
        else if (argument == "--route") {
            const std::string route = value();
            if (route == "any") options.route_filter = 0xffffffffu;
            else {
                const std::uint64_t parsed = parse_u64(route, "--route");
                if (parsed > 5u) throw std::invalid_argument("--route must be any or 0..5");
                options.route_filter = static_cast<std::uint32_t>(parsed);
            }
        } else if (argument == "--warmup") options.warmup = static_cast<std::uint32_t>(parse_u64(value(), "--warmup"));
        else if (argument == "--samples") options.samples = static_cast<std::uint32_t>(parse_u64(value(), "--samples"));
        else if (argument == "--min-sample-ms") options.minimum_sample_ms = parse_float(value(), "--min-sample-ms");
        else if (argument == "--verify-epochs") options.verify_epochs = static_cast<std::uint32_t>(parse_u64(value(), "--verify-epochs"));
        else if (argument == "--write-events") options.write_events = true;
        else if (argument == "--event-capacity") options.event_capacity = parse_u64(value(), "--event-capacity");
        else if (argument == "--device") options.device = static_cast<int>(parse_u64(value(), "--device"));
        else if (argument == "--csv") options.csv = value();
        else if (argument == "--help" || argument == "-h") usage(argv[0], 0);
        else throw std::invalid_argument("unknown option: " + argument);
    }
    if (options.preset != "file" && options.preset != "smoke" &&
        options.preset != "laptop" && options.preset != "vram") {
        throw std::invalid_argument("--preset must be file, smoke, laptop, or vram");
    }
    if (options.mode != "all" && options.mode != "seed" && options.mode != "materialize" &&
        options.mode != "dense" && options.mode != "end-to-end") {
        throw std::invalid_argument("--mode must be all, seed, materialize, dense, or end-to-end");
    }
    if (options.query != "crossing" && options.query != "visibility") {
        throw std::invalid_argument("--query must be crossing or visibility");
    }
    if (options.samples == 0u || options.minimum_sample_ms <= 0.0f) {
        throw std::invalid_argument("measurement samples and duration must be positive");
    }
    return options;
}

std::uint64_t checked_multiply(std::uint64_t left, std::uint64_t right, const char* name) {
    if (right != 0u && left > std::numeric_limits<std::uint64_t>::max() / right) {
        throw std::overflow_error(std::string(name) + " overflows 64-bit size");
    }
    return left * right;
}

unsigned grid_for(std::uint64_t count) {
    const std::uint64_t blocks = (count + kBlockSize - 1u) / kBlockSize;
    if (blocks > static_cast<std::uint64_t>(std::numeric_limits<unsigned>::max())) {
        throw std::runtime_error("workload exceeds CUDA grid.x limit");
    }
    return static_cast<unsigned>(blocks);
}

OrbitCounters download_counters(const DeviceBuffer<OrbitCounters>& buffer) {
    OrbitCounters counters{};
    CUDA_CHECK(cudaMemcpy(&counters, buffer.get(), sizeof(counters), cudaMemcpyDeviceToHost));
    return counters;
}

std::uint64_t download_event_count(const DeviceBuffer<unsigned long long>& buffer) {
    unsigned long long count = 0u;
    CUDA_CHECK(cudaMemcpy(&count, buffer.get(), sizeof(count), cudaMemcpyDeviceToHost));
    return static_cast<std::uint64_t>(count);
}

bool counters_equal(const OrbitCounters& left, const OrbitCounters& right) {
    return left.candidate == right.candidate && left.supported == right.supported &&
           left.compatible == right.compatible && left.verified == right.verified;
}

void print_counters(const OrbitCounters& counters) {
    std::cout << "Candidates                  : " << counters.candidate << '\n'
              << "Support survivors           : " << counters.supported << '\n'
              << "Compatible survivors        : " << counters.compatible << '\n'
              << "Verified states/events      : " << counters.verified << '\n';
}

float host_sample_seconds(std::uint64_t epoch_index, const DeviceQuery& query) {
    const float unwrapped = query.start_seconds + static_cast<float>(epoch_index) * query.step_seconds;
    if (query.wrap_seconds > 0.0f) {
        const float local = unwrapped - query.start_seconds;
        return query.start_seconds + (local - std::floor(local / query.wrap_seconds) * query.wrap_seconds);
    }
    return unwrapped;
}

bool host_wrap_seam(std::uint64_t epoch_index, const DeviceQuery& query) {
    if (!(query.wrap_seconds > 0.0f)) return false;
    const float local0 = static_cast<float>(epoch_index) * query.step_seconds;
    const float local1 = static_cast<float>(epoch_index + 1u) * query.step_seconds;
    return std::floor(local0 / query.wrap_seconds) != std::floor(local1 / query.wrap_seconds);
}

OrbitCounters cpu_oracle_prefix(
    const klb::OrbitData& data,
    const DeviceQuery& query,
    std::uint64_t epochs) {
    OrbitCounters counters{};
    const klb::OrbitGroundStation station{
        query.station_ecef_km, query.elevation_mask_sin, query.crossing_band_sin,
        query.maximum_slant_range_km, query.route_filter,
    };
    for (std::uint64_t epoch = 0u; epoch < epochs; ++epoch) {
        for (const klb::OrbitSeedDisk& seed : data.seeds) {
            ++counters.candidate;
            if (query.query_kind == 0u) {
                const float seconds = host_sample_seconds(epoch, query);
                const klb::Vec3 position = klb::propagate_orbit_seed(seed, seconds);
                const klb::OrbitEvaluation evaluation = klb::evaluate_orbit_visibility(
                    position, seconds, station, query.reference_gmst_rad,
                    query.earth_rotation_rad_s, seed.route_sector);
                if (evaluation.supported != 0u) ++counters.supported;
                if (evaluation.supported != 0u && evaluation.compatible != 0u) {
                    ++counters.compatible;
                    if (evaluation.guard <= 0.0f) ++counters.verified;
                }
            } else {
                if (host_wrap_seam(epoch, query)) continue;
                const float previous_seconds = host_sample_seconds(epoch, query);
                const float current_seconds = host_sample_seconds(epoch + 1u, query);
                const klb::OrbitEvaluation previous = klb::evaluate_orbit_visibility(
                    klb::propagate_orbit_seed(seed, previous_seconds), previous_seconds,
                    station, query.reference_gmst_rad, query.earth_rotation_rad_s, seed.route_sector);
                const klb::OrbitEvaluation current = klb::evaluate_orbit_visibility(
                    klb::propagate_orbit_seed(seed, current_seconds), current_seconds,
                    station, query.reference_gmst_rad, query.earth_rotation_rad_s, seed.route_sector);
                const bool supported = previous.supported != 0u || current.supported != 0u;
                const bool compatible = supported && previous.compatible != 0u && current.compatible != 0u;
                if (supported) ++counters.supported;
                if (compatible) ++counters.compatible;
                const klb::OrbitCrossing crossing = klb::evaluate_orbit_crossing(
                    previous, current, previous_seconds, current_seconds, query.crossing_band_sin);
                if (crossing.verified != 0u) ++counters.verified;
            }
        }
    }
    return counters;
}

void append_csv(
    const std::filesystem::path& path,
    const cudaDeviceProp& device,
    const klb::OrbitData& data,
    const Options& options,
    std::uint64_t epochs,
    std::uint64_t dense_bytes,
    const Result& result) {
    const bool exists = std::filesystem::exists(path) && std::filesystem::file_size(path) != 0u;
    std::ofstream output(path, std::ios::app);
    if (!output) throw std::runtime_error("unable to append benchmark CSV: " + path.string());
    if (!exists) {
        output << "device,compute_capability,preset,query,mode,seeds,epochs,candidates,container_bytes,dense_bytes,working_set_ratio,step_seconds,wrap_seconds,p50_ms,p95_ms,p99_ms,mean_ms,inner_repeats,candidates_per_second,logical_gbps,candidate_count,support_count,compatible_count,verified_count,event_yield,event_count,event_truncated,predictor\n";
    }
    const std::uint64_t container_bytes = std::filesystem::file_size(options.input);
    const double ratio = static_cast<double>(dense_bytes) / static_cast<double>(container_bytes);
    output << '"' << device.name << "\"," << device.major << '.' << device.minor << ','
           << options.preset << ',' << options.query << ',' << result.mode << ','
           << data.seeds.size() << ',' << epochs << ',' << result.counters.candidate << ','
           << container_bytes << ',' << dense_bytes << ',' << std::setprecision(12) << ratio << ','
           << options.step_seconds << ',' << options.wrap_seconds << ','
           << result.timing.p50_ms << ',' << result.timing.p95_ms << ','
           << result.timing.p99_ms << ',' << result.timing.mean_ms << ','
           << result.timing.inner_repeats << ',' << result.candidates_per_second << ','
           << result.logical_gigabytes_per_second << ',' << result.counters.candidate << ','
           << result.counters.supported << ',' << result.counters.compatible << ','
           << result.counters.verified << ','
           << (result.counters.candidate != 0u
               ? static_cast<double>(result.counters.verified) / result.counters.candidate
               : 0.0) << ','
           << result.event_count << ',' << (result.event_truncated ? 1 : 0) << ','
           << "kepler_j2_secular_coarse\n";
}

bool event_less(const CompactOrbitEvent& left, const CompactOrbitEvent& right) {
    if (left.epoch_index != right.epoch_index) return left.epoch_index < right.epoch_index;
    if (left.norad_id != right.norad_id) return left.norad_id < right.norad_id;
    return (left.lineage_and_type & 1u) < (right.lineage_and_type & 1u);
}

} // namespace

int main(int argc, char** argv) {
    try {
        Options options = parse_options(argc, argv);
        const klb::OrbitData data = klb::load_orbit_data(options.input);
        if (data.seeds.size() > kMaxSeeds || data.nodes.size() > kMaxNodes) {
            throw std::runtime_error("bundled CUDA constant-memory path supports at most 256 seeds and 256 nodes");
        }
        if (options.step_seconds == 0.0f) options.step_seconds = data.header.timeline_step_seconds;
        if (!(options.step_seconds > 0.0f)) throw std::invalid_argument("step must be positive");

        if (options.epochs == 0u) {
            if (options.preset == "file") {
                options.epochs = options.query == "crossing"
                    ? data.header.timeline_sample_count - 1u
                    : data.header.timeline_sample_count;
            } else if (options.preset == "smoke") {
                options.epochs = 65536u;
            } else if (options.preset == "laptop") {
                options.epochs = 1048576u;
            } else {
                options.epochs = 4194304u;
            }
        }
        if (options.epochs == 0u) throw std::invalid_argument("epoch count must be non-zero");
        if (options.epochs > std::numeric_limits<std::uint32_t>::max()) {
            throw std::invalid_argument("current compact event ABI uses a 32-bit epoch index");
        }
        if (options.wrap_seconds < 0.0f) {
            const double requested_duration = static_cast<double>(options.epochs) * options.step_seconds;
            options.wrap_seconds = requested_duration > data.header.timeline_duration_seconds
                ? data.header.timeline_duration_seconds
                : 0.0f;
        }

        CUDA_CHECK(cudaSetDevice(options.device));
        cudaDeviceProp device{};
        CUDA_CHECK(cudaGetDeviceProperties(&device, options.device));
        CUDA_CHECK(cudaMemcpyToSymbol(
            g_orbit_seeds, data.seeds.data(), data.seeds.size() * sizeof(klb::OrbitSeedDisk)));
        CUDA_CHECK(cudaMemcpyToSymbol(
            g_orbit_nodes, data.nodes.data(), data.nodes.size() * sizeof(klb::OrbitTimelineNodeDisk)));

        const klb::OrbitGroundStation station = klb::make_ground_station(
            options.latitude_degrees, options.longitude_degrees, options.altitude_km,
            options.elevation_degrees, options.crossing_band_degrees,
            options.maximum_slant_range_km, options.route_filter);
        DeviceQuery query{};
        query.station_ecef_km = station.ecef_km;
        query.elevation_mask_sin = station.elevation_mask_sin;
        query.crossing_band_sin = station.crossing_band_sin;
        query.maximum_slant_range_km = station.maximum_slant_range_km;
        query.start_seconds = options.start_seconds;
        query.step_seconds = options.step_seconds;
        query.wrap_seconds = options.wrap_seconds;
        query.reference_gmst_rad = data.header.reference_gmst_rad;
        query.earth_rotation_rad_s = data.header.earth_rotation_rad_s;
        query.timeline_start_seconds = data.header.timeline_start_seconds;
        query.timeline_duration_seconds = data.header.timeline_duration_seconds;
        query.node_tile_seconds = data.nodes.front().duration_seconds;
        query.seed_count = static_cast<std::uint32_t>(data.seeds.size());
        query.node_count = static_cast<std::uint32_t>(data.nodes.size());
        query.route_filter = options.route_filter;
        query.query_kind = options.query == "crossing" ? 1u : 0u;

        const std::uint64_t total_candidates = checked_multiply(
            options.epochs, data.seeds.size(), "candidate count");
        const std::uint64_t position_epochs = options.epochs +
            (options.query == "crossing" ? 1u : 0u);
        const std::uint64_t position_count = checked_multiply(
            position_epochs, data.seeds.size(), "dense position count");
        const std::uint64_t dense_bytes = checked_multiply(
            position_count, sizeof(DensePosition), "dense position bytes");
        if (position_count > std::numeric_limits<std::size_t>::max()) {
            throw std::runtime_error("dense position allocation exceeds host size_t");
        }

        const bool needs_dense = options.mode == "all" || options.mode == "materialize" ||
                                 options.mode == "dense" || options.mode == "end-to-end";
        std::size_t free_bytes = 0u;
        std::size_t total_bytes = 0u;
        CUDA_CHECK(cudaMemGetInfo(&free_bytes, &total_bytes));
        const std::uint64_t event_bytes = options.write_events
            ? checked_multiply(options.event_capacity, sizeof(CompactOrbitEvent), "event bytes")
            : 0u;
        if (needs_dense && dense_bytes + event_bytes + (128ull << 20u) >
            static_cast<std::uint64_t>(free_bytes) * 85u / 100u) {
            throw std::runtime_error(
                "requested dense workload leaves too little free VRAM; choose --preset laptop/smoke or lower --epochs");
        }

        DeviceBuffer<DensePosition> dense_positions(
            needs_dense ? static_cast<std::size_t>(position_count) : 0u);
        DeviceBuffer<OrbitCounters> counters(1u);
        DeviceBuffer<CompactOrbitEvent> events(
            options.write_events ? static_cast<std::size_t>(options.event_capacity) : 0u);
        DeviceBuffer<unsigned long long> event_count(options.write_events ? 1u : 0u);

        const unsigned candidate_grid = grid_for(total_candidates);
        const unsigned position_grid = grid_for(position_count);
        const dim3 block(kBlockSize, 1u, 1u);

        std::cout << std::fixed << std::setprecision(6)
                  << "Device                      : " << device.name << '\n'
                  << "Compute capability          : " << device.major << '.' << device.minor << '\n'
                  << "CUDA global memory          : "
                  << static_cast<double>(device.totalGlobalMem) / (1024.0 * 1024.0) << " MiB\n"
                  << "Reported L2                 : "
                  << static_cast<double>(device.l2CacheSize) / 1024.0 << " KiB\n"
                  << "SM count                    : " << device.multiProcessorCount << '\n'
                  << "Memory bus width            : " << device.memoryBusWidth << " bits\n"
                  << "Predictor                   : coarse Kepler + compiled secular J2\n"
                  << "Reference epoch             : "
                  << klb::format_unix_microseconds_iso8601(data.header.reference_unix_microseconds) << '\n'
                  << "Seeds / chain nodes         : " << data.seeds.size() << " / " << data.nodes.size() << '\n'
                  << "Query                       : " << options.query << '\n'
                  << "Epochs/intervals            : " << options.epochs << '\n'
                  << "Candidates                  : " << total_candidates << '\n'
                  << "Dense float4 positions      : " << position_count << '\n'
                  << "Dense working set           : "
                  << static_cast<double>(dense_bytes) / (1024.0 * 1024.0) << " MiB\n"
                  << "KLOC1 container             : " << std::filesystem::file_size(options.input) << " bytes\n"
                  << "Working-set ratio           : "
                  << static_cast<double>(dense_bytes) / std::filesystem::file_size(options.input) << "x\n"
                  << "Auto-wrap stress timeline   : "
                  << (options.wrap_seconds > 0.0f ? std::to_string(options.wrap_seconds) + " s" : "disabled") << '\n'
                  << "Station                     : " << options.latitude_degrees << ", "
                  << options.longitude_degrees << " deg\n"
                  << "Elevation guard             : " << options.elevation_degrees << " deg\n";
        if (options.wrap_seconds > 0.0f) {
            std::cout << "Physical-horizon boundary   : repeated bounded timeline for load only\n";
        }

        std::vector<Result> results;
        bool dense_ready = false;

        auto launch_materialize = [&]() {
            materialize_orbits_kernel<<<position_grid, block>>>(
                dense_positions.get(), position_count, query);
        };
        auto launch_seed_count = [&]() {
            CUDA_CHECK(cudaMemsetAsync(counters.get(), 0, sizeof(OrbitCounters)));
            query_seed_count_kernel<<<candidate_grid, block>>>(
                total_candidates, query, counters.get());
        };
        auto launch_dense_count = [&]() {
            CUDA_CHECK(cudaMemsetAsync(counters.get(), 0, sizeof(OrbitCounters)));
            query_dense_count_kernel<<<candidate_grid, block>>>(
                dense_positions.get(), total_candidates, query, counters.get());
        };
        auto launch_seed_compact = [&]() {
            CUDA_CHECK(cudaMemsetAsync(counters.get(), 0, sizeof(OrbitCounters)));
            CUDA_CHECK(cudaMemsetAsync(event_count.get(), 0, sizeof(unsigned long long)));
            query_seed_compact_kernel<<<candidate_grid, block>>>(
                total_candidates, query, counters.get(), events.get(), event_count.get(),
                static_cast<unsigned long long>(options.event_capacity));
        };
        auto launch_dense_compact = [&]() {
            CUDA_CHECK(cudaMemsetAsync(counters.get(), 0, sizeof(OrbitCounters)));
            CUDA_CHECK(cudaMemsetAsync(event_count.get(), 0, sizeof(unsigned long long)));
            query_dense_compact_kernel<<<candidate_grid, block>>>(
                dense_positions.get(), total_candidates, query, counters.get(), events.get(),
                event_count.get(), static_cast<unsigned long long>(options.event_capacity));
        };

        auto run_count = [&](const std::string& name, auto&& launch, std::uint64_t logical_bytes) {
            Result result{};
            result.mode = name;
            result.logical_bytes_per_candidate = logical_bytes;
            result.timing = measure_cuda(
                launch, options.warmup, options.samples, options.minimum_sample_ms);
            launch();
            CUDA_CHECK(cudaGetLastError());
            CUDA_CHECK(cudaDeviceSynchronize());
            result.counters = download_counters(counters);
            result.candidates_per_second = static_cast<double>(result.counters.candidate) /
                (result.timing.p50_ms * 1.0e-3);
            result.logical_gigabytes_per_second = logical_bytes != 0u
                ? result.candidates_per_second * static_cast<double>(logical_bytes) / 1.0e9
                : 0.0;
            results.push_back(result);
        };

        auto run_materialize = [&]() {
            Result result{};
            result.mode = "materialize_dense";
            result.timing = measure_cuda(
                launch_materialize, options.warmup, options.samples, options.minimum_sample_ms);
            launch_materialize();
            CUDA_CHECK(cudaGetLastError());
            CUDA_CHECK(cudaDeviceSynchronize());
            dense_ready = true;
            result.counters.candidate = position_count;
            result.candidates_per_second = static_cast<double>(position_count) /
                (result.timing.p50_ms * 1.0e-3);
            result.logical_bytes_per_candidate = sizeof(DensePosition);
            result.logical_gigabytes_per_second = result.candidates_per_second *
                sizeof(DensePosition) / 1.0e9;
            results.push_back(result);
        };

        if (options.mode == "all" || options.mode == "seed") {
            run_count("query_seed_direct", launch_seed_count, 0u);
        }
        if (needs_dense && (options.mode == "all" || options.mode == "materialize" ||
                            options.mode == "dense" || options.mode == "end-to-end")) {
            run_materialize();
        }
        if (options.mode == "all" || options.mode == "dense") {
            const std::uint64_t bytes_per_candidate = options.query == "crossing"
                ? 2u * sizeof(DensePosition)
                : sizeof(DensePosition);
            run_count("query_dense", launch_dense_count, bytes_per_candidate);
        }
        if (options.mode == "all" || options.mode == "end-to-end") {
            Result result{};
            result.mode = "materialize_plus_query";
            const auto launch = [&]() {
                launch_materialize();
                launch_dense_count();
            };
            result.timing = measure_cuda(
                launch, options.warmup, options.samples, options.minimum_sample_ms);
            launch();
            CUDA_CHECK(cudaGetLastError());
            CUDA_CHECK(cudaDeviceSynchronize());
            result.counters = download_counters(counters);
            result.candidates_per_second = static_cast<double>(result.counters.candidate) /
                (result.timing.p50_ms * 1.0e-3);
            const std::uint64_t read_bytes = options.query == "crossing"
                ? 2u * sizeof(DensePosition)
                : sizeof(DensePosition);
            result.logical_bytes_per_candidate = read_bytes + sizeof(DensePosition);
            result.logical_gigabytes_per_second = result.candidates_per_second *
                result.logical_bytes_per_candidate / 1.0e9;
            results.push_back(result);
            dense_ready = true;
        }

        std::vector<CompactOrbitEvent> seed_events;
        std::vector<CompactOrbitEvent> dense_events;
        if (options.write_events) {
            Result seed_result{};
            seed_result.mode = "compact_seed_events";
            seed_result.timing = measure_cuda(
                launch_seed_compact, options.warmup, options.samples, options.minimum_sample_ms);
            launch_seed_compact();
            CUDA_CHECK(cudaGetLastError());
            CUDA_CHECK(cudaDeviceSynchronize());
            seed_result.counters = download_counters(counters);
            seed_result.event_count = download_event_count(event_count);
            seed_result.event_truncated = seed_result.event_count > options.event_capacity;
            seed_result.candidates_per_second = static_cast<double>(seed_result.counters.candidate) /
                (seed_result.timing.p50_ms * 1.0e-3);
            if (!seed_result.event_truncated) {
                seed_events = events.download_prefix(static_cast<std::size_t>(seed_result.event_count));
            }
            results.push_back(seed_result);

            if (needs_dense) {
                if (!dense_ready) {
                    launch_materialize();
                    CUDA_CHECK(cudaGetLastError());
                    CUDA_CHECK(cudaDeviceSynchronize());
                    dense_ready = true;
                }
                Result dense_result{};
                dense_result.mode = "compact_dense_events";
                dense_result.timing = measure_cuda(
                    launch_dense_compact, options.warmup, options.samples, options.minimum_sample_ms);
                launch_dense_compact();
                CUDA_CHECK(cudaGetLastError());
                CUDA_CHECK(cudaDeviceSynchronize());
                dense_result.counters = download_counters(counters);
                dense_result.event_count = download_event_count(event_count);
                dense_result.event_truncated = dense_result.event_count > options.event_capacity;
                dense_result.candidates_per_second = static_cast<double>(dense_result.counters.candidate) /
                    (dense_result.timing.p50_ms * 1.0e-3);
                if (!dense_result.event_truncated) {
                    dense_events = events.download_prefix(static_cast<std::size_t>(dense_result.event_count));
                }
                results.push_back(dense_result);
            }
        }

        const auto seed_result = std::find_if(results.begin(), results.end(), [](const Result& result) {
            return result.mode == "query_seed_direct";
        });
        const auto dense_result = std::find_if(results.begin(), results.end(), [](const Result& result) {
            return result.mode == "query_dense";
        });
        if (seed_result != results.end() && dense_result != results.end() &&
            !counters_equal(seed_result->counters, dense_result->counters)) {
            throw std::runtime_error("direct seed and dense query counters differ");
        }

        if (options.verify_epochs != 0u) {
            const std::uint64_t verify_epochs = std::min<std::uint64_t>(
                options.verify_epochs, options.epochs);
            const std::uint64_t verify_candidates = verify_epochs * data.seeds.size();
            const OrbitCounters expected = cpu_oracle_prefix(data, query, verify_epochs);
            CUDA_CHECK(cudaMemset(counters.get(), 0, sizeof(OrbitCounters)));
            query_seed_count_kernel<<<grid_for(verify_candidates), block>>>(
                verify_candidates, query, counters.get());
            CUDA_CHECK(cudaGetLastError());
            CUDA_CHECK(cudaDeviceSynchronize());
            const OrbitCounters direct_prefix = download_counters(counters);
            if (!counters_equal(expected, direct_prefix)) {
                std::cerr << "CPU expected:\n";
                print_counters(expected);
                std::cerr << "GPU direct prefix:\n";
                print_counters(direct_prefix);
                throw std::runtime_error("CPU/GPU orbit query oracle mismatch");
            }
            if (dense_ready) {
                CUDA_CHECK(cudaMemset(counters.get(), 0, sizeof(OrbitCounters)));
                query_dense_count_kernel<<<grid_for(verify_candidates), block>>>(
                    dense_positions.get(), verify_candidates, query, counters.get());
                CUDA_CHECK(cudaGetLastError());
                CUDA_CHECK(cudaDeviceSynchronize());
                const OrbitCounters dense_prefix = download_counters(counters);
                if (!counters_equal(expected, dense_prefix)) {
                    throw std::runtime_error("CPU/GPU dense orbit query oracle mismatch");
                }
            }
            std::cout << "CPU/GPU oracle prefix       : " << verify_epochs
                      << " epochs, exact counters\n";
        }

        if (!seed_events.empty() || !dense_events.empty()) {
            if (seed_events.size() != dense_events.size() && needs_dense) {
                throw std::runtime_error("direct and dense compact event counts differ");
            }
            if (needs_dense) {
                std::sort(seed_events.begin(), seed_events.end(), event_less);
                std::sort(dense_events.begin(), dense_events.end(), event_less);
                for (std::size_t index = 0u; index < seed_events.size(); ++index) {
                    const CompactOrbitEvent& left = seed_events[index];
                    const CompactOrbitEvent& right = dense_events[index];
                    if (left.epoch_index != right.epoch_index || left.norad_id != right.norad_id ||
                        left.lineage_and_type != right.lineage_and_type ||
                        std::fabs(left.crossing_seconds - right.crossing_seconds) > 1.0e-4f) {
                        throw std::runtime_error("direct and dense compact event payloads differ");
                    }
                }
                std::cout << "Compacted event-set match   : " << seed_events.size()
                          << " sorted events\n";
            }
        }

        for (const Result& result : results) {
            std::cout << "\nMode                        : " << result.mode << '\n'
                      << "p50 / p95 / p99             : " << result.timing.p50_ms << " / "
                      << result.timing.p95_ms << " / " << result.timing.p99_ms << " ms\n"
                      << "Inner repeats               : " << result.timing.inner_repeats << '\n'
                      << "Rate                        : "
                      << result.candidates_per_second / 1.0e6 << " M candidates/s\n";
            if (result.logical_bytes_per_candidate != 0u) {
                std::cout << "Logical traffic             : "
                          << result.logical_gigabytes_per_second << " GB/s\n";
            }
            if (result.mode != "materialize_dense") {
                print_counters(result.counters);
                const double yield = result.counters.candidate != 0u
                    ? static_cast<double>(result.counters.verified) / result.counters.candidate
                    : 0.0;
                std::cout << "Verified yield              : " << 100.0 * yield << "%\n";
            }
            if (result.mode.rfind("compact_", 0u) == 0u) {
                std::cout << "Compacted event count       : " << result.event_count << '\n'
                          << "Event output truncated      : "
                          << (result.event_truncated ? "yes" : "no") << '\n';
            }
            if (!options.csv.empty()) {
                append_csv(options.csv, device, data, options, options.epochs, dense_bytes, result);
            }
        }

        if (seed_result != results.end() && dense_result != results.end()) {
            std::cout << "\nDirect seed / dense p50     : "
                      << seed_result->timing.p50_ms / dense_result->timing.p50_ms << "x\n"
                      << "Dense / direct rate         : "
                      << dense_result->candidates_per_second /
                         seed_result->candidates_per_second << "x\n";
        }
        std::cout << "\nAcceptance boundary         : promote only if measured memory savings justify\n"
                  << "                              predictor cost at the required error budget.\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "error: " << error.what() << '\n';
        return 1;
    }
}
