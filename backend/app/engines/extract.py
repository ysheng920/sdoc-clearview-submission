"""Engine 2 -- pull the 7 shipping fields out of one document.

Deterministic parsing first, the model only for what is left over. Every field
keeps its provenance and a Span back into the source text, because the dashboard
shows the original document beside the extracted value with the evidence
highlighted.

A scan has no source text to point at, so it takes a third path: the page image
goes to the same multimodal model, and the dashboard shows the scan itself
instead of a text pane.
"""
from __future__ import annotations

import base64
import re
from pathlib import Path

from .. import config
from ..llm import get_client
from ..trace import Field, Span, Tracer
from .docs import UnreadableDocument, labelled_lines, page_images, read_text
from .normalize import field_for_label, is_same_as_consignee, normalise, plausible


def extract(path: Path, *, client=None):
    """Return ({field_name: Field}, source_text, page_image_data_uri, Trace)."""
    client = client or get_client()
    tracer = Tracer("extract", document=path.name)
    fields: dict[str, Field] = {}

    try:
        text = read_text(path)
    except Exception as exc:  # noqa: BLE001 - reported, then retried visually
        tracer.step("read", f"no text layer in {path.name}: {exc}")
        return _read_visually(tracer, client, path, fields)

    tracer.step("read", f"read {len(text)} characters from {path.name}",
                chars=len(text), suffix=path.suffix.lower())

    pairs = labelled_lines(text, is_label=field_for_label)
    matched, rejected = [], []
    for label, value, start, end in pairs:
        name = field_for_label(label)
        if name is None:
            continue
        if name in fields:
            # If gross_weight_kg was already matched, allow "TOTAL" line to supersede it
            if name == "gross_weight_kg" and "total" in label.lower() and "total" not in (fields[name].span.label.lower() if fields[name].span and fields[name].span.label else ""):
                pass
            else:
                continue
        if not plausible(name, value):
            # Usually a column header paired with the wrong column's first row.
            # A wrong value is worse than a missing one, so drop it.
            rejected.append(f"{label} -> {name}: {value!r}")
            continue
        if name == "gross_weight_kg" and re.match(r"^[A-Za-z]{2,}\d+", value.strip()):
            rejected.append(f"{label} -> {name}: {value!r} (container serial)")
            continue
        fields[name] = Field(
            name=name, raw=value, value=normalise(name, value),
            source="deterministic", span=Span(start, end, label), confidence=1.0,
        )
        matched.append(f"{label} -> {name}")

    tracer.step(
        "parse_labels",
        f"matched {len(fields)} of {len(config.FIELDS)} fields from {len(pairs)} labelled lines",
        matched=matched, rejected_as_implausible=rejected,
    )

    missing = [f for f in config.FIELDS if f not in fields]
    used = _llm_fill(tracer, client, text, missing, fields) if missing else None

    return _finish(tracer, client, fields, text, None, used=used)


def _finish(tracer, client, fields, text, image_uri, *, used=None):
    # If notify_party is literally "SAME AS CONSIGNEE" or "AS ABOVE",
    # resolve its normalized comparison value to the consignee's normalized value
    np = fields.get("notify_party")
    cg = fields.get("consignee")
    if np and np.raw and is_same_as_consignee(np.raw) and cg and (cg.value or cg.raw):
        np.value = cg.value or normalise("consignee", cg.raw)
        tracer.step("resolve_notify", f"resolved notify_party '{np.raw}' to consignee '{np.value}'")

    still_missing = [f for f in config.FIELDS if f not in fields]
    for name in still_missing:
        fields[name] = Field(name=name, source="missing", confidence=0.0)

    found = len(config.FIELDS) - len(still_missing)
    why = f"{found}/{len(config.FIELDS)} fields found"
    if still_missing:
        why += f"; {', '.join(still_missing)} missing"
    elif all(f.source == "deterministic" for f in fields.values()):
        why += " by label parsing alone"

    used_model = any(f.source in ("llm", "cloud", "vlm") for f in fields.values())
    # `used` is what actually answered, not what was handed in. The client here
    # can be a router, and a router that never reads documents itself still
    # reported its own name: every scan came back labelled with the classifier
    # in front of it, which does not read documents at all.
    backend, model = used or (getattr(client, "name", None), getattr(client, "model", None))
    trace = tracer.finish(
        {name: f.to_dict() for name, f in fields.items()}, why=why,
        # Label-parsed fields cost nothing and involve no model; saying the
        # model's name here made every extraction look like a model call.
        backend=backend if used_model else "deterministic",
        model=model if used_model else None,
        confidence=round(sum(f.confidence for f in fields.values()) / len(config.FIELDS), 3),
    )
    return fields, text, image_uri, trace


_PARTY_RULES = """For shipper, consignee and notify_party, return the party's NAME only.
  - Extract strictly from the designated form field or table cell (e.g. "1. 发货人 (Shipper)", "Shipper", "Consignee"). Do NOT extract from decorative letterhead headers or top logos.
  - Leave out the street address, building, city, postcode and country, even
    though they are printed in the same box.
  - Keep the legal form when it is part of the name (CO., LTD., PTE. LTD.,
    SDN. BHD., GmbH, 有限公司).
  - When the name is printed in more than one language inside that field box, return the one written
    in the Latin alphabet. Return the local-script name if that is the only name in that field box.
  - If notify_party is printed as "SAME AS CONSIGNEE", "SAME AS ABOVE", or "AS ABOVE", resolve it to the consignee's actual company name.
  - Copy it exactly as printed. Do not translate, expand or tidy it."""

