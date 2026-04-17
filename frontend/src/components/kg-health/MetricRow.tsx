'use client'

/**
 * Ligne d'une metrique individuelle dans une FamilyCard.
 */

import { Box, Text, HStack, VStack, Progress, Badge, Button, Icon } from '@chakra-ui/react'
import { FiChevronRight } from 'react-icons/fi'
import { Metric, zoneColor, zoneGradient, zoneScheme } from './types'

interface MetricRowProps {
  metric: Metric
  onDrilldown?: (key: string) => void
}

export function MetricRow({ metric, onDrilldown }: MetricRowProps) {
  const color = zoneColor(metric.status.zone)
  const pctValue = Math.round(metric.value * 100)

  return (
    <Box py={2} borderTop="1px solid" borderColor="var(--border-default)" _first={{ borderTop: 'none' }}>
      <HStack justify="space-between" align="center" spacing={4}>
        <VStack align="start" spacing={0.5} flex={1}>
          <HStack spacing={2}>
            <Text fontSize="sm" color="var(--text-primary)" fontWeight="600">
              {metric.label}
            </Text>
            <Badge
              colorScheme={zoneScheme(metric.status.zone)}
              variant="subtle"
              fontSize="2xs"
              px={1.5}
            >
              {metric.display_value}
            </Badge>
            {metric.drilldown_available && onDrilldown && metric.drilldown_key && (
              <Button
                size="xs"
                variant="ghost"
                color="brand.300"
                onClick={() => onDrilldown(metric.drilldown_key!)}
                rightIcon={<Icon as={FiChevronRight} boxSize={3} />}
                fontSize="2xs"
                h="20px"
                px={2}
              >
                Details
              </Button>
            )}
          </HStack>
          <Text fontSize="xs" color="var(--text-muted)">
            {metric.description}
          </Text>
        </VStack>

        <Box w="140px" flexShrink={0}>
          <Progress
            value={pctValue}
            size="sm"
            borderRadius="full"
            bg="var(--bg-primary)"
            sx={{
              '& > div': {
                background: zoneGradient(metric.status.zone),
              },
            }}
          />
          <Text fontSize="2xs" color="var(--text-muted)" textAlign="right" mt={0.5}>
            poids {(metric.weight * 100).toFixed(0)}%
          </Text>
        </Box>
      </HStack>
    </Box>
  )
}
