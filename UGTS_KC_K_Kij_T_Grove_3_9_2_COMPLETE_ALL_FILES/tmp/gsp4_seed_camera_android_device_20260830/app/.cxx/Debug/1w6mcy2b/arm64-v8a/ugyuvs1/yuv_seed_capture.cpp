#include "yuv_seed_capture.hpp"

#include <algorithm>
#include <array>
#include <cerrno>
#include <condition_variable>
#include <cstdio>
#include <cstring>
#include <deque>
#include <exception>
#include <fstream>
#include <functional>
#include <limits>
#include <mutex>
#include <stdexcept>
#include <thread>
#include <utility>

#ifdef _WIN32
#include <io.h>
#include <share.h>
#else
#include <unistd.h>
#endif

namespace ugts::chrono {
namespace {

constexpr std::size_t FileHeaderBytes = 512u;
constexpr std::size_t StaticHeaderBytes = 256u;
constexpr std::size_t CommitSlotBytes = 128u;
constexpr std::size_t CommitSlot0Offset = 256u;
constexpr std::size_t CommitSlot1Offset = 384u;
constexpr std::size_t StaticDigestOffset = 208u;
constexpr std::size_t CommitDigestOffset = 80u;
constexpr std::size_t FrameHeaderBytes = 384u;
constexpr std::size_t FrameContentDigestOffset = 304u;
constexpr std::size_t FramePreSubstrateDigestOffset = 336u;
constexpr std::size_t FrameNoveltyEventCountOffset = 368u;
constexpr std::size_t BlockHeaderBytes = 192u;
constexpr std::size_t BlockContentDigestOffset = 104u;
constexpr std::size_t BlockPredictorOffset = 136u;
constexpr std::size_t BlockNoveltyMethodOffset = 140u;
constexpr std::size_t BlockLineageDigestOffset = 144u;
constexpr std::size_t TerminalHeaderBytes = 192u;
constexpr std::size_t TerminalContentDigestOffset = 144u;
constexpr std::size_t Alignment = 64u;
constexpr std::uint32_t FileFlags = 1u; // zero novelty bytes are omitted
constexpr std::uint32_t CommitFinal = 1u;
constexpr std::uint32_t FrameCheckpoint = 1u;
constexpr std::uint32_t NoveltyZero = 0u;
constexpr std::uint32_t NoveltyDense = 1u;
constexpr std::uint32_t NoveltySparseBitmask = 2u;
constexpr std::uint32_t NoveltySparseGaps = 3u;
constexpr std::uint32_t NoPreviousOrdinal = 0xffffffffu;
constexpr std::uint32_t MaxNoveltyWorkerCount = 64u;
constexpr std::uint32_t MaxNoveltyInFlightBlocks = 256u;

[[noreturn]] void fail(const std::string& message) {
    throw std::runtime_error("UGYUVS1 capture: " + message);
}

void require(bool condition, const std::string& message) {
    if (!condition) fail(message);
}

std::size_t alignUp(std::size_t value) {
    require(value <= std::numeric_limits<std::size_t>::max() - (Alignment - 1u),
            "alignment overflow");
    return ((value + Alignment - 1u) / Alignment) * Alignment;
}

void setU16(std::vector<std::uint8_t>& bytes, std::size_t offset, std::uint16_t value) {
    require(offset + 2u <= bytes.size(), "u16 write escaped record");
    bytes[offset] = static_cast<std::uint8_t>(value);
    bytes[offset + 1u] = static_cast<std::uint8_t>(value >> 8u);
}

void setU32(std::vector<std::uint8_t>& bytes, std::size_t offset, std::uint32_t value) {
    require(offset + 4u <= bytes.size(), "u32 write escaped record");
    for (unsigned index = 0u; index < 4u; ++index) {
        bytes[offset + index] = static_cast<std::uint8_t>(value >> (index * 8u));
    }
}

void setU64(std::vector<std::uint8_t>& bytes, std::size_t offset, std::uint64_t value) {
    require(offset + 8u <= bytes.size(), "u64 write escaped record");
    for (unsigned index = 0u; index < 8u; ++index) {
        bytes[offset + index] = static_cast<std::uint8_t>(value >> (index * 8u));
    }
}

void setI64(std::vector<std::uint8_t>& bytes, std::size_t offset, std::int64_t value) {
    setU64(bytes, offset, static_cast<std::uint64_t>(value));
}

std::uint16_t getU16(const std::uint8_t* bytes, std::size_t size, std::size_t offset) {
    require(offset + 2u <= size, "u16 read escaped record");
    return static_cast<std::uint16_t>(bytes[offset]) |
           static_cast<std::uint16_t>(static_cast<std::uint16_t>(bytes[offset + 1u]) << 8u);
}

std::uint32_t getU32(const std::uint8_t* bytes, std::size_t size, std::size_t offset) {
    require(offset + 4u <= size, "u32 read escaped record");
    std::uint32_t result = 0u;
    for (unsigned index = 0u; index < 4u; ++index) {
        result |= static_cast<std::uint32_t>(bytes[offset + index]) << (index * 8u);
    }
    return result;
}

std::uint64_t getU64(const std::uint8_t* bytes, std::size_t size, std::size_t offset) {
    require(offset + 8u <= size, "u64 read escaped record");
    std::uint64_t result = 0u;
    for (unsigned index = 0u; index < 8u; ++index) {
        result |= static_cast<std::uint64_t>(bytes[offset + index]) << (index * 8u);
    }
    return result;
}

std::int64_t getI64(const std::uint8_t* bytes, std::size_t size, std::size_t offset) {
    return static_cast<std::int64_t>(getU64(bytes, size, offset));
}

void setDigest(
    std::vector<std::uint8_t>& bytes,
    std::size_t offset,
    const Sha256Digest& digest
) {
    require(offset + digest.size() <= bytes.size(), "digest write escaped record");
    std::copy(digest.begin(), digest.end(), bytes.begin() + static_cast<std::ptrdiff_t>(offset));
}

Sha256Digest getDigest(const std::uint8_t* bytes, std::size_t size, std::size_t offset) {
    require(offset + 32u <= size, "digest read escaped record");
    Sha256Digest result{};
    std::copy_n(bytes + offset, result.size(), result.begin());
    return result;
}

bool allZero(const std::uint8_t* bytes, std::size_t size) {
    return std::all_of(bytes, bytes + size, [](std::uint8_t value) { return value == 0u; });
}

Sha256Digest hashWithZeroRange(
    const std::vector<std::uint8_t>& bytes,
    std::size_t offset,
    std::size_t count
) {
    require(offset <= bytes.size() && count <= bytes.size() - offset,
            "hash zero range escaped record");
    auto copy = bytes;
    std::fill(copy.begin() + static_cast<std::ptrdiff_t>(offset),
              copy.begin() + static_cast<std::ptrdiff_t>(offset + count),
              std::uint8_t{0});
    return sha256(copy.data(), copy.size());
}

Sha256Digest hashHeaderPayloadWithZeroRange(
    const std::vector<std::uint8_t>& header,
    std::size_t offset,
    std::size_t count,
    const std::vector<std::uint8_t>& payload
) {
    require(offset <= header.size() && count <= header.size() - offset,
            "hash zero range escaped header");
    auto joined = header;
    std::fill(joined.begin() + static_cast<std::ptrdiff_t>(offset),
              joined.begin() + static_cast<std::ptrdiff_t>(offset + count),
              std::uint8_t{0});
    joined.insert(joined.end(), payload.begin(), payload.end());
    return sha256(joined.data(), joined.size());
}

std::vector<std::uint8_t> digestPreimage(const char* domain) {
    const auto length = std::strlen(domain) + 1u;
    return {reinterpret_cast<const std::uint8_t*>(domain),
            reinterpret_cast<const std::uint8_t*>(domain) + length};
}

void appendU32(std::vector<std::uint8_t>& bytes, std::uint32_t value) {
    const auto offset = bytes.size();
    bytes.resize(offset + 4u);
    setU32(bytes, offset, value);
}

void appendU64(std::vector<std::uint8_t>& bytes, std::uint64_t value) {
    const auto offset = bytes.size();
    bytes.resize(offset + 8u);
    setU64(bytes, offset, value);
}

void appendDigest(std::vector<std::uint8_t>& bytes, const Sha256Digest& digest) {
    bytes.insert(bytes.end(), digest.begin(), digest.end());
}

std::uint64_t splitmix64(std::uint64_t value) noexcept {
    value += 0x9e3779b97f4a7c15ull;
    value = (value ^ (value >> 30u)) * 0xbf58476d1ce4e5b9ull;
    value = (value ^ (value >> 27u)) * 0x94d049bb133111ebull;
    return value ^ (value >> 31u);
}

std::uint64_t combineSeed(std::uint64_t seed, std::uint64_t value) noexcept {
    const auto mixed = splitmix64(value) + 0x9e3779b97f4a7c15ull +
                       (seed << 6u) + (seed >> 2u);
    return splitmix64(seed ^ mixed);
}

std::uint64_t stableId(
    std::uint64_t sessionSeed,
    std::uint64_t namespaceId,
    std::uint64_t address
) noexcept {
    return combineSeed(combineSeed(sessionSeed, namespaceId), address);
}

Sha256Digest blockLineageDigest(
    std::uint32_t frameOrdinal,
    const std::vector<std::uint32_t>& lineageSeeds,
    std::size_t first,
    std::size_t count
) {
    auto preimage = digestPreimage("UGYUVS1-GSP4-codeword-lineage-v1");
    appendU32(preimage, frameOrdinal);
    appendU32(preimage, static_cast<std::uint32_t>(first));
    appendU32(preimage, static_cast<std::uint32_t>(count));
    for (std::size_t local = 0u; local < count; ++local) {
        const auto lineageSeed = lineageSeeds[first + local];
        appendU32(preimage, lineageSeed);
        appendU32(preimage, gsp4Mix32(lineageSeed ^ frameOrdinal));
    }
    return sha256(preimage.data(), preimage.size());
}

std::vector<std::uint32_t> cameraLineageSeeds(
    std::uint64_t rootSeed,
    std::uint64_t recipeSeed,
    const std::vector<std::uint32_t>& traversal
) {
    std::vector<std::uint32_t> result;
    result.reserve(traversal.size());
    for (const auto address : traversal) {
        result.push_back(gsp4CodewordLineage(
            rootSeed, recipeSeed, address, 0u).lineageSeed);
    }
    return result;
}

Sha256Digest recipeDigest(
    const YuvSeedCaptureProfile& profile,
    const SeededUglut2Traversal& traversal
) {
    auto preimage = digestPreimage("UGYUVS1-UGCODE24-420-seed-recipe-v1");
    appendU32(preimage, profile.width);
    appendU32(preimage, profile.height);
    appendU32(preimage, Ugcode24_420Profile);
    appendU64(preimage, profile.rootSeed);
    appendU64(preimage, profile.traversalRecipeSeed);
    appendDigest(preimage, traversal.uglut2Sha256);
    appendDigest(preimage, traversal.traversalSha256);
    return sha256(preimage.data(), preimage.size());
}

Sha256Digest operatorDigest() {
    auto preimage = digestPreimage(
        "UGCODE24-420-v1:luma-address-codeword=[Y(x,y),U(floor(x/2),floor(y/2)),"
        "V(floor(x/2),floor(y/2))];storage=UGTRV1-luma-order;"
        "chroma-owner=even-x-even-y-once;novelty=mod256-mask-nonzero-values"
    );
    return sha256(preimage.data(), preimage.size());
}

void durableFlush(std::FILE* file) {
    require(file != nullptr, "durable flush received null file");
    require(std::fflush(file) == 0, "fflush failed");
#ifdef _WIN32
    require(_commit(_fileno(file)) == 0, "_commit failed");
#else
    require(::fsync(::fileno(file)) == 0, "fsync failed");
#endif
}

std::FILE* openFile(const std::string& path, const char* mode) {
#ifdef _WIN32
    // Capture and committed-prefix validation intentionally coexist. The
    // default secure CRT sharing mode denies this reader on Windows.
    return ::_fsopen(path.c_str(), mode, _SH_DENYNO);
#else
    return std::fopen(path.c_str(), mode);
#endif
}

void writeExact(std::FILE* file, const std::uint8_t* data, std::size_t size) {
    if (size == 0u) return;
    require(std::fwrite(data, 1u, size, file) == size, "file write failed");
}

void seekFile(std::FILE* file, std::uint64_t offset) {
#ifdef _WIN32
    require(_fseeki64(file, static_cast<__int64>(offset), SEEK_SET) == 0, "file seek failed");
#else
    require(::fseeko(file, static_cast<off_t>(offset), SEEK_SET) == 0, "file seek failed");
#endif
}

std::uint64_t fileSize(const std::string& path) {
    std::ifstream stream(path, std::ios::binary | std::ios::ate);
    require(stream.good(), "cannot open file: " + path);
    const auto end = stream.tellg();
    require(end >= 0, "cannot determine file length");
    return static_cast<std::uint64_t>(end);
}

bool hasSuffix(const std::string& value, const char* suffix) {
    const auto length = std::strlen(suffix);
    return value.size() >= length &&
           value.compare(value.size() - length, length, suffix) == 0;
}

std::vector<std::uint8_t> readExact(
    std::ifstream& stream,
    std::size_t size,
    const char* label
) {
    std::vector<std::uint8_t> result(size);
    if (size > 0u) {
        stream.read(reinterpret_cast<char*>(result.data()), static_cast<std::streamsize>(size));
        require(static_cast<std::size_t>(stream.gcount()) == size,
                std::string(label) + " is truncated");
    }
    return result;
}

std::vector<std::uint8_t> densePlane(
    const Plane8View& source,
    std::uint32_t width,
    std::uint32_t height,
    const char* label
) {
    require(source.data != nullptr, std::string(label) + " data pointer is null");
    require(source.rowStride >= width && source.pixelStride >= 1u,
            std::string(label) + " strides are invalid");
    const auto last = static_cast<std::uint64_t>(height - 1u) * source.rowStride +
                      static_cast<std::uint64_t>(width - 1u) * source.pixelStride;
    require(last < source.size, std::string(label) + " view exceeds its backing bytes");
    std::vector<std::uint8_t> result(static_cast<std::size_t>(width) * height);
    for (std::uint32_t y = 0u; y < height; ++y) {
        for (std::uint32_t x = 0u; x < width; ++x) {
            result[static_cast<std::size_t>(y) * width + x] =
                source.data[static_cast<std::size_t>(y) * source.rowStride +
                            static_cast<std::size_t>(x) * source.pixelStride];
        }
    }
    return result;
}

std::vector<std::uint8_t> metadataBytes(const ByteView& view) {
    require(view.data != nullptr || view.size == 0u, "metadata pointer is null");
    return view.size == 0u
        ? std::vector<std::uint8_t>{}
        : std::vector<std::uint8_t>(view.data, view.data + view.size);
}

std::vector<std::uint8_t> buildCommitSlot(
    std::uint64_t generation,
    bool finalized,
    std::uint64_t frameCount,
    std::uint64_t committedEnd,
    std::int64_t lastPts,
    const Sha256Digest& terminal
) {
    std::vector<std::uint8_t> slot(CommitSlotBytes, 0u);
    std::memcpy(slot.data(), "UGCMIT1\0", 8u);
    setU64(slot, 8u, generation);
    setU32(slot, 16u, finalized ? CommitFinal : 0u);
    setU64(slot, 24u, frameCount);
    setU64(slot, 32u, committedEnd);
    setI64(slot, 40u, lastPts);
    setDigest(slot, 48u, terminal);
    setDigest(slot, CommitDigestOffset,
              hashWithZeroRange(slot, CommitDigestOffset, 32u));
    return slot;
}

struct ParsedCommit {
    bool valid = false;
    std::uint64_t generation = 0u;
    bool finalized = false;
    std::uint64_t frameCount = 0u;
    std::uint64_t committedEnd = 0u;
    std::int64_t lastPts = std::numeric_limits<std::int64_t>::min();
    Sha256Digest terminal{};
};

ParsedCommit parseCommit(
    const std::uint8_t* slot,
    std::uint64_t recordOffset,
    std::uint64_t actualBytes
) {
    ParsedCommit result{};
    if (std::memcmp(slot, "UGCMIT1\0", 8u) != 0) return result;
    std::vector<std::uint8_t> bytes(slot, slot + CommitSlotBytes);
    if (getDigest(slot, CommitSlotBytes, CommitDigestOffset) !=
        hashWithZeroRange(bytes, CommitDigestOffset, 32u)) return result;
    result.generation = getU64(slot, CommitSlotBytes, 8u);
    const auto flags = getU32(slot, CommitSlotBytes, 16u);
    if (result.generation == 0u || (flags & ~CommitFinal) != 0u ||
        getU32(slot, CommitSlotBytes, 20u) != 0u ||
        !allZero(slot + 112u, 16u)) return ParsedCommit{};
    result.finalized = (flags & CommitFinal) != 0u;
    result.frameCount = getU64(slot, CommitSlotBytes, 24u);
    result.committedEnd = getU64(slot, CommitSlotBytes, 32u);
    result.lastPts = getI64(slot, CommitSlotBytes, 40u);
    result.terminal = getDigest(slot, CommitSlotBytes, 48u);
    const auto emptyEnd = result.finalized
        ? recordOffset + TerminalHeaderBytes
        : recordOffset;
    if (result.committedEnd < recordOffset || result.committedEnd > actualBytes ||
        (result.frameCount == 0u &&
         (result.committedEnd != emptyEnd ||
          result.lastPts != std::numeric_limits<std::int64_t>::min() ||
          (result.finalized
               ? allZero(result.terminal.data(), result.terminal.size())
               : !allZero(result.terminal.data(), result.terminal.size()))))) {
        return ParsedCommit{};
    }
    result.valid = true;
    return result;
}

std::vector<std::uint8_t> buildTerminalRecord(
    std::uint64_t frameCount,
    std::uint64_t committedPrefixBytes,
    std::int64_t lastPts,
    const Sha256Digest& lastFrameSha,
    const Sha256Digest& staticSha,
    const Sha256Digest& recipeSha
) {
    std::vector<std::uint8_t> record(TerminalHeaderBytes, 0u);
    std::memcpy(record.data(), "UGYEND1\0", 8u);
    setU16(record, 8u, 1u);
    setU16(record, 10u, 0u);
    setU32(record, 12u, static_cast<std::uint32_t>(TerminalHeaderBytes));
    setU64(record, 24u, frameCount);
    setU64(record, 32u, committedPrefixBytes);
    setI64(record, 40u, lastPts);
    setDigest(record, 48u, lastFrameSha);
    setDigest(record, 80u, staticSha);
    setDigest(record, 112u, recipeSha);
    setDigest(record, TerminalContentDigestOffset,
              hashWithZeroRange(record, TerminalContentDigestOffset, 32u));
    return record;
}

void appendUleb128(std::vector<std::uint8_t>& bytes, std::size_t value);

std::vector<std::uint8_t> buildNoveltyBlock(
    std::uint32_t blockOrdinal,
    std::uint32_t firstLumaOrdinal,
    std::uint32_t lumaCount,
    YuvPredictorProgram predictor,
    const Sha256Digest& lineageDigest,
    std::uint32_t& selectedRepresentation,
    const std::vector<std::uint8_t>& logical
) {
    const auto maskBytes = (logical.size() + 7u) / 8u;
    std::vector<std::uint8_t> mask(maskBytes, 0u);
    std::vector<std::uint8_t> values;
    std::vector<std::uint8_t> gaps;
    values.reserve(logical.size());
    auto nextOrdinal = std::size_t{0u};
    for (std::size_t index = 0u; index < logical.size(); ++index) {
        if (logical[index] != 0u) {
            mask[index >> 3u] |= static_cast<std::uint8_t>(1u << (index & 7u));
            appendUleb128(gaps, index - nextOrdinal);
            values.push_back(logical[index]);
            nextOrdinal = index + 1u;
        }
    }
    std::uint32_t representation = NoveltyZero;
    const std::vector<std::uint8_t>* auxiliary = nullptr;
    const std::vector<std::uint8_t>* storedValues = nullptr;
    const std::vector<std::uint8_t> empty;
    if (!values.empty()) {
        representation = NoveltyDense;
        auxiliary = &empty;
        storedValues = &logical;
        auto bestBytes = logical.size();
        const auto bitmaskBytes = mask.size() + values.size();
        if (bitmaskBytes < bestBytes) {
            representation = NoveltySparseBitmask;
            auxiliary = &mask;
            storedValues = &values;
            bestBytes = bitmaskBytes;
        }
        const auto gapBytes = gaps.size() + values.size();
        if (gapBytes < bestBytes) {
            representation = NoveltySparseGaps;
            auxiliary = &gaps;
            storedValues = &values;
        }
    } else {
        auxiliary = &empty;
        storedValues = &empty;
    }
    selectedRepresentation = representation;
    std::vector<std::uint8_t> header(BlockHeaderBytes, 0u);
    std::memcpy(header.data(), "UGNBLK1\0", 8u);
    setU16(header, 8u, 1u);
    setU16(header, 10u, 0u);
    setU32(header, 12u, static_cast<std::uint32_t>(BlockHeaderBytes));
    setU32(header, 16u, blockOrdinal);
    setU32(header, 20u, firstLumaOrdinal);
    setU32(header, 24u, lumaCount);
    setU32(header, 28u, static_cast<std::uint32_t>(logical.size()));
    setU32(header, 32u, static_cast<std::uint32_t>(auxiliary->size()));
    setU32(header, 36u, static_cast<std::uint32_t>(storedValues->size()));
    setDigest(header, 40u, sha256(logical.data(), logical.size()));
    setDigest(header, 72u, sha256(storedValues->data(), storedValues->size()));
    setU32(header, BlockPredictorOffset, static_cast<std::uint32_t>(predictor));
    setU32(header, BlockNoveltyMethodOffset, representation);
    setDigest(header, BlockLineageDigestOffset, lineageDigest);
    std::vector<std::uint8_t> payload;
    payload.reserve(auxiliary->size() + storedValues->size());
    payload.insert(payload.end(), auxiliary->begin(), auxiliary->end());
    payload.insert(payload.end(), storedValues->begin(), storedValues->end());
    setDigest(header, BlockContentDigestOffset,
              hashHeaderPayloadWithZeroRange(
                  header, BlockContentDigestOffset, 32u, payload));
    header.insert(header.end(), payload.begin(), payload.end());
    return header;
}

struct NoveltyBlockBuild {
    std::vector<std::uint8_t> logicalResidual;
    std::vector<std::uint8_t> serialized;
    std::uint64_t noveltyEventCount = 0u;
    std::size_t chromaOwnerCount = 0u;
    std::uint32_t representation = NoveltyZero;
};

// Persistent fixed-size workers plus a fixed-size submission queue. Results
// are retained for at most one bounded batch and consumed in block-ordinal
// order, so scheduling can never affect the canonical file byte order.
class BoundedNoveltyBlockPool final {
public:
    using Builder = std::function<NoveltyBlockBuild(std::size_t)>;
    using Consumer = std::function<void(NoveltyBlockBuild&&)>;

