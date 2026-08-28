#pragma once
#include "types.hpp"
#include <cstdint>
#include <vector>
namespace ugts41 {
struct FeatureConfig{std::uint16_t analysis_width=160,analysis_height=90,grid_columns=16,grid_rows=9,feature_budget=96;std::uint8_t gradient_floor=14;};
struct ExtractedFrame{FrameObservation observation{};std::vector<std::uint8_t>analysis_luma;float texture_score=0;};
class SeededFeatureExtractor{
public:SeededFeatureExtractor(std::uint64_t session_seed,FeatureConfig config={});
ExtractedFrame extract(const std::uint8_t*y,std::uint16_t source_width,std::uint16_t source_height,std::int32_t row_stride,std::int32_t pixel_stride,std::uint32_t frame_index,std::uint64_t timestamp_ns,const ImuSample&imu)const;
const FeatureConfig&config()const{return config_;}
private:std::uint64_t seed_;FeatureConfig config_;
};
struct KeyframePolicy{std::uint64_t maximum_interval_ns=1'000'000'000ULL,minimum_interval_ns=150'000'000ULL;std::uint8_t signature_distance=8;float orientation_radians=.09f;std::uint16_t minimum_features=18;};
class KeyframeSelector{public:explicit KeyframeSelector(KeyframePolicy p={}):policy_(p){}bool should_store(const FrameObservation&);void reset();private:KeyframePolicy policy_;bool have_=false;std::uint64_t time_=0,signature_=0;Quatf orientation_{};};
unsigned hamming64(std::uint64_t,std::uint64_t);float quaternion_angle(Quatf,Quatf);
}
