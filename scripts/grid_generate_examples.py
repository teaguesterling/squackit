"""Grid-search example generation with cross-model critic-refiner loop.

Strategy:
- Fix two 7b models (qwen2.5-coder:7b + qwen2.5:7b).
- Vary the prompt/strategy.
- For each (strategy, tool_group):
    Pass A: generate with coder, critique with qwen, refine with coder
    Pass B: generate with qwen, critique with coder, refine with qwen
  Cross-model critique surfaces more issues than self-review (ensemble).

- Persist every artifact to disk (generation, critique, refinement) so we
  can review & prune later without burning expensive tokens.

Designed to run for hours in the background. Resumable — skips any
output file that already exists.

Run:
    python scripts/grid_generate_examples.py
    # or restrict to one pass
    python scripts/grid_generate_examples.py --pass A

Check progress:
    ls scripts/example_grid_out/ | head
    # or count by stage:
    ls scripts/example_grid_out/ | awk -F'__' '{print $4}' | sort | uniq -c
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False

OLLAMA_HOST = "http://localhost:11435"
MODEL_CODER = "qwen2.5-coder:7b"
MODEL_QWEN = "qwen2.5:7b"
MODEL_GLM = "glm4:9b"
MODEL_QWEN3 = "qwen3:8b"
MODEL_CODEGEMMA = "codegemma:7b"
OUT_DIR = Path(__file__).parent / "example_grid_out"
OUT_DIR.mkdir(exist_ok=True)

# ─────────────────────────────────────────────────────────────────────
# Tool groups — breadth across the Rigged suite.
# ─────────────────────────────────────────────────────────────────────

TOOL_GROUPS: dict[str, str] = {
    "squackit_read": """\
# squackit (read-only code intelligence)

- find_names(source: str, selector: str) -> list[str]
    Names of AST nodes matching CSS selector.
- find(source: str, selector: str) -> list[dict]
    Full AST metadata (file, line, etc.) for matches.
- view(source: str, selector: str) -> str
    Rendered markdown of matched source code.
- complexity(source: str, selector: str) -> list[dict]
    Matches ranked by descendant complexity.
- read_source(file_path: str, lines: str) -> str
    File content (optionally restricted to 'start-end' lines).
""",

    "pluckit_chain": """\
# pluckit (chain API — used through squackit's `pluck` tool)

pluck(argv: str) takes a whitespace-separated chain:
    source_pattern [op [arg]]... [terminal]

Ops: find, filter, not_, unique, parent, children, siblings, ancestor,
     next, prev, containing, at_line, at_lines
Terminals: names, count, text, materialize, view (needs --plugin AstViewer),
           complexity, attr <name>
Control: reset (clears selection), pop (pops to previous)
Mutations (require allow_mutations=True): rename, replaceWith, wrap, unwrap,
    remove, append, prepend, insertBefore, insertAfter, addParam, removeParam,
    addArg, removeArg
""",

    "squackit_git": """\
# squackit (git history tools)

- recent_changes(n: int) -> list[dict]  — recent commits
- branch_list() -> list[dict]
- tag_list() -> list[dict]
- working_tree_status() -> list[dict]  — uncommitted files
- file_changes(from_rev, to_rev) -> list[dict]  — files touched between revs
- file_diff(file, from_rev, to_rev) -> str  — unified diff
- file_at_version(file, rev) -> str  — file contents at rev
- structural_diff(file, from_rev, to_rev) -> list[dict]
    added/removed/modified defs
- changed_function_summary(from_rev, to_rev) -> list[dict]
    changed functions ranked by complexity
""",

    "squackit_docs": """\
# squackit (markdown doc navigation)

- doc_outline(file_pattern: str, search: str = None) -> list[dict]
    Markdown section outlines. Use search= to filter by keyword.
- read_doc_section(file_path: str, target_id: str) -> str
    Read a specific section body by its slug id.
""",

    "squackit_workflows": """\
# squackit (compound workflow tools — single-call briefings)

- explore(path: str = None) -> str
    First-contact: languages, key defs, docs, recent activity.
