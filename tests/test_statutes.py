import json

import pytest

from ingest.statutes import display_pinpoint, human_url, parse_law, split_subsections
from ingest.v0 import V0Law

LAW = V0Law("test-act", "Test Act", "SO 2002, c 24, Sched B", "LEGISLATION-ON")
SECTIONS = {
    "1": "In this Act,\n“claim” means a claim to remedy an injury;",
    "4": "Unless this Act provides otherwise, a proceeding shall not be commenced after the second anniversary.",
    "15": "(1) Even if the period has not expired, no proceeding.\n(2) No proceeding after the 15th anniversary,\n(a) the person with the claim,\n(i) is incapable;\n(2.1) Despite subsection (2), none.",
    "25-49": "Omitted (amends or repeals other Acts).",
    "Schedule": "Table of things",
}
MARKDOWN = """# Test Act

S.O. 2002, c. 24, Sched. B

### Definitions

1 In this Act,
“claim” means a claim to remedy an injury;

## PART I LIMITATION PERIODS

### Basic Limitation Period

### Basic limitation period

4 Unless this Act provides otherwise, a proceeding shall not be commenced after the second anniversary.

## part ii ultimate periods

### Ultimate limitation periods

15 (1) Even if the period has not expired, no proceeding.
"""


def row(**overrides):
    base = {
        "name_en": "Test Act",
        "citation_en": "SO 2002, c 24, Sched B",
        "document_date_en": "2024-12-04 00:00:00+00:00",
        "source_url_en": "https://www.ontario.ca/laws/api/v2/legislation/en/doc-search/statute/02l24",
        "unofficial_text_en": MARKDOWN,
        "unofficial_sections_en": json.dumps(SECTIONS),
        "upstream_license": "See upstream license",
    }
    return {**base, **overrides}


@pytest.fixture
def parsed():
    return parse_law(row(), LAW)


def by_pinpoint(parsed):
    return {s["pinpoint"]: s for s in parsed.sections}


def test_document_fields(parsed):
    d = parsed.document
    assert d["slug"] == "test-act"
    assert d["title"] == "Test Act"
    assert d["citation"] == "SO 2002, c 24, Sched B"
    assert d["kind"] == "statute"
    assert str(d["in_force_from"]) == "2024-12-04"
    assert d["url"] == "https://www.ontario.ca/laws/statute/02l24"
    assert len(d["sha256"]) == 64


def test_sha_changes_with_text():
    a = parse_law(row(), LAW).document["sha256"]
    b = parse_law(row(unofficial_sections_en=json.dumps({**SECTIONS, "4": "changed"})), LAW).document["sha256"]
    assert a != b


def test_every_section_key_becomes_a_row(parsed):
    pins = by_pinpoint(parsed)
    for p in ["s-1", "s-4", "s-15", "ss-25-49", "schedule"]:
        assert pins[p]["kind"] == "section"


def test_text_is_preserved_exactly(parsed):
    pins = by_pinpoint(parsed)
    for key, text in SECTIONS.items():
        pin = {"Schedule": "schedule", "25-49": "ss-25-49"}.get(key, f"s-{key}")
        assert pins[pin]["text"] == text


def test_parts_and_headings(parsed):
    pins = by_pinpoint(parsed)
    assert pins["part-i"]["heading"] == "PART I LIMITATION PERIODS"
    assert pins["part-ii"]["heading"] == "part ii ultimate periods"
    assert pins["s-1"]["heading"] == "Definitions" and pins["s-1"]["parent"] is None
    assert pins["s-4"]["heading"] == "Basic limitation period"
    assert pins["s-4"]["parent"] == "part-i"
    assert pins["s-15"]["parent"] == "part-ii"


def test_section_without_markdown_line_keeps_previous_part(parsed):
    assert by_pinpoint(parsed)["ss-25-49"]["parent"] == "part-ii"


def test_subsections(parsed):
    pins = by_pinpoint(parsed)
    subs = [s for s in parsed.sections if s["parent"] == "s-15"]
    assert [s["pinpoint"] for s in subs] == ["s-15-1", "s-15-2", "s-15-2.1"]
    assert pins["s-15-2"]["text"] == "(2) No proceeding after the 15th anniversary,\n(a) the person with the claim,\n(i) is incapable;"
    assert "\n".join(s["text"] for s in subs) == SECTIONS["15"]


def test_sort_order_is_reading_order(parsed):
    order = [s["pinpoint"] for s in parsed.sections]
    assert order[:4] == ["s-1", "part-i", "s-4", "part-ii"]
    assert order.index("s-15") < order.index("s-15-1") < order.index("ss-25-49")
    assert [s["sort_order"] for s in parsed.sections] == list(range(1, len(order) + 1))


def test_pinpoints_unique(parsed):
    pins = [s["pinpoint"] for s in parsed.sections]
    assert len(pins) == len(set(pins))


