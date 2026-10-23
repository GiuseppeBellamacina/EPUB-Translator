from sqlalchemy import select

from app.core import bootstrap
from app.core.bootstrap import load_keys, resolve_providers
from app.core.encryption import decrypt_api_key
from app.db.database import async_session
from app.db.models import ProviderConfig

CONFIG = """
providers:
  - {name: router, type: custom, base_url: https://x/api, api_key_env: OPENROUTER_API_KEY,
     default_model: m:free, params: {structured_output_method: json_mode}}
  - {name: anthro, type: anthropic, api_key_env: ANTHROPIC_API_KEY}
  - {name: fake, type: fake}
"""


def test_load_keys_normalizes_hyphenated_names(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("OPENAI-API-KEY=sk-1\nopenrouter-api-key=or-1\nEMPTY=\n")
    keys = load_keys(env)
    assert keys["OPENAI_API_KEY"] == "sk-1"
    assert keys["OPENROUTER_API_KEY"] == "or-1"
    assert "EMPTY" not in keys


def test_missing_key_skips_provider():
    import yaml

    specs = resolve_providers(yaml.safe_load(CONFIG), {"OPENROUTER_API_KEY": "or-1"})
    assert [s["name"] for s in specs] == ["router", "fake"]


def test_defaults_without_providers_section():
    specs = resolve_providers({}, {"OPENAI_API_KEY": "sk"})
    assert [(s["name"], s["type"]) for s in specs] == [("openai", "openai")]


async def test_bootstrap_upserts_and_updates_key(db, tmp_path, monkeypatch):
    env, config = tmp_path / ".env", tmp_path / "config.yaml"
    config.write_text(CONFIG)
    monkeypatch.setattr(bootstrap.settings, "config_file", config)
    monkeypatch.setattr(bootstrap.settings, "env_file", env)

    for key in ("or-1", "or-2"):
        env.write_text(f"OPENROUTER-API-KEY={key}\n")
        async with async_session() as s:
            assert await bootstrap.bootstrap_providers(s) == ["router", "fake"]

    async with async_session() as s:
        rows = {p.name: p for p in (await s.execute(select(ProviderConfig))).scalars()}
    assert set(rows) == {"router", "fake"}
    assert decrypt_api_key(rows["router"].api_key_encrypted) == "or-2"
    assert rows["router"].params == {"structured_output_method": "json_mode"}
    assert rows["fake"].api_key_encrypted is None


async def test_bootstrap_never_takes_over_user_providers(db, tmp_path, monkeypatch):
    env, config = tmp_path / ".env", tmp_path / "config.yaml"
    config.write_text(CONFIG)
    env.write_text("OPENROUTER-API-KEY=or-1\n")
    monkeypatch.setattr(bootstrap.settings, "config_file", config)
    monkeypatch.setattr(bootstrap.settings, "env_file", env)
    async with async_session() as s:
        s.add(ProviderConfig(name="router", provider_type="openai", source="user"))
        await s.commit()
        assert await bootstrap.bootstrap_providers(s) == ["fake"]
    async with async_session() as s:
        rows = {p.name: p for p in (await s.execute(select(ProviderConfig))).scalars()}
    assert rows["router"].provider_type == "openai" and rows["router"].source == "user"
    assert rows["fake"].source == "config"


def test_update_provider_keeps_key_unless_given(db):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        created = client.post(
            "/api/providers", json={"name": "p", "provider_type": "openai", "api_key": "sk-1"}
        ).json()
        assert created["source"] == "user"
        url = f"/api/providers/{created['id']}"
        updated = client.put(url, json={"default_model": "gpt-4.1-mini"}).json()
        assert updated["default_model"] == "gpt-4.1-mini" and updated["name"] == "p"
        assert client.put(url, json={"name": "q"}).status_code == 200
        assert client.put("/api/providers/999", json={"name": "x"}).status_code == 404

    import asyncio

    async def key():
        async with async_session() as s:
            return (await s.get(ProviderConfig, created["id"])).api_key_encrypted

    assert decrypt_api_key(asyncio.run(key())) == "sk-1"


async def test_renamed_entries_keep_their_row_and_removed_ones_are_deactivated(
    db, tmp_path, monkeypatch
):
    env, config = tmp_path / ".env", tmp_path / "config.yaml"
    env.write_text("OPENROUTER-API-KEY=or-1\n")
    monkeypatch.setattr(bootstrap.settings, "config_file", config)
    monkeypatch.setattr(bootstrap.settings, "env_file", env)
    config.write_text(CONFIG)
    async with async_session() as s:
        await bootstrap.bootstrap_providers(s)
        router_id = (
            await s.execute(select(ProviderConfig.id).where(ProviderConfig.name == "router"))
        ).scalar_one()

    config.write_text(
        CONFIG.replace("name: router", "name: OpenRouter").replace(
            "  - {name: fake, type: fake}\n", ""
        )
    )
    async with async_session() as s:
        assert await bootstrap.bootstrap_providers(s) == ["OpenRouter"]
    async with async_session() as s:
        rows = {p.name: p for p in (await s.execute(select(ProviderConfig))).scalars()}
    assert set(rows) == {"OpenRouter", "fake"}
    assert rows["OpenRouter"].id == router_id and rows["OpenRouter"].is_active
    assert decrypt_api_key(rows["OpenRouter"].api_key_encrypted) == "or-1"
    assert rows["fake"].is_active is False


async def test_openrouter_custom_rows_become_their_own_type(db, tmp_path, monkeypatch):
    from app.core.llm_factory import LLMConfig, create_llm

    monkeypatch.setattr(bootstrap.settings, "config_file", tmp_path / "none.yaml")
    monkeypatch.setattr(bootstrap.settings, "env_file", tmp_path / "none.env")
    async with async_session() as s:
        s.add(
            ProviderConfig(
                name="mine",
                provider_type="custom",
                base_url="https://openrouter.ai/api/v1",
                source="user",
            )
        )
        await s.commit()
        await bootstrap.bootstrap_providers(s)
    async with async_session() as s:
        row = (await s.execute(select(ProviderConfig))).scalar_one()
    assert (row.provider_type, row.base_url) == ("openrouter", None)
    llm = create_llm(LLMConfig(provider="openrouter", model="x/y:free", api_key="k"))
    assert str(llm.openai_api_base) == "https://openrouter.ai/api/v1"


def test_provider_params_are_validated_and_stored(db):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        bad = {"name": "p", "provider_type": "fake", "params": {"max_concurrency": 0}}
        assert client.post("/api/providers", json=bad).status_code == 422
        created = client.post(
            "/api/providers",
            json={"name": "p", "provider_type": "fake", "params": {"requests_per_second": 1}},
        ).json()
        params = {"max_concurrency": 4, "max_retries": 2, "structured_output_method": "json_mode"}
        updated = client.put(f"/api/providers/{created['id']}", json={"params": params}).json()
        assert updated["params"] == params  # replaced as a whole; unset fields dropped
