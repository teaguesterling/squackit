#!/usr/bin/env python3
"""Head-to-head model benchmark on curated examples.

Takes a sample of intents from examples.json, runs each model in raw
completion mode (same as cascade), validates mechanically, measures time.

Usage:
    python scripts/benchmark_models.py                    # default 30 samples
    python scripts/benchmark_models.py --n 50             # 50 samples
    python scripts/benchmark_models.py --models qwen2.5-coder:7b qwen2.5-coder:3b
"""

from __future__ import annotations

import argparse
import ast
import json
import random
import re
import time
import urllib.request
from pathlib import Path

OLLAMA_HOST = "http://localhost:11435"
EXAMPLES_JSON = Path(__file__).parent.parent / "squackit" / "data" / "examples.json"

DEFAULT_MODELS = [
    "qwen2.5-coder:7b",
    "qwen2.5:7b",
    "qwen2.5-coder:3b",
]

STATIC_FEW_SHOT = """\
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


def build_few_shot(test_intent: dict, n_retrieval: int = 10) -> str:
    """Build few-shot prompt with retrieval from curated examples.

    Includes static examples + retrieved examples matching the test intent's
    tool. This simulates what the cascade would do with a retrieval system.
    """
    data = json.loads(EXAMPLES_JSON.read_text())
    all_examples = data["examples"]

    target_tool = test_intent.get("tool", "")
    target_tags = set(test_intent.get("tags", []))

    # Score examples by relevance
    scored = []
    for ex in all_examples:
        if "anti_pattern" in ex.get("tags", []):
            continue
        intent = ex.get("intent", "")
        if intent.lower() in {"", "natural language request"}:
            continue
        # Don't include the exact test intent
        if ex.get("code", "") == test_intent.get("code", ""):
            continue
        score = 0
        if ex.get("tool") == target_tool:
            score += 3
        ex_tags = set(ex.get("tags", []))
        score += len(target_tags & ex_tags)
        scored.append((score, ex))

    scored.sort(key=lambda x: -x[0])
    retrieved = scored[:n_retrieval]

    lines = []
    # Add retrieved examples first (tool-specific)
    for _, ex in retrieved:
        code = ex["code"]
        if "\n" in code:
            lines.append(f"{ex['intent']} -> {code}")
        else:
            lines.append(f"{ex['intent']} -> {code}")

    # Add static examples for breadth
    lines.append(STATIC_FEW_SHOT)

    return "\n".join(lines)


def query_raw(model: str, prompt: str, max_tokens: int = 80,
              timeout: int = 120) -> tuple[str, float, int]:
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
    lines = []
    for line in raw.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            break
        if "->" in stripped and lines:
            break
        if stripped.startswith(("To ", "Here", "This ", "Note", "You can", "# ")):
            break
        if stripped:
            lines.append(stripped)
        elif lines:
            break
    return "\n".join(lines)


def validate_code(code: str, expected_tool: str) -> tuple[bool, str]:
    """Quick mechanical validation: parses as Python and uses a known tool."""
    if not code.strip():
        return False, "empty"
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"syntax: {e.msg}"

    # Check that the expected tool appears somewhere in the code
    calls = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            calls.add(node.func.id)

    if expected_tool in calls:
        return True, "exact match"
    if calls:
        return False, f"wrong tool: {calls}"
    # Might be a variable assignment pattern
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
    if expected_tool in names:
        return True, "name referenced"
    return False, "tool not found"


def load_test_intents(n: int, seed: int = 42) -> list[dict]:
    data = json.loads(EXAMPLES_JSON.read_text())
    examples = data["examples"]
    # Only use positive examples with real intents
    candidates = [
        ex for ex in examples
        if "anti_pattern" not in ex.get("tags", [])
        and ex.get("intent", "").lower() not in {"", "natural language request"}
    ]
    rng = random.Random(seed)
    rng.shuffle(candidates)
    return candidates[:n]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=30, help="Number of test intents")
    ap.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-tokens", type=int, default=80)
    ap.add_argument("--mode", choices=["static", "retrieval", "both"], default="retrieval",
                    help="Few-shot mode: static (cascade default), retrieval (from examples.json), both")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    # Check models available
    try:
        with urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=10) as resp:
            body = json.loads(resp.read())
        available = {m["name"] for m in body.get("models", [])}
    except Exception as e:
        print(f"Cannot reach ollama: {e}")
        return 1

    models = [m for m in args.models if m in available]
    missing = [m for m in args.models if m not in available]
    if missing:
        print(f"Missing models (skipping): {missing}")
    if not models:
        print("No models available")
        return 1

    intents = load_test_intents(args.n, args.seed)
    print(f"Benchmark: {len(intents)} intents × {len(models)} models")
    print(f"Models: {', '.join(models)}")
    print()

    results: dict[str, dict] = {m: {"pass": 0, "fail": 0, "error": 0,
                                     "total_time": 0.0, "total_tokens": 0,
                                     "times": []} for m in models}

    for i, ex in enumerate(intents, 1):
        intent = ex["intent"]
        tool = ex["tool"]
        expected_code = ex["code"]

        if args.verbose:
            print(f"\n[{i}/{len(intents)}] {intent}")
            print(f"  expected: {expected_code[:80]}")

        few_shot = build_few_shot(ex) if args.mode in ("retrieval", "both") else STATIC_FEW_SHOT

        for model in models:
            prompt = f"{few_shot}\n{intent} ->"
            try:
                raw, elapsed, tokens = query_raw(model, prompt, args.max_tokens)
                code = extract_code(raw)
                ok, reason = validate_code(code, tool)

                results[model]["total_time"] += elapsed
                results[model]["total_tokens"] += tokens
                results[model]["times"].append(elapsed)

                if ok:
                    results[model]["pass"] += 1
                    marker = "OK"
                else:
                    results[model]["fail"] += 1
                    marker = f"FAIL ({reason})"

                if args.verbose:
                    short_model = model.split(":")[0].split("-")[-1]
                    print(f"  {short_model:10s} {elapsed:5.1f}s | {marker:30s} | {code[:60]}")

            except Exception as e:
                results[model]["error"] += 1
                results[model]["times"].append(0)
                if args.verbose:
                    print(f"  {model}: ERROR {e}")

        # Progress line
        if not args.verbose and i % 5 == 0:
            print(f"  {i}/{len(intents)}...", flush=True)

    # Summary
    print(f"\n{'='*75}")
    print(f"{'Model':30s} {'Pass':>6s} {'Fail':>6s} {'Err':>5s} {'Rate':>6s} {'Avg(s)':>7s} {'P50(s)':>7s} {'P95(s)':>7s}")
    print("-" * 75)
    for model in models:
        r = results[model]
        total = r["pass"] + r["fail"] + r["error"]
        rate = 100 * r["pass"] / max(total, 1)
        times = sorted(r["times"]) if r["times"] else [0]
        avg = r["total_time"] / max(total, 1)
        p50 = times[len(times) // 2]
        p95 = times[int(len(times) * 0.95)]
        print(f"{model:30s} {r['pass']:6d} {r['fail']:6d} {r['error']:5d} {rate:5.0f}% {avg:7.1f} {p50:7.1f} {p95:7.1f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
