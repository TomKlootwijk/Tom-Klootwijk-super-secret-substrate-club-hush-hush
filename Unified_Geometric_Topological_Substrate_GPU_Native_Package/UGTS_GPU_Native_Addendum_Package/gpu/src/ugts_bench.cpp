#include "ugts_egl_gles_min.h"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <numeric>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace fs = std::filesystem;
using Clock = std::chrono::steady_clock;

namespace {

struct Args {
    fs::path shader_dir = "shaders/es";
    fs::path out_dir = "benchmark_out";
    std::vector<std::size_t> sizes = {1024, 16384, 262144, 1048576};
    int warmup = 3;
    int iterations = 12;
};

std::vector<std::size_t> parse_sizes(const std::string& text) {
    std::vector<std::size_t> values;
    std::stringstream ss(text);
    std::string part;
    while (std::getline(ss, part, ',')) {
        if (part.empty()) continue;
        values.push_back(static_cast<std::size_t>(std::stoull(part)));
    }
    if (values.empty()) throw std::runtime_error("--sizes produced an empty list");
    return values;
}

Args parse_args(int argc, char** argv) {
    Args a;
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        auto need = [&](const char* name) -> std::string {
            if (i + 1 >= argc) throw std::runtime_error(std::string("missing value for ") + name);
            return argv[++i];
        };
        if (arg == "--shader-dir") a.shader_dir = need("--shader-dir");
        else if (arg == "--out-dir") a.out_dir = need("--out-dir");
        else if (arg == "--sizes") a.sizes = parse_sizes(need("--sizes"));
        else if (arg == "--warmup") a.warmup = std::stoi(need("--warmup"));
        else if (arg == "--iterations") a.iterations = std::stoi(need("--iterations"));
        else if (arg == "--help" || arg == "-h") {
            std::cout
                << "UGTS GPU-native benchmark\n"
                << "  --shader-dir PATH\n"
                << "  --out-dir PATH\n"
                << "  --sizes N,N,...\n"
                << "  --warmup N\n"
                << "  --iterations N\n";
            std::exit(0);
        } else {
            throw std::runtime_error("unknown argument: " + arg);
        }
    }
    if (a.warmup < 0 || a.iterations < 1) throw std::runtime_error("invalid iteration count");
    return a;
}

std::string read_text(const fs::path& p) {
    std::ifstream f(p, std::ios::binary);
    if (!f) throw std::runtime_error("cannot read " + p.string());
    std::ostringstream ss;
    ss << f.rdbuf();
    return ss.str();
}

void write_bytes(const fs::path& p, const std::vector<std::uint8_t>& data) {
    fs::create_directories(p.parent_path());
    std::ofstream f(p, std::ios::binary);
    if (!f) throw std::runtime_error("cannot write " + p.string());
    f.write(reinterpret_cast<const char*>(data.data()), static_cast<std::streamsize>(data.size()));
}

std::string json_escape(const std::string& s) {
    std::ostringstream o;
    for (unsigned char c : s) {
        switch (c) {
            case '\\': o << "\\\\"; break;
            case '"': o << "\\\""; break;
            case '\b': o << "\\b"; break;
            case '\f': o << "\\f"; break;
            case '\n': o << "\\n"; break;
            case '\r': o << "\\r"; break;
            case '\t': o << "\\t"; break;
            default:
                if (c < 0x20) {
                    o << "\\u" << std::hex << std::setw(4) << std::setfill('0') << int(c)
                      << std::dec << std::setfill(' ');
                } else {
                    o << c;
                }
        }
    }
    return o.str();
}

double millis(Clock::time_point a, Clock::time_point b) {
    return std::chrono::duration<double, std::milli>(b - a).count();
}

double percentile(std::vector<double> v, double q) {
    if (v.empty()) return 0.0;
    std::sort(v.begin(), v.end());
    const double idx = q * double(v.size() - 1);
    const auto lo = static_cast<std::size_t>(std::floor(idx));
    const auto hi = static_cast<std::size_t>(std::ceil(idx));
    const double t = idx - double(lo);
    return v[lo] * (1.0 - t) + v[hi] * t;
}

std::uint32_t load_u32_le(const std::uint8_t* p) {
    return std::uint32_t(p[0]) |
           (std::uint32_t(p[1]) << 8) |
           (std::uint32_t(p[2]) << 16) |
           (std::uint32_t(p[3]) << 24);
}

struct SpirvModuleInfo {
    std::size_t offset = 0;
    std::size_t size = 0;
    std::uint32_t version = 0;
    std::uint32_t generator = 0;
    std::uint32_t bound = 0;
    std::size_t instructions = 0;
    fs::path path;
};

std::vector<SpirvModuleInfo> extract_spirv(
    const std::vector<std::uint8_t>& binary,
    const fs::path& base_path) {

    constexpr std::uint32_t magic = 0x07230203u;
    std::vector<SpirvModuleInfo> modules;
    for (std::size_t off = 0; off + 20 <= binary.size(); ++off) {
        if (load_u32_le(binary.data() + off) != magic) continue;
        const std::size_t words_available = (binary.size() - off) / 4;
        std::size_t wi = 5;
        std::size_t instruction_count = 0;
        while (wi < words_available) {
            const std::uint32_t opword = load_u32_le(binary.data() + off + wi * 4);
            const std::uint32_t wc = opword >> 16;
            if (wc == 0 || wi + wc > words_available) break;
            wi += wc;
            ++instruction_count;
        }
        if (instruction_count < 8 || wi <= 5) continue;

        SpirvModuleInfo info;
        info.offset = off;
        info.size = wi * 4;
        info.version = load_u32_le(binary.data() + off + 4);
        info.generator = load_u32_le(binary.data() + off + 8);
        info.bound = load_u32_le(binary.data() + off + 12);
        info.instructions = instruction_count;
        info.path = base_path;
        if (!modules.empty()) {
            info.path += "_" + std::to_string(modules.size());
        }
        info.path += ".spv";

        std::vector<std::uint8_t> module(binary.begin() + static_cast<std::ptrdiff_t>(off),
                                         binary.begin() + static_cast<std::ptrdiff_t>(off + info.size));
        write_bytes(info.path, module);
        modules.push_back(info);
        off += info.size - 1;
    }
    return modules;
}

