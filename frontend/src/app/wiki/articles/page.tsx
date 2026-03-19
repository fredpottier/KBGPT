'use client'

import { useState, useEffect, useCallback } from 'react'
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
  Input,
  Select,
  Button,
  Spinner,
  Link,
  SimpleGrid,
} from '@chakra-ui/react'
import NextLink from 'next/link'
import { FiBook, FiSearch, FiChevronLeft, FiChevronRight } from 'react-icons/fi'
import { api } from '@/lib/api'

interface ArticleListItem {
  slug: string
  title: string
  entity_type: string
  category_key: string
  importance_tier: number
  importance_score: number
  generation_confidence: number
  source_count: number
  unit_count: number
  sections_count: number
  total_citations: number
  updated_at?: string
}

interface Category {
  category_key: string
  label: string
  article_count: number
}

const TIER_LABELS: Record<number, { label: string; color: string }> = {
  1: { label: 'Portail', color: 'purple' },
  2: { label: 'Principal', color: 'blue' },
  3: { label: 'Spécifique', color: 'gray' },
}

const PAGE_SIZE = 12

export default function WikiArticlesPage() {
  const [articles, setArticles] = useState<ArticleListItem[]>([])
  const [categories, setCategories] = useState<Category[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [selectedCategory, setSelectedCategory] = useState('')
  const [selectedTier, setSelectedTier] = useState('')
  const [searchInput, setSearchInput] = useState('')

  const fetchArticles = useCallback(async () => {
    setLoading(true)
    const params: any = { limit: PAGE_SIZE, offset }
    if (search) params.search = search
    if (selectedCategory) params.category = selectedCategory
    if (selectedTier) params.tier = parseInt(selectedTier)

    const res = await api.wiki.listArticles(params)
    if (res.success && res.data) {
      const d = res.data as { articles: ArticleListItem[]; total: number }
      setArticles(d.articles || [])
      setTotal(d.total || 0)
    }
    setLoading(false)
  }, [offset, search, selectedCategory, selectedTier])

  const fetchCategories = useCallback(async () => {
    const res = await api.wiki.categories()
    if (res.success && res.data) {
      const d = res.data as { categories: Category[] }
      if (d.categories) setCategories(d.categories)
    }
  }, [])

  useEffect(() => {
    fetchCategories()
  }, [fetchCategories])

  useEffect(() => {
    fetchArticles()
  }, [fetchArticles])

  const handleSearch = () => {
    setSearch(searchInput)
    setOffset(0)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleSearch()
  }

  const totalPages = Math.ceil(total / PAGE_SIZE)
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1

  const confidenceColor = (conf: number) => {
    if (conf >= 0.7) return 'green'
    if (conf >= 0.5) return 'yellow'
    return 'red'
  }

  return (
    <Container maxW="7xl" py={8} mt={16}>
      <VStack spacing={2} mb={8} align="start">
        <HStack>
          <Icon as={FiBook} boxSize={7} color="brand.400" />
          <Heading size="lg" color="text.primary">Articles</Heading>
          <Badge colorScheme="brand" fontSize="sm">{total}</Badge>
        </HStack>
        <Text color="text.muted" fontSize="sm">
          Parcourez les articles encyclopédiques du Knowledge Atlas.
        </Text>
      </VStack>

      {/* Filtres */}
      <Box bg="surface.default" rounded="xl" p={4} mb={6} borderWidth="1px" borderColor="border.default">
        <Flex gap={3} wrap="wrap" align="center">
          <HStack flex={1} minW="200px">
            <Icon as={FiSearch} color="text.muted" />
            <Input
              placeholder="Rechercher un article..."
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              onKeyDown={handleKeyDown}
              bg="bg.secondary"
              borderColor="border.default"
              color="text.primary"
              _placeholder={{ color: 'text.muted' }}
              size="sm"
            />
            <Button size="sm" colorScheme="brand" onClick={handleSearch}>
              Rechercher
            </Button>
          </HStack>

          <Select
            value={selectedCategory}
            onChange={(e) => { setSelectedCategory(e.target.value); setOffset(0) }}
            maxW="180px"
            bg="bg.secondary"
            borderColor="border.default"
            color="text.primary"
            size="sm"
            placeholder="Catégorie"
            sx={{ '& option': { background: '#1a1a2e !important', color: '#e2e8f0 !important' } }}
          >
            {categories.map((c) => (
              <option key={c.category_key} value={c.category_key}>
                {c.label} ({c.article_count})
              </option>
            ))}
          </Select>

          <Select
            value={selectedTier}
            onChange={(e) => { setSelectedTier(e.target.value); setOffset(0) }}
            maxW="150px"
            bg="bg.secondary"
            borderColor="border.default"
            color="text.primary"
            size="sm"
            placeholder="Tier"
            sx={{ '& option': { background: '#1a1a2e !important', color: '#e2e8f0 !important' } }}
          >
            <option value="1">Tier 1 — Portail</option>
            <option value="2">Tier 2 — Principal</option>
            <option value="3">Tier 3 — Spécifique</option>
          </Select>

          {(search || selectedCategory || selectedTier) && (
            <Button
              size="sm"
              variant="ghost"
              color="text.muted"
              onClick={() => {
                setSearch('')
                setSearchInput('')
                setSelectedCategory('')
                setSelectedTier('')
                setOffset(0)
              }}
            >
              Réinitialiser
            </Button>
          )}
        </Flex>
      </Box>

      {/* Liste */}
      {loading ? (
        <HStack justify="center" py={12}>
          <Spinner size="lg" color="brand.400" />
        </HStack>
      ) : articles.length === 0 ? (
        <Box bg="surface.default" rounded="xl" p={8} textAlign="center" borderWidth="1px" borderColor="border.default">
          <Text color="text.muted">Aucun article trouvé.</Text>
          <Link as={NextLink} href="/wiki/generate" color="brand.300" fontSize="sm" mt={2}>
            Générer un article
          </Link>
        </Box>
      ) : (
        <>
          <SimpleGrid columns={{ base: 1, md: 2, lg: 3 }} spacing={4} mb={6}>
            {articles.map((a) => {
              const tierInfo = TIER_LABELS[a.importance_tier] || TIER_LABELS[3]
              return (
                <Link
                  key={a.slug}
                  as={NextLink}
                  href={`/wiki/${a.slug}`}
                  _hover={{ textDecoration: 'none' }}
                >
                  <Box
                    bg="surface.default"
                    rounded="xl"
                    p={4}
                    borderWidth="1px"
                    borderColor="border.default"
                    _hover={{ borderColor: 'brand.500', transform: 'translateY(-2px)' }}
                    transition="all 0.2s"
                    h="full"
                  >
                    <HStack mb={2} spacing={2}>
                      <Badge colorScheme={tierInfo.color} fontSize="9px">{tierInfo.label}</Badge>
                      <Badge colorScheme="gray" fontSize="9px">{a.entity_type}</Badge>
                    </HStack>
                    <Heading size="sm" color="text.primary" mb={2} noOfLines={2}>
                      {a.title}
                    </Heading>
                    <HStack spacing={3} mb={2}>
                      <Text color="text.muted" fontSize="xs">{a.source_count} sources</Text>
                      <Text color="text.muted" fontSize="xs">{a.unit_count} units</Text>
                      <Text color="text.muted" fontSize="xs">{a.sections_count} sections</Text>
                    </HStack>
                    <HStack>
                      <Box flex={1} bg="gray.700" rounded="full" h="4px">
                        <Box
                          bg={`${confidenceColor(a.generation_confidence)}.400`}
                          h="4px"
                          rounded="full"
                          w={`${Math.round(a.generation_confidence * 100)}%`}
                        />
                      </Box>
                      <Text color="text.muted" fontSize="xs">
                        {Math.round(a.generation_confidence * 100)}%
                      </Text>
                    </HStack>
                    {a.updated_at && (
                      <Text color="text.muted" fontSize="xs" mt={2}>
                        {new Date(a.updated_at).toLocaleDateString('fr-FR')}
                      </Text>
                    )}
                  </Box>
                </Link>
              )
            })}
          </SimpleGrid>

          {/* Pagination */}
          {totalPages > 1 && (
            <HStack justify="center" spacing={4}>
              <Button
                size="sm"
                variant="ghost"
                leftIcon={<FiChevronLeft />}
                isDisabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              >
                Précédent
              </Button>
              <Text color="text.muted" fontSize="sm">
                Page {currentPage} / {totalPages}
              </Text>
              <Button
                size="sm"
                variant="ghost"
                rightIcon={<FiChevronRight />}
                isDisabled={offset + PAGE_SIZE >= total}
                onClick={() => setOffset(offset + PAGE_SIZE)}
              >
                Suivant
              </Button>
            </HStack>
          )}
        </>
      )}
    </Container>
  )
}
