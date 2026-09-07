# API Contract — ML Mpesa Analyzer

The service exposes HTTP endpoints on port `9050`. Interactive OpenAPI documentation is accessible at `/docs` or `/redoc` when the container is running.

---

## 1. Core Service Endpoints

### `GET /health`
Validates container health, database configuration, and LLM provider connectivity.

**Response `200 OK`**:
```json
{
  "status": "ok",
  "llm_provider": "openai-compatible",
  "llm_model": "qwen2.5-1.5b-instruct",
  "db_configured": true
}
```

---

### `POST /process/trigger`
Manually executes a single processing cycle on pending SMS records. Blocked if `auto_jobs_enabled` is set to `false`.

**Response `200 OK`**:
```json
{
  "senders_classified": 1,
  "messages_processed": 20,
  "finance_senders_found": 1,
  "transactional_inserted": 3,
  "errors": 0
}
```

---

### `POST /process/for-user/{user_id}`
Executes a targeted extraction job for all unprocessed SMS belonging to a specific user. Called by the CodeIgniter 4 backend during user rescan operations.

**Response `200 OK`**:
```json
{
  "job_id": 42,
  "user_id": "usr_9410",
  "status": "done",
  "messages_processed": 15,
  "errors": 0,
  "duration_seconds": 12
}
```

---

## 2. Administration Endpoints (`/admin/*`)

| Endpoint | Method | Payload / Params | Purpose |
|----------|:------:|------------------|---------|
| `/admin/status` | GET | None | Complete backend status: health, model files with GGUF headers, uptime, auto-jobs state. |
| `/admin/models` | GET | None | List available GGUF model files in `models/` with active marker. |
| `/admin/models/upload` | POST | Multipart form file | Upload a new `.gguf` weight file in 1 MB chunks. |
| `/admin/models/activate`| POST | `{"model_path": str}` | Activate model file (updates configuration, requires restart). |
| `/admin/models/delete` | POST | `{"model_path": str}` | Delete unused model file from disk. |
| `/admin/config` | POST | JSON config object | Update runtime config & `.env` parameters. |
| `/admin/test-prompt` | POST | `{"messages": [str]}` | Test classification and extraction on sample SMS messages. |
| `/admin/prompts` | GET | None | List versioned prompt templates and active overrides. |
| `/admin/prompts` | POST | `{"prompt_key": str, "template": str}` | Create and activate a new versioned prompt template. |
| `/admin/prompts/{id}/activate` | POST | None | Activate a previously saved prompt version. |
| `/admin/jobs/status` | GET | None | Check auto-jobs poller toggle state and aggregated job metrics. |
| `/admin/jobs/auto` | POST | `{"enabled": bool}` | Enable or disable the background poller daemon. |
| `/admin/jobs` | GET | `?limit=20` | Retrieve recent execution jobs with rich JSON metadata. |
| `/admin/allowed/defaults` | GET | None | Retrieve hardcoded fallback list of 60+ Kenyan financial senders. |