    BoundedNoveltyBlockPool(
        std::uint32_t workerCount,
        std::uint32_t maxInFlightBlocks
    ) : maxInFlightBlocks_(maxInFlightBlocks) {
        try {
            workers_.reserve(workerCount);
            for (std::uint32_t index = 0u; index < workerCount; ++index) {
                workers_.emplace_back([this] { workerLoop(); });
            }
        } catch (...) {
            {
                std::lock_guard<std::mutex> lock(queueMutex_);
                stopping_ = true;
            }
            queueReady_.notify_all();
            for (auto& worker : workers_) {
                if (worker.joinable()) worker.join();
            }
            throw;
        }
    }

    ~BoundedNoveltyBlockPool() {
        {
            std::lock_guard<std::mutex> lock(queueMutex_);
            stopping_ = true;
        }
        queueReady_.notify_all();
        queueSpace_.notify_all();
        for (auto& worker : workers_) {
            if (worker.joinable()) worker.join();
        }
    }

    BoundedNoveltyBlockPool(const BoundedNoveltyBlockPool&) = delete;
    BoundedNoveltyBlockPool& operator=(const BoundedNoveltyBlockPool&) = delete;

    void buildOrdered(
        std::size_t blockCount,
        const Builder& build,
        const Consumer& consume
    ) {
        for (std::size_t batchFirst = 0u; batchFirst < blockCount;
             batchFirst += maxInFlightBlocks_) {
            const auto batchCount = std::min<std::size_t>(
                maxInFlightBlocks_, blockCount - batchFirst);
            struct BatchState {
                explicit BatchState(std::size_t count)
                    : results(count), remaining(count) {}
                std::vector<NoveltyBlockBuild> results;
                std::mutex mutex;
                std::condition_variable finished;
                std::size_t remaining;
                std::exception_ptr failure;
            };
            auto state = std::make_shared<BatchState>(batchCount);
            std::size_t submitted = 0u;
            std::exception_ptr submissionFailure;
            try {
                for (; submitted < batchCount; ++submitted) {
                    const auto local = submitted;
                    const auto global = batchFirst + local;
                    enqueue([state, &build, local, global] {
                        std::exception_ptr failure;
                        try {
                            state->results[local] = build(global);
                        } catch (...) {
                            failure = std::current_exception();
                        }
                        std::lock_guard<std::mutex> lock(state->mutex);
                        if (failure != nullptr && state->failure == nullptr) {
                            state->failure = failure;
                        }
                        --state->remaining;
                        if (state->remaining == 0u) state->finished.notify_one();
                    });
                }
            } catch (...) {
                submissionFailure = std::current_exception();
                std::lock_guard<std::mutex> lock(state->mutex);
                state->remaining -= batchCount - submitted;
                if (state->remaining == 0u) state->finished.notify_one();
            }
            {
                std::unique_lock<std::mutex> lock(state->mutex);
                state->finished.wait(lock, [&state] {
                    return state->remaining == 0u;
                });
            }
            if (submissionFailure != nullptr) std::rethrow_exception(submissionFailure);
            if (state->failure != nullptr) std::rethrow_exception(state->failure);
            for (auto& result : state->results) consume(std::move(result));
        }
    }

private:
    using Task = std::function<void()>;

