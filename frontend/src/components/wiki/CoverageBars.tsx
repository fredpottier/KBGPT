'use client'

import { Box, Text, VStack, HStack, Tooltip } from '@chakra-ui/react'

interface SourceDetail {
  doc_id?: string
  doc_title: string
  doc_type?: string | null
  unit_count: number
  contribution_pct: number
}

const TYPE_COLORS: Record<string, string> = {
  regulation: 'blue.400',
  guideline: 'cyan.400',
  standard: 'teal.400',
  annual_report: 'purple.400',
  policy: 'green.400',
  technical: 'orange.400',
}

function getBarColor(docType?: string | null): string {
  if (!docType) return 'brand.400'
  return TYPE_COLORS[docType] || 'brand.400'
}

interface CoverageBarsProps {
  sources: SourceDetail[]
}

export default function CoverageBars({ sources }: CoverageBarsProps) {
  if (!sources || sources.length === 0) return null

  const totalUnits = sources.reduce((sum, s) => sum + s.unit_count, 0)

  return (
    <Box bg="surface.default" rounded="xl" p={4} borderWidth="1px" borderColor="border.default">
      <Text color="text.muted" fontSize="xs" mb={3} fontWeight="semibold" textTransform="uppercase">
        Sources documentaires
      </Text>
      <VStack spacing={2} align="stretch">
        {sources.map((source, i) => {
          const pct = totalUnits > 0 ? Math.round((source.unit_count / totalUnits) * 100) : 0
          return (
            <Box key={i}>
              <HStack justify="space-between" mb={1}>
                <Tooltip label={source.doc_title} hasArrow>
                  <Text color="text.secondary" fontSize="xs" noOfLines={1} maxW="200px">
                    {source.doc_title}
                  </Text>
                </Tooltip>
                <Text color="text.muted" fontSize="xs" whiteSpace="nowrap">
                  {pct}%
                </Text>
              </HStack>
              <Box bg="gray.700" rounded="full" h="6px">
                <Box
                  bg={getBarColor(source.doc_type)}
                  h="6px"
                  rounded="full"
                  w={`${Math.max(pct, 2)}%`}
                  transition="width 0.5s"
                />
              </Box>
            </Box>
          )
        })}
      </VStack>
    </Box>
  )
}
