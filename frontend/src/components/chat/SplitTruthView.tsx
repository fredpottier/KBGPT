'use client'

/**
 * Split Truth View — Affiche les positions divergentes cote a cote.
 *
 * Declenche quand response_mode === 'TENSION'.
 * Parse la reponse markdown structuree (Position A / Position B)
 * et l'affiche en deux colonnes avec badge de divergence.
 */

import { Box, HStack, VStack, Text, Icon, SimpleGrid, Badge } from '@chakra-ui/react'
import { FiAlertTriangle } from 'react-icons/fi'
import ReactMarkdown from 'react-markdown'

interface SplitTruthViewProps {
  /** La reponse complete en markdown (contient ## Position A, ## Position B, etc.) */
  answer: string
}

/** Extrait les sections d'une reponse markdown structuree TENSION */
function parseTensionAnswer(markdown: string): {
  synthesis: string
  positionA: string
  positionB: string
  analysis: string
  conclusion: string
} {
  const sections = {
    synthesis: '',
    positionA: '',
    positionB: '',
    analysis: '',
    conclusion: '',
  }

  // Patterns pour detecter les sections (FR et EN, flexible)
  const patterns = [
    { key: 'synthesis' as const, regex: /^#{1,3}\s*(?:\d+\.\s*)?(?:synth[eè]se|summary)/im },
    { key: 'positionA' as const, regex: /^#{1,3}\s*(?:\d+\.\s*)?position\s*a/im },
    { key: 'positionB' as const, regex: /^#{1,3}\s*(?:\d+\.\s*)?position\s*b/im },
    { key: 'analysis' as const, regex: /^#{1,3}\s*(?:\d+\.\s*)?(?:analyse|analysis|divergence|ce qui)/im },
    { key: 'conclusion' as const, regex: /^#{1,3}\s*(?:\d+\.\s*)?(?:conclusion|recommandation)/im },
  ]

  // Trouver les positions de chaque section
  const positions: { key: keyof typeof sections; start: number }[] = []
  for (const { key, regex } of patterns) {
    const match = markdown.match(regex)
    if (match && match.index !== undefined) {
      positions.push({ key, start: match.index })
    }
  }

  // Trier par position dans le texte
  positions.sort((a, b) => a.start - b.start)

  // Extraire le contenu de chaque section
  for (let i = 0; i < positions.length; i++) {
    const current = positions[i]
    const nextStart = i + 1 < positions.length ? positions[i + 1].start : markdown.length
    const content = markdown.substring(current.start, nextStart).trim()
    // Retirer le header de la section
    const lines = content.split('\n')
    sections[current.key] = lines.slice(1).join('\n').trim()
  }

  // Si pas de sections detectees, mettre tout dans synthesis
  if (positions.length === 0) {
    sections.synthesis = markdown
  }

  return sections
}

export default function SplitTruthView({ answer }: SplitTruthViewProps) {
  const sections = parseTensionAnswer(answer)
  const hasPositions = sections.positionA.length > 0 || sections.positionB.length > 0

  if (!hasPositions) {
    // Pas de structure Position A/B detectee — fallback markdown classique
    return null
  }

  return (
    <VStack spacing={4} align="stretch" w="full">
      {/* Badge divergence */}
      <HStack
        spacing={2}
        px={3}
        py={2}
        bg="rgba(251, 146, 60, 0.08)"
        borderRadius="md"
        border="1px solid"
        borderColor="rgba(251, 146, 60, 0.2)"
      >
        <Icon as={FiAlertTriangle} color="orange.400" boxSize={4} />
        <Text fontSize="xs" fontWeight="600" color="orange.400" textTransform="uppercase" letterSpacing="wider">
          Divergence documentaire detectee
        </Text>
      </HStack>

      {/* Synthese (si presente) */}
      {sections.synthesis && (
        <Box px={1}>
          <Text fontSize="sm" color="text.secondary" lineHeight="tall">
            <ReactMarkdown>{sections.synthesis}</ReactMarkdown>
          </Text>
        </Box>
      )}

      {/* Positions cote a cote */}
      <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
        {/* Position A */}
        <Box
          p={4}
          bg="rgba(96, 165, 250, 0.06)"
          borderRadius="lg"
          border="1px solid"
          borderColor="rgba(96, 165, 250, 0.15)"
        >
          <HStack spacing={2} mb={3}>
            <Badge
              colorScheme="blue"
              fontSize="2xs"
              fontWeight="700"
              px={2}
              py={0.5}
              borderRadius="sm"
            >
              Position A
            </Badge>
          </HStack>
          <Box fontSize="sm" color="text.primary" lineHeight="tall" sx={{
            'p': { mb: 2 },
            'strong': { color: 'blue.300' },
            'blockquote': { borderLeft: '2px solid', borderColor: 'blue.500', pl: 3, ml: 0, opacity: 0.9 },
          }}>
            <ReactMarkdown>{sections.positionA}</ReactMarkdown>
          </Box>
        </Box>

        {/* Position B */}
        <Box
          p={4}
          bg="rgba(251, 146, 60, 0.06)"
          borderRadius="lg"
          border="1px solid"
          borderColor="rgba(251, 146, 60, 0.15)"
        >
          <HStack spacing={2} mb={3}>
            <Badge
              colorScheme="orange"
              fontSize="2xs"
              fontWeight="700"
              px={2}
              py={0.5}
              borderRadius="sm"
            >
              Position B
            </Badge>
          </HStack>
          <Box fontSize="sm" color="text.primary" lineHeight="tall" sx={{
            'p': { mb: 2 },
            'strong': { color: 'orange.300' },
            'blockquote': { borderLeft: '2px solid', borderColor: 'orange.500', pl: 3, ml: 0, opacity: 0.9 },
          }}>
            <ReactMarkdown>{sections.positionB}</ReactMarkdown>
          </Box>
        </Box>
      </SimpleGrid>

      {/* Analyse (si presente) */}
      {sections.analysis && (
        <Box
          p={3}
          bg="rgba(156, 163, 175, 0.06)"
          borderRadius="md"
          border="1px solid"
          borderColor="rgba(156, 163, 175, 0.12)"
        >
          <Text fontSize="xs" fontWeight="600" color="text.muted" mb={2} textTransform="uppercase" letterSpacing="wider">
            Analyse
          </Text>
          <Box fontSize="sm" color="text.secondary" lineHeight="tall" sx={{ 'p': { mb: 1 } }}>
            <ReactMarkdown>{sections.analysis}</ReactMarkdown>
          </Box>
        </Box>
      )}

      {/* Conclusion (si presente) */}
      {sections.conclusion && (
        <Box px={1}>
          <Text fontSize="xs" fontWeight="600" color="text.muted" mb={1} textTransform="uppercase" letterSpacing="wider">
            Conclusion
          </Text>
          <Box fontSize="sm" color="text.secondary" lineHeight="tall" sx={{ 'p': { mb: 1 } }}>
            <ReactMarkdown>{sections.conclusion}</ReactMarkdown>
          </Box>
        </Box>
      )}
    </VStack>
  )
}
