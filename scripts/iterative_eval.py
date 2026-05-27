#!/usr/bin/env python3
"""Iterative evaluation — generate, execute, observe, fix.

Tests whether small models can iterate on their programs by seeing
real execution results. Uses lackpy's RestrictedRunner to execute
generated programs against actual squackit tools, then feeds errors
and outputs back to the model for correction.

This is the full loop:
  1. Model generates a program from intent
  2. Program executes in lackpy's sandbox against real tools
  3. Model sees the result (success + output, or error message)
  4. If failed, model gets another attempt with the error context
  5. Repeat up to max_iterations

Usage:
    python scripts/iterative_eval.py --models qwen2.5-coder:3b qwen2.5-coder:7b
    python scripts/iterative_eval.py --models qwen2.5-coder:7b --max-iter 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import urllib.request
from pathlib import Path

OLLAMA_HOST = "http://localhost:11435"
OUT_DIR = Path(__file__).parent / "iterative_results"
OUT_DIR.mkdir(exist_ok=True)

# ── Setup lackpy + squackit tools ─────────────────────────────────

def setup_lackpy():
    """Initialize lackpy service with squackit tools."""
    project_root = Path(__file__).parent.parent
    sys.path.insert(0, str(project_root))
    from lackpy.service import LackpyService
    from squackit.lackpy_integration import register_squackit_kit

    svc = LackpyService(workspace=project_root)
    register_squackit_kit(svc.toolbox)
    return svc


def get_runner_and_namespace(svc):
    """Get the restricted runner and resolved tool namespace."""
    from lackpy.kit.registry import resolve_kit
    resolved = resolve_kit(
        ["find_names", "find", "view", "complexity", "read_source"],
        svc.toolbox,
    )
    return svc._runner, resolved.callables, resolved.description


# ── Few-shot prompt ───────────────────────────────────────────────

GEN_FEW_SHOT = """\
Available tools (you can ONLY use these):
  find_names(source, selector) -> list[str]: returns a list of NAME STRINGS
  find(source, selector) -> list[dict]: returns dicts with file_path, name, start_line, end_line
  view(source, selector) -> str: rendered source code as markdown
  complexity(source, selector) -> list[dict]: dicts with name, file_path, complexity
  read_source(file_path, lines?) -> str: read file content

IMPORTANT: find_names returns NAMES (strings like 'main'), NOT file paths.
To get file paths, use find() which returns dicts with 'file_path' key.

Selector syntax: .fn .class .module .fn#main .class#Auth .fn .fn[name^='test_']

Examples:
find all function names -> find_names('src/**/*.py', '.fn')
find all classes -> find_names('src/**/*.py', '.class')
show me the main function -> view('src/**/*.py', '.fn#main')
find methods of the Auth class -> find_names('src/auth.py', '.class#Auth .fn')
count functions in cli.py -> n = len(find_names('squackit/cli.py', '.fn'))
get file paths of all functions -> results = find('squackit/**/*.py', '.fn')
for r in results:
    print(r['file_path'], r['name'])
count functions per file -> results = find('squackit/**/*.py', '.fn')
by_file = {}
for r in results:
    f = r['file_path']
    by_file[f] = by_file.get(f, 0) + 1
