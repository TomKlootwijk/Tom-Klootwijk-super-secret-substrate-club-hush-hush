#include "ugts_chess2/core.hpp"
#include "ugts_chess2/retrograde.hpp"
#include "ugts_chess2/search.hpp"
#include "ugts_chess2/sha256.hpp"

#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>

using namespace ugts::chess2;

namespace {
int failures = 0;
void check(bool condition, const std::string& label) {
    if (!condition) {
        ++failures;
        std::cerr << "FAIL: " << label << '\n';
    }
}
}

int main() {
    check(sha256_hex("") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", "SHA-256 empty vector");
    check(sha256_hex("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", "SHA-256 abc vector");

    const Position initial = Position::initial();
    check(initial.to_fen() == "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", "FEN roundtrip");
    const std::vector<std::uint64_t> expected = {1, 20, 400, 8902, 197281};
    for (int depth = 0; depth <= 4; ++depth) check(perft(initial, depth) == expected[static_cast<std::size_t>(depth)], "initial perft depth " + std::to_string(depth));

    const Position kiwipete = Position::from_fen("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1");
    check(perft(kiwipete, 1) == 48, "kiwipete depth 1");
    check(perft(kiwipete, 2) == 2039, "kiwipete depth 2");
    check(perft(kiwipete, 3) == 97862, "kiwipete depth 3");

    const std::vector<std::pair<std::string, std::vector<std::uint64_t>>> extra_perft = {
        {"8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", {14, 191, 2812}},
        {"r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1", {6, 264, 9467}},
        {"rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8", {44, 1486, 62379}},
        {"r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10", {46, 2079, 89890}},
    };
    for (std::size_t i = 0; i < extra_perft.size(); ++i) {
        const Position fixture = Position::from_fen(extra_perft[i].first);
        for (int depth = 1; depth <= 3; ++depth) {
            check(perft(fixture, depth) == extra_perft[i].second[static_cast<std::size_t>(depth - 1)],
                  "extra perft fixture " + std::to_string(i + 3) + " depth " + std::to_string(depth));
        }
    }

    const Position mate = Position::from_fen("8/8/8/8/8/k7/8/1QK5 w - - 0 1");
    const auto proof = prove_forced_mate(mate, 3, 500000);
    check(proof.proved, "mate in two proof");

    const auto retro = solve_retrograde_cpu(make_demo_graph());
    const std::vector<Wdl> expected_wdl = {Wdl::Loss, Wdl::Win, Wdl::Win, Wdl::Loss, Wdl::Draw, Wdl::Loss, Wdl::Win};
    check(retro.outcomes == expected_wdl, "retrograde fixed point");

    const Position kings = Position::from_fen("8/8/8/8/8/8/4k3/K7 w - - 0 1");
    check(insufficient_material(kings), "king versus king dead position");

    if (failures) {
        std::cerr << failures << " test(s) failed\n";
        return EXIT_FAILURE;
    }
    std::cout << "native tests passed\n";
    return EXIT_SUCCESS;
}
