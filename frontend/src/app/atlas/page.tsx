'use client'

import { useState, useEffect } from 'react'
import {
  Box, Container, Heading, Text, VStack, HStack, SimpleGrid,
  Badge, Spinner, Tabs, TabList, TabPanels, Tab, TabPanel,
  Icon, Divider,
} from '@chakra-ui/react'
import { FiBookOpen, FiLayers, FiGrid, FiArrowRight, FiFileText, FiDatabase } from 'react-icons/fi'
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

interface AtlasRoot {
  root_id: string
  name: string
  description: string
  topics: AtlasTopic[]
  claim_count: number
}

interface AtlasTheme {
  theme_id: string
  label: string
  description: string
  claim_count: number
  topic_count: number
  topic_ids: string[]
  topic_labels: string[]
}

interface AtlasHomepage {
  introduction: string
  roots: AtlasRoot[]
  themes: AtlasTheme[]
  total_docs: number
  total_claims: number
  total_topics: number
}

export default function AtlasPage() {
  const [data, setData] = useState<AtlasHomepage | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function load() {
      try {
        const res = await api.atlas.homepage()
        if (res.success && res.data) {
          setData(res.data as AtlasHomepage)
        }
      } catch (err) {
        console.error('Atlas load error:', err)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  if (loading) {
    return (
      <Container maxW="1200px" py={12}>
        <VStack spacing={4}>
          <Spinner size="xl" color="var(--accent)" />
          <Text color="var(--fg-secondary)">Chargement de l&apos;Atlas...</Text>
        </VStack>
      </Container>
    )
  }

  if (!data || (!data.roots.length && !data.themes.length)) {
    return (
      <Container maxW="1200px" py={12}>
        <VStack spacing={4} textAlign="center">
          <Icon as={FiBookOpen} boxSize={12} color="var(--fg-muted)" />
          <Heading size="lg" color="var(--fg-primary)">Atlas non disponible</Heading>
          <Text color="var(--fg-secondary)">
            L&apos;Atlas narratif n&apos;a pas encore ete genere. Lancez le script build_narrative_topics.py
            puis generate_atlas_content.py.
          </Text>
        </VStack>
      </Container>
    )
  }

  return (
    <Box minH="100vh" bg="var(--bg-canvas)">
      <Container maxW="1100px" py={10}>
        {/* Header */}
        <VStack spacing={6} mb={10} textAlign="center">
          <HStack spacing={3}>
            <Icon as={FiBookOpen} boxSize={8} color="var(--accent)" />
            <Heading size="xl" color="var(--fg-primary)" fontWeight="800">
              Atlas documentaire
            </Heading>
          </HStack>

          {/* Stats pills */}
          <HStack spacing={4} flexWrap="wrap" justify="center">
            <Badge px={3} py={1} rounded="full" bg="rgba(99,102,241,0.1)" color="var(--accent)" fontSize="sm">
              <HStack spacing={1}><Icon as={FiFileText} boxSize={3} /><Text>{data.total_docs} documents</Text></HStack>
            </Badge>
            <Badge px={3} py={1} rounded="full" bg="rgba(16,185,129,0.1)" color="#10B981" fontSize="sm">
              <HStack spacing={1}><Icon as={FiDatabase} boxSize={3} /><Text>{data.total_claims.toLocaleString()} faits verifies</Text></HStack>
            </Badge>
            <Badge px={3} py={1} rounded="full" bg="rgba(245,158,11,0.1)" color="#F59E0B" fontSize="sm">
              <HStack spacing={1}><Icon as={FiLayers} boxSize={3} /><Text>{data.total_topics} chapitres</Text></HStack>
            </Badge>
          </HStack>

          {/* Introduction structurée — paragraphes hiérarchisés */}
          {data.introduction && (() => {
            const paragraphs = data.introduction.split(/\n\n+/).map(p => p.trim()).filter(Boolean)
            const isReaderGuide = (p: string) => /^Si vous (d[ée]couvrez|connaissez)/i.test(p)
            const isVolume = (p: string) => /^\s*\d+\s+(textes?|documents?)\s+analys/i.test(p)
            return (
              <VStack maxW="800px" spacing={4} align="stretch" px={4} w="full">
                {paragraphs.map((p, i) => {
                  if (isVolume(p)) {
                    return (
                      <Text key={i} color="var(--fg-muted)" fontSize="sm" fontStyle="italic" textAlign="center" mt={2}>
                        {p}
                      </Text>
                    )
                  }
                  if (isReaderGuide(p)) {
                    return (
                      <Box
                        key={i}
                        bg="var(--bg-surface-alt)"
                        borderLeftWidth="3px"
                        borderLeftColor="var(--accent)"
                        rounded="md"
                        px={4} py={3}
                      >
                        <Text color="var(--fg-secondary)" fontSize="md" lineHeight="1.65">
                          {p}
                        </Text>
                      </Box>
                    )
                  }
                  return (
                    <Text key={i} color="var(--fg-secondary)" fontSize="md" lineHeight="1.7" textAlign="left">
                      {p}
                    </Text>
                  )
                })}
              </VStack>
            )
          })()}
        </VStack>

        <Divider borderColor="var(--border-default)" mb={8} />

        {/* Dual-axis tabs */}
        <Tabs variant="soft-rounded" colorScheme="blue">
          <TabList mb={6} justifyContent="center">
            <Tab
              _selected={{ bg: 'rgba(99,102,241,0.15)', color: 'var(--accent)' }}
              color="var(--fg-secondary)" fontWeight="600"
            >
              <HStack spacing={2}><Icon as={FiLayers} /><Text>Par dossier</Text></HStack>
            </Tab>
            <Tab
              _selected={{ bg: 'rgba(16,185,129,0.15)', color: '#10B981' }}
              color="var(--fg-secondary)" fontWeight="600"
            >
              <HStack spacing={2}><Icon as={FiGrid} /><Text>Par thème</Text></HStack>
            </Tab>
          </TabList>

          <TabPanels>
            {/* Tab 1: Par Dossier */}
            <TabPanel px={0}>
              <VStack spacing={10} align="stretch">
                {data.roots.map(root => (
                  <Box key={root.root_id}>
                    <HStack mb={2} spacing={3} flexWrap="wrap">
                      <Heading size="md" color="var(--fg-primary)">
                        {root.name}
                      </Heading>
                      <Badge colorScheme="purple" variant="subtle" fontSize="xs">
                        {root.claim_count.toLocaleString()} faits
                      </Badge>
                      <Badge variant="outline" fontSize="xs" color="var(--fg-muted)">
                        {root.topics.length} chapitre{root.topics.length > 1 ? 's' : ''}
                      </Badge>
                    </HStack>
                    {root.description && (
                      <Text
                        color="var(--fg-secondary)" fontSize="sm" lineHeight="1.65"
                        mb={4} maxW="900px"
                      >
                        {root.description}
                      </Text>
                    )}
                    <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
                      {root.topics.map((topic, i) => (
                        <TopicCard
                          key={topic.topic_id}
                          topic={topic}
                          chapterNumber={i + 1}
                          totalChapters={root.topics.length}
                        />
                      ))}
                    </SimpleGrid>
                  </Box>
                ))}
              </VStack>
            </TabPanel>

            {/* Tab 2: Par Thème */}
            <TabPanel px={0}>
              <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
                {data.themes.map((theme, i) => {
                  const card = (
                    <Box
                      p={5} rounded="xl"
                      cursor={theme.theme_id ? 'pointer' : 'default'}
                      bg="var(--bg-surface)"
                      borderWidth="1px" borderColor="var(--border-default)"
                      _hover={theme.theme_id ? { borderColor: '#10B981', transform: 'translateY(-2px)', shadow: 'md' } : {}}
                      transition="all 0.2s"
                      h="full"
                    >
                      <HStack justify="space-between" mb={3} flexWrap="wrap" gap={2}>
                        <Heading size="sm" color="var(--fg-primary)" flex={1}>
                          {theme.label}
                        </Heading>
                        <HStack spacing={1}>
                          <Badge colorScheme="green" variant="subtle" fontSize="xs">
                            {theme.claim_count.toLocaleString()} faits
                          </Badge>
                          {theme.topic_count > 0 && (
                            <Badge variant="outline" fontSize="xs" color="var(--fg-muted)">
                              {theme.topic_count} chapitre{theme.topic_count > 1 ? 's' : ''}
                            </Badge>
                          )}
                        </HStack>
                      </HStack>
                      {theme.description && (
                        <Text fontSize="sm" color="var(--fg-secondary)" lineHeight="1.6" mb={3}>
                          {theme.description}
                        </Text>
                      )}
                      {theme.topic_labels.length > 0 && (
                        <VStack align="start" spacing={1} mt={2}>
                          <Text fontSize="xs" color="var(--fg-muted)" fontWeight="600" textTransform="uppercase" letterSpacing="wider">
                            Perspectives membres
                          </Text>
                          {theme.topic_labels.slice(0, 3).map((label, j) => (
                            <Text key={j} fontSize="xs" color="var(--fg-muted)" noOfLines={1}>
                              • {label}
                            </Text>
                          ))}
                          {theme.topic_labels.length > 3 && (
                            <Text fontSize="xs" color="var(--fg-muted)" fontStyle="italic">
                              +{theme.topic_labels.length - 3} autres
                            </Text>
                          )}
                        </VStack>
                      )}
                      {theme.theme_id && (
                        <HStack mt={3} justify="flex-end">
                          <Text fontSize="xs" color="#10B981" fontWeight="600">
                            Explorer <Icon as={FiArrowRight} boxSize={3} />
                          </Text>
                        </HStack>
                      )}
                    </Box>
                  )
                  return theme.theme_id ? (
                    <NextLink key={theme.theme_id} href={`/atlas/theme/${theme.theme_id}`} passHref>
                      {card}
                    </NextLink>
                  ) : (
                    <Box key={i}>{card}</Box>
                  )
                })}
              </SimpleGrid>
            </TabPanel>
          </TabPanels>
        </Tabs>
      </Container>
    </Box>
  )
}

function TopicCard({
  topic,
  chapterNumber,
  totalChapters,
}: {
  topic: AtlasTopic
  chapterNumber?: number
  totalChapters?: number
}) {
  // Fallback : si title est vide, prendre les 60 premiers caracteres du summary
  const displayTitle =
    topic.title?.trim() ||
    (topic.executive_summary
      ? topic.executive_summary.split(/[.!?]/)[0].trim().slice(0, 70) + '…'
      : 'Chapitre sans titre')

  return (
    <NextLink href={`/atlas/topic/${topic.topic_id}`} passHref>
      <Box
        p={5} rounded="xl" cursor="pointer"
        bg="var(--bg-surface)"
        borderWidth="1px" borderColor="var(--border-default)"
        _hover={{ borderColor: 'var(--accent)', transform: 'translateY(-2px)', shadow: 'md' }}
        transition="all 0.2s"
        h="full"
      >
        <HStack justify="space-between" mb={2}>
          {chapterNumber && totalChapters ? (
            <Badge colorScheme="purple" variant="subtle" fontSize="xs">
              Chapitre {chapterNumber}/{totalChapters}
            </Badge>
          ) : (
            <Badge colorScheme="blue" variant="subtle" fontSize="xs">
              {topic.perspective_count}P
            </Badge>
          )}
          <Badge variant="outline" fontSize="xs" color="var(--fg-muted)">
            {topic.claim_count.toLocaleString()} faits
          </Badge>
        </HStack>
        <Heading size="sm" color="var(--fg-primary)" mb={2} noOfLines={2}>
          {displayTitle}
        </Heading>
        {topic.executive_summary && (
          <Text fontSize="xs" color="var(--fg-secondary)" noOfLines={3} lineHeight="1.5">
            {topic.executive_summary}
          </Text>
        )}
        {topic.subjects.length > 0 && (
          <HStack mt={3} spacing={1} flexWrap="wrap">
            {topic.subjects.slice(0, 3).map((s, i) => (
              <Badge key={i} fontSize="10px" variant="subtle" colorScheme="gray">
                {s}
              </Badge>
            ))}
          </HStack>
        )}
        <HStack mt={3} justify="flex-end">
          <Text fontSize="xs" color="var(--accent)" fontWeight="600">
            Lire <Icon as={FiArrowRight} boxSize={3} />
          </Text>
        </HStack>
      </Box>
    </NextLink>
  )
}
