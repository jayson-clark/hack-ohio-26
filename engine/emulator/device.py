"""Which accelerator the fire emulator runs on (#113).

MLX has two GPU backends: Metal on Apple silicon (what PyTorch calls "MPS")
and CUDA on NVIDIA GPUs (Linux, with the `mlx[cuda]` package). The same
training and inference code runs on either, so this only reports and
selects the device:

- auto: the GPU if MLX has one (Metal or CUDA), else the CPU;
- gpu: the GPU, or an error if there isn't one;
- cpu: the CPU, even with a GPU (slow, but useful for checking).
"""

import mlx.core as mx


def gpu_backend() -> str | None:
    """'metal', 'cuda', or None when MLX has no GPU backend here."""
    if mx.metal.is_available():
        return "metal"
    cuda = getattr(mx, "cuda", None)  # MLX builds before the CUDA backend lack it
    if cuda is not None and cuda.is_available():
        return "cuda"
    return None


def select(prefer: str = "auto") -> dict:
    """Make the chosen device MLX's default and describe it:
    {"backend": "metal" | "cuda" | "cpu", "device": name, "memory_gb": ...}."""
    if prefer not in ("auto", "gpu", "cpu"):
        raise ValueError(f"unknown device {prefer!r}: use auto, gpu or cpu")
    backend = gpu_backend()
    if prefer == "gpu" and backend is None:
        raise SystemExit("no GPU for MLX here: on a Mac it needs Apple silicon; on Linux, install mlx[cuda]")
    if prefer == "cpu" or backend is None:
        mx.set_default_device(mx.cpu)
        return {"backend": "cpu", "device": "CPU", "memory_gb": None}
    mx.set_default_device(mx.gpu)
    info = _info()
    memory = info.get("memory_size") or info.get("total_memory")
    return {
        "backend": backend,
        "device": str(info.get("device_name") or info.get("name") or backend),
        "memory_gb": round(memory / 2**30, 1) if memory else None,
    }


def _info() -> dict:
    try:
        return dict(mx.device_info())
    except Exception:  # older MLX, or a backend that doesn't report it
        return {}


def describe(d: dict) -> str:
    """'Apple M2 Max (metal, 96.0 GB)' for logs."""
    mem = f", {d['memory_gb']} GB" if d.get("memory_gb") else ""
    return f"{d['device']} ({d['backend']}{mem})"
