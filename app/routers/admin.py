from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx
import shutil
from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel, Field

from app.config import settings
from app.db.connection import verify_connection
from app.db.queries import (
    deactivate_prompts,
    delete_prompt,
    ensure_controls_table,
    ensure_jobs_table,
    ensure_prompts_table,
    fetch_jobs,
    get_active_prompt,
    get_all_prompts,
    get_max_version,
    insert_prompt,
    is_auto_jobs_enabled,
    set_control,
    set_prompt_active,
)
from app.models.schemas import ModelDownloadRequest
from app.services.classifier import SenderClassifier
from app.services.extractor import MessageExtractor
from app.services.gguf_metadata import read_gguf_metadata
from app.utils.prompt_templates import DEFAULT_PROMPTS, FINANCE_CATEGORIES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


class ConfigUpdate(BaseModel):
    llm_engine: Optional[str] = None
    llm_model: Optional[str] = None
    llm_max_tokens: Optional[int] = Field(default=None, ge=256, le=8192)
    llm_temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    llm_ctx_size: Optional[int] = Field(default=None, ge=256, le=131072)
    llm_batch_size: Optional[int] = Field(default=None, ge=1, le=8192)
    n_gpu_layers: Optional[int] = Field(default=None, ge=0, le=512)
    batch_size: Optional[int] = Field(default=None, ge=1, le=500)
    max_retries: Optional[int] = Field(default=None, ge=0, le=10)
    poll_interval: Optional[int] = Field(default=None, ge=5, le=3600)
    llm_provider: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_base_url: Optional[str] = None
    llm_external_provider: Optional[str] = None
    llm_external_api_key: Optional[str] = None
    llm_external_base_url: Optional[str] = None
    llm_external_model: Optional[str] = None
    llm_external_max_tokens: Optional[int] = Field(default=None, ge=256, le=8192)
    llm_external_temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    external_batch_size: Optional[int] = Field(default=None, ge=1, le=500)
    external_max_retries: Optional[int] = Field(default=None, ge=0, le=10)
    external_poll_interval: Optional[int] = Field(default=None, ge=5, le=3600)
    llm_fallback_provider: Optional[str] = None
    llm_fallback_api_key: Optional[str] = None
    llm_fallback_base_url: Optional[str] = None
    llm_fallback_model: Optional[str] = None
    llm_fallback_enabled: Optional[bool] = None
    llm_gemini_api_key: Optional[str] = None
    llm_deepseek_api_key: Optional[str] = None
    llm_openai_api_key: Optional[str] = None
    llm_groq_api_key: Optional[str] = None
    llm_mistral_api_key: Optional[str] = None
    llm_openrouter_api_key: Optional[str] = None
    llm_cohere_api_key: Optional[str] = None
    llm_kimi_api_key: Optional[str] = None
    llm_nemotron_api_key: Optional[str] = None
    llm_xai_api_key: Optional[str] = None


class ModelActivate(BaseModel):
    filename: str
    llm_model: Optional[str] = None


class ModelDelete(BaseModel):
    filename: str


class PromptCreate(BaseModel):
    prompt_key: str
    body: str
    title: Optional[str] = None


class TestPrompt(BaseModel):
    sender: str = Field(default="MPESA")
    messages: list[str] = Field(default_factory=lambda: [
        "Ksh 1,200.00 sent to John Doe for transaction XR4K9L2. New balance: Ksh 25,300.50. M-PESA.",
        "You have received Ksh 5,000.00 from SAFARICOM. New M-PESA balance is Ksh 30,300.50.",
    ])


