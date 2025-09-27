'use client'

import React, { createContext, useContext, useEffect, useState } from 'react'
import { useToast } from '@chakra-ui/react'
import { api } from '@/lib/api'
import { useLocalStorage } from '@/hooks/useLocalStorage'
import { User, UserCreate, UserUpdate, UserContextType } from '@/types/user'

const UserContext = createContext<UserContextType | undefined>(undefined)

interface UserProviderProps {
  children: React.ReactNode
}

export function UserProvider({ children }: UserProviderProps) {
  const [currentUser, setCurrentUser] = useLocalStorage<User | null>('sap-kb-current-user', null)
  const [availableUsers, setAvailableUsers] = useState<User[]>([])
  const [defaultUser, setDefaultUser] = useState<User | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const toast = useToast()

  // Charger la liste des utilisateurs et l'utilisateur par défaut au démarrage
  const refreshUsers = async () => {
    try {
      setIsLoading(true)
      setError(null)

      // Charger la liste des utilisateurs
      const usersResponse = await api.users.list()
      if (usersResponse.success && usersResponse.data) {
        setAvailableUsers(usersResponse.data.users)
      } else {
        throw new Error(usersResponse.error || 'Erreur lors du chargement des utilisateurs')
      }

      // Charger l'utilisateur par défaut
      const defaultResponse = await api.users.getDefault()
      if (defaultResponse.success && defaultResponse.data) {
        setDefaultUser(defaultResponse.data)

        // Si aucun utilisateur n'est sélectionné, prendre l'utilisateur par défaut
        if (!currentUser) {
          setCurrentUser(defaultResponse.data)
        }
      } else {
        // Si pas d'utilisateur par défaut, fallback sur le premier utilisateur ou celui avec id 'default-user'
        if (usersResponse.success && usersResponse.data && !currentUser) {
          const fallbackUser = usersResponse.data.users.find(u => u.id === 'default-user') || usersResponse.data.users[0]
          if (fallbackUser) {
            setCurrentUser(fallbackUser)
            setDefaultUser(fallbackUser)
          }
        }
      }
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Erreur inconnue'
      setError(errorMessage)
      toast({
        title: 'Erreur',
        description: errorMessage,
        status: 'error',
        duration: 3000,
        isClosable: true,
      })
    } finally {
      setIsLoading(false)
    }
  }

  // Changer d'utilisateur
  const switchUser = async (userIdOrUser: string | User) => {
    try {
      setError(null)

      let user: User | undefined

      // Si c'est un objet utilisateur complet, l'utiliser directement
      if (typeof userIdOrUser === 'object' && userIdOrUser !== null) {
        user = userIdOrUser
      } else {
        // Sinon, chercher dans la liste par ID
        user = availableUsers.find(u => u.id === userIdOrUser)
        if (!user) {
          throw new Error(`Utilisateur avec l'ID '${userIdOrUser}' introuvable`)
        }
      }

      setCurrentUser(user)

      // Mettre à jour l'activité de l'utilisateur
      await api.users.updateActivity(user.id)

      toast({
        title: 'Utilisateur changé',
        description: `Connecté en tant que ${user.name}`,
        status: 'success',
        duration: 2000,
        isClosable: true,
      })
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Erreur lors du changement d\'utilisateur'
      setError(errorMessage)
      toast({
        title: 'Erreur',
        description: errorMessage,
        status: 'error',
        duration: 3000,
        isClosable: true,
      })
    }
  }

  // Créer un nouvel utilisateur
  const createUser = async (userData: UserCreate): Promise<User> => {
    try {
      setError(null)

      const response = await api.users.create(userData)
      if (response.success && response.data) {
        const newUser = response.data
        setAvailableUsers(prev => [...prev, newUser])

        toast({
          title: 'Utilisateur créé',
          description: `${newUser.name} a été créé avec succès`,
          status: 'success',
          duration: 3000,
          isClosable: true,
        })

        return newUser
      } else {
        throw new Error(response.error || 'Erreur lors de la création de l\'utilisateur')
      }
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Erreur lors de la création'
      setError(errorMessage)
      toast({
        title: 'Erreur de création',
        description: errorMessage,
        status: 'error',
        duration: 3000,
        isClosable: true,
      })
      throw err
    }
  }

  // Mettre à jour un utilisateur
  const updateUser = async (userId: string, userData: UserUpdate): Promise<User> => {
    try {
      setError(null)

      const response = await api.users.update(userId, userData)
      if (response.success && response.data) {
        const updatedUser = response.data
        setAvailableUsers(prev => prev.map(u => u.id === userId ? updatedUser : u))

        // Si c'est l'utilisateur actuel, le mettre à jour
        if (currentUser?.id === userId) {
          setCurrentUser(updatedUser)
        }

        toast({
          title: 'Utilisateur mis à jour',
          description: `${updatedUser.name} a été modifié`,
          status: 'success',
          duration: 3000,
          isClosable: true,
        })

        return updatedUser
      } else {
        throw new Error(response.error || 'Erreur lors de la mise à jour de l\'utilisateur')
      }
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Erreur lors de la mise à jour'
      setError(errorMessage)
      toast({
        title: 'Erreur de mise à jour',
        description: errorMessage,
        status: 'error',
        duration: 3000,
        isClosable: true,
      })
      throw err
    }
  }

  // Supprimer un utilisateur
  const deleteUser = async (userId: string): Promise<void> => {
    try {
      setError(null)

      const userToDelete = availableUsers.find(u => u.id === userId)
      if (!userToDelete) {
        throw new Error('Utilisateur introuvable')
      }

      const response = await api.users.delete(userId)
      if (response.success) {
        setAvailableUsers(prev => prev.filter(u => u.id !== userId))

        // Si l'utilisateur supprimé était l'utilisateur actuel, basculer vers le par défaut
        if (currentUser?.id === userId) {
          const defaultUser = availableUsers.find(u => u.id === 'default-user')
          if (defaultUser) {
            setCurrentUser(defaultUser)
          } else if (availableUsers.length > 1) {
            setCurrentUser(availableUsers.find(u => u.id !== userId) || null)
          } else {
            setCurrentUser(null)
          }
        }

        toast({
          title: 'Utilisateur supprimé',
          description: `${userToDelete.name} a été supprimé`,
          status: 'info',
          duration: 3000,
          isClosable: true,
        })
      } else {
        throw new Error(response.error || 'Erreur lors de la suppression de l\'utilisateur')
      }
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Erreur lors de la suppression'
      setError(errorMessage)
      toast({
        title: 'Erreur de suppression',
        description: errorMessage,
        status: 'error',
        duration: 3000,
        isClosable: true,
      })
      throw err
    }
  }

  // Mettre à jour l'activité utilisateur
  const updateUserActivity = async (userId: string): Promise<void> => {
    try {
      await api.users.updateActivity(userId)
    } catch (err) {
      // Erreur silencieuse pour l'activité (pas critique)
      console.warn('Erreur lors de la mise à jour de l\'activité:', err)
    }
  }

  // Définir un utilisateur comme utilisateur par défaut
  const setDefaultUserFunc = async (userId: string): Promise<User> => {
    try {
      setError(null)

      const response = await api.users.setDefault(userId)
      if (response.success && response.data) {
        const newDefaultUser = response.data
        setDefaultUser(newDefaultUser)

        // Mettre à jour la propriété is_default dans la liste des utilisateurs disponibles
        setAvailableUsers(prev =>
          prev.map(u => ({ ...u, is_default: u.id === userId }))
        )

        toast({
          title: 'Utilisateur par défaut défini',
          description: `${newDefaultUser.name} est maintenant l'utilisateur par défaut`,
          status: 'success',
          duration: 3000,
          isClosable: true,
        })

        return newDefaultUser
      } else {
        throw new Error(response.error || 'Erreur lors de la définition de l\'utilisateur par défaut')
      }
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Erreur lors de la définition'
      setError(errorMessage)
      toast({
        title: 'Erreur',
        description: errorMessage,
        status: 'error',
        duration: 3000,
        isClosable: true,
      })
      throw err
    }
  }

  // Charger les utilisateurs au démarrage (seulement côté client)
  useEffect(() => {
    if (typeof window !== 'undefined') {
      refreshUsers()
    }
  }, [])

  // Mettre à jour l'activité de l'utilisateur actuel périodiquement
  useEffect(() => {
    if (!currentUser) return

    const interval = setInterval(() => {
      updateUserActivity(currentUser.id)
    }, 5 * 60 * 1000) // Toutes les 5 minutes

    return () => clearInterval(interval)
  }, [currentUser])

  const value: UserContextType = {
    currentUser,
    availableUsers,
    defaultUser,
    isLoading,
    error,
    switchUser,
    createUser,
    updateUser,
    deleteUser,
    refreshUsers,
    updateUserActivity,
    setDefaultUser: setDefaultUserFunc,
  }

  return (
    <UserContext.Provider value={value}>
      {children}
    </UserContext.Provider>
  )
}

// Hook pour utiliser le contexte utilisateur
export function useUser(): UserContextType {
  const context = useContext(UserContext)
  if (context === undefined) {
    throw new Error('useUser doit être utilisé dans un UserProvider')
  }
  return context
}