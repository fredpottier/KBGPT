export type UserRole = 'admin' | 'expert' | 'user'

export interface User {
  id: string
  name: string
  email?: string
  role: UserRole
  created_at: string
  last_active: string
}

export interface UserCreate {
  name: string
  email?: string
  role?: UserRole
}

export interface UserUpdate {
  name?: string
  email?: string
  role?: UserRole
}

export interface UserListResponse {
  users: User[]
  total: number
}

export interface UserContextType {
  // État actuel
  currentUser: User | null
  availableUsers: User[]
  defaultUser: User | null
  isLoading: boolean
  error: string | null

  // Actions
  switchUser: (userIdOrUser: string | User) => Promise<void>
  createUser: (userData: UserCreate) => Promise<User>
  updateUser: (userId: string, userData: UserUpdate) => Promise<User>
  deleteUser: (userId: string) => Promise<void>
  refreshUsers: () => Promise<void>
  updateUserActivity: (userId: string) => Promise<void>
  setDefaultUser: (userId: string) => Promise<User>
}