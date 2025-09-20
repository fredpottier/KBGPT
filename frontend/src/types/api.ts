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

export interface SearchResponse {
  status: 'success' | 'no_results'
  results: SearchChunk[]
  synthesis?: SynthesisResult
  message?: string
}