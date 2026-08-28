#include "klb/sgp4.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {

[[noreturn]] void usage(const char* executable, int exit_code) {
    std::ostream& output = exit_code == 0 ? std::cout : std::cerr;
    output
        << "KLB Full-SGP4 seed adapter, KSGP1 inspector, and query tool\n\n"
        << "Usage:\n"
        << "  " << executable << " pack-omm-csv <input.csv> <output.ksgp> [options]\n"
        << "  " << executable << " inspect <input.ksgp>\n"
        << "  " << executable << " verify <input.ksgp>\n"
        << "  " << executable << " sample <input.ksgp> [options]\n"
        << "  " << executable << " passes <input.ksgp> [options]\n"
        << "  " << executable << " compare-coarse <input.ksgp> <input.kloc> [options]\n\n"
        << "pack-omm-csv options:\n"
        << "  --horizon-hours X       Versioned timeline horizon (default 168)\n"
        << "  --step-seconds X        Declared state-sample step (default 1)\n"
        << "  --tile-hours X          Hash-linked timeline tile size (default 24)\n"
        << "  --elevation-deg X       Default ground mask metadata (default 10)\n"
        << "  --dut1-seconds X        UTC-to-UT1 offset metadata (default 0)\n"
        << "  --gravity MODEL         wgs72 (default), wgs72old, or wgs84\n"
        << "  --seed N                Chain seed, decimal or 0x-prefixed\n\n"
        << "sample options:\n"
        << "  --seconds X             Seconds from the KSGP1 reference epoch (default 0)\n"
        << "  --limit N               Number of seeds to print (default all)\n"
        << "  --dut1-seconds X        Override file DUT1 metadata\n"
        << "  --output PATH           Write CSV instead of standard output\n\n"
        << "passes options:\n"
        << "  --lat X --lon X         Ground-station latitude/longitude degrees (default 52,5)\n"
        << "  --alt-km X              Ground-station altitude kilometres (default 0.05)\n"
        << "  --elevation-deg X       Elevation guard threshold (default file metadata)\n"
        << "  --crossing-band-deg X   Sampled crossing acceptance band (default 0.25)\n"
        << "  --max-range-km X        Analytic support radius (default 33000)\n"
        << "  --route any|0..5        Optional route-sector compatibility filter\n"
        << "  --start-seconds X       Start from the KSGP1 reference epoch (default 0)\n"
        << "  --hours X               Duration (default file timeline)\n"
        << "  --step-seconds X        Sampling step (default file timeline step)\n"
        << "  --dut1-seconds X        Override file DUT1 metadata\n"
        << "  --output PATH           Write acquisition/loss event CSV (default stdout)\n\n"
        << "compare-coarse options:\n"
        << "  --hours X               Comparison duration (default 168)\n"
        << "  --step-seconds X        Comparison spacing (default 21600)\n"
        << "  --output PATH           Write per-object error CSV\n\n"
        << "The propagator is the complete Vallado/CSSI SGP4/SDP4 computational path,\n"
        << "including drag, short/long-period terms, deep-space lunar/solar terms,\n"
        << "and synchronous/half-day resonance branches. Ground visibility rotates\n"
        << "TEME to PEF with GMST and configurable DUT1; polar motion/EOP are not applied.\n";
    std::exit(exit_code);
}

std::uint64_t parse_u64(std::string_view text, const char* name) {
    std::size_t consumed = 0u;
    const std::uint64_t value = std::stoull(std::string(text), &consumed, 0);
    if (consumed != text.size()) throw std::invalid_argument(std::string(name) + " must be an integer");
    return value;
}

double parse_double(std::string_view text, const char* name) {
    std::size_t consumed = 0u;
    const double value = std::stod(std::string(text), &consumed);
    if (consumed != text.size() || !std::isfinite(value)) {
        throw std::invalid_argument(std::string(name) + " must be finite");
    }
    return value;
}

int parse_gravity(std::string_view value) {
    if (value == "wgs72") return klb::kSgp4Wgs72;
    if (value == "wgs72old") return klb::kSgp4Wgs72Old;
    if (value == "wgs84") return klb::kSgp4Wgs84;
    throw std::invalid_argument("--gravity must be wgs72, wgs72old, or wgs84");
}

