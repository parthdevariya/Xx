export type User = {
  id: string;
  email: string;
  display_name: string;
  role: string;
  role_name: string;
  permissions: string[];
};

export type ContentClass = "computed" | "model_generated" | "assumption" | "estimate" | "cached" | "test";
export type ExecClass = "hardware" | "cloud_simulator" | "local_simulator" | "classical" | "cached" | "test" | "";

export type ScenarioField = {
  key: string;
  label?: string;
  type: "number" | "text" | "textarea" | "matrix" | "list_number" | "list_text" | "json";
  required?: boolean;
  min?: number;
  max?: number;
  help?: string;
};

export type Scenario = {
  id: string;
  slug: string;
  status: string;
  is_demo: boolean;
  category: { slug: string; name: string; notice: string };
  version_no: number | null;
  name: string;
  tagline: string;
  engines: string[];
  solver_template: string;
  quantum_eligibility: string;
  modes: string[];
  default_mode: string;
  expected_output: string;
  description?: string;
  problem_statement?: string;
  context?: string;
  demonstrates?: string;
  visualizations?: string[];
  benchmark_config?: { approaches?: string[]; rubric?: RubricCriterion[] } & Record<string, unknown>;
  fields?: ScenarioField[];
  defaults?: Record<string, unknown>;
  policy?: {
    allowed_modes: string[];
    default_mode: string;
    max_cost_usd: number;
    allow_quantum_hardware: boolean;
    demo_enabled: boolean;
  } | null;
};

export type PlanStep = {
  key: string;
  engine: string;
  title: string;
  status: "planned" | "skipped" | "completed";
  reason: string;
  execution_class?: string;
  decision?: string;
  note?: string;
};

export type QuantumDecision = {
  decision: string;
  explanation: string;
  factors: Record<string, string | number | null>;
  run_quantum: boolean;
  route?: { backend: string; backend_name: string; algorithm: string; execution_class: string; qubits?: number };
  missing?: string[];
};

export type ExecEvent = { seq: number; at: string | null; engine: string; type: string; message: string; data: Record<string, unknown> };

export type Section = { content: unknown; class: ContentClass };

export type ExecutionResult = {
  step: string;
  engine: string;
  content_class: ContentClass;
  execution_class: ExecClass;
  title: string;
  content: Record<string, unknown>;
  created_at: string;
};

export type BenchmarkMetric = { approach: string; metric: string; value: number | null; text: string; unit: string; notes: string };

export type Execution = {
  id: string;
  mode: string;
  mode_label: string;
  status: string;
  scenario_id: string | null;
  is_demo: boolean;
  result_source: "live" | "cached" | "test";
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  ai_provider: string;
  ai_model: string;
  quantum_backend: string;
  algorithm: string;
  estimated_cost_usd: number;
  actual_cost_usd: number;
  error: string;
  event_seq: number;
  problem_summary: string;
  problem?: { text: string; inputs: Record<string, unknown>; attachments: unknown[]; structured: Record<string, unknown> };
  plan?: { mode: string; steps: PlanStep[]; quantum_decision: QuantumDecision; estimates: Record<string, number>; baselines: string[] } | null;
  final_output?: Record<string, Section | string>;
  resource_usage?: Record<string, unknown>;
  results?: ExecutionResult[];
  benchmark?: {
    id: string;
    objective: string;
    conclusion: string;
    methodology: Record<string, string>;
    environment: Record<string, unknown>;
    input_sha256: string;
    metrics: BenchmarkMetric[];
  } | null;
  intellect_runs?: string[];
  artifacts?: { kind: string; name: string }[];
  framework_version?: string | null;
  cached?: { is_cached: boolean; original_execution_id: string; computed_at: string; label: string };
};

export type SystemStatus = {
  database: string;
  ai: { configured_providers: string[]; status: string; test_provider_active: boolean };
  quantum: { providers: { vendor: string; name: string; status: string; active: boolean }[]; status: string };
  intellect: { framework: string | null; version: string | null; layers: number; rules: number; protected: number; status: string };
  scenarios: { published: number };
  worker: { recently_active_jobs: number };
};

export const MODE_LABELS: Record<string, string> = {
  ai_only: "AI Only",
  ai_intellect: "AI + Intellect",
  intellect_vs_ai: "Intellect vs AI (judged proof)",
  classical: "Classical",
  quantum: "Quantum Only",
  classical_quantum: "Classical vs Quantum",
  ai_classical: "AI + Classical",
  classical_intellect: "Classical + Intellect",
  ai_quantum: "AI + Quantum",
  hybrid: "Full Hybrid X",
  benchmark: "Comparative Benchmark",
};

export type ModeInfo = { key: string; label: string; engines: string[]; needs: string[]; description: string };

export type RubricCriterion = {
  id: string; criterion: string; why?: string; related_rules: string[];
  check: { type: "judge" | "max_questions" | "must_not_contain" | "must_contain_any"; value?: number | string[] };
};

export type ProofVerdict = { pass: boolean | null; evidence: string; reason: string };

export type ProofResult = {
  verdict: string;
  score: { ai_only: number; ai_intellect: number };
  total: number;
  criteria: {
    id: string; criterion: string; why: string; related_rules: string[]; rules_applied_by_intellect: string[];
    method: "judge" | "deterministic"; ai_only: ProofVerdict; ai_intellect: ProofVerdict;
  }[];
  intellect_only_wins: string[];
  ai_only_wins: string[];
  rules_behind_wins: string[];
  judge: { model: string; blind: boolean; order: Record<string, string>; error: string; test_provider: boolean };
  rubric_source: string;
  answers: { ai_only: string; ai_intellect: string };
  method_note: string;
};
