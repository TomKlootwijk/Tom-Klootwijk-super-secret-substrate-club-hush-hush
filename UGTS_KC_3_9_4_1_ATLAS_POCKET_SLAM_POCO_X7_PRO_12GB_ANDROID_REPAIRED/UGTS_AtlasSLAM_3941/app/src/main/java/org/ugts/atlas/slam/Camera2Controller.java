package org.ugts.atlas.slam;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Context;
import android.content.pm.PackageManager;
import android.graphics.ImageFormat;
import android.graphics.Matrix;
import android.graphics.RectF;
import android.graphics.SurfaceTexture;
import android.hardware.camera2.CameraAccessException;
import android.hardware.camera2.CameraCaptureSession;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraDevice;
import android.hardware.camera2.CameraManager;
import android.hardware.camera2.CaptureRequest;
import android.hardware.camera2.params.StreamConfigurationMap;
import android.media.Image;
import android.media.ImageReader;
import android.os.Handler;
import android.os.HandlerThread;
import android.util.Size;
import android.view.Surface;
import android.view.TextureView;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;

/**
 * Dependency-free platform Camera2 preview and YUV analysis controller.
 * It maintains at most two YUV Images and always acquires the newest frame.
 */
final class Camera2Controller {
    interface Listener {
        void onCameraReady(String description);
        void onCameraError(Throwable error);
    }

    private final Activity activity;
    private final TextureView textureView;
    private final FrameAnalyzer analyzer;
    private final Listener listener;
    private HandlerThread cameraThread;
    private Handler cameraHandler;
    private CameraDevice cameraDevice;
    private CameraCaptureSession captureSession;
    private ImageReader imageReader;
    private Surface previewSurface;
    private Size previewSize;
    private Size analysisSize;
    private String cameraId;
    private int sensorToDisplayRotation;
    private volatile boolean running;

    Camera2Controller(
            Activity activity,
            TextureView textureView,
            FrameAnalyzer analyzer,
            Listener listener) {
        this.activity = activity;
        this.textureView = textureView;
        this.analyzer = analyzer;
        this.listener = listener;
    }

    synchronized void start() {
        if (running) {
            return;
        }
        running = true;
        cameraThread = new HandlerThread("ugts-camera2");
        cameraThread.start();
        cameraHandler = new Handler(cameraThread.getLooper());
        textureView.setSurfaceTextureListener(surfaceListener);
        if (textureView.isAvailable()) {
            openCamera();
        }
    }

    synchronized void stop() {
        running = false;
        textureView.setSurfaceTextureListener(null);
        closeCameraObjects();
        HandlerThread thread = cameraThread;
        cameraHandler = null;
        cameraThread = null;
        if (thread != null) {
            thread.quitSafely();
            try {
                thread.join(1200);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        }
    }

    private final TextureView.SurfaceTextureListener surfaceListener =
            new TextureView.SurfaceTextureListener() {
                @Override
                public void onSurfaceTextureAvailable(SurfaceTexture surface, int width, int height) {
                    openCamera();
                }

                @Override
                public void onSurfaceTextureSizeChanged(SurfaceTexture surface, int width, int height) {
                    configureTransform(width, height);
                }

                @Override
                public boolean onSurfaceTextureDestroyed(SurfaceTexture surface) {
                    closeCameraObjects();
                    return true;
                }

                @Override
                public void onSurfaceTextureUpdated(SurfaceTexture surface) {}
            };

    @SuppressLint("MissingPermission")
    private synchronized void openCamera() {
        if (!running || cameraDevice != null || cameraHandler == null || !textureView.isAvailable()) {
            return;
        }
        if (activity.checkSelfPermission(Manifest.permission.CAMERA)
                != PackageManager.PERMISSION_GRANTED) {
            return;
        }
        try {
            CameraManager manager =
                    (CameraManager) activity.getSystemService(Context.CAMERA_SERVICE);
            cameraId = chooseBackCamera(manager);
            if (cameraId == null) {
                throw new IllegalStateException("No back camera available");
            }
            CameraCharacteristics characteristics = manager.getCameraCharacteristics(cameraId);
            StreamConfigurationMap map =
                    characteristics.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP);
            if (map == null) {
                throw new IllegalStateException("No stream configuration map");
            }
            analysisSize = chooseAnalysisSize(map.getOutputSizes(ImageFormat.YUV_420_888));
            previewSize = choosePreviewSize(
                    map.getOutputSizes(SurfaceTexture.class), aspect(analysisSize));
            sensorToDisplayRotation = computeSensorToDisplayRotation(characteristics);
            analyzer.setCamera(cameraId, sensorToDisplayRotation);

            imageReader = ImageReader.newInstance(
                    analysisSize.getWidth(),
                    analysisSize.getHeight(),
                    ImageFormat.YUV_420_888,
                    2);
            imageReader.setOnImageAvailableListener(
                    reader -> {
                        Image image = null;
                        try {
                            image = reader.acquireLatestImage();
                            if (image != null) {
                                Image owned = image;
                                image = null;
                                analyzer.analyze(owned);
                            }
                        } catch (Throwable error) {
                            if (image != null) {
                                image.close();
                            }
                            listener.onCameraError(error);
                        }
                    },
                    cameraHandler);

            configureTransform(textureView.getWidth(), textureView.getHeight());
            manager.openCamera(cameraId, deviceCallback, cameraHandler);
        } catch (Throwable error) {
            closeCameraObjects();
            listener.onCameraError(error);
        }
    }