const char* gravity_name(std::uint32_t value) {
    if (value == static_cast<std::uint32_t>(klb::kSgp4Wgs72Old)) return "WGS-72 old";
    if (value == static_cast<std::uint32_t>(klb::kSgp4Wgs72)) return "WGS-72";
    if (value == static_cast<std::uint32_t>(klb::kSgp4Wgs84)) return "WGS-84";
    return "unknown";
}

std::string csv_escape(std::string value) {
    std::string escaped;
    escaped.reserve(value.size() + 4u);
    escaped.push_back('"');
    for (char character : value) {
        if (character == '"') escaped.push_back('"');
        escaped.push_back(character);
    }
    escaped.push_back('"');
    return escaped;
}

double vector_radius(const double value[3]) {
    return std::sqrt(value[0] * value[0] + value[1] * value[1] + value[2] * value[2]);
}

std::uint32_t timeline_node_index(const klb::Sgp4Data& data, double seconds) {
    if (data.nodes.empty()) return 0u;
    double local = seconds - data.header.timeline_start_seconds;
    if (data.header.timeline_duration_seconds > 0.0) {
        local -= std::floor(local / data.header.timeline_duration_seconds) *
                 data.header.timeline_duration_seconds;
    }
    for (std::size_t index = 0; index < data.nodes.size(); ++index) {
        const klb::Sgp4TimelineNodeDisk& node = data.nodes[index];
        if (local >= node.start_seconds && local < node.start_seconds + node.duration_seconds) {
            return static_cast<std::uint32_t>(index);
        }
    }
    return static_cast<std::uint32_t>(data.nodes.size() - 1u);
}

void print_inspection(const std::filesystem::path& path, const klb::Sgp4Data& data) {
    const std::uint64_t file_bytes = std::filesystem::file_size(path);
    const klb::Sgp4Stats stats = klb::inspect_sgp4_data(data, file_bytes);
    const std::vector<klb::Sgp4Record> records = klb::compile_sgp4_records(data);
    std::uint64_t near_earth = 0u;
    std::uint64_t deep_nonresonant = 0u;
    std::uint64_t synchronous = 0u;
    std::uint64_t half_day = 0u;
    for (const klb::Sgp4Record& record : records) {
        if (record.method != 'd') ++near_earth;
        else if (record.irez == 1) ++synchronous;
        else if (record.irez == 2) ++half_day;
        else ++deep_nonresonant;
    }

    std::cout << std::fixed << std::setprecision(6)
              << "Format                      : KSGP1 v" << data.header.version << '\n'
              << "Predictor                   : full Vallado/CSSI SGP4 + SDP4 deep-space\n"
              << "Reference epoch             : "
              << klb::format_unix_microseconds_iso8601(data.header.reference_unix_microseconds) << '\n'
              << "Reference frame             : TEME; GMST TEME->PEF query conversion\n"
              << "Gravity constants           : " << gravity_name(data.header.gravity_model) << '\n'
              << "Source label                : " << data.header.source_name << '\n'
              << "Source bytes                : " << stats.source_bytes << '\n'
              << "Source FNV-1a64             : 0x" << std::hex << data.header.source_hash << std::dec << '\n'
              << "Container bytes             : " << stats.file_bytes << '\n'
              << "Compact mean-element seeds  : " << stats.seed_count << " x "
              << sizeof(klb::Sgp4SeedDisk) << " bytes\n"
              << "Compiled coefficient state  : " << stats.coefficient_bytes << " bytes (load-time, not stored)\n"
              << "Hash-linked timeline nodes  : " << stats.node_count << '\n'
              << "Timeline duration           : " << data.header.timeline_duration_seconds << " s\n"
              << "Timeline step               : " << data.header.timeline_step_seconds << " s\n"
              << "Timeline state samples      : " << stats.timeline_samples << '\n'
              << "Equivalent dense float4     : " << stats.equivalent_dense_float4_bytes << " bytes\n"
              << "Equivalent dense pos+vel    : " << stats.equivalent_dense_position_velocity_bytes << " bytes\n"
              << "Ratio vs dense float4       : " << stats.ratio_vs_dense_float4 << "x\n"
              << "Ratio vs dense pos+vel      : " << stats.ratio_vs_dense_position_velocity << "x\n"
              << "Near-Earth records          : " << near_earth << '\n'
              << "Deep-space non-resonant     : " << deep_nonresonant << '\n'
              << "Synchronous resonance       : " << synchronous << '\n'
              << "Half-day resonance          : " << half_day << '\n'
              << "Default DUT1                : " << data.header.default_dut1_seconds << " s\n"
              << "Default elevation mask      : "
              << data.header.default_elevation_mask_rad * klb::kSgp4RadToDeg << " degrees\n"
              << "Terminal chain hash         : 0x" << std::hex << data.header.chain_hash << std::dec << '\n'
              << "Payload hash                : 0x" << std::hex << data.header.payload_hash << std::dec << '\n';

    const std::size_t preview = std::min<std::size_t>(data.seeds.size(), 8u);
    std::cout << "\nSeed preview:\n";
    for (std::size_t index = 0u; index < preview; ++index) {
        const klb::Sgp4SeedDisk& seed = data.seeds[index];
        const klb::Sgp4Record& record = records[index];
        std::cout << "  [" << index << "] NORAD " << seed.norad_id
                  << ", PRN " << klb::sgp4_seed_prn(seed)
                  << ", route " << static_cast<unsigned>(klb::sgp4_seed_route(seed))
                  << ", branch " << (record.method == 'd' ? "deep" : "near")
                  << "/irez=" << record.irez
                  << ", e=" << seed.eccentricity
                  << ", n=" << seed.mean_motion_rad_min * 1440.0 / klb::kSgp4TwoPi
                  << " rev/day, " << klb::sgp4_string_at(data, seed.name_offset) << '\n';
    }
}

