#include "ugts_chess2/retrograde.hpp"

namespace ugts::chess2 {

bool cuda_backend_compiled() noexcept { return false; }
std::string cuda_device_summary() { return "CUDA backend not compiled; CPU oracle active"; }
RetroResult solve_retrograde(const RetroGraph& graph, bool /*prefer_cuda*/, bool close_unknown_as_draw) {
    return solve_retrograde_cpu(graph, close_unknown_as_draw);
}

}  // namespace ugts::chess2
