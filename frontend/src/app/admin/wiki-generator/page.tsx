'use client'

/**
 * Page Admin - Wiki Generator
 *
 * Workflow orienté action :
 * 1. On voit le résumé (combien de concepts sans article par tier)
 * 2. On choisit quoi générer (tier, nombre)
 * 3. On lance et on suit la progression
 * 4. En bas, la liste des concepts SANS article (les gaps à combler)
 */

import { useState, useEffect, useCallback, useRef } from 'react'
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
  Table,
  Th,
  Td,
  Tbody,
  Tr,
  Thead,
  Select,
  NumberInput,
  NumberInputField,
  NumberInputStepper,
  NumberIncrementStepper,
  NumberDecrementStepper,
  Flex,
  useToast,
  Icon,
  Link,
  Tooltip,
} from '@chakra-ui/react'
import {
  FiPlay,
  FiRefreshCw,
  FiCheckCircle,
  FiXCircle,
  FiExternalLink,
  FiZap,
  FiAlertCircle,
  FiLink,
} from 'react-icons/fi'
import NextLink from 'next/link'
import { useAuth } from '@/contexts/AuthContext'
import { apiClient } from '@/lib/api'

// Types
interface ScoredConcept {
  entity_name: string
  entity_type: string
  entity_id: string
  claim_count: number
  doc_count: number
  graph_degree: number
  importance_score: number
  importance_tier: number
  has_article: boolean
  article_slug: string | null
}

interface ScoringResponse {
  concepts: ScoredConcept[]
  total: number
  tier1_count: number
  tier2_count: number
  tier3_count: number
  articles_count: number
}

interface BatchJobItem {
  concept_name: string
  entity_type: string
  importance_tier: number
  job_id: string | null
  status: string
  article_slug: string | null
  error: string | null
}

interface BatchStatus {
  batch_id: string
  status: string
  total: number
  completed: number
  failed: number
  running: number
  queued: number
  language: string
  jobs: BatchJobItem[]
}

interface LinkingJobItem {
  slug: string
  title: string
  status: string
  link_count: number
  candidates_count: number
  error: string | null
}

interface LinkBatchStatus {
  batch_id: string
  status: string
  total: number
  completed: number
  failed: number
  skipped: number
  jobs: LinkingJobItem[]
}

const TIER_COLORS: Record<number, string> = { 1: 'purple', 2: 'blue', 3: 'gray' }
const STATUS_COLORS: Record<string, string> = {
  queued: 'gray', running: 'blue', completed: 'green', failed: 'red',
  cancelled: 'orange', suspended: 'orange',
}

