#!/usr/bin/env python3
"""Multi-line program generation — tests model ability to write 5-10 line programs.

These are realistic tasks where a small model writes a short script
using the squackit tool API. Each solution needs multiple statements:
variable assignments, loops, conditionals, tool calls composed together.

Usage:
    python scripts/multiline_tasks.py --models qwen2.5-coder:7b qwen3.5:2b
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

OLLAMA_HOST = "http://localhost:11435"
OUT_DIR = Path(__file__).parent / "multiline_results"
OUT_DIR.mkdir(exist_ok=True)

FEW_SHOT = """\
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
show recent commits -> recent_changes(10)
what files changed since main -> file_changes('main', 'HEAD')
find functions starting with test_ -> source = "tests/**/*.py"
selector = ".fn[name^='test_']"
result = find_names(source, selector)
result
compare function count across files -> files = ['cli.py', 'server.py', 'auth.py']
for f in files:
    n = len(find_names(f, '.fn'))
    print(f, n)
find the largest class by method count -> classes = find_names('src/**/*.py', '.class')
biggest = None
max_methods = 0
for cls in classes:
    methods = find_names('src/**/*.py', f'.class#{cls} .fn')
    if len(methods) > max_methods:
        max_methods = len(methods)
        biggest = cls
print(biggest, max_methods)"""

TASKS = [
    {
        "id": "ml_1",
        "intent": "for each python file in the project, count functions and classes, print a table",
        "description": "per-file function/class counts as a table",
        "min_lines": 3,
    },
    {
        "id": "ml_2",
        "intent": "find all classes, then for each class show its methods",
        "description": "iterate classes, list methods per class",
        "min_lines": 3,
    },
    {
        "id": "ml_3",
        "intent": "find the 3 most complex functions and show their source code",
        "description": "complexity ranking then view top 3",
        "min_lines": 3,
    },
    {
        "id": "ml_4",
        "intent": "compare the function names in tests/ vs src/ to find untested functions",
        "description": "set difference between src and test function names",
        "min_lines": 3,
    },
    {
        "id": "ml_5",
        "intent": "find all files that have more than 10 functions and rank them",
        "description": "per-file function count with filtering and sorting",
        "min_lines": 4,
    },
    {
        "id": "ml_6",
        "intent": "show me a summary: how many functions, classes, and files, plus the top 5 most complex",
        "description": "multi-metric codebase summary",
        "min_lines": 4,
    },
    {
        "id": "ml_7",
        "intent": "find all classes that have an __init__ method and show what parameters it takes",
        "description": "class init signature inspection",
        "min_lines": 3,
    },
    {
        "id": "ml_8",
        "intent": "for each module, find functions that start with _ (private) and list them grouped by file",
        "description": "grouped private function listing",
        "min_lines": 4,
    },
    # --- Testing / verification tasks ---
    {
        "id": "test_1",
        "intent": "check that every class has at least one method, report any empty classes",
        "description": "verify no empty classes exist",
        "min_lines": 4,
    },
    {
        "id": "test_2",
        "intent": "verify that every test file has at least one function starting with test_, warn about files that don't",
        "description": "test file coverage check",
        "min_lines": 4,
    },
    {
        "id": "test_3",
        "intent": "check if any function appears in multiple files (duplicate function names across modules)",
        "description": "detect duplicate function names",
        "min_lines": 5,
    },
    {
        "id": "test_4",
        "intent": "for each class, verify it has a docstring by checking if the first line after the class starts with a quote",
        "description": "docstring presence check per class",
        "min_lines": 5,
    },
    {
        "id": "test_5",
        "intent": "find functions longer than 50 lines and flag them as candidates for refactoring",
        "description": "long function detection for refactoring",
        "min_lines": 4,
    },
]


def query_raw(model: str, prompt: str, max_tokens: int = 300,
              timeout: int = 300) -> tuple[str, float, int]:
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
    return body.get("response", ""), elapsed, body.get("eval_count", 0)


def extract_program(raw: str) -> str:
    """Extract multi-line program from raw completion.

    More lenient than the single-line extractor — allows multiple
    lines of code up to the first blank line or prose marker.
    """
    lines = []
    for line in raw.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            break
        if "->" in stripped and lines:
            break
        if stripped.startswith(("To ", "Here's", "This ", "Note:", "You can", "The above", "Explanation")):
            break
        if stripped:
            lines.append(line.rstrip())
        elif lines and len(lines) >= 2:
            break
        elif lines:
            lines.append("")
    # Strip trailing blank lines
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def run_test(model: str, task: dict, timeout: int) -> dict:
    prompt = FEW_SHOT + f"\n{task['intent']} ->"
    try:
        raw, elapsed, tokens = query_raw(model, prompt, timeout=timeout)
        program = extract_program(raw)
        line_count = len([l for l in program.split("\n") if l.strip()])
        tps = tokens / elapsed if elapsed > 0 else 0
        return {
            "id": task["id"],
            "description": task["description"],
            "intent": task["intent"],
            "program": program,
            "raw": raw[:800],
            "line_count": line_count,
            "min_lines": task["min_lines"],
            "elapsed": round(elapsed, 2),
            "tokens": tokens,
            "tps": round(tps, 1),
        }
    except Exception as e:
        return {
            "id": task["id"],
            "description": task["description"],
            "intent": task["intent"],
            "program": "",
            "raw": "",
            "line_count": 0,
            "min_lines": task["min_lines"],
            "elapsed": 0,
            "tokens": 0,
            "tps": 0,
            "error": str(e),
        }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", required=True)
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args()

    print(f"Testing {len(args.models)} models × {len(TASKS)} multi-line tasks")
    print(f"Max tokens: 300, context: 4096")
    print()

    all_results = {}

    for mi, model in enumerate(args.models, 1):
        print(f"\n{'#'*70}")
        print(f"# [{mi}/{len(args.models)}] {model}")
        print(f"{'#'*70}")

        results = []
        for task in TASKS:
            result = run_test(model, task, args.timeout)
            results.append(result)

            lines = result["line_count"]
            minl = result["min_lines"]
            met = "OK" if lines >= minl else "SHORT"
            print(f"\n  {met:5s} {task['id']:8s} {result['elapsed']:5.1f}s {result['tps']:5.1f}t/s {lines}lines | {task['description']}")
            for line in result["program"].split("\n")[:10]:
                print(f"    | {line}")
            if result["line_count"] > 10:
                print(f"    | ... ({result['line_count'] - 10} more lines)")

        avg_time = sum(r["elapsed"] for r in results) / len(results)
        avg_lines = sum(r["line_count"] for r in results) / len(results)
        met_min = sum(1 for r in results if r["line_count"] >= r["min_lines"])

        model_data = {
            "model": model,
            "results": results,
            "avg_time": round(avg_time, 2),
            "avg_lines": round(avg_lines, 1),
            "met_minimum": met_min,
            "total": len(results),
        }
        all_results[model] = model_data

        print(f"\n  Summary: {met_min}/{len(results)} met minimum lines, avg {avg_lines:.1f} lines, avg {avg_time:.1f}s")

        out_path = OUT_DIR / f"{model.replace(':', '_').replace('/', '_')}.json"
        out_path.write_text(json.dumps(model_data, indent=2))

    # Summary
    print(f"\n\n{'='*70}")
    print(f"{'Model':35s} {'Met min':>8s} {'Avg lines':>10s} {'Avg time':>9s}")
    print("-" * 70)
    for model in args.models:
        r = all_results[model]
        print(f"{model:35s} {r['met_minimum']:>3d}/{r['total']:<3d}   {r['avg_lines']:>6.1f}     {r['avg_time']:>6.1f}s")

    summary_path = OUT_DIR / "summary.json"
    summary_path.write_text(json.dumps(all_results, indent=2, default=str))
    print(f"\nResults saved to {OUT_DIR}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
