'use client'

/**
 * Rendu d'une assertion individuelle - OSMOSE Assertion-Centric.
 *
 * Mode simplifie (2026-01):
 * - Coloration du texte uniquement selon le statut
 * - FACT: vert (green.500)
 * - INFERRED: orange (orange.400)
 * - FRAGILE: gris (gray.500)
 * - CONFLICT: rouge (red.500)
 *
 * Pas de bordures, marges speciales, italiques ou soulignements.
 * En mode simple: texte noir sans coloration.
 */

import { useMemo } from 'react'
import {
  Box,
  Text,
} from '@chakra-ui/react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Assertion, SourceRef, InstrumentationMode } from '@/types/instrumented'
import { getAssertionRenderConfig } from '@/types/instrumented'
import AssertionPopover from './AssertionPopover'

// Couleurs simplifiees par statut
const STATUS_COLORS: Record<string, string> = {
  FACT: 'green.500',
  INFERRED: 'orange.400',
  FRAGILE: 'gray.500',
  CONFLICT: 'red.500',
}

interface AssertionRendererProps {
  assertion: Assertion
  sources: SourceRef[]
  mode: InstrumentationMode
  onSourceClick?: (sourceId: string) => void
}

export default function AssertionRenderer({
  assertion,
  sources,
  mode,
  onSourceClick,
}: AssertionRendererProps) {
  const config = useMemo(() => getAssertionRenderConfig(mode), [mode])

  // Couleur du texte selon le mode
  const textColor = config.showStatusIndicators
    ? STATUS_COLORS[assertion.status] || 'text.primary'
    : 'text.primary'

  // Toujours montrer le hover en mode instrumented (sources ou statut)
  const showHover = config.enableHoverPopover

  // Contenu de l'assertion - simplifie sans bordures ni indicateurs
  const assertionContent = (
    <Box
      mb={2}
      transition="background 0.2s"
      _hover={{
        bg: showHover ? 'blackAlpha.50' : undefined,
      }}
      borderRadius="sm"
      cursor={showHover ? 'help' : 'default'}
    >
      <Text
        fontSize="sm"
        lineHeight="1.7"
        color={textColor}
      >
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            p: ({ children }) => <>{children}</>,
            strong: ({ children }) => (
              <Text as="span" fontWeight="bold">{children}</Text>
            ),
            em: ({ children }) => (
              <Text as="span" fontStyle="italic">{children}</Text>
            ),
          }}
        >
          {assertion.text_md}
        </ReactMarkdown>
      </Text>
    </Box>
  )

  // Avec popover si hover active ET sources disponibles
  if (showHover) {
    return (
      <AssertionPopover
        assertion={assertion}
        sources={sources}
        onSourceClick={onSourceClick}
      >
        {assertionContent}
      </AssertionPopover>
    )
  }

  return assertionContent
}

export { AssertionRenderer }
