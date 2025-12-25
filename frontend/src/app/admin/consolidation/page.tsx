'use client'

/**
 * OSMOS Consolidation Dashboard - Phase 2.11
 *
 * Administration page for managing Knowledge Graph consolidation:
 * - Trigger consolidation of RawClaims → CanonicalClaims
 * - Trigger consolidation of RawAssertions → CanonicalRelations
 * - View statistics and conflicts
 * - Monitor KG/RAG Contract status
 */

import { useState } from 'react'
import {
  Box,
  Button,
  Grid,
  GridItem,
  HStack,
  Icon,
  Text,
  VStack,
  Spinner,
  Center,
  SimpleGrid,
  Badge,
  Divider,
  Alert,
  AlertIcon,
  AlertTitle,
  AlertDescription,
  Progress,
  Tooltip,
  useToast,
  Table,
  Thead,
  Tbody,
  Tr,
  Th,
  Td,
  TableContainer,
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
  FiActivity,
  FiArrowRight,
  FiClock,
  FiFileText,
  FiTarget,
} from 'react-icons/fi'
import { apiClient } from '@/lib/api'

const MotionBox = motion(Box)

// Types
interface ConsolidationStats {
  raw_claims: number
  canonical_claims: number
  raw_assertions: number
  canonical_relations: number
  validated_claims: number
  candidate_claims: number
  conflicting_claims: number
  validated_relations: number
  candidate_relations: number
}

interface ConflictInfo {
  claim_type: string
  subject_concept_id: string
  subject_name?: string
  conflicting_values: string[]
  resolution_suggestion?: string
}

interface ConsolidationResult {
  claims_consolidated: number
  relations_consolidated: number
  conflicts_detected: number
  execution_time_ms: number
}

// Stat Card Component
const StatCard = ({
  title,
  value,
  subtitle,
  icon,
  color = 'brand',
  delay = 0,
}: {
  title: string
  value: string | number
  subtitle?: string
  icon: any
  color?: string
  delay?: number
}) => (
  <MotionBox
    initial={{ opacity: 0, y: 20 }}
    animate={{ opacity: 1, y: 0 }}
    transition={{ duration: 0.4, delay }}
  >
    <Box
      bg="bg.secondary"
      border="1px solid"
      borderColor="border.default"
      rounded="xl"
      p={5}
      position="relative"
      overflow="hidden"
      _hover={{
        borderColor: `${color}.500`,
        transform: 'translateY(-2px)',
        boxShadow: `0 0 20px rgba(99, 102, 241, 0.1)`,
      }}
      transition="all 0.2s"
    >
      <HStack spacing={4}>
        <Box
          w={12}
          h={12}
          rounded="xl"
          bg={`rgba(99, 102, 241, 0.15)`}
          display="flex"
          alignItems="center"
          justifyContent="center"
        >
          <Icon as={icon} boxSize={6} color={`${color}.400`} />
        </Box>
        <VStack align="start" spacing={0} flex={1}>
          <Text fontSize="xs" color="text.muted" textTransform="uppercase" letterSpacing="wide">
            {title}
          </Text>
          <Text fontSize="2xl" fontWeight="bold" color="text.primary">
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
  </MotionBox>
)

// Maturity Badge Component
const MaturityBadge = ({ maturity, count }: { maturity: string; count: number }) => {
  const colorScheme = {
    VALIDATED: 'green',
    CANDIDATE: 'yellow',
    CONFLICTING: 'red',
    CONTEXT_DEPENDENT: 'purple',
    SUPERSEDED: 'gray',
    AMBIGUOUS_TYPE: 'orange',
  }[maturity] || 'gray'

  return (
    <Badge colorScheme={colorScheme} px={2} py={1} rounded="md" fontSize="xs">
      {maturity}: {count}
    </Badge>
  )
}

// Section Card
const SectionCard = ({
  title,
  icon,
  children,
  delay = 0,
  action,
}: {
  title: string
  icon: any
  children: React.ReactNode
  delay?: number
  action?: React.ReactNode
}) => (
  <MotionBox
    initial={{ opacity: 0, y: 20 }}
    animate={{ opacity: 1, y: 0 }}
    transition={{ duration: 0.4, delay }}
  >
    <Box
      bg="bg.secondary"
      border="1px solid"
      borderColor="border.default"
      rounded="xl"
      overflow="hidden"
    >
      <HStack
        px={5}
        py={4}
        borderBottom="1px solid"
        borderColor="border.default"
        bg="bg.tertiary"
        justify="space-between"
      >
        <HStack>
          <Icon as={icon} boxSize={5} color="brand.400" />
          <Text fontWeight="semibold" color="text.primary">
            {title}
          </Text>
        </HStack>
        {action}
      </HStack>
      <Box p={5}>
        {children}
      </Box>
    </Box>
  </MotionBox>
)

