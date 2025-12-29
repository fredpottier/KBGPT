'use client'

/**
 * Coverage Map Panel - OSMOSE Answer+Proof Bloc D
 *
 * Affiche la carte de couverture: ce qui est couvert ET ce qui ne l'est pas.
 * C'est LA vraie differenciation vs RAG standard.
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
  Progress,
  List,
  ListItem,
  ListIcon,
} from '@chakra-ui/react'
import {
  ChevronDownIcon,
  ChevronUpIcon,
  WarningIcon,
} from '@chakra-ui/icons'
import {
  FiMap,
  FiCheckCircle,
  FiAlertCircle,
  FiXCircle,
  FiAlertTriangle,
  FiArrowRight,
} from 'react-icons/fi'
import { CoverageMap, DomainCoverage } from '@/types/api'

interface CoverageMapPanelProps {
  coverage: CoverageMap
}

// Configuration des statuts de domaine
const STATUS_CONFIG: Record<string, {
  icon: any
  color: string
  colorScheme: string
  label: string
}> = {
  covered: {
    icon: FiCheckCircle,
    color: 'green.400',
    colorScheme: 'green',
    label: 'Couvert',
  },
  partial: {
    icon: FiAlertCircle,
    color: 'yellow.400',
    colorScheme: 'yellow',
    label: 'Partiel',
  },
  debate: {
    icon: FiAlertTriangle,
    color: 'orange.400',
    colorScheme: 'orange',
    label: 'Debat',
  },
  not_covered: {
    icon: FiXCircle,
    color: 'red.400',
    colorScheme: 'red',
    label: 'Non couvert',
  },
}

export default function CoverageMapPanel({ coverage }: CoverageMapPanelProps) {
  const { isOpen, onToggle } = useDisclosure({ defaultIsOpen: false })

  // Cas special: DomainContext non configure
  if (coverage.message) {
    return (
      <Box
        bg="bg.secondary"
        borderRadius="lg"
        border="1px dashed"
        borderColor="gray.500"
        p={4}
      >
        <HStack spacing={2}>
          <Icon as={FiMap} boxSize={4} color="gray.400" />
          <Text fontSize="xs" color="gray.400">
            {coverage.message}
          </Text>
        </HStack>
      </Box>
    )
  }

  // Pas de domaines
  if (coverage.domains.length === 0) {
    return null
  }

  const coverageColor = coverage.coverage_percent !== null
    ? coverage.coverage_percent >= 70 ? 'green'
      : coverage.coverage_percent >= 40 ? 'yellow' : 'red'
    : 'gray'

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
          <Icon as={FiMap} boxSize={4} color="brand.400" />
          <Text fontSize="xs" fontWeight="medium" color="text.primary">
            Couverture de la question
          </Text>
          {coverage.coverage_percent !== null && (
            <Badge colorScheme={coverageColor} fontSize="2xs">
              {coverage.coverage_percent.toFixed(0)}%
            </Badge>
          )}
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
          {/* Liste des domaines */}
          <VStack spacing={2} align="stretch">
            {coverage.domains.map((domain) => (
              <DomainRow key={domain.domain_id} domain={domain} />
            ))}
          </VStack>

          {/* Resume */}
          {coverage.coverage_percent !== null && (
            <Box
              mt={2}
              p={3}
              bg="bg.tertiary"
              borderRadius="md"
            >
              <HStack justify="space-between" mb={2}>
                <Text fontSize="xs" color="text.secondary">
                  Couverture globale
                </Text>
                <Text fontSize="xs" fontWeight="medium" color={`${coverageColor}.400`}>
                  {coverage.covered_count}/{coverage.total_relevant} domaines
                </Text>
              </HStack>
              <Progress
                value={coverage.coverage_percent}
                size="sm"
                colorScheme={coverageColor}
                bg="bg.secondary"
                borderRadius="full"
              />
            </Box>
          )}

          {/* Recommandations */}
          {coverage.recommendations.length > 0 && (
            <Box
              mt={2}
              p={3}
              bg="rgba(251, 191, 36, 0.1)"
              borderRadius="md"
              border="1px solid"
              borderColor="yellow.600"
            >
              <HStack spacing={2} mb={2}>
                <Icon as={WarningIcon} color="yellow.400" boxSize={3.5} />
                <Text fontSize="xs" fontWeight="medium" color="yellow.300">
                  Pour une analyse complete, considerez :
                </Text>
              </HStack>
              <List spacing={1} pl={5}>
                {coverage.recommendations.map((rec, idx) => (
                  <ListItem key={idx} fontSize="xs" color="text.muted">
                    <ListIcon as={FiArrowRight} color="yellow.400" boxSize={3} />
                    {rec}
                  </ListItem>
                ))}
              </List>
            </Box>
          )}
        </VStack>
      </Collapse>
    </Box>
  )
}

// Composant pour une ligne de domaine
interface DomainRowProps {
  domain: DomainCoverage
}

function DomainRow({ domain }: DomainRowProps) {
  const config = STATUS_CONFIG[domain.status] || STATUS_CONFIG.not_covered

  return (
    <HStack
      py={1.5}
      px={2}
      borderRadius="md"
      justify="space-between"
      _hover={{ bg: 'bg.hover' }}
      transition="all 0.15s"
    >
      {/* Nom du domaine */}
      <Text fontSize="xs" color="text.primary" flex={1}>
        {domain.domain}
      </Text>

      {/* Statut */}
      <HStack spacing={2}>
        <Icon as={config.icon} color={config.color} boxSize={3.5} />
        <Text fontSize="xs" color={config.color} minW="70px">
          {config.label}
          {domain.relations_count > 0 && (
            <Text as="span" color="text.muted">
              {' '}({domain.relations_count})
            </Text>
          )}
        </Text>
      </HStack>

      {/* Note optionnelle */}
      {domain.note && (
        <Text fontSize="2xs" color="text.muted" fontStyle="italic">
          {domain.note}
        </Text>
      )}
    </HStack>
  )
}
