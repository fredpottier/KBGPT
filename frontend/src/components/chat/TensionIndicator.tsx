'use client'

/**
 * TensionIndicator — Pictogramme eclair + popup de tensions documentaires.
 *
 * Affiche un petit eclair orange en bas a droite du bloc reponse
 * quand contradiction_envelope.has_tension = true.
 * Au clic, ouvre une popup avec les paires de tension.
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
  Divider,
} from '@chakra-ui/react'
import { FiZap, FiArrowRight } from 'react-icons/fi'

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

const AXIS_CONFIG: Record<string, { label: string; color: string }> = {
  contradiction: { label: 'Contradiction', color: 'red' },
  refinement: { label: 'Precision', color: 'yellow' },
  qualification: { label: 'Nuance', color: 'blue' },
  tension: { label: 'Tension', color: 'orange' },
}

export default function TensionIndicator({ pairs, pairsCount }: TensionIndicatorProps) {
  const { isOpen, onOpen, onClose } = useDisclosure()

  if (!pairs || pairs.length === 0) return null

  return (
    <>
      {/* Pictogramme eclair */}
      <Tooltip label={`${pairsCount} divergence${pairsCount > 1 ? 's' : ''} documentaire${pairsCount > 1 ? 's' : ''} detectee${pairsCount > 1 ? 's' : ''}`} placement="top">
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

      {/* Modal de details */}
      <Modal isOpen={isOpen} onClose={onClose} size="lg" isCentered>
        <ModalOverlay bg="blackAlpha.700" />
        <ModalContent bg="bg.primary" border="1px solid" borderColor="border.default" borderRadius="xl">
          <ModalHeader pb={2}>
            <HStack spacing={2}>
              <Icon as={FiZap} color="orange.400" boxSize={5} />
              <Text fontSize="md" fontWeight="700" color="text.primary">
                Divergences documentaires
              </Text>
              <Badge colorScheme="orange" fontSize="2xs" borderRadius="full">
                {pairsCount}
              </Badge>
            </HStack>
            <Text fontSize="xs" color="text.muted" mt={1}>
              Ces divergences ont ete detectees entre les documents du corpus et ont influence la reponse.
            </Text>
          </ModalHeader>
          <ModalCloseButton color="text.muted" />
          <ModalBody pb={6}>
            <VStack spacing={4} align="stretch">
              {pairs.map((pair, idx) => {
                const config = AXIS_CONFIG[pair.axis] || AXIS_CONFIG.tension
                return (
                  <Box
                    key={idx}
                    p={3}
                    bg="bg.secondary"
                    borderRadius="lg"
                    border="1px solid"
                    borderColor="border.default"
                  >
                    <HStack spacing={2} mb={2}>
                      <Badge colorScheme={config.color} fontSize="2xs" borderRadius="sm">
                        {config.label}
                      </Badge>
                    </HStack>

                    <HStack spacing={3} align="start">
                      {/* Claim A */}
                      <Box flex={1}>
                        <Text fontSize="2xs" fontWeight="600" color="blue.300" mb={1}>
                          {pair.doc_a || 'Document A'}
                        </Text>
                        <Text fontSize="xs" color="text.secondary" lineHeight="tall">
                          {pair.claim_a}
                        </Text>
                      </Box>

                      {/* Fleche */}
                      <Icon as={FiArrowRight} color="orange.400" boxSize={4} mt={4} flexShrink={0} />

                      {/* Claim B */}
                      <Box flex={1}>
                        <Text fontSize="2xs" fontWeight="600" color="orange.300" mb={1}>
                          {pair.doc_b || 'Document B'}
                        </Text>
                        <Text fontSize="xs" color="text.secondary" lineHeight="tall">
                          {pair.claim_b}
                        </Text>
                      </Box>
                    </HStack>
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
