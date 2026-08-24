# ToolValue × GPT Researcher

This sample measures the marginal value of research sources inside the real
[`assafelovic/gpt-researcher`](https://github.com/assafelovic/gpt-researcher)
publisher. GPT Researcher had approximately 29,000 GitHub stars when this
integration was built on August 24, 2026.

The task is deliberately objective: given only a DOI, reconcile a paper's
exact title, peer-reviewed publication year, and full first-author name. Four
independently maintained public APIs provide competing or incomplete records:

- Crossref;
- OpenAlex;
- OpenCitations Meta;
- Europe PMC.

ToolValue scores exact fields against held-out labels. It does not ask an LLM
to judge the LLM.

## Why controlled source-review mode

The integration constructs the upstream `GPTResearcher` class and calls its
`write_report` publisher with static source context. GPT Researcher performs
the real OpenRouter-backed reconciliation and JSON synthesis, but ToolValue
owns the four source calls.

This boundary is intentional. If an autonomous search planner changes its
queries after a tool disappears, the counterfactual no longer contains the
same evidence minus one source. Static source-review mode isolates the question
we want to answer: **did this source's recorded output improve the final
answer?**

```mermaid
sequenceDiagram
    participant Eval as Blind evaluation
    participant TV as ToolValue
    participant APIs as 4 public source APIs
    participant GPTR as GPT Researcher publisher

    Eval->>TV: DOI + hidden gold metadata
    TV->>APIs: Fetch all four sources once
    APIs-->>TV: Frozen source records
    TV->>GPTR: Reconcile all records
    GPTR-->>TV: Baseline JSON answer
    loop Each source × three trials
        TV->>TV: Replay other frozen records; omit one
        TV->>GPTR: Reconcile reduced evidence
        GPTR-->>TV: Counterfactual JSON answer
    end
    TV->>TV: Exact-field score deltas
```

The integration points are lightweight annotations in
[`agent.py`](src/gpt_researcher_profiler/agent.py):

```python
@tool(name="crossref")
async def crossref(doi: str): ...

@model(name="gpt_researcher_writer", cost=lambda output: output.reported_cost)
async def synthesize(question: str, records: list[dict]): ...

@profile(task="gpt_researcher_scholarly_source_review", scorer=score_answer,
         validator=validate_research_run)
async def research(doi: str): ...
```

## Install

Python 3.12 or newer is required:

```bash
cd gpt-researcher-sample
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

Add your key only to the ignored local `.env` file:

```dotenv
OPENROUTER_API_KEY=your-key-here
OPENROUTER_MODEL=openai/gpt-4o-mini
```

The dependency is pinned to upstream commit
[`6f998577`](https://github.com/assafelovic/gpt-researcher/commit/6f998577d547b1e54ec662dac63583aa11e3b84b).
The published `gpt-researcher==0.16.0` package placed several typing imports
after their first use and failed during import on Python 3.12; the pinned
upstream commit contains the import-order fix. No GPT Researcher source is
vendored or patched in this repository. That commit's Python package metadata
reports version `0.14.7`, so the CLI displays both that version and the pinned
commit documented here.

## Run without an LLM

Use the scripted consensus writer to verify the public APIs, annotations,
replay, scorer, and request-count invariants for free:

```bash
.venv/bin/profile-gpt-researcher \
  --backend scripted \
  --sources public \
  --limit 5 \
  --trials 1
```

This mode is an integration check, not evidence that GPT Researcher ran.

## Run the real blind experiment

Omit `--blind-seed` to select a new unpredictable subset. The answers are
revealed only after the profile finishes:

```bash
.venv/bin/profile-gpt-researcher \
  --backend gpt-researcher \
  --sources public \
  --blind-cases 3 \
  --trials 3 \
  --json .toolvalue/live-openrouter-report.json \
  --store .toolvalue/live-openrouter.db
```

For three papers, expect exactly 12 external source requests: four in each
baseline and zero in counterfactuals. Expect 39 GPT Researcher writer runs:
three baselines plus `3 papers × 4 omitted sources × 3 trials`.

The CLI rejects invalid baselines instead of manufacturing a ranking. A valid
baseline must answer all three fields exactly and call every source exactly
once. Invalid counterfactuals reduce attribution coverage and are excluded from
quality deltas.

## Live result

The first completed blind run used seed `6520464970306572530` with public APIs,
GPT Researcher's real publisher, and `openai/gpt-4o-mini` through OpenRouter:

| Check | Observed |
|---|---:|
| Exact baseline answers | 3 / 3 |
| Attribution-eligible baselines | 3 / 3 |
| Replay integrity | 100% |
| Attribution coverage | 100% |
| Reliable source estimates | 4 / 4 |
| Public source executions | 12 / 12 expected |
| GPT Researcher writer runs | 39 / 39 expected |
| GPT Researcher reported cost | 0.003607 credits |

| Omitted source | Mean answer-quality delta | Useful cases | Interpretation for this sample |
|---|---:|---:|---|
| Crossref | +11.1% | 1 / 3 | It preserved the exact first-author form in one conflict |
| OpenAlex | 0.0% | 0 / 3 | Remaining sources recovered the same gold answers |
| OpenCitations | 0.0% | 0 / 3 | Remaining sources recovered the same gold answers |
| Europe PMC | 0.0% | 0 / 3 | Remaining sources recovered the same gold answers |

The Crossref effect came from the Piwowar paper. Crossref supplied the exact
gold form `Heather A. Piwowar`; OpenAlex and OpenCitations supplied
`Heather Piwowar`, while Europe PMC supplied `Piwowar HA`. With Crossref
removed, GPT Researcher chose a non-gold author form in all three trials,
reducing that case from 3/3 to 2/3 correct fields.

The conclusion is conditional, not universal: for these three DOI lookups,
three source calls were redundant under leave-one-out evaluation. The sample
is intentionally small, so use more blind cases before changing a production
retrieval policy.

## Test

```bash
.venv/bin/python -m unittest discover -s tests -v
```

The tests execute the pinned GPT Researcher import, ToolValue annotations,
blind-case generator, validity gate, strict replay, and deterministic
source-value fixture. They do not make a paid request unless
`OPENROUTER_API_KEY` is explicitly supplied to a real CLI run.
