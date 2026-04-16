"""Generate training examples for squackit's lackpy kit using a larger local model.

Strategy: give the 7b+ model meta-awareness that it's producing training data
for a smaller sibling. Bigger models are bad at template-matching in a
restricted sandbox but good at introspecting + generating diverse cases
when explicitly asked to.

Run:
    python scripts/generate_examples.py
"""

from __future__ import annotations

import json
import sys
import urllib.request

OLLAMA_HOST = "http://localhost:11435"
MODEL = "qwen2.5-coder:7b"

PROMPT = """\
You are curating training examples for a 1.5B-parameter sibling model that
will use a code-intelligence toolkit called **squackit** through a restricted
Python sandbox. Your job is to produce diverse, high-quality examples that
teach the smaller model what to generate.

# The environment your sibling runs in

The sandbox allows ONLY these constructs:
- Direct tool calls: `find_names('src/**/*.py', '.fn')`
- Variable assignment: `x = find_names(...)`
- Bare expressions (to return a value): `x`
- `len()`, `sorted()`, `list()`, `set()`, `print()`, dict/list/tuple literals
- for-loops where the iterable is a tool call result
- Subscripting and simple comprehensions over tool results

The sandbox DISALLOWS:
- `def` (function definitions)
- `import` anything (including `glob`, `os`, `pathlib`, `re`)
- `open()`, `Path(...)`, manual file I/O
- Referencing codebase symbols as Python names
  (e.g. `view(source=cli)` — 'cli' is NOT a variable;
  it should be the string `'cli'` inside a selector `.fn#cli`)
- Unknown function calls (only the kit tools + basic builtins)

# The tools available in this kit

## find_names(source: str, selector: str) -> list[str]
Returns names of AST nodes matching a CSS-like selector.

## find(source: str, selector: str) -> list[dict]
Returns full AST node metadata for matches.

## view(source: str, selector: str) -> str
Returns rendered markdown source code of matched nodes.

## complexity(source: str, selector: str) -> list[dict]
Returns matched nodes ranked by complexity (descendant count, highest first).

## read_source(file_path: str, lines: str) -> str
Returns file content (full file or a line range like '10-20').

# Selector syntax (this is what the smaller model gets wrong most)

- `.fn` — function definitions (any name)
- `.class` — class definitions
- `.call` — call expressions
- `.fn#name` — function NAMED exactly 'name' (the # is NOT a prefix match!)
- `.class#Name` — class named exactly 'Name'
- `.class#Name .fn` — methods inside class Name (descendant combinator)
- `.class#Name > .fn` — direct child methods only
- `.fn[name^='test_']` — functions whose name starts with 'test_'
- `.fn[name*='cache']` — functions whose name contains 'cache'
- `.fn[name$='_handler']` — functions whose name ends with '_handler'

# What I need from you

Generate **exactly 20 examples** in the JSON format below. Cover these
categories with at least 3 examples each:

1. **Simple single-selector queries** — `.fn`, `.class`, `.call`
2. **Named lookups** — `.fn#name`, `.class#Name`
3. **Compositional selectors** — methods of a class, direct vs descendant
4. **Attribute selectors** — prefix/suffix/contains on name
5. **Negative examples** — show a common mistake and the correct form

For negative examples, use the tag `"anti_pattern"` and make the `code`
field demonstrate the WRONG version. Add a `correct_code` field showing
the RIGHT version. These train the smaller model to recognize and avoid
the bad pattern.

# Output format (strict JSON)

Output ONLY a JSON array, no prose, no markdown fences. Each element:

```
{
  "intent": "natural language request",
  "code": "the sandbox-legal lackpy program that answers it",
  "tool": "the primary tool used",
  "tags": ["positive"],
  "notes": "one-line explanation of WHY this is the right chain"
}
```

For anti-patterns, use this shape:
```
{
  "intent": "natural language request that tempts a mistake",
  "code": "the WRONG attempt (would fail in sandbox)",
  "correct_code": "the right version",
  "tool": "intended tool",
  "tags": ["anti_pattern"],
  "notes": "what specifically is wrong and why the correct version works"
}
```

Output the JSON array now. Exactly 20 elements. No commentary."""


def query_ollama(prompt: str) -> str:
    data = json.dumps({
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.3, "num_predict": 4096},
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/generate",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        body = json.loads(resp.read())
    return body["response"]


def main() -> int:
    print(f"Querying {MODEL} for training examples...", file=sys.stderr)
    raw = query_ollama(PROMPT)

    # Try to extract the JSON array — model may wrap in prose
    start = raw.find("[")
    end = raw.rfind("]")
    if start == -1 or end == -1 or start > end:
        print("FAILED: no JSON array found in output", file=sys.stderr)
        print("Raw response:", file=sys.stderr)
        print(raw, file=sys.stderr)
        return 1

    candidate = raw[start : end + 1]
    try:
        examples = json.loads(candidate)
    except json.JSONDecodeError as e:
        print(f"FAILED: invalid JSON at offset {e.pos}: {e.msg}", file=sys.stderr)
        print("Candidate:", file=sys.stderr)
        print(candidate, file=sys.stderr)
        return 1

    if not isinstance(examples, list):
        print("FAILED: top-level not a list", file=sys.stderr)
        return 1

    positive = [e for e in examples if "positive" in e.get("tags", [])]
    anti = [e for e in examples if "anti_pattern" in e.get("tags", [])]

    print(f"Got {len(examples)} examples: {len(positive)} positive, {len(anti)} anti-pattern", file=sys.stderr)
    print(json.dumps(examples, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