@router.get("/status")
async def status():
    """Full backend status: health, config, model files, db, uptime."""
    db_ok = await verify_connection()

    llama_status = "unknown"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{settings.llm_base_url.rstrip('/')}/health")
            llama_status = "ok" if r.status_code == 200 else f"http_{r.status_code}"
    except Exception as e:
        llama_status = f"unreachable: {e.__class__.__name__}"

    models = _scan_models()

    auto_enabled = True
    try:
        await ensure_controls_table()
        auto_enabled = await is_auto_jobs_enabled()
    except Exception:
        pass

    return {
        "status": "ok",
        "auto_jobs_enabled": auto_enabled,
        "app": {
            "llm_engine": settings.llm_engine,
            "llm_provider": settings.llm_provider,
            "llm_model": settings.llm_model,
            "llm_max_tokens": settings.llm_max_tokens,
            "llm_temperature": settings.llm_temperature,
            "llm_ctx_size": settings.llm_ctx_size,
            "llm_batch_size": settings.llm_batch_size,
            "n_gpu_layers": settings.n_gpu_layers,
            "llm_base_url": settings.llm_base_url,
            "batch_size": settings.batch_size,
            "max_retries": settings.max_retries,
            "poll_interval": settings.poll_interval,
            "model_path": os.getenv("MODEL_PATH", ""),
            "llm_external_provider": settings.llm_external_provider,
            "llm_external_api_key": settings.llm_external_api_key,
            "llm_external_base_url": settings.llm_external_base_url,
            "llm_external_model": settings.llm_external_model,
            "llm_external_max_tokens": settings.llm_external_max_tokens,
            "llm_external_temperature": settings.llm_external_temperature,
            "external_batch_size": settings.external_batch_size,
            "external_max_retries": settings.external_max_retries,
            "external_poll_interval": settings.external_poll_interval,
            "llm_fallback_provider": settings.llm_fallback_provider,
            "llm_fallback_api_key": settings.llm_fallback_api_key,
            "llm_fallback_base_url": settings.llm_fallback_base_url,
            "llm_fallback_model": settings.llm_fallback_model,
            "llm_fallback_enabled": settings.llm_fallback_enabled,
            "llm_gemini_api_key": settings.llm_gemini_api_key,
            "llm_deepseek_api_key": settings.llm_deepseek_api_key,
            "llm_openai_api_key": settings.llm_openai_api_key,
            "llm_groq_api_key": settings.llm_groq_api_key,
            "llm_mistral_api_key": settings.llm_mistral_api_key,
            "llm_openrouter_api_key": settings.llm_openrouter_api_key,
            "llm_cohere_api_key": settings.llm_cohere_api_key,
            "llm_kimi_api_key": settings.llm_kimi_api_key,
            "llm_nemotron_api_key": settings.llm_nemotron_api_key,
            "llm_xai_api_key": settings.llm_xai_api_key,
        },
        "llama": llama_status,
        "db_configured": db_ok,
        "uptime": _uptime(),
        "models": models,
    }


@router.get("/models")
async def list_models():
    return {
        "models": _scan_models(),
        "active_model_path": os.getenv("MODEL_PATH", ""),
    }


