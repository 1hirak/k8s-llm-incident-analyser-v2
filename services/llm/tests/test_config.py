"""Tests for the runtime LLM config store and /config endpoints."""

import json
import os
import stat
from unittest.mock import patch

import pytest
from app.config_store import LLMConfigStore
from app.llm import get_provider
from app.llm.openai_provider import OpenAIProvider
from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


@pytest.fixture
def config_path(tmp_path) -> str:
    return str(tmp_path / "llm-config.json")


@pytest.fixture
def store(config_path) -> LLMConfigStore:
    return LLMConfigStore(config_path)


@pytest.fixture
def env_config(config_path):
    """Point LLM_CONFIG_PATH at an isolated temp file for this test."""
    patcher = patch.dict(
        os.environ, {"LLM_CONFIG_PATH": config_path}, clear=False
    )
    patcher.start()
    yield
    patcher.stop()


class TestLLMConfigStore:
    def test_read_missing_file_returns_empty(self, store):
        assert store._read() == {}

    def test_write_and_read_roundtrip(self, store):
        store.set_config(provider="openai", api_key="sk-secret", model="gpt-4o")
        data = store._read()
        assert data["provider"] == "openai"
        assert data["model"] == "gpt-4o"
        assert data["api_keys"]["openai"] == "sk-secret"

    def test_file_permissions_are_0600(self, store):
        store.set_config(provider="deepseek", api_key="dk-secret")
        mode = stat.S_IMODE(os.stat(store.path).st_mode)
        assert mode & 0o777 == 0o600

    def test_set_config_unknown_provider_raises(self, store):
        with pytest.raises(ValueError):
            store.set_config(provider="nope")

    def test_clear_key_removes_stored_key(self, store):
        store.set_config(provider="openai", api_key="sk-secret")
        assert store.is_available("openai") is True
        store.set_config(provider="openai", clear_key=True)
        assert store.is_available("openai") is False
        assert "openai" not in store._read().get("api_keys", {})

    def test_model_override_can_be_deleted(self, store):
        store.set_config(provider="openai", model="gpt-4o")
        assert store.resolve_model("openai") == "gpt-4o"
        store.set_config(provider="openai", model=None)
        assert store.resolve_model("openai") == "gpt-4o-mini"

    def test_file_key_takes_precedence_over_env(self, store):
        store.set_config(provider="openai", api_key="from-file")
        with patch.dict(
            os.environ, {"OPENAI_API_KEY": "from-env"}, clear=False
        ):
            provider, _, key = store.resolve_provider()
        assert provider == "openai"
        assert key == "from-file"

    def test_env_fallback_when_no_file(self, store):
        with patch.dict(
            os.environ,
            {"LLM_PROVIDER": "deepseek", "DEEPSEEK_API_KEY": "from-env"},
            clear=True,
        ):
            provider, _, key = store.resolve_provider()
        assert provider == "deepseek"
        assert key == "from-env"

    def test_availability_uses_file_or_env(self, store):
        store.set_config(provider="anthropic", api_key="ant-key")
        assert store.is_available("anthropic") is True
        assert store.is_available("openai") is False
        assert store.is_available("mock") is True


class TestGetConfigEndpoint:
    def test_get_config_defaults_to_env(self, config_path):
        with patch.dict(
            os.environ,
            {
                "LLM_CONFIG_PATH": config_path,
                "LLM_PROVIDER": "mock",
                "LLM_MODEL": "gpt-4o",
            },
            clear=True,
        ):
            resp = client.get("/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "mock"
        assert data["model"] == "gpt-4o"
        assert data["source"] == "env"
        ids = {p["id"] for p in data["providers"]}
        assert ids == {"mock", "openai", "anthropic", "deepseek", "openrouter"}

    def test_get_config_never_contains_key_values(self, env_config):
        resp = client.get("/config")
        assert resp.status_code == 200
        raw = json.dumps(resp.json())
        assert "api_key" not in raw.lower()
        assert "sk-" not in raw


class TestSetConfigEndpoint:
    def _env(self, config_path, **overrides) -> dict:
        """Environment for endpoint tests: isolated config path + cleared keys."""
        env = {"LLM_CONFIG_PATH": config_path}
        env.update(overrides)
        return env

    def test_set_provider_and_key(self, config_path):
        with patch.dict(os.environ, self._env(config_path), clear=True):
            resp = client.post(
                "/config",
                json={"provider": "openai", "api_key": "sk-secret"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "openai"
        assert data["source"] == "file"
        openai_item = next(
            p for p in data["providers"] if p["id"] == "openai"
        )
        assert openai_item["available"] is True
        assert "sk-secret" not in json.dumps(data)

    def test_set_model_override(self, config_path):
        with patch.dict(os.environ, self._env(config_path), clear=True):
            resp = client.post(
                "/config", json={"provider": "openai", "model": "gpt-4o"}
            )
        assert resp.json()["model"] == "gpt-4o"
        with patch.dict(os.environ, self._env(config_path), clear=True):
            resp = client.post("/config", json={"provider": "openai"})
        assert resp.json()["model"] == "gpt-4o"
        with patch.dict(os.environ, self._env(config_path), clear=True):
            resp = client.post(
                "/config", json={"provider": "openai", "model": None}
            )
        assert resp.json()["model"] is None

    def test_clear_key(self, config_path):
        with patch.dict(os.environ, self._env(config_path), clear=True):
            client.post(
                "/config",
                json={"provider": "deepseek", "api_key": "dk-secret"},
            )
        with patch.dict(os.environ, self._env(config_path), clear=True):
            resp = client.post(
                "/config",
                json={"provider": "deepseek", "clear_key": True},
            )
        data = resp.json()
        deepseek_item = next(
            p for p in data["providers"] if p["id"] == "deepseek"
        )
        assert deepseek_item["available"] is False

    def test_unknown_provider_returns_400(self, config_path):
        with patch.dict(os.environ, self._env(config_path), clear=True):
            resp = client.post("/config", json={"provider": "nope"})
        assert resp.status_code == 400


class TestGetProviderFromFile:
    def test_get_provider_uses_file_key(self, config_path):
        store = LLMConfigStore(config_path)
        store.set_config(provider="openai", api_key="sk-file-key")
        with patch.dict(
            os.environ,
            {"LLM_CONFIG_PATH": config_path, "OPENAI_API_KEY": "sk-env-key"},
            clear=False,
        ):
            provider = get_provider()
        assert isinstance(provider, OpenAIProvider)
        assert provider.api_key == "sk-file-key"
