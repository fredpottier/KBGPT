'use client'

/**
 * S3.E — Relations Explorer V3.3
 *
 * Mini-runtime UI pour explorer les LOGICAL_RELATION typées V3.3.
 * Theme-aware : utilise les CSS variables du preset (Fusion / Dark Elegance).
 */

import { useState, useEffect, useCallback } from 'react'
import {
  Box,
  Text,
  VStack,
  HStack,
  Badge,
  Spinner,
  Icon,
  SimpleGrid,
  Button,
  Tag,
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
  FiBookOpen,
  FiCheckCircle,
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

// ── Mapping type → CSS variables thématiques ───────────────────────────
// Utilise les tokens sémantiques du preset (success/error/warning/info/accent)
// pour s'adapter automatiquement au theme actif (Fusion light/dark, Dark Elegance).

type SemanticColor = 'success' | 'error' | 'warning' | 'info' | 'accent' | 'neutral'

const TYPE_SEMANTIC: Record<string, { color: SemanticColor; icon: typeof FiInfo; label: string }> = {
  CONFLICT:      { color: 'error',   icon: FiAlertTriangle, label: 'CONFLICT' },
  EQUIVALENT:    { color: 'success', icon: FiCheckCircle,   label: 'EQUIVALENT' },
  REAFFIRMS:     { color: 'success', icon: FiCheck,         label: 'REAFFIRMS' },
  OVERLAP:       { color: 'warning', icon: FiActivity,      label: 'OVERLAP' },
  EXCEPTION:     { color: 'warning', icon: FiZap,           label: 'EXCEPTION' },
  SUBSET:        { color: 'info',    icon: FiArrowRight,    label: 'SUBSET' },
  SUPERSET:      { color: 'info',    icon: FiArrowRight,    label: 'SUPERSET' },
  DEFINITION_OF: { color: 'accent',  icon: FiBookOpen,      label: 'DEFINITION_OF' },
  SUPERSEDES:    { color: 'accent',  icon: FiClock,         label: 'SUPERSEDES' },
  EVOLVES_FROM:  { color: 'accent',  icon: FiClock,         label: 'EVOLVES_FROM' },
  DISJOINT:      { color: 'neutral', icon: FiFilter,        label: 'DISJOINT' },
  UNRELATED:     { color: 'neutral', icon: FiFilter,        label: 'UNRELATED' },
}

// CSS variable tokens par couleur sémantique
const SEMANTIC_TOKENS: Record<SemanticColor, { bg: string; bgHover: string; fg: string; border: string }> = {
  success: { bg: 'var(--success-soft)', bgHover: 'var(--success-soft)', fg: 'var(--success-base)', border: 'var(--success-border)' },
  error:   { bg: 'var(--error-soft)',   bgHover: 'var(--error-soft)',   fg: 'var(--error-base)',   border: 'var(--error-border)' },
  warning: { bg: 'var(--warning-soft)', bgHover: 'var(--warning-soft)', fg: 'var(--warning-base)', border: 'var(--warning-border)' },
  info:    { bg: 'var(--info-soft)',    bgHover: 'var(--info-soft)',    fg: 'var(--info-base)',    border: 'var(--info-border)' },
  accent:  { bg: 'var(--accent-soft)',  bgHover: 'var(--accent-soft)',  fg: 'var(--accent)',       border: 'var(--accent)' },
  neutral: { bg: 'var(--bg-surface-alt)', bgHover: 'var(--bg-surface-alt)', fg: 'var(--fg-secondary)', border: 'var(--border-default)' },
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

  useEffect(() => { fetchStats() }, [fetchStats])
  useEffect(() => {
    if (selectedType) fetchDrilldown(selectedType, { contradictionsOnly, confidenceMin })
  }, [selectedType, contradictionsOnly, confidenceMin, fetchDrilldown])

  // ── Render helpers ───────────────────────────────────────────────────

  const renderStatCard = (label: string, value: string | number, helpText: string, semantic: SemanticColor = 'neutral') => {
    const tokens = SEMANTIC_TOKENS[semantic]
    return (
      <Box
        bg={tokens.bg}
        color={tokens.fg}
        p={5}
        borderRadius="lg"
        border="1px solid"
        borderColor={tokens.border}
      >
        <Text fontSize="sm" fontWeight="medium" mb={1} opacity={0.85}>{label}</Text>
        <Text fontSize="3xl" fontWeight="bold" lineHeight="1">
          {typeof value === 'number' ? value.toLocaleString() : value}
        </Text>
        <Text fontSize="xs" mt={1} opacity={0.75}>{helpText}</Text>
      </Box>
    )
  }

  const renderTypeCard = (stat: RelationTypeStat) => {
    const meta = TYPE_SEMANTIC[stat.type] || { color: 'neutral' as SemanticColor, icon: FiInfo, label: stat.type }
    const tokens = SEMANTIC_TOKENS[meta.color]
    const isSelected = selectedType === stat.type
    return (
      <Box
        key={stat.type}
        bg={tokens.bg}
        color={tokens.fg}
        p={4}
        borderRadius="lg"
        cursor="pointer"
        border="2px solid"
        borderColor={isSelected ? tokens.border : 'transparent'}
        _hover={{ borderColor: tokens.border, transform: 'translateY(-1px)' }}
        transition="all 0.15s"
        onClick={() => setSelectedType(stat.type)}
      >
        <HStack justify="space-between" mb={2}>
          <Icon as={meta.icon} boxSize={5} />
          <Text fontSize="xs" fontWeight="bold" letterSpacing="wide">{meta.label}</Text>
        </HStack>
        <Text fontSize="3xl" fontWeight="bold" lineHeight="1">{stat.count.toLocaleString()}</Text>
        <Text fontSize="xs" mt={2} opacity={0.85}>
          conf: {stat.avg_confidence.toFixed(2)} · {stat.sample_strong}S/{stat.sample_weak}W/{stat.sample_uncertain}U
        </Text>
        {stat.contradictions > 0 && (
          <Box mt={2} bg="var(--error-base)" color="var(--error-on)" px={2} py={1} borderRadius="md" fontSize="xs" fontWeight="bold" textAlign="center">
            {stat.contradictions} contradictions
          </Box>
        )}
      </Box>
    )
  }

  const renderRelationCard = (rel: RelationDetail) => {
    const meta = TYPE_SEMANTIC[rel.type] || { color: 'neutral' as SemanticColor, icon: FiInfo, label: rel.type }
    const tokens = SEMANTIC_TOKENS[meta.color]
    return (
      <Box
        key={`${rel.a_claim_id}-${rel.b_claim_id}`}
        bg="var(--bg-surface)"
        p={4}
        borderRadius="md"
        border="1px solid"
        borderColor={rel.is_contradiction ? 'var(--error-base)' : 'var(--border-default)'}
      >
        <HStack mb={3} flexWrap="wrap" gap={2}>
          <Box bg={tokens.bg} color={tokens.fg} px={2} py={1} borderRadius="md" fontSize="xs" fontWeight="bold">
            {rel.type}
          </Box>
          <Tag size="sm" bg="var(--bg-surface-alt)" color="var(--fg-secondary)">{rel.strength}</Tag>
          <Tooltip label="Confidence × strength_weight (kg_trust brut)">
            <Tag size="sm" bg="var(--accent-soft)" color="var(--accent)">kg_trust: {rel.kg_trust.toFixed(2)}</Tag>
          </Tooltip>
          <Tag size="sm" bg="var(--bg-surface-alt)" color="var(--fg-secondary)">conf: {rel.confidence.toFixed(2)}</Tag>
          {rel.is_contradiction && (
            <Box bg="var(--error-base)" color="var(--error-on)" px={2} py={1} borderRadius="md" fontSize="xs" fontWeight="bold">
              <Icon as={FiAlertTriangle} mr={1} />
              VRAIE CONTRADICTION
            </Box>
          )}
          {rel.scope_alignment && (
            <Tag size="sm" bg="var(--bg-surface-alt)" color="var(--fg-muted)">scope: {rel.scope_alignment}</Tag>
          )}
          {rel.temporal_relation && (
            <Tag size="sm" bg="var(--bg-surface-alt)" color="var(--fg-muted)">temp: {rel.temporal_relation}</Tag>
          )}
        </HStack>

        <SimpleGrid columns={{ base: 1, md: 2 }} spacing={3} mb={3}>
          <Box bg="var(--bg-surface-alt)" p={3} borderRadius="md">
            <Text fontSize="xs" color="var(--fg-muted)" mb={1}>
              <strong>A</strong> · doc: <Box as="code" bg="var(--bg-canvas)" px={1} borderRadius="sm">{rel.a_doc_id}</Box>
              {rel.a_publication_date && <> · pub: {rel.a_publication_date}</>}
              {rel.a_validity_start && <> · valid_from: {rel.a_validity_start}</>}
            </Text>
            <Text fontSize="sm" color="var(--fg-primary)">{rel.a_text}</Text>
          </Box>
          <Box bg="var(--bg-surface-alt)" p={3} borderRadius="md">
            <Text fontSize="xs" color="var(--fg-muted)" mb={1}>
              <strong>B</strong> · doc: <Box as="code" bg="var(--bg-canvas)" px={1} borderRadius="sm">{rel.b_doc_id}</Box>
              {rel.b_publication_date && <> · pub: {rel.b_publication_date}</>}
              {rel.b_validity_start && <> · valid_from: {rel.b_validity_start}</>}
            </Text>
            <Text fontSize="sm" color="var(--fg-primary)">{rel.b_text}</Text>
          </Box>
        </SimpleGrid>

        {rel.reasoning && (
          <Box bg="var(--bg-surface-alt)" p={3} borderRadius="md" mt={2}>
            <Text fontSize="xs" color="var(--fg-muted)" mb={1}><strong>Reasoning</strong></Text>
            <Text fontSize="sm" fontStyle="italic" color="var(--fg-secondary)">{rel.reasoning}</Text>
          </Box>
        )}

        {rel.contradiction_reason && (
          <Text fontSize="xs" color="var(--fg-muted)" mt={2}>
            <strong>contradiction_reason:</strong> {rel.contradiction_reason}
          </Text>
        )}
      </Box>
    )
  }

  // ── Render ───────────────────────────────────────────────────────────

  return (
    <Box p={6} maxW="1400px" mx="auto" color="var(--fg-primary)">
      <VStack align="stretch" spacing={6}>
        <Box>
          <HStack mb={2}>
            <Icon as={FiBarChart2} boxSize={6} color="var(--accent)" />
            <Text fontSize="2xl" fontWeight="bold">Relations Explorer V3.3</Text>
          </HStack>
          <Text fontSize="sm" color="var(--fg-muted)">
            Distribution des LOGICAL_RELATION typées V3.3 (S3.E mini-runtime). Cliquez sur un type pour drill-down.
          </Text>
        </Box>

        {statsLoading && <Spinner color="var(--accent)" />}
        {statsError && (
          <Box bg="var(--error-soft)" color="var(--error-base)" p={4} borderRadius="md">
            Erreur : {statsError}
          </Box>
        )}
        {stats && (
          <>
            <SimpleGrid columns={{ base: 2, md: 3 }} spacing={4}>
              {renderStatCard(
                'Total LOGICAL_RELATION V3.3',
                stats.total,
                'edges logiques typées',
                'accent'
              )}
              {renderStatCard(
                'Vraies contradictions',
                stats.true_contradictions,
                'CONFLICT + is_contradiction=true + conf ≥ 0.85',
                'error'
              )}
              {renderStatCard(
                'Types détectés',
                stats.by_type.length,
                'sur 12 types V3.3 possibles',
                'success'
              )}
            </SimpleGrid>

            <Box>
              <Text fontSize="lg" fontWeight="semibold" mb={3}>Distribution par type</Text>
              <SimpleGrid columns={{ base: 2, md: 4, lg: 6 }} spacing={3}>
                {stats.by_type.map(renderTypeCard)}
              </SimpleGrid>
            </Box>
          </>
        )}

        {selectedType && (
          <Box>
            <HStack mb={4} justify="space-between" flexWrap="wrap" gap={2}>
              <HStack>
                <Text fontSize="lg" fontWeight="semibold">Drill-down : {selectedType}</Text>
                {drilldown && (
                  <Tag size="md" bg="var(--bg-surface-alt)" color="var(--fg-secondary)">
                    {drilldown.total.toLocaleString()} total
                  </Tag>
                )}
              </HStack>
              <HStack flexWrap="wrap" gap={2}>
                <Button
                  size="sm"
                  bg={contradictionsOnly ? 'var(--error-base)' : 'var(--bg-surface-alt)'}
                  color={contradictionsOnly ? 'var(--error-on)' : 'var(--fg-primary)'}
                  borderColor="var(--error-base)"
                  borderWidth="1px"
                  _hover={{ bg: contradictionsOnly ? 'var(--error-base)' : 'var(--error-soft)' }}
                  onClick={() => setContradictionsOnly(!contradictionsOnly)}
                >
                  {contradictionsOnly ? '✓ Vraies contradictions' : 'Vraies contradictions'}
                </Button>
                <Button
                  size="sm"
                  bg={confidenceMin > 0 ? 'var(--accent)' : 'var(--bg-surface-alt)'}
                  color={confidenceMin > 0 ? 'var(--accent-on)' : 'var(--fg-primary)'}
                  borderColor="var(--accent)"
                  borderWidth="1px"
                  _hover={{ bg: confidenceMin > 0 ? 'var(--accent-hover)' : 'var(--accent-soft)' }}
                  onClick={() => setConfidenceMin(confidenceMin > 0 ? 0.0 : 0.85)}
                >
                  conf ≥ {confidenceMin > 0 ? '0.85' : 'all'}
                </Button>
                <Button
                  size="sm"
                  bg="var(--bg-surface-alt)"
                  color="var(--fg-primary)"
                  _hover={{ bg: 'var(--bg-hover, var(--bg-surface-alt))' }}
                  onClick={() => setSelectedType(null)}
                >
                  Fermer
                </Button>
              </HStack>
            </HStack>

            {drilldownLoading && <Spinner color="var(--accent)" />}
            {!drilldownLoading && drilldown && drilldown.relations.length === 0 && (
              <Text color="var(--fg-muted)">Aucune relation pour ces filtres.</Text>
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
