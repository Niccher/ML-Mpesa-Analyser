from __future__ import annotations

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class Direction(str, Enum):
    sent = "sent"
    received = "received"
    none_ = "none"


class TransactionType(str, Enum):
    transfer = "transfer"
    payment = "payment"
    deposit = "deposit"
    withdrawal = "withdrawal"
    loan = "loan"
    repayment = "repayment"
    salary = "salary"
    fee = "fee"
    interest = "interest"
    refund = "refund"
    other = "other"
    unknown = "unknown"


class FinanceCategory(str, Enum):
    mobile_money = "Mobile Money"
    bank = "Bank"
    sacco = "SACCO"
    fintech = "Fintech"
    insurance = "Insurance"
    payments_govt = "Payments/Govt"
    other_finance = "Other Finance"
    non_finance = "Non-Finance"


# ── Sender Classification ──────────────────────────────────


class SenderClassification(BaseModel):
    sender: str
    is_finance: bool
    confidence: float = Field(ge=0.0, le=1.0)
    category: FinanceCategory
    reasoning: str


# ── Per-Message Extraction ─────────────────────────────────


class MessageExtraction(BaseModel):
    body: str
    is_transactional: bool
    amount_before: Optional[float] = None
    amount_after: Optional[float] = None
    amount_changed: Optional[float] = None
    direction: Direction
    transaction_time: Optional[str] = None
    counterparty: Optional[str] = None
    transaction_reference: Optional[str] = None
    transaction_type: TransactionType = TransactionType.unknown


# ── Mode A (API) I/O ───────────────────────────────────────


class ModeARequest(BaseModel):
    messages: dict[str, list[str]] = Field(
        description="Map of sender → list of SMS body strings"
    )


class ModeAResult(BaseModel):
    sender: str
    classification: SenderClassification
    extractions: list[MessageExtraction]


class ModeAResponse(BaseModel):
    results: list[ModeAResult]
    summary: dict = Field(
        default_factory=lambda: {
            "total_senders": 0,
            "finance_senders": 0,
            "total_messages": 0,
            "transactional_messages": 0,
        }
    )


# ── Mode B (DB) I/O ────────────────────────────────────────


class ModeBRequest(BaseModel):
    batch_size: Optional[int] = None


class ModeBResponse(BaseModel):
    senders_classified: int
    messages_processed: int
    finance_senders_found: int
    transactional_inserted: int
    errors: int


# ── Health ──────────────────────────────────────────────────


class HealthResponse(BaseModel):
    status: str
    llm_provider: str
    llm_model: str
    db_configured: bool


class ProcessingJobResponse(BaseModel):
    job_id: int
    user_id: str
    status: str
    messages_processed: int = 0
    errors: int = 0
    duration_seconds: Optional[int] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
