#!/usr/bin/env python3
"""Hard/underspecified task evaluation for larger models.

Tests models on tasks that require more reasoning:
  - Ambiguous intents (multiple valid interpretations)
  - Multi-step reasoning (chained operations)
  - Underspecified queries (model must infer parameters)
  - Novel combinations (tools used in unexpected ways)
  - Error recovery patterns (what does model do with bad input?)

Usage:
    python scripts/hard_tasks.py --models qwen2.5-coder:7b deepseek-coder-v2:16b
    python scripts/hard_tasks.py --models llama3.1:70b --timeout 300
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.request
from pathlib import Path

OLLAMA_HOST = "http://localhost:11435"
OUT_DIR = Path(__file__).parent / "hard_task_results"
OUT_DIR.mkdir(exist_ok=True)

# Few-shot context (same as cascade default examples)
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
show docs about authentication -> doc_outline('docs/**/*.md', search='authentication')
show recent commits -> recent_changes(10)
what files changed since main -> file_changes('main', 'HEAD')
find functions starting with test_ -> source = "tests/**/*.py"
selector = ".fn[name^='test_']"
result = find_names(source, selector)
result"""

HARD_TESTS = {
    "ambiguous_intent": {
        "description": "Ambiguous requests where the model must pick a reasonable interpretation",
        "cases": [
            {
                "id": "amb_1",
                "intent": "what's going on in auth.py",
                "accept": lambda code: any(t in code for t in ["view(", "find_names(", "explore(", "investigate("]) and "auth" in code.lower(),
                "description": "vague 'what's going on' — any exploration tool is valid",
            },
            {
                "id": "amb_2",
                "intent": "help me understand the codebase",
                "accept": lambda code: any(t in code for t in ["explore(", "find_names(", "complexity("]),
                "description": "very vague — should pick explore() or structural overview",
            },
            {
                "id": "amb_3",
                "intent": "anything weird in the tests",
                "accept": lambda code: ("test" in code.lower() or "tests" in code.lower()) and any(t in code for t in ["find_names(", "complexity(", "find(", "search("]),
                "description": "subjective 'weird' — should look at test structure",
            },
        ],
    },
    "multi_step_reasoning": {
        "description": "Tasks requiring chained operations or intermediate variables",
        "cases": [
            {
                "id": "msr_1",
                "intent": "compare how many functions vs classes we have",
                "accept": lambda code: "len(" in code and "find_names" in code and ".fn" in code and ".class" in code,
                "description": "count both functions and classes",
            },
            {
                "id": "msr_2",
                "intent": "find the biggest class and show me its methods",
                "accept": lambda code: ("complexity(" in code or "find(" in code) and (".class" in code) and (".fn" in code or "view(" in code),
                "description": "two-step: find class, then inspect it",
            },
            {
                "id": "msr_3",
                "intent": "check if there are any functions that aren't tested",
                "accept": lambda code: "find_names" in code and (".fn" in code) and ("test" in code.lower()),
                "description": "compare function list against test coverage",
            },
            {
                "id": "msr_4",
                "intent": "show me what changed and review it",
                "accept": lambda code: ("review(" in code or "file_changes(" in code or "recent_changes" in code),
                "description": "git-aware review workflow",
            },
        ],
    },
    "underspecified": {
        "description": "Queries missing key parameters the model must infer",
        "cases": [
            {
                "id": "und_1",
                "intent": "find all the handlers",
                "accept": lambda code: "find_names(" in code and ("handler" in code.lower() or "Handler" in code),
                "description": "must infer handler = name suffix/pattern",
            },
            {
                "id": "und_2",
                "intent": "show me the config",
                "accept": lambda code: any(t in code for t in ["view(", "read_source(", "find_names("]) and ("config" in code.lower() or "*.toml" in code or "*.yaml" in code or "*.json" in code or "*.cfg" in code),
                "description": "must infer what 'config' means — file or class",
            },
            {
                "id": "und_3",
                "intent": "how complex is it",
                "accept": lambda code: "complexity(" in code,
                "description": "must infer 'it' = whole codebase functions",
            },
            {
                "id": "und_4",
                "intent": "find the entry point",
                "accept": lambda code: any(t in code for t in ["find_names(", "view(", "search("]) and ("main" in code or "entry" in code or "__main__" in code or "cli" in code.lower()),
                "description": "must infer entry point = main function or __main__",
            },
        ],
    },
    "novel_combinations": {
        "description": "Creative tool use not shown in examples",
        "cases": [
            {
                "id": "nov_1",
                "intent": "find all classes that have more than 5 methods",
                "accept": lambda code: "find_names(" in code and (".class" in code) and ("len(" in code or "count" in code.lower() or ">" in code),
                "description": "filtering by count — requires programmatic approach",
            },
            {
                "id": "nov_2",
                "intent": "find functions that import os or sys",
                "accept": lambda code: any(t in code for t in ["search(", "find(", "find_names("]) and ("os" in code or "sys" in code or "import" in code),
                "description": "cross-referencing imports with functions",
            },
            {
                "id": "nov_3",
                "intent": "generate a summary of all the modules",
                "accept": lambda code: any(t in code for t in ["find_names(", "explore(", "find("]) and (".module" in code or "**/*.py" in code),
                "description": "module-level overview",
            },
        ],
    },
    "selector_edge_cases": {
        "description": "Harder selector patterns not directly in examples",
        "cases": [
            {
                "id": "sec_1",
                "intent": "find all private methods (starting with underscore)",
                "accept": lambda code: "find_names(" in code and ("_'" in code or "_\"" in code) and ("name^=" in code or "#_" in code),
                "description": "prefix selector for underscore convention",
            },
            {
                "id": "sec_2",
                "intent": "find all decorated functions",
                "accept": lambda code: (".decorator" in code or ".fn" in code) and "find_names(" in code,
                "description": "decorator-related query (tricky — decorators are separate nodes)",
            },
            {
                "id": "sec_3",
                "intent": "find all async functions",
                "accept": lambda code: "find_names(" in code and ".fn" in code,
                "description": "async is not a separate type — model should use .fn",
            },
        ],
    },
}


