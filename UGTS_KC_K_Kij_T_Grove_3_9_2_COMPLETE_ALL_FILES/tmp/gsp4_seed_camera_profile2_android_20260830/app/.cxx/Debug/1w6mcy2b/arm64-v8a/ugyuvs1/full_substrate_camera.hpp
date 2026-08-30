#pragma once

#include "seeded_uglut2_traversal.hpp"

#include <array>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace ugts::chrono {

// UGYUVS1 logical profile 2. Profile 1 remains UGCODE24_420_CAMERA_EXACT.
constexpr std::uint32_t FullSubstrateCameraProfile = 2u;
constexpr std::uint32_t FullSubstrateCameraProgramVersion = 0x0001'0000u;
constexpr std::uint32_t FullSubstrateRadixDepth = 16u;
constexpr std::size_t FullSubstrateReceiptWords = 20u;

enum class FullSubstratePredictor : std::uint32_t {
    PreviousSame = 0u,
    PreviousKleinLeft = 1u,
    PreviousKleinUp = 2u,
    PreviousKleinMed = 3u,
};

enum FullSubstrateReceiptWord : std::size_t {
    ReceiptCartesianAddress = 0u,
    ReceiptSourceRho20 = 1u,
    ReceiptSourceTheta18 = 2u,
    ReceiptWrappedRho20 = 3u,
    ReceiptTopologicalTheta18 = 4u,
    ReceiptSclpKeyLow = 5u,
    ReceiptSclpKeyHigh = 6u,
    ReceiptMortonLow = 7u,
    ReceiptMortonHigh = 8u,
    ReceiptKlb37Low = 9u,
    ReceiptKlb37High = 10u,
    ReceiptPhiFinal = 11u,
    ReceiptOmegaFinal = 12u,
    ReceiptAlpha = 13u,
    ReceiptBranchWord = 14u,
    ReceiptPackedState = 15u,
    ReceiptKleinLeftAddress = 16u,
    ReceiptKleinUpAddress = 17u,
    ReceiptKleinUpLeftAddress = 18u,
    ReceiptTag = 19u,
};

// ReceiptPackedState bit layout. These are synthetic index-space guard classes;
// they do not assert scene geometry or an SDF magnitude.
constexpr std::uint32_t FullStateElevationMask = 0x0000'03ffu;
constexpr std::uint32_t FullStateSymbolShift = 10u;
constexpr std::uint32_t FullStateSelectorShift = 13u;
constexpr std::uint32_t FullStateRadialWrapOddBit = 1u << 15u;
constexpr std::uint32_t FullStateOrientationBit = 1u << 16u;
constexpr std::uint32_t FullStateKleinLeftReflectedBit = 1u << 17u;
constexpr std::uint32_t FullStateKleinUpReflectedBit = 1u << 18u;
constexpr std::uint32_t FullStateKleinUpLeftReflectedBit = 1u << 19u;
constexpr std::uint32_t FullStateInsideConeBit = 1u << 20u;
constexpr std::uint32_t FullStateNearConeBit = 1u << 21u;
constexpr std::uint32_t FullStateInsideSphereBit = 1u << 22u;
constexpr std::uint32_t FullStateNearSphereBit = 1u << 23u;
constexpr std::uint32_t FullStateApexGuardBit = 1u << 24u;
// A depth-16 implicit heap node is 17 bits. ReceiptBranchWord stores its low
// 16 bits beside the 16-bit prefix; this bit preserves the node's high bit.
constexpr std::uint32_t FullStateNodeHighBit = 1u << 25u;
constexpr std::uint32_t FullStateConeTripleShift = 26u;
constexpr std::uint32_t FullStateConeTripleMask = 7u << FullStateConeTripleShift;

struct FullSubstrateLaneInput {
    std::uint32_t width = 0u;
    std::uint32_t height = 0u;
    std::uint64_t rootSeed = 0u;
    std::uint64_t recipeSeed = 1u;
    std::uint32_t frameOrdinal = 0u;
    std::uint32_t cartesianAddress = 0u;
    std::uint32_t sourceRho20 = 0u;
    std::uint32_t sourceTheta18 = 0u;
};

struct FullSubstrateLaneReceipt {
    std::array<std::uint32_t, FullSubstrateReceiptWords> words{};

    FullSubstratePredictor predictor() const noexcept {
        return static_cast<FullSubstratePredictor>(
            (words[ReceiptPackedState] >> FullStateSelectorShift) & 3u);
    }
};

struct FullSubstrateConeProfile {
    std::uint32_t tripleIndex = 0u;
    std::uint32_t scale = 0u;
    std::uint32_t baseRadius = 0u;
    std::uint32_t height = 0u;
    std::uint32_t slantT = 0u;
};

struct FullSubstratePlaneBytes {
    const std::uint8_t* data = nullptr;
    std::size_t size = 0u;
};

struct FullSubstratePreviousFrame {
    FullSubstratePlaneBytes y;
    FullSubstratePlaneBytes u;
    FullSubstratePlaneBytes v;
};

struct FullSubstrateBlockReceipt {
    std::uint32_t firstLumaOrdinal = 0u;
    std::uint32_t lumaCount = 0u;
    std::array<std::uint32_t, 4u> selectorCounts{};
    Sha256Digest operatorStateSha256{};
};

struct FullSubstratePrediction {
    // Existing UGTRV1 owner order: Y for every luma address, followed by U,V
    // only at each even-x/even-y owner.
    std::vector<std::uint8_t> canonicalOwnerPrediction;
    std::vector<FullSubstrateBlockReceipt> blocks;
    Sha256Digest frameOperatorStateSha256{};
};

// Exact uint32 operators shared by the CPU oracle and integer-only GPU ports.
std::uint32_t fullSubstrateMix32(std::uint32_t value) noexcept;
std::uint32_t fullSubstrateSeedWord(std::uint64_t rootSeed, std::uint32_t index) noexcept;

// Frozen integer Pythagorean side-view delta-T profile. The eight (R,h,T)
// unit triples are (3,4,5), (5,12,13), (8,15,17), (7,24,25),
// (20,21,29), (12,35,37), (9,40,41), (28,45,53).
FullSubstrateConeProfile fullSubstrateConeProfile(std::uint64_t rootSeed) noexcept;

// Evaluate one luma-address owner. The 20 words are the canonical packed
// operator/branch receipt and are hashed little-endian by the frame program.
FullSubstrateLaneReceipt evaluateFullSubstrateCameraLane(
    const FullSubstrateLaneInput& input
);

std::vector<std::uint8_t> packFullSubstrateLaneReceipt(
    const FullSubstrateLaneReceipt& receipt
);

// Regenerate all predictor bytes and operator receipts from seed, UGLUT2
// rho/theta state, frame ordinal and the previous exact dense planes.
FullSubstratePrediction buildFullSubstrateCameraPrediction(
    std::uint32_t width,
    std::uint32_t height,
    std::uint64_t rootSeed,
    std::uint64_t recipeSeed,
    std::uint32_t frameOrdinal,
    const SeededUglut2Traversal& traversal,
    const FullSubstratePreviousFrame& previous,
    std::uint32_t blockLumaAddresses
);

// Static executable-program digest stored in the profile-2 UGYUVS1 header.
Sha256Digest fullSubstrateCameraOperatorDigest();

} // namespace ugts::chrono
