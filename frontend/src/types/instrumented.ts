/**
 * Types TypeScript pour Assertion-Centric UX (OSMOSE).
 *
 * Ce module definit les types pour le systeme de reponses instrumentees
 * qui remplace le score de confiance par un contrat de verite base sur des assertions.
 *
 * Chaque reponse est decomposee en assertions avec 4 statuts possibles:
 * - FACT: Explicitement present dans >= 1 source
 * - INFERRED: Deduit logiquement de FACTs
 * - FRAGILE: Faiblement soutenu (1 source, ancien, ambigu)
 * - CONFLICT: Sources incompatibles
 */

// --- Types Litteraux ---

export type AssertionStatus = 'FACT' | 'INFERRED' | 'FRAGILE' | 'CONFLICT'
export type AssertionScope = 'paragraph' | 'list_item'
export type Authority = 'official' | 'internal' | 'partner' | 'external'
export type Freshness = 'fresh' | 'mixed' | 'stale'

// --- Schemas de Support ---

export interface SourcesDateRange {
  from: string  // Annee de debut (YYYY)
  to: string    // Annee de fin (YYYY)
}

export interface AssertionSupport {
  supporting_sources_count: number
  weighted_support: number
  freshness: Freshness
  has_official: boolean
}

export interface AssertionMeta {
  support?: AssertionSupport
}

// --- Document et Localisation ---

export interface DocumentInfo {
  id: string
  title: string
  type: string  // PDF, PPTX, DOCX
  date?: string // YYYY-MM
  authority: Authority
  uri?: string
}

export interface SourceLocator {
  page_or_slide?: number
  bbox?: [number, number, number, number]  // [x1, y1, x2, y2] normalise 0-1
}

export interface SourceRef {
  id: string  // S1, S2, ...
  document: DocumentInfo
  locator?: SourceLocator
  excerpt: string
  thumbnail_url?: string
  evidence_url?: string
}

// --- Assertion ---

export interface Assertion {
  id: string  // A1, A2, ...
  text_md: string  // Markdown (gras, italique, liens autorisees)
  status: AssertionStatus
  scope: AssertionScope
  sources: string[]        // IDs sources supportant
  contradictions: string[] // IDs sources contradictoires (si CONFLICT)
  derived_from: string[]   // IDs assertions parentes (si INFERRED)
  inference_note?: string  // Explication (si INFERRED)
  meta?: AssertionMeta
}

// --- Proof Ticket ---

export interface ProofTicketCTA {
  label: string  // "Voir citation"
  type: 'source' | 'assertion' | 'external'
  id: string
}

export interface ProofTicket {
  ticket_id: string
  assertion_id: string
  title: string
  status: AssertionStatus
  summary: string
  primary_sources: string[]
  cta?: ProofTicketCTA
}

// --- Open Points ---

export interface OpenPoint {
  id: string  // OP1, OP2, ...
  description: string
  reason: string  // evidence_insufficient, conflict_unresolved, ...
  related_assertions: string[]
}

// --- Truth Contract ---

export interface TruthContract {
  facts_count: number
  inferred_count: number
  fragile_count: number
  conflict_count: number
  sources_count: number
  sources_date_range?: SourcesDateRange
}

// --- Instrumented Answer ---

export interface InstrumentedAnswer {
  answer_id: string
  generated_at: string  // ISO-8601
  truth_contract: TruthContract
  assertions: Assertion[]
  proof_tickets: ProofTicket[]
  sources: SourceRef[]
  open_points: OpenPoint[]
}

// --- Search Response Extension ---

export interface RetrievalStats {
  candidates_considered: number
  top_k_used: number
  kg_nodes_touched: number
  kg_edges_touched: number
}

export interface InstrumentedSearchResponse {
  request_id: string
  query: string
  instrumented_answer: InstrumentedAnswer
  retrieval?: RetrievalStats
}

// --- Candidats LLM (internes) ---

export interface AssertionCandidate {
  id: string
  text_md: string
  kind: 'FACT' | 'INFERRED'
  evidence_used: string[]
  derived_from: string[]
  notes?: string
}

export interface LLMAssertionResponse {
  assertions: AssertionCandidate[]
  open_points: string[]
}

// --- UI State pour Toggle Auditability ---

/**
 * Mode d'affichage de l'instrumentation.
 *
 * - 'simple': Texte sans mise en forme assertion (mode par defaut)
 * - 'instrumented': Revele couleurs, hover, proof tickets
 */
export type InstrumentationMode = 'simple' | 'instrumented'

export interface InstrumentationState {
  mode: InstrumentationMode
  /** Premiere visite de l'utilisateur (pour tooltip educatif) */
  isFirstVisit: boolean
  /** Animation en cours lors du switch */
  isTransitioning: boolean
}

