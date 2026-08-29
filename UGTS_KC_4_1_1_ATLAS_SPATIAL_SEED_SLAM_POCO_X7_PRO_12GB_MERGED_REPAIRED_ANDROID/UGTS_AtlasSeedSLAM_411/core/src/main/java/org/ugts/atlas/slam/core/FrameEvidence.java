package org.ugts.atlas.slam.core;

/** Compact measured evidence retained for each analyzed frame. */
public final class FrameEvidence {
    public final long frameIndex;
    public final long timestampNs;
    public final int width;
    public final int height;
    public final int lumaMeanQ8;
    public final int lumaVarianceQ8;
    public final int gradientMeanQ8;
    public final int featureCount;
    public final int matchCount;
    public final int inlierCount;
    public final short qw;
    public final short qx;
    public final short qy;
    public final short qz;
    public final short axMm;
    public final short ayMm;
    public final short azMm;
    public final boolean synthetic;

    public FrameEvidence(
            long frameIndex,
            long timestampNs,
            int width,
            int height,
            int lumaMeanQ8,
            int lumaVarianceQ8,
            int gradientMeanQ8,
            int featureCount,
            int matchCount,
            int inlierCount,
            short qw,
            short qx,
            short qy,
            short qz,
            short axMm,
            short ayMm,
            short azMm,
            boolean synthetic) {
        this.frameIndex = frameIndex;
        this.timestampNs = timestampNs;
        this.width = width;
        this.height = height;
        this.lumaMeanQ8 = lumaMeanQ8;
        this.lumaVarianceQ8 = lumaVarianceQ8;
        this.gradientMeanQ8 = gradientMeanQ8;
        this.featureCount = featureCount;
        this.matchCount = matchCount;
        this.inlierCount = inlierCount;
        this.qw = qw;
        this.qx = qx;
        this.qy = qy;
        this.qz = qz;
        this.axMm = axMm;
        this.ayMm = ayMm;
        this.azMm = azMm;
        this.synthetic = synthetic;
    }

    public static FrameEvidence summarize(
            GrayFrame frame,
            long frameIndex,
            SeededSchedule schedule,
            Quat orientation,
            Vec3 displacement,
            int featureCount,
            int matchCount,
            int inlierCount,
            boolean synthetic) {
        int[] indices = schedule.pixelIndices(frame.width, frame.height, frameIndex, 256);
        long sum = 0;
        long sumSq = 0;
        long gradient = 0;
        for (int index : indices) {
            int value = frame.pixels[index] & 255;
            sum += value;
            sumSq += (long) value * value;
            int x = index % frame.width;
            int y = index / frame.width;
            if (x > 0 && x + 1 < frame.width && y > 0 && y + 1 < frame.height) {
                gradient += frame.gradientL1(x, y);
            }
        }
        int count = Math.max(1, indices.length);
        double mean = sum / (double) count;
        double variance = Math.max(0.0, sumSq / (double) count - mean * mean);
        Quat q = orientation == null ? Quat.IDENTITY : orientation;
        Vec3 a = displacement == null ? Vec3.ZERO : displacement;
        return new FrameEvidence(
                frameIndex,
                frame.timestampNs,
                frame.width,
                frame.height,
                clampU16(Math.round(mean * 256.0)),
                clampU16(Math.round(variance * 8.0)),
                clampU16(Math.round(gradient * 256.0 / count)),
                Math.max(0, featureCount),
                Math.max(0, matchCount),
                Math.max(0, inlierCount),
                q16(q.w), q16(q.x), q16(q.y), q16(q.z),
                mm(a.x), mm(a.y), mm(a.z),
                synthetic);
    }

    private static short q16(double value) {
        return (short) Math.round(Vec3.clamp(value, -1.0, 1.0) * 32767.0);
    }

    private static short mm(double value) {
        long result = Math.round(value * 1000.0);
        return (short) Math.max(Short.MIN_VALUE, Math.min(Short.MAX_VALUE, result));
    }

    private static int clampU16(long value) {
        return (int) Math.max(0, Math.min(65535, value));
    }
}
