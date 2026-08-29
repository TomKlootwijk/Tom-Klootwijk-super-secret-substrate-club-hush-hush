#include "touch_router.hpp"

#include <array>
#include <cassert>
#include <cmath>
#include <iostream>
#include <span>

namespace {

template<std::size_t N>
kc::TouchUpdate send(
    kc::TouchRouter& router,kc::TouchAction action,std::int32_t changed,
    const std::array<kc::TouchPoint,N>& points
) {
    return router.handle({action,changed,std::span<const kc::TouchPoint>(points)});
}

void twoThumbDashKeepsMovementAndPulsesOnce() {
    kc::TouchRouter router;
    router.setViewport(1200.0f,600.0f,3.0f);
    send(router,kc::TouchAction::Down,7,std::array{kc::TouchPoint{7,100,300}});
    auto update=send(router,kc::TouchAction::Move,-1,std::array{kc::TouchPoint{7,172,300}});
    assert(std::abs(update.moveX-0.5f)<0.001f);

    send(router,kc::TouchAction::PointerDown,9,std::array{
        kc::TouchPoint{7,172,300},kc::TouchPoint{9,1000,300}
    });
    int dashPulses=0;
    update=send(router,kc::TouchAction::PointerUp,9,std::array{
        kc::TouchPoint{7,172,300},kc::TouchPoint{9,1000,300}
    });
    dashPulses+=update.dashPressed?1:0;
    assert(std::abs(update.moveX-0.5f)<0.001f);

    update=send(router,kc::TouchAction::Move,-1,std::array{kc::TouchPoint{7,172,300}});
    dashPulses+=update.dashPressed?1:0;
    assert(std::abs(update.moveX-0.5f)<0.001f);
    update=send(router,kc::TouchAction::Up,7,std::array{kc::TouchPoint{7,172,300}});
    dashPulses+=update.dashPressed?1:0;
    assert(dashPulses==1);
    assert(update.moveX==0.0f && !update.jumpPressed);
}

void reversedContactAndArrayOrderKeepsRoles() {
    kc::TouchRouter router;
    router.setViewport(1200.0f,600.0f,2.0f);
    send(router,kc::TouchAction::Down,20,std::array{kc::TouchPoint{20,1000,300}});
    // The movement pointer is added second and appears first in Android's
    // pointer array. Stable IDs, not array indices, must decide each role.
    send(router,kc::TouchAction::PointerDown,3,std::array{
        kc::TouchPoint{3,100,300},kc::TouchPoint{20,1000,300}
    });
    auto update=send(router,kc::TouchAction::Move,-1,std::array{
        kc::TouchPoint{3,160,300},kc::TouchPoint{20,1012,306}
    });
    assert(update.moveX>0.4f);
    assert(update.lookDeltaX==12.0f && update.lookDeltaY==6.0f);

    update=send(router,kc::TouchAction::PointerUp,20,std::array{
        kc::TouchPoint{20,1012,306},kc::TouchPoint{3,160,300}
    });
    assert(update.dashPressed);
    assert(update.moveX>0.4f);
    update=send(router,kc::TouchAction::Move,-1,std::array{kc::TouchPoint{3,200,300}});
    assert(update.moveX>0.69f && !update.dashPressed);
}

void cancelClearsEveryRoleWithoutActions() {
    kc::TouchRouter router;
    router.setViewport(1000.0f,500.0f,1.0f);
    send(router,kc::TouchAction::Down,1,std::array{kc::TouchPoint{1,100,250}});
    send(router,kc::TouchAction::Move,-1,std::array{kc::TouchPoint{1,180,250}});
    const auto cancelled=send(router,kc::TouchAction::Cancel,-1,std::array<kc::TouchPoint,0>{});
    assert(cancelled.cancelled);
    assert(cancelled.moveX==0.0f && cancelled.moveZ==0.0f);
    assert(!cancelled.jumpPressed && !cancelled.dashPressed);
    const auto stale=send(router,kc::TouchAction::Move,-1,std::array{kc::TouchPoint{1,240,250}});
    assert(stale.moveX==0.0f && stale.lookDeltaX==0.0f);
}

void dragOutAndBackIsNotATap() {
    kc::TouchRouter router;
    router.setViewport(1200.0f,600.0f,3.0f);
    send(router,kc::TouchAction::Down,4,std::array{kc::TouchPoint{4,1000,300}});
    send(router,kc::TouchAction::Move,-1,std::array{kc::TouchPoint{4,1080,300}});
    send(router,kc::TouchAction::Move,-1,std::array{kc::TouchPoint{4,1000,300}});
    const auto update=send(router,kc::TouchAction::Up,4,std::array{kc::TouchPoint{4,1000,300}});
    assert(!update.dashPressed);
}

void tapJumpAndPinchRemainAvailable() {
    kc::TouchRouter router;
    router.setViewport(1200.0f,600.0f,2.0f);
    send(router,kc::TouchAction::Down,1,std::array{kc::TouchPoint{1,100,300}});
    auto update=send(router,kc::TouchAction::Up,1,std::array{kc::TouchPoint{1,100,300}});
    assert(update.jumpPressed);

    send(router,kc::TouchAction::Down,1,std::array{kc::TouchPoint{1,100,300}});
    send(router,kc::TouchAction::PointerDown,2,std::array{
        kc::TouchPoint{1,100,300},kc::TouchPoint{2,900,300}
    });
    update=send(router,kc::TouchAction::Move,-1,std::array{
        kc::TouchPoint{1,120,300},kc::TouchPoint{2,930,300}
    });
    assert(std::abs(update.zoomDelta-10.0f)<0.001f);
    assert(update.lookDeltaX==30.0f);
    assert(update.moveX>0.13f);
}

} // namespace

int main() {
    twoThumbDashKeepsMovementAndPulsesOnce();
    reversedContactAndArrayOrderKeepsRoles();
    cancelClearsEveryRoleWithoutActions();
    dragOutAndBackIsNotATap();
    tapJumpAndPinchRemainAvailable();
    std::cout << "PASS touch router pointer-ID gestures\n";
    return 0;
}
