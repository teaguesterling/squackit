#!/usr/bin/env python3
"""Model card generator — tests each model across task categories.

Tests models in raw completion mode (cascade-style) across:
  1. Simple tool calls (single tool, obvious mapping)
  2. Selector generation (CSS-like AST selectors)
  3. Multi-step programs (variable assignment + chaining)
  4. Classification / routing (pick the right tool)
  5. Code generation (small edits, not tool calls)
  6. Structured output (JSON)

Results are saved as JSON for analysis.

Usage:
    python scripts/model_cards.py                     # test all models
    python scripts/model_cards.py --models qwen2.5-coder:3b phi4-mini:latest
"""

from __future__ import annotations

import argparse
import ast
import json
import time
import urllib.request
from pathlib import Path

OLLAMA_HOST = "http://localhost:11435"
OUT_DIR = Path(__file__).parent / "model_card_results"
OUT_DIR.mkdir(exist_ok=True)

# ─────────────────────────────────────────────────────────────────────
# Test battery
# ─────────────────────────────────────────────────────────────────────

TESTS = {
    "simple_tool_call": {
        "description": "Single tool, obvious intent-to-tool mapping",
        "prompt_style": "completion",
        "cases": [
            {
                "id": "stc_1",
                "prompt": "find all function names -> find_names('src/**/*.py', '.fn')\nfind all classes -> find_names('src/**/*.py', '.class')\nshow me the main function -> view('src/**/*.py', '.fn#main')\nlist all function names in cli.py ->",
                "accept": lambda code: "find_names" in code and "cli.py" in code,
                "description": "find_names on a specific file",
            },
            {
                "id": "stc_2",
                "prompt": "find all function names -> find_names('src/**/*.py', '.fn')\nget an overview of the codebase -> explore()\nreview changes since main -> review('main', 'HEAD')\nsearch for cache in the codebase ->",
                "accept": lambda code: "search" in code and "cache" in code,
                "description": "search with a keyword",
            },
            {
                "id": "stc_3",
                "prompt": "find all function names -> find_names('src/**/*.py', '.fn')\nread lines 1-20 of server.py -> read_source('server.py', '1-20')\nget an overview of the codebase -> explore()\nshow recent commits ->",
                "accept": lambda code: "recent_changes" in code,
                "description": "recent_changes",
            },
        ],
    },
    "selector_generation": {
        "description": "Generate correct CSS-like AST selectors",
        "prompt_style": "completion",
        "cases": [
            {
                "id": "sel_1",
                "prompt": "find all function names -> find_names('src/**/*.py', '.fn')\nfind all classes -> find_names('src/**/*.py', '.class')\nfind methods of the Auth class ->",
                "accept": lambda code: ".class#Auth" in code and ".fn" in code,
                "description": "descendant selector .class#Auth .fn",
            },
            {
                "id": "sel_2",
                "prompt": "find all function names -> find_names('src/**/*.py', '.fn')\nfind functions starting with test_ -> source = \"tests/**/*.py\"\nselector = \".fn[name^='test_']\"\nresult = find_names(source, selector)\nresult\nfind functions ending with _handler ->",
                "accept": lambda code: "name$=" in code or "name$='" in code,
                "description": "suffix selector [name$='_handler']",
            },
            {
                "id": "sel_3",
                "prompt": "find all function names -> find_names('src/**/*.py', '.fn')\nfind all classes -> find_names('src/**/*.py', '.class')\nfind all functions except main ->",
                "accept": lambda code: ":not" in code and "main" in code,
                "description": "negation selector :not(#main)",
            },
        ],
    },
    "multi_step": {
        "description": "Variable assignment + multi-line programs",
        "prompt_style": "completion",
        "cases": [
            {
                "id": "ms_1",
                "prompt": "find all function names -> find_names('src/**/*.py', '.fn')\ncount functions in cli.py -> n = len(find_names('cli.py', '.fn'))\ncount classes in the project ->",
                "accept": lambda code: "len(" in code and "find_names" in code and ".class" in code,
                "description": "count with len() wrapper",
            },
            {
                "id": "ms_2",
                "prompt": "find functions starting with test_ -> source = \"tests/**/*.py\"\nselector = \".fn[name^='test_']\"\nresult = find_names(source, selector)\nresult\nfind classes starting with Base ->",
                "accept": lambda code: "source" in code and "selector" in code and "Base" in code,
                "description": "variable assignment pattern for complex selector",
            },
        ],
    },
    "classification": {
        "description": "Pick the right tool from context",
        "prompt_style": "completion",
        "cases": [
            {
                "id": "cls_1",
                "prompt": "find all function names -> find_names('src/**/*.py', '.fn')\ntell me about validate_token -> investigate('validate_token')\nreview changes since main -> review('main', 'HEAD')\ntell me about the UserService class ->",
                "accept": lambda code: "investigate" in code and "UserService" in code,
                "description": "investigate for 'tell me about X'",
            },
            {
                "id": "cls_2",
                "prompt": "find all function names -> find_names('src/**/*.py', '.fn')\nshow me the main function -> view('src/**/*.py', '.fn#main')\nfind the most complex functions -> complexity('src/**/*.py', '.fn')\nshow me the AuthService class ->",
                "accept": lambda code: "view" in code and "AuthService" in code,
                "description": "view for 'show me X' (not find_names)",
            },
        ],
    },
    "code_snippet": {
        "description": "Generate small code snippets (not tool calls)",
        "prompt_style": "code",
        "cases": [
            {
                "id": "code_1",
                "prompt": "# Python: reverse a string\ndef reverse_string(s: str) -> str:\n    return",
                "accept": lambda code: "[::-1]" in code or "reversed" in code,
                "description": "string reversal",
            },
            {
                "id": "code_2",
                "prompt": "# Python: check if a number is prime\ndef is_prime(n: int) -> bool:\n    if n < 2:\n        return False\n    for i in range(",
                "accept": lambda code: ("range(" in code or "sqrt" in code) and "return" in code.lower(),
                "description": "primality check",
            },
            {
                "id": "code_3",
                "prompt": "# Python: flatten a nested list\ndef flatten(lst: list) -> list:",
                "accept": lambda code: ("for" in code or "isinstance" in code or "itertools" in code) and ("append" in code or "extend" in code or "yield" in code or "chain" in code or "+" in code),
                "description": "flatten nested list",
            },
        ],
    },
    "json_output": {
        "description": "Generate valid JSON",
        "prompt_style": "json",
        "cases": [
            {
                "id": "json_1",
                "prompt": '{"name": "Alice", "age": 30}\n{"name": "Bob", "age": 25}\n{"name": "Charlie", "age":',
                "accept": lambda code: code.strip().endswith("}") and '"age"' in code,
                "description": "complete a JSON object",
            },
            {
                "id": "json_2",
                "prompt": 'Classify the intent as JSON:\nIntent: "find all test functions"\n{"tool": "find_names", "selector": ".fn[name^=\'test_\']"}\nIntent: "show me the main class"\n{"tool":',
                "accept": lambda code: '"view"' in code or '"find"' in code,
                "description": "classify intent as JSON",
            },
        ],
    },
}


