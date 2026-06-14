---
name: author-catalog-entry
description: Use this skill to author or refine a single catalog entry under catalog/services/. Inputs are a serviceCode (manifest key) and an optional natural-language scenario. Output is the saved estimate URL plus a diff for the user to review and apply. The deterministic spine is `scripts/author-catalog.js`; the human steps are the UI-mirror probe and the four-condition browser eyeball.
---

# Author Catalog Entry

The catalog is the source of truth for an agent building real estimates. Each entry tells the calculator MCP server "for service X, here's the smallest config that produces a priced, editable estimate" plus traps the agent should know.

This skill walks the human through authoring or refining one entry, end to end.

## Inputs

- **serviceCode** (required) — manifest key, e.g. `awsKeyManagementService`, `amazonSimpleQueueService`.
- **scenario** (optional) — natural-language description of what to estimate. Defaults to "build a minimal valid estimate for this service."

## Required tooling

The local repo's shell tools (npm, node, scripts/), Edit/Write access to `catalog/services/*.json`, and a browser for the UI-mirror probe. The calculator MCP server does NOT need to be connected for the script flow.

## Catalog entry shape — quick reference

Don't read multiple existing entries to learn this. The schema is in `catalog/schema.json`; here's what every entry contains and why:

| Field | Required | Purpose |
|---|---|---|
| `serviceCode` | yes | Manifest key. Must be a valid manifest entry (use `node scripts/author-catalog.js resolve <code>`). |
| `displayName` | yes | Human-readable name. Often differs from the calculator's UI label (e.g. "Amazon SageMaker AI" vs PCT's "Amazon SageMaker"). |
| `templateId` | yes | The `estimateFor` value. For sub-service-selector parents it's the wrapper template id (e.g. `simpleStorageServiceClassesGroup`); for plain services it's `templates[0].id` from the PCT. |
| `status` | yes | `unverified` (this skill always starts here) / `partial` / `verified` / `broken`. Only browser-eyeballed entries become `verified`. |
| `required[]` | no | PCT-required fields. Source of truth for "this field MUST be sent." |
| `optional[]` | no | PCT-optional fields the agent might want to set. |
| `traps[]` | no | Free-form prose listing gotchas the PCT can't express. **The most valuable field.** |
| `subServices[]` | no | For sub-service-selector parents only — describes each child's `serviceCode`, `estimateFor`, and `required[]`. |
| `minimalConfig` | yes | Smallest config that produces an editable estimate. Plain shape for top-level services; keyed by sub-service code for parent envelopes. |

### Plain service example

```jsonc
{
  "serviceCode": "aWSLambda",
  "displayName": "AWS Lambda",
  "templateId": "lambdaWithFreeTier",
  "status": "verified",
  "lastVerifiedAt": "2026-05-29",
  "verifiedEstimateId": "<40-char-hex>",
  "required": [{ "field": "numberOfRequests", "hint": "...", "shape": "...", "example": "..." }],
  "optional": [...],
  "traps": ["Lambda's pricing engine reads sizeOfMemoryAllocated even though the PCT marks it optional — saves without it render $0."],
  "subServices": [],
  "minimalConfig": {
    "region": "us-east-1",
    "description": "API handler",
    "numberOfRequests": { "value": "1", "unit": "millionPerMonth" },
    "durationOfEachRequest": "200",
    "sizeOfMemoryAllocated": { "value": "1", "unit": "gb|NA" }
  }
}
```

### Sub-service-selector parent (S3, AppSync, SageMaker pattern)

```jsonc
{
  "serviceCode": "amazonSimpleStorageServiceGroup",
  "displayName": "Amazon S3",
  "templateId": "simpleStorageServiceClassesGroup",
  "subServices": [
    { "serviceCode": "amazonS3Standard", "estimateFor": "s3Standard", "required": [...] }
  ],
  "minimalConfig": {
    "amazonS3Standard": {
      "region": "us-east-1",
      "description": "Static assets",
      "s3StandardStorageSize": { "value": "500", "unit": "gb|month" }
    }
  }
}
```

### `columnFormIPM` (instance-table) shape

Some services (RDS, SageMaker Real-Time Inference) use a `columnFormIPM` matrix for instance type / deployment / pricing. Send the WRAPPED shape — the dotted-path syntax is rejected by `validateConfigKeys`:

```jsonc
"columnFormIPM": {
  "value": [{
    "Number of Nodes": { "value": "1" },
    "Instance Type": { "value": "db.r6g.large" },
    "Deployment Option": { "value": "Single-AZ" },
    "TermType": { "value": "OnDemand" },
    "undefined": { "value": { "unit": "100", "selectedId": "%Utilized/Month" } }
  }]
}
```

