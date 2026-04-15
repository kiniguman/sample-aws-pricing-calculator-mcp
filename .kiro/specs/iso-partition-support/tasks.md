# Implementation Plan: ISO Partition Support

## Overview

Add AWS ISO (Top Secret) and ISO-B (Secret) partition support to the pricing calculator MCP server. Implementation proceeds bottom-up: partition config registry in `aws-client.js`, then per-partition caching, then `estimate-builder.js` changes (partition storage, auto-detection, share URLs, region map), then MCP server tool wiring, and finally integration validation.

## Tasks

- [x] 1. Add partition configuration registry and region resolver to `lib/aws-client.js`
  - [x] 1.1 Define the `PARTITIONS` config object with entries for `aws`, `aws-iso`, and `aws-iso-b`
    - Each entry contains `manifestPath`, `cdnPrefix`, `contract`, and `regions`
    - `aws`: manifestPath `/manifest/en_US.json`, cdnPrefix `''`, contract `null`
    - `aws-iso`: manifestPath `/aws-iso/manifest/en_US.json`, cdnPrefix `/aws-iso`, contract `'5423f8cd3b711c6f899ba4dade31b50c'`, regions `us-iso-east-1`, `us-iso-west-1`
    - `aws-iso-b`: manifestPath `/aws-iso-b/manifest/en_US.json`, cdnPrefix `/aws-iso-b`, contract `'5423f8cd3b711c6f899ba4dade31b50c'`, regions `us-isob-east-1`
    - Export `PARTITIONS` from the module
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

  - [x] 1.2 Implement `resolvePartition(region)` utility function
    - Return `'aws-iso'` if region starts with `us-iso-`
    - Return `'aws-iso-b'` if region starts with `us-isob-`
    - Return `'aws'` otherwise (including null/undefined input)
    - Export `resolvePartition` from the module
    - _Requirements: 8.1, 8.2_

  - [ ]* 1.3 Write property tests for partition config and region resolution
    - **Property 1: Partition config completeness** — for each partition in {aws, aws-iso, aws-iso-b}, verify config has non-empty `manifestPath`, string `cdnPrefix`, object `regions`, and a `contract` field
    - **Validates: Requirement 1.1**
    - **Property 6: Region-to-partition resolution** — generate region strings with prefixes `us-iso-*`, `us-isob-*`, `us-east-*`, and random strings; verify `resolvePartition` returns the correct partition
    - **Validates: Requirements 8.1, 8.2**

- [x] 2. Implement per-partition manifest loading and definition fetching in `lib/aws-client.js`
  - [x] 2.1 Refactor `loadManifest()` to accept an optional `partition` parameter (default `'aws'`)
    - Replace singleton `manifestPromise` with a `Map<partition, Promise>` (`manifestCache`)
    - Construct manifest URL as `CDN_BASE + PARTITIONS[partition].manifestPath`
    - On failure, clear only that partition's cache entry to allow retry
    - Validate partition ID; throw if unknown
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 2.2 Refactor `fetchServiceDefinition()` to accept an optional `partition` parameter (default `'aws'`)
    - Change cache key from `serviceCode` to `partition:serviceCode`
    - Prepend `PARTITIONS[partition].cdnPrefix` to the service definition URL path
    - _Requirements: 3.1, 3.2, 3.3_

  - [ ]* 2.3 Write property tests for manifest URL construction and cache isolation
    - **Property 2: Manifest URL construction** — for each partition, verify the constructed URL equals `CDN_BASE + PARTITIONS[partition].manifestPath`
    - **Validates: Requirement 2.1**
    - **Property 3: Service definition URL construction** — for generated (partition, urlPath) pairs, verify URL equals `CDN_BASE + PARTITIONS[partition].cdnPrefix + urlPath`
    - **Validates: Requirement 3.1**
    - **Property 4: Per-partition cache isolation** — for pairs of distinct partitions, verify loading a resource for one does not affect the other's cache
    - **Validates: Requirements 2.2, 3.2**