def query_raw(model: str, prompt: str, max_tokens: int = 100,
              timeout: int = 180) -> tuple[str, float, int]:
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
    """Extract first meaningful output from raw completion."""
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


def run_test(model: str, test: dict) -> dict:
    """Run a single test case against a model."""
    try:
        raw, elapsed, tokens = query_raw(model, test["prompt"])
        output = extract_first_output(raw)
        passed = test["accept"](output)
        tps = tokens / elapsed if elapsed > 0 else 0
        return {
            "id": test["id"],
            "description": test["description"],
            "passed": passed,
            "output": output[:200],
            "raw": raw[:300],
            "elapsed": round(elapsed, 2),
            "tokens": tokens,
            "tps": round(tps, 1),
        }
    except Exception as e:
        return {
            "id": test["id"],
            "description": test["description"],
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
    ap.add_argument("--models", nargs="+", default=None,
                    help="Models to test (default: all available)")
    ap.add_argument("--categories", nargs="+", default=None,
                    help="Test categories to run (default: all)")
    args = ap.parse_args()

    # Discover models
    with urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=10) as resp:
        body = json.loads(resp.read())
    available = sorted(m["name"] for m in body.get("models", []))

    if args.models:
        models = [m for m in args.models if m in available]
    else:
        # Skip very large models that won't fit in memory
        models = [m for m in available if body.get("models", [])]
        sizes = {m["name"]: m.get("size", 0) for m in body.get("models", [])}
        models = [m for m in available if sizes.get(m, 0) < 15e9]

    categories = args.categories or list(TESTS.keys())

    total_tests = sum(len(TESTS[c]["cases"]) for c in categories)
    print(f"Testing {len(models)} models × {total_tests} tests across {len(categories)} categories")
    print(f"Models: {', '.join(models)}")
    print()

    all_results = {}

    for mi, model in enumerate(models, 1):
        print(f"\n{'#'*70}")
        print(f"# [{mi}/{len(models)}] {model}")
        print(f"{'#'*70}")

        model_results = {"model": model, "categories": {}}
        model_pass = 0
        model_total = 0

        for cat_name in categories:
            cat = TESTS[cat_name]
            cat_results = []

            for test in cat["cases"]:
                result = run_test(model, test)
                cat_results.append(result)
                model_total += 1
                if result["passed"]:
                    model_pass += 1

                status = "PASS" if result["passed"] else "FAIL"
                print(f"  {status:4s} {test['id']:8s} {result['elapsed']:5.1f}s {result['tps']:5.1f}t/s | {test['description']}")
                if result.get("output"):
                    print(f"         {result['output'][:80]}")

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

        # Save incrementally
        out_path = OUT_DIR / f"{model.replace(':', '_').replace('/', '_')}.json"
        out_path.write_text(json.dumps(model_results, indent=2))

    # Print summary table
    print(f"\n\n{'='*90}")
    print(f"{'Model':30s}", end="")
    for cat in categories:
        print(f" {cat[:8]:>8s}", end="")
    print(f" {'Total':>7s} {'Rate':>6s} {'Avg(s)':>7s}")
    print("-" * 90)

    for model in models:
        r = all_results[model]
        print(f"{model:30s}", end="")
        for cat in categories:
            cr = r["categories"].get(cat, {"passed": 0, "total": 0})
            print(f" {cr['passed']:>3d}/{cr['total']:<3d}", end="")
        print(f" {r['total_passed']:>3d}/{r['total_tests']:<3d} {r['pass_rate']:>5.0f}% {r['avg_time']:>6.1f}s")

    # Save summary
    summary_path = OUT_DIR / "summary.json"
    summary_path.write_text(json.dumps(all_results, indent=2, default=str))
    print(f"\nResults saved to {OUT_DIR}/")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
