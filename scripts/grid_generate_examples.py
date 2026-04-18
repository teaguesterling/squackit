"""Grid-search example generation with validated cross-model critic-refiner loop.

For each (strategy, tool_group) in the grid, for each pass:
  1. generate — the generator model produces 15 examples
  2. validate — mechanical check: parse the `code` field as Python AST,
     confirm no forbidden nodes (def/import/file I/O), confirm calls
     resolve to the kit, check selector strings for obvious mistakes
  3. critique — a DIFFERENT model sees the examples + validation report
     and explains what's wrong in natural language
  4. refine — original generator rewrites the examples based on the
     critique + validation

Validation turns "review by vibes" into "review by facts". The critic's
job becomes explaining mechanical failures, not discovering them.

Resumable — skips any output file that already exists.

Run:
    python scripts/grid_generate_examples.py
    python scripts/grid_generate_examples.py --pass A

Check progress:
    ls scripts/example_grid_out/ | awk -F'__' '{print $NF}' | sort | uniq -c
"""

from __future__ import annotations

import argparse
import ast
import json
import re
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
MODEL_CODER_3B = "qwen2.5-coder:3b"
MODEL_QWEN = "qwen2.5:7b"
MODEL_GLM = "glm4:9b"
MODEL_QWEN3 = "qwen3:8b"
MODEL_CODEGEMMA = "codegemma:7b"
OUT_DIR = Path(__file__).parent / "example_grid_out"
OUT_DIR.mkdir(exist_ok=True)

# ─────────────────────────────────────────────────────────────────────
# Tool groups — each includes concrete VALID and INVALID examples
# inlined in the prompt. Models ignore abstract type signatures; they
# pattern-match on examples. So we front-load them.
# ─────────────────────────────────────────────────────────────────────

