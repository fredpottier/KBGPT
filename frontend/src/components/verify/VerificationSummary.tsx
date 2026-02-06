'use client'

import {
  Box,
  HStack,
  VStack,
  Text,
  Badge,
  Progress,
  Stat,
  StatLabel,
  StatNumber,
  SimpleGrid,
  Icon,
} from '@chakra-ui/react'
import { FiCheckCircle, FiXCircle, FiAlertCircle, FiDatabase, FiHelpCircle } from 'react-icons/fi'
import type { VerificationSummary as SummaryType } from '@/types/verification'

interface StatusConfig {
  label: string
  colorScheme: string
  icon: typeof FiCheckCircle
  description: string
}

const STATUS_CONFIG: Record<string, StatusConfig> = {
  confirmed: {
    label: 'Confirmé',
    colorScheme: 'green',
    icon: FiCheckCircle,
    description: 'Claims confirment',
  },
  contradicted: {
    label: 'Contredit',
    colorScheme: 'red',
    icon: FiXCircle,
    description: 'Claims contredisent',
  },
  incomplete: {
    label: 'Incomplet',
    colorScheme: 'orange',
    icon: FiAlertCircle,
    description: 'Info partielle',
  },
  fallback: {
    label: 'RAG',
    colorScheme: 'gray',
    icon: FiDatabase,
    description: 'Chunks trouvés',
  },
  unknown: {
    label: 'Inconnu',
    colorScheme: 'gray',
    icon: FiHelpCircle,
    description: 'Non trouvé',
  },
}

interface VerificationSummaryProps {
  summary: SummaryType
}

export function VerificationSummary({ summary }: VerificationSummaryProps) {
  const { total, confirmed, contradicted, incomplete, fallback, unknown } = summary

  // Calculate percentages
  const getPercent = (value: number) => (total > 0 ? (value / total) * 100 : 0)

  // Overall quality score (weighted)
  const qualityScore = total > 0
    ? Math.round(
        ((confirmed * 1.0 + fallback * 0.5 + incomplete * 0.3) / total) * 100
      )
    : 0

  // Determine overall status
  const getOverallStatus = () => {
    if (contradicted > 0) return { label: 'Corrections recommandées', color: 'red' }
    if (incomplete > total * 0.3) return { label: 'Vérification partielle', color: 'orange' }
    if (confirmed > total * 0.5) return { label: 'Bien vérifié', color: 'green' }
    return { label: 'Vérification incomplète', color: 'gray' }
  }

  const overallStatus = getOverallStatus()

  return (
    <Box
      bg="bg.secondary"
      p={4}
      rounded="xl"
      border="1px solid"
      borderColor="border.default"
      mb={4}
    >
      {/* Header */}
      <HStack justify="space-between" mb={4}>
        <VStack align="start" spacing={0}>
          <Text fontSize="lg" fontWeight="bold" color="text.primary">
            Résumé de vérification
          </Text>
          <Text fontSize="sm" color="text.muted">
            {total} assertion{total > 1 ? 's' : ''} analysée{total > 1 ? 's' : ''}
          </Text>
        </VStack>
        <Badge
          colorScheme={overallStatus.color}
          fontSize="sm"
          px={3}
          py={1}
          rounded="full"
        >
          {overallStatus.label}
        </Badge>
      </HStack>

      {/* Progress bars */}
      <Box mb={4}>
        <HStack h="8px" spacing={0} rounded="full" overflow="hidden" bg="bg.primary">
          <Box
            w={`${getPercent(confirmed)}%`}
            h="100%"
            bg="green.500"
            transition="width 0.3s"
          />
          <Box
            w={`${getPercent(contradicted)}%`}
            h="100%"
            bg="red.500"
            transition="width 0.3s"
          />
          <Box
            w={`${getPercent(incomplete)}%`}
            h="100%"
            bg="orange.500"
            transition="width 0.3s"
          />
          <Box
            w={`${getPercent(fallback)}%`}
            h="100%"
            bg="gray.400"
            transition="width 0.3s"
          />
          <Box
            w={`${getPercent(unknown)}%`}
            h="100%"
            bg="gray.600"
            transition="width 0.3s"
          />
        </HStack>
      </Box>

      {/* Stats grid */}
      <SimpleGrid columns={{ base: 2, md: 5 }} spacing={3}>
        {Object.entries({
          confirmed,
          contradicted,
          incomplete,
          fallback,
          unknown,
        }).map(([key, value]) => {
          const config = STATUS_CONFIG[key]
          return (
            <Box
              key={key}
              p={2}
              bg="bg.primary"
              rounded="lg"
              textAlign="center"
            >
              <HStack justify="center" mb={1}>
                <Icon as={config.icon} color={`${config.colorScheme}.500`} boxSize={4} />
                <Text fontSize="xs" color="text.muted" fontWeight="medium">
                  {config.label}
                </Text>
              </HStack>
              <Text fontSize="xl" fontWeight="bold" color="text.primary">
                {value}
              </Text>
              <Text fontSize="xs" color="text.muted">
                {Math.round(getPercent(value))}%
              </Text>
            </Box>
          )
        })}
      </SimpleGrid>

      {/* Quality score */}
      <Box mt={4} pt={4} borderTop="1px solid" borderColor="border.default">
        <HStack justify="space-between">
          <Text fontSize="sm" color="text.muted">
            Score de fiabilité estimé
          </Text>
          <HStack>
            <Progress
              value={qualityScore}
              size="sm"
              w="100px"
              rounded="full"
              colorScheme={
                qualityScore >= 70 ? 'green' :
                qualityScore >= 40 ? 'orange' : 'red'
              }
            />
            <Text fontWeight="bold" color="text.primary">
              {qualityScore}%
            </Text>
          </HStack>
        </HStack>
      </Box>
    </Box>
  )
}
