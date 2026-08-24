# Live GitHub repository profiler

This is a separate, installable sample application that exercises ToolValue
end to end against the public GitHub REST API. It uses four real, read-only
evidence tools:

1. repository metadata;
2. README content;
3. repository topics;
4. language breakdown.

It requires no paid API and no AI model. A deterministic classifier is placed
behind `@model` because that annotation marks a decision boundary that must
rerun—not necessarily an LLM.

## Measured public-API run

The following results were observed on August 24, 2026 with `GITHUB_TOKEN`
explicitly unset:

| Repository | Predicted | Expected | Score |
|---|---|---|---:|
| `django/django` | Web framework | Web framework | 99.8% |
| `facebook/react` | UI library | UI library | 99.8% |
| `hashicorp/terraform` | Infrastructure as code | Infrastructure as code | 99.2% |
| `microsoft/playwright` | Testing | Testing | 99.8% |
| `prometheus/prometheus` | Observability | Observability | 99.8% |
| `kubernetes/kubernetes` | Container orchestration | Container orchestration | 99.2% |

| Evidence tool | Mean quality delta | Useful rate | Mean latency |
|---|---:|---:|---:|
| Repository metadata | +3.10% | 100% | 373 ms |
| README | +3.03% | 100% | 337 ms |
| Topics | +2.73% | 100% | 384 ms |
| Languages | 0.00% | 0% | 280 ms |

Run summary:

- six of six classifications matched their labels;
- aggregate baseline quality was 99.6%;
- replay integrity was 100%;
- 24 network requests were observed, exactly four baselines per case;
- zero network requests were made by counterfactual replays;
- 30 decision runs were observed: six baselines plus 24 ablations.

For this evaluation, language breakdown was a clear conditional-skip candidate:
it averaged 280 ms but contributed no measured quality. Repository data and API
latency can change, so current reruns may differ.

## How the score is produced

ToolValue does not create the score. This sample contains labeled expected
categories and supplies a deterministic scorer:

```python
accuracy = float(output["category"] == expected)
overall = 0.85 * accuracy + 0.15 * output["confidence"]
```

Confidence is derived from the number of independent evidence sources that
contain category-specific keywords. During each ablation, one source becomes
`ToolUnavailable`, the classifier reruns, and the same scorer evaluates the new
output. The reported tool value is:

```text
baseline score - counterfactual score without that tool
```

The roughly 3% deltas in this demonstration primarily reflect reduced
evidence-backed confidence, not incorrect counterfactual labels. The sample is
intended to validate profiling mechanics; a production integration should use
its own ground-truth dataset and task-relevant evaluator.

## Run it

From this directory:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
env -u GITHUB_TOKEN .venv/bin/python -m live_repo_profiler --limit 6
```

The final command deliberately demonstrates the unauthenticated public API. It
is rate limited. To use a higher limit, expose a read-only token only in your
shell:

```bash
export GITHUB_TOKEN="your-token"
.venv/bin/python -m live_repo_profiler --limit 6
```

Never commit the token or paste it into reports. The sample reads it from the
environment and does not persist it.

The command writes content-free artifacts by default:

- `.toolvalue/report.json` — aggregate metrics and content-free run details;
- `.toolvalue/profiles.db` — SQLite metadata and hashes for each case.

Useful options:

```bash
.venv/bin/python -m live_repo_profiler --limit 2
.venv/bin/python -m live_repo_profiler --request-cost-usd 0.001
.venv/bin/python -m live_repo_profiler --help
```

`--request-cost-usd` assigns an internal accounting cost to each request.
GitHub's public REST API does not charge per request.

## Replay invariant

There are four tool groups. For `N` cases, a correct run makes exactly `4 × N`
network requests—the baselines only. It executes the decision boundary `5 × N`
times: one baseline plus four leave-one-tool-out counterfactuals. The CLI prints
both counts and exits nonzero if they do not match.

## Project layout

```text
sample-project/
├── pyproject.toml
├── requirements.txt
├── src/live_repo_profiler/
│   ├── agent.py       # @tool, @model, @profile, and scorer integration
│   ├── client.py      # dependency-free public GitHub REST client
│   ├── dataset.py     # six labeled evaluation cases
│   └── __main__.py    # CLI, report output, and invariant checks
└── tests/test_e2e.py  # offline full-stack replay test
```

The client is injected into `build_agent`, so the offline test replaces only
the network seam while still exercising the real decorators, replay engine,
scoring, aggregation, and SQLite storage.

## Test it offline

```bash
.venv/bin/python -m unittest discover -s tests -v
```

The test expects two cases to make eight client calls and ten decision runs,
with four complete counterfactuals per case. No network access is required.

## Replace the deterministic decision with an LLM

Keep the four `@tool` functions unchanged and replace the body of the
`@model(name="repository_classifier")` function in `agent.py` with the desired
provider call. Assign its actual per-call cost through the decorator. ToolValue
will continue to freeze GitHub evidence while rerunning the model for each
ablation.