def test_rules_use_rule_prefix():
    rules = V0Law("rules-of-civil-procedure", "Rules of Civil Procedure", "RRO 1990, Reg 194", "REGULATIONS-ON")
    p = parse_law(row(unofficial_sections_en=json.dumps({"1.06": "(1) Forms.\n(2) Numbers."}), unofficial_text_en="1.06 (1) Forms."), rules)
    assert [s["pinpoint"] for s in p.sections] == ["r-1.06", "r-1.06-1", "r-1.06-2"]
    assert p.document["kind"] == "regulation"


def test_empty_section_text_rejected():
    with pytest.raises(ValueError, match="empty"):
        parse_law(row(unofficial_sections_en=json.dumps({"1": "  "})), LAW)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("No subsections here.", []),
        ("(1) One.\n(2) Two.", ["(1) One.", "(2) Two."]),
        ("(1) One,\n(a) clause;\n(1.1) Inserted.", ["(1) One,\n(a) clause;", "(1.1) Inserted."]),
        ("Intro text\n(1) One.\n(2) Two.", []),  # text before (1): keep the section whole
        ("(1) One.\n(1) Duplicate.", []),  # duplicate labels: keep the section whole
    ],
)
def test_split_subsections(text, expected):
    assert [t for _, t in split_subsections(text)] == expected


@pytest.mark.parametrize(
    "pinpoint, expected",
    [
        ("s-4", "s. 4"),
        ("s-4-1", "s. 4(1)"),
        ("s-1.1-2.1", "s. 1.1(2.1)"),
        ("r-1.06-2", "r. 1.06(2)"),
        ("part-iii.1", "Part III.1"),
        ("schedule", "Schedule"),
        ("form-43b", "Form 43B"),
        ("ss-25-49", "ss. 25-49"),
    ],
)
def test_display_pinpoint(pinpoint, expected):
    assert display_pinpoint(pinpoint) == expected


def test_human_url():
    api = "https://www.ontario.ca/laws/api/v2/legislation/en/doc-search/regulation/900194"
    assert human_url(api) == "https://www.ontario.ca/laws/regulation/900194"


def test_locate_sections_tolerates_out_of_order_markdown():
    from ingest.statutes import locate_sections

    md = "### Heading two\n\n2.02 Motion text\n\n## RULE 2.1\n\n### Heading two-one\n\n2.1.01 Other text"
    found = locate_sections(md, ["2.1.01", "2.02"])  # section map order differs from Markdown order
    assert found["2.1.01"] == ("RULE 2.1", "Heading two-one")
    assert found["2.02"] == (None, "Heading two")


def test_locate_sections_heading_does_not_leak_to_next_section():
    from ingest.statutes import locate_sections

    md = "### Transition\n\n24 Text\n\n25-49 Omitted (amends other Acts)."
    assert locate_sections(md, ["24", "25-49"])["25-49"] == (None, None)


def test_rule_headings_group_like_parts():
    from ingest.statutes import locate_sections, part_pinpoint

    md = "### GENERAL MATTERS\n\n### RULE 1 CITATION, APPLICATION AND INTERPRETATION\n\n### Citation\n\n1.01 These rules may be cited"
    assert locate_sections(md, ["1.01"])["1.01"] == ("RULE 1 CITATION, APPLICATION AND INTERPRETATION", "Citation")
    assert part_pinpoint("RULE 2.1 GENERAL POWERS") == "rule-2.1"
    assert display_pinpoint("rule-2.1") == "Rule 2.1"


def test_hash_changes_with_parser_version(monkeypatch):
    import ingest.statutes as st

    before = st.source_hash(row())
    monkeypatch.setattr(st, "PARSER_VERSION", st.PARSER_VERSION + 1)
    assert st.source_hash(row()) != before


@pytest.mark.parametrize("pinpoint, display, mcgill", [
    ("s-4", "s. 4", "s 4"), ("s-4-1", "s. 4(1)", "s 4(1)"), ("r-1.06-2", "r. 1.06(2)", "r 1.06(2)"),
    ("ss-25-49", "ss. 25-49", "ss 25–49"), ("rr-3-5", "rr. 3-5", "rr 3–5"), ("part-iii.1", "Part III.1", "Part III.1"),
    ("rule-2.1.01", "Rule 2.1.01", "Rule 2.1.01"), ("rule-7a", "Rule 7A", "Rule 7a"), ("743-9", "§ 743-9", "§ 743-9"),
    ("schedule-a", "Schedule A", "Schedule A"), ("para-45", "para 45", "Para 45"),
])
def test_display_and_mcgill_pinpoints(pinpoint, display, mcgill):
    assert display_pinpoint(pinpoint) == display
    assert display_pinpoint(pinpoint, mcgill=True) == mcgill
