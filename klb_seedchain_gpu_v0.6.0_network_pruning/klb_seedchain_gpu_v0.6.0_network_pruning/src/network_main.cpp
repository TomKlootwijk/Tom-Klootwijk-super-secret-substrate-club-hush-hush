#include "klb/network.hpp"

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
#include <vector>

namespace {

[[noreturn]] void usage(const char* executable, int code) {
    std::ostream& out = code == 0 ? std::cout : std::cerr;
    out << "KLB mixed-orbit network and pruning challenge\n\n"
        << "Usage:\n"
        << "  " << executable << " inspect <input.ksgp> <stations.csv> [--pairs pairs.csv]\n"
        << "  " << executable << " run <input.ksgp> <stations.csv> [options]\n"
        << "  " << executable << " verify <input.ksgp> <stations.csv> [options]\n\n"
        << "Run/verify options:\n"
        << "  --mode all|support|active  relation mask for run (default active)\n"
        << "  --start-seconds N          start relative to KSGP reference (default 0)\n"
        << "  --hours N                  duration in hours (default container horizon)\n"
        << "  --step-seconds N           event-sampling step (default container step)\n"
        << "  --dut1-seconds N           UT1-UTC override (default container value)\n"
        << "  --events FILE              write active/run event CSV\n"
        << "  --pairs FILE               write audited object-station pair CSV\n"
        << "  --summary FILE             write text summary\n"
        << "  --metrics FILE             write one-row-per-mode CSV\n";
    std::exit(code);
}

double parse_double(const char* text, const char* option) {
    std::size_t consumed = 0u;
    double value = 0.0;
    try {
        value = std::stod(text, &consumed);
    } catch (const std::exception&) {
        throw std::invalid_argument(std::string("invalid ") + option + ": " + text);
    }
    if (consumed != std::string(text).size() || !std::isfinite(value)) {
        throw std::invalid_argument(std::string("invalid ") + option + ": " + text);
    }
    return value;
}

klb::NetworkPairMode parse_mode(const std::string& text) {
    if (text == "all") return klb::NetworkPairMode::All;
    if (text == "support") return klb::NetworkPairMode::Support;
    if (text == "active") return klb::NetworkPairMode::Active;
    throw std::invalid_argument("--mode must be all, support, or active");
}

const char* mode_name(klb::NetworkPairMode mode) {
    switch (mode) {
        case klb::NetworkPairMode::All: return "all";
        case klb::NetworkPairMode::Support: return "support";
        case klb::NetworkPairMode::Active: return "active";
    }
    return "unknown";
}

struct RunOptions {
    klb::NetworkPairMode mode = klb::NetworkPairMode::Active;
    double start_seconds = 0.0;
    double duration_seconds = -1.0;
    double step_seconds = -1.0;
    double dut1_seconds = std::numeric_limits<double>::quiet_NaN();
    std::filesystem::path events_path;
    std::filesystem::path pairs_path;
    std::filesystem::path summary_path;
    std::filesystem::path metrics_path;
};

RunOptions parse_run_options(int argc, char** argv, int start) {
    RunOptions options{};
    for (int index = start; index < argc; ++index) {
        const std::string argument = argv[index];
        auto value = [&]() -> const char* {
            if (++index >= argc) throw std::invalid_argument(argument + " requires a value");
            return argv[index];
        };
        if (argument == "--mode") options.mode = parse_mode(value());
        else if (argument == "--start-seconds") options.start_seconds = parse_double(value(), "--start-seconds");
        else if (argument == "--hours") options.duration_seconds = parse_double(value(), "--hours") * 3600.0;
        else if (argument == "--step-seconds") options.step_seconds = parse_double(value(), "--step-seconds");
        else if (argument == "--dut1-seconds") options.dut1_seconds = parse_double(value(), "--dut1-seconds");
        else if (argument == "--events") options.events_path = value();
        else if (argument == "--pairs") options.pairs_path = value();
        else if (argument == "--summary") options.summary_path = value();
        else if (argument == "--metrics") options.metrics_path = value();
        else if (argument == "--help" || argument == "-h") usage(argv[0], 0);
        else throw std::invalid_argument("unknown option: " + argument);
    }
    return options;
}

void print_plan(std::ostream& out,
                const klb::Sgp4Data& data,
                const std::vector<klb::NetworkStation>& stations,
                const klb::NetworkPlan& plan) {
    out << std::fixed << std::setprecision(6)
        << "Mixed-orbit network plan\n"
        << "  reference UTC              : "
        << klb::format_unix_microseconds_iso8601(data.header.reference_unix_microseconds) << '\n'
        << "  objects                    : " << plan.stats.objects << '\n'
        << "  stations                   : " << plan.stats.stations << '\n'
        << "  all object-station pairs   : " << plan.stats.total_pairs << '\n'
        << "  support-possible pairs     : " << plan.stats.support_pairs << '\n'
        << "  policy-compatible pairs    : " << plan.stats.active_pairs << '\n'
        << "  support rejection gain     : " << plan.stats.support_rejection_gain << "x\n"
        << "  compatibility gain         : " << plan.stats.compatibility_rejection_gain << "x\n"
        << "  total relation gain        : " << plan.stats.total_rejection_gain << "x\n";
    std::uint64_t leo = 0, meo = 0, geo = 0, heo = 0;
    for (const klb::NetworkObjectProfile& object : plan.objects) {
        if (object.orbit_class == klb::kNetworkOrbitLeo) ++leo;
        else if (object.orbit_class == klb::kNetworkOrbitMeo) ++meo;
        else if (object.orbit_class == klb::kNetworkOrbitGeo) ++geo;
        else if (object.orbit_class == klb::kNetworkOrbitHeo) ++heo;
    }
    out << "  orbit classes              : LEO=" << leo << ", MEO=" << meo
        << ", GEO=" << geo << ", HEO=" << heo << '\n'
        << "  station-bitmask limit      : " << stations.size() << "/32\n"
        << "  policy boundary            : benchmark profiles, not operational station authorizations\n"
        << "  frame boundary             : TEME->PEF GMST+DUT1; polar motion/EOP omitted\n";
}

void print_run(std::ostream& out, const char* label, const klb::NetworkRunResult& result) {
    const klb::NetworkRunStats& s = result.stats;
    const double relation_rate = s.elapsed_seconds > 0.0
        ? static_cast<double>(s.relation_intervals) / s.elapsed_seconds : 0.0;
    const double propagation_rate = s.elapsed_seconds > 0.0
        ? static_cast<double>(s.propagated_object_intervals) / s.elapsed_seconds : 0.0;
    out << std::fixed << std::setprecision(6)
        << label << '\n'
        << "  elapsed                    : " << s.elapsed_seconds << " s\n"
        << "  time intervals             : " << s.intervals << '\n'
        << "  propagated object intervals: " << s.propagated_object_intervals << '\n'
        << "  relation intervals         : " << s.relation_intervals << '\n'
        << "  supported intervals        : " << s.supported_intervals << '\n'
        << "  compatible intervals       : " << s.compatible_intervals << '\n'
        << "  boundary evaluations       : " << s.boundary_evaluations << '\n'
        << "  visible endpoints          : " << s.visible_endpoints << '\n'
        << "  acquisition events         : " << s.acquisition_events << '\n'
        << "  loss events                : " << s.loss_events << '\n'
        << "  total events               : " << result.events.size() << '\n'
        << "  propagation failures       : " << s.propagation_failures << '\n'
        << "  object propagations/s      : " << propagation_rate << '\n'
        << "  logical relations/s        : " << relation_rate << '\n';
}

void write_metrics(const std::filesystem::path& path,
                   const klb::NetworkPlan& plan,
                   const std::vector<std::pair<std::string, klb::NetworkRunResult>>& rows) {
    if (path.empty()) return;
    if (!path.parent_path().empty()) std::filesystem::create_directories(path.parent_path());
    std::ofstream out(path, std::ios::trunc);
    if (!out) throw std::runtime_error("unable to create metrics CSV: " + path.string());
    out << "mode,objects,stations,total_pairs,support_pairs,active_pairs,support_rejection_gain,"
           "compatibility_rejection_gain,total_rejection_gain,intervals,propagated_object_intervals,"
           "relation_intervals,supported_intervals,compatible_intervals,boundary_evaluations,"
           "visible_endpoints,acquisition_events,loss_events,total_events,propagation_failures,"
           "elapsed_seconds,object_propagations_per_second,logical_relations_per_second\n";
    out << std::fixed << std::setprecision(9);
    for (const auto& row : rows) {
        const auto& s = row.second.stats;
        out << row.first << ',' << plan.stats.objects << ',' << plan.stats.stations << ','
            << plan.stats.total_pairs << ',' << plan.stats.support_pairs << ',' << plan.stats.active_pairs << ','
            << plan.stats.support_rejection_gain << ',' << plan.stats.compatibility_rejection_gain << ','
            << plan.stats.total_rejection_gain << ',' << s.intervals << ','
            << s.propagated_object_intervals << ',' << s.relation_intervals << ','
            << s.supported_intervals << ',' << s.compatible_intervals << ','
            << s.boundary_evaluations << ',' << s.visible_endpoints << ','
            << s.acquisition_events << ',' << s.loss_events << ',' << row.second.events.size() << ','
            << s.propagation_failures << ',' << s.elapsed_seconds << ','
            << (s.elapsed_seconds > 0.0 ? static_cast<double>(s.propagated_object_intervals) / s.elapsed_seconds : 0.0) << ','
            << (s.elapsed_seconds > 0.0 ? static_cast<double>(s.relation_intervals) / s.elapsed_seconds : 0.0) << '\n';
    }
}

int command_inspect(int argc, char** argv) {
    if (argc < 4) usage(argv[0], 2);
    const std::filesystem::path input = argv[2];
    const std::filesystem::path station_path = argv[3];
    std::filesystem::path pairs_path;
    for (int index = 4; index < argc; ++index) {
        const std::string argument = argv[index];
        if (argument == "--pairs") {
            if (++index >= argc) throw std::invalid_argument("--pairs requires a value");
            pairs_path = argv[index];
        } else if (argument == "--help" || argument == "-h") usage(argv[0], 0);
        else throw std::invalid_argument("unknown inspect option: " + argument);
    }
    const klb::Sgp4Data data = klb::load_sgp4_data(input);
    const std::vector<klb::Sgp4Record> records = klb::compile_sgp4_records(data);
    const std::vector<klb::NetworkStation> stations = klb::load_network_stations_csv(station_path);
    const klb::NetworkPlan plan = klb::build_network_plan(data, records, stations);
    print_plan(std::cout, data, stations, plan);
    if (!pairs_path.empty()) {
        klb::save_network_pairs_csv(pairs_path, data, stations, plan);
        std::cout << "  pair audit CSV             : " << pairs_path.string() << '\n';
    }
    return plan.stats.active_pairs == 0u ? 1 : 0;
}

int command_run(int argc, char** argv) {
    if (argc < 4) usage(argv[0], 2);
    const std::filesystem::path input = argv[2];
    const std::filesystem::path station_path = argv[3];
    RunOptions options = parse_run_options(argc, argv, 4);
    const klb::Sgp4Data data = klb::load_sgp4_data(input);
    const std::vector<klb::Sgp4Record> records = klb::compile_sgp4_records(data);
    const std::vector<klb::NetworkStation> stations = klb::load_network_stations_csv(station_path);
    const klb::NetworkPlan plan = klb::build_network_plan(data, records, stations);
    if (options.duration_seconds < 0.0) options.duration_seconds = data.header.timeline_duration_seconds;
    if (options.step_seconds < 0.0) options.step_seconds = data.header.timeline_step_seconds;
    if (std::isnan(options.dut1_seconds)) options.dut1_seconds = data.header.default_dut1_seconds;

    const klb::NetworkRunResult result = klb::run_network_cpu(
        data, records, stations, plan, options.mode, options.start_seconds,
        options.duration_seconds, options.step_seconds, options.dut1_seconds);
    print_plan(std::cout, data, stations, plan);
    print_run(std::cout, (std::string("CPU network run mode=") + mode_name(options.mode)).c_str(), result);
    if (!options.events_path.empty()) klb::save_network_events_csv(options.events_path, data, stations, result.events);
    if (!options.pairs_path.empty()) klb::save_network_pairs_csv(options.pairs_path, data, stations, plan);
    write_metrics(options.metrics_path, plan, {{mode_name(options.mode), result}});
    if (!options.summary_path.empty()) {
        if (!options.summary_path.parent_path().empty()) std::filesystem::create_directories(options.summary_path.parent_path());
        std::ofstream summary(options.summary_path, std::ios::trunc);
        print_plan(summary, data, stations, plan);
        print_run(summary, (std::string("CPU network run mode=") + mode_name(options.mode)).c_str(), result);
    }
    return result.stats.propagation_failures == 0u ? 0 : 1;
}

int command_verify(int argc, char** argv) {
    if (argc < 4) usage(argv[0], 2);
    const std::filesystem::path input = argv[2];
    const std::filesystem::path station_path = argv[3];
    RunOptions options = parse_run_options(argc, argv, 4);
    const klb::Sgp4Data data = klb::load_sgp4_data(input);
    klb::validate_sgp4_data(data, true);
    const std::vector<klb::Sgp4Record> records = klb::compile_sgp4_records(data);
    const std::vector<klb::NetworkStation> stations = klb::load_network_stations_csv(station_path);
    const klb::NetworkPlan plan = klb::build_network_plan(data, records, stations);
    if (options.duration_seconds < 0.0) options.duration_seconds = data.header.timeline_duration_seconds;
    if (options.step_seconds < 0.0) options.step_seconds = data.header.timeline_step_seconds;
    if (std::isnan(options.dut1_seconds)) options.dut1_seconds = data.header.default_dut1_seconds;

    const klb::NetworkRunResult all = klb::run_network_cpu(
        data, records, stations, plan, klb::NetworkPairMode::All,
        options.start_seconds, options.duration_seconds, options.step_seconds, options.dut1_seconds);
    const klb::NetworkRunResult support = klb::run_network_cpu(
        data, records, stations, plan, klb::NetworkPairMode::Support,
        options.start_seconds, options.duration_seconds, options.step_seconds, options.dut1_seconds);
    const klb::NetworkRunResult active = klb::run_network_cpu(
        data, records, stations, plan, klb::NetworkPairMode::Active,
        options.start_seconds, options.duration_seconds, options.step_seconds, options.dut1_seconds);

    const bool support_events_match = klb::network_events_equal(all.events, support.events);
    const bool active_events_match = klb::network_events_equal(all.events, active.events);
    const bool support_counts_match = all.stats.supported_intervals == support.stats.supported_intervals;
    const bool active_compatible_match = all.stats.compatible_intervals == active.stats.compatible_intervals;
    const bool failures_zero = all.stats.propagation_failures == 0u &&
        support.stats.propagation_failures == 0u && active.stats.propagation_failures == 0u;

    print_plan(std::cout, data, stations, plan);
    print_run(std::cout, "CPU all-pairs relation oracle", all);
    print_run(std::cout, "CPU support-envelope relation set", support);
    print_run(std::cout, "CPU support+compatibility active set", active);
    std::cout << std::fixed << std::setprecision(6)
        << "Pruning acceptance\n"
        << "  all/support event identity : " << (support_events_match ? "PASS" : "FAIL") << '\n'
        << "  all/active event identity  : " << (active_events_match ? "PASS" : "FAIL") << '\n'
        << "  support survivor equality  : " << (support_counts_match ? "PASS" : "FAIL") << '\n'
        << "  active compatible equality : " << (active_compatible_match ? "PASS" : "FAIL") << '\n'
        << "  propagation failures zero  : " << (failures_zero ? "PASS" : "FAIL") << '\n'
        << "  all/active CPU time ratio  : "
        << (active.stats.elapsed_seconds > 0.0 ? all.stats.elapsed_seconds / active.stats.elapsed_seconds : 0.0) << "x\n"
        << "  relation work reduction    : "
        << (active.stats.relation_intervals > 0u
            ? static_cast<double>(all.stats.relation_intervals) / static_cast<double>(active.stats.relation_intervals)
            : 0.0) << "x\n";

    if (!options.events_path.empty()) klb::save_network_events_csv(options.events_path, data, stations, active.events);
    if (!options.pairs_path.empty()) klb::save_network_pairs_csv(options.pairs_path, data, stations, plan);
    write_metrics(options.metrics_path, plan, {{"all", all}, {"support", support}, {"active", active}});
    if (!options.summary_path.empty()) {
        if (!options.summary_path.parent_path().empty()) std::filesystem::create_directories(options.summary_path.parent_path());
        std::ofstream summary(options.summary_path, std::ios::trunc);
        print_plan(summary, data, stations, plan);
        print_run(summary, "CPU all-pairs relation oracle", all);
        print_run(summary, "CPU support-envelope relation set", support);
        print_run(summary, "CPU support+compatibility active set", active);
        summary << "Pruning acceptance\n"
                << "  all/support event identity : " << (support_events_match ? "PASS" : "FAIL") << '\n'
                << "  all/active event identity  : " << (active_events_match ? "PASS" : "FAIL") << '\n'
                << "  support survivor equality  : " << (support_counts_match ? "PASS" : "FAIL") << '\n'
                << "  active compatible equality : " << (active_compatible_match ? "PASS" : "FAIL") << '\n'
                << "  propagation failures zero  : " << (failures_zero ? "PASS" : "FAIL") << '\n';
    }
    return support_events_match && active_events_match && support_counts_match &&
           active_compatible_match && failures_zero ? 0 : 1;
}

} // namespace

int main(int argc, char** argv) {
    try {
        if (argc < 2) usage(argv[0], 2);
        const std::string command = argv[1];
        if (command == "inspect") return command_inspect(argc, argv);
        if (command == "run") return command_run(argc, argv);
        if (command == "verify") return command_verify(argc, argv);
        if (command == "--help" || command == "-h") usage(argv[0], 0);
        throw std::invalid_argument("unknown command: " + command);
    } catch (const std::exception& error) {
        std::cerr << "error: " << error.what() << '\n';
        return 1;
    }
}
