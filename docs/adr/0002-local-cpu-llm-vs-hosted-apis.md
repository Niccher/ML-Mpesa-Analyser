# ADR 0002: Local CPU-Only LLM Inference vs Hosted Cloud APIs

- **Status**: Accepted
- **Date**: 2026-09-06
- **Context**: ML Intelligence Microservice (`ML Mpesa Analyzer`)

---

## Context and Problem Statement

Extracting structured financial entities (balances, amounts, counterparties) and categorizing unstructured Kenyan SMS messages requires natural language understanding beyond brittle hardcoded regular expressions.

We considered two architectural alternatives:
1. **Hosted Cloud APIs**: OpenAI (GPT-4o mini), Anthropic (Claude 3 Haiku), or Groq.
2. **Local Self-Hosted LLM**: Running an open-weights model locally via `llama.cpp` on CPU.

Financial SMS messages contain sensitive personally identifiable information (PII) including account balances, phone numbers, full names, and timestamps. Furthermore, users often operate in self-hosted or air-gapped home-lab environments with intermittent internet connectivity.

---

## Decision

Deploy a quantized local language model (**Qwen2.5 1.5B Instruct** in `Q4_K_M` GGUF format) co-located inside the Docker container running on CPU via `llama-server`.

1. **Hardware Parameters**: Constrained to pure CPU execution (`--n-gpu-layers 0`) with OpenMP threading (`libgomp1`) and RAM pinning (`--mlock`).
2. **OpenAI-Compatible Abstraction**: FastAPI communicates with `llama-server` on loopback port 8080 using standard `/v1/chat/completions` request schemas, preserving the ability to hot-swap to cloud providers via environment variables (`LLM_BASE_URL`, `LLM_API_KEY`) if explicitly requested by operators.

---

## Consequences

### Positive
- **Data Sovereignty & Privacy**: Financial SMS bodies and personal balances never leave the user's local infrastructure.
- **Zero API Ingestion Costs**: Unlimited bulk and batch extraction runs without recurring SaaS token fees.
- **Offline Resilience**: Extraction and synchronization continue reliably without active internet connectivity.
- **Low Footprint**: Consumes only ~1.5 GB host RAM, allowing seamless deployment on modest VPS or home servers.

### Negative
- **Inference Latency**: Processing speed is ~15–25 tokens/sec per batch on CPU, which is slower than cloud GPU endpoints but well within the requirements for asynchronous background polling.
