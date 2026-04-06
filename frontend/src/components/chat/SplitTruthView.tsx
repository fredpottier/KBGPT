'use client'

/**
 * Split Truth View — Affiche les positions divergentes de maniere compacte.
 *
 * Declenche quand response_mode === 'TENSION'.
 * Parse la reponse markdown pour extraire Position A / Position B
 * et les affiche dans un encart compact sous la reponse principale.
 */

import { Box, HStack, VStack, Text, Icon, SimpleGrid, Badge, Collapse, useDisclosure } from '@chakra-ui/react'
import { FiAlertTriangle, FiChevronDown, FiChevronUp } from 'react-icons/fi'
import ReactMarkdown from 'react-markdown'

interface SplitTruthViewProps {
  answer: string
}

function parseTensionAnswer(markdown: string): {
  mainAnswer: string
  positionA: string
  positionB: string
} {
  const result = { mainAnswer: '', positionA: '', positionB: '' }

  // Trouver Position A et Position B
  const posAMatch = markdown.match(/^#{1,3}\s*(?:\d+\.\s*)?position\s*a\b/im)
  const posBMatch = markdown.match(/^#{1,3}\s*(?:\d+\.\s*)?position\s*b\b/im)

  if (posAMatch && posAMatch.index !== undefined) {
    // Tout avant Position A = reponse principale
    result.mainAnswer = markdown.substring(0, posAMatch.index).trim()

    if (posBMatch && posBMatch.index !== undefined) {
      // Entre Position A et Position B
      const afterA = markdown.substring(posAMatch.index)
      const aLines = afterA.split('\n')
      result.positionA = aLines.slice(1, afterA.indexOf(posBMatch[0]) > 0 ? undefined : undefined)
        .join('\n').trim()

      // Extraire Position A proprement
      const aContent = markdown.substring(posAMatch.index, posBMatch.index)
      const aLines2 = aContent.split('\n')
      result.positionA = aLines2.slice(1).join('\n').trim()

      // Position B = tout apres le header B, jusqu'a la prochaine section majeure ou fin
      const afterB = markdown.substring(posBMatch.index)
      const bLines = afterB.split('\n')
      // Chercher la fin de Position B (prochaine section ## ou fin)
      let endIdx = bLines.length
      for (let i = 1; i < bLines.length; i++) {
        if (/^#{1,3}\s*(?:\d+\.\s*)?(?!position)/i.test(bLines[i])) {
          endIdx = i
          break
        }
      }
      result.positionB = bLines.slice(1, endIdx).join('\n').trim()
    }
  } else {
    // Pas de structure Position A/B detectee
    result.mainAnswer = markdown
  }

  // Nettoyer la reponse principale (retirer les headers de synthese/titre)
  result.mainAnswer = result.mainAnswer
    .replace(/^#.*\n/gm, '')  // retirer les headers
    .replace(/^---+\n/gm, '') // retirer les separateurs
    .trim()

  return result
}

export default function SplitTruthView({ answer }: SplitTruthViewProps) {
  const { isOpen, onToggle } = useDisclosure({ defaultIsOpen: true })
  const sections = parseTensionAnswer(answer)
  const hasPositions = sections.positionA.length > 20 || sections.positionB.length > 20

  if (!hasPositions) {
    return null
  }

  return (
    <VStack spacing={3} align="stretch" w="full">
      {/* Reponse principale */}
      {sections.mainAnswer && (
        <Box fontSize="sm" color="text.primary" lineHeight="tall" sx={{
          'p': { mb: 2 },
          'ul, ol': { pl: 4, mb: 2 },
          'li': { mb: 1 },
          'strong': { fontWeight: 600 },
        }}>
          <ReactMarkdown>{sections.mainAnswer}</ReactMarkdown>
        </Box>
      )}

      {/* Encart divergence compact */}
      <Box
        borderRadius="lg"
        border="1px solid"
        borderColor="rgba(251, 146, 60, 0.2)"
        overflow="hidden"
      >
        {/* Header cliquable */}
        <HStack
          spacing={2}
          px={3}
          py={2}
          bg="rgba(251, 146, 60, 0.06)"
          cursor="pointer"
          onClick={onToggle}
          _hover={{ bg: 'rgba(251, 146, 60, 0.10)' }}
          justify="space-between"
        >
          <HStack spacing={2}>
            <Icon as={FiAlertTriangle} color="orange.400" boxSize={3.5} />
            <Text fontSize="xs" fontWeight="600" color="orange.400">
              Divergence documentaire
            </Text>
          </HStack>
          <Icon as={isOpen ? FiChevronUp : FiChevronDown} color="orange.400" boxSize={3.5} />
        </HStack>

        {/* Contenu repliable */}
        <Collapse in={isOpen} animateOpacity>
          <SimpleGrid columns={{ base: 1, md: 2 }} spacing={0}>
            {/* Position A */}
            <Box
              p={3}
              borderRight={{ md: '1px solid' }}
              borderColor={{ md: 'rgba(156, 163, 175, 0.1)' }}
              borderBottom={{ base: '1px solid', md: 'none' }}
              borderBottomColor={{ base: 'rgba(156, 163, 175, 0.1)' }}
            >
              <Badge colorScheme="blue" fontSize="2xs" mb={2} px={1.5} py={0.5} borderRadius="sm">
                Position A
              </Badge>
              <Box fontSize="xs" color="text.secondary" lineHeight="tall" sx={{
                'p': { mb: 1 },
                'em': { fontSize: '2xs', opacity: 0.7 },
              }}>
                <ReactMarkdown>{sections.positionA}</ReactMarkdown>
              </Box>
            </Box>

            {/* Position B */}
            <Box p={3}>
              <Badge colorScheme="orange" fontSize="2xs" mb={2} px={1.5} py={0.5} borderRadius="sm">
                Position B
              </Badge>
              <Box fontSize="xs" color="text.secondary" lineHeight="tall" sx={{
                'p': { mb: 1 },
                'em': { fontSize: '2xs', opacity: 0.7 },
              }}>
                <ReactMarkdown>{sections.positionB}</ReactMarkdown>
              </Box>
            </Box>
          </SimpleGrid>
        </Collapse>
      </Box>
    </VStack>
  )
}
