import pytest

from ingest.citations import internal_refs, statute_refs


@pytest.mark.parametrize(
    "text, expected",
    [
        ("revised in accordance with clause 268 (1.4) (b).", ["s-268-1.4"]),
        ("the limits in subsection 18 (3) apply", ["s-18-3"]),
        ("the benefit under section 30, if purchased", ["s-30"]),
        ("paragraph 3 of subsection 28 (1)", ["s-28-1"]),
        ("subparagraph i of paragraph 2 of subsection 3 (1)", ["s-3-1"]),
        ("section 5 of this Act", ["s-5"]),
        ("section 30 ... section 30", ["s-30"]),
        # a list or range resolves its first item only (ceiling), and only when the whole list is in this law
        ("subsection 18 (3) and section 18", ["s-18-3"]),
        ("sections 25 to 49", ["s-25"]),
        ("sections 3, 4 and 5 of this Act", ["s-3"]),
        ("sections 3, 4 and 5 of the Negligence Act", []),
        ("section 5 and section 6 of the Act", []),
        ("sections 25 to 49 of the said Act", []),
        ("section 7 or 8 of Ontario Regulation 34/10", []),
        # another law's provision, or a relative reference within the same section: not followed (#61)
        ("section 280 of the Act", []),
        ("subsection 5 (1) of the Act", []),
        ("clause 3 (1) (a) of Ontario Regulation 34/10", []),
        ("Despite subsection (2), none.", []),
    ],
)
def test_internal_refs(text, expected):
    assert [pin for pin, _ in internal_refs(text)] == expected


def test_internal_refs_mark_provisions_that_set_the_terms():
    text = ("the amounts in subsection 7 (1) shall be revised in accordance with clause 268 (1.4) (b), "
            "subject to paragraph 3 of subsection 28 (1); see clause 268 (1.4) (a)")
    assert internal_refs(text) == [("s-7-1", False), ("s-268-1.4", True), ("s-28-1", True)]


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
        ("s. 44(10) of the Municipal Act, 2001", [("municipal-act-2001", "s-44-10")]),
        ("a subrogated claim under s. 30 of the Health Insurance Act", [("health-insurance-act", "s-30")]),
        ("the Compulsory Automobile Insurance Act, R.S.O. 1990, c. C.25, s. 2(1)",
         [("compulsory-automobile-insurance-act", "s-2-1")]),
        ("paid out of the fund under the Motor Vehicle Accident Claims Act", [("motor-vehicle-accident-claims-act", None)]),
        ("s. 3 of the Trespass to Property Act", [("trespass-to-property-act", "s-3")]),
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
