"""One aggregate view of a run, for the dashboard.

The per-row columns in `results` answer "how many of each"; the questions a
stakeholder actually asks -- which field goes wrong most often, how much of the
work the model had to do, where the time went -- only exist inside the stored
payloads. Scanning them costs ~200ms for 520 emails, which is cheaper than
denormalising the same facts into columns and keeping them true.
"""
from __future__ import annotations

import json
import math
from collections import Counter

from . import config, db, feedback
from .engines.decide import NEEDS_JUDGEMENT


# Most recent result per email, across every run. See main._scope.
_LATEST_PER_EMAIL = (
    "r.run_id = (SELECT MAX(r2.run_id) FROM results r2 WHERE r2.email_id = r.email_id)"
)


def build(run_id: int | None = None) -> dict:
    # The router's own threshold, not a second hardcoded one that can drift
    # away from it -- these were 0.6 here against 0.8 in the router.
    threshold = math.exp(config.ESCALATE_LOGP)
    conn = db.conn()
    if run_id is not None:
        run = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        rows = conn.execute(
            "SELECT payload FROM results r WHERE r.run_id=?", (run_id,)).fetchall()
        scope = {"kind": "run", "runs": 1}
    else:
        run = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        rows = conn.execute(
            f"SELECT r.payload FROM results r WHERE {_LATEST_PER_EMAIL}").fetchall()
        n_runs = conn.execute(
            "SELECT COUNT(*) FROM runs WHERE id IN (SELECT DISTINCT run_id FROM results)"
        ).fetchone()[0]
        scope = {"kind": "all", "runs": n_runs}
    records = [json.loads(r["payload"]) for r in rows]
    if not records:
        return {"run": dict(run) if run else None, "count": 0, "scope": scope}

    n = len(records)
    by_category: Counter = Counter()
    by_action: Counter = Counter()
    by_verdict: Counter = Counter()
    defect_fields: Counter = Counter()
    missing_fields: Counter = Counter()
    field_sources: Counter = Counter()
    doc_formats: Counter = Counter()
    cls_methods: Counter = Counter()
    total_docs = 0
    scanned_docs = 0
    prompt_tokens = 0
    completion_tokens = 0
    blockers: Counter = Counter()
    engine_ms: dict[str, list[float]] = {}
    engine_calls: Counter = Counter()

    escalated = needs_approval = needs_judgement = drafts = with_defects = 0
    confidences: list[float] = []
    attention: list[dict] = []
    llm_cases: list[dict] = []
    vlm_cases: list[dict] = []
    missing_cases: list[dict] = []

    for rec in records:
        cls = rec.get("classification") or {}
        dec = rec.get("decision") or {}
        cmp_ = rec.get("comparison")

        by_category[cls.get("category") or "UNKNOWN"] += 1
        by_action[dec.get("action") or "UNKNOWN"] += 1
        escalated += bool(cls.get("escalated"))
        needs_approval += bool(dec.get("needs_approval"))
        needs_judgement += dec.get("action") in NEEDS_JUDGEMENT
        drafts += bool(dec.get("draft"))
        if cls.get("confidence") is not None:
            confidences.append(float(cls["confidence"]))

        reason = cls.get("reason") or ""
        routing = cls.get("routing") or {}
        if "Submits shipping instruction" in reason or routing.get("method") == "deterministic_rule":
            cls_methods["deterministic_fast_path"] += 1
        elif cls.get("escalated") or routing.get("fallback_used"):
            cls_methods["escalated_fallback"] += 1
        elif cls.get("unclassified"):
            cls_methods["unclassified"] += 1
        else:
            cls_methods["primary_model"] += 1

        for b in rec.get("blockers") or []:
            # Collapse the variable tail so the counts group usefully.
            blockers[b.split(";")[0].split("--")[0].strip()[:70]] += 1

        if cmp_:
            by_verdict[cmp_["status"]] += 1
            with_defects += bool(cmp_.get("has_defect"))
            for f in cmp_.get("defect_fields") or []:
                defect_fields[f] += 1
            for f in cmp_.get("missing_fields") or []:
                missing_fields[f] += 1

        for doc_key, doc in (rec.get("documents") or {}).items():
            total_docs += 1
            name = doc.get("name") or doc.get("path") or doc_key
            ext = name.split(".")[-1].lower() if "." in name else "other"
            doc_formats[ext] += 1
            fields = doc.get("fields") or {}
            has_vlm = any((f.get("source") == "vlm") for f in fields.values())
            if doc.get("image") or has_vlm:
                scanned_docs += 1
            for field in fields.values():
                field_sources[field.get("source") or "missing"] += 1

            llm_fields = {k: f.get("value") for k, f in fields.items() if f.get("source") == "llm"}
            vlm_fields = {k: f.get("value") for k, f in fields.items() if f.get("source") == "vlm"}
            missing_f = [k for k, f in fields.items() if f.get("source") == "missing"]
            if llm_fields:
                llm_cases.append({
                    "email_id": rec["email_id"],
                    "subject": rec.get("subject"),
                    "doc_name": name,
                    "fields": llm_fields,
                })
            if vlm_fields:
                vlm_cases.append({
                    "email_id": rec["email_id"],
                    "subject": rec.get("subject"),
                    "doc_name": name,
                    "fields_count": len(vlm_fields),
                    "fields": vlm_fields,
                })
            if missing_f:
                missing_cases.append({
                    "email_id": rec["email_id"],
                    "subject": rec.get("subject"),
                    "doc_name": name,
                    "missing_fields": missing_f,
                })

        for t in rec.get("traces") or []:
            engine_ms.setdefault(t["engine"], []).append(t.get("ms") or 0.0)
            engine_calls[t["engine"]] += 1
            toks = t.get("tokens") or {}
            prompt_tokens += int(toks.get("prompt") or 0)
            completion_tokens += int(toks.get("completion") or 0)

        if dec.get("action") in NEEDS_JUDGEMENT:
            attention.append({
                "email_id": rec["email_id"],
                "subject": rec.get("subject"),
                "action": dec.get("action"),
                "why": dec.get("why"),
                "category": cls.get("category"),
                "confidence": cls.get("confidence"),
                "defect_fields": (cmp_ or {}).get("defect_fields") or [],
            })

    # Discrepancies first, then the merely incomplete.
    attention.sort(key=lambda a: (a["action"] != "FLAG_DISCREPANCY", a["email_id"]))

    compared = sum(by_verdict.values())
    total_fields = sum(field_sources.values())
    cls_total = sum(cls_methods.values()) or n
    total_engine_time = sum(sum(v) for v in engine_ms.values())

    rule_extractions = field_sources.get("deterministic", 0)
    fast_path_cls = cls_methods.get("deterministic_fast_path", 0)
    saved_calls = (rule_extractions // 7) + fast_path_cls
    estimated_saved_cost = round(saved_calls * 0.0012, 4)

    technical_summary = {
        "extraction": {
            "total_fields": total_fields,
            "sources": dict(field_sources),
            "rates": {
                k: round(v / max(total_fields, 1) * 100, 2)
                for k, v in field_sources.items()
            },
            "total_docs": total_docs,
            "scanned_docs": scanned_docs,
            "scan_rate": round(scanned_docs / max(total_docs, 1) * 100, 2),
            "formats": dict(doc_formats),
            "llm_cases": llm_cases,
            "vlm_cases": vlm_cases,
            "missing_cases": missing_cases[:30],
        },
        "classification": {
            "total_emails": n,
            "methods": dict(cls_methods),
            "rates": {
                k: round(v / max(cls_total, 1) * 100, 2)
                for k, v in cls_methods.items()
            },
        },
        "engines": {
            e: {
                "avg_ms": round(sum(v) / len(v), 1),
                "total_ms": round(sum(v), 1),
                "calls": engine_calls[e],
                "share_pct": round(sum(v) / max(total_engine_time, 0.001) * 100, 1),
            }
            for e, v in sorted(engine_ms.items())
        },
        "tokens": {
            "prompt": prompt_tokens,
            "completion": completion_tokens,
            "total": prompt_tokens + completion_tokens,
        },
        "total_engine_time_ms": round(total_engine_time, 1),
        "saved_calls": saved_calls,
        "estimated_saved_cost_usd": estimated_saved_cost,
    }

    out: dict = {
        "run": dict(run) if run else None,
        "scope": scope,
        "count": n,
        "headline": {
            "emails": n,
            "documents_compared": compared,
            "defects_found": with_defects,
            "needs_approval": needs_approval,
            "needs_judgement": needs_judgement,
            "drafts_written": drafts,
            "escalated": escalated,
            "escalation_rate": round(escalated / n, 4),
            "avg_ms": round(sum(r.get("total_ms") or 0 for r in records) / n, 1),
            "avg_confidence": round(sum(confidences) / len(confidences), 3) if confidences else None,
            "auto_cleared": by_action.get("AUTO_CLEAR", 0),
            "no_human_needed": n - needs_approval,
        },
        # The operational story, in the order the work happens.
        "funnel": [
            {"stage": "Received", "count": n,
             "note": "emails in the operations inbox"},
            {"stage": "Triaged", "count": n - by_action.get("IGNORE", 0),
             "note": f"{by_action.get('IGNORE', 0)} discarded as spam"},
            {"stage": "Needs documents", "count": by_category.get("BL_COMPARISON", 0),
             "note": "classified as a BL to check against an SI"},
            {"stage": "Compared", "count": compared,
             "note": f"{by_category.get('BL_COMPARISON', 0) - compared} could not be compared"},
            {"stage": "Discrepancy found", "count": with_defects,
             "note": "SI and BL disagree on at least one field"},
        ],
        "by_category": dict(by_category),
        "by_action": dict(by_action),
        "by_verdict": dict(by_verdict),
        "defect_fields": dict(defect_fields.most_common()),
        "missing_fields": dict(missing_fields.most_common()),
        "field_sources": dict(field_sources),
        "blockers": dict(blockers.most_common(8)),
        "engine_ms": {
            e: {"avg": round(sum(v) / len(v), 1),
                "total": round(sum(v), 1),
                "calls": engine_calls[e]}
            for e, v in sorted(engine_ms.items())
        },
        "technical_summary": technical_summary,
        "attention": attention[:25],
        "attention_total": len(attention),
        "router": {
            "threshold_logp": config.ESCALATE_LOGP,
            "threshold": round(threshold, 3),
            "enabled": config.ESCALATION_ENABLED,
            "escalated": escalated,
            "low_confidence": sum(1 for c in confidences if c < threshold),
        },
        "confidence_histogram": _histogram(confidences),
    }

    gt_path = config.DATA_DIR / "ground_truth.json"
    if gt_path.exists():
        gt = json.loads(gt_path.read_text(encoding="utf-8"))
        scored = [(r, gt[r["email_id"]]) for r in records if r["email_id"] in gt]
        if scored:
            errors = [(r, t) for r, t in scored
                      if (r["classification"] or {}).get("category") != t["category"]]
            caught = sum(1 for r, _ in errors
                         if (r["classification"] or {}).get("confidence", 1) < threshold)
            out["accuracy"] = {
                "scored": len(scored),
                "correct": len(scored) - len(errors),
                "rate": round((len(scored) - len(errors)) / len(scored), 4),
                "errors": len(errors),
                "caught_by_router": caught,
                "worst": [
                    {"email_id": r["email_id"], "truth": t["category"],
                     "predicted": (r["classification"] or {}).get("category"),
                     "confidence": (r["classification"] or {}).get("confidence"),
                     "subject": r.get("subject")}
                    for r, t in errors[:15]
                ],
            }

    export = feedback.export()
    out["feedback"] = {
        "count": export.get("feedback_count", 0),
        "alias_suggestions": len(export.get("alias_suggestions", [])),
        "regression_cases": len(export.get("regression_cases", [])),
    }
    return out


def _histogram(values: list[float], buckets: int = 10) -> list[dict]:
    """Confidence spread -- shows whether the model is decisive or hedging."""
    if not values:
        return []
    counts = [0] * buckets
    for v in values:
        idx = min(buckets - 1, max(0, int(v * buckets)))
        counts[idx] += 1
    return [{"from": round(i / buckets, 1), "to": round((i + 1) / buckets, 1), "count": c}
            for i, c in enumerate(counts)]
