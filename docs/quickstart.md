# Getting Started

## Installation

### From PyPI

```bash
pip install squackit
```

This installs squackit and its dependencies ([ast-pluckit](https://pypi.org/project/ast-pluckit/),
fastmcp, and transitively fledgling-mcp and duckdb).

### From source (development)

```bash
git clone https://github.com/teaguesterling/squackit.git
cd squackit
pip install -e ".[docs,test]"
```

## Command-line usage

squackit ships with a `squackit` CLI that exposes three things:

- **`squackit mcp serve`** — start the MCP server (for AI agents)
- **`squackit tool <name>`** — run any squackit tool from the shell
- **`squackit pluck ...`** — run pluckit chain queries

### Tool commands

```bash
squackit tool list                                  # show available tools
squackit tool view "**/*.py" ".fn#main"             # rendered source
squackit tool find "src/**/*.py" ".class"           # AST node metadata
squackit tool find_names "**/*.py" ".fn"            # just the names
squackit tool complexity "**/*.py" ".fn"            # nodes by complexity
squackit tool read_source squackit/cli.py --lines "1-20"
squackit tool project_overview
```

Tool names resolve in three conventions — use whichever you prefer:

```bash
squackit tool find_names    # underscore (canonical)
squackit tool find-names    # kebab-case
squackit tool FindNames     # CamelCase
squackit t find-names ...   # 't' is an alias for 'tool'
```

### Structured output

Add `--json` for machine-readable output:

```bash
squackit --json tool find "**/*.py" ".fn" | jq '.[] | .name'
squackit --json tool list
```

### Pluckit chains

The `pluck` command passes arguments directly to pluckit's chain evaluator.
It supports the full selector grammar, navigation, and terminals:

```bash
squackit pluck "**/*.py" find .fn names
squackit pluck "src/api.py" find .class children .fn count
squackit pluck --plugin AstViewer "**/*.py" find ".fn#handler" view
squackit pluck "**/*.py" find .fn names reset find .class names
```

See the [pluckit documentation](https://github.com/teaguesterling/pluckit)
for the full chain grammar.

## Running the MCP server

squackit is an [MCP](https://modelcontextprotocol.io/) server that communicates
over stdio. Start it with:

```bash
squackit mcp serve
```

Or via Python:

```bash
python -m squackit mcp serve
```

Options:

```bash
squackit mcp serve --transport sse --port 8080   # SSE transport
squackit mcp serve --root /path/to/project        # explicit project root
squackit mcp serve --profile analyst              # security profile
```

### Claude Code integration

Add squackit to your Claude Code MCP configuration (`.mcp.json`):

```json
{
  "mcpServers": {
    "squackit": {
      "command": "squackit",
      "args": ["mcp", "serve"]
    }
  }
}
```

### Programmatic usage

```python
from squackit.server import create_server

# Default: uses current directory, analyst profile
mcp = create_server()

# Custom: specific project root and module selection
mcp = create_server(
    root="/path/to/project",
    profile="analyst",
    modules=["source", "code", "docs", "repo"],
)

mcp.run()
```

## Tab completion

squackit's CLI uses Click's built-in shell completion. Activate by adding
this to your shell profile:

```bash
# Bash
eval "$(_SQUACKIT_COMPLETE=bash_source squackit)"

# Zsh
eval "$(_SQUACKIT_COMPLETE=zsh_source squackit)"

# Fish
_SQUACKIT_COMPLETE=fish_source squackit | source
```

Completion covers all three name conventions (underscore, kebab, CamelCase).

## Configuration

squackit infers sensible defaults for your project on startup. Override them
with a config file at `.squackit/config.toml` (or `.fledgling-python/config.toml`)
in your project root:

```toml
[defaults]
code_pattern = "src/**/*.rs"
doc_pattern = "documentation/**/*.md"
main_branch = "develop"
```

See [Configuration](configuration.md) for all options and precedence rules.

## Verifying the setup

After installing, check that everything works:

```bash
squackit tool project_overview
```

This should print a table of file counts by language for the current directory.
