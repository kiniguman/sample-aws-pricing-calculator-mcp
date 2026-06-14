# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Drives mcp-server.js over stdio. No AWS credentials needed; the server
itself talks to the public CloudFront endpoints.

Returns a TraceResult that predicates.py can score. This is the
CI-friendly path — fast, dep-free (no Bedrock, no auth, no gateway
hop), suitable for running on every PR in this repo.

A deployment-side equivalent (HTTPS through a gateway with auth) can
produce the same TraceResult shape and feed the same predicate library.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from eval.predicates import CallRecord, TraceResult, parse_text_or_none


REPO_ROOT = Path(__file__).resolve().parent.parent
SERVER_SCRIPT = REPO_ROOT / 'mcp-server.js'

# Per-call timeout for the JSON-RPC response. The slowest tool today is
# get_service_fields against a fresh manifest cache (~1-2s); 30s is
# defensive. Tune down once we have eval-run latency telemetry.
RESPONSE_TIMEOUT_S = 30


class MCPStdioClient:
    """Minimal MCP-over-stdio client.

    Spawns the server as a subprocess, exchanges JSON-RPC messages over
    stdin/stdout, captures stderr separately for trace events. Not a
    full MCP client — it implements only what the eval driver needs:
    initialize, tools/call.
    """

    def __init__(self, server_script: Path = SERVER_SCRIPT):
        if not server_script.exists():
            raise FileNotFoundError(f'mcp-server.js not at {server_script}')
        self._proc: subprocess.Popen | None = None
        self._server_script = server_script
        self._next_id = 1
        self._stderr_lines: list[str] = []

    def __enter__(self):
        self._proc = subprocess.Popen(
            ['node', str(self._server_script)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )
        self._initialize()
        return self

    def __exit__(self, *exc):
        if self._proc:
            try:
                self._proc.stdin.close()
                self._proc.wait(timeout=2)
            except (subprocess.TimeoutExpired, ValueError, BrokenPipeError):
                self._proc.kill()
            # Drain stderr so trace events captured during the run are
            # available to the caller via stderr_events().
            try:
                remaining = self._proc.stderr.read() or ''
                self._stderr_lines.extend(remaining.splitlines())
            except (ValueError, OSError):
                pass

    def call_tool(self, name: str, arguments: dict) -> dict:
        """Send tools/call. Returns the parsed JSON-RPC response.

        Raises RuntimeError on transport-level failure (server crashed,
        timeout). Tool-level failures (isError:true) are returned in
        the response — that's the agent-observable path and the eval
        cares about it.
        """
        req = {
            'jsonrpc': '2.0', 'id': self._next_id, 'method': 'tools/call',
            'params': {'name': name, 'arguments': arguments},
        }
        self._next_id += 1
        return self._send_and_recv(req)

    def stderr_events(self) -> list[dict]:
        """Parse stderr lines into trace events.

        lib/trace-logger.js emits one JSON line per event. Non-JSON
        lines (initial manifest-load logs from aws-client.js) are
        skipped silently — they're not events.
        """
        out = []
        for line in self._stderr_lines:
            line = line.strip()
            if not line.startswith('{'):
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    # ----- internals -----

    def _initialize(self) -> None:
        # MCP handshake. The server's McpServer accepts an empty
        # capabilities object from the client.
        req = {
            'jsonrpc': '2.0', 'id': self._next_id, 'method': 'initialize',
            'params': {
                'protocolVersion': '2025-06-18',
                'capabilities': {},
                'clientInfo': {'name': 'local-eval-driver', 'version': '0.1'},
            },
        }
        self._next_id += 1
        self._send_and_recv(req)
        # initialized notification — no id, no response expected.
        self._proc.stdin.write(json.dumps({
            'jsonrpc': '2.0', 'method': 'notifications/initialized',
        }) + '\n')
        self._proc.stdin.flush()

    def _send_and_recv(self, req: dict) -> dict:
        self._proc.stdin.write(json.dumps(req) + '\n')
        self._proc.stdin.flush()
        deadline = time.time() + RESPONSE_TIMEOUT_S
        while time.time() < deadline:
            line = self._proc.stdout.readline()
            if not line:
                raise RuntimeError('mcp-server.js closed stdout (likely crashed)')
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Eat notifications; only correlate by id for responses.
            if msg.get('id') == req['id']:
                return msg
        raise TimeoutError(f'no response in {RESPONSE_TIMEOUT_S}s for {req["method"]}')


def _extract_text(rpc_response: dict) -> str:
    """Pull the first text-content piece from a tools/call response."""
    content = rpc_response.get('result', {}).get('content', [])
    for c in content:
        if c.get('type') == 'text':
            return c.get('text', '')
    return ''


def _extract_url(text: str, parsed: Any) -> str | None:
    """Find a sharable_url in a tool response, if present."""
    if isinstance(parsed, dict):
        if 'sharable_url' in parsed:
            return parsed['sharable_url']
    return None


def _expand_template(value, context: dict):
    """Replace ${var} in scenario calls with values from context.

    Today only estimate_id is threaded through context.
    """
    if isinstance(value, str) and value.startswith('${') and value.endswith('}'):
        key = value[2:-1]
        if key not in context:
            raise KeyError(f'template var ${{{key}}} not in context')
        return context[key]
    if isinstance(value, dict):
        return {k: _expand_template(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_template(v, context) for v in value]
    return value


def run_scenario(scenario: dict) -> TraceResult:
    """Drive a hardcoded scenario through stdio and return a TraceResult.

    Scenario format:
        {
          "id": "lambda-1m-requests",
          "description": "...",
          "calls": [
            {"tool": "create_estimate", "args": {...}},
            {"tool": "add_service",
             "args": {"estimate_id": "${estimate_id}", "services": "..."}},
            ...
          ]
        }

    create_estimate / build_estimate responses populate
    context['estimate_id'] for subsequent calls.
    """
    started = time.time()
    trace = TraceResult(scenario_id=scenario['id'])
    context: dict = {}

    with MCPStdioClient() as client:
        for raw_call in scenario['calls']:
            try:
                args = _expand_template(raw_call['args'], context)
            except KeyError as e:
                trace.calls.append(CallRecord(
                    tool=raw_call['tool'], args=raw_call['args'],
                    is_error=True, text=f'template error: {e}', parsed=None,
                ))
                break

            response = client.call_tool(raw_call['tool'], args)
            text = _extract_text(response)
            parsed = parse_text_or_none(text)
            is_error = bool(response.get('result', {}).get('isError'))

            trace.calls.append(CallRecord(
                tool=raw_call['tool'], args=args,
                is_error=is_error, text=text, parsed=parsed,
            ))

            # Thread estimate_id through for subsequent template expansion.
            if not is_error and isinstance(parsed, dict):
                if 'estimate_id' in parsed:
                    context['estimate_id'] = parsed['estimate_id']
                if not trace.final_url:
                    trace.final_url = _extract_url(text, parsed)

        trace.events = client.stderr_events()

    trace.duration_ms = int((time.time() - started) * 1000)
    return trace
