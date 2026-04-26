# Named FTS Collections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable fledgling to host N independent BM25 indexes (collections) with per-collection IDF statistics, exposed through pluckit's Python API.

**Architecture:** Fledgling gets two parameterized SQL templates (create + search) and a catalog table. Pluckit wraps these in an `FtsCollection` class on the Connection, and migrates the Search pluckin to use the new templates. The existing `fts.content` collection is rebuilt using the new infrastructure. MCP tool surface is unchanged.

**Tech Stack:** DuckDB (SQL, FTS extension, MAP types), Python (fledgling Connection wrapper, pluckit Pluckin system)

**Repos:**
- Fledgling: `/mnt/aux-data/teague/Projects/source-sextant/main`
- Pluckit: `/mnt/aux-data/teague/Projects/pluckit/main`
- Lackpy (quartermaster): `/mnt/aux-data/teague/Projects/lackpy/main`

**Design spec:** `docs/superpowers/specs/2026-04-26-named-fts-collections-design.md`

---

## File Map

### Fledgling (source-sextant)

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `sql/fts.sql` | Add `fts.collections` catalog table DDL (non-breaking addition) |
| Modify | `fledgling/connection.py` | Add `create_fts_collection()`, `search_collection()` methods; register `content` in catalog after rebuild |
| Create | `tests/test_fts_collections.py` | Tests for the new collection infrastructure (create, search, catalog, idempotent rebuild) |

**Not modified:** `sql/fts_rebuild.sql` (wide `fts.content` schema preserved — `find_code_ranked` and MCP tools depend on columns like `file_path`, `ordinal`, `kind`), `tests/test_fts.py` (existing macros unchanged), `tests/conftest.py` (catalog DDL lives in `fts.sql`, loaded by existing fixtures).

### Pluckit

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `src/pluckit/fts.py` | `FtsCollection` class |
| Modify | `src/pluckit/plucker.py` | Add `fts_collection(name)` convenience method on Plucker |
| Create | `tests/pluckins/test_fts_collection.py` | Tests for `FtsCollection` (create, search, integration) |

**Not modified:** `src/pluckit/pluckins/search.py` (existing `fts_fts_content` references still correct — `content` collection keeps the wide schema and its BM25 accessor), `tests/pluckins/test_search.py` (verified passing, no changes needed).

---

## Task 1: Catalog Table in fts.sql (Fledgling SQL)

**Files:**
- Modify: `sql/fts.sql:52`
- Create: `tests/test_fts_collections.py`

Add the `fts.collections` catalog table to `fts.sql` — it lives alongside the existing `fts.content` table since both are part of the fts module. The catalog tracks which collections have been created and when they were last rebuilt.

- [ ] **Step 1: Write failing test for catalog table**

Create `tests/test_fts_collections.py`:

```python
"""Tests for named FTS collection infrastructure."""

import pytest
from conftest import PROJECT_ROOT, load_sql


class TestCatalog:
    def test_catalog_table_exists(self, fts_macros):
        tables = fts_macros.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'fts' AND table_name = 'collections'"
        ).fetchall()
        assert len(tables) == 1

    def test_catalog_columns(self, fts_macros):
        cols = fts_macros.execute(
            "DESCRIBE fts.collections"
        ).fetchall()
        col_names = [c[0] for c in cols]
        assert "name" in col_names
        assert "created_at" in col_names
        assert "rebuilt_at" in col_names

    def test_catalog_starts_empty(self, fts_macros):
        count = fts_macros.execute(
            "SELECT count(*) FROM fts.collections"
        ).fetchone()[0]
        assert count == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/aux-data/teague/Projects/source-sextant/main && python -m pytest tests/test_fts_collections.py::TestCatalog -v`
Expected: FAIL — `fts.collections` table does not exist.

- [ ] **Step 3: Add catalog table to fts.sql**

In `sql/fts.sql`, add after line 52 (`CREATE SCHEMA IF NOT EXISTS fts;`):

```sql
CREATE TABLE IF NOT EXISTS fts.collections (
    name       TEXT PRIMARY KEY,
    created_at TIMESTAMP DEFAULT current_timestamp,
    rebuilt_at TIMESTAMP
);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/aux-data/teague/Projects/source-sextant/main && python -m pytest tests/test_fts_collections.py::TestCatalog -v`
Expected: PASS

- [ ] **Step 5: Verify existing fts tests still pass (non-breaking)**

