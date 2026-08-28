package org.ugts.atlas.slam.core;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * Keyframe identity/pose/signature are durable for the session. Pixel and
 * descriptor payloads are deliberately retained only while the keyframe is
 * the active adjacent-frame mapping reference.
 */
public final class Keyframe {
    public final long id, timestampNs;
    public Pose pose;
    public final CameraModel camera;
    public GrayFrame frame;
    public List<Feature> features;
    public final long signature;

    public Keyframe(
            long id,
            long timestampNs,
            Pose pose,
            CameraModel camera,
            GrayFrame frame,
            List<Feature> features) {
        this.id = id;
        this.timestampNs = timestampNs;
        this.pose = pose;
        this.camera = camera;
        this.frame = frame.copy();
        this.features = Collections.unmodifiableList(new ArrayList<>(features));
        this.signature = signature(features);
    }

    public void releaseHeavyData() {
        frame = null;
        features = Collections.emptyList();
    }

    private static long signature(List<Feature> features) {
        int[] votes = new int[64];
        for (Feature feature : features) {
            long value = feature.d0
                    ^ Long.rotateLeft(feature.d1, 11)
                    ^ Long.rotateLeft(feature.d2, 29)
                    ^ Long.rotateLeft(feature.d3, 47);
            for (int i = 0; i < 64; i++) {
                votes[i] += ((value >>> i) & 1L) == 1 ? 1 : -1;
            }
        }
        long result = 0;
        for (int i = 0; i < 64; i++) {
            if (votes[i] >= 0) {
                result |= 1L << i;
            }
        }
        return result;
    }
}
