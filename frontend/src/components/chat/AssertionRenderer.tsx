'use client'

/**
 * Rendu d'une assertion individuelle - OSMOSE Assertion-Centric.
 *
 * Applique le style visuel selon le statut:
 * - FACT: ● vert en marge
 * - INFERRED: Texte italique
 * - FRAGILE: Souligne pointille
 * - CONFLICT: Fond rouge pale
 *
 * En mode simple: rendu sans style special
 */

import { useMemo } from 'react'
import {
  Box,
  Text,
  HStack,
} from '@chakra-ui/react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Assertion, SourceRef, InstrumentationMode, AssertionRenderConfig } from '@/types/instrumented'
import { ASSERTION_STYLES, getAssertionRenderConfig } from '@/types/instrumented'
import AssertionPopover from './AssertionPopover'

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
  const style = ASSERTION_STYLES[assertion.status]

  // Mode simple: rendu basique sans style
  if (!config.showStatusIndicators) {
    return (
      <Box mb={2}>
        <Text fontSize="sm" lineHeight="1.7" color="text.primary">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {assertion.text_md}
          </ReactMarkdown>
        </Text>
      </Box>
    )
  }

  // Mode instrumented: rendu avec indicateurs visuels
  const getStatusStyles = () => {
    switch (assertion.status) {
      case 'FACT':
        return {
          borderLeft: '3px solid',
          borderLeftColor: style.color,
          pl: 3,
          bg: 'transparent',
        }
      case 'INFERRED':
        return {
          fontStyle: 'italic',
          pl: 3,
          borderLeft: '3px solid',
          borderLeftColor: style.color,
          opacity: 0.9,
        }
      case 'FRAGILE':
        return {
          textDecoration: 'underline',
          textDecorationStyle: 'dotted',
          textDecorationColor: style.color,
          pl: 3,
          borderLeft: '3px solid',
          borderLeftColor: style.color,
        }
      case 'CONFLICT':
        return {
          bg: style.bgColor,
          borderLeft: '3px solid',
          borderLeftColor: style.color,
          pl: 3,
          borderRadius: 'sm',
        }
      default:
        return {}
    }
  }

  const statusStyles = getStatusStyles()

  // Contenu de l'assertion
  const assertionContent = (
    <Box
      mb={3}
      py={1}
      transition="all 0.2s"
      _hover={{
        bg: config.enableHoverPopover ? 'bg.hover' : undefined,
      }}
      {...statusStyles}
    >
      <HStack align="flex-start" spacing={2}>
        {/* Indicateur de statut */}
        <Text
          fontSize="sm"
          color={style.color}
          fontWeight="bold"
          mt="1px"
          minW="16px"
        >
          {style.indicator}
        </Text>

        {/* Texte de l'assertion */}
        <Box flex={1}>
          <Text
            fontSize="sm"
            lineHeight="1.7"
            color="text.primary"
            {...(assertion.status === 'INFERRED' ? { fontStyle: 'italic' } : {})}
            {...(assertion.status === 'FRAGILE' ? {
              textDecoration: 'underline',
              textDecorationStyle: 'dotted',
              textDecorationColor: style.color,
            } : {})}
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
      </HStack>
    </Box>
  )

  // Avec popover si hover active
  if (config.enableHoverPopover) {
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
