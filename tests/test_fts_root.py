"""Per-root FTS index (opt-in `root` on the search_* tools).

An FTS tool can full-text-search a repository other than the server's own project by
passing ``root=<dir>``: squackit builds & caches a connection-per-root and runs the macro
there. These tests cover the safety-critical bits — root validation and the build/cache/LRU
behavior — without standing up a FastMCP server (the end-to-end path is exercised in
manual/handshake testing)."""
import pytest

from squackit.server import _FTS_CACHE_MAX, _fts_con_for_root, _resolve_fts_root


class _Stub:
    """Stands in for the FastMCP instance — only needs to hold `_fts_servers`."""


def _write_repo(d):
    (d / "mod.py").write_text(
        'def find_widgets():\n'
        '    """Locate widgets in the warehouse."""\n'
        '    return ["acme-widget"]\n'
    )
    # A markdown file so the FTS build has docs to index (mirrors a real repo).
    (d / "README.md").write_text("# Widgets\n\nThis project finds widgets.\n")
    return d


def test_resolve_root_rejects_glob():
    with pytest.raises(ValueError):
        _resolve_fts_root("/tmp/foo/**/*.py")


def test_resolve_root_rejects_missing(tmp_path):
    with pytest.raises(ValueError):
        _resolve_fts_root(str(tmp_path / "does-not-exist"))


def test_resolve_root_accepts_directory(tmp_path):
    assert _resolve_fts_root(str(tmp_path)) == tmp_path.resolve()


def test_per_root_build_search_and_cache(tmp_path):
    repo = _write_repo(tmp_path)
    mcp = _Stub()
    con = _fts_con_for_root(mcp, str(repo))
    rows = con.search_code(query="widgets").fetchall()
    assert rows, "FTS index should find 'widgets' (definition name + docstring)"
    # Same root reuses the cached connection (no rebuild).
    assert _fts_con_for_root(mcp, str(repo)) is con
    assert len(mcp._fts_servers) == 1


def test_cache_is_lru_bounded(tmp_path):
    mcp = _Stub()
    for i in range(_FTS_CACHE_MAX + 2):
        d = tmp_path / f"repo{i}"
        d.mkdir()
        _write_repo(d)
        _fts_con_for_root(mcp, str(d))
    assert len(mcp._fts_servers) == _FTS_CACHE_MAX
