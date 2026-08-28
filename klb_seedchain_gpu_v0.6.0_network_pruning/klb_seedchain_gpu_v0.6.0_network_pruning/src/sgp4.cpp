#include "klb/sgp4.hpp"

#include <algorithm>
#include <array>
#include <bit>
#include <charconv>
#include <cmath>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <limits>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string_view>

namespace klb {
namespace {

constexpr std::array<char, 8> kSgp4Magic{'K', 'S', 'G', 'P', '1', '\0', '\0', '\0'};
constexpr std::uint64_t kFnvOffset = 1469598103934665603ull;
constexpr std::uint64_t kFnvPrime = 1099511628211ull;

void require_little_endian() {
    if constexpr (std::endian::native != std::endian::little) {
        throw std::runtime_error("KSGP1 currently requires a little-endian host");
    }
}

std::uint64_t fnv_update(std::uint64_t hash, const void* data, std::size_t size) {
    const auto* bytes = static_cast<const std::uint8_t*>(data);
    for (std::size_t index = 0; index < size; ++index) {
        hash ^= bytes[index];
        hash *= kFnvPrime;
    }
    return hash;
}

std::uint64_t payload_hash(const Sgp4Data& data) {
    std::uint64_t hash = kFnvOffset;
    if (!data.seeds.empty()) {
        hash = fnv_update(hash, data.seeds.data(), data.seeds.size() * sizeof(Sgp4SeedDisk));
    }
    if (!data.nodes.empty()) {
        hash = fnv_update(hash, data.nodes.data(), data.nodes.size() * sizeof(Sgp4TimelineNodeDisk));
    }
    if (!data.strings.empty()) hash = fnv_update(hash, data.strings.data(), data.strings.size());
    return hash;
}

std::uint64_t hash_node(const Sgp4TimelineNodeDisk& input) {
    Sgp4TimelineNodeDisk node = input;
    node.self_hash = 0u;
    return fnv1a64(&node, sizeof(node));
}

std::string read_binary_text(const std::filesystem::path& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) throw std::runtime_error("unable to open input file: " + path.string());
    input.seekg(0, std::ios::end);
    const std::streamoff end = input.tellg();
    if (end < 0) throw std::runtime_error("unable to determine input size: " + path.string());
    input.seekg(0, std::ios::beg);
    std::string bytes(static_cast<std::size_t>(end), '\0');
    if (!bytes.empty()) input.read(bytes.data(), static_cast<std::streamsize>(bytes.size()));
    if (!input) throw std::runtime_error("failed while reading input file: " + path.string());
    return bytes;
}

std::vector<std::string> parse_csv_row(std::string_view line) {
    std::vector<std::string> fields;
    std::string field;
    bool quoted = false;
    for (std::size_t index = 0; index < line.size(); ++index) {
        const char character = line[index];
        if (quoted) {
            if (character == '"') {
                if (index + 1u < line.size() && line[index + 1u] == '"') {
                    field.push_back('"');
                    ++index;
                } else {
                    quoted = false;
                }
            } else {
                field.push_back(character);
            }
        } else if (character == '"') {
            quoted = true;
        } else if (character == ',') {
            fields.push_back(std::move(field));
            field.clear();
        } else if (character != '\r') {
            field.push_back(character);
        }
    }
    if (quoted) throw std::runtime_error("unterminated quoted CSV field");
    fields.push_back(std::move(field));
    return fields;
}

std::int64_t days_from_civil(int year, unsigned month, unsigned day) {
    year -= month <= 2u ? 1 : 0;
    const int era = (year >= 0 ? year : year - 399) / 400;
    const unsigned yoe = static_cast<unsigned>(year - era * 400);
    const unsigned adjusted_month = month > 2u ? month - 3u : month + 9u;
    const unsigned doy = (153u * adjusted_month + 2u) / 5u + day - 1u;
    const unsigned doe = yoe * 365u + yoe / 4u - yoe / 100u + doy;
    return static_cast<std::int64_t>(era) * 146097ll + static_cast<std::int64_t>(doe) - 719468ll;
}

int parse_fixed_int(std::string_view text, std::size_t offset, std::size_t count, const char* name) {
    if (offset + count > text.size()) throw std::runtime_error(std::string("short ISO epoch while parsing ") + name);
    int value = 0;
    const char* begin = text.data() + offset;
    const char* end = begin + count;
    const auto result = std::from_chars(begin, end, value);
    if (result.ec != std::errc{} || result.ptr != end) {
        throw std::runtime_error(std::string("invalid ISO epoch ") + name);
    }
    return value;
}

std::int64_t parse_iso8601_microseconds(std::string_view text) {
    if (text.size() < 19u || text[4] != '-' || text[7] != '-' ||
        (text[10] != 'T' && text[10] != ' ') || text[13] != ':' || text[16] != ':') {
        throw std::runtime_error("unsupported OMM epoch format: " + std::string(text));
    }
    const int year = parse_fixed_int(text, 0u, 4u, "year");
    const int month = parse_fixed_int(text, 5u, 2u, "month");
    const int day = parse_fixed_int(text, 8u, 2u, "day");
    const int hour = parse_fixed_int(text, 11u, 2u, "hour");
    const int minute = parse_fixed_int(text, 14u, 2u, "minute");
    const int second = parse_fixed_int(text, 17u, 2u, "second");
    if (month < 1 || month > 12 || day < 1 || day > 31 || hour < 0 || hour > 23 ||
        minute < 0 || minute > 59 || second < 0 || second > 60) {
        throw std::runtime_error("out-of-range OMM epoch: " + std::string(text));
    }
    std::int64_t fraction = 0;
    if (text.size() > 19u && text[19] == '.') {
        std::size_t index = 20u;
        std::size_t digits = 0u;
        while (index < text.size() && text[index] >= '0' && text[index] <= '9' && digits < 6u) {
            fraction = fraction * 10ll + static_cast<std::int64_t>(text[index] - '0');
            ++index;
            ++digits;
        }
        while (digits < 6u) {
            fraction *= 10ll;
            ++digits;
        }
    }
    const std::int64_t days = days_from_civil(year, static_cast<unsigned>(month), static_cast<unsigned>(day));
    return (((days * 24ll + hour) * 60ll + minute) * 60ll + second) * 1000000ll + fraction;
}

double unix_microseconds_to_julian(std::int64_t value) {
    return static_cast<double>(value) / 1.0e6 / 86400.0 + 2440587.5;
}

std::uint16_t parse_prn(std::string_view object_name) {
    const std::size_t marker = object_name.find("PRN");
    if (marker == std::string_view::npos) return 0u;
    std::size_t index = marker + 3u;
    while (index < object_name.size() && object_name[index] == ' ') ++index;
    unsigned value = 0u;
    const char* begin = object_name.data() + index;
    const char* end = object_name.data() + object_name.size();
    const auto result = std::from_chars(begin, end, value);
    if (result.ec != std::errc{}) return 0u;
    return static_cast<std::uint16_t>(std::min(value, 65535u));
}

std::uint32_t append_string(std::vector<char>& table, std::string_view text) {
    if (table.empty()) table.push_back('\0');
    if (table.size() > std::numeric_limits<std::uint32_t>::max() - text.size() - 1u) {
        throw std::runtime_error("KSGP1 string table exceeds 32-bit offsets");
    }
    const std::uint32_t offset = static_cast<std::uint32_t>(table.size());
    table.insert(table.end(), text.begin(), text.end());
    table.push_back('\0');
    return offset;
}

const std::string& required_field(const std::vector<std::string>& fields,
                                  const std::map<std::string, std::size_t>& columns,
                                  const char* name) {
    const auto iterator = columns.find(name);
    if (iterator == columns.end() || iterator->second >= fields.size()) {
        throw std::runtime_error(std::string("OMM CSV is missing required field ") + name);
    }
    return fields[iterator->second];
}

std::uint32_t parse_u32(const std::string& text, const char* name) {
    if (text.empty()) return 0u;
    std::size_t consumed = 0u;
    const unsigned long value = std::stoul(text, &consumed, 10);
    if (consumed != text.size() || value > std::numeric_limits<std::uint32_t>::max()) {
        throw std::runtime_error(std::string("invalid OMM integer ") + name + ": " + text);
    }
    return static_cast<std::uint32_t>(value);
}

double parse_double(const std::string& text, const char* name) {
    if (text.empty()) return 0.0;
    std::size_t consumed = 0u;
    const double value = std::stod(text, &consumed);
    if (consumed != text.size() || !std::isfinite(value)) {
        throw std::runtime_error(std::string("invalid OMM scalar ") + name + ": " + text);
    }
    return value;
}

struct OmmSgp4Row {
    std::string object_name;
    std::string object_id;
    std::int64_t epoch_microseconds{};
    double mean_motion_rev_day{};
    double eccentricity{};
    double inclination_deg{};
    double raan_deg{};
    double argument_perigee_deg{};
    double mean_anomaly_deg{};
    double bstar{};
    double mean_motion_dot_rev_day2{};
    double mean_motion_ddot_rev_day3{};
    std::uint32_t norad_id{};
    std::uint32_t element_set_no{};
    std::uint32_t revolution_number{};
    std::uint32_t ephemeris_type{};
    std::uint16_t prn{};
    char classification{'U'};
};

std::vector<OmmSgp4Row> parse_omm_rows(const std::string& text) {
    std::istringstream input(text);
    std::string line;
    if (!std::getline(input, line)) throw std::runtime_error("OMM CSV is empty");
    const std::vector<std::string> header = parse_csv_row(line);
    std::map<std::string, std::size_t> columns;
    for (std::size_t index = 0; index < header.size(); ++index) columns.emplace(header[index], index);

    std::vector<OmmSgp4Row> rows;
    while (std::getline(input, line)) {
        if (line.empty() || line == "\r") continue;
        const std::vector<std::string> fields = parse_csv_row(line);
        OmmSgp4Row row{};
        row.object_name = required_field(fields, columns, "OBJECT_NAME");
        row.object_id = required_field(fields, columns, "OBJECT_ID");
        row.epoch_microseconds = parse_iso8601_microseconds(required_field(fields, columns, "EPOCH"));
        row.mean_motion_rev_day = parse_double(required_field(fields, columns, "MEAN_MOTION"), "MEAN_MOTION");
        row.eccentricity = parse_double(required_field(fields, columns, "ECCENTRICITY"), "ECCENTRICITY");
        row.inclination_deg = parse_double(required_field(fields, columns, "INCLINATION"), "INCLINATION");
        row.raan_deg = parse_double(required_field(fields, columns, "RA_OF_ASC_NODE"), "RA_OF_ASC_NODE");
        row.argument_perigee_deg = parse_double(required_field(fields, columns, "ARG_OF_PERICENTER"), "ARG_OF_PERICENTER");
        row.mean_anomaly_deg = parse_double(required_field(fields, columns, "MEAN_ANOMALY"), "MEAN_ANOMALY");
        row.norad_id = parse_u32(required_field(fields, columns, "NORAD_CAT_ID"), "NORAD_CAT_ID");
        row.element_set_no = parse_u32(required_field(fields, columns, "ELEMENT_SET_NO"), "ELEMENT_SET_NO");
        row.revolution_number = parse_u32(required_field(fields, columns, "REV_AT_EPOCH"), "REV_AT_EPOCH");
        row.ephemeris_type = parse_u32(required_field(fields, columns, "EPHEMERIS_TYPE"), "EPHEMERIS_TYPE");
        row.bstar = parse_double(required_field(fields, columns, "BSTAR"), "BSTAR");
        row.mean_motion_dot_rev_day2 = parse_double(required_field(fields, columns, "MEAN_MOTION_DOT"), "MEAN_MOTION_DOT");
        row.mean_motion_ddot_rev_day3 = parse_double(required_field(fields, columns, "MEAN_MOTION_DDOT"), "MEAN_MOTION_DDOT");
        const std::string classification = required_field(fields, columns, "CLASSIFICATION_TYPE");
        row.classification = classification.empty() ? 'U' : classification.front();
        row.prn = parse_prn(row.object_name);
        if (row.mean_motion_rev_day <= 0.0 || row.eccentricity < 0.0 || row.eccentricity >= 1.0) {
            throw std::runtime_error("invalid OMM orbital elements for NORAD " + std::to_string(row.norad_id));
        }
        rows.push_back(std::move(row));
    }
    if (rows.empty()) throw std::runtime_error("OMM CSV contains no records");
    std::sort(rows.begin(), rows.end(), [](const OmmSgp4Row& left, const OmmSgp4Row& right) {
        return left.norad_id < right.norad_id;
    });
    return rows;
}

void initialize_offsets(Sgp4Data& data) {
    data.header.header_bytes = sizeof(Sgp4HeaderDisk);
    data.header.seed_bytes = sizeof(Sgp4SeedDisk);
    data.header.node_bytes = sizeof(Sgp4TimelineNodeDisk);
    data.header.seed_count = data.seeds.size();
    data.header.node_count = data.nodes.size();
    data.header.seeds_offset = sizeof(Sgp4HeaderDisk);
    data.header.nodes_offset = data.header.seeds_offset + data.seeds.size() * sizeof(Sgp4SeedDisk);
    data.header.strings_offset = data.header.nodes_offset + data.nodes.size() * sizeof(Sgp4TimelineNodeDisk);
    data.header.strings_bytes = data.strings.size();
}

void sgp4_initl(double epoch, Sgp4Record& rec) {
    constexpr double x2o3 = 2.0 / 3.0;
    rec.eccsq = rec.ecco * rec.ecco;
    rec.omeosq = 1.0 - rec.eccsq;
    rec.rteosq = std::sqrt(rec.omeosq);
    rec.cosio = std::cos(rec.inclo);
    rec.cosio2 = rec.cosio * rec.cosio;
    const double ak = std::pow(rec.xke / rec.no_kozai, x2o3);
    const double d1 = 0.75 * rec.j2 * (3.0 * rec.cosio2 - 1.0) /
                      (rec.rteosq * rec.omeosq);
    double del = d1 / (ak * ak);
    const double adel = ak * (1.0 - del * del - del *
        (1.0 / 3.0 + 134.0 * del * del / 81.0));
    del = d1 / (adel * adel);
    rec.no_unkozai = rec.no_kozai / (1.0 + del);
    rec.ao = std::pow(rec.xke / rec.no_unkozai, x2o3);
    rec.sinio = std::sin(rec.inclo);
    const double po = rec.ao * rec.omeosq;
    rec.con42 = 1.0 - 5.0 * rec.cosio2;
    rec.con41 = -rec.con42 - 2.0 * rec.cosio2;
    rec.ainv = 1.0 / rec.ao;
    rec.posq = po * po;
    rec.rp = rec.ao * (1.0 - rec.ecco);
    rec.method = 'n';
    rec.gsto = sgp4_gstime(epoch + 2433281.5);
}

void sgp4_dscom(double epoch, double ep, double argpp, double tc,
                double inclp, double nodep, double np, Sgp4Record& rec) {
    constexpr double zes = 0.01675;
    constexpr double zel = 0.05490;
    constexpr double c1ss = 2.9864797e-6;
    constexpr double c1l = 4.7968065e-7;
    constexpr double zsinis = 0.39785416;
    constexpr double zcosis = 0.91744867;
    constexpr double zcosgs = 0.1945905;
    constexpr double zsings = -0.98088458;

    rec.nm = np;
    rec.em = ep;
    rec.snodm = std::sin(nodep);
    rec.cnodm = std::cos(nodep);
    rec.sinomm = std::sin(argpp);
    rec.cosomm = std::cos(argpp);
    rec.sinim = std::sin(inclp);
    rec.cosim = std::cos(inclp);
    rec.emsq = rec.em * rec.em;
    const double betasq = 1.0 - rec.emsq;
    rec.rtemsq = std::sqrt(betasq);
    rec.peo = rec.pinco = rec.plo = rec.pgho = rec.pho = 0.0;
    rec.day = epoch + 18261.5 + tc / 1440.0;
    const double xnodce = std::fmod(4.5236020 - 9.2422029e-4 * rec.day, kSgp4TwoPi);
    const double stem = std::sin(xnodce);
    const double ctem = std::cos(xnodce);
    const double zcosil = 0.91375164 - 0.03568096 * ctem;
    const double zsinil = std::sqrt(1.0 - zcosil * zcosil);
    const double zsinhl = 0.089683511 * stem / zsinil;
    const double zcoshl = std::sqrt(1.0 - zsinhl * zsinhl);
    rec.gam = 5.8351514 + 0.0019443680 * rec.day;
    double zx = 0.39785416 * stem / zsinil;
    const double zy = zcoshl * ctem + 0.91744867 * zsinhl * stem;
    zx = std::atan2(zx, zy);
    zx = rec.gam + zx - xnodce;
    const double zcosgl = std::cos(zx);
    const double zsingl = std::sin(zx);

    double zcosg = zcosgs;
    double zsing = zsings;
    double zcosi = zcosis;
    double zsini = zsinis;
    double zcosh = rec.cnodm;
    double zsinh = rec.snodm;
    double cc = c1ss;
    const double xnoi = 1.0 / rec.nm;

    for (int lsflg = 1; lsflg <= 2; ++lsflg) {
        const double a1 = zcosg * zcosh + zsing * zcosi * zsinh;
        const double a3 = -zsing * zcosh + zcosg * zcosi * zsinh;
        const double a7 = -zcosg * zsinh + zsing * zcosi * zcosh;
        const double a8 = zsing * zsini;
        const double a9 = zsing * zsinh + zcosg * zcosi * zcosh;
        const double a10 = zcosg * zsini;
        const double a2 = rec.cosim * a7 + rec.sinim * a8;
        const double a4 = rec.cosim * a9 + rec.sinim * a10;
        const double a5 = -rec.sinim * a7 + rec.cosim * a8;
        const double a6 = -rec.sinim * a9 + rec.cosim * a10;
        const double x1 = a1 * rec.cosomm + a2 * rec.sinomm;
        const double x2 = a3 * rec.cosomm + a4 * rec.sinomm;
        const double x3 = -a1 * rec.sinomm + a2 * rec.cosomm;
        const double x4 = -a3 * rec.sinomm + a4 * rec.cosomm;
        const double x5 = a5 * rec.sinomm;
        const double x6 = a6 * rec.sinomm;
        const double x7 = a5 * rec.cosomm;
        const double x8 = a6 * rec.cosomm;

        rec.z31 = 12.0 * x1 * x1 - 3.0 * x3 * x3;
        rec.z32 = 24.0 * x1 * x2 - 6.0 * x3 * x4;
        rec.z33 = 12.0 * x2 * x2 - 3.0 * x4 * x4;
        rec.z1 = 3.0 * (a1 * a1 + a2 * a2) + rec.z31 * rec.emsq;
        rec.z2 = 6.0 * (a1 * a3 + a2 * a4) + rec.z32 * rec.emsq;
        rec.z3 = 3.0 * (a3 * a3 + a4 * a4) + rec.z33 * rec.emsq;
        rec.z11 = -6.0 * a1 * a5 + rec.emsq * (-24.0 * x1 * x7 - 6.0 * x3 * x5);
        rec.z12 = -6.0 * (a1 * a6 + a3 * a5) + rec.emsq *
            (-24.0 * (x2 * x7 + x1 * x8) - 6.0 * (x3 * x6 + x4 * x5));
        rec.z13 = -6.0 * a3 * a6 + rec.emsq * (-24.0 * x2 * x8 - 6.0 * x4 * x6);
        rec.z21 = 6.0 * a2 * a5 + rec.emsq * (24.0 * x1 * x5 - 6.0 * x3 * x7);
        rec.z22 = 6.0 * (a4 * a5 + a2 * a6) + rec.emsq *
            (24.0 * (x2 * x5 + x1 * x6) - 6.0 * (x4 * x7 + x3 * x8));
        rec.z23 = 6.0 * a4 * a6 + rec.emsq * (24.0 * x2 * x6 - 6.0 * x4 * x8);
        rec.z1 = rec.z1 + rec.z1 + betasq * rec.z31;
        rec.z2 = rec.z2 + rec.z2 + betasq * rec.z32;
        rec.z3 = rec.z3 + rec.z3 + betasq * rec.z33;
        rec.s3 = cc * xnoi;
        rec.s2 = -0.5 * rec.s3 / rec.rtemsq;
        rec.s4 = rec.s3 * rec.rtemsq;
        rec.s1 = -15.0 * rec.em * rec.s4;
        rec.s5 = x1 * x3 + x2 * x4;
        rec.s6 = x2 * x3 + x1 * x4;
        rec.s7 = x2 * x4 - x1 * x3;
        if (lsflg == 1) {
            rec.ss1 = rec.s1; rec.ss2 = rec.s2; rec.ss3 = rec.s3; rec.ss4 = rec.s4;
            rec.ss5 = rec.s5; rec.ss6 = rec.s6; rec.ss7 = rec.s7;
            rec.sz1 = rec.z1; rec.sz2 = rec.z2; rec.sz3 = rec.z3;
            rec.sz11 = rec.z11; rec.sz12 = rec.z12; rec.sz13 = rec.z13;
            rec.sz21 = rec.z21; rec.sz22 = rec.z22; rec.sz23 = rec.z23;
            rec.sz31 = rec.z31; rec.sz32 = rec.z32; rec.sz33 = rec.z33;
            zcosg = zcosgl;
            zsing = zsingl;
            zcosi = zcosil;
            zsini = zsinil;
            zcosh = zcoshl * rec.cnodm + zsinhl * rec.snodm;
            zsinh = rec.snodm * zcoshl - rec.cnodm * zsinhl;
            cc = c1l;
        }
    }

    rec.zmol = std::fmod(4.7199672 + 0.22997150 * rec.day - rec.gam, kSgp4TwoPi);
    rec.zmos = std::fmod(6.2565837 + 0.017201977 * rec.day, kSgp4TwoPi);
    rec.se2 = 2.0 * rec.ss1 * rec.ss6;
    rec.se3 = 2.0 * rec.ss1 * rec.ss7;
    rec.si2 = 2.0 * rec.ss2 * rec.sz12;
    rec.si3 = 2.0 * rec.ss2 * (rec.sz13 - rec.sz11);
    rec.sl2 = -2.0 * rec.ss3 * rec.sz2;
    rec.sl3 = -2.0 * rec.ss3 * (rec.sz3 - rec.sz1);
    rec.sl4 = -2.0 * rec.ss3 * (-21.0 - 9.0 * rec.emsq) * zes;
    rec.sgh2 = 2.0 * rec.ss4 * rec.sz32;
    rec.sgh3 = 2.0 * rec.ss4 * (rec.sz33 - rec.sz31);
    rec.sgh4 = -18.0 * rec.ss4 * zes;
    rec.sh2 = -2.0 * rec.ss2 * rec.sz22;
    rec.sh3 = -2.0 * rec.ss2 * (rec.sz23 - rec.sz21);
    rec.ee2 = 2.0 * rec.s1 * rec.s6;
    rec.e3 = 2.0 * rec.s1 * rec.s7;
    rec.xi2 = 2.0 * rec.s2 * rec.z12;
    rec.xi3 = 2.0 * rec.s2 * (rec.z13 - rec.z11);
    rec.xl2 = -2.0 * rec.s3 * rec.z2;
    rec.xl3 = -2.0 * rec.s3 * (rec.z3 - rec.z1);
    rec.xl4 = -2.0 * rec.s3 * (-21.0 - 9.0 * rec.emsq) * zel;
    rec.xgh2 = 2.0 * rec.s4 * rec.z32;
    rec.xgh3 = 2.0 * rec.s4 * (rec.z33 - rec.z31);
    rec.xgh4 = -18.0 * rec.s4 * zel;
    rec.xh2 = -2.0 * rec.s2 * rec.z22;
    rec.xh3 = -2.0 * rec.s2 * (rec.z23 - rec.z21);
}


void sgp4_dsinit(double tc, double xpidot, Sgp4Record& rec) {
    constexpr double q22 = 1.7891679e-6;
    constexpr double q31 = 2.1460748e-6;
    constexpr double q33 = 2.2123015e-7;
    constexpr double root22 = 1.7891679e-6;
    constexpr double root44 = 7.3636953e-9;
    constexpr double root54 = 2.1765803e-9;
    constexpr double rptim = 4.37526908801129966e-3;
    constexpr double root32 = 3.7393792e-7;
    constexpr double root52 = 1.1428639e-7;
    constexpr double x2o3 = 2.0 / 3.0;
    constexpr double znl = 1.5835218e-4;
    constexpr double zns = 1.19459e-5;

    rec.irez = 0;
    if (rec.nm < 0.0052359877 && rec.nm > 0.0034906585) rec.irez = 1;
    if (rec.nm >= 8.26e-3 && rec.nm <= 9.24e-3 && rec.em >= 0.5) rec.irez = 2;

    const double ses = rec.ss1 * zns * rec.ss5;
    const double sis = rec.ss2 * zns * (rec.sz11 + rec.sz13);
    const double sls = -zns * rec.ss3 * (rec.sz1 + rec.sz3 - 14.0 - 6.0 * rec.emsq);
    const double sghs = rec.ss4 * zns * (rec.sz31 + rec.sz33 - 6.0);
    double shs = -zns * rec.ss2 * (rec.sz21 + rec.sz23);
    if (rec.inclm < 5.2359877e-2 || rec.inclm > kSgp4Pi - 5.2359877e-2) shs = 0.0;
    if (rec.sinim != 0.0) shs /= rec.sinim;
    const double sgs = sghs - rec.cosim * shs;

    rec.dedt = ses + rec.s1 * znl * rec.s5;
    rec.didt = sis + rec.s2 * znl * (rec.z11 + rec.z13);
    rec.dmdt = sls - znl * rec.s3 * (rec.z1 + rec.z3 - 14.0 - 6.0 * rec.emsq);
    const double sghl = rec.s4 * znl * (rec.z31 + rec.z33 - 6.0);
    double shll = -znl * rec.s2 * (rec.z21 + rec.z23);
    if (rec.inclm < 5.2359877e-2 || rec.inclm > kSgp4Pi - 5.2359877e-2) shll = 0.0;
    rec.domdt = sgs + sghl;
    rec.dnodt = shs;
    if (rec.sinim != 0.0) {
        rec.domdt -= rec.cosim / rec.sinim * shll;
        rec.dnodt += shll / rec.sinim;
    }

    rec.dndt = 0.0;
    const double theta = std::fmod(rec.gsto + tc * rptim, kSgp4TwoPi);
    rec.em += rec.dedt * rec.t;
    rec.inclm += rec.didt * rec.t;
    rec.argpm += rec.domdt * rec.t;
    rec.nodem += rec.dnodt * rec.t;
    rec.mm += rec.dmdt * rec.t;

    if (rec.irez != 0) {
        const double aonv = std::pow(rec.nm / rec.xke, x2o3);
        if (rec.irez == 2) {
            const double cosisq = rec.cosim * rec.cosim;
            const double emo = rec.em;
            rec.em = rec.ecco;
            const double emsqo = rec.emsq;
            rec.emsq = rec.eccsq;
            const double eoc = rec.em * rec.emsq;
            const double g201 = -0.306 - (rec.em - 0.64) * 0.440;
            double g211{};
            double g310{};
            double g322{};
            double g410{};
            double g422{};
            double g520{};
            if (rec.em <= 0.65) {
                g211 = 3.616 - 13.2470 * rec.em + 16.2900 * rec.emsq;
                g310 = -19.302 + 117.3900 * rec.em - 228.4190 * rec.emsq + 156.5910 * eoc;
                g322 = -18.9068 + 109.7927 * rec.em - 214.6334 * rec.emsq + 146.5816 * eoc;
                g410 = -41.122 + 242.6940 * rec.em - 471.0940 * rec.emsq + 313.9530 * eoc;
                g422 = -146.407 + 841.8800 * rec.em - 1629.014 * rec.emsq + 1083.4350 * eoc;
                g520 = -532.114 + 3017.977 * rec.em - 5740.032 * rec.emsq + 3708.2760 * eoc;
            } else {
                g211 = -72.099 + 331.819 * rec.em - 508.738 * rec.emsq + 266.724 * eoc;
                g310 = -346.844 + 1582.851 * rec.em - 2415.925 * rec.emsq + 1246.113 * eoc;
                g322 = -342.585 + 1554.908 * rec.em - 2366.899 * rec.emsq + 1215.972 * eoc;
                g410 = -1052.797 + 4758.686 * rec.em - 7193.992 * rec.emsq + 3651.957 * eoc;
                g422 = -3581.690 + 16178.110 * rec.em - 24462.770 * rec.emsq + 12422.520 * eoc;
                g520 = rec.em > 0.715
                    ? -5149.66 + 29936.92 * rec.em - 54087.36 * rec.emsq + 31324.56 * eoc
                    : 1464.74 - 4664.75 * rec.em + 3763.64 * rec.emsq;
            }
            double g533{};
            double g521{};
            double g532{};
            if (rec.em < 0.7) {
                g533 = -919.22770 + 4988.6100 * rec.em - 9064.7700 * rec.emsq + 5542.21 * eoc;
                g521 = -822.71072 + 4568.6173 * rec.em - 8491.4146 * rec.emsq + 5337.524 * eoc;
                g532 = -853.66600 + 4690.2500 * rec.em - 8624.7700 * rec.emsq + 5341.4 * eoc;
            } else {
                g533 = -37995.780 + 161616.52 * rec.em - 229838.20 * rec.emsq + 109377.94 * eoc;
                g521 = -51752.104 + 218913.95 * rec.em - 309468.16 * rec.emsq + 146349.42 * eoc;
                g532 = -40023.880 + 170470.89 * rec.em - 242699.48 * rec.emsq + 115605.82 * eoc;
            }
            const double sini2 = rec.sinim * rec.sinim;
            const double f220 = 0.75 * (1.0 + 2.0 * rec.cosim + cosisq);
            const double f221 = 1.5 * sini2;
            const double f321 = 1.875 * rec.sinim * (1.0 - 2.0 * rec.cosim - 3.0 * cosisq);
            const double f322 = -1.875 * rec.sinim * (1.0 + 2.0 * rec.cosim - 3.0 * cosisq);
            const double f441 = 35.0 * sini2 * f220;
            const double f442 = 39.3750 * sini2 * sini2;
            const double f522 = 9.84375 * rec.sinim *
                (sini2 * (1.0 - 2.0 * rec.cosim - 5.0 * cosisq) +
                 0.33333333 * (-2.0 + 4.0 * rec.cosim + 6.0 * cosisq));
            const double f523 = rec.sinim *
                (4.92187512 * sini2 * (-2.0 - 4.0 * rec.cosim + 10.0 * cosisq) +
                 6.56250012 * (1.0 + 2.0 * rec.cosim - 3.0 * cosisq));
            const double f542 = 29.53125 * rec.sinim *
                (2.0 - 8.0 * rec.cosim + cosisq * (-12.0 + 8.0 * rec.cosim + 10.0 * cosisq));
            const double f543 = 29.53125 * rec.sinim *
                (-2.0 - 8.0 * rec.cosim + cosisq * (12.0 + 8.0 * rec.cosim - 10.0 * cosisq));
            const double xno2 = rec.nm * rec.nm;
            const double ainv2 = aonv * aonv;
            double temp1 = 3.0 * xno2 * ainv2;
            double temp = temp1 * root22;
            rec.d2201 = temp * f220 * g201;
            rec.d2211 = temp * f221 * g211;
            temp1 *= aonv;
            temp = temp1 * root32;
            rec.d3210 = temp * f321 * g310;
            rec.d3222 = temp * f322 * g322;
            temp1 *= aonv;
            temp = 2.0 * temp1 * root44;
            rec.d4410 = temp * f441 * g410;
            rec.d4422 = temp * f442 * g422;
            temp1 *= aonv;
            temp = temp1 * root52;
            rec.d5220 = temp * f522 * g520;
            rec.d5232 = temp * f523 * g532;
            temp = 2.0 * temp1 * root54;
            rec.d5421 = temp * f542 * g521;
            rec.d5433 = temp * f543 * g533;
            rec.xlamo = std::fmod(rec.mo + 2.0 * rec.nodeo - 2.0 * theta, kSgp4TwoPi);
            rec.xfact = rec.mdot + rec.dmdt + 2.0 * (rec.nodedot + rec.dnodt - rptim) - rec.no_unkozai;
            rec.em = emo;
            rec.emsq = emsqo;
        }
        if (rec.irez == 1) {
            const double g200 = 1.0 + rec.emsq * (-2.5 + 0.8125 * rec.emsq);
            const double g310 = 1.0 + 2.0 * rec.emsq;
            const double g300 = 1.0 + rec.emsq * (-6.0 + 6.60937 * rec.emsq);
            const double f220 = 0.75 * (1.0 + rec.cosim) * (1.0 + rec.cosim);
            const double f311 = 0.9375 * rec.sinim * rec.sinim * (1.0 + 3.0 * rec.cosim) -
                                0.75 * (1.0 + rec.cosim);
            double f330 = 1.0 + rec.cosim;
            f330 = 1.875 * f330 * f330 * f330;
            rec.del1 = 3.0 * rec.nm * rec.nm * aonv * aonv;
            rec.del2 = 2.0 * rec.del1 * f220 * g200 * q22;
            rec.del3 = 3.0 * rec.del1 * f330 * g300 * q33 * aonv;
            rec.del1 = rec.del1 * f311 * g310 * q31 * aonv;
            rec.xlamo = std::fmod(rec.mo + rec.nodeo + rec.argpo - theta, kSgp4TwoPi);
            rec.xfact = rec.mdot + xpidot - rptim + rec.dmdt + rec.domdt + rec.dnodt - rec.no_unkozai;
        }
        rec.xli = rec.xlamo;
        rec.xni = rec.no_unkozai;
        rec.atime = 0.0;
        rec.nm = rec.no_unkozai + rec.dndt;
    }
}

} // namespace

