#include "ugts_go19/persistent_state_store.hpp"

#include "ugts_go19/sha256.hpp"

#include <array>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace ugts_go19 {
namespace {

constexpr std::string_view kSegmentMagic =
    "UGTS-CPP-PERSISTENT-BOARD-SEGMENT-v1";
constexpr std::string_view kFooterMagic = "UGTS-CPP-PERSISTENT-BOARD-FOOTER-v1";
constexpr std::string_view kBoardLocatorTag =
    "UGTS-CPP-PACKED-BOARD-LOCATOR-v1";

constexpr std::uint8_t kLittleEndianTag = 1U;
constexpr std::uint8_t kBoardSegmentKind = 1U;
constexpr std::uint8_t kBoardRecordVersion = 1U;
constexpr std::uint8_t kBoardRecordKind = 1U;
constexpr std::uint32_t kBoardRecordBytes = 152U;
constexpr std::uint32_t kBoardIndexEntryBytes = 56U;
constexpr std::size_t kDigestBytes = 32U;
constexpr std::size_t kPackedWords = 6U;

constexpr std::uint64_t kHeaderBytes = static_cast<std::uint64_t>(
    kSegmentMagic.size() + 1U + 1U + 1U + 2U + 4U + 8U * 8U);
constexpr std::uint64_t kFooterBytes = static_cast<std::uint64_t>(
    kFooterMagic.size() + 1U + 1U + 1U + 2U + 8U * 3U + kDigestBytes);
static_assert(kHeaderBytes == 109U, "v1 header width changed");
static_assert(kFooterBytes == 96U, "v1 footer width changed");

void AppendU8(std::string &output, std::uint8_t value) {
  output.push_back(static_cast<char>(value));
}

void AppendU16(std::string &output, std::uint16_t value) {
  for (unsigned int shift = 0; shift < 16U; shift += 8U) {
    AppendU8(output, static_cast<std::uint8_t>((value >> shift) & 0xffU));
  }
}

void AppendU32(std::string &output, std::uint32_t value) {
  for (unsigned int shift = 0; shift < 32U; shift += 8U) {
    AppendU8(output, static_cast<std::uint8_t>((value >> shift) & 0xffU));
  }
}

void AppendU64(std::string &output, std::uint64_t value) {
  for (unsigned int shift = 0; shift < 64U; shift += 8U) {
    AppendU8(output, static_cast<std::uint8_t>((value >> shift) & 0xffU));
  }
}

void AppendMagic(std::string &output, std::string_view magic) {
  output.append(magic.data(), magic.size());
  AppendU8(output, 0U);
}

void AppendDigest(std::string &output, const LocatorDigest256 &digest) {
  for (std::uint8_t byte : digest)
    AppendU8(output, byte);
}

std::uint8_t HexNibble(char value) {
  if (value >= '0' && value <= '9') {
    return static_cast<std::uint8_t>(value - '0');
  }
  if (value >= 'a' && value <= 'f') {
    return static_cast<std::uint8_t>(value - 'a' + 10);
  }
  throw std::logic_error("SHA-256 returned non-lowercase-hex output");
}

LocatorDigest256 DecodeSha256Hex(const std::string &hex) {
  if (hex.size() != kDigestBytes * 2U) {
    throw std::logic_error("SHA-256 returned the wrong digest length");
  }
  LocatorDigest256 digest{};
  for (std::size_t index = 0; index < digest.size(); ++index) {
    digest[index] = static_cast<std::uint8_t>(
        (HexNibble(hex[index * 2U]) << 4U) | HexNibble(hex[index * 2U + 1U]));
  }
  return digest;
}

std::uint64_t SizeAsU64(std::size_t value, const char *label) {
  if constexpr (sizeof(std::size_t) > sizeof(std::uint64_t)) {
    if (value >
        static_cast<std::size_t>(std::numeric_limits<std::uint64_t>::max())) {
      throw std::length_error(std::string(label) + " exceeds uint64");
    }
  }
  return static_cast<std::uint64_t>(value);
}

std::size_t U64AsSize(std::uint64_t value, const char *label) {
  if (value >
      static_cast<std::uint64_t>(std::numeric_limits<std::size_t>::max())) {
    throw std::length_error(std::string(label) + " exceeds size_t");
  }
  return static_cast<std::size_t>(value);
}

std::uint64_t CheckedEncodeAdd(std::uint64_t left, std::uint64_t right,
                               const char *label) {
  if (left > std::numeric_limits<std::uint64_t>::max() - right) {
    throw std::length_error(std::string(label) + " exceeds uint64");
  }
  return left + right;
}

std::uint64_t CheckedEncodeMultiply(std::uint64_t left, std::uint64_t right,
                                    const char *label) {
  if (left != 0U && right > std::numeric_limits<std::uint64_t>::max() / left) {
    throw std::length_error(std::string(label) + " exceeds uint64");
  }
  return left * right;
}

std::uint64_t CheckedDecodeAdd(std::uint64_t left, std::uint64_t right,
                               const char *label) {
  if (left > std::numeric_limits<std::uint64_t>::max() - right) {
    throw std::invalid_argument(std::string(label) +
                                " offset arithmetic overflow");
  }
  return left + right;
}

std::uint64_t CheckedDecodeMultiply(std::uint64_t left, std::uint64_t right,
                                    const char *label) {
  if (left != 0U && right > std::numeric_limits<std::uint64_t>::max() / left) {
    throw std::invalid_argument(std::string(label) +
                                " byte-count arithmetic overflow");
  }
  return left * right;
}

std::string BoardLocatorMaterial(const PackedBoard &board) {
  std::string material;
  material.reserve(kBoardLocatorTag.size() + 1U + 12U * 8U);
  material.append(kBoardLocatorTag.data(), kBoardLocatorTag.size());
  AppendU8(material, board.size);
  for (std::uint64_t word : board.black)
    AppendU64(material, word);
  for (std::uint64_t word : board.white)
    AppendU64(material, word);
  return material;
}

LocatorDigest256 LocateBoard(const PackedBoard &board,
                             const PersistentStateStoreCodecConfig &config) {
  const std::string material = BoardLocatorMaterial(board);
  if (config.board_locator)
    return config.board_locator(material);
  return DecodeSha256Hex(Sha256Hex(material));
}

void ValidateBoard(const PackedBoard &board) {
  // The existing exact unpacker owns the packed-board validity rules. Its
  // result is intentionally discarded after size, overlap, word, and tail
  // validation.
  static_cast<void>(UnpackBoardExact(board));
}

class Reader {
public:
  explicit Reader(std::string_view bytes, std::size_t offset = 0U)
      : bytes_(bytes), position_(offset) {
    if (offset > bytes_.size()) {
      throw std::invalid_argument(
          "persistent board segment offset is past EOF");
    }
  }

