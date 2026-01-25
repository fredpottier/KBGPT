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
      bg="gray.50"
      _dark={{ bg: 'gray.700' }}
      borderRadius="md"
      cursor={onClick ? 'pointer' : 'default'}
      _hover={onClick ? { bg: 'gray.100', _dark: { bg: 'gray.600' } } : undefined}
      onClick={onClick}
      transition="background 0.2s"
    >
      {/* Extrait */}
      <Text fontSize="xs" color="gray.700" _dark={{ color: 'gray.200' }} fontStyle="italic">
        "{source.excerpt}"
      </Text>

      {/* Nom du document */}
      <Text fontSize="10px" color="gray.500" mt={1} fontWeight="medium">
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
        bg="white"
        _dark={{ bg: 'gray.800' }}
        borderColor="gray.200"
        _dark-borderColor="gray.600"
        boxShadow="md"
        maxW="350px"
        _focus={{ boxShadow: 'md' }}
      >
        <PopoverArrow bg="white" _dark={{ bg: 'gray.800' }} />
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
                  <Text fontSize="10px" color="gray.400" textAlign="center">
                    +{relatedSources.length - 3} autres sources
                  </Text>
                )}
              </>
            ) : (
              /* Fallback: juste le statut si pas de sources */
              <Text fontSize="xs" color="gray.500" fontStyle="italic">
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