The literal `"undefined"` key is the matrix-internal utilization slot (RDS-style). Direct Connect uses a namespaced variant — see `catalog/services/awsDirectConnect.json`.

### Field-value shapes

| Field type | Shape |
|---|---|
| `numericInput` | string: `"1000"` |
| `frequency` | object: `{ value: "19", unit: "millionPerMonth" }` — unit MUST be in the field's options |
| `fileSize` | object: `{ value: "512", unit: "mb|NA" }` — `<size>\|<freq>` format |
| `dropdown` | string matching one of the option IDs |
| `durationInput` | object: `{ value: "960", unit: "min" }` |

### Why `traps[]` matters more than the schema

Every other field describes what the PCT says. Traps describe what the PCT can't say:
- "First management trail is FREE — Modeling only management volume produces $0"
- "Express workflow memory uses fileSize unit 'mb|NA' (not 'mb|month')"
- "Frequency unit MUST be perHour/perDay/perMonth — millionPerMonth zeroes pricing"
- "The 'undefined' selector in columnFormIPM is the literal matrix-slot key for utilization"

Authoring good traps is the main creative work in this skill.

## The Workflow

```
1. Resolve target
2. Generate / load catalog stub
3. UI-mirror probe (browser, manual)
4. Reconcile minimalConfig + auto-pad if too thin
5. Schema + lint preflight (offline)
6. Real save + DOM cost predicate check
7. Browser-eyeball → verified bump
```

Steps 1–2, 4–7 are driven by `scripts/author-catalog.js`. Step 3 is the manual probe in calculator.aws — this is the load-bearing step the skill cannot automate, because the calculator's frontend chooses what fields it accepts in ways the PCT doesn't fully document.

## The deterministic spine: `scripts/author-catalog.js`

Each subcommand emits structured JSON to stdout. Use `2>/dev/null` to drop status messages and parse JSON directly.

| Step | Subcommand | What it does |
|---|---|---|
| 1 | `resolve` | Confirms serviceCode in manifest; surfaces alternatives if missing. |
| 2 | `generate` | Creates the stub via `scripts/generate-catalog-stub.js`. Idempotent. |
| 4 | `pad` | Suggests minimalConfig values from surfaceable PCT fields. `--apply` writes. |
| 5 | `preflight` | Schema validate + offline rehydration lint. Reports `lint_verdict`. |
| 6 | `save` | Real save via `build_estimate` + round-trip check. |
| 7 | `verify` | Bumps status to verified after browser confirmation (gate). |
| - | `status` | Read current entry state. Useful between steps. |

## Step 1 — Resolve target

```bash
node scripts/author-catalog.js resolve <serviceCode> 2>/dev/null
```

Returns `{ ok, data: { in_manifest, manifest_name, sub_type, catalog_status } }`. If `ok: false`, the JSON includes `data.alternatives[]` — present them and ask the user which one they meant.

## Step 2 — Generate or load catalog stub

```bash
node scripts/author-catalog.js generate <serviceCode> 2>/dev/null
```

Creates the stub (no-op if file exists). Status starts at `unverified`.

## Step 3 — UI-mirror probe (manual, load-bearing)

Open https://calculator.aws/ in a fresh tab. Build the equivalent estimate manually for the target service with realistic, non-trivial values (volume above any free tier). Save it. Note the URL.

Fetch the saved blob to see exactly what fields the calculator accepted and in what shape:

```bash
node -e "
  const { fetchEstimate } = require('./lib/aws-client');
  (async () => {
    const data = await fetchEstimate('<URL_HASH>');
    const svc = Object.values(data.services)[0];
    console.log('serviceCode:', svc.serviceCode, 'estimateFor:', svc.estimateFor);
    for (const [k, v] of Object.entries(svc.calculationComponents || {})) {
      console.log(' ', k, ':', JSON.stringify(v));
    }
  })();
"
```

The output is the **ground-truth field set + value shapes** your `minimalConfig` must mirror. This step catches the bug class Lambda hid for two weeks (saves clean, lints editable, renders $0): PCT-required ≠ pricing-engine-required.

**Probe-first rhythm.** For existing-but-unverified entries, save with the current `minimalConfig` first and check rendered cost via `node eval/bin/csv-cost.js <URL>`. If cost is non-zero and matches realistic expectations, skip to step 6 — the entry is already correct. Fargate, NAT, and Cognito were correct on first probe; ALB and RDS PG needed the UI mirror because cost was $0 / wrong-shape.

## Step 4 — Reconcile minimalConfig

