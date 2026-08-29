#pragma once

#include <string>
#include <string_view>

namespace ugts_go19 {

// Portable one-shot SHA-256. The lowercase hexadecimal result is used only as
// a content address/evidence value; collision-independent state equality
// remains authoritative.
[[nodiscard]] std::string Sha256Hex(std::string_view data);

}  // namespace ugts_go19