def query_raw(model: str, prompt: str, max_tokens: int = 150,
              timeout: int = 300) -> tuple[str, float, int]:
    data = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "raw": True,
        "options": {
            "temperature": 0.2,
            "num_predict": max_tokens,
            "num_ctx": 2048,
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


def extract_first_output(raw: str) -> str:
    lines = []
    for line in raw.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            break
        if "->" in stripped and lines:
            break
        if stripped.startswith(("To ", "Here", "This ", "Note", "You can", "# ")) and lines:
            break
        if stripped:
            lines.append(stripped)
        elif lines:
            break
    return "\n".join(lines)


def run_test(model: str, test: dict, timeout: int) -> dict:
    prompt = FEW_SHOT + f"\n{test['intent']} ->"
    try:
        raw, elapsed, tokens = query_raw(model, prompt, timeout=timeout)
        output = extract_first_output(raw)
        passed = test["accept"](output)
        tps = tokens / elapsed if elapsed > 0 else 0
        return {
            "id": test["id"],
            "description": test["description"],
            "intent": test["intent"],
            "passed": passed,
            "output": output[:300],
            "raw": raw[:500],
            "elapsed": round(elapsed, 2),
            "tokens": tokens,
            "tps": round(tps, 1),
        }
    except Exception as e:
        return {
            "id": test["id"],
            "description": test["description"],
            "intent": test["intent"],
            "passed": False,
            "output": "",
            "raw": "",
            "elapsed": 0,
            "tokens": 0,
            "tps": 0,
            "error": str(e),
        }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", required=True)
    ap.add_argument("--categories", nargs="+", default=None)
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args()

    categories = args.categories or list(HARD_TESTS.keys())
    total_tests = sum(len(HARD_TESTS[c]["cases"]) for c in categories)
    print(f"Testing {len(args.models)} models × {total_tests} hard tasks")
    print()

    all_results = {}

    for mi, model in enumerate(args.models, 1):
        print(f"\n{'#'*70}")
        print(f"# [{mi}/{len(args.models)}] {model}")
        print(f"{'#'*70}")

        model_results = {"model": model, "categories": {}}
        model_pass = 0
        model_total = 0

        for cat_name in categories:
            cat = HARD_TESTS[cat_name]
            cat_results = []

            for test in cat["cases"]:
                result = run_test(model, test, args.timeout)
                cat_results.append(result)
                model_total += 1
                if result["passed"]:
                    model_pass += 1

                status = "PASS" if result["passed"] else "FAIL"
                print(f"  {status:4s} {test['id']:8s} {result['elapsed']:5.1f}s {result['tps']:5.1f}t/s | {test['description']}")
                if result.get("output"):
                    for line in result["output"].split("\n")[:3]:
                        print(f"         {line[:80]}")

            passed = sum(1 for r in cat_results if r["passed"])
            total = len(cat_results)
            print(f"  --- {cat_name}: {passed}/{total}")

            model_results["categories"][cat_name] = {
                "passed": passed,
                "total": total,
                "results": cat_results,
            }

        model_results["total_passed"] = model_pass
        model_results["total_tests"] = model_total
        model_results["pass_rate"] = round(100 * model_pass / max(model_total, 1), 1)

        avg_time = sum(
            r["elapsed"]
            for cat in model_results["categories"].values()
            for r in cat["results"]
        ) / max(model_total, 1)
        model_results["avg_time"] = round(avg_time, 2)

        print(f"\n  TOTAL: {model_pass}/{model_total} ({model_results['pass_rate']}%) avg {avg_time:.1f}s")

        all_results[model] = model_results
        out_path = OUT_DIR / f"{model.replace(':', '_').replace('/', '_')}.json"
        out_path.write_text(json.dumps(model_results, indent=2))

    # Summary table
    print(f"\n\n{'='*90}")
    print(f"{'Model':35s}", end="")
    for cat in categories:
        print(f" {cat[:8]:>8s}", end="")
    print(f" {'Total':>7s} {'Rate':>6s} {'Avg(s)':>7s}")
    print("-" * 90)

    for model in args.models:
        r = all_results.get(model)
        if not r:
            continue
        print(f"{model:35s}", end="")
        for cat in categories:
            cr = r["categories"].get(cat, {"passed": 0, "total": 0})
            print(f" {cr['passed']:>3d}/{cr['total']:<3d}", end="")
        print(f" {r['total_passed']:>3d}/{r['total_tests']:<3d} {r['pass_rate']:>5.0f}% {r['avg_time']:>6.1f}s")

    summary_path = OUT_DIR / "summary.json"
    summary_path.write_text(json.dumps(all_results, indent=2, default=str))
    print(f"\nResults saved to {OUT_DIR}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
