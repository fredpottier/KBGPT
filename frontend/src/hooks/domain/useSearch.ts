/**
 * useSearch - Hook de logique métier pour la recherche
 *
 * Ce hook encapsule toute la logique de recherche :
 * - Appels API
 * - Gestion des états (loading, error, data)
 * - Gestion des sessions
 * - Cache et optimisations
 *
 * Le composant de présentation (View) ne fait que recevoir les données
 * et appeler les actions, sans connaître les détails d'implémentation.
 */

import { useState, useCallback, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'

// Types
export interface SearchResult {
  id: string
  content: string
  score: number
  source: {
    filename: string
    page?: number
    chunk_index?: number
  }
  metadata?: Record<string, unknown>
}

export interface SearchSynthesis {
  answer: string
  confidence: number
  sources_used: string[]
}

export interface SearchResponse {
  query: string
  results: SearchResult[]
  synthesis?: SearchSynthesis
  graph_context?: unknown
  session_id?: string
}

export interface SearchParams {
  query: string
  use_graph_context?: boolean
  enrichment_level?: 'light' | 'standard' | 'deep'
  session_id?: string
  tenant_id?: string
}

export interface UseSearchOptions {
  sessionId?: string
  onSuccess?: (data: SearchResponse) => void
  onError?: (error: Error) => void
}

export interface UseSearchReturn {
  // État
  isLoading: boolean
  isSearching: boolean
  error: Error | null
  results: SearchResult[]
  synthesis: SearchSynthesis | null
  sessionId: string | null

  // Actions
  search: (params: SearchParams) => Promise<SearchResponse>
  clearResults: () => void
  setSessionId: (id: string | null) => void

  // Métadonnées
  lastQuery: string | null
  searchCount: number
}

/**
 * Hook principal pour la recherche
 */
export function useSearch(options: UseSearchOptions = {}): UseSearchReturn {
  const queryClient = useQueryClient()
  const [sessionId, setSessionId] = useState<string | null>(options.sessionId || null)
  const [results, setResults] = useState<SearchResult[]>([])
  const [synthesis, setSynthesis] = useState<SearchSynthesis | null>(null)
  const [lastQuery, setLastQuery] = useState<string | null>(null)
  const searchCountRef = useRef(0)

  // Mutation pour la recherche
  const searchMutation = useMutation({
    mutationFn: async (params: SearchParams): Promise<SearchResponse> => {
      const token = localStorage.getItem('access_token')

      const response = await axios.post<SearchResponse>(
        '/api/dispatch',
        {
          endpoint: '/api/search',
          method: 'POST',
          body: {
            question: params.query,
            use_graph_context: params.use_graph_context ?? false,
            enrichment_level: params.enrichment_level ?? 'standard',
            session_id: params.session_id || sessionId,
            tenant_id: params.tenant_id ?? 'default',
          },
        },
        {
          headers: {
            'Content-Type': 'application/json',
            ...(token && { Authorization: `Bearer ${token}` }),
          },
        }
      )

      return response.data
    },
    onSuccess: (data) => {
      setResults(data.results || [])
      setSynthesis(data.synthesis || null)
      setLastQuery(data.query)
      searchCountRef.current += 1

      // Mise à jour de la session si retournée par l'API
      if (data.session_id) {
        setSessionId(data.session_id)
      }

      // Callback optionnel
      options.onSuccess?.(data)
    },
    onError: (error: Error) => {
      options.onError?.(error)
    },
  })

  // Action de recherche
  const search = useCallback(
    async (params: SearchParams): Promise<SearchResponse> => {
      return searchMutation.mutateAsync(params)
    },
    [searchMutation]
  )

  // Nettoyer les résultats
  const clearResults = useCallback(() => {
    setResults([])
    setSynthesis(null)
    setLastQuery(null)
  }, [])

  return {
    // État
    isLoading: searchMutation.isPending,
    isSearching: searchMutation.isPending,
    error: searchMutation.error,
    results,
    synthesis,
    sessionId,

    // Actions
    search,
    clearResults,
    setSessionId,

    // Métadonnées
    lastQuery,
    searchCount: searchCountRef.current,
  }
}

export default useSearch
