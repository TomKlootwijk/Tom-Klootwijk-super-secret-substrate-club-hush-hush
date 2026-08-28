#pragma once
#include <cstdint>
namespace ugts41 {
struct VoxelKeyFields{std::uint8_t level=0;std::int32_t x=0,y=0,z=0;};
struct RayKeyFields{std::uint32_t log_depth=0,azimuth=0;std::uint16_t elevation=0,time=0;};
std::uint64_t pack_voxel_key(const VoxelKeyFields&);
VoxelKeyFields unpack_voxel_key(std::uint64_t);
std::uint64_t pack_ray_key(const RayKeyFields&);
RayKeyFields unpack_ray_key(std::uint64_t);
std::uint64_t ray_key_from_pixel(std::uint16_t x,std::uint16_t y,std::uint16_t width,std::uint16_t height,std::uint32_t frame_index,std::uint32_t log_depth=0);
std::uint32_t morton2d_16(std::uint16_t x,std::uint16_t y);
}