/**
 * Configuration de rendu pour les assertions.
 * Utilisee par AssertionRenderer pour adapter l'affichage.
 */
export interface AssertionRenderConfig {
  /** Mode d'affichage actuel */
  mode: InstrumentationMode
  /** Afficher les indicateurs de statut (●, italique, souligne) */
  showStatusIndicators: boolean
  /** Activer le hover avec popover */
  enableHoverPopover: boolean
  /** Afficher les proof tickets */
  showProofTickets: boolean
  /** Afficher le truth contract complet */
  showFullTruthContract: boolean
}

/**
 * Genere la configuration de rendu selon le mode.
 */
export function getAssertionRenderConfig(mode: InstrumentationMode): AssertionRenderConfig {
  if (mode === 'instrumented') {
    return {
      mode,
      showStatusIndicators: true,
      enableHoverPopover: true,
      showProofTickets: true,
      showFullTruthContract: true,
    }
  }
  // Mode simple
  return {
    mode,
    showStatusIndicators: false,
    enableHoverPopover: false,
    showProofTickets: false,
    showFullTruthContract: false,
  }
}

// --- Constantes visuelles ---

/**
 * Couleurs et styles par statut d'assertion.
 */
export const ASSERTION_STYLES: Record<AssertionStatus, {
  color: string
  bgColor: string
  borderColor: string
  indicator: string
  label: string
}> = {
  FACT: {
    color: '#059669',      // emerald-600
    bgColor: '#d1fae5',    // emerald-100
    borderColor: '#10b981', // emerald-500
    indicator: '●',
    label: 'Fait source',
  },
  INFERRED: {
    color: '#3b82f6',      // blue-500
    bgColor: '#dbeafe',    // blue-100
    borderColor: '#60a5fa', // blue-400
    indicator: '◐',
    label: 'Inference',
  },
  FRAGILE: {
    color: '#f59e0b',      // amber-500
    bgColor: '#fef3c7',    // amber-100
    borderColor: '#fbbf24', // amber-400
    indicator: '◌',
    label: 'Fragile',
  },
  CONFLICT: {
    color: '#ef4444',      // red-500
    bgColor: '#fee2e2',    // red-100
    borderColor: '#f87171', // red-400
    indicator: '⚡',
    label: 'Conflit',
  },
}

/**
 * Couleurs pour les badges d'autorite des sources.
 */
export const AUTHORITY_COLORS: Record<Authority, string> = {
  official: '#059669',  // emerald-600
  internal: '#3b82f6',  // blue-500
  partner: '#8b5cf6',   // violet-500
  external: '#6b7280',  // gray-500
}

// --- Helpers ---

/**
 * Compte les assertions par statut.
 */
export function countAssertionsByStatus(assertions: Assertion[]): TruthContract {
  const counts = {
    facts_count: 0,
    inferred_count: 0,
    fragile_count: 0,
    conflict_count: 0,
    sources_count: 0,
    sources_date_range: undefined as SourcesDateRange | undefined,
  }

  const sourceIds = new Set<string>()

  for (const assertion of assertions) {
    switch (assertion.status) {
      case 'FACT':
        counts.facts_count++
        break
      case 'INFERRED':
        counts.inferred_count++
        break
      case 'FRAGILE':
        counts.fragile_count++
        break
      case 'CONFLICT':
        counts.conflict_count++
        break
    }
    assertion.sources.forEach(s => sourceIds.add(s))
  }

  counts.sources_count = sourceIds.size
  return counts
}

/**
 * Genere le texte du truth contract pour affichage simplifie.
 */
export function formatTruthContractSimple(contract: TruthContract): string {
  return `${contract.sources_count} source${contract.sources_count > 1 ? 's' : ''} utilisee${contract.sources_count > 1 ? 's' : ''}`
}

/**
 * Genere le texte complet du truth contract.
 */
export function formatTruthContractFull(contract: TruthContract): string {
  const parts: string[] = []

  if (contract.facts_count > 0) {
    parts.push(`${contract.facts_count} fait${contract.facts_count > 1 ? 's' : ''} source${contract.facts_count > 1 ? 's' : ''}`)
  }
  if (contract.inferred_count > 0) {
    parts.push(`${contract.inferred_count} inference${contract.inferred_count > 1 ? 's' : ''}`)
  }
  if (contract.fragile_count > 0) {
    parts.push(`${contract.fragile_count} fragile${contract.fragile_count > 1 ? 's' : ''}`)
  }
  if (contract.conflict_count > 0) {
    parts.push(`${contract.conflict_count} conflit${contract.conflict_count > 1 ? 's' : ''}`)
  }

  let result = parts.join(' · ')

  if (contract.sources_date_range) {
    result += ` · Sources ${contract.sources_date_range.from}–${contract.sources_date_range.to}`
  }

  return result
}