    void enqueue(Task task) {
        {
            std::unique_lock<std::mutex> lock(queueMutex_);
            queueSpace_.wait(lock, [this] {
                return stopping_ || tasks_.size() < maxInFlightBlocks_;
            });
            require(!stopping_, "novelty worker pool is stopping");
            tasks_.push_back(std::move(task));
        }
        queueReady_.notify_one();
    }

    void workerLoop() {
        while (true) {
            Task task;
            {
                std::unique_lock<std::mutex> lock(queueMutex_);
                queueReady_.wait(lock, [this] {
                    return stopping_ || !tasks_.empty();
                });
                if (stopping_ && tasks_.empty()) return;
                task = std::move(tasks_.front());
                tasks_.pop_front();
            }
            queueSpace_.notify_one();
            task();
        }
    }

    std::size_t maxInFlightBlocks_;
    std::vector<std::thread> workers_;
    std::deque<Task> tasks_;
    std::mutex queueMutex_;
    std::condition_variable queueReady_;
    std::condition_variable queueSpace_;
    bool stopping_ = false;
};

std::uint8_t residualByte(std::uint8_t current, std::uint8_t previous) {
    return static_cast<std::uint8_t>(static_cast<unsigned>(current) - previous);
}

void appendUleb128(std::vector<std::uint8_t>& bytes, std::size_t value) {
    do {
        auto lane = static_cast<std::uint8_t>(value & 0x7fu);
        value >>= 7u;
        if (value != 0u) lane |= 0x80u;
        bytes.push_back(lane);
    } while (value != 0u);
}

std::size_t readCanonicalUleb128(
    const std::uint8_t* bytes,
    std::size_t size,
    std::size_t& position
) {
    const auto start = position;
    std::size_t result = 0u;
    unsigned shift = 0u;
    while (true) {
        require(position < size, "sparse-gap ULEB128 is truncated");
        const auto lane = bytes[position++];
        require(shift < std::numeric_limits<std::size_t>::digits,
                "sparse-gap ULEB128 overflows size_t");
        const auto payload = static_cast<std::size_t>(lane & 0x7fu);
        require(payload <= (std::numeric_limits<std::size_t>::max() >> shift),
                "sparse-gap ULEB128 payload overflows size_t");
        result |= payload << shift;
        if ((lane & 0x80u) == 0u) {
            require(position == start + 1u || lane != 0u,
                    "sparse-gap ULEB128 is not minimally encoded");
            return result;
        }
        shift += 7u;
    }
}

} // namespace

struct YuvSeedCaptureWriter::Impl {
    std::FILE* file = nullptr;
    std::string partialPath;
    YuvSeedCaptureProfile profile;
    SeededUglut2Traversal traversal;
    std::vector<std::uint32_t> lineageSeeds;
    Sha256Digest recipeSha{};
    Sha256Digest staticSha{};
    std::uint64_t recordOffset = 0u;
    std::uint64_t committedEnd = 0u;
    std::uint64_t generation = 1u;
    std::uint64_t frames = 0u;
    std::int64_t lastPts = std::numeric_limits<std::int64_t>::min();
    Sha256Digest terminal{};
    DenseYuv420p8Frame previous;
    Sha256Digest previousYSha{};
    Sha256Digest previousUSha{};
    Sha256Digest previousVSha{};
    bool closed = false;