TOOL_GROUPS: dict[str, dict] = {
    "squackit_read": {
        "spec": """\
# squackit (read-only code intelligence)

All selectors are CSS-over-AST. Valid primitives:
  .fn         — any function definition
  .class      — any class definition
  .call       — any call expression
  #name       — exact name match (use with a prefix, e.g. .fn#main)
  [name^='x'] — name starts with 'x'
  [name*='x'] — name contains 'x'
  [name$='x'] — name ends with 'x'
  A B         — B that descends from A (e.g. .class#Auth .fn)
  A > B       — B directly inside A (e.g. .class#Auth > .fn)

Tools:
  find_names(source: str, selector: str) -> list[str]
  find(source: str, selector: str) -> list[dict]
  view(source: str, selector: str) -> str            # rendered markdown
  complexity(source: str, selector: str) -> list[dict]  # ranked by complexity
  read_source(file_path: str, lines: str = None) -> str  # plain file read

CORRECT examples (use Black-compliant formatting — assign args to variables first):

  # Simple selector — inline is fine
  find_names('src/**/*.py', '.fn')

  # Named lookup
  find_names('src/auth.py', '.fn#validate_token')

  # Class methods (descendant combinator)
  find_names('src/auth.py', '.class#Auth .fn')

  # Attribute selectors — ALWAYS use variables to avoid quote nesting
  source = "src/**/*.py"
  selector = ".fn[name^='test_']"
  result = find_names(source, selector)
  result

  # Another attribute selector example
  source = "src/**/*.py"
  selector = ".fn[name*='validate']"
  result = find_names(source, selector)
  result

  # View and complexity
  view('src/api.py', '.class#Handler')
  complexity('src/**/*.py', '.fn')
  read_source('src/main.py', '1-50')

WRONG calls (DO NOT generate any of these — they all fail):
  find_names('src/**/*.py', '.fn[name^='test_']')  # ❌ quote nesting! Use variables instead
  find_names('src/**/*.py', 'function')  # ❌ 'function' is not a selector — use '.fn'
  find_names('src/**/*.py', 'func')      # ❌ 'func' is not a selector — use '.fn'
  find_names('src/**/*.py', 'var')       # ❌ no such selector
  find_names('def foo(): pass', '.fn')   # ❌ arg 1 is a glob, not source code
  squackit.find_names(...)               # ❌ no module prefix; call find_names directly
""",
        "kit_tools": {"find_names", "find", "view", "complexity", "read_source"},
    },

    "pluckit_chain": {
        "spec": """\
# pluckit (chain API via squackit's `pluck(argv: str)` tool)

pluck takes ONE argument: a whitespace-separated chain string.
Grammar: source_pattern [op [arg]]... [terminal]

Ops:     find, filter, not_, unique, parent, children, siblings,
         ancestor, next, prev, containing, at_line, at_lines
Terminals: names, count, text, materialize, view, complexity, attr <name>
Control:   reset (clear selection), pop (previous selection)

CORRECT examples (use variables for chains with attribute selectors):

  pluck('src/**/*.py find .fn names')
  pluck('src/**/*.py find .fn count')
  pluck('src/auth.py find .class#Auth children find .fn names')
  pluck('src/**/*.py find .fn containing cache names')
  pluck('src/**/*.py find .fn names reset find .class names')
  pluck('--plugin AstViewer src/api.py find .fn#handler view')

  # Attribute selectors — use a variable to avoid quote nesting
  chain = "src/**/*.py find .fn[name^='test_'] names"
  pluck(chain)

  chain = "src/**/*.py find .fn[name*='validate'] count"
  pluck(chain)

WRONG:
  pluck('src/**/*.py find .fn[name^='test_'] names')  # ❌ quote nesting! Use a variable
  squackit.pluck(...)                        # ❌ no module prefix
  pluck('*.py find names')                   # ❌ missing selector — find needs one
  pluck('src/**/*.py find function names')   # ❌ 'function' is not a selector; use '.fn'
  pluck('src/**/*.py', 'find', '.fn')        # ❌ pluck takes ONE arg (the whole chain)
""",
        "kit_tools": {"pluck"},
    },

    "squackit_git": {
        "spec": """\
# squackit (git history tools)

Tools:
  recent_changes(n: int = 20) -> list[dict]
  branch_list() -> list[dict]
  tag_list() -> list[dict]
  working_tree_status() -> list[dict]
  file_changes(from_rev: str, to_rev: str) -> list[dict]
  file_diff(file: str, from_rev: str, to_rev: str) -> str
  file_at_version(file: str, rev: str) -> str
  structural_diff(file: str, from_rev: str, to_rev: str) -> list[dict]
  changed_function_summary(from_rev: str, to_rev: str) -> list[dict]

CORRECT examples:
  recent_changes(10)
  branch_list()
  working_tree_status()
  file_changes('main', 'HEAD')
  file_diff('src/auth.py', 'HEAD~1', 'HEAD')
  changed_function_summary('main', 'feature-branch')

WRONG:
  git.log(...)                              # ❌ no 'git' namespace
  recent_changes('last 10')                 # ❌ takes int, not a phrase
  file_diff(file='a.py', rev='HEAD')        # ❌ needs from_rev AND to_rev
""",
        "kit_tools": {"recent_changes", "branch_list", "tag_list",
                      "working_tree_status", "file_changes", "file_diff",
                      "file_at_version", "structural_diff",
                      "changed_function_summary"},
    },

    "squackit_docs": {
        "spec": """\
# squackit (markdown doc navigation)

Tools:
  doc_outline(file_pattern: str, search: str = None) -> list[dict]
  read_doc_section(file_path: str, target_id: str) -> str

The target_id for read_doc_section is a slug like 'installation',
'css-selectors', 'quickstart' — obtained by first calling doc_outline.

CORRECT examples:
  doc_outline('docs/**/*.md')
  doc_outline('docs/**/*.md', search='authentication')
  read_doc_section('docs/api.md', 'quickstart')

WRONG:
  read_doc_section('docs/api.md', 'Quick Start')   # ❌ target_id is a slug, not title
  read_doc_section('docs/api.md', '#quickstart')   # ❌ no leading '#'
  doc_outline('docs/api.md', 'auth')                # ⚠️ search is a kwarg: search='auth'
""",
        "kit_tools": {"doc_outline", "read_doc_section"},
    },

    "squackit_workflows": {
        "spec": """\
# squackit (compound workflow tools — single-call briefings)

Tools:
  explore(path: str = None) -> str
  investigate(name: str) -> str
  review(from_rev: str = None, to_rev: str = None) -> str
  search(query: str) -> str

CORRECT examples:
  explore()
  explore('src/auth/')
  investigate('validate_token')
  review('main', 'HEAD')
  search('cache invalidation')

WRONG:
  investigate(validate_token)          # ❌ pass NAME as a string, not a Python symbol
  explore(src)                         # ❌ src is not defined; use a string path
  search(query=authentication)         # ❌ 'authentication' is not a variable
""",
        "kit_tools": {"explore", "investigate", "review", "search"},
    },

    "jetsam": {
        "spec": """\
# jetsam (git workflow accelerator)

Two-stage mutation pattern: save/sync return a plan; confirm() applies it.

Tools:
  status() -> str
  save(message: str) -> dict         # returns {"plan_id": "...", ...}
  sync() -> dict                      # returns plan
  confirm(plan_id: str) -> dict
  log(n: int = 20) -> list[dict]
  diff(rev: str = None) -> str
  pr_list() -> list[dict]
  pr_view(number: int) -> dict
  pr_comment(number: int, body: str) -> dict
  start(branch: str) -> str
  finish() -> str
  ship() -> str
  issue_close(number: int, comment: str = None) -> dict

CORRECT examples:
  status()
  plan = save('fix: null check')
  confirm(plan['plan_id'])
  log(5)
  pr_view(42)
  start('feature-auth')

WRONG:
  save('message').confirm()            # ❌ chained method call; save returns a dict
  jetsam.status()                      # ❌ no module prefix
  confirm(save('msg'))                 # ❌ pass the plan_id string, not the whole plan dict
""",
        "kit_tools": {"status", "save", "sync", "confirm", "log", "diff",
                      "pr_list", "pr_view", "pr_comment", "start", "finish",
                      "ship", "issue_close"},
    },

    "blq": {
        "spec": """\
# blq (build log query)

Tools:
  run(command: list[str]) -> str               # returns run_ref
  status() -> dict
  commands() -> list[dict]
  errors(run_ref: str = None) -> list[dict]
  events(run_ref: str) -> list[dict]
  output(run_ref: str, query: str = None) -> str
  event(ref: str) -> dict
  context(ref: str) -> str
  register_command(name: str, command: list[str]) -> None
  history(limit: int = 20) -> list[dict]

CORRECT examples:
  run(['pytest', 'tests/'])
  status()
  errors('run_abc123')
  output('run_abc123', query='AssertionError')
  event('evt_xyz')

WRONG:
  run('pytest tests/')                 # ❌ command is a list of argv, not a string
  blq.run([...])                        # ❌ no module prefix
  errors(query='failed')                # ❌ first arg is run_ref, not a query string
""",
        "kit_tools": {"run", "status", "commands", "errors", "events",
                      "output", "event", "context", "register_command", "history"},
    },

    "lackpy": {
        "spec": """\
# lackpy (delegate an intent to a small model via a restricted sandbox)

Tools:
  delegate(intent: str, kit: list[str]) -> dict
  generate(intent: str, kit: list[str]) -> str

Result dict keys: success (bool), program (str), output, error, trace (list).

CORRECT examples:
  delegate('find all test functions', ['find_names'])
  delegate('show the main function', ['view'])
  generate('list all classes', ['find_names'])

WRONG:
  delegate('find tests', kit='find_names')    # ❌ kit is a LIST
  lackpy.delegate(...)                         # ❌ no module prefix
""",
        "kit_tools": {"delegate", "generate"},
    },

    "kibitzer": {
        "spec": """\
# kibitzer (Claude Code tool-use shepherd)

Tools:
  before_call(tool: str, args: dict) -> dict
  after_call(tool: str, args: dict, result: object) -> None
  get_suggestions(tool: str) -> list[str]
  get_prompt_hints() -> list[str]
  change_mode(tool: str, new_mode: str) -> None
  report_generation(failure_mode: str) -> None

CORRECT examples:
  before_call('Bash', {'command': 'ls'})
  get_suggestions('Bash')
  change_mode('Bash', 'restricted')
  report_generation('IMPLEMENT_NOT_ORCHESTRATE')

WRONG:
  before_call(Bash, ...)                # ❌ tool name is a STRING
  change_mode(tool='Bash')              # ❌ missing new_mode argument
""",
        "kit_tools": {"before_call", "after_call", "get_suggestions",
                      "get_prompt_hints", "change_mode", "report_generation"},
    },
}

