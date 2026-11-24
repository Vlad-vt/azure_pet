"""Optional LLM-as-a-judge for retrieval misses.

Used only when explicitly enabled (``scripts/eval.py --llm-judge``) *and* an API key is present
(``OPENAI_API_KEY`` or ``GEMINI_API_KEY``). Without a key it is a no-op, so the default
evaluation never spends money. The judge answers one question per miss: is the predicted SKU an
acceptable substitute for the invoice line (i.e. is the "miss" really label noise such as a
duplicate catalog entry)?
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import httpx

PROMPT = (
    "You review product matches for supplier invoices. Answer with JSON "
    '{{"equivalent": true|false, "reason": "<10 words"}}.\n'
    "Invoice line: {line}\nGround-truth SKU: {truth}\nPredicted SKU: {pred}\n"
    "Is the predicted SKU the same product (same brand, variant and pack size) as the "
    "ground truth?"
)


@dataclass(frozen=True, slots=True)
class JudgeVerdict:
    equivalent: bool
    reason: str


class LLMJudge:
    def __init__(self, provider: str, api_key: str, model: str) -> None:
        self.provider = provider
        self._key = api_key
        self.model = model
        self._client = httpx.Client(timeout=30)

    @classmethod
    def from_env(cls) -> LLMJudge | None:
        if key := os.environ.get("OPENAI_API_KEY"):
            return cls("openai", key, os.environ.get("JUDGE_MODEL", "gpt-4o-mini"))
        if key := os.environ.get("GEMINI_API_KEY"):
            return cls("gemini", key, os.environ.get("JUDGE_MODEL", "gemini-1.5-flash"))
        return None

    def judge(self, line: str, truth: str, pred: str) -> JudgeVerdict:
        prompt = PROMPT.format(line=line, truth=truth, pred=pred)
        text = self._openai(prompt) if self.provider == "openai" else self._gemini(prompt)
        try:
            data: dict[str, Any] = json.loads(text.strip().strip("`").removeprefix("json"))
            return JudgeVerdict(bool(data.get("equivalent")), str(data.get("reason", ""))[:80])
        except (json.JSONDecodeError, AttributeError):
            return JudgeVerdict(False, "unparseable judge output")

    def _openai(self, prompt: str) -> str:
        r = self._client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {self._key}"},
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
        )
        r.raise_for_status()
        return str(r.json()["choices"][0]["message"]["content"])

    def _gemini(self, prompt: str) -> str:
        r = self._client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
            headers={"x-goog-api-key": self._key},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
            },
        )
        r.raise_for_status()
        return str(r.json()["candidates"][0]["content"]["parts"][0]["text"])