@router.post("/config")
async def update_config(payload: ConfigUpdate):
    """Update in-memory config and persist to both database controls and env file.

    Database takes precedence on hot-reload. llama.cpp restart is required for GGUF model paths.
    """
    env_path = os.getenv("ENV_FILE", "/app/.env")
    changes: list[str] = []

    async def apply(key: str, value) -> None:
        setattr(settings, key, value)
        _set_env(key, str(value), env_path)
        try:
            await set_control(key, str(value))
        except Exception as e:
            logger.warning(f"Failed to persist control '{key}' to DB: {e}")
        changes.append(f"{key}={value}")

    if payload.llm_engine is not None:
        await apply("llm_engine", payload.llm_engine)
    if payload.llm_model is not None:
        await apply("llm_model", payload.llm_model)
    if payload.llm_max_tokens is not None:
        await apply("llm_max_tokens", payload.llm_max_tokens)
    if payload.llm_temperature is not None:
        await apply("llm_temperature", payload.llm_temperature)
    if payload.llm_ctx_size is not None:
        await apply("llm_ctx_size", payload.llm_ctx_size)
    if payload.llm_batch_size is not None:
        await apply("llm_batch_size", payload.llm_batch_size)
    if payload.n_gpu_layers is not None:
        await apply("n_gpu_layers", payload.n_gpu_layers)
    if payload.batch_size is not None:
        await apply("batch_size", payload.batch_size)
    if payload.max_retries is not None:
        await apply("max_retries", payload.max_retries)
    if payload.poll_interval is not None:
        await apply("poll_interval", payload.poll_interval)
    if payload.llm_provider is not None:
        await apply("llm_provider", payload.llm_provider)
    if payload.llm_api_key is not None:
        await apply("llm_api_key", payload.llm_api_key)
    if payload.llm_base_url is not None:
        await apply("llm_base_url", payload.llm_base_url)
    if payload.llm_external_provider is not None:
        await apply("llm_external_provider", payload.llm_external_provider)
    if payload.llm_external_api_key is not None:
        await apply("llm_external_api_key", payload.llm_external_api_key)
    if payload.llm_external_base_url is not None:
        await apply("llm_external_base_url", payload.llm_external_base_url)
    if payload.llm_external_model is not None:
        await apply("llm_external_model", payload.llm_external_model)
    if payload.llm_external_max_tokens is not None:
        await apply("llm_external_max_tokens", payload.llm_external_max_tokens)
    if payload.llm_external_temperature is not None:
        await apply("llm_external_temperature", payload.llm_external_temperature)
    if payload.external_batch_size is not None:
        await apply("external_batch_size", payload.external_batch_size)
    if payload.external_max_retries is not None:
        await apply("external_max_retries", payload.external_max_retries)
    if payload.external_poll_interval is not None:
        await apply("external_poll_interval", payload.external_poll_interval)
    if payload.llm_fallback_provider is not None:
        await apply("llm_fallback_provider", payload.llm_fallback_provider)
    if payload.llm_fallback_api_key is not None:
        await apply("llm_fallback_api_key", payload.llm_fallback_api_key)
    if payload.llm_fallback_base_url is not None:
        await apply("llm_fallback_base_url", payload.llm_fallback_base_url)
    if payload.llm_fallback_model is not None:
        await apply("llm_fallback_model", payload.llm_fallback_model)
    if payload.llm_fallback_enabled is not None:
        await apply("llm_fallback_enabled", payload.llm_fallback_enabled)
    if payload.llm_gemini_api_key is not None:
        await apply("llm_gemini_api_key", payload.llm_gemini_api_key)
    if payload.llm_deepseek_api_key is not None:
        await apply("llm_deepseek_api_key", payload.llm_deepseek_api_key)
    if payload.llm_openai_api_key is not None:
        await apply("llm_openai_api_key", payload.llm_openai_api_key)
    if payload.llm_groq_api_key is not None:
        await apply("llm_groq_api_key", payload.llm_groq_api_key)
    if payload.llm_mistral_api_key is not None:
        await apply("llm_mistral_api_key", payload.llm_mistral_api_key)
    if payload.llm_openrouter_api_key is not None:
        await apply("llm_openrouter_api_key", payload.llm_openrouter_api_key)
    if payload.llm_cohere_api_key is not None:
        await apply("llm_cohere_api_key", payload.llm_cohere_api_key)
    if payload.llm_kimi_api_key is not None:
        await apply("llm_kimi_api_key", payload.llm_kimi_api_key)
    if payload.llm_nemotron_api_key is not None:
        await apply("llm_nemotron_api_key", payload.llm_nemotron_api_key)
    if payload.llm_xai_api_key is not None:
        await apply("llm_xai_api_key", payload.llm_xai_api_key)

    return {
        "status": "ok",
        "applied": changes,
        "note": "Config saved to DB and env. Restart llama.cpp for local model path changes.",
    }
class ConnectionTest(BaseModel):
    provider: str
    base_url: str
    api_key: str
    model: str