class HeadlessContext {
public:
    HeadlessContext() {
        auto get_platform = reinterpret_cast<PFNEGLGETPLATFORMDISPLAYEXTPROC>(
            eglGetProcAddress("eglGetPlatformDisplayEXT"));
        if (!get_platform) throw std::runtime_error("eglGetPlatformDisplayEXT unavailable");

        const EGLint display_attrs[] = {
            EGL_PLATFORM_ANGLE_TYPE_ANGLE, EGL_PLATFORM_ANGLE_TYPE_VULKAN_ANGLE,
            EGL_PLATFORM_ANGLE_DEVICE_TYPE_ANGLE, EGL_PLATFORM_ANGLE_DEVICE_TYPE_SWIFTSHADER_ANGLE,
            EGL_PLATFORM_ANGLE_NATIVE_PLATFORM_TYPE_ANGLE, EGL_PLATFORM_VULKAN_DISPLAY_MODE_HEADLESS_ANGLE,
            EGL_NONE};
        display_ = get_platform(EGL_PLATFORM_ANGLE_ANGLE, EGL_DEFAULT_DISPLAY, display_attrs);
        if (display_ == EGL_NO_DISPLAY) throw std::runtime_error("failed to create ANGLE display");
        if (!eglInitialize(display_, &egl_major_, &egl_minor_)) {
            std::ostringstream e; e << "eglInitialize failed: 0x" << std::hex << eglGetError();
            throw std::runtime_error(e.str());
        }
        if (!eglBindAPI(EGL_OPENGL_ES_API)) throw std::runtime_error("eglBindAPI failed");

        const EGLint config_attrs[] = {
            EGL_SURFACE_TYPE, EGL_PBUFFER_BIT,
            EGL_RENDERABLE_TYPE, EGL_OPENGL_ES3_BIT,
            EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_ALPHA_SIZE, 8,
            EGL_NONE};
        EGLint count = 0;
        if (!eglChooseConfig(display_, config_attrs, &config_, 1, &count) || count < 1) {
            throw std::runtime_error("eglChooseConfig failed");
        }
        const EGLint surface_attrs[] = {EGL_WIDTH, 1, EGL_HEIGHT, 1, EGL_NONE};
        surface_ = eglCreatePbufferSurface(display_, config_, surface_attrs);
        if (surface_ == EGL_NO_SURFACE) throw std::runtime_error("eglCreatePbufferSurface failed");

        const EGLint context_attrs[] = {EGL_CONTEXT_CLIENT_VERSION, 3, EGL_NONE};
        context_ = eglCreateContext(display_, config_, EGL_NO_CONTEXT, context_attrs);
        if (context_ == EGL_NO_CONTEXT) throw std::runtime_error("eglCreateContext failed");
        if (!eglMakeCurrent(display_, surface_, surface_, context_)) {
            throw std::runtime_error("eglMakeCurrent failed");
        }
    }

