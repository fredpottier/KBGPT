'use client'

/**
 * OSMOSE Markers Administration - ADR_MARKER_NORMALIZATION_LAYER
 * Compact industrial design matching other admin pages
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
  Flex,
  Badge,
  Alert,
  AlertIcon,
  AlertDescription,
  Table,
  Thead,
  Tbody,
  Tr,
  Th,
  Td,
  TableContainer,
  useToast,
  Input,
  IconButton,
  Progress,
  Tooltip,
  Modal,
  ModalOverlay,
  ModalContent,
  ModalHeader,
  ModalBody,
  ModalFooter,
  ModalCloseButton,
  useDisclosure,
  FormControl,
  FormLabel,
} from '@chakra-ui/react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  FiTag,
  FiAlertTriangle,
  FiPlus,
  FiTrash2,
  FiCheck,
  FiX,
  FiLayers,
  FiTarget,
  FiLink,
  FiPercent,
  FiArrowRight,
} from 'react-icons/fi'
import { apiClient } from '@/lib/api'

// Types
interface NormalizationStats {
  total_mentions: number
  resolved: number
  unresolved: number
  blacklisted: number
  pending_review: number
  resolution_rate: number
  unique_canonicals: number
  aliases_count: number
  blacklist_count: number
  rules_count: number
}

interface NormalizationSuggestion {
  mention_id: string
  raw_text: string
  doc_id: string
  suggested_canonical: string | null
  entity_anchor: string | null
  rule_id: string | null
  confidence: number
  reason: string
}

interface AliasInfo {
  raw_marker: string
  canonical_form: string
}

interface ClusterSuggestion {
  cluster_id: string
  raw_markers: string[]
  suggested_canonical: string
  document_count: number
  confidence: number
  reason: string
}

// Compact Metric Card - inline style
const MetricCard = ({
  label,
  value,
  icon,
  color = 'brand',
}: {
  label: string
  value: string | number
  icon: any
  color?: string
}) => (
  <HStack
    spacing={2}
    px={3}
    py={2}
    bg="whiteAlpha.50"
    border="1px solid"
    borderColor="whiteAlpha.100"
    rounded="md"
  >
    <Icon as={icon} boxSize={3.5} color={`${color}.400`} />
    <Text fontSize="sm" fontWeight="bold" color="text.primary">{value}</Text>
    <Text fontSize="xs" color="text.muted">{label}</Text>
  </HStack>
)

// Overview Tab - Compact design
const OverviewTab = ({ stats }: { stats: NormalizationStats | null }) => {
  const resolutionRate = stats ? Math.round(stats.resolution_rate * 100) : 0
  const rateColor = resolutionRate >= 80 ? 'green' : resolutionRate >= 50 ? 'yellow' : 'red'

  return (
    <VStack spacing={3} align="stretch">
      {/* Resolution Progress - compact */}
      <Box bg="whiteAlpha.50" border="1px solid" borderColor="whiteAlpha.100" rounded="lg" p={3}>
        <Flex justify="space-between" align="center" mb={2}>
          <HStack spacing={2}>
            <Icon as={FiPercent} boxSize={3.5} color={`${rateColor}.400`} />
            <Text fontSize="sm" fontWeight="medium" color="text.primary">Taux de résolution</Text>
          </HStack>
          <HStack spacing={3}>
            <Text fontSize="xs" color="text.muted">{stats?.resolved || 0} résolus</Text>
            <Text fontSize="xs" color="text.muted">{stats?.unresolved || 0} non résolus</Text>
            <Badge colorScheme={rateColor} fontSize="xs">{resolutionRate}%</Badge>
          </HStack>
        </Flex>
        <Progress
          value={resolutionRate}
          colorScheme={rateColor}
          rounded="full"
          size="sm"
          bg="whiteAlpha.100"
        />
      </Box>

      {/* Stats - inline metrics */}
      <Flex gap={2} flexWrap="wrap">
        <MetricCard label="mentions" value={stats?.total_mentions || 0} icon={FiTag} color="brand" />
        <MetricCard label="canoniques" value={stats?.unique_canonicals || 0} icon={FiTarget} color="green" />
        <MetricCard label="aliases" value={stats?.aliases_count || 0} icon={FiLink} color="blue" />
        <MetricCard label="blacklist" value={stats?.blacklist_count || 0} icon={FiX} color="red" />
      </Flex>

      {/* Architecture - compact pipeline */}
      <Box bg="whiteAlpha.50" border="1px solid" borderColor="whiteAlpha.100" rounded="lg" p={3}>
        <HStack spacing={2} mb={2}>
          <Icon as={FiLayers} boxSize={3.5} color="brand.400" />
          <Text fontSize="sm" fontWeight="medium" color="text.primary">Pipeline de Normalisation</Text>
        </HStack>
        <Flex gap={2} align="center" flexWrap="wrap">
          <HStack px={2} py={1} bg="yellow.900" rounded="md" borderLeft="2px solid" borderColor="yellow.400">
            <Text fontSize="xs" fontWeight="medium" color="yellow.200">MarkerMention</Text>
            <Text fontSize="10px" color="yellow.400">brut</Text>
          </HStack>
          <Icon as={FiArrowRight} boxSize={3} color="text.muted" />
          <HStack px={2} py={1} bg="brand.900" rounded="md" borderLeft="2px solid" borderColor="brand.400">
            <Text fontSize="xs" fontWeight="medium" color="brand.200">Normalisation</Text>
            <Text fontSize="10px" color="brand.400">rules + anchor</Text>
          </HStack>
          <Icon as={FiArrowRight} boxSize={3} color="text.muted" />
          <HStack px={2} py={1} bg="green.900" rounded="md" borderLeft="2px solid" borderColor="green.400">
            <Text fontSize="xs" fontWeight="medium" color="green.200">CanonicalMarker</Text>
            <Text fontSize="10px" color="green.400">unique</Text>
          </HStack>
        </Flex>
      </Box>
    </VStack>
  )
}