Run: `cd /mnt/aux-data/teague/Projects/source-sextant/main && python -m pytest tests/test_fts.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd /mnt/aux-data/teague/Projects/source-sextant/main
git add sql/fts.sql tests/test_fts_collections.py
git commit -m "feat(fts): add collections catalog table to fts schema"
```

---

## Task 2: Connection Wrapper — create_fts_collection (Fledgling Python)

**Files:**
- Modify: `fledgling/connection.py:486-527`
- Modify: `tests/conftest.py:151-183`
- Modify: `tests/test_fts_collections.py`

Add `create_fts_collection(name, source_query)` and `search_collection(name, query, limit)` methods to fledgling's `Connection` class. These methods execute parameterized SQL templates — they are not DuckDB macros.

- [ ] **Step 1: Write failing test for create_fts_collection**

Append to `tests/test_fts_collections.py`:

```python
import duckdb
from fledgling.connection import connect


@pytest.fixture
def fledgling_con():
    """Fledgling Connection with fts module loaded."""
    con = connect(root=PROJECT_ROOT, modules=["sandbox", "code", "docs", "fts"])
    return con


class TestCreateCollection:
    def test_creates_table(self, fledgling_con):
        fledgling_con.create_fts_collection("test_col", """
            SELECT '1' AS id, 'hello world' AS text,
                   map{'kind': 'test'} AS metadata
        """)
        count = fledgling_con.execute(
            "SELECT count(*) FROM fts.test_col"
        ).fetchone()[0]
        assert count == 1

    def test_table_has_correct_schema(self, fledgling_con):
        fledgling_con.create_fts_collection("test_col", """
            SELECT '1' AS id, 'hello world' AS text,
                   map{'kind': 'test'} AS metadata
        """)
        cols = fledgling_con.execute("DESCRIBE fts.test_col").fetchall()
        col_names = [c[0] for c in cols]
        assert "id" in col_names
        assert "text" in col_names
        assert "metadata" in col_names

    def test_updates_catalog(self, fledgling_con):
        fledgling_con.create_fts_collection("test_col", """
            SELECT '1' AS id, 'hello world' AS text,
                   map{'kind': 'test'} AS metadata
        """)
        row = fledgling_con.execute(
            "SELECT name, rebuilt_at FROM fts.collections WHERE name = 'test_col'"
        ).fetchone()
        assert row is not None
        assert row[0] == "test_col"
        assert row[1] is not None

    def test_idempotent_replace(self, fledgling_con):
        for i in range(2):
            fledgling_con.create_fts_collection("test_col", f"""
                SELECT '{i}' AS id, 'version {i}' AS text,
                       map{{'run': '{i}'}} AS metadata
            """)
        rows = fledgling_con.execute(
            "SELECT * FROM fts.test_col"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "1"

    def test_catalog_count_after_multiple_collections(self, fledgling_con):
        fledgling_con.create_fts_collection("alpha", """
            SELECT '1' AS id, 'alpha text' AS text, map{} AS metadata
        """)
        fledgling_con.create_fts_collection("beta", """
            SELECT '1' AS id, 'beta text' AS text, map{} AS metadata
        """)
        count = fledgling_con.execute(
            "SELECT count(*) FROM fts.collections"
        ).fetchone()[0]
        assert count >= 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/aux-data/teague/Projects/source-sextant/main && python -m pytest tests/test_fts_collections.py::TestCreateCollection -v`
Expected: FAIL — `create_fts_collection` method does not exist on Connection.

- [ ] **Step 3: Add create_fts_collection to Connection**

In `fledgling/connection.py`, add the following method to the `Connection` class (after `rebuild_fts`, around line 526):

```python
    def create_fts_collection(
        self,
        name: str,
        source_query: str,
    ) -> None:
        """Create or replace a named FTS collection.

        Drops and recreates ``fts.<name>`` from the source query, builds a
        BM25 index over the ``text`` column, and updates the catalog.

        The source query must produce ``(id TEXT, text TEXT, metadata MAP(TEXT, TEXT))``.

        Args:
            name: Collection name (becomes the table name in the fts schema).
            source_query: SQL SELECT producing (id, text, metadata) rows.
        """
        import re
        if not re.match(r'^[a-z_][a-z0-9_]*$', name):
            raise ValueError(f"Invalid collection name: {name!r}")
        self._con.execute(f"DROP TABLE IF EXISTS fts.{name}")
        self._con.execute(
            f"CREATE TABLE fts.{name} (id TEXT, text TEXT, metadata MAP(TEXT, TEXT))"
        )
        self._con.execute(
            f"INSERT INTO fts.{name} SELECT * FROM ({source_query})"
        )
        self._con.execute(
            f"PRAGMA create_fts_index('fts.{name}', 'id', 'text', overwrite = 1)"
        )
        self._con.execute(
            "INSERT OR REPLACE INTO fts.collections (name, created_at, rebuilt_at) "
            "VALUES (?, current_timestamp, current_timestamp)",
            [name],
        )
```

