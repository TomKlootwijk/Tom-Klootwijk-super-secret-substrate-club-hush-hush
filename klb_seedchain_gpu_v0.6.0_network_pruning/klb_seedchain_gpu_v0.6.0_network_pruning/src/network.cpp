#include "klb/network.hpp"

#include <algorithm>
#include <bit>
#include <chrono>
#include <cmath>
#include <cctype>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string_view>
#include <unordered_map>

namespace klb {
namespace {

std::string trim(std::string value) {
    auto not_space = [](unsigned char c) { return !std::isspace(c); };
    value.erase(value.begin(), std::find_if(value.begin(), value.end(), not_space));
    value.erase(std::find_if(value.rbegin(), value.rend(), not_space).base(), value.end());
    return value;
}

std::string upper(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
        return static_cast<char>(std::toupper(c));
    });
    return value;
}

std::vector<std::string> parse_csv_line(const std::string& line) {
    std::vector<std::string> fields;
    std::string field;
    bool quoted = false;
    for (std::size_t index = 0; index < line.size(); ++index) {
        const char c = line[index];
        if (quoted) {
            if (c == '"') {
                if (index + 1u < line.size() && line[index + 1u] == '"') {
                    field.push_back('"');
                    ++index;
                } else {
                    quoted = false;
                }
            } else {
                field.push_back(c);
            }
        } else if (c == ',') {
            fields.push_back(field);
            field.clear();
        } else if (c == '"') {
            quoted = true;
        } else {
            field.push_back(c);
        }
    }
    if (quoted) throw std::runtime_error("unterminated quoted CSV field");
    fields.push_back(field);
    return fields;
}

std::string csv_escape(const std::string& value) {
    if (value.find_first_of(",\"\r\n") == std::string::npos) return value;
    std::string escaped = "\"";
    for (char c : value) {
        if (c == '"') escaped.push_back('"');
        escaped.push_back(c);
    }
    escaped.push_back('"');
    return escaped;
}

double parse_double(const std::string& value, const char* field) {
    std::size_t consumed = 0u;
    double result = 0.0;
    try {
        result = std::stod(trim(value), &consumed);
    } catch (const std::exception&) {
        throw std::runtime_error(std::string("invalid numeric station field ") + field + ": " + value);
    }
    const std::string cleaned = trim(value);
    if (consumed != cleaned.size() || !std::isfinite(result)) {
        throw std::runtime_error(std::string("invalid numeric station field ") + field + ": " + value);
    }
    return result;
}

std::uint32_t parse_u32(const std::string& value, const char* field) {
    const std::string cleaned = trim(value);
    std::size_t consumed = 0u;
    unsigned long result = 0ul;
    try {
        result = std::stoul(cleaned, &consumed, 0);
    } catch (const std::exception&) {
        throw std::runtime_error(std::string("invalid station field ") + field + ": " + value);
    }
    if (consumed != cleaned.size() || result > std::numeric_limits<std::uint32_t>::max()) {
        throw std::runtime_error(std::string("invalid station field ") + field + ": " + value);
    }
    return static_cast<std::uint32_t>(result);
}

std::vector<std::string> split_mask(const std::string& text) {
    std::vector<std::string> parts;
    std::string current;
    for (char c : text) {
        if (c == '|' || c == '+' || c == ';' || c == '/') {
            if (!trim(current).empty()) parts.push_back(upper(trim(current)));
            current.clear();
        } else {
            current.push_back(c);
        }
    }
    if (!trim(current).empty()) parts.push_back(upper(trim(current)));
    return parts;
}

bool contains(const std::string& upper_name, std::string_view token) {
    return upper_name.find(token) != std::string::npos;
}

std::uint32_t all_station_bits(std::size_t count) {
    if (count == 0u) return 0u;
    if (count >= 32u) return 0xffffffffu;
    return (std::uint32_t{1u} << static_cast<unsigned>(count)) - 1u;
}

