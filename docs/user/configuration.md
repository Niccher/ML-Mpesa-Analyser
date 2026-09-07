# Configuration Guide — ML Mpesa Analyzer

The following environment variables configure the container runtime and connections. Edit `.env` before starting Compose.

---

## User Environment Variables

| Variable | Service | Required | Default | Purpose |
|----------|---------|:--------:|---------|---------|
| `LLM_PROVIDER` | FastAPI | No | `openai-compatible` | LLM backend type (`openai-compatible` or cloud provider) |
| `LLM_BASE_URL` | FastAPI | No | `http://localhost:8080/v1` | URL where llama-server is listening |
| `LLM_MODEL` | FastAPI | No | `qwen2.5-1.5b-instruct` | Active model identifier sent in request body |
| `LLM_MAX_TOKENS` | FastAPI | No | `2048` | Maximum token length for structured JSON extraction |
| `LLM_TEMPERATURE` | FastAPI | No | `0.2` | Generation temperature (low values ensure deterministic JSON) |
| `LLM_CTX_SIZE` | llama-server | No | `16384` | Context window length in tokens |
| `LLM_BATCH_SIZE` | llama-server | No | `512` | Batch evaluation chunk size |
| `N_GPU_LAYERS` | llama-server | No | `0` | GPU offloading layers (0 = pure CPU inference) |
| `MODEL_PATH` | llama-server | Yes | `/models/qwen2.5-1.5b-instruct-q4_k_m.gguf` | Path to active GGUF weights inside container |
| `DB_HOST` | MySQL | Yes | `mysql` | Hostname of shared MySQL server |
| `DB_PORT` | MySQL | Yes | `3306` | MySQL server port |
| `DB_USER` | MySQL | Yes | `root` | Database username |
| `DB_PASSWORD` | MySQL | Yes | `root_password` | Database password |
| `DB_NAME` | MySQL | Yes | `db_mpesa_analyzer` | Database schema name |
| `BATCH_SIZE` | Poller | No | `20` | Number of messages processed per extraction cycle |
| `POLL_INTERVAL` | Poller | No | `30` | Seconds between background DB poll checks |
| `MAX_RETRIES` | Poller | No | `3` | Maximum error retry attempts per failed SMS |
