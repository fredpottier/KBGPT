'use client'

import { useState, useEffect } from 'react'
import {
  Box,
  Container,
  Heading,
  Text,
  VStack,
  HStack,
  Grid,
  GridItem,
  Card,
  CardHeader,
  CardBody,
  Button,
  Select,
  Badge,
  Divider,
  Spinner,
  Alert,
  AlertIcon,
  AlertTitle,
  AlertDescription,
  Stat,
  StatLabel,
  StatNumber,
  StatHelpText,
  Icon,
  Flex,
  Tag,
  TagLabel,
  TagLeftIcon,
  Tooltip,
  useToast,
  Tabs,
  TabList,
  TabPanels,
  Tab,
  TabPanel,
  Input,
  InputGroup,
  InputLeftElement,
} from '@chakra-ui/react'
import {
  FiGitBranch,
  FiPlus,
  FiMinus,
  FiCheck,
  FiAlertTriangle,
  FiSearch,
  FiRefreshCw,
  FiFilter,
  FiArrowRight,
  FiInfo,
} from 'react-icons/fi'
import MainLayout from '@/components/layout/MainLayout'
import { fetchWithAuth } from '@/lib/fetchWithAuth'

// API Backend URL (bypass Next.js API routes)
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface ConceptInfo {
  concept_id: string
  label: string
  canonical_id?: string
  canonical_name?: string
  polarity: string
  scope: string
  confidence: number
  markers: string[]
  document_id?: string
}

interface DiffStats {
  count_only_a: number
  count_only_b: number
  count_both: number
  count_changed: number
  min_confidence?: number
  mode?: string
}

interface DiffResponse {
  marker_a: string
  marker_b: string
  mode: string
  only_in_a: ConceptInfo[]
  only_in_b: ConceptInfo[]
  in_both: ConceptInfo[]
  changed: any[]
  stats: DiffStats
}

interface MarkerInfo {
  value: string
  kind: string
  concept_count: number
  avg_confidence?: number
}

// Couleurs pour les polarités
const polarityColors: Record<string, string> = {
  positive: 'green',
  negative: 'red',
  deprecated: 'orange',
  future: 'blue',
  conditional: 'purple',
  unknown: 'gray',
}

// Icônes pour les scopes
const scopeIcons: Record<string, any> = {
  general: FiCheck,
  constrained: FiFilter,
  unknown: FiInfo,
}

