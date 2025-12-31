'use client'

/**
 * OSMOSE Pass 2 Dashboard - Hybrid Anchor Model Enrichment
 *
 * Page d'administration pour gérer les phases Pass 2:
 * 1. CLASSIFY_FINE - Classification LLM fine-grained
 * 2. ENRICH_RELATIONS - Détection relations cross-segment + persistence
 * 3. CONSOLIDATE_CLAIMS - RawClaims → CanonicalClaims
 * 4. CONSOLIDATE_RELATIONS - RawAssertions → CanonicalRelations
 *
 * Réutilise les composants existants de la page consolidation.
 */

import { useState } from 'react'
import {
  Box,
  Button,
  HStack,
  Icon,
  Text,
  VStack,
  Spinner,
  Center,
  SimpleGrid,
  Badge,
  Alert,
  AlertIcon,
  AlertTitle,
  AlertDescription,
  Divider,
  Progress,
  useToast,
  Tooltip,
  Card,
  CardHeader,
  CardBody,
  Heading,
  Accordion,
  AccordionItem,
  AccordionButton,
  AccordionPanel,
  AccordionIcon,
} from '@chakra-ui/react'
import { motion } from 'framer-motion'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  FiDatabase,
  FiRefreshCw,
  FiCheckCircle,
  FiAlertTriangle,
  FiLayers,
  FiGitMerge,
  FiZap,
  FiArrowRight,
  FiTarget,
  FiLink,
  FiFileText,
  FiPlay,
  FiCpu,
  FiGrid,
  FiBox,
  FiActivity,
} from 'react-icons/fi'
import { apiClient } from '@/lib/api'

const MotionBox = motion(Box)

// Types
interface Pass2Status {
  proto_concepts: number
  canonical_concepts: number
  raw_assertions: number
  raw_claims: number
  canonical_relations: number
  canonical_claims: number
  pending_jobs: number
  running_jobs: number
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
  description: string
  icon: any
  color: string
  endpoint: string
}

const phases: PhaseConfig[] = [
  {
    id: 'classify-fine',
    name: 'Classification Fine',
    description: 'Affine les types heuristiques avec classification LLM',
    icon: FiCpu,
    color: 'purple',
    endpoint: '/admin/pass2/classify-fine',
  },
  {
    id: 'enrich-relations',
    name: 'Enrichissement Relations',
    description: 'Détecte relations cross-segment et persiste en RawAssertions',
    icon: FiLink,
    color: 'blue',
    endpoint: '/admin/pass2/enrich-relations',
  },
  {
    id: 'consolidate-claims',
    name: 'Consolidation Claims',
    description: 'Groupe RawClaims → CanonicalClaims avec calcul maturité',
    icon: FiTarget,
    color: 'green',
    endpoint: '/admin/pass2/consolidate-claims',
  },
  {
    id: 'consolidate-relations',
    name: 'Consolidation Relations',
    description: 'Groupe RawAssertions → CanonicalRelations + typed edges',
    icon: FiGitMerge,
    color: 'orange',
    endpoint: '/admin/pass2/consolidate-relations',
  },
]

