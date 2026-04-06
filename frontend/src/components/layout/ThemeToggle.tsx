'use client'

import { useEffect } from 'react'
import { IconButton, Tooltip, useColorMode } from '@chakra-ui/react'
import { FiSun, FiMoon } from 'react-icons/fi'

/**
 * ThemeToggle — Bascule dark/light mode.
 *
 * Synchronise :
 * 1. Chakra colorMode (semantic tokens)
 * 2. data-theme sur <html> (CSS variables)
 * 3. localStorage (persistance)
 */
export default function ThemeToggle() {
  const { colorMode, toggleColorMode } = useColorMode()

  // Synchroniser data-theme avec colorMode de Chakra
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', colorMode)
  }, [colorMode])

  // Restaurer depuis localStorage au mount
  useEffect(() => {
    const saved = localStorage.getItem('chakra-ui-color-mode')
    if (saved) {
      document.documentElement.setAttribute('data-theme', saved)
    }
  }, [])

  return (
    <Tooltip label={colorMode === 'dark' ? 'Mode clair' : 'Mode sombre'} placement="bottom" hasArrow>
      <IconButton
        aria-label="Toggle theme"
        icon={colorMode === 'dark' ? <FiSun /> : <FiMoon />}
        variant="ghost"
        size="sm"
        color="text.muted"
        _hover={{ color: 'text.primary', bg: 'bg.hover' }}
        onClick={toggleColorMode}
      />
    </Tooltip>
  )
}
