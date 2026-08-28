#include "ugts_vulkan_min.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <numeric>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace fs = std::filesystem;
using Clock = std::chrono::steady_clock;

namespace {

void check(VkResult result, const char *what) {
  if (result != VK_SUCCESS)
    throw std::runtime_error(std::string(what) + " failed with VkResult " +
                             std::to_string(int(result)));
}
double elapsed_ms(Clock::time_point a, Clock::time_point b) {
  return std::chrono::duration<double, std::milli>(b - a).count();
}
double percentile(std::vector<double> values, double q) {
  std::sort(values.begin(), values.end());
  const double x = q * double(values.size() - 1);
  const auto lo = std::size_t(std::floor(x)), hi = std::size_t(std::ceil(x));
  const double t = x - double(lo);
  return values[lo] * (1.0 - t) + values[hi] * t;
}
std::uint32_t api_major(std::uint32_t v) { return (v >> 22u) & 0x7fu; }
std::uint32_t api_minor(std::uint32_t v) { return (v >> 12u) & 0x3ffu; }
std::uint32_t api_patch(std::uint32_t v) { return v & 0xfffu; }
std::uint32_t mix32(std::uint32_t x) {
  x ^= x >> 16;
  x *= 0x7feb352du;
  x ^= x >> 15;
  x *= 0x846ca68bu;
  x ^= x >> 16;
  return x;
}

std::vector<std::uint32_t> read_spirv(const fs::path &path) {
  std::ifstream f(path, std::ios::binary | std::ios::ate);
  if (!f)
    throw std::runtime_error("cannot read SPIR-V: " + path.string());
  const auto size = f.tellg();
  if (size <= 0 || (std::uint64_t(size) % 4) != 0)
    throw std::runtime_error("invalid SPIR-V size");
  std::vector<std::uint32_t> w(std::size_t(size) / 4);
  f.seekg(0);
  f.read(reinterpret_cast<char *>(w.data()), size);
  if (!f || w.empty() || w[0] != 0x07230203u)
    throw std::runtime_error("invalid SPIR-V magic");
  return w;
}

struct Args {
  fs::path spirv_dir = "spirv", out_dir = "vulkan_lut_benchmark_out";
  std::vector<std::size_t> entries = {2048,    16384,    131072,   1048576,
                                      8388608, 16777216, 33554432, 67108864};
  std::size_t min_candidates = 4194304, l2_bytes = 0;
  std::size_t latency_invocations = 65536;
  int warmup = 10, warmup_ms = 500, iterations = 30;
  bool reverse = false, latency_only = false;
};
std::vector<std::size_t> parse_sizes(const std::string &text) {
  std::stringstream ss(text);
  std::string part;
  std::vector<std::size_t> out;
  while (std::getline(ss, part, ','))
    if (!part.empty())
      out.push_back(std::stoull(part));
  if (out.empty())
    throw std::runtime_error("empty size list");
  return out;
}
Args parse_args(int argc, char **argv) {
  Args a;
  for (int i = 1; i < argc; ++i) {
    const std::string arg = argv[i];
    auto value = [&](const char *name) {
      if (i + 1 >= argc)
        throw std::runtime_error(std::string("missing value for ") + name);
      return std::string(argv[++i]);
    };
    if (arg == "--spirv-dir")
      a.spirv_dir = value("--spirv-dir");
    else if (arg == "--out-dir")
      a.out_dir = value("--out-dir");
    else if (arg == "--entries")
      a.entries = parse_sizes(value("--entries"));
    else if (arg == "--min-candidates")
      a.min_candidates = std::stoull(value("--min-candidates"));
    else if (arg == "--latency-invocations")
      a.latency_invocations = std::stoull(value("--latency-invocations"));
    else if (arg == "--l2-bytes")
      a.l2_bytes = std::stoull(value("--l2-bytes"));
    else if (arg == "--warmup")
      a.warmup = std::stoi(value("--warmup"));
    else if (arg == "--warmup-ms")
      a.warmup_ms = std::stoi(value("--warmup-ms"));
    else if (arg == "--iterations")
      a.iterations = std::stoi(value("--iterations"));
    else if (arg == "--reverse")
      a.reverse = true;
    else if (arg == "--latency-only")
      a.latency_only = true;
    else
      throw std::runtime_error("unknown argument: " + arg);
  }
  if (a.warmup < 0 || a.warmup_ms < 0 || a.iterations < 1 ||
      a.min_candidates < 1 || a.latency_invocations < 1 ||
      a.latency_invocations > std::numeric_limits<std::uint32_t>::max())
    throw std::runtime_error("invalid run parameters");
  for (auto n : a.entries) {
    if (n < 2 || n > std::numeric_limits<std::uint32_t>::max())
      throw std::runtime_error("entries must fit the uint32 range");
    if (!a.latency_only && (n & (n - 1)))
      throw std::runtime_error("LUT entries must be powers of two");
  }
  return a;
}

class VulkanContext {
public:
  VulkanContext() {
    VkApplicationInfo app{};
    app.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO;
    app.pApplicationName = "UGTS Log LUT Texture-Cache Probe";
    app.applicationVersion = 1;
    app.pEngineName = "UGTS-GN";
    app.engineVersion = 1;
    app.apiVersion = VK_API_VERSION_1_1;
    VkInstanceCreateInfo ici{};
    ici.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO;
    ici.pApplicationInfo = &app;
    VkResult ir = vkCreateInstance(&ici, nullptr, &instance_);
    if (ir == VK_ERROR_INCOMPATIBLE_DRIVER) {
      app.apiVersion = VK_API_VERSION_1_0;
      check(vkCreateInstance(&ici, nullptr, &instance_),
            "vkCreateInstance(1.0)");
    } else
      check(ir, "vkCreateInstance");
    std::uint32_t count = 0;
    check(vkEnumeratePhysicalDevices(instance_, &count, nullptr),
          "vkEnumeratePhysicalDevices(count)");
    if (!count)
      throw std::runtime_error("no Vulkan devices");
    std::vector<VkPhysicalDevice> devices(count);
    check(vkEnumeratePhysicalDevices(instance_, &count, devices.data()),
          "vkEnumeratePhysicalDevices(list)");
    int best = -1;
    for (auto d : devices) {
      VkPhysicalDeviceProperties p{};
      vkGetPhysicalDeviceProperties(d, &p);
      int rank = p.deviceType == VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU     ? 4
                 : p.deviceType == VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU ? 3
                 : p.deviceType == VK_PHYSICAL_DEVICE_TYPE_VIRTUAL_GPU    ? 2
                 : p.deviceType == VK_PHYSICAL_DEVICE_TYPE_CPU            ? 1
                                                                          : 0;
      if (rank > best) {
        best = rank;
        physical_ = d;
        props_ = p;
      }
    }
    std::uint32_t qcount = 0;
    vkGetPhysicalDeviceQueueFamilyProperties(physical_, &qcount, nullptr);
    std::vector<VkQueueFamilyProperties> qp(qcount);
    vkGetPhysicalDeviceQueueFamilyProperties(physical_, &qcount, qp.data());
    bool found = false;
    for (std::uint32_t i = 0; i < qcount; ++i)
      if (qp[i].queueCount && (qp[i].queueFlags & VK_QUEUE_COMPUTE_BIT)) {
        queue_family_ = i;
        timestamp_bits_ = qp[i].timestampValidBits;
        found = true;
        break;
      }
    if (!found)
      throw std::runtime_error("no compute queue");
    std::uint32_t extension_count = 0;
    check(vkEnumerateDeviceExtensionProperties(physical_, nullptr,
                                                &extension_count, nullptr),
          "vkEnumerateDeviceExtensionProperties(count)");
    std::vector<VkExtensionProperties> extensions(extension_count);
    if (extension_count)
      check(vkEnumerateDeviceExtensionProperties(
                physical_, nullptr, &extension_count, extensions.data()),
            "vkEnumerateDeviceExtensionProperties(list)");
    const bool has_shader_clock_extension =
        std::any_of(extensions.begin(), extensions.end(), [](const auto &x) {
          return std::strcmp(x.extensionName, "VK_KHR_shader_clock") == 0;
        });
    VkPhysicalDeviceShaderClockFeaturesKHR available_clock{};
    available_clock.sType =
        VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SHADER_CLOCK_FEATURES_KHR;
    VkPhysicalDeviceFeatures2 available_features{};
    available_features.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2;
    available_features.pNext =
        has_shader_clock_extension ? &available_clock : nullptr;
    vkGetPhysicalDeviceFeatures2(physical_, &available_features);
    shader_device_clock_ =
        has_shader_clock_extension && available_clock.shaderDeviceClock;
    const float priority = 1;
    VkDeviceQueueCreateInfo qci{};
    qci.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO;
    qci.queueFamilyIndex = queue_family_;
    qci.queueCount = 1;
    qci.pQueuePriorities = &priority;
    VkDeviceCreateInfo dci{};
    dci.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO;
    dci.queueCreateInfoCount = 1;
    dci.pQueueCreateInfos = &qci;
    const char *shader_clock_extension = "VK_KHR_shader_clock";
    VkPhysicalDeviceShaderClockFeaturesKHR enabled_clock{};
    enabled_clock.sType =
        VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SHADER_CLOCK_FEATURES_KHR;
    enabled_clock.shaderDeviceClock = shader_device_clock_ ? VK_TRUE : VK_FALSE;
    if (shader_device_clock_) {
      dci.pNext = &enabled_clock;
      dci.enabledExtensionCount = 1;
      dci.ppEnabledExtensionNames = &shader_clock_extension;
    }
    check(vkCreateDevice(physical_, &dci, nullptr, &device_), "vkCreateDevice");
    vkGetDeviceQueue(device_, queue_family_, 0, &queue_);
    vkGetPhysicalDeviceMemoryProperties(physical_, &mem_props_);
    VkCommandPoolCreateInfo cpci{};
    cpci.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO;
    cpci.flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;
    cpci.queueFamilyIndex = queue_family_;
    check(vkCreateCommandPool(device_, &cpci, nullptr, &command_pool_),
          "vkCreateCommandPool");
  }
  ~VulkanContext() {
    if (device_) {
      vkDeviceWaitIdle(device_);
      if (command_pool_)
        vkDestroyCommandPool(device_, command_pool_, nullptr);
      vkDestroyDevice(device_, nullptr);
    }
    if (instance_)
      vkDestroyInstance(instance_, nullptr);
  }
  std::uint32_t memory_type(std::uint32_t bits,
                            VkMemoryPropertyFlags required) const {
    for (std::uint32_t i = 0; i < mem_props_.memoryTypeCount; ++i)
      if ((bits & (1u << i)) &&
          (mem_props_.memoryTypes[i].propertyFlags & required) == required)
        return i;
    throw std::runtime_error("compatible memory type not found");
  }
  VkDevice device() const { return device_; }
  VkQueue queue() const { return queue_; }
  VkCommandPool command_pool() const { return command_pool_; }
  std::uint32_t timestamp_bits() const { return timestamp_bits_; }
  float timestamp_period() const { return props_.limits.timestampPeriod; }
  bool shader_device_clock() const { return shader_device_clock_; }
  const VkPhysicalDeviceProperties &properties() const { return props_; }

private:
  VkInstance instance_ = VK_NULL_HANDLE;
  VkPhysicalDevice physical_ = VK_NULL_HANDLE;
  VkDevice device_ = VK_NULL_HANDLE;
  VkQueue queue_ = VK_NULL_HANDLE;
  VkCommandPool command_pool_ = VK_NULL_HANDLE;
  VkPhysicalDeviceProperties props_{};
  VkPhysicalDeviceMemoryProperties mem_props_{};
  std::uint32_t queue_family_ = 0, timestamp_bits_ = 0;
  bool shader_device_clock_ = false;
};

struct Buffer {
  const VulkanContext *ctx = nullptr;
  VkBuffer buffer = VK_NULL_HANDLE;
  VkDeviceMemory memory = VK_NULL_HANDLE;
  VkDeviceSize size = 0;
  void *mapped = nullptr;
  Buffer(const VulkanContext &c, VkDeviceSize bytes, VkBufferUsageFlags usage,
         VkMemoryPropertyFlags memory_flags, bool map)
      : ctx(&c), size(bytes) {
    VkBufferCreateInfo bci{};
    bci.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
    bci.size = bytes;
    bci.usage = usage;
    bci.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    check(vkCreateBuffer(c.device(), &bci, nullptr, &buffer), "vkCreateBuffer");
    VkMemoryRequirements req{};
    vkGetBufferMemoryRequirements(c.device(), buffer, &req);
    VkMemoryAllocateInfo mai{};
    mai.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    mai.allocationSize = req.size;
    mai.memoryTypeIndex = c.memory_type(req.memoryTypeBits, memory_flags);
    check(vkAllocateMemory(c.device(), &mai, nullptr, &memory),
          "vkAllocateMemory");
    check(vkBindBufferMemory(c.device(), buffer, memory, 0),
          "vkBindBufferMemory");
    if (map)
      check(vkMapMemory(c.device(), memory, 0, bytes, 0, &mapped),
            "vkMapMemory");
  }
  Buffer(const Buffer &) = delete;
  Buffer &operator=(const Buffer &) = delete;
  ~Buffer() {
    if (!ctx)
      return;
    if (mapped)
      vkUnmapMemory(ctx->device(), memory);
    if (buffer)
      vkDestroyBuffer(ctx->device(), buffer, nullptr);
    if (memory)
      vkFreeMemory(ctx->device(), memory, nullptr);
  }
};

template <class Record>
double submit_once(const VulkanContext &ctx, const char *label, Record record) {
  VkCommandBufferAllocateInfo cai{};
  cai.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
  cai.commandPool = ctx.command_pool();
  cai.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
  cai.commandBufferCount = 1;
  VkCommandBuffer cmd = VK_NULL_HANDLE;
  check(vkAllocateCommandBuffers(ctx.device(), &cai, &cmd),
        "vkAllocateCommandBuffers");
  VkCommandBufferBeginInfo bi{};
  bi.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
  bi.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
  check(vkBeginCommandBuffer(cmd, &bi), "vkBeginCommandBuffer");
  record(cmd);
  check(vkEndCommandBuffer(cmd), "vkEndCommandBuffer");
  VkFenceCreateInfo fci{};
  fci.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO;
  VkFence fence = VK_NULL_HANDLE;
  check(vkCreateFence(ctx.device(), &fci, nullptr, &fence), "vkCreateFence");
  VkSubmitInfo si{};
  si.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
  si.commandBufferCount = 1;
  si.pCommandBuffers = &cmd;
  auto a = Clock::now();
  check(vkQueueSubmit(ctx.queue(), 1, &si, fence), label);
  check(vkWaitForFences(ctx.device(), 1, &fence, VK_TRUE,
                        std::numeric_limits<std::uint64_t>::max()),
        "vkWaitForFences");
  auto b = Clock::now();
  vkDestroyFence(ctx.device(), fence, nullptr);
  vkFreeCommandBuffers(ctx.device(), ctx.command_pool(), 1, &cmd);
  return elapsed_ms(a, b);
}

struct Program {
  VkShaderModule module = VK_NULL_HANDLE;
  VkPipelineCache cache = VK_NULL_HANDLE;
  VkPipeline pipeline = VK_NULL_HANDLE;
  std::size_t spv_bytes = 0, cache_bytes = 0;
  double cold_ms = 0, cached_ms = 0;
};
Program make_program(const VulkanContext &ctx, VkPipelineLayout layout,
                     const fs::path &spv_path) {
  const auto spv = read_spirv(spv_path);
  Program p{};
  p.spv_bytes = spv.size() * 4;
  VkShaderModuleCreateInfo sm{};
  sm.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO;
  sm.codeSize = p.spv_bytes;
  sm.pCode = spv.data();
  check(vkCreateShaderModule(ctx.device(), &sm, nullptr, &p.module),
        "vkCreateShaderModule");
  VkPipelineCacheCreateInfo pci{};
  pci.sType = VK_STRUCTURE_TYPE_PIPELINE_CACHE_CREATE_INFO;
  check(vkCreatePipelineCache(ctx.device(), &pci, nullptr, &p.cache),
        "vkCreatePipelineCache");
  VkPipelineShaderStageCreateInfo stage{};
  stage.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
  stage.stage = VK_SHADER_STAGE_COMPUTE_BIT;
  stage.module = p.module;
  stage.pName = "main";
  VkComputePipelineCreateInfo ci{};
  ci.sType = VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO;
  ci.stage = stage;
  ci.layout = layout;
  auto a = Clock::now();
  check(vkCreateComputePipelines(ctx.device(), p.cache, 1, &ci, nullptr,
                                 &p.pipeline),
        "vkCreateComputePipelines(cold)");
  auto b = Clock::now();
  p.cold_ms = elapsed_ms(a, b);
  std::size_t bytes = 0;
  check(vkGetPipelineCacheData(ctx.device(), p.cache, &bytes, nullptr),
        "vkGetPipelineCacheData(size)");
  std::vector<std::uint8_t> blob(bytes);
  if (bytes)
    check(vkGetPipelineCacheData(ctx.device(), p.cache, &bytes, blob.data()),
          "vkGetPipelineCacheData(data)");
  p.cache_bytes = bytes;
  vkDestroyPipeline(ctx.device(), p.pipeline, nullptr);
  p.pipeline = VK_NULL_HANDLE;
  vkDestroyPipelineCache(ctx.device(), p.cache, nullptr);
  p.cache = VK_NULL_HANDLE;
  VkPipelineCacheCreateInfo warm{};
  warm.sType = VK_STRUCTURE_TYPE_PIPELINE_CACHE_CREATE_INFO;
  warm.initialDataSize = bytes;
  warm.pInitialData = blob.data();
  check(vkCreatePipelineCache(ctx.device(), &warm, nullptr, &p.cache),
        "vkCreatePipelineCache(reload)");
  a = Clock::now();
  check(vkCreateComputePipelines(ctx.device(), p.cache, 1, &ci, nullptr,
                                 &p.pipeline),
        "vkCreateComputePipelines(cached)");
  b = Clock::now();
  p.cached_ms = elapsed_ms(a, b);
  return p;
}
void destroy_program(const VulkanContext &ctx, Program &p) {
  if (p.pipeline)
    vkDestroyPipeline(ctx.device(), p.pipeline, nullptr);
  if (p.cache)
    vkDestroyPipelineCache(ctx.device(), p.cache, nullptr);
  if (p.module)
    vkDestroyShaderModule(ctx.device(), p.module, nullptr);
}

std::vector<std::uint32_t> make_log_lut(std::size_t entries) {
  std::vector<std::uint32_t> words(1 + (entries + 1) / 2);
  words[0] = std::uint32_t(entries - 1);
  const double denominator = std::log2(double(entries));
  for (std::size_t i = 0; i < entries; ++i) {
    const auto code = std::uint32_t(
        std::llround(65535.0 * std::log2(1.0 + double(i)) / denominator));
    words[1 + (i >> 1)] |= (code & 0xffffu) << ((i & 1u) * 16u);
  }
  return words;
}

struct Row {
  std::string source, pattern;
  std::size_t entries = 0, table_bytes = 0, candidates = 0, validated = 0;
  double l2_fraction = 0, setup_ms = 0, upload_ms = 0, readback_ms = 0,
         device_min_ms = 0, device_mean_ms = 0, device_p50_ms = 0,
         device_p95_ms = 0, device_p99_ms = 0, device_max_ms = 0,
         lookup_mps = 0, logical_gbps = 0;
  bool valid = false;
};

Row run_one(const VulkanContext &ctx, VkDescriptorSetLayout dsl,
            VkPipelineLayout layout, VkPipeline pipeline,
            const std::string &source, const std::string &pattern,
            bool random_access, std::size_t entries,
            std::size_t min_candidates, std::size_t l2_bytes, int warmup,
            int warmup_ms, int iterations) {
  const auto setup0 = Clock::now();
  auto words = make_log_lut(entries);
  const std::size_t table_bytes = words.size() * 4,
                    candidates = std::max(entries, min_candidates),
                    output_bytes = candidates * 4;
  Buffer table_upload(ctx, table_bytes, VK_BUFFER_USAGE_TRANSFER_SRC_BIT,
                      VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT |
                          VK_MEMORY_PROPERTY_HOST_COHERENT_BIT,
                      true);
  Buffer output_readback(ctx, output_bytes, VK_BUFFER_USAGE_TRANSFER_DST_BIT,
                         VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT |
                             VK_MEMORY_PROPERTY_HOST_COHERENT_BIT,
                         true);
  Buffer table(ctx, table_bytes,
               VK_BUFFER_USAGE_UNIFORM_TEXEL_BUFFER_BIT |
                   VK_BUFFER_USAGE_STORAGE_BUFFER_BIT |
                   VK_BUFFER_USAGE_TRANSFER_DST_BIT,
               VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT, false);
  Buffer output(ctx, output_bytes,
                VK_BUFFER_USAGE_STORAGE_BUFFER_BIT |
                    VK_BUFFER_USAGE_TRANSFER_SRC_BIT,
                VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT, false);
  std::memcpy(table_upload.mapped, words.data(), table_bytes);
  const double upload_ms =
      submit_once(ctx, "vkQueueSubmit(upload)", [&](VkCommandBuffer cmd) {
        VkBufferCopy copy{0, 0, table_bytes};
        vkCmdCopyBuffer(cmd, table_upload.buffer, table.buffer, 1, &copy);
        VkBufferMemoryBarrier barrier{};
        barrier.sType = VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER;
        barrier.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
        barrier.dstAccessMask = VK_ACCESS_SHADER_READ_BIT;
        barrier.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
        barrier.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
        barrier.buffer = table.buffer;
        barrier.offset = 0;
        barrier.size = VK_WHOLE_SIZE;
        vkCmdPipelineBarrier(cmd, VK_PIPELINE_STAGE_TRANSFER_BIT,
                             VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, 0, 0,
                             nullptr, 1, &barrier, 0, nullptr);
      });
  VkBufferViewCreateInfo bvci{};
  bvci.sType = VK_STRUCTURE_TYPE_BUFFER_VIEW_CREATE_INFO;
  bvci.buffer = table.buffer;
  bvci.format = VK_FORMAT_R32_UINT;
  bvci.offset = 0;
  bvci.range = table_bytes;
  VkBufferView view = VK_NULL_HANDLE;
  check(vkCreateBufferView(ctx.device(), &bvci, nullptr, &view),
        "vkCreateBufferView");
  VkDescriptorPoolSize pool_sizes[2] = {
      {VK_DESCRIPTOR_TYPE_UNIFORM_TEXEL_BUFFER, 1},
      {VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 2}};
  VkDescriptorPoolCreateInfo dpci{};
  dpci.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO;
  dpci.maxSets = 1;
  dpci.poolSizeCount = 2;
  dpci.pPoolSizes = pool_sizes;
  VkDescriptorPool pool = VK_NULL_HANDLE;
  check(vkCreateDescriptorPool(ctx.device(), &dpci, nullptr, &pool),
        "vkCreateDescriptorPool");
  VkDescriptorSetAllocateInfo dsai{};
  dsai.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO;
  dsai.descriptorPool = pool;
  dsai.descriptorSetCount = 1;
  dsai.pSetLayouts = &dsl;
  VkDescriptorSet set = VK_NULL_HANDLE;
  check(vkAllocateDescriptorSets(ctx.device(), &dsai, &set),
        "vkAllocateDescriptorSets");
  VkDescriptorBufferInfo output_info{output.buffer, 0, output.size};
  VkDescriptorBufferInfo table_info{table.buffer, 0, table.size};
  VkWriteDescriptorSet writes[3]{};
  writes[0].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
  writes[0].dstSet = set;
  writes[0].dstBinding = 0;
  writes[0].descriptorCount = 1;
  writes[0].descriptorType = VK_DESCRIPTOR_TYPE_UNIFORM_TEXEL_BUFFER;
  writes[0].pTexelBufferView = &view;
  writes[1].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
  writes[1].dstSet = set;
  writes[1].dstBinding = 1;
  writes[1].descriptorCount = 1;
  writes[1].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;
  writes[1].pBufferInfo = &output_info;
  writes[2].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
  writes[2].dstSet = set;
  writes[2].dstBinding = 2;
  writes[2].descriptorCount = 1;
  writes[2].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;
  writes[2].pBufferInfo = &table_info;
  vkUpdateDescriptorSets(ctx.device(), 3, writes, 0, nullptr);
  VkCommandBufferAllocateInfo cai{};
  cai.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
  cai.commandPool = ctx.command_pool();
  cai.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
  cai.commandBufferCount = 1;
  VkCommandBuffer cmd = VK_NULL_HANDLE;
  check(vkAllocateCommandBuffers(ctx.device(), &cai, &cmd),
        "vkAllocateCommandBuffers");
  VkQueryPoolCreateInfo qpci{};
  qpci.sType = VK_STRUCTURE_TYPE_QUERY_POOL_CREATE_INFO;
  qpci.queryType = VK_QUERY_TYPE_TIMESTAMP;
  qpci.queryCount = 2;
  VkQueryPool qp = VK_NULL_HANDLE;
  check(vkCreateQueryPool(ctx.device(), &qpci, nullptr, &qp),
        "vkCreateQueryPool");
  VkCommandBufferBeginInfo bi{};
  bi.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
  bi.flags = VK_COMMAND_BUFFER_USAGE_SIMULTANEOUS_USE_BIT;
  check(vkBeginCommandBuffer(cmd, &bi), "vkBeginCommandBuffer");
  vkCmdResetQueryPool(cmd, qp, 0, 2);
  vkCmdWriteTimestamp(cmd, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, qp, 0);
  vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_COMPUTE, pipeline);
  vkCmdBindDescriptorSets(cmd, VK_PIPELINE_BIND_POINT_COMPUTE, layout, 0, 1,
                          &set, 0, nullptr);
  vkCmdDispatch(cmd, std::uint32_t((candidates + 255) / 256), 1, 1);
  vkCmdWriteTimestamp(cmd, VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT, qp, 1);
  check(vkEndCommandBuffer(cmd), "vkEndCommandBuffer");
  VkFenceCreateInfo fci{};
  fci.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO;
  VkFence fence = VK_NULL_HANDLE;
  check(vkCreateFence(ctx.device(), &fci, nullptr, &fence), "vkCreateFence");
  VkSubmitInfo si{};
  si.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
  si.commandBufferCount = 1;
  si.pCommandBuffers = &cmd;
  const auto setup1 = Clock::now();
  auto submit = [&]() {
    check(vkResetFences(ctx.device(), 1, &fence), "vkResetFences");
    check(vkQueueSubmit(ctx.queue(), 1, &si, fence), "vkQueueSubmit");
    check(vkWaitForFences(ctx.device(), 1, &fence, VK_TRUE,
                          std::numeric_limits<std::uint64_t>::max()),
          "vkWaitForFences");
    std::uint64_t ticks[2]{};
    check(vkGetQueryPoolResults(ctx.device(), qp, 0, 2, sizeof(ticks), ticks,
                                sizeof(std::uint64_t),
                                VK_QUERY_RESULT_64_BIT |
                                    VK_QUERY_RESULT_WAIT_BIT),
          "vkGetQueryPoolResults");
    std::uint64_t delta =
        ctx.timestamp_bits() >= 64
            ? ticks[1] - ticks[0]
            : (ticks[1] - ticks[0]) &
                  ((std::uint64_t(1) << ctx.timestamp_bits()) - 1);
    return double(delta) * ctx.timestamp_period() / 1e6;
  };
  int warmup_submissions = 0;
  const auto warmup_start = Clock::now();
  while (warmup_submissions < warmup ||
         elapsed_ms(warmup_start, Clock::now()) < warmup_ms) {
    submit();
    ++warmup_submissions;
  }
  std::vector<double> times;
  times.reserve(iterations);
  for (int i = 0; i < iterations; ++i)
    times.push_back(submit());
  const double readback_ms = submit_once(
      ctx, "vkQueueSubmit(readback)", [&](VkCommandBuffer transfer_cmd) {
        VkBufferMemoryBarrier a{};
        a.sType = VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER;
        a.srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT;
        a.dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT;
        a.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
        a.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
        a.buffer = output.buffer;
        a.offset = 0;
        a.size = VK_WHOLE_SIZE;
        vkCmdPipelineBarrier(transfer_cmd, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
                             VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 0, nullptr, 1,
                             &a, 0, nullptr);
        VkBufferCopy copy{0, 0, output_bytes};
        vkCmdCopyBuffer(transfer_cmd, output.buffer, output_readback.buffer, 1,
                        &copy);
        VkBufferMemoryBarrier b{};
        b.sType = VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER;
        b.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
        b.dstAccessMask = VK_ACCESS_HOST_READ_BIT;
        b.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
        b.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
        b.buffer = output_readback.buffer;
        b.offset = 0;
        b.size = VK_WHOLE_SIZE;
        vkCmdPipelineBarrier(transfer_cmd, VK_PIPELINE_STAGE_TRANSFER_BIT,
                             VK_PIPELINE_STAGE_HOST_BIT, 0, 0, nullptr, 1, &b,
                             0, nullptr);
      });
  const auto *actual =
      static_cast<const std::uint32_t *>(output_readback.mapped);
  std::size_t validated = 0;
  for (std::size_t i = 0; i < candidates; ++i) {
    const std::uint32_t logical =
        (random_access ? mix32(std::uint32_t(i)) : std::uint32_t(i)) &
        std::uint32_t(entries - 1);
    const std::uint32_t packed = words[1 + (logical >> 1)],
                        code = (packed >> ((logical & 1u) * 16u)) & 0xffffu;
    if (actual[i] != mix32(code ^ std::uint32_t(i)))
      break;
    ++validated;
  }
  Row row{};
  row.source = source;
  row.pattern = pattern;
  row.entries = entries;
  row.table_bytes = table_bytes;
  row.candidates = candidates;
  row.validated = validated;
  row.l2_fraction = l2_bytes ? double(table_bytes) / double(l2_bytes) : 0;
  row.setup_ms = elapsed_ms(setup0, setup1);
  row.upload_ms = upload_ms;
  row.readback_ms = readback_ms;
  row.device_min_ms = *std::min_element(times.begin(), times.end());
  row.device_mean_ms =
      std::accumulate(times.begin(), times.end(), 0.0) / times.size();
  row.device_p50_ms = percentile(times, .5);
  row.device_p95_ms = percentile(times, .95);
  row.device_p99_ms = percentile(times, .99);
  row.device_max_ms = *std::max_element(times.begin(), times.end());
  row.lookup_mps = double(candidates) / row.device_p50_ms / 1000.0;
  row.logical_gbps = double(candidates * 8) / (row.device_p50_ms * 1e6);
  row.valid = validated == candidates;
  vkDestroyFence(ctx.device(), fence, nullptr);
  vkDestroyQueryPool(ctx.device(), qp, nullptr);
  vkFreeCommandBuffers(ctx.device(), ctx.command_pool(), 1, &cmd);
  vkDestroyDescriptorPool(ctx.device(), pool, nullptr);
  vkDestroyBufferView(ctx.device(), view, nullptr);
  return row;
}

