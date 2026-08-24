export type ToolName = 'homepage' | 'registry' | 'search' | 'about' | 'reviews' | 'strong_model';
export type Segment = 'professional_services' | 'restaurant' | 'trades' | 'retail' | 'brand_legal_mismatch';

export type ToolDefinition = {
  name: ToolName;
  label: string;
  cost: number;
  latencyMs: number;
};

export type ProfileCase = {
  id: string;
  business: string;
  expected: string;
  output: string;
  segment: Segment;
  baselineScore: number;
  losses: Record<ToolName, number>;
  divergedTool?: ToolName;
};

export type ToolMetric = ToolDefinition & {
  qualityDelta: number;
  usefulRate: number;
  harmfulRate: number;
  valuePerDollar: number;
  runs: number;
};

export const tools: ToolDefinition[] = [
  { name: 'homepage', label: 'Homepage', cost: 0.002, latencyMs: 620 },
  { name: 'registry', label: 'Registry', cost: 0.001, latencyMs: 310 },
  { name: 'search', label: 'Search', cost: 0.001, latencyMs: 480 },
  { name: 'about', label: 'About page', cost: 0.002, latencyMs: 540 },
  { name: 'reviews', label: 'Reviews', cost: 0.007, latencyMs: 910 },
  { name: 'strong_model', label: 'Strong model', cost: 0.014, latencyMs: 1940 },
];

const businessNames = [
  ['Harbor & Finch LLP', 'Legal services'],
  ['North Loop Advisory', 'Management consulting'],
  ['Casa Juniper', 'Restaurant'],
  ['Austin Flow Pros', 'Plumbing'],
  ['Morrow & Vale Studio', 'Architecture'],
  ['Northstar Fabrication LLC', 'Industrial manufacturing'],
  ['Kinship Pediatrics', 'Medical practice'],
  ['Redbud Table', 'Restaurant'],
  ['Alloy Systems', 'Industrial manufacturing'],
  ['Parkline Supply Co.', 'Retail'],
  ['Rivers & Cole CPAs', 'Accounting'],
  ['Brightwell Electric', 'Electrical contractor'],
] as const;

const segmentCycle: Segment[] = [
  'professional_services', 'professional_services', 'restaurant', 'trades',
  'professional_services', 'brand_legal_mismatch', 'professional_services', 'restaurant',
  'brand_legal_mismatch', 'retail', 'professional_services', 'trades',
];

function round(value: number, precision = 4) {
  return Number(value.toFixed(precision));
}

function lossFor(tool: ToolName, segment: Segment, index: number) {
  const wobble = ((index * 7) % 5 - 2) * 0.003;
  const bases: Record<ToolName, Record<Segment, number>> = {
    homepage: { professional_services: 0.112, restaurant: 0.082, trades: 0.135, retail: 0.061, brand_legal_mismatch: 0.076 },
    registry: { professional_services: 0.018, restaurant: 0.008, trades: 0.055, retail: 0.023, brand_legal_mismatch: 0.238 },
    search: { professional_services: 0.046, restaurant: 0.054, trades: 0.051, retail: 0.041, brand_legal_mismatch: 0.044 },
    about: { professional_services: 0.048, restaurant: 0.009, trades: 0.025, retail: 0.013, brand_legal_mismatch: 0.018 },
    reviews: { professional_services: 0.001, restaurant: index % 4 === 0 ? 0.072 : 0.008, trades: 0.003, retail: 0.009, brand_legal_mismatch: 0 },
    strong_model: { professional_services: index % 11 === 0 ? 0.016 : 0, restaurant: 0.002, trades: 0.004, retail: 0, brand_legal_mismatch: 0.096 },
  };

  let value = bases[tool][segment];
  if (tool === 'reviews' && index % 23 === 0) value = -0.012;
  if (tool === 'registry' && index % 31 === 0) value = -0.008;
  if (!['reviews', 'strong_model'].includes(tool)) value += wobble;
  return round(value);
}

export const demoCases: ProfileCase[] = Array.from({ length: 128 }, (_, index) => {
  const segment = segmentCycle[index % segmentCycle.length];
  const [business, expected] = businessNames[index % businessNames.length];
  const baselineScore = round(0.91 + ((index * 13) % 9) * 0.01);
  const losses = Object.fromEntries(tools.map(tool => [tool.name, lossFor(tool.name, segment, index)])) as Record<ToolName, number>;
  return {
    id: `run_${String(882 + index).padStart(4, '0')}`,
    business: index < businessNames.length ? business : `${business} · ${Math.floor(index / businessNames.length) + 1}`,
    expected,
    output: expected,
    segment,
    baselineScore,
    losses,
    divergedTool: index % 43 === 0 ? 'search' : undefined,
  };
});

export function analyzeProfile(cases: ProfileCase[], segment: Segment | 'all' = 'all') {
  const selected = segment === 'all' ? cases : cases.filter(item => item.segment === segment);
  const validRuns = selected.filter(item => !item.divergedTool);
  const metrics: ToolMetric[] = tools.map(tool => {
    const comparable = validRuns.filter(item => item.divergedTool !== tool.name);
    const deltas = comparable.map(item => item.losses[tool.name]);
    const qualityDelta = deltas.reduce((sum, value) => sum + value, 0) / Math.max(1, deltas.length);
    const usefulRate = deltas.filter(value => value >= 0.01).length / Math.max(1, deltas.length);
    const harmfulRate = deltas.filter(value => value < 0).length / Math.max(1, deltas.length);
    return {
      ...tool,
      qualityDelta: round(qualityDelta),
      usefulRate: round(usefulRate),
      harmfulRate: round(harmfulRate),
      valuePerDollar: round(qualityDelta / tool.cost, 2),
      runs: comparable.length,
    };
  });
  const baselineQuality = selected.reduce((sum, item) => sum + item.baselineScore, 0) / Math.max(1, selected.length);
  const avgCost = tools.reduce((sum, tool) => sum + tool.cost, 0);
  const p95Latency = tools.reduce((sum, tool) => sum + tool.latencyMs, 0);
  const replayIntegrity = validRuns.length / Math.max(1, selected.length);
  return { cases: selected, metrics, baselineQuality, avgCost, p95Latency, replayIntegrity };
}

export function ablate(profileCase: ProfileCase, tool: ToolName) {
  const delta = profileCase.losses[tool];
  const counterfactualScore = round(Math.max(0, Math.min(1, profileCase.baselineScore - delta)));
  const diverged = profileCase.divergedTool === tool;
  return { baselineScore: profileCase.baselineScore, counterfactualScore, delta, diverged };
}

export function segmentLabel(segment: Segment | 'all') {
  const labels: Record<Segment | 'all', string> = {
    all: 'All segments', professional_services: 'Professional services', restaurant: 'Restaurants',
    trades: 'Home & field services', retail: 'Retail', brand_legal_mismatch: 'Brand / legal mismatch',
  };
  return labels[segment];
}

export function formatPercent(value: number, digits = 1) {
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatDelta(value: number) {
  return `${value >= 0 ? '+' : '−'}${Math.abs(value * 100).toFixed(1)}pp`;
}
