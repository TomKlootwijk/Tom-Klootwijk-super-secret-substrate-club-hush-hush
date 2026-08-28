#!/usr/bin/env python3
"""Compile the Android Java shell against a generated API-29-shaped stub surface.

This is a syntax/type-wiring gate, not a substitute for an Android SDK/AGP build.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SOURCES: dict[str, str] = {
"android/Manifest.java": r'''package android; public final class Manifest { public static final class permission { public static final String CAMERA="android.permission.CAMERA"; } }''',
"android/annotation/SuppressLint.java": r'''package android.annotation; import java.lang.annotation.*; @Retention(RetentionPolicy.CLASS) @Target({ElementType.TYPE,ElementType.METHOD,ElementType.CONSTRUCTOR,ElementType.FIELD}) public @interface SuppressLint { String[] value(); }''',
"android/util/DisplayMetrics.java": r'''package android.util; public class DisplayMetrics { public float density=1.0f; }''',
"android/util/Size.java": r'''package android.util; public final class Size { private final int w,h; public Size(int w,int h){this.w=w;this.h=h;} public int getWidth(){return w;} public int getHeight(){return h;} }''',
"android/util/SizeF.java": r'''package android.util; public final class SizeF { private final float w,h; public SizeF(float w,float h){this.w=w;this.h=h;} public float getWidth(){return w;} public float getHeight(){return h;} }''',
"android/content/res/Resources.java": r'''package android.content.res; import android.util.DisplayMetrics; public class Resources { public DisplayMetrics getDisplayMetrics(){return new DisplayMetrics();} }''',
"android/net/Uri.java": r'''package android.net; public class Uri {}''',
"android/content/pm/PackageManager.java": r'''package android.content.pm; public class PackageManager { public static final int PERMISSION_GRANTED=0; }''',
"android/content/DialogInterface.java": r'''package android.content; public interface DialogInterface { interface OnClickListener { void onClick(DialogInterface dialog,int which); } }''',
"android/content/ContentResolver.java": r'''package android.content; import android.net.Uri; import java.io.*; public class ContentResolver { public OutputStream openOutputStream(Uri u,String mode) throws FileNotFoundException { return new ByteArrayOutputStream(); } }''',
"android/content/Intent.java": r'''package android.content; import android.net.Uri; public class Intent { public static final String ACTION_CREATE_DOCUMENT="android.intent.action.CREATE_DOCUMENT"; public static final String CATEGORY_OPENABLE="android.intent.category.OPENABLE"; public static final String EXTRA_TITLE="android.intent.extra.TITLE"; private Uri data; public Intent(){} public Intent(String action){} public Intent addCategory(String c){return this;} public Intent setType(String t){return this;} public Intent putExtra(String k,String v){return this;} public Uri getData(){return data;} }''',
"android/content/Context.java": r'''package android.content; import android.content.res.Resources; import java.io.File; public class Context { public static final String CAMERA_SERVICE="camera"; public static final String SENSOR_SERVICE="sensor"; public static final String POWER_SERVICE="power"; public Object getSystemService(String s){return null;} public Context getApplicationContext(){return this;} public Resources getResources(){return new Resources();} public File getCacheDir(){return new File(".");} public ContentResolver getContentResolver(){return new ContentResolver();} }''',
"android/os/Bundle.java": r'''package android.os; public class Bundle {}''',
"android/os/SystemClock.java": r'''package android.os; public final class SystemClock { public static long elapsedRealtimeNanos(){return System.nanoTime();} }''',
"android/os/Looper.java": r'''package android.os; public class Looper {}''',
"android/os/Handler.java": r'''package android.os; public class Handler { public Handler(){} public Handler(Looper l){} public boolean post(Runnable r){r.run();return true;} }''',
"android/os/HandlerThread.java": r'''package android.os; public class HandlerThread extends Thread { public HandlerThread(String n){super(n);} public Looper getLooper(){return new Looper();} public boolean quitSafely(){return true;} }''',
"android/os/PowerManager.java": r'''package android.os; import java.util.concurrent.Executor; public class PowerManager { public static final int THERMAL_STATUS_NONE=0,THERMAL_STATUS_MODERATE=2,THERMAL_STATUS_SEVERE=3; public interface OnThermalStatusChangedListener { void onThermalStatusChanged(int status); } public int getCurrentThermalStatus(){return 0;} public void addThermalStatusListener(Executor e,OnThermalStatusChangedListener l){} public void removeThermalStatusListener(OnThermalStatusChangedListener l){} }''',
"android/text/InputType.java": r'''package android.text; public final class InputType { public static final int TYPE_CLASS_NUMBER=2,TYPE_NUMBER_FLAG_DECIMAL=8192; }''',
"android/graphics/Color.java": r'''package android.graphics; public final class Color { public static final int WHITE=-1,BLACK=0xff000000; public static int argb(int a,int r,int g,int b){return 0;} }''',
"android/graphics/ImageFormat.java": r'''package android.graphics; public final class ImageFormat { public static final int YUV_420_888=35; }''',
"android/graphics/Rect.java": r'''package android.graphics; public class Rect { public int left,top,right,bottom; public int width(){return right-left;} public int height(){return bottom-top;} }''',
"android/graphics/RectF.java": r'''package android.graphics; public class RectF { public float left,top,right,bottom; public RectF(){} public RectF(float l,float t,float r,float b){left=l;top=t;right=r;bottom=b;} public float centerX(){return (left+right)/2;} public float centerY(){return (top+bottom)/2;} public void offset(float x,float y){left+=x;right+=x;top+=y;bottom+=y;} }''',
"android/graphics/Matrix.java": r'''package android.graphics; public class Matrix { public enum ScaleToFit { FILL } public boolean setRectToRect(RectF a,RectF b,ScaleToFit f){return true;} public boolean postScale(float x,float y,float px,float py){return true;} public boolean postRotate(float d,float px,float py){return true;} }''',
"android/graphics/SurfaceTexture.java": r'''package android.graphics; public class SurfaceTexture { public void setDefaultBufferSize(int w,int h){} }''',
"android/graphics/Paint.java": r'''package android.graphics; public class Paint { public static final int ANTI_ALIAS_FLAG=1; public enum Style { STROKE,FILL } public Paint(){} public Paint(int f){} public void setColor(int c){} public void setStyle(Style s){} public void setStrokeWidth(float w){} public void setTextSize(float s){} }''',
"android/graphics/Canvas.java": r'''package android.graphics; public class Canvas { public void drawCircle(float x,float y,float r,Paint p){} public void drawRoundRect(RectF r,float rx,float ry,Paint p){} public void drawText(String s,float x,float y,Paint p){} public void drawPoint(float x,float y,Paint p){} public void drawLine(float x1,float y1,float x2,float y2,Paint p){} }''',
"android/view/Display.java": r'''package android.view; public class Display { public int getRotation(){return 0;} }''',
"android/view/WindowManager.java": r'''package android.view; public interface WindowManager { class LayoutParams { public static final int FLAG_KEEP_SCREEN_ON=128; } Display getDefaultDisplay(); }''',
"android/view/Window.java": r'''package android.view; public class Window { public void addFlags(int f){} }''',
"android/view/Gravity.java": r'''package android.view; public final class Gravity { public static final int CENTER=17,TOP=48,BOTTOM=80; }''',
"android/view/Surface.java": r'''package android.view; import android.graphics.SurfaceTexture; public class Surface implements AutoCloseable { public static final int ROTATION_0=0,ROTATION_90=1,ROTATION_180=2,ROTATION_270=3; public Surface(SurfaceTexture t){} public void close(){} }''',
"android/view/View.java": r'''package android.view; import android.content.Context; import android.content.res.Resources; import android.graphics.Canvas; public class View { public interface OnClickListener { void onClick(View v); } private final Context c; public View(Context c){this.c=c;} public void setOnClickListener(OnClickListener l){} public void setBackgroundColor(int c){} public Resources getResources(){return c.getResources();} public void setWillNotDraw(boolean b){} public void postInvalidateOnAnimation(){} public int getWidth(){return 1080;} public int getHeight(){return 1920;} protected void onDraw(Canvas c){} }''',
"android/view/TextureView.java": r'''package android.view; import android.content.Context; import android.graphics.Matrix; import android.graphics.SurfaceTexture; public class TextureView extends View { public interface SurfaceTextureListener { void onSurfaceTextureAvailable(SurfaceTexture s,int w,int h); void onSurfaceTextureSizeChanged(SurfaceTexture s,int w,int h); boolean onSurfaceTextureDestroyed(SurfaceTexture s); void onSurfaceTextureUpdated(SurfaceTexture s); } public TextureView(Context c){super(c);} public void setSurfaceTextureListener(SurfaceTextureListener l){} public boolean isAvailable(){return true;} public SurfaceTexture getSurfaceTexture(){return new SurfaceTexture();} public void setTransform(Matrix m){} }''',
"android/widget/TextView.java": r'''package android.widget; import android.content.Context; import android.view.View; public class TextView extends View { public TextView(Context c){super(c);} public void setText(CharSequence s){} public void setTextColor(int c){} public void setBackgroundColor(int c){} public void setGravity(int g){} public void setTextSize(float s){} public void setPadding(int a,int b,int c,int d){} }''',
"android/widget/Button.java": r'''package android.widget; import android.content.Context; public class Button extends TextView { public Button(Context c){super(c);} public void setAllCaps(boolean b){} public void setEnabled(boolean b){} }''',
"android/widget/EditText.java": r'''package android.widget; import android.content.Context; public class EditText extends TextView { public EditText(Context c){super(c);} public void setInputType(int t){} public void setHint(CharSequence s){} public CharSequence getText(){return "";} }''',
"android/widget/FrameLayout.java": r'''package android.widget; import android.content.Context; import android.view.View; public class FrameLayout extends View { public static class LayoutParams { public int gravity,topMargin; public LayoutParams(int w,int h){} } public FrameLayout(Context c){super(c);} public void addView(View v,LayoutParams p){} }''',
"android/widget/LinearLayout.java": r'''package android.widget; import android.content.Context; import android.view.View; public class LinearLayout extends View { public static final int VERTICAL=1; public static class LayoutParams { public LayoutParams(int w,int h,float weight){} } public LinearLayout(Context c){super(c);} public void setOrientation(int o){} public void setPadding(int a,int b,int c,int d){} public void setBackgroundColor(int c){} public void setGravity(int g){} public void addView(View v){} public void addView(View v,LayoutParams p){} }''',
"android/widget/Toast.java": r'''package android.widget; import android.content.Context; public class Toast { public static final int LENGTH_SHORT=0,LENGTH_LONG=1; public static Toast makeText(Context c,CharSequence s,int d){return new Toast();} public void show(){} }''',
"android/app/AlertDialog.java": r'''package android.app; import android.content.Context; import android.content.DialogInterface; import android.view.View; public class AlertDialog { public static class Builder { public Builder(Context c){} public Builder setTitle(CharSequence s){return this;} public Builder setMessage(CharSequence s){return this;} public Builder setView(View v){return this;} public Builder setNegativeButton(CharSequence s,DialogInterface.OnClickListener l){return this;} public Builder setPositiveButton(CharSequence s,DialogInterface.OnClickListener l){return this;} public AlertDialog show(){return new AlertDialog();} } }''',
"android/app/Activity.java": r'''package android.app; import android.content.*; import android.content.pm.PackageManager; import android.os.Bundle; import android.view.*; import java.util.concurrent.Executor; public class Activity extends Context { public static final int RESULT_OK=-1; protected void onCreate(Bundle b){} protected void onResume(){} protected void onPause(){} protected void onDestroy(){} protected void onActivityResult(int r,int c,Intent d){} public void onRequestPermissionsResult(int r,String[] p,int[] g){} public Window getWindow(){return new Window();} public WindowManager getWindowManager(){return new WindowManager(){public Display getDefaultDisplay(){return new Display();}};} public void setContentView(View v){} public int checkSelfPermission(String p){return PackageManager.PERMISSION_GRANTED;} public void requestPermissions(String[] p,int r){} public void runOnUiThread(Runnable r){r.run();} public Executor getMainExecutor(){return Runnable::run;} public void startActivityForResult(Intent i,int r){} }''',
"android/hardware/Sensor.java": r'''package android.hardware; public class Sensor { public static final int TYPE_GAME_ROTATION_VECTOR=15,TYPE_ROTATION_VECTOR=11,TYPE_LINEAR_ACCELERATION=10; public int getType(){return 0;} }''',
"android/hardware/SensorEvent.java": r'''package android.hardware; public class SensorEvent { public Sensor sensor; public long timestamp; public float[] values; }''',
"android/hardware/SensorEventListener.java": r'''package android.hardware; public interface SensorEventListener { void onSensorChanged(SensorEvent e); void onAccuracyChanged(Sensor s,int a); }''',
"android/hardware/SensorManager.java": r'''package android.hardware; import android.os.Handler; public class SensorManager { public static final int SENSOR_DELAY_GAME=1; public Sensor getDefaultSensor(int t){return null;} public boolean registerListener(SensorEventListener l,Sensor s,int d,Handler h){return true;} public void unregisterListener(SensorEventListener l){} public static void getQuaternionFromVector(float[] q,float[] v){} }''',
"android/media/Image.java": r'''package android.media; import java.nio.ByteBuffer; public abstract class Image implements AutoCloseable { public abstract int getWidth(); public abstract int getHeight(); public abstract long getTimestamp(); public abstract Plane[] getPlanes(); public abstract void close(); public abstract static class Plane { public abstract ByteBuffer getBuffer(); public abstract int getRowStride(); public abstract int getPixelStride(); } }''',
"android/media/ImageReader.java": r'''package android.media; import android.os.Handler; import android.view.Surface; public class ImageReader implements AutoCloseable { public interface OnImageAvailableListener { void onImageAvailable(ImageReader r); } public static ImageReader newInstance(int w,int h,int format,int max){return new ImageReader();} public void setOnImageAvailableListener(OnImageAvailableListener l,Handler h){} public Image acquireLatestImage(){return null;} public Surface getSurface(){return null;} public void close(){} }''',
"android/hardware/camera2/CameraAccessException.java": r'''package android.hardware.camera2; public class CameraAccessException extends Exception { public CameraAccessException(int r){super();} }''',
"android/hardware/camera2/CaptureRequest.java": r'''package android.hardware.camera2; import android.view.Surface; public class CaptureRequest { public static final int CONTROL_AF_MODE_CONTINUOUS_VIDEO=3,CONTROL_AE_MODE_ON=1,CONTROL_AWB_MODE_AUTO=1; public static final Key<Integer> CONTROL_AF_MODE=new Key<>(),CONTROL_AE_MODE=new Key<>(),CONTROL_AWB_MODE=new Key<>(); public static class Key<T>{} public static class Builder { public void addTarget(Surface s){} public <T> void set(Key<T> k,T v){} public CaptureRequest build(){return new CaptureRequest();} } }''',
"android/hardware/camera2/CameraCharacteristics.java": r'''package android.hardware.camera2; import android.graphics.Rect; import android.hardware.camera2.params.StreamConfigurationMap; import android.util.SizeF; public class CameraCharacteristics { public static final int LENS_FACING_BACK=1; public static final Key<Integer> LENS_FACING=new Key<>(),SENSOR_ORIENTATION=new Key<>(); public static final Key<StreamConfigurationMap> SCALER_STREAM_CONFIGURATION_MAP=new Key<>(); public static final Key<float[]> LENS_INFO_AVAILABLE_FOCAL_LENGTHS=new Key<>(),LENS_INTRINSIC_CALIBRATION=new Key<>(); public static final Key<SizeF> SENSOR_INFO_PHYSICAL_SIZE=new Key<>(); public static final Key<Rect> SENSOR_INFO_ACTIVE_ARRAY_SIZE=new Key<>(); public <T> T get(Key<T> k){return null;} public static class Key<T>{} }''',
"android/hardware/camera2/CameraManager.java": r'''package android.hardware.camera2; import android.os.Handler; public class CameraManager { public String[] getCameraIdList() throws CameraAccessException {return new String[0];} public CameraCharacteristics getCameraCharacteristics(String id) throws CameraAccessException {return new CameraCharacteristics();} public void openCamera(String id,CameraDevice.StateCallback c,Handler h) throws CameraAccessException {} }''',
"android/hardware/camera2/CameraDevice.java": r'''package android.hardware.camera2; import android.os.Handler; import android.view.Surface; import java.util.List; public abstract class CameraDevice implements AutoCloseable { public static final int TEMPLATE_PREVIEW=1; public abstract CaptureRequest.Builder createCaptureRequest(int t) throws CameraAccessException; public abstract void createCaptureSession(List<Surface> s,CameraCaptureSession.StateCallback c,Handler h) throws CameraAccessException; public abstract void close(); public abstract static class StateCallback { public abstract void onOpened(CameraDevice c); public abstract void onDisconnected(CameraDevice c); public abstract void onError(CameraDevice c,int e); } }''',
"android/hardware/camera2/CameraCaptureSession.java": r'''package android.hardware.camera2; import android.os.Handler; public abstract class CameraCaptureSession implements AutoCloseable { public abstract void setRepeatingRequest(CaptureRequest r,Object cb,Handler h) throws CameraAccessException; public abstract void stopRepeating() throws CameraAccessException; public abstract void close(); public abstract static class StateCallback { public abstract void onConfigured(CameraCaptureSession s); public abstract void onConfigureFailed(CameraCaptureSession s); } }''',
"android/hardware/camera2/params/StreamConfigurationMap.java": r'''package android.hardware.camera2.params; import android.util.Size; public class StreamConfigurationMap { public Size[] getOutputSizes(int f){return new Size[0];} public Size[] getOutputSizes(Class<?> c){return new Size[0];} }''',
}


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=False)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ugts_android_stub_") as temporary:
        temp = Path(temporary)
        stub_src = temp / "stub-src"
        stub_classes = temp / "stub-classes"
        core_classes = temp / "core-classes"
        app_classes = temp / "app-classes"
        for relative, source in SOURCES.items():
            path = stub_src / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source + "\n", encoding="utf-8")
        stub_classes.mkdir()
        core_classes.mkdir()
        app_classes.mkdir()
        result = run([
            "javac", "--release", "17", "-encoding", "UTF-8", "-d", str(stub_classes),
            *map(str, sorted(stub_src.rglob("*.java"))),
        ])
        if result.returncode:
            print(result.stdout + result.stderr)
            return result.returncode
        result = run([
            "javac", "--release", "17", "-encoding", "UTF-8", "-d", str(core_classes),
            *map(str, sorted((ROOT / "core/src/main/java").rglob("*.java"))),
        ])
        if result.returncode:
            print(result.stdout + result.stderr)
            return result.returncode
        classpath = f"{stub_classes}:{core_classes}"
        result = run([
            "javac", "--release", "17", "-encoding", "UTF-8", "-Xlint:all", "-Xlint:-deprecation",
            "-cp", classpath, "-d", str(app_classes),
            *map(str, sorted((ROOT / "app/src/main/java").rglob("*.java"))),
        ])
        if result.returncode:
            print(result.stdout + result.stderr)
            return result.returncode
        class_count = len(list(app_classes.rglob("*.class")))
        print(f"Android shell stub compile: PASS ({class_count} class files)")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