std::vector<std::uint32_t> make_pointer_table(std::size_t entries,
                                               bool random_links) {
  std::vector<std::uint32_t> next(entries);
  std::uint64_t prime_product = 1, remainder = entries;
  for (std::uint64_t prime = 2; prime * prime <= remainder; ++prime) {
    if (remainder % prime)
      continue;
    prime_product *= prime;
    while (remainder % prime == 0)
      remainder /= prime;
  }
  if (remainder > 1)
    prime_product *= remainder;
  if ((entries % 4) == 0 && (prime_product % 4) != 0)
    prime_product *= 2;
  const std::uint64_t multiplier =
      1 + prime_product * std::max<std::uint64_t>(1, 1664524 / prime_product);
  std::uint64_t increment = 1013904223u % entries;
  if (!increment)
    increment = 1;
  while (std::gcd(increment, std::uint64_t(entries)) != 1)
    ++increment;
  for (std::size_t i = 0; i < entries; ++i) {
    const auto x = std::uint32_t(i);
    next[i] = random_links
                  ? std::uint32_t((multiplier * x + increment) % entries)
                  : std::uint32_t((i + 1) % entries);
  }
  return next;
}

struct LatencyRow {
  std::string mode, pattern;
  std::size_t entries = 0, table_bytes = 0, invocations = 0, validated = 0;
  std::uint32_t chase_steps = 0;
  double l2_fraction = 0, setup_ms = 0, upload_ms = 0, readback_ms = 0,
         device_min_ms = 0, device_mean_ms = 0, device_p50_ms = 0,
         device_p95_ms = 0, device_p99_ms = 0, device_max_ms = 0,
         clock_min_ticks = 0, clock_mean_ticks = 0, clock_p50_ticks = 0,
         clock_p95_ticks = 0, clock_p99_ticks = 0, clock_max_ticks = 0;
  bool valid = false;
};

