package org.ugts.atlas.slam.core;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.TreeMap;

/**
 * Offline monocular visual-inertial scanner with an explicit proposal/verify/
 * commit boundary and KSEED-compatible measured evidence retention.
 */
public final class SlamEngine {
    public enum State { IDLE, SCANNING, PAUSED, FINISHED }

    private final SlamConfig config;
    private final FastBrief detector = new FastBrief();
    private final DescriptorMatcher matcher = new DescriptorMatcher();
    private final VisualInertialEstimator motionEstimator = new VisualInertialEstimator();
    private final Triangulator triangulator = new Triangulator();
    private final SemiDenseMapper semiDense = new SemiDenseMapper();
    private final ProposalVerifier verifier = new ProposalVerifier();

    private VoxelMap map;
    private final ArrayList<Keyframe> keyframes = new ArrayList<>();
    private final ArrayList<Vec3> trajectory = new ArrayList<>();
    private final ArrayList<LedgerEvent> ledger = new ArrayList<>();
    private final ArrayList<FrameEvidence> evidence = new ArrayList<>();

    private State state = State.IDLE;
    private String sessionId = "";
    private long startedNs;
    private long endedNs;
    private long frameId;
    private long eventSeq;
    private long rawInputBytes;
    private int rejectedProposals;
    private boolean syntheticSession;
    private String nativeIntegrityStatus = "java_fallback";
    private Seed128 seed = Seed128.ZERO;
    private SeededSchedule schedule = new SeededSchedule(seed);
    private byte[] stateHash = Hashing.sha256Text("UGTS-KC-4.1.1-IDLE");

    private GrayFrame previousFrame;
    private List<Feature> previousFeatures;
    private Pose previousPose = Pose.IDENTITY;
    private Quat orientationOrigin;
    private Quat previousOrientation;
    private Keyframe lastKeyframe;
    private CameraModel camera;
    private double metricScale = 1.0;
    private boolean scaleCalibrated;
    private SlamSnapshot lastSnapshot;

    public SlamEngine(SlamConfig config) {
        this.config = config.copy();
        resetContainers();
    }

    private void resetContainers() {
        map = new VoxelMap(config.voxelSize, config.maxVoxels);
        keyframes.clear();
        trajectory.clear();
        ledger.clear();
        evidence.clear();
        previousFrame = null;
        previousFeatures = null;
        lastKeyframe = null;
        camera = null;
        lastSnapshot = null;
        rawInputBytes = 0L;
        rejectedProposals = 0;
    }

    public synchronized void start(String sessionId, long nowNs) {
        start(sessionId, nowNs, Seed128.derive(sessionId, nowNs), false);
    }

    public synchronized void start(
            String sessionId, long nowNs, Seed128 selectedSeed, boolean synthetic) {
        resetContainers();
        this.sessionId = sessionId == null || sessionId.isEmpty() ? "session" : sessionId;
        startedNs = nowNs;
        endedNs = 0;
        frameId = 0;
        eventSeq = 0;
        metricScale = 1.0;
        scaleCalibrated = false;
        orientationOrigin = null;
        previousOrientation = null;
        previousPose = Pose.IDENTITY;
        state = State.SCANNING;
        seed = selectedSeed == null ? Seed128.derive(this.sessionId, nowNs) : selectedSeed;
        schedule = new SeededSchedule(seed);
        syntheticSession = synthetic;
        stateHash = Hashing.sha256(
                "UGTS-KC-4.1.1-STATE".getBytes(StandardCharsets.UTF_8),
                seed.toBytes(),
                this.sessionId.getBytes(StandardCharsets.UTF_8),
                Hashing.longLe(nowNs));
        commitSystemEvent(
                nowNs,
                "session_started",
                fields(
                        "session_id", this.sessionId,
                        "seed", seed.toHex(),
                        "synthetic", Boolean.toString(syntheticSession)));
    }

    public synchronized void setNativeIntegrityStatus(String value) {
        nativeIntegrityStatus = value == null ? "java_fallback" : value;
    }

    public synchronized void pause(long nowNs) {
        if (state == State.SCANNING) {
            state = State.PAUSED;
            commitSystemEvent(nowNs, "capture_paused", fields());
        }
    }

