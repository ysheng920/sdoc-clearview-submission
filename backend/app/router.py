"""Confidence router: keep work on the local model until it stops being trustworthy.

The signal is the minimum token logprob of the reply. In a short JSON answer the
scaffold tokens are near-certain, so the minimum is effectively the confidence of
the one token that matters -- the category value -- without having to work out
which token that is.

Backends that cannot report logprobs degrade to the abstention rules alone
(unparseable reply / off-menu label), which still catches the loud failures.
"""
from __future__ import annotations

import math

from . import config


def should_escalate(reply, categories: list[str]) -> tuple[bool, str]:
    """Return (escalate, human-readable reason)."""
    if reply.data is None:
        return True, f"local reply was not valid JSON ({reply.note})"

    category = str(reply.data.get("category", "")).strip().upper()
    if category not in categories:
        return True, f"local model answered {category!r}, which is not one of the 5 categories"

    if not config.ESCALATION_ENABLED:
        return False, "escalation disabled by configuration"

    if reply.has_logprobs:
        if reply.min_logprob < config.ESCALATE_LOGP:
            return True, (
                f"lowest token confidence {math.exp(reply.min_logprob):.0%} is below the "
                f"{math.exp(config.ESCALATE_LOGP):.0%} threshold")
        return False, (
            f"lowest token confidence {math.exp(reply.min_logprob):.0%} clears the "
            f"{math.exp(config.ESCALATE_LOGP):.0%} threshold")

    return False, "no logprobs from this backend -- accepted on abstention rules alone"
