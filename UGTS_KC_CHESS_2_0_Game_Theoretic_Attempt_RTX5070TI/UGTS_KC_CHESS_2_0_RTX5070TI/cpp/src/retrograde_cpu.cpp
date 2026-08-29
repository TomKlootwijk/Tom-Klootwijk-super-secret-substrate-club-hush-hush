#include "ugts_chess2/retrograde.hpp"

#include <algorithm>
#include <stdexcept>

namespace ugts::chess2 {

const char* wdl_name(Wdl value) noexcept {
    switch (value) {
        case Wdl::Unknown: return "unknown";
        case Wdl::Win: return "win";
        case Wdl::Draw: return "draw";
        case Wdl::Loss: return "loss";
        case Wdl::Invalid: return "invalid";
    }
    return "invalid";
}

namespace {
void validate_graph(const RetroGraph& graph) {
    if (graph.offsets.size() != graph.initial.size() + 1) throw std::invalid_argument("retrograde offsets must have node_count + 1 entries");
    if (graph.offsets.empty() || graph.offsets.front() != 0) throw std::invalid_argument("retrograde offsets must start at zero");
    if (graph.offsets.back() != graph.children.size()) throw std::invalid_argument("retrograde offsets do not cover the child array");
    for (std::size_t i = 1; i < graph.offsets.size(); ++i) if (graph.offsets[i] < graph.offsets[i - 1]) throw std::invalid_argument("retrograde offsets must be monotonic");
    for (auto child : graph.children) if (child >= graph.initial.size()) throw std::invalid_argument("retrograde child index out of range");
}
}  // namespace

RetroResult solve_retrograde_cpu(const RetroGraph& graph, bool close_unknown_as_draw) {
    validate_graph(graph);
    RetroResult result;
    result.outcomes = graph.initial;
    result.backend = "cpu-fixed-point";
    if (result.outcomes.empty()) return result;

    std::vector<Wdl> next = result.outcomes;
    bool changed = true;
    while (changed) {
        changed = false;
        next = result.outcomes;
        for (std::size_t node = 0; node < result.outcomes.size(); ++node) {
            if (result.outcomes[node] != Wdl::Unknown) continue;
            const auto begin = graph.offsets[node];
            const auto end = graph.offsets[node + 1];
            if (begin == end) continue;  // Terminal nodes must be seeded explicitly.
            bool any_child_loss = false;
            bool all_children_win = true;
            for (std::uint32_t e = begin; e < end; ++e) {
                const Wdl child = result.outcomes[graph.children[e]];
                if (child == Wdl::Loss) any_child_loss = true;
                if (child != Wdl::Win) all_children_win = false;
            }
            if (any_child_loss) {
                next[node] = Wdl::Win;
                changed = true;
            } else if (all_children_win) {
                next[node] = Wdl::Loss;
                changed = true;
            }
        }
        if (changed) {
            for (std::size_t i = 0; i < result.outcomes.size(); ++i) {
                if (result.outcomes[i] == Wdl::Unknown && next[i] != Wdl::Unknown) ++result.resolved_by_propagation;
            }
            result.outcomes.swap(next);
            ++result.iterations;
        }
    }
    if (close_unknown_as_draw) {
        for (auto& value : result.outcomes) {
            if (value == Wdl::Unknown) {
                value = Wdl::Draw;
                ++result.draws_after_fixpoint;
            }
        }
    }
    return result;
}

RetroGraph make_demo_graph() {
    RetroGraph graph;
    // 0 -> 1,2 ; 1 -> 3 ; 2 -> 4,5 ; 3 terminal LOSS ; 4 terminal DRAW ; 5 -> 6 ; 6 terminal WIN.
    graph.offsets = {0, 2, 3, 5, 5, 5, 6, 6};
    graph.children = {1, 2, 3, 4, 5, 6};
    graph.initial = {Wdl::Unknown, Wdl::Unknown, Wdl::Unknown, Wdl::Loss, Wdl::Draw, Wdl::Unknown, Wdl::Win};
    return graph;
}

}  // namespace ugts::chess2
