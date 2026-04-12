# Getting Started

## Installation

### From PyPI

```bash
pip install squackit
```

This installs squackit and its dependencies ([ast-pluckit](https://pypi.org/project/ast-pluckit/),
fastmcp, and transitively fledgling and duckdb).

### From source (development)

```bash
git clone https://github.com/teaguesterling/squackit.git
cd squackit
pip install -e ".[docs,test]"
```

## Running the MCP server

squackit is an [MCP](https://modelcontextprotocol.io/) server that communicates
over stdio. Start it with:

```bash
squackit
```

Or via Python:

```bash
python -m squackit
```

### Claude Code integration

Add squackit to your Claude Code MCP configuration (`.mcp.json`):

```json
{
  "mcpServers": {
    "squackit": {
      "command": "squackit",
      "args": []
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

```python
from squackit.db import create_connection

con = create_connection(repo=".")
print(con.project_overview().df())
```

This should print a table of file counts by language for the current directory.