# ─────────────────────────────────────────────────────────────────────
# Strategies — different ways to frame the generation task.
# ─────────────────────────────────────────────────────────────────────

STRATEGIES: dict[str, str] = {
    "meta_curator": """\
You are curating training examples for a 1.5B sibling model that will
call these tools through a RESTRICTED Python sandbox. Produce examples
the smaller model can pattern-match against.

Sandbox rules the sibling must obey:
  - Only direct tool calls and variable assignments — NO `def`, NO `import`
  - No file I/O (no `open`, `Path(...)`, `glob.glob`, `os.*`)
  - Strings are literal strings. A function named 'foo' is the string 'foo'
    inside a selector; it is NEVER an unquoted Python name.
  - End with a bare expression (e.g. `x`) to return a value

STUDY the correct/wrong examples in the tool spec below. Your output
examples must use the EXACT selector syntax and argument shapes shown
as correct. Never use a selector or argument shape marked as WRONG.
""",

    "teacher_mode": """\
You are writing examples for a tutorial read by programmers new to this
toolkit. Each example must use the EXACT syntax shown in the tool spec's
CORRECT examples. Never invent tool names, never invent selectors.

Each example should teach something distinct — cover the common use
cases shown in the spec.
""",

    "failure_first": """\
You are compiling a "what goes wrong" catalog. For each entry:
  - "code" is the WRONG attempt
  - "correct_code" is the right version
  - "notes" explains the fix

The WRONG attempts should be realistic — the kinds of mistakes a naive
caller would actually make. The "correct_code" must match one of the
CORRECT patterns from the tool spec exactly.

After the anti-patterns, add 5 positive examples that demonstrate the
right patterns clearly.
""",

    "compositional": """\
Demonstrate how the primitives compose. Start simple (one tool call)
and build up (chained queries, results feeding each other). Every
example must use the EXACT syntax from the tool spec's CORRECT section.

Do not invent new selectors, new tools, or new argument orders. If a
composition isn't shown in the spec, stick to simpler forms.
""",

    "domain_diverse": """\
Vary the intents widely. Refactoring, code review prep, complexity
analysis, git history, doc navigation, build debugging.

Every example must use the EXACT syntax from the tool spec's CORRECT
examples. Do not substitute words like 'function' for '.fn'.
""",
}

