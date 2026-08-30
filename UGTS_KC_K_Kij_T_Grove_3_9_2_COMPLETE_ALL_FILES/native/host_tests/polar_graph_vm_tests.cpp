#include "graph_vm.hpp"
#include "polar_kinematics.hpp"
#include "transform_hierarchy.hpp"

#include <array>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string_view>
#include <vector>

namespace {

constexpr std::array<std::string_view,7> Fields{
    "radius","angle_degrees","facing_degrees","turns_per_second",
    "growth_per_second","turn_acceleration","growth_acceleration",
};

std::vector<std::uint8_t> readBytes(const char* path) {
    std::ifstream stream(path,std::ios::binary);
    if (!stream) throw std::runtime_error("could not open test asset");
    std::vector<std::uint8_t> result;
    for (char value=0;stream.get(value);)
        result.push_back(static_cast<std::uint8_t>(static_cast<unsigned char>(value)));
    return result;
}

void check(bool condition,std::string_view message) {
    if (!condition) throw std::runtime_error(std::string(message));
}

void near(float actual,float expected,float tolerance,std::string_view message) {
    check(std::isfinite(actual) && std::abs(actual-expected)<=tolerance,message);
}

void appendU32(std::vector<std::uint8_t>& bytes,std::uint32_t value) {
    for (unsigned index=0;index<4;++index)
        bytes.push_back(static_cast<std::uint8_t>(value>>(index*8)));
}

std::vector<std::uint8_t> hierarchyPack(std::uint32_t child,std::uint32_t parent) {
    const char magic[8]={'K','C','H','I','3','9','2','\0'};
    std::vector<std::uint8_t> bytes(magic,magic+8);
    appendU32(bytes,0x01020304u);
    appendU32(bytes,1u);
    appendU32(bytes,1u);
    appendU32(bytes,0u);
    appendU32(bytes,child);
    appendU32(bytes,parent);
    return bytes;
}

float read(const kc::PackedPolarKinematics& polar,std::uint32_t node,std::string_view field) {
    float value=0.0f;
    check(polar.readGraphNumber(node,"polar_movement",field,value),"polar read failed");
    return value;
}

} // namespace

