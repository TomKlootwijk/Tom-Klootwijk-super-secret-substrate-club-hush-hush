#include "ugts5_packed_node.hpp"

#include <cassert>
#include <cstdint>
#include <iostream>

int main() {
    using ugts5::PackedNode32;
    using ugts5::PackedNodeFields;

    const PackedNodeFields f{3, 0, -17, 201, 0xa5, 2, true};
    const std::uint32_t word = PackedNode32::pack(f);
    assert(PackedNode32::verify(word));
    const auto decoded = PackedNode32::unpack(word);
    assert(decoded.family == f.family);
    assert(decoded.kappa == f.kappa);
    assert(decoded.delta_rho == f.delta_rho);
    assert(decoded.delta_theta == f.delta_theta);
    assert(decoded.grammar_path == f.grammar_path);
    assert(decoded.local_flags == f.local_flags);
    assert(decoded.active == f.active);

    const auto flipped = PackedNode32::klein_flip(word);
    const auto f2 = PackedNode32::unpack(flipped);
    assert(f2.family == f.family);
    assert(f2.kappa == 1);
    assert(f2.delta_theta == static_cast<std::uint8_t>(0u - f.delta_theta));
    assert(PackedNode32::klein_flip(flipped) == word);

    assert(!PackedNode32::verify(word ^ (1u << 12u)));
    std::cout << "UGTS5 native PackedNode32: PASS\n";
    std::cout << "word=0x" << std::hex << word << " flipped=0x" << flipped << "\n";
    return 0;
}
