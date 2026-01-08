'use client'

/**
 * Badge du Contrat de Verite (Truth Contract) - OSMOSE Assertion-Centric.
 *
 * Affiche un resume compact:
 * "5 faits sources · 2 inferences · 1 fragile · 0 conflit · Sources 2023-2025"
 *
 * En mode simple: affiche seulement "X sources utilisees"
 */

import {
  Box,
  HStack,
  Text,
  Icon,
  Tooltip,
  Badge,
} from '@chakra-ui/react'
import { FiShield, FiInfo } from 'react-icons/fi'
import type { TruthContract, InstrumentationMode } from '@/types/instrumented'
import { formatTruthContractSimple, formatTruthContractFull, ASSERTION_STYLES } from '@/types/instrumented'

interface TruthContractBadgeProps {
  contract: TruthContract
  mode: InstrumentationMode
}

export default function TruthContractBadge({
  contract,
  mode,
}: TruthContractBadgeProps) {
  // Mode simple: affichage minimal
  if (mode === 'simple') {
    return (
      <HStack spacing={1.5} color="text.secondary" fontSize="xs">
        <Icon as={FiInfo} boxSize={3} />
        <Text>{formatTruthContractSimple(contract)}</Text>
      </HStack>
    )
  }

  // Mode instrumented: affichage complet
  const { facts_count, inferred_count, fragile_count, conflict_count, sources_date_range } = contract

  return (
    <Box
      bg="rgba(34, 197, 94, 0.08)"
      border="1px solid"
      borderColor="green.500"
      borderRadius="md"
      px={3}
      py={2}
    >
      <HStack spacing={3} flexWrap="wrap">
        {/* Icone bouclier */}
        <HStack spacing={1.5}>
          <Icon as={FiShield} boxSize={4} color="green.500" />
          <Text fontSize="xs" fontWeight="semibold" color="green.500">
            Contrat de verite
          </Text>
        </HStack>

        {/* Separateur */}
        <Box h={4} w="1px" bg="green.500" opacity={0.3} />

        {/* Compteurs */}
        <HStack spacing={2} flexWrap="wrap">
          {/* Facts */}
          {facts_count > 0 && (
            <Tooltip label="Faits explicitement presents dans les sources" hasArrow>
              <Badge
                colorScheme="green"
                variant="subtle"
                fontSize="xs"
                px={2}
                py={0.5}
                borderRadius="full"
              >
                <HStack spacing={1}>
                  <Text>{ASSERTION_STYLES.FACT.indicator}</Text>
                  <Text>{facts_count} fait{facts_count > 1 ? 's' : ''}</Text>
                </HStack>
              </Badge>
            </Tooltip>
          )}

          {/* Inferred */}
          {inferred_count > 0 && (
            <Tooltip label="Deductions logiques basees sur les faits" hasArrow>
              <Badge
                colorScheme="blue"
                variant="subtle"
                fontSize="xs"
                px={2}
                py={0.5}
                borderRadius="full"
              >
                <HStack spacing={1}>
                  <Text>{ASSERTION_STYLES.INFERRED.indicator}</Text>
                  <Text>{inferred_count} inference{inferred_count > 1 ? 's' : ''}</Text>
                </HStack>
              </Badge>
            </Tooltip>
          )}

          {/* Fragile */}
          {fragile_count > 0 && (
            <Tooltip label="Affirmations faiblement soutenues" hasArrow>
              <Badge
                colorScheme="orange"
                variant="subtle"
                fontSize="xs"
                px={2}
                py={0.5}
                borderRadius="full"
              >
                <HStack spacing={1}>
                  <Text>{ASSERTION_STYLES.FRAGILE.indicator}</Text>
                  <Text>{fragile_count} fragile{fragile_count > 1 ? 's' : ''}</Text>
                </HStack>
              </Badge>
            </Tooltip>
          )}

          {/* Conflict */}
          {conflict_count > 0 && (
            <Tooltip label="Sources contradictoires detectees" hasArrow>
              <Badge
                colorScheme="red"
                variant="subtle"
                fontSize="xs"
                px={2}
                py={0.5}
                borderRadius="full"
              >
                <HStack spacing={1}>
                  <Text>{ASSERTION_STYLES.CONFLICT.indicator}</Text>
                  <Text>{conflict_count} conflit{conflict_count > 1 ? 's' : ''}</Text>
                </HStack>
              </Badge>
            </Tooltip>
          )}
        </HStack>

        {/* Date range */}
        {sources_date_range && (
          <>
            <Box h={4} w="1px" bg="green.500" opacity={0.3} />
            <Text fontSize="xs" color="text.secondary">
              Sources {sources_date_range.from}–{sources_date_range.to}
            </Text>
          </>
        )}
      </HStack>
    </Box>
  )
}

export { TruthContractBadge }
