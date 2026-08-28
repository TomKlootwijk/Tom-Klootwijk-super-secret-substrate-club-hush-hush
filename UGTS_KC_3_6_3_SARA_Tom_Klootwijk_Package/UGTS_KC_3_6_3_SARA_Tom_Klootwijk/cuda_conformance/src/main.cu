#include "sara363_cuda/crypto.cuh"

#include <cuda_runtime.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <numeric>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using sara363_cuda::ExtendedPrivateKey;
using sara363_cuda::byte;
using sara363_cuda::u32;

constexpr char kMnemonic[] =
    "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about";
constexpr char kSalt[] = "mnemonicTREZOR";
constexpr char kBip39Expected[] =
    "c55257c360c07c72029aebc1b53c05ed0362ada38ead3e3e9efa3708e5349553"
    "1f09a6987599d18264c1e1c92f2cf141630c7a3c4ab7c81b2f001698e7463b04";

constexpr byte kBip32Seed[16] = {
    0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07,
    0x08, 0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x0e, 0x0f,
};

constexpr u32 kPath[5] = {0x80000000U, 1U, 0x80000002U, 2U, 1000000000U};
constexpr const char* kPathNames[6] = {
    "m", "m/0'", "m/0'/1", "m/0'/1/2'", "m/0'/1/2'/2", "m/0'/1/2'/2/1000000000",
};
constexpr const char* kExpectedPrivate[6] = {
    "e8f32e723decf4051aefac8e2c93c9c5b214313817cdb01a1494b917c8436b35",
    "edb2e14f9ee77d26dd93b4ecede8d16ed408ce149b6cd80b0715a2d911a0afea",
    "3c6cb8d0f6a264c91ea8b5030fadaa8e538b020f0a387421a12de9319dc93368",
    "cbce0d719ecf7431d88e6a89fa1483e02e35092af60c042b1df2ff59fa424dca",
    "0f479245fb19a38a1954c5c7c0ebab2f9bdfd96a17563ef28a6a4b1a2a764ef4",
    "471b76e389e528d6de6d816857e012c5455051cad6660850e58372a6c3e6e7c8",
};
constexpr const char* kExpectedChain[6] = {
    "873dff81c02f525623fd1fe5167eac3a55a049de3d314bb42ee227ffed37d508",
    "47fdacbd0f1097043b78c63c20c34ef4ed9a111d980047ad16282c7ae6236141",
    "2a7857631386ba23dacac34180dd1983734e444fdbf774041578e9b6adb37c19",
    "04466b9cc8e161e966409ca52986c584f07e9dc81f735db683c3ff6ec7b1503f",
    "cfb71883f01676f587d023cc53a35bc7f88f724b1f8c2892ac1275ac822a3edd",
    "c783e67b921d2beb8f6b389cc646d7263b4145701dadd2161548a8b078e65e9e",
};
constexpr const char* kExpectedPublic[6] = {
    "0339a36013301597daef41fbe593a02cc513d0b55527ec2df1050e2e8ff49c85c2",
    "035a784662a4a20a65bf6aab9ae98a6c068a81c52e4b032c0fb5400c706cfccc56",
    "03501e454bf00751f24b1b489aa925215d66af2234e3891c3b21a52bedb3cd711c",
    "0357bfe1e341d01c69fe5654309956cbea516822fba8a601743a012a7896ee8dc2",
    "02e8445082a72f29b75ca48748a914df60622a609cacfce8ed0e35804560741d29",
    "022a471424da5e657499d1ff51cb43c47481a03b1e77f951fe64cec9f5a48f7011",
};

__device__ __constant__ char d_mnemonic[] =
    "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about";
__device__ __constant__ char d_salt[] = "mnemonicTREZOR";
__device__ __constant__ byte d_bip32_seed[16] = {
    0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07,
    0x08, 0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x0e, 0x0f,
};
__device__ __constant__ u32 d_path[5] = {0x80000000U, 1U, 0x80000002U, 2U, 1000000000U};

