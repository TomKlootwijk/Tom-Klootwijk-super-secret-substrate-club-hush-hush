#include "ugts_vulkan_min.h"

#include <algorithm>
#include <array>
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
#include <unordered_map>
#include <vector>

namespace fs = std::filesystem;
using Clock = std::chrono::steady_clock;

namespace {

void check(VkResult result, const char* what) {
    if (result != VK_SUCCESS) {
        throw std::runtime_error(std::string(what) + " failed with VkResult " + std::to_string(int(result)));
    }
}

double elapsed_ms(Clock::time_point a, Clock::time_point b) {
    return std::chrono::duration<double, std::milli>(b - a).count();
}

double percentile(std::vector<double> values, double q) {
    if (values.empty()) return 0.0;
    std::sort(values.begin(), values.end());
    const double x = q * double(values.size() - 1);
    const std::size_t lo = std::size_t(std::floor(x));
    const std::size_t hi = std::size_t(std::ceil(x));
    const double t = x - double(lo);
    return values[lo] * (1.0 - t) + values[hi] * t;
}

std::string json_escape(const std::string& s) {
    std::ostringstream out;
    for (unsigned char c : s) {
        switch (c) {
            case '\\': out << "\\\\"; break;
            case '"': out << "\\\""; break;
            case '\n': out << "\\n"; break;
            case '\r': out << "\\r"; break;
            case '\t': out << "\\t"; break;
            default:
                if (c < 0x20) out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << int(c) << std::dec;
                else out << c;
        }
    }
    return out.str();
}

std::vector<std::uint32_t> read_spirv(const fs::path& path) {
    std::ifstream f(path, std::ios::binary | std::ios::ate);
    if (!f) throw std::runtime_error("cannot read SPIR-V: " + path.string());
    const auto size = f.tellg();
    if (size <= 0 || (std::uint64_t(size) % 4) != 0) throw std::runtime_error("invalid SPIR-V size");
    std::vector<std::uint32_t> words(std::size_t(size) / 4);
    f.seekg(0);
    f.read(reinterpret_cast<char*>(words.data()), size);
    if (!f || words.empty() || words[0] != 0x07230203u) throw std::runtime_error("invalid SPIR-V magic");
    return words;
}

void write_bytes(const fs::path& path, const std::vector<std::uint8_t>& data) {
    fs::create_directories(path.parent_path());
    std::ofstream f(path, std::ios::binary);
    if (!f) throw std::runtime_error("cannot write " + path.string());
    f.write(reinterpret_cast<const char*>(data.data()), std::streamsize(data.size()));
}

std::string cache_filename(const std::string& program_name) {
    // Keep benchmark output paths below legacy Win32 MAX_PATH even when the
    // descriptive profile name is long. FNV-1a is deterministic and the full
    // program name remains in the JSON metadata.
    std::uint64_t hash = 14695981039346656037ull;
    for (unsigned char c : program_name) {
        hash ^= c;
        hash *= 1099511628211ull;
    }
    std::ostringstream out;
    out << "p_" << std::hex << std::setw(16) << std::setfill('0') << hash << ".vkcache";
    return out.str();
}

struct Args {
    fs::path spirv_dir = "spirv";
    fs::path out_dir = "vulkan_benchmark_out";
    std::vector<std::size_t> sizes = {1024, 16384, 262144, 1048576};
    int warmup = 3;
    int warmup_ms = 0;
    int iterations = 12;
    bool compact_only = false;
    bool compact_reverse = false;
    double compact_capacity_ratio = 1.0;
    bool allow_compact_overflow = false;
    bool prethreshold_only = false;
    bool hot_log_lut_only = false;
    bool cold_lineage_only = false;
    bool lut_only = false;
    bool lut_reverse = false;
};

std::vector<std::size_t> parse_sizes(const std::string& text) {
    std::stringstream ss(text);
    std::string part;
    std::vector<std::size_t> out;
    while (std::getline(ss, part, ',')) if (!part.empty()) out.push_back(std::stoull(part));
    if (out.empty()) throw std::runtime_error("empty --sizes");
    return out;
}

Args parse_args(int argc, char** argv) {
    Args a;
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        auto value = [&](const char* name) {
            if (i + 1 >= argc) throw std::runtime_error(std::string("missing value for ") + name);
            return std::string(argv[++i]);
        };
        if (arg == "--spirv-dir") a.spirv_dir = value("--spirv-dir");
        else if (arg == "--out-dir") a.out_dir = value("--out-dir");
        else if (arg == "--sizes") a.sizes = parse_sizes(value("--sizes"));
        else if (arg == "--warmup") a.warmup = std::stoi(value("--warmup"));
        else if (arg == "--warmup-ms") a.warmup_ms = std::stoi(value("--warmup-ms"));
        else if (arg == "--iterations") a.iterations = std::stoi(value("--iterations"));
        else if (arg == "--compact-only") a.compact_only = true;
        else if (arg == "--compact-reverse") a.compact_reverse = true;
        else if (arg == "--compact-capacity-ratio") a.compact_capacity_ratio = std::stod(value("--compact-capacity-ratio"));
        else if (arg == "--allow-compact-overflow") a.allow_compact_overflow = true;
        else if (arg == "--prethreshold-only") a.prethreshold_only = true;
        else if (arg == "--hot-log-lut-only") a.hot_log_lut_only = true;
        else if (arg == "--cold-lineage-only") a.cold_lineage_only = true;
        else if (arg == "--lut-only") a.lut_only = true;
        else if (arg == "--lut-reverse") a.lut_reverse = true;
        else if (arg == "--help" || arg == "-h") {
            std::cout << "UGTS native Vulkan benchmark\n"
                      << "  --spirv-dir PATH\n  --out-dir PATH\n  --sizes N,N,...\n"
                      << "  --warmup N\n  --warmup-ms N\n  --iterations N\n  --compact-only\n  --compact-reverse\n"
                      << "  --compact-capacity-ratio R\n  --allow-compact-overflow\n  --prethreshold-only\n  --hot-log-lut-only\n  --cold-lineage-only\n  --lut-only\n  --lut-reverse\n";
            std::exit(0);
        } else throw std::runtime_error("unknown argument: " + arg);
    }
    if (a.warmup < 0 || a.warmup_ms < 0 || a.iterations < 1) throw std::runtime_error("invalid iteration count");
    if (!std::isfinite(a.compact_capacity_ratio) || a.compact_capacity_ratio <= 0.0 || a.compact_capacity_ratio > 1.0) throw std::runtime_error("--compact-capacity-ratio must be in (0, 1]");
    return a;
}

std::uint32_t api_major(std::uint32_t v) { return (v >> 22u) & 0x7fu; }
std::uint32_t api_minor(std::uint32_t v) { return (v >> 12u) & 0x3ffu; }
std::uint32_t api_patch(std::uint32_t v) { return v & 0xfffu; }

class VulkanContext {
public:
    VulkanContext() {
        VkApplicationInfo app{};
        app.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO;
        app.pApplicationName = "UGTS Native Substrate Benchmark";
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
            check(vkCreateInstance(&ici, nullptr, &instance_), "vkCreateInstance(1.0)");
        } else check(ir, "vkCreateInstance");

        std::uint32_t count = 0;
        check(vkEnumeratePhysicalDevices(instance_, &count, nullptr), "vkEnumeratePhysicalDevices(count)");
        if (!count) throw std::runtime_error("no Vulkan physical devices");
        std::vector<VkPhysicalDevice> devices(count);
        check(vkEnumeratePhysicalDevices(instance_, &count, devices.data()), "vkEnumeratePhysicalDevices(list)");

        // Prefer a discrete/integrated/virtual GPU; fall back to CPU (SwiftShader in this validation container).
        physical_ = devices.front();
        int best_rank = -1;
        for (auto d : devices) {
            VkPhysicalDeviceProperties p{};
            vkGetPhysicalDeviceProperties(d, &p);
            int rank = 0;
            if (p.deviceType == VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU) rank = 4;
            else if (p.deviceType == VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU) rank = 3;
            else if (p.deviceType == VK_PHYSICAL_DEVICE_TYPE_VIRTUAL_GPU) rank = 2;
            else if (p.deviceType == VK_PHYSICAL_DEVICE_TYPE_CPU) rank = 1;
            if (rank > best_rank) { best_rank = rank; physical_ = d; props_ = p; }
        }

        std::uint32_t qcount = 0;
        vkGetPhysicalDeviceQueueFamilyProperties(physical_, &qcount, nullptr);
        std::vector<VkQueueFamilyProperties> qprops(qcount);
        vkGetPhysicalDeviceQueueFamilyProperties(physical_, &qcount, qprops.data());
        bool found = false;
        for (std::uint32_t i = 0; i < qcount; ++i) {
            if (qprops[i].queueCount && (qprops[i].queueFlags & VK_QUEUE_COMPUTE_BIT)) {
                queue_family_ = i;
                timestamp_bits_ = qprops[i].timestampValidBits;
                found = true;
                break;
            }
        }
        if (!found) throw std::runtime_error("no compute queue family");

        std::uint32_t extension_count = 0;
        check(vkEnumerateDeviceExtensionProperties(physical_, nullptr, &extension_count, nullptr), "vkEnumerateDeviceExtensionProperties(count)");
        std::vector<VkExtensionProperties> extensions(extension_count);
        if (extension_count) check(vkEnumerateDeviceExtensionProperties(physical_, nullptr, &extension_count, extensions.data()), "vkEnumerateDeviceExtensionProperties(list)");
        const char* executable_extension = "VK_KHR_pipeline_executable_properties";
        const bool executable_extension_present = std::any_of(extensions.begin(), extensions.end(), [&](const VkExtensionProperties& extension) {
            return std::strcmp(extension.extensionName, executable_extension) == 0;
        });
        performance_query_extension_present_ = std::any_of(extensions.begin(), extensions.end(), [](const VkExtensionProperties& extension) {
            return std::strcmp(extension.extensionName, "VK_KHR_performance_query") == 0;
        });
        VkPhysicalDevicePipelineExecutablePropertiesFeaturesKHR queried_executable_features{};
        queried_executable_features.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PIPELINE_EXECUTABLE_PROPERTIES_FEATURES_KHR;
        VkPhysicalDeviceFeatures2 queried_features{};
        queried_features.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2;
        queried_features.pNext = &queried_executable_features;
        if (executable_extension_present) vkGetPhysicalDeviceFeatures2(physical_, &queried_features);
        pipeline_executable_supported_ = executable_extension_present && queried_executable_features.pipelineExecutableInfo == VK_TRUE;

        const float priority = 1.0f;
        VkDeviceQueueCreateInfo qci{};
        qci.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO;
        qci.queueFamilyIndex = queue_family_;
        qci.queueCount = 1;
        qci.pQueuePriorities = &priority;
        VkDeviceCreateInfo dci{};
        dci.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO;
        dci.queueCreateInfoCount = 1;
        dci.pQueueCreateInfos = &qci;
        VkPhysicalDevicePipelineExecutablePropertiesFeaturesKHR enabled_executable_features{};
        if (pipeline_executable_supported_) {
            enabled_executable_features.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PIPELINE_EXECUTABLE_PROPERTIES_FEATURES_KHR;
            enabled_executable_features.pipelineExecutableInfo = VK_TRUE;
            dci.pNext = &enabled_executable_features;
            dci.enabledExtensionCount = 1;
            dci.ppEnabledExtensionNames = &executable_extension;
        }
        check(vkCreateDevice(physical_, &dci, nullptr, &device_), "vkCreateDevice");
        if (pipeline_executable_supported_) {
            get_pipeline_executable_properties_ = reinterpret_cast<PFN_vkGetPipelineExecutablePropertiesKHR>(vkGetDeviceProcAddr(device_, "vkGetPipelineExecutablePropertiesKHR"));
            get_pipeline_executable_statistics_ = reinterpret_cast<PFN_vkGetPipelineExecutableStatisticsKHR>(vkGetDeviceProcAddr(device_, "vkGetPipelineExecutableStatisticsKHR"));
            get_pipeline_executable_internal_representations_ = reinterpret_cast<PFN_vkGetPipelineExecutableInternalRepresentationsKHR>(vkGetDeviceProcAddr(device_, "vkGetPipelineExecutableInternalRepresentationsKHR"));
            pipeline_executable_supported_ = get_pipeline_executable_properties_ && get_pipeline_executable_statistics_ && get_pipeline_executable_internal_representations_;
        }
        vkGetDeviceQueue(device_, queue_family_, 0, &queue_);
        vkGetPhysicalDeviceMemoryProperties(physical_, &mem_props_);

