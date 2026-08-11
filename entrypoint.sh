#!/bin/bash
set -e

LLAMA_PORT=${LLAMA_PORT:-8080}
MODEL_PATH=${MODEL_PATH:-/models/qwen2.5-1.5b-instruct-q4_k_m.gguf}
LLM_CTX_SIZE=${LLM_CTX_SIZE:-16384}
LLM_BATCH_SIZE=${LLM_BATCH_SIZE:-512}
N_GPU_LAYERS=${N_GPU_LAYERS:-0}

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
exec uvicorn app.main:app --host 0.0.0.0 --port 9050
