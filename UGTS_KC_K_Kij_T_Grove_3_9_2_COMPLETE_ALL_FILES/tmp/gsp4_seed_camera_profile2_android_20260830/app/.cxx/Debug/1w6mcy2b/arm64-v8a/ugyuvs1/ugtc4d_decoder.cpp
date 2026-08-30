#include "ugtc4d_decoder.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <limits>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>
#include <tuple>
#include <utility>

namespace ugts::chrono {
namespace {

constexpr std::size_t ContainerHeaderBytes = 256u;
constexpr std::size_t DirectoryEntryBytes = 112u;
constexpr std::size_t ContainerContentDigestOffset = 216u;
constexpr std::size_t FrameHeaderBytes = 320u;
constexpr std::size_t FrameContentDigestOffset = 260u;
constexpr std::size_t RiceHeaderBytes = 160u;
constexpr std::size_t RiceContentDigestOffset = 108u;
constexpr std::size_t Alignment = 64u;
constexpr std::uint32_t RequiredContainerFlags = 0x0fu;
constexpr std::uint32_t RunTokensFlag = 1u;
constexpr std::uint32_t OptionalSectionFlag = 2u;
constexpr std::uint32_t FrameCheckpointFlag = 1u;
constexpr std::uint32_t NoPreviousOrdinal = 0xffffffffu;
constexpr std::uint32_t PredictorTemporalSubstrateMedianGreen = 11u;
constexpr std::uint32_t PredictorCartesianMedianGreenLumaLift = 13u;
constexpr std::uint32_t PredictorCartesianMedianQ709Codeword = 14u;
constexpr std::uint64_t Golden64 = 0x9e3779b97f4a7c15ull;
constexpr std::uint64_t Fnv64Offset = 0xcbf29ce484222325ull;
constexpr std::uint64_t Fnv64Prime = 0x100000001b3ull;
constexpr std::uint32_t RansScaleBits = 12u;
constexpr std::uint32_t RansTotalFrequency = 1u << RansScaleBits;
constexpr std::uint32_t RansByteL = 1u << 23u;

[[noreturn]] void fail(const std::string& message) {
    throw std::runtime_error("UGTC4D native decoder: " + message);
}

void require(bool condition, const std::string& message) {
    if (!condition) fail(message);
}

std::size_t checkedSize(std::uint64_t value, const char* label) {
    require(value <= static_cast<std::uint64_t>(std::numeric_limits<std::size_t>::max()),
            std::string(label) + " exceeds host address space");
    return static_cast<std::size_t>(value);
}

std::size_t alignUp(std::size_t value) {
    require(value <= std::numeric_limits<std::size_t>::max() - (Alignment - 1u),
            "alignment overflow");
    return ((value + Alignment - 1u) / Alignment) * Alignment;
}

class Reader final {
public:
    Reader(const std::uint8_t* data, std::size_t size) : data_(data), size_(size) {}

    const std::uint8_t* raw(std::size_t count) {
        require(count <= size_ - offset_, "truncated binary record");
        const auto* result = data_ + offset_;
        offset_ += count;
        return result;
    }

    std::uint8_t u8() { return *raw(1u); }
    std::uint16_t u16() {
        const auto* p = raw(2u);
        return static_cast<std::uint16_t>(p[0]) |
               static_cast<std::uint16_t>(static_cast<std::uint16_t>(p[1]) << 8u);
    }
    std::uint32_t u32() {
        const auto* p = raw(4u);
        return static_cast<std::uint32_t>(p[0]) |
               (static_cast<std::uint32_t>(p[1]) << 8u) |
               (static_cast<std::uint32_t>(p[2]) << 16u) |
               (static_cast<std::uint32_t>(p[3]) << 24u);
    }
    std::uint64_t u64() {
        const auto low = static_cast<std::uint64_t>(u32());
        return low | (static_cast<std::uint64_t>(u32()) << 32u);
    }
    std::int64_t i64() { return static_cast<std::int64_t>(u64()); }
    double f64() {
        static_assert(sizeof(double) == sizeof(std::uint64_t), "binary64 is required");
        const auto bits = u64();
        double result = 0.0;
        std::memcpy(&result, &bits, sizeof(result));
        return result;
    }
    std::size_t position() const noexcept { return offset_; }
    std::size_t remaining() const noexcept { return size_ - offset_; }

private:
    const std::uint8_t* data_ = nullptr;
    std::size_t size_ = 0u;
    std::size_t offset_ = 0u;
};

bool allZero(const std::uint8_t* data, std::size_t size) {
    return std::all_of(data, data + size, [](std::uint8_t value) { return value == 0u; });
}

Sha256Digest readDigest(Reader& reader) {
    Sha256Digest result{};
    std::memcpy(result.data(), reader.raw(result.size()), result.size());
    return result;
}

class Sha256 final {
public:
    Sha256() = default;

    void update(const std::uint8_t* data, std::size_t size) {
        require(!finished_, "SHA-256 update after finalization");
        require(size <= (std::numeric_limits<std::uint64_t>::max() - totalBytes_),
                "SHA-256 input length overflow");
        totalBytes_ += static_cast<std::uint64_t>(size);
        while (size > 0u) {
            const auto take = std::min(size, block_.size() - buffered_);
            std::memcpy(block_.data() + buffered_, data, take);
            buffered_ += take;
            data += take;
            size -= take;
            if (buffered_ == block_.size()) {
                compress(block_.data());
                buffered_ = 0u;
            }
        }
    }

    Sha256Digest finish() {
        require(!finished_, "SHA-256 finalized twice");
        finished_ = true;
        const auto bitLength = totalBytes_ * 8u;
        block_[buffered_++] = 0x80u;
        if (buffered_ > 56u) {
            std::fill(block_.begin() + static_cast<std::ptrdiff_t>(buffered_), block_.end(),
                      std::uint8_t{0});
            compress(block_.data());
            buffered_ = 0u;
        }
        std::fill(block_.begin() + static_cast<std::ptrdiff_t>(buffered_), block_.begin() + 56,
                  std::uint8_t{0});
        for (unsigned index = 0u; index < 8u; ++index) {
            block_[63u - index] = static_cast<std::uint8_t>(bitLength >> (index * 8u));
        }
        compress(block_.data());
        Sha256Digest result{};
        for (std::size_t index = 0u; index < state_.size(); ++index) {
            result[index * 4u] = static_cast<std::uint8_t>(state_[index] >> 24u);
            result[index * 4u + 1u] = static_cast<std::uint8_t>(state_[index] >> 16u);
            result[index * 4u + 2u] = static_cast<std::uint8_t>(state_[index] >> 8u);
            result[index * 4u + 3u] = static_cast<std::uint8_t>(state_[index]);
        }
        return result;
    }

private:
    static std::uint32_t rotateRight(std::uint32_t value, unsigned shift) {
        return (value >> shift) | (value << (32u - shift));
    }

    void compress(const std::uint8_t* block) {
        static constexpr std::array<std::uint32_t, 64> constants{{
            0x428a2f98u,0x71374491u,0xb5c0fbcfu,0xe9b5dba5u,0x3956c25bu,0x59f111f1u,0x923f82a4u,0xab1c5ed5u,
            0xd807aa98u,0x12835b01u,0x243185beu,0x550c7dc3u,0x72be5d74u,0x80deb1feu,0x9bdc06a7u,0xc19bf174u,
            0xe49b69c1u,0xefbe4786u,0x0fc19dc6u,0x240ca1ccu,0x2de92c6fu,0x4a7484aau,0x5cb0a9dcu,0x76f988dau,
            0x983e5152u,0xa831c66du,0xb00327c8u,0xbf597fc7u,0xc6e00bf3u,0xd5a79147u,0x06ca6351u,0x14292967u,
            0x27b70a85u,0x2e1b2138u,0x4d2c6dfcu,0x53380d13u,0x650a7354u,0x766a0abbu,0x81c2c92eu,0x92722c85u,
            0xa2bfe8a1u,0xa81a664bu,0xc24b8b70u,0xc76c51a3u,0xd192e819u,0xd6990624u,0xf40e3585u,0x106aa070u,
            0x19a4c116u,0x1e376c08u,0x2748774cu,0x34b0bcb5u,0x391c0cb3u,0x4ed8aa4au,0x5b9cca4fu,0x682e6ff3u,
            0x748f82eeu,0x78a5636fu,0x84c87814u,0x8cc70208u,0x90befffau,0xa4506cebu,0xbef9a3f7u,0xc67178f2u,
        }};
        std::array<std::uint32_t, 64> words{};
        for (std::size_t index = 0u; index < 16u; ++index) {
            const auto* p = block + index * 4u;
            words[index] = (static_cast<std::uint32_t>(p[0]) << 24u) |
                           (static_cast<std::uint32_t>(p[1]) << 16u) |
                           (static_cast<std::uint32_t>(p[2]) << 8u) |
                           static_cast<std::uint32_t>(p[3]);
        }
        for (std::size_t index = 16u; index < words.size(); ++index) {
            const auto x = words[index - 15u];
            const auto y = words[index - 2u];
            const auto small0 = rotateRight(x, 7u) ^ rotateRight(x, 18u) ^ (x >> 3u);
            const auto small1 = rotateRight(y, 17u) ^ rotateRight(y, 19u) ^ (y >> 10u);
            words[index] = words[index - 16u] + small0 + words[index - 7u] + small1;
        }
        auto a = state_[0]; auto b = state_[1]; auto c = state_[2]; auto d = state_[3];
        auto e = state_[4]; auto f = state_[5]; auto g = state_[6]; auto h = state_[7];
        for (std::size_t index = 0u; index < words.size(); ++index) {
            const auto big1 = rotateRight(e, 6u) ^ rotateRight(e, 11u) ^ rotateRight(e, 25u);
            const auto choice = (e & f) ^ ((~e) & g);
            const auto temp1 = h + big1 + choice + constants[index] + words[index];
            const auto big0 = rotateRight(a, 2u) ^ rotateRight(a, 13u) ^ rotateRight(a, 22u);
            const auto majority = (a & b) ^ (a & c) ^ (b & c);
            const auto temp2 = big0 + majority;
            h = g; g = f; f = e; e = d + temp1;
            d = c; c = b; b = a; a = temp1 + temp2;
        }
        state_[0] += a; state_[1] += b; state_[2] += c; state_[3] += d;
        state_[4] += e; state_[5] += f; state_[6] += g; state_[7] += h;
    }

