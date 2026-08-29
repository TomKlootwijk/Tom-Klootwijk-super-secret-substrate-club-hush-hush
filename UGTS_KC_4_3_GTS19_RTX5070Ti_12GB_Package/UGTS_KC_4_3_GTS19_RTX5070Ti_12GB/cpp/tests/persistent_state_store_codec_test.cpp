#include "ugts_go19/persistent_state_store.hpp"
#include "ugts_go19/sha256.hpp"

#include <array>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace {

using ugts_go19::DecodedPersistentBoardSegment;
using ugts_go19::DecodePersistentBoardSegmentV1;
using ugts_go19::EncodePersistentBoardSegmentV1;
using ugts_go19::ExactPackedBoardEqual;
using ugts_go19::kBlack;
using ugts_go19::kEmpty;
using ugts_go19::kWhite;
using ugts_go19::LocatorDigest256;
using ugts_go19::PackBoardExact;
using ugts_go19::PackedBoard;
using ugts_go19::PersistentArenaConfig;
using ugts_go19::PersistentBoardRecordInput;
using ugts_go19::PersistentStateArena;
using ugts_go19::PersistentStateStoreCodecConfig;
using ugts_go19::Sha256Hex;

constexpr std::string_view kSegmentMagic =
    "UGTS-CPP-PERSISTENT-BOARD-SEGMENT-v1";
constexpr std::string_view kFooterMagic = "UGTS-CPP-PERSISTENT-BOARD-FOOTER-v1";
constexpr std::size_t kBoardRecordBytes = 152U;
constexpr std::size_t kBoardIndexEntryBytes = 56U;

void Require(bool condition, const std::string &message) {
  if (!condition)
    throw std::runtime_error(message);
}

template <typename Exception, typename Function>
void RequireThrows(Function &&function, std::string_view expected,
                   const std::string &message) {
  try {
    function();
  } catch (const Exception &error) {
    if (std::string_view(error.what()).find(expected) ==
        std::string_view::npos) {
      throw std::runtime_error(message + ": wrong message: " + error.what());
    }
    return;
  }
  throw std::runtime_error(message + ": no exception");
}

std::uint64_t ReadU64(const std::string &bytes, std::size_t offset) {
  if (offset > bytes.size() || bytes.size() - offset < 8U) {
    throw std::runtime_error("test attempted an out-of-range u64 read");
  }
  std::uint64_t value = 0U;
  for (unsigned int shift = 0; shift < 64U; shift += 8U) {
    value |=
        static_cast<std::uint64_t>(static_cast<unsigned char>(bytes[offset++]))
        << shift;
  }
  return value;
}

void WriteU32(std::string &bytes, std::size_t offset, std::uint32_t value) {
  if (offset > bytes.size() || bytes.size() - offset < 4U) {
    throw std::runtime_error("test attempted an out-of-range u32 write");
  }
  for (unsigned int shift = 0; shift < 32U; shift += 8U) {
    bytes[offset++] = static_cast<char>((value >> shift) & 0xffU);
  }
}

void WriteU64(std::string &bytes, std::size_t offset, std::uint64_t value) {
  if (offset > bytes.size() || bytes.size() - offset < 8U) {
    throw std::runtime_error("test attempted an out-of-range u64 write");
  }
  for (unsigned int shift = 0; shift < 64U; shift += 8U) {
    bytes[offset++] = static_cast<char>((value >> shift) & 0xffU);
  }
}

std::uint8_t HexNibble(char value) {
  if (value >= '0' && value <= '9') {
    return static_cast<std::uint8_t>(value - '0');
  }
  if (value >= 'a' && value <= 'f') {
    return static_cast<std::uint8_t>(value - 'a' + 10);
  }
  throw std::runtime_error("test received invalid SHA-256 hex");
}

std::string DigestHex(const LocatorDigest256 &digest) {
  constexpr char kHex[] = "0123456789abcdef";
  std::string result;
  result.reserve(digest.size() * 2U);
  for (std::uint8_t byte : digest) {
    result.push_back(kHex[static_cast<std::size_t>(byte >> 4U)]);
    result.push_back(kHex[static_cast<std::size_t>(byte & 0x0fU)]);
  }
  return result;
}

std::size_t HeaderFieldOffset(std::size_t after_prefix) {
  return kSegmentMagic.size() + 1U + after_prefix;
}

