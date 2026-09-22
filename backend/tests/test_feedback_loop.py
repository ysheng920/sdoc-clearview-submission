"""The two things a correction is allowed to do, and the line between them.

An override changes one email. An approved mapping changes every email carrying
that exact pair of values -- and nothing else. These checks exist because the
difference between those two is the whole safety argument, and it is the kind of
thing that quietly stops being true.

No model is called: the labelled category is replayed and everything else --
extraction, comparison, the action -- is deterministic. Runs against a throwaway
database and mapping file, so it never touches the real ones.
`python tests/test_feedback_loop.py`.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_TMP = Path(tempfile.mkdtemp(prefix="clearview-test-"))
os.environ["SDOC_DB"] = str(_TMP / "test.db")
os.environ.setdefault("LLM_BACKEND", "deterministic")

from app import db, feedback, mappings  # noqa: E402
from app.engines.compare import compare  # noqa: E402
from app.engines.extract import extract  # noqa: E402
from app import config  # noqa: E402
from support import Refuses, run  # noqa: E402

mappings.PATH = _TMP / "mappings.json"
mappings.reload()


def reset():
    db.conn().execute("DELETE FROM feedback")
    db.conn().commit()
    if mappings.PATH.exists():
        mappings.PATH.unlink()
    mappings.reload()


def stored(email_id: str) -> dict:
    """A fresh engine result, as the pipeline would store it -- no overrides."""
    return run(email_id)


def test_an_override_changes_one_email_and_says_who_did_it():
    reset()
    record = stored("email_004")
    assert record["comparison"]["status"] == "MISMATCH"
    assert record["decision"]["action"] == "FLAG_DISCREPANCY"

    for field in ("consignee", "notify_party"):
        db.add_feedback("email_004", "verdict", "MATCH", target=field, was="MISMATCH",
                        context={"rule": "values_differ", "run_id": 1})

    fixed = feedback.apply_overrides(record)
    assert fixed["comparison"]["detail"]["consignee"]["status"] == "MATCH"
    assert fixed["comparison"]["defect_fields"] == []
    assert fixed["comparison"]["status"] == "OK", "the whole verdict has to be recomputed"
    assert fixed["decision"]["action"] == "AUTO_CLEAR", "and so does the recommended action"
    assert fixed["overridden"] is True

    # The override must be legible as a human act, not absorbed into the engine's voice.
    rule = fixed["comparison"]["detail"]["consignee"]["rule"]
    assert rule.startswith("human_override"), rule
    assert fixed["comparison"]["detail"]["consignee"]["overruled_rule"] == "values_differ"
    assert any(t["engine"] == "human review" for t in fixed["traces"])


def test_the_stored_result_is_never_rewritten_by_a_correction():
    """What the benchmark scores must stay the engine's own answer."""
    reset()
    db.add_feedback("email_004", "verdict", "MATCH", target="consignee",
                    was="MISMATCH", context={"rule": "values_differ"})
    again = stored("email_004")
    assert again["comparison"]["status"] == "MISMATCH"
    assert again["comparison"]["detail"]["consignee"]["status"] == "MISMATCH"


def test_flipping_a_verdict_back_is_an_undo_and_not_an_override():
    """Ending up where the engine already was is agreement, not a dispute.

    A reviewer who overrules a verdict and then changes their mind used to leave
    the field stamped human_override forever, and a row in the deviation list
    claiming the engine said the reviewer's own first answer.
    """
    reset()
    record = stored("email_004")
    engine = record["comparison"]["detail"]["consignee"]["status"]
    # `was` is the engine's word on both rows, which is what the endpoint now
    # records: it reads the stored result instead of believing the client, which
    # sends whatever is on screen -- after the first flip, the reviewer's own
    # answer. That is how "engine MISMATCH" reached a field the engine called
    # MATCH from the start.
    db.add_feedback("email_004", "verdict", "MATCH", target="consignee",
                    was=engine, context={"rule": "values_differ"})
    db.add_feedback("email_004", "verdict", engine, target="consignee",
                    was=engine, context={"rule": "values_differ"})

    back = feedback.apply_overrides(record)["comparison"]["detail"]["consignee"]
    assert back["status"] == engine
    assert "human_override" not in back["rule"], back["rule"]


