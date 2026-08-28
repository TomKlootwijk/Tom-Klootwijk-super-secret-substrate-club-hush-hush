#include "klb/sgp4.hpp"

#include <array>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

void require(bool condition, const std::string& message) {
    if (!condition) throw std::runtime_error(message);
}

double norm_difference(const double actual[3], const double expected[3]) {
    const double x = actual[0] - expected[0];
    const double y = actual[1] - expected[1];
    const double z = actual[2] - expected[2];
    return std::sqrt(x * x + y * y + z * z);
}

void set_tle_epoch(klb::Sgp4Record& record, int year, double day_of_year) {
    double jd = 0.0;
    double fraction = 0.0;
    klb::sgp4_jday(year, 1, 1, 0, 0, 0.0, jd, fraction);
    const double full = jd + fraction + day_of_year - 1.0;
    record.jdsatepoch = std::floor(full - 0.5) + 0.5;
    record.jdsatepochF = full - record.jdsatepoch;
}

struct ValladoCase {
    const char* name;
    int year;
    double epoch_day;
    double bstar;
    double ndot_rev_day2;
    double nddot_rev_day3;
    double inclination_degrees;
    double raan_degrees;
    double eccentricity;
    double argument_perigee_degrees;
    double mean_anomaly_degrees;
    double mean_motion_rev_day;
    double minutes_since_epoch;
    std::array<double, 3> expected_position_km;
    std::array<double, 3> expected_velocity_km_s;
    char expected_method;
    int expected_irez;
};

klb::Sgp4Record make_record(const ValladoCase& test) {
    constexpr double xpdotp = 1440.0 / klb::kSgp4TwoPi;
    klb::Sgp4Record record{};
    record.whichconst = klb::kSgp4Wgs72;
    set_tle_epoch(record, test.year, test.epoch_day);
    record.bstar = test.bstar;
    record.ndot = test.ndot_rev_day2 / (xpdotp * 1440.0);
    record.nddot = test.nddot_rev_day3 / (xpdotp * 1440.0 * 1440.0);
    record.inclo = test.inclination_degrees * klb::kSgp4DegToRad;
    record.nodeo = test.raan_degrees * klb::kSgp4DegToRad;
    record.ecco = test.eccentricity;
    record.argpo = test.argument_perigee_degrees * klb::kSgp4DegToRad;
    record.mo = test.mean_anomaly_degrees * klb::kSgp4DegToRad;
    record.no_kozai = test.mean_motion_rev_day / xpdotp;
    require(klb::sgp4_initialize(record, 'i'), std::string(test.name) + " initialization failed");
    return record;
}

void test_reference_vectors() {
    // Vallado/CSSI verification vectors cover near-Earth, deep-space
    // non-resonant, synchronous resonance, half-day resonance, and a
    // GPS-like low-eccentricity deep-space orbit.
    const std::vector<ValladoCase> tests{
        {
            "00005 near-Earth", 2000, 179.78495062, 2.8098e-5, 0.00000023, 0.0,
            34.2682, 348.7242, 0.1859667, 331.7664, 19.3264, 10.82419157, 0.0,
            {7022.46529266, -1400.08296755, 0.03995155},
            {1.893841015, 6.405893759, 4.534807250}, 'n', 0,
        },
        {
            "04632 deep-space non-resonant", 2004, 31.91070959, 1.0e-4, -0.00000084, 0.0,
            11.4628, 273.1101, 0.1450506, 207.6000, 143.9350, 1.20231981, -5184.0,
            {-29020.02587128, 13819.84419063, -5713.33679183},
            {-1.768068390, -3.235371192, -0.395206135}, 'd', 0,
        },
        {
            "08195 half-day resonance", 2006, 176.33215444, 1.1873e-4, 0.00000099, 0.0,
            64.1586, 279.0717, 0.6877146, 264.7651, 20.2257, 2.00491383, 120.0,
            {15223.91713658, -17852.95881713, 25280.39558224},
            {1.079041732, 0.875187372, 2.485682813}, 'd', 2,
        },
        {
            "14128 synchronous resonance", 2006, 176.02844893, 1.0e-4, -0.00000158, 0.0,
            11.4384, 35.2134, 0.0011562, 26.4582, 333.5652, 0.98870114, 120.0,
            {18263.33439094, 38159.96004751, 4186.18304085},
            {-2.744396611, 1.255583260, 0.528558932}, 'd', 1,
        },
        {
            "28129 GPS-like deep-space", 2006, 175.57071136, 1.0e-4, -0.00000104, 0.0,
            54.7298, 324.8098, 0.0048506, 266.2640, 93.1663, 2.00562768, 120.0,
            {18616.75971861, 3166.15177043, 18833.41523210},
            {-2.076122016, 2.838457575, 1.586210535}, 'd', 0,
        },
    };

    for (const ValladoCase& test : tests) {
        const klb::Sgp4Record record = make_record(test);
        require(record.method == test.expected_method,
                std::string(test.name) + " selected the wrong near/deep branch");
        require(record.irez == test.expected_irez,
                std::string(test.name) + " selected the wrong resonance branch");

        double position[3]{};
        double velocity[3]{};
        int error = 0;
        require(klb::sgp4_propagate_immutable(record, test.minutes_since_epoch,
                                               position, velocity, &error),
                std::string(test.name) + " propagation failed with error " + std::to_string(error));
        const double position_error = norm_difference(position, test.expected_position_km.data());
        const double velocity_error = norm_difference(velocity, test.expected_velocity_km_s.data());
        std::cout << test.name << ": dr=" << position_error
                  << " km, dv=" << velocity_error << " km/s\n";
        require(position_error < 1.0e-5,
                std::string(test.name) + " position reference mismatch");
        require(velocity_error < 1.0e-8,
                std::string(test.name) + " velocity reference mismatch");

        klb::Sgp4Record mutable_record = record;
        double mutable_position[3]{};
        double mutable_velocity[3]{};
        require(klb::sgp4_propagate_mutable(mutable_record, test.minutes_since_epoch,
                                             mutable_position, mutable_velocity),
                std::string(test.name) + " mutable propagation failed");
        require(norm_difference(position, mutable_position) < 1.0e-12,
                std::string(test.name) + " mutable/immutable position disagreement");
        require(norm_difference(velocity, mutable_velocity) < 1.0e-12,
                std::string(test.name) + " mutable/immutable velocity disagreement");
    }
}

