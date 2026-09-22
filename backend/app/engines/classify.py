"""Engine 1 -- route an incoming email into one of five operational buckets."""
from __future__ import annotations

import math
import re

from .. import config
from ..llm import get_client
from ..trace import Tracer

PROMPT = """You are triaging a shipping-ops inbox. Read the email and
return ONLY a JSON object: {{"category": "...", "intent": "...", "confidence": 0.0, "reason": "..."}}.

category must be exactly one of: BL_COMPARISON, SI_REQUEST, INVOICE_QUERY, GENERAL, SPAM.
BL_COMPARISON = asks to check/compare a Shipping Instruction against a draft Bill of Lading,
  or asks to send/issue a draft BL for checking/review.
SI_REQUEST = asks to create or issue a NEW Shipping Instruction for a specific shipment
  (not a reminder about SIs in general -- see the GENERAL example below).
INVOICE_QUERY = asks about an invoice, billing, freight, demurrage/detention (D&D), THC, or local charges.
SPAM = unrelated marketing / phishing / irrelevant content.
GENERAL = anything else shipping-related that doesn't fit the above, including
  internal admin reminders, SLA notices, or broadcasts that reference SIs
  without asking you to create or compare one specific document.

intent specifies the detailed semantic intent:
- For BL_COMPARISON:
  * "COMPARE_DOCS": The email asks to verify, compare, or check documents against each other (e.g. SI vs draft BL).
  * "REQUEST_DRAFT": The sender is conversationally asking, chasing, or requesting our team to provide, send, or issue a draft BL.
- For SI_REQUEST: "ISSUE_SI"
- For INVOICE_QUERY: "QUERY_CHARGES"
- For GENERAL: "GENERAL_NOTICE"
- For SPAM: "SPAM"

Worked examples (real emails from this dataset):

Example 1 -- BL_COMPARISON (intent: COMPARE_DOCS):
Subject: "TO CONFIRM DOCS _ 5RSG-00133 _ CALLAO_PERU..."
Body: "Attached are the SI and draft BL for OC 5RSG-00133... Please check the details and confirm."
Attachments: ["attachments/email_001_SI.txt", "attachments/email_001_BL.txt"]
-> {{"category": "BL_COMPARISON", "intent": "COMPARE_DOCS", "confidence": 0.98, "reason": "Requests check of attached SI vs draft BL"}}

Example 2 -- BL_COMPARISON (intent: REQUEST_DRAFT):
Subject: "RE_ TO CONFIRM DOCS _ 5AAT-03056 _ AQABA_JORDAN _ ROXCEL TRADING GMBH _ SIN525534192"
Body: "Dear Hari, Please assist to send the draft BL for SIN832764835 for checking asap. Thank you."
Attachments: []
-> {{"category": "BL_COMPARISON", "intent": "REQUEST_DRAFT", "confidence": 0.96, "reason": "Conversational request for our team to send the draft BL"}}

Example 3 -- BL_COMPARISON (intent: COMPARE_DOCS, dropped attachments):
Subject: "RE_ AFRT - LONG BEACH_US - EVER(EGLV433335384951) - 5RSG-19787..."
Body: "Dear Team, Please compare the SI and draft BL for 070500263211 and confirm (attachments appear to have been dropped)."
Attachments: []
-> {{"category": "BL_COMPARISON", "intent": "COMPARE_DOCS", "confidence": 0.95, "reason": "Wants document comparison but notes attachments were dropped"}}

Example 4 -- INVOICE_QUERY (intent: QUERY_CHARGES):
Subject: "Mill D & D charges - 6437419879"
Body: "Please find the D&D / detention charges for MSDUL0942527743. Kindly confirm the amount before we release payment."
Attachments: []
-> {{"category": "INVOICE_QUERY", "intent": "QUERY_CHARGES", "confidence": 0.9, "reason": "Asks to confirm detention/demurrage charges before payment"}}

Example 5 -- GENERAL (intent: GENERAL_NOTICE):
Subject: "_RPA_ India HSS SD Billing Process Completed - LE HAVRE V.QI540A"
Body: "Reminder: Please submit SI & AED for all pending shipments by end of day. Refer to the attached outstanding list."
Attachments: []
-> {{"category": "GENERAL", "intent": "GENERAL_NOTICE", "confidence": 0.75, "reason": "Broadcast reminder for all pending shipments, not single new SI request"}}

Now classify this email:

Subject: {subject}
From: {sender}
Body:
{body}
Attachments present: {attachments}
"""


