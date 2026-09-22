import type { Trace } from './types'

/**
 * Human-friendly formatters for system decisions, blockers, and rules.
 * Eliminates raw programmer slugs, lowercase sentences, and technical jargon.
 */

export function formatFriendlyBlocker(text: string): string {
  if (!text) return ''

  // 1. Wrong document type
  if (text.includes('wrong_doc_type') || text.toLowerCase().includes('wrong document type')) {
    return 'An incorrect document type was attached (e.g. invoice or packing list instead of a bill of lading). Please review the files manually.'
  }

  // 2. Missing attachment: only 1 attachment
  const matchOnly1 = text.match(/only 1 attachment provided \((?:attachments\/)?([^)]+)\)/i)
  if (matchOnly1) {
    const filename = matchOnly1[1].replace(/^attachments\//, '')
    return `Only 1 document was provided (${filename}). Both a Shipping Instruction and draft Bill of Lading are required.`
  }

  // 3. Missing attachment: only X attached
  const matchOnlyAttached = text.match(/only ([^)]+) attached/i)
  if (matchOnlyAttached) {
    const filename = matchOnlyAttached[1].replace(/attachments\//g, '')
    return `Only ${filename} was provided. Both a Shipping Instruction and draft Bill of Lading are required.`
  }

  // 4. Missing attachment: dropped or omitted
  if (
    text.includes('missing_attachment') ||
    text.toLowerCase().includes('dropped or omitted') ||
    text.toLowerCase().includes('neither was attached')
  ) {
    return 'Document attachments are missing or were omitted from the email. Both a Shipping Instruction and draft Bill of Lading are required.'
  }

  // 5. Blank fields / missing value
  if (
    text.includes('missing_value') ||
    text.toLowerCase().includes('left blank') ||
    text.toLowerCase().includes('blank fields')
  ) {
    return 'The sender noted in the email that required fields were left blank. Manual verification is needed to complete the missing information.'
  }

  // 6. Unreadable / scanned PDF
  if (text.includes('unreadable') || text.toLowerCase().includes('scanned pdf')) {
    return 'The attached document is a scanned image without a digital text layer. Visual verification by an operator is required.'
  }

  // Clean up any other text: remove trailing (code_slug) and capitalize
  let clean = text.replace(/\s*\([a-z0-9_-]+\)\s*$/i, '').trim()
  clean = clean.replace(/attachments\//g, '')
  if (clean.length > 0) {
    clean = clean.charAt(0).toUpperCase() + clean.slice(1)
    if (!clean.endsWith('.')) clean += '.'
  }
  return clean
}

export function formatFriendlyWhy(why: string, blockers?: string[], defectFields?: string[]): string {
  if (!why) return ''

  // If there are blockers or why starts with "cannot proceed automatically:"
  if (why.toLowerCase().startsWith('cannot proceed automatically:') || (blockers && blockers.length > 0)) {
    if (blockers && blockers.length > 0) {
      const formattedBlockers = blockers.map(formatFriendlyBlocker).join(' ')
      if (defectFields && defectFields.length > 0) {
        const fieldsStr = defectFields
          .map((f) => f.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()))
          .join(', ')
        return `${formattedBlockers} In addition, discrepancies were detected in: ${fieldsStr}.`
      }
      return formattedBlockers
    }
    const inner = why.replace(/^cannot proceed automatically:\s*/i, '')
    return formatFriendlyBlocker(inner)
  }

  // SI and BL disagree on ...
  const mismatchMatch = why.match(/SI and BL disagree on (.+)/i)
  if (mismatchMatch) {
    const fields = mismatchMatch[1]
      .split(',')
      .map((f) => f.trim().replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()))
      .join(', ')
    return `Discrepancies found between Shipping Instruction and Bill of Lading: ${fields}.`
  }

  // incomplete documents -- ... not found
  const missingMatch = why.match(/incomplete documents -- (.+) not found/i)
  if (missingMatch) {
    const fields = missingMatch[1]
      .split(',')
      .map((f) => f.trim().replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()))
      .join(', ')
    return `Incomplete document data: ${fields} could not be found in one of the documents.`
  }

  // all checked fields agree -- safe to confirm the draft BL
  if (why.toLowerCase().includes('all checked fields agree')) {
    return 'All 7 verified fields match between Shipping Instruction and Bill of Lading. The draft is safe to confirm.'
  }

  // spam
  if (why.toLowerCase().includes('classified as spam')) {
    return 'Identified as promotional or unsolicited outreach. No operational action is required.'
  }

  // general / bulletin
  if (why.toLowerCase().includes('informational bulletin')) {
    return 'Informational carrier bulletin or shipping advisory. No action is required.'
  }

  // conversational request for draft BL
  if (why.toLowerCase().includes('conversational request')) {
    return 'Customer requested a draft Bill of Lading. Route to the desk operator to prepare the draft.'
  }

  // si_request or invoice_query
  if (why.toLowerCase().includes('si request') || why.toLowerCase().includes('si_request')) {
    return 'Customer Shipping Instruction request received. Acknowledge receipt and route to the desk operator.'
  }
  if (why.toLowerCase().includes('invoice query') || why.toLowerCase().includes('invoice_query')) {
    return 'Customer invoice or billing query received. Acknowledge receipt and route to the accounts desk.'
  }

  // Generic fallback: strip internal code tags, capitalize first letter, add period
  let clean = why.replace(/\s*\([a-z0-9_-]+\)\s*$/i, '').trim()
  if (clean.length > 0) {
    clean = clean.charAt(0).toUpperCase() + clean.slice(1)
    if (!clean.endsWith('.')) clean += '.'
  }
  return clean
}

