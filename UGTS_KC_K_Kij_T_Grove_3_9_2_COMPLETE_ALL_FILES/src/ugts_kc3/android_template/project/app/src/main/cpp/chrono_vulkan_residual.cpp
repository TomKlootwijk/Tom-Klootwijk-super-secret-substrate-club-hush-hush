#include "chrono_vulkan_residual.hpp"

#include "chrono_gsp4_residual_spv.hpp"
#include "seeded_uglut2_traversal.hpp"

#include <android/log.h>
#include <vulkan/vulkan.h>

#include <algorithm>
#include <array>
#include <chrono>
#include <cstring>
#include <limits>
#include <stdexcept>

#define KC_VK_LOGI(...) __android_log_print(ANDROID_LOG_INFO,"UGTS-KC392-VK",__VA_ARGS__)
#define KC_VK_LOGE(...) __android_log_print(ANDROID_LOG_ERROR,"UGTS-KC392-VK",__VA_ARGS__)

namespace kc {
namespace {

constexpr std::uint32_t WorkgroupSize=256u;

void require(bool condition,const char* detail) {
    if (!condition) throw std::runtime_error(detail);
}

std::string digestHex(const ChronoSha256Digest& digest) {
    static constexpr char Hex[]="0123456789abcdef";
    std::string result(digest.size()*2u,'0');
    for (std::size_t index=0;index<digest.size();++index) {
        result[index*2u]=Hex[digest[index]>>4u];
        result[index*2u+1u]=Hex[digest[index]&15u];
    }
    return result;
}

} // namespace

struct ChronoVulkanResidual::Impl {
    struct Buffer {
        VkBuffer handle=VK_NULL_HANDLE;
        VkDeviceMemory memory=VK_NULL_HANDLE;
        void* mapped=nullptr;
        VkDeviceSize logicalBytes=0;
        bool coherent=false;
    };

    VkInstance instance=VK_NULL_HANDLE;
    VkPhysicalDevice physical=VK_NULL_HANDLE;
    VkDevice device=VK_NULL_HANDLE;
    VkQueue queue=VK_NULL_HANDLE;
    std::uint32_t queueFamily=0;
    std::uint32_t timestampValidBits=0;
    VkPhysicalDeviceProperties properties{};
    VkPhysicalDeviceMemoryProperties memoryProperties{};
    VkDescriptorSetLayout descriptorLayout=VK_NULL_HANDLE;
    VkPipelineLayout pipelineLayout=VK_NULL_HANDLE;
    VkShaderModule shader=VK_NULL_HANDLE;
    VkPipeline pipeline=VK_NULL_HANDLE;
    VkDescriptorPool descriptorPool=VK_NULL_HANDLE;
    VkDescriptorSet descriptorSet=VK_NULL_HANDLE;
    VkCommandPool commandPool=VK_NULL_HANDLE;
    VkCommandBuffer commandBuffer=VK_NULL_HANDLE;
    VkFence fence=VK_NULL_HANDLE;
    VkQueryPool queryPool=VK_NULL_HANDLE;
    Buffer current,previous,map,output;
    std::uint32_t width=0,height=0;
    std::size_t yBytes=0,chromaBytes=0,denseBytes=0,logicalBytes=0;
    std::vector<std::uint32_t> laneSource;
    std::vector<std::uint8_t> previousDense;
    std::vector<std::uint8_t> cpuResidual;
    std::string selectedDevice;
    std::uint64_t dispatches=0;
    bool ready=false;

    ~Impl() { shutdown(); }

    std::uint32_t memoryType(std::uint32_t bits) const {
        for (std::uint32_t index=0;index<memoryProperties.memoryTypeCount;++index) {
            const auto flags=memoryProperties.memoryTypes[index].propertyFlags;
            if ((bits&(1u<<index))!=0u &&
                (flags&VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT)!=0u) return index;
        }
        throw std::runtime_error("Vulkan device has no host-visible storage memory");
    }

