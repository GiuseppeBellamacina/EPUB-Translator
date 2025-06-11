import re
from bs4.element import NavigableString, Tag


class TextBuffer:
    def __init__(self, translate_func, debug=False, batch_size=None):
        print("\33[34mInitializing TextBuffer with batch size: \33[0m", batch_size)
        self.items = []  # List of (original_tag, text)
        self.translate_func = translate_func
        self.debug = debug
        self.blocking_tags = {"a", "h1", "h2", "title"}
        self.invalid_tags = {"script", "style", "meta"}
        self.batch_size = batch_size

    def add(self, tag, text):
        tag_name = tag.parent.name if tag.parent else None
        prev_tag_name = self._get_parent_name(self.items[-1][0]) if self.items else None

        force_flush = self.items and (
            prev_tag_name == tag_name
            and not self._ends_with_delimiter(self.items[-1][1])
            or prev_tag_name in self.blocking_tags
        )

        if force_flush:
            self.flush()
        self.items.append((tag, text))

        if self._ends_with_delimiter(text):
            self.flush()

    def flush(self):
        if not self.items:
            return

        chunks = []
        chunk = []
        for tag, text in self.items:
            chunk.append((tag, text))
            if self.batch_size and len(chunk) >= self.batch_size:
                chunks.append(chunk)
                chunk = []
        if chunk:
            chunks.append(chunk)

        all_texts = [" ".join(text for _, text in chunk).strip() for chunk in chunks]
        all_translations = self.translate_func(all_texts)

        assert len(all_translations) == len(chunks), "Mismatch between input and output batch lengths"

        for (chunk, translated) in zip(chunks, all_translations):
            if self.debug:
                print("—" * 20)
                print(f"Original: {' '.join(text for _, text in chunk)}")
                print(f"Translated: {translated}")
                print(f"Tags: {[self._get_parent_name(tag) for tag, _ in chunk]}")

            first_tag, _ = chunk[0]

            if isinstance(first_tag, Tag):
                for tag, _ in chunk[1:]:
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
                for tag, _ in chunk:
                    tag.extract()

        self.items.clear()

    def _ends_with_delimiter(self, text):
        return bool(re.search(r"[.!?;:\n]\s*$", text.strip()))

    def _get_parent_name(self, tag):
        return tag.parent.name if tag and tag.parent else None

    def _clone_tag(self, tag):
        new_tag = Tag(name=tag.name)
        for attr, value in tag.attrs.items():
            new_tag[attr] = value
        return new_tag
