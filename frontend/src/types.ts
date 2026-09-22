export type Span = { start: number; end: number; label: string | null }

export type Field = {
  name: string
  value: string | null
  raw: string | null
  source: 'deterministic' | 'llm' | 'cloud' | 'vlm' | 'missing'
  span: Span | null
  confidence: number
}

export type Step = {
  name: string
  detail: string
  data: Record<string, unknown>
  ms: number
}

export type Trace = {
  trace_id: string
  engine: 'classify' | 'extract' | 'compare' | 'decide'
  inputs: Record<string, unknown>
  steps: Step[]
  output: unknown
  why: string
  model: string | null
  backend: string | null
  confidence: number | null
  escalated: boolean
  tokens: Record<string, number>
  ms: number
}

export type FieldVerdict = {
  status: 'MATCH' | 'MISMATCH' | 'MISSING'
  rule: string
  /** What the engine decided before a reviewer overruled it. */
  overruled_rule?: string
  si: { raw: string | null; value: string | null; source: string; span: Span | null }
  bl: { raw: string | null; value: string | null; source: string; span: Span | null }
}

export type Comparison = {
  status: 'OK' | 'MISMATCH' | 'NEEDS_REVIEW'
  has_defect: boolean
  defect_fields: string[]
  missing_fields: string[]
  detail: Record<string, FieldVerdict>
}

export type Draft = {
  to: string
  subject: string
  body: string
  status: string
  reasoning: {
    generated_by: string
    action: string
    basis: string
    classified_as: string
    classification_confidence: number
    classification_reason: string
    escalated_to_larger_model: boolean
    comparison_status: string | null
    comparison_method: string | null
    evidence: { field: string; status: string; rule: string; si: string | null; bl: string | null }[]
    disclaimer: string
  }
}

export type Decision = {
  action: string
  why: string
  needs_approval: boolean
  needs_judgement: boolean
  draft: Draft | null
}

export type DocumentView = {
  name: string
  text: string
  /** Data URI of the page image, present only for a scan with no text layer. */
  image: string | null
  fields: Record<string, Field>
}

export type EmailRecord = {
  email_id: string
  subject: string
  from: string
  customer?: string
  customer_email?: string
  body: string
  attachments: string[]
  classification: { category: string; intent?: string; confidence: number; reason: string; escalated: boolean }
  comparison: Comparison | null
  documents: { si?: DocumentView; bl?: DocumentView }
  decision: Decision
  blockers: string[]
  traces: Trace[]
  total_ms: number
  feedback: FeedbackRow[]
  /** A reviewer has corrected something on this case. */
  overridden?: boolean
  /** A reviewer has finished with this case, so it leaves the queue. */
  resolved?: boolean
  /** The reviewer's word on which kind of unfinishable this is. */
  review_reason_override?: string
}

/**
 * How often this exact pair of normalised values has been overruled before.
 * Drives the escalating prompt: bookkeeping the first time, a finding the fifth.
 */
export type Occurrence = {
  kind: 'entity' | 'port' | null
  a?: string
  b?: string
  field?: string
  count: number
  emails?: string[]
  approved?: boolean
  suggest_after?: number
}

export type BlastRadius = {
  kind: string
  a: string
  b: string
  would_change: { email_id: string; field: string; status: string }[]
  already_match: { email_id: string; field: string; status: string }[]
  scanned: number
}

export type EmailSummary = {
  email_id: string
  subject: string
  from?: string
  customer?: string
  customer_email?: string
  category: string
  confidence: number
  escalated: number
  classification_routing?: {
    primary?: string
    fallback?: string
    fallback_used?: boolean
    threshold?: number
    primary_confidence?: number
    fallback_reason?: string
  }
  comparison_status: string | null
  action: string
  needs_approval: number
  needs_judgement: number
  total_ms: number
  blockers?: string[]
  why?: string
  attachments?: string[]
  /** True after an operator marks the case handled. */
  resolved?: boolean
  overridden?: boolean
}

export type FeedbackRow = {
  id: number
  created_at: string
  email_id: string
  kind: string
  target: string | null
  was: string | null
  corrected_to: string
  note: string | null
  reviewer: string
}

export type Metrics = {
  run_id: number
  count: number
  escalated: number
  escalation_rate: number
  needs_approval: number
  needs_judgement: number
  avg_ms: number
  by_category: Record<string, number>
  by_action: Record<string, number>
  by_verdict: Record<string, number>
  low_confidence: number
  accuracy?: number
  scored?: number
  errors?: number
  errors_caught_by_router?: number
  confusions?: { truth: string; predicted: string; email_id: string; confidence: number }[]
}

export type AppConfig = {
  backend: string
  model: string | null
  cloud_available: boolean
  cloud_model: string | null
  escalation_enabled: boolean
  escalate_logp: number
  emails_available: number
  /** False when no provider key is set: parsing and comparison only. */
  has_model: boolean
}

