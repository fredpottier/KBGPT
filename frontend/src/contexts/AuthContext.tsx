'use client'

import React, { createContext, useContext, useState, useEffect, useCallback, useRef, ReactNode } from 'react'
import { authService, User, LoginCredentials, RegisterData } from '@/lib/auth'
import { useRouter } from 'next/navigation'

// Intervalle de vérification du token (toutes les 2 minutes)
const TOKEN_CHECK_INTERVAL = 2 * 60 * 1000

interface AuthContextType {
  user: User | null
  isAuthenticated: boolean
  isLoading: boolean
  login: (credentials: LoginCredentials) => Promise<void>
  logout: () => void
  register: (data: RegisterData) => Promise<void>
  refreshUser: () => Promise<void>
  hasRole: (role: 'admin' | 'editor' | 'viewer') => boolean
  isAdmin: () => boolean
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

interface AuthProviderProps {
  children: ReactNode
}

export function AuthProvider({ children }: AuthProviderProps) {
  const [user, setUser] = useState<User | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isMounted, setIsMounted] = useState(false)
  const refreshIntervalRef = useRef<NodeJS.Timeout | null>(null)
  const router = useRouter()

  // Fonction pour vérifier et rafraîchir le token si nécessaire
  const checkAndRefreshToken = useCallback(async () => {
    // Utiliser ensureValidToken qui gère le refresh proactif
    const token = await authService.ensureValidToken()

    if (!token && user) {
      // Token invalide et pas de refresh possible -> déconnexion silencieuse
      console.log('[AuthContext] Token invalid and refresh failed, logging out')
      authService.logout()
      setUser(null)
      window.location.href = '/login'
    }
  }, [user])

  // Timer pour vérifier périodiquement le token
  useEffect(() => {
    if (!user) {
      // Pas d'utilisateur connecté, arrêter le timer
      if (refreshIntervalRef.current) {
        clearInterval(refreshIntervalRef.current)
        refreshIntervalRef.current = null
      }
      return
    }

    // Démarrer le timer de vérification
    console.log('[AuthContext] Starting token refresh timer (every 2 min)')
    refreshIntervalRef.current = setInterval(checkAndRefreshToken, TOKEN_CHECK_INTERVAL)

    // Cleanup
    return () => {
      if (refreshIntervalRef.current) {
        clearInterval(refreshIntervalRef.current)
        refreshIntervalRef.current = null
      }
    }
  }, [user, checkAndRefreshToken])

  // Rafraîchir le token quand l'onglet devient visible
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible' && user) {
        console.log('[AuthContext] Tab became visible, checking token...')
        checkAndRefreshToken()
      }
    }

    document.addEventListener('visibilitychange', handleVisibilityChange)

    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [user, checkAndRefreshToken])

  // Au chargement, vérifier si user authentifié
  useEffect(() => {
    setIsMounted(true)

    const initAuth = async () => {
      try {
        // Utiliser isAuthenticatedAsync pour tenter un refresh si le token est expiré
        const isValid = await authService.isAuthenticatedAsync()

        if (isValid) {
          const storedUser = authService.getUser()

          if (storedUser) {
            setUser(storedUser)
          } else {
            // Token présent mais pas de user en cache, fetch depuis API
            const currentUser = await authService.getCurrentUser()
            setUser(currentUser)
          }
        }
      } catch (error) {
        console.error('Failed to initialize auth:', error)
        // Token invalide, nettoyer
        authService.logout()
      } finally {
        setIsLoading(false)
      }
    }

    initAuth()
  }, [])

  const login = async (credentials: LoginCredentials) => {
    console.log('[AuthContext] Login started for:', credentials.email)
    setIsLoading(true)
    try {
      const response = await authService.login(credentials)
      console.log('[AuthContext] Login successful, user:', response.user)
      setUser(response.user)
      console.log('[AuthContext] User state updated, isAuthenticated will become true')
      // Redirection gérée par la page login pour supporter le paramètre ?redirect
    } catch (error) {
      console.error('[AuthContext] Login failed:', error)
      throw error
    } finally {
      setIsLoading(false)
    }
  }

  const logout = () => {
    console.log('[AuthContext] Logout called')
    authService.logout()
    setUser(null)
    console.log('[AuthContext] User state cleared, user is now null')

    // Force un refresh complet de la page pour réinitialiser tout le state
    // plutôt qu'un simple router.push qui garde le state React
    console.log('[AuthContext] Forcing full page reload to /login')
    window.location.href = '/login'
  }

  const register = async (data: RegisterData) => {
    setIsLoading(true)
    try {
      const response = await authService.register(data)
      setUser(response.user)
      // Redirection gérée par la page register
    } catch (error) {
      console.error('Registration failed:', error)
      throw error
    } finally {
      setIsLoading(false)
    }
  }

  const refreshUser = async () => {
    try {
      const currentUser = await authService.getCurrentUser()
      setUser(currentUser)
    } catch (error) {
      console.error('Failed to refresh user:', error)
      // Si échec, logout
      logout()
    }
  }

  const hasRole = useCallback((role: 'admin' | 'editor' | 'viewer'): boolean => {
    if (!user) return false

    // Hiérarchie: admin > editor > viewer
    if (role === 'viewer') return true // Tous les users authentifiés sont au moins viewer
    if (role === 'editor') return user.role === 'admin' || user.role === 'editor'
    if (role === 'admin') return user.role === 'admin'

    return false
  }, [user])

  const isAdmin = useCallback((): boolean => {
    return user?.role === 'admin'
  }, [user])

  const value: AuthContextType = {
    user,
    isAuthenticated: !!user,
    isLoading: isLoading || !isMounted, // Loading si pas encore monté côté client
    login,
    logout,
    register,
    refreshUser,
    hasRole,
    isAdmin,
  }

  // Toujours rendre le Provider, mais avec isLoading=true tant que pas monté côté client
  // Cela évite l'hydration mismatch tout en permettant à ProtectedRoute de fonctionner
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
