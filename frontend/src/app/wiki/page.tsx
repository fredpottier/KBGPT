'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import {
  Box,
  Container,
  Heading,
  Text,
  Input,
  Select,
  Button,
  VStack,
  HStack,
  Flex,
  Badge,
  Icon,
  Spinner,
  Alert,
  AlertIcon,
  AlertTitle,
  AlertDescription,
  Tooltip,
  List,
  ListItem,
  Divider,
  Code,
} from '@chakra-ui/react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Components } from 'react-markdown'
import { FiBook, FiSearch, FiAlertTriangle, FiCheck, FiInfo } from 'react-icons/fi'
import { api } from '@/lib/api'

const LANGUAGES = ['français', 'english', 'deutsch', 'italiano', 'español']
const POLL_INTERVAL = 2000
const POLL_TIMEOUT = 120000

// Composants Markdown Chakra UI (dark theme)
const markdownComponents: Components = {
  h1: ({ children }) => (
    <Heading as="h1" size="xl" color="text.primary" mt={6} mb={3}>
      {children}
    </Heading>
  ),
  h2: ({ children }) => (
    <Heading as="h2" size="lg" color="text.primary" mt={5} mb={2} borderBottom="1px" borderColor="border.default" pb={2}>
      {children}
    </Heading>
  ),
  h3: ({ children }) => (
    <Heading as="h3" size="md" color="text.primary" mt={4} mb={2}>
      {children}
    </Heading>
  ),
  p: ({ children }) => (
    <Text color="text.secondary" mb={3} lineHeight="tall">
      {children}
    </Text>
  ),
  ul: ({ children }) => (
    <Box as="ul" pl={6} mb={3} color="text.secondary">
      {children}
    </Box>
  ),
  ol: ({ children }) => (
    <Box as="ol" pl={6} mb={3} color="text.secondary">
      {children}
    </Box>
  ),
  li: ({ children }) => (
    <Box as="li" mb={1}>
      {children}
    </Box>
  ),
  table: ({ children }) => (
    <Box overflowX="auto" mb={4}>
      <Box as="table" w="full" fontSize="sm" borderWidth="1px" borderColor="border.default" rounded="md">
        {children}
      </Box>
    </Box>
  ),
  thead: ({ children }) => (
    <Box as="thead" bg="bg.hover">
      {children}
    </Box>
  ),
  th: ({ children }) => (
    <Box as="th" px={3} py={2} textAlign="left" fontWeight="semibold" color="text.primary" borderBottomWidth="1px" borderColor="border.default">
      {children}
    </Box>
  ),
  td: ({ children }) => (
    <Box as="td" px={3} py={2} borderBottomWidth="1px" borderColor="border.default" color="text.secondary">
      {children}
    </Box>
  ),
  code: ({ children, className }) => {
    const isInline = !className
    if (isInline) {
      return (
        <Code colorScheme="purple" fontSize="sm" px={1}>
          {children}
        </Code>
      )
    }
    return (
      <Box as="pre" bg="gray.900" p={4} rounded="md" overflowX="auto" mb={3}>
        <Code display="block" whiteSpace="pre" fontSize="sm" color="gray.200">
          {children}
        </Code>
      </Box>
    )
  },
  hr: () => <Divider my={4} borderColor="border.default" />,
  em: ({ children }) => (
    <Text as="em" color="text.muted" fontStyle="italic">
      {children}
    </Text>
  ),
  strong: ({ children }) => (
    <Text as="strong" color="text.primary" fontWeight="bold">
      {children}
    </Text>
  ),
}

interface ConceptSuggestion {
  entity_name: string
  entity_type: string
  claim_count: number
}

interface ArticleData {
  concept_name: string
  language: string
  markdown: string
  sections_count: number
  total_citations: number
  generation_confidence: number
  all_gaps: string[]
  source_count: number
  unit_count: number
  resolution: {
    resolution_method: string
    resolution_confidence: number
    matched_entities: number
    ambiguity_notes: string[]
  }
  generated_at: string
}