    public synchronized void resume(long nowNs) {
        if (state == State.PAUSED) {
            state = State.SCANNING;
            previousFrame = null;
            previousFeatures = null;
            commitSystemEvent(nowNs, "capture_resumed", fields());
        }
    }

    public synchronized void finish(long nowNs) {
        if (state == State.SCANNING || state == State.PAUSED) {
            state = State.FINISHED;
            endedNs = nowNs;
            if (lastKeyframe != null) {
                lastKeyframe.releaseHeavyData();
            }
            commitSystemEvent(
                    nowNs,
                    "session_finished",
                    fields(
                            "frames", Long.toString(frameId),
                            "voxels", Integer.toString(map.size()),
                            "state_hash", Hashing.hex(stateHash)));
        }
    }

    public synchronized State state() {
        return state;
    }

    public synchronized Seed128 seed() {
        return seed;
    }

    public synchronized SlamSnapshot process(
            GrayFrame frame,
            CameraModel cameraModel,
            Quat absoluteOrientation,
            Vec3 inertialDisplacementHint) {
        if (state != State.SCANNING || frame == null || cameraModel == null) {
            return lastSnapshot;
        }
        frameId++;
        rawInputBytes += frame.pixels.length;
        camera = cameraModel;
        Quat absolute = absoluteOrientation == null ? Quat.IDENTITY : absoluteOrientation;
        if (orientationOrigin == null) {
            orientationOrigin = absolute;
        }
        Quat orientation = orientationOrigin.conjugate().multiply(absolute);
        List<Feature> features = detector.detect(frame, config.maxFeatures, config.fastThreshold);
        List<Match> matches = new ArrayList<>();
        MotionEstimate motion = MotionEstimate.invalid(0);
        Pose pose = previousPose;

        if (previousFrame == null) {
            pose = new Pose(orientation, Vec3.ZERO);
            proposeKeyframe(frame, features, pose, MotionEstimate.invalid(0), true);
            commitSystemEvent(
                    frame.timestampNs,
                    "tracking_initialized",
                    fields(
                            "features", Integer.toString(features.size()),
                            "intrinsics", camera.source));
        } else {
            matches = matcher.match(previousFeatures, features);
            motion = motionEstimator.estimate(
                    previousFeatures,
                    features,
                    matches,
                    camera,
                    previousPose.orientation,
                    orientation,
                    config.minimumMatches);
            if (motion.valid) {
                double step = motion.nominalStep;
                if (inertialDisplacementHint != null && inertialDisplacementHint.finite()) {
                    double length = inertialDisplacementHint.norm();
                    if (length > 0.002 && length < 0.25) {
                        step = 0.78 * step + 0.22 * length;
                    }
                }
                Vec3 deltaWorld = previousPose.orientation.rotate(
                        motion.cameraCentreDirectionPrevious.scale(step));
                pose = new Pose(orientation, previousPose.position.add(deltaWorld));
            } else {
                pose = new Pose(orientation, previousPose.position);
            }
            if (shouldKeyframe(frame, pose, motion, features.size())) {
                proposeKeyframe(frame, features, pose, motion, false);
            }
            if (frameId % 30 == 0) {
                informationalEvent(
                        frame.timestampNs,
                        "tracking_checkpoint",
                        motion.valid ? "accepted_observation" : "deferred",
                        fields(
                                "matches", Integer.toString(matches.size()),
                                "inliers", Integer.toString(motion.inliers),
                                "quality", fmt(motion.quality)));
            }
        }

        evidence.add(FrameEvidence.summarize(
                frame,
                frameId,
                schedule,
                orientation,
                inertialDisplacementHint,
                features.size(),
                matches.size(),
                motion.inliers,
                syntheticSession));
        previousFrame = frame;
        previousFeatures = features;
        previousPose = pose;
        previousOrientation = orientation;
        trajectory.add(pose.position);
        if (trajectory.size() > config.maxTrajectoryPoints) {
            decimateTrajectory();
        }
        float[] featureXY = new float[features.size() * 2];
        for (int index = 0; index < features.size(); index++) {
            featureXY[index * 2] = features.get(index).x;
            featureXY[index * 2 + 1] = features.get(index).y;
        }
        lastSnapshot = new SlamSnapshot(
                state.name().toLowerCase(Locale.ROOT),
                scaleCalibrated ? "metric_anchor" : "relative_units",
                frameId,
                frame.timestampNs,
                frame.width,
                frame.height,
                features.size(),
                matches.size(),
                motion.inliers,
                keyframes.size(),
                map.size(),
                motion.quality,
                motion.parallaxRad,
                metricScale,
                pose,
                featureXY,
                map.sample(config.overlayMapSample),
                new ArrayList<>(trajectory));
        return lastSnapshot;
    }