    private final CameraDevice.StateCallback deviceCallback = new CameraDevice.StateCallback() {
        @Override
        public void onOpened(CameraDevice camera) {
            synchronized (Camera2Controller.this) {
                if (!running) {
                    camera.close();
                    return;
                }
                cameraDevice = camera;
            }
            createSession();
        }

        @Override
        public void onDisconnected(CameraDevice camera) {
            camera.close();
            synchronized (Camera2Controller.this) {
                if (cameraDevice == camera) {
                    cameraDevice = null;
                }
            }
            listener.onCameraError(new IllegalStateException("Camera disconnected"));
        }

        @Override
        public void onError(CameraDevice camera, int error) {
            camera.close();
            synchronized (Camera2Controller.this) {
                if (cameraDevice == camera) {
                    cameraDevice = null;
                }
            }
            listener.onCameraError(new IllegalStateException("Camera2 error " + error));
        }
    };

    private void createSession() {
        CameraDevice camera;
        ImageReader reader;
        Size preview;
        Handler handler;
        synchronized (this) {
            camera = cameraDevice;
            reader = imageReader;
            preview = previewSize;
            handler = cameraHandler;
        }
        if (camera == null || reader == null || preview == null || handler == null) {
            return;
        }
        try {
            SurfaceTexture texture = textureView.getSurfaceTexture();
            if (texture == null) {
                throw new IllegalStateException("Preview surface is unavailable");
            }
            texture.setDefaultBufferSize(preview.getWidth(), preview.getHeight());
            Surface localPreviewSurface = new Surface(texture);
            synchronized (this) {
                if (previewSurface != null) {
                    previewSurface.release();
                }
                previewSurface = localPreviewSurface;
            }
            Surface analysisSurface = reader.getSurface();
            CaptureRequest.Builder request = camera.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW);
            request.addTarget(localPreviewSurface);
            request.addTarget(analysisSurface);
            request.set(CaptureRequest.CONTROL_AF_MODE,
                    CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_VIDEO);
            request.set(CaptureRequest.CONTROL_AE_MODE,
                    CaptureRequest.CONTROL_AE_MODE_ON);
            request.set(CaptureRequest.CONTROL_AWB_MODE,
                    CaptureRequest.CONTROL_AWB_MODE_AUTO);

            camera.createCaptureSession(
                    Arrays.asList(localPreviewSurface, analysisSurface),
                    new CameraCaptureSession.StateCallback() {
                        @Override
                        public void onConfigured(CameraCaptureSession session) {
                            synchronized (Camera2Controller.this) {
                                if (!running || cameraDevice == null) {
                                    session.close();
                                    return;
                                }
                                captureSession = session;
                            }
                            try {
                                session.setRepeatingRequest(request.build(), null, handler);
                                listener.onCameraReady(
                                        "Camera2 "
                                                + preview.getWidth() + "×" + preview.getHeight()
                                                + " · analysis "
                                                + analysisSize.getWidth() + "×" + analysisSize.getHeight());
                            } catch (CameraAccessException error) {
                                listener.onCameraError(error);
                            }
                        }

                        @Override
                        public void onConfigureFailed(CameraCaptureSession session) {
                            listener.onCameraError(
                                    new IllegalStateException("Camera session configuration failed"));
                        }
                    },
                    handler);
        } catch (Throwable error) {
            listener.onCameraError(error);
        }
    }

    private synchronized void closeCameraObjects() {
        if (captureSession != null) {
            try {
                captureSession.stopRepeating();
            } catch (Exception ignored) {}
            captureSession.close();
            captureSession = null;
        }
        if (cameraDevice != null) {
            cameraDevice.close();
            cameraDevice = null;
        }
        if (imageReader != null) {
            imageReader.close();
            imageReader = null;
        }
        if (previewSurface != null) {
            previewSurface.release();
            previewSurface = null;
        }
    }

    private String chooseBackCamera(CameraManager manager) throws CameraAccessException {
        String fallback = null;
        for (String id : manager.getCameraIdList()) {
            CameraCharacteristics c = manager.getCameraCharacteristics(id);
            Integer facing = c.get(CameraCharacteristics.LENS_FACING);
            if (fallback == null) {
                fallback = id;
            }
            if (facing != null && facing == CameraCharacteristics.LENS_FACING_BACK) {
                return id;
            }
        }
        return fallback;
    }

    private int computeSensorToDisplayRotation(CameraCharacteristics c) {
        Integer orientation = c.get(CameraCharacteristics.SENSOR_ORIENTATION);
        int sensor = orientation == null ? 90 : orientation;
        int displayRotation = activity.getWindowManager().getDefaultDisplay().getRotation();
        int displayDegrees;
        switch (displayRotation) {
            case Surface.ROTATION_90:
                displayDegrees = 90;
                break;
            case Surface.ROTATION_180:
                displayDegrees = 180;
                break;
            case Surface.ROTATION_270:
                displayDegrees = 270;
                break;
            default:
                displayDegrees = 0;
        }
        return Math.floorMod(sensor - displayDegrees, 360);
    }

    private void configureTransform(int viewWidth, int viewHeight) {
        Size size = previewSize;
        if (size == null || viewWidth <= 0 || viewHeight <= 0) {
            return;
        }
        int rotation = activity.getWindowManager().getDefaultDisplay().getRotation();
        Matrix matrix = new Matrix();
        RectF viewRect = new RectF(0, 0, viewWidth, viewHeight);
        float centerX = viewRect.centerX();
        float centerY = viewRect.centerY();
        if (rotation == Surface.ROTATION_90 || rotation == Surface.ROTATION_270) {
            RectF bufferRect = new RectF(0, 0, size.getHeight(), size.getWidth());
            bufferRect.offset(centerX - bufferRect.centerX(), centerY - bufferRect.centerY());
            matrix.setRectToRect(viewRect, bufferRect, Matrix.ScaleToFit.FILL);
            float scale = Math.max(
                    (float) viewHeight / size.getHeight(),
                    (float) viewWidth / size.getWidth());
            matrix.postScale(scale, scale, centerX, centerY);
            matrix.postRotate(90f * (rotation - 2), centerX, centerY);
        } else if (rotation == Surface.ROTATION_180) {
            matrix.postRotate(180f, centerX, centerY);
        } else {
            // Most portrait phones expose a sensor rotated by 90 degrees.
            matrix.postRotate(sensorToDisplayRotation, centerX, centerY);
            float rotatedW = size.getHeight();
            float rotatedH = size.getWidth();
            float scale = Math.max(viewWidth / rotatedW, viewHeight / rotatedH);
            matrix.postScale(scale, scale, centerX, centerY);
        }
        activity.runOnUiThread(() -> textureView.setTransform(matrix));
    }

    private static Size chooseAnalysisSize(Size[] sizes) {
        if (sizes == null || sizes.length == 0) {
            return new Size(640, 480);
        }
        List<Size> candidates = new ArrayList<>(Arrays.asList(sizes));
        candidates.sort(Comparator.comparingLong(Camera2Controller::area));
        Size best = candidates.get(0);
        double bestScore = Double.POSITIVE_INFINITY;
        for (Size size : candidates) {
            int longEdge = Math.max(size.getWidth(), size.getHeight());
            int shortEdge = Math.min(size.getWidth(), size.getHeight());
            if (longEdge < 640 || longEdge > 1280 || shortEdge < 360) {
                continue;
            }
            double score = Math.abs(longEdge - 800.0)
                    + Math.abs(aspect(size) - 4.0 / 3.0) * 260.0;
            if (score < bestScore) {
                best = size;
                bestScore = score;
            }
        }
        return best;
    }

    private static Size choosePreviewSize(Size[] sizes, double targetAspect) {
        if (sizes == null || sizes.length == 0) {
            return new Size(1280, 720);
        }
        Size best = sizes[0];
        double bestScore = Double.POSITIVE_INFINITY;
        for (Size size : sizes) {
            int longEdge = Math.max(size.getWidth(), size.getHeight());
            if (longEdge > 1920) {
                continue;
            }
            double score = Math.abs(aspect(size) - targetAspect) * 1800.0
                    + Math.abs(longEdge - 1280.0);
            if (score < bestScore) {
                best = size;
                bestScore = score;
            }
        }
        return best;
    }

    private static long area(Size size) {
        return (long) size.getWidth() * size.getHeight();
    }

    private static double aspect(Size size) {
        int longEdge = Math.max(size.getWidth(), size.getHeight());
        int shortEdge = Math.min(size.getWidth(), size.getHeight());
        return shortEdge == 0 ? 1.0 : (double) longEdge / shortEdge;
    }
}
