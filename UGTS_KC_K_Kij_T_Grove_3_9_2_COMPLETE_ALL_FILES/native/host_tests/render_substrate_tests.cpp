#include "render_substrate.hpp"

#include <cmath>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

void check(bool condition,const std::string& message) {
    if (!condition) throw std::runtime_error(message);
}

void appendU16(std::vector<std::uint8_t>& bytes,std::uint16_t value) {
    bytes.push_back(static_cast<std::uint8_t>(value));
    bytes.push_back(static_cast<std::uint8_t>(value>>8));
}

void appendU32(std::vector<std::uint8_t>& bytes,std::uint32_t value) {
    for (unsigned index=0;index<4;++index)
        bytes.push_back(static_cast<std::uint8_t>(value>>(index*8)));
}

void appendU64(std::vector<std::uint8_t>& bytes,std::uint64_t value) {
    appendU32(bytes,static_cast<std::uint32_t>(value));
    appendU32(bytes,static_cast<std::uint32_t>(value>>32));
}

void appendF32(std::vector<std::uint8_t>& bytes,float value) {
    std::uint32_t bits=0;
    std::memcpy(&bits,&value,sizeof(bits));
    appendU32(bytes,bits);
}

std::vector<std::uint8_t> pack(
    std::uint8_t polar=0,std::uint8_t bayer=1,std::uint16_t levels=64,
    float strength=0.30f,std::uint64_t seed=0
) {
    const char magic[8]={'K','C','R','P','3','9','2','\0'};
    std::vector<std::uint8_t> bytes(magic,magic+8);
    appendU32(bytes,0x01020304u);
    appendU32(bytes,1u);
    bytes.push_back(polar);
    bytes.push_back(bayer);
    appendU16(bytes,levels);
    appendF32(bytes,strength);
    appendU64(bytes,seed);
    check(bytes.size()==32u,"test KCRP pack size changed");
    return bytes;
}

void writeU16(std::vector<std::uint8_t>& bytes,std::size_t offset,std::uint16_t value) {
    check(offset+2u<=bytes.size(),"test u16 mutation offset");
    bytes[offset]=static_cast<std::uint8_t>(value);
    bytes[offset+1u]=static_cast<std::uint8_t>(value>>8);
}

void writeU32(std::vector<std::uint8_t>& bytes,std::size_t offset,std::uint32_t value) {
    check(offset+4u<=bytes.size(),"test u32 mutation offset");
    for (unsigned index=0;index<4;++index)
        bytes[offset+index]=static_cast<std::uint8_t>(value>>(index*8));
}

void writeF32(std::vector<std::uint8_t>& bytes,std::size_t offset,float value) {
    std::uint32_t bits=0;
    std::memcpy(&bits,&value,sizeof(bits));
    writeU32(bytes,offset,bits);
}

std::vector<std::uint8_t> packV2(
    std::uint8_t materialMode=1u,std::uint8_t materialBands=8u,
    float materialStrength=0.75f,std::uint8_t polar=0u,
    std::uint8_t bayer=1u,std::uint16_t levels=64u,
    float strength=0.30f,std::uint64_t seed=0u
) {
    auto bytes=pack(polar,bayer,levels,strength,seed);
    writeU32(bytes,12u,2u);
    bytes.push_back(materialMode);
    bytes.push_back(materialBands);
    appendU16(bytes,0u);
    appendF32(bytes,materialStrength);
    check(bytes.size()==40u,"test KCRP v2 pack size changed");
    return bytes;
}

void expectFailure(const std::vector<std::uint8_t>& bytes,const std::string& fragment) {
    try {
        static_cast<void>(kc::parseRenderSubstrate(bytes));
    } catch (const std::runtime_error& error) {
        check(
            std::string(error.what()).find(fragment)!=std::string::npos,
            "unexpected KCRP rejection: "+std::string(error.what())
        );
        return;
    }
    throw std::runtime_error("invalid KCRP was accepted: "+fragment);
}

} // namespace

