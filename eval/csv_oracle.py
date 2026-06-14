# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Bridge from the Python eval harness to the existing Node CSV oracle
in validation/csv-export.js. Calls Node, gives it a saved-estimate
URL, returns parsed cost data.

Why a subprocess: validation/csv-export.js owns the Playwright
selectors, the polling logic for the rehydrate-disabled-Export-button
case, and the CSV parser. Reimplementing that in Python (or porting
to a separate Python+Playwright stack) would duplicate hard-won
behavior. The subprocess hop is one-shot per scenario, takes ~10s,
and reuses ground-truth code without modification.

The shell script `bin/csv-cost.js` (written next to this file) is
the thin Node entrypoint — it just requires csv-export.js, calls
downloadAndParseCsv, and prints JSON to stdout.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BRIDGE_SCRIPT = REPO_ROOT / 'eval' / 'bin' / 'csv-cost.js'

# Playwright takes a while to launch; rehydration polling adds more.
# 90s is the same ceiling validation/csv-export.js uses internally
# (NAVIGATION_TIMEOUT_MS + DOWNLOAD_TIMEOUT_MS + slack).
CSV_TIMEOUT_S = 120


class CSVOracleError(RuntimeError):
    pass


def fetch_cost(url: str) -> dict:
    """Drive the Node CSV oracle. Returns:
        {
          monthlyCost:      float|None,
          monthlyByService: list[[str, float]],
          configByService:  list[[str, str|None]],  # rehydrated Config Summary
        }

    `configByService` mirrors the calculator's "Configuration summary"
    column for each detailed-estimate row. Empty cells render as None.
    Useful to assert that fields surfaced as expected.

    Raises CSVOracleError on subprocess failure or unparseable JSON.
    """
    if not BRIDGE_SCRIPT.exists():
        raise CSVOracleError(f'bridge script missing at {BRIDGE_SCRIPT}')

    try:
        proc = subprocess.run(
            ['node', str(BRIDGE_SCRIPT), url],
            capture_output=True, text=True,
            timeout=CSV_TIMEOUT_S, check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise CSVOracleError(f'CSV oracle timed out after {CSV_TIMEOUT_S}s') from e

    if proc.returncode != 0:
        # stderr from csv-export.js carries Playwright errors —
        # surface a brief excerpt so failures aren't opaque.
        excerpt = (proc.stderr or '').strip().splitlines()[-3:]
        raise CSVOracleError(
            f'CSV oracle exit {proc.returncode}: ' + ' | '.join(excerpt),
        )

    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise CSVOracleError(f'CSV oracle stdout not JSON: {proc.stdout[:200]}') from e
