#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Run eval scenarios against the local mcp-server.js (stdio).

Usage:
    python eval/run.py                          # run all scenarios
    python eval/run.py lambda-minimal           # one scenario by id
    python eval/run.py --list                   # list available
    python eval/run.py --json                   # machine-readable output

Exit code 0 if all scenarios pass, 1 otherwise.

Reads scenario YAMLs from eval/scenarios/. Each scenario specifies a
list of MCP tool calls to drive and a list of predicate assertions to
check the resulting trace against.

A deployment-side eval can share the same scenario format and predicate
library — the only difference is the driver substrate (HTTPS through a
gateway vs. local stdio).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

# Make `from eval.predicates import ...` work both via direct invocation
# and via `python -m eval.run`.
if __name__ == '__main__' and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval import predicates
from eval.predicates import AssertionOutcome, TraceResult
from eval.stdio_driver import run_scenario


REPO_ROOT = Path(__file__).resolve().parent.parent
CANONICAL_CATALOG_DIR = REPO_ROOT / 'catalog' / 'services'
SCENARIOS_DIR = Path(__file__).resolve().parent / 'scenarios'


def _is_llm_scenario(scenario: dict) -> bool:
    """LLM scenarios have a `prompt`; scripted scenarios have `calls`."""
    return 'prompt' in scenario and 'calls' not in scenario


def _run_llm(scenario: dict, model_id: str | None = None) -> TraceResult:
    # Lazy import — boto3 only needed for LLM scenarios. Scripted
    # scenarios run dep-free; the harness keeps that property unless
    # you opt into LLM mode by writing a `prompt:` scenario.
    from eval.llm_driver import run_llm_scenario
    return run_llm_scenario(scenario, model_id=model_id)


def _load_yaml(path: Path) -> dict:
    """Minimal YAML loader fallback so we don't add a dep for a few files.

    We support the subset our scenarios use: top-level keys, scalar
    values, lists of dicts, and triple-quoted strings (via the `|`
    block scalar). If a scenario grows beyond this, install PyYAML.
    """
    try:
        import yaml  # type: ignore[import-untyped]
        return yaml.safe_load(path.read_text())
    except ImportError:
        raise SystemExit(
            'PyYAML required: pip install pyyaml\n'
            '(scenarios use YAML for readability; predicates.py and the '
            'driver have no extra deps)'
        )


def _load_scenarios() -> list[dict]:
    if not SCENARIOS_DIR.exists():
        return []
    out = []
    for path in sorted(SCENARIOS_DIR.glob('*.yaml')):
        scenario = _load_yaml(path)
        scenario['_path'] = path.name
        out.append(scenario)
    return out


# ----- Catalog mutation pipeline -----------------------------------------
#
# Scenarios may include a `catalog_mutations:` list. Each mutation is a
# JSON-Patch-style operation (RFC 6902) plus two domain-specific ops:
#
#   - op: removeEntry, service: <code>
#       Deletes the entire catalog/services/<code>.json file from the
#       mutated copy. Probes "what does the agent do with no entry?"
#
#   - op: replaceEntry, service: <code>, value: <full entry object>
#       Replaces the file contents wholesale. Useful for "revert to
#       a known-broken historical shape."
#
# Standard ops (add/remove/replace/copy/move/test) operate WITHIN a
# single entry, addressed as `service: <code>, path: /required/0/example/unit`.
# `path` is a JSON Pointer rooted at the entry object.
#
# Mutations are written to a temp dir under eval/_results/_catalog-<id>-<ts>/
# (gitignored), the CALCMCP_CATALOG_DIR env var is pointed at it, and the
# subprocess inherits the env. Cleanup deletes the temp dir on context exit
# unless --keep-mutated-catalog is set for debugging.


def _apply_pointer(obj: Any, pointer: str, op: str, value: Any = None) -> Any:
    """Apply a single JSON-Pointer op on a Python object (in place)."""
    if pointer in ('', '/'):
        if op == 'replace':
            return value
        raise ValueError(f'op {op!r} not supported on root pointer')
    parts = [p.replace('~1', '/').replace('~0', '~')
             for p in pointer.lstrip('/').split('/')]
    target = obj
    for p in parts[:-1]:
        if isinstance(target, list):
            target = target[int(p)]
        else:
            target = target[p]
    last = parts[-1]
    if isinstance(target, list):
        idx = len(target) if last == '-' else int(last)
        if op == 'add':
            target.insert(idx, value)
        elif op == 'replace':
            target[idx] = value
        elif op == 'remove':
            del target[idx]
        else:
            raise ValueError(f'unsupported op {op!r} on list')
    else:
        if op == 'add' or op == 'replace':
            target[last] = value
        elif op == 'remove':
            del target[last]
        else:
            raise ValueError(f'unsupported op {op!r} on object')
    return obj