void sgp4_get_gravity_constants(int whichconst, Sgp4Record& rec) {
    rec.whichconst = whichconst;
    switch (whichconst) {
    case kSgp4Wgs72Old:
        rec.mu = 398600.79964;
        rec.radiusearthkm = 6378.135;
        rec.xke = 0.0743669161;
        rec.tumin = 1.0 / rec.xke;
        rec.j2 = 0.001082616;
        rec.j3 = -0.00000253881;
        rec.j4 = -0.00000165597;
        rec.j3oj2 = rec.j3 / rec.j2;
        break;
    case kSgp4Wgs72:
        rec.mu = 398600.8;
        rec.radiusearthkm = 6378.135;
        rec.xke = 60.0 / std::sqrt(rec.radiusearthkm * rec.radiusearthkm * rec.radiusearthkm / rec.mu);
        rec.tumin = 1.0 / rec.xke;
        rec.j2 = 0.001082616;
        rec.j3 = -0.00000253881;
        rec.j4 = -0.00000165597;
        rec.j3oj2 = rec.j3 / rec.j2;
        break;
    case kSgp4Wgs84:
    default:
        rec.mu = 398600.5;
        rec.radiusearthkm = 6378.137;
        rec.xke = 60.0 / std::sqrt(rec.radiusearthkm * rec.radiusearthkm * rec.radiusearthkm / rec.mu);
        rec.tumin = 1.0 / rec.xke;
        rec.j2 = 0.00108262998905;
        rec.j3 = -0.00000253215306;
        rec.j4 = -0.00000161098761;
        rec.j3oj2 = rec.j3 / rec.j2;
        break;
    }
}

