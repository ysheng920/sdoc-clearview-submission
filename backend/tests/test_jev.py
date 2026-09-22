"""Reading a Decisions API answer, and what happens when there isn't one.

Jev returns probabilities rather than prose, which is the reason to use it for
classification and also the reason it needs its own checks: a chat reply that
comes back malformed is obvious, whereas a decision that quietly failed would
otherwise still look like a confident answer.

No network. The transport is stubbed with a recorded response, so this runs in
CI beside everything else. `python tests/test_jev.py`.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.llm import ClassificationRouter, jev  # noqa: E402
from app.llm.base import LLMReply  # noqa: E402
from app.engines.decide import decide  # noqa: E402

# Shape recorded from a live call on 2026-09-21.
RESPONSE = {
    "model": "typesafe/jev-1.13-20260917",
    "answers": {
        "category": {
            "type": "choice", "choice": "INVOICE_QUERY", "confidence": 0.89,
            "probabilities": {"INVOICE_QUERY": 0.89, "GENERAL": 0.09,
                              "BL_COMPARISON": 0.02, "SI_REQUEST": 0, "SPAM": 0},
        },
        "intent": {"type": "choice", "choice": "QUERY_CHARGES", "confidence": 0.9,
                   "probabilities": {"QUERY_CHARGES": 0.9}},
    },
    "usage": {"input_tokens": 465, "output_tokens": 63, "cost": 1.953e-05},
    "provider": "TypeSafe",
}

EMAIL = {"subject": "Mill D & D charges", "from": "a@b.com",
         "body": "Please confirm the detention charges before we release payment.",
         "attachments": []}


class FakeFallback:
    """Stands in for the text-generating client Jev hands document work to."""

    name = "stand-in"
    model = "stand-in-v1"

    def __init__(self):
        self.calls = []

    def complete(self, prompt, **kw):
        self.calls.append(kw.get("task"))
        return LLMReply(text="{}", data={}, model=self.model, backend=self.name)


class FixedClient:
    def __init__(self, reply):
        self.reply = reply
        self.calls = 0
        self.name = reply.backend
        self.model = reply.model

    def complete(self, prompt, **kw):
        self.calls += 1
        return self.reply


def stub(response, capture=None):
    """Replace the transport with one that returns `response`."""
    class Body:
        def read(self):
            return json.dumps(response).encode("utf-8")

    def urlopen(req, timeout=0):
        if capture is not None:
            capture.append(json.loads(req.data.decode("utf-8")))
        return Body()
    return urlopen


def client(response=RESPONSE, capture=None):
    original = jev.urllib.request.urlopen
    jev.urllib.request.urlopen = stub(response, capture)
    fallback = FakeFallback()
    return jev.JevClient("test-key", fallback=fallback), fallback, original


def test_a_decision_becomes_the_fields_classify_reads():
    c, _, original = client()
    try:
        reply = c.complete("ignored prompt", task="classify", hint=EMAIL)
    finally:
        jev.urllib.request.urlopen = original

    assert reply.data["category"] == "INVOICE_QUERY"
    assert reply.data["intent"] == "QUERY_CHARGES"
    # The calibrated probability, not the flat default the chat path falls back to.
    assert reply.data["confidence"] == 0.89
    assert reply.backend == "jev"
    assert reply.model == "typesafe/jev-1.13-20260917", "the resolved version, not the alias"
    assert reply.tokens == {"prompt": 465, "completion": 63}
    assert reply.cost == 1.953e-05, "the provider billed the call and said what it cost"


def test_the_note_says_what_it_nearly_chose():
    """With a calibrated model, the runner-up is the interesting part of a
    close call -- it is what a reviewer would want to see before overruling."""
    c, _, original = client()
    try:
        reply = c.complete("", task="classify", hint=EMAIL)
    finally:
        jev.urllib.request.urlopen = original
    assert "over GENERAL (0.09)" in reply.note, reply.note


def test_the_questions_carry_every_category_and_intent():
    """A choice model can only return an option it was given."""
    sent = []
    c, _, original = client(capture=sent)
    try:
        c.complete("", task="classify", hint=EMAIL)
    finally:
        jev.urllib.request.urlopen = original

    body = sent[0]
    assert body["model"] == "~typesafe/jev-latest"
    assert set(body["questions"]["category"]["criteria"]) == {
        "BL_COMPARISON", "SI_REQUEST", "INVOICE_QUERY", "GENERAL", "SPAM"}
    assert "REQUEST_DRAFT" in body["questions"]["intent"]["criteria"]
    assert EMAIL["subject"] in body["state"] and EMAIL["body"] in body["state"]


def test_reading_a_document_goes_to_a_model_that_can_write():
    """Jev generates no text, so extraction is not its job and must not silently
    return nothing."""
    c, fallback, original = client()
    try:
        reply = c.complete("extract these fields", task="extract", hint=EMAIL)
    finally:
        jev.urllib.request.urlopen = original
    assert fallback.calls == ["extract"]
    assert reply.backend == "stand-in"


def test_a_failed_decision_never_becomes_a_category():
    """The dangerous failure is a confident wrong answer, so a call that did not
    happen returns no data and says why."""
    original = jev.urllib.request.urlopen

    def boom(req, timeout=0):
        raise jev.urllib.error.URLError("connection reset")

    jev.urllib.request.urlopen = boom
    try:
        c = jev.JevClient("test-key", fallback=FakeFallback())
        reply = c.complete("", task="classify", hint=EMAIL)
    finally:
        jev.urllib.request.urlopen = original

    assert reply.data is None
    assert reply.text == ""
    assert "failed" in reply.note and "URLError" in reply.note


def test_confident_jev_is_accepted_without_spending_a_gemini_call():
    first = FixedClient(LLMReply(
        text='{"category":"BL_COMPARISON"}',
        data={"category": "BL_COMPARISON", "intent": "COMPARE_DOCS",
              "confidence": 0.91},
        model="jev-1.13", backend="jev", ms=20, cost=0.001,
    ))
    fallback = FixedClient(LLMReply(
        text='{"category":"GENERAL"}',
        data={"category": "GENERAL", "intent": "GENERAL_NOTICE", "confidence": 1},
        model="gemini-3.1-flash-lite", backend="gemini",
    ))
    reply = ClassificationRouter(first, fallback, threshold=0.8).complete(
        "prompt", task="classify", hint=EMAIL)
    assert first.calls == 1 and fallback.calls == 0
    assert reply.data["category"] == "BL_COMPARISON"
    assert reply.data["_routing"]["fallback_used"] is False


def test_low_confidence_jev_falls_back_to_gemini_and_keeps_the_audit_trail():
    first = FixedClient(LLMReply(
        text='{"category":"GENERAL"}',
        data={"category": "GENERAL", "intent": "GENERAL_NOTICE", "confidence": 0.72},
        model="jev-1.13", backend="jev", ms=20, cost=0.001,
        tokens={"prompt": 10, "completion": 2},
    ))
    fallback = FixedClient(LLMReply(
        text='{"category":"INVOICE_QUERY"}',
        data={"category": "INVOICE_QUERY", "intent": "QUERY_CHARGES",
              "confidence": 0.98},
        model="gemini-3.1-flash-lite", backend="gemini", ms=50, cost=0.002,
        tokens={"prompt": 20, "completion": 4},
    ))
    reply = ClassificationRouter(first, fallback, threshold=0.8).complete(
        "prompt", task="classify", hint=EMAIL)
    assert first.calls == 1 and fallback.calls == 1
    assert reply.data["category"] == "INVOICE_QUERY"
    assert reply.data["_routing"]["fallback_used"] is True
    assert reply.backend == "jev->gemini" and reply.ms == 70 and reply.cost == 0.003
    assert reply.tokens == {"prompt": 30, "completion": 6}


def test_two_provider_failures_require_human_review():
    empty_jev = FixedClient(LLMReply(
        text="", data=None, model="jev-1.13", backend="jev", note="timeout"))
    empty_gemini = FixedClient(LLMReply(
        text="", data=None, model="gemini-3.1-flash-lite", backend="gemini",
        note="provider unavailable"))
    reply = ClassificationRouter(empty_jev, empty_gemini, threshold=0.8).complete(
        "prompt", task="classify", hint=EMAIL)
    assert reply.data is None and reply.backend == "jev->gemini"

    decision, _ = decide(EMAIL, {
        "category": "GENERAL", "intent": "GENERAL_NOTICE", "confidence": 0,
        "unclassified": True,
    }, None)
    assert decision["action"] == "HUMAN_REVIEW"


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
            passed += 1
    print(f"\n{passed} checks passed")