LatencyRow run_latency_one(const VulkanContext &ctx, VkDescriptorSetLayout dsl,
                           VkPipelineLayout layout, VkPipeline pipeline,
                           const std::string &mode,
                           const std::string &pattern, bool random_links,
                           std::size_t entries, std::size_t invocations,
                           std::uint32_t chase_steps, std::size_t l2_bytes,
                           int warmup, int warmup_ms, int iterations) {
  const auto setup0 = Clock::now();
  auto next = make_pointer_table(entries, random_links);
  const std::size_t table_bytes = next.size() * sizeof(std::uint32_t),
                    output_words = invocations * 8,
                    output_bytes = output_words * sizeof(std::uint32_t);
  Buffer table_upload(ctx, table_bytes, VK_BUFFER_USAGE_TRANSFER_SRC_BIT,
                      VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT |
                          VK_MEMORY_PROPERTY_HOST_COHERENT_BIT,
                      true);
  Buffer output_readback(ctx, output_bytes, VK_BUFFER_USAGE_TRANSFER_DST_BIT,
                         VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT |
                             VK_MEMORY_PROPERTY_HOST_COHERENT_BIT,
                         true);
  Buffer table(ctx, table_bytes,
               VK_BUFFER_USAGE_STORAGE_BUFFER_BIT |
                   VK_BUFFER_USAGE_TRANSFER_DST_BIT,
               VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT, false);
  Buffer output(ctx, output_bytes,
                VK_BUFFER_USAGE_STORAGE_BUFFER_BIT |
                    VK_BUFFER_USAGE_TRANSFER_SRC_BIT,
                VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT, false);
  std::memcpy(table_upload.mapped, next.data(), table_bytes);
  const double upload_ms =
      submit_once(ctx, "vkQueueSubmit(latency upload)", [&](VkCommandBuffer cmd) {
        VkBufferCopy copy{0, 0, table_bytes};
        vkCmdCopyBuffer(cmd, table_upload.buffer, table.buffer, 1, &copy);
        VkBufferMemoryBarrier barrier{};
        barrier.sType = VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER;
        barrier.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
        barrier.dstAccessMask = VK_ACCESS_SHADER_READ_BIT;
        barrier.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
        barrier.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
        barrier.buffer = table.buffer;
        barrier.offset = 0;
        barrier.size = VK_WHOLE_SIZE;
        vkCmdPipelineBarrier(cmd, VK_PIPELINE_STAGE_TRANSFER_BIT,
                             VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, 0, 0,
                             nullptr, 1, &barrier, 0, nullptr);
      });
  VkDescriptorPoolSize pool_size{VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 2};
  VkDescriptorPoolCreateInfo dpci{};
  dpci.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO;
  dpci.maxSets = 1;
  dpci.poolSizeCount = 1;
  dpci.pPoolSizes = &pool_size;
  VkDescriptorPool pool = VK_NULL_HANDLE;
  check(vkCreateDescriptorPool(ctx.device(), &dpci, nullptr, &pool),
        "vkCreateDescriptorPool(latency)");
  VkDescriptorSetAllocateInfo dsai{};
  dsai.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO;
  dsai.descriptorPool = pool;
  dsai.descriptorSetCount = 1;
  dsai.pSetLayouts = &dsl;
  VkDescriptorSet set = VK_NULL_HANDLE;
  check(vkAllocateDescriptorSets(ctx.device(), &dsai, &set),
        "vkAllocateDescriptorSets(latency)");
  VkDescriptorBufferInfo output_info{output.buffer, 0, output.size};
  VkDescriptorBufferInfo table_info{table.buffer, 0, table.size};
  VkWriteDescriptorSet writes[2]{};
  writes[0].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
  writes[0].dstSet = set;
  writes[0].dstBinding = 1;
  writes[0].descriptorCount = 1;
  writes[0].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;
  writes[0].pBufferInfo = &output_info;
  writes[1].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
  writes[1].dstSet = set;
  writes[1].dstBinding = 2;
  writes[1].descriptorCount = 1;
  writes[1].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;
  writes[1].pBufferInfo = &table_info;
  vkUpdateDescriptorSets(ctx.device(), 2, writes, 0, nullptr);
  VkCommandBufferAllocateInfo cai{};
  cai.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
  cai.commandPool = ctx.command_pool();
  cai.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
  cai.commandBufferCount = 1;
  VkCommandBuffer cmd = VK_NULL_HANDLE;
  check(vkAllocateCommandBuffers(ctx.device(), &cai, &cmd),
        "vkAllocateCommandBuffers(latency)");
  VkQueryPoolCreateInfo qpci{};
  qpci.sType = VK_STRUCTURE_TYPE_QUERY_POOL_CREATE_INFO;
  qpci.queryType = VK_QUERY_TYPE_TIMESTAMP;
  qpci.queryCount = 2;
  VkQueryPool qp = VK_NULL_HANDLE;
  check(vkCreateQueryPool(ctx.device(), &qpci, nullptr, &qp),
        "vkCreateQueryPool(latency)");
  VkCommandBufferBeginInfo bi{};
  bi.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
  bi.flags = VK_COMMAND_BUFFER_USAGE_SIMULTANEOUS_USE_BIT;
  check(vkBeginCommandBuffer(cmd, &bi), "vkBeginCommandBuffer(latency)");
  vkCmdResetQueryPool(cmd, qp, 0, 2);
  vkCmdWriteTimestamp(cmd, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, qp, 0);
  vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_COMPUTE, pipeline);
  vkCmdBindDescriptorSets(cmd, VK_PIPELINE_BIND_POINT_COMPUTE, layout, 0, 1,
                          &set, 0, nullptr);
  vkCmdDispatch(cmd, std::uint32_t((invocations + 255) / 256), 1, 1);
  vkCmdWriteTimestamp(cmd, VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT, qp, 1);
  check(vkEndCommandBuffer(cmd), "vkEndCommandBuffer(latency)");
  VkFenceCreateInfo fci{};
  fci.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO;
  VkFence fence = VK_NULL_HANDLE;
  check(vkCreateFence(ctx.device(), &fci, nullptr, &fence),
        "vkCreateFence(latency)");
  VkSubmitInfo si{};
  si.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
  si.commandBufferCount = 1;
  si.pCommandBuffers = &cmd;
  const auto setup1 = Clock::now();
  auto submit = [&]() {
    check(vkResetFences(ctx.device(), 1, &fence), "vkResetFences(latency)");
    check(vkQueueSubmit(ctx.queue(), 1, &si, fence),
          "vkQueueSubmit(latency)");
    check(vkWaitForFences(ctx.device(), 1, &fence, VK_TRUE,
                          std::numeric_limits<std::uint64_t>::max()),
          "vkWaitForFences(latency)");
    std::uint64_t ticks[2]{};
    check(vkGetQueryPoolResults(ctx.device(), qp, 0, 2, sizeof(ticks), ticks,
                                sizeof(std::uint64_t),
                                VK_QUERY_RESULT_64_BIT |
                                    VK_QUERY_RESULT_WAIT_BIT),
          "vkGetQueryPoolResults(latency)");
    const std::uint64_t delta =
        ctx.timestamp_bits() >= 64
            ? ticks[1] - ticks[0]
            : (ticks[1] - ticks[0]) &
                  ((std::uint64_t(1) << ctx.timestamp_bits()) - 1);
    return double(delta) * ctx.timestamp_period() / 1e6;
  };
  int warmup_submissions = 0;
  const auto warmup_start = Clock::now();
  while (warmup_submissions < warmup ||
         elapsed_ms(warmup_start, Clock::now()) < warmup_ms) {
    submit();
    ++warmup_submissions;
  }
  std::vector<double> times;
  times.reserve(iterations);
  for (int i = 0; i < iterations; ++i)
    times.push_back(submit());
  const double readback_ms = submit_once(
      ctx, "vkQueueSubmit(latency readback)", [&](VkCommandBuffer transfer_cmd) {
        VkBufferMemoryBarrier a{};
        a.sType = VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER;
        a.srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT;
        a.dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT;
        a.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
        a.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
        a.buffer = output.buffer;
        a.offset = 0;
        a.size = VK_WHOLE_SIZE;
        vkCmdPipelineBarrier(transfer_cmd, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
                             VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 0, nullptr, 1,
                             &a, 0, nullptr);
        VkBufferCopy copy{0, 0, output_bytes};
        vkCmdCopyBuffer(transfer_cmd, output.buffer, output_readback.buffer, 1,
                        &copy);
        VkBufferMemoryBarrier b{};
        b.sType = VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER;
        b.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
        b.dstAccessMask = VK_ACCESS_HOST_READ_BIT;
        b.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
        b.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
        b.buffer = output_readback.buffer;
        b.offset = 0;
        b.size = VK_WHOLE_SIZE;
        vkCmdPipelineBarrier(transfer_cmd, VK_PIPELINE_STAGE_TRANSFER_BIT,
                             VK_PIPELINE_STAGE_HOST_BIT, 0, 0, nullptr, 1, &b,
                             0, nullptr);
      });
  const auto *actual =
      static_cast<const std::uint32_t *>(output_readback.mapped);
  std::vector<double> clock_ticks;
  clock_ticks.reserve(invocations);
  std::size_t validated = 0;
  for (std::size_t i = 0; i < invocations; ++i) {
    std::uint32_t expected =
        std::uint32_t(std::uint64_t(mix32(std::uint32_t(i))) % entries);
    for (std::uint32_t step = 0; step < chase_steps; ++step)
      expected = next[expected];
    const std::size_t base = i * 8;
    const bool payload_valid =
        actual[base + 4] == expected &&
        actual[base + 5] == mix32(expected ^ std::uint32_t(i)) &&
        actual[base + 6] == 0x55475453u && actual[base + 7] == chase_steps;
    if (payload_valid)
      ++validated;
    const std::uint64_t started = std::uint64_t(actual[base]) |
                                  (std::uint64_t(actual[base + 1]) << 32u);
    const std::uint64_t finished = std::uint64_t(actual[base + 2]) |
                                   (std::uint64_t(actual[base + 3]) << 32u);
    clock_ticks.push_back(double(finished - started));
  }
  LatencyRow row{};
  row.mode = mode;
  row.pattern = pattern;
  row.entries = entries;
  row.table_bytes = table_bytes;
  row.invocations = invocations;
  row.validated = validated;
  row.chase_steps = chase_steps;
  row.l2_fraction = l2_bytes ? double(table_bytes) / double(l2_bytes) : 0;
  row.setup_ms = elapsed_ms(setup0, setup1);
  row.upload_ms = upload_ms;
  row.readback_ms = readback_ms;
  row.device_min_ms = *std::min_element(times.begin(), times.end());
  row.device_mean_ms =
      std::accumulate(times.begin(), times.end(), 0.0) / times.size();
  row.device_p50_ms = percentile(times, .5);
  row.device_p95_ms = percentile(times, .95);
  row.device_p99_ms = percentile(times, .99);
  row.device_max_ms = *std::max_element(times.begin(), times.end());
  row.clock_min_ticks = *std::min_element(clock_ticks.begin(), clock_ticks.end());
  row.clock_mean_ticks =
      std::accumulate(clock_ticks.begin(), clock_ticks.end(), 0.0) /
      clock_ticks.size();
  row.clock_p50_ticks = percentile(clock_ticks, .5);
  row.clock_p95_ticks = percentile(clock_ticks, .95);
  row.clock_p99_ticks = percentile(clock_ticks, .99);
  row.clock_max_ticks = *std::max_element(clock_ticks.begin(), clock_ticks.end());
  row.valid = validated == invocations;
  vkDestroyFence(ctx.device(), fence, nullptr);
  vkDestroyQueryPool(ctx.device(), qp, nullptr);
  vkFreeCommandBuffers(ctx.device(), ctx.command_pool(), 1, &cmd);
  vkDestroyDescriptorPool(ctx.device(), pool, nullptr);
  return row;
}

