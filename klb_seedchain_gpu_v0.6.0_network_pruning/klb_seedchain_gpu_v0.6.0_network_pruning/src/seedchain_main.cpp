#include "klb/ply.hpp"
#include "klb/seedchain.hpp"

#include <cmath>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {

struct Options {
    klb::SeedChainBuildOptions build{};
    klb::SeedChainSequenceOptions sequence{};
    float log_k = 15.0f;
    bool verify_sequence = true;
};

[[noreturn]] void usage(const char* executable, int exit_code) {
    std::ostream& out = exit_code == 0 ? std::cout : std::cerr;
    out << "KLB SeedChain: seed + finite grammar + sparse novelty deployment\n\n"
        << "Usage:\n"
        << "  " << executable << " create <base.klb> <output.klsc> [options]\n"
        << "  " << executable << " create-ply <input.ply> <output.klsc> [options]\n"
        << "  " << executable << " fit-sequence <frames.txt> <output.klsc> [options]\n"
        << "  " << executable << " inspect <input.klsc>\n"
        << "  " << executable << " verify-sequence <frames.txt> <input.klsc>\n"
        << "  " << executable << " export <input.klsc> <frame> <output.ply>\n\n"
        << "Build options:\n"
        << "  --frames N                 Generated chain nodes/frames (default 240)\n"
        << "  --checkpoint N             Snapshot interval, 1..64 (default 16)\n"
        << "  --fps X                    Frames per second (default 60)\n"
        << "  --seed N                   Root deterministic seed\n"
        << "  --branch-amplitude X       Generated deformation as base-radius ratio (default 0.0125)\n"
        << "  --novelty-rate X           Generated events per point per frame (default 0.001)\n"
        << "  --novelty-quantum X        Delta quantum as base-radius ratio (default 0.0001)\n"
        << "  --novelty-impulse X        Generated event amplitude as radius ratio (default 0.004)\n"
        << "  --novelty-lifetime N       Frames before generated inverse event (default 8)\n"
        << "  --residual-threshold X     Sequence residual cutoff as radius ratio (default 0.002)\n"
        << "  --log-k X                  PLY log-radius curve (default 15)\n"
        << "  --no-verify                Skip post-fit reconstruction error scan\n\n"
        << "fit-sequence expects one PLY path per line. Paths may be relative to frames.txt.\n"
        << "All frames must have identical vertex count and stable vertex order. The converter\n"
        << "fits a Y-axis similarity transform and stores sparse quantized residuals.\n\n"
        << "The PLY adapter accepts ASCII, binary-little-endian and binary-big-endian vertices.\n"
        << "Faces, normals, colors and materials are intentionally not encoded.\n";
    std::exit(exit_code);
}

std::uint64_t parse_u64(std::string_view text, const char* name) {
    std::size_t consumed = 0u;
    const std::uint64_t value = std::stoull(std::string(text), &consumed, 0);
    if (consumed != text.size()) {
        throw std::invalid_argument(std::string(name) + " must be an integer");
    }
    return value;
}

float parse_float(std::string_view text, const char* name) {
    std::size_t consumed = 0u;
    const float value = std::stof(std::string(text), &consumed);
    if (consumed != text.size() || !std::isfinite(value)) {
        throw std::invalid_argument(std::string(name) + " must be finite");
    }
    return value;
}

Options parse_options(int argc, char** argv, int start) {
    Options options{};
    for (int i = start; i < argc; ++i) {
        const std::string arg = argv[i];
        auto require_value = [&]() -> const char* {
            if (++i >= argc) {
                throw std::invalid_argument(arg + " requires a value");
            }
            return argv[i];
        };

        if (arg == "--frames") {
            options.build.frames = static_cast<std::uint32_t>(parse_u64(require_value(), "--frames"));
        } else if (arg == "--checkpoint") {
            const auto value = static_cast<std::uint32_t>(parse_u64(require_value(), "--checkpoint"));
            options.build.checkpoint_stride = value;
            options.sequence.checkpoint_stride = value;
        } else if (arg == "--fps") {
            const float value = parse_float(require_value(), "--fps");
            options.build.frames_per_second = value;
            options.sequence.frames_per_second = value;
        } else if (arg == "--seed") {
            const auto value = static_cast<std::uint32_t>(parse_u64(require_value(), "--seed"));
            options.build.seed = value;
            options.sequence.seed = value;
        } else if (arg == "--branch-amplitude") {
            options.build.branch_amplitude_ratio = parse_float(require_value(), "--branch-amplitude");
        } else if (arg == "--novelty-rate") {
            options.build.novelty_rate = parse_float(require_value(), "--novelty-rate");
        } else if (arg == "--novelty-quantum") {
            const float value = parse_float(require_value(), "--novelty-quantum");
            options.build.novelty_quantum_ratio = value;
            options.sequence.novelty_quantum_ratio = value;
        } else if (arg == "--novelty-impulse") {
            options.build.novelty_impulse_ratio = parse_float(require_value(), "--novelty-impulse");
        } else if (arg == "--novelty-lifetime") {
            options.build.novelty_lifetime =
                static_cast<std::uint32_t>(parse_u64(require_value(), "--novelty-lifetime"));
        } else if (arg == "--residual-threshold") {
            options.sequence.residual_threshold_ratio =
                parse_float(require_value(), "--residual-threshold");
        } else if (arg == "--log-k") {
            options.log_k = parse_float(require_value(), "--log-k");
            options.sequence.log_k = options.log_k;
        } else if (arg == "--no-verify") {
            options.verify_sequence = false;
        } else if (arg == "--help" || arg == "-h") {
            usage(argv[0], 0);
        } else {
            throw std::invalid_argument("unknown option: " + arg);
        }
    }
    return options;
}

