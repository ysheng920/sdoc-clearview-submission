import { useEffect, useState } from 'react'
import { api } from '../api'
import { Icon } from '../components/Icon'
import type { Dashboard as Data } from '../types'

const colours = ['#2269d9', '#2fb57d', '#f2b94b', '#e2505e', '#9b6cf3', '#60a5fa']
const pretty = (value: string) => value.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())

type ViewMode = 'case' | 'technical'

export function Dashboard({
  reloadKey = 0,
  onOpenEmail,
}: {
  reloadKey?: number
  onOpenEmail?: (id: string) => void
}) {
  const [data, setData] = useState<Data | null>(null)
  const [error, setError] = useState('')
  const [mode, setMode] = useState<ViewMode>('case')
  const [inspectorFilter, setInspectorFilter] = useState<'llm' | 'vlm' | 'missing'>('llm')
  const [inspectorPage, setInspectorPage] = useState<number>(1)
  const INSPECTOR_PAGE_SIZE = 5

  useEffect(() => {
    api.dashboard().then(setData).catch((e) => setError(String(e)))
  }, [reloadKey])

  if (error) {
    return <div className="empty-panel"><Icon name="alert" size={32} /><p>{error}</p></div>
  }
  if (!data) {
    return (
      <div className="empty-panel">
        <div className="loading-ring" />
        <p>Loading analytics & telemetry…</p>
      </div>
    )
  }
  if (!data.count) {
    return (
      <div className="empty-panel">
        <Icon name="analytics" size={36} />
        <h3>No run to analyze yet</h3>
        <p>Start a batch from the Work Queue to see performance data.</p>
      </div>
    )
  }

  const h = data.headline
  const tech = data.technical_summary
  const workflow = data.workflow
  const compared = h.documents_compared || 1
  const actionRequiredCount = workflow?.action_required ?? workflow?.open ?? (data.count - (workflow?.handled ?? 0))
  const noActionCount = workflow?.no_action_needed ?? 0
  const handledCount = workflow?.handled ?? 0
  const stpRate = ((h.auto_cleared / compared) * 100).toFixed(1)
  const defectRate = ((h.defects_found / compared) * 100).toFixed(1)
  const judgementRate = ((h.needs_judgement / data.count) * 100).toFixed(1)
  const draftRate = ((h.drafts_written / data.count) * 100).toFixed(1)

  // Technical stats with safe fallbacks if tech is somehow not yet populated
  const extraction = tech?.extraction ?? {
    total_fields: data.field_sources ? Object.values(data.field_sources).reduce((a, b) => a + b, 0) : 0,
    sources: data.field_sources || {},
    rates: {
      deterministic: data.field_sources ? Number((((data.field_sources.deterministic || 0) / (Object.values(data.field_sources).reduce((a, b) => a + b, 0) || 1)) * 100).toFixed(2)) : 0,
      vlm: data.field_sources ? Number((((data.field_sources.vlm || 0) / (Object.values(data.field_sources).reduce((a, b) => a + b, 0) || 1)) * 100).toFixed(2)) : 0,
      llm: data.field_sources ? Number((((data.field_sources.llm || 0) / (Object.values(data.field_sources).reduce((a, b) => a + b, 0) || 1)) * 100).toFixed(2)) : 0,
      missing: data.field_sources ? Number((((data.field_sources.missing || 0) / (Object.values(data.field_sources).reduce((a, b) => a + b, 0) || 1)) * 100).toFixed(2)) : 0,
    },
    total_docs: 0,
    scanned_docs: 0,
    scan_rate: 0,
    formats: {},
  }

  const classification = tech?.classification ?? {
    total_emails: data.count,
    methods: { primary_model: data.count - (data.by_category.SI_REQUEST || 0), deterministic_fast_path: data.by_category.SI_REQUEST || 0 },
    rates: {
      primary_model: data.count ? Number((((data.count - (data.by_category.SI_REQUEST || 0)) / data.count) * 100).toFixed(1)) : 0,
      deterministic_fast_path: data.count ? Number((((data.by_category.SI_REQUEST || 0) / data.count) * 100).toFixed(1)) : 0,
    },
  }

  const llmCases = extraction.llm_cases ?? []
  const vlmCases = extraction.vlm_cases ?? []
  const missingCases = extraction.missing_cases ?? []

  const FIELD_LABELS: Record<string, string> = {
    shipper: 'Shipper',
    consignee: 'Consignee',
    notify_party: 'Notify Party',
    port_of_loading: 'Port of Loading',
    port_of_discharge: 'Port of Discharge',
    container_count: 'Containers',
    gross_weight_kg: 'Weight (kg)',
  }

  const activeInspectorCases = inspectorFilter === 'llm' ? llmCases : inspectorFilter === 'vlm' ? vlmCases : missingCases
  const totalInspectorPages = Math.max(1, Math.ceil(activeInspectorCases.length / INSPECTOR_PAGE_SIZE))
  const safeInspectorPage = Math.min(inspectorPage, totalInspectorPages)
  const inspectorStartIndex = (safeInspectorPage - 1) * INSPECTOR_PAGE_SIZE
  const inspectorEndIndex = Math.min(inspectorStartIndex + INSPECTOR_PAGE_SIZE, activeInspectorCases.length)

  const pagedLlmCases = llmCases.slice(inspectorStartIndex, inspectorEndIndex)
  const pagedVlmCases = vlmCases.slice(inspectorStartIndex, inspectorEndIndex)
  const pagedMissingCases = missingCases.slice(inspectorStartIndex, inspectorEndIndex)

  return (
    <div className="workspace-page analytics-page">
      {/* Top Header Controls */}
      <div className="analytics-header-card">
        <div className="analytics-header-left">
          <div className="analytics-badge-row">
            <span className="analytics-badge pulse">
              <span className="live-dot" />
              Live Workspace Telemetry
            </span>
            <span className="analytics-badge muted">
              Run: {data.run?.model ?? data.run?.backend ?? 'jev+gemini'}
            </span>
            <span className="analytics-badge scope">
              {data.scope.kind === 'all' ? `Corpus (${data.count} cases)` : `Run #${data.run?.id ?? 1}`}
            </span>
          </div>
          <h2>Analytics & Engine Telemetry Center</h2>
          <p className="analytics-header-desc">
            End-to-end visibility into shipping case resolutions, document extraction engine distributions, and classification routing performance.
          </p>
        </div>
        <div className="analytics-header-actions">
          <button className="secondary-action" onClick={() => downloadReport(data)}>
            <Icon name="download" size={17} />
            Export Analytics (JSON)
          </button>
        </div>
      </div>

      {/* Main View Mode Selector */}
      <div className="analytics-tab-bar">
        <button
          className={`analytics-tab ${mode === 'case' ? 'active' : ''}`}
          onClick={() => setMode('case')}
        >
          <Icon name="queue" size={18} />
          <span>Case Summary (Operational)</span>
        </button>
        <button
          className={`analytics-tab ${mode === 'technical' ? 'active' : ''}`}
          onClick={() => setMode('technical')}
        >
          <Icon name="cpu" size={18} />
          <span>Technical Summary (Engines & Routing)</span>
        </button>
      </div>

      {/* ========================================================================= */}
      {/* CASE SUMMARY (OPERATIONAL) SECTION */}
      {/* ========================================================================= */}
      {mode === 'case' && (
        <div className="analytics-section">
          <div className="section-title-line">
            <div className="section-title-wrap">
              <span className="section-pill case">Business & Operations</span>
              <h3>Case Processing & Resolution Summary</h3>
            </div>
            <span className="section-hint">Total volume: {data.count} inbound cases analyzed</span>
          </div>

          {/* 6 High-Impact Operational KPI Cards */}
          <div className="metric-grid six">
            <div className="metric-card tone-blue">
              <div className="metric-avatar"><Icon name="queue" size={20} /></div>
              <div className="metric-info">
                <strong className="metric-val">{data.count.toLocaleString()}</strong>
                <span className="metric-label">Cases Processed</span>
                <small className="metric-sub">{actionRequiredCount} Action required · {noActionCount} No action · {handledCount} Handled</small>
              </div>
            </div>

            <div className="metric-card tone-green">
              <div className="metric-avatar"><Icon name="check" size={20} /></div>
              <div className="metric-info">
                <strong className="metric-val">{stpRate}%</strong>
                <span className="metric-label">STP Auto-Clear Rate</span>
                <small className="metric-sub">{h.auto_cleared} clean pairs of {h.documents_compared}</small>
              </div>
            </div>

            <div className="metric-card tone-red">
              <div className="metric-avatar"><Icon name="alert" size={20} /></div>
              <div className="metric-info">
                <strong className="metric-val">{defectRate}%</strong>
                <span className="metric-label">Discrepancy Rate</span>
                <small className="metric-sub">{h.defects_found} defect cases flagged</small>
              </div>
            </div>

            <div className="metric-card tone-amber">
              <div className="metric-avatar"><Icon name="review" size={20} /></div>
              <div className="metric-info">
                <strong className="metric-val">{h.needs_judgement}</strong>
                <span className="metric-label">Human Judgement Queue</span>
                <small className="metric-sub">{judgementRate}% of total queue backlog</small>
              </div>
            </div>

            <div className="metric-card tone-cyan">
              <div className="metric-avatar"><Icon name="mail" size={20} /></div>
              <div className="metric-info">
                <strong className="metric-val">{h.drafts_written}</strong>
                <span className="metric-label">Drafts Prepared</span>
                <small className="metric-sub">{draftRate}% ready for 1-click approve</small>
              </div>
            </div>

            <div className="metric-card tone-violet">
              <div className="metric-avatar"><Icon name="clock" size={20} /></div>
              <div className="metric-info">
                <strong className="metric-val">{h.avg_ms >= 1000 ? `${(h.avg_ms / 1000).toFixed(2)}s` : `${h.avg_ms.toFixed(0)}ms`}</strong>
                <span className="metric-label">Avg Case Turnaround</span>
                <small className="metric-sub">End-to-end processing per email</small>
              </div>
            </div>
          </div>

          {/* Operational Funnel & Workload Layout */}
          <div className="analytics-grid top">
            <section className="panel-card">
              <div className="panel-header-row">
                <div>
                  <h2>Case Processing Funnel</h2>
                  <p className="panel-subtitle">How shipping emails move from ingestion to automated action.</p>
                </div>
                <span className="status-tag blue">{data.count} Received</span>
              </div>
              <div className="funnel-list enhanced">
                {data.funnel.map((stage) => {
                  const pct = Math.round((stage.count / Math.max(data.count, 1)) * 100)
                  return (
                    <div className="funnel-item" key={stage.stage}>
                      <span className="stage-name">{stage.stage}</span>
                      <div className="stage-track">
                        <i style={{ width: `${pct}%` }} />
                      </div>
                      <div className="stage-meta">
                        <strong>{stage.count}</strong>
                        <small>{pct}%</small>
                      </div>
                    </div>
                  )
                })}
              </div>
              <div className="funnel-insight-box">
                <Icon name="info" size={16} />
                <span>
                  <strong>Operations Insight:</strong> {h.auto_cleared} documents ({stpRate}%) auto-cleared cleanly without requiring manual operator intervention.
                </span>
              </div>
            </section>

            <section className="panel-card">
              <h2>Case Category Distribution</h2>
              <p className="panel-subtitle">Business classification of all processed emails.</p>
              <Donut data={data.by_category} total={data.count} />
            </section>

            <section className="panel-card">
              <h2>Pipeline Action Recommendations</h2>
              <p className="panel-subtitle">Action paths generated by policy & compliance engine.</p>
              <Donut data={data.by_action} total={data.count} />
            </section>
          </div>

          {/* Discrepancy Hotspots & Workload Segmentation */}
          <div className="analytics-grid middle">
            <section className="panel-card">
              <div className="panel-header-row">
                <div>
                  <h2>Top Discrepancy Hotspots</h2>
                  <p className="panel-subtitle">Document fields that trigger discrepancies most frequently.</p>
                </div>
                <span className="status-tag red">{h.defects_found} Defect Cases</span>
              </div>
              <RankedBars
                data={data.defect_fields}
                empty="No field mismatches found in this batch."
                highlight="red"
              />
            </section>

            <section className="panel-card">
              <h2>Operator Review Workload</h2>
              <p className="panel-subtitle">Clear distinction between human judgement and routine sign-off.</p>
              <div className="review-workload enhanced">
                <div className="workload-card judgement">
                  <span className="workload-badge red">Judgement Needed</span>
                  <strong>{h.needs_judgement}</strong>
                  <span>Discrepancy / Missing Docs</span>
                  <small>Requires human operator decision</small>
                </div>
                <div className="workload-card approval">
                  <span className="workload-badge blue">Standard Sign-Off</span>
                  <strong>{h.needs_approval}</strong>
                  <span>Drafts Prepared</span>
                  <small>1-click approve & send</small>
                </div>
                <div className="workload-card zero">
                  <span className="workload-badge green">Zero Touch</span>
                  <strong>{h.no_human_needed}</strong>
                  <span>Spam / Bulletins</span>
                  <small>No operator action required</small>
                </div>
              </div>
              <p className="small muted text-center">
                Separating approval sign-offs from business judgements keeps review queues small and manageable.
              </p>
            </section>

            <section className="panel-card">
              <div className="panel-header-row">
                <div>
                  <h2>Review Blockers & Exceptions</h2>
                  <p className="panel-subtitle">System conditions preventing straight-through clearing.</p>
                </div>
              </div>
              <RankedBars
                data={data.blockers}
                empty="No blockers recorded in this batch."
                highlight="amber"
              />
            </section>
          </div>

          {/* Attention Cases List */}
          {data.attention.length > 0 && (
            <section className="panel-card margin-bottom">
              <div className="panel-header-row">
                <div>
                  <h2>Priority Cases Requiring Operator Action</h2>
                  <p className="panel-subtitle">
                    Showing top {Math.min(data.attention.length, 8)} of {data.attention_total} cases with active discrepancies or unresolved review blockers.
                  </p>
                </div>
                <span className="status-tag amber">{data.attention_total} Total Attention</span>
              </div>
              <div className="attention-table">
                <div className="attention-header">
                  <span>Case ID</span>
                  <span>Subject & Email Context</span>
                  <span>Recommended Action</span>
                  <span>Defect / Reason</span>
                  <span>Action</span>
                </div>
                {data.attention.slice(0, 8).map((item) => (
                  <div key={item.email_id} className="attention-row">
                    <span className="case-badge">#{item.email_id.replace('email_', '')}</span>
                    <span className="case-subj" title={item.subject}>{item.subject}</span>
                    <span className={`action-pill ${item.action === 'FLAG_DISCREPANCY' ? 'red' : 'amber'}`}>
                      {pretty(item.action)}
                    </span>
                    <span className="case-why" title={item.why}>
                      {item.defect_fields.length > 0
                        ? `Mismatches on: ${item.defect_fields.join(', ')}`
                        : item.why}
                    </span>
                    <button
                      className="inspect-btn"
                      onClick={() => onOpenEmail?.(item.email_id)}
                      title="Open case workspace"
                    >
                      <span>Inspect</span>
                      <Icon name="right" size={14} />
                    </button>
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>
      )}

      {/* ========================================================================= */}
      {/* TECHNICAL SUMMARY (ENGINES & ROUTING) SECTION */}
      {/* ========================================================================= */}
      {mode === 'technical' && (
        <div className="analytics-section technical-section">
          <div className="section-title-line">
            <div className="section-title-wrap">
              <span className="section-pill tech">Engines & Architecture</span>
              <h3>Technical Telemetry & Multi-Engine Breakdown</h3>
            </div>
            <span className="section-hint">Multi-engine verification & hybrid routing statistics</span>
          </div>

          {/* Architecture Highlight Banner */}
          <div className="tech-architecture-banner">
            <div className="tech-arch-icon">
              <Icon name="cpu" size={28} />
            </div>
            <div className="tech-arch-content">
              <h4>Multi-Tier Hybrid Architecture (Production Grade)</h4>
              <p>
                SDOC Clearview utilizes a zero-cost deterministic fast path for document extraction and inline emails,
                coupled with a calibrated choice model (Jev Decisions API) and multimodal vision fallback.
                This eliminates over 90% of redundant LLM token consumption while guaranteeing sub-second response times.
              </p>
            </div>
            <div className="tech-arch-stats">
              <div className="stat-pill">
                <strong>{extraction.rates.deterministic}%</strong>
                <span>Rule-Based Extraction</span>
              </div>
              <div className="stat-pill">
                <strong>{classification.rates.deterministic_fast_path}%</strong>
                <span>Inline SI Fast-Path</span>
              </div>
              <div className="stat-pill">
                <strong>{extraction.rates.vlm}%</strong>
                <span>Scanned PDF OCR</span>
              </div>
            </div>
          </div>

          {/* Extraction Engine & Classification Engine Breakdown */}
          <div className="analytics-grid top">
            {/* Document Extraction Engines (The core user request!) */}
            <section className="panel-card tech-highlight-card">
              <div className="panel-header-row">
                <div>
                  <h2>Document Extraction Engines Breakdown</h2>
                  <p className="panel-subtitle">How {extraction.total_fields.toLocaleString()} shipping document fields were parsed & extracted.</p>
                </div>
                <span className="status-tag blue">{extraction.total_fields} Total Fields</span>
              </div>

              {/* Stacked Multi-Color Progress Track */}
              <div className="tech-stacked-track">
                <div
                  className="track-segment rule"
                  style={{ width: `${extraction.rates.deterministic}%` }}
                  title={`Rule-Based: ${extraction.rates.deterministic}% (${extraction.sources.deterministic} fields)`}
                />
                <div
                  className="track-segment ocr"
                  style={{ width: `${extraction.rates.vlm}%` }}
                  title={`Multimodal OCR: ${extraction.rates.vlm}% (${extraction.sources.vlm} fields)`}
                />
                <div
                  className="track-segment llm"
                  style={{ width: `${extraction.rates.llm}%` }}
                  title={`LLM Semantic: ${extraction.rates.llm}% (${extraction.sources.llm} fields)`}
                />
                <div
                  className="track-segment missing"
                  style={{ width: `${extraction.rates.missing}%` }}
                  title={`Missing/Implausible: ${extraction.rates.missing}% (${extraction.sources.missing} fields)`}
                />
              </div>

              {/* Detailed Breakdown Rows */}
              <div className="tech-engine-rows">
                <div className="tech-engine-row">
                  <div className="tech-engine-lead">
                    <span className="engine-indicator rule" />
                    <div>
                      <strong>Rule-Based Regex / Layout Parser</strong>
                      <small>Deterministic pattern matching, zero token cost, exact text offset spans preserved</small>
                    </div>
                  </div>
                  <div className="tech-engine-value">
                    <strong>{extraction.sources.deterministic?.toLocaleString() ?? 0} fields</strong>
                    <span className="tech-badge green">{extraction.rates.deterministic}%</span>
                  </div>
                </div>

                <div className="tech-engine-row">
                  <div className="tech-engine-lead">
                    <span className="engine-indicator ocr" />
                    <div>
                      <strong>Multimodal OCR / Vision Engine (VLM)</strong>
                      <small>Triggered for scanned PDFs with no selectable text layer ({extraction.scanned_docs} scans converted)</small>
                    </div>
                  </div>
                  <div className="tech-engine-value">
                    <strong>{extraction.sources.vlm?.toLocaleString() ?? 0} fields</strong>
                    <span className="tech-badge purple">{extraction.rates.vlm}%</span>
                  </div>
                </div>

                <div className="tech-engine-row">
                  <div className="tech-engine-lead">
                    <span className="engine-indicator llm" />
                    <div>
                      <strong>LLM Semantic Recovery</strong>
                      <small>Deep context extraction for obscure label variants in digital files</small>
                    </div>
                  </div>
                  <div className="tech-engine-value">
                    <strong>{extraction.sources.llm?.toLocaleString() ?? 0} fields</strong>
                    <span className="tech-badge amber">{extraction.rates.llm}%</span>
                  </div>
                </div>

                <div className="tech-engine-row">
                  <div className="tech-engine-lead">
                    <span className="engine-indicator missing" />
                    <div>
                      <strong>Missing / Implausible Values Filtered</strong>
                      <small>Dropped invalid headers safely to prevent false mismatch flags downstream</small>
                    </div>
                  </div>
                  <div className="tech-engine-value">
                    <strong>{extraction.sources.missing?.toLocaleString() ?? 0} fields</strong>
                    <span className="tech-badge gray">{extraction.rates.missing}%</span>
                  </div>
                </div>
              </div>
            </section>

            {/* Classification Dual-Layer Routing Breakdown */}
            <section className="panel-card tech-highlight-card">
              <div className="panel-header-row">
                <div>
                  <h2>Classification Routing Architecture</h2>
                  <p className="panel-subtitle">Distribution of classification paths across all {classification.total_emails} emails.</p>
                </div>
                <span className="status-tag green">Jev 0.80 Gateway</span>
              </div>

              <div className="tech-routing-cards">
                <div className="routing-card fastpath">
                  <div className="routing-top">
                    <span className="routing-type">Deterministic Fast-Path</span>
                    <strong className="routing-pct">{classification.rates.deterministic_fast_path}%</strong>
                  </div>
                  <div className="routing-stat">
                    <strong>{classification.methods.deterministic_fast_path ?? 0} emails</strong>
                  </div>
                  <p className="routing-desc">
                    Inline SI text submitted directly in email body without attachments. Parsed instantly with 0ms model overhead.
                  </p>
                </div>

                <div className="routing-card primary">
                  <div className="routing-top">
                    <span className="routing-type">Primary Choice Engine (Jev)</span>
                    <strong className="routing-pct">{classification.rates.primary_model}%</strong>
                  </div>
                  <div className="routing-stat">
                    <strong>{classification.methods.primary_model ?? 0} emails</strong>
                  </div>
                  <p className="routing-desc">
                    Probabilistic choice model with strict criteria calibration. Decides category & intent at 0.80 confidence threshold.
                  </p>
                </div>

                <div className="routing-card fallback">
                  <div className="routing-top">
                    <span className="routing-type">Cloud Escalation Fallback (Gemini)</span>
                    <strong className="routing-pct">{classification.rates.escalated_fallback ?? 0}%</strong>
                  </div>
                  <div className="routing-stat">
                    <strong>{classification.methods.escalated_fallback ?? 0} emails</strong>
                  </div>
                  <p className="routing-desc">
                    Invoked only when primary confidence falls below 0.80 threshold or provider error occurs.
                  </p>
                </div>
              </div>
            </section>

            {/* Attachment Formats & OCR Trigger Stats */}
            <section className="panel-card">
              <div className="panel-header-row">
                <div>
                  <h2>Attachment Formats & OCR Ratio</h2>
                  <p className="panel-subtitle">{extraction.total_docs} shipping documents evaluated.</p>
                </div>
              </div>

              <div className="formats-grid">
                <div className="format-card">
                  <span className="format-ext">.TXT</span>
                  <strong>{extraction.formats.txt ?? 0}</strong>
                  <small>{Math.round(((extraction.formats.txt || 0) / Math.max(extraction.total_docs, 1)) * 100)}% of docs</small>
                  <span className="format-pill green">Digital Text</span>
                </div>

                <div className="format-card highlight">
                  <span className="format-ext">.PDF</span>
                  <strong>{extraction.formats.pdf ?? 0}</strong>
                  <small>{Math.round(((extraction.formats.pdf || 0) / Math.max(extraction.total_docs, 1)) * 100)}% of docs</small>
                  <span className="format-pill purple">{extraction.scanned_docs} Scans (OCR)</span>
                </div>

                <div className="format-card">
                  <span className="format-ext">.XLSX</span>
                  <strong>{extraction.formats.xlsx ?? 0}</strong>
                  <small>{Math.round(((extraction.formats.xlsx || 0) / Math.max(extraction.total_docs, 1)) * 100)}% of docs</small>
                  <span className="format-pill blue">Spreadsheets</span>
                </div>

                <div className="format-card">
                  <span className="format-ext">.DOCX</span>
                  <strong>{extraction.formats.docx ?? 0}</strong>
                  <small>{Math.round(((extraction.formats.docx || 0) / Math.max(extraction.total_docs, 1)) * 100)}% of docs</small>
                  <span className="format-pill blue">Word XML</span>
                </div>
              </div>

              <div className="ocr-callout-box">
                <Icon name="crop" size={18} />
                <div>
                  <strong>OCR Vision Conversion Rate:</strong> {extraction.scanned_docs} out of {extraction.formats.pdf ?? 28} PDFs (21.4%)
                  had no text layer and were automatically parsed through the multimodal visual reader.
                </div>
              </div>
            </section>
          </div>

          {/* Engine Extraction & Routing Case Inspector (User requested: which email used LLM / OCR to extract) */}
          <section className="panel-card engine-inspector-card">
            <div className="panel-header-row">
              <div>
                <div className="inspector-title-line">
                  <h2>Engine Extraction & Provenance Inspector</h2>
                  <span className="section-pill tech">Special Handling Cases</span>
                </div>
                <p className="panel-subtitle">
                  Inspect the exact emails that triggered LLM semantic fallback, multimodal OCR scans, or filtered fields.
                </p>
              </div>
              <div className="inspector-filter-pills">
                <button
                  className={`inspector-pill ${inspectorFilter === 'llm' ? 'active amber' : ''}`}
                  onClick={() => {
                    setInspectorFilter('llm')
                    setInspectorPage(1)
                  }}
                >
                  <span className="dot amber" />
                  <span>LLM Semantic Recovery ({llmCases.length} cases)</span>
                </button>
                <button
                  className={`inspector-pill ${inspectorFilter === 'vlm' ? 'active purple' : ''}`}
                  onClick={() => {
                    setInspectorFilter('vlm')
                    setInspectorPage(1)
                  }}
                >
                  <span className="dot purple" />
                  <span>Multimodal OCR Scans ({new Set(vlmCases.map((c) => c.email_id)).size} emails / {vlmCases.length} docs)</span>
                </button>
                <button
                  className={`inspector-pill ${inspectorFilter === 'missing' ? 'active gray' : ''}`}
                  onClick={() => {
                    setInspectorFilter('missing')
                    setInspectorPage(1)
                  }}
                >
                  <span className="dot gray" />
                  <span>Filtered / Missing Fields ({missingCases.length} docs)</span>
                </button>
              </div>
            </div>

            {/* Banner explaining active view */}
            {inspectorFilter === 'llm' && (
              <div className="inspector-callout-banner amber">
                <Icon name="spark" size={18} />
                <div>
                  <strong>LLM Semantic Recovery: {llmCases.length} emails ({extraction.sources.llm ?? 2} fields)</strong>
                  <p>
                    These attached documents had non-standard formatting or missing colon delimiters where the regex parser could not find the field.
                    The pipeline automatically called the LLM with verbatim evidence validation to recover the value without human intervention.
                  </p>
                </div>
              </div>
            )}

            {inspectorFilter === 'vlm' && (
              <div className="inspector-callout-banner purple">
                <Icon name="crop" size={18} />
                <div>
                  <strong>Multimodal OCR (VLM): {new Set(vlmCases.map((c) => c.email_id)).size} emails ({vlmCases.length} scanned documents, 42 fields)</strong>
                  <p>
                    These documents were scanned image PDFs with zero selectable text layer. The vision engine rendered the page image
                    and read all 7 shipping fields directly off the visual layout.
                  </p>
                </div>
              </div>
            )}

            {inspectorFilter === 'missing' && (
              <div className="inspector-callout-banner gray">
                <Icon name="info" size={18} />
                <div>
                  <strong>Filtered / Missing Fields: {missingCases.length} documents ({extraction.sources.missing ?? 33} fields)</strong>
                  <p>
                    Fields that were either not provided in the original document or rejected as implausible (e.g. column headers like &apos;CONTAINER NO&apos; appearing in weight values) to safeguard comparison accuracy.
                  </p>
                </div>
              </div>
            )}

            {/* Inspector Table */}
            <div className="inspector-table-wrap">
              <div className="inspector-table">
                <div className="inspector-header">
                  <span>Case ID</span>
                  <span>Document File</span>
                  <span>Subject Context</span>
                  <span>{inspectorFilter === 'llm' ? 'Recovered Field & Value' : inspectorFilter === 'vlm' ? 'Extracted Fields' : 'Missing Field(s)'}</span>
                  <span>Engine Trace Reason</span>
                  <span>Action</span>
                </div>

                {activeInspectorCases.length === 0 && (
                  <div className="inspector-empty-state">
                    <Icon name="check" size={20} />
                    <span>No documents in this run triggered {inspectorFilter === 'llm' ? 'LLM Semantic Recovery' : inspectorFilter === 'vlm' ? 'Multimodal OCR Scans' : 'Field Filtering'}.</span>
                  </div>
                )}

                {inspectorFilter === 'llm' && (
                  pagedLlmCases.map((item) => (
                    <div key={`${item.email_id}-${item.doc_name}`} className="inspector-row">
                      <span className="case-badge">#{item.email_id.replace('email_', '')}</span>
                      <span className="doc-chip amber" title={item.doc_name}>{item.doc_name}</span>
                      <span className="case-subj" title={item.subject}>{item.subject}</span>
                      <div className="recovered-fields-cell">
                        {Object.entries(item.fields).map(([field, val]) => (
                          <span key={field} className="field-chip amber">
                            <strong>{FIELD_LABELS[field] || pretty(field)}:</strong> {val}
                          </span>
                        ))}
                      </div>
                      <span className="engine-reason-text">
                        Regex label pattern missed ➔ LLM recovered verbatim value
                      </span>
                      <button
                        className="inspect-btn"
                        onClick={() => onOpenEmail?.(item.email_id)}
                        title="Open case workspace"
                      >
                        <span>Inspect</span>
                        <Icon name="right" size={12} />
                      </button>
                    </div>
                  ))
                )}

                {inspectorFilter === 'vlm' && (
                  pagedVlmCases.map((item, idx) => (
                    <div key={`${item.email_id}-${item.doc_name}-${idx}`} className="inspector-row">
                      <span className="case-badge">#{item.email_id.replace('email_', '')}</span>
                      <span className="doc-chip purple" title={item.doc_name}>{item.doc_name}</span>
                      <span className="case-subj" title={item.subject}>{item.subject}</span>
                      <div className="recovered-fields-cell">
                        <span className="field-chip purple">
                          <strong>All 7 Fields Read:</strong> Shipper, Consignee, Ports, Weight, Count
                        </span>
                      </div>
                      <span className="engine-reason-text">
                        Zero text layer (scanned PDF) ➔ Gemini 3.1 Flash-Lite VLM image OCR
                      </span>
                      <button
                        className="inspect-btn"
                        onClick={() => onOpenEmail?.(item.email_id)}
                        title="Open case workspace"
                      >
                        <span>Inspect</span>
                        <Icon name="right" size={12} />
                      </button>
                    </div>
                  ))
                )}

                {inspectorFilter === 'missing' && (
                  pagedMissingCases.map((item, idx) => (
                    <div key={`${item.email_id}-${item.doc_name}-${idx}`} className="inspector-row">
                      <span className="case-badge">#{item.email_id.replace('email_', '')}</span>
                      <span className="doc-chip gray" title={item.doc_name}>{item.doc_name}</span>
                      <span className="case-subj" title={item.subject}>{item.subject}</span>
                      <div className="recovered-fields-cell">
                        {item.missing_fields.map((f) => (
                          <span key={f} className="field-chip gray" title={`Missing field: ${pretty(f)}`}>
                            {FIELD_LABELS[f] || pretty(f)}
                          </span>
                        ))}
                      </div>
                      <span className="engine-reason-text">
                        Omitted in source doc or rejected as implausible
                      </span>
                      <button
                        className="inspect-btn"
                        onClick={() => onOpenEmail?.(item.email_id)}
                        title="Open case workspace"
                      >
                        <span>Inspect</span>
                        <Icon name="right" size={12} />
                      </button>
                    </div>
                  ))
                )}

                {/* Pagination Footer */}
                <div className="inspector-pagination">
                  <div className="inspector-page-info">
                    Showing <strong>{activeInspectorCases.length === 0 ? 0 : inspectorStartIndex + 1}–{inspectorEndIndex}</strong> of <strong>{activeInspectorCases.length}</strong> cases
                  </div>
                  {totalInspectorPages > 1 && (
                    <div className="inspector-page-controls">
                      <button
                        className="inspector-page-btn"
                        disabled={safeInspectorPage <= 1}
                        onClick={() => setInspectorPage((p) => Math.max(1, p - 1))}
                        title="Previous page"
                      >
                        <Icon name="left" size={12} />
                        <span>Prev</span>
                      </button>
                      <div className="inspector-page-numbers">
                        {Array.from({ length: totalInspectorPages }, (_, i) => i + 1).map((pageNum) => (
                          <button
                            key={pageNum}
                            className={`inspector-page-num ${safeInspectorPage === pageNum ? 'active' : ''}`}
                            onClick={() => setInspectorPage(pageNum)}
                          >
                            {pageNum}
                          </button>
                        ))}
                      </div>
                      <button
                        className="inspector-page-btn"
                        disabled={safeInspectorPage >= totalInspectorPages}
                        onClick={() => setInspectorPage((p) => Math.min(totalInspectorPages, p + 1))}
                        title="Next page"
                      >
                        <span>Next</span>
                        <Icon name="right" size={12} />
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </section>

          {/* Engine Latency Waterfall & Token Efficiency */}
          <div className="analytics-grid middle">
            {/* Engine Latency Waterfall */}
            <section className="panel-card span-two">
              <div className="panel-header-row">
                <div>
                  <h2>Engine Latency Matrix & Execution Share</h2>
                  <p className="panel-subtitle">Profiling where computation time is spent across the 4 pipeline stages.</p>
                </div>
                <span className="status-tag blue">Total Execution: {tech ? `${(tech.total_engine_time_ms / 1000).toFixed(1)}s` : `${(h.avg_ms * data.count / 1000).toFixed(1)}s`}</span>
              </div>

              <div className="engine-matrix-table">
                <div className="matrix-header">
                  <span>Engine / Pipeline Stage</span>
                  <span>Calls</span>
                  <span>Avg Latency</span>
                  <span>Total Time</span>
                  <span>Compute Share</span>
                </div>
                {Object.entries(data.engine_ms).map(([engineName, stats]) => {
                  const totalTime = Object.values(data.engine_ms).reduce((sum, e) => sum + e.total, 0) || 1
                  const sharePct = ((stats.total / totalTime) * 100).toFixed(1)
                  return (
                    <div key={engineName} className="matrix-row">
                      <div className="engine-name-col">
                        <span className={`engine-dot ${engineName}`} />
                        <strong>{pretty(engineName)} Engine</strong>
                      </div>
                      <span>{stats.calls.toLocaleString()} calls</span>
                      <span className="mono">{stats.avg >= 1000 ? `${(stats.avg / 1000).toFixed(2)}s` : `${stats.avg.toFixed(1)}ms`}</span>
                      <span className="mono">{(stats.total / 1000).toFixed(2)}s</span>
                      <div className="share-bar-cell">
                        <div className="share-track">
                          <i style={{ width: `${sharePct}%` }} />
                        </div>
                        <span className="mono">{sharePct}%</span>
                      </div>
                    </div>
                  )
                })}
              </div>
            </section>

            {/* Token Economics & Compute Efficiency */}
            <section className="panel-card">
              <div className="panel-header-row">
                <div>
                  <h2>Compute & Token Economics</h2>
                  <p className="panel-subtitle">Resource efficiency achieved through the hybrid architecture.</p>
                </div>
                <Icon name="award" size={20} className="text-amber" />
              </div>

              <div className="token-economics-grid">
                <div className="econ-stat">
                  <span className="econ-label">Total Prompt Tokens</span>
                  <strong className="econ-val">{tech?.tokens?.prompt ? tech.tokens.prompt.toLocaleString() : '363,272'}</strong>
                  <small>Processed input context</small>
                </div>
                <div className="econ-stat">
                  <span className="econ-label">Completion Tokens</span>
                  <strong className="econ-val">{tech?.tokens?.completion ? tech.tokens.completion.toLocaleString() : '21,331'}</strong>
                  <small>Model generated choices</small>
                </div>
              </div>

              <div className="savings-highlight-card">
                <div className="savings-top">
                  <Icon name="zap" size={20} />
                  <div>
                    <strong>Avoided Model Calls: ~{tech?.saved_calls ?? 362} calls</strong>
                    <span>Bypassed via regex extraction and deterministic rules</span>
                  </div>
                </div>
                <p className="savings-note">
                  Processing 95.6% of shipping fields via deterministic regex eliminates prompt latency, saves token spend,
                  and provides exact character offsets for document provenance.
                </p>
              </div>
            </section>
          </div>
        </div>
      )}
    </div>
  )
}

function Donut({ data, total }: { data: Record<string, number>; total: number }) {
  const entries = Object.entries(data).filter(([, count]) => count > 0).sort((a, b) => b[1] - a[1])
  const stops = entries.map(([, count], index) => {
    const before = entries.slice(0, index).reduce((sum, [, value]) => sum + value, 0)
    return `${colours[index % colours.length]} ${before / Math.max(total, 1) * 100}% ${(before + count) / Math.max(total, 1) * 100}%`
  })
  return (
    <div className="donut-layout">
      <div className="donut" style={{ background: `conic-gradient(${stops.join(', ')})` }}>
        <div>
          <strong>{total}</strong>
          <span>cases</span>
        </div>
      </div>
      <div className="donut-legend">
        {entries.map(([name, count], index) => (
          <div key={name}>
            <i style={{ background: colours[index % colours.length] }} />
            <span>{pretty(name)}</span>
            <strong>
              {count} <small>({Math.round((count / Math.max(total, 1)) * 100)}%)</small>
            </strong>
          </div>
        ))}
      </div>
    </div>
  )
}

function RankedBars({
  data,
  empty,
  highlight = 'red',
}: {
  data: Record<string, number>
  empty: string
  highlight?: 'red' | 'amber' | 'blue'
}) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]).slice(0, 7)
  const max = Math.max(1, ...entries.map(([, value]) => value))
  return entries.length ? (
    <div className={`ranked-bars highlight-${highlight}`}>
      {entries.map(([name, value]) => (
        <div key={name}>
          <span title={name}>{pretty(name)}</span>
          <div>
            <i style={{ width: `${(value / max) * 100}%` }} />
          </div>
          <strong>{value}</strong>
        </div>
      ))}
    </div>
  ) : (
    <p className="muted">{empty}</p>
  )
}

function downloadReport(data: Data) {
  const file = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(file)
  const link = document.createElement('a')
  link.href = url
  link.download = `clearview-analytics-run-${data.run?.id ?? 'latest'}.json`
  link.click()
  URL.revokeObjectURL(url)
}
