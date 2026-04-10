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
  topics: AtlasTopic[]
  claim_count: number
}

interface AtlasTheme {
  label: string
  claim_count: number
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
          <Spinner size="xl" color="var(--accent-primary)" />
          <Text color="var(--text-secondary)">Chargement de l&apos;Atlas...</Text>
        </VStack>
      </Container>
    )
  }

  if (!data || (!data.roots.length && !data.themes.length)) {
    return (
      <Container maxW="1200px" py={12}>
        <VStack spacing={4} textAlign="center">
          <Icon as={FiBookOpen} boxSize={12} color="var(--text-muted)" />
          <Heading size="lg" color="var(--text-primary)">Atlas non disponible</Heading>
          <Text color="var(--text-secondary)">
            L&apos;Atlas narratif n&apos;a pas encore ete genere. Lancez le script build_narrative_topics.py
            puis generate_atlas_content.py.
          </Text>
        </VStack>
      </Container>
    )
  }

  return (
    <Box minH="100vh" bg="var(--bg-primary)">
      <Container maxW="1100px" py={10}>
        {/* Header */}
        <VStack spacing={6} mb={10} textAlign="center">
          <HStack spacing={3}>
            <Icon as={FiBookOpen} boxSize={8} color="var(--accent-primary)" />
            <Heading size="xl" color="var(--text-primary)" fontWeight="800">
              Atlas documentaire
            </Heading>
          </HStack>

          {/* Stats pills */}
          <HStack spacing={4} flexWrap="wrap" justify="center">
            <Badge px={3} py={1} rounded="full" bg="rgba(99,102,241,0.1)" color="var(--accent-primary)" fontSize="sm">
              <HStack spacing={1}><Icon as={FiFileText} boxSize={3} /><Text>{data.total_docs} documents</Text></HStack>
            </Badge>
            <Badge px={3} py={1} rounded="full" bg="rgba(16,185,129,0.1)" color="#10B981" fontSize="sm">
              <HStack spacing={1}><Icon as={FiDatabase} boxSize={3} /><Text>{data.total_claims.toLocaleString()} faits verifies</Text></HStack>
            </Badge>
            <Badge px={3} py={1} rounded="full" bg="rgba(245,158,11,0.1)" color="#F59E0B" fontSize="sm">
              <HStack spacing={1}><Icon as={FiLayers} boxSize={3} /><Text>{data.total_topics} chapitres</Text></HStack>
            </Badge>
          </HStack>

          {/* Introduction */}
          {data.introduction && (
            <Text
              color="var(--text-secondary)" fontSize="md" maxW="800px"
              lineHeight="1.7" px={4} textAlign="left"
            >
              {data.introduction}
            </Text>
          )}
        </VStack>

        <Divider borderColor="var(--border-default)" mb={8} />

        {/* Dual-axis tabs */}
        <Tabs variant="soft-rounded" colorScheme="blue">
          <TabList mb={6} justifyContent="center">
            <Tab
              _selected={{ bg: 'rgba(99,102,241,0.15)', color: 'var(--accent-primary)' }}
              color="var(--text-secondary)" fontWeight="600"
            >
              <HStack spacing={2}><Icon as={FiLayers} /><Text>Par produit</Text></HStack>
            </Tab>
            <Tab
              _selected={{ bg: 'rgba(16,185,129,0.15)', color: '#10B981' }}
              color="var(--text-secondary)" fontWeight="600"
            >
              <HStack spacing={2}><Icon as={FiGrid} /><Text>Par theme</Text></HStack>
            </Tab>
          </TabList>

          <TabPanels>
            {/* Tab 1: Par Produit */}
            <TabPanel px={0}>
              <VStack spacing={8} align="stretch">
                {data.roots.map(root => (
                  <Box key={root.root_id}>
                    <HStack mb={4} spacing={3}>
                      <Heading size="md" color="var(--text-primary)">
                        {root.name}
                      </Heading>
                      <Badge colorScheme="purple" variant="subtle" fontSize="xs">
                        {root.claim_count.toLocaleString()} claims
                      </Badge>
                    </HStack>
                    <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
                      {root.topics.map(topic => (
                        <TopicCard key={topic.topic_id} topic={topic} />
                      ))}
                    </SimpleGrid>
                  </Box>
                ))}
              </VStack>
            </TabPanel>

            {/* Tab 2: Par Theme */}
            <TabPanel px={0}>
              <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
                {data.themes.map((theme, i) => (
                  <Box
                    key={i}
                    p={5} rounded="xl"
                    bg="var(--bg-secondary)"
                    borderWidth="1px" borderColor="var(--border-default)"
                    _hover={{ borderColor: '#10B981', transform: 'translateY(-2px)' }}
                    transition="all 0.2s"
                  >
                    <HStack justify="space-between" mb={3}>
                      <Heading size="sm" color="var(--text-primary)">
                        {theme.label}
                      </Heading>
                      <Badge colorScheme="green" variant="subtle" fontSize="xs">
                        {theme.claim_count} claims
                      </Badge>
                    </HStack>
                    <VStack align="start" spacing={1}>
                      {theme.topic_labels.slice(0, 3).map((label, j) => (
                        <Text key={j} fontSize="xs" color="var(--text-muted)" noOfLines={1}>
                          {label}
                        </Text>
                      ))}
                      {theme.topic_labels.length > 3 && (
                        <Text fontSize="xs" color="var(--text-muted)" fontStyle="italic">
                          +{theme.topic_labels.length - 3} perspectives
                        </Text>
                      )}
                    </VStack>
                  </Box>
                ))}
              </SimpleGrid>
            </TabPanel>
          </TabPanels>
        </Tabs>
      </Container>
    </Box>
  )
}

function TopicCard({ topic }: { topic: AtlasTopic }) {
  return (
    <NextLink href={`/atlas/topic/${topic.topic_id}`} passHref>
      <Box
        p={5} rounded="xl" cursor="pointer"
        bg="var(--bg-secondary)"
        borderWidth="1px" borderColor="var(--border-default)"
        _hover={{ borderColor: 'var(--accent-primary)', transform: 'translateY(-2px)', shadow: 'md' }}
        transition="all 0.2s"
      >
        <HStack justify="space-between" mb={2}>
          <Badge colorScheme="blue" variant="subtle" fontSize="xs">
            {topic.perspective_count}P
          </Badge>
          <Badge variant="outline" fontSize="xs" color="var(--text-muted)">
            {topic.claim_count} claims
          </Badge>
        </HStack>
        <Heading size="sm" color="var(--text-primary)" mb={2} noOfLines={2}>
          {topic.title}
        </Heading>
        {topic.executive_summary && (
          <Text fontSize="xs" color="var(--text-secondary)" noOfLines={3} lineHeight="1.5">
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
          <Text fontSize="xs" color="var(--accent-primary)" fontWeight="600">
            Lire <Icon as={FiArrowRight} boxSize={3} />
          </Text>
        </HStack>
      </Box>
    </NextLink>
  )
}
