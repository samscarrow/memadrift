from __future__ import annotations

from datetime import date
from pathlib import Path

import click

from memadrift import __version__
from memadrift.audit import write_entries
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
from memadrift.parser import MemoryFile, MemoryStore, ParseError, Parser
from memadrift.reality import LocalEnvSource, UserSource, VerificationSource
from memadrift.schema import Schema
from memadrift.scorer import VERIFY_COSTS, is_stale, rank

DEFAULT_MEMORY = "MEMORY.md"
DEFAULT_SCHEMA = "schema.yaml"
DEFAULT_PENDING = "pending_verifications.json"


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
@click.option(
    "--network",
    is_flag=True,
    help="Enable network-based verification sources.",
)
@click.option(
    "--env-file",
    default=None,
    type=click.Path(),
    help="Path to .env file for secrets.",
)
@click.pass_context
def cli(ctx, memory, schema, no_backup, network, env_file):
    """Drift detection and remediation for Claude memory files."""
    ctx.ensure_object(dict)
    ctx.obj["memory_path"] = Path(memory)
    ctx.obj["schema_path"] = Path(schema)
    ctx.obj["no_backup"] = no_backup
    ctx.obj["network"] = network
    ctx.obj["env_file"] = env_file


@cli.command()
@click.option("--deep", is_flag=True, help="Normalize IDs across all included files.")
@click.pass_context
def ids(ctx, deep):
    """Assign/normalize deterministic IDs and rewrite the memory file."""
    memory_path = ctx.obj["memory_path"]
    if not memory_path.exists():
        click.echo(f"Memory file not found: {memory_path}", err=True)
        raise SystemExit(1)

    if deep:
        store = Parser.read_store(memory_path)
        changed = 0
        for item in store.all_items:
            correct_id = generate_id(item.type.value, str(item.scope), item.key)
            if item.id != correct_id:
                click.echo(f"  {item.id} -> {correct_id}  ({item.key})")
                item.id = correct_id
                changed += 1
        if changed:
            Parser.write_store(store, backup=not ctx.obj["no_backup"])
            click.echo(f"Updated {changed} ID(s) across all files.")
        else:
            click.echo("All IDs are correct.")
    else:
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

    # Validate refs (Step 6)
    from memadrift.validators import validate_ref

    base_dir = memory_path.parent
    for item in mf.items:
        if item.ref is not None:
            ref_errors = validate_ref(item.ref, base_dir)
            for err in ref_errors:
                errors.append(f"{item.key}: {err}")

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


def _build_source_registry(ctx, interactive: bool) -> list[VerificationSource]:
    """Build the verification source registry based on flags."""
    registry: list[VerificationSource] = [LocalEnvSource()]

    if ctx.obj.get("network"):
        from memadrift.external import ExternalSource, GitHubSource
        from memadrift.secrets import load_env

        env_file = ctx.obj.get("env_file")
        if env_file:
            load_env(env_file)
        else:
            load_env(".env")
        registry.append(ExternalSource())
        registry.append(GitHubSource())

    if interactive:
        registry.append(UserSource())

    return registry


@cli.command()
@click.option("--dry-run", is_flag=True, help="Show what would change without writing.")
@click.option("--interactive", is_flag=True, help="Enable interactive user prompts for verification.")
@click.option("--limit", type=int, default=0, help="Max items to check (0 = unlimited).")
@click.option("--max-cost", type=float, default=0.0, help="Max total verification cost (0 = unlimited).")
@click.option("--audit-log", default="audit.jsonl", type=click.Path(),
              help="Path to JSON-lines audit log.")
@click.option("--no-audit", is_flag=True, help="Disable audit log writing.")
@click.option("--deep", is_flag=True, help="Scan all included files.")
@click.option("--pending-queue", default=None, type=click.Path(),
              help="Path to pending verification queue.")
