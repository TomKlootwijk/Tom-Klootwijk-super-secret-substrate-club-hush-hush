#include <cuda_runtime.h>

#include "klb/network.hpp"
#include "klb/sgp4_gpu_compat.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <numeric>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

namespace {

#define CUDA_CHECK(call) do { \
    const cudaError_t error__ = (call); \
    if (error__ != cudaSuccess) { \
        std::ostringstream stream__; \
        stream__ << "CUDA error " << cudaGetErrorName(error__) << " (" \
                 << cudaGetErrorString(error__) << ") at " << __FILE__ << ':' << __LINE__; \
        throw std::runtime_error(stream__.str()); \
    } \
} while (0)

struct Vec3d { double x{}, y{}, z{}; };

struct ObjectMeta {
    std::uint32_t norad_id{};
    std::uint32_t route{};
    std::uint32_t lineage_seed{};
    std::uint32_t reserved{};
};

struct PairIndex {
    std::uint32_t object{};
    std::uint32_t station{};
};

struct GpuCounters {
    unsigned long long relation_intervals{};
    unsigned long long propagated_intervals{};
    unsigned long long supported{};
    unsigned long long compatible{};
    unsigned long long visible_endpoints{};
    unsigned long long boundary_evaluations{};
    unsigned long long aos{};
    unsigned long long los{};
    unsigned long long propagation_errors{};
};

struct GpuEvent {
    std::uint32_t station_id{};
    std::uint32_t norad_id{};
    std::uint32_t interval_index{};
    std::uint32_t type{};
    std::uint32_t lineage{};
    std::uint32_t route{};
    double crossing_seconds{};
    double minimum_abs_guard{};
};
static_assert(sizeof(GpuEvent) == 40u, "network GPU event ABI changed");

struct Options {
    std::filesystem::path input;
    std::filesystem::path stations;
    std::filesystem::path csv;
    std::string preset{"file"};
    std::uint64_t intervals{};
    double step_seconds{};
    std::uint32_t chunk{128u};
    int repeats{7};
    double min_ms{150.0};
    std::uint64_t validation_intervals{10080u};
    std::uint64_t event_capacity{1000000u};
    bool skip_dense{};
};

struct Timing {
    std::vector<double> samples;
    double p50{}, p95{}, p99{}, mean{};
    int inner{1};
};

__host__ __device__ inline Vec3d make_vec(double x, double y, double z) {
    return Vec3d{x, y, z};
}

__host__ __device__ inline std::uint64_t ceil_div(std::uint64_t a, std::uint64_t b) {
    return (a + b - 1u) / b;
}

__host__ __device__ inline klb::Sgp4Visibility visibility_from_pef(
    const Vec3d& satellite,
    const klb::NetworkStationGpu& station,
    bool compatible) {
    const double dx = satellite.x - station.ground.ecef_km[0];
    const double dy = satellite.y - station.ground.ecef_km[1];
    const double dz = satellite.z - station.ground.ecef_km[2];
    const double range = sqrt(dx * dx + dy * dy + dz * dz);
    const double elevation_sin = range > 1.0e-12
        ? (dx * station.ground.up_unit[0] + dy * station.ground.up_unit[1] +
           dz * station.ground.up_unit[2]) / range
        : 1.0;
    return klb::Sgp4Visibility{
        station.ground.elevation_mask_sin - elevation_sin,
        elevation_sin,
        range,
        range <= station.ground.maximum_slant_range_km ? 1u : 0u,
        compatible ? 1u : 0u,
    };
}

__host__ __device__ inline bool propagate_pef(
    const ElsetRec& record,
    double absolute_jd_utc,
    double dut1_seconds,
    Vec3d& position,
    int& error) {
    const double epoch_jd = record.jdsatepoch + record.jdsatepochF;
    const double minutes = (absolute_jd_utc - epoch_jd) * 1440.0;
    double teme[3]{};
    double velocity[3]{};
    const bool ok = klb::sgp4_propagate_immutable(
        static_cast<const klb::Sgp4Record&>(record), minutes,
        teme, velocity, &error);
    if (!ok || error != 0) {
        position = make_vec(0.0, 0.0, 0.0);
        return false;
    }
    double pef[3]{};
    klb::sgp4_teme_to_pef(teme, absolute_jd_utc + dut1_seconds / 86400.0, pef);
    position = make_vec(pef[0], pef[1], pef[2]);
    return true;
}

__device__ void add_counters(GpuCounters* destination, const GpuCounters& local) {
    if (local.relation_intervals) atomicAdd(&destination->relation_intervals, local.relation_intervals);
    if (local.propagated_intervals) atomicAdd(&destination->propagated_intervals, local.propagated_intervals);
    if (local.supported) atomicAdd(&destination->supported, local.supported);
    if (local.compatible) atomicAdd(&destination->compatible, local.compatible);
    if (local.visible_endpoints) atomicAdd(&destination->visible_endpoints, local.visible_endpoints);
    if (local.boundary_evaluations) atomicAdd(&destination->boundary_evaluations, local.boundary_evaluations);
    if (local.aos) atomicAdd(&destination->aos, local.aos);
    if (local.los) atomicAdd(&destination->los, local.los);
    if (local.propagation_errors) atomicAdd(&destination->propagation_errors, local.propagation_errors);
}

__device__ std::uint32_t event_lineage(
    const ObjectMeta& meta,
    const klb::Sgp4TimelineNodeDisk* nodes,
    std::uint32_t node_count,
    double crossing_seconds,
    std::uint64_t interval,
    std::uint32_t station_id,
    std::uint32_t type) {
    std::uint32_t base = meta.lineage_seed;
    if (node_count != 0u) {
        const std::uint32_t node_index = klb::sgp4_timeline_node_index(
            nodes, node_count, crossing_seconds);
        const std::uint32_t lo = static_cast<std::uint32_t>(interval);
        const std::uint32_t hi = static_cast<std::uint32_t>(interval >> 32u);
        base = klb::mix32(meta.lineage_seed ^ nodes[node_index].chain_seed ^ lo ^
                          klb::mix32(hi) ^ type * 0x9e3779b9u);
    }
    return klb::network_event_lineage(base, station_id, type);
}

