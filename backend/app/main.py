"""FastAPI surface for the dashboard. Thin: all the thinking lives in engines/."""
from __future__ import annotations

import base64
import json
import math
import os
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import benchmark, config, dashboard, db, feedback, mappings, sampling
from .llm import client_for, get_client, runnable
from .engines import docs
from .engines.extract import extract
from .pipeline import (SIMULATED_DIR, _find_attachments, list_email_ids,
                       load_email, process)

app = FastAPI(title="sdoc-clearview", version="0.1.0")

# The Vite dev server runs on another port; loopback origins only.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"], allow_headers=["*"],
)


@app.get("/api/health")
def health():
    """Small, dependency-free readiness check for Cloud Run."""
    return {"status": "ok", "service": "sdoc-clearview"}


class RunRequest(BaseModel):
    limit: int | None = None
    workers: int | None = None
    # Per-bucket counts, e.g. {"bl_defect": 5, "SPAM": 2}. Takes precedence
    # over `limit`, which only ever returned the head of the corpus.
    quota: dict[str, int] | None = None
    # Skip emails a previous run already processed, so repeated runs walk
    # forward through the corpus instead of re-billing the same work.
    exclude_used: bool = True
    seed: int | None = None
    # Resolve the selection and return it without processing anything.
    # Verifying a quota should never be able to spend money by accident.
    dry_run: bool = False
    # Which model to run. Absent means whatever the process was started with.
    backend: str | None = None
    model: str | None = None
    # 'queue' hands the results to an operator; 'benchmark' scores them and
    # leaves the queue alone, so the same corpus can be run again per model.
    purpose: str = "queue"
    passcode: str | None = None


class FeedbackRequest(BaseModel):
    kind: str                      # category | field | verdict | review_reason | resolve
    corrected_to: str
    target: str | None = None
    was: str | None = None
    note: str | None = None
    # Which document the reviewer edited, when kind='field'.
    side: str | None = None        # si | bl
    # Whether this correction also belongs in the mapping library's tally. The
    # reviewer answers it, because only they can tell a one-off apart from a
    # naming gap, and a counter nobody filtered is not evidence of anything.
    to_library: bool = False


class LibraryRequest(BaseModel):
    record: bool


class ApproveRequest(BaseModel):
    kind: str                      # entity | port
    a: str
    b: str
    note: str | None = None


@app.on_event("startup")
def _sweep_interrupted_runs() -> None:
    removed = db.purge_legacy_mock_runs()
    if removed["runs"]:
        print(f"[startup] removed {removed['runs']} legacy mock run(s) "
              f"and {removed['results']} result(s)")
    swept = db.orphan_runs()
    if swept:
        print(f"[startup] closed {swept} run(s) left running by a restart")


@app.get("/api/config")
def get_config():
    client = get_client()
    from .llm import ClassificationRouter
    is_router = isinstance(client, ClassificationRouter)
    return {
        "backend": client.name,
        "model": getattr(client, "model", None),
        "cloud_available": bool(config.GEMINI_API_KEY),
        "cloud_model": "gemini-3.1-flash-lite" if config.GEMINI_API_KEY else None,
        "escalation_enabled": is_router or config.ESCALATION_ENABLED,
        "escalate_logp": config.ESCALATE_LOGP,
        "emails_available": len(list_email_ids()),
        "has_model": client.name != "deterministic",
    }


# One hand-written email may carry this much attachment, decoded. Generous for
# the documents this handles and small enough that a paste cannot exhaust the
# process: the whole payload is held in memory before anything is written.
SIM_MAX_BYTES = 8 * 1024 * 1024
SIM_SUFFIXES = ({".txt", ".pdf", ".docx", ".xlsx", ".csv", ".md"}
                | docs.IMAGE_SUFFIXES)   # a photo of a document is a document


class SimAttachment(BaseModel):
    filename: str
    # base64 of the file. Sent in the JSON body rather than as multipart so
    # this needs no python-multipart: these are hand-made demo documents, and
    # the 33% inflation costs nothing at this size.
    content_b64: str
    # 'si' | 'bl' | '' -- the reviewer says which document this is, because
    # _find_attachments otherwise has to guess it from the filename.
    role: str = ""


class SimulateRequest(BaseModel):
    subject: str = ""
    sender: str = ""
    body: str = ""
    attachments: list[SimAttachment] = []


def _next_sim_id() -> str:
    used = {p.stem for p in SIMULATED_DIR.glob("sim_*.json")} if SIMULATED_DIR.exists() else set()
    n = 1
    while f"sim_{n:03d}" in used:
        n += 1
    return f"sim_{n:03d}"


