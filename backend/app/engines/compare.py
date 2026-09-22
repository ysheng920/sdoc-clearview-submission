"""Engine 3 -- decide, field by field, whether the SI and the BL agree.

No model is involved: a discrepancy report that a human will act on has to be
reproducible and explainable, so every verdict names the rule that produced it.
Those rule names are what the dashboard shows next to each row.
"""
from __future__ import annotations

import re

from .. import config, mappings
from ..trace import Field, Tracer
from .normalize import is_locode, is_same_as_consignee, norm_entity, port_city

MATCH, MISMATCH, MISSING = "MATCH", "MISMATCH", "MISSING"


def extract_container_spec(text: str) -> tuple[str | None, str | None]:
    """Extract (size, type) e.g. ('20', 'gp') or ('40', 'hc') from raw container text."""
    if not text:
        return None, None
    t = text.lower()

    # 1. Size: 20, 40, 45 (e.g. 20', 20ft, 20-foot, 20gp, 40hq)
    size = None
    m_size = re.search(r"(?:^|[^\d])(20|40|45)(?:\s*(?:'|ft|foot|feet|-foot)?)?(?:(?=[^\d])|$)", t)
    if m_size:
        size = m_size.group(1)

    # 2. Type: HC/HQ, GP/DC/DRY, RF/REEFER, OT, FR, TK
    ctype = None
    if re.search(r"(?:^|[\d\s'_/-])(hc|hq|high\s*cube|highcube)(?:[^\w]|$)", t):
        ctype = "hc"
    elif re.search(r"(?:^|[\d\s'_/-])(gp|dc|dry|general(?:\s*purpose)?|standard|std)(?:[^\w]|$)", t):
        ctype = "gp"
    elif re.search(r"(?:^|[\d\s'_/-])(rf|reefer|refrigerated)(?:[^\w]|$)", t):
        ctype = "rf"
    elif re.search(r"(?:^|[\d\s'_/-])(ot|open\s*top)(?:[^\w]|$)", t):
        ctype = "ot"
    elif re.search(r"(?:^|[\d\s'_/-])(fr|flat\s*rack)(?:[^\w]|$)", t):
        ctype = "fr"
    elif re.search(r"(?:^|[\d\s'_/-])(tk|tank)(?:[^\w]|$)", t):
        ctype = "tk"

    return size, ctype


def _compare_field(name: str, si: Field, bl: Field,
                   si_fields: dict[str, Field] | None = None,
                   bl_fields: dict[str, Field] | None = None) -> tuple[str, str]:
    """Return (status, rule) for one field."""
    if not si.value and not bl.value:
        return MISSING, "absent_from_both"
    if not si.value:
        return MISSING, "absent_from_si"
    if not bl.value:
        return MISSING, "absent_from_bl"

    if name in ("shipper", "consignee", "notify_party"):
        si_raw = si.raw or ""
        bl_raw = bl.raw or ""

        # If notify_party is "SAME AS CONSIGNEE", resolve to the document's consignee party
        if name == "notify_party":
            if is_same_as_consignee(si_raw) and si_fields and si_fields.get("consignee"):
                si_raw = si_fields["consignee"].raw or si_raw
            if is_same_as_consignee(bl_raw) and bl_fields and bl_fields.get("consignee"):
                bl_raw = bl_fields["consignee"].raw or bl_raw

        a, b = norm_entity(si_raw), norm_entity(bl_raw)
        if a and b:
            regional_subsidiaries = [
                "middle east", "far east", "asia pacific", "europe", "north america",
                "south america", "latin america", "southeast asia"
            ]
            for reg in regional_subsidiaries:
                if (reg in a) != (reg in b):
                    return MISMATCH, f"distinct_regional_subsidiary ({reg})"
            is_same_as_cnee = (name == "notify_party" and
                               (is_same_as_consignee(si.raw or "") or is_same_as_consignee(bl.raw or "")))
            if a == b:
                return MATCH, "same_as_consignee_match" if is_same_as_cnee else "exact_after_normalisation"
            if a.startswith(b) or b.startswith(a):
                return MATCH, "same_as_consignee_match" if is_same_as_cnee else "entity_prefix_match (one name is abbreviated)"
            t_a = set(a.split())
            t_b = set(b.split())
            if t_a and t_b and len(t_a & t_b) / min(len(t_a), len(t_b)) >= 0.6:
                return MATCH, "same_as_consignee_match" if is_same_as_cnee else "entity_token_overlap"
        # Last: a pair a reviewer explicitly approved. It is checked after every
        # rule so an approval can only ever rescue a MISMATCH, never override a
        # verdict a rule already reached on its own.
        hit = mappings.approved("entity", a, b)
        if hit:
            return MATCH, mappings.rule_name(hit)
        return MISMATCH, "values_differ"

    if name in ("port_of_loading", "port_of_discharge"):
        city_a, city_b = port_city(si.raw or ""), port_city(bl.raw or "")
        tok_a = set(city_a.split())
        tok_b = set(city_b.split())
        overlap = len(tok_a & tok_b) / min(len(tok_a), len(tok_b)) if tok_a and tok_b else 0.0

        if is_locode(si.value) and is_locode(bl.value):
            if si.value == bl.value:
                if not tok_a or not tok_b or overlap >= 0.5:
                    return MATCH, "exact_after_normalisation"
                return MISMATCH, "locode_matched_but_city_differs"
            return MISMATCH, "values_differ"

        if is_locode(si.value) != is_locode(bl.value):
            if city_a == city_b or overlap >= 0.5:
                return MATCH, "city_name_match (one side used a LOCODE)"

        if city_a and city_b and (city_a == city_b or overlap >= 0.5):
            return MATCH, "city_name_match"

        hit = mappings.approved("port", si.value, bl.value)
        if hit:
            return MATCH, mappings.rule_name(hit)

    if name == "gross_weight_kg":
        try:
            w1 = float(si.value or 0)
            w2 = float(bl.value or 0)
            if abs(w1 - w2) < 1.0:
                return MATCH, "exact_after_normalisation"
        except (ValueError, TypeError):
            pass

    if name == "container_count":
        if si.value != bl.value:
            return MISMATCH, "values_differ"

        # If both documents specify equipment specs, ensure size and type do not conflict
        size_si, type_si = extract_container_spec(si.raw or "")
        size_bl, type_bl = extract_container_spec(bl.raw or "")

        if size_si and size_bl and size_si != size_bl:
            return MISMATCH, f"container_size_mismatch ({size_si}' vs {size_bl}')"

        if type_si and type_bl and type_si != type_bl:
            return MISMATCH, f"container_type_mismatch ({type_si.upper()} vs {type_bl.upper()})"

        return MATCH, "exact_after_normalisation"

    if si.value == bl.value:
        return MATCH, "exact_after_normalisation"

    return MISMATCH, "values_differ"


