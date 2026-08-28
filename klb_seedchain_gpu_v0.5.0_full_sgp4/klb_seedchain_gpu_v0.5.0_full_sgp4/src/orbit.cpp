#include "klb/orbit.hpp"

#include <algorithm>
#include <array>
#include <bit>
#include <charconv>
#include <cmath>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <limits>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string_view>

namespace klb {
namespace {

constexpr std::array<char, 8> kOrbitMagic{'K', 'L', 'O', 'C', '1', '\0', '\0', '\0'};
constexpr std::uint64_t kFnvOffset = 1469598103934665603ull;
constexpr std::uint64_t kFnvPrime = 1099511628211ull;

void require_little_endian() {
    if constexpr (std::endian::native != std::endian::little) {
        throw std::runtime_error("KLOC1 currently requires a little-endian host");
    }
}

std::uint64_t fnv_update(std::uint64_t hash, const void* data, std::size_t size) {
    const auto* bytes = static_cast<const std::uint8_t*>(data);
    for (std::size_t index = 0; index < size; ++index) {
        hash ^= bytes[index];
        hash *= kFnvPrime;
    }
    return hash;
}

std::uint64_t payload_hash(const OrbitData& data) {
    std::uint64_t hash = kFnvOffset;
    if (!data.seeds.empty()) {
        hash = fnv_update(hash, data.seeds.data(), data.seeds.size() * sizeof(OrbitSeedDisk));
    }
    if (!data.nodes.empty()) {
        hash = fnv_update(hash, data.nodes.data(), data.nodes.size() * sizeof(OrbitTimelineNodeDisk));
    }
    if (!data.strings.empty()) {
        hash = fnv_update(hash, data.strings.data(), data.strings.size());
    }
    return hash;
}

std::uint64_t hash_node(const OrbitTimelineNodeDisk& input) {
    OrbitTimelineNodeDisk node = input;
    node.self_hash = 0u;
    return fnv1a64(&node, sizeof(node));
}

std::string read_binary_text(const std::filesystem::path& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) throw std::runtime_error("unable to open input file: " + path.string());
    input.seekg(0, std::ios::end);
    const std::streamoff end = input.tellg();
    if (end < 0) throw std::runtime_error("unable to determine input size: " + path.string());
    input.seekg(0, std::ios::beg);
    std::string bytes(static_cast<std::size_t>(end), '\0');
    if (!bytes.empty()) input.read(bytes.data(), static_cast<std::streamsize>(bytes.size()));
    if (!input) throw std::runtime_error("failed while reading input file: " + path.string());
    return bytes;
}

std::vector<std::string> parse_csv_row(std::string_view line) {
    std::vector<std::string> fields;
    std::string field;
    bool quoted = false;
    for (std::size_t index = 0; index < line.size(); ++index) {
        const char character = line[index];
        if (quoted) {
            if (character == '"') {
                if (index + 1u < line.size() && line[index + 1u] == '"') {
                    field.push_back('"');
                    ++index;
                } else {
                    quoted = false;
                }
            } else {
                field.push_back(character);
            }
        } else if (character == '"') {
            quoted = true;
        } else if (character == ',') {
            fields.push_back(std::move(field));
            field.clear();
        } else if (character != '\r') {
            field.push_back(character);
        }
    }
    if (quoted) throw std::runtime_error("unterminated quoted CSV field");
    fields.push_back(std::move(field));
    return fields;
}

std::int64_t days_from_civil(int year, unsigned month, unsigned day) {
    year -= month <= 2u ? 1 : 0;
    const int era = (year >= 0 ? year : year - 399) / 400;
    const unsigned yoe = static_cast<unsigned>(year - era * 400);
    const unsigned adjusted_month = month > 2u ? month - 3u : month + 9u;
    const unsigned doy = (153u * adjusted_month + 2u) / 5u + day - 1u;
    const unsigned doe = yoe * 365u + yoe / 4u - yoe / 100u + doy;
    return static_cast<std::int64_t>(era) * 146097ll + static_cast<std::int64_t>(doe) - 719468ll;
}

std::array<int, 3> civil_from_days(std::int64_t days) {
    days += 719468ll;
    const std::int64_t era = (days >= 0 ? days : days - 146096ll) / 146097ll;
    const unsigned doe = static_cast<unsigned>(days - era * 146097ll);
    const unsigned yoe = (doe - doe / 1460u + doe / 36524u - doe / 146096u) / 365u;
    int year = static_cast<int>(yoe) + static_cast<int>(era * 400ll);
    const unsigned doy = doe - (365u * yoe + yoe / 4u - yoe / 100u);
    const unsigned mp = (5u * doy + 2u) / 153u;
    const unsigned day = doy - (153u * mp + 2u) / 5u + 1u;
    const unsigned month = mp < 10u ? mp + 3u : mp - 9u;
    year += month <= 2u ? 1 : 0;
    return {year, static_cast<int>(month), static_cast<int>(day)};
}

int parse_fixed_int(std::string_view text, std::size_t offset, std::size_t count, const char* name) {
    if (offset + count > text.size()) throw std::runtime_error(std::string("short ISO epoch while parsing ") + name);
    int value = 0;
    const char* begin = text.data() + offset;
    const char* end = begin + count;
    const auto result = std::from_chars(begin, end, value);
    if (result.ec != std::errc{} || result.ptr != end) {
        throw std::runtime_error(std::string("invalid ISO epoch ") + name);
    }
    return value;
}

std::int64_t parse_iso8601_microseconds(std::string_view text) {
    if (text.size() < 19u || text[4] != '-' || text[7] != '-' ||
        (text[10] != 'T' && text[10] != ' ') || text[13] != ':' || text[16] != ':') {
        throw std::runtime_error("unsupported OMM epoch format: " + std::string(text));
    }
    const int year = parse_fixed_int(text, 0u, 4u, "year");
    const int month = parse_fixed_int(text, 5u, 2u, "month");
    const int day = parse_fixed_int(text, 8u, 2u, "day");
    const int hour = parse_fixed_int(text, 11u, 2u, "hour");
    const int minute = parse_fixed_int(text, 14u, 2u, "minute");
    const int second = parse_fixed_int(text, 17u, 2u, "second");
    if (month < 1 || month > 12 || day < 1 || day > 31 || hour < 0 || hour > 23 ||
        minute < 0 || minute > 59 || second < 0 || second > 60) {
        throw std::runtime_error("out-of-range OMM epoch: " + std::string(text));
    }
    std::int64_t fraction = 0;
    if (text.size() > 19u && text[19] == '.') {
        std::size_t index = 20u;
        std::size_t digits = 0u;
        while (index < text.size() && text[index] >= '0' && text[index] <= '9' && digits < 6u) {
            fraction = fraction * 10ll + static_cast<std::int64_t>(text[index] - '0');
            ++index;
            ++digits;
        }
        while (digits < 6u) {
            fraction *= 10ll;
            ++digits;
        }
    }
    const std::int64_t days = days_from_civil(year, static_cast<unsigned>(month), static_cast<unsigned>(day));
    return (((days * 24ll + hour) * 60ll + minute) * 60ll + second) * 1000000ll + fraction;
}

float gmst_at_unix_microseconds(std::int64_t unix_microseconds) {
    const double unix_seconds = static_cast<double>(unix_microseconds) / 1.0e6;
    const double julian_date = unix_seconds / 86400.0 + 2440587.5;
    const double days = julian_date - 2451545.0;
    const double centuries = days / 36525.0;
    double degrees = 280.46061837 + 360.98564736629 * days +
                     0.000387933 * centuries * centuries -
                     centuries * centuries * centuries / 38710000.0;
    degrees = std::fmod(degrees, 360.0);
    if (degrees < 0.0) degrees += 360.0;
    return static_cast<float>(degrees * static_cast<double>(kOrbitDegToRad));
}

std::uint16_t parse_prn(std::string_view object_name) {
    const std::size_t marker = object_name.find("PRN");
    if (marker == std::string_view::npos) return 0u;
    std::size_t index = marker + 3u;
    while (index < object_name.size() && object_name[index] == ' ') ++index;
    unsigned value = 0u;
    const char* begin = object_name.data() + index;
    const char* end = object_name.data() + object_name.size();
    const auto result = std::from_chars(begin, end, value);
    if (result.ec != std::errc{}) return 0u;
    return static_cast<std::uint16_t>(std::min(value, 65535u));
}

std::uint32_t append_string(std::vector<char>& table, std::string_view text) {
    if (table.empty()) table.push_back('\0');
    if (table.size() > std::numeric_limits<std::uint32_t>::max() - text.size() - 1u) {
        throw std::runtime_error("orbit string table exceeds 32-bit offsets");
    }
    const std::uint32_t offset = static_cast<std::uint32_t>(table.size());
    table.insert(table.end(), text.begin(), text.end());
    table.push_back('\0');
    return offset;
}

struct OmmRow {
    std::string object_name;
    std::string object_id;
    std::int64_t epoch_microseconds{};
    double mean_motion_rev_day{};
    double eccentricity{};
    double inclination_deg{};
    double raan_deg{};
    double argument_perigee_deg{};
    double mean_anomaly_deg{};
    std::uint32_t norad_id{};
    std::uint16_t prn{};
};

const std::string& required_field(
    const std::vector<std::string>& fields,
    const std::map<std::string, std::size_t>& columns,
    const char* name) {
    const auto iterator = columns.find(name);
    if (iterator == columns.end() || iterator->second >= fields.size()) {
        throw std::runtime_error(std::string("OMM CSV is missing required field ") + name);
    }
    return fields[iterator->second];
}

std::uint32_t parse_u32(const std::string& text, const char* name) {
    std::size_t consumed = 0u;
    const unsigned long value = std::stoul(text, &consumed, 10);
    if (consumed != text.size() || value > std::numeric_limits<std::uint32_t>::max()) {
        throw std::runtime_error(std::string("invalid OMM integer ") + name + ": " + text);
    }
    return static_cast<std::uint32_t>(value);
}

double parse_double(const std::string& text, const char* name) {
    std::size_t consumed = 0u;
    const double value = std::stod(text, &consumed);
    if (consumed != text.size() || !std::isfinite(value)) {
        throw std::runtime_error(std::string("invalid OMM scalar ") + name + ": " + text);
    }
    return value;
}

std::vector<OmmRow> parse_omm_rows(const std::string& csv) {
    std::istringstream stream(csv);
    std::string line;
    if (!std::getline(stream, line)) throw std::runtime_error("OMM CSV is empty");
    const std::vector<std::string> header = parse_csv_row(line);
    std::map<std::string, std::size_t> columns;
    for (std::size_t index = 0u; index < header.size(); ++index) columns[header[index]] = index;

    const std::array<const char*, 10> required{
        "OBJECT_NAME", "OBJECT_ID", "EPOCH", "MEAN_MOTION", "ECCENTRICITY",
        "INCLINATION", "RA_OF_ASC_NODE", "ARG_OF_PERICENTER", "MEAN_ANOMALY",
        "NORAD_CAT_ID",
    };
    for (const char* name : required) {
        if (columns.find(name) == columns.end()) {
            throw std::runtime_error(std::string("OMM CSV header lacks ") + name);
        }
    }

    std::vector<OmmRow> rows;
    std::uint32_t line_number = 1u;
    while (std::getline(stream, line)) {
        ++line_number;
        if (line.empty() || line == "\r") continue;
        const std::vector<std::string> fields = parse_csv_row(line);
        try {
            OmmRow row{};
            row.object_name = required_field(fields, columns, "OBJECT_NAME");
            row.object_id = required_field(fields, columns, "OBJECT_ID");
            row.epoch_microseconds = parse_iso8601_microseconds(required_field(fields, columns, "EPOCH"));
            row.mean_motion_rev_day = parse_double(required_field(fields, columns, "MEAN_MOTION"), "MEAN_MOTION");
            row.eccentricity = parse_double(required_field(fields, columns, "ECCENTRICITY"), "ECCENTRICITY");
            row.inclination_deg = parse_double(required_field(fields, columns, "INCLINATION"), "INCLINATION");
            row.raan_deg = parse_double(required_field(fields, columns, "RA_OF_ASC_NODE"), "RA_OF_ASC_NODE");
            row.argument_perigee_deg = parse_double(required_field(fields, columns, "ARG_OF_PERICENTER"), "ARG_OF_PERICENTER");
            row.mean_anomaly_deg = parse_double(required_field(fields, columns, "MEAN_ANOMALY"), "MEAN_ANOMALY");
            row.norad_id = parse_u32(required_field(fields, columns, "NORAD_CAT_ID"), "NORAD_CAT_ID");
            row.prn = parse_prn(row.object_name);
            if (!(row.mean_motion_rev_day > 0.0) || row.eccentricity < 0.0 || row.eccentricity >= 1.0) {
                throw std::runtime_error("unsupported non-elliptic or zero-motion OMM record");
            }
            rows.push_back(std::move(row));
        } catch (const std::exception& error) {
            throw std::runtime_error("OMM CSV line " + std::to_string(line_number) + ": " + error.what());
        }
    }
    if (rows.empty()) throw std::runtime_error("OMM CSV contains no data records");
    std::sort(rows.begin(), rows.end(), [](const OmmRow& left, const OmmRow& right) {
        return left.norad_id < right.norad_id;
    });
    for (std::size_t index = 1u; index < rows.size(); ++index) {
        if (rows[index - 1u].norad_id == rows[index].norad_id) {
            throw std::runtime_error("OMM CSV contains duplicate NORAD_CAT_ID " +
                                     std::to_string(rows[index].norad_id));
        }
    }
    return rows;
}

void initialize_offsets(OrbitData& data) {
    data.header.seed_count = data.seeds.size();
    data.header.node_count = data.nodes.size();
    data.header.seeds_offset = sizeof(OrbitHeaderDisk);
    data.header.nodes_offset = data.header.seeds_offset +
        data.seeds.size() * sizeof(OrbitSeedDisk);
    data.header.strings_offset = data.header.nodes_offset +
        data.nodes.size() * sizeof(OrbitTimelineNodeDisk);
    data.header.strings_bytes = data.strings.size();
}

} // namespace