// Suggestions Tab - Compact table
const SuggestionsTab = ({
  suggestions,
  onApply,
  onBlacklist,
  isApplying,
}: {
  suggestions: NormalizationSuggestion[]
  onApply: (mentionId: string, canonical: string, createAlias: boolean) => void
  onBlacklist: (marker: string) => void
  isApplying: boolean
}) => {
  const [selectedCanonical, setSelectedCanonical] = useState<Record<string, string>>({})

  if (suggestions.length === 0) {
    return (
      <Alert status="success" variant="subtle" rounded="lg" bg="green.900" border="1px solid" borderColor="green.700" py={2}>
        <AlertIcon color="green.400" boxSize={4} />
        <AlertDescription fontSize="sm" color="green.200">Tous les markers sont normalisés</AlertDescription>
      </Alert>
    )
  }

  return (
    <Box bg="whiteAlpha.50" border="1px solid" borderColor="whiteAlpha.100" rounded="lg" overflow="hidden">
      <HStack px={3} py={2} bg="whiteAlpha.50" borderBottom="1px solid" borderColor="whiteAlpha.100">
        <Icon as={FiAlertTriangle} boxSize={3.5} color="yellow.400" />
        <Text fontSize="sm" fontWeight="medium" color="text.primary">Markers non résolus</Text>
        <Badge colorScheme="yellow" fontSize="xs">{suggestions.length}</Badge>
      </HStack>
      <TableContainer>
        <Table size="sm">
          <Thead>
            <Tr>
              <Th color="text.muted" fontSize="xs" py={2}>Marker</Th>
              <Th color="text.muted" fontSize="xs" py={2}>Doc</Th>
              <Th color="text.muted" fontSize="xs" py={2}>Canonique</Th>
              <Th color="text.muted" fontSize="xs" py={2} isNumeric>%</Th>
              <Th color="text.muted" fontSize="xs" py={2} w="70px"></Th>
            </Tr>
          </Thead>
          <Tbody>
            {suggestions.slice(0, 20).map((suggestion) => (
              <Tr key={suggestion.mention_id} _hover={{ bg: 'whiteAlpha.50' }}>
                <Td py={1.5}>
                  <Text fontSize="xs" color="text.primary" fontFamily="mono" fontWeight="medium">
                    {suggestion.raw_text}
                  </Text>
                </Td>
                <Td py={1.5}>
                  <Text fontSize="10px" color="text.muted" maxW="100px" isTruncated>
                    {suggestion.doc_id}
                  </Text>
                </Td>
                <Td py={1.5}>
                  <Input
                    size="xs"
                    placeholder={suggestion.suggested_canonical || '...'}
                    value={selectedCanonical[suggestion.mention_id] || suggestion.suggested_canonical || ''}
                    onChange={(e) => setSelectedCanonical({
                      ...selectedCanonical,
                      [suggestion.mention_id]: e.target.value
                    })}
                    bg="whiteAlpha.100"
                    borderColor="whiteAlpha.200"
                    _focus={{ borderColor: 'brand.500' }}
                    maxW="150px"
                    fontSize="xs"
                  />
                </Td>
                <Td py={1.5} isNumeric>
                  <Badge
                    colorScheme={suggestion.confidence >= 0.8 ? 'green' : suggestion.confidence >= 0.5 ? 'yellow' : 'red'}
                    fontSize="10px"
                  >
                    {Math.round(suggestion.confidence * 100)}
                  </Badge>
                </Td>
                <Td py={1.5}>
                  <HStack spacing={0}>
                    <Tooltip label="Appliquer + alias" fontSize="xs">
                      <IconButton
                        aria-label="Apply"
                        icon={<FiCheck />}
                        size="xs"
                        colorScheme="green"
                        variant="ghost"
                        isLoading={isApplying}
                        onClick={() => {
                          const canonical = selectedCanonical[suggestion.mention_id] || suggestion.suggested_canonical
                          if (canonical) onApply(suggestion.mention_id, canonical, true)
                        }}
                      />
                    </Tooltip>
                    <Tooltip label="Blacklist" fontSize="xs">
                      <IconButton
                        aria-label="Blacklist"
                        icon={<FiX />}
                        size="xs"
                        colorScheme="red"
                        variant="ghost"
                        onClick={() => onBlacklist(suggestion.raw_text)}
                      />
                    </Tooltip>
                  </HStack>
                </Td>
              </Tr>
            ))}
          </Tbody>
        </Table>
      </TableContainer>
    </Box>
  )
}

