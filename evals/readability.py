"""Flesch-Kincaid grade level (stdlib). Syllables by a vowel-group heuristic — good enough to compare summaries
against the grade-10 target; not a linguistics tool."""
import re

WORD = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")


def syllables(word: str) -> int:
    w = word.lower()
    if len(w) <= 3:
        return 1
    if w.endswith("es") and not re.search(r"(?:c|g|s|x|z|ch|sh)es$", w):
        w = w[:-2]  # "makes" -> "mak", but "damages" keeps its syllable
    elif w.endswith("ed") and not re.search(r"[td]ed$", w):
        w = w[:-2]
    elif w.endswith("e") and not re.search(r"[^aeiouy]le$", w):
        w = w[:-1]  # silent final e, except consonant + "le" ("liable")
    n = len(re.findall(r"[aeiouy]+", w))
    n += len(re.findall(r"(?<![tsc])i[aou]|ie(?!$)", w))  # peri-od, li-able, occupi-er (not -tion/-sion)
    return max(1, n)


def fk_grade(text: str) -> float:
    words = WORD.findall(text)
    if not words:
        return 0.0
    sentences = max(1, len(re.findall(r"[.!?]+(?:\s|$)", text)))
    syl = sum(syllables(w) for w in words)
    return round(0.39 * len(words) / sentences + 11.8 * syl / len(words) - 15.59, 1)