double sgp4_gstime(double jdut1) {
    const double tut1 = (jdut1 - 2451545.0) / 36525.0;
    double value = -6.2e-6 * tut1 * tut1 * tut1 + 0.093104 * tut1 * tut1 +
                   (876600.0 * 3600.0 + 8640184.812866) * tut1 + 67310.54841;
    value = std::fmod(value * kSgp4DegToRad / 240.0, kSgp4TwoPi);
    if (value < 0.0) value += kSgp4TwoPi;
    return value;
}

void sgp4_jday(int year, int month, int day, int hour, int minute, double second,
               double& jd, double& jd_fraction) {
    jd = 367.0 * year -
         std::floor((7.0 * (year + std::floor((month + 9.0) / 12.0))) * 0.25) +
         std::floor(275.0 * month / 9.0) + day + 1721013.5;
    jd_fraction = (second + minute * 60.0 + hour * 3600.0) / 86400.0;
    if (std::fabs(jd_fraction) > 1.0) {
        const double whole = std::floor(jd_fraction);
        jd += whole;
        jd_fraction -= whole;
    }
}

bool sgp4_initialize(Sgp4Record& rec, char operation_mode) {
    constexpr double temp4 = 1.5e-12;
    rec.isimp = 0;
    rec.method = 'n';
    rec.aycof = rec.con41 = rec.cc1 = rec.cc4 = rec.cc5 = 0.0;
    rec.d2 = rec.d3 = rec.d4 = rec.delmo = rec.eta = 0.0;
    rec.argpdot = rec.omgcof = rec.sinmao = rec.t = 0.0;
    rec.t2cof = rec.t3cof = rec.t4cof = rec.t5cof = 0.0;
    rec.x1mth2 = rec.x7thm1 = rec.mdot = rec.nodedot = 0.0;
    rec.xlcof = rec.xmcof = rec.nodecf = 0.0;
    rec.irez = 0;
    rec.d2201 = rec.d2211 = rec.d3210 = rec.d3222 = 0.0;
    rec.d4410 = rec.d4422 = rec.d5220 = rec.d5232 = 0.0;
    rec.d5421 = rec.d5433 = rec.dedt = rec.del1 = rec.del2 = rec.del3 = 0.0;
    rec.didt = rec.dmdt = rec.dnodt = rec.domdt = 0.0;
    rec.e3 = rec.ee2 = rec.peo = rec.pgho = rec.pho = rec.pinco = rec.plo = 0.0;
    rec.se2 = rec.se3 = rec.sgh2 = rec.sgh3 = rec.sgh4 = 0.0;
    rec.sh2 = rec.sh3 = rec.si2 = rec.si3 = rec.sl2 = rec.sl3 = rec.sl4 = 0.0;
    rec.gsto = rec.xfact = rec.xgh2 = rec.xgh3 = rec.xgh4 = 0.0;
    rec.xh2 = rec.xh3 = rec.xi2 = rec.xi3 = rec.xl2 = rec.xl3 = rec.xl4 = 0.0;
    rec.xlamo = rec.zmol = rec.zmos = rec.atime = rec.xli = rec.xni = 0.0;

    sgp4_get_gravity_constants(rec.whichconst, rec);
    rec.error = 0;
    rec.operationmode = operation_mode;
    rec.am = rec.em = rec.im = rec.Om = rec.om = rec.mm = rec.nm = 0.0;
    const double ss = 78.0 / rec.radiusearthkm + 1.0;
    const double qzms2ttemp = (120.0 - 78.0) / rec.radiusearthkm;
    const double qzms2t = qzms2ttemp * qzms2ttemp * qzms2ttemp * qzms2ttemp;
    constexpr double x2o3 = 2.0 / 3.0;
    rec.init = 'y';
    rec.t = 0.0;
    const double epoch = rec.jdsatepoch + rec.jdsatepochF - 2433281.5;
    sgp4_initl(epoch, rec);
    rec.am = rec.em = rec.im = rec.Om = rec.om = rec.mm = rec.nm = 0.0;
    rec.error = 0;

    if (rec.omeosq >= 0.0 || rec.no_unkozai >= 0.0) {
        rec.isimp = rec.rp < (220.0 / rec.radiusearthkm + 1.0) ? 1 : 0;
        double sfour = ss;
        double qzms24 = qzms2t;
        const double perige = (rec.rp - 1.0) * rec.radiusearthkm;
        if (perige < 156.0) {
            sfour = perige - 78.0;
            if (perige < 98.0) sfour = 20.0;
            const double qzms24temp = (120.0 - sfour) / rec.radiusearthkm;
            qzms24 = qzms24temp * qzms24temp * qzms24temp * qzms24temp;
            sfour = sfour / rec.radiusearthkm + 1.0;
        }
        const double pinvsq = 1.0 / rec.posq;
        const double tsi = 1.0 / (rec.ao - sfour);
        rec.eta = rec.ao * rec.ecco * tsi;
        const double etasq = rec.eta * rec.eta;
        const double eeta = rec.ecco * rec.eta;
        const double psisq = std::fabs(1.0 - etasq);
        const double coef = qzms24 * std::pow(tsi, 4.0);
        const double coef1 = coef / std::pow(psisq, 3.5);
        const double cc2 = coef1 * rec.no_unkozai *
            (rec.ao * (1.0 + 1.5 * etasq + eeta * (4.0 + etasq)) +
             0.375 * rec.j2 * tsi / psisq * rec.con41 *
             (8.0 + 3.0 * etasq * (8.0 + etasq)));
        rec.cc1 = rec.bstar * cc2;
        double cc3 = 0.0;
        if (rec.ecco > 1.0e-4) {
            cc3 = -2.0 * coef * tsi * rec.j3oj2 * rec.no_unkozai * rec.sinio / rec.ecco;
        }
        rec.x1mth2 = 1.0 - rec.cosio2;
        rec.cc4 = 2.0 * rec.no_unkozai * coef1 * rec.ao * rec.omeosq *
            (rec.eta * (2.0 + 0.5 * etasq) + rec.ecco * (0.5 + 2.0 * etasq) -
             rec.j2 * tsi / (rec.ao * psisq) *
             (-3.0 * rec.con41 * (1.0 - 2.0 * eeta + etasq * (1.5 - 0.5 * eeta)) +
              0.75 * rec.x1mth2 * (2.0 * etasq - eeta * (1.0 + etasq)) *
              std::cos(2.0 * rec.argpo)));
        rec.cc5 = 2.0 * coef1 * rec.ao * rec.omeosq *
            (1.0 + 2.75 * (etasq + eeta) + eeta * etasq);
        const double cosio4 = rec.cosio2 * rec.cosio2;
        const double temp1 = 1.5 * rec.j2 * pinvsq * rec.no_unkozai;
        const double temp2 = 0.5 * temp1 * rec.j2 * pinvsq;
        const double temp3 = -0.46875 * rec.j4 * pinvsq * pinvsq * rec.no_unkozai;
        rec.mdot = rec.no_unkozai + 0.5 * temp1 * rec.rteosq * rec.con41 +
                   0.0625 * temp2 * rec.rteosq *
                   (13.0 - 78.0 * rec.cosio2 + 137.0 * cosio4);
        rec.argpdot = -0.5 * temp1 * rec.con42 +
                      0.0625 * temp2 * (7.0 - 114.0 * rec.cosio2 + 395.0 * cosio4) +
                      temp3 * (3.0 - 36.0 * rec.cosio2 + 49.0 * cosio4);
        const double xhdot1 = -temp1 * rec.cosio;
        rec.nodedot = xhdot1 +
            (0.5 * temp2 * (4.0 - 19.0 * rec.cosio2) +
             2.0 * temp3 * (3.0 - 7.0 * rec.cosio2)) * rec.cosio;
        const double xpidot = rec.argpdot + rec.nodedot;
        rec.omgcof = rec.bstar * cc3 * std::cos(rec.argpo);
        rec.xmcof = rec.ecco > 1.0e-4 ? -x2o3 * coef * rec.bstar / eeta : 0.0;
        rec.nodecf = 3.5 * rec.omeosq * xhdot1 * rec.cc1;
        rec.t2cof = 1.5 * rec.cc1;
        const double denominator = std::fabs(rec.cosio + 1.0) > temp4
            ? 1.0 + rec.cosio : temp4;
        rec.xlcof = -0.25 * rec.j3oj2 * rec.sinio * (3.0 + 5.0 * rec.cosio) / denominator;
        rec.aycof = -0.5 * rec.j3oj2 * rec.sinio;
        const double delmotemp = 1.0 + rec.eta * std::cos(rec.mo);
        rec.delmo = delmotemp * delmotemp * delmotemp;
        rec.sinmao = std::sin(rec.mo);
        rec.x7thm1 = 7.0 * rec.cosio2 - 1.0;

        if ((2.0 * kSgp4Pi / rec.no_unkozai) >= 225.0) {
            rec.method = 'd';
            rec.isimp = 1;
            rec.inclm = rec.inclo;
            sgp4_dscom(epoch, rec.ecco, rec.argpo, 0.0, rec.inclo,
                       rec.nodeo, rec.no_unkozai, rec);
            // Deep-space periodics are constructed to be zero at epoch.
            rec.argpm = rec.nodem = rec.mm = 0.0;
            sgp4_dsinit(0.0, xpidot, rec);
        }

        if (rec.isimp != 1) {
            const double cc1sq = rec.cc1 * rec.cc1;
            rec.d2 = 4.0 * rec.ao * tsi * cc1sq;
            const double temp = rec.d2 * tsi * rec.cc1 / 3.0;
            rec.d3 = (17.0 * rec.ao + sfour) * temp;
            rec.d4 = 0.5 * temp * rec.ao * tsi * (221.0 * rec.ao + 31.0 * sfour) * rec.cc1;
            rec.t3cof = rec.d2 + 2.0 * cc1sq;
            rec.t4cof = 0.25 * (3.0 * rec.d3 + rec.cc1 * (12.0 * rec.d2 + 10.0 * cc1sq));
            rec.t5cof = 0.2 * (3.0 * rec.d4 + 12.0 * rec.cc1 * rec.d3 +
                               6.0 * rec.d2 * rec.d2 +
                               15.0 * cc1sq * (2.0 * rec.d2 + cc1sq));
        }
    }

    double position[3]{};
    double velocity[3]{};
    int error = 0;
    const bool ok = sgp4_propagate_immutable(rec, 0.0, position, velocity, &error);
    rec.error = error;
    rec.init = 'n';
    return ok;
}

