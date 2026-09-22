"""Ollama and OpenRouter both speak /v1/chat/completions, so they share a client.

Only the base_url, the model id and whether a key is required differ.
"""
from __future__ import annotations

import base64
import math
import time

from .. import config
from .base import LLMReply, parse_json


def _logprob_for_value(text: str, tokens, data: dict | None,
                       key: str | None) -> float | None:
    """Lowest token confidence *within one JSON field's value*.

    Taking the minimum across the whole reply sounds equivalent and is not: any
    free-text field drags it down, because prose has many valid continuations.
    Measured on qwen3.5:4b, a correct and obvious classification scored 0.28 that
    way -- the uncertainty was all in the `reason` sentence, not the decision.
    Scoring only the tokens that spell the decision is what the router needs.
    """
    if not key or not data or not text:
        return None
    value = data.get(key)
    if not isinstance(value, str) or not value:
        return None

    idx = text.find(f'"{value}"')
    if idx == -1:
        return None
    start, end = idx + 1, idx + 1 + len(value)

    selected, pos = [], 0
    for tok in tokens:
        span = len(tok.token)
        if pos < end and pos + span > start:   # token overlaps the value
            selected.append(tok.logprob)
        pos += span
    return min(selected) if selected else None


# Every image used to be announced as PNG. It was one, while the only images
# were pages lifted out of a PDF; a photo of a document is usually a JPEG, and
# a provider that believes the label rather than the bytes rejects it.
_MAGIC = (
    (bytes.fromhex("89504e470d0a1a0a"), "image/png"),
    (bytes.fromhex("ffd8ff"), "image/jpeg"),
    (b"GIF8", "image/gif"),
    (b"BM", "image/bmp"),
)


def _media_type(data: bytes) -> str:
    for magic, media in _MAGIC:
        if data.startswith(magic):
            return media
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


class OpenAICompatClient:
    def __init__(self, *, name: str, base_url: str, model: str, api_key: str,
                 json_mode: bool = True, want_logprobs: bool = True,
                 no_think: bool = False):
        """no_think disables the model's reasoning channel -- see complete()."""
        from openai import OpenAI  # imported late so a rules-only run needs no dep

        # Ollama ignores the key but the SDK refuses to construct without one.
        self._client = OpenAI(base_url=base_url, api_key=api_key or "local",
                              timeout=config.REQUEST_TIMEOUT,
                              max_retries=config.REQUEST_RETRIES)
        self.name = name
        self.model = model
        self.json_mode = json_mode
        self.want_logprobs = want_logprobs
        self.no_think = no_think

    def complete(self, prompt: str, *, task: str = "", hint: dict | None = None,
                 max_tokens: int = 400, confidence_key: str | None = None,
                 image: bytes | None = None) -> LLMReply:
        t0 = time.perf_counter()

        if image is None:
            content: object = prompt
        else:
            # Same model, same endpoint -- the OCR capability was already
            # deployed, the pipeline just never sent it a picture.
            content = [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {
                    "url": f"data:{_media_type(image)};base64,"
                           + base64.b64encode(image).decode()}},
            ]

        kwargs: dict = {
            "model": self.model,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": max_tokens,
            "temperature": 0,
        }
        if self.no_think:
            # Qwen3.5 on Ollama reasons by default and returns that reasoning in a
            # separate `message.reasoning` field, leaving `content` EMPTY while the
            # whole token budget is spent -- so the failure looks like a parse error
            # with no clue why. Measured against this build: `/no_think` in the
            # prompt, `think: false` and `chat_template_kwargs.enable_thinking`
            # are all accepted and all silently ignored. Only this works.
            kwargs["reasoning_effort"] = "none"
        if self.json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if self.want_logprobs:
            kwargs["logprobs"] = True

        try:
            resp = self._client.chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 - surfaced in the Trace, not swallowed
            if self.want_logprobs and "logprob" in str(exc).lower():
                # Server doesn't support logprobs; retry once without and let the
                # router fall back to its abstention rules.
                self.want_logprobs = False
                return self.complete(prompt, task=task, hint=hint,
                                     max_tokens=max_tokens,
                                     confidence_key=confidence_key, image=image)
            return LLMReply(text="", data=None, model=self.model, backend=self.name,
                            ms=(time.perf_counter() - t0) * 1000,
                            note=f"request failed: {type(exc).__name__}: {exc}")

        choice = resp.choices[0]
        text = choice.message.content or ""
        data = parse_json(text)

        min_lp, has_lp = 0.0, False
        try:
            tokens = choice.logprobs.content  # type: ignore[union-attr]
            if tokens:
                scoped = _logprob_for_value(text, tokens, data, confidence_key)
                min_lp = round(scoped if scoped is not None
                               else min(t.logprob for t in tokens), 4)
                has_lp = True
        except (AttributeError, TypeError, ValueError):
            pass

        usage = getattr(resp, "usage", None)
        if data is not None:
            note = "ok"
        elif not text and getattr(choice.message, "reasoning", None):
            # The expensive failure: tokens were spent, none reached `content`.
            # Name it precisely, or it reads as an ordinary parse error.
            note = ("model reasoned instead of answering -- content was empty while "
                    "the reply went to `reasoning`. Pass reasoning_effort=none "
                    "(no_think=True) for this model.")
        elif "<think>" in text:
            note = "reply contained an inline <think> block -- set no_think for this model"
        elif choice.finish_reason == "length":
            note = f"reply hit the {max_tokens}-token cap before closing its JSON"
        else:
            note = f"reply was not valid JSON ({len(text)} chars)"

        return LLMReply(
            text=text, data=data, model=self.model, backend=self.name,
            min_logprob=min_lp, has_logprobs=has_lp,
            tokens={"prompt": getattr(usage, "prompt_tokens", 0) or 0,
                    "completion": getattr(usage, "completion_tokens", 0) or 0},
            ms=(time.perf_counter() - t0) * 1000, note=note,
        )
