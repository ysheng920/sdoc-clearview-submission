"""Pairs of values a reviewer approved as meaning the same thing.

A lookup table, deliberately not a rule. An entry matches one pair of normalised
values and nothing else: approving 'east bright' = 'east bright trading' cannot
change the verdict on any other company, because there is no generalisation step
for it to leak through. That is why this is allowed to affect live comparisons
while a threshold change is not -- lowering the token-overlap number from 0.6 to
0.5 rewrites how *every* company name is judged, and no reviewer can see that
blast radius from inside one case.

An approval is still a global, lasting act: every future email that carries the
pair will match on it. So it is written to a committed file rather than the
database, which makes it show up as a reviewable diff, and CI re-runs the corpus
with it in place.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta

# Malaysia Standard Time (MYT: UTC+8, Asia/Kuala_Lumpur)
MYT = timezone(timedelta(hours=8), name="Asia/Kuala_Lumpur")

from . import config

PATH = config.DATA_DIR / "mappings.json"
KINDS = ("entity", "port")

_entries: dict[str, list[dict]] | None = None
_pairs: dict[str, dict[frozenset, dict]] = {}


def reload() -> dict[str, list[dict]]:
    """Re-read the file. Called on first use and after every approval."""
    global _entries
    if PATH.exists():
        raw = json.loads(PATH.read_text(encoding="utf-8"))
    else:
        raw = {}
    _entries = {kind: list(raw.get(kind) or []) for kind in KINDS}
    _pairs.clear()
    for kind, rows in _entries.items():
        _pairs[kind] = {frozenset((r["a"], r["b"])): r for r in rows}
    return _entries


def entries(kind: str | None = None) -> list[dict]:
    if _entries is None:
        reload()
    if kind:
        return list(_entries[kind])
    return [dict(r, kind=k) for k in KINDS for r in _entries[k]]


def approved(kind: str, a: str | None, b: str | None) -> dict | None:
    """The approval for this pair of normalised values, or None.

    Order-independent: a reviewer approving SI-vs-BL must also settle BL-vs-SI.
    """
    if not a or not b or a == b:
        return None
    if _entries is None:
        reload()
    return _pairs.get(kind, {}).get(frozenset((a, b)))


def rule_name(hit: dict) -> str:
    """What the comparison table shows instead of 'values_differ'.

    It names the person and the date on purpose: a verdict that came from a human
    decision should not be able to hide behind wording that sounds automatic.
    """
    return f"approved_alias ({hit.get('approved_by', 'operator')}, {hit.get('approved_at', '')[:10]})"


def approve(kind: str, a: str, b: str, *, approved_by: str = "operator",
            from_email: str | None = None, run_id: int | None = None,
            note: str | None = None) -> dict:
    """Add a pair to the table and write the file. Idempotent on the pair."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
    if not a or not b:
        raise ValueError("both sides must normalise to something")
    if a == b:
        raise ValueError("the two values already normalise the same; nothing to approve")

    existing = approved(kind, a, b)
    if existing:
        return existing

    entry = {
        "a": a, "b": b,
        "approved_by": approved_by,
        "approved_at": datetime.now(MYT).strftime("%Y-%m-%d %H:%M:%S"),
        "from_email": from_email,
        "run_id": run_id,
        "note": note,
    }
    current = {k: list(entries(k)) for k in KINDS}
    current[kind].append(entry)
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(current, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    reload()
    return entry


def revoke(kind: str, a: str, b: str) -> bool:
    """Remove a pair. An approval that turns out to be wrong has to be undoable."""
    if not approved(kind, a, b):
        return False
    current = {k: [r for r in entries(k)
                   if k != kind or frozenset((r["a"], r["b"])) != frozenset((a, b))]
               for k in KINDS}
    PATH.write_text(json.dumps(current, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    reload()
    return True