def test_flipping_from_missing_to_match_and_back_to_mismatch_restores_engine():
    reset()
    record = stored("email_004")
    record["comparison"]["detail"]["shipper"]["status"] = "MISSING"
    record["comparison"]["detail"]["shipper"]["rule"] = "absent_from_bl"

    # User clicks Accept as Match
    db.add_feedback("email_004", "verdict", "MATCH", target="shipper",
                    was="MISSING", context={"rule": "absent_from_bl"})
    overridden = feedback.apply_overrides(record)["comparison"]["detail"]["shipper"]
    assert overridden["status"] == "MATCH"
    assert "human_override" in overridden["rule"]

    # User clicks Mark as Discrepancy (sends MISMATCH)
    db.add_feedback("email_004", "verdict", "MISMATCH", target="shipper",
                    was="MATCH", context={"rule": "absent_from_bl"})
    restored = feedback.apply_overrides(record)["comparison"]["detail"]["shipper"]
    assert restored["status"] == "MISSING"
    assert "human_override" not in restored["rule"], restored["rule"]
    assert restored["rule"] == "absent_from_bl"


def test_resolving_a_case_takes_it_out_of_the_queue():
    reset()
    record = stored("email_004")
    assert record["decision"]["needs_judgement"] is True
    db.add_feedback("email_004", "resolve", "done")
    done = feedback.apply_overrides(record)
    assert done["resolved"] is True
    assert done["decision"]["needs_judgement"] is False
    assert done["decision"]["needs_approval"] is False


def test_an_approved_pair_matches_that_pair_and_leaves_everything_else_alone():
    """The whole reason a lookup is allowed to go live and a threshold is not."""
    reset()
    si, *_ = extract(config.DATA_DIR / "attachments" / "email_004_SI.txt", client=Refuses())
    bl, *_ = extract(config.DATA_DIR / "attachments" / "email_004_BL.txt", client=Refuses())

    before, _ = compare(si, bl)
    assert before["detail"]["consignee"]["status"] == "MISMATCH"

    a, b = feedback.norm_pair("consignee", si["consignee"].raw, bl["consignee"].raw)
    mappings.approve("entity", a, b, approved_by="tester", from_email="email_004")

    after, _ = compare(si, bl)
    assert after["detail"]["consignee"]["status"] == "MATCH"
    assert after["detail"]["consignee"]["rule"].startswith("approved_alias (tester")

    # A clean pair must not move, and neither must a different mismatching pair.
    clean_si, *_ = extract(config.DATA_DIR / "attachments" / "email_001_SI.txt", client=Refuses())
    clean_bl, *_ = extract(config.DATA_DIR / "attachments" / "email_001_BL.txt", client=Refuses())
    clean, _ = compare(clean_si, clean_bl)
    assert clean["status"] == "OK"
    assert all(d["rule"] != "approved_alias" for d in clean["detail"].values())

    assert mappings.approved("entity", a, "something else entirely") is None
    assert mappings.approved("port", a, b) is None, "entity approvals are not port approvals"


def test_an_approval_is_order_independent_and_revocable():
    reset()
    mappings.approve("entity", "east bright", "east bright trading")
    assert mappings.approved("entity", "east bright trading", "east bright")
    assert mappings.revoke("entity", "east bright trading", "east bright")
    assert mappings.approved("entity", "east bright", "east bright trading") is None