void test_container_round_trip() {
    const std::filesystem::path directory = std::filesystem::temp_directory_path();
    const std::filesystem::path csv = directory / "klb_sgp4_test_input.csv";
    const std::filesystem::path packed = directory / "klb_sgp4_test_output.ksgp";
    {
        std::ofstream output(csv, std::ios::trunc);
        require(static_cast<bool>(output), "unable to create temporary OMM CSV");
        output
            << "OBJECT_NAME,OBJECT_ID,EPOCH,MEAN_MOTION,ECCENTRICITY,INCLINATION,RA_OF_ASC_NODE,ARG_OF_PERICENTER,MEAN_ANOMALY,EPHEMERIS_TYPE,CLASSIFICATION_TYPE,NORAD_CAT_ID,ELEMENT_SET_NO,REV_AT_EPOCH,BSTAR,MEAN_MOTION_DOT,MEAN_MOTION_DDOT\n"
            << "GPS BIIR-5  (PRN 22),2000-040A,2026-08-16T05:01:25.315392,2.00558143,.01194961,54.8445,212.7788,303.2314,118.5286,0,U,26407,999,19115,0,.37E-6,0\n"
            << "GPS BIIR-8  (PRN 16),2003-005A,2026-08-15T23:25:25.268160,2.00557354,.01491618,54.8746,212.5941,53.3572,336.1519,0,U,27663,999,17251,0,.35E-6,0\n";
    }

    klb::Sgp4PackOptions options{};
    options.horizon_seconds = 48.0 * 3600.0;
    options.step_seconds = 10.0;
    options.tile_seconds = 12.0 * 3600.0;
    options.elevation_mask_degrees = 12.5;
    options.dut1_seconds = 0.123;
    const klb::Sgp4Data data = klb::pack_omm_csv_sgp4(csv, options);
    require(data.seeds.size() == 2u, "OMM CSV seed count mismatch");
    require(data.nodes.size() == 4u, "timeline node count mismatch");
    require(klb::sgp4_seed_prn(data.seeds.front()) == 22u,
            "PRN parsing mismatch after NORAD sorting");
    require(data.header.predictor_model == klb::kSgp4ModelVallado2006,
            "KSGP1 model identifier mismatch");
    require((data.header.flags & klb::kSgp4FlagFullModel) != 0u,
            "KSGP1 full-model flag missing");

    const std::vector<klb::Sgp4Record> records = klb::compile_sgp4_records(data);
    require(records.size() == data.seeds.size(), "compiled coefficient count mismatch");
    for (std::size_t index = 0; index < records.size(); ++index) {
        const double minutes = klb::sgp4_minutes_from_reference(
            data.seeds[index], 3600.0,
            static_cast<double>(data.header.reference_unix_microseconds) / 1.0e6);
        const klb::Sgp4State state = klb::sgp4_state_at(records[index], minutes);
        require(state.error == 0, "compiled GPS seed failed to propagate");
        const double radius = std::sqrt(
            state.position_teme_km[0] * state.position_teme_km[0] +
            state.position_teme_km[1] * state.position_teme_km[1] +
            state.position_teme_km[2] * state.position_teme_km[2]);
        require(radius > 25000.0 && radius < 28000.0,
                "compiled GPS seed produced implausible radius");
    }

    klb::save_sgp4_data(packed, data);
    const klb::Sgp4Data loaded = klb::load_sgp4_data(packed);
    require(loaded.header.payload_hash == data.header.payload_hash,
            "KSGP1 payload hash changed across save/load");
    require(loaded.header.chain_hash == data.header.chain_hash,
            "KSGP1 chain hash changed across save/load");
    require(klb::sgp4_string_at(loaded, loaded.seeds.front().name_offset).find("PRN") != std::string::npos,
            "KSGP1 string table round trip failed");
    const klb::Sgp4Stats stats = klb::inspect_sgp4_data(
        loaded, std::filesystem::file_size(packed));
    require(stats.ratio_vs_dense_float4 > 100.0,
            "KSGP1 horizon-relative compression ratio is unexpectedly small");
    require(stats.coefficient_bytes == loaded.seeds.size() * sizeof(klb::Sgp4Record),
            "compiled coefficient footprint mismatch");

    std::error_code ignored;
    std::filesystem::remove(csv, ignored);
    std::filesystem::remove(packed, ignored);
}

void test_teme_to_pef_rotation() {
    const double input[3]{1.0, 0.0, 2.0};
    double output[3]{};
    klb::sgp4_teme_to_pef(input, 2451545.0, output);
    const double expected_radius = std::sqrt(5.0);
    const double actual_radius = std::sqrt(
        output[0] * output[0] + output[1] * output[1] + output[2] * output[2]);
    require(std::fabs(actual_radius - expected_radius) < 1.0e-12,
            "TEME-to-PEF rotation did not preserve radius");
}

} // namespace

int main() {
    try {
        test_reference_vectors();
        test_container_round_trip();
        test_teme_to_pef_rotation();
        std::cout << "KLB full SGP4/SDP4 tests passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "SGP4 test failure: " << error.what() << '\n';
        return 1;
    }
}
