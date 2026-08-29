#include "ugts_chess/cuda_api.hpp"
#include "ugts_chess/fen.hpp"
#include "ugts_chess/packed_chess.hpp"

#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {
using namespace ugts::chess;

constexpr std::array<char, 8> kInputMagic{{'U','G','T','S','C','B','2','0'}};
constexpr std::array<char, 8> kOutputMagic{{'U','G','T','S','M','V','2','0'}};

#pragma pack(push, 1)
struct InputHeader {
    char magic[8];
    std::uint32_t version;
    std::uint32_t record_size;
    std::uint32_t count;
    std::uint32_t flags;
    std::uint8_t reserved[40];
};
struct OutputHeader {
    char magic[8];
    std::uint32_t version;
    std::uint32_t move_size;
    std::uint32_t max_moves;
    std::uint32_t count;
    std::uint32_t flags;
    std::uint8_t reserved[36];
};
#pragma pack(pop)
static_assert(sizeof(InputHeader) == 64);
static_assert(sizeof(OutputHeader) == 64);
static_assert(sizeof(PackedPosition) == 64);

std::string json_escape(std::string_view value) {
    std::ostringstream out;
    for (unsigned char c : value) {
        switch (c) {
            case '"': out << "\\\""; break;
            case '\\': out << "\\\\"; break;
            case '\n': out << "\\n"; break;
            case '\r': out << "\\r"; break;
            case '\t': out << "\\t"; break;
            default: out << static_cast<char>(c); break;
        }
    }
    return out.str();
}

std::string arg_value(const std::vector<std::string>& args, std::string_view key, std::string fallback = {}) {
    for (std::size_t i = 0; i + 1 < args.size(); ++i) if (args[i] == key) return args[i + 1];
    return fallback;
}
bool has_flag(const std::vector<std::string>& args, std::string_view key) {
    return std::find(args.begin(), args.end(), key) != args.end();
}
int as_int(const std::string& text, const char* label) {
    try { return std::stoi(text); } catch (...) { throw std::invalid_argument(std::string(label) + " must be an integer"); }
}

std::vector<std::uint8_t> read_all(const std::string& path) {
    std::ifstream stream(path, std::ios::binary);
    if (!stream) throw std::runtime_error("cannot open input: " + path);
    stream.seekg(0, std::ios::end);
    const auto size = stream.tellg();
    if (size < 0) throw std::runtime_error("cannot determine input size");
    stream.seekg(0, std::ios::beg);
    std::vector<std::uint8_t> data(static_cast<std::size_t>(size));
    if (!data.empty()) stream.read(reinterpret_cast<char*>(data.data()), static_cast<std::streamsize>(data.size()));
    if (!stream) throw std::runtime_error("cannot read input: " + path);
    return data;
}
void write_all(const std::string& path, const void* data, std::size_t size) {
    std::ofstream stream(path, std::ios::binary | std::ios::trunc);
    if (!stream) throw std::runtime_error("cannot open output: " + path);
    stream.write(reinterpret_cast<const char*>(data), static_cast<std::streamsize>(size));
    if (!stream) throw std::runtime_error("cannot write output: " + path);
}

int cmd_device_info(const std::vector<std::string>& args) {
    const int device = as_int(arg_value(args, "--device", "0"), "device");
    const auto info = query_device(device);
    std::cout << "{\n"
              << "  \"cuda_compiled\": " << (info.cuda_compiled ? "true" : "false") << ",\n"
              << "  \"device_available\": " << (info.device_available ? "true" : "false") << ",\n"
              << "  \"device_index\": " << info.device_index << ",\n"
              << "  \"name\": \"" << json_escape(info.name) << "\",\n"
              << "  \"compute_capability\": \"" << info.compute_major << '.' << info.compute_minor << "\",\n"
              << "  \"total_memory_bytes\": " << info.total_memory << ",\n"
              << "  \"free_memory_bytes\": " << info.free_memory << ",\n"
              << "  \"multiprocessors\": " << info.multiprocessors << ",\n"
              << "  \"warp_size\": " << info.warp_size << ",\n"
              << "  \"max_threads_per_block\": " << info.max_threads_per_block << ",\n"
              << "  \"error\": \"" << json_escape(info.error) << "\"\n"
              << "}\n";
    return info.device_available ? 0 : 2;
}

int cmd_expand_fen(const std::vector<std::string>& args) {
    const std::string fen = arg_value(args, "--fen");
    if (fen.empty()) throw std::invalid_argument("--fen is required");
    PackedPosition position{};
    std::string error;
    if (!parse_fen(fen, position, error)) throw std::invalid_argument(error);
    auto moves = legal_uci_moves(position);
    std::cout << "{\n  \"fen\": \"" << json_escape(to_fen(position)) << "\",\n  \"legal_move_count\": " << moves.size() << ",\n  \"legal_moves\": [";
    for (std::size_t i = 0; i < moves.size(); ++i) {
        if (i) std::cout << ", ";
        std::cout << "\"" << moves[i] << "\"";
    }
    std::cout << "]\n}\n";
    return 0;
}