- investigate(name: str) -> str
    Function/symbol deep dive: definition, source, callers, callees.
- review(from_rev: str, to_rev: str) -> str
    Review prep: changed files + functions + diffs.
- search(query: str) -> str
    Multi-source search: definitions, call sites, docs, conversations.
""",

    "jetsam": """\
# jetsam (git workflow accelerator)

- status() -> str  — working tree status
- save(message: str) -> plan  — returns plan; must confirm() to apply
- sync() -> plan  — fetch/pull/rebase plan; must confirm()
- confirm(plan_id: str) -> result
- log(n: int) -> list[dict]
- diff(rev: str = None) -> str
- pr_list() -> list[dict]
- pr_view(number: int) -> dict
- pr_comment(number: int, body: str) -> dict
- start(branch: str) -> str  — create feature branch
- finish() -> str  — merge current branch
- ship() -> str  — push + PR
- issue_close(number: int, comment: str = None) -> dict

All mutating ops (save, sync) return plans; call confirm(plan_id) to apply.
""",

    "blq": """\
# blq (build log query)

- run(command: list[str]) -> run_id  — run a build, capture output
- status() -> dict  — current runs + errors
- commands() -> list[dict]  — registered commands
- errors(run_ref: str = None) -> list[dict]  — parsed errors from a run
- events(run_ref: str) -> list[dict]  — raw event stream
- output(run_ref: str, query: str = None) -> str  — captured logs
- event(ref: str) -> dict  — single event detail
- context(ref: str) -> str  — context around an event
- register_command(name: str, command: list[str]) -> None
- history(limit: int = 20) -> list[dict]
""",

    "lackpy": """\
# lackpy (delegate an intent to a small model)

- delegate(intent: str, kit: list[str], params: dict = None) -> result
    Run a natural-language intent as a restricted Python program.
    Result keys: success, program, output, error, trace.
- generate(intent: str, kit: list[str]) -> str
    Generate the program without running it.
""",

    "kibitzer": """\
# kibitzer (Claude Code tool-use shepherd)

- before_call(tool: str, args: dict) -> result
    Check a proposed tool call. Returns path guard verdict + suggestions.
- after_call(tool: str, args: dict, result: Any) -> None
    Record a tool call outcome.
- get_suggestions(tool: str) -> list[str]
    Current mode-controller suggestions for tool.
- get_prompt_hints() -> list[str]
    Coach hints to inject into the next prompt.
- change_mode(tool: str, new_mode: str) -> None
- report_generation(failure_mode: str) -> None
""",
}

# ─────────────────────────────────────────────────────────────────────
# Strategies — different ways to frame the same task.
# ─────────────────────────────────────────────────────────────────────

STRATEGIES: dict[str, str] = {
    "meta_curator": """\
You are curating training examples for a 1.5B-parameter sibling model that
calls these tools through a RESTRICTED Python sandbox. Your job is to
produce examples that teach the smaller model the exact patterns it needs.

Sandbox rules the sibling must obey:
- Only direct tool calls and variable assignments — no `def`, no `import`
- No file I/O (`open`, `Path`, `glob.glob`), no `os`, no regex modules
- Strings are strings, not variables — a function named 'foo' is the
  string `'foo'` inside a selector, not a Python name
- End with a bare expression (e.g. `x`) to return a value
""",

    "teacher_mode": """\
You are writing examples for a tutorial that will be read by programmers
learning this toolkit for the first time. Each example should be
self-explanatory from the intent alone. Cover the common use cases.
Avoid trivial variations; each example should teach something distinct.
""",

    "failure_first": """\
You are compiling a "what goes wrong" catalog. Start by listing the
5 most common mistakes a naive caller would make — wrong selector syntax,
wrong tool choice, sandbox-illegal patterns, argument type mistakes,
overengineering. For each failure mode produce:
- The WRONG attempt (as `code`)
- The correct version (as `correct_code`)
- A note explaining the fix
Then add positive examples that avoid these mistakes.
""",

    "compositional": """\
