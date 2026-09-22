"""One runnable check over the whole pipeline, with no model involved.

Extraction, comparison, blocker detection and the recommended action are all
deterministic; the only thing here that needs a model is deciding the category,
and that is replayed from ground_truth.json rather than simulated. So these
assertions are stable without a GPU, an API key, or a stand-in that invents
answers. Run it with `python tests/test_pipeline.py`.
"""
import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from support import Labelled, Refuses, run  # noqa: E402

from app.engines.compare import _compare_field, compare  # noqa: E402
from app.engines.extract import extract  # noqa: E402
from app.trace import Field  # noqa: E402
from app.llm.base import LLMReply  # noqa: E402
from app.engines.normalize import (field_for_label, is_locode, normalise,  # noqa: E402
                                   plausible)
from app import sampling  # noqa: E402


def test_conversational_draft_request_acknowledges_without_blockers():
    record = run("email_003")
    assert record["classification"]["category"] == "BL_COMPARISON"
    assert record["classification"]["intent"] == "REQUEST_DRAFT"
    assert not record["blockers"]
    assert record["decision"]["action"] == "ACKNOWLEDGE"
    assert "conversational request for draft BL" in record["decision"]["why"]


def test_every_engine_emits_a_trace():
    record = run("email_001")
    engines = [t["engine"] for t in record["traces"]]
    assert engines == ["classify", "extract", "extract", "compare", "decide"], engines
    for t in record["traces"]:
        assert t["why"], f"{t['engine']} finished without saying why"
        assert t["steps"], f"{t['engine']} recorded no steps"


def test_evidence_spans_slice_back_to_the_extracted_value():
    """The highlighting in the UI is only honest if the offsets are exact."""
    for doc_key in ("si", "bl"):
        record = run("email_001")
        doc = record["documents"][doc_key]
        for name, field in doc["fields"].items():
            if field["span"] is None:
                continue
            start, end = field["span"]["start"], field["span"]["end"]
            assert doc["text"][start:end] == field["raw"], (
                f"{doc_key}.{name}: span {start}:{end} does not match {field['raw']!r}")


def test_known_mismatch_is_caught_and_a_draft_explains_it():
    record = run("email_004")
    comparison = record["comparison"]
    assert comparison["status"] == "MISMATCH"
    assert set(comparison["defect_fields"]) == {"consignee", "notify_party"}
    assert record["decision"]["action"] == "FLAG_DISCREPANCY"

    draft = record["decision"]["draft"]
    assert draft is not None and "not sent" in draft["status"].lower()
    # The disagreeing values must appear in the body, or the reply is useless.
    assert "EAST BRIGHT FZ-LLC" in draft["body"]
    assert "UAB NOVAKOPA" in draft["body"]
    # The reply is a template, and the trace has to say so: the model chose
    # the category, not a word of this text.
    assert draft["reasoning"]["generated_by"] == "deterministic template"


def test_clean_pair_clears_without_a_model_deciding_it():
    record = run("email_001")
    assert record["comparison"]["status"] == "OK"
    assert record["decision"]["action"] == "AUTO_CLEAR"
    compare_trace = next(t for t in record["traces"] if t["engine"] == "compare")
    assert compare_trace["backend"] == "deterministic"


def test_label_variants_map_to_one_canonical_field():
    """SI and BL spell the same field differently; that is the whole problem."""
    assert field_for_label("Shipper/Exporter") == field_for_label("SHIPPER") == "shipper"
    assert field_for_label("Discharge Port") == field_for_label("POD") == "port_of_discharge"
    assert field_for_label("Gross Wt (kgs)") == field_for_label("Gross Weight (KG)") == "gross_weight_kg"
    # A negotiable BL names its consignee this way, and never carries both.
    assert field_for_label("To the Order of") == "consignee"
    assert field_for_label("Vessel Name") is None


