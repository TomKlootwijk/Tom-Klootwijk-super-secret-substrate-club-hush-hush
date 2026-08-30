#include "body_physics.hpp"
#include "graph_vm.hpp"

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace {

void check(bool condition,const std::string& message) {
    if (!condition) throw std::runtime_error(message);
}

void near(float actual,float expected,float tolerance,const std::string& label) {
    if (!std::isfinite(actual) || std::abs(actual-expected)>tolerance)
        throw std::runtime_error(label+" mismatch");
}

std::vector<std::uint8_t> readBytes(const char* path) {
    std::ifstream stream(path,std::ios::binary);
    if (!stream) throw std::runtime_error(std::string("could not read ")+path);
    std::vector<std::uint8_t> bytes;
    for (char value=0;stream.get(value);) {
        bytes.push_back(static_cast<std::uint8_t>(
            static_cast<unsigned char>(value)
        ));
    }
    return bytes;
}

kc::NodeData sphere(
    std::string id,kc::Vec3 position,kc::Vec3 velocity,
    bool dynamic,float mass,float restitution,float radius=1.0f
) {
    kc::NodeData node;
    node.id=std::move(id);
    node.translation=position;
    node.velocity=velocity;
    node.dynamic=dynamic;
    node.mass=mass;
    node.restitution=restitution;
    node.collider.type=1;
    node.collider.radius=radius;
    return node;
}

void sixHundredStepUntaggedCrateTest() {
    kc::NodeData player;
    player.id="player";
    player.tagMask=kc::TagPlayer;
    player.dynamic=true;
    player.translation={4.0f,5.0f,6.0f};
    player.velocity={7.0f,8.0f,9.0f};

    kc::NodeData crate;
    crate.id="untagged_crate";
    crate.dynamic=true;
    crate.mass=2.0f;
    crate.restitution=0.35f;
    crate.translation={0.0f,4.0f,0.0f};
    // Equivalent to one desktop Apply Force [3, 0] on a mass-two body.
    crate.velocity={1.5f,0.0f,0.0f};
    crate.collider.type=2;
    crate.collider.halfExtents={0.5f,0.5f,0.5f};
    check(crate.tagMask==0,"acceptance crate unexpectedly has a gameplay tag");

    std::vector<kc::NodeData> nodes{player,crate};
    constexpr float dt=1.0f/120.0f;
    for (int step=0;step<600;++step) {
        kc::integrateDynamicBodies(nodes,{0.0f,-9.81f,0.0f},dt,0);
        kc::constrainDynamicBodies(
            nodes,0.0f,{-20.0f,-8.0f,-20.0f},{20.0f,28.0f,20.0f},0
        );
        check(kc::resolveDynamicBodyPairs(nodes).empty(),"isolated crate made a body contact");
    }

    near(nodes[1].translation.x,7.5f,5.0e-4f,"600-step crate x");
    near(nodes[1].translation.y,0.5f,1.0e-5f,"600-step crate floor height");
    near(nodes[1].translation.z,0.0f,1.0e-6f,"600-step crate z");
    near(nodes[1].velocity.x,1.5f,1.0e-6f,"600-step crate horizontal velocity");
    near(nodes[1].velocity.y,0.0f,1.0e-6f,"600-step crate vertical velocity");
    near(nodes[0].translation.x,4.0f,1.0e-6f,"excluded Player translation");
    near(nodes[0].velocity.y,8.0f,1.0e-6f,"excluded Player velocity");
}

void staticDynamicContactTest() {
    kc::NodeData dynamic=sphere(
        "z_dynamic",{1.0f,2.0f,0.0f},{-2.0f,0.0f,0.0f},true,2.0f,0.6f,0.5f
    );
    kc::NodeData fixed;
    fixed.id="a_static";
    fixed.translation={0.0f,2.0f,0.0f};
    fixed.dynamic=false;
    fixed.mass=4.0f;
    fixed.restitution=0.25f;
    fixed.collider.type=2;
    fixed.collider.halfExtents={0.5f,0.5f,0.5f};
    // Reverse vector order to prove pairs are resolved by stable node id.
    std::vector<kc::NodeData> nodes{dynamic,fixed};

    const auto contacts=kc::resolveDynamicBodyPairs(nodes);
    check(contacts.size()==1,"static/dynamic contact count");
    check(
        contacts[0].firstNode==1 && contacts[0].secondNode==0,
        "static/dynamic contact order"
    );
    near(contacts[0].penetration,0.3660254f,1.0e-5f,"static/dynamic penetration");
    near(nodes[1].translation.x,0.0f,1.0e-6f,"static body translation");
    near(nodes[1].velocity.x,0.0f,1.0e-6f,"static body velocity");
    near(nodes[0].translation.x,1.3660254f,1.0e-5f,"dynamic body separation");
    near(nodes[0].velocity.x,0.5f,1.0e-5f,"static/dynamic restitution");
}

void dynamicDynamicContactTest() {
    auto right=sphere(
        "z_dynamic",{1.5f,2.0f,0.0f},{-1.0f,0.0f,0.0f},true,1.0f,0.8f
    );
    auto left=sphere(
        "a_dynamic",{0.0f,2.0f,0.0f},{1.0f,0.0f,0.0f},true,1.0f,0.5f
    );
    std::vector<kc::NodeData> nodes{right,left};

    const auto contacts=kc::resolveDynamicBodyPairs(nodes);
    check(contacts.size()==1,"dynamic/dynamic contact count");
    check(
        contacts[0].firstNode==1 && contacts[0].secondNode==0,
        "dynamic/dynamic contact order"
    );
    near(contacts[0].penetration,0.5f,1.0e-6f,"dynamic/dynamic penetration");
    near(nodes[1].translation.x,-0.25f,1.0e-6f,"left separation");
    near(nodes[0].translation.x,1.75f,1.0e-6f,"right separation");
    near(nodes[1].velocity.x,-0.5f,1.0e-6f,"left impulse");
    near(nodes[0].velocity.x,0.5f,1.0e-6f,"right impulse");
}

void nonSolidBodiesTest() {
    auto dynamic=sphere(
        "dynamic",{0.0f,1.0f,0.0f},{1.0f,0.0f,0.0f},true,1.0f,0.5f
    );
    auto sensor=sphere(
        "sensor",{0.0f,1.0f,0.0f},{0.0f,0.0f,0.0f},false,1.0f,0.0f
    );
    sensor.collider.sensor=true;
    auto inactive=sphere(
        "inactive",{0.0f,1.0f,0.0f},{0.0f,0.0f,0.0f},false,1.0f,0.0f
    );
    inactive.active=false;
    std::vector<kc::NodeData> nodes{dynamic,sensor,inactive};
    check(kc::resolveDynamicBodyPairs(nodes).empty(),"sensor or inactive body resolved");
    near(nodes[0].translation.x,0.0f,1.0e-6f,"non-solid contact moved dynamic body");
    near(nodes[0].velocity.x,1.0f,1.0e-6f,"non-solid contact changed velocity");
}

void authoredCrateGraphParityTest(const char* scenePath,const char* graphPath) {
    const auto scene=kc::parseScenePack(readBytes(scenePath));
    auto nodes=scene.nodes;
    kc::GraphVm graph;
    graph.load(readBytes(graphPath),nodes.size());
    graph.ready(nodes);
    check(graph.issues().empty(),"authored crate Ready graph reported an issue");

    std::size_t playerIndex=kc::NoBodyExclusion;
    std::size_t crateIndex=kc::NoBodyExclusion;
    for (std::size_t index=0;index<nodes.size();++index) {
        if ((nodes[index].tagMask&kc::TagPlayer)!=0) playerIndex=index;
        if (nodes[index].id=="crate") crateIndex=index;
    }
    check(playerIndex!=kc::NoBodyExclusion,"authored project has no Player");
    check(crateIndex!=kc::NoBodyExclusion,"authored project has no crate");
    check(nodes[crateIndex].tagMask==0,"authored crate is not untagged");
    near(scene.fixedDt,1.0f/64.0f,0.0f,"authored fixed step");
    near(nodes[crateIndex].velocity.x,1.0f,1.0e-6f,"Ready Apply Force velocity");
    const auto playerStart=nodes[playerIndex].translation;

    struct CrateCheckpoint {
        std::uint64_t tick;
        std::uint32_t xBits;
    };
    constexpr std::array<CrateCheckpoint,7> checkpoints{{
        {0,0xc1000000u},
        {1,0xc0ff8000u},
        {64,0xc0e00000u},
        {128,0xc0c00000u},
        {256,0xc0800000u},
        {512,0x00000000u},
        {600,0x3fb00000u},
    }};
    std::size_t checkpointIndex=0;
    const auto checkCheckpoint=[&](std::uint64_t tick) {
        if (checkpointIndex>=checkpoints.size() ||
            checkpoints[checkpointIndex].tick!=tick) {
            return;
        }
        const auto& crate=nodes[crateIndex];
        const auto label="authored crate checkpoint "+std::to_string(tick);
        check(
            std::bit_cast<std::uint32_t>(crate.translation.x)==
                checkpoints[checkpointIndex].xBits,
            label+" x bits"
        );
        check(
            std::bit_cast<std::uint32_t>(crate.translation.y)==0x3f000000u &&
                std::bit_cast<std::uint32_t>(crate.translation.z)==0x00000000u,
            label+" yz bits"
        );
        check(
            std::bit_cast<std::uint32_t>(crate.velocity.x)==0x3f800000u &&
                std::bit_cast<std::uint32_t>(crate.velocity.y)==0x00000000u &&
                std::bit_cast<std::uint32_t>(crate.velocity.z)==0x00000000u,
            label+" velocity bits"
        );
        ++checkpointIndex;
    };
    checkCheckpoint(0);

    const kc::GraphInputFrame input{};
    for (std::uint64_t tick=0;tick<600;++tick) {
        graph.tick(scene.fixedDt,tick,input,nodes);
        check(graph.issues().empty(),"authored crate Tick graph reported an issue");
        kc::integrateDynamicBodies(
            nodes,scene.gravity,scene.fixedDt,playerIndex
        );
        kc::constrainDynamicBodies(
            nodes,scene.floorY,scene.boundsMin,scene.boundsMax,playerIndex
        );
        check(
            kc::resolveDynamicBodyPairs(nodes).empty(),
            "authored crate unexpectedly made contact before its golden"
        );
        graph.finishStep(scene.fixedDt,tick,input,nodes);
        check(graph.issues().empty(),"authored crate finish step reported an issue");
        checkCheckpoint(tick+1);
    }

    check(checkpointIndex==checkpoints.size(),"authored checkpoints were not all visited");

    near(nodes[crateIndex].translation.x,1.375f,0.0f,"authored 600-tick crate x");
    near(nodes[crateIndex].translation.y,0.5f,0.0f,"authored crate y");
    near(nodes[crateIndex].velocity.x,1.0f,0.0f,"authored crate velocity");
    near(nodes[playerIndex].translation.x,playerStart.x,0.0f,"authored Player x");
    near(nodes[playerIndex].translation.y,playerStart.y,0.0f,"authored Player y");
    near(nodes[playerIndex].translation.z,playerStart.z,0.0f,"authored Player z");
}

void representativeGameplaySensorTest(const char* scenePath) {
    const auto scene=kc::parseScenePack(readBytes(scenePath));
    const auto player=std::find_if(
        scene.nodes.begin(),scene.nodes.end(),
        [](const kc::NodeData& node) {
            return node.alive && node.active && (node.tagMask&kc::TagPlayer)!=0;
        }
    );
    check(player!=scene.nodes.end(),"representative project has no Player");
    constexpr std::uint32_t GameplayMask=
        kc::TagCollectible|kc::TagHazard|kc::TagGoal;
    std::uint32_t seenMask=0;
    for (const auto& target:scene.nodes) {
        const auto targetMask=target.tagMask&GameplayMask;
        if (!target.active || !target.alive || targetMask==0) continue;
        check(target.collider.sensor,"representative gameplay target is not a sensor");
        auto overlappedPlayer=*player;
        auto overlappedTarget=target;
        overlappedPlayer.translation=overlappedTarget.translation;
        const auto start=overlappedPlayer.translation;
        std::vector<kc::NodeData> overlap{overlappedPlayer,overlappedTarget};
        check(
            kc::resolveDynamicBodyPairs(overlap).empty(),
            "gameplay sensor was consumed by solid body resolution"
        );
        near(overlap[0].translation.x,start.x,0.0f,"gameplay overlap Player x");
        near(overlap[0].translation.y,start.y,0.0f,"gameplay overlap Player y");
        near(overlap[0].translation.z,start.z,0.0f,"gameplay overlap Player z");
        check(
            length(overlap[1].translation-overlap[0].translation)<=
                kc::bodyBoundingRadius(overlap[0])+
                kc::bodyBoundingRadius(overlap[1]),
            "gameplay tag distance check no longer overlaps"
        );
        seenMask|=targetMask;
    }
    check(seenMask==GameplayMask,"representative project lacks a gameplay tag class");
}

} // namespace

int main(int argc,char** argv) {
    try {
        check(argc==4,"expected crate KC3D/KCVG and gameplay KC3D pack paths");
        sixHundredStepUntaggedCrateTest();
        staticDynamicContactTest();
        dynamicDynamicContactTest();
        nonSolidBodiesTest();
        authoredCrateGraphParityTest(argv[1],argv[2]);
        representativeGameplaySensorTest(argv[3]);
        std::cout<<"PASS generic dynamic body physics\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr<<"FAIL generic dynamic body physics: "<<error.what()<<'\n';
        return 1;
    }
}