Also ensure `fts_collections.sql` is loaded during connection setup. In the `load_macros` function (or wherever fts.sql is loaded), add `fts_collections.sql` after `fts.sql`. Check how `load_macros` works — it loads SQL files by module name. The `fts` module loads `fts.sql`. We need `fts_collections.sql` loaded as well.

The simplest approach: have `fts.sql` include the catalog table creation at the top (before the `fts.content` table), or modify the `fts` module's SQL load sequence. Since the catalog table is a simple `CREATE TABLE IF NOT EXISTS`, it's safe to add it at the top of `fts.sql` or load `fts_collections.sql` alongside. For now, add the catalog creation to the top of `fts.sql` — this keeps it in the same module without needing a new module entry. We'll move it to `fts_collections.sql` for cleanliness but have `load_macros` load it.

Actually, the simplest path: add the catalog CREATE TABLE to the top of `fts.sql` itself. The `fts_collections.sql` file is for reference/documentation but the actual DDL runs inside `fts.sql`. This avoids touching `install-fledgling.sql` module registry.

Update `sql/fts.sql` — add after line 52 (`CREATE SCHEMA IF NOT EXISTS fts;`):

```sql
CREATE TABLE IF NOT EXISTS fts.collections (
    name       TEXT PRIMARY KEY,
    created_at TIMESTAMP DEFAULT current_timestamp,
    rebuilt_at TIMESTAMP
);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/aux-data/teague/Projects/source-sextant/main && python -m pytest tests/test_fts_collections.py::TestCreateCollection -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /mnt/aux-data/teague/Projects/source-sextant/main
git add fledgling/connection.py sql/fts.sql tests/test_fts_collections.py
git commit -m "feat(fts): add create_fts_collection to Connection"
```

---

## Task 3: Connection Wrapper — search_collection (Fledgling Python)

**Files:**
- Modify: `fledgling/connection.py`
- Modify: `tests/test_fts_collections.py`

- [ ] **Step 1: Write failing test for search_collection**

Append to `tests/test_fts_collections.py`:

```python
class TestSearchCollection:
    def test_search_returns_results(self, fledgling_con):
        fledgling_con.create_fts_collection("search_test", """
            SELECT '1' AS id, 'the quick brown fox' AS text, map{} AS metadata
            UNION ALL
            SELECT '2', 'lazy dog sleeping', map{}
            UNION ALL
            SELECT '3', 'quick fox jumping over', map{}
        """)
        results = fledgling_con.search_collection("search_test", "quick fox")
        assert len(results) > 0

    def test_search_returns_scored_rows(self, fledgling_con):
        fledgling_con.create_fts_collection("score_test", """
            SELECT '1' AS id, 'authentication login password' AS text, map{} AS metadata
            UNION ALL
            SELECT '2', 'database connection pooling', map{}
        """)
        results = fledgling_con.search_collection("score_test", "authentication")
        assert len(results) >= 1
        row = results[0]
        assert row[0] == "1"  # id
        assert row[3] is not None  # score

    def test_search_respects_limit(self, fledgling_con):
        rows_sql = " UNION ALL ".join(
            f"SELECT '{i}' AS id, 'common term repeated' AS text, map{{}} AS metadata"
            for i in range(20)
        )
        fledgling_con.create_fts_collection("limit_test", rows_sql)
        results = fledgling_con.search_collection("limit_test", "common term", limit=5)
        assert len(results) <= 5

    def test_search_empty_collection(self, fledgling_con):
        fledgling_con.create_fts_collection("empty_test", """
            SELECT '1' AS id, 'some text' AS text, map{} AS metadata
            WHERE false
        """)
        results = fledgling_con.search_collection("empty_test", "anything")
        assert results == []

    def test_search_nonexistent_collection_errors(self, fledgling_con):
        with pytest.raises(Exception):
            fledgling_con.search_collection("nonexistent", "query")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/aux-data/teague/Projects/source-sextant/main && python -m pytest tests/test_fts_collections.py::TestSearchCollection -v`
