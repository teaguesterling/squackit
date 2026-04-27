# Kibitzer FTS Doc Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Kibitzer's ILIKE substring doc search with BM25 via named FTS collections.

**Architecture:** When `register_docs()` is called with tool doc references, Kibitzer builds a named FTS collection (`docs_<namespace>`) from the markdown sections. `_retrieve_doc_sections()` then uses `col.search(query)` instead of the current ILIKE word-splitting hack. The FTS collection is built lazily on first retrieval and cached on the session for the session's lifetime.

**Tech Stack:** kibitzer, pluckit (Plucker + FtsCollection), fledgling (BM25 via DuckDB FTS extension)

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/kibitzer/session.py:518-550` | Modify | Replace `_retrieve_doc_sections` ILIKE logic with FTS collection search |
| `src/kibitzer/session.py:436-453` | Modify | In `register_docs`, store Plucker instance for lazy FTS build |
| `tests/test_docs.py` | Modify | Update/add tests for BM25-backed doc retrieval |

All paths relative to `/mnt/aux-data/teague/Projects/kibitzer`.

## Design Decisions

**Why lazy FTS build (not eager at `register_docs` time):**
`register_docs` is called during session `load()` from config. Building an FTS collection requires reading and parsing all markdown files — too expensive for session init. Instead, build on first `_retrieve_doc_sections` call and cache the Plucker + collection on the session.

**Why one Plucker per namespace (not per `get_doc_context` call):**
The current code creates a fresh `Plucker(docs=...)` on every `_retrieve_doc_sections` call. That re-parses all markdown every time. Caching the Plucker (and its FTS collection) on the session avoids this.

**Schema mapping:**
Tool doc markdown sections → FTS collection rows:
- `id`: `{file_path}:{start_line}` (unique section identifier)
- `text`: `{title}\n{content}` (searchable text)
- `metadata`: `map{'file_path': ..., 'title': ..., 'tool': ...}` (for filtering and presentation)

**Tool filtering:**
The current code narrows by `file_path` when a `tool` parameter is given. With FTS collections, we search the full collection and filter results by the metadata `tool` field, or include the tool name in the query to let BM25 rank tool-specific sections higher. Since the collection is small (tool docs, not the full codebase), post-filtering is fine.

---

### Task 1: Build FTS collection from registered docs

Replace the per-call `Plucker(docs=...)` pattern with a cached Plucker + FTS collection that's built lazily on first retrieval.

**Files:**
- Modify: `src/kibitzer/session.py:436-550`
- Test: `tests/test_docs.py`

**Context:** `_retrieve_doc_sections` (line 518) currently creates a fresh `Plucker(docs=f"{docs_root}/**/*.md")` on every call, runs ILIKE filters, and returns `DocSection` objects. `register_docs` (line 436) stores `doc_refs`, `docs_root`, and `refinement` in `self._doc_registry[ns]`. We'll add a `_plucker` and `_fts_col` cache to the registry entry, built lazily.

- [ ] **Step 1: Write failing test for FTS-based doc retrieval**

Add a test that verifies BM25 ranking produces results for a multi-word query (the exact scenario where ILIKE falls down):

```python
# In tests/test_docs.py, add to TestGetDocContext class:

def test_multiword_query_finds_results(self, tmp_path):
    """BM25 handles multi-word queries without the ILIKE word-splitting hack."""
    proj = _project(tmp_path)
    doc_refs = _write_tool_docs(tmp_path)
    with KibitzerSession(project_dir=proj) as session:
        session.register_docs(doc_refs, docs_root=str(tmp_path))
        result = session.get_doc_context("read file path")
        assert len(result.sections) > 0
        # BM25 should rank read_file docs higher than edit_file
        files = [s.file_path for s in result.sections]
        read_idx = next(
            (i for i, f in enumerate(files) if "read_file" in f), len(files)
        )
        edit_idx = next(
            (i for i, f in enumerate(files) if "edit_file" in f), len(files)
        )
        assert read_idx < edit_idx
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/aux-data/teague/Projects/kibitzer && python -m pytest tests/test_docs.py::TestGetDocContext::test_multiword_query_finds_results -xvs`

Expected: May pass with current ILIKE (depending on word matching) or fail with wrong ranking. Either way, we're about to replace the implementation.

- [ ] **Step 3: Replace `_retrieve_doc_sections` with FTS collection search**

Replace the method at `session.py:518` with:

```python
def _retrieve_doc_sections(self, query, registry, tool=None):
    from kibitzer.docs import DocSection
    try:
        from pluckit import Plucker
    except ImportError:
        return []

    docs_root = registry.get("root")
    if not docs_root:
        return []

    # Lazy-build Plucker + FTS collection, cached on registry dict
    plucker = registry.get("_plucker")
    if plucker is None:
        try:
            plucker = Plucker(
                docs=f"{docs_root}/**/*.md",
                profile="analyst",
            )
            registry["_plucker"] = plucker
        except Exception:
            return []

    col = registry.get("_fts_col")
    if col is None:
        try:
            col = self._build_doc_collection(plucker, registry)
            registry["_fts_col"] = col
        except Exception:
            return []

    # Search with BM25
    try:
        search_query = query
        if tool:
            search_query = f"{tool} {query}"
        results = col.search(search_query, limit=20)
    except Exception:
        return []

    sections = []
    refs = registry.get("refs", {})
    for id_val, text, metadata, score in results:
        file_path = metadata.get("file_path", "")
        section_tool = metadata.get("tool")

        # Filter by tool if specified
        if tool and section_tool and section_tool != tool:
            doc_path = refs.get(tool)
            if doc_path and doc_path not in file_path:
                continue

        title = metadata.get("title", "")
        content = text
        if title and content.startswith(title):
            content = content[len(title):].lstrip("\n")

        sections.append(DocSection(
            title=title,
            content=content,
            file_path=file_path,
            level=int(metadata.get("level", "1")),
            tool=section_tool,
        ))
    return sections
```

- [ ] **Step 4: Add `_build_doc_collection` helper method**

Add this method to `KibitzerSession` (after `_retrieve_doc_sections`):

```python
def _build_doc_collection(self, plucker, registry):
    """Build an FTS collection from registered doc markdown files."""
    docs_root = registry["root"]
    refs = registry.get("refs", {})

    # Build reverse map: file_path -> tool name
    tool_for_file = {}
    for tool_name, rel_path in refs.items():
        if rel_path:
            tool_for_file[rel_path] = tool_name

    # Read all markdown sections via pluckit
    docs = plucker.docs()
    raw_sections = docs.sections()

    if not raw_sections:
        raise ValueError("No doc sections found")

    # Build source query for the FTS collection
    # Each section becomes a row: (id, text, metadata)
    rows = []
    for s in raw_sections:
        file_path = str(s.get("file_path", ""))
        title = str(s.get("title", ""))
        content = str(s.get("content", ""))
        level = s.get("level", 1)
        start_line = s.get("start_line", 0)

        # Match file to tool via refs
        tool_name = ""
        for ref_path, t_name in tool_for_file.items():
            if ref_path in file_path:
                tool_name = t_name
                break

        sec_id = f"{file_path}:{start_line}"
        text = f"{title}\n{content}" if content else title
        rows.append((sec_id, text, file_path, title, tool_name, str(level)))

    col = plucker.fts_collection("kibitzer_docs")

    # Build a UNION ALL query from the rows
    union_parts = []
    for sec_id, text, fp, title, tool_name, level in rows:
        esc = lambda s: s.replace("'", "''")
        union_parts.append(
            f"SELECT '{esc(sec_id)}' AS id, "
            f"'{esc(text)}' AS text, "
            f"map{{'file_path': '{esc(fp)}', 'title': '{esc(title)}', "
            f"'tool': '{esc(tool_name)}', 'level': '{esc(level)}'}} AS metadata"
        )

    source_query = " UNION ALL ".join(union_parts)
    col.create(source_query)
    return col
```

- [ ] **Step 5: Run existing tests**

Run: `cd /mnt/aux-data/teague/Projects/kibitzer && python -m pytest tests/test_docs.py -xvs`

Expected: All existing tests pass. The pipeline (`get_doc_context` → `_retrieve_doc_sections` → refinement callbacks) is unchanged — only the retrieval implementation changed.

- [ ] **Step 6: Commit**

```bash
cd /mnt/aux-data/teague/Projects/kibitzer
git add src/kibitzer/session.py tests/test_docs.py
git commit -m "feat: replace ILIKE doc search with BM25 via FTS collections