struct Bip32PathResult {
    ExtendedPrivateKey nodes[6];
};

struct Options {
    std::size_t bip39_batch = 1024;
    std::size_t bip32_batch = 64;
    int runs = 3;
    int device = 0;
    bool write_json = true;
    std::filesystem::path json_path = "benchmark_metrics.json";
};

struct Metrics {
    std::string device_name;
    int compute_major = 0;
    int compute_minor = 0;
    int driver_version = 0;
    int runtime_version = 0;
    std::size_t bip39_batch = 0;
    std::size_t bip32_batch = 0;
    int runs = 0;
    double cpu_bip39_ms = 0;
    double cpu_bip32_ms = 0;
    double gpu_bip39_mean_ms = 0;
    double gpu_bip39_min_ms = 0;
    double gpu_bip39_ops_s = 0;
    double gpu_bip39_rounds_s = 0;
    double gpu_bip32_mean_ms = 0;
    double gpu_bip32_min_ms = 0;
    double gpu_bip32_paths_s = 0;
    double gpu_bip32_edges_s = 0;
    double bip39_throughput_speedup = 0;
    double bip32_throughput_speedup = 0;
    bool cpu_bip39_pass = false;
    bool cpu_bip32_pass = false;
    bool gpu_bip39_pass = false;
    bool gpu_bip32_pass = false;
    bool repeatability_pass = false;
};

#define CUDA_CHECK(call)                                                                                              \
    do {                                                                                                              \
        const cudaError_t sara_cuda_error = (call);                                                                  \
        if (sara_cuda_error != cudaSuccess) {                                                                         \
            std::ostringstream sara_cuda_message;                                                                     \
            sara_cuda_message << #call << " failed at " << __FILE__ << ':' << __LINE__ << ": "                     \
                              << cudaGetErrorString(sara_cuda_error);                                                  \
            throw std::runtime_error(sara_cuda_message.str());                                                        \
        }                                                                                                             \
    } while (false)

template <typename T>
class DeviceBuffer {
  public:
    explicit DeviceBuffer(std::size_t count) : count_(count) {
        CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&pointer_), count_ * sizeof(T)));
    }
    ~DeviceBuffer() {
        if (pointer_ != nullptr) {
            cudaFree(pointer_);
        }
    }
    DeviceBuffer(const DeviceBuffer&) = delete;
    DeviceBuffer& operator=(const DeviceBuffer&) = delete;
    T* get() { return pointer_; }
    std::size_t count() const { return count_; }

  private:
    T* pointer_ = nullptr;
    std::size_t count_ = 0;
};

__global__ void bip39_batch_kernel(byte* output, std::size_t count) {
    const std::size_t index = static_cast<std::size_t>(blockIdx.x) * blockDim.x + threadIdx.x;
    if (index >= count) {
        return;
    }
    sara363_cuda::pbkdf2_hmac_sha512_2048(reinterpret_cast<const byte*>(d_mnemonic), sizeof(d_mnemonic) - 1,
                                          reinterpret_cast<const byte*>(d_salt), sizeof(d_salt) - 1,
                                          output + index * 64);
}

__global__ void bip32_conformance_kernel(Bip32PathResult* output) {
    if (blockIdx.x != 0 || threadIdx.x != 0) {
        return;
    }
    output->nodes[0] = sara363_cuda::bip32_master(d_bip32_seed, sizeof(d_bip32_seed));
    for (int i = 0; i < 5; ++i) {
        output->nodes[i + 1] = sara363_cuda::bip32_ckd_private(output->nodes[i], d_path[i]);
    }
}

__global__ void bip32_batch_kernel(ExtendedPrivateKey* output, std::size_t count) {
    const std::size_t index = static_cast<std::size_t>(blockIdx.x) * blockDim.x + threadIdx.x;
    if (index >= count) {
        return;
    }
    ExtendedPrivateKey node = sara363_cuda::bip32_master(d_bip32_seed, sizeof(d_bip32_seed));
    for (int i = 0; i < 5; ++i) {
        node = sara363_cuda::bip32_ckd_private(node, d_path[i]);
    }
    output[index] = node;
}

