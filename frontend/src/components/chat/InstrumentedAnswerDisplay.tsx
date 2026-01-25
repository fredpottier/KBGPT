'use client'

/**
 * Affichage complet d'une reponse instrumentee - OSMOSE Assertion-Centric.
 *
 * Mode simplifie (2026-01):
 * - InstrumentedToggle pour switcher entre mode simple et instrumented
 * - TruthContractBadge pour le resume de verite
 * - AssertionRenderer pour chaque assertion (coloration texte uniquement)
 * - Open Points visibles en mode instrumented
 *
 * Supprime: ProofTicketList (trop verbeux)
 */

import { useState, useCallback } from 'react'
import {
  Box,
  VStack,
  Flex,
  Divider,
  Text,
  Collapse,
} from '@chakra-ui/react'
import type { InstrumentedAnswer, InstrumentationMode, SearchChunk } from '@/types'
import InstrumentedToggle from './InstrumentedToggle'
import TruthContractBadge from './TruthContractBadge'
import AssertionRenderer from './AssertionRenderer'
import CopyButton from '@/components/ui/CopyButton'

interface InstrumentedAnswerDisplayProps {
  answer: InstrumentedAnswer
  chunks?: SearchChunk[]
  onSlideClick?: (chunk: SearchChunk) => void
  onSourceClick?: (sourceId: string) => void
}

export default function InstrumentedAnswerDisplay({
  answer,
  chunks,
  onSlideClick,
  onSourceClick,
}: InstrumentedAnswerDisplayProps) {
  const [mode, setMode] = useState<InstrumentationMode>('simple')
  const [isTransitioning, setIsTransitioning] = useState(false)

  // Handler pour le source click - trouve le chunk correspondant
  const handleSourceClick = useCallback((sourceId: string) => {
    if (onSourceClick) {
      onSourceClick(sourceId)
      return
    }

    // Fallback: trouver le chunk correspondant par index
    if (chunks && onSlideClick) {
      // sourceId est de la forme S1, S2, etc.
      const index = parseInt(sourceId.replace('S', ''), 10) - 1
      if (index >= 0 && index < chunks.length) {
        onSlideClick(chunks[index])
      }
    }
  }, [chunks, onSlideClick, onSourceClick])

  // Handler pour le changement de mode avec animation
  const handleModeChange = useCallback((newMode: InstrumentationMode) => {
    setIsTransitioning(true)
    setTimeout(() => {
      setMode(newMode)
      setIsTransitioning(false)
    }, 150)
  }, [])

  // Generer le texte complet pour la copie
  const getFullText = useCallback(() => {
    return answer.assertions.map(a => a.text_md).join('\n\n')
  }, [answer])

  const isInstrumented = mode === 'instrumented'

  return (
    <Box w="full">
      <VStack spacing={4} align="stretch">
        {/* Header avec toggle et truth contract */}
        <Box
          bg="bg.secondary"
          p={4}
          borderRadius="lg"
          border="1px solid"
          borderColor="border.default"
          transition="all 0.3s"
          opacity={isTransitioning ? 0.7 : 1}
        >
          {/* Toggle et actions */}
          <Flex justify="space-between" align="center" mb={3}>
            <InstrumentedToggle
              onModeChange={handleModeChange}
              initialMode={mode}
              size="sm"
            />
            <CopyButton text={getFullText()} />
          </Flex>

          {/* Truth Contract */}
          <Box mb={4}>
            <TruthContractBadge
              contract={answer.truth_contract}
              mode={mode}
            />
          </Box>

          <Divider my={3} />

          {/* Assertions */}
          <Box
            className="assertions-container"
            transition="all 0.3s ease-in-out"
          >
            {answer.assertions.map((assertion) => (
              <AssertionRenderer
                key={assertion.id}
                assertion={assertion}
                sources={answer.sources}
                mode={mode}
                onSourceClick={handleSourceClick}
              />
            ))}
          </Box>

          {/* Open Points */}
          {answer.open_points.length > 0 && (
            <Collapse in={isInstrumented} animateOpacity>
              <Box mt={4} pt={3} borderTop="1px solid" borderColor="border.default">
                <Text fontSize="xs" fontWeight="semibold" color="orange.500" mb={2}>
                  Points non resolus ({answer.open_points.length})
                </Text>
                <VStack spacing={1} align="stretch">
                  {answer.open_points.map((point) => (
                    <Text
                      key={point.id}
                      fontSize="xs"
                      color="text.secondary"
                      pl={3}
                      borderLeft="2px solid"
                      borderLeftColor="orange.400"
                    >
                      {point.description}
                    </Text>
                  ))}
                </VStack>
              </Box>
            </Collapse>
          )}
        </Box>

      </VStack>
    </Box>
  )
}

export { InstrumentedAnswerDisplay }
