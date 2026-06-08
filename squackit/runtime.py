"""In-memory runtime configuration for the squackit MCP server.

Distinct from ProjectDefaults (which is inferred-at-startup + file-loaded
overrides from .fledgling-python/config.toml). This module holds *session*
state that the MCP `config()` tool reads and writes — wiped on server
restart, no disk persistence.

Env vars at launch seed the initial values (e.g. SQUACKIT_ACTIVE_ROOT set
in .mcp.json env block). Resetting reverts to those env-seeded values, not
hardcoded defaults.

Shape mirrors jetsam.config.runtime; see retritis bench/config-endpoint-plan.md
for the cross-suite design.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields, replace
from typing import Any


_ENV_PREFIX = "SQUACKIT_"

_VALID_LOG_LEVELS = {"debug", "info", "warn", "warning", "error"}


@dataclass
class SquackitRuntimeConfig:
    """Session-scoped runtime knobs for the squackit MCP server.

    Common keys (suite-wide convention, also on jetsam):
        active_root: fallback when a tool's `path=`/`root=` arg is omitted.
            None means use the server's process cwd (today's behavior).
        log_level: debug | info | warn | error.

    Squackit-specific:
        max_results_default: default cap for token-aware result truncation
            when tools don't get an explicit max_results.
        complexity_max_results_default: separate cap for `complexity` tool,
            which is usually requested in smaller batches.
        fts_cache_size: LRU size for per-root FTS indexes. Larger = more
            roots cached cheaply; smaller = less RAM but more rebuilds.
            Note: takes effect on NEW roots; existing cache entries keep
            their slot until they age out naturally.
    """

    active_root: str | None = None
    log_level: str = "info"
    max_results_default: int = 50
    complexity_max_results_default: int = 20
    fts_cache_size: int = 8

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "SquackitRuntimeConfig":
        """Build a config seeded from environment variables.

        Variables read (each optional):
            SQUACKIT_ACTIVE_ROOT
            SQUACKIT_LOG_LEVEL
            SQUACKIT_MAX_RESULTS_DEFAULT
            SQUACKIT_COMPLEXITY_MAX_RESULTS_DEFAULT
            SQUACKIT_FTS_CACHE_SIZE

        Invalid values fall back to the dataclass default.
        """
        e = env if env is not None else os.environ
        cfg = cls()

        if v := e.get(f"{_ENV_PREFIX}ACTIVE_ROOT"):
            cfg.active_root = v
        if v := e.get(f"{_ENV_PREFIX}LOG_LEVEL"):
            if v.lower() in _VALID_LOG_LEVELS:
                cfg.log_level = v.lower()
        if v := e.get(f"{_ENV_PREFIX}MAX_RESULTS_DEFAULT"):
            try:
                cfg.max_results_default = max(1, int(v))
            except ValueError:
                pass
        if v := e.get(f"{_ENV_PREFIX}COMPLEXITY_MAX_RESULTS_DEFAULT"):
            try:
                cfg.complexity_max_results_default = max(1, int(v))
            except ValueError:
                pass
        if v := e.get(f"{_ENV_PREFIX}FTS_CACHE_SIZE"):
            try:
                cfg.fts_cache_size = max(1, int(v))
            except ValueError:
                pass

        return cfg

    def to_dict(self) -> dict[str, Any]:
        """Flat dict for the MCP `config()` response."""
        return {f.name: getattr(self, f.name) for f in fields(self)}


# Module-level singleton, seeded from env on import.
_runtime: SquackitRuntimeConfig = SquackitRuntimeConfig.from_env()
_seed: SquackitRuntimeConfig = replace(_runtime)


def get_runtime() -> SquackitRuntimeConfig:
    """Return the current runtime config."""
    return _runtime


def update_runtime(values: dict[str, Any]) -> SquackitRuntimeConfig:
    """Merge values into the runtime config. Validates atomically.

    Raises ValueError on unknown keys or invalid values, leaving the runtime
    config unchanged.
    """
    global _runtime
    valid_keys = {f.name for f in fields(SquackitRuntimeConfig)}
    unknown = set(values) - valid_keys
    if unknown:
        raise ValueError(
            f"unknown config key(s): {sorted(unknown)}. "
            f"Valid keys: {sorted(valid_keys)}"
        )

    candidate = replace(_runtime)
    for key, value in values.items():
        _validate_one(key, value)
        setattr(candidate, key, value)

    _runtime = candidate
    return _runtime


def reset_runtime() -> SquackitRuntimeConfig:
    """Reset to the env-seeded values captured at module import time."""
    global _runtime
    _runtime = replace(_seed)
    return _runtime


def resolve_scope_path(explicit_path: str | None = None) -> str:
    """Resolve a scope path with the runtime config fallback chain.

    Precedence: explicit_path -> runtime.active_root -> process cwd.
    Used by tools that scope queries to a directory (investigate, etc.)
    so a single `config(set={"active_root": X})` call configures the whole
    session.
    """
    if explicit_path is not None:
        return explicit_path
    runtime_root = _runtime.active_root
    if runtime_root is not None:
        return runtime_root
    return os.getcwd()


def _validate_one(key: str, value: Any) -> None:
    """Per-key value validation."""
    if key == "log_level":
        if not isinstance(value, str) or value.lower() not in _VALID_LOG_LEVELS:
            raise ValueError(
                f"log_level must be one of {sorted(_VALID_LOG_LEVELS)}, got {value!r}"
            )
    elif key in ("max_results_default", "complexity_max_results_default", "fts_cache_size"):
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(f"{key} must be a positive int, got {value!r}")
    elif key == "active_root":
        if value is not None and not isinstance(value, str):
            raise ValueError(f"active_root must be str or None, got {type(value).__name__}")
