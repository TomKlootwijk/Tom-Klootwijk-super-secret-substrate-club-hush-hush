#pragma once

#include "klb/core.hpp"

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

namespace klb {

constexpr std::uint32_t kOrbitFormatVersion = 1u;
constexpr std::uint32_t kOrbitModelKeplerJ2Secular = 1u;
constexpr std::uint32_t kOrbitSourceOmmCsv = 1u;
constexpr std::uint32_t kNoOrbitParent = 0xffffffffu;
constexpr std::uint32_t kOrbitMaxGpuSeeds = 256u;
constexpr std::uint32_t kOrbitMaxGpuNodes = 256u;

constexpr std::uint32_t kOrbitFlagHashLinked = 1u << 0u;
constexpr std::uint32_t kOrbitFlagStringTable = 1u << 1u;
constexpr std::uint32_t kOrbitFlagOmmSource = 1u << 2u;
constexpr std::uint32_t kOrbitFlagSecularJ2 = 1u << 3u;
constexpr std::uint32_t kOrbitFlagTimeline = 1u << 4u;
constexpr std::uint32_t kOrbitFlagCoarseModel = 1u << 5u;

constexpr std::uint32_t kOrbitNodeCheckpoint = 1u << 0u;
constexpr std::uint32_t kOrbitNodeTimelineTile = 1u << 1u;

constexpr float kOrbitMuEarthKm3S2 = 398600.4418f;
constexpr float kOrbitEarthEquatorialRadiusKm = 6378.137f;
constexpr float kOrbitEarthJ2 = 1.08262668e-3f;
constexpr float kOrbitEarthRotationRadS = 7.2921150e-5f;
constexpr float kOrbitPi = 3.14159265358979323846f;
constexpr float kOrbitTwoPi = 6.28318530717958647692f;
constexpr float kOrbitDegToRad = kOrbitPi / 180.0f;
constexpr float kOrbitRadToDeg = 180.0f / kOrbitPi;

#pragma pack(push, 1)
struct alignas(16) OrbitSeedDisk {
    std::uint32_t norad_id;
    std::uint16_t prn;
    std::uint8_t route_sector;
    std::uint8_t flags;

    float epoch_offset_seconds;
    float semi_major_axis_km;
    float eccentricity;
    float sqrt_one_minus_e2;

    float inclination_rad;
    float raan_rad;
    float argument_perigee_rad;
    float mean_anomaly_rad;

    float mean_motion_rad_s;
    float raan_rate_rad_s;
    float argument_perigee_rate_rad_s;
    float mean_anomaly_rate_rad_s;

    std::uint32_t lineage_seed;
    std::uint32_t name_offset;
};

struct alignas(16) OrbitTimelineNodeDisk {
    std::uint32_t parent_index;
    std::uint32_t node_index;
    std::uint32_t flags;
    std::uint32_t chain_seed;

    float start_seconds;
    float duration_seconds;
    float step_seconds;
    float reserved_float;

    std::uint64_t parent_hash;
    std::uint64_t self_hash;
    std::uint64_t source_hash;

    std::uint32_t epoch_begin;
    std::uint32_t epoch_count;
};

struct OrbitHeaderDisk {
    char magic[8];
    std::uint32_t version;
    std::uint32_t header_bytes;

    std::uint32_t flags;
    std::uint32_t seed_bytes;
    std::uint32_t node_bytes;
    std::uint32_t reserved0;

    std::uint64_t seed_count;
    std::uint64_t node_count;
    std::uint64_t seeds_offset;
    std::uint64_t nodes_offset;
    std::uint64_t strings_offset;
    std::uint64_t strings_bytes;

    std::uint64_t source_bytes;
    std::uint64_t source_hash;
    std::uint64_t payload_hash;
    std::uint64_t chain_hash;
    std::int64_t reference_unix_microseconds;

