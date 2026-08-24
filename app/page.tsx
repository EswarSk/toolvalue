'use client';

import { useEffect, useMemo, useState } from 'react';
import experimentData from '../data/experiments.json';
import {
  ablate, analyzeProfile, demoCases, formatDelta, formatPercent, segmentLabel, tools,
  type ProfileCase, type Segment, type ToolMetric, type ToolName,
} from '../lib/profiler';
import type { DashboardView, ResearchExperiment } from '../lib/experiments';
import { ResearchDashboard } from './research-dashboard';

type View = DashboardView;
type MetricMode = 'quality' | 'useful' | 'value';

const researchExperiments = experimentData as ResearchExperiment[];

const navigation: { group: string; items: { id: View; label: string; icon: string; count?: string }[] }[] = [
  { group: 'Analyze', items: [
    { id: 'overview', label: 'Overview', icon: '⌁' },
    { id: 'traces', label: 'Traces', icon: '↗', count: '128' },
    { id: 'experiments', label: 'Experiments', icon: '◎' },
  ] },
  { group: 'Optimize', items: [
    { id: 'policies', label: 'Policies', icon: '◇', count: '2' },
    { id: 'evals', label: 'Eval sets', icon: '✓' },
  ] },
];

const segmentOptions: (Segment | 'all')[] = ['all', 'professional_services', 'restaurant', 'trades', 'retail', 'brand_legal_mismatch'];

function Mark() {
  return <div className="mark" aria-label="ToolValue"><span /><span /><span /></div>;
}

function fmtCost(value: number) {
  return `$${value.toFixed(3)}`;
}

function metricValue(tool: ToolMetric, mode: MetricMode) {
  if (mode === 'useful') return `${Math.round(tool.usefulRate * 100)}%`;
  if (mode === 'value') return `${tool.valuePerDollar.toFixed(1)}×`;
  return formatDelta(tool.qualityDelta);
}

function metricWidth(tool: ToolMetric, metrics: ToolMetric[], mode: MetricMode) {
  const values = metrics.map(item => mode === 'useful' ? item.usefulRate : mode === 'value' ? item.valuePerDollar : item.qualityDelta);
  const own = mode === 'useful' ? tool.usefulRate : mode === 'value' ? tool.valuePerDollar : tool.qualityDelta;
  return `${Math.max(3, Math.abs(own) / Math.max(...values.map(Math.abs), 0.001) * 94)}%`;
}

function toolTone(tool: ToolMetric) {
  if (tool.qualityDelta < 0.01 && tool.cost >= 0.005) return 'coral';
  if (tool.qualityDelta >= 0.08) return 'mint';
  return 'blue';
}

function TraceDetail({ item, onClose }: { item: ProfileCase; onClose?: () => void }) {
  const [tool, setTool] = useState<ToolName>('reviews');
  const result = ablate(item, tool);
  return (
    <article className="trace-detail panel">
      <div className="panel-head">
        <div><span className="micro-label">COUNTERFACTUAL LAB</span><h3>{item.business}</h3><p>{item.id} · {segmentLabel(item.segment)}</p></div>
        {onClose && <button className="close-button" onClick={onClose} aria-label="Close trace detail">×</button>}
      </div>
      <div className="trace-outcome">
        <div><small>Expected</small><b>{item.expected}</b></div><span>→</span><div><small>Agent output</small><b>{item.output}</b></div><i>PASS</i>
      </div>
      <div className="ablation-controls">
        <span>Remove one evidence source</span>
        <div className="tool-chips">
          {tools.map(value => <button key={value.name} className={tool === value.name ? 'selected' : ''} onClick={() => setTool(value.name)}>{value.label}</button>)}
        </div>
      </div>
      <div className="comparison-grid">
        <div className="comparison baseline">
          <div><span className="status-dot" /><b>Baseline</b><em>{Math.round(item.baselineScore * 100)} score</em></div>
          <div className="evidence-stack">
            {tools.map(value => <span key={value.name}>{value.label}<i>frozen</i></span>)}
          </div>
          <p>{item.output}</p>
        </div>
        <div className="comparison-arrow"><span>−1</span><small>replay</small></div>
        <div className={`comparison counterfactual ${result.diverged ? 'diverged' : ''}`}>
          <div><span className="status-dot" /><b>Without {tools.find(value => value.name === tool)?.label}</b><em>{result.diverged ? 'diverged' : `${Math.round(result.counterfactualScore * 100)} score`}</em></div>
          <div className="evidence-stack">
            {tools.map(value => <span key={value.name} className={value.name === tool ? 'ablated' : ''}>{value.label}<i>{value.name === tool ? 'ablated' : 'replayed'}</i></span>)}
          </div>
          <p>{result.diverged ? 'REPLAY_DIVERGED' : result.delta > 0.08 ? 'Broader / less certain classification' : item.output}</p>
        </div>
      </div>
      <div className={`delta-callout ${result.delta < 0.01 ? 'weak' : ''}`}>
        <span>{result.diverged ? '!' : result.delta < 0.01 ? '≈' : '↓'}</span>
        <p><b>{result.diverged ? 'Experimental integrity protected' : `${formatDelta(result.delta)} leave-one-out value`}</b><small>{result.diverged ? 'The agent requested unseen evidence, so the replay was stopped.' : result.delta < 0.01 ? 'Removing this tool made no material difference.' : 'This evidence materially improved the scored result.'}</small></p>
      </div>
    </article>
  );
}

