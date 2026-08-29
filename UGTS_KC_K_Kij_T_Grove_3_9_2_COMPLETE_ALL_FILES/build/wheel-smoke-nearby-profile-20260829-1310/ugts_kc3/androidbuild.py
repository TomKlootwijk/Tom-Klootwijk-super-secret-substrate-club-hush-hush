"""Android toolchain discovery, APK compilation, and owner-device deployment.

The scene exporter intentionally remains usable without an Android SDK.  This
module is the optional second half of the workflow: it discovers a local SDK,
invokes the generated project's pinned Gradle wrapper, and can install a debug
or explicitly owner-signed build through ADB.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Mapping, Sequence


_VARIANTS: dict[str, tuple[str, str, str]] = {
    "poco-debug": ("pocoX7Pro", "debug", "assemblePocoX7ProDebug"),
    "poco-release": ("pocoX7Pro", "release", "assemblePocoX7ProRelease"),
    "universal-debug": ("universal", "debug", "assembleUniversalDebug"),
    "universal-release": ("universal", "release", "assembleUniversalRelease"),
}


@dataclass(frozen=True)
class AndroidDevice:
    serial: str
    state: str
    model: str = ""
    product: str = ""
    transport_id: str = ""

    @property
    def ready(self) -> bool:
        return self.state == "device"


@dataclass(frozen=True)
class AndroidToolchain:
    sdk_root: Path
    adb: Path
    gradle_command: tuple[str, ...]
    java: Path | None = None

    @classmethod
    def discover(cls, project_dir: str | Path) -> "AndroidToolchain":
        project_dir = Path(project_dir).resolve()
        sdk_root = _find_sdk_root()
        adb = _find_adb(sdk_root)
        gradle = _find_gradle_command(project_dir)
        java_path = shutil.which("java")
        return cls(sdk_root, adb, gradle, Path(java_path) if java_path else None)

    def environment(self) -> dict[str, str]:
        environment = dict(os.environ)
        environment["ANDROID_HOME"] = str(self.sdk_root)
        environment["ANDROID_SDK_ROOT"] = str(self.sdk_root)
        return environment


@dataclass(frozen=True)
class AndroidBuildResult:
    project_dir: Path
    variant: str
    task: str
    apk: Path
    output: str
    application_id: str = ""


@dataclass(frozen=True)
class AndroidInstallResult:
    apk: Path
    serial: str
    output: str


@dataclass(frozen=True)
class AndroidLaunchResult:
    application_id: str
    serial: str
    output: str


@dataclass(frozen=True)
class AndroidProfileResult:
    """Non-invasive SurfaceFlinger/memory/thermal snapshot of a running game."""

    application_id: str
    serial: str
    model: str
    requested_seconds: float
    samples: int
    frame_intervals: int
    display_period_ms: float
    effective_fps: float
    frame_ms_p50: float
    frame_ms_p95: float
    frame_ms_p99: float
    intervals_over_1_5_vsync: int
    pss_kib_min: int | None
    pss_kib_max: int | None
    rss_kib_min: int | None
    rss_kib_max: int | None
    gpu_c_min: float | None
    gpu_c_max: float | None
    battery_c_min: float | None
    battery_c_max: float | None
    battery_level_start: int | None
    battery_level_end: int | None
    thermal_status_max: int | None
    pid: int
    crash_buffer_lines: int | None
    summary: str
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "ugts-kc-android-profile-1",
            "application_id": self.application_id,
            "serial": self.serial,
            "model": self.model,
            "requested_seconds": self.requested_seconds,
            "samples": self.samples,
            "frame_intervals": self.frame_intervals,
            "display_period_ms": self.display_period_ms,
            "effective_fps": self.effective_fps,
            "frame_ms_p50": self.frame_ms_p50,
            "frame_ms_p95": self.frame_ms_p95,
            "frame_ms_p99": self.frame_ms_p99,
            "intervals_over_1_5_vsync": self.intervals_over_1_5_vsync,
            "pss_kib_min": self.pss_kib_min,
            "pss_kib_max": self.pss_kib_max,
            "rss_kib_min": self.rss_kib_min,
            "rss_kib_max": self.rss_kib_max,
            "gpu_c_min": self.gpu_c_min,
            "gpu_c_max": self.gpu_c_max,
            "battery_c_min": self.battery_c_min,
            "battery_c_max": self.battery_c_max,
            "battery_level_start": self.battery_level_start,
            "battery_level_end": self.battery_level_end,
            "thermal_status_max": self.thermal_status_max,
            "pid": self.pid,
            "crash_buffer_lines": self.crash_buffer_lines,
            "summary": self.summary,
            "warnings": list(self.warnings),
        }


def supported_variants() -> tuple[str, ...]:
    return tuple(_VARIANTS)


def _find_sdk_root() -> Path:
    candidates: list[Path] = []
    for name in ("ANDROID_SDK_ROOT", "ANDROID_HOME"):
        value = os.environ.get(name)
        if value:
            candidates.append(Path(value))
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "Android" / "Sdk")
    candidates.extend((
        Path.home() / "AppData" / "Local" / "Android" / "Sdk",
        Path.home() / "Android" / "Sdk",
        Path("/opt/android-sdk"),
    ))
    for candidate in candidates:
        candidate = candidate.expanduser()
        if candidate.is_dir() and (
            (candidate / "platform-tools").is_dir()
            or (candidate / "platforms").is_dir()
        ):
            return candidate.resolve()
    raise FileNotFoundError(
        "Android SDK not found; set ANDROID_SDK_ROOT or install it in the "
        "platform default location"
    )


def _find_adb(sdk_root: Path) -> Path:
    executable = "adb.exe" if os.name == "nt" else "adb"
    bundled = sdk_root / "platform-tools" / executable
    if bundled.is_file():
        return bundled.resolve()
    located = shutil.which("adb")
    if located:
        return Path(located).resolve()
    raise FileNotFoundError(f"ADB not found below {sdk_root}")


def _find_gradle_command(project_dir: Path) -> tuple[str, ...]:
    if os.name == "nt":
        wrapper = project_dir / "gradlew.bat"
        if wrapper.is_file():
            command_shell = os.environ.get("COMSPEC", "cmd.exe")
            return command_shell, "/d", "/c", str(wrapper)
    else:
        wrapper = project_dir / "gradlew"
        if wrapper.is_file():
            if os.access(wrapper, os.X_OK):
                return (str(wrapper),)
            shell = shutil.which("sh")
            if shell:
                # Wheel/sdist extraction does not reliably retain the executable
                # bit, but Gradle's wrapper is still a regular POSIX shell script.
                return (str(Path(shell).resolve()), str(wrapper))
    gradle = shutil.which("gradle")
    if gradle:
        return (str(Path(gradle).resolve()),)
    raise FileNotFoundError(
        f"no Gradle wrapper in {project_dir} and no system Gradle on PATH"
    )


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    timeout: float,
) -> str:
    completed = subprocess.run(
        list(command),
        cwd=cwd,
        env=dict(environment),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        tail = completed.stdout[-12000:]
        raise RuntimeError(
            f"command failed with exit code {completed.returncode}: "
            f"{' '.join(command)}\n{tail}"
        )
    return completed.stdout


def build_apk(
    project_dir: str | Path,
    variant: str = "poco-debug",
    *,
    clean: bool = False,
    timeout: float = 1800.0,
) -> AndroidBuildResult:
    """Compile one generated Android project variant and return its APK."""
    project_dir = Path(project_dir).resolve()
    if variant not in _VARIANTS:
        raise ValueError(
            f"unsupported Android variant {variant!r}; choose from "
            f"{', '.join(supported_variants())}"
        )
    if not (project_dir / "settings.gradle").is_file():
        raise FileNotFoundError(f"not an Android Gradle project: {project_dir}")
    flavor, build_type, task = _VARIANTS[variant]
    toolchain = AndroidToolchain.discover(project_dir)
    tasks = (["clean"] if clean else []) + [task, "--console=plain", "--stacktrace"]
    output = _run(
        (*toolchain.gradle_command, *tasks),
        cwd=project_dir,
        environment=toolchain.environment(),
        timeout=timeout,
    )
    output_dir = project_dir / "app" / "build" / "outputs" / "apk" / flavor / build_type
    apks = sorted(
        path for path in output_dir.glob("*.apk")
        if "androidtest" not in path.name.lower()
    )
    if not apks:
        raise FileNotFoundError(
            f"Gradle completed but produced no APK below {output_dir}"
        )
    metadata_path = output_dir / "output-metadata.json"
    if not metadata_path.is_file():
        # Older/external Gradle projects may not emit AGP output metadata. Keep
        # build-only compatibility; phone launch deliberately requires the
        # exact application id and will fail clearly before invoking ADB.
        return AndroidBuildResult(
            project_dir, variant, task, apks[-1], output, application_id=""
        )
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"could not read Android output metadata: {metadata_path}") from exc
    application_id = str(metadata.get("applicationId", ""))
    if not re.fullmatch(
        r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+",
        application_id,
    ):
        raise RuntimeError(
            f"Android output metadata has an invalid applicationId: {application_id!r}"
        )
    elements = metadata.get("elements")
    if not isinstance(elements, list) or not elements:
        raise RuntimeError(
            f"Android output metadata has no APK elements: {metadata_path}"
        )
    output_files = {
        str(element.get("outputFile", ""))
        for element in elements
        if isinstance(element, Mapping) and element.get("outputFile")
    }
    matching_apks = tuple(apk for apk in apks if apk.name in output_files)
    if not matching_apks:
        expected = ", ".join(sorted(output_files)) or "<none>"
        found = ", ".join(apk.name for apk in apks)
        raise RuntimeError(
            "Android output metadata does not match the APK files in the build "
            f"folder (expected: {expected}; found: {found})"
        )
    apk = matching_apks[-1]
    return AndroidBuildResult(
        project_dir, variant, task, apk, output, application_id=application_id
    )


def list_android_devices(
    toolchain: AndroidToolchain | None = None,
    *,
    project_dir: str | Path | None = None,
    timeout: float = 15.0,
) -> tuple[AndroidDevice, ...]:
    """Return attached ADB devices without treating unauthorized devices as ready."""
    if toolchain is None:
        if project_dir is None:
            sdk = _find_sdk_root()
            adb = _find_adb(sdk)
            gradle: tuple[str, ...] = ()
            toolchain = AndroidToolchain(sdk, adb, gradle)
        else:
            toolchain = AndroidToolchain.discover(project_dir)
    completed = subprocess.run(
        [str(toolchain.adb), "devices", "-l"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stdout.strip() or "adb devices failed")
    devices: list[AndroidDevice] = []
    for line in completed.stdout.splitlines()[1:]:
        line = line.strip()
        if not line or line.startswith("*"):
            continue
        fields = line.split()
        if len(fields) < 2:
            continue
        attributes = {
            key: value
            for field in fields[2:]
            if ":" in field
            for key, value in (field.split(":", 1),)
        }
        devices.append(AndroidDevice(
            serial=fields[0],
            state=fields[1],
            model=attributes.get("model", "").replace("_", " "),
            product=attributes.get("product", ""),
            transport_id=attributes.get("transport_id", ""),
        ))
    return tuple(devices)


def select_android_device(
    devices: Sequence[AndroidDevice] | None = None,
    *,
    serial: str | None = None,
) -> AndroidDevice:
    """Choose one authorized ADB device and explain common connection problems."""

    attached = tuple(list_android_devices() if devices is None else devices)
    if serial is not None:
        match = next((device for device in attached if device.serial == serial), None)
        if match is None:
            raise RuntimeError(f"ADB device is not connected: {serial}")
        if not match.ready:
            if match.state == "unauthorized":
                raise RuntimeError(
                    f"ADB device {serial} is waiting for USB-debugging authorization. "
                    "Unlock the phone and accept its Allow USB debugging prompt."
                )
            raise RuntimeError(f"ADB device {serial} is not ready (state: {match.state})")
        return match

    ready = tuple(device for device in attached if device.ready)
    if len(ready) == 1:
        return ready[0]
    if len(ready) > 1:
        labels = ", ".join(
            f"{device.model or 'Android device'} [{device.serial}]" for device in ready
        )
        raise RuntimeError(
            "More than one authorized Android device is connected. Disconnect the extra "
            f"device or deploy by serial. Ready devices: {labels}"
        )
    unauthorized = tuple(device for device in attached if device.state == "unauthorized")
    if unauthorized:
        labels = ", ".join(
            f"{device.model or 'Android phone'} [{device.serial}]" for device in unauthorized
        )
        raise RuntimeError(
            "The connected phone is waiting for USB-debugging authorization. Unlock it, "
            f"accept Allow USB debugging, and try Deploy again: {labels}"
        )
    if attached:
        states = ", ".join(f"{device.serial} ({device.state})" for device in attached)
        raise RuntimeError(
            "No connected Android device is ready for deployment. Reconnect USB and check "
            f"the phone's USB-debugging status: {states}"
        )
    raise RuntimeError(
        "No Android device was found. Connect the phone by USB, enable Developer options "
        "and USB debugging, then try Deploy again."
    )


def install_apk(
    apk: str | Path,
    *,
    serial: str | None = None,
    replace: bool = True,
    grant_permissions: bool = True,
    timeout: float = 180.0,
) -> AndroidInstallResult:
    """Install an APK on one explicitly selected, or the sole ready, ADB device."""
    apk = Path(apk).resolve()
    if not apk.is_file():
        raise FileNotFoundError(apk)
    sdk = _find_sdk_root()
    adb = _find_adb(sdk)
    toolchain = AndroidToolchain(sdk, adb, ())
    device = select_android_device(list_android_devices(toolchain), serial=serial)
    serial = device.serial
    command = [str(adb), "-s", serial, "install"]
    if replace:
        command.append("-r")
    if grant_permissions:
        command.append("-g")
    command.append(str(apk))
    output = _run(
        command,
        cwd=apk.parent,
        environment=os.environ,
        timeout=timeout,
    )
    if not re.search(r"(?m)^Success\s*$", output):
        raise RuntimeError(f"ADB did not report a successful install:\n{output}")
    return AndroidInstallResult(apk, serial, output)


def launch_android_app(
    application_id: str,
    *,
    serial: str | None = None,
    stop_existing: bool = True,
    timeout: float = 60.0,
) -> AndroidLaunchResult:
    """Open one installed native UGTS game on an explicitly selected phone."""

    if not re.fullmatch(
        r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+",
        application_id,
    ):
        raise ValueError(f"invalid Android application id: {application_id!r}")
    sdk = _find_sdk_root()
    adb = _find_adb(sdk)
    toolchain = AndroidToolchain(sdk, adb, ())
    device = select_android_device(list_android_devices(toolchain), serial=serial)
    component = f"{application_id}/android.app.NativeActivity"
    command = [
        str(adb), "-s", device.serial, "shell", "am", "start", "-W",
    ]
    if stop_existing:
        command.append("-S")
    command.extend(("--user", "current", "-n", component))
    output = _run(
        command,
        cwd=sdk,
        environment=os.environ,
        timeout=timeout,
    )
    if re.search(r"(?im)^\s*Error:", output) or not re.search(
        r"(?im)^\s*Status:\s*ok\s*$", output
    ):
        raise RuntimeError(
            "ADB installed the game, but Android did not confirm that it opened:\n"
            f"{output}"
        )
    return AndroidLaunchResult(application_id, device.serial, output)


def parse_surfaceflinger_latency(output: str) -> tuple[int, tuple[float, ...]]:
    """Parse one ``SurfaceFlinger --latency`` response into frame intervals.

    The first timestamp is used because it is the desired-presentation cadence
    exposed consistently by the tested Android 16 / Mali device. Pending rows
    and invalid sentinel timestamps are ignored.
    """

    lines = tuple(line.strip() for line in str(output).splitlines() if line.strip())
    if not lines:
        raise ValueError("SurfaceFlinger returned no frame timing data")
    try:
        period_ns = int(lines[0])
    except ValueError as exc:
        raise ValueError("SurfaceFlinger frame period is not a whole number") from exc
    if not 1_000_000 <= period_ns <= 1_000_000_000:
        raise ValueError(f"SurfaceFlinger frame period is invalid: {period_ns}")
    timestamps: list[int] = []
    for line in lines[1:]:
        fields = line.split()
        if len(fields) < 3:
            continue
        try:
            timestamp = int(fields[0])
        except ValueError:
            continue
        if 0 < timestamp < 9_000_000_000_000_000_000:
            timestamps.append(timestamp)
    intervals = tuple(
        delta_ms
        for before, after in zip(timestamps, timestamps[1:])
        if 0.0 < (delta_ms := (after - before) / 1_000_000.0) < 1_000.0
    )
    return period_ns, intervals


def _nearest_rank(values: Sequence[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * fraction) - 1))
    return ordered[index]


def _parse_meminfo(output: str) -> tuple[int, int] | None:
    match = re.search(
        r"TOTAL PSS:\s+(\d+).*?TOTAL RSS:\s+(\d+)",
        output,
        flags=re.DOTALL,
    )
    return None if match is None else (int(match.group(1)), int(match.group(2)))


def _parse_thermal(output: str) -> tuple[int | None, float | None]:
    status_match = re.search(r"Thermal Status:\s*(\d+)", output)
    status = None if status_match is None else int(status_match.group(1))
    current = output.split("Current temperatures from HAL:", 1)[-1]
    current = current.split("Current cooling devices from HAL:", 1)[0]
    gpu_match = re.search(
        r"Temperature\{mValue=([0-9]+(?:\.[0-9]+)?),\s*"
        r"mType=1,\s*mName=GPU",
        current,
    )
    gpu = None if gpu_match is None else float(gpu_match.group(1))
    return status, gpu


def _parse_battery(output: str) -> tuple[int | None, float | None]:
    level_match = re.search(r"(?m)^\s*level:\s*(\d+)\s*$", output)
    temperature_match = re.search(r"(?m)^\s*temperature:\s*(\d+)\s*$", output)
    level = None if level_match is None else int(level_match.group(1))
    temperature = (
        None if temperature_match is None else int(temperature_match.group(1)) / 10.0
    )
    return level, temperature


def _adb_text(
    adb: Path,
    serial: str,
    *arguments: str,
    timeout: float = 30.0,
) -> str:
    completed = subprocess.run(
        [str(adb), "-s", serial, *arguments],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        message = completed.stdout.strip() or "ADB profiling command failed"
        raise RuntimeError(message)
    return completed.stdout


def _optional_adb_text(
    adb: Path,
    serial: str,
    *arguments: str,
    timeout: float = 30.0,
) -> str:
    try:
        return _adb_text(adb, serial, *arguments, timeout=timeout)
    except (OSError, RuntimeError, subprocess.SubprocessError):
        return ""


def _surface_layer_candidates(output: str, application_id: str) -> tuple[str, ...]:
    expression = re.compile(
        rf"{re.escape(application_id)}/android\.app\.NativeActivity#(\d+)"
    )
    matches = {
        (int(match.group(1)), match.group(0))
        for match in expression.finditer(output)
    }
    return tuple(layer for _number, layer in sorted(matches, reverse=True))


def _discover_surface_layer(adb: Path, serial: str, application_id: str) -> str:
    listing = _adb_text(
        adb,
        serial,
        "shell",
        "dumpsys",
        "SurfaceFlinger",
        "--list",
    )
    candidates = _surface_layer_candidates(listing, application_id)
    for layer in candidates:
        latency = _optional_adb_text(
            adb,
            serial,
            "shell",
            "dumpsys",
            "SurfaceFlinger",
            "--latency",
            layer,
        )
        try:
            _period, intervals = parse_surfaceflinger_latency(latency)
        except ValueError:
            continue
        if intervals:
            return layer
    raise RuntimeError(
        "The game is installed, but Android exposes no active rendered surface. "
        "Open the game on the phone and keep its screen on, then try again."
    )


def profile_android_app(
    application_id: str,
    *,
    serial: str | None = None,
    seconds: float = 30.0,
    sample_seconds: float = 5.0,
) -> AndroidProfileResult:
    """Profile a running native game without injecting input or changing settings."""

    if not re.fullmatch(
        r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+",
        application_id,
    ):
        raise ValueError(f"invalid Android application id: {application_id!r}")
    seconds = float(seconds)
    sample_seconds = float(sample_seconds)
    if not 5.0 <= seconds <= 900.0:
        raise ValueError("profile duration must be between 5 and 900 seconds")
    if not 1.0 <= sample_seconds <= seconds:
        raise ValueError("profile sample interval must be between 1 second and the duration")

    sdk = _find_sdk_root()
    adb = _find_adb(sdk)
    toolchain = AndroidToolchain(sdk, adb, ())
    device = select_android_device(list_android_devices(toolchain), serial=serial)
    pid_text = _adb_text(adb, device.serial, "shell", "pidof", application_id).strip()
    if not re.fullmatch(r"\d+", pid_text):
        raise RuntimeError(
            "The game is not running on the selected phone. Open it, then try the profile again."
        )
    pid = int(pid_text)
    layer = _discover_surface_layer(adb, device.serial, application_id)

    intervals: list[float] = []
    periods: list[int] = []
    pss_values: list[int] = []
    rss_values: list[int] = []
    gpu_values: list[float] = []
    battery_temperatures: list[float] = []
    battery_levels: list[int] = []
    thermal_statuses: list[int] = []

    def snapshot() -> None:
        memory = _parse_meminfo(
            _optional_adb_text(
                adb, device.serial, "shell", "dumpsys", "meminfo", application_id
            )
        )
        if memory is not None:
            pss_values.append(memory[0])
            rss_values.append(memory[1])
        thermal_status, gpu = _parse_thermal(
            _optional_adb_text(
                adb, device.serial, "shell", "dumpsys", "thermalservice"
            )
        )
        if thermal_status is not None:
            thermal_statuses.append(thermal_status)
        if gpu is not None:
            gpu_values.append(gpu)
        battery_level, battery_temperature = _parse_battery(
            _optional_adb_text(adb, device.serial, "shell", "dumpsys", "battery")
        )
        if battery_level is not None:
            battery_levels.append(battery_level)
        if battery_temperature is not None:
            battery_temperatures.append(battery_temperature)

    snapshot()
    _adb_text(
        adb,
        device.serial,
        "shell",
        "dumpsys",
        "SurfaceFlinger",
        "--latency-clear",
    )
    sample_count = max(1, math.ceil(seconds / sample_seconds))
    remaining = seconds
    for _sample in range(sample_count):
        wait = min(sample_seconds, remaining)
        time.sleep(wait)
        remaining = max(0.0, remaining - wait)
        raw_latency = _adb_text(
            adb,
            device.serial,
            "shell",
            "dumpsys",
            "SurfaceFlinger",
            "--latency",
            layer,
        )
        period, sample_intervals = parse_surfaceflinger_latency(raw_latency)
        periods.append(period)
        intervals.extend(sample_intervals)
        _adb_text(
            adb,
            device.serial,
            "shell",
            "dumpsys",
            "SurfaceFlinger",
            "--latency-clear",
        )
        snapshot()

    final_pid = _adb_text(
        adb, device.serial, "shell", "pidof", application_id
    ).strip()
    if final_pid != pid_text:
        raise RuntimeError("The game restarted or stopped during the profile; no result was saved.")
    if not intervals or not periods:
        raise RuntimeError("Android returned no usable game frames during the profile.")
    period_ns = round(sum(periods) / len(periods))
    period_ms = period_ns / 1_000_000.0
    mean_ms = sum(intervals) / len(intervals)
    p95 = _nearest_rank(intervals, 0.95)
    missed = sum(value > period_ms * 1.5 for value in intervals)
    target_fps = 1000.0 / period_ms
    effective_fps = 1000.0 / mean_ms
    thermal_max = max(thermal_statuses, default=None)
    warnings: list[str] = []
    if effective_fps < target_fps * 0.95:
        warnings.append("Frame delivery stayed below 95% of the active display rate.")
    if p95 > period_ms * 1.5:
        warnings.append("The slowest five percent of frames missed the display cadence.")
    if thermal_max is not None and thermal_max >= 3:
        warnings.append("Android reported severe-or-higher thermal pressure.")
    if not pss_values:
        warnings.append("Android did not expose process memory totals.")
    crash_output = _optional_adb_text(
        adb,
        device.serial,
        "shell",
        "logcat",
        "-d",
        "-b",
        "crash",
        f"--pid={pid}",
        "*:V",
    )
    crash_lines = sum(
        bool(line.strip()) and not line.lstrip().startswith("---------")
        for line in crash_output.splitlines()
    )
    if crash_lines:
        warnings.append("Android's crash buffer contains lines for this running game.")
    summary = (
        f"Smooth {target_fps:.0f} Hz baseline"
        if not warnings
        else "Phone profile needs review"
    )
    return AndroidProfileResult(
        application_id=application_id,
        serial=device.serial,
        model=device.model,
        requested_seconds=seconds,
        samples=sample_count,
        frame_intervals=len(intervals),
        display_period_ms=round(period_ms, 4),
        effective_fps=round(effective_fps, 2),
        frame_ms_p50=round(_nearest_rank(intervals, 0.50), 3),
        frame_ms_p95=round(p95, 3),
        frame_ms_p99=round(_nearest_rank(intervals, 0.99), 3),
        intervals_over_1_5_vsync=missed,
        pss_kib_min=min(pss_values, default=None),
        pss_kib_max=max(pss_values, default=None),
        rss_kib_min=min(rss_values, default=None),
        rss_kib_max=max(rss_values, default=None),
        gpu_c_min=min(gpu_values, default=None),
        gpu_c_max=max(gpu_values, default=None),
        battery_c_min=min(battery_temperatures, default=None),
        battery_c_max=max(battery_temperatures, default=None),
        battery_level_start=battery_levels[0] if battery_levels else None,
        battery_level_end=battery_levels[-1] if battery_levels else None,
        thermal_status_max=thermal_max,
        pid=pid,
        crash_buffer_lines=crash_lines,
        summary=summary,
        warnings=tuple(warnings),
    )
