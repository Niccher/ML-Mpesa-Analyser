from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Optional

from sqlalchemy import text

from app.db.connection import get_engine

logger = logging.getLogger(__name__)


def _parse_date_to_mysql(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    raw = raw.strip().lower()

    # Kenyan formats: "9/7/26 at 6:14 am", "15/7/2026 at 10:30", "9/7/2026"
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2,4})\s+at\s+(\d{1,2}):(\d{2})\s*(am|pm)", raw)
    if m:
        d, mo, y, h, mi, ap = m.groups()
        if len(y) == 2:
            y = "20" + y
        h = int(h)
        if ap == "pm" and h != 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
        return f"{y}-{int(mo):02d}-{int(d):02d} {h:02d}:{mi}:00"

    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", raw)
    if m:
        d, mo, y = m.groups()
        if len(y) == 2:
            y = "20" + y
        return f"{y}-{int(mo):02d}-{int(d):02d}"

    return None


# ── Read unprocessed SMS (Mode B) ─────────────────────────


async def fetch_unprocessed_sms(batch_size: int) -> list[dict]:
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text("""
                SELECT s.id, s.sms_number, s.sms_body, s.sms_owner, s.sms_time
                FROM tbl_Sms s
                LEFT JOIN tbl_Sms_Processing p ON p.sms_id = s.id
                WHERE (p.sms_id IS NULL OR p.status = 'error')
                ORDER BY s.id ASC
                LIMIT :limit
            """),
            {"limit": batch_size},
        )
        rows = result.fetchall()
        return [
            {
                "id": row[0],
                "sms_number": row[1] or "",
                "sms_body": row[2] or "",
                "sms_owner": row[3] or "",
                "sms_time": row[4] or "",
            }
            for row in rows
        ]


# ── Tracking table helpers ─────────────────────────────────