# ─────────────────────────────────────────────────────────────────────
# Validator — parses the code field with Python's ast module, checks
# sandbox rules + kit membership + selector patterns.
# ─────────────────────────────────────────────────────────────────────

# Python builtins we allow the sandbox to use
SANDBOX_BUILTINS = {
    "len", "sorted", "list", "set", "dict", "tuple", "print", "str",
    "int", "float", "bool", "range", "enumerate", "zip", "map", "filter",
    "min", "max", "sum", "any", "all", "abs", "round",
}

FORBIDDEN_NODES = {
    ast.FunctionDef: "def",
    ast.AsyncFunctionDef: "async def",
    ast.Import: "import",
    ast.ImportFrom: "from-import",
    ast.ClassDef: "class",
    ast.Global: "global",
    ast.Nonlocal: "nonlocal",
    ast.Lambda: "lambda",
    ast.Try: "try/except",
    ast.Raise: "raise",
    ast.With: "with",
    ast.AsyncWith: "async with",
    ast.AsyncFor: "async for",
    ast.Await: "await",
    ast.Yield: "yield",
    ast.YieldFrom: "yield from",
}

# Selector strings that the generators incorrectly use. If a tool call
# passes any of these as a selector argument, it's wrong.
BAD_SELECTORS = {
    "function", "func", "fn", "method", "class", "cls", "variable", "var",
    "loop", "if", "for", "while", "return", "call", "import", "assign",
    "function_call", "function_def", "class_def", "def",
}


