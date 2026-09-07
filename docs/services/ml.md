# Machine Learning & Inference Handbook

This document describes the model architecture, prompt engineering strategies, and inference runtime powering financial transaction extraction.

---

## 1. Active Model: Qwen2.5 1.5B Instruct

The system runs [Qwen2.5 1.5B Instruct](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF) in `Q4_K_M` quantization format.

| Property | Value | Notes |
|----------|-------|-------|
| **Parameters** | 1.54 Billion | Transformer architecture with RoPE embeddings |
| **Quantization** | Q4_K_M (4-bit medium) | File size ~1.1 GB, RAM footprint ~1.5 GB |
| **Context Window** | 16,384 tokens | Accommodates multi-SMS batch evaluation |
| **Inference Hardware** | CPU-only | Standard x86 AVX2 / ARM NEON acceleration |
| **Throughput** | 15–25 tokens/sec | Modern multi-core CPU |

---

## 2. Model Switching & Alternatives

Any GGUF model supported by llama.cpp can be placed in `models/` and activated via the admin API or `.env`:

| Model | Parameters | Size (Q4_K_M) | Trade-Off |
|-------|:----------:|:-------------:|-----------|
| **Qwen2.5 1.5B** *(Active)* | 1.5B | 1.1 GB | Optimal balance of speed, low RAM, and JSON syntax adherence. |
| **Llama 3.2 1B** | 1.2B | 0.8 GB | Fastest extraction, slightly lower counterparty extraction accuracy. |
| **Llama 3.2 3B** | 3.2B | 2.0 GB | Higher reasoning quality on ambiguous notifications; requires 3+ GB RAM. |
| **Phi-3 Mini 3.8B** | 3.8B | 2.5 GB | Exceptional instruction adherence, higher CPU utilization. |

To switch models:
1. Place the new `.gguf` file in `models/`.
2. Update `MODEL_PATH` and `LLM_MODEL` in `.env`.
3. Restart: `docker compose up -d --build`.

---

## 3. Two-Tier Classification Pipeline

### Tier 1: Known Dictionary (Zero-Latency)
Before contacting the LLM, the sender number or alphanumeric header is compared against:
1. `tbl_Allowed_Senders` (database allowlist).
2. Curated dictionary of 60+ Kenyan financial institutions (`app/utils/prompt_templates.py`):
   - **Mobile Money**: MPESA, Airtel Money, T-Kash
   - **Banks**: KCB, Equity, NCBA, Co-op, Absa, StanChart, I&M, Stanbic, DTB, Family Bank
   - **Fintechs & Loans**: M-Shwari, Tala, Branch, Zenka, Timiza, Hustler Fund
   - **SACCOs**: Stima SACCO, Mwalimu SACCO, Harambee, Police SACCO
   - **Government & Utilities**: KRA, eCitizen, PesaLink

Matches are classified immediately with `0.95` confidence and zero LLM latency.

### Tier 2: LLM Few-Shot Evaluation
Unknown senders are sent to the LLM with up to 10 sample messages to classify whether the sender is a financial entity, identify the category, and provide reasoning.

---

## 4. Prompt Template Versioning

Prompts are managed by `prompt_manager.py`:
- Checks `tbl_LLM_Prompts` for an active override by key (`classify_sender`, `extract_batch`).
- If none is active, falls back to the hardcoded default in `prompt_templates.py`.
- Admin API (`POST /admin/prompts`) saves new versions without overwriting historical templates.
