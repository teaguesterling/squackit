# squackit Extraction — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract `fledgling/pro/` into a standalone `squackit` pip package with identical runtime behavior. Both packages coexist after this phase — `fledgling[pro]` is removed in a later plan.

**Architecture:** squackit is a verbatim migration of `fledgling/pro/` modules with imports rewritten (`fledgling.pro.X` → `squackit.X`). squackit depends on `fledgling-mcp>=0.6.2` at runtime; it still imports `fledgling` directly for `fledgling.connect()` and related APIs. Tests copied from `fledgling/tests/test_pro_*.py` with the same import rewrite. No behavioral changes, no new features, no refactoring. Phase 2 will land the new SQL macros and `fledgling-python` extraction; Phase 3 removes `fledgling/pro/`.

**Tech Stack:** Python 3.9+, hatchling build backend, pytest, duckdb, fastmcp, fledgling-mcp (runtime dep).

---

## Scope boundaries

**In scope:**
- Create `~/Projects/squackit/` as a new pip-installable package
- Copy every module from `fledgling/pro/` to `squackit/` with imports rewritten
- Copy every test from `fledgling/tests/test_pro_*.py` to `squackit/tests/` with imports rewritten
- `squackit` CLI entry point
- Self-contained test suite that dog-foods against the fledgling repo
- Initial git repo, initial commit, no tag

**Out of scope (future plans):**
- Removing `fledgling/pro/` from the fledgling repo (Phase 3)
- New SQL workflow macros in fledgling (Phase 2)
- `fledgling-python` extraction (Phase 2)
- Refactoring squackit to use pluckit (Phase 4)
- PyPI publication
- Access log persistence to disk (new feature, deferred)
- Kibitzer suggestion engine (new feature, deferred)

If a task reveals that verbatim migration is impossible for some module, stop and raise the issue — do not add refactoring to this plan.

---

## File structure

```
~/Projects/squackit/
├── .gitignore                   (new)
├── pyproject.toml               (new)
├── README.md                    (new)
├── CLAUDE.md                    (new, minimal stub)
├── squackit/
│   ├── __init__.py              (copy of fledgling/pro/__init__.py)
│   ├── __main__.py              (copy of fledgling/pro/__main__.py)
│   ├── db.py                    (copy of fledgling/pro/db.py)
│   ├── defaults.py              (copy of fledgling/pro/defaults.py)
│   ├── formatting.py            (copy of fledgling/pro/formatting.py)
│   ├── prompts.py               (copy of fledgling/pro/prompts.py)
│   ├── server.py                (copy of fledgling/pro/server.py)
│   ├── session.py               (copy of fledgling/pro/session.py)
│   └── workflows.py             (copy of fledgling/pro/workflows.py)
├── tests/
│   ├── conftest.py              (new — defines PROJECT_ROOT via fledgling discovery)
│   ├── test_defaults.py         (copy of fledgling/tests/test_pro_defaults.py)
│   ├── test_prompts.py          (copy of fledgling/tests/test_pro_prompts.py)
│   ├── test_resources.py        (copy of fledgling/tests/test_pro_resources.py)
│   ├── test_session.py          (copy of fledgling/tests/test_pro_session.py)
│   ├── test_truncation.py       (copy of fledgling/tests/test_pro_truncation.py)
│   └── test_workflows.py        (copy of fledgling/tests/test_pro_workflows.py)
└── docs/
    └── superpowers/
        ├── specs/
        │   └── 2026-04-10-squackit-design.md    (already exists)
        └── plans/
            └── 2026-04-10-squackit-extraction.md  (this file)
```

**Layout decision.** Flat package layout (`squackit/` at repo root), matching fledgling's convention. Not `src/squackit/`. This minimizes drift between fledgling's test files and squackit's copies.

---

## Migration dependency order

Modules are migrated in dependency order so each task's tests can run against only already-migrated modules. Derived from the `grep "^from\|^import"` scan of `fledgling/pro/*.py`:

```
formatting.py   — no internal deps (leaf)
session.py      — no internal deps (leaf)
defaults.py     — no internal deps (leaf)
db.py           — no internal deps (leaf; thin wrapper over fledgling.connect)
workflows.py    — depends on formatting
prompts.py      — depends on workflows
server.py       — depends on defaults, formatting, prompts, session, workflows
__main__.py     — depends on server
__init__.py     — no imports (version string only)
```

Task order follows this.

---

## Import rewrites — the universal sed pattern

Every `.py` file migrated needs the same transformation. The exact pattern:

