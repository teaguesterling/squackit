# Design: Training Data Pipeline for Small-Model Tool Calling

**Date:** 2026-04-16
**Status:** Draft
**Owner:** lackpy (with squackit providing tool specs + validator)

## Problem

The 1.5B model (qwen2.5-coder:1.5b) succeeds at tool calling only when the
intent closely matches an in-context example. Generic intents ("find all
function definitions in a directory") fail — the model writes `def` +
`import os` instead of calling `find_names('src/**/*.py', '.fn')`.

Few-shot examples (what we have now) help on exact-match intents but don't
generalize. Fine-tuning is the path to generalization — teaching the model
that "find functions" means `find_names(glob, '.fn')` at the weight level,
not just the prompt level.

## What we have (few-shot, working)

```
ToolSpec.examples → lackpy prompt builder → in-context examples → model generates
```

- 93 curated examples covering 45 tools
- Mechanical validator (AST parse + sandbox check + selector check)
- Works when intent ≈ example; fails otherwise

## What we need (training data)

```
(system_prompt, user_intent) → model_attempt → validator → (accepted | correction)
```

### Data format: preference pairs

Each training sample is a tuple:

```json
{
  "system": "<the full system prompt lackpy builds for this kit>",
  "intent": "find all function definitions",
  "chosen": "find_names('src/**/*.py', '.fn')",
  "rejected": "def find_funcs():\n    import os\n    ...",
  "rejection_reason": "Forbidden AST node: FunctionDef"
}
```

`chosen` is the correct program. `rejected` is what the model actually
generated. `rejection_reason` comes from the validator. This format supports
DPO (Direct Preference Optimization) training.

### For SFT (Supervised Fine-Tuning), just the positive side:

```json
{
  "system": "<system prompt>",
  "intent": "find all function definitions",
  "completion": "find_names('src/**/*.py', '.fn')"
}
```

## Pipeline architecture

### Phase 1: Intent generation (offline, larger model)

Use a 7b+ model or Claude to generate diverse intents for each tool:

```
For each tool in the kit:
  Generate 50-100 diverse intents that should use this tool.
  Vary: phrasing, specificity, file paths, function names,
        ambiguity level, multi-step vs single-step.
```

This is what the grid search tried to do, but focused on generating
`(intent, code)` pairs instead of intents alone. Generating just intents
is easier — no sandbox constraints to obey.

Target: 500-1,000 unique intents across all tools.

### Phase 2: Model attempts (online, target model)

Run each intent through the actual lackpy pipeline with the target model:

```python
for intent in intents:
    result = await svc.delegate(intent, kit=kit)
    capture(
        system_prompt=svc.last_system_prompt,  # needs lackpy exposure
        intent=intent,
        model_output=result['program'],
        success=result['success'],
        error=result.get('error'),
        validator_report=validate(result['program']),
    )
```

This produces raw `(intent, attempt, outcome)` triples. Failures are the
training signal — they show what the model does wrong.

### Phase 3: Correction generation (offline, larger model or hand-curated)

For each failed attempt, generate the correct program:

- If the intent is simple → mechanical: the correct program is in our
  curated examples or can be composed from them.
- If the intent is complex → use a 7b or Claude to generate the correction,
  validated by the mechanical validator.

### Phase 4: Format as training data

Combine into preference pairs (Phase 2 attempt + Phase 3 correction).
Format in the model's chat template. Write to JSONL.

### Phase 5: Fine-tune

Standard DPO or SFT on the target model. This is a lackpy concern —
squackit provides the tools, validator, and examples but doesn't own the
training loop.

## Volume estimates

- 500 intents × ~3 attempts per intent (retry on failure) = 1,500 samples
- After deduplication and filtering: ~800-1,200 usable pairs
- Minimum viable for a 1.5B fine-tune: ~1,000 pairs
- Sweet spot: 2,000-5,000 pairs

## What squackit provides

1. **Tool specs** (`squackit/lackpy_integration.py`) — ToolSpec objects with
   signatures, descriptions, and curated examples.
2. **Mechanical validator** (`scripts/grid_generate_examples.py:validate_example`)
   — can be extracted to a standalone module. Checks: syntax, forbidden AST
   nodes, unknown functions, bad selectors, unresolved names.
3. **Curated examples** (`squackit/data/examples.json`) — 93 examples covering
   45 tools. Seed data for intent generation and correction generation.

## What lackpy needs to add

1. **System prompt capture** — expose `svc.last_system_prompt` (or equivalent)
   so training data includes the exact prompt the model saw.
2. **Batch delegation mode** — run N intents efficiently, capturing all
   intermediate state.
3. **Training data writer** — JSONL output in the model's chat template format.
4. **Intent generator** — use a larger model to generate diverse intents from
   tool specs. Separate from the grid search (which tried to do too much).

## Relationship to the grid search

The grid search (`scripts/grid_generate_examples.py`) produced useful
infrastructure but targeted the wrong output:

| Grid search | Training pipeline |
|---|---|
| Generates `(intent, code)` pairs | Generates intents only (Phase 1) |
| 7b writes the code | Target model writes the code (Phase 2) |
| Validator checks the 7b's code | Validator checks the 1.5b's code |
| Critic is another 7b | Correction comes from examples or larger model |
| Output: few-shot examples | Output: preference pairs for fine-tuning |

The grid's **mechanical validator** and **tool group specs** transfer directly.
The grid's **example output** is useful as few-shot material (what we're using
now) and as seeds for Phase 3 corrections. The grid's **critic-refiner loop**
doesn't transfer — it was trying to fix generated code, but training data needs
the model's actual mistakes, not corrected versions.
