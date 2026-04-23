#!/usr/bin/env python3
"""Quartermaster with mechanical retrieval — BM25 pre-filter + model gap check.

Instead of asking a model to select tools from scratch, we:
1. Use DuckDB FTS to retrieve the top-k tools by description similarity
2. Ask a small model: "given these tools, is anything missing?"

This tests whether mechanical retrieval + tiny model review beats
pure model-based selection.

Usage:
    python scripts/qm_retrieval_eval.py
    python scripts/qm_retrieval_eval.py --models qwen2.5-coder:0.5b granite3.3:2b --top-k 5
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

import duckdb

OLLAMA_HOST = "http://localhost:11435"
OUT_DIR = Path(__file__).parent / "quartermaster_results"
OUT_DIR.mkdir(exist_ok=True)

# ── Tool inventory ───────────────────────────────────────────────

INVENTORY = [
    ("find", "Find AST nodes matching CSS selectors. Returns file paths, names, and line ranges as dicts."),
    ("find_names", "Find names of AST nodes matching CSS selectors. Returns a list of name strings."),
    ("view", "View rendered source code matching CSS selectors. Returns markdown with source blocks."),
    ("complexity", "Rank AST nodes by cyclomatic complexity. Returns dicts with name, file path, complexity score."),
    ("pluck", "Execute a pluckit chain query with method chaining and terminals."),
    ("find_definitions", "Find function, class, and module definitions by AST analysis. Returns structured results."),
    ("code_structure", "Structural overview of files with definition counts and complexity metrics."),
    ("complexity_hotspots", "Most complex functions in the codebase ranked by complexity score."),
    ("read_source", "Read file contents with optional line range, match filtering, and context."),
    ("read_context", "Read lines centered around a specific line number with surrounding context."),
    ("list_files", "Find files matching a glob pattern across the project tree."),
    ("doc_outline", "Markdown document section outlines with optional keyword or regex search."),
    ("recent_changes", "Git commit history showing author, date, message, and changed files."),
    ("file_changes", "Files changed between two git revisions with status and size deltas."),
    ("file_diff", "Line-level unified diff between two revisions for a specific file."),
    ("changed_function_summary", "Functions that changed between revisions, ranked by complexity delta."),
    ("working_tree_status", "Untracked and modified files in the current git working tree."),
    ("search_code", "BM25 full-text search over code definitions, identifiers, and comments."),
    ("search_docs", "BM25 full-text search over markdown documentation sections and headings."),
    ("project_overview", "File and language counts for the entire project. Quick structural summary."),
    ("explore", "First-contact codebase briefing covering languages, definitions, docs, and recent activity."),
    ("investigate", "Deep dive on a specific function: definition, source, callers, and callees."),
    ("review", "Code review preparation: changed files, affected functions by complexity, and diffs."),
    ("search", "Multi-source search across code definitions, documentation, and call sites."),
]

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
        "accept": {"file_diff", "file_changes", "read_source", "recent_changes"},
    },
]


# ── DuckDB FTS retrieval ───────────────────────────────��─────────

def setup_fts() -> duckdb.DuckDBPyConnection:
    """Create an in-memory DuckDB with FTS-indexed tool inventory."""
    con = duckdb.connect()
    con.execute("INSTALL fts; LOAD fts;")
    con.execute("""
        CREATE TABLE tools (
            name VARCHAR,
            description VARCHAR
        )
    """)
    con.executemany(
        "INSERT INTO tools VALUES (?, ?)",
        INVENTORY,
    )
    con.execute("""
        PRAGMA create_fts_index('tools', 'name', 'description', overwrite=1)
    """)
    return con


def retrieve_tools(con: duckdb.DuckDBPyConnection, intent: str, top_k: int = 5) -> list[tuple[str, str, float]]:
    """Retrieve top-k tools by BM25 relevance to intent."""
    results = con.execute("""
        SELECT name, description, score
        FROM (
            SELECT *, fts_main_tools.match_bm25(name, ?, conjunctive := 0) AS score
            FROM tools
        )
        WHERE score IS NOT NULL
        ORDER BY score DESC
        LIMIT ?
    """, [intent, top_k]).fetchall()
    return results


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


REVIEW_PROMPT = """\
A user wants to: {intent}

