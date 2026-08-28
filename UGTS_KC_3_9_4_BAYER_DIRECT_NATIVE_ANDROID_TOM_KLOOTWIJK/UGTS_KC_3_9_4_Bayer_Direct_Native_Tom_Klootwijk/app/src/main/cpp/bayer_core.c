#include "bayer_core.h"

#define BD_RGB565(r,g,b) ((bd_u16)((((bd_u16)(r) >> 3) << 11) | (((bd_u16)(g) >> 2) << 5) | ((bd_u16)(b) >> 3)))

static bd_i32 bd_abs(bd_i32 v) { return v < 0 ? -v : v; }
static bd_i32 bd_min(bd_i32 a, bd_i32 b) { return a < b ? a : b; }
static bd_i32 bd_max(bd_i32 a, bd_i32 b) { return a > b ? a : b; }
static bd_i32 bd_clamp(bd_i32 v, bd_i32 lo, bd_i32 hi) { return v < lo ? lo : (v > hi ? hi : v); }

static bd_u32 bd_hash32(bd_u32 x) {
    x ^= x >> 16;
    x *= 0x7feb352du;
    x ^= x >> 15;
    x *= 0x846ca68bu;
    x ^= x >> 16;
    return x;
}

static bd_i32 bd_tri8(bd_i32 v) {
    bd_i32 q = v & 255;
    return q < 128 ? q : 255 - q;
}

static bd_i32 bd_approx_norm(bd_i32 x, bd_i32 y) {
    x = bd_abs(x); y = bd_abs(y);
    const bd_i32 hi = bd_max(x, y);
    const bd_i32 lo = bd_min(x, y);
    return hi + (lo >> 1);
}

static bd_i32 bd_grove_field(bd_i32 x, bd_i32 y, bd_i32 w, bd_i32 h, bd_u32 tick, bd_u32 seed) {
    const bd_i32 sky = 22 + ((h - 1 - y) * 58) / bd_max(1, h - 1);
    bd_i32 lum = sky;

    const bd_i32 wave0 = bd_tri8(y * 5 + (bd_i32)(tick * 2u)) - 64;
    const bd_i32 wave1 = bd_tri8(y * 11 - (bd_i32)tick) - 64;
    const bd_i32 center = (w >> 1) + (wave0 * w) / 900 + (wave1 * w) / 1800;
    const bd_i32 trunk_width = 2 + (y * bd_max(8, w / 24)) / bd_max(1, h);
    const bd_i32 dx = bd_abs(x - center);
    if (dx <= trunk_width) lum += 155 - (dx * 70) / bd_max(1, trunk_width);

    for (bd_i32 k = 0; k < 7; ++k) {
        const bd_i32 root_y = (h * (24 + k * 10)) / 100;
        const bd_i32 rise = root_y - y;
        if (rise < 0 || rise > h / 5) continue;
        const bd_i32 side = ((k + (bd_i32)(seed & 1u)) & 1) ? 1 : -1;
        const bd_i32 bend = (bd_tri8(rise * 13 + k * 37 + (bd_i32)tick) - 64) / 10;
        const bd_i32 line_x = center + side * (rise * (3 + (k & 1))) / 2 + bend;
        const bd_i32 branch_width = 1 + (h / 5 - rise) / bd_max(8, h / 25);
        const bd_i32 d = bd_abs(x - line_x);
        if (d <= branch_width) lum += 150 - d * 30;

        const bd_i32 end_x = center + side * (h / 5) * (3 + (k & 1)) / 2;
        const bd_i32 end_y = root_y - h / 5;
        const bd_i32 leaf_r = bd_approx_norm(x - end_x, y - end_y);
        if (leaf_r < bd_max(10, w / 18)) {
            const bd_u32 n = bd_hash32((bd_u32)(x >> 2) ^ ((bd_u32)(y >> 2) << 12) ^ seed ^ (bd_u32)(k * 0x9e37));
            lum += 42 + (bd_i32)((n >> 27) & 31u);
        }
    }

    const bd_i32 halo = bd_approx_norm(x - (w >> 1), y - (h * 42 / 100));
    const bd_i32 ring = bd_abs(((halo + (bd_i32)(tick >> 1)) & 31) - 16);
    if (ring < 2) lum += 38;

    const bd_u32 stars = bd_hash32((bd_u32)(x >> 3) + ((bd_u32)(y >> 3) << 16) + seed);
    if ((stars & 1023u) < 13u && y < h * 3 / 5) lum += 110;
    return bd_clamp(lum, 0, 255);
}

