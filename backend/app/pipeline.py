"""Run one email through all four engines and keep every Trace."""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import config
from .engines.classify import classify
from .engines.compare import compare
from .engines.decide import decide
from .engines.extract import extract
from .llm import get_client


SIMULATED_DIR = config.DATA_DIR / "simulated"


def load_email(email_id: str) -> dict:
    """The corpus first, then hand-written emails.

    Simulated emails live outside the inbox on purpose -- the inbox is the 520
    the benchmark and the sampler are measured against -- but everything
    downstream still has to be able to read one back.
    """
    path = config.INBOX_DIR / f"{email_id}.json"
    if not path.exists():
        path = SIMULATED_DIR / f"{email_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def list_email_ids() -> list[str]:
    return sorted(p.stem for p in config.INBOX_DIR.glob("*.json"))


def _find_attachments(email: dict) -> tuple[Path | None, Path | None]:
    """Locate the SI and the BL among attachments by filename or content inspection."""
    si = bl = None
    attachments = email.get("attachments") or []
    for rel in attachments:
        path = config.DATA_DIR / rel
        name = path.name.upper()
        stem = path.stem.upper()
        # Check SI markers
        if any(m in name for m in ["_SI.", "_SI_", "SI_", "-SI.", " SHIPPING INSTRUCTION", "SHIPPING_INSTRUCTION"]) or stem == "SI":
            if si is None:
                si = path
        # Check BL markers
        elif any(m in name for m in ["_BL.", "_BL_", "BL_", "-BL.", " BILL OF LADING", "BILL_OF_LADING", "DRAFT_BL", "DRAFT BL"]) or stem == "BL":
            if bl is None:
                bl = path

    # Fallback for 1 attachment if filenames didn't carry obvious markers: inspect content
    if si is None and bl is None and len(attachments) == 1:
        try:
            from .engines.docs import read_text
            p = config.DATA_DIR / attachments[0]
            t = (read_text(p) or "")[:600].upper()
            if any(k in t for k in ["BILL OF LADING", "DRAFT B/L", "DRAFT BL", "B/L NO"]):
                bl = p
            else:
                si = p
        except Exception:
            si = config.DATA_DIR / attachments[0]

    # Fallback for 2 attachments if filenames didn't carry obvious markers: inspect content
    if (si is None or bl is None) and len(attachments) == 2:
        try:
            from .engines.docs import read_text
            p1 = config.DATA_DIR / attachments[0]
            p2 = config.DATA_DIR / attachments[1]
            t1 = (read_text(p1) or "")[:600].upper()
            t2 = (read_text(p2) or "")[:600].upper()
            if "SHIPPING INSTRUCTION" in t1 and ("BILL OF LADING" in t2 or "DRAFT" in t2):
                return p1, p2
            elif "SHIPPING INSTRUCTION" in t2 and ("BILL OF LADING" in t1 or "DRAFT" in t1):
                return p2, p1
        except Exception:
            # Two documents with no text to inspect -- photos of a BL and an SI,
            # which read_text refuses by design. Pairing them in the order they
            # were attached is a guess, but a safe one: the comparison asks
            # whether each field agrees, which is symmetric, so getting the two
            # the wrong way round cannot change a verdict. Returning nothing
            # instead reported "neither was attached" about two real documents.
            return (config.DATA_DIR / attachments[0], config.DATA_DIR / attachments[1])

    return si, bl


