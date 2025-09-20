'use client'

import {
  Box,
  Text,
  VStack,
  Badge,
  Divider,
  Flex,
} from '@chakra-ui/react'
import { SynthesisResult } from '@/types/api'
import CopyButton from './CopyButton'

interface SynthesizedAnswerProps {
  synthesis: SynthesisResult
}

export default function SynthesizedAnswer({ synthesis }: SynthesizedAnswerProps) {
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

  return (
    <Box w="full">
      <VStack spacing={4} align="stretch">
        {/* Header with confidence indicator */}
        <Box>
          <Text fontSize="lg" fontWeight="semibold" mb={2} color="gray.700">
            🤖 Réponse générée
          </Text>
          <Badge
            colorScheme={getConfidenceColor(synthesis.confidence)}
            variant="subtle"
            fontSize="xs"
          >
            {getConfidenceLabel(synthesis.confidence)} ({Math.round(synthesis.confidence * 100)}%)
          </Badge>
        </Box>

        <Divider />

        {/* Synthesized answer */}
        <Box
          bg="gray.50"
          p={6}
          borderRadius="lg"
          border="1px solid"
          borderColor="gray.200"
          position="relative"
        >
          <Text
            fontSize="md"
            lineHeight="1.6"
            whiteSpace="pre-wrap"
            color="gray.800"
            mb={4}
          >
            {synthesis.synthesized_answer}
          </Text>

          {/* Copy button positioned at bottom right of the answer */}
          <Flex justify="flex-end" mt={3}>
            <CopyButton
              text={synthesis.synthesized_answer}
              className="copy-answer-button"
            />
          </Flex>
        </Box>
      </VStack>
    </Box>
  )
}