/**
 * Instance axios configurée avec intercepteur JWT automatique
 *
 * Utiliser cette instance au lieu de axios directement pour bénéficier
 * de l'injection automatique du token JWT dans toutes les requêtes.
 */

import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios'
import { authService } from './auth'

// Créer une instance axios personnalisée
const axiosInstance = axios.create({
  baseURL: '/',
  timeout: 120000, // 2 minutes par défaut (ajustable par requête)
  headers: {
    'Content-Type': 'application/json',
  },
})

// Intercepteur de requête : ajoute automatiquement le token JWT
axiosInstance.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    // Récupérer le token JWT
    const token = authService.getAccessToken()

    // Ajouter le token dans les headers si disponible
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }

    return config
  },
  (error: AxiosError) => {
    return Promise.reject(error)
  }
)

// Intercepteur de réponse : gère les erreurs d'authentification
axiosInstance.interceptors.response.use(
  (response) => {
    // Retourner directement la réponse si succès
    return response
  },
  async (error: AxiosError) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean }

    // Si erreur 401 (non authentifié)
    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true

      try {
        // Tenter de rafraîchir le token
        const newToken = await authService.refreshToken()

        if (newToken && originalRequest.headers) {
          // Mettre à jour le header avec le nouveau token
          originalRequest.headers.Authorization = `Bearer ${newToken}`

          // Rejouer la requête avec le nouveau token
          return axiosInstance(originalRequest)
        }
      } catch (refreshError) {
        // Si le refresh échoue, déconnecter l'utilisateur
        authService.logout()

        // Rediriger vers la page de login
        if (typeof window !== 'undefined') {
          window.location.href = '/login'
        }

        return Promise.reject(refreshError)
      }
    }

    // Pour toutes les autres erreurs, les propager
    return Promise.reject(error)
  }
)

export default axiosInstance

// Export aussi axios natif pour les cas spécifiques
export { axios }
