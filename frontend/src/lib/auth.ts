/**
 * Service d'authentification client-side.
 * Gère login, logout, refresh token et stockage JWT.
 */

// Détection automatique de l'URL API en fonction de l'environnement
// IMPORTANT: Cette fonction doit être appelée côté client uniquement
const getApiBaseUrl = (): string => {
  // Vérification runtime: si window est undefined, on est côté serveur
  // Dans ce cas, retourner l'URL interne Docker
  if (typeof window === 'undefined') {
    return process.env.NEXT_PUBLIC_API_INTERNAL_URL || 'http://app:8000'
  }

  // Côté client: utiliser window.location pour construire l'URL du backend
  const hostname = window.location.hostname
  const protocol = window.location.protocol

  // Si on est en localhost, utiliser localhost:8000
  if (hostname === 'localhost' || hostname === '127.0.0.1') {
    return 'http://localhost:8000'
  }

  // Sinon, sur EC2 avec NGINX reverse proxy
  // NGINX écoute sur port 80 et route /api vers backend:8000
  // Donc on utilise juste l'URL sans port (port 80 par défaut)
  return `${protocol}//${hostname}`
}

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
    const apiBaseUrl = getApiBaseUrl()
    console.log('[AuthService] Sending login request to:', `${apiBaseUrl}/api/auth/login`)
    console.log('[AuthService] Credentials:', { email: credentials.email, password: '***' })

    // Timeout de 10 secondes pour éviter de rester bloqué
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 10000)

    try {
      const response = await fetch(`${apiBaseUrl}/api/auth/login`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(credentials),
        signal: controller.signal,
      })

      clearTimeout(timeoutId)

      console.log('[AuthService] Response status:', response.status, response.statusText)

      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: 'Login failed' }))
        console.error('[AuthService] Login failed:', error)
        throw new Error(error.detail || 'Invalid credentials')
      }

      const data: AuthResponse = await response.json()
      console.log('[AuthService] Login successful, received tokens')

      // Stocker tokens et user
      this.setAccessToken(data.access_token)
      this.setRefreshToken(data.refresh_token)
      this.setUser(data.user)

      console.log('[AuthService] Tokens and user stored in localStorage')

      return data
    } catch (error: any) {
      clearTimeout(timeoutId)
      if (error.name === 'AbortError') {
        console.error('[AuthService] Login request timeout (10s)')
        throw new Error('Request timeout - please check your connection')
      }
      console.error('[AuthService] Login error:', error)
      throw error
    }
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

    const apiBaseUrl = getApiBaseUrl()
    const response = await fetch(`${apiBaseUrl}/api/auth/refresh`, {
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

    const apiBaseUrl = getApiBaseUrl()
    const response = await fetch(`${apiBaseUrl}/api/auth/me`, {
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
    const apiBaseUrl = getApiBaseUrl()
    const response = await fetch(`${apiBaseUrl}/api/auth/register`, {
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