    ~HeadlessContext() {
        if (display_ != EGL_NO_DISPLAY) {
            eglMakeCurrent(display_, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
            if (context_ != EGL_NO_CONTEXT) eglDestroyContext(display_, context_);
            if (surface_ != EGL_NO_SURFACE) eglDestroySurface(display_, surface_);
            eglTerminate(display_);
        }
    }

    std::string vendor() const { return str(GL_VENDOR); }
    std::string renderer() const { return str(GL_RENDERER); }
    std::string version() const { return str(GL_VERSION); }
    std::string glsl() const { return str(GL_SHADING_LANGUAGE_VERSION); }
    std::string egl_vendor() const { return egl_str(EGL_VENDOR); }
    std::string egl_version() const { return egl_str(EGL_VERSION); }
    int egl_major() const { return egl_major_; }
    int egl_minor() const { return egl_minor_; }

private:
    std::string str(GLenum e) const {
        const auto* p = glGetString(e);
        return p ? reinterpret_cast<const char*>(p) : "";
    }
    std::string egl_str(EGLint e) const {
        const char* p = eglQueryString(display_, e);
        return p ? p : "";
    }

    EGLDisplay display_ = EGL_NO_DISPLAY;
    EGLConfig config_ = nullptr;
    EGLContext context_ = EGL_NO_CONTEXT;
    EGLSurface surface_ = EGL_NO_SURFACE;
    EGLint egl_major_ = 0;
    EGLint egl_minor_ = 0;
};

std::string inject_counter_mode(const std::string& source, bool counters) {
    const auto line_end = source.find('\n');
    if (line_end == std::string::npos) throw std::runtime_error("shader has no version line");
    return source.substr(0, line_end + 1) +
           std::string("#define ENABLE_COUNTERS ") + (counters ? "1\n" : "0\n") +
           source.substr(line_end + 1);
}

struct ProgramInfo {
    GLuint program = 0;
    double compile_ms = 0.0;
    double link_ms = 0.0;
    double binary_reload_ms = 0.0;
    bool binary_reload_ok = false;
    GLenum binary_format = 0;
    std::vector<std::uint8_t> binary;
    fs::path binary_path;
    std::vector<SpirvModuleInfo> spirv_modules;
};

ProgramInfo build_program(const std::string& source, const fs::path& cache_base) {
    ProgramInfo pi;
    GLuint shader = glCreateShader(GL_COMPUTE_SHADER);
    const GLchar* ptr = source.c_str();
    glShaderSource(shader, 1, &ptr, nullptr);
    auto t0 = Clock::now();
    glCompileShader(shader);
    auto t1 = Clock::now();
    pi.compile_ms = millis(t0, t1);

    GLint ok = GL_FALSE;
    glGetShaderiv(shader, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        GLint len = 0;
        glGetShaderiv(shader, GL_INFO_LOG_LENGTH, &len);
        std::vector<char> log(static_cast<std::size_t>(std::max(1, len)) + 1);
        glGetShaderInfoLog(shader, len, nullptr, log.data());
        glDeleteShader(shader);
        throw std::runtime_error(std::string("shader compile failed:\n") + log.data());
    }

    pi.program = glCreateProgram();
    glAttachShader(pi.program, shader);
    glProgramParameteri(pi.program, GL_PROGRAM_BINARY_RETRIEVABLE_HINT, GL_TRUE);
    t0 = Clock::now();
    glLinkProgram(pi.program);
    t1 = Clock::now();
    pi.link_ms = millis(t0, t1);
    glGetProgramiv(pi.program, GL_LINK_STATUS, &ok);
    if (!ok) {
        GLint len = 0;
        glGetProgramiv(pi.program, GL_INFO_LOG_LENGTH, &len);
        std::vector<char> log(static_cast<std::size_t>(std::max(1, len)) + 1);
        glGetProgramInfoLog(pi.program, len, nullptr, log.data());
        glDeleteProgram(pi.program);
        glDeleteShader(shader);
        throw std::runtime_error(std::string("program link failed:\n") + log.data());
    }
    glDetachShader(pi.program, shader);
    glDeleteShader(shader);

    GLint binary_len = 0;
    glGetProgramiv(pi.program, GL_PROGRAM_BINARY_LENGTH, &binary_len);
    if (binary_len > 0) {
        pi.binary.resize(static_cast<std::size_t>(binary_len));
        GLsizei written = 0;
        glGetProgramBinary(pi.program, binary_len, &written, &pi.binary_format, pi.binary.data());
        pi.binary.resize(static_cast<std::size_t>(written));
        pi.binary_path = cache_base;
        pi.binary_path += ".anglebin";
        write_bytes(pi.binary_path, pi.binary);

        GLuint reload = glCreateProgram();
        t0 = Clock::now();
        glProgramBinary(reload, pi.binary_format, pi.binary.data(), static_cast<GLsizei>(pi.binary.size()));
        t1 = Clock::now();
        pi.binary_reload_ms = millis(t0, t1);
        GLint reload_ok = GL_FALSE;
        glGetProgramiv(reload, GL_LINK_STATUS, &reload_ok);
        pi.binary_reload_ok = reload_ok == GL_TRUE;
        glDeleteProgram(reload);

        fs::path spv_base = cache_base;
        spv_base += "_module";
        pi.spirv_modules = extract_spirv(pi.binary, spv_base);
    }
    return pi;
}

std::uint32_t mix32(std::uint32_t x) {
    x ^= x >> 16;
    x *= 0x7feb352du;
    x ^= x >> 15;
    x *= 0x846ca68bu;
    x ^= x >> 16;
    return x;
}

std::uint16_t f32_to_f16(float f) {
    std::uint32_t x = 0;
    std::memcpy(&x, &f, 4);
    const std::uint32_t sign = (x >> 16) & 0x8000u;
    int exp = int((x >> 23) & 0xffu) - 127 + 15;
    std::uint32_t mant = x & 0x7fffffu;
    if (exp <= 0) {
        if (exp < -10) return static_cast<std::uint16_t>(sign);
        mant = (mant | 0x800000u) >> (1 - exp);
        return static_cast<std::uint16_t>(sign | ((mant + 0x1000u) >> 13));
    }
    if (exp >= 31) return static_cast<std::uint16_t>(sign | 0x7c00u);
    return static_cast<std::uint16_t>(sign | (std::uint32_t(exp) << 10) | ((mant + 0x1000u) >> 13));
}

float f16_to_f32(std::uint16_t h) {
    const std::uint32_t sign = (std::uint32_t(h & 0x8000u)) << 16;
    std::uint32_t exp = (h >> 10) & 0x1fu;
    std::uint32_t mant = h & 0x3ffu;
    std::uint32_t x = 0;
    if (exp == 0) {
        if (mant == 0) {
            x = sign;
        } else {
            exp = 1;
            while ((mant & 0x400u) == 0) { mant <<= 1; --exp; }
            mant &= 0x3ffu;
            x = sign | ((exp + (127 - 15)) << 23) | (mant << 13);
        }
    } else if (exp == 31) {
        x = sign | 0x7f800000u | (mant << 13);
    } else {
        x = sign | ((exp + (127 - 15)) << 23) | (mant << 13);
    }
    float f = 0.0f;
    std::memcpy(&f, &x, 4);
    return f;
}

std::uint32_t pack2(float a, float b) {
    return std::uint32_t(f32_to_f16(a)) | (std::uint32_t(f32_to_f16(b)) << 16);
}

std::array<float, 2> unpack2(std::uint32_t x) {
    return {f16_to_f32(static_cast<std::uint16_t>(x & 0xffffu)),
            f16_to_f32(static_cast<std::uint16_t>(x >> 16))};
}

struct alignas(16) State64 {
    float position_time[4];
    float axis_radius[4];
    float phase_guard[4];
    std::uint32_t meta[4];
};
struct alignas(16) Event32 {
    std::uint32_t scalar_bits[4];
    std::uint32_t topology_bits[4];
};
struct alignas(16) State32 {
    std::uint32_t words[8];
};
struct alignas(16) Event16 {
    std::uint32_t words[4];
};

static_assert(sizeof(State64) == 64, "G64 layout changed");
static_assert(sizeof(Event32) == 32, "E32 layout changed");
static_assert(sizeof(State32) == 32, "G32 layout changed");
static_assert(sizeof(Event16) == 16, "E16 layout changed");

struct EvalFields {
    float px, py, pz, time;
    float ax, ay, az, radius;
    float cone_cos, phase, guard_epsilon, confidence_floor;
    std::uint32_t sheet, orientation, compatibility_mask, lineage_seed;
};

EvalFields generated_fields(std::size_t i) {
    const float angle = float(i % 1024) * 0.01f;
    const float radius = 10.0f + float(int(i % 17) - 8) * 0.002f;
    EvalFields f{};
    f.px = radius * std::cos(angle);
    f.py = radius * std::sin(angle);
    f.pz = 0.0f;
    f.time = float(i) * 0.001f;
    f.ax = std::cos(angle);
    f.ay = std::sin(angle);
    f.az = 0.0f;
    f.radius = 10.0f;
    f.cone_cos = 0.5f;
    f.phase = float(i % 256) / 256.0f;
    f.guard_epsilon = 0.010f;
    f.confidence_floor = 0.70f;
    f.sheet = std::uint32_t(i & 1u);
    f.orientation = std::uint32_t((i >> 1u) & 1u);
    f.compatibility_mask = (i % 3) ? 4u : 1u;
    f.lineage_seed = std::uint32_t(i * 2654435761u);
    return f;
}

State64 make_g64(std::size_t i) {
    const auto f = generated_fields(i);
    State64 s{};
    s.position_time[0] = f.px; s.position_time[1] = f.py; s.position_time[2] = f.pz; s.position_time[3] = f.time;
    s.axis_radius[0] = f.ax; s.axis_radius[1] = f.ay; s.axis_radius[2] = f.az; s.axis_radius[3] = f.radius;
    s.phase_guard[0] = f.cone_cos; s.phase_guard[1] = f.phase;
    s.phase_guard[2] = f.guard_epsilon; s.phase_guard[3] = f.confidence_floor;
    s.meta[0] = f.sheet; s.meta[1] = f.orientation; s.meta[2] = f.compatibility_mask; s.meta[3] = f.lineage_seed;
    return s;
}

State32 make_g32(std::size_t i) {
    const auto f = generated_fields(i);
    State32 s{};
    s.words[0] = pack2(f.px, f.py);
    s.words[1] = pack2(f.pz, f.time);
    s.words[2] = pack2(f.ax, f.ay);
    s.words[3] = pack2(f.az, f.radius);
    s.words[4] = pack2(f.cone_cos, f.phase);
    s.words[5] = pack2(f.guard_epsilon, f.confidence_floor);
    s.words[6] = f.sheet | (f.orientation << 8) | ((f.compatibility_mask & 0xffffu) << 9);
    s.words[7] = f.lineage_seed;
    return s;
}

EvalFields decode_g32(const State32& s) {
    const auto xy = unpack2(s.words[0]);
    const auto zt = unpack2(s.words[1]);
    const auto aa = unpack2(s.words[2]);
    const auto ar = unpack2(s.words[3]);
    const auto cp = unpack2(s.words[4]);
    const auto gc = unpack2(s.words[5]);
    EvalFields f{};
    f.px = xy[0]; f.py = xy[1]; f.pz = zt[0]; f.time = zt[1];
    f.ax = aa[0]; f.ay = aa[1]; f.az = ar[0]; f.radius = ar[1];
    f.cone_cos = cp[0]; f.phase = cp[1]; f.guard_epsilon = gc[0]; f.confidence_floor = gc[1];
    f.sheet = s.words[6] & 255u;
    f.orientation = (s.words[6] >> 8) & 1u;
    f.compatibility_mask = (s.words[6] >> 9) & 0xffffu;
    f.lineage_seed = s.words[7];
    return f;
}

struct CpuEval {
    bool support = false;
    bool compatible = false;
    bool verified = false;
    std::uint32_t route = 0;
    std::uint32_t lineage = 0;
    float sdf = 0.0f;
    float guard = 0.0f;
    float confidence = 0.0f;
};

CpuEval cpu_eval(const EvalFields& f, std::size_t i) {
    CpuEval e{};
    const float r = std::sqrt(f.px * f.px + f.py * f.py + f.pz * f.pz);
    const float axis_len = std::sqrt(f.ax * f.ax + f.ay * f.ay + f.az * f.az);
    float cosine = 1.0f;
    if (r > 1e-8f && axis_len > 1e-8f) {
        cosine = (f.px * f.ax + f.py * f.ay + f.pz * f.az) / (r * axis_len);
    }
    e.support = r <= f.radius && cosine >= f.cone_cos;
    e.compatible = (f.compatibility_mask & 4u) != 0u && f.sheet == 1u && (f.orientation & 1u) == 0u;
    e.sdf = r - f.radius;
    e.guard = std::abs(e.sdf) - f.guard_epsilon;
    e.confidence = std::exp2(-std::abs(e.sdf) * 32.0f);
    e.verified = e.support && e.compatible && e.guard <= 0.0f && e.confidence >= f.confidence_floor;
    e.route = (f.orientation ^ (e.verified ? 1u : 0u)) & 1u;
    e.lineage = mix32(f.lineage_seed ^ std::uint32_t(i));
    return e;
}

struct Counts {
    std::uint64_t candidates = 0;
    std::uint64_t supported = 0;
    std::uint64_t compatible = 0;
    std::uint64_t verified = 0;
};

Counts cpu_counts_g64(const std::vector<State64>& states) {
    Counts c{};
    for (std::size_t i = 0; i < states.size(); ++i) {
        const auto& s = states[i];
        EvalFields f{};
        std::copy(s.position_time, s.position_time + 4, &f.px);
        f.ax = s.axis_radius[0]; f.ay = s.axis_radius[1]; f.az = s.axis_radius[2]; f.radius = s.axis_radius[3];
        f.cone_cos = s.phase_guard[0]; f.phase = s.phase_guard[1];
        f.guard_epsilon = s.phase_guard[2]; f.confidence_floor = s.phase_guard[3];
        f.sheet = s.meta[0]; f.orientation = s.meta[1]; f.compatibility_mask = s.meta[2]; f.lineage_seed = s.meta[3];
        const auto e = cpu_eval(f, i);
        ++c.candidates;
        if (e.support) ++c.supported;
        if (e.support && e.compatible) ++c.compatible;
        if (e.verified) ++c.verified;
    }
    return c;
}

Counts cpu_counts_g32(const std::vector<State32>& states) {
    Counts c{};
    for (std::size_t i = 0; i < states.size(); ++i) {
        const auto e = cpu_eval(decode_g32(states[i]), i);
        ++c.candidates;
        if (e.support) ++c.supported;
        if (e.support && e.compatible) ++c.compatible;
        if (e.verified) ++c.verified;
    }
    return c;
}

struct BenchRow {
    std::string profile;
    std::string mode;
    std::size_t candidates = 0;
    std::size_t input_record_bytes = 0;
    std::size_t output_record_bytes = 0;
    std::size_t total_buffer_bytes = 0;
    double upload_ms = 0.0;
    double dispatch_min_ms = 0.0;
    double dispatch_mean_ms = 0.0;
    double dispatch_p50_ms = 0.0;
    double dispatch_p95_ms = 0.0;
    double dispatch_p99_ms = 0.0;
    double dispatch_max_ms = 0.0;
    double candidate_rate_mps = 0.0;
    double verified_event_rate_mps = 0.0;
    double effective_bandwidth_gbps = 0.0;
    Counts counts;
    bool counter_validation = false;
    bool sample_validation = false;
};

struct ProfileRun {
    ProgramInfo program;
    std::vector<BenchRow> rows;
};

bool validate_g64_sample(const std::vector<State64>& states, GLuint output_buffer) {
    const std::size_t sample = std::min<std::size_t>(states.size(), 4096);
    glBindBuffer(GL_SHADER_STORAGE_BUFFER, output_buffer);
    auto* p = static_cast<Event32*>(glMapBufferRange(
        GL_SHADER_STORAGE_BUFFER, 0, static_cast<GLsizeiptr>(sample * sizeof(Event32)), GL_MAP_READ_BIT));
    if (!p) return false;
    bool ok = true;
    for (std::size_t i = 0; i < sample; ++i) {
        const auto& s = states[i];
        EvalFields f{};
        f.px=s.position_time[0];f.py=s.position_time[1];f.pz=s.position_time[2];f.time=s.position_time[3];
        f.ax=s.axis_radius[0];f.ay=s.axis_radius[1];f.az=s.axis_radius[2];f.radius=s.axis_radius[3];
        f.cone_cos=s.phase_guard[0];f.phase=s.phase_guard[1];f.guard_epsilon=s.phase_guard[2];f.confidence_floor=s.phase_guard[3];
        f.sheet=s.meta[0];f.orientation=s.meta[1];f.compatibility_mask=s.meta[2];f.lineage_seed=s.meta[3];
        const auto e = cpu_eval(f, i);
        if (p[i].topology_bits[0] != (e.verified ? 1u : 0u) ||
            p[i].topology_bits[1] != e.route ||
            p[i].topology_bits[2] != e.lineage) {
            ok = false; break;
        }
    }
    glUnmapBuffer(GL_SHADER_STORAGE_BUFFER);
    return ok;
}

bool validate_g32_sample(const std::vector<State32>& states, GLuint output_buffer) {
    const std::size_t sample = std::min<std::size_t>(states.size(), 4096);
    glBindBuffer(GL_SHADER_STORAGE_BUFFER, output_buffer);
    auto* p = static_cast<Event16*>(glMapBufferRange(
        GL_SHADER_STORAGE_BUFFER, 0, static_cast<GLsizeiptr>(sample * sizeof(Event16)), GL_MAP_READ_BIT));
    if (!p) return false;
    bool ok = true;
    for (std::size_t i = 0; i < sample; ++i) {
        const auto e = cpu_eval(decode_g32(states[i]), i);
        const std::uint32_t verified = p[i].words[2] & 1u;
        const std::uint32_t route = (p[i].words[2] >> 1) & 1u;
        if (verified != (e.verified ? 1u : 0u) || route != e.route || p[i].words[3] != e.lineage) {
            ok = false; break;
        }
    }
    glUnmapBuffer(GL_SHADER_STORAGE_BUFFER);
    return ok;
}

BenchRow finalize_row(
    const std::string& profile,
    const std::string& mode,
    std::size_t n,
    std::size_t input_bytes,
    std::size_t output_bytes,
    double upload_ms,
    const std::vector<double>& times,
    const Counts& counts,
    bool counter_validation,
    bool sample_validation) {

    BenchRow r{};
    r.profile = profile;
    r.mode = mode;
    r.candidates = n;
    r.input_record_bytes = input_bytes;
    r.output_record_bytes = output_bytes;
    r.total_buffer_bytes = n * (input_bytes + output_bytes) + 16;
    r.upload_ms = upload_ms;
    r.dispatch_min_ms = *std::min_element(times.begin(), times.end());
    r.dispatch_max_ms = *std::max_element(times.begin(), times.end());
    r.dispatch_mean_ms = std::accumulate(times.begin(), times.end(), 0.0) / double(times.size());
    r.dispatch_p50_ms = percentile(times, 0.50);
    r.dispatch_p95_ms = percentile(times, 0.95);
    r.dispatch_p99_ms = percentile(times, 0.99);
    r.candidate_rate_mps = double(n) / r.dispatch_p50_ms / 1000.0;
    r.verified_event_rate_mps = double(counts.verified) / r.dispatch_p50_ms / 1000.0;
    r.effective_bandwidth_gbps = double(n * (input_bytes + output_bytes)) / (r.dispatch_p50_ms * 1.0e6);
    r.counts = counts;
    r.counter_validation = counter_validation;
    r.sample_validation = sample_validation;
    return r;
}

template <typename StateT, typename EventT, typename MakeFn, typename CountFn, typename ValidateFn>
std::vector<BenchRow> run_sizes(
    GLuint program,
    const std::string& profile,
    const std::string& mode,
    bool counters_enabled,
    const Args& args,
    MakeFn make_state,
    CountFn count_fn,
    ValidateFn validate_fn) {

    std::vector<BenchRow> rows;
    glUseProgram(program);
    for (std::size_t n : args.sizes) {
        std::vector<StateT> states(n);
        for (std::size_t i = 0; i < n; ++i) states[i] = make_state(i);
        const Counts expected = count_fn(states);

        GLuint buffers[3] = {};
        glGenBuffers(3, buffers);

        auto t0 = Clock::now();
        glBindBuffer(GL_SHADER_STORAGE_BUFFER, buffers[0]);
        glBufferData(GL_SHADER_STORAGE_BUFFER,
                     static_cast<GLsizeiptr>(states.size() * sizeof(StateT)),
                     states.data(), GL_STATIC_DRAW);
        glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 0, buffers[0]);

        glBindBuffer(GL_SHADER_STORAGE_BUFFER, buffers[1]);
        glBufferData(GL_SHADER_STORAGE_BUFFER,
                     static_cast<GLsizeiptr>(n * sizeof(EventT)),
                     nullptr, GL_DYNAMIC_DRAW);
        glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 1, buffers[1]);

