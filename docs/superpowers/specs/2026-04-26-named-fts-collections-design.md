# Named FTS Collections

## Problem

Fledgling has a single hardcoded `fts.content` table with one BM25 index.
All content types (code, docs, comments, strings) share one inverted index,
so IDF statistics are distorted -- "function" is common in code but
distinctive in tool descriptions. Search macros filter by `kind`/`extractor`
after scoring, wasting computation and returning scores that don't reflect
per-domain term importance.

Quartermaster needs its own BM25 index over tool descriptions. Today it
builds a standalone index outside fledgling, duplicating BM25 infrastructure.

## Design

Two SQL primitives in fledgling, a Python convenience class in pluckit.

**Implementation note:** DuckDB macros can't execute DDL or resolve
dynamic table names. `create_fts_collection` is implemented as a
parameterized SQL script (template with string substitution, like the
existing `fts_rebuild.sql`). `search_collection` is similarly a
parameterized query template. Pluckit's `FtsCollection` class handles the
substitution and execution -- the "macro" interface is the Python method,
not a literal DuckDB macro.

### Fledgling SQL layer

**Catalog table** in the `fts` schema:

```sql
CREATE TABLE IF NOT EXISTS fts.collections (
    name       TEXT PRIMARY KEY,
    created_at TIMESTAMP DEFAULT current_timestamp,
    rebuilt_at TIMESTAMP
);
```

**`create_fts_collection(name, source_query)`** -- idempotent, always
replaces:

1. `DROP TABLE IF EXISTS fts.<name>`
2. `CREATE TABLE fts.<name> (id TEXT, text TEXT, metadata MAP(TEXT, TEXT))`
3. `INSERT INTO fts.<name> SELECT * FROM (<source_query>)`
4. `PRAGMA create_fts_index('fts.<name>', 'id', 'text', overwrite=1)`
5. Upsert catalog row with current timestamp as `rebuilt_at`

The source query must produce `(id TEXT, text TEXT, metadata MAP(TEXT, TEXT))`.

**`search_collection(name, query, limit=20)`** -- BM25 search:

1. Resolve the DuckDB-generated accessor: `fts_fts_<name>.match_bm25()`
2. Join `fts.<name>` with the BM25 scores
3. Return `(id, text, metadata, score)` ordered by score, limited

**Existing macros migrated:**

- `fts_rebuild.sql` calls `create_fts_collection('content', '<union-all>')` 
  instead of manually creating and populating `fts.content`
- `search_content(query, kind, extractor)` becomes a thin wrapper:
  `search_collection('content', query)` with metadata filtering on
  `metadata['kind']` and `metadata['extractor']`
- `search_docs`, `search_code`, `find_code_ranked` similarly wrap
  `search_collection` with appropriate metadata filters
- `fts_stats` extended to report per-collection statistics

**MCP tool surface unchanged.** `SearchContent`, `SearchDocs`, `SearchCode`,
`FtsStats` continue to work as before -- they call the migrated macros.

### Pluckit Python layer

**`FtsCollection` class:**

```python
class FtsCollection:
    def __init__(self, con, name):
        self.con = con
        self.name = name

    def create(self, source_query):
        self.con.execute(
            "SELECT create_fts_collection(?, ?)",
            [self.name, source_query],
        )

    def search(self, query, limit=20):
        return self.con.execute(
            "SELECT * FROM search_collection(?, ?, ?)",
            [self.name, query, limit],
        ).fetchall()
```

**Connection convenience:**

```python
def fts_collection(self, name) -> FtsCollection:
    return FtsCollection(self, name)
```

**Search pluckin migration:** Replace all hardcoded `fts_fts_content.match_bm25`
references with calls to `search_collection('content', ...)`.

### Consumers

**Quartermaster** replaces its standalone BM25 index:

```python
col = con.fts_collection("tools")
col.create("""
    SELECT name AS id, description AS text,
           map{'kit': kit_name} AS metadata
    FROM tool_inventory
""")
results = col.search("parse json config", limit=10)
```

**Kibitzer** -- no changes. Continues to suggest search tools to agents.

## Fixed table schema

Every collection uses the same three columns:

| Column   | Type              | Purpose                        |
|----------|-------------------|--------------------------------|
| id       | TEXT              | Unique key within collection   |
| text     | TEXT              | BM25-indexed content           |
| metadata | MAP(TEXT, TEXT)    | Consumer-defined attributes    |

BM25 always indexes `text`. Consumers use `metadata` for post-score
filtering (e.g., `metadata['kind'] = 'code'`).

## Migration plan

| Layer | Change | Notes |
|-------|--------|-------|
| Fledgling SQL | Add `create_fts_collection`, `search_collection` macros + catalog table | Additive |
| Fledgling SQL | Rewrite `fts_rebuild.sql` to use `create_fts_collection` | Breaking -- expected |
| Fledgling SQL | Rewrite search macros to wrap `search_collection` | Breaking -- expected |
| Pluckit | Add `FtsCollection` class + `Connection.fts_collection()` | Additive |
| Pluckit | Migrate Search pluckin internals | Breaking -- expected |
| Quartermaster | Replace standalone BM25 with `fts_collection("tools")` | Cleanup |
| Kibitzer | None | -- |
| MCP tools | None -- same published surface | -- |

No backward-compatibility shims. Fledgling is a local tool; users
upgrading rebuild their indexes on first use.

## Scope boundary

This design covers the infrastructure for N collections. It does not cover:

- Deciding which collections to create beyond `content` and `tools`
- Agent Riggs intent-to-selector mapping collection (future)
- Cross-collection search or federated ranking
