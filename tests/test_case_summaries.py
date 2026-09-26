from ingest.case_summaries import MAX_CHARS, excerpt_for_summary, summarize_cases
from ingest.caselaw import parse_decision
from ingest.statutes import load_document


def test_excerpt_keeps_opening_and_closing_paragraphs_within_budget():
    paras = [f"Paragraph {i}. " + "word " * 100 for i in range(1, 101)]
    text = excerpt_for_summary("Headnote", paras)
    assert text.startswith("Headnote") and "[1] Paragraph 1." in text and "[100] Paragraph 100." in text
    assert "[50] Paragraph 50." not in text and len(text) <= MAX_CHARS + 200


def test_summarize_cases_is_idempotent(conn):
    parsed = parse_decision({"citation_en": "2023 ONCA 9", "name_en": "Smith v. Jones", "document_date_en": "2023-01-01",
                             "url_en": "u", "unofficial_text_en": "Decision Content\n[1] Facts here. [2] Appeal dismissed.",
                             "upstream_license": "l", "dataset": "ONCA"})
    load_document(conn, parsed)
    calls = []
    assert summarize_cases(conn, lambda p: calls.append(p) or "A driver sued; the appeal was dismissed.", workers=1) == 1
    assert "Appeal dismissed." in calls[0] and "Smith v. Jones" in calls[0]
    assert summarize_cases(conn, lambda p: "again", workers=1) == 0
    assert conn.execute("SELECT plain_summary FROM documents WHERE slug = '2023-onca-9'").fetchone()[0].startswith("A driver sued")
