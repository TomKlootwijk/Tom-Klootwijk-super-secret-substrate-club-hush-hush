#pragma once
#ifndef __host__
#define __host__ __attribute__((host))
#endif
#ifndef __device__
#define __device__ __attribute__((device))
#endif
#ifndef __global__
#define __global__ __attribute__((global))
#endif
#ifndef __shared__
#define __shared__ __attribute__((shared))
#endif
#ifndef __constant__
#define __constant__ __attribute__((constant))
#endif
#ifndef __device_builtin__
#define __device_builtin__ __attribute__((device_builtin))
#endif
#ifndef __cudart_builtin__
#define __cudart_builtin__ __attribute__((cudart_builtin))
#endif
#ifndef __forceinline__
#define __forceinline__ inline __attribute__((always_inline))
#endif
#include <stddef.h>
#include <stdint.h>

// Device-side overload declarations normally supplied by CUDA math headers.
// They are sufficient for clang CUDA syntax validation; no object is linked.
#if defined(__CUDA__)
__device__ double sin(double);
__device__ double cos(double);
__device__ double sqrt(double);
__device__ double pow(double, double);
__device__ double atan2(double, double);
__device__ double fmod(double, double);
__device__ double fabs(double);
__device__ double floor(double);
__device__ float sinf(float);
__device__ float cosf(float);
__device__ float sqrtf(float);
__device__ float exp2f(float);
__device__ float expm1f(float);
__device__ float fabsf(float);
__device__ float floorf(float);
__device__ float tanhf(float);
#endif

typedef int cudaError_t;
static const cudaError_t cudaSuccess = 0;

enum cudaMemcpyKind {
    cudaMemcpyHostToHost = 0,
    cudaMemcpyHostToDevice = 1,
    cudaMemcpyDeviceToHost = 2,
    cudaMemcpyDeviceToDevice = 3,
    cudaMemcpyDefault = 4
};

enum cudaLimit { cudaLimitStackSize = 0 };

struct cudaDeviceProp {
    char name[256];
    size_t totalGlobalMem;
    size_t totalConstMem;
    size_t sharedMemPerBlock;
    int regsPerBlock;
    int warpSize;
    int maxThreadsPerBlock;
    int multiProcessorCount;
    int l2CacheSize;
    int memoryBusWidth;
    int major;
    int minor;
};

struct CUevent_st;
typedef CUevent_st* cudaEvent_t;
typedef void* cudaStream_t;

struct double4 { double x, y, z, w; };
__host__ __device__ inline double4 make_double4(double x, double y, double z, double w) {
    double4 value{x,y,z,w};
    return value;
}

struct __device_builtin__ uint3 { unsigned int x, y, z; };
struct dim3 {
    unsigned int x, y, z;
    __host__ __device__ constexpr dim3(unsigned int vx=1, unsigned int vy=1, unsigned int vz=1)
        : x(vx), y(vy), z(vz) {}
    __host__ __device__ constexpr dim3(uint3 v) : x(v.x), y(v.y), z(v.z) {}
    __host__ __device__ constexpr operator uint3() const { return uint3{x,y,z}; }
};

extern const __device__ __device_builtin__ uint3 threadIdx;
extern const __device__ __device_builtin__ uint3 blockIdx;
extern const __device__ __device_builtin__ dim3 blockDim;
extern const __device__ __device_builtin__ dim3 gridDim;
extern const __device__ __device_builtin__ int warpSize;

__device__ inline unsigned long long atomicAdd(
    unsigned long long* address, unsigned long long value) {
    const unsigned long long old = *address;
    *address += value;
    return old;
}

__device__ inline unsigned int atomicAdd(
    unsigned int* address, unsigned int value) {
    const unsigned int old = *address;
    *address += value;
    return old;
}

__device__ inline unsigned int __activemask() { return 0xffffffffu; }
__device__ inline unsigned int __ballot_sync(unsigned int mask, int predicate) {
    return predicate ? mask : 0u;
}
__device__ inline int __popc(unsigned int value) {
    int count = 0;
    while (value != 0u) { count += static_cast<int>(value & 1u); value >>= 1u; }
    return count;
}
__device__ inline int __ffs(int value) {
    if (value == 0) return 0;
    int index = 1;
    unsigned int v = static_cast<unsigned int>(value);
    while ((v & 1u) == 0u) { ++index; v >>= 1u; }
    return index;
}
template <typename T>
__device__ inline T __shfl_sync(unsigned int, T value, int, int = 32) { return value; }

#ifndef cudaMemcpyToSymbol
template <typename T> inline cudaError_t cudaMemcpyToSymbol(
    T&, const void*, size_t, size_t = 0, cudaMemcpyKind = cudaMemcpyHostToDevice) {
    return cudaSuccess;
}
#endif

extern "C" {
const char* cudaGetErrorName(cudaError_t);
const char* cudaGetErrorString(cudaError_t);
cudaError_t cudaGetDevice(int*);
cudaError_t cudaSetDevice(int);
cudaError_t cudaDriverGetVersion(int*);
cudaError_t cudaRuntimeGetVersion(int*);
cudaError_t cudaGetDeviceProperties(cudaDeviceProp*, int);
cudaError_t cudaDeviceSetLimit(cudaLimit, size_t);
cudaError_t cudaDeviceSynchronize(void);
cudaError_t cudaGetLastError(void);
cudaError_t cudaMalloc(void**, size_t);
cudaError_t cudaFree(void*);
cudaError_t cudaMemcpy(void*, const void*, size_t, cudaMemcpyKind);
cudaError_t cudaMemset(void*, int, size_t);
cudaError_t cudaMemsetAsync(void*, int, size_t, cudaStream_t = nullptr);
cudaError_t cudaMemGetInfo(size_t*, size_t*);
cudaError_t cudaEventCreate(cudaEvent_t*);
cudaError_t cudaEventDestroy(cudaEvent_t);
cudaError_t cudaEventRecord(cudaEvent_t, cudaStream_t = nullptr);
cudaError_t cudaEventSynchronize(cudaEvent_t);
cudaError_t cudaEventElapsedTime(float*, cudaEvent_t, cudaEvent_t);
cudaError_t cudaConfigureCall(dim3, dim3, size_t = 0, cudaStream_t = nullptr);
cudaError_t cudaSetupArgument(const void*, size_t, size_t);
cudaError_t cudaLaunch(const void*);
}