std::uint32_t selected_mask(const NetworkObjectProfile& profile,
                            NetworkPairMode mode,
                            std::size_t station_count) {
    if (mode == NetworkPairMode::All) return all_station_bits(station_count);
    if (mode == NetworkPairMode::Support) return profile.support_station_mask;
    return profile.active_station_mask;
}

bool event_less(const NetworkEvent& left, const NetworkEvent& right) {
    if (left.station_id != right.station_id) return left.station_id < right.station_id;
    if (left.norad_id != right.norad_id) return left.norad_id < right.norad_id;
    if (left.interval_index != right.interval_index) return left.interval_index < right.interval_index;
    if (left.type != right.type) return left.type < right.type;
    return left.crossing_seconds < right.crossing_seconds;
}

} // namespace

std::uint32_t parse_network_orbit_mask(const std::string& text) {
    const std::string cleaned = upper(trim(text));
    if (cleaned.empty() || cleaned == "ALL" || cleaned == "ANY" || cleaned == "*") {
        return kNetworkOrbitAll;
    }
    std::uint32_t result = 0u;
    for (const std::string& part : split_mask(cleaned)) {
        if (part == "LEO") result |= kNetworkOrbitLeo;
        else if (part == "MEO") result |= kNetworkOrbitMeo;
        else if (part == "GEO" || part == "GSO") result |= kNetworkOrbitGeo;
        else if (part == "HEO" || part == "DEEP") result |= kNetworkOrbitHeo;
        else throw std::runtime_error("unknown orbit-mask token: " + part);
    }
    if (result == 0u) throw std::runtime_error("empty orbit mask");
    return result;
}

std::uint32_t parse_network_service_mask(const std::string& text) {
    const std::string cleaned = upper(trim(text));
    if (cleaned.empty() || cleaned == "ALL" || cleaned == "ANY" || cleaned == "*") {
        return kNetworkServiceAll;
    }
    std::uint32_t result = 0u;
    for (const std::string& part : split_mask(cleaned)) {
        if (part == "NAV" || part == "NAVIGATION") result |= kNetworkServiceNavigation;
        else if (part == "RELAY" || part == "COMM") result |= kNetworkServiceRelay;
        else if (part == "EO" || part == "EARTH_OBS" || part == "EARTH-OBS") {
            result |= kNetworkServiceEarthObservation;
        } else if (part == "SCIENCE" || part == "SCI") result |= kNetworkServiceScience;
        else if (part == "CREWED" || part == "CREW") result |= kNetworkServiceCrewed;
        else throw std::runtime_error("unknown service-mask token: " + part);
    }
    if (result == 0u) throw std::runtime_error("empty service mask");
    return result;
}

std::uint32_t parse_network_route_mask(const std::string& text) {
    const std::string cleaned = upper(trim(text));
    if (cleaned.empty() || cleaned == "ALL" || cleaned == "ANY" || cleaned == "*") return 0x3fu;
    std::uint32_t result = 0u;
    for (const std::string& part : split_mask(cleaned)) {
        const std::uint32_t route = parse_u32(part, "route_mask");
        if (route > 5u) throw std::runtime_error("route values must be in 0..5");
        result |= std::uint32_t{1u} << route;
    }
    if (result == 0u) throw std::runtime_error("empty route mask");
    return result;
}

std::string network_orbit_mask_string(std::uint32_t mask) {
    std::vector<std::string> parts;
    if ((mask & kNetworkOrbitLeo) != 0u) parts.emplace_back("LEO");
    if ((mask & kNetworkOrbitMeo) != 0u) parts.emplace_back("MEO");
    if ((mask & kNetworkOrbitGeo) != 0u) parts.emplace_back("GEO");
    if ((mask & kNetworkOrbitHeo) != 0u) parts.emplace_back("HEO");
    std::ostringstream out;
    for (std::size_t i = 0; i < parts.size(); ++i) {
        if (i != 0u) out << '|';
        out << parts[i];
    }
    return out.str();
}

