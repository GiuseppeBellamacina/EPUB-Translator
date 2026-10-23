"""
Settings changed from the UI at runtime: books in parallel and the retrieval caps.

They live with every other default in ``config.yaml`` (``translation:``) and in the
``settings`` object read by the jobs; a change from the UI updates both (only those
lines of the file change). An old ``data/settings.json`` is moved into it once at
startup.
"""

import json
import re

import yaml
from pydantic import BaseModel, Field, ValidationError

from app.core.bootstrap import load_config
from app.core.config import settings


class AppSettings(BaseModel):
    max_parallel_books: int = Field(1, ge=1, le=8)  # books translated at the same time
    # entries per prompt (0 = all the passage mentions), read at every chunk: changes apply
    # to running jobs too. The passage's own mentions come first, then the text before it.
    max_glossary_terms: int = Field(150, ge=0, le=2000)
    max_compendium_entries: int = Field(60, ge=0, le=1000)

    @property
    def glossary_limit(self) -> int | None:
        return self.max_glossary_terms or None

    @property
    def compendium_limit(self) -> int | None:
        return self.max_compendium_entries or None


def load() -> AppSettings:
    try:
        return AppSettings(**{k: getattr(settings, k) for k in AppSettings.model_fields})
    except ValidationError:  # an invalid value in config.yaml: defaults
        return AppSettings()


def save(value: AppSettings) -> None:
    settings.apply_overrides(value.model_dump())
    path = settings.config_file
    if not path.parent.is_dir():  # no config mounted (tests): memory only
        return
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    updated = set_keys(text, "translation", value.model_dump())
    expected = {**(load_config(path).get("translation") or {}), **value.model_dump()}
    if (yaml.safe_load(updated) or {}).get("translation") != expected:  # unusual layout
        config = {**load_config(path), "translation": expected}
        updated = yaml.safe_dump(config, sort_keys=False, allow_unicode=True)
    # written in place: the file is a bind mount, it cannot be replaced
    path.write_text(updated, encoding="utf-8")


def set_keys(text: str, section: str, values: dict) -> str:
    """Set ``section.key: value`` lines in a YAML text, leaving every other line as it is
    (the user's layout, blank lines and comments)."""
    lines = text.splitlines()
    header = re.compile(rf"^{section}:\s*(#.*)?$")
    start = next((i for i, line in enumerate(lines) if header.match(line)), None)
    if start is None:
        body = "".join(f"  {k}: {v}\n" for k, v in values.items())
        return text.rstrip("\n") + f"\n\n{section}:\n{body}"
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i] and not lines[i][0].isspace()),
        len(lines),
    )
    for key, value in values.items():
        line = next((i for i in range(start + 1, end) if re.match(rf"\s+{key}:", lines[i])), None)
        if line is not None:
            lines[line] = f"  {key}: {value}"
            continue
        at = end
        while at - 1 > start and not lines[at - 1].strip():  # after the section's last line
            at -= 1
        lines.insert(at, f"  {key}: {value}")
        end += 1
    return "\n".join(lines) + "\n"


def migrate_legacy() -> None:
    """Move an old ``data/settings.json`` into config.yaml (values set there win)."""
    legacy = settings.data_dir / "settings.json"
    if not legacy.is_file():
        return
    try:
        old = json.loads(legacy.read_text())
    except ValueError:
        old = {}
    known = load_config().get("translation") or {}
    try:
        save(AppSettings(**{**load().model_dump(), **old, **known}))
    except ValidationError:
        pass
    legacy.unlink()
