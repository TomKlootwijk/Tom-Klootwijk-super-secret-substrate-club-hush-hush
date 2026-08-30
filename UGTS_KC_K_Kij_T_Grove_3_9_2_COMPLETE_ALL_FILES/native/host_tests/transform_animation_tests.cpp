#include "transform_animation.hpp"
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

void appendU8(std::vector<std::uint8_t>& output,std::uint8_t value) {
    output.push_back(value);
}

void appendU16(std::vector<std::uint8_t>& output,std::uint16_t value) {
    output.push_back(static_cast<std::uint8_t>(value));
    output.push_back(static_cast<std::uint8_t>(value>>8));
}

void appendU32(std::vector<std::uint8_t>& output,std::uint32_t value) {
    for (unsigned shift:{0u,8u,16u,24u})
        output.push_back(static_cast<std::uint8_t>(value>>shift));
}

void appendU64(std::vector<std::uint8_t>& output,std::uint64_t value) {
    appendU32(output,static_cast<std::uint32_t>(value));
    appendU32(output,static_cast<std::uint32_t>(value>>32));
}

void appendF32(std::vector<std::uint8_t>& output,float value) {
    std::uint32_t bits=0; std::memcpy(&bits,&value,sizeof(bits)); appendU32(output,bits);
}

void writeU16(std::vector<std::uint8_t>& output,std::size_t offset,std::uint16_t value) {
    output.at(offset)=static_cast<std::uint8_t>(value);
    output.at(offset+1)=static_cast<std::uint8_t>(value>>8);
}

void writeU32(std::vector<std::uint8_t>& output,std::size_t offset,std::uint32_t value) {
    for (unsigned index=0;index<4;++index)
        output.at(offset+index)=static_cast<std::uint8_t>(value>>(index*8));
}

void writeF32(std::vector<std::uint8_t>& output,std::size_t offset,float value) {
    std::uint32_t bits=0; std::memcpy(&bits,&value,sizeof(bits)); writeU32(output,offset,bits);
}

void appendKey(
    std::vector<std::uint8_t>& output,std::uint16_t time,std::uint8_t easing,
    const std::uint16_t (&values)[10]
) {
    appendU16(output,time); appendU8(output,easing); appendU8(output,0);
    for (const auto value:values) appendU16(output,value);
}

std::vector<std::uint8_t> validPack() {
    std::vector<std::uint8_t> output;
    const char magic[8]={'K','C','A','N','3','9','2','\0'};
    output.insert(output.end(),magic,magic+8);
    appendU32(output,0x01020304u); appendU32(output,1u);
    appendU16(output,1u); appendU16(output,0u); appendU32(output,2u);
    appendU32(output,0u); appendF32(output,1.0f); appendU32(output,0u);
    appendU16(output,2u); appendU8(output,0u); appendU8(output,0u);
    constexpr std::uint16_t identity[10]={
        0x0000,0x0000,0x0000,
        0x3c00,0x0000,0x0000,0x0000,
        0x3c00,0x3c00,0x3c00,
    };
    // The negative representation of +90 degrees around Y exercises
    // shortest-hemisphere quaternion canonicalization.
    constexpr std::uint16_t destination[10]={
        0x4000,0x4400,0x4600,
        0xb9a8,0x0000,0xb9a8,0x0000,
        0x4000,0x3800,0x3e00,
    };
    appendKey(output,0u,0u,identity);
    appendKey(output,65535u,0u,destination);
    return output;
}