bool sgp4_propagate_mutable(Sgp4Record& record, double minutes_since_epoch,
                            double position_km[3], double velocity_km_s[3]) {
    const bool ok = sgp4_propagate_immutable(record, minutes_since_epoch,
                                             position_km, velocity_km_s,
                                             &record.error);
    record.t = minutes_since_epoch;
    return ok;
}

Sgp4Record initialize_sgp4_record(const Sgp4SeedDisk& seed, int gravity_model) {
    Sgp4Record record{};
    record.whichconst = gravity_model;
    record.jdsatepoch = std::floor(seed.epoch_julian_date - 0.5) + 0.5;
    record.jdsatepochF = seed.epoch_julian_date - record.jdsatepoch;
    record.bstar = seed.bstar;
    record.ndot = seed.mean_motion_dot_rad_min2;
    record.nddot = seed.mean_motion_ddot_rad_min3;
    record.inclo = seed.inclination_rad;
    record.nodeo = seed.raan_rad;
    record.ecco = seed.eccentricity;
    record.argpo = seed.argument_perigee_rad;
    record.mo = seed.mean_anomaly_rad;
    record.no_kozai = seed.mean_motion_rad_min;
    if (!sgp4_initialize(record, 'i') && record.error != 0) {
        throw std::runtime_error("SGP4 initialization failed for NORAD " +
                                 std::to_string(seed.norad_id) +
                                 " with error " + std::to_string(record.error));
    }
    return record;
}

