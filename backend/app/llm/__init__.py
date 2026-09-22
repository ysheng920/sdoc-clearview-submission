"""Which client answers, and what happens when none can.

There is deliberately no simulator here. A stand-in that invents categories makes
every run look like it worked, and the one thing worse than a pipeline that stops
is one that quietly labels the whole inbox GENERAL. `Unavailable` answers nothing
and says so, so the absence shows up in the trace instead of in the results.
"""
from __future__ import annotations

from .. import config
from .base import LLMClient, LLMReply, parse_json  # noqa: F401  (re-exported)

_client: LLMClient | None = None


class Unavailable:
    """Refuses every request. Not a fallback answer -- the absence of one.

    Used where only the deterministic path is wanted (label parsing, rule
    comparison) and where no provider is configured at all.
    """

    name = "deterministic"
    model = None

    def __init__(self, why: str = "no model is configured"):
        self.why = why

    def complete(self, prompt: str, *, task: str = "", hint: dict | None = None,
                 max_tokens: int = 400, confidence_key: str | None = None,
                 image: bytes | None = None) -> LLMReply:
        return LLMReply(text="", data=None, model=None, backend="deterministic",
                        note=self.why)


def _chat_client(model: str | None = None):
    """The text-generating client, for engines that need one."""
    if config.OPENROUTER_API_KEY:
        from .openai_compat import OpenAICompatClient
        return OpenAICompatClient(name="openrouter", base_url=config.OPENROUTER_BASE_URL,
                                  model=model or config.MODEL,
                                  api_key=config.OPENROUTER_API_KEY,
                                  want_logprobs=False)
    if config.GEMINI_API_KEY:
        from .openai_compat import OpenAICompatClient
        return OpenAICompatClient(name="gemini", base_url=config.GEMINI_BASE_URL,
                                  model=model or "gemini-2.0-flash",
                                  api_key=config.GEMINI_API_KEY, want_logprobs=False)
    return Unavailable("no provider key is set, so nothing was asked")


def _gemini_client(model: str | None = None):
    """Gemini by whichever key is present, OpenRouter first.

    There is no Google key in this deployment -- Gemini is reached through the
    same OpenRouter key as Jev. Requiring GEMINI_API_KEY here made the fallback
    permanently Unavailable, which silently took the whole non-classify side of
    the router offline: document extraction and scanned-page reading both go
    straight to the fallback, so neither could ever call a model.
    """
    from .openai_compat import OpenAICompatClient
    if config.GEMINI_API_KEY:
        return OpenAICompatClient(name="gemini", base_url=config.GEMINI_BASE_URL,
                                  model=model or config.GEMINI_MODEL,
                                  api_key=config.GEMINI_API_KEY, want_logprobs=False)
    if config.OPENROUTER_API_KEY:
        return OpenAICompatClient(name="gemini", base_url=config.OPENROUTER_BASE_URL,
                                  model=model or config.GEMINI_MODEL_OPENROUTER,
                                  api_key=config.OPENROUTER_API_KEY, want_logprobs=False)
    return Unavailable("neither OPENROUTER_API_KEY nor GEMINI_API_KEY is set")


_INTENTS = {
    "BL_COMPARISON": {"COMPARE_DOCS", "REQUEST_DRAFT"},
    "SI_REQUEST": {"ISSUE_SI"},
    "INVOICE_QUERY": {"QUERY_CHARGES"},
    "GENERAL": {"GENERAL_NOTICE"},
    "SPAM": {"SPAM"},
}


def _sum_tokens(a: dict, b: dict) -> dict:
    keys = set(a) | set(b)
    return {key: int(a.get(key) or 0) + int(b.get(key) or 0) for key in keys}