async def ensure_tracking_table():
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS tbl_Sms_Processing (
                    sms_id INT PRIMARY KEY,
                    status VARCHAR(20) DEFAULT 'pending',
                    attempt_count INT DEFAULT 0,
                    last_error TEXT NULL,
                    processed_at DATETIME NULL,
                    INDEX idx_status (status)
                )
            """)
        )
        await conn.commit()


async def mark_processing(sms_id: int, status: str, error: Optional[str] = None):
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(
            text("""
                INSERT INTO tbl_Sms_Processing (sms_id, status, attempt_count, last_error, processed_at)
                VALUES (:sid, :status, 1, :error, NOW())
                ON DUPLICATE KEY UPDATE
                    status = :status2,
                    attempt_count = attempt_count + 1,
                    last_error = :error2,
                    processed_at = NOW()
            """),
            {
                "sid": sms_id,
                "status": status,
                "error": error,
                "status2": status,
                "error2": error,
            },
        )
        await conn.commit()


# ── Write parsed data ──────────────────────────────────────


async def upsert_sms_analysis(
    sms_id: int,
    direction: Optional[str],
    amount: Optional[float],
    balance: Optional[float],
    counterparty: Optional[str],
    transaction_type: Optional[str],
    is_transactional: bool,
    category: Optional[str],
    is_finance: Optional[bool],
    confidence: Optional[float],
    method: Optional[str],
    trans_date: Optional[str] = None,
):
    """Single canonical write: persist classification + parsed data to tbl_Sms.

    tbl_Sms is the single source of truth for per-SMS analysis. The old
    tbl_Sms_Classification and tbl_Analyzed_Transactions tables are now VIEWs
    derived from tbl_Sms, so they must not be written to directly.
    """
    parsed_date = _parse_date_to_mysql(trans_date) if trans_date else None

    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(
            text("""
                UPDATE tbl_Sms
                SET
                    sms_direction = :direction,
                    sms_amount = :amount,
                    sms_balance = :balance,
                    sms_counterparty = :counterparty,
                    sms_transaction_type = :transaction_type,
                    sms_is_transactional = :is_transactional,
                    sms_category = :category,
                    sms_is_finance = :is_finance,
                    sms_confidence = :confidence,
                    sms_method = :method,
                    sms_trans_date = :trans_date
                WHERE id = :sid
            """),
            {
                "sid": sms_id,
                "direction": direction,
                "amount": amount,
                "balance": balance,
                "counterparty": counterparty,
                "transaction_type": transaction_type,
                "is_transactional": 1 if is_transactional else 0,
                "category": category,
                "is_finance": 1 if is_finance else 0,
                "confidence": confidence,
                "method": method,
                "trans_date": parsed_date,
            },
        )
        await conn.commit()


# ── Sender profile helpers ─────────────────────────────────


async def upsert_sender_profile(
    owner: str,
    number: str,
    name: str,
    category: str,
    is_finance: bool,
    confidence: float,
):
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(
            text("""
                INSERT INTO tbl_Sender_Profiles
                    (sp_owner, sp_number, sp_name, sp_category, sp_is_finance, sp_confidence, sp_created, sp_updated)
                VALUES
                    (:owner, :number, :name, :category, :is_finance, :confidence, NOW(), NOW())
                ON DUPLICATE KEY UPDATE
                    sp_name = VALUES(sp_name),
                    sp_category = VALUES(sp_category),
                    sp_is_finance = VALUES(sp_is_finance),
                    sp_confidence = VALUES(sp_confidence),
                    sp_updated = NOW()
            """),
            {
                "owner": owner,
                "number": number,
                "name": name,
                "category": category,
                "is_finance": 1 if is_finance else 0,
                "confidence": confidence,
            },
        )
        await conn.commit()


async def get_sender_profile(owner: str, number: str) -> Optional[dict]:
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text("""
                SELECT * FROM tbl_Sender_Profiles
                WHERE sp_owner = :owner AND sp_number = :number
            """),
            {"owner": owner, "number": number},
        )
        row = result.fetchone()
        if row:
            return dict(row._mapping)
        return None


async def get_processed_sender_numbers(owner: str) -> set[str]:
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text("""
                SELECT DISTINCT sp_number FROM tbl_Sender_Profiles
                WHERE sp_owner = :owner AND sp_is_finance = 1
            """),
            {"owner": owner},
        )
        return {row[0] for row in result.fetchall()}


async def get_allowed_senders() -> dict[str, Optional[str]]:
    """Global "allowed by default" finance senders from tbl_Allowed_Senders.

    Returns a map of upper-cased sender -> category. The caller falls back to
    the hardcoded list when this table is empty (or on any DB error).
    """
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT sender, category FROM tbl_Allowed_Senders")
        )
        return {row[0].upper(): row[1] for row in result.fetchall()}


# ── Prompt version management ─────────────────────────────


async def ensure_prompts_table():
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS tbl_LLM_Prompts (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    prompt_key VARCHAR(50) NOT NULL,
                    version INT NOT NULL,
                    title VARCHAR(255) NOT NULL DEFAULT '',
                    body TEXT NOT NULL,
                    is_active TINYINT(1) DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uq_key_version (prompt_key, version),
                    KEY idx_key_active (prompt_key, is_active)
                )
            """)
        )
        await conn.commit()


async def get_all_prompts() -> list[dict]:
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text("""
                SELECT id, prompt_key, version, title, body, is_active, created_at
                FROM tbl_LLM_Prompts
                ORDER BY prompt_key ASC, version DESC
            """)
        )
        return [dict(row._mapping) for row in result.fetchall()]


async def get_active_prompt(key: str) -> Optional[str]:
    """Return the body of the active prompt for a key, or None."""
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text("""
                SELECT body FROM tbl_LLM_Prompts
                WHERE prompt_key = :k AND is_active = 1
                ORDER BY version DESC LIMIT 1
            """),
            {"k": key},
        )
        row = result.fetchone()
        return row[0] if row else None


async def get_max_version(key: str) -> int:
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text("""
                SELECT COALESCE(MAX(version), 0) FROM tbl_LLM_Prompts WHERE prompt_key = :k
            """),
            {"k": key},
        )
        return int(result.scalar_one())


async def deactivate_prompts(key: str):
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(
            text("UPDATE tbl_LLM_Prompts SET is_active = 0 WHERE prompt_key = :k"),
            {"k": key},
        )
        await conn.commit()


async def insert_prompt(key: str, title: str, body: str, version: int, is_active: int = 1) -> int:
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text("""
                INSERT INTO tbl_LLM_Prompts (prompt_key, version, title, body, is_active, created_at)
                VALUES (:k, :v, :t, :b, :a, NOW())
            """),
            {"k": key, "v": version, "t": title, "b": body, "a": is_active},
        )
        await conn.commit()
        return result.lastrowid


async def set_prompt_active(prompt_id: int, key: str):
    await deactivate_prompts(key)
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(
            text("UPDATE tbl_LLM_Prompts SET is_active = 1 WHERE id = :id"),
            {"id": prompt_id},
        )
        await conn.commit()


