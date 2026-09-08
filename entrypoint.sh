#!/bin/bash
set -e

LLAMA_PORT=${LLAMA_PORT:-8080}
MODEL_PATH=${MODEL_PATH:-/models/qwen2.5-1.5b-instruct-q4_k_m.gguf}
LLM_CTX_SIZE=${LLM_CTX_SIZE:-16384}
LLM_BATCH_SIZE=${LLM_BATCH_SIZE:-512}
N_GPU_LAYERS=${N_GPU_LAYERS:-0}

is_valid_gguf() {
    local file="$1"
    if [ ! -f "$file" ]; then
        return 1
    fi
    local fsize=$(stat -c%s "$file" 2>/dev/null || stat -f%z "$file" 2>/dev/null || wc -c < "$file" 2>/dev/null || echo 0)
    if [ "$fsize" -lt 52428800 ]; then
        echo "Warning: Model file ${file} is too small (${fsize} bytes) - incomplete or corrupted."
        return 1
    fi
    local magic=$(head -c 4 "$file" 2>/dev/null)
    if [ "$magic" != "GGUF" ]; then
        echo "Warning: Model file ${file} does not contain GGUF magic header (got '$magic')."
        return 1
    fi
    return 0
}

# Ensure model directory exists
mkdir -p "$(dirname "${MODEL_PATH}")"

# Verify or download the active model safely to avoid corruption
if ! is_valid_gguf "${MODEL_PATH}"; then
    echo "Model missing or corrupted at ${MODEL_PATH}. Downloading to temporary buffer..."
    TEMP_MODEL="${MODEL_PATH}.tmp"
    rm -f "${TEMP_MODEL}"
    curl -L --retry 3 --fail -o "${TEMP_MODEL}" "${MODEL_DOWNLOAD_URL:-https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf}"
    
    if is_valid_gguf "${TEMP_MODEL}"; then
        mv -f "${TEMP_MODEL}" "${MODEL_PATH}"
        echo "Model successfully downloaded and verified at ${MODEL_PATH}."
    else
        echo "ERROR: Downloaded model failed verification. Cleaning up."
        rm -f "${TEMP_MODEL}"
        FALLBACK_MODEL=$(find "$(dirname "${MODEL_PATH}")" -type f -name "*.gguf" 2>/dev/null | head -n 1)
        if [ -n "${FALLBACK_MODEL}" ] && is_valid_gguf "${FALLBACK_MODEL}"; then
            echo "Falling back to existing valid model: ${FALLBACK_MODEL}"
            MODEL_PATH="${FALLBACK_MODEL}"
        else
            echo "FATAL: No valid GGUF model could be verified or loaded."
            exit 1
        fi
    fi
fi

echo "Starting llama.cpp server on port ${LLAMA_PORT}..."
llama-server \
    --model "${MODEL_PATH}" \
    --port "${LLAMA_PORT}" \
    --host 0.0.0.0 \
    --ctx-size "${LLM_CTX_SIZE}" \
    --batch-size "${LLM_BATCH_SIZE}" \
    --n-gpu-layers "${N_GPU_LAYERS}" \
    --mlock \
    &

LLAMA_PID=$!

# Wait for the LLM server to be ready
echo "Waiting for llama.cpp to be ready..."
for i in $(seq 1 60); do
    if curl -s "http://localhost:${LLAMA_PORT}/health" > /dev/null 2>&1; then
        echo "llama.cpp ready after ${i}s"
        break
    fi
    sleep 2
done

if ! kill -0 "${LLAMA_PID}" 2>/dev/null; then
    echo "ERROR: llama.cpp failed to start"
    exit 1
fi

echo "Starting FastAPI app on port 9050..."
exec uvicorn app.main:app --host 0.0.0.0 --port 9050 --reload
