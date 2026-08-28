#pragma once

#include "klb/sgp4.hpp"

#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

namespace klb {

constexpr std::uint32_t kNetworkOrbitLeo = 1u << 0u;
constexpr std::uint32_t kNetworkOrbitMeo = 1u << 1u;
constexpr std::uint32_t kNetworkOrbitGeo = 1u << 2u;
constexpr std::uint32_t kNetworkOrbitHeo = 1u << 3u;
constexpr std::uint32_t kNetworkOrbitAll =
    kNetworkOrbitLeo | kNetworkOrbitMeo | kNetworkOrbitGeo | kNetworkOrbitHeo;

constexpr std::uint32_t kNetworkServiceNavigation = 1u << 0u;
constexpr std::uint32_t kNetworkServiceRelay = 1u << 1u;
constexpr std::uint32_t kNetworkServiceEarthObservation = 1u << 2u;
constexpr std::uint32_t kNetworkServiceScience = 1u << 3u;
constexpr std::uint32_t kNetworkServiceCrewed = 1u << 4u;
constexpr std::uint32_t kNetworkServiceAll =
    kNetworkServiceNavigation | kNetworkServiceRelay |
    kNetworkServiceEarthObservation | kNetworkServiceScience |
    kNetworkServiceCrewed;

struct alignas(16) NetworkStationGpu {
    Sgp4GroundStation ground{};
    std::uint32_t station_id{};
    std::uint32_t orbit_mask{kNetworkOrbitAll};
    std::uint32_t service_mask{kNetworkServiceAll};
    std::uint32_t route_mask{0x3fu};
};
static_assert(sizeof(NetworkStationGpu) == 96u,
              "network station GPU ABI must stay 96 bytes");

struct NetworkStation {
    NetworkStationGpu gpu{};
    std::string name;
    double latitude_degrees{};
    double longitude_degrees{};
    double altitude_km{};
    double elevation_mask_degrees{};
    double crossing_band_degrees{};
};

struct alignas(16) NetworkObjectProfile {
    std::uint32_t orbit_class{};
    std::uint32_t service_mask{};
    std::uint32_t support_station_mask{};
    std::uint32_t active_station_mask{};
    double period_minutes{};
    double perigee_altitude_km{};
    double apogee_altitude_km{};
    double maximum_abs_latitude_rad{};
};
static_assert(sizeof(NetworkObjectProfile) == 48u,
              "network object profile ABI must stay 48 bytes");

struct NetworkPlanStats {
    std::uint64_t objects{};
    std::uint64_t stations{};
    std::uint64_t total_pairs{};
    std::uint64_t support_pairs{};
    std::uint64_t active_pairs{};
    double support_rejection_gain{};
    double compatibility_rejection_gain{};
    double total_rejection_gain{};
};

struct NetworkPlan {
    std::vector<NetworkObjectProfile> objects;
    NetworkPlanStats stats{};
};

enum class NetworkPairMode : std::uint32_t {
    All = 0u,
    Support = 1u,
    Active = 2u,
};

struct NetworkEvent {
    double crossing_seconds{};
    double minimum_abs_guard{};
    std::uint64_t interval_index{};
    std::uint32_t seed_index{};
    std::uint32_t station_index{};
    std::uint32_t station_id{};
    std::uint32_t norad_id{};
    std::uint32_t type{}; // 1=AOS/acquire, 2=LOS/loss
    std::uint32_t lineage{};
};

struct NetworkRunStats {
    std::uint64_t intervals{};
    std::uint64_t propagated_object_intervals{};
    std::uint64_t relation_intervals{};
    std::uint64_t supported_intervals{};
    std::uint64_t compatible_intervals{};
    std::uint64_t visible_endpoints{};
    std::uint64_t boundary_evaluations{};
    std::uint64_t acquisition_events{};
    std::uint64_t loss_events{};
    std::uint64_t propagation_failures{};
    double elapsed_seconds{};
};

struct NetworkRunResult {
    NetworkRunStats stats{};
    std::vector<NetworkEvent> events;
};

std::vector<NetworkStation> load_network_stations_csv(
    const std::filesystem::path& path);
NetworkObjectProfile classify_network_object(
    const Sgp4SeedDisk& seed,
    const Sgp4Record& record,
    const std::string& name);
bool network_support_possible(
    const NetworkObjectProfile& object,
    const Sgp4Record& record,
    const NetworkStationGpu& station);
NetworkPlan build_network_plan(
    const Sgp4Data& data,
    const std::vector<Sgp4Record>& records,
    const std::vector<NetworkStation>& stations);
NetworkRunResult run_network_cpu(
    const Sgp4Data& data,
    const std::vector<Sgp4Record>& records,
    const std::vector<NetworkStation>& stations,
    const NetworkPlan& plan,
    NetworkPairMode mode,
    double start_seconds,
    double duration_seconds,
    double step_seconds,
    double dut1_seconds);
bool network_events_equal(
    const std::vector<NetworkEvent>& left,
    const std::vector<NetworkEvent>& right,
    double crossing_tolerance_seconds = 1.0e-9,
    double guard_tolerance = 1.0e-12);
void save_network_events_csv(
    const std::filesystem::path& path,
    const Sgp4Data& data,
    const std::vector<NetworkStation>& stations,
    const std::vector<NetworkEvent>& events);
void save_network_pairs_csv(
    const std::filesystem::path& path,
    const Sgp4Data& data,
    const std::vector<NetworkStation>& stations,
    const NetworkPlan& plan);

std::string network_orbit_mask_string(std::uint32_t mask);
std::string network_service_mask_string(std::uint32_t mask);
std::uint32_t parse_network_orbit_mask(const std::string& text);
std::uint32_t parse_network_service_mask(const std::string& text);
std::uint32_t parse_network_route_mask(const std::string& text);

KLB_HD KLB_INLINE bool network_policy_compatible(
    const NetworkObjectProfile& object,
    const NetworkStationGpu& station,
    std::uint32_t route_sector) {
    const bool orbit_ok = (object.orbit_class & station.orbit_mask) != 0u;
    const bool service_ok = (object.service_mask & station.service_mask) != 0u;
    const bool route_ok = route_sector < 32u &&
        (station.route_mask & (std::uint32_t{1} << route_sector)) != 0u;
    return orbit_ok && service_ok && route_ok;
}

KLB_HD KLB_INLINE std::uint32_t network_event_lineage(
    std::uint32_t base_lineage,
    std::uint32_t station_id,
    std::uint32_t event_type) {
    return mix32(base_lineage ^ mix32(station_id * 0x85ebca6bu) ^
                 event_type * 0x9e3779b9u);
}

} // namespace klb
