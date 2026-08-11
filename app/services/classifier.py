from __future__ import annotations

import logging
from typing import Optional

from app.db.queries import get_allowed_senders
from app.models.schemas import FinanceCategory, SenderClassification
from app.services.llm_service import llm
from app.utils.prompt_templates import FINANCE_CATEGORIES

logger = logging.getLogger(__name__)


class SenderClassifier:
    # Hardcoded fallback list. Used only when tbl_Allowed_Senders is empty
    # (or unreadable). The DB list takes precedence when it has entries.
    KNOWN_FINANCE: dict[str, FinanceCategory] = {}

    @classmethod
    def _build_hardcoded(cls):
        for cat, senders in FINANCE_CATEGORIES.items():
            for s in senders:
                cls.KNOWN_FINANCE[s.upper()] = FinanceCategory(cat)

    @classmethod
    async def reload_allowed(cls) -> None:
        """Refresh the known-finance lookup from the DB.

        DB first; if the table is empty or the query fails, fall back to the
        hardcoded FINANCE_CATEGORIES.
        """
        try:
            db_allowed = await get_allowed_senders()
            if db_allowed:
                cls.KNOWN_FINANCE = {
                    sender: FinanceCategory(cat) if cat else FinanceCategory("Other Finance")
                    for sender, cat in db_allowed.items()
                }
                logger.info(f"Using {len(db_allowed)} allowed senders from DB.")
                return
            logger.info("Allowed senders table empty — using hardcoded fallback list.")
        except Exception as e:
            logger.warning(f"Could not load allowed senders from DB ({e}); using hardcoded fallback.")
        cls.KNOWN_FINANCE = {}
        cls._build_hardcoded()

    @classmethod
    async def classify(
        cls, sender: str, sms_messages: list[str]
    ) -> SenderClassification:
        sender_upper = sender.upper().strip()

        # If sender is in the allowed list (DB or hardcoded fallback), return
        # immediately as finance — skip LLM classification. Extraction still
        # runs for finance senders downstream.
        if sender_upper in cls.KNOWN_FINANCE:
            cat = cls.KNOWN_FINANCE[sender_upper]
            return SenderClassification(
                sender=sender,
                is_finance=True,
                confidence=0.95,
                category=cat,
                reasoning=f"Known {cat.value} sender.",
            )

        # No SMS content to classify
        if not sms_messages:
            return SenderClassification(
                sender=sender,
                is_finance=False,
                confidence=0.0,
                category=FinanceCategory.non_finance,
                reasoning="No SMS content to analyze.",
            )

        # Use LLM for classification
        try:
            result = await llm.classify_sender(sender, sms_messages)
            return SenderClassification(
                sender=result.get("sender", sender),
                is_finance=bool(result.get("is_finance", False)),
                confidence=float(result.get("confidence", 0.0)),
                category=FinanceCategory(result.get("category", "Non-Finance")),
                reasoning=result.get("reasoning", ""),
            )
        except Exception as e:
            logger.error(f"LLM classification failed for {sender}: {e}")
            return SenderClassification(
                sender=sender,
                is_finance=False,
                confidence=0.0,
                category=FinanceCategory.non_finance,
                reasoning=f"Classification error: {e}",
            )

    @classmethod
    async def classify_batch(
        cls, sender_map: dict[str, list[str]]
    ) -> list[SenderClassification]:
        results: list[SenderClassification] = []
        for sender, messages in sender_map.items():
            result = await cls.classify(sender, messages)
            results.append(result)
        return results
