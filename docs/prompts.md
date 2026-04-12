# Prompt Templates

squackit registers three MCP prompt templates that pre-load live project data
into structured workflows. Each prompt gathers data from the project at call
time, so the agent starts with real context instead of asking for it.

## explore

**Exploration workflow with live project data.**

Pre-loads: languages, key definitions, documentation outline, recent git
activity, and step-by-step exploration guidance.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `path` | string | none | Narrow scope to a subdirectory |

```
User: "I just cloned this repo — what am I looking at?"
→ Call the explore prompt
```

The prompt returns a briefing document with the project's languages, top-level
structure, key definitions, documentation, and recent commits — plus guidance
on what to explore next.

## investigate

**Investigation workflow with pre-found definitions and source.**

Pre-loads: definition location, source code, callers, callees for the given
symptom (error message, function name, or file path).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `symptom` | string | required | Error message, function name, or file path |

```
User: "Why is parse_config raising a KeyError?"
→ Call the investigate prompt with symptom="parse_config"
```

The prompt finds where `parse_config` is defined, reads its source, finds
callers and callees, and provides a step-by-step debugging workflow.

## review

**Code review checklist with pre-loaded change summary.**

Pre-loads: changed files, complexity deltas for changed functions, and diffs
for the top changed files between two revisions.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `from_rev` | string | inferred main branch | Start revision |
| `to_rev` | string | `HEAD` | End revision |

```
User: "Review my changes before I push"
→ Call the review prompt
```

The prompt summarizes what changed, highlights complexity increases, shows
the actual diffs, and provides a structured review checklist.