_FIELD_RULES = f"""{_PARTY_RULES}
- For container_count, copy the full container quantity and equipment type verbatim as printed (e.g. "3 x 20'GP", "2 x 40'HC", "1 FCL", "4 CONTAINERS"). Do NOT simplify or reduce it to a bare number.
- For gross_weight_kg, keep the number and unit as written (e.g. "66,000 KGS", "21,577 KG")."""

_OCR_PROMPT = f"""Read this scanned shipping document and return ONLY a JSON object.

Use exactly these keys, copying each value verbatim as printed:
shipper, consignee, notify_party, port_of_loading, port_of_discharge,
container_count, gross_weight_kg

{_FIELD_RULES}

Omit any key you cannot read. Never guess a value."""


def _read_visually(tracer, client, path: Path, fields: dict[str, Field]):
    """Last resort for a document with no text layer: read the page image.

    This is the fallback model that does multimodal visual work -- Gemini 3.1 Flash-Lite is multimodal,
    so no separate OCR deployment is involved. Only the 6 scanned PDFs in this
    corpus reach here.
    """
    images = page_images(path)
    if not images:
        tracer.step("vision", f"{path.name} has no page image either -- nothing to read")
        # Nothing was called, so nothing may be named. Reporting the client here
        # put a model's name on a document no model ever saw.
        trace = tracer.finish(None, why=f"{path.name} is unreadable -- needs a human",
                              backend="deterministic")
        return {}, "", None, trace

    image = images[0]
    reply = client.complete(_OCR_PROMPT, task="ocr", max_tokens=config.MAX_TOKENS,
                            image=image)
    if not reply.data:
        tracer.step("vision",
                    f"{reply.backend} could not read the page image: {reply.note}",
                    note=reply.note, ms=round(reply.ms, 1))
        trace = tracer.finish(None, why=f"{path.name} is a scan and could not be read",
                              backend=reply.backend, model=reply.model)
        return {}, "", None, trace

    read = []
    for name in config.FIELDS:
        value = str(reply.data.get(name) or "").strip()
        if not value or not plausible(name, value):
            continue
        fields[name] = Field(
            name=name, raw=value, value=normalise(name, value),
            # No text layer means no offsets: the UI shows the scan itself
            # rather than pretending to highlight a position in a document.
            source="vlm", span=None, confidence=0.7,
        )
        read.append(name)

    tracer.step(
        "vision",
        f"{reply.backend}/{reply.model} read {len(read)} of {len(config.FIELDS)} "
        f"fields off the scanned page in {reply.ms / 1000:.1f}s",
        fields=read, tokens=reply.tokens, note=reply.note,
    )
    uri = "data:image/png;base64," + base64.b64encode(image).decode()
    return _finish(tracer, client, fields, "", uri, used=(reply.backend, reply.model))


def _llm_fill(tracer, client, text: str, missing: list[str],
              fields: dict[str, Field]) -> tuple[str | None, str | None] | None:
    """Ask the model for the fields the label parser could not find.

    Returns the backend and model that answered, so the trace can name what read
    the document rather than what was asked to.
    """
    prompt = _EXTRACT_PROMPT.format(missing=", ".join(missing), text=text[:6000],
                                    party_rules="- " + _PARTY_RULES.replace(chr(10), chr(10) + "  "))
    reply = client.complete(prompt, task="extract",
                            hint={"text": text, "missing": missing},
                            max_tokens=config.MAX_TOKENS)

    if not reply.data or not reply.data.get("fields"):
        tracer.step("llm_fallback",
                    f"asked {reply.backend} for {len(missing)} missing field(s), got nothing usable",
                    missing=missing, note=reply.note, ms=round(reply.ms, 1))
        return None

    found = []
    for name, payload in reply.data["fields"].items():
        if name not in missing or not isinstance(payload, dict):
            continue
        value = str(payload.get("value") or "").strip()
        if not value or not plausible(name, value):
            continue
        evidence = str(payload.get("evidence") or value)
        ev_lower = evidence.lower()
        is_notify_ref = (name == "notify_party" and any(k in ev_lower for k in ("same as", "as above", "consignee", "同收货人", "同上")))
        if not is_notify_ref and any(f != name and (f in ev_lower or f.replace("_", " ") in ev_lower) for f in config.FIELDS):
            continue
        idx = text.find(evidence)
        if idx == -1:
            idx = text.find(value)
            evidence = value
        span = Span(idx, idx + len(evidence), "model evidence") if idx != -1 else None
        fields[name] = Field(
            name=name, raw=value, value=normalise(name, value),
            source="llm",
            span=span, confidence=0.75 if span else 0.5,
        )
        found.append(name)

    tracer.step(
        "llm_fallback",
        f"{reply.backend} recovered {len(found)} of {len(missing)} missing field(s)"
        + ("" if found else " -- none"),
        missing=missing, recovered=found, model=reply.model,
        note=reply.note, tokens=reply.tokens, ms=round(reply.ms, 1),
    )
    return (reply.backend, reply.model) if found else None


_EXTRACT_PROMPT = """Extract shipping document fields from the document below.

Only these fields are missing and needed: {missing}

Return ONLY a JSON object of this shape, with one entry per field you find:
{{"fields": {{"<field_name>": {{"value": "<the value>", "evidence": "<the exact line from the document>"}}}}}}

Rules:
- "evidence" must be copied VERBATIM from the document, character for character.
- Omit any field you cannot find. Never guess.
- Container count: copy the full container quantity and equipment type verbatim as printed (e.g. "3 x 20'GP", "2 x 40'HC", "1 FCL", "4 CONTAINERS"), do not simplify to a bare number.
- Weights: keep the number and unit as written.
{party_rules}

DOCUMENT:
{text}
"""