std::size_t RecordsOffset(const std::string &bytes) {
  return static_cast<std::size_t>(ReadU64(bytes, HeaderFieldOffset(24U)));
}

std::size_t IndexOffset(const std::string &bytes) {
  return static_cast<std::size_t>(ReadU64(bytes, HeaderFieldOffset(40U)));
}

std::size_t FooterOffset(const std::string &bytes) {
  return static_cast<std::size_t>(ReadU64(bytes, HeaderFieldOffset(56U)));
}

void RefreshBodyDigestAt(std::string &bytes, std::size_t footer) {
  const std::size_t digest_offset =
      footer + kFooterMagic.size() + 1U + 1U + 1U + 2U + 8U * 3U;
  if (footer > bytes.size() || digest_offset > bytes.size() ||
      bytes.size() - digest_offset < 32U) {
    throw std::runtime_error("test cannot refresh malformed footer location");
  }
  const std::string hex = Sha256Hex(std::string_view(bytes.data(), footer));
  for (std::size_t index = 0; index < 32U; ++index) {
    bytes[digest_offset + index] = static_cast<char>(
        (HexNibble(hex[index * 2U]) << 4U) | HexNibble(hex[index * 2U + 1U]));
  }
}

void RefreshBodyDigest(std::string &bytes) {
  RefreshBodyDigestAt(bytes, FooterOffset(bytes));
}

PackedBoard PatternBoard(int size) {
  const std::size_t points =
      static_cast<std::size_t>(size) * static_cast<std::size_t>(size);
  std::vector<std::uint8_t> cells(points, kEmpty);
  cells[(static_cast<std::size_t>(size) * 7U + 1U) % points] = kBlack;
  if (points > 1U) {
    std::size_t white = (static_cast<std::size_t>(size) * 11U + 3U) % points;
    if (cells[white] != kEmpty)
      white = (white + 1U) % points;
    cells[white] = kWhite;
  }
  return PackBoardExact(size, cells);
}

std::vector<PersistentBoardRecordInput> AllSizeRecords() {
  std::vector<PersistentBoardRecordInput> result;
  for (int size = 1; size <= 19; ++size) {
    result.push_back(
        {static_cast<std::uint64_t>(size * 3), PatternBoard(size)});
  }
  return result;
}

void RequireRoundTripEquals(
    const std::vector<PersistentBoardRecordInput> &expected,
    const DecodedPersistentBoardSegment &actual, const std::string &label) {
  Require(actual.records.size() == expected.size(),
          label + " record count changed");
  for (std::size_t index = 0; index < expected.size(); ++index) {
    Require(actual.records[index].id == expected[index].id,
            label + " record ID changed");
    Require(ExactPackedBoardEqual(actual.records[index].board,
                                  expected[index].board),
            label + " packed board changed");
  }
}

void TestDeterministicRoundTripAllSizes() {
  const auto records = AllSizeRecords();
  const std::string first = EncodePersistentBoardSegmentV1(records);
  const std::string second = EncodePersistentBoardSegmentV1(records);
  Require(first == second,
          "same board segment did not encode deterministically");
  const auto decoded = DecodePersistentBoardSegmentV1(first);
  RequireRoundTripEquals(records, decoded, "all-size round trip");
  Require(decoded.segment_sha256 == Sha256Hex(first),
          "decoded complete-segment digest changed");
  Require(!decoded.body_sha256.empty() && decoded.body_sha256.size() == 64U,
          "decoded body digest was not canonical SHA-256 hex");

  std::vector<PersistentBoardRecordInput> normalized;
  for (const auto &record : decoded.records) {
    normalized.push_back({record.id, record.board});
  }
  Require(EncodePersistentBoardSegmentV1(normalized) == first,
          "decode/re-encode changed canonical segment bytes");
}