        VkCommandPoolCreateInfo cpci{};
        cpci.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO;
        cpci.flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;
        cpci.queueFamilyIndex = queue_family_;
        check(vkCreateCommandPool(device_, &cpci, nullptr, &command_pool_), "vkCreateCommandPool");
    }

    ~VulkanContext() {
        if (device_) {
            vkDeviceWaitIdle(device_);
            if (command_pool_) vkDestroyCommandPool(device_, command_pool_, nullptr);
            vkDestroyDevice(device_, nullptr);
        }
        if (instance_) vkDestroyInstance(instance_, nullptr);
    }

    std::uint32_t find_memory_type(std::uint32_t bits, VkMemoryPropertyFlags required) const {
        for (std::uint32_t i = 0; i < mem_props_.memoryTypeCount; ++i) {
            if ((bits & (1u << i)) && (mem_props_.memoryTypes[i].propertyFlags & required) == required) return i;
        }
        throw std::runtime_error("no compatible host-visible coherent memory type");
    }

    VkDevice device() const { return device_; }
    VkPhysicalDevice physical() const { return physical_; }
    VkQueue queue() const { return queue_; }
    VkCommandPool command_pool() const { return command_pool_; }
    const VkPhysicalDeviceProperties& properties() const { return props_; }
    std::uint32_t queue_family() const { return queue_family_; }
    std::uint32_t timestamp_bits() const { return timestamp_bits_; }
    float timestamp_period_ns() const { return props_.limits.timestampPeriod; }
    bool pipeline_executable_supported() const { return pipeline_executable_supported_; }
    bool performance_query_extension_present() const { return performance_query_extension_present_; }
    PFN_vkGetPipelineExecutablePropertiesKHR get_pipeline_executable_properties() const { return get_pipeline_executable_properties_; }
    PFN_vkGetPipelineExecutableStatisticsKHR get_pipeline_executable_statistics() const { return get_pipeline_executable_statistics_; }
    PFN_vkGetPipelineExecutableInternalRepresentationsKHR get_pipeline_executable_internal_representations() const { return get_pipeline_executable_internal_representations_; }

private:
    VkInstance instance_ = VK_NULL_HANDLE;
    VkPhysicalDevice physical_ = VK_NULL_HANDLE;
    VkDevice device_ = VK_NULL_HANDLE;
    VkQueue queue_ = VK_NULL_HANDLE;
    VkCommandPool command_pool_ = VK_NULL_HANDLE;
    VkPhysicalDeviceProperties props_{};
    VkPhysicalDeviceMemoryProperties mem_props_{};
    std::uint32_t queue_family_ = 0;
    std::uint32_t timestamp_bits_ = 0;
    bool pipeline_executable_supported_ = false;
    bool performance_query_extension_present_ = false;
    PFN_vkGetPipelineExecutablePropertiesKHR get_pipeline_executable_properties_ = nullptr;
    PFN_vkGetPipelineExecutableStatisticsKHR get_pipeline_executable_statistics_ = nullptr;
    PFN_vkGetPipelineExecutableInternalRepresentationsKHR get_pipeline_executable_internal_representations_ = nullptr;
};

struct MappedBuffer {
    const VulkanContext* ctx = nullptr;
    VkBuffer buffer = VK_NULL_HANDLE;
    VkDeviceMemory memory = VK_NULL_HANDLE;
    VkDeviceSize size = 0;
    void* mapped = nullptr;

    MappedBuffer() = default;
    MappedBuffer(const VulkanContext& c, VkDeviceSize bytes,
                 VkBufferUsageFlags usage = VK_BUFFER_USAGE_TRANSFER_SRC_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT)
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
        mai.memoryTypeIndex = c.find_memory_type(req.memoryTypeBits,
            VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
        check(vkAllocateMemory(c.device(), &mai, nullptr, &memory), "vkAllocateMemory");
        check(vkBindBufferMemory(c.device(), buffer, memory, 0), "vkBindBufferMemory");
        check(vkMapMemory(c.device(), memory, 0, bytes, 0, &mapped), "vkMapMemory");
    }

    MappedBuffer(const MappedBuffer&) = delete;
    MappedBuffer& operator=(const MappedBuffer&) = delete;
    MappedBuffer(MappedBuffer&& other) noexcept { *this = std::move(other); }
    MappedBuffer& operator=(MappedBuffer&& other) noexcept {
        if (this != &other) {
            release();
            ctx = other.ctx; buffer = other.buffer; memory = other.memory; size = other.size; mapped = other.mapped;
            other.ctx = nullptr; other.buffer = VK_NULL_HANDLE; other.memory = VK_NULL_HANDLE; other.mapped = nullptr; other.size = 0;
        }
        return *this;
    }
    ~MappedBuffer() { release(); }

    void release() {
        if (!ctx) return;
        if (mapped) vkUnmapMemory(ctx->device(), memory);
        if (buffer) vkDestroyBuffer(ctx->device(), buffer, nullptr);
        if (memory) vkFreeMemory(ctx->device(), memory, nullptr);
        ctx = nullptr; buffer = VK_NULL_HANDLE; memory = VK_NULL_HANDLE; mapped = nullptr; size = 0;
    }
};

struct DeviceBuffer {
    const VulkanContext* ctx = nullptr;
    VkBuffer buffer = VK_NULL_HANDLE;
    VkDeviceMemory memory = VK_NULL_HANDLE;
    VkDeviceSize size = 0;