Expected: FAIL — `search_collection` method does not exist.

- [ ] **Step 3: Add search_collection to Connection**

In `fledgling/connection.py`, add to the `Connection` class after `create_fts_collection`:

```python
    def search_collection(
        self,
        name: str,
        query: str,
        limit: int = 20,
    ) -> list:
        """BM25 search over a named FTS collection.

        Returns rows as ``(id, text, metadata, score)`` ordered by score descending.

        Args:
            name: Collection name (must have been created with create_fts_collection).
            query: BM25 search query.
            limit: Maximum results (default 20).
        """
        import re
        if not re.match(r'^[a-z_][a-z0-9_]*$', name):
            raise ValueError(f"Invalid collection name: {name!r}")
        sql = (
            f"SELECT c.id, c.text, c.metadata, "
            f"  fts_fts_{name}.match_bm25(c.id, ?) AS score "
            f"FROM fts.{name} c "
            f"WHERE fts_fts_{name}.match_bm25(c.id, ?) IS NOT NULL "
            f"ORDER BY score DESC "
            f"LIMIT ?"
        )
        return self._con.execute(sql, [query, query, limit]).fetchall()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/aux-data/teague/Projects/source-sextant/main && python -m pytest tests/test_fts_collections.py::TestSearchCollection -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /mnt/aux-data/teague/Projects/source-sextant/main
git add fledgling/connection.py tests/test_fts_collections.py
git commit -m "feat(fts): add search_collection to Connection"
```

---

## Task 4: Register Content Collection in Catalog After Rebuild (Fledgling)

**Files:**
- Modify: `sql/fts_rebuild.sql`
- Modify: `fledgling/connection.py`
- Modify: `tests/test_fts.py`

Rewrite `fts_rebuild.sql` to call `create_fts_collection` internally (via the Connection wrapper). Since `fts_rebuild.sql` is loaded as a raw SQL script by `connection.py:rebuild_fts()`, and the collection infrastructure is Python-side, we change `rebuild_fts()` to use `create_fts_collection('content', ...)` instead of loading the SQL file.

The existing `fts.content` schema is wide (id, file_path, start_line, end_line, extractor, kind, name, ordinal, attrs, text). The new collection schema is narrow (id, text, metadata). For `fts.content`, we keep the wide schema because `find_code_ranked`, `search_content`, and the MCP tools all depend on those columns. The collection-generic path (create_fts_collection) uses the narrow schema for new collections. The default `content` collection is a special case — `rebuild_fts` continues to use the wide `fts_rebuild.sql` script, but registers the rebuild in the catalog afterward.

- [ ] **Step 1: Write test for catalog registration after rebuild**

Append to `tests/test_fts_collections.py`:

```python
class TestContentCollectionCatalog:
    def test_rebuild_registers_content_in_catalog(self, fledgling_con):
        fledgling_con.rebuild_fts(
            docs_glob=PROJECT_ROOT + "/**/*.md",
            code_glob=PROJECT_ROOT + "/**/*.py",
        )
        row = fledgling_con.execute(
            "SELECT name, rebuilt_at FROM fts.collections WHERE name = 'content'"
        ).fetchone()
        assert row is not None
        assert row[0] == "content"
        assert row[1] is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/aux-data/teague/Projects/source-sextant/main && python -m pytest tests/test_fts_collections.py::TestContentCollectionCatalog -v`
Expected: FAIL — `rebuild_fts` doesn't register in catalog yet.

- [ ] **Step 3: Update rebuild_fts to register in catalog**

In `fledgling/connection.py`, modify the `rebuild_fts` method. After the line that calls `_load_sql_file(self._con, sql_dir / "fts_rebuild.sql")`, add:

```python
        self._con.execute(
            "INSERT OR REPLACE INTO fts.collections (name, created_at, rebuilt_at) "
            "VALUES ('content', current_timestamp, current_timestamp)"
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /mnt/aux-data/teague/Projects/source-sextant/main && python -m pytest tests/test_fts_collections.py::TestContentCollectionCatalog -v`
Expected: PASS

- [ ] **Step 5: Run full fts test suite to check for regressions**