  void ReadMagic(std::string_view expected, const char *label) {
    for (char byte : expected) {
      if (ReadU8(label) != static_cast<std::uint8_t>(byte)) {
        throw std::invalid_argument(std::string(label) + " mismatch");
      }
    }
    if (ReadU8(label) != 0U) {
      throw std::invalid_argument(std::string(label) + " mismatch");
    }
  }

  std::uint8_t ReadU8(const char *label) {
    if (position_ >= bytes_.size()) {
      throw std::invalid_argument(std::string("persistent board segment is ") +
                                  "truncated while reading " + label);
    }
    return static_cast<std::uint8_t>(
        static_cast<unsigned char>(bytes_[position_++]));
  }

  std::uint16_t ReadU16(const char *label) {
    std::uint16_t value = 0;
    for (unsigned int shift = 0; shift < 16U; shift += 8U) {
      value |= static_cast<std::uint16_t>(ReadU8(label)) << shift;
    }
    return value;
  }

  std::uint32_t ReadU32(const char *label) {
    std::uint32_t value = 0;
    for (unsigned int shift = 0; shift < 32U; shift += 8U) {
      value |= static_cast<std::uint32_t>(ReadU8(label)) << shift;
    }
    return value;
  }

  std::uint64_t ReadU64(const char *label) {
    std::uint64_t value = 0;
    for (unsigned int shift = 0; shift < 64U; shift += 8U) {
      value |= static_cast<std::uint64_t>(ReadU8(label)) << shift;
    }
    return value;
  }

  LocatorDigest256 ReadDigest(const char *label) {
    LocatorDigest256 digest{};
    for (std::uint8_t &byte : digest)
      byte = ReadU8(label);
    return digest;
  }

  [[nodiscard]] std::size_t position() const noexcept { return position_; }

  void RequirePosition(std::uint64_t expected, const char *label) const {
    if (SizeAsU64(position_, label) != expected) {
      throw std::invalid_argument(std::string(label) +
                                  " has noncanonical byte width");
    }
  }

  void RequireEnd() const {
    if (position_ != bytes_.size()) {
      throw std::invalid_argument(
          "persistent board segment has trailing bytes");
    }
  }

private:
  std::string_view bytes_;
  std::size_t position_ = 0;
};

struct EncodedRecordMetadata {
  std::uint64_t id = 0;
  std::uint64_t offset = 0;
  LocatorDigest256 locator{};
};

} // namespace