Edit `catalog/services/<serviceCode>.json`:
- Add any fields from the UI-mirror probe that aren't yet in `minimalConfig`.
- Match value-shape exactly — wrapped objects vs scalars, unit strings, `columnFormIPM` matrix shape.
- Add a `traps[]` entry for any non-obvious gotcha you discovered.

For services with surfaceable PCT fields the script hasn't already filled in:

```bash
# See suggestions
node scripts/author-catalog.js pad <serviceCode> 2>/dev/null

# Write them
node scripts/author-catalog.js pad <serviceCode> --apply 2>/dev/null
```

For services with **0 unconditionally surfaceable fields** (KMS, EBS — everything is `displayIf`-gated), `pad` reports nothing. Hand-author `minimalConfig` from the UI-mirror probe and document the gating in `traps[]`.

## Step 5 — Offline preflight

```bash
node scripts/author-catalog.js preflight <serviceCode> 2>/dev/null
```

Schema validate + rehydration lint. Returns `{ ok, data: { schema_valid, lint_verdict, lint_services, hint } }`.

If `ok: false`:
- `lint_verdict: read-only` → fix the catalog (likely a missing required field, wrong template id, or bad field shape) and re-run.
- `data.schema_errors` set → fix the JSON; the `pad` step's output may have been wrong.

Do NOT proceed to step 6 until preflight passes.

## Step 6 — Real save + cost rendering

```bash
node scripts/author-catalog.js save <serviceCode> 2>/dev/null
```

Returns `{ ok, data: { sharable_url, aws_estimate_id, round_trip_ok, round_trip_issue } }`. Does the real `build_estimate` save AND fetches the estimate back via `import_estimate` to confirm the rehydrated shape matches.

If `round_trip_ok: false`, the `round_trip_issue` field describes what went wrong (typically empty `calculationComponents` or missing services). The estimate was still saved — `sharable_url` is valid — but trust it less.

**Confirm the URL renders priced cost** via the DOM oracle:

```bash
node eval/bin/csv-cost.js "<sharable_url>"
```

Returns `{ monthlyCost, monthlyByService, configByService }`. A non-zero `monthlyCost` is the load-bearing check — saves can succeed and lint editable while still rendering $0 (the Lambda / Step Functions trap class). If `monthlyCost: 0`, return to step 3 (the UI-mirror revealed something `minimalConfig` is still missing).

The `configByService` field shows which fields the calculator's UI surfaced — useful for diagnosing "the save worked but the wrong fields appear in the rendered estimate."

## Step 7 — Browser-eyeball + verified-bump gate

**DO NOT bump `status: "unverified" → "verified"` directly.** The script's structural gate refuses to set verified without explicit confirmation.

Step 7a — Ask the user the four-condition browser eyeball:

> Did you OPEN the URL `<url>` in a browser AND see:
>   1. The service row appears with the right name.
>   2. All sent fields are visible in the row's config summary.
>   3. The estimate is editable (not Read-only).
>   4. Cost is non-zero (or zero is expected for free-tier).
>
> Reply 'yes — all four' to bump status to verified. Anything else, leave at unverified.

Step 7b — Only on an explicit affirmative covering all four:

```bash
node scripts/author-catalog.js verify <serviceCode> \
  --browser-confirmed yes-all-four \
  --estimate-id <sha1 from URL> 2>/dev/null
```

The script refuses if either flag is missing or the affirmation string is not the literal `yes-all-four`. Do not edit the catalog file directly to set verified — the script applies the change atomically and re-validates against the schema.

If only some conditions pass, propose `status: "partial"` instead (saves + renders but with required-input warnings).

## Final report

```
## Catalog authoring complete: <serviceCode>

- Final lint verdict: <verdict>
- Cost predicate: <$X.XX/mo>
- Saved estimate URL: <url>
- Status: <unverified | partial | verified>
```

## After the entry lands

Add an eval scenario at `eval/scenarios/<service>-minimal.yaml` asserting `assert_estimate_renders_cost` with a `min_monthly_usd` floor based on the volume probed in step 6. The floor protects against future PCT/pricing changes that drop the entry's cost rendering. See existing scenarios for the format.

```bash
python3 eval/run.py <scenario-id>           # confirm new scenario passes
SKIP_NETWORK=1 npm test                     # confirm no unit-test regression
```

## Don'ts

- **Don't skip the UI-mirror probe.** It's the only step that catches the silent-$0 trap class.
- **Don't bump status to `verified`** without the four-condition browser eyeball + the script's structural gate.
- **Don't write `verifiedEstimateId` by hand.** Only `verify` should produce it.
- **Don't fabricate fields** the PCT doesn't expose. If the calculator UI doesn't have it, agents shouldn't pass it.
