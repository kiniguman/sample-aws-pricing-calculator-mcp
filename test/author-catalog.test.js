// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * Tests for scripts/author-catalog.js — the deterministic spine of the
 * author-catalog-entry skill.
 *
 * Strategy: spawn the script as a child process and parse its stdout
 * JSON. This mirrors how the skill calls it (via Bash) and avoids
 * coupling the tests to internal helpers that may move.
 *
 * SKIP_NETWORK gate: subcommands that touch the manifest/PCT (resolve,
 * generate, pad) need a network. The status subcommand is filesystem-
 * only and runs unconditionally.
 */

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');

const SCRIPT = path.join(__dirname, '..', 'scripts', 'author-catalog.js');
const SKIP_NETWORK = process.env.SKIP_NETWORK === '1';

function runScript(args) {
  // stdio: ignore stdin, capture stdout, redirect stderr to /dev/null so
  // status messages from aws-client (e.g. "Loaded N services from manifest")
  // don't pollute the assertion. The script's contract is JSON-only stdout.
  const out = execFileSync('node', [SCRIPT, ...args], {
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  return JSON.parse(out);
}

describe('author-catalog.js status (filesystem-only)', () => {
  it('reports exists:true with shape fields for an authored entry', () => {
    // aWSLambda is always present in the catalog; whether it's
    // verified/partial/unverified shifts as the catalog evolves and
    // re-verifications happen. The test exercises the script's
    // reporting shape, not the entry's current status value.
    const r = runScript(['status', 'aWSLambda']);
    assert.equal(r.ok, true);
    assert.equal(r.data.exists, true);
    assert.ok(['verified', 'partial', 'unverified', 'broken'].includes(r.data.status),
      `expected a known status enum, got ${r.data.status}`);
    assert.ok(r.data.minimal_config_keys.includes('region'));
    assert.ok(r.data.required_count >= 1);
  });

  it('reports exists:false for a service without a catalog file', () => {
    const r = runScript(['status', 'definitelyNotInCatalog9876']);
    assert.equal(r.ok, true);
    assert.equal(r.data.exists, false);
    assert.match(r.data.hint, /generate/);
  });

  it('surfaces sub_service_codes for parent envelopes', () => {
    const r = runScript(['status', 'amazonSimpleStorageServiceGroup']);
    assert.equal(r.data.exists, true);
    assert.ok(r.data.sub_service_codes.length > 0,
      'parent envelopes should report their child serviceCodes');
  });
});

describe('author-catalog.js resolve (network)', () => {
  if (SKIP_NETWORK) {
    it.skip('SKIP_NETWORK=1; not running', () => {});
    return;
  }

  it('confirms in_manifest for known service', () => {
    const r = runScript(['resolve', 'aWSLambda']);
    assert.equal(r.ok, true);
    assert.equal(r.data.in_manifest, true);
    assert.equal(r.data.manifest_name, 'AWS Lambda');
  });

  it('returns alternatives when service is not in manifest', () => {
    const r = runScript(['resolve', 'thisServiceCodeDoesNotExist']);
    assert.equal(r.ok, false);
    assert.match(r.error, /not in.*manifest/);
    assert.ok(Array.isArray(r.data.alternatives));
  });
});

describe('author-catalog.js pad (network)', () => {
  if (SKIP_NETWORK) {
    it.skip('SKIP_NETWORK=1; not running', () => {});
    return;
  }

  it('reports nothing-to-do for an already-padded entry', () => {
    // aWSLambda's catalog has both surfaceable fields already.
    const r = runScript(['pad', 'aWSLambda']);
    assert.equal(r.ok, true);
    assert.equal(r.data.suggestions.length, 0);
    assert.equal(r.data.applied, false);
  });

  it('targets the active child for sub-service-selector parents', () => {
    // S3's parent envelope's minimalConfig is keyed by amazonS3Standard;
    // pad should report its target_path scoped to that child.
    const r = runScript(['pad', 'amazonSimpleStorageServiceGroup']);
    assert.equal(r.ok, true);
    assert.match(r.data.target_path, /amazonS3Standard/,
      'sub-service-selector parents should pad the active child, not the top-level');
  });
});

describe('author-catalog.js preflight (network)', () => {
  if (SKIP_NETWORK) {
    it.skip('SKIP_NETWORK=1; not running', () => {});
    return;
  }

  it('reports editable verdict for a known-good entry', () => {
    const r = runScript(['preflight', 'aWSLambda']);
    assert.equal(r.ok, true);
    assert.equal(r.data.lint_verdict, 'editable');
    assert.equal(r.data.schema_valid, true);
  });

  it('handles sub-service-selector parents (S3 group)', () => {
    const r = runScript(['preflight', 'amazonSimpleStorageServiceGroup']);
    assert.equal(r.ok, true);
    assert.equal(r.data.lint_verdict, 'editable');
  });
});

describe('author-catalog.js preflight schema errors (filesystem-only)', () => {
  // Exercise the schema-error short-circuit by writing a deliberately
  // invalid catalog file to a sandbox path, then running preflight.
  // Skips the network entirely because the schema check fails first.
  it('rejects schema-invalid entries before lint runs', () => {
    const fixture = path.join(__dirname, '..', 'catalog', 'services', '_test_schema_invalid.json');
    fs.writeFileSync(fixture, JSON.stringify({
      // missing required fields per catalog/schema.json
      $schema: '../schema.json',
      serviceCode: '_test_schema_invalid',
      // displayName, status, minimalConfig all missing
    }));
    try {
      const r = runScript(['preflight', '_test_schema_invalid']);
      assert.equal(r.ok, false);
      assert.match(r.error, /Schema validation failed/);
      assert.ok(Array.isArray(r.data.schema_errors));
      assert.ok(r.data.schema_errors.length > 0);
    } finally {
      fs.unlinkSync(fixture);
    }
  });
});

describe('author-catalog.js verify (filesystem-only, structural gate)', () => {
  // Fixture catalog file used across tests. Schema-valid name ([a-zA-Z][a-zA-Z0-9]*).
  const FIXTURE_CODE = 'zztestVerifyGate';
  const FIXTURE_PATH = path.join(__dirname, '..', 'catalog', 'services', `${FIXTURE_CODE}.json`);

  function writeFixture(overrides = {}) {
    fs.writeFileSync(FIXTURE_PATH, JSON.stringify({
      $schema: '../schema.json',
      serviceCode: FIXTURE_CODE,
      displayName: 'Verify gate test',
      templateId: 'template',
      status: 'unverified',
      required: [],
      optional: [],
      traps: [],
      subServices: [],
      minimalConfig: { region: 'us-east-1', description: 'test' },
      ...overrides,
    }, null, 2) + '\n');
  }
  function cleanup() {
    if (fs.existsSync(FIXTURE_PATH)) fs.unlinkSync(FIXTURE_PATH);
  }

  it('refuses without --browser-confirmed', () => {
    writeFixture();
    try {
      const r = runScript(['verify', FIXTURE_CODE]);
      assert.equal(r.ok, false);
      assert.match(r.error, /yes-all-four/);
      // File must NOT have been modified.
      const after = JSON.parse(fs.readFileSync(FIXTURE_PATH, 'utf8'));
      assert.equal(after.status, 'unverified', 'status must not change on refusal');
    } finally { cleanup(); }
  });

  it('refuses with wrong --browser-confirmed value', () => {
    writeFixture();
    try {
      const r = runScript(['verify', FIXTURE_CODE, '--browser-confirmed', 'yes',
        '--estimate-id', '0000000000000000000000000000000000000000']);
      assert.equal(r.ok, false);
      assert.match(r.error, /yes-all-four/);
    } finally { cleanup(); }
  });

  it('refuses without --estimate-id', () => {
    writeFixture();
    try {
      const r = runScript(['verify', FIXTURE_CODE, '--browser-confirmed', 'yes-all-four']);
      assert.equal(r.ok, false);
      assert.match(r.error, /estimate-id/);
    } finally { cleanup(); }
  });

  it('refuses with non-SHA1 estimate id', () => {
    writeFixture();
    try {
      const r = runScript(['verify', FIXTURE_CODE,
        '--browser-confirmed', 'yes-all-four',
        '--estimate-id', 'not-a-real-sha']);
      assert.equal(r.ok, false);
      assert.match(r.error, /40-hex-sha1/);
    } finally { cleanup(); }
  });

  it('writes verified status only when both flags valid', () => {
    writeFixture();
    try {
      const r = runScript(['verify', FIXTURE_CODE,
        '--browser-confirmed', 'yes-all-four',
        '--estimate-id', '1234567890abcdef1234567890abcdef12345678']);
      assert.equal(r.ok, true);
      assert.equal(r.data.new_status, 'verified');
      assert.match(r.data.lastVerifiedAt, /^\d{4}-\d{2}-\d{2}$/);
      const after = JSON.parse(fs.readFileSync(FIXTURE_PATH, 'utf8'));
      assert.equal(after.status, 'verified');
      assert.equal(after.verifiedEstimateId, '1234567890abcdef1234567890abcdef12345678');
    } finally { cleanup(); }
  });

  it('returns error JSON when entry does not exist', () => {
    cleanup();
    const r = runScript(['verify', 'definitelyNotInCatalog9876',
      '--browser-confirmed', 'yes-all-four',
      '--estimate-id', '1234567890abcdef1234567890abcdef12345678']);
    assert.equal(r.ok, false);
    assert.match(r.error, /No catalog entry/);
  });
});

describe('author-catalog.js usage errors', () => {
  it('exits 2 on unknown subcommand', () => {
    let exitCode = 0;
    try {
      execFileSync('node', [SCRIPT, 'nonsense', 'aWSLambda'], { stdio: ['ignore', 'ignore', 'ignore'] });
    } catch (err) {
      exitCode = err.status;
    }
    assert.equal(exitCode, 2, 'unknown subcommand should exit 2');
  });

  it('exits 2 when serviceCode is missing', () => {
    let exitCode = 0;
    try {
      execFileSync('node', [SCRIPT, 'status'], { stdio: ['ignore', 'ignore', 'ignore'] });
    } catch (err) {
      exitCode = err.status;
    }
    assert.equal(exitCode, 2);
  });
});
