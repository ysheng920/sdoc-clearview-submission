"""Pick a specific mix of emails to run, by what the labels say they are.

This is a test-harness capability, not a pipeline one. The system under test
never sees a label -- it still has to work out the category, read the documents
and decide for itself. All this does is let the operator construct a scenario
("five with a real discrepancy, three spam") instead of taking whatever the
first N ids happen to be.

Worth knowing before designing a sample: every defect and every edge case in
this corpus lives inside BL_COMPARISON. The other four categories never reach
extraction or comparison at all, so a sample made only of those exercises two
engines out of four.
"""
from __future__ import annotations

import json
import random

from . import config, db

# The four plain categories, plus BL_COMPARISON split by what actually happens
# to it. Asking for "10 BL_COMPARISON" would otherwise be a coin toss over
# whether anything interesting turned up.
BUCKETS = [
    ("bl_clean", "BL · clean", "runs the whole chain and agrees"),
    ("bl_defect", "BL · discrepancy", "SI and BL disagree -- drafts a discrepancy reply"),
    ("bl_edge", "BL · edge case", "missing attachment, wrong doc type, scan, or blank field"),
    ("SI_REQUEST", "SI request", "classify and acknowledge only"),
    ("INVOICE_QUERY", "Invoice query", "classify and acknowledge only"),
    ("GENERAL", "General", "classify only -- no action"),
    ("SPAM", "Spam", "classify and ignore"),
]
BUCKET_KEYS = [k for k, _, _ in BUCKETS]

_gt_cache: dict[str, dict] | None = None


def ground_truth() -> dict[str, dict]:
    global _gt_cache
    if _gt_cache is None:
        path = config.DATA_DIR / "ground_truth.json"
        _gt_cache = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return _gt_cache


def bucket_of(label: dict) -> str:
    """Which bucket a labelled email belongs to. The three are disjoint:
    an edge case never also carries a defect in this corpus."""
    if label.get("category") != "BL_COMPARISON":
        return label.get("category") or "GENERAL"
    if label.get("review_reason"):
        return "bl_edge"
    if label.get("has_defect"):
        return "bl_defect"
    return "bl_clean"


def used_ids() -> set[str]:
    """Emails the operator has already been given.

    Benchmark runs are excluded on purpose: scoring a model re-reads the whole
    corpus, and if that counted as "handled" then one benchmark would empty the
    queue for good. Derived from results rather than tracked separately, so
    clearing the queue is what resets it and there is no second place to keep in
    sync."""
    return {r[0] for r in db.conn().execute(
        "SELECT DISTINCT r.email_id FROM results r JOIN runs ON runs.id = r.run_id "
        "WHERE COALESCE(runs.purpose, 'queue') = 'queue'")}


def availability() -> dict:
    gt = ground_truth()
    used = used_ids()
    by_bucket: dict[str, dict] = {}
    for key, label, note in BUCKETS:
        ids = [eid for eid, g in gt.items() if bucket_of(g) == key]
        free = [eid for eid in ids if eid not in used]
        by_bucket[key] = {
            "label": label, "note": note,
            "total": len(ids), "used": len(ids) - len(free), "available": len(free),
        }
    # Only corpus emails count against the corpus. A hand-written simulated
    # email is processed and so appears in used_ids(), but it was never in the
    # pool to begin with -- subtracting it made the headline disagree with the
    # buckets underneath it, which are what a run is actually drawn from.
    used_in_corpus = used & set(gt)
    return {
        "buckets": by_bucket,
        "order": BUCKET_KEYS,
        "corpus": len(gt),
        "used": len(used_in_corpus),
        "available": len(gt) - len(used_in_corpus),
        "labelled": bool(gt),
    }


def pick(quota: dict[str, int], *, seed: int | None = None) -> tuple[list[str], dict[str, int]]:
    """Return (email_ids, shortfall_per_bucket).

    Picks at random inside a bucket rather than by id order -- taking the first
    N would hand back the same head of the corpus every time. Already-processed
    emails are excluded, so repeated runs walk forward instead of re-billing the
    same work. A bucket that cannot fill its quota reports the gap rather than
    quietly substituting from elsewhere.
    """
    gt = ground_truth()
    used = used_ids()
    rng = random.Random(seed)

    picked: list[str] = []
    short: dict[str, int] = {}
    for key in BUCKET_KEYS:
        want = int(quota.get(key) or 0)
        if want <= 0:
            continue
        free = sorted(eid for eid, g in gt.items()
                      if bucket_of(g) == key and eid not in used)
        if want > len(free):
            short[key] = want - len(free)
            want = len(free)
        picked.extend(rng.sample(free, want))

    picked.sort()
    return picked, short
