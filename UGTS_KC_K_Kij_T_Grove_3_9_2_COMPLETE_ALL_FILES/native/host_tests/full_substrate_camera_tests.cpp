#include "full_substrate_camera.hpp"

#include <array>
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

std::vector<std::uint8_t> readFile(const std::filesystem::path& path) {
    std::ifstream stream(path, std::ios::binary | std::ios::ate);
    check(stream.good(), "cannot open fixture");
    const auto end = stream.tellg();
    check(end >= 0, "cannot size fixture");
    std::vector<std::uint8_t> bytes(static_cast<std::size_t>(end));
    stream.seekg(0, std::ios::beg);
    stream.read(reinterpret_cast<char*>(bytes.data()),
                static_cast<std::streamsize>(bytes.size()));
    check(static_cast<std::size_t>(stream.gcount()) == bytes.size(),
          "fixture read is truncated");
    return bytes;
}

std::uint32_t parity32(std::uint32_t value) {
    value ^= value >> 16u;
    value ^= value >> 8u;
    value ^= value >> 4u;
    return (0x6996u >> (value & 15u)) & 1u;
}

} // namespace

int main() {
    try {
        constexpr std::uint32_t Width = 320u;
        constexpr std::uint32_t Height = 180u;
        constexpr std::uint64_t RootSeed = 0x0123'4567'89ab'cdefull;
        const auto lut = readFile(UGLUT2_FIXTURE_PATH);
        const auto traversal = regenerateSeededUglut2Traversal(
            Width, Height, RootSeed, 1u, lut);
        check(traversal.rho20ByCartesian.size() == Width * Height &&
                  traversal.theta18ByCartesian.size() == Width * Height,
              "traversal did not expose rho20/theta18 maps");

        const auto vectorAddress = 12'345u;
        const auto vector = evaluateFullSubstrateCameraLane(FullSubstrateLaneInput{
            Width,
            Height,
            RootSeed,
            1u,
            37u,
            vectorAddress,
            traversal.rho20ByCartesian[vectorAddress],
            traversal.theta18ByCartesian[vectorAddress],
        });
        check(vector.words[ReceiptCartesianAddress] == vectorAddress,
              "receipt address changed");
        const auto cone = fullSubstrateConeProfile(RootSeed);
        check(cone.tripleIndex != 0u &&
                  cone.baseRadius * cone.baseRadius + cone.height * cone.height ==
                      cone.slantT * cone.slantT &&
                  ((vector.words[ReceiptPackedState] & FullStateConeTripleMask) >>
                   FullStateConeTripleShift) == cone.tripleIndex,
              "Pythagorean delta-T cone receipt changed");
        const auto keyLow = vector.words[ReceiptSclpKeyLow];
        const auto keyHigh = vector.words[ReceiptSclpKeyHigh];
        check(((keyLow >> 12u) & 0x3fffu) == 37u &&
                  ((keyHigh >> 12u) & 0xfffffu) == vector.words[ReceiptWrappedRho20] &&
                  (((keyHigh & 0xfffu) << 6u) | (keyLow >> 26u)) ==
                      vector.words[ReceiptTopologicalTheta18],
              "SCLP contiguous key fields changed");
        const auto klbLow = vector.words[ReceiptKlb37Low];
        const auto klbHigh = vector.words[ReceiptKlb37High];
        check((parity32(klbLow) ^ parity32(klbHigh & 0x1fu)) == 0u &&
                  (klbHigh & ~0x1fu) == 0u,
              "KLB37 even parity/layout changed");
        const auto branchWord = vector.words[ReceiptBranchWord];
        check((branchWord >> 16u) <= 0xffffu,
              "packed branch prefix escaped sixteen bits");

        std::array<std::uint64_t, 4u> selectorCounts{};
        std::uint32_t stateOr = 0u;
        std::uint32_t stateAnd = 0xffff'ffffu;
        for (std::uint32_t seedVariant = 0u; seedVariant < 16u; ++seedVariant) {
            const auto scanSeed = RootSeed + seedVariant * 0x9e37'79b9u;
            for (std::uint32_t frame = 0u; frame < 8u; ++frame) {
                for (std::uint32_t address = 0u; address < Width * Height; ++address) {
                    const auto receipt = evaluateFullSubstrateCameraLane(
                        FullSubstrateLaneInput{
                            Width,
                            Height,
                            scanSeed,
                            1u,
                            frame,
                            address,
                            traversal.rho20ByCartesian[address],
                            traversal.theta18ByCartesian[address],
                        });
                    const auto packed = receipt.words[ReceiptPackedState];
                    stateOr |= packed;
                    stateAnd &= packed;
                    ++selectorCounts[static_cast<std::size_t>(receipt.predictor())];
                }
            }
        }
        for (const auto count : selectorCounts) {
            check(count != 0u, "one profile-2 predictor selector never toggled");
        }
        const auto requiredToggleMask = FullStateRadialWrapOddBit |
            FullStateOrientationBit | FullStateKleinUpReflectedBit |
            FullStateKleinUpLeftReflectedBit | FullStateInsideConeBit |
            FullStateNearConeBit | FullStateInsideSphereBit |
            FullStateNearSphereBit | FullStateApexGuardBit;
        check((stateOr & requiredToggleMask) == requiredToggleMask &&
                  ((~stateAnd) & requiredToggleMask) == requiredToggleMask,
              "a required topology/guard operator did not toggle");

        std::vector<std::uint8_t> previousY(Width * Height);
        std::vector<std::uint8_t> previousU(Width * Height / 4u);
        std::vector<std::uint8_t> previousV(previousU.size());
        for (std::size_t index = 0u; index < previousY.size(); ++index) {
            previousY[index] = static_cast<std::uint8_t>((index * 29u + 17u) & 255u);
        }
        for (std::size_t index = 0u; index < previousU.size(); ++index) {
            previousU[index] = static_cast<std::uint8_t>((index * 31u + 53u) & 255u);
            previousV[index] = static_cast<std::uint8_t>((index * 67u + 101u) & 255u);
        }
        const auto prediction = buildFullSubstrateCameraPrediction(
            Width,
            Height,
            RootSeed,
            1u,
            37u,
            traversal,
            FullSubstratePreviousFrame{
                {previousY.data(), previousY.size()},
                {previousU.data(), previousU.size()},
                {previousV.data(), previousV.size()},
            },
            4096u);
        check(prediction.canonicalOwnerPrediction.size() ==
                  previousY.size() + previousU.size() + previousV.size() &&
                  prediction.blocks.size() == 15u,
              "profile-2 prediction shape changed");
        std::uint64_t blockSelectors = 0u;
        for (const auto& block : prediction.blocks) {
            for (const auto count : block.selectorCounts) blockSelectors += count;
        }
        check(blockSelectors == previousY.size(),
              "block selector receipt count changed");

        const auto packedVector = packFullSubstrateLaneReceipt(vector);
        std::cout << "UGCAMNODE_FX1_PASS"
                  << " vector_receipt_sha256="
                  << sha256Hex(sha256(packedVector.data(), packedVector.size()))
                  << " frame_receipt_sha256="
                  << sha256Hex(prediction.frameOperatorStateSha256)
                  << " operator_sha256="
                  << sha256Hex(fullSubstrateCameraOperatorDigest())
                  << " selectors=" << selectorCounts[0] << ',' << selectorCounts[1]
                  << ',' << selectorCounts[2] << ',' << selectorCounts[3] << '\n';
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "UGCAMNODE_FX1_FAIL: " << error.what() << '\n';
        return 1;
    }
}
