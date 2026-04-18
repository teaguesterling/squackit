"""Cascade inference prototype — compound model with fast-path + fallback.

Tries models in speed order. First one that produces a valid program wins.
Validation is mechanical (AST parse + sandbox check), not model-based.

Usage:
    python scripts/cascade_prototype.py "find all test functions"
    python scripts/cascade_prototype.py "show me the main function"
    python scripts/cascade_prototype.py "count functions in cli.py"
"""

from __future__ import annotations

import ast
import json
import re
import sys
import time
import urllib.request
from dataclasses import dataclass

OLLAMA_HOST = "http://localhost:11435"

# Models in speed order (fastest first)
CASCADE = [
    {"model": "qwen2.5-coder:3b",  "max_tokens": 80,  "timeout": 15},
    {"model": "qwen2.5-coder:7b",  "max_tokens": 120, "timeout": 60},
    {"model": "qwen2.5:7b",        "max_tokens": 120, "timeout": 60},
]

# Tools the sandbox allows
KIT_TOOLS = {
    "find_names", "find", "view", "complexity", "read_source",
    "explore", "investigate", "review", "search",
    "doc_outline", "read_doc_section",
    "recent_changes", "branch_list", "tag_list", "working_tree_status",
    "file_changes", "file_diff", "file_at_version",
    "structural_diff", "changed_function_summary",
    "pluck",
}

ALLOWED_BUILTINS = {
    "len", "sorted", "list", "set", "dict", "tuple", "print", "str",
    "int", "float", "bool", "range", "enumerate", "zip", "min", "max",
    "sum", "any", "all",
}

FORBIDDEN_NODES = {
    ast.FunctionDef, ast.AsyncFunctionDef, ast.Import, ast.ImportFrom,
    ast.ClassDef, ast.Lambda, ast.Try, ast.Raise, ast.With,
}

# Few-shot examples — the core patterns we want the model to complete
EXAMPLES = """\
find all function names -> find_names('src/**/*.py', '.fn')
find all classes -> find_names('src/**/*.py', '.class')
show me the main function -> view('src/**/*.py', '.fn#main')
find methods of the Auth class -> find_names('src/auth.py', '.class#Auth .fn')
count functions in cli.py -> n = len(find_names('squackit/cli.py', '.fn'))
find the most complex functions -> complexity('src/**/*.py', '.fn')
read lines 1-20 of server.py -> read_source('squackit/server.py', '1-20')
get an overview of the codebase -> explore()
tell me about validate_token -> investigate('validate_token')
review changes since main -> review('main', 'HEAD')
search for cache across the codebase -> search('cache')
show docs about authentication -> doc_outline('docs/**/*.md', search='authentication')
show recent commits -> recent_changes(10)
what files changed since main -> file_changes('main', 'HEAD')
find functions starting with test_ -> source = "tests/**/*.py"
selector = ".fn[name^='test_']"
result = find_names(source, selector)
result"""


def build_prompt(intent: str) -> str:
    """Build a completion-style prompt the model just needs to finish."""
    return f"""{EXAMPLES}
{intent} ->"""


def validate(code: str) -> tuple[bool, str]:
    """Mechanical validation. Returns (ok, error_msg)."""
    code = code.strip()
    if not code:
        return False, "empty"

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"SyntaxError: {e.msg}"

    # Collect assigned names
    assigned = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    assigned.add(t.id)
        elif isinstance(node, ast.For) and isinstance(node.target, ast.Name):
            assigned.add(node.target.id)

    known = KIT_TOOLS | ALLOWED_BUILTINS | assigned | {"True", "False", "None"}

    for node in ast.walk(tree):
        if type(node) in FORBIDDEN_NODES:
            return False, f"forbidden: {type(node).__name__}"

        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                return False, f"method call: {func.attr}"
            if isinstance(func, ast.Name) and func.id not in known:
                return False, f"unknown function: {func.id}"

        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id not in known:
                return False, f"undefined name: {node.id}"

    return True, ""


