# Memadrift Project Plan

## Problem Statement
Your system persists "memory" as plain files in `~/.claude/projects/-home-sam/memory/`. `MEMORY.md` is injected into the system prompt at the start of every conversation (truncated after 200 lines). Drift is any deviation between what those files claim and current reality.

This project builds a drift detection and remediation loop for that file-only memory store, similar in spirit to config drift detection.

## Goals
- Detect memory drift: stale, contradictory, ambiguous, duplicated, or out-of-scope memories.
- Prioritize verification to avoid nagging: use a cost-aware scheduler and verify-on-use for expensive checks.
- Remediate safely: generate minimal patches to `MEMORY.md` (and optional topic files) with auditability and rollback.
- Keep `MEMORY.md` concise and parseable under the 200 line truncation constraint.
- Make IDs stable without relying on an LLM to increment counters.

## Non-Goals
- Storing conversation history or any hidden/session state.
- Building a database-backed memory system.
- Perfect truth discovery for human-only facts without explicit user confirmation.

## Core Design Decisions

### 1) Deterministic IDs (Fixes the "M-042" Problem)
LLMs are unreliable at maintaining sequential IDs. IDs must be assigned by the drift tool, not invented.

Plan:
- Use IDs derived from the memory item's logical key, not its current value.
- Compute `id = "mem_" + base32(blake2s("v1|" + type + "|" + scope + "|" + key))[:8]` (example).
- If an item is missing an ID, the tool computes and inserts it.
- If an item changes `value`, its ID stays the same (because `key` stays the same).
- If an item changes `key`, it is logically a different memory and gets a different ID.

### 2) Verification Is a Budgeted Scheduler (Fixes the Cost Problem)
Verification ranges from cheap (`git remote -v`) to expensive ("does the user still own a dog?").

Plan:
- Every memory item declares `verify_mode` and `verify_cost`.
- The tool runs `verify_mode=auto` checks on a schedule.
- `verify_mode=human` items are only prompted on use (when the item would influence a high-impact action) or when strong contradictory evidence exists.
- Drift scoring includes verification cost so the backlog does not turn into constant interruptions.

## Memory File Contract

### Required Properties Per Memory Item
Each memory item is a short, machine-parseable single-line record in `MEMORY.md`:
- `id`: deterministic ID assigned by the tool.
- `type`: `pref|fact|policy|env|workflow` (extendable).
- `scope`: `global|machine:<hostname>|repo:<path>|user:<name>` (extendable).
- `key`: stable logical key (dot-separated).
- `value`: current claim.
- `src`: `user|tool|inferred|doc` (provenance).
- `status`: `active|suspect|deprecated`.
- `last_verified`: `YYYY-MM-DD` or `never`.
- `ttl_days`: integer or `0` for "verify on use only".
- `verify_mode`: `auto|human|external`.
- `impact`: `low|med|high` (used to gate verify-on-use prompts).

### Proposed Line Format (Parseable, Compact)
Example:
`mem_7F3K9Q2A | pref | scope=global | key=editor.default | value=vim | src=user | status=active | last_verified=2026-02-05 | ttl_days=365 | verify_mode=human | impact=low`

Notes:
- The tool should tolerate minor formatting drift (extra spaces, reordered fields), but the canonical writer normalizes output.
- `MEMORY.md` should stay as an index. Longer context belongs in topic files referenced by `key` or `id`.

### Topic Files
Topic files are optional and only read when explicitly requested. The tool may:
- Suggest moving verbose detail from `MEMORY.md` into `patterns.md`, `debugging.md`, etc.
- Maintain backreferences like `ref=patterns.md#editor` as an optional field.

## Drift Taxonomy
The drift detector classifies findings:
- `stale`: `last_verified + ttl_days` is in the past.
- `contradiction`: an authoritative reality check disagrees with `value`.
- `scope_break`: claim is true in one scope but used in another.
- `ambiguous`: key/value cannot be operationalized (too vague to verify or apply).
- `duplicate`: multiple items represent the same logical key.
- `unverifiable`: `verify_mode=human|external` but no workflow exists to confirm.

## Reality Checks ("Current Reality")
Reality checks are adapters that return structured observations:
- Local checks: filesystem paths, installed binaries, git remotes, repo layout, OS facts.
- Tool checks: outputs from known CLI tools you already run.
- Human checks: explicit user confirmation prompts (only when needed).
- External checks: optional API calls (explicit opt-in).

Plan:
- Implement checks as a plugin interface: `check_id`, `applies_to(type,key,scope)`, `cost`, `run() -> observations`.
- Store check configuration in repo (not in the memory directory), for repeatability.

## Drift Scoring and Scheduling
Each finding gets a priority score that balances impact, evidence strength, age, and cost.

Plan:
- Compute a verification priority for each memory item.
- Example heuristic (configurable): `Base = impact_weight * age_weight * contradiction_weight`; `Priority = Base / (1 + verify_cost)`.
- Enforce a daily/weekly verification budget for `auto` checks.
- Enforce verify-on-use for `human` checks unless `impact=high` and `last_verified` is very old.

