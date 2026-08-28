#pragma once

#include "klb/core.hpp"
#include "klb/orbit.hpp"

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

namespace klb {

// KSGP1 stores the source mean elements and lineage/timeline metadata.  The
// larger Sgp4Record coefficient state is deterministically compiled at load
// time and is not part of the compressed on-disk payload.
constexpr std::uint32_t kSgp4ContainerVersion = 1u;
constexpr std::uint32_t kSgp4ModelVallado2006 = 2u;
constexpr std::uint32_t kSgp4SourceOmmCsv = 1u;
constexpr std::uint32_t kSgp4NoParent = 0xffffffffu;
constexpr std::uint32_t kSgp4MaxConstantSeeds = 32u;

constexpr std::uint32_t kSgp4FlagHashLinked = 1u << 0u;
constexpr std::uint32_t kSgp4FlagStringTable = 1u << 1u;
constexpr std::uint32_t kSgp4FlagOmmSource = 1u << 2u;
constexpr std::uint32_t kSgp4FlagFullModel = 1u << 3u;
constexpr std::uint32_t kSgp4FlagTimeline = 1u << 4u;
constexpr std::uint32_t kSgp4FlagWgs72 = 1u << 5u;
constexpr std::uint32_t kSgp4FlagTeme = 1u << 6u;

constexpr std::uint32_t kSgp4NodeCheckpoint = 1u << 0u;
constexpr std::uint32_t kSgp4NodeTimelineTile = 1u << 1u;

constexpr int kSgp4Wgs72Old = 1;
constexpr int kSgp4Wgs72 = 2;
constexpr int kSgp4Wgs84 = 3;
constexpr double kSgp4Pi = 3.141592653589793238462643383279502884;
constexpr double kSgp4TwoPi = 2.0 * kSgp4Pi;
constexpr double kSgp4DegToRad = kSgp4Pi / 180.0;
constexpr double kSgp4RadToDeg = 180.0 / kSgp4Pi;

#pragma pack(push, 1)
struct alignas(16) Sgp4SeedDisk {
    std::uint32_t norad_id;
    std::uint32_t lineage_seed;
    std::uint32_t name_offset;
    std::uint32_t object_id_offset;
    std::uint32_t element_set_no;
    std::uint32_t revolution_number;
    std::uint32_t packed_meta;  // prn[15:0], route[23:16], classification[31:24]
    std::uint32_t packed_flags; // ephemeris type[7:0], reserved thereafter

    double epoch_julian_date;
    double epoch_unix_seconds;
    double bstar;
    double mean_motion_dot_rad_min2;
    double mean_motion_ddot_rad_min3;
    double inclination_rad;
    double raan_rad;
    double eccentricity;
    double argument_perigee_rad;
    double mean_anomaly_rad;
    double mean_motion_rad_min;
    double reserved_double;
};

struct alignas(16) Sgp4TimelineNodeDisk {
    std::uint32_t parent_index;
    std::uint32_t node_index;
    std::uint32_t flags;
    std::uint32_t chain_seed;

    double start_seconds;
    double duration_seconds;

    std::uint64_t parent_hash;
    std::uint64_t self_hash;
    std::uint64_t source_hash;

    std::uint32_t sample_begin;
    std::uint32_t sample_count;
};

struct Sgp4HeaderDisk {
    char magic[8];
    std::uint32_t version;
    std::uint32_t header_bytes;

    std::uint32_t flags;
    std::uint32_t seed_bytes;
    std::uint32_t node_bytes;
    std::uint32_t predictor_model;

    std::uint64_t seed_count;
    std::uint64_t node_count;
    std::uint64_t seeds_offset;
    std::uint64_t nodes_offset;
    std::uint64_t strings_offset;
    std::uint64_t strings_bytes;

    std::uint64_t source_bytes;
    std::uint64_t source_hash;
    std::uint64_t payload_hash;
    std::uint64_t chain_hash;

    std::int64_t reference_unix_microseconds;
    double reference_julian_date;
    double timeline_start_seconds;
    double timeline_step_seconds;
    double timeline_duration_seconds;
    std::uint64_t timeline_sample_count;

    std::uint32_t source_format;
    std::uint32_t gravity_model;
    double default_elevation_mask_rad;
    double default_dut1_seconds;

