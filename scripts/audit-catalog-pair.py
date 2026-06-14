#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Catalog audit via paired with/without scenarios.

For each requested service, runs the `cat-<slug>-with` and
`cat-<slug>-without` eval scenarios (LLM-driven), then computes a
drift verdict from the resulting costs:

  - both saved & ratio < N      → REDUNDANT  (catalog adds <N× drift)
  - both saved & ratio >= N     → EARNS PLACE (>=N× drift, catalog
                                  is what holds the magnitude in band)
  - with saves, without fails   → EARNS PLACE (catalog is what lets
                                  the agent reach a priced save)
  - with fails, without saves   → REGRESSION (catalog is actively
                                  hurting; needs investigation)
  - both fail                   → BROKEN     (prompt/lint problem,
                                  not a catalog signal)

Why this and not a per-scenario predicate: the eval harness scores
scenarios independently. Cost-drift is inherently cross-scenario, so
it lives outside the harness as a thin wrapper that calls
`eval/run.py` then post-processes the JSON output.

Usage:
    # audit one service
    python3 scripts/audit-catalog-pair.py amazonElasticsearchService

    # audit several
    python3 scripts/audit-catalog-pair.py amazonRDSPostgreSQLDB awsLambda

    # audit every paired cat-* scenario in eval/scenarios/
    python3 scripts/audit-catalog-pair.py --all

    # custom drift threshold
    python3 scripts/audit-catalog-pair.py --factor 5 awsFargate

    # repeat each pair 3 times and use median cost (LLM variance dampener)
    python3 scripts/audit-catalog-pair.py --repeat 3 amazonBedrock

Output: writes a CSV to stdout (or --output PATH) with one row per
service. Exit code is non-zero if any service falls into BROKEN or
REGRESSION (the buckets that warrant attention before shipping).
REDUNDANT is informational; it doesn't fail the run.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIO_DIR = REPO_ROOT / 'eval' / 'scenarios'
RUN_PY = REPO_ROOT / 'eval' / 'run.py'

DEFAULT_DRIFT_FACTOR = 3.0


# Mapping serviceCode → scenario slug. The eval scenarios use short
# slugs (cat-lambda-with) for readability; this resolves serviceCodes
# to those slugs. Reads the scenarios on disk to keep the mapping
# authoritative.
def discover_scenarios() -> dict[str, str]:
    """Returns {serviceCode → slug} by scanning catalog_mutations in
    cat-*-without scenarios. The `removeEntry` op carries the
    canonical service code, so we read it directly rather than
    maintaining a hardcoded table.
    """
    out: dict[str, str] = {}
    for path in sorted(SCENARIO_DIR.glob('cat-*-without.yaml')):
        slug = path.stem[len('cat-'):-len('-without')]
        # Cheap line-scanner — we don't need a YAML parser for one key.
        # Looking for `service: <serviceCode>` under catalog_mutations.
        for line in path.read_text().splitlines():
            line = line.strip()
            if line.startswith('service:'):
                code = line.split(':', 1)[1].strip()
                if code:
                    out[code] = slug
                    break
    return out


def list_all_slugs() -> list[str]:
    return sorted({
        p.stem[len('cat-'):-len('-without')]
        for p in SCENARIO_DIR.glob('cat-*-without.yaml')
    })


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('services', nargs='*',
                   help='serviceCode(s) to audit. Use --all for everything.')
    p.add_argument('--all', action='store_true',
                   help='Audit every paired cat-* scenario.')
    p.add_argument('--factor', type=float, default=DEFAULT_DRIFT_FACTOR,
                   help=f'Drift factor threshold (default: {DEFAULT_DRIFT_FACTOR}). '
                        f'Pairs with cost ratio < N are REDUNDANT; >=N are EARNS PLACE.')
    p.add_argument('--output', '-o', default='-',
                   help='CSV output path; "-" for stdout (default).')
    p.add_argument('--keep-mutated-catalog', action='store_true',
                   help='Forwarded to eval/run.py for debugging.')
    p.add_argument('--repeat', '-n', type=int, default=1, metavar='N',
                   help='Run each scenario pair N times and use the median cost '
                        'for the verdict. Dampens LLM variance (NAT swung from '
                        '2.3x to 1.14x drift across single runs 2026-06-01). '
                        'Sequential — N copies of each scenario run back-to-back '
                        'via separate eval/run.py invocations.')
    return p.parse_args()


