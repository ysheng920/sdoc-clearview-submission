const CATEGORY_TONE: Record<string, string> = {
  BL_COMPARISON: 'accent',
  SI_REQUEST: 'info',
  INVOICE_QUERY: 'warn',
  GENERAL: 'neutral',
  SPAM: 'bad',
}

const STATUS_TONE: Record<string, string> = {
  OK: 'ok',
  MATCH: 'ok',
  MISMATCH: 'bad',
  NEEDS_REVIEW: 'warn',
  MISSING: 'bad',
}

const ACTION_TONE: Record<string, string> = {
  AUTO_CLEAR: 'ok',
  FLAG_DISCREPANCY: 'bad',
  HUMAN_REVIEW: 'warn',
  ACKNOWLEDGE: 'accent',
  NO_ACTION: 'neutral',
  IGNORE: 'neutral',
}

const SOURCE_LABEL: Record<string, string> = {
  deterministic: 'parsed',
  llm: 'model',
  cloud: 'cloud model',
  vlm: 'image model',
  missing: 'missing',
}

export function Badge({ tone, children, title }: {
  tone: string
  children: React.ReactNode
  title?: string
}) {
  return <span className={`badge ${tone}`} title={title}>{children}</span>
}

export const CategoryBadge = ({ value }: { value: string }) => (
  <Badge tone={CATEGORY_TONE[value] ?? 'neutral'}>{value.replace(/_/g, ' ')}</Badge>
)

export const StatusBadge = ({ value }: { value: string | null }) =>
  value ? <Badge tone={STATUS_TONE[value] ?? 'neutral'}>{value.replace(/_/g, ' ')}</Badge>
        : <span className="faint small">—</span>

export const ActionBadge = ({ value }: { value: string }) => (
  <Badge tone={ACTION_TONE[value] ?? 'neutral'}>{value.replace(/_/g, ' ')}</Badge>
)

export const SourceBadge = ({ value }: { value: string }) => (
  <Badge
    tone={value === 'deterministic' ? 'ok' : value === 'missing' ? 'bad' : 'info'}
    title={
      value === 'deterministic'
        ? 'Found by label parsing. No model involved, so this value is reproducible.'
        : value === 'missing'
        ? 'This field was missing or not found in the document.'
        : 'Extracted by a vision or language model.'
    }
  >
    {SOURCE_LABEL[value] ?? value}
  </Badge>
)

/** Shows the current direct-model path without claiming cloud routing is active. */
export function RouterBadge({ escalated, confidence }: {
  escalated: boolean | number
  confidence?: number
}) {
  const up = Boolean(escalated)
  const pct = confidence === undefined ? null : `${Math.round(confidence * 100)}%`
  return (
    <Badge
      tone={up ? 'info' : 'neutral'}
      title={
        up
          ? 'This classification was escalated by the backend.'
          : `Processed by the configured backend${pct ? `; recorded confidence ${pct}` : ''}. Automatic escalation is not active.`
      }
    >
      <span className="dot" />
      {up ? 'escalated' : 'direct'}{pct ? ` · ${pct}` : ''}
    </Badge>
  )
}

export function ConfidenceBar({ value }: { value: number }) {
  const tone = value >= 0.8 ? 'var(--ok)' : value >= 0.6 ? 'var(--warn)' : 'var(--bad)'
  return (
    <div className="row" style={{ gap: 7 }}>
      <div className="bar-track" style={{ width: 44 }}>
        <div className="bar" style={{ width: `${Math.max(2, value * 100)}%`, background: tone }} />
      </div>
      <span className="mono faint">{(value * 100).toFixed(0)}%</span>
    </div>
  )
}
