import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Random;
import org.ugts.atlas.slam.core.CameraModel;
import org.ugts.atlas.slam.core.DescriptorMatcher;
import org.ugts.atlas.slam.core.FastBrief;
import org.ugts.atlas.slam.core.Feature;
import org.ugts.atlas.slam.core.GrayFrame;
import org.ugts.atlas.slam.core.Match;
import org.ugts.atlas.slam.core.MotionEstimate;
import org.ugts.atlas.slam.core.Pose;
import org.ugts.atlas.slam.core.Quat;
import org.ugts.atlas.slam.core.SessionData;
import org.ugts.atlas.slam.core.SlamConfig;
import org.ugts.atlas.slam.core.SlamEngine;
import org.ugts.atlas.slam.core.Triangulator;
import org.ugts.atlas.slam.core.UgtsScanCodec;
import org.ugts.atlas.slam.core.Vec3;
import org.ugts.atlas.slam.core.VisualInertialEstimator;
import org.ugts.atlas.slam.core.VoxelMap;

public final class CoreSelfTest {
    private static int assertions;

    private CoreSelfTest() {}

    private static void check(boolean condition, String message) {
        assertions++;
        if (!condition) {
            throw new AssertionError(message);
        }
    }

    public static void main(String[] args) throws Exception {
        testMath();
        testVoxelPack();
        testVoxelCodec();
        testFeatureDeterminismAndMatching();
        testMotion();
        testTriangulation();
        testEngineLifecycleAndAnchor();
        System.out.println(
                "UGTS 3.9.4.1 host core self-test: PASS (" + assertions + " assertions)");
    }

    private static void testMath() {
        Vec3 a = new Vec3(1, 2, 3);
        Vec3 b = new Vec3(-2, 0, 4);
        check(Math.abs(a.cross(b).dot(a)) < 1e-12, "cross orthogonal to a");
        check(Math.abs(a.cross(b).dot(b)) < 1e-12, "cross orthogonal to b");
        Quat q = Quat.fromAxisAngle(new Vec3(0, 1, 0), Math.PI / 2);
        Vec3 rotated = q.rotate(new Vec3(1, 0, 0));
        check(Math.abs(rotated.z + 1) < 1e-9, "quaternion rotation");
        Pose pose = new Pose(q, new Vec3(2, 0, 0));
        check(
                pose.worldToCamera(pose.cameraToWorld(a)).distance(a) < 1e-9,
                "pose round trip");
    }

    private static void testVoxelPack() {
        int[][] values = {
            {0, 0, 0},
            {1, -1, 42},
            {-1_048_576, 1_048_575, -99},
            {551_221, -430_000, 777_777}
        };
        for (int[] value : values) {
            long key = VoxelMap.pack(value[0], value[1], value[2]);
            check(VoxelMap.unpackX(key) == value[0], "voxel x round trip");
            check(VoxelMap.unpackY(key) == value[1], "voxel y round trip");
            check(VoxelMap.unpackZ(key) == value[2], "voxel z round trip");
        }
    }

    private static void testVoxelCodec() throws Exception {
        VoxelMap map = new VoxelMap(0.01, 20_000);
        for (int i = 0; i < 8_000; i++) {
            map.add(
                    new Vec3(
                            (i % 80) * 0.01,
                            ((i / 80) % 20) * 0.01,
                            (i / 1600) * 0.01),
                    i & 255,
                    0.7);
        }
        List<VoxelMap.Cell> cells = map.cells();
        byte[] encodedA = UgtsScanCodec.encode(cells, map.voxelSize());
        byte[] encodedB = UgtsScanCodec.encode(cells, map.voxelSize());
        check(Arrays.equals(encodedA, encodedB), "codec is deterministic");
        UgtsScanCodec.Decoded decoded = UgtsScanCodec.decode(encodedA);
        check(decoded.records.size() == map.size(), "codec count");
        check(Math.abs(decoded.voxelSize - 0.01) < 1e-12, "codec voxel size");
        for (int i = 0; i < cells.size(); i++) {
            VoxelMap.Cell cell = cells.get(i);
            int[] record = decoded.records.get(i);
            check(cell.qx == record[0] && cell.qy == record[1] && cell.qz == record[2],
                    "codec coordinate record " + i);
        }
        check(encodedA.length < map.size() * 10L, "codec compactness");
    }

    private static void testFeatureDeterminismAndMatching() {
        int width = 320;
        int height = 240;
        byte[] pixels = textured(width, height, 0);
        GrayFrame frame = new GrayFrame(width, height, 1, pixels);
        FastBrief detector = new FastBrief();
        List<Feature> first = detector.detect(frame, 700, 18);
        List<Feature> second = detector.detect(frame.copy(), 700, 18);
        check(!first.isEmpty(), "features detected");
        check(first.size() == second.size(), "detector deterministic count");
        for (int i = 0; i < first.size(); i++) {
            Feature a = first.get(i);
            Feature b = second.get(i);
            check(a.x == b.x && a.y == b.y && a.distance(b) == 0,
                    "detector deterministic feature " + i);
        }
        List<Match> matches = new DescriptorMatcher().match(first, second);
        check(matches.size() >= Math.min(24, first.size()), "identity descriptors match");
        for (Match match : matches) {
            check(match.distance == 0, "identity match distance");
        }
    }