static bd_i32 bd_shell_field(bd_i32 x, bd_i32 y, bd_i32 w, bd_i32 h, bd_u32 tick, bd_u32 seed) {
    const bd_i32 cx = (w >> 1) + (bd_tri8((bd_i32)(tick * 3u)) - 64) * w / 1024;
    const bd_i32 cy = (h >> 1) + (bd_tri8((bd_i32)(tick * 2u + 91u)) - 64) * h / 1024;
    const bd_i32 dx = x - cx;
    const bd_i32 dy = (y - cy) * 2;
    const bd_i32 r = bd_approx_norm(dx, dy);
    const bd_i32 phase = (r * 5 - (bd_i32)(tick * 3u)) & 127;
    const bd_i32 band = bd_abs(phase - 64);
    bd_i32 lum = 26 + ((127 - band) * 150) / 127;
    const bd_i32 spokes = bd_abs((bd_tri8(dx * 3 + dy * 5 + (bd_i32)seed) - 64));
    if (spokes < 7) lum += 70;
    const bd_i32 core = bd_approx_norm(dx, dy);
    if (core < bd_min(w, h) / 7) lum = 235 - core * 90 / bd_max(1, bd_min(w, h) / 7);
    return bd_clamp(lum, 0, 255);
}

static bd_i32 bd_kij_field(bd_i32 x, bd_i32 y, bd_i32 w, bd_i32 h, bd_u32 tick, bd_u32 seed) {
    const bd_u32 a = (bd_u32)(x + (bd_i32)(tick >> 1));
    const bd_u32 b = (bd_u32)(y * 3 - (bd_i32)(tick >> 2));
    const bd_u32 n = bd_hash32((a >> 3) ^ ((b >> 3) << 15) ^ seed);
    bd_i32 lum = 20 + (bd_i32)((n >> 25) & 63u);
    const bd_i32 lattice = bd_abs((bd_i32)((a ^ (b * 5u)) & 63u) - 32);
    lum += (32 - lattice) * 3;
    const bd_i32 diag0 = bd_abs((x * 2 + y - (bd_i32)(tick >> 1)) % bd_max(1, w / 3));
    const bd_i32 diag1 = bd_abs((x - y * 2 + (bd_i32)(tick >> 2)) % bd_max(1, w / 4));
    if (diag0 < 3 || diag1 < 2) lum += 95;

    const bd_i32 cx = w >> 1, cy = h >> 1;
    const bd_i32 ax = bd_abs(x - cx), ay = bd_abs(y - cy);
    if ((ax < w / 40 && ay < h / 3) ||
        (ay < h / 40 && ax < w / 4) ||
        (bd_abs((x - cx) - (y - cy)) < 2 && ax < w / 5)) lum += 95;
    return bd_clamp(lum, 0, 255);
}

static bd_i32 bd_sclp_field(bd_i32 x, bd_i32 y, bd_i32 w, bd_i32 h, bd_u32 tick, bd_u32 seed) {
    const bd_i32 cx = w >> 1;
    const bd_i32 apex_y = h / 8;
    const bd_i32 yy = y - apex_y;
    bd_i32 lum = 18 + ((h - y) * 55) / bd_max(1, h);
    if (yy >= 0) {
        const bd_i32 half = 3 + yy * 3 / 4;
        const bd_i32 edge = bd_abs(bd_abs(x - cx) - half);
        if (edge < 3) lum += 170 - edge * 45;
        if (bd_abs(x - cx) < half && ((yy + (bd_i32)(tick >> 1)) & 31) < 3) lum += 70;
    }
    const bd_i32 dx = x - cx;
    const bd_i32 dy = (y - h * 2 / 3) * 2;
    const bd_i32 r = bd_approx_norm(dx, dy);
    const bd_i32 phase = (r + (bd_i32)(tick >> 1) + (bd_i32)(seed & 63u)) & 63;
    if (phase < 3 || phase > 60) lum += 105;
    const bd_i32 wrap = ((x + (bd_i32)(tick >> 2)) / bd_max(1, w / 8)) & 1;
    if (wrap && y > h / 2) lum += 22;
    return bd_clamp(lum, 0, 255);
}

