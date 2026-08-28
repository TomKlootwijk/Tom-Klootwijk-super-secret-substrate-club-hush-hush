#pragma once
#include "types.hpp"
#include <array>
#include <cstdint>
#include <filesystem>
#include <span>
#include <string>
#include <vector>
namespace ugts41 {
enum class StorageMode:std::uint16_t{SeedAndDeltas=0,SeedDeltasAndThumbnail=1};
enum class ChunkType:std::uint16_t{Frames=1,Events=2,Checkpoint=3,Summary=4};
struct KseedHeader{std::uint64_t session_seed=0,start_time_ns=0;std::uint16_t analysis_width=160,analysis_height=90,capture_fps_x100=3000,feature_budget=96;StorageMode storage_mode=StorageMode::SeedAndDeltas;std::array<std::uint8_t,32>profile_hash{},calibration_hash{};};
struct KseedReadResult{KseedHeader header{};std::vector<FrameObservation>frames;std::vector<std::vector<std::uint8_t>>thumbnails;std::vector<LedgerEvent>events;SessionStats stats{};bool header_crc_ok=false,chunk_crc_ok=false,chain_ok=false,complete=false;std::string error;};
class KseedWriter{
public:KseedWriter(const std::filesystem::path&,KseedHeader,std::size_t target_chunk_bytes=64U*1024U);~KseedWriter();KseedWriter(const KseedWriter&)=delete;KseedWriter&operator=(const KseedWriter&)=delete;
bool good()const;const std::string&error()const{return error_;}void append_frame(const FrameObservation&,std::span<const std::uint8_t>thumbnail={});void append_event(const LedgerEvent&);void checkpoint(std::span<const std::uint8_t>canonical_state);void close(const SessionStats&);std::uint64_t bytes_written()const{return bytes_written_;}
private:void flush_frames();void flush_events();void write_chunk(ChunkType,std::uint32_t,std::span<const std::uint8_t>);std::filesystem::path path_;KseedHeader header_;std::size_t target_=0;std::vector<std::uint8_t>frames_,events_;std::uint32_t frame_count_=0,event_count_=0,chunk_seq_=0;std::uint64_t previous_time_=0;std::uint32_t previous_index_=0;std::array<std::uint8_t,32>chain_{};std::uint64_t bytes_written_=0;bool closed_=false;std::string error_;class Impl;Impl*impl_=nullptr;
};
KseedReadResult read_kseed(const std::filesystem::path&);
std::vector<std::uint8_t>encode_frame_record(const FrameObservation&,std::uint64_t previous_time,std::uint32_t previous_index,std::span<const std::uint8_t>thumbnail={});
std::vector<std::uint8_t>encode_ledger_event_record(const LedgerEvent&);
}
