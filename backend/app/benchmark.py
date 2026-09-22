"""Scoring processed results against ground truth.

One scorer, used by the command-line evaluation and by the benchmarking page.
Two copies of this arithmetic would eventually disagree, and the page whose whole
job is to be trusted would be the one showing the wrong number.

Three stages, because they fail for different reasons and a single accuracy
figure hides that: routing the email to the right category, catching the cases
that cannot be certified at all, and agreeing with a human about which fields
disagree.

Nothing here reads the feedback table. A benchmark that scored corrected results
against ground truth would be marking its own homework with the answers in hand,
and would climb as reviewers worked rather than as the engine improved.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import config

CATEGORIES = config.CATEGORIES
REVIEW_REASONS = ("wrong_doc_type", "missing_attachment", "unreadable", "missing_value")


def ground_truth() -> dict[str, dict]:
    path = config.DATA_DIR / "ground_truth.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def record_to_submission(rec: dict) -> dict:
    """The four things ground truth has an opinion about, pulled off one record."""
    cat = rec["classification"]["category"]
    blockers = rec.get("blockers") or []
    cmp_ = rec.get("comparison")

    if blockers:
        text = " ".join(blockers).lower()
        reason = next((r for r in ("wrong_doc_type", "missing_attachment",
                                   "unreadable", "missing_value") if r in text),
                      "unreadable")
        return {"category": cat, "status": "NEEDS_REVIEW", "review_reason": reason,
                "has_defect": False, "defect_fields": []}

    if cmp_ is not None and cmp_["status"] == "MISMATCH":
        return {"category": cat, "status": "MISMATCH", "review_reason": None,
                "has_defect": True, "defect_fields": cmp_.get("defect_fields") or []}

    if cmp_ is not None and cmp_["status"] == "NEEDS_REVIEW":
        return {"category": cat, "status": "NEEDS_REVIEW", "review_reason": "missing_value",
                "has_defect": False, "defect_fields": []}

    return {"category": cat, "status": "OK", "review_reason": None,
            "has_defect": False, "defect_fields": []}


def _f1(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    return p, r, (2 * p * r / (p + r) if (p + r) else 0.0)


def score(predictions: dict[str, dict], gt: dict[str, dict] | None = None) -> dict:
    """Score one set of predictions. Emails absent from ground truth are skipped.

    `predictions` maps email_id to the shape record_to_submission returns.
    """
    gt = ground_truth() if gt is None else gt
    ids = [eid for eid in predictions if eid in gt]

    # Stage 1 -- classification.
    per_cat = {c: {"tp": 0, "fp": 0, "fn": 0} for c in CATEGORIES}
    confusion = {a: {b: 0 for b in CATEGORIES} for a in CATEGORIES}
    misclassified = []
    for eid in ids:
        actual, pred = gt[eid]["category"], predictions[eid]["category"]
        if actual in confusion and pred in confusion[actual]:
            confusion[actual][pred] += 1
        if pred == actual:
            if actual in per_cat:
                per_cat[actual]["tp"] += 1
        else:
            if actual in per_cat:
                per_cat[actual]["fn"] += 1
            if pred in per_cat:
                per_cat[pred]["fp"] += 1
            misclassified.append({"email_id": eid, "expected": actual, "predicted": pred})

    correct = len(ids) - len(misclassified)
    accuracy = correct / len(ids) if ids else 0.0
    by_category = {}
    for c in CATEGORIES:
        p, r, f = _f1(**per_cat[c])
        by_category[c] = {"precision": p, "recall": r, "f1": f, **per_cat[c],
                          "support": per_cat[c]["tp"] + per_cat[c]["fn"]}
    macro_f1 = sum(v["f1"] for v in by_category.values()) / len(CATEGORIES) if CATEGORIES else 0.0

    # Stage 2 -- the cases that cannot be certified, and why.
    edge_ids = [eid for eid in ids if gt[eid].get("status") == "NEEDS_REVIEW"]
    edge_rows, edge_correct = [], 0
    for eid in edge_ids:
        actual = gt[eid].get("review_reason")
        pred = predictions[eid].get("review_reason")
        ok = predictions[eid].get("status") == "NEEDS_REVIEW" and pred == actual
        edge_correct += ok
        edge_rows.append({"email_id": eid, "expected": actual, "predicted": pred, "ok": ok})
    edge_recall = edge_correct / len(edge_ids) if edge_ids else None

    # Stage 3 -- the field-level verdict, on the pairs that could be compared.
    doc_ids = [eid for eid in ids
               if gt[eid].get("category") == "BL_COMPARISON"
               and gt[eid].get("status") != "NEEDS_REVIEW"]
    dtp = dfp = dfn = exact = 0
    defect_rows = []
    for eid in doc_ids:
        a_def, p_def = gt[eid].get("has_defect", False), predictions[eid].get("has_defect", False)
        a_fields = set(gt[eid].get("defect_fields") or [])
        p_fields = set(predictions[eid].get("defect_fields") or [])
        dtp += a_def and p_def
        dfn += a_def and not p_def
        dfp += p_def and not a_def
        matched = a_fields == p_fields and a_def == p_def
        exact += matched
        if not matched:
            defect_rows.append({"email_id": eid, "expected": sorted(a_fields),
                                "predicted": sorted(p_fields)})
    dp, dr, df1 = _f1(dtp, dfp, dfn)

    return {
        "scored": len(ids),
        "classification": {
            "accuracy": accuracy, "correct": correct, "total": len(ids),
            "macro_f1": macro_f1, "by_category": by_category,
            "confusion": confusion, "misclassified": misclassified,
        },
        "edge_cases": {
            "recall": edge_recall, "correct": edge_correct, "total": len(edge_ids),
            "rows": edge_rows,
        },
        "comparison": {
            "precision": dp, "recall": dr, "f1": df1,
            "exact_match": (exact / len(doc_ids)) if doc_ids else None,
            "exact_matched": exact, "total": len(doc_ids), "mismatched_rows": defect_rows,
        },
    }


def headline(result: dict) -> dict[str, float]:
    """The five numbers the baseline gate compares, rounded once, in one place."""
    out = {
        "classification_accuracy": round(result["classification"]["accuracy"], 4),
        "macro_f1": round(result["classification"]["macro_f1"], 4),
    }
    if result["edge_cases"]["recall"] is not None:
        out["edge_case_recall"] = round(result["edge_cases"]["recall"], 4)
    if result["comparison"]["exact_match"] is not None:
        out["defect_f1"] = round(result["comparison"]["f1"], 4)
        out["exact_match_rate"] = round(result["comparison"]["exact_match"], 4)
    return out


def cases(predictions: dict[str, dict], gt: dict[str, dict] | None = None) -> list[dict]:
    """Every scored email, what ground truth says, and where the two part ways."""
    gt = ground_truth() if gt is None else gt
    out = []
    for eid in sorted(predictions):
        if eid not in gt:
            continue
        truth, pred = gt[eid], predictions[eid]
        checks = {
            "category": truth["category"] == pred["category"],
            "status": truth.get("status") == pred.get("status"),
            "review_reason": truth.get("review_reason") == pred.get("review_reason"),
            "defect_fields": sorted(truth.get("defect_fields") or [])
                             == sorted(pred.get("defect_fields") or []),
        }
        out.append({
            "email_id": eid,
            "truth": {k: truth.get(k) for k in
                      ("category", "status", "review_reason", "has_defect", "defect_fields")},
            "predicted": {k: pred.get(k) for k in
                          ("category", "status", "review_reason", "has_defect", "defect_fields")},
            "checks": checks,
            "ok": all(checks.values()),
        })
    return out


# --------------------------------------------------------------- speed and cost

# Engines that never call a model. Their time is real but it is not the model's,
# and mixing the two makes a fast model look slow on a document that took a
# second to parse.
DETERMINISTIC = ("deterministic",)


def sample(record: dict) -> dict:
    """The timing and token facts of one processed email, without its text.

    Returned rather than accumulated so a caller can summarise a corpus without
    holding every payload in memory.
    """
    engines: dict[str, dict] = {}
    prompt = completion = calls = reported = 0
    billed = 0.0
    for trace in record.get("traces") or []:
        name = trace.get("engine") or "?"
        slot = engines.setdefault(name, {"calls": 0, "ms": 0.0, "tokens": 0,
                                         "model_calls": 0, "cost": 0.0})
        slot["calls"] += 1
        slot["ms"] += trace.get("ms") or 0.0
        tokens = trace.get("tokens") or {}
        used = (tokens.get("prompt") or 0) + (tokens.get("completion") or 0)
        slot["tokens"] += used
        # Some providers bill the call and say what it cost. Preferred over any
        # rate table, because it is what was actually charged.
        for step in trace.get("steps") or []:
            spent = (step.get("data") or {}).get("cost") or 0.0
            billed += spent
            slot["cost"] += spent
        if trace.get("backend") not in DETERMINISTIC:
            calls += 1
            slot["model_calls"] += 1
            if tokens:
                reported += 1
        prompt += tokens.get("prompt") or 0
        completion += tokens.get("completion") or 0
    return {
        "ms": record.get("total_ms") or 0.0,
        "prompt": prompt, "completion": completion,
        "model_calls": calls, "calls_reporting_tokens": reported,
        "billed": billed,
        "engines": engines,
    }


def _quantile(values: list[float], q: float) -> float | None:
    """Nearest-rank, so the number returned is one that actually happened."""
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return ordered[idx]


def usage(samples: list[dict]) -> dict:
    """What a run cost: wall time per email, and tokens where they were reported.

    `calls_reporting_tokens` is carried through deliberately. Extraction calls a
    model without recording its usage, so a total presented as complete would be
    an undercount -- and an undercount of cost is the kind of number people make
    budget decisions on.
    """
    # One shape whether or not there is anything to summarise: a caller reading
    # usage["tokens"]["prompt"] should not have to know the list was empty.
    times = [s["ms"] for s in samples] or [0.0]
    prompt = sum(s["prompt"] for s in samples)
    completion = sum(s["completion"] for s in samples)
    calls = sum(s["model_calls"] for s in samples)
    reported = sum(s["calls_reporting_tokens"] for s in samples)
    billed = sum(s.get("billed") or 0.0 for s in samples)

    engines: dict[str, dict] = {}
    for s in samples:
        for name, slot in s["engines"].items():
            agg = engines.setdefault(name, {"calls": 0, "ms": 0.0, "tokens": 0,
                                            "model_calls": 0, "cost": 0.0})
            for k in ("calls", "ms", "tokens", "model_calls", "cost"):
                agg[k] += slot[k]
    for name, agg in engines.items():
        agg["mean_ms"] = agg["ms"] / agg["calls"] if agg["calls"] else 0.0
        agg["share_of_time"] = agg["ms"] / sum(times) if sum(times) else 0.0

    return {
        "emails": len(samples),
        "total_ms": sum(times),
        "mean_ms": sum(times) / len(times) if samples else 0.0,
        "median_ms": _quantile(times, 0.5),
        "p95_ms": _quantile(times, 0.95),
        "slowest_ms": max(times),
        "tokens": {"prompt": prompt, "completion": completion, "total": prompt + completion},
        "mean_tokens": (prompt + completion) / len(samples) if samples else 0.0,
        "model_calls": calls,
        "calls_reporting_tokens": reported,
        "token_coverage": (reported / calls) if calls else None,
        # What providers actually charged, where they said so. Zero means nobody
        # reported a cost, not that the run was free.
        "billed": billed,
        "by_engine": dict(sorted(engines.items(), key=lambda kv: -kv[1]["ms"])),
    }


# ------------------------------------------------------------------- pricing

PRICES_PATH = config.DATA_DIR / "model_prices.json"


def prices() -> dict[str, dict]:
    """Rates per million tokens, keyed the same way the benchmark keys models.

    A committed file rather than a built-in table: rates change, they differ per
    provider for the same model, and a number guessed here would be shown as a
    dollar figure somebody budgets against. An unpriced model reports no cost
    rather than a plausible one.
    """
    if not PRICES_PATH.exists():
        return {}
    return json.loads(PRICES_PATH.read_text(encoding="utf-8"))


def set_price(key: str, input_per_m: float | None, output_per_m: float | None) -> dict:
    current = prices()
    if input_per_m is None and output_per_m is None:
        current.pop(key, None)
    else:
        current[key] = {"input_per_m": input_per_m, "output_per_m": output_per_m,
                        "currency": "USD"}
    PRICES_PATH.parent.mkdir(parents=True, exist_ok=True)
    PRICES_PATH.write_text(json.dumps(current, indent=2, sort_keys=True) + chr(10),
                           encoding="utf-8")
    return current


def cost(usage_: dict, price: dict | None) -> dict | None:
    """Reported spend wins over a rate table; rates only fill the gap."""
    if usage_.get("billed") and usage_.get("emails"):
        per_email = usage_["billed"] / usage_["emails"]
        return {"currency": "USD", "input_per_m": None, "output_per_m": None,
                "total": usage_["billed"], "per_email": per_email,
                "projected_corpus": per_email * len(ground_truth()),
                "complete": True, "source": "reported by the provider"}
    return _cost_from_rates(usage_, price)


def _cost_from_rates(usage_: dict, price: dict | None) -> dict | None:
    """What the reported tokens came to, for providers that do not bill per call.

    Both figures carry the same caveat the token totals do: calls that never
    reported usage are not in them, so this is a floor. The projection is
    per-email cost times the corpus size -- an estimate, and labelled as one
    wherever it is shown.
    """
    if not price or not usage_.get("emails"):
        return None
    rate_in, rate_out = price.get("input_per_m"), price.get("output_per_m")
    if rate_in is None and rate_out is None:
        return None
    tokens = usage_["tokens"]
    total = (tokens["prompt"] / 1e6) * (rate_in or 0.0)         + (tokens["completion"] / 1e6) * (rate_out or 0.0)
    per_email = total / usage_["emails"]
    return {
        "currency": price.get("currency", "USD"),
        "input_per_m": rate_in, "output_per_m": rate_out,
        "total": total,
        "per_email": per_email,
        "projected_corpus": per_email * len(ground_truth()),
        "complete": usage_.get("token_coverage") in (None, 1.0),
        "source": "calculated from the rates you set",
    }