std::string network_service_mask_string(std::uint32_t mask) {
    std::vector<std::string> parts;
    if ((mask & kNetworkServiceNavigation) != 0u) parts.emplace_back("NAV");
    if ((mask & kNetworkServiceRelay) != 0u) parts.emplace_back("RELAY");
    if ((mask & kNetworkServiceEarthObservation) != 0u) parts.emplace_back("EARTH_OBS");
    if ((mask & kNetworkServiceScience) != 0u) parts.emplace_back("SCIENCE");
    if ((mask & kNetworkServiceCrewed) != 0u) parts.emplace_back("CREWED");
    std::ostringstream out;
    for (std::size_t i = 0; i < parts.size(); ++i) {
        if (i != 0u) out << '|';
        out << parts[i];
    }
    return out.str();
}

std::vector<NetworkStation> load_network_stations_csv(const std::filesystem::path& path) {
    std::ifstream input(path);
    if (!input) throw std::runtime_error("unable to open station CSV: " + path.string());
    std::string line;
    if (!std::getline(input, line)) throw std::runtime_error("station CSV is empty");
    const std::vector<std::string> headings = parse_csv_line(line);
    std::unordered_map<std::string, std::size_t> columns;
    for (std::size_t index = 0; index < headings.size(); ++index) {
        columns.emplace(upper(trim(headings[index])), index);
    }
    const std::vector<std::string> required{
        "STATION_ID", "NAME", "LATITUDE_DEG", "LONGITUDE_DEG", "ALTITUDE_KM",
        "ELEVATION_MASK_DEG", "CROSSING_BAND_DEG", "MAX_RANGE_KM",
        "ORBIT_MASK", "SERVICE_MASK", "ROUTE_MASK",
    };
    for (const std::string& heading : required) {
        if (!columns.contains(heading)) throw std::runtime_error("station CSV lacks column " + heading);
    }
    auto field = [&](const std::vector<std::string>& fields, const char* name) -> const std::string& {
        const std::size_t index = columns.at(name);
        if (index >= fields.size()) throw std::runtime_error(std::string("missing station field ") + name);
        return fields[index];
    };

    std::vector<NetworkStation> result;
    std::uint64_t line_number = 1u;
    while (std::getline(input, line)) {
        ++line_number;
        if (trim(line).empty() || trim(line).starts_with('#')) continue;
        const std::vector<std::string> fields = parse_csv_line(line);
        try {
            NetworkStation station{};
            station.gpu.station_id = parse_u32(field(fields, "STATION_ID"), "station_id");
            station.name = trim(field(fields, "NAME"));
            station.latitude_degrees = parse_double(field(fields, "LATITUDE_DEG"), "latitude_deg");
            station.longitude_degrees = parse_double(field(fields, "LONGITUDE_DEG"), "longitude_deg");
            station.altitude_km = parse_double(field(fields, "ALTITUDE_KM"), "altitude_km");
            station.elevation_mask_degrees = parse_double(field(fields, "ELEVATION_MASK_DEG"), "elevation_mask_deg");
            station.crossing_band_degrees = parse_double(field(fields, "CROSSING_BAND_DEG"), "crossing_band_deg");
            const double max_range = parse_double(field(fields, "MAX_RANGE_KM"), "max_range_km");
            station.gpu.orbit_mask = parse_network_orbit_mask(field(fields, "ORBIT_MASK"));
            station.gpu.service_mask = parse_network_service_mask(field(fields, "SERVICE_MASK"));
            station.gpu.route_mask = parse_network_route_mask(field(fields, "ROUTE_MASK"));
            if (station.name.empty()) throw std::runtime_error("station name is empty");
            if (station.latitude_degrees < -90.0 || station.latitude_degrees > 90.0 ||
                station.longitude_degrees < -180.0 || station.longitude_degrees > 180.0 ||
                station.elevation_mask_degrees <= -90.0 || station.elevation_mask_degrees >= 90.0 ||
                station.crossing_band_degrees <= 0.0 || max_range <= 0.0) {
                throw std::runtime_error("station values outside supported range");
            }
            station.gpu.ground = make_sgp4_ground_station(
                station.latitude_degrees, station.longitude_degrees, station.altitude_km,
                station.elevation_mask_degrees, station.crossing_band_degrees,
                max_range, 0xffffffffu);
            result.push_back(station);
        } catch (const std::exception& error) {
            throw std::runtime_error("station CSV line " + std::to_string(line_number) + ": " + error.what());
        }
    }
    if (result.empty()) throw std::runtime_error("station CSV contains no stations");
    if (result.size() > 32u) throw std::runtime_error("network station bitmask supports at most 32 stations");
    std::vector<std::uint32_t> ids;
    ids.reserve(result.size());
    for (const NetworkStation& station : result) ids.push_back(station.gpu.station_id);
    std::sort(ids.begin(), ids.end());
    if (std::adjacent_find(ids.begin(), ids.end()) != ids.end()) {
        throw std::runtime_error("station IDs must be unique");
    }
    return result;
}

