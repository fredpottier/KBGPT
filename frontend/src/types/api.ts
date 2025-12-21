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

// 🌊 Phase 3.5: Research Axes (basés sur signaux KG réels)
export interface ResearchAxis {
  axis_id: string
  axis_type: 'bridge' | 'weak_signal' | 'cluster' | 'continuity' | 'unexplored' | 'transitive'
  title: string
  justification: string
  contextual_question: string
  concepts_involved: string[]
  relevance_score: number
  data_source: string
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

export interface SearchResponse {
  status: 'success' | 'no_results'
  results: SearchChunk[]
  synthesis?: SynthesisResult
  message?: string
  // 🌊 Phase 3.5: Knowledge Graph
  graph_context?: any
  graph_data?: import('./graph').GraphData
  // 🌊 Phase 3.5+: Exploration Intelligence
  exploration_intelligence?: ExplorationIntelligence
}