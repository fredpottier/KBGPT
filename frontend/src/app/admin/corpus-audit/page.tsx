'use client'

/**
 * Corpus Audit Report — Radiographie de la base documentaire.
 *
 * Score de sante, top contradictions, zones a risque, recommandations.
 */

import { useState, useEffect, useCallback } from 'react'
import {
  Box,
  Text,
  VStack,
  HStack,
  SimpleGrid,
  Badge,
  Spinner,
  Icon,
  Progress,
  Flex,
  Link,
} from '@chakra-ui/react'
import NextLink from 'next/link'
import {
  FiActivity,
  FiFileText,
  FiDatabase,
  FiLayers,
  FiAlertTriangle,
  FiSlash,
  FiInfo,
  FiClock,
  FiHelpCircle,
  FiTarget,
  FiEdit3,
  FiCheckCircle,
  FiChevronRight,
} from 'react-icons/fi'

const API_BASE_URL = typeof window !== 'undefined'
  ? (process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000')
  : 'http://localhost:8000'

const getAuthHeaders = () => ({
  'Content-Type': 'application/json',
  Authorization: `Bearer ${localStorage.getItem('auth_token') || ''}`,
})

// ── Types ──────────────────────────────────────────────────────────────

interface AuditClaim {
  text: string
  doc_id: string
  verbatim: string
}

interface AuditContradiction {
  claim1: AuditClaim
  claim2: AuditClaim
  tension_nature: string
  tension_level: string
  entities: string[]
}

interface ContradictionHotspot {
  name: string
  contradictions: number
}

interface ContradictionType {
  type: string
  count: number
}

interface BlindSpot {
  type: string
  domain: string
  detail: string
  severity: string
}

interface ArticleToWrite {
  name: string
  claims: number
  docs: number
}

interface ScoreDetail {
  label: string
  description: string
  score: number
  max: number
  is_penalty?: boolean
}

interface CorpusStats {
  total_documents: number
  total_claims: number
  total_entities: number
  total_articles: number
  coverage_pct: number
}

interface AuditData {
  health_score: number
  score_details: ScoreDetail[]
  stats: CorpusStats
  total_contradictions: number
  total_hard_contradictions: number
  top_contradictions: AuditContradiction[]
  contradiction_hotspots: ContradictionHotspot[]
  contradiction_types: ContradictionType[]
  blind_spots: BlindSpot[]
  articles_to_write: ArticleToWrite[]
}

// ── Config ─────────────────────────────────────────────────────────────

const NATURE_LABELS: Record<string, { label: string; icon: any; color: string }> = {
  value_conflict: { label: 'Conflit de valeur', icon: FiSlash, color: 'red.400' },
  scope_conflict: { label: 'Variation de scope', icon: FiInfo, color: 'blue.400' },
  temporal_conflict: { label: 'Evolution temporelle', icon: FiClock, color: 'orange.400' },
  methodological: { label: 'Methodologique', icon: FiHelpCircle, color: 'purple.400' },
  complementary: { label: 'Complementaire', icon: FiLayers, color: 'green.400' },
  unclassified: { label: 'Non classifie', icon: FiHelpCircle, color: 'gray.400' },
}

// ── Score Gauge ────────────────────────────────────────────────────────

function HealthGauge({ score }: { score: number }) {
  const colorHex = score >= 70 ? '#22c55e' : score >= 40 ? '#f59e0b' : '#ef4444'
  const label = score >= 70 ? 'Bon' : score >= 40 ? 'Attention' : 'Critique'
  const colorScheme = score >= 70 ? 'green' : score >= 40 ? 'orange' : 'red'

  // SVG circle arc proportional to score
  const size = 140
  const strokeWidth = 8
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  const strokeDasharray = circumference
  const strokeDashoffset = circumference * (1 - score / 100)

  return (
    <Box textAlign="center">
      <Box position="relative" w={`${size}px`} h={`${size}px`} mx="auto" mb={3}>
        <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
          {/* Background track */}
          <circle
            cx={size / 2} cy={size / 2} r={radius}
            fill="none"
            stroke="rgba(255,255,255,0.06)"
            strokeWidth={strokeWidth}
          />
          {/* Score arc */}
          <circle
            cx={size / 2} cy={size / 2} r={radius}
            fill="none"
            stroke={colorHex}
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            strokeDasharray={strokeDasharray}
            strokeDashoffset={strokeDashoffset}
            style={{ transition: 'stroke-dashoffset 1s ease-out' }}
          />
        </svg>
        {/* Score number (centered over SVG) */}
        <Flex position="absolute" inset={0} align="center" justify="center" direction="column">
          <Text fontSize="3xl" fontWeight="800" color={colorHex}>
            {score}
          </Text>
          <Text fontSize="xs" color="var(--text-muted)" mt={-1}>/100</Text>
        </Flex>
      </Box>
      <Badge colorScheme={colorScheme} fontSize="xs" px={3} py={1}>
        {label}
      </Badge>
    </Box>
  )
}

// ── Stat Card ──────────────────────────────────────────────────────────

function StatCard({ icon, label, value, color }: { icon: any; label: string; value: string | number; color: string }) {
  return (
    <Box bg="var(--bg-secondary)" borderRadius="xl" p={4} borderWidth="1px" borderColor="var(--border-default)">
      <HStack spacing={3}>
        <Icon as={icon} color={color} boxSize={5} />
        <Box>
          <Text fontSize="xl" fontWeight="700" color="var(--text-primary)">{value}</Text>
          <Text fontSize="xs" color="var(--text-muted)">{label}</Text>
        </Box>
      </HStack>
    </Box>
  )
}

// ── Main Page ──────────────────────────────────────────────────────────

export default function CorpusAuditPage() {
  const [data, setData] = useState<AuditData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE_URL}/api/corpus-intelligence/audit`, { headers: getAuthHeaders() })
      if (!res.ok) throw new Error('Erreur chargement')
      setData(await res.json())
    } catch (err: any) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  if (loading) {
    return (
      <VStack py={20} spacing={4}>
        <Spinner size="lg" color="brand.400" thickness="3px" />
        <Text color="var(--text-muted)" fontSize="sm">Audit du corpus en cours...</Text>
      </VStack>
    )
  }

  if (error || !data) {
    return (
      <Box bg="rgba(239, 68, 68, 0.08)" border="1px solid rgba(239, 68, 68, 0.2)" borderRadius="xl" p={6}>
        <Text color="red.400">{error || 'Erreur inconnue'}</Text>
      </Box>
    )
  }

  const formatDocId = (docId: string) => {
    let label = docId
    if (label.includes('_')) {
      const parts = label.split('_')
      if (parts.length > 2 && parts[parts.length - 1].length >= 8) parts.pop()
      if (parts[0].startsWith('PMC')) parts[0] = `PMC ${parts[0].slice(3)}`
      label = parts.slice(0, 5).join(' ').replace(/_/g, ' ')
      if (label.length > 40) label = label.slice(0, 37) + '...'
    }
    return label
  }

  return (
    <Box>
      {/* Header */}
      <VStack align="start" spacing={1} mb={6}>
        <HStack spacing={3}>
          <Icon as={FiActivity} color="brand.400" boxSize={5} />
          <Text fontSize="xl" fontWeight="700" color="var(--text-primary)">
            Audit du Corpus
          </Text>
        </HStack>
        <Text fontSize="sm" color="var(--text-muted)">
          Radiographie de la sante et de la coherence de la base documentaire
        </Text>
      </VStack>

      {/* Stats cards */}
      <SimpleGrid columns={{ base: 2, md: 4 }} spacing={3} mb={6}>
        <StatCard icon={FiFileText} label="Documents analyses" value={data.stats.total_documents} color="brand.400" />
        <StatCard icon={FiDatabase} label="Claims extraites" value={data.stats.total_claims.toLocaleString()} color="green.400" />
        <StatCard icon={FiLayers} label="Articles generes" value={data.stats.total_articles} color="purple.400" />
        <StatCard icon={FiAlertTriangle} label="Contradictions" value={`${data.total_contradictions} (${data.total_hard_contradictions} dures)`} color="orange.400" />
      </SimpleGrid>

      {/* Score de qualite avec details */}
      <Box bg="var(--bg-secondary)" borderRadius="xl" p={5} borderWidth="1px" borderColor="var(--border-default)" mb={8}>
        <HStack spacing={6} align="start">
          <HealthGauge score={data.health_score} />
          <Box flex={1}>
            <Text fontSize="sm" fontWeight="600" color="var(--text-primary)" mb={3}>
              Decomposition du score de qualite
            </Text>
            <VStack spacing={2} align="stretch">
              {(data.score_details || []).map((detail, i) => (
                <HStack key={i} spacing={3} justify="space-between">
                  <Box flex={1}>
                    <HStack spacing={2}>
                      <Text fontSize="sm" color="var(--text-primary)" fontWeight="500">
                        {detail.label}
                      </Text>
                      <Text
                        fontSize="sm"
                        fontWeight="700"
                        color={detail.is_penalty ? 'red.400' : 'green.400'}
                      >
                        {detail.is_penalty ? detail.score : `+${detail.score}`}/{detail.max}
                      </Text>
                    </HStack>
                    <Text fontSize="xs" color="var(--text-muted)">
                      {detail.description}
                    </Text>
                  </Box>
                  <Box w="100px">
                    <Progress
                      value={detail.is_penalty ? 0 : (detail.score / detail.max) * 100}
                      size="xs"
                      borderRadius="full"
                      bg="var(--bg-primary)"
                      sx={{ '& > div': {
                        background: detail.is_penalty
                          ? 'transparent'
                          : detail.score / detail.max > 0.7
                            ? 'linear-gradient(90deg, #22c55e, #16a34a)'
                            : detail.score / detail.max > 0.4
                              ? 'linear-gradient(90deg, #f59e0b, #d97706)'
                              : 'linear-gradient(90deg, #ef4444, #dc2626)',
                      } }}
                    />
                  </Box>
                </HStack>
              ))}
            </VStack>
          </Box>
        </HStack>
      </Box>

      {/* Distribution des types de contradictions */}
      {data.contradiction_types.length > 0 && (
        <Box mb={8}>
          <Text fontSize="sm" fontWeight="600" color="var(--text-primary)" mb={3}>
            Repartition des contradictions par type
          </Text>
          <HStack spacing={3} flexWrap="wrap">
            {data.contradiction_types.map((ct) => {
              const cfg = NATURE_LABELS[ct.type] || NATURE_LABELS.unclassified
              const total = data.contradiction_types.reduce((s, c) => s + c.count, 0)
              const pct = total > 0 ? Math.round(ct.count / total * 100) : 0
              return (
                <Box key={ct.type} bg="var(--bg-secondary)" borderRadius="lg" p={3} borderWidth="1px" borderColor="var(--border-default)" minW="150px">
                  <HStack spacing={2} mb={1}>
                    <Icon as={cfg.icon} color={cfg.color} boxSize={3} />
                    <Text fontSize="xs" color="var(--text-muted)">{cfg.label}</Text>
                  </HStack>
                  <HStack spacing={2} align="baseline">
                    <Text fontSize="lg" fontWeight="700" color={cfg.color}>{ct.count}</Text>
                    <Text fontSize="xs" color="var(--text-muted)">({pct}%)</Text>
                  </HStack>
                </Box>
              )
            })}
          </HStack>
        </Box>
      )}

      {/* Top contradictions */}
      {data.top_contradictions.length > 0 && (
        <Box mb={8}>
          <HStack justify="space-between" mb={3}>
            <Text fontSize="sm" fontWeight="600" color="var(--text-primary)">
              Contradictions les plus critiques ({data.top_contradictions.length} sur {data.total_contradictions})
            </Text>
            <Link as={NextLink} href="/admin/contradictions" color="brand.300" fontSize="xs">
              Voir toutes <Icon as={FiChevronRight} boxSize={3} />
            </Link>
          </HStack>
          <VStack spacing={3} align="stretch">
            {data.top_contradictions.slice(0, 5).map((c, i) => {
              const cfg = NATURE_LABELS[c.tension_nature] || NATURE_LABELS.unclassified
              return (
                <Box key={i} bg="var(--bg-secondary)" borderRadius="lg" p={4} borderWidth="1px" borderColor="var(--border-default)"
                  borderLeftWidth="3px" borderLeftColor={cfg.color}>
                  <HStack spacing={2} mb={2}>
                    <Icon as={cfg.icon} color={cfg.color} boxSize={3} />
                    <Badge colorScheme={cfg.color.split('.')[0]} variant="subtle" fontSize="2xs">{cfg.label}</Badge>
                    {c.entities.slice(0, 2).map((e, j) => (
                      <Badge key={j} fontSize="2xs" colorScheme="brand" variant="outline">{e}</Badge>
                    ))}
                  </HStack>
                  <SimpleGrid columns={2} spacing={3}>
                    <Box>
                      <Text fontSize="xs" color="red.400" fontWeight="600" mb={1}>Source A</Text>
                      <Text fontSize="xs" color="var(--text-secondary)" noOfLines={2}>{c.claim1.text}</Text>
                      <Text fontSize="2xs" color="var(--text-muted)" mt={1}>{formatDocId(c.claim1.doc_id)}</Text>
                    </Box>
                    <Box>
                      <Text fontSize="xs" color="blue.400" fontWeight="600" mb={1}>Source B</Text>
                      <Text fontSize="xs" color="var(--text-secondary)" noOfLines={2}>{c.claim2.text}</Text>
                      <Text fontSize="2xs" color="var(--text-muted)" mt={1}>{formatDocId(c.claim2.doc_id)}</Text>
                    </Box>
                  </SimpleGrid>
                </Box>
              )
            })}
          </VStack>
        </Box>
      )}

      {/* Contradiction hotspots + Articles to write */}
      <SimpleGrid columns={{ base: 1, md: 2 }} spacing={6} mb={8}>
        {/* Hotspots */}
        {data.contradiction_hotspots.length > 0 && (
          <Box bg="var(--bg-secondary)" borderRadius="xl" p={5} borderWidth="1px" borderColor="var(--border-default)">
            <HStack spacing={2} mb={4}>
              <Icon as={FiTarget} color="orange.400" boxSize={4} />
              <Text fontSize="sm" fontWeight="600" color="var(--text-primary)">
                Concepts les plus controverses
              </Text>
            </HStack>
            <VStack spacing={2} align="stretch">
              {data.contradiction_hotspots.map((h) => (
                <HStack key={h.name} justify="space-between" py={1}>
                  <Text fontSize="sm" color="var(--text-primary)">{h.name}</Text>
                  <Badge colorScheme="orange" variant="subtle" fontSize="xs">
                    {h.contradictions} tensions
                  </Badge>
                </HStack>
              ))}
            </VStack>
          </Box>
        )}

        {/* Articles to write */}
        {data.articles_to_write.length > 0 && (
          <Box bg="var(--bg-secondary)" borderRadius="xl" p={5} borderWidth="1px" borderColor="var(--border-default)">
            <HStack spacing={2} mb={4}>
              <Icon as={FiEdit3} color="brand.400" boxSize={4} />
              <Text fontSize="sm" fontWeight="600" color="var(--text-primary)">
                Articles prioritaires a ecrire
              </Text>
            </HStack>
            <VStack spacing={2} align="stretch">
              {data.articles_to_write.map((a) => (
                <HStack key={a.name} justify="space-between" py={1}>
                  <Text fontSize="sm" color="var(--text-primary)">{a.name}</Text>
                  <HStack spacing={2}>
                    <Text fontSize="xs" color="var(--text-muted)">{a.claims} claims</Text>
                    <Text fontSize="xs" color="var(--text-muted)">{a.docs} docs</Text>
                  </HStack>
                </HStack>
              ))}
            </VStack>
          </Box>
        )}
      </SimpleGrid>

      {/* Blind spots */}
      {data.blind_spots.length > 0 && (
        <Box bg="rgba(251, 191, 36, 0.04)" borderRadius="xl" p={5} borderWidth="1px" borderColor="rgba(251, 191, 36, 0.15)">
          <HStack spacing={2} mb={3}>
            <Icon as={FiAlertTriangle} color="yellow.400" boxSize={4} />
            <Text fontSize="sm" fontWeight="600" color="yellow.400">
              Zones a surveiller
            </Text>
          </HStack>
          <VStack spacing={2} align="stretch">
            {data.blind_spots.map((spot, i) => (
              <HStack key={i} spacing={3}>
                <Icon as={FiInfo} color="yellow.500" boxSize={3} flexShrink={0} />
                <Box>
                  <Text fontSize="sm" color="var(--text-primary)" fontWeight="500">{spot.domain}</Text>
                  <Text fontSize="xs" color="var(--text-muted)">{spot.detail}</Text>
                </Box>
              </HStack>
            ))}
          </VStack>
        </Box>
      )}
    </Box>
  )
}
