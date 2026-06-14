# Skills

Skills are markdown-driven runbooks Claude follows to perform multi-step authoring or validation work in this repo. Each skill has a `SKILL.md` that the orchestrator (the main Claude session) reads and executes step-by-step.

## How to invoke

Mention the skill by name to Claude — e.g. "use the author-catalog-entry skill on awsKeyManagementService for a payment-processing scenario." Claude will load the skill's instructions and follow them.

## Available skills

| Skill | Purpose |
|---|---|
| [`author-catalog-entry`](./author-catalog-entry/SKILL.md) | Author or refine a single catalog entry under `catalog/services/`. Spawns a Haiku subagent to build a real estimate; the orchestrator proposes catalog edits when the subagent stumbles. Edits are proposed only — never auto-written. |

## Adding a new skill

1. Create `skills/<skill-name>/SKILL.md`.
2. Start with YAML frontmatter:
   ```yaml
   ---
   name: <skill-name>
   description: <one paragraph; this is what Claude reads to decide whether to use the skill>
   ---
   ```
3. Body is the runbook. Be explicit: list inputs, required tools, the exact loop, success/failure criteria, and the output format.
4. Reference helpers (scripts, library functions) by absolute repo path so the orchestrator doesn't have to guess.