export default function ComparePage() {
  const [markerA, setMarkerA] = useState('')
  const [markerB, setMarkerB] = useState('')
  const [diffMode, setDiffMode] = useState('concepts')
  const [minConfidence, setMinConfidence] = useState(0.5)
  const [diffResult, setDiffResult] = useState<DiffResponse | null>(null)
  const [availableMarkers, setAvailableMarkers] = useState<MarkerInfo[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [isLoadingMarkers, setIsLoadingMarkers] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [searchFilter, setSearchFilter] = useState('')
  const toast = useToast()

  // Charger les markers disponibles
  useEffect(() => {
    loadAvailableMarkers()
  }, [])

  const loadAvailableMarkers = async () => {
    setIsLoadingMarkers(true)
    try {
      // Endpoint dynamique: récupère les markers depuis Neo4j
      const response = await fetchWithAuth(`${API_BASE_URL}/api/markers?limit=50`)
      if (response.ok) {
        const data = await response.json()
        if (data.markers && data.markers.length > 0) {
          setAvailableMarkers(data.markers)
        } else {
          // Aucun marker en base, proposer des valeurs par défaut pour saisie manuelle
          setAvailableMarkers([])
        }
      } else {
        // API non disponible, liste vide (saisie manuelle possible)
        console.warn('Markers API not available, manual input mode')
        setAvailableMarkers([])
      }
    } catch (err) {
      console.error('Failed to load markers:', err)
      setAvailableMarkers([])
    } finally {
      setIsLoadingMarkers(false)
    }
  }

  const executeDiff = async () => {
    if (!markerA || !markerB) {
      toast({
        title: 'Sélection requise',
        description: 'Veuillez sélectionner deux markers à comparer',
        status: 'warning',
        duration: 3000,
      })
      return
    }

    if (markerA === markerB) {
      toast({
        title: 'Markers identiques',
        description: 'Veuillez sélectionner deux markers différents',
        status: 'warning',
        duration: 3000,
      })
      return
    }

    setIsLoading(true)
    setError(null)

    try {
      const response = await fetchWithAuth(`${API_BASE_URL}/api/concepts/diff`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          marker_a: markerA,
          marker_b: markerB,
          mode: diffMode,
          min_confidence: minConfidence,
          include_details: true,
        }),
      })

      if (!response.ok) {
        throw new Error(`Diff failed: ${response.status}`)
      }

      const data = await response.json()
      setDiffResult(data)

      toast({
        title: 'Comparaison terminée',
        description: `${data.stats?.count_only_a || 0} concepts uniquement dans ${markerA}, ${data.stats?.count_only_b || 0} dans ${markerB}`,
        status: 'success',
        duration: 4000,
      })
    } catch (err: any) {
      setError(err.message || 'Erreur lors de la comparaison')
      toast({
        title: 'Erreur',
        description: err.message || 'La comparaison a échoué',
        status: 'error',
        duration: 5000,
      })
    } finally {
      setIsLoading(false)
    }
  }

  const filterConcepts = (concepts: ConceptInfo[]) => {
    if (!searchFilter) return concepts
    const filter = searchFilter.toLowerCase()
    return concepts.filter(
      (c) =>
        c.label.toLowerCase().includes(filter) ||
        c.concept_id.toLowerCase().includes(filter) ||
        (c.canonical_name && c.canonical_name.toLowerCase().includes(filter))
    )
  }

  const renderConceptCard = (concept: ConceptInfo, context: 'a' | 'b' | 'both') => (
    <Card
      key={concept.concept_id}
      size="sm"
      variant="outline"
      borderColor={
        context === 'a' ? 'red.200' : context === 'b' ? 'green.200' : 'blue.200'
      }
      bg={
        context === 'a'
          ? 'red.50'
          : context === 'b'
          ? 'green.50'
          : 'blue.50'
      }
      _dark={{
        bg:
          context === 'a'
            ? 'red.900'
            : context === 'b'
            ? 'green.900'
            : 'blue.900',
        borderColor:
          context === 'a' ? 'red.700' : context === 'b' ? 'green.700' : 'blue.700',
      }}
    >
      <CardBody py={2} px={3}>
        <VStack align="stretch" spacing={1}>
          <HStack justify="space-between">
            <Text fontWeight="semibold" fontSize="sm" noOfLines={1}>
              {concept.label}
            </Text>
            <Badge
              colorScheme={polarityColors[concept.polarity] || 'gray'}
              size="sm"
            >
              {concept.polarity}
            </Badge>
          </HStack>

          <HStack spacing={2} wrap="wrap">
            {concept.canonical_name && (
              <Tooltip label={`Canonical: ${concept.canonical_id}`}>
                <Tag size="sm" colorScheme="purple" variant="subtle">
                  <TagLabel>{concept.canonical_name}</TagLabel>
                </Tag>
              </Tooltip>
            )}
            <Tag
              size="sm"
              colorScheme={concept.scope === 'general' ? 'teal' : 'orange'}
              variant="outline"
            >
              <TagLeftIcon as={scopeIcons[concept.scope] || FiInfo} />
              <TagLabel>{concept.scope}</TagLabel>
            </Tag>
            {concept.confidence && (
              <Tag size="sm" variant="subtle">
                <TagLabel>{Math.round(concept.confidence * 100)}%</TagLabel>
              </Tag>
            )}
          </HStack>

          {concept.markers && concept.markers.length > 0 && (
            <HStack spacing={1} wrap="wrap">
              {concept.markers.map((m) => (
                <Badge key={m} variant="outline" fontSize="xs">
                  {m}
                </Badge>
              ))}
            </HStack>
          )}
        </VStack>
      </CardBody>
    </Card>
  )

  return (
    <MainLayout>
      <Container maxW="container.xl" py={6}>
        <VStack spacing={6} align="stretch">
          {/* Header */}
          <Box>
            <HStack mb={2}>
              <Icon as={FiGitBranch} boxSize={6} color="brand.500" />
              <Heading size="lg">Comparaison de Concepts</Heading>
            </HStack>
            <Text color="text.secondary">
              Comparez les concepts entre deux markers (versions, éditions, etc.)
              pour identifier les différences.
            </Text>
          </Box>

          {/* Selection Panel */}
          <Card>
            <CardHeader pb={2}>
              <Heading size="sm">Sélection des Markers</Heading>
            </CardHeader>
            <CardBody>
              <Grid templateColumns={{ base: '1fr', md: 'repeat(5, 1fr)' }} gap={4}>
                <GridItem>
                  <VStack align="stretch">
                    <Text fontSize="sm" fontWeight="medium">
                      Marker A
                    </Text>
                    {availableMarkers.length > 0 ? (
                      <Select
                        value={markerA}
                        onChange={(e) => setMarkerA(e.target.value)}
                        placeholder="Sélectionner..."
                        isDisabled={isLoadingMarkers}
                      >
                        {availableMarkers.map((m) => (
                          <option key={m.value} value={m.value}>
                            {m.value} ({m.kind}) - {m.concept_count} concepts
                          </option>
                        ))}
                      </Select>
                    ) : (
                      <Input
                        value={markerA}
                        onChange={(e) => setMarkerA(e.target.value)}
                        placeholder="Ex: 1809, 2025, FPS03..."
                        isDisabled={isLoadingMarkers}
                      />
                    )}
                  </VStack>
                </GridItem>

                <GridItem display="flex" alignItems="flex-end" justifyContent="center">
                  <Icon as={FiArrowRight} boxSize={6} color="text.muted" mb={2} />
                </GridItem>

                <GridItem>
                  <VStack align="stretch">
                    <Text fontSize="sm" fontWeight="medium">
                      Marker B
                    </Text>
                    {availableMarkers.length > 0 ? (
                      <Select
                        value={markerB}
                        onChange={(e) => setMarkerB(e.target.value)}
                        placeholder="Sélectionner..."
                        isDisabled={isLoadingMarkers}
                      >
                        {availableMarkers.map((m) => (
                          <option key={m.value} value={m.value}>
                            {m.value} ({m.kind}) - {m.concept_count} concepts
                          </option>
                        ))}
                      </Select>
                    ) : (
                      <Input
                        value={markerB}
                        onChange={(e) => setMarkerB(e.target.value)}
                        placeholder="Ex: 2020, 2508, Cloud..."
                        isDisabled={isLoadingMarkers}
                      />
                    )}
                  </VStack>
                </GridItem>

                <GridItem>
                  <VStack align="stretch">
                    <Text fontSize="sm" fontWeight="medium">
                      Mode
                    </Text>
                    <Select
                      value={diffMode}
                      onChange={(e) => setDiffMode(e.target.value)}
                    >
                      <option value="concepts">Concepts (présence)</option>
                      <option value="assertions">Assertions (polarity)</option>
                    </Select>
                  </VStack>
                </GridItem>

                <GridItem display="flex" alignItems="flex-end">
                  <Button
                    colorScheme="brand"
                    leftIcon={<FiRefreshCw />}
                    onClick={executeDiff}
                    isLoading={isLoading}
                    loadingText="Comparaison..."
                    w="full"
                  >
                    Comparer
                  </Button>
                </GridItem>
              </Grid>
            </CardBody>
          </Card>

          {/* Error Alert */}
          {error && (
            <Alert status="error" rounded="lg">
              <AlertIcon />
              <AlertTitle>Erreur</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          {/* Results */}
          {diffResult && (
            <>
              {/* Stats Summary */}
              <Grid templateColumns={{ base: '1fr', md: 'repeat(4, 1fr)' }} gap={4}>
                <GridItem>
                  <Card bg="red.50" _dark={{ bg: 'red.900' }}>
                    <CardBody>
                      <Stat>
                        <StatLabel color="red.600" _dark={{ color: 'red.200' }}>
                          <HStack>
                            <Icon as={FiMinus} />
                            <Text>Uniquement dans {markerA}</Text>
                          </HStack>
                        </StatLabel>
                        <StatNumber color="red.700" _dark={{ color: 'red.100' }}>
                          {diffResult.stats?.count_only_a || 0}
                        </StatNumber>
                        <StatHelpText>concepts</StatHelpText>
                      </Stat>
                    </CardBody>
                  </Card>
                </GridItem>

                <GridItem>
                  <Card bg="green.50" _dark={{ bg: 'green.900' }}>
                    <CardBody>
                      <Stat>
                        <StatLabel color="green.600" _dark={{ color: 'green.200' }}>
                          <HStack>
                            <Icon as={FiPlus} />
                            <Text>Uniquement dans {markerB}</Text>
                          </HStack>
                        </StatLabel>
                        <StatNumber color="green.700" _dark={{ color: 'green.100' }}>
                          {diffResult.stats?.count_only_b || 0}
                        </StatNumber>
                        <StatHelpText>concepts</StatHelpText>
                      </Stat>
                    </CardBody>
                  </Card>
                </GridItem>

                <GridItem>
                  <Card bg="blue.50" _dark={{ bg: 'blue.900' }}>
                    <CardBody>
                      <Stat>
                        <StatLabel color="blue.600" _dark={{ color: 'blue.200' }}>
                          <HStack>
                            <Icon as={FiCheck} />
                            <Text>Dans les deux</Text>
                          </HStack>
                        </StatLabel>
                        <StatNumber color="blue.700" _dark={{ color: 'blue.100' }}>
                          {diffResult.stats?.count_both || 0}
                        </StatNumber>
                        <StatHelpText>concepts communs</StatHelpText>
                      </Stat>
                    </CardBody>
                  </Card>
                </GridItem>

                <GridItem>
                  <Card bg="orange.50" _dark={{ bg: 'orange.900' }}>
                    <CardBody>
                      <Stat>
                        <StatLabel color="orange.600" _dark={{ color: 'orange.200' }}>
                          <HStack>
                            <Icon as={FiAlertTriangle} />
                            <Text>Changements</Text>
                          </HStack>
                        </StatLabel>
                        <StatNumber color="orange.700" _dark={{ color: 'orange.100' }}>
                          {diffResult.stats?.count_changed || 0}
                        </StatNumber>
                        <StatHelpText>polarity modifiée</StatHelpText>
                      </Stat>
                    </CardBody>
                  </Card>
                </GridItem>
              </Grid>

              {/* Search Filter */}
              <InputGroup>
                <InputLeftElement>
                  <Icon as={FiSearch} color="text.muted" />
                </InputLeftElement>
                <Input
                  placeholder="Filtrer les concepts..."
                  value={searchFilter}
                  onChange={(e) => setSearchFilter(e.target.value)}
                />
              </InputGroup>

              {/* Diff Tabs */}
              <Tabs colorScheme="brand" variant="enclosed">
                <TabList>
                  <Tab>
                    <HStack>
                      <Icon as={FiMinus} color="red.500" />
                      <Text>
                        Uniquement {markerA} ({filterConcepts(diffResult.only_in_a).length})
                      </Text>
                    </HStack>
                  </Tab>
                  <Tab>
                    <HStack>
                      <Icon as={FiPlus} color="green.500" />
                      <Text>
                        Uniquement {markerB} ({filterConcepts(diffResult.only_in_b).length})
                      </Text>
                    </HStack>
                  </Tab>
                  <Tab>
                    <HStack>
                      <Icon as={FiCheck} color="blue.500" />
                      <Text>
                        Communs ({filterConcepts(diffResult.in_both).length})
                      </Text>
                    </HStack>
                  </Tab>
                  {diffResult.changed && diffResult.changed.length > 0 && (
                    <Tab>
                      <HStack>
                        <Icon as={FiAlertTriangle} color="orange.500" />
                        <Text>Changements ({diffResult.changed.length})</Text>
                      </HStack>
                    </Tab>
                  )}
                </TabList>

                <TabPanels>
                  {/* Only in A */}
                  <TabPanel px={0}>
                    {filterConcepts(diffResult.only_in_a).length === 0 ? (
                      <Alert status="info" rounded="lg">
                        <AlertIcon />
                        Aucun concept uniquement présent dans {markerA}
                      </Alert>
                    ) : (
                      <Grid
                        templateColumns={{
                          base: '1fr',
                          md: 'repeat(2, 1fr)',
                          lg: 'repeat(3, 1fr)',
                        }}
                        gap={3}
                      >
                        {filterConcepts(diffResult.only_in_a).map((c) =>
                          renderConceptCard(c, 'a')
                        )}
                      </Grid>
                    )}
                  </TabPanel>

                  {/* Only in B */}
                  <TabPanel px={0}>
                    {filterConcepts(diffResult.only_in_b).length === 0 ? (
                      <Alert status="info" rounded="lg">
                        <AlertIcon />
                        Aucun concept uniquement présent dans {markerB}
                      </Alert>
                    ) : (
                      <Grid
                        templateColumns={{
                          base: '1fr',
                          md: 'repeat(2, 1fr)',
                          lg: 'repeat(3, 1fr)',
                        }}
                        gap={3}
                      >
                        {filterConcepts(diffResult.only_in_b).map((c) =>
                          renderConceptCard(c, 'b')
                        )}
                      </Grid>
                    )}
                  </TabPanel>

                  {/* In Both */}
                  <TabPanel px={0}>
                    {filterConcepts(diffResult.in_both).length === 0 ? (
                      <Alert status="info" rounded="lg">
                        <AlertIcon />
                        Aucun concept commun aux deux markers
                      </Alert>
                    ) : (
                      <Grid
                        templateColumns={{
                          base: '1fr',
                          md: 'repeat(2, 1fr)',
                          lg: 'repeat(3, 1fr)',
                        }}
                        gap={3}
                      >
                        {filterConcepts(diffResult.in_both).map((c) =>
                          renderConceptCard(c, 'both')
                        )}
                      </Grid>
                    )}
                  </TabPanel>

                  {/* Changed */}
                  {diffResult.changed && diffResult.changed.length > 0 && (
                    <TabPanel px={0}>
                      <VStack spacing={3} align="stretch">
                        {diffResult.changed.map((change, idx) => (
                          <Card key={idx} variant="outline" borderColor="orange.300">
                            <CardBody>
                              <HStack justify="space-between">
                                <VStack align="start" spacing={1}>
                                  <Text fontWeight="semibold">{change.label}</Text>
                                  <Text fontSize="sm" color="text.muted">
                                    {change.concept_id}
                                  </Text>
                                </VStack>
                                <HStack>
                                  <Badge colorScheme={polarityColors[change.polarity_in_a]}>
                                    {change.polarity_in_a}
                                  </Badge>
                                  <Icon as={FiArrowRight} />
                                  <Badge colorScheme={polarityColors[change.polarity_in_b]}>
                                    {change.polarity_in_b}
                                  </Badge>
                                </HStack>
                              </HStack>
                            </CardBody>
                          </Card>
                        ))}
                      </VStack>
                    </TabPanel>
                  )}
                </TabPanels>
              </Tabs>
            </>
          )}

          {/* Empty State */}
          {!diffResult && !isLoading && (
            <Card>
              <CardBody>
                <VStack py={10} spacing={4}>
                  <Icon as={FiGitBranch} boxSize={12} color="text.muted" />
                  <Text color="text.muted" textAlign="center">
                    Sélectionnez deux markers et cliquez sur "Comparer" pour voir
                    les différences entre les concepts.
                  </Text>
                  <Text fontSize="sm" color="text.muted" textAlign="center">
                    Exemples: comparer 1809 vs 2020, ou Cloud vs Private
                  </Text>
                </VStack>
              </CardBody>
            </Card>
          )}
        </VStack>
      </Container>
    </MainLayout>
  )
}
