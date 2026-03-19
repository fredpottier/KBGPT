'use client'

import { useState, useEffect } from 'react'
import {
  Box,
  Container,
  Heading,
  Text,
  VStack,
  HStack,
  Flex,
  Badge,
  Icon,
  Spinner,
  Link,
  SimpleGrid,
  Wrap,
  WrapItem,
  Progress,
  Tooltip,
} from '@chakra-ui/react'
import NextLink from 'next/link'
import {
  FiBook,
  FiChevronRight,
  FiClock,
  FiFileText,
  FiDatabase,
  FiLayers,
  FiStar,
  FiAlertTriangle,
  FiAlertCircle,
  FiEdit3,
  FiTarget,
  FiSlash,
  FiInfo,
} from 'react-icons/fi'
import { api } from '@/lib/api'

interface CorpusStats {
  total_documents: number
  total_claims: number
  total_entities: number
  total_articles: number
  coverage_pct: number
}

interface DomainContext {
  domain_summary: string
  industry: string
  sub_domains: string[]
  key_concepts: string[]
  target_users: string[]
}

interface CorpusNarrativeEntityType {
  type: string
  count: number
}

interface CorpusNarrativeEntity {
  name: string
  claim_count: number
  has_article: boolean
  slug?: string | null
}

interface CorpusNarrativeDocType {
  type: string
  count: number
}

interface CorpusNarrative {
  top_entity_types: CorpusNarrativeEntityType[]
  top_entities: CorpusNarrativeEntity[]
  doc_type_distribution: CorpusNarrativeDocType[]
  entity_count_with_articles: number
  entity_count_without_articles: number
}

interface DomainArticle {
  slug: string
  title: string
  tier: number
}

interface KnowledgeDomain {
  name: string
  domain_key: string
  question: string
  doc_count: number
  sub_domains: string[]
  articles: DomainArticle[]
  article_count: number
}

interface RecentArticle {
  slug: string
  title: string
  entity_type: string
  category_key: string
  importance_tier: number
  generation_confidence: number
  updated_at?: string
}

interface StartHereItem {
  slug: string
  title: string
  importance_score: number
}

interface BlindSpot {
  type: string
  domain: string
  detail: string
  severity: string
}

interface HomeData {
  corpus_stats: CorpusStats
  domain_context?: DomainContext | null
  corpus_narrative?: CorpusNarrative | null
  knowledge_domains: KnowledgeDomain[]
  recent_articles: RecentArticle[]
  start_here?: StartHereItem[]
  blind_spots?: BlindSpot[]
  contradiction_count?: number
}

const DOMAIN_COLORS: Record<string, { border: string; accent: string; bg: string }> = {
  compliance: { border: 'blue.600', accent: 'blue.300', bg: 'rgba(59, 130, 246, 0.06)' },
  security: { border: 'red.600', accent: 'red.300', bg: 'rgba(239, 68, 68, 0.06)' },
  operations: { border: 'green.600', accent: 'green.300', bg: 'rgba(34, 197, 94, 0.06)' },
  sla: { border: 'purple.600', accent: 'purple.300', bg: 'rgba(168, 85, 247, 0.06)' },
  infrastructure: { border: 'orange.600', accent: 'orange.300', bg: 'rgba(249, 115, 22, 0.06)' },
  compatibility: { border: 'cyan.600', accent: 'cyan.300', bg: 'rgba(6, 182, 212, 0.06)' },
}

const TIER_DOTS: Record<number, string> = { 1: 'purple.400', 2: 'blue.400', 3: 'gray.500' }

const BLIND_SPOT_ICON: Record<string, any> = {
  high_contradictions: FiAlertTriangle,
  value_contradiction: FiSlash,
  scope_variation: FiInfo,
  low_coverage: FiAlertCircle,
  missing_article: FiEdit3,
}

const BLIND_SPOT_COLOR: Record<string, string> = {
  high_contradictions: 'orange.400',
  value_contradiction: 'red.400',
  scope_variation: 'blue.400',
  low_coverage: 'yellow.400',
  missing_article: 'blue.400',
}

/** Formatte un doc_type brut en label lisible */
function formatDocType(dtype: string): string {
  const map: Record<string, string> = {
    research_article: 'articles de recherche',
    guideline: 'guidelines',
    regulation: 'textes reglementaires',
    review: 'revues',
    technical_report: 'rapports techniques',
    presentation: 'presentations',
    white_paper: 'livres blancs',
    case_study: 'etudes de cas',
  }
  return map[dtype] || dtype.replace(/_/g, ' ')
}

