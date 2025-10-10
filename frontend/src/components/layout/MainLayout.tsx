'use client'

import { Box, Flex } from '@chakra-ui/react'
import { usePathname } from 'next/navigation'
import TopNavigation from './TopNavigation'
import ContextualSidebar from './ContextualSidebar'

interface MainLayoutProps {
  children: React.ReactNode
}

export default function MainLayout({ children }: MainLayoutProps) {
  const pathname = usePathname()

  // Pages d'authentification (pas de navigation)
  const isAuthPage = pathname === '/login' || pathname === '/register'

  // Si page d'authentification, afficher uniquement le contenu sans navigation
  if (isAuthPage) {
    return (
      <Box minH="100vh" bg="gray.50">
        {children}
      </Box>
    )
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
        >
          <Box p={6} h="full">
            {children}
          </Box>
        </Box>
      </Flex>
    </Box>
  )
}