def test_normalisation_makes_equivalent_spellings_compare_equal():
    assert normalise("gross_weight_kg", "21,577 KG") == "21577"
    assert normalise("gross_weight_kg", "138 MT") == "138000"
    assert normalise("container_count", "6 x 40'HC") == "6"
    assert normalise("consignee", "MOORIM SP CO., LTD") == normalise("consignee", "Moorim SP")
    # Only a bracketed code is a LOCODE -- CHINA is a country, not a port code.
    assert normalise("port_of_loading", "NANTONG, CHINA (CNNTG)") == "CNNTG"
    assert normalise("port_of_discharge", "BUSAN, SOUTH KOREA") == "busan"
    # Not-yet-known must read as absent, not as a value that could disagree.
    assert normalise("port_of_discharge", "TBA") is None
    assert normalise("consignee", "N/A") is None


def test_a_name_that_is_not_in_the_latin_alphabet_is_still_a_name():
    """Normalisation stripped every non-Latin character, so a Chinese shipper
    normalised to "" and the engine reported it absent from a document it was
    printed on -- on both documents at once, which should have been impossible.
    """
    cn = "日出国际货运有限公司"        # a company name, in Chinese
    assert normalise("shipper", cn), "a name in another script is still a name"
    assert normalise("shipper", cn) == normalise("shipper", cn + chr(10) + "Some street 200")

    # One document spells the port locally with the Latin name beside it, the
    # other only in Latin. Dropping the brackets to remove LOCODEs threw away
    # the only spelling the two had in common.
    local = "上海, 中国 (SHANGHAI, CHINA)"
    assert normalise("port_of_loading", local) == normalise("port_of_loading", "SHANGHAI, CHINA")

    # And the bracket rule must not fire when there is Latin text outside it:
    # WESTPORT is a terminal inside Port Klang, not the port the other side names.
    assert normalise("port_of_loading", "PORT KLANG (WESTPORT), MALAYSIA") == "port klang"


def test_the_same_facts_written_in_another_language_still_compare_equal():
    """Everything here was Latin-only by accident rather than by decision.

    Label parsing genuinely is Latin-only -- the model covers those documents --
    but normalisation runs on whatever the model read, and every table it
    consulted listed English only. So a correctly read value was thrown away by
    the plausibility guard, or compared against a differently-spelled form of
    itself and reported as a discrepancy.
    """
    # Units. The guard exists to drop a container id read as a weight; an
    # unrecognised unit is not that, and dropping it costs a whole field.
    for weight in ("22,000 KG", "22,000 公斤", "22,000 キロ", "22 吨", "22 MT"):
        assert plausible("gross_weight_kg", weight), weight
    assert normalise("gross_weight_kg", "22 吨") == normalise("gross_weight_kg", "22 MT")
    assert not plausible("gross_weight_kg", "GSLB0479748"), "the guard still has to bite"

    for count in ("20 x 40'GP", "20 个 40尺柜", "20개 40피트"):
        assert plausible("container_count", count) and normalise("container_count", count) == "20", count
    assert plausible("container_count", "THREE (3) x 40HQ") and normalise("container_count", "THREE (3) x 40HQ") == "3"
    assert not plausible("container_count", "COATED IVORY BOARD")

    # Not-yet-known. Compared as a value it is a spurious discrepancy.
    for unknown in ("TBA", "待定", "未定", "미정", "нет"):
        assert normalise("port_of_discharge", unknown) is None, unknown

    # Legal form and inter-word spacing, which CJK does not use for meaning.
    assert normalise("shipper", "日出国际货运有限公司") == normalise("shipper", "日出国际货运")
    assert normalise("consignee", "株式会社 山田商事") == normalise("consignee", "株式会社山田商事")


