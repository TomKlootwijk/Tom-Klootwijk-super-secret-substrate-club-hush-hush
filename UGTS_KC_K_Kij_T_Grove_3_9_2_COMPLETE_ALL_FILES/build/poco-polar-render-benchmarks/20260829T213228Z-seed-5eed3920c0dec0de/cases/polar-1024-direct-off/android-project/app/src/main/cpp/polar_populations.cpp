#include "polar_populations.hpp"
#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstring>
#include <limits>
#include <iterator>
#include <stdexcept>
#include <type_traits>
#include <vector>

namespace kc {
namespace {

constexpr std::size_t HeaderBytes=32u;
constexpr std::size_t OperatorBytes=16u;
constexpr std::size_t RecipeBytes=128u;
constexpr std::size_t MaxPackBytes=64u*1024u;
constexpr std::uint16_t MaxRecipes=64u;
constexpr std::uint32_t MaxInstancesPerRecipe=4096u;
constexpr std::uint32_t MaxTotalInstances=16384u;
constexpr std::uint64_t Golden=0x9E3779B97F4A7C15ull;

struct OperatorMeaning {
    std::uint16_t code=0;
    std::uint8_t slot=0,arity=0;
    std::uint64_t meaningHash=0;
    constexpr std::uint16_t mask() const {
        return static_cast<std::uint16_t>(1u<<slot);
    }
};

// These immutable hashes are part of KCPR392, not implementation labels.
constexpr std::array<OperatorMeaning,6> Operators{{
    {0x0001u,0u,3u,0x8bf057fe8b6a4c18ull},
    {0x0010u,1u,3u,0x2c683232ab8619b0ull},
    {0x0011u,2u,2u,0xbcb70d820cc04f24ull},
    {0x0020u,3u,3u,0xc6cb9d947ad82c97ull},
    {0x0030u,4u,2u,0x108012bf057981afull},
    {0x0040u,5u,3u,0x276bd26b782ef226ull},
}};

class Reader {
public:
    explicit Reader(const std::vector<std::uint8_t>& bytes)
        :data_(bytes.data()),size_(bytes.size()) {}
    std::size_t remaining() const { return size_-offset_; }
    const std::uint8_t* raw(std::size_t count) {
        if (count>remaining())
            throw std::runtime_error("truncated KCPR392 polar population asset");
        const auto* result=data_+offset_;
        offset_+=count;
        return result;
    }
    std::uint8_t u8() { return *raw(1); }
    std::uint16_t u16() {
        const auto* p=raw(2);
        return static_cast<std::uint16_t>(p[0])|
            static_cast<std::uint16_t>(static_cast<std::uint16_t>(p[1])<<8);
    }
    std::uint32_t u32() {
        const auto* p=raw(4);
        return static_cast<std::uint32_t>(p[0])|
            (static_cast<std::uint32_t>(p[1])<<8)|
            (static_cast<std::uint32_t>(p[2])<<16)|
            (static_cast<std::uint32_t>(p[3])<<24);
    }
    std::uint64_t u64() {
        const auto low=static_cast<std::uint64_t>(u32());
        return low|(static_cast<std::uint64_t>(u32())<<32);
    }
    float f32() {
        const auto bits=u32();
        return std::bit_cast<float>(bits);
    }
    std::array<std::uint8_t,16> address() {
        std::array<std::uint8_t,16> result{};
        std::memcpy(result.data(),raw(result.size()),result.size());
        return result;
    }
private:
    const std::uint8_t* data_=nullptr;
    std::size_t size_=0,offset_=0;
};

void require(bool condition,const char* message) {
    if (!condition) throw std::runtime_error(message);
}

constexpr std::uint32_t rotateRight(std::uint32_t value,unsigned shift) {
    return (value>>shift)|(value<<(32u-shift));
}

std::array<std::uint8_t,32> sha256(const std::vector<std::uint8_t>& source) {
    constexpr std::array<std::uint32_t,64> constants{{
        0x428a2f98u,0x71374491u,0xb5c0fbcfu,0xe9b5dba5u,0x3956c25bu,0x59f111f1u,0x923f82a4u,0xab1c5ed5u,
        0xd807aa98u,0x12835b01u,0x243185beu,0x550c7dc3u,0x72be5d74u,0x80deb1feu,0x9bdc06a7u,0xc19bf174u,
        0xe49b69c1u,0xefbe4786u,0x0fc19dc6u,0x240ca1ccu,0x2de92c6fu,0x4a7484aau,0x5cb0a9dcu,0x76f988dau,
        0x983e5152u,0xa831c66du,0xb00327c8u,0xbf597fc7u,0xc6e00bf3u,0xd5a79147u,0x06ca6351u,0x14292967u,
        0x27b70a85u,0x2e1b2138u,0x4d2c6dfcu,0x53380d13u,0x650a7354u,0x766a0abbu,0x81c2c92eu,0x92722c85u,
        0xa2bfe8a1u,0xa81a664bu,0xc24b8b70u,0xc76c51a3u,0xd192e819u,0xd6990624u,0xf40e3585u,0x106aa070u,
        0x19a4c116u,0x1e376c08u,0x2748774cu,0x34b0bcb5u,0x391c0cb3u,0x4ed8aa4au,0x5b9cca4fu,0x682e6ff3u,
        0x748f82eeu,0x78a5636fu,0x84c87814u,0x8cc70208u,0x90befffau,0xa4506cebu,0xbef9a3f7u,0xc67178f2u,
    }};
    std::vector<std::uint8_t> data=source;
    const auto bitLength=static_cast<std::uint64_t>(data.size())*8u;
    data.push_back(0x80u);
    while ((data.size()%64u)!=56u) data.push_back(0u);
    for (int shift=56;shift>=0;shift-=8)
        data.push_back(static_cast<std::uint8_t>(bitLength>>shift));
    std::array<std::uint32_t,8> state{{
        0x6a09e667u,0xbb67ae85u,0x3c6ef372u,0xa54ff53au,
        0x510e527fu,0x9b05688cu,0x1f83d9abu,0x5be0cd19u,
    }};
    for (std::size_t offset=0;offset<data.size();offset+=64u) {
        std::array<std::uint32_t,64> words{};
        for (std::size_t index=0;index<16u;++index) {
            const auto* p=data.data()+offset+index*4u;
            words[index]=(static_cast<std::uint32_t>(p[0])<<24)|
                (static_cast<std::uint32_t>(p[1])<<16)|
                (static_cast<std::uint32_t>(p[2])<<8)|p[3];
        }
        for (std::size_t index=16u;index<64u;++index) {
            const auto x=words[index-15u];
            const auto y=words[index-2u];
            const auto small0=rotateRight(x,7)^rotateRight(x,18)^(x>>3);
            const auto small1=rotateRight(y,17)^rotateRight(y,19)^(y>>10);
            words[index]=words[index-16u]+small0+words[index-7u]+small1;
        }
        auto a=state[0],b=state[1],c=state[2],d=state[3];
        auto e=state[4],f=state[5],g=state[6],h=state[7];
        for (std::size_t index=0;index<64u;++index) {
            const auto big1=rotateRight(e,6)^rotateRight(e,11)^rotateRight(e,25);
            const auto choice=(e&f)^((~e)&g);
            const auto temp1=h+big1+choice+constants[index]+words[index];
            const auto big0=rotateRight(a,2)^rotateRight(a,13)^rotateRight(a,22);
            const auto majority=(a&b)^(a&c)^(b&c);
            const auto temp2=big0+majority;
            h=g; g=f; f=e; e=d+temp1;
            d=c; c=b; b=a; a=temp1+temp2;
        }
        state[0]+=a; state[1]+=b; state[2]+=c; state[3]+=d;
        state[4]+=e; state[5]+=f; state[6]+=g; state[7]+=h;
    }
    std::array<std::uint8_t,32> result{};
    for (std::size_t index=0;index<state.size();++index) {
        result[index*4u]=static_cast<std::uint8_t>(state[index]>>24);
        result[index*4u+1u]=static_cast<std::uint8_t>(state[index]>>16);
        result[index*4u+2u]=static_cast<std::uint8_t>(state[index]>>8);
        result[index*4u+3u]=static_cast<std::uint8_t>(state[index]);
    }
    return result;
}

template<class Integer>
void appendLittle(std::vector<std::uint8_t>& output,Integer value) {
    using Unsigned=std::make_unsigned_t<Integer>;
    auto bits=static_cast<Unsigned>(value);
    for (std::size_t index=0;index<sizeof(Integer);++index)
        output.push_back(static_cast<std::uint8_t>(bits>>(index*8u)));
}

void appendAddress(
    std::vector<std::uint8_t>& output,const std::array<std::uint8_t,16>& value
) {
    output.insert(output.end(),value.begin(),value.end());
}

void appendLiteral(
    std::vector<std::uint8_t>& output,const char* value,std::size_t size
) {
    output.insert(output.end(),value,value+size);
}

std::vector<std::uint8_t> recipeSharedBytes(
    const PolarPopulations::Recipe& recipe,std::uint64_t rootSeed
) {
    static constexpr char Prefix[]="KCPR392-lineage-semantics-v1\0";
    std::vector<std::uint8_t> result;
    result.reserve(160u);
    appendLiteral(result,Prefix,sizeof(Prefix)-1u);
    appendLittle(result,recipe.preset);
    appendLittle(result,recipe.operatorMask);
    appendLittle(result,rootSeed);
    appendLittle(result,recipe.seed);
    appendAddress(result,recipe.profileAddress);
    appendAddress(result,recipe.prototypeAddress);
    for (const auto parameter:recipe.parameters)
        appendLittle(result,std::bit_cast<std::uint32_t>(parameter));
    for (const auto& meaning:Operators) {
        if ((recipe.operatorMask&meaning.mask())==0u) continue;
        appendLittle(result,meaning.code);
        appendLittle(result,meaning.meaningHash);
    }
    return result;
}

bool digestPrefixEquals(
    const std::array<std::uint8_t,32>& digest,
    const std::array<std::uint8_t,16>& address
) {
    return std::equal(address.begin(),address.end(),digest.begin());
}

std::array<std::uint8_t,16> digestAddress(
    const std::vector<std::uint8_t>& payload
) {
    const auto digest=sha256(payload);
    std::array<std::uint8_t,16> result{};
    std::copy_n(digest.begin(),result.size(),result.begin());
    return result;
}

void appendF32(std::vector<std::uint8_t>& output,float value) {
    if (value==0.0f) value=0.0f;
    appendLittle(output,std::bit_cast<std::uint32_t>(value));
}

void appendF64(std::vector<std::uint8_t>& output,double value) {
    appendLittle(output,std::bit_cast<std::uint64_t>(value));
}

void appendText(std::vector<std::uint8_t>& output,const std::string& value) {
    require(!value.empty() && value.size()<=std::numeric_limits<std::uint16_t>::max(),
        "KCPR392 dependency text length is invalid");
    appendLittle(output,static_cast<std::uint16_t>(value.size()));
    output.insert(output.end(),value.begin(),value.end());
}

std::array<std::uint8_t,16> profileSemanticsAddress(
    const PackedPolarKinematics::Profile& profile
) {
    static constexpr char Prefix[]="KCPR392-profile-semantics-v1\0";
    std::vector<std::uint8_t> lut;
    const auto resolution=profile.sineHalf.size();
    require(resolution==profile.cosineHalf.size() &&
        resolution==profile.normalizedRadiusHalf.size() &&
        resolution<=std::numeric_limits<std::uint16_t>::max(),
        "KCPR392 packed profile LUT dependency is invalid");
    lut.reserve(48u+resolution*6u);
    appendLiteral(lut,"UGLUT2",6u);
    appendLittle(lut,static_cast<std::uint16_t>(resolution));
    appendF64(lut,profile.r0);
    appendF64(lut,profile.rhoMin);
    appendF64(lut,profile.rhoMax);
    appendF64(lut,profile.coreRadius);
    appendF64(lut,profile.authoredRadiusScale);
    for (const auto value:profile.sineHalf) appendLittle(lut,value);
    for (const auto value:profile.cosineHalf) appendLittle(lut,value);
    for (const auto value:profile.normalizedRadiusHalf) appendLittle(lut,value);

    std::vector<std::uint8_t> payload;
    payload.reserve(sizeof(Prefix)-1u+2u+profile.id.size()+36u+lut.size());
    appendLiteral(payload,Prefix,sizeof(Prefix)-1u);
    appendText(payload,profile.id);
    appendF64(payload,profile.rhoVelocity);
    appendF64(payload,profile.thetaVelocity);
    appendF64(payload,profile.rhoAcceleration);
    appendF64(payload,profile.thetaAcceleration);
    appendLittle(payload,static_cast<std::uint32_t>(resolution));
    appendLittle(payload,static_cast<std::uint32_t>(lut.size()));
    payload.insert(payload.end(),lut.begin(),lut.end());
    return digestAddress(payload);
}

std::array<std::uint8_t,16> meshSemanticsAddress(const MeshData& mesh) {
    static constexpr char Prefix[]="KCPR392-mesh-semantics-v1\0";
    require(mesh.indices.size()%3u==0u,
        "KCPR392 mesh dependency does not contain triangles");
    require(mesh.vertices.size()<=std::numeric_limits<std::uint32_t>::max() &&
        mesh.indices.size()/3u<=std::numeric_limits<std::uint32_t>::max(),
        "KCPR392 mesh dependency exceeds its address domain");
    std::vector<std::uint8_t> payload;
    payload.reserve(sizeof(Prefix)-1u+12u+
        mesh.vertices.size()*24u+mesh.indices.size()*4u);
    appendLiteral(payload,Prefix,sizeof(Prefix)-1u);
    appendLittle(payload,static_cast<std::uint32_t>(mesh.vertices.size()));
    appendLittle(payload,static_cast<std::uint32_t>(mesh.indices.size()/3u));
    appendLittle(payload,static_cast<std::uint32_t>(mesh.vertices.size()));
    for (const auto& vertex:mesh.vertices) {
        appendF32(payload,vertex.position.x);
        appendF32(payload,vertex.position.y);
        appendF32(payload,vertex.position.z);
    }
    for (const auto index:mesh.indices) appendLittle(payload,index);
    for (const auto& vertex:mesh.vertices) {
        appendF32(payload,vertex.normal.x);
        appendF32(payload,vertex.normal.y);
        appendF32(payload,vertex.normal.z);
    }
    return digestAddress(payload);
}

std::array<std::uint8_t,16> materialSemanticsAddress(
    const MaterialData& material
) {
    static constexpr char Prefix[]="KCPR392-material-semantics-v1\0";
    std::vector<std::uint8_t> payload;
    payload.reserve(sizeof(Prefix)-1u+37u);
    appendLiteral(payload,Prefix,sizeof(Prefix)-1u);
    for (const auto value:material.baseColor) appendF32(payload,value);
    appendF32(payload,material.metallic);
    appendF32(payload,material.roughness);
    appendF32(payload,material.emissive.x);
    appendF32(payload,material.emissive.y);
    appendF32(payload,material.emissive.z);
    payload.push_back(material.doubleSided?1u:0u);
    return digestAddress(payload);
}

std::array<std::uint8_t,16> prototypeSemanticsAddress(
    const ScenePack& scene,const NodeData& node,
    const PackedPolarKinematics::Component& component,
    const std::array<std::uint8_t,16>& profileAddress
) {
    static constexpr char Prefix[]="KCPR392-prototype-semantics-v1\0";
    require(node.meshIndex<scene.meshes.size() &&
        node.materialIndex<scene.materials.size(),
        "KCPR392 prototype dependency render reference is invalid");
    const auto meshAddress=meshSemanticsAddress(scene.meshes[node.meshIndex]);
    const auto materialAddress=materialSemanticsAddress(
        scene.materials[node.materialIndex]
    );
    std::vector<std::uint8_t> payload;
    payload.reserve(sizeof(Prefix)-1u+2u+node.id.size()+64u+16u+20u);
    appendLiteral(payload,Prefix,sizeof(Prefix)-1u);
    appendText(payload,node.id);
    appendAddress(payload,profileAddress);
    appendAddress(payload,meshAddress);
    appendAddress(payload,materialAddress);
    appendLittle(payload,component.pose);
    appendLittle(payload,component.motion);
    appendF32(payload,node.translation.y);
    appendF32(payload,node.scale.x);
    appendF32(payload,node.scale.y);
    appendF32(payload,node.scale.z);
    appendF32(payload,node.velocity.y);
    return digestAddress(payload);
}

float round32(float value) {
    volatile float rounded=value;
    return rounded==0.0f?0.0f:rounded;
}

float add32(float left,float right) {
    const auto a=round32(left),b=round32(right);
    return round32(a+b);
}

float subtract32(float left,float right) {
    const auto a=round32(left),b=round32(right);
    return round32(a-b);
}

float multiply32(float left,float right) {
    const auto a=round32(left),b=round32(right);
    return round32(a*b);
}

float divide32(float left,float right) {
    const auto a=round32(left),b=round32(right);
    require(b!=0.0f,"KCPR392 polar population division by zero");
    return round32(a/b);
}

std::uint32_t periodicTurnCode(float turns,unsigned bits) {
    const auto value=round32(turns);
    const auto whole=std::floor(value);
    const auto fraction=subtract32(value,static_cast<float>(whole));
    const auto scaled=multiply32(
        fraction,static_cast<float>(std::uint32_t{1}<<bits)
    );
    return static_cast<std::uint32_t>(std::floor(scaled))&
        ((std::uint32_t{1}<<bits)-1u);
}

std::uint64_t splitmix64(std::uint64_t value) {
    value+=Golden;
    value=(value^(value>>30))*0xBF58476D1CE4E5B9ull;
    value=(value^(value>>27))*0x94D049BB133111EBull;
    return value^(value>>31);
}

std::uint64_t combineSeed(std::uint64_t seed,std::uint64_t value) {
    const auto mixed=splitmix64(value)+Golden+(seed<<6)+(seed>>2);
    return splitmix64(seed^mixed);
}

std::uint64_t stableId(
    std::uint64_t sessionSeed,std::uint64_t nameSpace,std::uint64_t address
) {
    return combineSeed(combineSeed(sessionSeed,nameSpace),address);
}

float seedUnitFloat(std::uint64_t value) {
    return static_cast<float>(splitmix64(value)>>40)/16777216.0f;
}

float lane(std::uint64_t lineage,std::uint64_t index) {
    return seedUnitFloat(combineSeed(lineage,index));
}

std::uint64_t addressU64(
    const std::array<std::uint8_t,16>& address,std::size_t offset
) {
    std::uint64_t result=0;
    for (std::size_t index=0;index<8u;++index)
        result|=static_cast<std::uint64_t>(address[offset+index])<<(index*8u);
    return result;
}

std::uint16_t presetMask(std::uint16_t preset) {
    if (preset==1u || preset==3u) return 0x003bu;
    if (preset==2u) return 0x003fu;
    return 0u;
}

void validateParameters(std::uint16_t preset,const std::array<float,8>& values) {
    require(std::all_of(values.begin(),values.end(),[](float value) {
        return std::isfinite(value);
    }),"KCPR392 polar population parameters must be finite");
    require(std::none_of(values.begin(),values.end(),[](float value) {
        return value==0.0f && std::signbit(value);
    }),"KCPR392 polar population parameters are not canonical positive zero");
    constexpr auto logLimit=std::bit_cast<float>(std::uint32_t{0x40b17218u});
    require(values[0]>=-logLimit && values[0]<=values[1] && values[1]<=logLimit,
        "KCPR392 polar population log-radius offset range is invalid");
    require(values[3]>=-4.0f && values[3]<=4.0f,
        "KCPR392 polar population turn step is invalid");
    require(values[4]>=0.0f && values[4]<=1.0f,
        "KCPR392 polar population turn variation is invalid");
    require(values[5]>=0.0f && values[5]<=1024.0f,
        "KCPR392 polar population height spread is invalid");
    require(values[6]>=0.05f && values[6]<=values[7] && values[7]<=8.0f,
        "KCPR392 polar population scale range is invalid");
    if (preset==2u)
        require(values[2]>=0.000001f && values[2]<=1.0f,
            "KCPR392 spiral growth rate is invalid");
    else
        require(values[2]==0.0f,
            "KCPR392 non-spiral growth rate must be zero");
}

} // namespace

void PolarPopulations::clear() {
    rootSeed_=0;
    totalInstances_=0;
    recipes_.clear();
    lastMaterializedCount_=0;
    lastCartesianComposeCount_=0;
}

void PolarPopulations::load(
    const std::vector<std::uint8_t>& bytes,std::uint64_t expectedRootSeed,
    const ScenePack& scene,const PackedPolarKinematics& polar
) {
    clear();
    if (bytes.empty()) return;
    try {
        require(bytes.size()<=MaxPackBytes,
            "KCPR392 polar population asset exceeds its byte limit");
        require(bytes.size()>=HeaderBytes,
            "truncated KCPR392 polar population asset");
        Reader reader(bytes);
        require(std::memcmp(reader.raw(8),"KCPR392\0",8)==0,
            "KCPR392 polar population magic mismatch");
        require(reader.u32()==0x01020304u,
            "KCPR392 polar population endian marker mismatch");
        require(reader.u32()==1u,
            "unsupported KCPR392 polar population version");
        const auto operatorCount=reader.u16();
        const auto recipeCount=reader.u16();
        totalInstances_=reader.u32();
        rootSeed_=reader.u64();
        require(rootSeed_==expectedRootSeed,
            "KCPR392 root seed does not match render_substrate.kcrp");
        require(operatorCount>=1u && operatorCount<=Operators.size(),
            "KCPR392 polar population operator count is invalid");
        require(recipeCount>=1u && recipeCount<=MaxRecipes,
            "KCPR392 polar population recipe count is invalid");
        const auto expectedSize=HeaderBytes+
            static_cast<std::size_t>(operatorCount)*OperatorBytes+
            static_cast<std::size_t>(recipeCount)*RecipeBytes;
        require(bytes.size()==expectedSize,
            bytes.size()<expectedSize
                ?"truncated KCPR392 polar population record"
                :"KCPR392 polar population asset has trailing bytes");

        std::uint16_t presentMask=0,previousCode=0;
        for (std::uint16_t index=0;index<operatorCount;++index) {
            const auto code=reader.u16();
            const auto slot=reader.u8();
            const auto arity=reader.u8();
            const auto flags=reader.u32();
            const auto meaningHash=reader.u64();
            require(index==0u || code>previousCode,
                "KCPR392 polar population operators are not canonical");
            const auto found=std::find_if(Operators.begin(),Operators.end(),
                [code](const OperatorMeaning& value){ return value.code==code; });
            require(found!=Operators.end(),
                "KCPR392 polar population operator is unknown");
            require(slot==found->slot && arity==found->arity && flags==0u &&
                meaningHash==found->meaningHash,
                "KCPR392 polar population operator meaning mismatch");
            presentMask=static_cast<std::uint16_t>(presentMask|found->mask());
            previousCode=code;
        }

        recipes_.reserve(recipeCount);
        std::uint64_t countedInstances=0;
        std::uint32_t countedGenerated=0;
        std::uint16_t usedMask=0;
        std::uint32_t previousPrototype=0;
        for (std::uint16_t recipeIndex=0;recipeIndex<recipeCount;++recipeIndex) {
            Recipe recipe;
            recipe.prototypeSceneNode=reader.u32();
            recipe.preset=reader.u16();
            recipe.operatorMask=reader.u16();
            recipe.instanceCount=reader.u32();
            recipe.seed=reader.u64();
            recipe.contentAddress=reader.address();
            recipe.lineageNamespace=reader.address();
            recipe.profileAddress=reader.address();
            recipe.prototypeAddress=reader.address();
            for (auto& parameter:recipe.parameters) parameter=reader.f32();
            const auto* reserved=reader.raw(12);
            require(std::all_of(reserved,reserved+12,[](std::uint8_t byte) {
                return byte==0u;
            }),"KCPR392 polar population recipe reserved bytes are nonzero");
            require(recipeIndex==0u || recipe.prototypeSceneNode>previousPrototype,
                "KCPR392 polar population recipes are not sparse-canonical");
            require(recipe.prototypeSceneNode<scene.nodes.size(),
                "KCPR392 polar population prototype node is invalid");
            require(recipe.preset>=1u && recipe.preset<=3u,
                "KCPR392 polar population preset code is invalid");
            require(recipe.operatorMask==presetMask(recipe.preset),
                "KCPR392 polar population preset operator mask is invalid");
            require((recipe.operatorMask&~presentMask)==0u,
                "KCPR392 polar population recipe references a missing operator");
            require(recipe.instanceCount>=2u &&
                recipe.instanceCount<=MaxInstancesPerRecipe,
                "KCPR392 polar population instance count is invalid");
            validateParameters(recipe.preset,recipe.parameters);

            const auto* component=polar.componentForSceneNode(recipe.prototypeSceneNode);
            require(component!=nullptr,
                "KCPR392 polar population prototype has no packed polar component");
            require(component->profile<polar.profiles().size(),
                "KCPR392 polar population prototype profile is invalid");
            const auto& prototype=scene.nodes[recipe.prototypeSceneNode];
            require(prototype.meshIndex<scene.meshes.size() &&
                prototype.materialIndex<scene.materials.size(),
                "KCPR392 polar population prototype render reference is invalid");
            recipe.profile=component->profile;
            const auto expectedProfileAddress=profileSemanticsAddress(
                polar.profiles()[recipe.profile]
            );
            require(recipe.profileAddress==expectedProfileAddress,
                "KCPR392 polar population profile dependency address mismatch");
            const auto expectedPrototypeAddress=prototypeSemanticsAddress(
                scene,prototype,*component,expectedProfileAddress
            );
            require(recipe.prototypeAddress==expectedPrototypeAddress,
                "KCPR392 polar population prototype dependency address mismatch");

            // Recompute both derived addresses after binding the exact KC3D
            // render/anchor semantics and exact KCPK profile/LUT dependency.
            auto shared=recipeSharedBytes(recipe,rootSeed_);
            require(digestPrefixEquals(sha256(shared),recipe.lineageNamespace),
                "KCPR392 polar population lineage namespace mismatch");
            static constexpr char ContentPrefix[]=
                "KCPR392-full-recipe-content-v1\0";
            std::vector<std::uint8_t> content;
            content.reserve(sizeof(ContentPrefix)-1u+shared.size()+4u);
            appendLiteral(content,ContentPrefix,sizeof(ContentPrefix)-1u);
            content.insert(content.end(),shared.begin(),shared.end());
            appendLittle(content,recipe.instanceCount);
            require(digestPrefixEquals(sha256(content),recipe.contentAddress),
                "KCPR392 polar population content address mismatch");

            recipe.firstGenerated=countedGenerated;
            recipe.generatedCount=recipe.instanceCount-1u;
            recipe.sessionSeed=combineSeed(rootSeed_,recipe.seed);
            recipe.lineageNamespaceId=combineSeed(
                addressU64(recipe.lineageNamespace,0u),
                addressU64(recipe.lineageNamespace,8u)
            );
            recipe.seededPhase=lane(stableId(
                recipe.sessionSeed,recipe.lineageNamespaceId,0u
            ),0u);
            recipe.logSpan=subtract32(
                recipe.parameters[1],recipe.parameters[0]
            );
            countedGenerated+=recipe.generatedCount;
            countedInstances+=recipe.instanceCount;
            require(countedInstances<=MaxTotalInstances,
                "KCPR392 polar population total exceeds its safety limit");
            usedMask=static_cast<std::uint16_t>(usedMask|recipe.operatorMask);
            previousPrototype=recipe.prototypeSceneNode;
            recipes_.push_back(recipe);
        }
        require(reader.remaining()==0u,
            "KCPR392 polar population reader did not consume the asset");
        require(usedMask==presentMask,
            "KCPR392 polar population operator table is not minimal-canonical");
        require(countedInstances==totalInstances_,
            "KCPR392 polar population total does not match its recipes");
        require(totalInstances_<=MaxTotalInstances,
            "KCPR392 polar population total exceeds its safety limit");

    } catch (...) {
        clear();
        throw;
    }
}

void PolarPopulations::beginFrame() const {
    lastMaterializedCount_=0;
    lastCartesianComposeCount_=0;
}

std::uint32_t PolarPopulations::prototypeSceneNode(
    std::size_t generatedIndex
) const {
    return recipes_[recipeIndex(generatedIndex)].prototypeSceneNode;
}

std::uint16_t PolarPopulations::profile(std::size_t generatedIndex) const {
    return recipes_[recipeIndex(generatedIndex)].profile;
}

std::uint32_t PolarPopulations::recipeIndex(std::size_t generatedIndex) const {
    if (generatedIndex>=generatedCount() || recipes_.empty())
        throw std::runtime_error("KCPR392 generated copy index is invalid");
    const auto found=std::upper_bound(
        recipes_.begin(),recipes_.end(),generatedIndex,
        [](std::size_t target,const Recipe& recipe) {
            return target<recipe.firstGenerated;
        }
    );
    if (found==recipes_.begin())
        throw std::runtime_error("KCPR392 generated recipe range is invalid");
    const auto recipe=std::prev(found);
    if (generatedIndex>=static_cast<std::size_t>(recipe->firstGenerated)+
            recipe->generatedCount)
        throw std::runtime_error("KCPR392 generated recipe range is invalid");
    return static_cast<std::uint32_t>(std::distance(recipes_.begin(),recipe));
}

PolarPopulations::RenderCopy PolarPopulations::materialize(
    std::size_t generatedIndex,const PackedPolarKinematics& polar,
    const std::vector<NodeData>& nodes,bool composeCartesian
) const {
    const auto selectedRecipe=recipeIndex(generatedIndex);
    const auto& recipe=recipes_[selectedRecipe];
    const auto instanceIndex=static_cast<std::uint32_t>(
        generatedIndex-recipe.firstGenerated+1u
    );
    const auto lineage=stableId(
        recipe.sessionSeed,recipe.lineageNamespaceId,instanceIndex
    );
    float radialUnit=lane(lineage,1u);
    if (recipe.preset==2u) {
        const auto spiralX=multiply32(
            static_cast<float>(instanceIndex),recipe.parameters[2]
        );
        radialUnit=divide32(spiralX,add32(1.0f,spiralX));
    }
    const auto rhoOffset=add32(
        recipe.parameters[0],multiply32(recipe.logSpan,radialUnit)
    );
    const auto turnJitter=multiply32(
        subtract32(lane(lineage,2u),0.5f),recipe.parameters[4]
    );
    const auto steppedTurn=multiply32(
        static_cast<float>(instanceIndex),recipe.parameters[3]
    );
    const auto turns=add32(
        add32(recipe.seededPhase,steppedTurn),turnJitter
    );
    const auto thetaOffsetCode=periodicTurnCode(turns,18u);
    const auto headingOffsetCode=static_cast<std::uint16_t>(
        periodicTurnCode(turns,12u)
    );
    const auto heightOffset=multiply32(
        subtract32(lane(lineage,3u),0.5f),recipe.parameters[5]
    );
    const auto scaleScalar=add32(
        recipe.parameters[6],multiply32(
            lane(lineage,4u),
            subtract32(recipe.parameters[7],recipe.parameters[6])
        )
    );
    require(std::isfinite(rhoOffset)&&std::isfinite(heightOffset)&&
        std::isfinite(scaleScalar),
        "KCPR392 polar population generated value is nonfinite");
    require(recipe.prototypeSceneNode<nodes.size(),
        "KCPR392 polar population prototype runtime node is invalid");
    const auto* component=polar.componentForSceneNode(recipe.prototypeSceneNode);
    require(component!=nullptr && component->profile==recipe.profile,
        "KCPR392 polar population prototype component changed incompatibly");
    RenderCopy copy;
    copy.generatedIndex=static_cast<std::uint32_t>(generatedIndex);
    copy.recipeIndex=selectedRecipe;
    copy.prototypeSceneNode=recipe.prototypeSceneNode;
    copy.instanceIndex=instanceIndex;
    copy.profile=recipe.profile;
    copy.lineage=lineage;
    copy.previousPose=polar.offsetPoseCodes(
        recipe.profile,component->previousPose,rhoOffset,
        thetaOffsetCode,headingOffsetCode
    );
    copy.pose=polar.offsetPoseCodes(
        recipe.profile,component->pose,rhoOffset,
        thetaOffsetCode,headingOffsetCode
    );
    copy.motion=component->motion;
    copy.node=nodes[recipe.prototypeSceneNode];
    copy.node.velocity.y=round32(copy.node.velocity.y);
    copy.node.translation.y=add32(copy.node.translation.y,heightOffset);
    copy.node.scale.x=multiply32(copy.node.scale.x,scaleScalar);
    copy.node.scale.y=multiply32(copy.node.scale.y,scaleScalar);
    copy.node.scale.z=multiply32(copy.node.scale.z,scaleScalar);
    ++lastMaterializedCount_;
    if (composeCartesian) {
        this->composeCartesian(copy,polar);
    }
    return copy;
}

void PolarPopulations::composeCartesian(
    RenderCopy& copy,const PackedPolarKinematics& polar
) const {
    require(copy.profile<polar.profiles().size(),
        "KCPR392 polar population Cartesian profile is invalid");
    polar.composePose(copy.profile,copy.pose,copy.motion,copy.node);
    ++lastCartesianComposeCount_;
}

} // namespace kc
