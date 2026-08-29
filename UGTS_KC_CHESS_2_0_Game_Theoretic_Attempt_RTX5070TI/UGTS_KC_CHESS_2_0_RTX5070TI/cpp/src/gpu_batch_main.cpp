#include "ugts_chess/cuda_api.hpp"
#include "ugts_chess/fen.hpp"
#include "ugts_chess/packed_chess.hpp"

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace fs = std::filesystem;
using ugts::chess::DeviceInfo;
using ugts::chess::MoveList;
using ugts::chess::PackedPosition;
using ugts::chess::kMaxMoves;

namespace {

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

std::string json_escape(const std::string& value) {
    std::string out;
    for (const char ch : value) {
        switch (ch) {
            case '\\': out += "\\\\"; break;
            case '"': out += "\\\""; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default: out += ch; break;
        }
    }
    return out;
}

std::string argument(int argc, char** argv, const std::string& name, const std::string& fallback = {}) {
    for (int i = 2; i + 1 < argc; ++i) {
        if (argv[i] == name) return argv[i + 1];
    }
    return fallback;
}

bool has_flag(int argc, char** argv, const std::string& flag) {
    for (int i = 2; i < argc; ++i) if (argv[i] == flag) return true;
    return false;
}

std::vector<std::uint8_t> read_all(const fs::path& path) {
    std::ifstream stream(path, std::ios::binary);
    if (!stream) throw std::runtime_error("cannot open input: " + path.string());
    stream.seekg(0, std::ios::end);
    const auto end = stream.tellg();
    if (end < 0) throw std::runtime_error("cannot size input: " + path.string());
    std::vector<std::uint8_t> data(static_cast<std::size_t>(end));
    stream.seekg(0, std::ios::beg);
    if (!data.empty()) stream.read(reinterpret_cast<char*>(data.data()), static_cast<std::streamsize>(data.size()));
    if (!stream && !data.empty()) throw std::runtime_error("cannot read input: " + path.string());
    return data;
}

void write_all(const fs::path& path, const void* data, std::size_t size) {
    if (path.has_parent_path()) fs::create_directories(path.parent_path());
    std::ofstream stream(path, std::ios::binary | std::ios::trunc);
    if (!stream) throw std::runtime_error("cannot open output: " + path.string());
    stream.write(reinterpret_cast<const char*>(data), static_cast<std::streamsize>(size));
    if (!stream) throw std::runtime_error("cannot write output: " + path.string());
}

int device_info(int argc, char** argv) {
    const int device = std::stoi(argument(argc, argv, "--device", "0"));
    const DeviceInfo info = ugts::chess::query_device(device);
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

int expand_batch(int argc, char** argv) {
    const fs::path input = argument(argc, argv, "--input");
    const fs::path output = argument(argc, argv, "--output");
    if (input.empty() || output.empty()) throw std::invalid_argument("expand-batch requires --input and --output");
    const int device = std::stoi(argument(argc, argv, "--device", "0"));
    const bool force_cpu = has_flag(argc, argv, "--cpu");

    const auto raw = read_all(input);
    if (raw.size() < sizeof(InputHeader)) throw std::runtime_error("truncated batch header");
    InputHeader header{};
    std::memcpy(&header, raw.data(), sizeof(header));
    if (std::memcmp(header.magic, "UGTSCB20", 8) != 0 || header.version != 1 || header.record_size != sizeof(PackedPosition)) {
        throw std::runtime_error("unsupported input batch format");
    }
    if (header.count > 20'000'000u) throw std::runtime_error("batch count exceeds safety limit");
    const std::size_t expected = sizeof(InputHeader) + static_cast<std::size_t>(header.count) * sizeof(PackedPosition);
    if (raw.size() != expected) throw std::runtime_error("input batch size mismatch");

    std::vector<PackedPosition> positions(header.count);
    if (header.count) std::memcpy(positions.data(), raw.data() + sizeof(InputHeader), positions.size() * sizeof(PackedPosition));
    std::vector<std::uint16_t> counts(header.count, 0);
    std::vector<std::uint16_t> moves(static_cast<std::size_t>(header.count) * kMaxMoves, 0);

    bool used_cuda = false;
    std::string backend = "cpu-packed-exact-candidate";
    std::string cuda_error;
    if (!force_cpu) {
        const DeviceInfo info = ugts::chess::query_device(device);
        if (info.cuda_compiled && info.device_available) {
            used_cuda = ugts::chess::expand_batch_cuda(
                positions.data(), positions.size(), moves.data(), counts.data(), device, cuda_error);
            if (used_cuda) backend = "cuda-packed-candidate-sm-runtime";
        } else {
            cuda_error = info.error;
        }
    }
    if (!used_cuda) {
        for (std::size_t index = 0; index < positions.size(); ++index) {
            MoveList list{};
            ugts::chess::generate_legal_moves(positions[index], list);
            counts[index] = list.count;
            std::copy_n(list.moves, list.count, moves.data() + index * kMaxMoves);
        }
    }

    OutputHeader out_header{};
    std::memcpy(out_header.magic, "UGTSMV20", 8);
    out_header.version = 1;
    out_header.move_size = sizeof(std::uint16_t);
    out_header.max_moves = kMaxMoves;
    out_header.count = header.count;
    out_header.flags = used_cuda ? 1u : 0u;
    const std::size_t total = sizeof(OutputHeader) + counts.size() * sizeof(std::uint16_t) + moves.size() * sizeof(std::uint16_t);
    std::vector<std::uint8_t> encoded(total);
    std::size_t cursor = 0;
    std::memcpy(encoded.data() + cursor, &out_header, sizeof(out_header)); cursor += sizeof(out_header);
    if (!counts.empty()) { std::memcpy(encoded.data() + cursor, counts.data(), counts.size() * sizeof(std::uint16_t)); cursor += counts.size() * sizeof(std::uint16_t); }
    if (!moves.empty()) std::memcpy(encoded.data() + cursor, moves.data(), moves.size() * sizeof(std::uint16_t));
    write_all(output, encoded.data(), encoded.size());

    std::uint64_t move_total = 0;
    for (const auto count : counts) move_total += count;
    std::cout << "{\"backend\":\"" << backend << "\",\"positions\":" << positions.size()
              << ",\"moves\":" << move_total << ",\"output_bytes\":" << encoded.size()
              << ",\"cuda_fallback_reason\":\"" << json_escape(cuda_error) << "\"}\n";
    return 0;
}

int selftest() {
    ugts::chess::PackedPosition position{};
    std::string error;
    if (!ugts::chess::parse_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", position, error)) {
        throw std::runtime_error("FEN selftest failed: " + error);
    }
    const auto moves = ugts::chess::legal_uci_moves(position);
    if (moves.size() != 20) throw std::runtime_error("move-generation selftest expected 20 moves");
    std::cout << "{\"valid\":true,\"initial_legal_moves\":20,\"backend\":\"packed-host-or-cuda-candidate\"}\n";
    return 0;
}

void usage() {
    std::cerr << "ugts-chess-gpu device-info [--device N]\n"
              << "ugts-chess-gpu expand-batch --input positions.ugcb --output moves.ugmv [--device N] [--cpu]\n"
              << "ugts-chess-gpu selftest\n";
}

}  // namespace

int main(int argc, char** argv) {
    try {
        if (argc < 2) { usage(); return 1; }
        const std::string command = argv[1];
        if (command == "device-info") return device_info(argc, argv);
        if (command == "expand-batch") return expand_batch(argc, argv);
        if (command == "selftest") return selftest();
        usage();
        return 1;
    } catch (const std::exception& exc) {
        std::cerr << "error: " << exc.what() << '\n';
        return 1;
    }
}
