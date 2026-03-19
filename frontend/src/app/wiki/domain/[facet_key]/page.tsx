'use client'

import { useState, useEffect } from 'react'
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
  Link,
  SimpleGrid,
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  Tooltip,
  Wrap,
  WrapItem,
} from '@chakra-ui/react'
import NextLink from 'next/link'
import {
  FiBook,
  FiChevronRight,
  FiDatabase,
  FiFileText,
  FiAlertTriangle,
  FiAlertCircle,
  FiEdit3,
  FiMessageCircle,
  FiLayers,
  FiInfo,
} from 'react-icons/fi'
import { api } from '@/lib/api'

interface DomainConcept {
  name: string
  entity_type: string
  claim_count: number
  doc_count: number
  article_slug?: string | null
  article_title?: string | null
  tier?: number | null
}

interface DomainArticle {
  slug: string
  title: string
  importance_tier: number
  importance_score: number
  confidence: number
  relevance: number
}

interface DomainDocument {
  doc_id: string
  claim_count: number
}

interface DomainStats {
  total_claims: number
  doc_count: number
  contradiction_count: number
  article_count: number
  gap_count: number
}

interface DomainGap {
  name: string
  entity_type: string
  claim_count: number
}

interface DomainQuestion {
  question: string
  concept: string
}

interface DomainData {
  facet_id: string
  name: string
  kind: string
  lifecycle: string
  doc_count: number
  question: string
  domain_key: string
  top_concepts: DomainConcept[]
  articles: DomainArticle[]
  documents: DomainDocument[]
  stats: DomainStats
  gaps: DomainGap[]
  suggested_questions: DomainQuestion[]
}

const KIND_LABELS: Record<string, { label: string; color: string }> = {
  domain: { label: 'Thematique', color: 'blue' },
  obligation: { label: 'Normatif', color: 'red' },
  capability: { label: 'Operationnel', color: 'green' },
  procedure: { label: 'Procedure', color: 'purple' },
  risk: { label: 'Risque', color: 'orange' },
  limitation: { label: 'Limitation', color: 'yellow' },
}

const TIER_LABELS: Record<number, { label: string; color: string }> = {
  1: { label: 'Portail', color: 'purple' },
  2: { label: 'Principal', color: 'blue' },
  3: { label: 'Specifique', color: 'gray' },
}

