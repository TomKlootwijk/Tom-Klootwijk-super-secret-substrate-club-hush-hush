package org.ugts.atlas.slam.core;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.zip.Deflater;

/**
 * Streamable KSEED 4.1 writer reconstructed from the supplied 4.1 report.
 * Raw camera frames are deliberately not serialized.
 */
public final class KSeedWriter {
    private static final int SCHEMA_FRAME = 0x4101;
    private static final int SCHEMA_KEYFRAME = 0x4102;
    private static final int SCHEMA_LEDGER = 0x4103;
    private static final int SCHEMA_VOXEL = 0x4104;
    private static final int SCHEMA_CALIBRATION = 0x4105;
    private static final int SCHEMA_SUMMARY = 0x41ff;

    private static final class PendingChunk {
        final int type;
        final int flags;
        final int sequence;
        final int recordCount;
        final int schemaId;
        final byte[] decoded;
        final byte[] stored;

        PendingChunk(
                int type,
                int flags,
                int sequence,
                int recordCount,
                int schemaId,
                byte[] decoded,
                boolean allowCompression) {
            this.type = type;
            this.sequence = sequence;
            this.recordCount = recordCount;
            this.schemaId = schemaId;
            this.decoded = decoded;
            byte[] candidate = allowCompression ? deflateFast(decoded) : decoded;
            if (allowCompression && candidate.length + 16 < decoded.length) {
                this.flags = flags | KSeed41.FLAG_COMPRESSED;
                this.stored = candidate;
            } else {
                this.flags = flags;
                this.stored = decoded;
            }
        }
    }

    public byte[] encode(SessionData session) throws IOException {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        write(output, session);
        return output.toByteArray();
    }

    public void write(OutputStream output, SessionData session) throws IOException {
        List<PendingChunk> chunks = new ArrayList<>();
        int flags = session.synthetic ? KSeed41.FLAG_SYNTHETIC : 0;
        int sequence = 0;
        chunks.add(new PendingChunk(
                KSeed41.CHUNK_FRAME_EVIDENCE,
                flags,
                sequence++,
                session.frameEvidence.size(),
                SCHEMA_FRAME,
                encodeFrameEvidence(session.frameEvidence),
                true));
        chunks.add(new PendingChunk(
                KSeed41.CHUNK_KEYFRAMES,
                flags,
                sequence++,
                session.keyframes.size(),
                SCHEMA_KEYFRAME,
                encodeKeyframes(session),
                true));
        chunks.add(new PendingChunk(
                KSeed41.CHUNK_LEDGER,
                flags,
                sequence++,
                session.events.size(),
                SCHEMA_LEDGER,
                encodeLedger(session.events),
                true));
        chunks.add(new PendingChunk(
                KSeed41.CHUNK_VOXELS,
                flags,
                sequence++,
                session.cells.size(),
                SCHEMA_VOXEL,
                encodeVoxels(session.cells),
                true));
        chunks.add(new PendingChunk(
                KSeed41.CHUNK_CALIBRATION,
                flags,
                sequence++,
                1,
                SCHEMA_CALIBRATION,
                encodeCalibration(session),
                true));

        long predicted = KSeed41.HEADER_BYTES + KSeed41.CHUNK_HEADER_BYTES + KSeed41.SUMMARY_BYTES;
        for (PendingChunk chunk : chunks) {
            predicted += KSeed41.CHUNK_HEADER_BYTES + chunk.stored.length;
        }
        byte[] summary = encodeSummary(session, predicted, chunks.size() + 1);
        chunks.add(new PendingChunk(
                KSeed41.CHUNK_SUMMARY,
                flags,
                sequence,
                1,
                SCHEMA_SUMMARY,
                summary,
                false));

        byte[] header = encodeHeader(session);
        output.write(header);
        byte[] previousHash = KSeed41.INITIAL_CHAIN;
        for (PendingChunk chunk : chunks) {
            byte[] first32 = encodeChunkFirst32(chunk);
            byte[] chain = Hashing.sha256(previousHash, first32, chunk.stored);
            output.write(first32);
            output.write(chain);
            output.write(chunk.stored);
            previousHash = chain;
        }
    }