void TestIndependentEmptyOneByOneGoldenVector() {
  const std::vector<PersistentBoardRecordInput> records = {
      {1U, PackBoardExact(1, {kEmpty})}};
  const std::string encoded = EncodePersistentBoardSegmentV1(records);
  const auto decoded = DecodePersistentBoardSegmentV1(encoded);

  Require(encoded.size() == 413U,
          "empty 1x1 golden segment byte count changed");
  RequireRoundTripEquals(records, decoded, "empty 1x1 golden round trip");
  Require(
      DigestHex(decoded.records.front().locator) ==
          "c85abc8f9a22bd143d8d8648540b42dfc9d6a9b02595b6d35f51e56cf2546da6",
      "empty 1x1 golden locator changed");
  Require(
      decoded.body_sha256 ==
          "13f77f4dead3f9703f8f8da467f6bf8cccf0407d62cdabfb7afb030bfc45c7ca",
      "empty 1x1 golden body SHA-256 changed");
  Require(
      decoded.segment_sha256 ==
          "4a4c6f3d4c469adcf78265d68f17b2717531054bf3c1120dfd60b40d125fe1b3",
      "empty 1x1 golden segment SHA-256 changed");
}

void TestIndependentMultiwordColorGoldenVector() {
  PackedBoard board;
  board.size = 9U;
  board.black = {1U, 64U, 0U, 0U, 0U, 0U};
  board.white = {2U, 2U, 0U, 0U, 0U, 0U};
  const std::vector<PersistentBoardRecordInput> records = {{7U, board}};
  const std::string encoded = EncodePersistentBoardSegmentV1(records);
  const auto decoded = DecodePersistentBoardSegmentV1(encoded);

  Require(encoded.size() == 413U,
          "multiword 9x9 golden segment byte count changed");
  RequireRoundTripEquals(records, decoded, "multiword 9x9 golden round trip");
  Require(
      DigestHex(decoded.records.front().locator) ==
          "802ef7acaaeab03894164efc2fb349489f67945be7451a2b47e0fbe0d6f67aaf",
      "multiword 9x9 golden locator changed");
  Require(
      decoded.body_sha256 ==
          "d266cba44a8d6e61b9a29f5d68dabd798556b3a7967066ad6100143861920a31",
      "multiword 9x9 golden body SHA-256 changed");
  Require(
      decoded.segment_sha256 ==
          "774737c843d0a372a3f7e94dfd3d6ceac02e1a7d6994aee5179ea9eb6842e929",
      "multiword 9x9 golden segment SHA-256 changed");
}

void TestDuplicateExactPayloadsKeepDistinctIds() {
  const PackedBoard duplicate = PatternBoard(11);
  const std::vector<PersistentBoardRecordInput> records = {{7U, duplicate},
                                                           {19U, duplicate}};
  const std::string encoded = EncodePersistentBoardSegmentV1(records);
  const auto decoded = DecodePersistentBoardSegmentV1(encoded);
  RequireRoundTripEquals(records, decoded, "duplicate-payload round trip");
  Require(decoded.records[0].id != decoded.records[1].id,
          "duplicate exact payload IDs were conflated");
  Require(
      ExactPackedBoardEqual(decoded.records[0].board, decoded.records[1].board),
      "duplicate exact payloads did not remain equal");
  Require(decoded.records[0].locator == decoded.records[1].locator,
          "identical payloads received different default locators");
}

void TestArenaAndCodecUseIdenticalBoardLocatorMaterial() {
  const PackedBoard board = PatternBoard(19);
  std::string arena_material;
  PersistentArenaConfig arena_config;
  arena_config.board_locator = [&](std::string_view material) {
    arena_material.assign(material.data(), material.size());
    return LocatorDigest256{};
  };
  PersistentStateArena arena(std::move(arena_config));
  static_cast<void>(arena.InternBoard(board));

  std::string codec_material;
  PersistentStateStoreCodecConfig codec_config;
  codec_config.board_locator = [&](std::string_view material) {
    codec_material.assign(material.data(), material.size());
    return LocatorDigest256{};
  };
  static_cast<void>(
      EncodePersistentBoardSegmentV1({{1U, board}}, codec_config));
  Require(arena_material == codec_material,
          "arena and board codec locator material diverged");
}

