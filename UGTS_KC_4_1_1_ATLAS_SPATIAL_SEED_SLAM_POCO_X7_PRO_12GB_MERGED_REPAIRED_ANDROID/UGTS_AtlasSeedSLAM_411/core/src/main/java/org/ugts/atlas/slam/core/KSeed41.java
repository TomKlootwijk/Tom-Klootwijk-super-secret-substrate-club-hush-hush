package org.ugts.atlas.slam.core;

import java.nio.charset.StandardCharsets;

/** Binary format constants for the reconstructed UGTS-KC KSEED 4.1 contract. */
public final class KSeed41 {
    public static final byte[] MAGIC = new byte[] {'K','S','E','E','D','4','1',0};
    public static final int VERSION_MAJOR = 4;
    public static final int VERSION_MINOR = 1;
    public static final int HEADER_BYTES = 128;
    public static final int CHUNK_HEADER_BYTES = 64;
    public static final int SUMMARY_BYTES = 60;
    public static final int STORAGE_MODE_EVIDENCE_DELTAS = 1;
    public static final int FLAG_COMPRESSED = 1;
    public static final int FLAG_SYNTHETIC = 1 << 15;

    public static final int CHUNK_FRAME_EVIDENCE = 1;
    public static final int CHUNK_KEYFRAMES = 2;
    public static final int CHUNK_LEDGER = 3;
    public static final int CHUNK_VOXELS = 4;
    public static final int CHUNK_CALIBRATION = 5;
    public static final int CHUNK_SUMMARY = 255;

    public static final byte[] INITIAL_CHAIN = Hashing.sha256(
            "KSEED41-CHAIN".getBytes(StandardCharsets.UTF_8));

    private KSeed41() {}
}
