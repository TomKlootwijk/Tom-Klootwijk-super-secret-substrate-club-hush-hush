#include "scene_pack.hpp"
#include "transform_hierarchy.hpp"

#include <cmath>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

void check(bool condition,const std::string& message) {
    if (!condition) throw std::runtime_error(message);
}

void near(float actual,float expected,float tolerance,const std::string& label) {
    if (!std::isfinite(actual)||std::abs(actual-expected)>tolerance)
        throw std::runtime_error(label+" mismatch");
}

void near(kc::Vec3 actual,kc::Vec3 expected,float tolerance,const std::string& label) {
    near(actual.x,expected.x,tolerance,label+" x");
    near(actual.y,expected.y,tolerance,label+" y");
    near(actual.z,expected.z,tolerance,label+" z");
}

std::vector<std::uint8_t> readBytes(const char* path) {
    std::ifstream stream(path,std::ios::binary);
    if (!stream) throw std::runtime_error(std::string("could not read ")+path);
    std::vector<std::uint8_t> bytes;
    for (char value=0;stream.get(value);)
        bytes.push_back(static_cast<std::uint8_t>(static_cast<unsigned char>(value)));
    return bytes;
}

std::size_t findNode(const std::vector<kc::NodeData>& nodes,const std::string& id) {
    for (std::size_t index=0;index<nodes.size();++index)
        if (nodes[index].id==id) return index;
    throw std::runtime_error("generated KC3D is missing node "+id);
}

void writeU32(std::vector<std::uint8_t>& bytes,std::size_t offset,std::uint32_t value) {
    check(offset+4<=bytes.size(),"test mutation offset");
    for (unsigned index=0;index<4;++index)
        bytes[offset+index]=static_cast<std::uint8_t>(value>>(index*8));
}

void appendU32(std::vector<std::uint8_t>& bytes,std::uint32_t value) {
    for (unsigned index=0;index<4;++index)
        bytes.push_back(static_cast<std::uint8_t>(value>>(index*8)));
}

std::vector<std::uint8_t> tooDeepPack() {
    const char magic[8]={'K','C','H','I','3','9','2','\0'};
    std::vector<std::uint8_t> bytes(magic,magic+8);
    appendU32(bytes,0x01020304u);
    appendU32(bytes,1u);
    appendU32(bytes,9u);
    appendU32(bytes,0u);
    for (std::uint32_t child=1;child<=9;++child) {
        appendU32(bytes,child);
        appendU32(bytes,child-1);
    }
    return bytes;
}

void expectLoadFailure(
    const std::vector<std::uint8_t>& bytes,const std::vector<kc::NodeData>& nodes,
    const std::string& label
) {
    kc::TransformHierarchy hierarchy;
    try {
        hierarchy.load(bytes,nodes);
    } catch (const std::exception&) {
        check(hierarchy.linkCount()==0,label+" did not clear runtime state");
        return;
    }
    throw std::runtime_error(label+" was accepted");
}

} // namespace

