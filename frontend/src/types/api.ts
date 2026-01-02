export interface Document {
  id: string
  filename: string
  title?: string
  content?: string
  file_type: string
  file_size: number
  status: 'pending' | 'processing' | 'completed' | 'failed'
  created_at: string
  updated_at: string
  metadata?: {
    pages?: number
    word_count?: number
    language?: string
    [key: string]: any
  }
}

export interface ChatMessage {
  id: string
  message: string
  response: string
  timestamp: string
  context_documents?: string[]
}

export interface ChatConversation {
  id: string
  title?: string
  messages: ChatMessage[]
  created_at: string
  updated_at: string
}

export interface User {
  id: string
  email: string
  name: string
  role: 'admin' | 'user'
  created_at: string
  last_login?: string
  is_active: boolean
}

export interface AdminSettings {
  model_config: {
    temperature: number
    max_tokens: number
    model_name: string
  }
  upload_config: {
    max_file_size: number
    allowed_extensions: string[]
  }
  system_config: {
    debug_mode: boolean
    log_level: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR'
  }
}

export interface MonitoringStats {
  documents: {
    total: number
    processed: number
    pending: number
    failed: number
  }
  chats: {
    total_messages: number
    active_conversations: number
    average_response_time: number
  }
  system: {
    uptime: number
    memory_usage: number
    cpu_usage: number
    disk_usage: number
  }
}

export interface LogEntry {
  timestamp: string
  level: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR'
  message: string
  source: string
  details?: any
}

export interface ApiError {
  message: string
  code?: string
  details?: any
}

// New types for search with synthesis
export interface SearchChunk {
  text: string
  source_file: string
  slide_index?: string
  score: number
  slide_image_url?: string
  rerank_score?: number
}

export interface SynthesisResult {
  synthesized_answer: string
  sources_used: string[]
  confidence: number
}

// 🌊 Phase 3.5+: Exploration Intelligence Types
export interface ConceptExplanation {
  concept_id: string
  concept_name: string
  why_used: string
  role_in_answer: string
  source_documents: string[]
  confidence: number
}

export interface ExplorationSuggestion {
  suggestion_type: 'concept' | 'document' | 'question'
  title: string
  description: string
  action_label: string
  action_value: string
  relevance_score: number
}

export interface SuggestedQuestion {
  question: string
  context: string
  related_concepts: string[]
}

// 🌊 Phase 3.5+: Research Axes v2 (basés sur KG typed edges)
export interface ResearchAxis {
  axis_id: string
  role: 'actionnable' | 'risk' | 'structure'
  short_label: string
  full_question: string
  source_concept: string
  target_concept: string
  relation_type: string
  relevance_score: number
  confidence: number
  explainer_trace: string
  search_query: string
}

export interface ExplorationIntelligence {
  concept_explanations: Record<string, ConceptExplanation>
  exploration_suggestions: ExplorationSuggestion[]
  suggested_questions: SuggestedQuestion[]
  // 🌊 Phase 3.5: Axes de recherche structurés
  research_axes: ResearchAxis[]
  processing_time_ms: number
}

// 🌊 Answer+Proof: Confidence Engine Types
export type EpistemicState = 'established' | 'partial' | 'debate' | 'incomplete'
export type ContractState = 'covered' | 'out_of_scope'

export interface KGSignals {
  typed_edges_count: number
  avg_conf: number
  validated_ratio: number
  conflicts_count: number
  orphan_concepts_count: number
  independent_sources_count: number
  expected_edges_missing_count: number
}

export interface DomainSignals {
  in_scope_domains: string[]
  matched_domains: string[]
}

export interface ConfidenceResult {
  epistemic_state: EpistemicState
  contract_state: ContractState
  badge: string
  micro_text: string
  warnings: string[]
  blockers: string[]
  rules_fired: string[]
  cta?: {
    label: string
    action: string
  }
  kg_signals?: KGSignals
  domain_signals?: DomainSignals
}

// 🌊 Answer+Proof: Knowledge Proof Summary (Bloc B)
export interface KnowledgeProofSummary {
  concepts_count: number
  relations_count: number
  relation_types: string[]
  sources_count: number
  contradictions_count: number
  coherence_status: 'coherent' | 'debate' | 'incomplete'
  maturity_percent: number
  avg_confidence: number
  dominant_concept_types: string[]
  solidity: 'Fragile' | 'Partielle' | 'Etablie'
  epistemic_state: EpistemicState
  contract_state: ContractState
}

// 🌊 Answer+Proof: Reasoning Trace (Bloc C)
export interface ReasoningSupport {
  relation_type: string
  source_concept_id: string
  source_concept_name: string
  target_concept_id: string
  target_concept_name: string
  edge_confidence: number
  canonical_relation_id?: string
  source_refs: string[]
}

export interface ReasoningStep {
  step: number
  statement: string
  has_kg_support: boolean
  is_conflict: boolean
  supports: ReasoningSupport[]
  source_refs: string[]
}

export interface ReasoningTrace {
  coherence_status: 'coherent' | 'partial_conflict' | 'conflict'
  coherence_message: string
  unsupported_steps_count: number
  steps: ReasoningStep[]
}

// 🌊 Answer+Proof: Coverage Map (Bloc D)
export interface DomainCoverage {
  domain_id: string
  domain: string
  status: 'covered' | 'partial' | 'debate' | 'not_covered'
  epistemic_state: EpistemicState
  relations_count: number
  concepts_found: string[]
  confidence: number
  note?: string
}

export interface CoverageMap {
  domains: DomainCoverage[]
  coverage_percent: number | null
  covered_count: number
  total_relevant: number
  recommendations: string[]
  message?: string
}

export interface SearchResponse {
  status: 'success' | 'no_results'
  results: SearchChunk[]
  synthesis?: SynthesisResult
  message?: string
  // 🌊 Phase 3.5: Knowledge Graph
  graph_context?: any
  graph_data?: import('./graph').GraphData
  // 🌊 Phase 3.5+: Proof Graph (budgeté et hiérarchisé)
  proof_graph?: import('./graph').ProofGraph
  // 🌊 Phase 3.5+: Exploration Intelligence
  exploration_intelligence?: ExplorationIntelligence
  // 🌊 Answer+Proof: New fields
  confidence?: ConfidenceResult
  knowledge_proof?: KnowledgeProofSummary
  reasoning_trace?: ReasoningTrace
  coverage_map?: CoverageMap
}