void TestInjectedLocatorCollisionsStayExact() {
  PersistentStateStoreCodecConfig collision_config;
  collision_config.board_locator = [](std::string_view) {
    LocatorDigest256 digest{};
    digest.fill(0x5aU);
    return digest;
  };
  const std::vector<PersistentBoardRecordInput> records = {
      {1U, PatternBoard(3)}, {2U, PatternBoard(4)}, {9U, PatternBoard(19)}};
  const std::string encoded =
      EncodePersistentBoardSegmentV1(records, collision_config);
  const auto decoded =
      DecodePersistentBoardSegmentV1(encoded, collision_config);
  RequireRoundTripEquals(records, decoded, "locator-collision round trip");
  Require(decoded.records[0].locator == decoded.records[1].locator &&
              decoded.records[1].locator == decoded.records[2].locator,
          "injected complete locator collision was not present");
  Require(!ExactPackedBoardEqual(decoded.records[0].board,
                                 decoded.records[1].board) &&
              !ExactPackedBoardEqual(decoded.records[1].board,
                                     decoded.records[2].board),
          "unequal boards were conflated under an injected locator collision");
  RequireThrows<std::invalid_argument>(
      [&] { static_cast<void>(DecodePersistentBoardSegmentV1(encoded)); },
      "locator mismatch",
      "segment decoded under a locator policy different from its encoding");
}

void TestEncodeValidationAndLimits() {
  const PackedBoard board = PatternBoard(3);
  RequireThrows<std::invalid_argument>(
      [&] { static_cast<void>(EncodePersistentBoardSegmentV1({})); },
      "at least one", "empty board segment was accepted");
  RequireThrows<std::invalid_argument>(
      [&] {
        static_cast<void>(EncodePersistentBoardSegmentV1(
            {{1U, board}, {1U, PatternBoard(4)}}));
      },
      "strictly increasing", "duplicate board IDs were accepted by encoder");
  RequireThrows<std::invalid_argument>(
      [&] {
        static_cast<void>(EncodePersistentBoardSegmentV1(
            {{2U, board}, {1U, PatternBoard(4)}}));
      },
      "strictly increasing", "out-of-order board IDs were accepted by encoder");

  PackedBoard overlap = board;
  overlap.black[0] |= 1U;
  overlap.white[0] |= 1U;
  RequireThrows<std::invalid_argument>(
      [&] {
        static_cast<void>(EncodePersistentBoardSegmentV1({{1U, overlap}}));
      },
      "overlap", "overlapping bitplanes were accepted by encoder");
  PackedBoard bad_tail = PackBoardExact(1, {kEmpty});
  bad_tail.black[0] = 2U;
  RequireThrows<std::invalid_argument>(
      [&] {
        static_cast<void>(EncodePersistentBoardSegmentV1({{1U, bad_tail}}));
      },
      "tail", "nonzero unused tail bit was accepted by encoder");

  const auto records = AllSizeRecords();
  const std::string encoded = EncodePersistentBoardSegmentV1(records);
  PersistentStateStoreCodecConfig count_limit;
  count_limit.limits.max_board_records = records.size() - 1U;
  RequireThrows<std::length_error>(
      [&] {
        static_cast<void>(EncodePersistentBoardSegmentV1(records, count_limit));
      },
      "count", "encoder record-count cap was ignored");
  PersistentStateStoreCodecConfig record_limit;
  record_limit.limits.max_record_bytes = kBoardRecordBytes - 1U;
  RequireThrows<std::length_error>(
      [&] {
        static_cast<void>(
            EncodePersistentBoardSegmentV1(records, record_limit));
      },
      "record width", "encoder record-byte cap was ignored");
  PersistentStateStoreCodecConfig segment_limit;
  segment_limit.limits.max_segment_bytes = encoded.size() - 1U;
  RequireThrows<std::length_error>(
      [&] {
        static_cast<void>(
            EncodePersistentBoardSegmentV1(records, segment_limit));
      },
      "byte limit", "encoder segment-byte cap was ignored");
}

