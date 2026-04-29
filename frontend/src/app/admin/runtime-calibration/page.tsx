'use client'

/**
 * R7.A — Runtime Calibration page.
 *
 * Permet de soumettre un mini-golden-set (questions + human_score) au runtime V1.1
 * et d'afficher la corrélation Pearson kg_trust vs eval humaine, ainsi que
 * la distribution des trust levels et le taux de hallucination potentiel.
 */

import { useState, useCallback } from 'react'
import {
  Box,
  Text,
  VStack,
  HStack,
  Badge,
  Spinner,
  Icon,
  Button,
  Textarea,
  Code,
  Tooltip,
  Divider,
  SimpleGrid,
} from '@chakra-ui/react'
import {
  FiTarget,
  FiPlay,
  FiAlertTriangle,
  FiInfo,
  FiCheckCircle,
} from 'react-icons/fi'

const API_BASE_URL = typeof window !== 'undefined'
  ? (process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000')
  : 'http://localhost:8000'

const getAuthHeaders = () => ({
  'Content-Type': 'application/json',
  Authorization: `Bearer ${localStorage.getItem('auth_token') || ''}`,
})

const SAMPLE_GOLDEN_SET = `[
  {
    "question": "What contradictions exist in the corpus on dual-use frequency changers?",
    "human_score": 0.95,
    "expected_mode": "CONFLICT_RISK",
    "expected_regime": "KG_LED"
  },
  {
    "question": "What was the rule for Halon 1301 in 2018?",
    "human_score": 0.55,
    "expected_mode": "SNAPSHOT_TEMPORAL",
    "expected_regime": "KG_LED"
  },
  {
    "question": "Which rules apply to lasers above 0.002 J per pulse?",
    "human_score": 0.85,
    "expected_mode": "APPLICABILITY_QUERY",
    "expected_regime": "KG_LED"
  }
]`

interface CalibItem {
  question: string
  human_score: number
  kg_trust: number
  trust_level: string
  detected_mode: string
  expected_mode?: string
  mode_correct?: boolean
  detected_regime: string
  expected_regime?: string
  regime_correct?: boolean
  n_evidence: number
}

interface CalibResult {
  pearson_r: number
  n_items: number
  n_high_confidence_wrong: number
  n_low_confidence_correct: number
  avg_kg_trust: number
  avg_human_score: number
  mode_accuracy?: number
  regime_accuracy?: number
  trust_level_distribution: Record<string, number>
  items: CalibItem[]
}

export default function RuntimeCalibrationPage() {
  const [persona, setPersona] = useState('explorer')
  const [goldenJson, setGoldenJson] = useState(SAMPLE_GOLDEN_SET)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<CalibResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const run = useCallback(async () => {
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      let items: any
      try {
        items = JSON.parse(goldenJson)
      } catch (e: any) {
        throw new Error(`JSON invalide : ${e.message}`)
      }
      if (!Array.isArray(items)) throw new Error('Le golden set doit être un array')

      const res = await fetch(`${API_BASE_URL}/api/admin/runtime/calibration/run`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({ items, persona }),
      })
      if (!res.ok) {
        const errBody = await res.text()
        throw new Error(`HTTP ${res.status}: ${errBody}`)
      }
      const data = await res.json()
      setResult(data)
    } catch (e: any) {
      setError(e.message || 'Calibration failed')
    } finally {
      setLoading(false)
    }
  }, [goldenJson, persona])

  return (
    <Box p={6} maxW="1400px" mx="auto">
      <VStack align="stretch" spacing={6}>
        <Box>
          <HStack spacing={3} mb={2}>
            <Icon as={FiTarget} boxSize={6} color="var(--accent-base)" />
            <Text fontSize="2xl" fontWeight="bold" color="var(--text-primary)">
              Runtime V1.1 — Calibration kg_trust
            </Text>
          </HStack>
          <Text fontSize="sm" color="var(--text-secondary)">
            Soumets un golden set (questions + human_score 0-1) pour calculer la corrélation
            Pearson entre kg_trust et l'évaluation humaine. Cible : Pearson ≥ 0.7.
          </Text>
        </Box>

        <Box p={5} bg="var(--bg-surface)" border="1px solid var(--border-default)" borderRadius="lg">
          <VStack align="stretch" spacing={4}>
            <Box>
              <Text fontSize="sm" fontWeight="semibold" mb={2} color="var(--text-primary)">
                Golden set (JSON array)
              </Text>
              <Textarea
                value={goldenJson}
                onChange={(e) => setGoldenJson(e.target.value)}
                rows={12}
                fontFamily="mono"
                fontSize="xs"
                bg="var(--bg-elevated)"
                color="var(--text-primary)"
                borderColor="var(--border-default)"
              />
              <Text fontSize="xs" color="var(--text-secondary)" mt={1}>
                Champs : <Code fontSize="xs">question</Code>,{' '}
                <Code fontSize="xs">human_score</Code> (0-1), optionnel{' '}
                <Code fontSize="xs">expected_mode</Code>,{' '}
                <Code fontSize="xs">expected_regime</Code>
              </Text>
            </Box>
            <HStack>
              <select
                value={persona}
                onChange={(e) => setPersona(e.target.value)}
                style={{
                  padding: '8px 12px',
                  borderRadius: '6px',
                  background: 'var(--bg-elevated)',
                  color: 'var(--text-primary)',
                  border: '1px solid var(--border-default)',
                }}
              >
                <option value="explorer">explorer</option>
                <option value="compliance_officer">compliance_officer</option>
                <option value="reader">reader</option>
              </select>
              <Button
                onClick={run}
                isDisabled={loading}
                colorScheme="blue"
                leftIcon={<FiPlay />}
              >
                {loading ? 'Running…' : 'Run calibration'}
              </Button>
            </HStack>
          </VStack>
        </Box>

        {error && (
          <Box p={4} bg="var(--bg-elevated)" border="1px solid var(--danger-base)" borderRadius="lg">
            <HStack>
              <Icon as={FiAlertTriangle} color="var(--danger-base)" />
              <Text color="var(--danger-base)" fontWeight="semibold">{error}</Text>
            </HStack>
          </Box>
        )}

        {loading && (
          <Box p={8} textAlign="center">
            <Spinner size="lg" color="var(--accent-base)" />
          </Box>
        )}

        {result && !loading && <CalibrationResults result={result} />}
      </VStack>
    </Box>
  )
}