@router.post("/test_connection")
async def test_connection(payload: ConnectionTest):
    """Test connection to an external LLM provider endpoint.

    Provider-aware: Gemini uses its native generateContent API,
    Cohere uses its own chat endpoint; all others use OpenAI-compat
    /chat/completions with Bearer auth.
    """
    import httpx

    provider = (payload.provider or "").lower().strip()
    api_key  = payload.api_key.strip()
    model    = payload.model.strip()
    base_url = payload.base_url.rstrip("/")

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:

            # ── Google Gemini (native REST) ────────────────────────────────
            if provider == "gemini":
                # Use the native generateContent endpoint — avoids the strict
                # rate limits imposed on the OpenAI-compat shim.
                gem_model = model if model else "gemini-1.5-flash"
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{gem_model}:generateContent"
                resp = await client.post(
                    url,
                    headers={
                        "Content-Type": "application/json",
                        "X-goog-api-key": api_key,
                    },
                    json={"contents": [{"parts": [{"text": "ping"}]}]},
                )
                resp.raise_for_status()
                res = resp.json()
                if "candidates" in res and len(res["candidates"]) > 0:
                    return {"status": "success", "message": "Connection successful! Gemini responded."}
                return {"status": "error", "message": f"Unexpected Gemini response: {res}"}

            # ── Cohere ─────────────────────────────────────────────────────
            if provider == "cohere":
                url = "https://api.cohere.com/v2/chat"
                resp = await client.post(
                    url,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {api_key}",
                    },
                    json={
                        "model": model or "command-r-plus",
                        "messages": [{"role": "user", "content": "ping"}],
                    },
                )
                resp.raise_for_status()
                res = resp.json()
                if "message" in res or "text" in res:
                    return {"status": "success", "message": "Connection successful! Cohere responded."}
                return {"status": "error", "message": f"Unexpected Cohere response: {res}"}

            # ── All OpenAI-compat providers ────────────────────────────────
            # (DeepSeek, OpenAI, Groq, Mistral, OpenRouter, Kimi, NVIDIA, x.ai, custom)
            url = f"{base_url}/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            }
            # Kimi requires a special origin header
            if provider == "kimi":
                headers["HTTP-Referer"] = "https://mpesa-analyzer.local"

            body = {
                "model": model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 5,
                "temperature": 0.0,
            }
            resp = await client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            res = resp.json()
            if "choices" in res and len(res["choices"]) > 0:
                return {"status": "success", "message": "Connection successful!"}
            return {"status": "error", "message": f"Invalid API response format: {res}"}

    except httpx.HTTPStatusError as e:
        status_code = e.response.status_code
        hints = {
            401: "Invalid or missing API key.",
            403: "API key lacks permission for this model/endpoint.",
            404: "Model or endpoint not found. Check the model name and base URL.",
            422: "Request rejected by the API — check model name and parameters.",
            429: "Rate limit hit. Wait a moment and try again, or check your quota.",
            500: "Provider internal error. Try again later.",
            503: "Provider overloaded or unavailable. Try again later.",
        }
        hint = hints.get(status_code, "")
        msg = f"HTTP {status_code}"
        if hint:
            msg += f" — {hint}"
        return {"status": "error", "message": f"Connection Failed\n{msg}"}
    except httpx.TimeoutException:
        return {"status": "error", "message": "Connection timed out (>20s). Check the base URL and your network."}
    except Exception as e:
        return {"status": "error", "message": f"Connection failed: {str(e)}"}


async def _restart_llama_server(model_path: str) -> str:
    """Terminates any running llama-server process and restarts it with the new model."""
    import shutil
    import subprocess

    llama_bin = shutil.which("llama-server") or "/usr/local/bin/llama-server"
    if not os.path.isfile(llama_bin) and not shutil.which("llama-server"):
        return "Model activated in database & configuration."

    try:
        subprocess.run(["pkill", "-f", "llama-server"], capture_output=True, timeout=5)
        await asyncio.sleep(1)

        port = os.getenv("LLAMA_PORT", "8080")
        ctx_size = str(settings.llm_ctx_size or 16384)
        batch_size = str(settings.llm_batch_size or 512)
        n_gpu = str(settings.n_gpu_layers or 0)

        cmd = [
            llama_bin,
            "--model", model_path,
            "--port", str(port),
            "--host", "0.0.0.0",
            "--ctx-size", str(ctx_size),
            "--batch-size", str(batch_size),
            "--n-gpu-layers", str(n_gpu),
            "--mlock",
        ]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        logger.info(f"Spawned llama-server with model {model_path} on port {port}")
        return "llama-server restarted with new model."
    except Exception as e:
        logger.warning(f"Could not auto-restart llama-server: {e}")
        return f"Model activated in database. (llama-server restart note: {e})"