OrbitData pack_omm_csv(const std::filesystem::path& csv_path, const OrbitPackOptions& options) {
    require_little_endian();
    if (!(options.horizon_seconds > 0.0f) || !std::isfinite(options.horizon_seconds)) {
        throw std::invalid_argument("orbit horizon must be finite and greater than zero");
    }
    if (!(options.step_seconds > 0.0f) || !std::isfinite(options.step_seconds)) {
        throw std::invalid_argument("orbit step must be finite and greater than zero");
    }
    if (!(options.tile_seconds > 0.0f) || !std::isfinite(options.tile_seconds)) {
        throw std::invalid_argument("orbit tile duration must be finite and greater than zero");
    }
    if (options.tile_seconds < options.step_seconds) {
        throw std::invalid_argument("orbit tile duration must be at least one sample step");
    }
    if (options.elevation_mask_degrees <= -90.0f || options.elevation_mask_degrees >= 90.0f ||
        !std::isfinite(options.elevation_mask_degrees)) {
        throw std::invalid_argument("elevation mask must be finite and between -90 and 90 degrees");
    }

    const std::string source = read_binary_text(csv_path);
    const std::vector<OmmRow> rows = parse_omm_rows(source);
    if (rows.size() > std::numeric_limits<std::uint32_t>::max()) {
        throw std::runtime_error("too many OMM records for KLOC1");
    }

    OrbitData data{};
    std::memcpy(data.header.magic, kOrbitMagic.data(), kOrbitMagic.size());
    data.header.version = kOrbitFormatVersion;
    data.header.header_bytes = sizeof(OrbitHeaderDisk);
    data.header.flags = kOrbitFlagHashLinked | kOrbitFlagStringTable |
                        kOrbitFlagOmmSource | kOrbitFlagSecularJ2 |
                        kOrbitFlagTimeline | kOrbitFlagCoarseModel;
    data.header.seed_bytes = sizeof(OrbitSeedDisk);
    data.header.node_bytes = sizeof(OrbitTimelineNodeDisk);
    data.header.source_bytes = source.size();
    data.header.source_hash = fnv1a64(source.data(), source.size());
    data.header.mu_earth_km3_s2 = kOrbitMuEarthKm3S2;
    data.header.earth_equatorial_radius_km = kOrbitEarthEquatorialRadiusKm;
    data.header.earth_j2 = kOrbitEarthJ2;
    data.header.earth_rotation_rad_s = kOrbitEarthRotationRadS;
    data.header.default_elevation_mask_rad = options.elevation_mask_degrees * kOrbitDegToRad;
    data.header.timeline_start_seconds = 0.0f;
    data.header.timeline_step_seconds = options.step_seconds;
    data.header.timeline_duration_seconds = options.horizon_seconds;
    data.header.timeline_sample_count =
        static_cast<std::uint64_t>(std::floor(
            static_cast<double>(options.horizon_seconds) / options.step_seconds)) + 1u;
    data.header.predictor_model = kOrbitModelKeplerJ2Secular;
    data.header.source_format = kOrbitSourceOmmCsv;
    const char source_name[] = "CelesTrak GP OMM CSV / GPS-OPS";
    std::memcpy(data.header.source_name, source_name,
                std::min(sizeof(source_name), sizeof(data.header.source_name)));

    data.header.reference_unix_microseconds = std::max_element(
        rows.begin(), rows.end(), [](const OmmRow& left, const OmmRow& right) {
            return left.epoch_microseconds < right.epoch_microseconds;
        })->epoch_microseconds;
    data.header.reference_gmst_rad = gmst_at_unix_microseconds(
        data.header.reference_unix_microseconds);

    data.seeds.reserve(rows.size());
    data.strings.push_back('\0');
    for (const OmmRow& row : rows) {
        const double mean_motion = row.mean_motion_rev_day *
            static_cast<double>(kOrbitTwoPi) / 86400.0;
        const double semi_major_axis = std::cbrt(
            static_cast<double>(kOrbitMuEarthKm3S2) / (mean_motion * mean_motion));
        const double eccentricity_squared = row.eccentricity * row.eccentricity;
        const double sqrt_one_minus_e2 = std::sqrt(1.0 - eccentricity_squared);
        const double inclination = row.inclination_deg * static_cast<double>(kOrbitDegToRad);
        const double cosine_inclination = std::cos(inclination);
        const double p = semi_major_axis * (1.0 - eccentricity_squared);
        const double secular_factor = 1.5 * static_cast<double>(kOrbitEarthJ2) *
            std::pow(static_cast<double>(kOrbitEarthEquatorialRadiusKm) / p, 2.0) *
            mean_motion;
        const double raan_rate = -secular_factor * cosine_inclination;
        const double argument_rate = 0.5 * secular_factor *
            (5.0 * cosine_inclination * cosine_inclination - 1.0);
        const double mean_rate = mean_motion + 0.5 * secular_factor * sqrt_one_minus_e2 *
            (3.0 * cosine_inclination * cosine_inclination - 1.0);

        OrbitSeedDisk seed{};
        seed.norad_id = row.norad_id;
        seed.prn = row.prn;
        double wrapped_raan = std::fmod(row.raan_deg, 360.0);
        if (wrapped_raan < 0.0) wrapped_raan += 360.0;
        seed.route_sector = static_cast<std::uint8_t>(
            std::min(5.0, std::floor((wrapped_raan + 30.0) / 60.0)));
        if (seed.route_sector == 6u) seed.route_sector = 0u;
        seed.flags = 0u;
        seed.epoch_offset_seconds = static_cast<float>(
            static_cast<double>(row.epoch_microseconds - data.header.reference_unix_microseconds) / 1.0e6);
        seed.semi_major_axis_km = static_cast<float>(semi_major_axis);
        seed.eccentricity = static_cast<float>(row.eccentricity);
        seed.sqrt_one_minus_e2 = static_cast<float>(sqrt_one_minus_e2);
        seed.inclination_rad = static_cast<float>(inclination);
        seed.raan_rad = static_cast<float>(wrapped_raan * static_cast<double>(kOrbitDegToRad));
        seed.argument_perigee_rad = static_cast<float>(
            row.argument_perigee_deg * static_cast<double>(kOrbitDegToRad));
        seed.mean_anomaly_rad = static_cast<float>(
            row.mean_anomaly_deg * static_cast<double>(kOrbitDegToRad));
        seed.mean_motion_rad_s = static_cast<float>(mean_motion);
        seed.raan_rate_rad_s = static_cast<float>(raan_rate);
        seed.argument_perigee_rate_rad_s = static_cast<float>(argument_rate);
        seed.mean_anomaly_rate_rad_s = static_cast<float>(mean_rate);
        seed.lineage_seed = mix32(row.norad_id ^ options.seed ^
                                  static_cast<std::uint32_t>(fnv1a64(
                                      row.object_id.data(), row.object_id.size())));
        seed.name_offset = append_string(data.strings, row.object_name + " | " + row.object_id);
        data.seeds.push_back(seed);
    }

    if (data.seeds.size() > kOrbitMaxGpuSeeds) {
        // KLOC1 itself supports more records; the bundled CUDA benchmark uses
        // constant memory and intentionally caps its direct path at 256.
    }

    const std::uint64_t seed_payload_hash = fnv1a64(
        data.seeds.data(), data.seeds.size() * sizeof(OrbitSeedDisk));
    const std::uint32_t tile_count = static_cast<std::uint32_t>(std::ceil(
        static_cast<double>(options.horizon_seconds) / options.tile_seconds));
    if (tile_count == 0u || tile_count > kOrbitMaxGpuNodes) {
        throw std::invalid_argument("timeline creates more than 256 chain nodes; increase --tile-seconds");
    }
    data.nodes.reserve(tile_count);
    std::uint64_t parent_hash = seed_payload_hash ^ data.header.source_hash;
    for (std::uint32_t index = 0u; index < tile_count; ++index) {
        OrbitTimelineNodeDisk node{};
        node.parent_index = index == 0u ? kNoOrbitParent : index - 1u;
        node.node_index = index;
        node.flags = kOrbitNodeTimelineTile | (index == 0u ? kOrbitNodeCheckpoint : 0u);
        node.chain_seed = mix32(options.seed ^ index ^ static_cast<std::uint32_t>(parent_hash));
        node.start_seconds = static_cast<float>(index) * options.tile_seconds;
        node.duration_seconds = std::min(
            options.tile_seconds, options.horizon_seconds - node.start_seconds);
        node.step_seconds = options.step_seconds;
        node.parent_hash = parent_hash;
        node.source_hash = data.header.source_hash;
        node.epoch_begin = static_cast<std::uint32_t>(std::llround(
            static_cast<double>(node.start_seconds) / options.step_seconds));
        node.epoch_count = static_cast<std::uint32_t>(std::llround(
            static_cast<double>(node.duration_seconds) / options.step_seconds));
        node.self_hash = hash_node(node);
        parent_hash = node.self_hash;
        data.nodes.push_back(node);
    }
    data.header.chain_hash = data.nodes.back().self_hash;
    initialize_offsets(data);
    data.header.payload_hash = payload_hash(data);
    validate_orbit_data(data, true);
    return data;
}

