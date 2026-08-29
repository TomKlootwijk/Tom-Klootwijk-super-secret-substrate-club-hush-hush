"""Android toolchain discovery, APK compilation, and owner-device deployment.

The scene exporter intentionally remains usable without an Android SDK.  This
module is the optional second half of the workflow: it discovers a local SDK,
invokes the generated project's pinned Gradle wrapper, and can install a debug
or explicitly owner-signed build through ADB.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import subprocess
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


@dataclass(frozen=True)
class AndroidInstallResult:
    apk: Path
    serial: str
    output: str


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
    return AndroidBuildResult(project_dir, variant, task, apks[-1], output)


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
    ready = tuple(device for device in list_android_devices(toolchain) if device.ready)
    if serial is None:
        if len(ready) != 1:
            detail = ", ".join(f"{d.serial} ({d.state})" for d in ready) or "none"
            raise RuntimeError(
                "install requires exactly one ready device when --serial is omitted; "
                f"ready devices: {detail}"
            )
        serial = ready[0].serial
    elif serial not in {device.serial for device in ready}:
        raise RuntimeError(f"ADB device is not ready: {serial}")
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