@app.post("/api/simulate")
def simulate(req: SimulateRequest):
    """Run one hand-written email through the same four engines as the corpus.

    Written to data/simulated/, never data/inbox/: the inbox is the labelled 520
    that sampling quotas and every benchmark number are measured against, and an
    invented email dropped in there would quietly move all of them.
    """
    if not (req.body.strip() or req.subject.strip() or req.attachments):
        raise HTTPException(422, "an email needs at least a subject, a body or an attachment")

    email_id = _next_sim_id()
    SIMULATED_DIR.mkdir(parents=True, exist_ok=True)

    total = 0
    written: list[str] = []
    for i, att in enumerate(req.attachments):
        try:
            raw = base64.b64decode(att.content_b64, validate=True)
        except Exception:
            raise HTTPException(422, f"{att.filename}: not valid base64")
        total += len(raw)
        if total > SIM_MAX_BYTES:
            raise HTTPException(413, f"attachments exceed {SIM_MAX_BYTES // 1024 // 1024} MB")
        suffix = Path(att.filename).suffix.lower()
        if suffix not in SIM_SUFFIXES:
            raise HTTPException(
                422, f"{att.filename}: {suffix or 'no extension'} cannot be read -- "
                     f"one of {', '.join(sorted(SIM_SUFFIXES))}")
        # The role goes in the filename because that is where _find_attachments
        # looks. Without it a single untagged file is classified by reading it,
        # which is a guess the reviewer already knows the answer to.
        role = att.role.lower()
        stem = f"{email_id}_{role.upper()}" if role in ("si", "bl") else f"{email_id}_{i}"
        out = SIMULATED_DIR / f"{stem}{suffix}"
        out.write_bytes(raw)
        written.append(f"simulated/{out.name}")

    email = {"email_id": email_id, "from": req.sender, "subject": req.subject,
             "body": req.body, "attachments": written}
    (SIMULATED_DIR / f"{email_id}.json").write_text(
        json.dumps(email, indent=2, ensure_ascii=False) + chr(10), encoding="utf-8")

    client = get_client()
    run_id = db.start_run(1, client.name, getattr(client, "model", ""), purpose="queue")
    try:
        record = process(email, client=client)
    except Exception as exc:  # noqa: BLE001 - a bad hand-made email is not a server fault
        db.finish_run(run_id, f"{type(exc).__name__}: {exc}")
        raise HTTPException(500, f"the pipeline failed on {email_id}: {exc}")
    db.save_result(run_id, record)
    db.finish_run(run_id)
    return {"run_id": run_id, "email_id": email_id, "record": get_email(email_id)}


@app.get("/api/pool")
def get_pool():
    """How many emails of each kind are left to sample."""
    return sampling.availability()


@app.delete("/api/pool")
def reset_pool(confirm: bool = False):
    """Clear the work queue, which is what makes every email selectable again.

    Destructive and irreversible for the queue, and deliberately not for anything
    else: benchmark runs are a record of what a model scored, they cost money to
    produce, and emptying an inbox is no reason to throw them away. Human
    corrections are keyed by email rather than by run and survive too.
    """
    if not confirm:
        raise HTTPException(400, "pass ?confirm=true -- this deletes the work queue")
    conn = db.conn()
    queue = "COALESCE(purpose, 'queue') = 'queue'"
    runs = conn.execute(f"SELECT COUNT(*) FROM runs WHERE {queue}").fetchone()[0]
    results = conn.execute(
        f"SELECT COUNT(*) FROM results WHERE run_id IN (SELECT id FROM runs WHERE {queue})"
    ).fetchone()[0]
    conn.execute(f"DELETE FROM results WHERE run_id IN (SELECT id FROM runs WHERE {queue})")
    conn.execute(f"DELETE FROM runs WHERE {queue}")
    conn.commit()
    kept = conn.execute(
        "SELECT COUNT(*) FROM runs WHERE COALESCE(purpose, 'queue') = 'benchmark'"
    ).fetchone()[0]
    return {"deleted_runs": runs, "deleted_results": results,
            "kept_benchmark_runs": kept, "pool": sampling.availability()}


@app.post("/api/demo/reset")
def reset_demo():
    """Reset system to clean demo baseline:
    - Predefined Approved Mappings loaded
    - 520 corpus results and 6 frozen demo cases restored
    """
    try:
        return db.reset_to_demo()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/runs")
def start_run(req: RunRequest):
    if req.purpose not in ("queue", "benchmark"):
        raise HTTPException(422, "purpose must be queue or benchmark")
    if req.purpose == "benchmark" and req.passcode != "686868":
        raise HTTPException(403, "Benchmark execution is protected. Invalid or missing 6-digit security passcode.")
    shortfall: dict[str, int] = {}
    if req.quota:
        ids, shortfall = sampling.pick(req.quota, seed=req.seed)
        if not ids:
            raise HTTPException(
                409, "nothing left to sample for that request -- lower the counts, "
                     "or reset the pool to make processed emails selectable again")
    else:
        # Legacy path: the head of the corpus, which is not a sample of anything.
        ids = list_email_ids()
        if req.exclude_used and req.purpose != "benchmark":
            used = sampling.used_ids()
            ids = [i for i in ids if i not in used]
        ids = ids[: req.limit] if req.limit else ids
        if not ids:
            raise HTTPException(404, "no emails left -- reset the pool or check SDOC_DATA_DIR")

    if req.dry_run:
        gt = sampling.ground_truth()
        by_bucket: dict[str, int] = {}
        for eid in ids:
            key = sampling.bucket_of(gt[eid]) if eid in gt else "unlabelled"
            by_bucket[key] = by_bucket.get(key, 0) + 1
        return {
            "dry_run": True, "run_id": None, "total": len(ids),
            "shortfall": shortfall, "by_bucket": by_bucket, "emails": ids,
            "note": "nothing was processed and no model was called",
        }

    try:
        # The validated Jev -> Gemini route is the default for both purposes.
        # An explicit choice is honoured either way: the picker used to be read
        # only for benchmarks, so choosing "rules only" in the run panel and
        # pressing Run still billed a full model run.
        client = client_for(req.backend, req.model) if req.backend else get_client()
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    run_id = db.start_run(len(ids), client.name, getattr(client, "model", ""),
                          purpose=req.purpose)
    threading.Thread(target=_execute,
                     args=(run_id, ids, req.workers or config.WORKERS, client),
                     daemon=True).start()
    return {"run_id": run_id, "total": len(ids), "shortfall": shortfall}


