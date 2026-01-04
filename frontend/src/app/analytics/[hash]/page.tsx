'use client'

/**
 * OSMOS Import Analytics Detail - Dark Elegance Edition
 *
 * Dashboard analytique complet d'un import
 */

import {
  Box,
  Text,
  VStack,
  HStack,
  Spinner,
  Center,
  SimpleGrid,
  Badge,
  Button,
  Icon,
  Flex,
  Progress,
  Divider,
} from '@chakra-ui/react'
import { motion } from 'framer-motion'
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
  FiActivity,
  FiTrendingUp,
  FiTrendingDown,
  FiTarget,
  FiLink,
} from 'react-icons/fi'

const MotionBox = motion(Box)

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

// === Pass 2 Quality Types ===
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

const PHASE_COLORS: Record<string, string> = {
  'Docling Extraction': 'blue.400',
  'Vision Gating': 'purple.400',
  'Vision Analysis': 'orange.400',
  'Structured Merge': 'green.400',
  'Linearization': 'cyan.400',
}

const formatDuration = (ms: number) => {
  if (ms < 1000) return `${ms.toFixed(0)}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${(ms / 60000).toFixed(1)}min`
}

const StatCard = ({
  title,
  value,
  subtitle,
  icon,
  color = 'brand.500',
}: {
  title: string
  value: string | number
  subtitle?: string
  icon: any
  color?: string
}) => (
  <Box
    bg="bg.secondary"
    border="1px solid"
    borderColor="border.default"
    rounded="xl"
    p={5}
    _hover={{ borderColor: color, transform: 'translateY(-2px)' }}
    transition="all 0.2s"
  >
    <HStack justify="space-between" mb={3}>
      <Box p={2} bg="bg.tertiary" rounded="lg">
        <Icon as={icon} boxSize={5} color={color} />
      </Box>
    </HStack>
    <Text fontSize="2xl" fontWeight="bold" color="text.primary">
      {value}
    </Text>
    <Text fontSize="sm" color="text.muted">
      {title}
    </Text>
    {subtitle && (
      <Text fontSize="xs" color="text.muted" mt={1}>
        {subtitle}
      </Text>
    )}
  </Box>
)

const PhaseBar = ({ phase, maxDuration }: { phase: PhaseMetrics; maxDuration: number }) => {
  const percentage = (phase.duration_ms / maxDuration) * 100
  const color = PHASE_COLORS[phase.name] || 'gray.400'

  return (
    <Box mb={4}>
      <Flex justify="space-between" mb={1}>
        <HStack>
          <Text fontSize="sm" color="text.primary" fontWeight="medium">
            {phase.name}
          </Text>
          {phase.llm_calls > 0 && (
            <Badge colorScheme="orange" size="sm" variant="subtle">
              {phase.llm_calls} appels {phase.llm_model || 'LLM'}
            </Badge>
          )}
        </HStack>
        <Text fontSize="sm" color="text.muted">
          {formatDuration(phase.duration_ms)}
        </Text>
      </Flex>
      <Progress
        value={percentage}
        size="sm"
        rounded="full"
        bg="bg.tertiary"
        sx={{
          '& > div': {
            background: color,
          },
        }}
      />
    </Box>
  )
}

