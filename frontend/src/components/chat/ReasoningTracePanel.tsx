'use client'

/**
 * Reasoning Trace Panel - OSMOSE Answer+Proof Bloc C
 *
 * Affiche le chemin de preuve narratif.
 * Montre POURQUOI la reponse tient en affichant les relations KG utilisees.
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
} from '@chakra-ui/react'
import {
  ChevronDownIcon,
  ChevronUpIcon,
  CheckCircleIcon,
  WarningIcon,
} from '@chakra-ui/icons'
import { FiSearch, FiAlertTriangle, FiCheckCircle, FiLink } from 'react-icons/fi'
import { ReasoningTrace, ReasoningStep, ReasoningSupport } from '@/types/api'

interface ReasoningTracePanelProps {
  trace: ReasoningTrace
  onSourceClick?: (sourceRef: string) => void
}

// Couleurs par type de relation
const RELATION_COLORS: Record<string, string> = {
  REQUIRES: 'blue',
  CAUSES: 'red',
  ENABLES: 'green',
  PART_OF: 'purple',
  SUBTYPE_OF: 'cyan',
  CONFLICTS_WITH: 'orange',
  APPLIES_TO: 'teal',
  USES: 'pink',
  DEFAULT: 'gray',
}

// Configuration coherence (definie hors du composant)
const COHERENCE_CONFIG: Record<string, { icon: any; color: string; label: string }> = {
  coherent: { icon: FiCheckCircle, color: 'green.400', label: 'Coherent' },
  partial_conflict: { icon: FiAlertTriangle, color: 'yellow.400', label: 'Partiel' },
  conflict: { icon: FiAlertTriangle, color: 'orange.400', label: 'Conflit' },
}

export default function ReasoningTracePanel({ trace, onSourceClick }: ReasoningTracePanelProps) {
  const { isOpen, onToggle } = useDisclosure({ defaultIsOpen: false })

  const coherenceConfig = COHERENCE_CONFIG[trace.coherence_status] || COHERENCE_CONFIG['coherent']

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
          <Icon as={FiSearch} boxSize={4} color="brand.400" />
          <Text fontSize="xs" fontWeight="medium" color="text.primary">
            Pourquoi cette reponse tient
          </Text>
          <Badge
            colorScheme={
              trace.coherence_status === 'coherent' ? 'green' :
              trace.coherence_status === 'partial_conflict' ? 'yellow' : 'orange'
            }
            fontSize="2xs"
          >
            {trace.steps.length} etape(s)
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
        <VStack spacing={3} p={4} align="stretch">
          {/* Etapes de raisonnement */}
          {trace.steps.length === 0 ? (
            <Text fontSize="xs" color="text.muted" textAlign="center" py={4}>
              Aucun chemin de raisonnement identifie
            </Text>
          ) : (
            trace.steps.map((step) => (
              <ReasoningStepCard
                key={step.step}
                step={step}
                onSourceClick={onSourceClick}
              />
            ))
          )}

          {/* Footer coherence */}
          <Box
            mt={2}
            pt={3}
            borderTop="1px solid"
            borderColor="border.default"
          >
            <HStack spacing={2}>
              <Icon as={coherenceConfig.icon} color={coherenceConfig.color} boxSize={4} />
              <Text fontSize="xs" color="text.secondary">
                {trace.coherence_message || 'Ces regles sont coherentes entre elles.'}
              </Text>
            </HStack>

            {trace.unsupported_steps_count > 0 && (
              <Text fontSize="2xs" color="text.muted" mt={1}>
                {trace.unsupported_steps_count} etape(s) non supportee(s) par le graphe
              </Text>
            )}
          </Box>
        </VStack>
      </Collapse>
    </Box>
  )
}

// Composant pour une etape de raisonnement
interface ReasoningStepCardProps {
  step: ReasoningStep
  onSourceClick?: (sourceRef: string) => void
}

function ReasoningStepCard({ step, onSourceClick }: ReasoningStepCardProps) {
  const borderColor = step.is_conflict ? 'orange.500' :
                      step.has_kg_support ? 'brand.500' : 'gray.500'
  const borderStyle = step.has_kg_support ? 'solid' : 'dashed'

  return (
    <Box
      pl={4}
      borderLeft="2px"
      borderLeftStyle={borderStyle}
      borderLeftColor={borderColor}
      py={1}
    >
      {/* Statement */}
      <HStack spacing={2} mb={1}>
        <Text fontSize="xs" fontWeight="medium" color="text.primary">
          {step.step}.
        </Text>
        <Text fontSize="xs" color="text.primary">
          {step.statement}
        </Text>
        {!step.has_kg_support && (
          <Tooltip label="Non supporte par le KG" placement="top" fontSize="xs">
            <Badge colorScheme="gray" fontSize="2xs" variant="outline">
              Hypothese
            </Badge>
          </Tooltip>
        )}
        {step.is_conflict && (
          <Tooltip label="Contradiction detectee" placement="top" fontSize="xs">
            <Badge colorScheme="orange" fontSize="2xs">
              Conflit
            </Badge>
          </Tooltip>
        )}
      </HStack>

      {/* Relations de support */}
      {step.supports.length > 0 && (
        <VStack align="start" pl={4} mt={1} spacing={0.5}>
          {step.supports.map((support, idx) => (
            <SupportRelation
              key={idx}
              support={support}
              onSourceClick={onSourceClick}
            />
          ))}
        </VStack>
      )}
    </Box>
  )
}

// Composant pour une relation de support
interface SupportRelationProps {
  support: ReasoningSupport
  onSourceClick?: (sourceRef: string) => void
}

function SupportRelation({ support, onSourceClick }: SupportRelationProps) {
  const colorScheme = RELATION_COLORS[support.relation_type] || RELATION_COLORS.DEFAULT

  return (
    <HStack fontSize="2xs" color="text.muted" spacing={1}>
      <Text color="text.muted">-</Text>
      <Badge
        colorScheme={colorScheme}
        fontSize="2xs"
        variant="subtle"
        px={1}
      >
        {support.relation_type}
      </Badge>
      <Icon as={FiLink} boxSize={2.5} />
      <Text color="text.secondary" fontFamily="mono">
        {support.target_concept_name}
      </Text>
      <Tooltip
        label={`Confiance: ${(support.edge_confidence * 100).toFixed(0)}%`}
        placement="top"
        fontSize="xs"
      >
        <Box
          w={1.5}
          h={1.5}
          rounded="full"
          bg={
            support.edge_confidence >= 0.7 ? 'green.400' :
            support.edge_confidence >= 0.4 ? 'yellow.400' : 'gray.400'
          }
        />
      </Tooltip>
      {support.source_refs.length > 0 && onSourceClick && (
        <Text
          color="brand.400"
          cursor="pointer"
          _hover={{ textDecoration: 'underline' }}
          onClick={() => onSourceClick(support.source_refs[0])}
        >
          [source]
        </Text>
      )}
    </HStack>
  )
}
