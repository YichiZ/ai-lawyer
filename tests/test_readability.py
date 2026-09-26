import pytest

from evals.readability import fk_grade, syllables


@pytest.mark.parametrize("word, n", [("cat", 1), ("limitation", 4), ("period", 3), ("the", 1), ("occupier", 4),
                                     ("negligence", 3), ("damages", 3), ("liable", 3), ("make", 1), ("anniversary", 5)])
def test_syllables(word, n):
    assert syllables(word) == n


def test_grade_orders_simple_below_legalese():
    simple = "You have two years to sue. The clock starts when you learn about the harm."
    legal = ("Unless this Act provides otherwise, a proceeding shall not be commenced in respect of a claim after the "
             "second anniversary of the day on which the claim was discovered, notwithstanding any agreement.")
    assert fk_grade(simple) < 6 < 10 < fk_grade(legal)


def test_grade_empty_text_is_zero():
    assert fk_grade("") == 0.0
