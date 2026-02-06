/**
 * OSMOSE Verification Types
 *
 * TypeScript types for text verification against Knowledge Graph.
 */

export type VerificationStatus =
  | 'confirmed'      // Claim confirms the assertion
  | 'contradicted'   // Claim contradicts the assertion
  | 'incomplete'     // Partial information found
  | 'fallback'       // Found in Qdrant only (no claim)
  | 'unknown'        // Nothing found

export interface Evidence {
  type: 'claim' | 'chunk'
  text: string
  sourceDoc: string
  sourcePage?: number
  sourceSection?: string
  confidence: number
  relationship: 'supports' | 'contradicts' | 'partial'
}

export interface Assertion {
  id: string
  text: string
  startIndex: number
  endIndex: number
  status: VerificationStatus
  confidence: number
  evidence: Evidence[]
}

export interface VerificationSummary {
  total: number
  confirmed: number
  contradicted: number
  incomplete: number
  fallback: number
  unknown: number
}

export interface VerificationResult {
  originalText: string
  assertions: Assertion[]
  summary: VerificationSummary
}

export interface CorrectionChange {
  original: string
  corrected: string
  reason: string
}

export interface CorrectionResult {
  correctedText: string
  changes: CorrectionChange[]
}

// API Request/Response types (camelCase for frontend, snake_case for API)
export interface VerifyRequest {
  text: string
  tenant_id?: string
}

export interface VerifyResponse {
  original_text: string
  assertions: Array<{
    id: string
    text: string
    start_index: number
    end_index: number
    status: VerificationStatus
    confidence: number
    evidence: Array<{
      type: 'claim' | 'chunk'
      text: string
      source_doc: string
      source_page?: number
      source_section?: string
      confidence: number
      relationship: 'supports' | 'contradicts' | 'partial'
    }>
  }>
  summary: VerificationSummary
}

export interface CorrectRequest {
  text: string
  assertions: Assertion[]
  tenant_id?: string
}

export interface CorrectResponse {
  corrected_text: string
  changes: Array<{
    original: string
    corrected: string
    reason: string
  }>
}

// Helper to convert API response to frontend types
export function convertVerifyResponse(response: VerifyResponse): VerificationResult {
  return {
    originalText: response.original_text,
    assertions: response.assertions.map(a => ({
      id: a.id,
      text: a.text,
      startIndex: a.start_index,
      endIndex: a.end_index,
      status: a.status,
      confidence: a.confidence,
      evidence: a.evidence.map(e => ({
        type: e.type,
        text: e.text,
        sourceDoc: e.source_doc,
        sourcePage: e.source_page,
        sourceSection: e.source_section,
        confidence: e.confidence,
        relationship: e.relationship
      }))
    })),
    summary: response.summary
  }
}

export function convertCorrectResponse(response: CorrectResponse): CorrectionResult {
  return {
    correctedText: response.corrected_text,
    changes: response.changes.map(c => ({
      original: c.original,
      corrected: c.corrected,
      reason: c.reason
    }))
  }
}
