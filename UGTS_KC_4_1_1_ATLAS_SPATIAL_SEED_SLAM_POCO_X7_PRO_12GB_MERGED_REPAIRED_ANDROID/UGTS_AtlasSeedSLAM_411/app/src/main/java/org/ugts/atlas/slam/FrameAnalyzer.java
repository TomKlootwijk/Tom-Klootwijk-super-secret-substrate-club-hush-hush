package org.ugts.atlas.slam;

import android.content.Context;
import android.media.Image;
import android.os.SystemClock;
import android.util.Log;
import java.util.Arrays;
import java.util.Locale;
import org.ugts.atlas.slam.core.CameraModel;
import org.ugts.atlas.slam.core.GrayFrame;
import org.ugts.atlas.slam.core.Quat;
import org.ugts.atlas.slam.core.SlamEngine;
import org.ugts.atlas.slam.core.SlamSnapshot;
import org.ugts.atlas.slam.core.Vec3;

/** Single-queue frame analysis. Every acquired Image is closed exactly once. */
final class FrameAnalyzer {
    private static final String PERF_TAG = "UGTS_PERF";
    private static final long PERF_REPORT_INTERVAL_NS = 5_000_000_000L;

    interface Listener {
        void onSnapshot(SlamSnapshot snapshot, String thermalLabel);
        void onError(Throwable error);
    }

    private final Context context;
    private final SlamEngine engine;
    private final SensorFusion sensors;
    private final ThermalGovernor thermal;
    private final Listener listener;
    private long lastAcceptedNs;
    private long lastUiNs;
    private CameraModel camera;
    private String cameraId;
    private int rotationDegrees;
    private final long[] analysisDurationsNs = new long[1024];
    private int analysisSampleCount;
    private long performanceStartImageNs;
    private long performanceLastReportImageNs;
    private long performanceReceived;
    private long performanceAccepted;
    private long performanceThrottled;

    FrameAnalyzer(
            Context context,
            SlamEngine engine,
            SensorFusion sensors,
            ThermalGovernor thermal,
            Listener listener) {
        this.context = context.getApplicationContext();
        this.engine = engine;
        this.sensors = sensors;
        this.thermal = thermal;
        this.listener = listener;
    }

    void setCamera(String id, int clockwiseRotationDegrees) {
        cameraId = id;
        rotationDegrees = clockwiseRotationDegrees;
        camera = null;
    }

    void analyze(Image image) {
        try {
            long ts = image.getTimestamp();
            boolean scanning = engine.state() == SlamEngine.State.SCANNING;
            if (scanning && performanceStartImageNs == 0) {
                performanceStartImageNs = ts;
                performanceLastReportImageNs = ts;
                performanceReceived = 0;
                performanceAccepted = 0;
                performanceThrottled = 0;
                analysisSampleCount = 0;
            } else if (!scanning && performanceStartImageNs != 0) {
                reportPerformance("final", lastAcceptedNs);
                performanceStartImageNs = 0;
            }
            if (scanning) {
                performanceReceived++;
            }
            if (ts - lastAcceptedNs < thermal.minimumFrameIntervalNs()) {
                if (scanning) {
                    performanceThrottled++;
                }
                return;
            }
            lastAcceptedNs = ts;
            long analysisStartNs = SystemClock.elapsedRealtimeNanos();
            GrayFrame gray = LumaResampler.convert(image, rotationDegrees, 640);
            if (camera == null || camera.width != gray.width || camera.height != gray.height) {
                camera = CameraCalibration.forCamera(
                        context, cameraId, gray.width, gray.height, rotationDegrees);
            }
            Quat orientation = sensors.orientationAt(ts);
            Vec3 displacementHint = sensors.displacementHint(
                    lastUiNs == 0 ? ts : lastUiNs, ts);
            SlamSnapshot snapshot = engine.process(gray, camera, orientation, displacementHint);
            if (scanning) {
                analysisDurationsNs[analysisSampleCount % analysisDurationsNs.length] =
                        SystemClock.elapsedRealtimeNanos() - analysisStartNs;
                analysisSampleCount++;
                performanceAccepted++;
                if (ts - performanceLastReportImageNs >= PERF_REPORT_INTERVAL_NS) {
                    reportPerformance("periodic", ts);
                    performanceLastReportImageNs = ts;
                }
            }
            if (snapshot != null && ts - lastUiNs >= 120_000_000L) {
                lastUiNs = ts;
                listener.onSnapshot(snapshot, thermal.label());
            }
        } catch (Throwable error) {
            listener.onError(error);
        } finally {
            image.close();
        }
    }

    private void reportPerformance(String phase, long imageTimestampNs) {
        int count = Math.min(analysisSampleCount, analysisDurationsNs.length);
        if (count == 0 || imageTimestampNs <= performanceStartImageNs) {
            return;
        }
        long[] sorted = new long[count];
        int start = Math.max(0, analysisSampleCount - count);
        for (int i = 0; i < count; i++) {
            sorted[i] = analysisDurationsNs[(start + i) % analysisDurationsNs.length];
        }
        Arrays.sort(sorted);
        double elapsedSeconds = (imageTimestampNs - performanceStartImageNs) / 1_000_000_000.0;
        Log.i(PERF_TAG, String.format(
                Locale.ROOT,
                "source=camera phase=%s elapsedSec=%.3f received=%d accepted=%d throttled=%d "
                        + "acceptedFps=%.3f analysisP50Ms=%.3f analysisP95Ms=%.3f "
                        + "analysisP99Ms=%.3f samples=%d",
                phase,
                elapsedSeconds,
                performanceReceived,
                performanceAccepted,
                performanceThrottled,
                performanceAccepted / elapsedSeconds,
                percentile(sorted, 0.50) / 1_000_000.0,
                percentile(sorted, 0.95) / 1_000_000.0,
                percentile(sorted, 0.99) / 1_000_000.0,
                count));
    }

    private static long percentile(long[] sorted, double fraction) {
        int index = (int) Math.ceil(fraction * sorted.length) - 1;
        return sorted[Math.max(0, Math.min(sorted.length - 1, index))];
    }
}
