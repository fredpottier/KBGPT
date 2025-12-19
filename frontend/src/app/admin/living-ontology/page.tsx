'use client'

import {
  Box,
  Button,
  Card,
  CardBody,
  CardHeader,
  Center,
  Flex,
  Grid,
  HStack,
  Icon,
  IconButton,
  Progress,
  Spinner,
  Stat,
  StatLabel,
  StatNumber,
  StatHelpText,
  Table,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tr,
  VStack,
  Badge,
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
} from '@chakra-ui/react'
import {
  CheckIcon,
  CloseIcon,
  RepeatIcon,
  InfoIcon,
  WarningIcon,
  StarIcon,
} from '@chakra-ui/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, useRef } from 'react'
import { api } from '@/lib/api'

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

const StatCard = ({
  title,
  value,
  subtitle,
  icon,
  color = 'blue',
}: {
  title: string
  value: string | number
  subtitle?: string
  icon: any
  color?: string
}) => (
  <Card>
    <CardBody>
      <HStack spacing={4}>
        <Box p={3} borderRadius="md" bg={`${color}.100`} color={`${color}.600`}>
          <Icon as={icon} boxSize={6} />
        </Box>
        <Stat>
          <StatLabel>{title}</StatLabel>
          <StatNumber>{value}</StatNumber>
          {subtitle && <StatHelpText>{subtitle}</StatHelpText>}
        </Stat>
      </HStack>
    </CardBody>
  </Card>
)

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
        })
        queryClient.invalidateQueries({ queryKey: ['living-ontology'] })
      } else {
        toast({
          title: 'Erreur',
          description: response.error || 'Echec du cycle de decouverte',
          status: 'error',
          duration: 5000,
        })
      }
    },
  })

  // Approve mutation
  const approveMutation = useMutation({
    mutationFn: (id: string) => api.livingOntology.approveProposal(id),
    onSuccess: (response) => {
      if (response.success) {
        toast({
          title: 'Proposition approuvee',
          status: 'success',
          duration: 3000,
        })
        queryClient.invalidateQueries({ queryKey: ['living-ontology'] })
      } else {
        toast({
          title: 'Erreur',
          description: response.error,
          status: 'error',
          duration: 5000,
        })
      }
      onClose()
    },
  })

  // Reject mutation
  const rejectMutation = useMutation({
    mutationFn: (id: string) => api.livingOntology.rejectProposal(id),
    onSuccess: (response) => {
      if (response.success) {
        toast({
          title: 'Proposition rejetee',
          status: 'info',
          duration: 3000,
        })
        queryClient.invalidateQueries({ queryKey: ['living-ontology'] })
      } else {
        toast({
          title: 'Erreur',
          description: response.error,
          status: 'error',
          duration: 5000,
        })
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
        <Spinner size="xl" color="teal.500" />
      </Center>
    )
  }

  if (statsError || !statsResponse?.success) {
    return (
      <Card>
        <CardBody>
          <Center py={12}>
            <VStack spacing={4}>
              <Icon as={WarningIcon} boxSize={12} color="red.500" />
              <Text fontSize="lg" color="red.500">
                Impossible de charger les statistiques Living Ontology
              </Text>
              <Text fontSize="sm" color="gray.500">
                Verifiez que le service est demarre
              </Text>
            </VStack>
          </Center>
        </CardBody>
      </Card>
    )
  }

  const stats: OntologyStats = statsResponse.data as OntologyStats
  // API retourne {proposals: [], types: [], changes: []} - extraire les tableaux
  const proposalsData = proposalsResponse?.data as { proposals?: TypeProposal[] } | undefined
  const proposals: TypeProposal[] = proposalsData?.proposals || []
  const historyData = historyResponse?.data as { changes?: OntologyChange[] } | undefined
  const history: OntologyChange[] = historyData?.changes || []
  const typesData = typesResponse?.data as { types?: Array<{ type_name: string; count: number }> } | undefined
  const types: Array<{ type_name: string; count: number }> = typesData?.types || []

  const getConfidenceColor = (confidence: number) => {
    if (confidence >= 0.85) return 'green'
    if (confidence >= 0.7) return 'blue'
    if (confidence >= 0.5) return 'yellow'
    return 'red'
  }

  return (
    <VStack spacing={6} align="stretch">
      {/* Header */}
      <Flex justify="space-between" align="center">
        <Box>
          <Text fontSize="2xl" fontWeight="bold">
            Living Ontology
          </Text>
          <Text color="gray.600" mt={1}>
            Gestion dynamique des types - OSMOSE Phase 2.3
          </Text>
        </Box>
        <HStack spacing={3}>
          <Button
            leftIcon={<RepeatIcon />}
            colorScheme="teal"
            onClick={() => discoverMutation.mutate(false)}
            isLoading={discoverMutation.isPending}
          >
            Lancer Decouverte
          </Button>
          <Tooltip label="Decouverte avec auto-promotion des types a haute confidence (>85%)">
            <Button
              leftIcon={<StarIcon />}
              colorScheme="purple"
              variant="outline"
              onClick={() => discoverMutation.mutate(true)}
              isLoading={discoverMutation.isPending}
            >
              Decouverte + Auto-Promote
            </Button>
          </Tooltip>
        </HStack>
      </Flex>

      {/* Statistics Cards */}
      <Grid templateColumns="repeat(auto-fit, minmax(200px, 1fr))" gap={4}>
        <StatCard
          title="Concepts"
          value={stats.total_concepts}
          subtitle="dans le Knowledge Graph"
          icon={InfoIcon}
          color="blue"
        />
        <StatCard
          title="Types"
          value={stats.unique_types}
          subtitle="types uniques"
          icon={StarIcon}
          color="green"
        />
        <StatCard
          title="Propositions"
          value={stats.pending_proposals}
          subtitle="en attente de review"
          icon={WarningIcon}
          color={stats.pending_proposals > 0 ? 'orange' : 'gray'}
        />
        <StatCard
          title="Changements"
          value={stats.total_changes}
          subtitle="dans l'historique"
          icon={RepeatIcon}
          color="purple"
        />
      </Grid>

      {/* Tabs */}
      <Tabs colorScheme="teal" variant="enclosed">
        <TabList>
          <Tab>
            Propositions
            {proposals.length > 0 && (
              <Badge ml={2} colorScheme="orange">
                {proposals.length}
              </Badge>
            )}
          </Tab>
          <Tab>Types Existants ({types.length})</Tab>
          <Tab>Historique</Tab>
          <Tab>Distribution</Tab>
        </TabList>

        <TabPanels>
          {/* Proposals Tab */}
          <TabPanel p={0} pt={4}>
            <Card>
              <CardBody>
                {proposalsLoading ? (
                  <Center py={8}>
                    <Spinner />
                  </Center>
                ) : proposals.length === 0 ? (
                  <Center py={8}>
                    <VStack spacing={2}>
                      <Icon as={CheckIcon} boxSize={8} color="green.500" />
                      <Text color="gray.500">Aucune proposition en attente</Text>
                    </VStack>
                  </Center>
                ) : (
                  <Table variant="simple" size="sm">
                    <Thead>
                      <Tr>
                        <Th>Type propose</Th>
                        <Th isNumeric>Confidence</Th>
                        <Th isNumeric>Occurrences</Th>
                        <Th>Concepts (apercu)</Th>
                        <Th>Actions</Th>
                      </Tr>
                    </Thead>
                    <Tbody>
                      {proposals.map((proposal) => (
                        <Tr key={proposal.id}>
                          <Td>
                            <Text fontWeight="medium">{proposal.type_name}</Text>
                          </Td>
                          <Td isNumeric>
                            <Badge colorScheme={getConfidenceColor(proposal.confidence)}>
                              {(proposal.confidence * 100).toFixed(0)}%
                            </Badge>
                          </Td>
                          <Td isNumeric>{proposal.occurrences}</Td>
                          <Td>
                            <Tooltip
                              label={proposal.support_concepts?.slice(0, 10).join(', ')}
                              hasArrow
                            >
                              <Text fontSize="sm" color="gray.600" noOfLines={1} maxW="200px">
                                {proposal.support_concepts?.slice(0, 3).join(', ')}
                                {(proposal.support_concepts?.length || 0) > 3 && '...'}
                              </Text>
                            </Tooltip>
                          </Td>
                          <Td>
                            <HStack spacing={2}>
                              <IconButton
                                aria-label="Approve"
                                icon={<CheckIcon />}
                                colorScheme="green"
                                size="sm"
                                onClick={() => handleAction(proposal, 'approve')}
                              />
                              <IconButton
                                aria-label="Reject"
                                icon={<CloseIcon />}
                                colorScheme="red"
                                size="sm"
                                variant="outline"
                                onClick={() => handleAction(proposal, 'reject')}
                              />
                            </HStack>
                          </Td>
                        </Tr>
                      ))}
                    </Tbody>
                  </Table>
                )}
              </CardBody>
            </Card>
          </TabPanel>

          {/* Types Tab */}
          <TabPanel p={0} pt={4}>
            <Card>
              <CardBody>
                {typesLoading ? (
                  <Center py={8}>
                    <Spinner />
                  </Center>
                ) : (
                  <Flex flexWrap="wrap" gap={2}>
                    {types.map((typeInfo) => (
                      <Badge
                        key={typeInfo.type_name}
                        colorScheme="teal"
                        variant="subtle"
                        px={3}
                        py={1}
                        borderRadius="full"
                      >
                        {typeInfo.type_name}
                        <Text as="span" ml={1} opacity={0.7}>
                          ({typeInfo.count})
                        </Text>
                      </Badge>
                    ))}
                  </Flex>
                )}
              </CardBody>
            </Card>
          </TabPanel>

          {/* History Tab */}
          <TabPanel p={0} pt={4}>
            <Card>
              <CardBody>
                {historyLoading ? (
                  <Center py={8}>
                    <Spinner />
                  </Center>
                ) : history.length === 0 ? (
                  <Center py={8}>
                    <Text color="gray.500">Aucun changement enregistre</Text>
                  </Center>
                ) : (
                  <Table variant="simple" size="sm">
                    <Thead>
                      <Tr>
                        <Th>Date</Th>
                        <Th>Action</Th>
                        <Th>Type</Th>
                        <Th>Details</Th>
                      </Tr>
                    </Thead>
                    <Tbody>
                      {history.slice(0, 20).map((change) => (
                        <Tr key={change.id}>
                          <Td>
                            <Text fontSize="sm">
                              {new Date(change.timestamp).toLocaleDateString('fr-FR', {
                                day: '2-digit',
                                month: '2-digit',
                                hour: '2-digit',
                                minute: '2-digit',
                              })}
                            </Text>
                          </Td>
                          <Td>
                            <Badge
                              colorScheme={
                                change.change_type === 'TYPE_CREATED'
                                  ? 'green'
                                  : change.change_type === 'TYPE_REJECTED'
                                  ? 'red'
                                  : 'blue'
                              }
                            >
                              {change.change_type}
                            </Badge>
                          </Td>
                          <Td>
                            <Text fontWeight="medium">{change.type_name}</Text>
                          </Td>
                          <Td>
                            <Text fontSize="sm" color="gray.600" noOfLines={1}>
                              {JSON.stringify(change.details).slice(0, 50)}...
                            </Text>
                          </Td>
                        </Tr>
                      ))}
                    </Tbody>
                  </Table>
                )}
              </CardBody>
            </Card>
          </TabPanel>

          {/* Distribution Tab */}
          <TabPanel p={0} pt={4}>
            <Card>
              <CardBody>
                <VStack spacing={3} align="stretch">
                  {Object.entries(stats.type_distribution || {})
                    .sort(([, a], [, b]) => b - a)
                    .map(([type, count]) => {
                      const percentage = (count / stats.total_concepts) * 100
                      return (
                        <Box key={type}>
                          <HStack justify="space-between" mb={1}>
                            <Text fontSize="sm" fontWeight="medium">
                              {type}
                            </Text>
                            <Text fontSize="sm" color="gray.600">
                              {count} ({percentage.toFixed(1)}%)
                            </Text>
                          </HStack>
                          <Progress
                            value={percentage}
                            size="sm"
                            colorScheme="teal"
                            borderRadius="full"
                          />
                        </Box>
                      )
                    })}
                </VStack>
              </CardBody>
            </Card>
          </TabPanel>
        </TabPanels>
      </Tabs>

      {/* Confirmation Dialog */}
      <AlertDialog isOpen={isOpen} leastDestructiveRef={cancelRef} onClose={onClose}>
        <AlertDialogOverlay>
          <AlertDialogContent>
            <AlertDialogHeader fontSize="lg" fontWeight="bold">
              {actionType === 'approve' ? 'Approuver la proposition' : 'Rejeter la proposition'}
            </AlertDialogHeader>

            <AlertDialogBody>
              {actionType === 'approve' ? (
                <>
                  Voulez-vous creer le type <strong>{selectedProposal?.type_name}</strong> ?
                  <Text mt={2} fontSize="sm" color="gray.600">
                    {selectedProposal?.occurrences} concepts seront reclassifies.
                  </Text>
                </>
              ) : (
                <>
                  Voulez-vous rejeter la proposition <strong>{selectedProposal?.type_name}</strong> ?
                  <Text mt={2} fontSize="sm" color="gray.600">
                    Cette action peut etre annulee lors du prochain cycle de decouverte.
                  </Text>
                </>
              )}
            </AlertDialogBody>

            <AlertDialogFooter>
              <Button ref={cancelRef} onClick={onClose}>
                Annuler
              </Button>
              <Button
                colorScheme={actionType === 'approve' ? 'green' : 'red'}
                onClick={confirmAction}
                ml={3}
                isLoading={approveMutation.isPending || rejectMutation.isPending}
              >
                {actionType === 'approve' ? 'Approuver' : 'Rejeter'}
              </Button>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialogOverlay>
      </AlertDialog>
    </VStack>
  )
}