    void createBuffer(Buffer& buffer,VkDeviceSize bytes) {
        buffer.logicalBytes=bytes;
        const VkBufferCreateInfo info{
            VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,nullptr,0u,bytes,
            VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,VK_SHARING_MODE_EXCLUSIVE,0u,nullptr};
        require(vkCreateBuffer(device,&info,nullptr,&buffer.handle)==VK_SUCCESS,
            "vkCreateBuffer failed");
        VkMemoryRequirements requirements{};
        vkGetBufferMemoryRequirements(device,buffer.handle,&requirements);
        const auto type=memoryType(requirements.memoryTypeBits);
        const VkMemoryAllocateInfo allocation{
            VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,nullptr,requirements.size,type};
        require(vkAllocateMemory(device,&allocation,nullptr,&buffer.memory)==VK_SUCCESS,
            "vkAllocateMemory failed");
        require(vkBindBufferMemory(device,buffer.handle,buffer.memory,0u)==VK_SUCCESS,
            "vkBindBufferMemory failed");
        require(vkMapMemory(device,buffer.memory,0u,VK_WHOLE_SIZE,0u,&buffer.mapped)==VK_SUCCESS,
            "vkMapMemory failed");
        buffer.coherent=(memoryProperties.memoryTypes[type].propertyFlags&
            VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)!=0u;
    }

    void flush(const Buffer& buffer) const {
        if (buffer.coherent) return;
        const VkMappedMemoryRange range{
            VK_STRUCTURE_TYPE_MAPPED_MEMORY_RANGE,nullptr,buffer.memory,0u,VK_WHOLE_SIZE};
        require(vkFlushMappedMemoryRanges(device,1u,&range)==VK_SUCCESS,
            "vkFlushMappedMemoryRanges failed");
    }

    void invalidate(const Buffer& buffer) const {
        if (buffer.coherent) return;
        const VkMappedMemoryRange range{
            VK_STRUCTURE_TYPE_MAPPED_MEMORY_RANGE,nullptr,buffer.memory,0u,VK_WHOLE_SIZE};
        require(vkInvalidateMappedMemoryRanges(device,1u,&range)==VK_SUCCESS,
            "vkInvalidateMappedMemoryRanges failed");
    }

    void destroyBuffer(Buffer& buffer) {
        if (!device) return;
        if (buffer.mapped) vkUnmapMemory(device,buffer.memory);
        if (buffer.handle) vkDestroyBuffer(device,buffer.handle,nullptr);
        if (buffer.memory) vkFreeMemory(device,buffer.memory,nullptr);
        buffer={};
    }

    void shutdown() {
        if (device) vkDeviceWaitIdle(device);
        destroyBuffer(output); destroyBuffer(map); destroyBuffer(previous); destroyBuffer(current);
        if (device && queryPool) vkDestroyQueryPool(device,queryPool,nullptr);
        if (device && fence) vkDestroyFence(device,fence,nullptr);
        if (device && commandPool) vkDestroyCommandPool(device,commandPool,nullptr);
        if (device && descriptorPool) vkDestroyDescriptorPool(device,descriptorPool,nullptr);
        if (device && pipeline) vkDestroyPipeline(device,pipeline,nullptr);
        if (device && shader) vkDestroyShaderModule(device,shader,nullptr);
        if (device && pipelineLayout) vkDestroyPipelineLayout(device,pipelineLayout,nullptr);
        if (device && descriptorLayout)
            vkDestroyDescriptorSetLayout(device,descriptorLayout,nullptr);
        if (device) vkDestroyDevice(device,nullptr);
        if (instance) vkDestroyInstance(instance,nullptr);
        instance=VK_NULL_HANDLE; physical=VK_NULL_HANDLE; device=VK_NULL_HANDLE;
        ready=false;
    }

