'use client'

/**
 * OSMOS Living Ontology - Dark Elegance Edition
 *
 * Dynamic type management with OSMOS intelligence
 */

import {
  Box,
  Button,
  Center,
  Flex,
  Grid,
  HStack,
  Icon,
  IconButton,
  Spinner,
  Table,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tr,
  VStack,
  useToast,
  AlertDialog,
  AlertDialogBody,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogContent,
  AlertDialogOverlay,
  useDisclosure,
  Tooltip,
  Tabs,
  TabList,
  TabPanels,
  Tab,
  TabPanel,
  SimpleGrid,
} from '@chakra-ui/react'
import { motion } from 'framer-motion'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, useRef } from 'react'
import { api } from '@/lib/api'
import {
  FiShare2,
  FiRefreshCw,
  FiStar,
  FiAlertTriangle,
  FiCheck,
  FiX,
  FiInfo,
  FiCpu,
  FiLayers,
  FiActivity,
  FiZap,
  FiCheckCircle,
} from 'react-icons/fi'

const MotionBox = motion(Box)

interface OntologyStats {
  total_concepts: number
  unique_types: number
  pending_proposals: number
  total_changes: number
  auto_promote_threshold: number
  type_distribution: Record<string, number>
}

interface TypeProposal {
  id: string
  type_name: string
  confidence: number
  occurrences: number
  support_concepts: string[]
  created_at: string
  status: string
}