    char source_name[48];
    std::uint8_t reserved[24];
};
#pragma pack(pop)

static_assert(sizeof(Sgp4SeedDisk) == 128u, "KSGP1 seed records must stay 128 bytes");
static_assert(sizeof(Sgp4TimelineNodeDisk) == 64u, "KSGP1 timeline nodes must stay 64 bytes");
static_assert(sizeof(Sgp4HeaderDisk) == 256u, "KSGP1 header must stay 256 bytes");

KLB_HD KLB_INLINE std::uint16_t sgp4_seed_prn(const Sgp4SeedDisk& seed) {
    return static_cast<std::uint16_t>(seed.packed_meta & 0xffffu);
}
KLB_HD KLB_INLINE std::uint8_t sgp4_seed_route(const Sgp4SeedDisk& seed) {
    return static_cast<std::uint8_t>((seed.packed_meta >> 16u) & 0xffu);
}
KLB_HD KLB_INLINE char sgp4_seed_classification(const Sgp4SeedDisk& seed) {
    return static_cast<char>((seed.packed_meta >> 24u) & 0xffu);
}
KLB_HD KLB_INLINE std::uint8_t sgp4_seed_ephemeris_type(const Sgp4SeedDisk& seed) {
    return static_cast<std::uint8_t>(seed.packed_flags & 0xffu);
}

// Mutable initialization/coefficient record based on the Vallado/CSSI SGP4
// state.  Disk identity and text metadata deliberately remain outside it.
struct alignas(16) Sgp4Record {
    int whichconst{};
    int error{};
    char operationmode{'i'};
    char init{'y'};
    char method{'n'};
    char reserved_char{};

    double jdsatepoch{};
    double jdsatepochF{};
    double nddot{};
    double ndot{};
    double bstar{};
    double inclo{};
    double nodeo{};
    double ecco{};
    double argpo{};
    double mo{};
    double no_kozai{};
    double no_unkozai{};

    double am{};
    double em{};
    double im{};
    double Om{};
    double om{};
    double mm{};
    double nm{};
    double t{};

    double tumin{};
    double mu{};
    double radiusearthkm{};
    double xke{};
    double j2{};
    double j3{};
    double j4{};
    double j3oj2{};

    double ep{};
    double inclp{};
    double nodep{};
    double argpp{};
    double mp{};

    int isimp{};
    int irez{};
    double aycof{};
    double con41{};
    double cc1{};
    double cc4{};
    double cc5{};
    double d2{};
    double d3{};
    double d4{};
    double delmo{};
    double eta{};
    double argpdot{};
    double omgcof{};
    double sinmao{};
    double t2cof{};
    double t3cof{};
    double t4cof{};
    double t5cof{};
    double x1mth2{};
    double x7thm1{};
    double mdot{};
    double nodedot{};
    double xlcof{};
    double xmcof{};
    double nodecf{};

    double d2201{};
    double d2211{};
    double d3210{};
    double d3222{};
    double d4410{};
    double d4422{};
    double d5220{};
    double d5232{};
    double d5421{};
    double d5433{};
    double dedt{};
    double del1{};
    double del2{};
    double del3{};
    double didt{};
    double dmdt{};
    double dnodt{};
    double domdt{};
    double e3{};
    double ee2{};
    double peo{};
    double pgho{};
    double pho{};
    double pinco{};
    double plo{};
    double se2{};
    double se3{};
    double sgh2{};
    double sgh3{};
    double sgh4{};
    double sh2{};
    double sh3{};
    double si2{};
    double si3{};
    double sl2{};
    double sl3{};
    double sl4{};
    double gsto{};
    double xfact{};
    double xgh2{};
    double xgh3{};
    double xgh4{};
    double xh2{};
    double xh3{};
    double xi2{};
    double xi3{};
    double xl2{};
    double xl3{};
    double xl4{};
    double xlamo{};
    double zmol{};
    double zmos{};
    double atime{};
    double xli{};
    double xni{};

    double snodm{};
    double cnodm{};
    double sinim{};
    double cosim{};
    double sinomm{};
    double cosomm{};
    double day{};
    double emsq{};
    double gam{};
    double rtemsq{};
    double s1{};
    double s2{};
    double s3{};
    double s4{};
    double s5{};
    double s6{};
    double s7{};
    double ss1{};
    double ss2{};
    double ss3{};
    double ss4{};
    double ss5{};
    double ss6{};
    double ss7{};
    double sz1{};
    double sz2{};
    double sz3{};
    double sz11{};
    double sz12{};
    double sz13{};
    double sz21{};
    double sz22{};
    double sz23{};
    double sz31{};
    double sz32{};
    double sz33{};
    double z1{};
    double z2{};
    double z3{};
    double z11{};
    double z12{};
    double z13{};
    double z21{};
    double z22{};
    double z23{};
    double z31{};
    double z32{};
    double z33{};
    double argpm{};
    double inclm{};
    double nodem{};
    double dndt{};
    double eccsq{};

