#include "spatial_keys.hpp"
#include <algorithm>
#include <stdexcept>
namespace ugts41 { namespace {constexpr std::uint32_t M20=(1U<<20)-1,M18=(1U<<18)-1,M14=(1U<<14)-1,M12=(1U<<12)-1;constexpr std::int32_t B=1<<19;std::uint32_t spread(std::uint16_t v){std::uint32_t x=v;x=(x|(x<<8))&0x00ff00ffU;x=(x|(x<<4))&0x0f0f0f0fU;x=(x|(x<<2))&0x33333333U;x=(x|(x<<1))&0x55555555U;return x;}}
std::uint64_t pack_voxel_key(const VoxelKeyFields&f){if(f.level>15)throw std::out_of_range("voxel level");auto e=[](std::int32_t v){if(v<-B||v>=B)throw std::out_of_range("voxel coordinate");return std::uint32_t(v+B);};return(std::uint64_t(f.level)<<60)|(std::uint64_t(e(f.x))<<40)|(std::uint64_t(e(f.y))<<20)|e(f.z);}
VoxelKeyFields unpack_voxel_key(std::uint64_t k){return{std::uint8_t((k>>60)&15),std::int32_t((k>>40)&M20)-B,std::int32_t((k>>20)&M20)-B,std::int32_t(k&M20)-B};}
std::uint64_t pack_ray_key(const RayKeyFields&f){if(f.log_depth>M20||f.azimuth>M18||f.elevation>M14||f.time>M12)throw std::out_of_range("ray field");return(std::uint64_t(f.log_depth)<<44)|(std::uint64_t(f.azimuth)<<26)|(std::uint64_t(f.elevation)<<12)|f.time;}
RayKeyFields unpack_ray_key(std::uint64_t k){return{std::uint32_t((k>>44)&M20),std::uint32_t((k>>26)&M18),std::uint16_t((k>>12)&M14),std::uint16_t(k&M12)};}
std::uint64_t ray_key_from_pixel(std::uint16_t x,std::uint16_t y,std::uint16_t w,std::uint16_t h,std::uint32_t frame,std::uint32_t depth){auto sw=std::max<std::uint32_t>(2,w),sh=std::max<std::uint32_t>(2,h);auto az=std::min<std::uint32_t>(M18,std::uint64_t(x)*M18/(sw-1));auto el=std::min<std::uint32_t>(M14,std::uint64_t(y)*M14/(sh-1));return pack_ray_key({std::min(depth,M20),az,std::uint16_t(el),std::uint16_t(frame&M12)});}
std::uint32_t morton2d_16(std::uint16_t x,std::uint16_t y){return spread(x)|(spread(y)<<1);}
}