def classify(email: dict, *, client=None):
    """Return (result_dict, Trace)."""
    client = client or get_client()
    tracer = Tracer("classify", email_id=email.get("email_id"),
                    subject=email.get("subject"))

    raw_attachments = email.get("attachments") or []
    body = (email.get("body") or "")[:3000]

    # Deterministic fast-path: email submitting an inline SI with no attachments
    body_lower = body.lower()
    if not raw_attachments and "shipping instruction" in body_lower and any(w in body_lower for w in ["please find", "here is", "details below", "as follows", "submitting", "submit"]):
        result = {
            "category": "SI_REQUEST", "intent": "ISSUE_SI", "confidence": 0.99,
            "reason": "Submits shipping instruction in email body (SI_REQUEST)",
            "escalated": False,
        }
        trace = tracer.finish(result, why="SI_REQUEST -- Submits shipping instruction in email body",
                              backend="deterministic", confidence=0.99)
        return result, trace

    prompt = PROMPT.format(
        sender=email.get("from", ""), subject=email.get("subject", ""),
        attachments=raw_attachments,
        body=body,
    )
    hint = {"email_id": email.get("email_id"), "from": email.get("from"),
            "subject": email.get("subject"), "body": email.get("body"),
            "attachments": raw_attachments}

    reply = client.complete(prompt, task="classify", hint=hint,
                            max_tokens=config.MAX_TOKENS,
                            confidence_key="category")
    tracer.step("model",
                f"{reply.backend}/{reply.model} answered in {reply.ms:.0f}ms: {reply.note}",
                model=reply.model, backend=reply.backend, note=reply.note,
                min_logprob=reply.min_logprob, tokens=reply.tokens,
                cost=reply.cost, raw=reply.text[:400])

    data = reply.data or {}
    raw_cat = str(data.get("category", "")).strip()
    if not raw_cat:
        m = re.search(r'["\']?category["\']?\s*:\s*["\']?([A-Za-z_]+)["\']?', reply.text, re.IGNORECASE)
        if m:
            raw_cat = m.group(1).strip()

    model_reason = str(data.get("reason") or "").strip()
    if not model_reason:
        m_r = re.search(r'["\']?reason["\']?\s*:\s*["\']([^"\'\n]+)["\']', reply.text, re.IGNORECASE)
        if m_r:
            model_reason = m_r.group(1).strip()

    model_intent = str(data.get("intent") or "").strip().upper()
    if not model_intent:
        m_i = re.search(r'["\']?intent["\']?\s*:\s*["\']?([A-Za-z_]+)["\']?', reply.text, re.IGNORECASE)
        if m_i:
            model_intent = m_i.group(1).strip().upper()

    # No answer is not a quiet GENERAL. Guessing here turned a provider outage
    # into a confidently mislabelled inbox, which is the failure that costs the
    # most to notice.
    answered = bool(data) or bool(reply.text.strip())
    confidence = ((math.exp(reply.min_logprob) if reply.has_logprobs
                   else float(data.get("confidence") or 0.8)) if answered else 0.0)

    category = raw_cat.upper()
    if category not in config.CATEGORIES:
        cat_lower = raw_cat.lower()
        if "comparison" in cat_lower or "compare" in cat_lower or ("bl" in cat_lower and "si" in cat_lower):
            category = "BL_COMPARISON"
        elif ("new" in cat_lower and "si" in cat_lower) or "si_request" in cat_lower or "si request" in cat_lower:
            category = "SI_REQUEST"
        elif "invoice" in cat_lower or "bill" in cat_lower or "charge" in cat_lower or "payment" in cat_lower:
            category = "INVOICE_QUERY"
        elif "spam" in cat_lower or "marketing" in cat_lower or "phish" in cat_lower:
            category = "SPAM"
        else:
            category = "GENERAL"

    if not model_intent:
        if category == "BL_COMPARISON":
            model_intent = "REQUEST_DRAFT" if not raw_attachments else "COMPARE_DOCS"
        elif category == "SI_REQUEST":
            model_intent = "ISSUE_SI"
        elif category == "INVOICE_QUERY":
            model_intent = "QUERY_CHARGES"
        elif category == "SPAM":
            model_intent = "SPAM"
        else:
            model_intent = "GENERAL_NOTICE"

    if not answered:
        model_reason = ("no classification was made -- "
                        f"{reply.note or 'the model returned nothing'}")
    routing = data.get("_routing") if isinstance(data.get("_routing"), dict) else {}
    result = {"category": category, "intent": model_intent, "confidence": round(confidence, 3),
              "reason": model_reason, "escalated": bool(routing.get("fallback_used")),
              "unclassified": not answered, "routing": routing}
    trace = tracer.finish(
        result, why=f"{category} ({model_intent}) -- {model_reason}" if model_reason else category,
        model=reply.model, backend=reply.backend,
        confidence=round(confidence, 3), escalated=bool(routing.get("fallback_used")),
        routing=routing, tokens=reply.tokens,
    )
    return result, trace
