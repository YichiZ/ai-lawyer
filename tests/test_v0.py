import pytest

from ingest.v0 import V0, V0Law, match_v0, norm_citation, norm_title


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("SO 2002, c 24, Sched B", "so 2002 c 24 sched b"),
        ("S.O. 2002, c. 24, Sched. B", "so 2002 c 24 sched b"),
        ("RSO 1990, c C43", "rso 1990 c c43"),
        ("R.S.O. 1990, c. C.43", "rso 1990 c c43"),
        ("RRO 1990, Reg 194", "rro 1990 reg 194"),
        ("O. Reg. 34/10", "o reg 34/10"),
    ],
)
def test_norm_citation(raw, expected):
    assert norm_citation(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Occupiers' Liability Act", "occupiers liability act"),
        ("Occupiers’ Liability Act", "occupiers liability act"),
        ("Occupiers Liability Act", "occupiers liability act"),
        ("Limitations Act, 2002", "limitations act 2002"),
        ("Statutory Accident bEnefits Schedule — Effective September 1, 2010",
         "statutory accident benefits schedule effective september 1 2010"),
    ],
)
def test_norm_title(raw, expected):
    assert norm_title(raw) == expected


def row(name, citation, dataset="LEGISLATION-ON", n=10):
    return {"name_en": name, "citation_en": citation, "dataset": dataset, "num_sections_en": n}


LIMITATIONS = V0Law("limitations-act-2002", "Limitations Act, 2002", "SO 2002, c 24, Sched B", "LEGISLATION-ON")


def test_matches_by_citation_despite_formatting():
    [r] = match_v0([row("Limitations Act, 2002", "S.O. 2002, c. 24, Sched. B", n=54)], [LIMITATIONS])
    assert (r.status, r.row["num_sections_en"]) == ("matched", 54)


def test_similar_title_other_citation_is_not_a_match():
    rows = [row("Real Property Limitations Act", "RSO 1990, c L15"), row("Limitations Act", "RSC 1985, c L-1")]
    [r] = match_v0(rows, [LIMITATIONS])
    assert r.status == "missing"
    assert "Real Property Limitations Act" in r.candidates


def test_citation_match_with_wrong_title_is_flagged():
    [r] = match_v0([row("Some Other Act", "SO 2002, c 24, Sched B")], [LIMITATIONS])
    assert r.status == "title_mismatch"


def test_title_may_carry_a_suffix():
    sabs = V0Law("statutory-accident-benefits-schedule", "Statutory Accident Benefits Schedule", "O Reg 34/10", "REGULATIONS-ON")
    rows = [row("Statutory Accident bEnefits Schedule — Effective September 1, 2010", "O Reg 34/10", "REGULATIONS-ON")]
    assert match_v0(rows, [sabs])[0].status == "matched"


def test_wrong_dataset_is_not_a_match():
    [r] = match_v0([row("Limitations Act, 2002", "SO 2002, c 24, Sched B", "REGULATIONS-ON")], [LIMITATIONS])
    assert r.status == "missing"


def test_duplicate_citation_rows_are_flagged():
    rows = [row("Limitations Act, 2002", "SO 2002, c 24, Sched B")] * 2
    assert match_v0(rows, [LIMITATIONS])[0].status == "ambiguous"


def test_v0_list_is_consistent():
    assert len({law.slug for law in V0}) == len(V0) == 12
    assert len({norm_citation(law.citation) for law in V0}) == len(V0)
