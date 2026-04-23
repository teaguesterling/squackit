#!/usr/bin/env python3
"""PSS selector generation eval — can models write CSS selectors for code?

Tests whether small models can generate pluckit CSS selectors from
natural language intents. This is a much more constrained output space
than multi-line Python: one selector string per task.

Two modes:
  ast-select: single bare selector (e.g., .fn:async)
  pss: selector + declaration block (e.g., .fn#main { show: body; })

Uses pluckit to actually execute selectors against squackit's codebase.

Usage:
    python scripts/selector_eval.py --models qwen2.5-coder:3b qwen2.5-coder:7b
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

OLLAMA_HOST = "http://localhost:11435"
OUT_DIR = Path(__file__).parent / "selector_results"
OUT_DIR.mkdir(exist_ok=True)

PROJECT_ROOT = Path(__file__).parent.parent

# ── Selector syntax prompt (from ast_select.py — proven at 93%) ──

SELECTOR_PROMPT = """\
You generate a single CSS-style selector for querying source code ASTs.

Selector syntax:
  .fn                         — all function definitions
  .cls                        — all class definitions
  .fn#NAME                    — function named NAME
  .cls#NAME                   — class named NAME
  .fn[name^="prefix"]         — functions whose name starts with prefix
  .fn:async                   — async functions
  .cls .fn                    — methods inside any class
  .cls#User .fn               — methods inside class User
  .fn:has(.call#execute_sql)  — functions containing a call to execute_sql
  .fn:not([name^="test_"])    — functions not starting with test_

Output: ONE selector, ONE line, nothing else.
No code fences, no Python, no chain syntax, no explanation.

{intent} ->"""

PSS_PROMPT = """\
You generate a pluckit selector sheet: one or more rules,
each a selector followed by a declaration block.

Sheet syntax:
  SELECTOR {{ show: body; }}
  SELECTOR {{ show: signature; }}
  SELECTOR {{ show: outline; }}

Multi-rule sheets are one rule per line.

Selector syntax:
  .fn                         — all function definitions
  .cls                        — all class definitions
  .fn#NAME                    — function named NAME
  .cls#NAME                   — class named NAME
  .fn[name^="prefix"]         — functions whose name starts with prefix
  .fn:async                   — async functions
  .cls .fn                    — methods inside any class
  .cls#User .fn               — methods inside class User

Output ONLY the sheet — no prose, no code fences.

{intent} ->"""

# ── Tasks ────────────────────────────────────────────────────────

TASKS = [
    # ast-select: single selector
    {
        "id": "sel_1",
        "intent": "find all async functions",
        "mode": "ast-select",
        "accept_patterns": [".fn:async"],
        "description": "basic pseudo-class",
    },
    {
        "id": "sel_2",
        "intent": "find all methods inside classes",
        "mode": "ast-select",
        "accept_patterns": [".cls .fn", ".class .fn"],
        "description": "descendant combinator",
    },
    {
        "id": "sel_3",
        "intent": "find the function named create_server",
        "mode": "ast-select",
        "accept_patterns": [".fn#create_server"],
        "description": "ID selector",
    },
    {
        "id": "sel_4",
        "intent": "find functions that start with test_",
        "mode": "ast-select",
        "accept_patterns": ['.fn[name^="test_"]', ".fn[name^='test_']", '.fn[name^=test_]'],
        "description": "attribute prefix selector",
    },
    {
        "id": "sel_5",
        "intent": "find all classes",
        "mode": "ast-select",
        "accept_patterns": [".cls", ".class"],
        "description": "basic type selector",
    },
    {
        "id": "sel_6",
        "intent": "find private functions (names starting with underscore)",
        "mode": "ast-select",
        "accept_patterns": ['.fn[name^="_"]', ".fn[name^='_']", '.fn[name^=_]'],
        "description": "attribute selector for private",
    },
    {
        "id": "sel_7",
        "intent": "find methods of the ToolPresentation class",
        "mode": "ast-select",
        "accept_patterns": [".cls#ToolPresentation .fn", ".class#ToolPresentation .fn"],
        "description": "scoped method query",
    },
    {
        "id": "sel_8",
        "intent": "find functions that are NOT async",
        "mode": "ast-select",
        "accept_patterns": [".fn:not(:async)", ".fn:not(.fn:async)"],
        "description": "negation pseudo-class",
    },
    # pss: selector sheets with display declarations
    {
        "id": "pss_1",
        "intent": "show the body of the main function and the signature of all test functions",
        "mode": "pss",
        "accept_patterns": [".fn#main", "show: body", "test_", "show: signature"],
        "description": "two-rule sheet with different displays",
    },
    {
        "id": "pss_2",
        "intent": "show an outline of all classes and the full body of async functions",
        "mode": "pss",
        "accept_patterns": [".cls", "show: outline", ":async", "show: body"],
        "description": "class outline + async body",
    },
    {
        "id": "pss_3",
        "intent": "show signatures of all functions starting with handle_",
        "mode": "pss",
        "accept_patterns": ["handle_", "show: signature"],
        "description": "filtered signature display",
    },
]


# ── Execution via pluckit ────────────────────────────────────────

def setup_pluckit():
    """Set up pluckit for selector execution."""
    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from pluckit import Plucker
        from pluckit.pluckins.viewer import AstViewer
        from pluckit.pluckins.search import Search
        p = Plucker(code="squackit/**/*.py", plugins=[AstViewer, Search])
        return p
    except Exception as e:
        print(f"Warning: pluckit setup failed: {e}")
        return None


def execute_selector(plucker, selector: str, mode: str) -> dict:
    """Execute a selector against the codebase."""
    if plucker is None:
        return {"success": False, "error": "pluckit not available"}
    try:
        if mode == "ast-select":
            result = plucker.find(selector)
            names = result.names()
            return {
                "success": True,
                "match_count": len(names),
                "names": names[:20],
            }
        elif mode == "pss":
            result = plucker.view(selector)
            md = result.markdown if hasattr(result, 'markdown') else str(result)
            return {
                "success": True,
                "output_len": len(md),
                "preview": md[:200],
            }
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


# ── Model interaction ────────────────────────────────────────────

def query_raw(model: str, prompt: str, max_tokens: int = 80,
              timeout: int = 120) -> tuple[str, float]:
    data = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "raw": True,
        "options": {
            "temperature": 0.1,
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
    return body.get("response", ""), elapsed


def extract_selector(raw: str) -> str:
    """Extract the selector from raw model output."""
    lines = []
    for line in raw.strip().split("\n"):
        stripped = line.strip()
        if not stripped:
            if lines:
                break
            continue
        if stripped.startswith(("```", "Output", "Note", "This", "Here", "The ")):
            break
        if "->" in stripped and lines:
            break
        lines.append(stripped)
    result = "\n".join(lines).strip()
    # Strip backticks models sometimes wrap selectors in
    result = result.strip("`").strip()
    return result


def score_selector(selector: str, task: dict, exec_result: dict) -> dict:
    """Score a generated selector."""
    # Pattern match: does the selector contain expected patterns?
    pattern_hits = sum(
        1 for p in task["accept_patterns"]
        if p.lower() in selector.lower()
    )
    pattern_score = pattern_hits / len(task["accept_patterns"])

    # Execution success
    exec_ok = exec_result.get("success", False)
    has_matches = exec_result.get("match_count", 0) > 0 or exec_result.get("output_len", 0) > 0

    return {
        "pattern_score": round(pattern_score, 2),
        "pattern_hits": pattern_hits,
        "pattern_total": len(task["accept_patterns"]),
        "executes": exec_ok,
        "has_matches": has_matches,
        "pass": pattern_score >= 0.5 and exec_ok,
    }


def run_task(model: str, task: dict, plucker) -> dict:
    prompt_template = PSS_PROMPT if task["mode"] == "pss" else SELECTOR_PROMPT
    prompt = prompt_template.format(intent=task["intent"])

    raw, elapsed = query_raw(model, prompt)
    selector = extract_selector(raw)

    exec_result = execute_selector(plucker, selector, task["mode"])
    scores = score_selector(selector, task, exec_result)

    return {
        "id": task["id"],
        "intent": task["intent"],
        "mode": task["mode"],
        "description": task["description"],
        "selector": selector,
        "raw": raw[:300],
        "elapsed": round(elapsed, 2),
        "exec_result": exec_result,
        **scores,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+",
                    default=["qwen2.5-coder:0.5b", "qwen2.5-coder:1.5b",
                             "qwen2.5-coder:3b", "qwen2.5-coder:7b",
                             "qwen2.5:1.5b", "qwen2.5:7b",
                             "granite3.3:2b", "deepseek-coder-v2:16b"])
    args = ap.parse_args()

    print("Setting up pluckit...")
    plucker = setup_pluckit()
    if plucker:
        print(f"  pluckit ready, source: {PROJECT_ROOT}")
    else:
        print("  pluckit unavailable, scoring patterns only")

    print(f"\n{len(TASKS)} tasks × {len(args.models)} models")
    print()

    all_results = {}

    for mi, model in enumerate(args.models, 1):
        print(f"\n{'#'*70}")
        print(f"# [{mi}/{len(args.models)}] {model}")
        print(f"{'#'*70}")

        model_results = []
        for task in TASKS:
            result = run_task(model, task, plucker)
            model_results.append(result)

            status = "PASS" if result["pass"] else "FAIL"
            exec_info = ""
            if result["executes"]:
                mc = result["exec_result"].get("match_count", "?")
                exec_info = f" matches={mc}"
            elif result["exec_result"].get("error"):
                exec_info = f" err={result['exec_result']['error'][:60]}"

            print(f"  {status:4s} {task['id']:6s} ({result['elapsed']:.1f}s) "
                  f"pat={result['pattern_hits']}/{result['pattern_total']} "
                  f"exec={'OK' if result['executes'] else 'ERR'}{exec_info}")
            print(f"    -> {result['selector'][:80]}")

        passes = sum(1 for r in model_results if r["pass"])
        executes = sum(1 for r in model_results if r["executes"])
        avg_pat = sum(r["pattern_score"] for r in model_results) / len(model_results)
        avg_time = sum(r["elapsed"] for r in model_results) / len(model_results)

        all_results[model] = {
            "model": model,
            "results": model_results,
            "passes": passes,
            "executes": executes,
            "total": len(model_results),
            "avg_pattern_score": round(avg_pat, 2),
            "avg_time": round(avg_time, 2),
        }

        print(f"\n  Summary: {passes}/{len(model_results)} pass, "
              f"{executes}/{len(model_results)} execute, "
              f"avg pattern={avg_pat:.0%}, avg {avg_time:.1f}s")

    # Summary table
    print(f"\n\n{'='*70}")
    print(f"{'Model':30s} {'Pass':>6s} {'Exec':>6s} {'Pat%':>6s} {'Time':>7s}")
    print("-" * 70)
    for model in args.models:
        r = all_results.get(model, {})
        print(f"{model:30s} {r.get('passes',0):>3d}/{r.get('total',0):<3d}"
              f"  {r.get('executes',0):>3d}/{r.get('total',0):<3d}"
              f"  {r.get('avg_pattern_score',0):>4.0%}"
              f"  {r.get('avg_time',0):>5.1f}s")

    summary_path = OUT_DIR / "summary.json"
    summary_path.write_text(json.dumps(all_results, indent=2, default=str))
    print(f"\nResults saved to {OUT_DIR}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