interface OntologyChange {
  id: string
  change_type: string
  type_name: string
  timestamp: string
  details: Record<string, any>
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

// Confidence Badge
const ConfidenceBadge = ({ confidence }: { confidence: number }) => {
  const getConfig = () => {
    if (confidence >= 0.85) return { color: 'green', bg: 'rgba(34, 197, 94, 0.15)' }
    if (confidence >= 0.7) return { color: 'blue', bg: 'rgba(59, 130, 246, 0.15)' }
    if (confidence >= 0.5) return { color: 'yellow', bg: 'rgba(234, 179, 8, 0.15)' }
    return { color: 'red', bg: 'rgba(239, 68, 68, 0.15)' }
  }

  const config = getConfig()

  return (
    <Box
      px={2.5}
      py={1}
      bg={config.bg}
      rounded="full"
      display="inline-flex"
    >
      <Text fontSize="xs" fontWeight="medium" color={`${config.color}.400`}>
        {(confidence * 100).toFixed(0)}%
      </Text>
    </Box>
  )
}

// Change Type Badge
const ChangeTypeBadge = ({ changeType }: { changeType: string }) => {
  const getConfig = () => {
    if (changeType === 'TYPE_CREATED') return { color: 'green', bg: 'rgba(34, 197, 94, 0.15)' }
    if (changeType === 'TYPE_REJECTED') return { color: 'red', bg: 'rgba(239, 68, 68, 0.15)' }
    return { color: 'blue', bg: 'rgba(59, 130, 246, 0.15)' }
  }

  const config = getConfig()

  return (
    <Box
      px={2.5}
      py={1}
      bg={config.bg}
      rounded="full"
      display="inline-flex"
    >
      <Text fontSize="xs" fontWeight="medium" color={`${config.color}.400`}>
        {changeType}
      </Text>
    </Box>
  )
}

export default function LivingOntologyPage() {
  const toast = useToast()
  const queryClient = useQueryClient()
  const { isOpen, onOpen, onClose } = useDisclosure()
  const cancelRef = useRef<HTMLButtonElement>(null)
  const [selectedProposal, setSelectedProposal] = useState<TypeProposal | null>(null)
  const [actionType, setActionType] = useState<'approve' | 'reject'>('approve')

  // Fetch stats
  const {
    data: statsResponse,
    isLoading: statsLoading,
    error: statsError,
  } = useQuery({
    queryKey: ['living-ontology', 'stats'],
    queryFn: () => api.livingOntology.stats(),
    refetchInterval: 30000,
  })

  // Fetch proposals
  const {
    data: proposalsResponse,
    isLoading: proposalsLoading,
  } = useQuery({
    queryKey: ['living-ontology', 'proposals'],
    queryFn: () => api.livingOntology.proposals(),
  })

  // Fetch history
  const {
    data: historyResponse,
    isLoading: historyLoading,
  } = useQuery({
    queryKey: ['living-ontology', 'history'],
    queryFn: () => api.livingOntology.history(),
  })

  // Fetch types
  const {
    data: typesResponse,
    isLoading: typesLoading,
  } = useQuery({
    queryKey: ['living-ontology', 'types'],
    queryFn: () => api.livingOntology.types(),
  })

  // Discovery mutation
  const discoverMutation = useMutation({
    mutationFn: (autoPromote: boolean) => api.livingOntology.discover(autoPromote),
    onSuccess: (response) => {
      if (response.success) {
        toast({
          title: 'Cycle de decouverte termine',
          description: `${response.data?.patterns_discovered || 0} patterns decouverts`,
          status: 'success',
          duration: 5000,
          position: 'top',
        })
        queryClient.invalidateQueries({ queryKey: ['living-ontology'] })
      } else {
        toast({ title: 'Erreur', description: response.error, status: 'error', duration: 5000, position: 'top' })
      }
    },
  })

  // Approve mutation
  const approveMutation = useMutation({
    mutationFn: (id: string) => api.livingOntology.approveProposal(id),
    onSuccess: (response) => {
      if (response.success) {
        toast({ title: 'Proposition approuvee', status: 'success', duration: 3000, position: 'top' })
        queryClient.invalidateQueries({ queryKey: ['living-ontology'] })
      } else {
        toast({ title: 'Erreur', description: response.error, status: 'error', duration: 5000, position: 'top' })
      }
      onClose()
    },
  })

  // Reject mutation
  const rejectMutation = useMutation({
    mutationFn: (id: string) => api.livingOntology.rejectProposal(id),
    onSuccess: (response) => {
      if (response.success) {
        toast({ title: 'Proposition rejetee', status: 'info', duration: 3000, position: 'top' })
        queryClient.invalidateQueries({ queryKey: ['living-ontology'] })
      } else {
        toast({ title: 'Erreur', description: response.error, status: 'error', duration: 5000, position: 'top' })
      }
      onClose()
    },
  })

  const handleAction = (proposal: TypeProposal, action: 'approve' | 'reject') => {
    setSelectedProposal(proposal)
    setActionType(action)
    onOpen()
  }

  const confirmAction = () => {
    if (!selectedProposal) return
    if (actionType === 'approve') {
      approveMutation.mutate(selectedProposal.id)
    } else {
      rejectMutation.mutate(selectedProposal.id)
    }
  }

  if (statsLoading) {
    return (
      <Center h="400px">
        <VStack spacing={4}>
          <Spinner size="xl" color="brand.500" thickness="3px" />
          <Text color="text.muted">Chargement de Living Ontology...</Text>
        </VStack>
      </Center>
    )
  }

  if (statsError || !statsResponse?.success) {
    return (
      <Center h="400px">
        <Box
          bg="rgba(239, 68, 68, 0.1)"
          border="1px solid"
          borderColor="red.500"
          rounded="xl"
          p={8}
          textAlign="center"
        >
          <Icon as={FiAlertTriangle} boxSize={12} color="red.400" mb={4} />
          <Text fontSize="lg" fontWeight="medium" color="red.400" mb={2}>
            Erreur de chargement
          </Text>
          <Text fontSize="sm" color="text.muted">
            Verifiez que le service Living Ontology est demarre
          </Text>
        </Box>
      </Center>
    )
  }

  const stats: OntologyStats = statsResponse.data as OntologyStats
  const proposalsData = proposalsResponse?.data as { proposals?: TypeProposal[] } | undefined
  const proposals: TypeProposal[] = proposalsData?.proposals || []
  const historyData = historyResponse?.data as { changes?: OntologyChange[] } | undefined
  const history: OntologyChange[] = historyData?.changes || []
  const typesData = typesResponse?.data as { types?: Array<{ type_name: string; count: number }> } | undefined
  const types: Array<{ type_name: string; count: number }> = typesData?.types || []

  return (
    <Box maxW="1400px" mx="auto">
      {/* Header */}
      <MotionBox
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
        mb={8}
      >
        <Flex justify="space-between" align="start" flexWrap="wrap" gap={4}>
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
              <Icon as={FiShare2} boxSize={5} color="white" />
            </Box>
            <VStack align="start" spacing={0}>
              <Text fontSize="2xl" fontWeight="bold" color="text.primary">
                Living Ontology
              </Text>
              <Text color="text.secondary">
                Gestion dynamique des types - OSMOS Phase 2.3
              </Text>
            </VStack>
          </HStack>

          <HStack spacing={3}>
            <Button
              leftIcon={<Icon as={FiRefreshCw} />}
              bg="brand.500"
              color="white"
              onClick={() => discoverMutation.mutate(false)}
              isLoading={discoverMutation.isPending}
              _hover={{ bg: 'brand.600', transform: 'translateY(-2px)', boxShadow: '0 0 20px rgba(99, 102, 241, 0.4)' }}
              transition="all 0.2s"
            >
              Lancer Decouverte
            </Button>
            <Tooltip label="Decouverte avec auto-promotion des types a haute confidence (>85%)">
              <Button
                leftIcon={<Icon as={FiZap} />}
                variant="outline"
                borderColor="accent.400"
                color="accent.400"
                onClick={() => discoverMutation.mutate(true)}
                isLoading={discoverMutation.isPending}
                _hover={{ bg: 'rgba(34, 211, 238, 0.1)' }}
              >
                Decouverte + Auto-Promote
              </Button>
            </Tooltip>
          </HStack>
        </Flex>
      </MotionBox>

      {/* Statistics Cards */}
      <SimpleGrid columns={{ base: 1, md: 2, xl: 4 }} spacing={4} mb={8}>
        <StatCard title="Concepts" value={stats.total_concepts} subtitle="dans le Knowledge Graph" icon={FiCpu} delay={0} />
        <StatCard title="Types" value={stats.unique_types} subtitle="types uniques" icon={FiLayers} color="green" delay={0.1} />
        <StatCard title="Propositions" value={stats.pending_proposals} subtitle="en attente de review" icon={FiInfo} color={stats.pending_proposals > 0 ? 'orange' : 'gray'} delay={0.2} />
        <StatCard title="Changements" value={stats.total_changes} subtitle="dans l'historique" icon={FiActivity} color="purple" delay={0.3} />
      </SimpleGrid>

      {/* Tabs */}
      <MotionBox
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, delay: 0.2 }}
      >
        <Tabs variant="unstyled">
          <TabList
            bg="bg.secondary"
            border="1px solid"
            borderColor="border.default"
            rounded="xl"
            p={1}
            mb={4}
          >
            <Tab
              rounded="lg"
              color="text.muted"
              _selected={{ bg: 'brand.500', color: 'white' }}
              _hover={{ color: 'text.primary' }}
              fontWeight="medium"
              fontSize="sm"
            >
              Propositions
              {proposals.length > 0 && (
                <Box
                  ml={2}
                  px={2}
                  py={0.5}
                  bg="rgba(249, 115, 22, 0.2)"
                  color="orange.400"
                  rounded="full"
                  fontSize="xs"
                >
                  {proposals.length}
                </Box>
              )}
            </Tab>
            <Tab
              rounded="lg"
              color="text.muted"
              _selected={{ bg: 'brand.500', color: 'white' }}
              _hover={{ color: 'text.primary' }}
              fontWeight="medium"
              fontSize="sm"
            >
              Types ({types.length})
            </Tab>
            <Tab
              rounded="lg"
              color="text.muted"
              _selected={{ bg: 'brand.500', color: 'white' }}
              _hover={{ color: 'text.primary' }}
              fontWeight="medium"
              fontSize="sm"
            >
              Historique
            </Tab>
            <Tab
              rounded="lg"
              color="text.muted"
              _selected={{ bg: 'brand.500', color: 'white' }}
              _hover={{ color: 'text.primary' }}
              fontWeight="medium"
              fontSize="sm"
            >
              Distribution
            </Tab>
          </TabList>