    ~Impl() {
        if (file != nullptr) std::fclose(file);
    }

    void commit(bool finalized) {
        ++generation;
        const auto slot = buildCommitSlot(
            generation, finalized, frames, committedEnd, lastPts, terminal);
        const auto offset = (generation & 1u) != 0u ? CommitSlot0Offset : CommitSlot1Offset;
        seekFile(file, offset);
        writeExact(file, slot.data(), slot.size());
        durableFlush(file);
    }
};

YuvSeedCaptureWriter::YuvSeedCaptureWriter(std::unique_ptr<Impl> impl)
    : impl_(std::move(impl)) {}

YuvSeedCaptureWriter::~YuvSeedCaptureWriter() = default;

std::unique_ptr<YuvSeedCaptureWriter> YuvSeedCaptureWriter::createPartial(
    const std::string& partialPath,
    const YuvSeedCaptureProfile& profile
) {
    require(!partialPath.empty(), "partial path is empty");
    require(profile.width >= 2u && profile.height >= 2u &&
                profile.width <= 65534u && profile.height <= 65534u &&
                (profile.width & 1u) == 0u && (profile.height & 1u) == 0u,
            "UGCODE24-420 dimensions are outside the even uint16 profile");
    require(profile.checkpointInterval >= 1u,
            "checkpoint interval must be at least one");
    require(profile.noveltyBlockLumaAddresses >= 1u &&
                profile.noveltyBlockLumaAddresses <= 65536u,
            "novelty block luma-address count is invalid");
    require(!profile.literalUglut2.empty(), "literal UGLUT2 bytes are required");
    if (auto* existing = openFile(partialPath, "rb")) {
        std::fclose(existing);
        fail("partial path already exists; refusing to overwrite it");
    }
    auto impl = std::make_unique<Impl>();
    impl->partialPath = partialPath;
    impl->profile = profile;
    impl->traversal = regenerateSeededUglut2Traversal(
        profile.width,
        profile.height,
        profile.rootSeed,
        profile.traversalRecipeSeed,
        profile.literalUglut2);
    impl->lineageSeeds = cameraLineageSeeds(
        profile.rootSeed,
        profile.traversalRecipeSeed,
        impl->traversal.polarOrdinalToCartesian);
    impl->recipeSha = recipeDigest(profile, impl->traversal);
    impl->recordOffset = alignUp(FileHeaderBytes + profile.literalUglut2.size());
    impl->committedEnd = impl->recordOffset;
    std::vector<std::uint8_t> header(FileHeaderBytes, 0u);
    std::memcpy(header.data(), "UGYUVS1\0", 8u);
    setU16(header, 8u, 1u);
    setU16(header, 10u, 0u);
    setU32(header, 12u, static_cast<std::uint32_t>(FileHeaderBytes));
    setU32(header, 16u, FileFlags);
    setU32(header, 20u, profile.width);
    setU32(header, 24u, profile.height);
    setU32(header, 28u, profile.width / 2u);
    setU32(header, 32u, profile.height / 2u);
    setU32(header, 36u, Ugcode24_420Profile);
    setU32(header, 40u, 8u);
    setU32(header, 44u, profile.checkpointInterval);
    setU32(header, 48u, profile.noveltyBlockLumaAddresses);
    require(profile.literalUglut2.size() <= std::numeric_limits<std::uint32_t>::max(),
            "UGLUT2 dependency is too large");
    setU32(header, 52u, static_cast<std::uint32_t>(profile.literalUglut2.size()));
    setU64(header, 56u, profile.rootSeed);
    setU64(header, 64u, profile.traversalRecipeSeed);
    setU64(header, 72u, impl->recordOffset);
    setDigest(header, 80u, impl->traversal.uglut2Sha256);
    setDigest(header, 112u, impl->traversal.traversalSha256);
    setDigest(header, 144u, impl->recipeSha);
    setDigest(header, 176u, operatorDigest());
    impl->staticSha = hashWithZeroRange(
        std::vector<std::uint8_t>(header.begin(), header.begin() + StaticHeaderBytes),
        StaticDigestOffset,
        32u);
    setDigest(header, StaticDigestOffset, impl->staticSha);
    const auto initial = buildCommitSlot(
        impl->generation,
        false,
        0u,
        impl->recordOffset,
        impl->lastPts,
        impl->terminal);
    std::copy(initial.begin(), initial.end(),
              header.begin() + static_cast<std::ptrdiff_t>(CommitSlot0Offset));
    impl->file = openFile(partialPath, "w+b");
    require(impl->file != nullptr, "cannot create partial file");
    writeExact(impl->file, header.data(), header.size());
    writeExact(impl->file, profile.literalUglut2.data(), profile.literalUglut2.size());
    const auto padding = impl->recordOffset - FileHeaderBytes - profile.literalUglut2.size();
    std::vector<std::uint8_t> zeros(static_cast<std::size_t>(padding), 0u);
    writeExact(impl->file, zeros.data(), zeros.size());
    durableFlush(impl->file);
    return std::unique_ptr<YuvSeedCaptureWriter>(
        new YuvSeedCaptureWriter(std::move(impl)));
}

YuvSeedCaptureAppendStats YuvSeedCaptureWriter::append(
    const Yuv420p8FrameView& view
) {
    require(impl_ != nullptr && !impl_->closed, "writer is closed");
    require(view.sensorTimestampNs >= 0 && view.sensorTimestampNs > impl_->lastPts,
            "sensor timestamps must be strictly increasing");
    const auto width = impl_->profile.width;
    const auto height = impl_->profile.height;
    const auto chromaWidth = width / 2u;
    const auto chromaHeight = height / 2u;
    DenseYuv420p8Frame current{};
    current.width = width;
    current.height = height;
    current.sensorTimestampNs = view.sensorTimestampNs;
    current.frameNumber = view.frameNumber;
    current.y = densePlane(view.y, width, height, "Y plane");
    current.u = densePlane(view.u, chromaWidth, chromaHeight, "U plane");
    current.v = densePlane(view.v, chromaWidth, chromaHeight, "V plane");
    current.canonicalMetadata = metadataBytes(view.canonicalMetadata);
    const auto ySha = sha256(current.y.data(), current.y.size());
    const auto uSha = sha256(current.u.data(), current.u.size());
    const auto vSha = sha256(current.v.data(), current.v.size());
    const auto preSubstrateSha = preSubstrateFrameSha256(current);
    const auto checkpoint = (impl_->frames % impl_->profile.checkpointInterval) == 0u;
    require(impl_->frames <= std::numeric_limits<std::uint32_t>::max(),
            "frame ordinal exceeds uint32");
    const auto ordinal = static_cast<std::uint32_t>(impl_->frames);
    const auto previousOrdinal = checkpoint ? NoPreviousOrdinal : ordinal - 1u;
    auto zeroY = std::vector<std::uint8_t>{};
    auto zeroU = std::vector<std::uint8_t>{};
    auto zeroV = std::vector<std::uint8_t>{};
    if (checkpoint) {
        zeroY.assign(current.y.size(), 0u);
        zeroU.assign(current.u.size(), 0u);
        zeroV.assign(current.v.size(), 0u);
    }
    const auto& previousY = checkpoint ? zeroY : impl_->previous.y;
    const auto& previousU = checkpoint ? zeroU : impl_->previous.u;
    const auto& previousV = checkpoint ? zeroV : impl_->previous.v;
    require(previousY.size() == current.y.size() && previousU.size() == current.u.size() &&
                previousV.size() == current.v.size(),
            "previous executable state has the wrong plane sizes");

    std::vector<std::uint8_t> fullResidual;
    fullResidual.reserve(current.y.size() + current.u.size() + current.v.size());
    std::vector<std::uint8_t> noveltyPayload;
    std::uint64_t noveltyEventCount = 0u;
    std::array<std::uint32_t, 4u> representationCounts{};
    std::uint32_t blockOrdinal = 0u;
    std::size_t ownerCount = 0u;
    for (std::size_t first = 0u; first < impl_->traversal.polarOrdinalToCartesian.size();
         first += impl_->profile.noveltyBlockLumaAddresses) {
        const auto count = std::min<std::size_t>(
            impl_->profile.noveltyBlockLumaAddresses,
            impl_->traversal.polarOrdinalToCartesian.size() - first);
        std::vector<std::uint8_t> blockResidual;
        blockResidual.reserve(count * 2u);
        for (std::size_t local = 0u; local < count; ++local) {
            const auto address = impl_->traversal.polarOrdinalToCartesian[first + local];
            const auto x = address % width;
            const auto y = address / width;
            blockResidual.push_back(residualByte(current.y[address], previousY[address]));
            if ((x & 1u) == 0u && (y & 1u) == 0u) {
                const auto chroma = static_cast<std::size_t>(y / 2u) * chromaWidth + x / 2u;
                blockResidual.push_back(residualByte(current.u[chroma], previousU[chroma]));
                blockResidual.push_back(residualByte(current.v[chroma], previousV[chroma]));
                ++ownerCount;
            }
        }
        noveltyEventCount += static_cast<std::uint64_t>(std::count_if(
            blockResidual.begin(), blockResidual.end(),
            [](std::uint8_t value) { return value != 0u; }));
        fullResidual.insert(fullResidual.end(), blockResidual.begin(), blockResidual.end());
        const auto predictor = checkpoint
            ? YuvPredictorProgram::RawExactLane
            : YuvPredictorProgram::PreviousSameAddress;
        std::uint32_t selectedRepresentation = NoveltyZero;
        const auto block = buildNoveltyBlock(
            blockOrdinal++,
            static_cast<std::uint32_t>(first),
            static_cast<std::uint32_t>(count),
            predictor,
            blockLineageDigest(
                ordinal,
                impl_->lineageSeeds,
                first,
                count),
            selectedRepresentation,
            blockResidual);
        require(selectedRepresentation < representationCounts.size(),
                "novelty representation dispatch escaped count table");
        ++representationCounts[selectedRepresentation];
        noveltyPayload.insert(noveltyPayload.end(), block.begin(), block.end());
    }
    require(ownerCount == current.u.size(), "canonical 2x2 chroma owner count mismatch");
    require(fullResidual.size() == current.y.size() + current.u.size() + current.v.size(),
            "UGCODE24-420 logical residual length mismatch");

    auto statePreimage = digestPreimage("UGYUVS1-executable-seed-state-v1");
    appendDigest(statePreimage, impl_->staticSha);
    appendDigest(statePreimage, impl_->recipeSha);
    appendU32(statePreimage, ordinal);
    appendU32(statePreimage, previousOrdinal);
    appendU64(statePreimage, static_cast<std::uint64_t>(view.sensorTimestampNs));
    appendU64(statePreimage, static_cast<std::uint64_t>(view.frameNumber));
    appendDigest(statePreimage, checkpoint ? sha256(zeroY.data(), zeroY.size()) : impl_->previousYSha);
    appendDigest(statePreimage, checkpoint ? sha256(zeroU.data(), zeroU.size()) : impl_->previousUSha);
    appendDigest(statePreimage, checkpoint ? sha256(zeroV.data(), zeroV.size()) : impl_->previousVSha);
    const auto stateSha = sha256(statePreimage.data(), statePreimage.size());

    std::vector<std::uint8_t> framePayload = noveltyPayload;
    framePayload.insert(framePayload.end(), current.canonicalMetadata.begin(),
                        current.canonicalMetadata.end());
    std::vector<std::uint8_t> header(FrameHeaderBytes, 0u);
    std::memcpy(header.data(), "UGYFRM1\0", 8u);
    setU16(header, 8u, 1u);
    setU16(header, 10u, 0u);
    setU32(header, 12u, static_cast<std::uint32_t>(FrameHeaderBytes));
    setU32(header, 16u, checkpoint ? FrameCheckpoint : 0u);
    setU32(header, 20u, ordinal);
    setU32(header, 24u, previousOrdinal);
    setU32(header, 28u, blockOrdinal);
    setI64(header, 32u, view.sensorTimestampNs);
    setI64(header, 40u, view.frameNumber);
    setU64(header, 48u, framePayload.size());
    setU64(header, 56u, noveltyPayload.size());
    setU64(header, 64u, current.canonicalMetadata.size());
    setU64(header, 72u, fullResidual.size());
    setDigest(header, 80u, ySha);
    setDigest(header, 112u, uSha);
    setDigest(header, 144u, vSha);
    setDigest(header, 176u, sha256(fullResidual.data(), fullResidual.size()));
    setDigest(header, 208u,
              sha256(current.canonicalMetadata.data(), current.canonicalMetadata.size()));
    setDigest(header, 240u, impl_->terminal);
    setDigest(header, 272u, stateSha);
    setDigest(header, FramePreSubstrateDigestOffset, preSubstrateSha);
    setU64(header, FrameNoveltyEventCountOffset, noveltyEventCount);
    setDigest(header, FrameContentDigestOffset,
              hashHeaderPayloadWithZeroRange(
                  header, FrameContentDigestOffset, 32u, framePayload));
    const auto contentSha = getDigest(header.data(), header.size(), FrameContentDigestOffset);

    seekFile(impl_->file, impl_->committedEnd);
    writeExact(impl_->file, header.data(), header.size());
    writeExact(impl_->file, framePayload.data(), framePayload.size());
    durableFlush(impl_->file);
    impl_->committedEnd += header.size() + framePayload.size();
    ++impl_->frames;
    impl_->lastPts = view.sensorTimestampNs;
    impl_->terminal = contentSha;
    impl_->previous = std::move(current);
    impl_->previousYSha = ySha;
    impl_->previousUSha = uSha;
    impl_->previousVSha = vSha;
    impl_->commit(false);
    YuvSeedCaptureAppendStats stats{};
    stats.ordinal = ordinal;
    stats.logicalLaneCount = fullResidual.size();
    stats.noveltyEventCount = noveltyEventCount;
    stats.noveltyPayloadBytes = noveltyPayload.size();
    stats.frameRecordBytes = header.size() + framePayload.size();
    stats.zeroBlockCount = representationCounts[NoveltyZero];
    stats.denseBlockCount = representationCounts[NoveltyDense];
    stats.sparseBitmaskBlockCount = representationCounts[NoveltySparseBitmask];
    stats.sparseGapBlockCount = representationCounts[NoveltySparseGaps];
    stats.preSubstrateSha256 = preSubstrateSha;
    return stats;
}

std::uint64_t YuvSeedCaptureWriter::frameCount() const noexcept {
    return impl_ == nullptr ? 0u : impl_->frames;
}

void YuvSeedCaptureWriter::finalize(const std::string& finalPath) {
    require(impl_ != nullptr && !impl_->closed, "writer is already closed");
    require(!finalPath.empty() && finalPath != impl_->partialPath,
            "final path must differ from the partial path");
    if (auto* existing = openFile(finalPath, "rb")) {
        std::fclose(existing);
        fail("final path already exists; refusing to overwrite it");
    }
    const auto terminalRecord = buildTerminalRecord(
        impl_->frames,
        impl_->committedEnd,
        impl_->lastPts,
        impl_->terminal,
        impl_->staticSha,
        impl_->recipeSha);
    seekFile(impl_->file, impl_->committedEnd);
    writeExact(impl_->file, terminalRecord.data(), terminalRecord.size());
    durableFlush(impl_->file);
    impl_->committedEnd += terminalRecord.size();
    impl_->terminal = getDigest(
        terminalRecord.data(), terminalRecord.size(), TerminalContentDigestOffset);
    impl_->commit(true);
    require(std::fclose(impl_->file) == 0, "closing finalized file failed");
    impl_->file = nullptr;
    require(std::rename(impl_->partialPath.c_str(), finalPath.c_str()) == 0,
            "atomic final rename failed; durable partial remains at source path");
    impl_->closed = true;
}

struct YuvSeedCaptureReader::Impl {
    std::string path;
    YuvSeedCaptureProfile profile;
    SeededUglut2Traversal traversal;
    std::vector<std::uint32_t> lineageSeeds;
    Sha256Digest recipeSha{};
    Sha256Digest staticSha{};
    ParsedCommit commit;
    std::uint64_t recordOffset = 0u;
};

YuvSeedCaptureReader::YuvSeedCaptureReader(const std::string& path)
    : impl_(std::make_shared<Impl>()) {
    impl_->path = path;
    const auto actualBytes = fileSize(path);
    require(actualBytes >= FileHeaderBytes, "file header is truncated");
    std::ifstream stream(path, std::ios::binary);
    require(stream.good(), "cannot open capture file");
    const auto header = readExact(stream, FileHeaderBytes, "file header");
    require(std::memcmp(header.data(), "UGYUVS1\0", 8u) == 0,
            "file magic mismatch");
    require(getU16(header.data(), header.size(), 8u) == 1u &&
                getU16(header.data(), header.size(), 10u) == 0u &&
                getU32(header.data(), header.size(), 12u) == FileHeaderBytes,
            "unsupported file version/header");
    require(getU32(header.data(), header.size(), 16u) == FileFlags,
            "file flags do not require zero-novelty omission");
    impl_->profile.width = getU32(header.data(), header.size(), 20u);
    impl_->profile.height = getU32(header.data(), header.size(), 24u);
    require(impl_->profile.width >= 2u && impl_->profile.height >= 2u &&
                impl_->profile.width <= 65534u && impl_->profile.height <= 65534u &&
                (impl_->profile.width & 1u) == 0u &&
                (impl_->profile.height & 1u) == 0u,
            "capture dimensions are not valid YUV420");
    require(getU32(header.data(), header.size(), 28u) == impl_->profile.width / 2u &&
                getU32(header.data(), header.size(), 32u) == impl_->profile.height / 2u &&
                getU32(header.data(), header.size(), 36u) == Ugcode24_420Profile &&
                getU32(header.data(), header.size(), 40u) == 8u,
            "logical UGCODE24-420 profile mismatch");
    impl_->profile.checkpointInterval = getU32(header.data(), header.size(), 44u);
    impl_->profile.noveltyBlockLumaAddresses = getU32(header.data(), header.size(), 48u);
    const auto lutBytes = getU32(header.data(), header.size(), 52u);
    impl_->profile.rootSeed = getU64(header.data(), header.size(), 56u);
    impl_->profile.traversalRecipeSeed = getU64(header.data(), header.size(), 64u);
    impl_->recordOffset = getU64(header.data(), header.size(), 72u);
    require(impl_->profile.checkpointInterval >= 1u &&
                impl_->profile.noveltyBlockLumaAddresses >= 1u &&
                impl_->profile.noveltyBlockLumaAddresses <= 65536u,
            "capture checkpoint/block profile is invalid");
    require(impl_->recordOffset == alignUp(FileHeaderBytes + lutBytes) &&
                impl_->recordOffset <= actualBytes,
            "record data offset is noncanonical");
    require(allZero(header.data() + 240u, 16u), "static reserved bytes are nonzero");
    auto staticBytes = std::vector<std::uint8_t>(
        header.begin(), header.begin() + StaticHeaderBytes);
    impl_->staticSha = getDigest(header.data(), header.size(), StaticDigestOffset);
    require(impl_->staticSha == hashWithZeroRange(staticBytes, StaticDigestOffset, 32u),
            "static header SHA-256 mismatch");
    stream.seekg(FileHeaderBytes, std::ios::beg);
    impl_->profile.literalUglut2 = readExact(stream, lutBytes, "UGLUT2 dependency");
    const auto padding = static_cast<std::size_t>(
        impl_->recordOffset - FileHeaderBytes - lutBytes);
    const auto paddingBytes = readExact(stream, padding, "UGLUT2 alignment padding");
    require(allZero(paddingBytes.data(), paddingBytes.size()),
            "UGLUT2 alignment padding is nonzero");
    impl_->traversal = regenerateSeededUglut2Traversal(
        impl_->profile.width,
        impl_->profile.height,
        impl_->profile.rootSeed,
        impl_->profile.traversalRecipeSeed,
        impl_->profile.literalUglut2);
    impl_->lineageSeeds = cameraLineageSeeds(
        impl_->profile.rootSeed,
        impl_->profile.traversalRecipeSeed,
        impl_->traversal.polarOrdinalToCartesian);
    require(impl_->traversal.uglut2Sha256 == getDigest(header.data(), header.size(), 80u) &&
                impl_->traversal.traversalSha256 == getDigest(header.data(), header.size(), 112u),
            "literal UGLUT2/traversal SHA-256 mismatch");
    impl_->recipeSha = recipeDigest(impl_->profile, impl_->traversal);
    require(impl_->recipeSha == getDigest(header.data(), header.size(), 144u) &&
                operatorDigest() == getDigest(header.data(), header.size(), 176u),
            "seed recipe/operator digest mismatch");
    const auto first = parseCommit(
        header.data() + CommitSlot0Offset, impl_->recordOffset, actualBytes);
    const auto second = parseCommit(
        header.data() + CommitSlot1Offset, impl_->recordOffset, actualBytes);
    require(first.valid || second.valid, "neither crash-safe commit slot is valid");
    impl_->commit = !second.valid || (first.valid && first.generation > second.generation)
        ? first : second;
    require(!hasSuffix(path, ".ugsp4c") || impl_->commit.finalized,
            "completed .ugsp4c lacks a valid FINAL commit");
    require(!impl_->commit.finalized || impl_->commit.committedEnd == actualBytes,
            "FINAL commit does not cover the complete file");
    inspection_.profile = Ugcode24_420Profile;
    inspection_.width = impl_->profile.width;
    inspection_.height = impl_->profile.height;
    inspection_.committedFrames = impl_->commit.frameCount;
    inspection_.committedBytes = impl_->commit.committedEnd;
    inspection_.generation = impl_->commit.generation;
    inspection_.finalized = impl_->commit.finalized;
    inspection_.recoveredIncomplete = !impl_->commit.finalized;
    inspection_.uncommittedTailBytes = actualBytes - impl_->commit.committedEnd;
    inspection_.uglut2Sha256 = impl_->traversal.uglut2Sha256;
    inspection_.traversalSha256 = impl_->traversal.traversalSha256;
    inspection_.terminalRecordSha256 = impl_->commit.terminal;
}

void YuvSeedCaptureReader::replay(
    const std::function<void(const DenseYuv420p8Frame&)>& consume
) const {
    require(static_cast<bool>(consume), "replay consumer is empty");
    std::ifstream stream(impl_->path, std::ios::binary);
    require(stream.good(), "cannot reopen capture file for replay");
    stream.seekg(static_cast<std::streamoff>(impl_->recordOffset), std::ios::beg);
    const auto width = impl_->profile.width;
    const auto height = impl_->profile.height;
    const auto chromaWidth = width / 2u;
    const auto chromaHeight = height / 2u;
    const auto yBytes = static_cast<std::size_t>(width) * height;
    const auto cBytes = static_cast<std::size_t>(chromaWidth) * chromaHeight;
    DenseYuv420p8Frame previous{};
    previous.width = width;
    previous.height = height;
    previous.y.assign(yBytes, 0u);
    previous.u.assign(cBytes, 0u);
    previous.v.assign(cBytes, 0u);
    const auto zeroY = previous.y;
    const auto zeroU = previous.u;
    const auto zeroV = previous.v;
    const auto zeroYSha = sha256(zeroY.data(), zeroY.size());
    const auto zeroUSha = sha256(zeroU.data(), zeroU.size());
    const auto zeroVSha = sha256(zeroV.data(), zeroV.size());
    auto previousYSha = zeroYSha;
    auto previousUSha = zeroUSha;
    auto previousVSha = zeroVSha;
    Sha256Digest terminal{};
    std::int64_t previousPts = std::numeric_limits<std::int64_t>::min();
    std::uint64_t consumedBytes = impl_->recordOffset;
    for (std::uint64_t frameIndex = 0u; frameIndex < impl_->commit.frameCount; ++frameIndex) {
        const auto header = readExact(stream, FrameHeaderBytes, "frame header");
        consumedBytes += header.size();
        require(std::memcmp(header.data(), "UGYFRM1\0", 8u) == 0 &&
                    getU16(header.data(), header.size(), 8u) == 1u &&
                    getU16(header.data(), header.size(), 10u) == 0u &&
                    getU32(header.data(), header.size(), 12u) == FrameHeaderBytes,
                "unsupported frame header");
        const auto flags = getU32(header.data(), header.size(), 16u);
        const auto ordinal = getU32(header.data(), header.size(), 20u);
        const auto previousOrdinal = getU32(header.data(), header.size(), 24u);
        const auto blockCount = getU32(header.data(), header.size(), 28u);
        const auto sensorPts = getI64(header.data(), header.size(), 32u);
        const auto frameNumber = getI64(header.data(), header.size(), 40u);
        const auto payloadBytes = getU64(header.data(), header.size(), 48u);
        const auto noveltyBytes = getU64(header.data(), header.size(), 56u);
        const auto metadataCount = getU64(header.data(), header.size(), 64u);
        const auto logicalSymbols = getU64(header.data(), header.size(), 72u);
        require(flags <= FrameCheckpoint && ordinal == frameIndex &&
                    sensorPts >= 0 && sensorPts > previousPts &&
                    payloadBytes == noveltyBytes + metadataCount &&
                    logicalSymbols == yBytes + cBytes * 2u &&
                    payloadBytes <= (yBytes + cBytes * 2u) * 2u +
                        static_cast<std::uint64_t>(blockCount) * BlockHeaderBytes + metadataCount,
                "frame scalar fields are invalid");
        const auto checkpoint = (flags & FrameCheckpoint) != 0u;
        require(checkpoint == (ordinal % impl_->profile.checkpointInterval == 0u) &&
                    (checkpoint ? previousOrdinal == NoPreviousOrdinal
                                : previousOrdinal == ordinal - 1u),
                "frame checkpoint/dependency schedule mismatch");
        require(getDigest(header.data(), header.size(), 240u) == terminal &&
                    allZero(header.data() + 376u, 8u),
                "frame chain/reserved bytes mismatch");
        require(payloadBytes <= static_cast<std::uint64_t>(std::numeric_limits<std::size_t>::max()),
                "frame payload exceeds host address space");
        const auto payload = readExact(
            stream, static_cast<std::size_t>(payloadBytes), "frame payload");
        consumedBytes += payload.size();
        require(getDigest(header.data(), header.size(), FrameContentDigestOffset) ==
                    hashHeaderPayloadWithZeroRange(
                        header, FrameContentDigestOffset, 32u, payload),
                "frame content SHA-256 mismatch");

        const auto& baseY = checkpoint ? zeroY : previous.y;
        const auto& baseU = checkpoint ? zeroU : previous.u;
        const auto& baseV = checkpoint ? zeroV : previous.v;
        auto statePreimage = digestPreimage("UGYUVS1-executable-seed-state-v1");
        appendDigest(statePreimage, impl_->staticSha);
        appendDigest(statePreimage, impl_->recipeSha);
        appendU32(statePreimage, ordinal);
        appendU32(statePreimage, previousOrdinal);
        appendU64(statePreimage, static_cast<std::uint64_t>(sensorPts));
        appendU64(statePreimage, static_cast<std::uint64_t>(frameNumber));
        appendDigest(statePreimage, checkpoint ? zeroYSha : previousYSha);
        appendDigest(statePreimage, checkpoint ? zeroUSha : previousUSha);
        appendDigest(statePreimage, checkpoint ? zeroVSha : previousVSha);
        require(getDigest(header.data(), header.size(), 272u) ==
                    sha256(statePreimage.data(), statePreimage.size()),
                "executable seed state SHA-256 mismatch");

        std::vector<std::uint8_t> residual;
        residual.reserve(yBytes + cBytes * 2u);
        std::uint64_t noveltyEventCount = 0u;
        std::size_t noveltyPosition = 0u;
        std::size_t ownerCount = 0u;
        const auto expectedBlocks = static_cast<std::uint32_t>(
            (yBytes + impl_->profile.noveltyBlockLumaAddresses - 1u) /
            impl_->profile.noveltyBlockLumaAddresses);
        require(blockCount == expectedBlocks, "novelty block count mismatch");
        for (std::uint32_t blockOrdinal = 0u; blockOrdinal < blockCount; ++blockOrdinal) {
            require(noveltyPosition + BlockHeaderBytes <= noveltyBytes,
                    "novelty block header is truncated");
            const auto* block = payload.data() + noveltyPosition;
            require(std::memcmp(block, "UGNBLK1\0", 8u) == 0 &&
                        getU16(block, BlockHeaderBytes, 8u) == 1u &&
                        getU16(block, BlockHeaderBytes, 10u) == 0u &&
                        getU32(block, BlockHeaderBytes, 12u) == BlockHeaderBytes &&
                        getU32(block, BlockHeaderBytes, 16u) == blockOrdinal,
                    "novelty block ABI mismatch");
            const auto first = getU32(block, BlockHeaderBytes, 20u);
            const auto lumaCount = getU32(block, BlockHeaderBytes, 24u);
            const auto blockSymbols = getU32(block, BlockHeaderBytes, 28u);
            const auto auxiliaryBytes = getU32(block, BlockHeaderBytes, 32u);
            const auto valueBytes = getU32(block, BlockHeaderBytes, 36u);
            const auto predictor = static_cast<YuvPredictorProgram>(
                getU32(block, BlockHeaderBytes, BlockPredictorOffset));
            const auto representation = getU32(
                block, BlockHeaderBytes, BlockNoveltyMethodOffset);
            require(first == static_cast<std::uint64_t>(blockOrdinal) *
                                impl_->profile.noveltyBlockLumaAddresses &&
                        lumaCount == std::min<std::size_t>(
                            impl_->profile.noveltyBlockLumaAddresses, yBytes - first),
                    "novelty block luma range mismatch");
            std::size_t expectedSymbols = lumaCount;
            for (std::size_t local = 0u; local < lumaCount; ++local) {
                const auto address = impl_->traversal.polarOrdinalToCartesian[first + local];
                const auto x = address % width;
                const auto y = address / width;
                if ((x & 1u) == 0u && (y & 1u) == 0u) {
                    expectedSymbols += 2u;
                    ++ownerCount;
                }
            }
            const auto expectedPredictor = checkpoint
                ? YuvPredictorProgram::RawExactLane
                : YuvPredictorProgram::PreviousSameAddress;
            require(blockSymbols == expectedSymbols &&
                        noveltyPosition + BlockHeaderBytes + auxiliaryBytes + valueBytes <=
                            noveltyBytes &&
                        predictor == expectedPredictor &&
                        representation <= NoveltySparseGaps &&
                        getDigest(block, BlockHeaderBytes, BlockLineageDigestOffset) ==
                            blockLineageDigest(
                                ordinal,
                                impl_->lineageSeeds,
                                first,
                                lumaCount) &&
                        allZero(block + 176u, 16u),
                    "novelty block sizes/reserved bytes mismatch");
            const auto* auxiliary = block + BlockHeaderBytes;
            const auto* values = auxiliary + auxiliaryBytes;
            std::vector<std::uint8_t> logical(expectedSymbols, 0u);
            std::size_t valuePosition = 0u;
            if (representation == NoveltyZero) {
                require(auxiliaryBytes == 0u && valueBytes == 0u,
                        "ZERO novelty block carries a payload");
            } else if (representation == NoveltyDense) {
                require(auxiliaryBytes == 0u && valueBytes == expectedSymbols,
                        "DENSE novelty block length mismatch");
                std::copy_n(values, expectedSymbols, logical.begin());
                valuePosition = static_cast<std::size_t>(std::count_if(
                    logical.begin(), logical.end(),
                    [](std::uint8_t value) { return value != 0u; }));
            } else if (representation == NoveltySparseBitmask) {
                require(auxiliaryBytes == (expectedSymbols + 7u) / 8u,
                        "SPARSE_BITMASK occupancy length mismatch");
                if ((expectedSymbols & 7u) != 0u) {
                    const auto usedBits = expectedSymbols & 7u;
                    require((auxiliary[auxiliaryBytes - 1u] &
                             ~((1u << usedBits) - 1u)) == 0u,
                            "SPARSE_BITMASK padding bits are nonzero");
                }
                for (std::size_t symbol = 0u; symbol < expectedSymbols; ++symbol) {
                    if ((auxiliary[symbol >> 3u] & (1u << (symbol & 7u))) != 0u) {
                        require(valuePosition < valueBytes && values[valuePosition] != 0u,
                                "SPARSE_BITMASK nonzero stream is invalid");
                        logical[symbol] = values[valuePosition++];
                    }
                }
            } else {
                require(valueBytes > 0u,
                        "SPARSE_GAPS requires at least one novelty event");
                std::size_t gapPosition = 0u;
                std::size_t nextOrdinal = 0u;
                while (gapPosition < auxiliaryBytes) {
                    require(valuePosition < valueBytes,
                            "SPARSE_GAPS has more indexes than values");
                    const auto gap = readCanonicalUleb128(
                        auxiliary, auxiliaryBytes, gapPosition);
                    require(gap <= expectedSymbols - nextOrdinal,
                            "SPARSE_GAPS address escapes the logical block");
                    const auto symbol = nextOrdinal + gap;
                    require(symbol < expectedSymbols && values[valuePosition] != 0u,
                            "SPARSE_GAPS nonzero event is invalid");
                    logical[symbol] = values[valuePosition++];
                    nextOrdinal = symbol + 1u;
                }
            }
            require((representation == NoveltyDense || valuePosition == valueBytes),
                    "novelty value count disagrees with its representation");
            const auto blockEventCount = static_cast<std::size_t>(std::count_if(
                logical.begin(), logical.end(),
                [](std::uint8_t value) { return value != 0u; }));
            require(representation == NoveltyDense || blockEventCount == valueBytes,
                    "sparse novelty event count mismatch");
            auto canonicalRepresentation = NoveltyZero;
            auto canonicalPayloadBytes = std::size_t{0u};
            std::vector<std::uint8_t> canonicalGaps;
            auto canonicalNext = std::size_t{0u};
            for (std::size_t symbol = 0u; symbol < logical.size(); ++symbol) {
                if (logical[symbol] != 0u) {
                    appendUleb128(canonicalGaps, symbol - canonicalNext);
                    canonicalNext = symbol + 1u;
                }
            }
            if (blockEventCount != 0u) {
                canonicalRepresentation = NoveltyDense;
                canonicalPayloadBytes = expectedSymbols;
                const auto bitmaskPayload =
                    (expectedSymbols + 7u) / 8u + blockEventCount;
                if (bitmaskPayload < canonicalPayloadBytes) {
                    canonicalRepresentation = NoveltySparseBitmask;
                    canonicalPayloadBytes = bitmaskPayload;
                }
                const auto gapPayload = canonicalGaps.size() + blockEventCount;
                if (gapPayload < canonicalPayloadBytes) {
                    canonicalRepresentation = NoveltySparseGaps;
                    canonicalPayloadBytes = gapPayload;
                }
            }
            require(representation == canonicalRepresentation &&
                        auxiliaryBytes + valueBytes == canonicalPayloadBytes &&
                        (representation != NoveltySparseGaps ||
                         (canonicalGaps.size() == auxiliaryBytes &&
                          std::equal(canonicalGaps.begin(), canonicalGaps.end(), auxiliary))),
                    "novelty representation is not the canonical byte-smallest choice");
            noveltyEventCount += blockEventCount;
            require(getDigest(block, BlockHeaderBytes, 40u) ==
                        sha256(logical.data(), logical.size()) &&
                        getDigest(block, BlockHeaderBytes, 72u) ==
                        sha256(values, valueBytes),
                    "novelty block logical/value SHA-256 mismatch");
            std::vector<std::uint8_t> blockBytes(
                block, block + BlockHeaderBytes + auxiliaryBytes + valueBytes);
            require(getDigest(block, BlockHeaderBytes, BlockContentDigestOffset) ==
                        hashWithZeroRange(blockBytes, BlockContentDigestOffset, 32u),
                    "novelty block content SHA-256 mismatch");
            residual.insert(residual.end(), logical.begin(), logical.end());
            noveltyPosition += BlockHeaderBytes + auxiliaryBytes + valueBytes;
        }
        require(noveltyPosition == noveltyBytes && ownerCount == cBytes &&
                    residual.size() == logicalSymbols &&
                    noveltyEventCount ==
                        getU64(header.data(), header.size(), FrameNoveltyEventCountOffset) &&
                    getDigest(header.data(), header.size(), 176u) ==
                        sha256(residual.data(), residual.size()),
                "novelty residual/owner invariant mismatch");
        DenseYuv420p8Frame current{};
        current.width = width;
        current.height = height;
        current.sensorTimestampNs = sensorPts;
        current.frameNumber = frameNumber;
        current.y = baseY;
        current.u = baseU;
        current.v = baseV;
        current.canonicalMetadata.assign(
            payload.begin() + static_cast<std::ptrdiff_t>(noveltyBytes), payload.end());
        require(current.canonicalMetadata.size() == metadataCount &&
                    getDigest(header.data(), header.size(), 208u) ==
                        sha256(current.canonicalMetadata.data(), current.canonicalMetadata.size()),
                "canonical metadata length/SHA-256 mismatch");
        std::size_t residualPosition = 0u;
        std::size_t reconstructedOwners = 0u;
        for (const auto address : impl_->traversal.polarOrdinalToCartesian) {
            current.y[address] = static_cast<std::uint8_t>(
                static_cast<unsigned>(current.y[address]) + residual[residualPosition++]);
            const auto x = address % width;
            const auto y = address / width;
            if ((x & 1u) == 0u && (y & 1u) == 0u) {
                const auto chroma = static_cast<std::size_t>(y / 2u) * chromaWidth + x / 2u;
                current.u[chroma] = static_cast<std::uint8_t>(
                    static_cast<unsigned>(current.u[chroma]) + residual[residualPosition++]);
                current.v[chroma] = static_cast<std::uint8_t>(
                    static_cast<unsigned>(current.v[chroma]) + residual[residualPosition++]);
                ++reconstructedOwners;
            }
        }
        require(residualPosition == residual.size() && reconstructedOwners == cBytes,
                "UGCODE24-420 reconstruction ownership mismatch");
        const auto ySha = sha256(current.y.data(), current.y.size());
        const auto uSha = sha256(current.u.data(), current.u.size());
        const auto vSha = sha256(current.v.data(), current.v.size());
        require(ySha == getDigest(header.data(), header.size(), 80u) &&
                    uSha == getDigest(header.data(), header.size(), 112u) &&
                    vSha == getDigest(header.data(), header.size(), 144u) &&
                    preSubstrateFrameSha256(current) ==
                        getDigest(
                            header.data(), header.size(), FramePreSubstrateDigestOffset),
                "pre-entropy dense plane SHA-256 mismatch");
        // Materialize once during strict replay to enforce the logical codeword
        // view and its dense 2x2 chroma mapping at every luma address.
        require(expandUgcode24_420(current).size() == yBytes * 3u,
                "UGCODE24-420 expanded codeword size mismatch");
        consume(current);
        previous = std::move(current);
        previousYSha = ySha;
        previousUSha = uSha;
        previousVSha = vSha;
        previousPts = sensorPts;
        terminal = getDigest(header.data(), header.size(), FrameContentDigestOffset);
    }
    if (impl_->commit.finalized) {
        const auto end = readExact(stream, TerminalHeaderBytes, "terminal record");
        consumedBytes += end.size();
        require(std::memcmp(end.data(), "UGYEND1\0", 8u) == 0 &&
                    getU16(end.data(), end.size(), 8u) == 1u &&
                    getU16(end.data(), end.size(), 10u) == 0u &&
                    getU32(end.data(), end.size(), 12u) == TerminalHeaderBytes &&
                    getU32(end.data(), end.size(), 16u) == 0u &&
                    getU32(end.data(), end.size(), 20u) == 0u &&
                    getU64(end.data(), end.size(), 24u) == impl_->commit.frameCount &&
                    getU64(end.data(), end.size(), 32u) + TerminalHeaderBytes ==
                        impl_->commit.committedEnd &&
                    getI64(end.data(), end.size(), 40u) == previousPts &&
                    getDigest(end.data(), end.size(), 48u) == terminal &&
                    getDigest(end.data(), end.size(), 80u) == impl_->staticSha &&
                    getDigest(end.data(), end.size(), 112u) == impl_->recipeSha &&
                    allZero(end.data() + 176u, 16u),
                "terminal record fields are invalid");
        const auto endSha = getDigest(
            end.data(), end.size(), TerminalContentDigestOffset);
        require(endSha == hashWithZeroRange(
                    end, TerminalContentDigestOffset, 32u) &&
                    endSha == impl_->commit.terminal,
                "terminal record SHA-256/commit gate mismatch");
        terminal = endSha;
    }
    require(consumedBytes == impl_->commit.committedEnd &&
                terminal == impl_->commit.terminal &&
                (impl_->commit.frameCount == 0u || previousPts == impl_->commit.lastPts),
            "commit slot does not match replayed record chain");
}

std::vector<DenseYuv420p8Frame> YuvSeedCaptureReader::decodeAll() const {
    std::vector<DenseYuv420p8Frame> frames;
    require(impl_->commit.frameCount <= std::numeric_limits<std::size_t>::max(),
            "frame count exceeds host address space");
    frames.reserve(static_cast<std::size_t>(impl_->commit.frameCount));
    replay([&frames](const DenseYuv420p8Frame& frame) { frames.push_back(frame); });
    return frames;
}

std::uint32_t gsp4Mix32(std::uint32_t value) noexcept {
    value ^= value >> 16u;
    value *= 0x7feb352du;
    value ^= value >> 15u;
    value *= 0x846ca68bu;
    value ^= value >> 16u;
    return value;
}

Gsp4CodewordLineage gsp4CodewordLineage(
    std::uint64_t rootSeed,
    std::uint64_t recipeSeed,
    std::uint64_t cartesianAddress,
    std::uint32_t frameOrdinal
) noexcept {
    const auto session = combineSeed(rootSeed, recipeSeed);
    const auto persistent = stableId(
        session, Gsp4CameraLineageNamespace, cartesianAddress);
    Gsp4CodewordLineage result{};
    result.lineageSeed = static_cast<std::uint32_t>(persistent);
    result.routedHash = gsp4Mix32(result.lineageSeed ^ frameOrdinal);
    return result;
}

Sha256Digest preSubstrateFrameSha256(const DenseYuv420p8Frame& frame) {
    require(frame.width >= 2u && frame.height >= 2u &&
                frame.width <= 65534u && frame.height <= 65534u &&
                (frame.width & 1u) == 0u && (frame.height & 1u) == 0u,
            "pre-substrate digest requires valid even dimensions");
    require(frame.sensorTimestampNs >= 0,
            "pre-substrate digest requires a nonnegative sensor timestamp");
    const auto yBytes = static_cast<std::size_t>(frame.width) * frame.height;
    const auto cBytes = static_cast<std::size_t>(frame.width / 2u) * (frame.height / 2u);
    require(frame.y.size() == yBytes && frame.u.size() == cBytes && frame.v.size() == cBytes,
            "pre-substrate digest plane sizes are invalid");
    std::vector<std::uint8_t> preimage;
    preimage.reserve(16u + yBytes + cBytes * 2u);
    appendU64(preimage, static_cast<std::uint64_t>(frame.sensorTimestampNs));
    appendU32(preimage, frame.width);
    appendU32(preimage, frame.height);
    preimage.insert(preimage.end(), frame.y.begin(), frame.y.end());
    preimage.insert(preimage.end(), frame.u.begin(), frame.u.end());
    preimage.insert(preimage.end(), frame.v.begin(), frame.v.end());
    return sha256(preimage.data(), preimage.size());
}

std::vector<std::uint8_t> expandUgcode24_420(const DenseYuv420p8Frame& frame) {
    require(frame.width >= 2u && frame.height >= 2u &&
                (frame.width & 1u) == 0u && (frame.height & 1u) == 0u,
            "UGCODE24-420 expansion requires positive even dimensions");
    const auto yBytes = static_cast<std::size_t>(frame.width) * frame.height;
    const auto chromaWidth = frame.width / 2u;
    const auto cBytes = static_cast<std::size_t>(chromaWidth) * (frame.height / 2u);
    require(frame.y.size() == yBytes && frame.u.size() == cBytes && frame.v.size() == cBytes,
            "dense YUV420 plane sizes are invalid");
    std::vector<std::uint8_t> result(yBytes * 3u);
    for (std::uint32_t y = 0u; y < frame.height; ++y) {
        for (std::uint32_t x = 0u; x < frame.width; ++x) {
            const auto luma = static_cast<std::size_t>(y) * frame.width + x;
            const auto chroma = static_cast<std::size_t>(y / 2u) * chromaWidth + x / 2u;
            result[luma * 3u] = frame.y[luma];
            result[luma * 3u + 1u] = frame.u[chroma];
            result[luma * 3u + 2u] = frame.v[chroma];
        }
    }
    return result;
}

} // namespace ugts::chrono