_retrieve_doc_sections now builds a named FTS collection from
registered tool doc markdown sections and uses BM25 ranking
instead of ILIKE substring matching. The Plucker and collection
are lazily built and cached on the session."
```

---

### Task 2: Handle edge cases and fallback

The FTS collection requires fledgling. When fledgling isn't available (pluckit installed without fledgling), `plucker.fts_collection()` raises `PluckerError`. We need graceful fallback to the old ILIKE approach so kibitzer doesn't break for users without fledgling.

**Files:**
- Modify: `src/kibitzer/session.py`
- Test: `tests/test_docs.py`

- [ ] **Step 1: Write test for graceful fallback without fledgling**

```python
# In tests/test_docs.py, add:

def test_retrieval_works_without_fledgling(self, tmp_path):
    """When FTS collection build fails, falls back to ILIKE search."""
    proj = _project(tmp_path)
    doc_refs = _write_tool_docs(tmp_path)
    from unittest.mock import patch

    with KibitzerSession(project_dir=proj) as session:
        session.register_docs(doc_refs, docs_root=str(tmp_path))
        # Force FTS collection build to fail
        with patch.object(
            session, "_build_doc_collection", side_effect=Exception("no fledgling")
        ):
            result = session.get_doc_context("read_file")
            # Should still find results via ILIKE fallback
            assert len(result.sections) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /mnt/aux-data/teague/Projects/kibitzer && python -m pytest tests/test_docs.py::TestGetDocContext::test_retrieval_works_without_fledgling -xvs`

Expected: FAIL — currently the exception propagates and returns `[]`.

- [ ] **Step 3: Add ILIKE fallback to `_retrieve_doc_sections`**

Update the FTS collection section of `_retrieve_doc_sections` to fall back on failure:

```python
def _retrieve_doc_sections(self, query, registry, tool=None):
    from kibitzer.docs import DocSection
    try:
        from pluckit import Plucker
    except ImportError:
        return []

    docs_root = registry.get("root")
    if not docs_root:
        return []

    # Lazy-build Plucker, cached on registry dict
    plucker = registry.get("_plucker")
    if plucker is None:
        try:
            plucker = Plucker(
                docs=f"{docs_root}/**/*.md",
                profile="analyst",
            )
            registry["_plucker"] = plucker
        except Exception:
            return []

    # Try FTS collection first (BM25 ranking)
    col = registry.get("_fts_col")
    if col is None and not registry.get("_fts_failed"):
        try:
            col = self._build_doc_collection(plucker, registry)
            registry["_fts_col"] = col
        except Exception:
            registry["_fts_failed"] = True

    if col is not None:
        try:
            return self._search_fts_collection(col, query, tool, registry)
        except Exception:
            pass

    # Fallback: ILIKE via DocSelection
    return self._retrieve_doc_sections_ilike(plucker, query, tool, registry)
```

- [ ] **Step 4: Extract ILIKE fallback method**

```python
def _retrieve_doc_sections_ilike(self, plucker, query, tool, registry):
    """Fallback doc retrieval using ILIKE substring matching."""
    from kibitzer.docs import DocSection
    try:
        docs = plucker.docs()

        if tool:
            doc_path = registry["refs"].get(tool)
            if doc_path:
                docs = docs.filter(file_path=doc_path)

        if query:
            words = query.split()
            if len(words) == 1:
                docs = docs.filter(search=words[0])
            else:
                full = docs.filter(search=query)
                if full.sections():
                    docs = full
                else:
                    longest = max(words, key=len)
                    docs = docs.filter(search=longest)

        raw_sections = docs.sections()
    except Exception:
        return []

    return [
        DocSection(
            title=s.get("title", ""),
            content=str(s.get("content", "")),
            file_path=s.get("file_path", ""),
            level=s.get("level", 1),
            tool=tool,
        )
        for s in raw_sections
    ]
```

- [ ] **Step 5: Extract FTS search method**

```python
def _search_fts_collection(self, col, query, tool, registry):
    """Search the FTS collection and return DocSection list."""
    from kibitzer.docs import DocSection

    search_query = f"{tool} {query}" if tool else query
    results = col.search(search_query, limit=20)

    sections = []
    refs = registry.get("refs", {})
    for id_val, text, metadata, score in results:
        file_path = metadata.get("file_path", "")
        section_tool = metadata.get("tool")

        if tool and section_tool and section_tool != tool:
            doc_path = refs.get(tool)
            if doc_path and doc_path not in file_path:
                continue

        title = metadata.get("title", "")
        content = text
        if title and content.startswith(title):
            content = content[len(title):].lstrip("\n")

        sections.append(DocSection(
            title=title,
            content=content,
            file_path=file_path,
            level=int(metadata.get("level", "1")),
            tool=section_tool,
        ))
    return sections
