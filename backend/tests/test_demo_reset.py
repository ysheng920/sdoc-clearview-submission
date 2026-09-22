import json
import sqlite3

from app import db


def _create_common_tables(c: sqlite3.Connection) -> None:
    c.executescript("""
        CREATE TABLE runs (
            id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
            backend TEXT, model TEXT, total INTEGER, done INTEGER, status TEXT,
            error TEXT, purpose TEXT
        );
        CREATE TABLE feedback (
            id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, email_id TEXT NOT NULL,
            kind TEXT NOT NULL, target TEXT, was TEXT, corrected_to TEXT, note TEXT,
            reviewer TEXT, context TEXT
        );
    """)


def test_demo_restore_maps_results_by_column_name(tmp_path):
    baseline_path = tmp_path / "demo_baseline.db"
    live_path = tmp_path / "live.db"

    baseline = sqlite3.connect(baseline_path)
    _create_common_tables(baseline)
    baseline.execute("""
        CREATE TABLE results (
            email_id TEXT, run_id INTEGER, category TEXT, confidence REAL,
            escalated INTEGER, comparison_status TEXT, action TEXT,
            needs_approval INTEGER, needs_judgement INTEGER, total_ms REAL,
            payload TEXT, PRIMARY KEY (email_id, run_id)
        )
    """)
    baseline.execute(
        "INSERT INTO runs VALUES (1, 'now', NULL, 'jev', 'jev-1.13', 1, 1, 'done', NULL, 'queue')"
    )
    payload = json.dumps({"email_id": "email_003", "decision": {"needs_judgement": True}})
    baseline.execute(
        "INSERT INTO results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("email_003", 1, "BL_COMPARISON", 0.98, 0, "MISMATCH",
         "FLAG_DISCREPANCY", 1, 1, 824.6, payload),
    )
    baseline.commit()
    baseline.close()

    live = sqlite3.connect(live_path)
    live.row_factory = sqlite3.Row
    _create_common_tables(live)
    # This is the physical order produced when needs_judgement was added to an
    # older database via ALTER TABLE: the new column is appended at the end.
    live.execute("""
        CREATE TABLE results (
            email_id TEXT, run_id INTEGER, category TEXT, confidence REAL,
            escalated INTEGER, comparison_status TEXT, action TEXT,
            needs_approval INTEGER, total_ms REAL, payload TEXT,
            needs_judgement INTEGER DEFAULT 0,
            PRIMARY KEY (email_id, run_id)
        )
    """)
    live.commit()

    db._restore_tables_from_baseline(live, baseline_path)

    restored = live.execute("SELECT * FROM results").fetchone()
    assert restored["needs_judgement"] == 1
    assert restored["total_ms"] == 824.6
    assert json.loads(restored["payload"])["email_id"] == "email_003"
    live.close()