void TestDecodeEnvelopeDigestAndResourceRejection() {
  const auto records = AllSizeRecords();
  const std::string valid = EncodePersistentBoardSegmentV1(records);
  const std::size_t footer_offset = FooterOffset(valid);

  auto require_resigned_body_byte_rejection = [&](std::size_t offset,
                                                  std::string_view expected,
                                                  const std::string &message) {
    std::string malformed = valid;
    malformed[offset] =
        static_cast<char>(static_cast<unsigned char>(malformed[offset]) ^ 1U);
    RefreshBodyDigestAt(malformed, footer_offset);
    RequireThrows<std::invalid_argument>(
        [&] { static_cast<void>(DecodePersistentBoardSegmentV1(malformed)); },
        expected, message);
  };
  require_resigned_body_byte_rejection(0U, "magic",
                                       "incorrect segment magic was accepted");
  require_resigned_body_byte_rejection(
      HeaderFieldOffset(0U), "header",
      "unsupported segment endianness was accepted");
  require_resigned_body_byte_rejection(HeaderFieldOffset(1U), "header",
                                       "unsupported segment kind was accepted");
  require_resigned_body_byte_rejection(HeaderFieldOffset(2U), "header",
                                       "nonzero segment flags were accepted");

  for (std::size_t field_offset : {8U, 16U, 24U, 32U, 40U, 48U, 56U, 64U}) {
    require_resigned_body_byte_rejection(
        HeaderFieldOffset(field_offset), "layout",
        "noncanonical header layout field was accepted at offset " +
            std::to_string(field_offset));
  }

  const std::size_t footer_tags = footer_offset + kFooterMagic.size() + 1U;
  auto require_footer_byte_rejection = [&](std::size_t offset,
                                           std::string_view expected,
                                           const std::string &message) {
    std::string malformed = valid;
    malformed[offset] =
        static_cast<char>(static_cast<unsigned char>(malformed[offset]) ^ 1U);
    RequireThrows<std::invalid_argument>(
        [&] { static_cast<void>(DecodePersistentBoardSegmentV1(malformed)); },
        expected, message);
  };
  require_footer_byte_rejection(footer_offset, "footer magic",
                                "incorrect footer magic was accepted");
  require_footer_byte_rejection(footer_tags, "footer",
                                "unsupported footer endianness was accepted");
  require_footer_byte_rejection(footer_tags + 1U, "footer",
                                "nonzero footer flags were accepted");

  auto require_footer_count_rejection = [&](std::size_t relative_offset,
                                            std::uint64_t value,
                                            const std::string &message) {
    std::string malformed = valid;
    WriteU64(malformed, footer_tags + 4U + relative_offset, value);
    RequireThrows<std::invalid_argument>(
        [&] { static_cast<void>(DecodePersistentBoardSegmentV1(malformed)); },
        "footer", message);
  };
  require_footer_count_rejection(0U, 95U,
                                 "noncanonical footer width was accepted");
  require_footer_count_rejection(
      8U, static_cast<std::uint64_t>(footer_offset + 1U),
      "incorrect footer body-byte count was accepted");
  require_footer_count_rejection(
      16U, static_cast<std::uint64_t>(valid.size() + 1U),
      "incorrect footer segment-byte count was accepted");

  RequireThrows<std::invalid_argument>(
      [&] {
        static_cast<void>(DecodePersistentBoardSegmentV1(
            valid.substr(0U, valid.size() - 1U)));
      },
      "persistent board segment", "truncated board segment was accepted");
  RequireThrows<std::invalid_argument>(
      [&] { static_cast<void>(DecodePersistentBoardSegmentV1(valid + "x")); },
      "layout", "board segment with trailing bytes was accepted");

  std::string digest_corruption = valid;
  digest_corruption[RecordsOffset(valid) + 24U] ^= 1;
  RequireThrows<std::invalid_argument>(
      [&] {
        static_cast<void>(DecodePersistentBoardSegmentV1(digest_corruption));
      },
      "SHA-256", "body corruption passed the segment digest");

  std::string reserved_header = valid;
  reserved_header[HeaderFieldOffset(4U)] = 1;
  RefreshBodyDigest(reserved_header);
  RequireThrows<std::invalid_argument>(
      [&] {
        static_cast<void>(DecodePersistentBoardSegmentV1(reserved_header));
      },
      "reserved", "nonzero header reserved field was accepted");

  std::string reserved_footer = valid;
  reserved_footer[FooterOffset(valid) + kFooterMagic.size() + 1U + 2U] = 1;
  RequireThrows<std::invalid_argument>(
      [&] {
        static_cast<void>(DecodePersistentBoardSegmentV1(reserved_footer));
      },
      "footer", "nonzero footer reserved field was accepted");

  std::string overflowing_offset = valid;
  WriteU64(overflowing_offset, HeaderFieldOffset(24U),
           std::numeric_limits<std::uint64_t>::max());
  RefreshBodyDigest(overflowing_offset);
  RequireThrows<std::invalid_argument>(
      [&] {
        static_cast<void>(DecodePersistentBoardSegmentV1(overflowing_offset));
      },
      "overflow", "overflowing records offset was accepted");

  PersistentStateStoreCodecConfig count_limit;
  count_limit.limits.max_board_records = records.size() - 1U;
  RequireThrows<std::length_error>(
      [&] {
        static_cast<void>(DecodePersistentBoardSegmentV1(valid, count_limit));
      },
      "count", "decoder record-count cap was ignored");
  PersistentStateStoreCodecConfig record_limit;
  record_limit.limits.max_record_bytes = kBoardRecordBytes - 1U;
  RequireThrows<std::length_error>(
      [&] {
        static_cast<void>(DecodePersistentBoardSegmentV1(valid, record_limit));
      },
      "record width", "decoder record-byte cap was ignored");
  PersistentStateStoreCodecConfig segment_limit;
  segment_limit.limits.max_segment_bytes = valid.size() - 1U;
  RequireThrows<std::length_error>(
      [&] {
        static_cast<void>(DecodePersistentBoardSegmentV1(valid, segment_limit));
      },
      "byte limit", "decoder segment-byte cap was ignored");

  std::string declared_huge_count = valid;
  WriteU64(declared_huge_count, HeaderFieldOffset(16U),
           std::numeric_limits<std::uint64_t>::max());
  RefreshBodyDigest(declared_huge_count);
  RequireThrows<std::length_error>(
      [&] {
        static_cast<void>(DecodePersistentBoardSegmentV1(declared_huge_count));
      },
      "count", "oversized declared record count reached allocation");

  PersistentStateStoreCodecConfig arithmetic_limits;
  arithmetic_limits.limits.max_segment_bytes =
      std::numeric_limits<std::uint64_t>::max();
  arithmetic_limits.limits.max_board_records =
      std::numeric_limits<std::uint64_t>::max();
  if constexpr (sizeof(std::size_t) < sizeof(std::uint64_t)) {
    RequireThrows<std::length_error>(
        [&] {
          static_cast<void>(DecodePersistentBoardSegmentV1(declared_huge_count,
                                                           arithmetic_limits));
        },
        "size_t", "declared record count bypassed the 32-bit size_t guard");
  } else {
    RequireThrows<std::invalid_argument>(
        [&] {
          static_cast<void>(DecodePersistentBoardSegmentV1(declared_huge_count,
                                                           arithmetic_limits));
        },
        "arithmetic overflow", "declared record bytes overflow was accepted");
  }
}

