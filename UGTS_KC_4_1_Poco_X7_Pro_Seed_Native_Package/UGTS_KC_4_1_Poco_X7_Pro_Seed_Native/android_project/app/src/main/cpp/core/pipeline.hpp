#pragma once
#include "ledger.hpp"
#include "types.hpp"
#include <cstdint>
#include <vector>
namespace ugts41 {
struct ObservationAdapterPolicy{std::uint16_t feature_proposals_per_keyframe=24;float confidence_floor=.35f,relative_uncertainty=1.0f;};
std::vector<EventProposal>proposals_from_frame(const FrameObservation&,std::uint64_t session_seed,ObservationAdapterPolicy policy={});
struct DemoWorld{std::vector<RouteNode>nodes;std::vector<RouteEdge>edges;};
DemoWorld generate_demo_world(std::uint64_t seed,std::uint32_t node_count=12);
std::vector<EventProposal>demo_world_proposals(const DemoWorld&,std::uint64_t session_seed,std::uint64_t timestamp_ns,bool metric_ready=true);
}
