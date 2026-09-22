"""Naming standards: make two spellings of the same thing compare equal.

This is what stops "PORT KLANG (WESTPORT), MALAYSIA (MYPKG)" and "Port Klang, MY"
from being reported as a discrepancy. Every rule here is deliberately visible --
comparison explains itself by naming the rule that matched.
"""
from __future__ import annotations

import re

# Label spellings seen across SI and BL forms, per canonical field.
FIELD_ALIASES: dict[str, list[str]] = {
    "shipper": ["shipper", "shipper exporter", "exporter", "shipper name"],
    # "To the order of" is how a negotiable BL names its consignee -- in this
    # corpus no document carries both, so it is a substitute, not an extra party.
    "consignee": ["consignee", "consignee non negotiable", "consigned to",
                  "to the order of", "to order of", "order of"],
    "notify_party": ["notify party", "notify", "notify address", "notify applicant"],
    "port_of_loading": ["port of loading", "pol", "loading port", "load port",
                        "port of receipt", "place of receipt"],
    "port_of_discharge": ["port of discharge", "pod", "discharge port",
                          "destination port", "place of delivery", "final destination"],
    "container_count": ["no of containers or packages", "container count", "containers",
                        "no of containers", "container qty", "equipment", "no of packages",
                        "quantity"],
    "gross_weight_kg": ["gross weight kg", "gross wt kgs", "gross weight", "gross wt",
                        "total gross weight", "weight kg", "total weight"],
}

# Legal-form suffixes carry no identity; two spellings of one company differ here.
_SUFFIXES = re.compile(
    r"\b(co|ltd|limited|llc|inc|corp|corporation|gmbh|bhd|sdn|fze|fz|pte|pvt|"
    r"plc|ag|sa|nv|bv|srl|spa|as|oy|ab|kk|jsc|llp)\b\.?", re.I)
# The same thing in the scripts that do not put spaces around it, so \b cannot
# find its edges. Without these, a Chinese company matched only when both
# documents happened to spell out the legal form -- the Latin side was stripped
# and the Chinese side was not.
_SUFFIXES_CJK = re.compile(
    "(股份有限公司|有限责任公司|有限公司|集团有限公司|集团|公司|"
    "株式会社|有限会社|合同会社|"
    "주식회사|유한회사|"
    "\u0410\u041e|\u0417\u0410\u041e|\u041e\u0410\u041e|\u041e\u041e\u041e|\u041f\u0410\u041e)")

# CJK writes no spaces between words, so any space inside a run of CJK is
# typesetting rather than meaning: "\u682a\u5f0f\u4f1a\u793e \u5c71\u7530\u5546\u4e8b" and "\u682a\u5f0f\u4f1a\u793e\u5c71\u7530\u5546\u4e8b" are one company.
_CJK = r"\u2e80-\u9fff\u3040-\u30ff\uac00-\ud7af\uff00-\uffef"
_CJK_SPACE = re.compile(f"(?<=[{_CJK}])\\s+(?=[{_CJK}])")
# The LOCODE is always parenthesised in this corpus -- 329 port lines carry it
# that way. Matching a bare five-letter token instead would read CHINA, INDIA,
# KENYA and CHILE as location codes (116 occurrences), so require the brackets.
_LOCODE = re.compile(r"\(\s*([A-Z]{2}[A-Z0-9]{3})\s*\)")
# A UN/LOCODE opens with an ISO 3166-1 country code. Without checking it, any
# five-letter city in brackets was read as a code: "\ubd80\uc0b0 (BUSAN)" normalised to
# the uppercase "BUSAN" and then disagreed with the city "busan" beside it.
_ISO_COUNTRIES = frozenset("""
AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL
BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV
CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD
GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM
IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK
LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW
MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR
PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS
ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY
UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW
""".split())
_PARENS = re.compile(r"\([^)]*\)")
# Punctuation out, letters of every script kept. Restricting this to a-z
# silently emptied any non-Latin name: a Chinese shipper normalised to ""
# and was then judged absent from a document it was printed on.
_NONWORD = re.compile(r"[^\w ]+|_+", re.UNICODE)

