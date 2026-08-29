package org.ugts.atlas.slam;

import android.content.Context;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;
import android.os.Handler;
import android.os.HandlerThread;
import org.ugts.atlas.slam.core.Quat;
import org.ugts.atlas.slam.core.Vec3;

/** Bounded timestamped orientation/linear-acceleration ring buffers. */
final class SensorFusion implements SensorEventListener, AutoCloseable {
    private static final int CAPACITY = 512;
    private final SensorManager manager;
    private final Sensor rotation;
    private final Sensor linearAcceleration;
    private final HandlerThread thread;
    private final Handler handler;

    private final long[] orientationTimes = new long[CAPACITY];
    private final Quat[] orientations = new Quat[CAPACITY];
    private int orientationHead;
    private int orientationSize;

    private final long[] accelerationTimes = new long[CAPACITY];
    private final Vec3[] accelerations = new Vec3[CAPACITY];
    private int accelerationHead;
    private int accelerationSize;
    private boolean started;

    SensorFusion(Context context) {
        manager = (SensorManager) context.getSystemService(Context.SENSOR_SERVICE);
        Sensor candidate = manager == null
                ? null
                : manager.getDefaultSensor(Sensor.TYPE_GAME_ROTATION_VECTOR);
        if (candidate == null && manager != null) {
            candidate = manager.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR);
        }
        rotation = candidate;
        linearAcceleration = manager == null
                ? null
                : manager.getDefaultSensor(Sensor.TYPE_LINEAR_ACCELERATION);
        thread = new HandlerThread("ugts-imu");
        thread.start();
        handler = new Handler(thread.getLooper());
    }

    synchronized void start() {
        if (started || manager == null) {
            return;
        }
        started = true;
        if (rotation != null) {
            manager.registerListener(
                    this, rotation, SensorManager.SENSOR_DELAY_GAME, handler);
        }
        if (linearAcceleration != null) {
            manager.registerListener(
                    this, linearAcceleration, SensorManager.SENSOR_DELAY_GAME, handler);
        }
    }

    synchronized void stop() {
        if (!started || manager == null) {
            return;
        }
        started = false;
        manager.unregisterListener(this);
    }

    @Override
    public void close() {
        stop();
        thread.quitSafely();
    }

    @Override
    public synchronized void onSensorChanged(SensorEvent event) {
        int type = event.sensor.getType();
        if (type == Sensor.TYPE_GAME_ROTATION_VECTOR
                || type == Sensor.TYPE_ROTATION_VECTOR) {
            float[] q = new float[4];
            SensorManager.getQuaternionFromVector(q, event.values);
            orientationTimes[orientationHead] = event.timestamp;
            orientations[orientationHead] = new Quat(q[0], q[1], q[2], q[3]);
            orientationHead = (orientationHead + 1) % CAPACITY;
            orientationSize = Math.min(CAPACITY, orientationSize + 1);
        } else if (type == Sensor.TYPE_LINEAR_ACCELERATION) {
            accelerationTimes[accelerationHead] = event.timestamp;
            accelerations[accelerationHead] =
                    new Vec3(event.values[0], event.values[1], event.values[2]);
            accelerationHead = (accelerationHead + 1) % CAPACITY;
            accelerationSize = Math.min(CAPACITY, accelerationSize + 1);
        }
    }

    @Override
    public void onAccuracyChanged(Sensor sensor, int accuracy) {}

    synchronized Quat orientationAt(long timestampNs) {
        if (orientationSize == 0) {
            return Quat.IDENTITY;
        }
        int newest = (orientationHead - 1 + CAPACITY) % CAPACITY;
        int older = newest;
        for (int i = 0; i < orientationSize; i++) {
            int index = (orientationHead - 1 - i + CAPACITY) % CAPACITY;
            if (orientationTimes[index] <= timestampNs) {
                older = index;
                break;
            }
        }
        int newer = (older + 1) % CAPACITY;
        Quat a = orientations[older];
        if (a == null) {
            Quat latest = orientations[newest];
            return latest == null ? Quat.IDENTITY : latest;
        }
        Quat b = orientations[newer];
        if (b == null || orientationTimes[newer] <= orientationTimes[older]
                || timestampNs <= orientationTimes[older]) {
            return a;
        }
        double u = Math.max(
                0.0,
                Math.min(
                        1.0,
                        (double) (timestampNs - orientationTimes[older])
                                / (orientationTimes[newer] - orientationTimes[older])));
        return Quat.slerp(a, b, u);
    }

    /**
     * Weak translation hint only. Double integration is drift-prone, so each
     * integration step and accepted total are bounded before the core blends it.
     */
    synchronized Vec3 displacementHint(long fromNs, long toNs) {
        if (accelerationSize < 2 || toNs <= fromNs) {
            return Vec3.ZERO;
        }
        Vec3 velocity = Vec3.ZERO;
        Vec3 position = Vec3.ZERO;
        long last = fromNs;
        for (int i = accelerationSize - 1; i >= 0; i--) {
            int index = (accelerationHead - accelerationSize + i + CAPACITY) % CAPACITY;
            long timestamp = accelerationTimes[index];
            Vec3 acceleration = accelerations[index];
            if (timestamp < fromNs || timestamp > toNs || acceleration == null) {
                continue;
            }
            double dt = Math.min(0.03, Math.max(0.0, (timestamp - last) * 1e-9));
            velocity = velocity.add(acceleration.scale(dt));
            position = position.add(velocity.scale(dt));
            last = timestamp;
        }
        double dt = Math.min(0.03, Math.max(0.0, (toNs - last) * 1e-9));
        Vec3 result = position.add(velocity.scale(dt));
        return result.norm() <= 0.25 ? result : Vec3.ZERO;
    }

    boolean hasRotation() {
        return rotation != null;
    }
}