double control_subtracted_ticks_per_load(const LatencyRow &row,
                                         const std::vector<LatencyRow> &rows) {
  if (!row.chase_steps)
    return 0.0;
  const auto control = std::find_if(rows.begin(), rows.end(), [&](const auto &x) {
    return x.pattern == row.pattern && x.entries == row.entries &&
           x.chase_steps == 0;
  });
  if (control == rows.end())
    return std::numeric_limits<double>::quiet_NaN();
  return (row.clock_p50_ticks - control->clock_p50_ticks) /
         double(row.chase_steps);
}

void write_latency_results(
    const Args &args, const VulkanContext &ctx,
    const std::vector<std::pair<std::string, Program>> &programs,
    const std::vector<LatencyRow> &rows) {
  fs::create_directories(args.out_dir);
  const auto &p = ctx.properties();
  std::ofstream j(args.out_dir / "l2_latency_results.json");
  j << std::fixed << std::setprecision(6)
    << "{\n  \"schema\": \"UGTS-VK-L2-LATENCY-1.0\",\n"
       "  \"runtime\": \"Vulkan compute / VK_KHR_shader_clock / dependent "
       "SSBO pointer chase\",\n  \"device\": {\"name\": \""
    << p.deviceName << "\", \"vendor_id\": " << p.vendorID
    << ", \"device_id\": " << p.deviceID << ", \"api_version\": \""
    << api_major(p.apiVersion) << '.' << api_minor(p.apiVersion) << '.'
    << api_patch(p.apiVersion)
    << "\", \"l2_bytes_external_query\": " << args.l2_bytes
    << ", \"shader_device_clock\": true},\n"
       "  \"run_parameters\": {\"warmup\": "
    << args.warmup << ", \"warmup_ms\": " << args.warmup_ms
    << ", \"iterations\": " << args.iterations
    << ", \"invocations\": " << args.latency_invocations
    << ", \"reverse\": " << (args.reverse ? "true" : "false")
    << "},\n"
       "  \"clock_semantics\": \"Device-scope realtime clock units are "
       "implementation-defined. Control-subtracted ticks per load include "
       "scheduler exposure and are not labelled GPU cycles or nanoseconds.\",\n"
       "  \"programs\": [\n";
  for (std::size_t i = 0; i < programs.size(); ++i) {
    const auto &x = programs[i];
    j << "    {\"name\": \"" << x.first << "\", \"spirv_bytes\": "
      << x.second.spv_bytes << ", \"pipeline_cache_bytes\": "
      << x.second.cache_bytes << ", \"cold_pipeline_ms\": " << x.second.cold_ms
      << ", \"cached_pipeline_ms\": " << x.second.cached_ms << "}"
      << (i + 1 == programs.size() ? "\n" : ",\n");
  }
  j << "  ],\n  \"results\": [\n";
  for (std::size_t i = 0; i < rows.size(); ++i) {
    const auto &r = rows[i];
    const double net = control_subtracted_ticks_per_load(r, rows);
    j << "    {\"mode\": \"" << r.mode << "\", \"pattern\": \""
      << r.pattern << "\", \"logical_entries\": " << r.entries
      << ", \"table_bytes\": " << r.table_bytes
      << ", \"l2_fraction\": " << r.l2_fraction
      << ", \"invocations\": " << r.invocations
      << ", \"chase_steps\": " << r.chase_steps
      << ", \"setup_ms\": " << r.setup_ms << ", \"upload_ms\": "
      << r.upload_ms << ", \"readback_ms\": " << r.readback_ms
      << ", \"device_ms\": {\"min\": " << r.device_min_ms
      << ", \"mean\": " << r.device_mean_ms << ", \"p50\": "
      << r.device_p50_ms << ", \"p95\": " << r.device_p95_ms
      << ", \"p99\": " << r.device_p99_ms << ", \"max\": "
      << r.device_max_ms << "}, \"clock_ticks\": {\"min\": "
      << r.clock_min_ticks << ", \"mean\": " << r.clock_mean_ticks
      << ", \"p50\": " << r.clock_p50_ticks << ", \"p95\": "
      << r.clock_p95_ticks << ", \"p99\": " << r.clock_p99_ticks
      << ", \"max\": " << r.clock_max_ticks
      << "}, \"control_subtracted_p50_ticks_per_load\": " << net
      << ", \"validated_outputs\": " << r.validated
      << ", \"validation\": " << (r.valid ? "true" : "false") << "}"
      << (i + 1 == rows.size() ? "\n" : ",\n");
  }
  j << "  ]\n}\n";
  std::ofstream c(args.out_dir / "l2_latency_results.csv");
  c << "mode,pattern,logical_entries,table_bytes,l2_fraction,invocations,"
       "chase_steps,setup_ms,upload_ms,readback_ms,device_p50_ms,device_p95_ms,"
       "device_p99_ms,clock_min_ticks,clock_mean_ticks,clock_p50_ticks,"
       "clock_p95_ticks,clock_p99_ticks,clock_max_ticks,"
       "control_subtracted_p50_ticks_per_load,validated_outputs,validation\n"
    << std::fixed << std::setprecision(6);
  for (const auto &r : rows)
    c << r.mode << ',' << r.pattern << ',' << r.entries << ',' << r.table_bytes
      << ',' << r.l2_fraction << ',' << r.invocations << ',' << r.chase_steps
      << ',' << r.setup_ms << ',' << r.upload_ms << ',' << r.readback_ms << ','
      << r.device_p50_ms << ',' << r.device_p95_ms << ',' << r.device_p99_ms
      << ',' << r.clock_min_ticks << ',' << r.clock_mean_ticks << ','
      << r.clock_p50_ticks << ',' << r.clock_p95_ticks << ','
      << r.clock_p99_ticks << ',' << r.clock_max_ticks << ','
      << control_subtracted_ticks_per_load(r, rows) << ',' << r.validated << ','
      << (r.valid ? 1 : 0) << '\n';
}

