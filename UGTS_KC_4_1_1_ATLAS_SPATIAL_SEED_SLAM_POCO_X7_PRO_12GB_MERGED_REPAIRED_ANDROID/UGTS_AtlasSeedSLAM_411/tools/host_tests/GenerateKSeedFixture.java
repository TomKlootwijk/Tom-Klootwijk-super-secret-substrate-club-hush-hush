import java.io.FileOutputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import org.ugts.atlas.slam.core.CameraModel;
import org.ugts.atlas.slam.core.GrayFrame;
import org.ugts.atlas.slam.core.KSeedReader;
import org.ugts.atlas.slam.core.KSeedWriter;
import org.ugts.atlas.slam.core.Quat;
import org.ugts.atlas.slam.core.Seed128;
import org.ugts.atlas.slam.core.SessionData;
import org.ugts.atlas.slam.core.SlamConfig;
import org.ugts.atlas.slam.core.SlamEngine;
import org.ugts.atlas.slam.core.Vec3;

public final class GenerateKSeedFixture {
    private GenerateKSeedFixture() {}

    public static void main(String[] args) throws Exception {
        if (args.length != 2) {
            throw new IllegalArgumentException("output.kseed summary.json");
        }
        int width = 160;
        int height = 96;
        int frames = 120;
        long start = 10_000_000_000L;
        Seed128 seed = Seed128.derive("UGTS-KC-4.1.1-RELEASE-FIXTURE");
        SlamConfig config = SlamConfig.pocoX7Pro12Gb();
        config.maxFeatures = 420;
        config.maxVoxels = 30_000;
        config.maxKeyframes = 96;
        config.semiDenseMaxPoints = 450;
        config.semiDenseDepthSamples = 16;
        SlamEngine engine = new SlamEngine(config);
        engine.setNativeIntegrityStatus("host_java_oracle");
        engine.start("atlas_seed_slam_411_fixture", start, seed, true);
        CameraModel camera = CameraModel.declaredFallback(width, height);
        for (int index = 0; index < frames; index++) {
            long timestamp = start + index * 100_000_000L;
            engine.process(
                    new GrayFrame(width, height, timestamp, pixels(width, height, index)),
                    camera,
                    Quat.fromAxisAngle(new Vec3(0, 1, 0), Math.sin(index * 0.025) * 0.08),
                    new Vec3(0.0025, 0.0, 0.003));
        }
        engine.finish(start + frames * 100_000_000L);
        SessionData session = engine.sessionData();
        Path output = Path.of(args[0]);
        Files.createDirectories(output.getParent());
        try (FileOutputStream stream = new FileOutputStream(output.toFile())) {
            new KSeedWriter().write(stream, session);
        }
        KSeedReader.Inspection inspection = new KSeedReader().inspect(Files.readAllBytes(output));
        Path summary = Path.of(args[1]);
        Files.createDirectories(summary.getParent());
        Files.writeString(summary, inspection.toJson());
        System.out.println("fixture=" + output);
        System.out.println("bytes=" + Files.size(output));
        System.out.println("frames=" + inspection.frames);
        System.out.println("events=" + inspection.events);
        System.out.println("voxels=" + inspection.voxels);
        System.out.println("final_chain=" + inspection.finalChainSha256);
    }

    private static byte[] pixels(int width, int height, int frame) {
        byte[] output = new byte[width * height];
        int shiftX = frame % 31;
        int shiftY = (frame / 4) % 17;
        for (int y = 0; y < height; y++) {
            for (int x = 0; x < width; x++) {
                int sx = x + shiftX;
                int sy = y + shiftY;
                int checker = (((sx / 7) ^ (sy / 7)) & 1) * 105;
                int wave = (int) (40 * Math.sin(sx * 0.13)
                        + 31 * Math.cos(sy * 0.19)
                        + 22 * Math.sin((sx + sy) * 0.071));
                int value = Math.max(0, Math.min(255, 102 + checker + wave));
                output[y * width + x] = (byte) value;
            }
        }
        return output;
    }
}
