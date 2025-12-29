'use client'

/**
 * OSMOSE Consolidation Dashboard - Phase 2.11 v2
 *
 * Administration page for managing Knowledge Graph consolidation:
 * - Tab Claims: RawClaims → CanonicalClaims
 * - Tab Relations: RawAssertions → CanonicalRelations
 * - Global "Consolidate All" button
 * - Comprehensive statistics for both
 *
 * Future: Automation settings (every X imports, every X days)
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
  Tabs,
  TabList,
  TabPanels,
  Tab,
  TabPanel,
  Table,
  Thead,
  Tbody,
  Tr,
  Th,
  Td,
  TableContainer,
  Stat,
  StatLabel,
  StatNumber,
  StatHelpText,
  useToast,
  Tooltip,
  Progress,
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
} from 'react-icons/fi'
import { apiClient } from '@/lib/api'

const MotionBox = motion(Box)

// Types
interface ConsolidationStats {
  raw_claims_count: number
  raw_assertions_count: number
  canonical_claims_count: number
  canonical_relations_count: number
  claims_validated: number
  claims_candidate: number
  claims_conflicting: number
  claims_context_dependent: number
  relations_validated: number
  relations_candidate: number
  relations_ambiguous: number
  relation_types: Record<string, number>
}

interface ConflictInfo {
  claim_type: string
  subject_concept_id: string
  subject_name?: string
  conflicting_values: string[]
}

interface ConsolidationResult {
  claims_consolidated: number
  relations_consolidated: number
  conflicts_detected: number
  execution_time_ms: number
  claims_validated: number
  claims_candidate: number
  relations_validated: number
  relations_candidate: number
}

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
        bg={`rgba(99, 102, 241, 0.15)`}
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

// Flow Diagram Component
const FlowDiagram = ({ type }: { type: 'claims' | 'relations' }) => {
  const isRelations = type === 'relations'
  return (
    <HStack spacing={3} justify="center" py={4} flexWrap="wrap">
      <Box
        px={3}
        py={2}
        bg="yellow.900"
        border="1px solid"
        borderColor="yellow.600"
        rounded="lg"
      >
        <Text fontSize="sm" fontWeight="medium" color="yellow.200">
          {isRelations ? 'RawAssertion' : 'RawClaim'}
        </Text>
      </Box>
      <Icon as={FiArrowRight} boxSize={4} color="text.muted" />
      <Box
        px={3}
        py={2}
        bg="brand.900"
        border="1px solid"
        borderColor="brand.500"
        rounded="lg"
      >
        <Text fontSize="sm" fontWeight="medium" color="brand.200">
          Consolidation
        </Text>
      </Box>
      <Icon as={FiArrowRight} boxSize={4} color="text.muted" />
      <Box
        px={3}
        py={2}
        bg="green.900"
        border="1px solid"
        borderColor="green.500"
        rounded="lg"
      >
        <Text fontSize="sm" fontWeight="medium" color="green.200">
          {isRelations ? 'CanonicalRelation' : 'CanonicalClaim'}
        </Text>
      </Box>
      {isRelations && (
        <>
          <Icon as={FiArrowRight} boxSize={4} color="text.muted" />
          <Box
            px={3}
            py={2}
            bg="purple.900"
            border="1px solid"
            borderColor="purple.500"
            rounded="lg"
          >
            <Text fontSize="sm" fontWeight="medium" color="purple.200">
              Typed Edges
            </Text>
          </Box>
        </>
      )}
    </HStack>
  )
}

// Claims Tab Content
const ClaimsTab = ({
  stats,
  conflicts,
  claimTypes,
  onConsolidate,
  isConsolidating,
  lastResult,
}: {
  stats: ConsolidationStats | null
  conflicts: ConflictInfo[]
  claimTypes: string[]
  onConsolidate: () => void
  isConsolidating: boolean
  lastResult: ConsolidationResult | null
}) => (
  <VStack spacing={6} align="stretch">
    {/* Flow Diagram */}
    <Box bg="bg.tertiary" rounded="xl" border="1px solid" borderColor="border.default">
      <FlowDiagram type="claims" />
    </Box>

    {/* Action Button */}
    <HStack justify="space-between">
      <Text color="text.secondary" fontSize="sm">
        Consolide les RawClaims en CanonicalClaims avec calcul de maturité
      </Text>
      <Button
        leftIcon={<FiPlay />}
        colorScheme="brand"
        onClick={onConsolidate}
        isLoading={isConsolidating}
        loadingText="Consolidation..."
      >
        Consolider Claims
      </Button>
    </HStack>

    {/* Last Result */}
    {lastResult && lastResult.claims_consolidated > 0 && (
      <Alert status="success" variant="subtle" rounded="xl" bg="green.900" border="1px solid" borderColor="green.600">
        <AlertIcon color="green.400" />
        <Box>
          <AlertTitle color="green.200">Claims consolidés</AlertTitle>
          <AlertDescription color="green.300">
            {lastResult.claims_consolidated} claims ({lastResult.claims_validated} validés, {lastResult.claims_candidate} candidats, {lastResult.conflicts_detected} conflits)
          </AlertDescription>
        </Box>
      </Alert>
    )}

    {/* Stats Grid */}
    <SimpleGrid columns={{ base: 2, md: 4 }} spacing={4}>
      <StatCard
        title="RawClaims"
        value={stats?.raw_claims_count || 0}
        subtitle="Avant consolidation"
        icon={FiFileText}
        color="yellow"
      />
      <StatCard
        title="CanonicalClaims"
        value={stats?.canonical_claims_count || 0}
        subtitle="Après consolidation"
        icon={FiTarget}
        color="green"
      />
      <StatCard
        title="Validés"
        value={stats?.claims_validated || 0}
        subtitle="Multi-source"
        icon={FiCheckCircle}
        color="green"
      />
      <StatCard
        title="Conflits"
        value={stats?.claims_conflicting || 0}
        subtitle="À résoudre"
        icon={FiAlertTriangle}
        color="red"
      />
    </SimpleGrid>

    {/* Conflicts Table */}
    {conflicts.length > 0 && (
      <Box bg="bg.secondary" border="1px solid" borderColor="border.default" rounded="xl" overflow="hidden">
        <HStack px={4} py={3} bg="bg.tertiary" borderBottom="1px solid" borderColor="border.default">
          <Icon as={FiAlertTriangle} color="red.400" />
          <Text fontWeight="semibold" color="text.primary">Conflits détectés</Text>
          <Badge colorScheme="red">{conflicts.length}</Badge>
        </HStack>
        <TableContainer>
          <Table variant="simple" size="sm">
            <Thead>
              <Tr>
                <Th color="text.muted">Concept</Th>
                <Th color="text.muted">Type</Th>
                <Th color="text.muted">Valeurs en conflit</Th>
              </Tr>
            </Thead>
            <Tbody>
              {conflicts.slice(0, 5).map((conflict, idx) => (
                <Tr key={idx}>
                  <Td>
                    <Text color="text.primary" fontWeight="medium">
                      {conflict.subject_name || conflict.subject_concept_id}
                    </Text>
                  </Td>
                  <Td><Badge colorScheme="purple">{conflict.claim_type}</Badge></Td>
                  <Td>
                    <HStack spacing={1} flexWrap="wrap">
                      {conflict.conflicting_values.slice(0, 3).map((val, i) => (
                        <Badge key={i} colorScheme="red" variant="subtle" fontSize="xs">{val}</Badge>
                      ))}
                    </HStack>
                  </Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        </TableContainer>
      </Box>
    )}

    {/* KG/RAG Contract Explanation */}
    <Box bg="bg.secondary" border="1px solid" borderColor="border.default" rounded="xl" p={5}>
      <HStack mb={4}>
        <Icon as={FiZap} color="brand.400" />
        <Text fontWeight="semibold" color="text.primary">KG/RAG Contract</Text>
      </HStack>
      <SimpleGrid columns={{ base: 1, md: 3 }} spacing={4}>
        <Box p={3} bg="green.900" rounded="lg" borderLeft="3px solid" borderColor="green.400">
          <Text fontSize="sm" fontWeight="medium" color="green.200">VALIDATED = Facts</Text>
          <Text fontSize="xs" color="green.300">Affirmer sans hedging</Text>
        </Box>
        <Box p={3} bg="yellow.900" rounded="lg" borderLeft="3px solid" borderColor="yellow.400">
          <Text fontSize="sm" fontWeight="medium" color="yellow.200">CANDIDATE = Suggestions</Text>
          <Text fontSize="xs" color="yellow.300">Utiliser du hedging</Text>
        </Box>
        <Box p={3} bg="red.900" rounded="lg" borderLeft="3px solid" borderColor="red.400">
          <Text fontSize="sm" fontWeight="medium" color="red.200">CONFLICTING = Conflits</Text>
          <Text fontSize="xs" color="red.300">Mentionner le désaccord</Text>
        </Box>
      </SimpleGrid>
    </Box>
  </VStack>
)

// Relations Tab Content
const RelationsTab = ({
  stats,
  onConsolidate,
  isConsolidating,
  lastResult,
}: {
  stats: ConsolidationStats | null
  onConsolidate: () => void
  isConsolidating: boolean
  lastResult: ConsolidationResult | null
}) => (
  <VStack spacing={6} align="stretch">
    {/* Flow Diagram */}
    <Box bg="bg.tertiary" rounded="xl" border="1px solid" borderColor="border.default">
      <FlowDiagram type="relations" />
    </Box>

    {/* Action Button */}
    <HStack justify="space-between">
      <Text color="text.secondary" fontSize="sm">
        Consolide les RawAssertions en CanonicalRelations et crée les typed edges
      </Text>
      <Button
        leftIcon={<FiPlay />}
        colorScheme="brand"
        onClick={onConsolidate}
        isLoading={isConsolidating}
        loadingText="Consolidation..."
      >
        Consolider Relations
      </Button>
    </HStack>

    {/* Last Result */}
    {lastResult && lastResult.relations_consolidated > 0 && (
      <Alert status="success" variant="subtle" rounded="xl" bg="green.900" border="1px solid" borderColor="green.600">
        <AlertIcon color="green.400" />
        <Box>
          <AlertTitle color="green.200">Relations consolidées</AlertTitle>
          <AlertDescription color="green.300">
            {lastResult.relations_consolidated} relations ({lastResult.relations_validated} validées, {lastResult.relations_candidate} candidates)
          </AlertDescription>
        </Box>
      </Alert>
    )}

    {/* Stats Grid */}
    <SimpleGrid columns={{ base: 2, md: 4 }} spacing={4}>
      <StatCard
        title="RawAssertions"
        value={stats?.raw_assertions_count || 0}
        subtitle="Avant consolidation"
        icon={FiFileText}
        color="yellow"
      />
      <StatCard
        title="CanonicalRelations"
        value={stats?.canonical_relations_count || 0}
        subtitle="Après consolidation"
        icon={FiLink}
        color="green"
      />
      <StatCard
        title="Validées"
        value={stats?.relations_validated || 0}
        subtitle="Typed edges créés"
        icon={FiCheckCircle}
        color="green"
      />
      <StatCard
        title="Candidates"
        value={stats?.relations_candidate || 0}
        subtitle="Single source"
        icon={FiTarget}
        color="yellow"
      />
    </SimpleGrid>

    {/* Relation Types Distribution */}
    {stats?.relation_types && Object.keys(stats.relation_types).length > 0 && (
      <Box bg="bg.secondary" border="1px solid" borderColor="border.default" rounded="xl" overflow="hidden">
        <HStack px={4} py={3} bg="bg.tertiary" borderBottom="1px solid" borderColor="border.default">
          <Icon as={FiLayers} color="brand.400" />
          <Text fontWeight="semibold" color="text.primary">Types de relations</Text>
          <Badge colorScheme="brand">{Object.keys(stats.relation_types).length}</Badge>
        </HStack>
        <SimpleGrid columns={{ base: 2, md: 4 }} spacing={3} p={4}>
          {Object.entries(stats.relation_types).slice(0, 8).map(([type, count]) => (
            <HStack
              key={type}
              p={2}
              bg="bg.tertiary"
              rounded="lg"
              justify="space-between"
            >
              <Text fontSize="sm" color="text.primary" fontWeight="medium">
                {type}
              </Text>
              <Badge colorScheme="brand">{count}</Badge>
            </HStack>
          ))}
        </SimpleGrid>
      </Box>
    )}

    {/* Maturity Explanation */}
    <Box bg="bg.secondary" border="1px solid" borderColor="border.default" rounded="xl" p={5}>
      <HStack mb={4}>
        <Icon as={FiDatabase} color="brand.400" />
        <Text fontWeight="semibold" color="text.primary">Maturité des Relations</Text>
      </HStack>
      <SimpleGrid columns={{ base: 1, md: 3 }} spacing={4}>
        <Box p={3} bg="green.900" rounded="lg" borderLeft="3px solid" borderColor="green.400">
          <Text fontSize="sm" fontWeight="medium" color="green.200">VALIDATED</Text>
          <Text fontSize="xs" color="green.300">2+ sources distinctes → Typed edge créé</Text>
        </Box>
        <Box p={3} bg="yellow.900" rounded="lg" borderLeft="3px solid" borderColor="yellow.400">
          <Text fontSize="sm" fontWeight="medium" color="yellow.200">CANDIDATE</Text>
          <Text fontSize="xs" color="yellow.300">1 seule source → Pas de typed edge</Text>
        </Box>
        <Box p={3} bg="orange.900" rounded="lg" borderLeft="3px solid" borderColor="orange.400">
          <Text fontSize="sm" fontWeight="medium" color="orange.200">AMBIGUOUS_TYPE</Text>
          <Text fontSize="xs" color="orange.300">Type incertain (delta &lt; 0.15)</Text>
        </Box>
      </SimpleGrid>
    </Box>
  </VStack>
)

export default function ConsolidationPage() {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [lastClaimsResult, setLastClaimsResult] = useState<ConsolidationResult | null>(null)
  const [lastRelationsResult, setLastRelationsResult] = useState<ConsolidationResult | null>(null)
  const [lastAllResult, setLastAllResult] = useState<ConsolidationResult | null>(null)

  // Fetch consolidation stats
  const {
    data: statsData,
    isLoading: statsLoading,
    refetch: refetchStats,
  } = useQuery({
    queryKey: ['consolidation', 'stats'],
    queryFn: async () => {
      const [statsRes, conflictsRes, claimTypesRes] = await Promise.all([
        apiClient.get<ConsolidationStats>('/claims/stats'),
        apiClient.get('/claims/conflicts'),
        apiClient.get('/claims/claim-types'),
      ])
      return {
        stats: statsRes.data,
        conflicts: conflictsRes.data?.conflicts || [],
        claimTypes: claimTypesRes.data || [],
      }
    },
    refetchInterval: 30000,
  })

  // Consolidate Claims only
  const consolidateClaimsMutation = useMutation({
    mutationFn: async () => {
      const response = await apiClient.post<ConsolidationResult>('/claims/consolidate', {
        consolidate_claims: true,
        consolidate_relations: false,
      })
      if (!response.success) throw new Error(response.error || 'Consolidation failed')
      return response.data
    },
    onSuccess: (data) => {
      setLastClaimsResult(data!)
      queryClient.invalidateQueries({ queryKey: ['consolidation'] })
      toast({
        title: 'Claims consolidés',
        description: `${data!.claims_consolidated} claims traités`,
        status: 'success',
        duration: 4000,
      })
    },
    onError: (error: any) => {
      toast({ title: 'Erreur', description: error.message, status: 'error', duration: 5000 })
    },
  })

  // Consolidate Relations only
  const consolidateRelationsMutation = useMutation({
    mutationFn: async () => {
      const response = await apiClient.post<ConsolidationResult>('/claims/consolidate', {
        consolidate_claims: false,
        consolidate_relations: true,
      })
      if (!response.success) throw new Error(response.error || 'Consolidation failed')
      return response.data
    },
    onSuccess: (data) => {
      setLastRelationsResult(data!)
      queryClient.invalidateQueries({ queryKey: ['consolidation'] })
      toast({
        title: 'Relations consolidées',
        description: `${data!.relations_consolidated} relations traitées`,
        status: 'success',
        duration: 4000,
      })
    },
    onError: (error: any) => {
      toast({ title: 'Erreur', description: error.message, status: 'error', duration: 5000 })
    },
  })

  // Consolidate All
  const consolidateAllMutation = useMutation({
    mutationFn: async () => {
      const response = await apiClient.post<ConsolidationResult>('/claims/consolidate', {
        consolidate_claims: true,
        consolidate_relations: true,
      })
      if (!response.success) throw new Error(response.error || 'Consolidation failed')
      return response.data
    },
    onSuccess: (data) => {
      setLastAllResult(data!)
      setLastClaimsResult(data!)
      setLastRelationsResult(data!)
      queryClient.invalidateQueries({ queryKey: ['consolidation'] })
      toast({
        title: 'Consolidation complète',
        description: `${data!.claims_consolidated} claims, ${data!.relations_consolidated} relations`,
        status: 'success',
        duration: 5000,
      })
    },
    onError: (error: any) => {
      toast({ title: 'Erreur', description: error.message, status: 'error', duration: 5000 })
    },
  })

  const isAnyConsolidating =
    consolidateClaimsMutation.isPending ||
    consolidateRelationsMutation.isPending ||
    consolidateAllMutation.isPending

  if (statsLoading) {
    return (
      <Center h="400px">
        <VStack spacing={4}>
          <Spinner size="xl" color="brand.500" thickness="3px" />
          <Text color="text.muted">Chargement des statistiques...</Text>
        </VStack>
      </Center>
    )
  }

  const stats = statsData?.stats || null
  const conflicts = statsData?.conflicts || []
  const claimTypes = statsData?.claimTypes || []

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
              bgGradient="linear(to-br, brand.500, accent.400)"
              display="flex"
              alignItems="center"
              justifyContent="center"
              boxShadow="0 0 20px rgba(99, 102, 241, 0.3)"
            >
              <Icon as={FiGitMerge} boxSize={5} color="white" />
            </Box>
            <VStack align="start" spacing={0}>
              <Text fontSize="2xl" fontWeight="bold" color="text.primary">
                Consolidation
              </Text>
              <Text color="text.secondary" fontSize="sm">
                Agrégation des extractions brutes en connaissances canoniques
              </Text>
            </VStack>
          </HStack>

          <Tooltip label="Consolide Claims ET Relations en une seule opération">
            <Button
              leftIcon={<FiRefreshCw />}
              colorScheme="brand"
              size="lg"
              onClick={() => consolidateAllMutation.mutate()}
              isLoading={consolidateAllMutation.isPending}
              loadingText="Consolidation..."
              _hover={{
                transform: 'translateY(-2px)',
                boxShadow: '0 0 20px rgba(99, 102, 241, 0.4)',
              }}
            >
              Tout consolider
            </Button>
          </Tooltip>
        </HStack>
      </MotionBox>

      {/* Global Result Alert */}
      {lastAllResult && (
        <MotionBox initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} mb={6}>
          <Alert status="success" variant="subtle" rounded="xl" bg="green.900" border="1px solid" borderColor="green.600">
            <AlertIcon color="green.400" />
            <Box flex="1">
              <AlertTitle color="green.200">Consolidation complète réussie</AlertTitle>
              <AlertDescription color="green.300">
                {lastAllResult.claims_consolidated} claims et {lastAllResult.relations_consolidated} relations
                consolidés en {(lastAllResult.execution_time_ms / 1000).toFixed(2)}s
              </AlertDescription>
            </Box>
          </Alert>
        </MotionBox>
      )}

      {/* Tabs */}
      <MotionBox
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, delay: 0.1 }}
      >
        <Tabs variant="soft-rounded" colorScheme="brand">
          <TabList mb={6} bg="bg.secondary" p={2} rounded="xl" border="1px solid" borderColor="border.default">
            <Tab
              _selected={{ bg: 'brand.500', color: 'white' }}
              color="text.secondary"
              fontWeight="medium"
            >
              <HStack>
                <Icon as={FiTarget} />
                <Text>Claims</Text>
                <Badge colorScheme="brand" variant="subtle">{stats?.canonical_claims_count || 0}</Badge>
              </HStack>
            </Tab>
            <Tab
              _selected={{ bg: 'brand.500', color: 'white' }}
              color="text.secondary"
              fontWeight="medium"
            >
              <HStack>
                <Icon as={FiLink} />
                <Text>Relations</Text>
                <Badge colorScheme="brand" variant="subtle">{stats?.canonical_relations_count || 0}</Badge>
              </HStack>
            </Tab>
          </TabList>

          <TabPanels>
            <TabPanel p={0}>
              <ClaimsTab
                stats={stats}
                conflicts={conflicts}
                claimTypes={claimTypes}
                onConsolidate={() => consolidateClaimsMutation.mutate()}
                isConsolidating={consolidateClaimsMutation.isPending}
                lastResult={lastClaimsResult}
              />
            </TabPanel>
            <TabPanel p={0}>
              <RelationsTab
                stats={stats}
                onConsolidate={() => consolidateRelationsMutation.mutate()}
                isConsolidating={consolidateRelationsMutation.isPending}
                lastResult={lastRelationsResult}
              />
            </TabPanel>
          </TabPanels>
        </Tabs>
      </MotionBox>

      {/* Future: Automation Settings */}
      <MotionBox
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, delay: 0.3 }}
        mt={8}
      >
        <Box
          bg="bg.secondary"
          border="1px dashed"
          borderColor="border.default"
          rounded="xl"
          p={5}
          opacity={0.7}
        >
          <HStack spacing={3}>
            <Icon as={FiZap} color="text.muted" />
            <VStack align="start" spacing={0}>
              <Text fontWeight="medium" color="text.muted">
                Automatisation (à venir)
              </Text>
              <Text fontSize="sm" color="text.muted">
                Configuration pour consolider automatiquement tous les X imports ou X jours
              </Text>
            </VStack>
          </HStack>
        </Box>
      </MotionBox>
    </Box>
  )
}
