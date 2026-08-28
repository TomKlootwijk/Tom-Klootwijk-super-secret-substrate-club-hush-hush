#include <cuda.h>

#include <cstddef>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>

namespace fs = std::filesystem;

namespace {

void check(CUresult result, const char *what) {
  if (result == CUDA_SUCCESS)
    return;
  const char *name = nullptr;
  const char *message = nullptr;
  cuGetErrorName(result, &name);
  cuGetErrorString(result, &message);
  throw std::runtime_error(std::string(what) + ": " +
                           (name ? name : "unknown") + " (" +
                           (message ? message : "no message") + ")");
}

}  // namespace

int main(int argc, char **argv) {
  try {
    fs::path output =
        "benchmarks/cuda_vmm_granularity_probe/vmm_granularity.json";
    if (argc == 3 && std::string(argv[1]) == "--out")
      output = argv[2];
    else if (argc != 1)
      throw std::runtime_error("usage: ugts_cuda_vmm_granularity_probe [--out PATH]");

    check(cuInit(0), "cuInit");
    CUdevice device{};
    check(cuDeviceGet(&device, 0), "cuDeviceGet");
    char name[256]{};
    check(cuDeviceGetName(name, sizeof(name), device), "cuDeviceGetName");
    int driver_version = 0;
    check(cuDriverGetVersion(&driver_version), "cuDriverGetVersion");
    int vmm_supported = 0;
    int compression_supported = 0;
    int l2_bytes = 0;
    check(cuDeviceGetAttribute(
              &vmm_supported,
              CU_DEVICE_ATTRIBUTE_VIRTUAL_MEMORY_MANAGEMENT_SUPPORTED, device),
          "cuDeviceGetAttribute(VMM)");
    check(cuDeviceGetAttribute(&compression_supported,
                               CU_DEVICE_ATTRIBUTE_GENERIC_COMPRESSION_SUPPORTED,
                               device),
          "cuDeviceGetAttribute(compression)");
    check(cuDeviceGetAttribute(&l2_bytes, CU_DEVICE_ATTRIBUTE_L2_CACHE_SIZE,
                               device),
          "cuDeviceGetAttribute(L2)");

    CUmemAllocationProp properties{};
    properties.type = CU_MEM_ALLOCATION_TYPE_PINNED;
    properties.requestedHandleTypes = CU_MEM_HANDLE_TYPE_NONE;
    properties.location.type = CU_MEM_LOCATION_TYPE_DEVICE;
    properties.location.id = device;
    std::size_t minimum = 0;
    std::size_t recommended = 0;
    check(cuMemGetAllocationGranularity(
              &minimum, &properties, CU_MEM_ALLOC_GRANULARITY_MINIMUM),
          "cuMemGetAllocationGranularity(minimum)");
    check(cuMemGetAllocationGranularity(
              &recommended, &properties, CU_MEM_ALLOC_GRANULARITY_RECOMMENDED),
          "cuMemGetAllocationGranularity(recommended)");

    fs::create_directories(output.parent_path());
    std::ofstream stream(output);
    if (!stream)
      throw std::runtime_error("cannot open output: " + output.string());
    stream << "{\n"
           << "  \"schema\": \"UGTS-CUDA-VMM-GRANULARITY-1.0\",\n"
           << "  \"device\": \"" << name << "\",\n"
           << "  \"device_ordinal\": 0,\n"
           << "  \"cuda_driver_version\": " << driver_version << ",\n"
           << "  \"l2_bytes\": " << l2_bytes << ",\n"
           << "  \"virtual_memory_management_supported\": "
           << (vmm_supported ? "true" : "false") << ",\n"
           << "  \"generic_compression_supported\": "
           << (compression_supported ? "true" : "false") << ",\n"
           << "  \"allocation_type\": \"pinned device-local VMM\",\n"
           << "  \"minimum_allocation_granularity_bytes\": " << minimum
           << ",\n"
           << "  \"recommended_allocation_granularity_bytes\": "
           << recommended << ",\n"
           << "  \"scope_note\": \"VMM allocation granularities are driver API properties; they do not declare the translation page size used by cudaMalloc or a TLB capacity.\"\n"
           << "}\n";
    std::cout << output.string() << " minimum=" << minimum
              << " recommended=" << recommended
              << " vmm=" << vmm_supported
              << " compression=" << compression_supported << '\n';
    return 0;
  } catch (const std::exception &error) {
    std::cerr << "error: " << error.what() << '\n';
    return 1;
  }
}