These tools were retrieved for this task:
{retrieved_tools}

Full tool inventory (only add from this list):
{all_tools}

Are any essential tools MISSING from the retrieved set? Reply with ONLY the missing tool names, one per line. If nothing is missing, reply "none".
Missing:"""

ALL_TOOLS_TEXT = "\n".join(f"  {name}: {desc}" for name, desc in INVENTORY)


def parse_additions(raw: str) -> set[str]:
    """Parse model response for additional tool names."""
    valid_names = {name for name, _ in INVENTORY}
    additions = set()
    for line in raw.replace(",", "\n").split("\n"):
        stripped = line.strip().strip("-•*123456789.)")
        stripped = stripped.strip()
        if stripped.lower() in ("none", "none.", "n/a", ""):
            continue
        for sep in (":", " -", " –", "("):
            if sep in stripped:
                stripped = stripped[:stripped.index(sep)]
        stripped = stripped.strip().lower()
        if stripped in valid_names:
            additions.add(stripped)
    return additions


def score_selection(selected: set[str], expected: set[str], accept: set[str]) -> dict:
    precision = len(selected & accept) / len(selected) if selected else 0
    recall = len(selected & expected) / len(expected) if expected else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    bad_picks = selected - accept
    return {
        "precision": round(precision, 2),
        "recall": round(recall, 2),
        "f1": round(f1, 2),
        "bad_picks": sorted(bad_picks),
        "selected": sorted(selected),
    }


# ── Main ─────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+",
                    default=["none", "qwen2.5-coder:0.5b", "qwen2.5:1.5b", "granite3.3:2b", "qwen2.5-coder:3b"])
    ap.add_argument("--top-k", type=int, default=5)
    args = ap.parse_args()

    print("Setting up DuckDB FTS index...")
    con = setup_fts()

    # Phase 1: Score mechanical retrieval alone
    print(f"\n{'='*70}")
    print(f"Phase 1: BM25 retrieval only (top-{args.top_k})")
    print(f"{'='*70}")

    retrieval_results = []
    for task in TASKS:
        retrieved = retrieve_tools(con, task["intent"], args.top_k)
        retrieved_names = {name for name, _, _ in retrieved}
        scores = score_selection(retrieved_names, task["expected"], task["accept"])

        result = {"id": task["id"], "intent": task["intent"], **scores,
                  "retrieved": [(n, round(s, 2)) for n, _, s in retrieved]}
        retrieval_results.append(result)

        f1_marker = "OK" if scores["f1"] >= 0.5 else "LOW"
        bad = f" BAD:{scores['bad_picks']}" if scores["bad_picks"] else ""
        print(f"  {f1_marker:3s} {task['id']:6s} "
              f"P={scores['precision']:.0%} R={scores['recall']:.0%} F1={scores['f1']:.0%} "
              f"sel={scores['selected']}{bad}")
        for name, _, score in retrieved:
            marker = "✓" if name in task["accept"] else " "
            print(f"    {marker} {name:30s} score={score:.2f}")

    avg_f1 = sum(r["f1"] for r in retrieval_results) / len(retrieval_results)
    avg_prec = sum(r["precision"] for r in retrieval_results) / len(retrieval_results)
    avg_rec = sum(r["recall"] for r in retrieval_results) / len(retrieval_results)
    good = sum(1 for r in retrieval_results if r["f1"] >= 0.5)
    print(f"\n  BM25 only: {good}/{len(retrieval_results)} good, "
          f"F1={avg_f1:.0%}, P={avg_prec:.0%}, R={avg_rec:.0%}")

    # Phase 2: BM25 + model review
    all_results = {"bm25_only": {
        "results": retrieval_results,
        "good": good, "total": len(retrieval_results),
        "avg_f1": round(avg_f1, 2), "avg_precision": round(avg_prec, 2),
        "avg_recall": round(avg_rec, 2), "avg_time": 0,
    }}

    models = [m for m in args.models if m != "none"]
    if models:
        print(f"\n{'='*70}")
        print(f"Phase 2: BM25 + model gap check")
        print(f"{'='*70}")

    for mi, model in enumerate(models, 1):
        print(f"\n{'#'*70}")
        print(f"# [{mi}/{len(models)}] BM25 + {model}")
        print(f"{'#'*70}")

        model_results = []
        for task in TASKS:
            retrieved = retrieve_tools(con, task["intent"], args.top_k)
            retrieved_names = {name for name, _, _ in retrieved}
            retrieved_text = "\n".join(
                f"  {name}: {desc}" for name, desc, _ in retrieved
            )

            prompt = REVIEW_PROMPT.format(
                intent=task["intent"],
                retrieved_tools=retrieved_text,
                all_tools=ALL_TOOLS_TEXT,
            )
            raw, elapsed = query_raw(model, prompt)
            additions = parse_additions(raw)
            # Don't let model remove retrieved tools, only add
            final_set = retrieved_names | additions

            scores = score_selection(final_set, task["expected"], task["accept"])
            result = {
                "id": task["id"], "intent": task["intent"],
                "retrieved": sorted(retrieved_names),
                "model_added": sorted(additions),
                "raw": raw[:300],
                "elapsed": round(elapsed, 2),
                **scores,
            }
            model_results.append(result)

            f1_marker = "OK" if scores["f1"] >= 0.5 else "LOW"
            added = f" +{sorted(additions)}" if additions else ""
            bad = f" BAD:{scores['bad_picks']}" if scores["bad_picks"] else ""
            print(f"  {f1_marker:3s} {task['id']:6s} ({elapsed:.1f}s) "
                  f"P={scores['precision']:.0%} R={scores['recall']:.0%} F1={scores['f1']:.0%} "
                  f"bm25={sorted(retrieved_names)}{added}{bad}")

        avg_f1 = sum(r["f1"] for r in model_results) / len(model_results)
        avg_prec = sum(r["precision"] for r in model_results) / len(model_results)
        avg_rec = sum(r["recall"] for r in model_results) / len(model_results)
        avg_time = sum(r["elapsed"] for r in model_results) / len(model_results)
        good = sum(1 for r in model_results if r["f1"] >= 0.5)

        all_results[f"bm25+{model}"] = {
            "model": model,
            "results": model_results,
            "good": good, "total": len(model_results),
            "avg_f1": round(avg_f1, 2), "avg_precision": round(avg_prec, 2),
            "avg_recall": round(avg_rec, 2), "avg_time": round(avg_time, 2),
        }

        print(f"\n  Summary: {good}/{len(model_results)} good, "
              f"F1={avg_f1:.0%}, P={avg_prec:.0%}, R={avg_rec:.0%}, avg {avg_time:.1f}s")

    # Final comparison
    print(f"\n\n{'='*70}")
    print(f"{'Strategy':40s} {'Good':>6s} {'F1':>6s} {'Prec':>6s} {'Rec':>6s} {'Time':>7s}")
    print("-" * 70)
    for key, r in all_results.items():
        print(f"{key:40s} {r['good']:>3d}/{r['total']:<3d}"
              f"  {r['avg_f1']:>4.0%}  {r['avg_precision']:>4.0%}"
              f"  {r['avg_recall']:>4.0%}  {r.get('avg_time',0):>5.1f}s")

    summary_path = OUT_DIR / "retrieval_summary.json"
    summary_path.write_text(json.dumps(all_results, indent=2, default=str))
    print(f"\nResults saved to {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