Run: `cd /mnt/aux-data/teague/Projects/source-sextant/main && python -m pytest tests/test_fts.py tests/test_fts_collections.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd /mnt/aux-data/teague/Projects/source-sextant/main
git add fledgling/connection.py tests/test_fts_collections.py
git commit -m "feat(fts): register content collection in catalog after rebuild"
```

---

## Task 5: FtsCollection Class (Pluckit Python)

**Files:**
- Create: `src/pluckit/fts.py`
- Create: `tests/pluckins/test_fts_collection.py`

The `FtsCollection` class wraps fledgling's `create_fts_collection` and `search_collection` methods into a clean object API. It delegates to the fledgling Connection which must be available on the Plucker.

- [ ] **Step 1: Write failing test for FtsCollection**

Create `tests/pluckins/test_fts_collection.py`:

```python
"""Tests for FtsCollection — named BM25 collections via pluckit."""
from __future__ import annotations

import textwrap

import pytest

from pluckit import Plucker
from pluckit.pluckins.search import Search


def _fledgling_available():
    try:
        import fledgling
        return True
    except ImportError:
        return False


requires_fledgling = pytest.mark.skipif(
    not _fledgling_available(),
    reason="fledgling not installed",
)


@pytest.fixture
def pluck_with_fledgling(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "sample.py").write_text("def hello(): pass\n")
    p = Plucker(
        code=str(src / "**/*.py"),
        plugins=[Search],
        repo=str(tmp_path),
    )
    if not p._ctx._fledgling_loaded:
        pytest.skip("fledgling not loaded")
    return p


@requires_fledgling
class TestFtsCollection:
    def test_create_and_search(self, pluck_with_fledgling):
        col = pluck_with_fledgling.fts_collection("test_tools")
        col.create("""
            SELECT 'tool1' AS id, 'parse json configuration files' AS text,
                   map{'kit': 'stdlib'} AS metadata
            UNION ALL
            SELECT 'tool2', 'send http request to api endpoint',
                   map{'kit': 'network'}
            UNION ALL
            SELECT 'tool3', 'validate json schema against document',
                   map{'kit': 'stdlib'}
        """)
        results = col.search("json")
        assert len(results) >= 1
        ids = [r[0] for r in results]
        assert "tool1" in ids or "tool3" in ids

    def test_search_limit(self, pluck_with_fledgling):
        col = pluck_with_fledgling.fts_collection("limit_test")
        rows = " UNION ALL ".join(
            f"SELECT 'id{i}' AS id, 'common keyword repeated' AS text, map{{}} AS metadata"
            for i in range(20)
        )
        col.create(rows)
        results = col.search("common keyword", limit=3)
        assert len(results) <= 3

    def test_separate_collections_independent(self, pluck_with_fledgling):
        p = pluck_with_fledgling
        col_a = p.fts_collection("alpha")
        col_a.create("""
            SELECT 'a1' AS id, 'unique alpha content' AS text, map{} AS metadata
        """)
        col_b = p.fts_collection("beta")
        col_b.create("""
            SELECT 'b1' AS id, 'unique beta content' AS text, map{} AS metadata
        """)
        alpha_results = col_a.search("alpha")
        beta_results = col_b.search("beta")
        assert len(alpha_results) >= 1
        assert len(beta_results) >= 1
        alpha_ids = [r[0] for r in alpha_results]
        beta_ids = [r[0] for r in beta_results]
        assert "a1" in alpha_ids
        assert "b1" in beta_ids
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/pluckins/test_fts_collection.py -v`
Expected: FAIL — `fts_collection` method does not exist on Plucker, `FtsCollection` class does not exist.

- [ ] **Step 3: Create FtsCollection class**

Create `src/pluckit/fts.py`:

```python
"""Named FTS collection wrapper over fledgling's collection infrastructure."""
from __future__ import annotations


class FtsCollection:
    """A named BM25 full-text search collection.

    Wraps fledgling's ``create_fts_collection`` and ``search_collection``
    methods. Obtain via ``plucker.fts_collection("name")``.

    Example::

        col = plucker.fts_collection("tools")
        col.create(\"\"\"
            SELECT name AS id, description AS text,
                   map{'kit': kit_name} AS metadata
            FROM tool_inventory
        \"\"\")
        results = col.search("parse json", limit=10)
    """

    def __init__(self, con, name: str):
        self._con = con
        self.name = name

    def create(self, source_query: str) -> None:
        """Create or replace this collection from a source query.

        The source query must produce ``(id TEXT, text TEXT, metadata MAP(TEXT, TEXT))`` rows.
        """
        self._con.create_fts_collection(self.name, source_query)

    def search(self, query: str, limit: int = 20) -> list:
        """BM25 search this collection. Returns (id, text, metadata, score) rows."""
        return self._con.search_collection(self.name, query, limit=limit)
```

