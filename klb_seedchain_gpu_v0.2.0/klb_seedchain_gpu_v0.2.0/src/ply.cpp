#include "klb/ply.hpp"

#include <algorithm>
#include <array>
#include <bit>
#include <cctype>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <unordered_map>
#include <utility>
#include <vector>

namespace klb {
namespace {

enum class PlyFormat {
    Ascii,
    BinaryLittle,
    BinaryBig,
};

enum class ScalarType {
    Int8,
    UInt8,
    Int16,
    UInt16,
    Int32,
    UInt32,
    Float32,
    Float64,
};

struct Property {
    bool is_list{};
    ScalarType scalar_type{};
    ScalarType count_type{};
    ScalarType item_type{};
    std::string name;
};

struct Element {
    std::string name;
    std::uint64_t count{};
    std::vector<Property> properties;
};

std::string strip_cr(std::string value) {
    if (!value.empty() && value.back() == '\r') {
        value.pop_back();
    }
    return value;
}

ScalarType parse_scalar_type(const std::string& name) {
    static const std::unordered_map<std::string, ScalarType> types{
        {"char", ScalarType::Int8},
        {"int8", ScalarType::Int8},
        {"uchar", ScalarType::UInt8},
        {"uint8", ScalarType::UInt8},
        {"short", ScalarType::Int16},
        {"int16", ScalarType::Int16},
        {"ushort", ScalarType::UInt16},
        {"uint16", ScalarType::UInt16},
        {"int", ScalarType::Int32},
        {"int32", ScalarType::Int32},
        {"uint", ScalarType::UInt32},
        {"uint32", ScalarType::UInt32},
        {"float", ScalarType::Float32},
        {"float32", ScalarType::Float32},
        {"double", ScalarType::Float64},
        {"float64", ScalarType::Float64},
    };
    const auto it = types.find(name);
    if (it == types.end()) {
        throw std::runtime_error("unsupported PLY scalar type: " + name);
    }
    return it->second;
}

template <typename T>
T byte_swap(T value) {
    static_assert(std::is_trivially_copyable_v<T>);
    std::array<std::uint8_t, sizeof(T)> bytes{};
    std::memcpy(bytes.data(), &value, sizeof(T));
    std::reverse(bytes.begin(), bytes.end());
    std::memcpy(&value, bytes.data(), sizeof(T));
    return value;
}

template <typename T>
T read_binary_value(std::istream& input, bool swap_endian) {
    T value{};
    input.read(reinterpret_cast<char*>(&value), sizeof(T));
    if (!input) {
        throw std::runtime_error("unexpected end of binary PLY payload");
    }
    if (swap_endian && sizeof(T) > 1u) {
        value = byte_swap(value);
    }
    return value;
}

double read_binary_scalar(std::istream& input, ScalarType type, bool swap_endian) {
    switch (type) {
    case ScalarType::Int8:
        return static_cast<double>(read_binary_value<std::int8_t>(input, false));
    case ScalarType::UInt8:
        return static_cast<double>(read_binary_value<std::uint8_t>(input, false));
    case ScalarType::Int16:
        return static_cast<double>(read_binary_value<std::int16_t>(input, swap_endian));
    case ScalarType::UInt16:
        return static_cast<double>(read_binary_value<std::uint16_t>(input, swap_endian));
    case ScalarType::Int32:
        return static_cast<double>(read_binary_value<std::int32_t>(input, swap_endian));
    case ScalarType::UInt32:
        return static_cast<double>(read_binary_value<std::uint32_t>(input, swap_endian));
    case ScalarType::Float32:
        return static_cast<double>(read_binary_value<float>(input, swap_endian));
    case ScalarType::Float64:
        return read_binary_value<double>(input, swap_endian);
    }
    throw std::runtime_error("invalid PLY scalar type");
}

double read_ascii_scalar(std::istream& input) {
    std::string token;
    if (!(input >> token)) {
        throw std::runtime_error("unexpected end of ASCII PLY payload");
    }
    std::size_t consumed = 0;
    const double value = std::stod(token, &consumed);
    if (consumed != token.size()) {
        throw std::runtime_error("invalid numeric token in ASCII PLY: " + token);
    }
    return value;
}

std::uint64_t scalar_to_count(double value) {
    if (!std::isfinite(value) || value < 0.0 || value > 100000000.0) {
        throw std::runtime_error("unreasonable PLY list length");
    }
    const double rounded = std::floor(value + 0.5);
    if (std::abs(rounded - value) > 1.0e-9) {
        throw std::runtime_error("PLY list length is not an integer");
    }
    return static_cast<std::uint64_t>(rounded);
}

} // namespace

std::vector<Vec3> read_ply_vertices(const std::filesystem::path& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        throw std::runtime_error("failed to open PLY file: " + path.string());
    }

    std::string line;
    if (!std::getline(input, line) || strip_cr(line) != "ply") {
        throw std::runtime_error("not a PLY file: " + path.string());
    }

    bool have_format = false;
    bool have_end_header = false;
    PlyFormat format = PlyFormat::Ascii;
    std::vector<Element> elements;
    Element* current_element = nullptr;