          <TabPanels>
            {/* Proposals Tab */}
            <TabPanel p={0}>
              <Box
                bg="bg.secondary"
                border="1px solid"
                borderColor="border.default"
                rounded="xl"
                overflow="hidden"
              >
                {proposalsLoading ? (
                  <Center py={12}><Spinner color="brand.500" /></Center>
                ) : proposals.length === 0 ? (
                  <Center py={12}>
                    <VStack spacing={3}>
                      <Icon as={FiCheckCircle} boxSize={10} color="green.400" />
                      <Text color="text.muted">Aucune proposition en attente</Text>
                    </VStack>
                  </Center>
                ) : (
                  <Box overflowX="auto">
                    <Table variant="unstyled" size="sm">
                      <Thead>
                        <Tr borderBottom="1px solid" borderColor="border.default">
                          <Th color="text.muted" py={4}>Type propose</Th>
                          <Th color="text.muted" py={4} isNumeric>Confidence</Th>
                          <Th color="text.muted" py={4} isNumeric>Occurrences</Th>
                          <Th color="text.muted" py={4}>Concepts</Th>
                          <Th color="text.muted" py={4}>Actions</Th>
                        </Tr>
                      </Thead>
                      <Tbody>
                        {proposals.map((proposal) => (
                          <Tr key={proposal.id} borderBottom="1px solid" borderColor="border.default" _hover={{ bg: 'bg.hover' }}>
                            <Td py={4}><Text fontWeight="medium" color="text.primary">{proposal.type_name}</Text></Td>
                            <Td py={4} isNumeric><ConfidenceBadge confidence={proposal.confidence} /></Td>
                            <Td py={4} isNumeric><Text color="text.secondary">{proposal.occurrences}</Text></Td>
                            <Td py={4}>
                              <Tooltip label={proposal.support_concepts?.slice(0, 10).join(', ')}>
                                <Text fontSize="sm" color="text.muted" noOfLines={1} maxW="200px">
                                  {proposal.support_concepts?.slice(0, 3).join(', ')}
                                  {(proposal.support_concepts?.length || 0) > 3 && '...'}
                                </Text>
                              </Tooltip>
                            </Td>
                            <Td py={4}>
                              <HStack spacing={2}>
                                <IconButton
                                  aria-label="Approuver"
                                  icon={<Icon as={FiCheck} />}
                                  size="sm"
                                  bg="rgba(34, 197, 94, 0.15)"
                                  color="green.400"
                                  onClick={() => handleAction(proposal, 'approve')}
                                  _hover={{ bg: 'rgba(34, 197, 94, 0.3)' }}
                                />
                                <IconButton
                                  aria-label="Rejeter"
                                  icon={<Icon as={FiX} />}
                                  size="sm"
                                  bg="rgba(239, 68, 68, 0.15)"
                                  color="red.400"
                                  onClick={() => handleAction(proposal, 'reject')}
                                  _hover={{ bg: 'rgba(239, 68, 68, 0.3)' }}
                                />
                              </HStack>
                            </Td>
                          </Tr>
                        ))}
                      </Tbody>
                    </Table>
                  </Box>
                )}
              </Box>
            </TabPanel>

