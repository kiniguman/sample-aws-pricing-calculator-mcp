// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * Convenience wrapper around lib/can-rehydrate. Loads the manifest,
 * fetches every per-service definition referenced by the saved blob
 * (parent + sub-service children), and runs canRehydrate.
 *
 * Network-touching — kept separate from lib/can-rehydrate.js so the
 * pure linter's tests can stay offline.
 */

const { canRehydrate } = require('./can-rehydrate');

function collectServiceCodes(savedBlob) {
  const codes = new Set();
  const services = Object.values(savedBlob.services || {});
  for (const group of Object.values(savedBlob.groups || {})) {
    services.push(...Object.values(group.services || {}));
  }
  for (const svc of services) {
    if (svc.serviceCode) codes.add(svc.serviceCode);
    for (const child of (svc.subServices || [])) {
      if (child.serviceCode) codes.add(child.serviceCode);
    }
  }
  return codes;
}

async function canRehydrateFetch({ savedBlob, partition = 'aws', catalog } = {}) {
  if (!savedBlob || typeof savedBlob !== 'object') {
    throw new TypeError('canRehydrateFetch requires a savedBlob object');
  }
  // Lazy-require to allow test-time module replacement via require.cache.
  const awsClient = require('./aws-client');
  const manifest = await awsClient.loadManifest(partition);
  const codes = collectServiceCodes(savedBlob);
  const perServiceDefinitions = new Map();
  for (const code of codes) {
    // fetchServiceDefinition throws on HTTP non-200 (and on non-manifest
    // codes). Per-code try/catch so one bad service doesn't abort the
    // whole lint — the linter then surfaces it as 'unknown' (definition
    // unavailable) rather than crashing.
    try {
      const def = await awsClient.fetchServiceDefinition(manifest, code, partition);
      if (def) perServiceDefinitions.set(code, def);
    } catch {
      // Leave the code out of the map — canRehydrate will report
      // status: 'unknown' for it.
    }
  }
  // Region list is best-effort — partition-specific. Skipping when
  // unreachable matches validation.js's preflight behavior, so the
  // lint matches the add-time check.
  let regionList = null;
  try {
    regionList = await awsClient.loadRegionList(partition);
  } catch {
    // unreachable — proceed without; checkInvalidRegion is a no-op.
  }
  return canRehydrate({ savedBlob, manifest, perServiceDefinitions, catalog, regionList });
}

module.exports = { canRehydrateFetch, collectServiceCodes };
