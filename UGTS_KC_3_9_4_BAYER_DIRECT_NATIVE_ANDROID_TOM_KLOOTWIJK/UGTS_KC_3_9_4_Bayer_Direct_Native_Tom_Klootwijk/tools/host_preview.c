#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <time.h>
#include "../app/src/main/cpp/bayer_core.h"

static void write_ppm(const char* path, const bd_u16* pixels, int width, int height) {
    FILE* file = fopen(path, "wb");
    if (!file) return;
    fprintf(file, "P6\n%d %d\n255\n", width, height);
    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            const bd_u16 v = pixels[y * width + x];
            const unsigned r5 = (v >> 11) & 31u;
            const unsigned g6 = (v >> 5) & 63u;
            const unsigned b5 = v & 31u;
            const unsigned char rgb[3] = {
                (unsigned char)((r5 << 3) | (r5 >> 2)),
                (unsigned char)((g6 << 2) | (g6 >> 4)),
                (unsigned char)((b5 << 3) | (b5 >> 2))
            };
            fwrite(rgb, 1, 3, file);
        }
    }
    fclose(file);
}

static double seconds(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec * 1.0e-9;
}

int main(int argc, char** argv) {
    const int width = argc > 1 ? atoi(argv[1]) : 480;
    const int height = argc > 2 ? atoi(argv[2]) : 216;
    const int frames = argc > 3 ? atoi(argv[3]) : 300;
    const char* output = argc > 4 ? argv[4] : "preview.ppm";
    const int forced_mode = argc > 5 ? atoi(argv[5]) : -1;
    bd_u16* pixels = (bd_u16*)malloc((size_t)width * (size_t)height * sizeof(bd_u16));
    if (!pixels) return 2;
    BdFrameState state = {0x39A4B47Eu, 0u, 0u, 0u, 4u, 1u};
    const double start = seconds();
    for (int i = 0; i < frames; ++i) {
        state.tick = (bd_u32)i;
        state.mode = (bd_u8)(forced_mode >= 0 ? (forced_mode & 3) : ((i / 75) & 3));
        state.palette = state.mode;
        bd_render_rgb565(pixels, width, width, height, &state);
    }
    const double elapsed = seconds() - start;
    const bd_u32 crc = bd_frame_crc32(pixels, width, width, height);
    write_ppm(output, pixels, width, height);
    printf("width=%d height=%d frames=%d seconds=%.9f fps=%.3f mpix_s=%.3f crc32=%08x\n",
           width, height, frames, elapsed, frames / elapsed,
           ((double)width * (double)height * (double)frames / elapsed) / 1.0e6,
           crc);
    free(pixels);
    return 0;
}