for f, n in sorted(by_file.items(), key=lambda x: -x[1]):
    print(f, n)"""

RETRY_TEMPLATE = """\
{few_shot}
{intent} -> {previous_code}
ERROR: {error}
HINT: {hint}
{intent} ->"""


# ── Error classification → distilled hints ────────────────────────
#
# Each hint is 1-3 lines (~20-50 tokens). In production these come
# from a Kibitzer doc query + a distillation agent that picks the
# relevant fragment. Here we hand-write them from observed failures.

def classify_error(error: str, code: str) -> tuple[str, str]:
    """Classify an error and return (category, distilled_hint).

    The hint is a 1-3 line micro-doc targeted at the specific mistake.
    ~20-50 tokens instead of ~200 tokens of full documentation.
    """
    error_lower = error.lower() if error else ""

    # Name resolution — model used unavailable builtins
    if "is not defined" in error_lower:
        missing = error.split("'")[1] if "'" in error else "unknown"
        if missing in ("map", "reduce", "filter"):
            return "sandbox", f"'{missing}' is not available. Use a for loop instead."
        if missing in ("os", "sys", "glob", "re", "pathlib", "subprocess"):
            return "sandbox", f"'{missing}' is not available. Only tool functions and builtins (len, print, sorted, set, list, dict, range, enumerate) are allowed."
        return "unknown_name", f"'{missing}' is not a tool. Available: find_names, find, view, complexity, read_source."

    # KeyError — wrong dict key
    if "keyerror" in error_lower or (error.startswith("'") and error.endswith("'")):
        bad_key = error.strip("'")
        if bad_key == "complexity":
            return "wrong_return_type", "find() returns {{file_path, name, start_line, end_line}} — no 'complexity' key. Use complexity() tool instead."
        if bad_key in ("file", "path", "filename"):
            return "wrong_return_type", f"No '{bad_key}' key. find() returns {{file_path, name, start_line, end_line}}. Use r['file_path']."
        return "wrong_return_type", f"No '{bad_key}' key in result. find() returns {{file_path, name, start_line, end_line}}. complexity() returns {{name, file_path, complexity}}."

    # File not found — names used as paths
    if "does not exist" in error_lower:
        if "find_names" in code:
            return "names_as_paths", "find_names() returns name STRINGS like 'main', not file paths. Use find() to get dicts with 'file_path'."
        return "bad_path", "File not found. Source files are in squackit/ (not src/). Use 'squackit/**/*.py'."

    # IO errors from bad globs
    if "io error" in error_lower or "failed to initialize" in error_lower:
        if "src/" in code and "squackit/" not in code:
            return "wrong_glob", "Wrong path: use 'squackit/**/*.py' not 'src/**/*.py'."
        if "read_ast needs at least one" in error_lower:
            return "empty_glob", "No files matched. Source is in squackit/ not src/. Use 'squackit/**/*.py'."
        return "io_error", "IO error. Check glob path — source is in squackit/**/*.py."

    # Parse errors
    if "parse error" in error_lower or "syntax" in error_lower:
        if "|" in code and any(w in code for w in ("map", "reduce", "grep")):
            return "pipe_syntax", "Pipe syntax (|) is not Python. Use for loops and variable assignment."
        if "->" in (code.split("\n")[0] if code else ""):
            return "arrow_in_code", "'->' is the prompt separator. Don't include it in code."
        return "syntax", "Python syntax error. Check indentation and statement structure."

    # Type errors
    if "typeerror" in error_lower:
        if "not iterable" in error_lower:
            return "type_error", "Tried to iterate a non-iterable. find_names() returns list[str], find() returns list[dict]."
        if "not subscriptable" in error_lower:
            return "type_error", "Tried to index a non-subscriptable. find_names() returns strings, not dicts."
        return "type_error", f"Type error: {error[:80]}"

    return "unknown", f"Error: {error[:100]}. Check tool usage and types."


# ── Tasks ─────────────────────────────────────────────────────────

TASKS = [
    {
        "id": "iter_1",
        "intent": "count how many functions are in each python file in squackit/, print file and count",
        "validate": lambda result: result.success and result.output is not None,
        "description": "per-file function count (needs find() for file paths)",
    },
    {
        "id": "iter_2",
        "intent": "find all classes and list their methods",
        "validate": lambda result: result.success,
        "description": "class method listing",
    },
    {
        "id": "iter_3",
        "intent": "find the 3 most complex functions in squackit/ and show their names and complexity scores",
        "validate": lambda result: result.success and result.output is not None,
        "description": "top-3 complexity ranking",
    },
    {
        "id": "iter_4",
        "intent": "find function names that appear in more than one file (duplicates across modules) in squackit/",
        "validate": lambda result: result.success,
        "description": "cross-module duplicate detection",
    },
    {
        "id": "iter_5",
        "intent": "for each class in squackit/, check if it has an __init__ method",
        "validate": lambda result: result.success,
        "description": "class init audit",
    },
    {
        "id": "iter_6",
        "intent": "find all functions in squackit/ whose names start with _ (private) and group them by file",
        "validate": lambda result: result.success,
        "description": "private function grouping",
    },
]


# ── Model interaction ─────────────────────────────────────────────

def query_raw(model: str, prompt: str, max_tokens: int = 300,
              timeout: int = 300) -> tuple[str, float]:
    data = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "raw": True,
        "options": {
            "temperature": 0.2,
            "num_predict": max_tokens,
            "num_ctx": 4096,
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
    return body.get("response", ""), elapsed


def extract_program(raw: str) -> str:
    lines = []
    for line in raw.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            break
        if "->" in stripped and lines:
            break
        if stripped.startswith(("To ", "Here's", "This ", "Note:", "You can", "The above")):
            break
        if stripped:
            lines.append(line.rstrip())
        elif lines and len(lines) >= 2:
            break
        elif lines:
            lines.append("")
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return ""
    # Strip the leading space that models emit after `->` on the first line,
    # then dedent the rest relative to the first real line.
    first = lines[0]
    leading = len(first) - len(first.lstrip())
    if leading > 0:
        prefix = first[:leading]
        lines = [l[leading:] if l.startswith(prefix) else l for l in lines]
    return "\n".join(lines)


# ── Main loop ─────────────────────────────────────────────────────

def run_task(model: str, task: dict, runner, namespace: dict,
             max_iter: int = 3, editor: str | None = None) -> dict:
    """Run a task with up to max_iter generate-execute-observe cycles.

    If editor is set, retries after the first failure use that model instead.
    """
    iterations = []
    current_prompt = GEN_FEW_SHOT + f"\n{task['intent']} ->"
    current_model = model

    for i in range(max_iter):
        # Generate (switch to editor model after first failure)
        raw, gen_time = query_raw(current_model, current_prompt)
        program = extract_program(raw)

        if not program.strip():
            iterations.append({
                "iteration": i + 1,
                "model_used": current_model,
                "program": "",
                "gen_time": round(gen_time, 2),
                "exec_success": False,
                "error": "Empty program generated",
            })
            break

        # Execute
        exec_result = runner.run(program, namespace)

        output_str = ""
        if exec_result.success:
            if exec_result.output is not None:
                output_str = str(exec_result.output)[:500]
            elif exec_result.variables:
                output_str = str(exec_result.variables)[:500]

        iteration = {
            "iteration": i + 1,
            "model_used": current_model,
            "program": program,
            "gen_time": round(gen_time, 2),
            "exec_success": exec_result.success,
            "output": output_str,
            "error": exec_result.error if not exec_result.success else None,
            "variables": {k: str(v)[:200] for k, v in exec_result.variables.items()} if exec_result.variables else {},
        }
        iterations.append(iteration)

        # Check if we're done
        if exec_result.success and task["validate"](exec_result):
            break

        # Switch to editor model for retries
        if editor:
            current_model = editor

        # Build retry prompt with classified error + distilled hint
        if not exec_result.success:
            category, hint = classify_error(
                exec_result.error or "", program,
            )
            iteration["error_category"] = category
            iteration["hint"] = hint
            current_prompt = RETRY_TEMPLATE.format(
                few_shot=GEN_FEW_SHOT,
                intent=task["intent"],
                previous_code=program,
                error=exec_result.error or "Unknown error",
                hint=hint,
            )
        else:
            current_prompt = RETRY_TEMPLATE.format(
                few_shot=GEN_FEW_SHOT,
                intent=task["intent"],
                previous_code=program,
                error="Program ran but may not fully answer the intent.",
                hint="Check output matches the intent. Ensure all requested information is printed.",
            )

    final = iterations[-1] if iterations else {}
    result = {
        "id": task["id"],
        "intent": task["intent"],
        "description": task["description"],
        "model": model,
        "iterations": iterations,
        "final_success": final.get("exec_success", False),
        "num_iterations": len(iterations),
        "total_gen_time": round(sum(it["gen_time"] for it in iterations), 2),
    }
    if editor:
        result["editor"] = editor
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=["qwen2.5-coder:3b", "qwen2.5-coder:7b"])
    ap.add_argument("--editor", default=None,
                    help="Editor model for fixing failures (if set, retries use this model)")
    ap.add_argument("--max-iter", type=int, default=3)
    ap.add_argument("--tasks", nargs="+", default=None,
                    help="Task IDs to run (default: all)")
    args = ap.parse_args()

    print("Setting up lackpy + squackit tools...")
    svc = setup_lackpy()
    runner, namespace, desc = get_runner_and_namespace(svc)
    print(f"Tools available: {list(namespace.keys())}")
    print(f"Max iterations per task: {args.max_iter}")
    if args.editor:
        print(f"Editor model: {args.editor}")
    print()

    tasks = TASKS
    if args.tasks:
        tasks = [t for t in TASKS if t["id"] in args.tasks]

    all_results = {}

    for mi, model in enumerate(args.models, 1):
        print(f"\n{'#'*70}")
        print(f"# [{mi}/{len(args.models)}] {model}")
        print(f"{'#'*70}")

        model_results = []
        for task in tasks:
            print(f"\n  --- {task['id']}: {task['description']} ---")
            result = run_task(model, task, runner, namespace, args.max_iter, editor=args.editor)
            model_results.append(result)

            for it in result["iterations"]:
                status = "OK" if it["exec_success"] else "ERR"
                cat = f" [{it.get('error_category', '')}]" if it.get("error_category") else ""
                mdl = f" ({it['model_used']})" if it.get('model_used') != model else ""
                print(f"  [{status}] iter {it['iteration']} ({it['gen_time']:.1f}s){cat}{mdl}")
                for line in it["program"].split("\n")[:6]:
                    print(f"    | {line}")
                if it.get("error"):
                    print(f"    ! {it['error'][:120]}")
                if it.get("hint"):
                    print(f"    ? {it['hint'][:120]}")
                if it.get("output"):
                    for line in str(it["output"]).split("\n")[:3]:
                        print(f"    > {line[:100]}")

            final_status = "SUCCESS" if result["final_success"] else "FAILED"
            print(f"  => {final_status} after {result['num_iterations']} iterations ({result['total_gen_time']:.1f}s)")

        successes = sum(1 for r in model_results if r["final_success"])
        avg_iters = sum(r["num_iterations"] for r in model_results) / len(model_results)
        avg_time = sum(r["total_gen_time"] for r in model_results) / len(model_results)

        all_results[model] = {
            "model": model,
            "results": model_results,
            "successes": successes,
            "total": len(model_results),
            "avg_iterations": round(avg_iters, 1),
            "avg_time": round(avg_time, 1),
        }

        print(f"\n  Summary: {successes}/{len(model_results)} succeeded, avg {avg_iters:.1f} iterations, avg {avg_time:.1f}s")

    # Summary table
    print(f"\n\n{'='*70}")
    print(f"{'Model':35s} {'Success':>8s} {'Avg iter':>9s} {'Avg time':>9s}")
    print("-" * 70)
    for model in args.models:
        r = all_results.get(model, {})
        print(f"{model:35s} {r.get('successes',0):>3d}/{r.get('total',0):<3d}   {r.get('avg_iterations',0):>5.1f}     {r.get('avg_time',0):>6.1f}s")

    summary_path = OUT_DIR / "summary.json"
    summary_path.write_text(json.dumps(all_results, indent=2, default=str))
    print(f"\nResults saved to {OUT_DIR}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
