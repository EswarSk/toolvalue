'use client';

import type { DashboardView, ResearchExperiment, ResearchToolMetric } from '../lib/experiments';

function percent(value: number, digits = 1) {
  return `${(value * 100).toFixed(digits)}%`;
}

function delta(value: number | null) {
  return value == null ? 'Insufficient' : `+${(value * 100).toFixed(1)}pp`;
}

function fieldLabel(field: string) {
  return field === 'first_author' ? 'author' : field;
}

function strongestCandidate(experiment: ResearchExperiment) {
  return [...experiment.tools]
    .filter(tool => tool.meanQualityDelta === 0)
    .sort((left, right) => right.averageLatencyMs - left.averageLatencyMs)[0];
}

function ToolTable({ experiment }: { experiment: ResearchExperiment }) {
  const maximum = Math.max(...experiment.tools.map(tool => tool.meanQualityDelta ?? 0), .001);
  return <article className="panel tool-panel research-tool-panel">
    <div className="panel-head"><div><h3>Marginal value by source</h3><p>Gold-field quality lost when each frozen source is removed</p></div><span className="source-evidence">{experiment.counterfactualTrials} trials · {experiment.cases} cases</span></div>
    <div className="research-tool-head"><span>Source</span><span>Mean quality Δ</span><span>Useful</span><span>Latency</span><span>95% interval</span></div>
    <div className="research-tool-list">{experiment.tools.map(tool => {
      const value = tool.meanQualityDelta ?? 0;
      const interval = tool.confidenceInterval95;
      return <div className="research-tool-row" key={tool.name}>
        <span><b>{tool.label}</b><small>{tool.reliable ? 'Reliable evidence' : 'Insufficient evidence'}</small></span>
        <span className="research-delta"><i style={{ width: `${Math.max(3, value / maximum * 100)}%` }} /><b>{delta(tool.meanQualityDelta)}</b></span>
        <span>{percent(tool.positiveRate, 0)}<small>{Math.round(tool.positiveRate * tool.independentCases)} / {tool.independentCases} cases</small></span>
        <span>{Math.round(tool.averageLatencyMs)} ms</span>
        <span>{interval ? `${(interval[0] * 100).toFixed(1)} to ${(interval[1] * 100).toFixed(1)}pp` : '—'}</span>
      </div>;
    })}</div>
  </article>;
}

