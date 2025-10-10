'use client'

import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react'
import { authService, User, LoginCredentials, RegisterData } from '@/lib/auth'
import { useRouter } from 'next/navigation'

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
  const router = useRouter()

  // Au chargement, vérifier si user authentifié
  useEffect(() => {
    setIsMounted(true)

    const initAuth = async () => {
      try {
        if (authService.isAuthenticated()) {
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
    setIsLoading(true)
    try {
      const response = await authService.login(credentials)
      setUser(response.user)
      router.push('/') // Rediriger vers home après login
    } catch (error) {
      console.error('Login failed:', error)
      throw error
    } finally {
      setIsLoading(false)
    }
  }

  const logout = () => {
    authService.logout()
    setUser(null)
    router.push('/login')
  }

  const register = async (data: RegisterData) => {
    setIsLoading(true)
    try {
      const response = await authService.register(data)
      setUser(response.user)
      router.push('/') // Rediriger vers home après register
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

  const hasRole = (role: 'admin' | 'editor' | 'viewer'): boolean => {
    return authService.hasRole(role)
  }

  const isAdmin = (): boolean => {
    return authService.isAdmin()
  }

  const value: AuthContextType = {
    user,
    isAuthenticated: !!user,
    isLoading,
    login,
    logout,
    register,
    refreshUser,
    hasRole,
    isAdmin,
  }

  // Éviter hydration mismatch : ne pas rendre tant que client-side n'est pas monté
  if (!isMounted) {
    return null
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