__device__ void append_event(
    GpuEvent* events,
    unsigned long long* count,
    unsigned long long capacity,
    const GpuEvent& event) {
    if (!events || !count) return;
    const unsigned long long index = atomicAdd(count, 1ull);
    if (index < capacity) events[index] = event;
}

__device__ void evaluate_relation(
    const klb::Sgp4Visibility& previous,
    const klb::Sgp4Visibility& current,
    double previous_seconds,
    double current_seconds,
    std::uint64_t interval,
    const ObjectMeta& meta,
    const klb::NetworkStationGpu& station,
    const klb::Sgp4TimelineNodeDisk* nodes,
    std::uint32_t node_count,
    GpuCounters& counters,
    GpuEvent* events,
    unsigned long long* event_count,
    unsigned long long event_capacity) {
    ++counters.relation_intervals;
    const bool supported = previous.supported != 0u || current.supported != 0u;
    const bool compatible = supported && previous.compatible != 0u && current.compatible != 0u;
    if (supported) ++counters.supported;
    if (compatible) {
        ++counters.compatible;
        ++counters.boundary_evaluations;
    }
    if (current.supported != 0u && current.compatible != 0u && current.guard <= 0.0) {
        ++counters.visible_endpoints;
    }
    const klb::Sgp4Crossing crossing = klb::sgp4_evaluate_crossing(
        previous, current, previous_seconds, current_seconds,
        station.ground.crossing_band_sin);
    if (crossing.verified == 0u) return;
    const std::uint32_t type = crossing.acquisition != 0u ? 1u : 2u;
    if (type == 1u) ++counters.aos; else ++counters.los;
    GpuEvent event{};
    event.station_id = station.station_id;
    event.norad_id = meta.norad_id;
    event.interval_index = static_cast<std::uint32_t>(interval);
    event.type = type;
    event.route = meta.route;
    event.lineage = event_lineage(meta, nodes, node_count,
                                  crossing.crossing_seconds, interval,
                                  station.station_id, type);
    event.crossing_seconds = crossing.crossing_seconds;
    event.minimum_abs_guard = crossing.minimum_abs_guard;
    append_event(events, event_count, event_capacity, event);
}

__global__ void pair_query_kernel(
    const ElsetRec* records,
    const ObjectMeta* meta,
    const klb::NetworkObjectProfile* profiles,
    const klb::NetworkStationGpu* stations,
    const PairIndex* pairs,
    std::uint32_t pair_count,
    std::uint64_t intervals,
    double reference_jd,
    double step_seconds,
    double dut1_seconds,
    std::uint32_t chunk_size,
    const klb::Sgp4TimelineNodeDisk* nodes,
    std::uint32_t node_count,
    GpuCounters* counters,
    GpuEvent* events,
    unsigned long long* event_count,
    unsigned long long event_capacity) {
    const std::uint64_t chunks_per_pair = ceil_div(intervals, chunk_size);
    const std::uint64_t thread = static_cast<std::uint64_t>(blockIdx.x) * blockDim.x + threadIdx.x;
    const std::uint64_t total = static_cast<std::uint64_t>(pair_count) * chunks_per_pair;
    if (thread >= total) return;
    const std::uint32_t pair_index = static_cast<std::uint32_t>(thread / chunks_per_pair);
    const std::uint64_t chunk_index = thread % chunks_per_pair;
    const PairIndex pair = pairs[pair_index];
    const ElsetRec& record = records[pair.object];
    const ObjectMeta& object_meta = meta[pair.object];
    const klb::NetworkObjectProfile& profile = profiles[pair.object];
    const klb::NetworkStationGpu& station = stations[pair.station];
    const bool policy = klb::network_policy_compatible(profile, station, object_meta.route);
    const std::uint64_t begin = chunk_index * chunk_size;
    const std::uint64_t end = (intervals < begin + static_cast<std::uint64_t>(chunk_size) ? intervals : begin + static_cast<std::uint64_t>(chunk_size));
    Vec3d previous_pef{};
    int previous_error = 0;
    const double previous_seconds0 = static_cast<double>(begin) * step_seconds;
    bool previous_ok = propagate_pef(record, reference_jd + previous_seconds0 / 86400.0,
                                     dut1_seconds, previous_pef, previous_error);
    klb::Sgp4Visibility previous{};
    if (previous_ok) previous = visibility_from_pef(previous_pef, station, policy);
    GpuCounters local{};
    for (std::uint64_t interval = begin; interval < end; ++interval) {
        const double previous_seconds = static_cast<double>(interval) * step_seconds;
        const double current_seconds = static_cast<double>(interval + 1u) * step_seconds;
        Vec3d current_pef{};
        int current_error = 0;
        const bool current_ok = propagate_pef(record,
            reference_jd + current_seconds / 86400.0, dut1_seconds,
            current_pef, current_error);
        ++local.propagated_intervals;
        klb::Sgp4Visibility current{};
        if (current_ok) current = visibility_from_pef(current_pef, station, policy);
        if (previous_ok && current_ok) {
            evaluate_relation(previous, current, previous_seconds, current_seconds,
                              interval, object_meta, station, nodes, node_count,
                              local, events, event_count, event_capacity);
        } else {
            ++local.relation_intervals;
            ++local.propagation_errors;
        }
        previous_ok = current_ok;
        previous_pef = current_pef;
        previous = current;
    }
    add_counters(counters, local);
}

