# Getting Started

## Installation

### From PyPI

```bash
pip install squawkit
```

This installs squawkit and its dependencies (pluckit, fastmcp, and transitively
fledgling and duckdb).

### From source (development)

```bash
git clone https://github.com/teaguesterling/squawkit.git
cd squawkit
pip install -e ".[docs,test]"
```

## Running the MCP server

squawkit is an [MCP](https://modelcontextprotocol.io/) server that communicates
over stdio. Start it with:

```bash
squawkit
```

Or via Python:

```bash
python -m squawkit
```

### Claude Code integration

Add squawkit to your Claude Code MCP configuration (`.mcp.json`):

```json
{
  "mcpServers": {
    "squawkit": {
      "command": "squawkit",
      "args": []
    }
  }
}
```

### Programmatic usage

```python
from squawkit.server import create_server

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

squawkit infers sensible defaults for your project on startup. Override them
with a config file at `.squawkit/config.toml` (or `.fledgling-python/config.toml`)
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
from squawkit.db import create_connection

con = create_connection(repo=".")
print(con.project_overview().df())
```

This should print a table of file counts by language for the current directory.
