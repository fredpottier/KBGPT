'use client'

import { Box, HStack, Text } from '@chakra-ui/react'

interface MetricBarProps {
  label: string
  value: number          // 0.0 - 1.0
  delta?: number | null  // vs baseline, in pp
  count?: number         // number of questions
}

export function MetricBar({ label, value, delta, count }: MetricBarProps) {
  const pct = Math.round(value * 100)
  const color = pct >= 70 ? '#22c55e' : pct >= 50 ? '#eab308' : '#ef4444'

  return (
    <Box mb={2}>
      <HStack justify="space-between" mb={1}>
        <HStack spacing={2}>
          <Text fontSize="13px" color="var(--text-secondary, #94a3b8)" fontFamily="'Fira Sans', sans-serif">
            {label}
          </Text>
          {count !== undefined && (
            <Text fontSize="10px" color="var(--text-muted, #475569)">
              {count}q
            </Text>
          )}
        </HStack>
        <HStack spacing={2}>
          <Text fontSize="15px" fontWeight="700" color={color} fontFamily="'Fira Code', monospace">
            {pct}%
          </Text>
          {delta !== null && delta !== undefined && delta !== 0 && (
            <Text
              fontSize="11px"
              fontFamily="'Fira Code', monospace"
              color={delta > 0 ? '#22c55e' : '#ef4444'}
            >
              {delta > 0 ? '+' : ''}{delta}
            </Text>
          )}
        </HStack>
      </HStack>
      <Box h="8px" bg="var(--border-subtle, #1e1e3a)" rounded="full" overflow="hidden">
        <Box
          h="100%"
          w={`${pct}%`}
          bg={color}
          rounded="full"
          transition="width 0.5s ease"
        />
      </Box>
    </Box>
  )
}
