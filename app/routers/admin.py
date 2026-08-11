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
from app.services.classifier import SenderClassifier
from app.services.extractor import MessageExtractor
from app.services.gguf_metadata import read_gguf_metadata
from app.utils.prompt_templates import DEFAULT_PROMPTS, FINANCE_CATEGORIES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


class ConfigUpdate(BaseModel):
    llm_model: Optional[str] = None
    llm_max_tokens: Optional[int] = Field(default=None, ge=256, le=8192)
    llm_temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    llm_ctx_size: Optional[int] = Field(default=None, ge=256, le=131072)
    llm_batch_size: Optional[int] = Field(default=None, ge=1, le=8192)
    n_gpu_layers: Optional[int] = Field(default=None, ge=0, le=512)
    batch_size: Optional[int] = Field(default=None, ge=1, le=500)
    max_retries: Optional[int] = Field(default=None, ge=0, le=10)
    poll_interval: Optional[int] = Field(default=None, ge=5, le=3600)


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
    """Update in-memory config. Note: llama.cpp restart is required for model changes."""
    env_path = os.getenv("ENV_FILE", "/app/.env")
    changes: list[str] = []

    def apply(key: str, value) -> None:
        setattr(settings, key, value)
        _set_env(key, value, env_path)
        changes.append(f"{key}={value}")

    if payload.llm_model is not None:
        apply("llm_model", payload.llm_model)
    if payload.llm_max_tokens is not None:
        apply("llm_max_tokens", payload.llm_max_tokens)
    if payload.llm_temperature is not None:
        apply("llm_temperature", payload.llm_temperature)
    if payload.llm_ctx_size is not None:
        apply("llm_ctx_size", payload.llm_ctx_size)
    if payload.llm_batch_size is not None:
        apply("llm_batch_size", payload.llm_batch_size)
    if payload.n_gpu_layers is not None:
        apply("n_gpu_layers", payload.n_gpu_layers)
    if payload.batch_size is not None:
        apply("batch_size", payload.batch_size)
    if payload.max_retries is not None:
        apply("max_retries", payload.max_retries)
    if payload.poll_interval is not None:
        apply("poll_interval", payload.poll_interval)

    return {
        "status": "ok",
        "applied": changes,
        "note": "Restart llama.cpp for model changes to take effect.",
    }


@router.post("/models/activate")
async def activate_model(payload: ModelActivate):
    """Mark a model file as active by updating MODEL_PATH env + .env file.

    A llama.cpp restart is required for the new model to be served.
    """
    model_dir = os.getenv("MODEL_DIR", "/models")
    full = os.path.join(model_dir, payload.filename)

    if not os.path.isfile(full):
        return {"status": "error", "message": f"Model file not found: {payload.filename}"}

    env_path = os.getenv("ENV_FILE", "/app/.env")
    _set_env("MODEL_PATH", full, env_path)
    if payload.llm_model:
        _set_env("LLM_MODEL", payload.llm_model, env_path)
        settings.llm_model = payload.llm_model

    return {
        "status": "ok",
        "message": f"Model '{payload.filename}' set active. Restart llama.cpp to load it.",
        "model_path": full,
        "llm_model": payload.llm_model or settings.llm_model,
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

    active_path = os.getenv("MODEL_PATH", "")
    if full == active_path or filename == os.path.basename(active_path):
        return {"status": "error", "message": f"'{filename}' is the active model; activate another model first."}

    try:
        os.remove(full)
    except Exception as e:
        return {"status": "error", "message": f"Delete failed: {e}"}

    logger.info(f"Deleted model '{filename}'")
    return {"status": "ok", "message": f"'{filename}' deleted.", "filename": filename}


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
    active_path = os.getenv("MODEL_PATH", "")
    models = []
    try:
        if os.path.isdir(model_dir):
            for f in sorted(os.listdir(model_dir)):
                if f.lower().endswith((".gguf", ".bin")):
                    full = os.path.join(model_dir, f)
                    models.append({
                        "filename": f,
                        "size_mb": round(os.path.getsize(full) / 1024 / 1024, 1),
                        "active": f == os.path.basename(active_path),
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