def validate_example(example: dict, tool_group: dict) -> dict:
    """Mechanically validate one example. Returns a report dict."""
    issues: list[str] = []
    code = example.get("code", "")
    if not isinstance(code, str) or not code.strip():
        return {"ok": False, "issues": ["empty or non-string code field"]}

    # Parse
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return {"ok": False, "issues": [f"SyntaxError: {e.msg} (line {e.lineno})"]}

    # Collect names assigned in this snippet so we don't flag legitimate vars
    assigned: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    assigned.add(t.id)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            if isinstance(node.target, ast.Name):
                assigned.add(node.target.id)
        elif isinstance(node, ast.For):
            if isinstance(node.target, ast.Name):
                assigned.add(node.target.id)

    kit = tool_group["kit_tools"]
    known_names = kit | SANDBOX_BUILTINS | assigned | {
        "True", "False", "None", "__builtins__",
    }

    for node in ast.walk(tree):
        # Forbidden constructs
        if type(node) in FORBIDDEN_NODES:
            issues.append(f"forbidden construct: {FORBIDDEN_NODES[type(node)]}")
            continue

        # Unresolved name reference (variable use before assignment)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id not in known_names:
                issues.append(
                    f"name '{node.id}' is used but not defined — if this is "
                    f"a literal (e.g. function/file name), quote it as a string"
                )

        # Call analysis
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                if isinstance(func.value, ast.Name):
                    issues.append(
                        f"method-style call '{func.value.id}.{func.attr}(...)': "
                        f"no module/object namespace allowed — call {func.attr} directly"
                    )
            elif isinstance(func, ast.Name):
                fname = func.id
                if fname not in kit and fname not in SANDBOX_BUILTINS:
                    issues.append(f"unknown function '{fname}' (not in kit, not a builtin)")
                else:
                    for arg in node.args + [kw.value for kw in node.keywords]:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            val = arg.value.strip()
                            if (val.lower() in BAD_SELECTORS
                                    and not val.startswith((".", "[", "#"))):
                                issues.append(
                                    f"bare word '{val}' passed to {fname}(...) — "
                                    f"selectors must use CSS syntax (e.g. .fn, .class)"
                                )

    # De-duplicate while preserving order
    seen = set()
    unique_issues = []
    for iss in issues:
        if iss not in seen:
            seen.add(iss)
            unique_issues.append(iss)

    return {"ok": len(unique_issues) == 0, "issues": unique_issues}


def validate_examples(examples: list, tool_group: dict) -> dict:
    """Validate a whole example set. Returns summary + per-example reports."""
    reports = []
    for i, ex in enumerate(examples):
        # Check anti-pattern examples' correct_code, not code
        if "anti_pattern" in ex.get("tags", []):
            target = {**ex, "code": ex.get("correct_code", ex.get("code", ""))}
            report = validate_example(target, tool_group)
            report["note"] = "validated correct_code (anti-pattern)"
        else:
            report = validate_example(ex, tool_group)
        report["index"] = i
        report["intent"] = ex.get("intent", "")
        reports.append(report)

    total = len(reports)
    fails = sum(1 for r in reports if not r["ok"])
    return {
        "total": total,
        "passing": total - fails,
        "failing": fails,
        "reports": reports,
    }


# ─────────────────────────────────────────────────────────────────────
# Prompts
# ─────────────────────────────────────────────────────────────────────

