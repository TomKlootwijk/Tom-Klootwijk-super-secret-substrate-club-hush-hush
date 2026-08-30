#include "graph_vm.hpp"
#include "transform_animation.hpp"

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
    std::uint32_t bits=0;
    std::memcpy(&bits,&value,sizeof(bits));
    appendU32(output,bits);
}

void appendText(std::vector<std::uint8_t>& output,const std::string& value) {
    appendU16(output,static_cast<std::uint16_t>(value.size()));
    output.insert(output.end(),value.begin(),value.end());
}

void appendKey(
    std::vector<std::uint8_t>& output,std::uint16_t time,
    const std::uint16_t (&values)[10]
) {
    appendU16(output,time); appendU8(output,0u); appendU8(output,0u);
    for (const auto value:values) appendU16(output,value);
}

std::vector<std::uint8_t> animationPack() {
    std::vector<std::uint8_t> output;
    const char magic[8]={'K','C','A','N','3','9','2','\0'};
    output.insert(output.end(),magic,magic+8);
    appendU32(output,0x01020304u); appendU32(output,2u);
    appendU16(output,1u); appendU16(output,0u); appendU32(output,2u);
    appendU32(output,0u); appendU64(output,kc::animationClipHash("jump"));
    appendF32(output,1.0f); appendU32(output,0u); appendU16(output,2u);
    appendU8(output,0u); appendU8(output,0u);
    constexpr std::uint16_t identity[10]={
        0x0000,0x0000,0x0000,
        0x3c00,0x0000,0x0000,0x0000,
        0x3c00,0x3c00,0x3c00,
    };
    constexpr std::uint16_t destination[10]={
        0x4400,0x0000,0x0000,
        0x3c00,0x0000,0x0000,0x0000,
        0x3c00,0x3c00,0x3c00,
    };
    appendKey(output,0u,identity); appendKey(output,65535u,destination);
    return output;
}

std::vector<std::uint8_t> graphPack(
    std::uint8_t opcode,const std::string& clip,bool option
) {
    const bool play=opcode==26u;
    std::vector<std::string> strings{"animation_action"};
    if (play) strings.push_back(clip);
    if (play&&clip<strings.front()) std::swap(strings[0],strings[1]);
    const auto graphString=static_cast<std::uint32_t>(
        strings[0]=="animation_action"?0u:1u
    );
    const auto clipString=play?static_cast<std::uint32_t>(
        strings[0]==clip?0u:1u
    ):0u;
    const std::uint32_t valueCount=play?3u:2u;
    const std::uint32_t inputCount=play?3u:2u;

    std::vector<std::uint8_t> output;
    const char magic[8]={'K','C','V','G','0','0','1','\0'};
    output.insert(output.end(),magic,magic+8);
    appendU32(output,0x01020304u); appendU32(output,1u);
    for (const auto count:{
        static_cast<std::uint32_t>(strings.size()),valueCount,1u,1u,2u,
        inputCount,1u,0u,
    }) appendU32(output,count);
    for (const auto& value:strings) appendText(output,value);
    appendU8(output,0u); // null entity
    appendU8(output,1u); appendU8(output,option?1u:0u); // bool option
    if (play) { appendU8(output,3u); appendU32(output,clipString); }

    appendU32(output,graphString); appendU32(output,0u);
    appendU16(output,2u); appendU16(output,1024u);
    appendU32(output,0u); appendU32(output,0u); // binding graph + scene node

    appendU32(output,0u); appendU32(output,0u);
    appendU16(output,0u); appendU16(output,1u); appendU16(output,0u);
    appendU8(output,1u); appendU8(output,0u); // Ready
    appendU32(output,0u); appendU32(output,1u);
    appendU16(output,static_cast<std::uint16_t>(inputCount));
    appendU16(output,0u); appendU16(output,0u);
    appendU8(output,opcode); appendU8(output,0u);

    appendU32(output,0u); // bound entity
    if (play) appendU32(output,2u); // clip string value
    appendU32(output,1u); // restart/reset bool
    appendU16(output,1u); // Ready -> action
    return output;
}

void check(bool condition,const std::string& message) {
    if (!condition) throw std::runtime_error(message);
}

void near(float actual,float expected,const std::string& label) {
    if (std::abs(actual-expected)>1.0e-5f)
        throw std::runtime_error(label+" mismatch");
}

std::vector<kc::NodeData> nodes() {
    kc::NodeData node;
    node.id="animated";
    node.translation={10.0f,20.0f,30.0f};
    return {node};
}

void playOpcodeTest() {
    auto scene=nodes();
    kc::TransformAnimations animations;
    animations.load(animationPack(),scene);
    kc::GraphVm vm;
    vm.setTransformAnimations(&animations);
    vm.load(graphPack(26u,"jump",true),scene.size());
    vm.ready(scene);
    check(vm.issues().empty(),"Play Animation reported an issue");
    near(scene[0].translation.x,10.0f,"Play Animation time zero");
    animations.tick(0.25f,scene);
    near(scene[0].translation.x,11.0f,"Play Animation next-tick advance");

    kc::GraphVm missing;
    missing.setTransformAnimations(&animations);
    missing.load(graphPack(26u,"missing",true),scene.size());
    missing.ready(scene);
    check(
        missing.issues().size()==1&&
        missing.issues()[0].code==kc::GraphVmError::MissingAnimationClip,
        "Play Animation missing clip error"
    );
}

void stopOpcodeTest() {
    auto scene=nodes();
    kc::TransformAnimations animations;
    animations.load(animationPack(),scene);
    check(
        animations.play(0,kc::animationClipHash("jump"),true,scene)==
            kc::AnimationControlResult::Ok,
        "direct setup play"
    );
    animations.tick(0.25f,scene);
    near(scene[0].translation.x,11.0f,"Stop Animation setup pose");

    kc::GraphVm hold;
    hold.setTransformAnimations(&animations);
    hold.load(graphPack(27u,"",false),scene.size());
    hold.ready(scene);
    check(hold.issues().empty(),"Stop Animation hold reported an issue");
    animations.tick(0.25f,scene);
    near(scene[0].translation.x,11.0f,"Stop Animation hold");

    kc::GraphVm reset;
    reset.setTransformAnimations(&animations);
    reset.load(graphPack(27u,"",true),scene.size());
    reset.ready(scene);
    check(reset.issues().empty(),"Stop Animation reset reported an issue");
    near(scene[0].translation.x,10.0f,"Stop Animation reset");
}

} // namespace

int main() {
    try {
        playOpcodeTest(); stopOpcodeTest();
        std::cout<<"PASS animation graph VM opcodes\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr<<"FAIL animation graph VM opcodes: "<<error.what()<<"\n";
        return 1;
    }
}
