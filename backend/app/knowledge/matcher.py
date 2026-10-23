"""
Which known terms a text mentions, in one pass over the text.

Terms and text are compared as content words (``similarity.content_words``: lowercase,
possessives and simple plurals folded, articles dropped), so "the Superds' village"
mentions "Superd" and "Ruijerd's spear" mentions "Ruijerd". The index is a dict of word
tuples, updated as terms are added: no regex per term, whatever the size of the glossary.
"""

import re
from collections import Counter
from collections.abc import Hashable

from app.knowledge.similarity import content_words

_PLACEHOLDER = re.compile(r"</?\d+/?>")


class TermMatcher:
    def __init__(self):
        self._terms: dict[tuple[str, ...], set[Hashable]] = {}  # folded term -> owners
        self._lengths: set[int] = set()

    def add(self, term: str, owner: Hashable) -> None:
        """Index ``term`` (a name, alias or source term) for the entry ``owner``."""
        words = tuple(content_words(term))
        if words:
            self._terms.setdefault(words, set()).add(owner)
            self._lengths.add(len(words))

    def find(self, text: str) -> Counter:
        """How many times each owner's terms occur in ``text``."""
        words = content_words(_PLACEHOLDER.sub(" ", text))
        found: Counter = Counter()
        for n in self._lengths:
            for i in range(len(words) - n + 1):
                for owner in self._terms.get(tuple(words[i : i + n]), ()):
                    found[owner] += 1
        return found

    def rank(self, text: str, context: str = "", limit: int | None = None) -> list[Hashable]:
        """Owners mentioned in ``text`` (most mentioned first), then those only in ``context``."""
        own, before = self.find(text), self.find(context) if context else Counter()
        ranked = sorted(own, key=lambda o: -own[o]) + sorted(
            (o for o in before if o not in own), key=lambda o: -before[o]
        )
        return ranked[:limit]
