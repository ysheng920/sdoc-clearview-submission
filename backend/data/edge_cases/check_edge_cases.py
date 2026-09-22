# -*- coding: utf-8 -*-
"""Self-check for the edge-case folder. Run it directly:

    python backend/data/edge_cases/check_edge_cases.py

No model and no network: it runs the project's own label parser over the SI/BL
transcriptions and asserts they still yield the raw values recorded in
expected.json, then re-derives each case verdict with compare.py. It fails if a
transcription and its expectation drift apart -- not if the extractor is bad.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
sys.path.insert(0, str(BACKEND))

from app import config  # noqa: E402
from app.engines.docs import labelled_lines  # noqa: E402
from app.engines.normalize import field_for_label, normalise, plausible  # noqa: E402
from app.engines.compare import compare  # noqa: E402
from app.trace import Field  # noqa: E402

EXPECTED = json.loads((HERE / "expected.json").read_text(encoding="utf-8"))
BODY_MARKER = "===== BODY (everything below this line, verbatim) ====="


def parse(path: Path) -> dict[str, str]:
    """Label-parse one transcription, first match per field, same order as extract.py."""
    text = path.read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for label, value, _s, _e in labelled_lines(text, is_label=field_for_label):
        name = field_for_label(label)
        if name and name not in out and plausible(name, value):
            out[name] = value
    return out


def main() -> int:
    failures: list[str] = []
    for eid, case in EXPECTED["cases"].items():
        for key in ("image", "email", "si_document", "bl_document", "si_crop",
                    "bl_crop", "email_crop", "scan_email", "si_scan", "bl_scan",
                    "email_text"):
            rel = case.get(key)
            if rel and not (HERE / rel).exists():
                failures.append(f"{eid} {key}: {rel} does not exist")

        # emails/*.txt is a copy-paste view of inbox/*.json -- keep them identical.
        inbox = json.loads((HERE / case["email"]).read_text(encoding="utf-8"))
        plain = (HERE / case["email_text"]).read_text(encoding="utf-8")
        head, _, body = plain.partition(BODY_MARKER)
        for label, want in (("Sender:", inbox["from"]), ("Subject:", inbox["subject"])):
            line = next((l for l in head.splitlines() if l.startswith(label)), "")
            if line.split(":", 1)[1].strip() != want:
                failures.append(f"{eid} email_text {label} {line!r} != {want!r}")
        if body.strip() != inbox["body"].strip():
            failures.append(f"{eid} email_text: body differs from {case['email']}")

        for side in ("si", "bl"):
            parsed = parse(HERE / case[f"{side}_document"])
            for name in EXPECTED["_fields"]:
                # "label_parser" is what the deterministic parser actually gets
                # off this transcription today -- often less than "raw", which is
                # what a perfect reader would see on the image. The gap between
                # the two is the point of these cases; drift from it is the bug.
                want = case["expected_extraction"][side][name]["label_parser"]
                got = parsed.get(name)
                if (want or "").strip() != (got or "").strip():
                    failures.append(
                        f"{eid} {side}.{name}: expected.json records {want!r}, "
                        f"label parser now gives {got!r}")

        # The verdict in expected.json must still be what compare.py derives.
        def fields(side: str) -> dict[str, Field]:
            src = case["expected_extraction"][side]
            return {
                n: (Field(name=n, source="missing") if src[n]["raw"] is None
                    else Field(name=n, raw=src[n]["raw"],
                               value=normalise(n, src[n]["raw"]), source="expected"))
                for n in EXPECTED["_fields"]
            }

        result, _ = compare(fields("si"), fields("bl"))
        row = case.get("current_code_row") or case["expected_row"]
        for key in ("status", "defect_fields", "missing_fields"):
            if result[key] != row[key]:
                failures.append(
                    f"{eid} verdict.{key}: recorded {row[key]!r}, compare.py gives {result[key]!r}")

    for f in failures:
        print("FAIL", f)
    print(f"\n{len(EXPECTED['cases'])} cases checked, {len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
