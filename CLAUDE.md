# squawkit: Project Conventions

## Current state (post-Phase 3)

squawkit reaches fledgling's SQL macros only through pluckit. The
dependency chain invariant is enforced:

    squawkit → pluckit → fledgling-python → fledgling (SQL)

## Import rules

- `squawkit.*` for internal imports
- `pluckit.*` for the fluent API and the macro-enabled Connection
  (squawkit's only runtime dependency for fledgling access)
- **Never** `import fledgling` or `from fledgling_python ...`. If you
  need a capability pluckit doesn't expose, grow pluckit — don't add an
  escape hatch.
- Tests use `from conftest import PROJECT_ROOT` — squawkit's `conftest.py`
  defines `PROJECT_ROOT` lazily via fledgling package discovery (repo
  layout preferred, bundled-package layout as fallback).

## Tests

Run with:
```
FLEDGLING_REPO_PATH=/path/to/fledgling/repo pytest tests/
```

Tests dog-food against the fledgling repo. Set `FLEDGLING_REPO_PATH` to
the repo root, or let conftest auto-discover from the installed fledgling
package (covers most tests; 6 tests that reference repo-only paths like
`docs/vision/*.md` still need the env var).