    void choosePhysicalDevice() {
        auto getFeatures2=reinterpret_cast<PFN_vkGetPhysicalDeviceFeatures2>(
            vkGetInstanceProcAddr(instance,"vkGetPhysicalDeviceFeatures2"));
        if (!getFeatures2) getFeatures2=reinterpret_cast<PFN_vkGetPhysicalDeviceFeatures2>(
            vkGetInstanceProcAddr(instance,"vkGetPhysicalDeviceFeatures2KHR"));
        require(getFeatures2,"Vulkan loader lacks physical-device feature-chain query");
        std::uint32_t count=0;
        require(vkEnumeratePhysicalDevices(instance,&count,nullptr)==VK_SUCCESS && count>0u,
            "no Vulkan physical device");
        std::vector<VkPhysicalDevice> devices(count);
        require(vkEnumeratePhysicalDevices(instance,&count,devices.data())==VK_SUCCESS,
            "Vulkan physical-device enumeration failed");
        int bestScore=std::numeric_limits<int>::min();
        for (const auto candidate:devices) {
            VkPhysicalDeviceProperties candidateProperties{};
            vkGetPhysicalDeviceProperties(candidate,&candidateProperties);
            VkPhysicalDevice8BitStorageFeatures eight{};
            eight.sType=VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_8BIT_STORAGE_FEATURES;
            VkPhysicalDeviceFeatures2 features{};
            features.sType=VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2;
            features.pNext=&eight;
            getFeatures2(candidate,&features);
            if (!eight.storageBuffer8BitAccess ||
                candidateProperties.apiVersion<VK_API_VERSION_1_2 ||
                candidateProperties.limits.maxComputeWorkGroupInvocations<WorkgroupSize ||
                candidateProperties.limits.maxComputeWorkGroupSize[0]<WorkgroupSize) continue;
            std::uint32_t familyCount=0;
            vkGetPhysicalDeviceQueueFamilyProperties(candidate,&familyCount,nullptr);
            std::vector<VkQueueFamilyProperties> families(familyCount);
            vkGetPhysicalDeviceQueueFamilyProperties(candidate,&familyCount,families.data());
            for (std::uint32_t family=0;family<familyCount;++family) {
                if ((families[family].queueFlags&VK_QUEUE_COMPUTE_BIT)==0u) continue;
                if (families[family].timestampValidBits==0u) continue;
                int score=candidateProperties.deviceType==VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU?100:0;
                if (std::strstr(candidateProperties.deviceName,"Mali")) score+=1000;
                if (score>bestScore) {
                    bestScore=score; physical=candidate; properties=candidateProperties;
                    queueFamily=family;
                    timestampValidBits=families[family].timestampValidBits;
                }
            }
        }
        require(physical!=VK_NULL_HANDLE,"no Vulkan compute device with 8-bit storage");
        vkGetPhysicalDeviceMemoryProperties(physical,&memoryProperties);
        selectedDevice=properties.deviceName;
    }

