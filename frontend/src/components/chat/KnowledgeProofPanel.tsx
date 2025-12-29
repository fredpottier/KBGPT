'use client'

/**
 * Knowledge Proof Panel - OSMOSE Answer+Proof Bloc B
 *
 * Affiche le resume structure de l'etat de la connaissance.
 * Remplace le score pourcentage par des metriques concretes et comprehensibles.
 */

import {
  Box,
  HStack,
  VStack,
  Text,
  Icon,
  Badge,
  Collapse,
  useDisclosure,
  Tooltip,
  Progress,
} from '@chakra-ui/react'
import {
  ChevronDownIcon,
  ChevronUpIcon,
  WarningIcon,
  CheckCircleIcon,
} from '@chakra-ui/icons'
import {
  FiDatabase,
  FiLink,
  FiFileText,
  FiShield,
  FiAlertTriangle,
  FiCheckCircle,
  FiXCircle,
} from 'react-icons/fi'
import { KnowledgeProofSummary, EpistemicState } from '@/types/api'

interface KnowledgeProofPanelProps {
  proof: KnowledgeProofSummary
}

// Configuration des etats epistemiques
const EPISTEMIC_CONFIG: Record<EpistemicState, {
  icon: any
  color: string
  label: string
  bg: string
}> = {
  established: {
    icon: FiCheckCircle,
    color: 'green.400',
    label: 'Etablie',
    bg: 'rgba(34, 197, 94, 0.1)',
  },
  partial: {
    icon: FiAlertTriangle,
    color: 'yellow.400',
    label: 'Partielle',
    bg: 'rgba(234, 179, 8, 0.1)',
  },
  debate: {
    icon: FiXCircle,
    color: 'orange.400',
    label: 'Debat',
    bg: 'rgba(251, 146, 60, 0.1)',
  },
  incomplete: {
    icon: FiXCircle,
    color: 'red.400',
    label: 'Incomplete',
    bg: 'rgba(239, 68, 68, 0.1)',
  },
}

// Configuration des solidites
const SOLIDITY_CONFIG: Record<string, { color: string; icon: any }> = {
  Etablie: { color: 'green.400', icon: FiCheckCircle },
  Partielle: { color: 'yellow.400', icon: FiAlertTriangle },
  Fragile: { color: 'red.400', icon: FiXCircle },
}

