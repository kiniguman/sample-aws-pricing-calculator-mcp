# Changelog

All notable changes to the AWS Pricing Calculator MCP server are
documented here. Format follows [Keep a Changelog](https://keepachangelog.com/).

## 1.2.0 — 2026-06-14

### Added

- **Two new MCP tools**:
  - `validate_estimate` — dry-run preflight that builds the would-be
    saved payload and runs the rehydration linter against it, without
    calling the AWS save API. Returns `{lint_verdict, next_step,
    lint_services, would_be_payload}` so an agent can confirm an
    estimate would render before paying the round-trip.
  - `build_estimate` — one-shot create + add-services + lint + save in
    a single call. Returns the shareable URL on success, or a
    structured envelope identifying which services need field
    discovery (`get_service_fields`) before retry.

- **Static rehydration linter** (`lib/can-rehydrate.js`) — pure
  predicate library that runs against the would-be saved blob to
  predict whether the calculator will render it editable. Refuses
  saves that would render read-only (template missing, sub-service
  shape errors, mutually-exclusive options both set, value-shape
  problems) or required-input (declared-required fields missing).
  Failures carry agent-actionable hints (`lib/lint-hints.js`)
  pointing the LLM at the specific recovery: which field to set,
  which option to swap, which service to redirect.

- **Curated service catalog** (`catalog/services/*.json`, 16 verified
  entries) — per-service hints declaring the smallest config that
  produces a priced editable estimate, pricing-engine-required fields
  the manifest underflags, gotcha notes (`traps[]`), sub-service
  routing for parent envelopes, and product-code redirects (e.g.
  Bedrock model parents → child model code). The catalog is loaded
  at runtime from per-service JSON files; a JSON Schema in
  `catalog/schema.json` validates entries.

- **Optional HTTP transport** (`MCP_TRANSPORT=http`) — opt-in
  alternative to the default stdio transport, for hosted deployments
  that need an HTTP entry point. Stdio remains the default; existing
  local clients (Claude Desktop, Kiro, Cursor, VS Code) work
  unchanged.

- **Pluggable estimate store + DynamoDB backend**
  (`lib/estimate-store.js`, `lib/estimate-store-dynamodb.js`) —
  selectable via `ESTIMATES_STORE` env var. The default in-memory
  store keeps the local developer experience unchanged (no AWS
  account needed); the DynamoDB store enables stateless multi-replica
  deployments where in-flight estimates must survive process
  restarts and round-robin routing across replicas.

- **Ambiguity rejection in `findService`** — short generic queries
  like `"RDS"` or `"S3"` now return a candidate list instead of
  silently grabbing an unrelated backup or archival service. A
  unique exact-name match still resolves; multiple partial matches
  surface the candidates so the caller can pick. Contributed by
  Marcel Törpe (`info@frumania.com`).

- **Scenario-driven eval harness** (`eval/`) — 87 YAML scenarios
  driving either scripted MCP calls (fast, AWS-free) or an
  LLM-driven agent (Bedrock Haiku) against the same predicate
  library. Predicates assert outcomes on the saved blob:
  `estimate_renders_cost` (Playwright DOM scrape of the calculator's
  rendered total), `saved_blob_field_equals` (structural assertion
  on what the agent actually saved), `validate_must_pass`
  (refuse-on-lint check). The harness also pairs `with-catalog` vs
  `without-catalog` scenarios so a maintainer can verify whether each
  catalog entry earns its place via cost-magnitude drift.

- **Structured trace events** (`lib/trace-logger.js`,
  `lib/trace-events.js`) — one JSON line per event on stderr, off by
  default, enabled with `TRACE=1`. Covers tool invocations
  (`tool.call`/`tool.result`), save round-trips
  (`save.send`/`save.ok`/`save.fail`), lint outcomes
  (`lint.refused`/`lint.passed`), and session boundaries
  (`session.start`). Designed for ingestion by downstream
  observability — stable event names, structured fields, no
  human-prose mixed into the JSON payload.

- **Build pipeline** — `npm run build` produces a single-file
  esbuild bundle at `dist/mcp-server.js` plus `dist/aws-calculator.zip`
  (the bundle plus the catalog files and a few runtime libs zipped
  for hosted deployment). `dist/bundle-contract.json` describes the
  bundle's environment-variable surface (6 vars: `ESTIMATES_STORE`,
  `ESTIMATES_TABLE`, `ESTIMATES_TTL_SECONDS`, `MCP_TRANSPORT`,
  `TRACE`, `TRACE_RESULT_TEXT_MAX`) so downstream consumers can
  typecheck their CDK/Terraform against the actual surface.

### Changed

- **`export_estimate` now refuses to save** when the static
  rehydration linter predicts the resulting blob would render
  read-only or required-input. Previously, every call returned a
  shareable URL regardless of whether the resulting estimate would
  render. Callers should check the response shape: a successful
  save returns the URL as before; a refused save returns
  `{lint_verdict: 'read_only'|'required_input', next_step: ...}`
  with an actionable recovery hint. Use the new `validate_estimate`
  tool to preflight before calling `export_estimate` if you want to
  separate validation from save.

- **`add_service` now validates field IDs and values** against the
  live service definition, catching dropdown options that don't
  exist, fileSize unit format errors, numeric/frequency type
  mismatches, and unsupported region/service pairs. Unambiguous
  mistakes (case mismatches, single-character typos, number-to-string
  coercion) are auto-corrected and surfaced via a new `corrections`
  array on the per-service result. Calls that would have silently
  created a malformed estimate now either succeed with corrections
  applied or return a structured error pointing at the offending
  field.

- **`add_service` returns a `partial: true` warning** when the
  catalog or manifest declares required fields the agent omitted.
  The entry still registers, but the agent sees on the same call
  that more discovery is needed — rather than learning during a
  later `validate_estimate` or `export_estimate`.

- **`get_service_fields` redirects deprecated parent shells** to the
  verified child service code via a `redirect_to_parent` envelope
  (e.g. `amazonS3` → `amazonS3Standard`). The envelope includes the
  child code and a preview of its fields. For curated services, the
  response also gains a `catalog` block with `minimalConfig`,
  required-field hints, and `traps[]`.

### Removed

- The BDD/Playwright `validation/` suite from PRs #5 and #6, replaced
  by the static rehydration linter (`lib/can-rehydrate.js`) and the
  scenario-driven eval harness (`eval/`). Thanks to the original
  contributors of #5 and #6 — the BDD scenarios and field-mapping
  work informed the predicate design.

### Known limitations

- The lint predicates are static — they catch read-only and
  required-input failures observable from the saved blob shape, but
  cannot evaluate runtime-only failure classes (math/expression
  errors during pricing recalculation, `columnFormIPM` "Best Match"
  failures against the live pricing index). The DOM cost oracle is
  the runtime backstop for those.

- The DOM cost oracle requires Playwright + Chromium; deployment
  runtimes without a browser can run the lint and trace events but
  cannot run the cost oracle.

- Catalog coverage is partial (16 verified entries against ~436
  manifest services). Uncatalogued services still benefit from the
  lint and trace events — they just don't get the
  magnitude-calibration role the catalog's `minimalConfig` plays for
  cataloged services.