def query_model(model: str, prompt: str, max_tokens: int, timeout: int) -> tuple[str, float, int]:
    """Query ollama. Returns (response_text, elapsed_seconds, token_count)."""
    data = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "raw": True,
        "options": {
            "temperature": 0.2,
            "num_predict": max_tokens,
            "num_ctx": 2048,
            "stop": ["\n\n"],
        },
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/generate",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read())
    elapsed = time.time() - t0
    return body.get("response", ""), elapsed, body.get("eval_count", 0)


def extract_code(raw: str) -> str:
    """Extract the code from a model response.

    The model should just complete the pattern: `intent -> code`
    But it might also emit explanation text, continuation examples, etc.
    Take everything up to the first blank line or next `->`.
    """
    lines = []
    for line in raw.split("\n"):
        stripped = line.strip()
        # Stop at markdown fences, next example, or explanation prose
        if stripped.startswith("```"):
            break
        if "->" in stripped and lines:
            break
        if stripped.startswith(("To ", "Here", "This ", "Note", "You can", "# ")):
            break
        if stripped:
            lines.append(stripped)
        elif lines:
            break  # blank line after code = done
    return "\n".join(lines)


@dataclass
class CascadeResult:
    intent: str
    code: str
    model: str
    elapsed: float
    tokens: int
    attempts: list  # [(model, code, error, elapsed)]
    valid: bool
    error: str


def cascade(intent: str) -> CascadeResult:
    """Try models in order until one produces valid code."""
    prompt = build_prompt(intent)
    attempts = []

    for tier in CASCADE:
        model = tier["model"]
        try:
            raw, elapsed, tokens = query_model(
                model, prompt, tier["max_tokens"], tier["timeout"]
            )
        except Exception as e:
            attempts.append((model, "", str(e), 0))
            continue

        code = extract_code(raw)
        ok, err = validate(code)
        attempts.append((model, code, err, elapsed))

        if ok:
            return CascadeResult(
                intent=intent, code=code, model=model,
                elapsed=elapsed, tokens=tokens,
                attempts=attempts, valid=True, error="",
            )

    # All failed
    last = attempts[-1] if attempts else ("", "", "no models", 0)
    return CascadeResult(
        intent=intent, code=last[1], model="NONE",
        elapsed=sum(a[3] for a in attempts), tokens=0,
        attempts=attempts, valid=False, error=last[2],
    )


def main():
    intents = sys.argv[1:] or [
        "find all function names in squackit/tools.py",
        "show me the validate_token function",
        "what are the most complex functions",
        "find functions that start with test_",
        "count how many functions are in cli.py",
        "find all classes",
        "show me methods of the ToolPresentation class",
        "get an overview of the codebase",
        "review changes since the last commit",
        "search for mutation across the codebase",
        "what files changed in the last commit",
        "read lines 10-30 of server.py",
    ]

    results = []
    for intent in intents:
        r = cascade(intent)
        results.append(r)
        mark = "✅" if r.valid else "❌"
        tier = f"tier {len(r.attempts)}" if r.valid else "FAIL"
        print(f"{mark} {r.elapsed:5.1f}s [{r.model:20s} {tier}] {intent}")
        print(f"   {r.code}")
        if not r.valid:
            for model, code, err, elapsed in r.attempts:
                print(f"   attempt {model}: {err} ({elapsed:.1f}s) -> {code[:60]}")
        print()

    # Summary
    wins = sum(1 for r in results if r.valid)
    avg_time = sum(r.elapsed for r in results if r.valid) / max(wins, 1)
    tier1 = sum(1 for r in results if r.valid and len(r.attempts) == 1)
    tier2 = sum(1 for r in results if r.valid and len(r.attempts) == 2)
    tier3 = sum(1 for r in results if r.valid and len(r.attempts) == 3)
    print(f"Score: {wins}/{len(results)}")
    print(f"Avg time (successes): {avg_time:.1f}s")
    print(f"Resolved at: tier1={tier1} tier2={tier2} tier3={tier3} fail={len(results)-wins}")


if __name__ == "__main__":
    main()
