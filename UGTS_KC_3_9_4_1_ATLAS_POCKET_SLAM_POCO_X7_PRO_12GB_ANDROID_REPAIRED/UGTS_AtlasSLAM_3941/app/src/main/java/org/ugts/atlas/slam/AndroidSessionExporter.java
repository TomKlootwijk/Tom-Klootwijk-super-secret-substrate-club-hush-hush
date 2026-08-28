package org.ugts.atlas.slam;

import android.content.Context;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;
import org.ugts.atlas.slam.core.JsonUtil;
import org.ugts.atlas.slam.core.Keyframe;
import org.ugts.atlas.slam.core.LedgerEvent;
import org.ugts.atlas.slam.core.SessionData;
import org.ugts.atlas.slam.core.UgtsScanCodec;

/** Writes a small deterministic evidence container into private cache storage. */
final class AndroidSessionExporter {
    private AndroidSessionExporter() {}

    static File exportCompact(Context context, SessionData data) throws Exception {
        File base = new File(context.getCacheDir(), "ugts_exports");
        if (!base.exists() && !base.mkdirs()) {
            throw new IOException("cannot create private export directory");
        }
        File out = new File(base, fileName(data));
        LinkedHashMap<String, byte[]> entries = new LinkedHashMap<>();
        entries.put("map.ugtsbin", UgtsScanCodec.encode(data.cells, data.voxelSize));
        entries.put("trajectory.csv", trajectory(data).getBytes(StandardCharsets.UTF_8));
        entries.put("ledger.ndjson", ledger(data).getBytes(StandardCharsets.UTF_8));
        entries.put("capture_policy.json", policy(data).getBytes(StandardCharsets.UTF_8));
        entries.put("README.txt", readme(data).getBytes(StandardCharsets.UTF_8));

        LinkedHashMap<String, String> digests = new LinkedHashMap<>();
        MessageDigest sha256 = MessageDigest.getInstance("SHA-256");
        for (Map.Entry<String, byte[]> entry : entries.entrySet()) {
            digests.put(entry.getKey(), hex(sha256.digest(entry.getValue())));
        }
        entries.put(
                "manifest.json",
                manifest(data, digests).getBytes(StandardCharsets.UTF_8));

        try (ZipOutputStream zip = new ZipOutputStream(new FileOutputStream(out))) {
            zip.setLevel(3);
            for (Map.Entry<String, byte[]> entry : entries.entrySet()) {
                ZipEntry zipEntry = new ZipEntry(entry.getKey());
                zipEntry.setTime(0L);
                zip.putNextEntry(zipEntry);
                zip.write(entry.getValue());
                zip.closeEntry();
            }
        }
        return out;
    }

    static String fileName(SessionData data) {
        return safe(data.sessionId) + ".ugtsscan";
    }

    private static String trajectory(SessionData data) {
        StringBuilder text = new StringBuilder(
                "keyframe,timestamp_ns,x,y,z,qw,qx,qy,qz\n");
        for (Keyframe keyframe : data.keyframes) {
            text.append(keyframe.id).append(',')
                    .append(keyframe.timestampNs).append(',')
                    .append(number(keyframe.pose.position.x)).append(',')
                    .append(number(keyframe.pose.position.y)).append(',')
                    .append(number(keyframe.pose.position.z)).append(',')
                    .append(number(keyframe.pose.orientation.w)).append(',')
                    .append(number(keyframe.pose.orientation.x)).append(',')
                    .append(number(keyframe.pose.orientation.y)).append(',')
                    .append(number(keyframe.pose.orientation.z)).append('\n');
        }
        return text.toString();
    }

    private static String ledger(SessionData data) {
        StringBuilder text = new StringBuilder();
        for (LedgerEvent event : data.events) {
            text.append(event.toJson()).append('\n');
        }
        return text.toString();
    }

    private static String policy(SessionData data) {
        return "{\n"
                + "  \"schema\": \"ugts.capture-policy/3.9.4.1\",\n"
                + "  \"device_profile\": \"poco-x7-pro-12gb-atlas-3941\",\n"
                + "  \"offline\": true,\n"
                + "  \"metric_scale\": \"" + JsonUtil.escape(data.scaleState) + "\",\n"
                + "  \"camera_intrinsics_source\": \""
                + JsonUtil.escape(data.cameraSource) + "\",\n"
                + "  \"camera_intrinsics_calibrated\": "
                + data.cameraCalibrated + ",\n"
                + "  \"keyframe_images_persisted\": false,\n"
                + "  \"unknown_is_free_space\": false\n"
                + "}\n";
    }

    private static String readme(SessionData data) {
        return "UGTS-KC Atlas Pocket SLAM 3.9.4.1 compact scan\n\n"
                + "map.ugtsbin: quantized voxel coordinates, sorted deltas, zigzag-varints "
                + "and DEFLATE.\n"
                + "trajectory.csv: accepted keyframe camera poses.\n"
                + "ledger.ndjson: ordered capture and verification events.\n"
                + "capture_policy.json: accuracy/privacy state.\n"
                + "manifest.json: SHA-256 hashes for all preceding entries.\n\n"
                + "Scale state: " + data.scaleState + ". Relative-unit scans must not be "
                + "interpreted as metres.\n";
    }

    private static String manifest(
            SessionData data, LinkedHashMap<String, String> hashes) {
        StringBuilder text = new StringBuilder()
                .append("{\n")
                .append("  \"schema\": \"ugts.scan-manifest/3.9.4.1\",\n")
                .append("  \"session_id\": \"")
                .append(JsonUtil.escape(data.sessionId)).append("\",\n")
                .append("  \"frames\": ").append(data.frames).append(",\n")
                .append("  \"keyframes\": ").append(data.keyframes.size()).append(",\n")
                .append("  \"voxels\": ").append(data.cells.size()).append(",\n")
                .append("  \"voxel_size\": ").append(number(data.voxelSize)).append(",\n")
                .append("  \"scale_state\": \"")
                .append(JsonUtil.escape(data.scaleState)).append("\",\n")
                .append("  \"entries\": {\n");
        int index = 0;
        for (Map.Entry<String, String> entry : hashes.entrySet()) {
            text.append("    \"").append(JsonUtil.escape(entry.getKey()))
                    .append("\": {\"sha256\": \"")
                    .append(entry.getValue()).append("\"}");
            if (++index < hashes.size()) {
                text.append(',');
            }
            text.append('\n');
        }
        return text.append("  }\n}\n").toString();
    }

    private static String safe(String value) {
        String result = value == null ? "session" : value.replaceAll("[^A-Za-z0-9._-]", "_");
        return result.isEmpty() ? "session" : result;
    }

    private static String number(double value) {
        return String.format(Locale.ROOT, "%.9g", value);
    }

    private static String hex(byte[] bytes) {
        StringBuilder result = new StringBuilder(bytes.length * 2);
        for (byte value : bytes) {
            result.append(String.format(Locale.ROOT, "%02x", value & 255));
        }
        return result.toString();
    }
}