def summarise(detail: dict) -> tuple[dict, str]:
    """Roll seven field verdicts up into one comparison result, plus its reason.

    Split out because a human override rewrites individual field verdicts and the
    whole result has to be recomputed from them. Two copies of this arithmetic
    would eventually disagree, and the one the operator sees would be the wrong one.
    """
    defects = [n for n, d in detail.items() if d["status"] == MISMATCH]
    missing = [n for n, d in detail.items() if d["status"] == MISSING]
    if defects:
        status, why = MISMATCH, (
            f"{len(defects)} field(s) disagree between SI and BL: {', '.join(defects)}")
    elif missing:
        status, why = "NEEDS_REVIEW", (
            f"cannot certify -- {', '.join(missing)} absent from at least one document")
    else:
        status, why = "OK", f"all {len(detail)} fields agree after normalisation"
    return {
        "status": status,
        "has_defect": bool(defects),
        "defect_fields": defects,
        "missing_fields": missing,
        "detail": detail,
    }, why


def compare(si_fields: dict[str, Field], bl_fields: dict[str, Field]):
    """Return (result_dict, Trace)."""
    tracer = Tracer("compare", fields=len(config.FIELDS))
    empty = Field(name="", source="missing")

    detail = {}
    for name in config.FIELDS:
        si = si_fields.get(name, empty)
        bl = bl_fields.get(name, empty)
        status, rule = _compare_field(name, si, bl, si_fields=si_fields, bl_fields=bl_fields)

        detail[name] = {
            "status": status, "rule": rule,
            "si": {"raw": si.raw, "value": si.value, "source": si.source,
                   "span": si.span.to_dict() if hasattr(si.span, "to_dict") else si.span},
            "bl": {"raw": bl.raw, "value": bl.value, "source": bl.source,
                   "span": bl.span.to_dict() if hasattr(bl.span, "to_dict") else bl.span},
        }
        tracer.step(f"field:{name}", f"{name}: {status} via {rule}",
                    si=si.raw, bl=bl.raw, status=status, rule=rule)

    result, why = summarise(detail)
    # Confidence here is coverage, not model belief: how much of the document
    # pair we were actually able to check.
    coverage = 1.0 - len(result["missing_fields"]) / len(config.FIELDS)
    trace = tracer.finish(result, why=why, backend="deterministic",
                          confidence=round(coverage, 3))
    return result, trace