export default function KnowledgeProofPanel({ proof }: KnowledgeProofPanelProps) {
  const { isOpen, onToggle } = useDisclosure({ defaultIsOpen: false })

  const epistemicConfig = EPISTEMIC_CONFIG[proof.epistemic_state] || EPISTEMIC_CONFIG.incomplete
  const solidityConfig = SOLIDITY_CONFIG[proof.solidity] || SOLIDITY_CONFIG.Fragile

  return (
    <Box
      bg="bg.secondary"
      borderRadius="lg"
      border="1px solid"
      borderColor="border.default"
      overflow="hidden"
    >
      {/* Header */}
      <HStack
        px={3}
        py={2}
        bg="bg.tertiary"
        borderBottom={isOpen ? '1px solid' : 'none'}
        borderColor="border.default"
        cursor="pointer"
        onClick={onToggle}
        _hover={{ bg: 'bg.hover' }}
        justify="space-between"
        transition="all 0.2s"
      >
        <HStack spacing={2}>
          <Icon as={FiShield} boxSize={4} color="brand.400" />
          <Text fontSize="xs" fontWeight="medium" color="text.primary">
            Etat de la connaissance
          </Text>
          <Badge
            colorScheme={
              proof.epistemic_state === 'established' ? 'green' :
              proof.epistemic_state === 'partial' ? 'yellow' :
              proof.epistemic_state === 'debate' ? 'orange' : 'red'
            }
            fontSize="2xs"
          >
            {epistemicConfig.label}
          </Badge>
        </HStack>
        <Icon
          as={isOpen ? ChevronUpIcon : ChevronDownIcon}
          color="text.muted"
          boxSize={4}
        />
      </HStack>

      {/* Content */}
      <Collapse in={isOpen}>
        <VStack spacing={4} p={4} align="stretch">
          {/* Section Fondements */}
          <Box>
            <Text fontSize="xs" fontWeight="semibold" color="text.secondary" mb={2}>
              Fondements
            </Text>
            <VStack spacing={1.5} align="stretch">
              <ProofMetric
                icon={FiDatabase}
                label="concepts identifies"
                value={proof.concepts_count}
              />
              <ProofMetric
                icon={FiLink}
                label="relations typees"
                value={proof.relations_count}
                detail={proof.relation_types.slice(0, 3).join(', ')}
              />
              <ProofMetric
                icon={FiFileText}
                label="sources documentaires"
                value={proof.sources_count}
              />
            </VStack>
          </Box>

          {/* Section Coherence */}
          <Box>
            <Text fontSize="xs" fontWeight="semibold" color="text.secondary" mb={2}>
              Coherence
            </Text>
            {proof.contradictions_count > 0 ? (
              <HStack
                p={2}
                bg="rgba(251, 146, 60, 0.1)"
                borderRadius="md"
                spacing={2}
              >
                <Icon as={WarningIcon} color="orange.400" boxSize={3.5} />
                <Text fontSize="xs" color="orange.300">
                  {proof.contradictions_count} contradiction(s) detectee(s)
                </Text>
              </HStack>
            ) : (
              <HStack
                p={2}
                bg="rgba(34, 197, 94, 0.1)"
                borderRadius="md"
                spacing={2}
              >
                <Icon as={CheckCircleIcon} color="green.400" boxSize={3.5} />
                <Text fontSize="xs" color="green.300">
                  Aucune contradiction detectee
                </Text>
              </HStack>
            )}
          </Box>

          {/* Section Nature */}
          <Box>
            <Text fontSize="xs" fontWeight="semibold" color="text.secondary" mb={2}>
              Nature
            </Text>
            <VStack spacing={2} align="stretch">
              {/* Types dominants */}
              {proof.dominant_concept_types.length > 0 && (
                <HStack spacing={1} flexWrap="wrap">
                  <Text fontSize="xs" color="text.muted">Types:</Text>
                  {proof.dominant_concept_types.map((type, idx) => (
                    <Badge key={idx} size="sm" variant="outline" colorScheme="blue">
                      {type}
                    </Badge>
                  ))}
                </HStack>
              )}

              {/* Solidite */}
              <HStack spacing={2}>
                <Text fontSize="xs" color="text.muted">Solidite:</Text>
                <HStack spacing={1}>
                  <Icon as={solidityConfig.icon} color={solidityConfig.color} boxSize={3} />
                  <Text fontSize="xs" color={solidityConfig.color}>
                    {proof.solidity}
                  </Text>
                </HStack>
              </HStack>

              {/* Maturite */}
              <Box>
                <HStack justify="space-between" mb={1}>
                  <Text fontSize="xs" color="text.muted">Maturite des relations</Text>
                  <Text fontSize="xs" color="text.secondary">
                    {proof.maturity_percent.toFixed(0)}%
                  </Text>
                </HStack>
                <Progress
                  value={proof.maturity_percent}
                  size="xs"
                  colorScheme={
                    proof.maturity_percent >= 70 ? 'green' :
                    proof.maturity_percent >= 40 ? 'yellow' : 'red'
                  }
                  bg="bg.tertiary"
                  borderRadius="full"
                />
              </Box>

              {/* Confiance moyenne */}
              <Box>
                <HStack justify="space-between" mb={1}>
                  <Text fontSize="xs" color="text.muted">Confiance moyenne</Text>
                  <Text fontSize="xs" color="text.secondary">
                    {(proof.avg_confidence * 100).toFixed(0)}%
                  </Text>
                </HStack>
                <Progress
                  value={proof.avg_confidence * 100}
                  size="xs"
                  colorScheme={
                    proof.avg_confidence >= 0.8 ? 'green' :
                    proof.avg_confidence >= 0.5 ? 'yellow' : 'red'
                  }
                  bg="bg.tertiary"
                  borderRadius="full"
                />
              </Box>
            </VStack>
          </Box>

          {/* Etat hors perimetre */}
          {proof.contract_state === 'out_of_scope' && (
            <Box
              p={2}
              bg="rgba(156, 163, 175, 0.1)"
              borderRadius="md"
              border="1px dashed"
              borderColor="gray.500"
            >
              <Text fontSize="xs" color="gray.400">
                Hors perimetre - Information indicative
              </Text>
            </Box>
          )}
        </VStack>
      </Collapse>
    </Box>
  )
}

// Composant pour une metrique individuelle
interface ProofMetricProps {
  icon: any
  label: string
  value: number
  detail?: string
}

function ProofMetric({ icon, label, value, detail }: ProofMetricProps) {
  return (
    <HStack spacing={2}>
      <Icon as={icon} color="text.muted" boxSize={3.5} />
      <Text fontSize="xs" color="text.primary">
        <Text as="span" fontWeight="medium" color="brand.400">
          {value}
        </Text>
        {' '}{label}
      </Text>
      {detail && (
        <Tooltip label={detail} placement="top" fontSize="xs">
          <Text fontSize="2xs" color="text.muted" fontFamily="mono" noOfLines={1}>
            ({detail})
          </Text>
        </Tooltip>
      )}
    </HStack>
  )
}