    std::array<std::uint32_t, 8> state_{{
        0x6a09e667u,0xbb67ae85u,0x3c6ef372u,0xa54ff53au,
        0x510e527fu,0x9b05688cu,0x1f83d9abu,0x5be0cd19u,
    }};
    std::array<std::uint8_t, 64> block_{};
    std::size_t buffered_ = 0u;
    std::uint64_t totalBytes_ = 0u;
    bool finished_ = false;
};

Sha256Digest sha256WithZeroRange(
    const std::uint8_t* data,
    std::size_t size,
    std::size_t zeroOffset,
    std::size_t zeroBytes
) {
    require(zeroOffset <= size && zeroBytes <= size - zeroOffset,
            "SHA-256 zero range is outside its record");
    Sha256 hasher;
    hasher.update(data, zeroOffset);
    std::array<std::uint8_t, 64> zeros{};
    auto remaining = zeroBytes;
    while (remaining > 0u) {
        const auto take = std::min(remaining, zeros.size());
        hasher.update(zeros.data(), take);
        remaining -= take;
    }
    hasher.update(data + zeroOffset + zeroBytes, size - zeroOffset - zeroBytes);
    return hasher.finish();
}

void appendU32(std::vector<std::uint8_t>& output, std::uint32_t value) {
    output.push_back(static_cast<std::uint8_t>(value));
    output.push_back(static_cast<std::uint8_t>(value >> 8u));
    output.push_back(static_cast<std::uint8_t>(value >> 16u));
    output.push_back(static_cast<std::uint8_t>(value >> 24u));
}

void appendU64(std::vector<std::uint8_t>& output, std::uint64_t value) {
    appendU32(output, static_cast<std::uint32_t>(value));
    appendU32(output, static_cast<std::uint32_t>(value >> 32u));
}

std::vector<std::uint8_t> encodeRunTokens(const std::vector<std::uint8_t>& source) {
    std::vector<std::uint8_t> output;
    std::size_t position = 0u;
    const auto repeatedLength = [&](std::size_t offset, std::size_t maximum) {
        const auto value = source[offset];
        const auto end = std::min(source.size(), offset + maximum);
        auto index = offset + 1u;
        while (index < end && source[index] == value) ++index;
        return index - offset;
    };
    while (position < source.size()) {
        const auto value = source[position];
        if (value == 0u) {
            const auto length = repeatedLength(position, 64u);
            output.push_back(static_cast<std::uint8_t>(length - 1u));
            position += length;
            continue;
        }
        const auto repeat = repeatedLength(position, 66u);
        if (repeat >= 3u) {
            output.push_back(static_cast<std::uint8_t>(0x40u | (repeat - 3u)));
            output.push_back(value);
            position += repeat;
            continue;
        }
        const auto start = position;
        position += repeat;
        while (position < source.size() && position - start < 64u) {
            if (source[position] == 0u) break;
            const auto candidate = repeatedLength(position, 66u);
            if (candidate >= 3u || position - start + candidate > 64u) break;
            position += candidate;
        }
        output.push_back(static_cast<std::uint8_t>(0x80u | (position - start - 1u)));
        output.insert(output.end(), source.begin() + static_cast<std::ptrdiff_t>(start),
                      source.begin() + static_cast<std::ptrdiff_t>(position));
    }
    return output;
}

std::vector<std::uint8_t> decodeRunTokens(
    const std::uint8_t* data,
    std::size_t size,
    std::size_t expected
) {
    std::vector<std::uint8_t> output;
    output.reserve(expected);
    std::size_t position = 0u;
    while (position < size) {
        const auto control = data[position++];
        const auto kind = control >> 6u;
        const auto code = control & 0x3fu;
        if (kind == 0u) {
            output.insert(output.end(), static_cast<std::size_t>(code) + 1u, 0u);
        } else if (kind == 1u) {
            require(position < size, "truncated metadata repeat token");
            const auto value = data[position++];
            require(value != 0u, "metadata repeat token encodes zero noncanonically");
            output.insert(output.end(), static_cast<std::size_t>(code) + 3u, value);
        } else if (kind == 2u) {
            const auto count = static_cast<std::size_t>(code) + 1u;
            require(count <= size - position, "truncated metadata literal token");
            output.insert(output.end(), data + position, data + position + count);
            position += count;
        } else {
            fail("reserved metadata run token");
        }
        require(output.size() <= expected, "metadata run tokens exceed logical length");
    }
    require(output.size() == expected, "metadata run-token logical length mismatch");
    require(encodeRunTokens(output) == std::vector<std::uint8_t>(data, data + size),
            "metadata run-token stream is noncanonical");
    return output;
}

std::uint64_t splitmix64(std::uint64_t value) {
    value += Golden64;
    value = (value ^ (value >> 30u)) * 0xbf58476d1ce4e5b9ull;
    value = (value ^ (value >> 27u)) * 0x94d049bb133111ebull;
    return value ^ (value >> 31u);
}

std::uint64_t hash64(const std::string& text) {
    auto value = Fnv64Offset;
    for (const auto character : text) {
        value = (value ^ static_cast<std::uint8_t>(character)) * Fnv64Prime;
    }
    return splitmix64(value ^ static_cast<std::uint64_t>(text.size()));
}

std::uint64_t combineSeed(std::uint64_t seed, std::uint64_t value) {
    const auto mixed = splitmix64(value) + Golden64 + (seed << 6u) + (seed >> 2u);
    return splitmix64(seed ^ mixed);
}

std::uint64_t stableId(
    std::uint64_t sessionSeed,
    std::uint64_t namespaceId,
    std::uint64_t address
) {
    return combineSeed(combineSeed(sessionSeed, namespaceId), address);
}

std::int64_t halfWordToFixed(std::uint16_t word, int fractionalBits) {
    const auto negative = (word & 0x8000u) != 0u;
    const auto exponent = static_cast<int>((word >> 10u) & 0x1fu);
    const auto fraction = static_cast<std::uint64_t>(word & 0x03ffu);
    require(exponent != 0x1f, "UGLUT2 contains a non-finite binary16 lane");
    const auto mantissa = exponent == 0 ? fraction : 1024u + fraction;
    const auto power = exponent == 0 ? -24 + fractionalBits : exponent - 25 + fractionalBits;
    if (mantissa == 0u) return 0;
    std::uint64_t magnitude = 0u;
    if (power >= 0) {
        require(power < 63 && mantissa <= (std::numeric_limits<std::uint64_t>::max() >> power),
                "binary16 fixed conversion overflow");
        magnitude = mantissa << power;
    } else {
        const auto shift = static_cast<unsigned>(-power);
        require(shift < 63u, "binary16 fixed conversion shift overflow");
        const auto denominator = 1ull << shift;
        const auto quotient = mantissa / denominator;
        const auto remainder = mantissa % denominator;
        const auto halfway = denominator >> 1u;
        magnitude = quotient + static_cast<std::uint64_t>(
            remainder > halfway || (remainder == halfway && (quotient & 1u) != 0u));
    }
    require(magnitude <= static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max()),
            "binary16 fixed conversion exceeds int64");
    const auto signedMagnitude = static_cast<std::int64_t>(magnitude);
    return negative ? -signedMagnitude : signedMagnitude;
}

std::uint8_t moduloByte(std::int64_t value) {
    return static_cast<std::uint8_t>(static_cast<std::uint64_t>(value) & 0xffu);
}

std::int16_t signedByte(std::uint8_t value) {
    return value < 128u ? static_cast<std::int16_t>(value)
                        : static_cast<std::int16_t>(static_cast<int>(value) - 256);
}

int floorDivide(int value, int positiveDivisor) {
    require(positiveDivisor > 0, "floor division requires a positive divisor");
    return value >= 0
        ? value / positiveDivisor
        : -((-value + positiveDivisor - 1) / positiveDivisor);
}

std::vector<std::uint8_t> decodeRiceStream(const std::uint8_t* data, std::size_t size) {
    require(size >= RiceHeaderBytes, "UGRICE1 header is truncated");
    Reader reader(data, size);
    require(std::memcmp(reader.raw(8u), "UGRICE1\0", 8u) == 0, "UGRICE1 magic mismatch");
    require(reader.u16() == 1u && reader.u16() == 0u, "unsupported UGRICE1 version");
    require(reader.u32() == RiceHeaderBytes, "UGRICE1 header size mismatch");
    require(reader.u32() == 1u, "UGRICE1 flags are unsupported");
    const auto logicalBytes64 = reader.u64();
    const auto blockBytes = reader.u32();
    const auto blockCount = reader.u32();
    const auto payloadBytes64 = reader.u64();
    const auto decodedDigest = readDigest(reader);
    const auto payloadDigest = readDigest(reader);
    const auto contentDigest = readDigest(reader);
    require(allZero(reader.raw(20u), 20u), "UGRICE1 reserved bytes are nonzero");
    require(blockBytes >= 256u && blockBytes <= (1u << 20u) &&
                (blockBytes & (blockBytes - 1u)) == 0u,
            "UGRICE1 block size is invalid");
    const auto logicalBytes = checkedSize(logicalBytes64, "UGRICE1 logical length");
    const auto payloadBytes = checkedSize(payloadBytes64, "UGRICE1 payload length");
    const auto expectedBlocks = logicalBytes == 0u
        ? 0u
        : static_cast<std::uint32_t>((logicalBytes - 1u) / blockBytes + 1u);
    require(blockCount == expectedBlocks, "UGRICE1 block count mismatch");
    require(payloadBytes <= logicalBytes + static_cast<std::size_t>(blockCount) * 8u,
            "UGRICE1 payload exceeds raw fallback bound");
    require(size == RiceHeaderBytes + payloadBytes, "UGRICE1 payload length mismatch");
    const auto* payload = data + RiceHeaderBytes;
    require(sha256(payload, payloadBytes) == payloadDigest, "UGRICE1 payload SHA-256 mismatch");
    require(sha256WithZeroRange(data, size, RiceContentDigestOffset, 32u) == contentDigest,
            "UGRICE1 content SHA-256 mismatch");

    std::vector<std::uint8_t> output;
    output.reserve(logicalBytes);
    std::size_t position = 0u;
    for (std::uint32_t blockIndex = 0u; blockIndex < blockCount; ++blockIndex) {
        require(position + 8u <= payloadBytes, "UGRICE1 block header is truncated");
        Reader blockReader(payload + position, payloadBytes - position);
        const auto method = blockReader.u8();
        const auto riceK = blockReader.u8();
        require(blockReader.u16() == 0u, "UGRICE1 block reserved field is nonzero");
        const auto encodedBits = blockReader.u32();
        position += 8u;
        const auto symbols = std::min<std::size_t>(blockBytes, logicalBytes - output.size());
        require(symbols > 0u, "UGRICE1 contains an excess block");
        std::size_t codedBytes = 0u;
        if (method == 0u) {
            require(riceK == 0u && encodedBits == symbols * 8u,
                    "UGRICE1 RAW metadata is noncanonical");
            codedBytes = symbols;
        } else if (method == 1u) {
            require(riceK <= 7u && encodedBits > 0u && encodedBits < symbols * 8u,
                    "UGRICE1 Rice metadata is invalid");
            codedBytes = (static_cast<std::size_t>(encodedBits) + 7u) / 8u;
        } else if (method == 2u) {
            require(riceK == 0u && (encodedBits & 7u) == 0u &&
                        encodedBits > 0u && encodedBits < symbols * 8u,
                    "UGRICE1 rANS metadata is invalid");
            codedBytes = encodedBits / 8u;
        } else {
            fail("unsupported UGRICE1 block method");
        }
        require(codedBytes <= payloadBytes - position, "UGRICE1 block payload is truncated");
        const auto* coded = payload + position;
        position += codedBytes;

        if (method == 0u) {
            output.insert(output.end(), coded, coded + codedBytes);
            continue;
        }
        if (method == 1u) {
            if ((encodedBits & 7u) != 0u) {
                const auto unused = 8u - (encodedBits & 7u);
                require((coded[codedBytes - 1u] & ((1u << unused) - 1u)) == 0u,
                        "UGRICE1 Rice padding bits are nonzero");
            }
            std::size_t bitPosition = 0u;
            for (std::size_t symbolIndex = 0u; symbolIndex < symbols; ++symbolIndex) {
                std::uint32_t quotient = 0u;
                while (true) {
                    require(bitPosition < encodedBits, "UGRICE1 Rice unary code is truncated");
                    const auto bit = (coded[bitPosition >> 3u] >>
                                      (7u - static_cast<unsigned>(bitPosition & 7u))) & 1u;
                    ++bitPosition;
                    if (bit != 0u) break;
                    ++quotient;
                    require(quotient <= (255u >> riceK),
                            "UGRICE1 Rice symbol exceeds byte alphabet");
                }
                std::uint32_t remainder = 0u;
                for (std::uint8_t index = 0u; index < riceK; ++index) {
                    require(bitPosition < encodedBits, "UGRICE1 Rice remainder is truncated");
                    remainder = (remainder << 1u) |
                        ((coded[bitPosition >> 3u] >>
                          (7u - static_cast<unsigned>(bitPosition & 7u))) & 1u);
                    ++bitPosition;
                }
                const auto mapped = (quotient << riceK) | remainder;
                require(mapped <= 255u, "UGRICE1 Rice symbol exceeds byte alphabet");
                const auto value = (mapped & 1u) == 0u
                    ? mapped >> 1u
                    : (256u - ((mapped + 1u) >> 1u)) & 0xffu;
                output.push_back(static_cast<std::uint8_t>(value));
            }
            require(bitPosition == encodedBits, "UGRICE1 Rice block has unused coded bits");
            continue;
        }

        require(codedBytes >= 36u, "UGRICE1 rANS block is truncated before table/state");
        const auto* presence = coded;
        std::vector<std::uint16_t> used;
        for (std::uint16_t symbol = 0u; symbol < 256u; ++symbol) {
            if ((presence[symbol >> 3u] & (1u << (symbol & 7u))) != 0u) used.push_back(symbol);
        }
        require(!used.empty(), "UGRICE1 rANS symbol table is empty");
        std::array<std::uint32_t, 256> frequencies{};
        std::array<std::uint32_t, 256> starts{};
        std::size_t tablePosition = 32u;
        std::uint32_t cumulative = 0u;
        for (std::size_t usedIndex = 0u; usedIndex + 1u < used.size(); ++usedIndex) {
            const auto varintStart = tablePosition;
            std::uint32_t value = 0u;
            unsigned shift = 0u;
            bool ended = false;
            for (unsigned byteIndex = 0u; byteIndex < 2u; ++byteIndex) {
                require(tablePosition < codedBytes, "UGRICE1 rANS frequency table is truncated");
                const auto byte = coded[tablePosition++];
                value |= static_cast<std::uint32_t>(byte & 0x7fu) << shift;
                if ((byte & 0x80u) == 0u) {
                    ended = true;
                    break;
                }
                shift += 7u;
            }
            require(ended && value >= 1u && value < RansTotalFrequency,
                    "UGRICE1 rANS frequency varint is invalid");
            require((value < 128u && tablePosition - varintStart == 1u) ||
                        (value >= 128u && tablePosition - varintStart == 2u),
                    "UGRICE1 rANS frequency varint is noncanonical");
            frequencies[used[usedIndex]] = value;
            cumulative += value;
            require(cumulative < RansTotalFrequency,
                    "UGRICE1 rANS frequencies exceed fixed total");
        }
        frequencies[used.back()] = RansTotalFrequency - cumulative;
        cumulative = 0u;
        for (std::size_t symbol = 0u; symbol < frequencies.size(); ++symbol) {
            starts[symbol] = cumulative;
            cumulative += frequencies[symbol];
        }
        require(cumulative == RansTotalFrequency, "UGRICE1 rANS frequency total mismatch");
        require(tablePosition + 4u <= codedBytes, "UGRICE1 rANS state is truncated");
        Reader stateReader(coded + tablePosition, codedBytes - tablePosition);
        std::uint64_t state = stateReader.u32();
        tablePosition += 4u;
        require(state >= RansByteL, "UGRICE1 rANS initial state is below lower bound");
        std::array<std::int16_t, RansTotalFrequency> lookup{};
        lookup.fill(-1);
        for (std::size_t symbol = 0u; symbol < frequencies.size(); ++symbol) {
            for (std::uint32_t slot = starts[symbol];
                 slot < starts[symbol] + frequencies[symbol]; ++slot) {
                lookup[slot] = static_cast<std::int16_t>(symbol);
            }
        }
        const auto renormalizedBytes = codedBytes - tablePosition;
        std::size_t consumed = 0u;
        const auto outputStart = output.size();
        for (std::size_t symbolIndex = 0u; symbolIndex < symbols; ++symbolIndex) {
            const auto slot = static_cast<std::uint32_t>(state) & (RansTotalFrequency - 1u);
            const auto symbol = lookup[slot];
            require(symbol >= 0, "UGRICE1 rANS state selected an empty slot");
            output.push_back(static_cast<std::uint8_t>(symbol));
            state = static_cast<std::uint64_t>(frequencies[static_cast<std::size_t>(symbol)]) *
                    (state >> RansScaleBits) +
                    (slot - starts[static_cast<std::size_t>(symbol)]);
            while (state < RansByteL) {
                require(consumed < renormalizedBytes,
                        "UGRICE1 rANS renormalization bytes are truncated");
                state = (state << 8u) | coded[tablePosition + consumed++];
            }
        }
        require(consumed == renormalizedBytes,
                "UGRICE1 rANS block has trailing renormalization bytes");
        require(state == RansByteL, "UGRICE1 rANS terminal state is noncanonical");

        // The table is not merely trusted: reproduce Python's stable
        // largest-remainder normalization from the decoded block.
        std::array<std::uint32_t, 256> counts{};
        for (auto index = outputStart; index < output.size(); ++index) ++counts[output[index]];
        const auto distinct = static_cast<std::uint32_t>(used.size());
        const auto remainingFrequency = RansTotalFrequency - distinct;
        std::array<std::uint32_t, 256> normalized{};
        std::vector<std::pair<std::uint64_t, std::uint16_t>> remainders;
        std::uint32_t allocated = 0u;
        for (const auto symbol : used) {
            const auto numerator = static_cast<std::uint64_t>(counts[symbol]) * remainingFrequency;
            const auto extra = static_cast<std::uint32_t>(numerator / symbols);
            normalized[symbol] = 1u + extra;
            allocated += extra;
            remainders.emplace_back(numerator % symbols, symbol);
        }
        auto leftovers = remainingFrequency - allocated;
        std::sort(remainders.begin(), remainders.end(), [](const auto& left, const auto& right) {
            if (left.first != right.first) return left.first > right.first;
            return left.second < right.second;
        });
        for (std::size_t index = 0u; index < leftovers; ++index) {
            ++normalized[remainders[index].second];
        }
        require(normalized == frequencies,
                "UGRICE1 rANS table is not canonical for the decoded block");
    }
    require(position == payloadBytes, "UGRICE1 payload has trailing bytes");
    require(output.size() == logicalBytes, "UGRICE1 decoded length mismatch");
    require(sha256(output.data(), output.size()) == decodedDigest,
            "UGRICE1 decoded SHA-256 mismatch");
    return output;
}

std::int64_t medianEdge(std::int64_t a, std::int64_t b, std::int64_t c) {
    const auto low = std::min(a, b);
    const auto high = std::max(a, b);
    return std::max(low, std::min(high, a + b - c));
}

std::set<std::string> requiredKinds() {
    return {
        "MANIFEST", "OPERATOR", "UGLUT2", "TRAVERS", "FRAME", "OBSERVE",
        "HYPOTHES", "GEOMETRY", "NOVELTY", "CHECKPNT", "SCENE3D",
    };
}

std::set<std::string> knownKinds() {
    auto result = requiredKinds();
    result.insert("METROLOG");
    return result;
}

const std::string& traversalMeaning() {
    static const std::string value =
        "ugts.kc392.chrono.seeded-log-polar-traversal.v1:"
        "NEW-codec-operator;pixel-address-members;top-left-image-math-up;"
        "canonical-half-pixel-grid-center;"
        "UGTS4.1-splitmix64-lineage(root,recipe,namespace,address);"
        "UGLUT2-binary16-radius-q16-exact-midpoint-ring;"
        "UGLUT2-binary16-direction-q30-exact-cross-wedge;"
        "packed-rho20-closed;packed-theta18-periodic-seeded-origin-direction;"
        "sort=core,rho20,theta18,radius2,sector-cross,lineage,cartesian-address";
    return value;
}

} // namespace

