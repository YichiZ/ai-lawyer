import json

import pytest

from evals.gold import TOPICS, load_gold, validate_gold
from ingest.statutes import load_document, parse_law
from test_statutes import LAW, row

GOOD = {"id": "lim-01", "question": "What is the basic limitation period?", "topic": "limitations",
        "expected": [{"slug": "test-act", "pinpoint": "s-4"}], "facts": ["second  Anniversary"], "must_refuse": False}
OOS = {"id": "oos-01", "question": "How do I appeal a BC speeding ticket?", "topic": "out-of-scope",
       "expected": [], "facts": [], "must_refuse": True}


@pytest.fixture
def db(conn):
    load_document(conn, parse_law(row(), LAW))
    return conn


def test_load_gold_reads_jsonl(tmp_path):
    p = tmp_path / "gold.jsonl"
    p.write_text(json.dumps(GOOD) + "\n\n" + json.dumps(OOS) + "\n")
    assert [i["id"] for i in load_gold(p)] == ["lim-01", "oos-01"]


def test_valid_items_pass(db):
    assert validate_gold([GOOD, OOS], db) == []


def test_fact_found_in_subsection_of_expected_section(db):
    item = {**GOOD, "expected": [{"slug": "test-act", "pinpoint": "s-15"}], "facts": ["15th anniversary"]}
    assert validate_gold([item], db) == []


@pytest.mark.parametrize(
    "change, error",
    [
        ({"id": ""}, "missing id"),
        ({"topic": "tax"}, "unknown topic"),
        ({"expected": []}, "no expected pinpoints"),
        ({"expected": [{"slug": "test-act", "pinpoint": "s-999"}]}, "pinpoint not found: test-act s-999"),
        ({"facts": []}, "no facts"),
        ({"facts": ["third anniversary"]}, "fact not in expected text: 'third anniversary'"),
        ({"must_refuse": True}, "in-scope item marked must_refuse"),
    ],
)
def test_invalid_in_scope_items(db, change, error):
    errors = validate_gold([{**GOOD, **change}], db)
    assert any(error in e for e in errors), errors


def test_out_of_scope_must_refuse_and_have_no_expected(db):
    errors = validate_gold([{**OOS, "must_refuse": False, "expected": [{"slug": "test-act", "pinpoint": "s-4"}]}], db)
    assert any("must_refuse" in e for e in errors) and any("expected" in e for e in errors)


def test_duplicate_ids(db):
    assert any("duplicate id lim-01" in e for e in validate_gold([GOOD, GOOD], db))


def test_topics_cover_the_five_guides():
    assert {"limitations", "city-claims", "slip-and-fall", "dog-bites", "motor-vehicle"} <= set(TOPICS)
