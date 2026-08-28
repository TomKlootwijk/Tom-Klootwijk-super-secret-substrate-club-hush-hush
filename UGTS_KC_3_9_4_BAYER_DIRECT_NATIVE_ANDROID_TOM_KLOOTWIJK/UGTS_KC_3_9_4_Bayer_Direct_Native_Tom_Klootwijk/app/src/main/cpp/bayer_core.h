#ifndef UGTS_KC_BAYER_CORE_H
#define UGTS_KC_BAYER_CORE_H

typedef unsigned char bd_u8;
typedef unsigned short bd_u16;
typedef unsigned int bd_u32;
typedef signed int bd_i32;

typedef struct BdFrameState {
    bd_u32 seed;
    bd_u32 tick;
    bd_u8 mode;
    bd_u8 palette;
    bd_u8 levels;
    bd_u8 flags;
} BdFrameState;

bd_u8 bd_bayer8(bd_i32 x, bd_i32 y);
bd_u16 bd_pixel_rgb565(bd_i32 x, bd_i32 y, bd_i32 width, bd_i32 height, const BdFrameState* state);
void bd_render_rgb565(bd_u16* pixels, bd_i32 stride, bd_i32 width, bd_i32 height, const BdFrameState* state);
bd_u32 bd_frame_crc32(const bd_u16* pixels, bd_i32 stride, bd_i32 width, bd_i32 height);

#endif
