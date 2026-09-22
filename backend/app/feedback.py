"""What happens to a human correction after the reviewer saves it.

Three things, deliberately kept apart, because they differ in how far they reach:

  1. override -- the correction changes what this one email shows: the field
     verdict, the comparison status, the recommended action, the draft, whether
     it is still in the review queue. It reaches exactly one email and takes
     effect immediately.

  2. counters -- how often the same disagreement has come up. Two of them, because
     "this happened again" means two different things: the same pair of spellings
     recurring is a missing alias, while one rule being overruled across many
     different values is a rule that is too strict. They change no verdict; they
     exist so a decision about the rules can be made on a number instead of a
     hunch.

Approving a pair into the mapping library is a third thing and lives in
mappings.py, because it is the only one that changes future emails.

Overrides are applied when a record is read, never when it is processed. The
stored result stays the engine's own output -- which is what the benchmark scores
and what the deviation list is measured against, so neither can be flattered by
the answers a reviewer supplied.
"""
from __future__ import annotations

import json
from collections import defaultdict

from . import db, mappings
from .engines.compare import summarise
from .engines.decide import decide
from .engines.normalize import norm_entity, norm_port, normalise

ENTITY_FIELDS = ("shipper", "consignee", "notify_party")
PORT_FIELDS = ("port_of_loading", "port_of_discharge")
KINDS = ("category", "field", "verdict", "review_reason", "resolve")

# How many times one disagreement has to recur before the Improvement page stops
# logging it and starts suggesting something. Picked, not measured -- raise it if
# suggestions start arriving before they are worth acting on.
SUGGEST_AFTER = 5


def _row(r) -> dict:
    d = dict(r)
    d["context"] = json.loads(d["context"]) if d.get("context") else {}
    return d


def rows() -> list[dict]:
    return [_row(r) for r in db.conn().execute(
        "SELECT * FROM feedback ORDER BY id DESC").fetchall()]


def rows_for(email_id: str) -> list[dict]:
    return [_row(r) for r in db.conn().execute(
        "SELECT * FROM feedback WHERE email_id=? ORDER BY id", (email_id,)).fetchall()]


def kind_of(field: str) -> str | None:
    """Which mapping table a field's values belong in, if any."""
    if field in ENTITY_FIELDS:
        return "entity"
    if field in PORT_FIELDS:
        return "port"
    return None


def norm_pair(field: str, si: str | None, bl: str | None) -> tuple[str | None, str | None]:
    """The two values as the comparison engine sees them."""
    kind = kind_of(field)
    fn = norm_entity if kind == "entity" else norm_port if kind == "port" else None
    if fn is None:
        return None, None
    return fn(si or ""), fn(bl or "")


# ---------------------------------------------------------------- 1. overrides

def _latest(rows_: list[dict]) -> dict[tuple[str, str | None], dict]:
    """Last correction wins, per (kind, target). Reviewers change their minds."""
    out: dict[tuple[str, str | None], dict] = {}
    for r in rows_:                       # rows_for() returns oldest first
        out[(r["kind"], r["target"])] = r
    return out