NetworkObjectProfile classify_network_object(const Sgp4SeedDisk& seed,
                                              const Sgp4Record& record,
                                              const std::string& name) {
    if (!(record.no_unkozai > 0.0) || !(record.radiusearthkm > 0.0)) {
        throw std::runtime_error("invalid initialized SGP4 record for network classification");
    }
    NetworkObjectProfile profile{};
    profile.period_minutes = kSgp4TwoPi / record.no_unkozai;
    const double semimajor_er = std::pow(record.xke / record.no_unkozai, 2.0 / 3.0);
    const double semimajor_km = semimajor_er * record.radiusearthkm;
    profile.perigee_altitude_km = semimajor_km * (1.0 - seed.eccentricity) - record.radiusearthkm;
    profile.apogee_altitude_km = semimajor_km * (1.0 + seed.eccentricity) - record.radiusearthkm;
    profile.maximum_abs_latitude_rad = std::asin(std::fabs(std::sin(seed.inclination_rad)));

    if (seed.eccentricity >= 0.20 ||
        (profile.apogee_altitude_km > 60000.0 && profile.perigee_altitude_km < 25000.0)) {
        profile.orbit_class = kNetworkOrbitHeo;
    } else if (profile.period_minutes < 225.0) {
        profile.orbit_class = kNetworkOrbitLeo;
    } else if (profile.period_minutes >= 1200.0 && profile.period_minutes <= 1600.0 &&
               seed.eccentricity < 0.10) {
        profile.orbit_class = kNetworkOrbitGeo;
    } else {
        profile.orbit_class = kNetworkOrbitMeo;
    }

    const std::string key = upper(name);
    if (contains(key, "GPS")) {
        profile.service_mask = kNetworkServiceNavigation;
    } else if (contains(key, "TDRS")) {
        profile.service_mask = kNetworkServiceRelay;
    } else if (contains(key, "ISS")) {
        profile.service_mask = kNetworkServiceCrewed | kNetworkServiceScience;
    } else if (contains(key, "TERRA") || contains(key, "AQUA") ||
               contains(key, "AURA") || contains(key, "GPM") ||
               contains(key, "NOAA")) {
        profile.service_mask = kNetworkServiceEarthObservation | kNetworkServiceScience;
    } else {
        profile.service_mask = kNetworkServiceScience;
    }
    return profile;
}

