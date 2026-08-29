#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <span>

namespace kc {

enum class TouchAction : std::uint8_t {
    Down,
    PointerDown,
    Move,
    PointerUp,
    Up,
    Cancel,
};

struct TouchPoint {
    std::int32_t id=-1;
    float x=0.0f;
    float y=0.0f;
};

struct TouchEvent {
    TouchAction action=TouchAction::Cancel;
    std::int32_t changedId=-1;
    std::span<const TouchPoint> points{};
};

struct TouchUpdate {
    float moveX=0.0f;
    float moveZ=0.0f;
    float lookDeltaX=0.0f;
    float lookDeltaY=0.0f;
    float zoomDelta=0.0f;
    bool jumpPressed=false;
    bool dashPressed=false;
    bool cancelled=false;
};

// Platform-neutral gesture state used by NativeActivity and host tests.  A
// pointer keeps the role assigned at contact time, so Android pointer-array
// reordering cannot turn a movement thumb into a camera thumb (or vice versa).
class TouchRouter {
public:
    static constexpr std::size_t MaxPointers=32;

    void setViewport(float width,float height,float densityScale=1.0f);
    TouchUpdate handle(const TouchEvent& event);

private:
    enum class Role : std::uint8_t { None, Move, Look };
    struct PointerState {
        std::int32_t id=-1;
        float startX=0.0f,startY=0.0f;
        float x=0.0f,y=0.0f;
        float maxDistanceSquared=0.0f;
        Role role=Role::None;
        bool active=false;
    };

    PointerState* find(std::int32_t id);
    const PointerState* find(std::int32_t id) const;
    PointerState* allocate(std::int32_t id);
    const TouchPoint* eventPoint(const TouchEvent& event,std::int32_t id) const;
    void updatePoint(PointerState& state,const TouchPoint& point);
    void updateMovement();
    float currentSpacing() const;
    std::size_t activeCount() const;
    void reset();
    TouchUpdate snapshot() const;

    std::array<PointerState,MaxPointers> pointers_{};
    std::int32_t movePointer_=-1;
    std::int32_t lookPointer_=-1;
    float width_=1.0f,height_=1.0f,densityScale_=1.0f;
    float movementRadius_=80.0f,tapSlop_=32.0f;
    float moveX_=0.0f,moveZ_=0.0f;
    float pinchSpacing_=-1.0f;
};

} // namespace kc
