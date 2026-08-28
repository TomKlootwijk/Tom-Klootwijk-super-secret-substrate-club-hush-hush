#include "storage_android.hpp"
#include "android_log.hpp"
#include <chrono>
#include <fstream>
#include <iomanip>
#include <sstream>
namespace ugts41::android {
SessionStorage::SessionStorage(std::filesystem::path root):root_(std::move(root)),sessions_(root_/"sessions"){std::error_code ec;std::filesystem::create_directories(sessions_,ec);if(ec)error_=ec.message();}
bool SessionStorage::begin(const KseedHeader&h,std::size_t chunk){if(active())return false;std::ostringstream name;name<<"session_"<<h.start_time_ns<<"_"<<std::hex<<std::setw(16)<<std::setfill('0')<<h.session_seed<<".kseed";session_path_=sessions_/name.str();writer_=std::make_unique<KseedWriter>(session_path_,h,chunk);if(!writer_->good()){error_=writer_->error();writer_.reset();return false;}UGTS_LOGI("session file=%s",session_path_.c_str());return true;}
void SessionStorage::finish(SessionStats stats,const std::string&profile,const std::string&hash){if(!writer_)return;writer_->close(stats);stats.stored_bytes=std::filesystem::file_size(session_path_);auto json=session_path_;json.replace_extension(".json");std::ofstream out(json);out<<"{\n  \"schema\": \"ugts-kc-native-session-summary-4.1\",\n  \"profile\": \""<<profile<<"\",\n  \"session_seed\": \"0x"<<std::hex<<std::setw(16)<<std::setfill('0')<<stats.session_seed<<std::dec<<"\",\n  \"frames_seen\": "<<stats.frames_seen<<",\n  \"keyframes_stored\": "<<stats.keyframes_stored<<",\n  \"events_committed\": "<<stats.events_committed<<",\n  \"rejected_proposals\": "<<stats.rejected_proposals<<",\n  \"raw_input_bytes\": "<<stats.raw_input_bytes<<",\n  \"stored_bytes\": "<<stats.stored_bytes<<",\n  \"state_hash\": \""<<hash<<"\",\n  \"raw_images_retained\": false\n}\n";UGTS_LOGI("session closed bytes=%llu",static_cast<unsigned long long>(stats.stored_bytes));writer_.reset();}
}
