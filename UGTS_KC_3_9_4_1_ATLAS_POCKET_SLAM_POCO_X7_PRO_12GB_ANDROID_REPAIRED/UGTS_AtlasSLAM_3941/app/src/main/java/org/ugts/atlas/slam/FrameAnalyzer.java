package org.ugts.atlas.slam;

import android.content.Context;
import android.media.Image;
import org.ugts.atlas.slam.core.CameraModel;
import org.ugts.atlas.slam.core.GrayFrame;
import org.ugts.atlas.slam.core.Quat;
import org.ugts.atlas.slam.core.SlamEngine;
import org.ugts.atlas.slam.core.SlamSnapshot;
import org.ugts.atlas.slam.core.Vec3;

/** Single-queue frame analysis. Every acquired Image is closed exactly once. */
final class FrameAnalyzer {
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
            if (ts - lastAcceptedNs < thermal.minimumFrameIntervalNs()) {
                return;
            }
            lastAcceptedNs = ts;
            GrayFrame gray = LumaResampler.convert(image, rotationDegrees, 640);
            if (camera == null || camera.width != gray.width || camera.height != gray.height) {
                camera = CameraCalibration.forCamera(
                        context, cameraId, gray.width, gray.height, rotationDegrees);
            }
            Quat orientation = sensors.orientationAt(ts);
            Vec3 displacementHint = sensors.displacementHint(
                    lastUiNs == 0 ? ts : lastUiNs, ts);
            SlamSnapshot snapshot = engine.process(gray, camera, orientation, displacementHint);
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
}
