"""Thin Groq wrapper that returns validated Pydantic objects, not raw strings.

Two rules encoded here:

1. Every call that expects structure goes through JSON mode and is parsed into
   a Pydantic model. If the model returns something malformed we retry once
   with the validation error appended, then give up rather than guess.
2. Temperature defaults low. This pipeline rewrites factual claims about a
   real person; creative sampling is not a feature.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, TypeVar

from groq import Groq, GroqError
from pydantic import BaseModel, ValidationError

from app.config import settings

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Transient failures worth retrying: connection blips and 5xx from Groq's edge.
_TRANSIENT_MARKERS = (
    "connection", "timeout", "timed out", "temporarily unavailable",
    "internal server error", "bad gateway", "service unavailable",
    "gateway timeout", "500", "502", "503", "504",
)

def _is_transient(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(m in text for m in _TRANSIENT_MARKERS)

class LLMUnavailable(RuntimeError):
    """Raised when no API key is configured or Groq cannot be reached."""

class TruncatedResponse(LLMUnavailable):
    """The model ran out of output budget mid-answer.

    Worth its own type because it is the silent one. gpt-oss closes the JSON
    when it is cut off, so a truncated reply still *parses* -- Pydantic
    validates a half-populated object and the missing experience, projects and
    achievements simply never appear. Nothing errors. Always check
    `finish_reason` rather than trusting a successful parse.
    """


class RateLimited(LLMUnavailable):
    """Groq refused the request because a quota is exhausted.

    Separated from other failures because it is both the most common and the
    most recoverable: limits are per-model, so a different model often works,
    and a daily limit resets on its own.
    """

    def __init__(self, message: str, model: str, retry_after: str | None = None):
        super().__init__(message)
        self.model = model
        self.retry_after = retry_after

_RETRY_RE = re.compile(r"try again in ([\dhms.]+)", re.I)
_LIMIT_RE = re.compile(r"on (tokens per day|tokens per minute|requests per \w+)", re.I)

def _classify(exc: Exception, model: str) -> LLMUnavailable:
    """Turn Groq's raw error blob into something a human can act on."""
    text = str(exc)
    if "rate_limit" not in text and "429" not in text:
        return LLMUnavailable(f"Groq request failed: {text[:200]}")

    retry = _RETRY_RE.search(text)
    window = _LIMIT_RE.search(text)
    kind = (window.group(1) if window else "rate limit").replace("tokens per day", "daily token limit")

    msg = f"Groq {kind} reached for model '{model}'"
    if retry:
        msg += f" — resets in {retry.group(1)}"
    return RateLimited(msg, model=model, retry_after=retry.group(1) if retry else None)

class GroqLLM:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = (api_key if api_key is not None else settings.groq_api_key).strip()
        self.model = model or settings.groq_model
        self._client: Groq | None = None

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    @property
    def client(self) -> Groq:
        if not self.api_key:
            raise LLMUnavailable(
                "GROQ_API_KEY is not set. Copy backend/.env.example to backend/.env "
                "and add a key from https://console.groq.com/keys"
            )
        if self._client is None:
            self._client = Groq(api_key=self.api_key)
        return self._client

    # -- raw text ----------------------------------------------------------

    def _create_with_retry(self, **kwargs: Any) -> Any:
        """Call chat.completions.create with backoff on transient failures.

        Groq's edge occasionally 5xx's or drops the connection mid-request. A
        short retry saves the build from a stack trace on the user's screen.
        Rate-limit and auth errors are NOT retried — those are terminal.
        """
        model = kwargs.get("model") or self.model
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                return self.client.chat.completions.create(**kwargs)
            except GroqError as exc:
                last_exc = exc
                if not _is_transient(exc) or attempt == 2:
                    raise _classify(exc, model) from exc
                delay = 1.0 * (2 ** attempt)
                log.warning("Groq transient error (attempt %d/3): %s — retrying in %.1fs",
                            attempt + 1, str(exc)[:120], delay)
                time.sleep(delay)
        # Unreachable, but keeps the type checker happy.
        raise _classify(last_exc or GroqError("unknown"), model)

    def complete(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> str:
        resp = self._create_with_retry(
            model = model or self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature = temperature,
            max_tokens = max_tokens,
        )
        return (resp.choices[0].message.content or "").strip()

    # -- structured --------------------------------------------------------

    def complete_json(
        self,
        system: str,
        user: str,
        schema: type[T],
        *,
        model: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        retries: int = 1,
        allow_truncated: bool = False,
    ) -> T:
        """Ask for JSON matching `schema` and return a validated instance.

        By default a truncated reply (``finish_reason == 'length'``) raises
        ``TruncatedResponse`` even if the JSON happens to parse — gpt-oss
        closes braces when cut off, so a successful parse is not proof of
        completeness. Callers on the last rung of a retry ladder can pass
        ``allow_truncated=True`` to accept the partial answer instead of
        failing the whole build.
        """
        # Compact separators: the schema is sent on every request and
        # pretty-printing it costs ~27% more tokens for zero benefit.
        shape = json.dumps(schema.model_json_schema(), separators = (",", ":"))
        sys_prompt = (
            f"{system}\n\n"
            "Reply with a single JSON object and nothing else. It must validate "
            f"against this JSON Schema:\n{shape}"
        )

        messages: list[dict[str, str]] = [
            {"role" : "system", "content" : sys_prompt},
            {"role" : "user", "content" : user},
        ]

        last_error = ""
        for attempt in range(retries + 1):
            resp = self._create_with_retry(
                model = model or self.model,
                messages = messages,
                temperature = temperature,
                max_tokens = max_tokens,
                response_format = {"type": "json_object"},
            )

            choice = resp.choices[0]
            was_truncated = choice.finish_reason == "length"
            raw = (choice.message.content or "").strip()

            if was_truncated and not allow_truncated:
                used = getattr(resp, "usage", None)
                raise TruncatedResponse(
                    f"model hit the {max_tokens}-token output cap "
                    f"(completion_tokens={getattr(used, 'completion_tokens', '?')}). "
                    "The reply is incomplete even though it may parse."
                )

            try:
                result = schema.model_validate_json(raw)
                if was_truncated:
                    log.warning(
                        "accepting truncated response as best-effort "
                        "(completion_tokens hit %d cap)", max_tokens,
                    )
                return result
            except ValidationError as exc:
                last_error = str(exc)
                if was_truncated:
                    # Truncated AND unparseable — nothing to salvage.
                    raise TruncatedResponse(
                        f"model was cut off at {max_tokens} tokens and the "
                        f"partial JSON did not validate: {last_error[:200]}"
                    ) from exc
                log.warning("LLM JSON failed validation (attempt %d): %s", attempt + 1, last_error[:300])
                messages.append({"role" : "assistant", "content" : raw})
                messages.append({
                    "role" : "user",
                    "content" : (
                        "That JSON failed schema validation with these errors:\n"
                        f"{last_error}\n\nReturn corrected JSON only."
                    ),
                })

        raise LLMUnavailable(f"Groq returned unparseable JSON after {retries + 1} attempts: {last_error[:300]}")

_default: GroqLLM | None = None

def get_llm() -> GroqLLM:
    global _default
    if _default is None:
        _default = GroqLLM()
    return _default