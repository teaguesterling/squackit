# squawkit: Project Conventions

## Phase 1 scope

squawkit is currently a verbatim migration of `fledgling/pro/` with imports
rewritten. Do not refactor, do not add features, do not restructure. The design
spec in `docs/superpowers/specs/2026-04-10-squawkit-design.md` describes the
target; Phase 1 only sets up the package boundary.

The migration rule is "verbatim + sed + conftest rewrite". In addition to the
import rewrite, each migrated test file that carried a local
`PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
has that line replaced with `from conftest import PROJECT_ROOT` so tests
resolve paths against the fledgling repo (what they were authored for) rather
than the squawkit repo they now live in. Any new test file migrated in the
remaining tasks must apply the same rewrite.

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
