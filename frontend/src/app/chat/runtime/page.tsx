'use client'

/**
 * R7 — Runtime V1.1 Chat (raisonnement-aware)
 *
 * Page de test du pipeline runtime V1.1 :
 * - Indicateur mode (1 sur 7) + régime (RAG_LED / KG_LED / HYBRID)
 * - Trust gauge + breakdown 4 axes (provenance / inference / recency / regime)
 * - 5 sections + business block modulable
 * - Drill-down typé par mode
 * - Persona switcher (compliance_officer / explorer / reader)
 *
 * Theme-aware : utilise les CSS variables du preset (Fusion / Dark Elegance).
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
  Select,
  Divider,
  Code,
  Tooltip,
} from '@chakra-ui/react'
import {
  FiSearch,
  FiZap,
  FiAlertTriangle,
  FiCheckCircle,
  FiClock,
  FiActivity,
  FiBookOpen,
  FiInfo,
  FiUser,
  FiTarget,
} from 'react-icons/fi'

const API_BASE_URL = typeof window !== 'undefined'
  ? (process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000')
  : 'http://localhost:8000'

const getAuthHeaders = () => ({
  'Content-Type': 'application/json',
  Authorization: `Bearer ${localStorage.getItem('auth_token') || ''}`,
})

// ── Types ──────────────────────────────────────────────────────────────

interface EvidenceItem {
  claim_id: string
  text: string
  doc_id: string
  publication_date?: string
  validity_start?: string
  validity_end?: string
  lifecycle_status?: string
  relation_type?: string
}

interface TrustScoreOut {
  score: number
  level: string
  breakdown: { provenance: number; inference: number; recency: number; regime: number }
  notes: string[]
}

interface RuntimeQueryResponse {
  short_answer: string
  conditions: string[]
  business_block: any
  evidence: EvidenceItem[]
  confidence: TrustScoreOut
  drill_down: { label: string; url: string }[]
  mode: string
  regime: string
  debug_info: Record<string, any>
}

const MODE_COLORS: Record<string, string> = {
  LOOKUP_FACTUAL: 'cyan',
  APPLICABILITY_QUERY: 'blue',
  SNAPSHOT_TEMPORAL: 'purple',
  DIFF_EVOLUTION: 'pink',
  CONFLICT_RISK: 'red',
  EXPLORATION_RELATIONAL: 'orange',
  SYNTHESIS_SUMMARY: 'green',
}

const REGIME_COLORS: Record<string, string> = {
  RAG_LED: 'cyan',
  KG_LED: 'purple',
  HYBRID: 'green',
}

const TRUST_COLORS: Record<string, string> = {
  AUTHORITATIVE: 'green',
  RELIABLE: 'cyan',
  PARTIAL: 'orange',
  FALLBACK: 'red',
}

// ── Component ──────────────────────────────────────────────────────────

export default function RuntimeChatPage() {
  const [question, setQuestion] = useState('')
  const [persona, setPersona] = useState<string>('explorer')
  const [loading, setLoading] = useState(false)
  const [response, setResponse] = useState<RuntimeQueryResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  const submit = useCallback(async () => {
    if (!question.trim()) return
    setLoading(true)
    setError(null)
    setResponse(null)
    try {
      const res = await fetch(`${API_BASE_URL}/api/runtime/query`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({
          question: question.trim(),
          persona,
          synthesize: true,
        }),
      })
      if (!res.ok) {
        const errBody = await res.text()
        throw new Error(`HTTP ${res.status}: ${errBody}`)
      }
      const data = await res.json()
      setResponse(data)
    } catch (e: any) {
      setError(e.message || 'Query failed')
    } finally {
      setLoading(false)
    }
  }, [question, persona])

  return (
    <Box p={6} maxW="1400px" mx="auto">
      <VStack align="stretch" spacing={6}>
        {/* Header */}
        <Box>
          <HStack spacing={3} mb={2}>
            <Icon as={FiZap} boxSize={6} color="var(--accent-base)" />
            <Text fontSize="2xl" fontWeight="bold" color="var(--text-primary)">
              Runtime V1.1 — Chat raisonnement-aware
            </Text>
          </HStack>
          <Text fontSize="sm" color="var(--text-secondary)">
            Pipeline : Query Resolver → Evidence Planner → Retrieval → Trust Evaluator → Response Composer.
            Visualise le mode, le régime, les preuves typées et le score kg_trust.
          </Text>
        </Box>

        {/* Form */}
        <Box
          p={5}
          bg="var(--bg-surface)"
          border="1px solid var(--border-default)"
          borderRadius="lg"
        >
          <VStack align="stretch" spacing={4}>
            <Box>
              <Text fontSize="sm" fontWeight="semibold" mb={2} color="var(--text-primary)">
                <Icon as={FiSearch} mr={2} /> Question
              </Text>
              <Textarea
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="Ex: What contradictions exist on ETOPS deviations? — Quel était le seuil en 2018? — Summarize the dual-use regulation"
                rows={3}
                bg="var(--bg-elevated)"
                color="var(--text-primary)"
                borderColor="var(--border-default)"
              />
            </Box>

            <HStack spacing={4} align="end">
              <Box flex={1}>
                <Text fontSize="sm" fontWeight="semibold" mb={2} color="var(--text-primary)">
                  <Icon as={FiUser} mr={2} /> Persona
                </Text>
                <Select
                  value={persona}
                  onChange={(e) => setPersona(e.target.value)}
                  bg="var(--bg-elevated)"
                  color="var(--text-primary)"
                  borderColor="var(--border-default)"
                >
                  <option value="explorer">Explorer (default — permissive, exploratory)</option>
                  <option value="compliance_officer">Compliance Officer (strict, audit trail max)</option>
                  <option value="reader">Reader (concise, executive style)</option>
                </Select>
              </Box>
              <Button
                onClick={submit}
                isDisabled={!question.trim() || loading}
                colorScheme="blue"
                leftIcon={<FiSearch />}
              >
                {loading ? 'Querying…' : 'Query'}
              </Button>
            </HStack>
          </VStack>
        </Box>

        {/* Error */}
        {error && (
          <Box
            p={4}
            bg="var(--bg-elevated)"
            border="1px solid var(--danger-base)"
            borderRadius="lg"
          >
            <HStack>
              <Icon as={FiAlertTriangle} color="var(--danger-base)" />
              <Text color="var(--danger-base)" fontWeight="semibold">Error: {error}</Text>
            </HStack>
          </Box>
        )}

        {/* Loading */}
        {loading && (
          <Box p={8} textAlign="center">
            <Spinner size="lg" color="var(--accent-base)" />
          </Box>
        )}

        {/* Response */}
        {response && !loading && <RuntimeResponseView response={response} />}
      </VStack>
    </Box>
  )
}

