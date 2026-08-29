#include <cuda_runtime.h>

#include <cstddef>
#include <iostream>
#include <string>

namespace {

int ReportCudaFailure(const char *operation, cudaError_t status,
                      int exit_code) {
  std::cerr << operation << " failed: " << cudaGetErrorString(status) << "\n";
  return exit_code;
}

std::string JsonEscape(const char *text) {
  std::string result;
  for (const unsigned char value : std::string(text)) {
    switch (value) {
    case '"':
      result += "\\\"";
      break;
    case '\\':
      result += "\\\\";
      break;
    case '\b':
      result += "\\b";
      break;
    case '\f':
      result += "\\f";
      break;
    case '\n':
      result += "\\n";
      break;
    case '\r':
      result += "\\r";
      break;
    case '\t':
      result += "\\t";
      break;
    default:
      if (value < 0x20U) {
        constexpr char hex[] = "0123456789abcdef";
        result += "\\u00";
        result.push_back(hex[value >> 4U]);
        result.push_back(hex[value & 0x0FU]);
      } else {
        result.push_back(static_cast<char>(value));
      }
    }
  }
  return result;
}

} // namespace

int main() {
  int count = 0;
  cudaError_t status = cudaGetDeviceCount(&count);
  if (status != cudaSuccess)
    return ReportCudaFailure("cudaGetDeviceCount", status, 2);
  if (count < 1) {
    std::cerr << "cudaGetDeviceCount reported no CUDA devices\n";
    return 2;
  }
  status = cudaSetDevice(0);
  if (status != cudaSuccess)
    return ReportCudaFailure("cudaSetDevice", status, 3);
  cudaDeviceProp properties{};
  status = cudaGetDeviceProperties(&properties, 0);
  if (status != cudaSuccess) {
    return ReportCudaFailure("cudaGetDeviceProperties", status, 4);
  }
  std::size_t free_bytes = 0;
  std::size_t total_bytes = 0;
  status = cudaMemGetInfo(&free_bytes, &total_bytes);
  if (status != cudaSuccess)
    return ReportCudaFailure("cudaMemGetInfo", status, 5);
  std::cout << "{\n"
            << "  \"device_name\": \"" << JsonEscape(properties.name) << "\",\n"
            << "  \"compute_capability\": \"" << properties.major << "."
            << properties.minor << "\",\n"
            << "  \"multiprocessors\": " << properties.multiProcessorCount
            << ",\n"
            << "  \"free_vram_bytes\": " << free_bytes << ",\n"
            << "  \"total_vram_bytes\": " << total_bytes << "\n"
            << "}\n";
  return 0;
}
