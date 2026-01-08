'use client'

/**
 * Icone d'oeil pour le mode d'affichage Instrumented (Assertion-Centric UX).
 *
 * Par defaut: Oeil ferme - texte affiche normalement
 * Active: Oeil ouvert avec halo - revele couleurs, hover details, proof tickets
 */

import { useState, useEffect, useCallback } from 'react'
import {
  Box,
  Tooltip,
  Icon,
  keyframes,
} from '@chakra-ui/react'
import { FiEye, FiEyeOff } from 'react-icons/fi'
import type { InstrumentationMode } from '@/types/instrumented'

const STORAGE_KEY = 'osmose_instrumentation_mode'
const FIRST_VISIT_KEY = 'osmose_instrumentation_first_visit'

// Animation de halo subtil
const glowAnimation = keyframes`
  0%, 100% {
    box-shadow: 0 0 4px 2px rgba(34, 197, 94, 0.3);
  }
  50% {
    box-shadow: 0 0 8px 4px rgba(34, 197, 94, 0.5);
  }
`

interface InstrumentedToggleProps {
  /** Callback quand le mode change */
  onModeChange: (mode: InstrumentationMode) => void
  /** Mode initial (optionnel, sinon lu depuis localStorage) */
  initialMode?: InstrumentationMode
  /** Taille de l'icone */
  size?: 'sm' | 'md'
}

export default function InstrumentedToggle({
  onModeChange,
  initialMode,
  size = 'sm',
}: InstrumentedToggleProps) {
  const [mode, setMode] = useState<InstrumentationMode>(initialMode || 'simple')
  const [isFirstVisit, setIsFirstVisit] = useState(false)
  const [isTransitioning, setIsTransitioning] = useState(false)

  // Charger le mode depuis localStorage au montage
  useEffect(() => {
    if (typeof window !== 'undefined') {
      const savedMode = localStorage.getItem(STORAGE_KEY) as InstrumentationMode | null
      const firstVisit = localStorage.getItem(FIRST_VISIT_KEY)

      if (savedMode && (savedMode === 'simple' || savedMode === 'instrumented')) {
        setMode(savedMode)
        onModeChange(savedMode)
      }

      if (!firstVisit) {
        setIsFirstVisit(true)
        localStorage.setItem(FIRST_VISIT_KEY, 'false')
      }
    }
  }, [onModeChange])

  // Handler pour le changement de mode
  const handleToggle = useCallback(() => {
    setIsTransitioning(true)

    const newMode: InstrumentationMode = mode === 'simple' ? 'instrumented' : 'simple'

    // Animation de transition
    setTimeout(() => {
      setMode(newMode)
      onModeChange(newMode)

      // Sauvegarder dans localStorage
      if (typeof window !== 'undefined') {
        localStorage.setItem(STORAGE_KEY, newMode)
      }

      setIsTransitioning(false)
    }, 100)
  }, [mode, onModeChange])

  const isInstrumented = mode === 'instrumented'
  const iconSize = size === 'sm' ? 4 : 5

  const tooltipLabel = isInstrumented
    ? 'Masquer les details de verite'
    : 'Voir les details de verite'

  const firstVisitTooltip = isFirstVisit
    ? 'Cliquez pour voir les preuves de chaque affirmation'
    : tooltipLabel

  return (
    <Tooltip
      label={firstVisitTooltip}
      placement="bottom"
      hasArrow
      bg="gray.700"
      color="white"
      fontSize="xs"
      px={3}
      py={2}
      borderRadius="md"
      isOpen={isFirstVisit ? true : undefined}
      onClose={() => setIsFirstVisit(false)}
    >
      <Box
        as="button"
        display="flex"
        alignItems="center"
        justifyContent="center"
        w={size === 'sm' ? 7 : 8}
        h={size === 'sm' ? 7 : 8}
        borderRadius="full"
        cursor="pointer"
        onClick={handleToggle}
        transition="all 0.2s ease-out"
        transform={isTransitioning ? 'scale(0.9)' : 'scale(1)'}
        bg={isInstrumented ? 'rgba(34, 197, 94, 0.15)' : 'transparent'}
        _hover={{
          bg: isInstrumented ? 'rgba(34, 197, 94, 0.25)' : 'rgba(128, 128, 128, 0.15)',
          transform: 'scale(1.05)',
        }}
        _active={{
          transform: 'scale(0.95)',
        }}
        animation={isInstrumented ? `${glowAnimation} 2s ease-in-out infinite` : 'none'}
        aria-label={tooltipLabel}
      >
        <Icon
          as={isInstrumented ? FiEye : FiEyeOff}
          boxSize={iconSize}
          color={isInstrumented ? 'green.400' : 'gray.400'}
          transition="all 0.2s"
          filter={isInstrumented ? 'drop-shadow(0 0 2px rgba(34, 197, 94, 0.6))' : 'none'}
        />
      </Box>
    </Tooltip>
  )
}

export { InstrumentedToggle }
