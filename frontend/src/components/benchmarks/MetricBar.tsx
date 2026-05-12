'use client'

import { Box, HStack, Text } from '@chakra-ui/react'

interface MetricBarProps {
  label: string
  value: number | null   // 0.0 - 1.0 ; null = métrique non applicable (N/A)
  delta?: number | null  // vs RAG pur, in pp
  count?: number         // number of questions
}

export function MetricBar({ label, value, delta, count }: MetricBarProps) {
  // CH-30.13 — value=null signifie "N/A" : on n'affiche pas de pourcentage ni
  // de barre colorée pour ne pas tirer artificiellement le score perçu vers le bas.
  if (value === null) {
    return (
      <Box mb={2}>
        <HStack justify="space-between" mb={1}>
          <Text fontSize="13px" color="var(--fg-muted)" fontFamily="'Fira Sans', sans-serif">
            {label}
          </Text>
          <Text fontSize="13px" fontFamily="'Fira Code', monospace" color="var(--fg-muted)">
            N/A
          </Text>
        </HStack>
        <Box h="8px" bg="var(--border-default)" rounded="full" opacity={0.4} />
      </Box>
    )
  }

  const pct = Math.round(value * 100)
  const color = pct >= 70 ? '#22c55e' : pct >= 50 ? '#eab308' : '#ef4444'

  return (
    <Box mb={2}>
      <HStack justify="space-between" mb={1}>
        <HStack spacing={2}>
          <Text fontSize="13px" color="var(--fg-secondary)" fontFamily="'Fira Sans', sans-serif">
            {label}
          </Text>
          {count !== undefined && (
            <Text fontSize="10px" color="var(--fg-muted)">
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
      <Box h="8px" bg="var(--border-default)" rounded="full" overflow="hidden">
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