void validate_orbit_data(const OrbitData& data, bool verify_hashes) {
    require_little_endian();
    if (std::memcmp(data.header.magic, kOrbitMagic.data(), kOrbitMagic.size()) != 0) {
        throw std::runtime_error("invalid KLOC1 magic");
    }
    if (data.header.version != kOrbitFormatVersion ||
        data.header.header_bytes != sizeof(OrbitHeaderDisk) ||
        data.header.seed_bytes != sizeof(OrbitSeedDisk) ||
        data.header.node_bytes != sizeof(OrbitTimelineNodeDisk)) {
        throw std::runtime_error("unsupported KLOC1 version or ABI size");
    }
    if (data.header.seed_count != data.seeds.size() ||
        data.header.node_count != data.nodes.size() ||
        data.header.strings_bytes != data.strings.size()) {
        throw std::runtime_error("KLOC1 header counts do not match loaded payloads");
    }
    if (data.seeds.empty() || data.nodes.empty() || data.strings.empty() || data.strings.front() != '\0') {
        throw std::runtime_error("KLOC1 requires seeds, chain nodes, and a NUL-prefixed string table");
    }
    const std::uint64_t expected_seeds_offset = sizeof(OrbitHeaderDisk);
    const std::uint64_t expected_nodes_offset = expected_seeds_offset +
        data.seeds.size() * sizeof(OrbitSeedDisk);
    const std::uint64_t expected_strings_offset = expected_nodes_offset +
        data.nodes.size() * sizeof(OrbitTimelineNodeDisk);
    if (data.header.seeds_offset != expected_seeds_offset ||
        data.header.nodes_offset != expected_nodes_offset ||
        data.header.strings_offset != expected_strings_offset) {
        throw std::runtime_error("KLOC1 payload offsets are noncanonical");
    }
    if (!(data.header.timeline_step_seconds > 0.0f) ||
        !(data.header.timeline_duration_seconds > 0.0f) ||
        data.header.timeline_sample_count < 2u) {
        throw std::runtime_error("KLOC1 timeline is invalid");
    }
    for (const OrbitSeedDisk& seed : data.seeds) {
        if (seed.name_offset >= data.strings.size()) {
            throw std::runtime_error("KLOC1 seed name offset is outside string table");
        }
        const auto begin = data.strings.begin() + seed.name_offset;
        if (std::find(begin, data.strings.end(), '\0') == data.strings.end()) {
            throw std::runtime_error("KLOC1 seed name is not NUL-terminated");
        }
        if (!(seed.semi_major_axis_km > data.header.earth_equatorial_radius_km) ||
            seed.eccentricity < 0.0f || seed.eccentricity >= 1.0f ||
            !std::isfinite(seed.mean_anomaly_rate_rad_s)) {
            throw std::runtime_error("KLOC1 contains an invalid orbit seed");
        }
    }
    std::uint64_t parent_hash = fnv1a64(
        data.seeds.data(), data.seeds.size() * sizeof(OrbitSeedDisk)) ^ data.header.source_hash;
    for (std::uint32_t index = 0u; index < data.nodes.size(); ++index) {
        const OrbitTimelineNodeDisk& node = data.nodes[index];
        if (node.node_index != index ||
            node.parent_index != (index == 0u ? kNoOrbitParent : index - 1u) ||
            node.parent_hash != parent_hash || node.source_hash != data.header.source_hash ||
            !(node.duration_seconds > 0.0f) || !(node.step_seconds > 0.0f)) {
            throw std::runtime_error("KLOC1 timeline chain metadata is invalid");
        }
        if (verify_hashes && node.self_hash != hash_node(node)) {
            throw std::runtime_error("KLOC1 timeline node hash mismatch");
        }
        parent_hash = node.self_hash;
    }
    if (data.header.chain_hash != data.nodes.back().self_hash) {
        throw std::runtime_error("KLOC1 terminal chain hash mismatch");
    }
    if (verify_hashes && data.header.payload_hash != payload_hash(data)) {
        throw std::runtime_error("KLOC1 payload hash mismatch");
    }
}

