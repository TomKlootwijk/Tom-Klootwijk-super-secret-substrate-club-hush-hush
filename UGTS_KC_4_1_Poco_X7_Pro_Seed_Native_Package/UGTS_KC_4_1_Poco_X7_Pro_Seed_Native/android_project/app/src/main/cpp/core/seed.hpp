#pragma once
#include <cstdint>
#include <string_view>
namespace ugts41 {
std::uint64_t splitmix64(std::uint64_t value);
std::uint64_t hash64(std::string_view text,std::uint64_t seed=0xcbf29ce484222325ULL);
std::uint64_t combine_seed(std::uint64_t seed,std::uint64_t value);
std::uint64_t stable_id(std::uint64_t session_seed,std::uint64_t namespace_id,std::uint64_t address);
float seed_unit_float(std::uint64_t value);
std::uint32_t seed_bounded(std::uint64_t value,std::uint32_t bound);
}
