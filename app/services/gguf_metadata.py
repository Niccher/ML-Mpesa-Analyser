"""Read lightweight metadata out of GGUF model files.

GGUF layout (little-endian):
    magic            4 bytes   "GGUF"
    version          uint32
    tensor_count     uint64
    metadata_kv_count uint64
    key-value pairs  (repeated)
    tensor info ...
    tensor data ...
"""

from __future__ import annotations

import io
import logging
import os
import re
import struct
from typing import BinaryIO, Optional

logger = logging.getLogger(__name__)

_MAGIC = b"GGUF"

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


def _read_exact(f: BinaryIO, n: int) -> bytes:
    data = f.read(n)
    if len(data) < n:
        raise EOFError(f"Unexpected end of file while reading {n} bytes")
    return data


def _read_string_stream(f: BinaryIO) -> str:
    len_bytes = _read_exact(f, 8)
    length = struct.unpack("<Q", len_bytes)[0]
    if length == 0:
        return ""
    # Cap string read to prevent memory explosion on corrupt headers
    if length > 10 * 1024 * 1024:
        f.seek(length, io.SEEK_CUR)
        return ""
    str_bytes = _read_exact(f, length)
    return str_bytes.decode("utf-8", errors="replace")


def _read_scalar_stream(f: BinaryIO, vtype: int):
    scalar_map = {
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
    }
    if vtype in scalar_map:
        fmt, size = scalar_map[vtype]
        raw = _read_exact(f, size)
        return struct.unpack(f"<{fmt}", raw)[0]
    if vtype == STRING:
        return _read_string_stream(f)
    raise ValueError(f"Unknown GGUF value type {vtype}")


def _parse_stream_metadata(f: BinaryIO) -> dict:
    header = _read_exact(f, 4)
    if header != _MAGIC:
        raise ValueError("Not a valid GGUF file")

    version_bytes = _read_exact(f, 4)
    version = struct.unpack("<I", version_bytes)[0]
    if version not in (1, 2, 3):
        logger.warning(f"Unexpected GGUF version {version}")

    _read_exact(f, 8)  # tensor_count
    kv_count_bytes = _read_exact(f, 8)
    kv_count = struct.unpack("<Q", kv_count_bytes)[0]

    meta: dict = {}
    for _ in range(kv_count):
        key = _read_string_stream(f)
        vtype = struct.unpack("<I", _read_exact(f, 4))[0]

        if vtype == ARRAY:
            elem_type = struct.unpack("<I", _read_exact(f, 4))[0]
            count = struct.unpack("<Q", _read_exact(f, 8))[0]

            # If it's a huge tokenizer array (e.g. tokenizer tokens), skip details
            if "tokenizer." in key and count > 1000:
                # Fast skip array
                if elem_type == STRING:
                    for _ in range(count):
                        s_len = struct.unpack("<Q", _read_exact(f, 8))[0]
                        f.seek(s_len, io.SEEK_CUR)
                else:
                    scalar_sizes = {UINT8: 1, INT8: 1, UINT16: 2, INT16: 2, UINT32: 4, INT32: 4, FLOAT32: 4, UINT64: 8, INT64: 8, FLOAT64: 8, BOOL: 1}
                    size = scalar_sizes.get(elem_type, 1)
                    f.seek(count * size, io.SEEK_CUR)
                meta[key] = f"Array[{count} items]"
            else:
                values = []
                for _ in range(count):
                    values.append(_read_scalar_stream(f, elem_type))
                meta[key] = values
        else:
            meta[key] = _read_scalar_stream(f, vtype)

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