def _execute(run_id: int, ids: list[str], workers: int, client=None) -> None:
    """Run every email, and make sure a failure is never silent.

    A worker thread that dies leaves the run row saying "running" forever, with
    nothing in the log and no error in the UI -- which is the single worst thing
    to be debugging during a demo. Everything here exists to make that loud:
    per-email isolation so one bad email cannot end the run, BaseException so a
    MemoryError is recorded too, and a guarded finish so a failing write cannot
    swallow the reason it was called.
    """
    def one(email_id: str) -> dict:
        try:
            return process(load_email(email_id), client=client)
        except Exception as exc:  # noqa: BLE001 - this email fails, the run goes on
            traceback.print_exc()
            return {
                "email_id": email_id, "subject": None, "from": None, "body": "",
                "attachments": [], "blockers": [f"pipeline error: {type(exc).__name__}: {exc}"],
                "classification": {"category": "GENERAL", "confidence": 0.0,
                                   "reason": "the pipeline raised before it could classify",
                                   "escalated": False},
                "comparison": None, "documents": {},
                "decision": {"action": "HUMAN_REVIEW", "why": f"pipeline error: {exc}",
                             "needs_approval": True, "needs_judgement": True, "draft": None},
                "traces": [], "total_ms": 0.0,
            }

    error = None
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            pending = {pool.submit(one, email_id): email_id for email_id in ids}
            # as_completed, not map: map hands results back in submission order,
            # so one slow email held the progress counter at 519/520 while every
            # other result sat finished and unsaved. Progress should say what has
            # actually been done.
            for future in as_completed(pending, timeout=config.EMAIL_TIMEOUT * len(ids)):
                db.save_result(run_id, future.result())
    except TimeoutError:
        stuck = [email_id for future, email_id in pending.items() if not future.done()]
        error = f"gave up waiting on {len(stuck)} email(s): {', '.join(stuck[:5])}"
        traceback.print_exc()
    except BaseException as exc:  # noqa: BLE001 - including MemoryError / KeyboardInterrupt
        error = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        try:
            db.finish_run(run_id, error)
        except Exception:  # noqa: BLE001 - never let the bookkeeping hide the cause
            traceback.print_exc()


@app.get("/api/runs")
def list_runs():
    return [dict(r) for r in db.conn().execute(
        "SELECT * FROM runs ORDER BY id DESC LIMIT 20").fetchall()]


@app.get("/api/runs/{run_id}")
def get_run(run_id: int):
    row = db.conn().execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"run {run_id} not found")
    return dict(row)


def _resolve_run(run_id: int | None) -> int:
    rid = run_id or db.latest_run_id()
    if rid is None:
        raise HTTPException(404, "no runs yet -- POST /api/runs first")
    return rid


# Every view used to be scoped to one run, which contradicted the way runs are
# composed: the sampler excludes already-processed emails precisely so that
# successive runs accumulate coverage. Three runs of one email each left the
# dashboard showing one email. Without an explicit run_id the views now span
# every run, taking the most recent result for each email.
# A run belongs to one of two worlds and the queue only lives in one of them.
# Without this a 520-email benchmark lands in the operator's inbox as 520 new
# cases nobody asked for.
_QUEUE_ONLY = "COALESCE((SELECT purpose FROM runs WHERE runs.id = r.run_id), 'queue') = 'queue'"

_LATEST_PER_EMAIL = (
    "r.run_id = (SELECT MAX(r2.run_id) FROM results r2 "
    "JOIN runs u2 ON u2.id = r2.run_id "
    "WHERE r2.email_id = r.email_id AND COALESCE(u2.purpose, 'queue') = 'queue')"
)


# Filtering by model is not the same as filtering by run: a model usually spans
# several runs, and "the latest result" then has to mean the latest *within that
# model*, or a later run by a different model would hide it.
_LATEST_PER_EMAIL_FOR_MODEL = (
    "r.run_id = (SELECT MAX(r2.run_id) FROM results r2 "
    "JOIN runs u2 ON u2.id = r2.run_id "
    "WHERE r2.email_id = r.email_id AND u2.backend || ':' || u2.model = ?)"
)


def _scope(run_id: int | None, model: str | None = None) -> tuple[str, list]:
    """SQL predicate over `results r` for one run, one model, or the queue."""
    if run_id is not None:
        return "r.run_id = ?", [run_id]
    if db.conn().execute(
            f"SELECT 1 FROM results r WHERE {_QUEUE_ONLY} LIMIT 1").fetchone() is None:
        raise HTTPException(404, "no runs yet -- POST /api/runs first")
    if model:
        return f"{_LATEST_PER_EMAIL_FOR_MODEL} AND {_QUEUE_ONLY}", [model]
    return _LATEST_PER_EMAIL, []


@app.get("/api/models/runnable")
def get_runnable():
    """The models a run can be started with, here, now."""
    return {"models": runnable(), "default": get_client().name}


