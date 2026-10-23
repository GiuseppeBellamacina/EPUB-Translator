"""
Glossary — the live, shared terminology of a translation job.

One instance is shared by every chunk and chapter of a job (chapters may run
concurrently; asyncio is single-threaded, so no locking is needed), so a term
added while translating one chapter is used by the next chunk anywhere.

Model-proposed terms are validated before joining: the source term must occur
in the source text it was proposed for, and an existing entry (user-edited or
earlier) is never overwritten, not even by a near-duplicate spelling of it.
"""

import re

from app.knowledge.matcher import TermMatcher
from app.knowledge.similarity import TermIndex
from app.models.schemas import GlossaryItem

_PLACEHOLDER = re.compile(r"</?\d+/?>")
MIN_ENFORCE_LENGTH = 3
MAX_RELEVANT = 60  # entries per prompt: the chunk's own terms first


def _key(term: str) -> str:
    return term.strip().lower()


def _word_pattern(term: str) -> re.Pattern:
    return re.compile(r"(?<!\w)" + re.escape(term.strip()) + r"(?!\w)", re.IGNORECASE)


def _match_case(source: str, replacement: str) -> str:
    """Mirror the casing of the matched source onto the replacement."""
    if source.isupper() and len(source) > 1:
        return replacement.upper()
    if source[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


class Glossary:
    def __init__(self, entries: list[GlossaryItem] | None = None):
        self._entries: dict[str, GlossaryItem] = {}
        self._known = TermIndex()  # source terms, for near-duplicates
        self._matcher = TermMatcher()  # source terms, to find the ones a text uses
        self.add(entries or [])

    @property
    def entries(self) -> list[GlossaryItem]:
        return list(self._entries.values())

    def __len__(self) -> int:
        return len(self._entries)

    def replace(self, other: "Glossary") -> None:
        """Take ``other``'s entries in place (the graph keeps its reference), in one step:
        readers never see a half-loaded glossary."""
        self.__dict__ = other.__dict__

    def add(self, items: list[GlossaryItem], source_text: str | None = None) -> list[GlossaryItem]:
        """Add new entries, returning those accepted.

        Rejected: empty/1-char terms, duplicates of an existing source term (also near
        ones: "Mara's", "the Order", spelling variants), entries without a target
        (unless do-not-translate) and — when ``source_text`` is given — terms that do
        not occur in it (hallucinated by the model).
        """
        plain_source = _PLACEHOLDER.sub("", source_text) if source_text is not None else None
        accepted = []
        for item in items:
            key = _key(item.source_term)
            if len(key) < 2 or key in self._entries:
                continue
            if self._known.find_duplicate(key):
                continue
            if not item.do_not_translate and not item.target_term.strip():
                continue
            if plain_source is not None and not _word_pattern(key).search(plain_source):
                continue
            entry = item.model_copy(
                update={
                    "source_term": item.source_term.strip(),
                    "target_term": item.target_term.strip(),
                }
            )
            self._entries[key] = entry
            self._known.add(key)
            self._matcher.add(key, key)
            accepted.append(entry)
        return accepted

    def relevant(
        self, text: str, context: str = "", limit: int = MAX_RELEVANT
    ) -> list[GlossaryItem]:
        """Entries whose source term occurs in ``text``, then those only in ``context``
        (the text before it), at most ``limit``: prompts stay small."""
        return [self._entries[k] for k in self._matcher.rank(text, context, limit)]

    def enforce(self, text: str, entries: list[GlossaryItem] | None = None) -> str:
        """Replace source terms the model left untranslated with their target term.

        Only ``entries`` when given (those of the passage translated). Skips
        do-not-translate entries, very short terms and terms whose translation equals
        the source (both would only cause spurious replacements).
        """
        for entry in self._entries.values() if entries is None else entries:
            source, target = entry.source_term, entry.target_term
            if (
                entry.do_not_translate
                or len(source) < MIN_ENFORCE_LENGTH
                or _key(source) == _key(target)
            ):
                continue
            text = _word_pattern(source).sub(lambda m: _match_case(m.group(0), target), text)
        return text