BASE_FORMAT_NOTE = """\
# Code style

Use Black-compliant Python formatting. When a tool argument contains
quotes (especially CSS attribute selectors like [name^='test_']),
ALWAYS assign it to a variable first to avoid quote-nesting bugs:

  # ✅ CORRECT — no quote nesting
  source = "src/**/*.py"
  selector = ".fn[name^='test_']"
  result = find_names(source, selector)
  result

  # ❌ WRONG — single quotes nest and break
  find_names('src/**/*.py', '.fn[name^='test_']')

Simple calls without attribute selectors can stay inline:
  find_names('src/**/*.py', '.fn')

# Output format (STRICT JSON)

Output ONLY a JSON array (no prose, no markdown fences). Exactly 15
examples. Each element uses one of these two shapes:

Positive example:
{
  "intent": "natural language request",
  "code": "sandbox-legal program that matches a CORRECT pattern from the spec",
  "tool": "primary tool used",
  "tags": ["positive"],
  "notes": "one-line explanation"
}

Anti-pattern:
{
  "intent": "natural language request",
  "code": "the WRONG attempt (must be realistic, match a WRONG pattern from the spec)",
  "correct_code": "the right version (must match a CORRECT pattern from the spec)",
  "tool": "intended tool",
  "tags": ["anti_pattern"],
  "notes": "what's wrong and why the correct version works"
}

Use ONLY the tools and selector syntax shown in the spec's CORRECT
section. Never invent new tool names, never invent new selectors.

Output the JSON array now."""


def build_gen_prompt(strategy_text: str, tool_spec: str) -> str:
    return f"""\
{strategy_text}

# Tools in scope for this batch

{tool_spec}

{BASE_FORMAT_NOTE}"""


CRITIC_PROMPT_TEMPLATE = """\
You are reviewing training examples. A mechanical validator has already
checked each example's code for sandbox compliance and kit membership.
Your job is to EXPLAIN the validator's findings in terms a 1.5B sibling
model can learn from, and spot qualitative issues the validator missed
(confusing intents, redundant examples, unrealistic cases).

# Validator report

{validator_report}

# Examples

{examples_json}

# Your output

Return a JSON array of issues (one per real problem). Cite the example
index (0-based). For each issue:
{{
  "index": 0,
  "severity": "error" | "warning",  // error = validator failed, warning = quality issue
  "issue": "short description",
  "fix": "one-sentence suggestion"
}}

Focus on issues the refining step can act on. Do not invent tool names
or argument shapes the spec doesn't support. Output ONLY the JSON array.
"""


REFINE_PROMPT_TEMPLATE = """\
You wrote these training examples. A validator found mechanical issues
and a reviewer added explanations. Produce an updated version of the
full set fixing every cited issue.

Keep the same strict JSON format (array of objects). Output the FULL
updated array — no diff, no prose.

Every `code` field must match the EXACT patterns from the spec's CORRECT
section. Do not invent tool names or selectors.

# Original examples
{original}

# Validator report
{validator_report}

# Reviewer issues
{issues}

# Updated JSON array
"""


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
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or start >= end:
        return None
    candidate = text[start : end + 1]

    # Try progressively more aggressive fixes
    for attempt in [
        candidate,                                  # raw
        candidate.replace("\\'", "'"),              # escaped single quotes
        re.sub(r'"\s+"', '"', candidate),           # qwen3 stray spaces between keys
        re.sub(r'"\s+"', '"', candidate.replace("\\'", "'")),  # both
    ]:
        try:
            return json.loads(attempt)
        except json.JSONDecodeError:
            continue
    return None


# ─────────────────────────────────────────────────────────────────────
# Pipeline
# ─────────────────────────────────────────────────────────────────────


def base(pass_label: str, strategy: str, tool_group: str, stage: str) -> Path:
    return OUT_DIR / f"{pass_label}__{strategy}__{tool_group}__{stage}"


def _log(msg: str) -> None:
    if HAS_TQDM and sys.stdout.isatty():
        tqdm.write(msg)
    else:
        print(msg, flush=True)


