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
from memadrift.reality import LocalEnvSource, UserSource, VerificationSource
from memadrift.schema import Schema
from memadrift.scorer import VERIFY_COSTS, is_stale, rank

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
@click.option(
    "--no-backup",
    is_flag=True,
    help="Disable .bak backup before writing.",
)
@click.pass_context
def cli(ctx, memory, schema, no_backup):
    """Drift detection and remediation for Claude memory files."""
    ctx.ensure_object(dict)
    ctx.obj["memory_path"] = Path(memory)
    ctx.obj["schema_path"] = Path(schema)
    ctx.obj["no_backup"] = no_backup


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
        Parser.write(mf, memory_path, backup=not ctx.obj["no_backup"])
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


def _try_check(
    registry: list[VerificationSource], source_id: str, expected: str,
):
    for source in registry:
        if source.can_check(source_id):
            return source.check(source_id, expected)
    return None


@cli.command()
@click.option("--dry-run", is_flag=True, help="Show what would change without writing.")
@click.option("--interactive", is_flag=True, help="Enable interactive user prompts for verification.")
@click.option("--limit", type=int, default=0, help="Max items to check (0 = unlimited).")
@click.option("--max-cost", type=float, default=0.0, help="Max total verification cost (0 = unlimited).")
@click.pass_context
def scan(ctx, dry_run, interactive, limit, max_cost):
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

    source_registry: list[VerificationSource] = [LocalEnvSource()]
    if interactive:
        source_registry.append(UserSource())

    today = date.today()
    ranked = rank(mf.items, today=today)

    results = []
    checked_count = 0
    spent_cost = 0.0

    for item in ranked:
        if limit and checked_count >= limit:
            click.echo(f"  Limit reached ({limit} items), stopping.")
            break

        item_cost = VERIFY_COSTS[item.verify_mode]
        if max_cost > 0 and spent_cost + item_cost > max_cost:
            click.echo(f"  Budget exhausted ({spent_cost:.1f}/{max_cost:.1f}), stopping.")
            break

        sources = schema.sources_for(item.key) if schema else []

        drift = None
        for source_id in sources:
            drift = _try_check(source_registry, source_id, item.value)
            if drift is not None:
                break

        # Implicit fallback for human-verified items when --interactive
        if drift is None and interactive and item.verify_mode == VerifyMode.HUMAN:
            drift = _try_check(source_registry, "user_confirm", item.value)

        if drift is not None:
            fix_result = apply_fix(item, drift, today=today)
            results.append(fix_result)
            checked_count += 1
            spent_cost += item_cost
            action_label = fix_result.action.value.replace("_", " ")
            click.echo(f"  {item.key}: {action_label} — {fix_result.detail}")
        else:
            click.echo(f"  {item.key}: no checkable source, skipping")

    if not dry_run and results:
        Parser.write(mf, memory_path, backup=not ctx.obj["no_backup"])
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
    Parser.write(mf, memory_path, backup=not ctx.obj["no_backup"])
    click.echo(f"Added {item_id} ({key} = {value})")
