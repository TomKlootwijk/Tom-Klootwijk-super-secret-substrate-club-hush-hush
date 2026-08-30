#include "full_substrate_camera.hpp"

#include <algorithm>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <string>

namespace ugts::chrono {
namespace {

constexpr std::uint32_t Rho20Mask = (1u << 20u) - 1u;
constexpr std::uint32_t Theta18Mask = (1u << 18u) - 1u;
constexpr std::uint32_t Phi12Mask = (1u << 12u) - 1u;
constexpr std::uint32_t KSeedStep = 0x9e37'79b9u;
constexpr std::uint32_t KSymbolStep = 0x85eb'ca6bu;

struct ConeUnitTriple {
    std::uint32_t radius;
    std::uint32_t height;
    std::uint32_t slant;
};

constexpr std::array<ConeUnitTriple, 8u> ConeTriples{{
    {3u, 4u, 5u},
    {5u, 12u, 13u},
    {8u, 15u, 17u},
    {7u, 24u, 25u},
    {20u, 21u, 29u},
    {12u, 35u, 37u},
    {9u, 40u, 41u},
    {28u, 45u, 53u},
}};

[[noreturn]] void fail(const std::string& message) {
    throw std::runtime_error("UGCAMNODE-FX1: " + message);
}

void require(bool condition, const std::string& message) {
    if (!condition) fail(message);
}

std::uint32_t rotateLeft(std::uint32_t value, std::uint32_t shift) noexcept {
    shift &= 31u;
    return shift == 0u ? value : (value << shift) | (value >> (32u - shift));
}

std::uint32_t parity32(std::uint32_t value) noexcept {
    value ^= value >> 16u;
    value ^= value >> 8u;
    value ^= value >> 4u;
    return (0x6996u >> (value & 15u)) & 1u;
}

std::uint64_t splitmix64(std::uint64_t value) noexcept {
    value += 0x9e37'79b9'7f4a'7c15ull;
    value = (value ^ (value >> 30u)) * 0xbf58'476d'1ce4'e5b9ull;
    value = (value ^ (value >> 27u)) * 0x94d0'49bb'1331'11ebull;
    return value ^ (value >> 31u);
}

std::uint64_t combineSeed(std::uint64_t seed, std::uint64_t value) noexcept {
    const auto mixed = splitmix64(value) + 0x9e37'79b9'7f4a'7c15ull +
                       (seed << 6u) + (seed >> 2u);
    return splitmix64(seed ^ mixed);
}

std::uint64_t stableId(
    std::uint64_t session,
    std::uint64_t nameSpace,
    std::uint64_t address
) noexcept {
    return combineSeed(combineSeed(session, nameSpace), address);
}

std::uint32_t abs32(std::int32_t value) noexcept {
    return value < 0 ? static_cast<std::uint32_t>(-value)
                     : static_cast<std::uint32_t>(value);
}

std::uint32_t absDifference(std::uint32_t left, std::uint32_t right) noexcept {
    return left >= right ? left - right : right - left;
}

std::int32_t floorDiv(std::int32_t value, std::int32_t divisor) noexcept {
    auto quotient = value / divisor;
    const auto remainder = value % divisor;
    if (remainder < 0) --quotient;
    return quotient;
}

std::int32_t floorMod(std::int32_t value, std::int32_t divisor) noexcept {
    const auto remainder = value % divisor;
    return remainder < 0 ? remainder + divisor : remainder;
}

struct KleinAddress {
    std::uint32_t address = 0u;
    bool reflected = false;
};

KleinAddress kleinAddress(
    std::int32_t x,
    std::int32_t y,
    std::uint32_t width,
    std::uint32_t height
) noexcept {
    const auto signedWidth = static_cast<std::int32_t>(width);
    const auto signedHeight = static_cast<std::int32_t>(height);
    const auto yWrap = floorDiv(y, signedHeight);
    const auto yy = floorMod(y, signedHeight);
    const auto reflected = (yWrap & 1) != 0;
    if (reflected) x = (signedWidth - 1) - x;
    const auto xx = floorMod(x, signedWidth);
    return KleinAddress{
        static_cast<std::uint32_t>(yy) * width + static_cast<std::uint32_t>(xx),
        reflected,
    };
}

std::int32_t q15Coordinate(std::uint32_t index, std::uint32_t extent) noexcept {
    // Allowed dimensions guarantee that the signed product fits int32.
    const auto numerator = static_cast<std::int32_t>(index * 2u + 1u) -
                           static_cast<std::int32_t>(extent);
    return (numerator * 32767) / static_cast<std::int32_t>(extent);
}

std::uint32_t triangleNumberMod32(std::uint32_t frame) noexcept {
    if ((frame & 1u) == 0u) return (frame / 2u) * (frame - 1u);
    return frame * ((frame - 1u) / 2u);
}

struct Word64 {
    std::uint32_t low = 0u;
    std::uint32_t high = 0u;
};

Word64 sclpContiguous(
    std::uint32_t rho20,
    std::uint32_t theta18,
    std::uint32_t frame14,
    std::uint32_t phi12
) noexcept {
    return Word64{
        (phi12 & Phi12Mask) |
            ((frame14 & 0x3fffu) << 12u) |
            ((theta18 & 0x3fu) << 26u),
        ((theta18 >> 6u) & 0x0fffu) | ((rho20 & Rho20Mask) << 12u),
    };
}

void appendBit(Word64& value, std::uint32_t bit) noexcept {
    value.high = (value.high << 1u) | (value.low >> 31u);
    value.low = (value.low << 1u) | (bit & 1u);
}

Word64 correctedMorton(
    std::uint32_t rho20,
    std::uint32_t theta18,
    std::uint32_t frame14,
    std::uint32_t phi12
) noexcept {
    Word64 result{};
    for (std::uint32_t round = 0u; round < 20u; ++round) {
        if (round < 20u) appendBit(result, (rho20 >> (19u - round)) & 1u);
        if (round < 18u) appendBit(result, (theta18 >> (17u - round)) & 1u);
        if (round < 14u) appendBit(result, (frame14 >> (13u - round)) & 1u);
        if (round < 12u) appendBit(result, (phi12 >> (11u - round)) & 1u);
    }
    return result;
}

Word64 klb37(
    std::uint32_t rho20,
    std::uint32_t theta18,
    std::uint32_t elevation10,
    std::uint32_t symbol3
) noexcept {
    // Round rho20 into eleven bits. Maximum product is below UINT32_MAX.
    const auto rho11 = static_cast<std::uint32_t>(
        (rho20 * 2047u + Rho20Mask / 2u) / Rho20Mask);
    const auto theta12 = (theta18 >> 6u) & 0x0fffu;
    std::uint32_t low = rho11 | (theta12 << 11u) |
                        ((elevation10 & 0x01ffu) << 23u);
    std::uint32_t high = ((elevation10 >> 9u) & 1u) |
                         ((symbol3 & 7u) << 1u);
    const auto parity = parity32(low) ^ parity32(high & 15u);
    high |= parity << 4u;
    return Word64{low, high};
}

std::uint8_t medianPredictor(
    std::uint8_t left,
    std::uint8_t up,
    std::uint8_t upLeft
) noexcept {
    const auto gradient = std::clamp(
        static_cast<int>(left) + static_cast<int>(up) - static_cast<int>(upLeft),
        0,
        255);
    const auto low = std::min<unsigned>(left, up);
    const auto high = std::max<unsigned>(left, up);
    return static_cast<std::uint8_t>(
        std::max<unsigned>(low, std::min<unsigned>(high, static_cast<unsigned>(gradient))));
}

std::uint8_t selectPredictor(
    FullSubstratePredictor selector,
    const std::uint8_t* plane,
    std::size_t planeSize,
    std::uint32_t same,
    std::uint32_t left,
    std::uint32_t up,
    std::uint32_t upLeft
) {
    require(plane != nullptr && same < planeSize && left < planeSize &&
                up < planeSize && upLeft < planeSize,
            "predictor address escaped previous plane");
    switch (selector) {
    case FullSubstratePredictor::PreviousSame:
        return plane[same];
    case FullSubstratePredictor::PreviousKleinLeft:
        return plane[left];
    case FullSubstratePredictor::PreviousKleinUp:
        return plane[up];
    case FullSubstratePredictor::PreviousKleinMed:
        return medianPredictor(plane[left], plane[up], plane[upLeft]);
    }
    fail("predictor selector escaped two bits");
}

void appendU32(std::vector<std::uint8_t>& bytes, std::uint32_t value) {
    bytes.push_back(static_cast<std::uint8_t>(value));
    bytes.push_back(static_cast<std::uint8_t>(value >> 8u));
    bytes.push_back(static_cast<std::uint8_t>(value >> 16u));
    bytes.push_back(static_cast<std::uint8_t>(value >> 24u));
}

void appendDigest(std::vector<std::uint8_t>& bytes, const Sha256Digest& digest) {
    bytes.insert(bytes.end(), digest.begin(), digest.end());
}

std::vector<std::uint8_t> domain(const char* text) {
    const auto length = std::strlen(text) + 1u;
    return {reinterpret_cast<const std::uint8_t*>(text),
            reinterpret_cast<const std::uint8_t*>(text) + length};
}

Sha256Digest blockDigest(
    std::uint32_t frameOrdinal,
    std::uint32_t first,
    const std::vector<FullSubstrateLaneReceipt>& receipts
) {
    auto bytes = domain("UGCAMNODE-FX1-block-receipts-v0.1.0");
    appendU32(bytes, frameOrdinal);
    appendU32(bytes, first);
    appendU32(bytes, static_cast<std::uint32_t>(receipts.size()));
    for (const auto& receipt : receipts) {
        for (const auto word : receipt.words) appendU32(bytes, word);
    }
    return sha256(bytes.data(), bytes.size());
}

} // namespace

std::uint32_t fullSubstrateMix32(std::uint32_t value) noexcept {
    value ^= value >> 16u;
    value *= 0x7feb'352du;
    value ^= value >> 15u;
    value *= 0x846c'a68bu;
    value ^= value >> 16u;
    return value;
}

std::uint32_t fullSubstrateSeedWord(
    std::uint64_t rootSeed,
    std::uint32_t index
) noexcept {
    const auto low = static_cast<std::uint32_t>(rootSeed);
    const auto high = static_cast<std::uint32_t>(rootSeed >> 32u);
    return fullSubstrateMix32(
        low ^ rotateLeft(high, index & 31u) ^ ((index + 1u) * KSeedStep));
}

FullSubstrateConeProfile fullSubstrateConeProfile(std::uint64_t rootSeed) noexcept {
    const auto index = fullSubstrateSeedWord(rootSeed, 16u) & 7u;
    const auto scale = 256u + (fullSubstrateSeedWord(rootSeed, 17u) & 255u);
    const auto unit = ConeTriples[index];
    return FullSubstrateConeProfile{
        index,
        scale,
        scale * unit.radius,
        scale * unit.height,
        scale * unit.slant,
    };
}

FullSubstrateLaneReceipt evaluateFullSubstrateCameraLane(
    const FullSubstrateLaneInput& input
) {
    require(input.width >= 2u && input.height >= 2u &&
                input.width <= 65534u && input.height <= 65534u,
            "dimensions are outside the bounded uint16 profile");
    const auto pixelCount = static_cast<std::size_t>(input.width) * input.height;
    require(input.cartesianAddress < pixelCount, "cartesian address is out of range");
    require(input.sourceRho20 <= Rho20Mask && input.sourceTheta18 <= Theta18Mask,
            "UGLUT2 rho/theta code is out of range");

    const auto address = input.cartesianAddress;
    const auto x = address % input.width;
    const auto y = address / input.width;
    const auto radialSum = input.sourceRho20 +
                           (fullSubstrateSeedWord(input.rootSeed, 3u) & 0x001f'ffffu);
    const auto wrappedRho20 = radialSum & Rho20Mask;
    const auto radialOdd = ((radialSum >> 20u) & 1u) != 0u;

    auto phi = fullSubstrateSeedWord(input.rootSeed, 20u);
    auto omega = fullSubstrateSeedWord(input.rootSeed, 21u);
    auto alpha = fullSubstrateSeedWord(input.rootSeed, 22u);
    phi += input.frameOrdinal * omega;
    phi += triangleNumberMod32(input.frameOrdinal) * alpha;
    omega += input.frameOrdinal * alpha;
    auto theta32 = input.sourceTheta18 << 14u;
    std::uint32_t orientation = 0u;
    if (radialOdd) {
        theta32 = 0x8000'0000u - theta32;
        phi = 0u - phi;
        omega = 0u - omega;
        alpha = 0u - alpha;
        orientation = 1u;
    }
    const auto topologicalTheta18 = (theta32 >> 14u) & Theta18Mask;
    const auto phi12 = phi >> 20u;
    const auto frame14 = input.frameOrdinal & 0x3fffu;
    const auto key = sclpContiguous(
        wrappedRho20, topologicalTheta18, frame14, phi12);
    const auto morton = correctedMorton(
        wrappedRho20, topologicalTheta18, frame14, phi12);

    const auto elevation10 = static_cast<std::uint32_t>(
        ((input.height - 1u - y) * 1023u + (input.height - 1u) / 2u) /
        (input.height - 1u));
    const auto symbol3 = fullSubstrateMix32(
        fullSubstrateSeedWord(input.rootSeed, 2u) ^ address ^
        (input.frameOrdinal * KSymbolStep)) & 7u;
    const auto klb = klb37(wrappedRho20, topologicalTheta18, elevation10, symbol3);
    const auto session = combineSeed(input.rootSeed, input.recipeSeed);
    const auto persistent = stableId(
        session, 0x7f0b'2a27'a8c2'7f83ull, address);
    const auto lineageSeed = static_cast<std::uint32_t>(persistent);
    const auto routedHash = fullSubstrateMix32(lineageSeed ^ input.frameOrdinal);
    const auto tag = fullSubstrateMix32(
        klb.low ^ rotateLeft(klb.high, 7u) ^ address ^
        fullSubstrateSeedWord(input.rootSeed, 4u) ^ lineageSeed ^
        rotateLeft(routedHash, 11u));

    const auto qx = q15Coordinate(x, input.width);
    const auto qy = -q15Coordinate(y, input.height);
    const auto apexX = static_cast<std::int32_t>(
        fullSubstrateSeedWord(input.rootSeed, 8u) & 8191u) - 4096;
    const auto apexY = static_cast<std::int32_t>(
        16384u + (fullSubstrateSeedWord(input.rootSeed, 9u) & 4095u));
    const auto cone = fullSubstrateConeProfile(input.rootSeed);
    const auto guard = 32u + (fullSubstrateSeedWord(input.rootSeed, 12u) & 127u);
    const auto radial = abs32(qx - apexX);
    const auto down = apexY - qy;
    const auto insideAxial = down >= 0 &&
                             static_cast<std::uint32_t>(down) <= cone.height;
    const auto sideLeft = radial * cone.height;
    const auto sideRight = down >= 0
        ? static_cast<std::uint32_t>(down) * cone.baseRadius
        : 0u;
    const auto insideCone = insideAxial && sideLeft <= sideRight;
    const auto withinSquaredGuard = [guard](std::uint32_t dx, std::uint32_t dy) {
        return dx <= guard && dy <= guard &&
               dx * dx + dy * dy <= guard * guard;
    };
    const auto apexGuard = withinSquaredGuard(radial, abs32(down));
    const auto cornerDx = absDifference(radial, cone.baseRadius);
    const auto cornerDy = abs32(down - static_cast<std::int32_t>(cone.height));
    const auto cornerNear = withinSquaredGuard(cornerDx, cornerDy);
    const auto dot = static_cast<std::int32_t>(radial * cone.baseRadius) +
                     down * static_cast<std::int32_t>(cone.height);
    const auto cross = static_cast<std::int32_t>(radial * cone.height) -
                       down * static_cast<std::int32_t>(cone.baseRadius);
    const auto tSquared = cone.slantT * cone.slantT;
    bool sideNear = false;
    if (dot < 0) sideNear = apexGuard;
    else if (static_cast<std::uint32_t>(dot) > tSquared) sideNear = cornerNear;
    else sideNear = abs32(cross) <= guard * cone.slantT;
    const auto baseNear = radial <= cone.baseRadius
        ? abs32(down - static_cast<std::int32_t>(cone.height)) <= guard
        : cornerNear;
    const auto nearCone = sideNear || baseNear;

    const auto sphereRadius = 3072u +
                              (fullSubstrateSeedWord(input.rootSeed, 13u) & 2047u);
    const auto sphereY = static_cast<std::int32_t>(
        fullSubstrateSeedWord(input.rootSeed, 14u) & 8191u) - 4096;
    const auto sphereOffset = sphereRadius + 2048u +
                              (fullSubstrateSeedWord(input.rootSeed, 15u) & 2047u);
    const auto sphereLeftX = apexX - static_cast<std::int32_t>(sphereOffset);
    const auto sphereRightX = apexX + static_cast<std::int32_t>(sphereOffset);
    const auto sphereClass = [&](std::int32_t centerX) {
        const auto dx = abs32(qx - centerX);
        const auto dy = abs32(qy - sphereY);
        const auto distance2 = dx * dx + dy * dy;
        const auto radius2 = sphereRadius * sphereRadius;
        const auto inner = sphereRadius > guard ? sphereRadius - guard : 0u;
        const auto outer = sphereRadius + guard;
        return std::array<bool, 2u>{
            distance2 <= radius2,
            distance2 >= inner * inner && distance2 <= outer * outer,
        };
    };
    const auto leftSphere = sphereClass(sphereLeftX);
    const auto rightSphere = sphereClass(sphereRightX);
    const auto insideSphere = leftSphere[0] || rightSphere[0];
    const auto nearSphere = leftSphere[1] || rightSphere[1];

    const auto left = kleinAddress(
        static_cast<std::int32_t>(x) - 1,
        static_cast<std::int32_t>(y), input.width, input.height);
    const auto up = kleinAddress(
        static_cast<std::int32_t>(x),
        static_cast<std::int32_t>(y) - 1, input.width, input.height);
    const auto upLeft = kleinAddress(
        static_cast<std::int32_t>(x) - 1,
        static_cast<std::int32_t>(y) - 1, input.width, input.height);

    const auto topology = (orientation ^ static_cast<std::uint32_t>(insideCone) ^
        static_cast<std::uint32_t>(insideSphere) ^
        static_cast<std::uint32_t>(nearCone) ^
        static_cast<std::uint32_t>(nearSphere) ^
        static_cast<std::uint32_t>(apexGuard)) & 1u;
    std::uint32_t node = 0u;
    std::uint32_t prefix = 0u;
    for (std::uint32_t depth = 0u; depth < FullSubstrateRadixDepth; ++depth) {
        const auto radix = (morton.high >> (31u - depth)) & 1u;
        const auto decisionParity = parity32(
            klb.low ^ klb.high ^ tag ^
            fullSubstrateSeedWord(input.rootSeed, 32u + depth) ^ node);
        const auto branch = radix ^ decisionParity ^ topology;
        prefix = ((prefix << 1u) | branch) & 0xffffu;
        node = node * 2u + 1u + branch;
        phi += omega;
        omega += alpha;
    }
    const auto selector = (node ^ tag ^ (phi >> 24u) ^ (omega >> 16u) ^
        (alpha >> 8u) ^ static_cast<std::uint32_t>(insideCone) ^
        static_cast<std::uint32_t>(insideSphere) ^
        static_cast<std::uint32_t>(nearCone) ^
        static_cast<std::uint32_t>(nearSphere) ^
        static_cast<std::uint32_t>(apexGuard)) & 3u;

    std::uint32_t packedState = elevation10 |
        (symbol3 << FullStateSymbolShift) |
        (selector << FullStateSelectorShift);
    if (radialOdd) packedState |= FullStateRadialWrapOddBit;
    if (orientation != 0u) packedState |= FullStateOrientationBit;
    if (left.reflected) packedState |= FullStateKleinLeftReflectedBit;
    if (up.reflected) packedState |= FullStateKleinUpReflectedBit;
    if (upLeft.reflected) packedState |= FullStateKleinUpLeftReflectedBit;
    if (insideCone) packedState |= FullStateInsideConeBit;
    if (nearCone) packedState |= FullStateNearConeBit;
    if (insideSphere) packedState |= FullStateInsideSphereBit;
    if (nearSphere) packedState |= FullStateNearSphereBit;
    if (apexGuard) packedState |= FullStateApexGuardBit;
    if ((node & 0x1'0000u) != 0u) packedState |= FullStateNodeHighBit;
    packedState |= cone.tripleIndex << FullStateConeTripleShift;

    FullSubstrateLaneReceipt receipt{};
    receipt.words = {
        address,
        input.sourceRho20,
        input.sourceTheta18,
        wrappedRho20,
        topologicalTheta18,
        key.low,
        key.high,
        morton.low,
        morton.high,
        klb.low,
        klb.high,
        phi,
        omega,
        alpha,
        (node & 0xffffu) | (prefix << 16u),
        packedState,
        left.address,
        up.address,
        upLeft.address,
        tag,
    };
    return receipt;
}

std::vector<std::uint8_t> packFullSubstrateLaneReceipt(
    const FullSubstrateLaneReceipt& receipt
) {
    std::vector<std::uint8_t> bytes;
    bytes.reserve(FullSubstrateReceiptWords * 4u);
    for (const auto word : receipt.words) appendU32(bytes, word);
    return bytes;
}

FullSubstratePrediction buildFullSubstrateCameraPrediction(
    std::uint32_t width,
    std::uint32_t height,
    std::uint64_t rootSeed,
    std::uint64_t recipeSeed,
    std::uint32_t frameOrdinal,
    const SeededUglut2Traversal& traversal,
    const FullSubstratePreviousFrame& previous,
    std::uint32_t blockLumaAddresses
) {
    require(width >= 2u && height >= 2u && width <= 65534u && height <= 65534u &&
                (width & 1u) == 0u && (height & 1u) == 0u,
            "prediction dimensions must be bounded even YUV420");
    const auto yBytes = static_cast<std::size_t>(width) * height;
    const auto chromaWidth = width / 2u;
    const auto chromaHeight = height / 2u;
    const auto cBytes = static_cast<std::size_t>(chromaWidth) * chromaHeight;
    require(previous.y.data != nullptr && previous.u.data != nullptr &&
                previous.v.data != nullptr && previous.y.size == yBytes &&
                previous.u.size == cBytes && previous.v.size == cBytes,
            "previous exact dense plane sizes are invalid");
    require(blockLumaAddresses >= 1u && blockLumaAddresses <= 65536u,
            "block luma-address count is invalid");
    require(traversal.width == width && traversal.height == height &&
                traversal.polarOrdinalToCartesian.size() == yBytes &&
                traversal.rho20ByCartesian.size() == yBytes &&
                traversal.theta18ByCartesian.size() == yBytes,
            "UGLUT2 traversal lacks profile-2 rho/theta state");

    FullSubstratePrediction result{};
    result.canonicalOwnerPrediction.reserve(yBytes + cBytes * 2u);
    const auto blockCount = (yBytes + blockLumaAddresses - 1u) / blockLumaAddresses;
    result.blocks.reserve(blockCount);
    for (std::size_t first = 0u; first < yBytes; first += blockLumaAddresses) {
        const auto count = std::min<std::size_t>(blockLumaAddresses, yBytes - first);
        std::vector<FullSubstrateLaneReceipt> receipts;
        receipts.reserve(count);
        FullSubstrateBlockReceipt block{};
        block.firstLumaOrdinal = static_cast<std::uint32_t>(first);
        block.lumaCount = static_cast<std::uint32_t>(count);
        for (std::size_t local = 0u; local < count; ++local) {
            const auto ordinal = first + local;
            const auto address = traversal.polarOrdinalToCartesian[ordinal];
            const auto receipt = evaluateFullSubstrateCameraLane(FullSubstrateLaneInput{
                width,
                height,
                rootSeed,
                recipeSeed,
                frameOrdinal,
                address,
                traversal.rho20ByCartesian[address],
                traversal.theta18ByCartesian[address],
            });
            const auto selector = receipt.predictor();
            ++block.selectorCounts[static_cast<std::size_t>(selector)];
            result.canonicalOwnerPrediction.push_back(selectPredictor(
                selector,
                previous.y.data,
                previous.y.size,
                address,
                receipt.words[ReceiptKleinLeftAddress],
                receipt.words[ReceiptKleinUpAddress],
                receipt.words[ReceiptKleinUpLeftAddress]));
            const auto x = address % width;
            const auto y = address / width;
            if ((x & 1u) == 0u && (y & 1u) == 0u) {
                const auto cx = x / 2u;
                const auto cy = y / 2u;
                const auto same = cy * chromaWidth + cx;
                const auto left = kleinAddress(
                    static_cast<std::int32_t>(cx) - 1,
                    static_cast<std::int32_t>(cy), chromaWidth, chromaHeight).address;
                const auto up = kleinAddress(
                    static_cast<std::int32_t>(cx),
                    static_cast<std::int32_t>(cy) - 1, chromaWidth, chromaHeight).address;
                const auto upLeft = kleinAddress(
                    static_cast<std::int32_t>(cx) - 1,
                    static_cast<std::int32_t>(cy) - 1,
                    chromaWidth, chromaHeight).address;
                result.canonicalOwnerPrediction.push_back(selectPredictor(
                    selector, previous.u.data, previous.u.size,
                    same, left, up, upLeft));
                result.canonicalOwnerPrediction.push_back(selectPredictor(
                    selector, previous.v.data, previous.v.size,
                    same, left, up, upLeft));
            }
            receipts.push_back(receipt);
        }
        block.operatorStateSha256 = blockDigest(
            frameOrdinal, block.firstLumaOrdinal, receipts);
        result.blocks.push_back(block);
    }
    require(result.canonicalOwnerPrediction.size() == yBytes + cBytes * 2u,
            "canonical owner prediction length mismatch");

    auto frameBytes = domain("UGCAMNODE-FX1-frame-receipts-v0.1.0");
    appendU32(frameBytes, width);
    appendU32(frameBytes, height);
    appendU32(frameBytes, frameOrdinal);
    appendU32(frameBytes, blockLumaAddresses);
    appendU32(frameBytes, static_cast<std::uint32_t>(result.blocks.size()));
    for (const auto& block : result.blocks) {
        appendU32(frameBytes, block.firstLumaOrdinal);
        appendU32(frameBytes, block.lumaCount);
        for (const auto count : block.selectorCounts) appendU32(frameBytes, count);
        appendDigest(frameBytes, block.operatorStateSha256);
    }
    result.frameOperatorStateSha256 = sha256(frameBytes.data(), frameBytes.size());
    return result;
}

Sha256Digest fullSubstrateCameraOperatorDigest() {
    const auto bytes = domain(
        "UGCAMNODE-FX1-v0.1.0;profile=2;rho=UGLUT2-rho20;theta=UGLUT2-theta18;"
        "key64=rho20|theta18|frame14|lowercase-phi12;morton=msb-round-robin;"
        "klb37=rho11|theta12|elevation10|symbol3|even-parity;radix-depth=16;"
        "node=2n+1+branch;klein=y-seam-x-reflection;sclp-odd-wrap=reflect-negate;"
        "gsp4-lineage=SplitMix64(root,recipe,namespace,address)+routed-mix32;"
        "guards=integer-index-pythagorean-delta-T-filled-triangle-segments+"
        "paired-sphere+euclidean-apex;"
        "cone-LUT=(3,4,5),(5,12,13),(8,15,17),(7,24,25),(20,21,29),"
        "(12,35,37),(9,40,41),(28,45,53);cone-index=G16&7;"
        "cone-scale=256+(G17&255);T^2=R^2+h^2;"
        "predictors=previous-same,klein-left,klein-up,klein-med;residual=mod256"
    );
    return sha256(bytes.data(), bytes.size());
}

} // namespace ugts::chrono