int hex_value(char c) {
    if (c >= '0' && c <= '9') {
        return c - '0';
    }
    if (c >= 'a' && c <= 'f') {
        return c - 'a' + 10;
    }
    if (c >= 'A' && c <= 'F') {
        return c - 'A' + 10;
    }
    throw std::runtime_error("invalid embedded hex fixture");
}

std::vector<byte> decode_hex(const char* text) {
    const std::string value(text);
    if ((value.size() & 1U) != 0) {
        throw std::runtime_error("odd embedded hex fixture length");
    }
    std::vector<byte> result(value.size() / 2);
    for (std::size_t i = 0; i < result.size(); ++i) {
        result[i] = static_cast<byte>((hex_value(value[i * 2]) << 4) | hex_value(value[i * 2 + 1]));
    }
    return result;
}

bool equal_bytes(const byte* actual, const char* expected_hex, std::size_t length) {
    const auto expected = decode_hex(expected_hex);
    if (expected.size() != length) {
        return false;
    }
    for (std::size_t i = 0; i < length; ++i) {
        if (actual[i] != expected[i]) {
            return false;
        }
    }
    return true;
}

bool equal_key(const ExtendedPrivateKey& a, const ExtendedPrivateKey& b) {
    if (a.valid != b.valid) {
        return false;
    }
    for (int i = 0; i < 32; ++i) {
        if (a.private_key[i] != b.private_key[i] || a.chain_code[i] != b.chain_code[i]) {
            return false;
        }
    }
    for (int i = 0; i < 33; ++i) {
        if (a.public_key[i] != b.public_key[i]) {
            return false;
        }
    }
    return true;
}

bool verify_bip32_path(const Bip32PathResult& result, bool verbose) {
    bool all_pass = true;
    for (int node = 0; node < 6; ++node) {
        const auto& value = result.nodes[node];
        const bool pass = value.valid != 0 && equal_bytes(value.private_key, kExpectedPrivate[node], 32) &&
                          equal_bytes(value.chain_code, kExpectedChain[node], 32) &&
                          equal_bytes(value.public_key, kExpectedPublic[node], 33);
        all_pass = all_pass && pass;
        if (verbose) {
            std::cout << "  " << std::left << std::setw(29) << kPathNames[node] << (pass ? "PASS" : "FAIL") << '\n';
        }
    }
    return all_pass;
}

Bip32PathResult compute_cpu_bip32() {
    Bip32PathResult result{};
    result.nodes[0] = sara363_cuda::bip32_master(kBip32Seed, sizeof(kBip32Seed));
    for (int i = 0; i < 5; ++i) {
        result.nodes[i + 1] = sara363_cuda::bip32_ckd_private(result.nodes[i], kPath[i]);
    }
    return result;
}

double mean(const std::vector<float>& values) {
    return std::accumulate(values.begin(), values.end(), 0.0) / static_cast<double>(values.size());
}

std::string json_escape(const std::string& value) {
    std::ostringstream out;
    for (const char c : value) {
        if (c == '\\' || c == '"') {
            out << '\\';
        }
        out << c;
    }
    return out.str();
}