void write_results(const Args &args, const VulkanContext &ctx,
                   const std::vector<std::pair<std::string, Program>> &programs,
                   const std::vector<Row> &rows) {
  fs::create_directories(args.out_dir);
  const auto &p = ctx.properties();
  std::ofstream j(args.out_dir / "lut_cache_results.json");
  j << std::fixed << std::setprecision(6)
    << "{\n  \"schema\": \"UGTS-VK-LUT-CACHE-1.1\",\n  \"runtime\": \"Vulkan "
       "compute / paired uniform texel and storage buffers\",\n  \"device\": {\"name\": \""
    << p.deviceName << "\", \"vendor_id\": " << p.vendorID
    << ", \"device_id\": " << p.deviceID << ", \"api_version\": \""
    << api_major(p.apiVersion) << '.' << api_minor(p.apiVersion) << '.'
    << api_patch(p.apiVersion)
    << "\", \"l2_bytes_external_query\": " << args.l2_bytes
    << "},\n  \"run_parameters\": {\"warmup\": " << args.warmup
    << ", \"warmup_ms\": " << args.warmup_ms
     << ", \"iterations\": " << args.iterations
     << ", \"minimum_candidates\": " << args.min_candidates
     << ", \"reverse\": " << (args.reverse ? "true" : "false")
     << "},\n  \"interpretation\": \"Empirical texture-fetch working-set sweep; "
       "direct hardware cache counters were unavailable.\",\n  \"programs\": "
       "[\n";
  for (std::size_t i = 0; i < programs.size(); ++i) {
    const auto &x = programs[i];
    const bool texture = x.first.rfind("texture_", 0) == 0;
    const bool random = x.first.find("random") != std::string::npos;
    j << "    {\"name\": \"" << x.first << "\", \"source\": \""
      << (texture ? "uniform_texel_buffer" : "storage_buffer")
      << "\", \"pattern\": \"" << (random ? "random" : "sequential")
      << "\", \"spirv_bytes\": " << x.second.spv_bytes
      << ", \"pipeline_cache_bytes\": " << x.second.cache_bytes
      << ", \"cold_pipeline_ms\": " << x.second.cold_ms
      << ", \"cached_pipeline_ms\": " << x.second.cached_ms << "}"
      << (i + 1 == programs.size() ? "\n" : ",\n");
  }
  j << "  ],\n  \"results\": [\n";
  for (std::size_t i = 0; i < rows.size(); ++i) {
    const auto &r = rows[i];
    j << "    {\"source\": \"" << r.source << "\", \"pattern\": \"" << r.pattern
      << "\", \"logical_entries\": " << r.entries
      << ", \"table_bytes\": " << r.table_bytes
      << ", \"l2_fraction\": " << r.l2_fraction
      << ", \"candidates\": " << r.candidates
      << ", \"setup_ms\": " << r.setup_ms << ", \"upload_ms\": " << r.upload_ms
      << ", \"readback_ms\": " << r.readback_ms
      << ", \"device_ms\": {\"min\": " << r.device_min_ms
      << ", \"mean\": " << r.device_mean_ms << ", \"p50\": " << r.device_p50_ms
      << ", \"p95\": " << r.device_p95_ms << ", \"p99\": " << r.device_p99_ms
      << ", \"max\": " << r.device_max_ms
      << "}, \"lookup_mps\": " << r.lookup_mps
      << ", \"logical_gbps\": " << r.logical_gbps
      << ", \"validated_outputs\": " << r.validated
      << ", \"validation\": " << (r.valid ? "true" : "false") << "}"
      << (i + 1 == rows.size() ? "\n" : ",\n");
  }
  j << "  ]\n}\n";
  std::ofstream c(args.out_dir / "lut_cache_results.csv");
  c << "source,pattern,logical_entries,table_bytes,l2_fraction,candidates,setup_ms,"
       "upload_ms,readback_ms,device_p50_ms,device_p95_ms,device_p99_ms,lookup_"
       "mps,logical_gbps,validated_outputs,validation\n"
    << std::fixed << std::setprecision(6);
  for (const auto &r : rows)
    c << r.source << ',' << r.pattern << ',' << r.entries << ',' << r.table_bytes << ','
      << r.l2_fraction << ',' << r.candidates << ',' << r.setup_ms << ','
      << r.upload_ms << ',' << r.readback_ms << ',' << r.device_p50_ms << ','
      << r.device_p95_ms << ',' << r.device_p99_ms << ',' << r.lookup_mps << ','
      << r.logical_gbps << ',' << r.validated << ',' << (r.valid ? 1 : 0)
      << '\n';
}

} // namespace

