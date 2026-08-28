#include <cstdlib>
#include <cuda_runtime.h>

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <numeric>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <unordered_map>
#include <utility>
#include <vector>

#include "klb/sgp4_gpu_compat.hpp"

namespace {

#define CUDA_CHECK(call)                                                        \
    do {                                                                        \
        const cudaError_t error__ = (call);                                     \
        if (error__ != cudaSuccess) {                                           \
            std::ostringstream message__;                                       \
            message__ << "CUDA error " << cudaGetErrorName(error__)             \
                      << " (" << cudaGetErrorString(error__) << ") at "          \
                      << __FILE__ << ":" << __LINE__;                            \
            throw std::runtime_error(message__.str());                          \
        }                                                                       \
    } while (0)

#if defined(__CUDACC__) || defined(__CUDA__)
#define KLB_HD __host__ __device__
#else
#define KLB_HD
#endif

struct Vec3d {
    double x;
    double y;
    double z;
};

using Station = klb::Sgp4GroundStation;
using Visibility = klb::Sgp4Visibility;

struct ObjectMeta {
    std::uint32_t norad_id;
    std::uint32_t route;
    std::uint32_t lineage_seed;
    std::uint32_t reserved;
};

struct Counters {
    unsigned long long intervals = 0;
    unsigned long long supported = 0;
    unsigned long long compatible = 0;
    unsigned long long visible_endpoints = 0;
    unsigned long long aos = 0;
    unsigned long long los = 0;
    unsigned long long propagation_errors = 0;
    unsigned long long boundary_evaluations = 0;
};

struct Event {
    std::uint32_t norad_id;
    // Canonical KSGP1 interval index (zero based), despite the legacy member
    // name retained for CSV/backward-compatibility with the v0.4 harness.
    std::uint32_t time_index;
    std::uint32_t type;  // 1 acquire/AOS, 2 loss/LOS
    std::uint32_t route;
    std::uint64_t lineage;  // canonical 32-bit checksum in the low word
    double guard;           // minimum absolute guard at the sampled endpoints
    double crossing_seconds;
};
static_assert(sizeof(Event) == 40, "Event ABI changed");

struct PvOutput {
    double r[3];
    double v[3];
    std::int32_t error;
    std::int32_t method;
};
static_assert(sizeof(PvOutput) == 56, "PvOutput ABI changed");

struct Options {
    std::string input;
    std::string preset = "file";
    std::string csv_path;
    std::string expected_events_path;
    std::uint64_t intervals = 0;
    double step_seconds = 0.0;
    std::uint32_t chunk = 256;
    int repeats = 7;
    double min_ms = 150.0;
    std::uint64_t event_capacity = 1000000;
    std::uint64_t cpu_prefix_intervals = 2048;
    bool skip_dense = false;
    bool skip_events = false;
    bool validation_only = false;
};

struct TimingStats {
    std::vector<double> samples_ms;
    double p50 = 0.0;
    double p95 = 0.0;
    double p99 = 0.0;
    double mean = 0.0;
    int inner = 1;
};

template <typename T>
KLB_HD T klb_min(T a, T b) {
    return a < b ? a : b;
}

KLB_HD Vec3d make_vec(double x, double y, double z) {
    return Vec3d{x, y, z};
}

KLB_HD Visibility visibility_from_pef(
    Vec3d satellite_pef,
    const Station& station,
    std::uint32_t route_sector) {
    const double dx = satellite_pef.x - station.ecef_km[0];
    const double dy = satellite_pef.y - station.ecef_km[1];
    const double dz = satellite_pef.z - station.ecef_km[2];
    const double range = sqrt(dx * dx + dy * dy + dz * dz);
    const double elevation_sin = range > 1.0e-12
        ? (dx * station.up_unit[0] + dy * station.up_unit[1] +
           dz * station.up_unit[2]) / range
        : 1.0;
    const bool route_ok = station.route_filter == 0xffffffffu ||
                          station.route_filter == route_sector;
    const bool support = range <= station.maximum_slant_range_km;
    return Visibility{
        station.elevation_mask_sin - elevation_sin,
        elevation_sin,
        range,
        support ? 1u : 0u,
        route_ok ? 1u : 0u,
    };
}

KLB_HD bool propagate_pef(const ElsetRec& rec,
                          double absolute_jd_utc,
                          double dut1_seconds,
                          Vec3d& pef,
                          int& error) {
    const double epoch_jd = rec.jdsatepoch + rec.jdsatepochF;
    const double minutes_since_epoch =
        (absolute_jd_utc - epoch_jd) * 1440.0;
    double r[3]{};
    double v[3]{};
    const bool ok = klb::sgp4_propagate_immutable(
        static_cast<const klb::Sgp4Record&>(rec),
        minutes_since_epoch, r, v, &error);
    if (!ok || error != 0) {
        pef = make_vec(0.0, 0.0, 0.0);
        return false;
    }
    double out[3]{};
    klb::sgp4_teme_to_pef(
        r, absolute_jd_utc + dut1_seconds / 86400.0, out);
    pef = make_vec(out[0], out[1], out[2]);
    return true;
}

KLB_HD std::uint64_t event_lineage(std::uint64_t node_chain_seed,
                                    const ObjectMeta& meta,
                                    std::uint64_t interval_index,
                                    std::uint32_t type) {
    const std::uint32_t lo = static_cast<std::uint32_t>(interval_index);
    const std::uint32_t hi = static_cast<std::uint32_t>(interval_index >> 32u);
    return static_cast<std::uint64_t>(klb::mix32(
        meta.lineage_seed ^ static_cast<std::uint32_t>(node_chain_seed) ^
        lo ^ klb::mix32(hi) ^ (type * 0x9e3779b9u)));
}

Station make_station(double latitude_deg,
                     double longitude_deg,
                     double altitude_km,
                     double elevation_guard_deg,
                     double crossing_band_deg,
                     double maximum_slant_range_km,
                     std::uint32_t route_filter = 0xffffffffu) {
    return klb::make_sgp4_ground_station(
        latitude_deg, longitude_deg, altitude_km,
        elevation_guard_deg, crossing_band_deg,
        maximum_slant_range_km, route_filter);
}

__device__ void add_counters(Counters* out, const Counters& local) {
    if (!out) {
        return;
    }
    if (local.intervals) {
        atomicAdd(&out->intervals, local.intervals);
    }
    if (local.supported) {
        atomicAdd(&out->supported, local.supported);
    }
    if (local.compatible) {
        atomicAdd(&out->compatible, local.compatible);
    }
    if (local.visible_endpoints) {
        atomicAdd(&out->visible_endpoints, local.visible_endpoints);
    }
    if (local.aos) {
        atomicAdd(&out->aos, local.aos);
    }
    if (local.los) {
        atomicAdd(&out->los, local.los);
    }
    if (local.propagation_errors) {
        atomicAdd(&out->propagation_errors, local.propagation_errors);
    }
    if (local.boundary_evaluations) {
        atomicAdd(&out->boundary_evaluations, local.boundary_evaluations);
    }
}

__device__ void append_event(Event* events,
                             unsigned long long* event_count,
                             unsigned long long capacity,
                             const Event& event) {
    if (!events || !event_count) {
        return;
    }
    const auto index = atomicAdd(event_count, 1ull);
    if (index < capacity) {
        events[index] = event;
    }
}

__global__ void validate_states_kernel(
    const ElsetRec* records,
    std::uint32_t object_count,
    const double* minutes,
    std::uint32_t time_count,
    PvOutput* output) {
    const std::uint64_t index =
        static_cast<std::uint64_t>(blockIdx.x) * blockDim.x + threadIdx.x;
    const std::uint64_t total =
        static_cast<std::uint64_t>(object_count) * time_count;
    if (index >= total) {
        return;
    }
    const std::uint32_t object =
        static_cast<std::uint32_t>(index / time_count);
    const std::uint32_t time_index =
        static_cast<std::uint32_t>(index % time_count);

    const ElsetRec& rec = records[object];
    double r[3]{};
    double v[3]{};
    int propagation_error = 0;
    const bool ok = klb::sgp4_propagate_immutable(
        static_cast<const klb::Sgp4Record&>(rec),
        minutes[time_index], r, v, &propagation_error);
    PvOutput value{};
    value.r[0] = r[0];
    value.r[1] = r[1];
    value.r[2] = r[2];
    value.v[0] = v[0];
    value.v[1] = v[1];
    value.v[2] = v[2];
    value.error = ok ? propagation_error :
        (propagation_error != 0 ? propagation_error : -1);
    value.method = static_cast<std::int32_t>(records[object].method);
    output[index] = value;
}

__global__ void query_seed_chunked_kernel(
    const ElsetRec* records,
    const ObjectMeta* meta,
    std::uint32_t object_count,
    std::uint64_t intervals,
    double reference_jd,
    double step_seconds,
    double dut1_seconds,
    std::uint32_t chunk_size,
    Station station,
    const std::uint64_t* node_chain_seeds,
    std::uint32_t node_count,
    double node_seconds,
    Counters* counters,
    Event* events,
    unsigned long long* event_count,
    unsigned long long event_capacity) {
    const std::uint64_t chunks_per_object =
        (intervals + chunk_size - 1ull) / chunk_size;
    const std::uint64_t thread =
        static_cast<std::uint64_t>(blockIdx.x) * blockDim.x + threadIdx.x;
    const std::uint64_t total_threads =
        chunks_per_object * static_cast<std::uint64_t>(object_count);
    if (thread >= total_threads) return;

    const std::uint32_t object =
        static_cast<std::uint32_t>(thread / chunks_per_object);
    const std::uint64_t chunk_index = thread % chunks_per_object;
    const std::uint64_t begin = chunk_index * chunk_size;
    const std::uint64_t end =
        klb_min(intervals, begin + static_cast<std::uint64_t>(chunk_size));

    const ElsetRec& rec = records[object];
    Vec3d previous_pef{};
    int previous_error = 0;
    const double previous_seconds = static_cast<double>(begin) * step_seconds;
    const double begin_jd = reference_jd + previous_seconds / 86400.0;
    bool previous_ok = propagate_pef(
        rec, begin_jd, dut1_seconds, previous_pef, previous_error);
    Visibility previous{};
    if (previous_ok) {
        previous = visibility_from_pef(
            previous_pef, station, meta[object].route);
    }

    Counters local{};
    for (std::uint64_t interval_index = begin;
         interval_index < end;
         ++interval_index) {
        const double current_seconds =
            static_cast<double>(interval_index + 1ull) * step_seconds;
        const double current_jd = reference_jd + current_seconds / 86400.0;
        Vec3d current_pef{};
        int current_error = 0;
        const bool current_ok = propagate_pef(
            rec, current_jd, dut1_seconds, current_pef, current_error);
        Visibility current{};
        if (current_ok) {
            current = visibility_from_pef(
                current_pef, station, meta[object].route);
        }

        ++local.intervals;
        const bool valid_pair = previous_ok && current_ok;
        if (valid_pair) {
            const bool supported =
                previous.supported != 0u || current.supported != 0u;
            const bool compatible =
                supported && previous.compatible != 0u &&
                current.compatible != 0u;
            if (supported) ++local.supported;
            if (compatible) {
                ++local.compatible;
                ++local.boundary_evaluations;
            }
            if (current.supported != 0u && current.compatible != 0u &&
                current.guard <= 0.0) {
                ++local.visible_endpoints;
            }

            const klb::Sgp4Crossing crossing = klb::sgp4_evaluate_crossing(
                previous, current,
                static_cast<double>(interval_index) * step_seconds,
                current_seconds,
                station.crossing_band_sin);
            if (crossing.verified != 0u) {
                const std::uint32_t type =
                    crossing.acquisition != 0u ? 1u : 2u;
                if (type == 1u) ++local.aos;
                else ++local.los;

                if (events && event_count) {
                    std::uint32_t node_index = 0u;
                    if (node_count != 0u && node_seconds > 0.0) {
                        double local_seconds = crossing.crossing_seconds;
                        const double chain_duration =
                            node_seconds * static_cast<double>(node_count);
                        if (chain_duration > 0.0) {
                            local_seconds = fmod(local_seconds, chain_duration);
                            if (local_seconds < 0.0) local_seconds += chain_duration;
                        }
                        const auto candidate = static_cast<std::uint64_t>(
                            local_seconds / node_seconds);
                        node_index = static_cast<std::uint32_t>(klb_min(
                            candidate,
                            static_cast<std::uint64_t>(node_count - 1u)));
                    }
                    const std::uint64_t chain_seed =
                        node_count == 0u ? 0ull : node_chain_seeds[node_index];
                    Event event{};
                    event.norad_id = meta[object].norad_id;
                    event.time_index =
                        static_cast<std::uint32_t>(interval_index);
                    event.type = type;
                    event.route = meta[object].route;
                    event.lineage = event_lineage(
                        chain_seed, meta[object], interval_index, type);
                    event.guard = crossing.minimum_abs_guard;
                    event.crossing_seconds = crossing.crossing_seconds;
                    append_event(
                        events, event_count, event_capacity, event);
                }
            }
        } else {
            ++local.propagation_errors;
        }

        previous_pef = current_pef;
        previous_ok = current_ok;
        previous_error = current_error;
        previous = current;
    }
    add_counters(counters, local);
}

__global__ void materialize_pef_chunked_kernel(
    const ElsetRec* records,
    std::uint32_t object_count,
    std::uint64_t intervals,
    double reference_jd,
    double step_seconds,
    double dut1_seconds,
    std::uint32_t chunk_size,
    double4* dense) {
    const std::uint64_t chunks_per_object =
        (intervals + chunk_size - 1ull) / chunk_size;
    const std::uint64_t thread =
        static_cast<std::uint64_t>(blockIdx.x) * blockDim.x + threadIdx.x;
    const std::uint64_t total_threads =
        chunks_per_object * static_cast<std::uint64_t>(object_count);
    if (thread >= total_threads) return;

    const std::uint32_t object =
        static_cast<std::uint32_t>(thread / chunks_per_object);
    const std::uint64_t chunk_index = thread % chunks_per_object;
    const std::uint64_t begin = chunk_index * chunk_size;
    const std::uint64_t end =
        klb_min(intervals, begin + static_cast<std::uint64_t>(chunk_size));
    const std::uint64_t stride = intervals + 1ull;
    const std::uint64_t base = static_cast<std::uint64_t>(object) * stride;

    const ElsetRec& rec = records[object];
    Vec3d state{};
    int error = 0;
    const double begin_seconds = static_cast<double>(begin) * step_seconds;
    const double begin_jd = reference_jd + begin_seconds / 86400.0;
    const bool begin_ok = propagate_pef(
        rec, begin_jd, dut1_seconds, state, error);
    if (begin == 0u) {
        dense[base] = make_double4(
            state.x, state.y, state.z,
            begin_ok ? 0.0 : static_cast<double>(error == 0 ? -1 : error));
    }

    for (std::uint64_t interval_index = begin;
         interval_index < end;
         ++interval_index) {
        const double current_seconds =
            static_cast<double>(interval_index + 1ull) * step_seconds;
        const double current_jd = reference_jd + current_seconds / 86400.0;
        const bool ok = propagate_pef(
            rec, current_jd, dut1_seconds, state, error);
        dense[base + interval_index + 1ull] = make_double4(
            state.x, state.y, state.z,
            ok ? 0.0 : static_cast<double>(error == 0 ? -1 : error));
    }
}

__global__ void query_dense_kernel(
    const double4* dense,
    const ObjectMeta* meta,
    std::uint32_t object_count,
    std::uint64_t intervals,
    double step_seconds,
    Station station,
    const std::uint64_t* node_chain_seeds,
    std::uint32_t node_count,
    double node_seconds,
    Counters* counters,
    Event* events,
    unsigned long long* event_count,
    unsigned long long event_capacity) {
    const std::uint64_t index =
        static_cast<std::uint64_t>(blockIdx.x) * blockDim.x + threadIdx.x;
    const std::uint64_t total = intervals * object_count;
    if (index >= total) return;

    const std::uint32_t object =
        static_cast<std::uint32_t>(index / intervals);
    const std::uint64_t interval_index = index % intervals;
    const std::uint64_t stride = intervals + 1ull;
    const std::uint64_t base = static_cast<std::uint64_t>(object) * stride;
    const double4 a = dense[base + interval_index];
    const double4 b = dense[base + interval_index + 1ull];

    Counters local{};
    local.intervals = 1u;
    if (a.w == 0.0 && b.w == 0.0) {
        const Visibility previous = visibility_from_pef(
            make_vec(a.x, a.y, a.z), station, meta[object].route);
        const Visibility current = visibility_from_pef(
            make_vec(b.x, b.y, b.z), station, meta[object].route);
        const bool supported =
            previous.supported != 0u || current.supported != 0u;
        const bool compatible =
            supported && previous.compatible != 0u &&
            current.compatible != 0u;
        if (supported) local.supported = 1u;
        if (compatible) {
            local.compatible = 1u;
            local.boundary_evaluations = 1u;
        }
        if (current.supported != 0u && current.compatible != 0u &&
            current.guard <= 0.0) {
            local.visible_endpoints = 1u;
        }

        const double current_seconds =
            static_cast<double>(interval_index + 1ull) * step_seconds;
        const klb::Sgp4Crossing crossing = klb::sgp4_evaluate_crossing(
            previous, current,
            static_cast<double>(interval_index) * step_seconds,
            current_seconds,
            station.crossing_band_sin);
        if (crossing.verified != 0u) {
            const std::uint32_t type =
                crossing.acquisition != 0u ? 1u : 2u;
            if (type == 1u) local.aos = 1u;
            else local.los = 1u;
            if (events && event_count) {
                std::uint32_t node_index = 0u;
                if (node_count != 0u && node_seconds > 0.0) {
                    double local_seconds = crossing.crossing_seconds;
                    const double chain_duration =
                        node_seconds * static_cast<double>(node_count);
                    if (chain_duration > 0.0) {
                        local_seconds = fmod(local_seconds, chain_duration);
                        if (local_seconds < 0.0) local_seconds += chain_duration;
                    }
                    const auto candidate = static_cast<std::uint64_t>(
                        local_seconds / node_seconds);
                    node_index = static_cast<std::uint32_t>(klb_min(
                        candidate,
                        static_cast<std::uint64_t>(node_count - 1u)));
                }
                const std::uint64_t chain_seed =
                    node_count == 0u ? 0ull : node_chain_seeds[node_index];
                Event event{};
                event.norad_id = meta[object].norad_id;
                event.time_index =
                    static_cast<std::uint32_t>(interval_index);
                event.type = type;
                event.route = meta[object].route;
                event.lineage = event_lineage(
                    chain_seed, meta[object], interval_index, type);
                event.guard = crossing.minimum_abs_guard;
                event.crossing_seconds = crossing.crossing_seconds;
                append_event(
                    events, event_count, event_capacity, event);
            }
        }
    } else {
        local.propagation_errors = 1u;
    }
    add_counters(counters, local);
}

std::uint64_t ceil_div(std::uint64_t a, std::uint64_t b) {
    return (a + b - 1ull) / b;
}

std::uint32_t grid_for(std::uint64_t work, std::uint32_t block) {
    const auto blocks = ceil_div(work, block);
    if (blocks > std::numeric_limits<std::uint32_t>::max()) {
        throw std::runtime_error("CUDA grid exceeds one-dimensional limit");
    }
    return static_cast<std::uint32_t>(blocks);
}

bool counters_equal(const Counters& a, const Counters& b) {
    return a.intervals == b.intervals &&
           a.supported == b.supported &&
           a.compatible == b.compatible &&
           a.visible_endpoints == b.visible_endpoints &&
           a.aos == b.aos &&
           a.los == b.los &&
           a.propagation_errors == b.propagation_errors &&
           a.boundary_evaluations == b.boundary_evaluations;
}

void print_counters(const char* label, const Counters& c) {
    std::cout << label << "\n";
    std::cout << "  intervals              " << c.intervals << "\n";
    std::cout << "  supported              " << c.supported << "\n";
    std::cout << "  compatible             " << c.compatible << "\n";
    std::cout << "  boundary evaluations   " << c.boundary_evaluations << "\n";
    std::cout << "  visible endpoints      " << c.visible_endpoints << "\n";
    std::cout << "  AOS                    " << c.aos << "\n";
    std::cout << "  LOS                    " << c.los << "\n";
    std::cout << "  propagation errors     " << c.propagation_errors << "\n";
}

Counters cpu_query_prefix(const std::vector<ElsetRec>& records,
                          const std::vector<ObjectMeta>& meta,
                          std::uint64_t intervals,
                          double reference_jd,
                          double step_seconds,
                          double dut1_seconds,
                          const Station& station) {
    Counters counters{};
    for (std::size_t object = 0; object < records.size(); ++object) {
        const ElsetRec& rec = records[object];
        Vec3d previous_pef{};
        int previous_error = 0;
        bool previous_ok = propagate_pef(
            rec, reference_jd, dut1_seconds,
            previous_pef, previous_error);
        Visibility previous{};
        if (previous_ok) {
            previous = visibility_from_pef(
                previous_pef, station, meta[object].route);
        }

        for (std::uint64_t interval_index = 0;
             interval_index < intervals;
             ++interval_index) {
            Vec3d current_pef{};
            int current_error = 0;
            const double current_seconds =
                static_cast<double>(interval_index + 1ull) * step_seconds;
            const bool current_ok = propagate_pef(
                rec,
                reference_jd + current_seconds / 86400.0,
                dut1_seconds,
                current_pef,
                current_error);
            Visibility current{};
            if (current_ok) {
                current = visibility_from_pef(
                    current_pef, station, meta[object].route);
            }

            ++counters.intervals;
            const bool valid_pair = previous_ok && current_ok;
            if (valid_pair) {
                const bool supported =
                    previous.supported != 0u || current.supported != 0u;
                const bool compatible =
                    supported && previous.compatible != 0u &&
                    current.compatible != 0u;
                if (supported) ++counters.supported;
                if (compatible) {
                    ++counters.compatible;
                    ++counters.boundary_evaluations;
                }
                if (current.supported != 0u && current.compatible != 0u &&
                    current.guard <= 0.0) {
                    ++counters.visible_endpoints;
                }
                const klb::Sgp4Crossing crossing =
                    klb::sgp4_evaluate_crossing(
                        previous, current,
                        static_cast<double>(interval_index) * step_seconds,
                        current_seconds,
                        station.crossing_band_sin);
                if (crossing.verified != 0u) {
                    if (crossing.acquisition != 0u) ++counters.aos;
                    else ++counters.los;
                }
            } else {
                ++counters.propagation_errors;
            }

            previous_pef = current_pef;
            previous_ok = current_ok;
            previous_error = current_error;
            previous = current;
        }
    }
    return counters;
}

double percentile(std::vector<double> values, double p) {
    if (values.empty()) {
        return 0.0;
    }
    std::sort(values.begin(), values.end());
    const double position = p * static_cast<double>(values.size() - 1);
    const auto lower = static_cast<std::size_t>(std::floor(position));
    const auto upper = static_cast<std::size_t>(std::ceil(position));
    if (lower == upper) {
        return values[lower];
    }
    const double weight = position - static_cast<double>(lower);
    return values[lower] * (1.0 - weight) + values[upper] * weight;
}

template <typename Launch>
TimingStats time_kernel(Launch launch, int repeats, double min_ms) {
    CUDA_CHECK(cudaDeviceSynchronize());
    launch();
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
    float first_ms = 0.0f;
    CUDA_CHECK(cudaEventElapsedTime(&first_ms, start, stop));
    const int inner = std::max(
        1, static_cast<int>(std::ceil(min_ms / std::max(0.001f, first_ms))));

    TimingStats stats;
    stats.inner = inner;
    stats.samples_ms.reserve(static_cast<std::size_t>(repeats));
    for (int repeat = 0; repeat < repeats; ++repeat) {
        CUDA_CHECK(cudaEventRecord(start));
        for (int i = 0; i < inner; ++i) {
            launch();
        }
        CUDA_CHECK(cudaEventRecord(stop));
        CUDA_CHECK(cudaEventSynchronize(stop));
        float elapsed = 0.0f;
        CUDA_CHECK(cudaEventElapsedTime(&elapsed, start, stop));
        stats.samples_ms.push_back(
            static_cast<double>(elapsed) / static_cast<double>(inner));
    }
    CUDA_CHECK(cudaEventDestroy(start));
    CUDA_CHECK(cudaEventDestroy(stop));

    stats.p50 = percentile(stats.samples_ms, 0.50);
    stats.p95 = percentile(stats.samples_ms, 0.95);
    stats.p99 = percentile(stats.samples_ms, 0.99);
    stats.mean = std::accumulate(
        stats.samples_ms.begin(), stats.samples_ms.end(), 0.0) /
        static_cast<double>(stats.samples_ms.size());
    return stats;
}

void print_timing(const char* name, const TimingStats& stats) {
    std::cout << std::fixed << std::setprecision(6);
    std::cout << name << "\n";
    std::cout << "  inner repeats          " << stats.inner << "\n";
    std::cout << "  p50 ms                 " << stats.p50 << "\n";
    std::cout << "  p95 ms                 " << stats.p95 << "\n";
    std::cout << "  p99 ms                 " << stats.p99 << "\n";
    std::cout << "  mean ms                " << stats.mean << "\n";
}

Options parse_options(int argc, char** argv) {
    if (argc < 2) {
        throw std::runtime_error(
            "usage: klb_sgp4_bench <file.ksgp> [--preset smoke|file|laptop] "
            "[--intervals N] [--step S] [--chunk N] [--repeats N] "
            "[--min-ms N] [--cpu-prefix N] [--event-capacity N] "
            "[--csv path] [--expected-events path] [--skip-dense] "
            "[--skip-events] [--validation-only]");
    }
    Options options;
    options.input = argv[1];
    for (int i = 2; i < argc; ++i) {
        const std::string arg = argv[i];
        auto value = [&](const char* name) -> std::string {
            if (i + 1 >= argc) {
                throw std::runtime_error(std::string("missing value for ") + name);
            }
            return argv[++i];
        };
        if (arg == "--preset") {
            options.preset = value("--preset");
        } else if (arg == "--intervals") {
            options.intervals = std::stoull(value("--intervals"));
        } else if (arg == "--step") {
            options.step_seconds = std::stod(value("--step"));
        } else if (arg == "--chunk") {
            options.chunk = static_cast<std::uint32_t>(
                std::stoul(value("--chunk")));
        } else if (arg == "--repeats") {
            options.repeats = std::stoi(value("--repeats"));
        } else if (arg == "--min-ms") {
            options.min_ms = std::stod(value("--min-ms"));
        } else if (arg == "--cpu-prefix") {
            options.cpu_prefix_intervals =
                std::stoull(value("--cpu-prefix"));
        } else if (arg == "--event-capacity") {
            options.event_capacity =
                std::stoull(value("--event-capacity"));
        } else if (arg == "--csv") {
            options.csv_path = value("--csv");
        } else if (arg == "--expected-events") {
            options.expected_events_path = value("--expected-events");
        } else if (arg == "--skip-dense") {
            options.skip_dense = true;
        } else if (arg == "--skip-events") {
            options.skip_events = true;
        } else if (arg == "--validation-only") {
            options.validation_only = true;
        } else {
            throw std::runtime_error("unknown option " + arg);
        }
    }
    if (options.chunk == 0 || options.repeats <= 0 ||
        options.min_ms <= 0.0 || options.event_capacity == 0) {
        throw std::runtime_error("numeric options must be positive");
    }
    return options;
}

std::uint64_t preset_intervals(const Options& options,
                               const ksgp::Container& container,
                               double step_seconds) {
    if (options.intervals != 0) {
        return options.intervals;
    }
    if (options.preset == "smoke") {
        return 8192;
    }
    if (options.preset == "file") {
        return static_cast<std::uint64_t>(
            std::floor(container.header.horizon_seconds / step_seconds));
    }
    if (options.preset == "laptop") {
        return 1048576;
    }
    throw std::runtime_error("unknown preset " + options.preset);
}

std::vector<ObjectMeta> make_meta(const ksgp::Container& container) {
    std::vector<ObjectMeta> meta;
    meta.reserve(container.seeds.size());
    for (const auto& seed : container.seeds) {
        ObjectMeta item{};
        item.norad_id = seed.norad_id;
        item.route = static_cast<std::uint32_t>(klb::sgp4_seed_route(seed));
        item.lineage_seed = seed.lineage_seed;
        item.reserved = 0u;
        meta.push_back(item);
    }
    return meta;
}

std::vector<std::uint64_t> make_node_hashes(
    const ksgp::Container& container) {
    std::vector<std::uint64_t> hashes;
    hashes.reserve(container.nodes.size());
    for (const auto& node : container.nodes) {
        hashes.push_back(static_cast<std::uint64_t>(node.chain_seed));
    }
    if (hashes.empty()) {
        hashes.push_back(0ull);
    }
    return hashes;
}

std::vector<ElsetRec> initialize_records(
    const ksgp::Container& container) {
    std::vector<ElsetRec> records;
    records.reserve(container.seeds.size());
    for (const auto& seed : container.seeds) {
        records.push_back(ksgp::initialize_from_seed(seed, 'i'));
    }
    return records;
}

void validate_gpu_states(const std::vector<ElsetRec>& records,
                         ElsetRec* device_records) {
    const std::vector<double> times{
        -1440.0, 0.0, 1.0, 60.0, 720.0, 1440.0, 4320.0, 10080.0
    };
    double* device_times = nullptr;
    PvOutput* device_output = nullptr;
    const std::uint64_t total =
        static_cast<std::uint64_t>(records.size()) * times.size();
    CUDA_CHECK(cudaMalloc(
        reinterpret_cast<void**>(&device_times),
        times.size() * sizeof(double)));
    CUDA_CHECK(cudaMalloc(
        reinterpret_cast<void**>(&device_output),
        total * sizeof(PvOutput)));
    CUDA_CHECK(cudaMemcpy(
        device_times, times.data(), times.size() * sizeof(double),
        cudaMemcpyHostToDevice));

    constexpr std::uint32_t block = 128;
    validate_states_kernel<<<grid_for(total, block), block>>>(
        device_records,
        static_cast<std::uint32_t>(records.size()),
        device_times,
        static_cast<std::uint32_t>(times.size()),
        device_output);
    CUDA_CHECK(cudaGetLastError());
    CUDA_CHECK(cudaDeviceSynchronize());

    std::vector<PvOutput> gpu(total);
    CUDA_CHECK(cudaMemcpy(
        gpu.data(), device_output, total * sizeof(PvOutput),
        cudaMemcpyDeviceToHost));

    long double sum_r2 = 0.0L;
    long double sum_v2 = 0.0L;
    double max_r = 0.0;
    double max_v = 0.0;
    std::size_t error_mismatches = 0;
    std::size_t method_mismatches = 0;
    for (std::size_t object = 0; object < records.size(); ++object) {
        for (std::size_t t = 0; t < times.size(); ++t) {
            ElsetRec cpu_rec = records[object];
            double r[3]{};
            double v[3]{};
            const bool ok = sgp4(&cpu_rec, times[t], r, v);
            const auto& value = gpu[object * times.size() + t];
            const int cpu_error = ok ? cpu_rec.error :
                (cpu_rec.error != 0 ? cpu_rec.error : -1);
            if (value.error != cpu_error) {
                ++error_mismatches;
            }
            if (value.method != static_cast<int>(records[object].method)) {
                ++method_mismatches;
            }
            double r2 = 0.0;
            double v2 = 0.0;
            for (int axis = 0; axis < 3; ++axis) {
                const double dr = value.r[axis] - r[axis];
                const double dv = value.v[axis] - v[axis];
                r2 += dr * dr;
                v2 += dv * dv;
            }
            const double re = std::sqrt(r2);
            const double ve = std::sqrt(v2);
            sum_r2 += static_cast<long double>(re) * re;
            sum_v2 += static_cast<long double>(ve) * ve;
            max_r = std::max(max_r, re);
            max_v = std::max(max_v, ve);
        }
    }
    const double rms_r =
        std::sqrt(static_cast<double>(sum_r2 / total));
    const double rms_v =
        std::sqrt(static_cast<double>(sum_v2 / total));

    CUDA_CHECK(cudaFree(device_times));
    CUDA_CHECK(cudaFree(device_output));

    std::cout << std::fixed << std::setprecision(9);
    std::cout << "CPU/GPU full-SGP4 validation\n";
    std::cout << "  states                 " << total << "\n";
    std::cout << "  error mismatches       " << error_mismatches << "\n";
    std::cout << "  method mismatches      " << method_mismatches << "\n";
    std::cout << "  RMS position delta     " << rms_r * 1.0e6 << " mm\n";
    std::cout << "  max position delta     " << max_r * 1.0e6 << " mm\n";
    std::cout << "  RMS velocity delta     " << rms_v * 1.0e6 << " mm/s\n";
    std::cout << "  max velocity delta     " << max_v * 1.0e6 << " mm/s\n";

    // GPU transcendental implementations need not be bit-identical to host libm.
    // These limits are strict enough to protect one-second pass-boundary tests.
    constexpr double max_position_km = 1.0e-5;   // 10 mm
    constexpr double max_velocity_km_s = 1.0e-8; // 0.01 mm/s
    if (error_mismatches != 0 || method_mismatches != 0 ||
        max_r > max_position_km || max_v > max_velocity_km_s) {
        throw std::runtime_error("CPU/GPU full-SGP4 validation failed");
    }
}


std::vector<std::string> parse_csv_fields(const std::string& line) {
    std::vector<std::string> fields;
    std::string field;
    bool quoted = false;
    for (std::size_t i = 0; i < line.size(); ++i) {
        const char c = line[i];
        if (quoted) {
            if (c == '"' && i + 1 < line.size() && line[i + 1] == '"') {
                field.push_back('"');
                ++i;
            } else if (c == '"') {
                quoted = false;
            } else {
                field.push_back(c);
            }
        } else if (c == '"') {
            quoted = true;
        } else if (c == ',') {
            fields.push_back(field);
            field.clear();
        } else {
            field.push_back(c);
        }
    }
    fields.push_back(field);
    return fields;
}

std::vector<Event> load_expected_events(const std::string& path) {
    std::ifstream in(path);
    if (!in) {
        throw std::runtime_error("cannot open expected event CSV " + path);
    }
    std::string line;
    if (!std::getline(in, line)) {
        throw std::runtime_error("expected event CSV is empty");
    }
    const auto header = parse_csv_fields(line);
    std::unordered_map<std::string, std::size_t> columns;
    for (std::size_t i = 0; i < header.size(); ++i) columns[header[i]] = i;

    auto column_any = [&](std::initializer_list<const char*> names,
                          bool required = true) -> std::size_t {
        for (const char* name : names) {
            const auto it = columns.find(name);
            if (it != columns.end()) return it->second;
        }
        if (!required) return std::numeric_limits<std::size_t>::max();
        std::ostringstream message;
        message << "expected event CSV is missing column ";
        bool first = true;
        for (const char* name : names) {
            if (!first) message << " or ";
            message << name;
            first = false;
        }
        throw std::runtime_error(message.str());
    };

    const auto type_col = column_any({"event_type"});
    const auto interval_col = column_any({"interval_index", "time_index"});
    const auto norad_col = column_any({"norad_id"});
    const auto route_col = column_any({"route_sector", "route"});
    const auto lineage_col = column_any({"lineage"});
    const auto guard_col = column_any({"minimum_abs_guard", "guard_sine"});
    const auto seconds_col = column_any({"seconds_from_reference"}, false);

    std::size_t required_max = std::max(
        {type_col, interval_col, norad_col, route_col, lineage_col, guard_col});
    if (seconds_col != std::numeric_limits<std::size_t>::max()) {
        required_max = std::max(required_max, seconds_col);
    }

    std::vector<Event> events;
    while (std::getline(in, line)) {
        if (line.empty()) continue;
        const auto fields = parse_csv_fields(line);
        if (fields.size() <= required_max) {
            throw std::runtime_error("truncated expected event CSV row");
        }
        Event event{};
        const std::string& type = fields[type_col];
        if (type == "AOS" || type == "acquire" || type == "acquisition") {
            event.type = 1u;
        } else if (type == "LOS" || type == "loss") {
            event.type = 2u;
        } else {
            throw std::runtime_error("unknown expected event type " + type);
        }
        event.time_index = static_cast<std::uint32_t>(
            std::stoul(fields[interval_col]));
        event.norad_id = static_cast<std::uint32_t>(
            std::stoul(fields[norad_col]));
        event.route = static_cast<std::uint32_t>(
            std::stoul(fields[route_col]));
        event.lineage = std::stoull(fields[lineage_col]);
        event.guard = std::stod(fields[guard_col]);
        event.crossing_seconds =
            seconds_col == std::numeric_limits<std::size_t>::max()
                ? std::numeric_limits<double>::quiet_NaN()
                : std::stod(fields[seconds_col]);
        events.push_back(event);
    }
    auto key = [](const Event& event) {
        return std::tuple{
            event.time_index,
            event.norad_id,
            event.type,
            event.route,
            event.lineage};
    };
    std::sort(events.begin(), events.end(),
              [&](const Event& a, const Event& b) { return key(a) < key(b); });
    return events;
}

std::vector<Event> copy_events(Event* device_events,
                               unsigned long long count,
                               std::uint64_t capacity) {
    if (count > capacity) {
        throw std::runtime_error(
            "event buffer truncated: count " + std::to_string(count) +
            " exceeds capacity " + std::to_string(capacity));
    }
    std::vector<Event> events(static_cast<std::size_t>(count));
    if (count != 0) {
        CUDA_CHECK(cudaMemcpy(
            events.data(), device_events,
            static_cast<std::size_t>(count) * sizeof(Event),
            cudaMemcpyDeviceToHost));
    }
    auto key = [](const Event& event) {
        return std::tuple{
            event.time_index,
            event.norad_id,
            event.type,
            event.route,
            event.lineage};
    };
    std::sort(events.begin(), events.end(),
              [&](const Event& a, const Event& b) {
                  return key(a) < key(b);
              });
    return events;
}

void compare_event_sets(const std::vector<Event>& a_events,
                        const std::vector<Event>& b_events,
                        const char* label,
                        double guard_tolerance,
                        double time_tolerance = 1.0e-6) {
    if (a_events.size() != b_events.size()) {
        throw std::runtime_error(
            std::string(label) + " event count mismatch: " +
            std::to_string(a_events.size()) + " vs " +
            std::to_string(b_events.size()));
    }
    double max_guard_delta = 0.0;
    double max_time_delta = 0.0;
    for (std::size_t i = 0; i < a_events.size(); ++i) {
        const auto& a = a_events[i];
        const auto& b = b_events[i];
        if (a.norad_id != b.norad_id ||
            a.time_index != b.time_index ||
            a.type != b.type ||
            a.route != b.route ||
            a.lineage != b.lineage) {
            std::ostringstream message;
            message << label << " event identity mismatch at index " << i
                    << ": got (interval=" << a.time_index
                    << ", norad=" << a.norad_id
                    << ", type=" << a.type
                    << ", route=" << a.route
                    << ", lineage=" << a.lineage
                    << ") expected (interval=" << b.time_index
                    << ", norad=" << b.norad_id
                    << ", type=" << b.type
                    << ", route=" << b.route
                    << ", lineage=" << b.lineage << ')';
            throw std::runtime_error(message.str());
        }
        max_guard_delta =
            std::max(max_guard_delta, std::abs(a.guard - b.guard));
        if (std::isfinite(a.crossing_seconds) &&
            std::isfinite(b.crossing_seconds)) {
            max_time_delta = std::max(
                max_time_delta,
                std::abs(a.crossing_seconds - b.crossing_seconds));
        }
    }
    std::cout << label << "\n";
    std::cout << "  events                 " << a_events.size() << "\n";
    std::cout << std::scientific << std::setprecision(6);
    std::cout << "  max guard delta        " << max_guard_delta << "\n";
    std::cout << "  max crossing delta s   " << max_time_delta << "\n";
    std::cout << std::fixed;
    if (max_guard_delta > guard_tolerance) {
        throw std::runtime_error(std::string(label) + " event guard mismatch");
    }
    if (max_time_delta > time_tolerance) {
        throw std::runtime_error(std::string(label) + " event time mismatch");
    }
}

void write_csv(const std::string& path,
               const Options& options,
               const ksgp::Container& container,
               std::uint64_t intervals,
               double step_seconds,
               const TimingStats& direct,
               const TimingStats* materialize,
               const TimingStats* dense_query,
               const Counters& counters,
               std::size_t event_count) {
    if (path.empty()) {
        return;
    }
    std::ofstream out(path);
    if (!out) {
        throw std::runtime_error("cannot write CSV " + path);
    }
    out << "format,objects,intervals,step_seconds,candidates,chunk,"
           "file_bytes,dense_double4_bytes,direct_p50_ms,direct_p95_ms,"
           "direct_p99_ms,direct_mean_ms,materialize_p50_ms,"
           "dense_query_p50_ms,end_to_end_dense_p50_ms,"
           "direct_speedup_vs_dense_e2e,supported,compatible,boundary_evaluations,"
           "visible_endpoints,aos,los,propagation_errors,event_count\n";
    const auto candidates =
        intervals * static_cast<std::uint64_t>(container.seeds.size());
    const auto dense_bytes =
        (intervals + 1ull) *
        static_cast<std::uint64_t>(container.seeds.size()) *
        sizeof(double4);
    const double materialize_p50 =
        materialize ? materialize->p50 : 0.0;
    const double dense_p50 =
        dense_query ? dense_query->p50 : 0.0;
    const double end_to_end = materialize_p50 + dense_p50;
    const double speedup =
        direct.p50 > 0.0 ? end_to_end / direct.p50 : 0.0;
    out << "KSGP1"
        << "," << container.seeds.size()
        << "," << intervals
        << "," << std::setprecision(17) << step_seconds
        << "," << candidates
        << "," << options.chunk
        << "," << container.actual_file_bytes
        << "," << dense_bytes
        << "," << direct.p50
        << "," << direct.p95
        << "," << direct.p99
        << "," << direct.mean
        << "," << materialize_p50
        << "," << dense_p50
        << "," << end_to_end
        << "," << speedup
        << "," << counters.supported
        << "," << counters.compatible
        << "," << counters.boundary_evaluations
        << "," << counters.visible_endpoints
        << "," << counters.aos
        << "," << counters.los
        << "," << counters.propagation_errors
        << "," << event_count
        << "\n";
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const Options options = parse_options(argc, argv);
        const auto container = ksgp::load(options.input, true);
        if (container.seeds.empty()) {
            throw std::runtime_error("KSGP1 contains no seeds");
        }

        int device = 0;
        CUDA_CHECK(cudaGetDevice(&device));
        cudaDeviceProp properties{};
        CUDA_CHECK(cudaGetDeviceProperties(&properties, device));
        CUDA_CHECK(cudaDeviceSetLimit(cudaLimitStackSize, 32768));

        const auto records = initialize_records(container);
        const auto meta = make_meta(container);
        const auto node_hashes = make_node_hashes(container);
        const auto deep = std::count_if(
            records.begin(), records.end(),
            [](const ElsetRec& rec) { return rec.method == 'd'; });

        std::cout << "Device                    " << properties.name << "\n";
        std::cout << "Compute capability        "
                  << properties.major << "." << properties.minor << "\n";
        std::cout << "Objects                   " << records.size() << "\n";
        std::cout << "Deep-space objects        " << deep << "\n";
        std::cout << "Initialized record bytes  " << sizeof(ElsetRec) << "\n";
        std::cout << "Portable seed bytes       "
                  << records.size() * sizeof(ksgp::SeedRecord) << "\n";
        std::cout << "Reference frame           TEME -> PEF by GMST approximation\n";
        if (deep != records.size()) {
            std::cout << "Note                      mixed near/deep object set\n";
        }

        ElsetRec* device_records = nullptr;
        ObjectMeta* device_meta = nullptr;
        std::uint64_t* device_node_hashes = nullptr;
        CUDA_CHECK(cudaMalloc(
            reinterpret_cast<void**>(&device_records),
            records.size() * sizeof(ElsetRec)));
        CUDA_CHECK(cudaMalloc(
            reinterpret_cast<void**>(&device_meta),
            meta.size() * sizeof(ObjectMeta)));
        CUDA_CHECK(cudaMalloc(
            reinterpret_cast<void**>(&device_node_hashes),
            node_hashes.size() * sizeof(std::uint64_t)));
        CUDA_CHECK(cudaMemcpy(
            device_records, records.data(),
            records.size() * sizeof(ElsetRec),
            cudaMemcpyHostToDevice));
        CUDA_CHECK(cudaMemcpy(
            device_meta, meta.data(),
            meta.size() * sizeof(ObjectMeta),
            cudaMemcpyHostToDevice));
        CUDA_CHECK(cudaMemcpy(
            device_node_hashes, node_hashes.data(),
            node_hashes.size() * sizeof(std::uint64_t),
            cudaMemcpyHostToDevice));

        validate_gpu_states(records, device_records);
        if (options.validation_only) {
            CUDA_CHECK(cudaFree(device_node_hashes));
            CUDA_CHECK(cudaFree(device_meta));
            CUDA_CHECK(cudaFree(device_records));
            return 0;
        }

        const double step_seconds =
            options.step_seconds > 0.0
                ? options.step_seconds
                : container.header.step_seconds;
        const std::uint64_t intervals =
            preset_intervals(options, container, step_seconds);
        if (intervals == 0) {
            throw std::runtime_error("interval count is zero");
        }
        if (intervals >
            static_cast<std::uint64_t>(
                std::numeric_limits<std::uint32_t>::max() - 1u)) {
            throw std::runtime_error(
                "event ABI currently limits time indices to uint32");
        }

        const Station station = make_station(
            container.header.station_lat_deg,
            container.header.station_lon_deg,
            container.header.station_alt_km,
            container.header.elevation_guard_deg,
            container.header.crossing_band_deg,
            container.header.maximum_slant_range_km);
        const double node_seconds =
            container.nodes.empty()
                ? std::max(1.0, container.header.horizon_seconds)
                : container.nodes.front().duration_seconds;
        const std::uint64_t chunks_per_object =
            ceil_div(intervals, options.chunk);
        const std::uint64_t direct_threads =
            chunks_per_object * records.size();
        constexpr std::uint32_t chunk_block = 64;
        const std::uint32_t direct_grid =
            grid_for(direct_threads, chunk_block);

        std::cout << std::fixed << std::setprecision(6);
        std::cout << "Intervals per object      " << intervals << "\n";
        std::cout << "Step seconds              " << step_seconds << "\n";
        std::cout << "Candidate intervals       "
                  << intervals * records.size() << "\n";
        std::cout << "Chunk size                " << options.chunk << "\n";
        std::cout << "Direct worker threads     " << direct_threads << "\n";
        const double tested_seconds =
            static_cast<double>(intervals) * step_seconds;
        if (tested_seconds > container.header.horizon_seconds + 1e-9) {
            std::cout << "Stress extension          "
                      << tested_seconds - container.header.horizon_seconds
                      << " seconds beyond declared chain horizon\n";
        }

        Counters* device_counters = nullptr;
        Event* device_events = nullptr;
        unsigned long long* device_event_count = nullptr;
        CUDA_CHECK(cudaMalloc(
            reinterpret_cast<void**>(&device_counters),
            sizeof(Counters)));
        CUDA_CHECK(cudaMalloc(
            reinterpret_cast<void**>(&device_events),
            options.event_capacity * sizeof(Event)));
        CUDA_CHECK(cudaMalloc(
            reinterpret_cast<void**>(&device_event_count),
            sizeof(unsigned long long)));

        auto reset_outputs = [&]() {
            CUDA_CHECK(cudaMemset(device_counters, 0, sizeof(Counters)));
            CUDA_CHECK(cudaMemset(
                device_event_count, 0, sizeof(unsigned long long)));
        };

        // CPU/GPU prefix oracle.
        const std::uint64_t prefix =
            std::min(intervals, options.cpu_prefix_intervals);
        const auto cpu_prefix = cpu_query_prefix(
            records, meta, prefix, container.header.reference_jd,
            step_seconds, container.header.dut1_seconds, station);
        const std::uint64_t prefix_chunks =
            ceil_div(prefix, options.chunk);
        const std::uint64_t prefix_threads =
            prefix_chunks * records.size();
        reset_outputs();
        query_seed_chunked_kernel<<<
            grid_for(prefix_threads, chunk_block), chunk_block>>>(
            device_records,
            device_meta,
            static_cast<std::uint32_t>(records.size()),
            prefix,
            container.header.reference_jd,
            step_seconds,
            container.header.dut1_seconds,
            options.chunk,
            station,
            device_node_hashes,
            static_cast<std::uint32_t>(node_hashes.size()),
            node_seconds,
            device_counters,
            nullptr,
            nullptr,
            0);
        CUDA_CHECK(cudaGetLastError());
        CUDA_CHECK(cudaDeviceSynchronize());
        Counters gpu_prefix{};
        CUDA_CHECK(cudaMemcpy(
            &gpu_prefix, device_counters, sizeof(Counters),
            cudaMemcpyDeviceToHost));
        print_counters("CPU prefix oracle", cpu_prefix);
        print_counters("GPU prefix", gpu_prefix);
        if (!counters_equal(cpu_prefix, gpu_prefix)) {
            throw std::runtime_error("CPU/GPU prefix counter mismatch");
        }

        // Full direct correctness run.
        reset_outputs();
        query_seed_chunked_kernel<<<direct_grid, chunk_block>>>(
            device_records,
            device_meta,
            static_cast<std::uint32_t>(records.size()),
            intervals,
            container.header.reference_jd,
            step_seconds,
            container.header.dut1_seconds,
            options.chunk,
            station,
            device_node_hashes,
            static_cast<std::uint32_t>(node_hashes.size()),
            node_seconds,
            device_counters,
            nullptr,
            nullptr,
            0);
        CUDA_CHECK(cudaGetLastError());
        CUDA_CHECK(cudaDeviceSynchronize());
        Counters direct_counters{};
        CUDA_CHECK(cudaMemcpy(
            &direct_counters, device_counters, sizeof(Counters),
            cudaMemcpyDeviceToHost));
        print_counters("Direct full-SGP4 counters", direct_counters);

        auto launch_direct = [&]() {
            query_seed_chunked_kernel<<<direct_grid, chunk_block>>>(
                device_records,
                device_meta,
                static_cast<std::uint32_t>(records.size()),
                intervals,
                container.header.reference_jd,
                step_seconds,
                container.header.dut1_seconds,
                options.chunk,
                station,
                device_node_hashes,
                static_cast<std::uint32_t>(node_hashes.size()),
                node_seconds,
                device_counters,
                nullptr,
                nullptr,
                0);
        };
        const auto direct_timing =
            time_kernel(launch_direct, options.repeats, options.min_ms);
        print_timing("query_seed_sgp4_direct", direct_timing);

        TimingStats materialize_timing{};
        TimingStats dense_query_timing{};
        Counters dense_counters{};
        double4* device_dense = nullptr;
        std::uint64_t dense_bytes = 0;
        bool have_dense = false;

        if (!options.skip_dense) {
            const std::uint64_t dense_elements =
                (intervals + 1ull) * records.size();
            if (dense_elements >
                std::numeric_limits<std::size_t>::max() / sizeof(double4)) {
                throw std::runtime_error("dense allocation size overflow");
            }
            dense_bytes = dense_elements * sizeof(double4);
            std::size_t free_bytes = 0;
            std::size_t total_bytes = 0;
            CUDA_CHECK(cudaMemGetInfo(&free_bytes, &total_bytes));
            std::cout << "Dense double4 bytes       " << dense_bytes << "\n";
            std::cout << "Free VRAM before dense    " << free_bytes << "\n";
            if (dense_bytes >
                static_cast<std::uint64_t>(
                    static_cast<long double>(free_bytes) * 0.75L)) {
                throw std::runtime_error(
                    "dense baseline would consume more than 75% of free VRAM; "
                    "use fewer intervals or --skip-dense");
            }
            CUDA_CHECK(cudaMalloc(
                reinterpret_cast<void**>(&device_dense),
                static_cast<std::size_t>(dense_bytes)));
            have_dense = true;

            auto launch_materialize = [&]() {
                materialize_pef_chunked_kernel<<<direct_grid, chunk_block>>>(
                    device_records,
                    static_cast<std::uint32_t>(records.size()),
                    intervals,
                    container.header.reference_jd,
                    step_seconds,
                    container.header.dut1_seconds,
                    options.chunk,
                    device_dense);
            };
            materialize_timing = time_kernel(
                launch_materialize, options.repeats, options.min_ms);
            print_timing("materialize_full_sgp4_double4", materialize_timing);
            launch_materialize();
            CUDA_CHECK(cudaGetLastError());
            CUDA_CHECK(cudaDeviceSynchronize());

            const std::uint64_t dense_work =
                intervals * records.size();
            constexpr std::uint32_t dense_block = 256;
            const std::uint32_t dense_grid =
                grid_for(dense_work, dense_block);
            reset_outputs();
            query_dense_kernel<<<dense_grid, dense_block>>>(
                device_dense,
                device_meta,
                static_cast<std::uint32_t>(records.size()),
                intervals,
                step_seconds,
                station,
                device_node_hashes,
                static_cast<std::uint32_t>(node_hashes.size()),
                node_seconds,
                device_counters,
                nullptr,
                nullptr,
                0);
            CUDA_CHECK(cudaGetLastError());
            CUDA_CHECK(cudaDeviceSynchronize());
            CUDA_CHECK(cudaMemcpy(
                &dense_counters, device_counters, sizeof(Counters),
                cudaMemcpyDeviceToHost));
            print_counters("Dense counters", dense_counters);
            if (!counters_equal(direct_counters, dense_counters)) {
                throw std::runtime_error(
                    "direct full-SGP4 and dense counter streams differ");
            }

            auto launch_dense_query = [&]() {
                query_dense_kernel<<<dense_grid, dense_block>>>(
                    device_dense,
                    device_meta,
                    static_cast<std::uint32_t>(records.size()),
                    intervals,
                    step_seconds,
                    station,
                    device_node_hashes,
                    static_cast<std::uint32_t>(node_hashes.size()),
                    node_seconds,
                    device_counters,
                    nullptr,
                    nullptr,
                    0);
            };
            dense_query_timing = time_kernel(
                launch_dense_query, options.repeats, options.min_ms);
            print_timing("query_dense_double4", dense_query_timing);

            const double dense_e2e =
                materialize_timing.p50 + dense_query_timing.p50;
            std::cout << "Dense end-to-end p50 ms   " << dense_e2e << "\n";
            std::cout << "Direct / dense-e2e ratio  "
                      << direct_timing.p50 / dense_e2e << "\n";
            std::cout << "Direct speedup vs e2e     "
                      << dense_e2e / direct_timing.p50 << "x\n";
        }

        std::size_t final_event_count = 0;
        if (!options.skip_events) {
            reset_outputs();
            query_seed_chunked_kernel<<<direct_grid, chunk_block>>>(
                device_records,
                device_meta,
                static_cast<std::uint32_t>(records.size()),
                intervals,
                container.header.reference_jd,
                step_seconds,
                container.header.dut1_seconds,
                options.chunk,
                station,
                device_node_hashes,
                static_cast<std::uint32_t>(node_hashes.size()),
                node_seconds,
                device_counters,
                device_events,
                device_event_count,
                options.event_capacity);
            CUDA_CHECK(cudaGetLastError());
            CUDA_CHECK(cudaDeviceSynchronize());
            unsigned long long direct_event_count = 0;
            CUDA_CHECK(cudaMemcpy(
                &direct_event_count, device_event_count,
                sizeof(unsigned long long), cudaMemcpyDeviceToHost));
            auto direct_events = copy_events(
                device_events, direct_event_count, options.event_capacity);
            final_event_count = direct_events.size();

            if (!options.expected_events_path.empty()) {
                const auto expected =
                    load_expected_events(options.expected_events_path);
                compare_event_sets(
                    direct_events, expected,
                    "GPU/CPU expected-event comparison", 1.0e-8, 1.0e-3);
            }

            if (have_dense) {
                const std::uint64_t dense_work =
                    intervals * records.size();
                constexpr std::uint32_t dense_block = 256;
                reset_outputs();
                query_dense_kernel<<<
                    grid_for(dense_work, dense_block), dense_block>>>(
                    device_dense,
                    device_meta,
                    static_cast<std::uint32_t>(records.size()),
                    intervals,
                    step_seconds,
                    station,
                    device_node_hashes,
                    static_cast<std::uint32_t>(node_hashes.size()),
                    node_seconds,
                    device_counters,
                    device_events,
                    device_event_count,
                    options.event_capacity);
                CUDA_CHECK(cudaGetLastError());
                CUDA_CHECK(cudaDeviceSynchronize());
                unsigned long long dense_event_count = 0;
                CUDA_CHECK(cudaMemcpy(
                    &dense_event_count, device_event_count,
                    sizeof(unsigned long long), cudaMemcpyDeviceToHost));
                auto dense_events = copy_events(
                    device_events, dense_event_count, options.event_capacity);
                compare_event_sets(direct_events, dense_events,
                                   "Direct/dense event comparison",
                                   1.0e-12, 1.0e-9);
            } else {
                std::cout << "Compacted direct events   "
                          << direct_events.size() << "\n";
            }
        }

        const auto dense_samples =
            (intervals + 1ull) * records.size();
        const auto dense_float4_bytes = dense_samples * 16ull;
        const auto dense_double4_bytes = dense_samples * 32ull;
        std::cout << "KSGP1 file bytes          "
                  << container.actual_file_bytes << "\n";
        std::cout << "Dense float4 bytes        "
                  << dense_float4_bytes << "\n";
        std::cout << "Dense double4 bytes       "
                  << dense_double4_bytes << "\n";
        std::cout << "Float4 horizon ratio      "
                  << static_cast<double>(dense_float4_bytes) /
                     static_cast<double>(container.actual_file_bytes)
                  << "x\n";
        std::cout << "Double4 horizon ratio     "
                  << static_cast<double>(dense_double4_bytes) /
                     static_cast<double>(container.actual_file_bytes)
                  << "x\n";

        write_csv(
            options.csv_path,
            options,
            container,
            intervals,
            step_seconds,
            direct_timing,
            have_dense ? &materialize_timing : nullptr,
            have_dense ? &dense_query_timing : nullptr,
            direct_counters,
            final_event_count);

        if (device_dense) {
            CUDA_CHECK(cudaFree(device_dense));
        }
        CUDA_CHECK(cudaFree(device_event_count));
        CUDA_CHECK(cudaFree(device_events));
        CUDA_CHECK(cudaFree(device_counters));
        CUDA_CHECK(cudaFree(device_node_hashes));
        CUDA_CHECK(cudaFree(device_meta));
        CUDA_CHECK(cudaFree(device_records));
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "error: " << e.what() << "\n";
        return 1;
    }
}