std::vector<Sgp4Record> compile_sgp4_records(const Sgp4Data& data) {
    validate_sgp4_data(data, false);
    std::vector<Sgp4Record> records;
    records.reserve(data.seeds.size());
    for (const Sgp4SeedDisk& seed : data.seeds) {
        records.push_back(initialize_sgp4_record(seed, static_cast<int>(data.header.gravity_model)));
    }
    return records;
}

Sgp4GroundStation make_sgp4_ground_station(
    double latitude_degrees,
    double longitude_degrees,
    double altitude_km,
    double elevation_mask_degrees,
    double crossing_band_degrees,
    double maximum_slant_range_km,
    std::uint32_t route_filter) {
    if (!std::isfinite(latitude_degrees) || latitude_degrees < -90.0 ||
        latitude_degrees > 90.0 || !std::isfinite(longitude_degrees) ||
        !std::isfinite(altitude_km) || altitude_km < -10.0 ||
        !std::isfinite(elevation_mask_degrees) || elevation_mask_degrees <= -90.0 ||
        elevation_mask_degrees >= 90.0 || !std::isfinite(crossing_band_degrees) ||
        crossing_band_degrees <= 0.0 || !std::isfinite(maximum_slant_range_km) ||
        maximum_slant_range_km <= 0.0) {
        throw std::invalid_argument("invalid full-SGP4 ground-station parameters");
    }

    constexpr double equatorial_radius_km = 6378.137;
    constexpr double flattening = 1.0 / 298.257223563;
    constexpr double eccentricity_squared = flattening * (2.0 - flattening);
    const double latitude = latitude_degrees * kSgp4DegToRad;
    const double longitude = longitude_degrees * kSgp4DegToRad;
    const double sin_lat = std::sin(latitude);
    const double cos_lat = std::cos(latitude);
    const double sin_lon = std::sin(longitude);
    const double cos_lon = std::cos(longitude);
    const double prime_vertical = equatorial_radius_km /
        std::sqrt(1.0 - eccentricity_squared * sin_lat * sin_lat);

    Sgp4GroundStation station{};
    station.ecef_km[0] = (prime_vertical + altitude_km) * cos_lat * cos_lon;
    station.ecef_km[1] = (prime_vertical + altitude_km) * cos_lat * sin_lon;
    station.ecef_km[2] = (prime_vertical * (1.0 - eccentricity_squared) + altitude_km) * sin_lat;
    station.up_unit[0] = cos_lat * cos_lon;
    station.up_unit[1] = cos_lat * sin_lon;
    station.up_unit[2] = sin_lat;
    station.elevation_mask_sin = std::sin(elevation_mask_degrees * kSgp4DegToRad);
    const double band_limit = std::min(89.999999, elevation_mask_degrees + crossing_band_degrees);
    station.crossing_band_sin = std::max(
        std::fabs(std::sin(band_limit * kSgp4DegToRad) - station.elevation_mask_sin),
        1.0e-12);
    station.maximum_slant_range_km = maximum_slant_range_km;
    station.route_filter = route_filter;
    return station;
}

