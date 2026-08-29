package org.ugts.atlas.slam.core;

/** Deterministic SplitMix64 schedule for bounded frame samples and stable choices. */
public final class SeededSchedule {
    private final Seed128 seed;

    public SeededSchedule(Seed128 seed) {
        this.seed = seed == null ? Seed128.ZERO : seed;
    }

    public long value(long stream, long index) {
        long state = seed.low
                ^ Long.rotateLeft(seed.high, 29)
                ^ mix(stream * 0x9e3779b97f4a7c15L)
                ^ mix(index * 0xd1b54a32d192ed03L);
        return mix(state);
    }

    public int bounded(long stream, long index, int bound) {
        if (bound <= 0) {
            throw new IllegalArgumentException("bound");
        }
        return (int) Long.remainderUnsigned(value(stream, index), bound);
    }

    public int[] pixelIndices(int width, int height, long frameIndex, int count) {
        if (width <= 0 || height <= 0 || count < 0) {
            throw new IllegalArgumentException("invalid schedule shape");
        }
        int pixels = Math.multiplyExact(width, height);
        int[] output = new int[Math.min(count, pixels)];
        for (int index = 0; index < output.length; index++) {
            output[index] = bounded(frameIndex, index, pixels);
        }
        return output;
    }

    private static long mix(long value) {
        value += 0x9e3779b97f4a7c15L;
        value = (value ^ (value >>> 30)) * 0xbf58476d1ce4e5b9L;
        value = (value ^ (value >>> 27)) * 0x94d049bb133111ebL;
        return value ^ (value >>> 31);
    }
}
