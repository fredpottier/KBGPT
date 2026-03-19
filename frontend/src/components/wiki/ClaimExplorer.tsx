'use client'

import { useState, useEffect } from 'react'
import {
  Box,
  Text,
  VStack,
  HStack,
  Badge,
  Spinner,
  Icon,
} from '@chakra-ui/react'
import { FiChevronDown, FiChevronRight } from 'react-icons/fi'
import { api } from '@/lib/api'

interface ClaimItem {
  claim_id: string
  text: string
  claim_type: string
  confidence: number
  doc_id?: string
  source_title: string
}

const CLAIM_TYPE_COLORS: Record<string, string> = {
  PRESCRIPTIVE: 'red',
  FACTUAL: 'blue',
  DEFINITIONAL: 'purple',
  PERMISSIVE: 'green',
  COMPARATIVE: 'orange',
  CONTEXTUAL: 'gray',
}

interface ClaimExplorerProps {
  slug: string
}

export default function ClaimExplorer({ slug }: ClaimExplorerProps) {
  const [claims, setClaims] = useState<ClaimItem[]>([])
  const [loading, setLoading] = useState(true)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  useEffect(() => {
    async function fetchClaims() {
      setLoading(true)
      const res = await api.wiki.articleClaims(slug, 10)
      if (res.success && res.data) {
        const d = res.data as { claims: ClaimItem[] }
        if (d.claims) setClaims(d.claims)
      }
      setLoading(false)
    }
    fetchClaims()
  }, [slug])

  if (loading) {
    return (
      <Box bg="surface.default" rounded="xl" p={4} borderWidth="1px" borderColor="border.default">
        <HStack>
          <Spinner size="sm" color="brand.400" />
          <Text color="text.muted" fontSize="sm">Chargement claims...</Text>
        </HStack>
      </Box>
    )
  }

  if (claims.length === 0) return null

  return (
    <Box bg="surface.default" rounded="xl" p={4} borderWidth="1px" borderColor="border.default">
      <Text color="text.muted" fontSize="xs" mb={3} fontWeight="semibold" textTransform="uppercase">
        Claims ({claims.length})
      </Text>
      <VStack spacing={2} align="stretch">
        {claims.map((claim) => {
          const isExpanded = expandedId === claim.claim_id
          const shortText = claim.text.length > 80 ? claim.text.slice(0, 77) + '...' : claim.text

          return (
            <Box
              key={claim.claim_id}
              p={2}
              rounded="md"
              bg="bg.secondary"
              cursor="pointer"
              onClick={() => setExpandedId(isExpanded ? null : claim.claim_id)}
              _hover={{ bg: 'bg.hover' }}
              transition="all 0.15s"
              borderLeft="2px solid"
              borderLeftColor={isExpanded ? `${CLAIM_TYPE_COLORS[claim.claim_type] || 'gray'}.400` : 'transparent'}
            >
              <HStack align="start" spacing={2}>
                <Box mt={0.5} color="text.muted" flexShrink={0}>
                  <Icon as={isExpanded ? FiChevronDown : FiChevronRight} boxSize={3} />
                </Box>
                <Box flex={1} minW={0}>
                  <HStack mb={1} spacing={1}>
                    <Badge
                      colorScheme={CLAIM_TYPE_COLORS[claim.claim_type] || 'gray'}
                      fontSize="9px"
                      px={1}
                    >
                      {claim.claim_type}
                    </Badge>
                  </HStack>
                  <Text color="text.secondary" fontSize="xs">
                    {isExpanded ? claim.text : shortText}
                  </Text>
                  {isExpanded && (
                    <HStack mt={2} spacing={3} pt={2} borderTop="1px" borderColor="border.default">
                      <Text color="text.muted" fontSize="9px">
                        Confiance : {Math.round((claim.confidence || 0) * 100)}%
                      </Text>
                      {claim.source_title && (
                        <Text color="text.muted" fontSize="9px" noOfLines={1}>
                          Source : {claim.source_title}
                        </Text>
                      )}
                    </HStack>
                  )}
                </Box>
              </HStack>
            </Box>
          )
        })}
      </VStack>
    </Box>
  )
}
