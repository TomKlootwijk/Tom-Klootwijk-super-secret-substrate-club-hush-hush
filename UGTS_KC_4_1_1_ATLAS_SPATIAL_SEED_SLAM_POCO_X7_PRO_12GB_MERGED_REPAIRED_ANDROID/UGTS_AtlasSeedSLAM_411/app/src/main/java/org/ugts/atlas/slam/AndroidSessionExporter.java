package org.ugts.atlas.slam;

import android.content.Context;
import android.os.SystemClock;
import android.util.Log;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import org.ugts.atlas.slam.core.KSeedWriter;
import org.ugts.atlas.slam.core.SessionData;

/** Writes the default KSEED 4.1 evidence stream into private cache storage. */
final class AndroidSessionExporter {
    private AndroidSessionExporter() {}

    static File exportKSeed(Context context, SessionData data) throws Exception {
        long startedNs = SystemClock.elapsedRealtimeNanos();
        File base = new File(context.getCacheDir(), "ugts_exports");
        if (!base.exists() && !base.mkdirs()) {
            throw new IOException("cannot create private export directory");
        }
        File output = new File(base, fileName(data));
        try (FileOutputStream stream = new FileOutputStream(output)) {
            new KSeedWriter().write(stream, data);
            stream.getFD().sync();
        }
        Log.i("UGTS_PERF", "source=kseed_export bytes=" + output.length()
                + " durationMs="
                + String.format(java.util.Locale.ROOT, "%.3f",
                        (SystemClock.elapsedRealtimeNanos() - startedNs) / 1_000_000.0));
        return output;
    }

    static String fileName(SessionData data) {
        return safe(data.sessionId) + ".kseed";
    }

    private static String safe(String value) {
        String result = value == null
                ? "session"
                : value.replaceAll("[^A-Za-z0-9._-]", "_");
        return result.isEmpty() ? "session" : result;
    }
}
