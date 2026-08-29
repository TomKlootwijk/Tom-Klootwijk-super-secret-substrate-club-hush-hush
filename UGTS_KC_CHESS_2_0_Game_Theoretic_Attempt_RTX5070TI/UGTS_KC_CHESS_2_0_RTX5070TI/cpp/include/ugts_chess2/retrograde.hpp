#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace ugts::chess2 {

enum class Wdl : std::uint8_t { Unknown = 0, Win = 1, Draw = 2, Loss = 3, Invalid = 4 };

struct RetroGraph {
    std::vector<std::uint32_t> offsets;
    std::vector<std::uint32_t> children;
    std::vector<Wdl> initial;
};

struct RetroResult {
    std::vector<Wdl> outcomes;
    std::uint32_t iterations = 0;
    std::uint64_t resolved_by_propagation = 0;
    std::uint64_t draws_after_fixpoint = 0;
    bool used_cuda = false;
    std::string backend;
};

[[nodiscard]] RetroResult solve_retrograde_cpu(const RetroGraph& graph, bool close_unknown_as_draw = true);
[[nodiscard]] RetroResult solve_retrograde(const RetroGraph& graph, bool prefer_cuda = true,
                                           bool close_unknown_as_draw = true);
[[nodiscard]] RetroGraph make_demo_graph();
[[nodiscard]] const char* wdl_name(Wdl value) noexcept;
[[nodiscard]] bool cuda_backend_compiled() noexcept;
[[nodiscard]] std::string cuda_device_summary();

}  // namespace ugts::chess2
