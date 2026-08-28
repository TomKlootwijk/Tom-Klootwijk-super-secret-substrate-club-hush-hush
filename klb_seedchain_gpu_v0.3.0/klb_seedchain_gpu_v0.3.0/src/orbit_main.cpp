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
#include <stdexcept>
#include <string>
#include <string_view>

namespace {

[[noreturn]] void usage(const char* executable, int exit_code) {
    std::ostream& output = exit_code == 0 ? std::cout : std::cerr;
    output
        << "KLB OrbitSeed adapter and KLOC1 inspector\n\n"
        << "Usage:\n"
        << "  " << executable << " pack-omm-csv <input.csv> <output.kloc> [options]\n"
        << "  " << executable << " inspect <input.kloc>\n"
        << "  " << executable << " verify <input.kloc>\n"
        << "  " << executable << " sample <input.kloc> [options]\n"
        << "  " << executable << " passes <input.kloc> [options]\n\n"
        << "pack-omm-csv options:\n"
        << "  --horizon-hours X       Versioned timeline horizon (default 168)\n"
        << "  --step-seconds X        Timeline state-sample step (default 1)\n"
        << "  --tile-hours X          Hash-linked timeline tile size (default 24)\n"
        << "  --elevation-deg X       Default ground mask metadata (default 10)\n"
        << "  --seed N                Chain seed, decimal or 0x-prefixed\n\n"
        << "sample options:\n"
        << "  --seconds X             Seconds from the KLOC1 reference epoch (default 0)\n"
        << "  --limit N               Number of seeds to print (default all)\n"
        << "  --output PATH           Write CSV instead of standard output\n\n"
        << "passes options:\n"
        << "  --lat X --lon X        Ground-station latitude/longitude degrees (default 52,5)\n"
        << "  --alt-km X             Ground-station altitude kilometres (default 0.05)\n"
        << "  --elevation-deg X      Elevation guard threshold (default file metadata)\n"
        << "  --crossing-band-deg X  Sampled crossing acceptance band (default 0.25)\n"
        << "  --max-range-km X       Analytic support radius (default 33000)\n"
        << "  --route any|0..5       Optional route-sector compatibility filter\n"
        << "  --start-seconds X      Start from the KLOC1 reference epoch (default 0)\n"
        << "  --hours X              Duration (default file timeline)\n"
        << "  --step-seconds X       Sampling step (default file timeline step)\n"
        << "  --output PATH          Write acquisition/loss event CSV (default stdout)\n\n"
        << "The bundled predictor is deterministic Kepler plus precomputed secular J2 rates.\n"
        << "It is a compression/query benchmark, not SGP4 or navigation-grade ephemeris.\n";
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

void print_inspection(const std::filesystem::path& path, const klb::OrbitData& data) {
    const std::uint64_t file_bytes = std::filesystem::file_size(path);
    const klb::OrbitStats stats = klb::inspect_orbit_data(data, file_bytes);
    std::cout << std::fixed << std::setprecision(6)
              << "Format                      : KLOC1 v" << data.header.version << '\n'
              << "Predictor                   : Kepler + compiled secular J2 rates (coarse)\n"
              << "Reference epoch             : "
              << klb::format_unix_microseconds_iso8601(data.header.reference_unix_microseconds) << '\n'
              << "Source label                : " << data.header.source_name << '\n'
              << "Source bytes                : " << stats.source_bytes << '\n'
              << "Source FNV-1a64             : 0x" << std::hex << data.header.source_hash << std::dec << '\n'
              << "Container bytes             : " << stats.file_bytes << '\n'
              << "Orbit seeds                 : " << stats.seed_count << '\n'
              << "Hash-linked timeline nodes  : " << stats.node_count << '\n'
              << "Timeline duration           : " << data.header.timeline_duration_seconds << " s\n"
              << "Timeline step               : " << data.header.timeline_step_seconds << " s\n"
              << "Timeline state samples      : " << stats.timeline_samples << '\n'
              << "Equivalent dense float4     : " << stats.equivalent_dense_float4_bytes << " bytes\n"
              << "Horizon-relative ratio      : " << stats.ratio_vs_dense_float4 << "x\n"
              << "Terminal chain hash         : 0x" << std::hex << data.header.chain_hash << std::dec << '\n'
              << "Payload hash                : 0x" << std::hex << data.header.payload_hash << std::dec << '\n'
              << "Default elevation mask      : "
              << data.header.default_elevation_mask_rad * klb::kOrbitRadToDeg << " degrees\n";

    const std::size_t preview = std::min<std::size_t>(data.seeds.size(), 6u);
    std::cout << "\nSeed preview:\n";
    for (std::size_t index = 0u; index < preview; ++index) {
        const klb::OrbitSeedDisk& seed = data.seeds[index];
        std::cout << "  [" << index << "] NORAD " << seed.norad_id
                  << ", PRN " << seed.prn
                  << ", route " << static_cast<unsigned>(seed.route_sector)
                  << ", a=" << seed.semi_major_axis_km << " km, e=" << seed.eccentricity
                  << ", " << klb::orbit_string_at(data, seed.name_offset) << '\n';
    }
}

int command_pack(int argc, char** argv) {
    if (argc < 4) usage(argv[0], 2);
    const std::filesystem::path input = argv[2];
    const std::filesystem::path output = argv[3];
    klb::OrbitPackOptions options{};
    for (int index = 4; index < argc; ++index) {
        const std::string argument = argv[index];
        auto value = [&]() -> const char* {
            if (++index >= argc) throw std::invalid_argument(argument + " requires a value");
            return argv[index];
        };
        if (argument == "--horizon-hours") {
            options.horizon_seconds = parse_float(value(), "--horizon-hours") * 3600.0f;
        } else if (argument == "--step-seconds") {
            options.step_seconds = parse_float(value(), "--step-seconds");
        } else if (argument == "--tile-hours") {
            options.tile_seconds = parse_float(value(), "--tile-hours") * 3600.0f;
        } else if (argument == "--elevation-deg") {
            options.elevation_mask_degrees = parse_float(value(), "--elevation-deg");
        } else if (argument == "--seed") {
            options.seed = static_cast<std::uint32_t>(parse_u64(value(), "--seed"));
        } else if (argument == "--help" || argument == "-h") {
            usage(argv[0], 0);
        } else {
            throw std::invalid_argument("unknown pack option: " + argument);
        }
    }
    const klb::OrbitData data = klb::pack_omm_csv(input, options);
    klb::save_orbit_data(output, data);
    print_inspection(output, data);
    return 0;
}

int command_inspect(int argc, char** argv) {
    if (argc != 3) usage(argv[0], 2);
    const std::filesystem::path input = argv[2];
    const klb::OrbitData data = klb::load_orbit_data(input);
    print_inspection(input, data);
    return 0;
}

int command_verify(int argc, char** argv) {
    if (argc != 3) usage(argv[0], 2);
    const std::filesystem::path input = argv[2];
    const klb::OrbitData data = klb::load_orbit_data(input);
    klb::validate_orbit_data(data, true);
    double minimum_radius = std::numeric_limits<double>::infinity();
    double maximum_radius = 0.0;
    for (const klb::OrbitSeedDisk& seed : data.seeds) {
        for (float seconds : {0.0f, 21600.0f, 43200.0f, data.header.timeline_duration_seconds}) {
            const klb::Vec3 position = klb::propagate_orbit_seed(seed, seconds);
            const double radius = klb::length(position);
            if (!std::isfinite(radius)) throw std::runtime_error("non-finite propagated position");
            minimum_radius = std::min(minimum_radius, radius);
            maximum_radius = std::max(maximum_radius, radius);
        }
    }
    std::cout << "KLOC1 hash chain and payload : valid\n"
              << "Seeds checked                : " << data.seeds.size() << '\n'
              << "Sampled ECI radius range     : " << minimum_radius << " .. "
              << maximum_radius << " km\n"
              << "Model boundary               : coarse benchmark predictor; not SGP4/navigation\n";
    return 0;
}

int command_sample(int argc, char** argv) {
    if (argc < 3) usage(argv[0], 2);
    const std::filesystem::path input = argv[2];
    float seconds = 0.0f;
    std::uint64_t limit = std::numeric_limits<std::uint64_t>::max();
    std::filesystem::path output_path;
    for (int index = 3; index < argc; ++index) {
        const std::string argument = argv[index];
        auto value = [&]() -> const char* {
            if (++index >= argc) throw std::invalid_argument(argument + " requires a value");
            return argv[index];
        };
        if (argument == "--seconds") {
            seconds = parse_float(value(), "--seconds");
        } else if (argument == "--limit") {
            limit = parse_u64(value(), "--limit");
        } else if (argument == "--output") {
            output_path = value();
        } else if (argument == "--help" || argument == "-h") {
            usage(argv[0], 0);
        } else {
            throw std::invalid_argument("unknown sample option: " + argument);
        }
    }
    const klb::OrbitData data = klb::load_orbit_data(input);
    std::ofstream file;
    std::ostream* output = &std::cout;
    if (!output_path.empty()) {
        file.open(output_path, std::ios::trunc);
        if (!file) throw std::runtime_error("unable to create sample CSV: " + output_path.string());
        output = &file;
    }
    *output << "seed_index,norad_id,prn,route_sector,seconds_from_reference,x_eci_km,y_eci_km,z_eci_km,radius_km,name\n";
    const std::size_t count = static_cast<std::size_t>(
        std::min<std::uint64_t>(limit, data.seeds.size()));
    *output << std::fixed << std::setprecision(6);
    for (std::size_t index = 0u; index < count; ++index) {
        const klb::OrbitSeedDisk& seed = data.seeds[index];
        const klb::Vec3 position = klb::propagate_orbit_seed(seed, seconds);
        std::string name = klb::orbit_string_at(data, seed.name_offset);
        std::replace(name.begin(), name.end(), '"', '\'');
        *output << index << ',' << seed.norad_id << ',' << seed.prn << ','
                << static_cast<unsigned>(seed.route_sector) << ',' << seconds << ','
                << position.x << ',' << position.y << ',' << position.z << ','
                << klb::length(position) << ",\"" << name << "\"\n";
    }
    return 0;
}


int command_passes(int argc, char** argv) {
    if (argc < 3) usage(argv[0], 2);
    const std::filesystem::path input = argv[2];
    const klb::OrbitData data = klb::load_orbit_data(input);

    float latitude_degrees = 52.0f;
    float longitude_degrees = 5.0f;
    float altitude_km = 0.05f;
    float elevation_degrees = data.header.default_elevation_mask_rad * klb::kOrbitRadToDeg;
    float crossing_band_degrees = 0.25f;
    float maximum_slant_range_km = 33000.0f;
    float start_seconds = 0.0f;
    float duration_seconds = data.header.timeline_duration_seconds;
    float step_seconds = data.header.timeline_step_seconds;
    std::uint32_t route_filter = 0xffffffffu;
    std::filesystem::path output_path;

    for (int index = 3; index < argc; ++index) {
        const std::string argument = argv[index];
        auto value = [&]() -> const char* {
            if (++index >= argc) throw std::invalid_argument(argument + " requires a value");
            return argv[index];
        };
        if (argument == "--lat") latitude_degrees = parse_float(value(), "--lat");
        else if (argument == "--lon") longitude_degrees = parse_float(value(), "--lon");
        else if (argument == "--alt-km") altitude_km = parse_float(value(), "--alt-km");
        else if (argument == "--elevation-deg") elevation_degrees = parse_float(value(), "--elevation-deg");
        else if (argument == "--crossing-band-deg") crossing_band_degrees = parse_float(value(), "--crossing-band-deg");
        else if (argument == "--max-range-km") maximum_slant_range_km = parse_float(value(), "--max-range-km");
        else if (argument == "--start-seconds") start_seconds = parse_float(value(), "--start-seconds");
        else if (argument == "--hours") duration_seconds = parse_float(value(), "--hours") * 3600.0f;
        else if (argument == "--step-seconds") step_seconds = parse_float(value(), "--step-seconds");
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
    if (!(duration_seconds > 0.0f) || !(step_seconds > 0.0f)) {
        throw std::invalid_argument("passes duration and step must be positive");
    }

    const klb::OrbitGroundStation station = klb::make_ground_station(
        latitude_degrees, longitude_degrees, altitude_km, elevation_degrees,
        crossing_band_degrees, maximum_slant_range_km, route_filter);
    const klb::OrbitView view = klb::make_orbit_view(data);
    const std::uint64_t intervals = static_cast<std::uint64_t>(
        std::floor(static_cast<double>(duration_seconds) / step_seconds));
    if (intervals == 0u) throw std::invalid_argument("passes duration is shorter than one step");

    std::ofstream file;
    std::ostream* output = &std::cout;
    if (!output_path.empty()) {
        file.open(output_path, std::ios::trunc);
        if (!file) throw std::runtime_error("unable to create passes CSV: " + output_path.string());
        output = &file;
    }
    *output << "event_index,event_type,event_time_utc,seconds_from_reference,norad_id,prn,route_sector,lineage,minimum_abs_guard,elevation_mask_deg,name\n";
    *output << std::fixed << std::setprecision(6);

    std::uint64_t candidate_intervals = 0u;
    std::uint64_t supported_intervals = 0u;
    std::uint64_t compatible_intervals = 0u;
    std::uint64_t visible_samples = 0u;
    std::uint64_t events = 0u;
    for (std::uint64_t epoch = 0u; epoch < intervals; ++epoch) {
        const float previous_seconds = start_seconds + static_cast<float>(epoch) * step_seconds;
        const float current_seconds = previous_seconds + step_seconds;
        for (const klb::OrbitSeedDisk& seed : data.seeds) {
            ++candidate_intervals;
            const klb::OrbitEvaluation previous = klb::evaluate_orbit_visibility(
                klb::propagate_orbit_seed(seed, previous_seconds), previous_seconds, station,
                data.header.reference_gmst_rad, data.header.earth_rotation_rad_s, seed.route_sector);
            const klb::OrbitEvaluation current = klb::evaluate_orbit_visibility(
                klb::propagate_orbit_seed(seed, current_seconds), current_seconds, station,
                data.header.reference_gmst_rad, data.header.earth_rotation_rad_s, seed.route_sector);
            const bool supported = previous.supported != 0u || current.supported != 0u;
            const bool compatible = supported && previous.compatible != 0u && current.compatible != 0u;
            if (supported) ++supported_intervals;
            if (compatible) ++compatible_intervals;
            if (current.supported != 0u && current.compatible != 0u && current.guard <= 0.0f) {
                ++visible_samples;
            }
            const klb::OrbitCrossing crossing = klb::evaluate_orbit_crossing(
                previous, current, previous_seconds, current_seconds, station.crossing_band_sin);
            if (crossing.verified == 0u) continue;

            const std::uint32_t node_index = klb::orbit_timeline_node_index(view, crossing.crossing_seconds);
            const std::uint32_t event_type = crossing.acquisition != 0u ? 1u : 2u;
            const std::uint32_t lineage = klb::orbit_lineage(
                seed, data.nodes[node_index], epoch, event_type);
            const std::int64_t event_microseconds = data.header.reference_unix_microseconds +
                static_cast<std::int64_t>(std::llround(
                    static_cast<double>(crossing.crossing_seconds) * 1000000.0));
            std::string name = klb::orbit_string_at(data, seed.name_offset);
            std::replace(name.begin(), name.end(), '"', '\'');
            *output << events << ',' << (crossing.acquisition != 0u ? "acquire" : "loss") << ','
                    << klb::format_unix_microseconds_iso8601(event_microseconds) << ','
                    << crossing.crossing_seconds << ',' << seed.norad_id << ',' << seed.prn << ','
                    << static_cast<unsigned>(seed.route_sector) << ',' << lineage << ','
                    << crossing.minimum_abs_guard << ',' << elevation_degrees << ",\"" << name << "\"\n";
            ++events;
        }
    }

    std::cerr << "KLOC1 coarse visibility schedule\n"
              << "  intervals              : " << intervals << '\n'
              << "  seeds                  : " << data.seeds.size() << '\n'
              << "  candidate intervals    : " << candidate_intervals << '\n'
              << "  support survivors      : " << supported_intervals << '\n'
              << "  compatible survivors   : " << compatible_intervals << '\n'
              << "  visible samples        : " << visible_samples << '\n'
              << "  acquisition/loss events: " << events << '\n'
              << "  model boundary         : coarse Kepler+J2; not SGP4/navigation\n";
    return 0;
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
        if (command == "--help" || command == "-h") usage(argv[0], 0);
        throw std::invalid_argument("unknown command: " + command);
    } catch (const std::exception& error) {
        std::cerr << "error: " << error.what() << '\n';
        return 1;
    }
}
