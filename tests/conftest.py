"""Shared fixtures for squawkit tests.

Tests dog-food against the fledgling repo (same pattern as fledgling's own
test suite). Set FLEDGLING_REPO_PATH to override the auto-discovered path.
"""

import os


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