def _infer_from_filename(filename: str) -> dict:
    """Fallback heuristics derived from standard GGUF naming conventions."""
    fn = filename.lower()
    inferred: dict = {}

    # Quantization extraction
    quant_match = re.search(r"\b(q[0-9]_[kK]_[sSmMlL]|q[0-9]_[0-9]|q[0-9]_[kK]|iq[0-9]_[a-zA-Z0-9]+|f16|f32|bf16)\b", fn)
    if quant_match:
        inferred["quantization"] = quant_match.group(1).upper()

    # Parameter count extraction (e.g. 1.5b, 3b, 7b, 8b, 14b, 70b, 0.5b)
    param_match = re.search(r"[-_]([0-9]+(?:\.[0-9]+)?)[bB][-_.]", filename)
    if param_match:
        inferred["n_params_label"] = f"{param_match.group(1)}B"

    # Architecture / Family inference
    if "qwen2.5" in fn:
        inferred["architecture"] = "qwen2"
        inferred["name"] = "Qwen 2.5"
        inferred["context_length"] = 32768
    elif "qwen2" in fn or "qwen" in fn:
        inferred["architecture"] = "qwen2"
        inferred["name"] = "Qwen 2"
        inferred["context_length"] = 32768
    elif "llama-3.2" in fn:
        inferred["architecture"] = "llama"
        inferred["name"] = "Llama 3.2"
        inferred["context_length"] = 131072
    elif "llama-3.1" in fn:
        inferred["architecture"] = "llama"
        inferred["name"] = "Llama 3.1"
        inferred["context_length"] = 131072
    elif "llama-3" in fn or "llama3" in fn:
        inferred["architecture"] = "llama"
        inferred["name"] = "Llama 3"
        inferred["context_length"] = 8192
    elif "smollm2" in fn:
        inferred["architecture"] = "llama"
        inferred["name"] = "SmolLM2"
        inferred["context_length"] = 8192
    elif "deepseek-r1" in fn:
        inferred["architecture"] = "qwen2" if "qwen" in fn else "deepseek2"
        inferred["name"] = "DeepSeek R1 Distill"
        inferred["context_length"] = 32768
    elif "gemma-2" in fn:
        inferred["architecture"] = "gemma2"
        inferred["name"] = "Gemma 2"
        inferred["context_length"] = 8192
    elif "mistral" in fn:
        inferred["architecture"] = "llama"
        inferred["name"] = "Mistral"
        inferred["context_length"] = 32768

    return inferred


def read_gguf_metadata(path: str) -> dict:
    """Return a friendly metadata dict for a GGUF model file with multi-architecture support."""
    filename = os.path.basename(path)
    inferred = _infer_from_filename(filename)

    meta: dict = {}
    try:
        if os.path.isfile(path):
            with open(path, "rb") as f:
                meta = _parse_stream_metadata(f)
    except Exception as e:
        logger.warning(f"Could not parse GGUF header for '{filename}' ({e}); using filename heuristics.")

    arch = meta.get("general.architecture") or inferred.get("architecture") or "llama"

    # Context length: try architecture-specific keys, general keys, or fallback
    context_length = (
        _as_int(meta.get(f"{arch}.context_length"))
        or _as_int(meta.get("llama.context_length"))
        or _as_int(meta.get("qwen2.context_length"))
        or _as_int(meta.get("qwen.context_length"))
        or _as_int(meta.get("gemma2.context_length"))
        or _as_int(meta.get("phi3.context_length"))
        or _as_int(meta.get("general.context_length"))
        or inferred.get("context_length")
        or 8192
    )

    embedding_length = (
        _as_int(meta.get(f"{arch}.embedding_length"))
        or _as_int(meta.get("llama.embedding_length"))
        or _as_int(meta.get("qwen2.embedding_length"))
    )

    block_count = (
        _as_int(meta.get(f"{arch}.block_count"))
        or _as_int(meta.get("llama.block_count"))
        or _as_int(meta.get("qwen2.block_count"))
    )

    file_type = _as_int(meta.get("general.file_type"))
    quant = _QUANT_LABELS.get(file_type) if file_type is not None else None
    if quant is None:
        quant = inferred.get("quantization") or (f"Q? (v{meta['general.quantization_version']})" if meta.get("general.quantization_version") else "Q4_K_M")

    n_params_raw = meta.get("general.parameter_count") or meta.get("general.n_params") or meta.get("general.size_label")
    n_params_label = format_params(n_params_raw) if n_params_raw and _as_int(n_params_raw) else (inferred.get("n_params_label") or "1.5B")

    model_name = meta.get("general.name") or inferred.get("name") or filename

    return {
        "name": model_name,
        "architecture": arch,
        "context_length": context_length,
        "embedding_length": embedding_length,
        "block_count": block_count,
        "n_params": _as_int(n_params_raw),
        "n_params_label": n_params_label,
        "quantization": quant,
        "file_type": file_type,
        "params_raw": n_params_raw,
    }

