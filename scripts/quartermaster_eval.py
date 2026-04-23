#!/usr/bin/env python3
"""Quartermaster pattern simulation — can tiny models select the right tools?

Given an intent and a 20+ tool inventory, the model must select the 2-5 tools
needed to accomplish the task. This tests whether 0.5b-3b models can do
tool selection as a classification task.

Usage:
    python scripts/quartermaster_eval.py --models qwen2.5-coder:0.5b qwen2.5-coder:1.5b qwen2.5-coder:3b
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

OLLAMA_HOST = "http://localhost:11435"
OUT_DIR = Path(__file__).parent / "quartermaster_results"
OUT_DIR.mkdir(exist_ok=True)

# ── Tool inventory (realistic squackit/fledgling tools) ──────────

INVENTORY = [
    {"name": "find", "desc": "Find AST nodes matching selectors, returns file paths and line ranges"},
    {"name": "find_names", "desc": "Find names of AST nodes matching selectors, returns list of strings"},
    {"name": "view", "desc": "View rendered source code matching CSS selectors"},
    {"name": "complexity", "desc": "Rank AST nodes by cyclomatic complexity"},
    {"name": "pluck", "desc": "Execute a pluckit chain query with method chaining"},
    {"name": "find_definitions", "desc": "Find function, class, module definitions by AST analysis"},
    {"name": "code_structure", "desc": "Structural overview with complexity metrics per file"},
    {"name": "complexity_hotspots", "desc": "Most complex functions ranked by complexity score"},
    {"name": "read_source", "desc": "Read file contents with optional line range and filtering"},
    {"name": "read_context", "desc": "Read lines centered around a specific line number"},
    {"name": "list_files", "desc": "Find files by glob pattern across the project"},
    {"name": "doc_outline", "desc": "Markdown section outlines with optional keyword search"},
    {"name": "recent_changes", "desc": "Git commit history with author and message"},
    {"name": "file_changes", "desc": "Files changed between two git revisions with status"},
    {"name": "file_diff", "desc": "Line-level unified diff between revisions for a file"},
    {"name": "changed_function_summary", "desc": "Changed functions ranked by complexity between revisions"},
    {"name": "working_tree_status", "desc": "Untracked and modified files in the working tree"},
    {"name": "search_code", "desc": "Full-text search over code definitions and comments"},
    {"name": "search_docs", "desc": "Full-text search over markdown documentation"},
    {"name": "project_overview", "desc": "File counts by language for the entire project"},
    {"name": "explore", "desc": "First-contact codebase briefing: languages, definitions, activity"},
    {"name": "investigate", "desc": "Deep dive on a function: definition, callers, callees"},
    {"name": "review", "desc": "Code review prep: changed files, functions, diffs"},
    {"name": "search", "desc": "Multi-source search across definitions, docs, and call sites"},
]

INVENTORY_TEXT = "\n".join(
    f"  {t['name']}: {t['desc']}" for t in INVENTORY
)

# ── Tasks with expected tool selections ──────────────────────────

TASKS = [
    {
        "id": "qm_1",
        "intent": "count how many functions are in each python file",
        "expected": {"find", "find_names"},
        "accept": {"find", "find_names", "find_definitions", "list_files", "code_structure"},
    },
    {
        "id": "qm_2",
        "intent": "show me the most complex functions in the project",
        "expected": {"complexity", "complexity_hotspots"},
        "accept": {"complexity", "complexity_hotspots", "code_structure", "find"},
    },
    {
        "id": "qm_3",
        "intent": "what changed in the last 5 commits and which functions were affected",
        "expected": {"recent_changes", "changed_function_summary"},
        "accept": {"recent_changes", "changed_function_summary", "file_changes"},
    },
    {
        "id": "qm_4",
        "intent": "find all references to 'cache' in the codebase",
        "expected": {"search_code", "search"},
        "accept": {"search_code", "search", "search_docs"},
    },
    {
        "id": "qm_5",
        "intent": "give me an overview of this project",
        "expected": {"explore", "project_overview"},
        "accept": {"explore", "project_overview", "list_files", "code_structure"},
    },
    {
        "id": "qm_6",
        "intent": "review the changes on this branch compared to main",
        "expected": {"review", "file_changes", "file_diff"},
        "accept": {"review", "file_changes", "file_diff", "changed_function_summary", "working_tree_status"},
    },
    {
        "id": "qm_7",
        "intent": "tell me everything about the validate_token function",
        "expected": {"investigate", "view"},
        "accept": {"investigate", "view", "find", "find_definitions", "read_source", "search_code"},
    },
    {
        "id": "qm_8",
        "intent": "find classes that don't have an __init__ method",
        "expected": {"find_names", "find"},
        "accept": {"find_names", "find", "find_definitions", "code_structure"},
    },
    {
        "id": "qm_9",
        "intent": "read the README and project documentation",
        "expected": {"doc_outline", "read_source"},
        "accept": {"doc_outline", "read_source", "search_docs", "list_files"},
    },
    {
        "id": "qm_10",
        "intent": "check if there are any uncommitted changes",
        "expected": {"working_tree_status"},
        "accept": {"working_tree_status", "file_diff"},
    },
    {
        "id": "qm_11",
        "intent": "find duplicate function names across different files",
        "expected": {"find_names", "find"},
        "accept": {"find_names", "find", "find_definitions"},
    },
    {
        "id": "qm_12",
        "intent": "show me the diff for server.py since last week",
        "expected": {"file_diff"},
        "accept": {"file_diff", "file_changes", "read_source"},
    },
]

# ── Prompt template ──────────────────────────────────────────────

SELECT_PROMPT = """\
You are a tool selector. Given a user intent and a tool inventory, select the 2-5 tools needed.