@app.get("/api/models")
def list_models():
    """Every model that has produced a stored result, cheaply.

    Counted in SQL rather than by reading payloads: this feeds a dropdown, and a
    dropdown should not cost a pass over the corpus.
    """
    rows = db.conn().execute(
        "SELECT runs.backend, runs.model, COUNT(DISTINCT r.email_id) AS emails, "
        "       COUNT(DISTINCT r.run_id) AS runs "
        "FROM results r JOIN runs ON runs.id = r.run_id "
        "WHERE COALESCE(runs.purpose, 'queue') = 'queue' "
        "  AND lower(COALESCE(runs.backend, '')) != 'mock' "
        "  AND lower(COALESCE(runs.model, '')) NOT LIKE 'mock%' "
        "GROUP BY runs.backend, runs.model ORDER BY emails DESC")
    return {"models": [
        {"key": f"{r['backend']}:{r['model']}", "backend": r["backend"],
         "model": r["model"], "emails": r["emails"], "runs": r["runs"]}
        for r in rows]}


def extract_real_customer(record: dict) -> tuple[str | None, str]:
    from_email = (record.get("from") or "").strip()
    docs = record.get("documents") or {}
    si_fields = (docs.get("si") or {}).get("fields") or {}
    bl_fields = (docs.get("bl") or {}).get("fields") or {}

    c = si_fields.get("consignee") or bl_fields.get("consignee") or {}
    s = si_fields.get("shipper") or bl_fields.get("shipper") or {}

    c_raw = (c.get("raw") or "").split("\n")[0].split(";")[0].split("|")[0].strip()
    s_raw = (s.get("raw") or "").split("\n")[0].split(";")[0].split("|")[0].strip()

    customer = c_raw or s_raw or None
    return customer, from_email


@app.get("/api/emails")
def list_emails(run_id: int | None = None, action: str | None = None,
                category: str | None = None, needs_approval: bool | None = None,
                needs_judgement: bool | None = None, model: str | None = None):
    if run_id is None and db.conn().execute(
            f"SELECT 1 FROM results r WHERE {_QUEUE_ONLY} LIMIT 1").fetchone() is None:
        return {"run_id": None, "count": 0, "emails": []}
    where, params = _scope(run_id, model)
    sql = ("SELECT r.email_id, r.category, r.confidence, r.escalated, "
           "r.comparison_status, r.action, r.needs_approval, r.needs_judgement, "
           "r.total_ms, r.payload FROM results r WHERE " + where)
    for column, value in (("action", action), ("category", category)):
        if value:
            sql += f" AND r.{column}=?"
            params.append(value)
    for column, flag in (("needs_approval", needs_approval),
                         ("needs_judgement", needs_judgement)):
        if flag is not None:
            sql += f" AND r.{column}=?"
            params.append(int(flag))
    rows = [dict(r) for r in db.conn().execute(sql + " ORDER BY r.email_id", params)]
    rid = run_id

    # Subjects and real customer details from actual pipeline records
    for r in rows:
        payload_str = r.pop("payload", None)
        payload_data = json.loads(payload_str) if payload_str else {}
        em = load_email(r["email_id"])
        r["subject"] = em.get("subject")
        r["from"] = em.get("from")
        c_name, c_email = extract_real_customer(payload_data)
        r["customer"] = c_name
        r["customer_email"] = c_email or em.get("from")
        r["blockers"] = payload_data.get("blockers", [])
        r["why"] = payload_data.get("decision", {}).get("why", "")
        r["attachments"] = payload_data.get("attachments") or em.get("attachments") or []
        # Keep the two confidence signals distinct for the operator UI.  Jev's
        # calibrated probability decides whether the case is routed; after a
        # fallback, the stored result confidence belongs to Gemini and is only a
        # self-reported score.  Returning the routing record lets the queue show
        # that handoff instead of presenting the two numbers as equivalent.
        classification = payload_data.get("classification") or {}
        routing = classification.get("routing")
        r["classification_routing"] = routing if isinstance(routing, dict) else {}

    # The stored columns are the engine's own verdict. Corrections are layered on
    # when a record is read, so the queue has to read them too -- otherwise a case
    # a reviewer already settled keeps its old badge and never leaves the queue.
    # Re-reading the whole record for those few is what keeps the row and the case
    # page from ever showing different verdicts.
    corrected = feedback.overridden_ids()
    for r in rows:
        r["resolved"] = False
        r["overridden"] = False
        if r["email_id"] not in corrected:
            continue
        full = get_email(r["email_id"], run_id, model)
        r.update(
            category=full["classification"]["category"],
            comparison_status=(full.get("comparison") or {}).get("status"),
            action=full["decision"]["action"],
            needs_approval=int(full["decision"]["needs_approval"]),
            needs_judgement=int(full["decision"]["needs_judgement"]),
            resolved=full.get("resolved", False),
            overridden=full.get("overridden", False),
        )
    return {"run_id": rid, "count": len(rows), "emails": rows}