Sha256Digest sha256(const std::uint8_t* data, std::size_t size) {
    require(data != nullptr || size == 0u, "null SHA-256 input");
    Sha256 hasher;
    if (size > 0u) hasher.update(data, size);
    return hasher.finish();
}

std::string sha256Hex(const Sha256Digest& digest) {
    std::ostringstream output;
    output << std::hex << std::setfill('0');
    for (const auto value : digest) output << std::setw(2) << static_cast<unsigned>(value);
    return output.str();
}

Ugtc4dDecoder::Ugtc4dDecoder(std::vector<std::uint8_t> bytes) : bytes_(std::move(bytes)) {
    parseContainer();
    parseSubstrate();
    buildPredictionPlan();
}

Ugtc4dDecoder Ugtc4dDecoder::fromFile(const std::string& path) {
    std::ifstream stream(path, std::ios::binary | std::ios::ate);
    require(stream.good(), "cannot open input file: " + path);
    const auto end = stream.tellg();
    require(end >= 0, "cannot determine input length: " + path);
    const auto length = static_cast<std::uint64_t>(end);
    std::vector<std::uint8_t> bytes(checkedSize(length, "input file"));
    stream.seekg(0, std::ios::beg);
    if (!bytes.empty()) {
        stream.read(reinterpret_cast<char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
        require(stream.good(), "cannot read complete input file: " + path);
    }
    return Ugtc4dDecoder(std::move(bytes));
}

std::vector<std::uint8_t> Ugtc4dDecoder::logicalSection(const SectionView& section) const {
    const auto offset = checkedSize(section.storedOffset, "section offset");
    const auto stored = checkedSize(section.storedBytes, "section stored length");
    const auto logical = checkedSize(section.logicalBytes, "section logical length");
    require(offset <= bytes_.size() && stored <= bytes_.size() - offset,
            "section range escaped file");
    if ((section.flags & RunTokensFlag) != 0u) {
        return decodeRunTokens(bytes_.data() + offset, stored, logical);
    }
    require(stored == logical, "raw section stored/logical length mismatch");
    return {bytes_.begin() + static_cast<std::ptrdiff_t>(offset),
            bytes_.begin() + static_cast<std::ptrdiff_t>(offset + stored)};
}

void Ugtc4dDecoder::parseContainer() {
    require(bytes_.size() >= ContainerHeaderBytes, "container header is truncated");
    require(static_cast<std::uint64_t>(bytes_.size()) <= (1ull << 34u),
            "container exceeds the 16-GiB safety limit");
    Reader reader(bytes_.data(), ContainerHeaderBytes);
    require(std::memcmp(reader.raw(8u), "UGTC4D1\0", 8u) == 0, "container magic mismatch");
    require(reader.u16() == 1u && reader.u16() == 0u, "unsupported container version");
    require(reader.u32() == 0x01020304u, "container endian marker mismatch");
    require(reader.u32() == ContainerHeaderBytes, "container header size mismatch");
    require(reader.u32() == RequiredContainerFlags, "container profile flags mismatch");
    header_.width = reader.u32();
    header_.height = reader.u32();
    require(reader.u32() == 1u && reader.u16() == 3u && reader.u16() == 8u,
            "container is not packed RGB8");
    header_.frameCount = reader.u32();
    header_.checkpointInterval = reader.u32();
    header_.firstSourcePts = reader.i64();
    header_.endSourcePtsExclusive = reader.i64();
    header_.timeBaseNumerator = reader.u64();
    header_.timeBaseDenominator = reader.u64();
    header_.centerX = reader.f64();
    header_.centerY = reader.f64();
    header_.r0 = reader.f64();
    header_.coreRadius = reader.f64();
    header_.rhoMin = reader.f64();
    header_.rhoMax = reader.f64();
    header_.lutResolution = reader.u32();
    const auto sectionCount = reader.u32();
    const auto directoryOffset64 = reader.u64();
    const auto directoryBytes64 = reader.u64();
    header_.sourceSha256 = readDigest(reader);
    header_.decodedStreamSha256 = readDigest(reader);
    const auto contentDigest = readDigest(reader);
    require(allZero(reader.raw(8u), 8u), "container reserved bytes are nonzero");
    require(reader.remaining() == 0u, "container header ABI drift");

    require(header_.width >= 1u && header_.width <= 65535u &&
                header_.height >= 1u && header_.height <= 65535u,
            "container dimensions are invalid");
    const auto pixelCount64 = static_cast<std::uint64_t>(header_.width) * header_.height;
    require(pixelCount64 <= (1ull << 30u), "container pixel count exceeds traversal limit");
    require(header_.frameCount >= 1u && header_.checkpointInterval >= 1u &&
                header_.checkpointInterval <= header_.frameCount,
            "container frame/checkpoint counts are invalid");
    require(header_.firstSourcePts < header_.endSourcePtsExclusive,
            "container PTS interval is invalid");
    require(header_.timeBaseNumerator >= 1u && header_.timeBaseDenominator >= 1u,
            "container time base is invalid");
    require(std::isfinite(header_.centerX) && std::isfinite(header_.centerY) &&
                std::isfinite(header_.r0) && std::isfinite(header_.coreRadius) &&
                std::isfinite(header_.rhoMin) && std::isfinite(header_.rhoMax) &&
                header_.r0 > 0.0 && header_.coreRadius > 0.0 &&
                header_.rhoMin < header_.rhoMax,
            "container log-polar profile is invalid");
    require(header_.centerX == (static_cast<double>(header_.width) - 1.0) * 0.5 &&
                header_.centerY == (static_cast<double>(header_.height) - 1.0) * 0.5,
            "container chart is not canonical pixel-grid centered");
    require(header_.lutResolution >= 16u && header_.lutResolution <= 4096u,
            "container LUT resolution is invalid");
    require(sectionCount >= 1u && sectionCount <= 4096u, "container section count is invalid");
    require(directoryBytes64 == static_cast<std::uint64_t>(sectionCount) * DirectoryEntryBytes,
            "container directory length mismatch");
    const auto directoryOffset = checkedSize(directoryOffset64, "directory offset");
    const auto directoryBytes = checkedSize(directoryBytes64, "directory length");
    require(directoryOffset % Alignment == 0u && directoryOffset >= ContainerHeaderBytes &&
                directoryBytes <= bytes_.size() - directoryOffset &&
                directoryOffset + directoryBytes == bytes_.size(),
            "container directory range is invalid");
    require(sha256WithZeroRange(bytes_.data(), bytes_.size(),
                                ContainerContentDigestOffset, 32u) == contentDigest,
            "whole-file SHA-256 mismatch");

    sections_.clear();
    sections_.reserve(sectionCount);
    Reader directory(bytes_.data() + directoryOffset, directoryBytes);
    std::string previousKind;
    std::uint64_t previousRecordStart = 0u;
    bool havePrevious = false;
    auto previousEnd = ContainerHeaderBytes;
    auto expectedOffset = alignUp(previousEnd);
    std::map<std::string, std::size_t> kindCounts;
    const auto known = knownKinds();
    for (std::uint32_t index = 0u; index < sectionCount; ++index) {
        const auto* kindRaw = directory.raw(8u);
        std::size_t kindLength = 0u;
        while (kindLength < 8u && kindRaw[kindLength] != 0u) ++kindLength;
        require(kindLength >= 1u &&
                    allZero(kindRaw + kindLength, 8u - kindLength),
                "section kind padding is noncanonical");
        std::string kind(reinterpret_cast<const char*>(kindRaw), kindLength);
        require(std::all_of(kind.begin(), kind.end(), [](char character) {
                    return (character >= 'A' && character <= 'Z') ||
                           (character >= '0' && character <= '9');
                }), "section kind contains noncanonical characters");
        SectionView section{};
        section.kind = kind;
        section.version = directory.u32();
        section.flags = directory.u32();
        section.storedOffset = directory.u64();
        section.storedBytes = directory.u64();
        section.logicalBytes = directory.u64();
        section.recordStart = directory.u64();
        section.recordCount = directory.u64();
        const auto storedDigest = readDigest(directory);
        std::array<std::uint8_t, 16> semanticAddress{};
        std::memcpy(semanticAddress.data(), directory.raw(16u), semanticAddress.size());
        require(allZero(directory.raw(8u), 8u), "directory reserved bytes are nonzero");

        require(section.version >= 1u && section.recordCount >= 1u,
                "section version/count is invalid");
        require(section.storedBytes <= (1ull << 32u) &&
                    section.logicalBytes <= (1ull << 32u),
                "section exceeds the 4-GiB safety limit");
        require((section.flags & ~(RunTokensFlag | OptionalSectionFlag)) == 0u,
                "section flags are unsupported");
        if (known.count(kind) == 0u) {
            require((section.flags & OptionalSectionFlag) != 0u,
                    "unknown mandatory section kind: " + kind);
        }
        if (havePrevious) {
            require(kind > previousKind ||
                        (kind == previousKind && section.recordStart > previousRecordStart),
                    "directory order is noncanonical");
        }
        previousKind = kind;
        previousRecordStart = section.recordStart;
        havePrevious = true;
        const auto storedOffset = checkedSize(section.storedOffset, "section offset");
        const auto storedBytes = checkedSize(section.storedBytes, "section stored length");
        require(storedOffset == expectedOffset && storedOffset % Alignment == 0u,
                "section offset/padding is noncanonical");
        require(allZero(bytes_.data() + previousEnd, storedOffset - previousEnd),
                "section alignment padding is nonzero");
        require(storedBytes <= directoryOffset - storedOffset,
                "section range overlaps directory");
        const auto* stored = bytes_.data() + storedOffset;
        require(sha256(stored, storedBytes) == storedDigest, "section SHA-256 mismatch");
        previousEnd = storedOffset + storedBytes;
        expectedOffset = alignUp(previousEnd);
        sections_.push_back(section);
        ++kindCounts[kind];

        const auto logical = logicalSection(sections_.back());
        const auto logicalDigest = sha256(logical.data(), logical.size());
        static constexpr char domain[] = "UGTC4D-section-semantics-v1\0";
        Sha256 semanticHasher;
        semanticHasher.update(reinterpret_cast<const std::uint8_t*>(domain), sizeof(domain) - 1u);
        semanticHasher.update(kindRaw, 8u);
        std::vector<std::uint8_t> fields;
        fields.reserve(40u);
        appendU32(fields, section.version);
        appendU32(fields, section.flags & ~RunTokensFlag);
        appendU64(fields, section.recordStart);
        appendU64(fields, section.recordCount);
        appendU64(fields, section.logicalBytes);
        semanticHasher.update(fields.data(), fields.size());
        semanticHasher.update(logicalDigest.data(), logicalDigest.size());
        const auto expectedAddress = semanticHasher.finish();
        require(std::equal(semanticAddress.begin(), semanticAddress.end(), expectedAddress.begin()),
                "section semantic address mismatch");
    }
    require(directory.remaining() == 0u, "directory parser did not consume every entry");
    require(directoryOffset == expectedOffset &&
                allZero(bytes_.data() + previousEnd, directoryOffset - previousEnd),
            "directory alignment padding is noncanonical");
    for (const auto& required : requiredKinds()) {
        require(kindCounts[required] >= 1u, "missing required section: " + required);
    }
    for (const auto& pair : kindCounts) {
        if (pair.first != "FRAME" && requiredKinds().count(pair.first) != 0u) {
            require(pair.second == 1u, "duplicate singleton section: " + pair.first);
        }
    }
    require(kindCounts["METROLOG"] <= 1u, "duplicate METROLOG section");
    require(kindCounts["FRAME"] == header_.frameCount,
            "FRAME section count disagrees with container header");
    frameSections_.clear();
    for (const auto& section : sections_) {
        if (section.kind == "FRAME") frameSections_.push_back(section);
    }
    for (std::size_t index = 0u; index < frameSections_.size(); ++index) {
        require(frameSections_[index].recordStart == index &&
                    frameSections_[index].recordCount == 1u &&
                    frameSections_[index].flags == 0u,
                "FRAME directory records are not canonical sequential raw sections");
    }
}

void Ugtc4dDecoder::parseSubstrate() {
    const SectionView* lutSection = nullptr;
    const SectionView* traversalSection = nullptr;
    for (const auto& section : sections_) {
        if (section.kind == "UGLUT2") lutSection = &section;
        if (section.kind == "TRAVERS") traversalSection = &section;
    }
    require(lutSection != nullptr && traversalSection != nullptr,
            "missing UGLUT2/TRAVERS substrate dependencies");
    uglut2_ = logicalSection(*lutSection);
    traversalRecipe_ = logicalSection(*traversalSection);
    uglut2Digest_ = sha256(uglut2_.data(), uglut2_.size());
    traversalRecipeDigest_ = sha256(traversalRecipe_.data(), traversalRecipe_.size());

    require(uglut2_.size() >= 48u, "UGLUT2 header is truncated");
    Reader lut(uglut2_.data(), uglut2_.size());
    require(std::memcmp(lut.raw(6u), "UGLUT2", 6u) == 0, "UGLUT2 magic mismatch");
    const auto resolution = lut.u16();
    const auto lutR0 = lut.f64();
    const auto lutRhoMin = lut.f64();
    const auto lutRhoMax = lut.f64();
    const auto lutCore = lut.f64();
    const auto radiusScale = lut.f64();
    require(resolution == header_.lutResolution && resolution >= 16u && resolution <= 4096u &&
                (resolution & (resolution - 1u)) == 0u,
            "UGLUT2 resolution/profile is unsupported");
    require(std::isfinite(lutR0) && std::isfinite(lutRhoMin) &&
                std::isfinite(lutRhoMax) && std::isfinite(lutCore) &&
                lutR0 > 0.0 && lutRhoMin < lutRhoMax && lutCore > 0.0 &&
                radiusScale == 1.0,
            "UGLUT2 scalar profile is invalid or non-unit-scaled");
    require(lutR0 == header_.r0 && lutCore == header_.coreRadius &&
                lutRhoMin == header_.rhoMin && lutRhoMax == header_.rhoMax,
            "UGLUT2 scalar profile disagrees with container header");
    require(lut.remaining() == static_cast<std::size_t>(resolution) * 3u * 2u,
            "UGLUT2 binary16 lane count mismatch");
    std::vector<std::uint16_t> sineWords(resolution), cosineWords(resolution), radiusWords(resolution);
    for (auto& word : sineWords) word = lut.u16();
    for (auto& word : cosineWords) word = lut.u16();
    for (auto& word : radiusWords) word = lut.u16();

    require(traversalRecipe_.size() == 128u, "UGTRV1 recipe length mismatch");
    Reader recipe(traversalRecipe_.data(), traversalRecipe_.size());
    require(std::memcmp(recipe.raw(8u), "UGTRV1\0\0", 8u) == 0, "UGTRV1 magic mismatch");
    require(recipe.u16() == 1u && recipe.u16() == 0u && recipe.u32() == 128u,
            "unsupported UGTRV1 version/header");
    const auto width = recipe.u32();
    const auto height = recipe.u32();
    const auto rootSeed = recipe.u64();
    const auto recipeSeed = recipe.u64();
    const auto recipeLutDigest = readDigest(recipe);
    const auto operatorHash = recipe.u64();
    const auto traversalDigest = readDigest(recipe);
    const auto centerMode = recipe.u32();
    const auto traversalFlags = recipe.u32();
    require(allZero(recipe.raw(8u), 8u), "UGTRV1 reserved bytes are nonzero");
    require(width == header_.width && height == header_.height,
            "UGTRV1 dimensions disagree with container");
    require(recipeLutDigest == uglut2Digest_, "UGTRV1 UGLUT2 dependency SHA-256 mismatch");
    require(operatorHash == hash64(traversalMeaning()), "UGTRV1 operator meaning hash mismatch");
    require(centerMode == 1u && traversalFlags == 3u,
            "UGTRV1 center/flags are unsupported");
    require(recipeSeed == 1u, "UGTRV1 current profile requires recipe seed 1");
    Reader sourcePrefix(header_.sourceSha256.data(), 8u);
    require(rootSeed == sourcePrefix.u64(), "UGTRV1 root seed is not source-digest-derived");

    std::vector<std::int64_t> radiusQ16(resolution), sineQ30(resolution), cosineQ30(resolution);
    for (std::size_t index = 0u; index < resolution; ++index) {
        radiusQ16[index] = halfWordToFixed(radiusWords[index], 16);
        sineQ30[index] = halfWordToFixed(sineWords[index], 30);
        cosineQ30[index] = halfWordToFixed(cosineWords[index], 30);
        require(radiusQ16[index] > 0 &&
                    (index == 0u || radiusQ16[index] >= radiusQ16[index - 1u]),
                "UGLUT2 radius lane is not positive monotone Q16");
        require(sineQ30[index] != 0 || cosineQ30[index] != 0,
                "UGLUT2 direction lane contains a zero vector");
    }
    require(radiusQ16[0] == static_cast<std::int64_t>(std::nearbyint(lutCore * 65536.0)),
            "UGLUT2 first radius is not the explicit core radius");
    require(cosineQ30[0] > 0 && sineQ30[0] == 0,
            "UGLUT2 direction ray zero is not canonical +X");
    for (std::size_t index = 0u; index + 1u < resolution; ++index) {
        require(cosineQ30[index] * sineQ30[index + 1u] -
                    sineQ30[index] * cosineQ30[index + 1u] > 0,
                "UGLUT2 direction rays are not strictly counter-clockwise");
    }
    require(cosineQ30.back() * sineQ30.front() - sineQ30.back() * cosineQ30.front() > 0,
            "UGLUT2 seam rays are not strictly counter-clockwise");

    const auto sessionSeed = combineSeed(rootSeed, recipeSeed);
    const auto namespaceId = hash64("ugtoms:chrono-seeded-log-polar-traversal:v1");
    const auto schedule = combineSeed(stableId(sessionSeed, namespaceId, 0u), 0u);
    const auto originSector = static_cast<std::uint32_t>(schedule) & (resolution - 1u);
    const auto reverse = ((schedule >> 63u) & 1u) != 0u;
    std::vector<std::uint64_t> radialMidpoints;
    radialMidpoints.reserve(resolution - 1u);
    for (std::size_t index = 0u; index + 1u < resolution; ++index) {
        const auto sum = static_cast<std::uint64_t>(radiusQ16[index] + radiusQ16[index + 1u]);
        require(sum <= std::numeric_limits<std::uint32_t>::max(),
                "UGLUT2 radius midpoint exceeds exact Q32 domain");
        radialMidpoints.push_back(sum * sum);
    }
    const auto coreRadius2 = static_cast<std::uint64_t>(radiusQ16[0] * 2) *
                             static_cast<std::uint64_t>(radiusQ16[0] * 2);

    struct Key {
        std::uint8_t notCore = 0u;
        std::uint32_t rho20 = 0u;
        std::uint32_t theta18 = 0u;
        std::int64_t radius2 = 0;
        std::int64_t sectorCross = 0;
        std::uint64_t lineage = 0u;
        std::uint32_t cartesian = 0u;
    };
    const auto pixelCount = checkedSize(static_cast<std::uint64_t>(width) * height, "pixel count");
    std::vector<Key> keys;
    keys.reserve(pixelCount);
    for (std::size_t address = 0u; address < pixelCount; ++address) {
        const auto x = static_cast<std::int64_t>(address % width);
        const auto y = static_cast<std::int64_t>(address / width);
        const auto dx2 = x * 2 - (static_cast<std::int64_t>(width) - 1);
        const auto dy2 = (static_cast<std::int64_t>(height) - 1) - y * 2;
        const auto targetRadius2 = dx2 * dx2 + dy2 * dy2;
        require(static_cast<std::uint64_t>(targetRadius2) <=
                    (static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max()) >> 32u),
                "pixel radius exceeds exact Q32 safety domain");
        const auto targetQ32 = static_cast<std::uint64_t>(targetRadius2) << 32u;
        auto ring = static_cast<std::uint32_t>(
            std::lower_bound(radialMidpoints.begin(), radialMidpoints.end(), targetQ32) -
            radialMidpoints.begin());
        const auto vectorHalf = dy2 < 0 || (dy2 == 0 && dx2 < 0);
        std::size_t low = 0u;
        std::size_t high = resolution;
        while (low < high) {
            const auto middle = (low + high) / 2u;
            const auto probe = std::min<std::size_t>(middle, resolution - 1u);
            const auto rayHalf = sineQ30[probe] < 0 ||
                                 (sineQ30[probe] == 0 && cosineQ30[probe] < 0);
            const auto cross = cosineQ30[probe] * dy2 - sineQ30[probe] * dx2;
            const auto lessOrEqual = (!rayHalf && vectorHalf) ||
                                     (rayHalf == vectorHalf && cross >= 0);
            if (lessOrEqual) low = middle + 1u;
            else high = middle;
        }
        auto sector = static_cast<std::uint32_t>((low - 1u) & (resolution - 1u));
        const auto core = targetQ32 < coreRadius2;
        if (core) {
            ring = 0u;
            sector = 0u;
        }
        const auto rho20 = static_cast<std::uint32_t>(
            (static_cast<std::uint64_t>(ring) * ((1u << 20u) - 1u) +
             (resolution - 1u) / 2u) / (resolution - 1u));
        const auto seededSector = reverse
            ? (originSector - sector) & (resolution - 1u)
            : (sector - originSector) & (resolution - 1u);
        auto theta18 = static_cast<std::uint32_t>(
            (static_cast<std::uint64_t>(seededSector) << 18u) / resolution);
        if (core) theta18 = 0u;
        keys.push_back(Key{
            static_cast<std::uint8_t>(!core), rho20, theta18, targetRadius2,
            cosineQ30[sector] * dy2 - sineQ30[sector] * dx2,
            stableId(sessionSeed, namespaceId, address),
            static_cast<std::uint32_t>(address),
        });
    }
    std::sort(keys.begin(), keys.end(), [](const Key& left, const Key& right) {
        return std::tie(left.notCore, left.rho20, left.theta18, left.radius2,
                        left.sectorCross, left.lineage, left.cartesian) <
               std::tie(right.notCore, right.rho20, right.theta18, right.radius2,
                        right.sectorCross, right.lineage, right.cartesian);
    });
    traversal_.resize(pixelCount);
    std::vector<std::uint8_t> traversalBytes;
    traversalBytes.reserve(pixelCount * 4u);
    for (std::size_t ordinal = 0u; ordinal < pixelCount; ++ordinal) {
        traversal_[ordinal] = keys[ordinal].cartesian;
        appendU32(traversalBytes, traversal_[ordinal]);
    }
    require(sha256(traversalBytes.data(), traversalBytes.size()) == traversalDigest,
            "seed/UGLUT2-regenerated traversal SHA-256 mismatch");
}