int command_pack(int argc, char** argv) {
    if (argc < 4) usage(argv[0], 2);
    const std::filesystem::path input = argv[2];
    const std::filesystem::path output = argv[3];
    klb::Sgp4PackOptions options{};
    for (int index = 4; index < argc; ++index) {
        const std::string argument = argv[index];
        auto value = [&]() -> const char* {
            if (++index >= argc) throw std::invalid_argument(argument + " requires a value");
            return argv[index];
        };
        if (argument == "--horizon-hours") options.horizon_seconds = parse_double(value(), "--horizon-hours") * 3600.0;
        else if (argument == "--step-seconds") options.step_seconds = parse_double(value(), "--step-seconds");
        else if (argument == "--tile-hours") options.tile_seconds = parse_double(value(), "--tile-hours") * 3600.0;
        else if (argument == "--elevation-deg") options.elevation_mask_degrees = parse_double(value(), "--elevation-deg");
        else if (argument == "--dut1-seconds") options.dut1_seconds = parse_double(value(), "--dut1-seconds");
        else if (argument == "--gravity") options.gravity_model = parse_gravity(value());
        else if (argument == "--seed") options.seed = static_cast<std::uint32_t>(parse_u64(value(), "--seed"));
        else if (argument == "--help" || argument == "-h") usage(argv[0], 0);
        else throw std::invalid_argument("unknown pack option: " + argument);
    }
    const klb::Sgp4Data data = klb::pack_omm_csv_sgp4(input, options);
    if (!output.parent_path().empty()) std::filesystem::create_directories(output.parent_path());
    klb::save_sgp4_data(output, data);
    print_inspection(output, data);
    return 0;
}

int command_inspect(int argc, char** argv) {
    if (argc != 3) usage(argv[0], 2);
    const std::filesystem::path input = argv[2];
    print_inspection(input, klb::load_sgp4_data(input));
    return 0;
}