# "TBA" and "N/A" say not-yet-known rather than naming anything. Treating them
# as values would report a spurious discrepancy; treating them as absent sends
# the document pair to a human, which is what not-yet-known deserves.
_PLACEHOLDER = {"", "n/a", "na", "tba", "tbc", "tbd", "to be advised",
                "to be confirmed", "-", "--", "none", "nil", "null",
                # Not-yet-known says the same thing in any language, and a
                # document that says it in Chinese used to be compared as
                # though the word itself were the port.
                "\u5f85\u5b9a", "\u672a\u5b9a", "\u5f85\u786e\u8ba4", "\u5f85\u78ba\u8a8d", "\u65e0", "\u7121", "\u53e6\u884c\u901a\u77e5",
                "\u672a\u5b9a", "\u672a\u5b9a\u3067\u3059", "\u306a\u3057",
                "\ubbf8\uc815", "\uc5c6\uc74c",
                "\u043d\u0435\u0442", "\u043d\u0435 \u0443\u043a\u0430\u0437\u0430\u043d\u043e", "\u043d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u043d\u043e"}
# A blank ruled onto the form: "____MT", "_______ MTS", "???". Without this,
# "Port of Loading (POL): ____MT" normalised to a port named "mt".
_BLANK_RUN = re.compile(r"^[\s_.\-?*x]*[_.\-?*]{2,}[\s_.\-?*x]*[a-z]{0,4}\.?$", re.I)


# Longest first so a specific alias wins over a shorter one it contains.
_ALIASES_BY_LENGTH = sorted(
    ((a, f) for f, aliases in FIELD_ALIASES.items() for a in aliases),
    key=lambda pair: -len(pair[0]),
)


def norm_label(label: str) -> str:
    """'Gross Wt (kgs)' -> 'gross wt'. Used to look up FIELD_ALIASES."""
    s = _PARENS.sub(" ", label.lower())
    s = _NONWORD.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def field_for_label(label: str) -> str | None:
    """Canonical field name for a document label, or None if it isn't one we want."""
    norm = norm_label(label)
    if not norm:
        return None
    for fieldname, aliases in FIELD_ALIASES.items():
        if norm in aliases:
            return fieldname
    # Real forms qualify their labels: "Shipper (Principal or Seller)",
    # "Total Containers". Match on a whole-word prefix or suffix so those land,
    # while "podium" still cannot be read as "pod". Longest alias first, so
    # "loading port" is not stolen by a shorter competitor.
    for alias, fieldname in _ALIASES_BY_LENGTH:
        if norm.startswith(alias + " ") or norm.endswith(" " + alias):
            return fieldname

    # Last resort: containment, only for aliases long enough that a partial hit
    # cannot be a coincidence.
    for fieldname, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            if len(alias) >= 8 and alias in norm:
                return fieldname
    return None


# Numeric fields pair with a real number, not whatever line follows a column
# header. Without this, a PDF table of CONTAINER NO. / DESCRIPTION / GROSS
# WEIGHT reads the container id "GSLB0479748" as a weight of 479,748 kg --
# a silently wrong value, which is worse than a missing one.
# Weight and count units, in the scripts this corpus does not contain but a real
# inbox does. The model read "22,000 公斤" correctly and the plausibility guard
# threw it away as not looking like a weight, which is the guard misfiring: a
# value it cannot recognise is dropped, so an unlisted unit costs a whole field.
_WEIGHT_UNITS = (r"kgs?|kilograms?|mt|tons?|tonnes?"
                 r"|公斤|千克|公吨|公噸|吨|噸|キロ|キログラム|トン|킬로그램|톤|кг|т|тонн\w*")
# "x" between count and type in English, equipment words, and the counters used instead elsewhere.
_COUNT_JOINERS = r"[x*×]|containers?|units?|pkgs?|packages?|boxes?|ctns?|fcl|teus?|feus?|个|個|台|只|隻|箇|본|개"

# Number words used when documents write quantities in words (e.g. "THREE (3) x 40HQ")
_NUMBER_WORDS_MAP = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
    "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17",
    "eighteen": "18", "nineteen": "19", "twenty": "20",
    "一": "1", "二": "2", "两": "2", "兩": "2", "三": "3", "四": "4",
    "五": "5", "六": "6", "七": "7", "八": "8", "九": "9", "十": "10",
}
_NUMBER_WORDS_REGEX = (
    r"zero|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
    r"一|二|两|兩|三|四|五|六|七|八|九|十"
)

_PLAUSIBLE = {
    "gross_weight_kg": re.compile(rf"^[\d][\d,. ]*({_WEIGHT_UNITS})?\.?$", re.I),
    "container_count": re.compile(
        rf"^\s*(?:"
        rf"\d+\s*(?:(?:{_COUNT_JOINERS})[\s\S]*)?|"
        rf"(?:say\s+)?(?:{_NUMBER_WORDS_REGEX})\s*(?:\(\s*\d+\s*\))?\s*(?:(?:{_COUNT_JOINERS})[\s\S]*)?|"
        rf"(?:\(\s*\d+\s*\))\s*(?:(?:{_COUNT_JOINERS})[\s\S]*)?"
        rf")$",
        re.I,
    ),
}