You are demonstrating how primitives compose. Start simple and build up:
first show a single tool call, then show a chain of two tool results
feeding each other, then show a more elaborate pipeline. Prefer examples
where later steps depend on earlier results. Show the sibling model that
tool chains can be powerful.
""",

    "domain_diverse": """\
Vary the intent domains widely. Include refactoring scenarios, code review
prep, finding dead code, measuring complexity, tracking git history,
navigating docs, debugging a build failure, investigating a function.
Each example should feel like a real task someone might actually want
to do.
""",
}

# ─────────────────────────────────────────────────────────────────────
# Prompt templates
# ─────────────────────────────────────────────────────────────────────

BASE_FORMAT_NOTE = """\
# Output format (STRICT JSON)

Output ONLY a JSON array, no prose, no markdown fences. Exactly 15
examples. Each positive example:
{
  "intent": "natural language request",
  "code": "sandbox-legal program",
  "tool": "primary tool used",
  "tags": ["positive"],
  "notes": "one-line explanation of why this is the right approach"
}

For anti-patterns use:
{
  "intent": "natural language request",
  "code": "the WRONG attempt",
  "correct_code": "the right version",
  "tool": "intended tool",
  "tags": ["anti_pattern"],
  "notes": "what's wrong and why the correct version works"
}

Use single quotes for Python strings inside "code" to avoid JSON escape issues.
Output the JSON array now."""


def build_gen_prompt(strategy_text: str, tool_group_text: str) -> str:
    return f"""\
{strategy_text}

# Tools in scope for this batch

{tool_group_text}

{BASE_FORMAT_NOTE}"""


CRITIC_PROMPT = """\
You are reviewing training examples another model produced. Your job is
to find issues that would confuse a 1.5B-parameter consumer. Identify
the TOP 5 issues. For each, cite the example index (0-based) and explain:
- What's wrong
- Why a 1.5B model would be confused or learn the wrong lesson
- A suggested fix (one sentence)

Common things to check:
- Does the code actually work in a restricted sandbox? (no imports, no def,
  no file I/O)
- Is the selector syntax correct? (.fn / .class with # for exact name,
  [name^=...] for prefix, space for descendant, > for direct child)
- Is the intent clear enough that a smaller model could pattern-match?
- Are anti-patterns genuinely anti-patterns (not just stylistic)?
- Are there redundant examples?

Output ONLY a JSON array of issues, no prose:
[
  {"index": 0, "issue": "...", "why_confusing": "...", "fix": "..."},
  ...
]

Examples to review:
"""


REFINE_PROMPT = """\
You wrote training examples. A second-opinion reviewer found issues.
Produce an updated version of the full example set incorporating the
fixes. Keep the same strict JSON format. Output the FULL updated array
(not a diff). Fix every cited issue. Keep uncriticized examples as-is.

Original examples:
{original}

Reviewer issues:
{issues}

