#pragma once

#include "klb/core.hpp"

#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

namespace klb {

#pragma pack(push, 1)
struct FileHeaderDisk {
    char magic[8];
    std::uint32_t version;
    std::uint32_t header_bytes;
    std::uint64_t record_count;
    std::uint64_t padded_count;
    std::uint64_t word_count;
    std::uint64_t source_bytes;
    std::uint32_t record_bits;
    std::uint32_t tile_records;
    std::uint32_t grid_width;
    std::uint32_t flags;
    float center[3];
    float radius_scale;
    float log_k;
    float rms_error;
    float max_error;
    std::uint64_t payload_hash;
    std::uint8_t reserved[28];
};
#pragma pack(pop)

static_assert(sizeof(FileHeaderDisk) == 128, "KLB file header must stay 128 bytes");

struct PackedData {
    FileHeaderDisk header{};
    std::vector<std::uint32_t> words;
};

struct PackStats {
    std::uint64_t input_points{};
    std::uint64_t padded_points{};
    std::uint64_t source_bytes{};
    std::uint64_t payload_bytes{};
    std::uint64_t file_bytes{};
    double bytes_per_point{};
    double ratio_vs_float3{};
    double ratio_vs_source_file{};
    double rms_error{};
    double max_error{};
};

PackedData pack_points(
    const std::vector<Vec3>& points,
    std::uint64_t source_bytes,
    float log_k,
    PackStats* stats = nullptr);

// Sequence-oriented variant: preserves the caller's vertex order so the same
// point index can be tracked across multiple frames.
PackedData pack_points_ordered(
    const std::vector<Vec3>& points,
    std::uint64_t source_bytes,
    float log_k,
    PackStats* stats = nullptr);

std::vector<Vec3> unpack_points(const PackedData& packed, bool include_padding = false);
std::vector<std::uint64_t> unpack_logical_codes(const PackedData& packed);

void save_packed(const std::filesystem::path& path, const PackedData& packed);
PackedData load_packed(const std::filesystem::path& path);
PackStats inspect_packed(const PackedData& packed, std::uint64_t actual_file_bytes = 0);
DecodeParams decode_params_from_header(const FileHeaderDisk& header);

std::vector<Vec3> generate_lsystem_points(std::size_t count);

} // namespace klb