std::vector<std::filesystem::path> read_frame_list(const std::filesystem::path& list_path) {
    std::ifstream input(list_path);
    if (!input) {
        throw std::runtime_error("failed to open frame list: " + list_path.string());
    }
    std::vector<std::filesystem::path> paths;
    std::string line;
    while (std::getline(input, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        const std::size_t first = line.find_first_not_of(" \t");
        if (first == std::string::npos || line[first] == '#') continue;
        const std::size_t last = line.find_last_not_of(" \t");
        std::filesystem::path path = line.substr(first, last - first + 1u);
        if (path.is_relative()) path = list_path.parent_path() / path;
        paths.push_back(path.lexically_normal());
    }
    if (paths.empty()) throw std::runtime_error("frame list contains no PLY paths");
    return paths;
}

std::vector<std::vector<klb::Vec3>> read_frames(
    const std::vector<std::filesystem::path>& frame_paths,
    std::uint64_t* source_bytes) {
    std::vector<std::vector<klb::Vec3>> frames;
    frames.reserve(frame_paths.size());
    std::uint64_t total_bytes = 0u;
    for (std::size_t i = 0u; i < frame_paths.size(); ++i) {
        std::cout << "Reading frame " << i << ": " << frame_paths[i] << '\n';
        frames.push_back(klb::read_ply_vertices(frame_paths[i]));
        total_bytes += std::filesystem::file_size(frame_paths[i]);
    }
    if (source_bytes != nullptr) *source_bytes = total_bytes;
    return frames;
}

void print_error_stats(const klb::SeedChainErrorStats& stats) {
    std::cout << std::fixed << std::setprecision(8)
              << "reconstruction RMS error    : " << stats.rms_error << '\n'
              << "reconstruction maximum error: " << stats.maximum_error << '\n'
              << "RMS / base radius          : " << (100.0 * stats.rms_error_over_radius) << "%\n"
              << "maximum / base radius      : " << (100.0 * stats.maximum_error_over_radius) << "%\n"
              << "worst frame / point        : " << stats.worst_frame << " / "
              << stats.worst_point << '\n';
}

void print_stats(const klb::SeedChainData& chain, const std::filesystem::path& path) {
    std::error_code error;
    const std::uint64_t actual_bytes = std::filesystem::file_size(path, error);
    const klb::SeedChainStats stats = klb::inspect_seedchain(chain, error ? 0u : actual_bytes);
    std::cout << std::fixed << std::setprecision(6)
              << "points                     : " << stats.points << '\n'
              << "frames / chain nodes       : " << stats.frames << '\n'
              << "checkpoint stride          : " << chain.header.checkpoint_stride << '\n'
              << "maximum linked depth       : " << stats.maximum_chain_depth << '\n'
              << "embedded base-word bytes  : " << stats.base_bytes << '\n'
              << "chain-node bytes           : " << stats.node_bytes << '\n'
              << "sparse novelty bytes       : " << stats.novelty_bytes << '\n'
              << "container bytes            : " << stats.file_bytes << '\n'
              << "bytes / point-frame        : " << stats.bytes_per_point_frame << '\n'
              << "ratio vs dense float3 seq  : " << stats.ratio_vs_float3_sequence << "x\n"
              << "ratio vs dense float4 seq  : " << stats.ratio_vs_float4_sequence << "x\n"
              << "novelty records / frame    : " << stats.novelty_records_per_frame << '\n'
              << "novelty record density     : " << (100.0 * stats.novelty_record_density)
              << "% of point-frames\n"
              << "base RMS quantization      : " << chain.header.base_header.rms_error << '\n'
              << "base maximum quantization  : " << chain.header.base_header.max_error << '\n'
              << "novelty quantum            : " << chain.header.novelty_quantum << '\n';
    if (chain.header.base_header.source_bytes != 0u) {
        std::cout << "base source-file bytes      : " << chain.header.base_header.source_bytes << '\n';
    }
    if (chain.header.source_sequence_bytes != 0u) {
        std::cout << "source sequence bytes       : " << chain.header.source_sequence_bytes << '\n'
                  << "ratio vs source sequence    : "
                  << (static_cast<double>(chain.header.source_sequence_bytes) /
                      static_cast<double>(stats.file_bytes)) << "x\n";
    }
    std::cout << "terminal chain hash        : 0x" << std::hex
              << chain.header.chain_hash << std::dec << '\n';
}

} // namespace