Updated JSON array:"""


# ─────────────────────────────────────────────────────────────────────
# Ollama plumbing
# ─────────────────────────────────────────────────────────────────────


def query(model: str, prompt: str, temperature: float = 0.3, max_tokens: int = 6000) -> str:
    data = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
            "num_ctx": 8192,
        },
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/generate",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=900) as resp:
        body = json.loads(resp.read())
    return body["response"]


def extract_json_array(text: str) -> list | None:
    """Pull the first top-level JSON array out of a messy model response."""
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or start >= end:
        return None
    candidate = text[start : end + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        fixed = candidate.replace("\\'", "'")
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            return None


# ─────────────────────────────────────────────────────────────────────
# Pipeline (files named `{pass}__{strategy}__{tool_group}__{stage}.{ext}`)
# ─────────────────────────────────────────────────────────────────────


def base(pass_label: str, strategy: str, tool_group: str, stage: str) -> Path:
    return OUT_DIR / f"{pass_label}__{strategy}__{tool_group}__{stage}"


def _log(msg: str) -> None:
    """Log line that coexists with tqdm (uses tqdm.write if available)."""
    if HAS_TQDM and sys.stdout.isatty():
        tqdm.write(msg)
    else:
        print(msg, flush=True)


def stage_generate(pass_label: str, strategy: str, tool_group: str, model: str) -> Path | None:
    out = base(pass_label, strategy, tool_group, "1_generate.json")
    if out.exists():
        return out
    raw_out = base(pass_label, strategy, tool_group, "1_generate.raw.txt")
    prompt = build_gen_prompt(STRATEGIES[strategy], TOOL_GROUPS[tool_group])
    t0 = time.time()
    try:
        raw = query(model, prompt, temperature=0.5)
    except Exception as e:
        _log(f"  [gen  {model}] {pass_label}/{strategy}/{tool_group}: ERROR after {time.time()-t0:.1f}s: {e}")
        return None
    raw_out.write_text(raw)
    examples = extract_json_array(raw)
    if examples is None:
        _log(f"  [gen  {model}] {pass_label}/{strategy}/{tool_group}: parse failed after {time.time()-t0:.1f}s (raw saved)")
        return None
    out.write_text(json.dumps(examples, indent=2))
    _log(f"  [gen  {model}] {pass_label}/{strategy}/{tool_group}: {len(examples)} examples in {time.time()-t0:.1f}s")
    return out


def stage_critique(gen_path: Path, critic_model: str) -> Path | None:
    out = gen_path.with_name(gen_path.name.replace("1_generate", "2_critique"))
    if out.exists():
        return out
    raw_out = out.with_suffix(".raw.txt")
    examples = json.loads(gen_path.read_text())
    prompt = CRITIC_PROMPT + json.dumps(examples, indent=2)
    t0 = time.time()
    try:
        raw = query(critic_model, prompt, temperature=0.2)
    except Exception as e:
        _log(f"  [crit {critic_model}] {gen_path.stem}: ERROR after {time.time()-t0:.1f}s: {e}")
        return None
    raw_out.write_text(raw)
    issues = extract_json_array(raw)
    if issues is None:
        _log(f"  [crit {critic_model}] {gen_path.stem}: parse failed after {time.time()-t0:.1f}s")
        return None
    out.write_text(json.dumps(issues, indent=2))
    _log(f"  [crit {critic_model}] {gen_path.stem}: {len(issues)} issues in {time.time()-t0:.1f}s")
    return out


def stage_refine(gen_path: Path, crit_path: Path, refiner_model: str) -> Path | None:
    out = gen_path.with_name(gen_path.name.replace("1_generate", "3_refine"))
    if out.exists():
        return out
    raw_out = out.with_suffix(".raw.txt")
    original = gen_path.read_text()
    issues = crit_path.read_text()
    prompt = REFINE_PROMPT.format(original=original, issues=issues)
    t0 = time.time()
    try:
        raw = query(refiner_model, prompt, temperature=0.3, max_tokens=8000)
    except Exception as e:
        _log(f"  [ref  {refiner_model}] {gen_path.stem}: ERROR after {time.time()-t0:.1f}s: {e}")
        return None
    raw_out.write_text(raw)
    refined = extract_json_array(raw)
    if refined is None:
        _log(f"  [ref  {refiner_model}] {gen_path.stem}: parse failed after {time.time()-t0:.1f}s")
        return None
    out.write_text(json.dumps(refined, indent=2))
    _log(f"  [ref  {refiner_model}] {gen_path.stem}: {len(refined)} examples in {time.time()-t0:.1f}s")
    return out


# ─────────────────────────────────────────────────────────────────────
# Passes — a pass fixes (generator, critic) roles.
# Cross-model critique: generator's weaknesses are caught by a different
# model, then the original generator refines.
# ─────────────────────────────────────────────────────────────────────

PASSES = {
    # Each generator's work is reviewed by a different model, then the
    # generator refines. Every available model gets a turn as generator,
    # paired with a different critic. Each pass catches issues its own
    # generator would miss.
    "A": {"gen": MODEL_CODER,     "crit": MODEL_QWEN,      "ref": MODEL_CODER},
    "B": {"gen": MODEL_QWEN,      "crit": MODEL_CODER,     "ref": MODEL_QWEN},
    "C": {"gen": MODEL_GLM,       "crit": MODEL_QWEN3,     "ref": MODEL_GLM},
    "D": {"gen": MODEL_QWEN3,     "crit": MODEL_GLM,       "ref": MODEL_QWEN3},
    "E": {"gen": MODEL_CODEGEMMA, "crit": MODEL_CODER,     "ref": MODEL_CODEGEMMA},
}


def check_models_available(required: set[str]) -> tuple[bool, set[str]]:
    """Verify all models are pulled locally. Returns (ok, missing)."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=10) as resp:
            body = json.loads(resp.read())
    except Exception as e:
        print(f"Cannot reach ollama at {OLLAMA_HOST}: {e}")
        return False, required
    available = {m["name"] for m in body.get("models", [])}
    missing = required - available
    return not missing, missing


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pass", dest="pass_label", choices=list(PASSES.keys()) + ["all"], default="all",
                    help="Which pass to run. 'all' runs every configured pass.")
    ap.add_argument("--skip-missing", action="store_true",
                    help="Skip passes whose models aren't pulled, instead of aborting.")
    args = ap.parse_args()

    passes = list(PASSES.keys()) if args.pass_label == "all" else [args.pass_label]

    # Preflight: check every model required by the selected passes
    needed = {PASSES[p][role] for p in passes for role in ("gen", "crit", "ref")}
    ok, missing = check_models_available(needed)
    if not ok:
        print(f"Missing models (pull them first): {sorted(missing)}")
        if args.skip_missing:
            passes = [p for p in passes
                      if not (set(PASSES[p].values()) & missing)]
            print(f"Skipping affected passes. Remaining: {passes}")
            if not passes:
                print("No runnable passes.")
                return 1
        else:
            print("Pass --skip-missing to run only the passes whose models are available.")
            return 1

    tasks = [(p, s, t) for p in passes for s in STRATEGIES for t in TOOL_GROUPS]
    total = len(tasks)
    print(f"Grid: {len(passes)} passes × {len(STRATEGIES)} strategies × {len(TOOL_GROUPS)} tool groups = {total} cells")
    print(f"Each cell: generate → cross-model critique → refine (3 ollama calls)")
    for label in passes:
        cfg = PASSES[label]
        print(f"Pass {label}: {cfg['gen']} generates, {cfg['crit']} critiques, {cfg['ref']} refines")
    print(f"Output: {OUT_DIR}")
    print()

    t_start = time.time()
    use_tqdm = HAS_TQDM and sys.stdout.isatty()
    iterator = (
        tqdm(tasks, desc="grid", unit="cell", ncols=100)
        if use_tqdm
        else tasks
    )

    for i, (pass_label, strategy, tool_group) in enumerate(iterator, 1):
        p = PASSES[pass_label]

        def _set(stage: str):
            if use_tqdm:
                iterator.set_postfix_str(f"{pass_label}/{strategy}/{tool_group} :: {stage}")

        if not use_tqdm:
            elapsed = time.time() - t_start
            eta = elapsed / max(i - 1, 1) * (total - i + 1) if i > 1 else 0
            print(f"[{i}/{total}] pass={pass_label} {strategy} × {tool_group} (elapsed={elapsed:.0f}s, eta={eta:.0f}s)")

        _set("generate")
        gen_path = stage_generate(pass_label, strategy, tool_group, p["gen"])
        if gen_path is None:
            continue
        _set("critique")
        crit_path = stage_critique(gen_path, p["crit"])
        if crit_path is None:
            continue
        _set("refine")
        stage_refine(gen_path, crit_path, p["ref"])
        if not use_tqdm:
            print()

    # Summary
    n_gen = len(list(OUT_DIR.glob("*1_generate.json")))
    n_crit = len(list(OUT_DIR.glob("*2_critique.json")))
    n_ref = len(list(OUT_DIR.glob("*3_refine.json")))
    total_time = time.time() - t_start
    print()
    print(f"Done in {total_time/60:.1f} min. "
          f"{n_gen} generations, {n_crit} critiques, {n_ref} refinements.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
