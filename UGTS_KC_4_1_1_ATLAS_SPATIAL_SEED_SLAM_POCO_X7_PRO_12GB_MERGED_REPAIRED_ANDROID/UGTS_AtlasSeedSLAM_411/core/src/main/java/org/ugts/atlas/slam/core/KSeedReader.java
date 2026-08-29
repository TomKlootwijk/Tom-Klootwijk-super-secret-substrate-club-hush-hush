package org.ugts.atlas.slam.core;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.zip.DataFormatException;
import java.util.zip.Inflater;

/** Independent-in-process framing, CRC, zlib and SHA-chain verifier. */
public final class KSeedReader {
    public static final class ChunkInfo {
        public final int type;
        public final int flags;
        public final int sequence;
        public final long recordCount;
        public final int decodedLength;
        public final int storedLength;
        public final int schemaId;
        public final String chainSha256;

        ChunkInfo(
                int type,
                int flags,
                int sequence,
                long recordCount,
                int decodedLength,
                int storedLength,
                int schemaId,
                String chainSha256) {
            this.type = type;
            this.flags = flags;
            this.sequence = sequence;
            this.recordCount = recordCount;
            this.decodedLength = decodedLength;
            this.storedLength = storedLength;
            this.schemaId = schemaId;
            this.chainSha256 = chainSha256;
        }
    }

    public static final class Inspection {
        public final Seed128 seed;
        public final long startTimeNs;
        public final int analysisWidth;
        public final int analysisHeight;
        public final int requestedCaptureFps;
        public final int featureBudget;
        public final int headerFlags;
        public final String captureProfileSha256;
        public final String calibrationSha256;
        public final long frames;
        public final long keyframes;
        public final long events;
        public final long voxels;
        public final long rawInputBytes;
        public final long storedBytes;
        public final int rejectedProposals;
        public final int stateFlags;
        public final int chunkCount;
        public final List<ChunkInfo> chunks;
        public final String finalChainSha256;

        Inspection(
                Seed128 seed,
                long startTimeNs,
                int analysisWidth,
                int analysisHeight,
                int requestedCaptureFps,
                int featureBudget,
                int headerFlags,
                String captureProfileSha256,
                String calibrationSha256,
                long frames,
                long keyframes,
                long events,
                long voxels,
                long rawInputBytes,
                long storedBytes,
                int rejectedProposals,
                int stateFlags,
                int chunkCount,
                List<ChunkInfo> chunks,
                String finalChainSha256) {
            this.seed = seed;
            this.startTimeNs = startTimeNs;
            this.analysisWidth = analysisWidth;
            this.analysisHeight = analysisHeight;
            this.requestedCaptureFps = requestedCaptureFps;
            this.featureBudget = featureBudget;
            this.headerFlags = headerFlags;
            this.captureProfileSha256 = captureProfileSha256;
            this.calibrationSha256 = calibrationSha256;
            this.frames = frames;
            this.keyframes = keyframes;
            this.events = events;
            this.voxels = voxels;
            this.rawInputBytes = rawInputBytes;
            this.storedBytes = storedBytes;
            this.rejectedProposals = rejectedProposals;
            this.stateFlags = stateFlags;
            this.chunkCount = chunkCount;
            this.chunks = Collections.unmodifiableList(new ArrayList<>(chunks));
            this.finalChainSha256 = finalChainSha256;
        }

        public String toJson() {
            StringBuilder text = new StringBuilder()
                    .append("{\n")
                    .append("  \"schema\": \"ugts.kseed-inspection/4.1.1\",\n")
                    .append("  \"seed\": \"").append(seed.toHex()).append("\",\n")
                    .append("  \"analysis_width\": ").append(analysisWidth).append(",\n")
                    .append("  \"analysis_height\": ").append(analysisHeight).append(",\n")
                    .append("  \"requested_capture_fps\": ").append(requestedCaptureFps).append(",\n")
                    .append("  \"feature_budget\": ").append(featureBudget).append(",\n")
                    .append("  \"frames\": ").append(frames).append(",\n")
                    .append("  \"keyframes\": ").append(keyframes).append(",\n")
                    .append("  \"events\": ").append(events).append(",\n")
                    .append("  \"voxels\": ").append(voxels).append(",\n")
                    .append("  \"raw_input_bytes\": ").append(rawInputBytes).append(",\n")
                    .append("  \"stored_bytes\": ").append(storedBytes).append(",\n")
                    .append("  \"rejected_proposals\": ").append(rejectedProposals).append(",\n")
                    .append("  \"chunk_count\": ").append(chunkCount).append(",\n")
                    .append("  \"final_chain_sha256\": \"")
                    .append(finalChainSha256).append("\"\n")
                    .append("}\n");
            return text.toString();
        }
    }