__global__ void grouped_query_kernel(
    const ElsetRec* records,
    const ObjectMeta* meta,
    const klb::NetworkObjectProfile* profiles,
    const klb::NetworkStationGpu* stations,
    std::uint32_t object_count,
    std::uint32_t station_count,
    std::uint32_t pair_mode,
    std::uint64_t intervals,
    double reference_jd,
    double step_seconds,
    double dut1_seconds,
    std::uint32_t chunk_size,
    const klb::Sgp4TimelineNodeDisk* nodes,
    std::uint32_t node_count,
    GpuCounters* counters,
    GpuEvent* events,
    unsigned long long* event_count,
    unsigned long long event_capacity) {
    const std::uint64_t chunks_per_object = ceil_div(intervals, chunk_size);
    const std::uint64_t thread = static_cast<std::uint64_t>(blockIdx.x) * blockDim.x + threadIdx.x;
    const std::uint64_t total = static_cast<std::uint64_t>(object_count) * chunks_per_object;
    if (thread >= total) return;
    const std::uint32_t object = static_cast<std::uint32_t>(thread / chunks_per_object);
    const std::uint64_t chunk_index = thread % chunks_per_object;
    const klb::NetworkObjectProfile& profile = profiles[object];
    std::uint32_t station_mask = station_count == 32u ? 0xffffffffu :
        ((std::uint32_t{1u} << station_count) - 1u);
    if (pair_mode == static_cast<std::uint32_t>(klb::NetworkPairMode::Support)) {
        station_mask = profile.support_station_mask;
    } else if (pair_mode == static_cast<std::uint32_t>(klb::NetworkPairMode::Active)) {
        station_mask = profile.active_station_mask;
    }
    if (station_mask == 0u) return;
    const ElsetRec& record = records[object];
    const ObjectMeta& object_meta = meta[object];
    const std::uint64_t begin = chunk_index * chunk_size;
    const std::uint64_t end = (intervals < begin + static_cast<std::uint64_t>(chunk_size) ? intervals : begin + static_cast<std::uint64_t>(chunk_size));
    Vec3d previous_pef{};
    int previous_error = 0;
    bool previous_ok = propagate_pef(record,
        reference_jd + static_cast<double>(begin) * step_seconds / 86400.0,
        dut1_seconds, previous_pef, previous_error);
    GpuCounters local{};
    for (std::uint64_t interval = begin; interval < end; ++interval) {
        const double previous_seconds = static_cast<double>(interval) * step_seconds;
        const double current_seconds = static_cast<double>(interval + 1u) * step_seconds;
        Vec3d current_pef{};
        int current_error = 0;
        const bool current_ok = propagate_pef(record,
            reference_jd + current_seconds / 86400.0,
            dut1_seconds, current_pef, current_error);
        ++local.propagated_intervals;
        std::uint32_t mask = station_mask;
        while (mask != 0u) {
            const int station_index = __ffs(static_cast<int>(mask)) - 1;
            mask &= mask - 1u;
            const klb::NetworkStationGpu& station = stations[station_index];
            const bool policy = klb::network_policy_compatible(profile, station, object_meta.route);
            if (previous_ok && current_ok) {
                const klb::Sgp4Visibility previous = visibility_from_pef(previous_pef, station, policy);
                const klb::Sgp4Visibility current = visibility_from_pef(current_pef, station, policy);
                evaluate_relation(previous, current, previous_seconds, current_seconds,
                                  interval, object_meta, station, nodes, node_count,
                                  local, events, event_count, event_capacity);
            } else {
                ++local.relation_intervals;
                ++local.propagation_errors;
            }
        }
        previous_ok = current_ok;
        previous_pef = current_pef;
    }
    add_counters(counters, local);
}

__global__ void materialize_kernel(
    const ElsetRec* records,
    std::uint32_t object_count,
    std::uint64_t intervals,
    double reference_jd,
    double step_seconds,
    double dut1_seconds,
    std::uint32_t chunk_size,
    double4* dense) {
    const std::uint64_t chunks_per_object = ceil_div(intervals, chunk_size);
    const std::uint64_t thread = static_cast<std::uint64_t>(blockIdx.x) * blockDim.x + threadIdx.x;
    const std::uint64_t total = static_cast<std::uint64_t>(object_count) * chunks_per_object;
    if (thread >= total) return;
    const std::uint32_t object = static_cast<std::uint32_t>(thread / chunks_per_object);
    const std::uint64_t chunk_index = thread % chunks_per_object;
    const std::uint64_t begin = chunk_index * chunk_size;
    const std::uint64_t end = (intervals < begin + static_cast<std::uint64_t>(chunk_size) ? intervals : begin + static_cast<std::uint64_t>(chunk_size));
    const std::uint64_t stride = intervals + 1u;
    const std::uint64_t base = static_cast<std::uint64_t>(object) * stride;
    const ElsetRec& record = records[object];
    if (begin == 0u) {
        Vec3d position{}; int error = 0;
        const bool ok = propagate_pef(record, reference_jd, dut1_seconds, position, error);
        dense[base] = make_double4(position.x, position.y, position.z,
                                   ok ? 0.0 : static_cast<double>(error == 0 ? -1 : error));
    }
    for (std::uint64_t interval = begin; interval < end; ++interval) {
        const double seconds = static_cast<double>(interval + 1u) * step_seconds;
        Vec3d position{}; int error = 0;
        const bool ok = propagate_pef(record, reference_jd + seconds / 86400.0,
                                      dut1_seconds, position, error);
        dense[base + interval + 1u] = make_double4(
            position.x, position.y, position.z,
            ok ? 0.0 : static_cast<double>(error == 0 ? -1 : error));
    }
}

