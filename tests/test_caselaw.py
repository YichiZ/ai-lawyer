import pytest

from ingest.caselaw import injury_score, is_injury_case, subject_of

CIVIL = "Grillone (Re)\nCollection\nDecisions of the Court of Appeal\nSubject\nCivil\nDecision Content\n"
CRIMINAL = "R. v. X\nSubject\nCriminal\nDecision Content\n"


def test_subject_of():
    assert subject_of(CIVIL) == "Civil" and subject_of(CRIMINAL) == "Criminal" and subject_of("no header") is None


@pytest.mark.parametrize("text, statute", [
    ("the action was statute-barred under the Limitations Act, 2002, S.O. 2002", True),
    ("liability under the Occupiers’ Liability Act", True),
    ("the Dog Owners' Liability Act imposes strict liability", True),
    ("apportionment under the Negligence Act", True),
    ("Statutory Accident Benefits Schedule", True),
    ("Workplace Safety and Insurance Act, 1997", True),
    ("under the Rules of Civil Procedure and the Courts of Justice Act", False),
])
def test_injury_statutes(text, statute):
    assert (injury_score(text)["statutes"] > 0) is statute


def test_is_injury_case_civil_with_statute():
    assert is_injury_case("ONCA", CIVIL + "the claim was out of time under the Limitations Act, 2002")


def test_criminal_onca_is_excluded_even_with_terms():
    assert not is_injury_case("ONCA", CRIMINAL + "negligence " * 5 + "Limitations Act, 2002")


def test_terms_threshold():
    text = CIVIL + "The plaintiff suffered personal injury in a motor vehicle accident caused by the defendant's negligence."
    assert is_injury_case("ONCA", text)
    assert not is_injury_case("ONCA", CIVIL + "a contract dispute about negligence in drafting")


def test_scc_has_no_subject_header_requirement():
    assert is_injury_case("SCC", "In this tort action for personal injury the duty of care and negligence of the occupier")


def test_generic_negligence_without_injury_terms_is_dropped():
    text = CIVIL + "professional negligence in the audit; negligence; negligent misstatement; duty of care owed to investors."
    assert not is_injury_case("ONCA", text)


def test_old_scc_decisions_are_dropped():
    text = "In this tort action for personal injury the duty of care and negligence of the occupier"
    assert is_injury_case("SCC", text, year=1985) and not is_injury_case("SCC", text, year=1925)


from ingest.caselaw import decision_slug, parse_decision, split_paragraphs
from ingest.statutes import display_pinpoint

BODY = ("Header\nDecision Content\nCOURT OF APPEAL\nI. OVERVIEW [1] The appellant was injured. See Smith v. Jones, [2004] 1 S.C.R. 5.\n"
        "[2] The trial judge found negligence at [1] of her reasons.\n[3] Appeal dismissed.")


def test_split_paragraphs_follows_the_sequence_and_ignores_citation_brackets():
    intro, paras = split_paragraphs(BODY)
    assert [n for n, _ in paras] == [1, 2, 3]
    assert paras[0][1] == "The appellant was injured. See Smith v. Jones, [2004] 1 S.C.R. 5."
    assert paras[1][1] == "The trial judge found negligence at [1] of her reasons."  # back-reference kept in text
    assert intro.endswith("I. OVERVIEW")


def test_no_numbered_paragraphs_keeps_one_body_paragraph():
    intro, paras = split_paragraphs("Decision Content\nShort endorsement without numbers.")
    assert paras == [(1, "Short endorsement without numbers.")]


def test_decision_slug_and_pinpoint_display():
    assert decision_slug("2023 ONCA 844") == "2023-onca-844"
    assert display_pinpoint("para-45") == "para 45"


def test_parse_decision_document_and_sections():
    row = {"citation_en": "2023 ONCA 844", "name_en": "Smith v. Jones", "document_date_en": "2023-12-18 00:00:00+00:00",
           "url_en": "https://example.org/d", "unofficial_text_en": BODY, "upstream_license": "non-commercial",
           "dataset": "ONCA"}
    p = parse_decision(row)
    d = p.document
    assert (d["kind"], d["slug"], d["neutral_citation"], d["court"], str(d["date"])) == (
        "decision", "2023-onca-844", "2023 ONCA 844", "ONCA", "2023-12-18")
    assert [s["pinpoint"] for s in p.sections] == ["intro", "para-1", "para-2", "para-3"]
    assert p.sections[1]["text"].startswith("The appellant was injured")


def test_decision_chunks_are_windows_of_whole_paragraphs():
    from ingest.chunks import DECISION_CHUNK_CHARS, plan_decision_chunks

    paras = [{"id": i, "pinpoint": f"para-{i}", "kind": "section", "heading": None, "text": f"Paragraph {i}. " + "word " * 120,
              "parent": None} for i in range(1, 9)]
    intro = [{"id": 0, "pinpoint": "intro", "kind": "part", "heading": "Parties", "text": "Header text", "parent": None}]
    chunks = plan_decision_chunks("Smith v Jones", "2023 ONCA 844", intro + paras)
    assert len(chunks) > 1 and all(len(c["text"]) <= DECISION_CHUNK_CHARS for c in chunks)
    assert "\n".join(c["text"] for c in chunks) == "\n".join(p["text"] for p in paras)  # every paragraph, once, in order
    assert chunks[0]["pinpoint"] == "para-1" and chunks[0]["section_ids"][0] == 1
    assert chunks[0]["context"].startswith("Smith v Jones, 2023 ONCA 844 — paras 1–")
