"""Scoring against ground truth, and the one way a benchmark page lies.

Nothing scores the whole corpus on its own any more, so the headline numbers
are whatever the last run produced. What is checked here is the arithmetic
around the edges, and the thing the page exists to prevent -- two models scored
on different emails and printed side by side as though that were a comparison.

`python tests/test_benchmark.py`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import benchmark  # noqa: E402

GT = {
    "a": {"category": "BL_COMPARISON", "status": "OK", "review_reason": None,
          "has_defect": False, "defect_fields": []},
    "b": {"category": "BL_COMPARISON", "status": "MISMATCH", "review_reason": None,
          "has_defect": True, "defect_fields": ["consignee", "shipper"]},
    "c": {"category": "SPAM", "status": "OK", "review_reason": None,
          "has_defect": False, "defect_fields": []},
    "d": {"category": "BL_COMPARISON", "status": "NEEDS_REVIEW",
          "review_reason": "wrong_doc_type", "has_defect": False, "defect_fields": []},
}


def pred(category, status="OK", reason=None, defect=False, fields=()):
    return {"category": category, "status": status, "review_reason": reason,
            "has_defect": defect, "defect_fields": list(fields)}


def test_a_perfect_run_scores_perfectly():
    predictions = {
        "a": pred("BL_COMPARISON"),
        "b": pred("BL_COMPARISON", "MISMATCH", defect=True, fields=["shipper", "consignee"]),
        "c": pred("SPAM"),
        "d": pred("BL_COMPARISON", "NEEDS_REVIEW", reason="wrong_doc_type"),
    }
    r = benchmark.score(predictions, GT)
    assert r["classification"]["accuracy"] == 1.0
    assert r["edge_cases"]["recall"] == 1.0
    assert r["comparison"]["f1"] == 1.0
    # Field order is not part of the answer; naming the same two fields is.
    assert r["comparison"]["exact_match"] == 1.0


def test_the_right_reason_is_part_of_catching_an_edge_case():
    """Sending it to a human for the wrong stated reason is not a pass: the reason
    is what tells the operator what to do next."""
    predictions = dict(
        a=pred("BL_COMPARISON"), b=pred("BL_COMPARISON", "MISMATCH", defect=True,
                                        fields=["consignee", "shipper"]),
        c=pred("SPAM"), d=pred("BL_COMPARISON", "NEEDS_REVIEW", reason="unreadable"))
    r = benchmark.score(predictions, GT)
    assert r["edge_cases"]["recall"] == 0.0
    assert r["edge_cases"]["rows"][0]["predicted"] == "unreadable"
    assert r["classification"]["accuracy"] == 1.0, "the category was still right"


def test_naming_the_wrong_field_still_counts_as_finding_the_defect():
    """Two different questions: did it flag the pair, and did it flag the right
    fields. Collapsing them would hide a report that is useless to act on."""
    predictions = dict(
        a=pred("BL_COMPARISON"),
        b=pred("BL_COMPARISON", "MISMATCH", defect=True, fields=["notify_party"]),
        c=pred("SPAM"), d=pred("BL_COMPARISON", "NEEDS_REVIEW", reason="wrong_doc_type"))
    r = benchmark.score(predictions, GT)
    assert r["comparison"]["f1"] == 1.0, "it did flag the pair"
    assert r["comparison"]["exact_match"] == 0.5, "on the wrong fields"


def test_only_emails_with_an_answer_are_scored():
    r = benchmark.score({"a": pred("BL_COMPARISON"), "zz": pred("SPAM")}, GT)
    assert r["scored"] == 1
    assert r["classification"]["total"] == 1


def test_a_stage_with_nothing_in_it_reports_nothing_rather_than_zero():
    """A model that saw no edge cases has not failed them -- and a page showing
    0.0% there would read as a failure."""
    r = benchmark.score({"a": pred("BL_COMPARISON")}, GT)
    assert r["edge_cases"]["recall"] is None
    assert r["comparison"]["exact_match"] == 1.0
    assert "edge_case_recall" not in benchmark.headline(r)


def test_two_models_on_different_emails_are_not_comparable():
    """The failure this page exists to prevent: each looks strong on its own
    slice, and the slices do not overlap, so neither number says which is better.
    """
    strong = benchmark.score({"a": pred("BL_COMPARISON"), "c": pred("SPAM")}, GT)
    weak = benchmark.score({"b": pred("SPAM"), "d": pred("SPAM")}, GT)
    assert strong["classification"]["accuracy"] == 1.0
    assert weak["classification"]["accuracy"] == 0.0

    common = set(["a", "c"]) & set(["b", "d"])
    assert common == set(), "no shared email, so the API reports no common subset"

    # Where they do overlap, both are scored on exactly the same emails.
    overlap = {"a", "c"}
    one = benchmark.score({e: pred(GT[e]["category"]) for e in overlap}, GT)
    two = benchmark.score({e: pred("GENERAL") for e in overlap}, GT)
    assert one["classification"]["total"] == two["classification"]["total"] == 2


def test_the_submission_shape_reads_blockers_in_priority_order():
    record = {"classification": {"category": "BL_COMPARISON"},
              "blockers": ["wrong document type attached (wrong_doc_type)",
                           "also unreadable"],
              "comparison": None}
    assert benchmark.record_to_submission(record)["review_reason"] == "wrong_doc_type"

    clean = {"classification": {"category": "BL_COMPARISON"}, "blockers": [],
             "comparison": {"status": "MISMATCH", "defect_fields": ["shipper"]}}
    out = benchmark.record_to_submission(clean)
    assert out["has_defect"] is True and out["defect_fields"] == ["shipper"]


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
            passed += 1
    print(f"\n{passed} checks passed")