def test_the_two_counters_answer_different_questions():
    reset()
    ctx = lambda si, bl, rule="values_differ": {                      # noqa: E731
        "si": si, "bl": bl, "rule": rule, "to_library": True,
        "norm_si": si, "norm_bl": bl}

    # Same pair, twice, on different emails -- a missing alias.
    db.add_feedback("email_004", "verdict", "MATCH", target="consignee",
                    was="MISMATCH", context=ctx("east bright", "east bright trading"))
    db.add_feedback("email_087", "verdict", "MATCH", target="consignee",
                    was="MISMATCH", context=ctx("east bright", "east bright trading"))
    # A different pair, same rule -- evidence about the rule, not the pair.
    db.add_feedback("email_203", "verdict", "MATCH", target="shipper",
                    was="MISMATCH", context=ctx("moorim sp", "moorim paper"))

    pairs = feedback.pair_counts()
    assert len(pairs) == 2
    top = pairs[0]
    assert top["count"] == 2 and top["emails"] == ["email_004", "email_087"]
    assert (top["a"], top["b"]) == ("east bright", "east bright trading")

    rules = feedback.rule_counts()
    assert len(rules) == 1
    assert rules[0]["rule"] == "values_differ"
    assert rules[0]["count"] == 3, "three corrections..."
    assert rules[0]["distinct_pairs"] == 2, "...but only two distinct pairs"
    assert rules[0]["suggest"] is False, f"{feedback.SUGGEST_AFTER} distinct pairs needed"


def test_a_correction_the_reviewer_kept_private_is_not_counted():
    """'Record it' is a separate answer from 'override it', and it has to bite."""
    reset()
    db.add_feedback("email_004", "verdict", "MATCH", target="consignee", was="MISMATCH",
                    context={"norm_si": "a", "norm_bl": "b", "rule": "values_differ",
                             "to_library": False})
    assert feedback.pair_counts() == []
    assert feedback.rule_counts() == []


def test_the_occurrence_message_counts_up():
    reset()
    si, bl = "EAST BRIGHT FZ-LLC", "UAB NOVAKOPA"
    first = feedback.occurrence("consignee", si, bl)
    assert first["count"] == 0 and first["kind"] == "entity"

    a, b = feedback.norm_pair("consignee", si, bl)
    db.add_feedback("email_004", "verdict", "MATCH", target="consignee", was="MISMATCH",
                    context={"si": si, "bl": bl, "norm_si": a, "norm_bl": b,
                             "rule": "values_differ", "to_library": True})
    second = feedback.occurrence("consignee", si, bl)
    assert second["count"] == 1
    assert second["approved"] is False


def test_a_second_correction_still_cites_the_engine_not_the_first_one():
    """Corrections stack; the record of what was overruled must not.

    Reading the rule back off an already-corrected record makes the second
    correction name the first one as the rule it disagreed with, and the
    deviation list then points at a rule that does not exist.
    """
    reset()
    engine = stored("email_004")
    original = engine["comparison"]["detail"]["consignee"]["rule"]
    assert original == "values_differ", original

    db.add_feedback("email_004", "field", "UAB NOVAKOPA UAB", target="consignee",
                    was="UAB NOVAKOPA", context={"side": "bl"})
    corrected = feedback.apply_overrides(engine)
    assert corrected["comparison"]["detail"]["consignee"]["rule"].startswith("recompared")

    # The engine's own record is what a later correction must be written against.
    assert stored("email_004")["comparison"]["detail"]["consignee"]["rule"] == original


def test_a_run_interrupted_by_a_restart_does_not_stay_running_forever():
    """A run row says "running" until its worker thread finishes it.

    Restart the API and that thread is gone, but the row is not, so the queue
    shows a batch in progress that nothing is working on -- which is what a stall
    actually looked like from the outside.
    """
    run_id = db.start_run(3, "jev", "~typesafe/jev-latest")
    assert dict(db.conn().execute(
        "SELECT status FROM runs WHERE id=?", (run_id,)).fetchone())["status"] == "running"

    assert db.orphan_runs() >= 1
    row = dict(db.conn().execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())
    assert row["status"] == "failed"
    assert row["finished_at"] and "interrupted" in row["error"]

    # A finished run is left alone.
    done_id = db.start_run(1, "jev", "m")
    db.finish_run(done_id, None)
    db.orphan_runs()
    assert dict(db.conn().execute(
        "SELECT status FROM runs WHERE id=?", (done_id,)).fetchone())["status"] == "done"


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
            passed += 1
    reset()
    print(f"\n{passed} checks passed")