void TestDecodeRecordAndIndexSemanticRejection() {
  const std::vector<PersistentBoardRecordInput> records = {
      {1U, PackBoardExact(1, {kEmpty})},
      {2U, PatternBoard(8)},
      {3U, PatternBoard(19)},
  };
  const std::string valid = EncodePersistentBoardSegmentV1(records);
  const std::size_t records_offset = RecordsOffset(valid);
  const std::size_t index_offset = IndexOffset(valid);

  auto require_refreshed_rejection = [&](std::string malformed,
                                         std::string_view expected,
                                         const std::string &message) {
    RefreshBodyDigest(malformed);
    RequireThrows<std::invalid_argument>(
        [&] { static_cast<void>(DecodePersistentBoardSegmentV1(malformed)); },
        expected, message);
  };

  std::string bad_size = valid;
  bad_size[records_offset + 16U] = 0;
  require_refreshed_rejection(std::move(bad_size), "board size",
                              "zero board size was accepted by decoder");

  std::string oversized_board = valid;
  oversized_board[records_offset + 16U] = 20;
  require_refreshed_rejection(std::move(oversized_board), "board size",
                              "oversized board was accepted by decoder");

  std::string overlap = valid;
  overlap[records_offset + 24U] = 1;
  overlap[records_offset + 72U] = 1;
  require_refreshed_rejection(std::move(overlap), "overlap",
                              "overlapping decoded bitplanes were accepted");

  std::string tail = valid;
  tail[records_offset + 24U] = 2;
  require_refreshed_rejection(std::move(tail), "tail",
                              "nonzero decoded tail bit was accepted");

  std::string unused_word = valid;
  unused_word[records_offset + 32U] = 1;
  require_refreshed_rejection(std::move(unused_word), "unused words",
                              "nonzero decoded unused word was accepted");

  std::string record_reserved = valid;
  record_reserved[records_offset + 6U] = 1;
  require_refreshed_rejection(std::move(record_reserved), "record fields",
                              "nonzero record reserved field was accepted");

  std::string board_reserved = valid;
  board_reserved[records_offset + 17U] = 1;
  require_refreshed_rejection(std::move(board_reserved), "record fields",
                              "nonzero board reserved field was accepted");

  std::string bad_record_width = valid;
  WriteU32(bad_record_width, records_offset, 151U);
  require_refreshed_rejection(std::move(bad_record_width), "record fields",
                              "noncanonical record width was accepted");

  std::string bad_record_version = valid;
  bad_record_version[records_offset + 4U] ^= 1;
  require_refreshed_rejection(std::move(bad_record_version), "record fields",
                              "unsupported record version was accepted");

  std::string bad_record_kind = valid;
  bad_record_kind[records_offset + 5U] ^= 1;
  require_refreshed_rejection(std::move(bad_record_kind), "record fields",
                              "unsupported record kind was accepted");

  std::string zero_record_id = valid;
  WriteU64(zero_record_id, records_offset + 8U, 0U);
  require_refreshed_rejection(std::move(zero_record_id), "duplicate",
                              "zero decoded record ID was accepted");

  std::string duplicate_ids = valid;
  WriteU64(duplicate_ids, records_offset + kBoardRecordBytes + 8U, 1U);
  require_refreshed_rejection(std::move(duplicate_ids), "duplicate",
                              "duplicate decoded IDs were accepted");

  std::string out_of_order_ids = valid;
  WriteU64(out_of_order_ids, records_offset + 8U, 5U);
  require_refreshed_rejection(std::move(out_of_order_ids), "out of order",
                              "out-of-order decoded IDs were accepted");

  std::string recomputed_corruption = valid;
  recomputed_corruption[records_offset + 24U] = 1;
  require_refreshed_rejection(
      std::move(recomputed_corruption), "locator mismatch",
      "rehashed board corruption bypassed locator check");

  std::string index_offset_corruption = valid;
  WriteU64(index_offset_corruption, index_offset + 8U,
           static_cast<std::uint64_t>(records_offset + 1U));
  require_refreshed_rejection(std::move(index_offset_corruption), "index",
                              "incorrect index record offset was accepted");

  std::string index_reserved = valid;
  index_reserved[index_offset + 20U] = 1;
  require_refreshed_rejection(std::move(index_reserved), "index",
                              "nonzero index reserved field was accepted");

  std::string index_record_id = valid;
  WriteU64(index_record_id, index_offset, 0U);
  require_refreshed_rejection(std::move(index_record_id), "index",
                              "incorrect index record ID was accepted");

  std::string index_record_width = valid;
  WriteU32(index_record_width, index_offset + 16U, 151U);
  require_refreshed_rejection(std::move(index_record_width), "index",
                              "incorrect index record width was accepted");

  std::string index_locator = valid;
  index_locator[index_offset + 24U] ^= 1;
  require_refreshed_rejection(std::move(index_locator), "index",
                              "index locator mismatch was accepted");

  // Keep these constants tied to the documented fixed-width layout.
  Require(IndexOffset(valid) ==
                  records_offset + records.size() * kBoardRecordBytes &&
              FooterOffset(valid) ==
                  index_offset + records.size() * kBoardIndexEntryBytes,
          "test fixture disagrees with documented section widths");
}

} // namespace

int main() {
  try {
    TestDeterministicRoundTripAllSizes();
    TestIndependentEmptyOneByOneGoldenVector();
    TestIndependentMultiwordColorGoldenVector();
    TestDuplicateExactPayloadsKeepDistinctIds();
    TestArenaAndCodecUseIdenticalBoardLocatorMaterial();
    TestInjectedLocatorCollisionsStayExact();
    TestEncodeValidationAndLimits();
    TestDecodeEnvelopeDigestAndResourceRejection();
    TestDecodeRecordAndIndexSemanticRejection();
    std::cout << "ugts_go_persistent_state_store_codec_tests: ok; "
                 "board-only bounded experimental codec; 19x19 root UNKNOWN\n";
    return 0;
  } catch (const std::exception &error) {
    std::cerr << "ugts_go_persistent_state_store_codec_tests: " << error.what()
              << '\n';
    return 1;
  }
}