def apply_overrides(record: dict) -> dict:
    """Layer this email's corrections over the engine's own result.

    Returns a new record. Every override is recorded as a step in an extra trace
    and names the reviewer in the rule column, so nothing a human decided can be
    mistaken for something the engine worked out.
    """
    corrections = rows_for(record["email_id"])
    record = dict(record)
    record["feedback"] = list(reversed(corrections))
    record["resolved"] = False
    record["overridden"] = False
    if not corrections:
        return record

    latest = _latest(corrections)
    steps: list[dict] = []
    comparison = json.loads(json.dumps(record.get("comparison"))) if record.get("comparison") else None

    for (kind, target), r in latest.items():
        to = r["corrected_to"]
        if kind == "resolve":
            record["resolved"] = to != "reopen"
            steps.append({"name": "resolve",
                          "detail": f"{r['reviewer']} marked this case {to}"})

        elif kind == "category":
            record["classification"] = dict(record["classification"],
                                            category=to, reason=f"corrected by {r['reviewer']}")
            steps.append({"name": "category",
                          "detail": f"{r['reviewer']} changed the category from {r['was']} to {to}"})

        elif kind == "review_reason":
            record["review_reason_override"] = to
            steps.append({"name": "review_reason",
                          "detail": f"{r['reviewer']} reclassified the blocker as {to}"})

        elif kind == "field" and comparison and target in comparison["detail"]:
            side = (r["context"] or {}).get("side", "bl")
            cell = comparison["detail"][target][side]
            cell["raw"] = to
            cell["value"] = normalise(target, to)
            cell["source"] = f"human ({r['reviewer']})"
            comparison["detail"][target]["rule"] = f"recompared after {r['reviewer']} corrected the {side.upper()} value"
            comparison["detail"][target]["status"] = _recompare(target, comparison["detail"][target])
            steps.append({"name": f"field:{target}",
                          "detail": f"{r['reviewer']} corrected the {side.upper()} {target} "
                                    f"from {r['was']!r} to {to!r}"})

        elif kind == "verdict" and comparison and target in comparison["detail"]:
            cell = comparison["detail"][target]
            orig_status = cell["status"]
            is_both_discrepancy = (to in ("MISMATCH", "MISSING") and orig_status in ("MISMATCH", "MISSING"))
            if to in ("reset", "revert") or to == orig_status or is_both_discrepancy:
                # Flipped and flipped back, or explicitly reverted. The reviewer
                # ended up where the engine already was (e.g. both are non-matching
                # discrepancies, or identical status) -- restore the engine's original rule.
                continue
            overruled = (r["context"] or {}).get("rule", cell["rule"])
            cell["status"] = to
            cell["rule"] = f"human_override ({r['reviewer']}, {r['created_at'][:10]})"
            cell["overruled_rule"] = overruled
            steps.append({"name": f"verdict:{target}",
                          "detail": f"{r['reviewer']} overruled {target}: "
                                    f"{r['was']} -> {to} (engine said {overruled})"})

    if comparison and steps:
        comparison, _why = summarise(comparison["detail"])
        record["comparison"] = comparison

    if steps:
        record["overridden"] = True
        decision, _t = decide(record, record["classification"],
                              record.get("comparison"), record.get("blockers") or [])
        record["decision"] = decision
        if record["resolved"]:
            decision["needs_judgement"] = False
            decision["needs_approval"] = False
        record["traces"] = list(record.get("traces") or []) + [{
            "trace_id": "override",
            "engine": "human review",
            "inputs": {"corrections": len(corrections)},
            "steps": [dict(s, data={}, ms=0.0) for s in steps],
            "output": {"resolved": record["resolved"]},
            "why": f"{len(steps)} human correction(s) applied on top of the engine result",
            "model": None, "backend": "human", "confidence": None,
            "escalated": False, "tokens": {}, "ms": 0.0,
        }]
    elif record["resolved"]:
        record["decision"] = dict(record["decision"],
                                  needs_judgement=False, needs_approval=False)
    return record


def _recompare(field: str, cell: dict) -> str:
    """Re-run one field's verdict after a value was corrected by hand."""
    from .engines.compare import _compare_field
    from .trace import Field
    def side(d):
        return Field(name=field, raw=d.get("raw"), value=d.get("value"),
                     source=d.get("source") or "missing")
    status, _rule = _compare_field(field, side(cell["si"]), side(cell["bl"]))
    return status


def overridden_ids() -> set[str]:
    return {r["email_id"] for r in rows()}


# ---------------------------------------------------------------- 2. counters

def _verdict_corrections() -> list[dict]:
    """Corrections that say a MISMATCH should have been a MATCH."""
    return [r for r in rows()
            if r["kind"] == "verdict" and r["corrected_to"] == "MATCH"
            and (r["context"] or {}).get("to_library")]


def pair_counts() -> list[dict]:
    """Counter A -- the same two spellings, overruled again.

    A recurring pair is a missing alias. It is fixable by approving one entry,
    and that approval cannot affect any other value.
    """
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in _verdict_corrections():
        ctx = r["context"]
        a, b = ctx.get("norm_si"), ctx.get("norm_bl")
        kind = kind_of(r["target"] or "")
        if not a or not b or a == b or not kind:
            continue
        groups[(kind, *sorted((a, b)))].append(r)

    out = []
    for (kind, a, b), hits in groups.items():
        out.append({
            "kind": kind, "a": a, "b": b,
            "count": len(hits),
            "field": hits[-1]["target"],
            "emails": sorted({h["email_id"] for h in hits}),
            "example": {"si": hits[-1]["context"].get("si"),
                        "bl": hits[-1]["context"].get("bl")},
            "approved": bool(mappings.approved(kind, a, b)),
        })
    return sorted(out, key=lambda r: -r["count"])