    private void decimateTrajectory() {
        if (trajectory.size() <= 2) {
            return;
        }
        ArrayList<Vec3> compact = new ArrayList<>((trajectory.size() + 1) / 2);
        for (int index = 0; index < trajectory.size(); index += 2) {
            compact.add(trajectory.get(index));
        }
        Vec3 last = trajectory.get(trajectory.size() - 1);
        if (compact.get(compact.size() - 1) != last) {
            compact.add(last);
        }
        trajectory.clear();
        trajectory.addAll(compact);
    }

    private boolean shouldKeyframe(
            GrayFrame frame, Pose pose, MotionEstimate motion, int features) {
        if (lastKeyframe == null) {
            return true;
        }
        long elapsed = frame.timestampNs - lastKeyframe.timestampNs;
        if (elapsed < config.keyframeMinIntervalNs) {
            return false;
        }
        return pose.translationDistance(lastKeyframe.pose) >= config.keyframeTranslation
                || pose.rotationDistance(lastKeyframe.pose) >= config.keyframeRotationRad
                || motion.parallaxRad >= config.keyframeParallaxRad
                || features < config.minimumMatches * 2;
    }

    private void proposeKeyframe(
            GrayFrame frame,
            List<Feature> features,
            Pose pose,
            MotionEstimate motion,
            boolean initial) {
        long candidateId = keyframes.size();
        String entityId = seed.stableId("keyframe", candidateId);
        List<Match> candidateMatches = lastKeyframe == null
                ? new ArrayList<>()
                : matcher.match(lastKeyframe.features, features);
        boolean underLimit = keyframes.size() < config.maxKeyframes;
        boolean enoughFeatures = features.size() >= Math.max(4, config.minimumMatches / 3);
        boolean compatible = initial || (motion.valid && !candidateMatches.isEmpty());
        double confidence = initial
                ? Math.min(1.0, features.size() / (double) Math.max(8, config.minimumMatches))
                : Vec3.clamp(
                        0.65 * motion.quality
                                + 0.35 * Math.min(1.0, candidateMatches.size() / 80.0),
                        0.0,
                        1.0);
        double numericError = initial ? 0.0 : 1.0 / Math.max(1.0, candidateMatches.size());
        SpatialProposal proposal = new SpatialProposal(
                seed.stableId("proposal", eventSeq),
                entityId,
                frame.timestampNs,
                "keyframe_commit",
                underLimit,
                enoughFeatures,
                compatible,
                compatible ? GuardStatus.CROSSING : GuardStatus.UNKNOWN,
                confidence,
                initial ? 0.10 : 0.08,
                numericError,
                initial ? 0.10 : 0.08,
                1.0 - confidence,
                initial ? 0.95 : 0.92,
                false,
                scaleCalibrated,
                syntheticSession ? SpatialProposal.TAG_SYNTHETIC : 0,
                fields(
                        "candidate_keyframe", Long.toString(candidateId),
                        "features", Integer.toString(features.size()),
                        "matches", Integer.toString(candidateMatches.size()),
                        "motion_quality", fmt(motion.quality)));
        VerificationResult result = verifier.verify(proposal);
        if (!result.accepted) {
            recordDecision(
                    proposal,
                    result,
                    fields(
                            "reason", result.reason,
                            "candidate_keyframe", Long.toString(candidateId),
                            "features", Integer.toString(features.size()),
                            "matches", Integer.toString(candidateMatches.size())));
            return;
        }

        Keyframe current = new Keyframe(
                candidateId, frame.timestampNs, pose, camera, frame, features);
        int sparse = 0;
        int dense = 0;
        if (lastKeyframe != null) {
            for (Match match : candidateMatches) {
                Triangulator.Result point = triangulator.triangulate(
                        lastKeyframe.pose,
                        current.pose,
                        camera,
                        lastKeyframe.features.get(match.previousIndex),
                        current.features.get(match.currentIndex));
                if (point == null) {
                    continue;
                }
                Feature feature = current.features.get(match.currentIndex);
                int intensity = frame.u8(
                        Math.max(0, Math.min(frame.width - 1, Math.round(feature.x))),
                        Math.max(0, Math.min(frame.height - 1, Math.round(feature.y))));
                double pointConfidence = Vec3.clamp(
                        (1.0 - match.distance / 90.0) * (1.0 - point.reprojection / 5.0),
                        0.05,
                        0.96);
                map.add(point.point, intensity, pointConfidence);
                sparse++;
            }
            if (sparse >= 12 && motion.quality >= 0.08) {
                dense = semiDense.fuse(lastKeyframe, current, map, config);
            }
            int loop = findLoopCandidate(current);
            if (loop >= 0) {
                informationalEvent(
                        frame.timestampNs,
                        "loop_closure_proposal",
                        "deferred",
                        fields(
                                "current_keyframe", Long.toString(current.id),
                                "candidate_keyframe", Integer.toString(loop),
                                "reason", "requires_geometric_bundle_adjustment"));
            }
        }
        keyframes.add(current);
        if (lastKeyframe != null) {
            lastKeyframe.releaseHeavyData();
        }
        lastKeyframe = current;
        recordDecision(
                proposal,
                result,
                fields(
                        "keyframe", Long.toString(current.id),
                        "stable_id", entityId,
                        "features", Integer.toString(features.size()),
                        "sparse_points", Integer.toString(sparse),
                        "semi_dense_points", Integer.toString(dense),
                        "map_voxels", Integer.toString(map.size())));
    }