bool network_support_possible(const NetworkObjectProfile& object,
                              const Sgp4Record& record,
                              const NetworkStationGpu& station) {
    const double station_radius = std::sqrt(
        station.ground.ecef_km[0] * station.ground.ecef_km[0] +
        station.ground.ecef_km[1] * station.ground.ecef_km[1] +
        station.ground.ecef_km[2] * station.ground.ecef_km[2]);
    if (!(station_radius > 0.0) || !(record.radiusearthkm > 0.0)) return true;

    const double station_latitude = std::asin(std::clamp(
        station.ground.ecef_km[2] / station_radius, -1.0, 1.0));
    const double minimum_central_angle = std::max(
        0.0, std::fabs(station_latitude) - object.maximum_abs_latitude_rad);
    const double cosine = std::cos(minimum_central_angle);

    const double perigee_radius = record.radiusearthkm + object.perigee_altitude_km;
    const double apogee_radius = record.radiusearthkm + object.apogee_altitude_km;
    // The envelope intentionally expands the SGP4 mean-element range. It is a
    // rejection test, so false positives are acceptable while false negatives
    // are checked by the all-pairs oracle.
    const double radial_margin = std::max(1000.0, 0.05 * std::max(apogee_radius, record.radiusearthkm));
    const double minimum_radius = std::max(record.radiusearthkm, perigee_radius - radial_margin);
    const double maximum_radius = std::max(minimum_radius, apogee_radius + radial_margin);

    const double optimum_radius = std::clamp(station_radius * cosine, minimum_radius, maximum_radius);
    const double minimum_range_squared = std::max(0.0,
        optimum_radius * optimum_radius + station_radius * station_radius -
        2.0 * optimum_radius * station_radius * cosine);
    const double conservative_range_margin = 1000.0;
    if (std::sqrt(minimum_range_squared) >
        station.ground.maximum_slant_range_km + conservative_range_margin) {
        return false;
    }

    // Do not reject on the elevation guard here. The plan's support stage is
    // deliberately limited to the declared slant-range domain so its survivor
    // count can be compared directly with the runtime support predicate.
    // Elevation remains the later relation guard, as required by the
    // support -> compatibility -> guard ordering.
    (void)maximum_radius;
    return true;
}

NetworkPlan build_network_plan(const Sgp4Data& data,
                               const std::vector<Sgp4Record>& records,
                               const std::vector<NetworkStation>& stations) {
    if (data.seeds.size() != records.size()) throw std::invalid_argument("seed/record count mismatch");
    if (stations.empty() || stations.size() > 32u) throw std::invalid_argument("station count must be 1..32");
    NetworkPlan plan{};
    plan.objects.reserve(data.seeds.size());
    for (std::size_t object_index = 0; object_index < data.seeds.size(); ++object_index) {
        NetworkObjectProfile profile = classify_network_object(
            data.seeds[object_index], records[object_index],
            sgp4_string_at(data, data.seeds[object_index].name_offset));
        const std::uint32_t route = sgp4_seed_route(data.seeds[object_index]);
        for (std::size_t station_index = 0; station_index < stations.size(); ++station_index) {
            const std::uint32_t bit = std::uint32_t{1u} << static_cast<unsigned>(station_index);
            const NetworkStationGpu& station = stations[station_index].gpu;
            if (network_support_possible(profile, records[object_index], station)) {
                profile.support_station_mask |= bit;
                if (network_policy_compatible(profile, station, route)) {
                    profile.active_station_mask |= bit;
                }
            }
        }
        plan.objects.push_back(profile);
    }
    plan.stats.objects = data.seeds.size();
    plan.stats.stations = stations.size();
    plan.stats.total_pairs = data.seeds.size() * stations.size();
    for (const NetworkObjectProfile& object : plan.objects) {
        plan.stats.support_pairs += std::popcount(object.support_station_mask);
        plan.stats.active_pairs += std::popcount(object.active_station_mask);
    }
    plan.stats.support_rejection_gain = plan.stats.support_pairs == 0u
        ? std::numeric_limits<double>::infinity()
        : static_cast<double>(plan.stats.total_pairs) / static_cast<double>(plan.stats.support_pairs);
    plan.stats.compatibility_rejection_gain = plan.stats.active_pairs == 0u
        ? std::numeric_limits<double>::infinity()
        : static_cast<double>(plan.stats.support_pairs) / static_cast<double>(plan.stats.active_pairs);
    plan.stats.total_rejection_gain = plan.stats.active_pairs == 0u
        ? std::numeric_limits<double>::infinity()
        : static_cast<double>(plan.stats.total_pairs) / static_cast<double>(plan.stats.active_pairs);
    return plan;
}

