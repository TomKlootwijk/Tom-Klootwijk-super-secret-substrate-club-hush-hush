package org.ugts.atlas.slam;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RectF;
import android.view.View;
import java.util.List;
import org.ugts.atlas.slam.core.MapPoint;
import org.ugts.atlas.slam.core.SlamSnapshot;
import org.ugts.atlas.slam.core.Vec3;

/** Lightweight overlay: tracked features plus a bounded top-down map sample. */
final class ScanOverlayView extends View {
    private final Paint feature = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint mapPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint pathPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint panel = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint text = new Paint(Paint.ANTI_ALIAS_FLAG);
    private volatile SlamSnapshot snapshot;

    ScanOverlayView(Context context) {
        super(context);
        setWillNotDraw(false);
        float density = getResources().getDisplayMetrics().density;
        feature.setColor(Color.argb(180, 40, 240, 205));
        feature.setStyle(Paint.Style.STROKE);
        feature.setStrokeWidth(1.2f * density);
        mapPaint.setColor(Color.argb(210, 255, 210, 80));
        mapPaint.setStrokeWidth(1.6f * density);
        pathPaint.setColor(Color.argb(230, 40, 210, 255));
        pathPaint.setStrokeWidth(2.0f * density);
        pathPaint.setStyle(Paint.Style.STROKE);
        panel.setColor(Color.argb(150, 8, 15, 22));
        text.setColor(Color.WHITE);
        text.setTextSize(15f * density);
    }

    void setSnapshot(SlamSnapshot value) {
        snapshot = value;
        postInvalidateOnAnimation();
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        SlamSnapshot value = snapshot;
        if (value == null) {
            return;
        }
        float density = getResources().getDisplayMetrics().density;
        float sx = (float) getWidth() / Math.max(1, value.imageWidth);
        float sy = (float) getHeight() / Math.max(1, value.imageHeight);
        float[] xy = value.featureXY;
        for (int i = 0; i + 1 < xy.length; i += 2) {
            canvas.drawCircle(xy[i] * sx, xy[i + 1] * sy, 2.2f * density, feature);
        }

        float box = Math.min(getWidth(), getHeight()) * 0.34f;
        float margin = 12f * density;
        float left = getWidth() - box - margin;
        float top = 82f * density;
        canvas.drawRoundRect(
                new RectF(left, top, left + box, top + box),
                9f * density,
                9f * density,
                panel);
        drawMap(canvas, value.mapSample, value.trajectory, left, top, box);
        String units = "metric_anchor".equals(value.scaleState) ? "m" : "relative";
        canvas.drawText(
                value.mapPointCount + " voxels · " + value.inlierCount + " inliers · " + units,
                margin,
                getHeight() - 116f * density,
                text);
    }

    private void drawMap(
            Canvas canvas,
            List<MapPoint> points,
            List<Vec3> path,
            float left,
            float top,
            float box) {
        if (points.isEmpty() && path.isEmpty()) {
            return;
        }
        double minX = Double.POSITIVE_INFINITY;
        double minZ = Double.POSITIVE_INFINITY;
        double maxX = Double.NEGATIVE_INFINITY;
        double maxZ = Double.NEGATIVE_INFINITY;
        for (MapPoint point : points) {
            minX = Math.min(minX, point.position.x);
            maxX = Math.max(maxX, point.position.x);
            minZ = Math.min(minZ, point.position.z);
            maxZ = Math.max(maxZ, point.position.z);
        }
        for (Vec3 point : path) {
            minX = Math.min(minX, point.x);
            maxX = Math.max(maxX, point.x);
            minZ = Math.min(minZ, point.z);
            maxZ = Math.max(maxZ, point.z);
        }
        double span = Math.max(1e-3, Math.max(maxX - minX, maxZ - minZ));
        float scale = (float) (box * 0.86 / span);
        float originX = left + box * 0.07f;
        float originY = top + box * 0.93f;
        for (MapPoint point : points) {
            canvas.drawPoint(
                    originX + (float) ((point.position.x - minX) * scale),
                    originY - (float) ((point.position.z - minZ) * scale),
                    mapPaint);
        }
        for (int i = 1; i < path.size(); i++) {
            Vec3 a = path.get(i - 1);
            Vec3 b = path.get(i);
            canvas.drawLine(
                    originX + (float) ((a.x - minX) * scale),
                    originY - (float) ((a.z - minZ) * scale),
                    originX + (float) ((b.x - minX) * scale),
                    originY - (float) ((b.z - minZ) * scale),
                    pathPaint);
        }
    }
}
