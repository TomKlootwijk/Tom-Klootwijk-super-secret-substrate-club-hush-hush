#include "touch_router.hpp"

#include <algorithm>
#include <cmath>

namespace kc {

void TouchRouter::setViewport(float width,float height,float densityScale) {
    width_=std::isfinite(width) && width>0.0f?width:1.0f;
    height_=std::isfinite(height) && height>0.0f?height:1.0f;
    densityScale_=std::isfinite(densityScale) && densityScale>0.0f
        ?std::clamp(densityScale,0.75f,4.0f):1.0f;
    movementRadius_=std::max(80.0f,width_*0.12f);
    // Preserve the former 32-pixel floor while scaling the allowance on
    // high-density phone panels such as the Poco target.
    tapSlop_=std::max(32.0f,12.0f*densityScale_);
    updateMovement();
}

TouchRouter::PointerState* TouchRouter::find(std::int32_t id) {
    for (auto& pointer:pointers_) if (pointer.active && pointer.id==id) return &pointer;
    return nullptr;
}

const TouchRouter::PointerState* TouchRouter::find(std::int32_t id) const {
    for (const auto& pointer:pointers_) if (pointer.active && pointer.id==id) return &pointer;
    return nullptr;
}

TouchRouter::PointerState* TouchRouter::allocate(std::int32_t id) {
    if (auto* existing=find(id)) return existing;
    for (auto& pointer:pointers_) {
        if (!pointer.active) {
            pointer=PointerState{};
            pointer.id=id;
            pointer.active=true;
            return &pointer;
        }
    }
    return nullptr;
}

const TouchPoint* TouchRouter::eventPoint(const TouchEvent& event,std::int32_t id) const {
    for (const auto& point:event.points) if (point.id==id) return &point;
    return nullptr;
}

void TouchRouter::updatePoint(PointerState& state,const TouchPoint& point) {
    state.x=point.x;
    state.y=point.y;
    const float dx=state.x-state.startX,dy=state.y-state.startY;
    state.maxDistanceSquared=std::max(state.maxDistanceSquared,dx*dx+dy*dy);
}

void TouchRouter::updateMovement() {
    const auto* movement=find(movePointer_);
    if (!movement) {
        moveX_=moveZ_=0.0f;
        return;
    }
    moveX_=std::clamp((movement->x-movement->startX)/movementRadius_,-1.0f,1.0f);
    moveZ_=std::clamp((movement->y-movement->startY)/movementRadius_,-1.0f,1.0f);
}

std::size_t TouchRouter::activeCount() const {
    return static_cast<std::size_t>(std::count_if(
        pointers_.begin(),pointers_.end(),[](const PointerState& pointer){ return pointer.active; }
    ));
}

float TouchRouter::currentSpacing() const {
    const PointerState* first=nullptr;
    const PointerState* second=nullptr;
    for (const auto& pointer:pointers_) {
        if (!pointer.active) continue;
        if (!first) first=&pointer;
        else { second=&pointer; break; }
    }
    if (!first || !second) return -1.0f;
    return std::hypot(second->x-first->x,second->y-first->y);
}

void TouchRouter::reset() {
    for (auto& pointer:pointers_) pointer=PointerState{};
    movePointer_=lookPointer_=-1;
    moveX_=moveZ_=0.0f;
    pinchSpacing_=-1.0f;
}

TouchUpdate TouchRouter::snapshot() const {
    TouchUpdate result;
    result.moveX=moveX_;
    result.moveZ=moveZ_;
    return result;
}

TouchUpdate TouchRouter::handle(const TouchEvent& event) {
    if (event.action==TouchAction::Cancel) {
        reset();
        auto result=snapshot();
        result.cancelled=true;
        return result;
    }

    if (event.action==TouchAction::Down || event.action==TouchAction::PointerDown) {
        const auto* point=eventPoint(event,event.changedId);
        auto* state=point?allocate(event.changedId):nullptr;
        if (state && point) {
            state->startX=state->x=point->x;
            state->startY=state->y=point->y;
            if (point->x<width_*0.45f && movePointer_<0) {
                state->role=Role::Move;
                movePointer_=state->id;
            } else if (point->x>=width_*0.45f && lookPointer_<0) {
                state->role=Role::Look;
                lookPointer_=state->id;
            }
        }
        updateMovement();
        pinchSpacing_=activeCount()>=2?currentSpacing():-1.0f;
        return snapshot();
    }

    if (event.action==TouchAction::Move) {
        auto result=snapshot();
        for (const auto& point:event.points) {
            auto* state=find(point.id);
            if (!state) continue;
            const float previousX=state->x,previousY=state->y;
            updatePoint(*state,point);
            if (state->role==Role::Look) {
                result.lookDeltaX+=state->x-previousX;
                result.lookDeltaY+=state->y-previousY;
            }
        }
        updateMovement();
        result.moveX=moveX_;
        result.moveZ=moveZ_;
        const float spacing=currentSpacing();
        if (spacing>=0.0f) {
            if (pinchSpacing_>=0.0f) result.zoomDelta=spacing-pinchSpacing_;
            pinchSpacing_=spacing;
        } else pinchSpacing_=-1.0f;
        return result;
    }

    if (event.action==TouchAction::Up || event.action==TouchAction::PointerUp) {
        for (const auto& point:event.points) {
            if (auto* state=find(point.id)) updatePoint(*state,point);
        }
        auto result=snapshot();
        auto* state=find(event.changedId);
        if (state) {
            const bool tap=state->maxDistanceSquared<=tapSlop_*tapSlop_;
            if (state->role==Role::Move) {
                result.jumpPressed=tap;
                movePointer_=-1;
            } else if (state->role==Role::Look) {
                result.dashPressed=tap;
                lookPointer_=-1;
            }
            *state=PointerState{};
        }
        updateMovement();
        result.moveX=moveX_;
        result.moveZ=moveZ_;
        pinchSpacing_=activeCount()>=2?currentSpacing():-1.0f;
        return result;
    }

    return snapshot();
}

} // namespace kc
