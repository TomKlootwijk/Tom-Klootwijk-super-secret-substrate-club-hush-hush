package org.ugts.atlas.slam.core;

/** Exact 21-bit-per-axis Morton key for signed voxel coordinates. */
public final class Morton3D {
    private static final int BITS = 21;
    private static final int BIAS = 1 << 20;
    private static final int MASK = (1 << BITS) - 1;

    private Morton3D() {}

    public static long encodeSigned21(int x, int y, int z) {
        int ux = checked(x);
        int uy = checked(y);
        int uz = checked(z);
        long result = 0L;
        for (int bit = 0; bit < BITS; bit++) {
            result |= ((long) ((ux >>> bit) & 1)) << (bit * 3);
            result |= ((long) ((uy >>> bit) & 1)) << (bit * 3 + 1);
            result |= ((long) ((uz >>> bit) & 1)) << (bit * 3 + 2);
        }
        return result;
    }

    public static int decodeX(long key) {
        return compact(key, 0) - BIAS;
    }

    public static int decodeY(long key) {
        return compact(key, 1) - BIAS;
    }

    public static int decodeZ(long key) {
        return compact(key, 2) - BIAS;
    }

    private static int checked(int value) {
        if (value < -BIAS || value >= BIAS) {
            throw new IllegalArgumentException("coordinate outside signed 21-bit range");
        }
        return value + BIAS;
    }

    private static int compact(long key, int lane) {
        int output = 0;
        for (int bit = 0; bit < BITS; bit++) {
            output |= (int) (((key >>> (bit * 3 + lane)) & 1L) << bit);
        }
        return output & MASK;
    }
}