    private static byte[] encodeHeader(SessionData session) {
        int width = session.frameEvidence.isEmpty() ? 0 : session.frameEvidence.get(0).width;
        int height = session.frameEvidence.isEmpty() ? 0 : session.frameEvidence.get(0).height;
        int flags = 0;
        if (session.synthetic) {
            flags |= 1;
        }
        if ("metric_anchor".equals(session.scaleState)) {
            flags |= 2;
        }
        if (session.nativeIntegrityStatus.startsWith("native")) {
            flags |= 4;
        }
        ByteBuffer header = ByteBuffer.allocate(KSeed41.HEADER_BYTES).order(ByteOrder.LITTLE_ENDIAN);
        header.put(KSeed41.MAGIC);
        header.putShort((short) KSeed41.VERSION_MAJOR);
        header.putShort((short) KSeed41.VERSION_MINOR);
        header.putShort((short) KSeed41.HEADER_BYTES);
        header.putShort((short) KSeed41.STORAGE_MODE_EVIDENCE_DELTAS);
        header.putInt(flags);
        header.put(session.seed.toBytes());
        header.putLong(session.startedNs);
        header.putInt(width);
        header.putInt(height);
        header.putInt(session.requestedCaptureFps);
        header.putInt(session.featureBudget);
        header.put(hash32(session.captureProfileSha256));
        header.put(hash32(session.calibrationSha256));
        byte[] bytes = header.array();
        ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN).putInt(
                124, (int) Hashing.crc32(bytes, 0, 124));
        return bytes;
    }

    private static byte[] encodeChunkFirst32(PendingChunk chunk) {
        ByteBuffer header = ByteBuffer.allocate(32).order(ByteOrder.LITTLE_ENDIAN);
        header.putShort((short) chunk.type);
        header.putShort((short) chunk.flags);
        header.putInt(chunk.sequence);
        header.putInt(chunk.recordCount);
        header.putInt(chunk.decoded.length);
        header.putInt(chunk.stored.length);
        header.putInt((int) Hashing.crc32(chunk.decoded));
        header.putInt((int) Hashing.crc32(chunk.stored));
        header.putInt(chunk.schemaId);
        return header.array();
    }

    private static byte[] encodeFrameEvidence(List<FrameEvidence> frames) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        Varint.writeUnsigned(out, frames.size());
        long previousFrame = 0;
        long previousTimestamp = 0;
        for (FrameEvidence frame : frames) {
            Varint.writeUnsigned(out, frame.frameIndex - previousFrame);
            Varint.writeUnsigned(out, frame.timestampNs - previousTimestamp);
            Varint.writeUnsigned(out, frame.width);
            Varint.writeUnsigned(out, frame.height);
            writeU16(out, frame.lumaMeanQ8);
            writeU16(out, frame.lumaVarianceQ8);
            writeU16(out, frame.gradientMeanQ8);
            Varint.writeUnsigned(out, frame.featureCount);
            Varint.writeUnsigned(out, frame.matchCount);
            Varint.writeUnsigned(out, frame.inlierCount);
            writeI16(out, frame.qw);
            writeI16(out, frame.qx);
            writeI16(out, frame.qy);
            writeI16(out, frame.qz);
            writeI16(out, frame.axMm);
            writeI16(out, frame.ayMm);
            writeI16(out, frame.azMm);
            out.write(frame.synthetic ? 1 : 0);
            previousFrame = frame.frameIndex;
            previousTimestamp = frame.timestampNs;
        }
        return out.toByteArray();
    }

    private static byte[] encodeKeyframes(SessionData session) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        Varint.writeUnsigned(out, session.keyframes.size());
        long previousId = 0;
        long previousTimestamp = 0;
        for (Keyframe frame : session.keyframes) {
            Varint.writeUnsigned(out, frame.id - previousId);
            Varint.writeUnsigned(out, frame.timestampNs - previousTimestamp);
            writeString(out, session.seed.stableId("kf", frame.id));
            writeQuantized(out, frame.pose.position.x, 1_000_000.0);
            writeQuantized(out, frame.pose.position.y, 1_000_000.0);
            writeQuantized(out, frame.pose.position.z, 1_000_000.0);
            writeI16(out, q16(frame.pose.orientation.w));
            writeI16(out, q16(frame.pose.orientation.x));
            writeI16(out, q16(frame.pose.orientation.y));
            writeI16(out, q16(frame.pose.orientation.z));
            writeLongLe(out, frame.signature);
            previousId = frame.id;
            previousTimestamp = frame.timestampNs;
        }
        return out.toByteArray();
    }

    private static byte[] encodeLedger(List<LedgerEvent> events) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        Varint.writeUnsigned(out, events.size());
        long previousSequence = 0;
        long previousTimestamp = 0;
        for (LedgerEvent event : events) {
            Varint.writeUnsigned(out, event.sequence - previousSequence);
            Varint.writeUnsigned(out, event.timestampNs - previousTimestamp);
            writeString(out, event.proposalId);
            writeString(out, event.entityId);
            writeString(out, event.type);
            writeString(out, event.commitState);
            writeString(out, event.reason);
            writeFixedHash(out, event.canonicalProposalSha256);
            writeFixedHash(out, event.preStateSha256);
            writeFixedHash(out, event.postStateSha256);
            Varint.writeUnsigned(out, event.fields.size());
            for (Map.Entry<String, String> item : event.fields.entrySet()) {
                writeString(out, item.getKey());
                writeString(out, item.getValue());
            }
            previousSequence = event.sequence;
            previousTimestamp = event.timestampNs;
        }
        return out.toByteArray();
    }

    private static byte[] encodeVoxels(List<VoxelMap.Cell> cells) throws IOException {
        final class Encoded {
            final long key;
            final VoxelMap.Cell cell;
            Encoded(long key, VoxelMap.Cell cell) { this.key = key; this.cell = cell; }
        }
        ArrayList<Encoded> ordered = new ArrayList<>(cells.size());
        for (VoxelMap.Cell cell : cells) {
            ordered.add(new Encoded(Morton3D.encodeSigned21(cell.qx, cell.qy, cell.qz), cell));
        }
        ordered.sort((a, b) -> Long.compareUnsigned(a.key, b.key));
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        Varint.writeUnsigned(out, ordered.size());
        long previous = 0;
        for (Encoded item : ordered) {
            Varint.writeUnsigned(out, item.key - previous);
            out.write(item.cell.intensity());
            out.write((int) Math.round(Vec3.clamp(item.cell.confidence(), 0.0, 1.0) * 255.0));
            Varint.writeUnsigned(out, item.cell.observations());
            previous = item.key;
        }
        return out.toByteArray();
    }

    private static byte[] encodeCalibration(SessionData session) {
        String json = "{\n"
                + "  \"schema\": \"ugts.kseed-calibration/4.1.1\",\n"
                + "  \"camera_source\": \"" + JsonUtil.escape(session.cameraSource) + "\",\n"
                + "  \"camera_calibrated\": " + session.cameraCalibrated + ",\n"
                + "  \"scale_state\": \"" + JsonUtil.escape(session.scaleState) + "\",\n"
                + "  \"metric_scale\": " + JsonUtil.finite(session.metricScale) + ",\n"
                + "  \"voxel_size\": " + JsonUtil.finite(session.voxelSize) + ",\n"
                + "  \"native_integrity_status\": \""
                + JsonUtil.escape(session.nativeIntegrityStatus) + "\"\n"
                + "}\n";
        return json.getBytes(StandardCharsets.UTF_8);
    }

    private static byte[] encodeSummary(SessionData session, long storedBytes, int chunkCount) {
        ByteBuffer summary = ByteBuffer.allocate(KSeed41.SUMMARY_BYTES).order(ByteOrder.LITTLE_ENDIAN);
        summary.putLong(session.frames);
        summary.putLong(session.keyframes.size());
        summary.putLong(session.events.size());
        summary.putLong(session.cells.size());
        summary.putLong(session.rawInputBytes);
        summary.putLong(storedBytes);
        summary.putInt(session.rejectedProposals);
        int stateFlags = 0;
        if (session.synthetic) stateFlags |= 1;
        if ("metric_anchor".equals(session.scaleState)) stateFlags |= 2;
        summary.putInt(stateFlags);
        summary.putInt(chunkCount);
        return summary.array();
    }

    private static byte[] deflateFast(byte[] input) {
        Deflater deflater = new Deflater(Deflater.BEST_SPEED, false);
        deflater.setInput(input);
        deflater.finish();
        ByteArrayOutputStream out = new ByteArrayOutputStream(Math.max(64, input.length / 2));
        byte[] buffer = new byte[8192];
        while (!deflater.finished()) {
            int count = deflater.deflate(buffer);
            if (count <= 0 && deflater.needsInput()) {
                break;
            }
            out.write(buffer, 0, count);
        }
        deflater.end();
        return out.toByteArray();
    }

    private static byte[] hash32(String value) {
        try {
            byte[] result = Hashing.fromHex(value);
            if (result.length == 32) {
                return result;
            }
        } catch (IllegalArgumentException ignored) {
            // Fall through to hashing the text.
        }
        return Hashing.sha256Text(String.valueOf(value));
    }

    private static void writeString(ByteArrayOutputStream out, String value) throws IOException {
        byte[] bytes = String.valueOf(value).getBytes(StandardCharsets.UTF_8);
        Varint.writeUnsigned(out, bytes.length);
        out.write(bytes);
    }

    private static void writeFixedHash(ByteArrayOutputStream out, String value) throws IOException {
        byte[] bytes;
        try {
            bytes = Hashing.fromHex(value);
        } catch (IllegalArgumentException error) {
            bytes = Hashing.sha256Text(String.valueOf(value));
        }
        if (bytes.length != 32) {
            bytes = Hashing.sha256(bytes);
        }
        out.write(bytes);
    }

    private static void writeU16(ByteArrayOutputStream out, int value) {
        out.write(value & 255);
        out.write((value >>> 8) & 255);
    }

    private static void writeI16(ByteArrayOutputStream out, short value) {
        writeU16(out, value & 0xffff);
    }

    private static void writeLongLe(ByteArrayOutputStream out, long value) {
        for (int index = 0; index < 8; index++) {
            out.write((int) (value >>> (index * 8)) & 255);
        }
    }

    private static void writeQuantized(ByteArrayOutputStream out, double value, double scale) {
        Varint.writeSigned(out, Math.round(value * scale));
    }

    private static short q16(double value) {
        return (short) Math.round(Vec3.clamp(value, -1.0, 1.0) * 32767.0);
    }
}
