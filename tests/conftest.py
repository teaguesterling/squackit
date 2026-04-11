"""Shared fixtures for squawkit tests.

Tests dog-food against the fledgling repo (same pattern as fledgling's own
test suite). Set FLEDGLING_REPO_PATH to override the auto-discovered path.
"""

import os
import pytest
import duckdb


def _discover_fledgling_repo() -> str:
    override = os.environ.get("FLEDGLING_REPO_PATH")
    if override:
        return override
    import fledgling
    pkg_dir = os.path.dirname(os.path.abspath(fledgling.__file__))
    repo_guess = os.path.dirname(pkg_dir)
    marker = os.path.join(repo_guess, "sql", "sandbox.sql")
    if os.path.exists(marker):
        return repo_guess
    raise RuntimeError(
        "squawkit tests require the fledgling repo for test data. "
        "Set FLEDGLING_REPO_PATH or install fledgling-mcp in editable mode."
    )


PROJECT_ROOT = _discover_fledgling_repo()
SQL_DIR = os.path.join(PROJECT_ROOT, "sql")
CLAUDE_PROJECTS_DIR = os.path.expanduser("~/.claude/projects")

SPEC_PATH = os.path.join(PROJECT_ROOT, "docs/vision/PRODUCT_SPEC.md")
ANALYSIS_PATH = os.path.join(PROJECT_ROOT, "docs/vision/CONVERSATION_ANALYSIS.md")
CONFTEST_PATH = os.path.join(PROJECT_ROOT, "tests/conftest.py")
SKILL_PATH = os.path.join(PROJECT_ROOT, "SKILL.md")
REPO_PATH = PROJECT_ROOT


def load_sql(con, filename):
    """Load a SQL macro file into a DuckDB connection."""
    path = os.path.join(SQL_DIR, filename)
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
    con.execute(f"SET VARIABLE _help_path = '{SKILL_PATH}'")


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