async def delete_prompt(prompt_id: int):
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(
            text("DELETE FROM tbl_LLM_Prompts WHERE id = :id"),
            {"id": prompt_id},
        )
        await conn.commit()


# ── Job controls (admin auto on/off) ───────────────────────


async def ensure_controls_table():
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS tbl_ML_Controls (
                    control_key VARCHAR(50) PRIMARY KEY,
                    control_value VARCHAR(255) NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                )
            """)
        )
        await conn.commit()


async def get_control(key: str, default: str = "") -> str:
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT control_value FROM tbl_ML_Controls WHERE control_key = :k"),
                {"k": key},
            )
            row = result.fetchone()
            return row[0] if row else default
    except Exception as e:
        logger.warning(f"Could not read control '{key}' ({e}); using default.")
        return default


async def set_control(key: str, value: str):
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(
            text("""
                INSERT INTO tbl_ML_Controls (control_key, control_value)
                VALUES (:k, :v)
                ON DUPLICATE KEY UPDATE control_value = VALUES(control_value)
            """),
            {"k": key, "v": value},
        )
        await conn.commit()


async def is_auto_jobs_enabled() -> bool:
    """Whether the background poller / auto jobs may run."""
    value = await get_control("auto_jobs_enabled", "1")
    return value.lower() in {"1", "true", "yes", "on"}


# ── User-triggered processing jobs ─────────────────────────


async def ensure_jobs_table():
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS tbl_Processing_Jobs (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id VARCHAR(100) NOT NULL,
                    status VARCHAR(20) DEFAULT 'queued',
                    started_at DATETIME NULL,
                    completed_at DATETIME NULL,
                    duration_seconds INT NULL,
                    messages_processed INT DEFAULT 0,
                    errors INT DEFAULT 0,
                    metadata JSON NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_user_status (user_id, status)
                )
            """)
        )
        # Add metadata column on legacy tables (MySQL 8: check before ALTER).
        col = await conn.execute(
            text("""
                SELECT COUNT(*) FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tbl_Processing_Jobs'
                  AND COLUMN_NAME = 'metadata'
            """)
        )
        if col.scalar_one() == 0:
            await conn.execute(text("ALTER TABLE tbl_Processing_Jobs ADD COLUMN metadata JSON NULL"))
        await conn.commit()


async def create_job(user_id: str) -> int:
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text("""
                INSERT INTO tbl_Processing_Jobs (user_id, status, created_at)
                VALUES (:user_id, 'queued', NOW())
            """),
            {"user_id": user_id},
        )
        await conn.commit()
        return result.lastrowid


async def update_job(job_id: int, **kwargs):
    sets = []
    params: dict = {"id": job_id}
    for key, val in kwargs.items():
        sets.append(f"{key} = :{key}")
        if isinstance(val, (dict, list)):
            params[key] = json.dumps(val)
        else:
            params[key] = val
    if not sets:
        return
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(
            text(f"UPDATE tbl_Processing_Jobs SET {', '.join(sets)} WHERE id = :id"),
            params,
        )
        await conn.commit()


async def fetch_jobs(limit: int = 100) -> list[dict]:
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text("""
                SELECT id, user_id, status, started_at, completed_at,
                       duration_seconds, messages_processed, errors, metadata, created_at
                FROM tbl_Processing_Jobs
                ORDER BY id DESC
                LIMIT :limit
            """),
            {"limit": limit},
        )
        return [dict(row._mapping) for row in result.fetchall()]


async def fetch_unprocessed_sms_by_owner(owner: str, batch_size: int) -> list[dict]:
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text("""
                SELECT s.id, s.sms_number, s.sms_body, s.sms_owner, s.sms_time
                FROM tbl_Sms s
                LEFT JOIN tbl_Sms_Processing p ON p.sms_id = s.id
                WHERE (p.sms_id IS NULL OR p.status = 'error')
                  AND s.sms_owner = :owner
                ORDER BY s.id ASC
                LIMIT :limit
            """),
            {"owner": owner, "limit": batch_size},
        )
        rows = result.fetchall()
        return [
            {
                "id": row[0],
                "sms_number": row[1] or "",
                "sms_body": row[2] or "",
                "sms_owner": row[3] or "",
                "sms_time": row[4] or "",
            }
            for row in rows
        ]