        const std::uint32_t zeros[4] = {};
        glBindBuffer(GL_SHADER_STORAGE_BUFFER, buffers[2]);
        glBufferData(GL_SHADER_STORAGE_BUFFER, sizeof(zeros), zeros, GL_DYNAMIC_DRAW);
        glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 2, buffers[2]);
        glFinish();
        auto t1 = Clock::now();
        const double upload_ms = millis(t0, t1);

        const GLuint groups = static_cast<GLuint>((n + 255) / 256);
        for (int w = 0; w < args.warmup; ++w) {
            glBindBuffer(GL_SHADER_STORAGE_BUFFER, buffers[2]);
            glBufferSubData(GL_SHADER_STORAGE_BUFFER, 0, sizeof(zeros), zeros);
            glDispatchCompute(groups, 1, 1);
            glMemoryBarrier(GL_SHADER_STORAGE_BARRIER_BIT | GL_BUFFER_UPDATE_BARRIER_BIT);
            glFinish();
        }

        std::vector<double> times;
        times.reserve(static_cast<std::size_t>(args.iterations));
        for (int it = 0; it < args.iterations; ++it) {
            glBindBuffer(GL_SHADER_STORAGE_BUFFER, buffers[2]);
            glBufferSubData(GL_SHADER_STORAGE_BUFFER, 0, sizeof(zeros), zeros);
            t0 = Clock::now();
            glDispatchCompute(groups, 1, 1);
            glMemoryBarrier(GL_SHADER_STORAGE_BARRIER_BIT | GL_BUFFER_UPDATE_BARRIER_BIT);
            glFinish();
            t1 = Clock::now();
            times.push_back(millis(t0, t1));
        }

        Counts actual = expected;
        bool counter_ok = !counters_enabled;
        if (counters_enabled) {
            glBindBuffer(GL_SHADER_STORAGE_BUFFER, buffers[2]);
            auto* p = static_cast<std::uint32_t*>(glMapBufferRange(
                GL_SHADER_STORAGE_BUFFER, 0, sizeof(zeros), GL_MAP_READ_BIT));
            if (p) {
                actual.candidates = p[0]; actual.supported = p[1];
                actual.compatible = p[2]; actual.verified = p[3];
                glUnmapBuffer(GL_SHADER_STORAGE_BUFFER);
                counter_ok = actual.candidates == expected.candidates &&
                             actual.supported == expected.supported &&
                             actual.compatible == expected.compatible &&
                             actual.verified == expected.verified;
            }
        }
        const bool sample_ok = validate_fn(states, buffers[1]);

        rows.push_back(finalize_row(
            profile, mode, n, sizeof(StateT), sizeof(EventT), upload_ms, times,
            actual, counter_ok, sample_ok));

        glDeleteBuffers(3, buffers);
        const GLenum err = glGetError();
        if (err != GL_NO_ERROR) {
            std::ostringstream e; e << "OpenGL error after profile " << profile << ": 0x" << std::hex << err;
            throw std::runtime_error(e.str());
        }
    }
    return rows;
}