def stored_record(email_id: str, run_id: int | None = None,
                  model: str | None = None) -> dict:
    """The engine's own result, with no corrections layered on.

    Kept separate from get_email because a correction has to be recorded against
    what the engine actually said. Reading it back off an already-corrected
    record makes the second correction cite the first one as the rule it
    overruled, and the deviation list then names a rule that does not exist.
    """
    where, params = _scope(run_id, model)
    row = db.conn().execute(
        f"SELECT r.payload FROM results r WHERE {where} AND r.email_id=?",
        [*params, email_id]).fetchone()
    if row is None:
        raise HTTPException(404, f"{email_id} has not been processed yet")
    record = json.loads(row["payload"])
    if record.get("comparison") is None and record.get("classification", {}).get("category") == "BL_COMPARISON":
        docs = record.get("documents") or {}
        if not docs:
            em = load_email(email_id)
            si_path, bl_path = _find_attachments(em)
            if si_path:
                si_fields, si_text, si_img, _ = extract(si_path)
                docs["si"] = {"name": si_path.name, "text": si_text, "image": si_img,
                              "fields": {k: v.to_dict() for k, v in si_fields.items()}}
            if bl_path:
                bl_fields, bl_text, bl_img, _ = extract(bl_path)
                docs["bl"] = {"name": bl_path.name, "text": bl_text, "image": bl_img,
                              "fields": {k: v.to_dict() for k, v in bl_fields.items()}}
            record["documents"] = docs
        si_dict = (docs.get("si") or {}).get("fields") or {}
        bl_dict = (docs.get("bl") or {}).get("fields") or {}
        if si_dict or bl_dict:
            from .engines.compare import compare
            from .trace import Field, Span
            si_f = {k: Field(**{**v, 'span': Span(**v['span']) if isinstance(v.get('span'), dict) else None}) for k, v in si_dict.items()}
            bl_f = {k: Field(**{**v, 'span': Span(**v['span']) if isinstance(v.get('span'), dict) else None}) for k, v in bl_dict.items()}
            cmp_res, _ = compare(si_f, bl_f)
            record["comparison"] = cmp_res
            try:
                db.conn().execute(
                    "UPDATE results SET payload=? WHERE email_id=? AND run_id = (SELECT MAX(r2.run_id) FROM results r2 WHERE r2.email_id = ?)",
                    [json.dumps(record), email_id, email_id]
                )
                db.conn().commit()
            except Exception:
                pass
    record["feedback"] = [f for f in feedback.rows() if f["email_id"] == email_id]
    c_name, c_email = extract_real_customer(record)
    record["customer"] = c_name
    record["customer_email"] = c_email or record.get("from")
    return record


@app.get("/api/emails/{email_id}")
def get_email(email_id: str, run_id: int | None = None, model: str | None = None):
    return feedback.apply_overrides(stored_record(email_id, run_id, model))


@app.get("/api/emails/{email_id}/draft.eml", response_class=PlainTextResponse)
def download_draft(email_id: str, run_id: int | None = None):
    """The draft as a .eml the operator opens in their own mail client and sends."""
    record = get_email(email_id, run_id)
    draft = (record.get("decision") or {}).get("draft")
    if not draft:
        raise HTTPException(404, f"{email_id} has no draft reply")
    headers = [
        f"To: {draft['to']}",
        f"Subject: {draft['subject']}",
        "X-Generated-By: sdoc-clearview (AI draft; a human approves before sending)",
        "Content-Type: text/plain; charset=utf-8",
    ]
    return "\n".join(headers) + "\n\n" + draft["body"] + "\n"


@app.post("/api/emails/{email_id}/feedback")
def post_feedback(email_id: str, req: FeedbackRequest):
    if req.kind not in feedback.KINDS:
        raise HTTPException(422, f"kind must be one of {', '.join(feedback.KINDS)}")

    # The two raw values and the rule being overruled are read from the stored
    # result rather than taken from the request: the client should not be able to
    # decide what the engine said it did.
    record = stored_record(email_id)
    context: dict = {"run_id": db.latest_run_id(), "to_library": req.to_library}

    # What the engine said is read from the record first and only falls back to
    # the request. It used to be the other way round, and the client sends what
    # is on screen -- which after one correction is the reviewer's own previous
    # verdict. The deviation list then reported the engine saying things it
    # never said: a flip and a flip back left "engine MISMATCH, human MATCH" on
    # a field the engine had called MATCH all along.
    was = None
    if req.kind == "category":
        was = record["classification"]["category"]
    elif req.kind == "review_reason":
        was = benchmark.record_to_submission(record).get("review_reason")
    elif req.kind in ("verdict", "field"):
        cell_now = ((record.get("comparison") or {}).get("detail") or {}).get(req.target or "")
        if cell_now:
            was = (cell_now["status"] if req.kind == "verdict"
                   else cell_now[req.side or "bl"]["raw"])
    if was is None:
        was = req.was
    if req.side:
        context["side"] = req.side
    cell = ((record.get("comparison") or {}).get("detail") or {}).get(req.target or "")
    if cell:
        context.update(si=cell["si"]["raw"], bl=cell["bl"]["raw"], rule=cell["rule"])
        a, b = feedback.norm_pair(req.target, cell["si"]["raw"], cell["bl"]["raw"])
        context.update(norm_si=a, norm_bl=b)

    fid = db.add_feedback(email_id, req.kind, req.corrected_to, target=req.target,
                          was=was, note=req.note, context=context)

    occurrence = None
    if req.kind == "verdict" and req.corrected_to == "MATCH" and cell:
        occurrence = feedback.occurrence(req.target, cell["si"]["raw"], cell["bl"]["raw"])
    return {"id": fid, "record": get_email(email_id), "occurrence": occurrence}