export default function WikiGeneratorPage() {
  const { isAuthenticated } = useAuth()
  const toast = useToast()

  const [scoring, setScoring] = useState<ScoringResponse | null>(null)
  const [loadingScoring, setLoadingScoring] = useState(false)

  const [maxTier, setMaxTier] = useState(2)
  const [maxArticles, setMaxArticles] = useState(10)
  const [generateAll, setGenerateAll] = useState(false)
  const [language, setLanguage] = useState('français')
  const [batchStatus, setBatchStatus] = useState<BatchStatus | null>(null)
  const [launching, setLaunching] = useState(false)
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Linking state
  const [linkStatus, setLinkStatus] = useState<LinkBatchStatus | null>(null)
  const [launchingLink, setLaunchingLink] = useState(false)
  const [forceRelink, setForceRelink] = useState(false)
  const linkPollingRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Derived: concepts sans article, groupés par tier
  const missingByTier = useCallback(() => {
    if (!scoring) return { t1: 0, t2: 0, t3: 0, missing: [] as ScoredConcept[] }
    const missing = scoring.concepts.filter(c => !c.has_article)
    return {
      t1: missing.filter(c => c.importance_tier === 1).length,
      t2: missing.filter(c => c.importance_tier === 2).length,
      t3: missing.filter(c => c.importance_tier === 3).length,
      missing,
    }
  }, [scoring])

  const gaps = missingByTier()

  const loadScoring = useCallback(async () => {
    setLoadingScoring(true)
    try {
      const res = await apiClient.get('/wiki/admin/scoring?tenant_id=default')
      setScoring(res.data as ScoringResponse)
    } catch (err: any) {
      toast({
        title: 'Erreur chargement scoring',
        description: err?.response?.data?.detail || err.message,
        status: 'error', duration: 5000,
      })
    } finally {
      setLoadingScoring(false)
    }
  }, [toast])

  useEffect(() => {
    if (isAuthenticated) loadScoring()
  }, [isAuthenticated, loadScoring])

  // Batch polling
  const pollBatchStatus = useCallback(async (batchId: string) => {
    try {
      const res = await apiClient.get(`/wiki/admin/batch-status/${encodeURIComponent(batchId)}`)
      const data = res.data as BatchStatus
      setBatchStatus(data)
      if (data.status !== 'running') {
        if (pollingRef.current) { clearInterval(pollingRef.current); pollingRef.current = null }
        loadScoring()
        const isSuspended = data.status === 'suspended'
        toast({
          title: isSuspended
            ? 'Génération suspendue — vLLM indisponible'
            : data.status === 'completed' ? 'Génération terminée' : 'Génération terminée avec erreurs',
          description: isSuspended
            ? `${data.completed} articles créés avant suspension. Relancez quand le vLLM sera de nouveau disponible.`
            : `${data.completed} articles créés, ${data.failed} échecs`,
          status: isSuspended ? 'error' : data.failed > 0 ? 'warning' : 'success',
          duration: isSuspended ? 15000 : 8000,
        })
      }
    } catch { /* ignore */ }
  }, [loadScoring, toast])

  const launchBatch = async () => {
    setLaunching(true)
    try {
      const res = await apiClient.post('/wiki/admin/batch-generate', {
        max_tier: maxTier, max_articles: effectiveMax, language, skip_existing: true,
      })
      const data = res.data as BatchStatus
      setBatchStatus(data)
      toast({
        title: 'Génération lancée',
        description: `${data.total} articles en file d'attente`,
        status: 'info', duration: 5000,
      })
      if (pollingRef.current) clearInterval(pollingRef.current)
      pollingRef.current = setInterval(() => pollBatchStatus(data.batch_id), 5000)
    } catch (err: any) {
      toast({
        title: 'Erreur lancement',
        description: err?.response?.data?.detail || err.message,
        status: 'error', duration: 5000,
      })
    } finally {
      setLaunching(false)
    }
  }

  // Linking polling
  const pollLinkStatus = useCallback(async () => {
    try {
      const res = await apiClient.get('/wiki/admin/link-status')
      const data = res.data as LinkBatchStatus
      setLinkStatus(data)
      if (data.status !== 'running') {
        if (linkPollingRef.current) { clearInterval(linkPollingRef.current); linkPollingRef.current = null }
        toast({
          title: data.status === 'suspended'
            ? 'Linking suspendu — vLLM indisponible'
            : 'Linking terminé',
          description: `${data.completed} articles linkés, ${data.failed} échecs`,
          status: data.status === 'suspended' ? 'error' : data.failed > 0 ? 'warning' : 'success',
          duration: 8000,
        })
      }
    } catch { /* ignore */ }
  }, [toast])

  const launchLinking = async () => {
    setLaunchingLink(true)
    try {
      const res = await apiClient.post('/wiki/admin/batch-link', {
        force: forceRelink, max_concurrent: 3,
      })
      const data = res.data as LinkBatchStatus
      setLinkStatus(data)
      toast({
        title: 'Linking lancé',
        description: `${data.total} articles en file d'attente`,
        status: 'info', duration: 5000,
      })
      if (linkPollingRef.current) clearInterval(linkPollingRef.current)
      linkPollingRef.current = setInterval(pollLinkStatus, 5000)
    } catch (err: any) {
      toast({
        title: 'Erreur lancement linking',
        description: err?.response?.data?.detail || err.message,
        status: 'error', duration: 5000,
      })
    } finally {
      setLaunchingLink(false)
    }
  }

  useEffect(() => {
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current)
      if (linkPollingRef.current) clearInterval(linkPollingRef.current)
    }
  }, [])

  const batchRunning = batchStatus?.status === 'running'
  const batchProgress = batchStatus
    ? ((batchStatus.completed + batchStatus.failed) / Math.max(batchStatus.total, 1)) * 100 : 0

  // Concepts sans article, filtrés par tier sélectionné, triés par score desc
  const missingConcepts = gaps.missing
    .filter(c => c.importance_tier <= maxTier)
    .sort((a, b) => b.importance_score - a.importance_score)

  const effectiveMax = generateAll ? missingConcepts.length : maxArticles

  if (!isAuthenticated) {
    return <Box p={8}><Text color="text.secondary">Authentification requise.</Text></Box>
  }

  return (
    <Box maxW="1200px" mx="auto" p={6}>
      {/* Header */}
      <VStack align="start" spacing={1} mb={8}>
        <HStack>
          <Icon as={FiZap} boxSize={6} color="purple.400" />
          <Heading size="lg" color="text.primary">Générateur Atlas</Heading>
          <Tooltip label="Recalculer le scoring">
            <Button size="xs" variant="ghost" onClick={loadScoring} isLoading={loadingScoring}>
              <Icon as={FiRefreshCw} />
            </Button>
          </Tooltip>
        </HStack>
        <Text color="text.secondary" fontSize="sm">
          Identifie automatiquement les concepts importants et génère les articles manquants.
        </Text>
      </VStack>

      {/* Situation actuelle — ce qui manque */}
      {scoring && (
        <SimpleGrid columns={{ base: 2, md: 4 }} spacing={4} mb={8}>
          <StatCard
            label="Articles existants"
            value={scoring.articles_count}
            total={scoring.total}
            color="green.400"
            sub={`sur ${scoring.total} concepts`}
          />
          <GapCard
            label="Tier 1 sans article"
            missing={gaps.t1}
            total={scoring.tier1_count}
            color="purple.400"
            desc="Portails — concepts structurants"
          />
          <GapCard
            label="Tier 2 sans article"
            missing={gaps.t2}
            total={scoring.tier2_count}
            color="blue.400"
            desc="Concepts principaux"
          />
          <GapCard
            label="Tier 3 sans article"
            missing={gaps.t3}
            total={scoring.tier3_count}
            color="gray.500"
            desc="Concepts spécifiques"
          />
        </SimpleGrid>
      )}

      {loadingScoring && !scoring && (
        <Flex justify="center" py={12}><Spinner size="lg" color="purple.400" /></Flex>
      )}

      {/* Génération — panneau principal */}
      <Box bg="surface.default" border="1px" borderColor="border.default" rounded="xl" p={6} mb={8}>
        <Heading size="md" color="text.primary" mb={1}>Générer les articles manquants</Heading>
        <Text fontSize="sm" color="text.secondary" mb={5}>
          Le systeme selectionne les concepts les plus importants et priorise ceux connectes
          aux articles existants pour tisser progressivement une toile de connaissance coherente.
        </Text>

        <Flex gap={6} wrap="wrap" align="end" mb={4}>
          <Box>
            <Text fontSize="sm" color="var(--text-secondary)" mb={1}>Périmètre</Text>
            <Select
              value={maxTier}
              onChange={e => setMaxTier(Number(e.target.value))}
              size="sm" w="220px"
              bg="var(--bg-tertiary)" color="var(--text-primary)" borderColor="var(--border-default)"
              sx={{ '& option': { background: 'var(--bg-tertiary)', color: 'var(--text-primary)' } }}
            >
              <option value={1}>Tier 1 uniquement ({gaps.t1} manquants)</option>
              <option value={2}>Tier 1 + 2 ({gaps.t1 + gaps.t2} manquants)</option>
              <option value={3}>Tous les tiers ({gaps.t1 + gaps.t2 + gaps.t3} manquants)</option>
            </Select>
          </Box>

          <Box>
            <Text fontSize="sm" color="var(--text-secondary)" mb={1}>Nombre d'articles</Text>
            <HStack spacing={2}>
              <NumberInput
                value={generateAll ? missingConcepts.length : maxArticles}
                onChange={(_, val) => { setGenerateAll(false); setMaxArticles(val || 10) }}
                min={1} max={9999} size="sm" w="100px"
                isDisabled={generateAll}
              >
                <NumberInputField bg="var(--bg-tertiary)" color="var(--text-primary)" borderColor="var(--border-default)" />
                <NumberInputStepper borderColor="var(--border-default)">
                  <NumberIncrementStepper color="var(--text-secondary)" />
                  <NumberDecrementStepper color="var(--text-secondary)" />
                </NumberInputStepper>
              </NumberInput>
              <Button
                size="sm"
                variant={generateAll ? 'solid' : 'outline'}
                colorScheme={generateAll ? 'purple' : 'gray'}
                onClick={() => setGenerateAll(!generateAll)}
                fontSize="xs"
              >
                Tous ({missingConcepts.length})
              </Button>
            </HStack>
          </Box>

          <Box>
            <Text fontSize="sm" color="var(--text-secondary)" mb={1}>Langue</Text>
            <Select
              value={language}
              onChange={e => setLanguage(e.target.value)}
              size="sm" w="140px"
              bg="var(--bg-tertiary)" color="var(--text-primary)" borderColor="var(--border-default)"
              sx={{ '& option': { background: 'var(--bg-tertiary)', color: 'var(--text-primary)' } }}
            >
              <option value="français">Français</option>
              <option value="english">English</option>
            </Select>
          </Box>

          <Button
            leftIcon={<FiPlay />}
            colorScheme="purple"
            size="md"
            onClick={launchBatch}
            isLoading={launching}
            isDisabled={batchRunning || missingConcepts.length === 0}
          >
            {missingConcepts.length === 0
              ? 'Aucun article à générer'
              : `Générer ${Math.min(effectiveMax, missingConcepts.length)} article${Math.min(effectiveMax, missingConcepts.length) > 1 ? 's' : ''}`
            }
          </Button>
        </Flex>

        {/* Batch progress */}
        {batchStatus && (
          <Box mt={4} pt={4} borderTop="1px" borderColor="border.default">
            <HStack mb={2} justify="space-between">
              <HStack>
                <Badge colorScheme={STATUS_COLORS[batchStatus.status] || 'gray'} fontSize="xs">
                  {batchStatus.status === 'running' ? 'En cours...' :
                   batchStatus.status === 'completed' ? 'Terminé' :
                   batchStatus.status === 'completed_with_errors' ? 'Terminé (avec erreurs)' :
                   batchStatus.status === 'suspended' ? 'Suspendu — vLLM indisponible' :
                   batchStatus.status}
                </Badge>
                <Text fontSize="sm" color="text.secondary">
                  {batchStatus.completed}/{batchStatus.total} terminés
                  {batchStatus.failed > 0 && ` — ${batchStatus.failed} échecs`}
                </Text>
              </HStack>
              {batchRunning && <Spinner size="sm" color="blue.400" />}
            </HStack>
            <Progress
              value={batchProgress}
              colorScheme={batchStatus.failed > 0 ? 'orange' : 'purple'}
              rounded="full" size="sm"
              hasStripe={batchRunning} isAnimated={batchRunning}
            />

            {/* Job list */}
            {batchStatus.jobs.length > 0 && (
              <Box mt={4} maxH="300px" overflowY="auto">
                <Table size="sm" variant="simple">
                  <Thead>
                    <Tr>
                      <Th color="text.muted">Concept</Th>
                      <Th color="text.muted">Tier</Th>
                      <Th color="text.muted">Statut</Th>
                      <Th color="text.muted">Article</Th>
                    </Tr>
                  </Thead>
                  <Tbody>
                    {batchStatus.jobs.map((job, i) => (
                      <Tr key={i}>
                        <Td color="text.primary" fontSize="sm">{job.concept_name}</Td>
                        <Td><Badge colorScheme={TIER_COLORS[job.importance_tier]} size="sm">T{job.importance_tier}</Badge></Td>
                        <Td>
                          <HStack spacing={1}>
                            {job.status === 'completed' && <Icon as={FiCheckCircle} color="green.400" boxSize={3} />}
                            {job.status === 'failed' && <Icon as={FiXCircle} color="red.400" boxSize={3} />}
                            {job.status === 'running' && <Spinner size="xs" color="blue.400" />}
                            <Text fontSize="sm" color={
                              job.status === 'completed' ? 'green.400' :
                              job.status === 'failed' ? 'red.400' :
                              job.status === 'running' ? 'blue.400' :
                              job.status === 'cancelled' ? 'orange.400' : 'var(--text-muted)'
                            }>
                              {job.status === 'completed' ? 'Créé' :
                               job.status === 'failed' ? 'Échec' :
                               job.status === 'running' ? 'En cours...' :
                               job.status === 'cancelled' ? 'Annulé' : 'En attente'}
                            </Text>
                          </HStack>
                          {job.error && <Text fontSize="xs" color="red.400" mt={1}>{job.error}</Text>}
                        </Td>
                        <Td>
                          {job.article_slug && (
                            <Link as={NextLink} href={`/wiki/${job.article_slug}`} color="blue.400" fontSize="sm">
                              <HStack spacing={1}><Text>Voir</Text><Icon as={FiExternalLink} boxSize={3} /></HStack>
                            </Link>
                          )}
                        </Td>
                      </Tr>
                    ))}
                  </Tbody>
                </Table>
              </Box>
            )}
          </Box>
        )}
      </Box>

      {/* Linking — injection de liens inter-concepts */}
      <Box bg="surface.default" border="1px" borderColor="border.default" rounded="xl" p={6} mb={8}>
        <Heading size="md" color="text.primary" mb={1}>
          <HStack spacing={2}>
            <Icon as={FiLink} color="blue.400" />
            <Text>Concept Linking</Text>
          </HStack>
        </Heading>
        <Text fontSize="sm" color="text.secondary" mb={5}>
          Injecte des liens inter-concepts dans les articles existants via LLM.
          Chaque mention contextuelle d'un concept est transformée en lien cliquable.
        </Text>

        <Flex gap={4} align="center" mb={4}>
          <Button
            leftIcon={<FiLink />}
            colorScheme="blue"
            size="md"
            onClick={launchLinking}
            isLoading={launchingLink}
            isDisabled={linkStatus?.status === 'running'}
          >
            Lancer le linking
          </Button>
          <Button
            size="sm"
            variant={forceRelink ? 'solid' : 'outline'}
            colorScheme={forceRelink ? 'orange' : 'gray'}
            onClick={() => setForceRelink(!forceRelink)}
            fontSize="xs"
          >
            {forceRelink ? 'Re-linker tout' : 'Nouveaux uniquement'}
          </Button>
        </Flex>

        {linkStatus && (
          <Box pt={4} borderTop="1px" borderColor="border.default">
            <HStack mb={2} justify="space-between">
              <HStack>
                <Badge colorScheme={STATUS_COLORS[linkStatus.status] || 'gray'} fontSize="xs">
                  {linkStatus.status === 'running' ? 'En cours...' :
                   linkStatus.status === 'completed' ? 'Terminé' :
                   linkStatus.status === 'suspended' ? 'Suspendu — vLLM indisponible' :
                   linkStatus.status}
                </Badge>
                <Text fontSize="sm" color="text.secondary">
                  {linkStatus.completed}/{linkStatus.total} linkés
                  {linkStatus.failed > 0 && ` — ${linkStatus.failed} échecs`}
                  {linkStatus.skipped > 0 && ` — ${linkStatus.skipped} ignorés`}
                </Text>
              </HStack>
              {linkStatus.status === 'running' && <Spinner size="sm" color="blue.400" />}
            </HStack>
            <Progress
              value={linkStatus.total > 0
                ? ((linkStatus.completed + linkStatus.failed + linkStatus.skipped) / linkStatus.total) * 100
                : 0}
              colorScheme={linkStatus.failed > 0 ? 'orange' : 'blue'}
              rounded="full" size="sm"
              hasStripe={linkStatus.status === 'running'}
              isAnimated={linkStatus.status === 'running'}
            />

            {linkStatus.jobs.length > 0 && (
              <Box mt={4} maxH="250px" overflowY="auto">
                <Table size="sm" variant="simple">
                  <Thead>
                    <Tr>
                      <Th color="text.muted">Article</Th>
                      <Th color="text.muted">Candidats</Th>
                      <Th color="text.muted">Liens</Th>
                      <Th color="text.muted">Statut</Th>
                    </Tr>
                  </Thead>
                  <Tbody>
                    {linkStatus.jobs.map((job, i) => (
                      <Tr key={i}>
                        <Td color="text.primary" fontSize="sm">
                          {job.title || job.slug}
                        </Td>
                        <Td color="text.secondary" fontSize="sm">{job.candidates_count}</Td>
                        <Td color="text.primary" fontSize="sm" fontWeight="medium">
                          {job.link_count > 0 ? job.link_count : '-'}
                        </Td>
                        <Td>
                          <HStack spacing={1}>
                            {job.status === 'completed' && <Icon as={FiCheckCircle} color="green.400" boxSize={3} />}
                            {job.status === 'failed' && <Icon as={FiXCircle} color="red.400" boxSize={3} />}
                            {job.status === 'running' && <Spinner size="xs" color="blue.400" />}
                            <Text fontSize="sm" color={
                              job.status === 'completed' ? 'green.400' :
                              job.status === 'failed' ? 'red.400' :
                              job.status === 'running' ? 'blue.400' :
                              job.status === 'cancelled' ? 'orange.400' :
                              job.status === 'skipped' ? 'gray.400' : 'var(--text-muted)'
                            }>
                              {job.status === 'completed' ? 'Linké' :
                               job.status === 'failed' ? 'Échec' :
                               job.status === 'running' ? 'En cours...' :
                               job.status === 'cancelled' ? 'Annulé' :
                               job.status === 'skipped' ? 'Ignoré' : 'En attente'}
                            </Text>
                          </HStack>
                          {job.error && <Text fontSize="xs" color="red.400" mt={1}>{job.error}</Text>}
                        </Td>
                      </Tr>
                    ))}
                  </Tbody>
                </Table>
              </Box>
            )}
          </Box>
        )}
      </Box>

      {/* Concepts sans article — aperçu de ce qui sera généré */}
      <Box bg="surface.default" border="1px" borderColor="border.default" rounded="xl" p={6}>
        <Flex justify="space-between" align="center" mb={4}>
          <HStack>
            <Icon as={FiAlertCircle} color="orange.400" />
            <Heading size="md" color="text.primary">Concepts sans article</Heading>
            <Badge colorScheme="orange">{missingConcepts.length}</Badge>
          </HStack>
          <Text fontSize="xs" color="text.muted">
            Triés par importance — les premiers seront générés en priorité
          </Text>
        </Flex>

        {missingConcepts.length === 0 ? (
          <Flex justify="center" py={8}>
            <VStack>
              <Icon as={FiCheckCircle} boxSize={8} color="green.400" />
              <Text color="text.secondary">Tous les concepts de ce périmètre ont un article.</Text>
            </VStack>
          </Flex>
        ) : (
          <Box maxH="500px" overflowY="auto">
            <Table size="sm" variant="simple">
              <Thead position="sticky" top={0} bg="surface.default" zIndex={1}>
                <Tr>
                  <Th color="text.muted" w="40px">#</Th>
                  <Th color="text.muted">Concept</Th>
                  <Th color="text.muted">Type</Th>
                  <Th color="text.muted" isNumeric>Claims</Th>
                  <Th color="text.muted" isNumeric>Sources</Th>
                  <Th color="text.muted" isNumeric>Score</Th>
                  <Th color="text.muted">Tier</Th>
                </Tr>
              </Thead>
              <Tbody>
                {missingConcepts.slice(0, 100).map((c, i) => (
                  <Tr
                    key={i}
                    _hover={{ bg: 'bg.hover' }}
                    opacity={i < maxArticles ? 1 : 0.5}
                    bg={i < maxArticles ? undefined : 'transparent'}
                  >
                    <Td color="text.muted" fontSize="xs">{i + 1}</Td>
                    <Td color="text.primary" fontWeight={i < maxArticles ? 'medium' : 'normal'} fontSize="sm">
                      {c.entity_name}
                      {i === maxArticles - 1 && maxArticles < missingConcepts.length && (
                        <Text as="span" fontSize="xs" color="text.muted" ml={2}>
                          limite
                        </Text>
                      )}
                    </Td>
                    <Td>
                      <Badge variant="subtle" colorScheme="gray" fontSize="xs">{c.entity_type}</Badge>
                    </Td>
                    <Td isNumeric color="text.secondary" fontSize="sm">{c.claim_count}</Td>
                    <Td isNumeric color="text.secondary" fontSize="sm">{c.doc_count}</Td>
                    <Td isNumeric color="text.primary" fontSize="sm">{c.importance_score.toFixed(1)}</Td>
                    <Td>
                      <Badge colorScheme={TIER_COLORS[c.importance_tier]} size="sm">T{c.importance_tier}</Badge>
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
            {missingConcepts.length > 100 && (
              <Text fontSize="xs" color="text.muted" textAlign="center" mt={2}>
                + {missingConcepts.length - 100} concepts supplémentaires non affichés
              </Text>
            )}
          </Box>
        )}
      </Box>
    </Box>
  )
}

// Stat card — articles existants
function StatCard({ label, value, total, color, sub }: {
  label: string; value: number; total: number; color: string; sub: string
}) {
  const pct = total > 0 ? ((value / total) * 100).toFixed(0) : '0'
  return (
    <Box bg="surface.default" border="1px" borderColor="border.default" rounded="xl" p={4}>
      <Text fontSize="2xl" fontWeight="bold" color={color}>{value}</Text>
      <Text fontSize="sm" color="text.primary" fontWeight="medium">{label}</Text>
      <Text fontSize="xs" color="text.muted">{sub} ({pct}%)</Text>
    </Box>
  )
}

// Gap card — concepts manquants par tier
function GapCard({ label, missing, total, color, desc }: {
  label: string; missing: number; total: number; color: string; desc: string
}) {
  const covered = total - missing
  const pct = total > 0 ? ((covered / total) * 100).toFixed(0) : '100'
  return (
    <Box bg="surface.default" border="1px" borderColor="border.default" rounded="xl" p={4}>
      <HStack justify="space-between" mb={1}>
        <Text fontSize="2xl" fontWeight="bold" color={missing > 0 ? 'orange.400' : 'green.400'}>
          {missing}
        </Text>
        <Text fontSize="xs" color="text.muted">{covered}/{total}</Text>
      </HStack>
      <Text fontSize="sm" color="text.primary" fontWeight="medium">{label}</Text>
      <Text fontSize="xs" color="text.muted">{desc}</Text>
      <Progress
        value={Number(pct)}
        size="xs"
        rounded="full"
        mt={2}
        colorScheme={missing > 0 ? 'orange' : 'green'}
      />
    </Box>
  )
}