Sgp4Data pack_omm_csv_sgp4(const std::filesystem::path& csv_path,
                           const Sgp4PackOptions& options) {
    require_little_endian();
    if (!(options.horizon_seconds > 0.0) || !(options.step_seconds > 0.0) ||
        !(options.tile_seconds > 0.0) || !std::isfinite(options.horizon_seconds) ||
        !std::isfinite(options.step_seconds) || !std::isfinite(options.tile_seconds) ||
        !std::isfinite(options.elevation_mask_degrees) ||
        !std::isfinite(options.dut1_seconds)) {
        throw std::invalid_argument("invalid KSGP1 packing options");
    }
    if (options.gravity_model != kSgp4Wgs72Old &&
        options.gravity_model != kSgp4Wgs72 &&
        options.gravity_model != kSgp4Wgs84) {
        throw std::invalid_argument("invalid SGP4 gravity model");
    }

    const std::string source = read_binary_text(csv_path);
    const std::vector<OmmSgp4Row> rows = parse_omm_rows(source);
    // Use the newest element epoch as the timeline reference. The source
    // records retain their individual epochs, so propagation remains exact,
    // while a positive timeline describes the useful forward horizon of the
    // freshest source snapshot rather than beginning at the stalest record.
    const auto reference_iterator = std::max_element(
        rows.begin(), rows.end(), [](const OmmSgp4Row& left, const OmmSgp4Row& right) {
            return left.epoch_microseconds < right.epoch_microseconds;
        });
    const std::int64_t reference_us = reference_iterator->epoch_microseconds;
    const double reference_unix_seconds = static_cast<double>(reference_us) / 1.0e6;

    Sgp4Data data{};
    std::memcpy(data.header.magic, kSgp4Magic.data(), kSgp4Magic.size());
    data.header.version = kSgp4ContainerVersion;
    data.header.flags = kSgp4FlagHashLinked | kSgp4FlagStringTable |
                        kSgp4FlagOmmSource | kSgp4FlagFullModel |
                        kSgp4FlagTimeline | kSgp4FlagTeme;
    if (options.gravity_model == kSgp4Wgs72) data.header.flags |= kSgp4FlagWgs72;
    data.header.predictor_model = kSgp4ModelVallado2006;
    data.header.source_bytes = source.size();
    data.header.source_hash = fnv1a64(source.data(), source.size());
    data.header.reference_unix_microseconds = reference_us;
    data.header.reference_julian_date = unix_microseconds_to_julian(reference_us);
    data.header.timeline_start_seconds = 0.0;
    data.header.timeline_step_seconds = options.step_seconds;
    data.header.timeline_duration_seconds = options.horizon_seconds;
    data.header.timeline_sample_count = static_cast<std::uint64_t>(
        std::floor(options.horizon_seconds / options.step_seconds + 1.0e-12)) + 1u;
    data.header.source_format = kSgp4SourceOmmCsv;
    data.header.gravity_model = static_cast<std::uint32_t>(options.gravity_model);
    data.header.default_elevation_mask_rad = options.elevation_mask_degrees * kSgp4DegToRad;
    data.header.default_dut1_seconds = options.dut1_seconds;
    std::snprintf(data.header.source_name, sizeof(data.header.source_name), "%s", "CelesTrak OMM CSV / full SGP4");
    data.strings.push_back('\0');

    constexpr double xpdotp = 1440.0 / kSgp4TwoPi;
    data.seeds.reserve(rows.size());
    for (std::size_t index = 0; index < rows.size(); ++index) {
        const OmmSgp4Row& row = rows[index];
        Sgp4SeedDisk seed{};
        seed.norad_id = row.norad_id;
        seed.lineage_seed = mix32(options.seed ^ row.norad_id ^ static_cast<std::uint32_t>(index));
        seed.name_offset = append_string(data.strings, row.object_name);
        seed.object_id_offset = append_string(data.strings, row.object_id);
        seed.element_set_no = row.element_set_no;
        seed.revolution_number = row.revolution_number;
        const std::uint8_t route = static_cast<std::uint8_t>(
            std::min(5, static_cast<int>(std::floor(
                std::fmod(row.raan_deg < 0.0 ? row.raan_deg + 360.0 : row.raan_deg, 360.0) / 60.0))));
        seed.packed_meta = static_cast<std::uint32_t>(row.prn) |
                           (static_cast<std::uint32_t>(route) << 16u) |
                           (static_cast<std::uint32_t>(static_cast<unsigned char>(row.classification)) << 24u);
        seed.packed_flags = row.ephemeris_type & 0xffu;
        seed.epoch_julian_date = unix_microseconds_to_julian(row.epoch_microseconds);
        seed.epoch_unix_seconds = static_cast<double>(row.epoch_microseconds) / 1.0e6;
        seed.bstar = row.bstar;
        seed.mean_motion_dot_rad_min2 = row.mean_motion_dot_rev_day2 / (xpdotp * 1440.0);
        seed.mean_motion_ddot_rad_min3 = row.mean_motion_ddot_rev_day3 /
                                         (xpdotp * 1440.0 * 1440.0);
        seed.inclination_rad = row.inclination_deg * kSgp4DegToRad;
        seed.raan_rad = row.raan_deg * kSgp4DegToRad;
        seed.eccentricity = row.eccentricity;
        seed.argument_perigee_rad = row.argument_perigee_deg * kSgp4DegToRad;
        seed.mean_anomaly_rad = row.mean_anomaly_deg * kSgp4DegToRad;
        seed.mean_motion_rad_min = row.mean_motion_rev_day / xpdotp;
        seed.reserved_double = reference_unix_seconds;
        data.seeds.push_back(seed);
    }

    const std::uint64_t node_count = static_cast<std::uint64_t>(
        std::ceil(options.horizon_seconds / options.tile_seconds));
    data.nodes.reserve(static_cast<std::size_t>(node_count));
    std::uint64_t parent_hash = 0u;
    for (std::uint64_t index = 0; index < node_count; ++index) {
        Sgp4TimelineNodeDisk node{};
        node.parent_index = index == 0u ? kSgp4NoParent : static_cast<std::uint32_t>(index - 1u);
        node.node_index = static_cast<std::uint32_t>(index);
        node.flags = kSgp4NodeTimelineTile | (index == 0u ? kSgp4NodeCheckpoint : 0u);
        node.chain_seed = mix32(options.seed ^ static_cast<std::uint32_t>(index) ^ 0x9e3779b9u);
        node.start_seconds = static_cast<double>(index) * options.tile_seconds;
        node.duration_seconds = std::min(options.tile_seconds,
            options.horizon_seconds - node.start_seconds);
        node.parent_hash = parent_hash;
        node.source_hash = data.header.source_hash;
        const long double begin = static_cast<long double>(node.start_seconds / options.step_seconds);
        const long double count = static_cast<long double>(node.duration_seconds / options.step_seconds);
        node.sample_begin = static_cast<std::uint32_t>(std::min<long double>(
            begin, std::numeric_limits<std::uint32_t>::max()));
        node.sample_count = static_cast<std::uint32_t>(std::min<long double>(
            std::ceil(count), std::numeric_limits<std::uint32_t>::max()));
        node.self_hash = hash_node(node);
        parent_hash = node.self_hash;
        data.nodes.push_back(node);
    }

    initialize_offsets(data);
    data.header.chain_hash = data.nodes.empty() ? 0u : data.nodes.back().self_hash;
    data.header.payload_hash = payload_hash(data);
    validate_sgp4_data(data, true);
    // Compile every record now: packing fails immediately on an invalid mean element set.
    (void)compile_sgp4_records(data);
    return data;
}