export type Run = {
  id: number
  started_at: string
  finished_at: string | null
  backend: string
  model: string
  total: number
  done: number
  status: string
  error: string | null
}

export type FunnelStage = { stage: string; count: number; note: string }

export type AttentionItem = {
  email_id: string
  subject: string
  action: string
  why: string
  category: string
  confidence: number
  defect_fields: string[]
}

export type Dashboard = {
  run: Run | null
  /** 'all' spans every run so far; 'run' is a single one. */
  scope: { kind: 'all' | 'run'; runs: number }
  count: number
  workflow?: {
    open: number
    action_required?: number
    no_action_needed?: number
    handled: number
    needs_judgement: number
  }
  headline: {
    emails: number
    documents_compared: number
    defects_found: number
    needs_approval: number
    needs_judgement: number
    drafts_written: number
    escalated: number
    escalation_rate: number
    avg_ms: number
    avg_confidence: number | null
    auto_cleared: number
    no_human_needed: number
  }
  funnel: FunnelStage[]
  by_category: Record<string, number>
  by_action: Record<string, number>
  by_verdict: Record<string, number>
  defect_fields: Record<string, number>
  missing_fields: Record<string, number>
  field_sources: Record<string, number>
  blockers: Record<string, number>
  engine_ms: Record<string, { avg: number; total: number; calls: number }>
  attention: AttentionItem[]
  attention_total: number
  router: {
    threshold_logp: number
    threshold: number
    enabled: boolean
    escalated: number
    low_confidence: number
  }
  confidence_histogram: { from: number; to: number; count: number }[]
  accuracy?: {
    scored: number
    correct: number
    rate: number
    errors: number
    caught_by_router: number
    worst: {
      email_id: string
      truth: string
      predicted: string
      confidence: number
      subject: string
    }[]
  }
  technical_summary?: TechnicalSummary
  feedback: { count: number; alias_suggestions: number; regression_cases: number }
}

export type TechnicalSummary = {
  extraction: {
    total_fields: number
    sources: Record<string, number>
    rates: Record<string, number>
    total_docs: number
    scanned_docs: number
    scan_rate: number
    formats: Record<string, number>
    llm_cases?: {
      email_id: string
      subject: string
      doc_name: string
      fields: Record<string, string>
    }[]
    vlm_cases?: {
      email_id: string
      subject: string
      doc_name: string
      fields_count: number
      fields?: Record<string, string>
    }[]
    missing_cases?: {
      email_id: string
      subject: string
      doc_name: string
      missing_fields: string[]
    }[]
  }
  classification: {
    total_emails: number
    methods: Record<string, number>
    rates: Record<string, number>
  }
  engines: Record<string, {
    avg_ms: number
    total_ms: number
    calls: number
    share_pct: number
  }>
  tokens: {
    prompt: number
    completion: number
    total: number
  }
  total_engine_time_ms: number
  saved_calls: number
  estimated_saved_cost_usd: number
}

export type PoolBucket = {
  label: string
  note: string
  total: number
  used: number
  available: number
}

export type Pool = {
  buckets: Record<string, PoolBucket>
  order: string[]
  corpus: number
  used: number
  available: number
  labelled: boolean
}

export type RunPreview = {
  dry_run: true
  run_id: null
  total: number
  shortfall: Record<string, number>
  by_bucket: Record<string, number>
  emails: string[]
  note: string
}

/** One category's confusion counts, as the shared scorer reports them. */
export type CategoryScore = {
  precision: number; recall: number; f1: number
  tp: number; fp: number; fn: number; support: number
}

export type StageMetrics = {
  scored: number
  classification: {
    accuracy: number; correct: number; total: number; macro_f1: number
    by_category: Record<string, CategoryScore>
    confusion: Record<string, Record<string, number>>
    misclassified: { email_id: string; expected: string; predicted: string }[]
  }
  edge_cases: {
    recall: number | null; correct: number; total: number
    rows: { email_id: string; expected: string | null; predicted: string | null; ok: boolean }[]
  }
  comparison: {
    precision: number; recall: number; f1: number
    exact_match: number | null; exact_matched: number; total: number
    mismatched_rows: { email_id: string; expected: string[]; predicted: string[] }[]
  }
}

export type Usage = {
  emails: number
  total_ms: number; mean_ms: number; median_ms: number | null
  p95_ms: number | null; slowest_ms: number
  tokens: { prompt: number; completion: number; total: number }
  mean_tokens: number
  model_calls: number
  calls_reporting_tokens: number
  /** Share of model calls that reported usage — the token totals are a floor. */
  token_coverage: number | null
  /** What providers actually charged, where they said so. */
  billed: number
  cost: {
    currency: string
    input_per_m: number | null; output_per_m: number | null
    total: number; per_email: number; projected_corpus: number
    /** False when some model calls never reported usage, so this is a floor. */
    complete: boolean
    /** Whether the provider billed it or rates were applied to token counts. */
    source: string
  } | null
  by_engine: Record<string, {
    calls: number; ms: number; tokens: number; model_calls: number; cost: number
    mean_ms: number; share_of_time: number
  }>
}