    void initialize(
        std::uint32_t requestedWidth,std::uint32_t requestedHeight,
        std::uint64_t rootSeed,std::uint64_t recipeSeed,
        const std::vector<std::uint8_t>& literalUglut2
    ) {
        width=requestedWidth; height=requestedHeight;
        yBytes=static_cast<std::size_t>(width)*height;
        chromaBytes=yBytes/4u;
        denseBytes=yBytes+2u*chromaBytes;
        const auto traversal=ugts::chrono::regenerateSeededUglut2Traversal(
            width,height,rootSeed,recipeSeed,literalUglut2);
        laneSource.reserve(denseBytes);
        for (const auto address:traversal.polarOrdinalToCartesian) {
            laneSource.push_back(address);
            const auto x=address%width;
            const auto y=address/width;
            if ((x&1u)==0u && (y&1u)==0u) {
                const auto chroma=(y/2u)*(width/2u)+x/2u;
                laneSource.push_back(static_cast<std::uint32_t>(yBytes+chroma));
                laneSource.push_back(static_cast<std::uint32_t>(yBytes+chromaBytes+chroma));
            }
        }
        require(laneSource.size()==denseBytes,"Vulkan canonical lane-source map length mismatch");
        logicalBytes=laneSource.size();
        previousDense.assign(denseBytes,0u);
        cpuResidual.resize(logicalBytes);

        const VkApplicationInfo application{
            VK_STRUCTURE_TYPE_APPLICATION_INFO,nullptr,"UGTS KC GSP4 residual",392u,
            "UGTOMS substrate",392u,VK_API_VERSION_1_2};
        const VkInstanceCreateInfo instanceInfo{
            VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,nullptr,0u,&application,
            0u,nullptr,0u,nullptr};
        require(vkCreateInstance(&instanceInfo,nullptr,&instance)==VK_SUCCESS,
            "vkCreateInstance failed");
        choosePhysicalDevice();
        const float priority=1.0f;
        const VkDeviceQueueCreateInfo queueInfo{
            VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,nullptr,0u,queueFamily,1u,&priority};
        VkPhysicalDevice8BitStorageFeatures eight{
            VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_8BIT_STORAGE_FEATURES,nullptr,
            VK_TRUE,VK_FALSE,VK_FALSE};
        const VkDeviceCreateInfo deviceInfo{
            VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,&eight,0u,1u,&queueInfo,
            0u,nullptr,0u,nullptr,nullptr};
        require(vkCreateDevice(physical,&deviceInfo,nullptr,&device)==VK_SUCCESS,
            "vkCreateDevice failed");
        vkGetDeviceQueue(device,queueFamily,0u,&queue);

        std::array<VkDescriptorSetLayoutBinding,4> bindings{};
        for (std::uint32_t index=0;index<bindings.size();++index)
            bindings[index]={index,VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,1u,
                VK_SHADER_STAGE_COMPUTE_BIT,nullptr};
        const VkDescriptorSetLayoutCreateInfo descriptorInfo{
            VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO,nullptr,0u,
            static_cast<std::uint32_t>(bindings.size()),bindings.data()};
        require(vkCreateDescriptorSetLayout(device,&descriptorInfo,nullptr,&descriptorLayout)==
            VK_SUCCESS,"vkCreateDescriptorSetLayout failed");
        const VkPushConstantRange push{VK_SHADER_STAGE_COMPUTE_BIT,0u,4u};
        const VkPipelineLayoutCreateInfo layoutInfo{
            VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO,nullptr,0u,
            1u,&descriptorLayout,1u,&push};
        require(vkCreatePipelineLayout(device,&layoutInfo,nullptr,&pipelineLayout)==VK_SUCCESS,
            "vkCreatePipelineLayout failed");
        const VkShaderModuleCreateInfo shaderInfo{
            VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,nullptr,0u,
            ChronoGsp4ResidualSpirv.size()*sizeof(std::uint32_t),
            ChronoGsp4ResidualSpirv.data()};
        require(vkCreateShaderModule(device,&shaderInfo,nullptr,&shader)==VK_SUCCESS,
            "vkCreateShaderModule failed");
        const VkPipelineShaderStageCreateInfo stage{
            VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,nullptr,0u,
            VK_SHADER_STAGE_COMPUTE_BIT,shader,"main",nullptr};
        const VkComputePipelineCreateInfo pipelineInfo{
            VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO,nullptr,0u,stage,pipelineLayout,
            VK_NULL_HANDLE,0};
        require(vkCreateComputePipelines(device,VK_NULL_HANDLE,1u,&pipelineInfo,nullptr,&pipeline)==
            VK_SUCCESS,"vkCreateComputePipelines failed");

        createBuffer(current,denseBytes); createBuffer(previous,denseBytes);
        createBuffer(map,laneSource.size()*sizeof(std::uint32_t));
        createBuffer(output,logicalBytes);
        std::memcpy(map.mapped,laneSource.data(),laneSource.size()*sizeof(std::uint32_t));
        flush(map);
        const VkDescriptorPoolSize poolSize{VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,4u};
        const VkDescriptorPoolCreateInfo poolInfo{
            VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO,nullptr,0u,1u,1u,&poolSize};
        require(vkCreateDescriptorPool(device,&poolInfo,nullptr,&descriptorPool)==VK_SUCCESS,
            "vkCreateDescriptorPool failed");
        const VkDescriptorSetAllocateInfo setInfo{
            VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO,nullptr,descriptorPool,1u,
            &descriptorLayout};
        require(vkAllocateDescriptorSets(device,&setInfo,&descriptorSet)==VK_SUCCESS,
            "vkAllocateDescriptorSets failed");
        const std::array<VkDescriptorBufferInfo,4> bufferInfo{{
            {current.handle,0u,current.logicalBytes},{previous.handle,0u,previous.logicalBytes},
            {map.handle,0u,map.logicalBytes},{output.handle,0u,output.logicalBytes}}};
        std::array<VkWriteDescriptorSet,4> writes{};
        for (std::uint32_t index=0;index<writes.size();++index) {
            writes[index]={VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET,nullptr,descriptorSet,index,0u,
                1u,VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,nullptr,&bufferInfo[index],nullptr};
        }
        vkUpdateDescriptorSets(device,writes.size(),writes.data(),0u,nullptr);
        const VkCommandPoolCreateInfo commandPoolInfo{
            VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,nullptr,
            VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT,queueFamily};
        require(vkCreateCommandPool(device,&commandPoolInfo,nullptr,&commandPool)==VK_SUCCESS,
            "vkCreateCommandPool failed");
        const VkCommandBufferAllocateInfo commandInfo{
            VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,nullptr,commandPool,
            VK_COMMAND_BUFFER_LEVEL_PRIMARY,1u};
        require(vkAllocateCommandBuffers(device,&commandInfo,&commandBuffer)==VK_SUCCESS,
            "vkAllocateCommandBuffers failed");
        VkFenceCreateInfo fenceInfo{};
        fenceInfo.sType=VK_STRUCTURE_TYPE_FENCE_CREATE_INFO;
        require(vkCreateFence(device,&fenceInfo,nullptr,&fence)==VK_SUCCESS,
            "vkCreateFence failed");
        const VkQueryPoolCreateInfo queryInfo{
            VK_STRUCTURE_TYPE_QUERY_POOL_CREATE_INFO,nullptr,0u,VK_QUERY_TYPE_TIMESTAMP,2u,0u};
        require(vkCreateQueryPool(device,&queryInfo,nullptr,&queryPool)==VK_SUCCESS,
            "vkCreateQueryPool failed");
        ready=true;
        KC_VK_LOGI(
            "Vulkan residual ready gpu=%s api=%u.%u.%u local=%u groups=%u "
            "lanes=%llu map_runtime_only=true storage8=true timestamp_bits=%u",
            selectedDevice.c_str(),VK_VERSION_MAJOR(properties.apiVersion),
            VK_VERSION_MINOR(properties.apiVersion),VK_VERSION_PATCH(properties.apiVersion),
            WorkgroupSize,static_cast<unsigned>((logicalBytes+WorkgroupSize-1u)/WorkgroupSize),
            static_cast<unsigned long long>(logicalBytes),
            timestampValidBits);
    }