export function formatFriendlyDecisionTitle(action: string, mismatchCount: number, hasBlockers: boolean): string {
  if (mismatchCount > 0 && hasBlockers) {
    return `${mismatchCount} Discrepanc${mismatchCount === 1 ? 'y' : 'ies'} & Blocker Detected`
  }
  if (mismatchCount > 0) {
    return `${mismatchCount} Discrepanc${mismatchCount === 1 ? 'y' : 'ies'} Detected`
  }
  if (hasBlockers) {
    return 'Verification Blocker Detected'
  }
  if (action === 'AUTO_CLEAR') {
    return 'Auto-Cleared: All Fields Match'
  }
  if (action === 'FLAG_DISCREPANCY') {
    return 'Discrepancy Flagged'
  }
  if (action === 'HUMAN_REVIEW') {
    return 'Human Review Required'
  }
  if (action === 'ACKNOWLEDGE') {
    return 'Acknowledge & Route'
  }
  if (action === 'NO_ACTION') {
    return 'No Action Required'
  }
  if (action === 'IGNORE') {
    return 'Unsolicited Email'
  }
  return action.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

/**
 * Why a document pane has nothing in it, in the extraction engine's own words.
 *
 * An empty pane with a "Digital Document" badge reads as a rendering bug, and a
 * reviewer cannot tell a corrupt attachment apart from a broken UI. The engine
 * already recorded the cause -- it was only ever shown on the Decision trace tab.
 *
 * Returns null when the document was read fine, or when the trace predates this
 * and has nothing to say.
 */
export function unreadableReason(traces: Trace[] | undefined, docName: string): string[] | null {
  const trace = (traces ?? []).find(
    (t) => t.engine === 'extract' && (t.inputs as { document?: string })?.document === docName,
  )
  // output is null only when extraction produced no fields at all.
  if (!trace || trace.output) return null
  const lines = trace.steps
    .map((s) => s.detail.split(docName).join('this file').replace(/ -- /g, ' — ').trim())
    .filter(Boolean)
    .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
  return lines.length ? lines : null
}

/**
 * Format raw evaluation rule slugs into polished, human-readable labels.
 * Transforms internal developer strings (e.g. 'locode_matched_but_city_differs')
 * into clear domain terminology ('UN/LOCODE matched, but city differs').
 */
export function formatFriendlyRule(rule: string | undefined | null): string {
  if (!rule) return 'Deterministic comparison'

  const KNOWN_RULES: Record<string, string> = {
    locode_matched_but_city_differs: 'UN/LOCODE matched, but city differs',
    exact_after_normalisation: 'Exact match after normalisation',
    exact_verbatim: 'Exact verbatim match',
    exact_after_cleaning: 'Exact match after cleanup',
    entity_token_overlap: 'Entity name token overlap (>60%)',
    city_name_match: 'City name matched',
    'city_name_match (one side used a LOCODE)': 'City name matched (one side used UN/LOCODE)',
    values_differ: 'Values disagree between documents',
    missing: 'Missing from one or both documents',
    missing_from_one_or_both_documents: 'Missing from one or both documents',
    numeric_equal: 'Numeric values equal',
    alias_match: 'Recognized alias / mapping',
    same_as_consignee_match: 'Same as consignee matches consignee party',
  }

  const trimmed = rule.trim()
  if (KNOWN_RULES[trimmed]) return KNOWN_RULES[trimmed]

  if (trimmed.startsWith('human_override')) {
    const detail = trimmed.replace(/^human_override:?\s*/i, '').trim()
    return detail ? `Reviewer override: ${detail}` : 'Human reviewer override'
  }

  if (trimmed.startsWith('approved_mapping')) {
    const detail = trimmed.replace(/^approved_mapping:?\s*/i, '').trim()
    return detail ? `Approved mapping: ${detail}` : 'Approved alias mapping'
  }

  if (trimmed.startsWith('container_size_mismatch')) {
    const detail = trimmed.replace(/^container_size_mismatch\s*/i, '').trim()
    return detail ? `Container size mismatch ${detail}` : 'Container size mismatch'
  }

  if (trimmed.startsWith('container_type_mismatch')) {
    const detail = trimmed.replace(/^container_type_mismatch\s*/i, '').trim()
    return detail ? `Container type mismatch ${detail}` : 'Container type mismatch'
  }

  // Handle generic rules: replace underscores, format LOCODE acronym, and capitalize words
  return trimmed
    .replace(/_/g, ' ')
    .replace(/\blocode\b/gi, 'UN/LOCODE')
    .replace(/\b([a-z])/g, (c) => c.toUpperCase())
}

/**
 * Formats any UTC or ISO timestamp into clean Malaysia time (MYT / Asia/Kuala_Lumpur, UTC+8).
 * Strips raw '+00:00', 'Z', and 'T' delimiters, presenting a clean 'YYYY-MM-DD HH:mm:ss'.
 */
export function formatMalaysiaTime(dateStr: string | undefined | null, includeSeconds = true): string {
  if (!dateStr) return '—'
  const trimmed = dateStr.trim()
  if (!trimmed) return '—'

  // If already a clean "YYYY-MM-DD HH:mm:ss", return as is
  if (/^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}(:\d{2})?$/.test(trimmed)) {
    return trimmed
  }

  try {
    let parseable = trimmed
    if (!parseable.includes('Z') && !/[+-]\d{2}:?\d{2}$/.test(parseable)) {
      parseable = parseable.replace(' ', 'T') + 'Z'
    }
    const d = new Date(parseable)
    if (isNaN(d.getTime())) {
      return trimmed.replace('T', ' ').replace(/\+00:?00$/, '').replace(/Z$/, '')
    }

    const formatted = new Intl.DateTimeFormat('en-CA', {
      timeZone: 'Asia/Kuala_Lumpur',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: includeSeconds ? '2-digit' : undefined,
      hour12: false,
    }).format(d).replace(/,\s*/, ' ')

    return formatted
  } catch {
    return trimmed.replace('T', ' ').replace(/\+00:?00$/, '').replace(/Z$/, '')
  }
}


