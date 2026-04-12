"""Shared fixtures for squackit tests.

Tests dog-food against fledgling's SQL macros and data files. Discovery
order for the fledgling root:

1. ``FLEDGLING_REPO_PATH`` env var (explicit override)
2. Repo layout — the parent of ``fledgling.__file__``'s directory, if it
   contains ``sql/sandbox.sql``. Matches a source checkout or editable
   install where the package is a subdir of a repo.
3. Installed-package layout — the fledgling package directory itself, if
   it bundles ``sql/sandbox.sql`` as package data. Matches a wheel install.

Path constants (``PROJECT_ROOT``, ``SQL_DIR``, etc.) are resolved lazily
via module ``__getattr__`` so tests that don't touch them (e.g. the
import-only smoke tests) don't pay the discovery cost.
"""

import os
import pytest
import duckdb


CLAUDE_PROJECTS_DIR = os.path.expanduser("~/.claude/projects")

_discovered_root = None


def _discover_fledgling_repo() -> str:
    override = os.environ.get("FLEDGLING_REPO_PATH")
    if override:
        return override
    import fledgling
    pkg_dir = os.path.dirname(os.path.abspath(fledgling.__file__))
    repo_guess = os.path.dirname(pkg_dir)
    if os.path.exists(os.path.join(repo_guess, "sql", "sandbox.sql")):
        return repo_guess
    if os.path.exists(os.path.join(pkg_dir, "sql", "sandbox.sql")):
        return pkg_dir
    raise RuntimeError(
        "squackit tests require fledgling SQL macros. Set "
        "FLEDGLING_REPO_PATH, or install a fledgling distribution that "
        "bundles sql/ (either as a sibling of the package or inside it)."
    )


def _get_project_root() -> str:
    global _discovered_root
    if _discovered_root is None:
        _discovered_root = _discover_fledgling_repo()
    return _discovered_root


_LAZY_PATHS = {
    "PROJECT_ROOT": lambda r: r,
    "REPO_PATH":    lambda r: r,
    "SQL_DIR":      lambda r: os.path.join(r, "sql"),
    "SPEC_PATH":    lambda r: os.path.join(r, "docs/vision/PRODUCT_SPEC.md"),
    "ANALYSIS_PATH": lambda r: os.path.join(r, "docs/vision/CONVERSATION_ANALYSIS.md"),
    "CONFTEST_PATH": lambda r: os.path.join(r, "tests/conftest.py"),
    "SKILL_PATH":   lambda r: os.path.join(r, "SKILL.md"),
}


def __getattr__(name):
    if name in _LAZY_PATHS:
        return _LAZY_PATHS[name](_get_project_root())
    raise AttributeError(f"module 'conftest' has no attribute {name!r}")


def load_sql(con, filename):
    """Load a SQL macro file into a DuckDB connection."""
    path = os.path.join(_get_project_root(), "sql", filename)
    with open(path) as f:
        sql = f.read()
    lines = [l for l in sql.split("\n") if not l.strip().startswith("--")]
    cleaned = "\n".join(lines)
    for stmt in cleaned.split(";"):
        stmt = stmt.strip()
        if stmt:
            con.execute(stmt + ";")


def materialize_help(con):
    """Set up help path for help.sql bootstrap."""
    skill_path = os.path.join(_get_project_root(), "SKILL.md")
    con.execute(f"SET VARIABLE _help_path = '{skill_path}'")


@pytest.fixture
def con():
    """Fresh in-memory DuckDB connection."""
    conn = duckdb.connect(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def all_macros(con):
    """Connection with ALL extensions and ALL macros loaded."""
    con.execute("LOAD read_lines")
    con.execute("LOAD sitting_duck")
    con.execute("LOAD markdown")
    con.execute("LOAD duck_tails")
    con.execute("SET VARIABLE fledgling_version = '0.6.2'")
    con.execute("SET VARIABLE fledgling_profile = 'test'")
    con.execute("SET VARIABLE fledgling_modules = ['source', 'code', 'docs', 'repo', 'structural']")
    load_sql(con, "dr_fledgling.sql")
    load_sql(con, "source.sql")
    load_sql(con, "code.sql")
    load_sql(con, "docs.sql")
    load_sql(con, "repo.sql")
    load_sql(con, "structural.sql")
    materialize_help(con)
    load_sql(con, "help.sql")
    return con
