#include "seeded_uglut2_traversal.hpp"
#include "ugtc4d_decoder.hpp"
#include "yuv_seed_capture.hpp"

#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

#ifndef UGTC4D_FIXTURE_PATH
#error UGTC4D_FIXTURE_PATH must name the independent UGTC4D fixture
#endif
#ifndef UGLUT2_FIXTURE_PATH
#error UGLUT2_FIXTURE_PATH must name the literal UGLUT2 fixture
#endif

namespace {

using ugts::chrono::ByteView;
using ugts::chrono::DenseYuv420p8Frame;
using ugts::chrono::Plane8View;
using ugts::chrono::Yuv420p8FrameView;
using ugts::chrono::YuvSeedCaptureAppendStats;
using ugts::chrono::YuvSeedCaptureProfile;
using ugts::chrono::YuvSeedCaptureReader;
using ugts::chrono::YuvSeedCaptureWriter;

void check(bool condition, const std::string& message) {
    if (!condition) throw std::runtime_error(message);
}

std::vector<std::uint8_t> readFile(const std::filesystem::path& path) {
    std::ifstream stream(path, std::ios::binary | std::ios::ate);
    check(stream.good(), "cannot open fixture: " + path.string());
    const auto end = stream.tellg();
    check(end >= 0, "cannot size fixture");
    std::vector<std::uint8_t> bytes(static_cast<std::size_t>(end));
    stream.seekg(0, std::ios::beg);
    stream.read(reinterpret_cast<char*>(bytes.data()),
                static_cast<std::streamsize>(bytes.size()));
    check(static_cast<std::size_t>(stream.gcount()) == bytes.size(),
          "fixture is truncated");
    return bytes;
}

std::uint64_t littleU64(const std::uint8_t* bytes) {
    std::uint64_t result = 0u;
    for (unsigned index = 0u; index < 8u; ++index) {
        result |= static_cast<std::uint64_t>(bytes[index]) << (index * 8u);
    }
    return result;
}

void appendU32(std::vector<std::uint8_t>& bytes, std::uint32_t value) {
    for (unsigned index = 0u; index < 4u; ++index) {
        bytes.push_back(static_cast<std::uint8_t>(value >> (index * 8u)));
    }
}

void appendU64(std::vector<std::uint8_t>& bytes, std::uint64_t value) {
    for (unsigned index = 0u; index < 8u; ++index) {
        bytes.push_back(static_cast<std::uint8_t>(value >> (index * 8u)));
    }
}

DenseYuv420p8Frame makeFrame(std::uint32_t width, std::uint32_t height) {
    DenseYuv420p8Frame frame{};
    frame.width = width;
    frame.height = height;
    frame.sensorTimestampNs = 1'000'000'000ll;
    frame.frameNumber = 700;
    frame.y.resize(static_cast<std::size_t>(width) * height);
    frame.u.resize(static_cast<std::size_t>(width / 2u) * (height / 2u));
    frame.v.resize(frame.u.size());
    for (std::uint32_t y = 0u; y < height; ++y) {
        for (std::uint32_t x = 0u; x < width; ++x) {
            frame.y[static_cast<std::size_t>(y) * width + x] =
                static_cast<std::uint8_t>((x * 29u + y * 47u + 17u) & 255u);
        }
    }
    for (std::size_t index = 0u; index < frame.u.size(); ++index) {
        frame.u[index] = static_cast<std::uint8_t>((index * 31u + 53u) & 255u);
        frame.v[index] = static_cast<std::uint8_t>((index * 67u + 101u) & 255u);
    }
    frame.canonicalMetadata = {1u, 0u, 8u, 0u, 0x34u, 0x12u, 0xa5u};
    return frame;
}

struct StridedFrame {
    std::vector<std::uint8_t> y;
    std::vector<std::uint8_t> u;
    std::vector<std::uint8_t> v;
    Yuv420p8FrameView view{};
};

std::vector<std::uint8_t> stridePlane(
    const std::vector<std::uint8_t>& dense,
    std::uint32_t width,
    std::uint32_t height,
    std::uint32_t rowStride,
    std::uint32_t pixelStride
) {
    std::vector<std::uint8_t> result(static_cast<std::size_t>(rowStride) * height, 0xcdu);
    for (std::uint32_t y = 0u; y < height; ++y) {
        for (std::uint32_t x = 0u; x < width; ++x) {
            result[static_cast<std::size_t>(y) * rowStride +
                   static_cast<std::size_t>(x) * pixelStride] =
                dense[static_cast<std::size_t>(y) * width + x];
        }
    }
    return result;
}

StridedFrame strided(const DenseYuv420p8Frame& frame) {
    StridedFrame result{};
    const auto yRow = frame.width * 2u + 7u;
    const auto cWidth = frame.width / 2u;
    const auto cHeight = frame.height / 2u;
    const auto cRow = cWidth * 2u + 5u;
    result.y = stridePlane(frame.y, frame.width, frame.height, yRow, 2u);
    result.u = stridePlane(frame.u, cWidth, cHeight, cRow, 2u);
    result.v = stridePlane(frame.v, cWidth, cHeight, cRow, 2u);
    result.view.sensorTimestampNs = frame.sensorTimestampNs;
    result.view.frameNumber = frame.frameNumber;
    result.view.y = Plane8View{result.y.data(), result.y.size(), yRow, 2u};
    result.view.u = Plane8View{result.u.data(), result.u.size(), cRow, 2u};
    result.view.v = Plane8View{result.v.data(), result.v.size(), cRow, 2u};
    result.view.canonicalMetadata = ByteView{
        frame.canonicalMetadata.data(), frame.canonicalMetadata.size()};
    return result;
}

std::vector<std::uint8_t> canonicalOwnerResidual(
    const DenseYuv420p8Frame& current,
    const DenseYuv420p8Frame* previous,
    const std::vector<std::uint32_t>& traversal
) {
    const auto subtract = [](std::uint8_t value, std::uint8_t base) {
        return static_cast<std::uint8_t>(static_cast<unsigned>(value) - base);
    };
    std::vector<std::uint8_t> result;
    result.reserve(current.y.size() + current.u.size() + current.v.size());
    const auto chromaWidth = current.width / 2u;
    for (const auto address : traversal) {
        const auto x = address % current.width;
        const auto y = address / current.width;
        result.push_back(subtract(
            current.y[address], previous == nullptr ? 0u : previous->y[address]));
        if ((x & 1u) == 0u && (y & 1u) == 0u) {
            const auto chroma =
                static_cast<std::size_t>(y / 2u) * chromaWidth + x / 2u;
            result.push_back(subtract(
                current.u[chroma], previous == nullptr ? 0u : previous->u[chroma]));
            result.push_back(subtract(
                current.v[chroma], previous == nullptr ? 0u : previous->v[chroma]));
        }
    }
    check(result.size() == current.y.size() + current.u.size() + current.v.size(),
          "independent canonical residual lane count mismatch");
    return result;
}

void checkFrame(
    const DenseYuv420p8Frame& actual,
    const DenseYuv420p8Frame& expected
) {
    check(actual.width == expected.width && actual.height == expected.height,
          "decoded dimensions changed");
    check(actual.sensorTimestampNs == expected.sensorTimestampNs &&
              actual.frameNumber == expected.frameNumber,
          "decoded camera chronology changed");
    check(actual.y == expected.y && actual.u == expected.u && actual.v == expected.v,
          "decoded dense camera planes changed");
    check(actual.canonicalMetadata == expected.canonicalMetadata,
          "decoded canonical metadata changed");
}

template <class Action>
void checkThrows(Action&& action, const std::string& label) {
    try {
        action();
    } catch (const std::exception&) {
        return;
    }
    throw std::runtime_error(label + " did not fail closed");
}

struct TempFiles {
    std::vector<std::filesystem::path> paths;
    ~TempFiles() {
        for (const auto& path : paths) {
            std::error_code ignored;
            std::filesystem::remove(path, ignored);
        }
    }
};

} // namespace

