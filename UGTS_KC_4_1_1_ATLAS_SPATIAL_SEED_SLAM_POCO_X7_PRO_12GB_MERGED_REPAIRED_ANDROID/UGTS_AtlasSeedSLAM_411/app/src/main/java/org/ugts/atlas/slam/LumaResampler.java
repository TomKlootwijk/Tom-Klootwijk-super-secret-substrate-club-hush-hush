package org.ugts.atlas.slam;

import android.media.Image;
import java.nio.ByteBuffer;
import org.ugts.atlas.slam.core.GrayFrame;

/** Direct Y-plane extraction, rotation and bounded nearest-neighbour downsample. */
final class LumaResampler {
    private LumaResampler() {}

    static GrayFrame convert(Image image, int clockwiseRotationDegrees, int maxLongEdge) {
        int sw = image.getWidth();
        int sh = image.getHeight();
        int rot = Math.floorMod(clockwiseRotationDegrees, 360);
        if (rot % 90 != 0) {
            throw new IllegalArgumentException("rotation must be a right angle");
        }

        int rw = (rot == 90 || rot == 270) ? sh : sw;
        int rh = (rot == 90 || rot == 270) ? sw : sh;
        double scale = Math.min(1.0, (double) maxLongEdge / Math.max(rw, rh));
        int ow = Math.max(64, ((int) Math.round(rw * scale)) & ~1);
        int oh = Math.max(64, ((int) Math.round(rh * scale)) & ~1);

        Image.Plane plane = image.getPlanes()[0];
        ByteBuffer buffer = plane.getBuffer().duplicate();
        int rowStride = plane.getRowStride();
        int pixelStride = plane.getPixelStride();
        int base = buffer.position();
        int limit = buffer.limit();
        byte[] out = new byte[ow * oh];

        for (int y = 0; y < oh; y++) {
            int dy = Math.min(rh - 1, Math.max(0, (int) (((y + 0.5) * rh) / oh)));
            int row = y * ow;
            for (int x = 0; x < ow; x++) {
                int dx = Math.min(rw - 1, Math.max(0, (int) (((x + 0.5) * rw) / ow)));
                int sx;
                int sy;
                if (rot == 90) {
                    sx = dy;
                    sy = sh - 1 - dx;
                } else if (rot == 180) {
                    sx = sw - 1 - dx;
                    sy = sh - 1 - dy;
                } else if (rot == 270) {
                    sx = sw - 1 - dy;
                    sy = dx;
                } else {
                    sx = dx;
                    sy = dy;
                }
                int index = base + sy * rowStride + sx * pixelStride;
                out[row + x] = index >= base && index < limit ? buffer.get(index) : 0;
            }
        }
        return new GrayFrame(ow, oh, image.getTimestamp(), out);
    }
}
