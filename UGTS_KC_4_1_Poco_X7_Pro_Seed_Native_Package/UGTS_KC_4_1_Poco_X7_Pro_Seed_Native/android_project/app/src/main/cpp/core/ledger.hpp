#pragma once
#include "types.hpp"
#include "verifier.hpp"
#include <array>
#include <cstdint>
#include <optional>
#include <unordered_map>
#include <vector>
namespace ugts41 {
struct MapNodeState{std::uint64_t id=0,spatial_key=0;float confidence=0,uncertainty=0;std::uint32_t evidence_count=0,tag_mask=0;std::array<std::int32_t,4>payload{};};
class SpatialLedger{
public:explicit SpatialLedger(ProposalVerifier verifier=ProposalVerifier{});std::optional<LedgerEvent>commit(const EventProposal&,VerificationDecision*decision=nullptr);void reset();
const std::vector<LedgerEvent>&events()const{return events_;}const std::unordered_map<std::uint64_t,MapNodeState>&nodes()const{return nodes_;}const std::unordered_map<std::uint64_t,RouteNode>&route_nodes()const{return route_nodes_;}const std::unordered_map<std::uint64_t,RouteEdge>&route_edges()const{return route_edges_;}const std::array<std::uint8_t,32>&state_hash()const{return state_hash_;}std::uint32_t rejected_count()const{return rejected_count_;}
private:void apply(const EventProposal&);ProposalVerifier verifier_;std::vector<LedgerEvent>events_;std::unordered_map<std::uint64_t,MapNodeState>nodes_;std::unordered_map<std::uint64_t,RouteNode>route_nodes_;std::unordered_map<std::uint64_t,RouteEdge>route_edges_;std::array<std::uint8_t,32>state_hash_{};std::uint32_t rejected_count_=0;
};
std::vector<std::uint8_t>encode_proposal_canonical(const EventProposal&);
}
