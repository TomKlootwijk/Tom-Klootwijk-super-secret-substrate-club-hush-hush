#include "seed.hpp"
namespace ugts41 {
std::uint64_t splitmix64(std::uint64_t v){v+=0x9e3779b97f4a7c15ULL;v=(v^(v>>30U))*0xbf58476d1ce4e5b9ULL;v=(v^(v>>27U))*0x94d049bb133111ebULL;return v^(v>>31U);}
std::uint64_t hash64(std::string_view text,std::uint64_t seed){std::uint64_t h=seed;for(unsigned char c:text){h^=c;h*=0x100000001b3ULL;}return splitmix64(h^text.size());}
std::uint64_t combine_seed(std::uint64_t seed,std::uint64_t value){return splitmix64(seed^(splitmix64(value)+0x9e3779b97f4a7c15ULL+(seed<<6U)+(seed>>2U)));}
std::uint64_t stable_id(std::uint64_t session_seed,std::uint64_t ns,std::uint64_t address){return combine_seed(combine_seed(session_seed,ns),address);}
float seed_unit_float(std::uint64_t value){const auto upper=static_cast<std::uint32_t>(splitmix64(value)>>40U);return static_cast<float>(upper)/16777216.0f;}
std::uint32_t seed_bounded(std::uint64_t value,std::uint32_t bound){if(!bound)return 0;const std::uint64_t product=static_cast<std::uint64_t>(static_cast<std::uint32_t>(splitmix64(value)))*bound;return static_cast<std::uint32_t>(product>>32U);}
}