function CalibrationResults({ result }: { result: CalibResult }) {
  const pearsonColor =
    result.pearson_r >= 0.7 ? 'var(--success-base)' :
    result.pearson_r >= 0.4 ? 'var(--warning-base)' :
    'var(--danger-base)'

  return (
    <VStack align="stretch" spacing={5}>
      {/* Headline */}
      <Box p={5} bg="var(--bg-surface)" border="1px solid var(--border-default)" borderRadius="lg">
        <Text fontSize="xs" fontWeight="bold" color="var(--text-secondary)" mb={3}>
          MÉTRIQUES GLOBALES
        </Text>
        <SimpleGrid columns={[2, 4]} spacing={4}>
          <Tooltip label="Cible R7 ≥ 0.7. Corrélation linéaire kg_trust vs human_score." placement="top">
            <Box>
              <Text fontSize="xs" color="var(--text-secondary)">Pearson r</Text>
              <Text fontSize="2xl" fontWeight="bold" color={pearsonColor}>
                {result.pearson_r.toFixed(3)}
              </Text>
            </Box>
          </Tooltip>
          <Box>
            <Text fontSize="xs" color="var(--text-secondary)">Items</Text>
            <Text fontSize="2xl" fontWeight="bold" color="var(--text-primary)">{result.n_items}</Text>
          </Box>
          <Box>
            <Text fontSize="xs" color="var(--text-secondary)">Avg kg_trust</Text>
            <Text fontSize="2xl" fontWeight="bold" color="var(--text-primary)">{result.avg_kg_trust.toFixed(2)}</Text>
          </Box>
          <Box>
            <Text fontSize="xs" color="var(--text-secondary)">Avg human</Text>
            <Text fontSize="2xl" fontWeight="bold" color="var(--text-primary)">{result.avg_human_score.toFixed(2)}</Text>
          </Box>
        </SimpleGrid>
      </Box>

      {/* Risk indicators */}
      <Box p={5} bg="var(--bg-surface)" border="1px solid var(--border-default)" borderRadius="lg">
        <Text fontSize="xs" fontWeight="bold" color="var(--text-secondary)" mb={3}>
          INDICATEURS DE RISQUE
        </Text>
        <SimpleGrid columns={[1, 2]} spacing={4}>
          <Box p={3} bg="var(--bg-elevated)" borderRadius="md" borderLeft="3px solid var(--danger-base)">
            <HStack mb={1}>
              <Icon as={FiAlertTriangle} color="var(--danger-base)" />
              <Text fontSize="sm" fontWeight="bold" color="var(--text-primary)">Sur-confiance (hallucination)</Text>
            </HStack>
            <Text fontSize="2xl" fontWeight="bold" color="var(--danger-base)">
              {result.n_high_confidence_wrong}
            </Text>
            <Text fontSize="xs" color="var(--text-secondary)">
              kg_trust ≥ 0.85 mais human &lt; 0.5
            </Text>
          </Box>
          <Box p={3} bg="var(--bg-elevated)" borderRadius="md" borderLeft="3px solid var(--warning-base)">
            <HStack mb={1}>
              <Icon as={FiInfo} color="var(--warning-base)" />
              <Text fontSize="sm" fontWeight="bold" color="var(--text-primary)">Sous-confiance</Text>
            </HStack>
            <Text fontSize="2xl" fontWeight="bold" color="var(--warning-base)">
              {result.n_low_confidence_correct}
            </Text>
            <Text fontSize="xs" color="var(--text-secondary)">
              kg_trust &lt; 0.65 mais human ≥ 0.5
            </Text>
          </Box>
        </SimpleGrid>
      </Box>

      {/* Mode/Regime accuracy */}
      {(result.mode_accuracy !== undefined || result.regime_accuracy !== undefined) && (
        <Box p={5} bg="var(--bg-surface)" border="1px solid var(--border-default)" borderRadius="lg">
          <Text fontSize="xs" fontWeight="bold" color="var(--text-secondary)" mb={3}>
            DÉTECTION MODE / RÉGIME
          </Text>
          <SimpleGrid columns={[1, 2]} spacing={4}>
            {result.mode_accuracy !== undefined && (
              <Box>
                <Text fontSize="xs" color="var(--text-secondary)">Mode accuracy</Text>
                <Text fontSize="xl" fontWeight="bold" color="var(--text-primary)">
                  {(result.mode_accuracy * 100).toFixed(0)}%
                </Text>
              </Box>
            )}
            {result.regime_accuracy !== undefined && (
              <Box>
                <Text fontSize="xs" color="var(--text-secondary)">Regime accuracy</Text>
                <Text fontSize="xl" fontWeight="bold" color="var(--text-primary)">
                  {(result.regime_accuracy * 100).toFixed(0)}%
                </Text>
              </Box>
            )}
          </SimpleGrid>
        </Box>
      )}

      {/* Trust level distribution */}
      <Box p={5} bg="var(--bg-surface)" border="1px solid var(--border-default)" borderRadius="lg">
        <Text fontSize="xs" fontWeight="bold" color="var(--text-secondary)" mb={3}>
          DISTRIBUTION TRUST LEVELS
        </Text>
        <HStack spacing={3} flexWrap="wrap">
          {Object.entries(result.trust_level_distribution).map(([level, count]) => (
            <Badge
              key={level}
              colorScheme={
                level === 'AUTHORITATIVE' ? 'green' :
                level === 'RELIABLE' ? 'cyan' :
                level === 'PARTIAL' ? 'orange' : 'red'
              }
              fontSize="sm"
              px={3}
              py={1}
            >
              {level} : {count}
            </Badge>
          ))}
        </HStack>
      </Box>

      {/* Per-item details */}
      <Box p={5} bg="var(--bg-surface)" border="1px solid var(--border-default)" borderRadius="lg">
        <Text fontSize="xs" fontWeight="bold" color="var(--text-secondary)" mb={3}>
          DÉTAIL PAR QUESTION
        </Text>
        <VStack align="stretch" spacing={2}>
          {result.items.map((item, i) => {
            const delta = item.kg_trust - item.human_score
            const isRisk = item.kg_trust >= 0.85 && item.human_score < 0.5
            const isUndershoot = item.kg_trust < 0.65 && item.human_score >= 0.5
            return (
              <Box
                key={i}
                p={3}
                bg="var(--bg-elevated)"
                borderRadius="md"
                borderLeft={`3px solid ${
                  isRisk ? 'var(--danger-base)' :
                  isUndershoot ? 'var(--warning-base)' :
                  'var(--success-base)'
                }`}
              >
                <Text fontSize="sm" color="var(--text-primary)" mb={1}>
                  {item.question}
                </Text>
                <HStack flexWrap="wrap" spacing={2}>
                  <Badge size="sm" colorScheme="cyan">human: {item.human_score.toFixed(2)}</Badge>
                  <Badge size="sm" colorScheme="purple">kg_trust: {item.kg_trust.toFixed(2)}</Badge>
                  <Badge size="sm" variant="outline">Δ: {delta >= 0 ? '+' : ''}{delta.toFixed(2)}</Badge>
                  <Badge size="sm">{item.trust_level}</Badge>
                  <Badge size="sm" variant="subtle">{item.detected_mode}</Badge>
                  {item.mode_correct === false && (
                    <Badge size="sm" colorScheme="red">mode KO ({item.expected_mode} attendu)</Badge>
                  )}
                  {item.mode_correct === true && (
                    <Badge size="sm" colorScheme="green"><Icon as={FiCheckCircle} mr={1} />mode OK</Badge>
                  )}
                  <Text fontSize="xs" color="var(--text-secondary)">
                    {item.n_evidence} evidence
                  </Text>
                </HStack>
              </Box>
            )
          })}
        </VStack>
      </Box>
    </VStack>
  )
}
