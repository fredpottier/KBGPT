/**
 * Wrapper autour de fetch() avec gestion automatique de l'authentification JWT.
 *
 * Fonctionnalités :
 * - Ajoute automatiquement le token JWT dans les headers
 * - Détecte les erreurs 401 (token expiré)
 * - Tente automatiquement un refresh token
 * - Redirige vers /login si le refresh échoue
 *
 * Utilisation :
 * ```typescript
 * const response = await fetchWithAuth('/api/entity-types')
 * const data = await response.json()
 * ```
 */

import { authService } from './auth'

/**
 * Wrapper fetch() avec authentification JWT automatique et gestion des 401.
 *
 * @param input - URL ou Request object
 * @param init - Options fetch (headers, method, body, etc.)
 * @returns Promise<Response>
 */
export async function fetchWithAuth(
  input: RequestInfo | URL,
  init?: RequestInit
): Promise<Response> {
  // Récupérer le token JWT
  const token = authService.getAccessToken()

  // Préparer les headers avec le token
  const headers = new Headers(init?.headers || {})
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  // Première tentative de requête
  let response = await fetch(input, {
    ...init,
    headers,
  })

  // Si erreur 401 (token expiré), tenter un refresh
  if (response.status === 401) {
    try {
      console.log('[fetchWithAuth] Token expired (401), attempting refresh...')

      // Tenter de rafraîchir le token
      const newToken = await authService.refreshAccessToken()

      console.log('[fetchWithAuth] Token refreshed successfully, retrying request')

      // Mettre à jour le header avec le nouveau token
      headers.set('Authorization', `Bearer ${newToken}`)

      // Rejouer la requête avec le nouveau token
      response = await fetch(input, {
        ...init,
        headers,
      })

      // Si toujours 401 après refresh, déconnecter
      if (response.status === 401) {
        console.error('[fetchWithAuth] Still 401 after refresh, logging out')
        authService.logout()

        if (typeof window !== 'undefined') {
          const redirectUrl = encodeURIComponent(window.location.pathname)
          window.location.href = `/login?redirect=${redirectUrl}`
        }
      }
    } catch (refreshError) {
      // Le refresh a échoué (refresh token expiré ou invalide)
      console.error('[fetchWithAuth] Refresh failed:', refreshError)
      authService.logout()

      // Rediriger vers la page de login
      if (typeof window !== 'undefined') {
        const redirectUrl = encodeURIComponent(window.location.pathname)
        window.location.href = `/login?redirect=${redirectUrl}`
      }

      // Propager l'erreur pour que le composant puisse la gérer
      throw new Error('Authentication expired. Please log in again.')
    }
  }

  return response
}

/**
 * Helper pour fetch JSON avec gestion automatique de l'authentification.
 *
 * @param input - URL ou Request object
 * @param init - Options fetch
 * @returns Promise<T> - Données JSON typées
 *
 * @example
 * ```typescript
 * const entityTypes = await fetchJsonWithAuth<EntityType[]>('/api/entity-types')
 * ```
 */
export async function fetchJsonWithAuth<T = any>(
  input: RequestInfo | URL,
  init?: RequestInit
): Promise<T> {
  const response = await fetchWithAuth(input, init)

  if (!response.ok) {
    // Tenter de parser l'erreur JSON
    const error = await response.json().catch(() => ({
      detail: `HTTP ${response.status}: ${response.statusText}`,
    }))

    throw new Error(error.detail || error.message || `Request failed with status ${response.status}`)
  }

  return response.json()
}

/**
 * Export aussi les méthodes HTTP courantes pour plus de commodité.
 */
export const httpClient = {
  get: async <T = any>(url: string, options?: RequestInit): Promise<T> => {
    return fetchJsonWithAuth<T>(url, { ...options, method: 'GET' })
  },

  post: async <T = any>(url: string, body?: any, options?: RequestInit): Promise<T> => {
    return fetchJsonWithAuth<T>(url, {
      ...options,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...options?.headers,
      },
      body: body ? JSON.stringify(body) : undefined,
    })
  },

  put: async <T = any>(url: string, body?: any, options?: RequestInit): Promise<T> => {
    return fetchJsonWithAuth<T>(url, {
      ...options,
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        ...options?.headers,
      },
      body: body ? JSON.stringify(body) : undefined,
    })
  },

  delete: async <T = any>(url: string, options?: RequestInit): Promise<T> => {
    return fetchJsonWithAuth<T>(url, { ...options, method: 'DELETE' })
  },

  patch: async <T = any>(url: string, body?: any, options?: RequestInit): Promise<T> => {
    return fetchJsonWithAuth<T>(url, {
      ...options,
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        ...options?.headers,
      },
      body: body ? JSON.stringify(body) : undefined,
    })
  },
}
