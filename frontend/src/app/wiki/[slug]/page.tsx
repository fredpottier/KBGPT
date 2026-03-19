'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { useParams } from 'next/navigation'
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
  Tooltip,
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  Link,
} from '@chakra-ui/react'
import NextLink from 'next/link'
import { Button } from '@chakra-ui/react'
import { FiBook, FiAlertTriangle, FiInfo, FiChevronRight, FiMessageCircle, FiCompass, FiLink, FiRefreshCw } from 'react-icons/fi'
import { api } from '@/lib/api'
import { useAuth } from '@/contexts/AuthContext'
import WikiMarkdown from '@/components/wiki/WikiMarkdown'
import ConceptMap from '@/components/wiki/ConceptMap'
import CoverageBars from '@/components/wiki/CoverageBars'
// import ClaimExplorer from '@/components/wiki/ClaimExplorer'  // Retiré : format claims pas assez lisible pour le lecteur

interface SourceDetail {
  doc_id?: string
  doc_title: string
  doc_type?: string | null
  unit_count: number
  contribution_pct: number
}

interface ArticleDetail {
  slug: string
  title: string
  language: string
  entity_type: string
  category_key: string
  markdown: string
  linked_markdown?: string | null
  outgoing_links?: string[]
  linked_at?: string | null
  sections_count: number
  total_citations: number
  generation_confidence: number
  all_gaps: string[]
  source_count: number
  unit_count: number
  source_details: SourceDetail[]
  related_concepts: { entity_name: string; entity_type: string; co_occurrence_count: number }[]
  resolution_method: string
  resolution_confidence: number
  importance_score: number
  importance_tier: number
  created_at?: string
  updated_at?: string
  reading_path?: { slug: string; title: string; importance_tier: number; concept_name: string }[]
  linked_articles?: { slug: string; title: string; importance_tier: number; shared_concepts: number }[]
}

const TIER_LABELS: Record<number, { label: string; color: string }> = {
  1: { label: 'Portail', color: 'purple' },
  2: { label: 'Principal', color: 'blue' },
  3: { label: 'Spécifique', color: 'gray' },
}

