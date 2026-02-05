from __future__ import annotations

from datetime import date
from pathlib import Path

import click

from memadrift import __version__
from memadrift.fixer import FixAction, apply_fix
from memadrift.ids import generate_id
from memadrift.models import (
    Impact,
    MemoryItem,
    MemoryType,
    Scope,
    Source,
    Status,
    VerifyMode,
)
from memadrift.parser import MemoryFile, ParseError, Parser
from memadrift.reality import LocalEnvSource
from memadrift.schema import Schema
from memadrift.scorer import is_stale, rank

DEFAULT_MEMORY = "MEMORY.md"
DEFAULT_SCHEMA = "schema.yaml"


@click.group()
@click.version_option(version=__version__, prog_name="memadrift")
@click.option(
    "--memory",
    default=DEFAULT_MEMORY,
    type=click.Path(),
    help="Path to memory file.",
)
@click.option(
    "--schema",
    default=DEFAULT_SCHEMA,
    type=click.Path(),
    help="Path to schema file.",
)
@click.pass_context
def cli(ctx, memory, schema):
    """Drift detection and remediation for Claude memory files."""
    ctx.ensure_object(dict)
    ctx.obj["memory_path"] = Path(memory)
    ctx.obj["schema_path"] = Path(schema)


@cli.command()
@click.pass_context
def ids(ctx):
    """Assign/normalize deterministic IDs and rewrite the memory file."""
    memory_path = ctx.obj["memory_path"]
    if not memory_path.exists():
        click.echo(f"Memory file not found: {memory_path}", err=True)
        raise SystemExit(1)

    mf = Parser.read(memory_path)
    changed = 0
    for item in mf.items:
        correct_id = generate_id(item.type.value, str(item.scope), item.key)
        if item.id != correct_id:
            click.echo(f"  {item.id} -> {correct_id}  ({item.key})")
            item.id = correct_id
            changed += 1

    if changed:
        Parser.write(mf, memory_path)
        click.echo(f"Updated {changed} ID(s).")
    else:
        click.echo("All IDs are correct.")


@cli.command()
@click.pass_context
def lint(ctx):
    """Read-only format and schema checks on the memory file."""
    memory_path = ctx.obj["memory_path"]
    schema_path = ctx.obj["schema_path"]
    errors: list[str] = []

    if not memory_path.exists():
        click.echo(f"Memory file not found: {memory_path}", err=True)
        raise SystemExit(1)

    # Check line count
    lines = memory_path.read_text().split("\n")
    if len(lines) > 200:
        errors.append(f"File exceeds 200 lines ({len(lines)} lines)")

    # Parse
    try:
        mf = Parser.read(memory_path)
    except ParseError as e:
        errors.append(str(e))
        _report_errors(errors)
        raise SystemExit(1)

    # Check IDs
    for item in mf.items:
        correct_id = generate_id(item.type.value, str(item.scope), item.key)
        if item.id != correct_id:
            errors.append(f"Wrong ID for {item.key}: {item.id} should be {correct_id}")

    # Check duplicate keys
    seen_keys: dict[str, str] = {}
    for item in mf.items:
        scope_key = f"{item.scope}:{item.key}"
        if scope_key in seen_keys:
            errors.append(f"Duplicate key: {item.key} in scope {item.scope}")
        seen_keys[scope_key] = item.id

    # Schema validation
    if schema_path.exists():
        schema = Schema.load(schema_path)
        for item in mf.items:
            resolved = schema.resolve(item.key)
            if resolved is None:
                errors.append(f"Unknown key: {item.key} (not in schema)")

    if errors:
        _report_errors(errors)
        raise SystemExit(1)
    else:
        click.echo("Lint passed. No issues found.")


def _report_errors(errors: list[str]) -> None:
    for err in errors:
        click.echo(f"  ERROR: {err}", err=True)
    click.echo(f"{len(errors)} error(s) found.", err=True)


@cli.command()
@click.option("--dry-run", is_flag=True, help="Show what would change without writing.")
@click.pass_context
def scan(ctx, dry_run):
    """Scan memory items for drift and apply fixes."""
    memory_path = ctx.obj["memory_path"]
    schema_path = ctx.obj["schema_path"]

    if not memory_path.exists():
        click.echo(f"Memory file not found: {memory_path}", err=True)
        raise SystemExit(1)

    mf = Parser.read(memory_path)

    schema = None
    if schema_path.exists():
        schema = Schema.load(schema_path)

    env_source = LocalEnvSource()
    today = date.today()
    ranked = rank(mf.items, today=today)

    results = []
    for item in ranked:
        stale = is_stale(item, today=today)
        sources = schema.sources_for(item.key) if schema else []

        if not sources:
            click.echo(f"  {item.key}: no sources configured, skipping")
            continue

        for source_id in sources:
            if not env_source.can_check(source_id):
                continue
            drift = env_source.check(source_id, item.value)
            fix_result = apply_fix(item, drift, today=today)
            results.append(fix_result)

            action_label = fix_result.action.value.replace("_", " ")
            click.echo(f"  {item.key}: {action_label} — {fix_result.detail}")
            break  # use first checkable source

    if not dry_run and results:
        Parser.write(mf, memory_path)
        click.echo(f"Wrote {len(results)} update(s) to {memory_path}.")
    elif dry_run:
        click.echo("Dry run — no changes written.")
    else:
        click.echo("No items to check.")


@cli.command()
@click.option("--key", required=True, help="Memory key (e.g., env.editor).")
@click.option("--value", required=True, help="Memory value.")
@click.option("--type", "mem_type", default="env", help="Memory type.")
@click.option("--scope", "scope_str", default="global", help="Scope (e.g., global, machine:host).")
@click.option("--src", "source", default="user", help="Source (user, tool, inferred, doc).")
@click.option("--ttl", "ttl_days", default=30, type=int, help="TTL in days (0 = never stale).")
@click.option("--verify-mode", default="auto", help="Verification mode.")
@click.option("--impact", default="low", help="Impact level.")
def add(key, value, mem_type, scope_str, source, ttl_days, verify_mode, impact):
    """Add a new memory item."""
    # Use the context's memory path if available, otherwise default
    ctx = click.get_current_context()
    memory_path = ctx.obj["memory_path"]

    # Generate ID
    item_id = generate_id(mem_type, scope_str, key)

    # Build item
    item = MemoryItem(
        id=item_id,
        type=MemoryType(mem_type),
        scope=Scope.parse(scope_str),
        key=key,
        value=value,
        src=Source(source),
        status=Status.ACTIVE,
        last_verified=date.today(),
        ttl_days=ttl_days,
        verify_mode=VerifyMode(verify_mode),
        impact=Impact(impact),
    )

    # Load or create file
    if memory_path.exists():
        mf = Parser.read(memory_path)
    else:
        mf = MemoryFile(frontmatter={"version": 1}, items=[], path=memory_path)

    # Check for duplicates
    for existing in mf.items:
        if existing.key == key and str(existing.scope) == scope_str:
            click.echo(
                f"Duplicate: {key} already exists in scope {scope_str} (ID: {existing.id})",
                err=True,
            )
            raise SystemExit(1)

    mf.items.append(item)
    Parser.write(mf, memory_path)
    click.echo(f"Added {item_id} ({key} = {value})")