bd_u8 bd_bayer8(bd_i32 x, bd_i32 y) {
    static const bd_u8 matrix[64] = {
         0,48,12,60, 3,51,15,63,
        32,16,44,28,35,19,47,31,
         8,56, 4,52,11,59, 7,55,
        40,24,36,20,43,27,39,23,
         2,50,14,62, 1,49,13,61,
        34,18,46,30,33,17,45,29,
        10,58, 6,54, 9,57, 5,53,
        42,26,38,22,41,25,37,21
    };
    return matrix[((y & 7) << 3) | (x & 7)];
}

bd_u16 bd_pixel_rgb565(bd_i32 x, bd_i32 y, bd_i32 width, bd_i32 height, const BdFrameState* state) {
    static const bd_u16 palettes[4][4] = {
        { BD_RGB565(1,5,9),   BD_RGB565(7,52,58),  BD_RGB565(26,181,169), BD_RGB565(255,224,132) },
        { BD_RGB565(5,2,15),  BD_RGB565(48,16,78), BD_RGB565(211,43,142), BD_RGB565(255,226,235) },
        { BD_RGB565(7,4,1),   BD_RGB565(74,30,4),  BD_RGB565(236,119,12), BD_RGB565(255,241,177) },
        { BD_RGB565(0,4,14),  BD_RGB565(6,30,88),  BD_RGB565(40,137,213), BD_RGB565(172,255,223) }
    };
    const bd_u8 mode = state ? (state->mode & 3u) : 0u;
    const bd_u32 tick = state ? state->tick : 0u;
    const bd_u32 seed = state ? state->seed : 0x39A4u;
    bd_i32 lum;
    if (mode == 0u) lum = bd_grove_field(x, y, width, height, tick, seed);
    else if (mode == 1u) lum = bd_shell_field(x, y, width, height, tick, seed);
    else if (mode == 2u) lum = bd_kij_field(x, y, width, height, tick, seed);
    else lum = bd_sclp_field(x, y, width, height, tick, seed);

    const bd_i32 threshold = (bd_i32)bd_bayer8(x, y);
    bd_i32 level = (lum * 4 + threshold * 4) >> 8;
    if (level > 3) level = 3;
    return palettes[(state ? state->palette : mode) & 3u][level];
}

void bd_render_rgb565(bd_u16* pixels, bd_i32 stride, bd_i32 width, bd_i32 height, const BdFrameState* state) {
    if (!pixels || stride < width || width <= 0 || height <= 0) return;
    for (bd_i32 y = 0; y < height; ++y) {
        bd_u16* row = pixels + y * stride;
        for (bd_i32 x = 0; x < width; ++x) row[x] = bd_pixel_rgb565(x, y, width, height, state);
    }
}

bd_u32 bd_frame_crc32(const bd_u16* pixels, bd_i32 stride, bd_i32 width, bd_i32 height) {
    bd_u32 crc = 0xffffffffu;
    if (!pixels || stride < width || width <= 0 || height <= 0) return 0u;
    for (bd_i32 y = 0; y < height; ++y) {
        const bd_u16* row = pixels + y * stride;
        for (bd_i32 x = 0; x < width; ++x) {
            bd_u16 value = row[x];
            for (bd_i32 byte_index = 0; byte_index < 2; ++byte_index) {
                bd_u32 c = (crc ^ (bd_u32)(value & 0xffu)) & 0xffu;
                for (bd_i32 bit = 0; bit < 8; ++bit) c = (c >> 1) ^ (0xedb88320u & (0u - (c & 1u)));
                crc = (crc >> 8) ^ c;
                value >>= 8;
            }
        }
    }
    return crc ^ 0xffffffffu;
}
