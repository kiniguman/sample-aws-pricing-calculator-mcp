# Eval — agent-behavior assertions

Reusable predicate library + stdio-MCP driver + LLM driver +
scenario runner. Two scenario styles: **scripted** (hardcoded MCP
calls, fast, no AWS deps) and **LLM-driven** (Bedrock Haiku gets the
tools and a natural-language prompt, captured trajectory is scored
the same way). Predicate library is shared; downstream consumers can
import it for their own deployment-side eval.

Hand-rolled — no external eval framework. Dependencies are
`pyyaml` (scenario parsing) and `boto3` (Bedrock for LLM scenarios),
plus the bundle's existing Playwright + Node MCP SDK. Scenarios are
plain YAML; predicates are plain Python functions discovered via
`getattr` from `predicates.py`.

## What this is

A scenario in `eval/scenarios/*.yaml` is either:

- **Scripted** — `calls:` array of MCP tool calls + `expectations:`
  predicates. The runner spawns `mcp-server.js`, drives the calls
  over stdio, captures the trace, scores it. No LLM. CI-friendly.
- **LLM-driven** — `prompt:` natural-language user message +
  `expectations:`. The runner spawns `mcp-server.js`, gives Haiku
  4.5 the MCP tools as Bedrock tool definitions, sends the prompt,
  captures every tool call the agent makes. Same `TraceResult`
  shape; same predicates score it.

LLM-driven scenarios test what production logs cannot:
- Did the agent call `get_service_fields` before committing to a save?
- Did the agent's config use catalog `minimalConfig` keys?
- Did the agent recover from a `needs_field_grounding` redirect?

As of this release: **87 scenarios** — 22 scripted + 65 LLM-driven.

## Running

```bash
pip install pyyaml             # one-time
python eval/run.py             # all scenarios
python eval/run.py a b c       # specific scenarios by id
python eval/run.py --list      # available scenarios
python eval/run.py --json      # machine-readable
python eval/run.py -v          # verbose, per-call
```

Scripted scenarios need no AWS credentials. LLM scenarios need
Bedrock access in `us-east-1` (uses the cross-region inference
profile `us.anthropic.claude-haiku-4-5-20251001-v1:0`).
The MCP server's outbound calls go to public CloudFront endpoints,
not your AWS account.

Exit code 0 if all pass, 1 if any predicate fails, 2 on usage error.

## Speed knobs

The full suite takes several minutes (LLM Bedrock calls + Playwright
launches dominate). Three flags shrink the loop:

```bash
python eval/run.py --scripted-only       # skip the 65 LLM scenarios (~30s for the 22 scripted)
python eval/run.py --skip-dom-oracle     # skip estimate_renders_cost predicates (no Playwright)
python eval/run.py --rerun-failed        # only the previous full run's failures
```

`--rerun-failed` reads `eval/_results/last-failed.txt`, which is
written automatically at the end of every full run. Subset runs
(specific ids, `--scripted-only`, `--rerun-failed` itself) do NOT
overwrite the seed list, so you can iterate on a flake or
regression as many times as you want without re-running the full
suite. After the issue is resolved, do another full run to refresh
the list.

## Files

```
eval/
  predicates.py             # assertion library — pure, reusable
  stdio_driver.py           # spawns mcp-server.js, scripted-call driver
  llm_driver.py             # Bedrock Haiku driver (lazy-imported)
  csv_oracle.py             # fetches rendered cost via Node bridge
  bin/csv-cost.js           # Node bridge to lib/dom-cost.js
  run.py                    # CLI: load YAML, dispatch by shape, score
  scenarios/*.yaml          # one file per scenario
  README.md                 # this file
```

## Predicate API

Each predicate is `assert_<name>(trace, **kwargs) -> AssertionOutcome`.
The runner looks up `assert_<predicate>` from `predicates.py` and
calls it with the keys named in the scenario expectation.

Scenario expectation:
```yaml
expectations:
  - predicate: lint_verdict
    expected: editable
```

Becomes the call:
```python
predicates.assert_lint_verdict(trace, expected='editable')
```

Today's predicates:

- `save_succeeded` — some path produced a calculator URL.
- `export_refused` — `export_estimate` was refused by the linter
  with the expected verdict. Use to assert the lint-refusal path
  fired correctly.
- `no_tool_errors` — every call returned `isError:false`.
- `lint_verdict` — last `validate_estimate` returned the expected
  verdict.
- `trajectory_includes` — given tool sequence appears (loose / strict).
- `response_field_present` — last call to a tool returned a JSON
  body with the given dotted-path field.
- `max_tool_calls` — trace has at most N calls (cost guardrail).
- `estimate_renders_cost` — the saved URL renders ≥
  `min_monthly_usd` (default 1¢) when scraped from the calculator's
  rendered DOM via `lib/dom-cost.js`. Catches the silent-$0 bug
  class that the static linter cannot evaluate. Requires Playwright
  + headless Chromium; ~5s per scenario.
- `saved_blob_field_equals` — fetches the saved estimate by ID and
  asserts a specific field's value matches the expected value.
  Catches "agent narrated X but actually saved Y" failures.
- `saved_blob_field_count` — fetches the saved estimate and asserts
  the number of services / groups / matching fields. Useful for
  multi-service prompts.

Add new predicates by writing `assert_<name>(trace, ...)` in
`predicates.py`. The runner discovers them via `getattr`.

## Scenario format

### Scripted (`calls:`)

```yaml
id: <unique-id>
description: |
  Free-form prose.
calls:
  - tool: <mcp-tool-name>
    args: { ... }
  - tool: <next>
    args:
      estimate_id: ${estimate_id}    # threaded from prior create/build response
expectations:
  - predicate: <name>
    <kwarg>: <value>
```

The `${estimate_id}` template var is set automatically when a
`create_estimate` or `build_estimate` call returns one.

### LLM-driven (`prompt:`)

```yaml
id: <unique-id>
prompt: |
  Build me an estimate for X with Y configuration.
description: |
  Free-form prose explaining what behavior this is testing.
system_extra: |
  Optional additional system framing. Do NOT instruct on tool
  sequencing — the eval measures whether the agent figures it out.
max_turns: 20    # optional override
expectations:
  - predicate: trajectory_includes
    sequence: [get_service_fields]
    strict: false
  - predicate: save_succeeded
```

The runner spawns mcp-server.js, lists its tools via `tools/list`,
hands them to Haiku as Bedrock tool definitions, and loops:
prompt → assistant tool_use → MCP dispatch → tool_result → next
turn, until the agent stops calling tools or `max_turns` hits.

## How this relates to deployment-side evals

The `predicates.py` module is intentionally transport-agnostic — it
asserts on the response *shape* the MCP server emits, not on how the
response was retrieved. A hosted deployment can reuse the same
predicates against an HTTPS endpoint by dropping in its own driver
(in place of `stdio_driver.py`) without forking the assertion logic.

## What this is NOT

- A replacement for unit tests. Tests (`test/`) cover pure functions
  and module-level invariants in seconds with mocked I/O; scenarios
  here exercise end-to-end MCP behavior with real saves and DOM
  scrapes (~5–7s each).
