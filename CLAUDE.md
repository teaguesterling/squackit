# squawkit: Project Conventions

## Phase 1 scope

squawkit is currently a verbatim migration of `fledgling/pro/` with imports
rewritten. Do not refactor, do not add features, do not restructure. The design
spec in `docs/superpowers/specs/2026-04-10-squawkit-design.md` describes the
target; Phase 1 only sets up the package boundary.

## Import rules

- `squawkit.*` for internal imports
- `import fledgling` and `from fledgling.connection import Connection` — stay
  (squawkit depends on fledgling at runtime)
- Tests use `from conftest import PROJECT_ROOT` — squawkit's `conftest.py`
  defines `PROJECT_ROOT` via `fledgling` package discovery

## Tests

Run with:
```
pytest tests/
```

Tests dog-food against the fledgling repo. Set `FLEDGLING_REPO_PATH` to override
the auto-discovered path.
