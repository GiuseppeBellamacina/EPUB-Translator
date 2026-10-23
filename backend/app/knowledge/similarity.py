"""
Near-duplicate detection for names and terms (glossary, compendium).

Models re-propose known terms in slightly different forms: "Mara's", "the Order",
"Demon Kings", "Kingdom of Asura" for "Asura Kingdom", "Ruijerdo" for "Ruijerd".
Two terms are the same when they have the same content words (articles and "of"
dropped, simple plurals folded, any order) and each word matches one of the other:
exactly for short words, by TF-IDF cosine over character trigrams for longer ones
(spelling variants). A term with an extra word is a different term ("Sword God" /
"Sword God Style", "knight" / "mage knight"). Pure Python, incremental: the corpora
are a few hundred short strings.
"""

import math
import re
from collections import Counter

NEAR_DUPLICATE = 0.78  # trigram cosine above which two words are spellings of one word
MIN_FUZZY_LENGTH = 5  # shorter words only match exactly (Ruby / Rudy, god / goddess)

_POSSESSIVE = re.compile(r"['’]s?\b")
_PUNCTUATION = re.compile(r"[^\w\s'’]")
_STOPWORDS = {"the", "a", "an", "of", "and"}


def _singular(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def content_words(term: str) -> list[str]:
    text = _POSSESSIVE.sub("", term.lower())
    text = _PUNCTUATION.sub(" ", text.replace("_", " "))
    return [_singular(w) for w in text.split() if w not in _STOPWORDS]


def _trigrams(word: str) -> Counter:
    padded = f" {word} "
    return Counter(padded[i : i + 3] for i in range(len(padded) - 2))


class TermIndex:
    """Known terms as content words, with the trigram statistics of their vocabulary."""

    def __init__(self):
        self._terms: dict[int, list[tuple[str, ...]]] = {}  # word count -> known terms
        self._vocabulary: dict[str, Counter] = {}  # known word -> its trigrams
        self._df: Counter = Counter()  # in how many known words each trigram occurs

    def add(self, term: str) -> None:
        words = tuple(content_words(term))
        if not words:
            return
        self._terms.setdefault(len(words), []).append(words)
        for word in words:
            if word not in self._vocabulary:
                self._vocabulary[word] = _trigrams(word)
                self._df.update(self._vocabulary[word].keys())

    def word_similarity(self, word: str, known: str) -> float:
        """TF-IDF cosine of two words' trigrams; the IDF comes from the other known words,
        so a common ending ("-tion") counts less than a distinctive stem."""
        a, b = _trigrams(word), self._vocabulary[known]
        docs = len(self._vocabulary) - 1

        def weights(counts: Counter) -> dict[str, float]:
            return {
                g: n * (math.log((1 + docs) / (1 + self._df[g] - (g in b))) + 1)
                for g, n in counts.items()
            }

        va, vb = weights(a), weights(b)
        dot = sum(w * vb.get(g, 0.0) for g, w in va.items())
        norm = math.sqrt(sum(w * w for w in va.values()) * sum(w * w for w in vb.values()))
        return dot / norm if norm else 0.0

    def _same_word(self, word: str, known: str) -> bool:
        if word == known:
            return True
        if min(len(word), len(known)) < MIN_FUZZY_LENGTH:
            return False
        return self.word_similarity(word, known) >= NEAR_DUPLICATE

    def find_duplicate(self, term: str) -> str | None:
        """The known term (as its content words) that ``term`` duplicates, if any."""
        words = content_words(term)
        for known in self._terms.get(len(words), ()):
            unused = list(known)
            for word in words:
                match = next((k for k in unused if self._same_word(word, k)), None)
                if match is None:
                    break
                unused.remove(match)
            else:
                return " ".join(known)
        return None
