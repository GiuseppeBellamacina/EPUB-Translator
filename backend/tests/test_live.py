"""Real-provider smoke tests. Excluded by default; run with ``pytest -m live``.

Uses the providers declared in the real config.yaml/.env (mounted in the dev container).
Each test makes a single tiny call to keep cost/quota negligible.
"""

from pathlib import Path

import pytest

from app.agents.translator_agent import translate_chunk
from app.core.bootstrap import load_config, load_keys, resolve_providers
from app.core.llm_factory import LLMConfig, create_llm

pytestmark = pytest.mark.live

ENV_FILE = Path("/run/secrets/app.env")
CONFIG_FILE = Path("/config/config.yaml")


def _provider(name: str) -> dict:
    specs = resolve_providers(load_config(CONFIG_FILE), load_keys(ENV_FILE))
    spec = next((s for s in specs if s["name"] == name), None)
    if spec is None:
        pytest.skip(f"provider {name!r} not configured")
    return spec


# config.yaml has no default models: a cheap one per provider (free on OpenRouter)
@pytest.mark.parametrize(
    "name, model",
    [("OpenRouter", "nvidia/nemotron-3.5-super-vl:free"), ("OpenAI", "gpt-4.1-nano")],
)
async def test_translate_one_sentence(name, model):
    spec = _provider(name)
    params = spec.get("params") or {}
    llm = create_llm(
        LLMConfig(
            provider=spec["type"],
            model=model,
            api_key=spec["api_key"],
            base_url=spec.get("base_url"),
            max_retries=2,
            structured_output_method=params.get("structured_output_method"),
        )
    )
    result = await translate_chunk(
        llm=llm,
        text="The old lighthouse stood at the edge of the cliff.",
        context="",
        chapter_summary="",
        glossary=[],
        source_language="english",
        target_language="italian",
    )
    assert "faro" in result.translated_text.lower()
