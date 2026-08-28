package org.ugts.atlas.slam;

import android.content.Context;
import android.os.PowerManager;
import java.util.concurrent.Executor;

/** Reduces analysis rate before severe thermal throttling or UI collapse. */
final class ThermalGovernor implements AutoCloseable {
    private volatile int status = PowerManager.THERMAL_STATUS_NONE;
    private final PowerManager power;
    private final PowerManager.OnThermalStatusChangedListener listener;

    ThermalGovernor(Context context, Executor executor) {
        power = (PowerManager) context.getSystemService(Context.POWER_SERVICE);
        listener = value -> status = value;
        if (power != null) {
            status = power.getCurrentThermalStatus();
            power.addThermalStatusListener(executor, listener);
        }
    }

    long minimumFrameIntervalNs() {
        if (status >= PowerManager.THERMAL_STATUS_SEVERE) {
            return 166_000_000L;
        }
        if (status >= PowerManager.THERMAL_STATUS_MODERATE) {
            return 100_000_000L;
        }
        return 66_000_000L;
    }

    String label() {
        if (status >= PowerManager.THERMAL_STATUS_SEVERE) {
            return "hot/6 fps";
        }
        if (status >= PowerManager.THERMAL_STATUS_MODERATE) {
            return "warm/10 fps";
        }
        return "normal/15 fps";
    }

    @Override
    public void close() {
        if (power != null) {
            power.removeThermalStatusListener(listener);
        }
    }
}
