#include <cuda.h>

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace fs = std::filesystem;

namespace {

std::string error_text(CUresult result) {
  const char *name = nullptr;
  const char *message = nullptr;
  cuGetErrorName(result, &name);
  cuGetErrorString(result, &message);
  return std::string(name ? name : "unknown") + " (" +
         (message ? message : "no message") + ")";
}

void check(CUresult result, const char *what) {
  if (result != CUDA_SUCCESS)
    throw std::runtime_error(std::string(what) + ": " + error_text(result));
}

struct ModeResult {
  std::string name;
  int requested_compression = 0;
  int effective_compression = -1;
  std::size_t minimum_granularity = 0;
  std::size_t recommended_granularity = 0;
  bool create_succeeded = false;
  bool property_query_succeeded = false;
  bool map_succeeded = false;
  bool read_write_verified = false;
  std::string error;
};

ModeResult run_mode(CUdevice device, const char *name,
                    unsigned char compression_type) {
  ModeResult result{};
  result.name = name;
  result.requested_compression = compression_type;
  CUmemAllocationProp requested{};
  requested.type = CU_MEM_ALLOCATION_TYPE_PINNED;
  requested.requestedHandleTypes = CU_MEM_HANDLE_TYPE_NONE;
  requested.location.type = CU_MEM_LOCATION_TYPE_DEVICE;
  requested.location.id = device;
  requested.allocFlags.compressionType = compression_type;
  CUmemGenericAllocationHandle handle = 0;
  CUdeviceptr address = 0;
  std::size_t mapped_bytes = 0;
  try {
    check(cuMemGetAllocationGranularity(
              &result.minimum_granularity, &requested,
              CU_MEM_ALLOC_GRANULARITY_MINIMUM),
          "cuMemGetAllocationGranularity(minimum)");
    check(cuMemGetAllocationGranularity(
              &result.recommended_granularity, &requested,
              CU_MEM_ALLOC_GRANULARITY_RECOMMENDED),
          "cuMemGetAllocationGranularity(recommended)");
    mapped_bytes = result.minimum_granularity;
    check(cuMemCreate(&handle, mapped_bytes, &requested, 0), "cuMemCreate");
    result.create_succeeded = true;
    CUmemAllocationProp effective{};
    check(cuMemGetAllocationPropertiesFromHandle(&effective, handle),
          "cuMemGetAllocationPropertiesFromHandle");
    result.property_query_succeeded = true;
    result.effective_compression = effective.allocFlags.compressionType;
    check(cuMemAddressReserve(&address, mapped_bytes,
                              result.minimum_granularity, 0, 0),
          "cuMemAddressReserve");
    check(cuMemMap(address, mapped_bytes, 0, handle, 0), "cuMemMap");
    CUmemAccessDesc access{};
    access.location.type = CU_MEM_LOCATION_TYPE_DEVICE;
    access.location.id = device;
    access.flags = CU_MEM_ACCESS_FLAGS_PROT_READWRITE;
    check(cuMemSetAccess(address, mapped_bytes, &access, 1), "cuMemSetAccess");
    result.map_succeeded = true;
    constexpr std::uint32_t pattern = 0x5a6bc7d8u;
    check(cuMemsetD32(address, pattern, mapped_bytes / sizeof(pattern)),
          "cuMemsetD32");
    check(cuCtxSynchronize(), "cuCtxSynchronize");
    std::uint32_t first = 0, last = 0;
    check(cuMemcpyDtoH(&first, address, sizeof(first)), "cuMemcpyDtoH(first)");
    check(cuMemcpyDtoH(&last, address + mapped_bytes - sizeof(last),
                       sizeof(last)),
          "cuMemcpyDtoH(last)");
    result.read_write_verified = first == pattern && last == pattern;
  } catch (const std::exception &exception) {
    result.error = exception.what();
  }
  if (result.map_succeeded)
    cuMemUnmap(address, mapped_bytes);
  if (address != 0)
    cuMemAddressFree(address, mapped_bytes);
  if (handle != 0)
    cuMemRelease(handle);
  return result;
}

void write_json_string(std::ostream &stream, const std::string &text) {
  stream << '"';
  for (const char character : text) {
    if (character == '"' || character == '\\')
      stream << '\\';
    stream << character;
  }
  stream << '"';
}

}  // namespace