    private static void testMotion() {
        CameraModel camera = new CameraModel(
                640, 480, 510, 510, 319.5, 239.5, true, "synthetic");
        Pose a = Pose.IDENTITY;
        Pose b = new Pose(
                Quat.fromAxisAngle(new Vec3(0, 1, 0), Math.toRadians(1.5)),
                new Vec3(0.12, 0.01, 0.0));
        ArrayList<Feature> featuresA = new ArrayList<>();
        ArrayList<Feature> featuresB = new ArrayList<>();
        ArrayList<Match> matches = new ArrayList<>();
        Random random = new Random(3941);
        for (int i = 0; i < 180; i++) {
            Vec3 world = new Vec3(
                    (random.nextDouble() - 0.5) * 3,
                    (random.nextDouble() - 0.5) * 2,
                    2.5 + random.nextDouble() * 4);
            double[] pa = camera.project(a.worldToCamera(world));
            double[] pb = camera.project(b.worldToCamera(world));
            if (pa == null || pb == null
                    || !camera.inside(pa[0], pa[1], 16)
                    || !camera.inside(pb[0], pb[1], 16)) {
                continue;
            }
            int index = featuresA.size();
            long d0 = random.nextLong();
            long d1 = random.nextLong();
            long d2 = random.nextLong();
            long d3 = random.nextLong();
            featuresA.add(new Feature(index, (float) pa[0], (float) pa[1], 100, d0, d1, d2, d3));
            featuresB.add(new Feature(index, (float) pb[0], (float) pb[1], 100, d0, d1, d2, d3));
            matches.add(new Match(index, index, 0));
        }
        MotionEstimate estimate = new VisualInertialEstimator().estimate(
                featuresA,
                featuresB,
                matches,
                camera,
                a.orientation,
                b.orientation,
                24);
        check(estimate.valid, "motion valid");
        check(estimate.inliers >= 24, "motion inliers");
        check(
                Math.abs(
                        estimate.cameraCentreDirectionPrevious
                                .normalized()
                                .dot(b.position.normalized())) > 0.75,
                "motion direction");
    }

    private static void testTriangulation() {
        CameraModel camera = new CameraModel(
                640, 480, 520, 520, 319.5, 239.5, true, "synthetic");
        Pose first = Pose.IDENTITY;
        Pose second = new Pose(Quat.IDENTITY, new Vec3(0.18, 0, 0));
        Vec3 world = new Vec3(0.25, -0.08, 3.2);
        double[] p1 = camera.project(first.worldToCamera(world));
        double[] p2 = camera.project(second.worldToCamera(world));
        check(p1 != null && p2 != null, "triangulation projections");
        Feature f1 = new Feature(0, (float) p1[0], (float) p1[1], 100, 1, 2, 3, 4);
        Feature f2 = new Feature(0, (float) p2[0], (float) p2[1], 100, 1, 2, 3, 4);
        Triangulator.Result result = new Triangulator().triangulate(
                first, second, camera, f1, f2);
        check(result != null, "triangulation accepted");
        check(result.point.distance(world) < 1e-3, "triangulation position");
        check(result.reprojection < 0.01, "triangulation reprojection");
    }

    private static void testEngineLifecycleAndAnchor() {
        int width = 320;
        int height = 240;
        SlamConfig config = SlamConfig.pocoX7Pro12Gb();
        config.maxFeatures = 600;
        config.semiDenseMaxPoints = 700;
        SlamEngine engine = new SlamEngine(config);
        engine.start("test", 1);
        CameraModel camera = CameraModel.declaredFallback(width, height);
        engine.process(
                new GrayFrame(width, height, 1_000_000_000L, textured(width, height, 0)),
                camera,
                Quat.IDENTITY,
                Vec3.ZERO);
        engine.process(
                new GrayFrame(width, height, 1_500_000_000L, textured(width, height, 3)),
                camera,
                Quat.IDENTITY,
                new Vec3(0.01, 0, 0));
        Vec3 before = engine.currentPosition();
        Vec3 syntheticEnd = before.add(new Vec3(1, 0, 0));
        check(
                engine.applyKnownDistanceAnchor(before, syntheticEnd, 2.0, 1_800_000_000L),
                "metric anchor accepted");
        engine.pause(1_900_000_000L);
        check(engine.state() == SlamEngine.State.PAUSED, "pause state");
        engine.resume(2_000_000_000L);
        check(engine.state() == SlamEngine.State.SCANNING, "resume state");
        engine.finish(2_100_000_000L);
        SessionData data = engine.sessionData();
        check(engine.state() == SlamEngine.State.FINISHED, "finish state");
        check(data.frames == 2, "engine frame count");
        check("metric_anchor".equals(data.scaleState), "metric anchor state");
        check(!data.events.isEmpty(), "ledger events");
        check(data.events.get(0).sequence == 0, "ledger sequence starts at zero");
        for (int i = 1; i < data.events.size(); i++) {
            check(
                    data.events.get(i).sequence == data.events.get(i - 1).sequence + 1,
                    "ledger sequence contiguous");
        }
    }

    private static byte[] textured(int width, int height, int shift) {
        byte[] pixels = new byte[width * height];
        for (int y = 0; y < height; y++) {
            for (int x = 0; x < width; x++) {
                int sx = Math.max(0, x - shift);
                int checker = (((sx / 12) + (y / 12)) & 1) * 150;
                int wave = (sx * 17 + y * 13 + ((sx * y) & 63)) & 63;
                pixels[y * width + x] = (byte) Math.min(255, 30 + checker + wave);
            }
        }
        return pixels;
    }
}