export default function WikiArticlePage() {
  const params = useParams()
  const slug = params?.slug as string
  const [article, setArticle] = useState<ArticleDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [regenerating, setRegenerating] = useState(false)
  const [regenProgress, setRegenProgress] = useState('')
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const { isAdmin } = useAuth()

  const fetchArticle = useCallback(async () => {
    if (!slug) return
    setLoading(true)
    const res = await api.wiki.getArticle(slug)
    if (res.success && res.data) {
      setArticle(res.data as ArticleDetail)
    } else {
      setError(res.error || 'Article introuvable')
    }
    setLoading(false)
  }, [slug])

  useEffect(() => {
    fetchArticle()
  }, [fetchArticle])

  useEffect(() => {
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current)
    }
  }, [])

  const handleRegenerate = async () => {
    if (!article || regenerating) return
    setRegenerating(true)
    setRegenProgress('Lancement...')

    const res = await api.wiki.generate(article.title, article.language || 'français', true)
    if (!res.success || !res.data) {
      setRegenProgress(`Erreur : ${res.error || 'échec'}`)
      setRegenerating(false)
      return
    }

    const jobId = (res.data as { job_id: string }).job_id
    setRegenProgress('Génération en cours...')

    pollingRef.current = setInterval(async () => {
      const statusRes = await api.wiki.status(jobId)
      if (!statusRes.success || !statusRes.data) return

      const data = statusRes.data as { status: string; progress?: string; article_slug?: string }
      setRegenProgress(data.progress || data.status)

      if (data.status === 'completed' || data.status === 'completed_with_warnings') {
        if (pollingRef.current) clearInterval(pollingRef.current)
        pollingRef.current = null
        setRegenProgress('Rechargement...')
        await fetchArticle()
        setRegenerating(false)
        setRegenProgress('')
      } else if (data.status === 'failed') {
        if (pollingRef.current) clearInterval(pollingRef.current)
        pollingRef.current = null
        setRegenProgress('Échec de la régénération')
        setRegenerating(false)
      }
    }, 2000)
  }

  const confidenceColor = (conf: number) => {
    if (conf >= 0.7) return 'green'
    if (conf >= 0.5) return 'yellow'
    return 'red'
  }

  if (loading) {
    return (
      <Container maxW="7xl" py={8} mt={16}>
        <HStack justify="center" py={20}>
          <Spinner size="lg" color="brand.400" />
          <Text color="text.muted">Chargement de l'article...</Text>
        </HStack>
      </Container>
    )
  }

  if (error || !article) {
    return (
      <Container maxW="7xl" py={8} mt={16}>
        <Box bg="surface.default" rounded="xl" p={8} textAlign="center" borderWidth="1px" borderColor="border.default">
          <Icon as={FiAlertTriangle} boxSize={8} color="orange.400" mb={4} />
          <Heading size="md" color="text.primary" mb={2}>Article introuvable</Heading>
          <Text color="text.muted" mb={4}>{error || `Aucun article pour "${slug}"`}</Text>
          <HStack justify="center" spacing={4}>
            <Link as={NextLink} href="/wiki" color="brand.300" fontSize="sm">
              Retour à l'accueil
            </Link>
            <Link as={NextLink} href={`/wiki/generate?concept=${encodeURIComponent(slug.replace(/[_-]/g, ' '))}`} color="brand.300" fontSize="sm">
              Générer cet article
            </Link>
          </HStack>
        </Box>
      </Container>
    )
  }

  const tierInfo = TIER_LABELS[article.importance_tier] || TIER_LABELS[3]

  // Filtrer les sections redondantes avec le sidebar (sources, lacunes, meta header)
  const cleanMarkdown = (md: string): string => {
    // Retirer la ligne meta "Article généré par OSMOSE — ..."
    let cleaned = md.replace(/^.*Article généré par OSMOSE.*$/gm, '')
    // Retirer le titre H1 (déjà affiché dans le header)
    cleaned = cleaned.replace(/^#\s+.+$/m, '')
    // Retirer la section "Sources documentaires" (tout jusqu'à la prochaine section ## ou fin)
    cleaned = cleaned.replace(/##?\s*Sources?\s+documentaires?\s*\n[\s\S]*?(?=\n##?\s|\n*$)/, '')
    // Retirer la section "Lacunes identifiées"
    cleaned = cleaned.replace(/##?\s*Lacunes?\s+identifiée?s?\s*\n[\s\S]*?(?=\n##?\s|\n*$)/, '')
    // Nettoyer les lignes vides multiples
    cleaned = cleaned.replace(/\n{4,}/g, '\n\n')
    return cleaned.trim()
  }

  return (
    <Container maxW="7xl" py={8} mt={16}>
      {/* Breadcrumb */}
      <Breadcrumb spacing="8px" separator={<FiChevronRight color="gray" />} mb={4}>
        <BreadcrumbItem>
          <BreadcrumbLink as={NextLink} href="/wiki" color="text.muted" fontSize="sm">Atlas</BreadcrumbLink>
        </BreadcrumbItem>
        <BreadcrumbItem>
          <BreadcrumbLink as={NextLink} href="/wiki/articles" color="text.muted" fontSize="sm">Articles</BreadcrumbLink>
        </BreadcrumbItem>
        <BreadcrumbItem isCurrentPage>
          <Text color="text.secondary" fontSize="sm">{article.title}</Text>
        </BreadcrumbItem>
      </Breadcrumb>

      {/* Header */}
      <HStack mb={6} spacing={3} align="center" flexWrap="wrap">
        <Icon as={FiBook} boxSize={6} color="brand.400" />
        <Heading size="lg" color="text.primary">{article.title}</Heading>
        <Badge colorScheme={tierInfo.color} fontSize="xs">{tierInfo.label}</Badge>
        <Badge colorScheme="gray" fontSize="xs">{article.entity_type}</Badge>
        <HStack ml="auto" spacing={2}>
          {isAdmin() && (
            <Tooltip label={regenProgress || 'Régénérer cet article avec les dernières données du KG'} hasArrow>
              <Button
                size="sm"
                leftIcon={<FiRefreshCw />}
                variant="outline"
                colorScheme="orange"
                borderColor="orange.500"
                color="orange.400"
                _hover={{ bg: 'rgba(237, 137, 54, 0.1)' }}
                onClick={handleRegenerate}
                isLoading={regenerating}
                loadingText={regenProgress || 'Régénération...'}
              >
                Régénérer
              </Button>
            </Tooltip>
          )}
          <Button
            as={NextLink}
            href={`/chat?q=${encodeURIComponent(`Que sait le corpus sur ${article.title} ?`)}`}
            size="sm"
            leftIcon={<FiMessageCircle />}
            variant="outline"
            colorScheme="brand"
            borderColor="brand.500"
            color="brand.400"
            _hover={{ bg: 'rgba(99, 102, 241, 0.1)' }}
          >
            Poser une question sur {article.title}
          </Button>
        </HStack>
      </HStack>

      {/* Reading Path */}
      {article.reading_path && article.reading_path.length > 0 && (
        <Box
          mb={6}
          bg="rgba(99, 102, 241, 0.06)"
          rounded="xl"
          p={5}
          borderWidth="1px"
          borderColor="rgba(99, 102, 241, 0.2)"
        >
          <HStack spacing={2} mb={3}>
            <Icon as={FiCompass} color="brand.400" boxSize={4} />
            <Text color="brand.400" fontSize="sm" fontWeight="semibold">
              Pour comprendre ce sujet, commencez par
            </Text>
          </HStack>
          <VStack spacing={2} align="stretch">
            {article.reading_path.map((item, i) => {
              const tierInfo = TIER_LABELS[item.importance_tier] || TIER_LABELS[3]
              return (
                <Link key={item.slug} as={NextLink} href={`/wiki/${item.slug}`} _hover={{ textDecoration: 'none' }}>
                  <HStack
                    spacing={3}
                    p={2}
                    rounded="md"
                    _hover={{ bg: 'rgba(99, 102, 241, 0.08)' }}
                    transition="background 0.15s"
                  >
                    <Text color="brand.400" fontSize="sm" fontWeight="bold" w="20px" textAlign="center">
                      {i + 1}.
                    </Text>
                    <Text color="text.primary" fontSize="sm" fontWeight="medium">
                      {item.title}
                    </Text>
                    <Badge colorScheme={tierInfo.color} fontSize="2xs" variant="subtle">
                      {tierInfo.label}
                    </Badge>
                  </HStack>
                </Link>
              )
            })}
          </VStack>
        </Box>
      )}

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
          <WikiMarkdown content={cleanMarkdown(
            // Utiliser linked_markdown sauf s'il est tronqué (perte > 20% = sections manquantes)
            article.linked_markdown && article.linked_markdown.length >= article.markdown.length * 0.80
              ? article.linked_markdown
              : article.markdown
          )} />
        </Box>

        {/* Sidebar */}
        <Box w={{ base: 'full', lg: '320px' }} flexShrink={0}>
          <VStack spacing={4} align="stretch">
            {/* Confiance */}
            <Box bg="surface.default" rounded="xl" p={4} borderWidth="1px" borderColor="border.default">
              <Text color="text.muted" fontSize="xs" mb={2} fontWeight="semibold" textTransform="uppercase">
                Confiance
              </Text>
              <Tooltip label="Signal d'exploitation : mesure la couverture et cohérence des preuves" hasArrow>
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

            {/* Stats rapides */}
            <Box bg="surface.default" rounded="xl" p={4} borderWidth="1px" borderColor="border.default">
              <Text color="text.muted" fontSize="xs" mb={3} fontWeight="semibold" textTransform="uppercase">
                Statistiques
              </Text>
              <VStack spacing={2} align="stretch">
                {([
                  ['Sources', article.source_count, 'Nombre de documents d\'origine dans lesquels des informations ont été trouvées'],
                  ['Passages', article.unit_count, 'Nombre d\'extraits de ces documents qui ont servi à rédiger cet article'],
                  ['Sections', article.sections_count, 'Nombre de chapitres dans cet article (ex : Vue d\'ensemble, Définition, Obligations...)'],
                  ['Citations', article.total_citations, 'Nombre de fois où un document source est cité dans le texte entre crochets [...]'],
                ] as [string, number, string][]).map(([label, value, tooltip]) => (
                  <Tooltip key={label} label={tooltip} hasArrow placement="left" fontSize="xs">
                    <HStack justify="space-between" cursor="help">
                      <Text color="text.muted" fontSize="sm">{label}</Text>
                      <Text color="text.primary" fontWeight="medium" fontSize="sm">{value}</Text>
                    </HStack>
                  </Tooltip>
                ))}
              </VStack>
            </Box>

            {/* Concept Map — filtre les concepts réellement mentionnés dans l'article */}
            <ConceptMap
              centralConcept={article.title}
              relatedConcepts={(article.related_concepts || []).filter(
                rc => article.markdown.toLowerCase().includes(rc.entity_name.toLowerCase())
              )}
            />

            {/* Articles lies */}
            {article.linked_articles && article.linked_articles.length > 0 && (
              <Box bg="surface.default" rounded="xl" p={4} borderWidth="1px" borderColor="border.default">
                <HStack spacing={2} mb={3}>
                  <Icon as={FiLink} color="brand.400" boxSize={3.5} />
                  <Text color="text.muted" fontSize="xs" fontWeight="semibold" textTransform="uppercase">
                    Articles lies
                  </Text>
                </HStack>
                <VStack spacing={1.5} align="stretch">
                  {article.linked_articles.map((la) => {
                    const tierInfo = TIER_LABELS[la.importance_tier] || TIER_LABELS[3]
                    return (
                      <Link key={la.slug} as={NextLink} href={`/wiki/${la.slug}`} _hover={{ textDecoration: 'none' }}>
                        <HStack
                          spacing={2}
                          p={2}
                          rounded="md"
                          _hover={{ bg: 'whiteAlpha.50' }}
                          transition="background 0.15s"
                        >
                          <Box w="5px" h="5px" rounded="full" bg={tierInfo.color === 'purple' ? 'purple.400' : tierInfo.color === 'blue' ? 'blue.400' : 'gray.500'} flexShrink={0} />
                          <Box flex={1} minW={0}>
                            <Text color="text.primary" fontSize="xs" fontWeight="medium" noOfLines={1}>
                              {la.title}
                            </Text>
                            <Text color="text.muted" fontSize="2xs">
                              {la.shared_concepts} concept{la.shared_concepts > 1 ? 's' : ''} en commun
                            </Text>
                          </Box>
                        </HStack>
                      </Link>
                    )
                  })}
                </VStack>
              </Box>
            )}

            {/* Coverage Bars */}
            <CoverageBars sources={article.source_details || []} />

            {/* Lacunes */}
            {article.all_gaps.length > 0 && (
              <Box bg="surface.default" rounded="xl" p={4} borderWidth="1px" borderColor="border.default">
                <Text color="text.muted" fontSize="xs" mb={3} fontWeight="semibold" textTransform="uppercase">
                  Lacunes ({article.all_gaps.length})
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
                <Text color="text.muted" fontSize="xs">Langue : {article.language}</Text>
                <Text color="text.muted" fontSize="xs">Résolution : {article.resolution_method}</Text>
                <Text color="text.muted" fontSize="xs">
                  Score importance : {article.importance_score?.toFixed(1)}
                </Text>
                {article.updated_at && (
                  <Text color="text.muted" fontSize="xs">
                    Mis à jour : {new Date(article.updated_at).toLocaleString('fr-FR')}
                  </Text>
                )}
              </VStack>
            </Box>
          </VStack>
        </Box>
      </Flex>
    </Container>
  )
}