std::string EncodePersistentBoardSegmentV1(
    const std::vector<PersistentBoardRecordInput> &records,
    const PersistentStateStoreCodecConfig &config) {
  const std::uint64_t record_count =
      SizeAsU64(records.size(), "persistent board record count");
  if (record_count == 0U) {
    throw std::invalid_argument(
        "persistent board segment must contain at least one record");
  }
  if (record_count > config.limits.max_board_records) {
    throw std::length_error(
        "persistent board record count exceeds configured limit");
  }
  if (kBoardRecordBytes > config.limits.max_record_bytes) {
    throw std::length_error(
        "persistent board record width exceeds configured limit");
  }

  const std::uint64_t records_bytes = CheckedEncodeMultiply(
      record_count, kBoardRecordBytes, "persistent board records");
  const std::uint64_t index_bytes = CheckedEncodeMultiply(
      record_count, kBoardIndexEntryBytes, "persistent board index");
  const std::uint64_t records_offset = kHeaderBytes;
  const std::uint64_t index_offset = CheckedEncodeAdd(
      records_offset, records_bytes, "persistent board segment");
  const std::uint64_t footer_offset =
      CheckedEncodeAdd(index_offset, index_bytes, "persistent board segment");
  const std::uint64_t segment_bytes =
      CheckedEncodeAdd(footer_offset, kFooterBytes, "persistent board segment");
  if (segment_bytes > config.limits.max_segment_bytes) {
    throw std::length_error(
        "persistent board segment exceeds configured byte limit");
  }

  std::string output;
  output.reserve(U64AsSize(segment_bytes, "persistent board segment"));
  AppendMagic(output, kSegmentMagic);
  AppendU8(output, kLittleEndianTag);
  AppendU8(output, kBoardSegmentKind);
  AppendU16(output, 0U); // flags
  AppendU32(output, 0U); // reserved
  AppendU64(output, kHeaderBytes);
  AppendU64(output, record_count);
  AppendU64(output, records_offset);
  AppendU64(output, records_bytes);
  AppendU64(output, index_offset);
  AppendU64(output, index_bytes);
  AppendU64(output, footer_offset);
  AppendU64(output, segment_bytes);
  if (SizeAsU64(output.size(), "persistent board header") != kHeaderBytes) {
    throw std::logic_error("persistent board header width changed");
  }

  std::vector<EncodedRecordMetadata> metadata;
  metadata.reserve(records.size());
  std::uint64_t previous_id = 0U;
  for (const PersistentBoardRecordInput &record : records) {
    if (record.id == 0U || record.id <= previous_id) {
      throw std::invalid_argument(
          "persistent board record IDs must be positive and strictly "
          "increasing");
    }
    ValidateBoard(record.board);
    const LocatorDigest256 locator = LocateBoard(record.board, config);
    const std::uint64_t offset =
        SizeAsU64(output.size(), "persistent board record offset");
    metadata.push_back({record.id, offset, locator});

    AppendU32(output, kBoardRecordBytes);
    AppendU8(output, kBoardRecordVersion);
    AppendU8(output, kBoardRecordKind);
    AppendU16(output, 0U); // reserved
    AppendU64(output, record.id);
    AppendU8(output, record.board.size);
    AppendU8(output, 0U);  // reserved
    AppendU16(output, 0U); // reserved
    AppendU32(output, 0U); // reserved
    for (std::uint64_t word : record.board.black)
      AppendU64(output, word);
    for (std::uint64_t word : record.board.white)
      AppendU64(output, word);
    AppendDigest(output, locator);
    if (SizeAsU64(output.size(), "persistent board record") !=
        CheckedEncodeAdd(offset, kBoardRecordBytes,
                         "persistent board record")) {
      throw std::logic_error("persistent board record width changed");
    }
    previous_id = record.id;
  }
  if (SizeAsU64(output.size(), "persistent board records") != index_offset) {
    throw std::logic_error("persistent board records width changed");
  }

  for (const EncodedRecordMetadata &entry : metadata) {
    AppendU64(output, entry.id);
    AppendU64(output, entry.offset);
    AppendU32(output, kBoardRecordBytes);
    AppendU32(output, 0U); // reserved
    AppendDigest(output, entry.locator);
  }
  if (SizeAsU64(output.size(), "persistent board index") != footer_offset) {
    throw std::logic_error("persistent board index width changed");
  }

  const std::string body_sha256 = Sha256Hex(output);
  AppendMagic(output, kFooterMagic);
  AppendU8(output, kLittleEndianTag);
  AppendU8(output, 0U);  // flags
  AppendU16(output, 0U); // reserved
  AppendU64(output, kFooterBytes);
  AppendU64(output, footer_offset);
  AppendU64(output, segment_bytes);
  AppendDigest(output, DecodeSha256Hex(body_sha256));
  if (SizeAsU64(output.size(), "persistent board segment") != segment_bytes) {
    throw std::logic_error("persistent board segment width changed");
  }
  return output;
}

