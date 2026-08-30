#include "full_substrate_camera.hpp"
#include "seeded_uglut2_traversal.hpp"
#include "yuv_seed_capture.hpp"

#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

#ifndef UGLUT2_FIXTURE_PATH
#error UGLUT2_FIXTURE_PATH must name the literal UGLUT2 fixture
#endif

namespace {

using namespace ugts::chrono;

void check(bool condition, const std::string& message) {
    if (!condition) throw std::runtime_error(message);
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

std::vector<std::uint8_t> readFile(const std::filesystem::path& path) {
    std::ifstream stream(path, std::ios::binary | std::ios::ate);
    check(stream.good(), "cannot open " + path.string());
    const auto end = stream.tellg();
    check(end >= 0, "cannot size " + path.string());
    std::vector<std::uint8_t> bytes(static_cast<std::size_t>(end));
    stream.seekg(0, std::ios::beg);
    stream.read(reinterpret_cast<char*>(bytes.data()),
                static_cast<std::streamsize>(bytes.size()));
    check(static_cast<std::size_t>(stream.gcount()) == bytes.size(),
          "short file read");
    return bytes;
}

std::uint64_t readU64(const std::uint8_t* bytes) {
    std::uint64_t value = 0u;
    for (unsigned index = 0u; index < 8u; ++index) {
        value |= static_cast<std::uint64_t>(bytes[index]) << (index * 8u);
    }
    return value;
}

DenseYuv420p8Frame makeFrame(
    std::uint32_t width,
    std::uint32_t height,
    std::uint32_t ordinal
) {
    DenseYuv420p8Frame frame{};
    frame.width = width;
    frame.height = height;
    frame.sensorTimestampNs = 7'000'000'000ll + ordinal * 41'666'667ll;
    frame.frameNumber = 9000 + ordinal;
    frame.y.resize(static_cast<std::size_t>(width) * height);
    frame.u.resize(static_cast<std::size_t>(width / 2u) * (height / 2u));
    frame.v.resize(frame.u.size());
    for (std::size_t address = 0u; address < frame.y.size(); ++address) {
        frame.y[address] = static_cast<std::uint8_t>(
            address * 37u + (address >> 3u) * 11u + ordinal * 19u);
    }
    for (std::size_t address = 0u; address < frame.u.size(); ++address) {
        frame.u[address] = static_cast<std::uint8_t>(
            address * 17u + ordinal * 31u + 53u);
        frame.v[address] = static_cast<std::uint8_t>(
            address * 43u + ordinal * 7u + 101u);
    }
    if (ordinal == 1u) {
        frame.y[7u] ^= 0x81u;
        frame.u[11u] += 3u;
    } else if (ordinal == 2u) {
        for (std::size_t address = 0u; address < frame.y.size(); address += 29u) {
            frame.y[address] += 1u;
        }
    } else if (ordinal == 4u) {
        for (auto& value : frame.v) value ^= 0x5au;
    }
    frame.canonicalMetadata = {
        2u, 0u, 12u, 0u,
        static_cast<std::uint8_t>(ordinal),
        static_cast<std::uint8_t>(ordinal * 13u),
    };
    return frame;
}

Yuv420p8FrameView viewOf(const DenseYuv420p8Frame& frame) {
    return Yuv420p8FrameView{
        frame.sensorTimestampNs,
        frame.frameNumber,
        {frame.y.data(), frame.y.size(), frame.width, 1u},
        {frame.u.data(), frame.u.size(), frame.width / 2u, 1u},
        {frame.v.data(), frame.v.size(), frame.width / 2u, 1u},
        {frame.canonicalMetadata.data(), frame.canonicalMetadata.size()},
    };
}

void checkFrame(
    const DenseYuv420p8Frame& actual,
    const DenseYuv420p8Frame& expected
) {
    check(actual.width == expected.width && actual.height == expected.height &&
              actual.sensorTimestampNs == expected.sensorTimestampNs &&
              actual.frameNumber == expected.frameNumber &&
              actual.y == expected.y && actual.u == expected.u &&
              actual.v == expected.v &&
              actual.canonicalMetadata == expected.canonicalMetadata,
          "profile-2 exact replay changed authoritative camera bytes");
}

struct PreparedFrame {
    std::vector<std::uint8_t> residual;
    Sha256Digest operatorStateSha{};
};

PreparedFrame prepare(
    const DenseYuv420p8Frame& current,
    const DenseYuv420p8Frame* previous,
    const YuvSeedCaptureProfile& profile,
    const SeededUglut2Traversal& traversal,
    std::uint32_t ordinal
) {
    std::vector<std::uint8_t> zeroY(current.y.size(), 0u);
    std::vector<std::uint8_t> zeroU(current.u.size(), 0u);
    std::vector<std::uint8_t> zeroV(current.v.size(), 0u);
    const auto& y = previous == nullptr ? zeroY : previous->y;
    const auto& u = previous == nullptr ? zeroU : previous->u;
    const auto& v = previous == nullptr ? zeroV : previous->v;
    const auto prediction = buildFullSubstrateCameraPrediction(
        current.width,
        current.height,
        profile.rootSeed,
        profile.traversalRecipeSeed,
        ordinal,
        traversal,
        {{y.data(), y.size()}, {u.data(), u.size()}, {v.data(), v.size()}},
        profile.noveltyBlockLumaAddresses);
    PreparedFrame result{};
    result.operatorStateSha = prediction.frameOperatorStateSha256;
    result.residual.reserve(current.y.size() + current.u.size() + current.v.size());
    const auto subtract = [](std::uint8_t value, std::uint8_t base) {
        return static_cast<std::uint8_t>(static_cast<unsigned>(value) - base);
    };
    auto lane = std::size_t{0u};
    const auto chromaWidth = current.width / 2u;
    for (const auto address : traversal.polarOrdinalToCartesian) {
        result.residual.push_back(subtract(
            current.y[address], prediction.canonicalOwnerPrediction[lane++]));
        const auto x = address % current.width;
        const auto yAddress = address / current.width;
        if ((x & 1u) == 0u && (yAddress & 1u) == 0u) {
            const auto chroma =
                static_cast<std::size_t>(yAddress / 2u) * chromaWidth + x / 2u;
            result.residual.push_back(subtract(
                current.u[chroma], prediction.canonicalOwnerPrediction[lane++]));
            result.residual.push_back(subtract(
                current.v[chroma], prediction.canonicalOwnerPrediction[lane++]));
        }
    }
    check(lane == prediction.canonicalOwnerPrediction.size() &&
              result.residual.size() == lane,
          "prepared profile-2 owner stream length changed");
    return result;
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

int main(int argc, char** argv) {
    try {
        constexpr std::uint32_t Width = 96u;
        constexpr std::uint32_t Height = 64u;
        const auto lut = readFile(UGLUT2_FIXTURE_PATH);
        std::vector<DenseYuv420p8Frame> frames;
        for (std::uint32_t ordinal = 0u; ordinal < 5u; ++ordinal) {
            frames.push_back(makeFrame(Width, Height, ordinal));
        }

        YuvSeedCaptureProfile profile{};
        profile.logicalProfile = FullSubstrateCameraProfile;
        profile.width = Width;
        profile.height = Height;
        profile.checkpointInterval = 3u;
        profile.noveltyBlockLumaAddresses = 257u;
        profile.rootSeed = 0x0123456789abcdefull;
        // Non-default recipe proves profile 2 binds, rather than hard-codes,
        // the full uint64 GSP4/traversal recipe seed.
        profile.traversalRecipeSeed = 0xfedcba9876543210ull;
        profile.literalUglut2 = lut;
        const auto traversal = regenerateSeededUglut2Traversal(
            Width, Height, profile.rootSeed, profile.traversalRecipeSeed, lut);

        const auto unique = std::to_string(
            std::chrono::high_resolution_clock::now().time_since_epoch().count());
        const auto base = std::filesystem::temp_directory_path() /
            ("ugyuvs1_profile2_" + unique);
        const auto singlePartial = base.string() + "_single.ugsp4c.partial";
        const auto singleFinal = base.string() + "_single.ugsp4c";
        const auto multiPartial = base.string() + "_multi.ugsp4c.partial";
        const auto multiFinal = base.string() + "_multi.ugsp4c";
        const auto preparedPartial = base.string() + "_prepared.ugsp4c.partial";
        const auto preparedFinal = base.string() + "_prepared.ugsp4c";
        const auto badPartial = base.string() + "_bad.ugsp4c.partial";
        const auto corruptFinal = base.string() + "_corrupt.ugsp4c";
        TempFiles cleanup{{
            singlePartial, singleFinal, multiPartial, multiFinal,
            preparedPartial, preparedFinal, badPartial, corruptFinal,
        }};

        const auto encode = [&](YuvSeedCaptureProfile runProfile,
                                const std::string& partial,
                                const std::string& final,
                                bool prepared) {
            auto writer = YuvSeedCaptureWriter::createPartial(partial, runProfile);
            for (std::size_t index = 0u; index < frames.size(); ++index) {
                const auto checkpoint =
                    index % runProfile.checkpointInterval == 0u;
                const auto preparedFrame = prepare(
                    frames[index], checkpoint ? nullptr : &frames[index - 1u],
                    runProfile, traversal, static_cast<std::uint32_t>(index));
                const auto stats = prepared
                    ? writer->appendPreparedFullSubstrateResidual(
                          viewOf(frames[index]),
                          {preparedFrame.residual.data(), preparedFrame.residual.size()})
                    : writer->append(viewOf(frames[index]));
                check(stats.operatorStateSha256 == preparedFrame.operatorStateSha,
                      "writer exposed the wrong frame operator-state receipt");
            }
            writer->finalize(final);
            YuvSeedCaptureReader reader(final);
            check(reader.inspection().profile == FullSubstrateCameraProfile &&
                      reader.inspection().finalized,
                  "reader did not report finalized logical profile 2");
            const auto decoded = reader.decodeAll();
            check(decoded.size() == frames.size(), "profile-2 frame count changed");
            for (std::size_t index = 0u; index < frames.size(); ++index) {
                checkFrame(decoded[index], frames[index]);
            }
            return readFile(final);
        };

        auto single = profile;
        single.noveltyWorkerCount = 1u;
        single.noveltyMaxInFlightBlocks = 2u;
        const auto singleBytes = encode(
            single, singlePartial, singleFinal, false);
        auto multi = profile;
        multi.noveltyWorkerCount = 4u;
        multi.noveltyMaxInFlightBlocks = 9u;
        const auto multiBytes = encode(
            multi, multiPartial, multiFinal, false);
        const auto preparedBytes = encode(
            multi, preparedPartial, preparedFinal, true);
        check(singleBytes == multiBytes,
              "profile-2 worker_count=1/4 bytes differ");
        check(singleBytes == preparedBytes,
              "profile-2 CPU/prepared residual bytes differ");

        {
            auto writer = YuvSeedCaptureWriter::createPartial(badPartial, profile);
            const auto good = prepare(frames[0], nullptr, profile, traversal, 0u);
            auto bad = good.residual;
            bad[bad.size() / 2u] ^= 1u;
            checkThrows(
                [&] {
                    writer->appendPreparedFullSubstrateResidual(
                        viewOf(frames[0]), {bad.data(), bad.size()});
                },
                "mismatched prepared profile-2 residual");
            checkThrows(
                [&] {
                    writer->appendPreparedResidual(
                        viewOf(frames[0]), {good.residual.data(), good.residual.size()});
                },
                "profile-1 ingress used on profile 2");
        }

        std::filesystem::copy_file(singleFinal, corruptFinal);
        const auto recordOffset = readU64(singleBytes.data() + 72u);
        {
            std::fstream stream(
                corruptFinal, std::ios::binary | std::ios::in | std::ios::out);
            const auto receiptByte = static_cast<std::streamoff>(
                recordOffset + 384u + 144u);
            stream.seekg(receiptByte, std::ios::beg);
            char lane = 0;
            stream.read(&lane, 1);
            stream.seekp(receiptByte, std::ios::beg);
            lane ^= 0x01;
            stream.write(&lane, 1);
        }
        checkThrows(
            [&] { YuvSeedCaptureReader(corruptFinal).decodeAll(); },
            "corrupt profile-2 block operator receipt");

        const auto digest = sha256(singleBytes.data(), singleBytes.size());
        check(singleBytes.size() == 71'966u &&
                  sha256Hex(digest) ==
                      "88221abab56a1820e2ef164273a212b2c0979dfbfca05dc1edfb825338f28130",
              "deterministic profile-2 fixture bytes changed");
        for (std::size_t index = 0u; index < frames.size(); ++index) {
            const auto checkpoint = index % profile.checkpointInterval == 0u;
            const auto fixturePrepared = prepare(
                frames[index], checkpoint ? nullptr : &frames[index - 1u],
                profile, traversal, static_cast<std::uint32_t>(index));
            std::cout << "UGYUVS1_PROFILE2_FRAME"
                      << " ordinal=" << index
                      << " pts=" << frames[index].sensorTimestampNs
                      << " frame_number=" << frames[index].frameNumber
                      << " pre_sha256="
                      << sha256Hex(preSubstrateFrameSha256(frames[index]))
                      << " operator_state_sha256="
                      << sha256Hex(fixturePrepared.operatorStateSha) << '\n';
        }
        check(argc <= 2, "expected at most one optional fixture output path");
        if (argc == 2) {
            check(argv[1] != nullptr && argv[1][0] != '\0',
                  "profile-2 fixture output path is empty");
            std::filesystem::copy_file(
                singleFinal,
                argv[1],
                std::filesystem::copy_options::overwrite_existing);
        }
        std::cout << "UGYUVS1_PROFILE2_PASS"
                  << " frames=" << frames.size()
                  << " file_bytes=" << singleBytes.size()
                  << " sha256=" << sha256Hex(digest)
                  << " operator_sha256="
                  << sha256Hex(fullSubstrateCameraOperatorDigest())
                  << " workers=1,4 prepared=exact replay=exact\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "UGYUVS1_PROFILE2_FAIL: " << error.what() << '\n';
        return 1;
    }
}
