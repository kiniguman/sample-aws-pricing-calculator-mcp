# Requirements Document

## Introduction

The AWS Pricing Calculator MCP server currently only supports the commercial AWS partition (and GovCloud regions within it). This feature adds support for the AWS ISO (Top Secret) and ISO-B (Secret) partitions, enabling users to create pricing estimates targeting isolated partition regions (`us-iso-east-1`, `us-iso-west-1`, `us-isob-east-1`). Each partition uses a distinct manifest, service definition CDN path, and contract-based share URL format.

## Glossary

- **MCP_Server**: The Model Context Protocol server that exposes calculator tools (search_services, get_service_fields, create_estimate, add_service, export_estimate)
- **Partition**: An isolated AWS infrastructure domain. Supported values: `aws` (commercial, default), `aws-iso` (Top Secret), `aws-iso-b` (Secret)
- **Manifest**: A JSON index of all available services for a given partition, fetched from a partition-specific URL
- **Service_Definition**: A JSON document describing a service's input fields, templates, and pricing configuration, fetched from a partition-specific CDN path
- **Estimate_Builder**: The internal class that assembles service configurations into an AWS-compatible estimate payload
- **AWS_Client**: The internal module responsible for fetching manifests, service definitions, and saving estimates to the AWS API
- **Share_URL**: The URL returned after exporting an estimate, which opens the estimate in the calculator.aws web UI
- **Contract_Parameter**: A query parameter (`ctrct`) appended to share URLs for non-commercial partitions, required by the contract-based calculator UI
- **CDN_Base**: The base URL (`https://d1qsjq9pzbk1k6.cloudfront.net`) used to fetch manifests and service definitions
- **Region**: An AWS region identifier (e.g., `us-east-1`, `us-iso-east-1`) that determines which partition a service configuration targets
- **REGIONS_Map**: The internal mapping of region identifiers to human-readable region names used in estimate payloads

## Requirements

### Requirement 1: Partition Configuration Registry

**User Story:** As a developer, I want a centralized partition configuration, so that partition-specific URLs, regions, and parameters are defined in one place and easy to maintain.

#### Acceptance Criteria

1. THE AWS_Client SHALL define a partition configuration mapping that associates each Partition identifier (`aws`, `aws-iso`, `aws-iso-b`) with its manifest URL path, service definition CDN path prefix, available regions, and Contract_Parameter value
2. WHEN the Partition is `aws`, THE AWS_Client SHALL use the manifest path `/manifest/en_US.json` and no CDN path prefix
3. WHEN the Partition is `aws-iso`, THE AWS_Client SHALL use the manifest path `/aws-iso/manifest/en_US.json` and the CDN path prefix `/aws-iso`
4. WHEN the Partition is `aws-iso-b`, THE AWS_Client SHALL use the manifest path `/aws-iso-b/manifest/en_US.json` and the CDN path prefix `/aws-iso-b`

### Requirement 2: Partition-Aware Manifest Loading

**User Story:** As a developer, I want the manifest loader to fetch the correct manifest for each partition, so that service searches return partition-appropriate results.

#### Acceptance Criteria

1. WHEN a manifest is requested for a specific Partition, THE AWS_Client SHALL fetch the manifest from the CDN_Base combined with that Partition's manifest URL path
2. THE AWS_Client SHALL cache manifests independently per Partition, so that loading the `aws-iso` manifest does not overwrite the cached `aws` manifest
3. IF the manifest fetch fails, THEN THE AWS_Client SHALL allow retry on subsequent calls for that Partition
4. WHEN no Partition is specified, THE AWS_Client SHALL default to the `aws` Partition

### Requirement 3: Partition-Aware Service Definition Fetching

**User Story:** As a developer, I want service definitions to be fetched from the correct partition-specific CDN path, so that pricing data matches the target partition.

#### Acceptance Criteria

1. WHEN a service definition is fetched for a Partition with a CDN path prefix, THE AWS_Client SHALL prepend that prefix to the service definition URL path
2. THE AWS_Client SHALL cache service definitions independently per Partition, so that the same service code in different partitions resolves to different cached entries
3. WHEN no Partition is specified, THE AWS_Client SHALL fetch service definitions from the default `aws` CDN path (no prefix)

