'use client'

/**
 * OSMOS Synthesized Answer - Dark Elegance Edition
 */

import {
  Box,
  Text,
  VStack,
  Flex,
  HStack,
  Icon,
} from '@chakra-ui/react'
import { SynthesisResult, SearchChunk, ExplorationIntelligence } from '@/types/api'
import CopyButton from './CopyButton'
import { ResponseGraph } from '@/components/chat'
import type { GraphData } from '@/types/graph'
import { FiCheckCircle, FiAlertCircle, FiAlertTriangle } from 'react-icons/fi'

interface SynthesizedAnswerProps {
  synthesis: SynthesisResult
  chunks?: SearchChunk[]
  onSlideClick?: (chunk: SearchChunk) => void
  graphData?: GraphData
  explorationIntelligence?: ExplorationIntelligence
  onSearch?: (query: string) => void
}

export default function SynthesizedAnswer({
  synthesis,
  chunks,
  onSlideClick,
  graphData,
  explorationIntelligence,
  onSearch,
}: SynthesizedAnswerProps) {
  const getConfidenceConfig = (confidence: number) => {
    if (confidence >= 0.7) return {
      color: 'green.400',
      bg: 'rgba(34, 197, 94, 0.15)',
      icon: FiCheckCircle,
      label: 'Tres fiable'
    }
    if (confidence >= 0.5) return {
      color: 'yellow.400',
      bg: 'rgba(250, 204, 21, 0.15)',
      icon: FiAlertTriangle,
      label: 'Fiable'
    }
    return {
      color: 'red.400',
      bg: 'rgba(239, 68, 68, 0.15)',
      icon: FiAlertCircle,
      label: 'Peu fiable'
    }
  }

  const confidenceConfig = getConfidenceConfig(synthesis.confidence)

  // Function to render text with clickable slide references
  const renderAnswerWithClickableSlides = (text: string) => {
    if (!chunks || !onSlideClick) {
      return text
    }

    // Create a map of slide numbers to chunks for quick lookup
    const slideToChunk = new Map<string, SearchChunk>()
    chunks.forEach(chunk => {
      if (chunk.slide_index && chunk.slide_image_url) {
        slideToChunk.set(chunk.slide_index.toString(), chunk)
      }
    })

    // Split text by slide references and create clickable elements
    const slidePattern = /\b(?:slides?)\s+(\d+)(?:\s+et\s+(\d+))?(?:\s*[-,]\s*(\d+))?(?:\s+à\s+(\d+))?\b/gi
    const parts: Array<string | JSX.Element> = []
    let lastIndex = 0
    let match

    while ((match = slidePattern.exec(text)) !== null) {
      const slideNumbers = [match[1], match[2], match[3], match[4]].filter(Boolean)

      if (match.index > lastIndex) {
        parts.push(text.substring(lastIndex, match.index))
      }

      const fullMatch = match[0]
      const matchParts = []
      let currentIndex = 0

      for (const slideNumber of slideNumbers) {
        const chunk = slideToChunk.get(slideNumber)

        const slideIndex = fullMatch.indexOf(slideNumber, currentIndex)

        if (slideIndex > currentIndex) {
          matchParts.push(fullMatch.substring(currentIndex, slideIndex))
        }

        if (chunk) {
          matchParts.push(
            <Text
              key={`slide-${match.index}-${slideNumber}`}
              as="span"
              color="brand.400"
              textDecoration="underline"
              cursor="pointer"
              _hover={{ color: 'brand.300' }}
              onClick={() => onSlideClick(chunk)}
              transition="color 0.2s"
            >
              {slideNumber}
            </Text>
          )
        } else {
          matchParts.push(slideNumber)
        }

        currentIndex = slideIndex + slideNumber.length
      }

      if (currentIndex < fullMatch.length) {
        matchParts.push(fullMatch.substring(currentIndex))
      }

      parts.push(...matchParts)

      lastIndex = match.index + match[0].length
    }

    if (lastIndex < text.length) {
      parts.push(text.substring(lastIndex))
    }

    return parts.length > 0 ? parts : text
  }

  return (
    <Box w="full">
      <VStack spacing={3} align="stretch">
        {/* Synthesized answer */}
        <Box
          bg="bg.secondary"
          p={4}
          borderRadius="lg"
          border="1px solid"
          borderColor="border.default"
          position="relative"
        >
          <Text
            fontSize="sm"
            lineHeight="1.6"
            whiteSpace="pre-wrap"
            color="text.primary"
          >
            {renderAnswerWithClickableSlides(synthesis.synthesized_answer)}
          </Text>

          {/* Copy + confidence */}
          <Flex justify="space-between" align="center" mt={3} pt={3} borderTop="1px solid" borderColor="border.default">
            <HStack
              px={2}
              py={1}
              bg={confidenceConfig.bg}
              rounded="md"
              spacing={1.5}
            >
              <Icon as={confidenceConfig.icon} boxSize={3.5} color={confidenceConfig.color} />
              <Text fontSize="xs" fontWeight="medium" color={confidenceConfig.color}>
                {Math.round(synthesis.confidence * 100)}%
              </Text>
            </HStack>
            <CopyButton
              text={synthesis.synthesized_answer}
              className="copy-answer-button"
            />
          </Flex>
        </Box>

        {/* Knowledge Graph */}
        {graphData && graphData.nodes.length > 0 && (
          <ResponseGraph
            graphData={graphData}
            explorationIntelligence={explorationIntelligence}
            onSearch={onSearch}
          />
        )}
      </VStack>
    </Box>
  )
}
