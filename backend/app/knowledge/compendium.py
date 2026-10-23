"""
Compendium — what the translation knows about the book's characters, places and
other elements: gender (English often leaves it implicit, Italian never does),
aliases and short translation notes.

Like the glossary, one instance is shared by every chunk of a job and grows while
translating: the model reports in ``compendium_updates`` what a passage reveals,
and ``merge`` folds it into the entry it belongs to (matched by name or alias,
near-duplicates included), so the next chunks and the reviewer see it.
"""

import re

from app.knowledge.matcher import TermMatcher
from app.knowledge.similarity import TermIndex, content_words
from app.models.schemas import CompendiumEntry

_PLACEHOLDER = re.compile(r"</?\d+/?>")
MAX_NOTES = 300  # characters of notes per entry: prompts stay small
MAX_RELEVANT = 25  # entries per prompt: the chunk's own mentions first


def _key(name: str) -> str:
    return " ".join(content_words(name))


def _mentioned(name: str, text: str) -> bool:
    return bool(re.search(r"(?<!\w)" + re.escape(name.strip()) + r"(?!\w)", text, re.IGNORECASE))


class Compendium:
    def __init__(self):
        self._entries: list[CompendiumEntry] = []
        self._user: set[int] = set()  # entries written by the user: never changed
        self._by_key: dict[str, int] = {}  # content-word key of every name/alias -> entry
        self._names = TermIndex()
        self._matcher = TermMatcher()  # names and aliases, to find the entries a text names

    @property
    def entries(self) -> list[CompendiumEntry]:
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def clear(self) -> None:
        """Empty in place (the graph keeps its reference), before reloading."""
        self.__init__()

    def _find(self, entry: CompendiumEntry) -> int | None:
        for name in [entry.name, *entry.aliases]:
            known = self._names.find_duplicate(name)
            if known is not None:
                return self._by_key[known]
        return None

    def knows(self, entry: CompendiumEntry) -> bool:
        """Whether the entry's name or an alias is already an entry (near-duplicates too)."""
        return self._find(entry) is not None

    def _register(self, index: int, name: str) -> bool:
        key = _key(name)
        if not key or key in self._by_key:
            return False
        self._by_key[key] = index
        self._names.add(name)
        self._matcher.add(name, index)
        return True

    def merge(
        self, updates: list[CompendiumEntry], source_text: str | None = None, user: bool = False
    ) -> list[CompendiumEntry]:
        """Fold updates into the compendium, returning the entries that changed.

        A new name becomes an entry; a known one (by name or alias) only gains what it
        lacks: a gender when unknown, new aliases, new notes. Entries written by the user
        are never changed. With ``source_text``, an update whose name and aliases do not
        occur in it is dropped (hallucinated by the model).
        """
        plain = _PLACEHOLDER.sub("", source_text) if source_text is not None else None
        changed: dict[int, CompendiumEntry] = {}
        for update in updates:
            names = [n.strip() for n in [update.name, *update.aliases] if len(n.strip()) > 1]
            if plain is not None:
                if not any(_mentioned(n, plain) for n in names):
                    continue  # hallucinated
                # the full name may come from earlier text; aliases must be in this one
                # (models also list translated forms: "la tutrice")
                names = names[:1] + [n for n in names[1:] if _mentioned(n, plain)]
            if not names:
                continue
            index = self._find(update)
            if index is None:
                entry = update.model_copy(update={"name": names[0], "aliases": [], "notes": ""})
                index = len(self._entries)
                self._entries.append(entry)
                self._register(index, entry.name)
                if user:
                    self._user.add(index)
                changed[index] = entry
            elif index in self._user:
                continue
            entry = self._entries[index]
            new = entry.model_copy(deep=True)
            if new.gender in ("unknown", "n/a") and update.gender in ("male", "female"):
                new.gender = update.gender
            for alias in names:
                if self._register(index, alias):
                    new.aliases.append(alias)
            note = update.notes.strip()
            if note and note.lower() not in new.notes.lower():
                combined = f"{new.notes} {note}".strip()
                new.notes = combined if len(combined) <= MAX_NOTES else new.notes or note
            if new != entry or index in changed:
                self._entries[index] = new
                changed[index] = new
        return list(changed.values())

    def relevant(
        self, text: str, context: str = "", limit: int = MAX_RELEVANT
    ) -> list[CompendiumEntry]:
        """Entries named in ``text`` (name or alias), then those only in ``context``
        (the text before it), at most ``limit``: prompts stay small."""
        return [self._entries[i] for i in self._matcher.rank(text, context, limit)]


def render(entries: list[CompendiumEntry]) -> str:
    """Compact prompt lines: ``- Rudeus (character, male; also Rudy): his notes``."""
    if not entries:
        return "(No entries yet)"
    lines = []
    for e in entries:
        facts = e.kind if e.gender in ("unknown", "n/a") else f"{e.kind}, {e.gender}"
        if e.kind == "character" and e.gender == "unknown":
            facts += ", gender unknown"
        if e.aliases:
            facts += "; also " + ", ".join(e.aliases)
        lines.append(f"- {e.name} ({facts})" + (f": {e.notes}" if e.notes else ""))
    return "\n".join(lines)