def plausible(fieldname: str, value: str) -> bool:
    """Does this value look like the field it was paired with?"""
    value = (value or "").strip()
    if not value or is_placeholder(value):
        return False
    rule = _PLAUSIBLE.get(fieldname)
    return bool(rule.match(value)) if rule else True


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", _NONWORD.sub(" ", text.lower())).strip()


def port_city(value: str) -> str:
    """City-only form, ignoring any LOCODE. The fallback when one document
    carries a code and the other spells the port out."""
    # A value that is nothing but a code names no city, and saying it does made
    # "MYPKG" disagree with the same code printed beside "PORT KLANG".
    if is_locode(value.strip().upper()):
        return ""
    outside = _clean(_PARENS.sub(" ", value).split(",")[0])
    if outside and outside.isascii():
        return outside

    # Nothing Latin outside the brackets: a local-script name with the Latin one
    # beside it, "上海, 中国 (SHANGHAI, CHINA)". Brackets are stripped to drop
    # LOCODEs, and that threw away the only spelling the other document uses --
    # so 上海 was compared against shanghai and read as absent.
    #
    # Only when the outside is not Latin, so "PORT KLANG (WESTPORT)" still
    # normalises to port klang rather than to westport.
    for group in _PARENS.findall(value):
        inner = group.strip("()").strip()
        if is_locode(inner.upper()):
            continue
        latin = _clean(inner.split(",")[0])
        if latin and latin.isascii():
            return latin
    return outside


def is_locode(value: str | None) -> bool:
    """Five characters is the shape; an ISO country code is what makes it a code.

    Shape alone let BUSAN, TOKYO and PARIS pass, so a city printed in brackets
    beside its local-script name normalised to an uppercase "code" that then
    disagreed with the same city spelled out on the other document.
    """
    text = value or ""
    return (bool(re.fullmatch(r"[A-Z]{2}[A-Z0-9]{3}", text))
            and text[:2] in _ISO_COUNTRIES)


# Where a company name stops and its address starts. Named once because
# _name_line has to answer the same question about a whole line: a bilingual
# letterhead offers several Latin lines and only one of them is the name.
_ADDRESS_MARKERS = r"bldg|building|p\.?o\.?\s*box|road|street|str\b|strasse|ave|avenue|tower|free zone|zone|blvd|boulevard|lane|way|drive|dr\b|suite|ste\b|floor|fl\b|opernring|new no|no\.?\s*\d"
_ADDRESS_SPLIT = re.compile(rf'(?i)[#]|(?=\b(?:{_ADDRESS_MARKERS})\b)'.replace('{_ADDRESS_MARKERS}', _ADDRESS_MARKERS))
_ADDRESS_LINE = re.compile(rf'(?i)^\s*(?:no\.?\s*)?\d|^\s*(?:{_ADDRESS_MARKERS})\b'
                          .replace('{_ADDRESS_MARKERS}', _ADDRESS_MARKERS))
_ADDRESS_ANYWHERE = re.compile(rf'(?i)\b(?:{_ADDRESS_MARKERS})\b'
                              .replace('{_ADDRESS_MARKERS}', _ADDRESS_MARKERS))


def _has_latin(text: str) -> bool:
    return any(ch.isascii() and ch.isalpha() for ch in text)


def _name_line(value: str) -> str:
    """The line carrying the company name, out of a letterhead.

    The first line, unless it holds no Latin text and a later one does. A
    bilingual letterhead puts the local-script name first and the Latin name
    under it, while the counterpart document carries only the Latin one -- so
    taking the first line threw away the only spelling the two had in common
    and reported one company as two.

    The search stops at the address: a Latin line opening with a street number
    or a PO box is past where the name ended.
    """
    lines = [line.strip() for line in value.split("|")[0].split("\n") if line.strip()]
    if not lines:
        return ""
    if _has_latin(lines[0]):
        return lines[0]
    for line in lines[1:]:
        if not _has_latin(line):
            continue
        # A Latin line naming a street is the address, not the name: the
        # local-script name had no Latin twin and the search is over.
        if _ADDRESS_LINE.match(line) or _ADDRESS_ANYWHERE.search(line):
            break
        return line
    return lines[0]


