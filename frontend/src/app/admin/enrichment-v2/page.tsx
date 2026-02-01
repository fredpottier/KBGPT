'use client'

/**
 * OSMOSE Pipeline V2 - Interface d'Enrichissement Stratifié
 * ============================================================
 * Ref: doc/ongoing/ARCH_STRATIFIED_PIPELINE_V2.md
 *
 * Interface pour le nouveau Pipeline V2 (style page legacy):
 * - Pass 0: Structural Graph (depuis cache)
 * - Pass 1: Lecture Stratifiée (Subject → Themes → Concepts)
 * - Pass 2: Enrichissement (Relations)
 * - Pass 3: Consolidation Corpus
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
  Checkbox,
} from '@chakra-ui/react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  FiRefreshCw,
  FiCheckCircle,
  FiAlertTriangle,
  FiPlay,
  FiArrowRight,
  FiLayers,
  FiActivity,
  FiStopCircle,
  FiClock,
  FiXCircle,
  FiX,
  FiBox,
  FiFileText,
  FiBookOpen,
  FiHash,
  FiDatabase,
  FiCpu,
  FiLink,
  FiTarget,
  FiGitMerge,
  FiInfo,
} from 'react-icons/fi'
import { apiClient } from '@/lib/api'


// ============================================================================
// TYPES
// ============================================================================

interface PipelineV2Stats {
  // Document-level
  documents_count: number
  subjects_count: number
  themes_count: number
  concepts_count: number
  informations_count: number
  assertion_logs_count: number
  // Corpus-level
  canonical_concepts_count: number
  relations_count: number
}

interface CachedDocument {
  cache_file: string
  cache_path: string
  document_id: string
  cache_version: string
  created_at: string | null
  size_bytes: number
}

interface ReprocessStatus {
  status: 'idle' | 'running' | 'completed' | 'failed' | 'cancelled'
  total_documents: number
  processed: number
  failed: number
  current_document: string | null
  current_phase: string | null
  progress_percent: number
  started_at: string | null
  errors: string[]
}

interface PhaseConfig {
  id: string
  name: string
  shortName: string
  pass: number
  icon: any
  color: string
  description: string
}


// ============================================================================
// CONFIG
// ============================================================================

const phases: PhaseConfig[] = [
  {
    id: 'pass0',
    name: 'Structural Graph',
    shortName: 'Structure',
    pass: 0,
    icon: FiDatabase,
    color: 'gray',
    description: 'Charge le cache extraction (DocItems, Chunks, Sections)'
  },
  {
    id: 'pass1',
    name: 'Lecture Stratifiée',
    shortName: 'Stratifié',
    pass: 1,
    icon: FiLayers,
    color: 'purple',
    description: 'Extrait Subject → Themes → Concepts → Informations'
  },
  {
    id: 'pass2',
    name: 'Enrichissement',
    shortName: 'Relations',
    pass: 2,
    icon: FiLink,
    color: 'blue',
    description: 'Détecte les relations entre concepts'
  },
  {
    id: 'pass3',
    name: 'Consolidation',
    shortName: 'Corpus',
    pass: 3,
    icon: FiGitMerge,
    color: 'orange',
    description: 'Fusionne en CanonicalConcepts cross-documents'
  },
]


// ============================================================================
// COMPONENTS
// ============================================================================

// Metric card compact
const MetricCard = ({
  label,
  value,
  icon,
  color = 'gray',
  tooltip
}: {
  label: string
  value: number
  icon: any
  color?: string
  tooltip?: string
}) => (
  <Tooltip label={tooltip} placement="top" hasArrow isDisabled={!tooltip}>
    <Box
      bg="#1e293b"
      border="1px solid"
      borderColor={`${color}.700`}
      rounded="lg"
      px={3}
      py={2}
      minW="100px"
    >
      <HStack spacing={2}>
        <Box
          w={7}
          h={7}
          rounded="md"
          bg={`${color}.900`}
          display="flex"
          alignItems="center"
          justifyContent="center"
        >
          <Icon as={icon} boxSize={4} color={`${color}.400`} />
        </Box>
        <Box>
          <Text fontSize="lg" fontWeight="bold" color="#f1f5f9" fontFamily="mono" lineHeight={1}>
            {value.toLocaleString()}
          </Text>
          <Text fontSize="xs" color="#94a3b8" lineHeight={1.2}>{label}</Text>
        </Box>
      </HStack>
    </Box>
  </Tooltip>
)

// Pass block for workflow
const PassBlock = ({
  passNum,
  label,
  icon,
  color,
  isActive = false,
  isComplete = false
}: {
  passNum: number
  label: string
  icon: any
  color: string
  isActive?: boolean
  isComplete?: boolean
}) => (
  <HStack
    spacing={2}
    bg={`${color}.900`}
    px={3}
    py={2}
    rounded="lg"
    border="2px solid"
    borderColor={isActive ? `${color}.400` : isComplete ? 'green.600' : `${color}.700`}
    opacity={isComplete ? 0.7 : 1}
  >
    {isActive ? (
      <Spinner size="sm" color={`${color}.400`} />
    ) : isComplete ? (
      <Icon as={FiCheckCircle} boxSize={4} color="green.400" />
    ) : (
      <Icon as={icon} boxSize={4} color={`${color}.400`} />
    )}
    <Box>
      <Badge size="xs" colorScheme={color} variant="solid">Pass {passNum}</Badge>
      <Text fontSize="xs" color={`${color}.200`} fontWeight="medium">{label}</Text>
    </Box>
  </HStack>
)

// Progress bar for reprocessing
const ReprocessProgress = ({
  status,
  onCancel
}: {
  status: ReprocessStatus
  onCancel: () => void
}) => {
  const isActive = status.status === 'running'
  const statusConfig = {
    idle: { color: 'gray', icon: FiClock, text: 'Inactif' },
    running: { color: 'blue', icon: FiActivity, text: 'En cours' },
    completed: { color: 'green', icon: FiCheckCircle, text: 'Terminé' },
    failed: { color: 'red', icon: FiXCircle, text: 'Échec' },
    cancelled: { color: 'gray', icon: FiStopCircle, text: 'Annulé' },
  }[status.status]

  if (status.status === 'idle') return null

  return (
    <Box
      bg="#1e293b"
      border="2px solid"
      borderColor={`${statusConfig.color}.500`}
      rounded="lg"
      p={3}
      mb={4}
    >
      <Flex justify="space-between" align="center" mb={2}>
        <HStack spacing={2}>
          {isActive ? (
            <Spinner size="sm" color={`${statusConfig.color}.400`} />
          ) : (
            <Icon as={statusConfig.icon} boxSize={4} color={`${statusConfig.color}.400`} />
          )}
          <Badge colorScheme={statusConfig.color}>{statusConfig.text}</Badge>
          {status.current_phase && (
            <Text fontSize="sm" color={`${statusConfig.color}.300`}>
              • {status.current_phase}
            </Text>
          )}
          {status.current_document && (
            <Text fontSize="xs" color="#94a3b8" fontFamily="mono">
              ({status.current_document.slice(0, 30)}...)
            </Text>
          )}
        </HStack>
        <HStack spacing={2}>
          <Text fontSize="sm" color="#94a3b8">
            {status.processed}/{status.total_documents}
          </Text>
          {isActive && (
            <Button
              size="xs"
              colorScheme="red"
              variant="outline"
              onClick={onCancel}
              leftIcon={<FiStopCircle />}
            >
              Stop
            </Button>
          )}
        </HStack>
      </Flex>
      <Progress
        value={status.progress_percent}
        size="sm"
        colorScheme={statusConfig.color}
        rounded="full"
        hasStripe={isActive}
        isAnimated={isActive}
      />
      {status.errors.length > 0 && (
        <Text fontSize="xs" color="red.400" mt={2}>
          Erreurs: {status.errors.slice(0, 2).join(', ')}
          {status.errors.length > 2 && ` (+${status.errors.length - 2})`}
        </Text>
      )}
    </Box>
  )
}


// ============================================================================
// MAIN COMPONENT
// ============================================================================

export default function EnrichmentV2Page() {
  const toast = useToast()
  const queryClient = useQueryClient()
  const pollingRef = useRef<NodeJS.Timeout | null>(null)

  const [selectedDocs, setSelectedDocs] = useState<Set<string>>(new Set())

  // Fetch Pipeline V2 stats from Neo4j
  const { data: stats, isLoading: statsLoading, refetch: refetchStats } = useQuery({
    queryKey: ['pipeline-v2', 'stats'],
    queryFn: async () => {
      const res = await apiClient.get<PipelineV2Stats>('/v2/stats/detailed', { timeout: 15000 })
      if (!res.success) {
        // Fallback to basic stats
        const basicRes = await apiClient.get<any>('/v2/stats', { timeout: 15000 })
        return {
          documents_count: 0,
          subjects_count: 0,
          themes_count: 0,
          concepts_count: basicRes.data?.concepts_count || 0,
          informations_count: basicRes.data?.informations_count || 0,
          assertion_logs_count: 0,
          canonical_concepts_count: basicRes.data?.canonical_concepts_count || 0,
          relations_count: basicRes.data?.relations_count || 0,
        }
      }
      return res.data
    },
    refetchInterval: 10000,
    retry: 3,
    retryDelay: 2000,
    refetchOnWindowFocus: true,
  })

  // Fetch cached documents
  const { data: cachedDocs, isLoading: cacheLoading, refetch: refetchCache } = useQuery({
    queryKey: ['cached-documents'],
    queryFn: async () => {
      const res = await apiClient.get<CachedDocument[]>('/v2/reprocess/cache', { timeout: 15000 })
      if (!res.success) return []
      return res.data || []
    },
    retry: 2,
    retryDelay: 1000,
  })

  // Fetch reprocess status - uses shorter timeout since this should be a fast endpoint
  const { data: reprocessStatus, refetch: refetchStatus, isError: statusError } = useQuery({
    queryKey: ['reprocess-status'],
    queryFn: async () => {
      const res = await apiClient.get<ReprocessStatus>('/v2/reprocess/status', { timeout: 10000 })
      if (!res.success) return { status: 'idle' as const, total_documents: 0, processed: 0, failed: 0, current_document: null, current_phase: null, progress_percent: 0, started_at: null, errors: [] }
      return res.data
    },
    refetchInterval: (query) => {
      const status = query.state.data?.status
      // Poll more frequently when running, less when idle
      return status === 'running' ? 2000 : 10000
    },
    retry: 5,  // More retries for status endpoint
    retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 10000),
    refetchOnWindowFocus: true,
    refetchIntervalInBackground: true,  // Continue polling even when tab not focused
  })

  // Start reprocessing
  const startReprocess = useMutation({
    mutationFn: async ({ runPass1, runPass2 }: { runPass1: boolean; runPass2: boolean }) => {
      const res = await apiClient.post('/v2/reprocess/start', {
        cache_paths: Array.from(selectedDocs),
        run_pass1: runPass1,
        run_pass2: runPass2,
        run_pass3: false,
        tenant_id: 'default',
      })
      if (!res.success) throw new Error(res.error || 'Request failed')
      return res.data
    },
    onSuccess: (data: any) => {
      toast({
        title: 'Traitement lancé',
        description: `${data?.total_documents || selectedDocs.size} document(s)`,
        status: 'success',
        duration: 3000,
      })
      setSelectedDocs(new Set())
      refetchStatus()
    },
    onError: (e: any) => {
      toast({ title: 'Erreur', description: e.message, status: 'error', duration: 3000 })
    },
  })

  // Cancel reprocessing
  const cancelReprocess = useMutation({
    mutationFn: async () => {
      const res = await apiClient.post('/v2/reprocess/cancel')
      if (!res.success) throw new Error(res.error || 'Request failed')
      return res.data
    },
    onSuccess: () => {
      toast({ title: 'Annulé', status: 'info', duration: 2000 })
      refetchStatus()
    },
  })

  // Run Pass 3 consolidation
  const runPass3 = useMutation({
    mutationFn: async () => {
      const res = await apiClient.post('/v2/consolidate', {
        mode: 'batch',
        tenant_id: 'default',
      })
      if (!res.success) throw new Error(res.error || 'Consolidation failed')
      return res.data
    },
    onSuccess: (data: any) => {
      toast({
        title: 'Pass 3 terminée',
        description: `${data?.canonical_concepts || 0} CanonicalConcepts créés`,
        status: 'success',
        duration: 5000,
      })
      refetchStats()
    },
    onError: (e: any) => {
      toast({ title: 'Erreur Pass 3', description: e.message, status: 'error', duration: 5000 })
    },
  })

  // Toggle document selection
  const toggleDoc = (path: string) => {
    setSelectedDocs(prev => {
      const next = new Set(prev)
      if (next.has(path)) {
        next.delete(path)
      } else {
        next.add(path)
      }
      return next
    })
  }

  // Select all
  const selectAll = () => {
    setSelectedDocs(new Set(cachedDocs?.map(d => d.cache_path) || []))
  }

  // Deselect all
  const deselectAll = () => {
    setSelectedDocs(new Set())
  }

  // Determine active phase from status
  const getActivePhase = (): string | null => {
    if (reprocessStatus?.status !== 'running') return null
    const phase = reprocessStatus.current_phase?.toUpperCase()
    if (phase?.includes('LOADING') || phase?.includes('PASS_0')) return 'pass0'
    if (phase?.includes('PASS_1')) return 'pass1'
    if (phase?.includes('PASS_2')) return 'pass2'
    if (phase?.includes('PASS_3')) return 'pass3'
    return null
  }

  const activePhase = getActivePhase()

  if (statsLoading) {
    return (
      <Center h="400px">
        <VStack spacing={3}>
          <Spinner color="purple.500" size="lg" />
          <Text color="#94a3b8">Chargement Pipeline V2...</Text>
        </VStack>
      </Center>
    )
  }

  return (
    <Box maxW="1400px" mx="auto" p={4}>
      {/* Header */}
      <Flex justify="space-between" align="center" mb={4}>
        <HStack spacing={3}>
          <Box
            w={10}
            h={10}
            rounded="lg"
            bgGradient="linear(to-br, purple.500, cyan.500)"
            display="flex"
            alignItems="center"
            justifyContent="center"
          >
            <Icon as={FiLayers} boxSize={5} color="white" />
          </Box>
          <Box>
            <Text fontSize="xl" fontWeight="bold" color="#f1f5f9" lineHeight={1}>
              Pipeline V2 - Lecture Stratifiée
            </Text>
            <Text fontSize="sm" color="#94a3b8">
              Subject → Themes → Concepts → Informations
            </Text>
          </Box>
        </HStack>
        <HStack spacing={2}>
          <Badge colorScheme="purple" variant="subtle">BETA</Badge>
          <IconButton
            aria-label="Refresh"
            icon={<FiRefreshCw />}
            size="sm"
            variant="ghost"
            onClick={() => {
              refetchStats()
              refetchCache()
              refetchStatus()
            }}
          />
        </HStack>
      </Flex>

      {/* Workflow Visualization */}
      <Box bg="#1e293b" border="1px solid" borderColor="#334155" rounded="xl" p={4} mb={4}>
        <Flex gap={3} align="center" justify="center" flexWrap="wrap">
          {phases.map((phase, i) => (
            <HStack key={phase.id} spacing={2}>
              <PassBlock
                passNum={phase.pass}
                label={phase.shortName}
                icon={phase.icon}
                color={phase.color}
                isActive={activePhase === phase.id}
                isComplete={false}
              />
              {i < phases.length - 1 && (
                <Icon as={FiArrowRight} boxSize={4} color="#64748b" />
              )}
            </HStack>
          ))}
        </Flex>
      </Box>

      {/* Stats Grid */}
      <Flex gap={3} mb={4} flexWrap="wrap">
        <MetricCard
          label="Subjects"
          value={stats?.subjects_count || 0}
          icon={FiTarget}
          color="purple"
          tooltip="1 Subject par document"
        />
        <MetricCard
          label="Themes"
          value={stats?.themes_count || 0}
          icon={FiBookOpen}
          color="cyan"
          tooltip="Thèmes majeurs détectés"
        />
        <MetricCard
          label="Concepts"
          value={stats?.concepts_count || 0}
          icon={FiBox}
          color="green"
          tooltip="max 15 par document"
        />
        <MetricCard
          label="Informations"
          value={stats?.informations_count || 0}
          icon={FiInfo}
          color="blue"
          tooltip="Assertions promues"
        />
        <MetricCard
          label="AssertionLog"
          value={stats?.assertion_logs_count || 0}
          icon={FiFileText}
          color="gray"
          tooltip="Journal des décisions"
        />
        <MetricCard
          label="Relations"
          value={stats?.relations_count || 0}
          icon={FiLink}
          color="orange"
          tooltip="Relations validées"
        />
      </Flex>

      {/* Reprocess Progress */}
      {reprocessStatus && reprocessStatus.status !== 'idle' && (
        <ReprocessProgress
          status={reprocessStatus}
          onCancel={() => cancelReprocess.mutate()}
        />
      )}

      {/* Documents Table */}
      <Box bg="#1e293b" border="1px solid" borderColor="#334155" rounded="xl" overflow="hidden">
        {/* Header */}
        <Flex
          justify="space-between"
          align="center"
          px={4}
          py={3}
          borderBottom="1px solid"
          borderColor="#334155"
        >
          <HStack spacing={3}>
            <Icon as={FiDatabase} color="#22d3ee" />
            <Text fontSize="sm" fontWeight="semibold" color="#f1f5f9">
              Documents en Cache ({cachedDocs?.length || 0})
            </Text>
            {selectedDocs.size > 0 && (
              <Badge colorScheme="cyan">{selectedDocs.size} sélectionné(s)</Badge>
            )}
          </HStack>
          <HStack spacing={2}>
            <Button size="xs" variant="ghost" onClick={selectAll}>
              Tout
            </Button>
            <Button size="xs" variant="ghost" onClick={deselectAll}>
              Aucun
            </Button>
            <Divider orientation="vertical" h="20px" borderColor="#475569" />
            <Button
              size="sm"
              colorScheme="purple"
              leftIcon={<FiPlay />}
              onClick={() => startReprocess.mutate({ runPass1: true, runPass2: false })}
              isLoading={startReprocess.isPending}
              isDisabled={selectedDocs.size === 0 || reprocessStatus?.status === 'running'}
            >
              Pass 1
            </Button>
            <Button
              size="sm"
              colorScheme="blue"
              leftIcon={<FiLink />}
              onClick={() => startReprocess.mutate({ runPass1: true, runPass2: true })}
              isLoading={startReprocess.isPending}
              isDisabled={selectedDocs.size === 0 || reprocessStatus?.status === 'running'}
            >
              Pass 1+2
            </Button>
            <Tooltip label="Pass 2 seul - Relations entre concepts (requiert Pass 1 déjà exécuté)" placement="top">
              <Button
                size="sm"
                colorScheme="cyan"
                variant="outline"
                leftIcon={<FiLink />}
                onClick={() => startReprocess.mutate({ runPass1: false, runPass2: true })}
                isLoading={startReprocess.isPending}
                isDisabled={selectedDocs.size === 0 || reprocessStatus?.status === 'running'}
              >
                Pass 2
              </Button>
            </Tooltip>
            <Divider orientation="vertical" h="20px" borderColor="#475569" />
            <Tooltip label="Consolidation corpus - fusionne les concepts similaires cross-documents" placement="top">
              <Button
                size="sm"
                colorScheme="orange"
                leftIcon={<FiGitMerge />}
                onClick={() => runPass3.mutate()}
                isLoading={runPass3.isPending}
                isDisabled={reprocessStatus?.status === 'running'}
              >
                Pass 3
              </Button>
            </Tooltip>
            <IconButton
              aria-label="Refresh"
              icon={<FiRefreshCw />}
              size="sm"
              variant="ghost"
              onClick={() => refetchCache()}
            />
          </HStack>
        </Flex>

        {/* Table */}
        {cacheLoading ? (
          <Center py={8}>
            <Spinner color="cyan.400" />
          </Center>
        ) : !cachedDocs?.length ? (
          <Center py={8}>
            <VStack spacing={2}>
              <Icon as={FiDatabase} boxSize={8} color="#64748b" />
              <Text color="#94a3b8">Aucun document en cache</Text>
              <Text fontSize="xs" color="#64748b">
                Importez des documents pour commencer
              </Text>
            </VStack>
          </Center>
        ) : (
          <Box maxH="400px" overflowY="auto">
            <Table size="sm">
              <Thead position="sticky" top={0} bg="#1e293b" zIndex={1}>
                <Tr>
                  <Th w="40px" borderColor="#334155"></Th>
                  <Th borderColor="#334155" color="#94a3b8">Document</Th>
                  <Th borderColor="#334155" color="#94a3b8">Version</Th>
                  <Th borderColor="#334155" color="#94a3b8" isNumeric>Taille</Th>
                </Tr>
              </Thead>
              <Tbody>
                {cachedDocs.map((doc) => (
                  <Tr
                    key={doc.cache_path}
                    _hover={{ bg: '#334155' }}
                    cursor="pointer"
                    onClick={() => toggleDoc(doc.cache_path)}
                    bg={selectedDocs.has(doc.cache_path) ? 'cyan.900' : undefined}
                  >
                    <Td borderColor="#334155">
                      <Checkbox
                        isChecked={selectedDocs.has(doc.cache_path)}
                        onChange={() => toggleDoc(doc.cache_path)}
                        colorScheme="cyan"
                      />
                    </Td>
                    <Td borderColor="#334155">
                      <Text fontSize="sm" color="#f1f5f9" noOfLines={1}>
                        {doc.document_id.length > 60
                          ? doc.document_id.substring(0, 60) + '...'
                          : doc.document_id}
                      </Text>
                    </Td>
                    <Td borderColor="#334155">
                      <Badge
                        colorScheme={doc.cache_version === 'v4' ? 'green' : 'gray'}
                        size="sm"
                      >
                        {doc.cache_version}
                      </Badge>
                    </Td>
                    <Td borderColor="#334155" isNumeric>
                      <Text fontSize="xs" color="#94a3b8">
                        {Math.round(doc.size_bytes / 1024)} KB
                      </Text>
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          </Box>
        )}
      </Box>

      {/* Help Footer */}
      <Box mt={4} bg="#1e293b" rounded="lg" px={4} py={3} border="1px solid" borderColor="#334155">
        <Text fontSize="xs" color="#94a3b8">
          <Text as="span" fontWeight="semibold" color="purple.300">Pass 0</Text>: Charge le cache extraction (DocItems, Chunks).{' '}
          <Text as="span" fontWeight="semibold" color="purple.300">Pass 1</Text>: Lecture Stratifiée - extrait Subject, Themes, Concepts (max 15), Informations.{' '}
          <Text as="span" fontWeight="semibold" color="blue.300">Pass 2</Text>: Relations inter-concepts.{' '}
          <Text as="span" fontWeight="semibold" color="orange.300">Pass 3</Text>: Consolidation corpus.
        </Text>
      </Box>
    </Box>
  )
}
