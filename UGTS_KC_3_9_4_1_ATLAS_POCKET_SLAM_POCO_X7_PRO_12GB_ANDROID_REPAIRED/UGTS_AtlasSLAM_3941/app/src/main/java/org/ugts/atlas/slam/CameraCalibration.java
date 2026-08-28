package org.ugts.atlas.slam;

import android.content.Context;
import android.graphics.Rect;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraManager;
import android.util.SizeF;
import org.ugts.atlas.slam.core.CameraModel;

/**
 * Reads Camera2 intrinsics without persisting a camera ID. A factory intrinsic
 * calibration is preferred; physical-size metadata is explicitly labelled as
 * an estimate rather than a completed session calibration.
 */
final class CameraCalibration {
    private CameraCalibration() {}

    static CameraModel forCamera(
            Context context,
            String cameraId,
            int outputWidth,
            int outputHeight,
            int clockwiseRotationDegrees) {
        if (cameraId == null) {
            return CameraModel.declaredFallback(outputWidth, outputHeight);
        }
        try {
            CameraManager manager = (CameraManager) context.getSystemService(Context.CAMERA_SERVICE);
            CameraCharacteristics c = manager.getCameraCharacteristics(cameraId);
            Rect active = c.get(CameraCharacteristics.SENSOR_INFO_ACTIVE_ARRAY_SIZE);
            float[] intrinsic = c.get(CameraCharacteristics.LENS_INTRINSIC_CALIBRATION);
            int rotation = Math.floorMod(clockwiseRotationDegrees, 360);

            if (active != null && intrinsic != null && intrinsic.length >= 4
                    && intrinsic[0] > 0 && intrinsic[1] > 0) {
                return mapFactoryIntrinsics(
                        active, intrinsic, outputWidth, outputHeight, rotation);
            }

            float[] focal = c.get(CameraCharacteristics.LENS_INFO_AVAILABLE_FOCAL_LENGTHS);
            SizeF sensor = c.get(CameraCharacteristics.SENSOR_INFO_PHYSICAL_SIZE);
            if (focal != null && focal.length > 0 && sensor != null
                    && sensor.getWidth() > 0 && sensor.getHeight() > 0) {
                boolean swap = rotation == 90 || rotation == 270;
                double physicalW = swap ? sensor.getHeight() : sensor.getWidth();
                double physicalH = swap ? sensor.getWidth() : sensor.getHeight();
                double fx = focal[0] / physicalW * outputWidth;
                double fy = focal[0] / physicalH * outputHeight;
                return new CameraModel(
                        outputWidth,
                        outputHeight,
                        fx,
                        fy,
                        (outputWidth - 1) * 0.5,
                        (outputHeight - 1) * 0.5,
                        false,
                        "camera2_physical_metadata_estimate");
            }
        } catch (Exception ignored) {
            // Explicitly fall through to the declared generic model.
        }
        return CameraModel.declaredFallback(outputWidth, outputHeight);
    }

    private static CameraModel mapFactoryIntrinsics(
            Rect active,
            float[] intrinsic,
            int outputWidth,
            int outputHeight,
            int rotation) {
        int rawOutputWidth = (rotation == 90 || rotation == 270) ? outputHeight : outputWidth;
        int rawOutputHeight = (rotation == 90 || rotation == 270) ? outputWidth : outputHeight;
        double rawAspect = (double) rawOutputWidth / rawOutputHeight;
        double activeAspect = (double) active.width() / active.height();

        double cropLeft = active.left;
        double cropTop = active.top;
        double cropWidth = active.width();
        double cropHeight = active.height();
        if (activeAspect > rawAspect) {
            cropWidth = cropHeight * rawAspect;
            cropLeft += (active.width() - cropWidth) * 0.5;
        } else if (activeAspect < rawAspect) {
            cropHeight = cropWidth / rawAspect;
            cropTop += (active.height() - cropHeight) * 0.5;
        }

        double sx = rawOutputWidth / cropWidth;
        double sy = rawOutputHeight / cropHeight;
        double rawFx = intrinsic[0] * sx;
        double rawFy = intrinsic[1] * sy;
        double rawCx = (intrinsic[2] - cropLeft) * sx;
        double rawCy = (intrinsic[3] - cropTop) * sy;

        double fx;
        double fy;
        double cx;
        double cy;
        if (rotation == 90) {
            fx = rawFy;
            fy = rawFx;
            cx = rawOutputHeight - 1.0 - rawCy;
            cy = rawCx;
        } else if (rotation == 180) {
            fx = rawFx;
            fy = rawFy;
            cx = rawOutputWidth - 1.0 - rawCx;
            cy = rawOutputHeight - 1.0 - rawCy;
        } else if (rotation == 270) {
            fx = rawFy;
            fy = rawFx;
            cx = rawCy;
            cy = rawOutputWidth - 1.0 - rawCx;
        } else {
            fx = rawFx;
            fy = rawFy;
            cx = rawCx;
            cy = rawCy;
        }
        return new CameraModel(
                outputWidth,
                outputHeight,
                fx,
                fy,
                cx,
                cy,
                true,
                "camera2_factory_intrinsic_calibration");
    }
}