export default function DomainPage() {
  const params = useParams()
  const facetKey = params?.facet_key as string
  const [data, setData] = useState<DomainData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    async function fetchDomain() {
      if (!facetKey) return
      setLoading(true)
      const res = await api.wiki.domain(facetKey)
      if (res.success && res.data) {
        setData(res.data as DomainData)
      } else {
        setError(res.error || 'Domaine introuvable')
      }
      setLoading(false)
    }
    fetchDomain()
  }, [facetKey])

  if (loading) {
    return (
      <Container maxW="7xl" py={8} mt={16}>
        <HStack justify="center" py={20}>
          <Spinner size="lg" color="brand.400" />
          <Text color="text.muted">Chargement du domaine...</Text>
        </HStack>
      </Container>
    )
  }

  if (error || !data) {
    return (
      <Container maxW="7xl" py={8} mt={16}>
        <Box bg="surface.default" rounded="xl" p={8} textAlign="center" borderWidth="1px" borderColor="border.default">
          <Icon as={FiAlertTriangle} boxSize={8} color="orange.400" mb={4} />
          <Heading size="md" color="text.primary" mb={2}>Domaine introuvable</Heading>
          <Text color="text.muted" mb={4}>{error || `Aucun domaine pour "${facetKey}"`}</Text>
          <Link as={NextLink} href="/wiki" color="brand.300" fontSize="sm">
            Retour a l'Atlas
          </Link>
        </Box>
      </Container>
    )
  }

  const kindInfo = KIND_LABELS[data.kind] || KIND_LABELS.domain

  return (
    <Container maxW="7xl" py={8} mt={16}>
      {/* Breadcrumb */}
      <Breadcrumb spacing="8px" separator={<FiChevronRight color="gray" />} mb={4}>
        <BreadcrumbItem>
          <BreadcrumbLink as={NextLink} href="/wiki" color="text.muted" fontSize="sm">Atlas</BreadcrumbLink>
        </BreadcrumbItem>
        <BreadcrumbItem>
          <Text color="text.muted" fontSize="sm">Domaines</Text>
        </BreadcrumbItem>
        <BreadcrumbItem isCurrentPage>
          <Text color="text.secondary" fontSize="sm">{data.name}</Text>
        </BreadcrumbItem>
      </Breadcrumb>

      {/* Header */}
      <Box mb={8}>
        <HStack spacing={3} mb={3} align="center" flexWrap="wrap">
          <Icon as={FiLayers} boxSize={6} color="brand.400" />
          <Heading size="lg" color="text.primary">{data.name}</Heading>
          <Badge colorScheme={kindInfo.color} fontSize="xs">{kindInfo.label}</Badge>
          {data.lifecycle !== 'validated' && (
            <Badge colorScheme="yellow" fontSize="xs">{data.lifecycle}</Badge>
          )}
        </HStack>

        {data.question && (
          <Text color="text.secondary" fontSize="md" lineHeight="tall" mb={4} maxW="700px">
            {data.question}
          </Text>
        )}

        {/* Stats inline */}
        <Flex gap={5} wrap="wrap">
          <HStack spacing={2}>
            <Icon as={FiDatabase} color="text.muted" boxSize={3.5} />
            <Text color="text.muted" fontSize="sm">
              <Text as="span" color="text.primary" fontWeight="semibold">{data.stats.total_claims.toLocaleString()}</Text> claims
            </Text>
          </HStack>
          <HStack spacing={2}>
            <Icon as={FiFileText} color="text.muted" boxSize={3.5} />
            <Text color="text.muted" fontSize="sm">
              <Text as="span" color="text.primary" fontWeight="semibold">{data.stats.doc_count}</Text> documents
            </Text>
          </HStack>
          <HStack spacing={2}>
            <Icon as={FiBook} color="text.muted" boxSize={3.5} />
            <Text color="text.muted" fontSize="sm">
              <Text as="span" color="text.primary" fontWeight="semibold">{data.stats.article_count}</Text> articles
            </Text>
          </HStack>
          {data.stats.contradiction_count > 0 && (
            <HStack spacing={2}>
              <Icon as={FiAlertTriangle} color="orange.400" boxSize={3.5} />
              <Text color="text.muted" fontSize="sm">
                <Text as="span" color="orange.400" fontWeight="semibold">{data.stats.contradiction_count}</Text> contradictions
              </Text>
            </HStack>
          )}
        </Flex>
      </Box>

      <Flex gap={6} direction={{ base: 'column', lg: 'row' }}>
        {/* Colonne principale */}
        <Box flex={1} minW={0}>
          <VStack spacing={6} align="stretch">
            {/* Concepts principaux */}
            <Box bg="surface.default" rounded="xl" p={6} borderWidth="1px" borderColor="border.default">
              <Text color="text.muted" fontSize="xs" fontWeight="semibold" textTransform="uppercase" mb={4}>
                Concepts principaux
              </Text>
              <VStack spacing={2} align="stretch">
                {data.top_concepts.map((concept) => {
                  const tierInfo = concept.tier ? TIER_LABELS[concept.tier] : null
                  return (
                    <HStack
                      key={concept.name}
                      p={3}
                      rounded="lg"
                      bg="bg.secondary"
                      borderWidth="1px"
                      borderColor="border.default"
                      justify="space-between"
                      _hover={{ borderColor: 'border.active' }}
                      transition="all 0.15s"
                    >
                      <HStack spacing={3}>
                        {concept.article_slug ? (
                          <Link as={NextLink} href={`/wiki/${concept.article_slug}`} _hover={{ textDecoration: 'none' }}>
                            <HStack spacing={2}>
                              <Icon as={FiBook} color="brand.400" boxSize={3.5} />
                              <Text color="text.primary" fontSize="sm" fontWeight="medium" _hover={{ color: 'brand.400' }}>
                                {concept.name}
                              </Text>
                            </HStack>
                          </Link>
                        ) : (
                          <Text color="text.primary" fontSize="sm" fontWeight="medium">
                            {concept.name}
                          </Text>
                        )}
                        {tierInfo && (
                          <Badge colorScheme={tierInfo.color} fontSize="2xs" variant="subtle">{tierInfo.label}</Badge>
                        )}
                        <Badge colorScheme="gray" fontSize="2xs" variant="outline">{concept.entity_type}</Badge>
                      </HStack>
                      <HStack spacing={3}>
                        <Tooltip label="Nombre de claims" hasArrow fontSize="xs">
                          <Text color="text.muted" fontSize="xs" cursor="help">
                            {concept.claim_count} claims
                          </Text>
                        </Tooltip>
                        <Tooltip label="Nombre de documents sources" hasArrow fontSize="xs">
                          <Text color="text.muted" fontSize="xs" cursor="help">
                            {concept.doc_count} docs
                          </Text>
                        </Tooltip>
                      </HStack>
                    </HStack>
                  )
                })}
              </VStack>
            </Box>

            {/* Articles */}
            {data.articles.length > 0 && (
              <Box bg="surface.default" rounded="xl" p={6} borderWidth="1px" borderColor="border.default">
                <Text color="text.muted" fontSize="xs" fontWeight="semibold" textTransform="uppercase" mb={4}>
                  Articles ({data.articles.length})
                </Text>
                <SimpleGrid columns={{ base: 1, md: 2 }} spacing={3}>
                  {data.articles.map((article) => {
                    const tierInfo = TIER_LABELS[article.importance_tier] || TIER_LABELS[3]
                    return (
                      <Link
                        key={article.slug}
                        as={NextLink}
                        href={`/wiki/${article.slug}`}
                        _hover={{ textDecoration: 'none' }}
                      >
                        <Box
                          p={4}
                          rounded="lg"
                          bg="bg.secondary"
                          borderWidth="1px"
                          borderColor="border.default"
                          _hover={{ borderColor: 'brand.500', transform: 'translateY(-1px)' }}
                          transition="all 0.2s"
                        >
                          <HStack spacing={2} mb={2}>
                            <Icon as={FiBook} color="brand.400" boxSize={4} />
                            <Text color="text.primary" fontSize="sm" fontWeight="medium" noOfLines={1}>
                              {article.title}
                            </Text>
                          </HStack>
                          <HStack spacing={2}>
                            <Badge colorScheme={tierInfo.color} fontSize="2xs">{tierInfo.label}</Badge>
                            <Text color="text.muted" fontSize="xs">
                              {Math.round(article.confidence * 100)}% confiance
                            </Text>
                          </HStack>
                        </Box>
                      </Link>
                    )
                  })}
                </SimpleGrid>
              </Box>
            )}

            {/* Questions frequentes */}
            {data.suggested_questions.length > 0 && (
              <Box bg="surface.default" rounded="xl" p={6} borderWidth="1px" borderColor="border.default">
                <HStack spacing={2} mb={4}>
                  <Icon as={FiMessageCircle} color="brand.400" boxSize={4} />
                  <Text color="text.muted" fontSize="xs" fontWeight="semibold" textTransform="uppercase">
                    Questions frequentes sur ce domaine
                  </Text>
                </HStack>
                <VStack spacing={2} align="stretch">
                  {data.suggested_questions.map((q, i) => (
                    <Link
                      key={i}
                      as={NextLink}
                      href={`/chat?q=${encodeURIComponent(q.question)}`}
                      _hover={{ textDecoration: 'none' }}
                    >
                      <HStack
                        p={3}
                        rounded="lg"
                        bg="bg.secondary"
                        borderWidth="1px"
                        borderColor="border.default"
                        _hover={{ borderColor: 'brand.500', bg: 'bg.tertiary' }}
                        transition="all 0.15s"
                        spacing={3}
                      >
                        <Icon as={FiMessageCircle} color="brand.400" boxSize={3.5} flexShrink={0} />
                        <Text color="text.secondary" fontSize="sm">
                          {q.question}
                        </Text>
                      </HStack>
                    </Link>
                  ))}
                </VStack>
              </Box>
            )}
          </VStack>
        </Box>

        {/* Sidebar */}
        <Box w={{ base: 'full', lg: '300px' }} flexShrink={0}>
          <VStack spacing={4} align="stretch">
            {/* Documents contributeurs */}
            {data.documents.length > 0 && (
              <Box bg="surface.default" rounded="xl" p={4} borderWidth="1px" borderColor="border.default">
                <Text color="text.muted" fontSize="xs" fontWeight="semibold" textTransform="uppercase" mb={3}>
                  Documents ({data.documents.length})
                </Text>
                <VStack spacing={1.5} align="stretch">
                  {data.documents.map((doc) => (
                    <HStack key={doc.doc_id} justify="space-between">
                      <Tooltip label={doc.doc_id} hasArrow fontSize="xs" placement="left">
                        <Text color="text.secondary" fontSize="xs" noOfLines={1} maxW="200px" cursor="help">
                          {doc.doc_id}
                        </Text>
                      </Tooltip>
                      <Text color="text.muted" fontSize="xs" flexShrink={0}>
                        {doc.claim_count} claims
                      </Text>
                    </HStack>
                  ))}
                </VStack>
              </Box>
            )}

            {/* Lacunes */}
            {data.gaps.length > 0 && (
              <Box bg="surface.default" rounded="xl" p={4} borderWidth="1px" borderColor="border.default">
                <HStack spacing={2} mb={3}>
                  <Icon as={FiInfo} color="yellow.400" boxSize={3.5} />
                  <Text color="text.muted" fontSize="xs" fontWeight="semibold" textTransform="uppercase">
                    Concepts sans article ({data.gaps.length})
                  </Text>
                </HStack>
                <VStack spacing={1.5} align="stretch">
                  {data.gaps.map((gap) => (
                    <HStack key={gap.name} justify="space-between">
                      <Link
                        as={NextLink}
                        href={`/wiki/generate?concept=${encodeURIComponent(gap.name)}`}
                        fontSize="xs"
                        color="text.secondary"
                        _hover={{ color: 'brand.400' }}
                        noOfLines={1}
                      >
                        {gap.name}
                      </Link>
                      <Text color="text.muted" fontSize="2xs" flexShrink={0}>
                        {gap.claim_count} claims
                      </Text>
                    </HStack>
                  ))}
                </VStack>
              </Box>
            )}

            {/* Contradictions locales */}
            {data.stats.contradiction_count > 0 && (
              <Box
                bg="rgba(251, 191, 36, 0.04)"
                rounded="xl"
                p={4}
                borderWidth="1px"
                borderColor="rgba(251, 191, 36, 0.15)"
              >
                <HStack spacing={2} mb={2}>
                  <Icon as={FiAlertTriangle} color="orange.400" boxSize={3.5} />
                  <Text color="orange.400" fontSize="xs" fontWeight="semibold" textTransform="uppercase">
                    Zone a surveiller
                  </Text>
                </HStack>
                <Text color="text.muted" fontSize="xs">
                  {data.stats.contradiction_count} claims en contradiction dans ce domaine.
                  Consultez les articles pour identifier les points de debat.
                </Text>
              </Box>
            )}
          </VStack>
        </Box>
      </Flex>
    </Container>
  )
}