def norm_entity(value: str) -> str | None:
    """Company names: drop legal suffixes, punctuation, case, and decouple street address."""
    if is_placeholder(value):
        return None
    v = _name_line(value)
    v = re.sub(r'(?i)\b(pte\.?\s*ltd\.?|sdn\.?\s*bhd\.?|co\.?,\s*ltd\.?|co\.?\s*ltd\.?|ltd\.?|fze\.?|gmbh\.?|inc\.?|llc\.?|limited)\s*([A-Z0-9#])', r'\1 \2', v)
    part = _ADDRESS_SPLIT.split(v)[0]
    m = re.search(r'(?i)\b(pte\.?\s*ltd|sdn\.?\s*bhd|co\.?,\s*ltd|co\.?\s*ltd|ltd|fze|gmbh|inc|llc|limited)\b', part)
    if m:
        part = part[:m.start()]
    s = _NONWORD.sub(" ", _SUFFIXES_CJK.sub(" ", _SUFFIXES.sub(" ", part.lower())))
    s = re.sub(r"\s+", " ", s).strip()
    # Last, so the spaces the two passes above introduced are collapsed too.
    return _CJK_SPACE.sub("", s) or None


_SAME_AS_CONSIGNEE = re.compile(
    r"^\s*(?:same\s*(?:as)?\s*(?:the\s*)?(?:consignee|cnee|above)|as\s*above|同收货人|同上)\s*[\.\*]*$",
    re.I
)


def is_same_as_consignee(value: str | None) -> bool:
    """True for values like 'SAME AS CONSIGNEE', 'SAME AS ABOVE', or 'AS ABOVE'."""
    return bool(_SAME_AS_CONSIGNEE.match((value or "").strip()))


def is_placeholder(value: str | None) -> bool:
    """True for values that say 'not decided yet' rather than naming anything."""
    v = (value or "").strip()
    return v.lower() in _PLACEHOLDER or bool(_BLANK_RUN.match(v))


def norm_port(value: str) -> str | None:
    """Prefer the parenthesised UN/LOCODE -- it is unambiguous; else the city."""
    if is_placeholder(value):
        return None
    for code in _LOCODE.finditer(value.upper()):
        if is_locode(code.group(1)):
            return code.group(1)
    # A document may carry the code on its own, with no brackets to mark it.
    # Requiring brackets was right when a bare five-letter token could be CHINA
    # or KENYA; a value that is nothing but a valid code is not that.
    bare = value.strip().upper()
    if is_locode(bare):
        return bare
    return port_city(value) or None


def norm_weight(value: str) -> str | None:
    """'21,577 KG' -> '21577'. Metric tons are converted so units never differ."""
    m = re.search(r"([\d,]+(?:\.\d+)?)", value)
    if not m:
        return None
    try:
        num = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    # \b does not find an edge beside CJK, so those are matched without it.
    if (re.search(r"\b(mt|tons?|tonnes?)\b", value, re.I)
            or re.search(r"(公吨|公噸|吨|噸|トン|톤|тонн)", value)):
        num *= 1000
    return str(int(round(num)))


def norm_containers(value: str) -> str | None:
    """\"3 x 40'HC\" -> '3', \"THREE (3) x 40HQ\" -> '3'. A bare number is taken as the count."""
    if not value:
        return None
    # 1. Digits in parentheses e.g. "THREE (3) x 40HQ", "SAY (3) CONTAINERS"
    m_paren = re.search(r"\(\s*(\d+)\s*\)", value)
    if m_paren:
        return m_paren.group(1)

    # 2. Leading digits: "3 x 40'HC" or "3"
    m_digit = (re.match(rf"\s*(\d+)\s*(?:{_COUNT_JOINERS})", value, re.I)
               or re.match(r"\s*(\d+)\s*$", value))
    if m_digit:
        return m_digit.group(1)

    # 3. Leading number words: "THREE x 40HQ", "THREE CONTAINERS", "SAY THREE CONTAINERS"
    m_word = re.match(rf"^\s*(?:say\s+)?({_NUMBER_WORDS_REGEX})\b", value, re.I)
    if m_word:
        w = m_word.group(1).lower()
        if w in _NUMBER_WORDS_MAP:
            return _NUMBER_WORDS_MAP[w]

    # 4. Fallback: first digit in string if followed by count joiners e.g. "SAY 3 CONTAINERS"
    m_any = re.search(rf"\b(\d+)\s*(?:{_COUNT_JOINERS})", value, re.I)
    if m_any:
        return m_any.group(1)

    return None


_NORMALISERS = {
    "shipper": norm_entity, "consignee": norm_entity, "notify_party": norm_entity,
    "port_of_loading": norm_port, "port_of_discharge": norm_port,
    "gross_weight_kg": norm_weight, "container_count": norm_containers,
}


def normalise(fieldname: str, value: str) -> str | None:
    fn = _NORMALISERS.get(fieldname)
    return fn(value) if fn else value.strip().lower()

