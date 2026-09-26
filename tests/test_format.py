import pytest

from app.format import indent_lines, mcgill_citation

STATUTE = {"kind": "statute", "title": "Limitations Act, 2002", "citation": "SO 2002, c 24, Sched B"}
REG = {"kind": "regulation", "title": "Statutory Accident Benefits Schedule", "citation": "O Reg 34/10"}
RULES = {"kind": "regulation", "title": "Rules of Civil Procedure", "citation": "RRO 1990, Reg 194"}
BYLAW = {"kind": "bylaw", "title": "Toronto Municipal Code, Chapter 743, Streets and Sidewalks, Use of",
         "citation": "Toronto Municipal Code, c 743"}


@pytest.mark.parametrize(
    "doc, pinpoint, title, reference",
    [
        (STATUTE, "s-4", "Limitations Act, 2002", "SO 2002, c 24, Sched B, s 4"),
        (STATUTE, "s-15-2", "Limitations Act, 2002", "SO 2002, c 24, Sched B, s 15(2)"),
        (STATUTE, "ss-25-49", "Limitations Act, 2002", "SO 2002, c 24, Sched B, ss 25–49"),
        (STATUTE, "part-ii", "Limitations Act, 2002", "SO 2002, c 24, Sched B, Part II"),
        (STATUTE, "schedule", "Limitations Act, 2002", "SO 2002, c 24, Sched B, Schedule"),
        (REG, "s-3-1", "Statutory Accident Benefits Schedule", "O Reg 34/10, s 3(1)"),
        (RULES, "r-2.02", "Rules of Civil Procedure", "RRO 1990, Reg 194, r 2.02"),
        (RULES, "rule-2", "Rules of Civil Procedure", "RRO 1990, Reg 194, Rule 2"),
        (BYLAW, "743-9", "", "City of Toronto Municipal Code, c 743, § 743-9"),
    ],
)
def test_mcgill_citation(doc, pinpoint, title, reference):
    c = mcgill_citation(doc, pinpoint)
    assert (c["title"], c["reference"]) == (title, reference)
    assert c["text"] == (f"{title}, {reference}" if title else reference)


def test_indent_levels():
    text = "\n".join([
        "(1) Even if the period has not expired,",
        "(a) the person with the claim,",
        "(i) is incapable,",
        "(ii) is not represented;",
        "(A) nested item",
        "(b) the person is a minor;",
        "(2) Second subsection.",
    ])
    assert [l["level"] for l in indent_lines(text)] == [1, 2, 3, 3, 4, 2, 1]


def test_letter_i_after_h_is_a_clause():
    text = "(g) seven;\n(h) eight;\n(i) nine;\n(j) ten."
    assert [l["level"] for l in indent_lines(text)] == [2, 2, 2, 2]


def test_plain_lines_and_labels_stay_verbatim():
    lines = indent_lines("Unless this Act provides otherwise,\n“claim” means a claim;")
    assert lines == [{"text": "Unless this Act provides otherwise,", "level": 0},
                     {"text": "“claim” means a claim;", "level": 0}]


def test_bylaw_letter_labels():
    assert [l["level"] for l in indent_lines("A. Every owner shall clear.\nB. The City may repair.")] == [1, 1]


def test_mcgill_citation_for_decisions():
    doc = {"kind": "decision", "title": "Smith v. Jones", "citation": "2023 ONCA 9"}
    assert mcgill_citation(doc, "para-45") == {"title": "Smith v. Jones", "reference": "2023 ONCA 9 at para 45",
                                               "text": "Smith v. Jones, 2023 ONCA 9 at para 45"}