void save_orbit_data(const std::filesystem::path& path, const OrbitData& input) {
    require_little_endian();
    OrbitData data = input;
    initialize_offsets(data);
    data.header.chain_hash = data.nodes.empty() ? 0u : data.nodes.back().self_hash;
    data.header.payload_hash = payload_hash(data);
    validate_orbit_data(data, true);
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    if (!output) throw std::runtime_error("unable to create KLOC1 file: " + path.string());
    output.write(reinterpret_cast<const char*>(&data.header), sizeof(data.header));
    output.write(reinterpret_cast<const char*>(data.seeds.data()),
                 static_cast<std::streamsize>(data.seeds.size() * sizeof(OrbitSeedDisk)));
    output.write(reinterpret_cast<const char*>(data.nodes.data()),
                 static_cast<std::streamsize>(data.nodes.size() * sizeof(OrbitTimelineNodeDisk)));
    output.write(data.strings.data(), static_cast<std::streamsize>(data.strings.size()));
    if (!output) throw std::runtime_error("failed while writing KLOC1 file: " + path.string());
}

OrbitData load_orbit_data(const std::filesystem::path& path) {
    require_little_endian();
    std::ifstream input(path, std::ios::binary);
    if (!input) throw std::runtime_error("unable to open KLOC1 file: " + path.string());
    input.seekg(0, std::ios::end);
    const std::streamoff end = input.tellg();
    if (end < static_cast<std::streamoff>(sizeof(OrbitHeaderDisk))) {
        throw std::runtime_error("KLOC1 file is shorter than its header");
    }
    const std::uint64_t file_bytes = static_cast<std::uint64_t>(end);
    input.seekg(0, std::ios::beg);

    OrbitData data{};
    input.read(reinterpret_cast<char*>(&data.header), sizeof(data.header));
    if (!input) throw std::runtime_error("failed while reading KLOC1 header");
    if (std::memcmp(data.header.magic, kOrbitMagic.data(), kOrbitMagic.size()) != 0) {
        throw std::runtime_error("invalid KLOC1 magic");
    }
    if (data.header.seed_count > std::numeric_limits<std::size_t>::max() / sizeof(OrbitSeedDisk) ||
        data.header.node_count > std::numeric_limits<std::size_t>::max() / sizeof(OrbitTimelineNodeDisk) ||
        data.header.strings_bytes > std::numeric_limits<std::size_t>::max()) {
        throw std::runtime_error("KLOC1 payload is too large for this host");
    }
    const std::uint64_t expected_end = data.header.strings_offset + data.header.strings_bytes;
    if (expected_end != file_bytes) {
        throw std::runtime_error("KLOC1 file size does not match header offsets");
    }
    data.seeds.resize(static_cast<std::size_t>(data.header.seed_count));
    data.nodes.resize(static_cast<std::size_t>(data.header.node_count));
    data.strings.resize(static_cast<std::size_t>(data.header.strings_bytes));
    input.seekg(static_cast<std::streamoff>(data.header.seeds_offset), std::ios::beg);
    input.read(reinterpret_cast<char*>(data.seeds.data()),
               static_cast<std::streamsize>(data.seeds.size() * sizeof(OrbitSeedDisk)));
    input.seekg(static_cast<std::streamoff>(data.header.nodes_offset), std::ios::beg);
    input.read(reinterpret_cast<char*>(data.nodes.data()),
               static_cast<std::streamsize>(data.nodes.size() * sizeof(OrbitTimelineNodeDisk)));
    input.seekg(static_cast<std::streamoff>(data.header.strings_offset), std::ios::beg);
    input.read(data.strings.data(), static_cast<std::streamsize>(data.strings.size()));
    if (!input) throw std::runtime_error("failed while reading KLOC1 payload");
    validate_orbit_data(data, true);
    return data;
}

