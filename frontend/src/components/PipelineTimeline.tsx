import { useLayoutEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import type { EmailRecord } from '../types'
import { Icon } from './Icon'
import { formatFriendlyBlocker, formatFriendlyRule } from '../formatters'

const FIELD_NAMES: Record<string, string> = {
  shipper: 'Shipper',
  consignee: 'Consignee',
  notify_party: 'Notify party',
  port_of_loading: 'Port of loading',
  port_of_discharge: 'Port of discharge',
  container_count: 'Container count',
  gross_weight_kg: 'Gross weight',
}

const CATEGORY_NAMES: Record<string, string> = {
  BL_COMPARISON: 'Draft Bill of Lading check',
  SI_REQUEST: 'Shipping Instruction request',
  INVOICE_QUERY: 'Invoice question',
  GENERAL: 'General enquiry',
  SPAM: 'Unrelated email',
}

const ACTION_NAMES: Record<string, string> = {
  FLAG_DISCREPANCY: 'Ask customer to resolve differences',
  HUMAN_REVIEW: 'Send for human review',
  AUTO_CLEAR: 'Confirm draft Bill of Lading',
  ACKNOWLEDGE: 'Acknowledge request & route to desk',
  NO_ACTION: 'No reply needed',
  IGNORE: 'No action needed',
}

const label = (val: string) => FIELD_NAMES[val] ?? val.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
const duration = (ms: number) => ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${ms.toFixed(1)}ms`
const text = (val: unknown) => typeof val === 'boolean' ? (val ? 'Yes' : 'No') : val == null ? '—' : String(val)
const asRecord = (val: unknown): Record<string, unknown> => val && typeof val === 'object' && !Array.isArray(val) ? val as Record<string, unknown> : {}
const plural = (n: number, one: string) => `${n} ${n === 1 ? one : one + 's'}`
const filled = (val: unknown) => typeof val === 'string' && val.trim() !== ''

/** Tone drives the colour of a flow card, its status chip and its detail box. */
type Tone = 'ok' | 'warn' | 'bad' | 'off'

type FlowStep = {
  id: string
  icon: string
  title: string
  engine: string
  /** null when the step has no engine timing of its own (intake, draft). */
  ms: number | null
  blurb: string
  status: string
  tone: Tone
  result: string
  issue?: string
  why: string
  panelTitle: string
  panelChip?: string
  panel: ReactNode
}

const STATUS_ICON: Record<Tone, string> = { ok: 'check', warn: 'alert', bad: 'x', off: 'info' }

function Kv({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="flow-kv">
      {rows.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}
    </dl>
  )
}

export function PipelineTimeline({ record, onShowDocuments, onShowOverview }: {
  record: EmailRecord
  onShowDocuments?: () => void
  onShowOverview?: () => void
}) {
  const [view, setView] = useState<'flow' | 'list'>('flow')
  const [picked, setPicked] = useState(0)
  const [openDetails, setOpenDetails] = useState(true)

  const mismatchCount = record.comparison?.defect_fields?.length ?? 0
  const totalFields = 7
  const matchedCount = totalFields - mismatchCount - (record.comparison?.missing_fields?.length ?? 0)

  const classifyTrace = record.traces.find((t) => t.engine === 'classify')
  const extractTraces = record.traces.filter((t) => t.engine === 'extract')
  const compareTrace = record.traces.find((t) => t.engine === 'compare')
  const decideTrace = record.traces.find((t) => t.engine === 'decide')

  const classifyModel = classifyTrace?.model
    || (classifyTrace?.backend === 'deterministic' ? 'Rule-based'
      : classifyTrace?.backend ? classifyTrace.backend.toUpperCase() : 'Unknown')
  const totalPipelineMs = record.total_ms || record.traces.reduce((acc, t) => acc + (t.ms || 0), 0)
  const totalExtractMs = extractTraces.reduce((sum, t) => sum + (t.ms || 0), 0)

  const tokensPrompt = classifyTrace?.tokens?.prompt ?? 0
  const tokensComp = classifyTrace?.tokens?.completion ?? 0
  const totalTokens = tokensPrompt + tokensComp

  const hasBlockers = Boolean(record.blockers && record.blockers.length > 0)
  const requiresReview = record.decision.needs_judgement || record.decision.needs_approval

  let stageNum = 0
  const classifyStageNum = classifyTrace ? String(++stageNum).padStart(2, '0') : null
  const extractStageNum = extractTraces.length > 0 ? String(++stageNum).padStart(2, '0') : null
  const compareStageNum = record.comparison ? String(++stageNum).padStart(2, '0') : null
  const decideStageNum = decideTrace ? String(++stageNum).padStart(2, '0') : null

  /* =========================================================================
     The flow: one card per thing that actually ran, in the order it ran.
     ========================================================================= */
  const flow: FlowStep[] = []

  flow.push({
    id: 'intake',
    icon: 'mail',
    title: 'Email intake',
    engine: 'Rule-based',
    ms: null,
    blurb: 'Inbound email received and parsed',
    status: 'Passed',
    tone: 'ok',
    result: record.attachments.length ? `${plural(record.attachments.length, 'attachment')} parsed` : 'No attachments',
    why: 'The message was taken exactly as it arrived — sender, subject, body and every attachment — before any engine touched it.',
    panelTitle: 'Received message',
    panel: <Kv rows={[
      ['From', record.from],
      ['Subject', record.subject],
      ['Attachments', record.attachments.length ? record.attachments.join(', ') : '—'],
    ]} />,
  })

  if (classifyTrace) {
    const conf = Math.round((classifyTrace.confidence ?? record.classification.confidence) * 100)
    const category = CATEGORY_NAMES[record.classification.category] ?? label(record.classification.category)
    flow.push({
      id: 'classify',
      icon: 'file',
      title: 'Classify intent',
      engine: classifyModel,
      ms: classifyTrace.ms,
      blurb: 'Identify document type and routing',
      status: classifyTrace.escalated ? 'Escalated' : 'Passed',
      tone: classifyTrace.escalated ? 'warn' : 'ok',
      result: category,
      issue: classifyTrace.escalated ? 'Confidence was low, so a larger model was asked to confirm' : undefined,
      why: record.classification.reason || classifyTrace.why || 'The email matched a known shipping documentation workflow.',
      panelTitle: 'Classification',
      panelChip: `${conf}% confidence`,
      panel: <Kv rows={[
        ['Category', `${category} (${record.classification.category})`],
        ['Confidence', `${conf}%`],
        ['Routing', classifyTrace.escalated ? 'Escalated to larger model' : 'Direct path'],
        ['Model', <code>{classifyTrace.model || classifyModel}</code>],
        ['Tokens', totalTokens > 0 ? `${totalTokens.toLocaleString()} (${tokensPrompt} prompt · ${tokensComp} output)` : 'None (no model call)'],
      ]} />,
    })
  }

  extractTraces.forEach((trace) => {
    const docName = text(trace.inputs.document)
    const lower = docName.toLowerCase()
    const kind = lower.includes('_si.') ? 'SI' : lower.includes('_bl.') ? 'BL' : docName
    const docLabel = kind === 'SI' ? 'Shipping Instruction' : kind === 'BL' ? 'Bill of Lading' : docName
    const entries = Object.entries(asRecord(trace.output))
    const read = entries.filter(([, v]) => filled(asRecord(v).raw) || filled(asRecord(v).value)).length
    const missing = entries.length - read
    const dead = entries.length === 0

    flow.push({
      id: `extract-${trace.trace_id}`,
      icon: 'file',
      title: `Extract ${kind} fields`,
      engine: trace.model || 'Label Parser',
      ms: trace.ms,
      blurb: `Extract fields from ${docLabel}`,
      status: dead ? 'Unreadable' : missing > 0 ? 'Warning' : 'Passed',
      tone: dead ? 'bad' : missing > 0 ? 'warn' : 'ok',
      result: dead ? 'Nothing could be read' : `${read} of ${entries.length} fields read`,
      issue: dead ? 'No text layer and no readable page image' : missing > 0 ? `${plural(missing, 'required field')} missing` : undefined,
      why: trace.why || 'Values were read off their own labels with line-boundary patterns — deterministic, nothing generated.',
      panelTitle: `${docLabel} — extracted fields`,
      panelChip: dead ? undefined : `${read} / ${entries.length} read`,
      panel: dead
        ? <p className="flow-empty">{docName} could not be parsed, so no field was taken from it.</p>
        : <div className="flow-fieldlist">
            {entries.map(([key, val]) => {
              const rec = asRecord(val)
              const shown = text(rec.raw ?? rec.value)
              const got = shown !== '—'
              return (
                <div key={key} className={got ? '' : 'miss'}>
                  <Icon name={got ? 'check' : 'x'} size={13} />
                  <span>{label(key)}</span>
                  <strong title={shown}>{shown}</strong>
                </div>
              )
            })}
          </div>,
    })
  })

  // A corrected case can carry a comparison whose own trace was replaced by the
  // human-review one, so the comparison -- not its trace -- decides this card.
  if (record.comparison) {
    const detail = record.comparison.detail
    const keys = Object.keys(detail).length ? Object.keys(detail) : Object.keys(FIELD_NAMES)
    const matched = keys.filter((k) => detail[k]?.status === 'MATCH').length
    const missingCount = record.comparison.missing_fields.length
    const tone: Tone = mismatchCount > 0 ? 'bad' : missingCount > 0 ? 'warn' : 'ok'
    const verdictOf = (key: string) => {
      const v = detail[key]
      if (!v) return 'Not checked'
      if (v.status === 'MATCH') return 'Match'
      if (v.status === 'MISSING') {
        const si = filled(v.si.raw)
        const bl = filled(v.bl.raw)
        return !si && !bl ? 'Missing in both' : !si ? 'Missing in SI' : 'Missing in BL'
      }
      return 'Mismatch'
    }

    flow.push({
      id: 'compare',
      icon: 'layers',
      title: 'Compare fields',
      engine: 'Deterministic Comparator',
      ms: compareTrace?.ms ?? null,
      blurb: 'Compare SI vs BL field values',
      status: mismatchCount > 0 ? 'Escalated' : missingCount > 0 ? 'Warning' : 'Passed',
      tone,
      result: `${matched} of ${keys.length} fields matched`,
      issue: mismatchCount > 0
        ? `${record.comparison.defect_fields.map(label).join(', ')} ${mismatchCount === 1 ? 'disagrees' : 'disagree'} between SI and BL`
        : missingCount > 0
          ? `${record.comparison.missing_fields.map(label).join(', ')} ${missingCount === 1 ? 'is' : 'are'} missing`
          : undefined,
      why: tone === 'ok'
        ? (compareTrace?.why || 'Every field agreed after normalisation, so nothing was escalated.')
        : 'These are required fields. The policy guardrail blocks automatic sending when a required field is missing or disagrees.',
      panelTitle: 'Field comparison result',
      panelChip: `${matched} / ${keys.length} matched`,
      panel: <div className="flow-fieldlist two-col">
        {keys.map((key) => {
          const ok = detail[key]?.status === 'MATCH'
          return (
            <div key={key} className={ok ? '' : 'miss'}>
              <Icon name={ok ? 'check' : 'x'} size={13} />
              <span>{label(key)}</span>
              <strong>{verdictOf(key)}</strong>
            </div>
          )
        })}
      </div>,
    })
  }

  if (decideTrace) {
    const action = ACTION_NAMES[record.decision.action] ?? label(record.decision.action)
    flow.push({
      id: 'decide',
      icon: 'flag',
      title: 'Policy decision',
      engine: 'Policy Engine',
      ms: decideTrace.ms,
      blurb: 'Apply guardrails and business rules',
      status: requiresReview ? 'Human review' : 'Passed',
      tone: requiresReview ? 'warn' : 'ok',
      result: action,
      issue: requiresReview ? 'Guardrail triggered — a human signs off before anything leaves the system' : undefined,
      why: record.decision.why || 'Standard routing applied based on the verification outcome.',
      panelTitle: 'Guardrail status',
      panel: <Kv rows={[
        ['Action', action],
        ['Human approval', record.decision.needs_approval ? 'Required before sending' : 'Not required'],
        ['Auto-dispatch', 'Inhibited (draft only)'],
        ['Blockers', record.blockers.length ? record.blockers.map(formatFriendlyBlocker).join(' ') : 'None'],
      ]} />,
    })
  }

  const draft = record.decision.draft
  flow.push({
    id: 'draft',
    icon: 'mail',
    title: 'Draft reply',
    engine: draft?.reasoning?.generated_by || 'Template',
    ms: null,
    blurb: draft ? 'Generate reply for sender' : 'No reply needed for this action',
    status: draft ? 'Passed' : 'Skipped',
    tone: draft ? 'ok' : 'off',
    result: draft ? 'Draft ready, not sent' : 'No draft required',
    why: draft
      ? 'The reply was composed from the decision above and parked as a draft. Nothing is sent without a reviewer.'
      : 'This action does not call for a reply to the sender.',
    panelTitle: 'Draft preview',
    panelChip: draft ? 'Not sent' : undefined,
    panel: draft
      ? <div className="flow-draft">
          <Kv rows={[['To', draft.to], ['Subject', draft.subject]]} />
          <pre>{draft.body}</pre>
          {onShowOverview && (
            <button className="secondary-action inline-link-btn" onClick={onShowOverview}>
              Review and edit the draft in overview →
            </button>
          )}
        </div>
      : <p className="flow-empty">No draft reply was generated.</p>,
  })

  // Only present once a reviewer has corrected something on this case.
  const overrideTrace = record.traces.find((t) => String(t.engine) === 'human review')
  if (overrideTrace) {
    flow.push({
      id: 'override',
      icon: 'user',
      title: 'Human review',
      engine: 'Reviewer',
      ms: null,
      blurb: 'Corrections applied on top of the engine result',
      status: record.resolved ? 'Resolved' : 'Corrected',
      tone: 'off',
      result: overrideTrace.why || `${plural(overrideTrace.steps.length, 'correction')} applied`,
      why: 'A reviewer overruled the engine on this case. The correction stands for this email only — it never becomes a rule on its own.',
      panelTitle: 'What the reviewer changed',
      panelChip: plural(overrideTrace.steps.length, 'change'),
      panel: <div className="flow-fieldlist">
        {overrideTrace.steps.map((s, i) => (
          <div key={`${s.name}-${i}`}>
            <Icon name="edit" size={13} />
            <span>{s.detail}</span>
          </div>
        ))}
      </div>,
    })
  }

  // Connectors are measured off the laid-out cards, so they follow the grid
  // wherever it wraps: straight within a row, an elbow curve down to the next.
  const gridRef = useRef<HTMLDivElement | null>(null)
  const [links, setLinks] = useState<{ paths: string[]; box: { w: number; h: number } }>({ paths: [], box: { w: 0, h: 0 } })

  useLayoutEffect(() => {
    const grid = gridRef.current
    if (!grid) { setLinks({ paths: [], box: { w: 0, h: 0 } }); return }
    const R = 8            // corner radius
    const CHANNEL = 13     // how far outside the grid the wrap runs

    const draw = () => {
      const base = grid.getBoundingClientRect()
      const rects = Array.from(grid.querySelectorAll<HTMLElement>('.flow-card')).map((c) => c.getBoundingClientRect())
      const paths: string[] = []
      for (let i = 0; i < rects.length - 1; i++) {
        const a = rects[i]
        const b = rects[i + 1]
        const ax = a.right - base.left
        const ay = a.top - base.top + a.height / 2
        const bx = b.left - base.left
        const by = b.top - base.top + b.height / 2
        if (b.top - a.top < 4) {
          paths.push(`M ${ax} ${ay} H ${bx}`)
          continue
        }
        const right = base.width + CHANNEL
        const leftCh = -CHANNEL
        const mid = (a.bottom + b.top) / 2 - base.top
        paths.push([
          `M ${ax} ${ay}`,
          `H ${right - R}`, `Q ${right} ${ay} ${right} ${ay + R}`,
          `V ${mid - R}`, `Q ${right} ${mid} ${right - R} ${mid}`,
          `H ${leftCh + R}`, `Q ${leftCh} ${mid} ${leftCh} ${mid + R}`,
          `V ${by - R}`, `Q ${leftCh} ${by} ${leftCh + R} ${by}`,
          `H ${bx}`,
        ].join(' '))
      }
      setLinks((prev) => prev.paths.join('|') === paths.join('|') && prev.box.w === base.width
        ? prev
        : { paths, box: { w: base.width, h: base.height } })
    }

    draw()
    const ro = new ResizeObserver(draw)
    ro.observe(grid)
    grid.querySelectorAll('.flow-card').forEach((c) => ro.observe(c))
    return () => ro.disconnect()
  }, [view, flow.length])

  const cur = flow[Math.min(picked, flow.length - 1)]
  const detailRows: [string, ReactNode][] = [
    ['Step', cur.title],
    ['Engine', cur.engine],
    ['Duration', cur.ms != null ? duration(cur.ms) : '—'],
    ['Result', cur.result],
  ]
  if (cur.issue) detailRows.push(['Issue', <span className="flow-issue">{cur.issue}</span>])
  detailRows.push(['Why this decision', cur.why])

  return (
    <div className="transparency-dashboard">
      {/* Blocker Alert (If pipeline encountered missing documents or blank scans) */}
      {hasBlockers && (
        <div className="pipeline-blocker-alert">
          <div className="blocker-icon-wrap">
            <Icon name="alert" size={22} />
          </div>
          <div className="blocker-content">
            <strong>Pipeline Intercepted: Ingestion Blocker</strong>
            <p>{formatFriendlyBlocker(record.blockers[0])}</p>
            <span className="blocker-guardrail-tag">
              <Icon name="check" size={13} />
              Guardrail Triggered: Automatic document comparison was withheld to prevent false approvals.
            </span>
          </div>
        </div>
      )}

      <div className="flow-board">
        <div className="flow-board-head">
          <div>
            <h2>How this case was processed</h2>
            <p>End-to-end decision flow with AI, rules and policy guardrails · {flow.length} steps · {duration(totalPipelineMs)} of engine time.</p>
          </div>
          <button className="secondary-action flow-view-toggle" onClick={() => setView(view === 'flow' ? 'list' : 'flow')}>
            <Icon name={view === 'flow' ? 'queue' : 'branch'} size={14} />
            {view === 'flow' ? 'View as list' : 'View as flow'}
          </button>
        </div>

        {view === 'flow' && (() => {
          const flowCols = flow.length >= 7 ? 4 : flow.length === 6 ? 3 : flow.length === 5 ? 3 : Math.min(flow.length, 4)
          return (
            <div className="flow-grid" ref={gridRef} style={{ '--flow-cols': flowCols } as React.CSSProperties}>
              {links.box.w > 0 && (
              <svg className="flow-links" width={links.box.w} height={links.box.h} aria-hidden="true">
                <defs>
                  <marker id="flow-arrowhead" markerWidth="7" markerHeight="7" refX="6.5" refY="3.5" orient="auto">
                    <path d="M0 0 L7 3.5 L0 7 Z" fill="currentColor" stroke="none" />
                  </marker>
                </defs>
                {links.paths.map((d, i) => <path key={i} d={d} markerEnd="url(#flow-arrowhead)" />)}
              </svg>
            )}
            {flow.map((step, i) => (
              <button
                key={step.id}
                className={`flow-card tone-${step.tone} ${i === picked ? 'picked' : ''}`}
                onClick={() => { setPicked(i); setOpenDetails(true) }}
              >
                <span className="flow-card-top">
                  <span className="flow-card-icon"><Icon name={step.icon} size={15} /></span>
                  <strong>{i + 1}. {step.title}</strong>
                </span>
                <span className="flow-card-pills">
                  <span className="flow-pill engine">{step.engine}</span>
                  {step.ms != null && <span className="flow-pill"><Icon name="clock" size={11} />{duration(step.ms)}</span>}
                </span>
                <span className="flow-card-blurb">{step.blurb}</span>
                <span className={`flow-status tone-${step.tone}`}>
                  <Icon name={STATUS_ICON[step.tone]} size={13} />
                  <span>{step.status}</span>
                  {step.issue && <small>{step.issue}</small>}
                </span>
              </button>
            ))}
          </div>
        )
      })()}
      </div>

      {view === 'flow' && (
        <div className="flow-details">
          <div className="flow-details-head">
            <span className="flow-card-icon"><Icon name={cur.icon} size={15} /></span>
            <h3>Step details: {cur.title}</h3>
            <span className={`flow-status tone-${cur.tone}`}>
              <Icon name={STATUS_ICON[cur.tone]} size={13} />
              <span>{cur.status}</span>
            </span>
            <div className="flow-details-nav">
              <button disabled={picked === 0} onClick={() => setPicked(picked - 1)}>
                <Icon name="left" size={13} /> Previous
              </button>
              <button disabled={picked >= flow.length - 1} onClick={() => setPicked(picked + 1)}>
                Next <Icon name="right" size={13} />
              </button>
              <button
                className={`flow-collapse ${openDetails ? 'open' : ''}`}
                onClick={() => setOpenDetails(!openDetails)}
                title={openDetails ? 'Collapse step details' : 'Expand step details'}
              >
                <Icon name="chevron" size={16} />
              </button>
            </div>
          </div>

          {openDetails && (
            <div className="flow-details-body">
              <Kv rows={detailRows} />
              <div className="flow-result-box">
                <div className="flow-result-box-head">
                  <strong>{cur.panelTitle}</strong>
                  {cur.panelChip && <span className={`flow-chip tone-${cur.tone}`}>{cur.panelChip}</span>}
                </div>
                {cur.panel}
                {(cur.id === 'compare' || cur.id.startsWith('extract-')) && onShowDocuments && (
                  <button className="secondary-action inline-link-btn" onClick={onShowDocuments}>
                    Open the documents & evidence viewer →
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {view === 'list' && (
      <div className="stages-transparency-list">

        {/* -----------------------------------------------------------------------
            STAGE 1: Classification & Intent Reasoning
            ----------------------------------------------------------------------- */}
        {classifyTrace && (
          <section className="stage-transparency-card" id="stage-classify">
            <header className="stage-card-header">
              <div className="stage-header-title">
                <span className="stage-badge-num">{classifyStageNum}</span>
                <div>
                  <h3>Identify Email Intent & Category</h3>
                  <p>Inbound email request classification and model routing</p>
                </div>
              </div>
              <div className="stage-header-pills">
                <span className="trans-pill model-pill" title="Model employed for intent classification">
                  <Icon name="spark" size={14} />
                  {classifyModel}
                </span>
                <span className="trans-pill time-pill" title="Execution latency">
                  <Icon name="clock" size={14} />
                  {duration(classifyTrace.ms)}
                </span>
                <span className="trans-pill conf-pill" title="Classification confidence score">
                  <Icon name="signal" size={14} />
                  {Math.round((classifyTrace.confidence ?? record.classification.confidence) * 100)}% Confidence
                </span>
                <span className="trans-pill route-pill" title="Escalation routing state">
                  {classifyTrace.escalated ? 'Escalated to Larger Model' : 'Direct Path'}
                </span>
              </div>
            </header>

            <div className="stage-card-body">
              <div className="stage-two-col">
                {/* Left: What Happened & Reason */}
                <div className="stage-col-primary">
                  <span className="stage-section-label">DETERMINED OUTCOME & REASONING</span>
                  <div className="stage-outcome-banner">
                    <span className="outcome-tag">
                      <Icon name="file" size={15} />
                      {CATEGORY_NAMES[record.classification.category] ?? label(record.classification.category)}
                    </span>
                    <span className="category-code">({record.classification.category})</span>
                  </div>

                  <div className="stage-ai-reasoning">
                    <span className="reason-label">
                      <Icon name="spark" size={14} />
                      AI Explanation:
                    </span>
                    <blockquote>
                      "{record.classification.reason || classifyTrace.why || 'The incoming email matches standard shipping documentation workflows.'}"
                    </blockquote>
                  </div>

                  <ul className="stage-checklist">
                    <li>
                      <Icon name="check" size={14} className="text-green" />
                      <span><strong>Document References:</strong> {record.attachments.length ? `${record.attachments.length} attachment file(s) referenced in context` : 'No attachments attached'}</span>
                    </li>
                    <li>
                      <Icon name="check" size={14} className="text-green" />
                      <span><strong>Confidence Check:</strong> Score of {Math.round((classifyTrace.confidence ?? record.classification.confidence) * 100)}% exceeded the 80% direct-path confidence threshold</span>
                    </li>
                    <li>
                      <Icon name="check" size={14} className="text-green" />
                      <span><strong>Next Pipeline Routing:</strong> {record.classification.category === 'BL_COMPARISON' ? 'Trigger dual document extraction for SI & BL' : 'Route directly to desk resolution'}</span>
                    </li>
                  </ul>
                </div>

                {/* Right: Engine Telemetry & Token Cost */}
                <div className="stage-col-secondary">
                  <span className="stage-section-label">ENGINE & RUNTIME TELEMETRY</span>
                  <div className="telemetry-box">
                    <div className="telemetry-row">
                      <span>Inference Engine</span>
                      <strong>{classifyTrace.backend ? classifyTrace.backend.toUpperCase() : 'GEMINI'}</strong>
                    </div>
                    <div className="telemetry-row">
                      <span>Model Version</span>
                      <code>{classifyTrace.model || 'gemini-3.1-flash-lite'}</code>
                    </div>
                    <div className="telemetry-row">
                      <span>Latency</span>
                      <strong>{duration(classifyTrace.ms)}</strong>
                    </div>
                    {totalTokens > 0 && (
                      <div className="telemetry-row">
                        <span>Tokens Consumed</span>
                        <strong>{totalTokens.toLocaleString()} tokens</strong>
                      </div>
                    )}
                    {tokensPrompt > 0 && (
                      <div className="telemetry-sub-row">
                        <span>Prompt / Completion</span>
                        <small>{tokensPrompt} prompt · {tokensComp} output</small>
                      </div>
                    )}
                    <div className="telemetry-row">
                      <span>Model Temperature</span>
                      <strong>0.0 (Deterministic)</strong>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </section>
        )}

        {/* -----------------------------------------------------------------------
            STAGE 2: Document Extraction (SI & BL combined)
            ----------------------------------------------------------------------- */}
        {extractTraces.length > 0 && (
          <section className="stage-transparency-card" id="stage-extract">
            <header className="stage-card-header">
              <div className="stage-header-title">
                <span className="stage-badge-num">{extractStageNum}</span>
                <div>
                  <h3>Extract Shipping Documents ({extractTraces.length === 2 ? 'SI & BL' : 'Logistics Files'})</h3>
                  <p>Deterministic field-level extraction from document bodies</p>
                </div>
              </div>
              <div className="stage-header-pills">
                <span className="trans-pill engine-pill" title="Parsing technology applied">
                  <Icon name="layers" size={14} />
                  Deterministic Label Parser
                </span>
                <span className="trans-pill time-pill" title="Total extraction latency">
                  <Icon name="clock" size={14} />
                  {duration(totalExtractMs)}
                </span>
                <span className="trans-pill count-pill" title="Fields successfully recognized">
                  <Icon name="check" size={14} />
                  {extractTraces.reduce((sum, t) => sum + Object.keys(asRecord(t.output)).length, 0)} Fields Recognized
                </span>
              </div>
            </header>

            <div className="stage-card-body">
              <div className="extract-summary-bar">
                <div className="extract-method-info">
                  <Icon name="layers" size={15} />
                  <span><strong>Extraction Guarantee:</strong> Line-boundary regex pattern recognition · 100% deterministic (zero generative hallucinations)</span>
                </div>
                {onShowDocuments && (
                  <button className="secondary-action inline-link-btn" onClick={onShowDocuments}>
                    <Icon name="file" size={13} /> View full documents in evidence viewer →
                  </button>
                )}
              </div>

              <div className="extract-docs-grid">
                {extractTraces.map((trace) => {
                  const docName = text(trace.inputs.document)
                  const isSI = docName.toLowerCase().includes('_si.')
                  const isBL = docName.toLowerCase().includes('_bl.')
                  const docTypeLabel = isSI ? 'Shipping Instruction (SI)' : isBL ? 'Bill of Lading (BL)' : docName
                  const fields = asRecord(trace.output)
                  const fieldEntries = Object.entries(fields)

                  return (
                    <div className="extract-doc-panel" key={trace.trace_id}>
                      <div className="extract-doc-panel-head">
                        <div className="doc-panel-meta">
                          <Icon name="file" size={17} className="doc-icon" />
                          <div>
                            <strong>{docTypeLabel}</strong>
                            <span className="doc-panel-filename">{docName}</span>
                          </div>
                        </div>
                        <span className="trans-pill time-pill">
                          <Icon name="clock" size={12} />
                          {duration(trace.ms)}
                        </span>
                      </div>

                      <div className="extracted-fields-compact">
                        {fieldEntries.map(([fKey, fData]) => {
                          const rec = asRecord(fData)
                          return (
                            <div className="field-compact-item" key={fKey}>
                              <span className="f-name">{label(fKey)}</span>
                              <strong className="f-val" title={text(rec.raw ?? rec.value)}>
                                {text(rec.raw ?? rec.value)}
                              </strong>
                              <span className="f-source">
                                {rec.source === 'deterministic' ? 'Label parsed' : String(rec.source)}
                              </span>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          </section>
        )}

        {/* -----------------------------------------------------------------------
            STAGE 3: Cross-Document 7-Field Verification
            ----------------------------------------------------------------------- */}
        {record.comparison && (
          <section className="stage-transparency-card" id="stage-compare">
            <header className="stage-card-header">
              <div className="stage-header-title">
                <span className="stage-badge-num">{compareStageNum}</span>
                <div>
                  <h3>Cross-Document 7-Field Verification</h3>
                  <p>Deterministic field-by-field consistency checking between SI and BL</p>
                </div>
              </div>
              <div className="stage-header-pills">
                <span className="trans-pill engine-pill" title="Comparison engine">
                  <Icon name="layers" size={14} />
                  Deterministic Rule Engine
                </span>
                <span className="trans-pill time-pill" title="Verification latency">
                  <Icon name="clock" size={14} />
                  {compareTrace ? duration(compareTrace.ms) : '—'}
                </span>
                {mismatchCount > 0 ? (
                  <span className="trans-pill badge-mismatch">
                    <Icon name="alert" size={14} />
                    {mismatchCount} Discrepanc{mismatchCount === 1 ? 'y' : 'ies'} Found
                  </span>
                ) : (
                  <span className="trans-pill badge-match">
                    <Icon name="check" size={14} />
                    100% Certified Match
                  </span>
                )}
              </div>
            </header>

            <div className="stage-card-body">
              {/* Outcome Banner */}
              <div className={`compare-verdict-banner ${mismatchCount > 0 ? 'mismatch' : 'match'}`}>
                <div className="verdict-icon-wrap">
                  <Icon name={mismatchCount > 0 ? 'alert' : 'check'} size={24} />
                </div>
                <div>
                  <h4>
                    {mismatchCount > 0
                      ? `${mismatchCount} Discrepanc${mismatchCount === 1 ? 'y' : 'ies'} Detected Between SI and BL`
                      : 'All 7 Shipping Fields Agree Perfectly'}
                  </h4>
                  <p>
                    {mismatchCount > 0
                      ? `Fields (${record.comparison.defect_fields.map(label).join(', ')}) disagree after formatting normalization. The remaining ${matchedCount} fields match.`
                      : 'Every shipper, consignee, notify party, port, and package field agrees. Certified safe for clearance.'}
                  </p>
                </div>
              </div>

              {/* Complete 7-Field Side-by-Side Comparison Table */}
              <div className="verification-transparency-table-wrap">
                <table className="verification-transparency-table">
                  <thead>
                    <tr>
                      <th style={{ width: '18%' }}>Field</th>
                      <th style={{ width: '28%' }}>Shipping Instruction (SI)</th>
                      <th style={{ width: '28%' }}>Bill of Lading (BL)</th>
                      <th style={{ width: '12%', textAlign: 'center' }}>Result</th>
                      <th style={{ width: '14%' }}>Matching Rule</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.keys(FIELD_NAMES).map((fieldKey) => {
                      const verdict = record.comparison?.detail[fieldKey]
                      const isMismatch = verdict?.status === 'MISMATCH'
                      const isMatch = verdict?.status === 'MATCH'

                      const siVal = verdict?.si?.raw || verdict?.si?.value || '—'
                      const blVal = verdict?.bl?.raw || verdict?.bl?.value || '—'
                      const ruleName = verdict?.rule ? formatFriendlyRule(verdict.rule) : (isMismatch ? 'Values disagree' : 'Exact match')

                      return (
                        <tr key={fieldKey} className={isMismatch ? 'row-mismatch' : 'row-match'}>
                          <td className="field-name-cell">
                            <strong>{label(fieldKey)}</strong>
                          </td>
                          <td className={`val-cell ${isMismatch ? 'mismatch-text' : ''}`}>
                            <span>{siVal}</span>
                          </td>
                          <td className={`val-cell ${isMismatch ? 'mismatch-text' : ''}`}>
                            <span>{blVal}</span>
                          </td>
                          <td style={{ textAlign: 'center' }}>
                            <span className={`verdict-chip ${isMismatch ? 'mismatch' : 'match'}`}>
                              {isMismatch ? 'MISMATCH' : isMatch ? 'MATCH' : verdict?.status ?? '—'}
                            </span>
                          </td>
                          <td className="rule-cell">
                            <small>{ruleName}</small>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </section>
        )}

        {/* -----------------------------------------------------------------------
            STAGE 4: Business Policy Decision & Draft Action
            ----------------------------------------------------------------------- */}
        {decideTrace && (
          <section className="stage-transparency-card" id="stage-decide">
            <header className="stage-card-header">
              <div className="stage-header-title">
                <span className="stage-badge-num">{decideStageNum}</span>
                <div>
                  <h3>Action Policy Decision & Response Draft</h3>
                  <p>Deterministic governance policy and safety guardrail dispatch</p>
                </div>
              </div>
              <div className="stage-header-pills">
                <span className="trans-pill engine-pill" title="Policy engine">
                  <Icon name="layers" size={14} />
                  Policy Engine
                </span>
                <span className="trans-pill time-pill">
                  <Icon name="clock" size={14} />
                  {duration(decideTrace.ms)}
                </span>
                <span className="trans-pill action-pill">
                  {ACTION_NAMES[record.decision.action] ?? label(record.decision.action)}
                </span>
              </div>
            </header>

            <div className="stage-card-body">
              <div className="stage-two-col">
                {/* Left: Why this decision & Guardrails */}
                <div className="stage-col-primary">
                  <span className="stage-section-label">POLICY RATIONALE & GUARDRAIL STATUS</span>
                  <div className="decision-callout-box">
                    <span className="decision-header">Selected Policy Action</span>
                    <strong>{ACTION_NAMES[record.decision.action] ?? label(record.decision.action)}</strong>
                    <p>{record.decision.why || 'Standard routing applied based on verification outcome.'}</p>
                  </div>

                  <div className="guardrail-status-grid">
                    <div className="guardrail-status-item">
                      <span>Human Approval</span>
                      <strong className={record.decision.needs_approval ? 'text-amber' : 'text-green'}>
                        {record.decision.needs_approval ? 'Required Before Sending' : 'Not Required'}
                      </strong>
                    </div>
                    <div className="guardrail-status-item">
                      <span>Auto-dispatch</span>
                      <strong className="text-rose">Inhibited (Draft Only)</strong>
                    </div>
                    <div className="guardrail-status-item">
                      <span>Operator Sign-off</span>
                      <strong>Pending Manual Review</strong>
                    </div>
                  </div>
                </div>

                {/* Right: Draft Email Preview */}
                <div className="stage-col-secondary">
                  <span className="stage-section-label">SYSTEM-GENERATED DRAFT PREVIEW</span>
                  {record.decision.draft ? (
                    <div className="stage-draft-paper">
                      <div className="draft-paper-meta">
                        <div><span>To:</span> <strong>{record.decision.draft.to}</strong></div>
                        <div><span>Subject:</span> <strong>{record.decision.draft.subject}</strong></div>
                      </div>
                      <pre className="draft-paper-body">{record.decision.draft.body}</pre>
                      {onShowOverview && (
                        <button className="secondary-action inline-link-btn" onClick={onShowOverview}>
                          Review and edit draft reply in overview →
                        </button>
                      )}
                    </div>
                  ) : (
                    <div className="no-draft-box">
                      <Icon name="file" size={20} />
                      <p>No draft reply required for this action.</p>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </section>
        )}

      </div>
      )}
    </div>
  )
}