@app.post("/api/feedback/{feedback_id}/library")
def set_library_flag(feedback_id: int, req: LibraryRequest):
    """The reviewer's answer to "does this belong in the mapping library?".

    Asked after the override rather than before it. The override is worth having
    either way, and this is a different judgement: not "is this email wrong" but
    "is this a naming gap or a one-off". Only the reviewer can tell those apart,
    and a tally nobody filtered is not evidence of anything.
    """
    row = db.conn().execute("SELECT * FROM feedback WHERE id=?", (feedback_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"no feedback row {feedback_id}")
    context = json.loads(row["context"]) if row["context"] else {}
    context["to_library"] = req.record
    db.conn().execute("UPDATE feedback SET context=? WHERE id=?",
                      (json.dumps(context, ensure_ascii=False), feedback_id))
    db.conn().commit()
    return {"id": feedback_id, "to_library": req.record,
            "occurrence": feedback.occurrence(row["target"], context.get("si"),
                                              context.get("bl")) if row["target"] else None}


@app.get("/api/mappings")
def list_mappings():
    all_rows = feedback.rows()
    return {
        "entries": mappings.entries(),
        "corrections": all_rows,
        "counters": {
            "entity": len(mappings.entries("entity")),
            "port": len(mappings.entries("port")),
            "pairs": feedback.pair_counts(),
            "rules": feedback.rule_counts(),
            "total_mappings": len(mappings.entries()),
            "total_corrections": len(all_rows),
        },
    }


@app.get("/api/mappings/blast-radius")
def mapping_blast_radius(kind: str, a: str, b: str):
    """What approving this pair would change, before anyone approves it."""
    if kind not in mappings.KINDS:
        raise HTTPException(422, f"kind must be one of {', '.join(mappings.KINDS)}")
    return feedback.blast_radius(kind, a, b)


@app.post("/api/mappings/approve")
def approve_mapping(req: ApproveRequest):
    """Approve one pair of normalised values as equivalent, for every future email.

    Narrow -- it matches this pair and nothing else -- but permanent and global,
    so the response repeats the blast radius the reviewer was shown.
    """
    try:
        entry = mappings.approve(req.kind, req.a, req.b, note=req.note)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"entry": entry, "blast_radius": feedback.blast_radius(req.kind, req.a, req.b),
            "file": str(mappings.PATH)}


@app.delete("/api/mappings")
def revoke_mapping(kind: str, a: str, b: str):
    if not mappings.revoke(kind, a, b):
        raise HTTPException(404, "no such approved pair")
    return {"revoked": {"kind": kind, "a": a, "b": b}}


@app.get("/api/feedback/export")
def export_feedback():
    return feedback.export()


def _predictions_by_model() -> dict[str, dict]:
    """Every stored result, grouped by the model that produced it.

    A model may span several runs, and runs can revisit an email, so the latest
    run wins per email -- the same rule the rest of the views use. Predictions are
    built from the stored payload, never from a record with overrides applied:
    scoring corrected results against ground truth would mark its own homework.
    """
    groups: dict[str, dict] = {}
    for row in db.conn().execute(
            "SELECT r.email_id, r.run_id, r.payload, runs.backend, runs.model "
            "FROM results r JOIN runs ON runs.id = r.run_id ORDER BY r.run_id"):
        key = f"{row['backend']}:{row['model']}"
        group = groups.setdefault(key, {
            # A rules-only run has no model; naming it after its backend beats
            # printing a blank column where a name should be.
            "key": key, "backend": row["backend"],
            "model": row["model"] or row["backend"],
            "runs": [], "predictions": {}, "samples": {},
        })
        if row["run_id"] not in group["runs"]:
            group["runs"].append(row["run_id"])
        record = json.loads(row["payload"])
        group["predictions"][row["email_id"]] = benchmark.record_to_submission(record)
        # Timing and tokens only -- the payload itself is dropped, so summarising
        # the whole corpus does not mean holding all of it.
        group["samples"][row["email_id"]] = benchmark.sample(record)
    return groups


def _priced(usage_: dict, key: str) -> dict:
    usage_["cost"] = benchmark.cost(usage_, benchmark.prices().get(key))
    return usage_


class PriceRequest(BaseModel):
    key: str
    input_per_m: float | None = None
    output_per_m: float | None = None


@app.get("/api/models/pricing")
def get_pricing():
    return {"prices": benchmark.prices(), "path": str(benchmark.PRICES_PATH),
            "unit": "USD per 1M tokens"}


@app.put("/api/models/pricing")
def put_pricing(req: PriceRequest):
    """Set a model's rates. Written to a committed file, like every other rate
    the system would otherwise have had to guess."""
    for value in (req.input_per_m, req.output_per_m):
        if value is not None and value < 0:
            raise HTTPException(422, "a rate cannot be negative")
    return {"prices": benchmark.set_price(req.key, req.input_per_m, req.output_per_m)}


