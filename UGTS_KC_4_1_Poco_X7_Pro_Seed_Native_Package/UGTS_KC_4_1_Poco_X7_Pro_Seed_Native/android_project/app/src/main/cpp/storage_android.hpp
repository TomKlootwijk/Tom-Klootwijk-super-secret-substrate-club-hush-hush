#pragma once
#include "core/kseed_codec.hpp"
#include <filesystem>
#include <memory>
#include <string>
namespace ugts41::android {
class SessionStorage{
public:explicit SessionStorage(std::filesystem::path app_data_root);bool begin(const KseedHeader&,std::size_t chunk_bytes);KseedWriter*writer(){return writer_.get();}const std::filesystem::path&session_path()const{return session_path_;}void finish(SessionStats stats,const std::string&profile,const std::string&state_hash);bool active()const{return writer_!=nullptr;}const std::string&error()const{return error_;}
private:std::filesystem::path root_,sessions_,session_path_;std::unique_ptr<KseedWriter>writer_;std::string error_;
};
}
