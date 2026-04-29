'use client'

/**
 * Popover simplifie pour une assertion - OSMOSE Assertion-Centric.
 *
 * Mode simplifie (2026-01):
 * Affiche au hover:
 * - L'extrait de texte source (excerpt) + nom du document
 * - Si pas de sources liees, affiche juste le statut
 */

import {
  Box,
  VStack,
  Text,
  Popover,
  PopoverTrigger,
  PopoverContent,
  PopoverArrow,
  PopoverBody,
} from '@chakra-ui/react'
import type { Assertion, SourceRef, AssertionStatus } from '@/types/instrumented'

// Labels simples par statut
const STATUS_LABELS: Record<AssertionStatus, string> = {
  FACT: 'Fait confirme par les sources',
  INFERRED: 'Deduit logiquement',
  FRAGILE: 'Support faible',
  CONFLICT: 'Sources contradictoires',
}

interface AssertionPopoverProps {
  assertion: Assertion
  sources: SourceRef[]
  children: React.ReactNode
  onSourceClick?: (sourceId: string) => void
}

/**
 * Rendu simplifie d'une source: juste l'extrait et le nom du document.
 */
function SimpleSourceItem({
  source,
  onClick,
}: {
  source: SourceRef
  onClick?: () => void
}) {
  return (
    <Box
      p={2}
      bg="bg.surface"
      _dark={{ bg: 'bg.surface-alt' }}
      borderRadius="md"
      cursor={onClick ? 'pointer' : 'default'}
      _hover={onClick ? { bg: 'bg.surface-alt', _dark: { bg: 'fg.muted' } } : undefined}
      onClick={onClick}
      transition="background 0.2s"
    >
      {/* Extrait */}
      <Text fontSize="xs" color="fg.secondary" _dark={{ color: 'gray.200' }} fontStyle="italic">
        "{source.excerpt}"
      </Text>

      {/* Nom du document */}
      <Text fontSize="10px" color="fg.muted" mt={1} fontWeight="medium">
        — {source.document.title}
      </Text>
    </Box>
  )
}

export default function AssertionPopover({
  assertion,
  sources,
  children,
  onSourceClick,
}: AssertionPopoverProps) {
  // Filtrer les sources liees a cette assertion
  const relatedSources = sources.filter(s => assertion.sources.includes(s.id))

  return (
    <Popover trigger="hover" placement="top" openDelay={200} closeDelay={100}>
      <PopoverTrigger>
        <Box as="span" cursor="help">
          {children}
        </Box>
      </PopoverTrigger>
      <PopoverContent
        bg="bg.canvas"
        _dark={{ bg: 'bg.surface' }}
        borderColor="border.default"
        _dark-borderColor="border.strong"
        boxShadow="md"
        maxW="350px"
        _focus={{ boxShadow: 'md' }}
      >
        <PopoverArrow bg="bg.canvas" _dark={{ bg: 'bg.surface' }} />
        <PopoverBody p={2}>
          <VStack spacing={2} align="stretch">
            {/* Sources si disponibles */}
            {relatedSources.length > 0 ? (
              <>
                {relatedSources.slice(0, 3).map(source => (
                  <SimpleSourceItem
                    key={source.id}
                    source={source}
                    onClick={onSourceClick ? () => onSourceClick(source.id) : undefined}
                  />
                ))}
                {relatedSources.length > 3 && (
                  <Text fontSize="10px" color="fg.muted" textAlign="center">
                    +{relatedSources.length - 3} autres sources
                  </Text>
                )}
              </>
            ) : (
              /* Fallback: juste le statut si pas de sources */
              <Text fontSize="xs" color="fg.muted" fontStyle="italic">
                {STATUS_LABELS[assertion.status]}
              </Text>
            )}
          </VStack>
        </PopoverBody>
      </PopoverContent>
    </Popover>
  )
}

export { AssertionPopover }
