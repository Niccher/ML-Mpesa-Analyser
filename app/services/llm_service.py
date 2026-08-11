from __future__ import annotations

import json
import logging
from typing import Any, Optional

import httpx

from app.config import settings
from app.services.prompt_manager import resolve as resolve_prompt

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

        prompt = await resolve_prompt(
            "classify_sender",
            sender=sender,
            sms_messages=formatted,
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

        prompt = await resolve_prompt(
            "extract_batch",
            messages_list=items,
        )

        raw = await self._call_llm(
            [{"role": "user", "content": prompt}],
        )
        return json.loads(raw)

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()


llm = LLMService()