NetworkRunResult run_network_cpu(const Sgp4Data& data,
                                 const std::vector<Sgp4Record>& records,
                                 const std::vector<NetworkStation>& stations,
                                 const NetworkPlan& plan,
                                 NetworkPairMode mode,
                                 double start_seconds,
                                 double duration_seconds,
                                 double step_seconds,
                                 double dut1_seconds) {
    if (records.size() != data.seeds.size() || plan.objects.size() != data.seeds.size()) {
        throw std::invalid_argument("network run input counts do not match");
    }
    if (!(duration_seconds > 0.0) || !(step_seconds > 0.0)) {
        throw std::invalid_argument("network duration and step must be positive");
    }
    const std::uint64_t intervals = static_cast<std::uint64_t>(
        std::floor(duration_seconds / step_seconds + 1.0e-12));
    if (intervals == 0u) throw std::invalid_argument("network duration is shorter than one step");
    const double reference_unix = static_cast<double>(data.header.reference_unix_microseconds) / 1.0e6;
    NetworkRunResult result{};
    result.stats.intervals = intervals;
    result.events.reserve(4096u);
    const auto begin_time = std::chrono::steady_clock::now();

    for (std::size_t object_index = 0; object_index < data.seeds.size(); ++object_index) {
        const Sgp4SeedDisk& seed = data.seeds[object_index];
        const Sgp4Record& record = records[object_index];
        const NetworkObjectProfile& profile = plan.objects[object_index];
        const std::uint32_t mask = selected_mask(profile, mode, stations.size());
        if (mask == 0u) continue;
        result.stats.relation_intervals +=
            static_cast<std::uint64_t>(std::popcount(mask)) * intervals;

        double previous_seconds = start_seconds;
        const double previous_minutes = sgp4_minutes_from_reference(seed, previous_seconds, reference_unix);
        Sgp4State previous_state = sgp4_state_at(record, previous_minutes);
        if (previous_state.error != 0) ++result.stats.propagation_failures;
        std::vector<Sgp4Visibility> previous(stations.size());
        if (previous_state.error == 0) {
            const double previous_jd = data.header.reference_julian_date + previous_seconds / 86400.0;
            for (std::size_t station_index = 0; station_index < stations.size(); ++station_index) {
                if ((mask & (std::uint32_t{1u} << static_cast<unsigned>(station_index))) == 0u) continue;
                previous[station_index] = sgp4_evaluate_visibility(
                    previous_state.position_teme_km, previous_jd, dut1_seconds,
                    stations[station_index].gpu.ground, sgp4_seed_route(seed));
                previous[station_index].compatible = network_policy_compatible(
                    profile, stations[station_index].gpu, sgp4_seed_route(seed)) ? 1u : 0u;
            }
        }

        for (std::uint64_t interval = 0u; interval < intervals; ++interval) {
            const double current_seconds = start_seconds + static_cast<double>(interval + 1u) * step_seconds;
            const double current_minutes = sgp4_minutes_from_reference(seed, current_seconds, reference_unix);
            const Sgp4State current_state = sgp4_state_at(record, current_minutes);
            ++result.stats.propagated_object_intervals;
            if (current_state.error != 0) ++result.stats.propagation_failures;
            const bool valid_pair = previous_state.error == 0 && current_state.error == 0;
            const double current_jd = data.header.reference_julian_date + current_seconds / 86400.0;

            for (std::size_t station_index = 0; station_index < stations.size(); ++station_index) {
                const std::uint32_t bit = std::uint32_t{1u} << static_cast<unsigned>(station_index);
                if ((mask & bit) == 0u) continue;
                Sgp4Visibility current{};
                if (current_state.error == 0) {
                    current = sgp4_evaluate_visibility(
                        current_state.position_teme_km, current_jd, dut1_seconds,
                        stations[station_index].gpu.ground, sgp4_seed_route(seed));
                    current.compatible = network_policy_compatible(
                        profile, stations[station_index].gpu, sgp4_seed_route(seed)) ? 1u : 0u;
                }
                const bool supported = valid_pair &&
                    (previous[station_index].supported != 0u || current.supported != 0u);
                const bool compatible = supported &&
                    previous[station_index].compatible != 0u && current.compatible != 0u;
                if (supported) ++result.stats.supported_intervals;
                if (compatible) {
                    ++result.stats.compatible_intervals;
                    ++result.stats.boundary_evaluations;
                }
                if (valid_pair && current.supported != 0u && current.compatible != 0u &&
                    current.guard <= 0.0) {
                    ++result.stats.visible_endpoints;
                }
                if (valid_pair) {
                    const Sgp4Crossing crossing = sgp4_evaluate_crossing(
                        previous[station_index], current, previous_seconds,
                        current_seconds, stations[station_index].gpu.ground.crossing_band_sin);
                    if (crossing.verified != 0u) {
                        const std::uint32_t event_type = crossing.acquisition != 0u ? 1u : 2u;
                        if (event_type == 1u) ++result.stats.acquisition_events;
                        else ++result.stats.loss_events;
                        const std::uint32_t node_index = sgp4_timeline_node_index(
                            data.nodes.data(), static_cast<std::uint32_t>(data.nodes.size()),
                            crossing.crossing_seconds);
                        const std::uint32_t base = data.nodes.empty() ? seed.lineage_seed :
                            sgp4_lineage(seed, data.nodes[node_index], interval, event_type);
                        result.events.push_back(NetworkEvent{
                            crossing.crossing_seconds,
                            crossing.minimum_abs_guard,
                            interval,
                            static_cast<std::uint32_t>(object_index),
                            static_cast<std::uint32_t>(station_index),
                            stations[station_index].gpu.station_id,
                            seed.norad_id,
                            event_type,
                            network_event_lineage(base, stations[station_index].gpu.station_id, event_type),
                        });
                    }
                }
                previous[station_index] = current;
            }
            previous_seconds = current_seconds;
            previous_state = current_state;
        }
    }
    std::sort(result.events.begin(), result.events.end(), event_less);
    result.stats.elapsed_seconds = std::chrono::duration<double>(
        std::chrono::steady_clock::now() - begin_time).count();
    return result;
}

