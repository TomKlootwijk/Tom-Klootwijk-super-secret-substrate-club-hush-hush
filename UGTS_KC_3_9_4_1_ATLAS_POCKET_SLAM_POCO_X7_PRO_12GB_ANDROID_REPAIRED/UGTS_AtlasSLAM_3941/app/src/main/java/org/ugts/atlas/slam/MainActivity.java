package org.ugts.atlas.slam;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.os.SystemClock;
import android.text.InputType;
import android.view.Gravity;
import android.view.TextureView;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;
import java.io.File;
import java.io.FileInputStream;
import java.io.OutputStream;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.ugts.atlas.slam.core.SessionData;
import org.ugts.atlas.slam.core.SlamConfig;
import org.ugts.atlas.slam.core.SlamEngine;
import org.ugts.atlas.slam.core.SlamSnapshot;
import org.ugts.atlas.slam.core.Vec3;

/**
 * Native, offline, dependency-minimal POCO X7 Pro capture shell. Camera/IMU
 * observations remain proposals; the platform-independent core owns commits.
 */
public final class MainActivity extends Activity
        implements FrameAnalyzer.Listener, Camera2Controller.Listener {
    private static final int CAMERA_REQUEST = 394;
    private static final int CREATE_SCAN_REQUEST = 395;

    private final ExecutorService exportExecutor = Executors.newSingleThreadExecutor(
            runnable -> new Thread(runnable, "ugts-export"));
    private TextureView preview;
    private ScanOverlayView overlay;
    private TextView status;
    private TextView banner;
    private Button start;
    private Button pause;
    private Button finish;
    private Button scale;
    private Button export;
    private SensorFusion sensors;
    private ThermalGovernor thermal;
    private SlamEngine engine;
    private FrameAnalyzer frameAnalyzer;
    private Camera2Controller camera;
    private Vec3 scaleStart;
    private File pendingExport;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        engine = new SlamEngine(SlamConfig.pocoX7Pro12Gb());
        sensors = new SensorFusion(this);
        thermal = new ThermalGovernor(this, getMainExecutor());
        frameAnalyzer = new FrameAnalyzer(this, engine, sensors, thermal, this);
        buildUi();
        camera = new Camera2Controller(this, preview, frameAnalyzer, this);
        if (checkSelfPermission(Manifest.permission.CAMERA)
                == PackageManager.PERMISSION_GRANTED) {
            startCaptureDevices();
        } else {
            requestPermissions(new String[] {Manifest.permission.CAMERA}, CAMERA_REQUEST);
        }
    }

    private void buildUi() {
        float density = getResources().getDisplayMetrics().density;
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.BLACK);
        preview = new TextureView(this);
        root.addView(preview, new FrameLayout.LayoutParams(-1, -1));
        overlay = new ScanOverlayView(this);
        root.addView(overlay, new FrameLayout.LayoutParams(-1, -1));

        banner = new TextView(this);
        banner.setText("MONOCULAR · RELATIVE SCALE UNTIL ANCHORED");
        banner.setTextColor(Color.WHITE);
        banner.setBackgroundColor(Color.argb(205, 110, 42, 22));
        banner.setGravity(Gravity.CENTER);
        banner.setTextSize(12);
        FrameLayout.LayoutParams bannerParams =
                new FrameLayout.LayoutParams(-1, (int) (42 * density));
        bannerParams.gravity = Gravity.TOP;
        root.addView(banner, bannerParams);

        status = new TextView(this);
        status.setTextColor(Color.WHITE);
        status.setTextSize(13);
        status.setPadding(
                (int) (12 * density),
                (int) (8 * density),
                (int) (12 * density),
                (int) (8 * density));
        status.setBackgroundColor(Color.argb(180, 7, 15, 22));
        status.setText("Ready · offline · no network permission");
        FrameLayout.LayoutParams statusParams = new FrameLayout.LayoutParams(-1, -2);
        statusParams.gravity = Gravity.TOP;
        statusParams.topMargin = (int) (42 * density);
        root.addView(status, statusParams);

        LinearLayout controls = new LinearLayout(this);
        controls.setOrientation(LinearLayout.VERTICAL);
        controls.setPadding(
                (int) (6 * density),
                (int) (4 * density),
                (int) (6 * density),
                (int) (8 * density));
        controls.setBackgroundColor(Color.argb(220, 10, 18, 25));
        LinearLayout firstRow = new LinearLayout(this);
        LinearLayout secondRow = new LinearLayout(this);
        firstRow.setGravity(Gravity.CENTER);
        secondRow.setGravity(Gravity.CENTER);
        start = button("Start");
        pause = button("Pause");
        finish = button("Finish");
        scale = button("Scale anchor");
        export = button("Export compact");
        add(firstRow, start);
        add(firstRow, pause);
        add(firstRow, finish);
        add(secondRow, scale);
        add(secondRow, export);
        controls.addView(firstRow);
        controls.addView(secondRow);
        FrameLayout.LayoutParams controlsParams = new FrameLayout.LayoutParams(-1, -2);
        controlsParams.gravity = Gravity.BOTTOM;
        root.addView(controls, controlsParams);
        setContentView(root);

        start.setOnClickListener(view -> beginOrResume());
        pause.setOnClickListener(view -> {
            engine.pause(SystemClock.elapsedRealtimeNanos());
            status.setText("Paused · preview remains local");
        });
        finish.setOnClickListener(view -> {
            engine.finish(SystemClock.elapsedRealtimeNanos());
            status.setText("Finished · ready to export");
        });
        scale.setOnClickListener(view -> scaleAction());
        export.setOnClickListener(view -> exportAction());
    }

    private Button button(String label) {
        Button value = new Button(this);
        value.setText(label);
        value.setAllCaps(false);
        value.setTextSize(12);
        return value;
    }

    private void add(LinearLayout row, View child) {
        row.addView(child, new LinearLayout.LayoutParams(0, -2, 1));
    }

    private void startCaptureDevices() {
        sensors.start();
        camera.start();
    }

    private void beginOrResume() {
        long now = SystemClock.elapsedRealtimeNanos();
        if (engine.state() == SlamEngine.State.IDLE
                || engine.state() == SlamEngine.State.FINISHED) {
            String id = "atlas3941_"
                    + new SimpleDateFormat("yyyyMMdd_HHmmss", Locale.ROOT).format(new Date());
            engine.start(id, now);
            scaleStart = null;
            banner.setText("RELATIVE SCALE · USE A KNOWN-DISTANCE ANCHOR");
            banner.setBackgroundColor(Color.argb(205, 110, 42, 22));
        } else {
            engine.resume(now);
        }
        status.setText("Scanning · translate slowly · retain textured overlap");
    }

    @Override
    public void onRequestPermissionsResult(
            int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == CAMERA_REQUEST
                && grantResults.length > 0
                && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            startCaptureDevices();
        } else if (requestCode == CAMERA_REQUEST) {
            status.setText("Camera permission is required for scanning");
        }
    }

    @Override
    public void onCameraReady(String description) {
        runOnUiThread(() -> status.setText(description + " · press Start"));
    }

    @Override
    public void onCameraError(Throwable error) {
        onError(error);
    }

    @Override
    public void onSnapshot(SlamSnapshot snapshot, String thermalLabel) {
        runOnUiThread(() -> {
            overlay.setSnapshot(snapshot);
            String scaleLabel = "metric_anchor".equals(snapshot.scaleState)
                    ? String.format(Locale.ROOT, "metric × %.4g", snapshot.metricScale)
                    : "relative/unanchored";
            status.setText(String.format(
                    Locale.ROOT,
                    "%s · frame %d · KF %d · %d voxels · Q %.2f · %s",
                    thermalLabel,
                    snapshot.frameId,
                    snapshot.keyframeCount,
                    snapshot.mapPointCount,
                    snapshot.trackingQuality,
                    scaleLabel));
            if ("metric_anchor".equals(snapshot.scaleState)) {
                banner.setText("METRIC ANCHOR ACTIVE · VERIFY WITH A SECOND CONTROL");
                banner.setBackgroundColor(Color.argb(205, 14, 92, 74));
            }
        });
    }

    @Override
    public void onError(Throwable error) {
        runOnUiThread(() -> status.setText(
                "Capture error: " + error.getClass().getSimpleName()
                        + " · " + String.valueOf(error.getMessage())));
    }

    private void scaleAction() {
        if (engine.state() != SlamEngine.State.SCANNING
                && engine.state() != SlamEngine.State.PAUSED) {
            Toast.makeText(this, "Start a scan first", Toast.LENGTH_SHORT).show();
            return;
        }
        if (scaleStart == null) {
            scaleStart = engine.currentPosition();
            scale.setText("Finish anchor");
            Toast.makeText(
                    this,
                    "Move the camera a measured straight-line distance, then tap Finish anchor",
                    Toast.LENGTH_LONG).show();
            return;
        }
        Vec3 end = engine.currentPosition();
        EditText input = new EditText(this);
        input.setInputType(
                InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_DECIMAL);
        input.setHint("Known distance in metres");
        new AlertDialog.Builder(this)
                .setTitle("Metric scale anchor")
                .setMessage(
                        "Enter measured camera displacement. This sets scale only; it does not "
                                + "remove monocular drift. Verify against another control length.")
                .setView(input)
                .setNegativeButton("Cancel", (dialog, which) -> resetScaleButton())
                .setPositiveButton("Apply", (dialog, which) -> {
                    try {
                        double metres = Double.parseDouble(input.getText().toString());
                        boolean accepted = engine.applyKnownDistanceAnchor(
                                scaleStart,
                                end,
                                metres,
                                SystemClock.elapsedRealtimeNanos());
                        Toast.makeText(
                                this,
                                accepted ? "Metric anchor applied" : "Anchor rejected",
                                Toast.LENGTH_LONG).show();
                    } catch (Exception ignored) {
                        Toast.makeText(this, "Invalid distance", Toast.LENGTH_SHORT).show();
                    } finally {
                        resetScaleButton();
                    }
                })
                .show();
    }

    private void resetScaleButton() {
        scaleStart = null;
        scale.setText("Scale anchor");
    }

    private void exportAction() {
        if (engine.state() == SlamEngine.State.IDLE) {
            Toast.makeText(this, "No scan session exists", Toast.LENGTH_SHORT).show();
            return;
        }
        engine.finish(SystemClock.elapsedRealtimeNanos());
        SessionData data = engine.sessionData();
        export.setEnabled(false);
        status.setText("Encoding compact scan…");
        exportExecutor.execute(() -> {
            try {
                File file = AndroidSessionExporter.exportCompact(this, data);
                pendingExport = file;
                runOnUiThread(() -> chooseExportDestination(file));
            } catch (Exception error) {
                runOnUiThread(() -> {
                    export.setEnabled(true);
                    onError(error);
                });
            }
        });
    }

    private void chooseExportDestination(File file) {
        Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("application/zip");
        intent.putExtra(Intent.EXTRA_TITLE, file.getName());
        startActivityForResult(intent, CREATE_SCAN_REQUEST);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != CREATE_SCAN_REQUEST) {
            return;
        }
        if (resultCode != RESULT_OK || data == null || data.getData() == null
                || pendingExport == null) {
            export.setEnabled(true);
            status.setText("Export cancelled; private temporary copy will be cleaned by Android");
            return;
        }
        Uri destination = data.getData();
        File source = pendingExport;
        status.setText("Writing selected document…");
        exportExecutor.execute(() -> {
            try (FileInputStream input = new FileInputStream(source);
                    OutputStream output = getContentResolver().openOutputStream(destination, "w")) {
                if (output == null) {
                    throw new IllegalStateException("Document provider returned no output stream");
                }
                byte[] buffer = new byte[64 * 1024];
                int count;
                while ((count = input.read(buffer)) != -1) {
                    output.write(buffer, 0, count);
                }
                output.flush();
                runOnUiThread(() -> {
                    export.setEnabled(true);
                    status.setText("Exported " + source.getName() + " · " + human(source.length()));
                    Toast.makeText(this, "Compact scan saved", Toast.LENGTH_LONG).show();
                });
            } catch (Exception error) {
                runOnUiThread(() -> {
                    export.setEnabled(true);
                    onError(error);
                });
            }
        });
    }

    private static String human(long bytes) {
        if (bytes < 1024) {
            return bytes + " B";
        }
        if (bytes < 1024 * 1024) {
            return String.format(Locale.ROOT, "%.1f KiB", bytes / 1024.0);
        }
        return String.format(Locale.ROOT, "%.1f MiB", bytes / 1048576.0);
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (camera != null
                && checkSelfPermission(Manifest.permission.CAMERA)
                        == PackageManager.PERMISSION_GRANTED) {
            sensors.start();
            camera.start();
        }
    }

    @Override
    protected void onPause() {
        if (camera != null) {
            camera.stop();
        }
        sensors.stop();
        super.onPause();
    }

    @Override
    protected void onDestroy() {
        if (camera != null) {
            camera.stop();
        }
        sensors.close();
        thermal.close();
        exportExecutor.shutdownNow();
        super.onDestroy();
    }
}