    private int findLoopCandidate(Keyframe current) {
        int best = -1;
        int bestDistance = 99;
        for (int index = 0; index < keyframes.size() - 12; index++) {
            if ((index & 1) != 0) {
                continue;
            }
            int distance = Long.bitCount(current.signature ^ keyframes.get(index).signature);
            if (distance < bestDistance) {
                bestDistance = distance;
                best = index;
            }
        }
        return bestDistance <= 13 ? best : -1;
    }

    public synchronized Vec3 currentPosition() {
        return previousPose.position;
    }

    public synchronized boolean applyKnownDistanceAnchor(
            Vec3 start, Vec3 end, double metres, long nowNs) {
        boolean inputValid = start != null && end != null
                && Double.isFinite(metres) && metres > 0.0;
        double relative = inputValid ? start.distance(end) : 0.0;
        boolean support = inputValid && relative >= 1e-5;
        SpatialProposal proposal = new SpatialProposal(
                seed.stableId("proposal", eventSeq),
                seed.stableId("scale", 0),
                nowNs,
                "metric_scale_anchor",
                inputValid,
                support,
                true,
                support ? GuardStatus.CROSSING : GuardStatus.UNKNOWN,
                support ? 1.0 : 0.0,
                0.95,
                0.0,
                1e-9,
                0.0,
                0.05,
                false,
                scaleCalibrated,
                syntheticSession ? SpatialProposal.TAG_SYNTHETIC : 0,
                fields(
                        "known_metres", fmt(metres),
                        "relative_distance", fmt(relative)));
        VerificationResult result = verifier.verify(proposal);
        if (!result.accepted) {
            recordDecision(proposal, result, fields("reason", result.reason));
            return false;
        }
        double factor = metres / relative;
        map.scale(factor);
        for (Keyframe keyframe : keyframes) {
            keyframe.pose = keyframe.pose.scaled(factor);
        }
        for (int index = 0; index < trajectory.size(); index++) {
            trajectory.set(index, trajectory.get(index).scale(factor));
        }
        previousPose = previousPose.scaled(factor);
        metricScale *= factor;
        scaleCalibrated = true;
        recordDecision(
                proposal,
                result,
                fields(
                        "known_metres", fmt(metres),
                        "relative_distance", fmt(relative),
                        "factor", fmt(factor)));
        return true;
    }