def stage_generate(pass_label: str, strategy: str, tool_group_name: str, model: str) -> Path | None:
    out = base(pass_label, strategy, tool_group_name, "1_generate.json")
    if out.exists():
        return out
    raw_out = base(pass_label, strategy, tool_group_name, "1_generate.raw.txt")
    spec = TOOL_GROUPS[tool_group_name]["spec"]
    prompt = build_gen_prompt(STRATEGIES[strategy], spec)
    t0 = time.time()
    try:
        raw = query(model, prompt, temperature=0.5)
    except Exception as e:
        _log(f"  [gen  {model}] {pass_label}/{strategy}/{tool_group_name}: ERROR {e}")
        return None
    raw_out.write_text(raw)
    examples = extract_json_array(raw)
    if examples is None:
        _log(f"  [gen  {model}] {pass_label}/{strategy}/{tool_group_name}: parse failed after {time.time()-t0:.1f}s (raw saved)")
        return None
    out.write_text(json.dumps(examples, indent=2))
    _log(f"  [gen  {model}] {pass_label}/{strategy}/{tool_group_name}: {len(examples)} examples in {time.time()-t0:.1f}s")
    return out


def stage_validate(gen_path: Path, tool_group_name: str) -> Path:
    """Mechanical validation. No model call. Always produces output."""
    out = gen_path.with_name(gen_path.name.replace("1_generate", "1b_validate"))
    if out.exists():
        return out
    examples = json.loads(gen_path.read_text())
    report = validate_examples(examples, TOOL_GROUPS[tool_group_name])
    out.write_text(json.dumps(report, indent=2))
    _log(f"  [val ] {gen_path.stem}: {report['passing']}/{report['total']} pass")
    return out


def stage_critique(gen_path: Path, val_path: Path, critic_model: str) -> Path | None:
    out = gen_path.with_name(gen_path.name.replace("1_generate", "2_critique"))
    if out.exists():
        return out
    raw_out = out.with_suffix(".raw.txt")
    examples_json = gen_path.read_text()
    validator_report = val_path.read_text()
    prompt = CRITIC_PROMPT_TEMPLATE.format(
        validator_report=validator_report,
        examples_json=examples_json,
    )
    t0 = time.time()
    try:
        raw = query(critic_model, prompt, temperature=0.2)
    except Exception as e:
        _log(f"  [crit {critic_model}] {gen_path.stem}: ERROR {e}")
        return None
    raw_out.write_text(raw)
    issues = extract_json_array(raw)
    if issues is None:
        _log(f"  [crit {critic_model}] {gen_path.stem}: parse failed after {time.time()-t0:.1f}s")
        return None
    out.write_text(json.dumps(issues, indent=2))
    _log(f"  [crit {critic_model}] {gen_path.stem}: {len(issues)} issues in {time.time()-t0:.1f}s")
    return out


def stage_refine(gen_path: Path, val_path: Path, crit_path: Path, refiner_model: str) -> Path | None:
    out = gen_path.with_name(gen_path.name.replace("1_generate", "3_refine"))
    if out.exists():
        return out
    raw_out = out.with_suffix(".raw.txt")
    original = gen_path.read_text()
    validator_report = val_path.read_text()
    issues = crit_path.read_text()
    prompt = REFINE_PROMPT_TEMPLATE.format(
        original=original,
        validator_report=validator_report,
        issues=issues,
    )
    t0 = time.time()
    try:
        raw = query(refiner_model, prompt, temperature=0.3, max_tokens=8000)
    except Exception as e:
        _log(f"  [ref  {refiner_model}] {gen_path.stem}: ERROR {e}")
        return None
    raw_out.write_text(raw)
    refined = extract_json_array(raw)
    if refined is None:
        _log(f"  [ref  {refiner_model}] {gen_path.stem}: parse failed after {time.time()-t0:.1f}s")
        return None
    out.write_text(json.dumps(refined, indent=2))

    # Also validate the refined output — this is the useful signal
    refined_report = validate_examples(refined, TOOL_GROUPS[gen_path.stem.split("__")[2]])
    refined_val = out.with_name(out.name.replace("3_refine", "3b_refine_validate"))
    refined_val.write_text(json.dumps(refined_report, indent=2))

    _log(f"  [ref  {refiner_model}] {gen_path.stem}: {len(refined)} examples "
         f"({refined_report['passing']}/{refined_report['total']} pass) in {time.time()-t0:.1f}s")
    return out