int main(int argc,char** argv) {
    if (argc!=5) {
        std::cerr<<"FAIL polar graph VM: expected KCPK, KCVG, conflict KCVG, and Player KCPK paths\n";
        return 1;
    }
    try {
        std::vector<kc::NodeData> nodes(3);
        nodes[0].id="floor";
        nodes[1].id="player"; nodes[1].dynamic=true; nodes[1].tagMask=kc::TagPlayer;
        nodes[2].id="goal"; nodes[2].translation.y=1.25f; nodes[2].velocity.y=2.5f;

        kc::PackedPolarKinematics polar;
        polar.load(readBytes(argv[1]),nodes);
        check(polar.profileCount()==1 && polar.componentCount()==1,"sparse polar counts changed");
        const auto& profile=polar.profiles().front();
        check(profile.sine.size()>=4 && profile.sine.size()%4u==0u &&
            profile.cosine.size()==profile.sine.size(),"polar direction LUT shape changed");
        const auto quarter=profile.sine.size()/4u;
        near(profile.cosine[0],1.0f,0.001f,"theta zero LUT X no longer matches cos(theta)");
        near(profile.sine[0],0.0f,0.001f,"theta zero LUT Z no longer matches sin(theta)");
        near(profile.cosine[quarter],0.0f,0.001f,
            "quarter-turn LUT X no longer matches cos(theta)");
        near(profile.sine[quarter],1.0f,0.001f,
            "quarter-turn LUT Z no longer matches sin(theta)");
        check(profile.cosineHalf[0]==0x3c00u && profile.sineHalf[0]==0x0000u,
            "theta zero authored half lanes changed");
        check(profile.cosineHalf[quarter]==0x0000u && profile.sineHalf[quarter]==0x3c00u,
            "quarter-turn authored half lanes changed");
        check(profile.radiusScale>1.0f,"non-unit UGLUT2 radius scale fixture changed");
        check(static_cast<double>(profile.radiusScale)!=profile.authoredRadiusScale,
            "radius-scale fixture unexpectedly became binary32 exact");
        check(profile.normalizedRadiusHalf.size()==profile.sine.size(),
            "authored radius half lanes were not retained");
        for (std::size_t index=0;index<profile.radii.size();++index)
            near(profile.radii[index],profile.normalizedRadii[index]*profile.radiusScale,0.0f,
                "CPU radius did not use the GPU binary32 radius scale");
        for (const auto field:{"translation.x","translation.z","translation.0","translation.2",
                "position.x","position.z","position.0","position.2","rotation","rotation.0"})
            check(polar.rejectsGraphWrite(2,"transform",field),
                "packed transform ownership conflict was not rejected");
        for (const auto field:{"","x","z","0","2"})
            check(polar.rejectsGraphWrite(2,"velocity",field),
                "packed Cartesian velocity ownership conflict was not rejected");
        check(polar.rejectsGraphWrite(2,"angular_velocity",""),
            "packed angular velocity ownership conflict was not rejected");
        for (const auto field:{"translation.y","translation.1","position.y","position.1","scale"})
            check(!polar.rejectsGraphWrite(2,"transform",field),
                "packed movement rejected an ordinary Y/scale transform write");
        check(!polar.rejectsGraphWrite(2,"velocity","y")&&
            !polar.rejectsGraphWrite(2,"velocity","1"),
            "packed movement rejected an ordinary vertical velocity write");
        polar.compose(nodes);

        kc::GraphVm vm;
        vm.load(readBytes(argv[2]),nodes.size());
        vm.setNumberComponentAccess(&polar);
        check(vm.hasNumberComponentAccess(),"graph component bridge was not wired");
        vm.ready(nodes);
        check(vm.issues().empty(),"valid polar graph reported a runtime issue");

        const std::array<float,7> tolerances{0.01f,0.002f,0.09f,2.0e-5f,1.0e-4f,3.0e-5f,2.0e-4f};
        const std::array<float,7> wrapped{4.0f,90.0f,270.0f,0.5f,-0.4f,0.3f,-0.7f};
        std::array<float,7> afterGraph{};
        for (std::size_t index=0;index<Fields.size();++index) {
            afterGraph[index]=read(polar,2,Fields[index]);
            if (!std::isfinite(afterGraph[index]) ||
                std::abs(afterGraph[index]-wrapped[index])>tolerances[index]) {
                std::cerr<<"polar mismatch field="<<Fields[index]<<" actual="
                    <<afterGraph[index]<<" expected="<<wrapped[index]<<'\n';
                check(false,"graph polar field did not round-trip");
            }
        }
        near(nodes[0].translation.y,afterGraph[0],0.0f,"value.component did not use the polar bridge");
        near(nodes[2].translation.y,1.25f,0.0f,"polar composition overwrote authored Y");
        const float omega=afterGraph[3]*6.2831853071795864769f;
        const float radialX=nodes[2].translation.x/afterGraph[0];
        const float radialZ=nodes[2].translation.z/afterGraph[0];
        near(nodes[2].velocity.x,
            afterGraph[0]*(afterGraph[4]*radialX-omega*radialZ),0.002f,
            "polar composition did not publish Cartesian X velocity");
        near(nodes[2].velocity.z,
            afterGraph[0]*(afterGraph[4]*radialZ+omega*radialX),0.002f,
            "polar composition did not publish Cartesian Z velocity");
        near(nodes[2].velocity.y,2.5f,0.0f,"polar composition overwrote authored Y velocity");

        check(polar.writeGraphNumber(2,"polar_movement","angle_degrees",180.0f,nodes),
            "direct semantic write failed");
        for (std::size_t index=0;index<Fields.size();++index) {
            if (index==1) continue;
            near(read(polar,2,Fields[index]),afterGraph[index],0.0f,
                "one-field write changed another packed field");
        }
        near(nodes[2].translation.x,-read(polar,2,"radius"),0.01f,
            "semantic write did not compose X immediately");
        near(nodes[2].translation.z,0.0f,0.01f,
            "semantic write did not compose Z immediately");

        check(polar.writeGraphNumber(2,"polar_movement","angle_degrees",0.0f,nodes),
            "theta-zero semantic write failed");
        near(nodes[2].translation.x,read(polar,2,"radius"),0.01f,
            "CPU theta zero X no longer matches direct cos(theta)");
        near(nodes[2].translation.z,0.0f,0.01f,
            "CPU theta zero Z no longer matches direct sin(theta)");
        check(polar.writeGraphNumber(2,"polar_movement","angle_degrees",90.0f,nodes),
            "quarter-turn semantic write failed");
        near(nodes[2].translation.x,0.0f,0.01f,
            "CPU quarter-turn X no longer matches direct cos(theta)");
        near(nodes[2].translation.z,read(polar,2,"radius"),0.01f,
            "CPU quarter-turn Z no longer matches direct sin(theta)");
        check(polar.writeGraphNumber(2,"polar_movement","angle_degrees",180.0f,nodes),
            "post-cardinal semantic restore failed");

        const auto stablePosition=nodes[2].translation;
        const auto stableRotation=nodes[2].rotation;
        check(!polar.writeGraphNumber(2,"polar_movement","radius",1.0e20f,nodes),
            "out-of-profile radius was accepted");
        check(!polar.writeGraphNumber(2,"polar_movement","turns_per_second",2.0f,nodes),
            "out-of-profile turn rate was accepted");
        check(!polar.writeGraphNumber(2,"polar_movement","radius",
            std::numeric_limits<float>::quiet_NaN(),nodes),"NaN was accepted");
        check(!polar.writeGraphNumber(2,"packed_kinematic","radius",3.0f,nodes),
            "storage component leaked into graph access");
        check(!polar.writeGraphNumber(2,"polar_movement","pose_word",3.0f,nodes),
            "packed field leaked into graph access");
        check(!polar.writeGraphNumber(1,"polar_movement","radius",3.0f,nodes),
            "missing sparse component was writable");
        near(nodes[2].translation.x,stablePosition.x,0.0f,"failed write changed position");
        near(nodes[2].rotation.w,stableRotation.w,0.0f,"failed write changed rotation");

        nodes[2].translation.x=123.0f;
        check(polar.writeGraphNumber(2,"polar_movement","radius",read(polar,2,"radius"),nodes),
            "no-op semantic write failed");
        near(nodes[2].translation.x,-read(polar,2,"radius"),0.01f,
            "no-op semantic write did not republish NodeData");

        kc::GraphVm conflictVm;
        conflictVm.load(readBytes(argv[3]),nodes.size());
        conflictVm.setNumberComponentAccess(&polar);
        conflictVm.ready(nodes);
        check(conflictVm.issues().size()==1,
            "conflicting generic packed transform write did not report one issue");
        check(conflictVm.issues()[0].code==kc::GraphVmError::PackedTransformOwnership,
            "conflicting generic packed transform write reported the wrong issue");
        check(std::string_view(kc::graphVmErrorName(conflictVm.issues()[0].code)).find(
                "packed polar owns X/Z")!=std::string_view::npos,
            "packed ownership issue was not child-readable");

        auto staticPlayerNodes=nodes;
        staticPlayerNodes[1].dynamic=false;
        try {
            kc::PackedPolarKinematics playerPolar;
            playerPolar.load(readBytes(argv[4]),staticPlayerNodes);
            check(false,"packed polar Player binding was accepted");
        } catch (const std::runtime_error& error) {
            check(std::string_view(error.what()).find("Player controller")!=std::string_view::npos,
                "packed polar Player binding reported the wrong ownership error");
        }

        nodes[0].translation={1.0f,2.0f,3.0f};
        nodes[0].rotation={1.0f,0.0f,0.0f,0.0f};
        nodes[0].scale={1.0f,1.0f,1.0f};
        kc::TransformHierarchy rootHierarchy;
        rootHierarchy.load(hierarchyPack(0,2),nodes);
        check(rootHierarchy.isLinked(2)&&!rootHierarchy.isChild(2),
            "packed hierarchy root was misclassified as a forbidden child");
        check(polar.writeGraphNumber(2,"polar_movement","angle_degrees",0.0f,nodes)&&
            polar.writeGraphNumber(2,"polar_movement","facing_degrees",0.0f,nodes),
            "packed hierarchy-root pose setup failed");
        rootHierarchy.compose(nodes);
        near(nodes[0].translation.x,read(polar,2,"radius")+1.0f,0.02f,
            "packed hierarchy root did not drive child X");
        near(nodes[0].translation.y,3.25f,0.001f,
            "packed hierarchy root did not preserve child-local Y");
        near(nodes[0].translation.z,3.0f,0.001f,
            "packed hierarchy root did not drive child Z");

        kc::TransformHierarchy childHierarchy;
        childHierarchy.load(hierarchyPack(2,0),nodes);
        check(childHierarchy.isChild(2),
            "forbidden packed hierarchy child escaped runtime ownership query");

        std::cout<<"PASS polar graph component bridge\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr<<"FAIL polar graph VM: "<<error.what()<<'\n';
        return 1;
    }
}
