#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <span>
#include <string>
namespace ugts41 {
class Sha256 {
public: Sha256(); void update(std::span<const std::uint8_t> data); void update(const void* data,std::size_t size); std::array<std::uint8_t,32> finish();
private: void transform(const std::uint8_t block[64]); std::array<std::uint32_t,8> state_{}; std::array<std::uint8_t,64> buffer_{}; std::uint64_t total_bytes_=0; std::size_t buffer_size_=0; bool finished_=false;
};
std::array<std::uint8_t,32> sha256(std::span<const std::uint8_t> data);
std::string hex_bytes(std::span<const std::uint8_t> data);
std::string hex_digest(std::span<const std::uint8_t> data);
}
