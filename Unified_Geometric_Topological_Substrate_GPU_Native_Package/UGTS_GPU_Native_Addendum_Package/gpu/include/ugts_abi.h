#pragma once
#include <cstdint>

#define UGTS_ABI_MAJOR 1u
#define UGTS_ABI_MINOR 1u
#define UGTS_LOCAL_SIZE_X 256u

namespace ugts {

struct alignas(16) G64State {
    float position_time[4];   // x,y,z,t
    float axis_radius[4];     // ax,ay,az,R
    float phase_guard[4];     // cone_cos, phase, guard_epsilon, confidence_floor
    std::uint32_t meta[4];    // sheet, orientation, compatibility_mask, lineage_seed
};

struct alignas(16) E32Event {
    std::uint32_t scalar_bits[4];   // float bits: sdf, guard, confidence, event_time
    std::uint32_t topology_bits[4]; // verified, route, lineage_hash, state_flags
};

struct alignas(16) G32State {
    std::uint32_t words[8]; // six FP16 pairs, packed topology, lineage seed
};

struct alignas(16) E16Event {
    std::uint32_t words[4]; // sdf bits, packed guard/confidence, flags, lineage hash
};

static_assert(sizeof(G64State) == 64);
static_assert(sizeof(E32Event) == 32);
static_assert(sizeof(G32State) == 32);
static_assert(sizeof(E16Event) == 16);

constexpr std::uint32_t META_SHEET_MASK = 0x000000ffu;
constexpr std::uint32_t META_ORIENTATION_BIT = 1u << 8;
constexpr std::uint32_t META_COMPAT_SHIFT = 9u;
constexpr std::uint32_t META_COMPAT_MASK = 0x01fffe00u;

constexpr std::uint32_t EVENT_VERIFIED_BIT = 1u << 0;
constexpr std::uint32_t EVENT_ROUTE_BIT = 1u << 1;
constexpr std::uint32_t EVENT_SHEET_SHIFT = 2u;
constexpr std::uint32_t EVENT_IN_SUPPORT_BIT = 1u << 10;
constexpr std::uint32_t EVENT_COMPATIBLE_BIT = 1u << 11;

} // namespace ugts
