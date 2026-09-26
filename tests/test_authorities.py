from app.authorities import SECONDARY_LABEL, authorities_named, prose_of, secondary_statutes, unsourced_authorities

CASE = {"title": "Crinson v. Toronto (City)", "kind": "decision"}
STATUTE = {"title": "Limitations Act, 2002", "kind": "statute"}


def test_authorities_named_and_unsourced():
    prose = "Under the Municipal Act, 2001, notice is due in 10 days. The Limitations Act, 2002 also applies, see O. Reg. 461/96."
    assert authorities_named(prose) == ["Municipal Act, 2001", "Limitations Act, 2002", "O. Reg. 461/96"]
    draft = prose + "\n\n**What the law says**\n\n> quote — Limitations Act, 2002"
    assert prose_of(draft) == prose + "\n\n"
    assert unsourced_authorities(draft, ["Limitations Act, 2002"]) == ["Municipal Act, 2001", "O. Reg. 461/96"]
    assert authorities_named("Under the Trespass to Property Act, force is limited.") == ["Trespass to Property Act"]


def test_secondary_statutes_only_when_every_claim_is_a_decision():
    prose = "Under s. 44(10) of the Municipal Act, 2001, notice is due within 10 days."
    assert secondary_statutes(prose, [CASE]) == ["Municipal Act, 2001"]
    assert secondary_statutes(prose, [CASE, STATUTE]) == []  # a statute source: not secondary (the eval calls it invented)
    assert secondary_statutes("The Limitations Act, 2002 applies.", [STATUTE]) == []
    assert secondary_statutes("A court held the occupier liable.", [CASE]) == []
    assert secondary_statutes(prose, []) == []


LIBRARY = ["Highway Traffic Act", "Limitations Act, 2002", "Insurance Act", "O Reg 34/10",
           "Toronto Municipal Code, Chapter 719, Snow and Ice Removal"]


def test_laws_in_the_library_are_not_secondary():
    assert secondary_statutes("Under the Highway Traffic Act, s. 193, the owner is liable.", [CASE], LIBRARY) == []
    assert secondary_statutes("The Limitations Act sets two years.", [CASE], LIBRARY) == []  # year dropped
    assert secondary_statutes("See O. Reg. 34/10.", [CASE], LIBRARY) == []  # citation form
    assert secondary_statutes("The Toronto Municipal Code requires clearing.", [CASE], LIBRARY) == []
    # exact match, not containment: "Insurance Act" in the library does not cover the Health Insurance Act
    assert secondary_statutes("Under the Health Insurance Act, OHIP may sue.", [CASE], LIBRARY) == ["Health Insurance Act"]
    assert secondary_statutes("Under the Municipal Act, 2001, notice is due.", [CASE], LIBRARY) == ["Municipal Act, 2001"]


def test_determiner_phrases_are_not_authorities():
    for text in ("This Act requires notice within 10 days, as the court held.", "Such Act applies.",
                 "The Act says so.", "the Act says so.", "That Code governs.", "Each Act differs."):
        assert authorities_named(text) == [], text
        assert secondary_statutes(text, [CASE]) == [], text
    assert authorities_named("This Highway Traffic Act section applies.") == ["Highway Traffic Act"]


def test_label_names_no_authority():
    assert authorities_named(SECONDARY_LABEL) == []
