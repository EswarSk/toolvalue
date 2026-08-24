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

function sourceFinding(source: string) {
  if (source === 'open_citations') return 'Only source with the exact BERT title';
  if (source === 'crossref') return 'Resolved the CRISPR author-name conflict';
  if (source === 'europe_pmc') return 'No answer changed; slowest source in this run';
  return 'No answer changed when this source was hidden';
}

function ToolTable({ experiment }: { experiment: ResearchExperiment }) {
  const maximum = Math.max(...experiment.tools.map(tool => tool.meanQualityDelta ?? 0), .001);
  return <article className="panel tool-panel research-tool-panel">
    <div className="panel-head"><div><h3>What changed when each source was hidden?</h3><p>Answer loss means title, year, or author became incorrect</p></div><span className="source-evidence">{experiment.counterfactualTrials} repeats · {experiment.cases} papers</span></div>
    <div className="research-tool-head"><span>Source</span><span>Answer loss</span><span>Changed answer</span><span>Avg wait</span><span>What happened</span></div>
    <div className="research-tool-list">{experiment.tools.map(tool => {
      const value = tool.meanQualityDelta ?? 0;
      return <div className="research-tool-row" key={tool.name}>
        <span><b>{tool.label}</b><small>{value > 0 ? 'Affected a result' : 'Redundant in this sample'}</small></span>
        <span className="research-delta"><i style={{ width: `${Math.max(3, value / maximum * 100)}%` }} /><b>{delta(tool.meanQualityDelta)}</b></span>
        <span>{percent(tool.positiveRate, 0)}<small>{Math.round(tool.positiveRate * tool.independentCases)} of {tool.independentCases} papers</small></span>
        <span>{Math.round(tool.averageLatencyMs)} ms</span>
        <span className="source-finding">{sourceFinding(tool.name)}</span>
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
      <div className="insight-copy"><span className="insight-label">THE RESULT, IN PLAIN ENGLISH</span><h2>All <strong>{experiment.cases} answers were correct.</strong><br />Only <strong>{valuable.length} of {experiment.tools.length} sources</strong> changed an answer.</h2><p>{valuable.map(tool => tool.label).join(' and ')} each protected one correct field. Hiding {redundant.map(tool => tool.label).join(' or ')} did not change any answer in this sample.</p><div className="insight-actions"><button onClick={() => onNavigate('traces')}>See the affected papers <span>→</span></button><button className="link-button" onClick={() => onNavigate('experiments')}>How the test worked</button></div></div>
      <div className="research-proof"><div><span>Papers answered correctly</span><b>{experiment.eligibleCases}/{experiment.cases}</b><small>Exact title, year, and author</small></div><div><span>Sources that changed an answer</span><b>{valuable.length}/{experiment.tools.length}</b><small>Measured by hiding one at a time</small></div><div><span>Live API calls during retests</span><b>0</b><small>Recorded evidence was reused</small></div><div><span>AI reasoning runs</span><b>{experiment.modelRuns}</b><small>10 original + 120 comparisons</small></div></div>
    </section>

    <section className="stats-grid" aria-label="Research profile summary"><article><span>Answer accuracy</span><b>{percent(experiment.baselineQuality)}</b><small className="positive">All gold fields matched</small></article><article><span>Fair comparison</span><b>{percent(experiment.replayIntegrity)}</b><small>Every recorded source replayed correctly</small></article><article><span>Usable comparisons</span><b>{percent(experiment.attributionCoverage)}</b><small>All four source estimates passed checks</small></article><article><span>Total reported model cost</span><b>${experiment.reportedModelCost.toFixed(4)}</b><small>OpenRouter-reported usage</small></article></section>

    <section className="lower-grid"><ToolTable experiment={experiment} />
      <article className="panel recommendation research-recommendation conclusion-card"><div className="recommend-top"><span>CONCLUSION</span><i>TEST, DON'T REMOVE</i></div><h3>Keep the valuable sources. Test a conditional skip for {candidate?.label}.</h3><ul><li><b>Keep Crossref and OpenCitations:</b> each saved one exact answer.</li><li><b>Test {candidate?.label}:</b> it changed no answer and was slowest at {Math.round(candidate?.averageLatencyMs ?? 0)} ms.</li><li><b>Do not remove it globally:</b> ten papers are not enough for a universal rule.</li></ul><div className="conclusion-note">The profiler produces evidence for the next experiment—not an automatic production change.</div><button onClick={() => onNavigate('policies')}>Read the recommendation <span>→</span></button></article>
    </section>
    <section className="method-strip"><div><span>1</span><p><b>Ask</b><small>Find paper metadata</small></p></div><i>→</i><div><span>2</span><p><b>Record</b><small>{experiment.sourceExecutions} source responses</small></p></div><i>→</i><div><span>3</span><p><b>Hide</b><small>One source at a time</small></p></div><i>→</i><div><span>4</span><p><b>Compare</b><small>Did the answer get worse?</small></p></div><em>Real GPT Researcher · no API calls during comparisons</em></section>
  </div>;
}

function Cases({ experiment }: { experiment: ResearchExperiment }) {
  return <div className="page view-page research-page"><div className="view-title"><div><span className="micro-label">BLIND EVALUATION CASES</span><h1>Case evidence</h1><p>Every baseline matched exact title, year, and first author.</p></div><span className="seed-chip">Seed {experiment.blindSeed}</span></div><section className="panel research-cases"><div className="research-case-head"><span>Paper</span><span>Venue</span><span>Baseline</span><span>Source effect</span></div>{experiment.caseResults.map(item => <article key={item.doi}><span><b>{item.title}</b><small>{item.doi} · {item.firstAuthor} · {item.year}</small></span><span>{item.venue}</span><span><i className="pass-dot" />{percent(item.baselineScore, 0)}</span><span>{item.effects.length ? item.effects.map(effect => <em key={effect.source}>{effect.sourceLabel} +{(effect.meanDelta * 100).toFixed(1)}pp · {effect.affectedFields.map(fieldLabel).join(', ')}</em>) : <small>No single-source effect</small>}</span></article>)}</section></div>;
}

function Experiments({ experiment, history }: { experiment: ResearchExperiment; history: ResearchExperiment[] }) {
  const replayRuns = experiment.cases * experiment.tools.length * experiment.counterfactualTrials;
  return <div className="page view-page research-page experiment-story">
    <div className="view-title"><div><span className="micro-label">CONTROLLED COUNTERFACTUAL TEST</span><h1>How we tested four research sources</h1><p>One simple question: does the answer get worse when a source is hidden?</p></div><i className="status-pill">Complete</i></div>
    <section className="experiment-hero panel research-experiment-hero">
      <div className="experiment-copy"><span className="experiment-icon">◎</span><h2>{experiment.cases} blind academic papers</h2><p>GPT Researcher had to return the exact <b>title, publication year, and first author</b>. It could use four public databases, but never saw the correct answer.</p>
        <div className="experiment-sources">{experiment.tools.map(tool => <span key={tool.name}>{tool.label}</span>)}</div>
        <div className="experiment-spec"><span><small>AI AGENT</small><b>GPT Researcher</b></span><span><small>MODEL</small><b>{experiment.modelId}</b></span><span><small>SCORING</small><b>Exact fields, no AI judge</b></span></div>
      </div>
      <div className="experiment-diagram clear-diagram">
        <div><b>1 · ORIGINAL RUN</b><span>{experiment.cases} papers × 4 live sources</span><small>{experiment.sourceExecutions} public API calls</small></div>
        <i>record every response once</i>
        <div className="replay-nodes"><b>2 · HIDE ONE SOURCE</b>{experiment.tools.map(tool => <span key={tool.name}>Without {tool.label}</span>)}</div>
        <strong>3 · REASON AGAIN & COMPARE<br /><small>{replayRuns} controlled comparisons · 0 new API calls</small></strong>
      </div>
    </section>
    <section className="experiment-proof-row"><article><span>Original answers</span><b>{experiment.eligibleCases}/{experiment.cases} correct</b><small>Required before attribution</small></article><article><span>Recorded source calls</span><b>{experiment.sourceExecutions}</b><small>Only during original runs</small></article><article><span>Comparison runs</span><b>{replayRuns}</b><small>Four omissions × three repeats</small></article><article><span>Total AI runs</span><b>{experiment.modelRuns}</b><small>{experiment.cases} original + {replayRuns} comparisons</small></article></section>
    <section className="history panel compact-history"><div className="panel-head"><div><h3>Completed experiments</h3><p>Real GPT Researcher profiles, not dashboard mock data</p></div></div><div className="history-row head"><span>Experiment</span><span>Cases</span><span>Integrity</span><span>Quality</span><span>Cost</span><span>Status</span></div>{history.map(item => <div className="history-row" key={item.id}><span><b>{item.label}</b><small>Seed {item.blindSeed}</small></span><span>{item.cases}</span><span>{percent(item.replayIntegrity)}</span><span>{percent(item.baselineQuality)}</span><span>${item.reportedModelCost.toFixed(5)}</span><span><i className="status-pill">Complete</i></span></div>)}</section>
  </div>;
}

function Policy({ experiment }: { experiment: ResearchExperiment }) {
  const candidate = strongestCandidate(experiment);
  return <div className="page view-page research-page conclusion-story">
    <div className="view-title"><div><span className="micro-label">RESULTS + CONCLUSION</span><h1>What did the profiler learn?</h1><p>The agent was correct—but not every source contributed equally.</p></div><i className="status-pill">Evidence, not automation</i></div>
    <section className="result-summary"><article><span>Correct answers</span><b>{experiment.eligibleCases}/{experiment.cases}</b><small>Exact title, year, and author</small></article><article><span>Sources that mattered</span><b>2/4</b><small>Changed at least one answer</small></article><article><span>Live calls during comparison</span><b>0</b><small>Frozen evidence kept the test fair</small></article></section>
    <section className="result-conclusion-grid">
      <article className="panel source-outcomes"><div className="panel-head"><div><h3>Source-by-source result</h3><p>What happened when each database was hidden</p></div></div>{experiment.tools.map(tool => <div className={`source-outcome ${tool.meanQualityDelta ? 'mattered' : ''}`} key={tool.name}><span><b>{tool.label}</b><small>{sourceFinding(tool.name)}</small></span><strong>{tool.meanQualityDelta ? `${delta(tool.meanQualityDelta)} answer loss` : 'No answer changed'}</strong></div>)}</article>
      <article className="panel decision-card"><span className="decision-kicker">THE DEFENSIBLE CONCLUSION</span><h2>Test a conditional skip for {candidate?.label}. Do not remove it globally.</h2><p>{candidate?.label} changed no answer and was the slowest source at <b>{Math.round(candidate?.averageLatencyMs ?? 0)} ms</b>. That makes it the best next experiment—not proof that it is always unnecessary.</p><div className="decision-steps"><span><i>1</i><b>Keep</b><small>Crossref + OpenCitations</small></span><span><i>2</i><b>Test</b><small>{candidate?.label} skip rule</small></span><span><i>3</i><b>Expand</b><small>More blind papers</small></span></div><footer>ToolValue recommends the next measurement. It never changes production routing automatically.</footer></article>
    </section>
  </div>;
}

function EvalSet({ experiment }: { experiment: ResearchExperiment }) {
  return <div className="page view-page research-page integration-story">
    <div className="view-title"><div><span className="micro-label">FRAMEWORK-INDEPENDENT PYTHON LIBRARY</span><h1>Add profiling with annotations</h1><p>Keep your agent and tools. Mark the three boundaries ToolValue needs to observe.</p></div><span className="source-evidence">pip install toolvalue</span></div>
    <section className="panel annotation-hero">
      <div className="annotation-copy"><span className="integration-kicker">THREE LIGHTWEIGHT ANNOTATIONS</span><h2>Profiling sits on top of your existing Python functions.</h2><p>Your functions behave normally in production. When you run an evaluation, ToolValue records external evidence once and measures what changes when each tool is unavailable.</p>
        <div className="annotation-legend"><div><code>@tool</code><span><b>External evidence</b><small>Record and freeze each API response</small></span></div><div><code>@model</code><span><b>Reasoning boundary</b><small>Rerun with one source hidden</small></span></div><div><code>@profile</code><span><b>Task + scorer</b><small>Coordinate and measure the experiment</small></span></div></div>
      </div>
      <pre className="profile-code"><code><span className="code-muted">from</span> toolvalue <span className="code-muted">import</span> profile, tool, model{`\n\n`}<span className="code-green">@tool</span>(group=<i>"research_sources"</i>){`\n`}<b>def</b> crossref(doi):{`\n`}    <span className="code-muted">return</span> crossref_client.lookup(doi){`\n\n`}<span className="code-blue">@model</span>{`\n`}<b>def</b> write_answer(question, evidence):{`\n`}    <span className="code-muted">return</span> researcher.answer(question, evidence){`\n\n`}<span className="code-highlight">@profile(</span>{`\n`}<span className="code-highlight">    task=</span><i>"paper_metadata"</i>,{`\n`}<span className="code-highlight">    scorer=exact_title_year_author,</span>{`\n`}<span className="code-highlight">)</span>{`\n`}<b>def</b> research_paper(doi):{`\n`}    evidence = [{`\n`}        crossref(doi), openalex(doi),{`\n`}        opencitations(doi), europe_pmc(doi),{`\n`}    ]{`\n`}    <span className="code-muted">return</span> write_answer(<i>"Find title, year, author"</i>, evidence)</code></pre>
    </section>
    <section className="annotation-footer"><span><b>Normal production call</b><code>research_paper(doi)</code></span><i>same function</i><span><b>Evaluation call</b><code>research_paper.profile_case(...)</code></span><em>No agent framework required</em></section>
  </div>;
}

export function ResearchDashboard({ experiment, history, view, onNavigate }: { experiment: ResearchExperiment; history: ResearchExperiment[]; view: DashboardView; onNavigate: (view: DashboardView) => void }) {
  if (view === 'traces') return <Cases experiment={experiment} />;
  if (view === 'experiments') return <Experiments experiment={experiment} history={history} />;
  if (view === 'policies') return <Policy experiment={experiment} />;
  if (view === 'evals') return <EvalSet experiment={experiment} />;
  return <Overview experiment={experiment} onNavigate={onNavigate} />;
}