@click.pass_context
def scan(ctx, dry_run, interactive, limit, max_cost, audit_log, no_audit, deep, pending_queue):
    """Scan memory items for drift and apply fixes."""
    memory_path = ctx.obj["memory_path"]
    schema_path = ctx.obj["schema_path"]

    if not memory_path.exists():
        click.echo(f"Memory file not found: {memory_path}", err=True)
        raise SystemExit(1)

    if deep:
        store = Parser.read_store(memory_path)
        items = store.all_items
    else:
        store = None
        mf = Parser.read(memory_path)
        items = mf.items

    schema = None
    if schema_path.exists():
        schema = Schema.load(schema_path)

    source_registry = _build_source_registry(ctx, interactive)

    today = date.today()
    ranked = rank(items, today=today)

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
            if pending_queue:
                from memadrift.pending import add_to_queue

                add_to_queue(
                    item_id=item.id,
                    key=item.key,
                    current_value=item.value,
                    verify_mode=item.verify_mode.value,
                    source_file=str(memory_path),
                    evidence="no checkable source",
                    path=pending_queue,
                )
                click.echo(f"  {item.key}: queued for pending verification")
            else:
                click.echo(f"  {item.key}: no checkable source, skipping")

    if not dry_run and results:
        if deep and store:
            Parser.write_store(store, backup=not ctx.obj["no_backup"])
        else:
            Parser.write(mf, memory_path, backup=not ctx.obj["no_backup"])
        click.echo(f"Wrote {len(results)} update(s) to {memory_path}.")
        if not no_audit:
            count = write_entries(results, Path(audit_log), str(memory_path))
            click.echo(f"Appended {count} entry/entries to {audit_log}.")
    elif dry_run:
        click.echo("Dry run — no changes written.")
    else:
        click.echo("No items to check.")


def _is_cold(item: MemoryItem, today: date) -> bool:
    """Check if an item is cold (eligible for archival)."""
    if item.impact != Impact.LOW or item.type != MemoryType.FACT:
        return False
    if isinstance(item.last_verified, str):
        return False  # last_verified == "never"
    age = (today - item.last_verified).days
    return age > 180


@cli.command()
@click.option("--archive", default="archive.md", help="Path to archive file (relative to memory dir).")
@click.option("--dry-run", is_flag=True, help="Show cold items without moving.")
@click.pass_context
def optimize(ctx, archive, dry_run):
    """Move cold items from MEMORY.md to an archive file."""
    memory_path = ctx.obj["memory_path"]

    if not memory_path.exists():
        click.echo(f"Memory file not found: {memory_path}", err=True)
        raise SystemExit(1)

    mf = Parser.read(memory_path)
    today = date.today()
    base_dir = memory_path.parent

    cold_items = [item for item in mf.items if _is_cold(item, today)]

    if not cold_items:
        click.echo("No cold items found.")
        return

    if dry_run:
        click.echo("Cold items (would be archived):")
        for item in cold_items:
            click.echo(f"  {item.key} (last verified: {item.last_verified})")
        return

    # Load or create archive
    archive_path = base_dir / archive
    if archive_path.exists():
        archive_mf = Parser.read(archive_path)
    else:
        archive_mf = MemoryFile(
            frontmatter={"version": 1, "role": "archive"},
            items=[],
            path=archive_path,
        )

    # Move cold items to archive
    for item in cold_items:
        archive_mf.items.append(item)
        mf.items.remove(item)
        click.echo(f"  Archived: {item.key}")

    # Ensure includes has archive
    includes = mf.frontmatter.get("includes", []) or []
    if archive not in includes:
        includes.append(archive)
        mf.frontmatter["includes"] = includes

    backup = not ctx.obj["no_backup"]
    Parser.write(archive_mf, archive_path, backup=backup)
    Parser.write(mf, memory_path, backup=backup)
    click.echo(f"Moved {len(cold_items)} item(s) to {archive}.")


@cli.command("verify-pending")
@click.option("--queue", "queue_path", default=DEFAULT_PENDING, type=click.Path(),
              help="Path to pending verification queue.")
@click.pass_context
def verify_pending(ctx, queue_path):
    """Interactively verify items from the pending queue."""
    from memadrift.pending import read_queue, remove_from_queue

    memory_path = ctx.obj["memory_path"]

    entries = read_queue(queue_path)
    if not entries:
        click.echo("No pending verifications.")
        return

    if not memory_path.exists():
        click.echo(f"Memory file not found: {memory_path}", err=True)
        raise SystemExit(1)

    mf = Parser.read(memory_path)
    user_source = UserSource()
    today = date.today()
    resolved_count = 0

    for entry in list(entries):
        item_id = entry["item_id"]
        key = entry["key"]
        current_value = entry["current_value"]

        # Find item in memory file
        item = None
        for it in mf.items:
            if it.id == item_id:
                item = it
                break

        if item is None:
            click.echo(f"  {key}: item {item_id} not found in memory file, removing from queue")
            remove_from_queue(item_id, queue_path)
            continue

        click.echo(f"  Verifying: {key} = {current_value}")
        drift = user_source.check("user_confirm", current_value)
        fix_result = apply_fix(item, drift, today=today)
        action_label = fix_result.action.value.replace("_", " ")
        click.echo(f"    {action_label} — {fix_result.detail}")
        remove_from_queue(item_id, queue_path)
        resolved_count += 1

    if resolved_count:
        Parser.write(mf, memory_path, backup=not ctx.obj["no_backup"])
        click.echo(f"Resolved {resolved_count} pending item(s).")
    else:
        click.echo("No items resolved.")


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
