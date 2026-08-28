#pragma once

#include "klb/sgp4.hpp"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <string>
#include <vector>

// Compatibility ABI for the correctness-first CUDA harness.  The durable
// KSGP1 format and authoritative algorithm remain the klb:: types above.
struct ElsetRec : public klb::Sgp4Record {
    char satid[16]{};
    int epochyr{};
    int epochtynumrev{};
    double epochdays{};
    char classification{'U'};
    char intldesg[16]{};
    int ephtype{};
    long elnum{};
    long revnum{};
};

constexpr int wgs72old = klb::kSgp4Wgs72Old;
constexpr int wgs72 = klb::kSgp4Wgs72;
constexpr int wgs84 = klb::kSgp4Wgs84;
constexpr double pi = klb::kSgp4Pi;
constexpr double twopi = klb::kSgp4TwoPi;
constexpr double deg2rad = klb::kSgp4DegToRad;

inline bool sgp4init(char operation_mode, ElsetRec* record) {
    return record != nullptr && klb::sgp4_initialize(*record, operation_mode);
}

#if defined(__CUDACC__) || defined(__CUDA__)
#define KLB_SGP4_COMPAT_HD __host__ __device__
#define KLB_SGP4_COMPAT_INLINE __forceinline__
#else
#define KLB_SGP4_COMPAT_HD
#define KLB_SGP4_COMPAT_INLINE inline
#endif

KLB_SGP4_COMPAT_HD KLB_SGP4_COMPAT_INLINE bool sgp4(
    ElsetRec* record,
    double minutes_since_epoch,
    double* position_km,
    double* velocity_km_s) {
    if (record == nullptr || position_km == nullptr || velocity_km_s == nullptr) {
        return false;
    }
    int error = 0;
    const bool ok = klb::sgp4_propagate_immutable(
        static_cast<const klb::Sgp4Record&>(*record),
        minutes_since_epoch,
        position_km,
        velocity_km_s,
        &error);
    record->error = error;
    return ok;
}

KLB_SGP4_COMPAT_HD KLB_SGP4_COMPAT_INLINE double gstime(double julian_ut1) {
    return klb::sgp4_gstime_device(julian_ut1);
}

inline void jday(
    int year,
    int month,
    int day,
    int hour,
    int minute,
    double second,
    double* jd,
    double* jd_fraction) {
    if (jd == nullptr || jd_fraction == nullptr) return;
    klb::sgp4_jday(year, month, day, hour, minute, second, *jd, *jd_fraction);
}

inline void getgravconst(int model, ElsetRec* record) {
    if (record != nullptr) klb::sgp4_get_gravity_constants(model, *record);
}

#undef KLB_SGP4_COMPAT_HD
#undef KLB_SGP4_COMPAT_INLINE

namespace ksgp {

using SeedRecord = klb::Sgp4SeedDisk;
using TimelineNode = klb::Sgp4TimelineNodeDisk;

struct Header {
    double reference_jd{};
    double reference_unix_seconds{};
    double timeline_start_seconds{};
    double horizon_seconds{};
    double step_seconds{};
    double elevation_guard_deg{};
    double crossing_band_deg{0.25};
    double maximum_slant_range_km{33000.0};
    double dut1_seconds{};
    double station_lat_deg{52.0};
    double station_lon_deg{5.0};
    double station_alt_km{0.05};
    std::uint64_t payload_hash{};
    std::uint64_t terminal_hash{};
    char source_label[64]{};
};

struct Container {
    Header header{};
    std::vector<SeedRecord> seeds;
    std::vector<TimelineNode> nodes;
    std::uint64_t actual_file_bytes{};
};

inline std::uint64_t mix64(std::uint64_t x) {
    x ^= x >> 30u;
    x *= 0xbf58476d1ce4e5b9ull;
    x ^= x >> 27u;
    x *= 0x94d049bb133111ebull;
    x ^= x >> 31u;
    return x;
}

inline std::uint32_t route_from_raan(double raan_rad) {
    double wrapped = std::fmod(raan_rad, klb::kSgp4TwoPi);
    if (wrapped < 0.0) wrapped += klb::kSgp4TwoPi;
    const auto route = static_cast<std::uint32_t>(
        std::floor(wrapped * 6.0 / klb::kSgp4TwoPi));
    return std::min<std::uint32_t>(5u, route);
}

inline Container load(const std::filesystem::path& path, bool verify_hashes = true) {
    klb::Sgp4Data data = klb::load_sgp4_data(path);
    klb::validate_sgp4_data(data, verify_hashes);
    Container result{};
    result.header.reference_jd = data.header.reference_julian_date;
    result.header.reference_unix_seconds =
        static_cast<double>(data.header.reference_unix_microseconds) / 1.0e6;
    result.header.timeline_start_seconds = data.header.timeline_start_seconds;
    result.header.horizon_seconds = data.header.timeline_duration_seconds;
    result.header.step_seconds = data.header.timeline_step_seconds;
    result.header.elevation_guard_deg =
        data.header.default_elevation_mask_rad * klb::kSgp4RadToDeg;
    result.header.dut1_seconds = data.header.default_dut1_seconds;
    result.header.payload_hash = data.header.payload_hash;
    result.header.terminal_hash = data.header.chain_hash;
    std::snprintf(result.header.source_label, sizeof(result.header.source_label),
                  "%s", data.header.source_name);
    result.seeds = std::move(data.seeds);
    result.nodes = std::move(data.nodes);
    result.actual_file_bytes = std::filesystem::file_size(path);
    return result;
}

inline ElsetRec initialize_from_seed(
    const SeedRecord& seed,
    char operation_mode = 'i') {
    ElsetRec record{};
    static_cast<klb::Sgp4Record&>(record) =
        klb::initialize_sgp4_record(seed, klb::kSgp4Wgs72);
    record.operationmode = operation_mode;
    record.classification = klb::sgp4_seed_classification(seed);
    record.ephtype = static_cast<int>(klb::sgp4_seed_ephemeris_type(seed));
    record.elnum = static_cast<long>(seed.element_set_no);
    record.revnum = static_cast<long>(seed.revolution_number);
    std::snprintf(record.satid, sizeof(record.satid), "%u", seed.norad_id);
    return record;
}

} // namespace ksgp
