#pragma once

#include "klb/core.hpp"

#include <filesystem>
#include <vector>

namespace klb {

std::vector<Vec3> read_ply_vertices(const std::filesystem::path& path);
void write_ply_vertices_ascii(const std::filesystem::path& path, const std::vector<Vec3>& points);

} // namespace klb

