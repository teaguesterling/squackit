# Handoff: squackit Extraction Plan — Resume at Task 2

You are resuming execution of an in-progress multi-phase project migration. The previous session designed the architecture, wrote the specs and implementation plan, and executed Task 1 of 12. Your job is to continue executing Tasks 2 through 12 using the subagent-driven-development skill.

## The mission in one paragraph

We are extracting `fledgling/pro/` (currently a subpackage of the fledgling-mcp repo) into a brand-new standalone Python package called **squackit** at `~/Projects/squackit/`. This is Phase 1 of a three-phase migration: Phase 1 is a verbatim migration (same behavior, new package); Phase 2 adds new SQL workflow macros in fledgling plus `fledgling-python` extraction; Phase 3 deletes `fledgling/pro/` and rewires squackit to use pluckit. You are only doing Phase 1. Do not refactor, do not add features, do not restructure — just move code with imports rewritten.

## Key paths

- **Plan (your primary reference):** `/home/teague/Projects/squackit/docs/superpowers/plans/2026-04-10-squackit-extraction.md` (1054 lines, 12 tasks)
- **Design spec:** `/home/teague/Projects/squackit/docs/superpowers/specs/2026-04-10-squackit-design.md`
- **Fledgling reorg spec (parent design):** `/mnt/aux-data/teague/Projects/source-sextant/main/docs/superpowers/specs/2026-04-10-fledgling-reorg-design.md`
- **Pluckit integration spec (sibling, not in Phase 1):** `/home/teague/Projects/pluckit/main/docs/superpowers/specs/2026-04-10-fledgling-python-integration-design.md`
- **Fledgling source repo (read-only in Phase 1):** `/mnt/aux-data/teague/Projects/source-sextant/main`
- **squackit target repo (writable):** `/home/teague/Projects/squackit`

**Read the plan first.** It contains full task text with exact commands for every step. Do not have subagents read the plan — you extract task text yourself and paste it into subagent prompts per the subagent-driven-development skill.

## What's done

**Task 1 of 12: COMPLETE.** Scaffolded squackit package. Verified by spec reviewer. Commit SHA `2d9775b` on branch `main` at `~/Projects/squackit/`. Files created:

```
~/Projects/squackit/
├── .git/                             (initialized, branch: main)
├── .gitignore                        (146 bytes)
├── pyproject.toml                    (1101 bytes — depends on fledgling-mcp>=0.6.2, duckdb>=1.5.0, fastmcp>=3.0)
├── README.md                         (858 bytes)
├── CLAUDE.md                         (801 bytes)
├── squackit/__init__.py              (76 bytes — version placeholder)
└── docs/superpowers/                 (pre-existing, contains specs/ and plans/)
```

Code quality review was skipped for Task 1 because it contained only configuration files with no logic. All subsequent tasks should go through the full two-stage review (spec compliance then code quality).

## What's next: Tasks 2 through 12

| # | Task | Touches | Model hint |
|---|---|---|---|
| 2 | Install dev mode + smoke test | `tests/test_smoke.py`, `tests/__init__.py`, pip install -e | haiku |
| 3 | Migrate `formatting.py` + `test_truncation.py` | leaf module, cp+sed | haiku |
| 4 | Migrate `session.py` + `test_session.py` | leaf module | haiku |
| 5 | Migrate `defaults.py` + `test_defaults.py` | leaf module | haiku |
| 6 | Migrate `db.py` | thin fledgling.connect wrapper, no test file | haiku |
| 7 | Migrate `workflows.py` + `test_workflows.py` | depends on formatting | haiku |
| 8 | Migrate `prompts.py` + `test_prompts.py` | depends on workflows | haiku |
| 9 | Migrate `server.py` + `test_resources.py` — the big one (494 lines, imports from every module) | depends on all; first full-suite test run | **sonnet** |
| 10 | Migrate `__main__.py` and finalize `__init__.py` | entry point wiring | haiku |
| 11 | Extend smoke test with entry point verification | tests/test_smoke.py append | haiku |
| 12 | Full suite + wheel build verification | clean pytest cache, python -m build | haiku |

Task 9 should use sonnet because it has 9 steps, touches the largest file, and is the first point where the full test suite runs end-to-end — any failures require judgment to triage. Everything else is mechanical cp+sed+test+commit.

## Execution protocol (subagent-driven-development)

For each task, follow the skill's per-task loop:

