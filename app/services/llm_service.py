from __future__ import annotations

import json
import logging
from typing import Any, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class LLMService:
    def __init__(self):
        self.provider = settings.llm_provider
        self.api_key = settings.llm_api_key
        self.base_url = settings.llm_base_url.rstrip("/")
        self.model = settings.llm_model
        self.max_tokens = settings.llm_max_tokens
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=600.0)
        return self._client

    async def _call_llm(self, messages: list[dict], response_format: Optional[str] = None) -> str:
        client = await self._get_client()
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": 0.05,
        }

        if response_format == "json_object":
            body["response_format"] = {"type": "json_object"}

        try:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"].strip()
            # Strip markdown code fences if present
            if content.startswith("```"):
                content = content.split("\n", 1)[-1]
                content = content.rsplit("\n", 1)[0]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()
            return content
        except httpx.HTTPStatusError as e:
            logger.error(f"LLM API error: {e.response.status_code} {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"LLM call failed: {e}  type={type(e).__name__}")
            raise

    async def classify_sender(self, sender: str, sms_messages: list[str]) -> dict:
        sample = sms_messages[:10]
        formatted = "\n---\n".join(f"[{i+1}] {m[:300]}" for i, m in enumerate(sample))

        prompt = (
            "You are a financial SMS classifier. Determine whether the sender of "
            "the following SMS messages is finance-related.\n\n"
            "Finance-related senders include: banks, mobile money services (MPESA, "
            "Airtel Money, T-Kash), SACCOS, fintech lenders (Tala, Branch, Zenka), "
            "insurance companies, payment aggregators (PesaLink, eCitizen), and "
            "government revenue authorities (KRA).\n\n"
            "Non-finance senders include: marketing/promotional numbers, social media, "
            "utilities (unless payment confirmations), ride-hailing, e-commerce order "
            "confirmations, and general service notifications that do not involve money.\n\n"
            f"Sender name: {sender}\n\n"
            f"Sample SMS messages from this sender:\n{formatted}\n\n"
            "Respond with valid JSON only, using this exact schema:\n"
            "{\n"
            '    "sender": "<sender>",\n'
            '    "is_finance": true/false,\n'
            '    "confidence": 0.0-1.0,\n'
            '    "category": "Mobile Money" | "Bank" | "SACCO" | "Fintech" | "Insurance" | "Payments/Govt" | "Other Finance" | "Non-Finance",\n'
            '    "reasoning": "brief explanation"\n'
            "}"
        )

        raw = await self._call_llm(
            [{"role": "user", "content": prompt}],
            response_format="json_object",
        )
        return json.loads(raw)

    async def extract_batch(self, sms_bodies: list[str]) -> list[dict]:
        items = "\n".join(
            f"{i} | {body[:500]}" for i, body in enumerate(sms_bodies)
        )

        prompt = (
            "You are a financial data extractor. Parse each of the following SMS "
            "messages and extract structured financial information.\n\n"
            "For each message:\n"
            "- is_transactional: true if this SMS describes a financial transaction "
            "(money movement, balance change, payment, deposit). false if it is a "
            "notification (OTP, promo, maintenance alert, general info).\n"
            "- amount_before: balance before the transaction, if explicitly stated. null otherwise.\n"
            "- amount_after: balance after the transaction, if explicitly stated. null otherwise.\n"
            "- amount_changed: the transaction amount. null if not found or not transactional.\n"
            '- direction: "sent" if money left, "received" if money came in, "none" if not applicable.\n'
            "- transaction_time: any date/time mentioned. null if not present.\n"
            "- counterparty: the other party. null if not present.\n"
            "- transaction_reference: any reference code. null if not present.\n"
            '- transaction_type: "transfer", "payment", "deposit", "withdrawal", "loan", "repayment", "salary", "fee", "interest", "refund", "other", "unknown"\n\n'
            f"Messages (index | body):\n{items}\n\n"
            "Respond with a valid JSON array only. One object per message, in the same order:\n"
            "[\n"
            "  {\n"
            '    "body": "original SMS text (truncated to 120 chars)",\n'
            '    "is_transactional": true/false,\n'
            '    "amount_before": null or number,\n'
            '    "amount_after": null or number,\n'
            '    "amount_changed": null or number,\n'
            '    "direction": "sent" | "received" | "none",\n'
            '    "transaction_time": null or string,\n'
            '    "counterparty": null or string,\n'
            '    "transaction_reference": null or string,\n'
            '    "transaction_type": "transfer" | "payment" | "deposit" | "withdrawal" | "loan" | "repayment" | "salary" | "fee" | "interest" | "refund" | "other" | "unknown"\n'
            "  }\n"
            "]"
        )

        raw = await self._call_llm(
            [{"role": "user", "content": prompt}],
        )
        return json.loads(raw)

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()


llm = LLMService()