void write_device_report(const HeadlessContext& ctx, const fs::path& out) {
    GLint max_invocations = 0, max_shared = 0, max_compute_ssbo = 0, max_ssbo_bindings = 0;
    GLint64 max_ssbo_size = 0;
    GLint wg_count[3] = {}, wg_size[3] = {};
    glGetIntegerv(GL_MAX_COMPUTE_WORK_GROUP_INVOCATIONS, &max_invocations);
    glGetIntegerv(GL_MAX_COMPUTE_SHARED_MEMORY_SIZE, &max_shared);
    glGetIntegerv(GL_MAX_COMPUTE_SHADER_STORAGE_BLOCKS, &max_compute_ssbo);
    glGetIntegerv(GL_MAX_SHADER_STORAGE_BUFFER_BINDINGS, &max_ssbo_bindings);
    glGetInteger64v(GL_MAX_SHADER_STORAGE_BLOCK_SIZE, &max_ssbo_size);
    for (GLuint i = 0; i < 3; ++i) {
        glGetIntegeri_v(GL_MAX_COMPUTE_WORK_GROUP_COUNT, i, &wg_count[i]);
        glGetIntegeri_v(GL_MAX_COMPUTE_WORK_GROUP_SIZE, i, &wg_size[i]);
    }

    std::ofstream f(out);
    f << "UGTS GPU-native validation device\n";
    f << "EGL: " << ctx.egl_major() << '.' << ctx.egl_minor() << " | " << ctx.egl_vendor() << " | " << ctx.egl_version() << "\n";
    f << "GL vendor: " << ctx.vendor() << "\n";
    f << "GL renderer: " << ctx.renderer() << "\n";
    f << "GL version: " << ctx.version() << "\n";
    f << "GLSL: " << ctx.glsl() << "\n";
    f << "Max work-group invocations: " << max_invocations << "\n";
    f << "Max work-group count: " << wg_count[0] << ',' << wg_count[1] << ',' << wg_count[2] << "\n";
    f << "Max work-group size: " << wg_size[0] << ',' << wg_size[1] << ',' << wg_size[2] << "\n";
    f << "Max shared memory bytes: " << max_shared << "\n";
    f << "Max compute shader storage blocks: " << max_compute_ssbo << "\n";
    f << "Max SSBO bindings: " << max_ssbo_bindings << "\n";
    f << "Max SSBO block bytes: " << max_ssbo_size << "\n";
    f << "Timing method: host wall clock around dispatch + memory barrier + glFinish.\n";
    f << "Interpretation: API-native compile/dispatch validation on a software Vulkan device; not a physical-GPU performance claim.\n";
}

