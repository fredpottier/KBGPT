'use client'

/**
 * V2-S5 — Runtime V2 Chat (anchor-driven, simplifié)
 *
 * Frontend pour le pipeline anchor-driven (Vision recentrée 30/04/2026) :
 * - 1 input question + toggle Audit (compliance officer)
 * - Pas de mode-classifier, pas de régime, pas de persona switcher
 * - Affichage selon PipelineDecision :
 *     ANSWERED_AUTHORITATIVE / ANSWERED_SCOPED → claims + anchor + trust
 *     ANSWERED_EVOLUTION → timeline chronologique
 *     ESCALATE_* → message d'escalade au user
 *     AUDIT_REPORT → liste conflicts (vrai vs résolu par lifecycle)
 *
 * Theme-aware : utilise les CSS variables du preset.
 */

import { useState, useCallback } from 'react'
import {
  Box,
  Text,
  VStack,
  HStack,
  Badge,
  Spinner,
  Button,
  Textarea,
  Switch,
  Divider,
  Heading,
  Tag,
  Tooltip,
  Modal,
  ModalOverlay,
  ModalContent,
  ModalHeader,
  ModalBody,
  ModalCloseButton,
  useDisclosure,
} from '@chakra-ui/react'
import { LifecycleGraphMini } from '@/components/runtime/LifecycleGraphMini'

type AnchorType = 'point' | 'range' | 'current_default'

type AnchorScope = {
  version?: string | null
  date?: string | null
  range_start?: string | null
  range_end?: string | null
  extraction_evidence?: string | null
}

type ResolvedAnchor = {
  anchor_type: AnchorType
  scope: AnchorScope
  confidence: number
  reasoning?: string | null
  extraction_method: string
}

type EvidenceClaim = {
  claim_id: string
  doc_id: string
  text: string
  score: number
  publication_date?: string | null
}

type ConflictReport = {
  claim_a_id: string
  claim_b_id: string
  doc_a_id: string
  doc_b_id: string
  confidence: number
  reasoning?: string | null
  is_resolved_by_lifecycle: boolean
  lifecycle_resolution_type?: string | null
}

type EvolutionPoint = {
  doc_id: string
  publication_date?: string | null
  claims: EvidenceClaim[]
}

type PipelineResponse = {
  decision: string
  question: string
  anchor: ResolvedAnchor
  authoritative_doc_ids: string[]
  claims: EvidenceClaim[]
  evolution_points: EvolutionPoint[]
  escalation_message?: string | null
  alternatives: { doc_id: string; confidence: number }[]
  conflicts: ConflictReport[]
  synthesized_answer?: string | null
  trust_score: number
  trust_breakdown: Record<string, unknown>
  diagnostic: Record<string, unknown>
}

const DECISION_LABELS: Record<string, { label: string; color: string }> = {
  answered_authoritative: { label: 'Réponse autoritaire', color: 'green' },
  answered_scoped: { label: 'Réponse scope explicite', color: 'blue' },
  answered_evolution: { label: 'Évolution', color: 'purple' },
  escalate_ambiguous: { label: 'Précision requise', color: 'orange' },
  escalate_no_docs: { label: 'Aucun document', color: 'red' },
  not_found: { label: 'Pas trouvé', color: 'gray' },
  audit_report: { label: 'Audit', color: 'yellow' },
}

const ANCHOR_LABELS: Record<AnchorType, string> = {
  point: 'Cadre ponctuel',
  range: 'Plage / évolution',
  current_default: 'Vérité courante (implicite)',
}

type DocDetail = {
  doc_id: string
  primary_subject?: string | null
  publication_date?: string | null
  lifecycle_status?: string | null
  language?: string | null
  lifecycle_outgoing: { target: string; type: string; confidence: number; evidence_quote?: string | null }[]
  lifecycle_incoming: { source: string; type: string; confidence: number; evidence_quote?: string | null }[]
  n_claims: number
  n_conflicts: number
}

