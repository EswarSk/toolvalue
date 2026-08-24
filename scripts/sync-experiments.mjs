import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const outputPath = resolve(root, 'data/experiments.json');
const reports = [
  {
    id: 'gpt-researcher-10',
    label: 'GPT Researcher · 10 blind papers',
    path: 'gpt-researcher-sample/.toolvalue/live-openrouter-10-report.json',
  },
  {
    id: 'gpt-researcher-3',
    label: 'GPT Researcher · 3 blind papers',
    path: 'gpt-researcher-sample/.toolvalue/live-openrouter-clean-report.json',
  },
];

const labels = {
  crossref: 'Crossref',
  openalex: 'OpenAlex',
  open_citations: 'OpenCitations',
  europe_pmc: 'Europe PMC',
};

function mean(values) {
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
}

function normalize(spec, report, exactBlindSeed) {
  const answers = report.experiment?.blind_answers ?? [];
  const profiles = report.profiles ?? [];
  const cases = answers.map((answer, offset) => {
    const profile = profiles.find(item => item.baseline?.metadata?.paper_index === answer.index) ?? profiles[offset];
    const grouped = new Map();
    for (const counterfactual of profile?.counterfactuals ?? []) {
      if (counterfactual.status !== 'complete' || !(counterfactual.delta > 0)) continue;
      const values = grouped.get(counterfactual.ablated_unit) ?? [];
      values.push(counterfactual);
      grouped.set(counterfactual.ablated_unit, values);
    }
    const effects = [...grouped.entries()].map(([source, values]) => ({
      source,
      sourceLabel: labels[source] ?? source,
      meanDelta: mean(values.map(item => item.delta)),
      affectedFields: Object.entries(values[0]?.score_components ?? {})
        .filter(([field, score]) => field !== 'overall' && score === 0)
        .map(([field]) => field),
      trials: values.length,
    }));
    return {
      index: answer.index,
      doi: answer.doi,
      title: answer.title,
      year: answer.year,
      firstAuthor: answer.first_author,
      venue: answer.venue,
      baselineScore: profile?.baseline?.score ?? 0,
      eligible: profile?.baseline?.valid ?? false,
      effects,
    };
  });
  const completedAt = profiles
    .map(item => item.baseline?.started_at)
    .filter(Boolean)
    .sort()
    .at(-1) ?? null;

  return {
    id: spec.id,
    label: spec.label,
    title: 'Scholarly source review',
    task: report.task,
    status: 'complete',
    completedAt,
    cases: report.cases,
    eligibleCases: report.eligible_cases,
    baselineQuality: report.baseline_quality,
    baselineEligibility: report.baseline_eligibility,
    averageCost: report.average_cost,
    averageLatencyMs: report.average_latency_ms,
    replayIntegrity: report.replay_integrity,
    attributionCoverage: report.attribution_coverage,
    tools: (report.tools ?? []).map(tool => ({
      name: tool.unit,
      label: labels[tool.unit] ?? tool.unit,
      attempts: tool.attempts,
      runs: tool.runs,
      independentCases: tool.independent_cases,
      meanQualityDelta: tool.mean_quality_delta,
      positiveRate: tool.positive_rate,
      zeroValueRate: tool.zero_value_rate,
      attributionCoverage: tool.attribution_coverage,
      reliable: tool.attribution_reliable,
      averageLatencyMs: tool.avg_latency_ms,
      confidenceInterval95: tool.confidence_interval_95,
    })),
    upstream: report.experiment?.upstream,
    upstreamVersion: report.experiment?.upstream_version,
    writerBackend: report.experiment?.writer_backend,
    modelId: report.experiment?.model_id,
    sourceMode: report.experiment?.source_mode,
    sourceExecutions: report.experiment?.source_executions,
    modelRuns: report.experiment?.model_runs,
    reportedModelCost: report.experiment?.reported_model_cost,
    counterfactualTrials: report.experiment?.counterfactual_trials,
    blindSeed: exactBlindSeed ?? String(report.experiment?.blind_seed ?? ''),
    caseResults: cases,
  };
}

const experiments = reports.flatMap(spec => {
  const path = resolve(root, spec.path);
  if (!existsSync(path)) return [];
  const raw = readFileSync(path, 'utf8');
  const exactBlindSeed = raw.match(/"blind_seed"\s*:\s*(\d+)/)?.[1];
  return [normalize(spec, JSON.parse(raw), exactBlindSeed)];
});

if (experiments.length === 0) {
  if (!existsSync(outputPath)) throw new Error('No ToolValue reports were found and no generated dashboard data exists.');
  console.log('No local ToolValue reports found; preserving generated dashboard data.');
  process.exit(0);
}

mkdirSync(dirname(outputPath), { recursive: true });
writeFileSync(outputPath, `${JSON.stringify(experiments, null, 2)}\n`);
console.log(`Synced ${experiments.length} ToolValue experiments to data/experiments.json.`);
