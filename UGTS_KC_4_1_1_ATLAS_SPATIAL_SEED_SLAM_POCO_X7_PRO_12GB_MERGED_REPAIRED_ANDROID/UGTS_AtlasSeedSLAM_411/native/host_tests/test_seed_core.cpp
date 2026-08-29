#include <cstdlib>
#include <iostream>
#include <string>
#include "seed_core.h"

namespace {
int checks = 0;
void require(bool condition, const std::string& message) {
    ++checks;
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        std::exit(1);
    }
}
}

int main() {
    require(ugts_seed::self_test(), "native self-test");
    const std::uint8_t text[] = {'1','2','3','4','5','6','7','8','9'};
    require(ugts_seed::crc32(text, sizeof(text)) == 0xcbf43926u, "CRC32 fixture");
    const auto first = ugts_seed::schedule_value(7, 9, 11, 13);
    require(first == ugts_seed::schedule_value(7, 9, 11, 13), "schedule deterministic");
    require(first != ugts_seed::schedule_value(7, 9, 11, 14), "schedule changes by index");
    for (std::uint64_t index = 0; index < 10000; ++index) {
        require(ugts_seed::schedule_bounded(7, 9, 11, index, 257) < 257, "bounded schedule");
    }
    std::cout << "Native seed host tests: PASS (" << checks << " checks)\n";
    return 0;
}
