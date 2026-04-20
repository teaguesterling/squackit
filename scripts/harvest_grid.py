#!/usr/bin/env python3
"""Harvest validated examples from grid passes into a single gold dataset.

Reads all grid output, takes only mechanically-valid examples, deduplicates
by normalized code, and merges with the existing curated examples.json.

Usage:
    python scripts/harvest_grid.py                  # dry-run (stats only)
    python scripts/harvest_grid.py --write           # write merged examples.json
    python scripts/harvest_grid.py --passes A B F    # harvest specific passes
"""

from __future__ import annotations

import argparse
import json
import re
import textwrap
from pathlib import Path

GRID_DIR = Path(__file__).parent / "example_grid_out"
EXAMPLES_JSON = Path(__file__).parent.parent / "squackit" / "data" / "examples.json"


def _normalize_code(code: str) -> str:
    """Normalize code for deduplication — collapse whitespace, strip quotes."""
    c = code.strip()
    c = re.sub(r"\s+", " ", c)
    return c


def _has_real_intent(example: dict) -> bool:
    """Reject examples with placeholder intents."""
    intent = example.get("intent", "")
    return bool(intent) and intent.lower() not in {
        "natural language request",
        "intent",
        "example intent",
        "",
    }


def load_grid_examples(passes: list[str] | None = None) -> list[dict]:
    """Load validated examples from grid output.

    Prefers refined (3_refine.json + 3b_refine_validate.json) when available,
    falls back to initial (1_generate.json + 1b_validate.json).
    """
    examples = []
    seen_cells = set()

    for val_path in sorted(GRID_DIR.glob("*_validate.json")):
        name = val_path.name
        # Determine which cell this belongs to
        if "3b_refine_validate" in name:
            stage = "refined"
            cell_key = name.replace("__3b_refine_validate.json", "")
            examples_path = val_path.with_name(name.replace("3b_refine_validate", "3_refine"))
        elif "1b_validate" in name:
            stage = "initial"
            cell_key = name.replace("__1b_validate.json", "")
            examples_path = val_path.with_name(name.replace("1b_validate", "1_generate"))
        else:
            continue

        # Filter by pass
        pass_label = cell_key.split("__")[0]
        if passes and pass_label not in passes:
            continue

        # Prefer refined over initial
        if stage == "initial" and cell_key in seen_cells:
            continue
        if stage == "refined":
            seen_cells.add(cell_key)

        if not examples_path.exists():
            continue

        try:
            report = json.loads(val_path.read_text())
            all_examples = json.loads(examples_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        # Match examples to validation reports
        for r in report.get("reports", []):
            if not r.get("ok"):
                continue
            idx = r.get("index", -1)
            if idx < 0 or idx >= len(all_examples):
                continue

            ex = dict(all_examples[idx])
            ex["_source"] = f"{cell_key}__{stage}"
            ex["_pass"] = pass_label
            examples.append(ex)

    return examples


def deduplicate(examples: list[dict], existing: list[dict]) -> list[dict]:
    """Deduplicate by normalized code, preferring existing examples."""
    seen = set()

    # Existing examples take priority
    for ex in existing:
        key = _normalize_code(ex.get("code", "") or ex.get("correct_code", ""))
        seen.add(key)

    novel = []
    for ex in examples:
        code = ex.get("code", "")
        if "anti_pattern" in ex.get("tags", []):
            code = ex.get("correct_code", code)
        key = _normalize_code(code)
        if key and key not in seen:
            seen.add(key)
            novel.append(ex)

    return novel


VALID_TOOLS = {
    "after_call", "before_call", "branch_list", "change_mode",
    "changed_function_summary", "commands", "complexity", "confirm",
    "context", "delegate", "diff", "doc_outline", "errors", "event",
    "events", "explore", "file_at_version", "file_changes", "file_diff",
    "find", "find_names", "finish", "generate", "get_prompt_hints",
    "get_suggestions", "history", "investigate", "issue_close", "log",
    "output", "pluck", "pr_comment", "pr_list", "pr_view",
    "read_doc_section", "read_source", "recent_changes", "register_command",
    "report_generation", "review", "run", "save", "search", "ship",
    "start", "status", "structural_diff", "sync", "tag_list", "view",
    "working_tree_status",
}


def _normalize_tool(tool_raw: str) -> str | None:
    """Normalize a tool field to a valid tool name, or None if unrecoverable."""
    if isinstance(tool_raw, list):
        tool_raw = tool_raw[0] if tool_raw else ""
    t = tool_raw.strip()
    if not t:
        return None
    # Strip namespace prefixes: squackit.find_names -> find_names
    if "." in t:
        t = t.rsplit(".", 1)[-1]
    # Reject compound tool fields (commas, parens, spaces)
    if any(c in t for c in ",( "):
        return None
    if t in VALID_TOOLS:
        return t
    return None


def clean_example(ex: dict) -> dict | None:
    """Clean a grid example into the curated format. Returns None if invalid."""
    tool = _normalize_tool(ex.get("tool", ""))
    if tool is None:
        return None

    cleaned = {}
    cleaned["intent"] = ex.get("intent", "").strip()
    cleaned["code"] = ex.get("code", "").strip()

    if not cleaned["intent"] or not cleaned["code"]:
        return None

    if "anti_pattern" in ex.get("tags", []):
        if ex.get("correct_code"):
            cleaned["correct_code"] = ex["correct_code"].strip()

    cleaned["tool"] = tool

    # Build semantic tags
    tags = [t for t in ex.get("tags", []) if t not in {"positive"}]
    if "anti_pattern" not in tags:
        intent_lower = cleaned["intent"].lower()
        tag_words = {
            "function": ["function", "method", "def"],
            "class": ["class"],
            "find": ["find", "search", "locate", "list"],
            "view": ["view", "show", "display", "see"],
            "count": ["count", "how many"],
            "complexity": ["complex"],
            "git": ["commit", "branch", "diff", "change", "merge"],
            "doc": ["doc", "readme", "markdown"],
            "review": ["review"],
            "explore": ["explore", "overview", "codebase"],
        }
        for tag, words in tag_words.items():
            if any(w in intent_lower for w in words) and tag not in tags:
                tags.append(tag)

    if tool not in tags:
        tags.append(tool)

    cleaned["tags"] = tags
    return cleaned


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help="Write merged examples.json")
    ap.add_argument("--passes", nargs="+", help="Harvest specific passes (default: all)")
    ap.add_argument("--stats", action="store_true", help="Show detailed stats")
    args = ap.parse_args()

    # Load existing
    data = json.loads(EXAMPLES_JSON.read_text())
    existing = data["examples"]
    print(f"Existing: {len(existing)} examples")

    # Load grid
    raw = load_grid_examples(args.passes)
    print(f"Grid valid examples: {len(raw)}")

    # Filter placeholder intents
    real = [ex for ex in raw if _has_real_intent(ex)]
    placeholder = len(raw) - len(real)
    print(f"After removing placeholder intents: {len(real)} ({placeholder} removed)")

    # Deduplicate
    novel = deduplicate(real, existing)
    print(f"Novel (deduplicated): {len(novel)}")

    # Clean and filter invalid tools
    cleaned = [c for ex in novel if (c := clean_example(ex)) is not None]
    rejected = len(novel) - len(cleaned)
    print(f"After tool validation: {len(cleaned)} ({rejected} rejected)")

    if args.stats:
        # Stats by tool
        by_tool = {}
        for ex in cleaned:
            t = ex.get("tool", "?")
            by_tool[t] = by_tool.get(t, 0) + 1
        print("\nBy tool:")
        for t in sorted(by_tool):
            print(f"  {t:30s} {by_tool[t]}")

        # Anti-pattern count
        anti = sum(1 for ex in cleaned if "anti_pattern" in ex.get("tags", []))
        print(f"\nPositive: {len(cleaned) - anti}, Anti-pattern: {anti}")

    if args.write:
        merged = existing + cleaned
        data["examples"] = merged
        data["_meta"] = {
            "total": len(merged),
            "curated": len(existing),
            "harvested": len(cleaned),
            "passes": args.passes or "all",
        }
        EXAMPLES_JSON.write_text(json.dumps(data, indent=2) + "\n")
        print(f"\nWrote {len(merged)} examples to {EXAMPLES_JSON}")
    else:
        total = len(existing) + len(cleaned)
        print(f"\nDry run — would produce {total} examples. Use --write to save.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