| Old | New |
|---|---|
| `from fledgling.pro.defaults import X` | `from squackit.defaults import X` |
| `from fledgling.pro.formatting import X` | `from squackit.formatting import X` |
| `from fledgling.pro.prompts import X` | `from squackit.prompts import X` |
| `from fledgling.pro.session import X` | `from squackit.session import X` |
| `from fledgling.pro.workflows import X` | `from squackit.workflows import X` |
| `from fledgling.pro.server import X` | `from squackit.server import X` |
| `import fledgling.pro.X` | `import squackit.X` |
| `fledgling.pro.session.time.time` (in mock patch paths) | `squackit.session.time.time` |

**Imports that MUST remain unchanged** (squackit's runtime dependency on fledgling):

- `import fledgling`
- `from fledgling.connection import Connection`
- `from conftest import PROJECT_ROOT` (inside test files — squackit's conftest.py will define PROJECT_ROOT locally)

The sed one-liner used in each task (run from inside the squackit repo root):

```bash
sed -i 's|fledgling\.pro\.|squackit.|g; s|fledgling\.pro|squackit|g' <path>
```

The first substitution handles `fledgling.pro.X` (module path); the second catches any bare `fledgling.pro` reference (e.g., in docstrings or `__module__` comparisons). Order matters — the specific pattern must run first.

---

## Task 1: Scaffold the squackit package

**Files:**
- Create: `~/Projects/squackit/.gitignore`
- Create: `~/Projects/squackit/pyproject.toml`
- Create: `~/Projects/squackit/README.md`
- Create: `~/Projects/squackit/CLAUDE.md`
- Create: `~/Projects/squackit/squackit/__init__.py` (placeholder)

The `~/Projects/squackit/` directory already exists and contains `docs/superpowers/specs/` and `docs/superpowers/plans/` from the brainstorming phase. This task adds the package scaffolding around that existing docs tree without disturbing it.

- [ ] **Step 1: Initialize git repo**

Run:
```bash
cd ~/Projects/squackit && git init -b main && git status
```
Expected: `Initialized empty Git repository in ~/Projects/squackit/.git/` and untracked `docs/` directory.

- [ ] **Step 2: Create `.gitignore`**

Write `~/Projects/squackit/.gitignore` with:
```
__pycache__/
*.py[cod]
*.so
.pytest_cache/
.venv/
venv/
dist/
build/
*.egg-info/
.DS_Store
.squackit/
```

- [ ] **Step 3: Create `pyproject.toml`**

Write `~/Projects/squackit/pyproject.toml` with:
```toml
[project]
name = "squackit"
version = "0.1.0"
description = "Semi-QUalified Agent Companion Kit — the stateful intelligence + MCP server layer for fledgling-equipped agents."
readme = "README.md"
license = "Apache-2.0"
requires-python = ">=3.9"
authors = [
    { name = "Teague Sterling" },
]
keywords = ["mcp", "ai-agents", "code-intelligence", "fledgling", "duckdb"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "Topic :: Software Development :: Libraries :: Python Modules",
    "Programming Language :: Python :: 3",
    "License :: OSI Approved :: Apache Software License",
]
dependencies = [
    "fledgling-mcp>=0.6.2",
    "duckdb>=1.5.0",
    "fastmcp>=3.0",
]

[project.scripts]
squackit = "squackit.server:main"

[project.urls]
Repository = "https://github.com/teaguesterling/squackit"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["squackit"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]

[dependency-groups]
test = [
    "pytest>=7.0",
]
```

- [ ] **Step 4: Create `README.md`**

Write `~/Projects/squackit/README.md`:
```markdown
# squackit

**Semi-QUalified Agent Companion Kit.** The stateful intelligence + MCP server layer
for [fledgling](https://github.com/teaguesterling/fledgling)-equipped agents.

squackit wraps fledgling's SQL macros with smart defaults, token-aware output,
session caching, compound workflows, an MCP server, prompts, and resources. It is
the Python-side "cold-start agent support" layer — the features that don't belong
in fledgling's neutral SQL core.

## Status

**Phase 1 — extraction from fledgling/pro/.** Runtime behavior identical to
`fledgling-mcp[pro]`. Subsequent phases add new features, refactor to use pluckit,
and retire the `fledgling-mcp[pro]` extra.

See `docs/superpowers/specs/2026-04-10-squackit-design.md` for the full design.

## Install

```bash
pip install -e .
```

## Run

```bash
squackit
```

Starts the FastMCP server on stdio.
```

- [ ] **Step 5: Create `CLAUDE.md`** (minimal stub)

Write `~/Projects/squackit/CLAUDE.md`:
```markdown
# squackit: Project Conventions

## Phase 1 scope

squackit is currently a verbatim migration of `fledgling/pro/` with imports
rewritten. Do not refactor, do not add features, do not restructure. The design
spec in `docs/superpowers/specs/2026-04-10-squackit-design.md` describes the
target; Phase 1 only sets up the package boundary.

## Import rules

- `squackit.*` for internal imports
- `import fledgling` and `from fledgling.connection import Connection` — stay
  (squackit depends on fledgling at runtime)
- Tests use `from conftest import PROJECT_ROOT` — squackit's `conftest.py`
  defines `PROJECT_ROOT` via `fledgling` package discovery

## Tests

Run with:
```
pytest tests/
```

Tests dog-food against the fledgling repo. Set `FLEDGLING_REPO_PATH` to override
the auto-discovered path.
```

- [ ] **Step 6: Create placeholder package module**

Write `~/Projects/squackit/squackit/__init__.py`:
```python
"""squackit — Semi-QUalified Agent Companion Kit."""

__version__ = "0.1.0"
```

- [ ] **Step 7: Commit scaffolding**

Run:
```bash
cd ~/Projects/squackit && \
  git add .gitignore pyproject.toml README.md CLAUDE.md squackit/__init__.py && \
  git commit -m "feat: scaffold squackit package (Phase 1 - extraction)"
```

Expected: first commit in the new repo.

---

## Task 2: Install in dev mode and write smoke test

**Files:**
- Create: `~/Projects/squackit/tests/__init__.py`
- Create: `~/Projects/squackit/tests/test_smoke.py`

- [ ] **Step 1: Write the failing smoke test**

Write `~/Projects/squackit/tests/test_smoke.py`:
```python
"""Package smoke tests — imports only, no behavior."""


def test_import_squackit():
    import squackit
    assert squackit.__version__ == "0.1.0"


def test_fledgling_available():
    """squackit's runtime depends on fledgling — verify it's importable."""
    import fledgling
    assert hasattr(fledgling, "connect")
```

Write `~/Projects/squackit/tests/__init__.py` (empty file):
```python
```

- [ ] **Step 2: Run smoke test to verify it fails**

Run:
```bash
cd ~/Projects/squackit && pytest tests/test_smoke.py -v
```
Expected: FAIL or ERROR with `ModuleNotFoundError: No module named 'squackit'` (package not yet installed).

- [ ] **Step 3: Install in editable mode**

Run:
```bash
cd ~/Projects/squackit && pip install -e .
```
Expected: `Successfully installed squackit-0.1.0` and resolution of `fledgling-mcp>=0.6.2`, `duckdb>=1.5.0`, `fastmcp>=3.0`. If `fledgling-mcp` is not available on PyPI yet in the engineer's environment, install it first with `pip install -e /mnt/aux-data/teague/Projects/source-sextant/main` (the local fledgling repo).

- [ ] **Step 4: Run smoke test to verify it passes**

Run:
```bash
cd ~/Projects/squackit && pytest tests/test_smoke.py -v
```
Expected: PASS on both tests.

- [ ] **Step 5: Commit smoke test**

```bash
cd ~/Projects/squackit && \
  git add tests/__init__.py tests/test_smoke.py && \
  git commit -m "test: add package smoke tests"
```

---

## Task 3: Migrate `formatting.py` (leaf module)

**Files:**
- Create: `~/Projects/squackit/squackit/formatting.py` (from `fledgling/pro/formatting.py`)
- Create: `~/Projects/squackit/tests/test_truncation.py` (from `fledgling/tests/test_pro_truncation.py`)

`formatting.py` has no internal fledgling-pro imports — only stdlib. Its test file is `test_pro_truncation.py` which tests the truncation helpers. This is the simplest module to migrate.

- [ ] **Step 1: Copy the source file**

Run:
```bash
cp /mnt/aux-data/teague/Projects/source-sextant/main/fledgling/pro/formatting.py \
   ~/Projects/squackit/squackit/formatting.py
```

- [ ] **Step 2: Apply import rewrite**

Run:
```bash
sed -i 's|fledgling\.pro\.|squackit.|g; s|fledgling\.pro|squackit|g' \
    ~/Projects/squackit/squackit/formatting.py
```

- [ ] **Step 3: Verify no stale imports remain**

Run:
```bash
grep -n 'fledgling\.pro' ~/Projects/squackit/squackit/formatting.py
```
Expected: no output (zero matches). If matches appear, stop and investigate.

- [ ] **Step 4: Copy and rewrite the test file**

Run:
```bash
cp /mnt/aux-data/teague/Projects/source-sextant/main/tests/test_pro_truncation.py \
   ~/Projects/squackit/tests/test_truncation.py && \
sed -i 's|fledgling\.pro\.|squackit.|g; s|fledgling\.pro|squackit|g' \
    ~/Projects/squackit/tests/test_truncation.py
```

- [ ] **Step 5: Create a minimal `conftest.py` so the test file's `from conftest import PROJECT_ROOT` works**

Write `~/Projects/squackit/tests/conftest.py`:
```python
"""Shared fixtures for squackit tests.

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
        "squackit tests require the fledgling repo for test data. "
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
```

- [ ] **Step 6: Run the formatting/truncation tests**

Run:
```bash
cd ~/Projects/squackit && pytest tests/test_truncation.py -v
```
Expected: PASS on all tests that don't transitively require other unmigrated modules. If a test fails because it imports `squackit.server` (which doesn't exist yet), skip it with `pytest ... -k 'not server'` or allow it to ERROR — note which tests deferred until Task 8. Do **not** modify test code to work around missing modules.

If *all* tests error because of `squackit.server` import at module level, this task's verification is deferred: mark in the commit message "(full verification deferred until Task 8)" and continue. The import verification in Step 3 is still a hard pass requirement.

- [ ] **Step 7: Commit**

```bash
cd ~/Projects/squackit && \
  git add squackit/formatting.py tests/test_truncation.py tests/conftest.py && \
  git commit -m "feat: migrate formatting.py + test_truncation.py"
```

---

## Task 4: Migrate `session.py`

**Files:**
- Create: `~/Projects/squackit/squackit/session.py`
- Create: `~/Projects/squackit/tests/test_session.py`

`session.py` has no internal fledgling-pro imports. Its test file has function-level imports that the sed pattern will handle.

- [ ] **Step 1: Copy and rewrite the source file**

```bash
cp /mnt/aux-data/teague/Projects/source-sextant/main/fledgling/pro/session.py \
   ~/Projects/squackit/squackit/session.py && \
sed -i 's|fledgling\.pro\.|squackit.|g; s|fledgling\.pro|squackit|g' \
    ~/Projects/squackit/squackit/session.py
```

- [ ] **Step 2: Verify no stale imports**

```bash
grep -n 'fledgling\.pro' ~/Projects/squackit/squackit/session.py
```
Expected: no output.

- [ ] **Step 3: Copy and rewrite the test file**

```bash
cp /mnt/aux-data/teague/Projects/source-sextant/main/tests/test_pro_session.py \
   ~/Projects/squackit/tests/test_session.py && \
sed -i 's|fledgling\.pro\.|squackit.|g; s|fledgling\.pro|squackit|g' \
    ~/Projects/squackit/tests/test_session.py
```

- [ ] **Step 4: Verify test imports**

```bash
grep -n 'fledgling\.pro' ~/Projects/squackit/tests/test_session.py
```
Expected: no output.

- [ ] **Step 5: Run session-only tests (those that don't import server)**

```bash
cd ~/Projects/squackit && pytest tests/test_session.py -v -k 'not create_server and not resource'
```
Expected: tests that touch `squackit.session` pass. Tests that transitively require `squackit.server` (via function-level imports) will be re-run after Task 8.

- [ ] **Step 6: Commit**

```bash
cd ~/Projects/squackit && \
  git add squackit/session.py tests/test_session.py && \
  git commit -m "feat: migrate session.py + test_session.py"
```

---

## Task 5: Migrate `defaults.py`

**Files:**
- Create: `~/Projects/squackit/squackit/defaults.py`
- Create: `~/Projects/squackit/tests/test_defaults.py`

`defaults.py` imports `subprocess`, `tomllib`, and fledgling-neutral stdlib only. No internal fledgling-pro imports.

- [ ] **Step 1: Copy and rewrite the source file**

```bash
cp /mnt/aux-data/teague/Projects/source-sextant/main/fledgling/pro/defaults.py \
   ~/Projects/squackit/squackit/defaults.py && \
sed -i 's|fledgling\.pro\.|squackit.|g; s|fledgling\.pro|squackit|g' \
    ~/Projects/squackit/squackit/defaults.py
```

- [ ] **Step 2: Verify no stale imports**

```bash
grep -n 'fledgling\.pro' ~/Projects/squackit/squackit/defaults.py
```
Expected: no output.

- [ ] **Step 3: Copy and rewrite the test file**

```bash
cp /mnt/aux-data/teague/Projects/source-sextant/main/tests/test_pro_defaults.py \
   ~/Projects/squackit/tests/test_defaults.py && \
sed -i 's|fledgling\.pro\.|squackit.|g; s|fledgling\.pro|squackit|g' \
    ~/Projects/squackit/tests/test_defaults.py
```

- [ ] **Step 4: Verify test imports**

```bash
grep -n 'fledgling\.pro' ~/Projects/squackit/tests/test_defaults.py
```
Expected: no output.

- [ ] **Step 5: Run defaults-only tests**

```bash
cd ~/Projects/squackit && pytest tests/test_defaults.py -v -k 'not create_server'
```
Expected: dataclass, config, and inference tests pass. Tests that import `squackit.server` at function level will ERROR until Task 8.

- [ ] **Step 6: Commit**

```bash
cd ~/Projects/squackit && \
  git add squackit/defaults.py tests/test_defaults.py && \
  git commit -m "feat: migrate defaults.py + test_defaults.py"
```

---

## Task 6: Migrate `db.py`

**Files:**
- Create: `~/Projects/squackit/squackit/db.py`

`db.py` is a 15-line thin wrapper over `fledgling.connect()`. No internal deps, no dedicated test file. Included for completeness and to preserve the `squackit.db.create_connection(...)` API that `server.py` calls at module level.

- [ ] **Step 1: Copy and rewrite the source file**

```bash
cp /mnt/aux-data/teague/Projects/source-sextant/main/fledgling/pro/db.py \
   ~/Projects/squackit/squackit/db.py && \
sed -i 's|fledgling\.pro\.|squackit.|g; s|fledgling\.pro|squackit|g' \
    ~/Projects/squackit/squackit/db.py
```

- [ ] **Step 2: Verify the file still imports fledgling (not squackit)**

```bash
grep -n 'import fledgling' ~/Projects/squackit/squackit/db.py
```
Expected: 1 match — `import fledgling`. The sed pattern does not touch bare `fledgling` references.

- [ ] **Step 3: Verify no stale `fledgling.pro` references**

```bash
grep -n 'fledgling\.pro' ~/Projects/squackit/squackit/db.py
```
Expected: no output.

- [ ] **Step 4: Spot-check the wrapper still works**

Run:
```bash
cd ~/Projects/squackit && python -c "from squackit.db import create_connection; c = create_connection(); print(type(c).__name__)"
```
Expected: `Connection` (the fledgling proxy). If this fails, `fledgling.connect()` has a runtime issue unrelated to this migration — stop and investigate.

- [ ] **Step 5: Commit**

```bash
cd ~/Projects/squackit && \
  git add squackit/db.py && \
  git commit -m "feat: migrate db.py"
```

---

## Task 7: Migrate `workflows.py`

**Files:**
- Create: `~/Projects/squackit/squackit/workflows.py`
- Create: `~/Projects/squackit/tests/test_workflows.py`

`workflows.py` imports `from fledgling.pro.formatting import _format_markdown_table, _truncate_rows` — this is the first migration where the sed pattern rewrites a real internal import. `formatting.py` must already be migrated (Task 3).

- [ ] **Step 1: Copy and rewrite the source file**

```bash
cp /mnt/aux-data/teague/Projects/source-sextant/main/fledgling/pro/workflows.py \
   ~/Projects/squackit/squackit/workflows.py && \
sed -i 's|fledgling\.pro\.|squackit.|g; s|fledgling\.pro|squackit|g' \
    ~/Projects/squackit/squackit/workflows.py
```

- [ ] **Step 2: Verify the formatting import rewrote correctly**

```bash
grep -n 'from squackit.formatting' ~/Projects/squackit/squackit/workflows.py
```
Expected: 1 match: `from squackit.formatting import _format_markdown_table, _truncate_rows`

- [ ] **Step 3: Verify no stale `fledgling.pro` references**

```bash
grep -n 'fledgling\.pro' ~/Projects/squackit/squackit/workflows.py
```
Expected: no output.

- [ ] **Step 4: Verify the module imports cleanly**

```bash
cd ~/Projects/squackit && python -c "import squackit.workflows; print('ok')"
```
Expected: `ok`.

- [ ] **Step 5: Copy and rewrite the test file**

```bash
cp /mnt/aux-data/teague/Projects/source-sextant/main/tests/test_pro_workflows.py \
   ~/Projects/squackit/tests/test_workflows.py && \
sed -i 's|fledgling\.pro\.|squackit.|g; s|fledgling\.pro|squackit|g' \
    ~/Projects/squackit/tests/test_workflows.py
```

- [ ] **Step 6: Verify test imports**

```bash
grep -n 'fledgling\.pro' ~/Projects/squackit/tests/test_workflows.py
```
Expected: no output.

- [ ] **Step 7: Run workflow-only tests (skip server-dependent ones)**

```bash
cd ~/Projects/squackit && pytest tests/test_workflows.py -v -k 'not create_server'
```
Expected: helper-function tests (`_format_briefing`, `_section`, `_has_module`) pass. Integration tests that call `create_server` will ERROR until Task 8.

- [ ] **Step 8: Commit**

```bash
cd ~/Projects/squackit && \
  git add squackit/workflows.py tests/test_workflows.py && \
  git commit -m "feat: migrate workflows.py + test_workflows.py"
```

---

## Task 8: Migrate `prompts.py`

**Files:**
- Create: `~/Projects/squackit/squackit/prompts.py`
- Create: `~/Projects/squackit/tests/test_prompts.py`

`prompts.py` imports `from fledgling.pro.workflows import explore, investigate, review` — depends on `workflows.py` (Task 7).

- [ ] **Step 1: Copy and rewrite the source file**

```bash
cp /mnt/aux-data/teague/Projects/source-sextant/main/fledgling/pro/prompts.py \
   ~/Projects/squackit/squackit/prompts.py && \
sed -i 's|fledgling\.pro\.|squackit.|g; s|fledgling\.pro|squackit|g' \
    ~/Projects/squackit/squackit/prompts.py
```

- [ ] **Step 2: Verify the workflows import rewrote correctly**

```bash
grep -n 'from squackit.workflows' ~/Projects/squackit/squackit/prompts.py
```
Expected: 1 match: `from squackit.workflows import explore, investigate, review`

- [ ] **Step 3: Verify no stale references**

```bash
grep -n 'fledgling\.pro' ~/Projects/squackit/squackit/prompts.py
```
Expected: no output.

- [ ] **Step 4: Verify the module imports cleanly**

```bash
cd ~/Projects/squackit && python -c "import squackit.prompts; print('ok')"
```
Expected: `ok`.

- [ ] **Step 5: Copy and rewrite the test file**

```bash
cp /mnt/aux-data/teague/Projects/source-sextant/main/tests/test_pro_prompts.py \
   ~/Projects/squackit/tests/test_prompts.py && \
sed -i 's|fledgling\.pro\.|squackit.|g; s|fledgling\.pro|squackit|g' \
    ~/Projects/squackit/tests/test_prompts.py
```

- [ ] **Step 6: Verify test imports**

```bash
grep -n 'fledgling\.pro' ~/Projects/squackit/tests/test_prompts.py
```
Expected: no output.

- [ ] **Step 7: Run prompt tests that don't need the server**

```bash
cd ~/Projects/squackit && pytest tests/test_prompts.py -v -k 'not create_server'
```
Expected: pure prompt tests pass; integration tests deferred to Task 9.

- [ ] **Step 8: Commit**

```bash
cd ~/Projects/squackit && \
  git add squackit/prompts.py tests/test_prompts.py && \
  git commit -m "feat: migrate prompts.py + test_prompts.py"
```

---

## Task 9: Migrate `server.py` — the big one

**Files:**
- Create: `~/Projects/squackit/squackit/server.py`
- Create: `~/Projects/squackit/tests/test_resources.py`

`server.py` is 494 lines and imports from every other migrated module:
- `from fledgling.pro.defaults import (...)`  → `from squackit.defaults import (...)`
- `from fledgling.pro.formatting import (...)` → `from squackit.formatting import (...)`
- `from fledgling.pro.prompts import register_prompts` → `from squackit.prompts import register_prompts`
- `from fledgling.pro.session import AccessLog, SessionCache` → `from squackit.session import AccessLog, SessionCache`
- `from fledgling.pro.workflows import register_workflows` → `from squackit.workflows import register_workflows`

Also imports `import fledgling` and `from fledgling.connection import Connection` — both preserved (not touched by sed).

- [ ] **Step 1: Copy and rewrite the source file**

```bash
cp /mnt/aux-data/teague/Projects/source-sextant/main/fledgling/pro/server.py \
   ~/Projects/squackit/squackit/server.py && \
sed -i 's|fledgling\.pro\.|squackit.|g; s|fledgling\.pro|squackit|g' \
    ~/Projects/squackit/squackit/server.py
```

- [ ] **Step 2: Verify no stale `fledgling.pro` references**

```bash
grep -n 'fledgling\.pro' ~/Projects/squackit/squackit/server.py
```
Expected: no output.

- [ ] **Step 3: Verify `import fledgling` and `from fledgling.connection` are preserved**

```bash
grep -n '^import fledgling$\|^from fledgling\.connection' ~/Projects/squackit/squackit/server.py
```
Expected: two matches — `import fledgling` and `from fledgling.connection import Connection`.

- [ ] **Step 4: Verify the module imports cleanly**

```bash
cd ~/Projects/squackit && python -c "import squackit.server; print('ok')"
```
Expected: `ok`. If this fails with an `ImportError` naming a specific symbol, the sed pattern missed something — grep for `fledgling.pro` again and investigate.

- [ ] **Step 5: Verify `create_server` is callable**

```bash
cd ~/Projects/squackit && \
  FLEDGLING_REPO_PATH=/mnt/aux-data/teague/Projects/source-sextant/main \
  python -c "from squackit.server import create_server; s = create_server(root='/mnt/aux-data/teague/Projects/source-sextant/main'); print(type(s).__name__)"
```
Expected: `FastMCP` (or the FastMCP class name).

- [ ] **Step 6: Copy and rewrite `test_pro_resources.py` → `test_resources.py`**

```bash
cp /mnt/aux-data/teague/Projects/source-sextant/main/tests/test_pro_resources.py \
   ~/Projects/squackit/tests/test_resources.py && \
sed -i 's|fledgling\.pro\.|squackit.|g; s|fledgling\.pro|squackit|g' \
    ~/Projects/squackit/tests/test_resources.py
```

- [ ] **Step 7: Verify resource test imports**

```bash
grep -n 'fledgling\.pro' ~/Projects/squackit/tests/test_resources.py
```
Expected: no output.

- [ ] **Step 8: Run the full test suite for the first time**

```bash
cd ~/Projects/squackit && \
  FLEDGLING_REPO_PATH=/mnt/aux-data/teague/Projects/source-sextant/main \
  pytest tests/ -v
```
Expected: all tests pass. If any tests fail with `fledgling.pro` attribute errors, the sed pattern missed something — run `grep -rn 'fledgling\.pro' squackit/ tests/` to find stragglers. If tests fail for unrelated reasons, those are pre-existing issues — document them in a GitHub issue but do not attempt fixes in this plan.

- [ ] **Step 9: Commit**

```bash
cd ~/Projects/squackit && \
  git add squackit/server.py tests/test_resources.py && \
  git commit -m "feat: migrate server.py + test_resources.py (full suite passing)"
```

---

## Task 10: Migrate `__main__.py` and finalize `__init__.py`

**Files:**
- Modify: `~/Projects/squackit/squackit/__init__.py`
- Create: `~/Projects/squackit/squackit/__main__.py`

`__init__.py` currently has only the version placeholder from Task 1. It should match `fledgling/pro/__init__.py`'s content. `__main__.py` is 5 lines, enables `python -m squackit` as an alias for `squackit-server`.

- [ ] **Step 1: Overwrite `__init__.py` with the migrated version**

Write `~/Projects/squackit/squackit/__init__.py`:
```python
"""squackit: Semi-QUalified Agent Companion Kit — the stateful intelligence + MCP server layer for fledgling-equipped agents."""

__version__ = "0.1.0"
```
(This matches `fledgling/pro/__init__.py` except for name and version.)

- [ ] **Step 2: Copy and rewrite `__main__.py`**

```bash
cp /mnt/aux-data/teague/Projects/source-sextant/main/fledgling/pro/__main__.py \
   ~/Projects/squackit/squackit/__main__.py && \
sed -i 's|fledgling\.pro\.|squackit.|g; s|fledgling\.pro|squackit|g' \
    ~/Projects/squackit/squackit/__main__.py
```

- [ ] **Step 3: Verify `__main__.py` imports correctly**

```bash
grep -n 'from squackit\.server import main' ~/Projects/squackit/squackit/__main__.py
```
Expected: 1 match.

- [ ] **Step 4: Verify `python -m squackit` resolves the entry point**

```bash
cd ~/Projects/squackit && python -c "from squackit.__main__ import main; print('ok')" 2>&1 | head
```
Expected: `ok` (do NOT actually invoke `python -m squackit` — it would start an MCP server on stdio and hang the terminal).

- [ ] **Step 5: Commit**

```bash
cd ~/Projects/squackit && \
  git add squackit/__init__.py squackit/__main__.py && \
  git commit -m "feat: migrate __init__.py and __main__.py"
```

---

## Task 11: Entry point smoke test

**Files:**
- Modify: `~/Projects/squackit/tests/test_smoke.py`

Verify the `squackit` CLI entry point installed by `pyproject.toml`'s `[project.scripts]` is discoverable and importable without actually running the server.

- [ ] **Step 1: Extend the smoke test**

Edit `~/Projects/squackit/tests/test_smoke.py` to append:
```python


def test_entry_point_importable():
    """The `squackit` CLI entry point must resolve to a callable."""
    from squackit.server import main
    assert callable(main)


def test_cli_script_installed():
    """pyproject.toml's [project.scripts] should install a `squackit` script."""
    import shutil
    assert shutil.which("squackit") is not None, \
        "squackit CLI script not on PATH — re-run `pip install -e .`"
```

- [ ] **Step 2: Run the smoke tests**

```bash
cd ~/Projects/squackit && pytest tests/test_smoke.py -v
```
Expected: all four tests pass.

- [ ] **Step 3: Commit**

```bash
cd ~/Projects/squackit && \
  git add tests/test_smoke.py && \
  git commit -m "test: extend smoke tests with entry point verification"
```

---

## Task 12: Full suite verification + wheel build

**Files:** none modified

Final verification: full test suite runs green from a clean pytest cache, and the package builds a valid wheel.

- [ ] **Step 1: Clean pytest cache and run full suite**

```bash
cd ~/Projects/squackit && \
  rm -rf .pytest_cache && \
  FLEDGLING_REPO_PATH=/mnt/aux-data/teague/Projects/source-sextant/main \
  pytest tests/ -v 2>&1 | tail -40
```
Expected: all tests pass. Record the pass count in the final commit message.

- [ ] **Step 2: Build the wheel**

```bash
cd ~/Projects/squackit && python -m build --wheel 2>&1 | tail -10
```
Expected: `Successfully built squackit-0.1.0-py3-none-any.whl` (or similar). If `build` is not installed, install it first: `pip install build`.

- [ ] **Step 3: Inspect the wheel contents**

```bash
python -c "import zipfile; z = zipfile.ZipFile('dist/squackit-0.1.0-py3-none-any.whl'); print('\n'.join(sorted(z.namelist())))"
```
Expected: the list should include `squackit/__init__.py`, `squackit/server.py`, and all eight module files. No `fledgling/` files should appear (we bundle squackit, not fledgling).

- [ ] **Step 4: Final commit**

```bash
cd ~/Projects/squackit && \
  rm -rf dist build *.egg-info && \
  git add -A && \
  git diff --cached --quiet || git commit -m "chore: Phase 1 complete — squackit package extracted verbatim from fledgling/pro/"
```
(If the working tree is clean after the build cleanup, no new commit is made. That's fine.)

- [ ] **Step 5: Summary check**

Run:
```bash
cd ~/Projects/squackit && git log --oneline
```
Expected: 10–12 commits, one per task, describing the scaffold + migration sequence.

---

## Post-migration state

At the end of Plan 1:

- `~/Projects/squackit/` is a standalone pip-installable package
- `pip install -e ~/Projects/squackit` provides the `squackit` CLI
- `squackit` command starts an MCP server identical in behavior to `fledgling-pro`
- All ~1700 lines of pro-related tests pass against the fledgling repo as test data
- `fledgling/pro/` is **untouched** — `fledgling-pro` still works from the fledgling repo
- Both servers can run in parallel (different stdio processes)

**What Plan 2 adds:**
- New SQL workflow macros in fledgling (`explore_query`, `investigate_query`, `review_query`, `search_query`, `pss_render`, `ast_select_render`)
- `connection.py` / `tools.py` refinements (MCP-publications-based wrapper source, overlay-semantic `.fledgling-init.sql`, `attach`/`lockdown`/`configure` verbs)

**What Plan 3 adds:**
- `fledgling-python` extracted as a standalone package
- squackit rewired to use pluckit (and fledgling-python transitively)
- `fledgling/pro/` deleted from fledgling

---

## Self-review checklist

**Spec coverage.** Each item in the fledgling reorg spec's Section 3 ("Dissolve `fledgling/pro/`") has a corresponding task:

- `defaults.py` → Task 5
- `formatting.py` → Task 3
- `workflows.py` (Python side; SQL macros are Plan 2) → Task 7
- `session.py` → Task 4
- `prompts.py` → Task 8
- `server.py` → Task 9
- `__main__.py` → Task 10
- `db.py` → Task 6
- Tests (all six `test_pro_*.py`) → Tasks 3, 4, 5, 7, 8, 9

**Placeholder scan.** No TBDs, TODOs, or "implement later" markers. One "GitHub issue" mention in Task 9 Step 8 is a genuine escape hatch for pre-existing test failures unrelated to the migration — it directs the engineer to document rather than silently skip.

**Type consistency.** No type/method invention in this plan — every name used (`_format_markdown_table`, `create_server`, `AccessLog`, etc.) is a direct reference to an existing symbol in `fledgling/pro/` that the migration preserves unchanged.

**Task size.** Each task is 4–9 steps, 2–5 minutes per step. The biggest task (Task 9, server.py) has 9 steps but each step is a single command or verification.

**Cross-task dependencies.** Task order follows the import dependency graph: leaves first (formatting, session, defaults, db), then workflows, prompts, server, entry point, smoke tests, wheel build. Re-running a failed task does not require redoing earlier tasks.

---

## Cross-references

- **squackit design spec:** `~/Projects/squackit/docs/superpowers/specs/2026-04-10-squackit-design.md`
- **fledgling reorg design:** `/mnt/aux-data/teague/Projects/source-sextant/main/docs/superpowers/specs/2026-04-10-fledgling-reorg-design.md`
- **pluckit integration design:** `~/Projects/pluckit/main/docs/superpowers/specs/2026-04-10-fledgling-python-integration-design.md`
