// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * Long-form description strings for the 9 MCP tools. Pulled out of
 * mcp-server.js so the entry point reads as schema + handler binding
 * rather than walls of agent-facing prose.
 *
 * These descriptions ship to clients via tools/list and shape agent
 * behavior — they're the contract surface of the MCP server. Edit
 * with that in mind: a sloppy paragraph here propagates to every agent
 * that connects.
 */

'use strict';

exports.GET_SERVER_INFO =
  'Get version and capability information about this MCP server.';

exports.SEARCH_SERVICES =
  'Search AWS services available in the calculator. Returns service keys ' +
  'and names. Use this to find the correct service key before adding it ' +
  'to an estimate. Supports multiple comma-separated search terms in a ' +
  'single call (e.g. "Lambda, S3, API Gateway, CloudWatch").';

exports.GET_SERVICE_FIELDS =
  'Get the input fields for one or more AWS services. Returns field IDs, ' +
  'types, labels, and valid options. Use this to discover what configuration ' +
  'a service accepts before adding it to an estimate. The field IDs returned ' +
  'here are the exact keys to use in add_service config. Accepts multiple ' +
  'comma-separated service keys. IMPORTANT: When duplicate fields exist with ' +
  'version suffixes (e.g. fieldName and fieldName_v2), ALWAYS use the highest ' +
  'version — it maps to the latest configuration path. Ignore lower versions. ' +
  'For curated services (status: verified or partial), the response also ' +
  'includes a `catalog` object with a known-working `minimalConfig`, required ' +
  'field hints with examples, and `traps[]` listing service-specific gotchas. ' +
  'Prefer using `minimalConfig` as a starting point for `add_service`. If the ' +
  'response carries `status: "redirect_to_parent"`, the service code you passed ' +
  'is a deprecated parent envelope — re-call get_service_fields with one of ' +
  'the codes in `child_service_codes` and use that instead.';

exports.CREATE_ESTIMATE =
  'Create a new empty estimate. Returns an estimate ID to use with ' +
  'add_service and export_estimate.';

exports.ADD_SERVICE =
  `Add one or more AWS services to an estimate. Accepts a single service or a JSON array of services in the "services" parameter.

Field values follow these patterns based on field type:
- numericInput: plain string value, e.g. "1000"
- frequency: object with value and unit, e.g. {"value": "19", "unit": "millionPerMonth"}
- fileSize: object with value and unit. The unit format is "{size}|{frequency}" where size comes from the field's validSizes (gb, tb, mb, etc.) and frequency is usually "NA". Check the field's defaultUnit from get_service_fields. Examples: {"value": "512", "unit": "mb|NA"}, {"value": "1", "unit": "tb|NA"}, {"value": "10", "unit": "gb|NA"}, {"value": "8", "unit": "gb|month"}
- dropdown: string matching one of the option IDs from get_service_fields
- durationInput: object with value and unit, e.g. {"value": "960", "unit": "min"}

CRITICAL — DISCOVERY BEFORE ACTION: For any service you have not already inspected with get_service_fields THIS SESSION, call get_service_fields FIRST. The calculator's pricing engine silently requires fields the PCT does not mark required (e.g. AWS Lambda needs sizeOfMemoryAllocated, storageAmountEphemeral, and architecture toggles to compute non-zero cost). Sending a partial config saves cleanly but renders $0 in the rehydrated estimate. The get_service_fields response includes a "catalog" block for curated services — its minimalConfig is a known-good baseline; its traps[] document gotchas; its required[] lists what the pricing engine actually demands. Always start from minimalConfig and modify, rather than constructing a config from training priors.

IMPORTANT: Before calling this tool, you MUST confirm the desired AWS region with the user if they haven't already specified one. Do NOT assume a default region. Always include "region" in each service config. Use "description" to label what each service entry represents. IMPORTANT: descriptions and group names must NOT contain <, >, or & characters (AWS rejects them).

Config keys are validated against the service definition. Invalid field IDs will be rejected with suggested corrections.

For batch mode, pass a JSON array in "services":
[{"service":"aWSLambda","instance":"Compute","group":"Prod","config":{...}},{"service":"amazonS3Standard","group":"Prod","config":{...}}]

For multi-service estimates, prefer build_estimate over create_estimate + add_service + export_estimate — but only AFTER you have called get_service_fields for each service. build_estimate does not skip the discovery requirement.

RETRY SEMANTICS: add_service ALWAYS APPENDS — it never replaces an existing entry. If a previous attempt already added a service to this estimate (e.g. you are rebuilding after a validation issue, or the user reported a problem with an earlier save), DO NOT call add_service again on the same estimate_id with the same configuration; that produces a duplicate row and inflates the cost. Instead, call create_estimate to start fresh, then add the corrected services. As a defense, the response surfaces an "existing_entry" field when (service, description) already matches a stored entry — if you see that field, you are about to create a duplicate; back out and use create_estimate.`;

exports.VALIDATE_ESTIMATE =
  'Dry-run preflight: builds the would-be saved payload and runs the static ' +
  'rehydration linter — WITHOUT calling the AWS save API. Use this to confirm ' +
  'an estimate would lint editable before paying the save round-trip. Returns ' +
  '{lint_verdict, next_step, lint_services, would_be_payload}. Inverse of ' +
  'export_estimate; use that one when you want the URL.';

exports.EXPORT_ESTIMATE =
  'Export an estimate to calculator.aws and get a shareable URL. The link ' +
  'will show the full estimate with AWS-calculated pricing. Before saving, ' +
  'runs a static rehydration linter against the payload. If the lint predicts ' +
  'the saved estimate would render as read-only (frozen, uneditable), the ' +
  'export is refused with a description of which predicate failed.';

exports.BUILD_ESTIMATE =
  `One-shot: create an estimate, add services, lint-preflight, save, and return the calculator URL. Replaces three separate calls (create_estimate + add_service + export_estimate). Returns {sharable_url, aws_estimate_id, services} on success.

CRITICAL — DISCOVERY BEFORE ACTION: For any service you have not already inspected with get_service_fields THIS SESSION, call get_service_fields FIRST. The calculator's pricing engine silently requires fields the PCT does not mark required; sending a partial config saves cleanly but renders $0 in the rehydrated estimate. Curated services include a "catalog" block in get_service_fields with a minimalConfig that is a known-good starting point — base your config on it rather than guessing field IDs from training priors.

If any service fails validation, returns a structured needs_field_grounding redirect pointing you at get_service_fields for the affected services (isError:false; not a hard failure — call get_service_fields and retry). If the saved blob would rehydrate as read-only, returns the per-service lint detail with no save attempt.

The estimate is kept in the in-memory store, so the returned aws_estimate_id can be passed to add_service/export_estimate to extend it.`;

exports.IMPORT_ESTIMATE =
  'Download an existing AWS Pricing Calculator estimate by URL or ID. ' +
  'Returns the estimate in JSON (raw, for modifications like region swaps) ' +
  'or Markdown (for LLM consumption, summaries, funding recommendations).';
