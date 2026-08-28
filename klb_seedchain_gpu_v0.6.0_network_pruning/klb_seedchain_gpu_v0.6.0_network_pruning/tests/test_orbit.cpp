#include "klb/orbit.hpp"

#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {

void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

template <typename Function>
void require_throws(Function&& function, const char* message) {
    try {
        function();
    } catch (...) {
        return;
    }
    throw std::runtime_error(message);
}

std::filesystem::path temporary_path(const char* suffix) {
    const auto base = std::filesystem::temp_directory_path();
    return base / ("klb_orbit_test_" + std::to_string(klb::mix32(0x12345678u)) + suffix);
}

} // namespace

int main() {
    try {
        const std::filesystem::path csv_path = temporary_path(".csv");
        const std::filesystem::path kloc_path = temporary_path(".kloc");
        {
            std::ofstream output(csv_path, std::ios::trunc);
            output
                << "OBJECT_NAME,OBJECT_ID,EPOCH,MEAN_MOTION,ECCENTRICITY,INCLINATION,RA_OF_ASC_NODE,ARG_OF_PERICENTER,MEAN_ANOMALY,EPHEMERIS_TYPE,CLASSIFICATION_TYPE,NORAD_CAT_ID,ELEMENT_SET_NO,REV_AT_EPOCH,BSTAR,MEAN_MOTION_DOT,MEAN_MOTION_DDOT\n"
                << "GPS TEST A (PRN 01),2020-001A,2026-08-16T00:00:00.000000,2.0056,.0100,55.0,30.0,10.0,20.0,0,U,10001,1,1,0,0,0\n"
                << "\"GPS, TEST B (PRN 02)\",2020-002A,2026-08-16T00:10:00.000000,2.0057,.0200,56.0,330.0,20.0,30.0,0,U,10002,1,1,0,0,0\n";
        }

        klb::OrbitPackOptions options{};
        options.horizon_seconds = 3600.0f;
        options.step_seconds = 10.0f;
        options.tile_seconds = 1200.0f;
        const klb::OrbitData packed = klb::pack_omm_csv(csv_path, options);
        require(packed.seeds.size() == 2u, "OMM row count mismatch");
        require(packed.nodes.size() == 3u, "timeline node count mismatch");
        require(packed.header.timeline_sample_count == 361u, "timeline sample count mismatch");
        require(packed.seeds[0].norad_id == 10001u, "NORAD sort mismatch");
        require(packed.seeds[0].prn == 1u && packed.seeds[1].prn == 2u, "PRN parse mismatch");
        require(klb::orbit_string_at(packed, packed.seeds[1].name_offset).find("GPS, TEST B") != std::string::npos,
                "quoted CSV parse mismatch");
        require(packed.nodes[0].parent_index == klb::kNoOrbitParent, "root parent mismatch");
        require(packed.nodes[1].parent_hash == packed.nodes[0].self_hash, "node chain mismatch");
        klb::validate_orbit_data(packed, true);

        klb::save_orbit_data(kloc_path, packed);
        const klb::OrbitData loaded = klb::load_orbit_data(kloc_path);
        require(loaded.header.payload_hash == packed.header.payload_hash, "save/load payload hash mismatch");
        require(loaded.header.chain_hash == packed.header.chain_hash, "save/load chain hash mismatch");
        const klb::OrbitStats stats = klb::inspect_orbit_data(loaded, std::filesystem::file_size(kloc_path));
        require(stats.equivalent_dense_float4_bytes == 361u * 2u * 16u, "dense equivalent mismatch");
        require(stats.ratio_vs_dense_float4 > 1.0, "expected expanded timeline to exceed container");

        for (const klb::OrbitSeedDisk& seed : loaded.seeds) {
            for (float seconds : {0.0f, 600.0f, 3600.0f}) {
                const klb::Vec3 position = klb::propagate_orbit_seed(seed, seconds);
                const float radius = klb::length(position);
                require(std::isfinite(radius), "non-finite propagated radius");
                require(radius > 25000.0f && radius < 28000.0f, "unexpected GPS-like orbit radius");
            }
        }

        const klb::OrbitGroundStation station = klb::make_ground_station(
            52.0f, 5.0f, 0.05f, 10.0f, 0.25f, 33000.0f);
        const klb::Vec3 position = klb::propagate_orbit_seed(loaded.seeds.front(), 0.0f);
        const klb::OrbitEvaluation visibility = klb::evaluate_orbit_visibility(
            position, 0.0f, station, loaded.header.reference_gmst_rad,
            loaded.header.earth_rotation_rad_s, loaded.seeds.front().route_sector);
        require(std::isfinite(visibility.guard) && std::isfinite(visibility.slant_range_km),
                "non-finite visibility evaluation");
        require(visibility.supported == 1u, "GPS satellite should fall within 33000 km support");

        klb::OrbitData corrupt = loaded;
        corrupt.nodes[1].self_hash ^= 1u;
        require_throws([&]() { klb::validate_orbit_data(corrupt, true); },
                       "hash corruption was not detected");

        std::filesystem::remove(csv_path);
        std::filesystem::remove(kloc_path);
        std::cout << "KLB orbit tests passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "orbit test failure: " << error.what() << '\n';
        return 1;
    }
}
