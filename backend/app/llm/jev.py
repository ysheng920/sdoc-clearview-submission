"""TypeSafe Jev, through OpenRouter's Decisions API.

Not a chat model. It does not generate text at all: it answers typed questions
about a state and returns calibrated probabilities. That makes it a poor fit for
extraction -- there is nothing for it to write -- and an unusually good fit for
classification, which is a pick from five named options and nothing more.

Two things follow from that, and both are improvements on what the chat path can
do here:

  * the confidence is the model's own calibrated probability for the option it
    picked, not the flat 0.8 the chat path falls back to when a provider returns
    no usage signal. A number the dashboard prints as a percentage should mean
    something, and this one does.
  * every reply carries the provider's own cost for the call, so a run's spend is
    reported rather than reconstructed from a rate table somebody typed in.

Extraction and OCR are delegated to a second client, so a Jev run is honestly a
pair: Jev classifies, something else reads documents. Each trace records the
backend that actually answered it, so the split shows up in the pipeline view and
in the per-engine breakdown rather than being hidden behind one model name.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from .. import config
from .base import LLMReply

ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
MODEL = "~typesafe/jev-latest"

# The five categories, worded as decision criteria rather than prompt prose --
# this model is given options to choose between, not an instruction to follow.
CATEGORY_CRITERIA = {
    "BL_COMPARISON": "Asks us to check or compare a Shipping Instruction against a "
                     "draft Bill of Lading, or chases the draft BL for that purpose",
    "SI_REQUEST": "Asks us to create, issue or submit a NEW Shipping Instruction "
                  "for a specific shipment",
    "INVOICE_QUERY": "Asks about an invoice, billing, freight, demurrage or detention "
                     "(D&D), THC or local charges",
    "GENERAL": "Shipping-related but none of the above -- bulletins, broadcast "
               "reminders, acknowledgements, status chatter",
    "SPAM": "Marketing, phishing, or unrelated to shipping operations",
}

INTENT_CRITERIA = {
    "COMPARE_DOCS": "Wants two attached documents checked against each other, even "
                    "if the attachments were dropped in transit",
    "REQUEST_DRAFT": "Is chasing us to send them the draft Bill of Lading; there is "
                     "nothing for us to compare yet",
    "ISSUE_SI": "Wants a Shipping Instruction created or submitted",
    "QUERY_CHARGES": "Is asking about money -- charges, invoices, payment",
    "GENERAL_NOTICE": "A notice or bulletin with no specific action for us",
    "SPAM": "Not a real operational request",
}


def _state(hint: dict) -> str:
    """The email as the model sees it. Bounded, because the state is billed."""
    attachments = hint.get("attachments") or []
    return (
        f"Subject: {hint.get('subject') or '(none)'}\n"
        f"From: {hint.get('from') or '(unknown)'}\n"
        f"Attachments: {', '.join(a.rsplit('/', 1)[-1] for a in attachments) or '(none)'}\n"
        f"Body:\n{(hint.get('body') or '')[:3000]}"
    )


class JevClient:
    """Classification via the Decisions API; everything else via `fallback`."""

    def __init__(self, api_key: str, fallback, model: str = MODEL,
                 timeout: float | None = None):
        self.name = "jev"
        self.model = model
        self._key = api_key
        self._fallback = fallback
        self._timeout = timeout if timeout is not None else config.REQUEST_TIMEOUT

    def complete(self, prompt: str, *, task: str = "", hint: dict | None = None,
                 max_tokens: int = 400, confidence_key: str | None = None,
                 image: bytes | None = None) -> LLMReply:
        if task != "classify" or not hint:
            # Reading a document is generation, which this model does not do.
            return self._fallback.complete(
                prompt, task=task, hint=hint, max_tokens=max_tokens,
                confidence_key=confidence_key, image=image)

        body = {
            "model": self.model,
            "state": _state(hint),
            "questions": {
                "category": {
                    "type": "choice",
                    "instructions": "Which kind of shipping-operations email is this?",
                    "criteria": CATEGORY_CRITERIA,
                },
                "intent": {
                    "type": "choice",
                    "instructions": "What does the sender actually want us to do?",
                    "criteria": INTENT_CRITERIA,
                },
            },
        }

        t0 = time.perf_counter()
        try:
            raw = urllib.request.urlopen(urllib.request.Request(
                ENDPOINT, data=json.dumps(body).encode("utf-8"),
                headers={"Authorization": f"Bearer {self._key}",
                         "Content-Type": "application/json",
                         "X-Title": "sdoc-clearview"},
            ), timeout=self._timeout).read().decode("utf-8")
            payload = json.loads(raw)
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            ms = (time.perf_counter() - t0) * 1000
            # A failed decision must not silently become a category. Returning no
            # data lets classify fall through to its own handling, and the note
            # says why on the trace.
            return LLMReply(text="", data=None, model=self.model, backend=self.name,
                            ms=ms, note=f"decisions call failed: {type(exc).__name__}: {exc}")

        ms = (time.perf_counter() - t0) * 1000
        answers = payload.get("answers") or {}
        category = (answers.get("category") or {}).get("choice")
        intent = (answers.get("intent") or {}).get("choice")
        confidence = (answers.get("category") or {}).get("confidence")
        spread = (answers.get("category") or {}).get("probabilities") or {}

        # Runner-up, so the trace can say what it nearly chose -- the useful thing
        # to see when a calibrated model reports it was unsure.
        ranked = sorted(spread.items(), key=lambda kv: -kv[1])
        runner_up = ranked[1] if len(ranked) > 1 else None
        reason = f"chose {category}"
        if runner_up and runner_up[1] > 0:
            reason += f" over {runner_up[0]} ({runner_up[1]:.2f})"

        usage = payload.get("usage") or {}
        data = {"category": category, "intent": intent, "reason": reason}
        if confidence is not None:
            data["confidence"] = confidence

        return LLMReply(
            text=json.dumps(data),
            data=data,
            model=payload.get("model") or self.model,
            backend=self.name,
            ms=ms,
            tokens={"prompt": usage.get("input_tokens") or 0,
                    "completion": usage.get("output_tokens") or 0},
            cost=float(usage.get("cost") or 0.0),
            note=f"decisions API, {payload.get('provider', 'TypeSafe')}: {reason}",
        )


def available() -> bool:
    return bool(config.OPENROUTER_API_KEY)