void write_metrics_json(const Metrics& m, const std::filesystem::path& path) {
    if (!path.parent_path().empty()) {
        std::filesystem::create_directories(path.parent_path());
    }
    std::ofstream out(path, std::ios::binary);
    if (!out) {
        throw std::runtime_error("unable to open metrics output: " + path.string());
    }
    out << std::fixed << std::setprecision(6);
    out << "{\n"
        << "  \"schema\": \"sara363.cuda.fixed-vector.metrics.v1\",\n"
        << "  \"safety_profile\": \"immutable-published-vectors-only\",\n"
        << "  \"device\": {\"name\": \"" << json_escape(m.device_name) << "\", \"compute_capability\": \""
        << m.compute_major << '.' << m.compute_minor << "\", \"driver_version\": " << m.driver_version
        << ", \"runtime_version\": " << m.runtime_version << "},\n"
        << "  \"configuration\": {\"bip39_batch\": " << m.bip39_batch << ", \"bip32_batch\": "
        << m.bip32_batch << ", \"timed_runs\": " << m.runs << "},\n"
        << "  \"correctness\": {\"cpu_bip39\": " << (m.cpu_bip39_pass ? "true" : "false")
        << ", \"cpu_bip32_vector1_full_path\": " << (m.cpu_bip32_pass ? "true" : "false")
        << ", \"gpu_bip39\": " << (m.gpu_bip39_pass ? "true" : "false")
        << ", \"gpu_bip32_vector1_full_path\": " << (m.gpu_bip32_pass ? "true" : "false")
        << ", \"repeatability\": " << (m.repeatability_pass ? "true" : "false") << "},\n"
        << "  \"cpu\": {\"bip39_ms_per_operation\": " << m.cpu_bip39_ms
        << ", \"bip32_vector1_ms_per_path\": " << m.cpu_bip32_ms << "},\n"
        << "  \"gpu\": {\n"
        << "    \"bip39_mean_batch_ms\": " << m.gpu_bip39_mean_ms << ",\n"
        << "    \"bip39_min_batch_ms\": " << m.gpu_bip39_min_ms << ",\n"
        << "    \"bip39_operations_per_second\": " << m.gpu_bip39_ops_s << ",\n"
        << "    \"pbkdf2_rounds_per_second\": " << m.gpu_bip39_rounds_s << ",\n"
        << "    \"bip32_mean_batch_ms\": " << m.gpu_bip32_mean_ms << ",\n"
        << "    \"bip32_min_batch_ms\": " << m.gpu_bip32_min_ms << ",\n"
        << "    \"bip32_paths_per_second\": " << m.gpu_bip32_paths_s << ",\n"
        << "    \"bip32_ckd_edges_per_second\": " << m.gpu_bip32_edges_s << "\n"
        << "  },\n"
        << "  \"throughput_speedup_vs_single_cpu\": {\"bip39\": " << m.bip39_throughput_speedup
        << ", \"bip32_vector1_path\": " << m.bip32_throughput_speedup << "}\n"
        << "}\n";
}

Options parse_options(int argc, char** argv) {
    Options options{};
    for (int i = 1; i < argc; ++i) {
        const std::string argument(argv[i]);
        auto next = [&]() -> std::string {
            if (++i >= argc) {
                throw std::runtime_error("missing value after " + argument);
            }
            return argv[i];
        };
        if (argument == "--bip39-batch") {
            options.bip39_batch = std::stoull(next());
        } else if (argument == "--bip32-batch") {
            options.bip32_batch = std::stoull(next());
        } else if (argument == "--runs") {
            options.runs = std::stoi(next());
        } else if (argument == "--device") {
            options.device = std::stoi(next());
        } else if (argument == "--json") {
            options.json_path = next();
            options.write_json = true;
        } else if (argument == "--no-json") {
            options.write_json = false;
        } else if (argument == "--quick") {
            options.bip39_batch = 8;
            options.bip32_batch = 2;
            options.runs = 1;
        } else if (argument == "--help") {
            std::cout << "Fixed public-vector conformance benchmark only.\n"
                         "Options: --bip39-batch N --bip32-batch N --runs N --device N --json PATH --no-json --quick\n"
                         "There are deliberately no mnemonic, passphrase, address, wordlist, candidate, or search options.\n";
            std::exit(0);
        } else {
            throw std::runtime_error("unknown option: " + argument);
        }
    }
    if (options.bip39_batch == 0 || options.bip39_batch > 65536 || options.bip32_batch == 0 ||
        options.bip32_batch > 4096 || options.runs < 1 || options.runs > 20) {
        throw std::runtime_error("batch/runs outside fixed benchmark limits");
    }
    return options;
}

} // namespace