std::vector<std::uint8_t> validV2Pack() {
    struct AuthoredClip {
        std::uint64_t hash=0;
        std::uint16_t destinationX=0;
        bool autoplay=false;
    };
    std::vector<AuthoredClip> clips{
        {kc::animationClipHash("idle"),0x4000u,true},
        {kc::animationClipHash("jump"),0x4400u,false},
    };
    std::sort(clips.begin(),clips.end(),[](const auto& left,const auto& right) {
        return left.hash<right.hash;
    });

    std::vector<std::uint8_t> output;
    const char magic[8]={'K','C','A','N','3','9','2','\0'};
    output.insert(output.end(),magic,magic+8);
    appendU32(output,0x01020304u); appendU32(output,2u);
    appendU16(output,static_cast<std::uint16_t>(clips.size()));
    appendU16(output,0u); appendU32(output,4u);
    std::uint32_t firstKey=0;
    for (const auto& clip:clips) {
        appendU32(output,0u); appendU64(output,clip.hash); appendF32(output,1.0f);
        appendU32(output,firstKey); appendU16(output,2u);
        appendU8(output,0u); appendU8(output,clip.autoplay?1u:0u);
        firstKey+=2;
    }
    constexpr std::uint16_t identity[10]={
        0x0000,0x0000,0x0000,
        0x3c00,0x0000,0x0000,0x0000,
        0x3c00,0x3c00,0x3c00,
    };
    for (const auto& clip:clips) {
        const std::uint16_t destination[10]={
            clip.destinationX,0x0000,0x0000,
            0x3c00,0x0000,0x0000,0x0000,
            0x3c00,0x3c00,0x3c00,
        };
        appendKey(output,0u,0u,identity);
        appendKey(output,65535u,0u,destination);
    }
    return output;
}

std::vector<kc::NodeData> baseNodes() {
    kc::NodeData node;
    node.id="animated";
    node.translation={10.0f,20.0f,30.0f};
    node.rotation={1.0f,0.0f,0.0f,0.0f};
    node.scale={2.0f,3.0f,4.0f};
    return {node};
}

void check(bool condition,const std::string& message) {
    if (!condition) throw std::runtime_error(message);
}

void near(float actual,float expected,float tolerance,const std::string& label) {
    if (std::abs(actual-expected)>tolerance)
        throw std::runtime_error(label+" mismatch");
}

void expectFailure(
    const std::vector<std::uint8_t>& bytes,const std::vector<kc::NodeData>& nodes,
    const std::string& label
) {
    kc::TransformAnimations runtime;
    runtime.load(validPack(),baseNodes());
    try {
        runtime.load(bytes,nodes);
    } catch (const std::exception&) {
        check(runtime.bindingCount()==0&&runtime.keyCount()==0,label+" did not clear state");
        return;
    }
    throw std::runtime_error(label+" was accepted");
}

void playbackTest() {
    auto nodes=baseNodes(); kc::TransformAnimations runtime;
    runtime.load(validPack(),nodes);
    check(runtime.bindingCount()==1&&runtime.keyCount()==2,"valid KCAN counts");
    runtime.compose(nodes);
    near(nodes[0].translation.x,10.0f,1.0e-6f,"initial translation");
    near(nodes[0].rotation.w,1.0f,1.0e-6f,"initial rotation");
    near(nodes[0].scale.y,3.0f,1.0e-6f,"initial scale");

    runtime.tick(0.25f,nodes); runtime.tick(0.25f,nodes);
    near(nodes[0].translation.x,11.0f,1.0e-5f,"half translation x");
    near(nodes[0].translation.y,22.0f,1.0e-5f,"half translation y");
    near(nodes[0].translation.z,33.0f,1.0e-5f,"half translation z");
    near(nodes[0].rotation.w,0.92388f,2.0e-4f,"half rotation w");
    near(nodes[0].rotation.y,0.382683f,2.0e-4f,"half rotation y");
    near(nodes[0].scale.x,3.0f,1.0e-5f,"half scale x");
    near(nodes[0].scale.y,2.25f,1.0e-5f,"half scale y");
    near(nodes[0].scale.z,5.0f,1.0e-5f,"half scale z");

    runtime.tick(0.25f,nodes); runtime.tick(0.25f,nodes);
    near(nodes[0].translation.x,12.0f,1.0e-5f,"final translation");
    near(nodes[0].rotation.w,0.707107f,2.0e-4f,"final rotation w");
    near(nodes[0].rotation.y,0.707107f,2.0e-4f,"final rotation y");
    near(nodes[0].scale.y,1.5f,1.0e-5f,"final scale");
    runtime.tick(0.25f,nodes);
    near(nodes[0].translation.x,12.0f,1.0e-5f,"once mode hold");
    check(
        runtime.play(0,kc::animationClipHash("main"),true,nodes)==
            kc::AnimationControlResult::Ok,
        "KCAN v1 did not normalize to the main autoplay clip"
    );
    near(nodes[0].translation.x,10.0f,1.0e-5f,"v1 restart at time zero");
}