def rule_counts() -> list[dict]:
    """Counter B -- one rule overruled across many different values.

    Unlike a recurring pair, this cannot be fixed by an alias: the rule itself is
    too strict. Fixing it means changing a threshold or adding a branch, which
    reaches every email, so it goes to a developer and a pull request.
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in _verdict_corrections():
        rule = (r["context"] or {}).get("rule")
        if rule:
            groups[rule].append(r)

    out = []
    for rule, hits in groups.items():
        distinct = {(h["context"].get("norm_si"), h["context"].get("norm_bl")) for h in hits}
        out.append({
            "rule": rule,
            "count": len(hits),
            "distinct_pairs": len(distinct),
            "fields": sorted({h["target"] for h in hits if h["target"]}),
            "emails": sorted({h["email_id"] for h in hits}),
            "suggest": len(distinct) >= SUGGEST_AFTER,
        })
    return sorted(out, key=lambda r: -r["count"])


def occurrence(field: str, si: str | None, bl: str | None) -> dict:
    """What to tell the reviewer the moment they overrule a verdict.

    The message escalates with the count, so the first one reads as bookkeeping
    and the fifth reads as a finding.
    """
    kind = kind_of(field)
    a, b = norm_pair(field, si, bl)
    if not kind or not a or not b or a == b:
        return {"kind": None, "count": 0, "known": False}
    key = tuple(sorted((a, b)))
    match = next((p for p in pair_counts()
                  if p["kind"] == kind and (p["a"], p["b"]) == key), None)
    return {
        "kind": kind, "a": key[0], "b": key[1], "field": field,
        "count": match["count"] if match else 0,
        "emails": match["emails"] if match else [],
        "approved": bool(mappings.approved(kind, a, b)),
        "suggest_after": SUGGEST_AFTER,
    }


def blast_radius(kind: str, a: str, b: str) -> dict:
    """Which already-processed emails approving this pair would change.

    Read from stored results rather than by re-running the pipeline: re-running
    would call the model again, and the reviewer is waiting. Every email this
    corpus has seen is in the table already.
    """
    fields = ENTITY_FIELDS if kind == "entity" else PORT_FIELDS
    key = {a, b}
    would_change, already = [], []
    seen: set[str] = set()
    for row in db.conn().execute(
            "SELECT email_id, run_id, payload FROM results ORDER BY run_id DESC"):
        if row["email_id"] in seen:
            continue
        seen.add(row["email_id"])
        comparison = (json.loads(row["payload"]) or {}).get("comparison")
        if not comparison:
            continue
        for field in fields:
            cell = comparison["detail"].get(field)
            if not cell:
                continue
            na, nb = norm_pair(field, cell["si"]["raw"], cell["bl"]["raw"])
            if not na or not nb or {na, nb} != key:
                continue
            (would_change if cell["status"] != "MATCH" else already).append(
                {"email_id": row["email_id"], "field": field, "status": cell["status"]})
    return {
        "kind": kind, "a": a, "b": b,
        "would_change": would_change,
        "already_match": already,
        "scanned": len(seen),
    }


def export() -> dict:
    """The payload the Improvement page renders."""
    pairs = pair_counts()
    return {
        "feedback_count": len(rows()),
        "overridden_emails": len(overridden_ids()),
        "pair_counts": pairs,
        "rule_counts": rule_counts(),
        "mappings": mappings.entries(),
        "suggest_after": SUGGEST_AFTER,
        # Kept so the existing Improvement page keeps rendering while its tabs
        # are rebuilt around the two counters.
        "alias_suggestions": [
            {"field": p["field"], "from": p["example"]["si"], "to": p["example"]["bl"],
             "normalised_from": p["a"], "normalised_to": p["b"],
             "email_id": p["emails"][-1], "count": p["count"],
             "suggestion": f"treat {p['a']!r} and {p['b']!r} as the same {p['field']}"}
            for p in pairs],
    }
