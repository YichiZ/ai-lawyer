from app.glossary import find_terms

TERMS = ["occupier", "limitation period", "basic limitation period", "claim", "premises"]


def spans(text):
    return [(text[s:e], term) for s, e, term in find_terms(text, TERMS)]


def test_whole_words_case_insensitive():
    assert spans("An Occupier of premises owes a duty.") == [("Occupier", "occupier"), ("premises", "premises")]


def test_longest_match_wins_and_no_overlap():
    assert spans("the basic limitation period applies") == [("basic limitation period", "basic limitation period")]


def test_not_inside_other_words():
    assert spans("claims and reclaimed land") == []  # plural and embedded forms are not matched


def test_each_term_linked_once_per_text():
    assert spans("A claim is a claim.") == [("claim", "claim")]


def test_empty():
    assert find_terms("", TERMS) == [] and find_terms("text", []) == []
