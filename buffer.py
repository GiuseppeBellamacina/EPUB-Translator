import re
from bs4.element import NavigableString, Tag

class TextBuffer:
    def __init__(self, translate_func, debug=False, batch_size=1):
        self.translate_func = translate_func
        self.debug = debug
        self.batch_size = batch_size

        self.blocking_tags = {"a", "h1", "h2", "title"}
        self.invalid_tags = {"script", "style", "meta"}

        self.current_phrase = []
        self.phrases = []

    def add(self, tag, text):
        tag_name = self._get_parent_name(tag)

        if self.current_phrase:
            last_tag, last_text = self.current_phrase[-1]
            last_tag_name = self._get_parent_name(last_tag)

            ends_with_delim = self._ends_with_delimiter(last_text)
            blocking = tag_name in self.blocking_tags or last_tag_name in self.blocking_tags
            same_tag = tag_name == last_tag_name
            valid_repeat = same_tag and tag_name not in self.invalid_tags
            changed_tag = tag_name != last_tag_name

            force_boundary = ends_with_delim or blocking or valid_repeat or changed_tag

            if force_boundary:
                self._commit_phrase()

        self.current_phrase.append((tag, text))

        if len(self.phrases) >= self.batch_size:
            self._flush_phrases()

    def flush(self):
        if self.current_phrase:
            self._commit_phrase()
        if self.phrases:
            self._flush_phrases()

    def _commit_phrase(self):
        if self.current_phrase:
            self.phrases.append(self.current_phrase)
            self.current_phrase = []

    def _flush_phrases(self):
        if not self.phrases:
            return

        original_texts = ["".join(text for _, text in phrase).strip() for phrase in self.phrases]
        translations = self.translate_func(original_texts)
        assert len(translations) == len(self.phrases), "Mismatch in batch size"

        for phrase, translated in zip(self.phrases, translations):
            first_tag, _ = phrase[0]

            if self.debug:
                print("—" * 20)
                print(f"Original: {''.join(t for _, t in phrase)}")
                print(f"Translated: {translated}")
                print(f"Tags: {[self._get_parent_name(t) for t, _ in phrase]}")

            if isinstance(first_tag, Tag):
                for tag, _ in phrase[1:]:
                    tag.extract()
                first_tag.clear()
                first_tag.append(NavigableString(translated))
            else:
                parent = first_tag.parent
                parent_tag_name = parent.name if parent else None
                if not parent_tag_name or parent_tag_name in self.invalid_tags:
                    parent_tag_name = "p"
                    new_tag = Tag(name=parent_tag_name)
                else:
                    new_tag = self._clone_tag(parent)
                new_tag.clear()
                new_tag.append(NavigableString(translated))
                first_tag.insert_before(new_tag)
                for tag, _ in phrase:
                    tag.extract()

        self.phrases.clear()

    def _ends_with_delimiter(self, text):
        return bool(re.search(r"[.!?;:]\s*$", text.strip()))

    def _get_parent_name(self, tag):
        return tag.parent.name if tag and tag.parent else None

    def _clone_tag(self, tag):
        new_tag = Tag(name=tag.name)
        for attr, value in tag.attrs.items():
            new_tag[attr] = value
        return new_tag
