package org.ugts.atlas.slam;

import android.os.SystemClock;
import android.util.Log;
import java.util.Arrays;
import java.util.Locale;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import org.ugts.atlas.slam.core.CameraModel;
import org.ugts.atlas.slam.core.GrayFrame;
import org.ugts.atlas.slam.core.Quat;
import org.ugts.atlas.slam.core.Seed128;
import org.ugts.atlas.slam.core.SeededSchedule;
import org.ugts.atlas.slam.core.SlamEngine;
import org.ugts.atlas.slam.core.SlamSnapshot;
import org.ugts.atlas.slam.core.Vec3;

/** Deterministic fallback fixture; every proposal remains tagged synthetic by the engine. */
final class SyntheticFrameSource implements AutoCloseable {
    private static final String PERF_TAG = "UGTS_PERF";
    private static final int WIDTH = 320;
    private static final int HEIGHT = 180;
    private final SlamEngine engine;
    private final FrameAnalyzer.Listener listener;
    private ScheduledExecutorService executor;
    private long frameIndex;
    private long baseNs;
    private SeededSchedule schedule;
    private final long[] processingDurationsNs = new long[300];
    private long runStartNs;

    SyntheticFrameSource(SlamEngine engine, FrameAnalyzer.Listener listener) {
        this.engine = engine;
        this.listener = listener;
    }

    synchronized void start(Seed128 seed, long nowNs) {
        stop();
        frameIndex = 0;
        baseNs = nowNs;
        schedule = new SeededSchedule(seed);
        runStartNs = SystemClock.elapsedRealtimeNanos();
        executor = Executors.newSingleThreadScheduledExecutor(
                runnable -> new Thread(runnable, "ugts-demo-frames"));
        executor.scheduleAtFixedRate(this::tick, 0, 100, TimeUnit.MILLISECONDS);
    }

    synchronized void stop() {
        if (executor != null) {
            executor.shutdownNow();
            executor = null;
        }
    }

    private void tick() {
        try {
            long index = frameIndex++;
            if (index >= 300) {
                stop();
                return;
            }
            long timestampNs = baseNs + index * 100_000_000L;
            long processingStartNs = SystemClock.elapsedRealtimeNanos();
            GrayFrame frame = new GrayFrame(WIDTH, HEIGHT, timestampNs, pixels(index));
            double yaw = Math.sin(index * 0.025) * 0.10;
            Quat orientation = Quat.fromAxisAngle(new Vec3(0, 1, 0), yaw);
            Vec3 displacement = new Vec3(0.0025, 0.0, 0.0035);
            SlamSnapshot snapshot = engine.process(
                    frame,
                    CameraModel.declaredFallback(WIDTH, HEIGHT),
                    orientation,
                    displacement);
            processingDurationsNs[(int) index] =
                    SystemClock.elapsedRealtimeNanos() - processingStartNs;
            if ((index + 1) % 50 == 0) {
                reportPerformance((int) index + 1);
            }
            if (snapshot != null) {
                listener.onSnapshot(snapshot, "DEMO/10 fps");
            }
        } catch (Throwable error) {
            listener.onError(error);
        }
    }

    private void reportPerformance(int count) {
        long[] sorted = Arrays.copyOf(processingDurationsNs, count);
        Arrays.sort(sorted);
        double elapsedSeconds =
                (SystemClock.elapsedRealtimeNanos() - runStartNs) / 1_000_000_000.0;
        Log.i(PERF_TAG, String.format(
                Locale.ROOT,
                "source=demo elapsedSec=%.3f frames=%d effectiveFps=%.3f "
                        + "processingP50Ms=%.3f processingP95Ms=%.3f processingP99Ms=%.3f",
                elapsedSeconds,
                count,
                count / elapsedSeconds,
                percentile(sorted, 0.50) / 1_000_000.0,
                percentile(sorted, 0.95) / 1_000_000.0,
                percentile(sorted, 0.99) / 1_000_000.0));
    }

    private static long percentile(long[] sorted, double fraction) {
        int index = (int) Math.ceil(fraction * sorted.length) - 1;
        return sorted[Math.max(0, Math.min(sorted.length - 1, index))];
    }

    private byte[] pixels(long index) {
        byte[] output = new byte[WIDTH * HEIGHT];
        int shiftX = (int) (index % 37);
        int shiftY = (int) ((index / 3) % 19);
        for (int y = 0; y < HEIGHT; y++) {
            for (int x = 0; x < WIDTH; x++) {
                int sx = x + shiftX;
                int sy = y + shiftY;
                int checker = (((sx / 12) ^ (sy / 12)) & 1) * 72;
                int waves = (int) (42.0 * Math.sin(sx * 0.083)
                        + 35.0 * Math.cos(sy * 0.107)
                        + 26.0 * Math.sin((sx + sy) * 0.047));
                int dots = 0;
                for (int marker = 0; marker < 12; marker++) {
                    int cx = schedule.bounded(100 + marker, marker, WIDTH);
                    int cy = schedule.bounded(200 + marker, marker, HEIGHT);
                    int dx = Math.floorMod(x - cx + shiftX, WIDTH);
                    int dy = Math.floorMod(y - cy + shiftY, HEIGHT);
                    dx = Math.min(dx, WIDTH - dx);
                    dy = Math.min(dy, HEIGHT - dy);
                    if (dx * dx + dy * dy < 36) {
                        dots += 90;
                    }
                }
                int value = 105 + checker + waves + dots;
                output[y * WIDTH + x] = (byte) Math.max(0, Math.min(255, value));
            }
        }
        return output;
    }

    @Override
    public void close() {
        stop();
    }
}
