'use client'

import { useState, useEffect } from 'react'
import { useParams } from 'next/navigation'
import {
  Box, Container, Heading, Text, VStack, HStack, Badge, SimpleGrid,
  Spinner, Divider, Icon, Breadcrumb, BreadcrumbItem, BreadcrumbLink,
} from '@chakra-ui/react'
import { FiArrowLeft, FiArrowRight, FiGrid, FiLayers, FiDatabase, FiFileText } from 'react-icons/fi'
import NextLink from 'next/link'
import { api } from '@/lib/api'

interface AtlasTopic {
  topic_id: string
  title: string
  executive_summary: string
  subjects: string[]
  claim_count: number
  perspective_count: number
  reading_order: number
  atlas_root: string
}

interface AtlasThemePerspective {
  perspective_id: string
  label: string
  claim_count: number
  parent_topic_id: string
  parent_topic_label: string
}

interface AtlasThemeDetail {
  theme_id: string
  label: string
  description: string
  claim_count: number
  topic_count: number
  related_topics: AtlasTopic[]
  perspectives: AtlasThemePerspective[]
}

export default function AtlasThemePage() {
  const params = useParams()
  const themeId = params?.id as string
  const [theme, setTheme] = useState<AtlasThemeDetail | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function load() {
      try {
        const res = await api.atlas.theme(themeId)
        if (res.success && res.data) {
          setTheme(res.data as AtlasThemeDetail)
        }
      } catch (err) {
        console.error('Theme load error:', err)
      } finally {
        setLoading(false)
      }
    }
    if (themeId) load()
  }, [themeId])

  if (loading) {
    return (
      <Box minH="60vh" display="flex" alignItems="center" justifyContent="center">
        <Spinner size="xl" color="var(--accent)" />
      </Box>
    )
  }

  if (!theme || !theme.label) {
    return (
      <Container maxW="container.lg" py={12}>
        <Text color="var(--fg-muted)">Thème introuvable.</Text>
      </Container>
    )
  }

  return (
    <Box minH="100vh" bg="var(--bg-canvas)" py={8}>
      <Container maxW="container.xl">
        {/* Breadcrumb */}
        <Breadcrumb
          fontSize="sm" color="var(--fg-muted)" mb={6}
          separator={<Icon as={FiArrowRight} boxSize={3} />}
        >
          <BreadcrumbItem>
            <BreadcrumbLink as={NextLink} href="/atlas">Atlas</BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbItem>
            <BreadcrumbLink as={NextLink} href="/atlas">Thèmes</BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbItem isCurrentPage>
            <Text color="var(--fg-secondary)" noOfLines={1}>{theme.label}</Text>
          </BreadcrumbItem>
        </Breadcrumb>

        {/* Hero */}
        <VStack spacing={4} align="stretch" mb={10}>
          <HStack spacing={3} flexWrap="wrap">
            <Icon as={FiGrid} boxSize={5} color="#10B981" />
            <Heading size="lg" color="var(--fg-primary)">
              {theme.label}
            </Heading>
          </HStack>

          <HStack spacing={2} flexWrap="wrap">
            <Badge px={3} py={1} rounded="full" bg="rgba(16,185,129,0.1)" color="#10B981" fontSize="sm">
              <HStack spacing={1}><Icon as={FiDatabase} boxSize={3} /><Text>{theme.claim_count.toLocaleString()} faits</Text></HStack>
            </Badge>
            <Badge px={3} py={1} rounded="full" bg="rgba(99,102,241,0.1)" color="var(--accent)" fontSize="sm">
              <HStack spacing={1}><Icon as={FiLayers} boxSize={3} /><Text>{theme.topic_count} chapitre{theme.topic_count > 1 ? 's' : ''} traversé{theme.topic_count > 1 ? 's' : ''}</Text></HStack>
            </Badge>
            <Badge px={3} py={1} rounded="full" bg="rgba(245,158,11,0.1)" color="#F59E0B" fontSize="sm">
              <HStack spacing={1}><Icon as={FiFileText} boxSize={3} /><Text>{theme.perspectives.length} perspective{theme.perspectives.length > 1 ? 's' : ''}</Text></HStack>
            </Badge>
          </HStack>

          {theme.description && (
            <Text
              color="var(--fg-secondary)" fontSize="md" maxW="900px"
              lineHeight="1.7"
            >
              {theme.description}
            </Text>
          )}
        </VStack>

        <Divider borderColor="var(--border-default)" mb={8} />

        {/* Chapitres concernés */}
        {theme.related_topics.length > 0 && (
          <Box mb={10}>
            <Heading size="md" color="var(--fg-primary)" mb={2}>
              Chapitres concernés
            </Heading>
            <Text fontSize="sm" color="var(--fg-muted)" mb={4}>
              Chapitres de l'Atlas qui abordent ce thème, classés par pertinence.
            </Text>
            <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
              {theme.related_topics.map(topic => (
                <NextLink key={topic.topic_id} href={`/atlas/topic/${topic.topic_id}`} passHref>
                  <Box
                    p={5} rounded="xl" cursor="pointer"
                    bg="var(--bg-surface)"
                    borderWidth="1px" borderColor="var(--border-default)"
                    _hover={{ borderColor: '#10B981', transform: 'translateY(-2px)', shadow: 'md' }}
                    transition="all 0.2s"
                    h="full"
                  >
                    <HStack justify="space-between" mb={2}>
                      {topic.atlas_root && (
                        <Badge colorScheme="purple" variant="subtle" fontSize="xs" noOfLines={1}>
                          {topic.atlas_root}
                        </Badge>
                      )}
                      <Badge variant="outline" fontSize="xs" color="var(--fg-muted)">
                        {topic.claim_count.toLocaleString()} faits
                      </Badge>
                    </HStack>
                    <Heading size="sm" color="var(--fg-primary)" mb={2} noOfLines={2}>
                      {topic.title || 'Chapitre sans titre'}
                    </Heading>
                    {topic.executive_summary && (
                      <Text fontSize="xs" color="var(--fg-secondary)" noOfLines={3} lineHeight="1.5">
                        {topic.executive_summary}
                      </Text>
                    )}
                    <HStack mt={3} justify="flex-end">
                      <Text fontSize="xs" color="var(--accent)" fontWeight="600">
                        Lire <Icon as={FiArrowRight} boxSize={3} />
                      </Text>
                    </HStack>
                  </Box>
                </NextLink>
              ))}
            </SimpleGrid>
          </Box>
        )}

        {/* Perspectives membres */}
        {theme.perspectives.length > 0 && (
          <Box>
            <Heading size="md" color="var(--fg-primary)" mb={2}>
              Perspectives membres
            </Heading>
            <Text fontSize="sm" color="var(--fg-muted)" mb={4}>
              Toutes les perspectives qui composent ce thème, avec leur chapitre d'origine.
            </Text>
            <VStack align="stretch" spacing={2}>
              {theme.perspectives.map(persp => (
                <Box
                  key={persp.perspective_id}
                  p={3} rounded="md"
                  bg="var(--bg-surface-alt)"
                  borderLeftWidth="3px"
                  borderLeftColor="#10B981"
                >
                  <HStack justify="space-between" align="start" flexWrap="wrap" gap={2}>
                    <VStack align="start" spacing={1} flex={1}>
                      <Text color="var(--fg-primary)" fontSize="sm" fontWeight="500">
                        {persp.label || 'Perspective sans titre'}
                      </Text>
                      {persp.parent_topic_id && persp.parent_topic_label && (
                        <NextLink href={`/atlas/topic/${persp.parent_topic_id}`} passHref>
                          <Text
                            as="a"
                            fontSize="xs" color="var(--accent)"
                            _hover={{ textDecoration: 'underline' }}
                          >
                            ↳ dans le chapitre « {persp.parent_topic_label} »
                          </Text>
                        </NextLink>
                      )}
                    </VStack>
                    <Badge variant="outline" fontSize="xs" color="var(--fg-muted)">
                      {persp.claim_count.toLocaleString()} faits
                    </Badge>
                  </HStack>
                </Box>
              ))}
            </VStack>
          </Box>
        )}

        {/* Footer back */}
        <HStack mt={12} justify="center">
          <NextLink href="/atlas" passHref>
            <Text
              as="a" fontSize="sm" color="var(--accent)"
              _hover={{ textDecoration: 'underline' }}
            >
              <Icon as={FiArrowLeft} boxSize={3} mr={1} />
              Retour à l'Atlas
            </Text>
          </NextLink>
        </HStack>
      </Container>
    </Box>
  )
}