int command_verify(int argc, char** argv) {
    if (argc != 3) usage(argv[0], 2);
    const std::filesystem::path input = argv[2];
    const klb::Sgp4Data data = klb::load_sgp4_data(input);
    klb::validate_sgp4_data(data, true);
    const std::vector<klb::Sgp4Record> records = klb::compile_sgp4_records(data);
    const double reference_unix = static_cast<double>(data.header.reference_unix_microseconds) / 1.0e6;
    double minimum_radius = std::numeric_limits<double>::infinity();
    double maximum_radius = 0.0;
    double minimum_speed = std::numeric_limits<double>::infinity();
    double maximum_speed = 0.0;
    std::uint64_t evaluations = 0u;
    std::uint64_t failures = 0u;
    const std::array<double, 5> fractions{0.0, 0.125, 0.5, 0.875, 1.0};
    for (std::size_t seed_index = 0u; seed_index < data.seeds.size(); ++seed_index) {
        for (double fraction : fractions) {
            const double seconds = data.header.timeline_start_seconds +
                fraction * data.header.timeline_duration_seconds;
            const double minutes = klb::sgp4_minutes_from_reference(
                data.seeds[seed_index], seconds, reference_unix);
            const klb::Sgp4State state = klb::sgp4_state_at(records[seed_index], minutes);
            ++evaluations;
            if (state.error != 0) {
                ++failures;
                continue;
            }
            const double radius = vector_radius(state.position_teme_km);
            const double speed = vector_radius(state.velocity_teme_km_s);
            if (!std::isfinite(radius) || !std::isfinite(speed)) {
                throw std::runtime_error("non-finite full-SGP4 state");
            }
            minimum_radius = std::min(minimum_radius, radius);
            maximum_radius = std::max(maximum_radius, radius);
            minimum_speed = std::min(minimum_speed, speed);
            maximum_speed = std::max(maximum_speed, speed);
        }
    }
    if (failures != 0u) throw std::runtime_error("one or more packed records failed verification propagation");
    std::cout << std::fixed << std::setprecision(9)
              << "KSGP1 hash chain and payload : valid\n"
              << "Compiled SGP4 records        : " << records.size() << '\n'
              << "Reference evaluations        : " << evaluations << '\n'
              << "Propagation failures         : " << failures << '\n'
              << "Sampled TEME radius range    : " << minimum_radius << " .. " << maximum_radius << " km\n"
              << "Sampled TEME speed range     : " << minimum_speed << " .. " << maximum_speed << " km/s\n"
              << "Reference-vector coverage    : run klb_sgp4_tests (near, deep, irez=1, irez=2, GPS-like)\n"
              << "Frame boundary               : TEME->PEF uses GMST+DUT1; polar motion/EOP omitted\n";
    return 0;
}

int command_sample(int argc, char** argv) {
    if (argc < 3) usage(argv[0], 2);
    const std::filesystem::path input = argv[2];
    double seconds = 0.0;
    std::uint64_t limit = std::numeric_limits<std::uint64_t>::max();
    double dut1_override = std::numeric_limits<double>::quiet_NaN();
    std::filesystem::path output_path;
    for (int index = 3; index < argc; ++index) {
        const std::string argument = argv[index];
        auto value = [&]() -> const char* {
            if (++index >= argc) throw std::invalid_argument(argument + " requires a value");
            return argv[index];
        };
        if (argument == "--seconds") seconds = parse_double(value(), "--seconds");
        else if (argument == "--limit") limit = parse_u64(value(), "--limit");
        else if (argument == "--dut1-seconds") dut1_override = parse_double(value(), "--dut1-seconds");
        else if (argument == "--output") output_path = value();
        else if (argument == "--help" || argument == "-h") usage(argv[0], 0);
        else throw std::invalid_argument("unknown sample option: " + argument);
    }
    const klb::Sgp4Data data = klb::load_sgp4_data(input);
    const std::vector<klb::Sgp4Record> records = klb::compile_sgp4_records(data);
    const double reference_unix = static_cast<double>(data.header.reference_unix_microseconds) / 1.0e6;
    const double dut1 = std::isnan(dut1_override) ? data.header.default_dut1_seconds : dut1_override;
    const double julian_utc = data.header.reference_julian_date + seconds / 86400.0;

    std::ofstream file;
    std::ostream* output = &std::cout;
    if (!output_path.empty()) {
        if (!output_path.parent_path().empty()) std::filesystem::create_directories(output_path.parent_path());
        file.open(output_path, std::ios::trunc);
        if (!file) throw std::runtime_error("unable to create sample CSV: " + output_path.string());
        output = &file;
    }
    *output << "seed_index,norad_id,prn,route_sector,seconds_from_reference,minutes_from_element_epoch,"
               "x_teme_km,y_teme_km,z_teme_km,vx_teme_km_s,vy_teme_km_s,vz_teme_km_s,"
               "x_pef_km,y_pef_km,z_pef_km,radius_km,sgp4_error,name,object_id\n";
    *output << std::fixed << std::setprecision(9);
    const std::size_t count = static_cast<std::size_t>(std::min<std::uint64_t>(limit, data.seeds.size()));
    for (std::size_t index = 0u; index < count; ++index) {
        const klb::Sgp4SeedDisk& seed = data.seeds[index];
        const double minutes = klb::sgp4_minutes_from_reference(seed, seconds, reference_unix);
        const klb::Sgp4State state = klb::sgp4_state_at(records[index], minutes);
        double pef[3]{};
        if (state.error == 0) {
            klb::sgp4_teme_to_pef(state.position_teme_km, julian_utc + dut1 / 86400.0, pef);
        }
        *output << index << ',' << seed.norad_id << ',' << klb::sgp4_seed_prn(seed) << ','
                << static_cast<unsigned>(klb::sgp4_seed_route(seed)) << ',' << seconds << ',' << minutes << ','
                << state.position_teme_km[0] << ',' << state.position_teme_km[1] << ',' << state.position_teme_km[2] << ','
                << state.velocity_teme_km_s[0] << ',' << state.velocity_teme_km_s[1] << ',' << state.velocity_teme_km_s[2] << ','
                << pef[0] << ',' << pef[1] << ',' << pef[2] << ','
                << vector_radius(state.position_teme_km) << ',' << state.error << ','
                << csv_escape(klb::sgp4_string_at(data, seed.name_offset)) << ','
                << csv_escape(klb::sgp4_string_at(data, seed.object_id_offset)) << '\n';
    }
    return 0;
}

