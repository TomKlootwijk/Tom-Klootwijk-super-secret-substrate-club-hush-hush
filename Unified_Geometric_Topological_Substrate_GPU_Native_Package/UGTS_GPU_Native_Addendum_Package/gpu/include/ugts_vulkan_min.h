#pragma once
// Minimal Vulkan 1.0 declarations used by the UGTS compute benchmark.
// This is intentionally not a substitute for the official Khronos headers.
// Production builds should include <vulkan/vulkan.h> instead.

#include <cstddef>
#include <cstdint>

#if defined(_WIN32)
#  define VKAPI_ATTR
#  define VKAPI_CALL __stdcall
#  define VKAPI_PTR VKAPI_CALL
#else
#  define VKAPI_ATTR
#  define VKAPI_CALL
#  define VKAPI_PTR
#endif

extern "C" {

typedef std::uint32_t VkFlags;
typedef std::uint32_t VkBool32;
typedef std::uint64_t VkDeviceSize;
typedef std::uint32_t VkSampleMask;

typedef struct VkInstance_T* VkInstance;
typedef struct VkPhysicalDevice_T* VkPhysicalDevice;
typedef struct VkDevice_T* VkDevice;
typedef struct VkQueue_T* VkQueue;
typedef struct VkCommandBuffer_T* VkCommandBuffer;
typedef struct VkDeviceMemory_T* VkDeviceMemory;
typedef struct VkBuffer_T* VkBuffer;
typedef struct VkShaderModule_T* VkShaderModule;
typedef struct VkPipelineCache_T* VkPipelineCache;
typedef struct VkPipeline_T* VkPipeline;
typedef struct VkPipelineLayout_T* VkPipelineLayout;
typedef struct VkDescriptorSetLayout_T* VkDescriptorSetLayout;
typedef struct VkDescriptorSet_T* VkDescriptorSet;
typedef struct VkDescriptorPool_T* VkDescriptorPool;
typedef struct VkCommandPool_T* VkCommandPool;
typedef struct VkFence_T* VkFence;
typedef struct VkQueryPool_T* VkQueryPool;
typedef struct VkSemaphore_T* VkSemaphore;
typedef struct VkSampler_T* VkSampler;
typedef struct VkBufferView_T* VkBufferView;

#define VK_NULL_HANDLE nullptr
#define VK_WHOLE_SIZE (~VkDeviceSize(0))
#define VK_QUEUE_FAMILY_IGNORED (~std::uint32_t(0))
#define VK_TRUE 1u
#define VK_FALSE 0u
#define VK_MAX_PHYSICAL_DEVICE_NAME_SIZE 256u
#define VK_MAX_EXTENSION_NAME_SIZE 256u
#define VK_MAX_DESCRIPTION_SIZE 256u
#define VK_UUID_SIZE 16u
#define VK_MAX_MEMORY_TYPES 32u
#define VK_MAX_MEMORY_HEAPS 16u
#define VK_MAKE_API_VERSION(variant, major, minor, patch) \
    ((((std::uint32_t)(variant)) << 29u) | (((std::uint32_t)(major)) << 22u) | \
     (((std::uint32_t)(minor)) << 12u) | ((std::uint32_t)(patch)))
#define VK_API_VERSION_1_0 VK_MAKE_API_VERSION(0,1,0,0)
#define VK_API_VERSION_1_1 VK_MAKE_API_VERSION(0,1,1,0)


typedef enum VkResult {
    VK_SUCCESS = 0,
    VK_NOT_READY = 1,
    VK_TIMEOUT = 2,
    VK_EVENT_SET = 3,
    VK_EVENT_RESET = 4,
    VK_INCOMPLETE = 5,
    VK_ERROR_OUT_OF_HOST_MEMORY = -1,
    VK_ERROR_OUT_OF_DEVICE_MEMORY = -2,
    VK_ERROR_INITIALIZATION_FAILED = -3,
    VK_ERROR_DEVICE_LOST = -4,
    VK_ERROR_MEMORY_MAP_FAILED = -5,
    VK_ERROR_LAYER_NOT_PRESENT = -6,
    VK_ERROR_EXTENSION_NOT_PRESENT = -7,
    VK_ERROR_FEATURE_NOT_PRESENT = -8,
    VK_ERROR_INCOMPATIBLE_DRIVER = -9,
    VK_ERROR_TOO_MANY_OBJECTS = -10,
    VK_ERROR_FORMAT_NOT_SUPPORTED = -11,
    VK_ERROR_FRAGMENTED_POOL = -12,
    VK_ERROR_UNKNOWN = -13
} VkResult;

typedef enum VkStructureType {
    VK_STRUCTURE_TYPE_APPLICATION_INFO = 0,
    VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO = 1,
    VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO = 2,
    VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO = 3,
    VK_STRUCTURE_TYPE_SUBMIT_INFO = 4,
    VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO = 5,
    VK_STRUCTURE_TYPE_MAPPED_MEMORY_RANGE = 6,
    VK_STRUCTURE_TYPE_FENCE_CREATE_INFO = 8,
    VK_STRUCTURE_TYPE_QUERY_POOL_CREATE_INFO = 11,
    VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO = 12,
    VK_STRUCTURE_TYPE_BUFFER_VIEW_CREATE_INFO = 13,
    VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO = 16,
    VK_STRUCTURE_TYPE_PIPELINE_CACHE_CREATE_INFO = 17,
    VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO = 18,
    VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO = 29,
    VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO = 30,
    VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO = 32,
    VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO = 33,
    VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO = 34,
    VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET = 35,
    VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO = 39,
    VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO = 40,
    VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO = 42,
    VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER = 44,
    VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2 = 1000059000,
    VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SHADER_CLOCK_FEATURES_KHR = 1000181000,
    VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PIPELINE_EXECUTABLE_PROPERTIES_FEATURES_KHR = 1000269000,
    VK_STRUCTURE_TYPE_PIPELINE_INFO_KHR = 1000269001,
    VK_STRUCTURE_TYPE_PIPELINE_EXECUTABLE_PROPERTIES_KHR = 1000269002,
    VK_STRUCTURE_TYPE_PIPELINE_EXECUTABLE_INFO_KHR = 1000269003,
    VK_STRUCTURE_TYPE_PIPELINE_EXECUTABLE_STATISTIC_KHR = 1000269004,
    VK_STRUCTURE_TYPE_PIPELINE_EXECUTABLE_INTERNAL_REPRESENTATION_KHR = 1000269005
} VkStructureType;

typedef enum VkPhysicalDeviceType {
    VK_PHYSICAL_DEVICE_TYPE_OTHER = 0,
    VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU = 1,
    VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU = 2,
    VK_PHYSICAL_DEVICE_TYPE_VIRTUAL_GPU = 3,
    VK_PHYSICAL_DEVICE_TYPE_CPU = 4
} VkPhysicalDeviceType;

typedef enum VkSharingMode {
    VK_SHARING_MODE_EXCLUSIVE = 0,
    VK_SHARING_MODE_CONCURRENT = 1
} VkSharingMode;

typedef enum VkDescriptorType {
    VK_DESCRIPTOR_TYPE_SAMPLER = 0,
    VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER = 1,
    VK_DESCRIPTOR_TYPE_SAMPLED_IMAGE = 2,
    VK_DESCRIPTOR_TYPE_STORAGE_IMAGE = 3,
    VK_DESCRIPTOR_TYPE_UNIFORM_TEXEL_BUFFER = 4,
    VK_DESCRIPTOR_TYPE_STORAGE_TEXEL_BUFFER = 5,
    VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER = 6,
    VK_DESCRIPTOR_TYPE_STORAGE_BUFFER = 7
} VkDescriptorType;

typedef enum VkFormat {
    VK_FORMAT_R32_UINT = 98
} VkFormat;

typedef enum VkPipelineBindPoint {
    VK_PIPELINE_BIND_POINT_GRAPHICS = 0,
    VK_PIPELINE_BIND_POINT_COMPUTE = 1
} VkPipelineBindPoint;

typedef enum VkCommandBufferLevel {
    VK_COMMAND_BUFFER_LEVEL_PRIMARY = 0,
    VK_COMMAND_BUFFER_LEVEL_SECONDARY = 1
} VkCommandBufferLevel;

typedef enum VkQueryType {
    VK_QUERY_TYPE_OCCLUSION = 0,
    VK_QUERY_TYPE_PIPELINE_STATISTICS = 1,
    VK_QUERY_TYPE_TIMESTAMP = 2
} VkQueryType;

typedef VkFlags VkInstanceCreateFlags;
typedef VkFlags VkDeviceQueueCreateFlags;
typedef VkFlags VkDeviceCreateFlags;
typedef VkFlags VkQueueFlags;
typedef VkFlags VkMemoryPropertyFlags;
typedef VkFlags VkMemoryHeapFlags;
typedef VkFlags VkBufferCreateFlags;
typedef VkFlags VkBufferViewCreateFlags;
typedef VkFlags VkBufferUsageFlags;
typedef VkFlags VkDescriptorSetLayoutCreateFlags;
typedef VkFlags VkShaderStageFlags;
typedef VkFlags VkPipelineLayoutCreateFlags;
typedef VkFlags VkShaderModuleCreateFlags;
typedef VkFlags VkPipelineCacheCreateFlags;
typedef VkFlags VkPipelineShaderStageCreateFlags;
typedef VkFlags VkPipelineCreateFlags;
typedef VkFlags VkDescriptorPoolCreateFlags;
typedef VkFlags VkCommandPoolCreateFlags;
typedef VkFlags VkCommandBufferUsageFlags;
typedef VkFlags VkFenceCreateFlags;
typedef VkFlags VkQueryPoolCreateFlags;
typedef VkFlags VkAccessFlags;
typedef VkFlags VkPipelineStageFlags;
typedef VkFlags VkDependencyFlags;
typedef VkFlags VkQueryResultFlags;
typedef VkFlags VkSampleCountFlags;

enum : VkQueueFlags {
    VK_QUEUE_GRAPHICS_BIT = 0x00000001,
    VK_QUEUE_COMPUTE_BIT = 0x00000002,
    VK_QUEUE_TRANSFER_BIT = 0x00000004
};
enum : VkMemoryPropertyFlags {
    VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT = 0x00000001,
    VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT = 0x00000002,
    VK_MEMORY_PROPERTY_HOST_COHERENT_BIT = 0x00000004,
    VK_MEMORY_PROPERTY_HOST_CACHED_BIT = 0x00000008
};
enum : VkBufferUsageFlags {
    VK_BUFFER_USAGE_TRANSFER_SRC_BIT = 0x00000001,
    VK_BUFFER_USAGE_TRANSFER_DST_BIT = 0x00000002,
    VK_BUFFER_USAGE_UNIFORM_TEXEL_BUFFER_BIT = 0x00000004,
    VK_BUFFER_USAGE_STORAGE_BUFFER_BIT = 0x00000020
};
enum : VkShaderStageFlags {
    VK_SHADER_STAGE_COMPUTE_BIT = 0x00000020
};
enum : VkCommandPoolCreateFlags {
    VK_COMMAND_POOL_CREATE_TRANSIENT_BIT = 0x00000001,
    VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT = 0x00000002
};
enum : VkCommandBufferUsageFlags {
    VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT = 0x00000001,
    VK_COMMAND_BUFFER_USAGE_SIMULTANEOUS_USE_BIT = 0x00000004
};
enum : VkAccessFlags {
    VK_ACCESS_TRANSFER_READ_BIT = 0x00000800,
    VK_ACCESS_TRANSFER_WRITE_BIT = 0x00001000,
    VK_ACCESS_SHADER_READ_BIT = 0x00000020,
    VK_ACCESS_SHADER_WRITE_BIT = 0x00000040,
    VK_ACCESS_HOST_READ_BIT = 0x00002000,
    VK_ACCESS_HOST_WRITE_BIT = 0x00004000
};
enum : VkPipelineStageFlags {
    VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT = 0x00000001,
    VK_PIPELINE_STAGE_TRANSFER_BIT = 0x00001000,
    VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT = 0x00000800,
    VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT = 0x00002000,
    VK_PIPELINE_STAGE_HOST_BIT = 0x00004000
};
enum : VkQueryResultFlags {
    VK_QUERY_RESULT_64_BIT = 0x00000001,
    VK_QUERY_RESULT_WAIT_BIT = 0x00000002
};
enum : VkPipelineCreateFlags {
    VK_PIPELINE_CREATE_CAPTURE_STATISTICS_BIT_KHR = 0x00000040,
    VK_PIPELINE_CREATE_CAPTURE_INTERNAL_REPRESENTATIONS_BIT_KHR = 0x00000080
};

typedef enum VkPipelineExecutableStatisticFormatKHR {
    VK_PIPELINE_EXECUTABLE_STATISTIC_FORMAT_BOOL32_KHR = 0,
    VK_PIPELINE_EXECUTABLE_STATISTIC_FORMAT_INT64_KHR = 1,
    VK_PIPELINE_EXECUTABLE_STATISTIC_FORMAT_UINT64_KHR = 2,
    VK_PIPELINE_EXECUTABLE_STATISTIC_FORMAT_FLOAT64_KHR = 3
} VkPipelineExecutableStatisticFormatKHR;

typedef struct VkExtent3D {
    std::uint32_t width, height, depth;
} VkExtent3D;

typedef struct VkApplicationInfo {
    VkStructureType sType;
    const void* pNext;
    const char* pApplicationName;
    std::uint32_t applicationVersion;
    const char* pEngineName;
    std::uint32_t engineVersion;
    std::uint32_t apiVersion;
} VkApplicationInfo;

typedef struct VkInstanceCreateInfo {
    VkStructureType sType;
    const void* pNext;
    VkInstanceCreateFlags flags;
    const VkApplicationInfo* pApplicationInfo;
    std::uint32_t enabledLayerCount;
    const char* const* ppEnabledLayerNames;
    std::uint32_t enabledExtensionCount;
    const char* const* ppEnabledExtensionNames;
} VkInstanceCreateInfo;

typedef struct VkPhysicalDeviceLimitsPrefix {
    std::uint32_t maxImageDimension1D;
    std::uint32_t maxImageDimension2D;
    std::uint32_t maxImageDimension3D;
    std::uint32_t maxImageDimensionCube;
    std::uint32_t maxImageArrayLayers;
    std::uint32_t maxTexelBufferElements;
    std::uint32_t maxUniformBufferRange;
    std::uint32_t maxStorageBufferRange;
    std::uint32_t maxPushConstantsSize;
    std::uint32_t maxMemoryAllocationCount;
    std::uint32_t maxSamplerAllocationCount;
    VkDeviceSize bufferImageGranularity;
    VkDeviceSize sparseAddressSpaceSize;
    std::uint32_t maxBoundDescriptorSets;
    std::uint32_t maxPerStageDescriptorSamplers;
    std::uint32_t maxPerStageDescriptorUniformBuffers;
    std::uint32_t maxPerStageDescriptorStorageBuffers;
    std::uint32_t maxPerStageDescriptorSampledImages;
    std::uint32_t maxPerStageDescriptorStorageImages;
    std::uint32_t maxPerStageDescriptorInputAttachments;
    std::uint32_t maxPerStageResources;
    std::uint32_t maxDescriptorSetSamplers;
    std::uint32_t maxDescriptorSetUniformBuffers;
    std::uint32_t maxDescriptorSetUniformBuffersDynamic;
    std::uint32_t maxDescriptorSetStorageBuffers;
    std::uint32_t maxDescriptorSetStorageBuffersDynamic;
    std::uint32_t maxDescriptorSetSampledImages;
    std::uint32_t maxDescriptorSetStorageImages;
    std::uint32_t maxDescriptorSetInputAttachments;
    std::uint32_t maxVertexInputAttributes;
    std::uint32_t maxVertexInputBindings;
    std::uint32_t maxVertexInputAttributeOffset;
    std::uint32_t maxVertexInputBindingStride;
    std::uint32_t maxVertexOutputComponents;
    std::uint32_t maxTessellationGenerationLevel;
    std::uint32_t maxTessellationPatchSize;
    std::uint32_t maxTessellationControlPerVertexInputComponents;
    std::uint32_t maxTessellationControlPerVertexOutputComponents;
    std::uint32_t maxTessellationControlPerPatchOutputComponents;
    std::uint32_t maxTessellationControlTotalOutputComponents;
    std::uint32_t maxTessellationEvaluationInputComponents;
    std::uint32_t maxTessellationEvaluationOutputComponents;
    std::uint32_t maxGeometryShaderInvocations;
    std::uint32_t maxGeometryInputComponents;
    std::uint32_t maxGeometryOutputComponents;
    std::uint32_t maxGeometryOutputVertices;
    std::uint32_t maxGeometryTotalOutputComponents;
    std::uint32_t maxFragmentInputComponents;
    std::uint32_t maxFragmentOutputAttachments;
    std::uint32_t maxFragmentDualSrcAttachments;
    std::uint32_t maxFragmentCombinedOutputResources;
    std::uint32_t maxComputeSharedMemorySize;
    std::uint32_t maxComputeWorkGroupCount[3];
    std::uint32_t maxComputeWorkGroupInvocations;
    std::uint32_t maxComputeWorkGroupSize[3];
    std::uint32_t subPixelPrecisionBits;
    std::uint32_t subTexelPrecisionBits;
    std::uint32_t mipmapPrecisionBits;
    std::uint32_t maxDrawIndexedIndexValue;
    std::uint32_t maxDrawIndirectCount;
    float maxSamplerLodBias;
    float maxSamplerAnisotropy;
    std::uint32_t maxViewports;
    std::uint32_t maxViewportDimensions[2];
    float viewportBoundsRange[2];
    std::uint32_t viewportSubPixelBits;
    std::size_t minMemoryMapAlignment;
    VkDeviceSize minTexelBufferOffsetAlignment;
    VkDeviceSize minUniformBufferOffsetAlignment;
    VkDeviceSize minStorageBufferOffsetAlignment;
    std::int32_t minTexelOffset;
    std::uint32_t maxTexelOffset;
    std::int32_t minTexelGatherOffset;
    std::uint32_t maxTexelGatherOffset;
    float minInterpolationOffset;
    float maxInterpolationOffset;
    std::uint32_t subPixelInterpolationOffsetBits;
    std::uint32_t maxFramebufferWidth;
    std::uint32_t maxFramebufferHeight;
    std::uint32_t maxFramebufferLayers;
    VkSampleCountFlags framebufferColorSampleCounts;
    VkSampleCountFlags framebufferDepthSampleCounts;
    VkSampleCountFlags framebufferStencilSampleCounts;
    VkSampleCountFlags framebufferNoAttachmentsSampleCounts;
    std::uint32_t maxColorAttachments;
    VkSampleCountFlags sampledImageColorSampleCounts;
    VkSampleCountFlags sampledImageIntegerSampleCounts;
    VkSampleCountFlags sampledImageDepthSampleCounts;
    VkSampleCountFlags sampledImageStencilSampleCounts;
    VkSampleCountFlags storageImageSampleCounts;
    std::uint32_t maxSampleMaskWords;
    VkBool32 timestampComputeAndGraphics;
    float timestampPeriod;
    // Remaining standard VkPhysicalDeviceLimits fields plus sparse properties.
    alignas(8) std::uint8_t opaqueTail[1024];
} VkPhysicalDeviceLimitsPrefix;

typedef struct VkPhysicalDeviceProperties {
    std::uint32_t apiVersion;
    std::uint32_t driverVersion;
    std::uint32_t vendorID;
    std::uint32_t deviceID;
    VkPhysicalDeviceType deviceType;
    char deviceName[VK_MAX_PHYSICAL_DEVICE_NAME_SIZE];
    std::uint8_t pipelineCacheUUID[VK_UUID_SIZE];
    VkPhysicalDeviceLimitsPrefix limits;
} VkPhysicalDeviceProperties;

// Oversized opaque core feature storage keeps this minimal header ABI-safe for
// vkGetPhysicalDeviceFeatures2 while exposing only the extension feature used
// by the benchmark. The driver writes the standard VkPhysicalDeviceFeatures
// prefix; the extra words remain untouched.
typedef struct VkPhysicalDeviceFeatures2 {
    VkStructureType sType;
    void* pNext;
    VkBool32 opaqueFeatures[64];
} VkPhysicalDeviceFeatures2;

typedef struct VkPhysicalDevicePipelineExecutablePropertiesFeaturesKHR {
    VkStructureType sType;
    void* pNext;
    VkBool32 pipelineExecutableInfo;
} VkPhysicalDevicePipelineExecutablePropertiesFeaturesKHR;

typedef struct VkPhysicalDeviceShaderClockFeaturesKHR {
    VkStructureType sType;
    void* pNext;
    VkBool32 shaderSubgroupClock;
    VkBool32 shaderDeviceClock;
} VkPhysicalDeviceShaderClockFeaturesKHR;

typedef struct VkExtensionProperties {
    char extensionName[VK_MAX_EXTENSION_NAME_SIZE];
    std::uint32_t specVersion;
} VkExtensionProperties;

typedef struct VkQueueFamilyProperties {
    VkQueueFlags queueFlags;
    std::uint32_t queueCount;
    std::uint32_t timestampValidBits;
    VkExtent3D minImageTransferGranularity;
} VkQueueFamilyProperties;

typedef struct VkMemoryType {
    VkMemoryPropertyFlags propertyFlags;
    std::uint32_t heapIndex;
} VkMemoryType;

typedef struct VkMemoryHeap {
    VkDeviceSize size;
    VkMemoryHeapFlags flags;
} VkMemoryHeap;

typedef struct VkPhysicalDeviceMemoryProperties {
    std::uint32_t memoryTypeCount;
    VkMemoryType memoryTypes[VK_MAX_MEMORY_TYPES];
    std::uint32_t memoryHeapCount;
    VkMemoryHeap memoryHeaps[VK_MAX_MEMORY_HEAPS];
} VkPhysicalDeviceMemoryProperties;

typedef struct VkDeviceQueueCreateInfo {
    VkStructureType sType;
    const void* pNext;
    VkDeviceQueueCreateFlags flags;
    std::uint32_t queueFamilyIndex;
    std::uint32_t queueCount;
    const float* pQueuePriorities;
} VkDeviceQueueCreateInfo;

typedef struct VkDeviceCreateInfo {
    VkStructureType sType;
    const void* pNext;
    VkDeviceCreateFlags flags;
    std::uint32_t queueCreateInfoCount;
    const VkDeviceQueueCreateInfo* pQueueCreateInfos;
    std::uint32_t enabledLayerCount;
    const char* const* ppEnabledLayerNames;
    std::uint32_t enabledExtensionCount;
    const char* const* ppEnabledExtensionNames;
    const void* pEnabledFeatures;
} VkDeviceCreateInfo;

typedef struct VkBufferCreateInfo {
    VkStructureType sType;
    const void* pNext;
    VkBufferCreateFlags flags;
    VkDeviceSize size;
    VkBufferUsageFlags usage;
    VkSharingMode sharingMode;
    std::uint32_t queueFamilyIndexCount;
    const std::uint32_t* pQueueFamilyIndices;
} VkBufferCreateInfo;

typedef struct VkMemoryRequirements {
    VkDeviceSize size;
    VkDeviceSize alignment;
    std::uint32_t memoryTypeBits;
} VkMemoryRequirements;

typedef struct VkMemoryAllocateInfo {
    VkStructureType sType;
    const void* pNext;
    VkDeviceSize allocationSize;
    std::uint32_t memoryTypeIndex;
} VkMemoryAllocateInfo;

typedef struct VkDescriptorSetLayoutBinding {
    std::uint32_t binding;
    VkDescriptorType descriptorType;
    std::uint32_t descriptorCount;
    VkShaderStageFlags stageFlags;
    const VkSampler* pImmutableSamplers;
} VkDescriptorSetLayoutBinding;

typedef struct VkDescriptorSetLayoutCreateInfo {
    VkStructureType sType;
    const void* pNext;
    VkDescriptorSetLayoutCreateFlags flags;
    std::uint32_t bindingCount;
    const VkDescriptorSetLayoutBinding* pBindings;
} VkDescriptorSetLayoutCreateInfo;

typedef struct VkPipelineLayoutCreateInfo {
    VkStructureType sType;
    const void* pNext;
    VkPipelineLayoutCreateFlags flags;
    std::uint32_t setLayoutCount;
    const VkDescriptorSetLayout* pSetLayouts;
    std::uint32_t pushConstantRangeCount;
    const void* pPushConstantRanges;
} VkPipelineLayoutCreateInfo;

typedef struct VkShaderModuleCreateInfo {
    VkStructureType sType;
    const void* pNext;
    VkShaderModuleCreateFlags flags;
    std::size_t codeSize;
    const std::uint32_t* pCode;
} VkShaderModuleCreateInfo;

typedef struct VkPipelineCacheCreateInfo {
    VkStructureType sType;
    const void* pNext;
    VkPipelineCacheCreateFlags flags;
    std::size_t initialDataSize;
    const void* pInitialData;
} VkPipelineCacheCreateInfo;

typedef struct VkSpecializationInfo VkSpecializationInfo;
typedef struct VkPipelineShaderStageCreateInfo {
    VkStructureType sType;
    const void* pNext;
    VkPipelineShaderStageCreateFlags flags;
    VkShaderStageFlags stage;
    VkShaderModule module;
    const char* pName;
    const VkSpecializationInfo* pSpecializationInfo;
} VkPipelineShaderStageCreateInfo;

typedef struct VkComputePipelineCreateInfo {
    VkStructureType sType;
    const void* pNext;
    VkPipelineCreateFlags flags;
    VkPipelineShaderStageCreateInfo stage;
    VkPipelineLayout layout;
    VkPipeline basePipelineHandle;
    std::int32_t basePipelineIndex;
} VkComputePipelineCreateInfo;

typedef struct VkPipelineInfoKHR {
    VkStructureType sType;
    const void* pNext;
    VkPipeline pipeline;
} VkPipelineInfoKHR;

typedef struct VkPipelineExecutablePropertiesKHR {
    VkStructureType sType;
    void* pNext;
    VkShaderStageFlags stages;
    char name[VK_MAX_DESCRIPTION_SIZE];
    char description[VK_MAX_DESCRIPTION_SIZE];
    std::uint32_t subgroupSize;
} VkPipelineExecutablePropertiesKHR;

typedef struct VkPipelineExecutableInfoKHR {
    VkStructureType sType;
    const void* pNext;
    VkPipeline pipeline;
    std::uint32_t executableIndex;
} VkPipelineExecutableInfoKHR;

typedef union VkPipelineExecutableStatisticValueKHR {
    VkBool32 b32;
    std::int64_t i64;
    std::uint64_t u64;
    double f64;
} VkPipelineExecutableStatisticValueKHR;

typedef struct VkPipelineExecutableStatisticKHR {
    VkStructureType sType;
    void* pNext;
    char name[VK_MAX_DESCRIPTION_SIZE];
    char description[VK_MAX_DESCRIPTION_SIZE];
    VkPipelineExecutableStatisticFormatKHR format;
    VkPipelineExecutableStatisticValueKHR value;
} VkPipelineExecutableStatisticKHR;

typedef struct VkPipelineExecutableInternalRepresentationKHR {
    VkStructureType sType;
    void* pNext;
    char name[VK_MAX_DESCRIPTION_SIZE];
    char description[VK_MAX_DESCRIPTION_SIZE];
    VkBool32 isText;
    std::size_t dataSize;
    void* pData;
} VkPipelineExecutableInternalRepresentationKHR;

typedef struct VkDescriptorPoolSize {
    VkDescriptorType type;
    std::uint32_t descriptorCount;
} VkDescriptorPoolSize;

typedef struct VkDescriptorPoolCreateInfo {
    VkStructureType sType;
    const void* pNext;
    VkDescriptorPoolCreateFlags flags;
    std::uint32_t maxSets;
    std::uint32_t poolSizeCount;
    const VkDescriptorPoolSize* pPoolSizes;
} VkDescriptorPoolCreateInfo;

typedef struct VkDescriptorSetAllocateInfo {
    VkStructureType sType;
    const void* pNext;
    VkDescriptorPool descriptorPool;
    std::uint32_t descriptorSetCount;
    const VkDescriptorSetLayout* pSetLayouts;
} VkDescriptorSetAllocateInfo;

typedef struct VkDescriptorBufferInfo {
    VkBuffer buffer;
    VkDeviceSize offset;
    VkDeviceSize range;
} VkDescriptorBufferInfo;

typedef struct VkWriteDescriptorSet {
    VkStructureType sType;
    const void* pNext;
    VkDescriptorSet dstSet;
    std::uint32_t dstBinding;
    std::uint32_t dstArrayElement;
    std::uint32_t descriptorCount;
    VkDescriptorType descriptorType;
    const void* pImageInfo;
    const VkDescriptorBufferInfo* pBufferInfo;
    const VkBufferView* pTexelBufferView;
} VkWriteDescriptorSet;

typedef struct VkCommandPoolCreateInfo {
    VkStructureType sType;
    const void* pNext;
    VkCommandPoolCreateFlags flags;
    std::uint32_t queueFamilyIndex;
} VkCommandPoolCreateInfo;

typedef struct VkCommandBufferAllocateInfo {
    VkStructureType sType;
    const void* pNext;
    VkCommandPool commandPool;
    VkCommandBufferLevel level;
    std::uint32_t commandBufferCount;
} VkCommandBufferAllocateInfo;

typedef struct VkCommandBufferBeginInfo {
    VkStructureType sType;
    const void* pNext;
    VkCommandBufferUsageFlags flags;
    const void* pInheritanceInfo;
} VkCommandBufferBeginInfo;

typedef struct VkBufferMemoryBarrier {
    VkStructureType sType;
    const void* pNext;
    VkAccessFlags srcAccessMask;
    VkAccessFlags dstAccessMask;
    std::uint32_t srcQueueFamilyIndex;
    std::uint32_t dstQueueFamilyIndex;
    VkBuffer buffer;
    VkDeviceSize offset;
    VkDeviceSize size;
} VkBufferMemoryBarrier;

typedef struct VkBufferViewCreateInfo {
    VkStructureType sType;
    const void* pNext;
    VkBufferViewCreateFlags flags;
    VkBuffer buffer;
    VkFormat format;
    VkDeviceSize offset;
    VkDeviceSize range;
} VkBufferViewCreateInfo;

typedef struct VkBufferCopy {
    VkDeviceSize srcOffset;
    VkDeviceSize dstOffset;
    VkDeviceSize size;
} VkBufferCopy;

typedef struct VkSubmitInfo {
    VkStructureType sType;
    const void* pNext;
    std::uint32_t waitSemaphoreCount;
    const VkSemaphore* pWaitSemaphores;
    const VkPipelineStageFlags* pWaitDstStageMask;
    std::uint32_t commandBufferCount;
    const VkCommandBuffer* pCommandBuffers;
    std::uint32_t signalSemaphoreCount;
    const VkSemaphore* pSignalSemaphores;
} VkSubmitInfo;

typedef struct VkFenceCreateInfo {
    VkStructureType sType;
    const void* pNext;
    VkFenceCreateFlags flags;
} VkFenceCreateInfo;

typedef struct VkQueryPoolCreateInfo {
    VkStructureType sType;
    const void* pNext;
    VkQueryPoolCreateFlags flags;
    VkQueryType queryType;
    std::uint32_t queryCount;
    VkFlags pipelineStatistics;
} VkQueryPoolCreateInfo;

typedef struct VkAllocationCallbacks VkAllocationCallbacks;
typedef void (VKAPI_PTR *PFN_vkVoidFunction)(void);
typedef VkResult (VKAPI_PTR *PFN_vkGetPipelineExecutablePropertiesKHR)(VkDevice, const VkPipelineInfoKHR*, std::uint32_t*, VkPipelineExecutablePropertiesKHR*);
typedef VkResult (VKAPI_PTR *PFN_vkGetPipelineExecutableStatisticsKHR)(VkDevice, const VkPipelineExecutableInfoKHR*, std::uint32_t*, VkPipelineExecutableStatisticKHR*);
typedef VkResult (VKAPI_PTR *PFN_vkGetPipelineExecutableInternalRepresentationsKHR)(VkDevice, const VkPipelineExecutableInfoKHR*, std::uint32_t*, VkPipelineExecutableInternalRepresentationKHR*);

VKAPI_ATTR VkResult VKAPI_CALL vkCreateInstance(const VkInstanceCreateInfo*, const VkAllocationCallbacks*, VkInstance*);
VKAPI_ATTR void VKAPI_CALL vkDestroyInstance(VkInstance, const VkAllocationCallbacks*);
VKAPI_ATTR VkResult VKAPI_CALL vkEnumeratePhysicalDevices(VkInstance, std::uint32_t*, VkPhysicalDevice*);
VKAPI_ATTR VkResult VKAPI_CALL vkEnumerateDeviceExtensionProperties(VkPhysicalDevice, const char*, std::uint32_t*, VkExtensionProperties*);
VKAPI_ATTR void VKAPI_CALL vkGetPhysicalDeviceProperties(VkPhysicalDevice, VkPhysicalDeviceProperties*);
VKAPI_ATTR void VKAPI_CALL vkGetPhysicalDeviceFeatures2(VkPhysicalDevice, VkPhysicalDeviceFeatures2*);
VKAPI_ATTR void VKAPI_CALL vkGetPhysicalDeviceQueueFamilyProperties(VkPhysicalDevice, std::uint32_t*, VkQueueFamilyProperties*);
VKAPI_ATTR void VKAPI_CALL vkGetPhysicalDeviceMemoryProperties(VkPhysicalDevice, VkPhysicalDeviceMemoryProperties*);
VKAPI_ATTR VkResult VKAPI_CALL vkCreateDevice(VkPhysicalDevice, const VkDeviceCreateInfo*, const VkAllocationCallbacks*, VkDevice*);
VKAPI_ATTR void VKAPI_CALL vkDestroyDevice(VkDevice, const VkAllocationCallbacks*);
VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL vkGetDeviceProcAddr(VkDevice, const char*);
VKAPI_ATTR void VKAPI_CALL vkGetDeviceQueue(VkDevice, std::uint32_t, std::uint32_t, VkQueue*);
VKAPI_ATTR VkResult VKAPI_CALL vkDeviceWaitIdle(VkDevice);

VKAPI_ATTR VkResult VKAPI_CALL vkCreateBuffer(VkDevice, const VkBufferCreateInfo*, const VkAllocationCallbacks*, VkBuffer*);
VKAPI_ATTR void VKAPI_CALL vkDestroyBuffer(VkDevice, VkBuffer, const VkAllocationCallbacks*);
VKAPI_ATTR void VKAPI_CALL vkGetBufferMemoryRequirements(VkDevice, VkBuffer, VkMemoryRequirements*);
VKAPI_ATTR VkResult VKAPI_CALL vkAllocateMemory(VkDevice, const VkMemoryAllocateInfo*, const VkAllocationCallbacks*, VkDeviceMemory*);
VKAPI_ATTR void VKAPI_CALL vkFreeMemory(VkDevice, VkDeviceMemory, const VkAllocationCallbacks*);
VKAPI_ATTR VkResult VKAPI_CALL vkBindBufferMemory(VkDevice, VkBuffer, VkDeviceMemory, VkDeviceSize);
VKAPI_ATTR VkResult VKAPI_CALL vkMapMemory(VkDevice, VkDeviceMemory, VkDeviceSize, VkDeviceSize, VkFlags, void**);
VKAPI_ATTR void VKAPI_CALL vkUnmapMemory(VkDevice, VkDeviceMemory);
VKAPI_ATTR VkResult VKAPI_CALL vkCreateBufferView(VkDevice, const VkBufferViewCreateInfo*, const VkAllocationCallbacks*, VkBufferView*);
VKAPI_ATTR void VKAPI_CALL vkDestroyBufferView(VkDevice, VkBufferView, const VkAllocationCallbacks*);

VKAPI_ATTR VkResult VKAPI_CALL vkCreateDescriptorSetLayout(VkDevice, const VkDescriptorSetLayoutCreateInfo*, const VkAllocationCallbacks*, VkDescriptorSetLayout*);
VKAPI_ATTR void VKAPI_CALL vkDestroyDescriptorSetLayout(VkDevice, VkDescriptorSetLayout, const VkAllocationCallbacks*);
VKAPI_ATTR VkResult VKAPI_CALL vkCreatePipelineLayout(VkDevice, const VkPipelineLayoutCreateInfo*, const VkAllocationCallbacks*, VkPipelineLayout*);
VKAPI_ATTR void VKAPI_CALL vkDestroyPipelineLayout(VkDevice, VkPipelineLayout, const VkAllocationCallbacks*);
VKAPI_ATTR VkResult VKAPI_CALL vkCreateShaderModule(VkDevice, const VkShaderModuleCreateInfo*, const VkAllocationCallbacks*, VkShaderModule*);
VKAPI_ATTR void VKAPI_CALL vkDestroyShaderModule(VkDevice, VkShaderModule, const VkAllocationCallbacks*);
VKAPI_ATTR VkResult VKAPI_CALL vkCreatePipelineCache(VkDevice, const VkPipelineCacheCreateInfo*, const VkAllocationCallbacks*, VkPipelineCache*);
VKAPI_ATTR void VKAPI_CALL vkDestroyPipelineCache(VkDevice, VkPipelineCache, const VkAllocationCallbacks*);
VKAPI_ATTR VkResult VKAPI_CALL vkGetPipelineCacheData(VkDevice, VkPipelineCache, std::size_t*, void*);
VKAPI_ATTR VkResult VKAPI_CALL vkCreateComputePipelines(VkDevice, VkPipelineCache, std::uint32_t, const VkComputePipelineCreateInfo*, const VkAllocationCallbacks*, VkPipeline*);
VKAPI_ATTR void VKAPI_CALL vkDestroyPipeline(VkDevice, VkPipeline, const VkAllocationCallbacks*);

VKAPI_ATTR VkResult VKAPI_CALL vkCreateDescriptorPool(VkDevice, const VkDescriptorPoolCreateInfo*, const VkAllocationCallbacks*, VkDescriptorPool*);
VKAPI_ATTR void VKAPI_CALL vkDestroyDescriptorPool(VkDevice, VkDescriptorPool, const VkAllocationCallbacks*);
VKAPI_ATTR VkResult VKAPI_CALL vkAllocateDescriptorSets(VkDevice, const VkDescriptorSetAllocateInfo*, VkDescriptorSet*);
VKAPI_ATTR void VKAPI_CALL vkUpdateDescriptorSets(VkDevice, std::uint32_t, const VkWriteDescriptorSet*, std::uint32_t, const void*);

VKAPI_ATTR VkResult VKAPI_CALL vkCreateCommandPool(VkDevice, const VkCommandPoolCreateInfo*, const VkAllocationCallbacks*, VkCommandPool*);
VKAPI_ATTR void VKAPI_CALL vkDestroyCommandPool(VkDevice, VkCommandPool, const VkAllocationCallbacks*);
VKAPI_ATTR VkResult VKAPI_CALL vkAllocateCommandBuffers(VkDevice, const VkCommandBufferAllocateInfo*, VkCommandBuffer*);
VKAPI_ATTR void VKAPI_CALL vkFreeCommandBuffers(VkDevice, VkCommandPool, std::uint32_t, const VkCommandBuffer*);
VKAPI_ATTR VkResult VKAPI_CALL vkBeginCommandBuffer(VkCommandBuffer, const VkCommandBufferBeginInfo*);
VKAPI_ATTR VkResult VKAPI_CALL vkEndCommandBuffer(VkCommandBuffer);
VKAPI_ATTR void VKAPI_CALL vkCmdBindPipeline(VkCommandBuffer, VkPipelineBindPoint, VkPipeline);
VKAPI_ATTR void VKAPI_CALL vkCmdBindDescriptorSets(VkCommandBuffer, VkPipelineBindPoint, VkPipelineLayout, std::uint32_t, std::uint32_t, const VkDescriptorSet*, std::uint32_t, const std::uint32_t*);
VKAPI_ATTR void VKAPI_CALL vkCmdDispatch(VkCommandBuffer, std::uint32_t, std::uint32_t, std::uint32_t);
VKAPI_ATTR void VKAPI_CALL vkCmdCopyBuffer(VkCommandBuffer, VkBuffer, VkBuffer, std::uint32_t, const VkBufferCopy*);
VKAPI_ATTR void VKAPI_CALL vkCmdFillBuffer(VkCommandBuffer, VkBuffer, VkDeviceSize, VkDeviceSize, std::uint32_t);
VKAPI_ATTR void VKAPI_CALL vkCmdPipelineBarrier(VkCommandBuffer, VkPipelineStageFlags, VkPipelineStageFlags, VkDependencyFlags, std::uint32_t, const void*, std::uint32_t, const VkBufferMemoryBarrier*, std::uint32_t, const void*);

VKAPI_ATTR VkResult VKAPI_CALL vkCreateFence(VkDevice, const VkFenceCreateInfo*, const VkAllocationCallbacks*, VkFence*);
VKAPI_ATTR void VKAPI_CALL vkDestroyFence(VkDevice, VkFence, const VkAllocationCallbacks*);
VKAPI_ATTR VkResult VKAPI_CALL vkResetFences(VkDevice, std::uint32_t, const VkFence*);
VKAPI_ATTR VkResult VKAPI_CALL vkWaitForFences(VkDevice, std::uint32_t, const VkFence*, VkBool32, std::uint64_t);
VKAPI_ATTR VkResult VKAPI_CALL vkQueueSubmit(VkQueue, std::uint32_t, const VkSubmitInfo*, VkFence);
VKAPI_ATTR VkResult VKAPI_CALL vkQueueWaitIdle(VkQueue);

VKAPI_ATTR VkResult VKAPI_CALL vkCreateQueryPool(VkDevice, const VkQueryPoolCreateInfo*, const VkAllocationCallbacks*, VkQueryPool*);
VKAPI_ATTR void VKAPI_CALL vkDestroyQueryPool(VkDevice, VkQueryPool, const VkAllocationCallbacks*);
VKAPI_ATTR void VKAPI_CALL vkCmdResetQueryPool(VkCommandBuffer, VkQueryPool, std::uint32_t, std::uint32_t);
VKAPI_ATTR void VKAPI_CALL vkCmdWriteTimestamp(VkCommandBuffer, VkPipelineStageFlags, VkQueryPool, std::uint32_t);
VKAPI_ATTR VkResult VKAPI_CALL vkGetQueryPoolResults(VkDevice, VkQueryPool, std::uint32_t, std::uint32_t, std::size_t, void*, VkDeviceSize, VkQueryResultFlags);

} // extern "C"