void write_results_json(
    const HeadlessContext& ctx,
    const Args& args,
    const std::vector<std::pair<std::string, ProgramInfo>>& programs,
    const std::vector<BenchRow>& rows,
    const fs::path& out) {

    std::ofstream f(out);
    f << std::fixed << std::setprecision(6);
    f << "{\n";
    f << "  \"schema\": \"UGTS-BENCH-1.1\",\n";
    f << "  \"measurement_scope\": \"native GPU API compile and synchronous dispatch on validation device\",\n";
    f << "  \"physical_gpu_claim\": false,\n";
    f << "  \"device\": {\n";
    f << "    \"egl_vendor\": \"" << json_escape(ctx.egl_vendor()) << "\",\n";
    f << "    \"egl_version\": \"" << json_escape(ctx.egl_version()) << "\",\n";
    f << "    \"gl_vendor\": \"" << json_escape(ctx.vendor()) << "\",\n";
    f << "    \"gl_renderer\": \"" << json_escape(ctx.renderer()) << "\",\n";
    f << "    \"gl_version\": \"" << json_escape(ctx.version()) << "\",\n";
    f << "    \"glsl_version\": \"" << json_escape(ctx.glsl()) << "\"\n";
    f << "  },\n";
    f << "  \"run_parameters\": {\"warmup\": " << args.warmup << ", \"iterations\": " << args.iterations << "},\n";
    f << "  \"programs\": [\n";
    for (std::size_t i = 0; i < programs.size(); ++i) {
        const auto& name = programs[i].first;
        const auto& p = programs[i].second;
        f << "    {\"name\": \"" << json_escape(name) << "\", "
          << "\"compile_ms\": " << p.compile_ms << ", \"link_ms\": " << p.link_ms
          << ", \"binary_bytes\": " << p.binary.size()
          << ", \"binary_format\": " << p.binary_format
          << ", \"binary_reload_ms\": " << p.binary_reload_ms
          << ", \"binary_reload_ok\": " << (p.binary_reload_ok ? "true" : "false")
          << ", \"spirv_modules\": [";
        for (std::size_t j = 0; j < p.spirv_modules.size(); ++j) {
            const auto& m = p.spirv_modules[j];
            f << "{\"offset\": " << m.offset << ", \"bytes\": " << m.size
              << ", \"version_word\": " << m.version
              << ", \"generator_word\": " << m.generator
              << ", \"bound\": " << m.bound
              << ", \"instructions\": " << m.instructions
              << ", \"path\": \"" << json_escape(m.path.filename().string()) << "\"}";
            if (j + 1 != p.spirv_modules.size()) f << ',';
        }
        f << "]}" << (i + 1 == programs.size() ? "\n" : ",\n");
    }
    f << "  ],\n";
    f << "  \"benchmarks\": [\n";
    for (std::size_t i = 0; i < rows.size(); ++i) {
        const auto& r = rows[i];
        f << "    {\n";
        f << "      \"profile\": \"" << r.profile << "\", \"mode\": \"" << r.mode << "\",\n";
        f << "      \"candidates\": " << r.candidates << ",\n";
        f << "      \"input_record_bytes\": " << r.input_record_bytes << ", \"output_record_bytes\": " << r.output_record_bytes << ",\n";
        f << "      \"total_buffer_bytes\": " << r.total_buffer_bytes << ", \"upload_ms\": " << r.upload_ms << ",\n";
        f << "      \"dispatch_ms\": {\"min\": " << r.dispatch_min_ms << ", \"mean\": " << r.dispatch_mean_ms
          << ", \"p50\": " << r.dispatch_p50_ms << ", \"p95\": " << r.dispatch_p95_ms
          << ", \"p99\": " << r.dispatch_p99_ms << ", \"max\": " << r.dispatch_max_ms << "},\n";
        f << "      \"candidate_rate_mps\": " << r.candidate_rate_mps
          << ", \"verified_event_rate_mps\": " << r.verified_event_rate_mps
          << ", \"effective_bandwidth_gbps\": " << r.effective_bandwidth_gbps << ",\n";
        f << "      \"counts\": {\"candidates\": " << r.counts.candidates
          << ", \"supported\": " << r.counts.supported
          << ", \"compatible\": " << r.counts.compatible
          << ", \"verified\": " << r.counts.verified << "},\n";
        f << "      \"counter_validation\": " << (r.counter_validation ? "true" : "false")
          << ", \"sample_validation\": " << (r.sample_validation ? "true" : "false") << "\n";
        f << "    }" << (i + 1 == rows.size() ? "\n" : ",\n");
    }
    f << "  ]\n";
    f << "}\n";
}