1. **Extract full task text from the plan file** (read the plan yourself; don't pass the file path to the subagent)
2. **Dispatch an implementer subagent** with the Agent tool, `subagent_type: "general-purpose"`, model per the hint above. The prompt structure is defined in the skill at `/home/teague/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.7/skills/subagent-driven-development/implementer-prompt.md` — include:
   - Full task text pasted verbatim
   - Context section explaining where this task fits (scene-setting — the subagent has zero prior context)
   - Explicit scope boundaries ("only do this task, not the next one")
   - The working directory (`~/Projects/squackit/`)
   - "Ask questions before starting" prompt
3. **When implementer reports DONE**, dispatch a spec compliance reviewer (general-purpose, haiku is fine) with the full task requirements and explicit instructions to verify by reading files, not trusting the report. Do NOT include the implementer's report as the source of truth — pass it as a claim to verify.
4. **When spec reviewer reports ✅**, dispatch a code quality reviewer using `subagent_type: "superpowers:code-reviewer"`. For this reviewer, pass the task's BASE_SHA (commit before the task) and HEAD_SHA (commit after the task) so the reviewer sees only the task's diff.
5. **Mark the TodoWrite task complete** and move to the next plan task.

**Do not skip reviews.** Do not run multiple implementers in parallel (conflicts). Do not let the implementer read the plan file.

**When either review finds issues:** send the same implementer subagent back with the specific issues to fix via SendMessage, then re-run the relevant review. Loop until approved.

## Current task tracker state (TodoWrite)

Tasks 1–6 are brainstorming/planning (all completed). Tasks 7–18 track plan execution:

```
#7  [completed] Exec Task 1: Scaffold squackit package
#8  [pending]   Exec Task 2: Install dev mode + smoke test
#9  [pending]   Exec Task 3: Migrate formatting.py
#10 [pending]   Exec Task 4: Migrate session.py
#11 [pending]   Exec Task 5: Migrate defaults.py
#12 [pending]   Exec Task 6: Migrate db.py
#13 [pending]   Exec Task 7: Migrate workflows.py
#14 [pending]   Exec Task 8: Migrate prompts.py
#15 [pending]   Exec Task 9: Migrate server.py (big one)
#16 [pending]   Exec Task 10: Migrate __main__/__init__
#17 [pending]   Exec Task 11: Entry point smoke test
#18 [pending]   Exec Task 12: Full suite + wheel build
```

Mark task N as `in_progress` when you dispatch its implementer, `completed` after both reviews pass.

If you start a fresh session, the task IDs above will not exist in your TodoWrite state — recreate them (or your own equivalents) so you can track progress.

## Critical technical details the subagent doesn't know

**The universal sed pattern for every import rewrite** (run from inside the squackit repo root):

```bash
sed -i 's|fledgling\.pro\.|squackit.|g; s|fledgling\.pro|squackit|g' <path>
```

The first substitution handles `fledgling.pro.X`; the second catches any bare `fledgling.pro` reference. Order matters — specific pattern first.

**Imports that MUST remain unchanged** (squackit's runtime dependency on fledgling — do NOT let sed touch these):
- `import fledgling`
- `from fledgling.connection import Connection`
- `from conftest import PROJECT_ROOT` (inside test files — squackit's conftest.py defines PROJECT_ROOT locally via fledgling package discovery)

**Why these stay:** squackit depends on the existing fledgling-mcp package at runtime. The `fledgling/pro/*` → `squackit/*` rewrite only affects the pro subpackage — bare `fledgling` references still point at the installed fledgling package (which is still `fledgling-mcp>=0.6.2`).

**Task 3 creates `tests/conftest.py`** with an auto-discovery pattern for fledgling's repo root. The full content is in Task 3 Step 5 of the plan. It reads `FLEDGLING_REPO_PATH` env var or falls back to introspecting the installed fledgling package. Tests dog-food against fledgling's repo as test data.

**For Task 2 (install):** if `pip install -e .` fails because fledgling-mcp 0.6.2 is not installed in the environment, the fallback is `pip install -e /mnt/aux-data/teague/Projects/source-sextant/main` to install fledgling from the local repo in editable mode. This is already documented in the plan.

**For Task 9 (big one):** the first full-suite test run happens in Step 8. Tests that depend on the fledgling repo need `FLEDGLING_REPO_PATH=/mnt/aux-data/teague/Projects/source-sextant/main` set in the environment. Example:

```bash
cd ~/Projects/squackit && \
  FLEDGLING_REPO_PATH=/mnt/aux-data/teague/Projects/source-sextant/main \
  pytest tests/ -v
```

Some tests in the migrated suite may fail for reasons unrelated to the migration (pre-existing flakiness, environment-specific issues). The plan instructs the subagent to document such failures without attempting fixes — Phase 1 goal is "behavior matches fledgling-mcp[pro]," which is satisfied if tests that pass in fledgling also pass in squackit.

**Tasks 3–9 defer test verification for tests that transitively depend on later-migrated modules.** For example, `test_defaults.py` imports `squackit.server` at function level inside some tests. In Task 5 (defaults migration), those tests will ERROR because server.py doesn't exist yet. The plan says to skip them with `-k 'not create_server'` during migration tasks, then re-run the full suite in Task 9 Step 8. This is expected behavior, not a bug.

**Task 6 (db.py) has no dedicated test file.** It's a 15-line thin wrapper over `fledgling.connect()`. Verification is a spot-check: `python -c "from squackit.db import create_connection; c = create_connection(); print(type(c).__name__)"` should print `Connection`.

## Scope boundaries (do NOT let subagents drift)

**In scope for Phase 1:**
- Create `~/Projects/squackit/` as a pip-installable package (IN PROGRESS)
- Copy every module from `fledgling/pro/` → `squackit/` with imports rewritten via the sed pattern
- Copy every test from `tests/test_pro_*.py` → `squackit/tests/test_*.py` with the same rewrite
- `squackit` CLI entry point
- Self-contained conftest.py
- Self-contained test suite that dog-foods against fledgling
- Git commit per task, no tags, no PyPI publish

**Strictly out of scope (these belong to Phase 2 or 3):**
- Removing `fledgling/pro/` from the fledgling repo (Phase 3)
- New SQL workflow macros in fledgling (`explore_query`, `investigate_query`, etc. — Phase 2)
- `fledgling-python` extraction (Phase 2)
- Refactoring squackit to use pluckit (Phase 4)
- PyPI publication of squackit
- Access log persistence to disk (new feature, deferred)
- Kibitzer suggestion engine (new feature, deferred)
- Any behavior change relative to `fledgling-mcp[pro]`

**If a subagent reports a problem that would require an out-of-scope change, the answer is "stop and escalate" — do not widen scope.** The only exception is pre-existing bugs discovered during testing that must be documented rather than fixed.

## Environment notes

- **No worktree was used.** squackit is a brand-new repo, so a worktree doesn't apply. fledgling's repo is touched only as a read-only source for `cp` commands.
- **Main branch is intentional.** The plan creates the repo with `git init -b main` and commits directly. This is standard for bootstrapping a new repo. The user consented to this approach by choosing execution option 1 (subagent-driven) after reviewing the plan.
- **Primary working directory in the original session:** `/mnt/aux-data/teague/Projects/source-sextant/main` (the fledgling repo). Your session may open at a different cwd — always use absolute paths.
- **Today's date (at handoff time):** 2026-04-10.

## Design decisions worth knowing (but not changing)

These were settled during the brainstorming phase and are frozen for Phase 1:

- **Package name:** `squackit` (Semi-QUalified Agent Companion Kit). Sibling to `pluckit` (verb+it construction).
- **Import name:** `squackit`. CLI entry point: `squackit`.
- **Layout:** flat (`squackit/` at repo root), not `src/squackit/`. Matches fledgling's convention.
- **Runtime dep on fledgling-mcp>=0.6.2.** squackit imports `fledgling` directly for `Connection`. Will change in Phase 3 when fledgling-python exists.
- **Test data:** dog-fooded against the fledgling repo. `FLEDGLING_REPO_PATH` env var overrides, auto-discovery fallback via installed fledgling package.
- **Target layering (not yet reached in Phase 1):** `fledgling (SQL) → fledgling-python → pluckit → squackit → consumers`. Plan 1 is preparation for this layering, but Plan 1's squackit still imports fledgling directly (short-circuits pluckit and fledgling-python, which don't yet exist as separate packages). This inversion is fine and will be fixed in Phase 3.

## How to start

1. Read the plan at `~/Projects/squackit/docs/superpowers/plans/2026-04-10-squackit-extraction.md` to orient yourself. Skim the file structure section and the task list; read Task 2 in full.
2. Verify current state: `git -C ~/Projects/squackit log --oneline` should show exactly one commit (the Task 1 scaffolding). `ls ~/Projects/squackit/` should show the files listed under "What's done" above.
3. Invoke the skill: `Skill(skill="superpowers:subagent-driven-development")`.
4. Mark Task #8 in-progress in TodoWrite (or your equivalent), extract Task 2 text from the plan, dispatch the implementer subagent per the skill's per-task loop.
5. Proceed task by task. Expect ~12 implementer dispatches + ~24 review dispatches (spec + code quality per task, except Task 1 which is done). Budget accordingly.

## If things go wrong

- **Implementer reports BLOCKED or NEEDS_CONTEXT:** provide the missing context and re-dispatch (don't retry the same prompt). If the blocker is that the plan is wrong, escalate to the user rather than guess.
- **Spec reviewer finds issues:** use SendMessage to the implementer with the specific issues, then re-dispatch the spec reviewer.
- **Code quality reviewer flags Critical or Important issues:** same loop.
- **A test fails for a reason unrelated to the migration:** document in the commit message (e.g., "xfail: pre-existing flakiness in test_X, tracked in issue #Y") and proceed. Do not fix pre-existing bugs in Phase 1.
- **You discover the plan has a gap:** escalate to the user. Do not widen scope without explicit approval.

## Success criteria for Phase 1 complete

1. All 12 tasks completed with both reviews passing
2. 12 commits on `~/Projects/squackit/` main branch, one per task, with descriptive messages
3. `pip install -e ~/Projects/squackit` works
4. `squackit` CLI is on PATH after install
5. `pytest tests/` passes the full migrated suite (modulo pre-existing issues, documented)
6. `python -m build --wheel` produces a valid `squackit-0.1.0-py3-none-any.whl`
7. `fledgling/pro/` in the fledgling repo is **untouched** — `fledgling-pro` still works from the original repo

When you reach success criteria, report back to the user with a summary and wait for direction on Phase 2.

---

**End of handoff.** This prompt is designed to be pasted into a fresh Claude Code session with no prior context. All the state you need is in the plan file and the current git history of `~/Projects/squackit/`.
