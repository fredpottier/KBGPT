'use client'

/**
 * Header global du KG Health : gauge score + resume corpus.
 */

import { Box, Text, HStack, VStack, Flex, Badge, SimpleGrid, Icon } from '@chakra-ui/react'
import { FiDatabase, FiFileText, FiLayers, FiActivity, FiAlertTriangle } from 'react-icons/fi'
import { KGHealthScoreResponse, zoneColor, zoneScheme } from './types'

function ScoreGauge({ score, zone }: { score: number; zone: 'green' | 'yellow' | 'red' }) {
  const color = zoneColor(zone)
  const size = 160
  const strokeWidth = 10
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  const strokeDashoffset = circumference * (1 - score / 100)

  return (
    <Box position="relative" w={`${size}px`} h={`${size}px`} flexShrink={0}>
      <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="rgba(255,255,255,0.06)"
          strokeWidth={strokeWidth}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={strokeDashoffset}
          style={{ transition: 'stroke-dashoffset 1s ease-out' }}
        />
      </svg>
      <Flex position="absolute" inset={0} align="center" justify="center" direction="column">
        <Text fontSize="4xl" fontWeight="800" color={color} lineHeight={1}>
          {score.toFixed(0)}
        </Text>
        <Text fontSize="xs" color="var(--text-muted)" mt={1}>
          /100
        </Text>
      </Flex>
    </Box>
  )
}

function StatCard({
  icon,
  label,
  value,
  color,
}: {
  icon: any
  label: string
  value: string | number
  color: string
}) {
  return (
    <Box
      bg="var(--bg-secondary)"
      borderRadius="lg"
      p={3}
      borderWidth="1px"
      borderColor="var(--border-default)"
    >
      <HStack spacing={3}>
        <Icon as={icon} color={color} boxSize={4} />
        <Box>
          <Text fontSize="lg" fontWeight="700" color="var(--text-primary)" lineHeight={1.1}>
            {typeof value === 'number' ? value.toLocaleString() : value}
          </Text>
          <Text fontSize="2xs" color="var(--text-muted)">
            {label}
          </Text>
        </Box>
      </HStack>
    </Box>
  )
}

export function HealthScoreCard({ data }: { data: KGHealthScoreResponse }) {
  return (
    <Box
      bg="var(--bg-secondary)"
      borderRadius="xl"
      p={6}
      borderWidth="1px"
      borderColor="var(--border-default)"
      mb={6}
    >
      <HStack spacing={8} align="center" mb={5}>
        <ScoreGauge score={data.global_score} zone={data.global_status.zone} />

        <VStack align="start" spacing={2} flex={1}>
          <HStack spacing={2}>
            <Text fontSize="xs" color="var(--text-muted)" textTransform="uppercase" letterSpacing="wide">
              Score global KG Health
            </Text>
            <Badge colorScheme={zoneScheme(data.global_status.zone)} fontSize="2xs" px={2}>
              {data.global_status.label}
            </Badge>
          </HStack>
          <Text fontSize="xl" fontWeight="700" color="var(--text-primary)" lineHeight={1.2}>
            Diagnostic intrinseque de la qualite du Knowledge Graph
          </Text>
          <Text fontSize="sm" color="var(--text-muted)">
            Calcule en {data.compute_duration_ms} ms &middot; 4 familles &middot; pondere
          </Text>
        </VStack>
      </HStack>

      <SimpleGrid columns={{ base: 2, md: 5 }} spacing={3}>
        <StatCard
          icon={FiFileText}
          label="Documents"
          value={data.summary.total_documents}
          color="brand.400"
        />
        <StatCard
          icon={FiDatabase}
          label="Claims"
          value={data.summary.total_claims}
          color="green.400"
        />
        <StatCard
          icon={FiActivity}
          label="Entites"
          value={data.summary.total_entities}
          color="blue.400"
        />
        <StatCard
          icon={FiLayers}
          label="Facets"
          value={data.summary.total_facets}
          color="purple.400"
        />
        <StatCard
          icon={FiAlertTriangle}
          label="Contradictions"
          value={data.summary.total_contradictions}
          color="orange.400"
        />
      </SimpleGrid>
    </Box>
  )
}