# ─────────────────────────────────────────────────────────────────────
# Passes
# ─────────────────────────────────────────────────────────────────────

PASSES = {
    "A": {"gen": MODEL_CODER,     "crit": MODEL_QWEN,      "ref": MODEL_CODER},
    "B": {"gen": MODEL_QWEN,      "crit": MODEL_CODER,     "ref": MODEL_QWEN},
    "C": {"gen": MODEL_GLM,       "crit": MODEL_QWEN3,     "ref": MODEL_GLM},
    "D": {"gen": MODEL_QWEN3,     "crit": MODEL_GLM,       "ref": MODEL_QWEN3},
    "E": {"gen": MODEL_CODEGEMMA, "crit": MODEL_CODER,     "ref": MODEL_CODEGEMMA},
    # Optimized passes based on grid results
    "F": {"gen": MODEL_CODER,     "crit": MODEL_CODER_3B,  "ref": MODEL_CODER},    # best quality
    "G": {"gen": MODEL_CODER_3B,  "crit": MODEL_CODER,     "ref": MODEL_CODER_3B}, # fastest
}


def check_models_available(required: set[str]) -> tuple[bool, set[str]]:
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
    ap.add_argument("--pass", dest="pass_label",
                    choices=list(PASSES.keys()) + ["all"], default="all")
    ap.add_argument("--skip-missing", action="store_true")
    args = ap.parse_args()

    passes = list(PASSES.keys()) if args.pass_label == "all" else [args.pass_label]

    needed = {PASSES[p][role] for p in passes for role in ("gen", "crit", "ref")}
    ok, missing = check_models_available(needed)
    if not ok:
        print(f"Missing models: {sorted(missing)}")
        if args.skip_missing:
            passes = [p for p in passes
                      if not (set(PASSES[p].values()) & missing)]
            print(f"Remaining passes: {passes}")
            if not passes:
                return 1
        else:
            print("Pass --skip-missing to run available passes.")
            return 1

    tasks = [(p, s, t) for p in passes for s in STRATEGIES for t in TOOL_GROUPS]
    total = len(tasks)
    print(f"Grid: {len(passes)} × {len(STRATEGIES)} × {len(TOOL_GROUPS)} = {total} cells")
    for label in passes:
        cfg = PASSES[label]
        print(f"  Pass {label}: gen={cfg['gen']}  crit={cfg['crit']}  ref={cfg['ref']}")
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
        _set("validate")
        val_path = stage_validate(gen_path, tool_group)
        _set("critique")
        crit_path = stage_critique(gen_path, val_path, p["crit"])
        if crit_path is None:
            continue
        _set("refine")
        stage_refine(gen_path, val_path, crit_path, p["ref"])
        if not use_tqdm:
            print()

    n_gen = len(list(OUT_DIR.glob("*1_generate.json")))
    n_val = len(list(OUT_DIR.glob("*1b_validate.json")))
    n_crit = len(list(OUT_DIR.glob("*2_critique.json")))
    n_ref = len(list(OUT_DIR.glob("*3_refine.json")))
    n_ref_val = len(list(OUT_DIR.glob("*3b_refine_validate.json")))

    # Aggregate pass rates for quick feedback
    before_total = before_pass = 0
    after_total = after_pass = 0
    for p in OUT_DIR.glob("*1b_validate.json"):
        r = json.loads(p.read_text())
        before_total += r["total"]
        before_pass += r["passing"]
    for p in OUT_DIR.glob("*3b_refine_validate.json"):
        r = json.loads(p.read_text())
        after_total += r["total"]
        after_pass += r["passing"]

    total_time = time.time() - t_start
    print()
    print(f"Done in {total_time/60:.1f} min. gen={n_gen} val={n_val} crit={n_crit} ref={n_ref} ref_val={n_ref_val}")
    if before_total:
        print(f"Validation pass rate — initial: {before_pass}/{before_total} ({100*before_pass/before_total:.0f}%)"
              + (f"  refined: {after_pass}/{after_total} ({100*after_pass/after_total:.0f}%)"
                 if after_total else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
