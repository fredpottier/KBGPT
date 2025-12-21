'use client'

import { Box, Flex, Center, Spinner, VStack, Text } from '@chakra-ui/react'
import { usePathname, useRouter } from 'next/navigation'
import { useEffect } from 'react'
import { useAuth } from '@/contexts/AuthContext'
import TopNavigation from './TopNavigation'
import ContextualSidebar from './ContextualSidebar'

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
    console.log('[MainLayout] Auth Check:', {
      pathname,
      isLoading,
      isAuthenticated,
      isAuthPage,
    })

    if (!isLoading && !isAuthenticated && !isAuthPage) {
      // Sauvegarder l'URL pour redirection après login
      const redirectUrl = encodeURIComponent(pathname || '/')
      console.log('[MainLayout] Not authenticated, redirecting to /login')
      router.push(`/login?redirect=${redirectUrl}`)
    }
  }, [isLoading, isAuthenticated, isAuthPage, pathname, router])

  // Si page d'authentification, afficher uniquement le contenu sans navigation
  if (isAuthPage) {
    return (
      <Box minH="100vh" bg="gray.50">
        {children}
      </Box>
    )
  }

  // Pendant le chargement de l'authentification
  if (isLoading) {
    return (
      <Center h="100vh" bg="gray.50">
        <VStack spacing={4}>
          <Spinner size="xl" color="brand.500" thickness="4px" />
          <Text color="gray.600">Vérification de l'authentification...</Text>
        </VStack>
      </Center>
    )
  }

  // Si pas authentifié et pas sur page auth, ne rien afficher (redirection en cours)
  if (!isAuthenticated) {
    return null
  }

  // Déterminer la section actuelle
  const getCurrentSection = (): 'chat' | 'documents' | 'admin' => {
    if (pathname?.startsWith('/chat')) return 'chat'
    if (pathname?.startsWith('/documents')) return 'documents'
    if (pathname?.startsWith('/rfp-excel')) return 'documents' // RFP Excel fait partie de documents
    if (pathname?.startsWith('/admin')) return 'admin'
    return 'chat' // par défaut
  }

  const currentSection = getCurrentSection()
  const showSidebar = currentSection !== 'chat' && (
    currentSection === 'documents' ||
    currentSection === 'admin' // Admin sidebar avec menu ontologies
  )

  return (
    <Box minH="100vh">
      {/* Navigation horizontale en haut - maintenant sticky */}
      <TopNavigation />

      <Flex pt="64px"> {/* Padding top pour le menu sticky */}
        {/* Menu latéral contextuel */}
        <ContextualSidebar section={currentSection} />

        {/* Contenu principal */}
        <Box
          flex="1"
          ml={showSidebar ? '256px' : '0'} // 64 * 4 = 256px (sidebar documents ou admin)
          minH="calc(100vh - 64px)"
          bg="gray.50"
          overflowY="auto"
        >
          <Box p={6}>
            {children}
          </Box>
        </Box>
      </Flex>
    </Box>
  )
}