// ── Response View ──────────────────────────────────────────────────────

function RuntimeResponseView({ response }: { response: RuntimeQueryResponse }) {
  const modeColor = MODE_COLORS[response.mode] || 'gray'
  const regimeColor = REGIME_COLORS[response.regime] || 'gray'
  const trustColor = TRUST_COLORS[response.confidence.level] || 'gray'

  return (
    <VStack align="stretch" spacing={5}>
      {/* Mode + Regime + Trust badges */}
      <HStack spacing={4} flexWrap="wrap">
        <Badge colorScheme={modeColor} fontSize="sm" px={3} py={1}>
          <Icon as={FiTarget} mr={1} /> Mode : {response.mode}
        </Badge>
        <Badge colorScheme={regimeColor} fontSize="sm" px={3} py={1}>
          <Icon as={FiActivity} mr={1} /> Régime : {response.regime}
        </Badge>
        <Badge colorScheme={trustColor} fontSize="sm" px={3} py={1}>
          <Icon as={FiCheckCircle} mr={1} /> Trust : {response.confidence.score.toFixed(2)} ({response.confidence.level})
        </Badge>
        {response.debug_info?.persona && (
          <Badge fontSize="sm" px={3} py={1} variant="outline" borderColor="var(--border-default)" color="var(--text-secondary)">
            <Icon as={FiUser} mr={1} /> Persona : {response.debug_info.persona}
          </Badge>
        )}
        {response.debug_info?.fallback_strategy && response.debug_info.fallback_strategy !== 'NONE' && (
          <Badge colorScheme="orange" fontSize="sm" px={3} py={1}>
            <Icon as={FiAlertTriangle} mr={1} /> Fallback : {response.debug_info.fallback_strategy}
          </Badge>
        )}
        {response.debug_info?.escalation_triggered && (
          <Badge colorScheme="purple" fontSize="sm" px={3} py={1}>
            <Icon as={FiZap} mr={1} /> Escalation
          </Badge>
        )}
      </HStack>

      {/* Section 1: Short answer */}
      <Box
        p={5}
        bg="var(--bg-surface)"
        border="1px solid var(--accent-base)"
        borderRadius="lg"
      >
        <Text fontSize="xs" fontWeight="bold" color="var(--accent-base)" mb={2}>
          1. RÉPONSE COURTE
        </Text>
        <Text color="var(--text-primary)" whiteSpace="pre-wrap">{response.short_answer}</Text>
      </Box>

      {/* Section 2: Conditions */}
      {response.conditions && response.conditions.length > 0 && (
        <Box
          p={5}
          bg="var(--bg-surface)"
          border="1px solid var(--border-default)"
          borderRadius="lg"
        >
          <Text fontSize="xs" fontWeight="bold" color="var(--text-secondary)" mb={2}>
            2. CONDITIONS / SCOPE
          </Text>
          <VStack align="stretch" spacing={1}>
            {response.conditions.map((c, i) => (
              <Text key={i} fontSize="sm" color="var(--text-primary)">• {c}</Text>
            ))}
          </VStack>
        </Box>
      )}

      {/* Trust breakdown */}
      <TrustBreakdown trust={response.confidence} />

      {/* Business block */}
      <BusinessBlockView mode={response.mode} block={response.business_block} />

      {/* Section 3: Evidence */}
      {response.evidence && response.evidence.length > 0 && (
        <Box
          p={5}
          bg="var(--bg-surface)"
          border="1px solid var(--border-default)"
          borderRadius="lg"
        >
          <Text fontSize="xs" fontWeight="bold" color="var(--text-secondary)" mb={3}>
            3. PREUVES VERBATIM ({response.evidence.length})
          </Text>
          <VStack align="stretch" spacing={3}>
            {response.evidence.map((e, i) => (
              <Box
                key={i}
                p={3}
                bg="var(--bg-elevated)"
                borderRadius="md"
                borderLeft="3px solid var(--accent-base)"
              >
                <HStack mb={1} flexWrap="wrap">
                  <Code fontSize="xs">{e.doc_id}</Code>
                  {e.publication_date && (
                    <Badge size="sm" variant="subtle" colorScheme="cyan">
                      <Icon as={FiClock} mr={1} /> pub: {e.publication_date}
                    </Badge>
                  )}
                  {e.validity_start && (
                    <Badge size="sm" variant="subtle" colorScheme="purple">
                      valid_from: {e.validity_start}
                    </Badge>
                  )}
                  {e.lifecycle_status && e.lifecycle_status !== 'UNKNOWN' && (
                    <Badge size="sm" colorScheme={
                      e.lifecycle_status === 'ACTIVE' ? 'green' :
                      ['WITHDRAWN', 'REPEALED', 'DEPRECATED', 'SUPERSEDED'].includes(e.lifecycle_status) ? 'red' :
                      'gray'
                    }>
                      {e.lifecycle_status}
                    </Badge>
                  )}
                  {e.relation_type && (
                    <Badge size="sm" colorScheme="orange">
                      via {e.relation_type}
                    </Badge>
                  )}
                </HStack>
                <Text fontSize="sm" color="var(--text-primary)">{e.text}</Text>
              </Box>
            ))}
          </VStack>
        </Box>
      )}

      {/* Section 5: Drill-down */}
      {response.drill_down && response.drill_down.length > 0 && (
        <Box
          p={5}
          bg="var(--bg-surface)"
          border="1px solid var(--border-default)"
          borderRadius="lg"
        >
          <Text fontSize="xs" fontWeight="bold" color="var(--text-secondary)" mb={3}>
            5. DRILL-DOWN
          </Text>
          <VStack align="stretch" spacing={2}>
            {response.drill_down.map((d, i) => (
              <Button
                key={i}
                as="a"
                href={d.url}
                size="sm"
                variant="outline"
                justifyContent="flex-start"
                leftIcon={<FiBookOpen />}
                color="var(--text-primary)"
                borderColor="var(--border-default)"
                _hover={{ bg: 'var(--bg-elevated)' }}
              >
                {d.label}
              </Button>
            ))}
          </VStack>
        </Box>
      )}

      {/* Debug info */}
      <Box
        p={4}
        bg="var(--bg-surface)"
        border="1px dashed var(--border-default)"
        borderRadius="lg"
      >
        <Text fontSize="xs" fontWeight="bold" color="var(--text-secondary)" mb={2}>
          <Icon as={FiInfo} mr={1} /> DEBUG INFO
        </Text>
        <Code fontSize="xs" w="100%" whiteSpace="pre-wrap" bg="var(--bg-elevated)" p={2}>
          {JSON.stringify(response.debug_info, null, 2)}
        </Code>
      </Box>
    </VStack>
  )
}

