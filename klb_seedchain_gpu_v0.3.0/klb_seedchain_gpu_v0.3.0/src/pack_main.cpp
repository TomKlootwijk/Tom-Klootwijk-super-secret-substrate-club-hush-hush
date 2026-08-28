#include "klb/format.hpp"
#include "klb/ply.hpp"

#include <cstdlib>
#include <filesystem>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {

struct Options {
    float log_k = 15.0f;
    std::size_t points = 262144u;
    std::filesystem::path decoded_path;
};

[[noreturn]] void usage(const char* executable, int exit_code) {
    std::ostream& out = exit_code == 0 ? std::cout : std::cerr;
    out << "KLB37 packer / PLY adapter\n\n"
        << "Usage:\n"
        << "  " << executable << " pack <input.ply> <output.klb> [--log-k 15] [--decoded roundtrip.ply]\n"
        << "  " << executable << " generate <output.klb> [--points 262144] [--log-k 15] [--decoded preview.ply]\n"
        << "  " << executable << " inspect <input.klb> [--decoded output.ply]\n\n"
        << "The pack command reads ASCII, binary-little-endian, or binary-big-endian PLY vertices.\n"
        << "Faces and other properties are deliberately ignored: this benchmark tests point packing,\n"
        << "not general mesh compression.\n";
    std::exit(exit_code);
}

std::size_t parse_size(std::string_view text, const char* name) {
    std::size_t consumed = 0;
    const unsigned long long value = std::stoull(std::string(text), &consumed, 10);
    if (consumed != text.size() || value == 0u) {
        throw std::invalid_argument(std::string(name) + " must be a positive integer");
    }
    return static_cast<std::size_t>(value);
}

float parse_float(std::string_view text, const char* name) {
    std::size_t consumed = 0;
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
        if (arg == "--log-k") {
            if (++i >= argc) {
                throw std::invalid_argument("--log-k requires a value");
            }
            options.log_k = parse_float(argv[i], "--log-k");
        } else if (arg == "--points") {
            if (++i >= argc) {
                throw std::invalid_argument("--points requires a value");
            }
            options.points = parse_size(argv[i], "--points");
        } else if (arg == "--decoded") {
            if (++i >= argc) {
                throw std::invalid_argument("--decoded requires a path");
            }
            options.decoded_path = argv[i];
        } else if (arg == "--help" || arg == "-h") {
            usage(argv[0], 0);
        } else {
            throw std::invalid_argument("unknown option: " + arg);
        }
    }
    return options;
}

void print_stats(const klb::PackedData& packed, const std::filesystem::path& path) {
    std::error_code error;
    const std::uint64_t actual_bytes = std::filesystem::file_size(path, error);
    const klb::PackStats stats = klb::inspect_packed(packed, error ? 0u : actual_bytes);
    const double scale = packed.header.radius_scale;

    std::cout << std::fixed << std::setprecision(6)
              << "records                 : " << stats.input_points << '\n'
              << "padded records          : " << stats.padded_points << '\n'
              << "record width            : " << packed.header.record_bits << " bits\n"
              << "payload bytes           : " << stats.payload_bytes << '\n'
              << "container bytes         : " << stats.file_bytes << '\n'
              << "payload bytes/point     : " << stats.bytes_per_point << '\n'
              << "container ratio/float3  : " << stats.ratio_vs_float3 << "x\n"
              << "RMS position error      : " << stats.rms_error
              << " (" << (scale > 0.0 ? 100.0 * stats.rms_error / scale : 0.0) << "% of radius)\n"
              << "max position error      : " << stats.max_error
              << " (" << (scale > 0.0 ? 100.0 * stats.max_error / scale : 0.0) << "% of radius)\n"
              << "payload FNV-1a          : 0x" << std::hex << packed.header.payload_hash << std::dec << '\n';
    if (stats.source_bytes != 0u) {
        std::cout << "source file bytes       : " << stats.source_bytes << '\n'
                  << "source/container ratio  : " << stats.ratio_vs_source_file
                  << "x (not mesh-equivalent; faces are omitted)\n";
    }
}

} // namespace

int main(int argc, char** argv) {
    try {
        if (argc < 2) {
            usage(argv[0], 2);
        }
        const std::string command = argv[1];
        if (command == "--help" || command == "-h" || command == "help") {
            usage(argv[0], 0);
        }

        if (command == "pack") {
            if (argc < 4) {
                usage(argv[0], 2);
            }
            const std::filesystem::path input_path = argv[2];
            const std::filesystem::path output_path = argv[3];
            const Options options = parse_options(argc, argv, 4);

            std::cout << "Reading PLY vertices: " << input_path << '\n';
            const std::vector<klb::Vec3> points = klb::read_ply_vertices(input_path);
            const std::uint64_t source_bytes = std::filesystem::file_size(input_path);
            std::cout << "Packing " << points.size() << " vertices...\n";
            klb::PackedData packed = klb::pack_points(points, source_bytes, options.log_k);
            klb::save_packed(output_path, packed);
            std::cout << "Wrote: " << output_path << '\n';
            print_stats(packed, output_path);

            if (!options.decoded_path.empty()) {
                klb::write_ply_vertices_ascii(options.decoded_path, klb::unpack_points(packed));
                std::cout << "Wrote decoded point preview: " << options.decoded_path << '\n';
            }
            return 0;
        }

        if (command == "generate") {
            if (argc < 3) {
                usage(argv[0], 2);
            }
            const std::filesystem::path output_path = argv[2];
            const Options options = parse_options(argc, argv, 3);
            std::cout << "Generating " << options.points << " parity-bifurcated L-system points...\n";
            const std::vector<klb::Vec3> points = klb::generate_lsystem_points(options.points);
            klb::PackedData packed = klb::pack_points(points, 0u, options.log_k);
            klb::save_packed(output_path, packed);
            std::cout << "Wrote: " << output_path << '\n';
            print_stats(packed, output_path);

            if (!options.decoded_path.empty()) {
                klb::write_ply_vertices_ascii(options.decoded_path, klb::unpack_points(packed));
                std::cout << "Wrote decoded point preview: " << options.decoded_path << '\n';
            }
            return 0;
        }

        if (command == "inspect") {
            if (argc < 3) {
                usage(argv[0], 2);
            }
            const std::filesystem::path input_path = argv[2];
            const Options options = parse_options(argc, argv, 3);
            const klb::PackedData packed = klb::load_packed(input_path);
            print_stats(packed, input_path);
            if (!options.decoded_path.empty()) {
                klb::write_ply_vertices_ascii(options.decoded_path, klb::unpack_points(packed));
                std::cout << "Wrote decoded point preview: " << options.decoded_path << '\n';
            }
            return 0;
        }

        throw std::invalid_argument("unknown command: " + command);
    } catch (const std::exception& error) {
        std::cerr << "error: " << error.what() << '\n';
        return 1;
    }
}

