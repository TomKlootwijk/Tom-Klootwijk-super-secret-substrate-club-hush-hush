#include "klb/network.hpp"

#include <filesystem>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {

void require(bool condition, const std::string& message) {
    if (!condition) throw std::runtime_error(message);
}

std::filesystem::path source_root() {
    return std::filesystem::path(__FILE__).parent_path().parent_path();
}

void test_masks() {
    require(klb::parse_network_orbit_mask("LEO|MEO") ==
                (klb::kNetworkOrbitLeo | klb::kNetworkOrbitMeo),
            "orbit mask parse failed");
    require(klb::parse_network_service_mask("NAV|SCIENCE") ==
                (klb::kNetworkServiceNavigation | klb::kNetworkServiceScience),
            "service mask parse failed");
    require(klb::parse_network_route_mask("0|2|5") == ((1u << 0u) | (1u << 2u) | (1u << 5u)),
            "route mask parse failed");
    require(klb::network_orbit_mask_string(klb::kNetworkOrbitGeo) == "GEO",
            "orbit mask format failed");
}

void test_plan_and_pruning() {
    const std::filesystem::path root = source_root();
    const std::filesystem::path source =
        root / "data/network/source/celestrak_mixed_gps_tdrss_2026-08-16_omm.csv";
    const std::filesystem::path station_path =
        root / "data/network/benchmark_station_network.csv";

    klb::Sgp4PackOptions options{};
    options.horizon_seconds = 6.0 * 3600.0;
    options.step_seconds = 300.0;
    options.tile_seconds = 6.0 * 3600.0;
    options.elevation_mask_degrees = 10.0;
    const klb::Sgp4Data data = klb::pack_omm_csv_sgp4(source, options);
    const std::vector<klb::Sgp4Record> records = klb::compile_sgp4_records(data);
    const std::vector<klb::NetworkStation> stations =
        klb::load_network_stations_csv(station_path);
    require(data.seeds.size() == 58u, "mixed source must contain 58 objects");
    require(stations.size() == 16u, "benchmark network must contain 16 stations");

    const klb::NetworkPlan plan = klb::build_network_plan(data, records, stations);
    require(plan.stats.total_pairs == 58u * 16u, "total pair count is wrong");
    require(plan.stats.support_pairs > 0u && plan.stats.support_pairs < plan.stats.total_pairs,
            "support envelope did not prune");
    require(plan.stats.active_pairs > 0u && plan.stats.active_pairs < plan.stats.support_pairs,
            "compatibility policy did not prune");
    require(plan.stats.total_rejection_gain > 2.0, "combined pruning gain is unexpectedly weak");

    std::uint64_t leo = 0u, meo = 0u, geo = 0u, heo = 0u;
    for (const klb::NetworkObjectProfile& object : plan.objects) {
        if (object.orbit_class == klb::kNetworkOrbitLeo) ++leo;
        else if (object.orbit_class == klb::kNetworkOrbitMeo) ++meo;
        else if (object.orbit_class == klb::kNetworkOrbitGeo) ++geo;
        else if (object.orbit_class == klb::kNetworkOrbitHeo) ++heo;
    }
    require(leo > 0u && meo > 0u && geo > 0u && heo > 0u,
            "mixed source did not cover all four orbit classes");

    const double duration = 6.0 * 3600.0;
    const double step = 300.0;
    const klb::NetworkRunResult all = klb::run_network_cpu(
        data, records, stations, plan, klb::NetworkPairMode::All,
        0.0, duration, step, 0.0);
    const klb::NetworkRunResult support = klb::run_network_cpu(
        data, records, stations, plan, klb::NetworkPairMode::Support,
        0.0, duration, step, 0.0);
    const klb::NetworkRunResult active = klb::run_network_cpu(
        data, records, stations, plan, klb::NetworkPairMode::Active,
        0.0, duration, step, 0.0);

    require(all.stats.propagation_failures == 0u &&
            support.stats.propagation_failures == 0u &&
            active.stats.propagation_failures == 0u,
            "network propagation failure");
    require(klb::network_events_equal(all.events, support.events),
            "support envelope removed a real event");
    require(klb::network_events_equal(all.events, active.events),
            "compatibility pruning changed the event set");
    require(all.stats.supported_intervals == support.stats.supported_intervals,
            "support-pruned survivor count differs from all-pairs oracle");
    require(all.stats.compatible_intervals == active.stats.compatible_intervals,
            "active compatible count differs from all-pairs oracle");
    require(active.stats.relation_intervals < all.stats.relation_intervals,
            "active relation work was not reduced");

    const std::filesystem::path temp = std::filesystem::temp_directory_path() /
        "klb_network_test_output";
    std::filesystem::remove_all(temp);
    klb::save_network_pairs_csv(temp / "pairs.csv", data, stations, plan);
    klb::save_network_events_csv(temp / "events.csv", data, stations, active.events);
    require(std::filesystem::file_size(temp / "pairs.csv") > 100u,
            "pair CSV was not written");
    require(std::filesystem::file_size(temp / "events.csv") > 100u,
            "event CSV was not written");
    std::filesystem::remove_all(temp);
}

} // namespace

int main() {
    try {
        test_masks();
        test_plan_and_pruning();
        std::cout << "KLB network tests passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "KLB network test failure: " << error.what() << '\n';
        return 1;
    }
}