OrbitStats inspect_orbit_data(const OrbitData& data, std::uint64_t actual_file_bytes) {
    validate_orbit_data(data, true);
    OrbitStats stats{};
    stats.seed_count = data.seeds.size();
    stats.node_count = data.nodes.size();
    stats.seed_bytes = data.seeds.size() * sizeof(OrbitSeedDisk);
    stats.node_bytes = data.nodes.size() * sizeof(OrbitTimelineNodeDisk);
    stats.string_bytes = data.strings.size();
    stats.source_bytes = data.header.source_bytes;
    stats.file_bytes = actual_file_bytes != 0u
        ? actual_file_bytes
        : sizeof(OrbitHeaderDisk) + stats.seed_bytes + stats.node_bytes + stats.string_bytes;
    stats.timeline_samples = data.header.timeline_sample_count;
    const long double dense = static_cast<long double>(stats.timeline_samples) *
        static_cast<long double>(stats.seed_count) * 16.0L;
    stats.equivalent_dense_float4_bytes = dense > static_cast<long double>(std::numeric_limits<std::uint64_t>::max())
        ? std::numeric_limits<std::uint64_t>::max()
        : static_cast<std::uint64_t>(dense);
    stats.ratio_vs_dense_float4 = stats.file_bytes != 0u
        ? static_cast<double>(dense / static_cast<long double>(stats.file_bytes))
        : 0.0;
    stats.source_to_container_ratio = stats.file_bytes != 0u
        ? static_cast<double>(stats.source_bytes) / static_cast<double>(stats.file_bytes)
        : 0.0;
    return stats;
}