bool network_events_equal(const std::vector<NetworkEvent>& left_input,
                          const std::vector<NetworkEvent>& right_input,
                          double crossing_tolerance_seconds,
                          double guard_tolerance) {
    if (left_input.size() != right_input.size()) return false;
    std::vector<NetworkEvent> left = left_input;
    std::vector<NetworkEvent> right = right_input;
    std::sort(left.begin(), left.end(), event_less);
    std::sort(right.begin(), right.end(), event_less);
    for (std::size_t index = 0; index < left.size(); ++index) {
        const NetworkEvent& a = left[index];
        const NetworkEvent& b = right[index];
        if (a.interval_index != b.interval_index || a.station_id != b.station_id ||
            a.norad_id != b.norad_id || a.type != b.type || a.lineage != b.lineage ||
            std::fabs(a.crossing_seconds - b.crossing_seconds) > crossing_tolerance_seconds ||
            std::fabs(a.minimum_abs_guard - b.minimum_abs_guard) > guard_tolerance) {
            return false;
        }
    }
    return true;
}

void save_network_events_csv(const std::filesystem::path& path,
                             const Sgp4Data& data,
                             const std::vector<NetworkStation>& stations,
                             const std::vector<NetworkEvent>& events) {
    if (!path.parent_path().empty()) std::filesystem::create_directories(path.parent_path());
    std::ofstream output(path, std::ios::trunc);
    if (!output) throw std::runtime_error("unable to create network event CSV: " + path.string());
    output << "event_index,event_type,event_time_utc,seconds_from_reference,interval_index,station_id,station_name,"
              "norad_id,object_name,orbit_route,lineage,minimum_abs_guard\n";
    output << std::fixed << std::setprecision(9);
    for (std::size_t index = 0; index < events.size(); ++index) {
        const NetworkEvent& event = events[index];
        const Sgp4SeedDisk& seed = data.seeds.at(event.seed_index);
        const std::int64_t event_microseconds = data.header.reference_unix_microseconds +
            static_cast<std::int64_t>(std::llround(event.crossing_seconds * 1.0e6));
        output << index << ',' << (event.type == 1u ? "acquire" : "loss") << ','
               << format_unix_microseconds_iso8601(event_microseconds) << ','
               << event.crossing_seconds << ',' << event.interval_index << ','
               << event.station_id << ',' << csv_escape(stations.at(event.station_index).name) << ','
               << event.norad_id << ',' << csv_escape(sgp4_string_at(data, seed.name_offset)) << ','
               << static_cast<unsigned>(sgp4_seed_route(seed)) << ',' << event.lineage << ','
               << event.minimum_abs_guard << '\n';
    }
}

