'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import { Box, Spinner, Center, Text, VStack } from '@chakra-ui/react'

interface ProtectedRouteProps {
  children: React.ReactNode
  requireRole?: 'admin' | 'editor' | 'viewer'
}

/**
 * Composant pour protéger les routes nécessitant authentification.
 *
 * Usage:
 * ```tsx
 * <ProtectedRoute requireRole="admin">
 *   <AdminPage />
 * </ProtectedRoute>
 * ```
 */
export function ProtectedRoute({ children, requireRole }: ProtectedRouteProps) {
  const { isAuthenticated, isLoading, user, hasRole } = useAuth()
  const router = useRouter()

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      // Pas authentifié, rediriger vers login
      router.push(`/login?redirect=${encodeURIComponent(window.location.pathname)}`)
    } else if (!isLoading && isAuthenticated && requireRole && !hasRole(requireRole)) {
      // Authentifié mais pas le bon rôle, rediriger vers home avec message
      router.push('/?error=insufficient_permissions')
    }
  }, [isLoading, isAuthenticated, requireRole, router, hasRole])

  // Pendant le chargement
  if (isLoading) {
    return (
      <Center h="100vh">
        <VStack spacing={4}>
          <Spinner size="xl" color="brand.500" thickness="4px" />
          <Text color="gray.600">Loading...</Text>
        </VStack>
      </Center>
    )
  }

  // Si pas authentifié, ne rien afficher (la redirection est en cours)
  if (!isAuthenticated) {
    return null
  }

  // Si role requis et user ne l'a pas, ne rien afficher (redirection en cours)
  if (requireRole && !hasRole(requireRole)) {
    return (
      <Center h="100vh">
        <VStack spacing={4}>
          <Text fontSize="xl" color="red.500">
            ⛔ Insufficient Permissions
          </Text>
          <Text color="gray.600">
            You need the role "{requireRole}" to access this page.
          </Text>
          <Text color="gray.500" fontSize="sm">
            Your role: {user?.role}
          </Text>
        </VStack>
      </Center>
    )
  }

  // Tout est bon, afficher le contenu
  return <>{children}</>
}
