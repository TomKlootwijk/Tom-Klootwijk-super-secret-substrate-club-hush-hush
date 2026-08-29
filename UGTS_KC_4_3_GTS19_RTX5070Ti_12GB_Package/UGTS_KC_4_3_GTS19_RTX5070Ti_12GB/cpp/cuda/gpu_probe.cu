#include <cuda_runtime.h>

#include <cstddef>
#include <iostream>

int main() {
  int count = 0;
  cudaError_t status = cudaGetDeviceCount(&count);
  if (status != cudaSuccess || count < 1) {
    std::cerr << "No CUDA device available: " << cudaGetErrorString(status) << "\n";
    return 2;
  }
  status = cudaSetDevice(0);
  if (status != cudaSuccess) {
    std::cerr << cudaGetErrorString(status) << "\n";
    return 3;
  }
  cudaDeviceProp properties{};
  cudaGetDeviceProperties(&properties, 0);
  std::size_t free_bytes = 0;
  std::size_t total_bytes = 0;
  cudaMemGetInfo(&free_bytes, &total_bytes);
  std::cout << "{\n"
            << "  \"device_name\": \"" << properties.name << "\",\n"
            << "  \"compute_capability\": \"" << properties.major << "."
            << properties.minor << "\",\n"
            << "  \"multiprocessors\": " << properties.multiProcessorCount
            << ",\n"
            << "  \"free_vram_bytes\": " << free_bytes << ",\n"
            << "  \"total_vram_bytes\": " << total_bytes << "\n"
            << "}\n";
  return 0;
}
