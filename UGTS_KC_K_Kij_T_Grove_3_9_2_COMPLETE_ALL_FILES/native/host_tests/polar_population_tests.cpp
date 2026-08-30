#include "graph_vm.hpp"
#include "polar_kinematics.hpp"
#include "polar_populations.hpp"
#include "render_substrate.hpp"
#include "scene_pack.hpp"

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {

std::vector<std::uint8_t> readBytes(const char* path) {
    std::ifstream stream(path,std::ios::binary);
    if (!stream) throw std::runtime_error("could not open polar population test asset");
    return {
        std::istreambuf_iterator<char>(stream),
        std::istreambuf_iterator<char>()
    };
}

void check(bool condition,std::string_view message) {
    if (!condition) throw std::runtime_error(std::string(message));
}

void appendU8(std::vector<std::uint8_t>& bytes,std::uint8_t value) {
    bytes.push_back(value);
}

void appendU16(std::vector<std::uint8_t>& bytes,std::uint16_t value) {
    bytes.push_back(static_cast<std::uint8_t>(value));
    bytes.push_back(static_cast<std::uint8_t>(value>>8));
}

void appendU32(std::vector<std::uint8_t>& bytes,std::uint32_t value) {
    for (unsigned index=0;index<4u;++index)
        bytes.push_back(static_cast<std::uint8_t>(value>>(index*8u)));
}

struct RenderRecipeAction {
    std::uint32_t targetToken=0;
    std::uint32_t visibleToken=1;
};

std::vector<std::uint8_t> renderRecipeGraph(
    std::uint32_t binding,const std::vector<RenderRecipeAction>& actions
) {
    check(!actions.empty(),"render recipe test graph needs an action");
    const char magic[8]={'K','C','V','G','0','0','1','\0'};
    const std::string_view graphId="render_recipe_toggle";
    std::vector<std::uint8_t> bytes(magic,magic+8);
    appendU32(bytes,0x01020304u);
    appendU32(bytes,1u);
    appendU32(bytes,1u); // strings
    appendU32(bytes,3u); // null, false, true
    appendU32(bytes,1u); // graphs
    appendU32(bytes,1u); // bindings
    appendU32(bytes,static_cast<std::uint32_t>(actions.size()+1u));
    appendU32(bytes,static_cast<std::uint32_t>(actions.size()*2u));
    appendU32(bytes,static_cast<std::uint32_t>(actions.size()));
    appendU32(bytes,0u); // state
    appendU16(bytes,static_cast<std::uint16_t>(graphId.size()));
    bytes.insert(bytes.end(),graphId.begin(),graphId.end());
    appendU8(bytes,0u); // null
    appendU8(bytes,1u); appendU8(bytes,0u); // false
    appendU8(bytes,1u); appendU8(bytes,1u); // true
    appendU32(bytes,0u); // graph ID string
    appendU32(bytes,0u); // first node
    appendU16(bytes,static_cast<std::uint16_t>(actions.size()+1u));
    appendU16(bytes,1024u);
    appendU32(bytes,0u); // graph index
    appendU32(bytes,binding);

    // Ready: its only flow starts the first Show or Hide Extra Copies action.
    appendU32(bytes,0u); appendU32(bytes,0u);
    appendU16(bytes,0u); appendU16(bytes,1u); appendU16(bytes,0u);
    appendU8(bytes,1u); appendU8(bytes,0u);
    for (std::size_t index=0;index<actions.size();++index) {
        appendU32(bytes,static_cast<std::uint32_t>(index*2u));
        appendU32(bytes,static_cast<std::uint32_t>(index+1u));
        appendU16(bytes,2u);
        appendU16(bytes,index+1u<actions.size()?1u:0u);
        appendU16(bytes,0u);
        appendU8(bytes,30u); appendU8(bytes,0u);
    }
    for (const auto& action:actions) {
        appendU32(bytes,action.targetToken);
        appendU32(bytes,action.visibleToken);
    }
    for (std::size_t index=0;index<actions.size();++index)
        appendU16(bytes,static_cast<std::uint16_t>(index+1u));
    return bytes;
}

void expectGraphLoadFailure(
    const std::vector<std::uint8_t>& bytes,std::size_t sceneNodeCount,
    std::string_view message
) {
    bool rejected=false;
    try {
        kc::GraphVm vm;
        vm.load(bytes,sceneNodeCount);
    } catch (const std::runtime_error&) {
        rejected=true;
    }
    check(rejected,message);
}

class ExpectedReader {
public:
    explicit ExpectedReader(const std::vector<std::uint8_t>& bytes)
        :data_(bytes.data()),size_(bytes.size()) {}
    const std::uint8_t* raw(std::size_t count) {
        if (count>size_-offset_) throw std::runtime_error("truncated expected vector");
        const auto* result=data_+offset_; offset_+=count; return result;
    }
    std::uint16_t u16() {
        const auto* p=raw(2); return static_cast<std::uint16_t>(p[0]|(p[1]<<8));
    }
    std::uint32_t u32() {
        const auto* p=raw(4); return static_cast<std::uint32_t>(p[0])|
            (static_cast<std::uint32_t>(p[1])<<8)|
            (static_cast<std::uint32_t>(p[2])<<16)|
            (static_cast<std::uint32_t>(p[3])<<24);
    }
    std::uint64_t u64() {
        return static_cast<std::uint64_t>(u32())|
            (static_cast<std::uint64_t>(u32())<<32);
    }
    float f32() { return std::bit_cast<float>(u32()); }
    std::array<std::uint8_t,16> address() {
        std::array<std::uint8_t,16> result{};
        std::memcpy(result.data(),raw(result.size()),result.size());
        return result;
    }
    bool done() const { return offset_==size_; }
private:
    const std::uint8_t* data_=nullptr;
    std::size_t size_=0,offset_=0;
};

void expectLoadFailure(
    const std::vector<std::uint8_t>& bytes,std::uint64_t seed,
    const kc::ScenePack& scene,const kc::PackedPolarKinematics& polar,
    std::string_view message
) {
    bool rejected=false;
    try {
        kc::PolarPopulations populations;
        populations.load(bytes,seed,scene,polar);
    } catch (const std::runtime_error&) {
        rejected=true;
    }
    check(rejected,message);
}

void expectLoadFailureContaining(
    const std::vector<std::uint8_t>& bytes,std::uint64_t seed,
    const kc::ScenePack& scene,const kc::PackedPolarKinematics& polar,
    std::string_view expectedMessage,std::string_view message
) {
    bool rejected=false;
    try {
        kc::PolarPopulations populations;
        populations.load(bytes,seed,scene,polar);
    } catch (const std::runtime_error& error) {
        rejected=std::string_view(error.what()).find(expectedMessage)!=
            std::string_view::npos;
    }
    check(rejected,message);
}

void near(float actual,float expected,float tolerance,std::string_view message) {
    check(std::isfinite(actual)&&std::isfinite(expected)&&
        std::abs(actual-expected)<=tolerance,message);
}

float testF32(float value) {
    volatile float rounded=value;
    return rounded;
}

float testAdd32(float left,float right) {
    volatile float result=testF32(left)+testF32(right);
    return result;
}

float testSubtract32(float left,float right) {
    volatile float result=testF32(left)-testF32(right);
    return result;
}

float testMultiply32(float left,float right) {
    volatile float result=testF32(left)*testF32(right);
    return result;
}

float testDivide32(float left,float right) {
    volatile float result=testF32(left)/testF32(right);
    return result;
}

std::uint16_t testU16At(
    const std::vector<std::uint8_t>& bytes,std::size_t offset
) {
    check(offset+2u<=bytes.size(),"test u16 offset is outside the fixture");
    return static_cast<std::uint16_t>(bytes[offset])|
        static_cast<std::uint16_t>(
            static_cast<std::uint16_t>(bytes[offset+1u])<<8u
        );
}

void testWriteU16At(
    std::vector<std::uint8_t>& bytes,std::size_t offset,std::uint16_t value
) {
    check(offset+2u<=bytes.size(),"test u16 write is outside the fixture");
    bytes[offset]=static_cast<std::uint8_t>(value);
    bytes[offset+1u]=static_cast<std::uint8_t>(value>>8u);
}

void testWriteU32At(
    std::vector<std::uint8_t>& bytes,std::size_t offset,std::uint32_t value
) {
    check(offset+4u<=bytes.size(),"test u32 write is outside the fixture");
    for (std::size_t index=0;index<4u;++index)
        bytes[offset+index]=static_cast<std::uint8_t>(value>>(index*8u));
}

std::vector<std::uint8_t> growV4Fixture(
    const std::vector<std::uint8_t>& glowV3
) {
    check(glowV3.size()>=32u &&
            std::memcmp(glowV3.data(),"KCPR392\0",8)==0,
        "Grow source is not a KCPR392 fixture");
    check(testU16At(glowV3,16u)==8u && testU16At(glowV3,18u)==1u,
        "Grow source is not the frozen one-recipe Glow fixture");
    const auto oldRecipeOffset=32u+8u*16u;
    check(oldRecipeOffset+128u==glowV3.size() &&
            testU16At(glowV3,oldRecipeOffset+6u)==0x0e3bu,
        "Grow source recipe layout or mask changed");

    std::vector<std::uint8_t> result=glowV3;
    testWriteU32At(result,12u,4u);
    testWriteU16At(result,16u,9u);
    constexpr std::array<std::uint8_t,16> GrowOperator{{
        0x53u,0x00u,0x0cu,0x02u,0x00u,0x00u,0x00u,0x00u,
        0x6bu,0x79u,0xa6u,0xb7u,0x07u,0x8cu,0x55u,0x1du,
    }};
    result.insert(
        result.begin()+static_cast<std::ptrdiff_t>(oldRecipeOffset),
        GrowOperator.begin(),GrowOperator.end()
    );
    const auto recipeOffset=oldRecipeOffset+GrowOperator.size();
    testWriteU16At(result,recipeOffset+6u,0x1e3bu);
    // Exact v4 content address for the frozen v3 Ring fixture under:
    // prefix v4, unchanged lineage bytes, full mask, unchanged Glow lanes,
    // Glow+Grow meaning entries, then the unchanged instance count.
    constexpr std::array<std::uint8_t,16> GrowContentAddress{{
        0xa5u,0xbeu,0x3du,0xedu,0x37u,0x4fu,0x69u,0x4fu,
        0x69u,0x6cu,0x16u,0xaau,0x61u,0xeeu,0x65u,0x88u,
    }};
    std::copy(
        GrowContentAddress.begin(),GrowContentAddress.end(),
        result.begin()+static_cast<std::ptrdiff_t>(recipeOffset+20u)
    );
    return result;
}

std::uint32_t runGlowVectors(
    const std::vector<std::uint8_t>& expectedBytes,
    std::vector<kc::NodeData>& nodes,
    const kc::PackedPolarKinematics& polar,
    const kc::PolarPopulations& populations
) {
    ExpectedReader expected(expectedBytes);
    check(std::memcmp(expected.raw(8),"KPGV392\0",8)==0,
        "Glow expected vector magic changed");
    check(expected.u32()==1u,"Glow expected vector version changed");
    const auto vectorCount=expected.u32();
    check(vectorCount>=1u && vectorCount<=64u,
        "Glow expected vector count is invalid");
    const auto expectedLineageAddress=expected.address();
    const auto expectedContentAddress=expected.address();
    const auto centerRho=expected.f32();
    const auto invHalfWidth=expected.f32();
    const auto strength=expected.f32();
    check(populations.formatVersion()==3u,
        "native Glow fixture did not load as KCPR v3");
    check(populations.recipeCount()==1u && populations.generatedCount()==63u &&
            populations.totalInstanceCount()==64u,
        "native Glow fixture counts changed");
    const auto& recipe=populations.recipes().front();
    check(recipe.preset==1u && recipe.operatorMask==0x0e3bu && recipe.glow,
        "native Glow preset, operator mask, or enabled state changed");
    check(recipe.lineageNamespace==expectedLineageAddress &&
            recipe.contentAddress==expectedContentAddress,
        "native Glow lineage/content address parity changed");
    near(recipe.glowCenterRho,centerRho,0.0f,
        "native Glow center rho changed");
    near(recipe.glowInvHalfWidth,invHalfWidth,0.0f,
        "native Glow inverse half width changed");
    near(recipe.glowStrength,strength,0.0f,
        "native Glow strength changed");

    constexpr float Tau=6.28318530717958647692f;
    constexpr float Tolerance=2.0e-6f;
    for (std::uint32_t vectorIndex=0;vectorIndex<vectorCount;++vectorIndex) {
        const auto instanceIndex=expected.u32();
        const auto theta18=expected.u32();
        const auto lineage=expected.u64();
        const auto phase12=expected.u32();
        const auto shiftedTheta18=expected.u32();
        const auto rho=expected.f32();
        const auto pulse=expected.f32();
        const auto direction=expected.f32();
        const auto glow=expected.f32();
        check(populations.instanceLineage(0u,instanceIndex)==lineage,
            "native Glow random-access lineage changed");
        check(populations.glowPhase12(0u,instanceIndex)==phase12,
            "native Glow lane-5 phase12 changed");
        check(((theta18+(phase12<<6u))&0x3ffffu)==shiftedTheta18,
            "native Glow shifted theta18 code changed");
        const auto lutSample=populations.evaluateGlowSample(
            0u,instanceIndex,rho,theta18,polar,
            kc::PolarPopulations::GlowDirectionMode::Lut
        );
        near(lutSample.pulse,pulse,Tolerance,
            "native Glow radial pulse changed");
        near(lutSample.direction,direction,Tolerance,
            "native Glow authored UGLUT2 direction changed");
        near(lutSample.field,glow,Tolerance,
            "native Glow authored UGLUT2 field changed");
        near(lutSample.displayScaleMultiplier,1.0f,0.0f,
            "legacy KCPR v3 unexpectedly enabled display scaling");

        const auto angleStep=testDivide32(Tau,262144.0f);
        const auto shiftedAngle=testMultiply32(
            static_cast<float>(shiftedTheta18),angleStep
        );
        const auto directDirection=std::clamp(testAdd32(
            0.5f,testMultiply32(
                0.5f,testF32(static_cast<float>(std::cos(shiftedAngle)))
            )
        ),0.0f,1.0f);
        const auto directGlow=std::clamp(testMultiply32(
            testMultiply32(strength,pulse),directDirection
        ),0.0f,4.0f);
        const auto directSample=populations.evaluateGlowSample(
            0u,instanceIndex,rho,theta18,polar,
            kc::PolarPopulations::GlowDirectionMode::Direct
        );
        near(directSample.direction,directDirection,0.0f,
            "native Glow Direct direction formula changed");
        near(directSample.field,directGlow,0.0f,
            "native Glow Direct field formula changed");
    }
    check(expected.done(),"Glow expected vector has trailing bytes");
    const auto firstCopy=populations.materialize(0u,polar,nodes,false);
    check(firstCopy.instanceIndex==1u &&
            firstCopy.glowPhase12==populations.glowPhase12(0u,1u),
        "native Glow visible-copy phase attribute changed");

    const auto rendererBytes=readBytes(UGTS_RENDERER_SOURCE_PATH);
    const std::string rendererSource(rendererBytes.begin(),rendererBytes.end());
    const auto engineBytes=readBytes(UGTS_ENGINE_SOURCE_PATH);
    const std::string engineSource(engineBytes.begin(),engineBytes.end());
    const auto rendererHeaderBytes=readBytes(UGTS_RENDERER_HEADER_SOURCE_PATH);
    const std::string rendererHeader(
        rendererHeaderBytes.begin(),rendererHeaderBytes.end()
    );
    const auto shaderBytes=readBytes(UGTS_POLAR_SHADER_SOURCE_PATH);
    const std::string shaderSource(shaderBytes.begin(),shaderBytes.end());
    const auto sceneVertexBytes=readBytes(UGTS_SCENE_VERTEX_SOURCE_PATH);
    const std::string sceneVertex(sceneVertexBytes.begin(),sceneVertexBytes.end());
    const auto sceneFragmentBytes=readBytes(UGTS_SCENE_FRAGMENT_SOURCE_PATH);
    const std::string sceneFragment(
        sceneFragmentBytes.begin(),sceneFragmentBytes.end()
    );
    check(rendererHeader.find("PolarInstanceStrideBytes=36u;")!=
            std::string::npos &&
        rendererHeader.find(
            "static_assert(sizeof(PolarInstance)==PolarInstanceStrideBytes);")!=
            std::string::npos &&
        rendererHeader.find("std::uint32_t glowPhase12=0;")!=std::string::npos &&
        rendererHeader.find("PolarMaterialValidFlag=0x40000000u;")!=
            std::string::npos &&
        rendererHeader.find("PolarGeneratedCopyFlag=0x80000000u;")!=
            std::string::npos,
        "polar instance ABI is not the frozen 32-byte payload plus one u32 phase");
    check(shaderSource.find("layout(location = 4) in uint aGlowPhase12;")!=
            std::string::npos &&
        shaderSource.find("lutDirection(materialAngle).x")!=std::string::npos &&
        shaderSource.find("0.5+0.5*cos(materialAngle)")!=std::string::npos &&
        shaderSource.find("1.0-u*u*(3.0-2.0*u)")!=std::string::npos &&
        shaderSource.find("(aGlowPhase12&GeneratedCopyFlag)!=0u")!=
            std::string::npos &&
        shaderSource.find("clamp(1.0+glowField,1.0,5.0)")!=
            std::string::npos &&
        shaderSource.find("instanceScale*=displayGrowScale;")!=
            std::string::npos &&
        shaderSource.find("uniform int uGrow") == std::string::npos,
        "polar shader lost shared Glow/Grow formulas, prototype gate, or compact ABI");
    const auto burstScalePosition=shaderSource.find(
        "instanceScale=uBurstScale*displayScale;"
    );
    const auto growScalePosition=shaderSource.find(
        "instanceScale*=displayGrowScale;"
    );
    check(burstScalePosition!=std::string::npos &&
            growScalePosition!=std::string::npos &&
            burstScalePosition<growScalePosition,
        "polar shader no longer applies Burst before Grow");
    check(sceneVertex.find("vPolarGlow = uPolarGlowField;")!=std::string::npos &&
        sceneFragment.find("lit += materialBase * vPolarGlow;")!=
            std::string::npos,
        "ordinary fallback or scene lighting silently dropped Glow");
    check(rendererSource.find(
            "polarKinematics,PolarPopulations::GlowDirectionMode::Lut")!=
            std::string::npos &&
        rendererSource.find("glUniform1f(uPolarGlowField_,0.0f);")!=
            std::string::npos &&
        rendererSource.find("group.glowRecipeIndex")!=std::string::npos &&
        rendererSource.find("group.burstRecipeIndex")!=std::string::npos &&
        rendererSource.find("recipe.growCopies?3:1")!=std::string::npos &&
        rendererSource.find("PolarGeneratedCopyFlag")!=std::string::npos &&
        rendererSource.find(
            "copy.node,copy.glowField,copy.materialCoordinate")!=
            std::string::npos,
        "renderer lost shared LUT fallback, Grow bitfield, or generated-copy gate");
    check(engineSource.find(
            "polar population format_version=%u recipes=%u generated=%u glow_recipes=%u glow_instances=%u grow_recipes=%u grow_instances=%u gpu_instance_stride_bytes=%u")!=
            std::string::npos &&
        engineSource.find("RendererGles3::PolarInstanceStrideBytes")!=
            std::string::npos,
        "engine startup log cannot prove loaded Glow recipes/instances/ABI");

    std::cout<<"PASS native KCPR392 Glow vectors="<<vectorCount
        <<" generated="<<populations.generatedCount()
        <<" source_formula_only=true\n";
    return vectorCount;
}

void runGrowCopiesV4(
    const std::vector<std::uint8_t>& glowV3Bytes,std::vector<kc::NodeData>& nodes,
    const kc::ScenePack& scene,const kc::PackedPolarKinematics& polar,
    std::uint64_t rootSeed,const kc::PolarPopulations& glowV3
) {
    const auto growBytes=growV4Fixture(glowV3Bytes);
    kc::PolarPopulations grow;
    grow.load(growBytes,rootSeed,scene,polar);
    check(grow.formatVersion()==4u && grow.recipeCount()==1u &&
            grow.generatedCount()==63u,
        "native Grow fixture did not load as bounded KCPR v4");
    const auto& recipe=grow.recipes().front();
    check(recipe.glow && recipe.growCopies &&
            recipe.operatorMask==0x1e3bu,
        "native Grow Glow dependency, enabled state, or mask changed");
    check(recipe.lineageNamespace==glowV3.recipes().front().lineageNamespace,
        "Grow changed the spatial lineage namespace");
    check(recipe.contentAddress!=glowV3.recipes().front().contentAddress,
        "Grow did not change the full recipe content address");

    const auto centerSample=grow.evaluateGlowSample(
        0u,1u,recipe.glowCenterRho,0u,polar,
        kc::PolarPopulations::GlowDirectionMode::Lut
    );
    const auto expectedCenterMultiplier=std::clamp(
        testAdd32(1.0f,centerSample.field),1.0f,5.0f
    );
    near(
        centerSample.displayScaleMultiplier,expectedCenterMultiplier,0.0f,
        "native Grow did not reuse the exact bounded Glow field"
    );

    const auto prototypeIndex=recipe.prototypeSceneNode;
    check(prototypeIndex<nodes.size(),"native Grow prototype is invalid");
    const auto prototypeBefore=nodes[prototypeIndex];
    bool testedPositiveField=false;
    for (std::size_t generatedIndex=0u;
            generatedIndex<grow.generatedCount();++generatedIndex) {
        auto baseline=glowV3.materialize(
            generatedIndex,polar,nodes,false
        );
        glowV3.composeCartesian(baseline,polar);
        auto grown=grow.materialize(generatedIndex,polar,nodes,false);
        grow.composeCartesian(grown,polar);
        check(grown.lineage==baseline.lineage && grown.pose==baseline.pose &&
                grown.previousPose==baseline.previousPose,
            "Grow changed placement lineage or packed pose");
        if (grown.glowField<=0.0f) continue;
        const auto multiplier=std::clamp(
            testAdd32(1.0f,grown.glowField),1.0f,5.0f
        );
        near(grown.displayScaleMultiplier,multiplier,0.0f,
            "native Grow CPU multiplier changed");
        near(grown.node.scale.x,
            testMultiply32(baseline.node.scale.x,multiplier),0.0f,
            "native Grow CPU X display scale changed");
        near(grown.node.scale.y,
            testMultiply32(baseline.node.scale.y,multiplier),0.0f,
            "native Grow CPU Y display scale changed");
        near(grown.node.scale.z,
            testMultiply32(baseline.node.scale.z,multiplier),0.0f,
            "native Grow CPU Z display scale changed");
        near(grown.node.translation.x,baseline.node.translation.x,0.0f,
            "Grow changed generated X placement");
        near(grown.node.translation.y,baseline.node.translation.y,0.0f,
            "Grow changed generated Y placement");
        near(grown.node.translation.z,baseline.node.translation.z,0.0f,
            "Grow changed generated Z placement");
        testedPositiveField=true;
        break;
    }
    check(testedPositiveField,"native Grow fixture produced no positive field");
    check(nodes[prototypeIndex].scale.x==prototypeBefore.scale.x &&
            nodes[prototypeIndex].scale.y==prototypeBefore.scale.y &&
            nodes[prototypeIndex].scale.z==prototypeBefore.scale.z,
        "Grow mutated the authoritative prototype scale");

    auto invalid=growBytes;
    testWriteU32At(invalid,12u,3u);
    expectLoadFailure(invalid,rootSeed,scene,polar,
        "KCPR v3 accepted the v4 Grow operator");
    invalid=glowV3Bytes;
    testWriteU32At(invalid,12u,4u);
    expectLoadFailure(invalid,rootSeed,scene,polar,
        "KCPR v4 accepted an asset without a Grow recipe");
    const auto recipeOffset=32u+9u*16u;
    invalid=growBytes;
    testWriteU16At(
        invalid,recipeOffset+6u,
        static_cast<std::uint16_t>(0x1e3bu&~0x0200u)
    );
    expectLoadFailure(invalid,rootSeed,scene,polar,
        "KCPR v4 accepted Grow without its complete Glow field");
    invalid=growBytes;
    invalid[32u+8u*16u+8u]^=1u;
    expectLoadFailure(invalid,rootSeed,scene,polar,
        "KCPR v4 accepted a changed Grow meaning hash");
    invalid=growBytes;
    std::fill(
        invalid.begin()+static_cast<std::ptrdiff_t>(recipeOffset+116u),
        invalid.begin()+static_cast<std::ptrdiff_t>(recipeOffset+128u),
        std::uint8_t{0}
    );
    expectLoadFailure(invalid,rootSeed,scene,polar,
        "KCPR v4 accepted Grow without Glow parameters");

    std::cout<<"PASS native KCPR392 Grow v4 generated="
        <<grow.generatedCount()
        <<" stride_bytes=36 prototype_unchanged=true\n";
}

std::uint32_t runBurstVectors(
    const std::vector<std::uint8_t>& expectedBytes,
    std::vector<kc::NodeData>& nodes,
    const kc::PackedPolarKinematics& polar,
    const kc::PolarPopulations& populations
) {
    ExpectedReader expected(expectedBytes);
    check(std::memcmp(expected.raw(8),"KPBV392\0",8)==0,
        "Burst expected vector magic changed");
    check(expected.u32()==1u,"Burst expected vector version changed");
    const auto vectorCount=expected.u32();
    check(vectorCount>=1u && vectorCount<=64u,
        "Burst expected vector count is invalid");
    check(populations.formatVersion()==2u,
        "native Burst fixture did not load as KCPR v2");
    check(populations.recipeCount()==1u && populations.generatedCount()==31u &&
            populations.totalInstanceCount()==32u,
        "native Burst fixture counts changed");
    const auto& recipe=populations.recipes().front();
    check(recipe.preset==4u && recipe.operatorMask==0x01e1u,
        "native Burst preset or operator mask changed");
    check(recipe.prototypeSceneNode<nodes.size(),
        "native Burst prototype is outside the fixture scene");

    populations.beginFrame();
    std::vector<kc::PolarPopulations::RenderCopy> copies;
    copies.reserve(vectorCount);
    for (std::uint32_t vectorIndex=0;vectorIndex<vectorCount;++vectorIndex) {
        const auto fixedTick=expected.u64();
        const auto generatedIndex=expected.u32();
        const auto instanceIndex=expected.u32();
        const auto lineage=expected.u64();
        const auto previousPose=expected.u64();
        const auto currentPose=expected.u64();
        const auto cycleTick=expected.u32();
        const auto durationTicks=expected.u32();
        const auto age=expected.f32();
        const auto rho=expected.f32();
        const auto envelope=expected.f32();
        const auto heightFactor=expected.f32();
        const auto baseScale=expected.f32();
        const auto localX=expected.f32();
        const auto localZ=expected.f32();
        float finalTrs[10]{};
        for (auto& value:finalTrs) value=expected.f32();

        const auto copy=populations.materialize(
            generatedIndex,polar,nodes,fixedTick,false
        );
        check(copy.burst && copy.recipeIndex==0u &&
                copy.instanceIndex==instanceIndex,
            "native Burst copy identity changed");
        check(copy.lineage==lineage && copy.previousPose==previousPose &&
                copy.pose==currentPose && copy.motion==0u,
            "native Burst lineage or local pose changed");
        check(((copy.pose>>12u)&0x3fffu)==cycleTick &&
                durationTicks==static_cast<std::uint32_t>(recipe.parameters[2]),
            "native Burst fixed-tick cycle changed");
        if (cycleTick==0u)
            check(copy.previousPose==copy.pose,
                "native Burst wrap did not snap previous to current");
        else
            check(((copy.previousPose>>12u)&0x3fffu)+1u==cycleTick,
                "native Burst previous tick is not the prior local phase");

        const auto calculatedAge=testDivide32(
            static_cast<float>(cycleTick),static_cast<float>(durationTicks-1u)
        );
        const auto calculatedRho=testAdd32(
            recipe.parameters[0],testMultiply32(
                testSubtract32(recipe.parameters[1],recipe.parameters[0]),
                calculatedAge
            )
        );
        const auto calculatedEnvelope=testMultiply32(
            testMultiply32(4.0f,calculatedAge),
            testSubtract32(1.0f,calculatedAge)
        );
        near(age,calculatedAge,0.0f,"native Burst age schedule changed");
        near(rho,calculatedRho,0.0f,"native Burst rho schedule changed");
        near(envelope,calculatedEnvelope,0.0f,
            "native Burst envelope schedule changed");
        near(copy.burstEnvelope,envelope,0.0f,
            "native Burst copy envelope changed");
        near(copy.burstHeightFactor,heightFactor,0.0f,
            "native Burst height lineage lane changed");
        near(copy.burstScaleScalar,baseScale,0.0f,
            "native Burst scale lineage lane changed");

        kc::NodeData localNode{};
        polar.composePose(copy.profile,copy.pose,0u,localNode);
        near(localNode.translation.x,localX,0.0f,
            "native Burst LUT local X changed");
        near(localNode.translation.z,localZ,0.0f,
            "native Burst LUT local Z changed");

        auto cartesian=copy;
        populations.composeCartesian(cartesian,polar);
        const float actualTrs[]={
            cartesian.node.translation.x,cartesian.node.translation.y,
            cartesian.node.translation.z,
            cartesian.node.rotation.w,cartesian.node.rotation.x,
            cartesian.node.rotation.y,cartesian.node.rotation.z,
            cartesian.node.scale.x,cartesian.node.scale.y,cartesian.node.scale.z,
        };
        for (std::size_t field=0;field<10u;++field)
            near(actualTrs[field],finalTrs[field],
                field>=3u&&field<=6u?2.0e-5f:0.0f,
                "native Burst Cartesian TRS changed");
        copies.push_back(copy);
    }
    check(expected.done(),"Burst expected vector has trailing bytes");
    check(populations.lastMaterializedCount()==vectorCount &&
            populations.lastCartesianComposeCount()==vectorCount,
        "native Burst host vector accounting changed");

    // Mirror the renderer's common caps: hidden recipes consume nothing, and
    // a Burst copy consumes both one visible slot and one remaining particle.
    populations.beginFrame();
    constexpr std::uint32_t MaxVisible=3u;
    std::uint32_t drawn=2u,remainingParticles=1u;
    for (std::uint32_t local=0u;
            local<recipe.generatedCount && drawn<MaxVisible &&
            remainingParticles>0u;++local) {
        static_cast<void>(populations.materialize(
            static_cast<std::size_t>(recipe.firstGenerated)+local,
            polar,nodes,0u,false
        ));
        ++drawn;
        --remainingParticles;
    }
    check(drawn==MaxVisible && remainingParticles==0u &&
            populations.lastMaterializedCount()==1u &&
            populations.lastCartesianComposeCount()==0u,
        "native Burst did not respect shared particle/maxVisible caps");
    check(copies.size()==vectorCount,"native Burst vectors were not retained locally");
    return vectorCount;
}

} // namespace

