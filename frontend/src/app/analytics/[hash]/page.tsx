'use client'

/**
 * OSMOS Import Analytics Detail - Compact Industrial Design
 * Dense dashboard for single import analysis
 */

import {
  Box,
  Text,
  HStack,
  Spinner,
  Center,
  Badge,
  Icon,
  Flex,
  Progress,
  IconButton,
  Tooltip,
  Grid,
  GridItem,
} from '@chakra-ui/react'
import { useParams, useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'
import {
  FiArrowLeft,
  FiClock,
  FiFileText,
  FiEye,
  FiCpu,
  FiDatabase,
  FiZap,
  FiCheckCircle,
  FiAlertTriangle,
  FiInfo,
  FiTarget,
  FiLink,
  FiTrendingUp,
  FiTrendingDown,
  FiActivity,
  FiBox,
  FiLayers,
  FiRefreshCw,
} from 'react-icons/fi'

// Types
interface PhaseMetrics {
  name: string
  duration_ms: number
  llm_calls: number
  llm_model: string | null
  details: Record<string, unknown>
}

interface GatingAnalysis {
  total_pages: number
  vision_required: number
  vision_recommended: number
  no_vision: number
  avg_vns: number
  max_vns: number
  reasons_distribution: Record<string, number>
}

interface VisionAnalysis {
  pages_processed: number
  total_elements: number
  total_relations: number
  avg_elements_per_page: number
  element_types: Record<string, number>
}

interface OsmoseAnalysis {
  proto_concepts: number
  canonical_concepts: number
  topics_segmented: number
  relations_stored: number
  phase2_relations: number
  embeddings_stored: number
}

interface DensityMetrics {
  segments_total: number
  segments_processed: number
  coverage_pct: number
  raw_relations: number
  unique_relations: number
  dup_ratio: number
  relations_per_segment: number
}

interface VaguenessMetrics {
  total_relations: number
  vague_relations: number
  vague_pct: number
  vague_types: Record<string, number>
}

interface HubMetrics {
  total_edges: number
  top1_node: string
  top1_degree: number
  top1_degree_share: number
  top10_degree_share: number
  top10_nodes: Array<{ node: string; degree: number }>
}

interface CycleMetrics {
  symmetric_pairs: number
  symmetric_ratio: number
  short_cycles_3: number
  problematic_pairs: Array<{ a: string; b: string; type: string }>
}

interface QualityReport {
  document_id: string
  verdict: 'OK' | 'TOO_PERMISSIVE' | 'TOO_RESTRICTIVE' | 'INSUFFICIENT_DATA'
  verdict_reasons: string[]
  quality_score: number
  density: DensityMetrics
  vagueness: VaguenessMetrics
  hubs: HubMetrics
  cycles: CycleMetrics
  flags: Record<string, boolean>
}

interface ImportAnalytics {
  document_id: string
  document_name: string
  file_type: string
  import_timestamp: string
  cache_used: boolean
  total_pages: number
  total_chars: number
  total_duration_ms: number
  phases: PhaseMetrics[]
  gating: GatingAnalysis | null
  vision: VisionAnalysis | null
  osmose: OsmoseAnalysis | null
  quality_score: number
  quality_notes: string[]
}

// Utility functions
const formatDuration = (ms: number) => {
  if (ms < 1000) return `${ms.toFixed(0)}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${(ms / 60000).toFixed(1)}min`
}

const formatChars = (chars: number) => {
  if (chars > 1000000) return `${(chars / 1000000).toFixed(1)}M`
  if (chars > 1000) return `${(chars / 1000).toFixed(0)}K`
  return chars.toString()
}

// Compact metric card
const MetricCard = ({ label, value, icon, color = 'gray', tooltip }: { label: string; value: string | number; icon: any; color?: string; tooltip?: string }) => (
  <Tooltip label={tooltip} placement="top" hasArrow isDisabled={!tooltip}>
    <Box bg="whiteAlpha.50" border="1px solid" borderColor={`${color}.800`} rounded="lg" px={3} py={2} cursor={tooltip ? 'help' : 'default'}>
      <HStack spacing={2}>
        <Box w={7} h={7} rounded="md" bg={`${color}.900`} display="flex" alignItems="center" justifyContent="center">
          <Icon as={icon} boxSize={3.5} color={`${color}.400`} />
        </Box>
        <Box>
          <Text fontSize="lg" fontWeight="bold" color="text.primary" fontFamily="mono" lineHeight={1}>{value}</Text>
          <Text fontSize="xs" color="text.muted" lineHeight={1.2}>{label}</Text>
        </Box>
      </HStack>
    </Box>
  </Tooltip>
)

// Compact inline stat
const StatItem = ({ label, value, color = 'gray' }: { label: string; value: string | number; color?: string }) => (
  <HStack spacing={1.5} px={2} py={1} bg="whiteAlpha.50" rounded="md">
    <Text fontSize="xs" fontWeight="bold" fontFamily="mono" color={`${color}.300`}>{value}</Text>
    <Text fontSize="xs" color="text.muted">{label}</Text>
  </HStack>
)

// Phase colors (contrasting colors for adjacent phases)
const PHASE_COLORS: Record<string, string> = {
  'Docling Extraction': 'blue',
  'Vision Gating': 'pink',
  'Vision Analysis': 'green',
  'Structured Merge': 'orange',
  'Linearization': 'cyan',
}

// Stacked timeline bar
const PhasesTimeline = ({ phases }: { phases: PhaseMetrics[] }) => {
  const totalDuration = phases.reduce((sum, p) => sum + p.duration_ms, 0)
  const MIN_WIDTH_PX = 3 // Minimum visible width for tiny phases

  return (
    <Box>
      {/* Stacked bar */}
      <Tooltip
        label={phases.map(p => `${p.name}: ${formatDuration(p.duration_ms)}`).join(' → ')}
        placement="top"
        hasArrow
      >
        <Flex h={3} rounded="full" overflow="hidden" bg="whiteAlpha.100" cursor="help">
          {phases.map((phase, i) => {
            const pct = (phase.duration_ms / totalDuration) * 100
            const color = PHASE_COLORS[phase.name] || 'gray'
            return (
              <Tooltip key={phase.name} label={`${phase.name}: ${formatDuration(phase.duration_ms)}`} placement="top" hasArrow>
                <Box
                  bg={`${color}.400`}
                  h="full"
                  minW={`${MIN_WIDTH_PX}px`}
                  flex={pct > 1 ? pct : undefined}
                  w={pct <= 1 ? `${MIN_WIDTH_PX}px` : undefined}
                  borderRight={i < phases.length - 1 ? '1px solid' : 'none'}
                  borderColor="whiteAlpha.300"
                  transition="all 0.2s"
                  _hover={{ filter: 'brightness(1.2)' }}
                />
              </Tooltip>
            )
          })}
        </Flex>
      </Tooltip>

      {/* Legend - vertical */}
      <Box mt={2}>
        {phases.map((phase) => {
          const color = PHASE_COLORS[phase.name] || 'gray'
          return (
            <HStack key={phase.name} spacing={2} py={0.5}>
              <Box w={2} h={2} rounded="sm" bg={`${color}.400`} flexShrink={0} />
              <Text fontSize="xs" color="text.muted" flex={1}>{phase.name}</Text>
              <Text fontSize="xs" fontFamily="mono" color="text.primary" fontWeight="medium">
                {formatDuration(phase.duration_ms)}
              </Text>
            </HStack>
          )
        })}
      </Box>
    </Box>
  )
}

// Quality pill
const QualityPill = ({ label, value, color, tooltip }: { label: string; value: string | number; color: string; tooltip?: string }) => (
  <Tooltip label={tooltip} placement="top" hasArrow isDisabled={!tooltip}>
    <HStack spacing={1.5} px={2} py={0.5} bg={`${color}.900`} border="1px solid" borderColor={`${color}.700`} rounded="md" cursor={tooltip ? 'help' : 'default'}>
      <Box w={2} h={2} rounded="full" bg={`${color}.400`} />
      <Text fontSize="xs" fontWeight="bold" fontFamily="mono" color={`${color}.300`}>{value}</Text>
      <Text fontSize="xs" color={`${color}.400`}>{label}</Text>
    </HStack>
  </Tooltip>
)

export default function AnalyticsDetailPage() {
  const params = useParams()
  const router = useRouter()
  const hash = params.hash as string
  const [analytics, setAnalytics] = useState<ImportAnalytics | null>(null)
  const [quality, setQuality] = useState<QualityReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const getAuthHeaders = () => ({
    'Content-Type': 'application/json',
    Authorization: `Bearer ${localStorage.getItem('auth_token') || ''}`,
  })

  const fetchAnalytics = async () => {
    try {
      setLoading(true)
      const response = await fetch(`/api/analytics/imports/${hash}`, {
        headers: getAuthHeaders(),
        credentials: 'include',
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const data: ImportAnalytics = await response.json()
      setAnalytics(data)
      if (data.document_id) fetchQuality(data.document_id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }

  const fetchQuality = async (documentId: string) => {
    try {
      const response = await fetch(`/api/analytics/quality/${encodeURIComponent(documentId)}`, {
        headers: getAuthHeaders(),
        credentials: 'include',
      })
      if (response.ok) {
        const data: QualityReport = await response.json()
        setQuality(data)
      }
    } catch (err) {
      console.error('Failed to fetch quality data:', err)
    }
  }

  useEffect(() => { if (hash) fetchAnalytics() }, [hash])

  if (loading) {
    return <Center h="200px"><Spinner size="md" color="brand.500" /></Center>
  }

  if (error) {
    return (
      <Box maxW="1400px" mx="auto" p={3}>
        <Box bg="red.900" border="1px solid" borderColor="red.600" rounded="lg" p={3} textAlign="center">
          <Text fontSize="sm" color="red.300">Erreur: {error}</Text>
        </Box>
      </Box>
    )
  }

  if (!analytics) return null

  const totalDuration = analytics.total_duration_ms || analytics.phases.reduce((t, p) => t + p.duration_ms, 0)
  const totalLLMCalls = analytics.phases.reduce((t, p) => t + p.llm_calls, 0)

  return (
    <Box maxW="1400px" mx="auto" p={3}>
      {/* Header */}
      <Flex justify="space-between" align="center" mb={3}>
        <HStack spacing={3}>
          <IconButton aria-label="Back" icon={<FiArrowLeft />} size="sm" variant="ghost" onClick={() => router.push('/analytics')} />
          <Box w={8} h={8} rounded="lg" bgGradient="linear(to-br, brand.500, cyan.500)" display="flex" alignItems="center" justifyContent="center">
            <Icon as={FiActivity} boxSize={4} color="white" />
          </Box>
          <Box>
            <Text fontSize="lg" fontWeight="bold" color="text.primary" lineHeight={1} noOfLines={1} maxW="500px">
              {analytics.document_name}
            </Text>
            <Text fontSize="xs" color="text.muted">ID: {analytics.document_id}</Text>
          </Box>
        </HStack>
        <HStack spacing={2}>
          <Badge colorScheme="blue" textTransform="uppercase" fontSize="xs">{analytics.file_type}</Badge>
          <Tooltip
            label={
              analytics.quality_notes && analytics.quality_notes.length > 0
                ? analytics.quality_notes.join(' • ')
                : analytics.quality_score >= 90
                  ? "Extraction excellente"
                  : "Détails dans la section Notes ci-dessous"
            }
            placement="bottom"
            hasArrow
            maxW="400px"
          >
            <Badge colorScheme={analytics.quality_score >= 70 ? 'green' : analytics.quality_score >= 50 ? 'yellow' : 'red'} fontSize="xs" cursor="help">
              Score: {analytics.quality_score}%
            </Badge>
          </Tooltip>
          <IconButton aria-label="Refresh" icon={<FiRefreshCw />} size="sm" variant="ghost" onClick={fetchAnalytics} />
        </HStack>
      </Flex>

      {/* Main Metrics Row */}
      <Flex gap={3} mb={3} flexWrap="wrap">
        <MetricCard label="Pages" value={analytics.total_pages} icon={FiFileText} color="blue" />
        <MetricCard label="Caracteres" value={formatChars(analytics.total_chars)} icon={FiDatabase} color="purple" />
        <MetricCard label="Duree" value={formatDuration(totalDuration)} icon={FiClock} color="orange" />
        <MetricCard label="Appels LLM" value={totalLLMCalls} icon={FiZap} color="cyan" tooltip="Appels Vision GPT-4o" />
      </Flex>

      {/* Two Column Layout */}
      <Grid templateColumns={{ base: '1fr', lg: '1fr 1fr' }} gap={3} mb={3}>
        {/* Phases */}
        <GridItem>
          <Box bg="whiteAlpha.50" rounded="lg" p={3} border="1px solid" borderColor="whiteAlpha.100" h="full">
            <HStack mb={2}>
              <Icon as={FiClock} boxSize={3.5} color="brand.400" />
              <Text fontSize="sm" fontWeight="semibold" color="text.primary">Phases de traitement</Text>
              <Text fontSize="xs" color="text.muted" fontFamily="mono">({formatDuration(totalDuration)} total)</Text>
            </HStack>
            <PhasesTimeline phases={analytics.phases} />
          </Box>
        </GridItem>

        {/* Vision Gating + Vision Analysis */}
        <GridItem>
          <Box bg="whiteAlpha.50" rounded="lg" p={3} border="1px solid" borderColor="whiteAlpha.100" h="full">
            {analytics.gating && (
              <>
                <HStack mb={2}>
                  <Icon as={FiEye} boxSize={3.5} color="purple.400" />
                  <Text fontSize="sm" fontWeight="semibold" color="text.primary">Vision Gating</Text>
                </HStack>
                <Flex gap={2} mb={2} flexWrap="wrap">
                  <StatItem label="No Vision" value={analytics.gating.no_vision} color="green" />
                  <StatItem label="Recommended" value={analytics.gating.vision_recommended} color="yellow" />
                  <StatItem label="Required" value={analytics.gating.vision_required} color="orange" />
                </Flex>
                <HStack spacing={4} fontSize="xs" color="text.muted" mb={3}>
                  <Text>VNS moy: <Text as="span" fontFamily="mono" color="text.primary">{analytics.gating.avg_vns.toFixed(3)}</Text></Text>
                  <Text>VNS max: <Text as="span" fontFamily="mono" color="text.primary">{analytics.gating.max_vns.toFixed(3)}</Text></Text>
                </HStack>
              </>
            )}

            {analytics.vision && (
              <>
                <HStack mb={2} mt={analytics.gating ? 2 : 0} pt={analytics.gating ? 2 : 0} borderTop={analytics.gating ? '1px solid' : 'none'} borderColor="whiteAlpha.100">
                  <Icon as={FiCpu} boxSize={3.5} color="orange.400" />
                  <Text fontSize="sm" fontWeight="semibold" color="text.primary">Vision GPT-4o</Text>
                </HStack>
                <Flex gap={2} flexWrap="wrap">
                  <StatItem label="pages" value={analytics.vision.pages_processed} color="orange" />
                  <StatItem label="elements" value={analytics.vision.total_elements} color="cyan" />
                  <StatItem label="relations" value={analytics.vision.total_relations} color="purple" />
                  <StatItem label="elem/page" value={analytics.vision.avg_elements_per_page.toFixed(1)} color="gray" />
                </Flex>
              </>
            )}

            {!analytics.gating && !analytics.vision && (
              <Text fontSize="xs" color="text.muted">Pas de donnees Vision</Text>
            )}
          </Box>
        </GridItem>
      </Grid>

      {/* OSMOSE Row */}
      {analytics.osmose && (
        <Box bg="whiteAlpha.50" rounded="lg" p={3} mb={3} border="1px solid" borderColor="whiteAlpha.100">
          <HStack mb={2}>
            <Icon as={FiDatabase} boxSize={3.5} color="cyan.400" />
            <Text fontSize="sm" fontWeight="semibold" color="text.primary">OSMOSE - Knowledge Graph</Text>
          </HStack>
          <Flex gap={3} flexWrap="wrap">
            <MetricCard label="Proto Concepts" value={analytics.osmose.proto_concepts} icon={FiBox} color="yellow" />
            <MetricCard label="Canonical" value={analytics.osmose.canonical_concepts} icon={FiLayers} color="green" />
            <MetricCard label="Relations" value={analytics.osmose.relations_stored} icon={FiLink} color="purple" />
            <MetricCard label="Embeddings" value={analytics.osmose.embeddings_stored} icon={FiTarget} color="orange" />
            {analytics.osmose.topics_segmented > 0 && (
              <MetricCard label="Topics" value={analytics.osmose.topics_segmented} icon={FiActivity} color="cyan" />
            )}
          </Flex>
        </Box>
      )}

      {/* Quality Report */}
      {quality && (
        <Box bg="whiteAlpha.50" rounded="lg" p={3} border="1px solid" borderColor={
          quality.verdict === 'OK' ? 'green.600' :
          quality.verdict === 'TOO_PERMISSIVE' ? 'red.600' :
          quality.verdict === 'TOO_RESTRICTIVE' ? 'yellow.600' : 'whiteAlpha.100'
        }>
          <Flex justify="space-between" align="center" mb={2}>
            <HStack>
              <Icon as={FiActivity} boxSize={3.5} color="brand.400" />
              <Text fontSize="sm" fontWeight="semibold" color="text.primary">Qualite Enrichissement</Text>
            </HStack>
            <HStack spacing={2}>
              <Badge colorScheme={
                quality.verdict === 'OK' ? 'green' :
                quality.verdict === 'TOO_PERMISSIVE' ? 'red' :
                quality.verdict === 'TOO_RESTRICTIVE' ? 'yellow' : 'gray'
              } fontSize="xs">
                {quality.verdict === 'OK' ? 'OK' :
                 quality.verdict === 'TOO_PERMISSIVE' ? 'Trop Permissif' :
                 quality.verdict === 'TOO_RESTRICTIVE' ? 'Trop Restrictif' : 'Donnees Insuffisantes'}
              </Badge>
              <Badge colorScheme={quality.quality_score >= 70 ? 'green' : quality.quality_score >= 50 ? 'yellow' : 'red'} fontSize="xs">
                {quality.quality_score}%
              </Badge>
            </HStack>
          </Flex>

          {/* Verdict reasons */}
          {quality.verdict_reasons.length > 0 && (
            <Box bg="whiteAlpha.50" rounded="md" p={2} mb={2}>
              {quality.verdict_reasons.map((reason, i) => (
                <HStack key={i} spacing={1.5} mb={i < quality.verdict_reasons.length - 1 ? 1 : 0}>
                  <Icon
                    as={reason.includes('OK') ? FiCheckCircle : reason.includes('Trop') || reason.includes('eleve') ? FiAlertTriangle : FiInfo}
                    boxSize={3}
                    color={reason.includes('OK') ? 'green.400' : reason.includes('Trop') || reason.includes('eleve') ? 'red.400' : 'blue.400'}
                  />
                  <Text fontSize="xs" color="text.primary">{reason}</Text>
                </HStack>
              ))}
            </Box>
          )}

          {/* Quality Metrics Grid */}
          <Grid templateColumns={{ base: 'repeat(2, 1fr)', md: 'repeat(4, 1fr)' }} gap={2} mb={2}>
            <Box bg="whiteAlpha.50" rounded="md" p={2}>
              <HStack spacing={1} mb={1}>
                <Icon as={FiTarget} boxSize={3} color="blue.400" />
                <Text fontSize="xs" color="text.muted">Couverture</Text>
              </HStack>
              <Text fontSize="lg" fontWeight="bold" fontFamily="mono" color={
                quality.density.coverage_pct >= 20 ? 'green.400' : quality.density.coverage_pct >= 10 ? 'yellow.400' : 'red.400'
              }>{quality.density.coverage_pct.toFixed(1)}%</Text>
              <Text fontSize="xs" color="text.muted">{quality.density.segments_processed}/{quality.density.segments_total}</Text>
            </Box>

            <Box bg="whiteAlpha.50" rounded="md" p={2}>
              <HStack spacing={1} mb={1}>
                <Icon as={FiLink} boxSize={3} color="purple.400" />
                <Text fontSize="xs" color="text.muted">Dedup Ratio</Text>
              </HStack>
              <Text fontSize="lg" fontWeight="bold" fontFamily="mono" color={
                quality.density.dup_ratio <= 0.30 ? 'green.400' : quality.density.dup_ratio <= 0.50 ? 'yellow.400' : 'red.400'
              }>{(quality.density.dup_ratio * 100).toFixed(0)}%</Text>
              <Text fontSize="xs" color="text.muted">{quality.density.unique_relations}/{quality.density.raw_relations}</Text>
            </Box>

            <Box bg="whiteAlpha.50" rounded="md" p={2}>
              <HStack spacing={1} mb={1}>
                <Icon as={FiTrendingDown} boxSize={3} color="orange.400" />
                <Text fontSize="xs" color="text.muted">Vague</Text>
              </HStack>
              <Text fontSize="lg" fontWeight="bold" fontFamily="mono" color={
                quality.vagueness.vague_pct <= 15 ? 'green.400' : quality.vagueness.vague_pct <= 30 ? 'yellow.400' : 'red.400'
              }>{quality.vagueness.vague_pct.toFixed(1)}%</Text>
              <Text fontSize="xs" color="text.muted">{quality.vagueness.vague_relations} vagues</Text>
            </Box>

            <Box bg="whiteAlpha.50" rounded="md" p={2}>
              <HStack spacing={1} mb={1}>
                <Icon as={FiTrendingUp} boxSize={3} color="cyan.400" />
                <Text fontSize="xs" color="text.muted">Hub Top1</Text>
              </HStack>
              <Text fontSize="lg" fontWeight="bold" fontFamily="mono" color={
                quality.hubs.top1_degree_share <= 0.10 ? 'green.400' : quality.hubs.top1_degree_share <= 0.20 ? 'yellow.400' : 'red.400'
              }>{(quality.hubs.top1_degree_share * 100).toFixed(1)}%</Text>
              <Text fontSize="xs" color="text.muted" noOfLines={1}>{quality.hubs.top1_node?.substring(0, 15) || '-'}</Text>
            </Box>
          </Grid>

          {/* Additional stats row */}
          <Flex gap={2} flexWrap="wrap">
            <QualityPill label="rel/seg" value={quality.density.relations_per_segment.toFixed(1)} color="blue" />
            <QualityPill label="symetriques" value={quality.cycles.symmetric_pairs} color={quality.cycles.symmetric_pairs === 0 ? 'green' : 'yellow'} />
            <QualityPill label="edges" value={quality.hubs.total_edges} color="purple" />
            {Object.entries(quality.flags).filter(([_, v]) => v).map(([flag]) => (
              <Badge key={flag} colorScheme={flag.includes('high') || flag.includes('hub') ? 'red' : 'yellow'} variant="subtle" fontSize="xs">
                {flag.replace(/_/g, ' ')}
              </Badge>
            ))}
          </Flex>
        </Box>
      )}

      {/* Quality Notes */}
      {analytics.quality_notes && analytics.quality_notes.length > 0 && (
        <Box bg="whiteAlpha.50" rounded="lg" p={3} mt={3} border="1px solid" borderColor="whiteAlpha.100">
          <HStack mb={2}>
            <Icon as={FiInfo} boxSize={3.5} color="brand.400" />
            <Text fontSize="sm" fontWeight="semibold" color="text.primary">Notes</Text>
          </HStack>
          <Flex gap={2} flexWrap="wrap">
            {analytics.quality_notes.map((note, i) => (
              <HStack key={i} px={2} py={1} bg="whiteAlpha.50" rounded="md" spacing={1.5}>
                <Icon
                  as={note.includes('OK') || note.includes('riche') ? FiCheckCircle : note.includes('Peu') || note.includes('pauvre') ? FiAlertTriangle : FiInfo}
                  boxSize={3}
                  color={note.includes('OK') || note.includes('riche') ? 'green.400' : note.includes('Peu') || note.includes('pauvre') ? 'yellow.400' : 'blue.400'}
                />
                <Text fontSize="xs" color="text.primary">{note}</Text>
              </HStack>
            ))}
          </Flex>
        </Box>
      )}
    </Box>
  )
}
