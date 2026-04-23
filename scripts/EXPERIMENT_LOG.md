# Model Delegation Experiment Log — 2026-04-20/21

## Goal

Find the fastest route to high success rate with the smallest models
possible for delegating code intelligence tasks via lackpy.

## Setup

- Ollama server on localhost:11435
- Models: qwen2.5-coder (0.5b/1.5b/3b/7b), qwen2.5 (1.5b/7b),
  qwen3.5 (2b/4b/9b), granite3.3:2b, deepseek-coder-v2:16b,
  deepseek-llm:7b
- Execution via lackpy RestrictedRunner + real squackit tools against
  the squackit codebase itself

## Experiments and Findings

### 1. Iterative Execution (iterative_eval.py)

Generate Python programs using squackit tool API, execute in sandbox,
retry with error feedback. 6 tasks requiring find/find_names/complexity
tool composition.

| Strategy              | coder:3b | coder:7b | deepseek:16b |
|-----------------------|----------|----------|--------------|
| No docs               | 4/6 35s  | —        | —            |
| Full docs (~200-800t) | 4/6 32s  | 3/6 54s  | —            |
| Hints XML (~20-50t)   | 2/6 29s  | 4/6 44s  | **6/6 31s**  |
| Hints plain text      | 3/6 26s  | **5/6 48s** | 5/6 33s   |
| Editor: 3b->7b        | 4/6 51s  | —        | —            |
| Editor: 3b->deepseek  | 4/6 35s  | —        | —            |

**Key findings:**
- Full doc dumps don't help — too noisy for small context windows
- XML tags leak into raw completions for small models, hurt 3b
- Plain text `ERROR:` / `HINT:` prefixes work for 7b+
- Editor pattern fails: bad code in retry prompt poisons the fixer
- deepseek-coder-v2:16b solves everything — coding specialization
  matters more than parameter count (qwen3.5:9b got 2/6 at 160s)
- Cold starts: 3b=3.1s, 7b=5.1s, 16b=10.3s

### 2. Quartermaster Tool Selection (quartermaster_eval.py)

Given natural language intent + 24-tool inventory, select 2-5 relevant
tools. Tests classification ability, not code generation.

| Model                | Good (F1>=0.5) | F1   | Prec | Rec  | Time  |
|----------------------|----------------|------|------|------|-------|
| coder:0.5b           | 1/12           | 26%  | 16%  | 75%  | 1.4s  |
| coder:1.5b           | 2/12           | 35%  | 28%  | 68%  | 2.9s  |
| coder:3b             | 5/12           | 46%  | 51%  | 64%  | 4.2s  |
| **coder:7b**         | **8/12**       | 54%  | 68%  | 56%  | 3.2s  |
| qwen2.5:1.5b         | 6/12           | 43%  | 49%  | 64%  | 1.7s  |
| qwen2.5:7b           | 7/12           | 55%  | 72%  | 60%  | 10.8s |
| **granite3.3:2b**    | **8/12**       | 48%  | 56%  | 53%  | 2.4s  |
| deepseek-v2:16b      | 5/12           | 26%  | 42%  | 33%  | 2.2s  |
| qwen3.5:2b           | 2/12           | 22%  | 19%  | 29%  | 10.2s |
| qwen3.5:4b           | 2/12           | 36%  | 26%  | 92%  | 20.2s |

**Key findings:**
- granite3.3:2b ties coder:7b (8/12) at 2.4s and 1.5GB — best QM
  candidate. Non-coder general models are better at classification.
- Coding models are bad at tool selection (deepseek:16b flopped)
- qwen3.5 thinking models are too slow for a triage role

### 3. BM25 Retrieval + Model Gap Check (qm_retrieval_eval.py)

Mechanical BM25 retrieval against tool descriptions, then ask model
what's missing.

| Strategy            | Good  | F1   | Prec | Rec  | Time  |
|---------------------|-------|------|------|------|-------|
| **BM25 only**       |**7/12**| 48% | 47%  | 56%  | 0.0s  |
| + coder:0.5b        | 2/12  | 31%  | 22%  | 75%  | 2.5s  |
| + qwen2.5:1.5b      |**7/12**| 55% | 46%  | 68%  | 6.2s  |
| + granite:2b        | 6/12  | 46%  | 44%  | 56%  | 10.0s |
| + coder:3b          | 7/12  | 48%  | 47%  | 56%  | 9.0s  |
| + coder:7b          | 7/12  | 48%  | 47%  | 56%  | 19.8s |

**Key findings:**
- BM25 alone gets 7/12 at zero latency — already competitive
- Models barely improve over mechanical retrieval
- qwen2.5:1.5b is the only model that meaningfully improves recall
- BM25 failures are vocabulary mismatch — fixable with better tool
  descriptions (add intent-language synonyms)

### 4. PSS Selector Generation (selector_eval.py)

Generate CSS-like AST selectors from natural language. Single-line
output, executed via pluckit against real codebase.

| Model                | Pass  | Execute | Pattern | Time  |
|----------------------|-------|---------|---------|-------|
| coder:0.5b           | 2/11  | **11/11** | 11%   | 1.2s  |
| coder:1.5b           | 5/11  | **11/11** | 33%   | 2.6s  |
| **coder:3b**         |**8/11**| **11/11** | 55%   | 4.4s  |
| coder:7b             | 6/11  | **11/11** | 45%   | 3.8s  |
| qwen2.5:1.5b         | 3/11  | **11/11** | 18%   | 2.8s  |
| qwen2.5:7b           | 7/11  | **11/11** | 51%   | 3.8s  |
| granite:2b           | 6/11  | **11/11** | 39%   | 1.9s  |
| **deepseek:16b**     |**8/11**| **11/11** | 56%   | 2.6s  |

**Key findings:**
- **100% execution rate across every model, every task** — even 0.5b
  never produces an invalid selector
- coder:3b ties deepseek:16b at 8/11 — the constrained DSL levels
  the playing field
- coder:7b (6/11) is *worse* than coder:3b (8/11) on selectors
- Compare: Python tool API needed retries and got 4/6 at best for 3b;
  selectors get 8/11 first try. Constrained output space wins.
- The PSS/ast-select DSL is the right interface for small models

## Conclusions

### The production pipeline should be:

1. **PSS selectors as primary interface** — 100% execution rate,
   8/11 correct at 3b, no retry needed for most tasks
2. **BM25 tool retrieval** for the quartermaster role — 7/12 at zero
   cost, better than most models
3. **coder:3b as default solver** — best balance of speed, accuracy,
   and resource usage for selectors
4. **deepseek:16b for escalation** — same accuracy but handles the
   harder composition tasks that 3b misses

### Design principles validated:

- **Constrain the output space, don't grow the model** — selectors
  beat Python programs at every model size
- **Mechanical retrieval beats model-based selection** — BM25 is free
  and competitive with 7b models
- **Coding specialization >> parameter count** — deepseek:16b beats
  qwen3.5:9b; granite:2b beats coder:3b at classification
- **The scaffold matters more than the model** — prompt format (XML
  vs plain text), tool descriptions, and DSL design had larger effects
  than doubling model size

### Next steps:

- Pull sqlcoder models for text-to-SQL evaluation against DuckDB
- Implement quartermaster in lackpy (resolve_kit with kit=None)
- Build intent->selector mapping from production logs (agent riggs)
- Enrich BM25 tool descriptions with intent-language synonyms
- Test pluckit chain grammar as composition layer between selectors