### Requirement 4: Partition-Aware Service Search

**User Story:** As a user, I want to search for services available in ISO and ISO-B partitions, so that I can discover which services are available before adding them to an estimate.

#### Acceptance Criteria

1. WHEN the search_services tool is called with a `partition` parameter, THE MCP_Server SHALL load the manifest for that Partition and search within it
2. WHEN the search_services tool is called without a `partition` parameter, THE MCP_Server SHALL search the default `aws` manifest
3. WHEN the get_service_fields tool is called with a `partition` parameter, THE MCP_Server SHALL fetch the service definition from that Partition's CDN path

### Requirement 5: Partition-Aware Estimate Creation

**User Story:** As a user, I want to create estimates that target ISO or ISO-B partitions, so that I can get pricing for services in those environments.

#### Acceptance Criteria

1. WHEN the create_estimate tool is called with a `partition` parameter, THE MCP_Server SHALL store the Partition on the Estimate_Builder instance
2. WHEN the Estimate_Builder builds a payload, THE Estimate_Builder SHALL use the stored Partition to load the correct manifest and fetch partition-specific service definitions
3. WHEN no `partition` is specified on create_estimate, THE Estimate_Builder SHALL default to the `aws` Partition

### Requirement 6: ISO and ISO-B Region Support

**User Story:** As a user, I want to specify ISO and ISO-B regions in service configurations, so that estimates reflect the correct region names and pricing.

#### Acceptance Criteria

1. THE REGIONS_Map SHALL include the region `us-iso-east-1` with the display name `US ISO East`
2. THE REGIONS_Map SHALL include the region `us-iso-west-1` with the display name `US ISO West`
3. THE REGIONS_Map SHALL include the region `us-isob-east-1` with the display name `US ISOB East (Ohio)`

### Requirement 7: Partition-Aware Estimate Export and Share URL

**User Story:** As a user, I want exported estimates for ISO partitions to produce share URLs that open correctly in the contract-based calculator, so that I can share estimates with colleagues.

#### Acceptance Criteria

1. WHEN an estimate for the `aws` Partition is exported, THE Estimate_Builder SHALL produce a Share_URL in the format `https://calculator.aws/#/estimate?id={savedKey}`
2. WHEN an estimate for the `aws-iso` Partition is exported, THE Estimate_Builder SHALL produce a Share_URL that includes the Contract_Parameter for `aws-iso`
3. WHEN an estimate for the `aws-iso-b` Partition is exported, THE Estimate_Builder SHALL produce a Share_URL that includes the Contract_Parameter for `aws-iso-b`
4. THE AWS_Client SHALL use the same save API endpoint for all partitions

### Requirement 8: Partition Auto-Detection from Region

**User Story:** As a user, I want the system to infer the correct partition from the region I specify, so that I do not need to manually set the partition when it can be determined from context.

#### Acceptance Criteria

1. WHEN a region starting with `us-iso-` is provided in a service configuration and no explicit Partition is set on the estimate, THE Estimate_Builder SHALL treat the estimate as targeting the `aws-iso` Partition
2. WHEN a region starting with `us-isob-` is provided in a service configuration and no explicit Partition is set on the estimate, THE Estimate_Builder SHALL treat the estimate as targeting the `aws-iso-b` Partition
3. IF services in a single estimate reference regions from different partitions, THEN THE MCP_Server SHALL return an error indicating that mixed-partition estimates are not supported

### Requirement 9: Backward Compatibility

**User Story:** As an existing user, I want the calculator to continue working exactly as before when I do not use ISO features, so that no existing workflows break.

#### Acceptance Criteria

1. WHEN no `partition` parameter is provided to any tool, THE MCP_Server SHALL behave identically to the current implementation
2. THE AWS_Client SHALL continue to use the existing manifest URL for the `aws` Partition
3. THE Estimate_Builder SHALL continue to produce the existing Share_URL format for `aws` Partition estimates