void Ugtc4dDecoder::buildPredictionPlan() {
    const auto count = traversal_.size();
    std::vector<std::int32_t> inverse(count, -1);
    for (std::size_t ordinal = 0u; ordinal < count; ++ordinal) {
        const auto address = traversal_[ordinal];
        require(address < count && inverse[address] < 0, "traversal is not bijective");
        inverse[address] = static_cast<std::int32_t>(ordinal);
    }
    predictionPlan_.parent.resize(count);
    predictionPlan_.a.resize(count);
    predictionPlan_.b.resize(count);
    predictionPlan_.c.resize(count);
    predictionPlan_.useMedian.resize(count);
    static constexpr std::array<std::pair<int, int>, 8> offsets{{
        {-1,0},{1,0},{0,-1},{0,1},{-1,-1},{1,-1},{-1,1},{1,1},
    }};
    static constexpr std::array<std::array<int, 3>, 4> tripleIndexes{{
        {{0,2,4}}, {{1,2,5}}, {{0,3,6}}, {{1,3,7}},
    }};
    for (std::size_t ordinal = 0u; ordinal < count; ++ordinal) {
        const auto address = static_cast<std::size_t>(traversal_[ordinal]);
        const auto x = static_cast<int>(address % header_.width);
        const auto y = static_cast<int>(address / header_.width);
        std::array<std::int32_t, 8> predecessors{};
        predecessors.fill(-1);
        for (std::size_t index = 0u; index < offsets.size(); ++index) {
            const auto nx = x + offsets[index].first;
            const auto ny = y + offsets[index].second;
            if (nx >= 0 && ny >= 0 && nx < static_cast<int>(header_.width) &&
                ny < static_cast<int>(header_.height)) {
                const auto neighbor = static_cast<std::size_t>(ny) * header_.width +
                                      static_cast<std::size_t>(nx);
                if (inverse[neighbor] < static_cast<std::int32_t>(ordinal)) {
                    predecessors[index] = inverse[neighbor];
                }
            }
        }
        predictionPlan_.parent[ordinal] =
            *std::max_element(predecessors.begin(), predecessors.end());
        std::array<std::int32_t, 4> scores{};
        scores.fill(-1);
        for (std::size_t choice = 0u; choice < tripleIndexes.size(); ++choice) {
            const auto& triple = tripleIndexes[choice];
            if (predecessors[triple[0]] >= 0 && predecessors[triple[1]] >= 0 &&
                predecessors[triple[2]] >= 0) {
                scores[choice] = std::min({predecessors[triple[0]],
                                           predecessors[triple[1]],
                                           predecessors[triple[2]]});
            }
        }
        const auto choice = static_cast<std::size_t>(
            std::max_element(scores.begin(), scores.end()) - scores.begin());
        predictionPlan_.useMedian[ordinal] = scores[choice] >= 0 ? 1u : 0u;
        predictionPlan_.a[ordinal] = predecessors[tripleIndexes[choice][0]];
        predictionPlan_.b[ordinal] = predecessors[tripleIndexes[choice][1]];
        predictionPlan_.c[ordinal] = predecessors[tripleIndexes[choice][2]];
    }
}

