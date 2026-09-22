"""SQLite via stdlib. Three tables, no ORM, no migration tool."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone, timedelta

# Malaysia Standard Time (MYT: UTC+8, Asia/Kuala_Lumpur)
MYT = timezone(timedelta(hours=8), name="Asia/Kuala_Lumpur")

from . import config

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    backend     TEXT,
    model       TEXT,
    total       INTEGER DEFAULT 0,
    done        INTEGER DEFAULT 0,
    status      TEXT DEFAULT 'running',
    error       TEXT,
    -- 'queue' is an operator working through an inbox; 'benchmark' is the same
    -- corpus scored again to compare models. Keeping them apart is what lets one
    -- be reset without destroying the other.
    purpose     TEXT DEFAULT 'queue'
);
CREATE TABLE IF NOT EXISTS results (
    email_id          TEXT NOT NULL,
    run_id            INTEGER NOT NULL,
    category          TEXT,
    confidence        REAL,
    escalated         INTEGER DEFAULT 0,
    comparison_status TEXT,
    action            TEXT,
    needs_approval    INTEGER DEFAULT 0,
    needs_judgement   INTEGER DEFAULT 0,
    total_ms          REAL,
    payload           TEXT NOT NULL,
    PRIMARY KEY (email_id, run_id)
);
CREATE TABLE IF NOT EXISTS feedback (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at   TEXT NOT NULL,
    email_id     TEXT NOT NULL,
    kind         TEXT NOT NULL,     -- category | field | verdict | review_reason | resolve
    target       TEXT,              -- field name, when kind='field'
    was          TEXT,
    corrected_to TEXT,
    note         TEXT,
    reviewer     TEXT DEFAULT 'operator',
    context      TEXT               -- JSON: side, raw values, rule overruled, run_id
);
CREATE INDEX IF NOT EXISTS idx_results_run ON results(run_id);
"""


def now() -> str:
    return datetime.now(MYT).strftime("%Y-%m-%d %H:%M:%S")


_startup_cleaned = False


def conn() -> sqlite3.Connection:
    """One connection per thread -- sqlite3 objects are not shareable."""
    global _startup_cleaned
    c = getattr(_local, "conn", None)
    if c is None:
        c = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.executescript(SCHEMA)
        _migrate(c)
        if not _startup_cleaned:
            c.execute("UPDATE runs SET status='done', finished_at=? WHERE status='running'", (now(),))
            c.commit()
            _startup_cleaned = True
        _local.conn = c
    return c


def _migrate(c: sqlite3.Connection) -> None:
    """CREATE TABLE IF NOT EXISTS never adds a column to an existing file."""
    have = {r["name"] for r in c.execute("PRAGMA table_info(runs)")}
    if "purpose" not in have:
        c.execute("ALTER TABLE runs ADD COLUMN purpose TEXT DEFAULT 'queue'")
        c.commit()

    have = {r["name"] for r in c.execute("PRAGMA table_info(feedback)")}
    if "context" not in have:
        # Everything a correction needs beyond "what it was changed to": which
        # side was edited, the values either way, the rule that produced the
        # verdict being overruled, and the run it was recorded against. One JSON
        # column rather than five, so the next thing worth keeping does not need
        # another migration.
        c.execute("ALTER TABLE feedback ADD COLUMN context TEXT")
        c.commit()

    have = {r["name"] for r in c.execute("PRAGMA table_info(results)")}
    if "needs_judgement" not in have:
        c.execute("ALTER TABLE results ADD COLUMN needs_judgement INTEGER DEFAULT 0")
        # Backfill from the payload so older runs stay comparable.
        c.execute("""UPDATE results SET needs_judgement = 1
                     WHERE action IN ('FLAG_DISCREPANCY', 'HUMAN_REVIEW')""")
        c.commit()


def start_run(total: int, backend: str, model: str, purpose: str = "queue") -> int:
    c = conn()
    cur = c.execute(
        "INSERT INTO runs (started_at, backend, model, total, purpose) "
        "VALUES (?,?,?,?,?)",
        (now(), backend, model, total, purpose))
    c.commit()
    return cur.lastrowid