TOOLS:
{inventory}

Respond with ONLY the tool names, one per line. No explanations.

Intent: {intent}
Tools:"""


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


def parse_selection(raw: str) -> set[str]:
    """Extract tool names from model response."""
    valid_names = {t["name"] for t in INVENTORY}
    selected = set()
    # Split on both newlines and commas to handle varied formats
    chunks = raw.replace(",", "\n").split("\n")
    for chunk in chunks:
        stripped = chunk.strip().strip("-•*123456789.)")
        stripped = stripped.strip()
        for sep in (":", " -", " –", "("):
            if sep in stripped:
                stripped = stripped[:stripped.index(sep)]
        stripped = stripped.strip().lower()
        if stripped in valid_names:
            selected.add(stripped)
    return selected


def score_selection(selected: set[str], expected: set[str], accept: set[str]) -> dict:
    """Score a tool selection against expected and acceptable sets."""
    # Precision: what fraction of selected tools are acceptable?
    precision = len(selected & accept) / len(selected) if selected else 0
    # Recall: what fraction of expected tools were selected?
    recall = len(selected & expected) / len(expected) if expected else 0
    # Any bad picks (tools not in accept set)?
    bad_picks = selected - accept
    # F1
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    return {
        "precision": round(precision, 2),
        "recall": round(recall, 2),
        "f1": round(f1, 2),
        "bad_picks": sorted(bad_picks),
        "selected": sorted(selected),
    }


def run_task(model: str, task: dict) -> dict:
    prompt = SELECT_PROMPT.format(inventory=INVENTORY_TEXT, intent=task["intent"])
    raw, elapsed = query_raw(model, prompt)
    selected = parse_selection(raw)
    scores = score_selection(selected, task["expected"], task["accept"])

    return {
        "id": task["id"],
        "intent": task["intent"],
        "expected": sorted(task["expected"]),
        "accept": sorted(task["accept"]),
        "raw": raw[:400],
        "elapsed": round(elapsed, 2),
        **scores,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+",
                    default=["qwen2.5-coder:0.5b", "qwen2.5-coder:1.5b", "qwen2.5-coder:3b"])
    args = ap.parse_args()

    print(f"Quartermaster tool selection: {len(INVENTORY)} tools × {len(TASKS)} intents × {len(args.models)} models")
    print()

    all_results = {}

    for mi, model in enumerate(args.models, 1):
        print(f"\n{'#'*70}")
        print(f"# [{mi}/{len(args.models)}] {model}")
        print(f"{'#'*70}")

        model_results = []
        for task in TASKS:
            result = run_task(model, task)
            model_results.append(result)

            f1_marker = "OK" if result["f1"] >= 0.5 else "LOW"
            bad = f" BAD:{result['bad_picks']}" if result["bad_picks"] else ""
            print(f"  {f1_marker:3s} {task['id']:6s} ({result['elapsed']:.1f}s) "
                  f"P={result['precision']:.0%} R={result['recall']:.0%} F1={result['f1']:.0%} "
                  f"sel={result['selected']}{bad}")

        avg_f1 = sum(r["f1"] for r in model_results) / len(model_results)
        avg_precision = sum(r["precision"] for r in model_results) / len(model_results)
        avg_recall = sum(r["recall"] for r in model_results) / len(model_results)
        avg_time = sum(r["elapsed"] for r in model_results) / len(model_results)
        good = sum(1 for r in model_results if r["f1"] >= 0.5)

        all_results[model] = {
            "model": model,
            "results": model_results,
            "avg_f1": round(avg_f1, 2),
            "avg_precision": round(avg_precision, 2),
            "avg_recall": round(avg_recall, 2),
            "avg_time": round(avg_time, 2),
            "good_selections": good,
            "total": len(model_results),
        }

        print(f"\n  Summary: {good}/{len(model_results)} good (F1≥0.5), "
              f"avg F1={avg_f1:.0%}, P={avg_precision:.0%}, R={avg_recall:.0%}, "
              f"avg {avg_time:.1f}s")

    # Summary table
    print(f"\n\n{'='*70}")
    print(f"{'Model':30s} {'Good':>6s} {'F1':>6s} {'Prec':>6s} {'Rec':>6s} {'Time':>7s}")
    print("-" * 70)
    for model in args.models:
        r = all_results.get(model, {})
        print(f"{model:30s} {r.get('good_selections',0):>3d}/{r.get('total',0):<3d}"
              f"  {r.get('avg_f1',0):>4.0%}"
              f"  {r.get('avg_precision',0):>4.0%}"
              f"  {r.get('avg_recall',0):>4.0%}"
              f"  {r.get('avg_time',0):>5.1f}s")

    summary_path = OUT_DIR / "summary.json"
    summary_path.write_text(json.dumps(all_results, indent=2, default=str))
    print(f"\nResults saved to {OUT_DIR}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