            {/* Types Tab */}
            <TabPanel p={0}>
              <Box
                bg="bg.secondary"
                border="1px solid"
                borderColor="border.default"
                rounded="xl"
                p={5}
              >
                {typesLoading ? (
                  <Center py={8}><Spinner color="brand.500" /></Center>
                ) : (
                  <Flex flexWrap="wrap" gap={2}>
                    {types.map((typeInfo) => (
                      <Box
                        key={typeInfo.type_name}
                        px={3}
                        py={1.5}
                        bg="rgba(34, 211, 238, 0.1)"
                        border="1px solid"
                        borderColor="rgba(34, 211, 238, 0.2)"
                        rounded="full"
                      >
                        <Text fontSize="sm" color="accent.400">
                          {typeInfo.type_name}
                          <Text as="span" ml={1.5} opacity={0.7}>({typeInfo.count})</Text>
                        </Text>
                      </Box>
                    ))}
                  </Flex>
                )}
              </Box>
            </TabPanel>

            {/* History Tab */}
            <TabPanel p={0}>
              <Box
                bg="bg.secondary"
                border="1px solid"
                borderColor="border.default"
                rounded="xl"
                overflow="hidden"
              >
                {historyLoading ? (
                  <Center py={12}><Spinner color="brand.500" /></Center>
                ) : history.length === 0 ? (
                  <Center py={12}><Text color="text.muted">Aucun changement enregistre</Text></Center>
                ) : (
                  <Box overflowX="auto">
                    <Table variant="unstyled" size="sm">
                      <Thead>
                        <Tr borderBottom="1px solid" borderColor="border.default">
                          <Th color="text.muted" py={4}>Date</Th>
                          <Th color="text.muted" py={4}>Action</Th>
                          <Th color="text.muted" py={4}>Type</Th>
                          <Th color="text.muted" py={4}>Details</Th>
                        </Tr>
                      </Thead>
                      <Tbody>
                        {history.slice(0, 20).map((change) => (
                          <Tr key={change.id} borderBottom="1px solid" borderColor="border.default" _hover={{ bg: 'bg.hover' }}>
                            <Td py={4}>
                              <Text fontSize="sm" color="text.secondary">
                                {new Date(change.timestamp).toLocaleDateString('fr-FR', {
                                  day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
                                })}
                              </Text>
                            </Td>
                            <Td py={4}><ChangeTypeBadge changeType={change.change_type} /></Td>
                            <Td py={4}><Text fontWeight="medium" color="text.primary">{change.type_name}</Text></Td>
                            <Td py={4}><Text fontSize="sm" color="text.muted" noOfLines={1}>{JSON.stringify(change.details).slice(0, 50)}...</Text></Td>
                          </Tr>
                        ))}
                      </Tbody>
                    </Table>
                  </Box>
                )}
              </Box>
            </TabPanel>