@app.get("/api/benchmark")
def get_benchmark(models: str | None = None):
    """Every model that has processed anything, scored against ground truth.

    Each model is also scored on the emails they all share. Runs are composed by
    quota and skip what earlier runs covered, so two models routinely sit on
    different slices of the corpus -- and a table comparing them on different
    emails reads like a comparison while being nothing of the kind.
    """
    groups = _predictions_by_model()
    wanted = [m for m in (models or "").split(",") if m] or list(groups)
    chosen = [groups[k] for k in wanted if k in groups]

    gt = benchmark.ground_truth()
    scored = [{
        "key": g["key"], "model": g["model"], "backend": g["backend"],
        "runs": g["runs"], "emails": len(g["predictions"]),
        "metrics": benchmark.score(g["predictions"], gt),
        "usage": _priced(benchmark.usage(list(g["samples"].values())), g["key"]),
    } for g in chosen]

    common = sorted(set.intersection(
        *[set(g["predictions"]) & set(gt) for g in chosen])) if chosen else []
    on_common = None
    if len(chosen) > 1 and common:
        on_common = {g["key"]: benchmark.score(
            {e: g["predictions"][e] for e in common}, gt) for g in chosen}

    return {
        "ground_truth_total": len(gt),
        "available": [{"key": g["key"], "model": g["model"], "backend": g["backend"],
                       "emails": len(g["predictions"]), "runs": g["runs"]}
                      for g in groups.values()],
        "models": scored,
        "common_emails": len(common),
        "identical_coverage": len({frozenset(g["predictions"]) for g in chosen}) <= 1,
        "on_common": on_common,
    }


@app.delete("/api/benchmark/history")
def clear_benchmark_history(confirm: bool = False):
    """Drop benchmark runs only. The work queue is untouched."""
    if not confirm:
        raise HTTPException(400, "pass ?confirm=true -- this deletes every benchmark run")
    conn = db.conn()
    where = "COALESCE(purpose, 'queue') = 'benchmark'"
    runs = conn.execute(f"SELECT COUNT(*) FROM runs WHERE {where}").fetchone()[0]
    conn.execute(f"DELETE FROM results WHERE run_id IN (SELECT id FROM runs WHERE {where})")
    conn.execute(f"DELETE FROM runs WHERE {where}")
    conn.commit()
    return {"deleted_runs": runs}


@app.get("/api/benchmark/cases")
def get_benchmark_cases(model: str, outcome: str = "all"):
    """Email by email: what ground truth says, and what this model said."""
    groups = _predictions_by_model()
    if model not in groups:
        raise HTTPException(404, f"no results for {model}")
    rows = benchmark.cases(groups[model]["predictions"])
    if outcome == "wrong":
        rows = [r for r in rows if not r["ok"]]
    elif outcome == "right":
        rows = [r for r in rows if r["ok"]]
    return {"model": model, "count": len(rows), "cases": rows}


@app.get("/api/benchmark/decision-models")
@app.get("/api/benchmark/latest")
def get_benchmark_decision_models(full: bool = True):
    """Return the 520-email two-model benchmark evaluation for Jev and Gemini."""
    results_dir = config.BASE_DIR / "benchmarks" / "results"
    target_name = "latest.json" if full else "latest-summary.json"
    file_path = results_dir / target_name
    if not file_path.exists():
        file_path = results_dir / ("latest-summary.json" if full else "latest.json")
    if not file_path.exists():
        matches = sorted(results_dir.glob("decision-models-*.json"), reverse=True)
        if matches:
            file_path = matches[0]
    if not file_path.exists():
        raise HTTPException(404, "Decision models benchmark result file not found")
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(500, f"Failed to load benchmark result: {e}")


@app.get("/api/benchmark/report.md", response_class=PlainTextResponse)
def get_benchmark_report_md():
    """Return markdown summary report of latest decision models benchmark."""
    md_path = config.BASE_DIR / "benchmarks" / "results" / "latest.md"
    if not md_path.exists():
        raise HTTPException(404, "Decision models benchmark markdown report not found")
    return md_path.read_text(encoding="utf-8")


_decision_benchmark_job = {
    "status": "idle",
    "current_model": None,
    "model_label": None,
    "model_index": 0,
    "total_models": 2,
    "pct": 0,
    "total_cases": 520,
    "error": None,
    "generated_at": None,
}


@app.get("/api/benchmark/decision-models/status")
def get_decision_benchmark_status():
    """Return live status of the running or completed 2-model benchmark."""
    return _decision_benchmark_job


class DecisionBenchmarkRunRequest(BaseModel):
    limit: int | None = None
    workers: int = 4
    batch_size: int = 8
    passcode: str | None = None


@app.post("/api/benchmark/decision-models/run")
def run_decision_models_benchmark(req: DecisionBenchmarkRunRequest | None = None):
    """Trigger a new 520-email ground-truth evaluation across Jev and Gemini."""
    if not req or req.passcode != "686868":
        raise HTTPException(
            status_code=403,
            detail="Benchmark execution is protected. Invalid or missing 6-digit security passcode (686868)."
        )

    global _decision_benchmark_job
    if _decision_benchmark_job.get("status") == "running":
        return {"status": "running", "job": _decision_benchmark_job}

    limit = req.limit if req else None
    workers = req.workers if req else 4
    batch_size = req.batch_size if req else 8

    _decision_benchmark_job = {
        "status": "running",
        "current_model": "starting",
        "model_label": "Initializing benchmark...",
        "model_index": 0,
        "total_models": 2,
        "pct": 0,
        "total_cases": limit or 520,
        "error": None,
        "generated_at": None,
    }

    def _worker():
        global _decision_benchmark_job
        try:
            import sys
            backend_dir = str(config.BASE_DIR)
            if backend_dir not in sys.path:
                sys.path.insert(0, backend_dir)
            import benchmark_decision_models

            def on_progress(p):
                global _decision_benchmark_job
                _decision_benchmark_job.update(p)

            result = benchmark_decision_models.run_decision_benchmark(
                limit=limit,
                batch_size=batch_size,
                workers=workers,
                on_progress=on_progress,
            )
            _decision_benchmark_job = {
                "status": "completed",
                "current_model": None,
                "model_label": None,
                "model_index": 3,
                "total_models": 3,
                "pct": 100,
                "total_cases": result.get("dataset", {}).get("cases", 520),
                "error": None,
                "generated_at": result.get("generated_at"),
            }
        except Exception as exc:
            _decision_benchmark_job = {
                "status": "failed",
                "current_model": None,
                "model_label": None,
                "model_index": 0,
                "total_models": 3,
                "pct": 0,
                "total_cases": limit or 520,
                "error": str(exc),
                "generated_at": None,
            }

    threading.Thread(target=_worker, daemon=True).start()
    return {"status": "running", "job": _decision_benchmark_job}