void validate_sgp4_data(const Sgp4Data& data, bool verify_hashes) {
    require_little_endian();
    if (std::memcmp(data.header.magic, kSgp4Magic.data(), kSgp4Magic.size()) != 0) {
        throw std::runtime_error("invalid KSGP1 magic");
    }
    if (data.header.version != kSgp4ContainerVersion ||
        data.header.header_bytes != sizeof(Sgp4HeaderDisk) ||
        data.header.seed_bytes != sizeof(Sgp4SeedDisk) ||
        data.header.node_bytes != sizeof(Sgp4TimelineNodeDisk)) {
        throw std::runtime_error("unsupported KSGP1 version or record size");
    }
    if (data.header.predictor_model != kSgp4ModelVallado2006 ||
        data.header.source_format != kSgp4SourceOmmCsv) {
        throw std::runtime_error("unsupported KSGP1 predictor/source model");
    }
    if (data.header.seed_count != data.seeds.size() ||
        data.header.node_count != data.nodes.size() ||
        data.header.strings_bytes != data.strings.size()) {
        throw std::runtime_error("KSGP1 header count mismatch");
    }
    if (data.seeds.empty() || data.nodes.empty() || data.strings.empty() || data.strings.front() != '\0') {
        throw std::runtime_error("KSGP1 requires non-empty seeds, timeline, and string table");
    }
    Sgp4Data copy = data;
    initialize_offsets(copy);
    if (copy.header.seeds_offset != data.header.seeds_offset ||
        copy.header.nodes_offset != data.header.nodes_offset ||
        copy.header.strings_offset != data.header.strings_offset) {
        throw std::runtime_error("KSGP1 offset mismatch");
    }
    for (const Sgp4SeedDisk& seed : data.seeds) {
        if (seed.name_offset >= data.strings.size() || seed.object_id_offset >= data.strings.size() ||
            !(seed.epoch_julian_date > 2400000.0) || !(seed.mean_motion_rad_min > 0.0) ||
            seed.eccentricity < 0.0 || seed.eccentricity >= 1.0) {
            throw std::runtime_error("invalid KSGP1 seed record");
        }
    }
    std::uint64_t parent_hash = 0u;
    for (std::size_t index = 0; index < data.nodes.size(); ++index) {
        const Sgp4TimelineNodeDisk& node = data.nodes[index];
        if (node.node_index != index ||
            node.parent_index != (index == 0u ? kSgp4NoParent : static_cast<std::uint32_t>(index - 1u)) ||
            node.parent_hash != parent_hash || node.source_hash != data.header.source_hash) {
            throw std::runtime_error("KSGP1 timeline linkage mismatch");
        }
        if (verify_hashes && node.self_hash != hash_node(node)) {
            throw std::runtime_error("KSGP1 timeline node hash mismatch");
        }
        parent_hash = node.self_hash;
    }
    if (data.header.chain_hash != data.nodes.back().self_hash) {
        throw std::runtime_error("KSGP1 terminal chain hash mismatch");
    }
    if (verify_hashes && data.header.payload_hash != payload_hash(data)) {
        throw std::runtime_error("KSGP1 payload hash mismatch");
    }
}