def resolve_slugs(service_args: list[str], use_all: bool) -> list[str]:
    if use_all:
        return list_all_slugs()
    code_to_slug = discover_scenarios()
    all_slugs = set(list_all_slugs())  # authoritative — derived from filenames
    slugs = []
    missing = []
    for arg in service_args:
        # Accept either a serviceCode (preferred) or a slug. Slugs win when
        # there are multiple scenario pairs for the same serviceCode (e.g.
        # cat-bedrock-* and cat-bedrock-titan-* both target amazonBedrock).
        if arg in all_slugs:
            slugs.append(arg)
        elif arg in code_to_slug:
            slugs.append(code_to_slug[arg])
        else:
            missing.append(arg)
    if missing:
        print(f'No paired scenarios found for: {", ".join(missing)}',
              file=sys.stderr)
        print(f'  Known services: {", ".join(sorted(code_to_slug))}',
              file=sys.stderr)
        print(f'  Known slugs:    {", ".join(sorted(all_slugs))}',
              file=sys.stderr)
        sys.exit(2)
    return slugs


def run_eval(scenario_ids: list[str], keep_mutated: bool) -> list[dict]:
    """Invoke `python3 eval/run.py <ids> --json` and parse the result."""
    cmd = ['python3', str(RUN_PY)] + scenario_ids + ['--json']
    if keep_mutated:
        cmd.append('--keep-mutated-catalog')
    print(f'Running {len(scenario_ids)} scenarios...', file=sys.stderr)
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          cwd=REPO_ROOT)
    if proc.returncode != 0 and not proc.stdout:
        print('eval/run.py failed:', file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        sys.exit(proc.returncode)
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        print(f'JSON parse error: {e}', file=sys.stderr)
        print('--- stdout (first 500 chars) ---', file=sys.stderr)
        print(proc.stdout[:500], file=sys.stderr)
        sys.exit(1)


def extract_cost(actual):
    if not actual:
        return None
    # Predicate's `actual` field is shaped like '$346.47/mo (per-row: ...)'
    m = re.match(r'\$([0-9.]+)/mo', actual)
    return float(m.group(1)) if m else None


def classify(w, wo, factor):
    """Returns (verdict, ratio). ratio is None when not computed."""
    if not w['saved'] and not wo['saved']:
        return 'BROKEN', None
    if not w['saved']:
        # The without saves but the with doesn't — catalog is the problem.
        return 'REGRESSION', None
    if not wo['saved']:
        return 'EARNS PLACE', None
    # Both saved.
    if w['cost'] is None or wo['cost'] is None:
        return 'NO COST DATA', None
    if w['cost'] == 0 and wo['cost'] == 0:
        # Both rendered $0. Could be free-tier-correct, could be silent
        # trap. From a catalog-audit standpoint, the catalog isn't
        # changing the outcome, so we mark redundant; the silent-trap
        # case is a separate predicate's responsibility.
        return 'BOTH ZERO', 1.0
    if w['cost'] == 0:
        # WITH renders $0 — possible silent trap that the catalog isn't
        # protecting against. Surface as a regression.
        return 'WITH ZERO', None
    if wo['cost'] == 0:
        # Catalog protected against $0; without it, nothing rendered.
        return 'EARNS PLACE', None
    ratio = max(w['cost'], wo['cost']) / min(w['cost'], wo['cost'])
    if ratio >= factor:
        return 'EARNS PLACE', ratio
    return 'REDUNDANT', ratio


def _aggregate_runs(runs: list[dict]) -> dict:
    """Collapse N per-run dicts into the single shape `classify` expects.

    - saved: True iff a strict majority of runs saved (ties favor False —
      a 50/50 split signals instability, not success).
    - cost: median of the costs across runs that have a cost. None if
      no run produced a cost.
    - url: the URL of the run whose cost is closest to the median (the
      "representative" save). Useful for debugging the verdict.
    """
    if not runs:
        return {'saved': False, 'cost': None, 'cost_actual': None,
                'url': None, 'tools': 0, 'runs': 0}
    saved_count = sum(1 for r in runs if r['saved'])
    saved_majority = saved_count > len(runs) / 2

    costs_with_url = [(r['cost'], r['url'], r['cost_actual'])
                      for r in runs if r['cost'] is not None]
    if costs_with_url:
        costs = sorted(c[0] for c in costs_with_url)
        n = len(costs)
        median_cost = (costs[n // 2] if n % 2 == 1
                       else (costs[n // 2 - 1] + costs[n // 2]) / 2)
        # Pick the actual run whose cost is nearest the median for the URL —
        # gives a debuggable handle on the representative save.
        nearest = min(costs_with_url, key=lambda c: abs(c[0] - median_cost))
        repr_url = nearest[1]
        repr_actual = nearest[2]
    else:
        median_cost = None
        repr_url = next((r['url'] for r in runs if r['url']), None)
        repr_actual = None

    avg_tools = sum(r['tools'] for r in runs) / len(runs)
    return {
        'saved': saved_majority,
        'cost': median_cost,
        'cost_actual': repr_actual,
        'url': repr_url,
        'tools': round(avg_tools),
        'runs': len(runs),
    }


def main():
    args = parse_args()
    if not args.services and not args.all:
        print('error: provide at least one service or --all', file=sys.stderr)
        sys.exit(2)

    if args.repeat < 1:
        print('--repeat must be >= 1', file=sys.stderr)
        sys.exit(2)

    slugs = resolve_slugs(args.services, args.all)
    if not slugs:
        print('no slugs resolved', file=sys.stderr)
        sys.exit(2)

    scenario_ids = []
    for slug in slugs:
        scenario_ids.append(f'cat-{slug}-with')
        scenario_ids.append(f'cat-{slug}-without')

    # Per (slug, kind) → list of per-run dicts. eval/run.py dedups argv so
    # we run N separate invocations rather than passing duplicate ids.
    per_run: dict[tuple[str, str], list[dict]] = {}
    for run_idx in range(args.repeat):
        if args.repeat > 1:
            print(f'\n=== run {run_idx + 1}/{args.repeat} ===',
                  file=sys.stderr)
        results = run_eval(scenario_ids, args.keep_mutated_catalog)
        for r in results:
            sid = r['scenario']
            if not sid.startswith('cat-'):
                continue
            parts = sid[len('cat-'):].rsplit('-', 1)
            if len(parts) != 2 or parts[1] not in ('with', 'without'):
                continue
            slug, kind = parts
            save_o = next((o for o in r['outcomes']
                           if o['predicate'] == 'save_succeeded'), None)
            cost_o = next((o for o in r['outcomes']
                           if o['predicate'] == 'estimate_renders_cost'), None)
            per_run.setdefault((slug, kind), []).append({
                'saved': bool(save_o and save_o['status'] == 'ok'),
                'cost': extract_cost(cost_o.get('actual') if cost_o else None),
                'cost_actual': cost_o.get('actual') if cost_o else None,
                'url': r.get('final_url'),
                'tools': len(r['tool_calls']),
            })

    # Aggregate per (slug, kind) into the single shape classify() expects.
    by_slug: dict[str, dict[str, dict]] = {}
    for (slug, kind), runs in per_run.items():
        by_slug.setdefault(slug, {})[kind] = _aggregate_runs(runs)

    # Build CSV rows. `runs` column reports N when --repeat > 1; otherwise blank.
    has_repeats = args.repeat > 1
    header = ['service', 'with_saved', 'with_cost',
              'without_saved', 'without_cost', 'ratio',
              'verdict', 'with_url', 'without_url']
    if has_repeats:
        header.insert(7, 'runs')
    rows = [header]
    failures = 0
    summary = {'EARNS PLACE': 0, 'REDUNDANT': 0, 'BROKEN': 0,
               'REGRESSION': 0, 'BOTH ZERO': 0, 'WITH ZERO': 0,
               'NO COST DATA': 0}
    for slug in slugs:
        pair = by_slug.get(slug, {})
        w = pair.get('with')
        wo = pair.get('without')
        if not w or not wo:
            empty = [slug, '', '', '', '', '', 'INCOMPLETE', '', '']
            if has_repeats:
                empty.insert(7, '')
            rows.append(empty)
            failures += 1
            continue
        verdict, ratio = classify(w, wo, args.factor)
        summary[verdict] = summary.get(verdict, 0) + 1
        if verdict in ('BROKEN', 'REGRESSION', 'WITH ZERO'):
            failures += 1
        row = [
            slug,
            'yes' if w['saved'] else 'no',
            f'${w["cost"]}' if w['cost'] is not None else '',
            'yes' if wo['saved'] else 'no',
            f'${wo["cost"]}' if wo['cost'] is not None else '',
            f'{ratio:.2f}' if ratio is not None else '',
            verdict,
            w.get('url') or '',
            wo.get('url') or '',
        ]
        if has_repeats:
            # Show actual run counts (with may differ from without if one
            # invocation crashed). Format: "with/without".
            row.insert(7, f'{w.get("runs", 1)}/{wo.get("runs", 1)}')
        rows.append(row)

    # Emit CSV.
    out_lines = []
    for row in rows:
        out_lines.append(','.join(_csv_escape(c) for c in row))
    csv_text = '\n'.join(out_lines) + '\n'
    if args.output == '-':
        sys.stdout.write(csv_text)
    else:
        Path(args.output).write_text(csv_text)
        print(f'wrote {args.output}', file=sys.stderr)

    # Summary line on stderr.
    print('', file=sys.stderr)
    parts = [f'{k}={v}' for k, v in summary.items() if v > 0]
    repeat_note = f', median-of-{args.repeat}' if args.repeat > 1 else ''
    print(f'audit summary ({args.factor}× drift threshold{repeat_note}): '
          + ', '.join(parts), file=sys.stderr)

    sys.exit(1 if failures > 0 else 0)


def _csv_escape(v) -> str:
    s = '' if v is None else str(v)
    if any(ch in s for ch in ',"\n'):
        return '"' + s.replace('"', '""') + '"'
    return s


if __name__ == '__main__':
    main()
