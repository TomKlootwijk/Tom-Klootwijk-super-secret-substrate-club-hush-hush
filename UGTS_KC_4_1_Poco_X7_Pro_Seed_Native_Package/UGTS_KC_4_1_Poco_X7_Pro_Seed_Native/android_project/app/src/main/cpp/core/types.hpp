#pragma once

#include <array>
#include <cstdint>
#include <vector>

namespace ugts41 {

struct Vec3f { float x=0.0f, y=0.0f, z=0.0f; };
struct Quatf { float x=0.0f, y=0.0f, z=0.0f, w=1.0f; };

struct ImuSample {
    std::uint64_t timestamp_ns=0;
    Vec3f acceleration{};
    Vec3f angular_velocity{};
    Quatf orientation{};
};

struct FeaturePoint {
    std::uint16_t x=0, y=0;
    std::uint8_t intensity=0, gradient=0;
    std::uint16_t score=0;
    std::uint64_t ray_key=0;
};

struct FrameObservation {
    std::uint32_t frame_index=0;
    std::uint64_t timestamp_ns=0;
    std::uint16_t width=0, height=0;
    Quatf orientation{};
    Vec3f acceleration{};
    Vec3f angular_velocity{};
    std::uint8_t mean_luma=0, deviation_luma=0;
    std::uint64_t luma_signature=0;
    std::vector<FeaturePoint> features;
};

enum class EventKind : std::uint8_t {
    SessionStart=1, FeatureRay=2, Keyframe=3, ManualAnchor=4,
    RouteNode=5, RouteEdge=6, StateChange=7, Checkpoint=8,
    SessionEnd=9, ThermalPolicy=10
};

enum class GuardStatus : std::uint8_t {
    Rejected=0, Confirmed=1, Crossing=2, Touch=3, Tangency=4, Unknown=5
};

struct EventProposal {
    std::uint64_t proposal_id=0;
    EventKind kind=EventKind::FeatureRay;
    std::uint64_t timestamp_ns=0;
    std::uint64_t stable_id=0;
    std::uint64_t spatial_key=0;
    float confidence=0.0f;
    float numeric_error=0.0f;
    float uncertainty=0.0f;
    float relation_value=0.0f;
    float metric_a=0.0f;
    float metric_b=0.0f;
    GuardStatus guard=GuardStatus::Unknown;
    bool support_ok=false;
    bool compatibility_ok=false;
    bool metric_required=false;
    bool metric_ready=false;
    std::uint32_t tag_mask=0;
    std::array<std::int32_t,4> payload{};
};

struct VerificationDecision { bool accepted=false; std::uint32_t reason_mask=0; };

struct LedgerEvent {
    std::uint32_t sequence=0;
    EventProposal proposal{};
    std::array<std::uint8_t,32> pre_hash{};
    std::array<std::uint8_t,32> post_hash{};
};

struct RouteNode {
    std::uint64_t id=0;
    Vec3f position{};
    float uncertainty=0.0f;
    std::uint32_t flags=0;
};

struct RouteEdge {
    std::uint64_t id=0, from=0, to=0;
    float clearance_lower=0.0f;
    float slope_upper=0.0f;
    float confidence=0.0f;
    bool passable=false;
};

struct SessionStats {
    std::uint64_t session_seed=0, start_time_ns=0, end_time_ns=0;
    std::uint32_t frames_seen=0, keyframes_stored=0, proposals_seen=0;
    std::uint32_t events_committed=0, rejected_proposals=0;
    std::uint64_t raw_input_bytes=0, stored_bytes=0;
};

} // namespace ugts41
