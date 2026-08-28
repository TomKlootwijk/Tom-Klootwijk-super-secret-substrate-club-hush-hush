from __future__ import annotations

from dataclasses import dataclass, asdict
import os
import platform
import sys
from typing import Any

import torch


@dataclass(frozen=True)
class DeviceReport:
    index: int
    name: str
    compute_capability: tuple[int, int]
    total_vram_bytes: int
    multi_processor_count: int
    bf16_supported: bool


def hardware_report() -> dict[str, Any]:
    """Return a reproducible PyTorch/CUDA capability report.

    The report intentionally distinguishes a CUDA-enabled PyTorch build from a
    working CUDA runtime and from the named physical device.  It is suitable for
    attaching to benchmark artifacts before any throughput claim is made.
    """
    built_with_cuda = bool(torch.version.cuda)
    cuda_available = bool(torch.cuda.is_available())
    devices: list[dict[str, Any]] = []
    if cuda_available:
        for index in range(torch.cuda.device_count()):
            props = torch.cuda.get_device_properties(index)
            major, minor = torch.cuda.get_device_capability(index)
            try:
                bf16 = bool(torch.cuda.is_bf16_supported(index))
            except TypeError:  # older PyTorch accepts no index
                current = torch.cuda.current_device()
                try:
                    torch.cuda.set_device(index)
                    bf16 = bool(torch.cuda.is_bf16_supported())
                finally:
                    torch.cuda.set_device(current)
            devices.append(
                asdict(
                    DeviceReport(
                        index=index,
                        name=torch.cuda.get_device_name(index),
                        compute_capability=(int(major), int(minor)),
                        total_vram_bytes=int(props.total_memory),
                        multi_processor_count=int(props.multi_processor_count),
                        bf16_supported=bf16,
                    )
                )
            )
    try:
        arch_list = list(torch.cuda.get_arch_list()) if built_with_cuda else []
    except Exception:
        arch_list = []
    return {
        "format": "UGTS-SPATIAL-HARDWARE-1",
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "torch": torch.__version__,
        "torch_cuda_version": torch.version.cuda,
        "cuda_build": built_with_cuda,
        "cuda_available": cuda_available,
        "cuda_device_count": int(torch.cuda.device_count()) if cuda_available else 0,
        "compiled_cuda_arches": arch_list,
        "cuda_visible_devices": os.getenv("CUDA_VISIBLE_DEVICES"),
        "devices": devices,
        "acceptance": {
            "sm120_present": any(
                tuple(device["compute_capability"]) == (12, 0) for device in devices
            ),
            "twelve_gib_or_more_present": any(
                int(device["total_vram_bytes"]) >= 12 * 1024**3 for device in devices
            ),
            "note": (
                "A successful capability report is not a throughput result. Preserve "
                "device, driver, power mode, thermal state, precision and error budget "
                "with every benchmark."
            ),
        },
    }