// Aliases Tab - Compact
const AliasesTab = ({
  aliases,
  onAdd,
  onDelete,
  isAdding,
}: {
  aliases: AliasInfo[]
  onAdd: (raw: string, canonical: string) => void
  onDelete: (raw: string) => void
  isAdding: boolean
}) => {
  const { isOpen, onOpen, onClose } = useDisclosure()
  const [newRaw, setNewRaw] = useState('')
  const [newCanonical, setNewCanonical] = useState('')

  const handleAdd = () => {
    if (newRaw && newCanonical) {
      onAdd(newRaw, newCanonical)
      setNewRaw('')
      setNewCanonical('')
      onClose()
    }
  }

  return (
    <VStack spacing={3} align="stretch">
      <Flex justify="space-between" align="center">
        <Text color="text.muted" fontSize="xs">
          Mappings manuels entre markers bruts et formes canoniques
        </Text>
        <Button leftIcon={<FiPlus />} size="xs" bg="#4338CA" color="white" _hover={{ bg: '#6366F1' }} onClick={onOpen}>
          Ajouter
        </Button>
      </Flex>

      <Box bg="whiteAlpha.50" border="1px solid" borderColor="whiteAlpha.100" rounded="lg" overflow="hidden">
        <TableContainer>
          <Table size="sm">
            <Thead>
              <Tr>
                <Th color="text.muted" fontSize="xs" py={2}>Marker brut</Th>
                <Th color="text.muted" fontSize="xs" py={2}>Canonique</Th>
                <Th color="text.muted" fontSize="xs" py={2} w="50px"></Th>
              </Tr>
            </Thead>
            <Tbody>
              {aliases.length === 0 ? (
                <Tr>
                  <Td colSpan={3} py={3}>
                    <Text color="text.muted" textAlign="center" fontSize="xs">
                      Aucun alias configuré
                    </Text>
                  </Td>
                </Tr>
              ) : (
                aliases.map((alias) => (
                  <Tr key={alias.raw_marker} _hover={{ bg: 'whiteAlpha.50' }}>
                    <Td py={1.5}>
                      <Text fontSize="xs" color="text.primary" fontFamily="mono">{alias.raw_marker}</Text>
                    </Td>
                    <Td py={1.5}>
                      <Badge colorScheme="green" fontSize="10px">{alias.canonical_form}</Badge>
                    </Td>
                    <Td py={1.5}>
                      <IconButton
                        aria-label="Delete"
                        icon={<FiTrash2 />}
                        size="xs"
                        colorScheme="red"
                        variant="ghost"
                        onClick={() => onDelete(alias.raw_marker)}
                      />
                    </Td>
                  </Tr>
                ))
              )}
            </Tbody>
          </Table>
        </TableContainer>
      </Box>

      {/* Add Alias Modal - Compact */}
      <Modal isOpen={isOpen} onClose={onClose} size="sm">
        <ModalOverlay />
        <ModalContent bg="bg.secondary" borderColor="whiteAlpha.200">
          <ModalHeader fontSize="sm" color="text.primary" py={3}>Ajouter un alias</ModalHeader>
          <ModalCloseButton size="sm" />
          <ModalBody pb={4}>
            <VStack spacing={3}>
              <FormControl>
                <FormLabel fontSize="xs" color="text.muted">Marker brut</FormLabel>
                <Input
                  size="sm"
                  placeholder="ex: v1.0"
                  value={newRaw}
                  onChange={(e) => setNewRaw(e.target.value)}
                  bg="whiteAlpha.100"
                  borderColor="whiteAlpha.200"
                  fontSize="xs"
                />
              </FormControl>
              <FormControl>
                <FormLabel fontSize="xs" color="text.muted">Forme canonique</FormLabel>
                <Input
                  size="sm"
                  placeholder="ex: Version 1.0"
                  value={newCanonical}
                  onChange={(e) => setNewCanonical(e.target.value)}
                  bg="whiteAlpha.100"
                  borderColor="whiteAlpha.200"
                  fontSize="xs"
                />
              </FormControl>
            </VStack>
          </ModalBody>
          <ModalFooter py={3}>
            <Button variant="ghost" size="sm" mr={2} onClick={onClose}>Annuler</Button>
            <Button
              size="sm"
              bg="#4338CA"
              color="white"
              _hover={{ bg: '#6366F1' }}
              onClick={handleAdd}
              isLoading={isAdding}
              isDisabled={!newRaw || !newCanonical}
            >
              Ajouter
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
    </VStack>
  )
}