std::uint32_t Ugtc4dDecoder::framePredictor(std::size_t frameIndex) const {
    require(frameIndex < frameSections_.size(), "frame index is out of range");
    const auto& section = frameSections_[frameIndex];
    require((section.flags & RunTokensFlag) == 0u && section.storedBytes >= 28u,
            "FRAME section cannot expose a predictor field");
    const auto offset = checkedSize(section.storedOffset, "FRAME section offset");
    Reader reader(bytes_.data() + offset + 24u, 4u);
    return reader.u32();
}

DecodedFrame Ugtc4dDecoder::decodeFrame(
    std::size_t frameIndex,
    const DecodedFrame* previous
) const {
    require(frameIndex < frameSections_.size(), "frame index is out of range");
    const auto raw = logicalSection(frameSections_[frameIndex]);
    require(raw.size() >= FrameHeaderBytes, "UGFRM2 header is truncated");
    Reader frame(raw.data(), raw.size());
    require(std::memcmp(frame.raw(8u), "UGFRM2\0\0", 8u) == 0, "UGFRM2 magic mismatch");
    require(frame.u16() == 2u && frame.u16() == 0u, "unsupported UGFRM2 version");
    require(frame.u32() == FrameHeaderBytes, "UGFRM2 header size mismatch");
    DecodedFrame result{};
    result.ordinal = frame.u32();
    const auto flags = frame.u32();
    result.predictor = frame.u32();
    result.sourcePts = frame.i64();
    result.sourceEndPtsExclusive = frame.i64();
    const auto logicalBytes64 = frame.u64();
    const auto payloadBytes64 = frame.u64();
    result.previousOrdinal = frame.u32();
    require(frame.u32() == 0u, "UGFRM2 reserved field is nonzero");
    const auto lutDigest = readDigest(frame);
    const auto recipeDigest = readDigest(frame);
    const auto cartesianDigest = readDigest(frame);
    const auto polarDigest = readDigest(frame);
    const auto residualDigest = readDigest(frame);
    const auto payloadDigest = readDigest(frame);
    const auto contentDigest = readDigest(frame);
    require(allZero(frame.raw(28u), 28u), "UGFRM2 reserved tail is nonzero");
    const auto logicalBytes = checkedSize(logicalBytes64, "UGFRM2 logical length");
    const auto payloadBytes = checkedSize(payloadBytes64, "UGFRM2 payload length");
    require(result.ordinal == frameIndex && result.ordinal == frameSections_[frameIndex].recordStart,
            "UGFRM2 ordinal disagrees with directory");
    require(result.sourcePts < result.sourceEndPtsExclusive,
            "UGFRM2 source interval is invalid");
    require(flags <= FrameCheckpointFlag, "UGFRM2 flags are unsupported");
    require(logicalBytes == traversal_.size() * 3u,
            "UGFRM2 logical RGB length disagrees with raster");
    require(raw.size() == FrameHeaderBytes + payloadBytes, "UGFRM2 payload length mismatch");
    require(lutDigest == uglut2Digest_ && recipeDigest == traversalRecipeDigest_,
            "UGFRM2 substrate dependency digest mismatch");
    require(sha256WithZeroRange(raw.data(), raw.size(), FrameContentDigestOffset, 32u) == contentDigest,
            "UGFRM2 content SHA-256 mismatch");
    const auto* payload = raw.data() + FrameHeaderBytes;
    require(sha256(payload, payloadBytes) == payloadDigest, "UGFRM2 payload SHA-256 mismatch");
    const auto residual = decodeRiceStream(payload, payloadBytes);
    require(residual.size() == logicalBytes &&
                sha256(residual.data(), residual.size()) == residualDigest,
            "UGFRM2 residual length/SHA-256 mismatch");

    const auto count = traversal_.size();
    std::vector<std::uint8_t> residualOrdinal(count * 3u);
    for (std::size_t ordinal = 0u; ordinal < count; ++ordinal) {
        for (std::size_t channel = 0u; channel < 3u; ++channel) {
            residualOrdinal[ordinal * 3u + channel] = residual[channel * count + ordinal];
        }
    }

    // Predictor dispatch is deliberately isolated: q709 and later exact
    // substrate transforms add a case without changing container, entropy, or
    // seed-regenerated traversal code.
    if (result.predictor == PredictorCartesianMedianGreenLumaLift ||
        result.predictor == PredictorCartesianMedianQ709Codeword) {
        require(flags == FrameCheckpointFlag && result.previousOrdinal == NoPreviousOrdinal &&
                    previous == nullptr,
                "Cartesian predictor must be an independent checkpoint");
        std::vector<std::uint8_t> cartesianResidual(count * 3u);
        for (std::size_t ordinal = 0u; ordinal < count; ++ordinal) {
            const auto address = static_cast<std::size_t>(traversal_[ordinal]);
            std::copy_n(residualOrdinal.data() + ordinal * 3u, 3u,
                        cartesianResidual.data() + address * 3u);
        }
        std::vector<std::uint8_t> transformed(count * 3u);
        for (std::size_t y = 0u; y < header_.height; ++y) {
            for (std::size_t x = 0u; x < header_.width; ++x) {
                const auto address = y * header_.width + x;
                for (std::size_t channel = 0u; channel < 3u; ++channel) {
                    std::int64_t prediction = 0;
                    if (y == 0u && x > 0u) {
                        prediction = transformed[(address - 1u) * 3u + channel];
                    } else if (x == 0u && y > 0u) {
                        prediction = transformed[(address - header_.width) * 3u + channel];
                    } else if (x > 0u && y > 0u) {
                        const auto a = transformed[(address - 1u) * 3u + channel];
                        const auto b = transformed[(address - header_.width) * 3u + channel];
                        const auto c = transformed[(address - header_.width - 1u) * 3u + channel];
                        prediction = medianEdge(a, b, c);
                    }
                    transformed[address * 3u + channel] = moduloByte(
                        static_cast<std::int64_t>(cartesianResidual[address * 3u + channel]) +
                        prediction);
                }
            }
        }
        result.cartesianRgb.resize(count * 3u);
        for (std::size_t address = 0u; address < count; ++address) {
            const auto yLane = transformed[address * 3u];
            std::int16_t cr = 0;
            std::int16_t cb = 0;
            int adjustment = 0;
            if (result.predictor == PredictorCartesianMedianQ709Codeword) {
                // Predictor 14 stores the exact q709 codeword as [Y,Cb,Cr].
                // q709 is the codec ABI name, not a BT.709 matrix claim.
                cb = signedByte(transformed[address * 3u + 1u]);
                cr = signedByte(transformed[address * 3u + 2u]);
                adjustment = floorDivide(5 * static_cast<int>(cr) +
                                         2 * static_cast<int>(cb), 16);
            } else {
                // Predictor 13 stores the older exact lift as [Y,Cr,Cb].
                cr = signedByte(transformed[address * 3u + 1u]);
                cb = signedByte(transformed[address * 3u + 2u]);
                adjustment = floorDivide(static_cast<int>(cr) + static_cast<int>(cb), 4);
            }
            const auto green = moduloByte(static_cast<int>(yLane) - adjustment);
            result.cartesianRgb[address * 3u] = moduloByte(static_cast<int>(green) + cr);
            result.cartesianRgb[address * 3u + 1u] = green;
            result.cartesianRgb[address * 3u + 2u] = moduloByte(static_cast<int>(green) + cb);
        }
        result.polarRgb.resize(count * 3u);
        for (std::size_t ordinal = 0u; ordinal < count; ++ordinal) {
            const auto address = static_cast<std::size_t>(traversal_[ordinal]);
            std::copy_n(result.cartesianRgb.data() + address * 3u, 3u,
                        result.polarRgb.data() + ordinal * 3u);
        }
    } else if (result.predictor == PredictorTemporalSubstrateMedianGreen) {
        require(flags == 0u && previous != nullptr &&
                    result.previousOrdinal == previous->ordinal &&
                    result.previousOrdinal < result.ordinal &&
                    previous->polarRgb.size() == count * 3u,
                "predictor 11 previous-frame dependency mismatch");
        std::vector<std::uint8_t> values(count * 3u);
        for (std::size_t ordinal = 0u; ordinal < count; ++ordinal) {
            for (std::size_t channel = 0u; channel < 3u; ++channel) {
                std::int64_t prediction = 0;
                if (predictionPlan_.useMedian[ordinal] != 0u) {
                    prediction = medianEdge(
                        values[static_cast<std::size_t>(predictionPlan_.a[ordinal]) * 3u + channel],
                        values[static_cast<std::size_t>(predictionPlan_.b[ordinal]) * 3u + channel],
                        values[static_cast<std::size_t>(predictionPlan_.c[ordinal]) * 3u + channel]);
                } else if (predictionPlan_.parent[ordinal] >= 0) {
                    prediction = values[
                        static_cast<std::size_t>(predictionPlan_.parent[ordinal]) * 3u + channel];
                }
                values[ordinal * 3u + channel] = moduloByte(
                    static_cast<std::int64_t>(residualOrdinal[ordinal * 3u + channel]) +
                    prediction);
            }
        }
        result.polarRgb.resize(count * 3u);
        for (std::size_t ordinal = 0u; ordinal < count; ++ordinal) {
            const auto* previousRgb = previous->polarRgb.data() + ordinal * 3u;
            const auto previousG = previousRgb[1];
            const std::array<std::uint8_t, 3> previousGreenDelta{{
                previousG,
                moduloByte(static_cast<int>(previousRgb[0]) - previousG),
                moduloByte(static_cast<int>(previousRgb[2]) - previousG),
            }};
            const auto g = moduloByte(static_cast<int>(values[ordinal * 3u]) +
                                      previousGreenDelta[0]);
            const auto rg = moduloByte(static_cast<int>(values[ordinal * 3u + 1u]) +
                                       previousGreenDelta[1]);
            const auto bg = moduloByte(static_cast<int>(values[ordinal * 3u + 2u]) +
                                       previousGreenDelta[2]);
            result.polarRgb[ordinal * 3u] = moduloByte(static_cast<int>(rg) + g);
            result.polarRgb[ordinal * 3u + 1u] = g;
            result.polarRgb[ordinal * 3u + 2u] = moduloByte(static_cast<int>(bg) + g);
        }
        result.cartesianRgb.resize(count * 3u);
        for (std::size_t ordinal = 0u; ordinal < count; ++ordinal) {
            const auto address = static_cast<std::size_t>(traversal_[ordinal]);
            std::copy_n(result.polarRgb.data() + ordinal * 3u, 3u,
                        result.cartesianRgb.data() + address * 3u);
        }
    } else {
        fail("unsupported predictor mode " + std::to_string(result.predictor));
    }

    require(sha256(result.polarRgb.data(), result.polarRgb.size()) == polarDigest,
            "UGFRM2 polar RGB SHA-256 mismatch");
    require(sha256(result.cartesianRgb.data(), result.cartesianRgb.size()) == cartesianDigest,
            "UGFRM2 Cartesian RGB SHA-256 mismatch");
    return result;
}