int main() {
    try {
        const auto absent=kc::parseRenderSubstrate({});
        check(!absent.present,"empty KCRP did not preserve legacy mode");
        check(absent.formatVersion==0u,"empty KCRP format version");
        check(absent.polarMode==kc::PolarRenderMode::Cpu,"empty KCRP polar mode");
        check(absent.bayerMode==kc::BayerRenderMode::Off,"empty KCRP Bayer mode");
        check(!absent.bayerEnabled(),"empty KCRP enabled Bayer");

        const auto configured=kc::parseRenderSubstrate(
            pack(1,3,256,0.125f,0xFEDCBA9876543210ull)
        );
        check(configured.present,"valid KCRP was not marked present");
        check(configured.formatVersion==1u,"valid v1 KCRP format version");
        check(configured.polarMode==kc::PolarRenderMode::Lut,"valid KCRP polar mode");
        check(configured.bayerMode==kc::BayerRenderMode::Custom,"valid KCRP Bayer mode");
        check(configured.levels==256u,"valid KCRP Bayer levels");
        check(configured.strength==0.125f,"valid KCRP Bayer strength");
        check(configured.seed==0xFEDCBA9876543210ull,"valid KCRP seed");
        check(configured.bayerEnabled(),"valid KCRP did not enable Bayer");
        check(
            configured.polarMaterialMode==kc::PolarMaterialMode::Off &&
                configured.polarMaterialBands==1u &&
                configured.polarMaterialStrength==0.0f &&
                !configured.polarMaterialEnabled(),
            "valid v1 KCRP did not preserve Polar Material defaults"
        );

        const auto material=kc::parseRenderSubstrate(packV2(
            1u,12u,0.625f,1u,3u,128u,0.25f,0x0123456789ABCDEFull
        ));
        check(material.present&&material.formatVersion==2u,
            "valid v2 KCRP version");
        check(material.polarMode==kc::PolarRenderMode::Lut &&
                material.bayerMode==kc::BayerRenderMode::Custom &&
                material.levels==128u && material.strength==0.25f &&
                material.seed==0x0123456789ABCDEFull,
            "valid v2 KCRP changed the frozen v1 prefix");
        check(material.polarMaterialMode==kc::PolarMaterialMode::Bands &&
                material.polarMaterialBands==12u &&
                material.polarMaterialStrength==0.625f &&
                material.polarMaterialEnabled(),
            "valid v2 KCRP Polar Material tail");

        check(std::string(kc::polarRenderModeName(kc::PolarRenderMode::Auto))=="auto","auto name");
        check(std::string(kc::polarRenderModeName(kc::PolarRenderMode::Lut))=="lut","lut name");
        check(std::string(kc::polarRenderModeName(kc::PolarRenderMode::Direct))=="direct","direct name");
        check(std::string(kc::polarRenderModeName(kc::PolarRenderMode::Cpu))=="cpu","cpu name");
        check(std::string(kc::bayerRenderModeName(kc::BayerRenderMode::Off))=="off","off name");
        check(std::string(kc::bayerRenderModeName(kc::BayerRenderMode::Subtle))=="subtle","subtle name");
        check(std::string(kc::bayerRenderModeName(kc::BayerRenderMode::Retro))=="retro","retro name");
        check(std::string(kc::bayerRenderModeName(kc::BayerRenderMode::Custom))=="custom","custom name");
        check(std::string(kc::polarMaterialModeName(kc::PolarMaterialMode::Off))=="off",
            "Polar Material off name");
        check(std::string(kc::polarMaterialModeName(kc::PolarMaterialMode::Bands))=="bands",
            "Polar Material bands name");
        check(
            std::string(kc::polarRenderModeName(static_cast<kc::PolarRenderMode>(255)))=="unknown",
            "unknown polar name"
        );
        check(
            std::string(kc::bayerRenderModeName(static_cast<kc::BayerRenderMode>(255)))=="unknown",
            "unknown Bayer name"
        );
        check(
            std::string(kc::polarMaterialModeName(
                static_cast<kc::PolarMaterialMode>(255)
            ))=="unknown",
            "unknown Polar Material name"
        );

        auto invalid=pack();
        expectFailure(std::vector<std::uint8_t>(invalid.begin(),invalid.end()-1),"truncated");
        invalid.push_back(0);
        expectFailure(invalid,"trailing bytes");

        invalid=pack(); invalid[0]^=0xFFu;
        expectFailure(invalid,"magic mismatch");
        invalid=pack(); writeU32(invalid,8,0u);
        expectFailure(invalid,"endian marker mismatch");
        invalid=pack(); writeU32(invalid,12,2u);
        expectFailure(invalid,"truncated");
        invalid=pack(); writeU32(invalid,12,3u);
        expectFailure(invalid,"unsupported KCRP");
        invalid=pack(); invalid[16]=4u;
        expectFailure(invalid,"polar render mode");
        invalid=pack(); invalid[17]=4u;
        expectFailure(invalid,"Bayer render mode");
        invalid=pack(); writeU16(invalid,18,1u);
        expectFailure(invalid,"Bayer levels");
        invalid=pack(); writeU16(invalid,18,257u);
        expectFailure(invalid,"Bayer levels");
        invalid=pack(); writeF32(invalid,20,std::numeric_limits<float>::quiet_NaN());
        expectFailure(invalid,"Bayer strength");
        invalid=pack(); writeF32(invalid,20,std::numeric_limits<float>::infinity());
        expectFailure(invalid,"Bayer strength");
        invalid=pack(); writeF32(invalid,20,-0.01f);
        expectFailure(invalid,"Bayer strength");
        invalid=pack(); writeF32(invalid,20,1.01f);
        expectFailure(invalid,"Bayer strength");
        expectFailure(pack(3,0,2,0.01f,42u),"off mode");

        const auto cpuOff=kc::parseRenderSubstrate(pack(3,0,2,0.0f,42u));
        check(cpuOff.present,"CPU/off KCRP presence");
        check(cpuOff.polarMode==kc::PolarRenderMode::Cpu,"CPU/off polar mode");
        check(!cpuOff.bayerEnabled(),"CPU/off enabled Bayer");
        check(cpuOff.seed==42u,"CPU/off seed");

        const auto zeroStrength=kc::parseRenderSubstrate(pack(2,3,32,0.0f,7u));
        check(zeroStrength.present,"zero-strength KCRP presence");
        check(!zeroStrength.bayerEnabled(),
            "zero-strength Bayer should take the exact legacy blit path");

        invalid=packV2(); invalid.pop_back();
        expectFailure(invalid,"truncated");
        invalid=pack();
        invalid.insert(invalid.end(),8u,0u);
        expectFailure(invalid,"trailing bytes");
        invalid=packV2(); invalid[32]=2u;
        expectFailure(invalid,"Polar Material mode");
        invalid=packV2(); invalid[33]=0u;
        expectFailure(invalid,"Polar Material bands");
        invalid=packV2(); invalid[33]=33u;
        expectFailure(invalid,"Polar Material bands");
        invalid=packV2(); writeU16(invalid,34u,1u);
        expectFailure(invalid,"reserved field");
        invalid=packV2();
        writeF32(invalid,36u,std::numeric_limits<float>::quiet_NaN());
        expectFailure(invalid,"Polar Material strength");
        invalid=packV2(); writeF32(invalid,36u,-0.0f);
        expectFailure(invalid,"Polar Material strength");
        invalid=packV2(0u,1u,0.5f);
        expectFailure(invalid,"off mode has nonzero strength");
        const auto materialOff=kc::parseRenderSubstrate(packV2(0u,1u,0.0f));
        check(!materialOff.polarMaterialEnabled(),
            "v2 Polar Material off mode was enabled");

        std::cout<<"PASS strict optional KCRP render substrate\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr<<"FAIL render substrate: "<<error.what()<<'\n';
        return 1;
    }
}