export default function Home() {
  const [view, setView] = useState<View>('overview');
  const [segment, setSegment] = useState<Segment | 'all'>('all');
  const [metricMode, setMetricMode] = useState<MetricMode>('quality');
  const [selectedTrace, setSelectedTrace] = useState<ProfileCase>(demoCases[0]);
  const [drawer, setDrawer] = useState<'policy' | 'experiment' | null>(null);
  const [runState, setRunState] = useState<'idle' | 'running' | 'complete'>('idle');
  const [profileVersion, setProfileVersion] = useState(4);
  const [activeExperimentId, setActiveExperimentId] = useState(researchExperiments[0]?.id ?? 'industry-demo');
  const profile = useMemo(() => analyzeProfile(demoCases, segment), [segment, profileVersion]);
  const activeResearch = researchExperiments.find(item => item.id === activeExperimentId);
  const activeTitle = activeResearch?.title ?? 'Industry classification';

  useEffect(() => {
    if (runState !== 'running') return;
    const timer = window.setTimeout(() => {
      setRunState('complete');
      setProfileVersion(version => version + 1);
    }, 2200);
    return () => window.clearTimeout(timer);
  }, [runState]);

  function navigate(next: View) {
    setView(next);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function selectExperiment(id: string) {
    setActiveExperimentId(id);
    setDrawer(null);
    setView('overview');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function navigationCount(item: { id: View; count?: string }) {
    if (!activeResearch) return item.count;
    if (item.id === 'traces') return String(activeResearch.cases);
    if (item.id === 'policies') return '1';
    return undefined;
  }

  function navigationLabel(item: { id: View; label: string }) {
    if (!activeResearch) return item.label;
    if (item.id === 'traces') return 'Cases';
    if (item.id === 'policies') return 'Conclusion';
    if (item.id === 'evals') return 'Integration';
    return item.label;
  }

  function startExperiment() {
    setRunState('running');
    setDrawer('experiment');
  }

  function exportReport() {
    const rows = ['tool,quality_delta,useful_rate,cost,value_per_dollar', ...profile.metrics.map(tool => `${tool.name},${tool.qualityDelta},${tool.usefulRate},${tool.cost},${tool.valuePerDollar}`)];
    const url = URL.createObjectURL(new Blob([rows.join('\n')], { type: 'text/csv' }));
    const link = document.createElement('a');
    link.href = url; link.download = 'toolvalue-industry-classification.csv'; link.click(); URL.revokeObjectURL(url);
  }

  return (
    <main className="shell">
      <aside className="sidebar">
        <button className="brand" onClick={() => navigate('overview')}><Mark /><span>toolvalue</span><i>beta</i></button>
        <div className="workspace">
          <span className="workspace-avatar">T</span>
          <span><b>ToolValue</b><small>{activeResearch ? 'Live experiment dashboard' : 'Demo workspace'}</small></span>
          <i>⌄</i>
        </div>
        <nav aria-label="Product navigation">
          {navigation.map(group => <div key={group.group}><p>{group.group}</p>{group.items.map(item => (
            <button key={item.id} className={view === item.id ? 'active' : ''} onClick={() => navigate(item.id)}><span>{item.icon}</span>{navigationLabel(item)}{navigationCount(item) && <em>{navigationCount(item)}</em>}</button>
          ))}</div>)}
        </nav>
        <div className="sidebar-bottom">
          <button onClick={() => navigate('evals')}><span>?</span> Documentation</button>
          <div className="user"><span>EV</span><b>Eswara Vegi<small>Developer</small></b><i>•••</i></div>
        </div>
      </aside>

      <section className="content">
        <header className="topbar">
          <div className="breadcrumbs"><span>{activeTitle}</span><i>/</i><b>{navigationLabel(navigation.flatMap(group => group.items).find(item => item.id === view) ?? { id: view, label: view })}</b></div>
          <label className="mobile-view-switcher"><span>View</span><select aria-label="Select dashboard view" value={view} onChange={event => navigate(event.target.value as View)}>{navigation.flatMap(group => group.items).map(item => <option value={item.id} key={item.id}>{navigationLabel(item)}</option>)}</select></label>
          <div className="top-actions"><label className="experiment-switcher"><span>Experiment</span><select aria-label="Select dashboard experiment" value={activeExperimentId} onChange={event => selectExperiment(event.target.value)}>{researchExperiments.map(item => <option value={item.id} key={item.id}>{item.label}</option>)}<option value="industry-demo">Industry classification · demo</option></select></label><button className="icon-button" aria-label="Notifications">●</button>{activeResearch ? <button className="run-button" onClick={() => navigate('experiments')}>View run <span>↗</span></button> : <button className="run-button" onClick={startExperiment}>Run experiment <span>R</span></button>}</div>
        </header>

        {activeResearch ? <ResearchDashboard experiment={activeResearch} history={researchExperiments} view={view} onNavigate={navigate} /> : <>
        {view === 'overview' && <div className="page">
          <div className="title-row">
            <div><div className="eyebrow"><span className="live-dot" />PROFILE COMPLETE <i>·</i> {profile.cases.length} CASES</div><h1>Industry classification</h1><p>Leave-one-out value profile <span>·</span> v1.{profileVersion} <span>·</span> Updated just now</p></div>
            <div className="title-actions"><label><span>Segment</span><select value={segment} onChange={event => setSegment(event.target.value as Segment | 'all')}>{segmentOptions.map(option => <option value={option} key={option}>{segmentLabel(option)}</option>)}</select></label><button className="secondary-button" onClick={exportReport}>Export report <span>↓</span></button></div>
          </div>

          <section className="insight-card">
            <div className="insight-copy"><span className="insight-label">OPTIMIZATION FOUND</span><h2>Cut tool spend by <strong>24.8%</strong><br />while preserving <strong>99.2%</strong> of quality.</h2><p>Reviews and strong-model escalation account for 31% of run cost, but materially improve only 6% of cases.</p><div className="insight-actions"><button onClick={() => setDrawer('policy')}>Review policy <span>→</span></button><button className="link-button" onClick={() => document.getElementById('evidence')?.scrollIntoView({ behavior: 'smooth' })}>See the evidence</button></div></div>
            <div className="savings-visual" aria-label="Projected cost reduction from 2.7 cents to 2 cents per run"><div className="savings-head"><span>Cost / successful run</span><b>−24.8%</b></div><div className="cost-row"><span>Current</span><div className="cost-track"><i className="current-cost" /></div><strong>$0.027</strong></div><div className="cost-row"><span>Proposed</span><div className="cost-track"><i className="proposed-cost" /></div><strong>$0.020</strong></div><div className="quality-note"><span>✓</span><p><b>Quality guardrail passed</b><small>{formatPercent(profile.baselineQuality)} → {formatPercent(profile.baselineQuality * .992)} expected quality</small></p></div></div>
          </section>

          <section className="stats-grid" aria-label="Profile summary"><article><span>Baseline quality</span><b>{formatPercent(profile.baselineQuality)}</b><small className="positive">↑ 2.3pp vs. v1.3</small></article><article><span>Average run cost</span><b>{fmtCost(profile.avgCost)}</b><small>Across {profile.cases.length} eval cases</small></article><article><span>P95 latency</span><b>{(profile.p95Latency / 1000).toFixed(1)}s</b><small className="positive">↓ 0.7s from last run</small></article><article><span>Replay integrity</span><b>{formatPercent(profile.replayIntegrity)}</b><small>{profile.cases.length - Math.round(profile.cases.length * profile.replayIntegrity)} diverged experiments</small></article></section>

          <section className="lower-grid" id="evidence">
            <article className="panel tool-panel">
              <div className="panel-head"><div><h3>Marginal value by tool</h3><p>{segmentLabel(segment)} · {metricMode === 'quality' ? 'quality lost when each tool is removed' : metricMode === 'useful' ? 'share of runs with ≥1pp benefit' : 'quality delta per dollar spent'}</p></div><div className="segmented-control"><button className={metricMode === 'quality' ? 'selected' : ''} onClick={() => setMetricMode('quality')}>Quality Δ</button><button className={metricMode === 'useful' ? 'selected' : ''} onClick={() => setMetricMode('useful')}>Useful</button><button className={metricMode === 'value' ? 'selected' : ''} onClick={() => setMetricMode('value')}>Value / $</button></div></div>
              <div className="tool-list dynamic-bars">{profile.metrics.map(tool => <button className="tool-row" key={tool.name} onClick={() => { setSelectedTrace(profile.cases.find(item => Math.abs(item.losses[tool.name] - tool.qualityDelta) < .03) ?? profile.cases[0]); setView('traces'); }}><span>{tool.label}</span><div className="bar-track"><i className={`bar ${toolTone(tool)}`} style={{ width: metricWidth(tool, profile.metrics, metricMode) }} /></div><b>{metricValue(tool, metricMode)}</b><small>{fmtCost(tool.cost)}</small></button>)}</div>
              <div className="legend"><span><i className="legend-mint" /> Essential</span><span><i className="legend-blue" /> Useful</span><span><i className="legend-coral" /> Optimization candidate</span><em>Avg. cost</em></div>
            </article>
            <article className="panel recommendation"><div className="recommend-top"><span>01</span><i>HIGH CONFIDENCE</i></div><h3>Skip reviews for professional services</h3><p>Reviews cost <b>$0.007/run</b> and change the correct answer in just <b>2.1%</b> of this segment.</p><div className="rule"><small>RECOMMENDED ROUTING RULE</small><code><span>if</span> segment == <em>"professional_services"</em>:<br />&nbsp;&nbsp;skip(<b>reviews</b>)</code></div><div className="impact"><div><span>−19.4%</span><small>Cost</small></div><div><span>−0.1pp</span><small>Quality</small></div><div><span>38</span><small>Cases</small></div></div><button onClick={() => setDrawer('policy')}>Inspect recommendation <span>→</span></button></article>
          </section>

          <section className="method-strip"><div><span>1</span><p><b>Record</b><small>Freeze tool outputs</small></p></div><i>→</i><div><span>2</span><p><b>Replay</b><small>Reuse exact evidence</small></p></div><i>→</i><div><span>3</span><p><b>Ablate</b><small>Remove one source</small></p></div><i>→</i><div><span>4</span><p><b>Measure</b><small>Compare score delta</small></p></div><em>Strict replay · no new external data</em></section>
        </div>}

        {view === 'traces' && <div className="page view-page">
          <div className="view-title"><div><span className="micro-label">RECORDED EVIDENCE</span><h1>Trace explorer</h1><p>Inspect baseline runs and replay any one without a selected tool.</p></div><div className="trace-search">⌕ <input aria-label="Search traces" placeholder="Search businesses…" /></div></div>
          <div className="trace-layout"><article className="panel trace-table"><div className="table-head"><span>Business</span><span>Segment</span><span>Score</span><span>Cost</span></div>{demoCases.slice(0, 12).map(item => <button key={item.id} className={selectedTrace.id === item.id ? 'selected' : ''} onClick={() => setSelectedTrace(item)}><span><b>{item.business}</b><small>{item.id}</small></span><span>{segmentLabel(item.segment)}</span><span><i className="pass-dot" />{Math.round(item.baselineScore * 100)}</span><span>$0.027</span></button>)}</article><TraceDetail item={selectedTrace} /></div>
        </div>}

        {view === 'experiments' && <div className="page view-page">
          <div className="view-title"><div><span className="micro-label">EVALUATION HARNESS</span><h1>Experiments</h1><p>Run controlled leave-one-out replays against a golden dataset.</p></div><button className="primary-button" onClick={startExperiment}>New experiment <span>→</span></button></div>
          <section className="experiment-hero panel"><div><span className="experiment-icon">◎</span><h2>Profile a new agent version</h2><p>We’ll run the baseline, freeze every external result, and replay each case with one tool group removed.</p><div className="experiment-spec"><span><small>TASK</small><b>industry_classification</b></span><span><small>DATASET</small><b>businesses_gold_v3 · 128 cases</b></span><span><small>METHOD</small><b>Leave-one-out · strict replay</b></span></div><button className="primary-button" onClick={startExperiment}>Run 768 counterfactuals <span>→</span></button></div><div className="experiment-diagram"><div><b>BASELINE</b><span>6 tools</span></div><i>freeze</i><div className="replay-nodes">{tools.map(tool => <span key={tool.name}>− {tool.label}</span>)}</div><strong>6× replay</strong></div></section>
          <section className="history panel"><div className="panel-head"><div><h3>Experiment history</h3><p>Most recent profiles for this task</p></div></div><div className="history-row head"><span>Version</span><span>Cases</span><span>Integrity</span><span>Quality</span><span>Cost</span><span>Status</span></div>{[profileVersion, profileVersion - 1, profileVersion - 2].map((version, index) => <div className="history-row" key={version}><span><b>v1.{version}</b><small>{index === 0 ? 'Just now' : `${index * 3} days ago`}</small></span><span>128</span><span>{index === 2 ? '96.9%' : '97.6%'}</span><span>{index === 0 ? formatPercent(profile.baselineQuality) : `${(93.9 - index * .5).toFixed(1)}%`}</span><span>$0.027</span><span><i className="status-pill">Complete</i></span></div>)}</section>
        </div>}

        {view === 'policies' && <div className="page view-page">
          <div className="view-title"><div><span className="micro-label">RECOMMENDATIONS ONLY</span><h1>Routing policies</h1><p>Profiler-proposed changes. Nothing is applied to production automatically.</p></div><button className="secondary-button" onClick={exportReport}>Export policy brief <span>↓</span></button></div>
          <section className="policy-summary"><div><span>Projected savings</span><b>$7,430<small>/ month</small></b></div><div><span>Quality impact</span><b>−0.7<small>pp</small></b></div><div><span>Recommendations</span><b>2<small> ready</small></b></div></section>
          <section className="policy-list"><article className="panel policy-card"><div className="policy-index">01</div><div><div className="policy-tags"><span>HIGH CONFIDENCE</span><i>Reviews</i></div><h2>Skip reviews for professional services</h2><p>Keep reviews for restaurants and low-evidence cases. Skip when the business is a professional service and homepage evidence is available.</p><div className="policy-metrics"><span><small>MONTHLY SAVINGS</small><b>$4,880</b></span><span><small>QUALITY Δ</small><b>−0.1pp</b></span><span><small>EVIDENCE</small><b>38 cases</b></span></div></div><button onClick={() => setDrawer('policy')}>Review policy →</button></article><article className="panel policy-card"><div className="policy-index">02</div><div><div className="policy-tags"><span>MEDIUM CONFIDENCE</span><i>Strong model</i></div><h2>Escalate only when identity signals conflict</h2><p>The strong model adds little when three sources corroborate. Preserve escalation for brand/legal mismatches or explicit source conflict.</p><div className="policy-metrics"><span><small>MONTHLY SAVINGS</small><b>$2,550</b></span><span><small>QUALITY Δ</small><b>−0.6pp</b></span><span><small>EVIDENCE</small><b>128 cases</b></span></div></div><button onClick={() => setDrawer('policy')}>Review policy →</button></article></section>
        </div>}

        {view === 'evals' && <div className="page view-page">
          <div className="view-title"><div><span className="micro-label">GOLDEN DATASETS</span><h1>Evaluation sets</h1><p>Developer-defined truth and scoring stay at the center of every profile.</p></div><button className="primary-button">Import JSONL <span>＋</span></button></div>
          <section className="eval-grid"><article className="panel eval-card"><div><span className="dataset-icon">✓</span><i>ACTIVE</i></div><h2>businesses_gold_v3</h2><p>Hand-labeled industry classification cases with developer-provided segmentation.</p><div className="dataset-stats"><span><b>128</b><small>Cases</small></span><span><b>5</b><small>Segments</small></span><span><b>2</b><small>Scorers</small></span></div><button onClick={() => navigate('traces')}>Open dataset <span>→</span></button></article><article className="panel scorer-card"><span className="micro-label">SCORER CONFIGURATION</span><h2>Deterministic first</h2><p>ToolValue does not decide what “correct” means. This task uses business metrics supplied by the developer.</p><pre><code><i>score</i> = 0.75 * industry_accuracy<br />&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;+ 0.25 * evidence_grounding</code></pre><div><span>industry_accuracy</span><b>0.75</b></div><div><span>evidence_grounding</span><b>0.25</b></div></article></section>
          <section className="integration-panel panel"><div><span className="micro-label">THREE LINES TO INSTRUMENT</span><h2>Own the insight, not the runtime.</h2><p>ToolValue wraps the task and tool boundaries without becoming another agent framework.</p></div><pre><code><span>@profile</span>(task=<i>"industry_classification"</i>, scorer=accuracy)<br /><b>async def</b> enrich(business):<br />&nbsp;&nbsp;&nbsp;&nbsp;...</code></pre></section>
        </div>}
        </>}
      </section>

      {drawer && !activeResearch && <div className="overlay" role="dialog" aria-modal="true" aria-label={drawer === 'policy' ? 'Policy recommendation' : 'Experiment status'} onMouseDown={event => { if (event.target === event.currentTarget) setDrawer(null); }}><aside className="drawer">
        <button className="drawer-close" onClick={() => setDrawer(null)} aria-label="Close">×</button>
        {drawer === 'policy' ? <><span className="drawer-kicker">POLICY 01 · HIGH CONFIDENCE</span><h2>Skip reviews for professional services</h2><p className="drawer-lede">A conditional skip captures most of the savings without removing the tool where it matters.</p><div className="drawer-chart"><div><span>Professional services</span><b>+0.1pp</b><i style={{ width: '4%' }} /></div><div><span>Restaurants</span><b>+3.6pp</b><i style={{ width: '74%' }} /></div><div><span>Retail</span><b>+0.8pp</b><i style={{ width: '20%' }} /></div></div><div className="drawer-rule"><small>PROPOSED CONDITION</small><code><span>if</span> segment == <i>"professional_services"</i><br />&nbsp;&nbsp;<span>and</span> homepage.status == <i>"success"</i>:<br />&nbsp;&nbsp;&nbsp;&nbsp;skip(<b>reviews</b>)</code></div><div className="guardrails"><h3>Guardrails</h3><label><span>Minimum quality retention</span><b>99.0%</b></label><label><span>Re-evaluate after</span><b>1,000 runs</b></label><label><span>Automatic production changes</span><b className="off">Off</b></label></div><button className="primary-button full-button" onClick={() => { setDrawer(null); setView('policies'); }}>Open policy workspace <span>→</span></button><small className="disclaimer">Recommendation only. ToolValue never changes production routing.</small></> : <><span className="drawer-kicker">COUNTERFACTUAL PROFILE</span><h2>{runState === 'complete' ? 'Profile complete' : 'Running 768 replays'}</h2><p className="drawer-lede">{runState === 'complete' ? 'All frozen-evidence experiments finished successfully.' : 'No external APIs are called during strict replay.'}</p><div className={`run-visual ${runState}`}><div className="run-ring"><span>{runState === 'complete' ? '✓' : '◎'}</span></div><b>{runState === 'complete' ? '100%' : 'Analyzing'}</b><small>{runState === 'complete' ? '765 valid · 3 diverged' : 'search · homepage · registry · reviews'}</small></div><div className="run-steps"><span className="done">Baseline recorded <i>128/128</i></span><span className="done">External evidence frozen <i>100%</i></span><span className={runState === 'complete' ? 'done' : 'active'}>Leave-one-out replays <i>{runState === 'complete' ? '768/768' : '•••'}</i></span><span className={runState === 'complete' ? 'done' : ''}>Aggregate & recommend <i>{runState === 'complete' ? 'Done' : 'Queued'}</i></span></div>{runState === 'complete' && <button className="primary-button full-button" onClick={() => { setDrawer(null); setView('overview'); }}>View new profile <span>→</span></button>}</>}
      </aside></div>}
    </main>
  );
}