void write_results_csv(const std::vector<BenchRow>& rows, const fs::path& out) {
    std::ofstream f(out);
    f << "profile,mode,candidates,input_record_bytes,output_record_bytes,total_buffer_bytes,upload_ms,dispatch_min_ms,dispatch_mean_ms,dispatch_p50_ms,dispatch_p95_ms,dispatch_p99_ms,dispatch_max_ms,candidate_rate_mps,verified_event_rate_mps,effective_bandwidth_gbps,supported,compatible,verified,counter_validation,sample_validation\n";
    f << std::fixed << std::setprecision(6);
    for (const auto& r : rows) {
        f << r.profile << ',' << r.mode << ',' << r.candidates << ','
          << r.input_record_bytes << ',' << r.output_record_bytes << ',' << r.total_buffer_bytes << ','
          << r.upload_ms << ',' << r.dispatch_min_ms << ',' << r.dispatch_mean_ms << ','
          << r.dispatch_p50_ms << ',' << r.dispatch_p95_ms << ',' << r.dispatch_p99_ms << ',' << r.dispatch_max_ms << ','
          << r.candidate_rate_mps << ',' << r.verified_event_rate_mps << ',' << r.effective_bandwidth_gbps << ','
          << r.counts.supported << ',' << r.counts.compatible << ',' << r.counts.verified << ','
          << (r.counter_validation ? 1 : 0) << ',' << (r.sample_validation ? 1 : 0) << '\n';
    }
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const Args args = parse_args(argc, argv);
        fs::create_directories(args.out_dir);
        fs::create_directories(args.out_dir / "native_cache");

        HeadlessContext ctx;
        write_device_report(ctx, args.out_dir / "device_report.txt");
        std::cout << "Device: " << ctx.renderer() << "\n";

        struct Job { std::string profile; std::string mode; fs::path shader; bool counters; };
        const std::vector<Job> jobs = {
            {"G64_E32", "evaluate", args.shader_dir / "ugts_eval_g64.comp", false},
            {"G64_E32", "evaluate_commit", args.shader_dir / "ugts_eval_g64.comp", true},
            {"G32_E16", "evaluate", args.shader_dir / "ugts_eval_g32.comp", false},
            {"G32_E16", "evaluate_commit", args.shader_dir / "ugts_eval_g32.comp", true},
        };

        std::vector<std::pair<std::string, ProgramInfo>> programs;
        std::vector<BenchRow> all_rows;

        for (const auto& job : jobs) {
            const std::string job_name = job.profile + "_" + job.mode;
            std::cout << "Compiling " << job_name << "...\n";
            const std::string source = inject_counter_mode(read_text(job.shader), job.counters);
            const fs::path cache_base = args.out_dir / "native_cache" / job_name;
            ProgramInfo program = build_program(source, cache_base);

            std::vector<BenchRow> rows;
            if (job.profile == "G64_E32") {
                rows = run_sizes<State64, Event32>(
                    program.program, job.profile, job.mode, job.counters, args,
                    make_g64, cpu_counts_g64, validate_g64_sample);
            } else {
                rows = run_sizes<State32, Event16>(
                    program.program, job.profile, job.mode, job.counters, args,
                    make_g32, cpu_counts_g32, validate_g32_sample);
            }

            for (const auto& r : rows) {
                std::cout << "  N=" << r.candidates
                          << " p50=" << std::fixed << std::setprecision(3) << r.dispatch_p50_ms << " ms"
                          << " CER=" << std::setprecision(2) << r.candidate_rate_mps << " M/s"
                          << " SET=" << r.verified_event_rate_mps << " M/s"
                          << " valid=" << (r.sample_validation && r.counter_validation ? "yes" : "no") << "\n";
            }
            all_rows.insert(all_rows.end(), rows.begin(), rows.end());
            programs.emplace_back(job_name, std::move(program));
        }

        write_results_json(ctx, args, programs, all_rows, args.out_dir / "benchmark_results.json");
        write_results_csv(all_rows, args.out_dir / "benchmark_results.csv");

        for (auto& p : programs) {
            if (p.second.program) glDeleteProgram(p.second.program);
        }

        const bool all_valid = std::all_of(all_rows.begin(), all_rows.end(), [](const BenchRow& r) {
            return r.sample_validation && r.counter_validation;
        });
        if (!all_valid) {
            std::cerr << "Validation failure detected.\n";
            return 2;
        }
        std::cout << "Wrote " << (args.out_dir / "benchmark_results.json") << "\n";
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "UGTS benchmark error: " << e.what() << "\n";
        return 1;
    }
}
