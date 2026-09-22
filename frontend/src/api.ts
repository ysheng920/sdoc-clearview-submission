import type {
  AppConfig, BenchmarkCase, BenchmarkReport, BlastRadius, Dashboard, EmailRecord,
  FeedbackExport, ModelOption, RunnableModel,
  EmailSummary, Metrics, Occurrence, Pool, Run, RunPreview, DecisionBenchmarkReport,
  SimulateRequest, SimulateResult, MappingListResponse,
} from './types'

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} on ${path}`)
  return res.json() as Promise<T>
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} on ${path}`)
  return res.json() as Promise<T>
}

export const api = {
  config: () => get<AppConfig>('/api/config'),
  runs: () => get<Run[]>('/api/runs'),
  run: (id: number) => get<Run>(`/api/runs/${id}`),
  startRun: (limit: number | null, workers = 4) =>
    post<{ run_id: number; total: number }>('/api/runs', { limit, workers }),

  pool: () => get<Pool>('/api/pool'),

  /**
   * Run one hand-written email through the same four engines as the corpus.
   *
   * Uses its own fetch rather than post(): the server explains a rejected
   * attachment in `detail` ("this extension cannot be read"), and the shared
   * helper throws away everything but the status code.
   */
  simulate: async (payload: SimulateRequest) => {
    const res = await fetch('/api/simulate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!res.ok) {
      const detail = await res.json().then((d) => d?.detail).catch(() => null)
      throw new Error(detail || `${res.status} ${res.statusText} on /api/simulate`)
    }
    return res.json() as Promise<SimulateResult>
  },

  /** Restore the committed 526-case demo baseline and predefined mappings. */
  resetDemo: async () => {
    const res = await fetch('/api/demo/reset', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    })
    if (!res.ok) {
      const detail = await res.json().then((d) => d?.detail).catch(() => null)
      throw new Error(detail || `${res.status} ${res.statusText} on /api/demo/reset`)
    }
    return res.json() as Promise<{
      status: string
      runs: number
      results: number
      feedback: number
      mappings: number
      message: string
    }>
  },

  /** Resolve the selection without processing anything -- no model is called. */
  previewQuota: (quota: Record<string, number>) =>
    post<RunPreview>('/api/runs', { quota, dry_run: true }),

  /** Score the whole corpus again. Does not touch the operator's queue. */
  runBenchmark: (choice: { backend: string; model?: string; passcode?: string }, workers = 6) =>
    post<{ run_id: number; total: number }>(
      '/api/runs', { ...choice, purpose: 'benchmark', exclude_used: false, workers }),

  clearBenchmarkHistory: async () => {
    const res = await fetch('/api/benchmark/history?confirm=true', { method: 'DELETE' })
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
    return res.json() as Promise<{ deleted_runs: number }>
  },

  runQuota: (quota: Record<string, number>, workers = 4,
             choice?: { backend: string; model?: string }) =>
    post<{ run_id: number; total: number; shortfall: Record<string, number> }>(
      '/api/runs', { quota, workers, ...choice },
    ),

  /** Models this deployment can actually run, and why not where it cannot. */
  runnableModels: () =>
    get<{ models: RunnableModel[]; default: string }>('/api/models/runnable'),

  resetPool: async () => {
    const res = await fetch('/api/pool?confirm=true', { method: 'DELETE' })
    if (!res.ok) throw new Error(`${res.status} ${res.statusText} on /api/pool`)
    return res.json() as Promise<{ deleted_runs: number; deleted_results: number }>
  },

  emails: (
    params: {
      needs_approval?: boolean
      needs_judgement?: boolean
      category?: string
      action?: string
      model?: string
    } = {},
  ) => {
    const q = new URLSearchParams()
    if (params.needs_approval !== undefined) q.set('needs_approval', String(params.needs_approval))
    if (params.needs_judgement !== undefined) q.set('needs_judgement', String(params.needs_judgement))
    if (params.category) q.set('category', params.category)
    if (params.action) q.set('action', params.action)
    if (params.model) q.set('model', params.model)
    const qs = q.toString()
    return get<{ run_id: number; count: number; emails: EmailSummary[] }>(
      `/api/emails${qs ? `?${qs}` : ''}`,
    )
  },
  email: (id: string, model?: string) =>
    get<EmailRecord>(`/api/emails/${id}${model ? `?model=${encodeURIComponent(model)}` : ''}`),

  /** Models that have produced a stored result, for the queue filter. */
  models: () => get<{ models: ModelOption[] }>('/api/models'),
  metrics: () => get<Metrics>('/api/metrics'),
  dashboard: () => get<Dashboard>('/api/dashboard'),

  sendFeedback: (
    emailId: string,
    payload: {
      kind: 'category' | 'field' | 'verdict' | 'review_reason' | 'resolve'
      corrected_to: string
      target?: string
      was?: string
      note?: string
      /** Which document was edited, for kind='field'. */
      side?: 'si' | 'bl'
      to_library?: boolean
    },
    // The response carries the re-read record, so the caller never has to guess
    // what the correction did -- it renders what the server now says.
  ) => post<{ id: number; record: EmailRecord; occurrence: Occurrence | null }>(
    `/api/emails/${emailId}/feedback`, payload,
  ),

  /** The reviewer's answer to "does this belong in the mapping library?". */
  recordInLibrary: (feedbackId: number, record: boolean) =>
    post<{ id: number; to_library: boolean; occurrence: Occurrence | null }>(
      `/api/feedback/${feedbackId}/library`, { record },
    ),

  /** What approving this pair would change, read before anyone approves it. */
  blastRadius: (kind: string, a: string, b: string) =>
    get<BlastRadius>(`/api/mappings/blast-radius?kind=${encodeURIComponent(kind)}`
      + `&a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`),

  revokeMapping: async (kind: string, a: string, b: string) => {
    const q = new URLSearchParams({ kind, a, b })
    const res = await fetch(`/api/mappings?${q}`, { method: 'DELETE' })
    if (!res.ok) throw new Error(`${res.status} ${res.statusText} on /api/mappings`)
    return res.json() as Promise<{ revoked: { kind: string; a: string; b: string } }>
  },

  approveMapping: (kind: string, a: string, b: string, note?: string) =>
    post<{ entry: Record<string, unknown>; blast_radius: BlastRadius; file: string }>(
      '/api/mappings/approve', { kind, a, b, note },
    ),

  mappings: () => get<MappingListResponse>('/api/mappings'),

  feedbackExport: () => get<FeedbackExport>('/api/feedback/export'),

  /** Models scored against ground truth. */
  benchmark: (models?: string[]) =>
    get<BenchmarkReport>(`/api/benchmark${models?.length
      ? `?models=${encodeURIComponent(models.join(','))}` : ''}`),

  /** Comprehensive 520-case two-model benchmark (Jev, Gemini). */
  decisionBenchmark: (full: boolean = true) =>
    get<DecisionBenchmarkReport>(`/api/benchmark/decision-models?full=${full}`),

  runDecisionBenchmark: (limit?: number, passcode?: string) =>
    post<{ status: string; job: Record<string, unknown> }>('/api/benchmark/decision-models/run', { limit, passcode }),

  decisionBenchmarkStatus: () =>
    get<{
      status: 'idle' | 'running' | 'completed' | 'failed'
      current_model?: string | null
      model_label?: string | null
      model_index: number
      total_models: number
      pct: number
      total_cases: number
      error?: string | null
      generated_at?: string | null
    }>('/api/benchmark/decision-models/status'),

  decisionBenchmarkMarkdown: () =>
    fetch('/api/benchmark/report.md').then((r) => {
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
      return r.text()
    }),

  benchmarkCases: (model: string, outcome: 'all' | 'wrong' | 'right' = 'all') =>
    get<{ model: string; count: number; cases: BenchmarkCase[] }>(
      `/api/benchmark/cases?model=${encodeURIComponent(model)}&outcome=${outcome}`),

  pricing: () => get<{ prices: Record<string, { input_per_m: number | null; output_per_m: number | null; currency: string }>; path: string; unit: string }>('/api/models/pricing'),

  setPrice: async (key: string, input_per_m: number | null, output_per_m: number | null) => {
    const res = await fetch('/api/models/pricing', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key, input_per_m, output_per_m }),
    })
    if (!res.ok) throw new Error(`${res.status} ${res.statusText} on /api/models/pricing`)
    return res.json() as Promise<{ prices: Record<string, unknown> }>
  },

  draftUrl: (id: string) => `/api/emails/${id}/draft.eml`,
}