OrbitView make_orbit_view(const OrbitData& data) {
    validate_orbit_data(data, false);
    if (data.seeds.size() > std::numeric_limits<std::uint32_t>::max() ||
        data.nodes.size() > std::numeric_limits<std::uint32_t>::max()) {
        throw std::runtime_error("KLOC1 view exceeds 32-bit GPU counts");
    }
    return {
        data.seeds.data(),
        data.nodes.data(),
        static_cast<std::uint32_t>(data.seeds.size()),
        static_cast<std::uint32_t>(data.nodes.size()),
        data.header.earth_rotation_rad_s,
        data.header.reference_gmst_rad,
        data.header.timeline_start_seconds,
        data.header.timeline_duration_seconds,
    };
}

std::string orbit_string_at(const OrbitData& data, std::uint32_t offset) {
    if (offset >= data.strings.size()) throw std::out_of_range("orbit string offset outside table");
    const char* begin = data.strings.data() + offset;
    const char* end = static_cast<const char*>(std::memchr(begin, '\0', data.strings.size() - offset));
    if (end == nullptr) throw std::runtime_error("unterminated orbit string");
    return std::string(begin, end);
}

std::string format_unix_microseconds_iso8601(std::int64_t unix_microseconds) {
    std::int64_t seconds = unix_microseconds / 1000000ll;
    std::int64_t fraction = unix_microseconds % 1000000ll;
    if (fraction < 0) {
        fraction += 1000000ll;
        --seconds;
    }
    std::int64_t days = seconds / 86400ll;
    std::int64_t seconds_of_day = seconds % 86400ll;
    if (seconds_of_day < 0) {
        seconds_of_day += 86400ll;
        --days;
    }
    const auto civil = civil_from_days(days);
    const int hour = static_cast<int>(seconds_of_day / 3600ll);
    const int minute = static_cast<int>((seconds_of_day % 3600ll) / 60ll);
    const int second = static_cast<int>(seconds_of_day % 60ll);
    std::ostringstream output;
    output << std::setfill('0')
           << std::setw(4) << civil[0] << '-'
           << std::setw(2) << civil[1] << '-'
           << std::setw(2) << civil[2] << 'T'
           << std::setw(2) << hour << ':'
           << std::setw(2) << minute << ':'
           << std::setw(2) << second << '.'
           << std::setw(6) << fraction << 'Z';
    return output.str();
}

