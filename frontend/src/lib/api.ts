import axios, { AxiosInstance, AxiosRequestConfig, AxiosResponse } from 'axios'

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

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
      baseURL: '/api',
      timeout: 30000,
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

        // Add current user ID header if available
        if (typeof window !== 'undefined') {
          const currentUserData = localStorage.getItem('sap-kb-current-user')
          if (currentUserData) {
            try {
              const user = JSON.parse(currentUserData)
              if (user && user.id) {
                config.headers['X-User-ID'] = user.id
              }
            } catch (error) {
              console.warn('Erreur lors du parsing des données utilisateur:', error)
            }
          }
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
  // Documents - Using the existing /dispatch endpoint
  documents: {
    list: () => apiClient.get('/documents'), // Not implemented in backend yet
    upload: (file: File, documentType?: string) => {
      const formData = new FormData()
      formData.append('action_type', 'ingest')
      formData.append('file', file)
      if (documentType) {
        formData.append('document_type', documentType)
      }
      return api.dispatch.action(formData)
    },
    get: (id: string) => apiClient.get(`/documents/${id}`), // Not implemented in backend yet
    delete: (id: string) => apiClient.delete(`/documents/${id}`), // Not implemented in backend yet
  },

  // Chat - Using the direct /search endpoint (more logical)
  chat: {
    send: (message: string, language?: string, mime?: string, solution?: string) =>
      apiClient.post('/search', { question: message, language, mime, solution }),
    history: () => apiClient.get('/chat/history'), // Not implemented in backend yet
    conversation: (id: string) => apiClient.get(`/chat/${id}`), // Not implemented in backend yet
  },

  // Search endpoint (same as chat.send but more explicit)
  search: {
    query: (question: string, language?: string, mime?: string, solution?: string) =>
      apiClient.post('/search', { question, language, mime, solution }),
    solutions: () => apiClient.get('/solutions'),
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

  // Users
  users: {
    list: () => apiClient.get('/users'),
    get: (id: string) => apiClient.get(`/users/${id}`),
    create: (user: any) => apiClient.post('/users', user),
    update: (id: string, user: any) => apiClient.put(`/users/${id}`, user),
    delete: (id: string) => apiClient.delete(`/users/${id}`),
    updateActivity: (id: string) => apiClient.post(`/users/${id}/activity`),
    getDefault: () => apiClient.get('/users/default'),
    setDefault: (id: string) => apiClient.post(`/users/${id}/set-default`),
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
}