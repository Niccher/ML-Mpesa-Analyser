# Machine Learning & Inference Handbook

This document describes the model architecture, prompt engineering strategies, and inference runtime powering financial transaction extraction.

---

## 1. Active & Supported Models

The system natively supports GGUF models optimized with `llama.cpp`:

| Property | Qwen2.5 1.5B Instruct | Qwen2.5 3B Instruct (Recommended) | Llama 3.2 3B Instruct |
|----------|----------------------|-----------------------------------|-----------------------|
| **Parameters** | 1.54 Billion | 3.09 Billion | 3.21 Billion |
| **Quantization** | Q4_K_M (4-bit medium) | Q4_K_M (4-bit medium) | Q4_K_M (4-bit medium) |
| **File Size** | ~1.1 GB | ~2.0 GB | ~2.0 GB |
| **RAM Footprint** | ~1.5 GB | ~2.5 GB | ~2.6 GB |
| **Context Window** | 16,384 tokens | 32,768 tokens | 8,192 tokens |
| **Hardware** | 2-4 Cores, AVX2 | 4+ Cores, AVX2 / CUDA | 4+ Cores, AVX2 / CUDA |
| **Throughput** | 20–30 tokens/sec | 12–20 tokens/sec | 14–22 tokens/sec |

---

## 2. Model Presets & Dynamic Activation

Admins can download and activate presets directly from the WebApp:

1. **One-Click Downloads**: Pulls validated GGUF weights from Hugging Face into `models/`.
2. **Pre-Flight Validation**: Checks host disk space and RAM headroom before starting downloads.
3. **Hot Reload**: Calls `/admin/models/activate` which safely reloads `llama-server` with the selected model.

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
- Admin API (`POST /admin/prompts`) saves new versions without overwriting historical templates.\n