'use client'

import {
  Box,
  Text,
  VStack,
  Badge,
  Divider,
  Flex,
} from '@chakra-ui/react'
import { SynthesisResult, SearchChunk, ExplorationIntelligence } from '@/types/api'
import CopyButton from './CopyButton'
import { ResponseGraph } from '@/components/chat'
import type { GraphData } from '@/types/graph'

interface SynthesizedAnswerProps {
  synthesis: SynthesisResult
  chunks?: SearchChunk[]
  onSlideClick?: (chunk: SearchChunk) => void
  graphData?: GraphData
  explorationIntelligence?: ExplorationIntelligence
  onSearch?: (query: string) => void
}

export default function SynthesizedAnswer({ synthesis, chunks, onSlideClick, graphData, explorationIntelligence, onSearch }: SynthesizedAnswerProps) {
  const getConfidenceColor = (confidence: number) => {
    if (confidence >= 0.7) return 'green'
    if (confidence >= 0.5) return 'yellow'
    return 'red'
  }

  const getConfidenceLabel = (confidence: number) => {
    if (confidence >= 0.7) return 'Très fiable'
    if (confidence >= 0.5) return 'Fiable'
    return 'Peu fiable'
  }

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
    // Pattern étendu pour gérer: "slide 78", "slides 78", "slides 78 et 79", etc.
    const slidePattern = /\b(?:slides?)\s+(\d+)(?:\s+et\s+(\d+))?(?:\s*[-,]\s*(\d+))?(?:\s+à\s+(\d+))?\b/gi
    const parts: Array<string | JSX.Element> = []
    let lastIndex = 0
    let match

    while ((match = slidePattern.exec(text)) !== null) {
      // Extract all slide numbers from the match
      const slideNumbers = [match[1], match[2], match[3], match[4]].filter(Boolean)

      // Add text before the match
      if (match.index > lastIndex) {
        parts.push(text.substring(lastIndex, match.index))
      }

      // Process the entire match to create clickable parts
      const fullMatch = match[0]
      const matchParts = []
      let currentIndex = 0

      // For each slide number, make it clickable if chunk exists
      for (const slideNumber of slideNumbers) {
        const chunk = slideToChunk.get(slideNumber)
        const slideText = `slide ${slideNumber}`

        // Find where this slide number appears in the full match
        const slideIndex = fullMatch.indexOf(slideNumber, currentIndex)

        // Add text before the slide number
        if (slideIndex > currentIndex) {
          matchParts.push(fullMatch.substring(currentIndex, slideIndex))
        }

        // Add clickable slide number
        if (chunk) {
          matchParts.push(
            <Text
              key={`slide-${match.index}-${slideNumber}`}
              as="span"
              color="blue.600"
              textDecoration="underline"
              cursor="pointer"
              _hover={{ color: "blue.800", textDecoration: "underline" }}
              onClick={() => onSlideClick(chunk)}
            >
              {slideNumber}
            </Text>
          )
        } else {
          matchParts.push(slideNumber)
        }

        currentIndex = slideIndex + slideNumber.length
      }

      // Add remaining text from the match
      if (currentIndex < fullMatch.length) {
        matchParts.push(fullMatch.substring(currentIndex))
      }

      // Add all parts of this match
      parts.push(...matchParts)

      lastIndex = match.index + match[0].length
    }

    // Add remaining text
    if (lastIndex < text.length) {
      parts.push(text.substring(lastIndex))
    }

    return parts.length > 0 ? parts : text
  }

  return (
    <Box w="full">
      <VStack spacing={2} align="stretch">
        {/* Synthesized answer - ultra compact, pas de header */}
        <Box
          bg="gray.50"
          p={2}
          borderRadius="sm"
          border="1px solid"
          borderColor="gray.200"
          position="relative"
        >
          <Text
            fontSize="xs"
            lineHeight="1.4"
            whiteSpace="pre-wrap"
            color="gray.700"
          >
            {renderAnswerWithClickableSlides(synthesis.synthesized_answer)}
          </Text>

          {/* Copy + confidence inline */}
          <Flex justify="space-between" align="center" mt={1.5}>
            <Badge
              colorScheme={getConfidenceColor(synthesis.confidence)}
              variant="subtle"
              fontSize="2xs"
            >
              {Math.round(synthesis.confidence * 100)}%
            </Badge>
            <CopyButton
              text={synthesis.synthesized_answer}
              className="copy-answer-button"
            />
          </Flex>
        </Box>

        {/* Knowledge Graph - APRÈS la réponse */}
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