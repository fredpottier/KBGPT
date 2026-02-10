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
  Link,
  Icon,
  Flex,
  useToast,
  Center,
  Tooltip,
  IconButton,
} from '@chakra-ui/react'
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
  processed: number
  total: number
  errors: string[]
  started_at: string | null
  completed_at: string | null
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
          const jobRes = await apiClient.get<JobStatus>(`/claimfirst/jobs/${statusRes.data.current_job_id}`)
          if (jobRes.success && jobRes.data) {
            setCurrentJob(jobRes.data)
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
          <Link href="/admin/enrichment-v2" _hover={{ textDecor: 'none' }}>
            <Badge colorScheme="gray" variant="outline" cursor="pointer">
              Pipeline V2 →
            </Badge>
          </Link>
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

          {/* Archive Isolated Claims — Chantier 0 Phase 1B */}
          <Box bg="#1e293b" border="1px solid" borderColor="#334155" rounded="xl" p={4} mb={4}>
            <Flex justify="space-between" align="center" mb={3}>
              <HStack spacing={2}>
                <Icon as={FiArchive} color="yellow.400" boxSize={4} />
                <Text fontSize="sm" fontWeight="semibold" color="#f1f5f9">
                  Archivage claims isolées
                </Text>
                <Badge colorScheme="yellow" variant="subtle" fontSize="xs">Post-import</Badge>
              </HStack>
              <HStack spacing={2}>
                <Button
                  size="xs"
                  variant="outline"
                  colorScheme="yellow"
                  onClick={handleArchiveDryRun}
                  isLoading={archiveLoading}
                  leftIcon={<Icon as={FiActivity} />}
                >
                  Analyser
                </Button>
                <Button
                  size="xs"
                  colorScheme="yellow"
                  onClick={handleArchiveExecute}
                  isLoading={archiveLoading}
                  isDisabled={!archiveResult || archiveResult.mode === 'execute'}
                  leftIcon={<Icon as={FiArchive} />}
                >
                  Archiver
                </Button>
              </HStack>
            </Flex>
            <Text fontSize="xs" color="#64748b" mb={2}>
              Marque les claims sans structured_form et sans relations (CHAINS_TO, ABOUT, REFINES...) comme archivées.
              Elles sont exclues du query engine mais conservées dans le graphe.
            </Text>
            {archiveResult && (
              <Box
                bg={archiveResult.mode === 'execute' ? 'green.900' : '#0f172a'}
                border="1px solid"
                borderColor={archiveResult.mode === 'execute' ? 'green.700' : '#334155'}
                rounded="md"
                p={3}
                mt={2}
              >
                <HStack spacing={4} flexWrap="wrap">
                  <VStack spacing={0} align="start">
                    <Text fontSize="xs" color="#64748b">Claims totales</Text>
                    <Text fontSize="sm" fontWeight="bold" color="#f1f5f9">
                      {archiveResult.total_claims?.toLocaleString()}
                    </Text>
                  </VStack>
                  {archiveResult.mode === 'dry-run' ? (
                    <>
                      <VStack spacing={0} align="start">
                        <Text fontSize="xs" color="#64748b">Isolées détectées</Text>
                        <Text fontSize="sm" fontWeight="bold" color="yellow.300">
                          {archiveResult.isolated_count?.toLocaleString()} ({archiveResult.isolated_percentage}%)
                        </Text>
                      </VStack>
                    </>
                  ) : (
                    <>
                      <VStack spacing={0} align="start">
                        <Text fontSize="xs" color="#64748b">Nouvellement archivées</Text>
                        <Text fontSize="sm" fontWeight="bold" color="green.300">
                          {archiveResult.newly_archived?.toLocaleString()}
                        </Text>
                      </VStack>
                      <VStack spacing={0} align="start">
                        <Text fontSize="xs" color="#64748b">Total archivées</Text>
                        <Text fontSize="sm" fontWeight="bold" color="green.300">
                          {archiveResult.total_archived?.toLocaleString()}
                        </Text>
                      </VStack>
                    </>
                  )}
                </HStack>
                <Text fontSize="xs" color="#94a3b8" mt={2}>{archiveResult.message}</Text>
              </Box>
            )}
          </Box>

          {/* Cross-Doc Chain Detection */}
          <Box bg="#1e293b" border="1px solid" borderColor="#334155" rounded="xl" p={4} mb={4}>
            <Flex justify="space-between" align="center" mb={3}>
              <HStack spacing={2}>
                <Icon as={FiLink2} color="blue.400" boxSize={4} />
                <Text fontSize="sm" fontWeight="semibold" color="#f1f5f9">
                  Chaînes cross-document
                </Text>
                <Badge colorScheme="blue" variant="subtle" fontSize="xs">Post-import</Badge>
              </HStack>
              <HStack spacing={2}>
                <Button
                  size="xs"
                  variant="outline"
                  colorScheme="blue"
                  onClick={handleCrossDocDryRun}
                  isLoading={crossDocLoading}
                  leftIcon={<Icon as={FiActivity} />}
                >
                  Analyser
                </Button>
                <Button
                  size="xs"
                  colorScheme="blue"
                  onClick={handleCrossDocExecute}
                  isLoading={crossDocLoading}
                  isDisabled={!crossDocResult || crossDocResult.mode === 'execute' || (crossDocResult.chains_detected ?? 0) === 0}
                  leftIcon={<Icon as={FiLink2} />}
                >
                  Créer les chaînes
                </Button>
              </HStack>
            </Flex>
            <Text fontSize="xs" color="#64748b" mb={2}>
              Détecte les ponts sémantiques entre documents via les entités S/P/O partagées (object→subject).
              Exécuté automatiquement après l{"'"}import, ou manuellement ici.
            </Text>
            {crossDocResult && (
              <Box
                bg={crossDocResult.mode === 'execute' ? 'green.900' : '#0f172a'}
                border="1px solid"
                borderColor={crossDocResult.mode === 'execute' ? 'green.700' : '#334155'}
                rounded="md"
                p={3}
                mt={2}
              >
                <HStack spacing={4} flexWrap="wrap">
                  <VStack spacing={0} align="start">
                    <Text fontSize="xs" color="#64748b">Claims S/P/O</Text>
                    <Text fontSize="sm" fontWeight="bold" color="#f1f5f9">
                      {crossDocResult.claims_with_sf?.toLocaleString()}
                    </Text>
                  </VStack>
                  <VStack spacing={0} align="start">
                    <Text fontSize="xs" color="#64748b">Documents</Text>
                    <Text fontSize="sm" fontWeight="bold" color="#f1f5f9">
                      {crossDocResult.documents}
                    </Text>
                  </VStack>
                  {crossDocResult.mode === 'dry-run' ? (
                    <>
                      <VStack spacing={0} align="start">
                        <Text fontSize="xs" color="#64748b">Chaînes détectées</Text>
                        <Text fontSize="sm" fontWeight="bold" color="blue.300">
                          {crossDocResult.chains_detected?.toLocaleString()}
                        </Text>
                      </VStack>
                      <VStack spacing={0} align="start">
                        <Text fontSize="xs" color="#64748b">Cross-doc existantes</Text>
                        <Text fontSize="sm" fontWeight="bold" color="#94a3b8">
                          {crossDocResult.existing_cross?.toLocaleString()}
                        </Text>
                      </VStack>
                    </>
                  ) : (
                    <>
                      <VStack spacing={0} align="start">
                        <Text fontSize="xs" color="#64748b">Chaînes créées</Text>
                        <Text fontSize="sm" fontWeight="bold" color="green.300">
                          {crossDocResult.chains_persisted?.toLocaleString()}
                        </Text>
                      </VStack>
                      <VStack spacing={0} align="start">
                        <Text fontSize="xs" color="#64748b">Total cross-doc</Text>
                        <Text fontSize="sm" fontWeight="bold" color="green.300">
                          {crossDocResult.total_cross_doc?.toLocaleString()}
                        </Text>
                      </VStack>
                      <VStack spacing={0} align="start">
                        <Text fontSize="xs" color="#64748b">Total intra-doc</Text>
                        <Text fontSize="sm" fontWeight="bold" color="#94a3b8">
                          {crossDocResult.total_intra_doc?.toLocaleString()}
                        </Text>
                      </VStack>
                    </>
                  )}
                </HStack>
                <Text fontSize="xs" color="#94a3b8" mt={2}>{crossDocResult.message}</Text>
              </Box>
            )}
          </Box>

          {/* Entity Canonicalization */}
          <Box bg="#1e293b" border="1px solid" borderColor="#334155" rounded="xl" p={4} mb={4}>
            <Flex justify="space-between" align="center" mb={3}>
              <HStack spacing={2}>
                <Icon as={FiTarget} color="purple.400" boxSize={4} />
                <Text fontSize="sm" fontWeight="semibold" color="#f1f5f9">
                  Canonicalisation des entités
                </Text>
                <Badge colorScheme="purple" variant="subtle" fontSize="xs">Post-import</Badge>
              </HStack>
              <HStack spacing={2}>
                <Button
                  size="xs"
                  variant="outline"
                  colorScheme="purple"
                  onClick={handleCanonDryRun}
                  isLoading={canonLoading}
                  leftIcon={<Icon as={FiActivity} />}
                >
                  Analyser
                </Button>
                <Button
                  size="xs"
                  colorScheme="purple"
                  onClick={handleCanonExecute}
                  isLoading={canonLoading}
                  isDisabled={!canonResult || canonResult.mode === 'execute' || (canonResult.total_merges ?? 0) === 0}
                  leftIcon={<Icon as={FiTarget} />}
                >
                  Fusionner
                </Button>
              </HStack>
            </Flex>
            <Text fontSize="xs" color="#64748b" mb={2}>
              Fusionne les entités dupliquées cross-document : variantes version
              (&quot;S/4HANA 2023&quot; → &quot;S/4HANA&quot;) et containments
              (&quot;S4HANA&quot; ⊂ &quot;SAP S4HANA&quot;).
              Exécuté automatiquement après l{"'"}import, ou manuellement ici.
            </Text>
            {canonResult && (
              <Box
                bg={canonResult.mode === 'execute' ? 'green.900' : '#0f172a'}
                border="1px solid"
                borderColor={canonResult.mode === 'execute' ? 'green.700' : '#334155'}
                rounded="md"
                p={3}
                mt={2}
              >
                <HStack spacing={4} flexWrap="wrap">
                  <VStack spacing={0} align="start">
                    <Text fontSize="xs" color="#64748b">Entités initiales</Text>
                    <Text fontSize="sm" fontWeight="bold" color="#f1f5f9">
                      {canonResult.entities_initial?.toLocaleString()}
                    </Text>
                  </VStack>
                  {canonResult.mode === 'dry-run' ? (
                    <>
                      <VStack spacing={0} align="start">
                        <Text fontSize="xs" color="#64748b">Fusions version</Text>
                        <Text fontSize="sm" fontWeight="bold" color="purple.300">
                          {canonResult.version_merges?.toLocaleString()}
                        </Text>
                      </VStack>
                      <VStack spacing={0} align="start">
                        <Text fontSize="xs" color="#64748b">Fusions containment</Text>
                        <Text fontSize="sm" fontWeight="bold" color="purple.300">
                          {canonResult.containment_merges?.toLocaleString()}
                        </Text>
                      </VStack>
                      <VStack spacing={0} align="start">
                        <Text fontSize="xs" color="#64748b">Total fusions</Text>
                        <Text fontSize="sm" fontWeight="bold" color="purple.300">
                          {canonResult.total_merges?.toLocaleString()}
                        </Text>
                      </VStack>
                    </>
                  ) : (
                    <>
                      <VStack spacing={0} align="start">
                        <Text fontSize="xs" color="#64748b">Fusionnées</Text>
                        <Text fontSize="sm" fontWeight="bold" color="green.300">
                          {canonResult.total_merges?.toLocaleString()}
                        </Text>
                      </VStack>
                      <VStack spacing={0} align="start">
                        <Text fontSize="xs" color="#64748b">Entités restantes</Text>
                        <Text fontSize="sm" fontWeight="bold" color="green.300">
                          {canonResult.entities_after?.toLocaleString()}
                        </Text>
                      </VStack>
                      <VStack spacing={0} align="start">
                        <Text fontSize="xs" color="#64748b">Hubs annotés</Text>
                        <Text fontSize="sm" fontWeight="bold" color="#94a3b8">
                          {canonResult.hubs_annotated?.toLocaleString()}
                        </Text>
                      </VStack>
                    </>
                  )}
                </HStack>
                <Text fontSize="xs" color="#94a3b8" mt={2}>{canonResult.message}</Text>
              </Box>
            )}
          </Box>

          {/* Current Job Status */}
          {currentJob && (
            <Box
              bg="#1e293b"
              border="2px solid"
              borderColor={
                currentJob.status === 'finished' ? 'green.600' :
                currentJob.status === 'failed' ? 'red.600' :
                'blue.600'
              }
              rounded="xl"
              p={4}
              mb={4}
            >
              <Flex justify="space-between" align="center" mb={3}>
                <HStack spacing={2}>
                  <Icon as={FiActivity} color={
                    currentJob.status === 'finished' ? 'green.400' :
                    currentJob.status === 'failed' ? 'red.400' :
                    'blue.400'
                  } />
                  <Text fontWeight="semibold" color="#f1f5f9">Job en cours</Text>
                </HStack>
                <Badge
                  colorScheme={
                    currentJob.status === 'finished' ? 'green' :
                    currentJob.status === 'failed' ? 'red' :
                    currentJob.status === 'queued' ? 'yellow' :
                    'blue'
                  }
                >
                  {currentJob.status}
                </Badge>
              </Flex>

              <VStack align="stretch" spacing={3}>
                <HStack justify="space-between">
                  <Text fontSize="sm" color="#94a3b8">
                    ID: <code style={{ color: '#f1f5f9' }}>{currentJob.job_id}</code>
                  </Text>
                  {currentJob.phase && (
                    <Badge colorScheme="purple" variant="subtle">{currentJob.phase}</Badge>
                  )}
                </HStack>

                {currentJob.current_document && (
                  <Text fontSize="sm" color="#64748b">
                    Document: {currentJob.current_document}
                  </Text>
                )}

                <Box>
                  <Flex justify="space-between" mb={1}>
                    <Text fontSize="xs" color="#64748b">Progression</Text>
                    <Text fontSize="xs" color="#94a3b8">{currentJob.processed} / {currentJob.total}</Text>
                  </Flex>
                  <Progress
                    value={currentJob.total > 0 ? (currentJob.processed / currentJob.total) * 100 : 0}
                    colorScheme="purple"
                    bg="#334155"
                    borderRadius="full"
                    size="sm"
                  />
                </Box>

                {currentJob.errors.length > 0 && (
                  <Box bg="red.900" border="1px solid" borderColor="red.700" rounded="md" p={2}>
                    <Text fontSize="xs" color="red.300" fontWeight="semibold">
                      {currentJob.errors.length} erreur(s)
                    </Text>
                    {currentJob.errors.slice(0, 2).map((err, i) => (
                      <Text key={i} fontSize="xs" color="red.400">{err}</Text>
                    ))}
                  </Box>
                )}
              </VStack>
            </Box>
          )}

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
