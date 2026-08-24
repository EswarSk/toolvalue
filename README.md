# ToolValue

ToolValue is a small Python library that answers one question production traces cannot:

> Which agent tools materially improve output quality relative to their cost?

It wraps an existing agent function, records its tool results, freezes that evidence, replays the same function with one tool removed at a time, and aggregates the resulting score deltas.

```python
from toolvalue import EvalCase, ToolUnavailable, profile, tool

@tool(cost=0.002, group="web")
async def homepage(business):
    return await browser.fetch(business.url)

@tool(cost=0.007, group="reviews")
async def reviews(business):
    return await directory.reviews(business.name)

def accuracy(result, expected):
    return 1.0 if result["industry"] == expected else 0.0

@profile(task="industry_classification", scorer=accuracy)
async def enrich(business):
    home = await homepage(business)
    review_data = await reviews(business)

    if not isinstance(home, ToolUnavailable):
        return classify(home)
    return classify(review_data)
```

The decorated function still behaves normally:

```python
result = await enrich(business)
```

Profile one golden case:

```python
case = await enrich.profile_case(
    business,
    expected={"industry": "Plumbing"},
    metadata={"segment": "trades"},
)
```

Or evaluate a dataset:

```python
report = await enrich.evaluate([
    EvalCase(args=(business,), expected=label, metadata={"segment": segment})
    for business, label, segment in dataset
])

for tool in report.tools:
    print(tool.unit, tool.mean_quality_delta, tool.avg_cost)
```

Segment using dimensions supplied by the application rather than inventing them:

```python
from toolvalue import aggregate_by_metadata

by_segment = aggregate_by_metadata(report.profiles, "segment")
restaurant_reviews = next(
    tool for tool in by_segment["restaurant"].tools
    if tool.unit == "reviews"
)
```

## Why the tool boundary is still required

`@profile(...)` is the task integration. Counterfactual replay also needs visibility into external evidence. Add `@tool(...)` to direct functions, or wrap functions from a centralized registry:

```python
from toolvalue import middleware

registry["search"] = middleware().wrap(
    "search",
    registry["search"],
    cost=0.001,
)
```

A task decorator alone cannot safely replay data it never observed. ToolValue deliberately does not own the agent runtime, model provider, or tool registry.

## Strict replay

Counterfactual runs never access new external data. A baseline call is keyed by tool name and normalized arguments. During replay:

- matching calls return a frozen copy of the recorded result;
- the ablated tool returns `ToolUnavailable(reason="counterfactual_ablation")`;
- an unseen non-ablated call marks that counterfactual `diverged`;
- `replay_policy="never"` prevents side-effecting tools from being replayed.

This preserves experimental integrity while allowing the agent to reason again after evidence is removed.

## Install and run the demo

```bash
python -m pip install -e .
toolvalue demo --json .toolvalue/report.json
```

The bundled business-enrichment agent demonstrates segment-dependent value: reviews matter for restaurants, registry and escalation matter for brand/legal mismatches, and reviews are mostly waste for professional services.

```bash
toolvalue analyze .toolvalue/report.json
```

## Data and privacy

The in-process replay needs a transient copy of tool results. `SQLiteStore` persists metadata and hashes by default, not raw arguments, outputs, or expected labels:

```python
from toolvalue import SQLiteStore

store = SQLiteStore(".toolvalue/profiles.db")

@profile(task="industry", scorer=accuracy, store=store)
async def enrich(...):
    ...
```

Pass `capture_content=True` to the store only when local raw-content persistence is appropriate.

## Scope of v0.1

Implemented:

- sync and async `@profile` task boundaries;
- sync and async `@tool` recording;
- frozen result replay with normalized argument hashing;
- standardized ablation sentinel;
- strict divergence detection;
- developer-defined deterministic or async scorers;
- leave-one-tool/group-out experiments;
- quality, cost, latency, useful-rate, harmful-rate, divergence, confidence interval, and value-per-dollar aggregation;
- in-memory and SQLite metadata stores;
- CLI report and an executable business-enrichment demo.

This is explicitly **leave-one-out counterfactual value**, not perfect causal attribution. Redundant and interacting tools require pairwise or Shapley-style analysis in a future version.
