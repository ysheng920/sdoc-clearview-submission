"""One interface, three backends. Engines never import a concrete client."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class LLMReply:
    text: str
    data: dict | None                 # parsed JSON, None if unparseable
    model: str
    backend: str
    min_logprob: float = 0.0          # router signal; 0.0 == "no signal available"
    has_logprobs: bool = False
    tokens: dict = field(default_factory=dict)
    # What the provider says the call cost. Reported rather than reconstructed
    # from a rate table, where a backend gives it; 0.0 means it did not.
    cost: float = 0.0
    ms: float = 0.0
    note: str = ""                    # why it looks the way it does, for the Trace


class LLMClient(Protocol):
    name: str
    model: str

    def complete(self, prompt: str, *, task: str = "", hint: dict | None = None,
                 max_tokens: int = 400, confidence_key: str | None = None,
                 image: bytes | None = None) -> LLMReply: ...


_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")
_THINK = re.compile(r"<think>.*?</think>\s*", re.S)


def parse_json(text: str) -> dict | None:
    """Recover a JSON object from a chat reply.

    Small local models wrap replies in fences and, for Qwen3-family builds,
    may emit a <think> block first. Strip both before giving up.
    """
    if not text:
        return None
    cleaned = _FENCE.sub("", _THINK.sub("", text)).strip()
    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    # Try outermost {...} in the reply
    i = cleaned.find("{")
    j = cleaned.rfind("}")
    if i != -1 and j > i:
        try:
            obj = json.loads(cleaned[i:j + 1])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

    # Truncated JSON recovery: reply began with '{' but was cut off before closing '}'
    if i != -1:
        snippet = cleaned[i:]
        for cut in range(len(snippet), 0, -1):
            if snippet[cut - 1] in (',', '\n', '"'):
                cand = snippet[:cut].rstrip().rstrip(',') + "\n}"
                try:
                    obj = json.loads(cand)
                    if isinstance(obj, dict):
                        return obj
                except json.JSONDecodeError:
                    continue

    return None
