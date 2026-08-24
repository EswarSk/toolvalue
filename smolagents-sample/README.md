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

## Run locally

```bash
cd smolagents-sample
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m smolagents_profiler
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