    DeviceBuffer() = default;
    DeviceBuffer(const VulkanContext& c, VkDeviceSize bytes, VkBufferUsageFlags usage)
        : ctx(&c), size(bytes) {
        VkBufferCreateInfo bci{};
        bci.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
        bci.size = bytes;
        bci.usage = usage;
        bci.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
        check(vkCreateBuffer(c.device(), &bci, nullptr, &buffer), "vkCreateBuffer(device-local)");
        VkMemoryRequirements req{};
        vkGetBufferMemoryRequirements(c.device(), buffer, &req);
        VkMemoryAllocateInfo mai{};
        mai.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
        mai.allocationSize = req.size;
        mai.memoryTypeIndex = c.find_memory_type(req.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
        check(vkAllocateMemory(c.device(), &mai, nullptr, &memory), "vkAllocateMemory(device-local)");
        check(vkBindBufferMemory(c.device(), buffer, memory, 0), "vkBindBufferMemory(device-local)");
    }

    DeviceBuffer(const DeviceBuffer&) = delete;
    DeviceBuffer& operator=(const DeviceBuffer&) = delete;
    ~DeviceBuffer() {
        if (!ctx) return;
        if (buffer) vkDestroyBuffer(ctx->device(), buffer, nullptr);
        if (memory) vkFreeMemory(ctx->device(), memory, nullptr);
    }
};

template<class Record>
double submit_once(const VulkanContext& ctx, const char* label, Record record) {
    VkCommandBufferAllocateInfo cai{};
    cai.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
    cai.commandPool = ctx.command_pool();
    cai.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
    cai.commandBufferCount = 1;
    VkCommandBuffer cmd = VK_NULL_HANDLE;
    check(vkAllocateCommandBuffers(ctx.device(), &cai, &cmd), "vkAllocateCommandBuffers(transfer)");
    VkCommandBufferBeginInfo bi{};
    bi.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
    bi.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
    check(vkBeginCommandBuffer(cmd, &bi), "vkBeginCommandBuffer(transfer)");
    record(cmd);
    check(vkEndCommandBuffer(cmd), "vkEndCommandBuffer(transfer)");
    VkFenceCreateInfo fci{};
    fci.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO;
    VkFence fence = VK_NULL_HANDLE;
    check(vkCreateFence(ctx.device(), &fci, nullptr, &fence), "vkCreateFence(transfer)");
    VkSubmitInfo si{};
    si.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
    si.commandBufferCount = 1;
    si.pCommandBuffers = &cmd;
    const auto start = Clock::now();
    check(vkQueueSubmit(ctx.queue(), 1, &si, fence), label);
    check(vkWaitForFences(ctx.device(), 1, &fence, VK_TRUE, std::numeric_limits<std::uint64_t>::max()),
          "vkWaitForFences(transfer)");
    const auto stop = Clock::now();
    vkDestroyFence(ctx.device(), fence, nullptr);
    vkFreeCommandBuffers(ctx.device(), ctx.command_pool(), 1, &cmd);
    return elapsed_ms(start, stop);
}

std::uint32_t mix32(std::uint32_t x) {
    x ^= x >> 16; x *= 0x7feb352du; x ^= x >> 15; x *= 0x846ca68bu; x ^= x >> 16; return x;
}

std::uint16_t f32_to_f16(float f) {
    std::uint32_t x; std::memcpy(&x, &f, 4);
    const std::uint32_t sign = (x >> 16) & 0x8000u;
    int exp = int((x >> 23) & 0xffu) - 127 + 15;
    std::uint32_t mant = x & 0x7fffffu;
    if (exp <= 0) {
        if (exp < -10) return std::uint16_t(sign);
        mant = (mant | 0x800000u) >> (1 - exp);
        return std::uint16_t(sign | ((mant + 0x1000u) >> 13));
    }
    if (exp >= 31) return std::uint16_t(sign | 0x7c00u);
    return std::uint16_t(sign | (std::uint32_t(exp) << 10) | ((mant + 0x1000u) >> 13));
}

float f16_to_f32(std::uint16_t h) {
    const std::uint32_t sign = std::uint32_t(h & 0x8000u) << 16;
    std::uint32_t exp = (h >> 10) & 0x1fu;
    std::uint32_t mant = h & 0x3ffu;
    std::uint32_t x;
    if (exp == 0) {
        if (!mant) x = sign;
        else {
            exp = 1;
            while (!(mant & 0x400u)) { mant <<= 1; --exp; }
            mant &= 0x3ffu;
            x = sign | ((exp + 112u) << 23) | (mant << 13);
        }
    } else if (exp == 31) x = sign | 0x7f800000u | (mant << 13);
    else x = sign | ((exp + 112u) << 23) | (mant << 13);
    float f; std::memcpy(&f, &x, 4); return f;
}

float u32_to_f32(std::uint32_t x) { float f; std::memcpy(&f, &x, 4); return f; }
bool close_float(float actual,float expected,float tolerance) {
    return std::isfinite(actual)&&std::isfinite(expected)&&
        std::abs(actual-expected)<=tolerance*std::max(1.0f,std::abs(expected));
}

std::uint32_t pack2(float a, float b) { return std::uint32_t(f32_to_f16(a)) | (std::uint32_t(f32_to_f16(b)) << 16); }
std::array<float,2> unpack2(std::uint32_t x) { return {f16_to_f32(std::uint16_t(x)), f16_to_f32(std::uint16_t(x >> 16))}; }

std::vector<std::uint32_t> make_confidence_lut() {
    constexpr std::size_t intervals = 4096;
    constexpr float max_distance = 0.125f;
    std::vector<std::uint32_t> words((intervals + 2) / 2, 0u);
    for (std::size_t i = 0; i <= intervals; ++i) {
        const float distance = max_distance * float(i) / float(intervals);
        const std::uint32_t code = f32_to_f16(std::exp2(-distance * 32.0f));
        words[i >> 1] |= code << ((i & 1u) * 16u);
    }
    return words;
}

std::vector<std::uint32_t> make_confidence_pair_lut() {
    constexpr std::size_t intervals = 4096;
    constexpr float max_distance = 0.125f;
    std::vector<std::uint32_t> words(intervals, 0u);
    for (std::size_t i = 0; i < intervals; ++i) {
        const float lo_distance = max_distance * float(i) / float(intervals);
        const float hi_distance = max_distance * float(i + 1) / float(intervals);
        const std::uint32_t lo = f32_to_f16(std::exp2(-lo_distance * 32.0f));
        const std::uint32_t hi = f32_to_f16(std::exp2(-hi_distance * 32.0f));
        words[i] = lo | (hi << 16u);
    }
    return words;
}

std::vector<std::uint32_t> make_log_threshold_lut() {
    constexpr std::size_t entries = 64;
    constexpr float max_distance = 0.125f;
    std::vector<std::uint32_t> words(entries / 2, 0u);
    for (std::size_t code = 0; code < entries; ++code) {
        const float distance = max_distance * float(code) / float(entries - 1);
        words[code >> 1] |= std::uint32_t(f32_to_f16(distance)) << ((code & 1u) * 16u);
    }
    return words;
}

struct alignas(16) State64 { float position_time[4], axis_radius[4], phase_guard[4]; std::uint32_t meta[4]; };
struct alignas(16) Event32 { std::uint32_t scalar_bits[4], topology_bits[4]; };
struct alignas(16) State32 { std::uint32_t words[8]; };
struct State24 { std::uint32_t words[6]; };
struct State20 { std::uint32_t words[5]; };
struct alignas(16) Event16 { std::uint32_t words[4]; };
static_assert(sizeof(State64) == 64 && sizeof(Event32) == 32 && sizeof(State32) == 32 && sizeof(State24) == 24 && sizeof(State20) == 20 && sizeof(Event16) == 16);

struct Fields {
    float px,py,pz,time, ax,ay,az,radius, cone_cos,phase,guard_epsilon,confidence_floor;
    std::uint32_t sheet,orientation,compatibility_mask,lineage_seed;
};

Fields fields_for(std::size_t i) {
    const float a = float(i % 1024) * 0.01f;
    const float r = 10.0f + float(int(i % 17) - 8) * 0.002f;
    Fields f{};
    f.px=r*std::cos(a);f.py=r*std::sin(a);f.pz=0;f.time=float(i)*0.001f;
    f.ax=std::cos(a);f.ay=std::sin(a);f.az=0;f.radius=10;
    f.cone_cos=0.5f;f.phase=float(i%256)/256.0f;f.guard_epsilon=0.010f;f.confidence_floor=0.70f;
    f.sheet=std::uint32_t(i&1u);f.orientation=std::uint32_t((i>>1u)&1u);
    f.compatibility_mask=(i%3)?4u:1u;f.lineage_seed=std::uint32_t(i*2654435761u);
    return f;
}

State64 make64(std::size_t i) {
    const auto f=fields_for(i); State64 s{};
    s.position_time[0]=f.px;s.position_time[1]=f.py;s.position_time[2]=f.pz;s.position_time[3]=f.time;
    s.axis_radius[0]=f.ax;s.axis_radius[1]=f.ay;s.axis_radius[2]=f.az;s.axis_radius[3]=f.radius;
    s.phase_guard[0]=f.cone_cos;s.phase_guard[1]=f.phase;s.phase_guard[2]=f.guard_epsilon;s.phase_guard[3]=f.confidence_floor;
    s.meta[0]=f.sheet;s.meta[1]=f.orientation;s.meta[2]=f.compatibility_mask;s.meta[3]=f.lineage_seed; return s;
}

State32 make32(std::size_t i) {
    const auto f=fields_for(i); State32 s{};
    s.words[0]=pack2(f.px,f.py);s.words[1]=pack2(f.pz,f.time);s.words[2]=pack2(f.ax,f.ay);s.words[3]=pack2(f.az,f.radius);
    s.words[4]=pack2(f.cone_cos,f.phase);s.words[5]=pack2(f.guard_epsilon,f.confidence_floor);
    s.words[6]=f.sheet|(f.orientation<<8)|((f.compatibility_mask&0xffffu)<<9);s.words[7]=f.lineage_seed; return s;
}

Fields decode32(const State32& s,std::size_t) {
    auto xy=unpack2(s.words[0]),zt=unpack2(s.words[1]),aa=unpack2(s.words[2]),ar=unpack2(s.words[3]),cp=unpack2(s.words[4]),gc=unpack2(s.words[5]);
    Fields f{};f.px=xy[0];f.py=xy[1];f.pz=zt[0];f.time=zt[1];f.ax=aa[0];f.ay=aa[1];f.az=ar[0];f.radius=ar[1];
    f.cone_cos=cp[0];f.phase=cp[1];f.guard_epsilon=gc[0];f.confidence_floor=gc[1];
    f.sheet=s.words[6]&255u;f.orientation=(s.words[6]>>8)&1u;f.compatibility_mask=(s.words[6]>>9)&0xffffu;f.lineage_seed=s.words[7];return f;
}

State32 make32_prethreshold(std::size_t i) {
    State32 s=make32(i);
    const auto guard_confidence=unpack2(s.words[5]);
    const float confidence_distance=std::isnan(guard_confidence[1])
        ? -std::numeric_limits<float>::infinity()
        : (guard_confidence[1]<=0.0f?guard_confidence[0]:-std::log2(guard_confidence[1])/32.0f);
    const float effective_distance=std::min(guard_confidence[0],confidence_distance);
    s.words[5]=pack2(guard_confidence[0],effective_distance);
    return s;
}

Fields decode32_prethreshold(const State32& s,std::size_t i) {
    Fields f=decode32(s,i);
    const float effective_distance=f.confidence_floor;
    f.confidence_floor=std::exp2(-effective_distance*32.0f);
    return f;
}

State24 make24_logthreshold(std::size_t i) {
    constexpr float max_distance=0.125f;
    const auto f=fields_for(i);
    const float packed_floor=f16_to_f32(f32_to_f16(f.confidence_floor));
    const float confidence_distance=packed_floor<=0.0f?max_distance:-std::log2(packed_floor)/32.0f;
    const auto confidence_code=std::uint32_t(std::clamp<long>(std::lround(confidence_distance/max_distance*63.0f),0,63));
    const bool compatible=(f.compatibility_mask&4u)&&f.sheet==1u&&(f.orientation&1u)==0u;
    const std::uint32_t hot_meta=(f.sheet&255u)|((f.orientation&1u)<<8)|(std::uint32_t(compatible)<<9)|(confidence_code<<10);
    State24 s{};
    s.words[0]=pack2(f.px,f.py);
    s.words[1]=pack2(f.pz,f.cone_cos);
    s.words[2]=pack2(f.ax,f.ay);
    s.words[3]=pack2(f.az,f.radius);
    s.words[4]=std::uint32_t(f32_to_f16(f.guard_epsilon))|(hot_meta<<16);
    s.words[5]=f.lineage_seed;
    return s;
}

Fields decode24_logthreshold(const State24& s,std::size_t) {
    constexpr float max_distance=0.125f;
    const auto xy=unpack2(s.words[0]),z_cone=unpack2(s.words[1]),axis_xy=unpack2(s.words[2]),axis_z_radius=unpack2(s.words[3]);
    const float guard_epsilon=f16_to_f32(std::uint16_t(s.words[4]));
    const std::uint32_t hot_meta=s.words[4]>>16;
    const std::uint32_t confidence_code=(hot_meta>>10)&63u;
    const float threshold=f16_to_f32(f32_to_f16(max_distance*float(confidence_code)/63.0f));
    Fields f{};f.px=xy[0];f.py=xy[1];f.pz=z_cone[0];f.ax=axis_xy[0];f.ay=axis_xy[1];f.az=axis_z_radius[0];f.radius=axis_z_radius[1];
    f.cone_cos=z_cone[1];f.guard_epsilon=guard_epsilon;f.confidence_floor=std::exp2(-threshold*32.0f);
    f.sheet=hot_meta&255u;f.orientation=(hot_meta>>8)&1u;f.compatibility_mask=((hot_meta>>9)&1u)?4u:0u;f.lineage_seed=s.words[5];return f;
}

State20 make20_cold_lineage(std::size_t i) {
    const State24 source=make24_logthreshold(i);
    State20 state{};
    std::copy_n(source.words,5,state.words);
    return state;
}

Fields decode20_cold_lineage(const State20& s,std::size_t i) {
    State24 expanded{};
    std::copy_n(s.words,5,expanded.words);
    expanded.words[5]=fields_for(i).lineage_seed;
    return decode24_logthreshold(expanded,i);
}

struct Eval {
    bool support=false,compatible=false,verified=false;
    float sdf=0,cone_margin=0,guard=0,confidence=0;
    std::uint32_t route=0,lineage=0,state_flags=0;
};
Eval eval(const Fields& f,std::size_t i) {
    Eval e{};const float r=std::sqrt(f.px*f.px+f.py*f.py+f.pz*f.pz);const float al=std::sqrt(f.ax*f.ax+f.ay*f.ay+f.az*f.az);
    const float c=(r>1e-8f&&al>1e-8f)?(f.px*f.ax+f.py*f.ay+f.pz*f.az)/(r*al):1.0f;
    e.sdf=r-f.radius;e.cone_margin=c-f.cone_cos;e.support=e.sdf<=0&&e.cone_margin>=0;e.compatible=(f.compatibility_mask&4u)&&f.sheet==1u&&(f.orientation&1u)==0u;
    e.guard=std::abs(e.sdf)-f.guard_epsilon;e.confidence=std::exp2(-std::abs(e.sdf)*32.0f);
    e.verified=e.support&&e.compatible&&e.guard<=0&&e.confidence>=f.confidence_floor;e.route=(f.orientation^(e.verified?1u:0u))&1u;e.lineage=mix32(f.lineage_seed^std::uint32_t(i));
    e.state_flags=(e.verified?1u:0u)|(e.route<<1)|(f.sheet<<2)|(e.support?(1u<<10):0u)|(e.compatible?(1u<<11):0u);return e;
}

struct Counts { std::uint64_t candidates=0,supported=0,compatible=0,verified=0; };
template<class T,class Decode> Counts counts_for(const std::vector<T>& states,Decode decode) {
    Counts c{};for(std::size_t i=0;i<states.size();++i){auto e=eval(decode(states[i],i),i);++c.candidates;if(e.support)++c.supported;if(e.support&&e.compatible)++c.compatible;if(e.verified)++c.verified;}return c;
}

struct ExecutableStatisticRecord {
    std::string name,description;
    VkPipelineExecutableStatisticFormatKHR format=VK_PIPELINE_EXECUTABLE_STATISTIC_FORMAT_UINT64_KHR;
    VkPipelineExecutableStatisticValueKHR value{};
};

struct InternalRepresentationRecord {
    std::string name,description;
    bool is_text=false;
    std::size_t bytes=0;
    std::string artifact;
};

struct PipelineExecutableRecord {
    std::string name,description;
    VkShaderStageFlags stages=0;
    std::uint32_t subgroup_size=0;
    std::vector<ExecutableStatisticRecord> statistics;
    std::vector<InternalRepresentationRecord> internal_representations;
};

struct PipelineProgram {
    VkShaderModule module=VK_NULL_HANDLE;VkPipelineCache cache=VK_NULL_HANDLE;VkPipeline pipeline=VK_NULL_HANDLE;
    double module_create_ms=0,cold_pipeline_ms=0,cached_pipeline_ms=0;std::vector<std::uint8_t> cache_blob;bool cache_reload_ok=false;
    std::vector<PipelineExecutableRecord> executables;
};

std::vector<PipelineExecutableRecord> capture_pipeline_executables(const VulkanContext& ctx,VkPipeline pipeline,const fs::path& artifact_dir,const std::string& artifact_tag) {
    std::vector<PipelineExecutableRecord> records;
    if(!ctx.pipeline_executable_supported())return records;
    VkPipelineInfoKHR pipeline_info{};pipeline_info.sType=VK_STRUCTURE_TYPE_PIPELINE_INFO_KHR;pipeline_info.pipeline=pipeline;
    std::uint32_t executable_count=0;check(ctx.get_pipeline_executable_properties()(ctx.device(),&pipeline_info,&executable_count,nullptr),"vkGetPipelineExecutablePropertiesKHR(count)");
    std::vector<VkPipelineExecutablePropertiesKHR> properties(executable_count);
    for(auto& property:properties)property.sType=VK_STRUCTURE_TYPE_PIPELINE_EXECUTABLE_PROPERTIES_KHR;
    if(executable_count)check(ctx.get_pipeline_executable_properties()(ctx.device(),&pipeline_info,&executable_count,properties.data()),"vkGetPipelineExecutablePropertiesKHR(list)");
    properties.resize(executable_count);records.reserve(executable_count);
    for(std::uint32_t executable_index=0;executable_index<executable_count;++executable_index){
        const auto& property=properties[executable_index];PipelineExecutableRecord record{};record.name=property.name;record.description=property.description;record.stages=property.stages;record.subgroup_size=property.subgroupSize;
        VkPipelineExecutableInfoKHR executable_info{};executable_info.sType=VK_STRUCTURE_TYPE_PIPELINE_EXECUTABLE_INFO_KHR;executable_info.pipeline=pipeline;executable_info.executableIndex=executable_index;
        std::uint32_t statistic_count=0;check(ctx.get_pipeline_executable_statistics()(ctx.device(),&executable_info,&statistic_count,nullptr),"vkGetPipelineExecutableStatisticsKHR(count)");
        std::vector<VkPipelineExecutableStatisticKHR> statistics(statistic_count);for(auto& statistic:statistics)statistic.sType=VK_STRUCTURE_TYPE_PIPELINE_EXECUTABLE_STATISTIC_KHR;
        if(statistic_count)check(ctx.get_pipeline_executable_statistics()(ctx.device(),&executable_info,&statistic_count,statistics.data()),"vkGetPipelineExecutableStatisticsKHR(list)");
        statistics.resize(statistic_count);record.statistics.reserve(statistic_count);for(const auto& statistic:statistics)record.statistics.push_back({statistic.name,statistic.description,statistic.format,statistic.value});
        std::uint32_t representation_count=0;check(ctx.get_pipeline_executable_internal_representations()(ctx.device(),&executable_info,&representation_count,nullptr),"vkGetPipelineExecutableInternalRepresentationsKHR(count)");
        std::vector<VkPipelineExecutableInternalRepresentationKHR> representations(representation_count);for(auto& representation:representations)representation.sType=VK_STRUCTURE_TYPE_PIPELINE_EXECUTABLE_INTERNAL_REPRESENTATION_KHR;
        if(representation_count){
            check(ctx.get_pipeline_executable_internal_representations()(ctx.device(),&executable_info,&representation_count,representations.data()),"vkGetPipelineExecutableInternalRepresentationsKHR(metadata)");representations.resize(representation_count);
            std::vector<std::vector<std::uint8_t>> data(representation_count);for(std::size_t i=0;i<representations.size();++i){data[i].resize(representations[i].dataSize);representations[i].pData=data[i].empty()?nullptr:data[i].data();}
            check(ctx.get_pipeline_executable_internal_representations()(ctx.device(),&executable_info,&representation_count,representations.data()),"vkGetPipelineExecutableInternalRepresentationsKHR(data)");
            fs::create_directories(artifact_dir);for(std::size_t representation_index=0;representation_index<representations.size();++representation_index){auto& representation=representations[representation_index];data[representation_index].resize(representation.dataSize);std::ostringstream filename;filename<<artifact_tag<<"_e"<<executable_index<<"_r"<<representation_index<<(representation.isText?".txt":".bin");const auto artifact_path=artifact_dir/filename.str();write_bytes(artifact_path,data[representation_index]);record.internal_representations.push_back({representation.name,representation.description,representation.isText==VK_TRUE,representation.dataSize,filename.str()});}
        }
        records.push_back(std::move(record));
    }
    return records;
}

PipelineProgram create_pipeline(const VulkanContext& ctx,VkPipelineLayout layout,const std::vector<std::uint32_t>& spv,const fs::path& cache_path) {
    PipelineProgram p{};
    VkShaderModuleCreateInfo sm{};sm.sType=VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO;sm.codeSize=spv.size()*4;sm.pCode=spv.data();
    auto t0=Clock::now();check(vkCreateShaderModule(ctx.device(),&sm,nullptr,&p.module),"vkCreateShaderModule");auto t1=Clock::now();p.module_create_ms=elapsed_ms(t0,t1);
    VkPipelineCacheCreateInfo pci{};pci.sType=VK_STRUCTURE_TYPE_PIPELINE_CACHE_CREATE_INFO;check(vkCreatePipelineCache(ctx.device(),&pci,nullptr,&p.cache),"vkCreatePipelineCache");
    VkPipelineShaderStageCreateInfo stage{};stage.sType=VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;stage.stage=VK_SHADER_STAGE_COMPUTE_BIT;stage.module=p.module;stage.pName="main";
    VkComputePipelineCreateInfo ci{};ci.sType=VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO;ci.stage=stage;ci.layout=layout;if(ctx.pipeline_executable_supported())ci.flags=VK_PIPELINE_CREATE_CAPTURE_STATISTICS_BIT_KHR|VK_PIPELINE_CREATE_CAPTURE_INTERNAL_REPRESENTATIONS_BIT_KHR;
    t0=Clock::now();check(vkCreateComputePipelines(ctx.device(),p.cache,1,&ci,nullptr,&p.pipeline),"vkCreateComputePipelines(cold)");t1=Clock::now();p.cold_pipeline_ms=elapsed_ms(t0,t1);
    std::size_t bytes=0;check(vkGetPipelineCacheData(ctx.device(),p.cache,&bytes,nullptr),"vkGetPipelineCacheData(size)");p.cache_blob.resize(bytes);
    if(bytes){check(vkGetPipelineCacheData(ctx.device(),p.cache,&bytes,p.cache_blob.data()),"vkGetPipelineCacheData(data)");p.cache_blob.resize(bytes);write_bytes(cache_path,p.cache_blob);}
    vkDestroyPipeline(ctx.device(),p.pipeline,nullptr);p.pipeline=VK_NULL_HANDLE;vkDestroyPipelineCache(ctx.device(),p.cache,nullptr);p.cache=VK_NULL_HANDLE;
    VkPipelineCacheCreateInfo warm{};warm.sType=VK_STRUCTURE_TYPE_PIPELINE_CACHE_CREATE_INFO;warm.initialDataSize=p.cache_blob.size();warm.pInitialData=p.cache_blob.data();
    check(vkCreatePipelineCache(ctx.device(),&warm,nullptr,&p.cache),"vkCreatePipelineCache(reload)");
    t0=Clock::now();VkResult result=vkCreateComputePipelines(ctx.device(),p.cache,1,&ci,nullptr,&p.pipeline);t1=Clock::now();p.cached_pipeline_ms=elapsed_ms(t0,t1);p.cache_reload_ok=result==VK_SUCCESS;check(result,"vkCreateComputePipelines(cached)");p.executables=capture_pipeline_executables(ctx,p.pipeline,cache_path.parent_path().parent_path()/"pipeline_executables",cache_path.stem().string());return p;
}

void destroy_program(const VulkanContext& ctx,PipelineProgram& p){if(p.pipeline)vkDestroyPipeline(ctx.device(),p.pipeline,nullptr);if(p.cache)vkDestroyPipelineCache(ctx.device(),p.cache,nullptr);if(p.module)vkDestroyShaderModule(ctx.device(),p.module,nullptr);p={};}

struct BenchRow {
    std::string profile,mode,counter_mode;std::size_t candidates=0,input_record_bytes=0,cold_lineage_bytes=0,output_record_bytes=0,total_buffer_bytes=0,auxiliary_lut_bytes=0,allocated_output_bytes=0,logical_output_bytes=0,output_capacity_events=0,output_events=0,overflow_events=0;bool compact=false;
    double setup_ms=0,upload_ms=0,readback_ms=0,host_min_ms=0,host_mean_ms=0,host_p50_ms=0,host_p95_ms=0,host_p99_ms=0,host_max_ms=0;
    double device_min_ms=0,device_mean_ms=0,device_p50_ms=0,device_p95_ms=0,device_p99_ms=0,device_max_ms=0;
    double candidate_rate_mps=0,verified_event_rate_mps=0,effective_bandwidth_gbps=0,confidence_abs_error_max=0,confidence_abs_error_mean=0;std::size_t validated_outputs=0,oracle_exact_outputs=0,boundary_divergent_outputs=0;std::uint64_t discrete_semantic_hash=1469598103934665603ull;Counts counts{},oracle_counts{};bool counters_ok=false,sample_ok=false,completeness_ok=true,overflow_ok=true;
};

template<class StateT,class EventT,class Make,class Decode>
BenchRow run_one(const VulkanContext& ctx,VkDescriptorSetLayout dsl,VkPipelineLayout layout,VkPipeline pipeline,const std::string& profile,const std::string& mode,bool commit,int lut_kind,bool compact,bool full_counters,std::size_t n,int warmup,int warmup_ms,int iterations,double compact_capacity_ratio,Make make,Decode decode) {
    auto setup0=Clock::now();
    std::vector<StateT> states(n);for(std::size_t i=0;i<n;++i)states[i]=make(i);const Counts expected=counts_for(states,decode);
    const bool cold_lineage=profile=="G20_E16_LOGTHRESH_DIRECT_COLD_LINEAGE_SUBGROUP_COMPACT";
    std::vector<std::uint32_t> lineage_words(cold_lineage?n:1,0u);
    if(cold_lineage)for(std::size_t i=0;i<n;++i)lineage_words[i]=fields_for(i).lineage_seed;
    const auto lut_words=lut_kind==3?make_log_threshold_lut():(lut_kind==2?make_confidence_pair_lut():(lut_kind==1?make_confidence_lut():std::vector<std::uint32_t>{0u}));
    const std::size_t output_capacity_events=compact?std::max<std::size_t>(1,std::min(n,std::size_t(std::ceil(double(n)*compact_capacity_ratio)))):n;
    const VkDeviceSize input_bytes=n*sizeof(StateT),output_bytes=output_capacity_events*sizeof(EventT),counter_bytes=16,lut_bytes=lut_words.size()*sizeof(std::uint32_t),lineage_bytes=lineage_words.size()*sizeof(std::uint32_t);
    MappedBuffer upload(ctx,input_bytes,VK_BUFFER_USAGE_TRANSFER_SRC_BIT);
    MappedBuffer lut_upload(ctx,lut_bytes,VK_BUFFER_USAGE_TRANSFER_SRC_BIT);
    MappedBuffer lineage_upload(ctx,lineage_bytes,VK_BUFFER_USAGE_TRANSFER_SRC_BIT);
    MappedBuffer output_readback(ctx,output_bytes,VK_BUFFER_USAGE_TRANSFER_DST_BIT);
    MappedBuffer counter_readback(ctx,counter_bytes,VK_BUFFER_USAGE_TRANSFER_DST_BIT);
    DeviceBuffer input(ctx,input_bytes,VK_BUFFER_USAGE_STORAGE_BUFFER_BIT|VK_BUFFER_USAGE_TRANSFER_DST_BIT);
    DeviceBuffer lut(ctx,lut_bytes,VK_BUFFER_USAGE_UNIFORM_TEXEL_BUFFER_BIT|VK_BUFFER_USAGE_TRANSFER_DST_BIT);
    DeviceBuffer lineage_buffer(ctx,lineage_bytes,VK_BUFFER_USAGE_STORAGE_BUFFER_BIT|VK_BUFFER_USAGE_TRANSFER_DST_BIT);
    DeviceBuffer output(ctx,output_bytes,VK_BUFFER_USAGE_STORAGE_BUFFER_BIT|VK_BUFFER_USAGE_TRANSFER_SRC_BIT);
    DeviceBuffer counter(ctx,counter_bytes,VK_BUFFER_USAGE_STORAGE_BUFFER_BIT|VK_BUFFER_USAGE_TRANSFER_SRC_BIT|VK_BUFFER_USAGE_TRANSFER_DST_BIT);
    std::memcpy(upload.mapped,states.data(),std::size_t(input_bytes));
    std::memcpy(lut_upload.mapped,lut_words.data(),std::size_t(lut_bytes));
    std::memcpy(lineage_upload.mapped,lineage_words.data(),std::size_t(lineage_bytes));
    const double upload_ms=submit_once(ctx,"vkQueueSubmit(upload)",[&](VkCommandBuffer transfer_cmd){
        VkBufferMemoryBarrier host_to_transfer[3]{};for(auto& b:host_to_transfer){b.sType=VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER;b.srcAccessMask=VK_ACCESS_HOST_WRITE_BIT;b.dstAccessMask=VK_ACCESS_TRANSFER_READ_BIT;b.srcQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED;b.dstQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED;b.offset=0;b.size=VK_WHOLE_SIZE;}host_to_transfer[0].buffer=upload.buffer;host_to_transfer[1].buffer=lut_upload.buffer;host_to_transfer[2].buffer=lineage_upload.buffer;
        vkCmdPipelineBarrier(transfer_cmd,VK_PIPELINE_STAGE_HOST_BIT,VK_PIPELINE_STAGE_TRANSFER_BIT,0,0,nullptr,3,host_to_transfer,0,nullptr);
        VkBufferCopy input_region{0,0,input_bytes};vkCmdCopyBuffer(transfer_cmd,upload.buffer,input.buffer,1,&input_region);
        VkBufferCopy lut_region{0,0,lut_bytes};vkCmdCopyBuffer(transfer_cmd,lut_upload.buffer,lut.buffer,1,&lut_region);
        VkBufferCopy lineage_region{0,0,lineage_bytes};vkCmdCopyBuffer(transfer_cmd,lineage_upload.buffer,lineage_buffer.buffer,1,&lineage_region);
        VkBufferMemoryBarrier transfer_to_compute[3]{};for(auto& b:transfer_to_compute){b.sType=VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER;b.srcAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT;b.dstAccessMask=VK_ACCESS_SHADER_READ_BIT;b.srcQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED;b.dstQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED;b.offset=0;b.size=VK_WHOLE_SIZE;}transfer_to_compute[0].buffer=input.buffer;transfer_to_compute[1].buffer=lut.buffer;transfer_to_compute[2].buffer=lineage_buffer.buffer;
        vkCmdPipelineBarrier(transfer_cmd,VK_PIPELINE_STAGE_TRANSFER_BIT,VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,0,0,nullptr,3,transfer_to_compute,0,nullptr);
    });
    VkBufferViewCreateInfo bvci{};bvci.sType=VK_STRUCTURE_TYPE_BUFFER_VIEW_CREATE_INFO;bvci.buffer=lut.buffer;bvci.format=VK_FORMAT_R32_UINT;bvci.offset=0;bvci.range=lut_bytes;VkBufferView lut_view=VK_NULL_HANDLE;check(vkCreateBufferView(ctx.device(),&bvci,nullptr,&lut_view),"vkCreateBufferView(confidence LUT)");
    VkDescriptorPoolSize ps[2]={{VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,4},{VK_DESCRIPTOR_TYPE_UNIFORM_TEXEL_BUFFER,1}};VkDescriptorPoolCreateInfo dp{};dp.sType=VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO;dp.maxSets=1;dp.poolSizeCount=2;dp.pPoolSizes=ps;
    VkDescriptorPool pool=VK_NULL_HANDLE;check(vkCreateDescriptorPool(ctx.device(),&dp,nullptr,&pool),"vkCreateDescriptorPool");
    VkDescriptorSetAllocateInfo dai{};dai.sType=VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO;dai.descriptorPool=pool;dai.descriptorSetCount=1;dai.pSetLayouts=&dsl;VkDescriptorSet set=VK_NULL_HANDLE;check(vkAllocateDescriptorSets(ctx.device(),&dai,&set),"vkAllocateDescriptorSets");
    VkDescriptorBufferInfo infos[4]={{input.buffer,0,input.size},{output.buffer,0,output.size},{counter.buffer,0,counter.size},{lineage_buffer.buffer,0,lineage_buffer.size}};VkWriteDescriptorSet writes[5]{};
    for(std::uint32_t i=0;i<3;++i){writes[i].sType=VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;writes[i].dstSet=set;writes[i].dstBinding=i;writes[i].descriptorCount=1;writes[i].descriptorType=VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;writes[i].pBufferInfo=&infos[i];}
    writes[3].sType=VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;writes[3].dstSet=set;writes[3].dstBinding=3;writes[3].descriptorCount=1;writes[3].descriptorType=VK_DESCRIPTOR_TYPE_UNIFORM_TEXEL_BUFFER;writes[3].pTexelBufferView=&lut_view;
    writes[4].sType=VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;writes[4].dstSet=set;writes[4].dstBinding=4;writes[4].descriptorCount=1;writes[4].descriptorType=VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;writes[4].pBufferInfo=&infos[3];
    vkUpdateDescriptorSets(ctx.device(),5,writes,0,nullptr);
    VkCommandBufferAllocateInfo cai{};cai.sType=VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;cai.commandPool=ctx.command_pool();cai.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY;cai.commandBufferCount=1;VkCommandBuffer cmd=VK_NULL_HANDLE;check(vkAllocateCommandBuffers(ctx.device(),&cai,&cmd),"vkAllocateCommandBuffers");
    VkQueryPoolCreateInfo qci{};qci.sType=VK_STRUCTURE_TYPE_QUERY_POOL_CREATE_INFO;qci.queryType=VK_QUERY_TYPE_TIMESTAMP;qci.queryCount=2;VkQueryPool qp=VK_NULL_HANDLE;check(vkCreateQueryPool(ctx.device(),&qci,nullptr,&qp),"vkCreateQueryPool");
    VkCommandBufferBeginInfo bi{};bi.sType=VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;bi.flags=VK_COMMAND_BUFFER_USAGE_SIMULTANEOUS_USE_BIT;check(vkBeginCommandBuffer(cmd,&bi),"vkBeginCommandBuffer");
    vkCmdResetQueryPool(cmd,qp,0,2);vkCmdFillBuffer(cmd,counter.buffer,0,counter.size,0u);
    VkBufferMemoryBarrier clear_to_compute{};clear_to_compute.sType=VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER;clear_to_compute.srcAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT;clear_to_compute.dstAccessMask=VK_ACCESS_SHADER_READ_BIT|VK_ACCESS_SHADER_WRITE_BIT;clear_to_compute.srcQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED;clear_to_compute.dstQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED;clear_to_compute.buffer=counter.buffer;clear_to_compute.offset=0;clear_to_compute.size=VK_WHOLE_SIZE;
    vkCmdPipelineBarrier(cmd,VK_PIPELINE_STAGE_TRANSFER_BIT,VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,0,0,nullptr,1,&clear_to_compute,0,nullptr);
    vkCmdWriteTimestamp(cmd,VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,qp,0);vkCmdBindPipeline(cmd,VK_PIPELINE_BIND_POINT_COMPUTE,pipeline);vkCmdBindDescriptorSets(cmd,VK_PIPELINE_BIND_POINT_COMPUTE,layout,0,1,&set,0,nullptr);vkCmdDispatch(cmd,std::uint32_t((n+255)/256),1,1);vkCmdWriteTimestamp(cmd,VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT,qp,1);check(vkEndCommandBuffer(cmd),"vkEndCommandBuffer");
    VkFenceCreateInfo fci{};fci.sType=VK_STRUCTURE_TYPE_FENCE_CREATE_INFO;VkFence fence=VK_NULL_HANDLE;check(vkCreateFence(ctx.device(),&fci,nullptr,&fence),"vkCreateFence");
    VkSubmitInfo si{};si.sType=VK_STRUCTURE_TYPE_SUBMIT_INFO;si.commandBufferCount=1;si.pCommandBuffers=&cmd;
    auto setup1=Clock::now();
    auto submit=[&](double* host,double* device){check(vkResetFences(ctx.device(),1,&fence),"vkResetFences");auto a=Clock::now();check(vkQueueSubmit(ctx.queue(),1,&si,fence),"vkQueueSubmit");check(vkWaitForFences(ctx.device(),1,&fence,VK_TRUE,std::numeric_limits<std::uint64_t>::max()),"vkWaitForFences");auto b=Clock::now();if(host)*host=elapsed_ms(a,b);std::uint64_t ticks[2]={};check(vkGetQueryPoolResults(ctx.device(),qp,0,2,sizeof(ticks),ticks,sizeof(std::uint64_t),VK_QUERY_RESULT_64_BIT|VK_QUERY_RESULT_WAIT_BIT),"vkGetQueryPoolResults");std::uint64_t delta=0;if(ctx.timestamp_bits()>=64)delta=ticks[1]-ticks[0];else if(ctx.timestamp_bits()>0){const std::uint64_t mask=(std::uint64_t(1)<<ctx.timestamp_bits())-1;delta=(ticks[1]-ticks[0])&mask;}if(device)*device=double(delta)*double(ctx.timestamp_period_ns())/1.0e6;};
    int warmup_submissions=0;const auto warmup_start=Clock::now();while(warmup_submissions<warmup||elapsed_ms(warmup_start,Clock::now())<warmup_ms){submit(nullptr,nullptr);++warmup_submissions;}
    std::vector<double> host_times,device_times;host_times.reserve(iterations);device_times.reserve(iterations);for(int i=0;i<iterations;++i){double h=0,d=0;submit(&h,&d);host_times.push_back(h);device_times.push_back(d);}
    const double readback_ms=submit_once(ctx,"vkQueueSubmit(readback)",[&](VkCommandBuffer transfer_cmd){
        VkBufferMemoryBarrier compute_to_transfer[2]{};for(auto& b:compute_to_transfer){b.sType=VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER;b.srcAccessMask=VK_ACCESS_SHADER_WRITE_BIT;b.dstAccessMask=VK_ACCESS_TRANSFER_READ_BIT;b.srcQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED;b.dstQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED;b.offset=0;b.size=VK_WHOLE_SIZE;}compute_to_transfer[0].buffer=output.buffer;compute_to_transfer[1].buffer=counter.buffer;
        vkCmdPipelineBarrier(transfer_cmd,VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,VK_PIPELINE_STAGE_TRANSFER_BIT,0,0,nullptr,2,compute_to_transfer,0,nullptr);
        VkBufferCopy output_region{0,0,output_bytes};vkCmdCopyBuffer(transfer_cmd,output.buffer,output_readback.buffer,1,&output_region);
        VkBufferCopy counter_region{0,0,counter_bytes};vkCmdCopyBuffer(transfer_cmd,counter.buffer,counter_readback.buffer,1,&counter_region);
        VkBufferMemoryBarrier transfer_to_host[2]{};for(auto& b:transfer_to_host){b.sType=VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER;b.srcAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT;b.dstAccessMask=VK_ACCESS_HOST_READ_BIT;b.srcQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED;b.dstQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED;b.offset=0;b.size=VK_WHOLE_SIZE;}transfer_to_host[0].buffer=output_readback.buffer;transfer_to_host[1].buffer=counter_readback.buffer;
        vkCmdPipelineBarrier(transfer_cmd,VK_PIPELINE_STAGE_TRANSFER_BIT,VK_PIPELINE_STAGE_HOST_BIT,0,0,nullptr,2,transfer_to_host,0,nullptr);
    });
    const auto* committed_counts=static_cast<const std::uint32_t*>(counter_readback.mapped);
    Counts committed{committed_counts[0],committed_counts[1],committed_counts[2],committed_counts[3]};
    bool sample_ok=true,completeness_ok=true;std::size_t validated_outputs=0,oracle_exact_outputs=0,boundary_divergent_outputs=0;double confidence_abs_error_max=0,confidence_abs_error_sum=0;std::uint64_t discrete_semantic_hash=1469598103934665603ull;Counts observed{};const EventT* events=static_cast<const EventT*>(output_readback.mapped);
    const auto hash_word=[&](std::uint32_t word){for(int byte=0;byte<4;++byte){discrete_semantic_hash^=std::uint8_t(word>>(byte*8));discrete_semantic_hash*=1099511628211ull;}};
    const auto is_boundary=[](const Eval& e,const Fields& f){return std::abs(e.sdf)<=5e-5f||std::abs(e.cone_margin)<=5e-5f||std::abs(e.guard)<=5e-5f||std::abs(e.confidence-f.confidence_floor)<=5e-5f;};
    if(!compact){
        for(std::size_t i=0;i<n;++i){
            const auto f=decode(states[i],i);const auto e=eval(f,i);std::uint32_t flags=0,lineage=0,verified_word=0,route_word=0;float actual_confidence=0;bool scalar_valid=false;
            if constexpr(sizeof(EventT)==32){const auto& event=events[i];flags=event.topology_bits[3];lineage=event.topology_bits[2];verified_word=event.topology_bits[0];route_word=event.topology_bits[1];actual_confidence=u32_to_f32(event.scalar_bits[2]);scalar_valid=close_float(u32_to_f32(event.scalar_bits[0]),e.sdf,5e-5f)&&close_float(u32_to_f32(event.scalar_bits[1]),e.guard,5e-5f)&&close_float(actual_confidence,e.confidence,5e-5f)&&u32_to_f32(event.scalar_bits[3])==f.time;hash_word(event.scalar_bits[0]);hash_word(event.scalar_bits[1]);hash_word(event.scalar_bits[3]);for(const auto word:event.topology_bits)hash_word(word);}
            else{const auto& event=events[i];const auto packed=unpack2(event.words[1]);flags=event.words[2];lineage=event.words[3];verified_word=flags&1u;route_word=(flags>>1)&1u;actual_confidence=packed[1];scalar_valid=close_float(u32_to_f32(event.words[0]),e.sdf,5e-4f)&&close_float(packed[0],e.guard,2e-3f)&&close_float(actual_confidence,e.confidence,2e-3f);hash_word(event.words[0]);hash_word(event.words[1]&0xffffu);hash_word(event.words[2]);hash_word(event.words[3]);}
            const double confidence_error=std::abs(double(actual_confidence)-double(e.confidence));confidence_abs_error_max=std::max(confidence_abs_error_max,confidence_error);confidence_abs_error_sum+=confidence_error;
            const bool actual_verified=(flags&1u)!=0,actual_support=(flags&(1u<<10))!=0,actual_compatible=(flags&(1u<<11))!=0;const std::uint32_t actual_route=(flags>>1)&1u;
            ++observed.candidates;if(actual_support)++observed.supported;if(actual_support&&actual_compatible)++observed.compatible;if(actual_verified)++observed.verified;
            const std::uint32_t internally_expected_flags=(actual_verified?1u:0u)|(actual_route<<1)|(f.sheet<<2)|(actual_support?(1u<<10):0u)|(actual_compatible?(1u<<11):0u);
            const bool internally_consistent=flags==internally_expected_flags&&verified_word==(actual_verified?1u:0u)&&route_word==actual_route&&actual_route==((f.orientation^(actual_verified?1u:0u))&1u)&&lineage==e.lineage&&actual_compatible==e.compatible;
            const bool oracle_exact=flags==e.state_flags;const bool boundary_case=is_boundary(e,f);
            const bool valid=internally_consistent&&scalar_valid&&(oracle_exact||boundary_case);
            if(!valid){std::cerr<<"validation mismatch "<<profile<<' '<<mode<<" i="<<i<<" flags="<<flags<<" expected_flags="<<e.state_flags<<" scalar_valid="<<(scalar_valid?1:0)<<" internal_valid="<<(internally_consistent?1:0)<<" boundary="<<(boundary_case?1:0)<<'\n';sample_ok=false;break;}
            ++validated_outputs;if(oracle_exact)++oracle_exact_outputs;else ++boundary_divergent_outputs;
        }
    } else {
        if constexpr(sizeof(EventT)==16){
            std::unordered_map<std::uint32_t,std::vector<std::size_t>> eligible;
            eligible.reserve(std::size_t(expected.verified)+n/8+1024);
            for(std::size_t i=0;i<n;++i){const auto f=decode(states[i],i);const auto e=eval(f,i);if(e.verified||is_boundary(e,f))eligible[e.lineage].push_back(i);}
            const std::size_t compact_count=std::size_t(committed.verified);
            if(compact_count>n){std::cerr<<"compact output count exceeds capacity: "<<compact_count<<" > "<<n<<'\n';sample_ok=false;}
            const std::size_t inspect_count=std::min(compact_count,output_capacity_events);
            completeness_ok=compact_count<=output_capacity_events;
            for(std::size_t slot=0;sample_ok&&slot<inspect_count;++slot){
                const auto& event=events[slot];const auto packed=unpack2(event.words[1]);const std::uint32_t flags=event.words[2],lineage=event.words[3];auto found=eligible.find(lineage);
                if(found==eligible.end()){std::cerr<<"unexpected or duplicate compact lineage at slot="<<slot<<" lineage="<<lineage<<'\n';sample_ok=false;break;}
                bool matched=false;
                for(std::size_t bucket_index=0;bucket_index<found->second.size();++bucket_index){
                    const std::size_t i=found->second[bucket_index];const auto f=decode(states[i],i);const auto e=eval(f,i);const float actual_confidence=packed[1];
                    const bool scalar_valid=close_float(u32_to_f32(event.words[0]),e.sdf,5e-4f)&&close_float(packed[0],e.guard,2e-3f)&&close_float(actual_confidence,e.confidence,2e-3f);
                    const bool actual_verified=(flags&1u)!=0,actual_support=(flags&(1u<<10))!=0,actual_compatible=(flags&(1u<<11))!=0;const std::uint32_t actual_route=(flags>>1)&1u;
                    const std::uint32_t internally_expected_flags=1u|(actual_route<<1)|(f.sheet<<2)|(1u<<10)|(1u<<11);
                    const bool internally_consistent=actual_verified&&actual_support&&actual_compatible&&flags==internally_expected_flags&&actual_route==((f.orientation^1u)&1u)&&lineage==e.lineage&&e.compatible;
                    const bool oracle_exact=flags==e.state_flags;const bool boundary_case=is_boundary(e,f);const bool valid=internally_consistent&&scalar_valid&&(oracle_exact||boundary_case);
                    if(!valid)continue;
                    const double confidence_error=std::abs(double(actual_confidence)-double(e.confidence));confidence_abs_error_max=std::max(confidence_abs_error_max,confidence_error);confidence_abs_error_sum+=confidence_error;
                    hash_word(event.words[0]);hash_word(event.words[1]&0xffffu);hash_word(event.words[2]);hash_word(event.words[3]);
                    ++validated_outputs;if(oracle_exact)++oracle_exact_outputs;else ++boundary_divergent_outputs;
                    found->second[bucket_index]=found->second.back();found->second.pop_back();if(found->second.empty())eligible.erase(found);matched=true;break;
                }
                if(!matched){std::cerr<<"compact payload did not match any source in lineage bucket at slot="<<slot<<" lineage="<<lineage<<'\n';sample_ok=false;break;}
            }
            if(completeness_ok)for(const auto& item:eligible){if(!sample_ok)break;for(const auto source_i:item.second){const auto f=decode(states[source_i],source_i);const auto e=eval(f,source_i);if(e.verified&&!is_boundary(e,f)){std::cerr<<"missing non-boundary compact event source_i="<<source_i<<'\n';sample_ok=false;break;}}}
            observed={n,full_counters?committed.supported:0,full_counters?committed.compatible:0,committed.verified};
        } else {std::cerr<<"compact validation requires E16 output\n";sample_ok=false;}
    }
    const std::size_t retained_events=compact?std::min(std::size_t(committed.verified),output_capacity_events):n;
    const std::size_t overflow_events=compact&&std::size_t(committed.verified)>output_capacity_events?std::size_t(committed.verified)-output_capacity_events:0;
    const bool retained_count_ok=!compact||validated_outputs==retained_events;
    const bool counters_ok=compact?(full_counters?(committed.candidates==n&&committed.supported==expected.supported&&committed.compatible==expected.compatible&&retained_count_ok):(committed.candidates==0&&committed.supported==0&&committed.compatible==0&&retained_count_ok)):(!commit||(committed.candidates==observed.candidates&&committed.supported==observed.supported&&committed.compatible==observed.compatible&&committed.verified==observed.verified));
    if(!counters_ok)std::cerr<<"counter mismatch "<<profile<<' '<<mode<<" observed="<<observed.candidates<<','<<observed.supported<<','<<observed.compatible<<','<<observed.verified<<" committed="<<committed.candidates<<','<<committed.supported<<','<<committed.compatible<<','<<committed.verified<<'\n';
    BenchRow r{};r.profile=profile;r.mode=mode;r.counter_mode=compact?(full_counters?"full_plus_verified_append":"verified_append"):(commit?"full":"none");r.compact=compact;r.candidates=n;r.input_record_bytes=sizeof(StateT);r.cold_lineage_bytes=cold_lineage?std::size_t(lineage_bytes):0;r.output_record_bytes=sizeof(EventT);r.auxiliary_lut_bytes=lut_kind?std::size_t(lut_bytes):0;r.allocated_output_bytes=std::size_t(output_bytes);r.output_capacity_events=output_capacity_events;r.output_events=retained_events;r.overflow_events=overflow_events;r.logical_output_bytes=r.output_events*sizeof(EventT);r.total_buffer_bytes=std::size_t(input_bytes)+r.cold_lineage_bytes+r.allocated_output_bytes+16+r.auxiliary_lut_bytes;r.setup_ms=elapsed_ms(setup0,setup1);r.upload_ms=upload_ms;r.readback_ms=readback_ms;
    r.host_min_ms=*std::min_element(host_times.begin(),host_times.end());r.host_max_ms=*std::max_element(host_times.begin(),host_times.end());r.host_mean_ms=std::accumulate(host_times.begin(),host_times.end(),0.0)/host_times.size();r.host_p50_ms=percentile(host_times,.5);r.host_p95_ms=percentile(host_times,.95);r.host_p99_ms=percentile(host_times,.99);
    r.device_min_ms=*std::min_element(device_times.begin(),device_times.end());r.device_max_ms=*std::max_element(device_times.begin(),device_times.end());r.device_mean_ms=std::accumulate(device_times.begin(),device_times.end(),0.0)/device_times.size();r.device_p50_ms=percentile(device_times,.5);r.device_p95_ms=percentile(device_times,.95);r.device_p99_ms=percentile(device_times,.99);
    const double basis=r.device_p50_ms>0?r.device_p50_ms:r.host_p50_ms;r.candidate_rate_mps=double(n)/basis/1000.0;r.verified_event_rate_mps=double(observed.verified)/basis/1000.0;r.effective_bandwidth_gbps=double(std::size_t(input_bytes)+r.cold_lineage_bytes+r.logical_output_bytes)/(basis*1e6);r.confidence_abs_error_max=confidence_abs_error_max;r.confidence_abs_error_mean=validated_outputs?confidence_abs_error_sum/double(validated_outputs):0;r.validated_outputs=validated_outputs;r.oracle_exact_outputs=oracle_exact_outputs;r.boundary_divergent_outputs=boundary_divergent_outputs;r.discrete_semantic_hash=discrete_semantic_hash;r.counts=observed;r.oracle_counts=expected;r.counters_ok=counters_ok;r.sample_ok=sample_ok;r.completeness_ok=completeness_ok;
    vkDestroyFence(ctx.device(),fence,nullptr);vkDestroyQueryPool(ctx.device(),qp,nullptr);vkFreeCommandBuffers(ctx.device(),ctx.command_pool(),1,&cmd);vkDestroyDescriptorPool(ctx.device(),pool,nullptr);vkDestroyBufferView(ctx.device(),lut_view,nullptr);return r;
}

struct ProgramRecord {std::string name;fs::path spv_path;PipelineProgram program;};

void write_json(const VulkanContext& ctx,const Args& args,const std::vector<ProgramRecord>& programs,const std::vector<BenchRow>& rows,const fs::path& path) {
    std::ofstream f(path);f<<std::fixed<<std::setprecision(6);const auto&p=ctx.properties();
    f<<"{\n  \"schema\": \"UGTS-VK-BENCH-1.8\",\n  \"runtime\": \"Vulkan compute\",\n"
     <<"  \"physical_gpu_claim\": "<<(p.deviceType==VK_PHYSICAL_DEVICE_TYPE_CPU?"false":"true")<<",\n"
     <<"  \"memory_path\": {\"storage\": \"device-local Vulkan buffers\", \"transfer\": \"explicit host-visible coherent staging\", \"timed_scope\": \"compute dispatch only\"},\n"
     <<"  \"validation\": {\"coverage\": \"all dense records; every retained compact record; non-boundary completeness when capacity does not overflow; exact compact demand cross-checked against dense GPU output\", \"fields\": \"scalar, guard, confidence, route, lineage, state flags, append uniqueness, overflow demand, and commit counters\"},\n"
     <<"  \"device\": {\"name\": \""<<json_escape(p.deviceName)<<"\", \"type\": "<<int(p.deviceType)<<", \"vendor_id\": "<<p.vendorID<<", \"device_id\": "<<p.deviceID<<", \"api_version\": \""<<api_major(p.apiVersion)<<'.'<<api_minor(p.apiVersion)<<'.'<<api_patch(p.apiVersion)<<"\", \"timestamp_period_ns\": "<<p.limits.timestampPeriod<<", \"timestamp_valid_bits\": "<<ctx.timestamp_bits()<<", \"pipeline_executable_capture\": "<<(ctx.pipeline_executable_supported()?"true":"false")<<", \"performance_query_extension_present\": "<<(ctx.performance_query_extension_present()?"true":"false")<<"},\n"
     <<"  \"run_parameters\": {\"warmup\": "<<args.warmup<<", \"warmup_ms\": "<<args.warmup_ms<<", \"iterations\": "<<args.iterations<<", \"compact_only\": "<<(args.compact_only?"true":"false")<<", \"compact_reverse\": "<<(args.compact_reverse?"true":"false")<<", \"compact_capacity_ratio\": "<<args.compact_capacity_ratio<<", \"allow_compact_overflow\": "<<(args.allow_compact_overflow?"true":"false")<<", \"prethreshold_only\": "<<(args.prethreshold_only?"true":"false")<<", \"hot_log_lut_only\": "<<(args.hot_log_lut_only?"true":"false")<<", \"cold_lineage_only\": "<<(args.cold_lineage_only?"true":"false")<<", \"lut_only\": "<<(args.lut_only?"true":"false")<<", \"lut_reverse\": "<<(args.lut_reverse?"true":"false")<<"},\n  \"programs\": [\n";
    for(std::size_t i=0;i<programs.size();++i){const auto&x=programs[i];f<<"    {\"name\": \""<<x.name<<"\", \"spirv_bytes\": "<<fs::file_size(x.spv_path)<<", \"shader_module_create_ms\": "<<x.program.module_create_ms<<", \"cold_pipeline_create_ms\": "<<x.program.cold_pipeline_ms<<", \"pipeline_cache_bytes\": "<<x.program.cache_blob.size()<<", \"cached_pipeline_create_ms\": "<<x.program.cached_pipeline_ms<<", \"cache_reload_ok\": "<<(x.program.cache_reload_ok?"true":"false")<<", \"pipeline_executables\": [";
        for(std::size_t executable_index=0;executable_index<x.program.executables.size();++executable_index){const auto& executable=x.program.executables[executable_index];if(executable_index)f<<',';f<<"{\"name\":\""<<json_escape(executable.name)<<"\",\"description\":\""<<json_escape(executable.description)<<"\",\"stages\":"<<executable.stages<<",\"subgroup_size\":"<<executable.subgroup_size<<",\"statistics\":[";
            for(std::size_t statistic_index=0;statistic_index<executable.statistics.size();++statistic_index){const auto& statistic=executable.statistics[statistic_index];if(statistic_index)f<<',';f<<"{\"name\":\""<<json_escape(statistic.name)<<"\",\"description\":\""<<json_escape(statistic.description)<<"\",\"format\":"<<int(statistic.format)<<",\"value\":";switch(statistic.format){case VK_PIPELINE_EXECUTABLE_STATISTIC_FORMAT_BOOL32_KHR:f<<(statistic.value.b32?"true":"false");break;case VK_PIPELINE_EXECUTABLE_STATISTIC_FORMAT_INT64_KHR:f<<statistic.value.i64;break;case VK_PIPELINE_EXECUTABLE_STATISTIC_FORMAT_UINT64_KHR:f<<statistic.value.u64;break;case VK_PIPELINE_EXECUTABLE_STATISTIC_FORMAT_FLOAT64_KHR:f<<statistic.value.f64;break;default:f<<"null";break;}f<<'}';}
            f<<"],\"internal_representations\":[";for(std::size_t representation_index=0;representation_index<executable.internal_representations.size();++representation_index){const auto& representation=executable.internal_representations[representation_index];if(representation_index)f<<',';f<<"{\"name\":\""<<json_escape(representation.name)<<"\",\"description\":\""<<json_escape(representation.description)<<"\",\"is_text\":"<<(representation.is_text?"true":"false")<<",\"bytes\":"<<representation.bytes<<",\"artifact\":\"pipeline_executables/"<<json_escape(representation.artifact)<<"\"}";}f<<"]}";
        }
        f<<"]}"<<(i+1==programs.size()?"\n":",\n");}
    f<<"  ],\n  \"benchmarks\": [\n";
    for(std::size_t i=0;i<rows.size();++i){const auto&r=rows[i];f<<"    {\"profile\": \""<<r.profile<<"\", \"mode\": \""<<r.mode<<"\", \"compact\": "<<(r.compact?"true":"false")<<", \"counter_mode\": \""<<r.counter_mode<<"\", \"candidates\": "<<r.candidates<<", \"input_record_bytes\": "<<r.input_record_bytes<<", \"cold_lineage_bytes\": "<<r.cold_lineage_bytes<<", \"output_record_bytes\": "<<r.output_record_bytes<<", \"total_buffer_bytes\": "<<r.total_buffer_bytes<<", \"allocated_output_bytes\": "<<r.allocated_output_bytes<<", \"logical_output_bytes\": "<<r.logical_output_bytes<<", \"output_capacity_events\": "<<r.output_capacity_events<<", \"output_events\": "<<r.output_events<<", \"overflow_events\": "<<r.overflow_events<<", \"auxiliary_lut_bytes\": "<<r.auxiliary_lut_bytes<<", \"setup_ms\": "<<r.setup_ms<<", \"upload_ms\": "<<r.upload_ms<<", \"readback_ms\": "<<r.readback_ms<<", \"host_dispatch_ms\": {\"min\": "<<r.host_min_ms<<", \"mean\": "<<r.host_mean_ms<<", \"p50\": "<<r.host_p50_ms<<", \"p95\": "<<r.host_p95_ms<<", \"p99\": "<<r.host_p99_ms<<", \"max\": "<<r.host_max_ms<<"}, \"device_dispatch_ms\": {\"min\": "<<r.device_min_ms<<", \"mean\": "<<r.device_mean_ms<<", \"p50\": "<<r.device_p50_ms<<", \"p95\": "<<r.device_p95_ms<<", \"p99\": "<<r.device_p99_ms<<", \"max\": "<<r.device_max_ms<<"}, \"candidate_rate_mps\": "<<r.candidate_rate_mps<<", \"verified_event_rate_mps\": "<<r.verified_event_rate_mps<<", \"effective_bandwidth_gbps\": "<<r.effective_bandwidth_gbps<<", \"confidence_abs_error_max\": "<<r.confidence_abs_error_max<<", \"confidence_abs_error_mean\": "<<r.confidence_abs_error_mean<<", \"discrete_semantic_hash\": "<<r.discrete_semantic_hash<<", \"counts\": {\"candidates\": "<<r.counts.candidates<<", \"supported\": "<<r.counts.supported<<", \"compatible\": "<<r.counts.compatible<<", \"verified\": "<<r.counts.verified<<"}, \"oracle_counts\": {\"candidates\": "<<r.oracle_counts.candidates<<", \"supported\": "<<r.oracle_counts.supported<<", \"compatible\": "<<r.oracle_counts.compatible<<", \"verified\": "<<r.oracle_counts.verified<<"}, \"validated_outputs\": "<<r.validated_outputs<<", \"oracle_exact_outputs\": "<<r.oracle_exact_outputs<<", \"boundary_divergent_outputs\": "<<r.boundary_divergent_outputs<<", \"completeness_validation\": "<<(r.completeness_ok?"true":"false")<<", \"overflow_validation\": "<<(r.overflow_ok?"true":"false")<<", \"counter_validation\": "<<(r.counters_ok?"true":"false")<<", \"sample_validation\": "<<(r.sample_ok?"true":"false")<<"}"<<(i+1==rows.size()?"\n":",\n");}
    f<<"  ]\n}\n";
}

void write_csv(const std::vector<BenchRow>& rows,const fs::path& path) {
    std::ofstream f(path);f<<"profile,mode,compact,counter_mode,candidates,input_record_bytes,cold_lineage_bytes,output_record_bytes,total_buffer_bytes,allocated_output_bytes,logical_output_bytes,output_capacity_events,output_events,overflow_events,auxiliary_lut_bytes,setup_ms,upload_ms,readback_ms,host_p50_ms,host_p95_ms,host_p99_ms,device_p50_ms,device_p95_ms,device_p99_ms,candidate_rate_mps,verified_event_rate_mps,effective_bandwidth_gbps,confidence_abs_error_max,confidence_abs_error_mean,discrete_semantic_hash,supported,compatible,verified,oracle_supported,oracle_compatible,oracle_verified,validated_outputs,oracle_exact_outputs,boundary_divergent_outputs,completeness_validation,overflow_validation,counter_validation,sample_validation\n"<<std::fixed<<std::setprecision(6);
    for(const auto&r:rows)f<<r.profile<<','<<r.mode<<','<<(r.compact?1:0)<<','<<r.counter_mode<<','<<r.candidates<<','<<r.input_record_bytes<<','<<r.cold_lineage_bytes<<','<<r.output_record_bytes<<','<<r.total_buffer_bytes<<','<<r.allocated_output_bytes<<','<<r.logical_output_bytes<<','<<r.output_capacity_events<<','<<r.output_events<<','<<r.overflow_events<<','<<r.auxiliary_lut_bytes<<','<<r.setup_ms<<','<<r.upload_ms<<','<<r.readback_ms<<','<<r.host_p50_ms<<','<<r.host_p95_ms<<','<<r.host_p99_ms<<','<<r.device_p50_ms<<','<<r.device_p95_ms<<','<<r.device_p99_ms<<','<<r.candidate_rate_mps<<','<<r.verified_event_rate_mps<<','<<r.effective_bandwidth_gbps<<','<<r.confidence_abs_error_max<<','<<r.confidence_abs_error_mean<<','<<r.discrete_semantic_hash<<','<<r.counts.supported<<','<<r.counts.compatible<<','<<r.counts.verified<<','<<r.oracle_counts.supported<<','<<r.oracle_counts.compatible<<','<<r.oracle_counts.verified<<','<<r.validated_outputs<<','<<r.oracle_exact_outputs<<','<<r.boundary_divergent_outputs<<','<<(r.completeness_ok?1:0)<<','<<(r.overflow_ok?1:0)<<','<<(r.counters_ok?1:0)<<','<<(r.sample_ok?1:0)<<'\n';
}

} // namespace

