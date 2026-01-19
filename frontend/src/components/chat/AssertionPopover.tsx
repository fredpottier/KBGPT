'use client'

/**
 * Popover de details pour une assertion - OSMOSE Assertion-Centric.
 *
 * Affiche au hover:
 * - Statut de l'assertion avec explication
 * - Sources supportant l'assertion
 * - Note d'inference si INFERRED
 * - Apercu des sources contradictoires si CONFLICT
 */

import {
  Box,
  VStack,
  HStack,
  Text,
  Badge,
  Divider,
  Link,
  Icon,
  Popover,
  PopoverTrigger,
  PopoverContent,
  PopoverArrow,
  PopoverBody,
  Image,
} from '@chakra-ui/react'
import { FiExternalLink, FiFileText, FiAlertTriangle } from 'react-icons/fi'
import type { Assertion, SourceRef, AssertionStatus } from '@/types/instrumented'
import { ASSERTION_STYLES, AUTHORITY_COLORS } from '@/types/instrumented'

interface AssertionPopoverProps {
  assertion: Assertion
  sources: SourceRef[]
  children: React.ReactNode
  onSourceClick?: (sourceId: string) => void
}

/**
 * Rendu d'une source dans le popover.
 */
function SourceItem({
  source,
  onClick,
}: {
  source: SourceRef
  onClick?: () => void
}) {
  const authorityColor = AUTHORITY_COLORS[source.document.authority]

  return (
    <Box
      p={2}
      bg="bg.tertiary"
      borderRadius="md"
      cursor={onClick ? 'pointer' : 'default'}
      _hover={onClick ? { bg: 'bg.hover' } : undefined}
      onClick={onClick}
      transition="background 0.2s"
    >
      <HStack justify="space-between" mb={1}>
        <HStack spacing={2}>
          <Icon as={FiFileText} boxSize={3} color="text.secondary" />
          <Text fontSize="xs" fontWeight="medium" color="text.primary" noOfLines={1}>
            {source.document.title}
          </Text>
        </HStack>
        <Badge
          size="sm"
          fontSize="9px"
          bg={`${authorityColor}20`}
          color={authorityColor}
          px={1.5}
          py={0.5}
          borderRadius="full"
        >
          {source.document.authority}
        </Badge>
      </HStack>

      {/* Excerpt */}
      <Text fontSize="xs" color="text.secondary" noOfLines={2} pl={5}>
        "{source.excerpt}"
      </Text>

      {/* Locator */}
      {source.locator?.page_or_slide && (
        <HStack mt={1} pl={5} spacing={1}>
          <Text fontSize="10px" color="text.muted">
            Page/Slide {source.locator.page_or_slide}
          </Text>
          {source.thumbnail_url && (
            <Image
              src={source.thumbnail_url}
              alt="Thumbnail"
              boxSize="24px"
              objectFit="cover"
              borderRadius="sm"
            />
          )}
        </HStack>
      )}
    </Box>
  )
}

/**
 * Explication du statut.
 */