// Consolidation Flow Diagram
const ConsolidationFlowDiagram = () => (
  <Box
    bg="bg.tertiary"
    rounded="xl"
    p={6}
    border="1px solid"
    borderColor="border.default"
  >
    <HStack spacing={4} justify="center" align="center" flexWrap="wrap">
      <VStack spacing={1}>
        <Box
          px={4}
          py={2}
          bg="yellow.900"
          border="1px solid"
          borderColor="yellow.600"
          rounded="lg"
        >
          <Text fontSize="sm" fontWeight="medium" color="yellow.200">
            RawClaim / RawAssertion
          </Text>
        </Box>
        <Text fontSize="xs" color="text.muted">Extraction</Text>
      </VStack>

      <Icon as={FiArrowRight} boxSize={5} color="text.muted" />

      <VStack spacing={1}>
        <Box
          px={4}
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
        <Text fontSize="xs" color="text.muted">Groupement + Maturite</Text>
      </VStack>

      <Icon as={FiArrowRight} boxSize={5} color="text.muted" />

      <VStack spacing={1}>
        <Box
          px={4}
          py={2}
          bg="green.900"
          border="1px solid"
          borderColor="green.500"
          rounded="lg"
        >
          <Text fontSize="sm" fontWeight="medium" color="green.200">
            CanonicalClaim / CanonicalRelation
          </Text>
        </Box>
        <Text fontSize="xs" color="text.muted">Knowledge Graph</Text>
      </VStack>
    </HStack>
  </Box>
)

