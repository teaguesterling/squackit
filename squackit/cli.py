"""squackit CLI — entry point for the squackit MCP server."""

from __future__ import annotations

import json as _json

import click

from squackit.tool_config import (
    ToolPresentation,
    build_tool_registry,
    normalize_tool_name,
    to_kebab,
    to_camel,
)


@click.group()
@click.version_option(package_name="squackit")
@click.option("--json", "json_output", is_flag=True, default=False,
              help="Output in JSON format.")
@click.pass_context
def cli(ctx, json_output):
    """Semi-QUalified Agent Companion Kit — MCP server for fledgling-equipped agents."""
    ctx.ensure_object(dict)
    ctx.obj["json"] = json_output


# ── MCP serve ─────────────────────────────────────────────────────────

@cli.group()
def mcp():
    """MCP server commands."""


@mcp.command()
@click.option("--transport", "-t",
              type=click.Choice(["stdio", "sse"], case_sensitive=False),
              default="stdio", show_default=True, help="Transport protocol.")
@click.option("--port", "-p", type=int, default=8080, show_default=True,
              help="Port for SSE transport.")
@click.option("--root", type=click.Path(exists=True, file_okay=False),
              default=None, help="Project root directory (defaults to CWD).")
@click.option("--profile", default="analyst", show_default=True,
              help="Security profile.")
@click.option("--modules", "-m", multiple=True,
              help="SQL modules to load (repeatable).")
@click.option("--init", "init_path", default=None,
              help="Init file path. Pass 'false' to use sources only.")
def serve(transport, port, root, profile, modules, init_path):
    """Start the squackit MCP server."""
    from squackit.server import create_server

    init = None
    if init_path is not None:
        init = False if init_path.lower() == "false" else init_path

    server = create_server(
        root=root,
        init=init,
        modules=list(modules) or None,
        profile=profile,
    )

    kwargs = {}
    if transport == "sse":
        kwargs["transport"] = "sse"
        kwargs["port"] = port

    server.run(**kwargs)


# ── Tool group ────────────────────────────────────────────────────────

class ToolGroup(click.Group):
    """Click group that resolves tool names across naming conventions."""

    def get_command(self, ctx, cmd_name):
        cmd = super().get_command(ctx, cmd_name)
        if cmd:
            return cmd
        normalized = normalize_tool_name(cmd_name)
        return super().get_command(ctx, normalized)

    def list_commands(self, ctx):
        base = super().list_commands(ctx)
        expanded = set()
        for name in base:
            expanded.add(name)
            expanded.add(to_kebab(name))
            expanded.add(to_camel(name))
        return sorted(expanded)


def _get_registry():
    """Lazily build the tool registry."""
    from pluckit import Plucker
    p = Plucker()
    con = p.connection
    return build_tool_registry(con._tools), con


def _make_tool_command(presentation: ToolPresentation, con) -> click.Command:
    """Generate a Click command from a ToolPresentation."""
    from squackit.formatting import _format_markdown_table, format_json

    params = []

    for p in presentation.required:
        params.append(click.Argument([p], required=True))

    for p in presentation.optional:
        params.append(click.Option([f"--{p}"], default=None))

    @click.pass_context
    def callback(ctx, **kwargs):
        filtered = {k: v for k, v in kwargs.items() if v is not None}

        for k in list(filtered):
            if k in presentation.numeric_params:
                try:
                    filtered[k] = int(filtered[k])
                except (TypeError, ValueError):
                    pass

        macro = getattr(con, presentation.macro_name)
        try:
            rel = macro(**filtered)
            cols = rel.columns
            rows = rel.fetchall()
        except Exception as e:
            click.echo(f"Error: {e}", err=True)
            ctx.exit(1)
            return

        if not rows:
            click.echo("(no results)")
            return

        json_output = ctx.obj.get("json", False) if ctx.obj else False
        if json_output:
            click.echo(format_json(cols, rows))
        elif presentation.format == "text":
            if len(cols) == 1:
                for row in rows:
                    click.echo(str(row[0]))
            elif "line_number" in cols and "content" in cols:
                ln_idx = cols.index("line_number")
                ct_idx = cols.index("content")
                for row in rows:
                    click.echo(f"{row[ln_idx]:4d}  {row[ct_idx]}")
            else:
                for row in rows:
                    parts = [str(v) for v in row if v is not None]
                    click.echo("  ".join(parts))
        else:
            click.echo(_format_markdown_table(cols, rows))

    return click.Command(
        name=presentation.name,
        help=presentation.description,
        params=params,
        callback=callback,
    )


class LazyToolGroup(ToolGroup):
    """ToolGroup that lazily loads tools on first access."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._loaded = False
        self._con = None

    def _ensure_loaded(self, ctx):
        if self._loaded:
            return
        self._loaded = True
        try:
            registry, self._con = _get_registry()
        except Exception as e:
            click.echo(f"Warning: Could not load tools: {e}", err=True)
            return
        for name, presentation in registry.items():
            cmd = _make_tool_command(presentation, self._con)
            self.add_command(cmd, name)

    def get_command(self, ctx, cmd_name):
        self._ensure_loaded(ctx)
        return super().get_command(ctx, cmd_name)

    def list_commands(self, ctx):
        self._ensure_loaded(ctx)
        return super().list_commands(ctx)


@cli.group("tool", cls=LazyToolGroup)
@click.pass_context
def tool_group(ctx):
    """Run fledgling tools from the command line."""
    ctx.ensure_object(dict)


# Alias: squackit t
cli.add_command(tool_group, "t")


@tool_group.command("list")
@click.pass_context
def tool_list(ctx):
    """List available tools."""
    from squackit.formatting import _format_markdown_table, format_json

    tool_group_cmd = ctx.parent.command
    tool_group_cmd._ensure_loaded(ctx)

    tools = []
    seen = set()
    for name in sorted(tool_group_cmd.commands):
        if name == "list":
            continue
        normalized = normalize_tool_name(name)
        if normalized in seen:
            continue
        seen.add(normalized)

        cmd = tool_group_cmd.commands[name]
        tools.append({
            "name": normalized,
            "description": cmd.help or "",
        })

    json_output = ctx.obj.get("json", False) if ctx.obj else False
    if json_output:
        click.echo(_json.dumps(tools, indent=2))
    else:
        cols = ["Name", "Description"]
        rows = [(t["name"], t["description"][:60]) for t in tools]
        click.echo(_format_markdown_table(cols, rows))
