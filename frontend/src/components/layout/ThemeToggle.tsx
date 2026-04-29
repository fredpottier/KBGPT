'use client'

import { useEffect } from 'react'
import { IconButton, Tooltip, useColorMode } from '@chakra-ui/react'
import { FiSun, FiMoon } from 'react-icons/fi'
import { usePresetTheme } from '@/theme/PresetThemeProvider'

/**
 * ThemeToggle — Bascule dark/light mode.
 *
 * Source de vérité : PresetThemeProvider (mode = 'light' | 'dark').
 * Synchronise Chakra colorMode pour les composants qui en dépendent.
 */
export default function ThemeToggle() {
  const { mode, toggleMode } = usePresetTheme()
  const { colorMode, setColorMode } = useColorMode()

  // Sync Chakra colorMode <- mode du preset (source de vérité)
  useEffect(() => {
    if (colorMode !== mode) {
      setColorMode(mode)
    }
  }, [mode, colorMode, setColorMode])

  return (
    <Tooltip label={mode === 'dark' ? 'Mode clair' : 'Mode sombre'} placement="bottom" hasArrow>
      <IconButton
        aria-label="Toggle theme"
        icon={mode === 'dark' ? <FiSun /> : <FiMoon />}
        variant="ghost"
        size="sm"
        color="fg.muted"
        _hover={{ color: 'fg.primary', bg: 'bg.hover' }}
        onClick={toggleMode}
      />
    </Tooltip>
  )
}