int main(int argc, char** argv) {
    try {
        if (argc < 2) usage(argv[0], 2);
        const std::string command = argv[1];
        if (command == "--help" || command == "-h" || command == "help") usage(argv[0], 0);

        if (command == "create") {
            if (argc < 4) usage(argv[0], 2);
            const std::filesystem::path input_path = argv[2];
            const std::filesystem::path output_path = argv[3];
            const Options options = parse_options(argc, argv, 4);
            const klb::PackedData base = klb::load_packed(input_path);
            std::cout << "Building hash-linked seed chain from: " << input_path << '\n';
            const klb::SeedChainData chain = klb::build_seedchain(base, options.build);
            klb::save_seedchain(output_path, chain);
            std::cout << "Wrote: " << output_path << '\n';
            print_stats(chain, output_path);
            return 0;
        }

        if (command == "create-ply") {
            if (argc < 4) usage(argv[0], 2);
            const std::filesystem::path input_path = argv[2];
            const std::filesystem::path output_path = argv[3];
            const Options options = parse_options(argc, argv, 4);
            std::cout << "Reading PLY vertices: " << input_path << '\n';
            const std::vector<klb::Vec3> points = klb::read_ply_vertices(input_path);
            const std::uint64_t source_bytes = std::filesystem::file_size(input_path);
            const klb::PackedData base = klb::pack_points(points, source_bytes, options.log_k);
            std::cout << "Building generated seed chain for " << points.size() << " vertices...\n";
            const klb::SeedChainData chain = klb::build_seedchain(base, options.build);
            klb::save_seedchain(output_path, chain);
            std::cout << "Wrote: " << output_path << '\n';
            print_stats(chain, output_path);
            return 0;
        }

        if (command == "fit-sequence") {
            if (argc < 4) usage(argv[0], 2);
            const std::filesystem::path list_path = argv[2];
            const std::filesystem::path output_path = argv[3];
            const Options options = parse_options(argc, argv, 4);
            const std::vector<std::filesystem::path> frame_paths = read_frame_list(list_path);
            std::uint64_t source_bytes = 0u;
            const std::vector<std::vector<klb::Vec3>> frames = read_frames(frame_paths, &source_bytes);
            std::cout << "Fitting Y-axis similarity predictors and sparse residual chain...\n";
            const klb::SeedChainData chain =
                klb::build_seedchain_sequence(frames, source_bytes, options.sequence);
            klb::save_seedchain(output_path, chain);
            std::cout << "Wrote: " << output_path << '\n';
            print_stats(chain, output_path);
            if (options.verify_sequence) {
                std::cout << "Validating reconstructed sequence against source PLY frames...\n";
                print_error_stats(klb::compare_seedchain_sequence(chain, frames));
            }
            return 0;
        }

        if (command == "inspect") {
            if (argc != 3) usage(argv[0], 2);
            const std::filesystem::path input_path = argv[2];
            const klb::SeedChainData chain = klb::load_seedchain(input_path);
            print_stats(chain, input_path);
            return 0;
        }

        if (command == "verify-sequence") {
            if (argc != 4) usage(argv[0], 2);
            const std::filesystem::path list_path = argv[2];
            const std::filesystem::path input_path = argv[3];
            const klb::SeedChainData chain = klb::load_seedchain(input_path);
            const std::vector<std::filesystem::path> frame_paths = read_frame_list(list_path);
            const std::vector<std::vector<klb::Vec3>> frames = read_frames(frame_paths, nullptr);
            print_error_stats(klb::compare_seedchain_sequence(chain, frames));
            return 0;
        }

        if (command == "export") {
            if (argc != 5) usage(argv[0], 2);
            const std::filesystem::path input_path = argv[2];
            const std::uint64_t frame64 = parse_u64(argv[3], "frame");
            if (frame64 > std::numeric_limits<std::uint32_t>::max()) {
                throw std::out_of_range("frame index exceeds uint32 range");
            }
            const std::filesystem::path output_path = argv[4];
            const klb::SeedChainData chain = klb::load_seedchain(input_path);
            const auto points = klb::reconstruct_seedchain_frame(
                chain, static_cast<std::uint32_t>(frame64));
            klb::write_ply_vertices_ascii(output_path, points);
            std::cout << "Reconstructed frame " << frame64 << " to: " << output_path << '\n';
            return 0;
        }

        throw std::invalid_argument("unknown command: " + command);
    } catch (const std::exception& error) {
        std::cerr << "error: " << error.what() << '\n';
        return 1;
    }
}