void multiClipControlTest() {
    auto nodes=baseNodes(); kc::TransformAnimations runtime;
    runtime.load(validV2Pack(),nodes);
    check(runtime.bindingCount()==1,"KCAN v2 controller count");
    check(runtime.clipCount()==2&&runtime.keyCount()==4,"KCAN v2 clip/key counts");
    runtime.compose(nodes);
    near(nodes[0].translation.x,10.0f,1.0e-6f,"v2 autoplay time zero");
    runtime.tick(0.25f,nodes); runtime.tick(0.25f,nodes);
    near(nodes[0].translation.x,11.0f,1.0e-5f,"v2 autoplay midpoint");

    check(
        runtime.play(0,kc::animationClipHash("jump"),true,nodes)==
            kc::AnimationControlResult::Ok,
        "v2 play jump"
    );
    near(nodes[0].translation.x,10.0f,1.0e-6f,"play did not compose time zero");
    runtime.tick(0.25f,nodes); runtime.tick(0.25f,nodes);
    near(nodes[0].translation.x,12.0f,1.0e-5f,"jump midpoint");
    check(runtime.stop(0,false,nodes)==kc::AnimationControlResult::Ok,"stop hold");
    runtime.tick(0.25f,nodes);
    near(nodes[0].translation.x,12.0f,1.0e-5f,"stop did not hold pose");
    check(
        runtime.play(0,kc::animationClipHash("jump"),false,nodes)==
            kc::AnimationControlResult::Ok,
        "resume jump"
    );
    runtime.tick(0.25f,nodes);
    near(nodes[0].translation.x,13.0f,1.0e-5f,"resume did not retain elapsed time");
    check(
        runtime.play(0,kc::animationClipHash("jump"),true,nodes)==
            kc::AnimationControlResult::Ok,
        "restart jump"
    );
    near(nodes[0].translation.x,10.0f,1.0e-6f,"restart did not return to time zero");
    for (int index=0;index<4;++index) runtime.tick(0.25f,nodes);
    near(nodes[0].translation.x,14.0f,1.0e-5f,"once endpoint");
    runtime.tick(0.25f,nodes);
    near(nodes[0].translation.x,14.0f,1.0e-5f,"once did not stop at end");
    check(runtime.stop(0,true,nodes)==kc::AnimationControlResult::Ok,"stop reset");
    near(nodes[0].translation.x,10.0f,1.0e-6f,"stop reset translation");
    near(nodes[0].scale.y,3.0f,1.0e-6f,"stop reset scale");
    check(
        runtime.play(0,kc::animationClipHash("missing"),true,nodes)==
            kc::AnimationControlResult::MissingClip,
        "missing clip result"
    );
    check(
        runtime.play(1,kc::animationClipHash("jump"),true,nodes)==
            kc::AnimationControlResult::MissingController,
        "missing controller result"
    );
}

void inactiveAdvancesTest() {
    auto nodes=baseNodes(); kc::TransformAnimations runtime;
    runtime.load(validPack(),nodes); nodes[0].active=false;
    runtime.tick(0.25f,nodes); runtime.tick(0.25f,nodes);
    near(nodes[0].translation.x,10.0f,1.0e-6f,"inactive node changed");
    nodes[0].active=true; runtime.compose(nodes);
    near(nodes[0].translation.x,11.0f,1.0e-5f,"inactive clock did not advance");
    runtime.load({},nodes);
    check(runtime.bindingCount()==0&&runtime.keyCount()==0,"empty optional KCAN did not clear");
}