def test_both_reading_paths_ask_for_a_party_the_same_way():
    """Two calls on the same cell have to be told the same thing.

    A party box prints a name and an address, and the prompts left "the value"
    to the model: reading the same document twice returned the name alone once
    and the whole block the other time, and the comparison read one company as
    two. The rules are written once for that reason -- a path that quietly stops
    including them brings the disagreement back.
    """
    from app.engines.extract import _EXTRACT_PROMPT, _OCR_PROMPT, _PARTY_RULES

    assert _PARTY_RULES in _OCR_PROMPT
    rendered = _EXTRACT_PROMPT.format(
        missing="shipper", text="",
        party_rules="- " + _PARTY_RULES.replace(chr(10), chr(10) + "  "))
    for line in _PARTY_RULES.splitlines():
        assert line.strip() in rendered, line

    # The three things the rules have to settle, since each was a live failure.
    lowered = _PARTY_RULES.lower()
    assert "address" in lowered, "the address is what gets included by accident"
    assert "latin" in lowered, "a bilingual letterhead names the party twice"
    assert "exactly as printed" in lowered, "a copied value is the safety argument"


def test_a_bilingual_letterhead_names_one_company_not_two():
    """The BL prints the name twice and the SI prints it once.

    norm_entity kept the first line to cut the address off the name, which on a
    bilingual letterhead is the local-script name -- so the only spelling the
    two documents shared was thrown away and one company was reported as two.
    """
    NL = chr(10)
    bl = ("大洋棕榈贸易有限公司" + NL
          + "OCEAN PALM TRADING CO., LTD." + NL
          + "中国广东省深圳市南山区科技南路 100 号")
    assert normalise("shipper", bl) == normalise("shipper", "OCEAN PALM TRADING CO., LTD.")

    # The address still has to be cut off, and a Latin first line still wins.
    assert normalise("consignee", "GLOBAL OILS PTE. LTD." + NL + "8 Marina View, #15-01") == "global oils"
    assert normalise("shipper", "NAGAPPA EXPORTS" + NL + "NEW NO : 23, L-BLOCK") == "nagappa exports"
    # A local-script name with only an address under it keeps the name.
    assert normalise("shipper", "日出国际货运有限公司" + NL + "上海市浦东新区 200 号") == "日出国际货运"


def test_five_letters_in_brackets_is_not_automatically_a_port_code():
    """A UN/LOCODE opens with an ISO country code; BUSAN does not.

    Shape alone made a city printed beside its local-script name normalise to an
    uppercase "code", which then disagreed with the same city spelled out.
    """
    assert is_locode("MYPKG") and is_locode("CNNTG")
    assert not is_locode("BUSAN"), "BU is not a country"
    assert not is_locode("port klang"), "a city is not a code"

    def port(raw):
        return Field(name="port_of_discharge", raw=raw,
                     value=normalise("port_of_discharge", raw), source="deterministic")

    status, rule = _compare_field("port_of_discharge", port("부산 (BUSAN)"), port("BUSAN, KOREA"))
    assert status == "MATCH", f"{status} via {rule}"

    # A code on its own, against the same code printed beside its city.
    status, _rule = _compare_field(
        "port_of_discharge", port("PORT KLANG (WESTPORT), MALAYSIA (MYPKG)"), port("MYPKG"))
    assert status == "MATCH", status

    # And the real defect this corpus contains still has to be caught.
    status, rule = _compare_field(
        "port_of_loading", port("SINGAPORE (SGSIN)"),
        port("PORT KLANG (WESTPORT), MALAYSIA (SGSIN)"))
    assert status == "MISMATCH" and "city_differs" in rule, f"{status} via {rule}"


def test_placeholder_ports_need_review_rather_than_flagging_a_defect():
    si, *_ = extract(config.DATA_DIR / "attachments" / "email_001_SI.txt", client=Refuses())
    bl, *_ = extract(config.DATA_DIR / "attachments" / "email_001_BL.txt", client=Refuses())
    bl["port_of_discharge"].raw = "TBA"
    bl["port_of_discharge"].value = None

    result, _ = compare(si, bl)
    assert "port_of_discharge" in result["missing_fields"]
    assert "port_of_discharge" not in result["defect_fields"]
    assert result["status"] == "NEEDS_REVIEW"