int main(int argc, char** argv) {
    try {
        const Options options = parse_options(argc, argv);
        std::cout << "SARA 3.6.3 CUDA fixed-vector conformance benchmark\n"
                     "SAFETY PROFILE: immutable published vectors only; no candidate enumeration or target comparison.\n\n";

        Metrics metrics{};
        metrics.bip39_batch = options.bip39_batch;
        metrics.bip32_batch = options.bip32_batch;
        metrics.runs = options.runs;

        constexpr int cpu_runs = 7;
        byte cpu_bip39[64];
        std::vector<double> cpu_bip39_times;
        Bip32PathResult cpu_bip32{};
        std::vector<double> cpu_bip32_times;
        for (int run = 0; run < cpu_runs; ++run) {
            const auto start = std::chrono::steady_clock::now();
            sara363_cuda::pbkdf2_hmac_sha512_2048(reinterpret_cast<const byte*>(kMnemonic), sizeof(kMnemonic) - 1,
                                                  reinterpret_cast<const byte*>(kSalt), sizeof(kSalt) - 1, cpu_bip39);
            const auto stop = std::chrono::steady_clock::now();
            cpu_bip39_times.push_back(std::chrono::duration<double, std::milli>(stop - start).count());
        }
        metrics.cpu_bip39_ms = std::accumulate(cpu_bip39_times.begin(), cpu_bip39_times.end(), 0.0) / cpu_runs;
        metrics.cpu_bip39_pass = equal_bytes(cpu_bip39, kBip39Expected, 64);

        for (int run = 0; run < cpu_runs; ++run) {
            const auto start = std::chrono::steady_clock::now();
            cpu_bip32 = compute_cpu_bip32();
            const auto stop = std::chrono::steady_clock::now();
            cpu_bip32_times.push_back(std::chrono::duration<double, std::milli>(stop - start).count());
        }
        metrics.cpu_bip32_ms = std::accumulate(cpu_bip32_times.begin(), cpu_bip32_times.end(), 0.0) / cpu_runs;
        std::cout << "CPU official-vector checks:\n";
        std::cout << "  BIP39 vector (PBKDF2-HMAC-SHA512/2048) " << (metrics.cpu_bip39_pass ? "PASS" : "FAIL") << '\n';
        metrics.cpu_bip32_pass = verify_bip32_path(cpu_bip32, true);
        std::cout << "  CPU mean timings (" << cpu_runs << " runs): BIP39 " << std::fixed << std::setprecision(3)
                  << metrics.cpu_bip39_ms << " ms; full BIP32 vector-1 path " << metrics.cpu_bip32_ms << " ms\n\n";

        CUDA_CHECK(cudaSetDevice(options.device));
        cudaDeviceProp device{};
        CUDA_CHECK(cudaGetDeviceProperties(&device, options.device));
        CUDA_CHECK(cudaDriverGetVersion(&metrics.driver_version));
        CUDA_CHECK(cudaRuntimeGetVersion(&metrics.runtime_version));
        metrics.device_name = device.name;
        metrics.compute_major = device.major;
        metrics.compute_minor = device.minor;
        std::cout << "CUDA device: " << device.name << " (compute " << device.major << '.' << device.minor << ")\n";
        std::cout << "CUDA driver/runtime: " << metrics.driver_version << '/' << metrics.runtime_version << "\n\n";

        DeviceBuffer<Bip32PathResult> gpu_path(1);
        bip32_conformance_kernel<<<1, 1>>>(gpu_path.get());
        CUDA_CHECK(cudaGetLastError());
        CUDA_CHECK(cudaDeviceSynchronize());
        Bip32PathResult gpu_bip32{};
        CUDA_CHECK(cudaMemcpy(&gpu_bip32, gpu_path.get(), sizeof(gpu_bip32), cudaMemcpyDeviceToHost));
        std::cout << "GPU full BIP32 vector-1 checks:\n";
        metrics.gpu_bip32_pass = verify_bip32_path(gpu_bip32, true);

        DeviceBuffer<byte> gpu_bip39(options.bip39_batch * 64);
        DeviceBuffer<ExtendedPrivateKey> gpu_bip32_batch(options.bip32_batch);
        const unsigned threads = 128;
        const unsigned bip39_blocks = static_cast<unsigned>((options.bip39_batch + threads - 1) / threads);
        const unsigned bip32_blocks = static_cast<unsigned>((options.bip32_batch + threads - 1) / threads);

        bip39_batch_kernel<<<bip39_blocks, threads>>>(gpu_bip39.get(), options.bip39_batch);
        bip32_batch_kernel<<<bip32_blocks, threads>>>(gpu_bip32_batch.get(), options.bip32_batch);
        CUDA_CHECK(cudaGetLastError());
        CUDA_CHECK(cudaDeviceSynchronize());

        std::vector<float> bip39_times;
        std::vector<float> bip32_times;
        std::vector<byte> host_bip39(options.bip39_batch * 64);
        std::vector<ExtendedPrivateKey> host_bip32(options.bip32_batch);
        metrics.gpu_bip39_pass = true;
        bool repeatability = true;
        std::vector<byte> prior_bip39;
        std::vector<ExtendedPrivateKey> prior_bip32;

        for (int run = 0; run < options.runs; ++run) {
            cudaEvent_t start{};
            cudaEvent_t stop{};
            CUDA_CHECK(cudaEventCreate(&start));
            CUDA_CHECK(cudaEventCreate(&stop));
            CUDA_CHECK(cudaEventRecord(start));
            bip39_batch_kernel<<<bip39_blocks, threads>>>(gpu_bip39.get(), options.bip39_batch);
            CUDA_CHECK(cudaGetLastError());
            CUDA_CHECK(cudaEventRecord(stop));
            CUDA_CHECK(cudaEventSynchronize(stop));
            float elapsed = 0;
            CUDA_CHECK(cudaEventElapsedTime(&elapsed, start, stop));
            bip39_times.push_back(elapsed);
            CUDA_CHECK(cudaEventDestroy(start));
            CUDA_CHECK(cudaEventDestroy(stop));
            CUDA_CHECK(cudaMemcpy(host_bip39.data(), gpu_bip39.get(), host_bip39.size(), cudaMemcpyDeviceToHost));
            for (std::size_t i = 0; i < options.bip39_batch; ++i) {
                metrics.gpu_bip39_pass = metrics.gpu_bip39_pass && equal_bytes(host_bip39.data() + i * 64, kBip39Expected, 64);
            }
            if (run != 0 && host_bip39 != prior_bip39) {
                repeatability = false;
            }
            prior_bip39 = host_bip39;

            CUDA_CHECK(cudaEventCreate(&start));
            CUDA_CHECK(cudaEventCreate(&stop));
            CUDA_CHECK(cudaEventRecord(start));
            bip32_batch_kernel<<<bip32_blocks, threads>>>(gpu_bip32_batch.get(), options.bip32_batch);
            CUDA_CHECK(cudaGetLastError());
            CUDA_CHECK(cudaEventRecord(stop));
            CUDA_CHECK(cudaEventSynchronize(stop));
            elapsed = 0;
            CUDA_CHECK(cudaEventElapsedTime(&elapsed, start, stop));
            bip32_times.push_back(elapsed);
            CUDA_CHECK(cudaEventDestroy(start));
            CUDA_CHECK(cudaEventDestroy(stop));
            CUDA_CHECK(cudaMemcpy(host_bip32.data(), gpu_bip32_batch.get(), host_bip32.size() * sizeof(ExtendedPrivateKey),
                                  cudaMemcpyDeviceToHost));
            const ExtendedPrivateKey& expected_final = gpu_bip32.nodes[5];
            for (const auto& value : host_bip32) {
                metrics.gpu_bip32_pass = metrics.gpu_bip32_pass && equal_key(value, expected_final);
            }
            if (run != 0) {
                if (host_bip32.size() != prior_bip32.size()) {
                    repeatability = false;
                } else {
                    for (std::size_t i = 0; i < host_bip32.size(); ++i) {
                        repeatability = repeatability && equal_key(host_bip32[i], prior_bip32[i]);
                    }
                }
            }
            prior_bip32 = host_bip32;
        }

        metrics.repeatability_pass = repeatability;
        metrics.gpu_bip39_mean_ms = mean(bip39_times);
        metrics.gpu_bip39_min_ms = *std::min_element(bip39_times.begin(), bip39_times.end());
        metrics.gpu_bip32_mean_ms = mean(bip32_times);
        metrics.gpu_bip32_min_ms = *std::min_element(bip32_times.begin(), bip32_times.end());
        metrics.gpu_bip39_ops_s = static_cast<double>(options.bip39_batch) * 1000.0 / metrics.gpu_bip39_mean_ms;
        metrics.gpu_bip39_rounds_s = metrics.gpu_bip39_ops_s * 2048.0;
        metrics.gpu_bip32_paths_s = static_cast<double>(options.bip32_batch) * 1000.0 / metrics.gpu_bip32_mean_ms;
        metrics.gpu_bip32_edges_s = metrics.gpu_bip32_paths_s * 5.0;
        metrics.bip39_throughput_speedup = metrics.gpu_bip39_ops_s * metrics.cpu_bip39_ms / 1000.0;
        metrics.bip32_throughput_speedup = metrics.gpu_bip32_paths_s * metrics.cpu_bip32_ms / 1000.0;

        std::cout << "\nGPU batch verification:\n"
                  << "  BIP39 all " << options.bip39_batch << " outputs across " << options.runs << " run(s): "
                  << (metrics.gpu_bip39_pass ? "PASS" : "FAIL") << '\n'
                  << "  BIP32 all " << options.bip32_batch << " paths across " << options.runs << " run(s): "
                  << (metrics.gpu_bip32_pass ? "PASS" : "FAIL") << '\n'
                  << "  Byte-for-byte repeatability: " << (metrics.repeatability_pass ? "PASS" : "FAIL") << "\n\n";
        std::cout << std::fixed << std::setprecision(3)
                  << "Measured GPU metrics (mean of " << options.runs << " timed run(s)):\n"
                  << "  BIP39 batch: " << metrics.gpu_bip39_mean_ms << " ms for " << options.bip39_batch << " operations; "
                  << std::setprecision(1) << metrics.gpu_bip39_ops_s << " operations/s; " << metrics.gpu_bip39_rounds_s
                  << " PBKDF2 rounds/s\n"
                  << std::setprecision(3) << "  BIP32 vector-1 batch: " << metrics.gpu_bip32_mean_ms << " ms for "
                  << options.bip32_batch << " complete paths; " << std::setprecision(1) << metrics.gpu_bip32_paths_s
                  << " paths/s; " << metrics.gpu_bip32_edges_s << " CKD edges/s\n"
                  << "  Throughput vs this single CPU implementation: BIP39 " << metrics.bip39_throughput_speedup
                  << "x; BIP32 " << metrics.bip32_throughput_speedup << "x\n";

        if (options.write_json) {
            write_metrics_json(metrics, options.json_path);
            std::cout << "Metrics JSON: " << std::filesystem::absolute(options.json_path).string() << '\n';
        }

        const bool pass = metrics.cpu_bip39_pass && metrics.cpu_bip32_pass && metrics.gpu_bip39_pass &&
                          metrics.gpu_bip32_pass && metrics.repeatability_pass;
        std::cout << "\nOVERALL CONFORMANCE: " << (pass ? "PASS" : "FAIL") << '\n';
        return pass ? 0 : 2;
    } catch (const std::exception& error) {
        std::cerr << "ERROR: " << error.what() << '\n';
        return 1;
    }
}
