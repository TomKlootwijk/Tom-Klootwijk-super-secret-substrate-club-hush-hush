import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.Random;
import org.ugts.atlas.slam.core.Bayer4Level;
import org.ugts.atlas.slam.core.CameraModel;
import org.ugts.atlas.slam.core.GrayFrame;
import org.ugts.atlas.slam.core.GuardStatus;
import org.ugts.atlas.slam.core.KSeed41;
import org.ugts.atlas.slam.core.KSeedReader;
import org.ugts.atlas.slam.core.KSeedWriter;
import org.ugts.atlas.slam.core.Morton3D;
import org.ugts.atlas.slam.core.ProposalVerifier;
import org.ugts.atlas.slam.core.Quat;
import org.ugts.atlas.slam.core.Seed128;
import org.ugts.atlas.slam.core.SeededSchedule;
import org.ugts.atlas.slam.core.SessionData;
import org.ugts.atlas.slam.core.SlamConfig;
import org.ugts.atlas.slam.core.SlamEngine;
import org.ugts.atlas.slam.core.SpatialProposal;
import org.ugts.atlas.slam.core.Vec3;
import org.ugts.atlas.slam.core.VerificationResult;

public final class SeedSpatialSelfTest {
    private static int assertions;

    private SeedSpatialSelfTest() {}

    private static void check(boolean condition, String message) {
        assertions++;
        if (!condition) {
            throw new AssertionError(message);
        }
    }

    public static void main(String[] args) throws Exception {
        testSeedAndSchedule();
        testMorton();
        testBayer();
        testVerifier();
        testKSeedRoundTripAndCorruption();
        System.out.println(
                "UGTS 4.1.1 seed/spatial self-test: PASS (" + assertions + " assertions)");
    }

    private static void testSeedAndSchedule() {
        Seed128 first = Seed128.derive("fixture");
        Seed128 second = Seed128.derive("fixture");
        check(first.equals(second), "seed derivation deterministic");
        check(first.toHex().length() == 32, "seed width");
        check(Seed128.fromHex(first.toHex()).equals(first), "seed hex round trip");
        check(first.stableId("node", 7).equals(first.stableId("node", 7)),
                "stable identifier deterministic");
        SeededSchedule schedule = new SeededSchedule(first);
        for (int index = 0; index < 10_000; index++) {
            int value = schedule.bounded(17, index, 257);
            check(value >= 0 && value < 257, "bounded schedule");
        }
    }

    private static void testMorton() {
        Random random = new Random(411);
        for (int index = 0; index < 4096; index++) {
            int x = random.nextInt(2_097_152) - 1_048_576;
            int y = random.nextInt(2_097_152) - 1_048_576;
            int z = random.nextInt(2_097_152) - 1_048_576;
            long key = Morton3D.encodeSigned21(x, y, z);
            check(Morton3D.decodeX(key) == x, "Morton x");
            check(Morton3D.decodeY(key) == y, "Morton y");
            check(Morton3D.decodeZ(key) == z, "Morton z");
        }
    }

    private static void testBayer() {
        byte[] ramp = new byte[256 * 8];
        for (int y = 0; y < 8; y++) {
            for (int x = 0; x < 256; x++) {
                ramp[y * 256 + x] = (byte) x;
            }
        }
        byte[] projected = Bayer4Level.project(ramp, 256, 8);
        for (byte value : projected) {
            int unsigned = value & 255;
            check(unsigned == 0 || unsigned == 85 || unsigned == 170 || unsigned == 255,
                    "Bayer four-level output");
        }
    }

    private static void testVerifier() {
        ProposalVerifier verifier = new ProposalVerifier();
        LinkedHashMap<String, String> payload = new LinkedHashMap<>();
        payload.put("kind", "fixture");
        SpatialProposal accepted = proposal(
                "p:1", "node:1", true, true, true, GuardStatus.CROSSING,
                0.9, 0.8, 0.01, 0.02, 0.1, 0.2, false, false, payload);
        check(verifier.verify(accepted).accepted, "proposal accepted");
        SpatialProposal metricMissing = proposal(
                "p:2", "node:2", true, true, true, GuardStatus.CROSSING,
                0.9, 0.8, 0.01, 0.02, 0.1, 0.2, true, false, payload);
        check("metric_unavailable".equals(verifier.verify(metricMissing).reason),
                "metric gate");
        SpatialProposal numeric = proposal(
                "p:3", "node:3", true, true, true, GuardStatus.CROSSING,
                0.9, 0.8, 0.03, 0.02, 0.1, 0.2, false, false, payload);
        check("numeric_error_exceeds_margin".equals(verifier.verify(numeric).reason),
                "numeric gate");
        SpatialProposal guard = proposal(
                "p:4", "node:4", true, true, true, GuardStatus.TANGENCY,
                0.9, 0.8, 0.01, 0.02, 0.1, 0.2, false, false, payload);
        check("guard_tangency".equals(verifier.verify(guard).reason), "guard class gate");
    }

