"""
Cost estimator — what translating a book will cost with a given model.

The token profile comes from the book's real chunks (the same ones the pipeline
will translate) plus the measured size of the pipeline's prompts; per chunk:

- translate: prompt + glossary + summary + overlap context + text → translation
- review:    prompt + glossary + text + translation → verdict (corrected text
  when rejected)
- retries:   a share of rejected chunks is translated and reviewed again
- analysis:  one call on the first substantial unit

Approximations, all module constants: target-language expansion, rejection
rate, Claude's tokenizer producing more tokens than OpenAI's for the same text,
and reasoning models' thinking tokens (billed as output).
"""

from dataclasses import asdict, dataclass

from app.agents.analyzer import ANALYSIS_PROMPT
from app.agents.reviewer import REVIEW_PROMPT
from app.agents.translator_agent import TRANSLATION_PROMPT
from app.services.chunker import SmartChunker
from app.services.documents import Document
from app.services.pricing import ModelPrice, PriceTable
from app.services.translation_service import (
    analysis_text,
    lead_context_for,
    trail_context_for,
)

# Translations take more tokens than the English source (accents, longer words)
EXPANSION = {"english": 1.0, "italian": 1.25, "spanish": 1.2, "french": 1.25, "german": 1.3}
DEFAULT_EXPANSION = 1.25
REJECTION_RATE = 0.2  # share of chunks the reviewer rejects (one retry each)
GLOSSARY_TOKENS = 100  # relevant glossary entries sent per call
COMPENDIUM_TOKENS = 150  # relevant compendium entries sent per call
SUMMARY_TOKENS = 80
JSON_OVERHEAD = 80  # structured-output wrapping, new_terms, compendium_updates
ANALYSIS_OUTPUT = 600
TOKENIZER_FACTOR = {"anthropic": 1.15, "openai": 1.0}  # vs the chars/4 estimate
REASONING_FACTOR = 1.0  # extra thinking tokens per visible output token

DEFAULT_MODELS = {
    "openai": [
        "gpt-4.1-nano",
        "gpt-4o-mini",
        "gpt-5-nano",
        "gpt-4.1-mini",
        "gpt-5-mini",
        "gpt-4.1",
    ],
    "anthropic": ["claude-haiku-5-5", "claude-haiku-4-5", "claude-sonnet-5-5", "claude-opus-5-5"],
}


@dataclass
class TokenProfile:
    """Token counts of a book, independent of model and target language."""

    units: int
    chunks: int
    source_tokens: int  # text to translate
    context_tokens: int  # overlap context sent with chunks
    analysis_tokens: int


@dataclass
class Usage:
    input_tokens: int
    output_tokens: int


def _prompt_tokens(prompt, chunker: SmartChunker) -> int:
    """Size of a prompt template with every variable empty."""
    empty = {name: "" for name in prompt.input_variables}
    return sum(chunker.count_tokens(str(m.content)) for m in prompt.format_messages(**empty))


def profile_document(doc: Document, chunker: SmartChunker) -> TokenProfile:
    chunks = source = context = 0
    for i in range(len(doc.units)):
        unit_chunks = chunker.create_chunks(doc.blocks(i, chunker))
        chunks += len(unit_chunks)
        source += sum(c.total_tokens for c in unit_chunks)
        context += sum(chunker.count_tokens(c.context_text) for c in unit_chunks if c.context_text)
        if unit_chunks and i > 0:  # first chunk gets the previous unit's tail as context
            context += chunker.count_tokens(lead_context_for(doc, i, chunker))
        # every chunk also sees the text that follows it (next chunk's first block)
        context += sum(c.blocks[0].token_count for c in unit_chunks[1:])
        if unit_chunks:
            context += chunker.count_tokens(trail_context_for(doc, i, chunker))
    analysis = chunker.count_tokens(analysis_text(doc))
    return TokenProfile(len(doc.units), chunks, source, context, analysis)


def usage(profile: TokenProfile, target_language: str, review: bool) -> Usage:
    chunker = SmartChunker()
    expansion = EXPANSION.get(target_language.strip().lower(), DEFAULT_EXPANSION)
    translated = profile.source_tokens * expansion
    per_call = GLOSSARY_TOKENS + COMPENDIUM_TOKENS + SUMMARY_TOKENS

    translate_in = (
        profile.chunks * (_prompt_tokens(TRANSLATION_PROMPT, chunker) + per_call)
        + profile.source_tokens
        + profile.context_tokens
    )
    translate_out = translated + profile.chunks * JSON_OVERHEAD
    total_in, total_out = translate_in, translate_out

    if review:
        review_in = (
            profile.chunks
            * (_prompt_tokens(REVIEW_PROMPT, chunker) + GLOSSARY_TOKENS + COMPENDIUM_TOKENS)
            + profile.context_tokens  # the reviewer sees the text before the chunk too
            + profile.source_tokens
            + translated
        )
        review_out = profile.chunks * JSON_OVERHEAD + REJECTION_RATE * translated
        # rejected chunks: one more translation (with feedback) and one more review
        total_in += review_in + REJECTION_RATE * (translate_in + review_in)
        total_out += review_out + REJECTION_RATE * (translate_out + profile.chunks * JSON_OVERHEAD)

    if profile.analysis_tokens:
        total_in += _prompt_tokens(ANALYSIS_PROMPT, chunker) + profile.analysis_tokens
        total_out += ANALYSIS_OUTPUT
    return Usage(round(total_in), round(total_out))


def model_cost(base: Usage, price: ModelPrice) -> dict:
    factor = TOKENIZER_FACTOR.get(price.provider, 1.0)
    input_tokens = base.input_tokens * factor
    output_tokens = base.output_tokens * factor * (1 + (REASONING_FACTOR if price.reasoning else 0))
    return {
        "input_tokens": round(input_tokens),
        "output_tokens": round(output_tokens),
        "cost": input_tokens * price.input_per_token + output_tokens * price.output_per_token,
    }


def estimate(
    profile: TokenProfile,
    prices: PriceTable,
    target_language: str,
    models: dict[str, list[str]] | None = None,
) -> dict:
    """Cost of translating the book with each listed model, with and without review."""
    with_review = usage(profile, target_language, review=True)
    without_review = usage(profile, target_language, review=False)
    rows = []
    for provider, names in (DEFAULT_MODELS if models is None else models).items():
        for name in dict.fromkeys(names):  # dedupe, keep order
            price = prices.models.get(name)
            if price is None or price.provider != provider:
                continue
            rows.append(
                {
                    "provider": provider,
                    "model": name,
                    "input_per_million": price.input_per_token * 1e6,
                    "output_per_million": price.output_per_token * 1e6,
                    "reasoning": price.reasoning,
                    "with_review": model_cost(with_review, price),
                    "without_review": model_cost(without_review, price),
                }
            )
    rows.sort(key=lambda r: r["with_review"]["cost"])
    return {
        "profile": asdict(profile),
        "target_language": target_language,
        "prices_fetched_at": prices.fetched_at,
        "prices_source": prices.source,
        "models": rows,
    }
