# squackit Phase 3: Pluckit Rewire Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace squackit's direct runtime dependency on `fledgling` with `pluckit`, enforcing the design-spec invariant "squackit imports pluckit, **not** fledgling-python directly."

**Architecture:** Point-to-point rewrite of squackit's connection source. `db.py` and `server.py` stop calling `fledgling.connect()` and obtain their connection through pluckit. All `from fledgling.connection import Connection` TYPE_CHECKING imports switch to pluckit's equivalent. Tests drop the `import fledgling` pattern where it's being used for connection setup. No behavior changes; no API changes; no new features.

**Tech Stack:** Python 3.9+, pluckit (new runtime dep), fastmcp, duckdb (transitive via pluckit), pytest, hatchling.

---

## Execution gate — prerequisites (do NOT start executing tasks until all are true)

This plan cannot be executed until Phase 2 cross-repo work lands. The checklist below is what Task 1 verifies; if any of it fails, the plan is BLOCKED and should escalate, not work around.

- [ ] **pluckit** is published on PyPI (or pip-installable from a local editable install) at a version that contains the fledgling-python integration described in `/home/teague/Projects/pluckit/main/docs/superpowers/specs/2026-04-10-fledgling-python-integration-design.md`
- [ ] **fledgling-python** exists as a package (standalone, or re-exported through pluckit — squackit doesn't care which as long as it never imports fledgling-python by name)
- [ ] **pluckit publicly exposes** the three APIs squackit needs (see "pluckit API assumptions" below)
- [ ] **fledgling** (upstream) has the new SQL workflow macros (`pss_render`, `ast_select_render`, etc.) merged — not because this plan uses them, but because pluckit's release likely pins a minimum fledgling version that requires them
- [ ] **squackit's Phase 1 main branch is green** — `182 passed` on the full suite (matches post-Phase-1 state)

If any item fails at Task 1, STOP and escalate to the user. Do not patch around missing pluckit APIs by reaching into pluckit internals or re-adding a direct `fledgling` import.

---

## pluckit API assumptions (must be confirmed at Task 1)

This plan assumes pluckit exposes the following public API. If the actual API differs, update the code blocks in the affected tasks (flagged with 🔗 **API-contingent**) before execution. The tasks are written against these assumed names so the plan is executable once the names are confirmed or corrected.

| squackit need | Current (fledgling) usage | Assumed pluckit API | Task(s) affected |
|---|---|---|---|
| Obtain a DuckDB connection with fledgling macros + extensions loaded | `fledgling.connect(init=init, root=root, modules=modules, profile=profile)` | `pluckit.Plucker(repo=root, profile=profile, modules=modules, init=init)` — returns a `Plucker` whose `.connection` property is the fledgling Connection proxy | 3, 4 |
| Access the underlying `DuckDBPyConnection` (for AccessLog, which inserts into a sql table via a raw cursor) | `con._con` (private attribute of Connection proxy) | `plucker.connection.raw` (public property) OR `plucker.connection._con` (escape hatch, same attribute the proxy already exposes) | 4 |
| Enumerate auto-registered macro wrappers for MCP tool registration | `con._tools.list()` (private attribute of Connection proxy) | `plucker.connection.tools.list()` — same shape: list of `{"name": str, "params": dict}` dicts | 4 |
| Call a fledgling SQL macro via Python | `con.project_overview()`, `con.dr_fledgling()`, `con.find_definitions(...)` — Connection proxy's `__getattr__` magic | `plucker.connection.project_overview()` etc. — identical shape (the Connection proxy is preserved) | 4 |
| Type-hint a connection parameter | `from fledgling.connection import Connection` | `from pluckit import Plucker` and hint the `.connection` property's type, or `from pluckit.types import Connection` if pluckit re-exports it | 5 |

**Why these specific assumptions.** The pluckit integration spec says pluckit's `_Context.db` *becomes* a fledgling Connection proxy when fledgling-python is installed. If pluckit promotes that through its `Plucker` object as `plucker.connection`, squackit's existing call sites (`con.project_overview()`, `con.dr_fledgling()`, `con._con`, `con._tools.list()`) continue to work with only the binding site changing. This is the minimum-disruption path. If pluckit instead wraps the proxy in its own adapter, the tasks below will need a one-line-per-site rewrite that the agent can mechanically apply.

**Validation plan at Task 1.** Task 1 is pure discovery — no code changes, no commits. It runs a handful of `python -c` probes to confirm each assumption. If any probe fails, the plan reports BLOCKED and the user decides whether to update the plan or escalate to pluckit.

---

## Scope boundaries

**In scope for Phase 3:**
- Swap `fledgling-mcp>=0.6.2` → `pluckit>=X.Y.Z` in `pyproject.toml`
- Remove every direct `import fledgling` / `from fledgling.*` statement from `squackit/*.py`
- Rewire `squackit/db.py` and `squackit/server.py` to use pluckit as the connection source
- Update TYPE_CHECKING imports in `squackit/defaults.py`, `squackit/prompts.py`, `squackit/workflows.py`
- Update the `all_macros` fixture in `tests/conftest.py` to set up its connection through pluckit if needed (only if the current fledgling-direct setup stops working — otherwise leave it alone)
- Update any test files that import `fledgling` directly for the connection setup pattern (audit: currently `tests/test_defaults.py:7` has `import fledgling`)
- Full 182/182 test suite still green at the end
- `python -m build --wheel` produces a wheel whose METADATA shows `Requires-Dist: pluckit>=X.Y.Z` and NOT `fledgling-mcp`

**Strictly out of scope (separate plans or deferred features):**
- Refactoring `squackit/workflows.py` to use the new `explore_query` / `investigate_query` / `review_query` / `search_query` SQL macros — that belongs to a "workflows macro refactor" plan, not this rewire
- Access log persistence to disk (`~/.squackit/sessions/<id>.duckdb`) — a new feature, deferred
- Kibitzer engine — a new feature, deferred
- Deleting `fledgling/pro/` from the fledgling repo — fledgling-team concern, handled by the fledgling reorg plan
- Renaming MCP resource URIs (still `fledgling://project` etc.) — could happen later, but it's a behavior change and not part of the rewire
- Renaming the MCP server name (still `"fledgling"`) — same rationale
- Publishing squackit to PyPI — separate release process
- Any change to MCP tool surface, prompt templates, resource shapes, or output formatting

**If a task reveals an in-scope change requires an out-of-scope change to succeed, STOP and escalate.**

---

## File structure (no new files; only modifications)

```
squackit/
├── pyproject.toml                    ← MODIFIED: deps updated
├── CLAUDE.md                         ← MODIFIED: "Import rules" section updated
├── squackit/
│   ├── __init__.py                    (unchanged)
│   ├── __main__.py                    (unchanged)
│   ├── db.py                          ← MODIFIED: returns from pluckit, not fledgling
│   ├── defaults.py                    ← MODIFIED: TYPE_CHECKING import updated
│   ├── formatting.py                  (unchanged)
│   ├── prompts.py                     ← MODIFIED: TYPE_CHECKING import updated
│   ├── server.py                      ← MODIFIED: imports pluckit; create_server() uses Plucker
│   ├── session.py                     (unchanged — uses DuckDBPyConnection directly)
│   └── workflows.py                   ← MODIFIED: TYPE_CHECKING import updated
└── tests/
    ├── conftest.py                    ← POSSIBLY MODIFIED: all_macros fixture (only if it breaks)
    ├── test_defaults.py               ← MODIFIED: drop `import fledgling` on line 7
    ├── test_smoke.py                  ← MODIFIED: add test_pluckit_available
    └── (other test files unchanged — they already work through conftest fixtures)
```

---

## Tasks (7 total)

Each task is small, TDD-flavored (failing test → implement → passing test → commit), and independently committable. Model hints: Task 4 (server.py surgery) should use `sonnet`; everything else can use `haiku`.

---

### Task 1: Verify prerequisites and pluckit API assumptions (discovery only)

**Files:** none modified. No commit at the end of this task.

This task is pure discovery. It validates the plan's assumptions against the real pluckit package available in the venv. If any check fails, STOP and escalate.

- [ ] **Step 1: Check pluckit is installed and importable**

```bash
/home/teague/.local/share/venv/bin/python -c "import pluckit; print(pluckit.__version__)" 2>&1
```
Expected: prints a version string. If ModuleNotFoundError, run `pip install pluckit` first (or install the local editable copy from `/home/teague/Projects/pluckit/main`).

- [ ] **Step 2: Verify `Plucker` constructor accepts the expected kwargs**

```bash
/home/teague/.local/share/venv/bin/python -c "
import inspect
from pluckit import Plucker
sig = inspect.signature(Plucker.__init__)
params = set(sig.parameters.keys())
required = {'repo'}
optional = {'profile', 'modules', 'init'}
missing = required - params
print('missing required:', missing)
print('optional supported:', {p for p in optional if p in params})
print('all params:', sorted(params))
"
```
Expected: `missing required` is empty. If it's not, the assumed `Plucker(repo=..., profile=..., modules=..., init=...)` signature is wrong and Task 4's code blocks need to be adapted (possibly by passing kwargs through a different mechanism). Report BLOCKED with the actual signature.

- [ ] **Step 3: Verify the macro-call proxy is reachable**

```bash
/home/teague/.local/share/venv/bin/python -c "
from pluckit import Plucker
p = Plucker(repo='/tmp')
conn = p.connection
# Check that the connection exposes fledgling's macro-call proxy surface:
print('has project_overview:', callable(getattr(conn, 'project_overview', None)))
print('has dr_fledgling:', callable(getattr(conn, 'dr_fledgling', None)))
print('has _tools:', hasattr(conn, '_tools'))
print('has _con:', hasattr(conn, '_con'))
print('type:', type(conn).__name__)
"
```
Expected: all four `has ...` lines print `True`. If `project_overview` is not callable, pluckit is not exposing the fledgling Connection proxy — Task 4 needs a different approach (e.g., calling `conn.execute("SELECT * FROM project_overview()")` directly, or pluckit's own wrapper API). Report BLOCKED with the actual attribute surface.

- [ ] **Step 4: Verify `_tools.list()` works**

```bash
/home/teague/.local/share/venv/bin/python -c "
from pluckit import Plucker
p = Plucker(repo='/tmp')
tools = p.connection._tools.list()
print('tool count:', len(tools))
print('first tool keys:', sorted(tools[0].keys()) if tools else 'empty')
"
```
Expected: tool count is ≥ 20 (fledgling exposes many macros) and first tool's keys contain `name` and `params`. If the shape differs, Task 4's `for macro_info in con._tools.list(): ...` loop needs adjustment.

- [ ] **Step 5: Verify the raw DuckDBPyConnection is reachable**

```bash
/home/teague/.local/share/venv/bin/python -c "
import duckdb
from pluckit import Plucker
p = Plucker(repo='/tmp')
raw = p.connection._con
print('raw type:', type(raw).__name__)
print('is DuckDBPyConnection:', isinstance(raw, duckdb.DuckDBPyConnection))
"
```
Expected: prints `DuckDBPyConnection` and `True`. AccessLog in `squackit/session.py` currently calls `AccessLog(con._con)` — if `con._con` isn't a raw DuckDBPyConnection, AccessLog's constructor contract changes and `squackit/server.py:178` needs a different accessor.

- [ ] **Step 6: Document findings and decide go/no-go**

Write a short summary of what each probe returned. If all six probes match expectations, proceed to Task 2. If any probe fails, report BLOCKED with:
- Which probe failed
- The actual output
- A proposed plan delta (which tasks' code blocks need adjustment)

Do NOT commit anything from this task. It's verification-only.

---

### Task 2: Add pluckit to dependencies, verify smoke test 🔗 API-contingent (version pin)

**Files:**
- Modify: `pyproject.toml` (the `[project].dependencies` list)
- Modify: `tests/test_smoke.py` (append one test)

- [ ] **Step 1: Write a failing smoke test for pluckit availability**

Append to `tests/test_smoke.py`:
```python


def test_pluckit_available():
    """squackit's runtime depends on pluckit — verify it's importable."""
    import pluckit
    assert hasattr(pluckit, "Plucker")
```

- [ ] **Step 2: Run smoke tests to verify 5 pass, 1 fails**

```bash
cd /home/teague/Projects/squackit && \
  /home/teague/.local/share/venv/bin/python -m pytest tests/test_smoke.py -v 2>&1 | tail -15
```
Expected: `test_pluckit_available` FAILS with `ModuleNotFoundError` OR passes if pluckit was already in the venv from Task 1. Either is fine — we're documenting the dependency.

- [ ] **Step 3: Edit pyproject.toml — swap deps**

Find the `dependencies` array in `[project]` and replace:
```toml
dependencies = [
    "fledgling-mcp>=0.6.2",
    "duckdb>=1.5.0",
    "fastmcp>=3.0",
]
```
with:
```toml
dependencies = [
    "pluckit>=X.Y.Z",  # ← actual minimum version TBD at Task 1
    "fastmcp>=3.0",
]
```

The `duckdb` dependency is dropped because pluckit depends on it transitively. The `fledgling-mcp` dependency is dropped — Phase 3's whole point is that squackit no longer depends on it directly.

**Version pin:** fill in `X.Y.Z` with the version Task 1 verified. If Task 1 found pluckit at (say) version `0.3.1`, use `pluckit>=0.3.1`. Add a comment noting the minimum-version rationale ("first version with fledgling-python integration").

- [ ] **Step 4: Re-install and re-run smoke tests**

```bash
cd /home/teague/Projects/squackit && \
  /home/teague/.local/share/venv/bin/python -m pip install -e . 2>&1 | tail -3 && \
  /home/teague/.local/share/venv/bin/python -m pytest tests/test_smoke.py -v 2>&1 | tail -15
```
Expected: `pip install -e .` reports success and resolves pluckit; all 5 smoke tests pass.

- [ ] **Step 5: Commit**

```bash
cd /home/teague/Projects/squackit && \
  git add pyproject.toml tests/test_smoke.py && \
  git commit -m "feat: swap fledgling-mcp runtime dep for pluckit"
```

---

### Task 3: Rewire `squackit/db.py` 🔗 API-contingent

**Files:**
- Modify: `squackit/db.py` (all 15 lines, rewrite the module)

`db.py` is a thin wrapper over `fledgling.connect()`. After Phase 3 it's a thin wrapper over pluckit's `Plucker`. The public name (`create_connection`) stays for backwards compatibility with any external caller, but its return type changes from a fledgling Connection to the pluckit-owned Connection proxy exposed via `plucker.connection`.

- [ ] **Step 1: Write a failing test for the new contract**

Append to `tests/test_smoke.py`:
```python


def test_create_connection_returns_macro_proxy():
    """create_connection() should return an object with fledgling macro methods."""
    from squackit.db import create_connection
    conn = create_connection()
    assert callable(getattr(conn, "project_overview", None))
```

- [ ] **Step 2: Run the new test — expect FAIL**

```bash
cd /home/teague/Projects/squackit && \
  /home/teague/.local/share/venv/bin/python -m pytest tests/test_smoke.py::test_create_connection_returns_macro_proxy -v 2>&1 | tail -15
```
Expected: FAIL (the current `db.py` still returns `fledgling.connect()` result, which may or may not have `project_overview` depending on whether `fledgling` is still in the venv). Fine either way.

- [ ] **Step 3: Rewrite `squackit/db.py`**

Replace the entire file with:
```python
"""DuckDB connection for squackit.

Thin wrapper over pluckit's Plucker that returns a fledgling-enabled
connection proxy. All macro calls (``conn.project_overview()``, etc.)
route through pluckit → fledgling-python → fledgling's SQL macros.
"""

from pluckit import Plucker


def create_connection(**kwargs):
    """Create a fledgling-enabled DuckDB connection via pluckit.

    Accepts the same kwargs that :class:`pluckit.Plucker` accepts
    (``repo``, ``profile``, ``modules``, ``init``). Returns the Plucker's
    fledgling Connection proxy — the same object the rest of squackit
    treats as ``con`` throughout server.py.
    """
    return Plucker(**kwargs).connection
```

**If Task 1 found that the attribute is not `Plucker(...).connection`** (e.g. pluckit uses a different name like `.db` or exposes it via `Plucker(...).engine`), update the single `return Plucker(**kwargs).connection` line accordingly. Everything else in this file is pluckit-API-agnostic.

- [ ] **Step 4: Run all smoke tests — expect all pass**

```bash
cd /home/teague/Projects/squackit && \
  /home/teague/.local/share/venv/bin/python -m pytest tests/test_smoke.py -v 2>&1 | tail -15
```
Expected: 6 passed (4 original + 2 added in Tasks 2 and 3).

- [ ] **Step 5: Commit**

```bash
cd /home/teague/Projects/squackit && \
  git add squackit/db.py tests/test_smoke.py && \
  git commit -m "feat: rewire db.py to use pluckit"
```

---

### Task 4: Rewire `squackit/server.py` — the big one 🔗 API-contingent

**Files:**
- Modify: `squackit/server.py:27-28` (drop direct fledgling imports)
- Modify: `squackit/server.py:168` (replace `fledgling.connect(...)` with the pluckit equivalent)
- Modify: `squackit/server.py:297` (update Connection type hint, if present)

This is the only task that touches more than one line of real logic in `server.py`. The resource handlers, tool-registration loop, and prompt/resource definitions all stay identical because they interact with `con` through the Connection proxy interface, which Task 1 verified pluckit preserves.

- [ ] **Step 1: Run the full suite to establish a baseline**

```bash
cd /mnt/aux-data/teague/Projects/source-sextant/main && \
  FLEDGLING_REPO_PATH=$(pwd) \
  /home/teague/.local/share/venv/bin/python -m pytest /home/teague/Projects/squackit/tests/ 2>&1 | tail -5
```
Expected: `182 passed` (or whatever the current baseline is). Record the number. You'll re-run this at Step 5 and it must match.

- [ ] **Step 2: Delete the two direct fledgling imports at lines 27-28**

Remove these two lines from `squackit/server.py`:
```python
import fledgling
from fledgling.connection import Connection
```

- [ ] **Step 3: Add the pluckit import**

In the import block (near the top, after the stdlib imports), add:
```python
from pluckit import Plucker
```

- [ ] **Step 4: Replace the `fledgling.connect(...)` call**

At `squackit/server.py:168` (inside `create_server()`), find:
```python
    con = fledgling.connect(init=init, root=root, modules=modules, profile=profile)
```
and replace with:
```python
    con = Plucker(repo=root, profile=profile, modules=modules, init=init).connection
```

**If Task 1 found that `Plucker` uses different kwarg names** (e.g. `root=` instead of `repo=`), update this line. Everything else in `create_server()` stays the same — `con._con` (line 178), `con._tools.list()` (line 183), and all `con.<macro>()` calls in resource handlers (lines 201, 215, etc.) work through the Connection proxy which pluckit preserves.

- [ ] **Step 5: Fix the Connection type hint**

At `squackit/server.py:297` (the signature of `_register_tool` or whichever helper takes `con: Connection`), either:
- (a) Replace `Connection` with a broader type: `con: "duckdb.DuckDBPyConnection"` (using a string-literal forward reference), OR
- (b) Add a TYPE_CHECKING import at the top of the file:
  ```python
  if TYPE_CHECKING:
      from pluckit import Plucker  # for plucker.connection type
  ```
  and hint the type as `con: "Plucker.connection"` or whatever pluckit's public type for the proxy is.

Option (a) is simpler and survives pluckit API changes. Option (b) is more correct typing. Pick (a) unless pluckit exports a clean Connection type.

- [ ] **Step 6: Run the full suite — expect 182 passed (unchanged baseline)**

```bash
cd /mnt/aux-data/teague/Projects/source-sextant/main && \
  FLEDGLING_REPO_PATH=$(pwd) \
  /home/teague/.local/share/venv/bin/python -m pytest /home/teague/Projects/squackit/tests/ 2>&1 | tail -5
```
Expected: identical pass count to Step 1 (e.g. `182 passed`). If the count drops by even 1, something broke — investigate before committing.

- [ ] **Step 7: Confirm no direct fledgling references remain in server.py**

```bash
grep -n 'fledgling' /home/teague/Projects/squackit/squackit/server.py
```
Expected output contains ONLY references that are string literals (e.g. `"fledgling"` as the MCP server name, `"fledgling://project"` as a resource URI, `"Fledgling"` in docstrings) — NOT import statements, NOT `fledgling.connect(...)` calls. If any import-like reference remains, revisit Steps 2–5.

- [ ] **Step 8: Commit**

```bash
cd /home/teague/Projects/squackit && \
  git add squackit/server.py && \
  git commit -m "feat: rewire server.py to obtain its connection via pluckit"
```

---

### Task 5: Update TYPE_CHECKING imports in defaults/prompts/workflows

**Files:**
- Modify: `squackit/defaults.py:20`
- Modify: `squackit/prompts.py:21`
- Modify: `squackit/workflows.py:18`

These three files only import `Connection` inside a `TYPE_CHECKING:` guard for type hints. The imports are not used at runtime. Replacing them is purely a typing change with zero runtime impact — but we still run the suite afterward to confirm no mypy-time breakage leaked through.

- [ ] **Step 1: In each of the three files, replace the import**

Currently:
```python
if TYPE_CHECKING:
    from fledgling.connection import Connection
```
After:
```python
if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection as Connection
```

Rationale: `DuckDBPyConnection` is what `plucker.connection._con` wraps, and the fledgling Connection proxy forwards all attribute access to it. Using `DuckDBPyConnection` as the type hint is the broadest-compatible choice that doesn't depend on any pluckit-specific type.

**Alternative**: if pluckit publicly exports its own Connection type (check at Task 1 Step 3), use that instead:
```python
if TYPE_CHECKING:
    from pluckit.types import Connection  # or whatever pluckit calls it
```

Pick the duckdb fallback unless Task 1 confirmed a pluckit type exists.

- [ ] **Step 2: Run the full suite**

```bash
cd /mnt/aux-data/teague/Projects/source-sextant/main && \
  FLEDGLING_REPO_PATH=$(pwd) \
  /home/teague/.local/share/venv/bin/python -m pytest /home/teague/Projects/squackit/tests/ 2>&1 | tail -5
```
Expected: same pass count as Task 4 Step 6. TYPE_CHECKING blocks are runtime-inert so this should be a no-op at test time.

- [ ] **Step 3: Commit**

```bash
cd /home/teague/Projects/squackit && \
  git add squackit/defaults.py squackit/prompts.py squackit/workflows.py && \
  git commit -m "refactor: drop TYPE_CHECKING fledgling imports in favor of duckdb"
```

---

### Task 6: Audit and update tests that import `fledgling` directly

**Files:**
- Modify: `tests/test_defaults.py:7` (has `import fledgling`)
- Possibly modify: `tests/conftest.py` (the `all_macros` fixture)

- [ ] **Step 1: Find every test file that imports fledgling**

```bash
grep -rn '^import fledgling\|^from fledgling' /home/teague/Projects/squackit/tests/
```
Expected: At least `tests/test_defaults.py:7: import fledgling`. If other files appear, include them in Step 2.

- [ ] **Step 2: Audit how `fledgling` is used in each match**

For each matched file, read the surrounding code and classify each `fledgling.*` reference:

| Classification | How to handle |
|---|---|
| `fledgling.connect(...)` call setting up a connection in a test | Replace with `from squackit.db import create_connection; con = create_connection(...)`. Squackit already owns this wrapper (Task 3). |
| `from fledgling.connection import Connection` for a type hint | Replace with `from duckdb import DuckDBPyConnection as Connection` (same pattern as Task 5). |
| A bare `import fledgling` with no dotted-attribute access | Probably dead — remove. |

Do NOT rewrite the `conftest.py` `all_macros` fixture unless the full suite breaks. That fixture uses `duckdb.connect(":memory:")` directly and loads SQL files — it doesn't go through fledgling.connect() at all, so it should be untouched. Verify with:
```bash
grep -n 'fledgling' /home/teague/Projects/squackit/tests/conftest.py
```
Expected output: only references to the *string* "fledgling" (e.g. `os.environ.get("FLEDGLING_REPO_PATH")`, `fledgling_version`, `fledgling_modules`, `fledgling_profile`), NOT an `import fledgling` line. If an `import fledgling` appears, it needs to be removed.

- [ ] **Step 3: Apply the replacements**

For `tests/test_defaults.py:7`, read the file to see what `fledgling` is used for and apply the appropriate replacement from Step 2's table. Likely it's a test fixture that calls `fledgling.connect(root=str(PROJECT_ROOT))` — in which case replace with `create_connection(repo=str(PROJECT_ROOT))` (note: `repo=` is pluckit's kwarg per Task 1's verification).

- [ ] **Step 4: Re-run the suite**

```bash
cd /mnt/aux-data/teague/Projects/source-sextant/main && \
  FLEDGLING_REPO_PATH=$(pwd) \
  /home/teague/.local/share/venv/bin/python -m pytest /home/teague/Projects/squackit/tests/ 2>&1 | tail -5
```
Expected: same pass count as Task 5.

- [ ] **Step 5: Confirm no direct fledgling imports remain anywhere in squackit code**

```bash
grep -rn '^import fledgling\|^from fledgling' /home/teague/Projects/squackit/squackit/ /home/teague/Projects/squackit/tests/
```
Expected: empty output. If any match, revisit the affected file.

- [ ] **Step 6: Commit**

```bash
cd /home/teague/Projects/squackit && \
  git add tests/test_defaults.py && \
  git commit -m "test: route test fixtures through squackit.db.create_connection"
```
(If conftest.py needed a change, include it in the same commit.)

---

### Task 7: Full suite + wheel build verification + CLAUDE.md update

**Files:**
- Modify: `CLAUDE.md` (the "Import rules" section)
- No code changes; final verification pass

- [ ] **Step 1: Clean pytest cache and run the full suite**

```bash
cd /home/teague/Projects/squackit && rm -rf .pytest_cache && \
  cd /mnt/aux-data/teague/Projects/source-sextant/main && \
  FLEDGLING_REPO_PATH=$(pwd) \
  /home/teague/.local/share/venv/bin/python -m pytest /home/teague/Projects/squackit/tests/ 2>&1 | tail -10
```
Expected: `182 passed` (the post-Phase-1 baseline plus any smoke tests added in Tasks 2/3). Actual count after Phase 3 should be 184 (182 baseline + `test_pluckit_available` + `test_create_connection_returns_macro_proxy`). If the count is lower, something regressed — do NOT proceed.

- [ ] **Step 2: Build the wheel**

```bash
cd /home/teague/Projects/squackit && \
  rm -rf dist build *.egg-info && \
  /home/teague/.local/share/venv/bin/python -m build --wheel 2>&1 | tail -10
```
Expected: `Successfully built squackit-0.1.0-py3-none-any.whl`.

- [ ] **Step 3: Inspect the wheel METADATA**

```bash
cd /home/teague/Projects/squackit && \
  /home/teague/.local/share/venv/bin/python -c "
import zipfile
z = zipfile.ZipFile('dist/squackit-0.1.0-py3-none-any.whl')
meta = z.read('squackit-0.1.0.dist-info/METADATA').decode()
for line in meta.splitlines():
    if 'Requires-Dist' in line or 'Name' in line or 'Version' in line:
        print(line)
"
```
Expected:
- `Requires-Dist: pluckit>=X.Y.Z` is present
- `Requires-Dist: fledgling-mcp...` is NOT present
- `Requires-Dist: fastmcp>=3.0` is still present
- `Requires-Dist: duckdb...` may or may not be present (depends on whether it was kept as a direct dep — Task 2 recommends dropping it)

- [ ] **Step 4: Inspect the wheel file contents**

```bash
/home/teague/.local/share/venv/bin/python -c "
import zipfile
z = zipfile.ZipFile('/home/teague/Projects/squackit/dist/squackit-0.1.0-py3-none-any.whl')
for name in sorted(z.namelist()):
    print(name)
"
```
Expected: 9 `squackit/*.py` files + dist-info entries. Same shape as Phase 1's wheel.

- [ ] **Step 5: Grep the wheel source for any accidental fledgling imports**

```bash
/home/teague/.local/share/venv/bin/python -c "
import zipfile
z = zipfile.ZipFile('/home/teague/Projects/squackit/dist/squackit-0.1.0-py3-none-any.whl')
for name in z.namelist():
    if name.endswith('.py'):
        src = z.read(name).decode()
        for lineno, line in enumerate(src.splitlines(), 1):
            if 'import fledgling' in line or 'from fledgling' in line:
                print(f'{name}:{lineno}: {line}')
"
```
Expected: empty output. If any line appears, Phase 3 is incomplete.

- [ ] **Step 6: Update CLAUDE.md import rules**

Open `/home/teague/Projects/squackit/CLAUDE.md` and replace the existing "Import rules" section with:
```markdown
## Import rules

- `squackit.*` for internal imports
- `pluckit.*` for the fluent API and the macro-enabled Connection (squackit's
  only runtime dependency for fledgling access)
- **Never** `import fledgling` or `from fledgling_python ...`. squackit reaches
  fledgling's SQL macros only through pluckit. If you need a capability pluckit
  doesn't expose, grow pluckit, don't add an escape hatch.
- Tests use `from conftest import PROJECT_ROOT` — squackit's `conftest.py`
  defines `PROJECT_ROOT` lazily via fledgling package discovery (repo layout
  preferred, bundled-package layout as fallback).
```

Leave the "Phase 1 scope" section alone — it's outdated but documents history and will be updated in a future "Phase 3 complete" pass.

- [ ] **Step 7: Clean build artifacts and make the final commit**

```bash
cd /home/teague/Projects/squackit && \
  rm -rf dist build *.egg-info && \
  git add CLAUDE.md && \
  git commit -m "chore: Phase 3 complete — squackit imports pluckit, not fledgling"
```

- [ ] **Step 8: Print the commit trail for the record**

```bash
cd /home/teague/Projects/squackit && git log --oneline -10
```
Expected: the 7 Phase-3 commits sit on top of Phase 1's history. A reader should be able to see the rewire without scrolling.

---

## Post-Phase-3 state

At the end of this plan:

- `squackit` depends on `pluckit`, not on `fledgling-mcp`, at the wheel-METADATA level
- Zero `import fledgling` or `from fledgling.*` statements remain in `squackit/*.py` or `tests/*.py`
- `create_server()` obtains its Connection proxy through `Plucker(...).connection`
- `squackit.db.create_connection()` delegates to pluckit
- All 182 Phase-1 tests still pass, plus 2 new smoke tests verifying pluckit availability and the connection contract (184 total)
- `python -m build --wheel` produces a clean wheel with `Requires-Dist: pluckit>=X.Y.Z`
- CLAUDE.md documents the new import rule

The dependency invariant `squackit → pluckit → fledgling-python → fledgling` is now enforced at the package level, matching the design spec.

## What Phase 3 intentionally does NOT do

These are documented so a future reader doesn't mistake the plan's incompleteness for a scope miss:

- **Workflows macro refactor.** `squackit/workflows.py` still contains the verbatim fledgling-pro workflow objects. Rewriting them to use the new `explore_query` / `investigate_query` / `review_query` / `search_query` SQL macros is a Phase 4 concern. It deserves its own plan because the output-shape compatibility matrix is non-trivial.
- **Access log persistence to disk.** Still in-memory. `~/.squackit/sessions/<id>.duckdb` is a future feature; the schema is drafted in the squackit design spec but not implemented.
- **Kibitzer engine.** Out of scope, deferred.
- **MCP resource URI rename.** Resource URIs still start with `fledgling://`. Renaming to `squackit://` is a behavior change; it's a one-line-per-URI task but it's an API break for anyone consuming these URIs, so it gets a separate decision.
- **Server name rename.** `FastMCP("fledgling")` stays as `"fledgling"`. Same rationale as URI rename.
- **Publishing to PyPI.** The wheel is built locally for verification. Publishing is a separate release process with its own checklist.

## Self-review

**Spec coverage.** The Phase 3 slice of the squackit design spec is:
- Dependency chain invariant 1 ("squackit imports pluckit, not fledgling_python") — Tasks 2, 4, 5, 6 cover every touchpoint
- Dependency chain invariant 2 ("squackit never constructs SQL strings; it calls pluckit chains or invokes fledgling SQL macros via pluckit's macro-call proxy") — already true for squackit post-Phase-1 (no string-SQL construction in squackit code); Task 4 preserves it via the Connection proxy hand-off
- Dependency chain invariant 3 ("squackit is the only layer with session state") — unchanged; squackit/session.py still owns AccessLog and SessionCache
- Dependency chain invariant 4 ("squackit is the only layer that knows about MCP as a protocol") — unchanged; FastMCP wiring stays in server.py

**Placeholder scan.** No TBDs, TODOs, or "implement later" markers in the task steps themselves. The version pin (`X.Y.Z`) in Task 2 is a deliberate placeholder filled in from Task 1's verification output; the 🔗 API-contingent markers flag tasks whose code blocks may need mechanical adjustment if Task 1 uncovers pluckit API differences. Both are documented gaps, not lazy planning.

**Type consistency.** Every reference is to an existing symbol: `pluckit.Plucker` (exists in `/home/teague/Projects/pluckit/main/src/pluckit/plucker.py`), `plucker.connection` (assumed per Task 1 verification), `squackit.db.create_connection` (Phase 1 symbol), `AccessLog`, `SessionCache`, `create_server` (all Phase 1 symbols). No invented names.

**Task size.** Task 1 is 6 steps (discovery, the longest). Tasks 2–6 are 5-step TDD cycles. Task 7 is 8 steps (verification + CLAUDE.md + commit). All steps are 2-5 minute operations.

**Cross-task dependencies.** Tasks execute in order 1 → 2 → 3 → 4 → 5 → 6 → 7. Task 1 is a gate (blocks everything else if prerequisites fail). Task 4 depends on Task 3 (db.py's create_connection is used in server.py? Actually no — they're independent, server.py uses Plucker directly. Task 4 depends on Task 2 for the pluckit dep being in pyproject.toml). Tasks 5 and 6 are commutative with each other — either order works. Task 7 depends on all prior tasks being done.

## Cross-references

- **squackit design spec:** `/home/teague/Projects/squackit/docs/superpowers/specs/2026-04-10-squackit-design.md`
- **pluckit integration spec:** `/home/teague/Projects/pluckit/main/docs/superpowers/specs/2026-04-10-fledgling-python-integration-design.md`
- **fledgling reorg spec:** `/mnt/aux-data/teague/Projects/source-sextant/main/docs/superpowers/specs/2026-04-10-fledgling-reorg-design.md`
- **Phase 1 plan (for reference):** `/home/teague/Projects/squackit/docs/superpowers/plans/2026-04-10-squackit-extraction.md`
