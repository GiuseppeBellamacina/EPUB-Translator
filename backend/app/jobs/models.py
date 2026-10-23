"""Value objects shared by the queue, the runner and the API."""

from pydantic import BaseModel


class RunConfig(BaseModel):
    """The settings of one book's run (stored on the queue item and on the job)."""

    provider_id: int
    model: str | None = None
    review_model: str | None = None
    enable_review: bool = True
    # feature switches (agents/pipeline.Features), plus the end-of-book doubt review
    analysis: bool = True
    use_glossary: bool = True
    learn_glossary: bool = True
    enforce_glossary: bool = True
    use_compendium: bool = True
    learn_compendium: bool = True
    doubt_review: bool = True
    # after an edit touching many passages (or notes), ask before fixing them; off: fix
    ask_before_fixes: bool = True
    source_language: str | None = None  # None: the book's own
    target_language: str | None = None
    style_instructions: str = ""
    temperature: float = 0.0
    max_tokens: int | None = None
    restart: bool = False