export default function ConsolidationPage() {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [lastResult, setLastResult] = useState<ConsolidationResult | null>(null)

  // Fetch consolidation stats
  const {
    data: statsResponse,
    isLoading: statsLoading,
    error: statsError,
    refetch: refetchStats,
  } = useQuery({
    queryKey: ['consolidation', 'stats'],
    queryFn: async () => {
      // Fetch counts from Neo4j via API
      const [claimsRes, conflictsRes, claimTypesRes] = await Promise.all([
        apiClient.post('/claims/search', { limit: 1 }),
        apiClient.get('/claims/conflicts'),
        apiClient.get('/claims/claim-types'),
      ])

      // Build stats object
      const stats: ConsolidationStats = {
        raw_claims: 0,  // Would need separate endpoint
        canonical_claims: claimsRes.data?.total || 0,
        raw_assertions: 0,  // Would need separate endpoint
        canonical_relations: 0,  // Would need separate endpoint
        validated_claims: 0,
        candidate_claims: 0,
        conflicting_claims: conflictsRes.data?.total_conflicts || 0,
        validated_relations: 0,
        candidate_relations: 0,
      }

      return { stats, conflicts: conflictsRes.data?.conflicts || [], claimTypes: claimTypesRes.data || [] }
    },
    refetchInterval: 30000,
  })

  // Consolidation mutation
  const consolidateMutation = useMutation({
    mutationFn: async () => {
      const response = await apiClient.post<ConsolidationResult>('/claims/consolidate', {
        force: false,
      })
      if (!response.success) {
        throw new Error(response.error || 'Consolidation failed')
      }
      return response.data
    },
    onSuccess: (data) => {
      setLastResult(data!)
      queryClient.invalidateQueries({ queryKey: ['consolidation'] })
      toast({
        title: 'Consolidation terminee',
        description: `${data!.claims_consolidated} claims, ${data!.relations_consolidated} relations consolidees`,
        status: 'success',
        duration: 5000,
        isClosable: true,
      })
    },
    onError: (error: any) => {
      toast({
        title: 'Erreur de consolidation',
        description: error.message,
        status: 'error',
        duration: 5000,
        isClosable: true,
      })
    },
  })

  const stats = statsResponse?.stats
  const conflicts = statsResponse?.conflicts || []
  const claimTypes = statsResponse?.claimTypes || []

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

  return (
    <Box maxW="1400px" mx="auto">
      {/* Header */}
      <MotionBox
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
        mb={8}
      >
        <HStack spacing={3} justify="space-between" flexWrap="wrap">
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
                Consolidation Knowledge Graph
              </Text>
              <Text color="text.secondary">
                Agregation des assertions brutes en connaissances canoniques
              </Text>
            </VStack>
          </HStack>

          <Button
            leftIcon={<FiRefreshCw />}
            colorScheme="brand"
            size="lg"
            onClick={() => consolidateMutation.mutate()}
            isLoading={consolidateMutation.isPending}
            loadingText="Consolidation..."
            _hover={{
              transform: 'translateY(-2px)',
              boxShadow: '0 0 20px rgba(99, 102, 241, 0.4)',
            }}
          >
            Lancer la consolidation
          </Button>
        </HStack>
      </MotionBox>

      {/* Last Result Alert */}
      {lastResult && (
        <MotionBox
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          mb={6}
        >
          <Alert
            status="success"
            variant="subtle"
            rounded="xl"
            bg="green.900"
            borderColor="green.600"
            border="1px solid"
          >
            <AlertIcon color="green.400" />
            <Box flex="1">
              <AlertTitle color="green.200">Consolidation reussie</AlertTitle>
              <AlertDescription color="green.300">
                {lastResult.claims_consolidated} claims et {lastResult.relations_consolidated} relations
                consolides en {(lastResult.execution_time_ms / 1000).toFixed(2)}s.
                {lastResult.conflicts_detected > 0 && (
                  <Text as="span" color="orange.300">
                    {' '}{lastResult.conflicts_detected} conflits detectes.
                  </Text>
                )}
              </AlertDescription>
            </Box>
          </Alert>
        </MotionBox>
      )}

      {/* Flow Diagram */}
      <MotionBox
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, delay: 0.1 }}
        mb={6}
      >
        <ConsolidationFlowDiagram />
      </MotionBox>

      {/* Statistics Cards */}
      <SimpleGrid columns={{ base: 1, md: 2, xl: 4 }} spacing={4} mb={6}>
        <StatCard
          title="Claims Canoniques"
          value={stats?.canonical_claims || 0}
          subtitle="Assertions unaires consolidees"
          icon={FiTarget}
          delay={0.2}
        />
        <StatCard
          title="Claims Valides"
          value={stats?.validated_claims || '-'}
          subtitle="Multi-source confirmes"
          icon={FiCheckCircle}
          color="green"
          delay={0.3}
        />
        <StatCard
          title="Conflits"
          value={stats?.conflicting_claims || 0}
          subtitle="Valeurs contradictoires"
          icon={FiAlertTriangle}
          color="red"
          delay={0.4}
        />
        <StatCard
          title="Types de Claims"
          value={claimTypes.length}
          subtitle="Categories detectees"
          icon={FiLayers}
          color="purple"
          delay={0.5}
        />
      </SimpleGrid>

      <Grid templateColumns={{ base: '1fr', lg: '2fr 1fr' }} gap={6}>
        {/* Conflicts Table */}
        <SectionCard
          title="Conflits detectes"
          icon={FiAlertTriangle}
          delay={0.6}
          action={
            <Badge colorScheme="red" fontSize="sm">
              {conflicts.length} conflits
            </Badge>
          }
        >
          {conflicts.length === 0 ? (
            <Center py={8}>
              <VStack spacing={2}>
                <Icon as={FiCheckCircle} boxSize={10} color="green.400" />
                <Text color="text.muted">Aucun conflit detecte</Text>
                <Text fontSize="sm" color="text.muted">
                  Toutes les valeurs sont coherentes
                </Text>
              </VStack>
            </Center>
          ) : (
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
                  {conflicts.slice(0, 10).map((conflict: ConflictInfo, idx: number) => (
                    <Tr key={idx}>
                      <Td>
                        <Text color="text.primary" fontWeight="medium">
                          {conflict.subject_name || conflict.subject_concept_id}
                        </Text>
                      </Td>
                      <Td>
                        <Badge colorScheme="purple">{conflict.claim_type}</Badge>
                      </Td>
                      <Td>
                        <HStack spacing={2} flexWrap="wrap">
                          {conflict.conflicting_values.map((val, i) => (
                            <Badge key={i} colorScheme="red" variant="subtle">
                              {val}
                            </Badge>
                          ))}
                        </HStack>
                      </Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>
              {conflicts.length > 10 && (
                <Text fontSize="sm" color="text.muted" mt={3} textAlign="center">
                  ... et {conflicts.length - 10} autres conflits
                </Text>
              )}
            </TableContainer>
          )}
        </SectionCard>

        {/* Claim Types & Info */}
        <VStack spacing={6} align="stretch">
          {/* Claim Types */}
          <SectionCard title="Types de Claims" icon={FiLayers} delay={0.7}>
            {claimTypes.length === 0 ? (
              <Text color="text.muted" fontSize="sm">
                Aucun type de claim trouve
              </Text>
            ) : (
              <VStack align="stretch" spacing={2}>
                {claimTypes.slice(0, 10).map((type: string, idx: number) => (
                  <HStack
                    key={idx}
                    p={2}
                    bg="bg.tertiary"
                    rounded="lg"
                    justify="space-between"
                  >
                    <Text fontSize="sm" color="text.primary">
                      {type}
                    </Text>
                    <Icon as={FiTarget} color="brand.400" boxSize={4} />
                  </HStack>
                ))}
                {claimTypes.length > 10 && (
                  <Text fontSize="xs" color="text.muted" textAlign="center">
                    +{claimTypes.length - 10} autres types
                  </Text>
                )}
              </VStack>
            )}
          </SectionCard>

          {/* KG/RAG Contract Info */}
          <SectionCard title="KG/RAG Contract" icon={FiZap} delay={0.8}>
            <VStack align="stretch" spacing={3}>
              <Box p={3} bg="green.900" rounded="lg" borderLeft="3px solid" borderColor="green.400">
                <Text fontSize="sm" fontWeight="medium" color="green.200">
                  VALIDATED = KG Facts
                </Text>
                <Text fontSize="xs" color="green.300">
                  Le LLM peut affirmer directement ces faits
                </Text>
              </Box>

              <Box p={3} bg="yellow.900" rounded="lg" borderLeft="3px solid" borderColor="yellow.400">
                <Text fontSize="sm" fontWeight="medium" color="yellow.200">
                  CANDIDATE = RAG Suggestions
                </Text>
                <Text fontSize="xs" color="yellow.300">
                  Le LLM doit utiliser du hedging ("selon certaines sources...")
                </Text>
              </Box>

              <Box p={3} bg="red.900" rounded="lg" borderLeft="3px solid" borderColor="red.400">
                <Text fontSize="sm" fontWeight="medium" color="red.200">
                  CONFLICTING = Conflits
                </Text>
                <Text fontSize="xs" color="red.300">
                  Le LLM doit mentionner le desaccord entre sources
                </Text>
              </Box>
            </VStack>
          </SectionCard>
        </VStack>
      </Grid>

      {/* Help Section */}
      <MotionBox
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, delay: 0.9 }}
        mt={6}
      >
        <Box
          bg="bg.secondary"
          border="1px solid"
          borderColor="border.default"
          rounded="xl"
          p={5}
        >
          <HStack spacing={3} mb={4}>
            <Icon as={FiFileText} color="brand.400" />
            <Text fontWeight="semibold" color="text.primary">
              Qu'est-ce que la consolidation ?
            </Text>
          </HStack>
          <SimpleGrid columns={{ base: 1, md: 3 }} spacing={4}>
            <VStack align="start" spacing={2}>
              <Text fontSize="sm" fontWeight="medium" color="brand.300">
                1. Groupement
              </Text>
              <Text fontSize="sm" color="text.muted">
                Les assertions brutes extraites de differents documents sont groupees
                par cle unique (sujet, type, scope).
              </Text>
            </VStack>
            <VStack align="start" spacing={2}>
              <Text fontSize="sm" fontWeight="medium" color="brand.300">
                2. Calcul de maturite
              </Text>
              <Text fontSize="sm" color="text.muted">
                Chaque groupe est evalue : VALIDATED si multi-source coherent,
                CONFLICTING si valeurs contradictoires, CANDIDATE sinon.
              </Text>
            </VStack>
            <VStack align="start" spacing={2}>
              <Text fontSize="sm" fontWeight="medium" color="brand.300">
                3. Knowledge Graph
              </Text>
              <Text fontSize="sm" color="text.muted">
                Les connaissances canoniques sont stockees dans Neo4j avec
                leurs sources, permettant le KG/RAG Contract.
              </Text>
            </VStack>
          </SimpleGrid>
        </Box>
      </MotionBox>
    </Box>
  )
}