// Stat Card Component
const StatCard = ({
  title,
  value,
  subtitle,
  icon,
  color = 'brand',
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
    p={4}
    _hover={{
      borderColor: `${color}.500`,
      transform: 'translateY(-2px)',
    }}
    transition="all 0.2s"
  >
    <HStack spacing={3}>
      <Box
        w={10}
        h={10}
        rounded="lg"
        bg={`${color}.900`}
        display="flex"
        alignItems="center"
        justifyContent="center"
      >
        <Icon as={icon} boxSize={5} color={`${color}.400`} />
      </Box>
      <VStack align="start" spacing={0} flex={1}>
        <Text fontSize="xs" color="text.muted" textTransform="uppercase">
          {title}
        </Text>
        <Text fontSize="xl" fontWeight="bold" color="text.primary">
          {value}
        </Text>
        {subtitle && (
          <Text fontSize="xs" color="text.muted">
            {subtitle}
          </Text>
        )}
      </VStack>
    </HStack>
  </Box>
)

// Phase Card Component
const PhaseCard = ({
  phase,
  onRun,
  isRunning,
  lastResult,
}: {
  phase: PhaseConfig
  onRun: () => void
  isRunning: boolean
  lastResult: Pass2Result | null
}) => {
  const hasResult = lastResult?.phase === phase.name

  return (
    <Box
      bg="bg.secondary"
      border="1px solid"
      borderColor={hasResult && lastResult?.success ? 'green.500' : 'border.default'}
      rounded="xl"
      p={5}
      _hover={{ borderColor: `${phase.color}.500` }}
      transition="all 0.2s"
    >
      <HStack spacing={4} mb={4}>
        <Box
          w={12}
          h={12}
          rounded="xl"
          bg={`${phase.color}.900`}
          display="flex"
          alignItems="center"
          justifyContent="center"
        >
          <Icon as={phase.icon} boxSize={6} color={`${phase.color}.400`} />
        </Box>
        <VStack align="start" spacing={1} flex={1}>
          <Text fontWeight="semibold" color="text.primary">
            {phase.name}
          </Text>
          <Text fontSize="sm" color="text.muted">
            {phase.description}
          </Text>
        </VStack>
      </HStack>

      {hasResult && (
        <Box mb={4} p={3} bg="bg.tertiary" rounded="lg">
          <HStack justify="space-between" mb={2}>
            <HStack>
              <Icon
                as={lastResult.success ? FiCheckCircle : FiAlertTriangle}
                color={lastResult.success ? 'green.400' : 'red.400'}
              />
              <Text fontSize="sm" color={lastResult.success ? 'green.300' : 'red.300'}>
                {lastResult.success ? 'Succès' : 'Erreur'}
              </Text>
            </HStack>
            <Text fontSize="xs" color="text.muted">
              {(lastResult.execution_time_ms / 1000).toFixed(1)}s
            </Text>
          </HStack>
          <SimpleGrid columns={3} spacing={2}>
            <VStack spacing={0}>
              <Text fontSize="lg" fontWeight="bold" color="text.primary">
                {lastResult.items_processed}
              </Text>
              <Text fontSize="xs" color="text.muted">Traités</Text>
            </VStack>
            <VStack spacing={0}>
              <Text fontSize="lg" fontWeight="bold" color="green.400">
                {lastResult.items_created}
              </Text>
              <Text fontSize="xs" color="text.muted">Créés</Text>
            </VStack>
            <VStack spacing={0}>
              <Text fontSize="lg" fontWeight="bold" color="blue.400">
                {lastResult.items_updated}
              </Text>
              <Text fontSize="xs" color="text.muted">Maj</Text>
            </VStack>
          </SimpleGrid>
          {lastResult.errors.length > 0 && (
            <Text fontSize="xs" color="red.400" mt={2}>
              {lastResult.errors.join(', ')}
            </Text>
          )}
        </Box>
      )}

      <Button
        leftIcon={<FiPlay />}
        colorScheme={phase.color}
        size="sm"
        w="full"
        onClick={onRun}
        isLoading={isRunning}
        loadingText="Exécution..."
      >
        Exécuter
      </Button>
    </Box>
  )
}

// Flow Diagram
const Pass2FlowDiagram = () => (
  <Box
    bg="bg.tertiary"
    border="1px solid"
    borderColor="border.default"
    rounded="xl"
    p={6}
    mb={6}
  >
    <Text fontWeight="semibold" color="text.primary" mb={4} textAlign="center">
      Pipeline Pass 2 - Hybrid Anchor Model
    </Text>
    <HStack spacing={2} justify="center" flexWrap="wrap">
      <Box px={3} py={2} bg="yellow.900" border="1px solid" borderColor="yellow.600" rounded="lg">
        <Text fontSize="sm" fontWeight="medium" color="yellow.200">Pass 1</Text>
        <Text fontSize="xs" color="yellow.300">Proto → Canonical</Text>
      </Box>
      <Icon as={FiArrowRight} boxSize={4} color="text.muted" />
      <Box px={3} py={2} bg="purple.900" border="1px solid" borderColor="purple.500" rounded="lg">
        <Text fontSize="sm" fontWeight="medium" color="purple.200">Classify Fine</Text>
      </Box>
      <Icon as={FiArrowRight} boxSize={4} color="text.muted" />
      <Box px={3} py={2} bg="blue.900" border="1px solid" borderColor="blue.500" rounded="lg">
        <Text fontSize="sm" fontWeight="medium" color="blue.200">Enrich Relations</Text>
      </Box>
      <Icon as={FiArrowRight} boxSize={4} color="text.muted" />
      <Box px={3} py={2} bg="green.900" border="1px solid" borderColor="green.500" rounded="lg">
        <Text fontSize="sm" fontWeight="medium" color="green.200">Consolidation</Text>
      </Box>
      <Icon as={FiArrowRight} boxSize={4} color="text.muted" />
      <Box px={3} py={2} bg="brand.900" border="1px solid" borderColor="brand.500" rounded="lg">
        <Text fontSize="sm" fontWeight="medium" color="brand.200">KG Enrichi</Text>
      </Box>
    </HStack>
  </Box>
)

export default function Pass2DashboardPage() {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [phaseResults, setPhaseResults] = useState<Record<string, Pass2Result>>({})
  const [runningPhase, setRunningPhase] = useState<string | null>(null)

  // Fetch Pass 2 status
  const {
    data: status,
    isLoading: statusLoading,
    refetch: refetchStatus,
  } = useQuery({
    queryKey: ['pass2', 'status'],
    queryFn: async () => {
      const res = await apiClient.get<Pass2Status>('/admin/pass2/status')
      if (!res.success) throw new Error(res.error)
      return res.data
    },
    refetchInterval: 10000,
  })

  // Run individual phase
  const runPhaseMutation = useMutation({
    mutationFn: async ({ endpoint, phaseId }: { endpoint: string; phaseId: string }) => {
      setRunningPhase(phaseId)
      const res = await apiClient.post<Pass2Result>(endpoint, {
        limit: 100,
      })
      if (!res.success) throw new Error(res.error || 'Phase failed')
      return { result: res.data, phaseId }
    },
    onSuccess: ({ result, phaseId }) => {
      if (result) {
        setPhaseResults((prev) => ({ ...prev, [phaseId]: result }))
      }
      queryClient.invalidateQueries({ queryKey: ['pass2'] })
      toast({
        title: 'Phase terminée',
        description: `${result?.items_processed || 0} items traités, ${result?.items_created || 0} créés`,
        status: result?.success ? 'success' : 'warning',
        duration: 4000,
      })
    },
    onError: (error: any) => {
      toast({
        title: 'Erreur',
        description: error.message,
        status: 'error',
        duration: 5000,
      })
    },
    onSettled: () => {
      setRunningPhase(null)
    },
  })

  // Run full Pass 2
  const runFullMutation = useMutation({
    mutationFn: async () => {
      const res = await apiClient.post('/admin/pass2/run-full', {
        skip_classify: false,
        skip_enrich: false,
        skip_consolidate: false,
      })
      if (!res.success) throw new Error(res.error || 'Full Pass 2 failed')
      return res.data
    },
    onSuccess: (data: any) => {
      queryClient.invalidateQueries({ queryKey: ['pass2'] })
      const totalProcessed = Object.values(data.phases || {}).reduce(
        (sum: number, p: any) => sum + (p.items_processed || 0),
        0
      )
      toast({
        title: 'Pass 2 complet terminé',
        description: `${totalProcessed} items traités au total`,
        status: data.success ? 'success' : 'warning',
        duration: 5000,
      })
    },
    onError: (error: any) => {
      toast({
        title: 'Erreur Pass 2',
        description: error.message,
        status: 'error',
        duration: 5000,
      })
    },
  })

  if (statusLoading) {
    return (
      <Center h="400px">
        <VStack spacing={4}>
          <Spinner size="xl" color="brand.500" thickness="3px" />
          <Text color="text.muted">Chargement du statut Pass 2...</Text>
        </VStack>
      </Center>
    )
  }

  return (
    <Box maxW="1400px" mx="auto">
      {/* Header */}
      <MotionBox
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
        mb={6}
      >
        <HStack spacing={3} justify="space-between" flexWrap="wrap" gap={4}>
          <HStack spacing={3}>
            <Box
              w={10}
              h={10}
              rounded="lg"
              bgGradient="linear(to-br, brand.500, purple.400)"
              display="flex"
              alignItems="center"
              justifyContent="center"
              boxShadow="0 0 20px rgba(99, 102, 241, 0.3)"
            >
              <Icon as={FiActivity} boxSize={5} color="white" />
            </Box>
            <VStack align="start" spacing={0}>
              <Text fontSize="2xl" fontWeight="bold" color="text.primary">
                Pass 2 Dashboard
              </Text>
              <Text color="text.secondary" fontSize="sm">
                Enrichissement du Knowledge Graph (Hybrid Anchor Model)
              </Text>
            </VStack>
          </HStack>

          <HStack spacing={3}>
            <Tooltip label="Rafraîchir le statut">
              <Button
                leftIcon={<FiRefreshCw />}
                variant="outline"
                onClick={() => refetchStatus()}
              >
                Rafraîchir
              </Button>
            </Tooltip>
            <Tooltip label="Exécute toutes les phases dans l'ordre">
              <Button
                leftIcon={<FiZap />}
                colorScheme="brand"
                size="lg"
                onClick={() => runFullMutation.mutate()}
                isLoading={runFullMutation.isPending}
                loadingText="Exécution..."
                _hover={{
                  transform: 'translateY(-2px)',
                  boxShadow: '0 0 20px rgba(99, 102, 241, 0.4)',
                }}
              >
                Exécuter Pass 2 Complet
              </Button>
            </Tooltip>
          </HStack>
        </HStack>
      </MotionBox>

      {/* Flow Diagram */}
      <Pass2FlowDiagram />

      {/* Status Cards */}
      <SimpleGrid columns={{ base: 2, md: 4, lg: 8 }} spacing={4} mb={8}>
        <StatCard
          title="ProtoConcepts"
          value={status?.proto_concepts || 0}
          icon={FiBox}
          color="yellow"
        />
        <StatCard
          title="CanonicalConcepts"
          value={status?.canonical_concepts || 0}
          icon={FiGrid}
          color="green"
        />
        <StatCard
          title="RawAssertions"
          value={status?.raw_assertions || 0}
          icon={FiFileText}
          color="orange"
        />
        <StatCard
          title="RawClaims"
          value={status?.raw_claims || 0}
          icon={FiFileText}
          color="blue"
        />
        <StatCard
          title="CanonicalRelations"
          value={status?.canonical_relations || 0}
          icon={FiLink}
          color="purple"
        />
        <StatCard
          title="CanonicalClaims"
          value={status?.canonical_claims || 0}
          icon={FiTarget}
          color="teal"
        />
        <StatCard
          title="Jobs en attente"
          value={status?.pending_jobs || 0}
          icon={FiLayers}
          color="gray"
        />
        <StatCard
          title="Jobs en cours"
          value={status?.running_jobs || 0}
          icon={FiActivity}
          color="brand"
        />
      </SimpleGrid>

      {/* Alert if no RawAssertions */}
      {status && status.raw_assertions === 0 && status.canonical_concepts > 0 && (
        <Alert status="info" variant="subtle" rounded="xl" mb={6} bg="blue.900" border="1px solid" borderColor="blue.600">
          <AlertIcon color="blue.400" />
          <Box>
            <AlertTitle color="blue.200">Relations non extraites</AlertTitle>
            <AlertDescription color="blue.300">
              Aucune RawAssertion n'existe. Exécutez "Enrichissement Relations" pour détecter
              les relations cross-segment et les persister dans Neo4j.
            </AlertDescription>
          </Box>
        </Alert>
      )}

      {/* Phases Grid */}
      <Text fontSize="lg" fontWeight="semibold" color="text.primary" mb={4}>
        Phases Pass 2
      </Text>
      <SimpleGrid columns={{ base: 1, md: 2, lg: 4 }} spacing={4} mb={8}>
        {phases.map((phase) => (
          <PhaseCard
            key={phase.id}
            phase={phase}
            onRun={() => runPhaseMutation.mutate({ endpoint: phase.endpoint, phaseId: phase.id })}
            isRunning={runningPhase === phase.id}
            lastResult={phaseResults[phase.id] || null}
          />
        ))}
      </SimpleGrid>

      {/* Architecture Info */}
      <Accordion allowToggle>
        <AccordionItem border="1px solid" borderColor="border.default" rounded="xl" mb={4}>
          <AccordionButton py={4} _expanded={{ bg: 'bg.secondary' }} rounded="xl">
            <HStack flex="1">
              <Icon as={FiDatabase} color="brand.400" />
              <Text fontWeight="semibold" color="text.primary">
                Architecture Hybrid Anchor Model
              </Text>
            </HStack>
            <AccordionIcon />
          </AccordionButton>
          <AccordionPanel pb={4}>
            <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
              <Box p={4} bg="bg.tertiary" rounded="lg">
                <Text fontWeight="semibold" color="text.primary" mb={2}>Pass 1 (Ingestion)</Text>
                <VStack align="start" spacing={1}>
                  <Text fontSize="sm" color="text.muted">1. EXTRACT_CONCEPTS - Extraction NER + LLM</Text>
                  <Text fontSize="sm" color="text.muted">2. ANCHOR_RESOLUTION - Matching texte ↔ concepts</Text>
                  <Text fontSize="sm" color="text.muted">3. GATE_CHECK - Promotion Proto → Canonical</Text>
                  <Text fontSize="sm" color="text.muted">4. CHUNK - Découpage document-centric</Text>
                </VStack>
              </Box>
              <Box p={4} bg="bg.tertiary" rounded="lg">
                <Text fontWeight="semibold" color="text.primary" mb={2}>Pass 2 (Enrichissement)</Text>
                <VStack align="start" spacing={1}>
                  <Text fontSize="sm" color="text.muted">1. CLASSIFY_FINE - Classification LLM fine-grained</Text>
                  <Text fontSize="sm" color="text.muted">2. ENRICH_RELATIONS - Relations cross-segment</Text>
                  <Text fontSize="sm" color="text.muted">3. CONSOLIDATE - Claims + Relations → Canonical</Text>
                  <Text fontSize="sm" color="text.muted">4. CROSS_DOC - Consolidation corpus (TODO)</Text>
                </VStack>
              </Box>
            </SimpleGrid>
          </AccordionPanel>
        </AccordionItem>

        <AccordionItem border="1px solid" borderColor="border.default" rounded="xl">
          <AccordionButton py={4} _expanded={{ bg: 'bg.secondary' }} rounded="xl">
            <HStack flex="1">
              <Icon as={FiZap} color="brand.400" />
              <Text fontWeight="semibold" color="text.primary">
                KG/RAG Contract (Maturité)
              </Text>
            </HStack>
            <AccordionIcon />
          </AccordionButton>
          <AccordionPanel pb={4}>
            <SimpleGrid columns={{ base: 1, md: 3 }} spacing={4}>
              <Box p={4} bg="green.900" rounded="lg" borderLeft="3px solid" borderColor="green.400">
                <Text fontWeight="semibold" color="green.200">VALIDATED</Text>
                <Text fontSize="sm" color="green.300">2+ sources distinctes</Text>
                <Text fontSize="xs" color="green.400" mt={2}>→ Affirmer sans hedging</Text>
              </Box>
              <Box p={4} bg="yellow.900" rounded="lg" borderLeft="3px solid" borderColor="yellow.400">
                <Text fontWeight="semibold" color="yellow.200">CANDIDATE</Text>
                <Text fontSize="sm" color="yellow.300">1 seule source</Text>
                <Text fontSize="xs" color="yellow.400" mt={2}>→ Utiliser du hedging</Text>
              </Box>
              <Box p={4} bg="red.900" rounded="lg" borderLeft="3px solid" borderColor="red.400">
                <Text fontWeight="semibold" color="red.200">CONFLICTING</Text>
                <Text fontSize="sm" color="red.300">Valeurs contradictoires</Text>
                <Text fontSize="xs" color="red.400" mt={2}>→ Mentionner le désaccord</Text>
              </Box>
            </SimpleGrid>
          </AccordionPanel>
        </AccordionItem>
      </Accordion>
    </Box>
  )
}
