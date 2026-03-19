'use client'

/**
 * Page Admin - Pipeline Claim-First (Pivot Épistémique)
 *
 * Interface pour lancer et monitorer le nouveau pipeline Claim-First.
 */

import { useState, useEffect, useCallback } from 'react'
import {
  Box,
  Heading,
  Text,
  Button,
  VStack,
  HStack,
  Badge,
  SimpleGrid,
  Spinner,
  Progress,
  Checkbox,
  Table,
  Th,
  Td,
  Tbody,
  Tr,
  Thead,
  Icon,
  Flex,
  useToast,
  Center,
  Tooltip,
  IconButton,
  Link,
} from '@chakra-ui/react'
import NextLink from 'next/link'
import {
  FiPlay,
  FiRefreshCw,
  FiFileText,
  FiActivity,
  FiCheckCircle,
  FiDatabase,
  FiLayers,
  FiLink2,
  FiAlertTriangle,
  FiTarget,
  FiXCircle,
  FiArchive,
  FiClock,
  FiZap,
  FiStopCircle,
  FiLoader,
  FiExternalLink,
} from 'react-icons/fi'
import { useAuth } from '@/contexts/AuthContext'
import { apiClient } from '@/lib/api'

// Types
interface ClaimFirstStatus {
  claims: number
  entities: number
  facets: number
  clusters: number
  // Subject Resolution (INV-8, INV-9)
  doc_contexts: number
  subject_anchors: number
  // Relations (Passage/SUPPORTED_BY retirés — Chantier 0)
  about: number
  has_facet: number
  in_cluster: number
  contradicts: number
  refines: number
  qualifies: number
  about_subject: number
  // Documents
  documents_available: number
  documents_processed: number
  // Job status
  job_running: boolean
  current_job_id: string | null
  current_phase: string | null
  worker_state?: {
    processed: number
    total_documents: number
    total_claims: number
    total_entities: number
    current_filename: string
    phase: string
    failed: number
  } | null
}

interface ArchiveResult {
  mode: string
  total_claims: number
  isolated_count?: number
  isolated_percentage?: number
  newly_archived?: number
  total_archived?: number
  message: string
}

interface CrossDocResult {
  mode: string
  claims_with_sf: number
  documents: number
  chains_detected?: number
  chains_persisted?: number
  total_cross_doc?: number
  total_intra_doc?: number
  hubs_excluded?: number
  existing_intra?: number
  existing_cross?: number
  message: string
}

interface CanonResult {
  mode: string
  entities_initial: number
  version_merges: number
  containment_merges: number
  total_merges: number
  entities_after?: number
  hubs_annotated?: number
  message: string
}

interface AvailableDocument {
  doc_id: string
  filename: string
  cached_at: string | null
}

interface JobStatus {
  job_id: string
  status: string
  phase: string | null
  current_document: string | null
  current_filename: string | null
  processed: number
  failed: number
  skipped: number
  total: number
  total_claims: number
  total_entities: number
  errors: string[]
  started_at: string | null
  completed_at: string | null
  elapsed_seconds: number | null
}

// Metric card (same style as enrichment-v2)
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
          <Text fontSize="lg" fontWeight="bold" color="#f1f5f9" lineHeight={1}>
            {(value ?? 0).toLocaleString()}
          </Text>
          <Text fontSize="xs" color="#94a3b8">{label}</Text>
        </Box>
      </HStack>
    </Box>
  </Tooltip>
)

// Relation stat display
const RelationStat = ({ label, value, color = 'gray' }: { label: string; value: number; color?: string }) => (
  <VStack spacing={0}>
    <Text fontWeight="bold" fontSize="lg" color={(value ?? 0) > 0 ? `${color}.400` : '#64748b'}>
      {(value ?? 0).toLocaleString()}
    </Text>
    <Text fontSize="xs" color="#64748b">{label}</Text>
  </VStack>
)