int main(int argc,char** argv) {
    if (argc!=6) {
        std::cerr<<"FAIL polar population: expected KC3D KCPK KCPR KCRP vector paths\n";
        return 1;
    }
    try {
        const auto sceneBytes=readBytes(argv[1]);
        const auto polarBytes=readBytes(argv[2]);
        const auto populationBytes=readBytes(argv[3]);
        const auto substrateBytes=readBytes(argv[4]);
        const auto expectedBytes=readBytes(argv[5]);
        const auto scene=kc::parseScenePack(sceneBytes);
        auto nodes=scene.nodes;
        kc::PackedPolarKinematics polar;
        polar.load(polarBytes,nodes);
        polar.compose(nodes);
        const auto substrate=kc::parseRenderSubstrate(substrateBytes);
        kc::PolarPopulations populations;
        populations.load(populationBytes,substrate.seed,scene,polar);

        check(!populations.recipes().empty(),
            "Polar Material fixture has no KCPR recipe");
        const auto& materialRecipe=populations.recipes().front();
        const auto* materialComponent=polar.componentForSceneNode(
            materialRecipe.prototypeSceneNode
        );
        check(materialComponent!=nullptr,
            "Polar Material prototype has no packed-polar component");
        auto legacyComposed=nodes[materialRecipe.prototypeSceneNode];
        auto sampledComposed=legacyComposed;
        kc::PackedPolarKinematics::PolarChartSample reusedChart;
        polar.composePose(
            materialRecipe.profile,materialComponent->pose,
            materialComponent->motion,legacyComposed
        );
        polar.composePose(
            materialRecipe.profile,materialComponent->pose,
            materialComponent->motion,sampledComposed,&reusedChart
        );
        const float legacyPose[]={
            legacyComposed.translation.x,legacyComposed.translation.z,
            legacyComposed.rotation.w,legacyComposed.rotation.x,
            legacyComposed.rotation.y,legacyComposed.rotation.z,
            legacyComposed.velocity.x,legacyComposed.velocity.z,
        };
        const float sampledPose[]={
            sampledComposed.translation.x,sampledComposed.translation.z,
            sampledComposed.rotation.w,sampledComposed.rotation.x,
            sampledComposed.rotation.y,sampledComposed.rotation.z,
            sampledComposed.velocity.x,sampledComposed.velocity.z,
        };
        for (std::size_t field=0;field<std::size(legacyPose);++field)
            near(sampledPose[field],legacyPose[field],0.0f,
                "optional Polar Material chart changed composed geometry");
        const auto separatelySampled=polar.samplePoseChart(
            materialRecipe.profile,materialComponent->pose
        );
        near(reusedChart.normalizedRho,separatelySampled.normalizedRho,0.0f,
            "reused Polar Material log-radius sample changed");
        near(reusedChart.directionX,separatelySampled.directionX,0.0f,
            "reused Polar Material direction X changed");
        near(reusedChart.directionY,separatelySampled.directionY,0.0f,
            "reused Polar Material direction Y changed");
        const auto materialCoordinate=populations.materialCoordinate(
            0u,0u,reusedChart
        );
        check(materialCoordinate.valid(),
            "KCPR prototype did not expose a Polar Material coordinate");
        near(
            materialCoordinate.phase,
            testDivide32(
                static_cast<float>(populations.materialPhase12(0u,0u)),4096.0f
            ),0.0f,"Polar Material phase changed from the shared lineage lane"
        );
        check(
            populations.glowPhase12(0u,0u)==
                (materialRecipe.glow?populations.materialPhase12(0u,0u):0u),
            "Glow compatibility phase changed"
        );
        near(kc::PolarPopulations::polarBandMultiplier(
                materialCoordinate,4u,0.0f),1.0f,0.0f,
            "zero-strength Polar Bands changed authored material");
        const auto fullBand=kc::PolarPopulations::polarBandMultiplier(
            materialCoordinate,4u,1.0f
        );
        check(fullBand>=0.5f&&fullBand<=1.5f,
            "Polar Bands multiplier escaped its bounded range");
        bool rejectedNegativeZero=false;
        try {
            static_cast<void>(kc::PolarPopulations::polarBandMultiplier(
                materialCoordinate,4u,-0.0f
            ));
        } catch (const std::runtime_error&) {
            rejectedNegativeZero=true;
        }
        check(rejectedNegativeZero,
            "Polar Bands accepted a negative-zero strength");

        if (expectedBytes.size()>=8u &&
            std::memcmp(expectedBytes.data(),"KPGV392\0",8)==0) {
            const auto operatorCount=static_cast<std::size_t>(populationBytes[16])|
                (static_cast<std::size_t>(populationBytes[17])<<8u);
            const auto recipeOffset=32u+operatorCount*16u;
            check(recipeOffset+128u==populationBytes.size(),
                "native Glow fixture recipe offset changed");
            auto invalid=populationBytes;
            invalid[12u]=2u;
            expectLoadFailure(invalid,substrate.seed,scene,polar,
                "KCPR v2 accepted v3 Glow operators/tail");
            invalid=populationBytes;
            invalid[recipeOffset+7u]&=static_cast<std::uint8_t>(~0x02u);
            expectLoadFailure(invalid,substrate.seed,scene,polar,
                "partial Glow modifier mask was accepted");
            invalid=populationBytes;
            invalid[recipeOffset+120u]=0u;
            invalid[recipeOffset+121u]=0u;
            invalid[recipeOffset+122u]=0u;
            invalid[recipeOffset+123u]=0u;
            expectLoadFailure(invalid,substrate.seed,scene,polar,
                "zero Glow inverse half width was accepted");
            invalid=populationBytes;
            invalid[recipeOffset+124u]=0u;
            invalid[recipeOffset+125u]=0u;
            invalid[recipeOffset+126u]=0xc0u;
            invalid[recipeOffset+127u]=0x7fu;
            expectLoadFailure(invalid,substrate.seed,scene,polar,
                "nonfinite Glow strength was accepted");
            invalid=populationBytes;
            invalid[recipeOffset+116u]=0x00u;
            invalid[recipeOffset+117u]=0x00u;
            invalid[recipeOffset+118u]=0xc8u;
            invalid[recipeOffset+119u]=0x42u;
            expectLoadFailureContaining(
                invalid,substrate.seed,scene,polar,
                "interval is outside the Movement profile",
                "out-of-profile Glow interval reached content-address validation"
            );
            invalid=populationBytes;
            const auto glowMeaningHashOffset=32u+5u*16u+8u;
            invalid[glowMeaningHashOffset]^=1u;
            expectLoadFailure(invalid,substrate.seed,scene,polar,
                "changed Glow operator meaning hash was accepted");
            const auto vectorCount=runGlowVectors(
                expectedBytes,nodes,polar,populations
            );
            check(vectorCount==6u,"native Glow canonical vector count changed");
            runGrowCopiesV4(
                populationBytes,nodes,scene,polar,substrate.seed,populations
            );
            return 0;
        }

        if (expectedBytes.size()>=8u &&
            std::memcmp(expectedBytes.data(),"KPBV392\0",8)==0) {
            const auto vectorCount=runBurstVectors(
                expectedBytes,nodes,polar,populations
            );
            std::cout<<"PASS native KCPR392 Burst vectors="<<vectorCount
                <<" generated="<<populations.generatedCount()<<'\n';
            return 0;
        }

        ExpectedReader expected(expectedBytes);
        check(std::memcmp(expected.raw(8),"KPXV392\0",8)==0,
            "expected vector magic changed");
        check(expected.u32()==1u,"expected vector version changed");
        const auto dt=expected.f32();
        const auto recipeCount=expected.u32();
        const auto generatedCount=expected.u32();
        const auto totalCount=expected.u32();
        const auto rootSeed=expected.u64();
        const auto vectorCount=expected.u32();
        check(populations.recipeCount()==recipeCount,"native recipe count mismatch");
        check(populations.recipes().size()==recipeCount,
            "resident metadata is not recipe-bounded");
        check(populations.generatedCount()==generatedCount,"native generated count mismatch");
        check(populations.totalInstanceCount()==totalCount,"native total count mismatch");
        check(populations.rootSeed()==rootSeed,"native root seed mismatch");
        check(populations.formatVersion()==1u,"legacy KCPR fixture version changed");
        check(nodes.size()==scene.nodes.size(),"polar recipes created ECS NodeData rows");
        for (std::size_t recipeIndex=0;recipeIndex<recipeCount;++recipeIndex)
            check(populations.copiesVisible(recipeIndex),
                "loaded recipe copies were not initially visible");

        polar.tick(dt,nodes);
        populations.beginFrame();
        std::vector<std::uint32_t> testedIndices;
        testedIndices.reserve(vectorCount);
        for (std::uint32_t vectorIndex=0;vectorIndex<vectorCount;++vectorIndex) {
            const auto generatedIndex=expected.u32();
            testedIndices.push_back(generatedIndex);
            const auto copy=populations.materialize(
                generatedIndex,polar,nodes,true
            );
            check(copy.generatedIndex==generatedIndex,"generated index vector mismatch");
            check(copy.recipeIndex==expected.u32(),"recipe index vector mismatch");
            check(copy.prototypeSceneNode==expected.u32(),"prototype vector mismatch");
            check(copy.instanceIndex==expected.u32(),"instance index vector mismatch");
            check(copy.profile==expected.u16(),"profile vector mismatch");
            check(expected.u16()==0u,"expected vector reserved field changed");
            check(copy.lineage==expected.u64(),"lineage vector mismatch");
            check(copy.previousPose==expected.u64(),"previous pose vector mismatch");
            check(copy.pose==expected.u64(),"current pose vector mismatch");
            check(copy.motion==expected.u64(),"motion vector mismatch");
            const float actual[]={
                copy.node.translation.x,copy.node.translation.y,copy.node.translation.z,
                copy.node.rotation.w,copy.node.rotation.x,copy.node.rotation.y,copy.node.rotation.z,
                copy.node.scale.x,copy.node.scale.y,copy.node.scale.z,
                copy.node.velocity.x,copy.node.velocity.y,copy.node.velocity.z,
            };
            for (std::size_t field=0;field<13u;++field) {
                const auto wanted=expected.f32();
                const auto exact=field==1u||(field>=7u&&field<=9u)||field==11u;
                near(actual[field],wanted,exact?0.0f:2.0e-5f,
                    "generated Cartesian vector mismatch");
            }
        }
        check(expected.done(),"expected vector has trailing bytes");
        check(populations.lastMaterializedCount()==vectorCount,
            "visible-prefix materialization count changed");
        check(populations.lastCartesianComposeCount()==vectorCount,
            "CPU visible-prefix Cartesian compose count changed");
        if (totalCount==16384u) {
            check(recipeCount<=64u && populations.recipes().size()==recipeCount,
                "16K fixture retained metadata beyond its bounded recipes");
            check(vectorCount<=64u,
                "16K recipe fixture composed more than maxVisible=64 copies");
        }
        populations.beginFrame();
        for (const auto generatedIndex:testedIndices)
            static_cast<void>(populations.materialize(
                generatedIndex,polar,nodes,false
            ));
        check(populations.lastMaterializedCount()==vectorCount,
            "GPU visible-prefix pose materialization count changed");
        check(populations.lastCartesianComposeCount()==0u,
            "GPU Direct/LUT path performed CPU Cartesian composition");
        auto negativeZeroNodes=nodes;
        const auto firstPrototype=populations.recipes().front().prototypeSceneNode;
        negativeZeroNodes[firstPrototype].velocity.y=-0.0f;
        const auto canonicalZeroCopy=populations.materialize(
            populations.recipes().front().firstGenerated,
            polar,negativeZeroNodes,false
        );
        check(canonicalZeroCopy.node.velocity.y==0.0f &&
            !std::signbit(canonicalZeroCopy.node.velocity.y),
            "generated prototype Y velocity retained negative zero");

        expectLoadFailure(
            populationBytes,substrate.seed+1u,scene,polar,
            "root-seed mismatch was accepted"
        );
        auto truncated=populationBytes;
        truncated.pop_back();
        expectLoadFailure(truncated,substrate.seed,scene,polar,"truncated KCPR was accepted");
        auto trailing=populationBytes;
        trailing.push_back(0u);
        expectLoadFailure(trailing,substrate.seed,scene,polar,"trailing KCPR was accepted");
        auto corrupt=populationBytes;
        const auto operatorCount=static_cast<std::size_t>(corrupt[16])|
            (static_cast<std::size_t>(corrupt[17])<<8);
        const auto recipeOffset=32u+operatorCount*16u;
        check(recipeOffset+128u<=corrupt.size(),"test recipe offset is invalid");
        corrupt[recipeOffset+20u]^=1u;
        expectLoadFailure(corrupt,substrate.seed,scene,polar,
            "corrupt KCPR content address was accepted");
        corrupt=populationBytes;
        corrupt[recipeOffset+52u]^=1u;
        expectLoadFailure(corrupt,substrate.seed,scene,polar,
            "stale KCPK profile dependency was accepted");
        corrupt=populationBytes;
        corrupt[recipeOffset+68u]^=1u;
        expectLoadFailure(corrupt,substrate.seed,scene,polar,
            "stale KC3D prototype dependency was accepted");
        auto legacyInV2=populationBytes;
        legacyInV2[12u]=2u;
        expectLoadFailure(legacyInV2,substrate.seed,scene,polar,
            "KCPR v2 accepted an asset without a Burst recipe");
        auto unsupportedVersion=populationBytes;
        unsupportedVersion[12u]=3u;
        expectLoadFailure(unsupportedVersion,substrate.seed,scene,polar,
            "unsupported KCPR version was accepted");
        auto burstInV1=populationBytes;
        burstInV1[recipeOffset+4u]=4u;
        burstInV1[recipeOffset+5u]=0u;
        expectLoadFailure(burstInV1,substrate.seed,scene,polar,
            "KCPR v1 accepted the Burst preset");

        check(kc::allRenderRecipeCopiesVisible(0u)==0u,
            "zero render recipes did not initialize to an empty mask");
        check(kc::allRenderRecipeCopiesVisible(65u)==0u,
            "over-limit render recipes did not fail closed");
        auto fullMask=kc::allRenderRecipeCopiesVisible(64u);
        check(fullMask==std::numeric_limits<std::uint64_t>::max(),
            "64 render recipes did not initialize all visibility bits safely");
        check(kc::renderRecipeCopiesVisible(fullMask,64u,0u) &&
            kc::renderRecipeCopiesVisible(fullMask,64u,63u),
            "render recipe visibility lost bit zero or bit 63");
        check(kc::setRenderRecipeCopiesVisible(fullMask,64u,0u,false) &&
            kc::setRenderRecipeCopiesVisible(fullMask,64u,63u,false),
            "render recipe visibility could not clear an edge bit");
        check(!kc::renderRecipeCopiesVisible(fullMask,64u,0u) &&
            !kc::renderRecipeCopiesVisible(fullMask,64u,63u),
            "render recipe visibility retained a cleared edge bit");
        const auto boundedMask=fullMask;
        check(!kc::setRenderRecipeCopiesVisible(fullMask,64u,64u,true) &&
            fullMask==boundedMask,
            "out-of-range render recipe visibility changed the mask");

        kc::PolarPopulations emptyPopulations;
        check(!emptyPopulations.copiesVisible(0u) &&
            !emptyPopulations.setCopiesVisible(0u,false),
            "an empty population exposed mutable render recipe state");

        const auto firstRecipeNode=populations.recipes().front().prototypeSceneNode;
        check(populations.setCopiesVisible(firstRecipeNode,false) &&
            !populations.copiesVisible(0u),
            "prototype scene node did not map to its render recipe bit");
        check(!populations.setCopiesVisible(
                static_cast<std::uint32_t>(nodes.size()),false) &&
            !populations.copiesVisible(0u),
            "invalid prototype target changed render recipe state");
        for (const auto& recipe:populations.recipes())
            check(populations.setCopiesVisible(recipe.prototypeSceneNode,false),
                "could not hide a loaded render recipe");
        populations.beginFrame();
        std::uint32_t visibleBudget=5u;
        constexpr std::uint32_t MaxVisible=17u;
        for (std::size_t recipeIndex=0;
                recipeIndex<populations.recipes().size() && visibleBudget<MaxVisible;
                ++recipeIndex) {
            if (!populations.copiesVisible(recipeIndex)) continue;
            const auto& recipe=populations.recipes()[recipeIndex];
            for (std::uint32_t local=0;
                    local<recipe.generatedCount && visibleBudget<MaxVisible;++local) {
                static_cast<void>(populations.materialize(
                    static_cast<std::size_t>(recipe.firstGenerated)+local,
                    polar,nodes,false
                ));
                ++visibleBudget;
            }
        }
        check(visibleBudget==5u && populations.lastMaterializedCount()==0u,
            "hidden recipes consumed visible budget or materialized copies");
        for (const auto& recipe:populations.recipes())
            check(populations.setCopiesVisible(recipe.prototypeSceneNode,true),
                "could not restore a loaded render recipe");

        kc::GraphVm missingBridge;
        missingBridge.load(renderRecipeGraph(firstRecipeNode,{{0u,1u}}),nodes.size());
        missingBridge.ready(nodes);
        check(missingBridge.issues().size()==1u &&
            missingBridge.issues()[0].code==kc::GraphVmError::MissingRenderRecipeAccess,
            "missing Make Many bridge did not report its explicit safe error");
        check(populations.copiesVisible(0u),
            "missing Make Many bridge changed render recipe state");
        check(std::string_view(kc::graphVmErrorName(
                kc::GraphVmError::MissingRenderRecipeAccess)).find("Make Many runtime")!=
                std::string_view::npos,
            "missing Make Many bridge error was not child-readable");

        kc::GraphVm readyHide;
        readyHide.load(renderRecipeGraph(firstRecipeNode,{{0u,1u}}),nodes.size());
        readyHide.setRenderRecipeAccess(&populations);
        check(readyHide.hasRenderRecipeAccess(),
            "Make Many graph bridge was not connected");
        readyHide.ready(nodes);
        check(readyHide.issues().empty() && !populations.copiesVisible(0u),
            "Ready did not hide extra copies before the first frame");
        check(populations.setCopiesVisible(firstRecipeNode,true),
            "could not restore recipe after Ready test");

        std::uint32_t nonRecipeNode=0u;
        while (nonRecipeNode<nodes.size()) {
            bool isRecipe=false;
            for (const auto& recipe:populations.recipes())
                isRecipe=isRecipe || recipe.prototypeSceneNode==nonRecipeNode;
            if (!isRecipe) break;
            ++nonRecipeNode;
        }
        check(nonRecipeNode<nodes.size(),"fixture has no non-recipe scene node");
        kc::GraphVm invalidTarget;
        invalidTarget.load(renderRecipeGraph(nonRecipeNode,{{0u,1u}}),nodes.size());
        invalidTarget.setRenderRecipeAccess(&populations);
        invalidTarget.ready(nodes);
        check(invalidTarget.issues().size()==1u &&
            invalidTarget.issues()[0].code==kc::GraphVmError::InvalidRenderRecipeTarget,
            "non-recipe target did not report its explicit safe error");
        check(populations.copiesVisible(0u),
            "non-recipe target changed another recipe bit");

        kc::GraphVm flowGraph;
        flowGraph.load(renderRecipeGraph(
            firstRecipeNode,{{0u,1u},{0u,2u}}
        ),nodes.size());
        flowGraph.setRenderRecipeAccess(&populations);
        flowGraph.ready(nodes);
        check(flowGraph.issues().empty() && populations.copiesVisible(0u),
            "Show or Hide Extra Copies did not continue through its flow output");

        constexpr std::uint32_t LinkedReadyEntity=0x40000000u;
        constexpr std::uint32_t LinkedFirstActionOutput=0x40000001u;
        expectGraphLoadFailure(
            renderRecipeGraph(firstRecipeNode,{{LinkedReadyEntity,1u}}),nodes.size(),
            "linked entity target escaped the literal-only opcode 30 contract"
        );
        expectGraphLoadFailure(
            renderRecipeGraph(firstRecipeNode,{{1u,1u}}),nodes.size(),
            "non-string/null literal target escaped opcode 30 validation"
        );
        expectGraphLoadFailure(
            renderRecipeGraph(firstRecipeNode,{{0u,0u}}),nodes.size(),
            "non-Boolean literal visibility escaped opcode 30 validation"
        );
        expectGraphLoadFailure(
            renderRecipeGraph(
                firstRecipeNode,{{0u,1u},{0u,LinkedFirstActionOutput}}
            ),nodes.size(),
            "opcode 30 incorrectly exposed a pure data output"
        );

        const auto rendererBytes=readBytes(UGTS_RENDERER_SOURCE_PATH);
        const std::string rendererSource(rendererBytes.begin(),rendererBytes.end());
        const std::string_view guard=
            "if (!polarPopulations.copiesVisible(recipeIndex)) continue;";
        const auto guardPosition=rendererSource.find(guard);
        check(guardPosition!=std::string::npos,
            "renderer lost the common render recipe visibility guard");
        check(rendererSource.find(guard,guardPosition+guard.size())==std::string::npos,
            "CPU and GPU paths grew divergent render recipe visibility guards");
        const auto prototypePosition=rendererSource.find(
            "const auto& recipe=populationRecipes[recipeIndex];",guardPosition
        );
        const auto materializePosition=rendererSource.find(
            "polarPopulations.materialize(",guardPosition
        );
        const auto budgetPosition=rendererSource.find("++drawn;",guardPosition);
        check(prototypePosition!=std::string::npos &&
            materializePosition!=std::string::npos &&
            budgetPosition!=std::string::npos &&
            guardPosition<prototypePosition && guardPosition<materializePosition &&
            guardPosition<budgetPosition,
            "hidden recipe guard runs after prototype, materialization, or budget consumption");
        check(rendererSource.find(
                "std::uint32_t remainingBurstBudget=particleBudget;")!=
                std::string::npos &&
            rendererSource.find(
                "recipe.preset!=4u || remainingBurstBudget>0u")!=
                std::string::npos &&
            rendererSource.find(
                "if (recipe.preset==4u) --remainingBurstBudget;")!=
                std::string::npos,
            "renderer lost the shared remaining particle budget for Burst");
        check(rendererSource.find(
                "copyIndex,polarKinematics,nodes,fixedTick,false")!=
                std::string::npos &&
            rendererSource.find(
                "copyIndex,polarKinematics,nodes,fixedTick,true")!=
                std::string::npos,
            "renderer did not materialize Burst from the authoritative fixed tick");
        const auto burstBatchPosition=rendererSource.find(
            "group.burstRecipeIndex=static_cast<std::uint16_t>(recipeIndex);"
        );
        const auto burstBatchPushPosition=rendererSource.find(
            "polarGroups_.push_back(std::move(group));",burstBatchPosition
        );
        const auto burstBatchContinuePosition=rendererSource.find(
            "continue;",burstBatchPushPosition
        );
        check(burstBatchPosition!=std::string::npos &&
            burstBatchPushPosition!=std::string::npos &&
            burstBatchContinuePosition!=std::string::npos,
            "renderer lost one dedicated GPU batch per Burst recipe");

        const auto shaderBytes=readBytes(UGTS_POLAR_SHADER_SOURCE_PATH);
        const std::string shaderSource(shaderBytes.begin(),shaderBytes.end());
        check(shaderSource.find("uniform uvec4 uBurstAnchorPose;")!=
                std::string::npos &&
            shaderSource.find("uniform vec4 uBurstRecipe;")!=
                std::string::npos &&
            shaderSource.find("uniform vec3 uBurstScale;")!=
                std::string::npos,
            "polar shader lost its bounded per-recipe Burst uniforms");
        check(shaderSource.find(
                "vec4 sampleValue=lutSample(rho,theta);")!=
                std::string::npos &&
            shaderSource.find(
                "vec4 anchorSample=lutSample(anchorRho,anchorTheta);")!=
                std::string::npos &&
            shaderSource.find(
                "anchorHeadingDirection=lutSample(uPolarProfile.x,anchorHeading).xy;")!=
                std::string::npos,
            "shared-LUT mode no longer decodes local, anchor, and heading directions");
        check(shaderSource.find(
                "(previousAnchorHeading+previousHeading)&0x0fffu;")!=
                std::string::npos &&
            shaderSource.find(
                "(currentAnchorHeading+currentHeading)&0x0fffu;")!=
                std::string::npos &&
            shaderSource.find(
                "previousCombinedHeading,currentCombinedHeading,4096.0,alpha")!=
                std::string::npos,
            "polar shader lost packed-code Burst facing composition");
        check(shaderSource.find(
                "burstEnvelope=(4.0*age)*(1.0-age);")!=
                std::string::npos &&
            shaderSource.find(
                "float displayScale=aBaseYScale.y*burstEnvelope;")!=
                std::string::npos &&
            shaderSource.find(
                "instanceScale=uBurstScale*displayScale;")!=
                std::string::npos,
            "polar shader lost the Burst envelope/scale schedule");

        const auto engineBytes=readBytes(UGTS_ENGINE_SOURCE_PATH);
        const std::string engineSource(engineBytes.begin(),engineBytes.end());
        const auto populationLoadPosition=engineSource.find("polarPopulations_.load(");
        const auto bridgePosition=engineSource.find(
            "graphVm_.setRenderRecipeAccess(&polarPopulations_);"
        );
        const auto readyPosition=engineSource.find("graphVm_.ready(nodes_);");
        check(populationLoadPosition!=std::string::npos &&
            bridgePosition!=std::string::npos && readyPosition!=std::string::npos &&
            populationLoadPosition<bridgePosition && bridgePosition<readyPosition,
            "engine did not connect loaded render recipes before Ready");
        check(engineSource.find(
                "remainingParticleBudget=particles_.size()>=tuning_.particleBudget")!=
                std::string::npos &&
            engineSource.find(
                "quality.maxVisibleNodes,remainingParticleBudget,fixedTick_,time_")!=
                std::string::npos,
            "engine did not pass remaining particles, visibility, and fixed tick together");

        std::cout<<"PASS native KCPR392 polar populations generated="
            <<generatedCount<<" tested="<<vectorCount<<" ecs_nodes="
            <<nodes.size()<<'\n';
        return 0;
    } catch (const std::exception& error) {
        std::cerr<<"FAIL polar population: "<<error.what()<<'\n';
        return 1;
    }
}
