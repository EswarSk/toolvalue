export type ResearchToolMetric = {
  name: string;
  label: string;
  attempts: number;
  runs: number;
  independentCases: number;
  meanQualityDelta: number | null;
  positiveRate: number;
  zeroValueRate: number;
  attributionCoverage: number;
  reliable: boolean;
  averageLatencyMs: number;
  confidenceInterval95: [number, number] | null;
};

export type ResearchCaseEffect = {
  source: string;
  sourceLabel: string;
  meanDelta: number;
  affectedFields: string[];
  trials: number;
};

export type ResearchCaseResult = {
  index: number;
  doi: string;
  title: string;
  year: number;
  firstAuthor: string;
  venue: string;
  baselineScore: number;
  eligible: boolean;
  effects: ResearchCaseEffect[];
};

export type ResearchExperiment = {
  id: string;
  label: string;
  title: string;
  task: string;
  status: 'complete';
  completedAt: string | null;
  cases: number;
  eligibleCases: number;
  baselineQuality: number;
  baselineEligibility: number;
  averageCost: number;
  averageLatencyMs: number;
  replayIntegrity: number;
  attributionCoverage: number;
  tools: ResearchToolMetric[];
  upstream: string;
  upstreamVersion: string;
  writerBackend: string;
  modelId: string;
  sourceMode: string;
  sourceExecutions: number;
  modelRuns: number;
  reportedModelCost: number;
  counterfactualTrials: number;
  blindSeed: string;
  caseResults: ResearchCaseResult[];
};

export type DashboardView = 'overview' | 'traces' | 'experiments' | 'policies' | 'evals';
