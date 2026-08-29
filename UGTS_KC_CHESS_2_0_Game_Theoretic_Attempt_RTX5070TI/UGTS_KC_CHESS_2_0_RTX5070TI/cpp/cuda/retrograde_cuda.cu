#include "ugts_chess2/retrograde.hpp"

#include <cuda_runtime.h>

#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace ugts::chess2 {
namespace {

void check(cudaError_t status, const char* what) {
    if (status != cudaSuccess) throw std::runtime_error(std::string(what) + ": " + cudaGetErrorString(status));
}

__global__ void retro_step(const std::uint32_t* offsets, const std::uint32_t* children,
                           const std::uint8_t* current, std::uint8_t* next,
                           std::uint32_t node_count, unsigned int* changed) {
    const std::uint32_t node = blockIdx.x * blockDim.x + threadIdx.x;
    if (node >= node_count) return;
    const std::uint8_t old_value = current[node];
    next[node] = old_value;
    if (old_value != static_cast<std::uint8_t>(Wdl::Unknown)) return;
    const std::uint32_t begin = offsets[node];
    const std::uint32_t end = offsets[node + 1];
    if (begin == end) return;
    bool any_loss = false;
    bool all_win = true;
    for (std::uint32_t edge = begin; edge < end; ++edge) {
        const std::uint8_t child = current[children[edge]];
        if (child == static_cast<std::uint8_t>(Wdl::Loss)) any_loss = true;
        if (child != static_cast<std::uint8_t>(Wdl::Win)) all_win = false;
    }
    std::uint8_t resolved = static_cast<std::uint8_t>(Wdl::Unknown);
    if (any_loss) resolved = static_cast<std::uint8_t>(Wdl::Win);
    else if (all_win) resolved = static_cast<std::uint8_t>(Wdl::Loss);
    if (resolved != static_cast<std::uint8_t>(Wdl::Unknown)) {
        next[node] = resolved;
        atomicAdd(changed, 1u);
    }
}

RetroResult solve_cuda_impl(const RetroGraph& graph, bool close_unknown_as_draw) {
    if (graph.offsets.size() != graph.initial.size() + 1 || graph.offsets.empty() || graph.offsets.back() != graph.children.size()) {
        throw std::invalid_argument("invalid retrograde graph");
    }
    int device_count = 0;
    check(cudaGetDeviceCount(&device_count), "cudaGetDeviceCount");
    if (device_count < 1) throw std::runtime_error("no CUDA device is available");

    const std::size_t n = graph.initial.size();
    const std::size_t edge_count = graph.children.size();
    std::vector<std::uint8_t> host(n);
    for (std::size_t i = 0; i < n; ++i) host[i] = static_cast<std::uint8_t>(graph.initial[i]);

    std::uint32_t* d_offsets = nullptr;
    std::uint32_t* d_children = nullptr;
    std::uint8_t* d_current = nullptr;
    std::uint8_t* d_next = nullptr;
    unsigned int* d_changed = nullptr;
    check(cudaMalloc(&d_offsets, graph.offsets.size() * sizeof(std::uint32_t)), "cudaMalloc offsets");
    check(cudaMalloc(&d_children, edge_count * sizeof(std::uint32_t)), "cudaMalloc children");
    check(cudaMalloc(&d_current, n * sizeof(std::uint8_t)), "cudaMalloc current");
    check(cudaMalloc(&d_next, n * sizeof(std::uint8_t)), "cudaMalloc next");
    check(cudaMalloc(&d_changed, sizeof(unsigned int)), "cudaMalloc changed");
    try {
        check(cudaMemcpy(d_offsets, graph.offsets.data(), graph.offsets.size() * sizeof(std::uint32_t), cudaMemcpyHostToDevice), "copy offsets");
        if (edge_count) check(cudaMemcpy(d_children, graph.children.data(), edge_count * sizeof(std::uint32_t), cudaMemcpyHostToDevice), "copy children");
        if (n) check(cudaMemcpy(d_current, host.data(), n * sizeof(std::uint8_t), cudaMemcpyHostToDevice), "copy outcomes");

        RetroResult result;
        result.used_cuda = true;
        result.backend = "cuda-sm-runtime-fixed-point";
        constexpr int threads = 256;
        const int blocks = static_cast<int>((n + threads - 1) / threads);
        for (std::uint32_t iteration = 0; iteration <= n; ++iteration) {
            unsigned int changed = 0;
            check(cudaMemset(d_changed, 0, sizeof(unsigned int)), "clear changed");
            retro_step<<<blocks, threads>>>(d_offsets, d_children, d_current, d_next, static_cast<std::uint32_t>(n), d_changed);
            check(cudaGetLastError(), "retrograde kernel launch");
            check(cudaDeviceSynchronize(), "retrograde kernel sync");
            check(cudaMemcpy(&changed, d_changed, sizeof(unsigned int), cudaMemcpyDeviceToHost), "copy changed");
            if (changed == 0) break;
            result.resolved_by_propagation += changed;
            ++result.iterations;
            std::swap(d_current, d_next);
        }
        if (n) check(cudaMemcpy(host.data(), d_current, n * sizeof(std::uint8_t), cudaMemcpyDeviceToHost), "copy final outcomes");
        result.outcomes.resize(n);
        for (std::size_t i = 0; i < n; ++i) {
            auto value = static_cast<Wdl>(host[i]);
            if (close_unknown_as_draw && value == Wdl::Unknown) {
                value = Wdl::Draw;
                ++result.draws_after_fixpoint;
            }
            result.outcomes[i] = value;
        }
        cudaFree(d_offsets); cudaFree(d_children); cudaFree(d_current); cudaFree(d_next); cudaFree(d_changed);
        return result;
    } catch (...) {
        cudaFree(d_offsets); cudaFree(d_children); cudaFree(d_current); cudaFree(d_next); cudaFree(d_changed);
        throw;
    }
}
}  // namespace

bool cuda_backend_compiled() noexcept { return true; }

std::string cuda_device_summary() {
    int count = 0;
    const cudaError_t status = cudaGetDeviceCount(&count);
    if (status != cudaSuccess) return std::string("CUDA runtime error: ") + cudaGetErrorString(status);
    if (count < 1) return "CUDA backend compiled, but no CUDA device is visible";
    cudaDeviceProp p{};
    if (cudaGetDeviceProperties(&p, 0) != cudaSuccess) return "CUDA device visible, but properties query failed";
    std::ostringstream out;
    out << p.name << " | compute capability " << p.major << '.' << p.minor
        << " | global memory " << (p.totalGlobalMem / (1024ull * 1024ull)) << " MiB"
        << " | SMs " << p.multiProcessorCount;
    return out.str();
}

RetroResult solve_retrograde(const RetroGraph& graph, bool prefer_cuda, bool close_unknown_as_draw) {
    if (!prefer_cuda) return solve_retrograde_cpu(graph, close_unknown_as_draw);
    try {
        return solve_cuda_impl(graph, close_unknown_as_draw);
    } catch (const std::exception& exc) {
        auto result = solve_retrograde_cpu(graph, close_unknown_as_draw);
        result.backend += std::string("; CUDA fallback reason: ") + exc.what();
        return result;
    }
}

}  // namespace ugts::chess2