@router.post("/models/activate")
async def activate_model(payload: ModelActivate):
    """Mark a model file as active by updating MODEL_PATH env, DB controls, and reloading llama-server."""
    model_dir = os.getenv("MODEL_DIR", "/models")
    full = os.path.join(model_dir, payload.filename)

    if not os.path.isfile(full):
        return {"status": "error", "message": f"Model file not found: {payload.filename}"}

    env_path = os.getenv("ENV_FILE", "/app/.env")
    _set_env("MODEL_PATH", full, env_path)
    os.environ["MODEL_PATH"] = full
    settings.model_path = full
    try:
        await set_control("model_path", full)
    except Exception as e:
        logger.warning(f"Failed to persist model_path control: {e}")

    llm_model_val = payload.llm_model or os.path.splitext(payload.filename)[0]
    _set_env("LLM_MODEL", llm_model_val, env_path)
    os.environ["LLM_MODEL"] = llm_model_val
    settings.llm_model = llm_model_val
    try:
        await set_control("llm_model", llm_model_val)
    except Exception as e:
        logger.warning(f"Failed to persist llm_model control: {e}")

    restart_msg = await _restart_llama_server(full)

    return {
        "status": "ok",
        "message": f"Model '{payload.filename}' is now active. {restart_msg}",
        "model_path": full,
        "llm_model": llm_model_val,
    }


@router.post("/models/upload")
async def upload_model(file: UploadFile = File(...)):
    """Upload a .gguf/.bin model file into MODEL_DIR."""
    allowed = {".gguf", ".bin"}
    filename = os.path.basename(file.filename or "")
    ext = os.path.splitext(filename)[1].lower()
    if ext not in allowed:
        await file.close()
        return {"status": "error", "message": f"Only {', '.join(sorted(allowed))} files are allowed."}

    model_dir = os.getenv("MODEL_DIR", "/models")
    if not os.path.isdir(model_dir):
        await file.close()
        return {"status": "error", "message": f"Model directory not found: {model_dir}"}

    dest = os.path.join(model_dir, filename)
    if os.path.exists(dest):
        await file.close()
        return {"status": "error", "message": f"A model named '{filename}' already exists."}

    total = 0
    try:
        with open(dest, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                out.write(chunk)
                total += len(chunk)
    except Exception as e:
        try:
            os.remove(dest)
        except Exception:
            pass
        await file.close()
        return {"status": "error", "message": f"Upload failed: {e}"}

    await file.close()
    logger.info(f"Uploaded model '{filename}' ({round(total/1024/1024,1)} MB)")
    return {
        "status": "ok",
        "message": f"'{filename}' uploaded ({round(total/1024/1024, 1)} MB). Restart llama.cpp to serve it.",
        "filename": filename,
        "size_mb": round(total / 1024 / 1024, 1),
    }


@router.post("/models/delete")
async def delete_model(payload: ModelDelete):
    """Delete a model file from MODEL_DIR. Active models cannot be deleted."""
    model_dir = os.getenv("MODEL_DIR", "/models")
    filename = os.path.basename(payload.filename)
    full = os.path.join(model_dir, filename)

    if not os.path.isfile(full):
        return {"status": "error", "message": f"Model file not found: {payload.filename}"}

    try:
        with open(full, "rb") as f:
            if f.read(4) != b"GGUF":
                return {"status": "error", "message": "Refusing to delete non-GGUF file."}
    except Exception as e:
        return {"status": "error", "message": f"Could not verify file: {e}"}

    active_path = getattr(settings, "model_path", None) or os.getenv("MODEL_PATH", "")
    if full == active_path or filename == os.path.basename(active_path):
        return {"status": "error", "message": f"'{filename}' is the active model; activate another model first."}

    try:
        os.remove(full)
    except Exception as e:
        return {"status": "error", "message": f"Delete failed: {e}"}

    logger.info(f"Deleted model '{filename}'")
    return {"status": "ok", "message": f"'{filename}' deleted.", "filename": filename}


_download_tasks: dict[str, dict] = {}


async def _stream_download_task(task_id: str, url: str, dest_path: str, hf_token: Optional[str] = None):
    headers = {"User-Agent": "MpesaAnalyzer/1.0"}
    if hf_token:
        headers["Authorization"] = f"Bearer {hf_token}"

    temp_path = dest_path + ".download"
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(900.0, connect=30.0)) as client:
            async with client.stream("GET", url, headers=headers) as resp:
                if resp.status_code >= 400:
                    _download_tasks[task_id]["status"] = "error"
                    _download_tasks[task_id]["message"] = f"HTTP {resp.status_code}: {resp.reason_phrase}"
                    return

                total_str = resp.headers.get("content-length")
                total = int(total_str) if total_str and total_str.isdigit() else 0
                _download_tasks[task_id]["total_bytes"] = total
                received = 0

                with open(temp_path, "wb") as out:
                    async for chunk in resp.aiter_bytes(chunk_size=1024 * 512):
                        out.write(chunk)
                        received += len(chunk)
                        _download_tasks[task_id]["bytes_received"] = received
                        if total > 0:
                            _download_tasks[task_id]["progress_pct"] = round((received / total) * 100, 1)
                        else:
                            _download_tasks[task_id]["progress_pct"] = 0.0

                if os.path.exists(dest_path):
                    os.remove(dest_path)
                os.rename(temp_path, dest_path)
                _download_tasks[task_id]["status"] = "done"
                _download_tasks[task_id]["progress_pct"] = 100.0
                _download_tasks[task_id]["size_mb"] = round(received / (1024 * 1024), 1)
                _download_tasks[task_id]["message"] = f"'{os.path.basename(dest_path)}' downloaded successfully."
                logger.info(f"Downloaded model '{os.path.basename(dest_path)}' ({round(received / (1024 * 1024), 1)} MB)")
    except Exception as e:
        logger.error(f"Download failed for task {task_id}: {e}")
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        _download_tasks[task_id]["status"] = "error"
        _download_tasks[task_id]["message"] = f"Download failed: {e}"