            {/* Distribution Tab */}
            <TabPanel p={0}>
              <Box
                bg="bg.secondary"
                border="1px solid"
                borderColor="border.default"
                rounded="xl"
                p={5}
              >
                <VStack spacing={4} align="stretch">
                  {Object.entries(stats.type_distribution || {})
                    .sort(([, a], [, b]) => b - a)
                    .map(([type, count]) => {
                      const percentage = (count / stats.total_concepts) * 100
                      return (
                        <Box key={type}>
                          <HStack justify="space-between" mb={2}>
                            <Text fontSize="sm" fontWeight="medium" color="text.primary">{type}</Text>
                            <Text fontSize="sm" color="text.muted">{count} ({percentage.toFixed(1)}%)</Text>
                          </HStack>
                          <Box h="8px" bg="bg.tertiary" rounded="full" overflow="hidden">
                            <Box
                              h="full"
                              w={`${percentage}%`}
                              bg="accent.400"
                              rounded="full"
                              boxShadow="0 0 10px rgba(34, 211, 238, 0.4)"
                            />
                          </Box>
                        </Box>
                      )
                    })}
                </VStack>
              </Box>
            </TabPanel>
          </TabPanels>
        </Tabs>
      </MotionBox>

      {/* Confirmation Dialog */}
      <AlertDialog isOpen={isOpen} leastDestructiveRef={cancelRef} onClose={onClose} isCentered>
        <AlertDialogOverlay bg="rgba(0, 0, 0, 0.7)" backdropFilter="blur(4px)">
          <AlertDialogContent bg="bg.secondary" border="1px solid" borderColor="border.default" rounded="xl">
            <AlertDialogHeader color="text.primary" fontSize="lg" fontWeight="bold">
              {actionType === 'approve' ? 'Approuver la proposition' : 'Rejeter la proposition'}
            </AlertDialogHeader>
            <AlertDialogBody color="text.secondary">
              {actionType === 'approve' ? (
                <>
                  Voulez-vous creer le type <Text as="span" fontWeight="bold" color="brand.400">{selectedProposal?.type_name}</Text> ?
                  <Text mt={2} fontSize="sm" color="text.muted">
                    {selectedProposal?.occurrences} concepts seront reclassifies.
                  </Text>
                </>
              ) : (
                <>
                  Voulez-vous rejeter la proposition <Text as="span" fontWeight="bold" color="red.400">{selectedProposal?.type_name}</Text> ?
                  <Text mt={2} fontSize="sm" color="text.muted">
                    Cette action peut etre annulee lors du prochain cycle de decouverte.
                  </Text>
                </>
              )}
            </AlertDialogBody>
            <AlertDialogFooter gap={3}>
              <Button ref={cancelRef} onClick={onClose} variant="ghost" _hover={{ bg: 'bg.hover' }}>
                Annuler
              </Button>
              <Button
                bg={actionType === 'approve' ? 'green.500' : 'red.500'}
                color="white"
                onClick={confirmAction}
                isLoading={approveMutation.isPending || rejectMutation.isPending}
                _hover={{ bg: actionType === 'approve' ? 'green.600' : 'red.600' }}
              >
                {actionType === 'approve' ? 'Approuver' : 'Rejeter'}
              </Button>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialogOverlay>
      </AlertDialog>
    </Box>
  )
}
