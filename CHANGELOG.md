# Changelog

All notable changes to the local AWS Pricing Calculator MCP server are
documented here. Format follows [Keep a Changelog](https://keepachangelog.com/).

## Unreleased

### Added

- **9 MCP tools** for programmatic AWS calculator estimate construction:
  `search_services`, `get_service_fields`, `create_estimate`,
  `add_service`, `build_estimate`, `validate_estimate`,
  `export_estimate`, `import_estimate`, `get_server_info`. The full tool
  surface is registered in `mcp-server.js`; long descriptions live in
  `lib/tool-descriptions.js`.
- **Static rehydration linter** (`lib/can-rehydrate.js`) with 12
  predicates: `template-existence`, `required-field-presence`,
  `value-parsability`, `sub-service-active-list`,
  `definition-unavailable`, `empty-estimate`, `one-of-mutex`,
  `unknown-field-id`, `invalid-option-id`, `invalid-region`,
  `column-form-default-trap`, `tenancy-pricing-mismatch`. Refuses saves
  the calculator would render read-only or silently price wrong, with
  agent-actionable recovery hints in `lib/lint-hints.js`.
- **Curated service catalog** (`catalog/services/*.json`). Each entry
  declares verified `minimalConfig`, required-field hints with
  examples, traps documenting service-specific gotchas, sub-service
  routing, product-code redirects (e.g. for Bedrock parent envelopes),
  and `defaultFields` for the silent-default field-injection class.
- **Eval harness** (`eval/`) with scripted and LLM-driven scenarios.
  Paired catalog drift audits (`cat-*-with`/`cat-*-without`),
  DOM-scraped cost oracle (`lib/dom-cost.js`), saved-blob field
  assertions (`saved_blob_field_equals` predicate), and trace-event
  correlation. ~84 scenarios across cataloged services.
- **Structured trace events** (`lib/trace-events.js`) for save round-trips
  (`save.send`/`save.ok`/`save.fail`), lint outcomes, session starts,
  template-hint usage, and EC2 tenancy remap signals. Routed through
  `lib/trace-logger.js` to stderr; toggle via `TRACE` env var.
- **Discovery-time helpers**: synthetic field surfacing for fields the
  manifest hides inside composite components (e.g. EC2 utilization);
  parent-envelope and product-code redirects in `get_service_fields`
  and `search_services`; partial-entry warnings on `add_service` so
  agents see missing required fields on the same call rather than
  during a later validate or export.
- **Build pipeline**: `npm run build` produces `dist/aws-calculator.zip`
  + `dist/mcp-server.js` (single-file bundle for runtime deployment).
  `dist/bundle-contract.json` describes the bundle's tool surface and
  schema for downstream contract testing.

### Methodology

- **Verify at user layer.** Behavior fixes ship with eval scenarios
  that drive an LLM agent through the end-to-end flow and assert on
  the saved blob — not just the transform output. Internal tests catch
  layer-specific regressions; eval scenarios catch the gap between
  "transform behaves correctly given X" and "agents produce X."
- **Catalog as data, lint as defense.** The catalog declares what
  fields the pricing engine actually needs (often broader than the
  manifest's `validations.required: true`). The lint mirrors the
  calculator's own silent-zero gate — refuse saves where partial-pop
  would render at $0 — without flagging configurations the calculator
  would silently and correctly zero (e.g. unused feature gates).
- **Don't trust agent narration.** Agents narrate intent; saved blobs
  show effect. Verification compares the saved blob to the user's
  request, not the agent's prose. The `saved_blob_field_equals`
  predicate is the cheap, durable form.

### Known limitations

- The lint predicates cover ~90% of read-only / required-input traps
  observed in practice. A small number of math-walk false-positive
  classes (e.g. independent-slot patterns in MediaLive) require
  service-specific shape detection that's still evolving.
- The DOM-scraped cost oracle requires Playwright; deployment runtimes
  without Chromium can run the lint and trace events but cannot run
  the cost oracle.
- Per-service catalog coverage is partial (~30 services verified). The
  lint and trace events work uncatalogued, but uncatalogued services
  miss the magnitude-calibration role the catalog's `minimalConfig`
  plays.