__global__ void dense_query_kernel(
    const double4* dense,
    const ObjectMeta* meta,
    const klb::NetworkObjectProfile* profiles,
    const klb::NetworkStationGpu* stations,
    std::uint32_t object_count,
    std::uint32_t station_count,
    std::uint32_t pair_mode,
    std::uint64_t intervals,
    double step_seconds,
    const klb::Sgp4TimelineNodeDisk* nodes,
    std::uint32_t node_count,
    GpuCounters* counters,
    GpuEvent* events,
    unsigned long long* event_count,
    unsigned long long event_capacity) {
    const std::uint64_t index = static_cast<std::uint64_t>(blockIdx.x) * blockDim.x + threadIdx.x;
    const std::uint64_t total = static_cast<std::uint64_t>(object_count) * intervals;
    if (index >= total) return;
    const std::uint32_t object = static_cast<std::uint32_t>(index / intervals);
    const std::uint64_t interval = index % intervals;
    const std::uint64_t stride = intervals + 1u;
    const std::uint64_t base = static_cast<std::uint64_t>(object) * stride;
    const double4 a = dense[base + interval];
    const double4 b = dense[base + interval + 1u];
    GpuCounters local{};
    local.propagated_intervals = 0u;
    std::uint32_t mask = station_count == 32u ? 0xffffffffu :
        ((std::uint32_t{1u} << station_count) - 1u);
    const klb::NetworkObjectProfile& profile = profiles[object];
    if (pair_mode == static_cast<std::uint32_t>(klb::NetworkPairMode::Support)) mask = profile.support_station_mask;
    else if (pair_mode == static_cast<std::uint32_t>(klb::NetworkPairMode::Active)) mask = profile.active_station_mask;
    if (a.w != 0.0 || b.w != 0.0) {
        local.propagation_errors = __popc(mask);
        local.relation_intervals = __popc(mask);
        add_counters(counters, local);
        return;
    }
    const Vec3d previous_pef = make_vec(a.x, a.y, a.z);
    const Vec3d current_pef = make_vec(b.x, b.y, b.z);
    const ObjectMeta& object_meta = meta[object];
    while (mask != 0u) {
        const int station_index = __ffs(static_cast<int>(mask)) - 1;
        mask &= mask - 1u;
        const klb::NetworkStationGpu& station = stations[station_index];
        const bool policy = klb::network_policy_compatible(profile, station, object_meta.route);
        const klb::Sgp4Visibility previous = visibility_from_pef(previous_pef, station, policy);
        const klb::Sgp4Visibility current = visibility_from_pef(current_pef, station, policy);
        evaluate_relation(previous, current,
            static_cast<double>(interval) * step_seconds,
            static_cast<double>(interval + 1u) * step_seconds,
            interval, object_meta, station, nodes, node_count,
            local, events, event_count, event_capacity);
    }
    add_counters(counters, local);
}

std::uint32_t grid_for(std::uint64_t work, std::uint32_t block) {
    const std::uint64_t blocks = ceil_div(work, block);
    if (blocks > std::numeric_limits<std::uint32_t>::max()) {
        throw std::runtime_error("CUDA one-dimensional grid limit exceeded");
    }
    return static_cast<std::uint32_t>(blocks);
}

std::vector<PairIndex> make_pairs(const klb::NetworkPlan& plan,
                                  std::size_t station_count,
                                  klb::NetworkPairMode mode) {
    std::vector<PairIndex> pairs;
    for (std::size_t object = 0; object < plan.objects.size(); ++object) {
        std::uint32_t mask = station_count == 32u ? 0xffffffffu :
            ((std::uint32_t{1u} << static_cast<unsigned>(station_count)) - 1u);
        if (mode == klb::NetworkPairMode::Support) mask = plan.objects[object].support_station_mask;
        else if (mode == klb::NetworkPairMode::Active) mask = plan.objects[object].active_station_mask;
        for (std::size_t station = 0; station < station_count; ++station) {
            if ((mask & (std::uint32_t{1u} << static_cast<unsigned>(station))) != 0u) {
                pairs.push_back(PairIndex{static_cast<std::uint32_t>(object), static_cast<std::uint32_t>(station)});
            }
        }
    }
    return pairs;
}

bool event_less(const GpuEvent& a, const GpuEvent& b) {
    return std::tie(a.station_id, a.norad_id, a.interval_index, a.type, a.crossing_seconds) <
           std::tie(b.station_id, b.norad_id, b.interval_index, b.type, b.crossing_seconds);
}

bool events_equal(std::vector<GpuEvent> a, std::vector<GpuEvent> b) {
    if (a.size() != b.size()) return false;
    std::sort(a.begin(), a.end(), event_less);
    std::sort(b.begin(), b.end(), event_less);
    for (std::size_t i = 0; i < a.size(); ++i) {
        if (a[i].station_id != b[i].station_id || a[i].norad_id != b[i].norad_id ||
            a[i].interval_index != b[i].interval_index || a[i].type != b[i].type ||
            a[i].lineage != b[i].lineage ||
            std::fabs(a[i].crossing_seconds - b[i].crossing_seconds) > 1.0e-9 ||
            std::fabs(a[i].minimum_abs_guard - b[i].minimum_abs_guard) > 1.0e-12) return false;
    }
    return true;
}

bool counters_match_events(const GpuCounters& a, const GpuCounters& b) {
    return a.compatible == b.compatible && a.visible_endpoints == b.visible_endpoints &&
           a.boundary_evaluations == b.boundary_evaluations && a.aos == b.aos &&
           a.los == b.los && a.propagation_errors == b.propagation_errors;
}

Timing summarize(std::vector<double> samples, int inner) {
    if (samples.empty()) return {};
    std::sort(samples.begin(), samples.end());
    auto percentile = [&](double p) {
        const std::size_t index = static_cast<std::size_t>(
            std::min<double>(samples.size() - 1u, std::ceil(p * samples.size()) - 1.0));
        return samples[index];
    };
    Timing timing{};
    timing.samples = samples;
    timing.p50 = percentile(0.50);
    timing.p95 = percentile(0.95);
    timing.p99 = percentile(0.99);
    timing.mean = std::accumulate(samples.begin(), samples.end(), 0.0) /
                  static_cast<double>(samples.size());
    timing.inner = inner;
    return timing;
}

