#include "polar_kinematics.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

namespace {

constexpr double Tau=6.283185307179586476925286766559;

struct VectorCase {
    std::string name;
    double inputX=0.0,inputZ=0.0;
    bool core=false;
    std::uint64_t pose=0,motion=0,nextPose=0,nextMotion=0;
    float directX=0.0f,directZ=0.0f,lutX=0.0f,lutZ=0.0f;
    float directVelocityX=0.0f,directVelocityZ=0.0f;
    float lutVelocityX=0.0f,lutVelocityZ=0.0f;
    float directAccelerationX=0.0f,directAccelerationZ=0.0f;
    float lutAccelerationX=0.0f,lutAccelerationZ=0.0f;
    float headingW=1.0f,headingY=0.0f;
    float directHeadingCosine=1.0f,directHeadingSine=0.0f;
    float lutHeadingCosine=1.0f,lutHeadingSine=0.0f;
};

struct Artifact {
    std::unordered_map<std::string,std::string> metadata;
    std::vector<std::pair<std::string,std::string>> shaderSnippets;
    std::vector<VectorCase> cases;
};

void check(bool condition,std::string_view message) {
    if (!condition) throw std::runtime_error(std::string(message));
}

std::string readText(const char* path) {
    std::ifstream stream(path,std::ios::binary);
    if (!stream) throw std::runtime_error("could not open polar conformance text");
    return {
        std::istreambuf_iterator<char>(stream),
        std::istreambuf_iterator<char>()
    };
}

std::vector<std::uint8_t> readBytes(const char* path) {
    const auto text=readText(path);
    return {text.begin(),text.end()};
}

std::vector<std::string> splitTabs(std::string line) {
    if (!line.empty() && line.back()=='\r') line.pop_back();
    std::vector<std::string> fields;
    std::size_t first=0;
    while (true) {
        const auto tab=line.find('\t',first);
        fields.push_back(line.substr(first,tab-first));
        if (tab==std::string::npos) return fields;
        first=tab+1u;
    }
}

double number(std::string_view text) {
    std::size_t consumed=0;
    const auto value=std::stod(std::string(text),&consumed);
    check(consumed==text.size()&&std::isfinite(value),"invalid conformance number");
    return value;
}

std::uint64_t hexWord(std::string_view text) {
    std::size_t consumed=0;
    const auto value=std::stoull(std::string(text),&consumed,16);
    check(consumed==text.size()&&text.size()==16u,"invalid conformance word");
    return value;
}

std::string compact(std::string_view text) {
    std::string result;
    result.reserve(text.size());
    for (const auto character:text) {
        if (character!=' '&&character!='\t'&&character!='\r'&&character!='\n')
            result.push_back(character);
    }
    return result;
}

Artifact readArtifact(const char* path) {
    Artifact result;
    std::ifstream stream(path);
    if (!stream) throw std::runtime_error("could not open polar conformance vectors");
    std::unordered_map<std::string,std::size_t> columns;
    std::string line;
    while (std::getline(stream,line)) {
        const auto fields=splitTabs(line);
        if (fields.empty()||fields[0].empty()||fields[0][0]=='#') continue;
        if (fields[0]=="meta") {
            check(fields.size()==3u,"malformed conformance metadata");
            check(result.metadata.emplace(fields[1],fields[2]).second,
                "duplicate conformance metadata");
            continue;
        }
        if (fields[0]=="shader") {
            check(fields.size()==3u,"malformed conformance shader contract");
            result.shaderSnippets.emplace_back(fields[1],fields[2]);
            continue;
        }
        if (fields[0]=="columns") {
            check(fields.size()>3u&&fields[1]=="case","malformed conformance columns");
            for (std::size_t index=2;index<fields.size();++index)
                check(columns.emplace(fields[index],index-1u).second,
                    "duplicate conformance column");
            continue;
        }
        check(fields[0]=="case"&&!columns.empty(),"unknown conformance record");
        const auto get=[&](std::string_view name)->const std::string& {
            const auto found=columns.find(std::string(name));
            check(found!=columns.end()&&found->second<fields.size(),
                "missing conformance case field");
            return fields[found->second];
        };
        VectorCase item;
        item.name=get("name");
        item.inputX=number(get("input_x")); item.inputZ=number(get("input_z"));
        check(get("core")=="true"||get("core")=="false","invalid core flag");
        item.core=get("core")=="true";
        item.pose=hexWord(get("pose_word")); item.motion=hexWord(get("motion_word"));
        item.nextPose=hexWord(get("next_pose_word"));
        item.nextMotion=hexWord(get("next_motion_word"));
        item.directX=static_cast<float>(number(get("direct_x")));
        item.directZ=static_cast<float>(number(get("direct_z")));
        item.lutX=static_cast<float>(number(get("lut_x")));
        item.lutZ=static_cast<float>(number(get("lut_z")));
        item.directVelocityX=static_cast<float>(number(get("direct_velocity_x")));
        item.directVelocityZ=static_cast<float>(number(get("direct_velocity_z")));
        item.lutVelocityX=static_cast<float>(number(get("lut_velocity_x")));
        item.lutVelocityZ=static_cast<float>(number(get("lut_velocity_z")));
        item.directAccelerationX=static_cast<float>(number(get("direct_acceleration_x")));
        item.directAccelerationZ=static_cast<float>(number(get("direct_acceleration_z")));
        item.lutAccelerationX=static_cast<float>(number(get("lut_acceleration_x")));
        item.lutAccelerationZ=static_cast<float>(number(get("lut_acceleration_z")));
        item.headingW=static_cast<float>(number(get("heading_w")));
        item.headingY=static_cast<float>(number(get("heading_y")));
        item.directHeadingCosine=static_cast<float>(number(get("direct_heading_cos")));
        item.directHeadingSine=static_cast<float>(number(get("direct_heading_sin")));
        item.lutHeadingCosine=static_cast<float>(number(get("lut_heading_cos")));
        item.lutHeadingSine=static_cast<float>(number(get("lut_heading_sin")));
        result.cases.push_back(item);
    }
    check(result.metadata.at("schema")=="ugts-kc-polar-substrate-v1",
        "polar conformance schema changed");
    check(result.metadata.at("evidence")=="shader_source_formula_only_no_gpu_execution",
        "polar conformance evidence scope changed");
    check(std::stoul(result.metadata.at("case_count"))==result.cases.size(),
        "polar conformance case count changed");
    check(!result.shaderSnippets.empty()&&!result.cases.empty(),
        "polar conformance artifact is empty");
    return result;
}

void near(double actual,double expected,double tolerance,std::string_view message) {
    check(std::isfinite(actual)&&std::isfinite(expected)&&
        std::abs(actual-expected)<=tolerance,message);
}

double closed(std::uint32_t code,double minimum,double maximum,unsigned bits) {
    const auto maximumCode=static_cast<double>((std::uint64_t{1}<<bits)-1u);
    return minimum+(maximum-minimum)*static_cast<double>(code)/maximumCode;
}

double periodic(std::uint32_t code,unsigned bits) {
    return Tau*static_cast<double>(code)/static_cast<double>(std::uint64_t{1}<<bits);
}

double signedValue(std::uint16_t code,double maximum) {
    const auto value=(code&0x8000u)?static_cast<int>(code)-0x10000:static_cast<int>(code);
    return static_cast<double>(value)/32767.0*maximum;
}

std::uint32_t encodeClosed(double value,double minimum,double maximum,unsigned bits) {
    value=std::max(minimum,std::min(maximum,value));
    const auto maximumCode=(std::uint64_t{1}<<bits)-1u;
    return static_cast<std::uint32_t>(std::nearbyint(
        (value-minimum)/(maximum-minimum)*static_cast<double>(maximumCode)
    ));
}

std::uint32_t encodePeriodic(double value,unsigned bits) {
    value=std::fmod(value,Tau); if (value<0.0) value+=Tau;
    return static_cast<std::uint32_t>(std::floor(
        value/Tau*static_cast<double>(std::uint64_t{1}<<bits)
    ))&static_cast<std::uint32_t>((std::uint64_t{1}<<bits)-1u);
}

struct Decoded {
    double rho=0.0,theta=0.0,heading=0.0;
    double rhoVelocity=0.0,thetaVelocity=0.0;
    double rhoAcceleration=0.0,thetaAcceleration=0.0;
};

Decoded decode(
    const VectorCase& item,const kc::PackedPolarKinematics::Profile& profile
) {
    Decoded result;
    result.rho=closed(static_cast<std::uint32_t>(item.pose>>44),
        profile.rhoMin,profile.rhoMax,20);
    result.theta=periodic(static_cast<std::uint32_t>((item.pose>>26)&0x3ffffu),18);
    result.heading=periodic(static_cast<std::uint32_t>(item.pose&0xfffu),12);
    result.rhoVelocity=signedValue(static_cast<std::uint16_t>(item.motion>>48),
        profile.rhoVelocity);
    result.thetaVelocity=signedValue(static_cast<std::uint16_t>(item.motion>>32),
        profile.thetaVelocity);
    result.rhoAcceleration=signedValue(static_cast<std::uint16_t>(item.motion>>16),
        profile.rhoAcceleration);
    result.thetaAcceleration=signedValue(static_cast<std::uint16_t>(item.motion),
        profile.thetaAcceleration);
    return result;
}

struct State {
    double x=0.0,z=0.0,velocityX=0.0,velocityZ=0.0;
    double accelerationX=0.0,accelerationZ=0.0;
};

State state(const Decoded& value,double radius,double sine,double cosine) {
    State result;
    result.x=radius*cosine; result.z=radius*sine;
    result.velocityX=radius*(value.rhoVelocity*cosine-value.thetaVelocity*sine);
    result.velocityZ=radius*(value.rhoVelocity*sine+value.thetaVelocity*cosine);
    const auto radial=value.rhoAcceleration+value.rhoVelocity*value.rhoVelocity-
        value.thetaVelocity*value.thetaVelocity;
    const auto tangent=value.thetaAcceleration+
        2.0*value.rhoVelocity*value.thetaVelocity;
    result.accelerationX=radius*(radial*cosine-tangent*sine);
    result.accelerationZ=radius*(radial*sine+tangent*cosine);
    return result;
}

std::pair<double,double> lutDirection(
    const kc::PackedPolarKinematics::Profile& profile,double theta
) {
    const auto count=profile.sine.size();
    const auto coordinate=theta*static_cast<double>(count)/Tau;
    const auto low=static_cast<std::size_t>(std::floor(coordinate))%count;
    const auto high=(low+1u)%count;
    const auto fraction=coordinate-std::floor(coordinate);
    auto sine=profile.sine[low]+(profile.sine[high]-profile.sine[low])*fraction;
    auto cosine=profile.cosine[low]+(profile.cosine[high]-profile.cosine[low])*fraction;
    const auto length=std::hypot(sine,cosine);
    return {sine/length,cosine/length};
}

double lutRadius(const kc::PackedPolarKinematics::Profile& profile,double rho) {
    rho=std::max(profile.rhoMin,std::min(profile.rhoMax,rho));
    const auto count=profile.radii.size();
    const auto coordinate=(rho-profile.rhoMin)*static_cast<double>(count-1u)/
        (profile.rhoMax-profile.rhoMin);
    const auto low=static_cast<std::size_t>(std::floor(coordinate));
    const auto high=std::min(count-1u,low+1u);
    return profile.radii[low]+(profile.radii[high]-profile.radii[low])*
        (coordinate-static_cast<double>(low));
}

} // namespace

