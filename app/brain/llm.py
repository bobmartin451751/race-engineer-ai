"""LLM backends: local llama.cpp server and DeepSeek (OpenAI-compatible)."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import requests

log = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 2


class LLMError(RuntimeError):
    pass


@dataclass
class LLMReply:
    text: str
    provider: str
    latency_s: float
    used_tools: bool = False


class LLMClient:
    def __init__(self, name: str, cfg: dict[str, Any]) -> None:
        self.name = name
        self.base_url = str(cfg.get("base_url", "")).rstrip("/")
        self.model = str(cfg.get("model", ""))
        self.api_key = str(cfg.get("api_key", "") or "")
        self.temperature = float(cfg.get("temperature", 0.3))
        self.max_tokens = int(cfg.get("max_tokens", 220))
        self.timeout_s = float(cfg.get("timeout_s", 15))
        self.disable_thinking = bool(cfg.get("disable_thinking", False))
        self.api_key_env = cfg.get("api_key_env")
        self.last_error: str | None = None
        self._health_cache: tuple[bool, str, float] | None = None

    # ------------------------------------------------------------------
    def health(self) -> tuple[bool, str]:
        if self.name != "local" and not self.api_key:
            return False, f"missing API key ({self.api_key_env or 'api_key'})"
        now = time.time()
        if self._health_cache and now - self._health_cache[2] < 10.0:
            return self._health_cache[0], self._health_cache[1]
        try:
            resp = requests.get(f"{self.base_url}/models", timeout=3,
                                headers=self._headers())
            if resp.status_code == 200:
                result = (True, "ok")
            else:
                result = (False, f"HTTP {resp.status_code}")
        except requests.RequestException as exc:
            result = (False, str(exc))
        self._health_cache = (result[0], result[1], now)
        return result

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key and self.api_key != "local":
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    # ------------------------------------------------------------------
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_runner=None,
    ) -> LLMReply:
        started = time.time()
        used_tools = False
        convo = list(messages)

        for _round in range(MAX_TOOL_ROUNDS + 1):
            payload: dict[str, Any] = {
                "model": self.model,
                "messages": convo,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "stream": False,
            }
            if self.disable_thinking:
                payload["thinking"] = {"type": "disabled"}
            if tools and tool_runner:
                payload["tools"] = tools
                payload["tool_choice"] = "auto"

            data = self._post(payload)
            message = data["choices"][0]["message"]
            tool_calls = message.get("tool_calls") or []
            if not tool_calls or not tool_runner:
                text = (message.get("content") or "").strip()
                if not text and message.get("reasoning_content"):
                    log.warning("%s returned reasoning without content", self.name)
                return LLMReply(
                    text=text,
                    provider=self.name,
                    latency_s=time.time() - started,
                    used_tools=used_tools,
                )

            used_tools = True
            convo.append(
                {
                    "role": "assistant",
                    "content": message.get("content") or "",
                    "tool_calls": tool_calls,
                }
            )
            for call in tool_calls:
                fn = call.get("function", {})
                result = tool_runner(fn.get("name", ""), fn.get("arguments", "{}"))
                convo.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id", ""),
                        "content": result,
                    }
                )

        raise LLMError(f"{self.name} exceeded {MAX_TOOL_ROUNDS} tool rounds")

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/chat/completions"
        try:
            resp = requests.post(
                url, headers=self._headers(), json=payload, timeout=self.timeout_s
            )
        except requests.RequestException as exc:
            self.last_error = str(exc)
            self._health_cache = None
            raise LLMError(f"{self.name} request failed: {exc}") from exc

        if resp.status_code != 200:
            self._health_cache = None
            detail = resp.text[:500].replace("\n", " ")
            self.last_error = f"HTTP {resp.status_code}: {detail}"
            # llama.cpp without --jinja rejects tools; retry once without them
            if resp.status_code == 400 and "tools" in payload:
                log.warning("%s rejected tool calling, retrying without tools", self.name)
                payload = {k: v for k, v in payload.items() if k not in ("tools", "tool_choice")}
                return self._post(payload)
            raise LLMError(f"{self.name} HTTP {resp.status_code}: {detail}")

        try:
            return resp.json()
        except json.JSONDecodeError as exc:
            raise LLMError(f"{self.name} returned invalid JSON") from exc


def tidy_reply(text: str, max_words: int = 45) -> str:
    """Keep radio replies short and speakable."""
    text = " ".join(text.replace("\n", " ").split())
    if not text:
        return text
    # drop markdown emphasis that survives to TTS
    for token in ("**", "__", "`"):
        text = text.replace(token, "")
    sentences = _split_sentences(text)
    out: list[str] = []
    words = 0
    for sentence in sentences:
        n = len(sentence.split())
        if out and words + n > max_words:
            break
        out.append(sentence.strip())
        words += n
        if len(out) >= 2:
            break
    return " ".join(out).strip()


def _split_sentences(text: str) -> list[str]:
    import re

    parts = re.split(r"(?<=[.!?])\s+", text)
    return [part for part in parts if part.strip()]