int cmd_expand_batch(const std::vector<std::string>& args) {
    const std::string input_path = arg_value(args, "--input");
    const std::string output_path = arg_value(args, "--output");
    if (input_path.empty() || output_path.empty()) throw std::invalid_argument("--input and --output are required");
    const int device = as_int(arg_value(args, "--device", "0"), "device");
    const bool force_cpu = has_flag(args, "--cpu");
    const auto bytes = read_all(input_path);
    if (bytes.size() < sizeof(InputHeader)) throw std::runtime_error("truncated input header");
    InputHeader header{};
    std::memcpy(&header, bytes.data(), sizeof(header));
    if (!std::equal(kInputMagic.begin(), kInputMagic.end(), header.magic)) throw std::runtime_error("bad input magic");
    if (header.version != 1 || header.record_size != sizeof(PackedPosition)) throw std::runtime_error("unsupported input format");
    const std::size_t expected = sizeof(InputHeader) + static_cast<std::size_t>(header.count) * sizeof(PackedPosition);
    if (bytes.size() != expected) throw std::runtime_error("input size mismatch");
    std::vector<PackedPosition> positions(header.count);
    if (header.count) std::memcpy(positions.data(), bytes.data() + sizeof(InputHeader), positions.size() * sizeof(PackedPosition));
    std::vector<std::uint16_t> counts(header.count, 0);
    std::vector<std::uint16_t> moves(static_cast<std::size_t>(header.count) * kMaxMoves, 0);

    bool used_cuda = false;
    std::string cuda_error_text;
    const auto started = std::chrono::steady_clock::now();
    if (!force_cpu && header.count) {
        used_cuda = expand_batch_cuda(positions.data(), positions.size(), moves.data(), counts.data(), device, cuda_error_text);
    }
    if (!used_cuda) {
        for (std::size_t i = 0; i < positions.size(); ++i) {
            MoveList list{};
            generate_legal_moves(positions[i], list);
            counts[i] = list.count;
            for (std::uint16_t j = 0; j < list.count; ++j) moves[i * kMaxMoves + j] = list.moves[j];
        }
    }
    const double seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
    OutputHeader out_header{};
    std::copy(kOutputMagic.begin(), kOutputMagic.end(), out_header.magic);
    out_header.version = 1;
    out_header.move_size = 2;
    out_header.max_moves = kMaxMoves;
    out_header.count = header.count;
    out_header.flags = used_cuda ? 1u : 0u;
    std::vector<std::uint8_t> output(sizeof(OutputHeader) + counts.size() * sizeof(std::uint16_t) + moves.size() * sizeof(std::uint16_t));
    std::size_t offset = 0;
    std::memcpy(output.data() + offset, &out_header, sizeof(out_header)); offset += sizeof(out_header);
    if (!counts.empty()) { std::memcpy(output.data() + offset, counts.data(), counts.size() * sizeof(std::uint16_t)); offset += counts.size() * sizeof(std::uint16_t); }
    if (!moves.empty()) std::memcpy(output.data() + offset, moves.data(), moves.size() * sizeof(std::uint16_t));
    write_all(output_path, output.data(), output.size());
    std::uint64_t total_moves = 0;
    for (auto count : counts) total_moves += count;
    std::cout << "{\"backend\":\"" << (used_cuda ? "cuda" : "cpu") << "\",\"positions\":" << positions.size()
              << ",\"moves\":" << total_moves << ",\"seconds\":" << std::fixed << std::setprecision(6) << seconds
              << ",\"cuda_fallback_reason\":\"" << json_escape(cuda_error_text) << "\"}\n";
    return 0;
}

int cmd_self_test() {
    struct Case { const char* name; const char* fen; int depth; std::uint64_t expected; };
    const std::array<Case, 9> cases{{
        {"initial_d1", "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", 1, 20},
        {"initial_d2", "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", 2, 400},
        {"initial_d3", "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", 3, 8902},
        {"initial_d4", "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", 4, 197281},
        {"kiwipete_d3", "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", 3, 97862},
        {"position3_d4", "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", 4, 43238},
        {"position4_d3", "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1", 3, 9467},
        {"position5_d3", "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8", 3, 62379},
        {"position6_d3", "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10", 3, 89890},
    }};
    std::cout << "{\n  \"record_size\": " << sizeof(PackedPosition) << ",\n  \"tests\": [\n";
    for (std::size_t i = 0; i < cases.size(); ++i) {
        PackedPosition position{}; std::string error;
        if (!parse_fen(cases[i].fen, position, error)) throw std::runtime_error(std::string(cases[i].name) + ": " + error);
        const auto actual = perft(position, cases[i].depth);
        if (actual != cases[i].expected) throw std::runtime_error(std::string(cases[i].name) + " mismatch");
        std::cout << "    {\"name\":\"" << cases[i].name << "\",\"depth\":" << cases[i].depth << ",\"nodes\":" << actual << ",\"pass\":true}"
                  << (i + 1 == cases.size() ? "\n" : ",\n");
    }
    std::cout << "  ],\n  \"passed\": " << cases.size() << "\n}\n";
    return 0;
}

void usage() {
    std::cout << "ugts-chess-gpu commands:\n"
              << "  device-info [--device N]\n"
              << "  self-test\n"
              << "  expand-fen --fen FEN\n"
              << "  expand-batch --input file.ugcb --output file.ugmv [--device N] [--cpu]\n";
}
}  // namespace

int main(int argc, char** argv) {
    try {
        if (argc < 2) { usage(); return 1; }
        std::vector<std::string> args;
        for (int i = 2; i < argc; ++i) args.emplace_back(argv[i]);
        const std::string command = argv[1];
        if (command == "device-info") return cmd_device_info(args);
        if (command == "self-test") return cmd_self_test();
        if (command == "expand-fen") return cmd_expand_fen(args);
        if (command == "expand-batch") return cmd_expand_batch(args);
        usage();
        return 1;
    } catch (const std::exception& exc) {
        std::cerr << "error: " << exc.what() << '\n';
        return 1;
    }
}
