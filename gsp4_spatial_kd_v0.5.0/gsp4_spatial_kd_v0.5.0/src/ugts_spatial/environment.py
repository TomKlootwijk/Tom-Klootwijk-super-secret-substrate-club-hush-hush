from __future__ import annotations

import platform
import time
from typing import Any

import torch


def gpu_environment_report(
    *,
    run_smoke: bool = True,
    requested_device: str = "auto",
    precision: str = "float16",
) -> dict[str, Any]:
    """Return a machine-readable CUDA/PyTorch readiness report.

    The smoke path launches matrix multiplication, indexed reduction, and a
    synchronization. Those operations exercise the primitives used by the
    dependency-light HGT/TGN implementation without claiming application
    throughput from a microbenchmark.
    """

    precision = precision.lower()
    if precision not in {"float16", "bf16", "float32"}:
        raise ValueError("precision must be float16, bf16 or float32")
    if requested_device not in {"auto", "cuda", "cpu"}:
        raise ValueError("requested_device must be auto, cuda or cpu")
    report: dict[str, Any] = {
        "format": "GSP4-GPU-ENVIRONMENT-2",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "torch": torch.__version__,
        "torch_cuda_version": torch.version.cuda,
        "cuda_available": bool(torch.cuda.is_available()),
        "cuda_device_count": int(torch.cuda.device_count()) if torch.cuda.is_available() else 0,
        "torch_arch_list": list(torch.cuda.get_arch_list()) if torch.cuda.is_available() else [],
        "smoke_requested": bool(run_smoke),
        "requested_device": requested_device,
        "requested_precision": precision,
    }
    if requested_device == "cpu":
        report.update(
            {
                "ready": True,
                "reason": "CPU inspection requested; this does not validate the target GPU",
            }
        )
        return report
    if not torch.cuda.is_available():
        report.update(
            {
                "ready": False,
                "reason": "torch.cuda.is_available() is false; install a CUDA-enabled PyTorch wheel and current NVIDIA driver",
            }
        )
        return report

    devices: list[dict[str, Any]] = []
    for index in range(torch.cuda.device_count()):
        props = torch.cuda.get_device_properties(index)
        capability = torch.cuda.get_device_capability(index)
        devices.append(
            {
                "index": index,
                "name": torch.cuda.get_device_name(index),
                "compute_capability": [int(capability[0]), int(capability[1])],
                "total_memory_bytes": int(props.total_memory),
                "multiprocessor_count": int(props.multi_processor_count),
                "bf16_supported": bool(torch.cuda.is_bf16_supported()),
            }
        )
    report["devices"] = devices

    if not run_smoke:
        report["ready"] = True
        return report

    device = torch.device("cuda:0")
    torch.cuda.synchronize(device)
    start = time.perf_counter()
    try:
        generator = torch.Generator(device=device)
        generator.manual_seed(20260710)
        dtype = {
            "float16": torch.float16,
            "bf16": torch.bfloat16,
            "float32": torch.float32,
        }[precision]
        if dtype is torch.bfloat16 and not torch.cuda.is_bf16_supported():
            raise RuntimeError("BF16 was requested but is not supported by the selected CUDA device")
        left = torch.randn((1024, 256), generator=generator, device=device, dtype=dtype)
        right = torch.randn((256, 256), generator=generator, device=device, dtype=dtype)
        product = left @ right
        groups = torch.arange(product.shape[0], device=device, dtype=torch.int64) % 64
        reduced = torch.zeros((64, product.shape[1]), device=device, dtype=torch.float32)
        reduced.index_add_(0, groups, product.float())
        maxima = torch.full((64,), -torch.inf, device=device, dtype=torch.float32)
        maxima.scatter_reduce_(
            0,
            groups,
            product[:, 0].float(),
            reduce="amax",
            include_self=True,
        )
        checksum = float((reduced.sum() + maxima.sum()).item())
        torch.cuda.synchronize(device)
        report["smoke"] = {
            "passed": True,
            "elapsed_ms": float((time.perf_counter() - start) * 1000.0),
            "checksum": checksum,
            "precision": precision,
            "operations": [f"{precision}_matmul", "index_add", "scatter_reduce_amax"],
        }
        report["ready"] = True
    except Exception as exc:  # pragma: no cover - target hardware path
        report["smoke"] = {
            "passed": False,
            "elapsed_ms": float((time.perf_counter() - start) * 1000.0),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        report["ready"] = False
    return report