// Clusters Tab - Compact
const ClustersTab = ({ clusters }: { clusters: ClusterSuggestion[] }) => {
  if (clusters.length === 0) {
    return (
      <Alert status="info" variant="subtle" rounded="lg" bg="blue.900" border="1px solid" borderColor="blue.700" py={2}>
        <AlertIcon color="blue.400" boxSize={4} />
        <AlertDescription fontSize="xs" color="blue.200">
          Aucun cluster détecté. Importez plus de documents pour voir des patterns émerger.
        </AlertDescription>
      </Alert>
    )
  }

  return (
    <VStack spacing={2} align="stretch">
      {clusters.map((cluster) => (
        <Box
          key={cluster.cluster_id}
          bg="whiteAlpha.50"
          border="1px solid"
          borderColor="whiteAlpha.100"
          rounded="lg"
          p={3}
        >
          <Flex justify="space-between" align="center" mb={2}>
            <HStack spacing={2}>
              <Badge colorScheme="brand" fontSize="10px">{cluster.raw_markers.length} markers</Badge>
              <Badge colorScheme="green" fontSize="10px">{cluster.document_count} docs</Badge>
              <Badge colorScheme={cluster.confidence >= 0.8 ? 'green' : 'yellow'} fontSize="10px">
                {Math.round(cluster.confidence * 100)}%
              </Badge>
            </HStack>
            <Button
              size="xs"
              bg="#4338CA"
              color="white"
              _hover={{ bg: '#6366F1' }}
              rightIcon={<FiArrowRight />}
            >
              {cluster.suggested_canonical}
            </Button>
          </Flex>
          <Flex gap={1} flexWrap="wrap" mb={2}>
            {cluster.raw_markers.map((marker) => (
              <Badge key={marker} variant="subtle" colorScheme="gray" fontFamily="mono" fontSize="10px">
                {marker}
              </Badge>
            ))}
          </Flex>
          <Text fontSize="10px" color="text.muted">{cluster.reason}</Text>
        </Box>
      ))}
    </VStack>
  )
}

