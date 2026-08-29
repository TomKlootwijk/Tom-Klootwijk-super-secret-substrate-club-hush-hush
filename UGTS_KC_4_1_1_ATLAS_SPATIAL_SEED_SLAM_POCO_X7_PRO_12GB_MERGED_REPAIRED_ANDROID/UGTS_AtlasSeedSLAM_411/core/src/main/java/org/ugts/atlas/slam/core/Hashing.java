package org.ugts.atlas.slam.core;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Locale;
import java.util.zip.CRC32;

/** Small deterministic integrity helpers shared by the ledger and KSEED codec. */
public final class Hashing {
    private Hashing() {}

    public static byte[] sha256(byte[]... parts) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            for (byte[] part : parts) {
                if (part != null) {
                    digest.update(part);
                }
            }
            return digest.digest();
        } catch (NoSuchAlgorithmException error) {
            throw new IllegalStateException("SHA-256 unavailable", error);
        }
    }

    public static byte[] sha256Text(String value) {
        return sha256(value.getBytes(StandardCharsets.UTF_8));
    }

    public static long crc32(byte[] value) {
        CRC32 crc = new CRC32();
        crc.update(value);
        return crc.getValue();
    }

    public static long crc32(byte[] value, int offset, int length) {
        CRC32 crc = new CRC32();
        crc.update(value, offset, length);
        return crc.getValue();
    }

    public static String hex(byte[] value) {
        StringBuilder text = new StringBuilder(value.length * 2);
        for (byte item : value) {
            text.append(String.format(Locale.ROOT, "%02x", item & 255));
        }
        return text.toString();
    }

    public static byte[] fromHex(String value) {
        if (value == null || (value.length() & 1) != 0) {
            throw new IllegalArgumentException("invalid hexadecimal text");
        }
        byte[] output = new byte[value.length() / 2];
        for (int index = 0; index < output.length; index++) {
            int hi = Character.digit(value.charAt(index * 2), 16);
            int lo = Character.digit(value.charAt(index * 2 + 1), 16);
            if (hi < 0 || lo < 0) {
                throw new IllegalArgumentException("invalid hexadecimal text");
            }
            output[index] = (byte) ((hi << 4) | lo);
        }
        return output;
    }

    public static byte[] longLe(long value) {
        return ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN).putLong(value).array();
    }
}
