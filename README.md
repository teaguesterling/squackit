# squawkit

**Semi-QUalified Agent Wingman Kit.** The stateful intelligence + MCP server layer
for [fledgling](https://github.com/teaguesterling/fledgling)-equipped agents.

squawkit wraps fledgling's SQL macros with smart defaults, token-aware output,
session caching, compound workflows, an MCP server, prompts, and resources. It is
the Python-side "cold-start agent support" layer — the features that don't belong
in fledgling's neutral SQL core.

## Status

**Phase 1 — extraction from fledgling/pro/.** Runtime behavior identical to
`fledgling-mcp[pro]`. Subsequent phases add new features, refactor to use pluckit,
and retire the `fledgling-mcp[pro]` extra.

See `docs/superpowers/specs/2026-04-10-squawkit-design.md` for the full design.

## Install

```bash
pip install -e .
```

## Run

```bash
squawkit
```

Starts the FastMCP server on stdio.
