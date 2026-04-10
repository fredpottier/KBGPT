'use client'

import { useState, useEffect } from 'react'
import { useParams } from 'next/navigation'
import {
  Box, Container, Heading, Text, VStack, HStack, Badge,
  Spinner, Divider, Icon, Breadcrumb, BreadcrumbItem, BreadcrumbLink,
} from '@chakra-ui/react'
import { FiBookOpen, FiArrowLeft, FiLink, FiFileText, FiDatabase } from 'react-icons/fi'
import NextLink from 'next/link'
import { api } from '@/lib/api'

interface AtlasSection {
  perspective_id: string
  title: string
  content: string
  claim_count: number
}

interface RelatedTopic {
  topic_id: string
  title: string
  role: string
  weight: number
}

interface AtlasArticle {
  topic_id: string
  title: string
  executive_summary: string
  sections: AtlasSection[]
  related_topics: RelatedTopic[]
  total_claims: number
  total_docs: number
  generated_at: string
}

const ROLE_LABELS: Record<string, { label: string; color: string }> = {
  leads_to: { label: 'Mene a', color: 'blue' },
  details: { label: 'Precise', color: 'purple' },
  complements: { label: 'Complete', color: 'green' },
  nuances: { label: 'Nuance', color: 'orange' },
  tensions: { label: 'En tension', color: 'red' },
}

export default function AtlasArticlePage() {
  const params = useParams()
  const topicId = params?.id as string
  const [article, setArticle] = useState<AtlasArticle | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!topicId) return
    api.get(`/atlas/topic/${topicId}`)
      .then(res => setArticle(res.data))
      .catch(err => console.error('Article load error:', err))
      .finally(() => setLoading(false))
  }, [topicId])

  if (loading) {
    return (
      <Container maxW="900px" py={12}>
        <VStack><Spinner size="xl" color="var(--accent-primary)" /></VStack>
      </Container>
    )
  }

  if (!article || article.title === 'Not found') {
    return (
      <Container maxW="900px" py={12}>
        <Text color="var(--text-secondary)">Article non trouve.</Text>
      </Container>
    )
  }

  return (
    <Box minH="100vh" bg="var(--bg-primary)">
      <Container maxW="900px" py={8}>
        {/* Breadcrumb */}
        <Breadcrumb mb={6} fontSize="sm" color="var(--text-muted)">
          <BreadcrumbItem>
            <BreadcrumbLink as={NextLink} href="/atlas" color="var(--accent-primary)">
              <HStack spacing={1}><Icon as={FiBookOpen} boxSize={3} /><Text>Atlas</Text></HStack>
            </BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbItem isCurrentPage>
            <Text noOfLines={1} maxW="400px">{article.title}</Text>
          </BreadcrumbItem>
        </Breadcrumb>

        {/* Article header */}
        <VStack spacing={4} align="start" mb={8}>
          <Heading size="lg" color="var(--text-primary)" lineHeight="1.3">
            {article.title}
          </Heading>

          <HStack spacing={3} flexWrap="wrap">
            <Badge px={2} py={0.5} rounded="md" bg="rgba(99,102,241,0.1)" color="var(--accent-primary)" fontSize="xs">
              <HStack spacing={1}><Icon as={FiDatabase} boxSize={3} /><Text>{article.total_claims} faits</Text></HStack>
            </Badge>
            <Badge px={2} py={0.5} rounded="md" bg="rgba(16,185,129,0.1)" color="#10B981" fontSize="xs">
              <HStack spacing={1}><Icon as={FiFileText} boxSize={3} /><Text>{article.total_docs} documents</Text></HStack>
            </Badge>
            <Badge px={2} py={0.5} rounded="md" bg="rgba(245,158,11,0.1)" color="#F59E0B" fontSize="xs">
              {article.sections.length} sections
            </Badge>
          </HStack>

          {/* Executive summary */}
          {article.executive_summary && (
            <Box
              p={5} rounded="xl" w="100%"
              bg="rgba(99,102,241,0.05)"
              borderLeft="4px solid var(--accent-primary)"
            >
              <Text fontSize="sm" color="var(--text-secondary)" lineHeight="1.7" fontStyle="italic">
                {article.executive_summary}
              </Text>
            </Box>
          )}
        </VStack>

        <Divider borderColor="var(--border-default)" mb={8} />

        {/* Sections */}
        <VStack spacing={8} align="stretch">
          {article.sections.map((section, i) => (
            <Box key={section.perspective_id} id={`section-${i}`}>
              <HStack mb={3} spacing={2}>
                <Heading size="md" color="var(--text-primary)">
                  {section.title}
                </Heading>
                <Badge variant="subtle" colorScheme="gray" fontSize="10px">
                  {section.claim_count} claims
                </Badge>
              </HStack>
              {section.content ? (
                <Text
                  color="var(--text-secondary)" fontSize="sm" lineHeight="1.8"
                  whiteSpace="pre-wrap"
                >
                  {section.content}
                </Text>
              ) : (
                <Text color="var(--text-muted)" fontSize="sm" fontStyle="italic">
                  Contenu en cours de generation...
                </Text>
              )}
            </Box>
          ))}
        </VStack>

        {/* Related topics */}
        {article.related_topics.length > 0 && (
          <>
            <Divider borderColor="var(--border-default)" my={8} />
            <VStack spacing={4} align="start">
              <HStack spacing={2}>
                <Icon as={FiLink} color="var(--text-muted)" />
                <Heading size="sm" color="var(--text-primary)">Articles connexes</Heading>
              </HStack>
              <VStack spacing={2} align="stretch" w="100%">
                {article.related_topics.map(rel => {
                  const roleInfo = ROLE_LABELS[rel.role] || { label: rel.role, color: 'gray' }
                  return (
                    <NextLink key={rel.topic_id} href={`/atlas/topic/${rel.topic_id}`} passHref>
                      <HStack
                        p={3} rounded="lg" cursor="pointer"
                        bg="var(--bg-secondary)" borderWidth="1px" borderColor="var(--border-default)"
                        _hover={{ borderColor: 'var(--accent-primary)' }}
                        transition="all 0.15s"
                      >
                        <Badge colorScheme={roleInfo.color} variant="subtle" fontSize="10px" minW="70px" textAlign="center">
                          {roleInfo.label}
                        </Badge>
                        <Text fontSize="sm" color="var(--text-primary)" flex={1} noOfLines={1}>
                          {rel.title}
                        </Text>
                        <Icon as={FiArrowLeft} color="var(--text-muted)" transform="rotate(180deg)" />
                      </HStack>
                    </NextLink>
                  )
                })}
              </VStack>
            </VStack>
          </>
        )}

        {/* Footer */}
        <Box mt={10} pt={6} borderTopWidth="1px" borderColor="var(--border-default)">
          <Text fontSize="xs" color="var(--text-muted)" textAlign="center">
            Article genere automatiquement a partir de {article.total_claims} faits verifies
            extraits de {article.total_docs} documents source.
            {article.generated_at && ` Derniere generation : ${new Date(article.generated_at).toLocaleDateString('fr-FR')}.`}
          </Text>
        </Box>
      </Container>
    </Box>
  )
}