void save_sgp4_data(const std::filesystem::path& path, const Sgp4Data& input) {
    require_little_endian();
    Sgp4Data data = input;
    initialize_offsets(data);
    data.header.chain_hash = data.nodes.empty() ? 0u : data.nodes.back().self_hash;
    data.header.payload_hash = payload_hash(data);
    validate_sgp4_data(data, true);
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    if (!output) throw std::runtime_error("unable to create KSGP1 file: " + path.string());
    output.write(reinterpret_cast<const char*>(&data.header), sizeof(data.header));
    output.write(reinterpret_cast<const char*>(data.seeds.data()),
                 static_cast<std::streamsize>(data.seeds.size() * sizeof(Sgp4SeedDisk)));
    output.write(reinterpret_cast<const char*>(data.nodes.data()),
                 static_cast<std::streamsize>(data.nodes.size() * sizeof(Sgp4TimelineNodeDisk)));
    output.write(data.strings.data(), static_cast<std::streamsize>(data.strings.size()));
    if (!output) throw std::runtime_error("failed while writing KSGP1 file: " + path.string());
}

Sgp4Data load_sgp4_data(const std::filesystem::path& path) {
    require_little_endian();
    std::ifstream input(path, std::ios::binary);
    if (!input) throw std::runtime_error("unable to open KSGP1 file: " + path.string());
    input.seekg(0, std::ios::end);
    const std::streamoff end = input.tellg();
    if (end < static_cast<std::streamoff>(sizeof(Sgp4HeaderDisk))) {
        throw std::runtime_error("KSGP1 file is shorter than its header");
    }
    const std::uint64_t file_bytes = static_cast<std::uint64_t>(end);
    input.seekg(0, std::ios::beg);
    Sgp4Data data{};
    input.read(reinterpret_cast<char*>(&data.header), sizeof(data.header));
    if (!input) throw std::runtime_error("failed while reading KSGP1 header");
    if (std::memcmp(data.header.magic, kSgp4Magic.data(), kSgp4Magic.size()) != 0) {
        throw std::runtime_error("invalid KSGP1 magic");
    }
    if (data.header.seed_count > std::numeric_limits<std::size_t>::max() / sizeof(Sgp4SeedDisk) ||
        data.header.node_count > std::numeric_limits<std::size_t>::max() / sizeof(Sgp4TimelineNodeDisk) ||
        data.header.strings_bytes > std::numeric_limits<std::size_t>::max()) {
        throw std::runtime_error("KSGP1 payload is too large for this host");
    }
    const std::uint64_t expected_end = data.header.strings_offset + data.header.strings_bytes;
    if (expected_end != file_bytes) throw std::runtime_error("KSGP1 size/offset mismatch");
    data.seeds.resize(static_cast<std::size_t>(data.header.seed_count));
    data.nodes.resize(static_cast<std::size_t>(data.header.node_count));
    data.strings.resize(static_cast<std::size_t>(data.header.strings_bytes));
    input.seekg(static_cast<std::streamoff>(data.header.seeds_offset), std::ios::beg);
    input.read(reinterpret_cast<char*>(data.seeds.data()),
               static_cast<std::streamsize>(data.seeds.size() * sizeof(Sgp4SeedDisk)));
    input.seekg(static_cast<std::streamoff>(data.header.nodes_offset), std::ios::beg);
    input.read(reinterpret_cast<char*>(data.nodes.data()),
               static_cast<std::streamsize>(data.nodes.size() * sizeof(Sgp4TimelineNodeDisk)));
    input.seekg(static_cast<std::streamoff>(data.header.strings_offset), std::ios::beg);
    input.read(data.strings.data(), static_cast<std::streamsize>(data.strings.size()));
    if (!input) throw std::runtime_error("failed while reading KSGP1 payload");
    validate_sgp4_data(data, true);
    return data;
}

Sgp4Stats inspect_sgp4_data(const Sgp4Data& data, std::uint64_t actual_file_bytes) {
    validate_sgp4_data(data, true);
    Sgp4Stats stats{};
    stats.seed_count = data.seeds.size();
    stats.node_count = data.nodes.size();
    stats.seed_bytes = data.seeds.size() * sizeof(Sgp4SeedDisk);
    stats.node_bytes = data.nodes.size() * sizeof(Sgp4TimelineNodeDisk);
    stats.string_bytes = data.strings.size();
    stats.coefficient_bytes = data.seeds.size() * sizeof(Sgp4Record);
    stats.source_bytes = data.header.source_bytes;
    stats.file_bytes = actual_file_bytes != 0u ? actual_file_bytes :
        sizeof(Sgp4HeaderDisk) + stats.seed_bytes + stats.node_bytes + stats.string_bytes;
    stats.timeline_samples = data.header.timeline_sample_count;
    const long double samples = static_cast<long double>(stats.timeline_samples) *
                                static_cast<long double>(stats.seed_count);
    const long double dense_float4 = samples * 16.0L;
    const long double dense_pv = samples * 48.0L;
    stats.equivalent_dense_float4_bytes = dense_float4 > std::numeric_limits<std::uint64_t>::max()
        ? std::numeric_limits<std::uint64_t>::max() : static_cast<std::uint64_t>(dense_float4);
    stats.equivalent_dense_position_velocity_bytes = dense_pv > std::numeric_limits<std::uint64_t>::max()
        ? std::numeric_limits<std::uint64_t>::max() : static_cast<std::uint64_t>(dense_pv);
    stats.ratio_vs_dense_float4 = stats.file_bytes == 0u ? 0.0 :
        static_cast<double>(dense_float4 / static_cast<long double>(stats.file_bytes));
    stats.ratio_vs_dense_position_velocity = stats.file_bytes == 0u ? 0.0 :
        static_cast<double>(dense_pv / static_cast<long double>(stats.file_bytes));
    return stats;
}

std::string sgp4_string_at(const Sgp4Data& data, std::uint32_t offset) {
    if (offset >= data.strings.size()) throw std::out_of_range("KSGP1 string offset outside table");
    const char* begin = data.strings.data() + offset;
    const char* end = static_cast<const char*>(std::memchr(begin, '\0', data.strings.size() - offset));
    if (end == nullptr) throw std::runtime_error("unterminated KSGP1 string");
    return std::string(begin, end);
}

} // namespace klb
