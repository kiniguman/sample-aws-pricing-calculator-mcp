# AWS Pricing Calculator MCP Server

[Model Context Protocol](https://modelcontextprotocol.io) (MCP) server that programmatically creates, reads, updates [AWS Pricing Calculator](https://calculator.aws/#/estimate) estimates through natural language.

[![Install in Kiro](https://img.shields.io/badge/Install-Kiro-9046FF?style=flat-square&logo=kiro)](https://kiro.dev/launch/mcp/add?name=aws-pricing-calculator-mcp-server&config=%7B%22command%22%3A%22npx%22%2C%22args%22%3A%5B%22-y%22%2C%22sample-aws-pricing-calculator-mcp%40latest%22%5D%7D) [![Install in Cursor](https://img.shields.io/badge/Install-Cursor-blue?style=flat-square&logo=cursor)](https://cursor.com/en/install-mcp?name=aws-pricing-calculator-mcp-server&config=eyJjb21tYW5kIjoibnB4IiwiYXJncyI6WyIteSIsInNhbXBsZS1hd3MtcHJpY2luZy1jYWxjdWxhdG9yLW1jcEBsYXRlc3QiXX0%3D) [![Install in VS Code](https://img.shields.io/badge/Install-VS_Code-FF9900?style=flat-square&logo=visualstudiocode&logoColor=white)](https://insiders.vscode.dev/redirect/mcp/install?name=aws-pricing-calculator-mcp-server&config=%7B%22command%22%3A%22npx%22%2C%22args%22%3A%5B%22-y%22%2C%22sample-aws-pricing-calculator-mcp%40latest%22%5D%7D)

## Key Features

- **Creating Estimates**: Live service definitions from the AWS Calculator CDN (436 services in the manifest). Empirical coverage of agent success: ~54% of services produce a priced estimate from PCT alone; ~30% need a curated catalog entry to avoid silent-$0 traps; the rest are deprecated parent shells handled by automatic redirects. See [Catalog & validation](#catalog--validation).
- **Importing Estimates**: Download existing estimates by URL/ID as JSON (for modifications e.g. swap AWS regions) or Markdown (for LLM analysis)
- **Batch Processing**: Create estimates from Excel/CSV files via LLM-assisted parsing
- **No AWS Credentials Required**: Works without AWS account access

## Example

Prompt:
> Create an AWS Pricing Calculator estimate for a common Wordpress environment on AWS (Dev, Quality, Production).

Output:
![](example1.png)

## Quick Start

Requires [Node.js®](https://nodejs.org/en/download).

```bash
git clone https://github.com/aws-samples/sample-aws-pricing-calculator-mcp.git
cd sample-aws-pricing-calculator-mcp
npm install
npm run build
```

The server communicates over stdio using the MCP protocol — it's designed to be used by MCP-compatible clients (e.g. Claude, Kiro), not called directly via HTTP.

### MCP Client Configuration

Add to your MCP client config (e.g. `~/.kiro/settings/mcp.json`):

Using npm/npx (Also always fetches latest version)
```json
    "aws-pricing-calculator-mcp-server" : {
      "command" : "npx",
      "args" : [ "-y", "sample-aws-pricing-calculator-mcp@latest" ]
    }
```

From local source (after build)
```json
    "aws-pricing-calculator-mcp-server": {
      "command": "node",
      "args": ["/path/to/sample-aws-pricing-calculator-mcp/dist/mcp-server.js"]
    }
```

## MCP Tools

| Tool | Description |
|---|---|
| `search_services` | Search AWS services by name or key. Supports comma-separated queries. |
| `get_service_fields` | Get input field IDs, types, labels, valid options, and selector values for one or more services. For curated services, the response includes a `catalog` block with a known-working `minimalConfig`, required-field hints, and gotcha notes (`traps`). For deprecated parent shells (e.g. `amazonS3` → `amazonS3Standard`), returns a `redirect_to_parent` envelope with the verified child code and a preview of its fields. |
| `create_estimate` | Create a new empty estimate. Returns an estimate ID. |
| `add_service` | Add one or more services to an estimate with config values. Supports batch mode. Validates field names AND values against the service definition (dropdown options, fileSize unit format, numeric/frequency types and their unit enums, region whitelist). Auto-corrects unambiguous mistakes (case mismatches, single-character typos, number-to-string coercion) and returns a `corrections` array on the per-service response listing what was fixed. |
| `build_estimate` | One-shot: create + add services + lint preflight + save. Use when all services are known up front. Returns the shareable URL or, if any service fails validation, a structured `needs_field_grounding` envelope pointing the agent at `get_service_fields` for the affected services. |
| `validate_estimate` | Dry-run preflight: builds the would-be saved payload and runs the static rehydration linter — without calling the save API. Returns `{lint_verdict, next_step, lint_services, would_be_payload}`. Use to confirm an estimate would lint editable before paying the save round-trip. |
| `export_estimate` | Export an estimate to calculator.aws and get a shareable URL. Refuses with an actionable `next_step` if the static linter predicts the saved blob would rehydrate read-only. |
| `import_estimate` | Download an existing estimate by URL or ID. Returns JSON (raw) or Markdown. |
| `get_server_info` | Get version and capability information about this MCP server. |

## Project Structure

```
mcp-server.js              # Entry point — registers the 9 MCP tools, stdio + HTTP transports
lib/
  aws-client.js            # Manifest loading, service definitions, field extraction, save/read APIs
  estimate-builder.js      # In-memory estimate model, AWS payload assembly, export
  ec2.js                   # EC2 agent-friendly → ec2Enhancement transform
  validation.js            # Pre-save config validation (field-id check, value shape + unit enum, region whitelist, auto-correct)
  can-rehydrate.js         # Static rehydration linter (pure)
  can-rehydrate-fetch.js   # Network wrapper around the linter
  surfaceability.js        # Surfaceability index — used by the catalog `pad` subcommand to suggest fields
  lint-hints.js            # Translates lint failures into agent-actionable next_step text
  catalog.js               # Loader for catalog/services/*.json curated entries
  pct-config.js            # Suggest a config from PCT alone (used by `pad` and the diagnostic)
  dom-cost.js              # Playwright DOM scrape — cost numbers + Config Summary from a saved-estimate URL
  handler-helpers.js       # Shared internals for the MCP tool handlers (envelope helpers, field-result builder, redirect detection)
  tool-descriptions.js     # The 9 long agent-facing description strings (separated from wiring)
  estimate-store.js        # Pluggable in-flight estimate store (memory default)
  estimate-store-dynamodb.js # DynamoDB-backed store for stateless multi-replica deployments
  trace-logger.js          # Structured JSON trace events on stderr (one line per event)
catalog/
  schema.json              # JSON Schema for catalog entries
  services/                # Hand-curated per-service skeletons (minimalConfig, traps, subServices)
test/                      # node:test suite (unit + integration; SKIP_NETWORK=1 for offline)
eval/                      # Scenario-driven behavior eval (stdio + LLM drivers)
scripts/                   # Operator tools (catalog authoring, sweep, diagnostic, rehydration check)
```

## Build

```bash
npm run build
```

Produces `dist/mcp-server.js` — a single-file esbuild bundle (minified, CJS, Node platform).

## Tests

```bash
npm test
```

## Architecture

```
┌─────────────────┐       stdio        ┌──────────────────────────────────────┐
│   MCP Client    │◄──────────────────►│         MCP Server                   │
│ (Kiro, Claude,  │   JSON-RPC over    │                                      │
│  Cursor, etc.)  │   stdin/stdout     │  mcp-server.js (entry point)         │
└─────────────────┘                    │    ├── lib/aws-client.js             │
                                       │    ├── lib/estimate-builder.js       │
                                       │    └── lib/ec2.js                    │
                                       └──────────┬───────────┬──────────────┘
                                                  │           │
                                        HTTPS GET │           │ HTTPS POST
                                                  ▼           ▼
                                       ┌──────────────┐  ┌──────────────────┐
                                       │ CloudFront   │  │ AWS Calculator   │
                                       │ CDN          │  │ Save API         │
                                       │              │  │                  │
                                       │ • manifest   │  │ POST /v2/saveAs  │
                                       │ • service    │  │ → returns        │
                                       │   definitions│  │   shareable URL  │
                                       └──────────────┘  └──────────────────┘
```

- The MCP server runs as a **local child process** spawned by the MCP client. It communicates exclusively over stdio — it is not network-accessible.
- All outbound requests are **HTTPS** to public, unauthenticated AWS CloudFront distributions. No AWS credentials are required or used.
- Estimate data is held **in memory only** and is lost when the process exits. No data is persisted to disk.

## How It Works

### Service Discovery

On first use, the server fetches the AWS Calculator manifest from CloudFront, which contains all 436+ services with their keys, names, and definition URLs. Service definitions are fetched on demand and cached. The `get_service_fields` tool parses these definitions to extract input field IDs, types, labels, and valid options into a flat, usable format.

### Estimate Building

`EstimateBuilder` holds services and groups in memory. When you add a service via `add_service`, config is stored as-is using the AWS field IDs. Services can be organized into named groups, and multiple instances of the same service are supported via composite keys (e.g. `aWSLambda:Compute`).

### EC2 Handling

EC2 uses a custom config transform (`lib/ec2.js`) that converts agent-friendly fields (instance type, OS, pricing strategy) into the `ec2Enhancement` format the calculator expects. This includes support for On-Demand, Savings Plans, Reserved Instances, and Spot pricing.

### Partition Support

The server supports three AWS partitions:
- `aws` — standard commercial regions
- `aws-iso` — US ISO East/West
- `aws-iso-b` — US ISOB East

### Export to calculator.aws

When `export_estimate` is called, the builder:

1. Resolves each service name against the manifest
2. Fetches the service definition to get the correct `version`, `serviceCode`, and template ID
3. Maps config keys to `calculationComponents` in the AWS payload format
4. POSTs the assembled payload to the AWS Calculator save API
5. Returns the shareable `calculator.aws` URL

AWS recalculates the actual costs when someone opens the link.

## Environment Variables

All optional:

| Variable | Default | Purpose |
|---|---|---|
| `AWS_SAVE_URL` | CloudFront save URL | Override the AWS Calculator save endpoint (testing). |
| `MCP_TRANSPORT` | `stdio` | Set to `http` to expose the MCP over HTTP on `PORT` (default `8000`, `HOST` default `127.0.0.1`). |
| `ESTIMATES_STORE` | `memory` | In-flight estimate store. See [Estimate persistence](#estimate-persistence). |
| `TRACE` | `off` | Set to `on` (or `1`/`true`/`yes`) to enable structured stderr trace events. Off by default — `emit()` is a no-op and `traceTool` is a passthrough when unset. See [Trace events](#trace-events). |
| `TRACE_RESULT_TEXT_MAX` | `500` | Cap on `resultText` length when tracing is enabled. Errors get a separate higher cap. |

## Estimate persistence

The MCP server keeps in-flight estimates (between `create_estimate` and `export_estimate`) in a pluggable store. Configure with `ESTIMATES_STORE`:

| Value | Description |
| --- | --- |
| `memory` (default) | In-process `Map`. State is lost when the process exits. Suitable for stdio and single-process deployments. |
| `dynamodb` | Persists snapshots in a DynamoDB table. Required for any deployment where `create_estimate` and `add_service` may run in different processes (multi-replica HTTP, Lambda, container runtimes with non-sticky session routing, etc.). |

### `dynamodb` configuration

The AWS SDK packages are NOT bundled with the published artifact (they are declared as optional peer dependencies). Before running with `ESTIMATES_STORE=dynamodb`, install them in your deployment image:

```bash
npm install @aws-sdk/client-dynamodb @aws-sdk/lib-dynamodb
```

Additional env vars when `ESTIMATES_STORE=dynamodb`:

| Variable | Required | Description |
| --- | --- | --- |
| `ESTIMATES_TABLE` | Yes | DynamoDB table name. |
| `AWS_REGION` | Yes | AWS region for the DynamoDB client. |
| `ESTIMATES_TTL_SECONDS` | No | If set, items are written with an `expiresAt` attribute equal to `now + ESTIMATES_TTL_SECONDS`. Pair this with a TTL configuration on the table (TTL attribute name: `expiresAt`) to expire abandoned estimates automatically. |

### Table schema

```
TableName: <ESTIMATES_TABLE>
PartitionKey: id (String)
Attributes:
  id        (String)  the estimate's UUID
  snapshot  (String)  JSON-encoded snapshot of the estimate
  expiresAt (Number)  optional epoch seconds, populated when ESTIMATES_TTL_SECONDS is set
TTL attribute: expiresAt  (configure on the table if you set ESTIMATES_TTL_SECONDS)
```

The IAM role running the server needs `dynamodb:GetItem`, `dynamodb:PutItem`, and `dynamodb:DeleteItem` on the table.

### Implementation notes

- Each estimate is stored as a single JSON string under one item. Estimates that approach DynamoDB's 400 KB per-item cap (hundreds of services) will fail to write — use S3 or chunk-encoding if you need that.
- The store is constructed once at process start. Switching backends requires restarting the process.

## Catalog & validation

### What's in the catalog

The catalog (`catalog/services/*.json`) holds curated per-service hints — the `minimalConfig` an agent should send, fields that need careful shapes, and free-text `traps[]` documenting gotchas the PCT can't express (e.g. "Step Functions' frequency unit MUST be perMonth, not millionPerMonth"). As of the latest commit:

- **27 entries total** (15 verified, 11 unverified, 1 partial)
- The 15 verified entries cover the highest-impact services from production lint analyzer data: Lambda, RDS PostgreSQL, ALB, Fargate, CloudTrail, Direct Connect, NAT Gateway, Transit Gateway, EC2, Cognito, S3 group, SNS, SageMaker, Bedrock, Step Functions
- Each verified entry is reverified end-to-end by `npm run validate-catalog:cost` — saves a fresh estimate from `minimalConfig` and confirms it renders a non-zero cost in calculator.aws

### What's NOT in the catalog (and why that's fine)

A 2026-05-30 diagnostic across all 376 un-cataloged active services found:

| Outcome | Count | What it means |
|---|---|---|
| **`pct-sufficient`** | **204 (54%)** | Save + render priced cost from PCT alone. **No catalog entry needed.** |
| `needs-catalog` | 90 (24%) | Save lints clean but renders $0 — the silent-trap class. Future catalog work. |
| `skip` (all-conditional) | 80 (21%) | PCT exposes no surfaceable fields; everything is `displayIf`-gated. Future catalog work. |
| `save-fail` | 2 (1%) | Save API refused; needs catalog or shape fix. |

The number to internalize: **more than half of un-cataloged services already work** because the agent reads the PCT, sends fields, the calculator prices them. The catalog earns its keep on the 30-40% subset where the PCT is silently misleading.

### What's been verified end-to-end

| | Verified | Unverified |
|---|---|---|
| Catalog entries render priced via DOM oracle | 15/15 (Step Functions was caught broken + fixed during this batch) | — |
| Static rehydration linter predicates work | 4/4 covered by ~120 unit tests | math/expression errors during recalculation |
| Tool descriptions trigger discovery-before-action | 5/5 LLM eval scenarios pass on Sonnet 4.5 (and Haiku 4.5) | actual production traffic effect (waiting on 7-day post-deploy data) |
| `redirect_to_parent` steers agents from `amazonS3` to `amazonS3Standard` | 1/1 LLM scenario passes | other deprecated parents (only `amazonS3` currently triggers the redirect) |
| Region-whitelist preflight rejects unsupported pairs | 396/436 services covered (~91%) | the 40 services absent from the whitelist endpoint (Bedrock et al.) skip validation |

### Three test surfaces, no overlap

- **`npm test`** (`test/`) — node:test suite, 322/327 pass with mocked I/O. Per-commit CI gate. Covers pure functions (validation, lint, surfaceability), payload construction, EC2 transforms, catalog schema.
- **`python3 eval/run.py`** (`eval/`) — 17 stdio + 5 LLM scenarios. Each scenario does a real save via the MCP server, then asserts `estimate_renders_cost` against the saved URL via `lib/dom-cost.js`. Run on demand (~1-2 min for stdio; ~$0.05 for LLM scenarios on Sonnet 4.5).
- **`npm run validate-catalog:cost`** (`scripts/validate-verified-catalog.js`) — sweeps verified catalog entries against the cost oracle. Catches stale URLs and pricing-engine drift. Run on a cadence (manual / cron / pre-deploy).

### The diagnostic

`scripts/diagnose-service.js` answers "would this service work without a catalog entry?" Useful when triaging future catalog work — runs against any subset of the manifest, classifies each service into the four buckets above. ~5-7s per service via Playwright DOM probe; ~10 min for the full manifest at concurrency 3. Output goes to `docs/diagnose/` (gitignored).

## Known Issues

- The CloudFront save/manifest APIs are undocumented and may change without notice.
- Callers must use the correct AWS field IDs — discover them via `get_service_fields`.
- While the tool discovers applicable selectorValues, it currently cannot resolve dependencies e.g. Instance Types <-> License 
- With the default `memory` store, estimates don't persist across restarts. Use `ESTIMATES_STORE=dynamodb` for stateless or multi-replica deployments.
- No local cost calculation — pricing is computed by AWS when viewing the shareable link -> Make sure to press `Update estimate` to reflect latest pricing.
- Only https://calculator.aws/ supported for now

## Security

This is sample code intended for educational purposes. You should work with your security and legal teams to meet your organizational security, regulatory, and compliance requirements before deployment.

### Security Model

This MCP server is a **local tool provider** — it runs as a child process of an MCP client and is not network-accessible. It has no authentication or authorization layer; access control is the responsibility of the MCP client that spawns it.

The server does not handle AWS credentials, customer data, or PII. It processes only pricing configuration parameters (e.g., region, instance type, request counts) provided by the MCP client.

These are the same public, unauthenticated endpoints used by the [calculator.aws](https://calculator.aws) website. No AWS credentials are transmitted.

### Input Validation and Sanitization

- All MCP tool inputs are validated using [Zod](https://zod.dev/) schemas before processing.
- User-provided descriptions and group names are sanitized to remove `<`, `>`, and `&` characters before inclusion in API payloads, preventing HTML/XML injection in the calculator frontend.
- Service configuration keys are validated against AWS service definitions with typo detection (Levenshtein distance), rejecting invalid field IDs before they reach the API.

### Data Handling

- Estimate data is held **in memory only** for the lifetime of the process. No data is written to disk or persisted across restarts.
- The data consists of pricing configuration (region codes, service parameters, instance types) — not secrets, credentials, or personally identifiable information.
- Shareable URLs generated by the export contain only an opaque estimate ID. The estimate content is stored by AWS, not by this server.

### Reporting Security Issues

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for information on reporting security issues.

## AWS MCP Servers Comparison: Pricing & Cost Management

| | **AWS Pricing Calculator MCP (This)** | **[AWS Billing & Cost Management MCP](https://github.com/awslabs/mcp#-cost--operations)** | **[AWS Pricing MCP](https://github.com/awslabs/mcp#-cost--operations)** |
|---|---|---|---|
| **Purpose** | Build shareable cost estimates for new workloads | Analyze historical spend & optimize existing costs | Query real-time pricing data from Price List API |
| **Data Source** | AWS Pricing Calculator (calculator.aws) | Cost Explorer, Cost Optimization Hub, Compute Optimizer, Savings Plans, Budgets, Storage Lens | AWS Price List Bulk API |
| **Output** | Shareable calculator.aws URL with full estimate | Natural language cost insights, savings recommendations | Raw pricing data, cost reports (markdown/CSV) |
| **Use Case** | "What will this new architecture cost?" | "Where am I overspending today?" | "What's the per-unit price of X?" |
| **Scope** | Forward-looking estimates | Historical & current spend | Current catalog pricing |
| **AWS Credentials** | Not required (uses public calculator API) | Required (reads your billing data) | Required (`pricing:*` permissions) |

TL;DR: Use the Pricing Calculator MCP to build estimates for proposals, the Billing & Cost Management MCP to analyze/optimize what you're already spending, and the Pricing MCP for granular unit-price lookups and IaC cost analysis.

## Trace events

When tracing is enabled (`TRACE=on`), the server emits structured JSON
lines on stderr, one per event, for every tool call and save operation.
Hosted deployments typically capture these via the runtime's log
pipeline; in stdio mode they appear on the process stderr directly.

**Tracing is off by default.** Set `TRACE=on` (or `1`/`true`/`yes`) to
enable. The default keeps stderr quiet for local CLI use and avoids
shipping diagnostic noise to production logs unless a deployment opts
in. The names below are also captured in the bundle contract
(`dist/bundle-contract.json`) so downstream consumers can discover the
contract programmatically.

Each line carries `ts` (ISO timestamp), `event` (one of the names below),
and an `mcpSessionId` field when the call was made over HTTP transport.

| Event | Payload fields | When emitted |
|---|---|---|
| `tool.call` | `name`, `args`, `mcpSessionId?` | Tool handler entry |
| `tool.result` | `name`, `isError`, `resultText` (≤500 chars), `resultLength` (pre-truncation), `durationMs`, `mcpSessionId?` | Tool handler exit (success or error) |
| `lint` | `verdict`, `services`, `estimateId?`, `mcpSessionId?` | `export_estimate` / `build_estimate`, after rehydration linter runs |
| `save.send` | `bytes`, `groupCount`, `serviceCount`, `estimateId?`, `mcpSessionId?` | Before POST to AWS save API |
| `save.ok` | `savedKey`, `estimateId?`, `mcpSessionId?` | Save API returned 200 |
| `save.fail` | `status`, `body` (≤500 chars), `estimateId?`, `mcpSessionId?` | Save API returned non-200 |
| `build_estimate.needs_grounding` | `estimateId`, `servicesToInspect`, `failureCount`, `mcpSessionId?` | `build_estimate` cold-call had unresolvable field IDs; agent gets a `needs_field_grounding` redirect |
| `get_service_fields.redirect_to_parent` | `serviceCode`, `redirectTo`, `childCodes`, `previewServiceCode?`, `mcpSessionId?` | Agent called `get_service_fields` for a deprecated parent shell (e.g. `amazonS3`); response routes them to the verified child code |
| `template_hint.unverified` | `serviceCode`, `templateId`, `estimateId`, `mcpSessionId?` | An `unverified` catalog entry's `templateId` was used as a hint — surfaces risky overrides for follow-up |

`tool.call` and `tool.result` are paired — sort by `ts` to reconstruct the
sequence. `save.*` events sit between them on `export_estimate` /
`build_estimate` calls.

`resultText` is truncated to keep log volume bounded; `resultLength` is
the original (pre-truncation) length, so a glance at a `tool.result` line
tells you whether the truncated text hid 50 chars or 50 KB. To see more
of the actual text in a specific run (e.g. when investigating a tool
whose response is being clipped at the wrong place), set
`TRACE_RESULT_TEXT_MAX=<N>` in the runtime environment — the cap is
re-read on every emit, so the change takes effect immediately. Default
is 500 chars; set it as high as you need for the investigation.

### Customer-text redaction

Trace events land in CloudWatch under an account-wide log group, so
anything written there is queryable by anyone with read access. To keep
agent-supplied free text out of those logs, the wrapper redacts values
at known-sensitive keys before emit:

- `name` — estimate names from `create_estimate` / `build_estimate`
- `description` — per-service free-text labels from `add_service` /
  `build_estimate` / `import_estimate`

Both fields are replaced with `[redacted: <N> chars]` in `tool.call`
args and `tool.result` resultText. Structure is preserved (you still see
"the agent set a description") but the content isn't. `resultLength`
reflects the original pre-redaction length. Non-sensitive fields —
service codes, region IDs, field IDs, numeric values, UUIDs — pass
through untouched and remain queryable.

If a future tool surface adds a new field that carries customer text,
extend `SENSITIVE_KEYS` in `lib/trace-logger.js`. The redactor walks
nested structures recursively, including the JSON-stringified `services`
arg of `add_service` / `build_estimate`.

The `mcpSessionId` field has three possible states, useful for telling
transports apart at a glance:

- HTTP request with an `mcp-session-id` header → `"mcpSessionId": "<uuid>"`.
- HTTP request without the header → `"mcpSessionId": null`.
- Stdio transport (no HTTP at all) → field is omitted entirely.

## Changelog

### [1.2.0] - 2026-05-30

**Catalog and validation work, with empirical receipts.**

- **Catalog grew 23 → 27 entries** (Lambda re-verified, ALB / Fargate / RDS PG bumped to verified, CloudTrail / Direct Connect / Transit Gateway / Step Functions newly authored). Each verified entry now requires a non-zero rendered cost in calculator.aws — the bar that exposed the prior "verified but renders $0" trap class (Lambda hid this for 2 weeks; Step Functions for 2 weeks via a `millionPerMonth` unit that lints clean but doesn't price).
- **Static rehydration linter** now rejects frequency/durationInput units not in the field's PCT options (the Step Functions trap, in code form). Region whitelist preflight rejects unsupported region/service pairs at `add_service` time.
- **`get_service_fields` redirect** for deprecated parent shells: agents calling with `amazonS3` get a `redirect_to_parent` envelope steering them to `amazonS3Standard` with the first child's fields preview-fetched inline.
- **`build_estimate` needs_grounding nudge**: cold-calls with unresolvable field IDs return an `isError: false` envelope pointing at `get_service_fields` rather than a hard error (production observed 0% recovery on `isError: true`).
- **Discovery-before-action** wired into tool descriptions; verified end-to-end on Sonnet 4.5 (production model) and Haiku 4.5 via 5 LLM eval scenarios. All five pass; multi-service messy prompts produce priced estimates without cold-call failures.
- **Eval harness** (`eval/`) — 17 stdio + 5 LLM scenarios, each asserting `assert_estimate_renders_cost` against the real saved URL via DOM scrape. Catches the silent-$0 regression class that lint + roundtrip miss.
- **DOM cost oracle** (`lib/dom-cost.js`) — Playwright probe that returns both rendered cost and the rehydrated Config Summary text. Used by the eval harness, the catalog sweep, and the diagnostic.
- **`scripts/validate-verified-catalog.js`** — sweeps verified catalog entries on a cadence, fails if any render < $0.01/mo. Found Step Functions broken on first run.
- **`scripts/diagnose-service.js`** — falsifiable test of catalog ceiling. Probes each un-cataloged service to classify as `pct-sufficient` / `needs-catalog` / `skip` / `save-fail`. Result: 54% of un-cataloged services price clean from PCT alone — they don't need catalog entries.
- **Architecture cleanup**: removed the CSV-export oracle stack, field-mapping survey runner, and BDD scaffolding now subsumed by `dom-cost.js` and the eval harness (~5600 lines). Refactored `mcp-server.js` from 689 → 367 lines by extracting `lib/handler-helpers.js` and `lib/tool-descriptions.js`.
- **Test count**: 322/327 pass after the cleanup (was 374/379 before; net −52 tests as deletions exceeded new tests). All eval scenarios pass.

Net branch effect: +7100 / −15000 lines.

### [1.1.0] - 2026-05-14
- Added optional HTTP transport (`MCP_TRANSPORT=http`) for hosted deployments (multi-replica HTTP, container runtimes). Defaults to stdio so existing MCP clients are unaffected.
- Fixed HTTP transport reconnection on persistent connections — calls `server.close()` between requests so the second tool call no longer fails with "Already connected to a transport" on long-lived containers.
- Added pluggable estimate store (`ESTIMATES_STORE` env var: `memory` default or `dynamodb`). Enables stateless deployments where requests may land on different processes. AWS SDK is an optional peer dependency, externalized at build time so the default bundle size is unchanged.
- Added `EstimateBuilder.toJSON()` / `EstimateBuilder.fromJSON()` for serialized round-trip through any store.
- Refactored validation helpers into `lib/validation.js` so unit tests exercise the shipping code instead of a copy.
- Added end-to-end roundtrip integration tests (build → save → fetch → field-by-field compare) for Lambda, grouped EC2, and the SNS subService write path.
- Test count grew from 70 to 95.

### [1.0.2] - 2026-05-13
- Added to npm https://www.npmjs.com/package/sample-aws-pricing-calculator-mcp
- Added quick install button (Kiro, Cursor, VS Code)

### [1.0.1] - 2026-05-13
- Fixed Bug: Proper support for nested Structures e.g. Elasticache, RDS, Bedrock, ALB
- Fixed Bug: EC2/EBS iops, throughput not recognized
- Enriched field metadata with allowed values, also validates upon submission - yet dependencies are not resolved
- Costs are now displayed on initial load - however pressing 'Update estimate' is recommended
- Supports importing/reading estimates
- Dependencies updated
- Removed dead code
- Version info added (get_server_info)

### [1.0.0] - 2026-04-30
- Initial Release

## License

This library is licensed under the MIT-0 License. See the [LICENSE](LICENSE) file.

## Disclaimer

Before using an MCP Server, you should consider conducting your own independent assessment to ensure that your use would comply with your own specific security and quality control practices and standards, as well as the laws, rules, and regulations that govern you and your content.