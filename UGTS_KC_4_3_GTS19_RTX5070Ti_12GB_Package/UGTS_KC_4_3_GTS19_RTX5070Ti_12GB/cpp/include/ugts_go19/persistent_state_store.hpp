#pragma once

#include "ugts_go19/persistent_state.hpp"

#include <cstdint>
#include <string>
#include <vector>

namespace ugts_go19 {

// Experimental, bounded codec limits. This stage materializes a complete
// board-only segment in memory; it is not a pager, checkpoint, or proof store.
struct PersistentStateStoreCodecLimits {
  std::uint64_t max_segment_bytes = 64U * 1024U * 1024U;
  std::uint64_t max_record_bytes = 4096U;
  std::uint64_t max_board_records = 250000U;
};

struct PersistentStateStoreCodecConfig {
  PersistentStateStoreCodecLimits limits;
  // Empty selects SHA-256 over the same canonical packed-board locator
  // material used by PersistentStateArena. An injected function is for
  // deterministic testing or a future index policy. Locator equality is never
  // accepted as board equality.
  LocatorFunction board_locator;
};

struct PersistentBoardRecordInput {
  // IDs are positive and strictly increasing within a segment. This codec is
  // framing, not interning: distinct IDs may intentionally carry exactly the
  // same board, and ID inequality never establishes board inequality.
  std::uint64_t id = 0;
  PackedBoard board;
};

struct DecodedPersistentBoardRecord {
  std::uint64_t id = 0;
  PackedBoard board;
  // This is a verified locator copied from the segment. ExactPackedBoardEqual
  // remains the identity comparison even when locators collide.
  LocatorDigest256 locator{};
};

struct DecodedPersistentBoardSegment {
  std::vector<DecodedPersistentBoardRecord> records;
  // SHA-256 of the bytes preceding the footer and of the complete segment.
  // These protect/select artifacts; neither digest establishes board identity.
  std::string body_sha256;
  std::string segment_sha256;
};

// Deterministic in-memory v1 codec for immutable packed-board records only.
// Both functions enforce the supplied resource limits. They deliberately do
// not serialize history roots, persistent states, proof values, paging state,
// publication metadata, or a solved result. Exact duplicate board payloads are
// preserved under distinct ordered IDs. A future interning/import layer must
// exact-compare payloads and either canonicalize or reject duplicates; locators
// and ID inequality are not identity evidence. The 19x19 root remains UNKNOWN.
[[nodiscard]] std::string EncodePersistentBoardSegmentV1(
    const std::vector<PersistentBoardRecordInput> &records,
    const PersistentStateStoreCodecConfig &config = {});

[[nodiscard]] DecodedPersistentBoardSegment DecodePersistentBoardSegmentV1(
    const std::string &bytes,
    const PersistentStateStoreCodecConfig &config = {});

} // namespace ugts_go19
