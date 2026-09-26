import pytest

from ingest.bylaws import clean_lines, parse_chapter
from ingest.statutes import display_pinpoint

RAW = """TORONTO MUNICIPAL CODE
CHAPTER 743, STREETS AND SIDEWALKS, USE OF
Chapter 743
STREETS AND SIDEWALKS, USE OF
ARTICLE I
Terminology
§ 743-1. Definitions.
ARTICLE II
General Provisions
§ 743-9. Fouling and obstruction streets.
§ 743-10. Street cleaning and repair, including a very long heading that wraps onto
the next line.
[HISTORY: Adopted by Council.]

\f
743-1

October 9, 2025

TORONTO MUNICIPAL CODE
CHAPTER 743, STREETS AND SIDEWALKS, USE OF
ARTICLE I
Terminology
§ 743-1. Definitions.
A.

As used in this chapter, the following terms shall have the meanings indicated:
SIDEWALK - The part of a street used by pedestrians.
3
ARTICLE II
General Provisions
§ 743-9. Fouling and obstruction streets.
No person shall foul a street.
\f
743-2

October 9, 2025

TORONTO MUNICIPAL CODE
CHAPTER 743, STREETS AND SIDEWALKS, USE OF
§ 743-10. Street cleaning and repair, including a very long heading that wraps onto
the next line.
A.

Every owner shall keep the sidewalk clear.
B.

The City may repair.
\f
743-3

February 26, 2026
"""


@pytest.fixture
def parsed():
    return parse_chapter(RAW, chapter="743", title="Streets and Sidewalks, Use of", pdf_sha256="a" * 64,
                         url="https://www.toronto.ca/legdocs/municode/1184_743.pdf", license="© City of Toronto")


def by_pin(parsed):
    return {s["pinpoint"]: s for s in parsed.sections}


def test_clean_lines_drops_page_furniture():
    lines = clean_lines(RAW, "743")
    assert "TORONTO MUNICIPAL CODE" not in lines
    assert "743-2" not in lines and "October 9, 2025" not in lines and "3" not in lines
    assert not any(l.startswith("CHAPTER 743,") for l in lines)


def test_document(parsed):
    d = parsed.document
    assert d["slug"] == "toronto-municipal-code-743"
    assert d["title"] == "Toronto Municipal Code, Chapter 743, Streets and Sidewalks, Use of"
    assert d["citation"] == "Toronto Municipal Code, c 743"
    assert d["kind"] == "bylaw" and d["reproduction"] == "excerpt"
    assert str(d["in_force_from"]) == "2026-02-26"  # latest page date = consolidation date
    assert len(d["sha256"]) == 64


def test_table_of_contents_is_skipped(parsed):
    sections = [s for s in parsed.sections if s["kind"] == "section"]
    assert [s["pinpoint"] for s in sections] == ["743-1", "743-9", "743-10"]


def test_articles_are_parts(parsed):
    pins = by_pin(parsed)
    assert pins["article-i"]["heading"] == "Article I — Terminology"
    assert pins["743-1"]["parent"] == "article-i"
    assert pins["743-9"]["parent"] == "article-ii"
    assert pins["743-10"]["parent"] == "article-ii"


def test_headings_and_text(parsed):
    pins = by_pin(parsed)
    assert pins["743-10"]["heading"] == "Street cleaning and repair, including a very long heading that wraps onto the next line"
    assert pins["743-10"]["text"] == "A. Every owner shall keep the sidewalk clear.\nB. The City may repair."
    assert pins["743-1"]["text"].startswith("A. As used in this chapter")
    assert "SIDEWALK - The part of a street used by pedestrians." in pins["743-1"]["text"]


def test_display_pinpoint_for_bylaw_sections():
    assert display_pinpoint("743-9") == "§ 743-9"
    assert display_pinpoint("719-4.1") == "§ 719-4.1"
    assert display_pinpoint("article-ii") == "Article II"


def test_no_sections_raises():
    with pytest.raises(ValueError, match="no sections"):
        parse_chapter("TORONTO MUNICIPAL CODE\nnothing here", chapter="1", title="x", pdf_sha256="a" * 64, url="u", license="l")


def test_wrapped_lines_are_rejoined_into_paragraphs():
    raw = """§ 719-2. Time limit.
A.

Every owner or occupant of any building must, within 12 hours after any fall of snow,
rain or hail has ceased, clear away snow.
B.

After the removal, the owner must apply sand.
[Added 1999-11-25 by By-law
No. 776-1999]
BUILDING - Includes the land
appurtenant to the building.
"""
    [s] = parse_chapter(raw, chapter="719", title="Snow", pdf_sha256="c" * 64, url="u", license="l").sections
    assert s["text"].split("\n") == [
        "A. Every owner or occupant of any building must, within 12 hours after any fall of snow, rain or hail has ceased, clear away snow.",
        "B. After the removal, the owner must apply sand.",
        "[Added 1999-11-25 by By-law No. 776-1999]",
        "BUILDING - Includes the land appurtenant to the building.",
    ]
