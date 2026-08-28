#pragma once
#include <cstddef>
#include <cstdint>
#include <span>
#include <vector>
namespace ugts41 {
void append_varuint(std::vector<std::uint8_t>& out,std::uint64_t value);
void append_varint(std::vector<std::uint8_t>& out,std::int64_t value);
bool read_varuint(std::span<const std::uint8_t> data,std::size_t& offset,std::uint64_t& value);
bool read_varint(std::span<const std::uint8_t> data,std::size_t& offset,std::int64_t& value);
}
