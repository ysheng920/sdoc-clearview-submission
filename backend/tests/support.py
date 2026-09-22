"""Test doubles, and the line they are not allowed to cross.

There is no simulated model here. Two doubles, both of which refuse to invent
anything:

  `Refuses`  answers nothing at all. Extraction falls back to label parsing,
             which is deterministic, and classification reports that it did not
             happen. This is what the rules-only checks run on.

  `Labelled` replays the category from ground_truth.json and nothing else -- no
             intent, no confidence of its own. Used by the checks that are about
             everything *downstream* of classification: routing to the document
             path, blocker detection, comparison, the recommended action, the
             draft. Those are deterministic once the category is known, and the
             category is the one thing a rules-only run cannot supply.

`Labelled` deliberately withholds the intent so the classifier's own fallback
has to derive it. That fallback reads nothing but the attachment count, and
reproducing it here is the point: it is where a real regression lived.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.llm.base import LLMReply  # noqa: E402


def ground_truth() -> dict[str, dict]:
    return json.loads((config.DATA_DIR / "ground_truth.json").read_text(encoding="utf-8"))


class Refuses:
    """Answers nothing, and says so. The absence of a model, not a stand-in."""

    name = "deterministic"
    model = None

    def __init__(self):
        self.calls = 0

    def complete(self, prompt: str, *, task: str = "", hint: dict | None = None,
                 max_tokens: int = 400, confidence_key: str | None = None,
                 image: bytes | None = None) -> LLMReply:
        self.calls += 1
        return LLMReply(text="", data=None, model=None, backend="deterministic",
                        note="no model was asked")


class Labelled(Refuses):
    """Replays the labelled category so the rest of the pipeline can be checked.

    Only for `task="classify"`. Extraction still gets nothing, so the fields come
    from label parsing exactly as they would with no model at all.
    """

    name = "labelled-fixture"
    model = "ground-truth-category"

    def __init__(self, overrides: dict[str, str] | None = None):
        super().__init__()
        self._gt = ground_truth()
        self._overrides = overrides or {}

    def complete(self, prompt: str, *, task: str = "", hint: dict | None = None,
                 max_tokens: int = 400, confidence_key: str | None = None,
                 image: bytes | None = None) -> LLMReply:
        if task != "classify":
            return super().complete(prompt, task=task, hint=hint,
                                    max_tokens=max_tokens,
                                    confidence_key=confidence_key, image=image)
        email_id = (hint or {}).get("email_id")
        category = self._overrides.get(email_id) or (self._gt.get(email_id) or {}).get("category")
        if not category:
            return super().complete(prompt, task=task, hint=hint)
        self.calls += 1
        # No intent on purpose -- the classifier's own fallback must derive it.
        data = {"category": category, "reason": "replayed from ground truth"}
        return LLMReply(text=json.dumps(data), data=data, model=self.model,
                        backend=self.name, note="labelled fixture")


def run(email_id: str, *, client=None):
    """One email through the pipeline, with the labelled category replayed.

    Extraction still gets no model, so every field comes from label parsing --
    which on this corpus finds all seven on every comparable pair.
    """
    from app.pipeline import load_email, process
    return process(load_email(email_id), client=client or Labelled())
