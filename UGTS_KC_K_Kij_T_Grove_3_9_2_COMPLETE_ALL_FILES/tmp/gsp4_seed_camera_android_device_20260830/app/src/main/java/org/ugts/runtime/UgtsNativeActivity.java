package org.ugts.runtime;

import android.Manifest;
import android.app.NativeActivity;
import android.content.pm.PackageManager;
import android.graphics.SurfaceTexture;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.view.Surface;

import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Minimal API-26 bridge between the NDK decoder and a GLES external texture.
 * updateTexImage is deliberately invoked only through consumeVideoFrame, which
 * the native render thread calls while its EGL context is current.
 */
public final class UgtsNativeActivity extends NativeActivity
        implements SurfaceTexture.OnFrameAvailableListener {
    private static final String TAG = "UGTS-KC392";
    public static final long NO_VIDEO_FRAME = Long.MIN_VALUE;

    private final AtomicBoolean videoFrameAvailable = new AtomicBoolean(false);
    private SurfaceTexture videoSurfaceTexture;
    private Surface videoSurface;

    /** Camera access is requested only after an editable scene recorder asks for it. */
    public boolean hasCameraPermission() {
        return checkSelfPermission(Manifest.permission.CAMERA)
                == PackageManager.PERMISSION_GRANTED;
    }

    public void requestCameraPermission() {
        if (hasCameraPermission()) return;
        runOnUiThread(() -> requestPermissions(
                new String[] { Manifest.permission.CAMERA }, 3921));
    }

    public synchronized Surface createVideoSurface(int externalTextureName) {
        releaseVideoSurface();
        videoSurfaceTexture = new SurfaceTexture(externalTextureName);
        videoSurfaceTexture.setOnFrameAvailableListener(
                this, new Handler(Looper.getMainLooper()));
        videoSurface = new Surface(videoSurfaceTexture);
        videoFrameAvailable.set(false);
        Log.i(TAG, "chrono SurfaceTexture created; GL consumption stays on render thread");
        return videoSurface;
    }

    @Override
    public void onFrameAvailable(SurfaceTexture ignored) {
        // Native releases no second codec output until this flag is consumed,
        // so a pre-existing true value is an invariant violation, not a queue.
        if (!videoFrameAvailable.compareAndSet(false, true)) {
            Log.e(TAG, "chrono SurfaceTexture callback arrived while a frame was already pending");
        }
    }

    /**
     * @return SurfaceTexture timestamp in nanoseconds, or NO_VIDEO_FRAME.
     */
    public synchronized long consumeVideoFrame(float[] transform) {
        if (!videoFrameAvailable.compareAndSet(true, false)) return NO_VIDEO_FRAME;
        if (videoSurfaceTexture == null || transform == null || transform.length != 16) {
            throw new IllegalStateException("chrono SurfaceTexture bridge is not initialized");
        }
        videoSurfaceTexture.updateTexImage();
        videoSurfaceTexture.getTransformMatrix(transform);
        return videoSurfaceTexture.getTimestamp();
    }

    public synchronized void releaseVideoSurface() {
        videoFrameAvailable.set(false);
        if (videoSurface != null) {
            videoSurface.release();
            videoSurface = null;
        }
        if (videoSurfaceTexture != null) {
            videoSurfaceTexture.setOnFrameAvailableListener(null);
            videoSurfaceTexture.release();
            videoSurfaceTexture = null;
            Log.i(TAG, "chrono SurfaceTexture released");
        }
    }
}