    public synchronized SlamSnapshot snapshot() {
        return lastSnapshot;
    }

    public synchronized SessionData sessionData() {
        String captureProfile = "poco-x7-pro-12gb|fps=15|features=" + config.maxFeatures
                + "|voxels=" + config.maxVoxels + "|voxel=" + config.voxelSize;
        String calibration = camera == null
                ? "unknown"
                : camera.source + "|" + camera.width + "x" + camera.height
                        + "|" + camera.calibrated;
        return new SessionData(
                sessionId,
                scaleCalibrated ? "metric_anchor" : "relative_units",
                camera == null ? "unknown" : camera.source,
                startedNs,
                endedNs == 0 ? System.nanoTime() : endedNs,
                frameId,
                metricScale,
                map.voxelSize(),
                camera != null && camera.calibrated,
                map.cells(),
                new ArrayList<>(keyframes),
                new ArrayList<>(ledger),
                seed,
                new ArrayList<>(evidence),
                Hashing.hex(stateHash),
                rawInputBytes,
                rejectedProposals,
                syntheticSession,
                15,
                config.maxFeatures,
                Hashing.hex(Hashing.sha256Text(captureProfile)),
                Hashing.hex(Hashing.sha256Text(calibration)),
                nativeIntegrityStatus);
    }

    private void commitSystemEvent(long timestampNs, String type, Map<String, String> fields) {
        SpatialProposal proposal = new SpatialProposal(
                seed.stableId("proposal", eventSeq),
                seed.stableId("session", 0),
                timestampNs,
                type,
                true,
                true,
                true,
                GuardStatus.CROSSING,
                1.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                false,
                scaleCalibrated,
                syntheticSession ? SpatialProposal.TAG_SYNTHETIC : 0,
                fields);
        recordDecision(proposal, verifier.verify(proposal), fields);
    }

    private void informationalEvent(
            long timestampNs, String type, String reason, Map<String, String> fields) {
        String proposalId = seed.stableId("observation", eventSeq);
        byte[] canonical = canonicalFields(fields);
        String current = Hashing.hex(stateHash);
        ledger.add(new LedgerEvent(
                eventSeq++,
                timestampNs,
                proposalId,
                seed.stableId("session", 0),
                type,
                "deferred",
                reason,
                Hashing.hex(Hashing.sha256(canonical)),
                current,
                current,
                fields));
    }

    private void recordDecision(
            SpatialProposal proposal,
            VerificationResult result,
            Map<String, String> fields) {
        String pre = Hashing.hex(stateHash);
        String post = pre;
        if (result.accepted) {
            stateHash = Hashing.sha256(
                    stateHash,
                    proposal.canonicalBytes(),
                    canonicalFields(fields),
                    result.reason.getBytes(StandardCharsets.UTF_8));
            post = Hashing.hex(stateHash);
        } else {
            rejectedProposals++;
        }
        ledger.add(new LedgerEvent(
                eventSeq++,
                proposal.timestampNs,
                proposal.proposalId,
                proposal.entityId,
                proposal.type,
                result.accepted ? "accepted" : "rejected",
                result.reason,
                Hashing.hex(result.canonicalProposalHash),
                pre,
                post,
                fields));
    }

    private static byte[] canonicalFields(Map<String, String> fields) {
        StringBuilder text = new StringBuilder();
        for (Map.Entry<String, String> item : new TreeMap<>(fields).entrySet()) {
            text.append(item.getKey()).append('=').append(item.getValue()).append('\n');
        }
        return text.toString().getBytes(StandardCharsets.UTF_8);
    }

    private static Map<String, String> fields(String... keyValues) {
        LinkedHashMap<String, String> output = new LinkedHashMap<>();
        for (int index = 0; index + 1 < keyValues.length; index += 2) {
            output.put(keyValues[index], keyValues[index + 1]);
        }
        return output;
    }

    private static String fmt(double value) {
        return String.format(Locale.ROOT, "%.8g", value);
    }
}