def _materialize_mutated_catalog(mutations: list[dict], scenario_id: str) -> Path:
    """Copy the canonical catalog into a temp dir and apply mutations.

    Returns the temp dir path. Caller is responsible for cleanup.
    """
    results_dir = REPO_ROOT / 'eval' / '_results'
    results_dir.mkdir(parents=True, exist_ok=True)
    tag = f'{scenario_id}-{int(time.time())}'
    temp_dir = Path(tempfile.mkdtemp(prefix=f'_catalog-{tag}-', dir=results_dir))
    shutil.copytree(CANONICAL_CATALOG_DIR, temp_dir, dirs_exist_ok=True)

    for m in mutations:
        op = m.get('op')
        service = m.get('service')
        if not service:
            raise ValueError(f'mutation missing `service`: {m!r}')
        entry_path = temp_dir / f'{service}.json'

        if op == 'removeEntry':
            if entry_path.exists():
                entry_path.unlink()
            continue

        if op == 'replaceEntry':
            value = m.get('value')
            if not isinstance(value, dict):
                raise ValueError(f'replaceEntry needs value (dict): {m!r}')
            entry_path.write_text(json.dumps(value, indent=2) + '\n')
            continue

        # Standard JSON Pointer ops on a single entry.
        if not entry_path.exists():
            raise ValueError(
                f'mutation targets {service!r} but no such entry in canonical '
                f'catalog (did you forget to use replaceEntry to author it?)'
            )
        entry = json.loads(entry_path.read_text())
        pointer = m.get('path', '')
        value = m.get('value')
        _apply_pointer(entry, pointer, op, value)
        entry_path.write_text(json.dumps(entry, indent=2) + '\n')

    return temp_dir


@contextmanager
def _catalog_environment(scenario: dict, *, keep: bool = False):
    """Set CALCMCP_CATALOG_DIR for the scope of one scenario, if mutations apply."""
    mutations = scenario.get('catalog_mutations') or []
    if not mutations:
        yield None
        return

    temp_dir = _materialize_mutated_catalog(mutations, scenario['id'])
    prior = os.environ.get('CALCMCP_CATALOG_DIR')
    os.environ['CALCMCP_CATALOG_DIR'] = str(temp_dir)
    try:
        yield temp_dir
    finally:
        if prior is None:
            del os.environ['CALCMCP_CATALOG_DIR']
        else:
            os.environ['CALCMCP_CATALOG_DIR'] = prior
        if not keep:
            shutil.rmtree(temp_dir, ignore_errors=True)


def _check_expectation(trace: TraceResult, expectation: dict) -> AssertionOutcome:
    """Dispatch one expectation entry to the matching predicate function."""
    name = expectation['predicate']
    fn = getattr(predicates, f'assert_{name}', None)
    if fn is None:
        return AssertionOutcome(
            status='fail', predicate=name,
            reason=f'unknown predicate {name!r} (see eval/predicates.py)',
        )
    # Pass any non-`predicate` keys as kwargs to the predicate function.
    kwargs = {k: v for k, v in expectation.items() if k != 'predicate'}
    try:
        return fn(trace, **kwargs)
    except TypeError as e:
        return AssertionOutcome(
            status='fail', predicate=name,
            reason=f'wrong args for {name!r}: {e}',
        )


def _format_outcome(o: AssertionOutcome) -> str:
    icon = {'ok': 'PASS', 'fail': 'FAIL', 'skip': 'SKIP'}[o.status]
    line = f'    [{icon}] {o.predicate}'
    if o.reason:
        line += f' — {o.reason}'
    return line


