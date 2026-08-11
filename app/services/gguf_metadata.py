"""Read lightweight metadata out of GGUF model files.

GGUF layout (little-endian):
    magic            4 bytes   "GGUF"
    version          uint32
    tensor_count     uint64
    metadata_kv_count uint64
    key-value pairs  (repeated)
    tensor info ...
    tensor data ...

Only the key-value header is parsed here (tensor info/data are skipped),
so we only read a small prefix of the file rather than the whole model.
"""

from __future__ import annotations

import os
import struct
from typing import Optional

_MAGIC = b"GGUF"
_HEADER_SIZE = 4 + 4 + 8 + 8  # magic + version + tensor_count + kv_count

# GGUFValueType
UINT8 = 0
INT8 = 1
UINT16 = 2
INT16 = 3
UINT32 = 4
INT32 = 5
FLOAT32 = 6
BOOL = 7
STRING = 8
ARRAY = 9
UINT64 = 10
INT64 = 11
FLOAT64 = 12

# GGML file_type -> human readable quantization label
_QUANT_LABELS = {
    0: "F32",
    1: "F16",
    2: "Q4_0",
    3: "Q4_1",
    6: "Q8_0",
    7: "Q5_0",
    8: "Q5_1",
    9: "Q2_K",
    10: "Q3_K",
    11: "Q3_K_S",
    12: "Q3_K_M",
    13: "Q3_K_L",
    14: "Q4_K",
    15: "Q4_K_S",
    16: "Q4_K_M",
    17: "Q5_K",
    18: "Q5_K_S",
    19: "Q5_K_M",
    20: "Q6_K",
    21: "IQ1_S",
    22: "IQ2_XXS",
    23: "IQ2_XS",
    24: "IQ3_XXS",
    25: "IQ1_M",
    26: "IQ4_NL",
    27: "IQ3_XS",
    28: "IQ3_S",
    29: "IQ2_S",
    30: "IQ2_M",
    31: "IQ4_XS",
    32: "IQ3_M",
    33: "IQ1_S",
    34: "IQ1_M",
    35: "IQ4_NL",
    36: "IQ4_XS",
    37: "IQ4_H",
}

# GGUF types that fit in 8 bytes when packed into an uint64-style read
_INT_TYPES = {UINT8, INT8, UINT16, INT16, UINT32, INT32, UINT64, INT64}
_FLOAT_TYPES = {FLOAT32, FLOAT64}


def _read_u64(buf: bytes, offset: int) -> int:
    return struct.unpack_from("<Q", buf, offset)[0]


def _read_u32(buf: bytes, offset: int) -> int:
    return struct.unpack_from("<I", buf, offset)[0]


def _read_string(buf: bytes, offset: int) -> tuple[str, int]:
    length = _read_u64(buf, offset)
    offset += 8
    return buf[offset : offset + length].decode("utf-8", errors="replace"), offset + length


def _read_scalar(buf: bytes, offset: int, vtype: int):
    """Read a single (non-array) value of the given GGUF type."""
    fmt = {
        UINT8: ("B", 1),
        INT8: ("b", 1),
        UINT16: ("H", 2),
        INT16: ("h", 2),
        UINT32: ("I", 4),
        INT32: ("i", 4),
        FLOAT32: ("f", 4),
        UINT64: ("Q", 8),
        INT64: ("q", 8),
        FLOAT64: ("d", 8),
        BOOL: ("?", 1),
    }.get(vtype)

    if fmt:
        code, size = fmt
        return struct.unpack_from(code, buf, offset)[0], offset + size
    if vtype == STRING:
        return _read_string(buf, offset)
    raise ValueError(f"Unsupported GGUF value type {vtype}")


def _parse_metadata(buf: bytes) -> dict:
    """Parse the metadata KV section into a dict. Skips tensor info."""
    if len(buf) < _HEADER_SIZE or buf[:4] != _MAGIC:
        raise ValueError("Not a GGUF file")

    kv_count = _read_u64(buf, 4 + 4 + 8)
    offset = _HEADER_SIZE
    meta: dict = {}

    for _ in range(kv_count):
        key, offset = _read_string(buf, offset)
        vtype = _read_u32(buf, offset)
        offset += 4

        if vtype == ARRAY:
            elem_type = _read_u32(buf, offset)
            offset += 4
            count = _read_u64(buf, offset)
            offset += 8
            values = []
            for _ in range(count):
                val, offset = _read_scalar(buf, offset, elem_type)
                values.append(val)
            meta[key] = values
        else:
            val, offset = _read_scalar(buf, offset, vtype)
            meta[key] = val

    return meta


def _as_int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def format_params(n_params) -> str:
    n = _as_int(n_params)
    if not n:
        return "—"
    if n >= 1_000_000_000:
        return f"{n / 1e9:.2f}B"
    if n >= 1_000_000:
        return f"{n / 1e6:.2f}M"
    if n >= 1_000:
        return f"{n / 1e3:.2f}K"
    return str(n)


def read_gguf_metadata(path: str) -> dict:
    """Return a friendly metadata dict for a GGUF model file.

    Returns an empty dict (no exception) if the file is not a valid GGUF
    or cannot be read, so model listings degrade gracefully.
    """
    try:
        size = os.path.getsize(path)
        # Metadata header (KV pairs) sits at the very start of the file.
        # Read up to 2MB; expand if the header turns out to be larger.
        read_len = min(size, 2 * 1024 * 1024)
        with open(path, "rb") as f:
            buf = f.read(read_len)
        meta = _parse_metadata(buf)
    except Exception:
        return {}

    file_type = _as_int(meta.get("general.file_type"))
    quant = _QUANT_LABELS.get(file_type) if file_type is not None else None
    if quant is None and meta.get("general.quantization_version") is not None:
        quant = f"Q? (v{meta['general.quantization_version']})"

    return {
        "name": meta.get("general.name"),
        "architecture": meta.get("general.architecture"),
        "context_length": _as_int(meta.get("llama.context_length")),
        "embedding_length": _as_int(meta.get("llama.embedding_length")),
        "block_count": _as_int(meta.get("llama.block_count")),
        "n_params": _as_int(meta.get("general.n_params")),
        "n_params_label": format_params(meta.get("general.n_params")),
        "quantization": quant,
        "file_type": file_type,
        "params_raw": meta.get("general.n_params"),
    }