def test_block_layout_documents_yield_their_fields():
    """Label on one line, value on the next -- 36 attachments use this, and the
    first parser read none of them."""
    for name in ("email_055_BL.docx", "email_059_BL.pdf"):
        fields, *_ = extract(config.DATA_DIR / "attachments" / name, client=Refuses())
        found = [f for f in config.FIELDS if fields[f].raw]
        assert len(found) == 7, f"{name}: only got {found}"


def test_a_value_has_to_look_like_the_field_it_was_paired_with():
    """A column header sits above its rows, so naive pairing hands the wrong
    column over: a table of CONTAINER NO. / GROSS WEIGHT read the container id
    GSLB0479748 as 479,748 kg. A silently wrong weight is worse than a missing
    one, so implausible values are dropped rather than kept.

    Checked directly because the corpus no longer produces the pairing -- the
    rule was doing its job invisibly, and nothing failed when it was removed.
    """
    assert plausible("gross_weight_kg", "21,577 KG")
    assert plausible("gross_weight_kg", "138 MT")
    assert not plausible("gross_weight_kg", "GSLB0479748"), "a container id is not a weight"
    assert not plausible("gross_weight_kg", "MSDU1234567")

    assert plausible("container_count", "6 x 40'HC")
    assert plausible("container_count", "6")
    assert plausible("container_count", "THREE (3) x 40HQ")
    assert plausible("container_count", "SAY THREE (3) CONTAINERS ONLY")
    assert not plausible("container_count", "COATED IVORY BOARD")

    # Fields with no shape to check accept anything that is not a placeholder.
    assert plausible("shipper", "APRIL FAR EAST (M) SDN BHD")
    assert not plausible("shipper", "TBA")


def test_one_side_naming_the_port_and_the_other_coding_it_still_matches():
    """SI and BL routinely disagree on form, not on fact: NANTONG, CHINA (CNNTG)
    against Nantong. Without the city fallback that reads as a discrepancy and
    goes to a person who has nothing to decide."""
    def field(raw):
        return Field(name="port_of_loading", raw=raw, value=normalise("port_of_loading", raw),
                     source="deterministic")

    coded, named = field("NANTONG, CHINA (CNNTG)"), field("Nantong")
    status, rule = _compare_field("port_of_loading", coded, named)
    assert status == "MATCH", f"{status} via {rule}"
    # The exact rule matters: a second, broader city branch sits below this one
    # and would quietly cover for it, so asserting only "matched somehow" would
    # let the LOCODE-aware path be deleted without anything failing.
    assert rule == "city_name_match (one side used a LOCODE)", rule

    # And it must not flatten two genuinely different ports.
    other = field("BUSAN, SOUTH KOREA")
    assert _compare_field("port_of_loading", coded, other)[0] == "MISMATCH"


def test_a_blank_form_field_stays_missing_rather_than_becoming_a_value():
    """Every one of these was a silently wrong value, which is worse than none."""
    si, *_ = extract(config.DATA_DIR / "attachments" / "email_517_SI.txt", client=Refuses())
    # "Port of Loading (POL): ____MT" is a ruled-off blank, not a port called "mt".
    assert si["port_of_loading"].raw is None
    # "Port of Discharge (POD): TBA" is not yet decided.
    assert si["port_of_discharge"].raw is None
    # A real value on the same document still comes through.
    assert si["gross_weight_kg"].value == "340770"

    other, *_ = extract(config.DATA_DIR / "attachments" / "email_519_SI.txt", client=Refuses())
    # "SHIPPER:" is empty; it must not swallow the next field's line.
    assert other["shipper"].raw is None, other["shipper"].raw
    assert other["consignee"].raw == "UAB NOVAKOPA"


def test_a_column_header_does_not_donate_the_wrong_columns_value():
    """CONTAINER NO. / DESCRIPTION / GROSS WEIGHT (KG) sit above their rows, so
    naive pairing reads a container id as a weight."""
    si, *_ = extract(config.DATA_DIR / "attachments" / "email_208_SI.pdf", client=Refuses())
    # The real total is stated further down, past a glyph pypdf could not map.
    assert si["gross_weight_kg"].value == "143940", si["gross_weight_kg"].raw


