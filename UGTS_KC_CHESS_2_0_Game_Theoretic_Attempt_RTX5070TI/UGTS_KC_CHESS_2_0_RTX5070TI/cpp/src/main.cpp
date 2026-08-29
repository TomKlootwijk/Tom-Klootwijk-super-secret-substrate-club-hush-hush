#include "ugts_chess2/core.hpp"
#include "ugts_chess2/retrograde.hpp"
#include "ugts_chess2/search.hpp"

#include <chrono>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

#ifndef UGTS_CHESS2_VERSION
#define UGTS_CHESS2_VERSION "2.0.0"
#endif

namespace {
using namespace ugts::chess2;

std::string json_escape(std::string_view value) {
    std::ostringstream out;
    for (unsigned char c : value) {
        switch (c) {
            case '"': out << "\\\""; break;
            case '\\': out << "\\\\"; break;
            case '\b': out << "\\b"; break;
            case '\f': out << "\\f"; break;
            case '\n': out << "\\n"; break;
            case '\r': out << "\\r"; break;
            case '\t': out << "\\t"; break;
            default:
                if (c < 0x20) out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << static_cast<int>(c);
                else out << static_cast<char>(c);
        }
    }
    return out.str();
}

std::string arg_value(const std::vector<std::string>& args, std::string_view name, std::string fallback = {}) {
    for (std::size_t i = 0; i + 1 < args.size(); ++i) if (args[i] == name) return args[i + 1];
    return fallback;
}

bool has_flag(const std::vector<std::string>& args, std::string_view name) {
    for (const auto& arg : args) if (arg == name) return true;
    return false;
}

int as_int(const std::string& text, const char* label) {
    try { return std::stoi(text); }
    catch (...) { throw std::invalid_argument(std::string(label) + " must be an integer"); }
}

std::uint64_t as_u64(const std::string& text, const char* label) {
    try { return std::stoull(text); }
    catch (...) { throw std::invalid_argument(std::string(label) + " must be an unsigned integer"); }
}

Position load_position(const std::vector<std::string>& args) {
    const std::string fen = arg_value(args, "--fen", "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1");
    return Position::from_fen(fen);
}

void print_usage() {
    std::cout << "UGTS Chess 2.0 native foundation\n"
              << "commands:\n"
              << "  info\n"
              << "  validate [--fen FEN]\n"
              << "  perft --depth N [--fen FEN] [--divide]\n"
              << "  search --depth N [--nodes N] [--fen FEN]\n"
              << "  prove-mate --plies N [--nodes N] --fen FEN\n"
              << "  retro-demo [--cpu]\n"
              << "  root-shards [--fen FEN]\n"
              << "  selftest\n";
}

int cmd_info() {
    std::cout << "{\n"
              << "  \"name\": \"UGTS Chess Game-Theoretic Foundation\",\n"
              << "  \"version\": \"" << UGTS_CHESS2_VERSION << "\",\n"
              << "  \"canonical_identity\": \"ugts.application.chess.game-theoretic-solver@2.0.0\",\n"
              << "  \"cuda_backend_compiled\": " << (cuda_backend_compiled() ? "true" : "false") << ",\n"
              << "  \"cuda_device\": \"" << json_escape(cuda_device_summary()) << "\",\n"
              << "  \"target_profile\": \"GeForce RTX 5070 Ti Laptop GPU, 12 GB GDDR7, SM120 when detected\",\n"
              << "  \"proof_boundary\": \"GPU hashes and heuristic scores are caches or ordering aids; only independently checked exact records may certify WDL.\",\n"
              << "  \"initial_position_status\": \"unresolved\"\n"
              << "}\n";
    return 0;
}

int cmd_validate(const std::vector<std::string>& args) {
    const Position p = load_position(args);
    const auto moves = legal_moves(p);
    const auto status = position_status(p);
    std::cout << "{\n"
              << "  \"valid\": true,\n"
              << "  \"fen\": \"" << json_escape(p.to_fen()) << "\",\n"
              << "  \"state_sha256\": \"" << state_sha256(p) << "\",\n"
              << "  \"repetition_sha256\": \"" << repetition_key(p) << "\",\n"
              << "  \"legal_move_count\": " << moves.size() << ",\n"
              << "  \"terminal\": " << (status.terminal ? "true" : "false") << ",\n"
              << "  \"status\": \"" << json_escape(status.code) << "\",\n"
              << "  \"legal_moves\": [";
    for (std::size_t i = 0; i < moves.size(); ++i) {
        if (i) std::cout << ", ";
        std::cout << "\"" << moves[i].uci() << "\"";
    }
    std::cout << "]\n}\n";
    return 0;
}

int cmd_perft(const std::vector<std::string>& args) {
    const int depth = as_int(arg_value(args, "--depth", "-1"), "depth");
    const Position p = load_position(args);
    const auto started = std::chrono::steady_clock::now();
    if (has_flag(args, "--divide")) {
        const auto divide = perft_divide(p, depth);
        std::uint64_t total = 0;
        std::cout << "{\n  \"fen\": \"" << json_escape(p.to_fen()) << "\",\n  \"depth\": " << depth << ",\n  \"divide\": {\n";
        for (std::size_t i = 0; i < divide.size(); ++i) {
            total += divide[i].second;
            std::cout << "    \"" << divide[i].first << "\": " << divide[i].second << (i + 1 == divide.size() ? "\n" : ",\n");
        }
        std::cout << "  },\n  \"nodes\": " << total << "\n}\n";
    } else {
        const auto nodes = perft(p, depth);
        const auto elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
        std::cout << "{\n  \"fen\": \"" << json_escape(p.to_fen()) << "\",\n  \"depth\": " << depth
                  << ",\n  \"nodes\": " << nodes << ",\n  \"seconds\": " << std::fixed << std::setprecision(6) << elapsed
                  << ",\n  \"nodes_per_second\": " << (elapsed > 0 ? static_cast<double>(nodes) / elapsed : 0.0) << "\n}\n";
    }
    return 0;
}

int cmd_search(const std::vector<std::string>& args) {
    const int depth = as_int(arg_value(args, "--depth", "5"), "depth");
    const auto budget = as_u64(arg_value(args, "--nodes", "10000000"), "nodes");
    const Position p = load_position(args);
    const auto result = search_position(p, depth, budget);
    std::cout << "{\n  \"fen\": \"" << json_escape(p.to_fen()) << "\",\n  \"depth\": " << result.depth
              << ",\n  \"nodes\": " << result.nodes << ",\n  \"score_cp\": " << result.score_cp
              << ",\n  \"status\": \"" << result.status << "\",\n  \"proof\": false,\n  \"pv\": [";
    for (std::size_t i = 0; i < result.principal_variation.size(); ++i) {
        if (i) std::cout << ", ";
        std::cout << "\"" << result.principal_variation[i].uci() << "\"";
    }
    std::cout << "]\n}\n";
    return 0;
}

int cmd_prove_mate(const std::vector<std::string>& args) {
    const int plies = as_int(arg_value(args, "--plies", "-1"), "plies");
    const auto budget = as_u64(arg_value(args, "--nodes", "2000000"), "nodes");
    const Position p = load_position(args);
    const auto result = prove_forced_mate(p, plies, budget);
    std::cout << "{\n  \"fen\": \"" << json_escape(p.to_fen()) << "\",\n  \"max_plies\": " << result.max_plies
              << ",\n  \"nodes\": " << result.nodes << ",\n  \"status\": \"" << result.status << "\",\n  \"proved\": " << (result.proved ? "true" : "false") << ",\n  \"representative_line\": [";
    for (std::size_t i = 0; i < result.principal_line.size(); ++i) {
        if (i) std::cout << ", ";
        std::cout << "\"" << result.principal_line[i].uci() << "\"";
    }
    std::cout << "]\n}\n";
    return result.proved ? 0 : 2;
}

int cmd_retro_demo(const std::vector<std::string>& args) {
    const auto result = solve_retrograde(make_demo_graph(), !has_flag(args, "--cpu"));
    std::cout << "{\n  \"backend\": \"" << json_escape(result.backend) << "\",\n  \"used_cuda\": " << (result.used_cuda ? "true" : "false")
              << ",\n  \"iterations\": " << result.iterations << ",\n  \"resolved_by_propagation\": " << result.resolved_by_propagation
              << ",\n  \"draws_after_fixpoint\": " << result.draws_after_fixpoint << ",\n  \"outcomes\": [";
    for (std::size_t i = 0; i < result.outcomes.size(); ++i) {
        if (i) std::cout << ", ";
        std::cout << "\"" << wdl_name(result.outcomes[i]) << "\"";
    }
    std::cout << "]\n}\n";
    return 0;
}

int cmd_root_shards(const std::vector<std::string>& args) {
    const Position p = load_position(args);
    const auto moves = legal_moves(p);
    std::cout << "{\n  \"root_fen\": \"" << json_escape(p.to_fen()) << "\",\n  \"root_sha256\": \"" << state_sha256(p) << "\",\n  \"game_theoretic_value\": \"unknown\",\n  \"shards\": [\n";
    for (std::size_t i = 0; i < moves.size(); ++i) {
        const auto child = apply_move(p, moves[i]);
        std::cout << "    {\"id\": \"root-" << std::setw(2) << std::setfill('0') << (i + 1) << '-' << moves[i].uci()
                  << "\", \"move\": \"" << moves[i].uci() << "\", \"child_fen\": \"" << json_escape(child.to_fen())
                  << "\", \"child_sha256\": \"" << state_sha256(child) << "\", \"status\": \"unresolved\"}"
                  << (i + 1 == moves.size() ? "\n" : ",\n");
    }
    std::cout << "  ]\n}\n";
    return 0;
}

int cmd_selftest() {
    const Position p = Position::initial();
    if (p.to_fen() != "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1") throw std::runtime_error("FEN roundtrip failed");
    const std::vector<std::uint64_t> expected = {1, 20, 400, 8902, 197281};
    for (int d = 0; d <= 4; ++d) if (perft(p, d) != expected[static_cast<std::size_t>(d)]) throw std::runtime_error("initial perft mismatch at depth " + std::to_string(d));
    const Position mate = Position::from_fen("8/8/8/8/8/k7/8/1QK5 w - - 0 1");
    const auto proof = prove_forced_mate(mate, 3, 200000);
    if (!proof.proved) throw std::runtime_error("mate-in-two proof failed");
    const auto retro = solve_retrograde_cpu(make_demo_graph());
    const std::vector<Wdl> expected_wdl = {Wdl::Loss, Wdl::Win, Wdl::Win, Wdl::Loss, Wdl::Draw, Wdl::Loss, Wdl::Win};
    if (retro.outcomes != expected_wdl) throw std::runtime_error("retrograde demo mismatch");
    std::cout << "{\"selftest\":\"pass\",\"perft_depth_4\":197281,\"mate_proved\":true,\"retrograde\":\"pass\"}\n";
    return 0;
}
}  // namespace

int main(int argc, char** argv) {
    try {
        if (argc < 2) { print_usage(); return 1; }
        std::vector<std::string> args;
        for (int i = 2; i < argc; ++i) args.emplace_back(argv[i]);
        const std::string command = argv[1];
        if (command == "info") return cmd_info();
        if (command == "validate") return cmd_validate(args);
        if (command == "perft") return cmd_perft(args);
        if (command == "search") return cmd_search(args);
        if (command == "prove-mate") return cmd_prove_mate(args);
        if (command == "retro-demo") return cmd_retro_demo(args);
        if (command == "root-shards") return cmd_root_shards(args);
        if (command == "selftest") return cmd_selftest();
        print_usage();
        return 1;
    } catch (const std::exception& exc) {
        std::cerr << "error: " << exc.what() << '\n';
        return 1;
    }
}