## Remediation Model
Remediation outputs safe changes without silently rewriting memory:
- `patch`: a unified diff that updates `MEMORY.md` (and topic files if configured).
- `actions`: structured list of recommended steps (for human verifications).
- `audit`: a short record of what changed and why.

Safety rules:
- Always support `--dry-run`.
- Create backups before writing (or require git).
- Use atomic writes (write temp file then rename).
- Never delete memories automatically; deprecate first unless explicitly instructed.

## CLI Deliverable
Python CLI (initially) for local use:
- `memadrift scan`: parse memories, run scheduled checks, emit a report.
- `memadrift report`: render findings as Markdown suitable for pasting into a chat.
- `memadrift apply`: apply recommended patches (with backup and audit log).
- `memadrift lint`: enforce format, ID presence, and the 200 line constraint.
- `memadrift ids`: assign or normalize deterministic IDs in `MEMORY.md`.

Outputs:
- `dist/drift_report.json`
- `dist/drift_report.md`
- `dist/patch.diff`

## Milestones

### M0: Repo Skeleton
- Choose Python packaging approach (`uv` + `pyproject.toml` recommended).
- Add `src/` layout, `memadrift` CLI entrypoint, and `tests/`.
- Add sample fixtures that mirror the real memory directory structure.

Acceptance:
- `memadrift --help` runs.
- CI or local `pytest` runs with at least one passing test.

### M1: Parser, Normalizer, Deterministic IDs
- Implement robust parsing for the line format.
- Implement canonical writer that normalizes spacing and field ordering.
- Implement deterministic ID assignment and duplicate detection.

Acceptance:
- Running `memadrift ids` on a fixture file produces stable IDs across runs.
- Changing `value` keeps the same `id` for the same `key`.

### M2: Drift Detection Core
- Implement drift taxonomy and report generation.
- Add `ttl` evaluation and `stale` classification.
- Add contradiction engine that compares memory claims to observations.

Acceptance:
- A fixture with seeded stale and contradictory items yields expected findings.
- Output report is stable and human-readable.

### M3: Reality Check Plugins (Cheap First)
- Implement 3 to 6 cheap, deterministic checks:
- `git_remote`: verify `repo:*` scoped remotes.
- `binary_exists`: verify tools referenced by `env.*` keys.
- `path_exists`: verify filesystem paths.
- `hostname_scope`: validate `machine:*` scoping usage.

Acceptance:
- `memadrift scan` runs plugins and reports contradictions with evidence.

### M4: Cost-Aware Scheduling and Verify-on-Use
- Implement scoring that incorporates `verify_cost` and `impact`.
- Implement policy that suppresses human prompts unless on-use or high-risk.
- Add a "verification queue" output that can be pasted into a chat when needed.

Acceptance:
- A fixture containing human-only items does not generate prompts during scheduled scans.
- Contradiction evidence or explicit on-use triggers a prompt recommendation.

### M5: Remediation and Safe Writes
- Generate patches for common fixes:
- Update `value` when authoritative reality contradicts it.
- Update `last_verified` when checks pass.
- Deprecate duplicates.
- Implement atomic apply with backups and audit log file.

Acceptance:
- `memadrift apply --dry-run` shows patch.
- `memadrift apply` updates fixture files exactly as patch indicates.

### M6: Linting and 200 Line Budget
- Enforce `MEMORY.md` line limit (200).
- Suggest compaction or moving details into topic files.
- Implement `memadrift lint` with actionable output.

Acceptance:
- Overlong fixture is flagged with specific candidates to move.
- Canonical formatting reduces accidental line bloat.

### M7: Documentation and Operational Workflow
- Document recommended workflow:
- When to run `scan` (start of conversation, daily cron, pre-action).
- How to handle human verifications (verify-on-use templates).
- How to review and apply patches safely.

Acceptance:
- A new user can run the tool against a sample memory directory and understand the outputs.

## Testing Strategy
- Unit tests for parsing, canonicalization, ID stability, and diff generation.
- Golden-file tests for `report` output.
- Integration test on a fixture memory directory for `scan -> patch -> apply`.
- Property tests for "reordering fields does not change semantics" (optional).

## Risks and Mitigations
- Parser brittleness due to LLM-edited formatting.
- Mitigation: tolerant parser plus canonical writer and `lint`.
- Over-eager verification causing user fatigue.
- Mitigation: strict cost-aware scheduler and verify-on-use policy.
- Unclear "authoritative" source definitions.
- Mitigation: per-check explicit authority and evidence attached to findings.
- Accidental destructive edits.
- Mitigation: dry-run, backups, atomic writes, and "deprecate before delete."

## Open Questions
- Where should the audit live: git history only, or an explicit `MEMORY_AUDIT.md`?
- Should topic files get deterministic IDs as well, or only `MEMORY.md`?
- What are the initial memory `type` and `key` conventions you prefer?
- Which reality checks are highest value in your daily workflow (top 5)?
