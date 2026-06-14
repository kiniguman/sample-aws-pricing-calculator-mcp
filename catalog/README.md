# Service Catalog

Per-service curated entries describing the minimum config required to produce a priced, editable estimate on calculator.aws. Each entry is hand-authored, schema-validated, and round-trip verified against the live calculator UI.

## Why this exists

A payload that the save API accepts is not the same as a payload that the calculator renders editable. Some payloads save cleanly but render Read-only (the calculator's frontend rejects them on rehydrate). Others render with a "Required input" warning and a $0 cost. This catalog formalizes "what does a known-good payload for service X actually look like" for the most-used services.

## Status levels

| status | meaning |
|---|---|
| `verified` | End-to-end verified — saves cleanly, fetches back, opens in the browser as fully editable, and renders ≥ $0.01/mo cost. Requires `lastVerifiedAt` and `verifiedEstimateId`. |
| `partial` | Saves and renders, but the calculator shows "Required input" — minimal config is missing fields the user must add interactively. Requires `lastVerifiedAt` and `verifiedEstimateId`. |
| `unverified` | Not yet probed against the live API. Schema-valid but unproven. |
| `broken` | Known not to work. Document why in `traps[]`. |

Current coverage: 16 `verified`, 1 `partial`, 0 `unverified`, 0 `broken`.

## How MCP tools consume the catalog

Tools enrich responses with catalog data when an entry exists:

- `get_service_fields` returns a `catalog` block (`minimalConfig`, required-field hints, `traps[]`) alongside the manifest-derived fields.
- `add_service` uses `required[]` to detect partial entries and emit a `partial: true` warning when an agent omits required inputs.
- `EstimateBuilder` honors `templateId` as a hint, overriding the auto-inferred template for multi-template services (e.g. Cognito's three tiers — Lite, Essentials, Plus).
- The static rehydration linter (`lib/can-rehydrate.js`) reads `required[]` to gate saves on missing pricing-engine-required fields the manifest may underflag.

## Adding a new service

The end-to-end workflow is driven by `scripts/author-catalog.js` (the deterministic spine) plus a mandatory **UI-mirror probe** step that catches the silent-$0 bug class.

### 1. Resolve the serviceCode

```bash
node scripts/author-catalog.js resolve <serviceCode>
```

Returns whether the code is in the manifest and any existing catalog status. If `ok: false`, the JSON's `data.alternatives[]` lists likely typo corrections.

### 2. UI-mirror probe (mandatory for new entries; conditional for existing entries)

**Probe-first rhythm.** For existing-but-unverified entries, save with the current `minimalConfig` first and check rendered cost via `node eval/bin/csv-cost.js <URL>`. If cost is non-zero and matches realistic expectations, skip to step 6 (browser eyeball + verify) — the entry is already correct.

For **new entries** (no existing config to probe), the UI mirror is non-negotiable.

This step catches the silent-$0 bug class — saves cleanly, lints editable, renders $0. The PCT's `validations.required` is necessary but not sufficient: the calculator's pricing engine reads more fields, in shapes the PCT doesn't always describe.

1. **Build the equivalent estimate manually in [calculator.aws](https://calculator.aws/).** Pick non-trivial volume (above any free tier, with one or more rate-driving fields populated).
2. **Save it.** Note the URL.
3. **Fetch the saved blob:**
   ```bash
   node -e "
     const { fetchEstimate } = require('./lib/aws-client');
     (async () => {
       const data = await fetchEstimate('<URL_HASH>');
       // Saved estimates have services either at top-level (data.services)
       // or nested inside groups (data.groups[<name>].services). Walk both.
       const flat = [
         ...Object.values(data.services || {}),
         ...Object.values(data.groups || {}).flatMap(g => Object.values(g.services || {})),
       ];
       for (const svc of flat) {
         console.log('serviceCode:', svc.serviceCode, 'estimateFor:', svc.estimateFor);
         for (const [k, v] of Object.entries(svc.calculationComponents || {})) {
           console.log(' ', k, ':', JSON.stringify(v));
         }
       }
     })();
   "
   ```
4. **Confirm the URL renders priced cost:**
   ```bash
   node eval/bin/csv-cost.js "https://calculator.aws/#/estimate?id=<URL_HASH>"
   ```
   If `monthlyCost: 0`, your manual config wasn't sufficient — fix it in the UI and re-save.

The output of step 3 is your ground-truth field set + value shapes. The catalog's `minimalConfig` must match this *structurally* (same field names, same value-shape — wrapped objects vs scalars).

#### Pro-tip: pricing aggregation files

For multi-template / multi-selector services (RDS, EC2, Fargate), the calculator's frontend fetches a JSON file listing every valid selector tuple before building the UI. URL pattern:

```
https://calculator.aws/pricing/2.0/meteredUnitMaps/<serviceFamily>/USD/current/<calc-id>/<URL-encoded-region>/primary-selector-aggregations.json
```

Find the exact URL by opening calculator.aws in a browser, opening DevTools → Network tab, navigating to the service, and filtering for `primary-selector-aggregations`. The file is the authoritative source for *which combinations of instance type / deployment / term type / etc. are valid* — useful when picking values for `minimalConfig`. Example for RDS PostgreSQL in us-east-1:

```bash
curl -sL --compressed "https://calculator.aws/pricing/2.0/meteredUnitMaps/rds/USD/current/rds-postgresql-calc/US%20East%20(N.%20Virginia)/primary-selector-aggregations.json" \
  | jq '.aggregations[] | select(.selectors."Instance Type" == "db.r6g.large")'
```

### 3. Generate the stub or edit the existing entry

If new:
```bash
node scripts/author-catalog.js generate <serviceCode>
```
Stub starts with `status: "unverified"` and PCT-derived `required[]` + `optional[]`.

If existing-but-unverified: open `catalog/services/<serviceCode>.json` directly. **Audit `minimalConfig` against your UI-mirror output from step 2.** Common gaps:

- Missing fields the pricing engine reads but the manifest doesn't flag as required.
- Wrong shapes — e.g. `columnFormIPM` requires the wrapped `{value: [{...}]}` form, NOT dotted-path keys like `"columnFormIPM[0].Instance Type"`.
- Wrong `templateId` for multi-template services (e.g. picking the wrong tier of Cognito).

### 4. Apply the minimality discipline

`minimalConfig` is the **smallest config that produces an editable, priced estimate** — not the maximal config that mirrors what the UI happens to emit. After the UI-mirror gives you the full field set, drop fields one at a time until cost drops or the calculator UI shows a "Please specify value..." or "required-input" warning. The minimum is the one where removing any single field breaks priced rendering.

Empirically test by re-saving with each candidate field removed. If cost stays the same, the field was redundant; drop it.

### 5. Save + lint preflight + cost check

```bash
node scripts/author-catalog.js preflight <serviceCode>   # offline lint
node scripts/author-catalog.js save <serviceCode>        # real save
node eval/bin/csv-cost.js "<URL>"                        # cost render check
```

Iterate steps 3–5 until cost is non-zero and matches realistic expectations.

### 6. Browser-verify the four conditions

Open the saved URL and confirm:

- The service row appears with the right name and region.
- All `minimalConfig` values are visible in the row's config summary.
- The estimate is editable — no "Read-only" banner, no "required-input" warning.
- **Cost is non-zero on initial page load** (no need to click edit on any row).

### 7. Bump status to verified

```bash
node scripts/author-catalog.js verify <serviceCode> \
  --browser-confirmed yes-all-four \
  --estimate-id <40-char hex from URL>
```

The script refuses without both flags. If only some conditions passed, propose `status: "partial"` instead with a trap explaining what's missing.

### 8. Add an eval scenario

Each verified entry should have a corresponding eval scenario in `eval/scenarios/<service>-minimal.yaml` asserting `estimate_renders_cost` with a `min_monthly_usd` floor. The floor protects against future PCT/pricing changes that drop the entry's cost rendering. See existing scenarios for the format.

```bash
python eval/run.py <scenario-id>            # confirm new scenario passes
SKIP_NETWORK=1 npm test                     # confirm no unit-test regression
```

### 9. Commit

One entry + its eval scenario per commit:

```
feat(catalog): verify <serviceCode> + eval scenario

<one-line summary of any minimalConfig changes and the renders-priced result>
Estimate id: <40-char hex>
```

## Schema field reference

See `catalog/schema.json` for the canonical schema. Brief reference:

- `serviceCode` — must match a manifest entry's `serviceCode`.
- `displayName` — human-readable name shown to agents.
- `templateId` — the `estimateFor` value the calculator expects. Find it in the PCT's `templates[].id`.
- `status` / `lastVerifiedAt` / `verifiedEstimateId` — verification state and provenance.
- `required[]` — fields the pricing engine reads (often broader than the manifest's `validations.required: true`). Each entry: `{ field, hint, shape?, enum?, default?, example? }`.
- `optional[]` — same shape as `required[]`; fields the agent might want to set.
- `traps[]` — gotchas that change agent behavior. Each trap should fit one of the utility types described under "Trap quality standard" below — author-only or unverifiable claims should not be added.
- `subServices[]` — for parent envelopes, lists each child's `{ serviceCode, estimateFor, required[], productCodes? }`. `productCodes` is used for orphan-child redirects (e.g. routing `titanTextEmbeddingsV2` to its parent envelope).
- `defaultFields` — fields the calculator silently injects when omitted, with their default values. Used by the lint's `column-form-default-trap` predicate to refuse saves that would silently price unwanted defaults.
- `minimalConfig` — the smallest config that produces an editable, priced estimate. For parent envelopes, keyed by sub-service code.

## Trap quality standard

Traps are agent-facing — every entry under `traps[]` is read by an LLM constructing a config. To keep the catalog signal-to-noise high, each trap should provide one of the following utilities:

- **Prevents save-failure** — without this trap, the agent's save would fail (lint refusal, value validation, sub-service-selector rejected).
- **Prevents silent-zero** — without this trap, save+lint pass but cost renders $0 in the calculator.
- **Steers selection** — empirically demonstrated by a probe in `eval/scenarios/`, manifest-derived (the mechanism is visible to `get_service_fields`), or a well-known AWS pricing fact (e.g. "Multi-AZ doubles cost"). Affects which option the agent picks rather than whether the save succeeds.

What does NOT belong in `traps[]`:

- Author-side guidance (notes telling future maintainers how to interpret a tool, or how to verify the entry).
- Historical context (when something was renamed, when a bug was fixed).
- Unfalsifiable prose with no actionable lever for the agent.
- Anything an agent could derive from a single `get_service_fields` call.

Such notes can live in code comments or in a separate maintainer doc — but not in the agent-visible `traps[]` array.

## What does NOT belong in the catalog

- Pricing logic, validation arithmetic — that's the calculator's job.
- Anything that can't be verified by round-trip — mark it `unverified`, don't fabricate.
- Field definitions copied from the PCT — those are derivable; the catalog is for empirical truth.
- UI labels — those are i18n'd in the PCT and shouldn't be hardcoded here.

## Drift

When AWS changes a contract (PCT version bump, template rename), an entry's saved URL may stop rendering priced. The fix is:

1. Re-run the cost-oracle sweep to find affected entries: `npm run validate-catalog:cost`.
2. For each failing entry, repeat the UI-mirror probe (step 2) and update `minimalConfig` to match the current contract.
3. Re-eyeball the URL in the browser (step 6).
4. Update `lastVerifiedAt` and `verifiedEstimateId` (and any changed fields).
5. Commit with message `Refresh catalog entry for <serviceCode> (<reason>)`.