int main(int argc,char**argv){try{const Args args=parse_args(argc,argv);fs::create_directories(args.out_dir/"pipeline_cache");VulkanContext ctx;const auto&props=ctx.properties();std::cout<<"Vulkan device: "<<props.deviceName<<" | API "<<api_major(props.apiVersion)<<'.'<<api_minor(props.apiVersion)<<'.'<<api_patch(props.apiVersion)<<" | timestamp "<<props.limits.timestampPeriod<<" ns\n";
    VkDescriptorSetLayoutBinding bindings[5]{};for(std::uint32_t i=0;i<3;++i){bindings[i].binding=i;bindings[i].descriptorType=VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;bindings[i].descriptorCount=1;bindings[i].stageFlags=VK_SHADER_STAGE_COMPUTE_BIT;}bindings[3].binding=3;bindings[3].descriptorType=VK_DESCRIPTOR_TYPE_UNIFORM_TEXEL_BUFFER;bindings[3].descriptorCount=1;bindings[3].stageFlags=VK_SHADER_STAGE_COMPUTE_BIT;bindings[4].binding=4;bindings[4].descriptorType=VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;bindings[4].descriptorCount=1;bindings[4].stageFlags=VK_SHADER_STAGE_COMPUTE_BIT;VkDescriptorSetLayoutCreateInfo dci{};dci.sType=VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO;dci.bindingCount=5;dci.pBindings=bindings;VkDescriptorSetLayout dsl=VK_NULL_HANDLE;check(vkCreateDescriptorSetLayout(ctx.device(),&dci,nullptr,&dsl),"vkCreateDescriptorSetLayout");VkPipelineLayoutCreateInfo plci{};plci.sType=VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO;plci.setLayoutCount=1;plci.pSetLayouts=&dsl;VkPipelineLayout layout=VK_NULL_HANDLE;check(vkCreatePipelineLayout(ctx.device(),&plci,nullptr,&layout),"vkCreatePipelineLayout");
    struct Job{std::string profile,mode,file;bool commit;int lut_kind;bool compact,full_counters;};std::vector<Job>jobs;
    if(args.hot_log_lut_only)jobs={{"G32_E16","evaluate","ugts_g32_evaluate.spv",false,0,false,false},{"G32_E16","evaluate_commit","ugts_g32_evaluate_commit.spv",true,0,false,true},{"G32_E16_SUBGROUP_COMPACT","append","ugts_g32_compact_subgroup_append.spv",true,0,true,false},{"G32_E16_SUBGROUP_COMPACT","append_counts","ugts_g32_compact_subgroup_append_counts.spv",true,0,true,true},{"G24_E16_LOGTHRESH_DIRECT_SUBGROUP_COMPACT","append","ugts_g24_logthreshold_direct_subgroup_compact_append.spv",true,0,true,false},{"G24_E16_LOGTHRESH_DIRECT_SUBGROUP_COMPACT","append_counts","ugts_g24_logthreshold_direct_subgroup_compact_append_counts.spv",true,0,true,true},{"G24_E16_LOGTHRESH_SUBGROUP_COMPACT","append","ugts_g24_logthreshold_subgroup_compact_append.spv",true,3,true,false},{"G24_E16_LOGTHRESH_SUBGROUP_COMPACT","append_counts","ugts_g24_logthreshold_subgroup_compact_append_counts.spv",true,3,true,true}};
    else if(args.cold_lineage_only)jobs={{"G32_E16","evaluate","ugts_g32_evaluate.spv",false,0,false,false},{"G32_E16","evaluate_commit","ugts_g32_evaluate_commit.spv",true,0,false,true},{"G24_E16_LOGTHRESH_DIRECT_SUBGROUP_COMPACT","append","ugts_g24_logthreshold_direct_subgroup_compact_append.spv",true,0,true,false},{"G24_E16_LOGTHRESH_DIRECT_SUBGROUP_COMPACT","append_counts","ugts_g24_logthreshold_direct_subgroup_compact_append_counts.spv",true,0,true,true},{"G20_E16_LOGTHRESH_DIRECT_COLD_LINEAGE_SUBGROUP_COMPACT","append","ugts_g20_cold_lineage_subgroup_compact_append.spv",true,0,true,false},{"G20_E16_LOGTHRESH_DIRECT_COLD_LINEAGE_SUBGROUP_COMPACT","append_counts","ugts_g20_cold_lineage_subgroup_compact_append_counts.spv",true,0,true,true}};
    else if(args.prethreshold_only)jobs={{"G32_E16","evaluate","ugts_g32_evaluate.spv",false,0,false,false},{"G32_E16","evaluate_commit","ugts_g32_evaluate_commit.spv",true,0,false,true},{"G32_E16_SUBGROUP_COMPACT","append","ugts_g32_compact_subgroup_append.spv",true,0,true,false},{"G32_E16_SUBGROUP_COMPACT","append_counts","ugts_g32_compact_subgroup_append_counts.spv",true,0,true,true},{"G32_E16_PRETHRESHOLD_SUBGROUP_COMPACT","append","ugts_g32_prethreshold_subgroup_compact_append.spv",true,0,true,false},{"G32_E16_PRETHRESHOLD_SUBGROUP_COMPACT","append_counts","ugts_g32_prethreshold_subgroup_compact_append_counts.spv",true,0,true,true}};
    else if(args.compact_only)jobs={{"G32_E16","evaluate","ugts_g32_evaluate.spv",false,0,false,false},{"G32_E16","evaluate_commit","ugts_g32_evaluate_commit.spv",true,0,false,true},{"G32_E16_COMPACT","append","ugts_g32_compact_append.spv",true,0,true,false},{"G32_E16_COMPACT","append_counts","ugts_g32_compact_append_counts.spv",true,0,true,true},{"G32_E16_SUBGROUP_COMPACT","append","ugts_g32_compact_subgroup_append.spv",true,0,true,false},{"G32_E16_SUBGROUP_COMPACT","append_counts","ugts_g32_compact_subgroup_append_counts.spv",true,0,true,true}};
    else if(args.lut_only)jobs={{"G32_E16","evaluate","ugts_g32_evaluate.spv",false,0,false,false},{"G32_E16_LUT","evaluate","ugts_g32_lut_evaluate.spv",false,1,false,false},{"G32_E16_LUT_PAIR","evaluate","ugts_g32_lut_pair_evaluate.spv",false,2,false,false},{"G32_E16","evaluate_commit","ugts_g32_evaluate_commit.spv",true,0,false,true},{"G32_E16_LUT","evaluate_commit","ugts_g32_lut_evaluate_commit.spv",true,1,false,true},{"G32_E16_LUT_PAIR","evaluate_commit","ugts_g32_lut_pair_evaluate_commit.spv",true,2,false,true}};
    else jobs={{"G64_E32","evaluate","ugts_g64_evaluate.spv",false,0,false,false},{"G64_E32","evaluate_commit","ugts_g64_evaluate_commit.spv",true,0,false,true},{"G32_E16","evaluate","ugts_g32_evaluate.spv",false,0,false,false},{"G32_E16_LUT","evaluate","ugts_g32_lut_evaluate.spv",false,1,false,false},{"G32_E16_LUT_PAIR","evaluate","ugts_g32_lut_pair_evaluate.spv",false,2,false,false},{"G32_E16","evaluate_commit","ugts_g32_evaluate_commit.spv",true,0,false,true},{"G32_E16_LUT","evaluate_commit","ugts_g32_lut_evaluate_commit.spv",true,1,false,true},{"G32_E16_LUT_PAIR","evaluate_commit","ugts_g32_lut_pair_evaluate_commit.spv",true,2,false,true}};std::vector<ProgramRecord>programs;std::vector<BenchRow>rows;
    if((args.compact_only||args.prethreshold_only||args.hot_log_lut_only||args.cold_lineage_only)&&args.compact_reverse)std::reverse(jobs.begin(),jobs.end());
    if(args.lut_only&&args.lut_reverse)std::reverse(jobs.begin(),jobs.end());
    for(const auto&j:jobs){ProgramRecord pr{};pr.name=j.profile+"_"+j.mode;pr.spv_path=args.spirv_dir/j.file;auto spv=read_spirv(pr.spv_path);std::cout<<"Creating pipeline "<<pr.name<<"...\n";pr.program=create_pipeline(ctx,layout,spv,args.out_dir/"pipeline_cache"/cache_filename(pr.name));for(auto n:args.sizes){BenchRow r;if(j.profile=="G64_E32")r=run_one<State64,Event32>(ctx,dsl,layout,pr.program.pipeline,j.profile,j.mode,j.commit,j.lut_kind,j.compact,j.full_counters,n,args.warmup,args.warmup_ms,args.iterations,args.compact_capacity_ratio,make64,[](const State64&s,std::size_t){Fields f{};f.px=s.position_time[0];f.py=s.position_time[1];f.pz=s.position_time[2];f.time=s.position_time[3];f.ax=s.axis_radius[0];f.ay=s.axis_radius[1];f.az=s.axis_radius[2];f.radius=s.axis_radius[3];f.cone_cos=s.phase_guard[0];f.phase=s.phase_guard[1];f.guard_epsilon=s.phase_guard[2];f.confidence_floor=s.phase_guard[3];f.sheet=s.meta[0];f.orientation=s.meta[1];f.compatibility_mask=s.meta[2];f.lineage_seed=s.meta[3];return f;});else if(j.profile=="G20_E16_LOGTHRESH_DIRECT_COLD_LINEAGE_SUBGROUP_COMPACT")r=run_one<State20,Event16>(ctx,dsl,layout,pr.program.pipeline,j.profile,j.mode,j.commit,j.lut_kind,j.compact,j.full_counters,n,args.warmup,args.warmup_ms,args.iterations,args.compact_capacity_ratio,make20_cold_lineage,decode20_cold_lineage);else if(j.profile=="G24_E16_LOGTHRESH_SUBGROUP_COMPACT"||j.profile=="G24_E16_LOGTHRESH_DIRECT_SUBGROUP_COMPACT")r=run_one<State24,Event16>(ctx,dsl,layout,pr.program.pipeline,j.profile,j.mode,j.commit,j.lut_kind,j.compact,j.full_counters,n,args.warmup,args.warmup_ms,args.iterations,args.compact_capacity_ratio,make24_logthreshold,decode24_logthreshold);else if(j.profile=="G32_E16_PRETHRESHOLD_SUBGROUP_COMPACT")r=run_one<State32,Event16>(ctx,dsl,layout,pr.program.pipeline,j.profile,j.mode,j.commit,j.lut_kind,j.compact,j.full_counters,n,args.warmup,args.warmup_ms,args.iterations,args.compact_capacity_ratio,make32_prethreshold,decode32_prethreshold);else r=run_one<State32,Event16>(ctx,dsl,layout,pr.program.pipeline,j.profile,j.mode,j.commit,j.lut_kind,j.compact,j.full_counters,n,args.warmup,args.warmup_ms,args.iterations,args.compact_capacity_ratio,make32,decode32);std::cout<<"  N="<<n<<" device-p50="<<std::fixed<<std::setprecision(3)<<r.device_p50_ms<<" ms host-p50="<<r.host_p50_ms<<" ms CER="<<std::setprecision(2)<<r.candidate_rate_mps<<" M/s SET="<<r.verified_event_rate_mps<<" M/s outputs="<<r.output_events<<"/"<<r.output_capacity_events<<" overflow="<<r.overflow_events<<" provisional="<<(r.sample_ok&&r.counters_ok?"yes":"no")<<"\n";rows.push_back(r);}programs.push_back(std::move(pr));}
    for(auto&r:rows)if(r.compact){const auto dense=std::find_if(rows.begin(),rows.end(),[&](const BenchRow&x){return !x.compact&&x.profile=="G32_E16"&&x.mode=="evaluate"&&x.candidates==r.candidates;});const std::size_t expected_overflow=r.counts.verified>r.output_capacity_events?std::size_t(r.counts.verified)-r.output_capacity_events:0;r.overflow_ok=dense!=rows.end()&&r.counts.verified==dense->counts.verified&&r.overflow_events==expected_overflow;if(!r.overflow_ok)r.counters_ok=false;if(r.overflow_events&&!args.allow_compact_overflow){std::cerr<<"compact capacity overflow "<<r.profile<<' '<<r.mode<<" N="<<r.candidates<<" demand="<<r.counts.verified<<" capacity="<<r.output_capacity_events<<'\n';r.sample_ok=false;}}
    write_json(ctx,args,programs,rows,args.out_dir/"vulkan_benchmark_results.json");write_csv(rows,args.out_dir/"vulkan_benchmark_results.csv");bool valid=std::all_of(rows.begin(),rows.end(),[&](const BenchRow&r){return r.sample_ok&&r.counters_ok&&r.overflow_ok&&(r.completeness_ok||args.allow_compact_overflow);});for(auto&x:programs)destroy_program(ctx,x.program);vkDestroyPipelineLayout(ctx.device(),layout,nullptr);vkDestroyDescriptorSetLayout(ctx.device(),dsl,nullptr);if(!valid){std::cerr<<"validation failed\n";return 2;}std::cout<<"Wrote native Vulkan benchmark results.\n";return 0;}catch(const std::exception&e){std::cerr<<"UGTS Vulkan benchmark error: "<<e.what()<<"\n";return 1;}}