@router.post("/models/download")
async def download_model(payload: ModelDownloadRequest):
    """Initiate a background download of a .gguf/.bin model from a URL or Hugging Face."""
    url = (payload.url or "").strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        return {"status": "error", "message": "URL must start with http:// or https://"}

    filename = (payload.filename or "").strip()
    if not filename:
        from urllib.parse import unquote, urlparse
        parsed = urlparse(url)
        path = unquote(parsed.path)
        filename = os.path.basename(path)

    filename = os.path.basename(filename)
    allowed = {".gguf", ".bin"}
    ext = os.path.splitext(filename)[1].lower()
    if ext not in allowed:
        return {"status": "error", "message": f"Filename must end with .gguf or .bin. Detected: '{filename}'"}

    model_dir = os.getenv("MODEL_DIR", "/models")
    if not os.path.isdir(model_dir):
        os.makedirs(model_dir, exist_ok=True)

    dest = os.path.join(model_dir, filename)
    if os.path.exists(dest):
        return {"status": "error", "message": f"A model file named '{filename}' already exists."}

    import asyncio
    import uuid
    task_id = uuid.uuid4().hex[:12]
    _download_tasks[task_id] = {
        "task_id": task_id,
        "status": "downloading",
        "filename": filename,
        "progress_pct": 0.0,
        "bytes_received": 0,
        "total_bytes": 0,
        "message": "Download in progress...",
    }

    asyncio.create_task(_stream_download_task(task_id, url, dest, payload.hf_token))

    return {
        "status": "started",
        "task_id": task_id,
        "filename": filename,
        "message": f"Started background download of '{filename}'.",
    }


@router.get("/models/download/{task_id}")
async def get_download_status(task_id: str):
    """Check progress of a background model download task."""
    task = _download_tasks.get(task_id)
    if not task:
        return {"status": "error", "message": f"Download task '{task_id}' not found."}
    return task



# ── Prompt version management ─────────────────────────────


@router.get("/allowed/defaults")
async def allowed_defaults():
    """The hardcoded default finance senders the backend falls back to.

    These are the "preselected good senders" baked into the ML code. They apply
    whenever tbl_Allowed_Senders is empty (or on DB failure). Exposing them lets
    the webapp show them even before the user has uploaded matching data.
    """
    return {
        "defaults": [
            {"sender": s, "category": cat}
            for cat, senders in FINANCE_CATEGORIES.items()
            for s in sorted(senders)
        ],
        "categories": list(FINANCE_CATEGORIES.keys()),
    }


