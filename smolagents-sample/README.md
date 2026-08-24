# ToolValue × Hugging Face smolagents

This integration runs ToolValue against the real
[`huggingface/smolagents`](https://github.com/huggingface/smolagents)
`ToolCallingAgent`. GitHub showed approximately 29,000 stars when this example
was selected on August 24, 2026. The sample pins the latest stable release at
that time, `smolagents==1.26.0`.

## Why smolagents

We compared several prominent Python agent frameworks on GitHub:

| Project | Approximate stars | Local integration trade-off |
|---|---:|---|
| AutoGen | 60.6k | Famous, but a larger multi-agent runtime for this focused test |
| CrewAI | 57.6k | Famous, but oriented around crews and provider-backed execution |
| LangGraph | 40.4k | Strong graph runtime, with more integration scaffolding |
| smolagents | 29.0k | Small, model-agnostic, native multi-tool loop, no Docker required |

smolagents gives us a recognizable upstream runtime without obscuring the
profiling boundary. This sample uses its genuine `ToolCallingAgent`, `Tool`
classes, messages, action/observation memory, and `final_answer` protocol.

## Problem

The agent triages five service incidents by calling four tools in sequence:

- recent deployment risk;
- error-rate telemetry;
- runbook recommendation;
- on-call engineer lookup.

A deterministic local `Model` subclass drives the calls. This avoids a model
download, API key, nondeterminism, and model-as-judge scoring while preserving
the real smolagents agent loop. ToolValue uses exact-match labels for
`rollback`, `investigate`, or `healthy`.

## Run a real OpenRouter LLM experiment

Install the sample, then add your key to the local `.env` file. Do not paste it
into source code, a command-line flag, chat, or a report:

```bash
cd smolagents-sample
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

```dotenv
# smolagents-sample/.env
OPENROUTER_API_KEY=your-key-here
OPENROUTER_MODEL=openai/gpt-4o-mini
```

The repository contains `.env.example`; the real `.env` is ignored by Git. A
key already exported in the shell takes precedence over the file.

Run one incident first to limit spend:

```bash
.venv/bin/python -m smolagents_profiler \
  --backend openrouter \
  --model openai/gpt-4o-mini \
  --limit 1 \
  --json .toolvalue/openrouter-report.json \
  --store .toolvalue/openrouter-profiles.db
```

`openai/gpt-4o-mini` was available through OpenRouter and advertised support
for both `tools` and `tool_choice` when checked on August 24, 2026. You may set
`OPENROUTER_MODEL` or pass another current tool-capable model with `--model`.
OpenRouter documents its current catalog and tool support through the
[`/api/v1/models`](https://openrouter.ai/api/v1/models) endpoint.

The default OpenRouter limit is one case even if `--limit` is omitted. That one
case creates five complete agent executions: one baseline plus four tool
ablations. With one tool call per turn and a final-answer turn, expect up to 25
paid LLM requests. Check the model's current pricing before increasing the
limit.

### Prove that an LLM actually ran

The command must show all of the following:

```text
Model backend: openrouter (...)
OpenRouter LLM calls:    greater than 0
OpenRouter input tokens: greater than 0
OpenRouter output tokens: greater than 0
OpenRouter reported cost: ... credits
Fixture tool executions: 4 observed / 4 expected (baselines only)
Replay integrity: 100.0%
```

The JSON report repeats the backend, model ID, LLM call count, token counts,
OpenRouter-reported cost, and underlying tool executions under `experiment`.
This is the audit trail that distinguishes the live experiment from the
scripted integration test. OpenRouter returns usage and cost data directly in
each non-streaming response; ToolValue records each response's latency and
reported cost at the `@model` boundary.

The key is never written to SQLite or JSON.

## Run blind scenarios

The fixed incident cases are useful for regression tests but should not be the
only evidence. Blind mode randomly samples unique signal combinations, assigns
opaque service IDs, and computes labels with an independent deterministic
oracle. Only the service ID is passed into the agent. The CLI withholds the
signals and expected labels until the complete profile finishes, then records
the random seed so the run can be reproduced:

```bash
.venv/bin/python -m smolagents_profiler \
  --backend openrouter \
  --blind-cases 5 \
  --json .toolvalue/blind-openrouter-report.json \
  --store .toolvalue/blind-openrouter-profiles.db
```

Use `--blind-seed <number>` only when reproducing an earlier run. Omitting it
creates a new unpredictable seed.

### What the first blind run exposed

The first five-case blind run used seed `7906770189683002919`. It was not a
clean attribution run, and the CLI correctly exited nonzero:

| Check | Observed |
|---|---:|
| Baseline accuracy | 4 / 5 (80%) |
| Replay integrity | 100% |
| Expected baseline tool executions | 20 |
| Actual baseline tool executions | 23 |
| OpenRouter LLM calls | 137 |
| Input / output tokens | 208,485 / 12,000 |
| OpenRouter-reported cost | 0.028230 credits |

The LLM duplicated three baseline tool calls in the failed case. During many
ablations it repeatedly retried the unavailable tool until the smolagents step
limit. Consequently, even the deliberately irrelevant on-call lookup appeared
valuable in three cases. Those percentages must not be interpreted as clean
evidence attribution: they measure the combined effect of missing evidence and
the agent's poor recovery behavior.

This is a useful profiler finding in its own right. A production evaluation
must report execution-policy violations and retry costs alongside quality
deltas, and it should not automatically remove a tool from one blind run.

## Run the deterministic local test

```bash
cd smolagents-sample
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m smolagents_profiler --backend scripted
```

The command writes content-free artifacts to `.toolvalue/report.json` and
`.toolvalue/profiles.db`.

## What this verifies

For five cases with four tool groups:

- the upstream agent should execute fixture tools exactly 20 times—baselines only;
- ToolValue should produce 20 leave-one-out counterfactuals;
- the smolagents decision model should run 125 times across agent steps;
- replay integrity should be 100%;
- the on-call lookup should have zero marginal value for incident classification.

The external tools are local fixtures so the sample is fast and reproducible.
They can be replaced with production clients without changing the ToolValue
annotations.

## Test

```bash
.venv/bin/python -m unittest discover -s tests -v
```

This test executes the actual pinned smolagents package. It does not reimplement
the upstream agent loop or mock the `ToolCallingAgent`.
