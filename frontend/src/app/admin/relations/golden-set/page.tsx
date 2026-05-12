'use client'

/**
 * S3.F.2 — Golden set annotation UI.
 *
 * Liste les GoldenPair non annotés, permet à l'admin de cocher pour chaque paire :
 * - "Correct" → human_label = predicted_type (le classifier a raison)
 * - "Wrong type" → human_label = autre type V3.3 (à choisir)
 * - "Rejected" → human_label = "REJECTED" (cette paire ne devrait PAS exister)
 *
 * Une fois annoté, lancer `scripts/eval_classifier_golden.py` pour mesurer
 * la précision et débloquer le cleanup legacy.
 */

import { useState, useEffect, useCallback } from 'react'
import {
  Box,
  Text,
  VStack,
  HStack,
  Button,
  SimpleGrid,
  Tag,
  Spinner,
  Icon,
  Select,
  Textarea,
} from '@chakra-ui/react'
import {
  FiCheck,
  FiX,
  FiAlertTriangle,
  FiArrowRight,
  FiSkipForward,
} from 'react-icons/fi'

const API_BASE_URL = typeof window !== 'undefined'
  ? (process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000')
  : 'http://localhost:8000'

const getAuthHeaders = () => ({
  'Content-Type': 'application/json',
  Authorization: `Bearer ${localStorage.getItem('auth_token') || ''}`,
})

const V33_TYPES = [
  'SUBSET', 'SUPERSET', 'EQUIVALENT', 'OVERLAP', 'DISJOINT',
  'CONFLICT', 'EXCEPTION', 'DEFINITION_OF',
  'SUPERSEDES', 'EVOLVES_FROM', 'REAFFIRMS', 'UNRELATED',
  'REJECTED',
] as const

interface GoldenPair {
  golden_id: string
  predicted_type: string
  predicted_strength: string
  predicted_confidence: number
  predicted_is_contradiction: boolean
  predicted_reasoning: string
  scope_alignment: string | null
  temporal_relation: string | null
  a_claim_id: string
  a_text: string
  a_doc_id: string
  b_claim_id: string
  b_text: string
  b_doc_id: string
  human_label: string | null
  human_notes: string | null
}

interface GoldenSetStats {
  total: number
  annotated: number
  by_predicted_type: Record<string, number>
}

export default function GoldenSetAnnotationPage() {
  const [pairs, setPairs] = useState<GoldenPair[]>([])
  const [stats, setStats] = useState<GoldenSetStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [currentIdx, setCurrentIdx] = useState(0)
  const [showAll, setShowAll] = useState(false)
  const [filterType, setFilterType] = useState<string>('all')
  const [customLabel, setCustomLabel] = useState<string>('')
  const [notes, setNotes] = useState<string>('')

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE_URL}/api/admin/relations/golden-set`, {
        headers: getAuthHeaders(),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setPairs(data.pairs)
      setStats(data.stats)

      // Position au premier non-annoté
      const firstUnannotatedIdx = data.pairs.findIndex((p: GoldenPair) => p.human_label === null)
      if (firstUnannotatedIdx >= 0) setCurrentIdx(firstUnannotatedIdx)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  const submitAnnotation = async (label: string, customNotes?: string) => {
    const pair = pairs[currentIdx]
    if (!pair) return

    try {
      const res = await fetch(`${API_BASE_URL}/api/admin/relations/golden-set/${pair.golden_id}`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({
          human_label: label,
          human_notes: customNotes || notes || null,
        }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)

      // Update local state
      const updated = [...pairs]
      updated[currentIdx] = { ...pair, human_label: label, human_notes: customNotes || notes || null }
      setPairs(updated)
      setNotes('')
      setCustomLabel('')

      // Position au prochain non-annoté
      const nextIdx = updated.findIndex((p, i) => i > currentIdx && p.human_label === null)
      if (nextIdx >= 0) setCurrentIdx(nextIdx)

      // Update stats
      if (stats) setStats({ ...stats, annotated: updated.filter(p => p.human_label !== null).length })
    } catch (e) {
      console.error(e)
    }
  }

  const filteredPairs = filterType === 'all'
    ? pairs
    : pairs.filter(p => p.predicted_type === filterType)

  const currentPair = pairs[currentIdx]

  if (loading) return <Box p={6}><Spinner color="var(--accent)" /></Box>

  return (
    <Box p={6} maxW="1400px" mx="auto" color="var(--fg-primary)">
      <VStack align="stretch" spacing={6}>
        {/* Header + stats */}
        <Box>
          <Text fontSize="2xl" fontWeight="bold" mb={2}>Golden Set Annotation (S3.F)</Text>
          <Text fontSize="sm" color="var(--fg-muted)" mb={3}>
            Annoter chaque paire prédite : <strong>Correct</strong> = le classifier a raison,
            <strong> Wrong type</strong> = mauvaise classification (préciser le bon type),
            <strong> Rejected</strong> = la paire ne devrait pas exister du tout.
          </Text>
          {stats && (
            <HStack spacing={4}>
              <Tag size="lg" bg="var(--accent-soft)" color="var(--accent)">
                {stats.annotated} / {stats.total} annotées
              </Tag>
              <Tag size="lg" bg="var(--bg-surface-alt)" color="var(--fg-secondary)">
                {stats.total - stats.annotated} restantes
              </Tag>
            </HStack>
          )}
        </Box>

        {/* Mode toggle */}
        <HStack>
          <Button
            size="sm"
            bg={!showAll ? 'var(--accent)' : 'var(--bg-surface-alt)'}
            color={!showAll ? 'var(--accent-on)' : 'var(--fg-primary)'}
            onClick={() => setShowAll(false)}
          >
            Mode annotation (one by one)
          </Button>
          <Button
            size="sm"
            bg={showAll ? 'var(--accent)' : 'var(--bg-surface-alt)'}
            color={showAll ? 'var(--accent-on)' : 'var(--fg-primary)'}
            onClick={() => setShowAll(true)}
          >
            Voir toutes les annotations
          </Button>
          {showAll && (
            <Select
              size="sm"
              maxW="200px"
              value={filterType}
              onChange={(e) => setFilterType(e.target.value)}
              bg="var(--bg-surface)"
              color="var(--fg-primary)"
            >
              <option value="all">Tous les types</option>
              {Object.keys(stats?.by_predicted_type || {}).map(t => (
                <option key={t} value={t}>{t} ({stats?.by_predicted_type[t]})</option>
              ))}
            </Select>
          )}
        </HStack>

        {/* Mode annotation */}
        {!showAll && currentPair && (
          <Box bg="var(--bg-surface)" p={6} borderRadius="lg" border="1px solid" borderColor="var(--border-default)">
            <HStack mb={3} flexWrap="wrap" gap={2}>
              <Text fontSize="xs" color="var(--fg-muted)">Paire {currentIdx + 1} / {pairs.length}</Text>
              <Box bg="var(--accent-soft)" color="var(--accent)" px={2} py={1} borderRadius="md" fontSize="sm" fontWeight="bold">
                Predicted: {currentPair.predicted_type}
              </Box>
              <Tag bg="var(--bg-surface-alt)" color="var(--fg-secondary)">{currentPair.predicted_strength}</Tag>
              <Tag bg="var(--bg-surface-alt)" color="var(--fg-secondary)">conf: {currentPair.predicted_confidence.toFixed(2)}</Tag>
              {currentPair.predicted_is_contradiction && (
                <Tag bg="var(--error-base)" color="var(--error-on)">VRAIE CONTRADICTION</Tag>
              )}
              {currentPair.scope_alignment && (
                <Tag bg="var(--bg-surface-alt)" color="var(--fg-muted)">scope: {currentPair.scope_alignment}</Tag>
              )}
              {currentPair.temporal_relation && (
                <Tag bg="var(--bg-surface-alt)" color="var(--fg-muted)">temp: {currentPair.temporal_relation}</Tag>
              )}
            </HStack>

            <SimpleGrid columns={{ base: 1, md: 2 }} spacing={3} mb={4}>
              <Box bg="var(--bg-surface-alt)" p={3} borderRadius="md">
                <Text fontSize="xs" color="var(--fg-muted)" mb={1}>
                  <strong>A</strong> · doc: <Box as="code" bg="var(--bg-canvas)" px={1} borderRadius="sm">{currentPair.a_doc_id}</Box>
                </Text>
                <Text fontSize="sm">{currentPair.a_text}</Text>
              </Box>
              <Box bg="var(--bg-surface-alt)" p={3} borderRadius="md">
                <Text fontSize="xs" color="var(--fg-muted)" mb={1}>
                  <strong>B</strong> · doc: <Box as="code" bg="var(--bg-canvas)" px={1} borderRadius="sm">{currentPair.b_doc_id}</Box>
                </Text>
                <Text fontSize="sm">{currentPair.b_text}</Text>
              </Box>
            </SimpleGrid>

            {currentPair.predicted_reasoning && (
              <Box bg="var(--bg-surface-alt)" p={3} borderRadius="md" mb={4}>
                <Text fontSize="xs" color="var(--fg-muted)" mb={1}><strong>Reasoning du LLM</strong></Text>
                <Text fontSize="sm" fontStyle="italic" color="var(--fg-secondary)">{currentPair.predicted_reasoning}</Text>
              </Box>
            )}

            {/* Notes optionnelles */}
            <Textarea
              placeholder="Notes (optionnel) — ex: pourquoi tu rejettes, ou quel type devrait être le bon"
              size="sm"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              bg="var(--bg-surface)"
              color="var(--fg-primary)"
              mb={4}
            />

            {/* Action buttons */}
            <HStack flexWrap="wrap" spacing={2}>
              <Button
                bg="var(--success-base)"
                color="var(--success-on)"
                _hover={{ opacity: 0.85 }}
                leftIcon={<Icon as={FiCheck} />}
                onClick={() => submitAnnotation(currentPair.predicted_type)}
              >
                Correct ({currentPair.predicted_type})
              </Button>

              <HStack>
                <Select
                  size="md"
                  placeholder="Wrong type → autre"
                  value={customLabel}
                  onChange={(e) => setCustomLabel(e.target.value)}
                  bg="var(--bg-surface)"
                  color="var(--fg-primary)"
                  maxW="200px"
                >
                  {V33_TYPES.filter(t => t !== currentPair.predicted_type && t !== 'REJECTED').map(t => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                </Select>
                <Button
                  bg="var(--warning-base)"
                  color="var(--warning-on)"
                  _hover={{ opacity: 0.85 }}
                  isDisabled={!customLabel}
                  onClick={() => submitAnnotation(customLabel)}
                >
                  Wrong type
                </Button>
              </HStack>

              <Button
                bg="var(--error-base)"
                color="var(--error-on)"
                _hover={{ opacity: 0.85 }}
                leftIcon={<Icon as={FiX} />}
                onClick={() => submitAnnotation('REJECTED')}
              >
                Rejected (n'aurait pas dû être créée)
              </Button>

              <Button
                variant="outline"
                leftIcon={<Icon as={FiSkipForward} />}
                onClick={() => {
                  const nextIdx = pairs.findIndex((p, i) => i > currentIdx && p.human_label === null)
                  if (nextIdx >= 0) setCurrentIdx(nextIdx)
                }}
              >
                Skip
              </Button>
            </HStack>
          </Box>
        )}

        {/* Mode "voir toutes" */}
        {showAll && (
          <VStack align="stretch" spacing={2}>
            {filteredPairs.map((p, i) => (
              <Box key={p.golden_id} bg="var(--bg-surface)" p={3} borderRadius="md" border="1px solid"
                   borderColor={p.human_label === null ? 'var(--warning-base)' : p.human_label === p.predicted_type ? 'var(--success-base)' : 'var(--error-base)'}>
                <HStack justify="space-between" mb={1}>
                  <HStack>
                    <Text fontSize="xs" color="var(--fg-muted)">#{i + 1}</Text>
                    <Tag bg="var(--accent-soft)" color="var(--accent)">{p.predicted_type}</Tag>
                    <Tag bg="var(--bg-surface-alt)" color="var(--fg-secondary)">conf: {p.predicted_confidence.toFixed(2)}</Tag>
                  </HStack>
                  <Tag bg={p.human_label === null ? 'var(--warning-soft)' : p.human_label === p.predicted_type ? 'var(--success-soft)' : 'var(--error-soft)'}
                       color={p.human_label === null ? 'var(--warning-base)' : p.human_label === p.predicted_type ? 'var(--success-base)' : 'var(--error-base)'}>
                    {p.human_label === null ? 'Non annoté' : p.human_label === p.predicted_type ? '✓ Correct' : `→ ${p.human_label}`}
                  </Tag>
                </HStack>
                <Text fontSize="xs" color="var(--fg-muted)" mb={1}>A: {p.a_text.slice(0, 100)}...</Text>
                <Text fontSize="xs" color="var(--fg-muted)">B: {p.b_text.slice(0, 100)}...</Text>
              </Box>
            ))}
          </VStack>
        )}
      </VStack>
    </Box>
  )
}
