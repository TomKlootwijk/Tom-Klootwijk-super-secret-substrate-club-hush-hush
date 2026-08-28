#include "scene_pack.hpp"
#include "device_profile.hpp"
#include "adaptive_quality.hpp"
#include <cassert>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <iterator>
#include <vector>

int main(int argc,char** argv) {
    if (argc != 2) {
        std::cerr << "usage: native_core_tests scene.kc3d\n";
        return 2;
    }
    std::ifstream input(argv[1],std::ios::binary);
    std::vector<std::uint8_t> bytes((std::istreambuf_iterator<char>(input)),{});
    const auto scene=kc::parseScenePack(bytes);
    assert(scene.projectId=="tom_klootwijk_signature_arena_3d");
    assert(scene.meshes.size()==4);
    assert(scene.materials.size()==8);
    assert(scene.nodes.size()==66);
    assert(scene.qualities.size()==5);
    assert(scene.targets.size()==4);

    kc::DeviceInfo poco;
    poco.model="POCO X7 Pro";
    poco.manufacturer="POCO";
    poco.gpu="Mali-G720 MC7";
    poco.ramMb=12288;
    poco.cpuCores=8;
    poco.glesMajor=3;
    poco.glesMinor=2;
    poco.refreshHz=120;
    const auto selected=kc::selectProfile(scene,poco,"auto");
    assert(selected.profileId=="poco_x7_pro_12gb");
    assert(selected.qualityId=="signature_ultra");
    assert(selected.targetFps==120);

    kc::AdaptiveQuality controller(0);
    std::size_t index=0;
    for (int i=0;i<4;++i) index=controller.update(scene,50.0f,120.0f,4,0.5f);
    assert(index>=1);
    for (int i=0;i<20;++i) index=controller.update(scene,120.0f,120.0f,0,0.5f);
    assert(index==0);

    std::cout << "PASS native core: " << scene.title
              << " meshes=" << scene.meshes.size()
              << " nodes=" << scene.nodes.size()
              << " profile=" << selected.profileId
              << " quality=" << selected.qualityId << "\n";
    return 0;
}
