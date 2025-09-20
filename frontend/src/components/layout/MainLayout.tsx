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

  // Déterminer la section actuelle
  const getCurrentSection = (): 'chat' | 'documents' | 'admin' => {
    if (pathname?.startsWith('/chat')) return 'chat'
    if (pathname?.startsWith('/documents')) return 'documents'
    if (pathname?.startsWith('/admin')) return 'admin'
    return 'chat' // par défaut
  }

  const currentSection = getCurrentSection()
  const showSidebar = currentSection !== 'chat' && (
    currentSection === 'documents' ||
    (currentSection === 'admin' && false) // Admin sidebar vide pour le moment
  )

  return (
    <Box minH="100vh">
      {/* Navigation horizontale en haut */}
      <TopNavigation />

      <Flex>
        {/* Menu latéral contextuel */}
        <ContextualSidebar section={currentSection} />

        {/* Contenu principal */}
        <Box
          flex="1"
          ml={showSidebar && currentSection === 'documents' ? '256px' : '0'} // 64 * 4 = 256px
          pt="64px" // Hauteur de la TopNavigation
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