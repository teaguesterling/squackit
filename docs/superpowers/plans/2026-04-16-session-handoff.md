# Session Handoff: squackit — Lackpy Kit Curation

## What happened across these two sessions

### Session 1 (2026-04-12 → 2026-04-14)
- v0.3.0: Click CLI (`squackit mcp serve`, `squackit tool`, `--json`, tab completion)
- v0.3.0: ToolPresentation refactor (replaced 8 scattered dicts)
- v0.3.1: Pluckit tool integration (view, find, find_names, complexity)
- v0.3.2: `squackit pluck` CLI + tool namespace cleanup (46 → 20 tools)
- v0.3.3: `pluck` MCP tool + documentation refresh
- v0.4.0: Mutation safety + pluckin tool discovery (`squackit_tools()`)
- v0.4.1: Search workflow fix (382KB → 10KB)
- Pluckit: Selection dunders, View.relation, parent tracking
- Pluckit: `plugins` → `pluckins` package rename
- Filed: 4 pluckit issues, 3 duck_tails issues

### Session 2 (2026-04-14 → 2026-04-16)
- MCP stress test: all 34 tools verified, 4 bugs found and filed
- 5 superpowers skills written and dogfood-validated
- Agent system prompt for Claude-sized agents
- Truncation added to executor-based tools
- Lackpy integration: SquackitProvider, ToolSpecs, register_squackit_kit
- Lackpy delegation verified end-to-end (1.5b generates correct programs)
- Model scaling test: 1.5b > 3b > 7b for sandbox-constrained tool calling
- Grid-search example generator with mechanical validator
- First run: 96% validation pass rate (vs ~0% with old prompt)

## Current state

### squackit
- **Version:** 0.4.1 on PyPI (tag v0.4.1). Main is ahead with unpublished commits.
- **Branch:** main, pushed to origin
- **Tests:** 275 passing
- **Key files changed since v0.4.1:**
  - `squackit/lackpy_integration.py` — SquackitProvider + ToolSpecs
  - `docs/agent-system-prompt.md` — agent orientation doc
  - `docs/superpowers/skills/` — 5 skills (all dogfood-validated)
  - `scripts/grid_generate_examples.py` — grid search with validator

### Grid run
- **In progress.** ~11 of 225 cells complete (pass A only so far).
- **Quality audit results:** 63 unique novel examples out of 184 total (47% useful).
- **Decision:** hand-curate the 63 good examples + fill gaps manually, rather than iterating prompts.
- **Output location:** `scripts/example_grid_out/` (gitignored)
- **Grid can be resumed:** `python scripts/grid_generate_examples.py --skip-missing`

### Pluckit
- **Version:** 0.9.0 on PyPI
- **Branch:** `feat/training-data-generator` at origin
- **Key changes this session:** `pluckins` rename, `PluckinRegistry.pluckins` property

## Immediate next task: Hand-curate lackpy training examples

Take the 63 novel examples from the grid output + manually write examples for the 20 uncovered tools. Target: ~100 curated examples covering all tools with natural-sounding intents.

### What needs curation:
1. **Fix quoting bugs** — `[name^='test_']` inside single-quoted strings (6 examples)
2. **Fill tool gaps** — 20 tools have zero novel examples (git tools, kibitzer, some blq)
3. **Diversify intents** — make them sound like real developer requests
4. **Deduplicate** — remove the 25 spec copies and 31 duplicates
5. **Add compositional selectors** — `.class#X > .fn`, `:has(...)`, `[name*='...']`
6. **Wire into ToolSpecs** — update `squackit/lackpy_integration.py` to load curated examples

### Where examples live:
- Raw grid output: `scripts/example_grid_out/`
- Curated examples should go: `squackit/data/examples.json` (or similar)
- Loaded by: `squackit/lackpy_integration.py:_make_tool_specs()`

## Environment notes
- **Venv:** `/home/teague/.local/share/venv/bin/python`
- **Ollama:** `http://localhost:11435` (via alpaca), model `qwen2.5-coder:1.5b`
- **FLEDGLING_REPO_PATH:** `/mnt/aux-data/teague/Projects/source-sextant/main`
- **Memory:** `/home/teague/.claude/projects/-mnt-aux-data-teague-Projects-squackit/memory/`