// Main Page Component
export default function MarkersPage() {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState(0)

  // Fetch stats
  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['markers', 'normalization', 'stats'],
    queryFn: async () => {
      const response = await apiClient.get<NormalizationStats>('/markers/normalization/stats')
      return response.data
    },
  })

  // Fetch suggestions
  const { data: suggestionsData } = useQuery({
    queryKey: ['markers', 'normalization', 'suggestions'],
    queryFn: async () => {
      const response = await apiClient.get<{ suggestions: NormalizationSuggestion[] }>('/markers/normalization/suggestions')
      return response.data?.suggestions || []
    },
  })

  // Fetch aliases
  const { data: aliasesData } = useQuery({
    queryKey: ['markers', 'normalization', 'aliases'],
    queryFn: async () => {
      const response = await apiClient.get<{ aliases: AliasInfo[] }>('/markers/normalization/aliases')
      return response.data?.aliases || []
    },
  })

  // Fetch clusters
  const { data: clustersData } = useQuery({
    queryKey: ['markers', 'normalization', 'clusters'],
    queryFn: async () => {
      const response = await apiClient.get<{ clusters: ClusterSuggestion[] }>('/markers/normalization/clusters')
      return response.data?.clusters || []
    },
  })

  // Apply normalization mutation
  const applyMutation = useMutation({
    mutationFn: async ({ mentionId, canonical, createAlias }: { mentionId: string, canonical: string, createAlias: boolean }) => {
      const response = await apiClient.post('/markers/normalization/apply', {
        mention_id: mentionId,
        canonical_form: canonical,
        create_alias: createAlias,
      })
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['markers'] })
      toast({ title: 'Normalisation appliquee', status: 'success', duration: 3000 })
    },
    onError: (error: any) => {
      toast({ title: 'Erreur', description: error.message, status: 'error', duration: 5000 })
    },
  })

  // Add alias mutation
  const addAliasMutation = useMutation({
    mutationFn: async ({ raw, canonical }: { raw: string, canonical: string }) => {
      const response = await apiClient.post('/markers/normalization/aliases', {
        raw_marker: raw,
        canonical_form: canonical,
      })
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['markers'] })
      toast({ title: 'Alias ajoute', status: 'success', duration: 3000 })
    },
    onError: (error: any) => {
      toast({ title: 'Erreur', description: error.message, status: 'error', duration: 5000 })
    },
  })

  // Delete alias mutation
  const deleteAliasMutation = useMutation({
    mutationFn: async (rawMarker: string) => {
      const response = await apiClient.delete(`/markers/normalization/aliases/${encodeURIComponent(rawMarker)}`)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['markers'] })
      toast({ title: 'Alias supprime', status: 'success', duration: 3000 })
    },
    onError: (error: any) => {
      toast({ title: 'Erreur', description: error.message, status: 'error', duration: 5000 })
    },
  })

  // Blacklist mutation
  const blacklistMutation = useMutation({
    mutationFn: async (marker: string) => {
      const response = await apiClient.post('/markers/normalization/blacklist', { marker })
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['markers'] })
      toast({ title: 'Marker blackliste', status: 'success', duration: 3000 })
    },
    onError: (error: any) => {
      toast({ title: 'Erreur', description: error.message, status: 'error', duration: 5000 })
    },
  })

  // Tab config
  const tabs = [
    { id: 'overview', label: 'Vue d\'ensemble', icon: FiPercent },
    { id: 'suggestions', label: 'Suggestions', icon: FiAlertTriangle, count: suggestionsData?.length || 0, countColor: 'yellow' },
    { id: 'aliases', label: 'Aliases', icon: FiLink, count: aliasesData?.length || 0, countColor: 'brand' },
    { id: 'clusters', label: 'Clusters', icon: FiLayers },
  ]

  if (statsLoading) {
    return <Center h="200px"><Spinner size="md" color="brand.500" /></Center>
  }

  return (
    <Box maxW="1200px" mx="auto" p={3}>
      {/* Compact Header */}
      <Flex justify="space-between" align="center" mb={3}>
        <HStack spacing={3}>
          <Box
            w={8}
            h={8}
            rounded="lg"
            bgGradient="linear(to-br, #4338CA, #6366F1)"
            display="flex"
            alignItems="center"
            justifyContent="center"
          >
            <Icon as={FiTag} boxSize={4} color="white" />
          </Box>
          <Box>
            <Text fontSize="lg" fontWeight="bold" color="text.primary" lineHeight={1}>
              Markers
            </Text>
            <Text fontSize="xs" color="text.muted">
              Normalisation des identifiants de version et contexte
            </Text>
          </Box>
        </HStack>
      </Flex>

      {/* Compact Tabs */}
      <Flex gap={1} mb={3} flexWrap="wrap">
        {tabs.map((tab, index) => (
          <HStack
            key={tab.id}
            as="button"
            spacing={1.5}
            px={3}
            py={1.5}
            rounded="md"
            bg={activeTab === index ? '#4338CA' : 'whiteAlpha.50'}
            border="1px solid"
            borderColor={activeTab === index ? '#6366F1' : 'whiteAlpha.100'}
            color={activeTab === index ? 'white' : 'text.secondary'}
            fontSize="xs"
            fontWeight="medium"
            cursor="pointer"
            transition="all 0.15s"
            _hover={{ bg: activeTab === index ? '#4338CA' : 'whiteAlpha.100' }}
            onClick={() => setActiveTab(index)}
          >
            <Icon as={tab.icon} boxSize={3.5} />
            <Text>{tab.label}</Text>
            {tab.count !== undefined && tab.count > 0 && (
              <Badge colorScheme={tab.countColor} fontSize="10px" ml={0.5}>{tab.count}</Badge>
            )}
          </HStack>
        ))}
      </Flex>

      {/* Tab Content */}
      <Box>
        {activeTab === 0 && <OverviewTab stats={stats || null} />}
        {activeTab === 1 && (
          <SuggestionsTab
            suggestions={suggestionsData || []}
            onApply={(mentionId, canonical, createAlias) =>
              applyMutation.mutate({ mentionId, canonical, createAlias })
            }
            onBlacklist={(marker) => blacklistMutation.mutate(marker)}
            isApplying={applyMutation.isPending}
          />
        )}
        {activeTab === 2 && (
          <AliasesTab
            aliases={aliasesData || []}
            onAdd={(raw, canonical) => addAliasMutation.mutate({ raw, canonical })}
            onDelete={(raw) => deleteAliasMutation.mutate(raw)}
            isAdding={addAliasMutation.isPending}
          />
        )}
        {activeTab === 3 && <ClustersTab clusters={clustersData || []} />}
      </Box>
    </Box>
  )
}
