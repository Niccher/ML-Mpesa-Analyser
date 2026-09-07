# Operational Runbook: Upgrading and Swapping GGUF Models

This runbook describes the procedure for evaluating, staging, and activating alternative GGUF models in the **ML Mpesa Analyzer** container.

---

## 1. Candidate Models & Sizing

| Model | Quantization | Size | RAM Required | Best Use Case |
|-------|:------------:|:----:|:------------:|---------------|
| **Qwen2.5 1.5B** *(Default)* | Q4_K_M | 1.1 GB | ~1.5 GB | Baseline, balanced speed and adherence |
| **Llama 3.2 1B Instruct** | Q4_K_M | 0.8 GB | ~1.2 GB | Low-memory VPS environments |
| **Llama 3.2 3B Instruct** | Q4_K_M | 2.0 GB | ~2.8 GB | Higher accuracy on informal Swahili/Sheng |
| **Phi-3 Mini 3.8B** | Q4_K_M | 2.5 GB | ~3.2 GB | Strict JSON formatting compliance |

---

## 2. Procedure A: Via Admin Console (Zero-CLI)

1. **Access Model Management**:
   Open http://localhost:9002/admin/ml/models in the WebApp dashboard.
2. **Upload New Model**:
   Upload the new `.gguf` file via the web interface. The file is streamed in 1 MB chunks to `models/` inside the container.
3. **Inspect GGUF Metadata**:
   Verify detected parameter count, architecture, context size, and quantization reported by the automatic header reader.
4. **Test Prompt Adherence**:
   Navigate to **Test Prompt** (`/admin/ml/test`) and run sample messages to verify JSON extraction with the new weights.
5. **Activate**:
   Click **Activate** on the target model row.
6. **Restart Container**:
   Restart the container to bind llama-server to the new model:
   ```bash
   docker compose restart ml-mpesa-analyzer
   ```

---

## 3. Procedure B: Via Command Line

1. Download model file into `models/`:
   ```bash
   wget -P models/ https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf
   ```
2. Update `.env`:
   ```ini
   MODEL_PATH=/models/qwen2.5-3b-instruct-q4_k_m.gguf
   LLM_MODEL=qwen2.5-3b-instruct
   ```
3. Restart container stack:
   ```bash
   docker compose up --build -d
   ```
4. Verify health:
   ```bash
   curl -f http://localhost:9050/health
   ```
