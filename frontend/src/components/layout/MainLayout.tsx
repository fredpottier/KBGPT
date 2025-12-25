'use client'

import { Box, Center, Spinner, VStack, Text } from '@chakra-ui/react'
import { usePathname, useRouter } from 'next/navigation'
import { useEffect } from 'react'
import { useAuth } from '@/contexts/AuthContext'
import TopNavigation from './TopNavigation'

interface MainLayoutProps {
  children: React.ReactNode
}

export default function MainLayout({ children }: MainLayoutProps) {
  const pathname = usePathname()
  const router = useRouter()
  const { isAuthenticated, isLoading } = useAuth()

  // Pages d'authentification (pas de navigation)
  const isAuthPage = pathname === '/login' || pathname === '/register'

  // Redirection si non authentifié
  useEffect(() => {
    if (!isLoading && !isAuthenticated && !isAuthPage) {
      const redirectUrl = encodeURIComponent(pathname || '/')
      router.push(`/login?redirect=${redirectUrl}`)
    }
  }, [isLoading, isAuthenticated, isAuthPage, pathname, router])

  // Si page d'authentification, afficher uniquement le contenu sans navigation
  if (isAuthPage) {
    return (
      <Box minH="100vh" bg="bg.primary">
        {children}
      </Box>
    )
  }

  // Pendant le chargement de l'authentification
  if (isLoading) {
    return (
      <Center h="100vh" bg="bg.primary">
        <VStack spacing={4}>
          <Spinner
            size="xl"
            color="brand.500"
            thickness="3px"
            speed="0.8s"
          />
          <Text color="text.secondary">Vérification de l'authentification...</Text>
        </VStack>
      </Center>
    )
  }

  // Si pas authentifié et pas sur page auth, ne rien afficher (redirection en cours)
  if (!isAuthenticated) {
    return null
  }

  return (
    <Box minH="100vh" bg="bg.primary">
      {/* Navigation horizontale avec dropdowns */}
      <TopNavigation />

      {/* Contenu principal - pleine largeur */}
      <Box
        pt="64px"
        minH="calc(100vh - 64px)"
      >
        <Box p={6} maxW="1400px" mx="auto">
          {children}
        </Box>
      </Box>
    </Box>
  )
}