#include "feature_extractor.hpp"
#include "kseed_codec.hpp"
#include "ledger.hpp"
#include "pipeline.hpp"
#include "seed.hpp"
#include "sha256.hpp"
#include "spatial_keys.hpp"
#include "varint.hpp"
#include "verifier.hpp"
#include <filesystem>
#include <fstream>
#include <iostream>
#include <span>
#include <string>
#include <vector>
using namespace ugts41;
namespace {int passed=0;void ok(bool v,const char*n){if(!v){std::cerr<<"FAIL: "<<n<<"\n";std::exit(1);}passed++;std::cout<<"PASS: "<<n<<"\n";}EventProposal valid(std::uint64_t id){EventProposal p;p.proposal_id=id;p.stable_id=id+1;p.spatial_key=id+2;p.timestamp_ns=100;p.confidence=.9f;p.numeric_error=.001f;p.uncertainty=.2f;p.guard=GuardStatus::Confirmed;p.support_ok=p.compatibility_ok=true;return p;}}
int main(){
 std::string abc="abc";ok(hex_digest(std::span<const std::uint8_t>((const std::uint8_t*)abc.data(),abc.size()))=="ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad","sha256");
 ok(splitmix64(7)==splitmix64(7)&&splitmix64(7)!=splitmix64(8),"seed determinism");
 std::vector<std::uint8_t>vi;append_varuint(vi,0);append_varuint(vi,128);append_varint(vi,-99);std::size_t off=0;std::uint64_t u;std::int64_t s;ok(read_varuint(vi,off,u)&&u==0,"varuint 0");ok(read_varuint(vi,off,u)&&u==128,"varuint 128");ok(read_varint(vi,off,s)&&s==-99,"varint signed");
 auto vk=pack_voxel_key({7,-123,456,-1});auto vf=unpack_voxel_key(vk);ok(vf.level==7&&vf.x==-123&&vf.y==456&&vf.z==-1,"voxel key");auto rk=pack_ray_key({1048575,262143,16383,4095});auto rf=unpack_ray_key(rk);ok(rf.log_depth==1048575&&rf.azimuth==262143&&rf.elevation==16383&&rf.time==4095,"ray key");
 constexpr std::uint16_t W=320,H=180;std::vector<std::uint8_t>img(std::size_t(W)*H);for(unsigned y=0;y<H;y++)for(unsigned x=0;x<W;x++)img[std::size_t(y)*W+x]=std::uint8_t((x*3+y*5+((x/20+y/20)%2)*70)&255);ImuSample imu;imu.orientation={0,0,0,1};imu.acceleration={0.1f,9.8f,-.2f};imu.angular_velocity={.01f,.02f,.03f};SeededFeatureExtractor ex(0x1234);auto out=ex.extract(img.data(),W,H,W,1,1,1000000000ULL,imu);auto frame=out.observation;ok(frame.width==160&&frame.height==90,"analysis size");ok(!frame.features.empty()&&frame.features.size()<=96,"feature budget");auto again=ex.extract(img.data(),W,H,W,1,1,1000000000ULL,imu);ok(again.observation.luma_signature==frame.luma_signature&&again.observation.features.front().x==frame.features.front().x,"feature deterministic");KeyframeSelector ks;ok(ks.should_store(frame)&&!ks.should_store(frame),"keyframe selector");
 ProposalVerifier pv;auto p=valid(10);ok(pv.verify(p).accepted,"verifier accept");p.support_ok=false;ok(!pv.verify(p).accepted,"verifier reject");
 SpatialLedger ledger;p=valid(20);ok(ledger.commit(p).has_value(),"ledger commit");auto hash=ledger.state_hash();p=valid(30);ledger.commit(p);ok(hash!=ledger.state_hash()&&ledger.nodes().size()==2,"ledger state/hash");
 auto demo=generate_demo_world(0xdeadbeef,12);auto dp=demo_world_proposals(demo,123,200,true);SpatialLedger dl;for(auto&q:dp)dl.commit(q);ok(dl.route_nodes().size()==demo.nodes.size()&&dl.route_edges().size()==demo.edges.size(),"demo route commit");
 auto props=proposals_from_frame(frame,0x7777);ok(props.size()>1&&props.front().kind==EventKind::Keyframe,"observation adapter");
 auto path=std::filesystem::temp_directory_path()/"ugts41_test.kseed";KseedHeader kh;kh.session_seed=0x1234;kh.start_time_ns=1000000000ULL;kh.storage_mode=StorageMode::SeedDeltasAndThumbnail;std::string profile="profile";kh.profile_hash=sha256(std::span<const std::uint8_t>((const std::uint8_t*)profile.data(),profile.size()));KseedWriter writer(path,kh,512);ok(writer.good(),"writer open");writer.append_frame(frame,out.analysis_luma);auto f2=frame;f2.frame_index=2;f2.timestamp_ns+=33333333;writer.append_frame(f2);for(auto&e:ledger.events())writer.append_event(e);SessionStats stats;stats.session_seed=kh.session_seed;stats.start_time_ns=kh.start_time_ns;stats.end_time_ns=2000000000ULL;stats.frames_seen=2;stats.keyframes_stored=2;stats.events_committed=ledger.events().size();writer.close(stats);auto read=read_kseed(path);if(!read.error.empty())std::cerr<<read.error<<"\n";ok(read.complete&&read.header_crc_ok&&read.chunk_crc_ok&&read.chain_ok,"kseed integrity");ok(read.frames.size()==2&&read.events.size()==ledger.events().size(),"kseed roundtrip");ok(read.stats.stored_bytes==std::filesystem::file_size(path),"summary final byte count");ok(read.thumbnails[0].size()==out.analysis_luma.size(),"thumbnail roundtrip");auto corrupt=path.string()+".bad";std::ifstream in(path,std::ios::binary);std::vector<std::uint8_t>b((std::istreambuf_iterator<char>(in)),{});b[b.size()/2]^=1;std::ofstream co(corrupt,std::ios::binary);co.write((char*)b.data(),b.size());co.close();auto bad=read_kseed(corrupt);ok(!bad.complete&&!bad.error.empty(),"corruption detection");std::filesystem::remove(path);std::filesystem::remove(corrupt);
 std::cout<<"TOTAL PASS: "<<passed<<"\n";return 0;}