def process(email: dict, *, client=None) -> dict:
    """Return the full record for one email: verdict, decision and all Traces."""
    traces = []
    blockers = []
    documents = {}
    comparison = None

    client = client or get_client()

    classification, t_cls = classify(email, client=client)
    traces.append(t_cls)

    if classification["category"] == "BL_COMPARISON":
        attachments = email.get("attachments") or []
        body = email.get("body") or ""

        if not attachments:
            # Semantic intent routing:
            # - If intent is "REQUEST_DRAFT": customer is asking/chasing for draft BL (conversational request).
            #   No missing attachments expected -> no blockers, routes to desk.
            # - Otherwise (e.g. "COMPARE_DOCS"): sender intended document comparison but attachments are missing/dropped.
            # When no model supplies an intent, the fallback derives one from the
            # attachment count alone -- and "no attachments" is the shape of both
            # a chase for a draft and a comparison whose attachments were dropped.
            # The body is the only thing that separates them, so where it says so
            # outright it outranks the inferred intent.
            body_l = body.lower()
            dropped = any(k in body_l for k in ["dropped", "failed to attach",
                                                "forgot to attach", "no attachment",
                                                "omitted"])
            if dropped or classification.get("intent") != "REQUEST_DRAFT":
                blockers.append("attachments were dropped or omitted (missing_attachment)")
        elif len(attachments) == 1:
            blockers.append(f"only 1 attachment provided ({attachments[0]}); both SI and draft BL are required (missing_attachment)")
            si_path, bl_path = _find_attachments(email)
            si_fields, bl_fields = {}, {}
            if si_path:
                si_fields, si_text, si_img, t_si = extract(si_path, client=client)
                traces.append(t_si)
                documents["si"] = {"name": si_path.name, "text": si_text, "image": si_img,
                                   "fields": {k: v.to_dict() for k, v in si_fields.items()}}
            if bl_path:
                bl_fields, bl_text, bl_img, t_bl = extract(bl_path, client=client)
                traces.append(t_bl)
                documents["bl"] = {"name": bl_path.name, "text": bl_text, "image": bl_img,
                                   "fields": {k: v.to_dict() for k, v in bl_fields.items()}}
            if si_fields or bl_fields:
                comparison, t_cmp = compare(si_fields, bl_fields)
                traces.append(t_cmp)
        else:
            si_path, bl_path = _find_attachments(email)
            if si_path is None or bl_path is None:
                have = [p.name for p in (si_path, bl_path) if p]
                blockers.append(
                    "both an SI and a draft BL are required; "
                    + (f"only {', '.join(have)} attached (missing_attachment)" if have else "neither was attached (missing_attachment)"))
                si_fields, bl_fields = {}, {}
                if si_path:
                    si_fields, si_text, si_img, t_si = extract(si_path, client=client)
                    traces.append(t_si)
                    documents["si"] = {"name": si_path.name, "text": si_text, "image": si_img,
                                       "fields": {k: v.to_dict() for k, v in si_fields.items()}}
                if bl_path:
                    bl_fields, bl_text, bl_img, t_bl = extract(bl_path, client=client)
                    traces.append(t_bl)
                    documents["bl"] = {"name": bl_path.name, "text": bl_text, "image": bl_img,
                                       "fields": {k: v.to_dict() for k, v in bl_fields.items()}}
                if si_fields or bl_fields:
                    comparison, t_cmp = compare(si_fields, bl_fields)
                    traces.append(t_cmp)
            else:
                si_fields, si_text, si_img, t_si = extract(si_path, client=client)
                traces.append(t_si)
                bl_fields, bl_text, bl_img, t_bl = extract(bl_path, client=client)
                traces.append(t_bl)

                documents = {
                    "si": {"name": si_path.name, "text": si_text, "image": si_img,
                           "fields": {k: v.to_dict() for k, v in si_fields.items()}},
                    "bl": {"name": bl_path.name, "text": bl_text, "image": bl_img,
                           "fields": {k: v.to_dict() for k, v in bl_fields.items()}},
                }

                # Edge case: unreadable scan or unreadable file
                if si_img or bl_img or not si_fields or not bl_fields:
                    blockers.append("scanned PDF or unreadable document requires manual verification (unreadable)")

                # Edge case: wrong document type
                bl_upper = (bl_text or "")[:400].upper()
                si_upper = (si_text or "")[:400].upper()
                WRONG_DOC_TYPES = [
                    "COMMERCIAL INVOICE", "TAX INVOICE", "PROFORMA INVOICE",
                    "PACKING LIST", "CERTIFICATE OF ORIGIN", "CERTIFICATE OF ANALYSIS",
                    "CERTIFICATE OF QUALITY", "CUSTOMS DECLARATION", "EXPORT DECLARATION",
                    "INSURANCE CERTIFICATE", "DELIVERY ORDER"
                ]
                if any(k in bl_upper or k in si_upper for k in WRONG_DOC_TYPES):
                    blockers.append("wrong document type attached (wrong_doc_type)")

                # Edge case: missing value (blank fields)
                if re.search(r'\b(left blank|blank fields?|missing values?|fields? (are|were) blank|empty fields?|fields? omitted)\b', body, re.IGNORECASE):
                    blockers.append("sender indicated required fields were left blank (missing_value)")

                # Always perform 7-field cross-check so operator sees what is extracted & missing
                comparison, t_cmp = compare(si_fields, bl_fields)
                traces.append(t_cmp)

    decision, t_dec = decide(email, classification, comparison, blockers)
    traces.append(t_dec)

    return {
        "email_id": email.get("email_id"),
        "subject": email.get("subject"),
        "from": email.get("from"),
        "body": email.get("body"),
        "attachments": [a.rsplit("/", 1)[-1] for a in email.get("attachments") or []],
        "classification": classification,
        "comparison": comparison,
        "documents": documents,
        "decision": decision,
        "blockers": blockers,
        "traces": [t.to_dict() for t in traces],
        "total_ms": round(sum(t.ms for t in traces), 1),
    }
