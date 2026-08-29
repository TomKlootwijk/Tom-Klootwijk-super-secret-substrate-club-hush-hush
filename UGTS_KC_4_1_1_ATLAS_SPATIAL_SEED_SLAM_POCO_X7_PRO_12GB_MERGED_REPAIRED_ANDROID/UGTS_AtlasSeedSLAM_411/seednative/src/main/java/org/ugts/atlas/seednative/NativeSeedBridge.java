package org.ugts.atlas.seednative;

/** Optional arm64 native accelerator. Failure falls back to the Java oracle. */
public final class NativeSeedBridge {
    private static final boolean AVAILABLE;
    private static final String STATUS;

    static {
        boolean loaded = false;
        String status;
        try {
            System.loadLibrary("ugts_seed_native");
            loaded = nativeSelfTest();
            status = loaded
                    ? String.format("native_abi_%08x", nativeAbiVersion())
                    : "native_self_test_failed";
        } catch (Throwable error) {
            status = "java_fallback_" + error.getClass().getSimpleName();
        }
        AVAILABLE = loaded;
        STATUS = status;
    }

    private NativeSeedBridge() {}

    public static boolean isAvailable() {
        return AVAILABLE;
    }

    public static String status() {
        return STATUS;
    }

    public static int crc32(byte[] input) {
        if (!AVAILABLE) {
            throw new IllegalStateException("native seed library unavailable");
        }
        return nativeCrc32(input);
    }

    public static int scheduleBounded(
            long seedHigh, long seedLow, long stream, long index, int bound) {
        if (!AVAILABLE) {
            throw new IllegalStateException("native seed library unavailable");
        }
        return nativeScheduleBounded(seedHigh, seedLow, stream, index, bound);
    }

    private static native int nativeAbiVersion();
    private static native boolean nativeSelfTest();
    private static native int nativeCrc32(byte[] input);
    private static native int nativeScheduleBounded(
            long seedHigh, long seedLow, long stream, long index, int bound);
}
