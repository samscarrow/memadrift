Here is the scope for Phase 1: The Memory Kernel.
Objective

Build a standalone Python CLI tool (mem-cli) that manages MEMORY.md. It must reliably handle IDs, calculate drift scores, and enforce the schema without requiring an LLM to run.

Success Metric: You can manually run mem-cli add --key editor --value vim and mem-cli verify, and the system correctly updates the file, calculates stable IDs, and detects if the local environment contradicts the file.
Workstream A: The Data Contract (Schema Strictness)

Goal: Define the storage format so rigidly that a Regex can parse it 100% of the time.

    Define MEMORY.md Format:

        Header: YAML frontmatter for global config (e.g., drift_threshold: 0.8).

        Body: A strict pipe-delimited table or labeled list.

        Constraint: No free-text notes outside of dedicated "Details" sections.

    Define schema.yaml (The Canonicalizer):

        To solve the "Semantic Drift" (Key Fragmentation) issue without a Vector DB, use a rigid Allowlist for Phase 1.

        Deliverable: A YAML file defining allowed keys and their types.
    YAML

    keys:
      env.editor:
        type: string
        source: ["env_var:EDITOR", "git_config:core.editor"]
        aliases: ["editor", "text_editor"]
      user.name:
        type: string
        source: ["git_config:user.name"]

Workstream B: The Engine (Python Logic)

Goal: The "Drift Detector" script. This is the brain.

    ID Generator: Implement the base32(sha256(scope|type|key)) logic.

        Test: ensure running it twice on the same input produces the exact same ID.

    The Parser Class:

        Reads MEMORY.md -> deserializes to List of Dicts.

        Writes List of Dicts -> serializes to MEMORY.md (preserving comments/formatting is hard; consider overwriting cleanly for MVP).

    The Scorer Class:

        Implement the Priority Formula: (Impact * Age) / Cost.

        Task: Hardcode the "Cost" table (e.g., os.environ checks = 0.1, user_input = 100.0).

Workstream C: The Reality Layer (Interfaces)

Goal: Build the plugin system for "Truth".

    Interface Definition: Create an abstract base class VerificationSource.
    Python

    class VerificationSource:
        def check(self, key, expected_value) -> DriftResult:
            # Returns: MATCH, CONTRADICTION, or UNVERIFIABLE
            pass

    Implement "LocalEnv" Source:

        Map env.editor to os.environ.get('EDITOR').

        Map git.* to subprocess.check_output(['git', ...]).

    Implement "User" Source (Mocked):

        For Phase 1, just have this print to console: "User, is this true? [y/n]".

Workstream D: The "Fixer" (Remediation)

Goal: The logic that decides what to do when drift is found.

    Auto-Fix Logic: If source=env and reality differs, automatically update MEMORY.md and set last_verified = now.

    Suspect Logic: If source=user and reality differs (or is missing), change status to suspect and increment a drift_counter.

Implementation Plan (Sprint View)
Step	Component	Task	Est. Complexity
1	Core	Write mem.py that can generate the Deterministic ID from a string.	Low
2	Storage	Create the MEMORY.md read/write parser.	Med
3	Canon	Implement schema.yaml loading and Alias resolution (map "editor" -> "env.editor").	Low
4	Reality	Build the LocalEnv checker (check $EDITOR or Git config).	Med
5	Loop	Wire it up: mem.py verify loops through items, checks Reality, updates dates.	High