// ── Trust Breakdown ────────────────────────────────────────────────────

function TrustBreakdown({ trust }: { trust: TrustScoreOut }) {
  const axes: Array<[string, number, string]> = [
    ['Provenance', trust.breakdown.provenance, 'Qualité des sources (validity_start, doc_id)'],
    ['Inference', trust.breakdown.inference, 'Qualité des LOGICAL_RELATION (confidence, derived ratio)'],
    ['Recency', trust.breakdown.recency, 'Décay exponentiel sur 5 ans'],
    ['Regime', trust.breakdown.regime, 'Adéquation régime ↔ mode'],
  ]
  return (
    <Box
      p={5}
      bg="var(--bg-surface)"
      border="1px solid var(--border-default)"
      borderRadius="lg"
    >
      <Text fontSize="xs" fontWeight="bold" color="var(--text-secondary)" mb={3}>
        4. CONFIANCE — kg_trust = {trust.score.toFixed(2)} ({trust.level})
      </Text>
      <VStack align="stretch" spacing={2}>
        {axes.map(([label, value, hint]) => (
          <Tooltip key={label} label={hint} placement="left">
            <HStack>
              <Text fontSize="sm" w="100px" color="var(--text-primary)">{label}</Text>
              <Box flex={1} h="6px" bg="var(--bg-elevated)" borderRadius="full" overflow="hidden">
                <Box
                  h="100%"
                  w={`${value * 100}%`}
                  bg={value >= 0.7 ? 'var(--success-base)' : value >= 0.4 ? 'var(--warning-base)' : 'var(--danger-base)'}
                />
              </Box>
              <Text fontSize="sm" w="50px" textAlign="right" color="var(--text-primary)">
                {value.toFixed(2)}
              </Text>
            </HStack>
          </Tooltip>
        ))}
      </VStack>
      {trust.notes && trust.notes.length > 0 && (
        <Box mt={3} p={3} bg="var(--bg-elevated)" borderRadius="md">
          <Text fontSize="xs" color="var(--text-secondary)" mb={1}>Notes :</Text>
          {trust.notes.map((n, i) => (
            <Text key={i} fontSize="xs" color="var(--text-secondary)">• {n}</Text>
          ))}
        </Box>
      )}
    </Box>
  )
}

