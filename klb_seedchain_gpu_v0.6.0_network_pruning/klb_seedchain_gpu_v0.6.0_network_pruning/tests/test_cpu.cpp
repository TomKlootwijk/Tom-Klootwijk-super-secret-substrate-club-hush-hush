#include "klb/format.hpp"
#include "klb/ply.hpp"
#include "klb/seedchain.hpp"

#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

void expect(bool condition, const std::string& message) {
    if (!condition) {
        throw std::runtime_error("test failure: " + message);
    }
}

void test_swizzle() {
    for (std::uint64_t i = 0; i < 4096u; ++i) {
        const std::uint64_t swizzled = klb::xor_swizzle_16x16(i);
        expect(klb::xor_swizzle_16x16(swizzled) == i, "XOR swizzle must be self-inverse");
    }
}

void test_bitstream() {
    constexpr std::uint64_t kCount = 4096u;
    const std::uint64_t bits = kCount * klb::kRecordBits;
    std::vector<std::uint32_t> words(static_cast<std::size_t>((bits + 31u) / 32u + 2u), 0u);
    std::vector<std::uint64_t> codes(static_cast<std::size_t>(kCount));
    std::mt19937 rng(12345u);
    for (std::uint64_t i = 0; i < kCount; ++i) {
        const std::uint64_t code = klb::make_record_code(
            rng() & static_cast<std::uint32_t>(klb::kRhoMask),
            rng() & static_cast<std::uint32_t>(klb::kThetaMask),
            rng() & static_cast<std::uint32_t>(klb::kPhiMask),
            rng() & static_cast<std::uint32_t>(klb::kSymbolMask));
        codes[static_cast<std::size_t>(i)] = code;
        klb::write_bits37(words.data(), i, code);
    }
    for (std::uint64_t i = 0; i < kCount; ++i) {
        expect(klb::read_bits37(words.data(), i) == codes[static_cast<std::size_t>(i)],
               "37-bit read/write mismatch");
        expect(klb::record_has_even_parity(codes[static_cast<std::size_t>(i)]),
               "record parity must be even");
    }
}

void test_klein() {
    constexpr std::uint32_t width = 16u;
    constexpr std::uint32_t height = 9u;
    for (std::int64_t x = -40; x <= 40; ++x) {
        for (std::int64_t y = -20; y <= 20; ++y) {
            const std::uint64_t base = klb::klein_index(x, y, width, height);
            const std::uint64_t x_wrap = klb::klein_index(x + width, y, width, height);
            const std::uint64_t reflected = klb::klein_index((width - 1) - x, y, width, height);
            const std::uint64_t y_wrap = klb::klein_index(x, y + height, width, height);
            expect(base == x_wrap, "x seam must wrap periodically");
            expect(y_wrap == reflected, "y seam must reflect x");
        }
    }
}

void write_binary_ply(const std::filesystem::path& path) {
    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    out << "ply\n"
        << "format binary_little_endian 1.0\n"
        << "element vertex 3\n"
        << "property float x\n"
        << "property float y\n"
        << "property float z\n"
        << "element face 1\n"
        << "property list uchar int vertex_indices\n"
        << "end_header\n";
    const float vertices[9] = {0.0f, 0.0f, 0.0f, 1.0f, 2.0f, 3.0f, -1.0f, 0.5f, 4.0f};
    out.write(reinterpret_cast<const char*>(vertices), sizeof(vertices));
    const std::uint8_t count = 3u;
    const std::int32_t face[3] = {0, 1, 2};
    out.write(reinterpret_cast<const char*>(&count), sizeof(count));
    out.write(reinterpret_cast<const char*>(face), sizeof(face));
}

void test_ply(const std::filesystem::path& directory) {
    const std::vector<klb::Vec3> expected{{0.0f, 0.0f, 0.0f}, {1.0f, 2.0f, 3.0f}, {-1.0f, 0.5f, 4.0f}};
    const auto ascii_path = directory / "roundtrip_ascii.ply";
    klb::write_ply_vertices_ascii(ascii_path, expected);
    const std::vector<klb::Vec3> ascii = klb::read_ply_vertices(ascii_path);
    expect(ascii.size() == expected.size(), "ASCII PLY vertex count");

    const auto binary_path = directory / "sample_binary.ply";
    write_binary_ply(binary_path);
    const std::vector<klb::Vec3> binary = klb::read_ply_vertices(binary_path);
    expect(binary.size() == expected.size(), "binary PLY vertex count");
    for (std::size_t i = 0; i < expected.size(); ++i) {
        expect(std::abs(binary[i].x - expected[i].x) < 1.0e-7f, "binary PLY x");
        expect(std::abs(binary[i].y - expected[i].y) < 1.0e-7f, "binary PLY y");
        expect(std::abs(binary[i].z - expected[i].z) < 1.0e-7f, "binary PLY z");
    }
}

void test_pack_roundtrip(const std::filesystem::path& directory) {
    const std::vector<klb::Vec3> source = klb::generate_lsystem_points(8192u);
    klb::PackStats stats{};
    const klb::PackedData packed = klb::pack_points(source, 0u, 15.0f, &stats);
    expect(packed.header.record_count == source.size(), "packed record count");
    expect(packed.header.padded_count % klb::kTileRecords == 0u, "tile padding");
    expect(stats.ratio_vs_float3 > 2.0, "container should be smaller than float3 input");
    expect(stats.max_error < static_cast<double>(packed.header.radius_scale) * 0.01,
           "quantization max error should stay below 1% of radius");

    const auto path = directory / "test.klb";
    klb::save_packed(path, packed);
    const klb::PackedData loaded = klb::load_packed(path);
    expect(loaded.header.payload_hash == packed.header.payload_hash, "payload hash roundtrip");
    expect(klb::unpack_logical_codes(loaded) == klb::unpack_logical_codes(packed), "code roundtrip");
    expect(klb::unpack_points(loaded).size() == source.size(), "decoded point count");
}

