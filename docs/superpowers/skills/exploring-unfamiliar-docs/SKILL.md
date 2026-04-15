---
name: exploring-unfamiliar-docs
description: Use when you need to understand or summarize a corpus of markdown documentation you don't already have in context — project docs, a blog, a wiki dump. Teaches progressive disclosure via doc_outline + read_doc_section instead of reading every file.
---

# Exploring Unfamiliar Docs

## Overview

Agents default to reading every file when handed a doc corpus. On a 500-page blog or a project's full docs tree, that's hundreds of KB of content for a question you can answer from ~5 pages.

Squackit's `doc_outline` and `read_doc_section` tools let you walk the structure first, narrow by pattern or keyword, and only read the sections you actually need.

**Core principle:** read spines before chapters. The table of contents is almost free; the content isn't.

## When to use

Use this pattern when:
- You're answering a question about docs you haven't seen before
- The corpus is larger than ~5 files
- You want progressive disclosure (see shape → narrow → read)
- The docs are markdown (the tools parse heading hierarchy)

Don't use this pattern when:
- The corpus is 1-3 files → just Read them
- The docs are not markdown → doc_outline won't parse them
- You need full-text search across all content → use `search` workflow or Grep
- You already have the sections in context

## The three-step workflow

### Step 1: See the shape

Start with top-level headings only. Gives you the table of contents.

```
doc_outline(file_pattern="/path/to/docs/**/*.md", max_lvl=1)
```

Returns post/chapter titles. Read them. Identify:
- Is there a series? (numbered prefixes, related titles)
- Which posts/pages match the user's question?
- Which subdirectories look like the right neighborhood?

**Watch for silent truncation.** `doc_outline` truncates to ~50 rows by default and shows `--- omitted N of M rows ---`. If you see this on Step 1, the table of contents is incomplete. Two ways to handle:

```
# A) Raise max_results (use this when you want one global TOC)
doc_outline(file_pattern=".../**/*.md", max_lvl=1, max_results=500)

# B) Outline subdirectories one at a time (use this when the corpus
#    has a clear directory structure — usually faster + more focused)
doc_outline(file_pattern=".../guides/**/*.md", max_lvl=1)
doc_outline(file_pattern=".../reference/**/*.md", max_lvl=1)
```

For corpora over ~15 files with clear subdirectory grouping, **prefer B** — you can stop drilling as soon as you find the relevant area.

### Step 2: Narrow by keyword or subdirectory

Once you know where to look, drill in with `search` or a tighter pattern:

```
# By keyword — returns only sections whose title or path contains the term
doc_outline(file_pattern="/path/to/docs/**/*.md", search="authentication", max_lvl=2)

# By subdirectory — the neighborhood you identified in Step 1
doc_outline(file_pattern="/path/to/docs/guides/**/*.md", max_lvl=2)
```

Now you have a list of specific sections with file paths, section IDs, and line ranges.

### Step 3: Read the section

Pick the most relevant section and read just that:

```
read_doc_section(
    file_path="/path/to/docs/guides/auth-setup.md",
    target_id="oauth-flow"
)
```

Returns the section body. Usually 1-5KB vs the 50+ KB of reading the whole file.

**Never guess `target_id`.** The IDs are slug-form (`my-section-title` from `## My Section Title`) but slugification rules vary — underscores, punctuation, capitalization can trip you up. Always run `doc_outline` on the file first to get the exact ID, even if you already know the path.

```
# ❌ Don't guess
read_doc_section(file_path="...", target_id="css_selectors_for_code")  # may fail silently

# ✅ Outline first
doc_outline(file_pattern="/exact/file/path.md")
# → copy the section_id from the output
read_doc_section(file_path="...", target_id="css-selectors-for-code")
```

**When a section is huge.** If `read_doc_section` returns a multi-tens-of-KB body, the MCP layer may spill to disk and only show you a preview. That's fine for discovery but means the section is too coarse to grab whole. Re-outline with `max_lvl=3` (or higher) on that file to find sub-sections, then read those.

## Decision rules

**When to use `doc_outline` search vs `search` workflow:**
- `doc_outline search="X"` — filters sections by heading/path match. Fast, structured.
- `search(query="X")` workflow — multi-source (code + docs + git + conversations). Broader.

Use `doc_outline search` when the term is likely to appear in a heading. Use `search` workflow when the term could be anywhere (body text, code identifiers).

**When to read the whole file after all:**
- The file is short (under ~100 lines)
- You need continuous flow across sections (e.g., a narrative essay)
- `read_doc_section` returns truncated/flattened output for a critical section

## Anti-patterns

**Don't Read the corpus.**
```
❌ Read(each_file) for 61 blog posts
✅ doc_outline(max_lvl=1) → read the 3 that matter
```

**Don't skip the outline.**
Even if you think you know which file has the answer, `doc_outline` gives you section IDs so you can target `read_doc_section` precisely. Reading a 500-line file to find one heading is wasteful.

**Don't use Grep for structured questions.**
```
❌ Grep("oauth") → matching lines, no hierarchy
✅ doc_outline(search="oauth") → matching sections with their titles and paths
```
Grep is right when you need the raw string match (e.g., a specific error message). `doc_outline` is right when the question is structural ("which section covers oauth?").

## Example: "What does this blog say about X?"

```
# Step 1: See the shape
doc_outline(file_pattern="~/Projects/mysite/blog/**/*.md", max_lvl=1)
# → 61 post titles. Two look relevant.

# Step 2: Narrow
doc_outline(file_pattern="~/Projects/mysite/blog/**/*.md", search="X", max_lvl=2)
# → 8 matching sections across 3 files.

# Step 3: Read the best match
read_doc_section(file_path="...", target_id="the-X-problem")
# → 2KB, has the answer.
```

Three tool calls. ~10KB total context. vs Reading 500KB to answer the same question.

## Output shape notes

- `doc_outline` returns a table with `file_path`, `section_id`, `section_path`, `level`, `title`, `start_line`, `end_line`
- `doc_outline` truncates by default (~50 rows) — use `max_results` to raise the cap, or pre-narrow the pattern
- `read_doc_section` returns the section body as plain text (flattens some markdown like code fences — acceptable for summary/extraction, but re-Read the file if exact formatting matters)
- `read_doc_section` may spill very large bodies (50KB+) to disk and only return a preview — re-outline at higher `max_lvl` and read sub-sections instead
- Both tools cache results (session lifetime). If files change between calls and you see a `(cached — same as Ns ago)` prefix, the answer is from before the change — re-Read the file or restart the session if freshness matters
