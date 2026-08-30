#include "ugtc4d_decoder.hpp"

#include <chrono>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

#ifndef UGTC4D_FIXTURE_PATH
#error UGTC4D_FIXTURE_PATH must name the generated custom fixture
#endif

namespace {

void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

std::vector<std::uint8_t> readFile(const std::string& path) {
    std::ifstream stream(path, std::ios::binary | std::ios::ate);
    require(stream.good(), "cannot open fixture");
    const auto length = stream.tellg();
    require(length >= 0, "cannot determine fixture length");
    std::vector<std::uint8_t> result(static_cast<std::size_t>(length));
    stream.seekg(0, std::ios::beg);
    if (!result.empty()) stream.read(reinterpret_cast<char*>(result.data()), length);
    require(stream.good(), "cannot read fixture");
    return result;
}

std::vector<std::uint8_t> expectedFrame(unsigned ordinal) {
    constexpr unsigned width = 8u;
    constexpr unsigned height = 6u;
    std::vector<std::uint8_t> result(width * height * 3u);
    for (unsigned y = 0u; y < height; ++y) {
        for (unsigned x = 0u; x < width; ++x) {
            const auto address = (y * width + x) * 3u;
            auto red = (x * 29u + y * 11u + 7u) & 255u;
            auto green = (x * 13u + y * 37u + 19u) & 255u;
            auto blue = ((x ^ y) * 41u + x * 3u + 23u) & 255u;
            if (ordinal != 0u) {
                red = (red + ordinal * ((x + y) % 3u)) & 255u;
                green = (green + ordinal * ((2u * x + y) % 2u)) & 255u;
                blue = (blue + ordinal * ((x + 2u * y) % 4u)) & 255u;
            }
            result[address] = static_cast<std::uint8_t>(red);
            result[address + 1u] = static_cast<std::uint8_t>(green);
            result[address + 2u] = static_cast<std::uint8_t>(blue);
        }
    }
    return result;
}

void runFixture() {
    const std::string path = UGTC4D_FIXTURE_PATH;
    auto decoder = ugts::chrono::Ugtc4dDecoder::fromFile(path);
    require(decoder.header().width == 8u && decoder.header().height == 6u,
            "fixture raster header mismatch");
    require(decoder.frameCount() == 3u && decoder.traversal().size() == 48u,
            "fixture count/traversal mismatch");
    require(decoder.framePredictor(0u) == 13u && decoder.framePredictor(1u) == 11u &&
                decoder.framePredictor(2u) == 14u,
            "fixture predictor dispatch mismatch");
    const auto first = decoder.decodeFrame(0u);
    require(first.cartesianRgb == expectedFrame(0u),
            "predictor 13 did not reconstruct exact Cartesian fixture RGB");
    const auto second = decoder.decodeFrame(1u, &first);
    require(second.cartesianRgb == expectedFrame(1u),
            "predictor 11 did not reconstruct exact Cartesian fixture RGB");
    const auto third = decoder.decodeFrame(2u);
    require(third.cartesianRgb == expectedFrame(2u),
            "predictor 14 q709 did not reconstruct exact Cartesian fixture RGB");
    require(first.sourcePts == 100 && first.sourceEndPtsExclusive == 140 &&
                second.sourcePts == 140 && second.sourceEndPtsExclusive == 180 &&
                third.sourcePts == 180 && third.sourceEndPtsExclusive == 220,
            "fixture PTS intervals mismatch");
    const auto verified = decoder.verifyAllFrames();
    require(verified.frames == 3u && verified.decodedRgbBytes == 432u &&
                verified.predictor13Frames == 1u && verified.predictor11Frames == 1u &&
                verified.predictor14Frames == 1u,
            "fixture full-stream verification summary mismatch");

    bool missingPreviousRejected = false;
    try {
        static_cast<void>(decoder.decodeFrame(1u));
    } catch (const std::runtime_error&) {
        missingPreviousRejected = true;
    }
    require(missingPreviousRejected, "temporal frame accepted a missing dependency");

    auto corrupt = readFile(path);
    corrupt[50] ^= 1u;
    bool corruptionRejected = false;
    try {
        static_cast<void>(ugts::chrono::Ugtc4dDecoder(std::move(corrupt)));
    } catch (const std::runtime_error&) {
        corruptionRejected = true;
    }
    require(corruptionRejected, "whole-file corruption was not rejected");

    std::cout << "UGTC4D_NATIVE_FIXTURE_PASS bytes=" << readFile(path).size()
              << " frames=3 predictors=13,11,14 traversal_pixels=48\n";
}

void runFullOracle(const std::string& path) {
    const auto started = std::chrono::steady_clock::now();
    auto decoder = ugts::chrono::Ugtc4dDecoder::fromFile(path);
    const auto verified = decoder.verifyAllFrames();
    const auto seconds = std::chrono::duration<double>(
        std::chrono::steady_clock::now() - started).count();
    std::cout << "UGTC4D_NATIVE_FULL_PASS frames=" << decoder.frameCount()
              << " decoded_rgb_bytes=" << verified.decodedRgbBytes
              << " temporal_frames=" << verified.predictor11Frames
              << " seconds=" << seconds << '\n';
}

} // namespace

int main(int argc, char** argv) {
    try {
        runFixture();
        if (argc == 2) runFullOracle(argv[1]);
        else if (argc > 2) throw std::runtime_error("expected zero or one full-oracle path");
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "UGTC4D_NATIVE_TEST_FAIL " << error.what() << '\n';
        return 1;
    }
}