int main(int argc,char** argv) {
    try {
        if (argc!=3) {
            std::cerr<<"usage: transform_hierarchy_tests scene.kc3d hierarchies.kchi\n";
            return 2;
        }
        const auto scene=kc::parseScenePack(readBytes(argv[1]));
        auto nodes=scene.nodes;
        const auto root=findNode(nodes,"hierarchy_root");
        const auto level1=findNode(nodes,"hierarchy_level_1");
        const auto level2=findNode(nodes,"hierarchy_level_2");
        const auto level3=findNode(nodes,"hierarchy_level_3");

        // KC3D still contains the authored parent-local payload.
        near(nodes[level1].translation,{1.0f,0.0f,0.0f},0.0f,"KC3D level-1 local");
        near(nodes[level2].translation,{0.0f,1.0f,0.0f},0.0f,"KC3D level-2 local");
        near(nodes[level3].translation,{0.0f,0.0f,1.0f},0.0f,"KC3D level-3 local");

        const auto hierarchyBytes=readBytes(argv[2]);
        auto corrupt=hierarchyBytes;
        writeU32(corrupt,32,0u);
        expectLoadFailure(corrupt,nodes,"noncanonical duplicate child");
        corrupt=hierarchyBytes;
        writeU32(corrupt,28,99u);
        expectLoadFailure(corrupt,nodes,"missing parent index");
        corrupt=hierarchyBytes;
        writeU32(corrupt,36,0u);
        expectLoadFailure(corrupt,nodes,"hierarchy cycle");
        corrupt=hierarchyBytes;
        corrupt.push_back(0u);
        expectLoadFailure(corrupt,nodes,"trailing hierarchy byte");
        std::vector<kc::NodeData> deepNodes(10);
        expectLoadFailure(tooDeepPack(),deepNodes,"depth-nine hierarchy");

        kc::TransformHierarchy hierarchy;
        hierarchy.load(hierarchyBytes,nodes);
        check(hierarchy.linkCount()==3,"generated KCHI link count");
        check(hierarchy.maxDepth()==3,"generated KCHI max depth");
        check(hierarchy.isLinked(root)&&hierarchy.isLinked(level1)&&
            hierarchy.isLinked(level2)&&hierarchy.isLinked(level3),
            "hierarchy-linked render fallback query missed a participant");
        check(!hierarchy.isChild(root),"hierarchy root was misclassified as a child");
        check(hierarchy.isChild(level1)&&hierarchy.isChild(level2)&&hierarchy.isChild(level3),
            "hierarchy child ownership query missed a child");

        // Move, rotate and uniformly scale the root. Descendants at every
        // depth must receive world TRS in the same composition pass.
        nodes[root].translation={10.0f,-2.0f,5.0f};
        nodes[root].rotation=kc::axisAngle({0.0f,0.0f,1.0f},kc::kPi*0.5f);
        nodes[root].scale={2.0f,2.0f,2.0f};
        hierarchy.compose(nodes);
        near(nodes[level1].translation,{10.0f,0.0f,5.0f},2.0e-5f,"first level world");
        near(nodes[level2].translation,{9.0f,0.0f,5.0f},3.0e-5f,"second level world");
        near(nodes[level3].translation,{11.0f,0.0f,5.0f},4.0e-5f,"third level world");
        near(nodes[level1].scale,{1.0f,1.0f,1.0f},1.0e-6f,"first level scale");
        near(nodes[level2].scale,{2.0f,2.0f,2.0f},1.0e-6f,"second level scale");
        near(nodes[level3].scale,{2.0f,4.0f,6.0f},1.0e-6f,"third level scale");

        // A second root pose proves composition retained the original local
        // child TRS rather than feeding the previous world values back in.
        nodes[root].translation={-4.0f,3.0f,1.0f};
        nodes[root].rotation={1.0f,0.0f,0.0f,0.0f};
        nodes[root].scale={0.5f,0.5f,0.5f};
        hierarchy.compose(nodes);
        near(nodes[level1].translation,{-3.5f,3.0f,1.0f},2.0e-5f,"repeat first level");
        near(nodes[level2].translation,{-3.5f,3.25f,1.0f},3.0e-5f,"repeat second level");
        near(nodes[level3].translation,{-3.5f,2.75f,1.0f},4.0e-5f,"repeat third level");
        near(nodes[level3].scale,{0.5f,1.0f,1.5f},1.0e-6f,"repeat third scale");

        nodes[root].scale={0.5f,0.6f,0.5f};
        try {
            hierarchy.compose(nodes);
            throw std::runtime_error("nonuniform runtime parent scale was accepted");
        } catch (const std::runtime_error& error) {
            check(
                std::string(error.what()).find("uniform and positive")!=std::string::npos,
                "unexpected runtime-scale failure"
            );
        }

        std::cout<<"PASS generated KC3D+KCHI transform hierarchy links="
            <<hierarchy.linkCount()<<" depth="<<hierarchy.maxDepth()<<"\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr<<error.what()<<"\n";
        return 1;
    }
}