export default function AnalyticsDetailPage() {
  const params = useParams()
  const router = useRouter()
  const hash = params.hash as string
  const [analytics, setAnalytics] = useState<ImportAnalytics | null>(null)
  const [quality, setQuality] = useState<QualityReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [qualityLoading, setQualityLoading] = useState(false)
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
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }
      const data: ImportAnalytics = await response.json()
      setAnalytics(data)

      // Fetch quality data using document_id
      if (data.document_id) {
        fetchQuality(data.document_id)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }

  const fetchQuality = async (documentId: string) => {
    try {
      setQualityLoading(true)
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
    } finally {
      setQualityLoading(false)
    }
  }

  useEffect(() => {
    if (hash) {
      fetchAnalytics()
    }
  }, [hash])

  const maxDuration = analytics?.phases?.reduce((max, p) => Math.max(max, p.duration_ms), 0) || 1

  return (
    <Box minH="100vh" bg="bg.primary" pt={20} px={6} pb={10}>
      <Box maxW="1400px" mx="auto">
        {/* Header */}
        <MotionBox
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
        >
          <HStack mb={8}>
            <Button
              leftIcon={<FiArrowLeft />}
              variant="ghost"
              color="text.secondary"
              onClick={() => router.push('/analytics')}
              _hover={{ bg: 'bg.hover' }}
            >
              Retour
            </Button>
          </HStack>
        </MotionBox>

        {loading ? (
          <Center h="400px">
            <VStack spacing={4}>
              <Spinner size="xl" color="brand.500" thickness="3px" />
              <Text color="text.muted">Chargement des analytics...</Text>
            </VStack>
          </Center>
        ) : error ? (
          <Box
            bg="error.500/10"
            border="1px solid"
            borderColor="error.500"
            rounded="xl"
            p={6}
            textAlign="center"
          >
            <Text color="error.400">Erreur: {error}</Text>
            <Button mt={4} onClick={fetchAnalytics} colorScheme="red" variant="outline">
              Reessayer
            </Button>
          </Box>
        ) : analytics ? (
          <VStack spacing={6} align="stretch">
            {/* Document Info */}
            <MotionBox
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              bg="bg.secondary"
              border="1px solid"
              borderColor="border.default"
              rounded="xl"
              p={6}
            >
              <Flex justify="space-between" align="start" flexWrap="wrap" gap={4}>
                <VStack align="start" spacing={1}>
                  <HStack>
                    <Icon as={FiFileText} color="brand.400" />
                    <Text fontSize="xl" fontWeight="bold" color="text.primary">
                      {analytics.document_name}
                    </Text>
                    <Badge colorScheme="blue" textTransform="uppercase">
                      {analytics.file_type}
                    </Badge>
                  </HStack>
                  <Text fontSize="sm" color="text.muted">
                    ID: {analytics.document_id}
                  </Text>
                </VStack>
                <HStack>
                  <Badge
                    colorScheme={analytics.quality_score >= 70 ? 'green' : analytics.quality_score >= 50 ? 'yellow' : 'red'}
                    fontSize="lg"
                    px={3}
                    py={1}
                    rounded="lg"
                  >
                    Score: {analytics.quality_score}%
                  </Badge>
                </HStack>
              </Flex>
            </MotionBox>

            {/* Stats Cards */}
            <SimpleGrid columns={{ base: 2, md: 4 }} spacing={4}>
              <StatCard
                title="Pages"
                value={analytics.total_pages}
                icon={FiFileText}
                color="blue.400"
              />
              <StatCard
                title="Caracteres"
                value={`${(analytics.total_chars / 1000).toFixed(0)}K`}
                icon={FiDatabase}
                color="purple.400"
              />
              <StatCard
                title="Duree totale"
                value={formatDuration(analytics.total_duration_ms || analytics.phases.reduce((t, p) => t + p.duration_ms, 0))}
                icon={FiClock}
                color="orange.400"
              />
              <StatCard
                title="Appels LLM"
                value={analytics.phases.reduce((t, p) => t + p.llm_calls, 0)}
                subtitle="Vision GPT-4o"
                icon={FiZap}
                color="cyan.400"
              />
            </SimpleGrid>

            {/* Phases Timeline */}
            <MotionBox
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1 }}
              bg="bg.secondary"
              border="1px solid"
              borderColor="border.default"
              rounded="xl"
              p={6}
            >
              <HStack mb={4}>
                <Icon as={FiClock} color="brand.400" />
                <Text fontSize="lg" fontWeight="semibold" color="text.primary">
                  Phases de traitement
                </Text>
              </HStack>
              {analytics.phases.map((phase) => (
                <PhaseBar key={phase.name} phase={phase} maxDuration={maxDuration} />
              ))}
            </MotionBox>

            {/* Two Column Layout */}
            <SimpleGrid columns={{ base: 1, lg: 2 }} spacing={6}>
              {/* Vision Gating */}
              {analytics.gating && (
                <MotionBox
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.2 }}
                  bg="bg.secondary"
                  border="1px solid"
                  borderColor="border.default"
                  rounded="xl"
                  p={6}
                >
                  <HStack mb={4}>
                    <Icon as={FiEye} color="purple.400" />
                    <Text fontSize="lg" fontWeight="semibold" color="text.primary">
                      Vision Gating
                    </Text>
                  </HStack>
                  <SimpleGrid columns={3} spacing={4} mb={4}>
                    <Box textAlign="center" p={3} bg="bg.tertiary" rounded="lg">
                      <Text fontSize="xl" fontWeight="bold" color="green.400">
                        {analytics.gating.no_vision}
                      </Text>
                      <Text fontSize="xs" color="text.muted">No Vision</Text>
                    </Box>
                    <Box textAlign="center" p={3} bg="bg.tertiary" rounded="lg">
                      <Text fontSize="xl" fontWeight="bold" color="yellow.400">
                        {analytics.gating.vision_recommended}
                      </Text>
                      <Text fontSize="xs" color="text.muted">Recommended</Text>
                    </Box>
                    <Box textAlign="center" p={3} bg="bg.tertiary" rounded="lg">
                      <Text fontSize="xl" fontWeight="bold" color="orange.400">
                        {analytics.gating.vision_required}
                      </Text>
                      <Text fontSize="xs" color="text.muted">Required</Text>
                    </Box>
                  </SimpleGrid>
                  <Divider borderColor="border.default" my={4} />
                  <HStack justify="space-between">
                    <Text fontSize="sm" color="text.muted">VNS moyen</Text>
                    <Text fontSize="sm" color="text.primary" fontWeight="medium">
                      {analytics.gating.avg_vns.toFixed(3)}
                    </Text>
                  </HStack>
                  <HStack justify="space-between" mt={2}>
                    <Text fontSize="sm" color="text.muted">VNS max</Text>
                    <Text fontSize="sm" color="text.primary" fontWeight="medium">
                      {analytics.gating.max_vns.toFixed(3)}
                    </Text>
                  </HStack>
                </MotionBox>
              )}

              {/* Vision Analysis */}
              {analytics.vision && (
                <MotionBox
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.25 }}
                  bg="bg.secondary"
                  border="1px solid"
                  borderColor="border.default"
                  rounded="xl"
                  p={6}
                >
                  <HStack mb={4}>
                    <Icon as={FiCpu} color="orange.400" />
                    <Text fontSize="lg" fontWeight="semibold" color="text.primary">
                      Vision GPT-4o
                    </Text>
                  </HStack>
                  <SimpleGrid columns={2} spacing={4} mb={4}>
                    <Box textAlign="center" p={3} bg="bg.tertiary" rounded="lg">
                      <Text fontSize="xl" fontWeight="bold" color="text.primary">
                        {analytics.vision.pages_processed}
                      </Text>
                      <Text fontSize="xs" color="text.muted">Pages traitees</Text>
                    </Box>
                    <Box textAlign="center" p={3} bg="bg.tertiary" rounded="lg">
                      <Text fontSize="xl" fontWeight="bold" color="text.primary">
                        {analytics.vision.avg_elements_per_page.toFixed(1)}
                      </Text>
                      <Text fontSize="xs" color="text.muted">Elements/page</Text>
                    </Box>
                  </SimpleGrid>
                  <Divider borderColor="border.default" my={4} />
                  <HStack justify="space-between">
                    <Text fontSize="sm" color="text.muted">Elements extraits</Text>
                    <Text fontSize="sm" color="text.primary" fontWeight="medium">
                      {analytics.vision.total_elements}
                    </Text>
                  </HStack>
                  <HStack justify="space-between" mt={2}>
                    <Text fontSize="sm" color="text.muted">Relations detectees</Text>
                    <Text fontSize="sm" color="text.primary" fontWeight="medium">
                      {analytics.vision.total_relations}
                    </Text>
                  </HStack>
                </MotionBox>
              )}
            </SimpleGrid>

            {/* OSMOSE */}
            {analytics.osmose && (
              <MotionBox
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.3 }}
                bg="bg.secondary"
                border="1px solid"
                borderColor="border.default"
                rounded="xl"
                p={6}
              >
                <HStack mb={4}>
                  <Icon as={FiDatabase} color="cyan.400" />
                  <Text fontSize="lg" fontWeight="semibold" color="text.primary">
                    OSMOSE - Knowledge Graph
                  </Text>
                </HStack>
                <SimpleGrid columns={{ base: 2, md: 4 }} spacing={4}>
                  <Box textAlign="center" p={4} bg="bg.tertiary" rounded="lg">
                    <Text fontSize="2xl" fontWeight="bold" color="cyan.400">
                      {analytics.osmose.proto_concepts}
                    </Text>
                    <Text fontSize="sm" color="text.muted">Proto Concepts</Text>
                  </Box>
                  <Box textAlign="center" p={4} bg="bg.tertiary" rounded="lg">
                    <Text fontSize="2xl" fontWeight="bold" color="green.400">
                      {analytics.osmose.canonical_concepts}
                    </Text>
                    <Text fontSize="sm" color="text.muted">Canonical Concepts</Text>
                  </Box>
                  <Box textAlign="center" p={4} bg="bg.tertiary" rounded="lg">
                    <Text fontSize="2xl" fontWeight="bold" color="purple.400">
                      {analytics.osmose.relations_stored}
                    </Text>
                    <Text fontSize="sm" color="text.muted">Relations</Text>
                  </Box>
                  <Box textAlign="center" p={4} bg="bg.tertiary" rounded="lg">
                    <Text fontSize="2xl" fontWeight="bold" color="orange.400">
                      {analytics.osmose.embeddings_stored}
                    </Text>
                    <Text fontSize="sm" color="text.muted">Embeddings</Text>
                  </Box>
                </SimpleGrid>
              </MotionBox>
            )}

            {/* Pass 2 Quality Metrics */}
            {quality && (
              <MotionBox
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.35 }}
                bg="bg.secondary"
                border="1px solid"
                borderColor={
                  quality.verdict === 'OK' ? 'green.500' :
                  quality.verdict === 'TOO_PERMISSIVE' ? 'red.500' :
                  quality.verdict === 'TOO_RESTRICTIVE' ? 'yellow.500' :
                  'border.default'
                }
                rounded="xl"
                p={6}
              >
                <Flex justify="space-between" align="center" mb={4}>
                  <HStack>
                    <Icon as={FiActivity} color="brand.400" />
                    <Text fontSize="lg" fontWeight="semibold" color="text.primary">
                      Qualite Pass 2
                    </Text>
                  </HStack>
                  <Badge
                    colorScheme={
                      quality.verdict === 'OK' ? 'green' :
                      quality.verdict === 'TOO_PERMISSIVE' ? 'red' :
                      quality.verdict === 'TOO_RESTRICTIVE' ? 'yellow' :
                      'gray'
                    }
                    fontSize="md"
                    px={3}
                    py={1}
                    rounded="lg"
                  >
                    {quality.verdict === 'OK' ? 'OK' :
                     quality.verdict === 'TOO_PERMISSIVE' ? 'Trop Permissif' :
                     quality.verdict === 'TOO_RESTRICTIVE' ? 'Trop Restrictif' :
                     'Donnees Insuffisantes'}
                  </Badge>
                </Flex>

                {/* Verdict Reasons */}
                {quality.verdict_reasons.length > 0 && (
                  <Box mb={4} p={3} bg="bg.tertiary" rounded="lg">
                    {quality.verdict_reasons.map((reason, i) => (
                      <HStack key={i} mb={i < quality.verdict_reasons.length - 1 ? 2 : 0}>
                        <Icon
                          as={reason.includes('OK') ? FiCheckCircle :
                              reason.includes('Trop') || reason.includes('eleve') ? FiAlertTriangle :
                              FiInfo}
                          color={reason.includes('OK') ? 'green.400' :
                                 reason.includes('Trop') || reason.includes('eleve') ? 'red.400' :
                                 'blue.400'}
                          boxSize={4}
                        />
                        <Text fontSize="sm" color="text.primary">{reason}</Text>
                      </HStack>
                    ))}
                  </Box>
                )}

                {/* Quality Score */}
                <Box mb={4}>
                  <Flex justify="space-between" mb={1}>
                    <Text fontSize="sm" color="text.muted">Score Qualite</Text>
                    <Text fontSize="sm" fontWeight="bold" color={
                      quality.quality_score >= 70 ? 'green.400' :
                      quality.quality_score >= 50 ? 'yellow.400' :
                      'red.400'
                    }>
                      {quality.quality_score}%
                    </Text>
                  </Flex>
                  <Progress
                    value={quality.quality_score}
                    size="sm"
                    rounded="full"
                    bg="bg.tertiary"
                    sx={{
                      '& > div': {
                        background: quality.quality_score >= 70 ? 'green.400' :
                                    quality.quality_score >= 50 ? 'yellow.400' : 'red.400',
                      },
                    }}
                  />
                </Box>

                <Divider borderColor="border.default" my={4} />

                {/* Metrics Grid */}
                <SimpleGrid columns={{ base: 2, md: 4 }} spacing={4}>
                  {/* Density */}
                  <Box p={3} bg="bg.tertiary" rounded="lg">
                    <HStack mb={2}>
                      <Icon as={FiTarget} color="blue.400" boxSize={4} />
                      <Text fontSize="xs" color="text.muted" fontWeight="medium">COUVERTURE</Text>
                    </HStack>
                    <Text fontSize="xl" fontWeight="bold" color={
                      quality.density.coverage_pct >= 20 ? 'green.400' :
                      quality.density.coverage_pct >= 10 ? 'yellow.400' :
                      'red.400'
                    }>
                      {quality.density.coverage_pct.toFixed(1)}%
                    </Text>
                    <Text fontSize="xs" color="text.muted">
                      {quality.density.segments_processed}/{quality.density.segments_total} segments
                    </Text>
                  </Box>

                  {/* Dedup Ratio */}
                  <Box p={3} bg="bg.tertiary" rounded="lg">
                    <HStack mb={2}>
                      <Icon as={FiLink} color="purple.400" boxSize={4} />
                      <Text fontSize="xs" color="text.muted" fontWeight="medium">DEDUP RATIO</Text>
                    </HStack>
                    <Text fontSize="xl" fontWeight="bold" color={
                      quality.density.dup_ratio <= 0.30 ? 'green.400' :
                      quality.density.dup_ratio <= 0.50 ? 'yellow.400' :
                      'red.400'
                    }>
                      {(quality.density.dup_ratio * 100).toFixed(0)}%
                    </Text>
                    <Text fontSize="xs" color="text.muted">
                      {quality.density.unique_relations}/{quality.density.raw_relations} uniques
                    </Text>
                  </Box>

                  {/* Vagueness */}
                  <Box p={3} bg="bg.tertiary" rounded="lg">
                    <HStack mb={2}>
                      <Icon as={FiTrendingDown} color="orange.400" boxSize={4} />
                      <Text fontSize="xs" color="text.muted" fontWeight="medium">VAGUE</Text>
                    </HStack>
                    <Text fontSize="xl" fontWeight="bold" color={
                      quality.vagueness.vague_pct <= 15 ? 'green.400' :
                      quality.vagueness.vague_pct <= 30 ? 'yellow.400' :
                      'red.400'
                    }>
                      {quality.vagueness.vague_pct.toFixed(1)}%
                    </Text>
                    <Text fontSize="xs" color="text.muted">
                      {quality.vagueness.vague_relations} relations vagues
                    </Text>
                  </Box>

                  {/* Hub Explosion */}
                  <Box p={3} bg="bg.tertiary" rounded="lg">
                    <HStack mb={2}>
                      <Icon as={FiTrendingUp} color="cyan.400" boxSize={4} />
                      <Text fontSize="xs" color="text.muted" fontWeight="medium">HUB TOP1</Text>
                    </HStack>
                    <Text fontSize="xl" fontWeight="bold" color={
                      quality.hubs.top1_degree_share <= 0.10 ? 'green.400' :
                      quality.hubs.top1_degree_share <= 0.20 ? 'yellow.400' :
                      'red.400'
                    }>
                      {(quality.hubs.top1_degree_share * 100).toFixed(1)}%
                    </Text>
                    <Text fontSize="xs" color="text.muted" noOfLines={1} title={quality.hubs.top1_node}>
                      {quality.hubs.top1_node?.substring(0, 12) || '-'}...
                    </Text>
                  </Box>
                </SimpleGrid>

                {/* Additional Stats Row */}
                <SimpleGrid columns={{ base: 2, md: 3 }} spacing={4} mt={4}>
                  <HStack justify="space-between" p={2} bg="bg.tertiary" rounded="md">
                    <Text fontSize="xs" color="text.muted">Relations/Segment</Text>
                    <Text fontSize="sm" fontWeight="medium" color="text.primary">
                      {quality.density.relations_per_segment.toFixed(1)}
                    </Text>
                  </HStack>
                  <HStack justify="space-between" p={2} bg="bg.tertiary" rounded="md">
                    <Text fontSize="xs" color="text.muted">Paires Symetriques</Text>
                    <Text fontSize="sm" fontWeight="medium" color={
                      quality.cycles.symmetric_pairs === 0 ? 'green.400' : 'yellow.400'
                    }>
                      {quality.cycles.symmetric_pairs}
                    </Text>
                  </HStack>
                  <HStack justify="space-between" p={2} bg="bg.tertiary" rounded="md">
                    <Text fontSize="xs" color="text.muted">Total Edges</Text>
                    <Text fontSize="sm" fontWeight="medium" color="text.primary">
                      {quality.hubs.total_edges}
                    </Text>
                  </HStack>
                </SimpleGrid>

                {/* Flags Summary */}
                {Object.entries(quality.flags).some(([_, v]) => v) && (
                  <Box mt={4}>
                    <Text fontSize="xs" color="text.muted" mb={2}>FLAGS ACTIFS</Text>
                    <Flex flexWrap="wrap" gap={2}>
                      {Object.entries(quality.flags)
                        .filter(([_, v]) => v)
                        .map(([flag, _]) => (
                          <Badge
                            key={flag}
                            colorScheme={
                              flag.includes('high') || flag.includes('hub') ? 'red' :
                              flag.includes('low') ? 'yellow' : 'gray'
                            }
                            variant="subtle"
                            fontSize="xs"
                          >
                            {flag.replace(/_/g, ' ')}
                          </Badge>
                        ))}
                    </Flex>
                  </Box>
                )}
              </MotionBox>
            )}

            {qualityLoading && (
              <Box
                bg="bg.secondary"
                border="1px solid"
                borderColor="border.default"
                rounded="xl"
                p={6}
              >
                <HStack>
                  <Spinner size="sm" color="brand.500" />
                  <Text color="text.muted">Chargement des metriques de qualite...</Text>
                </HStack>
              </Box>
            )}

            {/* Quality Notes */}
            {analytics.quality_notes && analytics.quality_notes.length > 0 && (
              <MotionBox
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.35 }}
                bg="bg.secondary"
                border="1px solid"
                borderColor="border.default"
                rounded="xl"
                p={6}
              >
                <HStack mb={4}>
                  <Icon as={FiInfo} color="brand.400" />
                  <Text fontSize="lg" fontWeight="semibold" color="text.primary">
                    Notes de qualite
                  </Text>
                </HStack>
                <VStack align="stretch" spacing={2}>
                  {analytics.quality_notes.map((note, i) => (
                    <HStack key={i} p={3} bg="bg.tertiary" rounded="lg">
                      <Icon
                        as={note.includes('OK') || note.includes('riche') ? FiCheckCircle : note.includes('Peu') || note.includes('pauvre') ? FiAlertTriangle : FiInfo}
                        color={note.includes('OK') || note.includes('riche') ? 'green.400' : note.includes('Peu') || note.includes('pauvre') ? 'yellow.400' : 'blue.400'}
                      />
                      <Text fontSize="sm" color="text.primary">{note}</Text>
                    </HStack>
                  ))}
                </VStack>
              </MotionBox>
            )}
          </VStack>
        ) : null}
      </Box>
    </Box>
  )
}
