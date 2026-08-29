#include "ugts_chess/cuda_api.hpp"

namespace ugts::chess {

DeviceInfo query_device(int requested_device) {
    DeviceInfo info{};
    info.cuda_compiled = false;
    info.device_available = false;
    info.device_index = requested_device;
    info.error = "binary was built without CUDA; rebuild with -DUGTS_ENABLE_CUDA=ON";
    return info;
}

bool expand_batch_cuda(
    const PackedPosition*, std::size_t, std::uint16_t*, std::uint16_t*, int, std::string& error) {
    error = "CUDA support not compiled";
    return false;
}

}  // namespace ugts::chess