void save_network_pairs_csv(const std::filesystem::path& path,
                            const Sgp4Data& data,
                            const std::vector<NetworkStation>& stations,
                            const NetworkPlan& plan) {
    if (!path.parent_path().empty()) std::filesystem::create_directories(path.parent_path());
    std::ofstream output(path, std::ios::trunc);
    if (!output) throw std::runtime_error("unable to create network pair CSV: " + path.string());
    output << "seed_index,norad_id,object_name,orbit_class,service_class,station_index,station_id,station_name,"
              "support_possible,compatible,active,station_orbit_mask,station_service_mask,period_min,perigee_km,apogee_km\n";
    output << std::fixed << std::setprecision(6);
    for (std::size_t object_index = 0; object_index < plan.objects.size(); ++object_index) {
        const NetworkObjectProfile& object = plan.objects[object_index];
        const Sgp4SeedDisk& seed = data.seeds.at(object_index);
        for (std::size_t station_index = 0; station_index < stations.size(); ++station_index) {
            const std::uint32_t bit = std::uint32_t{1u} << static_cast<unsigned>(station_index);
            const bool support = (object.support_station_mask & bit) != 0u;
            const bool active = (object.active_station_mask & bit) != 0u;
            const bool compatible = network_policy_compatible(
                object, stations[station_index].gpu, sgp4_seed_route(seed));
            output << object_index << ',' << seed.norad_id << ','
                   << csv_escape(sgp4_string_at(data, seed.name_offset)) << ','
                   << network_orbit_mask_string(object.orbit_class) << ','
                   << network_service_mask_string(object.service_mask) << ','
                   << station_index << ',' << stations[station_index].gpu.station_id << ','
                   << csv_escape(stations[station_index].name) << ','
                   << (support ? 1 : 0) << ',' << (compatible ? 1 : 0) << ','
                   << (active ? 1 : 0) << ','
                   << network_orbit_mask_string(stations[station_index].gpu.orbit_mask) << ','
                   << network_service_mask_string(stations[station_index].gpu.service_mask) << ','
                   << object.period_minutes << ',' << object.perigee_altitude_km << ','
                   << object.apogee_altitude_km << '\n';
        }
    }
}

} // namespace klb