def _run_one(scenario: dict, verbose: bool = False,
             llm_model_id: str | None = None,
             keep_mutated_catalog: bool = False,
             skip_dom_oracle: bool = False,
             ) -> tuple[TraceResult, list[AssertionOutcome]]:
    with _catalog_environment(scenario, keep=keep_mutated_catalog):
        trace = (_run_llm(scenario, model_id=llm_model_id) if _is_llm_scenario(scenario)
                 else run_scenario(scenario))
    expectations = scenario.get('expectations', [])
    if skip_dom_oracle:
        expectations = [e for e in expectations
                        if e.get('predicate') != 'estimate_renders_cost']
    outcomes = [_check_expectation(trace, exp) for exp in expectations]
    return trace, outcomes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scenario_id', nargs='*',
                        help='specific scenario id(s) (default: run all)')
    parser.add_argument('--list', action='store_true',
                        help='list available scenarios and exit')
    parser.add_argument('--json', action='store_true',
                        help='emit machine-readable JSON')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='print per-call detail')
    parser.add_argument('--model',
                        help='Bedrock inference-profile id for LLM scenarios '
                             '(e.g. us.anthropic.claude-sonnet-4-5-20250929-v1:0). '
                             'Overrides scenario `model:` and the driver default.')
    parser.add_argument('--keep-mutated-catalog', action='store_true',
                        help='Leave the mutated-catalog temp dir on disk after '
                             'the scenario completes (debugging only)')
    parser.add_argument('--scripted-only', action='store_true',
                        help='Skip LLM scenarios (those with `prompt:`). '
                             'Fast regression check — no Bedrock calls.')
    parser.add_argument('--skip-dom-oracle', action='store_true',
                        help='Skip estimate_renders_cost predicates (saves '
                             '~5s per scenario by avoiding Playwright launch).')
    parser.add_argument('--rerun-failed', action='store_true',
                        help='Run only scenarios that failed in the previous '
                             'run (read from eval/_results/last-failed.txt). '
                             'Tight feedback loop after a flaky or '
                             'newly-broken scenario surfaces in a full run.')
    args = parser.parse_args()

    scenarios = _load_scenarios()

    if args.list:
        for s in scenarios:
            print(f'  {s["id"]:<32}  {s["_path"]}')
        return 0

    if args.scenario_id:
        wanted = set(args.scenario_id)
        scenarios = [s for s in scenarios if s['id'] in wanted]
        missing = wanted - {s['id'] for s in scenarios}
        if missing:
            print(f'no scenario matches: {", ".join(sorted(missing))}', file=sys.stderr)
            return 2

    if args.rerun_failed:
        last_failed_path = REPO_ROOT / 'eval' / '_results' / 'last-failed.txt'
        if not last_failed_path.exists():
            print(f'no previous failures recorded at {last_failed_path}', file=sys.stderr)
            return 2
        wanted = {line.strip() for line in last_failed_path.read_text().splitlines() if line.strip()}
        if not wanted:
            print('previous run had no failures — nothing to rerun', file=sys.stderr)
            return 0
        scenarios = [s for s in scenarios if s['id'] in wanted]

    if args.scripted_only:
        scenarios = [s for s in scenarios if not _is_llm_scenario(s)]

    if not scenarios:
        print('no scenarios found', file=sys.stderr)
        return 2

    results = []
    failed = 0
    for scenario in scenarios:
        if not args.json:
            print(f'\n{scenario["id"]}: {scenario.get("description", "").strip()}')
        trace, outcomes = _run_one(scenario, verbose=args.verbose,
                                   llm_model_id=args.model,
                                   keep_mutated_catalog=args.keep_mutated_catalog,
                                   skip_dom_oracle=args.skip_dom_oracle)
        scenario_failed = sum(1 for o in outcomes if o.status == 'fail')
        if scenario_failed > 0:
            failed += 1

        if not args.json:
            print(f'  {len(trace.calls)} tool calls in {trace.duration_ms}ms')
            if args.verbose:
                for c in trace.calls:
                    # nosemgrep: is-function-without-parentheses
                    # is_error is a `bool` field on the CallRecord dataclass.
                    tag = 'ERR' if c.is_error else 'ok'
                    print(f'    [{tag}] {c.tool}')
            for o in outcomes:
                print(_format_outcome(o))

        results.append({
            'scenario': scenario['id'],
            'duration_ms': trace.duration_ms,
            'tool_calls': [c.tool for c in trace.calls],
            'final_url': trace.final_url,
            'assistant_messages': trace.assistant_messages,
            'outcomes': [
                {'predicate': o.predicate, 'status': o.status,
                 'reason': o.reason, 'expected': o.expected, 'actual': o.actual}
                for o in outcomes
            ],
        })

    # Persist failed-scenario ids for --rerun-failed. Skip when --rerun-failed
    # itself is the driver (don't overwrite the seed list mid-iteration unless
    # we ran the full set) and skip when --scripted-only / explicit ids
    # narrow the run (those subsets shouldn't claim authority over the
    # full-suite failure list).
    is_full_run = (not args.scenario_id and not args.scripted_only
                   and not args.rerun_failed)
    if is_full_run:
        last_failed_path = REPO_ROOT / 'eval' / '_results' / 'last-failed.txt'
        last_failed_path.parent.mkdir(parents=True, exist_ok=True)
        failed_ids = [r['scenario'] for r in results
                      if any(o['status'] == 'fail' for o in r['outcomes'])]
        last_failed_path.write_text('\n'.join(failed_ids) + ('\n' if failed_ids else ''))

    if args.json:
        print(json.dumps(results, indent=2, default=str))
    else:
        passed = len(scenarios) - failed
        print(f'\n{passed}/{len(scenarios)} scenarios passed')

    return 1 if failed > 0 else 0


if __name__ == '__main__':
    sys.exit(main())
