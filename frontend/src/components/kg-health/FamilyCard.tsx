'use client'

/**
 * Card d'une famille (Provenance / Structure / Distribution / Coherence).
 * Affiche le score de la famille + ses metriques ponderees.
 */

import { Box, Text, HStack, VStack, Badge, Icon } from '@chakra-ui/react'
import {
  FiShield,
  FiLayers,
  FiActivity,
  FiCheckCircle,
} from 'react-icons/fi'
import { FamilyScore, zoneColor, zoneScheme } from './types'
import { MetricRow } from './MetricRow'

const FAMILY_ICONS: Record<string, any> = {
  provenance: FiShield,
  structure: FiLayers,
  distribution: FiActivity,
  coherence: FiCheckCircle,
}

const FAMILY_DESCRIPTIONS: Record<string, string> = {
  provenance:
    'Traçabilite, diversite des sources et resolution des entites (25% du score global)',
  structure:
    'Integrite des liens claim-facet-entity et resolution des sujets (35% du score global)',
  distribution:
    'Richesse et equilibre de l\'extraction (pas de hub dominant, 20% du score global)',
  coherence:
    'Absence de contradictions dures, cohesion du graphe, fraicheur des Perspectives (20% du score global)',
}

interface FamilyCardProps {
  family: FamilyScore
  onDrilldown: (key: string) => void
}

export function FamilyCard({ family, onDrilldown }: FamilyCardProps) {
  const color = zoneColor(family.status.zone)
  const icon = FAMILY_ICONS[family.name] ?? FiActivity
  const description = FAMILY_DESCRIPTIONS[family.name] ?? ''

  return (
    <Box
      bg="var(--bg-secondary)"
      borderRadius="xl"
      p={5}
      borderWidth="1px"
      borderColor="var(--border-default)"
      borderLeftWidth="3px"
      borderLeftColor={color}
    >
      <HStack justify="space-between" align="start" mb={3}>
        <HStack spacing={3} align="start">
          <Icon as={icon} color={color} boxSize={5} mt={0.5} />
          <VStack align="start" spacing={0.5}>
            <Text fontSize="md" fontWeight="700" color="var(--text-primary)">
              {family.label}
            </Text>
            <Text fontSize="xs" color="var(--text-muted)" maxW="340px">
              {description}
            </Text>
          </VStack>
        </HStack>

        <VStack align="end" spacing={1}>
          <HStack spacing={2}>
            <Text fontSize="2xl" fontWeight="800" color={color} lineHeight={1}>
              {family.score.toFixed(0)}
            </Text>
            <Text fontSize="xs" color="var(--text-muted)">
              /100
            </Text>
          </HStack>
          <Badge colorScheme={zoneScheme(family.status.zone)} variant="subtle" fontSize="2xs">
            {family.status.label}
          </Badge>
        </VStack>
      </HStack>

      <Box>
        {family.metrics.map((m) => (
          <MetricRow key={m.key} metric={m} onDrilldown={onDrilldown} />
        ))}
      </Box>
    </Box>
  )
}