int main(int argc, char **argv) {
  try {
    fs::path output =
        "benchmarks/cuda_vmm_compression_probe/vmm_compression.json";
    if (argc == 3 && std::string(argv[1]) == "--out")
      output = argv[2];
    else if (argc != 1)
      throw std::runtime_error(
          "usage: ugts_cuda_vmm_compression_probe [--out PATH]");
    check(cuInit(0), "cuInit");
    CUdevice device{};
    check(cuDeviceGet(&device, 0), "cuDeviceGet");
    CUcontext context{};
    check(cuDevicePrimaryCtxRetain(&context, device),
          "cuDevicePrimaryCtxRetain");
    check(cuCtxSetCurrent(context), "cuCtxSetCurrent");
    char device_name[256]{};
    check(cuDeviceGetName(device_name, sizeof(device_name), device),
          "cuDeviceGetName");
    int driver_version = 0, compression_supported = 0, l2_bytes = 0;
    check(cuDriverGetVersion(&driver_version), "cuDriverGetVersion");
    check(cuDeviceGetAttribute(
              &compression_supported,
              CU_DEVICE_ATTRIBUTE_GENERIC_COMPRESSION_SUPPORTED, device),
          "cuDeviceGetAttribute(compression)");
    check(cuDeviceGetAttribute(&l2_bytes, CU_DEVICE_ATTRIBUTE_L2_CACHE_SIZE,
                               device),
          "cuDeviceGetAttribute(L2)");
    const std::vector<ModeResult> modes = {
        run_mode(device, "non_compressible", CU_MEM_ALLOCATION_COMP_NONE),
        run_mode(device, "generic_compressible",
                 CU_MEM_ALLOCATION_COMP_GENERIC)};
    fs::create_directories(output.parent_path());
    std::ofstream stream(output);
    if (!stream)
      throw std::runtime_error("cannot open output: " + output.string());
    stream << "{\n  \"schema\": \"UGTS-CUDA-VMM-COMPRESSION-PROBE-1.0\",\n"
           << "  \"device\": ";
    write_json_string(stream, device_name);
    stream << ",\n  \"device_ordinal\": 0,\n"
           << "  \"cuda_driver_version\": " << driver_version << ",\n"
           << "  \"l2_bytes\": " << l2_bytes << ",\n"
           << "  \"generic_compression_supported_attribute\": "
           << (compression_supported ? "true" : "false") << ",\n"
           << "  \"compression_enum\": {\"none\": "
           << int(CU_MEM_ALLOCATION_COMP_NONE) << ", \"generic\": "
           << int(CU_MEM_ALLOCATION_COMP_GENERIC) << "},\n"
           << "  \"modes\": [\n";
    for (std::size_t index = 0; index < modes.size(); ++index) {
      const auto &mode = modes[index];
      stream << "    {\"name\": ";
      write_json_string(stream, mode.name);
      stream << ", \"requested_compression\": "
             << mode.requested_compression
             << ", \"effective_compression\": "
             << mode.effective_compression
             << ", \"minimum_granularity_bytes\": "
             << mode.minimum_granularity
             << ", \"recommended_granularity_bytes\": "
             << mode.recommended_granularity
             << ", \"create_succeeded\": "
             << (mode.create_succeeded ? "true" : "false")
             << ", \"property_query_succeeded\": "
             << (mode.property_query_succeeded ? "true" : "false")
             << ", \"map_succeeded\": "
             << (mode.map_succeeded ? "true" : "false")
             << ", \"read_write_verified\": "
             << (mode.read_write_verified ? "true" : "false")
             << ", \"error\": ";
      write_json_string(stream, mode.error);
      stream << '}' << (index + 1 == modes.size() ? "\n" : ",\n");
    }
    stream << "  ],\n"
           << "  \"scope_note\": \"The effective property verifies whether the driver granted the compressible allocation hint. It does not expose the achieved hardware compression ratio, L2 compressed bytes, DRAM traffic or compression counters.\"\n"
           << "}\n";
    for (const auto &mode : modes)
      std::cout << mode.name << " requested=" << mode.requested_compression
                << " effective=" << mode.effective_compression
                << " granularity=" << mode.minimum_granularity
                << " created=" << mode.create_succeeded
                << " mapped=" << mode.map_succeeded
                << " verified=" << mode.read_write_verified
                << (mode.error.empty() ? "" : " error=" + mode.error) << '\n';
    check(cuDevicePrimaryCtxRelease(device), "cuDevicePrimaryCtxRelease");
    return modes[0].read_write_verified && modes[1].read_write_verified &&
                   modes[0].effective_compression ==
                       CU_MEM_ALLOCATION_COMP_NONE &&
                   modes[1].effective_compression ==
                       CU_MEM_ALLOCATION_COMP_GENERIC
               ? 0
               : 2;
  } catch (const std::exception &error) {
    std::cerr << "error: " << error.what() << '\n';
    return 1;
  }
}