void test_seedchain(const std::filesystem::path& directory) {
    const std::vector<klb::Vec3> source = klb::generate_lsystem_points(4096u);
    const klb::PackedData base = klb::pack_points(source, 0u, 15.0f);

    klb::SeedChainBuildOptions options{};
    options.frames = 33u;
    options.checkpoint_stride = 8u;
    options.novelty_rate = 0.004f;
    options.novelty_lifetime = 4u;
    const klb::SeedChainData chain = klb::build_seedchain(base, options);
    klb::validate_seedchain(chain, true);
    expect(chain.nodes.size() == options.frames, "seed-chain frame count");
    expect(chain.nodes[8].checkpoint_index == 8u, "seed-chain checkpoint index");
    expect((chain.nodes[8].flags & klb::kSeedNodeCheckpoint) != 0u, "checkpoint flag");
    expect(chain.nodes[15].depth_from_checkpoint == 7u, "checkpoint depth");

    const klb::SeedChainStats stats = klb::inspect_seedchain(chain);
    expect(stats.ratio_vs_float3_sequence > 10.0, "generated seed-chain compression ratio");
    expect(stats.maximum_chain_depth == 7u, "maximum chain depth");

    const auto frame0 = klb::reconstruct_seedchain_frame(chain, 0u);
    const auto frame32 = klb::reconstruct_seedchain_frame(chain, 32u);
    expect(frame0.size() == source.size(), "seed-chain frame 0 point count");
    expect(frame32.size() == source.size(), "seed-chain final point count");
    for (std::size_t i = 0; i < 32u; ++i) {
        expect(std::isfinite(frame32[i].x) && std::isfinite(frame32[i].y) && std::isfinite(frame32[i].z),
               "seed-chain reconstructed coordinates must be finite");
    }

    const auto path = directory / "test.klsc";
    klb::save_seedchain(path, chain);
    const klb::SeedChainData loaded = klb::load_seedchain(path);
    expect(loaded.header.chain_hash == chain.header.chain_hash, "seed-chain terminal hash roundtrip");
    expect(loaded.novelties.size() == chain.novelties.size(), "seed-chain novelty count roundtrip");
}

void test_fitted_sequence() {
    const std::vector<klb::Vec3> base = klb::generate_lsystem_points(1024u);
    std::vector<std::vector<klb::Vec3>> frames;
    frames.reserve(6u);
    for (std::uint32_t frame = 0u; frame < 6u; ++frame) {
        const float angle = 0.08f * static_cast<float>(frame);
        const float sine = std::sinf(angle);
        const float cosine = std::cosf(angle);
        const float scale = 1.0f + 0.01f * static_cast<float>(frame);
        std::vector<klb::Vec3> points;
        points.reserve(base.size());
        for (const klb::Vec3& p : base) {
            points.push_back({
                scale * (cosine * p.x - sine * p.z) + 0.02f * static_cast<float>(frame),
                scale * p.y - 0.01f * static_cast<float>(frame),
                scale * (sine * p.x + cosine * p.z) + 0.015f * static_cast<float>(frame),
            });
        }
        if (frame == 3u) {
            points[17].x += 0.04f;
            points[17].y -= 0.03f;
        }
        frames.push_back(std::move(points));
    }

    klb::SeedChainSequenceOptions options{};
    options.checkpoint_stride = 2u;
    options.residual_threshold_ratio = 0.002f;
    const klb::SeedChainData chain = klb::build_seedchain_sequence(frames, 123456u, options);
    expect(!chain.novelties.empty(), "fitted sequence should retain the external sparse edit");
    expect((chain.nodes[3].flags & klb::kSeedNodeExternalFit) != 0u, "external-fit node flag");
    expect(chain.header.source_sequence_bytes == 123456u, "source sequence byte accounting");
    expect(chain.header.base_header.source_bytes == 0u,
           "fitted base must not mislabel total sequence bytes as one base source file");

    const auto decoded = klb::reconstruct_seedchain_frame(chain, 3u);
    const float radius = chain.header.base_header.radius_scale;
    float max_error = 0.0f;
    for (std::size_t i = 0; i < decoded.size(); ++i) {
        max_error = std::max(max_error, klb::length(decoded[i] - frames[3][i]));
    }
    expect(max_error < radius * 0.006f, "fitted sequence reconstruction error budget");

    const klb::SeedChainErrorStats error_stats = klb::compare_seedchain_sequence(chain, frames);
    expect(error_stats.points == base.size(), "sequence verifier point count");
    expect(error_stats.frames == frames.size(), "sequence verifier frame count");
    expect(error_stats.maximum_error < radius * 0.006f, "sequence verifier maximum error budget");
}

} // namespace

int main() {
    try {
        const std::filesystem::path directory =
            std::filesystem::temp_directory_path() / "klb_cuda_arch_test_cpu";
        std::filesystem::remove_all(directory);
        std::filesystem::create_directories(directory);

        test_swizzle();
        test_bitstream();
        test_klein();
        test_ply(directory);
        test_pack_roundtrip(directory);
        test_seedchain(directory);
        test_fitted_sequence();

        std::filesystem::remove_all(directory);
        std::cout << "All CPU tests passed.\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}