- [ ] **Step 4: Add fts_collection method to Plucker**

In `src/pluckit/plucker.py`, add an import and method. Find the `connection` property (around line 76) and add after it:

```python
    def fts_collection(self, name: str):
        """Get a named FTS collection handle.

        Requires fledgling. The returned object supports ``.create(query)``
        and ``.search(query)`` for building and querying BM25 indexes.
        """
        from pluckit.fts import FtsCollection
        con = self.connection
        if not hasattr(con, 'create_fts_collection'):
            from pluckit.types import PluckerError
            raise PluckerError(
                "Named FTS collections require fledgling. "
                "Install with: pip install fledgling-mcp"
            )
        return FtsCollection(con, name)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/pluckins/test_fts_collection.py -v`
Expected: PASS

- [ ] **Step 6: Run existing search tests to check for regressions**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/pluckins/test_search.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
cd /mnt/aux-data/teague/Projects/pluckit/main
git add src/pluckit/fts.py src/pluckit/plucker.py tests/pluckins/test_fts_collection.py
git commit -m "feat: add FtsCollection class for named BM25 collections"
```

---

## Task 6: Migrate Search Pluckin Internals (Pluckit)

**Files:**
- Modify: `src/pluckit/pluckins/search.py`
- Modify: `tests/pluckins/test_search.py`

Replace all hardcoded `fts_fts_content.match_bm25` references in the Search pluckin with calls to `search_collection('content', ...)` on the fledgling Connection. The public API (`.search()`, `.search_docs()`, `.search_code()`) is unchanged.

The `_search_plucker` and `_search_selection` methods currently build SQL strings with `fts_fts_content.match_bm25(c.id, query)`. These need to change to use the Connection's `search_collection` method, or to call the existing macros (`search_content`, `search_code`) which are still available and already use `fts_fts_content` internally.

Actually, the existing macros (`search_content`, `search_code`, `search_docs`) haven't changed — they still work. The Search pluckin's `search_docs` and `search_code` methods already delegate to these macros via the Connection's `__getattr__`. The only hardcoded references are in `_search_plucker` and `_search_selection`.

The cleanest migration: keep `_search_plucker` and `_search_selection` using the `fts_fts_content` accessor (it still exists, still works), but refactor the SQL to use the Connection's `search_collection` when available. This is a future optimization — for now, the hardcoded references work because the `content` collection always uses `fts.content` with `fts_fts_content` as its accessor.

Since the existing code works and the search macros haven't changed, we defer refactoring the internals and just verify everything passes.

- [ ] **Step 1: Run existing search pluckin tests**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/pluckins/test_search.py -v`
Expected: PASS — no changes needed, macros still use `fts_fts_content`.

- [ ] **Step 2: Add _assert_fts_index to also check catalog (optional hardening)**

In `src/pluckit/pluckins/search.py`, update `_assert_fts_index` to try the catalog first:

```python
def _assert_fts_index(db) -> None:
    """Check that fts.content exists and has rows."""
    try:
        count = db.sql("SELECT count(*) FROM fts.content").fetchone()[0]
    except Exception:
        raise PluckerError(
            "FTS index not found. Ensure fledgling is loaded with the 'fts' module "
            "and call rebuild_fts() before searching."
        )
    if count == 0:
        raise PluckerError(
            "FTS index is empty. Call rebuild_fts() to populate it."
        )
```

This doesn't change — the validation is still correct. No code change needed.

