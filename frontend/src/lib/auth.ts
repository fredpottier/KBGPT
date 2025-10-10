/**
 * Service d'authentification client-side.
 * Gère login, logout, refresh token et stockage JWT.
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

export interface LoginCredentials {
  email: string
  password: string
}

export interface RegisterData {
  email: string
  password: string
  full_name?: string
  role?: 'admin' | 'editor' | 'viewer'
}

export interface AuthTokens {
  access_token: string
  refresh_token: string
  token_type: string
}

export interface User {
  user_id: string
  email: string
  full_name?: string
  role: 'admin' | 'editor' | 'viewer'
  is_active: boolean
  tenant_id: string
}

export interface AuthResponse {
  access_token: string
  refresh_token: string
  token_type: string
  user: User
}

class AuthService {
  private readonly ACCESS_TOKEN_KEY = 'auth_token'
  private readonly REFRESH_TOKEN_KEY = 'refresh_token'
  private readonly USER_KEY = 'user'

  /**
   * Login utilisateur et stocke les tokens.
   */
  async login(credentials: LoginCredentials): Promise<AuthResponse> {
    const response = await fetch(`${API_BASE_URL}/api/auth/login`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(credentials),
    })

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Login failed' }))
      throw new Error(error.detail || 'Invalid credentials')
    }

    const data: AuthResponse = await response.json()

    // Stocker tokens et user
    this.setAccessToken(data.access_token)
    this.setRefreshToken(data.refresh_token)
    this.setUser(data.user)

    return data
  }

  /**
   * Logout utilisateur et nettoie le stockage.
   */
  logout(): void {
    if (typeof window === 'undefined') return

    console.log('[AuthService] Logout - Clearing localStorage')
    localStorage.removeItem(this.ACCESS_TOKEN_KEY)
    localStorage.removeItem(this.REFRESH_TOKEN_KEY)
    localStorage.removeItem(this.USER_KEY)
    console.log('[AuthService] Logout - LocalStorage cleared:', {
      hasToken: !!localStorage.getItem(this.ACCESS_TOKEN_KEY),
      hasRefreshToken: !!localStorage.getItem(this.REFRESH_TOKEN_KEY),
      hasUser: !!localStorage.getItem(this.USER_KEY)
    })
  }

  /**
   * Refresh le access token avec le refresh token.
   */
  async refreshAccessToken(): Promise<string> {
    const refreshToken = this.getRefreshToken()

    if (!refreshToken) {
      throw new Error('No refresh token available')
    }

    const response = await fetch(`${API_BASE_URL}/api/auth/refresh`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })

    if (!response.ok) {
      // Refresh failed, logout
      this.logout()
      throw new Error('Refresh token expired')
    }

    const data: AuthTokens = await response.json()

    // Mettre à jour access token
    this.setAccessToken(data.access_token)

    // Si nouveau refresh token fourni, le mettre à jour aussi
    if (data.refresh_token) {
      this.setRefreshToken(data.refresh_token)
    }

    return data.access_token
  }

  /**
   * Récupère les infos utilisateur courant depuis l'API.
   */
  async getCurrentUser(): Promise<User> {
    const token = this.getAccessToken()

    if (!token) {
      throw new Error('No access token')
    }

    const response = await fetch(`${API_BASE_URL}/api/auth/me`, {
      method: 'GET',
      headers: {
        'Authorization': `Bearer ${token}`,
      },
    })

    if (!response.ok) {
      throw new Error('Failed to fetch user')
    }

    const user: User = await response.json()
    this.setUser(user)

    return user
  }

  /**
   * Register nouvel utilisateur.
   */
  async register(data: RegisterData): Promise<AuthResponse> {
    const response = await fetch(`${API_BASE_URL}/api/auth/register`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(data),
    })

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Registration failed' }))
      throw new Error(error.detail || 'Registration failed')
    }

    const authData: AuthResponse = await response.json()

    // Stocker tokens et user
    this.setAccessToken(authData.access_token)
    this.setRefreshToken(authData.refresh_token)
    this.setUser(authData.user)

    return authData
  }

  // === Storage helpers ===

  getAccessToken(): string | null {
    if (typeof window === 'undefined') return null
    return localStorage.getItem(this.ACCESS_TOKEN_KEY)
  }

  setAccessToken(token: string): void {
    if (typeof window === 'undefined') return
    localStorage.setItem(this.ACCESS_TOKEN_KEY, token)
  }

  getRefreshToken(): string | null {
    if (typeof window === 'undefined') return null
    return localStorage.getItem(this.REFRESH_TOKEN_KEY)
  }

  setRefreshToken(token: string): void {
    if (typeof window === 'undefined') return
    localStorage.setItem(this.REFRESH_TOKEN_KEY, token)
  }

  getUser(): User | null {
    if (typeof window === 'undefined') return null
    const userStr = localStorage.getItem(this.USER_KEY)
    if (!userStr) return null

    try {
      return JSON.parse(userStr)
    } catch {
      return null
    }
  }

  setUser(user: User): void {
    if (typeof window === 'undefined') return
    localStorage.setItem(this.USER_KEY, JSON.stringify(user))
  }

  /**
   * Vérifie si l'utilisateur est authentifié.
   */
  isAuthenticated(): boolean {
    return !!this.getAccessToken()
  }

  /**
   * Vérifie si l'utilisateur a un rôle spécifique.
   */
  hasRole(role: 'admin' | 'editor' | 'viewer'): boolean {
    const user = this.getUser()
    if (!user) return false

    // Hiérarchie: admin > editor > viewer
    if (role === 'viewer') return true // Tous les users authentifiés sont au moins viewer
    if (role === 'editor') return user.role === 'admin' || user.role === 'editor'
    if (role === 'admin') return user.role === 'admin'

    return false
  }

  /**
   * Vérifie si l'utilisateur est admin.
   */
  isAdmin(): boolean {
    return this.hasRole('admin')
  }
}

export const authService = new AuthService()