// ── Business Block ─────────────────────────────────────────────────────

function BusinessBlockView({ mode, block }: { mode: string; block: any }) {
  if (!block || Object.keys(block).length === 0) return null

  const renderContent = () => {
    if (block.type === 'snapshot') {
      return (
        <VStack align="stretch" spacing={2}>
          <HStack>
            <Icon as={FiClock} color="var(--accent-base)" />
            <Text fontSize="sm" color="var(--text-primary)">
              Snapshot at <Code>{block.as_of || 'unspecified'}</Code> — {block.n_active_at_t || 0} actifs sur {block.n_total_valid || 0} valides
            </Text>
          </HStack>
        </VStack>
      )
    }
    if (block.type === 'diff') {
      const s = block.summary || {}
      return (
        <HStack spacing={4} flexWrap="wrap">
          <Badge colorScheme="green">Introduced : {s.introduced || 0}</Badge>
          <Badge colorScheme="red">Retired : {s.retired || 0}</Badge>
          <Badge colorScheme="orange">Modified : {s.modified || 0}</Badge>
          <Badge colorScheme="cyan">Reaffirmed : {s.reaffirmed || 0}</Badge>
          {block.period && (
            <Text fontSize="xs" color="var(--text-secondary)">
              Période : {block.period.start} → {block.period.end}
            </Text>
          )}
        </HStack>
      )
    }
    if (block.type === 'contradictions') {
      return (
        <VStack align="stretch" spacing={2}>
          <HStack>
            <Badge colorScheme="red">{block.n_real_conflicts || 0} vraies contradictions</Badge>
            <Badge variant="outline" colorScheme="gray">{block.n_total_candidates || 0} candidates totales</Badge>
          </HStack>
          {(block.conflicts || []).slice(0, 3).map((c: any, i: number) => (
            <Box key={i} p={3} bg="var(--bg-elevated)" borderRadius="md" borderLeft="3px solid var(--danger-base)">
              <HStack mb={1}>
                <Badge colorScheme="red" size="sm">conf={c.confidence?.toFixed(2)}</Badge>
                {c.scope_alignment && <Badge size="sm">scope: {c.scope_alignment}</Badge>}
                {c.temporal_relation && <Badge size="sm">temporal: {c.temporal_relation}</Badge>}
              </HStack>
              <Text fontSize="xs" color="var(--text-primary)">
                <Code fontSize="xs">{c.claim_a?.doc_id}</Code> : {c.claim_a?.text}
              </Text>
              <Text fontSize="xs" color="var(--text-primary)" mt={1}>
                <Code fontSize="xs">{c.claim_b?.doc_id}</Code> : {c.claim_b?.text}
              </Text>
              {c.reasoning && (
                <Text fontSize="xs" color="var(--text-secondary)" mt={1} fontStyle="italic">
                  → {c.reasoning}
                </Text>
              )}
            </Box>
          ))}
        </VStack>
      )
    }
    if (block.type === 'navigation') {
      return (
        <VStack align="stretch" spacing={2}>
          <Text fontSize="sm" color="var(--text-secondary)">
            {block.n_total_relations || 0} relations totales
          </Text>
          <HStack flexWrap="wrap" spacing={2}>
            {Object.entries(block.relations_by_type || {}).map(([type, info]: [string, any]) => (
              <Badge key={type} fontSize="sm" px={3} py={1}>
                {type} : {info.count || info}
              </Badge>
            ))}
          </HStack>
        </VStack>
      )
    }
    if (block.type === 'applicable_rules') {
      return (
        <Text fontSize="sm" color="var(--text-primary)">
          {(block.rules || []).length} règles applicables
          {block.withdrawn_excluded?.length > 0 && (
            <Text as="span" color="var(--text-secondary)">
              {' '}(+{block.withdrawn_excluded.length} exclues car withdrawn/superseded)
            </Text>
          )}
        </Text>
      )
    }
    if (block.type === 'summary') {
      return (
        <HStack spacing={4} flexWrap="wrap">
          <Badge>Chunks : {block.n_chunks || 0}</Badge>
          <Badge>Relations : {block.n_relations || 0}</Badge>
          <Badge>Docs : {(block.docs_covered || []).length}</Badge>
        </HStack>
      )
    }
    return (
      <Code fontSize="xs" w="100%" whiteSpace="pre-wrap" bg="var(--bg-elevated)" p={2}>
        {JSON.stringify(block, null, 2)}
      </Code>
    )
  }

  return (
    <Box
      p={5}
      bg="var(--bg-surface)"
      border="1px solid var(--border-default)"
      borderRadius="lg"
    >
      <Text fontSize="xs" fontWeight="bold" color="var(--text-secondary)" mb={3}>
        BLOC MÉTIER ({block.type || 'generic'})
      </Text>
      {renderContent()}
    </Box>
  )
}