@router.get("/prompts")
async def list_prompts():
    """List prompt versions + current resolution per key.

    For each key we report whether it is using an active DB prompt or the
    hardcoded default (fallback), alongside the default template text.
    """
    try:
        await ensure_prompts_table()
        rows = await get_all_prompts()
    except Exception as e:
        logger.error(f"Failed to load prompts: {e}")
        return {"keys": list(DEFAULT_PROMPTS.keys()), "prompts": [], "resolved": {}, "error": str(e)}

    resolved = {}
    for key in DEFAULT_PROMPTS:
        active = await get_active_prompt(key) if rows else None
        resolved[key] = {
            "key": key,
            "using_db": active is not None,
            "active": active,
            "default": DEFAULT_PROMPTS[key],
        }

    return {"keys": list(DEFAULT_PROMPTS.keys()), "prompts": rows, "resolved": resolved}


@router.post("/prompts")
async def create_prompt(payload: PromptCreate):
    """Create a new prompt version for a key and make it active.

    "Editing" an existing prompt is the same operation — it simply produces a
    new version. The previous active version is deactivated.
    """
    key = payload.prompt_key
    if key not in DEFAULT_PROMPTS:
        return {"status": "error", "message": f"Unknown prompt key '{key}'. Allowed: {', '.join(DEFAULT_PROMPTS)}"}

    body = payload.body.strip()
    if not body:
        return {"status": "error", "message": "Prompt body cannot be empty."}

    await ensure_prompts_table()
    await deactivate_prompts(key)
    version = await get_max_version(key) + 1
    prompt_id = await insert_prompt(key, (payload.title or "").strip(), body, version, 1)

    logger.info(f"Created prompt '{key}' v{version} (id={prompt_id}) and set active")
    return {
        "status": "ok",
        "message": f"Created version v{version} for '{key}' and set it active.",
        "id": prompt_id,
        "version": version,
    }


@router.post("/prompts/{prompt_id}/activate")
async def activate_prompt(prompt_id: int):
    """Switch the active version of a key to an existing prompt version."""
    try:
        await ensure_prompts_table()
        prompts = await get_all_prompts()
    except Exception as e:
        return {"status": "error", "message": f"Could not load prompts: {e}"}

    target = next((p for p in prompts if p["id"] == prompt_id), None)
    if not target:
        return {"status": "error", "message": "Prompt not found."}

    await set_prompt_active(prompt_id, target["prompt_key"])
    return {"status": "ok", "message": f"Prompt v{target['version']} for '{target['prompt_key']}' is now active."}


@router.post("/prompts/{prompt_id}/delete")
async def delete_prompt_endpoint(prompt_id: int):
    """Delete a prompt version. Active versions cannot be deleted."""
    try:
        await ensure_prompts_table()
        prompts = await get_all_prompts()
    except Exception as e:
        return {"status": "error", "message": f"Could not load prompts: {e}"}

    target = next((p for p in prompts if p["id"] == prompt_id), None)
    if not target:
        return {"status": "error", "message": "Prompt not found."}
    if target["is_active"]:
        return {"status": "error", "message": "Cannot delete the active prompt; activate another version first."}

    await delete_prompt(prompt_id)
    return {"status": "ok", "message": f"Deleted v{target['version']} for '{target['prompt_key']}'."}


@router.post("/test-prompt")
async def test_prompt(payload: TestPrompt):
    """Run a classification + extraction on sample messages to verify the LLM."""
    started = datetime.now(timezone.utc)
    try:
        classification = await SenderClassifier.classify(payload.sender, payload.messages)
        extraction = await MessageExtractor.extract_batch(payload.messages)
    except Exception as e:
        logger.error(f"Test prompt failed: {e}")
        return {"status": "error", "message": str(e)}

    elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)

    return {
        "status": "ok",
        "elapsed_ms": elapsed_ms,
        "classification": classification.model_dump(),
        "extractions": [e.model_dump() if e else None for e in extraction],
    }


def _scan_models() -> list[dict]:
    """List model files in MODEL_DIR, enriched with GGUF metadata."""
    model_dir = os.getenv("MODEL_DIR", "/models")
    active_path = getattr(settings, "model_path", None) or os.getenv("MODEL_PATH", "")
    models = []
    try:
        if os.path.isdir(model_dir):
            for f in sorted(os.listdir(model_dir)):
                if f.lower().endswith((".gguf", ".bin")):
                    full = os.path.join(model_dir, f)
                    is_active = (f == os.path.basename(active_path) or full == active_path)
                    models.append({
                        "filename": f,
                        "size_mb": round(os.path.getsize(full) / 1024 / 1024, 1),
                        "active": is_active,
                        "metadata": read_gguf_metadata(full),
                    })
    except Exception as e:
        logger.error(f"Failed to list models: {e}")
    return models


