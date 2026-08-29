#include "ugts_chess/cuda_api.hpp"

#include <cuda_runtime.h>

#include <algorithm>
#include <sstream>

namespace ugts::chess {
namespace {

__global__ void expand_scalar_kernel(
    const PackedPosition* positions,
    std::size_t count,
    std::uint16_t* moves,
    std::uint16_t* counts) {
    const std::size_t index = static_cast<std::size_t>(blockIdx.x) * blockDim.x + threadIdx.x;
    if (index >= count) return;
    MoveList list{};
    generate_legal_moves(positions[index], list);
    counts[index] = list.count;
    std::uint16_t* destination = moves + index * kMaxMoves;
    for (std::uint16_t move_index = 0; move_index < list.count; ++move_index) {
        destination[move_index] = list.moves[move_index];
    }
    for (std::uint16_t move_index = list.count; move_index < kMaxMoves; ++move_index) {
        destination[move_index] = 0;
    }
}

std::string cuda_error(cudaError_t code, const char* stage) {
    std::ostringstream out;
    out << stage << ": " << cudaGetErrorName(code) << " - " << cudaGetErrorString(code);
    return out.str();
}

}  // namespace

DeviceInfo query_device(int requested_device) {
    DeviceInfo info{};
    info.cuda_compiled = true;
    info.device_index = requested_device;
    int count = 0;
    cudaError_t code = cudaGetDeviceCount(&count);
    if (code != cudaSuccess) {
        info.error = cuda_error(code, "cudaGetDeviceCount");
        return info;
    }
    if (requested_device < 0 || requested_device >= count) {
        info.error = "requested CUDA device is unavailable";
        return info;
    }
    cudaDeviceProp properties{};
    code = cudaGetDeviceProperties(&properties, requested_device);
    if (code != cudaSuccess) {
        info.error = cuda_error(code, "cudaGetDeviceProperties");
        return info;
    }
    code = cudaSetDevice(requested_device);
    if (code != cudaSuccess) {
        info.error = cuda_error(code, "cudaSetDevice");
        return info;
    }
    std::size_t free_bytes = 0;
    std::size_t total_bytes = 0;
    code = cudaMemGetInfo(&free_bytes, &total_bytes);
    if (code != cudaSuccess) {
        info.error = cuda_error(code, "cudaMemGetInfo");
        return info;
    }
    info.device_available = true;
    info.compute_major = properties.major;
    info.compute_minor = properties.minor;
    info.total_memory = total_bytes;
    info.free_memory = free_bytes;
    info.multiprocessors = properties.multiProcessorCount;
    info.warp_size = properties.warpSize;
    info.max_threads_per_block = properties.maxThreadsPerBlock;
    info.name = properties.name;
    return info;
}

bool expand_batch_cuda(
    const PackedPosition* positions,
    std::size_t count,
    std::uint16_t* output_moves,
    std::uint16_t* output_counts,
    int device_index,
    std::string& error) {
    if (count == 0) return true;
    cudaError_t code = cudaSetDevice(device_index);
    if (code != cudaSuccess) { error = cuda_error(code, "cudaSetDevice"); return false; }

    PackedPosition* device_positions = nullptr;
    std::uint16_t* device_moves = nullptr;
    std::uint16_t* device_counts = nullptr;
    const std::size_t positions_bytes = count * sizeof(PackedPosition);
    const std::size_t moves_bytes = count * kMaxMoves * sizeof(std::uint16_t);
    const std::size_t counts_bytes = count * sizeof(std::uint16_t);

    auto cleanup = [&]() {
        if (device_positions) cudaFree(device_positions);
        if (device_moves) cudaFree(device_moves);
        if (device_counts) cudaFree(device_counts);
    };

    code = cudaMalloc(&device_positions, positions_bytes);
    if (code != cudaSuccess) { error = cuda_error(code, "cudaMalloc positions"); cleanup(); return false; }
    code = cudaMalloc(&device_moves, moves_bytes);
    if (code != cudaSuccess) { error = cuda_error(code, "cudaMalloc moves"); cleanup(); return false; }
    code = cudaMalloc(&device_counts, counts_bytes);
    if (code != cudaSuccess) { error = cuda_error(code, "cudaMalloc counts"); cleanup(); return false; }
    code = cudaMemcpy(device_positions, positions, positions_bytes, cudaMemcpyHostToDevice);
    if (code != cudaSuccess) { error = cuda_error(code, "cudaMemcpy positions"); cleanup(); return false; }

    constexpr int threads = 256;
    const int blocks = static_cast<int>((count + threads - 1) / threads);
    expand_scalar_kernel<<<blocks, threads>>>(device_positions, count, device_moves, device_counts);
    code = cudaGetLastError();
    if (code != cudaSuccess) { error = cuda_error(code, "kernel launch"); cleanup(); return false; }
    code = cudaDeviceSynchronize();
    if (code != cudaSuccess) { error = cuda_error(code, "kernel execution"); cleanup(); return false; }
    code = cudaMemcpy(output_counts, device_counts, counts_bytes, cudaMemcpyDeviceToHost);
    if (code != cudaSuccess) { error = cuda_error(code, "cudaMemcpy counts"); cleanup(); return false; }
    code = cudaMemcpy(output_moves, device_moves, moves_bytes, cudaMemcpyDeviceToHost);
    if (code != cudaSuccess) { error = cuda_error(code, "cudaMemcpy moves"); cleanup(); return false; }
    cleanup();
    return true;
}

}  // namespace ugts::chess