int main() {
    try {
        const auto started = std::chrono::steady_clock::now();
        const auto lut = readFile(UGLUT2_FIXTURE_PATH);
        const std::string authority = "UGTC4D native C++17 fixture authority v1";
        const auto authoritySha = ugts::chrono::sha256(
            reinterpret_cast<const std::uint8_t*>(authority.data()), authority.size());
        const auto rootSeed = littleU64(authoritySha.data());

        const auto tinyTraversal = ugts::chrono::regenerateSeededUglut2Traversal(
            8u, 6u, rootSeed, 1u, lut);
        const auto existing = ugts::chrono::Ugtc4dDecoder::fromFile(UGTC4D_FIXTURE_PATH);
        check(tinyTraversal.polarOrdinalToCartesian == existing.traversal(),
              "standalone UGLUT2 traversal differs from UGTC4D oracle");

        check(ugts::chrono::gsp4Mix32(0u) == 0u &&
                  ugts::chrono::gsp4Mix32(1u) == 0x688990c0u,
              "GSP4 mix32 vector mismatch");
        const auto lineage = ugts::chrono::gsp4CodewordLineage(
            0x0123456789abcdefull, 1u, 17u, 3u);
        check(lineage.lineageSeed == 1448769291u && lineage.routedHash == 1452375230u,
              "GSP4 Python/C++ lineage vector mismatch");

        constexpr std::uint32_t Width = 320u;
        constexpr std::uint32_t Height = 180u;
        auto frame0 = makeFrame(Width, Height);
        auto frame1 = frame0;
        frame1.sensorTimestampNs += 33'333'333ll;
        frame1.frameNumber += 1;
        frame1.canonicalMetadata.back() ^= 0x11u;
        auto frame2 = frame1;
        frame2.sensorTimestampNs += 33'333'333ll;
        frame2.frameNumber += 1;
        frame2.y[0] += 1u;
        frame2.y[1000] += 3u;
        frame2.y.back() -= 1u;
        frame2.u[5] += 7u;
        frame2.v[7] -= 9u;
        frame2.canonicalMetadata.back() ^= 0x22u;
        auto frame3 = frame2;
        frame3.sensorTimestampNs += 33'333'333ll;
        frame3.frameNumber += 1;
        for (std::size_t index = 0u; index < frame3.y.size(); index += 4u) {
            frame3.y[index] += 1u;
        }
        frame3.canonicalMetadata.back() ^= 0x44u;
        const std::vector<DenseYuv420p8Frame> expected{frame0, frame1, frame2, frame3};

        std::vector<std::uint8_t> independentPreimage;
        appendU64(independentPreimage, static_cast<std::uint64_t>(frame0.sensorTimestampNs));
        appendU32(independentPreimage, Width);
        appendU32(independentPreimage, Height);
        independentPreimage.insert(independentPreimage.end(), frame0.y.begin(), frame0.y.end());
        independentPreimage.insert(independentPreimage.end(), frame0.u.begin(), frame0.u.end());
        independentPreimage.insert(independentPreimage.end(), frame0.v.begin(), frame0.v.end());
        check(ugts::chrono::preSubstrateFrameSha256(frame0) ==
                  ugts::chrono::sha256(independentPreimage.data(), independentPreimage.size()),
              "pre-substrate digest serialization mismatch");

        const auto unique = std::to_string(
            std::chrono::high_resolution_clock::now().time_since_epoch().count());
        const auto base = std::filesystem::temp_directory_path() /
                          ("ugyuvs1_native_" + unique);
        const auto partial = base.string() + ".ugsp4c.partial";
        const auto final = base.string() + ".ugsp4c";
        const auto crashPartial = base.string() + "_crash.ugsp4c.partial";
        const auto corrupt = base.string() + "_corrupt.ugsp4c";
        const auto tailed = base.string() + "_tail.ugsp4c";
        const auto singlePartial = base.string() + "_single.ugsp4c.partial";
        const auto singleFinal = base.string() + "_single.ugsp4c";
        const auto multiPartial = base.string() + "_multi.ugsp4c.partial";
        const auto multiFinal = base.string() + "_multi.ugsp4c";
        const auto preparedPartial = base.string() + "_prepared.ugsp4c.partial";
        const auto preparedFinal = base.string() + "_prepared.ugsp4c";
        const auto invalidPartial = base.string() + "_invalid.ugsp4c.partial";
        TempFiles cleanup{{
            partial,
            final,
            crashPartial,
            corrupt,
            tailed,
            singlePartial,
            singleFinal,
            multiPartial,
            multiFinal,
            preparedPartial,
            preparedFinal,
            invalidPartial,
        }};

        YuvSeedCaptureProfile profile{};
        profile.width = Width;
        profile.height = Height;
        profile.checkpointInterval = 10u;
        profile.rootSeed = rootSeed;
        profile.traversalRecipeSeed = 1u;
        profile.literalUglut2 = lut;

        std::vector<YuvSeedCaptureAppendStats> stats;
        auto writer = YuvSeedCaptureWriter::createPartial(partial, profile);
        for (const auto& frame : expected) {
            auto source = strided(frame);
            stats.push_back(writer->append(source.view));
        }
        check(stats[0].denseBlockCount == 1u && stats[0].noveltyEventCount > 80'000u,
              "checkpoint did not select dense exact storage");
        check(stats[1].zeroBlockCount == 1u && stats[1].noveltyEventCount == 0u &&
                  stats[1].noveltyPayloadBytes == 192u,
              "negative memory stored a mask or residual payload");
        check(stats[2].sparseGapBlockCount == 1u && stats[2].noveltyEventCount == 5u,
              "isolated novelty did not select sparse gaps");
        check(stats[3].sparseBitmaskBlockCount == 1u &&
                  stats[3].noveltyEventCount == frame3.y.size() / 4u,
              "distributed novelty did not select sparse bitmask");
        check(std::filesystem::exists(partial),
              "writer partial disappeared before committed-prefix replay");

        {
            YuvSeedCaptureReader live(partial);
            check(live.inspection().recoveredIncomplete &&
                      live.inspection().committedFrames == expected.size(),
                  "live partial did not expose its committed prefix");
            const auto frames = live.decodeAll();
            check(frames.size() == expected.size(), "live partial frame count changed");
            for (std::size_t index = 0u; index < frames.size(); ++index) {
                checkFrame(frames[index], expected[index]);
            }
        }
        writer->finalize(final);
        YuvSeedCaptureReader reader(final);
        check(reader.inspection().finalized && !reader.inspection().recoveredIncomplete &&
                  reader.inspection().uncommittedTailBytes == 0u &&
                  reader.inspection().committedBytes == std::filesystem::file_size(final),
              "FINAL gate/inspection mismatch");
        const auto decoded = reader.decodeAll();
        check(decoded.size() == expected.size(), "final replay frame count changed");
        for (std::size_t index = 0u; index < decoded.size(); ++index) {
            checkFrame(decoded[index], expected[index]);
        }
        const auto expanded = ugts::chrono::expandUgcode24_420(decoded.front());
        const auto address = static_cast<std::size_t>(1u) * Width + 1u;
        check(expanded[address * 3u] == frame0.y[address] &&
                  expanded[address * 3u + 1u] == frame0.u[0] &&
                  expanded[address * 3u + 2u] == frame0.v[0],
              "expanded UGCODE24-420 sharing changed");

        auto parityProfile = profile;
        parityProfile.noveltyBlockLumaAddresses = 4096u;
        const auto parityTraversal = ugts::chrono::regenerateSeededUglut2Traversal(
            Width,
            Height,
            parityProfile.rootSeed,
            parityProfile.traversalRecipeSeed,
            parityProfile.literalUglut2).polarOrdinalToCartesian;
        const auto encodeParity = [&expected, &parityTraversal](
            const YuvSeedCaptureProfile& runProfile,
            const std::string& runPartial,
            const std::string& runFinal,
            bool usePrepared,
            std::vector<YuvSeedCaptureAppendStats>& runStats
        ) {
            auto runWriter = YuvSeedCaptureWriter::createPartial(
                runPartial, runProfile);
            for (std::size_t index = 0u; index < expected.size(); ++index) {
                auto source = strided(expected[index]);
                if (usePrepared) {
                    const auto checkpoint =
                        (index % runProfile.checkpointInterval) == 0u;
                    const auto residual = canonicalOwnerResidual(
                        expected[index],
                        checkpoint ? nullptr : &expected[index - 1u],
                        parityTraversal);
                    runStats.push_back(runWriter->appendPreparedResidual(
                        source.view,
                        ByteView{residual.data(), residual.size()}));
                } else {
                    runStats.push_back(runWriter->append(source.view));
                }
            }
            runWriter->finalize(runFinal);
            return readFile(runFinal);
        };

        auto singleProfile = parityProfile;
        singleProfile.noveltyWorkerCount = 1u;
        singleProfile.noveltyMaxInFlightBlocks = 3u;
        std::vector<YuvSeedCaptureAppendStats> singleStats;
        const auto singleBytes = encodeParity(
            singleProfile, singlePartial, singleFinal, false, singleStats);

        auto multiProfile = parityProfile;
        multiProfile.noveltyWorkerCount = 4u;
        multiProfile.noveltyMaxInFlightBlocks = 8u;
        std::vector<YuvSeedCaptureAppendStats> multiStats;
        const auto multiBytes = encodeParity(
            multiProfile, multiPartial, multiFinal, false, multiStats);
        std::vector<YuvSeedCaptureAppendStats> preparedStats;
        const auto preparedBytes = encodeParity(
            multiProfile, preparedPartial, preparedFinal, true, preparedStats);
        check(singleBytes == multiBytes,
              "worker_count=1 and worker_count=4 finalized bytes differ");
        check(singleBytes == preparedBytes,
              "CPU and prepared canonical residual finalized bytes differ");
        check(multiStats.front().noveltyWorkerCount == 4u &&
                  multiStats.front().noveltyMaxInFlightBlocks == 8u &&
                  multiStats.front().denseBlockCount == 15u,
              "bounded multi-worker append stats/configuration mismatch");

        auto invalidProfile = parityProfile;
        invalidProfile.noveltyWorkerCount = 4u;
        invalidProfile.noveltyMaxInFlightBlocks = 3u;
        checkThrows(
            [&invalidPartial, &invalidProfile] {
                YuvSeedCaptureWriter::createPartial(invalidPartial, invalidProfile);
            },
            "in-flight bound smaller than worker count");
        {
            auto invalidWriter = YuvSeedCaptureWriter::createPartial(
                invalidPartial, multiProfile);
            auto source = strided(frame0);
            auto shortResidual = canonicalOwnerResidual(
                frame0, nullptr, parityTraversal);
            shortResidual.pop_back();
            checkThrows(
                [&invalidWriter, &source, &shortResidual] {
                    invalidWriter->appendPreparedResidual(
                        source.view,
                        ByteView{shortResidual.data(), shortResidual.size()});
                },
                "short prepared canonical residual");
        }

        {
            auto crashWriter = YuvSeedCaptureWriter::createPartial(crashPartial, profile);
            auto source = strided(frame0);
            crashWriter->append(source.view);
        }
        {
            std::ofstream tail(crashPartial, std::ios::binary | std::ios::app);
            const std::vector<std::uint8_t> garbage(37u, 0xeeu);
            tail.write(reinterpret_cast<const char*>(garbage.data()),
                       static_cast<std::streamsize>(garbage.size()));
        }
        YuvSeedCaptureReader recovered(crashPartial);
        check(recovered.inspection().recoveredIncomplete &&
                  recovered.inspection().committedFrames == 1u &&
                  recovered.inspection().uncommittedTailBytes == 37u,
              "crash recovery did not isolate the committed prefix");
        checkFrame(recovered.decodeAll().front(), frame0);

        std::filesystem::copy_file(final, corrupt);
        {
            std::fstream file(corrupt, std::ios::binary | std::ios::in | std::ios::out);
            file.seekg(704 + 384 + 192 + 13, std::ios::beg);
            char value = 0;
            file.read(&value, 1);
            file.seekp(704 + 384 + 192 + 13, std::ios::beg);
            value ^= 0x5a;
            file.write(&value, 1);
        }
        checkThrows([&corrupt] { YuvSeedCaptureReader(corrupt).decodeAll(); },
                    "payload corruption");
        std::filesystem::copy_file(final, tailed);
        {
            std::ofstream tail(tailed, std::ios::binary | std::ios::app);
            tail.put(static_cast<char>(0x55));
        }
        checkThrows([&tailed] { YuvSeedCaptureReader invalid(tailed); },
                    "FINAL trailing bytes");

        std::uint64_t events = 0u;
        for (const auto& item : stats) events += item.noveltyEventCount;
        const auto finalBytes = readFile(final);
        const auto finalSha = ugts::chrono::sha256(finalBytes.data(), finalBytes.size());
        const auto paritySha = ugts::chrono::sha256(
            multiBytes.data(), multiBytes.size());
        check(events == 100469u && finalBytes.size() == 114845u,
              "deterministic fixture counts/size changed");
        check(ugts::chrono::sha256Hex(finalSha) ==
                  "22ac87ed1ffeecd50b7eb2609ac8326ec002e0414cc0d3c3dd940271446216d1" &&
                  ugts::chrono::sha256Hex(stats[0].preSubstrateSha256) ==
                  "eccb2f605f75783d5d128b673796f87e58c185ad364f256c464c2c0f291633f0",
              "deterministic fixture SHA-256 changed");
        const auto elapsed = std::chrono::duration<double>(
            std::chrono::steady_clock::now() - started).count();
        std::cout << "UGYUVS1_NATIVE_PASS"
                  << " frames=" << decoded.size()
                  << " authoritative_bytes_per_frame="
                  << (frame0.y.size() + frame0.u.size() + frame0.v.size())
                  << " file_bytes=" << finalBytes.size()
                  << " novelty_events=" << events
                  << " zero_frame_payload_bytes=" << stats[1].noveltyPayloadBytes
                  << " parity_workers=" << multiStats.front().noveltyWorkerCount
                  << " parity_max_in_flight="
                  << multiStats.front().noveltyMaxInFlightBlocks
                  << " cpu_prepared_parity_sha256="
                  << ugts::chrono::sha256Hex(paritySha)
                  << " file_sha256="
                  << ugts::chrono::sha256Hex(finalSha)
                  << " frame0_pre_sha256="
                  << ugts::chrono::sha256Hex(stats[0].preSubstrateSha256)
                  << " seconds=" << elapsed << '\n';
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "UGYUVS1_NATIVE_FAIL: " << error.what() << '\n';
        return 1;
    }
}
