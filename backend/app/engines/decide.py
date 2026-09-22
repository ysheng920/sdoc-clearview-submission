"""Engine 4 -- turn findings into the action an operator would actually take.

Drafts are drafts. Nothing here sends mail; the draft is shown in the dashboard
for a human to approve, and every draft carries the reasoning that produced it
so the reviewer can check the machine's work instead of trusting it.
"""
from __future__ import annotations

import re

from ..trace import Tracer

IGNORE = "IGNORE"
NO_ACTION = "NO_ACTION"
ACKNOWLEDGE = "ACKNOWLEDGE"
AUTO_CLEAR = "AUTO_CLEAR"
FLAG_DISCREPANCY = "FLAG_DISCREPANCY"
HUMAN_REVIEW = "HUMAN_REVIEW"

# Two different questions, previously conflated into one flag:
#
#   needs_approval  -- a reply was drafted and a person signs it before it is
#                      sent. Routine: 84% of a real inbox lands here.
#   needs_judgement -- the machine could not settle it and wants a decision.
#                      This is the one that belongs in a review queue.
#
# Collapsing them made the review queue hold 437 of 520 emails, which is not a
# queue, and made the dashboard disagree with it by 269.
NEEDS_APPROVAL = {ACKNOWLEDGE, AUTO_CLEAR, FLAG_DISCREPANCY, HUMAN_REVIEW}
NEEDS_JUDGEMENT = {FLAG_DISCREPANCY, HUMAN_REVIEW}


def decide(email: dict, classification: dict, comparison: dict | None,
           blockers: list[str] | None = None):
    """Return (decision_dict, Trace)."""
    tracer = Tracer("decide", email_id=email.get("email_id"),
                    category=classification.get("category"))
    category = classification.get("category")
    blockers = blockers or []

    if blockers:
        action, why = HUMAN_REVIEW, f"cannot proceed automatically: {'; '.join(blockers)}"
    elif classification.get("unclassified"):
        action, why = HUMAN_REVIEW, "classification unavailable -- a human must route this email"
    elif category == "SPAM":
        action, why = IGNORE, "classified as spam -- no operational action"
    elif category == "GENERAL":
        action, why = NO_ACTION, "informational bulletin -- nothing to action"
    elif category in ("SI_REQUEST", "INVOICE_QUERY"):
        action, why = ACKNOWLEDGE, f"{category.lower().replace('_', ' ')} -- acknowledge and route to the desk owner"
    elif comparison is None:
        if classification.get("intent") == "REQUEST_DRAFT" or not email.get("attachments"):
            action, why = ACKNOWLEDGE, "conversational request for draft BL -- acknowledge and route to the desk owner"
        else:
            action, why = HUMAN_REVIEW, "document comparison expected but not performed"
    elif comparison["status"] == "MISMATCH":
        action = FLAG_DISCREPANCY
        why = f"SI and BL disagree on {', '.join(comparison['defect_fields'])}"
    elif comparison["status"] == "NEEDS_REVIEW":
        action = HUMAN_REVIEW
        why = f"incomplete documents -- {', '.join(comparison['missing_fields'])} not found"
    else:
        action, why = AUTO_CLEAR, "all checked fields agree -- safe to confirm the draft BL"

    tracer.step("select_action", f"{action}: {why}", action=action)

    draft = _draft(email, classification, comparison, action, why)
    if draft:
        tracer.step("compose_draft",
                    f"drafted a {len(draft['body'].splitlines())}-line reply "
                    f"(NOT sent -- awaiting human approval)",
                    subject=draft["subject"])

    decision = {
        "action": action,
        "why": why,
        "needs_approval": action in NEEDS_APPROVAL,
        "needs_judgement": action in NEEDS_JUDGEMENT,
        "draft": draft,
    }
    trace = tracer.finish(decision, why=why, backend="deterministic")
    return decision, trace


def _draft(email: dict, classification: dict, comparison: dict | None,
           action: str, why: str) -> dict | None:
    if action in (IGNORE, NO_ACTION):
        return None

    subject = email.get("subject") or "(no subject)"
    # A bare "RE" prefix test also matches "REQUEST BL DRAFT ...", which is not a
    # reply -- require the separator that an actual reply prefix carries.
    already_reply = re.match(r"\s*(re|fw|fwd)\s*[:_\-]", subject, re.I) is not None
    reply_subject = subject if already_reply else f"RE: {subject}"
    sender = email.get("from", "")
    lines: list[str] = ["Dear Sir/Madam,", ""]

    if action == FLAG_DISCREPANCY and comparison:
        lines += [
            "We have checked the draft Bill of Lading against the Shipping Instruction "
            "and found the following discrepancies. Please review and advise before we proceed:",
            "",
        ]
        for name in comparison["defect_fields"]:
            d = comparison["detail"][name]
            lines += [
                f"  {name.replace('_', ' ').title()}",
                f"    Shipping Instruction : {d['si']['raw']}",
                f"    Draft Bill of Lading : {d['bl']['raw']}",
            ]
        lines += ["", "The remaining fields were checked and agree.", ""]
    elif action == AUTO_CLEAR:
        lines += ["We have checked the draft Bill of Lading against the Shipping "
                  "Instruction. All checked fields agree and we confirm the draft as correct.", ""]
    elif action == ACKNOWLEDGE:
        lines += ["Thank you for your email. We have received your request and it has "
                  "been routed to the responsible desk. We will revert shortly.", ""]
    elif action == HUMAN_REVIEW:
        lines += [f"We are reviewing your documents. One or more items require manual "
                  f"checking ({why}). We will revert once confirmed.", ""]

    lines += ["Best regards,", "Documentation Team"]

    return {
        "to": sender,
        "subject": reply_subject,
        "body": "\n".join(lines),
        "status": "DRAFT -- not sent, awaiting human approval",
        # Shown beside the draft so a reviewer can audit the machine's reasoning
        # rather than take the text on trust.
        "reasoning": _reasoning(classification, comparison, action, why),
    }


def _reasoning(classification: dict, comparison: dict | None,
               action: str, why: str) -> dict:
    evidence = []
    if comparison:
        for name, d in comparison["detail"].items():
            if d["status"] != "MATCH":
                evidence.append({
                    "field": name, "status": d["status"], "rule": d["rule"],
                    "si": d["si"]["raw"], "bl": d["bl"]["raw"],
                })
    return {
        # Not "AI". Nothing in the draft came from a model: the text is one of
        # four templates and the values in it come from the deterministic
        # comparison. Saying otherwise put "AI" on the timeline as the engine
        # that wrote the reply, next to a line in this same object stating that
        # no model was involved.
        "generated_by": "deterministic template",
        "action": action,
        "basis": why,
        "classified_as": classification.get("category"),
        "classification_confidence": classification.get("confidence"),
        "classification_reason": classification.get("reason"),
        "escalated_to_larger_model": classification.get("escalated", False),
        "comparison_status": comparison["status"] if comparison else None,
        "comparison_method": "deterministic field rules (no model involved)" if comparison else None,
        "evidence": evidence,
        "disclaimer": "Drafted automatically. A human must approve before sending.",
    }
