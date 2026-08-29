#!/usr/bin/env python3
"""Collect non-authoritative hardware/build facts from the target machine."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def run(command: list[str]) -> dict:
    try:
        process = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        return {
            "command": command,
            "returncode": process.returncode,
            "stdout": process.stdout.strip(),
            "stderr": process.stderr.strip(),
        }
    except Exception as exc:  # diagnostic utility
        return {"command": command, "error": repr(exc)}


def main() -> int:
    payload = {
        "purpose": "configuration evidence only; not a proof result",
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "tools": {
            name: shutil.which(name)
            for name in ("nvidia-smi", "nvcc", "cmake", "git", "c++")
        },
    }
    if shutil.which("nvidia-smi"):
        payload["nvidia_smi"] = run(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,memory.total,memory.free,power.limit,temperature.gpu",
                "--format=csv,noheader,nounits",
            ]
        )
    if shutil.which("nvcc"):
        payload["nvcc"] = run(["nvcc", "--version"])
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    print(text, end="")
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