    bool dispatch(
        std::span<const std::uint8_t> y,std::span<const std::uint8_t> u,
        std::span<const std::uint8_t> v,bool checkpoint,
        std::vector<std::uint8_t>& residual,ChronoVulkanResidualReceipt& receipt
    ) {
        require(ready,"Vulkan residual is unavailable");
        require(y.size()==yBytes && u.size()==chromaBytes && v.size()==chromaBytes,
            "Vulkan residual input plane size mismatch");
        auto* currentBytes=static_cast<std::uint8_t*>(current.mapped);
        std::memcpy(currentBytes,y.data(),y.size());
        std::memcpy(currentBytes+yBytes,u.data(),u.size());
        std::memcpy(currentBytes+yBytes+chromaBytes,v.data(),v.size());
        auto* previousBytes=static_cast<std::uint8_t*>(previous.mapped);
        if (checkpoint) std::memset(previousBytes,0,denseBytes);
        else std::memcpy(previousBytes,previousDense.data(),denseBytes);
        flush(current); flush(previous);
        for (std::size_t lane=0;lane<logicalBytes;++lane) {
            const auto source=laneSource[lane];
            cpuResidual[lane]=static_cast<std::uint8_t>(
                static_cast<unsigned>(currentBytes[source])-previousBytes[source]);
        }
        require(vkResetFences(device,1u,&fence)==VK_SUCCESS,"vkResetFences failed");
        require(vkResetCommandBuffer(commandBuffer,0u)==VK_SUCCESS,
            "vkResetCommandBuffer failed");
        const VkCommandBufferBeginInfo begin{
            VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO,nullptr,
            VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT,nullptr};
        require(vkBeginCommandBuffer(commandBuffer,&begin)==VK_SUCCESS,
            "vkBeginCommandBuffer failed");
        vkCmdResetQueryPool(commandBuffer,queryPool,0u,2u);
        vkCmdWriteTimestamp(commandBuffer,VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,queryPool,0u);
        vkCmdBindPipeline(commandBuffer,VK_PIPELINE_BIND_POINT_COMPUTE,pipeline);
        vkCmdBindDescriptorSets(commandBuffer,VK_PIPELINE_BIND_POINT_COMPUTE,pipelineLayout,
            0u,1u,&descriptorSet,0u,nullptr);
        const auto lanes=static_cast<std::uint32_t>(logicalBytes);
        vkCmdPushConstants(commandBuffer,pipelineLayout,VK_SHADER_STAGE_COMPUTE_BIT,0u,4u,&lanes);
        const auto groups=(lanes+WorkgroupSize-1u)/WorkgroupSize;
        vkCmdDispatch(commandBuffer,groups,1u,1u);
        const VkBufferMemoryBarrier barrier{
            VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER,nullptr,
            VK_ACCESS_SHADER_WRITE_BIT,VK_ACCESS_HOST_READ_BIT,
            VK_QUEUE_FAMILY_IGNORED,VK_QUEUE_FAMILY_IGNORED,output.handle,0u,output.logicalBytes};
        vkCmdPipelineBarrier(commandBuffer,VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
            VK_PIPELINE_STAGE_HOST_BIT,0u,0u,nullptr,1u,&barrier,0u,nullptr);
        vkCmdWriteTimestamp(commandBuffer,VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT,queryPool,1u);
        require(vkEndCommandBuffer(commandBuffer)==VK_SUCCESS,"vkEndCommandBuffer failed");
        const VkSubmitInfo submit{
            VK_STRUCTURE_TYPE_SUBMIT_INFO,nullptr,0u,nullptr,nullptr,1u,&commandBuffer,
            0u,nullptr};
        const auto wallStart=std::chrono::steady_clock::now();
        require(vkQueueSubmit(queue,1u,&submit,fence)==VK_SUCCESS,"vkQueueSubmit failed");
        require(vkWaitForFences(device,1u,&fence,VK_TRUE,5'000'000'000ull)==VK_SUCCESS,
            "Vulkan residual fence timed out");
        const auto wallEnd=std::chrono::steady_clock::now();
        invalidate(output);
        residual.resize(logicalBytes);
        std::memcpy(residual.data(),output.mapped,logicalBytes);
        require(residual==cpuResidual,"Vulkan residual failed full CPU byte parity");
        std::array<std::uint64_t,2> timestamps{};
        const auto queryStatus=vkGetQueryPoolResults(
            device,queryPool,0u,2u,sizeof(timestamps),timestamps.data(),sizeof(std::uint64_t),
            VK_QUERY_RESULT_64_BIT|VK_QUERY_RESULT_WAIT_BIT);
        std::uint64_t gpuNanoseconds=0u;
        if (queryStatus==VK_SUCCESS) {
            const auto mask=timestampValidBits>=64u
                ?std::numeric_limits<std::uint64_t>::max()
                :((1ull<<timestampValidBits)-1ull);
            const auto ticks=(timestamps[1]-timestamps[0])&mask;
            gpuNanoseconds=static_cast<std::uint64_t>(
                static_cast<double>(ticks)*properties.limits.timestampPeriod);
        }
        std::memcpy(previousDense.data(),currentBytes,denseBytes);
        ++dispatches;
        receipt.dispatchIndex=dispatches;
        receipt.workgroupCount=groups;
        receipt.gpuNanoseconds=gpuNanoseconds;
        receipt.submitWallNanoseconds=static_cast<std::uint64_t>(
            std::chrono::duration_cast<std::chrono::nanoseconds>(wallEnd-wallStart).count());
        receipt.residualSha256=chronoCaptureSha256(residual);
        receipt.fullCpuParity=true;
        if (dispatches==1u || dispatches%30u==0u) {
            const auto sha=digestHex(receipt.residualSha256);
            KC_VK_LOGI(
                "Vulkan residual dispatch=%llu groups=%u local=%u gpu_ns=%llu wall_ns=%llu "
                "sha256=%s cpu_full_parity=true",
                static_cast<unsigned long long>(dispatches),groups,WorkgroupSize,
                static_cast<unsigned long long>(gpuNanoseconds),
                static_cast<unsigned long long>(receipt.submitWallNanoseconds),sha.c_str());
        }
        return true;
    }
};

ChronoVulkanResidual::ChronoVulkanResidual():impl_(std::make_unique<Impl>()) {}
ChronoVulkanResidual::~ChronoVulkanResidual()=default;

bool ChronoVulkanResidual::configure(
    std::uint32_t width,std::uint32_t height,std::uint64_t rootSeed,
    std::uint64_t recipeSeed,const std::vector<std::uint8_t>& literalUglut2
) {
    try {
        impl_->initialize(width,height,rootSeed,recipeSeed,literalUglut2);
        return true;
    } catch (const std::exception& error) {
        KC_VK_LOGE("Vulkan residual unavailable, deterministic CPU fallback active: %s",error.what());
        impl_->shutdown();
        return false;
    }
}

bool ChronoVulkanResidual::compute(
    std::span<const std::uint8_t> y,std::span<const std::uint8_t> u,
    std::span<const std::uint8_t> v,bool checkpoint,
    std::vector<std::uint8_t>& residual,ChronoVulkanResidualReceipt& receipt
) {
    try {
        return impl_->dispatch(y,u,v,checkpoint,residual,receipt);
    } catch (const std::exception& error) {
        KC_VK_LOGE("Vulkan residual dispatch failed: %s",error.what());
        return false;
    }
}

bool ChronoVulkanResidual::available() const { return impl_ && impl_->ready; }
std::uint64_t ChronoVulkanResidual::dispatchCount() const {
    return impl_?impl_->dispatches:0u;
}
const std::string& ChronoVulkanResidual::deviceName() const { return impl_->selectedDevice; }

} // namespace kc
