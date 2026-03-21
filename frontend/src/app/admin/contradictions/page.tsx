'use client'

/**
 * Contradiction Explorer — Navigation interactive dans les tensions du corpus.
 *
 * Chaque contradiction = deux claims face-a-face avec type de tension,
 * severite, entites communes, et verbatim quotes.
 */

import { useState, useEffect, useCallback } from 'react'
import {
  Box,
  Text,
  VStack,
  HStack,
  Flex,
  Badge,
  Spinner,
  Select,
  Input,
  Icon,
  SimpleGrid,
  Button,
  Collapse,
  useDisclosure,
} from '@chakra-ui/react'
import {
  FiAlertTriangle,
  FiSlash,
  FiInfo,
  FiClock,
  FiLayers,
  FiHelpCircle,
  FiChevronDown,
  FiChevronUp,
  FiFileText,
  FiChevronLeft,
  FiChevronRight,
} from 'react-icons/fi'

const API_BASE_URL = typeof window !== 'undefined'
  ? (process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000')
  : 'http://localhost:8000'

const getAuthHeaders = () => ({
  'Content-Type': 'application/json',
  Authorization: `Bearer ${localStorage.getItem('auth_token') || ''}`,
})

// ── Types ──────────────────────────────────────────────────────────────

interface ClaimSide {
  id: string
  text: string
  doc_id: string
  verbatim: string
  claim_type: string
  page: number | null
}

interface Contradiction {
  claim1: ClaimSide
  claim2: ClaimSide
  tension_nature: string
  tension_level: string
  entities: string[]
}

interface ContradictionStats {
  by_nature: Record<string, number>
  by_level: Record<string, number>
  total: number
}

interface ContradictionResponse {
  contradictions: Contradiction[]
  total: number
  limit: number
  offset: number
  stats: ContradictionStats
}

// ── Config ─────────────────────────────────────────────────────────────

const NATURE_CONFIG: Record<string, { label: string; icon: any; color: string; bg: string }> = {
  value_conflict: { label: 'Conflit de valeur', icon: FiSlash, color: 'red.400', bg: 'rgba(239, 68, 68, 0.08)' },
  scope_conflict: { label: 'Variation de scope', icon: FiLayers, color: 'blue.400', bg: 'rgba(59, 130, 246, 0.08)' },
  temporal_conflict: { label: 'Evolution temporelle', icon: FiClock, color: 'orange.400', bg: 'rgba(249, 115, 22, 0.08)' },
  methodological: { label: 'Methodologique', icon: FiInfo, color: 'purple.400', bg: 'rgba(168, 85, 247, 0.08)' },
  complementary: { label: 'Complementaire', icon: FiLayers, color: 'green.400', bg: 'rgba(34, 197, 94, 0.08)' },
  unclassified: { label: 'Non classifie', icon: FiHelpCircle, color: 'gray.400', bg: 'rgba(113, 113, 122, 0.08)' },
}

const LEVEL_CONFIG: Record<string, { label: string; color: string }> = {
  hard: { label: 'Dur', color: 'red' },
  soft: { label: 'Modere', color: 'orange' },
  unknown: { label: 'Indetermine', color: 'gray' },
}

// ── Contradiction Card ─────────────────────────────────────────────────

function ContradictionCard({ item }: { item: Contradiction }) {
  const { isOpen, onToggle } = useDisclosure()
  const nature = NATURE_CONFIG[item.tension_nature] || NATURE_CONFIG.unclassified
  const level = LEVEL_CONFIG[item.tension_level] || LEVEL_CONFIG.unknown

  const formatDocId = (docId: string) => {
    let label = docId
    if (label.includes('_')) {
      const parts = label.split('_')
      if (parts.length > 2 && parts[parts.length - 1].length >= 8) parts.pop()
      if (parts[0].startsWith('PMC')) parts[0] = `PMC ${parts[0].slice(3)}`
      label = parts.slice(0, 5).join(' ').replace(/_/g, ' ')
      if (label.length > 45) label = label.slice(0, 42) + '...'
    }
    return label
  }

  return (
    <Box
      bg={nature.bg}
      borderWidth="1px"
      borderColor="var(--border-default)"
      borderLeftWidth="4px"
      borderLeftColor={nature.color}
      borderRadius="xl"
      p={5}
      transition="all 0.2s"
      _hover={{ borderColor: nature.color }}
    >
      {/* Header: nature + level + entities */}
      <Flex justify="space-between" align="center" mb={4}>
        <HStack spacing={3}>
          <Icon as={nature.icon} color={nature.color} boxSize={4} />
          <Badge colorScheme={nature.color.split('.')[0]} variant="subtle" fontSize="xs" px={2} py={0.5}>
            {nature.label}
          </Badge>
          <Badge colorScheme={level.color} variant="outline" fontSize="xs" px={2} py={0.5}>
            {level.label}
          </Badge>
        </HStack>
        {item.entities.length > 0 && (
          <HStack spacing={1} flexWrap="wrap">
            {item.entities.slice(0, 3).map((e, i) => (
              <Badge key={i} fontSize="2xs" colorScheme="brand" variant="subtle" px={1.5}>
                {e}
              </Badge>
            ))}
            {item.entities.length > 3 && (
              <Text fontSize="2xs" color="var(--text-muted)">+{item.entities.length - 3}</Text>
            )}
          </HStack>
        )}
      </Flex>

      {/* Two claims face-to-face */}
      <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
        {/* Claim 1 */}
        <Box bg="var(--bg-primary)" borderRadius="lg" p={4} borderWidth="1px" borderColor="rgba(239, 68, 68, 0.15)">
          <HStack spacing={2} mb={2}>
            <Box w="8px" h="8px" borderRadius="full" bg="red.400" />
            <Text fontSize="2xs" color="var(--text-muted)" fontWeight="600" textTransform="uppercase">Source A</Text>
          </HStack>
          <Text fontSize="sm" color="var(--text-primary)" lineHeight="tall" mb={2}>
            {item.claim1.text}
          </Text>
          <HStack spacing={2} flexWrap="wrap">
            <Icon as={FiFileText} color="var(--text-muted)" boxSize={3} />
            <Text fontSize="2xs" color="var(--text-muted)" noOfLines={1}>
              {formatDocId(item.claim1.doc_id)}
            </Text>
            {item.claim1.page && (
              <Text fontSize="2xs" color="var(--text-muted)">p.{item.claim1.page}</Text>
            )}
          </HStack>
        </Box>

        {/* Claim 2 */}
        <Box bg="var(--bg-primary)" borderRadius="lg" p={4} borderWidth="1px" borderColor="rgba(59, 130, 246, 0.15)">
          <HStack spacing={2} mb={2}>
            <Box w="8px" h="8px" borderRadius="full" bg="blue.400" />
            <Text fontSize="2xs" color="var(--text-muted)" fontWeight="600" textTransform="uppercase">Source B</Text>
          </HStack>
          <Text fontSize="sm" color="var(--text-primary)" lineHeight="tall" mb={2}>
            {item.claim2.text}
          </Text>
          <HStack spacing={2} flexWrap="wrap">
            <Icon as={FiFileText} color="var(--text-muted)" boxSize={3} />
            <Text fontSize="2xs" color="var(--text-muted)" noOfLines={1}>
              {formatDocId(item.claim2.doc_id)}
            </Text>
            {item.claim2.page && (
              <Text fontSize="2xs" color="var(--text-muted)">p.{item.claim2.page}</Text>
            )}
          </HStack>
        </Box>
      </SimpleGrid>

      {/* Verbatim quotes (expandable) */}
      {(item.claim1.verbatim || item.claim2.verbatim) && (
        <Box mt={3}>
          <Button
            size="xs"
            variant="ghost"
            color="var(--text-muted)"
            onClick={onToggle}
            rightIcon={isOpen ? <FiChevronUp /> : <FiChevronDown />}
            _hover={{ color: 'var(--text-primary)' }}
          >
            Citations verbatim
          </Button>
          <Collapse in={isOpen}>
            <SimpleGrid columns={{ base: 1, md: 2 }} spacing={3} mt={2}>
              {item.claim1.verbatim && (
                <Box bg="rgba(239, 68, 68, 0.04)" borderRadius="md" p={3} borderLeftWidth="2px" borderLeftColor="red.800">
                  <Text fontSize="xs" color="var(--text-secondary)" fontStyle="italic" lineHeight="tall">
                    "{item.claim1.verbatim}"
                  </Text>
                </Box>
              )}
              {item.claim2.verbatim && (
                <Box bg="rgba(59, 130, 246, 0.04)" borderRadius="md" p={3} borderLeftWidth="2px" borderLeftColor="blue.800">
                  <Text fontSize="xs" color="var(--text-secondary)" fontStyle="italic" lineHeight="tall">
                    "{item.claim2.verbatim}"
                  </Text>
                </Box>
              )}
            </SimpleGrid>
          </Collapse>
        </Box>
      )}
    </Box>
  )
}

// ── Main Page ──────────────────────────────────────────────────────────

export default function ContradictionsPage() {
  const [data, setData] = useState<ContradictionResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Filters
  const [natureFilter, setNatureFilter] = useState('')
  const [levelFilter, setLevelFilter] = useState('')
  const [entityFilter, setEntityFilter] = useState('')
  const [page, setPage] = useState(0)
  const pageSize = 10

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      if (natureFilter) params.set('nature', natureFilter)
      if (levelFilter) params.set('level', levelFilter)
      if (entityFilter) params.set('entity', entityFilter)
      params.set('limit', String(pageSize))
      params.set('offset', String(page * pageSize))

      const res = await fetch(
        `${API_BASE_URL}/api/corpus-intelligence/contradictions?${params}`,
        { headers: getAuthHeaders() }
      )
      if (!res.ok) throw new Error('Erreur chargement')
      setData(await res.json())
    } catch (err: any) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [natureFilter, levelFilter, entityFilter, page])

  useEffect(() => { fetchData() }, [fetchData])

  // Reset page when filters change
  useEffect(() => { setPage(0) }, [natureFilter, levelFilter, entityFilter])

  return (
    <Box>
      {/* Header */}
      <VStack align="start" spacing={1} mb={6}>
        <HStack spacing={3}>
          <Icon as={FiAlertTriangle} color="orange.400" boxSize={5} />
          <Text fontSize="xl" fontWeight="700" color="var(--text-primary)">
            Contradiction Explorer
          </Text>
        </HStack>
        <Text fontSize="sm" color="var(--text-muted)">
          Navigation interactive dans les tensions detectees entre sources documentaires
        </Text>
      </VStack>

      {/* Stats */}
      {data?.stats && (
        <HStack spacing={4} mb={6} flexWrap="wrap">
          <Badge px={3} py={1.5} borderRadius="md" bg="rgba(239, 68, 68, 0.1)" color="red.300" fontSize="sm" fontWeight="700">
            {data.stats.total} contradictions
          </Badge>
          {Object.entries(data.stats.by_nature).map(([nature, count]) => {
            const cfg = NATURE_CONFIG[nature] || NATURE_CONFIG.unclassified
            return (
              <Badge key={nature} px={2} py={1} borderRadius="md" bg={cfg.bg} color={cfg.color} fontSize="xs"
                cursor="pointer" onClick={() => setNatureFilter(natureFilter === nature ? '' : nature)}
                opacity={!natureFilter || natureFilter === nature ? 1 : 0.4}
                transition="opacity 0.15s"
              >
                {cfg.label}: {count}
              </Badge>
            )
          })}
        </HStack>
      )}

      {/* Filters */}
      <HStack spacing={3} mb={6} flexWrap="wrap">
        <Select
          size="sm" w="200px" bg="var(--bg-secondary)" borderColor="var(--border-default)"
          color="var(--text-primary)" value={natureFilter}
          onChange={(e) => setNatureFilter(e.target.value)}
          sx={{ option: { bg: '#12121a', color: '#f4f4f5' } }}
        >
          <option value="">Tous les types</option>
          <option value="value_conflict">Conflit de valeur</option>
          <option value="scope_conflict">Variation de scope</option>
          <option value="temporal_conflict">Evolution temporelle</option>
          <option value="methodological">Methodologique</option>
          <option value="complementary">Complementaire</option>
        </Select>

        <Select
          size="sm" w="160px" bg="var(--bg-secondary)" borderColor="var(--border-default)"
          color="var(--text-primary)" value={levelFilter}
          onChange={(e) => setLevelFilter(e.target.value)}
          sx={{ option: { bg: '#12121a', color: '#f4f4f5' } }}
        >
          <option value="">Toutes severites</option>
          <option value="hard">Dur</option>
          <option value="soft">Modere</option>
        </Select>

        <Input
          size="sm" w="200px" bg="var(--bg-secondary)" borderColor="var(--border-default)"
          color="var(--text-primary)" placeholder="Filtrer par concept..."
          value={entityFilter}
          onChange={(e) => setEntityFilter(e.target.value)}
        />
      </HStack>

      {/* Content */}
      {loading ? (
        <VStack py={16} spacing={4}>
          <Spinner size="lg" color="brand.400" thickness="3px" />
          <Text color="var(--text-muted)" fontSize="sm">Chargement des contradictions...</Text>
        </VStack>
      ) : error ? (
        <Box bg="rgba(239, 68, 68, 0.08)" border="1px solid rgba(239, 68, 68, 0.2)" borderRadius="xl" p={6}>
          <Text color="red.400">{error}</Text>
        </Box>
      ) : data && data.contradictions.length === 0 ? (
        <Box bg="var(--bg-secondary)" borderRadius="xl" p={8} textAlign="center" borderWidth="1px" borderColor="var(--border-default)">
          <Text color="var(--text-muted)">Aucune contradiction trouvee avec ces filtres.</Text>
        </Box>
      ) : data && (
        <>
          <VStack spacing={4} align="stretch">
            {data.contradictions.map((item, i) => (
              <ContradictionCard key={`${item.claim1.id}-${item.claim2.id}-${i}`} item={item} />
            ))}
          </VStack>

          {/* Pagination */}
          <HStack justify="center" mt={6} spacing={4}>
            <Button
              size="sm" variant="ghost" color="var(--text-muted)"
              leftIcon={<FiChevronLeft />}
              isDisabled={page === 0}
              onClick={() => setPage(p => p - 1)}
            >
              Precedent
            </Button>
            <Text fontSize="sm" color="var(--text-muted)">
              {page * pageSize + 1}-{Math.min((page + 1) * pageSize, data.total)} sur {data.total}
            </Text>
            <Button
              size="sm" variant="ghost" color="var(--text-muted)"
              rightIcon={<FiChevronRight />}
              isDisabled={(page + 1) * pageSize >= data.total}
              onClick={() => setPage(p => p + 1)}
            >
              Suivant
            </Button>
          </HStack>
        </>
      )}
    </Box>
  )
}
