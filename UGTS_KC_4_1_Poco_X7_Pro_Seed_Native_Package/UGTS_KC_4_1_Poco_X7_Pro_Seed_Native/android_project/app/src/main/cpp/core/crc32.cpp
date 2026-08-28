#include "crc32.hpp"
namespace ugts41 {std::uint32_t crc32(std::span<const std::uint8_t> data){std::uint32_t crc=0xffffffffU;for(auto byte:data){crc^=byte;for(int bit=0;bit<8;++bit){auto mask=0U-(crc&1U);crc=(crc>>1U)^(0xedb88320U&mask);}}return ~crc;}}