struct PassEvent {
    double seconds{};
    std::uint64_t interval{};
    std::uint32_t seed_index{};
    std::uint32_t lineage{};
    std::uint32_t acquisition{};
    double minimum_abs_guard{};
};

int command_passes(int argc, char** argv) {
    if (argc < 3) usage(argv[0], 2);
    const std::filesystem::path input = argv[2];
    const klb::Sgp4Data data = klb::load_sgp4_data(input);
    const std::vector<klb::Sgp4Record> records = klb::compile_sgp4_records(data);

    double latitude_degrees = 52.0;
    double longitude_degrees = 5.0;
    double altitude_km = 0.05;
    double elevation_degrees = data.header.default_elevation_mask_rad * klb::kSgp4RadToDeg;
    double crossing_band_degrees = 0.25;
    double maximum_slant_range_km = 33000.0;
    double start_seconds = data.header.timeline_start_seconds;
    double duration_seconds = data.header.timeline_duration_seconds;
    double step_seconds = data.header.timeline_step_seconds;
    double dut1_seconds = data.header.default_dut1_seconds;
    std::uint32_t route_filter = 0xffffffffu;
    std::filesystem::path output_path;

    for (int index = 3; index < argc; ++index) {
        const std::string argument = argv[index];
        auto value = [&]() -> const char* {
            if (++index >= argc) throw std::invalid_argument(argument + " requires a value");
            return argv[index];
        };
        if (argument == "--lat") latitude_degrees = parse_double(value(), "--lat");
        else if (argument == "--lon") longitude_degrees = parse_double(value(), "--lon");
        else if (argument == "--alt-km") altitude_km = parse_double(value(), "--alt-km");
        else if (argument == "--elevation-deg") elevation_degrees = parse_double(value(), "--elevation-deg");
        else if (argument == "--crossing-band-deg") crossing_band_degrees = parse_double(value(), "--crossing-band-deg");
        else if (argument == "--max-range-km") maximum_slant_range_km = parse_double(value(), "--max-range-km");
        else if (argument == "--start-seconds") start_seconds = parse_double(value(), "--start-seconds");
        else if (argument == "--hours") duration_seconds = parse_double(value(), "--hours") * 3600.0;
        else if (argument == "--step-seconds") step_seconds = parse_double(value(), "--step-seconds");
        else if (argument == "--dut1-seconds") dut1_seconds = parse_double(value(), "--dut1-seconds");
        else if (argument == "--route") {
            const std::string route = value();
            if (route == "any") route_filter = 0xffffffffu;
            else {
                const std::uint64_t parsed = parse_u64(route, "--route");
                if (parsed > 5u) throw std::invalid_argument("--route must be any or 0..5");
                route_filter = static_cast<std::uint32_t>(parsed);
            }
        } else if (argument == "--output") output_path = value();
        else if (argument == "--help" || argument == "-h") usage(argv[0], 0);
        else throw std::invalid_argument("unknown passes option: " + argument);
    }
    if (!(duration_seconds > 0.0) || !(step_seconds > 0.0)) {
        throw std::invalid_argument("passes duration and step must be positive");
    }

    const klb::Sgp4GroundStation station = klb::make_sgp4_ground_station(
        latitude_degrees, longitude_degrees, altitude_km, elevation_degrees,
        crossing_band_degrees, maximum_slant_range_km, route_filter);
    const std::uint64_t intervals = static_cast<std::uint64_t>(std::floor(duration_seconds / step_seconds));
    if (intervals == 0u) throw std::invalid_argument("passes duration is shorter than one step");
    const double reference_unix = static_cast<double>(data.header.reference_unix_microseconds) / 1.0e6;

    std::uint64_t candidate_intervals = 0u;
    std::uint64_t supported_intervals = 0u;
    std::uint64_t compatible_intervals = 0u;
    std::uint64_t visible_samples = 0u;
    std::uint64_t propagation_failures = 0u;
    std::vector<PassEvent> events;
    events.reserve(2048u);

    // Satellite-major traversal reuses the previous propagated state, reducing
    // the CPU oracle from two propagations per interval to one after startup.
    for (std::size_t seed_index = 0u; seed_index < data.seeds.size(); ++seed_index) {
        const klb::Sgp4SeedDisk& seed = data.seeds[seed_index];
        const klb::Sgp4Record& record = records[seed_index];
        double previous_seconds = start_seconds;
        double previous_minutes = klb::sgp4_minutes_from_reference(seed, previous_seconds, reference_unix);
        klb::Sgp4State previous_state = klb::sgp4_state_at(record, previous_minutes);
        klb::Sgp4Visibility previous{};
        if (previous_state.error == 0) {
            previous = klb::sgp4_evaluate_visibility(
                previous_state.position_teme_km,
                data.header.reference_julian_date + previous_seconds / 86400.0,
                dut1_seconds, station, klb::sgp4_seed_route(seed));
        } else {
            ++propagation_failures;
        }

        for (std::uint64_t interval = 0u; interval < intervals; ++interval) {
            const double current_seconds = start_seconds + static_cast<double>(interval + 1u) * step_seconds;
            const double current_minutes = klb::sgp4_minutes_from_reference(seed, current_seconds, reference_unix);
            const klb::Sgp4State current_state = klb::sgp4_state_at(record, current_minutes);
            klb::Sgp4Visibility current{};
            if (current_state.error == 0) {
                current = klb::sgp4_evaluate_visibility(
                    current_state.position_teme_km,
                    data.header.reference_julian_date + current_seconds / 86400.0,
                    dut1_seconds, station, klb::sgp4_seed_route(seed));
            } else {
                ++propagation_failures;
            }

            ++candidate_intervals;
            const bool valid_pair = previous_state.error == 0 && current_state.error == 0;
            const bool supported = valid_pair && (previous.supported != 0u || current.supported != 0u);
            const bool compatible = supported && previous.compatible != 0u && current.compatible != 0u;
            if (supported) ++supported_intervals;
            if (compatible) ++compatible_intervals;
            if (valid_pair && current.supported != 0u && current.compatible != 0u && current.guard <= 0.0) {
                ++visible_samples;
            }
            if (valid_pair) {
                const klb::Sgp4Crossing crossing = klb::sgp4_evaluate_crossing(
                    previous, current, previous_seconds, current_seconds,
                    static_cast<double>(station.crossing_band_sin));
                if (crossing.verified != 0u) {
                    const std::uint32_t node_index = timeline_node_index(data, crossing.crossing_seconds);
                    const std::uint32_t event_kind = crossing.acquisition != 0u ? 1u : 2u;
                    events.push_back({
                        crossing.crossing_seconds,
                        interval,
                        static_cast<std::uint32_t>(seed_index),
                        klb::sgp4_lineage(seed, data.nodes[node_index], interval, event_kind),
                        crossing.acquisition,
                        crossing.minimum_abs_guard,
                    });
                }
            }
            previous_seconds = current_seconds;
            previous_state = current_state;
            previous = current;
        }
    }

    std::sort(events.begin(), events.end(), [](const PassEvent& left, const PassEvent& right) {
        if (left.seconds != right.seconds) return left.seconds < right.seconds;
        if (left.seed_index != right.seed_index) return left.seed_index < right.seed_index;
        return left.acquisition > right.acquisition;
    });

    std::ofstream file;
    std::ostream* output = &std::cout;
    if (!output_path.empty()) {
        if (!output_path.parent_path().empty()) std::filesystem::create_directories(output_path.parent_path());
        file.open(output_path, std::ios::trunc);
        if (!file) throw std::runtime_error("unable to create passes CSV: " + output_path.string());
        output = &file;
    }
    *output << "event_index,event_type,event_time_utc,seconds_from_reference,interval_index,norad_id,prn,"
               "route_sector,lineage,minimum_abs_guard,elevation_mask_deg,dut1_seconds,name,object_id\n";
    *output << std::fixed << std::setprecision(9);
    for (std::size_t index = 0u; index < events.size(); ++index) {
        const PassEvent& event = events[index];
        const klb::Sgp4SeedDisk& seed = data.seeds[event.seed_index];
        const std::int64_t event_microseconds = data.header.reference_unix_microseconds +
            static_cast<std::int64_t>(std::llround(event.seconds * 1000000.0));
        *output << index << ',' << (event.acquisition != 0u ? "acquire" : "loss") << ','
                << klb::format_unix_microseconds_iso8601(event_microseconds) << ','
                << event.seconds << ',' << event.interval << ',' << seed.norad_id << ','
                << klb::sgp4_seed_prn(seed) << ','
                << static_cast<unsigned>(klb::sgp4_seed_route(seed)) << ',' << event.lineage << ','
                << event.minimum_abs_guard << ',' << elevation_degrees << ',' << dut1_seconds << ','
                << csv_escape(klb::sgp4_string_at(data, seed.name_offset)) << ','
                << csv_escape(klb::sgp4_string_at(data, seed.object_id_offset)) << '\n';
    }

    std::cerr << "KSGP1 full-SGP4 visibility schedule\n"
              << "  intervals               : " << intervals << '\n'
              << "  seeds                   : " << data.seeds.size() << '\n'
              << "  candidate intervals     : " << candidate_intervals << '\n'
              << "  support survivors       : " << supported_intervals << '\n'
              << "  compatible survivors    : " << compatible_intervals << '\n'
              << "  visible samples         : " << visible_samples << '\n'
              << "  acquisition/loss events : " << events.size() << '\n'
              << "  propagation failures    : " << propagation_failures << '\n'
              << "  model                   : full SGP4/SDP4\n"
              << "  frame boundary          : TEME->PEF GMST+DUT1; polar motion/EOP omitted\n";
    return propagation_failures == 0u ? 0 : 1;
}