```

- [ ] **Step 6: Run all tests**

Run: `cd /mnt/aux-data/teague/Projects/kibitzer && python -m pytest tests/test_docs.py -xvs`

Expected: All tests pass, including the new fallback test.

- [ ] **Step 7: Commit**

```bash
cd /mnt/aux-data/teague/Projects/kibitzer
git add src/kibitzer/session.py tests/test_docs.py
git commit -m "feat: add ILIKE fallback when FTS collection build fails

When fledgling is unavailable or FTS collection build fails,
_retrieve_doc_sections falls back to the original ILIKE
substring matching. The _fts_failed flag prevents retrying
on every call."
```

---

### Task 3: Test BM25 ranking quality

Verify that BM25 actually improves retrieval quality over ILIKE for the scenarios that matter to kibitzer: error correction with multi-word queries, tool-scoped lookups, and failure-mode-driven doc context.

**Files:**
- Test: `tests/test_docs.py`

- [ ] **Step 1: Write ranking quality tests**

```python
# Add a new test class in tests/test_docs.py:

def _has_fledgling():
    try:
        import fledgling
        return True
    except ImportError:
        return False


@pytest.mark.skipif(
    not (_has_pluckit() and _has_fledgling()),
    reason="pluckit + fledgling required for BM25 tests",
)
class TestBm25DocRetrieval:
    """Tests that specifically exercise BM25 ranking over ILIKE."""

    def _write_varied_docs(self, root):
        """Create docs with overlapping vocabulary to test ranking."""
        docs_dir = root / "docs" / "tools"
        docs_dir.mkdir(parents=True)
        (docs_dir / "read_file.md").write_text(
            "# read_file\n\n"
            "Read a file from the workspace.\n\n"
            "## Parameters\n\n"
            "- **path**: The file path to read. Must be relative.\n\n"
            "## Notes\n\n"
            "Raises FileNotFoundError if the path does not exist.\n"
            "Returns the full file content as a string.\n"
        )
        (docs_dir / "edit_file.md").write_text(
            "# edit_file\n\n"
            "Replace text in a file.\n\n"
            "## Parameters\n\n"
            "- **path**: The file path to edit.\n"
            "- **old_str**: The text to find in the file.\n"
            "- **new_str**: The replacement text.\n\n"
            "## Notes\n\n"
            "The old_str must appear exactly once in the file.\n"
            "Returns True on success.\n"
        )
        (docs_dir / "list_files.md").write_text(
            "# list_files\n\n"
            "List files in a directory.\n\n"
            "## Parameters\n\n"
            "- **directory**: The directory path to list.\n"
            "- **recursive**: Whether to list recursively (default: false).\n\n"
            "## Notes\n\n"
            "Returns a list of file paths relative to the workspace.\n"
        )
        return {
            "read_file": "docs/tools/read_file.md",
            "edit_file": "docs/tools/edit_file.md",
            "list_files": "docs/tools/list_files.md",
        }

    def test_bm25_ranks_specific_tool_higher(self, tmp_path):
        """BM25 should rank 'read_file' docs higher for 'read file path'."""
        proj = _project(tmp_path)
        doc_refs = self._write_varied_docs(tmp_path)
        with KibitzerSession(project_dir=proj) as session:
            session.register_docs(doc_refs, docs_root=str(tmp_path))
            result = session.get_doc_context("read file path")
            assert len(result.sections) > 0
            first_file = result.sections[0].file_path
            assert "read_file" in first_file

    def test_bm25_multiword_no_degradation(self, tmp_path):
        """Multi-word queries should return results (ILIKE splits words)."""
        proj = _project(tmp_path)
        doc_refs = self._write_varied_docs(tmp_path)
        with KibitzerSession(project_dir=proj) as session:
            session.register_docs(doc_refs, docs_root=str(tmp_path))
            result = session.get_doc_context("file not found error")
            assert len(result.sections) > 0

    def test_tool_filter_with_bm25(self, tmp_path):
        """Tool filter narrows to tool-specific docs."""
        proj = _project(tmp_path)
        doc_refs = self._write_varied_docs(tmp_path)
        with KibitzerSession(project_dir=proj) as session:
            session.register_docs(doc_refs, docs_root=str(tmp_path))
            result = session.get_doc_context(
                "parameters", tool="edit_file",
            )
            for s in result.sections:
                assert "edit_file" in s.file_path

    def test_correction_hints_use_bm25(self, tmp_path):
        """get_correction_hints should benefit from BM25 ranking."""
        proj = _project(tmp_path)
        doc_refs = self._write_varied_docs(tmp_path)
        with KibitzerSession(project_dir=proj) as session:
            session.register_docs(doc_refs, docs_root=str(tmp_path))
            signal = session.get_correction_hints(
                failure_mode="stdlib_leak",
                tool="read_file",
            )
            doc_context = signal.get("doc_context", [])
            assert len(doc_context) > 0
            files = [d["file"] for d in doc_context]
            assert any("read_file" in f for f in files)