    float mu_earth_km3_s2;
    float earth_equatorial_radius_km;
    float earth_j2;
    float earth_rotation_rad_s;
    float reference_gmst_rad;
    float default_elevation_mask_rad;
    float timeline_start_seconds;
    float timeline_step_seconds;
    float timeline_duration_seconds;

    std::uint64_t timeline_sample_count;
    std::uint32_t predictor_model;
    std::uint32_t source_format;

    char source_name[48];
    std::uint8_t reserved[36];
};
#pragma pack(pop)

static_assert(sizeof(OrbitSeedDisk) == 64u, "orbit seed records must stay 64 bytes");
static_assert(sizeof(OrbitTimelineNodeDisk) == 64u, "orbit timeline nodes must stay 64 bytes");
static_assert(sizeof(OrbitHeaderDisk) == 256u, "orbit header must stay 256 bytes");
static_assert(alignof(OrbitSeedDisk) == 16u, "orbit seeds must remain 16-byte aligned");
static_assert(alignof(OrbitTimelineNodeDisk) == 16u, "orbit nodes must remain 16-byte aligned");

struct OrbitData {
    OrbitHeaderDisk header{};
    std::vector<OrbitSeedDisk> seeds;
    std::vector<OrbitTimelineNodeDisk> nodes;
    std::vector<char> strings;
};

struct OrbitPackOptions {
    float horizon_seconds = 7.0f * 24.0f * 3600.0f;
    float step_seconds = 1.0f;
    float tile_seconds = 24.0f * 3600.0f;
    float elevation_mask_degrees = 10.0f;
    std::uint32_t seed = 0x4f524254u;
};

struct OrbitStats {
    std::uint64_t file_bytes{};
    std::uint64_t source_bytes{};
    std::uint64_t seed_bytes{};
    std::uint64_t node_bytes{};
    std::uint64_t string_bytes{};
    std::uint64_t seed_count{};
    std::uint64_t node_count{};
    std::uint64_t timeline_samples{};
    std::uint64_t equivalent_dense_float4_bytes{};
    double ratio_vs_dense_float4{};
    double source_to_container_ratio{};
};

struct OrbitView {
    const OrbitSeedDisk* seeds{};
    const OrbitTimelineNodeDisk* nodes{};
    std::uint32_t seed_count{};
    std::uint32_t node_count{};
    float earth_rotation_rad_s{kOrbitEarthRotationRadS};
    float reference_gmst_rad{};
    float timeline_start_seconds{};
    float timeline_duration_seconds{};
};

struct OrbitGroundStation {
    Vec3 ecef_km{};
    float elevation_mask_sin{};
    float crossing_band_sin{};
    float maximum_slant_range_km{};
    std::uint32_t route_filter{0xffffffffu};
};

struct OrbitEvaluation {
    float guard{};
    float elevation_sin{};
    float slant_range_km{};
    std::uint32_t supported{};
    std::uint32_t compatible{};
};

struct OrbitCrossing {
    std::uint32_t verified{};
    std::uint32_t acquisition{};
    float interpolation{};
    float crossing_seconds{};
    float minimum_abs_guard{};
};

OrbitData pack_omm_csv(const std::filesystem::path& csv_path, const OrbitPackOptions& options = {});
void validate_orbit_data(const OrbitData& data, bool verify_hashes = true);
void save_orbit_data(const std::filesystem::path& path, const OrbitData& data);
OrbitData load_orbit_data(const std::filesystem::path& path);
OrbitStats inspect_orbit_data(const OrbitData& data, std::uint64_t actual_file_bytes = 0u);
OrbitView make_orbit_view(const OrbitData& data);
std::string orbit_string_at(const OrbitData& data, std::uint32_t offset);
std::string format_unix_microseconds_iso8601(std::int64_t unix_microseconds);
OrbitGroundStation make_ground_station(
    float latitude_degrees,
    float longitude_degrees,
    float altitude_km,
    float elevation_mask_degrees,
    float crossing_band_degrees,
    float maximum_slant_range_km,
    std::uint32_t route_filter = 0xffffffffu);

KLB_HD KLB_INLINE float orbit_wrap_radians(float value) {
    const float turns = ::floorf((value + kOrbitPi) / kOrbitTwoPi);
    return value - turns * kOrbitTwoPi;
}

KLB_HD KLB_INLINE Vec3 orbit_rotate_z(const Vec3& value, float angle) {
    const float sine = ::sinf(angle);
    const float cosine = ::cosf(angle);
    return {
        cosine * value.x - sine * value.y,
        sine * value.x + cosine * value.y,
        value.z,
    };
}

// Closed, deterministic benchmark predictor compiled from OMM mean elements.
// It is a Kepler solve with secular J2 rates precomputed by the packer. It is
// intentionally not presented as a replacement for SGP4 or navigation-grade ephemerides.
KLB_HD KLB_INLINE Vec3 propagate_orbit_seed(const OrbitSeedDisk& seed, float seconds_from_reference) {
    const float dt = seconds_from_reference - seed.epoch_offset_seconds;
    const float raan = orbit_wrap_radians(seed.raan_rad + seed.raan_rate_rad_s * dt);
    const float argument = orbit_wrap_radians(
        seed.argument_perigee_rad + seed.argument_perigee_rate_rad_s * dt);
    const float mean_anomaly = orbit_wrap_radians(
        seed.mean_anomaly_rad + seed.mean_anomaly_rate_rad_s * dt);

    float eccentric_anomaly = mean_anomaly;
    // GPS operational eccentricities are small; five fixed iterations avoid a
    // divergent loop and make host/device work deterministic.
    for (std::uint32_t iteration = 0u; iteration < 5u; ++iteration) {
        const float sine = ::sinf(eccentric_anomaly);
        const float cosine = ::cosf(eccentric_anomaly);
        const float function = eccentric_anomaly - seed.eccentricity * sine - mean_anomaly;
        const float derivative = 1.0f - seed.eccentricity * cosine;
        eccentric_anomaly -= function / derivative;
    }

    const float cosine_e = ::cosf(eccentric_anomaly);
    const float sine_e = ::sinf(eccentric_anomaly);
    const float x_orbit = seed.semi_major_axis_km * (cosine_e - seed.eccentricity);
    const float y_orbit = seed.semi_major_axis_km * seed.sqrt_one_minus_e2 * sine_e;

    const float cosine_raan = ::cosf(raan);
    const float sine_raan = ::sinf(raan);
    const float cosine_argument = ::cosf(argument);
    const float sine_argument = ::sinf(argument);
    const float cosine_inclination = ::cosf(seed.inclination_rad);
    const float sine_inclination = ::sinf(seed.inclination_rad);

    const float p00 = cosine_raan * cosine_argument -
                      sine_raan * sine_argument * cosine_inclination;
    const float p01 = -cosine_raan * sine_argument -
                      sine_raan * cosine_argument * cosine_inclination;
    const float p10 = sine_raan * cosine_argument +
                      cosine_raan * sine_argument * cosine_inclination;
    const float p11 = -sine_raan * sine_argument +
                      cosine_raan * cosine_argument * cosine_inclination;
    const float p20 = sine_argument * sine_inclination;
    const float p21 = cosine_argument * sine_inclination;

    return {
        p00 * x_orbit + p01 * y_orbit,
        p10 * x_orbit + p11 * y_orbit,
        p20 * x_orbit + p21 * y_orbit,
    };
}

KLB_HD KLB_INLINE OrbitEvaluation evaluate_orbit_visibility(
    const Vec3& satellite_eci_km,
    float seconds_from_reference,
    const OrbitGroundStation& station,
    float reference_gmst_rad,
    float earth_rotation_rad_s,
    std::uint32_t route_sector) {
    const float earth_angle = reference_gmst_rad + earth_rotation_rad_s * seconds_from_reference;
    const Vec3 station_eci = orbit_rotate_z(station.ecef_km, earth_angle);
    const float station_radius = length(station_eci);
    const Vec3 zenith = station_radius > 1.0e-12f
        ? station_eci * (1.0f / station_radius)
        : Vec3{0.0f, 0.0f, 1.0f};
    const Vec3 line_of_sight = satellite_eci_km - station_eci;
    const float slant_range = length(line_of_sight);
    const float elevation_sin = slant_range > 1.0e-12f
        ? dot(line_of_sight, zenith) / slant_range
        : 1.0f;
    const float guard = station.elevation_mask_sin - elevation_sin;
    const std::uint32_t supported =
        slant_range <= station.maximum_slant_range_km ? 1u : 0u;
    const std::uint32_t compatible =
        station.route_filter == 0xffffffffu || station.route_filter == route_sector ? 1u : 0u;
    return {guard, elevation_sin, slant_range, supported, compatible};
}

KLB_HD KLB_INLINE OrbitCrossing evaluate_orbit_crossing(
    const OrbitEvaluation& previous,
    const OrbitEvaluation& current,
    float previous_seconds,
    float current_seconds,
    float crossing_band_sin) {
    const bool sign_change =
        (previous.guard > 0.0f && current.guard <= 0.0f) ||
        (previous.guard <= 0.0f && current.guard > 0.0f);
    const float previous_abs = ::fabsf(previous.guard);
    const float current_abs = ::fabsf(current.guard);
    const float minimum_abs = previous_abs < current_abs ? previous_abs : current_abs;
    const bool bounded = minimum_abs <= crossing_band_sin;
    const bool gates =
        (previous.supported != 0u || current.supported != 0u) &&
        previous.compatible != 0u && current.compatible != 0u;
    const float denominator = previous.guard - current.guard;
    float interpolation = ::fabsf(denominator) > 1.0e-20f
        ? previous.guard / denominator
        : 0.5f;
    interpolation = interpolation < 0.0f ? 0.0f : (interpolation > 1.0f ? 1.0f : interpolation);
    const float crossing_seconds = previous_seconds +
        interpolation * (current_seconds - previous_seconds);
    return {
        sign_change && bounded && gates ? 1u : 0u,
        previous.guard > 0.0f && current.guard <= 0.0f ? 1u : 0u,
        interpolation,
        crossing_seconds,
        minimum_abs,
    };
}

KLB_HD KLB_INLINE std::uint32_t orbit_timeline_node_index(
    const OrbitView& view,
    float seconds_from_reference) {
    if (view.node_count == 0u) return 0u;
    float local = seconds_from_reference - view.timeline_start_seconds;
    if (view.timeline_duration_seconds > 0.0f) {
        local -= ::floorf(local / view.timeline_duration_seconds) * view.timeline_duration_seconds;
    }
    // Nodes may have nonuniform final duration; the short linear scan is bounded
    // to <=256 records and normally resolves in seven daily tiles.
    for (std::uint32_t index = 0u; index < view.node_count; ++index) {
        const OrbitTimelineNodeDisk node = view.nodes[index];
        if (local >= node.start_seconds && local < node.start_seconds + node.duration_seconds) {
            return index;
        }
    }
    return view.node_count - 1u;
}

KLB_HD KLB_INLINE std::uint32_t orbit_lineage(
    const OrbitSeedDisk& seed,
    const OrbitTimelineNodeDisk& node,
    std::uint64_t epoch_index,
    std::uint32_t event_type) {
    const std::uint32_t epoch_lo = static_cast<std::uint32_t>(epoch_index);
    const std::uint32_t epoch_hi = static_cast<std::uint32_t>(epoch_index >> 32u);
    return mix32(seed.lineage_seed ^ node.chain_seed ^ epoch_lo ^
                 (epoch_hi * 0x9e3779b9u) ^ (event_type * 0x85ebca6bu));
}

} // namespace klb