int main(int argc,char** argv) {
    if (argc!=4) {
        std::cerr<<"FAIL polar substrate conformance: expected TSV KCPK shader paths\n";
        return 1;
    }
    try {
        const auto artifact=readArtifact(argv[1]);
        const auto shader=compact(readText(argv[3]));
        for (const auto& [name,snippet]:artifact.shaderSnippets) {
            static_cast<void>(name);
            check(shader.find(compact(snippet))!=std::string::npos,
                "shader source formula diverged from canonical artifact");
        }

        const auto nodeBase=static_cast<std::uint32_t>(
            std::stoul(artifact.metadata.at("native_node_base"))
        );
        std::vector<kc::NodeData> nodes(nodeBase+artifact.cases.size());
        for (std::size_t index=0;index<artifact.cases.size();++index) {
            nodes[nodeBase+index].translation.y=static_cast<float>(index)+0.25f;
            nodes[nodeBase+index].velocity.y=-static_cast<float>(index)-0.5f;
        }
        kc::PackedPolarKinematics polar;
        polar.load(readBytes(argv[2]),nodes);
        check(polar.profileCount()==1u,"conformance KCPK profile count changed");
        check(polar.componentCount()==artifact.cases.size(),
            "conformance KCPK component count changed");
        const auto& profile=polar.profiles().front();
        const auto meta=[&](std::string_view name) {
            return number(artifact.metadata.at(std::string(name)));
        };
        near(profile.r0,meta("r0"),0.0,"profile r0 changed");
        near(profile.rhoMin,meta("rho_min"),0.0,"profile rho minimum changed");
        near(profile.rhoMax,meta("rho_max"),0.0,"profile rho maximum changed");
        near(profile.coreRadius,meta("core_radius"),0.0,"profile core changed");
        near(profile.rhoVelocity,meta("rho_velocity_limit"),0.0,
            "rho velocity range changed");
        near(profile.thetaVelocity,meta("theta_velocity_limit"),0.0,
            "theta velocity range changed");
        near(profile.rhoAcceleration,meta("rho_acceleration_limit"),0.0,
            "rho acceleration range changed");
        near(profile.thetaAcceleration,meta("theta_acceleration_limit"),0.0,
            "theta acceleration range changed");
        check(profile.sine.size()==static_cast<std::size_t>(
            std::stoul(artifact.metadata.at("lut_resolution"))
        ),"conformance LUT resolution changed");

        const auto tolerance=meta("binary32_tolerance");
        polar.compose(nodes);
        for (std::size_t index=0;index<artifact.cases.size();++index) {
            const auto& item=artifact.cases[index];
            const auto& component=polar.components()[index];
            check(component.sceneNode==nodeBase+index,"conformance scene-node index changed");
            check(component.pose==item.pose&&component.motion==item.motion,
                "conformance packed words changed");
            const auto decoded=decode(item,profile);

            const auto inputRadius=std::hypot(item.inputX,item.inputZ);
            const auto core=inputRadius<profile.coreRadius;
            check(core==item.core,"conformance core classification changed");
            const auto inputRho=core?profile.rhoMin:std::max(
                profile.rhoMin,std::min(profile.rhoMax,std::log(inputRadius/profile.r0))
            );
            const auto inputTheta=core?0.0:std::atan2(item.inputZ,item.inputX);
            check(encodeClosed(inputRho,profile.rhoMin,profile.rhoMax,20)==item.pose>>44,
                "conformance Cartesian rho encoding changed");
            check(encodePeriodic(inputTheta,18)==((item.pose>>26)&0x3ffffu),
                "conformance Cartesian theta encoding changed");

            const auto direct=state(
                decoded,profile.r0*std::exp(decoded.rho),
                std::sin(decoded.theta),std::cos(decoded.theta)
            );
            near(direct.x,item.directX,tolerance,"direct X vector changed");
            near(direct.z,item.directZ,tolerance,"direct Z vector changed");
            near(direct.velocityX,item.directVelocityX,tolerance,
                "direct velocity X vector changed");
            near(direct.velocityZ,item.directVelocityZ,tolerance,
                "direct velocity Z vector changed");
            near(direct.accelerationX,item.directAccelerationX,tolerance,
                "direct acceleration X vector changed");
            near(direct.accelerationZ,item.directAccelerationZ,tolerance,
                "direct acceleration Z vector changed");

            const auto [lutSine,lutCosine]=lutDirection(profile,decoded.theta);
            const auto lut=state(
                decoded,lutRadius(profile,decoded.rho),lutSine,lutCosine
            );
            near(lut.x,item.lutX,tolerance,"LUT X vector changed");
            near(lut.z,item.lutZ,tolerance,"LUT Z vector changed");
            near(lut.velocityX,item.lutVelocityX,tolerance,
                "LUT velocity X vector changed");
            near(lut.velocityZ,item.lutVelocityZ,tolerance,
                "LUT velocity Z vector changed");
            near(lut.accelerationX,item.lutAccelerationX,tolerance,
                "LUT acceleration X vector changed");
            near(lut.accelerationZ,item.lutAccelerationZ,tolerance,
                "LUT acceleration Z vector changed");

            const auto& node=nodes[nodeBase+index];
            near(node.translation.x,item.lutX,tolerance,"native compose X changed");
            near(node.translation.z,item.lutZ,tolerance,"native compose Z changed");
            near(node.velocity.x,item.lutVelocityX,tolerance,
                "native compose velocity X changed");
            near(node.velocity.z,item.lutVelocityZ,tolerance,
                "native compose velocity Z changed");
            near(node.translation.y,static_cast<double>(index)+0.25,0.0,
                "native compose changed authored Y");
            near(node.velocity.y,-static_cast<double>(index)-0.5,0.0,
                "native compose changed authored Y velocity");
            near(node.rotation.w,item.headingW,tolerance,"native heading W changed");
            near(node.rotation.y,item.headingY,tolerance,"native heading Y changed");
            near(std::cos(decoded.heading),item.directHeadingCosine,tolerance,
                "direct heading cosine changed");
            near(std::sin(decoded.heading),item.directHeadingSine,tolerance,
                "direct heading sine changed");
            const auto [headingSine,headingCosine]=lutDirection(profile,decoded.heading);
            near(headingCosine,item.lutHeadingCosine,tolerance,
                "LUT heading cosine changed");
            near(headingSine,item.lutHeadingSine,tolerance,
                "LUT heading sine changed");
            near(std::hypot(
                std::cos(decoded.heading)-headingCosine,
                std::sin(decoded.heading)-headingSine
            ),0.0,meta("maximum_direct_lut_heading_error"),
                "direct/LUT heading divergence exceeded contract");

            near(std::hypot(direct.x-lut.x,direct.z-lut.z),0.0,
                meta("maximum_direct_lut_position_error"),
                "direct/LUT position divergence exceeded contract");
            near(std::hypot(
                direct.velocityX-lut.velocityX,direct.velocityZ-lut.velocityZ
            ),0.0,meta("maximum_direct_lut_velocity_error"),
                "direct/LUT velocity divergence exceeded contract");
            near(std::hypot(
                direct.accelerationX-lut.accelerationX,
                direct.accelerationZ-lut.accelerationZ
            ),0.0,meta("maximum_direct_lut_acceleration_error"),
                "direct/LUT acceleration divergence exceeded contract");
        }

        polar.tick(static_cast<float>(meta("fixed_dt")),nodes);
        for (std::size_t index=0;index<artifact.cases.size();++index) {
            const auto& component=polar.components()[index];
            check(component.previousPose==artifact.cases[index].pose,
                "native previous pose changed");
            check(component.pose==artifact.cases[index].nextPose,
                "native derivative next pose changed");
            check(component.motion==artifact.cases[index].nextMotion,
                "native derivative next motion changed");
        }
        std::cout<<"PASS polar substrate conformance vectors="<<artifact.cases.size()
            <<" source_formula_only=true\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr<<"FAIL polar substrate conformance: "<<error.what()<<'\n';
        return 1;
    }
}