- [ ] **Step 3: Run all pluckit tests**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/ -v --timeout=120`
Expected: PASS

- [ ] **Step 4: Commit (if any changes were made)**

If no changes needed, skip this step. If `_assert_fts_index` was updated:

```bash
cd /mnt/aux-data/teague/Projects/pluckit/main
git add src/pluckit/pluckins/search.py
git commit -m "refactor: verify search pluckin compatible with collection infrastructure"
```

---

## Task 7: Integration Test — End-to-End Collection Flow

**Files:**
- Modify: `tests/pluckins/test_fts_collection.py` (pluckit)

Full end-to-end test: create a collection, search it, verify isolation from the default `content` collection.

- [ ] **Step 1: Write integration test**

Append to `tests/pluckins/test_fts_collection.py`:

```python
@requires_fledgling
class TestFtsCollectionIntegration:
    def test_custom_collection_isolated_from_content(self, pluck_with_fledgling):
        p = pluck_with_fledgling
        # Rebuild default FTS index
        p.rebuild_fts(
            docs_glob=str(p._ctx.repo) + "/**/*.md",
            code_glob=str(p._ctx.repo) + "/**/*.py",
        )
        # Create a custom collection with completely different content
        col = p.fts_collection("custom_tools")
        col.create("""
            SELECT 'mytool' AS id,
                   'xylophone_unique_term_not_in_code' AS text,
                   map{'source': 'test'} AS metadata
        """)
        # Search custom collection — should find our unique term
        results = col.search("xylophone_unique_term_not_in_code")
        assert len(results) == 1
        assert results[0][0] == "mytool"

        # Search default content collection — should NOT find our unique term
        default_results = p.connection.execute(
            "SELECT * FROM search_content('xylophone_unique_term_not_in_code')"
        ).fetchall()
        assert len(default_results) == 0

    def test_multiple_collections_different_idf(self, pluck_with_fledgling):
        p = pluck_with_fledgling
        # Collection where "function" is rare (tool descriptions)
        col_tools = p.fts_collection("tools_idf")
        col_tools.create("""
            SELECT '1' AS id, 'parse json files' AS text, map{} AS metadata
            UNION ALL SELECT '2', 'send network request', map{}
            UNION ALL SELECT '3', 'function to validate data', map{}
        """)
        # Collection where "function" is common (code)
        col_code = p.fts_collection("code_idf")
        col_code.create("""
            SELECT '1' AS id, 'function parse_json returns dict' AS text, map{} AS metadata
            UNION ALL SELECT '2', 'function send_request returns response' AS text, map{}
            UNION ALL SELECT '3', 'function validate_data checks schema' AS text, map{}
        """)
        # "function" should score higher in tools (rare) than code (common)
        tool_results = col_tools.search("function")
        code_results = col_code.search("function")
        # Both should find results
        assert len(tool_results) >= 1
        assert len(code_results) >= 1
```

- [ ] **Step 2: Run integration tests**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/pluckins/test_fts_collection.py::TestFtsCollectionIntegration -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
cd /mnt/aux-data/teague/Projects/pluckit/main
git add tests/pluckins/test_fts_collection.py
git commit -m "test: end-to-end FTS collection isolation and IDF independence"
```

---

## Task 8: Verify MCP Tool Surface Unchanged (Fledgling)

**Files:**
- No new files — read-only verification

Ensure the MCP tools (SearchContent, SearchDocs, SearchCode, FtsStats) still work after all changes.

- [ ] **Step 1: Run MCP server tests**

Run: `cd /mnt/aux-data/teague/Projects/source-sextant/main && python -m pytest tests/test_mcp_server.py -v -k "fts or search or Search"`
Expected: PASS (or skip if no FTS-specific MCP tests exist)

- [ ] **Step 2: Run the full fledgling test suite**

Run: `cd /mnt/aux-data/teague/Projects/source-sextant/main && python -m pytest tests/ -v --timeout=120`
Expected: PASS

- [ ] **Step 3: Run the full pluckit test suite**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest tests/ -v --timeout=120`
Expected: PASS

- [ ] **Step 4: No commit needed — verification only**

---

## Summary

| Task | What | Where | Risk |
|------|------|-------|------|
| 1 | Catalog table in fts.sql | fledgling | Low |
| 2 | `create_fts_collection` method | fledgling | Low |
| 3 | `search_collection` method | fledgling | Low |
| 4 | Register content in catalog after rebuild | fledgling | Low |
| 5 | `FtsCollection` class + `plucker.fts_collection()` | pluckit | Low |
| 6 | Verify Search pluckin compatibility | pluckit | Low |
| 7 | End-to-end integration tests | pluckit | Low |
| 8 | Full regression verification | both | None |

Total: 8 tasks, fledgling-first (1-4) then pluckit (5-7) then verification (8). Quartermaster migration (lackpy) is deferred to a follow-up since it's an experimental script — the infrastructure is ready for it after Task 7.