def save_result(run_id: int, record: dict) -> None:
    c = conn()
    cmp_ = record.get("comparison") or {}
    dec = record.get("decision") or {}
    cls = record.get("classification") or {}
    c.execute(
        """INSERT OR REPLACE INTO results
           (email_id, run_id, category, confidence, escalated, comparison_status,
            action, needs_approval, needs_judgement, total_ms, payload)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (record["email_id"], run_id, cls.get("category"), cls.get("confidence"),
         int(bool(cls.get("escalated"))), cmp_.get("status"), dec.get("action"),
         int(bool(dec.get("needs_approval"))), int(bool(dec.get("needs_judgement"))),
         record.get("total_ms"), json.dumps(record, ensure_ascii=False)))
    c.execute("UPDATE runs SET done = done + 1 WHERE id = ?", (run_id,))
    c.commit()


def finish_run(run_id: int, error: str | None = None) -> None:
    c = conn()
    c.execute("UPDATE runs SET finished_at=?, status=?, error=? WHERE id=?",
              (now(), "failed" if error else "done", error, run_id))
    c.commit()


def latest_run_id() -> int | None:
    row = conn().execute("SELECT id FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    return row["id"] if row else None


def orphan_runs() -> int:
    """Close out runs whose worker thread no longer exists.

    A run row says "running" until its thread finishes. Restart the API and that
    thread is gone, but the row stays -- so the queue shows a batch in progress
    that nothing is working on, forever. Swept once at startup, where "still
    running" can only mean "was interrupted".
    """
    c = conn()
    cur = c.execute(
        "UPDATE runs SET status='failed', finished_at=?, "
        "error=COALESCE(error, 'interrupted -- the API restarted while it was running') "
        "WHERE status='running'", (now(),))
    c.commit()
    return cur.rowcount


def purge_legacy_mock_runs() -> dict[str, int]:
    """Remove results produced by the retired mock backend.

    The mock client was deleted from the application, but databases created
    before that change still contain its runs. Those rows otherwise appear as a
    selectable model and can become the queue's latest result for every email.
    Human feedback is kept because it records an operator action on the case,
    independently of which model originally surfaced it.
    """
    c = conn()
    where = "lower(COALESCE(backend, ''))='mock' OR lower(COALESCE(model, '')) LIKE 'mock%'"
    run_ids = [r["id"] for r in c.execute(f"SELECT id FROM runs WHERE {where}")]
    if not run_ids:
        return {"runs": 0, "results": 0}
    marks = ",".join("?" for _ in run_ids)
    results = c.execute(
        f"SELECT COUNT(*) FROM results WHERE run_id IN ({marks})", run_ids
    ).fetchone()[0]
    c.execute(f"DELETE FROM results WHERE run_id IN ({marks})", run_ids)
    c.execute(f"DELETE FROM runs WHERE id IN ({marks})", run_ids)
    c.commit()
    return {"runs": len(run_ids), "results": results}


def add_feedback(email_id: str, kind: str, corrected_to: str,
                 target: str | None = None, was: str | None = None,
                 note: str | None = None, reviewer: str = "operator",
                 context: dict | None = None) -> int:
    c = conn()
    cur = c.execute(
        """INSERT INTO feedback (created_at, email_id, kind, target, was, corrected_to,
                                 note, reviewer, context) VALUES (?,?,?,?,?,?,?,?,?)""",
        (now(), email_id, kind, target, was, corrected_to, note, reviewer,
         json.dumps(context, ensure_ascii=False) if context else None))
    c.commit()
    return cur.lastrowid


_DEMO_TABLE_COLUMNS = {
    "runs": (
        "id", "started_at", "finished_at", "backend", "model", "total",
        "done", "status", "error", "purpose",
    ),
    "results": (
        "email_id", "run_id", "category", "confidence", "escalated",
        "comparison_status", "action", "needs_approval", "needs_judgement",
        "total_ms", "payload",
    ),
    "feedback": (
        "id", "created_at", "email_id", "kind", "target", "was",
        "corrected_to", "note", "reviewer", "context",
    ),
}


def _restore_tables_from_baseline(c: sqlite3.Connection, baseline_path) -> None:
    """Restore by column name so migrated databases cannot shift values.

    SQLite appends columns added by ALTER TABLE. That means an older live
    database can have a different physical column order from a freshly-created
    baseline even when both contain the same named columns. SELECT * is unsafe
    across those two schemas.
    """
    b_str = str(baseline_path).replace("\\", "/")
    c.execute("ATTACH DATABASE ? AS demo", (b_str,))
    try:
        # Validate the complete baseline before deleting anything from the live
        # database. A partial or stale seed must not destroy a working queue.
        for table, columns in _DEMO_TABLE_COLUMNS.items():
            available = {
                row[1] for row in c.execute(f"PRAGMA demo.table_info({table})")
            }
            missing = set(columns) - available
            if missing:
                raise RuntimeError(
                    f"Demo baseline table {table} is missing columns: {', '.join(sorted(missing))}"
                )

        with c:
            for table, columns in _DEMO_TABLE_COLUMNS.items():
                names = ", ".join(columns)
                c.execute(f"DELETE FROM {table}")
                c.execute(
                    f"INSERT INTO {table} ({names}) "
                    f"SELECT {names} FROM demo.{table}"
                )
    finally:
        c.execute("DETACH DATABASE demo")


def reset_to_demo() -> dict:
    """Reset database and mappings to clean demo baseline:
    - Sync runs, results and feedback from the committed demo_baseline.db
    - Reset mappings.json from demo_mappings.json
    - Clean up simulated emails
    """
    import shutil
    from . import mappings

    c = conn()

    # 1. Restore runs, results and feedback from the frozen baseline. Never
    # manufacture a baseline from the live database: on a fresh clone that
    # database is empty, making Reset Demo report success while restoring 0 rows.
    baseline_path = config.DATA_DIR / "demo_baseline.db"
    if not baseline_path.exists():
        raise FileNotFoundError(
            f"Demo baseline is missing: {baseline_path}. Pull backend/data/demo_baseline.db from the repository."
        )

    _restore_tables_from_baseline(c, baseline_path)

    # 2. Restore predefined mappings
    demo_mappings_path = config.DATA_DIR / "demo_mappings.json"
    if demo_mappings_path.exists():
        shutil.copy2(demo_mappings_path, mappings.PATH)
        mappings.reload()

    # 3. Restore baseline simulated emails
    sim_dir = config.DATA_DIR / "simulated"
    demo_sim_dir = config.DATA_DIR / "demo_simulated"
    if demo_sim_dir.exists():
        sim_dir.mkdir(parents=True, exist_ok=True)
        for f in sim_dir.iterdir():
            if f.is_file():
                try:
                    f.unlink()
                except OSError:
                    pass
        for f in demo_sim_dir.iterdir():
            if f.is_file():
                shutil.copy2(f, sim_dir / f.name)

    total_runs = c.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    total_results = c.execute("SELECT COUNT(*) FROM results").fetchone()[0]
    total_feedback = c.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
    total_mappings = len(mappings.entries())

    return {
        "status": "ok",
        "runs": total_runs,
        "results": total_results,
        "feedback": total_feedback,
        "mappings": total_mappings,
        "message": f"Demo environment reset to baseline: {total_results} results, {total_feedback} manual corrections, {total_mappings} predefined mappings."
    }

