'use client'

/**
 * TensionIndicator — Pictogramme eclair + popup explicative.
 *
 * Petit eclair orange a cote du bouton copie.
 * Au clic, popup qui EXPLIQUE les tensions de maniere comprehensible.
 */

import {
  Box,
  HStack,
  VStack,
  Text,
  Icon,
  IconButton,
  Modal,
  ModalOverlay,
  ModalContent,
  ModalHeader,
  ModalBody,
  ModalCloseButton,
  useDisclosure,
  Badge,
  Tooltip,
} from '@chakra-ui/react'
import { FiZap } from 'react-icons/fi'

interface TensionPair {
  claim_a: string
  claim_b: string
  doc_a: string
  doc_b: string
  axis: string
}

interface TensionIndicatorProps {
  pairs: TensionPair[]
  pairsCount: number
}

const AXIS_CONFIG: Record<string, { label: string; color: string; verb: string }> = {
  contradiction: { label: 'Contradiction', color: 'red', verb: 'contredit' },
  refinement: { label: 'Precision', color: 'yellow', verb: 'precise' },
  qualification: { label: 'Nuance', color: 'blue', verb: 'nuance' },
  tension: { label: 'Divergence', color: 'orange', verb: 'diverge de' },
}

/** Genere une explication humaine courte pour une paire de tension */
function explainTension(pair: TensionPair): string {
  const config = AXIS_CONFIG[pair.axis] || AXIS_CONFIG.tension
  const docA = pair.doc_a || 'Un document'
  const docB = pair.doc_b || 'un autre document'

  // Extraire les 60 premiers chars significatifs de chaque claim
  const shortA = pair.claim_a.length > 80 ? pair.claim_a.substring(0, 77) + '...' : pair.claim_a
  const shortB = pair.claim_b.length > 80 ? pair.claim_b.substring(0, 77) + '...' : pair.claim_b

  return `**${docA}** ${config.verb} **${docB}**`
}

export default function TensionIndicator({ pairs, pairsCount }: TensionIndicatorProps) {
  const { isOpen, onOpen, onClose } = useDisclosure()

  if (!pairs || pairs.length === 0) return null

  return (
    <>
      <Tooltip
        label={`${pairsCount} divergence${pairsCount > 1 ? 's' : ''} detectee${pairsCount > 1 ? 's' : ''}`}
        placement="top"
        fontSize="xs"
      >
        <IconButton
          aria-label="Voir les tensions"
          icon={<FiZap size={14} />}
          size="xs"
          variant="ghost"
          color="orange.400"
          _hover={{ bg: 'rgba(251, 146, 60, 0.15)', color: 'orange.300' }}
          onClick={onOpen}
        />
      </Tooltip>

      <Modal isOpen={isOpen} onClose={onClose} size="lg" isCentered>
        <ModalOverlay bg="blackAlpha.700" />
        <ModalContent bg="bg.primary" border="1px solid" borderColor="border.default" borderRadius="xl" mx={4}>
          <ModalHeader pb={1}>
            <HStack spacing={2}>
              <Icon as={FiZap} color="orange.400" boxSize={4} />
              <Text fontSize="sm" fontWeight="700" color="text.primary">
                Divergences detectees
              </Text>
              <Badge colorScheme="orange" fontSize="2xs" borderRadius="full">{pairsCount}</Badge>
            </HStack>
            <Text fontSize="xs" color="text.muted" mt={1}>
              La reponse tient compte de ces divergences entre documents.
            </Text>
          </ModalHeader>
          <ModalCloseButton color="text.muted" size="sm" />
          <ModalBody pb={5} pt={2}>
            <VStack spacing={3} align="stretch">
              {pairs.map((pair, idx) => {
                const config = AXIS_CONFIG[pair.axis] || AXIS_CONFIG.tension
                const docA = pair.doc_a || 'Document A'
                const docB = pair.doc_b || 'Document B'

                return (
                  <Box
                    key={idx}
                    p={3}
                    bg="bg.secondary"
                    borderRadius="lg"
                    border="1px solid"
                    borderColor="border.default"
                    fontSize="xs"
                  >
                    {/* Type de divergence */}
                    <Badge colorScheme={config.color} fontSize="2xs" borderRadius="sm" mb={2}>
                      {config.label}
                    </Badge>

                    {/* Explication en deux blocs empiles */}
                    <VStack spacing={2} align="stretch">
                      <Box
                        pl={3}
                        borderLeft="2px solid"
                        borderColor="blue.400"
                      >
                        <Text fontSize="2xs" fontWeight="600" color="blue.300" mb={0.5}>
                          {docA}
                        </Text>
                        <Text color="text.secondary" lineHeight="tall">
                          {pair.claim_a.length > 150 ? pair.claim_a.substring(0, 147) + '...' : pair.claim_a}
                        </Text>
                      </Box>

                      <Box
                        pl={3}
                        borderLeft="2px solid"
                        borderColor="orange.400"
                      >
                        <Text fontSize="2xs" fontWeight="600" color="orange.300" mb={0.5}>
                          {docB}
                        </Text>
                        <Text color="text.secondary" lineHeight="tall">
                          {pair.claim_b.length > 150 ? pair.claim_b.substring(0, 147) + '...' : pair.claim_b}
                        </Text>
                      </Box>
                    </VStack>
                  </Box>
                )
              })}
            </VStack>
          </ModalBody>
        </ModalContent>
      </Modal>
    </>
  )
}