# ── Job controls (auto on/off) ─────────────────────────────


class JobToggle(BaseModel):
    enabled: bool


@router.get("/jobs/status")
async def job_status():
    """Auto-jobs toggle state + summary of recent processing jobs."""
    try:
        await ensure_controls_table()
        enabled = await is_auto_jobs_enabled()
        jobs = await fetch_jobs(limit=50)
    except Exception as e:
        logger.error(f"Failed to load job status: {e}")
        return {"auto_enabled": True, "jobs": [], "error": str(e)}

    # Aggregate metadata across recent jobs (for the admin overview).
    totals = {
        "jobs": len(jobs),
        "messages_processed": 0,
        "sms_total": 0,
        "sms_finance": 0,
        "sms_unwanted": 0,
        "senders_total": 0,
        "senders_finance": 0,
        "senders_unwanted": 0,
        "errors": 0,
    }
    for j in jobs:
        m = j.get("metadata") or {}
        if isinstance(m, str):
            try:
                m = json.loads(m)
            except Exception:
                m = {}
        totals["messages_processed"] += int(m.get("messages_processed", j.get("messages_processed") or 0))
        totals["sms_total"] += int(m.get("sms_total", 0))
        totals["sms_finance"] += int(m.get("sms_finance", 0))
        totals["sms_unwanted"] += int(m.get("sms_unwanted", 0))
        totals["senders_total"] += int(m.get("senders_total", 0))
        totals["senders_finance"] += int(m.get("senders_finance", 0))
        totals["senders_unwanted"] += int(m.get("senders_unwanted", 0))
        totals["errors"] += int(m.get("errors", j.get("errors") or 0))

    return {
        "auto_enabled": enabled,
        "totals": totals,
        "jobs": jobs,
    }


@router.post("/jobs/auto")
async def toggle_jobs(payload: JobToggle):
    """Enable or disable the background auto-processing poller."""
    try:
        await ensure_controls_table()
        await set_control("auto_jobs_enabled", "1" if payload.enabled else "0")
    except Exception as e:
        logger.error(f"Failed to set auto-jobs toggle: {e}")
        return {"status": "error", "message": f"Failed to persist toggle: {e}"}

    logger.info(f"Auto jobs {'ENABLED' if payload.enabled else 'DISABLED'} by admin")
    return {
        "status": "ok",
        "auto_enabled": payload.enabled,
        "message": f"Auto jobs {'enabled' if payload.enabled else 'disabled'}. "
                   + ("New jobs will run on the next poll cycle." if payload.enabled
                      else "No ML jobs will run until re-enabled."),
    }


@router.get("/jobs")
async def list_jobs():
    """Recent processing jobs with full metadata."""
    try:
        await ensure_jobs_table()
        jobs = await fetch_jobs(limit=200)
    except Exception as e:
        logger.error(f"Failed to list jobs: {e}")
        return {"jobs": [], "error": str(e)}

    for j in jobs:
        m = j.get("metadata")
        if isinstance(m, str):
            try:
                j["metadata"] = json.loads(m)
            except Exception:
                j["metadata"] = None

    return {"jobs": jobs}


def _uptime() -> Optional[float]:
    try:
        with open("/proc/uptime", "r") as f:
            return float(f.read().split()[0])
    except Exception:
        return None


def _set_env(key: str, value: str, path: str) -> None:
    """Update or append a KEY=VALUE line in the given env file."""
    try:
        if os.path.isfile(path):
            with open(path, "r") as f:
                lines = f.readlines()
        else:
            lines = []

        found = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(key + "="):
                lines[i] = f"{key}={value}\n"
                found = True
                break

        if not found:
            lines.append(f"{key}={value}\n")

        with open(path, "w") as f:
            f.writelines(lines)
    except Exception as e:
        logger.error(f"Failed to update env file {path}: {e}")
