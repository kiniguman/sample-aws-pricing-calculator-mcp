# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
LLM-driven scenario runner: gives Haiku 4.5 the MCP tools and a
natural-language prompt, captures the trajectory, returns a
TraceResult that predicates.py can score.

This is what turns the eval harness from a regression-test of
scripted MCP-call sequences into a behavior eval. It answers
questions production traces cannot:
  - Did the agent call get_service_fields before add_service?
  - Did the agent's add_service config use catalog minimalConfig keys?
  - Did the agent recover from a needs_grounding redirect?

Stays within local_calculator: drives the local mcp-server.js over
stdio, talks to Bedrock for the LLM. No Cognito/Gateway dance, no
production credentials needed beyond what AWS profiles already grant.

Cost estimate: each scenario ≈ 5-15 tool calls × 2K tokens each ≈
$0.001 per scenario at Haiku 4.5 prices. Full eval suite (5
scenarios) is < 1 cent per run.
"""

from __future__ import annotations

import json
import time
from typing import Any

import boto3

from eval.predicates import CallRecord, TraceResult, parse_text_or_none
from eval.stdio_driver import MCPStdioClient, _extract_text, _extract_url


# Haiku 4.5 needs an inference profile, not a bare model id. The
# `us.` prefix is the US-region cross-region inference profile.
DEFAULT_MODEL_ID = 'us.anthropic.claude-haiku-4-5-20251001-v1:0'

# Cap LLM-driver scenarios at 20 turns. A healthy scenario terminates
# in 3-8 turns; 20 leaves headroom for recovery loops without letting
# a runaway agent spend money. Adjust per-scenario via max_turns.
DEFAULT_MAX_TURNS = 20

# Per-call max_tokens for Haiku's response. Tool-use blocks are
# small; final summaries are small. 4K leaves plenty of room.
RESPONSE_MAX_TOKENS = 4000


class LLMDriverError(RuntimeError):
    """Driver-level failure (not a scenario failure)."""


def _list_mcp_tools(client: MCPStdioClient) -> list[dict]:
    """Pull tool definitions from the MCP server via tools/list.

    Returns Bedrock-formatted tool defs:
        {name, description, input_schema}

    The MCP server's tool schemas are JSON Schema; Bedrock accepts
    JSON Schema directly under `input_schema`. We pass them through
    with one rename (the MCP wire format calls it `inputSchema`,
    camelCase; Bedrock wants `input_schema`).
    """
    req = {
        'jsonrpc': '2.0', 'id': client._next_id, 'method': 'tools/list',
        'params': {},
    }
    client._next_id += 1
    response = client._send_and_recv(req)
    raw_tools = response.get('result', {}).get('tools', [])
    bedrock_tools = []
    for t in raw_tools:
        bedrock_tools.append({
            'name': t['name'],
            'description': t.get('description', ''),
            'input_schema': t.get('inputSchema', {'type': 'object'}),
        })
    return bedrock_tools


def _bedrock_invoke(
    bedrock_client, model_id: str, system: str,
    messages: list[dict], tools: list[dict],
) -> dict:
    """One Bedrock invoke call. Returns the parsed response body."""
    body = {
        'anthropic_version': 'bedrock-2023-05-31',
        'max_tokens': RESPONSE_MAX_TOKENS,
        'system': system,
        'messages': messages,
        'tools': tools,
    }
    response = bedrock_client.invoke_model(
        modelId=model_id, body=json.dumps(body),
    )
    return json.loads(response['body'].read())


def _build_system_prompt(extra: str | None = None) -> str:
    """System prompt for the eval agent.

    Deliberately minimal. The point of the eval is to measure what an
    agent does WITHOUT hand-holding — instructing it to call
    get_service_fields would defeat the test of catalog uptake. The
    extra parameter lets a scenario inject scenario-specific framing
    (e.g. 'You are estimating a production workload') but should not
    instruct on tool sequencing.
    """
    base = (
        'You are an AWS pricing analyst. The user wants an AWS Pricing '
        'Calculator estimate. Use the tools available to build it and '
        'return a shareable URL.\n\n'
        'The user is unavailable for follow-up — make reasonable '
        'assumptions about any magnitudes or configuration the prompt '
        'leaves unspecified, and proceed. Do not ask clarifying '
        'questions.\n\n'
        'When done, write a one-line summary of what you built and stop.'
    )
    if extra:
        return base + '\n\n' + extra
    return base


def run_llm_scenario(
    scenario: dict,
    *,
    model_id: str | None = None,
    region: str = 'us-east-1',
    max_turns: int | None = None,
    bedrock_client=None,
) -> TraceResult:
    """Drive an LLM scenario: prompt → tool calls → final answer.

    Scenario shape:
        id: <slug>
        prompt: <natural-language user message>
        model: <optional Bedrock inference-profile id; overrides default>
        system_extra: <optional additional system framing>
        max_turns: <optional override>

    Model selection precedence: explicit model_id arg > scenario['model']
    > DEFAULT_MODEL_ID. Lets the runner ask "does Sonnet 4.5 (production)
    behave the same as Haiku 4.5 (cheap eval default) on this prompt?"
    without rewriting every scenario.

    Returns a TraceResult identical in shape to scripted scenarios,
    so predicates.py works unchanged.
    """
    started = time.time()
    resolved_model_id = model_id or scenario.get('model') or DEFAULT_MODEL_ID
    trace = TraceResult(scenario_id=scenario['id'])
    max_t = max_turns or scenario.get('max_turns') or DEFAULT_MAX_TURNS

    if bedrock_client is None:
        bedrock_client = boto3.client('bedrock-runtime', region_name=region)

    system = _build_system_prompt(scenario.get('system_extra'))
    user_prompt = scenario['prompt']

    with MCPStdioClient() as mcp:
        tools = _list_mcp_tools(mcp)
        messages: list[dict] = [{'role': 'user', 'content': user_prompt}]

        for turn in range(max_t):
            try:
                resp = _bedrock_invoke(bedrock_client, resolved_model_id, system,
                                       messages, tools)
            except Exception as e:
                raise LLMDriverError(f'Bedrock invoke failed at turn {turn}: {e}')

            content = resp.get('content', [])
            stop_reason = resp.get('stop_reason')

            # Append the assistant's full content block to the message
            # history (Bedrock requires this for the next call to
            # reference tool_use ids).
            messages.append({'role': 'assistant', 'content': content})

            # Capture text content blocks for reasoning analysis. The
            # model alternates text and tool_use; text often contains
            # the rationale for the upcoming tool call.
            for block in content:
                if block.get('type') == 'text':
                    text_value = block.get('text', '').strip()
                    if text_value:
                        trace.assistant_messages.append(text_value)

            tool_use_blocks = [b for b in content if b.get('type') == 'tool_use']
            if not tool_use_blocks:
                # Agent stopped without calling more tools. End scenario.
                break

            tool_result_blocks = []
            for tu in tool_use_blocks:
                tool_name = tu['name']
                tool_args = tu.get('input', {})
                tool_use_id = tu['id']

                # Some tools (build_estimate / add_service) take a
                # `services` arg that's expected to be a JSON-encoded
                # STRING. The LLM tends to emit it as a structured
                # object. Re-encode if needed.
                if 'services' in tool_args and not isinstance(
                    tool_args['services'], str,
                ):
                    tool_args['services'] = json.dumps(tool_args['services'])

                try:
                    rpc = mcp.call_tool(tool_name, tool_args)
                except Exception as e:
                    text = f'(driver error invoking tool: {e})'
                    rpc = {'result': {'isError': True,
                                      'content': [{'type': 'text', 'text': text}]}}

                text = _extract_text(rpc)
                parsed = parse_text_or_none(text)
                is_error = bool(rpc.get('result', {}).get('isError'))

                trace.calls.append(CallRecord(
                    tool=tool_name, args=tool_args,
                    is_error=is_error, text=text, parsed=parsed,
                ))

                if not is_error and not trace.final_url:
                    trace.final_url = _extract_url(text, parsed)

                tool_result_blocks.append({
                    'type': 'tool_result',
                    'tool_use_id': tool_use_id,
                    'content': text,
                    'is_error': is_error,
                })

            messages.append({'role': 'user', 'content': tool_result_blocks})

            if stop_reason == 'end_turn':
                # Agent indicated done at this turn. Some Haiku turns
                # signal end_turn even with tool_use blocks present;
                # break only if there were no further tools to call.
                if not tool_use_blocks:
                    break

        trace.events = mcp.stderr_events()

    trace.duration_ms = int((time.time() - started) * 1000)
    return trace
