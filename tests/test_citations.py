import pytest

from ingest.citations import statute_refs


@pytest.mark.parametrize(
    "text, expected",
    [
        ("the claim was barred by s. 4 of the Limitations Act, 2002.", [("limitations-act-2002", "s-4")]),
        ("under section 5(1)(a) of the Limitations Act, 2002, the claim", [("limitations-act-2002", "s-5-1")]),
        ("Limitations Act, 2002, S.O. 2002, c. 24, Sched. B, s. 15(2)", [("limitations-act-2002", "s-15-2")]),
        ("the Occupiers’ Liability Act, R.S.O. 1990, c. O.2, s. 3(1) imposes", [("occupiers-liability-act", "s-3-1")]),
        ("s. 2 of the Dog Owners' Liability Act", [("dog-owners-liability-act", "s-2")]),
        ("section 267.5(5) of the Insurance Act", [("insurance-act", "s-267.5-5")]),
        ("apportioned under the Negligence Act, R.S.O. 1990, c. N.1", [("negligence-act", None)]),
        ("s. 42(6) of the City of Toronto Act, 2006", [("city-of-toronto-act-2006", "s-42-6")]),
        ("the Criminal Code, s. 249", []),
    ],
)
def test_statute_refs(text, expected):
    assert statute_refs(text) == expected


def test_refs_are_deduplicated_in_order():
    text = "s. 4 of the Limitations Act, 2002 ... s. 4 of the Limitations Act, 2002 ... s. 5 of the Limitations Act, 2002"
    assert statute_refs(text) == [("limitations-act-2002", "s-4"), ("limitations-act-2002", "s-5")]


def test_section_is_not_pinned_on_the_wrong_statute():
    refs = statute_refs("liability under the Negligence Act and s. 4 of the Limitations Act, 2002")
    assert refs == [("negligence-act", None), ("limitations-act-2002", "s-4")]
