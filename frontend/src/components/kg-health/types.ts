/**
 * Types partages entre le backend KG Health API et le frontend.
 * Miroir strict des schemas Pydantic `knowbase.api.schemas.kg_health`.
 */

export type Zone = 'green' | 'yellow' | 'red'

export interface MetricStatus {
  zone: Zone
  label: string
}

export interface Metric {
  key: string
  label: string
  description: string
  value: number
  display_value: string
  raw: number | null
  weight: number
  status: MetricStatus
  drilldown_available: boolean
  drilldown_key: string | null
}

export interface FamilyScore {
  name: 'provenance' | 'structure' | 'distribution' | 'coherence'
  label: string
  score: number
  status: MetricStatus
  weight: number
  metrics: Metric[]
}

export interface DocLinkageRow {
  doc_id: string
  claims_total: number
  linkage_rate: number
  subject_status: string
}

export interface HubRow {
  entity: string
  claims: number
  share_pct: number
}

export interface SingletonStats {
  total_components: number
  singletons: number
  singleton_rate: number
  giant_component_size: number
  giant_component_pct: number
}

export interface ActionablesPanel {
  worst_docs: DocLinkageRow[]
  top_hubs: HubRow[]
  singleton_stats: SingletonStats | null
  perspective_status: string | null
  perspective_new_claims: number
}

export interface KGHealthCorpusSummary {
  total_claims: number
  total_entities: number
  total_facets: number
  total_documents: number
  total_contradictions: number
}

export interface KGHealthScoreResponse {
  global_score: number
  global_status: MetricStatus
  families: FamilyScore[]
  summary: KGHealthCorpusSummary
  actionables: ActionablesPanel
  computed_at: string
  compute_duration_ms: number
}

export interface KGHealthDrilldownResponse {
  key: string
  title: string
  columns: string[]
  rows: Record<string, any>[]
  total_available: number
}

// ── Helpers couleur ────────────────────────────────────────────────────

export const zoneColor = (zone: Zone): string => {
  if (zone === 'green') return '#22c55e'
  if (zone === 'yellow') return '#f59e0b'
  return '#ef4444'
}

export const zoneScheme = (zone: Zone): string => {
  if (zone === 'green') return 'green'
  if (zone === 'yellow') return 'orange'
  return 'red'
}

export const zoneGradient = (zone: Zone): string => {
  if (zone === 'green') return 'linear-gradient(90deg, #22c55e, #16a34a)'
  if (zone === 'yellow') return 'linear-gradient(90deg, #f59e0b, #d97706)'
  return 'linear-gradient(90deg, #ef4444, #dc2626)'
}