template <typename Launch>
Timing time_kernel(Launch&& launch, int repeats, double minimum_ms) {
    cudaEvent_t begin{}, end{};
    CUDA_CHECK(cudaEventCreate(&begin));
    CUDA_CHECK(cudaEventCreate(&end));
    launch();
    CUDA_CHECK(cudaDeviceSynchronize());
    CUDA_CHECK(cudaEventRecord(begin));
    launch();
    CUDA_CHECK(cudaEventRecord(end));
    CUDA_CHECK(cudaEventSynchronize(end));
    float single_ms = 0.0f;
    CUDA_CHECK(cudaEventElapsedTime(&single_ms, begin, end));
    const int inner = std::max(1, static_cast<int>(std::ceil(minimum_ms / std::max(0.001f, single_ms))));
    std::vector<double> samples;
    samples.reserve(static_cast<std::size_t>(repeats));
    for (int repeat = 0; repeat < repeats; ++repeat) {
        CUDA_CHECK(cudaEventRecord(begin));
        for (int i = 0; i < inner; ++i) launch();
        CUDA_CHECK(cudaEventRecord(end));
        CUDA_CHECK(cudaEventSynchronize(end));
        float elapsed = 0.0f;
        CUDA_CHECK(cudaEventElapsedTime(&elapsed, begin, end));
        samples.push_back(static_cast<double>(elapsed) / static_cast<double>(inner));
    }
    CUDA_CHECK(cudaEventDestroy(begin));
    CUDA_CHECK(cudaEventDestroy(end));
    return summarize(samples, inner);
}

Options parse_options(int argc, char** argv) {
    if (argc < 3) {
        throw std::invalid_argument(
            "usage: klb_network_bench input.ksgp stations.csv [--preset smoke|file|laptop] "
            "[--intervals N] [--step-seconds N] [--chunk N] [--repeats N] "
            "[--min-ms N] [--validation-intervals N] [--event-capacity N] "
            "[--skip-dense] [--csv FILE]");
    }
    Options options{};
    options.input = argv[1];
    options.stations = argv[2];
    for (int index = 3; index < argc; ++index) {
        const std::string argument = argv[index];
        auto value = [&]() -> const char* {
            if (++index >= argc) throw std::invalid_argument(argument + " requires a value");
            return argv[index];
        };
        if (argument == "--preset") options.preset = value();
        else if (argument == "--intervals") options.intervals = std::stoull(value());
        else if (argument == "--step-seconds") options.step_seconds = std::stod(value());
        else if (argument == "--chunk") options.chunk = static_cast<std::uint32_t>(std::stoul(value()));
        else if (argument == "--repeats") options.repeats = std::stoi(value());
        else if (argument == "--min-ms") options.min_ms = std::stod(value());
        else if (argument == "--validation-intervals") options.validation_intervals = std::stoull(value());
        else if (argument == "--event-capacity") options.event_capacity = std::stoull(value());
        else if (argument == "--csv") options.csv = value();
        else if (argument == "--skip-dense") options.skip_dense = true;
        else throw std::invalid_argument("unknown option: " + argument);
    }
    if (options.chunk == 0u || options.repeats <= 0 || options.min_ms <= 0.0) {
        throw std::invalid_argument("chunk, repeats, and min-ms must be positive");
    }
    return options;
}

void set_preset(Options& options, const klb::Sgp4Data& data) {
    if (options.intervals != 0u && options.step_seconds > 0.0) return;
    if (options.preset == "smoke") {
        if (options.intervals == 0u) options.intervals = 2048u;
        if (options.step_seconds <= 0.0) options.step_seconds = 60.0;
    } else if (options.preset == "file") {
        if (options.intervals == 0u) options.intervals =
            static_cast<std::uint64_t>(std::floor(data.header.timeline_duration_seconds /
                                                  data.header.timeline_step_seconds));
        if (options.step_seconds <= 0.0) options.step_seconds = data.header.timeline_step_seconds;
    } else if (options.preset == "laptop") {
        if (options.intervals == 0u) options.intervals = 1048576u;
        if (options.step_seconds <= 0.0) options.step_seconds = 1.0;
    } else {
        throw std::invalid_argument("preset must be smoke, file, or laptop");
    }
}

void write_csv(const std::filesystem::path& path,
               const std::string& device,
               const Options& options,
               const klb::NetworkPlan& plan,
               std::uint64_t dense_bytes,
               const std::vector<std::tuple<std::string, Timing, std::uint64_t, std::uint64_t>>& rows) {
    if (path.empty()) return;
    std::ofstream out(path, std::ios::trunc);
    if (!out) throw std::runtime_error("unable to create CSV: " + path.string());
    out << "device,preset,mode,objects,stations,total_pairs,support_pairs,active_pairs,intervals,step_seconds,"
           "relation_intervals,propagated_intervals,dense_bytes,p50_ms,p95_ms,p99_ms,mean_ms,inner_repeats,"
           "logical_relations_per_second,propagations_per_second\n";
    out << std::fixed << std::setprecision(9);
    for (const auto& [name, timing, relations, propagations] : rows) {
        out << '"' << device << "\"," << options.preset << ',' << name << ','
            << plan.stats.objects << ',' << plan.stats.stations << ',' << plan.stats.total_pairs << ','
            << plan.stats.support_pairs << ',' << plan.stats.active_pairs << ',' << options.intervals << ','
            << options.step_seconds << ',' << relations << ',' << propagations << ',' << dense_bytes << ','
            << timing.p50 << ',' << timing.p95 << ',' << timing.p99 << ',' << timing.mean << ',' << timing.inner << ','
            << (timing.p50 > 0.0 ? static_cast<double>(relations) / (timing.p50 * 1.0e-3) : 0.0) << ','
            << (timing.p50 > 0.0 ? static_cast<double>(propagations) / (timing.p50 * 1.0e-3) : 0.0) << '\n';
    }
}

} // namespace

