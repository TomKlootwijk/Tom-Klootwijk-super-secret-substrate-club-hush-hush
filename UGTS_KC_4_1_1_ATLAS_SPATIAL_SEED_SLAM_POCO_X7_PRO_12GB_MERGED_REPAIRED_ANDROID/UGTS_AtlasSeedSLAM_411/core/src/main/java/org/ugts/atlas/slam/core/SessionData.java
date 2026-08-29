package org.ugts.atlas.slam.core;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/** Immutable export snapshot. Real-world photons are not implied by the seed. */
public final class SessionData {
    public final String sessionId;
    public final String scaleState;
    public final String cameraSource;
    public final long startedNs;
    public final long endedNs;
    public final long frames;
    public final double metricScale;
    public final double voxelSize;
    public final boolean cameraCalibrated;
    public final List<VoxelMap.Cell> cells;
    public final List<Keyframe> keyframes;
    public final List<LedgerEvent> events;
    public final Seed128 seed;
    public final List<FrameEvidence> frameEvidence;
    public final String finalStateHash;
    public final long rawInputBytes;
    public final int rejectedProposals;
    public final boolean synthetic;
    public final int requestedCaptureFps;
    public final int featureBudget;
    public final String captureProfileSha256;
    public final String calibrationSha256;
    public final String nativeIntegrityStatus;

    public SessionData(
            String sessionId,
            String scaleState,
            String cameraSource,
            long startedNs,
            long endedNs,
            long frames,
            double metricScale,
            double voxelSize,
            boolean cameraCalibrated,
            List<VoxelMap.Cell> cells,
            List<Keyframe> keyframes,
            List<LedgerEvent> events,
            Seed128 seed,
            List<FrameEvidence> frameEvidence,
            String finalStateHash,
            long rawInputBytes,
            int rejectedProposals,
            boolean synthetic,
            int requestedCaptureFps,
            int featureBudget,
            String captureProfileSha256,
            String calibrationSha256,
            String nativeIntegrityStatus) {
        this.sessionId = sessionId;
        this.scaleState = scaleState;
        this.cameraSource = cameraSource;
        this.startedNs = startedNs;
        this.endedNs = endedNs;
        this.frames = frames;
        this.metricScale = metricScale;
        this.voxelSize = voxelSize;
        this.cameraCalibrated = cameraCalibrated;
        this.cells = Collections.unmodifiableList(new ArrayList<>(cells));
        this.keyframes = Collections.unmodifiableList(new ArrayList<>(keyframes));
        this.events = Collections.unmodifiableList(new ArrayList<>(events));
        this.seed = seed == null ? Seed128.ZERO : seed;
        this.frameEvidence = Collections.unmodifiableList(new ArrayList<>(frameEvidence));
        this.finalStateHash = finalStateHash == null ? "" : finalStateHash;
        this.rawInputBytes = rawInputBytes;
        this.rejectedProposals = rejectedProposals;
        this.synthetic = synthetic;
        this.requestedCaptureFps = requestedCaptureFps;
        this.featureBudget = featureBudget;
        this.captureProfileSha256 = normalizeHash(captureProfileSha256);
        this.calibrationSha256 = normalizeHash(calibrationSha256);
        this.nativeIntegrityStatus = nativeIntegrityStatus == null ? "java_fallback" : nativeIntegrityStatus;
    }

    /** Compatibility constructor retained for tools that consume the 3.9.4.1 shape. */
    public SessionData(
            String sessionId,
            String scaleState,
            String cameraSource,
            long startedNs,
            long endedNs,
            long frames,
            double metricScale,
            double voxelSize,
            boolean cameraCalibrated,
            List<VoxelMap.Cell> cells,
            List<Keyframe> keyframes,
            List<LedgerEvent> events) {
        this(
                sessionId,
                scaleState,
                cameraSource,
                startedNs,
                endedNs,
                frames,
                metricScale,
                voxelSize,
                cameraCalibrated,
                cells,
                keyframes,
                events,
                Seed128.derive(String.valueOf(sessionId), startedNs),
                Collections.emptyList(),
                "",
                0L,
                0,
                false,
                15,
                1100,
                Hashing.hex(Hashing.sha256Text("ugts.capture-profile/4.1.1")),
                Hashing.hex(Hashing.sha256Text("uncalibrated")),
                "java_fallback");
    }

    private static String normalizeHash(String value) {
        if (value == null || value.length() != 64) {
            return Hashing.hex(Hashing.sha256Text(String.valueOf(value)));
        }
        return value.toLowerCase();
    }
}