def test_a_quota_is_filled_exactly_from_the_bucket_it_names():
    """Asking for 10 BL_COMPARISON is a coin toss over whether anything
    interesting turns up -- every defect and edge case in this corpus sits
    inside that one category, so the buckets split it by what actually happens."""
    gt = sampling.ground_truth()
    original = sampling.used_ids
    sampling.used_ids = lambda: set()
    try:
        want = {"bl_defect": 4, "bl_edge": 3, "SPAM": 2}
        ids, short = sampling.pick(want, seed=7)
        assert not short and len(ids) == 9
        got = collections.Counter(sampling.bucket_of(gt[i]) for i in ids)
        assert dict(got) == want, got

        # The three BL buckets must not overlap, or a quota double-counts.
        for eid, label in gt.items():
            if label["category"] == "BL_COMPARISON":
                assert not (label.get("review_reason") and label.get("has_defect")), eid
    finally:
        sampling.used_ids = original


def test_a_processed_email_is_not_offered_again():
    """Repeated runs should walk forward through the corpus, not re-bill the
    same work. Asking for more than remains reports the gap instead of
    quietly substituting from another bucket."""
    original = sampling.used_ids
    try:
        sampling.used_ids = lambda: set()
        first, _ = sampling.pick({"bl_edge": 12}, seed=1)
        assert len(first) == 12

        sampling.used_ids = lambda: set(first)
        second, short = sampling.pick({"bl_edge": 12}, seed=1)
        assert not set(second) & set(first), "handed back an email already processed"
        # Only 20 edge cases exist, so 12 used leaves 8 and a shortfall of 4.
        assert len(second) == 8 and short == {"bl_edge": 4}
    finally:
        sampling.used_ids = original


def test_review_queue_separates_a_decision_from_a_signature():
    """One flag for both meanings put 84% of the inbox in the review queue."""
    mismatch = run("email_004")["decision"]
    assert mismatch["needs_judgement"] is True, "a discrepancy is a decision"
    assert mismatch["needs_approval"] is True, "and its draft still needs signing"

    clean = run("email_001")["decision"]
    assert clean["action"] == "AUTO_CLEAR"
    assert clean["needs_judgement"] is False, "nothing to decide when all fields agree"
    assert clean["needs_approval"] is True, "but a person still sends the confirmation"

    spam = run("email_116")["decision"]
    assert spam["needs_judgement"] is False and spam["needs_approval"] is False


def test_two_emails_with_no_attachments_are_not_the_same_email():
    """Both arrive with nothing attached, and they need opposite handling.

    One is a customer chasing us for a draft BL; the other wanted a comparison
    and the attachments were dropped in transit. An intent inferred from the
    attachment count cannot tell them apart -- it sees "no attachments" both
    times -- so the body has to be read.
    """
    chase = run("email_003")
    assert chase["blockers"] == [], "chasing us for a draft is not a blocked case"
    assert chase["decision"]["action"] == "ACKNOWLEDGE"

    for eid in ("email_506", "email_508", "email_510"):
        dropped = run((eid))
        assert dropped["blockers"], f"{eid} says its attachments were dropped"
        assert "missing_attachment" in dropped["blockers"][0], dropped["blockers"]
        assert dropped["decision"]["action"] == "HUMAN_REVIEW"


def test_unreadable_document_escalates_instead_of_guessing():
    record = run("email_512")
    assert record["decision"]["action"] == "HUMAN_REVIEW"
    assert record["blockers"], "an unreadable scan must say why it stopped"


