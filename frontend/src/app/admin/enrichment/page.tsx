'use client'

/**
 * OSMOSE Enrichment KG Dashboard - Pass 2 + Pass 3
 * ADR Graph-First Architecture compliant
 * Dense, industrial admin interface
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Box,
  Button,
  HStack,
  Icon,
  Text,
  VStack,
  Spinner,
  Center,
  Badge,
  Progress,
  useToast,
  Tooltip,
  Table,
  Thead,
  Tbody,
  Tr,
  Th,
  Td,
  Flex,
  IconButton,
  Divider,
} from '@chakra-ui/react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  FiRefreshCw,
  FiCheckCircle,
  FiAlertTriangle,
  FiZap,
  FiArrowRight,
  FiPlay,
  FiCpu,
  FiLink,
  FiTarget,
  FiGitMerge,
  FiLayers,
  FiActivity,
  FiStopCircle,
  FiClock,
  FiXCircle,
  FiX,
  FiBox,
  FiGrid,
  FiFileText,
  FiBookOpen,
  FiHash,
  FiShield,
  FiCalendar,
  FiBarChart2,
  FiAlertCircle,
  FiTrendingUp,
  FiEye,
} from 'react-icons/fi'
import { apiClient } from '@/lib/api'

// Types
interface EnrichmentStatus {
  // Document-level (Pass 1-3)
  proto_concepts: number
  canonical_concepts: number
  mentioned_in_count: number
  topics_count: number
  has_topic_count: number
  covers_count: number
  raw_assertions: number
  proven_relations: number

  // Corpus-level (Pass 4)
  er_standalone_concepts: number
  er_merged_concepts: number
  er_pending_proposals: number
  co_occurs_relations: number  // Pass 4b: PATCH-LINK

  // Jobs
  pending_jobs: number
  running_jobs: number
}

// Governance types (ADR 2026-01-07)
interface GovernanceMetrics {
  total_relations: number
  tier_distribution: {
    HIGH: number
    MEDIUM: number
    LOW: number
    WEAK: number
  }
  unscored_relations: number
  co_occurs_count: number
  high_confidence_ratio: number
  avg_evidence_count: number
}

interface TensionCounts {
  total: number
  UNRESOLVED: number
  ACKNOWLEDGED: number
  EXPLAINED: number
}

interface Pass2Result {
  success: boolean
  phase: string
  items_processed: number
  items_created: number
  items_updated: number
  execution_time_ms: number
  errors: string[]
  details: Record<string, any>
}

interface PhaseConfig {
  id: string
  name: string
  shortName: string
  pass: number
  subPhase: string | null
  icon: any
  color: string
  endpoint: string
  description: string
}

interface Pass2JobProgress {
  phase: string
  items_processed: number
  items_total: number
  percentage: number
  current_batch: number
  total_batches: number
  errors: string[]
}

interface Pass2Job {
  job_id: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  progress: Pass2JobProgress | null
  created_at: string
  started_at: string | null
  completed_at: string | null
  error: string | null
  result: Record<string, any> | null
}

// ADR-compliant phases avec noms explicites
const phases: PhaseConfig[] = [
  // Pass 2.0 - Corpus Promotion (ADR_UNIFIED_CORPUS_PROMOTION)
  {
    id: 'corpus-promotion',
    name: 'Promotion Corpus',
    shortName: 'Promotion',
    pass: 2,
    subPhase: '0',
    icon: FiTrendingUp,
    color: 'yellow',
    endpoint: '/admin/pass2/corpus-promotion',
    description: 'Promouvoit ProtoConcepts → CanonicalConcepts (vue corpus)'
  },
  // Enrichissement (ex-Pass 2)
  {
    id: 'structural-topics',
    name: 'Structure documentaire',
    shortName: 'Structure',
    pass: 2,
    subPhase: 'a',
    icon: FiBookOpen,
    color: 'cyan',
    endpoint: '/admin/pass2/structural-topics',
    description: 'Detecte les sections (H1/H2) et leurs couvertures'
  },
  {
    id: 'classify-fine',
    name: 'Typage concepts',
    shortName: 'Typage',
    pass: 2,
    subPhase: 'b',
    icon: FiCpu,
    color: 'purple',
    endpoint: '/admin/pass2/classify-fine',
    description: 'Classifie chaque concept (produit, norme, process...)'
  },
  {
    id: 'enrich-relations',
    name: 'Relations candidates',
    shortName: 'Candidates',
    pass: 2,
    subPhase: 'c',
    icon: FiLink,
    color: 'blue',
    endpoint: '/admin/pass2/enrich-relations',
    description: 'Detecte les relations potentielles entre concepts'
  },
  // Validation (ex-Pass 3)
  {
    id: 'semantic-consolidation',
    name: 'Validation extractive',
    shortName: 'Validation',
    pass: 3,
    subPhase: null,
    icon: FiShield,
    color: 'green',
    endpoint: '/admin/pass3/run',
    description: 'Valide chaque relation avec citation du texte source'
  },
  // Consolidation Corpus (Pass 4) - ADR 2026-01-07
  {
    id: 'entity-resolution',
    name: 'Entity Resolution',
    shortName: 'ER',
    pass: 4,
    subPhase: 'a',
    icon: FiGitMerge,
    color: 'orange',
    endpoint: '/admin/pass2/corpus-er',
    description: 'Fusionne les concepts dupliques cross-documents'
  },
  {
    id: 'corpus-links',
    name: 'Liens Corpus',
    shortName: 'Links',
    pass: 4,
    subPhase: 'b',
    icon: FiLink,
    color: 'pink',
    endpoint: '/admin/pass4/corpus-links',
    description: 'Cree les liens CO_OCCURS_IN_CORPUS (≥2 docs communs)'
  },
]

// Metric card - compact with color-coded border
const MetricCard = ({ label, value, icon, color = 'gray', tooltip }: { label: string; value: number; icon: any; color?: string; tooltip?: string }) => (
  <Tooltip label={tooltip} placement="top" hasArrow isDisabled={!tooltip}>
    <Box bg="whiteAlpha.50" border="1px solid" borderColor={`${color}.700`} rounded="lg" px={3} py={2} minW="90px" cursor={tooltip ? 'help' : undefined}>
      <HStack spacing={2}>
        <Box w={6} h={6} rounded="md" bg={`${color}.900`} display="flex" alignItems="center" justifyContent="center">
          <Icon as={icon} boxSize={3} color={`${color}.400`} />
        </Box>
        <Box>
          <Text fontSize="md" fontWeight="bold" color="text.primary" fontFamily="mono" lineHeight={1}>{value.toLocaleString()}</Text>
          <Text fontSize="2xs" color="text.muted" lineHeight={1.2}>{label}</Text>
        </Box>
      </HStack>
    </Box>
  </Tooltip>
)

// Small inline stat
const StatItem = ({ label, value, icon, color = 'gray' }: { label: string; value: number; icon: any; color?: string }) => (
  <HStack spacing={1.5} px={2} py={1} bg="whiteAlpha.50" rounded="md" minW="fit-content">
    <Icon as={icon} boxSize={3} color={`${color}.400`} />
    <Text fontSize="xs" fontWeight="bold" color="text.primary" fontFamily="mono">{value}</Text>
    <Text fontSize="2xs" color="text.muted">{label}</Text>
  </HStack>
)

// Confidence tier bar visualization
const TierBar = ({ tiers, total }: { tiers: { HIGH: number; MEDIUM: number; LOW: number; WEAK: number }; total: number }) => {
  if (total === 0) return <Text fontSize="2xs" color="text.muted">Aucune relation scoree</Text>
  const pct = (v: number) => Math.round((v / total) * 100)
  const tierConfig = [
    { key: 'HIGH', color: 'green', label: 'HIGH' },
    { key: 'MEDIUM', color: 'blue', label: 'MED' },
    { key: 'LOW', color: 'yellow', label: 'LOW' },
    { key: 'WEAK', color: 'gray', label: 'WEAK' },
  ] as const
  return (
    <VStack align="stretch" spacing={1} w="full">
      <HStack h="6px" w="full" rounded="full" overflow="hidden" bg="whiteAlpha.100">
        {tierConfig.map(({ key, color }) => {
          const val = tiers[key] || 0
          const width = pct(val)
          return width > 0 ? <Box key={key} h="full" bg={`${color}.500`} w={`${width}%`} /> : null
        })}
      </HStack>
      <HStack spacing={3} justify="center">
        {tierConfig.map(({ key, color, label }) => (
          <HStack key={key} spacing={1}>
            <Box w={2} h={2} rounded="sm" bg={`${color}.500`} />
            <Text fontSize="2xs" color="text.muted">{label}: {tiers[key] || 0}</Text>
          </HStack>
        ))}
      </HStack>
    </VStack>
  )
}

// Flow step - pass-aware styling
const PassBlock = ({
  passNum,
  label,
  steps,
  activeStep,
  isComplete = false
}: {
  passNum: number
  label: string
  steps: { name: string; color: string }[]
  activeStep: string | null
  isComplete?: boolean
}) => (
  <Box
    bg="whiteAlpha.50"
    border="2px solid"
    borderColor={activeStep && steps.some(s => s.name === activeStep) ? 'brand.400' : isComplete ? 'green.600' : 'whiteAlpha.200'}
    rounded="lg"
    p={2}
    position="relative"
  >
    <HStack spacing={1} mb={1.5}>
      <Badge size="xs" colorScheme={isComplete ? 'green' : 'gray'} variant="solid">Pass {passNum}</Badge>
      <Text fontSize="2xs" color="text.muted">{label}</Text>
    </HStack>
    <HStack spacing={1} flexWrap="wrap">
      {steps.map((step, i) => {
        const isActive = activeStep === step.name
        return (
          <HStack key={step.name} spacing={1}>
            <HStack
              spacing={1}
              bg={`${step.color}.900`}
              px={1.5}
              py={0.5}
              rounded="md"
              border="1px solid"
              borderColor={isActive ? `${step.color}.400` : `${step.color}.700`}
              animation={isActive ? "pulse-glow 2s ease-in-out infinite" : undefined}
              boxShadow={isActive ? `0 0 10px var(--chakra-colors-${step.color}-500)` : undefined}
              sx={isActive ? {
                "@keyframes pulse-glow": {
                  "0%, 100%": { boxShadow: `0 0 6px var(--chakra-colors-${step.color}-600)` },
                  "50%": { boxShadow: `0 0 16px var(--chakra-colors-${step.color}-400)` },
                },
              } : undefined}
            >
              <Box
                w={1.5}
                h={1.5}
                rounded="full"
                bg={`${step.color}.400`}
                animation={isActive ? "blink 1.5s ease-in-out infinite" : undefined}
                sx={isActive ? {
                  "@keyframes blink": {
                    "0%, 100%": { opacity: 1 },
                    "50%": { opacity: 0.3 },
                  },
                } : undefined}
              />
              <Text fontSize="2xs" color={`${step.color}.200`} fontWeight="medium">{step.name}</Text>
            </HStack>
            {i < steps.length - 1 && <Icon as={FiArrowRight} boxSize={2.5} color="whiteAlpha.400" />}
          </HStack>
        )
      })}
    </HStack>
  </Box>
)

// Format duration
const formatDuration = (startTime: string | null, endTime?: string | null): string => {
  if (!startTime) return '--'
  const start = new Date(startTime).getTime()
  const end = endTime ? new Date(endTime).getTime() : Date.now()
  const seconds = Math.floor((end - start) / 1000)
  if (seconds < 60) return `${seconds}s`
  return `${Math.floor(seconds / 60)}m${seconds % 60}s`
}

// Compact Job Progress
const JobProgress = ({ job, onCancel, onClear, isCancelling }: { job: Pass2Job; onCancel: () => void; onClear: () => void; isCancelling: boolean }) => {
  const progress = job.progress
  const isActive = job.status === 'pending' || job.status === 'running'
  const statusConfig = {
    pending: { color: 'yellow', icon: FiClock, text: 'Attente' },
    running: { color: 'blue', icon: FiActivity, text: 'En cours' },
    completed: { color: 'green', icon: FiCheckCircle, text: 'Termine' },
    failed: { color: 'red', icon: FiXCircle, text: 'Echec' },
    cancelled: { color: 'gray', icon: FiStopCircle, text: 'Annule' },
  }[job.status]

  return (
    <Box bg="whiteAlpha.50" border="1px solid" borderColor={`${statusConfig.color}.500`} rounded="lg" p={2} mb={3}>
      <Flex justify="space-between" align="center" mb={1.5}>
        <HStack spacing={2}>
          {isActive ? <Spinner size="xs" color={`${statusConfig.color}.400`} /> : <Icon as={statusConfig.icon} boxSize={3} color={`${statusConfig.color}.400`} />}
          <Badge size="sm" colorScheme={statusConfig.color}>{statusConfig.text}</Badge>
          <Text fontSize="2xs" color="text.muted" fontFamily="mono">#{job.job_id.slice(0, 8)}</Text>
          {progress?.phase && <Text fontSize="2xs" color={`${statusConfig.color}.300`}>• {progress.phase}</Text>}
        </HStack>
        <HStack spacing={1}>
          {isActive && (
            <Button size="xs" variant="ghost" colorScheme="red" onClick={onCancel} isLoading={isCancelling} leftIcon={<FiStopCircle />}>
              Stop
            </Button>
          )}
          {!isActive && (
            <IconButton aria-label="Close" icon={<FiX />} size="xs" variant="ghost" onClick={onClear} />
          )}
        </HStack>
      </Flex>

      {progress && (
        <Box>
          <Flex justify="space-between" mb={1}>
            <Text fontSize="2xs" color="text.muted">
              {progress.items_processed}/{progress.items_total} • Batch {progress.current_batch}/{progress.total_batches}
            </Text>
            <Text fontSize="2xs" fontWeight="bold" color={`${statusConfig.color}.300`}>{progress.percentage.toFixed(0)}%</Text>
          </Flex>
          <Progress value={progress.percentage} size="xs" colorScheme={statusConfig.color} rounded="full" hasStripe={isActive} isAnimated={isActive} />
        </Box>
      )}

      <HStack spacing={3} mt={1.5} fontSize="2xs" color="text.muted">
        <Text>Start: {job.started_at ? new Date(job.started_at).toLocaleTimeString() : '--'}</Text>
        <Text>Duree: {formatDuration(job.started_at, job.completed_at)}</Text>
        {job.error && <Text color="red.300" noOfLines={1}>Err: {job.error}</Text>}
      </HStack>
    </Box>
  )
}

// Map job phase to flow step name
const getActiveFlowStep = (jobPhase: string | undefined): string | null => {
  if (!jobPhase) return null
  const phaseMap: Record<string, string> = {
    // Pass 2.0 - Corpus Promotion (ADR_UNIFIED_CORPUS_PROMOTION)
    'CORPUS_PROMOTION': 'Promotion',
    'corpus_promotion': 'Promotion',
    'Promoting concepts': 'Promotion',
    // Pass 2a - Structure
    'STRUCTURAL_TOPICS': 'Structure',
    'structural_topics': 'Structure',
    'Topics & Scope': 'Structure',
    'Extracting document sections': 'Structure',
    // Pass 2b - Classification
    'CLASSIFY_FINE': 'Typage',
    'Classification Fine': 'Typage',
    'Starting classification': 'Typage',
    // Pass 2c - Relations candidates
    'ENRICH_RELATIONS': 'Candidates',
    'Enrichissement Relations': 'Candidates',
    'Relations Segment': 'Candidates',
    'Detecting relations': 'Candidates',
    // Pass 3 - Validation extractive
    'SEMANTIC_CONSOLIDATION': 'Validation',
    'Consolidation Semantique': 'Validation',
    // Pass 4a - Entity Resolution
    'ENTITY_RESOLUTION': 'ER',
    'entity_resolution': 'ER',
    'CORPUS_ER': 'ER',
    // Pass 4b - Corpus Links
    'CORPUS_LINKS': 'Links',
    'corpus_links': 'Links',
    // Legacy (redirige vers Validation)
    'CONSOLIDATE_CLAIMS': 'Validation',
    'CONSOLIDATE_RELATIONS': 'Validation',
    'CROSS_DOC': 'ER',  // Legacy mapping
  }
  return phaseMap[jobPhase] || null
}

export default function EnrichmentDashboardPage() {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [phaseResults, setPhaseResults] = useState<Record<string, Pass2Result>>({})
  const [runningPhase, setRunningPhase] = useState<string | null>(null)
  const [activeJobId, setActiveJobId] = useState<string | null>(null)
  const [activeJob, setActiveJob] = useState<Pass2Job | null>(null)
  const [isCancelling, setIsCancelling] = useState(false)
  const pollingRef = useRef<NodeJS.Timeout | null>(null)
  const toastShownRef = useRef<string | null>(null)

  // Poll job status
  const pollJob = useCallback(async (jobId: string) => {
    try {
      const res = await apiClient.get<Pass2Job>(`/admin/pass2/jobs/${jobId}`)
      if (res.success && res.data) {
        setActiveJob(res.data)
        if (['completed', 'failed', 'cancelled'].includes(res.data.status)) {
          if (pollingRef.current) { clearInterval(pollingRef.current); pollingRef.current = null }
          queryClient.invalidateQueries({ queryKey: ['enrichment'] })
          if (toastShownRef.current !== jobId) {
            toastShownRef.current = jobId
            const msg = { completed: ['Enrichissement termine', 'success'], failed: ['Enrichissement echoue', 'error'], cancelled: ['Enrichissement annule', 'warning'] }[res.data.status] as [string, 'success' | 'error' | 'warning']
            toast({ title: msg[0], status: msg[1], duration: 3000 })
          }
        }
      }
    } catch (e) { console.error('Poll error:', e) }
  }, [queryClient, toast])

  useEffect(() => {
    if (activeJobId && !pollingRef.current) {
      pollJob(activeJobId)
      pollingRef.current = setInterval(() => pollJob(activeJobId), 2000)
    }
    return () => { if (pollingRef.current) { clearInterval(pollingRef.current); pollingRef.current = null } }
  }, [activeJobId, pollJob])

  // Load active job on mount
  useEffect(() => {
    if (!activeJobId) {
      apiClient.get<{ jobs: Pass2Job[] }>('/admin/pass2/jobs?limit=5').then(res => {
        const active = res.data?.jobs?.find(j => j.status === 'running' || j.status === 'pending')
        if (active) { setActiveJobId(active.job_id); setActiveJob(active) }
      }).catch(() => {})
    }
  }, [])

  const handleCancel = async () => {
    if (!activeJobId) return
    setIsCancelling(true)
    try { await apiClient.delete(`/admin/pass2/jobs/${activeJobId}`) } catch (e) { toast({ title: 'Erreur annulation', status: 'error', duration: 2000 }) }
    setIsCancelling(false)
  }

  const handleClear = () => {
    setActiveJobId(null); setActiveJob(null)
    if (pollingRef.current) { clearInterval(pollingRef.current); pollingRef.current = null }
    toastShownRef.current = null
  }

  // Fetch enrichment status
  const { data: status, isLoading, refetch, isError } = useQuery({
    queryKey: ['enrichment', 'status'],
    queryFn: async () => {
      const res = await apiClient.get<EnrichmentStatus>('/admin/enrichment/status')
      if (!res.success) throw new Error(res.error)
      return res.data
    },
    refetchInterval: 30000, // Reduced frequency to avoid issues
    retry: 1,
    staleTime: 10000, // Consider data fresh for 10s
  })

  // Run individual phase
  const runPhase = useMutation({
    mutationFn: async ({ endpoint, phaseId }: { endpoint: string; phaseId: string }) => {
      setRunningPhase(phaseId)
      const res = await apiClient.post<Pass2Result>(endpoint, { limit: 100 })
      if (!res.success) throw new Error(res.error || 'Failed')
      return { result: res.data, phaseId }
    },
    onSuccess: ({ result, phaseId }) => {
      if (result) setPhaseResults(prev => ({ ...prev, [phaseId]: result }))
      queryClient.invalidateQueries({ queryKey: ['enrichment'] })
      toast({ title: `${result?.items_processed || 0} traites`, status: result?.success ? 'success' : 'warning', duration: 2000 })
    },
    onError: (e: any) => toast({ title: 'Erreur', description: e.message, status: 'error', duration: 3000 }),
    onSettled: () => setRunningPhase(null),
  })

  // Run full Pass 2
  const runPass2 = useMutation({
    mutationFn: async () => {
      const res = await apiClient.post<Pass2Job>('/admin/pass2/jobs', {
        skip_promotion: false, // Pass 2.0: ProtoConcepts → CanonicalConcepts
        skip_classify: false,
        skip_enrich: false,
        skip_consolidate: true, // ADR: plus de consolidate legacy
        skip_corpus_er: true,
        batch_size: 500,
        process_all: true
      })
      if (!res.success || !res.data) throw new Error(res.error || 'Failed')
      return res.data
    },
    onSuccess: (job) => { setActiveJobId(job.job_id); setActiveJob(job); toast({ title: 'Pass 2 lance (Promotion + Enrichissement)', status: 'info', duration: 2000 }) },
    onError: (e: any) => toast({ title: 'Erreur', description: e.message, status: 'error', duration: 3000 }),
  })

  // Run Pass 3
  const runPass3 = useMutation({
    mutationFn: async () => {
      // Clear any stale job before running
      setActiveJob(null)
      setActiveJobId(null)
      const res = await apiClient.post<Pass2Result>('/admin/pass3/run', { max_candidates: 50 })
      if (!res.success) throw new Error(res.error || 'Failed')
      return res.data
    },
    onSuccess: (result) => {
      if (result) setPhaseResults(prev => ({ ...prev, 'semantic-consolidation': result }))
      queryClient.invalidateQueries({ queryKey: ['enrichment'] })
      toast({ title: `Pass 3: ${result?.items_created || 0} relations prouvees`, status: result?.success ? 'success' : 'warning', duration: 3000 })
    },
    onError: (e: any) => toast({ title: 'Erreur Pass 3', description: e.message, status: 'error', duration: 3000 }),
  })

  // Run Corpus Consolidation (Pass 4: ER + Links)
  const runCorpusConsolidation = useMutation({
    mutationFn: async () => {
      // Clear any stale job before running
      setActiveJob(null)
      setActiveJobId(null)
      // Run Pass 4a: Entity Resolution
      const erRes = await apiClient.post<Pass2Result>('/admin/pass2/corpus-er', { dry_run: false })
      // Run Pass 4b: Corpus Links
      const linksRes = await apiClient.post<Pass2Result>('/admin/pass4/corpus-links', {})
      return { er: erRes.data, links: linksRes.data }
    },
    onSuccess: ({ er, links }) => {
      if (er) setPhaseResults(prev => ({ ...prev, 'entity-resolution': er }))
      if (links) setPhaseResults(prev => ({ ...prev, 'corpus-links': links }))
      queryClient.invalidateQueries({ queryKey: ['enrichment'] })
      toast({
        title: `Corpus: ${er?.items_created || 0} merges, ${links?.items_created || 0} liens`,
        status: 'success',
        duration: 3000
      })
    },
    onError: (e: any) => toast({ title: 'Erreur Corpus', description: e.message, status: 'error', duration: 3000 }),
  })

  // Schedule batch
  const scheduleBatch = useMutation({
    mutationFn: async () => {
      const res = await apiClient.post('/admin/enrichment/schedule', {
        run_pass2: true,
        run_pass3: true,
        scheduled_time: 'tonight'
      })
      if (!res.success) throw new Error(res.error || 'Failed')
      return res.data
    },
    onSuccess: () => { toast({ title: 'Batch nocturne programme', status: 'success', duration: 2000 }) },
    onError: (e: any) => toast({ title: 'Erreur', description: e.message, status: 'error', duration: 3000 }),
  })

  // === GOVERNANCE LAYERS (ADR 2026-01-07) ===

  // Fetch governance quality metrics
  const { data: governanceMetrics, refetch: refetchGovernance } = useQuery({
    queryKey: ['governance', 'metrics'],
    queryFn: async () => {
      const res = await apiClient.get<GovernanceMetrics>('/admin/governance/quality/metrics')
      if (!res.success) return null
      return res.data
    },
    refetchInterval: 60000,
    retry: 1,
  })

  // Fetch tension counts
  const { data: tensionCounts } = useQuery({
    queryKey: ['governance', 'tensions'],
    queryFn: async () => {
      const res = await apiClient.get<TensionCounts>('/admin/governance/conflict/counts')
      if (!res.success) return null
      return res.data
    },
    refetchInterval: 60000,
    retry: 1,
  })

  // Run quality scoring
  const runQualityScoring = useMutation({
    mutationFn: async () => {
      const res = await apiClient.post('/admin/governance/quality/score', {})
      if (!res.success) throw new Error(res.error || 'Failed')
      return res.data
    },
    onSuccess: (data: any) => {
      queryClient.invalidateQueries({ queryKey: ['governance'] })
      toast({
        title: `Scoring: ${data?.relations_scored || 0} relations scorees`,
        description: `HIGH: ${data?.tier_distribution?.HIGH || 0}, MED: ${data?.tier_distribution?.MEDIUM || 0}`,
        status: 'success',
        duration: 4000
      })
    },
    onError: (e: any) => toast({ title: 'Erreur scoring', description: e.message, status: 'error', duration: 3000 }),
  })

  // Run conflict detection
  const runConflictDetection = useMutation({
    mutationFn: async () => {
      const res = await apiClient.post('/admin/governance/conflict/detect', {})
      if (!res.success) throw new Error(res.error || 'Failed')
      return res.data
    },
    onSuccess: (data: any) => {
      queryClient.invalidateQueries({ queryKey: ['governance'] })
      const tensionsFound = data?.stats?.tensions_detected || 0
      toast({
        title: tensionsFound > 0 ? `${tensionsFound} tension(s) detectee(s)` : 'Aucune nouvelle tension',
        status: tensionsFound > 0 ? 'warning' : 'success',
        duration: 3000
      })
    },
    onError: (e: any) => toast({ title: 'Erreur detection', description: e.message, status: 'error', duration: 3000 }),
  })

  if (isLoading) return <Center h="200px"><Spinner color="brand.500" /></Center>

  const hasActiveJob = activeJob && ['pending', 'running'].includes(activeJob.status)
  // Only show glow if job is actually running (not completed/failed)
  const currentStep = hasActiveJob ? getActiveFlowStep(activeJob?.progress?.phase) : null

  // Check if Pass 2a has been run (needed for Pass 3)
  const hasTopics = (status?.topics_count || 0) > 0

  return (
    <Box maxW="1400px" mx="auto" p={3}>
      {/* Header Row */}
      <Flex justify="space-between" align="center" mb={3}>
        <HStack spacing={3}>
          <Box w={8} h={8} rounded="lg" bgGradient="linear(to-br, brand.500, green.500)" display="flex" alignItems="center" justifyContent="center">
            <Icon as={FiActivity} boxSize={4} color="white" />
          </Box>
          <Box>
            <Text fontSize="lg" fontWeight="bold" color="text.primary" lineHeight={1}>Enrichissement KG</Text>
            <Text fontSize="2xs" color="text.muted">Promotion → Structure → Typage → Candidates → Validation → Corpus</Text>
          </Box>
        </HStack>
        <HStack spacing={2}>
          <IconButton aria-label="Refresh" icon={<FiRefreshCw />} size="sm" variant="ghost" onClick={() => refetch()} />
        </HStack>
      </Flex>

      {/* Pipeline Flow Visualization */}
      <Box bg="whiteAlpha.30" rounded="lg" p={3} mb={3} border="1px solid" borderColor="whiteAlpha.100">
        <Flex gap={3} align="center" justify="center" flexWrap="wrap">
          {/* Import (Pass 1) - ProtoConcepts only */}
          <HStack spacing={1} px={2} py={1} bg="green.900" border="1px solid" borderColor="green.600" rounded="md">
            <Icon as={FiCheckCircle} boxSize={3} color="green.400" />
            <Text fontSize="2xs" color="green.200">Import</Text>
            <Text fontSize="2xs" color="green.500">(Proto)</Text>
          </HStack>

          <Icon as={FiArrowRight} boxSize={4} color="whiteAlpha.400" />

          {/* Pass 2: Enrichissement (inclut Promotion 2.0) */}
          <PassBlock
            passNum={2}
            label="Enrichissement"
            steps={[
              { name: 'Promotion', color: 'yellow' },
              { name: 'Structure', color: 'cyan' },
              { name: 'Typage', color: 'purple' },
              { name: 'Candidates', color: 'blue' },
            ]}
            activeStep={currentStep}
            isComplete={hasTopics}
          />

          <Icon as={FiArrowRight} boxSize={4} color="whiteAlpha.400" />

          {/* Validation Block */}
          <PassBlock
            passNum={3}
            label="Preuve"
            steps={[
              { name: 'Validation', color: 'green' },
            ]}
            activeStep={currentStep}
            isComplete={(status?.proven_relations || 0) > 0}
          />

          <Icon as={FiArrowRight} boxSize={4} color="whiteAlpha.400" />

          {/* Corpus Consolidation Block (Pass 4) */}
          <PassBlock
            passNum={4}
            label="Corpus"
            steps={[
              { name: 'ER', color: 'orange' },
              { name: 'Links', color: 'pink' },
            ]}
            activeStep={currentStep}
            isComplete={(status?.er_merged_concepts || 0) > 0 || (status?.co_occurs_relations || 0) > 0}
          />

          <Icon as={FiArrowRight} boxSize={4} color="whiteAlpha.400" />

          {/* KG Ready */}
          <HStack spacing={1} px={2} py={1} bg={(status?.proven_relations || 0) > 0 ? "green.900" : "whiteAlpha.100"} border="1px solid" borderColor={(status?.proven_relations || 0) > 0 ? "green.600" : "whiteAlpha.200"} rounded="md">
            <Icon as={(status?.proven_relations || 0) > 0 ? FiCheckCircle : FiTarget} boxSize={3} color={(status?.proven_relations || 0) > 0 ? "green.400" : "whiteAlpha.400"} />
            <Text fontSize="2xs" color={(status?.proven_relations || 0) > 0 ? "green.200" : "whiteAlpha.400"}>KG Ready</Text>
          </HStack>
        </Flex>
      </Box>

      {/* Action Buttons */}
      <Flex gap={2} mb={3} flexWrap="wrap">
        <Button
          size="sm"
          colorScheme="cyan"
          variant="solid"
          leftIcon={<FiLayers />}
          onClick={() => runPass2.mutate()}
          isLoading={runPass2.isPending}
          isDisabled={!!hasActiveJob}
        >
          Enrichissement
        </Button>
        <Button
          size="sm"
          colorScheme="green"
          variant="solid"
          leftIcon={<FiShield />}
          onClick={() => runPass3.mutate()}
          isLoading={runPass3.isPending}
          isDisabled={!!hasActiveJob || !hasTopics}
          title={!hasTopics ? "Structure requise d'abord" : undefined}
        >
          Validation
        </Button>
        <Divider orientation="vertical" h="24px" borderColor="whiteAlpha.300" />
        <Button
          size="sm"
          colorScheme="orange"
          variant="solid"
          leftIcon={<FiGitMerge />}
          onClick={() => runCorpusConsolidation.mutate()}
          isLoading={runCorpusConsolidation.isPending}
          isDisabled={!!hasActiveJob || (status?.proven_relations || 0) === 0}
          title={(status?.proven_relations || 0) === 0 ? "Relations prouvees requises d'abord" : undefined}
        >
          Consolidation Corpus
        </Button>
        <Tooltip label="Planification horaire disponible prochainement" hasArrow>
          <Button
            size="sm"
            colorScheme="purple"
            variant="outline"
            leftIcon={<FiCalendar />}
            onClick={() => scheduleBatch.mutate()}
            isLoading={scheduleBatch.isPending}
          >
            Programmer Nocturne
          </Button>
        </Tooltip>
      </Flex>

      {/* Active Job */}
      {activeJob && <JobProgress job={activeJob} onCancel={handleCancel} onClear={handleClear} isCancelling={isCancelling} />}

      {/* Metrics Grid */}
      <Box bg="whiteAlpha.30" rounded="xl" p={3} mb={3} border="1px solid" borderColor="whiteAlpha.100">
        <Flex gap={3} flexWrap="wrap" justify="space-between">
          {/* Pass 1 + Pass 2.0 Output */}
          <VStack align="flex-start" spacing={1}>
            <Text fontSize="2xs" color="text.muted" fontWeight="medium">Extraction (Pass 1 + 2.0)</Text>
            <HStack spacing={2}>
              <MetricCard label="Proto" value={status?.proto_concepts || 0} icon={FiBox} color="yellow" tooltip="ProtoConcepts extraits par le LLM (Pass 1). Concepts bruts avant promotion." />
              <MetricCard label="Canonical" value={status?.canonical_concepts || 0} icon={FiGrid} color="green" tooltip="CanonicalConcepts apres promotion corpus (Pass 2.0). Concepts uniques regroupes." />
              <MetricCard label="Mentions" value={status?.mentioned_in_count || 0} icon={FiHash} color="gray" tooltip="Liens MENTIONED_IN entre concepts et documents/sections." />
            </HStack>
          </VStack>

          {/* Pass 2a Output */}
          <VStack align="flex-start" spacing={1}>
            <Text fontSize="2xs" color="text.muted" fontWeight="medium">Structure (Pass 2a)</Text>
            <HStack spacing={2}>
              <MetricCard label="Sections" value={status?.topics_count || 0} icon={FiBookOpen} color="cyan" tooltip="Sections documentaires detectees depuis les titres H1/H2. Representent la structure logique des documents." />
              <MetricCard label="Doc→Sec" value={status?.has_topic_count || 0} icon={FiLink} color="cyan" tooltip="Liens entre documents et leurs sections. Un document peut avoir plusieurs sections." />
              <MetricCard label="Couvertures" value={status?.covers_count || 0} icon={FiLayers} color="cyan" tooltip="Liens indiquant quels concepts sont abordes dans chaque section. Sert au filtrage par perimetre thematique." />
            </HStack>
          </VStack>

          {/* Pass 2b + Pass 3 Output */}
          <VStack align="flex-start" spacing={1}>
            <Text fontSize="2xs" color="text.muted" fontWeight="medium">Relations (Pass 2b + 3)</Text>
            <HStack spacing={2}>
              <MetricCard label="Candidates" value={status?.raw_assertions || 0} icon={FiFileText} color="blue" tooltip="Relations potentielles detectees entre concepts (ex: 'A requiert B'). Doivent etre validees par Pass 3." />
              <MetricCard label="Validees" value={status?.proven_relations || 0} icon={FiShield} color="green" tooltip="Relations confirmees avec une citation exacte du texte source. Garantit zero hallucination." />
            </HStack>
          </VStack>

          {/* Pass 4: Corpus Consolidation */}
          <VStack align="flex-end" spacing={1}>
            <Text fontSize="2xs" color="text.muted" fontWeight="medium">Corpus (Pass 4)</Text>
            <HStack spacing={2}>
              <Tooltip label="Concepts regroupes car consideres comme des variantes du meme concept (synonymes, abreviations...)." hasArrow placement="top">
                <Box><StatItem label="Merges" value={status?.er_merged_concepts || 0} icon={FiGitMerge} color="orange" /></Box>
              </Tooltip>
              <Tooltip label="Liens faibles cross-documents: concepts qui apparaissent ensemble dans 2+ documents." hasArrow placement="top">
                <Box><StatItem label="Co-occurs" value={status?.co_occurs_relations || 0} icon={FiLink} color="pink" /></Box>
              </Tooltip>
            </HStack>
          </VStack>
        </Flex>
      </Box>

      {/* Governance Layers - ADR 2026-01-07 */}
      <Box bg="whiteAlpha.30" rounded="xl" p={3} mb={3} border="1px solid" borderColor="teal.800">
        <Flex justify="space-between" align="flex-start" mb={2}>
          <HStack spacing={2}>
            <Icon as={FiBarChart2} boxSize={4} color="teal.400" />
            <Text fontSize="sm" fontWeight="semibold" color="text.primary">Gouvernance KG</Text>
            <Badge size="xs" colorScheme="teal" variant="subtle">ADR</Badge>
          </HStack>
          <HStack spacing={2}>
            <Button
              size="xs"
              colorScheme="teal"
              variant="solid"
              leftIcon={<FiTrendingUp />}
              onClick={() => runQualityScoring.mutate()}
              isLoading={runQualityScoring.isPending}
              isDisabled={(status?.proven_relations || 0) === 0}
            >
              Scorer
            </Button>
            <Button
              size="xs"
              colorScheme="orange"
              variant="outline"
              leftIcon={<FiAlertCircle />}
              onClick={() => runConflictDetection.mutate()}
              isLoading={runConflictDetection.isPending}
              isDisabled={(status?.proven_relations || 0) === 0}
            >
              Detecter Tensions
            </Button>
          </HStack>
        </Flex>

        <Flex gap={4} flexWrap="wrap">
          {/* Quality Layer */}
          <Box flex="1" minW="280px">
            <Text fontSize="2xs" color="text.muted" fontWeight="medium" mb={1.5}>Confiance Relations</Text>
            {governanceMetrics ? (
              <TierBar tiers={governanceMetrics.tier_distribution} total={governanceMetrics.total_relations} />
            ) : (
              <Text fontSize="2xs" color="text.muted" fontStyle="italic">Non score - cliquez "Scorer"</Text>
            )}
            {governanceMetrics && (
              <HStack spacing={3} mt={2} justify="center">
                <Text fontSize="2xs" color="text.muted">
                  <Text as="span" fontWeight="bold" color="green.300">{governanceMetrics.high_confidence_ratio.toFixed(0)}%</Text> haute confiance
                </Text>
                <Text fontSize="2xs" color="text.muted">
                  <Text as="span" fontWeight="bold" color="text.primary">{governanceMetrics.avg_evidence_count.toFixed(1)}</Text> preuves/rel
                </Text>
                {governanceMetrics.unscored_relations > 0 && (
                  <Text fontSize="2xs" color="yellow.300">{governanceMetrics.unscored_relations} non scorees</Text>
                )}
              </HStack>
            )}
          </Box>

          {/* Conflict Layer */}
          <Box minW="160px">
            <Text fontSize="2xs" color="text.muted" fontWeight="medium" mb={1.5}>Tensions Detectees</Text>
            {tensionCounts ? (
              <VStack align="flex-start" spacing={1}>
                <HStack spacing={3}>
                  <HStack spacing={1}>
                    <Box w={2} h={2} rounded="full" bg={tensionCounts.UNRESOLVED > 0 ? "orange.500" : "gray.600"} />
                    <Text fontSize="xs" fontWeight="bold" color={tensionCounts.UNRESOLVED > 0 ? "orange.300" : "text.muted"}>{tensionCounts.UNRESOLVED}</Text>
                    <Text fontSize="2xs" color="text.muted">non traitees</Text>
                  </HStack>
                </HStack>
                <HStack spacing={3}>
                  <HStack spacing={1}>
                    <Box w={2} h={2} rounded="full" bg="blue.600" />
                    <Text fontSize="2xs" color="text.muted">{tensionCounts.ACKNOWLEDGED} vues</Text>
                  </HStack>
                  <HStack spacing={1}>
                    <Box w={2} h={2} rounded="full" bg="green.600" />
                    <Text fontSize="2xs" color="text.muted">{tensionCounts.EXPLAINED} expliquees</Text>
                  </HStack>
                </HStack>
                {tensionCounts.total > 0 && (
                  <Button
                    size="xs"
                    variant="ghost"
                    colorScheme="teal"
                    leftIcon={<FiEye />}
                    mt={1}
                    onClick={() => window.open('/admin/tensions', '_blank')}
                  >
                    Voir tensions
                  </Button>
                )}
              </VStack>
            ) : (
              <Text fontSize="2xs" color="text.muted" fontStyle="italic">Non detecte</Text>
            )}
          </Box>
        </Flex>

        <Text fontSize="2xs" color="text.muted" mt={2} fontStyle="italic">
          Les scores sont des indicateurs de support, pas des decisions de verite. Une relation LOW n'est pas "fausse".
        </Text>
      </Box>

      {/* Phases Table */}
      <Box bg="whiteAlpha.50" rounded="lg" overflow="hidden">
        <Table size="sm" variant="unstyled">
          <Thead>
            <Tr borderBottom="1px solid" borderColor="whiteAlpha.100">
              <Th py={2} px={3} color="text.muted" fontSize="2xs" fontWeight="medium">Phase</Th>
              <Th py={2} px={3} color="text.muted" fontSize="2xs" fontWeight="medium">Description</Th>
              <Th py={2} px={3} color="text.muted" fontSize="2xs" fontWeight="medium" isNumeric>Resultat</Th>
              <Th py={2} px={3} color="text.muted" fontSize="2xs" fontWeight="medium" w="80px"></Th>
            </Tr>
          </Thead>
          <Tbody>
            {phases.map((phase) => {
              const result = phaseResults[phase.id]
              const isRunning = runningPhase === phase.id
              const isDisabled = !!hasActiveJob || (phase.pass === 3 && !hasTopics)
              return (
                <Tr key={phase.id} borderBottom="1px solid" borderColor="whiteAlpha.50" _hover={{ bg: 'whiteAlpha.50' }}>
                  <Td py={1.5} px={3}>
                    <HStack spacing={2}>
                      <Icon as={phase.icon} boxSize={3} color={`${phase.color}.400`} />
                      <VStack align="flex-start" spacing={0}>
                        <Text fontSize="xs" fontWeight="medium" color="text.primary">{phase.shortName}</Text>
                        <Text fontSize="2xs" color="text.muted">Pass {phase.pass}{phase.subPhase ? phase.subPhase : ''}</Text>
                      </VStack>
                    </HStack>
                  </Td>
                  <Td py={1.5} px={3}>
                    <Text fontSize="2xs" color="text.muted">{phase.description}</Text>
                  </Td>
                  <Td py={1.5} px={3} isNumeric>
                    {result && (
                      <HStack spacing={2} justify="flex-end">
                        <Icon as={result.success ? FiCheckCircle : FiAlertTriangle} boxSize={3} color={result.success ? 'green.400' : 'red.400'} />
                        <Text fontSize="2xs" fontFamily="mono" color="text.muted">
                          {result.items_processed}→{result.items_created}
                        </Text>
                        <Text fontSize="2xs" color="text.muted">{(result.execution_time_ms / 1000).toFixed(1)}s</Text>
                      </HStack>
                    )}
                  </Td>
                  <Td py={1.5} px={3}>
                    <Button
                      size="xs"
                      variant="ghost"
                      colorScheme={phase.color}
                      leftIcon={<FiPlay />}
                      onClick={() => runPhase.mutate({ endpoint: phase.endpoint, phaseId: phase.id })}
                      isLoading={isRunning}
                      isDisabled={isDisabled}
                    >
                      Run
                    </Button>
                  </Td>
                </Tr>
              )
            })}
          </Tbody>
        </Table>
      </Box>

      {/* Help Footer */}
      <Box mt={3} bg="whiteAlpha.50" rounded="lg" px={3} py={2} border="1px solid" borderColor="whiteAlpha.100">
        <Text fontSize="2xs" color="text.muted">
          <Text as="span" fontWeight="semibold" color="yellow.300">Promotion</Text> transforme ProtoConcepts en CanonicalConcepts (vue corpus).
          <Text as="span" fontWeight="semibold" color="cyan.300"> Structure</Text> detecte les sections (H1/H2).
          <Text as="span" fontWeight="semibold" color="purple.300"> Typage</Text> classifie les concepts.
          <Text as="span" fontWeight="semibold" color="blue.300"> Candidates</Text> detecte les relations.
          <Text as="span" fontWeight="semibold" color="green.300"> Validation</Text> confirme avec citation.
          <Text as="span" fontWeight="semibold" color="orange.300"> ER</Text> fusionne les doublons cross-doc.
          <Text as="span" fontWeight="semibold" color="pink.300"> Links</Text> cree les liens faibles corpus.
        </Text>
      </Box>
    </Box>
  )
}
