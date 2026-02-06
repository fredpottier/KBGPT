import axios, { AxiosInstance, AxiosRequestConfig, AxiosResponse } from 'axios'

// Determine if we're running on server or client
const isServer = typeof window === 'undefined'

// Detect if we're behind NGINX reverse proxy (EC2 deployment)
// NGINX routes /api/* to backend, so we can use relative URL
const isBehindProxy = !isServer && typeof window !== 'undefined' &&
  (window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1')

// Use internal Docker URL for server-side calls
// For client-side: use relative URL if behind proxy, otherwise external URL
const API_BASE_URL = isServer
  ? (process.env.NEXT_PUBLIC_API_INTERNAL_URL || 'http://app:8000')
  : isBehindProxy
    ? ''  // Relative URL - NGINX will route /api/* to backend
    : (process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000')

export interface ApiResponse<T = any> {
  success: boolean
  data?: T
  message?: string
  error?: string
}

class ApiClient {
  private client: AxiosInstance

  constructor() {
    this.client = axios.create({
      baseURL: `${API_BASE_URL}/api`,
      timeout: 120000, // 2 minutes pour les requêtes de recherche complexes
      headers: {
        'Content-Type': 'application/json',
      },
    })

    this.client.interceptors.request.use(
      (config) => {
        // Add auth token if available
        const token = typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null
        if (token) {
          config.headers.Authorization = `Bearer ${token}`
        }
        return config
      },
      (error) => {
        return Promise.reject(error)
      }
    )

    this.client.interceptors.response.use(
      (response: AxiosResponse) => response,
      (error) => {
        if (error.response?.status === 401) {
          // Handle unauthorized
          if (typeof window !== 'undefined') {
            localStorage.removeItem('auth_token')
            window.location.href = '/login'
          }
        }
        return Promise.reject(error)
      }
    )
  }

  async get<T>(url: string, config?: AxiosRequestConfig): Promise<ApiResponse<T>> {
    try {
      const response = await this.client.get(url, config)
      return {
        success: true,
        data: response.data,
      }
    } catch (error: any) {
      return {
        success: false,
        error: error.response?.data?.message || error.message || 'An error occurred',
      }
    }
  }

  async post<T>(url: string, data?: any, config?: AxiosRequestConfig): Promise<ApiResponse<T>> {
    try {
      const response = await this.client.post(url, data, config)
      return {
        success: true,
        data: response.data,
      }
    } catch (error: any) {
      return {
        success: false,
        error: error.response?.data?.message || error.message || 'An error occurred',
      }
    }
  }

  async put<T>(url: string, data?: any, config?: AxiosRequestConfig): Promise<ApiResponse<T>> {
    try {
      const response = await this.client.put(url, data, config)
      return {
        success: true,
        data: response.data,
      }
    } catch (error: any) {
      return {
        success: false,
        error: error.response?.data?.message || error.message || 'An error occurred',
      }
    }
  }

  async delete<T>(url: string, config?: AxiosRequestConfig): Promise<ApiResponse<T>> {
    try {
      const response = await this.client.delete(url, config)
      return {
        success: true,
        data: response.data,
      }
    } catch (error: any) {
      return {
        success: false,
        error: error.response?.data?.message || error.message || 'An error occurred',
      }
    }
  }
}

export const apiClient = new ApiClient()

// Helper functions for common API operations
export const api = {
  // Documents - Document Backbone API (Phase 1)
  documents: {
    // List documents with filters (pagination, type, status)
    list: (params?: {
      document_type?: string
      status?: string
      limit?: number
      offset?: number
    }) => {
      const queryParams = new URLSearchParams()
      if (params?.document_type) queryParams.append('document_type', params.document_type)
      if (params?.status) queryParams.append('status', params.status)
      if (params?.limit) queryParams.append('limit', params.limit.toString())
      if (params?.offset) queryParams.append('offset', params.offset.toString())
      const query = queryParams.toString()
      return apiClient.get(`/documents${query ? `?${query}` : ''}`)
    },

    // Get document by ID with versions
    getById: (id: string) => apiClient.get(`/documents/${id}`),

    // Get all versions of a document
    getVersions: (documentId: string) => apiClient.get(`/documents/${documentId}/versions`),

    // Get version lineage graph (for D3.js visualization)
    getLineage: (documentId: string) => apiClient.get(`/documents/${documentId}/lineage`),

    // Create new version of document
    createVersion: (documentId: string, file: File, versionLabel: string, effectiveDate?: string, authorName?: string) => {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('version_label', versionLabel)
      if (effectiveDate) formData.append('effective_date', effectiveDate)
      if (authorName) formData.append('author_name', authorName)
      return apiClient.post(`/documents/${documentId}/versions`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
    },

    // Resolve Episode to Document (provenance traceability)
    getByEpisode: (episodeUuid: string) => apiClient.get(`/documents/by-episode/${episodeUuid}`),

    // Legacy upload via dispatch
    upload: (file: File, documentType?: string) => {
      const formData = new FormData()
      formData.append('action_type', 'ingest')
      formData.append('file', file)
      if (documentType) {
        formData.append('document_type', documentType)
      }
      return api.dispatch.action(formData)
    },
  },

  // Chat - Using the direct /search endpoint (more logical)
  chat: {
    send: (
      message: string,
      language?: string,
      mime?: string,
      solution?: string,
      useGraphContext?: boolean,
      graphEnrichmentLevel?: 'none' | 'light' | 'standard' | 'deep',
      sessionId?: string,
      useInstrumented?: boolean
    ) =>
      apiClient.post('/search', {
        question: message,
        language,
        mime,
        solution,
        use_graph_context: useGraphContext,
        graph_enrichment_level: graphEnrichmentLevel,
        session_id: sessionId,
        use_instrumented: useInstrumented ?? true,  // 🎯 OSMOSE: Activer le rendu instrumenté par défaut
      }),
    history: () => apiClient.get('/chat/history'), // Not implemented in backend yet
    conversation: (id: string) => apiClient.get(`/chat/${id}`), // Not implemented in backend yet
  },

  // Search endpoint (same as chat.send but more explicit)
  search: {
    query: (
      question: string,
      language?: string,
      mime?: string,
      solution?: string,
      useGraphContext?: boolean,
      graphEnrichmentLevel?: 'none' | 'light' | 'standard' | 'deep'
    ) =>
      apiClient.post('/search', {
        question,
        language,
        mime,
        solution,
        use_graph_context: useGraphContext,
        graph_enrichment_level: graphEnrichmentLevel,
      }),
    solutions: () => apiClient.get('/solutions'),
  },

  // Living Ontology - OSMOS Phase 2.3
  livingOntology: {
    stats: () => apiClient.get('/living-ontology/stats'),
    types: () => apiClient.get('/living-ontology/types'),
    patterns: () => apiClient.get('/living-ontology/patterns'),
    discover: (autoPromote?: boolean) =>
      apiClient.post('/living-ontology/discover', { auto_promote: autoPromote }),
    proposals: () => apiClient.get('/living-ontology/proposals'),
    approveProposal: (id: string) => apiClient.post(`/living-ontology/proposals/${id}/approve`),
    rejectProposal: (id: string, reason?: string) =>
      apiClient.post(`/living-ontology/proposals/${id}/reject`, { reason }),
    history: () => apiClient.get('/living-ontology/history'),
  },

  // Dispatch endpoint for file operations
  dispatch: {
    action: (formData: FormData) =>
      apiClient.post('/dispatch', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      }),
  },

  // Status endpoint
  status: {
    get: (uid: string) => apiClient.get(`/status/${uid}`),
  },

  // Imports - Import tracking and history
  imports: {
    history: () => apiClient.get('/imports/history'),
    active: () => apiClient.get('/imports/active'),
    sync: () => apiClient.post('/imports/sync'),
    delete: (uid: string) => apiClient.delete(`/imports/${uid}`),
  },

  // Entity Types - Dynamic entity types management
  entityTypes: {
    list: (status?: string) => apiClient.get(`/entity-types${status ? `?status=${status}` : ''}`),
    get: (typeName: string) => apiClient.get(`/entity-types/${typeName}`),
    approve: (typeName: string) => apiClient.post(`/entity-types/${typeName}/approve`),
    reject: (typeName: string, reason?: string) => apiClient.post(`/entity-types/${typeName}/reject`, { reason }),
    delete: (typeName: string) => apiClient.delete(`/entity-types/${typeName}`),
    importYaml: (file: File) => {
      const formData = new FormData()
      formData.append('file', file)
      return apiClient.post('/entity-types/import-yaml', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
    },
    exportYaml: () => apiClient.get('/entity-types/export-yaml'),
  },

  // Document Types - DEPRECATED
  // Ce système est remplacé par le Domain Context global.
  // Ces endpoints seront supprimés dans une future version.
  documentTypes: {
    list: () => apiClient.get('/document-types'),
    get: (id: string) => apiClient.get(`/document-types/${id}`),
    create: (data: any) => apiClient.post('/document-types', data),
    update: (id: string, data: any) => apiClient.put(`/document-types/${id}`, data),
    delete: (id: string) => apiClient.delete(`/document-types/${id}`),
  },

  // Admin
  admin: {
    users: {
      list: () => apiClient.get('/admin/users'),
      create: (user: any) => apiClient.post('/admin/users', user),
      update: (id: string, user: any) => apiClient.put(`/admin/users/${id}`, user),
      delete: (id: string) => apiClient.delete(`/admin/users/${id}`),
    },
    settings: {
      get: () => apiClient.get('/admin/settings'),
      update: (settings: any) => apiClient.put('/admin/settings', settings),
    },
    monitoring: {
      stats: () => apiClient.get('/admin/monitoring/stats'),
      logs: () => apiClient.get('/admin/monitoring/logs'),
    },
  },

  // Concepts - Phase 3.5 Explainable Graph-RAG
  concepts: {
    explain: (conceptId: string) => apiClient.get(`/concepts/${conceptId}/explain`),
    search: (query: string, limit: number = 10) =>
      apiClient.get(`/concepts/search?q=${encodeURIComponent(query)}&limit=${limit}`),
    related: (conceptId: string, maxDepth: number = 2) =>
      apiClient.get(`/concepts/${conceptId}/related?max_depth=${maxDepth}`),
  },

  // Claims - Phase 2.11 OSMOSE KG/RAG Contract
  claims: {
    // Search claims with filters
    search: (params?: {
      query?: string
      subject_concept_id?: string
      claim_type?: string
      maturity?: 'CANDIDATE' | 'VALIDATED' | 'CONFLICTING' | 'CONTEXT_DEPENDENT' | 'SUPERSEDED'
      min_confidence?: number
      limit?: number
      offset?: number
    }) => apiClient.post('/claims/search', params || {}),

    // Get claims for a concept
    forConcept: (conceptId: string, claimTypes?: string, includeConflicting: boolean = true) => {
      const params = new URLSearchParams()
      if (claimTypes) params.append('claim_types', claimTypes)
      params.append('include_conflicting', includeConflicting.toString())
      return apiClient.get(`/claims/concept/${conceptId}?${params.toString()}`)
    },

    // Get KG/RAG Contract for a concept
    kgRagContract: (conceptId: string) => apiClient.get(`/claims/concept/${conceptId}/kg-rag`),

    // Get all conflicts
    conflicts: () => apiClient.get('/claims/conflicts'),

    // Get claim types
    types: () => apiClient.get('/claims/claim-types'),

    // Trigger consolidation
    consolidate: (params?: {
      subject_concept_id?: string
      claim_type?: string
      doc_id?: string
      force?: boolean
    }) => apiClient.post('/claims/consolidate', params || {}),
  },

  // Sessions - Memory Layer (Phase 2.5)
  sessions: {
    // Session CRUD
    list: (activeOnly: boolean = true, limit: number = 20) =>
      apiClient.get(`/sessions?active_only=${activeOnly}&limit=${limit}`),
    get: (sessionId: string) => apiClient.get(`/sessions/${sessionId}`),
    create: (title?: string) => apiClient.post('/sessions', { title }),
    update: (sessionId: string, data: { title?: string; is_active?: boolean }) =>
      apiClient.put(`/sessions/${sessionId}`, data),
    delete: (sessionId: string) => apiClient.delete(`/sessions/${sessionId}`),

    // Messages
    getMessages: (sessionId: string, limit?: number, offset?: number) => {
      const params = new URLSearchParams()
      if (limit) params.append('limit', limit.toString())
      if (offset) params.append('offset', offset.toString())
      const query = params.toString()
      return apiClient.get(`/sessions/${sessionId}/messages${query ? `?${query}` : ''}`)
    },
    addMessage: (sessionId: string, message: {
      role: 'user' | 'assistant' | 'system',
      content: string,
      entities_mentioned?: string[],
      documents_referenced?: string[],
      model_used?: string,
      tokens_input?: number,
      tokens_output?: number,
      latency_ms?: number
    }) => apiClient.post(`/sessions/${sessionId}/messages`, message),

    // Context
    getContext: (sessionId: string, includeSummary: boolean = true, recentCount: number = 10) =>
      apiClient.get(`/sessions/${sessionId}/context?include_summary=${includeSummary}&recent_count=${recentCount}`),
    updateContext: (sessionId: string, context: {
      entities?: any[],
      documents?: any[],
      search_results?: any[],
      topics?: string[]
    }) => apiClient.put(`/sessions/${sessionId}/context`, context),

    // Feedback
    addFeedback: (sessionId: string, messageId: string, rating: 1 | 2, comment?: string) =>
      apiClient.post(`/sessions/${sessionId}/messages/${messageId}/feedback`, { rating, comment }),

    // Title generation
    generateTitle: (sessionId: string, force: boolean = false) =>
      apiClient.post(`/sessions/${sessionId}/generate-title?force=${force}`),

    // Reference resolution
    resolve: (query: string, sessionId: string) =>
      apiClient.post('/sessions/resolve', { query, session_id: sessionId }),

    // Summary generation
    getSummary: (sessionId: string, format: 'business' | 'technical' | 'executive' = 'business') =>
      apiClient.get(`/sessions/${sessionId}/summary?format=${format}`),
    generateSummary: (sessionId: string, format: 'business' | 'technical' | 'executive' = 'business') =>
      apiClient.post(`/sessions/${sessionId}/summary`, { format }),
  },

  // Verification - Text verification against Knowledge Graph
  verify: {
    // Analyze text and verify assertions
    analyze: (text: string, tenantId: string = 'default') =>
      apiClient.post('/verify/analyze', { text, tenant_id: tenantId }),

    // Generate corrected text based on verified assertions
    correct: (text: string, assertions: any[], tenantId: string = 'default') =>
      apiClient.post('/verify/correct', { text, assertions, tenant_id: tenantId }),
  },
}