- [x] 3. Checkpoint
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Update `lib/estimate-builder.js` for partition support
  - [x] 4.1 Extend the `REGIONS` map with ISO and ISO-B regions
    - Add `'us-iso-east-1': 'US ISO East'`
    - Add `'us-iso-west-1': 'US ISO West'`
    - Add `'us-isob-east-1': 'US ISOB East (Ohio)'`
    - _Requirements: 6.1, 6.2, 6.3_

  - [x] 4.2 Add partition support to the `EstimateBuilder` constructor and internal methods
    - Accept optional `partition` parameter in constructor, store as `this.partition`
    - Implement `_resolvePartition()`: returns explicit partition if set, otherwise infers from service regions using `resolvePartition()`, defaults to `'aws'`
    - Implement `_validatePartitionConsistency()`: collects partitions from all service regions, throws error if more than one distinct partition is found
    - _Requirements: 5.1, 5.2, 5.3, 8.1, 8.2, 8.3_

  - [x] 4.3 Update `toAWSPayload()` to use partition-aware manifest and definition loading
    - Call `loadManifest(partition)` instead of `loadManifest()`
    - Pass `partition` to `fetchServiceDefinition()` calls
    - Call `_validatePartitionConsistency()` before building payload
    - _Requirements: 5.2, 8.3_

  - [x] 4.4 Implement `_buildShareUrl()` and update `export()` to construct partition-aware share URLs
    - Move share URL construction from `saveEstimate` return value to `EstimateBuilder`
    - For `aws` partition: `https://calculator.aws/#/estimate?id={savedKey}`
    - For `aws-iso` / `aws-iso-b`: `https://calculator.aws/#/?ctrct={contract}#/estimate?id={savedKey}`
    - Update `export()` to call `_buildShareUrl()` with the resolved partition
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [ ]* 4.5 Write property tests for share URL and mixed-partition validation
    - **Property 5: Share URL contract parameter correctness** — for generated (savedKey, partition) pairs, verify URL includes `ctrct` param iff partition has non-null contract, and the contract value matches
    - **Validates: Requirements 7.1, 7.2, 7.3**
    - **Property 7: Mixed-partition rejection** — generate sets of regions spanning multiple partitions, verify `_validatePartitionConsistency()` throws an error
    - **Validates: Requirement 8.3**

  - [ ]* 4.6 Write unit tests for EstimateBuilder partition features
    - Test constructor stores partition correctly
    - Test `_resolvePartition()` returns explicit partition, auto-detected partition, and default `'aws'`
    - Test `_validatePartitionConsistency()` passes for same-partition regions and throws for mixed
    - Test `_buildShareUrl()` produces correct URLs for each partition
    - Test REGIONS map contains all three ISO/ISO-B entries with correct display names
    - _Requirements: 5.1, 5.3, 6.1, 6.2, 6.3, 8.1, 8.2, 8.3_

- [x] 5. Checkpoint
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Wire partition parameter into MCP server tools in `mcp-server.js`
  - [x] 6.1 Add optional `partition` parameter to `search_services` tool
    - Accept `partition` as optional zod string parameter
    - Validate partition value against known partition IDs
    - Pass partition to `loadManifest(partition)`
    - _Requirements: 4.1, 4.2_

  - [x] 6.2 Add optional `partition` parameter to `get_service_fields` tool
    - Pass partition to `loadManifest(partition)` and `fetchServiceDefinition(..., partition)`
    - _Requirements: 4.3_

  - [x] 6.3 Add optional `partition` parameter to `create_estimate` tool
    - Pass partition to `EstimateBuilder` constructor
    - _Requirements: 5.1_

  - [ ]* 6.4 Write unit tests for MCP server partition wiring
    - Test `search_services` without partition defaults to `aws` manifest
    - Test `create_estimate` with partition stores it on the builder
    - Test unknown partition returns an error response
    - _Requirements: 4.1, 4.2, 5.1, 9.1_

- [x] 7. Backward compatibility verification
  - [x] 7.1 Verify existing tests pass without modification
    - Run full test suite; all existing tests in `test/aws-client.test.js`, `test/ec2.test.js`, and `test/estimate-builder.test.js` must continue to pass
    - No existing function signatures should break when called without the new `partition` parameter
    - _Requirements: 9.1, 9.2, 9.3_

- [x] 8. Final checkpoint
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- The project uses Node.js built-in `node:test` for testing — property tests should use a loop-based approach or `fast-check` as a dev dependency
- All partition logic defaults to `'aws'` when no partition is specified, preserving backward compatibility
- Share URL construction moves from `saveEstimate()` in aws-client to `EstimateBuilder.export()` so the builder controls the URL format based on partition