export default function WikiHomePage() {
  const [data, setData] = useState<HomeData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function fetchHome() {
      const res = await api.wiki.home()
      if (res.success && res.data) {
        setData(res.data as HomeData)
      }
      setLoading(false)
    }
    fetchHome()
  }, [])

  if (loading) {
    return (
      <Container maxW="7xl" py={8} mt={16}>
        <HStack justify="center" py={20}>
          <Spinner size="lg" color="brand.400" />
          <Text color="var(--text-muted)">Chargement de l'Atlas...</Text>
        </HStack>
      </Container>
    )
  }

  if (!data) {
    return (
      <Container maxW="7xl" py={8} mt={16}>
        <Box bg="var(--bg-secondary)" rounded="xl" p={8} textAlign="center" borderWidth="1px" borderColor="var(--border-default)">
          <Text color="var(--text-muted)">Impossible de charger les donnees de l'Atlas.</Text>
        </Box>
      </Container>
    )
  }

  const { corpus_stats, domain_context, corpus_narrative, knowledge_domains, recent_articles } = data
  const activeDomains = knowledge_domains.filter(d => d.article_count > 0 || d.doc_count > 0)
  const startHere = data.start_here || []
  const blindSpots = data.blind_spots || []
  const contradictionCount = data.contradiction_count || 0

  // Construire le paragraphe narratif dynamique — ton editorial, pas un listing de stats
  const narrativeText = (() => {
    if (!corpus_narrative || corpus_narrative.top_entities.length === 0) return ''

    const parts: string[] = []
    const topEntities = corpus_narrative.top_entities
    const docTypes = corpus_narrative.doc_type_distribution
    const articlesWithCount = topEntities.filter(e => e.has_article)

    // Phrase d'ouverture contextualisee
    if (docTypes.length > 0) {
      const docTypeLabels = docTypes.slice(0, 3).map(d => formatDocType(d.type))
      parts.push(
        `Parcourez les articles de synthese generes a partir de ${corpus_stats.total_documents} documents sources (${docTypeLabels.join(', ')}).`
      )
    } else {
      parts.push(
        `Parcourez les articles de synthese generes a partir de ${corpus_stats.total_documents} documents sources.`
      )
    }

    // Description thematique avec les concepts principaux
    if (topEntities.length >= 3) {
      const conceptNames = topEntities.slice(0, 5).map(e => e.name)
      // Construire une phrase naturelle : "A, B, C et D"
      const lastConcept = conceptNames.pop()
      const conceptList = conceptNames.length > 0
        ? `${conceptNames.join(', ')} et ${lastConcept}`
        : lastConcept
      parts.push(
        `Les sujets les plus documentes incluent ${conceptList}.`
      )
    }

    // Couverture editoriale
    if (corpus_stats.total_articles > 0) {
      parts.push(
        `${corpus_stats.total_articles} articles couvrent ${corpus_stats.coverage_pct}% des concepts identifies dans le corpus.`
      )
    }

    return parts.join(' ')
  })()

  return (
    <Container maxW="7xl" py={8} mt={16}>
      {/* Hero — Introduction editoriale contextuelle */}
      <Box mb={10}>
        <Heading size="lg" color="var(--text-primary)" mb={4}>
          Knowledge Atlas
        </Heading>

        {/* Resume editorial si domain_context disponible */}
        {domain_context?.domain_summary && (
          <Text color="var(--text-secondary)" fontSize="md" lineHeight="tall" maxW="800px" mb={3}>
            {domain_context.domain_summary}
          </Text>
        )}

        {/* Paragraphe narratif dynamique */}
        {narrativeText ? (
          <Text color="var(--text-muted)" fontSize="sm" lineHeight="tall" maxW="800px" mb={5}>
            {narrativeText}
          </Text>
        ) : !domain_context?.domain_summary ? (
          <Text color="var(--text-secondary)" fontSize="md" lineHeight="tall" maxW="800px" mb={5}>
            Bienvenue dans l'Atlas de connaissances. Explorez les domaines ci-dessous pour
            acceder aux articles de synthese generes a partir de la base documentaire.
          </Text>
        ) : null}

        {/* Indicateurs + barre de couverture */}
        <Flex gap={6} wrap="wrap" mb={4}>
          <HStack spacing={2}>
            <Icon as={FiFileText} color="var(--text-muted)" boxSize={4} />
            <Text color="var(--text-muted)" fontSize="sm">
              <Text as="span" color="var(--text-primary)" fontWeight="semibold">{corpus_stats.total_documents}</Text> documents analyses
            </Text>
          </HStack>
          <HStack spacing={2}>
            <Icon as={FiDatabase} color="var(--text-muted)" boxSize={4} />
            <Text color="var(--text-muted)" fontSize="sm">
              <Text as="span" color="var(--text-primary)" fontWeight="semibold">{corpus_stats.total_claims.toLocaleString()}</Text> faits extraits
            </Text>
          </HStack>
          {corpus_stats.total_articles > 0 && (
            <HStack spacing={2}>
              <Icon as={FiLayers} color="var(--text-muted)" boxSize={4} />
              <Text color="var(--text-muted)" fontSize="sm">
                <Link as={NextLink} href="/wiki/articles" color="var(--text-primary)" fontWeight="semibold">
                  {corpus_stats.total_articles} articles
                </Link> de synthese disponibles
              </Text>
            </HStack>
          )}
          {contradictionCount > 0 && (
            <HStack spacing={2}>
              <Icon as={FiAlertTriangle} color="orange.400" boxSize={4} />
              <Text color="var(--text-muted)" fontSize="sm">
                <Text as="span" color="orange.400" fontWeight="semibold">{contradictionCount}</Text> contradictions detectees
              </Text>
            </HStack>
          )}
        </Flex>

        {/* Barre de progression couverture */}
        {corpus_stats.coverage_pct > 0 && corpus_stats.total_entities > 0 && (
          <Box maxW="400px">
            <HStack justify="space-between" mb={1}>
              <Text color="var(--text-muted)" fontSize="xs">Couverture du corpus</Text>
              <Text color="var(--text-primary)" fontSize="xs" fontWeight="semibold">{corpus_stats.coverage_pct}%</Text>
            </HStack>
            <Progress
              value={corpus_stats.coverage_pct}
              size="xs"
              rounded="full"
              bg="var(--bg-secondary)"
              sx={{
                '& > div': {
                  background: corpus_stats.coverage_pct > 50
                    ? 'linear-gradient(90deg, #8B5CF6, #6366F1)'
                    : 'linear-gradient(90deg, #F59E0B, #EF4444)',
                },
              }}
            />
          </Box>
        )}
      </Box>

      {/* Ce que couvre ce corpus — Top concepts en badges cliquables */}
      {corpus_narrative && corpus_narrative.top_entities.length > 0 && (
        <Box mb={10}>
          <HStack spacing={2} mb={4}>
            <Icon as={FiTarget} color="brand.400" boxSize={4} />
            <Text color="var(--text-muted)" fontSize="xs" fontWeight="semibold" textTransform="uppercase" letterSpacing="wider">
              Ce que couvre ce corpus
            </Text>
          </HStack>
          <Wrap spacing={3}>
            {corpus_narrative.top_entities.slice(0, 10).map((entity) => {
              const maxClaims = corpus_narrative!.top_entities[0]?.claim_count || 1
              const ratio = entity.claim_count / maxClaims
              // Taille variable selon le poids
              const fontSize = ratio > 0.6 ? 'md' : ratio > 0.3 ? 'sm' : 'xs'
              const px = ratio > 0.6 ? 4 : ratio > 0.3 ? 3 : 2
              const py = ratio > 0.6 ? 2 : 1.5

              if (entity.has_article && entity.slug) {
                return (
                  <WrapItem key={entity.name}>
                    <Link as={NextLink} href={`/wiki/${entity.slug}`} _hover={{ textDecoration: 'none' }}>
                      <Box
                        px={px}
                        py={py}
                        rounded="lg"
                        bg="rgba(99, 102, 241, 0.08)"
                        borderWidth="1px"
                        borderColor="rgba(99, 102, 241, 0.3)"
                        _hover={{
                          borderColor: 'brand.400',
                          transform: 'translateY(-1px)',
                          boxShadow: '0 2px 8px rgba(99, 102, 241, 0.2)',
                        }}
                        transition="all 0.15s"
                        cursor="pointer"
                      >
                        <Text color="var(--text-primary)" fontSize={fontSize} fontWeight="medium">
                          {entity.name}
                        </Text>
                        <Text color="var(--text-muted)" fontSize="xs">
                          {entity.claim_count} faits
                        </Text>
                      </Box>
                    </Link>
                  </WrapItem>
                )
              }

              return (
                <WrapItem key={entity.name}>
                  <Tooltip label="Article en attente de generation" placement="top" hasArrow>
                    <Box
                      px={px}
                      py={py}
                      rounded="lg"
                      bg="var(--bg-secondary)"
                      borderWidth="1px"
                      borderColor="var(--border-default)"
                      opacity={0.6}
                    >
                      <Text color="var(--text-muted)" fontSize={fontSize} fontWeight="medium">
                        {entity.name}
                      </Text>
                      <Text color="var(--text-muted)" fontSize="xs">
                        {entity.claim_count} faits
                      </Text>
                    </Box>
                  </Tooltip>
                </WrapItem>
              )
            })}
          </Wrap>
        </Box>
      )}

      {/* Commencer par — Articles Tier 1 */}
      {startHere.length > 0 && (
        <Box mb={10}>
          <HStack spacing={2} mb={4}>
            <Icon as={FiStar} color="purple.400" boxSize={4} />
            <Text color="var(--text-muted)" fontSize="xs" fontWeight="semibold" textTransform="uppercase" letterSpacing="wider">
              Commencer par
            </Text>
          </HStack>
          <SimpleGrid columns={{ base: 1, sm: 2, md: 3, lg: 5 }} spacing={3}>
            {startHere.map((item) => (
              <Link
                key={item.slug}
                as={NextLink}
                href={`/wiki/${item.slug}`}
                _hover={{ textDecoration: 'none' }}
              >
                <HStack
                  p={3}
                  bg="rgba(168, 85, 247, 0.06)"
                  rounded="lg"
                  borderWidth="1px"
                  borderColor="purple.800"
                  spacing={3}
                  _hover={{
                    borderColor: 'purple.500',
                    transform: 'translateY(-2px)',
                    boxShadow: '0 4px 12px rgba(168, 85, 247, 0.15)',
                  }}
                  transition="all 0.2s"
                >
                  <Icon as={FiStar} color="purple.400" boxSize={4} flexShrink={0} />
                  <Text color="var(--text-primary)" fontSize="sm" fontWeight="medium" noOfLines={2}>
                    {item.title}
                  </Text>
                </HStack>
              </Link>
            ))}
          </SimpleGrid>
        </Box>
      )}

      {/* Domaines de connaissance — approche editoriale */}
      <VStack spacing={6} align="stretch" mb={10}>
        <Text color="var(--text-muted)" fontSize="xs" fontWeight="semibold" textTransform="uppercase" letterSpacing="wider">
          Explorer par domaine
        </Text>

        {activeDomains.map((domain) => {
          const colors = DOMAIN_COLORS[domain.domain_key] || DOMAIN_COLORS.compliance
          // Utiliser domain.question si disponible, sinon construire dynamiquement
          const description = domain.question
            ? domain.question
            : `${domain.article_count} article${domain.article_count !== 1 ? 's' : ''}, ${domain.doc_count} document${domain.doc_count !== 1 ? 's' : ''} sources`
          return (
            <Box
              key={domain.domain_key}
              bg={colors.bg}
              rounded="xl"
              p={6}
              borderWidth="1px"
              borderColor={colors.border}
              borderLeftWidth="4px"
            >
              {/* Titre + description editoriale */}
              <HStack spacing={3} mb={2} align="baseline">
                <Link as={NextLink} href={`/wiki/domain/${domain.domain_key}`} _hover={{ textDecoration: 'none' }}>
                  <Heading size="md" color="var(--text-primary)" _hover={{ color: 'brand.400' }} transition="color 0.15s">
                    {domain.name}
                  </Heading>
                </Link>
                {domain.article_count > 0 && (
                  <Badge colorScheme="gray" fontSize="xs" fontWeight="normal">
                    {domain.article_count} article{domain.article_count > 1 ? 's' : ''}
                  </Badge>
                )}
              </HStack>

              <Text color="var(--text-secondary)" fontSize="sm" lineHeight="tall" mb={4} maxW="700px">
                {description}
              </Text>

              {/* Sous-domaines comme contexte */}
              {domain.sub_domains.length > 0 && (
                <Wrap spacing={2} mb={4}>
                  {domain.sub_domains.map((sub, i) => (
                    <WrapItem key={i}>
                      <Badge
                        variant="subtle"
                        colorScheme="gray"
                        fontSize="xs"
                        px={2}
                        py={0.5}
                        rounded="md"
                      >
                        {sub}
                      </Badge>
                    </WrapItem>
                  ))}
                </Wrap>
              )}

              {/* Articles — les points d'entree cliquables */}
              {domain.articles.length > 0 ? (
                <Box>
                  <Text color="var(--text-muted)" fontSize="xs" mb={2} fontWeight="medium">
                    Articles disponibles :
                  </Text>
                  <Wrap spacing={2}>
                    {domain.articles.map((article) => (
                      <WrapItem key={article.slug}>
                        <Link
                          as={NextLink}
                          href={`/wiki/${article.slug}`}
                          _hover={{ textDecoration: 'none' }}
                        >
                          <HStack
                            bg="var(--bg-secondary)"
                            px={3}
                            py={1.5}
                            rounded="md"
                            spacing={2}
                            borderWidth="1px"
                            borderColor="var(--border-default)"
                            _hover={{ borderColor: colors.accent, transform: 'translateY(-1px)' }}
                            transition="all 0.15s"
                          >
                            <Box w="6px" h="6px" rounded="full" bg={TIER_DOTS[article.tier] || 'gray.500'} />
                            <Text color="var(--text-primary)" fontSize="sm">{article.title}</Text>
                          </HStack>
                        </Link>
                      </WrapItem>
                    ))}
                    {domain.article_count > domain.articles.length && (
                      <WrapItem>
                        <Link as={NextLink} href="/wiki/articles" color={colors.accent} fontSize="sm" px={2} py={1.5}>
                          +{domain.article_count - domain.articles.length} autres <Icon as={FiChevronRight} boxSize={3} />
                        </Link>
                      </WrapItem>
                    )}
                  </Wrap>
                </Box>
              ) : (
                <Text color="var(--text-muted)" fontSize="sm" fontStyle="italic">
                  Les articles de ce domaine sont en cours de generation.
                </Text>
              )}
            </Box>
          )
        })}
      </VStack>

      {/* Zones a surveiller — Blind Spots */}
      {blindSpots.length > 0 && (
        <Box
          mb={10}
          bg="rgba(251, 191, 36, 0.04)"
          rounded="xl"
          p={6}
          borderWidth="1px"
          borderColor="rgba(251, 191, 36, 0.2)"
        >
          <HStack spacing={2} mb={4}>
            <Icon as={FiAlertTriangle} color="yellow.400" boxSize={4} />
            <Text color="yellow.400" fontSize="xs" fontWeight="semibold" textTransform="uppercase" letterSpacing="wider">
              Zones a surveiller
            </Text>
          </HStack>
          <VStack spacing={3} align="stretch">
            {blindSpots.map((spot, i) => {
              const SpotIcon = BLIND_SPOT_ICON[spot.type] || FiAlertCircle
              const color = BLIND_SPOT_COLOR[spot.type] || 'yellow.400'
              return (
                <HStack key={i} spacing={3} align="start">
                  <Icon as={SpotIcon} color={color} boxSize={4} mt={0.5} flexShrink={0} />
                  <Box>
                    <Text color="var(--text-primary)" fontSize="sm" fontWeight="medium">
                      {spot.domain}
                    </Text>
                    <Text color="var(--text-muted)" fontSize="xs">
                      {spot.detail}
                    </Text>
                  </Box>
                </HStack>
              )
            })}
          </VStack>
        </Box>
      )}

      {/* Articles recents */}
      {recent_articles.length > 0 && (
        <Box bg="var(--bg-secondary)" rounded="xl" p={6} borderWidth="1px" borderColor="var(--border-default)">
          <HStack mb={4} justify="space-between">
            <HStack>
              <Icon as={FiClock} color="var(--text-muted)" boxSize={4} />
              <Text color="var(--text-muted)" fontSize="xs" fontWeight="semibold" textTransform="uppercase">
                Derniers articles ajoutes
              </Text>
            </HStack>
            <Link as={NextLink} href="/wiki/articles" color="brand.300" fontSize="xs">
              Tous les articles <Icon as={FiChevronRight} boxSize={3} />
            </Link>
          </HStack>
          <SimpleGrid columns={{ base: 1, md: 2, lg: 3 }} spacing={3}>
            {recent_articles.map((a) => (
              <Link
                key={a.slug}
                as={NextLink}
                href={`/wiki/${a.slug}`}
                _hover={{ textDecoration: 'none' }}
              >
                <HStack
                  p={3}
                  rounded="md"
                  _hover={{ bg: 'var(--bg-hover)' }}
                  transition="background 0.15s"
                  spacing={3}
                >
                  <Icon as={FiBook} color="brand.400" boxSize={4} flexShrink={0} />
                  <Box>
                    <Text color="var(--text-primary)" fontSize="sm" fontWeight="medium">{a.title}</Text>
                    {a.updated_at && (
                      <Text color="var(--text-muted)" fontSize="xs">
                        {new Date(a.updated_at).toLocaleDateString('fr-FR')}
                      </Text>
                    )}
                  </Box>
                </HStack>
              </Link>
            ))}
          </SimpleGrid>
        </Box>
      )}
    </Container>
  )
}