@app.get("/api/dashboard")
def get_dashboard(run_id: int | None = None):
    """Everything processed so far, or one run when asked for by id."""
    if run_id is None and db.latest_run_id() is None:
        return {"run_id": None, "count": 0, "run": None, "headline": None}
    _scope(run_id)
    report = dashboard.build(run_id)
    cases = list_emails(run_id=run_id)["emails"]
    report["workflow"] = {
        "action_required": sum(
            not bool(case.get("resolved"))
            and (bool(case.get("needs_approval")) or bool(case.get("needs_judgement")))
            for case in cases
        ),
        "no_action_needed": sum(
            not bool(case.get("resolved"))
            and not bool(case.get("needs_approval"))
            and not bool(case.get("needs_judgement"))
            for case in cases
        ),
        "open": sum(
            not bool(case.get("resolved"))
            and not (case.get("comparison_status") == "OK" or case.get("action") == "AUTO_CLEAR")
            for case in cases
        ),
        "auto_cleared": sum(
            not bool(case.get("resolved"))
            and (case.get("comparison_status") == "OK" or case.get("action") == "AUTO_CLEAR")
            for case in cases
        ),
        "handled": sum(bool(case.get("resolved")) for case in cases),
        "needs_judgement": sum(
            not bool(case.get("resolved")) and bool(case.get("needs_judgement"))
            for case in cases
        ),
    }
    return report


@app.get("/api/metrics")
def metrics(run_id: int | None = None):
    if run_id is None and db.latest_run_id() is None:
        return {"run_id": None, "count": 0}
    where, params = _scope(run_id)
    rows = [dict(r) for r in db.conn().execute(
        f"SELECT r.* FROM results r WHERE {where}", params)]
    if not rows:
        return {"run_id": run_id, "count": 0}
    rid = run_id

    threshold = math.exp(config.ESCALATE_LOGP)
    n = len(rows)
    escalated = sum(r["escalated"] for r in rows)
    by_category: dict[str, int] = {}
    by_action: dict[str, int] = {}
    by_verdict: dict[str, int] = {}
    for r in rows:
        by_category[r["category"]] = by_category.get(r["category"], 0) + 1
        by_action[r["action"]] = by_action.get(r["action"], 0) + 1
        if r["comparison_status"]:
            by_verdict[r["comparison_status"]] = by_verdict.get(r["comparison_status"], 0) + 1

    out = {
        "run_id": rid, "count": n,
        "escalated": escalated, "escalation_rate": round(escalated / n, 4),
        "needs_approval": sum(r["needs_approval"] for r in rows),
        "needs_judgement": sum(r["needs_judgement"] for r in rows),
        "avg_ms": round(sum(r["total_ms"] or 0 for r in rows) / n, 2),
        "by_category": by_category, "by_action": by_action, "by_verdict": by_verdict,
        "threshold": round(threshold, 3),
        "low_confidence": sum(1 for r in rows if (r["confidence"] or 0) < threshold),
    }

    # Ground truth ships with the sample corpus; when present, score against it.
    gt_path = config.DATA_DIR / "ground_truth.json"
    if gt_path.exists():
        gt = json.loads(gt_path.read_text(encoding="utf-8"))
        scored = [(r, gt[r["email_id"]]["category"]) for r in rows if r["email_id"] in gt]
        if scored:
            correct = sum(r["category"] == truth for r, truth in scored)
            errors = [(r, t) for r, t in scored if r["category"] != t]
            caught = sum(1 for r, _ in errors if (r["confidence"] or 0) < threshold)
            out["accuracy"] = round(correct / len(scored), 4)
            out["scored"] = len(scored)
            out["errors"] = len(errors)
            # The number that justifies the router: of everything it got wrong,
            # how much did it already know it was unsure about?
            out["errors_caught_by_router"] = caught
            out["confusions"] = [
                {"truth": t, "predicted": r["category"], "email_id": r["email_id"],
                 "confidence": r["confidence"]} for r, t in errors[:50]]
    return out


# Production image: Vite's compiled assets are copied here. Mount this last so
# every /api route above keeps precedence while all browser routes resolve to
# the React application. Local development still uses Vite and skips the mount.
_static_dir = Path(os.environ.get("SDOC_STATIC_DIR", config.BASE_DIR / "static"))
if _static_dir.is_dir():
    app.mount("/", StaticFiles(directory=_static_dir, html=True), name="frontend")
