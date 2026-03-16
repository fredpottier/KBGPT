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
} from '@chakra-ui/react'
import NextLink from 'next/link'
import {
  FiBook,
  FiChevronRight,
  FiClock,
  FiFileText,
  FiDatabase,
  FiLayers,
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

interface HomeData {
  corpus_stats: CorpusStats
  domain_context?: DomainContext | null
  knowledge_domains: KnowledgeDomain[]
  recent_articles: RecentArticle[]
}

const DOMAIN_COLORS: Record<string, { border: string; accent: string; bg: string; icon: string }> = {
  compliance: { border: 'blue.600', accent: 'blue.300', bg: 'rgba(59, 130, 246, 0.06)', icon: '\\u2696' },
  security: { border: 'red.600', accent: 'red.300', bg: 'rgba(239, 68, 68, 0.06)', icon: '\\uD83D\\uDD12' },
  operations: { border: 'green.600', accent: 'green.300', bg: 'rgba(34, 197, 94, 0.06)', icon: '\\u2699' },
  sla: { border: 'purple.600', accent: 'purple.300', bg: 'rgba(168, 85, 247, 0.06)', icon: '\\uD83D\\uDCCA' },
  infrastructure: { border: 'orange.600', accent: 'orange.300', bg: 'rgba(249, 115, 22, 0.06)', icon: '\\uD83C\\uDFD7' },
  compatibility: { border: 'cyan.600', accent: 'cyan.300', bg: 'rgba(6, 182, 212, 0.06)', icon: '\\uD83D\\uDD17' },
}

const DOMAIN_DESCRIPTIONS: Record<string, string> = {
  compliance: 'Protection des donnees, cadre juridique europeen, obligations legales des organisations et droits des personnes concernees.',
  security: 'Cybersecurite, menaces et vulnerabilites, mesures de protection, frameworks de securite et bonnes pratiques.',
  operations: 'Gestion operationnelle, processus metier, gouvernance et organisation des activites.',
  sla: 'Niveaux de service, engagements contractuels, metriques de performance et garanties.',
  infrastructure: 'Architecture technique, systemes d\'information, plateformes et composants technologiques.',
  compatibility: 'Interoperabilite, standards techniques, integration entre systemes et conformite aux normes.',
}

const TIER_DOTS: Record<number, string> = { 1: 'purple.400', 2: 'blue.400', 3: 'gray.500' }

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

  const { corpus_stats, domain_context, knowledge_domains, recent_articles } = data
  const activeDomains = knowledge_domains.filter(d => d.article_count > 0 || d.doc_count > 0)

  return (
    <Container maxW="7xl" py={8} mt={16}>
      {/* Hero — Introduction editoriale */}
      <Box mb={10}>
        <Heading size="lg" color="var(--text-primary)" mb={4}>
          Knowledge Atlas
        </Heading>

        {domain_context?.domain_summary ? (
          <Text color="var(--text-secondary)" fontSize="md" lineHeight="tall" maxW="800px" mb={5}>
            {domain_context.domain_summary}
          </Text>
        ) : (
          <Text color="var(--text-secondary)" fontSize="md" lineHeight="tall" maxW="800px" mb={5}>
            Bienvenue dans l'Atlas de connaissances. Explorez les domaines ci-dessous pour
            acceder aux articles de synthese generes a partir de la base documentaire.
          </Text>
        )}

        {/* Indicateurs discrets */}
        <Flex gap={6} wrap="wrap">
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
        </Flex>
      </Box>

      {/* Domaines de connaissance — approche editoriale */}
      <VStack spacing={6} align="stretch" mb={10}>
        <Text color="var(--text-muted)" fontSize="xs" fontWeight="semibold" textTransform="uppercase" letterSpacing="wider">
          Explorer par domaine
        </Text>

        {activeDomains.map((domain) => {
          const colors = DOMAIN_COLORS[domain.domain_key] || DOMAIN_COLORS.compliance
          const description = DOMAIN_DESCRIPTIONS[domain.domain_key] || domain.question
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
                <Heading size="md" color="var(--text-primary)">{domain.name}</Heading>
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
