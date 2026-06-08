"""Tests for the in-memory runtime config + MCP config() tool."""

from __future__ import annotations

import pytest

from squackit import runtime as rt
from squackit.runtime import (
    SquackitRuntimeConfig,
    get_runtime,
    reset_runtime,
    resolve_scope_path,
    update_runtime,
)


@pytest.fixture(autouse=True)
def _isolate_runtime():
    """Reset the module singleton + seed between tests so order doesn't matter."""
    rt._runtime = SquackitRuntimeConfig()
    rt._seed = SquackitRuntimeConfig()
    yield
    rt._runtime = SquackitRuntimeConfig()
    rt._seed = SquackitRuntimeConfig()


class TestFromEnv:
    def test_empty_env_returns_defaults(self):
        cfg = SquackitRuntimeConfig.from_env(env={})
        assert cfg.active_root is None
        assert cfg.log_level == "info"
        assert cfg.max_results_default == 50
        assert cfg.complexity_max_results_default == 20
        assert cfg.fts_cache_size == 8

    def test_active_root_from_env(self):
        cfg = SquackitRuntimeConfig.from_env(env={"SQUACKIT_ACTIVE_ROOT": "/tmp/repo"})
        assert cfg.active_root == "/tmp/repo"

    def test_log_level_normalized_lowercase(self):
        cfg = SquackitRuntimeConfig.from_env(env={"SQUACKIT_LOG_LEVEL": "DEBUG"})
        assert cfg.log_level == "debug"

    def test_log_level_invalid_falls_back_to_default(self):
        cfg = SquackitRuntimeConfig.from_env(env={"SQUACKIT_LOG_LEVEL": "verbose"})
        assert cfg.log_level == "info"

    def test_int_field_from_env(self):
        cfg = SquackitRuntimeConfig.from_env(env={"SQUACKIT_MAX_RESULTS_DEFAULT": "100"})
        assert cfg.max_results_default == 100

    def test_int_field_invalid_falls_back(self):
        cfg = SquackitRuntimeConfig.from_env(env={"SQUACKIT_MAX_RESULTS_DEFAULT": "abc"})
        assert cfg.max_results_default == 50

    def test_int_field_zero_clamped_to_one(self):
        cfg = SquackitRuntimeConfig.from_env(env={"SQUACKIT_FTS_CACHE_SIZE": "0"})
        assert cfg.fts_cache_size == 1


class TestUpdateRuntime:
    def test_set_active_root_persists_in_singleton(self):
        update_runtime({"active_root": "/tmp/x"})
        assert get_runtime().active_root == "/tmp/x"

    def test_unknown_key_raises_and_leaves_unchanged(self):
        original = get_runtime().to_dict()
        with pytest.raises(ValueError, match="unknown config key"):
            update_runtime({"bogus": "value"})
        assert get_runtime().to_dict() == original

    def test_invalid_value_raises_and_leaves_unchanged(self):
        original = get_runtime().to_dict()
        with pytest.raises(ValueError, match="log_level"):
            update_runtime({"log_level": "verbose"})
        assert get_runtime().to_dict() == original

    def test_atomic_batch_set_either_all_or_none(self):
        original = get_runtime().to_dict()
        with pytest.raises(ValueError):
            update_runtime({"active_root": "/tmp/y", "log_level": "verbose"})
        # active_root should NOT have been applied even though it's valid
        assert get_runtime().to_dict() == original

    def test_int_field_rejects_string(self):
        with pytest.raises(ValueError, match="max_results_default"):
            update_runtime({"max_results_default": "50"})

    def test_int_field_rejects_bool(self):
        # bool is an int subclass in Python — must reject explicitly
        with pytest.raises(ValueError, match="max_results_default"):
            update_runtime({"max_results_default": True})

    def test_int_field_rejects_zero_or_negative(self):
        with pytest.raises(ValueError, match="fts_cache_size"):
            update_runtime({"fts_cache_size": 0})
        with pytest.raises(ValueError, match="fts_cache_size"):
            update_runtime({"fts_cache_size": -1})


class TestResetRuntime:
    def test_reset_reverts_to_seed(self, monkeypatch):
        # Simulate launch-time env seed
        monkeypatch.setenv("SQUACKIT_ACTIVE_ROOT", "/tmp/seeded")
        rt._seed = SquackitRuntimeConfig.from_env()
        rt._runtime = SquackitRuntimeConfig.from_env()
        # Override at runtime
        update_runtime({"active_root": "/tmp/overridden"})
        assert get_runtime().active_root == "/tmp/overridden"
        # Reset goes back to seed (not dataclass defaults)
        reset_runtime()
        assert get_runtime().active_root == "/tmp/seeded"

    def test_reset_with_no_env_goes_to_defaults(self):
        update_runtime({"active_root": "/tmp/x", "max_results_default": 200})
        reset_runtime()
        assert get_runtime().active_root is None
        assert get_runtime().max_results_default == 50


class TestResolveScopePath:
    """Precedence: explicit -> runtime.active_root -> os.getcwd()."""

    def test_explicit_wins(self, monkeypatch):
        update_runtime({"active_root": "/tmp/runtime"})
        monkeypatch.chdir("/tmp")
        assert resolve_scope_path("/tmp/explicit") == "/tmp/explicit"

    def test_runtime_active_root_used_when_explicit_none(self, monkeypatch):
        update_runtime({"active_root": "/tmp/runtime"})
        monkeypatch.chdir("/tmp")
        assert resolve_scope_path(None) == "/tmp/runtime"

    def test_cwd_used_when_both_none(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert resolve_scope_path(None) == str(tmp_path)


class TestConfigToolViaMCP:
    """Smoke tests for the registered MCP tool."""

    @pytest.fixture(scope="class")
    def mcp(self):
        pytest.importorskip("fastmcp")
        from conftest import PROJECT_ROOT
        from squackit.server import create_server
        return create_server(root=PROJECT_ROOT, init=False)

    def test_config_is_registered(self, mcp):
        import asyncio
        async def _list():
            from fastmcp import Client
            async with Client(mcp) as client:
                tools = await client.list_tools()
                return [t.name for t in tools]
        loop = asyncio.new_event_loop()
        try:
            names = loop.run_until_complete(_list())
        finally:
            loop.close()
        assert "config" in names

    def test_config_returns_current_state(self, mcp):
        import asyncio
        async def _call():
            return await mcp.call_tool("config", {})
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(_call())
        finally:
            loop.close()
        # FastMCP wraps the dict in result.content[0].text as JSON
        text = result.content[0].text if hasattr(result, "content") else str(result)
        assert "active_root" in text
        assert "max_results_default" in text
