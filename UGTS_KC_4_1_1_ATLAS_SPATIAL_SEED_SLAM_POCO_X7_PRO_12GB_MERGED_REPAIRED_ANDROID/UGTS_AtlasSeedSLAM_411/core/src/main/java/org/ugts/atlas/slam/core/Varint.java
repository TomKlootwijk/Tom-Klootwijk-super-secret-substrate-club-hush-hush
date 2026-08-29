package org.ugts.atlas.slam.core;

import java.io.ByteArrayOutputStream;
import java.io.EOFException;
import java.io.IOException;
import java.io.InputStream;

public final class Varint {
    private Varint() {}

    public static void writeUnsigned(ByteArrayOutputStream out, long value) {
        while ((value & ~0x7fL) != 0) {
            out.write((int) (value & 0x7f) | 0x80);
            value >>>= 7;
        }
        out.write((int) value);
    }

    public static long readUnsigned(InputStream input) throws IOException {
        long value = 0;
        int shift = 0;
        while (shift < 64) {
            int item = input.read();
            if (item < 0) {
                throw new EOFException();
            }
            value |= (long) (item & 0x7f) << shift;
            if ((item & 0x80) == 0) {
                return value;
            }
            shift += 7;
        }
        throw new IOException("varint overflow");
    }

    public static long zigzag(int value) {
        return ((long) value << 1) ^ (value >> 31);
    }

    public static int unzigzag(long value) {
        return (int) ((value >>> 1) ^ -(value & 1));
    }

    public static long zigzagLong(long value) {
        return (value << 1) ^ (value >> 63);
    }

    public static long unzigzagLong(long value) {
        return (value >>> 1) ^ -(value & 1L);
    }

    public static void writeSigned(ByteArrayOutputStream out, long value) {
        writeUnsigned(out, zigzagLong(value));
    }

    public static long readSigned(InputStream input) throws IOException {
        return unzigzagLong(readUnsigned(input));
    }
}
