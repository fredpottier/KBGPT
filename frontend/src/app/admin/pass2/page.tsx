'use client'

/**
 * OSMOSE Pass 2 Dashboard - Compact Industrial Design
 * Dense, information-rich admin interface
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
  FiChevronRight,
} from 'react-icons/fi'
import { apiClient } from '@/lib/api'

// Types
interface Pass2Status {
  proto_concepts: number
  canonical_concepts: number
  raw_assertions: number
  raw_claims: number
  canonical_relations: number
  canonical_claims: number
  er_standalone_concepts: number
  er_merged_concepts: number
  er_pending_proposals: number
  pending_jobs: number
  running_jobs: number
}

interface KGQualityStats {
  claims_validated: number
  claims_candidate: number
  claims_conflicting: number
  relations_validated: number
  relations_candidate: number
  relations_ambiguous: number
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
  icon: any
  color: string
  endpoint: string
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

const phases: PhaseConfig[] = [
  { id: 'classify-fine', name: 'Classification Fine', shortName: 'Classify', icon: FiCpu, color: 'purple', endpoint: '/admin/pass2/classify-fine' },
  { id: 'enrich-relations', name: 'Enrichissement Relations', shortName: 'Relations', icon: FiLink, color: 'blue', endpoint: '/admin/pass2/enrich-relations' },
  { id: 'consolidate-claims', name: 'Consolidation Claims', shortName: 'Claims', icon: FiTarget, color: 'green', endpoint: '/admin/pass2/consolidate-claims' },
  { id: 'consolidate-relations', name: 'Consolidation Relations', shortName: 'Rels', icon: FiGitMerge, color: 'orange', endpoint: '/admin/pass2/consolidate-relations' },
  { id: 'corpus-er', name: 'Entity Resolution', shortName: 'ER', icon: FiLayers, color: 'cyan', endpoint: '/admin/pass2/corpus-er' },
]

// Metric card - compact but readable
const MetricCard = ({ label, value, icon, color = 'gray' }: { label: string; value: number; icon: any; color?: string }) => (
  <Box bg="whiteAlpha.50" border="1px solid" borderColor={`${color}.800`} rounded="lg" px={3} py={2} minW="100px">
    <HStack spacing={2}>
      <Box w={7} h={7} rounded="md" bg={`${color}.900`} display="flex" alignItems="center" justifyContent="center">
        <Icon as={icon} boxSize={3.5} color={`${color}.400`} />
      </Box>
      <Box>
        <Text fontSize="lg" fontWeight="bold" color="text.primary" fontFamily="mono" lineHeight={1}>{value.toLocaleString()}</Text>
        <Text fontSize="xs" color="text.muted" lineHeight={1.2}>{label}</Text>
      </Box>
    </HStack>
  </Box>
)

// Small inline stat for secondary metrics
const StatItem = ({ label, value, icon, color = 'gray' }: { label: string; value: number; icon: any; color?: string }) => (
  <HStack spacing={1.5} px={2} py={1} bg="whiteAlpha.50" rounded="md" minW="fit-content">
    <Icon as={icon} boxSize={3} color={`${color}.400`} />
    <Text fontSize="xs" fontWeight="bold" color="text.primary" fontFamily="mono">{value}</Text>
    <Text fontSize="xs" color="text.muted">{label}</Text>
  </HStack>
)

// Quality stat pill - visible but compact with tooltip
const QualityPill = ({ label, value, color, tooltip }: { label: string; value: number; color: string; tooltip: string }) => (
  <Tooltip label={tooltip} placement="top" hasArrow>
    <HStack spacing={1.5} px={2} py={0.5} bg={`${color}.900`} border="1px solid" borderColor={`${color}.700`} rounded="md" cursor="help">
      <Box w={2} h={2} rounded="full" bg={`${color}.400`} />
      <Text fontSize="xs" fontWeight="bold" fontFamily="mono" color={`${color}.300`}>{value}</Text>
      <Text fontSize="xs" color={`${color}.400`}>{label}</Text>
    </HStack>
  </Tooltip>
)

// Compact flow step with optional active animation
const FlowStep = ({ name, color, isLast = false, isActive = false }: { name: string; color: string; isLast?: boolean; isActive?: boolean }) => (
  <HStack spacing={2}>
    <HStack
      spacing={1.5}
      bg={`${color}.900`}
      px={2}
      py={0.5}
      rounded="md"
      border="1px solid"
      borderColor={isActive ? `${color}.400` : `${color}.700`}
      position="relative"
      animation={isActive ? "pulse-glow 2s ease-in-out infinite" : undefined}
      boxShadow={isActive ? `0 0 12px var(--chakra-colors-${color}-500)` : undefined}
      sx={isActive ? {
        "@keyframes pulse-glow": {
          "0%, 100%": {
            boxShadow: `0 0 8px var(--chakra-colors-${color}-600)`,
            borderColor: `var(--chakra-colors-${color}-500)`,
          },
          "50%": {
            boxShadow: `0 0 20px var(--chakra-colors-${color}-400)`,
            borderColor: `var(--chakra-colors-${color}-300)`,
          },
        },
      } : undefined}
    >
      <Box
        w={1.5}
        h={1.5}
        rounded="full"
        bg={`${color}.400`}
        animation={isActive ? "blink-inverse 2s ease-in-out infinite" : undefined}
        sx={isActive ? {
          "@keyframes blink-inverse": {
            "0%, 100%": { opacity: 1, transform: "scale(1.1)" },
            "50%": { opacity: 0.3, transform: "scale(0.8)" },
          },
        } : undefined}
      />
      <Text fontSize="xs" color={isActive ? `${color}.100` : `${color}.200`} fontWeight={isActive ? "semibold" : "medium"}>{name}</Text>
    </HStack>
    {!isLast && <Icon as={FiArrowRight} boxSize={3.5} color="whiteAlpha.500" />}
  </HStack>
)

// Map job phase to flow step name
const getActiveFlowStep = (jobPhase: string | undefined): string | null => {
  if (!jobPhase) return null
  const phaseMap: Record<string, string> = {
    'CLASSIFY_FINE': 'Classification',
    'Classification Fine': 'Classification',
    'ENRICH_RELATIONS': 'Relations',
    'Enrichissement Relations': 'Relations',
    'CONSOLIDATE_CLAIMS': 'Consolidation',
    'Consolidation Claims': 'Consolidation',
    'CONSOLIDATE_RELATIONS': 'Consolidation',
    'Consolidation Relations': 'Consolidation',
    'CORPUS_ER': 'Deduplication',
    'Entity Resolution': 'Deduplication',
  }
  return phaseMap[jobPhase] || null
}

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
    <Box bg="whiteAlpha.50" border="1px solid" borderColor={`${statusConfig.color}.500`} rounded="lg" p={3} mb={3}>
      <Flex justify="space-between" align="center" mb={2}>
        <HStack spacing={2}>
          {isActive ? <Spinner size="xs" color={`${statusConfig.color}.400`} /> : <Icon as={statusConfig.icon} boxSize={3.5} color={`${statusConfig.color}.400`} />}
          <Badge size="sm" colorScheme={statusConfig.color}>{statusConfig.text}</Badge>
          <Text fontSize="xs" color="text.muted" fontFamily="mono">#{job.job_id.slice(0, 8)}</Text>
          {progress?.phase && <Text fontSize="xs" color={`${statusConfig.color}.300`}>• {progress.phase}</Text>}
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
            <Text fontSize="xs" color="text.muted">
              {progress.items_processed}/{progress.items_total} • Batch {progress.current_batch}/{progress.total_batches}
            </Text>
            <Text fontSize="xs" fontWeight="bold" color={`${statusConfig.color}.300`}>{progress.percentage.toFixed(0)}%</Text>
          </Flex>
          <Progress value={progress.percentage} size="xs" colorScheme={statusConfig.color} rounded="full" hasStripe={isActive} isAnimated={isActive} />
        </Box>
      )}

      <HStack spacing={4} mt={2} fontSize="xs" color="text.muted">
        <Text>Start: {job.started_at ? new Date(job.started_at).toLocaleTimeString() : '--'}</Text>
        <Text>Duree: {formatDuration(job.started_at, job.completed_at)}</Text>
        {job.error && <Text color="red.300" noOfLines={1}>Err: {job.error}</Text>}
      </HStack>
    </Box>
  )
}

export default function Pass2DashboardPage() {
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
          queryClient.invalidateQueries({ queryKey: ['pass2'] })
          if (toastShownRef.current !== jobId) {
            toastShownRef.current = jobId
            const msg = { completed: ['Pass 2 termine', 'success'], failed: ['Pass 2 echoue', 'error'], cancelled: ['Pass 2 annule', 'warning'] }[res.data.status] as [string, 'success' | 'error' | 'warning']
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

  // Fetch status
  const { data: status, isLoading, refetch } = useQuery({
    queryKey: ['pass2', 'status'],
    queryFn: async () => { const res = await apiClient.get<Pass2Status>('/admin/pass2/status'); if (!res.success) throw new Error(res.error); return res.data },
    refetchInterval: 10000,
  })

  // Fetch KG quality stats
  const { data: qualityStats } = useQuery({
    queryKey: ['pass2', 'quality'],
    queryFn: async () => {
      const res = await apiClient.get<KGQualityStats>('/claims/stats')
      if (!res.success) return null
      return res.data
    },
    refetchInterval: 30000,
  })

  // Run phase
  const runPhase = useMutation({
    mutationFn: async ({ endpoint, phaseId }: { endpoint: string; phaseId: string }) => {
      setRunningPhase(phaseId)
      const res = await apiClient.post<Pass2Result>(endpoint, { limit: 100 })
      if (!res.success) throw new Error(res.error || 'Failed')
      return { result: res.data, phaseId }
    },
    onSuccess: ({ result, phaseId }) => {
      if (result) setPhaseResults(prev => ({ ...prev, [phaseId]: result }))
      queryClient.invalidateQueries({ queryKey: ['pass2'] })
      toast({ title: `${result?.items_processed || 0} traites`, status: result?.success ? 'success' : 'warning', duration: 2000 })
    },
    onError: (e: any) => toast({ title: 'Erreur', description: e.message, status: 'error', duration: 3000 }),
    onSettled: () => setRunningPhase(null),
  })

  // Run full
  const runFull = useMutation({
    mutationFn: async () => {
      const res = await apiClient.post<Pass2Job>('/admin/pass2/jobs', { skip_classify: false, skip_enrich: false, skip_consolidate: false, batch_size: 500, process_all: true })
      if (!res.success || !res.data) throw new Error(res.error || 'Failed')
      return res.data
    },
    onSuccess: (job) => { setActiveJobId(job.job_id); setActiveJob(job); toast({ title: 'Job cree', status: 'info', duration: 2000 }) },
    onError: (e: any) => toast({ title: 'Erreur', description: e.message, status: 'error', duration: 3000 }),
  })

  if (isLoading) return <Center h="200px"><Spinner color="brand.500" /></Center>

  const hasActiveJob = activeJob && ['pending', 'running'].includes(activeJob.status)

  return (
    <Box maxW="1400px" mx="auto" p={3}>
      {/* Header Row */}
      <Flex justify="space-between" align="center" mb={3}>
        <HStack spacing={3}>
          <Box w={8} h={8} rounded="lg" bgGradient="linear(to-br, brand.500, purple.500)" display="flex" alignItems="center" justifyContent="center">
            <Icon as={FiActivity} boxSize={4} color="white" />
          </Box>
          <Box>
            <Text fontSize="lg" fontWeight="bold" color="text.primary" lineHeight={1}>Enrichissement du Knowledge Graph</Text>
            <Text fontSize="xs" color="text.muted">Classification, relations et consolidation des connaissances</Text>
          </Box>
        </HStack>
        <HStack spacing={2}>
          <IconButton aria-label="Refresh" icon={<FiRefreshCw />} size="sm" variant="ghost" onClick={() => refetch()} />
          <Button size="sm" colorScheme="brand" leftIcon={<FiZap />} onClick={() => runFull.mutate()} isLoading={runFull.isPending} isDisabled={!!hasActiveJob}>
            Enrichir
          </Button>
        </HStack>
      </Flex>

      {/* Explanation + Pipeline Flow */}
      {(() => {
        const currentStep = getActiveFlowStep(activeJob?.progress?.phase)
        const isJobRunning = activeJob && ['pending', 'running'].includes(activeJob.status)
        return (
          <Box bg="whiteAlpha.50" rounded="lg" px={4} py={3} mb={3} border="1px solid" borderColor="whiteAlpha.100">
            <Text fontSize="sm" color="text.secondary" mb={2}>
              Apres l'import des documents, cette etape ameliore la qualite du graphe de connaissances :
              classification fine des concepts, detection des relations entre entites, et consolidation des informations multi-sources.
            </Text>
            <HStack spacing={1} justify="center" flexWrap="wrap" pt={2} borderTop="1px solid" borderColor="whiteAlpha.100">
              <FlowStep name="Import" color="yellow" isActive={false} />
              <FlowStep name="Classification" color="purple" isActive={isJobRunning && currentStep === 'Classification'} />
              <FlowStep name="Relations" color="blue" isActive={isJobRunning && currentStep === 'Relations'} />
              <FlowStep name="Consolidation" color="green" isActive={isJobRunning && currentStep === 'Consolidation'} />
              <FlowStep name="Deduplication" color="cyan" isActive={isJobRunning && currentStep === 'Deduplication'} />
              <FlowStep name="KG Enrichi" color="brand" isLast isActive={false} />
            </HStack>
          </Box>
        )
      })()}

      {/* Active Job */}
      {activeJob && <JobProgress job={activeJob} onCancel={handleCancel} onClear={handleClear} isCancelling={isCancelling} />}

      {/* Main Metrics - Prominent */}
      <Box bg="whiteAlpha.30" rounded="xl" p={3} mb={3} border="1px solid" borderColor="whiteAlpha.100">
        <Flex gap={3} flexWrap="wrap" justify="space-between">
          {/* KG Core Metrics */}
          <HStack spacing={3} flexWrap="wrap">
            <MetricCard label="ProtoConcepts" value={status?.proto_concepts || 0} icon={FiBox} color="yellow" />
            <MetricCard label="Canonical" value={status?.canonical_concepts || 0} icon={FiGrid} color="green" />
            <MetricCard label="RawAssertions" value={status?.raw_assertions || 0} icon={FiFileText} color="orange" />
            <MetricCard label="RawClaims" value={status?.raw_claims || 0} icon={FiFileText} color="blue" />
            <MetricCard label="CanonicalRels" value={status?.canonical_relations || 0} icon={FiLink} color="purple" />
            <MetricCard label="CanonicalClaims" value={status?.canonical_claims || 0} icon={FiTarget} color="teal" />
          </HStack>

          {/* ER Stats - Secondary */}
          <VStack align="flex-end" spacing={1}>
            <Text fontSize="xs" color="text.muted" fontWeight="medium">Entity Resolution</Text>
            <HStack spacing={2}>
              <StatItem label="Standalone" value={status?.er_standalone_concepts || 0} icon={FiGrid} color="cyan" />
              <StatItem label="Merged" value={status?.er_merged_concepts || 0} icon={FiGitMerge} color="cyan" />
              <StatItem label="Pending" value={status?.er_pending_proposals || 0} icon={FiLayers} color="cyan" />
            </HStack>
          </VStack>
        </Flex>
      </Box>

      {/* Phases Table */}
      <Box bg="whiteAlpha.50" rounded="lg" overflow="hidden">
        <Table size="sm" variant="unstyled">
          <Thead>
            <Tr borderBottom="1px solid" borderColor="whiteAlpha.100">
              <Th py={2} px={3} color="text.muted" fontSize="xs" fontWeight="medium">Phase</Th>
              <Th py={2} px={3} color="text.muted" fontSize="xs" fontWeight="medium">Description</Th>
              <Th py={2} px={3} color="text.muted" fontSize="xs" fontWeight="medium" isNumeric>Resultat</Th>
              <Th py={2} px={3} color="text.muted" fontSize="xs" fontWeight="medium" w="100px"></Th>
            </Tr>
          </Thead>
          <Tbody>
            {phases.map((phase) => {
              const result = phaseResults[phase.id]
              const isRunning = runningPhase === phase.id
              return (
                <Tr key={phase.id} borderBottom="1px solid" borderColor="whiteAlpha.50" _hover={{ bg: 'whiteAlpha.50' }}>
                  <Td py={2} px={3}>
                    <HStack spacing={2}>
                      <Icon as={phase.icon} boxSize={3.5} color={`${phase.color}.400`} />
                      <Text fontSize="sm" fontWeight="medium" color="text.primary">{phase.shortName}</Text>
                    </HStack>
                  </Td>
                  <Td py={2} px={3}>
                    <Text fontSize="xs" color="text.muted">{phase.name}</Text>
                  </Td>
                  <Td py={2} px={3} isNumeric>
                    {result && (
                      <HStack spacing={2} justify="flex-end">
                        <Icon as={result.success ? FiCheckCircle : FiAlertTriangle} boxSize={3} color={result.success ? 'green.400' : 'red.400'} />
                        <Text fontSize="xs" fontFamily="mono" color="text.muted">
                          {result.items_processed}→{result.items_created}
                        </Text>
                        <Text fontSize="xs" color="text.muted">{(result.execution_time_ms / 1000).toFixed(1)}s</Text>
                      </HStack>
                    )}
                  </Td>
                  <Td py={2} px={3}>
                    <Button
                      size="xs"
                      variant="ghost"
                      colorScheme={phase.color}
                      leftIcon={<FiPlay />}
                      onClick={() => runPhase.mutate({ endpoint: phase.endpoint, phaseId: phase.id })}
                      isLoading={isRunning}
                      isDisabled={!!hasActiveJob}
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

      {/* KG Quality Footer */}
      {qualityStats && (
        <Box mt={3} bg="whiteAlpha.50" rounded="lg" px={4} py={2} border="1px solid" borderColor="whiteAlpha.100">
          <Flex gap={6} flexWrap="wrap" align="center">
            <HStack spacing={2}>
              <Text fontSize="xs" color="text.muted" fontWeight="semibold">Qualité KG</Text>
              <Text fontSize="xs" color="whiteAlpha.300">|</Text>
              <Text fontSize="xs" color="text.muted">Claims:</Text>
              <QualityPill label="validés" value={qualityStats.claims_validated} color="green" tooltip="Confirmés par 2+ documents sources" />
              <QualityPill label="candidats" value={qualityStats.claims_candidate} color="yellow" tooltip="Issus d'un seul document source" />
              {qualityStats.claims_conflicting > 0 && (
                <QualityPill label="conflits" value={qualityStats.claims_conflicting} color="red" tooltip="Valeurs contradictoires entre documents" />
              )}
            </HStack>
            <HStack spacing={2}>
              <Text fontSize="xs" color="text.muted">Relations:</Text>
              <QualityPill label="validées" value={qualityStats.relations_validated} color="green" tooltip="Confirmées par 2+ documents, typed edges créés" />
              <QualityPill label="candidates" value={qualityStats.relations_candidate} color="yellow" tooltip="Issues d'un seul document source" />
              {qualityStats.relations_ambiguous > 0 && (
                <QualityPill label="ambiguës" value={qualityStats.relations_ambiguous} color="orange" tooltip="Type de relation incertain (delta < 0.15)" />
              )}
            </HStack>
          </Flex>
        </Box>
      )}
    </Box>
  )
}
