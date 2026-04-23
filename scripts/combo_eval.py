#!/usr/bin/env python3
"""Combination evaluation — generate with one model, critique with another.

Tests whether a second model can identify logic errors in generated programs,
and whether a third pass can fix them.

Pipeline: generator -> critic -> (optional) refiner

Usage:
    python scripts/combo_eval.py
"""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

OLLAMA_HOST = "http://localhost:11435"
OUT_DIR = Path(__file__).parent / "combo_results"
OUT_DIR.mkdir(exist_ok=True)

# ── Few-shot for generation (same as multiline_tasks.py) ──────────

GEN_FEW_SHOT = """\
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

# ── Few-shot for critic ──────────────────────────────────────────

CRITIC_FEW_SHOT = """\
Available tools and what they return:
  find_names(source_glob, selector) -> list[str]: returns a list of NAME STRINGS like ['main', 'parse_args']
  find(source_glob, selector) -> list[dict]: returns dicts with {name, file_path, start_line, end_line}
  complexity(source_glob, selector) -> list[dict]: returns dicts with {name, file_path, complexity}
  view(source_glob, selector) -> str: rendered source code
  read_source(file_path, lines?) -> str: file content

IMPORTANT: find_names returns NAMES (strings), NOT file paths. To get file paths, use find().

Review this code for logic errors:
```
files = find_names('src/**/*.py', '.fn')
for f in files:
    count = len(find_names(f, '.fn'))
    print(f, count)
```
Errors found:
1. find_names returns function NAMES like 'main', not file paths. Iterating names as file paths will fail.
Fix: Use find() to get file_path fields, or iterate known file globs.
---
Review this code for logic errors:
```
tested = set(find_names('src/**/*.py', '.fn'))
untested = set(find_names('tests/**/*.py', '.fn')) - tested
print(untested)
```
Errors found:
1. Logic is reversed. This finds test functions NOT in src, not src functions missing tests. Fix: swap the operands.
---
Review this code for logic errors:
```
classes = find_names('src/**/*.py', '.class')
for cls in classes:
    methods = find_names('src/**/*.py', f'.class#{cls} .fn')
    print(f"{cls}: {len(methods)} methods")
```
Errors found:
None. This correctly finds classes then queries methods per class.
---"""

# ── Few-shot for refiner ─────────────────────────────────────────

REFINER_FEW_SHOT = """\
Fix the code based on the errors identified.

