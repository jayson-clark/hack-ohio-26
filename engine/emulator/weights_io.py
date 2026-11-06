"""The emulator's weights file, readable and writable without MLX or PyTorch.

Weights are always stored the way MLX saves them (`FireUNet.save_weights`),
so the engine on a Mac loads a model whatever trained it. That is a
safetensors file of float32 tensors named like `e1.a.weight`, with
convolution kernels laid out (out, kh, kw, in). PyTorch keeps the same names
but lays kernels out (out, in, kh, kw); `to_torch` / `to_mlx` convert.

safetensors format: an 8-byte little-endian header length, a JSON header
{name: {"dtype", "shape", "data_offsets": [begin, end]}}, then the raw
little-endian data. Only what the emulator uses (F32) is supported.
"""

import json
import struct
from pathlib import Path

import numpy as np

_DTYPES = {"F32": np.dtype("<f4")}


def read(path: str | Path) -> dict[str, np.ndarray]:
    raw = Path(path).read_bytes()
    (n,) = struct.unpack("<Q", raw[:8])
    header = json.loads(raw[8 : 8 + n])
    base = 8 + n
    out = {}
    for name, info in header.items():
        if name == "__metadata__":
            continue
        if info["dtype"] not in _DTYPES:
            raise ValueError(f"{path}: {name} is {info['dtype']}; only F32 weights are supported")
        b, e = info["data_offsets"]
        out[name] = np.frombuffer(raw[base + b : base + e], _DTYPES[info["dtype"]]).reshape(info["shape"]).copy()
    return out


def write(path: str | Path, tensors: dict[str, np.ndarray]) -> None:
    header, chunks, offset = {}, [], 0
    for name in sorted(tensors):
        a = np.ascontiguousarray(tensors[name], dtype="<f4")
        header[name] = {"dtype": "F32", "shape": list(a.shape), "data_offsets": [offset, offset + a.nbytes]}
        chunks.append(a.tobytes())
        offset += a.nbytes
    head = json.dumps(header, separators=(",", ":")).encode()
    head += b" " * (-len(head) % 8)  # the data starts 8-byte aligned
    Path(path).write_bytes(struct.pack("<Q", len(head)) + head + b"".join(chunks))


def to_torch(mlx_tensors: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """MLX layout -> PyTorch layout (conv kernels (out, kh, kw, in) -> (out, in, kh, kw))."""
    return {k: v.transpose(0, 3, 1, 2) if v.ndim == 4 else v for k, v in mlx_tensors.items()}


def to_mlx(torch_tensors: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """PyTorch layout -> MLX layout."""
    return {k: v.transpose(0, 2, 3, 1) if v.ndim == 4 else v for k, v in torch_tensors.items()}
