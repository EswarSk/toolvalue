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
  --blind-cases 10 \
  --trials 3 \
  --json .toolvalue/live-openrouter-report.json \
  --store .toolvalue/live-openrouter.db
```

The benchmark contains 15 curated papers spanning computing, biology, physics,
and medicine. For ten sampled papers, expect exactly 40 external source
requests: four in each baseline and zero in counterfactuals. Expect 130 GPT
Researcher writer runs: ten baselines plus
`10 papers × 4 omitted sources × 3 trials`.

The CLI rejects invalid baselines instead of manufacturing a ranking. A valid
baseline must answer all three fields exactly and call every source exactly
once. Invalid counterfactuals reduce attribution coverage and are excluded from
quality deltas.

## Live result

The larger blind run used seed `4567280523530631214` with public APIs, GPT
Researcher's real publisher, and `openai/gpt-4o-mini` through OpenRouter:

| Check | Observed |
|---|---:|
| Exact baseline answers | 10 / 10 |
| Attribution-eligible baselines | 10 / 10 |
| Replay integrity | 100% |
| Attribution coverage | 100% |
| Reliable source estimates | 4 / 4 |
| Public source executions | 40 / 40 expected |
| Counterfactual source executions | 0 |
| GPT Researcher writer runs | 130 / 130 expected |
| GPT Researcher reported cost | 0.011771 credits |

| Omitted source | Mean answer-quality delta | Useful cases | Interpretation for this sample |
|---|---:|---:|---|
| Crossref | +3.3% | 1 / 10 | Its corroboration resolved one first-author conflict |
| OpenCitations | +3.3% | 1 / 10 | It uniquely supplied the BERT title |
| OpenAlex | 0.0% | 0 / 10 | Remaining sources recovered the same gold answers |
| Europe PMC | 0.0% | 0 / 10 | Remaining sources recovered the same gold answers |

OpenCitations was essential for the BERT case: the other three APIs did not
supply its title, so all three omissions reduced that answer from 3/3 to 2/3
correct fields. Crossref mattered for the CRISPR paper's author spelling. It
corroborated OpenCitations' `Martin Jinek` against OpenAlex's `Martin Jínek` and
Europe PMC's `Jinek M`; removing Crossref lost the exact author field in all
three trials.

The result is still conditional rather than universal. Crossref and
OpenCitations were useful in 10% of cases; OpenAlex and Europe PMC were fully
redundant under these leave-one-out tests. The 95% intervals for the two
positive mean effects include zero, so this is not yet statistical evidence
for a global retrieval-policy change. Europe PMC was also the slowest source
in this run at roughly 973 ms on average, making it the strongest candidate for
a larger conditional-skip experiment.

## Test

```bash
.venv/bin/python -m unittest discover -s tests -v
```

The tests execute the pinned GPT Researcher import, ToolValue annotations,
blind-case generator, validity gate, strict replay, and deterministic
source-value fixture. They do not make a paid request unless
`OPENROUTER_API_KEY` is explicitly supplied to a real CLI run.