    private static SpatialProposal proposal(
            String proposalId,
            String entityId,
            boolean identifier,
            boolean support,
            boolean compatible,
            GuardStatus guard,
            double confidence,
            double floor,
            double error,
            double margin,
            double uncertainty,
            double maximum,
            boolean requiresMetric,
            boolean metric,
            LinkedHashMap<String, String> payload) {
        return new SpatialProposal(
                proposalId, entityId, 123, "test", identifier, support, compatible, guard,
                confidence, floor, error, margin, uncertainty, maximum,
                requiresMetric, metric, 0, payload);
    }

    private static void testKSeedRoundTripAndCorruption() throws Exception {
        SlamConfig config = SlamConfig.pocoX7Pro12Gb();
        config.maxFeatures = 500;
        config.maxVoxels = 20_000;
        config.maxKeyframes = 64;
        config.semiDenseMaxPoints = 500;
        SlamEngine engine = new SlamEngine(config);
        Seed128 seed = Seed128.derive("KSEED-411-SELF-TEST");
        engine.start("kseed_fixture", 1_000_000_000L, seed, true);
        CameraModel camera = CameraModel.declaredFallback(160, 96);
        for (int frame = 0; frame < 40; frame++) {
            engine.process(
                    new GrayFrame(
                            160,
                            96,
                            1_000_000_000L + frame * 100_000_000L,
                            textured(160, 96, frame)),
                    camera,
                    Quat.fromAxisAngle(new Vec3(0, 1, 0), frame * 0.001),
                    new Vec3(0.002, 0, 0.003));
        }
        engine.finish(5_100_000_000L);
        SessionData data = engine.sessionData();
        check(data.frames == 40, "KSEED fixture frame count");
        check(data.frameEvidence.size() == 40, "frame evidence retained");
        check(data.synthetic, "synthetic state retained");
        check(data.rawInputBytes == 40L * 160 * 96, "raw input accounting");
        byte[] first = new KSeedWriter().encode(data);
        byte[] second = new KSeedWriter().encode(data);
        check(Arrays.equals(first, second), "KSEED deterministic encoding");
        check(first.length > KSeed41.HEADER_BYTES, "KSEED has chunks");
        KSeedReader.Inspection inspection = new KSeedReader().read(
                new ByteArrayInputStream(first));
        check(inspection.seed.equals(seed), "KSEED seed round trip");
        check(inspection.frames == data.frames, "KSEED summary frames");
        check(inspection.events == data.events.size(), "KSEED summary events");
        check(inspection.voxels == data.cells.size(), "KSEED summary voxels");
        check(inspection.storedBytes == first.length, "KSEED exact stored bytes");
        check(inspection.chunkCount == 6, "KSEED expected chunk count");
        check(inspection.chunks.get(0).recordCount == 40, "frame chunk record count");
        check(inspection.chunks.get(inspection.chunks.size() - 1).type
                        == KSeed41.CHUNK_SUMMARY,
                "summary is final chunk");
        check(first.length < data.rawInputBytes, "fixture compression below raw luma");
        byte[] corrupted = first.clone();
        corrupted[corrupted.length / 2] ^= 1;
        boolean rejected = false;
        try {
            new KSeedReader().inspect(corrupted);
        } catch (IOException expected) {
            rejected = true;
        }
        check(rejected, "corruption rejected");
        for (int index = 1; index < data.events.size(); index++) {
            check(data.events.get(index).sequence == data.events.get(index - 1).sequence + 1,
                    "ledger sequence contiguous");
        }
    }

    private static byte[] textured(int width, int height, int shift) {
        byte[] pixels = new byte[width * height];
        for (int y = 0; y < height; y++) {
            for (int x = 0; x < width; x++) {
                int sx = x + shift;
                int checker = (((sx / 8) ^ (y / 8)) & 1) * 105;
                int wave = (int) (42 * Math.sin(sx * 0.12) + 33 * Math.cos(y * 0.17));
                pixels[y * width + x] = (byte) Math.max(0, Math.min(255, 100 + checker + wave));
            }
        }
        return pixels;
    }
}