Original:
```
files = find_names('src/**/*.py', '.fn')
for f in files:
    count = len(find_names(f, '.fn'))
    print(f, count)
```
Errors: find_names returns names not file paths.
Fixed:
```
results = find('src/**/*.py', '.fn')
files = set(r['file_path'] for r in results)
for f in files:
    fns = find_names(f, '.fn')
    print(f, len(fns))
```
---
Original:
```
tested = set(find_names('src/**/*.py', '.fn'))
untested = set(find_names('tests/**/*.py', '.fn')) - tested
print(untested)
```
Errors: Logic is reversed.
Fixed:
```
src_fns = set(find_names('src/**/*.py', '.fn'))
test_fns = set(find_names('tests/**/*.py', '.fn'))
untested = src_fns - test_fns
print(untested)
```
---"""

TASKS = [
    {
        "id": "combo_1",
        "intent": "for each python file in the project, count functions and classes, print a table",
    },
    {
        "id": "combo_2",
        "intent": "compare the function names in tests/ vs src/ to find untested functions",
    },
    {
        "id": "combo_3",
        "intent": "find all files that have more than 10 functions and rank them",
    },
    {
        "id": "combo_4",
        "intent": "check that every class has at least one method, report any empty classes",
    },
    {
        "id": "combo_5",
        "intent": "find functions longer than 50 lines and flag them as candidates for refactoring",
    },
    {
        "id": "combo_6",
        "intent": "show me a summary: how many functions, classes, and files, plus the top 5 most complex",
    },
    {
        "id": "combo_7",
        "intent": "check if any function appears in multiple files (duplicate function names across modules)",
    },
    {
        "id": "combo_8",
        "intent": "for each class, check if it has an __init__ method, report classes missing one",
    },
]

COMBOS = [
    {"name": "3b-gen_7b-crit_7b-fix", "gen": "qwen2.5-coder:3b", "crit": "qwen2.5-coder:7b", "fix": "qwen2.5-coder:7b"},
    {"name": "7b-gen_3b-crit_3b-fix", "gen": "qwen2.5-coder:7b", "crit": "qwen2.5-coder:3b", "fix": "qwen2.5-coder:3b"},
    {"name": "3b-gen_ds16b-crit_3b-fix", "gen": "qwen2.5-coder:3b", "crit": "deepseek-coder-v2:16b", "fix": "qwen2.5-coder:3b"},
    {"name": "3b-gen_3b-crit_7b-fix", "gen": "qwen2.5-coder:3b", "crit": "qwen2.5-coder:3b", "fix": "qwen2.5-coder:7b"},
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
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def extract_critique(raw: str) -> str:
    lines = []
    for line in raw.split("\n"):
        stripped = line.strip()
        if stripped == "---":
            break
        if stripped.startswith("Review this"):
            break
        if stripped:
            lines.append(line.rstrip())
        elif lines:
            break
    return "\n".join(lines)


def extract_fixed(raw: str) -> str:
    in_code = False
    lines = []
    for line in raw.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```") and not in_code:
            in_code = True
            continue
        if stripped.startswith("```") and in_code:
            break
        if in_code:
            lines.append(line.rstrip())
        elif not in_code and stripped and not stripped.startswith(("Original", "Error", "Fix")):
            lines.append(line.rstrip())
        elif lines and not stripped:
            break
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def run_pipeline(combo: dict, task: dict) -> dict:
    result = {"id": task["id"], "intent": task["intent"], "combo": combo["name"]}

    # Step 1: Generate
    gen_prompt = GEN_FEW_SHOT + f"\n{task['intent']} ->"
    gen_raw, gen_time, gen_tokens = query_raw(combo["gen"], gen_prompt)
    generated = extract_program(gen_raw)
    result["generated"] = generated
    result["gen_time"] = round(gen_time, 2)
    result["gen_model"] = combo["gen"]

    if not generated.strip():
        result["critique"] = "No code generated"
        result["fixed"] = ""
        result["total_time"] = round(gen_time, 2)
        return result

    # Step 2: Critique
    crit_prompt = CRITIC_FEW_SHOT + f"Review this code for logic errors:\n```\n{generated}\n```\nErrors found:"
    crit_raw, crit_time, crit_tokens = query_raw(combo["crit"], crit_prompt, max_tokens=200)
    critique = extract_critique(crit_raw)
    result["critique"] = critique
    result["crit_time"] = round(crit_time, 2)
    result["crit_model"] = combo["crit"]

    # Step 3: Fix (only if errors found)
    has_errors = critique.strip() and "none" not in critique.lower()[:20]
    if has_errors:
        fix_prompt = REFINER_FEW_SHOT + f"Original:\n```\n{generated}\n```\nErrors: {critique}\nFixed:\n```\n"
        fix_raw, fix_time, fix_tokens = query_raw(combo["fix"], fix_prompt)
        fixed = extract_fixed(fix_raw)
        result["fixed"] = fixed
        result["fix_time"] = round(fix_time, 2)
        result["fix_model"] = combo["fix"]
    else:
        result["fixed"] = generated
        result["fix_time"] = 0
        result["fix_model"] = "none"

    result["total_time"] = round(gen_time + crit_time + result.get("fix_time", 0), 2)
    return result


def main() -> int:
    print(f"Testing {len(COMBOS)} model combinations × {len(TASKS)} tasks")
    print(f"Pipeline: generate -> critique -> fix")
    print()

    all_results = {}

    for ci, combo in enumerate(COMBOS, 1):
        print(f"\n{'#'*70}")
        print(f"# [{ci}/{len(COMBOS)}] {combo['name']}")
        print(f"#   gen={combo['gen']}  crit={combo['crit']}  fix={combo['fix']}")
        print(f"{'#'*70}")

        combo_results = []
        for task in TASKS:
            result = run_pipeline(combo, task)
            combo_results.append(result)

            print(f"\n  {task['id']} | {task['intent'][:60]}")
            print(f"  GEN ({result['gen_time']:.1f}s):")
            for line in result["generated"].split("\n")[:6]:
                print(f"    | {line}")

            print(f"  CRIT ({result.get('crit_time', 0):.1f}s):")
            for line in result.get("critique", "").split("\n")[:4]:
                print(f"    > {line}")

            if result.get("fixed") and result["fixed"] != result["generated"]:
                print(f"  FIX ({result.get('fix_time', 0):.1f}s):")
                for line in result["fixed"].split("\n")[:6]:
                    print(f"    + {line}")

            print(f"  TOTAL: {result['total_time']:.1f}s")

        avg_time = sum(r["total_time"] for r in combo_results) / len(combo_results)
        all_results[combo["name"]] = {
            "combo": combo,
            "results": combo_results,
            "avg_time": round(avg_time, 2),
        }
        print(f"\n  Average pipeline time: {avg_time:.1f}s")

        out_path = OUT_DIR / f"{combo['name']}.json"
        out_path.write_text(json.dumps(all_results[combo["name"]], indent=2))

    # Save summary
    summary_path = OUT_DIR / "summary.json"
    summary_path.write_text(json.dumps(all_results, indent=2, default=str))
    print(f"\nResults saved to {OUT_DIR}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
