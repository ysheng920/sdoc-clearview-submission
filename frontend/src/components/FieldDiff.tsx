import type { Comparison } from '../types'
import { StatusBadge } from './Badges'
import { formatFriendlyRule } from '../formatters'

/**
 * The SI/BL comparison, field by field. Each row names the rule that produced
 * the verdict, because "these differ" is not actionable but "these differ and
 * here is the rule that decided so" can be argued with.
 */
export function FieldDiff({ comparison }: { comparison: Comparison }) {
  return (
    <div className="card">
      <h3>Field comparison · {comparison.status.replace(/_/g, ' ')}</h3>

      <div className="diff-row head">
        <span>Field</span>
        <span>Shipping Instruction</span>
        <span>Draft Bill of Lading</span>
        <span>Verdict</span>
      </div>

      {Object.entries(comparison.detail).map(([name, d]) => (
        <div key={name} className={`diff-row${d.status === 'MISMATCH' ? ' is-mismatch' : ''}`}>
          <span className="muted">{name.replace(/_/g, ' ')}</span>
          <span className={`v${d.si.raw?.trim() ? '' : ' empty'}`}>{d.si.raw?.trim() ? d.si.raw : <span className="cell-missing-text">Missing</span>}</span>
          <span className={`v${d.bl.raw?.trim() ? '' : ' empty'}`}>{d.bl.raw?.trim() ? d.bl.raw : <span className="cell-missing-text">Missing</span>}</span>
          <span>
            <StatusBadge value={d.status} />
            <div className="rule">{formatFriendlyRule(d.rule)}</div>
          </span>
        </div>
      ))}

      <p className="small faint" style={{ marginTop: 12, marginBottom: 0 }}>
        Comparison uses deterministic rules only — no model is involved, so the same
        two documents always produce the same verdict.
      </p>
    </div>
  )
}