class ClassificationRouter:
    """Jev first, then Gemini when the decision is uncertain or unavailable.

    The routing threshold comes from the 520-email benchmark: at 0.80 Jev
    handled 509 cases with no errors, leaving 11 for Gemini. Non-classification
    work goes straight to Gemini because Jev is a choice model, not a generator.
    """

    name = "jev+gemini"

    def __init__(self, primary, fallback, threshold: float | None = None):
        self.primary = primary
        self.fallback = fallback
        self.threshold = (config.CLASSIFICATION_FALLBACK_THRESHOLD
                          if threshold is None else threshold)
        self.model = f"{getattr(primary, 'model', 'jev')} -> {getattr(fallback, 'model', 'gemini')}"

    @staticmethod
    def _shape_valid(reply: LLMReply) -> bool:
        data = reply.data or {}
        category = str(data.get("category") or "").upper()
        intent = str(data.get("intent") or "").upper()
        return category in _INTENTS and intent in _INTENTS[category]

    def _accepted(self, reply: LLMReply) -> tuple[bool, float]:
        data = reply.data or {}
        try:
            confidence = float(data.get("confidence"))
        except (TypeError, ValueError):
            return False, 0.0
        return self._shape_valid(reply) and confidence >= self.threshold, confidence

    @staticmethod
    def _with_routing(reply: LLMReply, routing: dict, *, backend: str | None = None,
                      note: str | None = None, ms: float | None = None,
                      cost: float | None = None, tokens: dict | None = None) -> LLMReply:
        data = dict(reply.data) if reply.data else None
        if data is not None:
            data["_routing"] = routing
        return LLMReply(
            text=reply.text, data=data, model=reply.model,
            backend=backend or reply.backend,
            min_logprob=reply.min_logprob, has_logprobs=reply.has_logprobs,
            tokens=tokens if tokens is not None else reply.tokens,
            cost=reply.cost if cost is None else cost,
            ms=reply.ms if ms is None else ms,
            note=note or reply.note,
        )

    def complete(self, prompt: str, *, task: str = "", hint: dict | None = None,
                 max_tokens: int = 400, confidence_key: str | None = None,
                 image: bytes | None = None) -> LLMReply:
        kwargs = {"task": task, "hint": hint, "max_tokens": max_tokens,
                  "confidence_key": confidence_key, "image": image}
        if task != "classify":
            return self.fallback.complete(prompt, **kwargs)

        first = self.primary.complete(prompt, **kwargs)
        accepted, confidence = self._accepted(first)
        if accepted:
            return self._with_routing(first, {
                "primary": "jev", "fallback": "gemini", "fallback_used": False,
                "threshold": self.threshold, "primary_confidence": confidence,
            }, note=f"Jev accepted at {confidence:.2f} (threshold {self.threshold:.2f}); {first.note}")

        if first.data and not self._shape_valid(first):
            reason = "invalid category or intent"
        elif first.data:
            reason = f"confidence {confidence:.2f} below {self.threshold:.2f}"
        else:
            reason = first.note or "no valid Jev decision"
        second = self.fallback.complete(prompt, **kwargs)
        routing = {
            "primary": "jev", "fallback": "gemini", "fallback_used": True,
            "threshold": self.threshold, "primary_confidence": confidence,
            "fallback_reason": reason,
        }
        if not self._shape_valid(second):
            return LLMReply(
                text="", data=None, model=second.model,
                backend="jev->gemini", ms=first.ms + second.ms,
                tokens=_sum_tokens(first.tokens, second.tokens),
                cost=first.cost + second.cost,
                note=f"Jev was not accepted ({reason}); Gemini returned no valid classification: {second.note}",
            )
        return self._with_routing(
            second, routing, backend="jev->gemini",
            note=f"Gemini fallback used because Jev returned {reason}; {second.note}",
            ms=first.ms + second.ms, cost=first.cost + second.cost,
            tokens=_sum_tokens(first.tokens, second.tokens),
        )


def operational_client() -> LLMClient:
    """The fixed production route; benchmark clients remain independently selectable."""
    from .jev import JevClient
    gemini = _gemini_client()
    primary = (JevClient(config.OPENROUTER_API_KEY, fallback=gemini)
               if config.OPENROUTER_API_KEY else Unavailable("OPENROUTER_API_KEY is not set"))
    return ClassificationRouter(primary, gemini)


def client_for(backend: str, model: str | None = None):
    """Build a client for one run, without touching the process-wide default.

    A run picks its own model, so this must not be the cached singleton: two runs
    of different models in one process would otherwise both get whichever was
    asked for first.
    """
    if backend in ("jev+gemini", "operational"):
        return operational_client()
    if backend == "deterministic":
        return Unavailable("rules only; no model was asked")
    if backend == "jev":
        from .jev import JevClient
        if not config.OPENROUTER_API_KEY:
            raise ValueError("jev needs OPENROUTER_API_KEY")
        # Jev writes nothing, so document reading goes to a chat model.
        return JevClient(config.OPENROUTER_API_KEY, fallback=_gemini_client())
    if backend == "gemini":
        client = _gemini_client(model)
        if isinstance(client, Unavailable):
            raise ValueError("gemini needs OPENROUTER_API_KEY or GEMINI_API_KEY")
        return client
    if backend == "openrouter":
        if not config.OPENROUTER_API_KEY:
            raise ValueError("openrouter needs OPENROUTER_API_KEY")
        from .openai_compat import OpenAICompatClient
        return OpenAICompatClient(name="openrouter", base_url=config.OPENROUTER_BASE_URL,
                                  model=model or config.MODEL,
                                  api_key=config.OPENROUTER_API_KEY, want_logprobs=False)
    raise ValueError(f"unknown backend {backend!r}")


def get_client() -> LLMClient:
    """The process-wide production route; deterministic mode remains available to CI."""
    global _client
    if _client is None:
        if config.LLM_BACKEND == "deterministic":
            _client = Unavailable("rules only; no model was asked")
        else:
            _client = operational_client()
    return _client


def runnable() -> list[dict]:
    """What a run can be started with, here, now.

    One entry: the Jev -> Gemini route the corpus was validated on. The single
    backends behind it are still reachable through client_for() for a benchmark
    started by hand, but offering them in the run panel invited an operator run
    on a model nothing has been measured against.
    """
    has_or = bool(config.OPENROUTER_API_KEY)
    return [{
        "backend": "jev+gemini",
        "model": f"~typesafe/jev-latest -> {config.GEMINI_MODEL}",
        "label": "Jev → Gemini",
        "available": has_or,
        "editable": False,
        "cost": "per call, then per token",
        "note": f"Jev classifies. Anything it is not confident about above "
                f"{config.CLASSIFICATION_FALLBACK_THRESHOLD:.2f} goes to Gemini, "
                f"which also reads every document and every scanned page."
                if has_or else "Needs OPENROUTER_API_KEY.",
    }]


def get_cloud_client() -> LLMClient | None:
    """Legacy helper: returns None since the primary client runs the full model directly."""
    return None


def reset() -> None:
    """Drop cached clients so tests can switch backends."""
    global _client
    _client = None