int main(int argc, char **argv) {
  try {
    const Args args = parse_args(argc, argv);
    fs::create_directories(args.out_dir);
    VulkanContext ctx;
    const auto &p = ctx.properties();
    std::cout << "Vulkan LUT probe device: " << p.deviceName
              << " | reported L2 " << args.l2_bytes << " bytes\n";
    VkDescriptorSetLayoutBinding bindings[3]{};
    bindings[0].binding = 0;
    bindings[0].descriptorType = VK_DESCRIPTOR_TYPE_UNIFORM_TEXEL_BUFFER;
    bindings[0].descriptorCount = 1;
    bindings[0].stageFlags = VK_SHADER_STAGE_COMPUTE_BIT;
    bindings[1].binding = 1;
    bindings[1].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;
    bindings[1].descriptorCount = 1;
    bindings[1].stageFlags = VK_SHADER_STAGE_COMPUTE_BIT;
    bindings[2].binding = 2;
    bindings[2].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;
    bindings[2].descriptorCount = 1;
    bindings[2].stageFlags = VK_SHADER_STAGE_COMPUTE_BIT;
    VkDescriptorSetLayoutCreateInfo dci{};
    dci.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO;
    dci.bindingCount = 3;
    dci.pBindings = bindings;
    VkDescriptorSetLayout dsl = VK_NULL_HANDLE;
    check(vkCreateDescriptorSetLayout(ctx.device(), &dci, nullptr, &dsl),
          "vkCreateDescriptorSetLayout");
    VkPipelineLayoutCreateInfo plci{};
    plci.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO;
    plci.setLayoutCount = 1;
    plci.pSetLayouts = &dsl;
    VkPipelineLayout layout = VK_NULL_HANDLE;
    check(vkCreatePipelineLayout(ctx.device(), &plci, nullptr, &layout),
          "vkCreatePipelineLayout");
    if (args.latency_only) {
      if (!ctx.shader_device_clock())
        throw std::runtime_error(
            "selected device does not expose shaderDeviceClock through "
            "VK_KHR_shader_clock");
      std::vector<std::pair<std::string, Program>> latency_programs;
      latency_programs.emplace_back(
          "control",
          make_program(ctx, layout,
                       args.spirv_dir / "ugts_l2_latency_control.spv"));
      latency_programs.emplace_back(
          "chase512",
          make_program(ctx, layout,
                       args.spirv_dir / "ugts_l2_latency_chase512.spv"));
      if (args.reverse)
        std::reverse(latency_programs.begin(), latency_programs.end());
      std::vector<LatencyRow> latency_rows;
      for (auto entries : args.entries) {
        std::vector<bool> patterns = {false, true};
        if (args.reverse)
          std::reverse(patterns.begin(), patterns.end());
        for (bool random_links : patterns) {
          const std::string pattern =
              random_links ? "random_full_period" : "sequential_ring";
          for (auto &program : latency_programs) {
            const std::uint32_t steps =
                program.first == "chase512" ? 512u : 0u;
            auto r = run_latency_one(
                ctx, dsl, layout, program.second.pipeline, program.first,
                pattern, random_links, entries, args.latency_invocations,
                steps, args.l2_bytes, args.warmup, args.warmup_ms,
                args.iterations);
            std::cout << std::setw(9) << program.first << ' ' << std::setw(18)
                      << pattern << " table=" << std::setw(8) << std::fixed
                      << std::setprecision(3)
                      << (r.table_bytes / (1024.0 * 1024.0))
                      << " MiB clock_p50=" << std::setprecision(1)
                      << r.clock_p50_ticks << " ticks valid="
                      << (r.valid ? "yes" : "no") << '\n';
            latency_rows.push_back(r);
          }
        }
      }
      write_latency_results(args, ctx, latency_programs, latency_rows);
      const bool valid =
          std::all_of(latency_rows.begin(), latency_rows.end(),
                      [](const LatencyRow &r) { return r.valid; });
      for (auto &x : latency_programs)
        destroy_program(ctx, x.second);
      vkDestroyPipelineLayout(ctx.device(), layout, nullptr);
      vkDestroyDescriptorSetLayout(ctx.device(), dsl, nullptr);
      return valid ? 0 : 2;
    }
    std::vector<std::pair<std::string, Program>> programs;
    programs.emplace_back(
        "texture_sequential",
        make_program(ctx, layout,
                     args.spirv_dir / "ugts_log_lut_sequential.spv"));
    programs.emplace_back(
        "ssbo_sequential",
        make_program(ctx, layout,
                     args.spirv_dir / "ugts_log_ssbo_sequential.spv"));
    programs.emplace_back(
        "texture_random",
        make_program(ctx, layout, args.spirv_dir / "ugts_log_lut_random.spv"));
    programs.emplace_back(
        "ssbo_random",
        make_program(ctx, layout, args.spirv_dir / "ugts_log_ssbo_random.spv"));
    if (args.reverse)
      std::reverse(programs.begin(), programs.end());
    std::vector<Row> rows;
    for (auto &program : programs) {
      for (auto entries : args.entries) {
        const bool texture = program.first.rfind("texture_", 0) == 0;
        const bool random = program.first.find("random") != std::string::npos;
        const std::string source =
            texture ? "uniform_texel_buffer" : "storage_buffer";
        const std::string pattern = random ? "random" : "sequential";
        auto r = run_one(ctx, dsl, layout, program.second.pipeline,
                         source, pattern, random, entries, args.min_candidates,
                         args.l2_bytes, args.warmup, args.warmup_ms,
                         args.iterations);
        std::cout << std::setw(18) << program.first << " table=" << std::setw(9)
                  << (r.table_bytes / (1024.0 * 1024.0))
                  << " MiB p50=" << std::setw(8) << std::fixed
                  << std::setprecision(3) << r.device_p50_ms
                  << " ms lookup=" << std::setprecision(1) << r.lookup_mps
                  << " M/s valid=" << (r.valid ? "yes" : "no") << '\n';
        rows.push_back(r);
      }
    }
    write_results(args, ctx, programs, rows);
    bool valid = std::all_of(rows.begin(), rows.end(),
                             [](const Row &r) { return r.valid; });
    for (auto &x : programs)
      destroy_program(ctx, x.second);
    vkDestroyPipelineLayout(ctx.device(), layout, nullptr);
    vkDestroyDescriptorSetLayout(ctx.device(), dsl, nullptr);
    return valid ? 0 : 2;
  } catch (const std::exception &e) {
    std::cerr << "UGTS LUT benchmark error: " << e.what() << '\n';
    return 1;
  }
}
