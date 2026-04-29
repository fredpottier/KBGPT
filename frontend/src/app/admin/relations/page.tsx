'use client'

/**
 * S3.E — Relations Explorer V3.3
 *
 * Mini-runtime UI pour explorer les LOGICAL_RELATION typées V3.3 :
 * - Distribution des 12 types
 * - Drill-down par type avec top 20 paires (triées par confidence)
 * - Filtre vraies contradictions (CONFLICT + is_contradiction=true + conf >= 0.85)
 * - Affichage kg_trust brut (confidence × strength_weight)
 *
 * Backend : /api/admin/relations/stats, /by_type/{type}, /conflicts
 */

import { useState, useEffect, useCallback } from 'react'
import {
  Box,
  Text,
  VStack,
  HStack,
  Flex,
  Badge,
  Spinner,
  Icon,
  SimpleGrid,
  Button,
  Tag,
  Stat,
  StatLabel,
  StatNumber,
  StatHelpText,
  Divider,
  Tooltip,
} from '@chakra-ui/react'
import {
  FiAlertTriangle,
  FiCheck,
  FiArrowRight,
  FiActivity,
  FiBarChart2,
  FiClock,
  FiZap,
  FiInfo,
  FiFilter,
} from 'react-icons/fi'

const API_BASE_URL = typeof window !== 'undefined'
  ? (process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000')
  : 'http://localhost:8000'

const getAuthHeaders = () => ({
  'Content-Type': 'application/json',
  Authorization: `Bearer ${localStorage.getItem('auth_token') || ''}`,
})

// ── Types ──────────────────────────────────────────────────────────────

interface RelationTypeStat {
  type: string
  count: number
  contradictions: number
  avg_confidence: number
  sample_strong: number
  sample_weak: number
  sample_uncertain: number
}

interface RelationsStatsResponse {
  total: number
  by_type: RelationTypeStat[]
  legacy_remaining: number
  true_contradictions: number
}

interface RelationDetail {
  a_claim_id: string
  a_text: string
  a_doc_id: string
  a_publication_date: string | null
  a_validity_start: string | null
  b_claim_id: string
  b_text: string
  b_doc_id: string
  b_publication_date: string | null
  b_validity_start: string | null
  type: string
  strength: string
  confidence: number
  is_contradiction: boolean
  contradiction_reason: string | null
  scope_alignment: string | null
  temporal_relation: string | null
  reasoning: string
  extracted_at: string | null
  kg_trust: number
}

interface RelationsByTypeResponse {
  type: string
  total: number
  relations: RelationDetail[]
}

// ── Couleurs par type ───────────────────────────────────────────────────

const TYPE_COLORS: Record<string, { bg: string; text: string; icon: typeof FiInfo }> = {
  CONFLICT: { bg: 'red.900', text: 'red.100', icon: FiAlertTriangle },
  EQUIVALENT: { bg: 'green.900', text: 'green.100', icon: FiCheck },
  OVERLAP: { bg: 'orange.900', text: 'orange.100', icon: FiActivity },
  SUBSET: { bg: 'blue.900', text: 'blue.100', icon: FiArrowRight },
  SUPERSET: { bg: 'blue.900', text: 'blue.100', icon: FiArrowRight },
  EXCEPTION: { bg: 'purple.900', text: 'purple.100', icon: FiZap },
  DEFINITION_OF: { bg: 'teal.900', text: 'teal.100', icon: FiInfo },
  SUPERSEDES: { bg: 'cyan.900', text: 'cyan.100', icon: FiClock },
  EVOLVES_FROM: { bg: 'cyan.900', text: 'cyan.100', icon: FiClock },
  REAFFIRMS: { bg: 'green.900', text: 'green.100', icon: FiCheck },
  DISJOINT: { bg: 'gray.700', text: 'gray.100', icon: FiFilter },
  UNRELATED: { bg: 'gray.700', text: 'gray.100', icon: FiFilter },
}

// ── Component ──────────────────────────────────────────────────────────

export default function RelationsExplorerPage() {
  const [stats, setStats] = useState<RelationsStatsResponse | null>(null)
  const [statsLoading, setStatsLoading] = useState(true)
  const [statsError, setStatsError] = useState<string | null>(null)

  const [selectedType, setSelectedType] = useState<string | null>(null)
  const [drilldown, setDrilldown] = useState<RelationsByTypeResponse | null>(null)
  const [drilldownLoading, setDrilldownLoading] = useState(false)
  const [contradictionsOnly, setContradictionsOnly] = useState(false)
  const [confidenceMin, setConfidenceMin] = useState(0.0)

  // Fetch stats
  const fetchStats = useCallback(async () => {
    setStatsLoading(true)
    setStatsError(null)
    try {
      const res = await fetch(`${API_BASE_URL}/api/admin/relations/stats`, {
        headers: getAuthHeaders(),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: RelationsStatsResponse = await res.json()
      setStats(data)
    } catch (e: any) {
      setStatsError(e?.message || 'Erreur fetch stats')
    } finally {
      setStatsLoading(false)
    }
  }, [])

  // Fetch drilldown
  const fetchDrilldown = useCallback(
    async (type: string, opts: { contradictionsOnly?: boolean; confidenceMin?: number } = {}) => {
      setDrilldownLoading(true)
      try {
        const params = new URLSearchParams({
          limit: '20',
          confidence_min: String(opts.confidenceMin ?? 0.0),
          contradictions_only: String(opts.contradictionsOnly ?? false),
        })
        const res = await fetch(
          `${API_BASE_URL}/api/admin/relations/by_type/${type}?${params}`,
          { headers: getAuthHeaders() }
        )
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const data: RelationsByTypeResponse = await res.json()
        setDrilldown(data)
      } catch (e: any) {
        setDrilldown(null)
      } finally {
        setDrilldownLoading(false)
      }
    },
    []
  )

  useEffect(() => {
    fetchStats()
  }, [fetchStats])

  useEffect(() => {
    if (selectedType) {
      fetchDrilldown(selectedType, { contradictionsOnly, confidenceMin })
    }
  }, [selectedType, contradictionsOnly, confidenceMin, fetchDrilldown])

  // ── Render helpers ───────────────────────────────────────────────────

  const renderTypeCard = (stat: RelationTypeStat) => {
    const color = TYPE_COLORS[stat.type] || { bg: 'gray.800', text: 'gray.100', icon: FiInfo }
    const isSelected = selectedType === stat.type
    return (
      <Box
        key={stat.type}
        bg={color.bg}
        color={color.text}
        p={4}
        borderRadius="lg"
        cursor="pointer"
        border={isSelected ? '2px solid' : '1px solid'}
        borderColor={isSelected ? 'white' : 'whiteAlpha.300'}
        _hover={{ transform: 'translateY(-2px)', shadow: 'lg' }}
        transition="all 0.15s"
        onClick={() => setSelectedType(stat.type)}
      >
        <HStack justify="space-between" mb={2}>
          <Icon as={color.icon} boxSize={5} />
          <Badge colorScheme="whiteAlpha" variant="solid">{stat.type}</Badge>
        </HStack>
        <Text fontSize="3xl" fontWeight="bold">{stat.count.toLocaleString()}</Text>
        <Text fontSize="xs" opacity={0.85}>
          conf moy: {stat.avg_confidence.toFixed(2)} · {stat.sample_strong}S/{stat.sample_weak}W/{stat.sample_uncertain}U
        </Text>
        {stat.contradictions > 0 && (
          <Badge colorScheme="red" variant="solid" mt={2}>
            {stat.contradictions} contradictions
          </Badge>
        )}
      </Box>
    )
  }

  const renderRelationCard = (rel: RelationDetail) => {
    const color = TYPE_COLORS[rel.type] || { bg: 'gray.800', text: 'gray.100', icon: FiInfo }
    return (
      <Box
        key={`${rel.a_claim_id}-${rel.b_claim_id}`}
        bg="gray.800"
        p={4}
        borderRadius="md"
        border="1px solid"
        borderColor={rel.is_contradiction ? 'red.500' : 'whiteAlpha.200'}
      >
        <HStack mb={2} flexWrap="wrap">
          <Badge bg={color.bg} color={color.text} fontSize="sm">{rel.type}</Badge>
          <Badge colorScheme={rel.strength === 'STRONG' ? 'green' : rel.strength === 'WEAK' ? 'yellow' : 'gray'}>
            {rel.strength}
          </Badge>
          <Tooltip label="Confidence × strength_weight (kg_trust brut)">
            <Tag size="sm" colorScheme="blue">kg_trust: {rel.kg_trust.toFixed(2)}</Tag>
          </Tooltip>
          <Tag size="sm">conf: {rel.confidence.toFixed(2)}</Tag>
          {rel.is_contradiction && (
            <Badge colorScheme="red" variant="solid">
              <Icon as={FiAlertTriangle} mr={1} />
              VRAIE CONTRADICTION
            </Badge>
          )}
          {rel.scope_alignment && <Tag size="sm" colorScheme="purple">scope: {rel.scope_alignment}</Tag>}
          {rel.temporal_relation && <Tag size="sm" colorScheme="cyan">temp: {rel.temporal_relation}</Tag>}
        </HStack>

        <SimpleGrid columns={{ base: 1, md: 2 }} spacing={3} mb={3}>
          <Box bg="blackAlpha.400" p={3} borderRadius="md">
            <Text fontSize="xs" color="gray.400" mb={1}>
              <strong>A</strong> · doc: <code>{rel.a_doc_id}</code>
              {rel.a_publication_date && <> · pub: {rel.a_publication_date}</>}
              {rel.a_validity_start && <> · valid_from: {rel.a_validity_start}</>}
            </Text>
            <Text fontSize="sm">{rel.a_text}</Text>
          </Box>
          <Box bg="blackAlpha.400" p={3} borderRadius="md">
            <Text fontSize="xs" color="gray.400" mb={1}>
              <strong>B</strong> · doc: <code>{rel.b_doc_id}</code>
              {rel.b_publication_date && <> · pub: {rel.b_publication_date}</>}
              {rel.b_validity_start && <> · valid_from: {rel.b_validity_start}</>}
            </Text>
            <Text fontSize="sm">{rel.b_text}</Text>
          </Box>
        </SimpleGrid>

        {rel.reasoning && (
          <Box bg="blackAlpha.300" p={3} borderRadius="md" mt={2}>
            <Text fontSize="xs" color="gray.300" mb={1}><strong>Reasoning</strong></Text>
            <Text fontSize="sm" fontStyle="italic" color="gray.200">{rel.reasoning}</Text>
          </Box>
        )}

        {rel.contradiction_reason && (
          <Text fontSize="xs" color="gray.400" mt={2}>
            <strong>contradiction_reason:</strong> {rel.contradiction_reason}
          </Text>
        )}
      </Box>
    )
  }

  // ── Render ───────────────────────────────────────────────────────────

  return (
    <Box p={6} maxW="1400px" mx="auto">
      <VStack align="stretch" spacing={6}>
        <Box>
          <HStack mb={2}>
            <Icon as={FiBarChart2} boxSize={6} />
            <Text fontSize="2xl" fontWeight="bold">Relations Explorer V3.3</Text>
          </HStack>
          <Text fontSize="sm" color="gray.400">
            Distribution des LOGICAL_RELATION typées V3.3 (S3.E mini-runtime). Cliquez sur un type pour drill-down.
          </Text>
        </Box>

        {/* Top stats */}
        {statsLoading && <Spinner />}
        {statsError && <Text color="red.300">Erreur : {statsError}</Text>}
        {stats && (
          <>
            <SimpleGrid columns={{ base: 2, md: 4 }} spacing={4}>
              <Stat bg="gray.800" p={4} borderRadius="md">
                <StatLabel color="gray.400">Total LOGICAL_RELATION V3.3</StatLabel>
                <StatNumber>{stats.total.toLocaleString()}</StatNumber>
                <StatHelpText fontSize="xs">edges typées (legacy exclues)</StatHelpText>
              </Stat>
              <Stat bg="red.900" p={4} borderRadius="md">
                <StatLabel color="red.200">Vraies contradictions</StatLabel>
                <StatNumber color="white">{stats.true_contradictions}</StatNumber>
                <StatHelpText fontSize="xs" color="red.200">
                  CONFLICT + is_contradiction=true + conf ≥ 0.85
                </StatHelpText>
              </Stat>
              <Stat bg="gray.800" p={4} borderRadius="md">
                <StatLabel color="gray.400">Edges legacy V0</StatLabel>
                <StatNumber>{stats.legacy_remaining.toLocaleString()}</StatNumber>
                <StatHelpText fontSize="xs">CONTRADICTS/REFINES/QUALIFIES (exclues du runtime)</StatHelpText>
              </Stat>
              <Stat bg="gray.800" p={4} borderRadius="md">
                <StatLabel color="gray.400">Réduction du bruit</StatLabel>
                <StatNumber>
                  {stats.legacy_remaining > 0
                    ? `${(stats.legacy_remaining / Math.max(stats.true_contradictions, 1)).toFixed(0)}×`
                    : '—'}
                </StatNumber>
                <StatHelpText fontSize="xs">legacy / vraies contradictions</StatHelpText>
              </Stat>
            </SimpleGrid>

            <Divider />

            {/* Distribution par type */}
            <Box>
              <Text fontSize="lg" fontWeight="semibold" mb={3}>Distribution par type</Text>
              <SimpleGrid columns={{ base: 2, md: 4, lg: 6 }} spacing={3}>
                {stats.by_type.map(renderTypeCard)}
              </SimpleGrid>
            </Box>
          </>
        )}

        <Divider />

        {/* Drill-down */}
        {selectedType && (
          <Box>
            <HStack mb={4} justify="space-between" flexWrap="wrap">
              <HStack>
                <Text fontSize="lg" fontWeight="semibold">Drill-down : {selectedType}</Text>
                {drilldown && <Badge>{drilldown.total.toLocaleString()} total</Badge>}
              </HStack>
              <HStack>
                <Button
                  size="sm"
                  variant={contradictionsOnly ? 'solid' : 'outline'}
                  colorScheme="red"
                  onClick={() => setContradictionsOnly(!contradictionsOnly)}
                >
                  {contradictionsOnly ? 'Vraies contradictions ✓' : 'Vraies contradictions'}
                </Button>
                <Button
                  size="sm"
                  variant={confidenceMin > 0 ? 'solid' : 'outline'}
                  onClick={() => setConfidenceMin(confidenceMin > 0 ? 0.0 : 0.85)}
                >
                  conf ≥ {confidenceMin > 0 ? '0.85' : 'all'}
                </Button>
                <Button size="sm" onClick={() => setSelectedType(null)}>Fermer</Button>
              </HStack>
            </HStack>

            {drilldownLoading && <Spinner />}
            {!drilldownLoading && drilldown && drilldown.relations.length === 0 && (
              <Text color="gray.400">Aucune relation pour ces filtres.</Text>
            )}
            <VStack align="stretch" spacing={3}>
              {drilldown?.relations.map(renderRelationCard)}
            </VStack>
          </Box>
        )}
      </VStack>
    </Box>
  )
}
