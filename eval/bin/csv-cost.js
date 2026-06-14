#!/usr/bin/env node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

// Thin bridge: drive lib/dom-cost.js for one URL, print
// {monthlyCost, monthlyByService} to stdout as JSON. Used by the
// Python eval harness's csv_oracle.py.
//
// DOM scraping replaced the CSV download path on 2026-05-29 because
// the calculator's CSV is generated client-side from in-memory state
// (there's no server-side endpoint), so we always need a browser
// open — but we don't need the Export-button → menu → modal →
// download dance. The cost numbers render directly into the page
// DOM in a stable order (Estimate summary block: Upfront, Monthly,
// 12-month total). Skipping the export flow saves ~7s per scenario.
//
// Errors go to stderr (so the parent's JSON parse stays clean) and
// exit non-zero so the parent can detect failure.
//
// usage:  node eval/bin/csv-cost.js <url>

const path = require('node:path');
const { fetchCostFromDOM } = require(
  path.join(__dirname, '..', '..', 'lib', 'dom-cost'),
);

async function main() {
  const url = process.argv[2];
  if (!url) {
    console.error('usage: csv-cost.js <calculator.aws estimate URL>');
    process.exit(2);
  }
  const r = await fetchCostFromDOM(url);
  process.stdout.write(JSON.stringify({
    monthlyCost: r.monthlyCost,
    monthlyByService: [...r.monthlyByService],
    configByService: r.configByService ? [...r.configByService] : [],
  }) + '\n');
}

main().catch(err => {
  console.error(err.stack || err.message || String(err));
  process.exit(1);
});