class RouterDouble(Refuses):
    """A router that delegates, and answers under a different name.

    The one stand-in in this file, and deliberately not a model: it invents no
    extraction, only a reply whose `backend` differs from the client's own name.
    That difference is the whole check -- see the test below.
    """

    name = "router"
    model = "primary -> fallback"

    def complete(self, prompt: str, *, task: str = "", hint: dict | None = None,
                 max_tokens: int = 400, confidence_key: str | None = None,
                 image: bytes | None = None) -> LLMReply:
        self.calls += 1
        return LLMReply(
            text="", backend="fallback", model="the-model-that-answered",
            data={"fields": {"notify_party": {"value": "ACME NOTIFY LTD",
                                              "evidence": "Notify Party: ACME NOTIFY LTD"}}},
            note="answered by the fallback")


def test_an_image_attachment_goes_to_the_page_reader_not_the_text_parser():
    """A photo of a document is a document.

    Unknown suffixes fall through to read_text, which decodes with
    errors="replace" and so returns noise instead of raising -- an image was
    label-parsed as binary garbage and the page was never looked at. The routing
    is checked here, not the reading: no model is called.
    """
    from app.engines.docs import UnreadableDocument, page_images, read_text

    png = Path(__file__).resolve().parent / "_probe.png"
    # Smallest valid PNG: header plus one IHDR chunk is enough to be recognised.
    png.write_bytes(bytes.fromhex("89504e470d0a1a0a") + b"IHDR" + bytes(20))
    try:
        try:
            read_text(png)
        except UnreadableDocument as exc:
            assert "text layer" in str(exc)
        else:
            raise AssertionError("an image must not be read as text")
        assert page_images(png), "the image itself is the page to read"
    finally:
        png.unlink()


def test_a_trace_names_what_read_the_document_not_what_was_asked():
    """Provenance, not quality.

    A router hands document work to whichever model can actually do it, and the
    trace used to record the router's own name -- so every scan came back
    attributed to a two-model route whose first half cannot read a document at
    all, and the dashboard repeated it.
    """
    doc = Path(__file__).resolve().parent.parent / "data" / "attachments" / "email_090_SI.txt"
    assert doc.exists(), doc

    # Nothing was asked: label parsing found everything, so no model is named.
    _f, _t, _i, trace = extract(doc, client=RouterDouble())
    assert trace.backend == "deterministic", trace.backend
    assert trace.model is None, trace.model

    # A gap the parser cannot fill is named after whoever filled it.
    partial = Path(__file__).resolve().parent / "_partial.txt"
    partial.write_text("Shipper: ACME PAPER PTE LTD\n", encoding="utf-8")
    try:
        fields, _t, _i, trace = extract(partial, client=RouterDouble())
        assert fields["notify_party"].source == "llm"
        assert trace.backend == "fallback", f"named the router, not the reader: {trace.backend}"
        assert trace.model == "the-model-that-answered", trace.model
    finally:
        partial.unlink()

def test_container_size_and_type_mismatches_are_flagged():
    """Even when container counts match (3 == 3), 20'GP vs 40'HC is a discrepancy."""
    f_20gp = Field(name="container_count", raw="3 x 20'GP", value="3")
    f_40hc = Field(name="container_count", raw="3 x 40'HC", value="3")
    f_40gp = Field(name="container_count", raw="3 x 40'GP", value="3")
    f_20dry = Field(name="container_count", raw="3 x 20FT DRY CONTAINER", value="3")
    f_bare = Field(name="container_count", raw="3 CONTAINERS", value="3")

    # 1. Size mismatch (20' vs 40')
    status, rule = _compare_field("container_count", f_20gp, f_40hc)
    assert status == "MISMATCH"
    assert "container_size_mismatch" in rule

    # 2. Type mismatch (GP vs HC)
    status, rule = _compare_field("container_count", f_40gp, f_40hc)
    assert status == "MISMATCH"
    assert "container_type_mismatch" in rule

    # 3. Equivalent phrasing (20'GP vs 20FT DRY) matches
    status, rule = _compare_field("container_count", f_20gp, f_20dry)
    assert status == "MATCH"

    # 4. Count-only BL (3 CONTAINERS) matches without false alarm
    status, rule = _compare_field("container_count", f_20gp, f_bare)
    assert status == "MATCH"


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
            passed += 1
    print(f"\n{passed} checks passed")