function StatusExplanation({ status }: { status: AssertionStatus }) {
  const explanations: Record<AssertionStatus, string> = {
    FACT: "Cette affirmation est explicitement presente dans une ou plusieurs sources verifiees.",
    INFERRED: "Cette affirmation est deduite logiquement d'autres faits etablis.",
    FRAGILE: "Cette affirmation n'est soutenue que par une seule source ou une source ancienne.",
    CONFLICT: "Attention: des sources contradictoires ont ete detectees pour cette affirmation.",
  }

  const style = ASSERTION_STYLES[status]

  return (
    <Box
      p={2}
      bg={`${style.bgColor}`}
      borderLeft="3px solid"
      borderLeftColor={style.borderColor}
      borderRadius="sm"
    >
      <HStack spacing={2} mb={1}>
        <Text fontSize="sm" fontWeight="semibold" color={style.color}>
          {style.indicator} {style.label}
        </Text>
      </HStack>
      <Text fontSize="xs" color="text.secondary">
        {explanations[status]}
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
  const contradictingSources = sources.filter(s => assertion.contradictions.includes(s.id))

  return (
    <Popover trigger="hover" placement="top" openDelay={300} closeDelay={100}>
      <PopoverTrigger>
        <Box as="span" cursor="help">
          {children}
        </Box>
      </PopoverTrigger>
      <PopoverContent
        bg="bg.secondary"
        borderColor="border.default"
        boxShadow="lg"
        maxW="400px"
        _focus={{ boxShadow: 'lg' }}
      >
        <PopoverArrow bg="bg.secondary" />
        <PopoverBody p={3}>
          <VStack spacing={3} align="stretch">
            {/* Status explanation */}
            <StatusExplanation status={assertion.status} />

            {/* Inference note */}
            {assertion.status === 'INFERRED' && assertion.inference_note && (
              <Box>
                <Text fontSize="xs" fontWeight="semibold" color="text.secondary" mb={1}>
                  Raisonnement:
                </Text>
                <Text fontSize="xs" color="text.primary" fontStyle="italic">
                  {assertion.inference_note}
                </Text>
              </Box>
            )}

            {/* Supporting sources */}
            {relatedSources.length > 0 && (
              <Box>
                <Text fontSize="xs" fontWeight="semibold" color="text.secondary" mb={2}>
                  Sources ({relatedSources.length}):
                </Text>
                <VStack spacing={2} align="stretch">
                  {relatedSources.slice(0, 3).map(source => (
                    <SourceItem
                      key={source.id}
                      source={source}
                      onClick={onSourceClick ? () => onSourceClick(source.id) : undefined}
                    />
                  ))}
                  {relatedSources.length > 3 && (
                    <Text fontSize="xs" color="text.muted" textAlign="center">
                      +{relatedSources.length - 3} autres sources
                    </Text>
                  )}
                </VStack>
              </Box>
            )}

            {/* Contradicting sources */}
            {contradictingSources.length > 0 && (
              <Box>
                <Divider my={2} />
                <HStack spacing={1} mb={2}>
                  <Icon as={FiAlertTriangle} boxSize={3} color="red.500" />
                  <Text fontSize="xs" fontWeight="semibold" color="red.500">
                    Sources contradictoires ({contradictingSources.length}):
                  </Text>
                </HStack>
                <VStack spacing={2} align="stretch">
                  {contradictingSources.slice(0, 2).map(source => (
                    <SourceItem
                      key={source.id}
                      source={source}
                      onClick={onSourceClick ? () => onSourceClick(source.id) : undefined}
                    />
                  ))}
                </VStack>
              </Box>
            )}

            {/* KG Evidence - 🌊 OSMOSE: Affiche la preuve KG si disponible */}
            {assertion.meta?.support?.kg_relation && (
              <Box
                p={2}
                bg="green.50"
                borderLeft="3px solid"
                borderLeftColor="green.500"
                borderRadius="sm"
              >
                <HStack spacing={2} mb={1}>
                  <Text fontSize="xs" fontWeight="semibold" color="green.700">
                    🔗 Relation KG confirmee: {assertion.meta.support.kg_relation}
                  </Text>
                  {assertion.meta.support.kg_confidence && (
                    <Badge size="sm" colorScheme="green" fontSize="9px">
                      {Math.round(assertion.meta.support.kg_confidence * 100)}%
                    </Badge>
                  )}
                </HStack>
                {assertion.meta.support.kg_evidence_quote && (
                  <Text fontSize="xs" color="green.600" fontStyle="italic" mt={1}>
                    "{assertion.meta.support.kg_evidence_quote}"
                  </Text>
                )}
                {assertion.meta.support.kg_source_count && assertion.meta.support.kg_source_count > 0 && (
                  <Text fontSize="10px" color="green.500" mt={1}>
                    Confirme par {assertion.meta.support.kg_source_count} source(s) dans le Knowledge Graph
                  </Text>
                )}
              </Box>
            )}

            {/* Meta info */}
            {assertion.meta?.support && (
              <Box pt={2} borderTop="1px solid" borderColor="border.default">
                <HStack spacing={3} fontSize="10px" color="text.muted" flexWrap="wrap">
                  <Text>
                    Support: {assertion.meta.support.supporting_sources_count} source(s)
                  </Text>
                  <Text>
                    Fraicheur: {assertion.meta.support.freshness}
                  </Text>
                  {assertion.meta.support.has_official && (
                    <Badge size="sm" colorScheme="green" fontSize="9px">
                      Source officielle
                    </Badge>
                  )}
                  {assertion.meta.support.kg_relation && (
                    <Badge size="sm" colorScheme="teal" fontSize="9px">
                      KG: {assertion.meta.support.kg_relation}
                    </Badge>
                  )}
                </HStack>
              </Box>
            )}
          </VStack>
        </PopoverBody>
      </PopoverContent>
    </Popover>
  )
}

export { AssertionPopover }
