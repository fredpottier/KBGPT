'use client'

/**
 * OSMOS Synthesized Answer - Dark Elegance Edition
 * Avec rendu Markdown pour une mise en page enrichie
 */

import {
  Box,
  Text,
  VStack,
  Flex,
  HStack,
  Icon,
  Heading,
  UnorderedList,
  OrderedList,
  ListItem,
  Code,
  Link,
} from '@chakra-ui/react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Components } from 'react-markdown'
import { SynthesisResult, SearchChunk, ExplorationIntelligence } from '@/types/api'
import CopyButton from './CopyButton'
import { ResponseGraph } from '@/components/chat'
import type { GraphData, ProofGraph } from '@/types/graph'
import { FiCheckCircle, FiAlertCircle, FiAlertTriangle } from 'react-icons/fi'

interface SynthesizedAnswerProps {
  synthesis: SynthesisResult
  chunks?: SearchChunk[]
  onSlideClick?: (chunk: SearchChunk) => void
  graphData?: GraphData
  proofGraph?: ProofGraph  // 🌊 Phase 3.5+: Proof Graph prioritaire
  explorationIntelligence?: ExplorationIntelligence
  onSearch?: (query: string) => void
}

// Composants Chakra UI personnalisés pour le rendu Markdown
const createMarkdownComponents = (
  chunks?: SearchChunk[],
  onSlideClick?: (chunk: SearchChunk) => void
): Components => {
  // Map des numéros de slides vers les chunks
  const slideToChunk = new Map<string, SearchChunk>()
  if (chunks) {
    chunks.forEach(chunk => {
      if (chunk.slide_index && chunk.slide_image_url) {
        slideToChunk.set(chunk.slide_index.toString(), chunk)
      }
    })
  }

  // Fonction pour rendre le texte avec slides cliquables
  const renderTextWithSlides = (text: string): React.ReactNode => {
    if (!chunks || !onSlideClick || slideToChunk.size === 0) {
      return text
    }

    const slidePattern = /\b(?:slides?)\s+(\d+)(?:\s+et\s+(\d+))?(?:\s*[-,]\s*(\d+))?(?:\s+à\s+(\d+))?\b/gi
    const parts: React.ReactNode[] = []
    let lastIndex = 0
    let match
    let keyCounter = 0

    while ((match = slidePattern.exec(text)) !== null) {
      if (match.index > lastIndex) {
        parts.push(text.substring(lastIndex, match.index))
      }

      const slideNumbers = [match[1], match[2], match[3], match[4]].filter(Boolean)
      const fullMatch = match[0]
      let currentIndex = 0

      for (const slideNumber of slideNumbers) {
        const slideIndex = fullMatch.indexOf(slideNumber, currentIndex)
        if (slideIndex > currentIndex) {
          parts.push(fullMatch.substring(currentIndex, slideIndex))
        }

        const chunk = slideToChunk.get(slideNumber)
        if (chunk) {
          parts.push(
            <Text
              key={`slide-${keyCounter++}`}
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
          parts.push(slideNumber)
        }
        currentIndex = slideIndex + slideNumber.length
      }

      if (currentIndex < fullMatch.length) {
        parts.push(fullMatch.substring(currentIndex))
      }
      lastIndex = match.index + fullMatch.length
    }

    if (lastIndex < text.length) {
      parts.push(text.substring(lastIndex))
    }

    return parts.length > 0 ? <>{parts}</> : text
  }

  // Traiter les children pour les slides cliquables
  const processChildren = (children: React.ReactNode): React.ReactNode => {
    if (typeof children === 'string') {
      return renderTextWithSlides(children)
    }
    if (Array.isArray(children)) {
      return children.map((child, i) =>
        typeof child === 'string' ? <span key={i}>{renderTextWithSlides(child)}</span> : child
      )
    }
    return children
  }

  return {
    // Titres
    h1: ({ children }) => (
      <Heading as="h1" size="lg" mt={4} mb={2} color="text.primary">
        {children}
      </Heading>
    ),
    h2: ({ children }) => (
      <Heading as="h2" size="md" mt={3} mb={2} color="text.primary">
        {children}
      </Heading>
    ),
    h3: ({ children }) => (
      <Heading as="h3" size="sm" mt={3} mb={1} color="text.primary" fontWeight="semibold">
        {children}
      </Heading>
    ),
    h4: ({ children }) => (
      <Heading as="h4" size="xs" mt={2} mb={1} color="text.primary" fontWeight="semibold">
        {children}
      </Heading>
    ),
    // Paragraphes
    p: ({ children }) => (
      <Text fontSize="sm" lineHeight="1.7" color="text.primary" mb={2}>
        {processChildren(children)}
      </Text>
    ),
    // Listes
    ul: ({ children }) => (
      <UnorderedList spacing={1} pl={4} mb={2} color="text.primary">
        {children}
      </UnorderedList>
    ),
    ol: ({ children }) => (
      <OrderedList spacing={1} pl={4} mb={2} color="text.primary">
        {children}
      </OrderedList>
    ),
    li: ({ children }) => (
      <ListItem fontSize="sm" lineHeight="1.6">
        {processChildren(children)}
      </ListItem>
    ),
    // Texte enrichi
    strong: ({ children }) => (
      <Text as="span" fontWeight="bold" color="text.primary">
        {children}
      </Text>
    ),
    em: ({ children }) => (
      <Text as="span" fontStyle="italic" color="text.secondary">
        {children}
      </Text>
    ),
    // Code
    code: ({ children }) => (
      <Code
        fontSize="xs"
        px={1}
        py={0.5}
        bg="bg.tertiary"
        color="brand.300"
        borderRadius="sm"
      >
        {children}
      </Code>
    ),
    pre: ({ children }) => (
      <Box
        as="pre"
        bg="bg.tertiary"
        p={3}
        borderRadius="md"
        overflowX="auto"
        fontSize="xs"
        mb={2}
      >
        {children}
      </Box>
    ),
    // Liens
    a: ({ href, children }) => (
      <Link
        href={href}
        color="brand.400"
        textDecoration="underline"
        _hover={{ color: 'brand.300' }}
        isExternal
      >
        {children}
      </Link>
    ),
    // Blockquote
    blockquote: ({ children }) => (
      <Box
        borderLeftWidth="3px"
        borderLeftColor="brand.500"
        pl={3}
        py={1}
        my={2}
        bg="bg.tertiary"
        borderRadius="sm"
        fontStyle="italic"
        color="text.secondary"
      >
        {children}
      </Box>
    ),
    // Séparateur horizontal
    hr: () => (
      <Box
        as="hr"
        borderColor="border.default"
        my={3}
      />
    ),
  }
}

export default function SynthesizedAnswer({
  synthesis,
  chunks,
  onSlideClick,
  graphData,
  proofGraph,
  explorationIntelligence,
  onSearch,
}: SynthesizedAnswerProps) {
  // Créer les composants Markdown avec le contexte des slides
  const markdownComponents = createMarkdownComponents(chunks, onSlideClick)

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
          <Box className="markdown-answer">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={markdownComponents}
            >
              {synthesis.synthesized_answer}
            </ReactMarkdown>
          </Box>

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

        {/* Knowledge Graph (ProofGraph prioritaire si disponible) */}
        {(graphData && graphData.nodes.length > 0) || (proofGraph && proofGraph.nodes.length > 0) ? (
          <ResponseGraph
            graphData={graphData || { nodes: [], edges: [], queryConceptIds: [], usedConceptIds: [], suggestedConceptIds: [] }}
            proofGraph={proofGraph}
            explorationIntelligence={explorationIntelligence}
            onSearch={onSearch}
          />
        ) : null}
      </VStack>
    </Box>
  )
}