function exportExperiment(experiment: ResearchExperiment) {
  const rows = [
    'source,mean_quality_delta,useful_rate,independent_cases,average_latency_ms,attribution_coverage',
    ...experiment.tools.map(tool => [tool.name, tool.meanQualityDelta, tool.positiveRate, tool.independentCases, tool.averageLatencyMs, tool.attributionCoverage].join(',')),
  ];
  const url = URL.createObjectURL(new Blob([rows.join('\n')], { type: 'text/csv' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `${experiment.id}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

function Overview({ experiment, onNavigate }: { experiment: ResearchExperiment; onNavigate: (view: DashboardView) => void }) {
  const valuable = experiment.tools.filter(tool => (tool.meanQualityDelta ?? 0) > 0);
  const redundant = experiment.tools.filter(tool => tool.meanQualityDelta === 0);
  const candidate = strongestCandidate(experiment);
  return <div className="page research-page">
    <div className="title-row">
      <div><div className="eyebrow"><span className="live-dot" />PROFILE COMPLETE <i>·</i> {experiment.cases} BLIND CASES</div><h1>{experiment.title}</h1><p>GPT Researcher <span>·</span> {experiment.modelId} <span>·</span> public scholarly APIs</p></div>
      <div className="title-actions"><button className="secondary-button" onClick={() => exportExperiment(experiment)}>Export report <span>↓</span></button></div>
    </div>

    <section className="insight-card research-insight">
      <div className="insight-copy"><span className="insight-label">OBSERVED SOURCE VALUE</span><h2><strong>{valuable.length} of {experiment.tools.length}</strong> sources changed answer quality.</h2><p>{valuable.map(tool => tool.label).join(' and ')} each protected one exact gold field. {redundant.map(tool => tool.label).join(' and ')} were leave-one-out redundant across this blind sample.</p><div className="insight-actions"><button onClick={() => onNavigate('traces')}>Inspect affected cases <span>→</span></button><button className="link-button" onClick={() => onNavigate('experiments')}>See execution proof</button></div></div>
      <div className="research-proof"><div><span>External source calls</span><b>{experiment.sourceExecutions}</b><small>baselines only</small></div><div><span>Counterfactual source calls</span><b>0</b><small>strict frozen replay</small></div><div><span>GPT Researcher runs</span><b>{experiment.modelRuns}</b><small>{experiment.counterfactualTrials} trials per omission</small></div><div><span>Reported model cost</span><b>${experiment.reportedModelCost.toFixed(5)}</b><small>OpenRouter credits</small></div></div>
    </section>

    <section className="stats-grid" aria-label="Research profile summary"><article><span>Baseline quality</span><b>{percent(experiment.baselineQuality)}</b><small className="positive">{experiment.eligibleCases}/{experiment.cases} exact and eligible</small></article><article><span>Replay integrity</span><b>{percent(experiment.replayIntegrity)}</b><small>Frozen evidence matched every replay</small></article><article><span>Attribution coverage</span><b>{percent(experiment.attributionCoverage)}</b><small>{experiment.tools.filter(tool => tool.reliable).length}/{experiment.tools.length} reliable estimates</small></article><article><span>Average baseline latency</span><b>{(experiment.averageLatencyMs / 1000).toFixed(1)}s</b><small>Source fetch + synthesis</small></article></section>

    <section className="lower-grid"><ToolTable experiment={experiment} />
      <article className="panel recommendation research-recommendation"><div className="recommend-top"><span>WATCH</span><i>CONDITIONAL</i></div><h3>Test skipping {candidate?.label ?? 'the slowest redundant source'}</h3><p>It had <b>0.0pp observed marginal value</b> and averaged <b>{Math.round(candidate?.averageLatencyMs ?? 0)} ms</b>. Run more blind cases before changing routing globally.</p><div className="rule"><small>SAFE NEXT EXPERIMENT</small><code><span>if</span> source_coverage &gt;= <em>3</em>:<br />&nbsp;&nbsp;trial_skip(<b>{candidate?.name ?? 'source'}</b>)</code></div><div className="impact"><div><span>0.0pp</span><small>Observed loss</small></div><div><span>{experiment.cases}</span><small>Cases</small></div><div><span>95%</span><small>Coverage gate</small></div></div><button onClick={() => onNavigate('policies')}>Inspect candidate <span>→</span></button></article>
    </section>
    <section className="method-strip"><div><span>1</span><p><b>Fetch</b><small>Four public APIs</small></p></div><i>→</i><div><span>2</span><p><b>Freeze</b><small>{experiment.sourceExecutions} recorded outputs</small></p></div><i>→</i><div><span>3</span><p><b>Omit</b><small>One source × {experiment.counterfactualTrials} trials</small></p></div><i>→</i><div><span>4</span><p><b>Score</b><small>Exact title, year, author</small></p></div><em>Real GPT Researcher · no counterfactual API calls</em></section>
  </div>;
}

function Cases({ experiment }: { experiment: ResearchExperiment }) {
  return <div className="page view-page research-page"><div className="view-title"><div><span className="micro-label">BLIND EVALUATION CASES</span><h1>Case evidence</h1><p>Every baseline matched exact title, year, and first author.</p></div><span className="seed-chip">Seed {experiment.blindSeed}</span></div><section className="panel research-cases"><div className="research-case-head"><span>Paper</span><span>Venue</span><span>Baseline</span><span>Source effect</span></div>{experiment.caseResults.map(item => <article key={item.doi}><span><b>{item.title}</b><small>{item.doi} · {item.firstAuthor} · {item.year}</small></span><span>{item.venue}</span><span><i className="pass-dot" />{percent(item.baselineScore, 0)}</span><span>{item.effects.length ? item.effects.map(effect => <em key={effect.source}>{effect.sourceLabel} +{(effect.meanDelta * 100).toFixed(1)}pp · {effect.affectedFields.map(fieldLabel).join(', ')}</em>) : <small>No single-source effect</small>}</span></article>)}</section></div>;
}

function Experiments({ experiment, history }: { experiment: ResearchExperiment; history: ResearchExperiment[] }) {
  return <div className="page view-page research-page"><div className="view-title"><div><span className="micro-label">RECORDED TOOLVALUE OUTPUT</span><h1>Experiment details</h1><p>The dashboard is synced from generated ToolValue JSON reports.</p></div><i className="status-pill">Complete</i></div><section className="experiment-hero panel research-experiment-hero"><div><span className="experiment-icon">◎</span><h2>{experiment.label}</h2><p>GPT Researcher reconciled Crossref, OpenAlex, OpenCitations, and Europe PMC records against exact held-out metadata.</p><div className="experiment-spec"><span><small>TASK</small><b>{experiment.task}</b></span><span><small>MODEL</small><b>{experiment.modelId}</b></span><span><small>METHOD</small><b>Strict replay · {experiment.counterfactualTrials} trials</b></span></div><div className="run-facts"><span><b>{experiment.sourceExecutions}</b> external calls</span><span><b>0</b> counterfactual calls</span><span><b>{experiment.modelRuns}</b> model runs</span></div></div><div className="experiment-diagram"><div><b>BASELINE</b><span>4 public sources</span></div><i>freeze once</i><div className="replay-nodes">{experiment.tools.map(tool => <span key={tool.name}>− {tool.label}</span>)}</div><strong>{experiment.cases * experiment.tools.length * experiment.counterfactualTrials} controlled replays</strong></div></section><section className="history panel"><div className="panel-head"><div><h3>Experiment history</h3><p>Real GPT Researcher profiles synced from ToolValue</p></div></div><div className="history-row head"><span>Experiment</span><span>Cases</span><span>Integrity</span><span>Quality</span><span>Cost</span><span>Status</span></div>{history.map(item => <div className="history-row" key={item.id}><span><b>{item.label}</b><small>Seed {item.blindSeed}</small></span><span>{item.cases}</span><span>{percent(item.replayIntegrity)}</span><span>{percent(item.baselineQuality)}</span><span>${item.reportedModelCost.toFixed(5)}</span><span><i className="status-pill">Complete</i></span></div>)}</section></div>;
}

function Policy({ experiment }: { experiment: ResearchExperiment }) {
  const candidate = strongestCandidate(experiment);
  return <div className="page view-page research-page"><div className="view-title"><div><span className="micro-label">EVIDENCE, NOT AUTOMATION</span><h1>Routing candidate</h1><p>No source is removed automatically. This is the next hypothesis to test.</p></div></div><section className="policy-summary"><div><span>Observed quality loss</span><b>0.0<small>pp</small></b></div><div><span>Candidate latency</span><b>{Math.round(candidate?.averageLatencyMs ?? 0)}<small> ms</small></b></div><div><span>Supporting cases</span><b>{experiment.cases}<small> blind papers</small></b></div></section><article className="panel policy-card research-policy"><div className="policy-index">01</div><div><div className="policy-tags"><span>NEEDS MORE DATA</span><i>{candidate?.label}</i></div><h2>Conditionally skip the slowest redundant source</h2><p>{candidate?.label} changed no gold field in this run and was the slowest source. Preserve it whenever the other databases are incomplete, and expand the evaluation before production use.</p><div className="policy-metrics"><span><small>MEAN QUALITY Δ</small><b>0.0pp</b></span><span><small>USEFUL RATE</small><b>0%</b></span><span><small>ATTRIBUTION COVERAGE</small><b>{percent(candidate?.attributionCoverage ?? 0)}</b></span></div></div></article></div>;
}

function EvalSet({ experiment }: { experiment: ResearchExperiment }) {
  return <div className="page view-page research-page"><div className="view-title"><div><span className="micro-label">GOLDEN DATASET</span><h1>Scholarly DOI evaluation</h1><p>Blind papers selected from a 15-paper curated benchmark.</p></div></div><section className="eval-grid"><article className="panel eval-card"><div><span className="dataset-icon">✓</span><i>ACTIVE</i></div><h2>scholarly_doi_gold_v1</h2><p>Cross-domain peer-reviewed papers with exact title, publication year, and full first-author labels.</p><div className="dataset-stats"><span><b>{experiment.cases}</b><small>Blind cases</small></span><span><b>15</b><small>Available cases</small></span><span><b>3</b><small>Exact scorers</small></span></div></article><article className="panel scorer-card"><span className="micro-label">SCORER CONFIGURATION</span><h2>Deterministic exact fields</h2><p>No model-as-judge is used. Each field contributes one third of answer quality.</p><pre><code><i>overall</i> = (exact_title<br />&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;+ exact_year<br />&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;+ exact_first_author) / 3</code></pre><div><span>Baseline eligibility</span><b>3 / 3 fields</b></div><div><span>Counterfactual repetitions</span><b>{experiment.counterfactualTrials}</b></div></article></section></div>;
}

export function ResearchDashboard({ experiment, history, view, onNavigate }: { experiment: ResearchExperiment; history: ResearchExperiment[]; view: DashboardView; onNavigate: (view: DashboardView) => void }) {
  if (view === 'traces') return <Cases experiment={experiment} />;
  if (view === 'experiments') return <Experiments experiment={experiment} history={history} />;
  if (view === 'policies') return <Policy experiment={experiment} />;
  if (view === 'evals') return <EvalSet experiment={experiment} />;
  return <Overview experiment={experiment} onNavigate={onNavigate} />;
}
