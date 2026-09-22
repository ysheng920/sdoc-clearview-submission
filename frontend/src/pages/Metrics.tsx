import { useEffect, useState } from 'react'
import { api } from '../api'
import { Badge, CategoryBadge } from '../components/Badges'
import type { Metrics as M } from '../types'

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="card stat">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  )
}

function BarList({ data }: { data: Record<string, number> }) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1])
  const max = Math.max(1, ...entries.map(([, v]) => v))
  return (
    <>
      {entries.map(([k, v]) => (
        <div className="bar-row" key={k}>
          <span className="small muted">{k.replace(/_/g, ' ')}</span>
          <div className="bar-track">
            <div className="bar" style={{ width: `${(v / max) * 100}%` }} />
          </div>
          <span className="mono small faint" style={{ textAlign: 'right' }}>{v}</span>
        </div>
      ))}
    </>
  )
}

export function Metrics({ reloadKey = 0 }: { reloadKey?: number }) {
  const [m, setM] = useState<M | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.metrics().then(setM).catch((e) => setError(String(e)))
  }, [reloadKey])

  // An empty database answers 404; that is a state, not a failure.
  if (error) {
    return (
      <div className="empty-state">
        {error.includes("404")
          ? "No run yet — compose one from Run pipeline."
          : error}
      </div>
    )
  }
  // Loading and empty must not look the same, or a slow fetch reads as "no data".
  if (!m) return <div className="empty-state">Loading…</div>
  if (!m.count) return <div className="empty-state">No run yet — start one from the toolbar.</div>

  const caught = m.errors_caught_by_router ?? 0
  const errs = m.errors ?? 0
  // With no cloud backend configured nothing actually escalates, so the real
  // escalation_rate is 0. Quoting that as the cost would understate it -- the
  // honest figure is how many were flagged low-confidence and would have gone.
  const noCloud = m.escalated === 0 && m.low_confidence > 0
  const costRate = noCloud ? m.low_confidence / m.count : m.escalation_rate

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div className="stats">
        <Stat label="Emails processed" value={String(m.count)} sub={`run #${m.run_id}`} />
        <Stat
          label="Average latency"
          value={`${m.avg_ms.toFixed(1)}ms`}
          sub="per email, all four engines"
        />
        <Stat
          label={noCloud ? 'Would escalate' : 'Escalated to cloud'}
          value={`${(costRate * 100).toFixed(1)}%`}
          sub={
            noCloud
              ? `${m.low_confidence} flagged low-confidence; no cloud backend configured, so nothing left this machine`
              : `${m.escalated} of ${m.count} left this machine`
          }
        />
        <Stat
          label="Awaiting approval"
          value={String(m.needs_approval)}
          sub="drafts a human must sign off"
        />
        {m.accuracy !== undefined && (
          <Stat
            label="Classification accuracy"
            value={`${(m.accuracy * 100).toFixed(1)}%`}
            sub={`scored against ${m.scored} labelled emails`}
          />
        )}
      </div>

      {m.accuracy !== undefined && (
        <div className="card">
          <h3>Does the router catch what the model gets wrong?</h3>
          <p className="small muted" style={{ marginTop: 0 }}>
            The point of a confidence router is not that the local model is never wrong —
            it is that it knows when it might be. Of <strong>{errs}</strong> misclassification
            {errs === 1 ? '' : 's'}, <strong>{caught}</strong> fell below the confidence
            threshold and would be re-asked of the larger model.
          </p>
          <div className="row" style={{ gap: 14 }}>
            <Badge tone={errs === 0 || caught === errs ? 'ok' : 'warn'}>
              {errs === 0 ? 'no errors' : `${((caught / errs) * 100).toFixed(0)}% of errors caught`}
            </Badge>
            <span className="small faint">
              at {(costRate * 100).toFixed(1)}% escalation cost
              {noCloud && ' (would-be — no cloud backend configured)'}
            </span>
          </div>

          {m.confusions && m.confusions.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <div className="diff-row head" style={{ gridTemplateColumns: '120px 1fr 1fr 110px' }}>
                <span>Email</span><span>Should be</span><span>Predicted</span><span>Confidence</span>
              </div>
              {m.confusions.slice(0, 12).map((c) => (
                <div key={c.email_id} className="diff-row" style={{ gridTemplateColumns: '120px 1fr 1fr 110px' }}>
                  <span className="mono small">{c.email_id}</span>
                  <span><CategoryBadge value={c.truth} /></span>
                  <span><CategoryBadge value={c.predicted} /></span>
                  <span className="mono small">
                    {(c.confidence * 100).toFixed(0)}%
                    {c.confidence < 0.6 && <Badge tone="ok" title="Below threshold — router catches it">caught</Badge>}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="two-col">
        <div className="card">
          <h3>By category</h3>
          <BarList data={m.by_category} />
        </div>
        <div className="card">
          <h3>By action taken</h3>
          <BarList data={m.by_action} />
        </div>
      </div>

      {Object.keys(m.by_verdict).length > 0 && (
        <div className="card">
          <h3>Document comparison outcomes</h3>
          <BarList data={m.by_verdict} />
        </div>
      )}
    </div>
  )
}
