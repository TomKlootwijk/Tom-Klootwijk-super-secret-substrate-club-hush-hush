#include "yuv_seed_capture.hpp"

#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using namespace ugts::chrono;

void require(bool condition, const std::string& message) {
    if (!condition) throw std::runtime_error(message);
}

bool hasSuffix(const std::string& value, const char* suffix) {
    const auto length = std::char_traits<char>::length(suffix);
    return value.size() >= length &&
           value.compare(value.size() - length, length, suffix) == 0;
}

std::vector<std::uint8_t> readFile(const std::filesystem::path& path) {
    std::ifstream stream(path, std::ios::binary | std::ios::ate);
    require(stream.good(), "cannot open " + path.string());
    const auto end = stream.tellg();
    require(end >= 0 &&
                static_cast<std::uint64_t>(end) <=
                    std::numeric_limits<std::size_t>::max(),
            "file exceeds host address space");
    std::vector<std::uint8_t> bytes(static_cast<std::size_t>(end));
    stream.seekg(0, std::ios::beg);
    stream.read(reinterpret_cast<char*>(bytes.data()),
                static_cast<std::streamsize>(bytes.size()));
    require(static_cast<std::size_t>(stream.gcount()) == bytes.size(),
            "short file read");
    return bytes;
}

std::uint32_t parseU32(const char* text, const char* label) {
    require(text != nullptr && text[0] != '\0', std::string(label) + " is empty");
    std::size_t used = 0u;
    const auto value = std::stoull(text, &used, 10);
    require(text[used] == '\0' && value <= std::numeric_limits<std::uint32_t>::max(),
            std::string(label) + " is not uint32");
    return static_cast<std::uint32_t>(value);
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

struct ExactFrameReceipt {
    std::int64_t sensorTimestampNs = 0;
    std::int64_t frameNumber = -1;
    Sha256Digest preSubstrateSha{};
    Sha256Digest metadataSha{};
};

} // namespace

int main(int argc, char** argv) {
    try {
        require(argc >= 3 && argc <= 5,
                "usage: yuv_seed_capture_reencode_profile2 "
                "<profile1.ugsp4c> <profile2.ugsp4c> [workers] [max-in-flight]");
        const std::filesystem::path sourcePath = argv[1];
        const std::filesystem::path finalPath = argv[2];
        require(hasSuffix(sourcePath.string(), ".ugsp4c") &&
                    hasSuffix(finalPath.string(), ".ugsp4c"),
                "source/final paths must use .ugsp4c");
        require(std::filesystem::absolute(sourcePath).lexically_normal() !=
                    std::filesystem::absolute(finalPath).lexically_normal(),
                "source and profile-2 output paths must differ");
        require(!std::filesystem::exists(finalPath),
                "profile-2 output already exists; refusing to overwrite it");
        const auto partialPath = finalPath.string() + ".partial";
        require(!std::filesystem::exists(partialPath),
                "profile-2 partial already exists; refusing to overwrite it");

        YuvSeedCaptureReader source(sourcePath.string());
        require(source.inspection().finalized &&
                    source.inspection().profile == Ugcode24_420Profile,
                "source must be a finalized logical profile-1 UGYUVS1 file");
        auto outputProfile = source.sourceProfile();
        outputProfile.logicalProfile = FullSubstrateCameraProfile;
        outputProfile.noveltyWorkerCount =
            argc >= 4 ? parseU32(argv[3], "workers") : 4u;
        outputProfile.noveltyMaxInFlightBlocks =
            argc >= 5 ? parseU32(argv[4], "max-in-flight")
                      : std::max<std::uint32_t>(
                            outputProfile.noveltyWorkerCount, 8u);

        std::vector<ExactFrameReceipt> receipts;
        receipts.reserve(static_cast<std::size_t>(
            source.inspection().committedFrames));
        auto writer = YuvSeedCaptureWriter::createPartial(
            partialPath, outputProfile);
        source.replay([&](const DenseYuv420p8Frame& frame) {
            receipts.push_back(ExactFrameReceipt{
                frame.sensorTimestampNs,
                frame.frameNumber,
                preSubstrateFrameSha256(frame),
                sha256(frame.canonicalMetadata.data(),
                       frame.canonicalMetadata.size()),
            });
            writer->append(viewOf(frame));
        });
        writer->finalize(finalPath.string());

        YuvSeedCaptureReader output(finalPath.string());
        require(output.inspection().finalized &&
                    output.inspection().profile == FullSubstrateCameraProfile &&
                    output.inspection().committedFrames == receipts.size(),
                "profile-2 output inspection mismatch");
        auto verified = std::size_t{0u};
        output.replay([&](const DenseYuv420p8Frame& frame) {
            require(verified < receipts.size(), "profile-2 replay gained a frame");
            const auto& expected = receipts[verified];
            require(frame.sensorTimestampNs == expected.sensorTimestampNs &&
                        frame.frameNumber == expected.frameNumber &&
                        preSubstrateFrameSha256(frame) == expected.preSubstrateSha &&
                        sha256(frame.canonicalMetadata.data(),
                               frame.canonicalMetadata.size()) == expected.metadataSha,
                    "profile-2 output is not byte-identical to source authority");
            ++verified;
        });
        require(verified == receipts.size(), "profile-2 replay lost a frame");

        const auto sourceBytes = readFile(sourcePath);
        const auto outputBytes = readFile(finalPath);
        std::cout << "UGYUVS1_REENCODE_PROFILE2_PASS"
                  << " frames=" << receipts.size()
                  << " source_bytes=" << sourceBytes.size()
                  << " profile2_bytes=" << outputBytes.size()
                  << " source_sha256="
                  << sha256Hex(sha256(sourceBytes.data(), sourceBytes.size()))
                  << " profile2_sha256="
                  << sha256Hex(sha256(outputBytes.data(), outputBytes.size()))
                  << " exact_yuv_pts_metadata=true\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "UGYUVS1_REENCODE_PROFILE2_FAIL: " << error.what() << '\n';
        return 1;
    }
}