OrbitGroundStation make_ground_station(
    float latitude_degrees,
    float longitude_degrees,
    float altitude_km,
    float elevation_mask_degrees,
    float crossing_band_degrees,
    float maximum_slant_range_km,
    std::uint32_t route_filter) {
    if (!std::isfinite(latitude_degrees) || latitude_degrees < -90.0f || latitude_degrees > 90.0f ||
        !std::isfinite(longitude_degrees) ||
        !std::isfinite(altitude_km) || altitude_km < -10.0f ||
        !std::isfinite(elevation_mask_degrees) || elevation_mask_degrees <= -90.0f ||
        elevation_mask_degrees >= 90.0f ||
        !std::isfinite(crossing_band_degrees) || crossing_band_degrees <= 0.0f ||
        !std::isfinite(maximum_slant_range_km) || maximum_slant_range_km <= 0.0f) {
        throw std::invalid_argument("invalid ground-station/query parameters");
    }
    const double latitude = static_cast<double>(latitude_degrees) * kOrbitDegToRad;
    const double longitude = static_cast<double>(longitude_degrees) * kOrbitDegToRad;
    constexpr double flattening = 1.0 / 298.257223563;
    constexpr double eccentricity_squared = flattening * (2.0 - flattening);
    const double sine_latitude = std::sin(latitude);
    const double cosine_latitude = std::cos(latitude);
    const double normal = static_cast<double>(kOrbitEarthEquatorialRadiusKm) /
        std::sqrt(1.0 - eccentricity_squared * sine_latitude * sine_latitude);
    const Vec3 ecef{
        static_cast<float>((normal + altitude_km) * cosine_latitude * std::cos(longitude)),
        static_cast<float>((normal + altitude_km) * cosine_latitude * std::sin(longitude)),
        static_cast<float>((normal * (1.0 - eccentricity_squared) + altitude_km) * sine_latitude),
    };
    const float elevation_mask_rad = elevation_mask_degrees * kOrbitDegToRad;
    const float band_rad = crossing_band_degrees * kOrbitDegToRad;
    const float base_sine = std::sinf(elevation_mask_rad);
    const float upper_sine = std::sinf(elevation_mask_rad + band_rad);
    return {
        ecef,
        base_sine,
        std::max(std::fabs(upper_sine - base_sine), 1.0e-7f),
        maximum_slant_range_km,
        route_filter,
    };
}

} // namespace klb
