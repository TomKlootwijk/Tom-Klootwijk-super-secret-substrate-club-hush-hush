#include "packed_kernels.cuh"

#include <cuda_runtime.h>

#include <stdexcept>

namespace ugts_go19::cuda {
namespace {

__global__ void EmptyMaskKernel(const std::uint64_t* black,
                                const std::uint64_t* white,
                                std::uint64_t* empty,
                                std::size_t total_words,
                                std::size_t words_per_state,
                                std::uint64_t tail_mask) {
  const std::size_t index = blockIdx.x * blockDim.x + threadIdx.x;
  if (index >= total_words) return;
  std::uint64_t value = ~(black[index] | white[index]);
  if ((index + 1) % words_per_state == 0) value &= tail_mask;
  empty[index] = value;
}

}  // namespace

void LaunchEmptyMask(const std::uint64_t* black, const std::uint64_t* white,
                     std::uint64_t* empty, std::size_t states,
                     std::size_t words_per_state, std::uint64_t tail_mask,
                     void* stream) {
  if (!black || !white || !empty || states == 0 || words_per_state == 0) {
    throw std::invalid_argument("invalid empty-mask launch arguments");
  }
  const std::size_t total = states * words_per_state;
  constexpr int threads = 256;
  const int blocks = static_cast<int>((total + threads - 1) / threads);
  EmptyMaskKernel<<<blocks, threads, 0, static_cast<cudaStream_t>(stream)>>>(
      black, white, empty, total, words_per_state, tail_mask);
  const auto status = cudaGetLastError();
  if (status != cudaSuccess) {
    throw std::runtime_error(cudaGetErrorString(status));
  }
}

}  // namespace ugts_go19::cuda