int command_compare_coarse(int argc, char** argv) {
    if (argc < 4) usage(argv[0], 2);
    const std::filesystem::path sgp4_path = argv[2];
    const std::filesystem::path coarse_path = argv[3];
    double duration_seconds = 168.0 * 3600.0;
    double step_seconds = 21600.0;
    std::filesystem::path output_path;
    for (int index = 4; index < argc; ++index) {
        const std::string argument = argv[index];
        auto value = [&]() -> const char* {
            if (++index >= argc) throw std::invalid_argument(argument + " requires a value");
            return argv[index];
        };
        if (argument == "--hours") duration_seconds = parse_double(value(), "--hours") * 3600.0;
        else if (argument == "--step-seconds") step_seconds = parse_double(value(), "--step-seconds");
        else if (argument == "--output") output_path = value();
        else if (argument == "--help" || argument == "-h") usage(argv[0], 0);
        else throw std::invalid_argument("unknown compare-coarse option: " + argument);
    }
    if (!(duration_seconds >= 0.0) || !(step_seconds > 0.0)) {
        throw std::invalid_argument("comparison duration must be nonnegative and step positive");
    }

    const klb::Sgp4Data full = klb::load_sgp4_data(sgp4_path);
    const std::vector<klb::Sgp4Record> records = klb::compile_sgp4_records(full);
    const klb::OrbitData coarse = klb::load_orbit_data(coarse_path);
    std::map<std::uint32_t, std::size_t> coarse_by_norad;
    for (std::size_t index = 0u; index < coarse.seeds.size(); ++index) {
        coarse_by_norad.emplace(coarse.seeds[index].norad_id, index);
    }

    struct ErrorAccumulator {
        std::uint64_t samples{};
        long double squared{};
        double maximum{};
    };
    std::vector<ErrorAccumulator> per_seed(full.seeds.size());
    ErrorAccumulator global{};
    const std::uint64_t samples = static_cast<std::uint64_t>(std::floor(duration_seconds / step_seconds)) + 1u;
    const double full_reference_unix = static_cast<double>(full.header.reference_unix_microseconds) / 1.0e6;
    const double coarse_reference_unix = static_cast<double>(coarse.header.reference_unix_microseconds) / 1.0e6;

    for (std::size_t full_index = 0u; full_index < full.seeds.size(); ++full_index) {
        const klb::Sgp4SeedDisk& seed = full.seeds[full_index];
        const auto found = coarse_by_norad.find(seed.norad_id);
        if (found == coarse_by_norad.end()) continue;
        const klb::OrbitSeedDisk& coarse_seed = coarse.seeds[found->second];
        for (std::uint64_t sample = 0u; sample < samples; ++sample) {
            const double seconds = static_cast<double>(sample) * step_seconds;
            const double absolute_unix = full_reference_unix + seconds;
            const double full_minutes = (absolute_unix - seed.epoch_unix_seconds) / 60.0;
            const klb::Sgp4State state = klb::sgp4_state_at(records[full_index], full_minutes);
            if (state.error != 0) continue;
            const float coarse_seconds = static_cast<float>(absolute_unix - coarse_reference_unix);
            const klb::Vec3 coarse_position = klb::propagate_orbit_seed(coarse_seed, coarse_seconds);
            const double dx = state.position_teme_km[0] - coarse_position.x;
            const double dy = state.position_teme_km[1] - coarse_position.y;
            const double dz = state.position_teme_km[2] - coarse_position.z;
            const double error = std::sqrt(dx * dx + dy * dy + dz * dz);
            ErrorAccumulator& local = per_seed[full_index];
            ++local.samples;
            local.squared += static_cast<long double>(error) * error;
            local.maximum = std::max(local.maximum, error);
            ++global.samples;
            global.squared += static_cast<long double>(error) * error;
            global.maximum = std::max(global.maximum, error);
        }
    }

    std::ofstream file;
    std::ostream* output = &std::cout;
    if (!output_path.empty()) {
        if (!output_path.parent_path().empty()) std::filesystem::create_directories(output_path.parent_path());
        file.open(output_path, std::ios::trunc);
        if (!file) throw std::runtime_error("unable to create comparison CSV: " + output_path.string());
        output = &file;
    }
    *output << "norad_id,prn,samples,rms_position_error_km,max_position_error_km,name\n";
    *output << std::fixed << std::setprecision(9);
    for (std::size_t index = 0u; index < full.seeds.size(); ++index) {
        const ErrorAccumulator& error = per_seed[index];
        if (error.samples == 0u) continue;
        const double rms = std::sqrt(static_cast<double>(error.squared / error.samples));
        const klb::Sgp4SeedDisk& seed = full.seeds[index];
        *output << seed.norad_id << ',' << klb::sgp4_seed_prn(seed) << ',' << error.samples << ','
                << rms << ',' << error.maximum << ','
                << csv_escape(klb::sgp4_string_at(full, seed.name_offset)) << '\n';
    }
    const double global_rms = global.samples == 0u ? 0.0 :
        std::sqrt(static_cast<double>(global.squared / global.samples));
    std::cerr << std::fixed << std::setprecision(6)
              << "Coarse predictor versus full SGP4\n"
              << "  matched samples          : " << global.samples << '\n'
              << "  RMS position difference  : " << global_rms << " km\n"
              << "  maximum difference       : " << global.maximum << " km\n"
              << "  interpretation           : difference quantifies the removed v0.3 surrogate, not SGP4 error\n";
    return global.samples == 0u ? 1 : 0;
}

} // namespace

int main(int argc, char** argv) {
    try {
        if (argc < 2) usage(argv[0], 2);
        const std::string command = argv[1];
        if (command == "pack-omm-csv") return command_pack(argc, argv);
        if (command == "inspect") return command_inspect(argc, argv);
        if (command == "verify") return command_verify(argc, argv);
        if (command == "sample") return command_sample(argc, argv);
        if (command == "passes") return command_passes(argc, argv);
        if (command == "compare-coarse") return command_compare_coarse(argc, argv);
        if (command == "--help" || command == "-h") usage(argv[0], 0);
        throw std::invalid_argument("unknown command: " + command);
    } catch (const std::exception& error) {
        std::cerr << "error: " << error.what() << '\n';
        return 1;
    }
}