export type BenchmarkReport = {
  ground_truth_total: number
  available: { key: string; model: string; backend: string; emails: number; runs: number[] }[]
  models: { key: string; model: string; backend: string; runs: number[]; emails: number; metrics: StageMetrics; usage: Usage }[]
  common_emails: number
  /** False when the selected models ran on different slices of the corpus. */
  identical_coverage: boolean
  on_common: Record<string, StageMetrics> | null
}

export type DecisionModelCategoryScore = {
  precision: number
  recall: number
  f1: number
  support: number
}

export type DecisionModelConfidenceRoutingRow = {
  threshold: number
  auto_cases: number
  coverage: number
  auto_errors: number
  auto_accuracy: number
  fallback_cases: number
}

export type DecisionModelCasePrediction = {
  email_id: string
  expected: string
  predicted: string
  correct: boolean
  confidence: number
  probabilities?: Record<string, number>
}

export type DecisionModelData = {
  name: string
  accuracy: number
  correct: number
  total: number
  macro_f1: number
  per_category: Record<string, DecisionModelCategoryScore>
  confusion_matrix: Record<string, Record<string, number>>
  latency: {
    batch_size: number
    median_batch_ms: number
    p95_batch_ms: number
    effective_ms_per_email: number
    wall_time_s: number
  }
  usage: {
    input_tokens: number
    output_tokens: number
    cost_usd: number
  }
  mean_reported_confidence: number
  resolved_models?: Record<string, number>
  providers?: Record<string, number>
  confidence_routing: DecisionModelConfidenceRoutingRow[]
  predictions?: DecisionModelCasePrediction[]
}

export type DecisionBenchmarkReport = {
  schema_version: number
  generated_at: string
  dataset: {
    name: string
    cases: number
    category_distribution: Record<string, number>
    input: string
    attachment_contents_sent: boolean
  }
  methodology: {
    task: string
    categories: string[]
    batch_size: number
    workers: number
    temperature: number
    confidence_note: string
  }
  requested_models: {
    jev: string
    gemini: string
    qwen?: string
    [key: string]: string | undefined
  }
  models: {
    jev: DecisionModelData
    gemini: DecisionModelData
    qwen?: DecisionModelData
    [key: string]: DecisionModelData | undefined
  }
  highlights: {
    highest_accuracy: string
    highest_macro_f1: string
    lowest_effective_latency: string
    lowest_reported_cost: string
  }
}

export type BenchmarkCase = {
  email_id: string
  truth: { category: string; status: string; review_reason: string | null; has_defect: boolean; defect_fields: string[] }
  predicted: { category: string; status: string; review_reason: string | null; has_defect: boolean; defect_fields: string[] }
  checks: Record<string, boolean>
  ok: boolean
}

/** What the Improvement page renders: the three artefacts a correction becomes. */
export type FeedbackExport = {
  feedback_count: number
  overridden_emails: number
  /** Counter A — the same two spellings, overruled again. A missing alias. */
  pair_counts: {
    kind: string; a: string; b: string; count: number; field: string | null
    emails: string[]; example: { si: string | null; bl: string | null }; approved: boolean
  }[]
  /** Counter B — one rule overruled across many values. The rule is too strict. */
  rule_counts: {
    rule: string; count: number; distinct_pairs: number
    fields: string[]; emails: string[]; suggest: boolean
  }[]
  mappings: {
    kind: string; a: string; b: string
    approved_by: string; approved_at: string; from_email: string | null; run_id: number | null
  }[]
  suggest_after: number
}

export type MappingEntry = {
  kind: 'entity' | 'port'
  a: string
  b: string
  approved_by: string
  approved_at: string
  from_email?: string | null
  run_id?: number | null
  note?: string | null
}

export type MappingListResponse = {
  entries: MappingEntry[]
  corrections: FeedbackRow[]
  counters: {
    entity: number
    port: number
    pairs: unknown[]
    rules: unknown[]
    total_mappings: number
    total_corrections: number
  }
}

export type ModelOption = {
  key: string; backend: string; model: string; emails: number; runs: number
}

/** A model a run can be started with, here and now. */
export type RunnableModel = {
  backend: string
  model: string
  label: string
  available: boolean
  /** Whether the model id itself can be typed over (chat backends). */
  editable: boolean
  cost: string
  note: string
}

export type SimAttachment = {
  filename: string
  /** base64 of the file's bytes, without a data: prefix. */
  content_b64: string
  /** 'si' | 'bl' | '' -- which document this is, so nothing has to guess. */
  role: string
}

export type SimulateRequest = {
  subject: string
  sender: string
  body: string
  attachments: SimAttachment[]
}

export type SimulateResult = {
  run_id: number
  email_id: string
  record: EmailRecord
}