export default function WikiPage() {
  const [searchQuery, setSearchQuery] = useState('')
  const [suggestions, setSuggestions] = useState<ConceptSuggestion[]>([])
  const [showSuggestions, setShowSuggestions] = useState(false)
  const [selectedConcept, setSelectedConcept] = useState('')
  const [language, setLanguage] = useState('français')
  const [jobId, setJobId] = useState<string | null>(null)
  const [jobStatus, setJobStatus] = useState<string | null>(null)
  const [progress, setProgress] = useState<string | null>(null)
  const [article, setArticle] = useState<ArticleData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isGenerating, setIsGenerating] = useState(false)

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const pollStartRef = useRef<number>(0)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const suggestionsRef = useRef<HTMLDivElement>(null)

  // Nettoyage polling
  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

  useEffect(() => {
    return () => {
      stopPolling()
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [stopPolling])

  // Fermer suggestions si clic extérieur
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (suggestionsRef.current && !suggestionsRef.current.contains(e.target as Node)) {
        setShowSuggestions(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  // Autocomplétion debounced
  const handleSearchChange = (value: string) => {
    setSearchQuery(value)
    setSelectedConcept('')

    if (debounceRef.current) clearTimeout(debounceRef.current)

    if (value.length < 2) {
      setSuggestions([])
      setShowSuggestions(false)
      return
    }

    debounceRef.current = setTimeout(async () => {
      const res = await api.wiki.searchConcepts(value, 10)
      if (res.success && res.data?.results) {
        setSuggestions(res.data.results)
        setShowSuggestions(true)
      }
    }, 300)
  }

  const selectConcept = (concept: ConceptSuggestion) => {
    setSelectedConcept(concept.entity_name)
    setSearchQuery(concept.entity_name)
    setShowSuggestions(false)
  }

  // Reset state avant nouvelle génération
  const resetState = () => {
    stopPolling()
    setArticle(null)
    setJobId(null)
    setJobStatus(null)
    setProgress(null)
    setError(null)
  }

  // Lancer la génération
  const handleGenerate = async () => {
    const concept = selectedConcept || searchQuery.trim()
    if (!concept) return

    resetState()
    setIsGenerating(true)

    const forceRegenerate = article !== null
    const res = await api.wiki.generate(concept, language, forceRegenerate)
    if (!res.success || !res.data) {
      setError(res.error || 'Erreur lors du lancement de la génération')
      setIsGenerating(false)
      return
    }

    const newJobId = res.data.job_id
    setJobId(newJobId)
    setJobStatus(res.data.status)

    // Si le job est déjà terminé (réutilisé)
    if (res.data.status === 'completed' || res.data.status === 'completed_with_warnings') {
      await fetchArticle(newJobId)
      setIsGenerating(false)
      return
    }

    // Démarrer le polling
    pollStartRef.current = Date.now()
    pollRef.current = setInterval(async () => {
      const elapsed = Date.now() - pollStartRef.current
      if (elapsed > POLL_TIMEOUT) {
        stopPolling()
        setError('Génération trop longue (> 2 min). Veuillez réessayer.')
        setIsGenerating(false)
        return
      }

      const statusRes = await api.wiki.status(newJobId)
      if (!statusRes.success || !statusRes.data) return

      const { status: st, progress: prog, error: err } = statusRes.data
      setJobStatus(st)
      setProgress(prog)

      if (st === 'completed' || st === 'completed_with_warnings') {
        stopPolling()
        await fetchArticle(newJobId)
        setIsGenerating(false)
      } else if (st === 'failed') {
        stopPolling()
        setError(err || 'Génération échouée')
        setIsGenerating(false)
      }
    }, POLL_INTERVAL)
  }

  const fetchArticle = async (id: string) => {
    const res = await api.wiki.article(id)
    if (res.success && res.data) {
      setArticle(res.data)
      setJobStatus(res.data.generation_confidence < 0.5 ? 'completed_with_warnings' : 'completed')
    } else {
      setError(res.error || 'Erreur lors de la récupération de l\'article')
    }
  }

  const confidenceColor = (conf: number) => {
    if (conf >= 0.7) return 'green'
    if (conf >= 0.5) return 'yellow'
    return 'red'
  }

  const methodColor = (method: string) => {
    if (method.startsWith('exact')) return 'green'
    if (method === 'canonical' || method.startsWith('alias')) return 'blue'
    return 'red'
  }

  return (
    <Container maxW="7xl" py={8} mt={16}>
      {/* Header */}
      <VStack spacing={2} mb={8} align="start">
        <HStack>
          <Icon as={FiBook} boxSize={7} color="brand.400" />
          <Heading size="lg" color="text.primary">Wiki Generation Console</Heading>
        </HStack>
        <Text color="text.muted" fontSize="sm">
          Recherchez un concept, lancez la génération et consultez l'article encyclopédique.
        </Text>
      </VStack>

      {/* Controls */}
      <Box bg="surface.default" rounded="xl" p={6} mb={6} borderWidth="1px" borderColor="border.default">
        <VStack spacing={4} align="stretch">
          {/* Recherche concept */}
          <Box position="relative" ref={suggestionsRef}>
            <HStack>
              <Icon as={FiSearch} color="text.muted" />
              <Input
                placeholder="Rechercher un concept..."
                value={searchQuery}
                onChange={(e) => handleSearchChange(e.target.value)}
                onFocus={() => suggestions.length > 0 && setShowSuggestions(true)}
                bg="bg.secondary"
                borderColor="border.default"
                color="text.primary"
                _placeholder={{ color: 'text.muted' }}
              />
            </HStack>
            {showSuggestions && suggestions.length > 0 && (
              <Box
                position="absolute"
                top="100%"
                left={0}
                right={0}
                zIndex={10}
                bg="surface.default"
                borderWidth="1px"
                borderColor="border.default"
                rounded="md"
                shadow="lg"
                maxH="250px"
                overflowY="auto"
                mt={1}
              >
                {suggestions.map((s, i) => (
                  <Box
                    key={i}
                    px={4}
                    py={2}
                    cursor="pointer"
                    _hover={{ bg: 'bg.hover' }}
                    onClick={() => selectConcept(s)}
                  >
                    <HStack justify="space-between">
                      <VStack align="start" spacing={0}>
                        <Text color="text.primary" fontWeight="medium" fontSize="sm">{s.entity_name}</Text>
                        <Text color="text.muted" fontSize="xs">{s.entity_type}</Text>
                      </VStack>
                      <Badge colorScheme="purple" fontSize="xs">{s.claim_count} claims</Badge>
                    </HStack>
                  </Box>
                ))}
              </Box>
            )}
          </Box>

          <HStack>
            <Select
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              maxW="200px"
              bg="bg.secondary"
              borderColor="border.default"
              color="text.primary"
            >
              {LANGUAGES.map((l) => (
                <option key={l} value={l}>{l}</option>
              ))}
            </Select>
            <Button
              colorScheme="brand"
              onClick={handleGenerate}
              isDisabled={(!selectedConcept && !searchQuery.trim()) || isGenerating}
              isLoading={isGenerating}
              loadingText="Génération..."
              leftIcon={<Icon as={FiBook} />}
            >
              {article ? 'Régénérer l\'article' : 'Générer l\'article'}
            </Button>
          </HStack>
        </VStack>
      </Box>

      {/* Progression */}
      {isGenerating && (
        <Box bg="surface.default" rounded="xl" p={4} mb={6} borderWidth="1px" borderColor="border.default">
          <HStack>
            <Spinner size="sm" color="brand.400" />
            <Text color="text.secondary" fontSize="sm">
              {progress || 'Initialisation...'}
            </Text>
          </HStack>
        </Box>
      )}

      {/* Erreur */}
      {error && (
        <Alert status="error" rounded="xl" mb={6} bg="red.900" borderColor="red.600" borderWidth="1px">
          <AlertIcon />
          <Box>
            <AlertTitle color="red.200">Erreur</AlertTitle>
            <AlertDescription color="red.300">{error}</AlertDescription>
          </Box>
        </Alert>
      )}

      {/* Article + Metadata */}
      {article && (
        <Flex gap={6} direction={{ base: 'column', lg: 'row' }}>
          {/* Article principal */}
          <Box
            flex={1}
            bg="surface.default"
            rounded="xl"
            p={6}
            borderWidth="1px"
            borderColor="border.default"
            minW={0}
          >
            {jobStatus === 'completed_with_warnings' && (
              <Alert status="warning" rounded="md" mb={4} bg="orange.900" borderColor="orange.600" borderWidth="1px">
                <AlertIcon color="orange.300" />
                <Box>
                  <AlertTitle color="orange.200" fontSize="sm">Attention</AlertTitle>
                  <AlertDescription color="orange.300" fontSize="xs">
                    Article généré avec des signaux faibles (confiance basse, lacunes importantes ou résolution approximative).
                  </AlertDescription>
                </Box>
              </Alert>
            )}
            <Box className="wiki-article">
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                {article.markdown}
              </ReactMarkdown>
            </Box>
          </Box>

          {/* Panneau metadata */}
          <Box
            w={{ base: 'full', lg: '300px' }}
            flexShrink={0}
          >
            <VStack spacing={4} align="stretch">
              {/* Confiance */}
              <Box bg="surface.default" rounded="xl" p={4} borderWidth="1px" borderColor="border.default">
                <Text color="text.muted" fontSize="xs" mb={2} fontWeight="semibold" textTransform="uppercase">
                  Confiance de génération
                </Text>
                <Tooltip label="Signal d'exploitation : mesure la couverture et cohérence des preuves, pas la 'vérité' du contenu." hasArrow>
                  <HStack>
                    <Box flex={1} bg="gray.700" rounded="full" h="8px">
                      <Box
                        bg={`${confidenceColor(article.generation_confidence)}.400`}
                        h="8px"
                        rounded="full"
                        w={`${Math.round(article.generation_confidence * 100)}%`}
                        transition="width 0.5s"
                      />
                    </Box>
                    <Text color="text.primary" fontWeight="bold" fontSize="sm">
                      {Math.round(article.generation_confidence * 100)}%
                    </Text>
                  </HStack>
                </Tooltip>
              </Box>

              {/* Stats */}
              <Box bg="surface.default" rounded="xl" p={4} borderWidth="1px" borderColor="border.default">
                <Text color="text.muted" fontSize="xs" mb={3} fontWeight="semibold" textTransform="uppercase">
                  Statistiques
                </Text>
                <VStack spacing={2} align="stretch">
                  <HStack justify="space-between">
                    <Text color="text.muted" fontSize="sm">Sections</Text>
                    <Text color="text.primary" fontWeight="medium" fontSize="sm">{article.sections_count}</Text>
                  </HStack>
                  <HStack justify="space-between">
                    <Text color="text.muted" fontSize="sm">Citations</Text>
                    <Text color="text.primary" fontWeight="medium" fontSize="sm">{article.total_citations}</Text>
                  </HStack>
                  <HStack justify="space-between">
                    <Text color="text.muted" fontSize="sm">Sources</Text>
                    <Text color="text.primary" fontWeight="medium" fontSize="sm">{article.source_count}</Text>
                  </HStack>
                  <HStack justify="space-between">
                    <Text color="text.muted" fontSize="sm">Evidence units</Text>
                    <Text color="text.primary" fontWeight="medium" fontSize="sm">{article.unit_count}</Text>
                  </HStack>
                </VStack>
              </Box>

              {/* Résolution */}
              <Box bg="surface.default" rounded="xl" p={4} borderWidth="1px" borderColor="border.default">
                <Text color="text.muted" fontSize="xs" mb={3} fontWeight="semibold" textTransform="uppercase">
                  Résolution du concept
                </Text>
                <VStack spacing={2} align="stretch">
                  <HStack justify="space-between">
                    <Text color="text.muted" fontSize="sm">Méthode</Text>
                    <Badge colorScheme={methodColor(article.resolution.resolution_method)} fontSize="xs">
                      {article.resolution.resolution_method}
                    </Badge>
                  </HStack>
                  <HStack justify="space-between">
                    <Text color="text.muted" fontSize="sm">Confiance</Text>
                    <Text color="text.primary" fontWeight="medium" fontSize="sm">
                      {Math.round(article.resolution.resolution_confidence * 100)}%
                    </Text>
                  </HStack>
                  <HStack justify="space-between">
                    <Text color="text.muted" fontSize="sm">Entités</Text>
                    <Text color="text.primary" fontWeight="medium" fontSize="sm">
                      {article.resolution.matched_entities}
                    </Text>
                  </HStack>
                  {article.resolution.resolution_method === 'fuzzy' && (
                    <HStack mt={1}>
                      <Icon as={FiAlertTriangle} color="orange.400" boxSize={3} />
                      <Text color="orange.300" fontSize="xs">Ancrage approximatif (fuzzy)</Text>
                    </HStack>
                  )}
                  {article.resolution.ambiguity_notes.length > 0 && (
                    <Box mt={1}>
                      {article.resolution.ambiguity_notes.map((note, i) => (
                        <Text key={i} color="orange.300" fontSize="xs">{note}</Text>
                      ))}
                    </Box>
                  )}
                </VStack>
              </Box>

              {/* Lacunes */}
              {article.all_gaps.length > 0 && (
                <Box bg="surface.default" rounded="xl" p={4} borderWidth="1px" borderColor="border.default">
                  <Text color="text.muted" fontSize="xs" mb={3} fontWeight="semibold" textTransform="uppercase">
                    Lacunes identifiées ({article.all_gaps.length})
                  </Text>
                  <VStack spacing={1} align="stretch">
                    {article.all_gaps.map((gap, i) => (
                      <HStack key={i} align="start">
                        <Icon as={FiInfo} color="yellow.400" boxSize={3} mt={1} flexShrink={0} />
                        <Text color="text.muted" fontSize="xs">{gap}</Text>
                      </HStack>
                    ))}
                  </VStack>
                </Box>
              )}

              {/* Metadata */}
              <Box bg="surface.default" rounded="xl" p={4} borderWidth="1px" borderColor="border.default">
                <Text color="text.muted" fontSize="xs" mb={2} fontWeight="semibold" textTransform="uppercase">
                  Metadata
                </Text>
                <VStack spacing={1} align="stretch">
                  <Text color="text.muted" fontSize="xs">
                    Langue : {article.language}
                  </Text>
                  <Text color="text.muted" fontSize="xs">
                    Généré le : {new Date(article.generated_at).toLocaleString('fr-FR')}
                  </Text>
                </VStack>
              </Box>
            </VStack>
          </Box>
        </Flex>
      )}
    </Container>
  )
}