DecodedPersistentBoardSegment
DecodePersistentBoardSegmentV1(const std::string &bytes,
                               const PersistentStateStoreCodecConfig &config) {
  const std::uint64_t byte_count =
      SizeAsU64(bytes.size(), "persistent board segment");
  if (byte_count > config.limits.max_segment_bytes) {
    throw std::length_error(
        "persistent board segment exceeds configured byte limit");
  }
  const std::uint64_t minimum_bytes =
      CheckedEncodeAdd(CheckedEncodeAdd(kHeaderBytes, kBoardRecordBytes,
                                        "minimum persistent board segment"),
                       CheckedEncodeAdd(kBoardIndexEntryBytes, kFooterBytes,
                                        "minimum persistent board segment"),
                       "minimum persistent board segment");
  if (byte_count < minimum_bytes) {
    throw std::invalid_argument("persistent board segment is truncated");
  }

  Reader header(bytes);
  header.ReadMagic(kSegmentMagic, "persistent board segment magic");
  const std::uint8_t endian = header.ReadU8("endianness");
  const std::uint8_t segment_kind = header.ReadU8("segment kind");
  const std::uint16_t flags = header.ReadU16("header flags");
  const std::uint32_t reserved = header.ReadU32("header reserved field");
  const std::uint64_t header_bytes = header.ReadU64("header byte count");
  const std::uint64_t record_count = header.ReadU64("record count");
  const std::uint64_t records_offset = header.ReadU64("records offset");
  const std::uint64_t records_bytes = header.ReadU64("records byte count");
  const std::uint64_t index_offset = header.ReadU64("index offset");
  const std::uint64_t index_bytes = header.ReadU64("index byte count");
  const std::uint64_t footer_offset = header.ReadU64("footer offset");
  const std::uint64_t segment_bytes = header.ReadU64("segment byte count");
  header.RequirePosition(kHeaderBytes, "persistent board header");

  if (endian != kLittleEndianTag || segment_kind != kBoardSegmentKind ||
      flags != 0U || reserved != 0U) {
    throw std::invalid_argument(
        "persistent board header tags or reserved fields are unsupported");
  }
  if (record_count == 0U) {
    throw std::invalid_argument(
        "persistent board segment must contain at least one record");
  }
  if (record_count > config.limits.max_board_records) {
    throw std::length_error(
        "persistent board record count exceeds configured limit");
  }
  if (kBoardRecordBytes > config.limits.max_record_bytes) {
    throw std::length_error(
        "persistent board record width exceeds configured limit");
  }
  if (record_count >
      static_cast<std::uint64_t>(std::numeric_limits<std::size_t>::max())) {
    throw std::length_error("persistent board record count exceeds size_t");
  }

  const std::uint64_t calculated_records_bytes = CheckedDecodeMultiply(
      record_count, kBoardRecordBytes, "persistent board records");
  const std::uint64_t calculated_index_bytes = CheckedDecodeMultiply(
      record_count, kBoardIndexEntryBytes, "persistent board index");
  const std::uint64_t declared_records_end = CheckedDecodeAdd(
      records_offset, records_bytes, "persistent board records");
  const std::uint64_t declared_index_end =
      CheckedDecodeAdd(index_offset, index_bytes, "persistent board index");
  const std::uint64_t declared_segment_end =
      CheckedDecodeAdd(footer_offset, kFooterBytes, "persistent board footer");
  if (header_bytes != kHeaderBytes || records_offset != kHeaderBytes ||
      records_bytes != calculated_records_bytes ||
      declared_records_end != index_offset ||
      index_bytes != calculated_index_bytes ||
      declared_index_end != footer_offset ||
      declared_segment_end != segment_bytes || segment_bytes != byte_count) {
    throw std::invalid_argument(
        "persistent board segment layout is noncanonical");
  }

  Reader footer(bytes, U64AsSize(footer_offset, "persistent board footer"));
  footer.ReadMagic(kFooterMagic, "persistent board footer magic");
  const std::uint8_t footer_endian = footer.ReadU8("footer endianness");
  const std::uint8_t footer_flags = footer.ReadU8("footer flags");
  const std::uint16_t footer_reserved = footer.ReadU16("footer reserved field");
  const std::uint64_t footer_bytes = footer.ReadU64("footer byte count");
  const std::uint64_t footer_body_bytes = footer.ReadU64("footer body bytes");
  const std::uint64_t footer_segment_bytes =
      footer.ReadU64("footer segment bytes");
  const LocatorDigest256 stored_body_digest =
      footer.ReadDigest("footer body SHA-256");
  footer.RequireEnd();
  if (footer_endian != kLittleEndianTag || footer_flags != 0U ||
      footer_reserved != 0U || footer_bytes != kFooterBytes ||
      footer_body_bytes != footer_offset ||
      footer_segment_bytes != segment_bytes) {
    throw std::invalid_argument(
        "persistent board footer fields are noncanonical");
  }

  const std::string body_sha256 = Sha256Hex(std::string_view(
      bytes.data(), U64AsSize(footer_offset, "persistent board body")));
  if (stored_body_digest != DecodeSha256Hex(body_sha256)) {
    throw std::invalid_argument(
        "persistent board segment body SHA-256 mismatch");
  }

  Reader body(bytes, U64AsSize(records_offset, "persistent board records"));
  std::vector<DecodedPersistentBoardRecord> records;
  records.reserve(static_cast<std::size_t>(record_count));
  std::vector<std::uint64_t> record_offsets;
  record_offsets.reserve(static_cast<std::size_t>(record_count));
  std::uint64_t previous_id = 0U;
  for (std::uint64_t index = 0U; index < record_count; ++index) {
    const std::uint64_t record_offset =
        SizeAsU64(body.position(), "persistent board record offset");
    const std::uint32_t record_bytes = body.ReadU32("record byte count");
    const std::uint8_t version = body.ReadU8("record version");
    const std::uint8_t kind = body.ReadU8("record kind");
    const std::uint16_t record_reserved = body.ReadU16("record reserved field");
    const std::uint64_t id = body.ReadU64("record ID");
    PackedBoard board;
    board.size = body.ReadU8("board size");
    const std::uint8_t board_reserved8 = body.ReadU8("board reserved field");
    const std::uint16_t board_reserved16 = body.ReadU16("board reserved field");
    const std::uint32_t board_reserved32 = body.ReadU32("board reserved field");
    for (std::uint64_t &word : board.black) {
      word = body.ReadU64("black bitplane");
    }
    for (std::uint64_t &word : board.white) {
      word = body.ReadU64("white bitplane");
    }
    const LocatorDigest256 stored_locator = body.ReadDigest("board locator");

    if (record_bytes != kBoardRecordBytes ||
        record_bytes > config.limits.max_record_bytes ||
        version != kBoardRecordVersion || kind != kBoardRecordKind ||
        record_reserved != 0U || board_reserved8 != 0U ||
        board_reserved16 != 0U || board_reserved32 != 0U) {
      throw std::invalid_argument(
          "persistent board record fields are noncanonical");
    }
    if (id == 0U || id <= previous_id) {
      throw std::invalid_argument(
          "persistent board record IDs are duplicate or out of order");
    }
    body.RequirePosition(CheckedDecodeAdd(record_offset, record_bytes,
                                          "persistent board record"),
                         "persistent board record");
    ValidateBoard(board);
    const LocatorDigest256 expected_locator = LocateBoard(board, config);
    if (stored_locator != expected_locator) {
      throw std::invalid_argument("persistent board locator mismatch");
    }

    records.push_back({id, board, stored_locator});
    record_offsets.push_back(record_offset);
    previous_id = id;
  }
  body.RequirePosition(index_offset, "persistent board records");

  for (std::size_t index = 0; index < records.size(); ++index) {
    const std::uint64_t id = body.ReadU64("index record ID");
    const std::uint64_t offset = body.ReadU64("index record offset");
    const std::uint32_t record_bytes = body.ReadU32("index record byte count");
    const std::uint32_t index_reserved = body.ReadU32("index reserved field");
    const LocatorDigest256 locator = body.ReadDigest("index board locator");
    if (id != records[index].id || offset != record_offsets[index] ||
        record_bytes != kBoardRecordBytes || index_reserved != 0U ||
        locator != records[index].locator) {
      throw std::invalid_argument(
          "persistent board index does not exactly match its record");
    }
  }
  body.RequirePosition(footer_offset, "persistent board index");

  DecodedPersistentBoardSegment result;
  result.records = std::move(records);
  result.body_sha256 = body_sha256;
  result.segment_sha256 = Sha256Hex(bytes);
  return result;
}

} // namespace ugts_go19