FullVerification Ugtc4dDecoder::verifyAllFrames() const {
    require(!frameSections_.empty(), "decoded stream contains no frames");
    static constexpr char domain[] = "UGTC4D-decoded-cartesian-rgb8-stream-v2\0";
    Sha256 streamHasher;
    streamHasher.update(reinterpret_cast<const std::uint8_t*>(domain), sizeof(domain) - 1u);
    std::vector<std::uint8_t> profile;
    profile.reserve(24u);
    appendU32(profile, header_.width);
    appendU32(profile, header_.height);
    appendU64(profile, header_.timeBaseNumerator);
    appendU64(profile, header_.timeBaseDenominator);
    streamHasher.update(profile.data(), profile.size());

    FullVerification verification{};
    DecodedFrame previous;
    bool havePrevious = false;
    std::int64_t previousEnd = 0;
    for (std::size_t index = 0u; index < frameSections_.size(); ++index) {
        const auto predictor = framePredictor(index);
        const auto* dependency = predictor == PredictorTemporalSubstrateMedianGreen
            ? (havePrevious ? &previous : nullptr)
            : nullptr;
        auto current = decodeFrame(index, dependency);
        require((index == 0u && current.sourcePts == header_.firstSourcePts) ||
                    (index > 0u && current.sourcePts == previousEnd),
                "decoded frame intervals are not contiguous with the container");
        if (index + 1u == frameSections_.size()) {
            require(current.sourceEndPtsExclusive == header_.endSourcePtsExclusive,
                    "final decoded interval disagrees with container");
        }
        std::vector<std::uint8_t> framePrefix;
        framePrefix.reserve(28u);
        appendU32(framePrefix, current.ordinal);
        appendU64(framePrefix, static_cast<std::uint64_t>(current.sourcePts));
        appendU64(framePrefix, static_cast<std::uint64_t>(current.sourceEndPtsExclusive));
        appendU64(framePrefix, static_cast<std::uint64_t>(current.cartesianRgb.size()));
        streamHasher.update(framePrefix.data(), framePrefix.size());
        streamHasher.update(current.cartesianRgb.data(), current.cartesianRgb.size());
        ++verification.frames;
        verification.decodedRgbBytes += current.cartesianRgb.size();
        if (predictor == PredictorCartesianMedianGreenLumaLift) {
            ++verification.predictor13Frames;
        } else if (predictor == PredictorCartesianMedianQ709Codeword) {
            ++verification.predictor14Frames;
        } else if (predictor == PredictorTemporalSubstrateMedianGreen) {
            ++verification.predictor11Frames;
        }
        previousEnd = current.sourceEndPtsExclusive;
        previous = std::move(current);
        havePrevious = true;
    }
    require(streamHasher.finish() == header_.decodedStreamSha256,
            "decoded Cartesian RGB/PTS stream SHA-256 mismatch");
    return verification;
}

} // namespace ugts::chrono