type ClaimDetail = {
  claim_id: string
  doc_id: string
  text: string
  passage_text?: string | null
  publication_date?: string | null
  lifecycle_status?: string | null
  confidence?: number | null
  logical_outgoing: { target_claim_id: string; target_doc_id: string; target_text_preview: string; relation_type: string; confidence: number; reasoning?: string | null }[]
  logical_incoming: { source_claim_id: string; source_doc_id: string; source_text_preview: string; relation_type: string; confidence: number; reasoning?: string | null }[]
  facets: { name: string; confidence: number; level: string }[]
}

export default function RuntimeV2Chat() {
  const [question, setQuestion] = useState('')
  const [auditMode, setAuditMode] = useState(false)
  const [response, setResponse] = useState<PipelineResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // P2.4 — Drill-down modal doc
  const { isOpen: isDocOpen, onOpen: onDocOpen, onClose: onDocClose } = useDisclosure()
  const [docDetail, setDocDetail] = useState<DocDetail | null>(null)
  const [docLoading, setDocLoading] = useState(false)

  const openDocDetail = useCallback(async (docId: string) => {
    setDocLoading(true)
    setDocDetail(null)
    onDocOpen()
    try {
      const res = await fetch(`/api/runtime_v2/doc_detail/${encodeURIComponent(docId)}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setDocDetail(await res.json())
    } catch (exc) {
      console.error('Doc detail failed:', exc)
    } finally {
      setDocLoading(false)
    }
  }, [onDocOpen])

  // P5 polish — Drill-down modal claim
  const { isOpen: isClaimOpen, onOpen: onClaimOpen, onClose: onClaimClose } = useDisclosure()
  const [claimDetail, setClaimDetail] = useState<ClaimDetail | null>(null)
  const [claimLoading, setClaimLoading] = useState(false)

  const openClaimDetail = useCallback(async (claimId: string) => {
    setClaimLoading(true)
    setClaimDetail(null)
    onClaimOpen()
    try {
      const res = await fetch(`/api/runtime_v2/claim_detail/${encodeURIComponent(claimId)}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setClaimDetail(await res.json())
    } catch (exc) {
      console.error('Claim detail failed:', exc)
    } finally {
      setClaimLoading(false)
    }
  }, [onClaimOpen])

  const submit = useCallback(async () => {
    if (!question.trim()) return
    setLoading(true)
    setError(null)
    setResponse(null)
    try {
      const res = await fetch('/api/runtime_v2/answer', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, audit_mode: auditMode, top_k_claims: 8 }),
      })
      if (!res.ok) {
        const txt = await res.text()
        throw new Error(`HTTP ${res.status}: ${txt}`)
      }
      const data: PipelineResponse = await res.json()
      setResponse(data)
    } catch (exc: unknown) {
      setError(exc instanceof Error ? exc.message : 'Erreur inconnue')
    } finally {
      setLoading(false)
    }
  }, [question, auditMode])

  const decisionInfo = response ? DECISION_LABELS[response.decision] || { label: response.decision, color: 'gray' } : null
  const anchorLabel = response ? ANCHOR_LABELS[response.anchor.anchor_type] : ''

  return (
    <Box p={6} maxW="1100px" mx="auto" color="var(--fg)" bg="var(--bg-page)">
      <VStack align="stretch" spacing={5}>
        <Heading size="lg" color="var(--accent-base)">
          OSMOSIS — Runtime V2 (anchor-driven)
        </Heading>
        <Text fontSize="sm" color="var(--fg-muted)">
          Pipeline simplifié 5 étapes : Anchor Extractor → Anchor Filter → Current Resolver → Retrieval → Conflict Detector.
          Le toggle <b>Audit</b> remonte les contradictions internes (mode compliance officer).
        </Text>

        <Box borderWidth="1px" borderColor="var(--border)" rounded="md" p={4} bg="var(--bg-surface)">
          <VStack align="stretch" spacing={3}>
            <Textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Pose ta question…"
              rows={2}
              bg="var(--bg-input)"
              borderColor="var(--border)"
              color="var(--fg)"
            />
            <HStack justify="space-between">
              <HStack>
                <Switch isChecked={auditMode} onChange={(e) => setAuditMode(e.target.checked)} colorScheme="yellow" />
                <Text fontSize="sm">Mode Audit</Text>
                <Tooltip label="Retourne les contradictions intra-anchor (vraies + résolues par lifecycle)">
                  <Badge variant="outline">?</Badge>
                </Tooltip>
              </HStack>
              <Button onClick={submit} isLoading={loading} colorScheme="green">
                Envoyer
              </Button>
            </HStack>
          </VStack>
        </Box>

        {error && (
          <Box p={3} bg="red.700" color="white" rounded="md">
            <Text>Erreur : {error}</Text>
          </Box>
        )}

        {loading && (
          <HStack>
            <Spinner size="sm" />
            <Text>Pipeline en cours…</Text>
          </HStack>
        )}

        {response && decisionInfo && (
          <VStack align="stretch" spacing={4}>
            {/* Décision globale */}
            <Box borderWidth="1px" borderColor="var(--border)" rounded="md" p={4} bg="var(--bg-surface)">
              <HStack justify="space-between" mb={2}>
                <HStack>
                  <Badge colorScheme={decisionInfo.color} fontSize="md" px={2} py={1}>
                    {decisionInfo.label}
                  </Badge>
                  <Badge variant="outline">{anchorLabel}</Badge>
                </HStack>
                <HStack>
                  <Text fontSize="sm" color="var(--fg-muted)">Trust score</Text>
                  <Badge colorScheme={response.trust_score >= 0.8 ? 'green' : response.trust_score >= 0.5 ? 'yellow' : 'red'}>
                    {(response.trust_score * 100).toFixed(0)}%
                  </Badge>
                </HStack>
              </HStack>

              {/* Anchor details */}
              <Box mt={3} fontSize="sm">
                <Text color="var(--fg-muted)">Anchor extrait (confidence {(response.anchor.confidence * 100).toFixed(0)}%) :</Text>
                <HStack mt={1} flexWrap="wrap" spacing={2}>
                  {response.anchor.scope.version && (
                    <Tag size="sm" colorScheme="blue">version: {response.anchor.scope.version}</Tag>
                  )}
                  {response.anchor.scope.date && (
                    <Tag size="sm" colorScheme="blue">date: {response.anchor.scope.date}</Tag>
                  )}
                  {response.anchor.scope.range_start && (
                    <Tag size="sm" colorScheme="purple">depuis: {response.anchor.scope.range_start}</Tag>
                  )}
                  {response.anchor.scope.range_end && (
                    <Tag size="sm" colorScheme="purple">jusqu'à: {response.anchor.scope.range_end}</Tag>
                  )}
                  {response.anchor.scope.extraction_evidence && (
                    <Tooltip label={response.anchor.scope.extraction_evidence}>
                      <Tag size="sm" variant="outline">evidence: «{response.anchor.scope.extraction_evidence.slice(0, 30)}…»</Tag>
                    </Tooltip>
                  )}
                </HStack>
              </Box>
            </Box>

            {/* Escalade */}
            {response.escalation_message && (
              <Box borderWidth="1px" borderColor="orange.400" rounded="md" p={4} bg="orange.900">
                <Text fontWeight="bold" mb={2}>Précision requise</Text>
                <Text>{response.escalation_message}</Text>
                {response.alternatives.length > 0 && (
                  <VStack align="stretch" mt={3} spacing={1}>
                    <Text fontSize="sm" color="var(--fg-muted)">Alternatives :</Text>
                    {response.alternatives.map((alt, i) => (
                      <HStack key={i} fontSize="sm">
                        <Text fontFamily="mono">{alt.doc_id}</Text>
                        <Badge size="sm">{(alt.confidence * 100).toFixed(0)}%</Badge>
                      </HStack>
                    ))}
                  </VStack>
                )}
              </Box>
            )}

            {/* Synthèse LLM (P2.1) */}
            {response.synthesized_answer && (
              <Box borderWidth="1px" borderColor="var(--accent-base)" rounded="md" p={4} bg="var(--bg-surface)">
                <Heading size="sm" mb={2} color="var(--accent-base)">Réponse</Heading>
                <Text fontSize="md" whiteSpace="pre-wrap">{response.synthesized_answer}</Text>
              </Box>
            )}

            {/* Sources autoritaires */}
            {response.authoritative_doc_ids.length > 0 && (
              <Box borderWidth="1px" borderColor="var(--border)" rounded="md" p={4} bg="var(--bg-surface)">
                <Text fontSize="sm" color="var(--fg-muted)" mb={2}>
                  Sources autoritaires ({response.authoritative_doc_ids.length})
                </Text>
                <HStack flexWrap="wrap" spacing={2}>
                  {response.authoritative_doc_ids.slice(0, 10).map((d) => (
                    <Tag
                      key={d}
                      size="sm"
                      colorScheme="cyan"
                      cursor="pointer"
                      onClick={() => openDocDetail(d)}
                      _hover={{ opacity: 0.8 }}
                    >
                      {d}
                    </Tag>
                  ))}
                </HStack>
              </Box>
            )}

            {/* Claims (POINT / CURRENT) */}
            {response.claims.length > 0 && (
              <Box borderWidth="1px" borderColor="var(--border)" rounded="md" p={4} bg="var(--bg-surface)">
                <Heading size="sm" mb={3}>Claims pertinents ({response.claims.length})</Heading>
                <VStack align="stretch" spacing={3}>
                  {response.claims.map((c) => (
                    <Box
                      key={c.claim_id}
                      p={3}
                      borderLeft="3px solid var(--accent-base)"
                      bg="var(--bg-page)"
                      cursor="pointer"
                      onClick={() => openClaimDetail(c.claim_id)}
                      _hover={{ borderLeftWidth: '5px' }}
                    >
                      <HStack justify="space-between" mb={1}>
                        <HStack>
                          <Text fontSize="xs" fontFamily="mono" color="var(--fg-muted)">
                            {c.doc_id} · {c.publication_date || '—'}
                          </Text>
                          <Tooltip label="Click pour drill-down claim">
                            <Badge size="xs" variant="outline">→</Badge>
                          </Tooltip>
                        </HStack>
                        <Badge size="sm">{c.score.toFixed(2)}</Badge>
                      </HStack>
                      <Text fontSize="sm">{c.text}</Text>
                    </Box>
                  ))}
                </VStack>
              </Box>
            )}

            {/* Evolution timeline (RANGE) */}
            {response.evolution_points.length > 0 && (
              <Box borderWidth="1px" borderColor="var(--border)" rounded="md" p={4} bg="var(--bg-surface)">
                <Heading size="sm" mb={3}>Timeline ({response.evolution_points.length} points)</Heading>
                <VStack align="stretch" spacing={4}>
                  {response.evolution_points.map((ep, i) => (
                    <Box key={ep.doc_id} p={3} bg="var(--bg-page)" borderLeft="3px solid var(--accent-base)">
                      <HStack mb={2}>
                        <Badge colorScheme="purple">{ep.publication_date || '—'}</Badge>
                        <Text fontSize="xs" fontFamily="mono">{ep.doc_id}</Text>
                      </HStack>
                      <VStack align="stretch" spacing={1}>
                        {ep.claims.slice(0, 3).map((c) => (
                          <Text key={c.claim_id} fontSize="sm" color="var(--fg-muted)">
                            • {c.text.slice(0, 200)}{c.text.length > 200 ? '…' : ''}
                          </Text>
                        ))}
                      </VStack>
                    </Box>
                  ))}
                </VStack>
              </Box>
            )}

            {/* Conflicts */}
            {response.conflicts.length > 0 && (
              <Box borderWidth="1px" borderColor={auditMode ? 'yellow.400' : 'red.400'} rounded="md" p={4} bg={auditMode ? 'yellow.900' : 'red.900'}>
                <Heading size="sm" mb={3}>
                  {auditMode ? 'Audit — Contradictions détectées' : 'Contradictions intra-anchor'}
                  ({response.conflicts.length})
                </Heading>
                <VStack align="stretch" spacing={2}>
                  {response.conflicts.map((c, i) => (
                    <Box key={i} p={2} bg="var(--bg-page)" rounded="sm">
                      <HStack justify="space-between" mb={1}>
                        <HStack spacing={1}>
                          <Tag size="sm" fontFamily="mono">{c.doc_a_id.slice(0, 30)}</Tag>
                          <Text>vs</Text>
                          <Tag size="sm" fontFamily="mono">{c.doc_b_id.slice(0, 30)}</Tag>
                        </HStack>
                        <HStack>
                          <Badge size="sm">{(c.confidence * 100).toFixed(0)}%</Badge>
                          {c.is_resolved_by_lifecycle && (
                            <Badge colorScheme="blue" size="sm">
                              résolu par {c.lifecycle_resolution_type}
                            </Badge>
                          )}
                        </HStack>
                      </HStack>
                      {c.reasoning && (
                        <Text fontSize="xs" color="var(--fg-muted)">{c.reasoning}</Text>
                      )}
                    </Box>
                  ))}
                </VStack>
              </Box>
            )}

            {/* Diagnostic (debug) */}
            <Box borderWidth="1px" borderColor="var(--border)" rounded="md" p={3} bg="var(--bg-page)">
              <Text fontSize="xs" color="var(--fg-muted)" fontFamily="mono">
                diagnostic: {JSON.stringify(response.diagnostic)}
              </Text>
            </Box>
          </VStack>
        )}
      </VStack>

      {/* P2.4 — Drill-down modal */}
      <Modal isOpen={isDocOpen} onClose={onDocClose} size="2xl">
        <ModalOverlay />
        <ModalContent bg="var(--bg-surface)" color="var(--fg)">
          <ModalHeader>
            {docDetail ? docDetail.doc_id : 'Détail document'}
          </ModalHeader>
          <ModalCloseButton />
          <ModalBody pb={6}>
            {docLoading && <Spinner />}
            {docDetail && (
              <VStack align="stretch" spacing={4}>
                <Box>
                  <Text fontSize="sm" color="var(--fg-muted)">Subject</Text>
                  <Text>{docDetail.primary_subject || '—'}</Text>
                </Box>
                <HStack>
                  <Box>
                    <Text fontSize="sm" color="var(--fg-muted)">Publication</Text>
                    <Text fontFamily="mono">{docDetail.publication_date || '—'}</Text>
                  </Box>
                  <Box ml={6}>
                    <Text fontSize="sm" color="var(--fg-muted)">Lifecycle</Text>
                    <Badge colorScheme={docDetail.lifecycle_status === 'ACTIVE' ? 'green' : 'gray'}>
                      {docDetail.lifecycle_status || 'UNKNOWN'}
                    </Badge>
                  </Box>
                  <Box ml={6}>
                    <Text fontSize="sm" color="var(--fg-muted)">Claims</Text>
                    <Text>{docDetail.n_claims}</Text>
                  </Box>
                  <Box ml={6}>
                    <Text fontSize="sm" color="var(--fg-muted)">Conflicts</Text>
                    <Text>{docDetail.n_conflicts}</Text>
                  </Box>
                </HStack>

                {docDetail.lifecycle_outgoing.length > 0 && (
                  <Box>
                    <Heading size="xs" mb={2}>Ce doc <Tag size="sm" colorScheme="purple">{`→`}</Tag> (sortantes)</Heading>
                    <VStack align="stretch" spacing={1}>
                      {docDetail.lifecycle_outgoing.map((r, i) => (
                        <HStack key={i} fontSize="sm">
                          <Badge colorScheme={r.type === 'SUPERSEDES' ? 'red' : 'blue'}>{r.type}</Badge>
                          <Tag
                            size="sm"
                            cursor="pointer"
                            onClick={() => openDocDetail(r.target)}
                            _hover={{ opacity: 0.8 }}
                          >
                            {r.target}
                          </Tag>
                          <Badge>{(r.confidence * 100).toFixed(0)}%</Badge>
                          {r.evidence_quote && (
                            <Tooltip label={r.evidence_quote}>
                              <Text fontSize="xs" color="var(--fg-muted)" isTruncated maxW="300px">
                                «{r.evidence_quote.slice(0, 60)}…»
                              </Text>
                            </Tooltip>
                          )}
                        </HStack>
                      ))}
                    </VStack>
                  </Box>
                )}

                {docDetail.lifecycle_incoming.length > 0 && (
                  <Box>
                    <Heading size="xs" mb={2}>Ce doc <Tag size="sm" colorScheme="purple">{`←`}</Tag> (entrantes)</Heading>
                    <VStack align="stretch" spacing={1}>
                      {docDetail.lifecycle_incoming.map((r, i) => (
                        <HStack key={i} fontSize="sm">
                          <Tag
                            size="sm"
                            cursor="pointer"
                            onClick={() => openDocDetail(r.source)}
                            _hover={{ opacity: 0.8 }}
                          >
                            {r.source}
                          </Tag>
                          <Badge colorScheme={r.type === 'SUPERSEDES' ? 'red' : 'blue'}>{r.type}</Badge>
                          <Badge>{(r.confidence * 100).toFixed(0)}%</Badge>
                        </HStack>
                      ))}
                    </VStack>
                  </Box>
                )}

                {docDetail.lifecycle_outgoing.length === 0 && docDetail.lifecycle_incoming.length === 0 && (
                  <Text fontSize="sm" color="var(--fg-muted)">
                    Aucune relation lifecycle déclarée.
                  </Text>
                )}

                {/* P5 polish — Mini graph view lifecycle */}
                {(docDetail.lifecycle_outgoing.length > 0 || docDetail.lifecycle_incoming.length > 0) && (
                  <Box mt={2}>
                    <Heading size="xs" mb={2}>Graphe lifecycle (voisinage)</Heading>
                    <LifecycleGraphMini focusDocId={docDetail.doc_id} onNodeClick={openDocDetail} />
                  </Box>
                )}
              </VStack>
            )}
          </ModalBody>
        </ModalContent>
      </Modal>

      {/* P5 polish — Drill-down modal claim */}
      <Modal isOpen={isClaimOpen} onClose={onClaimClose} size="2xl" scrollBehavior="inside">
        <ModalOverlay />
        <ModalContent bg="var(--bg-surface)" color="var(--fg)">
          <ModalHeader>
            <Text fontSize="md" fontFamily="mono">{claimDetail?.claim_id || 'Claim detail'}</Text>
            {claimDetail && (
              <Text fontSize="xs" color="var(--fg-muted)">
                {claimDetail.doc_id} · {claimDetail.publication_date || '—'}
              </Text>
            )}
          </ModalHeader>
          <ModalCloseButton />
          <ModalBody pb={6}>
            {claimLoading && <Spinner />}
            {claimDetail && (
              <VStack align="stretch" spacing={4}>
                <Box p={3} bg="var(--bg-page)" rounded="md">
                  <Text fontSize="sm" fontWeight="bold">Texte du claim</Text>
                  <Text fontSize="sm" mt={1}>{claimDetail.text}</Text>
                </Box>

                {claimDetail.passage_text && claimDetail.passage_text !== claimDetail.text && (
                  <Box p={3} bg="var(--bg-page)" rounded="md">
                    <Text fontSize="xs" color="var(--fg-muted)">Passage source</Text>
                    <Text fontSize="xs" mt={1}>{claimDetail.passage_text.slice(0, 500)}</Text>
                  </Box>
                )}

                {claimDetail.facets.length > 0 && (
                  <Box>
                    <Heading size="xs" mb={2}>Facets</Heading>
                    <HStack flexWrap="wrap" spacing={1}>
                      {claimDetail.facets.map((f, i) => (
                        <Tag key={i} size="sm" colorScheme={f.level === 'STRONG' ? 'green' : 'gray'}>
                          {f.name} ({(f.confidence * 100).toFixed(0)}%)
                        </Tag>
                      ))}
                    </HStack>
                  </Box>
                )}

                {claimDetail.logical_outgoing.length > 0 && (
                  <Box>
                    <Heading size="xs" mb={2}>
                      Relations sortantes ({claimDetail.logical_outgoing.length})
                    </Heading>
                    <VStack align="stretch" spacing={2}>
                      {claimDetail.logical_outgoing.map((r, i) => (
                        <Box
                          key={i}
                          p={2}
                          bg="var(--bg-page)"
                          rounded="sm"
                          cursor="pointer"
                          onClick={() => openClaimDetail(r.target_claim_id)}
                          _hover={{ opacity: 0.8 }}
                        >
                          <HStack mb={1}>
                            <Badge colorScheme={r.relation_type === 'CONFLICT' ? 'red' : r.relation_type === 'EQUIVALENT' ? 'green' : 'blue'}>
                              {r.relation_type}
                            </Badge>
                            <Text fontSize="xs" fontFamily="mono" color="var(--fg-muted)">
                              {r.target_doc_id}
                            </Text>
                            <Badge size="sm">{(r.confidence * 100).toFixed(0)}%</Badge>
                          </HStack>
                          <Text fontSize="xs">{r.target_text_preview}…</Text>
                        </Box>
                      ))}
                    </VStack>
                  </Box>
                )}

                {claimDetail.logical_incoming.length > 0 && (
                  <Box>
                    <Heading size="xs" mb={2}>
                      Relations entrantes ({claimDetail.logical_incoming.length})
                    </Heading>
                    <VStack align="stretch" spacing={2}>
                      {claimDetail.logical_incoming.map((r, i) => (
                        <Box
                          key={i}
                          p={2}
                          bg="var(--bg-page)"
                          rounded="sm"
                          cursor="pointer"
                          onClick={() => openClaimDetail(r.source_claim_id)}
                          _hover={{ opacity: 0.8 }}
                        >
                          <HStack mb={1}>
                            <Text fontSize="xs" fontFamily="mono" color="var(--fg-muted)">
                              {r.source_doc_id}
                            </Text>
                            <Badge colorScheme={r.relation_type === 'CONFLICT' ? 'red' : r.relation_type === 'EQUIVALENT' ? 'green' : 'blue'}>
                              {r.relation_type}
                            </Badge>
                            <Badge size="sm">{(r.confidence * 100).toFixed(0)}%</Badge>
                          </HStack>
                          <Text fontSize="xs">{r.source_text_preview}…</Text>
                        </Box>
                      ))}
                    </VStack>
                  </Box>
                )}

                {claimDetail.logical_outgoing.length === 0 && claimDetail.logical_incoming.length === 0 && (
                  <Text fontSize="sm" color="var(--fg-muted)">
                    Aucune relation logique avec d'autres claims.
                  </Text>
                )}
              </VStack>
            )}
          </ModalBody>
        </ModalContent>
      </Modal>
    </Box>
  )
}