int main(int argc, char** argv) {
    try {
        Options options = parse_options(argc, argv);
        const klb::Sgp4Data data = klb::load_sgp4_data(options.input);
        const std::vector<klb::Sgp4Record> base_records = klb::compile_sgp4_records(data);
        const std::vector<klb::NetworkStation> host_stations = klb::load_network_stations_csv(options.stations);
        const klb::NetworkPlan plan = klb::build_network_plan(data, base_records, host_stations);
        set_preset(options, data);
        options.validation_intervals = std::min(options.validation_intervals, options.intervals);

        int device_id = 0;
        CUDA_CHECK(cudaGetDevice(&device_id));
        cudaDeviceProp properties{};
        CUDA_CHECK(cudaGetDeviceProperties(&properties, device_id));
        std::size_t free_bytes = 0u, total_bytes = 0u;
        CUDA_CHECK(cudaMemGetInfo(&free_bytes, &total_bytes));

        std::vector<ElsetRec> records(base_records.size());
        std::vector<ObjectMeta> meta(data.seeds.size());
        for (std::size_t i = 0; i < base_records.size(); ++i) {
            static_cast<klb::Sgp4Record&>(records[i]) = base_records[i];
            meta[i] = ObjectMeta{data.seeds[i].norad_id, klb::sgp4_seed_route(data.seeds[i]),
                                 data.seeds[i].lineage_seed, 0u};
        }
        std::vector<klb::NetworkStationGpu> stations;
        stations.reserve(host_stations.size());
        for (const auto& station : host_stations) stations.push_back(station.gpu);
        const std::vector<PairIndex> pairs_all = make_pairs(plan, stations.size(), klb::NetworkPairMode::All);
        const std::vector<PairIndex> pairs_support = make_pairs(plan, stations.size(), klb::NetworkPairMode::Support);
        const std::vector<PairIndex> pairs_active = make_pairs(plan, stations.size(), klb::NetworkPairMode::Active);

        ElsetRec* d_records = nullptr;
        ObjectMeta* d_meta = nullptr;
        klb::NetworkObjectProfile* d_profiles = nullptr;
        klb::NetworkStationGpu* d_stations = nullptr;
        klb::Sgp4TimelineNodeDisk* d_nodes = nullptr;
        PairIndex *d_all = nullptr, *d_support = nullptr, *d_active = nullptr;
        GpuCounters* d_counters = nullptr;
        GpuEvent* d_events = nullptr;
        unsigned long long* d_event_count = nullptr;
        CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&d_records), records.size() * sizeof(ElsetRec)));
        CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&d_meta), meta.size() * sizeof(ObjectMeta)));
        CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&d_profiles), plan.objects.size() * sizeof(klb::NetworkObjectProfile)));
        CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&d_stations), stations.size() * sizeof(klb::NetworkStationGpu)));
        if (!data.nodes.empty()) CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&d_nodes), data.nodes.size() * sizeof(klb::Sgp4TimelineNodeDisk)));
        CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&d_all), pairs_all.size() * sizeof(PairIndex)));
        CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&d_support), pairs_support.size() * sizeof(PairIndex)));
        CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&d_active), pairs_active.size() * sizeof(PairIndex)));
        CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&d_counters), sizeof(GpuCounters)));
        CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&d_events), options.event_capacity * sizeof(GpuEvent)));
        CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&d_event_count), sizeof(unsigned long long)));
        CUDA_CHECK(cudaMemcpy(d_records, records.data(), records.size() * sizeof(ElsetRec), cudaMemcpyHostToDevice));
        CUDA_CHECK(cudaMemcpy(d_meta, meta.data(), meta.size() * sizeof(ObjectMeta), cudaMemcpyHostToDevice));
        CUDA_CHECK(cudaMemcpy(d_profiles, plan.objects.data(), plan.objects.size() * sizeof(klb::NetworkObjectProfile), cudaMemcpyHostToDevice));
        CUDA_CHECK(cudaMemcpy(d_stations, stations.data(), stations.size() * sizeof(klb::NetworkStationGpu), cudaMemcpyHostToDevice));
        if (!data.nodes.empty()) CUDA_CHECK(cudaMemcpy(d_nodes, data.nodes.data(), data.nodes.size() * sizeof(klb::Sgp4TimelineNodeDisk), cudaMemcpyHostToDevice));
        CUDA_CHECK(cudaMemcpy(d_all, pairs_all.data(), pairs_all.size() * sizeof(PairIndex), cudaMemcpyHostToDevice));
        CUDA_CHECK(cudaMemcpy(d_support, pairs_support.data(), pairs_support.size() * sizeof(PairIndex), cudaMemcpyHostToDevice));
        CUDA_CHECK(cudaMemcpy(d_active, pairs_active.data(), pairs_active.size() * sizeof(PairIndex), cudaMemcpyHostToDevice));

        constexpr std::uint32_t block = 128u;
        const double reference_jd = data.header.reference_julian_date;
        const double dut1 = data.header.default_dut1_seconds;
        auto launch_pair = [&](const PairIndex* pairs, std::uint32_t count, std::uint64_t intervals,
                               GpuEvent* events = nullptr, unsigned long long* event_count = nullptr) {
            const std::uint64_t threads = static_cast<std::uint64_t>(count) * ceil_div(intervals, options.chunk);
            pair_query_kernel<<<grid_for(threads, block), block>>>(
                d_records, d_meta, d_profiles, d_stations, pairs, count, intervals,
                reference_jd, options.step_seconds, dut1, options.chunk,
                d_nodes, static_cast<std::uint32_t>(data.nodes.size()),
                d_counters, events, event_count, options.event_capacity);
        };
        auto launch_grouped = [&](klb::NetworkPairMode mode, std::uint64_t intervals,
                                  GpuEvent* events = nullptr, unsigned long long* event_count = nullptr) {
            const std::uint64_t threads = records.size() * ceil_div(intervals, options.chunk);
            grouped_query_kernel<<<grid_for(threads, block), block>>>(
                d_records, d_meta, d_profiles, d_stations,
                static_cast<std::uint32_t>(records.size()), static_cast<std::uint32_t>(stations.size()),
                static_cast<std::uint32_t>(mode), intervals, reference_jd,
                options.step_seconds, dut1, options.chunk,
                d_nodes, static_cast<std::uint32_t>(data.nodes.size()),
                d_counters, events, event_count, options.event_capacity);
        };

        auto reset_outputs = [&]() {
            CUDA_CHECK(cudaMemset(d_counters, 0, sizeof(GpuCounters)));
            CUDA_CHECK(cudaMemset(d_event_count, 0, sizeof(unsigned long long)));
        };

        std::vector<std::tuple<std::string, Timing, std::uint64_t, std::uint64_t>> timing_rows;
        auto timed_pair = [&](const char* name, const PairIndex* pairs, std::uint32_t count) {
            reset_outputs();
            Timing timing = time_kernel([&]() { launch_pair(pairs, count, options.intervals); },
                                        options.repeats, options.min_ms);
            timing_rows.emplace_back(name, timing,
                static_cast<std::uint64_t>(count) * options.intervals,
                static_cast<std::uint64_t>(count) * options.intervals);
        };
        timed_pair("pair_all", d_all, static_cast<std::uint32_t>(pairs_all.size()));
        timed_pair("pair_support", d_support, static_cast<std::uint32_t>(pairs_support.size()));
        timed_pair("pair_active", d_active, static_cast<std::uint32_t>(pairs_active.size()));
        auto timed_grouped = [&](const char* name, klb::NetworkPairMode mode, std::uint64_t relations) {
            reset_outputs();
            Timing timing = time_kernel([&]() { launch_grouped(mode, options.intervals); },
                                        options.repeats, options.min_ms);
            timing_rows.emplace_back(name, timing, relations,
                static_cast<std::uint64_t>(records.size()) * options.intervals);
        };
        timed_grouped("grouped_all", klb::NetworkPairMode::All,
                      plan.stats.total_pairs * options.intervals);
        timed_grouped("grouped_active", klb::NetworkPairMode::Active,
                      plan.stats.active_pairs * options.intervals);

        double4* d_dense = nullptr;
        std::uint64_t dense_bytes = 0u;
        if (!options.skip_dense) {
            const long double bytes = static_cast<long double>(records.size()) *
                static_cast<long double>(options.intervals + 1u) * sizeof(double4);
            if (bytes > static_cast<long double>(std::numeric_limits<std::uint64_t>::max()))
                throw std::runtime_error("dense allocation size overflow");
            dense_bytes = static_cast<std::uint64_t>(bytes);
            if (dense_bytes + 512ull * 1024ull * 1024ull > free_bytes) {
                throw std::runtime_error("dense baseline would leave less than 512 MiB free VRAM; use --skip-dense");
            }
            CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&d_dense), dense_bytes));
            const std::uint64_t material_threads = records.size() * ceil_div(options.intervals, options.chunk);
            Timing material = time_kernel([&]() {
                materialize_kernel<<<grid_for(material_threads, block), block>>>(
                    d_records, static_cast<std::uint32_t>(records.size()), options.intervals,
                    reference_jd, options.step_seconds, dut1, options.chunk, d_dense);
            }, options.repeats, options.min_ms);
            timing_rows.emplace_back("materialize_dense", material,
                                     static_cast<std::uint64_t>(records.size()) * options.intervals,
                                     static_cast<std::uint64_t>(records.size()) * options.intervals);
            const std::uint64_t dense_threads = records.size() * options.intervals;
            reset_outputs();
            Timing dense_query = time_kernel([&]() {
                dense_query_kernel<<<grid_for(dense_threads, block), block>>>(
                    d_dense, d_meta, d_profiles, d_stations,
                    static_cast<std::uint32_t>(records.size()), static_cast<std::uint32_t>(stations.size()),
                    static_cast<std::uint32_t>(klb::NetworkPairMode::Active),
                    options.intervals, options.step_seconds,
                    d_nodes, static_cast<std::uint32_t>(data.nodes.size()),
                    d_counters, nullptr, nullptr, 0u);
            }, options.repeats, options.min_ms);
            timing_rows.emplace_back("query_dense_active", dense_query,
                                     plan.stats.active_pairs * options.intervals, 0u);
        }

        auto collect_events = [&](auto&& launch) {
            reset_outputs();
            launch();
            CUDA_CHECK(cudaGetLastError());
            CUDA_CHECK(cudaDeviceSynchronize());
            GpuCounters counters{};
            unsigned long long count = 0u;
            CUDA_CHECK(cudaMemcpy(&counters, d_counters, sizeof(counters), cudaMemcpyDeviceToHost));
            CUDA_CHECK(cudaMemcpy(&count, d_event_count, sizeof(count), cudaMemcpyDeviceToHost));
            if (count > options.event_capacity) throw std::runtime_error("GPU event buffer truncated");
            std::vector<GpuEvent> events(static_cast<std::size_t>(count));
            if (count != 0u) CUDA_CHECK(cudaMemcpy(events.data(), d_events,
                static_cast<std::size_t>(count) * sizeof(GpuEvent), cudaMemcpyDeviceToHost));
            return std::pair<GpuCounters, std::vector<GpuEvent>>(counters, std::move(events));
        };

        const std::uint64_t v = options.validation_intervals;
        const auto pair_all_validation = collect_events([&]() {
            launch_pair(d_all, static_cast<std::uint32_t>(pairs_all.size()), v, d_events, d_event_count);
        });
        const auto pair_active_validation = collect_events([&]() {
            launch_pair(d_active, static_cast<std::uint32_t>(pairs_active.size()), v, d_events, d_event_count);
        });
        const auto grouped_active_validation = collect_events([&]() {
            launch_grouped(klb::NetworkPairMode::Active, v, d_events, d_event_count);
        });
        bool dense_validation_available = d_dense != nullptr && v == options.intervals;
        std::pair<GpuCounters, std::vector<GpuEvent>> dense_active_validation{};
        if (dense_validation_available) {
            dense_active_validation = collect_events([&]() {
                const std::uint64_t threads = records.size() * v;
                dense_query_kernel<<<grid_for(threads, block), block>>>(
                    d_dense, d_meta, d_profiles, d_stations,
                    static_cast<std::uint32_t>(records.size()), static_cast<std::uint32_t>(stations.size()),
                    static_cast<std::uint32_t>(klb::NetworkPairMode::Active),
                    v, options.step_seconds, d_nodes, static_cast<std::uint32_t>(data.nodes.size()),
                    d_counters, d_events, d_event_count, options.event_capacity);
            });
        }

        const klb::NetworkRunResult cpu_all = klb::run_network_cpu(
            data, base_records, host_stations, plan, klb::NetworkPairMode::All,
            0.0, static_cast<double>(v) * options.step_seconds,
            options.step_seconds, dut1);
        const klb::NetworkRunResult cpu_active = klb::run_network_cpu(
            data, base_records, host_stations, plan, klb::NetworkPairMode::Active,
            0.0, static_cast<double>(v) * options.step_seconds,
            options.step_seconds, dut1);

        auto cpu_to_gpu = [](const klb::NetworkRunResult& cpu) {
            std::vector<GpuEvent> output;
            output.reserve(cpu.events.size());
            for (const auto& event : cpu.events) {
                output.push_back(GpuEvent{event.station_id, event.norad_id,
                    static_cast<std::uint32_t>(event.interval_index), event.type,
                    event.lineage, 0u, event.crossing_seconds, event.minimum_abs_guard});
            }
            return output;
        };
        const std::vector<GpuEvent> cpu_all_events = cpu_to_gpu(cpu_all);
        const std::vector<GpuEvent> cpu_active_events = cpu_to_gpu(cpu_active);
        const bool pair_all_cpu_match = events_equal(pair_all_validation.second, cpu_all_events);
        const bool pair_active_cpu_match = events_equal(pair_active_validation.second, cpu_active_events);
        const bool pair_grouped_match = events_equal(pair_active_validation.second, grouped_active_validation.second);
        const bool pair_counter_match = counters_match_events(pair_active_validation.first, grouped_active_validation.first);
        const bool dense_event_match = !dense_validation_available ||
            events_equal(grouped_active_validation.second, dense_active_validation.second);
        const bool dense_counter_match = !dense_validation_available ||
            counters_match_events(grouped_active_validation.first, dense_active_validation.first);
        const bool failures_zero = pair_all_validation.first.propagation_errors == 0u &&
            pair_active_validation.first.propagation_errors == 0u &&
            grouped_active_validation.first.propagation_errors == 0u &&
            (!dense_validation_available || dense_active_validation.first.propagation_errors == 0u);

        std::cout << std::fixed << std::setprecision(6)
                  << "KLB mixed-orbit network GPU challenge\n"
                  << "  device                    : " << properties.name << '\n'
                  << "  compute capability        : " << properties.major << '.' << properties.minor << '\n'
                  << "  objects/stations          : " << records.size() << '/' << stations.size() << '\n'
                  << "  pair plan                 : all=" << plan.stats.total_pairs
                  << ", support=" << plan.stats.support_pairs
                  << ", active=" << plan.stats.active_pairs << '\n'
                  << "  total relation gain       : " << plan.stats.total_rejection_gain << "x\n"
                  << "  intervals/step            : " << options.intervals << '/' << options.step_seconds << " s\n"
                  << "  dense baseline            : " << dense_bytes / (1024.0 * 1024.0) << " MiB\n";
        for (const auto& [name, timing, relations, propagations] : timing_rows) {
            std::cout << "  " << std::setw(22) << std::left << name
                      << " p50=" << std::setw(11) << timing.p50 << " ms"
                      << "  relations/s=" << (timing.p50 > 0.0 ? relations / (timing.p50 * 1.0e-3) : 0.0)
                      << "  propagations/s=" << (timing.p50 > 0.0 ? propagations / (timing.p50 * 1.0e-3) : 0.0)
                      << '\n';
        }
        std::cout << "Validation over " << v << " intervals\n"
                  << "  pair-all vs CPU events    : " << (pair_all_cpu_match ? "PASS" : "FAIL") << '\n'
                  << "  pair-active vs CPU events : " << (pair_active_cpu_match ? "PASS" : "FAIL") << '\n'
                  << "  pair vs grouped events    : " << (pair_grouped_match ? "PASS" : "FAIL") << '\n'
                  << "  pair vs grouped counters  : " << (pair_counter_match ? "PASS" : "FAIL") << '\n'
                  << "  grouped vs dense events   : " << (dense_validation_available ? (dense_event_match ? "PASS" : "FAIL") : "SKIP") << '\n'
                  << "  grouped vs dense counters : " << (dense_validation_available ? (dense_counter_match ? "PASS" : "FAIL") : "SKIP") << '\n'
                  << "  propagation errors zero   : " << (failures_zero ? "PASS" : "FAIL") << '\n';

        write_csv(options.csv, properties.name, options, plan, dense_bytes, timing_rows);

        if (d_dense) CUDA_CHECK(cudaFree(d_dense));
        CUDA_CHECK(cudaFree(d_event_count));
        CUDA_CHECK(cudaFree(d_events));
        CUDA_CHECK(cudaFree(d_counters));
        CUDA_CHECK(cudaFree(d_active));
        CUDA_CHECK(cudaFree(d_support));
        CUDA_CHECK(cudaFree(d_all));
        if (d_nodes) CUDA_CHECK(cudaFree(d_nodes));
        CUDA_CHECK(cudaFree(d_stations));
        CUDA_CHECK(cudaFree(d_profiles));
        CUDA_CHECK(cudaFree(d_meta));
        CUDA_CHECK(cudaFree(d_records));

        return pair_all_cpu_match && pair_active_cpu_match && pair_grouped_match &&
               pair_counter_match && dense_event_match && dense_counter_match && failures_zero ? 0 : 1;
    } catch (const std::exception& error) {
        std::cerr << "error: " << error.what() << '\n';
        return 1;
    }
}