```

- [ ] **Step 2: Run BM25 tests**

Run: `cd /mnt/aux-data/teague/Projects/kibitzer && python -m pytest tests/test_docs.py::TestBm25DocRetrieval -xvs`

Expected: All pass.

- [ ] **Step 3: Run full test suite**

Run: `cd /mnt/aux-data/teague/Projects/kibitzer && python -m pytest tests/ -x --timeout=30`

Expected: All tests pass. No regressions in non-doc tests.

- [ ] **Step 4: Commit**

```bash
cd /mnt/aux-data/teague/Projects/kibitzer
git add tests/test_docs.py
git commit -m "test: add BM25 ranking quality tests for doc retrieval"
```

---

### Task 4: Clean up Plucker construction

The `Plucker(profile="analyst")` constructor requires fledgling. When kibitzer is installed without fledgling (pluckit-only), the `profile` arg will fail. The Plucker should be constructed without `profile` in the fallback path, and with appropriate fledgling modules when available.

**Files:**
- Modify: `src/kibitzer/session.py`
- Test: `tests/test_docs.py`

- [ ] **Step 1: Write test for Plucker construction without profile**

```python
# In TestGetDocContext:

def test_works_with_pluckit_only(self, tmp_path):
    """Doc retrieval works when fledgling is not installed."""
    proj = _project(tmp_path)
    doc_refs = _write_tool_docs(tmp_path)
    from unittest.mock import patch
    import pluckit.plucker as pmod

    orig_init = pmod.Plucker.__init__

    def reject_profile(self_inner, *args, profile=None, **kwargs):
        if profile is not None:
            raise TypeError("profile requires fledgling")
        return orig_init(self_inner, *args, **kwargs)

    with KibitzerSession(project_dir=proj) as session:
        session.register_docs(doc_refs, docs_root=str(tmp_path))
        with patch.object(pmod.Plucker, "__init__", reject_profile):
            result = session.get_doc_context("read_file")
            assert len(result.sections) > 0
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /mnt/aux-data/teague/Projects/kibitzer && python -m pytest tests/test_docs.py::TestGetDocContext::test_works_with_pluckit_only -xvs`

Expected: FAIL — profile kwarg causes error.

- [ ] **Step 3: Fix Plucker construction to try profile, fall back without**

Update the Plucker construction in `_retrieve_doc_sections`:

```python
# Replace the Plucker construction block:
if plucker is None:
    try:
        plucker = Plucker(
            docs=f"{docs_root}/**/*.md",
            profile="analyst",
        )
    except Exception:
        try:
            plucker = Plucker(docs=f"{docs_root}/**/*.md")
        except Exception:
            return []
    registry["_plucker"] = plucker
```

- [ ] **Step 4: Run tests**

Run: `cd /mnt/aux-data/teague/Projects/kibitzer && python -m pytest tests/test_docs.py -xvs`

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
cd /mnt/aux-data/teague/Projects/kibitzer
git add src/kibitzer/session.py tests/test_docs.py
git commit -m "fix: Plucker construction falls back when profile unavailable"
```

---

## Summary

| Task | What | Risk |
|------|------|------|
| 1 | Core replacement: ILIKE → BM25 FTS collection | Medium — changes retrieval behavior |
| 2 | Graceful fallback when FTS unavailable | Low — defensive code |
| 3 | BM25 ranking quality tests | Low — tests only |
| 4 | Plucker construction robustness | Low — defensive code |

All changes are in the kibitzer repo. No changes needed in pluckit or fledgling — the named FTS collections infrastructure is already in place.