    public Inspection read(InputStream input) throws IOException {
        return inspect(readAll(input));
    }

    public Inspection inspect(byte[] bytes) throws IOException {
        if (bytes.length < KSeed41.HEADER_BYTES) {
            throw new IOException("truncated KSEED header");
        }
        byte[] headerBytes = Arrays.copyOfRange(bytes, 0, KSeed41.HEADER_BYTES);
        ByteBuffer header = ByteBuffer.wrap(headerBytes).order(ByteOrder.LITTLE_ENDIAN);
        byte[] magic = new byte[KSeed41.MAGIC.length];
        header.get(magic);
        if (!Arrays.equals(magic, KSeed41.MAGIC)) {
            throw new IOException("KSEED magic mismatch");
        }
        int major = Short.toUnsignedInt(header.getShort());
        int minor = Short.toUnsignedInt(header.getShort());
        int headerSize = Short.toUnsignedInt(header.getShort());
        int mode = Short.toUnsignedInt(header.getShort());
        if (major != KSeed41.VERSION_MAJOR || minor != KSeed41.VERSION_MINOR
                || headerSize != KSeed41.HEADER_BYTES
                || mode != KSeed41.STORAGE_MODE_EVIDENCE_DELTAS) {
            throw new IOException("unsupported KSEED version or mode");
        }
        int headerFlags = header.getInt();
        byte[] seedBytes = new byte[16];
        header.get(seedBytes);
        Seed128 seed = Seed128.fromBytes(seedBytes);
        long startTimeNs = header.getLong();
        int width = header.getInt();
        int height = header.getInt();
        int fps = header.getInt();
        int featureBudget = header.getInt();
        byte[] captureHash = new byte[32];
        byte[] calibrationHash = new byte[32];
        header.get(captureHash);
        header.get(calibrationHash);
        long declaredHeaderCrc = Integer.toUnsignedLong(header.getInt());
        long actualHeaderCrc = Hashing.crc32(headerBytes, 0, 124);
        if (declaredHeaderCrc != actualHeaderCrc) {
            throw new IOException("KSEED header CRC mismatch");
        }

        int offset = KSeed41.HEADER_BYTES;
        int expectedSequence = 0;
        byte[] previousHash = KSeed41.INITIAL_CHAIN;
        ArrayList<ChunkInfo> chunkInfo = new ArrayList<>();
        byte[] summary = null;
        while (offset < bytes.length) {
            if (bytes.length - offset < KSeed41.CHUNK_HEADER_BYTES) {
                throw new IOException("truncated KSEED chunk header");
            }
            byte[] first32 = Arrays.copyOfRange(bytes, offset, offset + 32);
            byte[] declaredChain = Arrays.copyOfRange(bytes, offset + 32, offset + 64);
            ByteBuffer chunk = ByteBuffer.wrap(first32).order(ByteOrder.LITTLE_ENDIAN);
            int type = Short.toUnsignedInt(chunk.getShort());
            int flags = Short.toUnsignedInt(chunk.getShort());
            int sequence = chunk.getInt();
            long recordCount = Integer.toUnsignedLong(chunk.getInt());
            int decodedLength = chunk.getInt();
            int storedLength = chunk.getInt();
            long decodedCrc = Integer.toUnsignedLong(chunk.getInt());
            long storedCrc = Integer.toUnsignedLong(chunk.getInt());
            int schemaId = chunk.getInt();
            if (sequence != expectedSequence++) {
                throw new IOException("KSEED chunk sequence mismatch");
            }
            if (decodedLength < 0 || storedLength < 0
                    || offset + KSeed41.CHUNK_HEADER_BYTES + storedLength > bytes.length) {
                throw new IOException("invalid KSEED chunk lengths");
            }
            byte[] stored = Arrays.copyOfRange(
                    bytes,
                    offset + KSeed41.CHUNK_HEADER_BYTES,
                    offset + KSeed41.CHUNK_HEADER_BYTES + storedLength);
            if (Hashing.crc32(stored) != storedCrc) {
                throw new IOException("KSEED stored CRC mismatch at sequence " + sequence);
            }
            byte[] actualChain = Hashing.sha256(previousHash, first32, stored);
            if (!Arrays.equals(actualChain, declaredChain)) {
                throw new IOException("KSEED SHA-256 chain mismatch at sequence " + sequence);
            }
            byte[] decoded = (flags & KSeed41.FLAG_COMPRESSED) != 0
                    ? inflate(stored, decodedLength)
                    : stored;
            if (decoded.length != decodedLength || Hashing.crc32(decoded) != decodedCrc) {
                throw new IOException("KSEED decoded payload mismatch at sequence " + sequence);
            }
            chunkInfo.add(new ChunkInfo(
                    type,
                    flags,
                    sequence,
                    recordCount,
                    decodedLength,
                    storedLength,
                    schemaId,
                    Hashing.hex(actualChain)));
            if (type == KSeed41.CHUNK_SUMMARY) {
                if (summary != null || decoded.length != KSeed41.SUMMARY_BYTES) {
                    throw new IOException("invalid duplicate or sized KSEED summary");
                }
                summary = decoded;
            }
            previousHash = actualChain;
            offset += KSeed41.CHUNK_HEADER_BYTES + storedLength;
        }
        if (offset != bytes.length || summary == null) {
            throw new IOException("KSEED summary missing or trailing data present");
        }
        if (chunkInfo.get(chunkInfo.size() - 1).type != KSeed41.CHUNK_SUMMARY) {
            throw new IOException("KSEED summary must be final chunk");
        }
        ByteBuffer values = ByteBuffer.wrap(summary).order(ByteOrder.LITTLE_ENDIAN);
        long frames = values.getLong();
        long keyframes = values.getLong();
        long events = values.getLong();
        long voxels = values.getLong();
        long rawInputBytes = values.getLong();
        long storedBytes = values.getLong();
        int rejected = values.getInt();
        int stateFlags = values.getInt();
        int chunkCount = values.getInt();
        if (storedBytes != bytes.length) {
            throw new IOException("KSEED stored_bytes does not equal actual length");
        }
        if (chunkCount != chunkInfo.size()) {
            throw new IOException("KSEED summary chunk count mismatch");
        }
        return new Inspection(
                seed,
                startTimeNs,
                width,
                height,
                fps,
                featureBudget,
                headerFlags,
                Hashing.hex(captureHash),
                Hashing.hex(calibrationHash),
                frames,
                keyframes,
                events,
                voxels,
                rawInputBytes,
                storedBytes,
                rejected,
                stateFlags,
                chunkCount,
                chunkInfo,
                Hashing.hex(previousHash));
    }

    private static byte[] inflate(byte[] stored, int expectedLength) throws IOException {
        Inflater inflater = new Inflater(false);
        inflater.setInput(stored);
        ByteArrayOutputStream output = new ByteArrayOutputStream(expectedLength);
        byte[] buffer = new byte[8192];
        try {
            while (!inflater.finished()) {
                int count = inflater.inflate(buffer);
                if (count > 0) {
                    output.write(buffer, 0, count);
                } else if (inflater.needsDictionary() || inflater.needsInput()) {
                    break;
                }
                if (output.size() > expectedLength) {
                    throw new IOException("inflated KSEED payload exceeds declared length");
                }
            }
        } catch (DataFormatException error) {
            throw new IOException("invalid KSEED zlib payload", error);
        } finally {
            inflater.end();
        }
        byte[] decoded = output.toByteArray();
        if (decoded.length != expectedLength) {
            throw new IOException("KSEED zlib length mismatch");
        }
        return decoded;
    }

    private static byte[] readAll(InputStream input) throws IOException {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        byte[] buffer = new byte[8192];
        int count;
        while ((count = input.read(buffer)) != -1) {
            output.write(buffer, 0, count);
        }
        return output.toByteArray();
    }
}
