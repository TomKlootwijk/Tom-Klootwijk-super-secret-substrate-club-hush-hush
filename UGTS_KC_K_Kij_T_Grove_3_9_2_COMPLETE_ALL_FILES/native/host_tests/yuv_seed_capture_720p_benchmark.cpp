#include "ugtc4d_decoder.hpp"
#include "yuv_seed_capture.hpp"

#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

#ifndef UGLUT2_FIXTURE_PATH
#error UGLUT2_FIXTURE_PATH must name the literal UGLUT2 fixture
#endif

namespace {

using Clock = std::chrono::steady_clock;
using ugts::chrono::ByteView;
using ugts::chrono::DenseYuv420p8Frame;
using ugts::chrono::Plane8View;
using ugts::chrono::Yuv420p8FrameView;
using ugts::chrono::YuvSeedCaptureProfile;
using ugts::chrono::YuvSeedCaptureWriter;

void check(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

std::vector<std::uint8_t> readFile(const std::filesystem::path& path) {
    std::ifstream stream(path, std::ios::binary | std::ios::ate);
    check(stream.good(), "cannot open benchmark dependency/output");
    const auto end = stream.tellg();
    check(end >= 0, "cannot size benchmark dependency/output");
    std::vector<std::uint8_t> result(static_cast<std::size_t>(end));
    stream.seekg(0, std::ios::beg);
    stream.read(reinterpret_cast<char*>(result.data()),
                static_cast<std::streamsize>(result.size()));
    check(static_cast<std::size_t>(stream.gcount()) == result.size(),
          "benchmark dependency/output is truncated");
    return result;
}

DenseYuv420p8Frame initialFrame() {
    constexpr std::uint32_t Width = 1280u;
    constexpr std::uint32_t Height = 720u;
    DenseYuv420p8Frame frame{};
    frame.width = Width;
    frame.height = Height;
    frame.sensorTimestampNs = 5'000'000'000ll;
    frame.frameNumber = 1000;
    frame.y.resize(static_cast<std::size_t>(Width) * Height);
    frame.u.resize(static_cast<std::size_t>(Width / 2u) * (Height / 2u));
    frame.v.resize(frame.u.size());
    for (std::uint32_t y = 0u; y < Height; ++y) {
        for (std::uint32_t x = 0u; x < Width; ++x) {
            frame.y[static_cast<std::size_t>(y) * Width + x] =
                static_cast<std::uint8_t>((x * 13u + y * 29u + (x ^ y) + 19u) & 255u);
        }
    }
    for (std::size_t index = 0u; index < frame.u.size(); ++index) {
        frame.u[index] = static_cast<std::uint8_t>((index * 17u + 71u) & 255u);
        frame.v[index] = static_cast<std::uint8_t>((index * 43u + 113u) & 255u);
    }
    frame.canonicalMetadata = {1u, 0u, 0x80u, 0x02u, 0xd0u, 0x02u};
    return frame;
}

Yuv420p8FrameView view(const DenseYuv420p8Frame& frame) {
    return Yuv420p8FrameView{
        frame.sensorTimestampNs,
        frame.frameNumber,
        Plane8View{frame.y.data(), frame.y.size(), frame.width, 1u},
        Plane8View{frame.u.data(), frame.u.size(), frame.width / 2u, 1u},
        Plane8View{frame.v.data(), frame.v.size(), frame.width / 2u, 1u},
        ByteView{frame.canonicalMetadata.data(), frame.canonicalMetadata.size()},
    };
}

double seconds(Clock::time_point first, Clock::time_point second) {
    return std::chrono::duration<double>(second - first).count();
}

} // namespace

int main() {
    std::filesystem::path partial;
    std::filesystem::path final;
    try {
        const auto lut = readFile(UGLUT2_FIXTURE_PATH);
        auto first = initialFrame();
        auto unchanged = first;
        unchanged.sensorTimestampNs += 33'333'333ll;
        unchanged.frameNumber += 1;
        auto sparse = unchanged;
        sparse.sensorTimestampNs += 33'333'333ll;
        sparse.frameNumber += 1;
        sparse.y[0] += 1u;
        sparse.y[123'456] -= 2u;
        sparse.y.back() += 3u;
        sparse.u[17] += 4u;
        sparse.v[19] -= 5u;

        const auto unique = std::to_string(
            std::chrono::high_resolution_clock::now().time_since_epoch().count());
        const auto base = std::filesystem::temp_directory_path() /
                          ("ugyuvs1_720p_" + unique);
        partial = base.string() + ".ugsp4c.partial";
        final = base.string() + ".ugsp4c";

        YuvSeedCaptureProfile profile{};
        profile.width = first.width;
        profile.height = first.height;
        profile.checkpointInterval = 300u;
        profile.rootSeed = 0x0123456789abcdefull;
        profile.traversalRecipeSeed = 1u;
        profile.literalUglut2 = lut;

        const auto createBegin = Clock::now();
        auto writer = YuvSeedCaptureWriter::createPartial(partial.string(), profile);
        const auto createEnd = Clock::now();
        const auto frame0Begin = Clock::now();
        const auto stats0 = writer->append(view(first));
        const auto frame0End = Clock::now();
        const auto stats1 = writer->append(view(unchanged));
        const auto frame1End = Clock::now();
        const auto stats2 = writer->append(view(sparse));
        const auto frame2End = Clock::now();
        writer->finalize(final.string());
        const auto finalEnd = Clock::now();

        const auto readBegin = Clock::now();
        const ugts::chrono::YuvSeedCaptureReader reader(final.string());
        const auto decoded = reader.decodeAll();
        const auto readEnd = Clock::now();
        check(decoded.size() == 3u, "720p replay frame count mismatch");
        check(decoded[0].y == first.y && decoded[0].u == first.u && decoded[0].v == first.v &&
                  decoded[1].y == unchanged.y && decoded[1].u == unchanged.u &&
                  decoded[1].v == unchanged.v && decoded[2].y == sparse.y &&
                  decoded[2].u == sparse.u && decoded[2].v == sparse.v,
              "720p dense plane replay mismatch");
        check(stats0.denseBlockCount == 15u &&
                  stats1.zeroBlockCount == 15u && stats1.noveltyEventCount == 0u &&
                  stats2.sparseGapBlockCount > 0u && stats2.noveltyEventCount == 5u,
              "720p novelty representation selection mismatch");

        const auto file = readFile(final);
        const auto fileSha = ugts::chrono::sha256Hex(
            ugts::chrono::sha256(file.data(), file.size()));
        check(stats0.frameRecordBytes == 1'385'670u &&
                  stats1.frameRecordBytes == 3'270u &&
                  stats2.frameRecordBytes == 3'287u &&
                  stats1.noveltyPayloadBytes == 2'880u &&
                  file.size() == 1'393'123u,
              "deterministic 720p sizes changed");
        check(fileSha ==
                  "63b51ae1228d6d36aeeb8ea8e76b3c8ba1793c8201e71f6484de61e9c7e7cdab",
              "deterministic 720p file SHA-256 changed");
        const auto authorityBytes = static_cast<double>(first.y.size() +
            first.u.size() + first.v.size());
        const auto toMibPerSecond = [authorityBytes](double elapsed) {
            return authorityBytes / (1024.0 * 1024.0) / elapsed;
        };
        std::cout << std::fixed << std::setprecision(6)
                  << "UGYUVS1_720P_PASS"
                  << " file_bytes=" << file.size()
                  << " checkpoint_record_bytes=" << stats0.frameRecordBytes
                  << " unchanged_record_bytes=" << stats1.frameRecordBytes
                  << " sparse_record_bytes=" << stats2.frameRecordBytes
                  << " unchanged_novelty_bytes=" << stats1.noveltyPayloadBytes
                  << " sparse_events=" << stats2.noveltyEventCount
                  << " create_seconds=" << seconds(createBegin, createEnd)
                  << " checkpoint_seconds=" << seconds(frame0Begin, frame0End)
                  << " unchanged_seconds=" << seconds(frame0End, frame1End)
                  << " sparse_seconds=" << seconds(frame1End, frame2End)
                  << " finalize_seconds=" << seconds(frame2End, finalEnd)
                  << " replay_seconds=" << seconds(readBegin, readEnd)
                  << " checkpoint_mib_s="
                  << toMibPerSecond(seconds(frame0Begin, frame0End))
                  << " unchanged_mib_s="
                  << toMibPerSecond(seconds(frame0End, frame1End))
                  << " sparse_mib_s="
                  << toMibPerSecond(seconds(frame1End, frame2End))
                  << " checkpoint_pre_sha256="
                  << ugts::chrono::sha256Hex(stats0.preSubstrateSha256)
                  << " unchanged_pre_sha256="
                  << ugts::chrono::sha256Hex(stats1.preSubstrateSha256)
                  << " sparse_pre_sha256="
                  << ugts::chrono::sha256Hex(stats2.preSubstrateSha256)
                  << " file_sha256=" << fileSha << '\n';
        std::error_code ignored;
        std::filesystem::remove(final, ignored);
        return 0;
    } catch (const std::exception& error) {
        std::error_code ignored;
        if (!partial.empty()) std::filesystem::remove(partial, ignored);
        if (!final.empty()) std::filesystem::remove(final, ignored);
        std::cerr << "UGYUVS1_720P_FAIL: " << error.what() << '\n';
        return 1;
    }
}