void playbackModesAndEasingTest() {
    auto loopPack=validPack(); loopPack.at(38)=1;
    auto nodes=baseNodes(); kc::TransformAnimations loop;
    loop.load(loopPack,nodes);
    for (int index=0;index<4;++index) loop.tick(0.25f,nodes);
    near(nodes[0].translation.x,10.0f,1.0e-5f,"loop wrap");

    auto pingpongPack=validPack(); pingpongPack.at(38)=2;
    nodes=baseNodes(); kc::TransformAnimations pingpong;
    pingpong.load(pingpongPack,nodes);
    for (int index=0;index<6;++index) pingpong.tick(0.25f,nodes);
    near(nodes[0].translation.x,11.0f,1.0e-5f,"pingpong reflection");

    auto stepPack=validPack(); stepPack.at(66)=1;
    nodes=baseNodes(); kc::TransformAnimations step;
    step.load(stepPack,nodes); step.tick(0.25f,nodes); step.tick(0.25f,nodes);
    near(nodes[0].translation.x,10.0f,1.0e-5f,"step easing hold");
    step.tick(0.25f,nodes); step.tick(0.25f,nodes);
    near(nodes[0].translation.x,12.0f,1.0e-5f,"step easing endpoint");

    auto easeInPack=validPack(); easeInPack.at(66)=2;
    nodes=baseNodes(); kc::TransformAnimations easeIn;
    easeIn.load(easeInPack,nodes); easeIn.tick(0.25f,nodes); easeIn.tick(0.25f,nodes);
    near(nodes[0].translation.x,10.5f,1.0e-5f,"ease-in midpoint");

    for (std::uint8_t easing=3;easing<=8;++easing) {
        auto pack=validPack(); pack.at(66)=easing;
        nodes=baseNodes(); kc::TransformAnimations runtime;
        runtime.load(pack,nodes); runtime.tick(0.25f,nodes);
        check(std::isfinite(nodes[0].translation.x)&&std::isfinite(nodes[0].rotation.w)&&
            std::isfinite(nodes[0].scale.y),"portable easing produced a nonfinite pose");
    }
}

void rejectionTests() {
    const auto valid=validPack(); const auto nodes=baseNodes();
    auto corrupt=valid; corrupt.push_back(0); expectFailure(corrupt,nodes,"trailing byte");
    corrupt=valid; writeU32(corrupt,32,1u); expectFailure(corrupt,nodes,"noncontiguous keys");
    corrupt=valid; writeU16(corrupt,64,0u); expectFailure(corrupt,nodes,"duplicate key time");
    corrupt=valid; writeU16(corrupt,44,0x3c00u); expectFailure(corrupt,nodes,"nonidentity first key");
    corrupt=valid; writeU16(corrupt,50,0x3800u); expectFailure(corrupt,nodes,"nonnormalized first rotation");
    corrupt=valid; writeU16(corrupt,82,0xbc00u); expectFailure(corrupt,nodes,"scale sign crossing");
    corrupt=valid; writeU16(corrupt,68,0x7000u); expectFailure(corrupt,nodes,"translation range");
    corrupt=valid; writeU16(corrupt,82,0x5800u); expectFailure(corrupt,nodes,"scale upper range");
    corrupt=valid; writeU16(corrupt,82,0x1000u); expectFailure(corrupt,nodes,"scale lower range");
    corrupt=valid; writeU16(corrupt,68,0x7c00u); expectFailure(corrupt,nodes,"infinite key value");
    corrupt=valid; writeF32(corrupt,28,0.001f); expectFailure(corrupt,nodes,"short duration");
    auto dynamicNodes=nodes; dynamicNodes[0].dynamic=true;
    expectFailure(valid,dynamicNodes,"dynamic binding");
    auto playerNodes=nodes; playerNodes[0].tagMask=kc::TagPlayer;
    expectFailure(valid,playerNodes,"Player binding");

    const auto v2=validV2Pack();
    corrupt=v2; corrupt.at(47)=2u; expectFailure(corrupt,nodes,"v2 unknown flags");
    corrupt=v2; corrupt.at(47)=1u; corrupt.at(71)=1u;
    expectFailure(corrupt,nodes,"v2 duplicate autoplay");
    corrupt=v2;
    for (std::size_t index=0;index<8;++index) corrupt.at(52+index)=corrupt.at(28+index);
    expectFailure(corrupt,nodes,"v2 duplicate clip hash");
}

} // namespace

int main() {
    try {
        playbackTest(); multiClipControlTest(); inactiveAdvancesTest();
        playbackModesAndEasingTest(); rejectionTests();
        std::cout<<"PASS transform animation runtime\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr<<"FAIL transform animation runtime: "<<error.what()<<"\n";
        return 1;
    }
}