// Main Component
export default function ClaimFirstPage() {
  const { isAdmin, isLoading: authLoading } = useAuth()
  const toast = useToast()
  const [status, setStatus] = useState<ClaimFirstStatus | null>(null)
  const [documents, setDocuments] = useState<AvailableDocument[]>([])
  const [selectedDocs, setSelectedDocs] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(true)
  const [jobLoading, setJobLoading] = useState(false)
  const [currentJob, setCurrentJob] = useState<JobStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [archiveLoading, setArchiveLoading] = useState(false)
  const [archiveResult, setArchiveResult] = useState<ArchiveResult | null>(null)
  const [crossDocLoading, setCrossDocLoading] = useState(false)
  const [crossDocResult, setCrossDocResult] = useState<CrossDocResult | null>(null)
  const [canonLoading, setCanonLoading] = useState(false)
  const [canonResult, setCanonResult] = useState<CanonResult | null>(null)
  const [importedDocs, setImportedDocs] = useState<Record<string, number>>({})

  // Load status and documents
  const loadData = useCallback(async () => {
    try {
      setLoading(true)
      setError(null)

      const [statusRes, docsRes, importedRes] = await Promise.all([
        apiClient.get<ClaimFirstStatus>('/claimfirst/status'),
        apiClient.get<{ documents: AvailableDocument[]; count: number }>('/claimfirst/documents?limit=200'),
        apiClient.get<{ imported: Record<string, number>; count: number }>('/claimfirst/imported-doc-ids'),
      ])

      if (statusRes.success && statusRes.data) {
        setStatus(statusRes.data)

        if (statusRes.data.current_job_id) {
          // Essayer de charger le job RQ
          const jobRes = await apiClient.get<JobStatus>(`/claimfirst/jobs/${statusRes.data.current_job_id}`)
          if (jobRes.success && jobRes.data) {
            setCurrentJob(jobRes.data)
          } else if (statusRes.data.worker_state && statusRes.data.job_running) {
            // Fallback : construire un JobStatus depuis worker_state (job RQ perdu après restart)
            const ws = statusRes.data.worker_state
            setCurrentJob({
              job_id: statusRes.data.current_job_id,
              status: 'started',
              phase: ws.phase || statusRes.data.current_phase || 'PROCESSING',
              current_filename: ws.current_filename || '',
              processed: ws.processed,
              total: ws.total_documents,
              total_claims: ws.total_claims,
              total_entities: ws.total_entities,
              failed: ws.failed,
              errors: [],
              skipped: 0,
            } as JobStatus)
          }
        } else {
          setCurrentJob(null)
        }
      } else {
        setError(statusRes.error || 'Failed to fetch status')
      }

      if (docsRes.success && docsRes.data) {
        setDocuments(docsRes.data.documents || [])
      }

      if (importedRes.success && importedRes.data) {
        setImportedDocs(importedRes.data.imported || {})
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!authLoading) {
      loadData()
    }
  }, [authLoading, loadData])

  // Poll job status if running
  useEffect(() => {
    if (!currentJob) return
    if (currentJob.status === 'finished' || currentJob.status === 'failed') return

    const interval = setInterval(async () => {
      try {
        const jobRes = await apiClient.get<JobStatus>(`/claimfirst/jobs/${currentJob.job_id}`)
        if (jobRes.success && jobRes.data) {
          setCurrentJob(jobRes.data)
          if (jobRes.data.status === 'finished' || jobRes.data.status === 'failed') {
            loadData()
          }
        }
      } catch (err) {
        console.error('Failed to poll job status:', err)
      }
    }, 2000)

    return () => clearInterval(interval)
  }, [currentJob, loadData])

  // Handle document selection
  const toggleDoc = (docId: string) => {
    const newSet = new Set(selectedDocs)
    if (newSet.has(docId)) {
      newSet.delete(docId)
    } else {
      newSet.add(docId)
    }
    setSelectedDocs(newSet)
  }

  const selectAll = () => setSelectedDocs(new Set(documents.map((d) => d.doc_id)))
  const selectNone = () => setSelectedDocs(new Set())
  const selectNewOnly = () => setSelectedDocs(new Set(documents.filter((d) => !importedDocs[d.doc_id]).map((d) => d.doc_id)))

  // Handle job creation
  const handleProcessSelected = async () => {
    if (selectedDocs.size === 0) return
    try {
      setJobLoading(true)
      setError(null)
      const res = await apiClient.post<JobStatus>('/claimfirst/jobs', {
        doc_ids: Array.from(selectedDocs),
      })
      if (res.success && res.data) {
        setCurrentJob(res.data)
        setSelectedDocs(new Set())
        toast({
          title: 'Job créé',
          description: `Traitement de ${res.data.total} documents lancé`,
          status: 'success',
          duration: 3000,
        })
      } else {
        throw new Error(res.error || 'Failed to create job')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create job')
      toast({
        title: 'Erreur',
        description: err instanceof Error ? err.message : 'Erreur inconnue',
        status: 'error',
        duration: 5000,
      })
    } finally {
      setJobLoading(false)
    }
  }

  const handleProcessAll = async () => {
    try {
      setJobLoading(true)
      setError(null)
      const res = await apiClient.post<JobStatus>('/claimfirst/process-all', {})
      if (res.success && res.data) {
        setCurrentJob(res.data)
        toast({
          title: 'Job créé',
          description: `Traitement de ${res.data.total} documents lancé`,
          status: 'success',
          duration: 3000,
        })
      } else {
        throw new Error(res.error || 'Failed to process all')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to process all')
      toast({
        title: 'Erreur',
        description: err instanceof Error ? err.message : 'Erreur inconnue',
        status: 'error',
        duration: 5000,
      })
    } finally {
      setJobLoading(false)
    }
  }

  // Archive isolated claims (Phase 1B)
  const handleArchiveDryRun = async () => {
    try {
      setArchiveLoading(true)
      setArchiveResult(null)
      const res = await apiClient.post<ArchiveResult>('/claimfirst/archive-isolated?execute=false', {})
      if (res.success && res.data) {
        setArchiveResult(res.data)
      } else {
        throw new Error(res.error || 'Échec du dry-run')
      }
    } catch (err) {
      toast({
        title: 'Erreur',
        description: err instanceof Error ? err.message : 'Erreur inconnue',
        status: 'error',
        duration: 5000,
      })
    } finally {
      setArchiveLoading(false)
    }
  }

  const handleArchiveExecute = async () => {
    try {
      setArchiveLoading(true)
      const res = await apiClient.post<ArchiveResult>('/claimfirst/archive-isolated?execute=true', {})
      if (res.success && res.data) {
        setArchiveResult(res.data)
        toast({
          title: 'Archivage terminé',
          description: res.data.message,
          status: 'success',
          duration: 5000,
        })
        loadData()
      } else {
        throw new Error(res.error || 'Échec de l\'archivage')
      }
    } catch (err) {
      toast({
        title: 'Erreur',
        description: err instanceof Error ? err.message : 'Erreur inconnue',
        status: 'error',
        duration: 5000,
      })
    } finally {
      setArchiveLoading(false)
    }
  }

  // Cross-doc chain detection
  const handleCrossDocDryRun = async () => {
    try {
      setCrossDocLoading(true)
      setCrossDocResult(null)
      const res = await apiClient.post<CrossDocResult>('/claimfirst/detect-cross-doc?execute=false', {})
      if (res.success && res.data) {
        setCrossDocResult(res.data)
      } else {
        throw new Error(res.error || 'Échec de la détection')
      }
    } catch (err) {
      toast({
        title: 'Erreur',
        description: err instanceof Error ? err.message : 'Erreur inconnue',
        status: 'error',
        duration: 5000,
      })
    } finally {
      setCrossDocLoading(false)
    }
  }

  const handleCrossDocExecute = async () => {
    try {
      setCrossDocLoading(true)
      const res = await apiClient.post<CrossDocResult>('/claimfirst/detect-cross-doc?execute=true', {})
      if (res.success && res.data) {
        setCrossDocResult(res.data)
        toast({
          title: 'Chaînes cross-doc créées',
          description: res.data.message,
          status: 'success',
          duration: 5000,
        })
        loadData()
      } else {
        throw new Error(res.error || 'Échec de la détection')
      }
    } catch (err) {
      toast({
        title: 'Erreur',
        description: err instanceof Error ? err.message : 'Erreur inconnue',
        status: 'error',
        duration: 5000,
      })
    } finally {
      setCrossDocLoading(false)
    }
  }

  // Entity canonicalization
  const handleCanonDryRun = async () => {
    try {
      setCanonLoading(true)
      setCanonResult(null)
      const res = await apiClient.post<CanonResult>('/claimfirst/canonicalize-entities?execute=false', {})
      if (res.success && res.data) {
        setCanonResult(res.data)
      } else {
        throw new Error(res.error || 'Échec de l\'analyse')
      }
    } catch (err) {
      toast({
        title: 'Erreur',
        description: err instanceof Error ? err.message : 'Erreur inconnue',
        status: 'error',
        duration: 5000,
      })
    } finally {
      setCanonLoading(false)
    }
  }

  const handleCanonExecute = async () => {
    try {
      setCanonLoading(true)
      const res = await apiClient.post<CanonResult>('/claimfirst/canonicalize-entities?execute=true', {})
      if (res.success && res.data) {
        setCanonResult(res.data)
        toast({
          title: 'Entités canonicalisées',
          description: res.data.message,
          status: 'success',
          duration: 5000,
        })
        loadData()
      } else {
        throw new Error(res.error || 'Échec de la canonicalisation')
      }
    } catch (err) {
      toast({
        title: 'Erreur',
        description: err instanceof Error ? err.message : 'Erreur inconnue',
        status: 'error',
        duration: 5000,
      })
    } finally {
      setCanonLoading(false)
    }
  }

  // Loading states
  if (authLoading) {
    return (
      <Center h="400px">
        <VStack spacing={3}>
          <Spinner color="purple.500" size="lg" />
          <Text color="#94a3b8">Chargement...</Text>
        </VStack>
      </Center>
    )
  }

  if (!isAdmin()) {
    return (
      <Center h="400px">
        <Box bg="#1e293b" border="1px solid" borderColor="red.700" rounded="xl" p={6}>
          <HStack spacing={3}>
            <Icon as={FiXCircle} color="red.400" boxSize={6} />
            <Box>
              <Text color="#f1f5f9" fontWeight="bold">Accès refusé</Text>
              <Text color="#94a3b8" fontSize="sm">Cette page est réservée aux administrateurs.</Text>
            </Box>
          </HStack>
        </Box>
      </Center>
    )
  }

  if (loading) {
    return (
      <Center h="400px">
        <VStack spacing={3}>
          <Spinner color="purple.500" size="lg" />
          <Text color="#94a3b8">Chargement Pipeline Claim-First...</Text>
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
            bgGradient="linear(to-br, purple.500, pink.500)"
            display="flex"
            alignItems="center"
            justifyContent="center"
          >
            <Icon as={FiTarget} boxSize={5} color="white" />
          </Box>
          <Box>
            <Text fontSize="xl" fontWeight="bold" color="#f1f5f9" lineHeight={1}>
              Pipeline Claim-First
            </Text>
            <Text fontSize="sm" color="#94a3b8">
              Pivot Épistémique - Claims comme objet central
            </Text>
          </Box>
        </HStack>
        <HStack spacing={2}>
          <Badge colorScheme="purple" variant="subtle">V3</Badge>
          <IconButton
            aria-label="Refresh"
            icon={<FiRefreshCw />}
            size="sm"
            variant="ghost"
            color="#94a3b8"
            onClick={loadData}
            isLoading={loading}
          />
        </HStack>
      </Flex>

      {/* Error */}
      {error && (
        <Box bg="#1e293b" border="1px solid" borderColor="red.700" rounded="xl" p={4} mb={4}>
          <HStack spacing={3}>
            <Icon as={FiAlertTriangle} color="red.400" boxSize={5} />
            <Text color="red.300">{error}</Text>
          </HStack>
        </Box>
      )}

      {status && (
        <>
          {/* Stats Grid */}
          <Flex gap={3} mb={4} flexWrap="wrap">
            <MetricCard label="Claims" value={status.claims} icon={FiCheckCircle} color="green" tooltip="Affirmations documentées" />
            <MetricCard label="Entities" value={status.entities} icon={FiDatabase} color="blue" tooltip="Ancres de navigation" />
            <MetricCard label="Facets" value={status.facets} icon={FiLayers} color="purple" tooltip="Axes de navigation" />
            <MetricCard label="Clusters" value={status.clusters} icon={FiLink2} color="orange" tooltip="Agrégations inter-docs" />
            <MetricCard label="Contexts" value={status.doc_contexts} icon={FiTarget} color="cyan" tooltip="Contextes documentaires (INV-8)" />
            <MetricCard label="Subjects" value={status.subject_anchors} icon={FiActivity} color="pink" tooltip="Sujets résolus (INV-9)" />
          </Flex>

          {/* Relations Stats */}
          <Box bg="#1e293b" border="1px solid" borderColor="#334155" rounded="xl" p={4} mb={4}>
            <Text fontSize="sm" fontWeight="semibold" color="#94a3b8" mb={3}>RELATIONS</Text>
            <SimpleGrid columns={{ base: 4, md: 7 }} gap={4}>
              <RelationStat label="ABOUT" value={status.about} color="blue" />
              <RelationStat label="HAS_FACET" value={status.has_facet} color="purple" />
              <RelationStat label="IN_CLUSTER" value={status.in_cluster} color="orange" />
              <RelationStat label="CONTRADICTS" value={status.contradicts} color="red" />
              <RelationStat label="REFINES" value={status.refines} color="cyan" />
              <RelationStat label="QUALIFIES" value={status.qualifies} color="pink" />
              <RelationStat label="ABOUT_SUBJECT" value={status.about_subject} color="teal" />
            </SimpleGrid>
          </Box>

          {/* Lien vers Post-Import (les actions ont été déplacées) */}
          <Box bg="#1e293b" border="1px solid" borderColor="#334155" rounded="xl" p={4} mb={4}>
            <Flex justify="space-between" align="center">
              <HStack spacing={2}>
                <Icon as={FiRefreshCw} color="brand.400" boxSize={4} />
                <Text fontSize="sm" fontWeight="semibold" color="#f1f5f9">
                  Opérations post-import
                </Text>
                <Text fontSize="xs" color="#64748b">
                  Canonicalisation, chaînes cross-doc, archivage, facettes, contradictions...
                </Text>
              </HStack>
              <Link as={NextLink} href="/admin/post-import">
                <Button size="sm" colorScheme="brand" variant="outline" leftIcon={<FiExternalLink />}>
                  Ouvrir
                </Button>
              </Link>
            </Flex>
          </Box>

          {/* Actions post-import déplacées vers /admin/post-import */}


          {/* Current Job Status — Panneau de suivi enrichi */}
          {currentJob && (() => {
            const isRunning = currentJob.status === 'started' || currentJob.status === 'queued'
            const isFinished = currentJob.status === 'finished'
            const isFailed = currentJob.status === 'failed'
            const isCircuitBreaker = currentJob.phase === 'VLLM_UNAVAILABLE'
            const progressPct = currentJob.total > 0
              ? Math.round((currentJob.processed / currentJob.total) * 100)
              : 0
            const elapsed = currentJob.elapsed_seconds || 0
            const avgPerDoc = currentJob.processed > 0 ? elapsed / currentJob.processed : 0
            const remaining = currentJob.total - currentJob.processed - currentJob.failed - currentJob.skipped
            const eta = avgPerDoc > 0 && remaining > 0 ? Math.round(avgPerDoc * remaining) : 0

            const formatDuration = (s: number) => {
              if (s < 60) return `${s}s`
              if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`
              return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`
            }

            const phaseLabels: Record<string, { label: string; color: string }> = {
              'INIT': { label: 'Initialisation', color: 'gray' },
              'LOADING': { label: 'Chargement', color: 'blue' },
              'EXTRACTING': { label: 'Extraction LLM', color: 'purple' },
              'PERSISTED': { label: 'Persisté', color: 'green' },
              'CROSS_DOC_CHAINS': { label: 'Chaînes cross-doc', color: 'cyan' },
              'CANONICALIZE_ENTITIES': { label: 'Canonicalisation', color: 'teal' },
              'CROSS_DOC_CLUSTERING': { label: 'Clustering cross-doc', color: 'orange' },
              'QS_CROSS_DOC_COMPARISON': { label: 'Comparaison QS', color: 'pink' },
              'DONE': { label: 'Terminé', color: 'green' },
              'VLLM_UNAVAILABLE': { label: 'vLLM indisponible', color: 'red' },
            }

            const currentPhase = currentJob.phase ? phaseLabels[currentJob.phase] || { label: currentJob.phase, color: 'gray' } : null

            return (
            <Box
              bg="#0f172a"
              border="2px solid"
              borderColor={
                isCircuitBreaker ? 'red.500' :
                isFinished ? 'green.600' :
                isFailed ? 'red.600' :
                'blue.600'
              }
              rounded="xl"
              p={0}
              mb={4}
              overflow="hidden"
            >
              {/* Header */}
              <Box
                bg={
                  isCircuitBreaker ? 'red.900' :
                  isFinished ? 'green.900' :
                  isFailed ? 'red.900' :
                  'blue.900'
                }
                px={4} py={3}
              >
                <Flex justify="space-between" align="center">
                  <HStack spacing={3}>
                    <Icon
                      as={
                        isCircuitBreaker ? FiStopCircle :
                        isFinished ? FiCheckCircle :
                        isFailed ? FiXCircle :
                        FiLoader
                      }
                      color={
                        isCircuitBreaker ? 'red.300' :
                        isFinished ? 'green.300' :
                        isFailed ? 'red.300' :
                        'blue.300'
                      }
                      boxSize={5}
                    />
                    <Box>
                      <Text fontWeight="bold" color="#f1f5f9" fontSize="md">
                        {isCircuitBreaker ? 'Circuit Breaker activé' :
                         isFinished ? 'Traitement terminé' :
                         isFailed ? 'Traitement échoué' :
                         'Traitement en cours'}
                      </Text>
                      <Text fontSize="xs" color="#94a3b8">
                        Job {currentJob.job_id}
                      </Text>
                    </Box>
                  </HStack>
                  <HStack spacing={2}>
                    {currentPhase && (
                      <Badge colorScheme={currentPhase.color} variant="solid" fontSize="xs">
                        {currentPhase.label}
                      </Badge>
                    )}
                    {elapsed > 0 && (
                      <HStack spacing={1}>
                        <Icon as={FiClock} color="#64748b" boxSize={3} />
                        <Text fontSize="xs" color="#94a3b8">{formatDuration(elapsed)}</Text>
                      </HStack>
                    )}
                  </HStack>
                </Flex>
              </Box>

              <Box px={4} py={3}>
                <VStack align="stretch" spacing={3}>

                  {/* Document en cours */}
                  {isRunning && currentJob.current_filename && (
                    <Box bg="#1e293b" rounded="lg" px={3} py={2} border="1px solid" borderColor="#334155">
                      <HStack spacing={2}>
                        <Icon as={FiFileText} color="blue.400" boxSize={4} />
                        <Box flex={1} minW={0}>
                          <Text fontSize="xs" color="#64748b">Document en cours</Text>
                          <Text fontSize="sm" color="#e2e8f0" fontWeight="medium" isTruncated>
                            {currentJob.current_filename}
                          </Text>
                        </Box>
                      </HStack>
                    </Box>
                  )}

                  {/* Barre de progression */}
                  <Box>
                    <Flex justify="space-between" mb={1} align="baseline">
                      <HStack spacing={2}>
                        <Text fontSize="sm" fontWeight="semibold" color="#f1f5f9">
                          {progressPct}%
                        </Text>
                        <Text fontSize="xs" color="#64748b">
                          ({currentJob.processed} / {currentJob.total} documents)
                        </Text>
                      </HStack>
                      {isRunning && eta > 0 && (
                        <Text fontSize="xs" color="#94a3b8">
                          ETA: ~{formatDuration(eta)}
                        </Text>
                      )}
                    </Flex>
                    <Progress
                      value={progressPct}
                      colorScheme={isCircuitBreaker ? 'red' : isFinished ? 'green' : 'purple'}
                      bg="#334155"
                      borderRadius="full"
                      size="md"
                      hasStripe={isRunning}
                      isAnimated={isRunning}
                    />
                  </Box>

                  {/* Métriques temps réel */}
                  <SimpleGrid columns={{ base: 2, md: 5 }} gap={2}>
                    <Box bg="#1e293b" rounded="md" px={3} py={2} textAlign="center">
                      <Text fontSize="lg" fontWeight="bold" color="green.400">
                        {currentJob.total_claims.toLocaleString()}
                      </Text>
                      <Text fontSize="xs" color="#64748b">Claims</Text>
                    </Box>
                    <Box bg="#1e293b" rounded="md" px={3} py={2} textAlign="center">
                      <Text fontSize="lg" fontWeight="bold" color="blue.400">
                        {currentJob.total_entities.toLocaleString()}
                      </Text>
                      <Text fontSize="xs" color="#64748b">Entités</Text>
                    </Box>
                    <Box bg="#1e293b" rounded="md" px={3} py={2} textAlign="center">
                      <Text fontSize="lg" fontWeight="bold" color="#f1f5f9">
                        {currentJob.processed}
                      </Text>
                      <Text fontSize="xs" color="#64748b">Traités</Text>
                    </Box>
                    <Box bg="#1e293b" rounded="md" px={3} py={2} textAlign="center">
                      <Text fontSize="lg" fontWeight="bold" color={currentJob.failed > 0 ? 'red.400' : '#64748b'}>
                        {currentJob.failed}
                      </Text>
                      <Text fontSize="xs" color="#64748b">Erreurs</Text>
                    </Box>
                    <Box bg="#1e293b" rounded="md" px={3} py={2} textAlign="center">
                      <Text fontSize="lg" fontWeight="bold" color={currentJob.skipped > 0 ? 'yellow.400' : '#64748b'}>
                        {currentJob.skipped}
                      </Text>
                      <Text fontSize="xs" color="#64748b">Ignorés</Text>
                    </Box>
                  </SimpleGrid>

                  {/* Throughput */}
                  {elapsed > 0 && currentJob.processed > 0 && (
                    <HStack spacing={4} justify="center">
                      <HStack spacing={1}>
                        <Icon as={FiZap} color="yellow.400" boxSize={3} />
                        <Text fontSize="xs" color="#94a3b8">
                          {formatDuration(Math.round(avgPerDoc))}/doc
                        </Text>
                      </HStack>
                      <Text fontSize="xs" color="#475569">|</Text>
                      <Text fontSize="xs" color="#94a3b8">
                        {(currentJob.total_claims / (elapsed / 60)).toFixed(1)} claims/min
                      </Text>
                      <Text fontSize="xs" color="#475569">|</Text>
                      <Text fontSize="xs" color="#94a3b8">
                        ~{Math.round(currentJob.total_claims / currentJob.processed)} claims/doc
                      </Text>
                    </HStack>
                  )}

                  {/* Circuit breaker alert */}
                  {isCircuitBreaker && (
                    <Box bg="red.900" border="1px solid" borderColor="red.600" rounded="md" p={3}>
                      <HStack spacing={2} mb={1}>
                        <Icon as={FiStopCircle} color="red.300" boxSize={4} />
                        <Text fontSize="sm" color="red.200" fontWeight="semibold">
                          Circuit Breaker - vLLM indisponible
                        </Text>
                      </HStack>
                      <Text fontSize="xs" color="red.300">
                        Le traitement a été arrêté car le vLLM ne répond plus.
                        {remaining > 0 && ` ${remaining} documents restants non traités.`}
                      </Text>
                    </Box>
                  )}

                  {/* Erreurs */}
                  {currentJob.errors.length > 0 && !isCircuitBreaker && (
                    <Box bg="red.900" border="1px solid" borderColor="red.700" rounded="md" p={2}>
                      <Text fontSize="xs" color="red.300" fontWeight="semibold" mb={1}>
                        {currentJob.errors.length} erreur(s)
                      </Text>
                      {currentJob.errors.slice(0, 5).map((err, i) => {
                        // Parser "filename: error message"
                        const colonIdx = err.indexOf(': ')
                        const docName = colonIdx > 0 ? err.slice(0, colonIdx).trim() : ''
                        const errMsg = colonIdx > 0 ? err.slice(colonIdx + 2).trim() : err
                        return (
                          <Box key={i} mb={1} pl={2} borderLeft="2px solid" borderLeftColor="red.600">
                            {docName && (
                              <Text fontSize="xs" color="red.200" fontWeight="medium">{docName}</Text>
                            )}
                            <Text fontSize="xs" color="red.400">{errMsg}</Text>
                          </Box>
                        )
                      })}
                      {currentJob.errors.length > 5 && (
                        <Text fontSize="xs" color="red.500" mt={1}>
                          ... et {currentJob.errors.length - 5} autres
                        </Text>
                      )}
                    </Box>
                  )}

                  {/* Résumé final */}
                  {isFinished && elapsed > 0 && (
                    <Box bg="green.900" border="1px solid" borderColor="green.700" rounded="md" p={3}>
                      <Text fontSize="sm" color="green.200" fontWeight="semibold" mb={1}>
                        Traitement terminé en {formatDuration(elapsed)}
                      </Text>
                      <Text fontSize="xs" color="green.300">
                        {currentJob.processed} documents traités
                        {' → '}{currentJob.total_claims.toLocaleString()} claims,{' '}
                        {currentJob.total_entities.toLocaleString()} entités extraites.
                        {currentJob.processed > 0 && ` Moyenne: ${formatDuration(Math.round(avgPerDoc))}/doc.`}
                      </Text>
                    </Box>
                  )}
                </VStack>
              </Box>
            </Box>
            )
          })()}

          {/* Documents Selection */}
          <Box bg="#1e293b" border="1px solid" borderColor="#334155" rounded="xl" p={4}>
            <Flex justify="space-between" align="center" mb={4}>
              <Box>
                <Text fontWeight="semibold" color="#f1f5f9">Documents disponibles</Text>
                <Text fontSize="sm" color="#64748b">
                  {documents.length} documents — <Text as="span" color="green.400">{documents.filter(d => importedDocs[d.doc_id]).length} importés</Text>, <Text as="span" color="orange.300">{documents.filter(d => !importedDocs[d.doc_id]).length} nouveaux</Text>
                </Text>
              </Box>
              <HStack spacing={2}>
                <Button size="xs" variant="ghost" color="#94a3b8" onClick={selectAll}>
                  Tout
                </Button>
                <Button size="xs" variant="ghost" color="#94a3b8" onClick={selectNone}>
                  Aucun
                </Button>
                <Button size="xs" variant="ghost" color="green.400" onClick={selectNewOnly}>
                  Nouveaux uniquement
                </Button>
              </HStack>
            </Flex>

            {/* Action Buttons */}
            <HStack mb={4} spacing={3}>
              <Button
                colorScheme="green"
                size="sm"
                isDisabled={selectedDocs.size === 0 || jobLoading || currentJob?.status === 'started'}
                onClick={handleProcessSelected}
                isLoading={jobLoading}
                leftIcon={<Icon as={FiPlay} />}
              >
                Traiter sélectionnés ({selectedDocs.size})
              </Button>
              <Button
                colorScheme="purple"
                size="sm"
                isDisabled={documents.length === 0 || jobLoading || currentJob?.status === 'started'}
                onClick={handleProcessAll}
                isLoading={jobLoading}
                leftIcon={<Icon as={FiPlay} />}
              >
                Traiter TOUS ({documents.length})
              </Button>
            </HStack>

            {/* Documents Table */}
            {documents.length === 0 ? (
              <Box bg="#0f172a" border="1px solid" borderColor="#334155" rounded="lg" p={4} textAlign="center">
                <Icon as={FiFileText} boxSize={8} color="#64748b" mb={2} />
                <Text color="#94a3b8">Aucun document dans le cache</Text>
                <Text fontSize="sm" color="#64748b">
                  Importez des documents via Pass 0 pour les voir apparaître ici.
                </Text>
              </Box>
            ) : (
              <Box
                maxH="350px"
                overflowY="auto"
                border="1px solid"
                borderColor="#334155"
                rounded="lg"
                sx={{
                  '&::-webkit-scrollbar': { width: '6px' },
                  '&::-webkit-scrollbar-track': { bg: '#1e293b' },
                  '&::-webkit-scrollbar-thumb': { bg: '#475569', borderRadius: '3px' },
                }}
              >
                <Table size="sm" variant="unstyled">
                  <Thead position="sticky" top={0} bg="#0f172a" zIndex={1}>
                    <Tr>
                      <Th color="#64748b" width="40px" borderBottom="1px solid" borderColor="#334155"></Th>
                      <Th color="#64748b" borderBottom="1px solid" borderColor="#334155">Document ID</Th>
                      <Th color="#64748b" borderBottom="1px solid" borderColor="#334155">Fichier</Th>
                      <Th color="#64748b" borderBottom="1px solid" borderColor="#334155">Cache</Th>
                    </Tr>
                  </Thead>
                  <Tbody>
                    {documents.map((doc) => {
                      const isImported = !!importedDocs[doc.doc_id]
                      const claimCount = importedDocs[doc.doc_id] || 0
                      return (
                        <Tr
                          key={doc.doc_id}
                          _hover={{ bg: '#334155' }}
                          cursor="pointer"
                          onClick={() => toggleDoc(doc.doc_id)}
                          bg={selectedDocs.has(doc.doc_id) ? '#334155' : 'transparent'}
                        >
                          <Td borderBottom="1px solid" borderColor="#1e293b">
                            <Checkbox
                              isChecked={selectedDocs.has(doc.doc_id)}
                              onChange={() => toggleDoc(doc.doc_id)}
                              colorScheme="purple"
                            />
                          </Td>
                          <Td borderBottom="1px solid" borderColor="#1e293b">
                            <code style={{ fontSize: '11px', color: isImported ? '#4ade80' : '#94a3b8' }}>{doc.doc_id}</code>
                          </Td>
                          <Td borderBottom="1px solid" borderColor="#1e293b">
                            <Text as="span" color={isImported ? '#4ade80' : '#f1f5f9'}>
                              {doc.filename}
                            </Text>
                            {isImported && (
                              <Text as="span" fontSize="2xs" color="#22c55e" ml={2}>
                                ({claimCount} claims)
                              </Text>
                            )}
                          </Td>
                          <Td fontSize="xs" color="#64748b" borderBottom="1px solid" borderColor="#1e293b">
                            {doc.cached_at ? new Date(doc.cached_at).toLocaleDateString() : '-'}
                          </Td>
                        </Tr>
                      )
                    })}
                  </Tbody>
                </Table>
              </Box>
            )}
          </Box>

          {/* Info Card */}
          <Box bg="#1e293b" border="1px solid" borderColor="orange.800" rounded="xl" p={4} mt={4}>
            <HStack spacing={2} mb={2}>
              <Icon as={FiAlertTriangle} color="orange.400" boxSize={4} />
              <Text fontSize="sm" fontWeight="semibold" color="orange.300">Notes Pipeline Claim-First</Text>
            </HStack>
            <VStack align="start" spacing={1} fontSize="xs" color="#94a3b8">
              <Text><Text as="span" color="#f1f5f9" fontWeight="medium">Claim</Text> = affirmation synthétisée, fondée sur passages verbatim. Dit UNE chose précise.</Text>
              <Text><Text as="span" color="#f1f5f9" fontWeight="medium">Entity</Text> = ancre de navigation (pas structurante). Extraction par patterns déterministes.</Text>
              <Text><Text as="span" color="#f1f5f9" fontWeight="medium">Facet</Text> = axe de navigation (domain, risk, obligation...). Patterns déterministes.</Text>
              <Text><Text as="span" color="#f1f5f9" fontWeight="medium">ClaimCluster</Text> = agrégation inter-documents. "Ces claims disent la même chose".</Text>
              <Text color="orange.400" mt={1}>Prérequis: Documents importés via Pass 0 pour générer le cache d'extraction.</Text>
            </VStack>
          </Box>
        </>
      )}
    </Box>
  )
}