    double ainv{};
    double ao{};
    double con42{};
    double cosio{};
    double cosio2{};
    double omeosq{};
    double posq{};
    double rp{};
    double rteosq{};
    double sinio{};
};

struct Sgp4Data {
    Sgp4HeaderDisk header{};
    std::vector<Sgp4SeedDisk> seeds;
    std::vector<Sgp4TimelineNodeDisk> nodes;
    std::vector<char> strings;
};

struct Sgp4PackOptions {
    double horizon_seconds = 7.0 * 24.0 * 3600.0;
    double step_seconds = 1.0;
    double tile_seconds = 24.0 * 3600.0;
    double elevation_mask_degrees = 10.0;
    double dut1_seconds = 0.0;
    std::uint32_t seed = 0x53475034u;
    int gravity_model = kSgp4Wgs72;
};

struct Sgp4Stats {
    std::uint64_t file_bytes{};
    std::uint64_t source_bytes{};
    std::uint64_t seed_bytes{};
    std::uint64_t node_bytes{};
    std::uint64_t string_bytes{};
    std::uint64_t coefficient_bytes{};
    std::uint64_t seed_count{};
    std::uint64_t node_count{};
    std::uint64_t timeline_samples{};
    std::uint64_t equivalent_dense_float4_bytes{};
    std::uint64_t equivalent_dense_position_velocity_bytes{};
    double ratio_vs_dense_float4{};
    double ratio_vs_dense_position_velocity{};
};

struct Sgp4State {
    double position_teme_km[3]{};
    double velocity_teme_km_s[3]{};
    int error{};
};

struct Sgp4Visibility {
    double guard{};
    double elevation_sin{};
    double slant_range_km{};
    std::uint32_t supported{};
    std::uint32_t compatible{};
};

// Double-precision ground-station query state for the full-SGP4 path.  The
// up vector is the WGS-84 geodetic surface normal, rather than a radial
// geocentric approximation.  This keeps propagation accuracy and frame/query
// accuracy as separate, measurable concerns.
struct alignas(16) Sgp4GroundStation {
    double ecef_km[3]{};
    double up_unit[3]{};
    double elevation_mask_sin{};
    double crossing_band_sin{};
    double maximum_slant_range_km{};
    std::uint32_t route_filter{0xffffffffu};
    std::uint32_t reserved{};
};
static_assert(sizeof(Sgp4GroundStation) == 80u,
              "full-SGP4 station ABI must stay 80 bytes");

struct Sgp4Crossing {
    std::uint32_t verified{};
    std::uint32_t acquisition{};
    double interpolation{};
    double crossing_seconds{};
    double minimum_abs_guard{};
};

struct Sgp4ErrorStats {
    std::uint64_t samples{};
    std::uint64_t failures{};
    double rms_position_km{};
    double max_position_km{};
    double rms_velocity_km_s{};
    double max_velocity_km_s{};
};

Sgp4Data pack_omm_csv_sgp4(const std::filesystem::path& csv_path, const Sgp4PackOptions& options = {});
void validate_sgp4_data(const Sgp4Data& data, bool verify_hashes = true);
void save_sgp4_data(const std::filesystem::path& path, const Sgp4Data& data);
Sgp4Data load_sgp4_data(const std::filesystem::path& path);
Sgp4Stats inspect_sgp4_data(const Sgp4Data& data, std::uint64_t actual_file_bytes = 0u);
std::string sgp4_string_at(const Sgp4Data& data, std::uint32_t offset);
std::vector<Sgp4Record> compile_sgp4_records(const Sgp4Data& data);
Sgp4Record initialize_sgp4_record(const Sgp4SeedDisk& seed, int gravity_model = kSgp4Wgs72);
Sgp4GroundStation make_sgp4_ground_station(
    double latitude_degrees,
    double longitude_degrees,
    double altitude_km,
    double elevation_mask_degrees,
    double crossing_band_degrees,
    double maximum_slant_range_km = 50000.0,
    std::uint32_t route_filter = 0xffffffffu);

// Mutable host reference functions used by initialization and independent
// verification.  The GPU-facing function below uses an immutable coefficient
// record and local work state.
void sgp4_get_gravity_constants(int whichconst, Sgp4Record& record);
double sgp4_gstime(double jdut1);
void sgp4_jday(int year, int month, int day, int hour, int minute, double second,
               double& jd, double& jd_fraction);
bool sgp4_initialize(Sgp4Record& record, char operation_mode = 'i');
bool sgp4_propagate_mutable(Sgp4Record& record, double minutes_since_epoch,
                            double position_km[3], double velocity_km_s[3]);

KLB_HD KLB_INLINE double sgp4_abs(double value) { return value < 0.0 ? -value : value; }
KLB_HD KLB_INLINE double sgp4_mod(double value, double modulus) { return ::fmod(value, modulus); }

struct Sgp4Work {
    double t{};
    double argpm{};
    double mm{};
    double nodem{};
    double nm{};
    double em{};
    double inclm{};
    double am{};
    double emsq{};
    double sinim{};
    double cosim{};
    double ep{};
    double inclp{};
    double argpp{};
    double nodep{};
    double mp{};
    double aycof{};
    double xlcof{};
    double con41{};
    double x1mth2{};
    double x7thm1{};
    double atime{};
    double xli{};
    double xni{};
    double dndt{};
    int error{};
};

KLB_HD KLB_INLINE void sgp4_dpper_immutable(
    const Sgp4Record& rec,
    char init,
    Sgp4Work& work) {
    constexpr double zns = 1.19459e-5;
    constexpr double zes = 0.01675;
    constexpr double znl = 1.5835218e-4;
    constexpr double zel = 0.05490;

    double zm = rec.zmos + zns * work.t;
    if (init == 'y') zm = rec.zmos;
    double zf = zm + 2.0 * zes * ::sin(zm);
    double sinzf = ::sin(zf);
    double f2 = 0.5 * sinzf * sinzf - 0.25;
    double f3 = -0.5 * sinzf * ::cos(zf);
    const double ses = rec.se2 * f2 + rec.se3 * f3;
    const double sis = rec.si2 * f2 + rec.si3 * f3;
    const double sls = rec.sl2 * f2 + rec.sl3 * f3 + rec.sl4 * sinzf;
    const double sghs = rec.sgh2 * f2 + rec.sgh3 * f3 + rec.sgh4 * sinzf;
    const double shs = rec.sh2 * f2 + rec.sh3 * f3;

    zm = rec.zmol + znl * work.t;
    if (init == 'y') zm = rec.zmol;
    zf = zm + 2.0 * zel * ::sin(zm);
    sinzf = ::sin(zf);
    f2 = 0.5 * sinzf * sinzf - 0.25;
    f3 = -0.5 * sinzf * ::cos(zf);
    const double sel = rec.ee2 * f2 + rec.e3 * f3;
    const double sil = rec.xi2 * f2 + rec.xi3 * f3;
    const double sll = rec.xl2 * f2 + rec.xl3 * f3 + rec.xl4 * sinzf;
    const double sghl = rec.xgh2 * f2 + rec.xgh3 * f3 + rec.xgh4 * sinzf;
    const double shll = rec.xh2 * f2 + rec.xh3 * f3;

    double pe = ses + sel;
    double pinc = sis + sil;
    double pl = sls + sll;
    double pgh = sghs + sghl;
    double ph = shs + shll;

    if (init == 'n') {
        pe -= rec.peo;
        pinc -= rec.pinco;
        pl -= rec.plo;
        pgh -= rec.pgho;
        ph -= rec.pho;
        work.inclp += pinc;
        work.ep += pe;
        const double sinip = ::sin(work.inclp);
        const double cosip = ::cos(work.inclp);
        if (work.inclp >= 0.2) {
            ph /= sinip;
            pgh -= cosip * ph;
            work.argpp += pgh;
            work.nodep += ph;
            work.mp += pl;
        } else {
            const double sinop = ::sin(work.nodep);
            const double cosop = ::cos(work.nodep);
            double alfdp = sinip * sinop;
            double betdp = sinip * cosop;
            const double dalf = ph * cosop + pinc * cosip * sinop;
            const double dbet = -ph * sinop + pinc * cosip * cosop;
            alfdp += dalf;
            betdp += dbet;
            work.nodep = sgp4_mod(work.nodep, kSgp4TwoPi);
            if (work.nodep < 0.0 && rec.operationmode == 'a') work.nodep += kSgp4TwoPi;
            double xls = work.mp + work.argpp + cosip * work.nodep;
            const double dls = pl + pgh - pinc * work.nodep * sinip;
            xls = sgp4_mod(xls + dls, kSgp4TwoPi);
            const double xnoh = work.nodep;
            work.nodep = ::atan2(alfdp, betdp);
            if (work.nodep < 0.0 && rec.operationmode == 'a') work.nodep += kSgp4TwoPi;
            if (sgp4_abs(xnoh - work.nodep) > kSgp4Pi) {
                work.nodep += work.nodep < xnoh ? kSgp4TwoPi : -kSgp4TwoPi;
            }
            work.mp += pl;
            work.argpp = xls - work.mp - cosip * work.nodep;
        }
    }
}

KLB_HD KLB_INLINE void sgp4_dspace_immutable(
    const Sgp4Record& rec,
    double tc,
    Sgp4Work& work) {
    constexpr double fasx2 = 0.13130908;
    constexpr double fasx4 = 2.8843198;
    constexpr double fasx6 = 0.37448087;
    constexpr double g22 = 5.7686396;
    constexpr double g32 = 0.95240898;
    constexpr double g44 = 1.8014998;
    constexpr double g52 = 1.0508330;
    constexpr double g54 = 4.4108898;
    constexpr double rptim = 4.37526908801129966e-3;
    constexpr double stepp = 720.0;
    constexpr double stepn = -720.0;
    constexpr double step2 = 259200.0;

    work.dndt = 0.0;
    const double theta = sgp4_mod(rec.gsto + tc * rptim, kSgp4TwoPi);
    work.em += rec.dedt * work.t;
    work.inclm += rec.didt * work.t;
    work.argpm += rec.domdt * work.t;
    work.nodem += rec.dnodt * work.t;
    work.mm += rec.dmdt * work.t;

    if (rec.irez == 0) return;

    work.atime = 0.0;
    work.xni = rec.no_unkozai;
    work.xli = rec.xlamo;
    const double delt = work.t > 0.0 ? stepp : stepn;
    double ft = 0.0;
    double xndt = 0.0;
    double xnddt = 0.0;
    double xldot = 0.0;
    while (true) {
        if (rec.irez != 2) {
            xndt = rec.del1 * ::sin(work.xli - fasx2) +
                    rec.del2 * ::sin(2.0 * (work.xli - fasx4)) +
                    rec.del3 * ::sin(3.0 * (work.xli - fasx6));
            xldot = work.xni + rec.xfact;
            xnddt = rec.del1 * ::cos(work.xli - fasx2) +
                     2.0 * rec.del2 * ::cos(2.0 * (work.xli - fasx4)) +
                     3.0 * rec.del3 * ::cos(3.0 * (work.xli - fasx6));
            xnddt *= xldot;
        } else {
            const double xomi = rec.argpo + rec.argpdot * work.atime;
            const double x2omi = xomi + xomi;
            const double x2li = work.xli + work.xli;
            xndt = rec.d2201 * ::sin(x2omi + work.xli - g22) +
                    rec.d2211 * ::sin(work.xli - g22) +
                    rec.d3210 * ::sin(xomi + work.xli - g32) +
                    rec.d3222 * ::sin(-xomi + work.xli - g32) +
                    rec.d4410 * ::sin(x2omi + x2li - g44) +
                    rec.d4422 * ::sin(x2li - g44) +
                    rec.d5220 * ::sin(xomi + work.xli - g52) +
                    rec.d5232 * ::sin(-xomi + work.xli - g52) +
                    rec.d5421 * ::sin(xomi + x2li - g54) +
                    rec.d5433 * ::sin(-xomi + x2li - g54);
            xldot = work.xni + rec.xfact;
            xnddt = rec.d2201 * ::cos(x2omi + work.xli - g22) +
                     rec.d2211 * ::cos(work.xli - g22) +
                     rec.d3210 * ::cos(xomi + work.xli - g32) +
                     rec.d3222 * ::cos(-xomi + work.xli - g32) +
                     rec.d5220 * ::cos(xomi + work.xli - g52) +
                     rec.d5232 * ::cos(-xomi + work.xli - g52) +
                     2.0 * (rec.d4410 * ::cos(x2omi + x2li - g44) +
                            rec.d4422 * ::cos(x2li - g44) +
                            rec.d5421 * ::cos(xomi + x2li - g54) +
                            rec.d5433 * ::cos(-xomi + x2li - g54));
            xnddt *= xldot;
        }
        if (sgp4_abs(work.t - work.atime) < stepp) {
            ft = work.t - work.atime;
            break;
        }
        work.xli += xldot * delt + xndt * step2;
        work.xni += xndt * delt + xnddt * step2;
        work.atime += delt;
    }

    work.nm = work.xni + xndt * ft + xnddt * ft * ft * 0.5;
    const double xl = work.xli + xldot * ft + xndt * ft * ft * 0.5;
    if (rec.irez != 1) {
        work.mm = xl - 2.0 * work.nodem + 2.0 * theta;
    } else {
        work.mm = xl - work.nodem - work.argpm + theta;
    }
    work.dndt = work.nm - rec.no_unkozai;
    work.nm = rec.no_unkozai + work.dndt;
}

KLB_HD KLB_INLINE bool sgp4_propagate_immutable(
    const Sgp4Record& rec,
    double minutes_since_epoch,
    double position_km[3],
    double velocity_km_s[3],
    int* error_out = nullptr) {
    constexpr double x2o3 = 2.0 / 3.0;
    constexpr double temp4 = 1.5e-12;
    Sgp4Work work{};
    work.t = minutes_since_epoch;
    work.error = 0;
    work.aycof = rec.aycof;
    work.xlcof = rec.xlcof;
    work.con41 = rec.con41;
    work.x1mth2 = rec.x1mth2;
    work.x7thm1 = rec.x7thm1;

    const double vkmpersec = rec.radiusearthkm * rec.xke / 60.0;
    const double xmdf = rec.mo + rec.mdot * work.t;
    const double argpdf = rec.argpo + rec.argpdot * work.t;
    const double nodedf = rec.nodeo + rec.nodedot * work.t;
    work.argpm = argpdf;
    work.mm = xmdf;
    const double t2 = work.t * work.t;
    work.nodem = nodedf + rec.nodecf * t2;
    double tempa = 1.0 - rec.cc1 * work.t;
    double tempe = rec.bstar * rec.cc4 * work.t;
    double templ = rec.t2cof * t2;

    if (rec.isimp != 1) {
        const double delomg = rec.omgcof * work.t;
        const double delmtemp = 1.0 + rec.eta * ::cos(xmdf);
        const double delm = rec.xmcof * (delmtemp * delmtemp * delmtemp - rec.delmo);
        const double temp = delomg + delm;
        work.mm = xmdf + temp;
        work.argpm = argpdf - temp;
        const double t3 = t2 * work.t;
        const double t4 = t3 * work.t;
        tempa -= rec.d2 * t2 + rec.d3 * t3 + rec.d4 * t4;
        tempe += rec.bstar * rec.cc5 * (::sin(work.mm) - rec.sinmao);
        templ += rec.t3cof * t3 + t4 * (rec.t4cof + work.t * rec.t5cof);
    }

    work.nm = rec.no_unkozai;
    work.em = rec.ecco;
    work.inclm = rec.inclo;
    if (rec.method == 'd') sgp4_dspace_immutable(rec, work.t, work);
    if (work.nm <= 0.0) {
        work.error = 2;
        if (error_out) *error_out = work.error;
        return false;
    }

    work.am = ::pow(rec.xke / work.nm, x2o3) * tempa * tempa;
    work.nm = rec.xke / ::pow(work.am, 1.5);
    work.em -= tempe;
    if (work.em >= 1.0 || work.em < -0.001) {
        work.error = 1;
        if (error_out) *error_out = work.error;
        return false;
    }
    if (work.em < 1.0e-6) work.em = 1.0e-6;
    work.mm += rec.no_unkozai * templ;
    double xlm = work.mm + work.argpm + work.nodem;
    work.emsq = work.em * work.em;
    work.nodem = sgp4_mod(work.nodem, kSgp4TwoPi);
    work.argpm = sgp4_mod(work.argpm, kSgp4TwoPi);
    xlm = sgp4_mod(xlm, kSgp4TwoPi);
    work.mm = sgp4_mod(xlm - work.argpm - work.nodem, kSgp4TwoPi);
    work.sinim = ::sin(work.inclm);
    work.cosim = ::cos(work.inclm);

    work.ep = work.em;
    double xincp = work.inclm;
    work.inclp = work.inclm;
    work.argpp = work.argpm;
    work.nodep = work.nodem;
    work.mp = work.mm;
    double sinip = work.sinim;
    double cosip = work.cosim;
    if (rec.method == 'd') {
        sgp4_dpper_immutable(rec, 'n', work);
        xincp = work.inclp;
        if (xincp < 0.0) {
            xincp = -xincp;
            work.nodep += kSgp4Pi;
            work.argpp -= kSgp4Pi;
        }
        if (work.ep < 0.0 || work.ep > 1.0) {
            work.error = 3;
            if (error_out) *error_out = work.error;
            return false;
        }
    }

    if (rec.method == 'd') {
        sinip = ::sin(xincp);
        cosip = ::cos(xincp);
        work.aycof = -0.5 * rec.j3oj2 * sinip;
        const double denominator = sgp4_abs(cosip + 1.0) > temp4 ? (1.0 + cosip) : temp4;
        work.xlcof = -0.25 * rec.j3oj2 * sinip * (3.0 + 5.0 * cosip) / denominator;
    }

    const double axnl = work.ep * ::cos(work.argpp);
    double temp = 1.0 / (work.am * (1.0 - work.ep * work.ep));
    const double aynl = work.ep * ::sin(work.argpp) + temp * work.aycof;
    const double xl = work.mp + work.argpp + work.nodep + temp * work.xlcof * axnl;
    const double u = sgp4_mod(xl - work.nodep, kSgp4TwoPi);
    double eo1 = u;
    double tem5 = 9999.9;
    double sineo1 = 0.0;
    double coseo1 = 0.0;
    for (int ktr = 1; sgp4_abs(tem5) >= 1.0e-12 && ktr <= 10; ++ktr) {
        sineo1 = ::sin(eo1);
        coseo1 = ::cos(eo1);
        tem5 = 1.0 - coseo1 * axnl - sineo1 * aynl;
        tem5 = (u - aynl * coseo1 + axnl * sineo1 - eo1) / tem5;
        if (sgp4_abs(tem5) >= 0.95) tem5 = tem5 > 0.0 ? 0.95 : -0.95;
        eo1 += tem5;
    }

    const double ecose = axnl * coseo1 + aynl * sineo1;
    const double esine = axnl * sineo1 - aynl * coseo1;
    const double el2 = axnl * axnl + aynl * aynl;
    const double pl = work.am * (1.0 - el2);
    if (pl < 0.0) {
        work.error = 4;
        if (error_out) *error_out = work.error;
        return false;
    }

    const double rl = work.am * (1.0 - ecose);
    const double rdotl = ::sqrt(work.am) * esine / rl;
    const double rvdotl = ::sqrt(pl) / rl;
    const double betal = ::sqrt(1.0 - el2);
    temp = esine / (1.0 + betal);
    const double sinu = work.am / rl * (sineo1 - aynl - axnl * temp);
    const double cosu = work.am / rl * (coseo1 - axnl + aynl * temp);
    double su = ::atan2(sinu, cosu);
    const double sin2u = (cosu + cosu) * sinu;
    const double cos2u = 1.0 - 2.0 * sinu * sinu;
    temp = 1.0 / pl;
    const double temp1 = 0.5 * rec.j2 * temp;
    const double temp2 = temp1 * temp;
    if (rec.method == 'd') {
        const double cosisq = cosip * cosip;
        work.con41 = 3.0 * cosisq - 1.0;
        work.x1mth2 = 1.0 - cosisq;
        work.x7thm1 = 7.0 * cosisq - 1.0;
    }

    const double mrt = rl * (1.0 - 1.5 * temp2 * betal * work.con41) +
                       0.5 * temp1 * work.x1mth2 * cos2u;
    su -= 0.25 * temp2 * work.x7thm1 * sin2u;
    const double xnode = work.nodep + 1.5 * temp2 * cosip * sin2u;
    const double xinc = xincp + 1.5 * temp2 * cosip * sinip * cos2u;
    const double mvt = rdotl - work.nm * temp1 * work.x1mth2 * sin2u / rec.xke;
    const double rvdot = rvdotl + work.nm * temp1 *
        (work.x1mth2 * cos2u + 1.5 * work.con41) / rec.xke;

    const double sinsu = ::sin(su);
    const double cossu = ::cos(su);
    const double snod = ::sin(xnode);
    const double cnod = ::cos(xnode);
    const double sini = ::sin(xinc);
    const double cosi = ::cos(xinc);
    const double xmx = -snod * cosi;
    const double xmy = cnod * cosi;
    const double ux = xmx * sinsu + cnod * cossu;
    const double uy = xmy * sinsu + snod * cossu;
    const double uz = sini * sinsu;
    const double vx = xmx * cossu - cnod * sinsu;
    const double vy = xmy * cossu - snod * sinsu;
    const double vz = sini * cossu;

    position_km[0] = mrt * ux * rec.radiusearthkm;
    position_km[1] = mrt * uy * rec.radiusearthkm;
    position_km[2] = mrt * uz * rec.radiusearthkm;
    velocity_km_s[0] = (mvt * ux + rvdot * vx) * vkmpersec;
    velocity_km_s[1] = (mvt * uy + rvdot * vy) * vkmpersec;
    velocity_km_s[2] = (mvt * uz + rvdot * vz) * vkmpersec;

    if (mrt < 1.0) {
        work.error = 6;
        if (error_out) *error_out = work.error;
        return false;
    }
    if (error_out) *error_out = 0;
    return true;
}

KLB_HD KLB_INLINE Sgp4State sgp4_state_at(
    const Sgp4Record& record,
    double minutes_since_epoch) {
    Sgp4State result{};
    sgp4_propagate_immutable(record, minutes_since_epoch,
                             result.position_teme_km,
                             result.velocity_teme_km_s,
                             &result.error);
    return result;
}

KLB_HD KLB_INLINE double sgp4_gstime_device(double jdut1) {
    const double tut1 = (jdut1 - 2451545.0) / 36525.0;
    double value = -6.2e-6 * tut1 * tut1 * tut1 + 0.093104 * tut1 * tut1 +
                   (876600.0 * 3600.0 + 8640184.812866) * tut1 + 67310.54841;
    value = sgp4_mod(value * kSgp4DegToRad / 240.0, kSgp4TwoPi);
    if (value < 0.0) value += kSgp4TwoPi;
    return value;
}

KLB_HD KLB_INLINE void sgp4_teme_to_pef(
    const double teme[3],
    double julian_ut1,
    double pef[3]) {
    const double theta = sgp4_gstime_device(julian_ut1);
    const double sine = ::sin(theta);
    const double cosine = ::cos(theta);
    pef[0] = cosine * teme[0] + sine * teme[1];
    pef[1] = -sine * teme[0] + cosine * teme[1];
    pef[2] = teme[2];
}

KLB_HD KLB_INLINE Sgp4Visibility sgp4_evaluate_visibility(
    const double position_teme_km[3],
    double julian_utc,
    double dut1_seconds,
    const Sgp4GroundStation& station,
    std::uint32_t route_sector) {
    double position_pef[3]{};
    sgp4_teme_to_pef(position_teme_km,
                     julian_utc + dut1_seconds / 86400.0,
                     position_pef);
    const double dx = position_pef[0] - station.ecef_km[0];
    const double dy = position_pef[1] - station.ecef_km[1];
    const double dz = position_pef[2] - station.ecef_km[2];
    const double range = ::sqrt(dx * dx + dy * dy + dz * dz);
    const double elevation_sin = range > 1.0e-12
        ? (dx * station.up_unit[0] + dy * station.up_unit[1] +
           dz * station.up_unit[2]) / range
        : 1.0;
    const bool route_ok = station.route_filter == 0xffffffffu ||
                          station.route_filter == route_sector;
    const bool support = range <= station.maximum_slant_range_km;
    return {
        station.elevation_mask_sin - elevation_sin,
        elevation_sin,
        range,
        support ? 1u : 0u,
        route_ok ? 1u : 0u,
    };
}

KLB_HD KLB_INLINE Sgp4Crossing sgp4_evaluate_crossing(
    const Sgp4Visibility& previous,
    const Sgp4Visibility& current,
    double previous_seconds,
    double current_seconds,
    double crossing_band) {
    Sgp4Crossing result{};
    result.minimum_abs_guard = sgp4_abs(previous.guard) < sgp4_abs(current.guard)
        ? sgp4_abs(previous.guard) : sgp4_abs(current.guard);
    if (previous.supported == 0u && current.supported == 0u) return result;
    if (previous.compatible == 0u || current.compatible == 0u) return result;
    const bool changed = (previous.guard > 0.0 && current.guard <= 0.0) ||
                         (previous.guard <= 0.0 && current.guard > 0.0);
    if (!changed || result.minimum_abs_guard > crossing_band) return result;
    const double denominator = previous.guard - current.guard;
    double alpha = denominator != 0.0 ? previous.guard / denominator : 0.5;
    if (alpha < 0.0) alpha = 0.0;
    if (alpha > 1.0) alpha = 1.0;
    result.verified = 1u;
    result.acquisition = previous.guard > 0.0 && current.guard <= 0.0 ? 1u : 0u;
    result.interpolation = alpha;
    result.crossing_seconds = previous_seconds + alpha * (current_seconds - previous_seconds);
    return result;
}

KLB_HD KLB_INLINE double sgp4_minutes_from_reference(
    const Sgp4SeedDisk& seed,
    double seconds_from_reference,
    double reference_unix_seconds) {
    return (reference_unix_seconds + seconds_from_reference - seed.epoch_unix_seconds) / 60.0;
}

KLB_HD KLB_INLINE std::uint32_t sgp4_timeline_node_index(
    const Sgp4TimelineNodeDisk* nodes,
    std::uint32_t node_count,
    double seconds_from_reference) {
    if (nodes == nullptr || node_count == 0u) return 0u;
    if (seconds_from_reference <= nodes[0].start_seconds) return 0u;
    for (std::uint32_t index = 0u; index < node_count; ++index) {
        const Sgp4TimelineNodeDisk node = nodes[index];
        if (seconds_from_reference >= node.start_seconds &&
            seconds_from_reference < node.start_seconds + node.duration_seconds) {
            return index;
        }
    }
    return node_count - 1u;
}

KLB_HD KLB_INLINE std::uint32_t sgp4_lineage(
    const Sgp4SeedDisk& seed,
    const Sgp4TimelineNodeDisk& node,
    std::uint64_t sample_index,
    std::uint32_t event_kind) {
    const std::uint32_t lo = static_cast<std::uint32_t>(sample_index);
    const std::uint32_t hi = static_cast<std::uint32_t>(sample_index >> 32u);
    return mix32(seed.lineage_seed ^ node.chain_seed ^ lo ^ mix32(hi) ^
                 (event_kind * 0x9e3779b9u));
}

} // namespace klb