    while (std::getline(input, line)) {
        line = strip_cr(std::move(line));
        std::istringstream tokens(line);
        std::string keyword;
        tokens >> keyword;
        if (keyword.empty() || keyword == "comment" || keyword == "obj_info") {
            continue;
        }
        if (keyword == "format") {
            std::string name;
            std::string version;
            tokens >> name >> version;
            if (version != "1.0") {
                throw std::runtime_error("unsupported PLY version: " + version);
            }
            if (name == "ascii") {
                format = PlyFormat::Ascii;
            } else if (name == "binary_little_endian") {
                format = PlyFormat::BinaryLittle;
            } else if (name == "binary_big_endian") {
                format = PlyFormat::BinaryBig;
            } else {
                throw std::runtime_error("unsupported PLY format: " + name);
            }
            have_format = true;
        } else if (keyword == "element") {
            std::string name;
            std::uint64_t count = 0;
            if (!(tokens >> name >> count)) {
                throw std::runtime_error("malformed PLY element declaration");
            }
            elements.push_back({name, count, {}});
            current_element = &elements.back();
        } else if (keyword == "property") {
            if (current_element == nullptr) {
                throw std::runtime_error("PLY property declared before any element");
            }
            std::string first;
            tokens >> first;
            if (first == "list") {
                std::string count_type;
                std::string item_type;
                std::string name;
                if (!(tokens >> count_type >> item_type >> name)) {
                    throw std::runtime_error("malformed PLY list property");
                }
                Property property{};
                property.is_list = true;
                property.count_type = parse_scalar_type(count_type);
                property.item_type = parse_scalar_type(item_type);
                property.name = name;
                current_element->properties.push_back(std::move(property));
            } else {
                std::string name;
                if (!(tokens >> name)) {
                    throw std::runtime_error("malformed PLY scalar property");
                }
                Property property{};
                property.is_list = false;
                property.scalar_type = parse_scalar_type(first);
                property.name = name;
                current_element->properties.push_back(std::move(property));
            }
        } else if (keyword == "end_header") {
            have_end_header = true;
            break;
        }
    }

    if (!have_format || !have_end_header) {
        throw std::runtime_error("incomplete PLY header: " + path.string());
    }

    std::uint64_t vertex_count = 0;
    for (const Element& element : elements) {
        if (element.name == "vertex") {
            vertex_count += element.count;
        }
    }
    if (vertex_count == 0u) {
        throw std::runtime_error("PLY file contains no vertex element");
    }
    if (vertex_count > static_cast<std::uint64_t>(std::numeric_limits<std::size_t>::max())) {
        throw std::runtime_error("PLY vertex count is too large for this host");
    }

    const bool file_little = format != PlyFormat::BinaryBig;
    const bool host_little = std::endian::native == std::endian::little;
    const bool swap_endian = format != PlyFormat::Ascii && file_little != host_little;
    auto read_scalar = [&](ScalarType type) -> double {
        if (format == PlyFormat::Ascii) {
            return read_ascii_scalar(input);
        }
        return read_binary_scalar(input, type, swap_endian);
    };

    std::vector<Vec3> points;
    points.reserve(static_cast<std::size_t>(vertex_count));

    for (const Element& element : elements) {
        for (std::uint64_t record = 0; record < element.count; ++record) {
            double x = 0.0;
            double y = 0.0;
            double z = 0.0;
            bool have_x = false;
            bool have_y = false;
            bool have_z = false;

            for (const Property& property : element.properties) {
                if (property.is_list) {
                    const std::uint64_t list_count = scalar_to_count(read_scalar(property.count_type));
                    for (std::uint64_t item = 0; item < list_count; ++item) {
                        (void)read_scalar(property.item_type);
                    }
                    continue;
                }

                const double value = read_scalar(property.scalar_type);
                if (element.name == "vertex") {
                    if (property.name == "x") {
                        x = value;
                        have_x = true;
                    } else if (property.name == "y") {
                        y = value;
                        have_y = true;
                    } else if (property.name == "z") {
                        z = value;
                        have_z = true;
                    }
                }
            }

            if (element.name == "vertex") {
                if (!have_x || !have_y || !have_z) {
                    throw std::runtime_error("PLY vertex element is missing x, y, or z");
                }
                if (!std::isfinite(x) || !std::isfinite(y) || !std::isfinite(z)) {
                    throw std::runtime_error("PLY contains a non-finite vertex coordinate");
                }
                points.emplace_back(static_cast<float>(x), static_cast<float>(y), static_cast<float>(z));
            }
        }
    }

    return points;
}

void write_ply_vertices_ascii(const std::filesystem::path& path, const std::vector<Vec3>& points) {
    std::ofstream output(path, std::ios::trunc);
    if (!output) {
        throw std::runtime_error("failed to create PLY file: " + path.string());
    }
    output << "ply\n"
           << "format ascii 1.0\n"
           << "comment generated by klb_cuda_arch_test\n"
           << "element vertex " << points.size() << "\n"
           << "property float x\n"
           << "property float y\n"
           << "property float z\n"
           << "element face 0\n"
           << "property list uchar int vertex_indices\n"
           << "end_header\n";
    output << std::setprecision(9);
    for (const Vec3& p : points) {
        output << p.x << ' ' << p.y << ' ' << p.z << '\n';
    }
    if (!output) {
        throw std::runtime_error("failed while writing PLY file: " + path.string());
    }
}

} // namespace klb

