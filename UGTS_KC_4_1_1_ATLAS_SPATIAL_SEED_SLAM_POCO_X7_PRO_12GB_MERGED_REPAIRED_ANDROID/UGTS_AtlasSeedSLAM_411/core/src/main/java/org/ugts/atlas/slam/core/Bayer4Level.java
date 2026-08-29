package org.ugts.atlas.slam.core;

/** Exact 8x8 ordered Bayer projection to four luma levels; presentation only. */
public final class Bayer4Level {
    private static final int[] MATRIX = {
        0, 32, 8, 40, 2, 34, 10, 42,
        48, 16, 56, 24, 50, 18, 58, 26,
        12, 44, 4, 36, 14, 46, 6, 38,
        60, 28, 52, 20, 62, 30, 54, 22,
        3, 35, 11, 43, 1, 33, 9, 41,
        51, 19, 59, 27, 49, 17, 57, 25,
        15, 47, 7, 39, 13, 45, 5, 37,
        63, 31, 55, 23, 61, 29, 53, 21
    };

    private Bayer4Level() {}

    public static int quantize(int luma, int x, int y) {
        int bounded = Math.max(0, Math.min(255, luma));
        int scaled = bounded * 3;
        int base = scaled >>> 8;
        int remainder = scaled & 255;
        int threshold = MATRIX[(y & 7) * 8 + (x & 7)] * 4 + 2;
        if (remainder > threshold && base < 3) {
            base++;
        }
        return base;
    }

    public static byte[] project(byte[] luma, int width, int height) {
        if (luma == null || width <= 0 || height <= 0 || luma.length != width * height) {
            throw new IllegalArgumentException("invalid luma image");
        }
        byte[] output = new byte[luma.length];
        for (int y = 0; y < height; y++) {
            for (int x = 0; x < width; x++) {
                int level = quantize(luma[y * width + x] & 255, x, y);
                output[y * width + x] = (byte) (level * 85);
            }
        }
        return output;
    }
}
