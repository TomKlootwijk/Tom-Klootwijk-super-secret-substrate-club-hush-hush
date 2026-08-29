package org.ugts.atlas.slam.core;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;

/** Versioned 128-bit session seed. It schedules deterministic work; it is not encryption. */
public final class Seed128 {
    public static final Seed128 ZERO = new Seed128(0L, 0L);
    public final long high;
    public final long low;

    public Seed128(long high, long low) {
        this.high = high;
        this.low = low;
    }

    public static Seed128 derive(String label) {
        byte[] digest = Hashing.sha256(label.getBytes(StandardCharsets.UTF_8));
        ByteBuffer buffer = ByteBuffer.wrap(digest).order(ByteOrder.BIG_ENDIAN);
        return new Seed128(buffer.getLong(), buffer.getLong());
    }

    public static Seed128 derive(String sessionId, long startTimeNs) {
        return derive("UGTS-KC-4.1.1|" + String.valueOf(sessionId) + "|" + startTimeNs);
    }

    public static Seed128 fromBytes(byte[] bytes) {
        if (bytes == null || bytes.length != 16) {
            throw new IllegalArgumentException("seed must contain exactly 16 bytes");
        }
        ByteBuffer buffer = ByteBuffer.wrap(bytes).order(ByteOrder.BIG_ENDIAN);
        return new Seed128(buffer.getLong(), buffer.getLong());
    }

    public static Seed128 fromHex(String value) {
        return fromBytes(Hashing.fromHex(value));
    }

    public byte[] toBytes() {
        return ByteBuffer.allocate(16).order(ByteOrder.BIG_ENDIAN)
                .putLong(high).putLong(low).array();
    }

    public String toHex() {
        return Hashing.hex(toBytes());
    }

    public String stableId(String namespace, long index) {
        byte[] digest = Hashing.sha256(
                toBytes(),
                namespace.getBytes(StandardCharsets.UTF_8),
                Hashing.longLe(index));
        return namespace + ":" + Hashing.hex(Arrays.copyOf(digest, 12));
    }

    @Override
    public boolean equals(Object value) {
        return value instanceof Seed128
                && ((Seed128) value).high == high
                && ((Seed128) value).low == low;
    }

    @Override
    public int hashCode() {
        return (int) (high ^ (high >>> 32) ^ low ^ (low >>> 32));
    }

    @Override
    public String toString() {
        return toHex();
    }
}
