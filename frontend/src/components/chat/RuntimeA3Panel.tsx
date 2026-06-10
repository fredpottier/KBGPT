'use client'

/**
 * RuntimeA3Panel — expose la VALEUR différenciante de runtime_a3 (answering KG-first)
 * que /search ne montrait pas : citations claim-level (verbatim + doc + page),
 * abstention disciplinée / signal de tension, et trace de raisonnement repliable.
 *
 * Branché dans le chat de prod (31/05/2026) sous la réponse synthétisée.
 */

import { useState } from 'react'
import {
  VStack,
  Box,
  Text,
  HStack,
  Badge,
  Icon,
  Collapse,
} from '@chakra-ui/react'
import {
  FiAlertTriangle,
  FiFileText,
  FiChevronDown,
  FiChevronRight,
  FiSearch,
  FiCheckCircle,
  FiShield,
} from 'react-icons/fi'
// [SOURCE_VIEWER] module autonome Phase C — voir components/source-viewer/README.md
import { SourceViewer, SOURCE_VIEWER_ENABLED, type SourceViewerTarget } from '@/components/source-viewer'

interface CitedClaim {
  claim_id: string
  claim_verbatim: string
  doc_title?: string | null
  section_id?: string | null
  page?: number | null
  source_doc_id?: string | null
  n?: number
  // Phase C (traçabilité enrichie) — tous optionnels, dégradation silencieuse.
  source_verbatim_quote?: string | null
  valid_from?: string | null
  valid_until?: string | null
  invalidated_at?: string | null
  lifecycle_status?: string | null
  // Profilage documentaire (en-tête de nature, 10/06) — optionnels, best-effort.
  source_role?: string | null
  source_summary?: string | null
}

// Phase C — badge bitemporel calculé depuis les dates/lifecycle du claim cité.
// Texte intemporel/factuel (cf principe UI : les données portent le verdict).
function lifecycleBadge(c: CitedClaim): { label: string; color: string } | null {
  const obsolete = !!c.invalidated_at || !!c.valid_until ||
    (c.lifecycle_status && /withdraw|cancel|supersed|obsolet|replac/i.test(c.lifecycle_status))
  if (obsolete) {
    const since = c.invalidated_at || c.valid_until
    return { label: since ? `obsolète (${since})` : 'obsolète', color: 'orange' }
  }
  if (c.valid_from) return { label: `en vigueur · depuis ${c.valid_from}`, color: 'green' }
  return null
}

interface IterationTrace {
  iteration: number
  n_sub_goals: number
  n_tool_calls: number
  n_results: number
  verdict: string
  covered_sub_goals?: number[]
  uncovered_sub_goals?: number[]
  evaluate_reasoning?: string
}

export interface RuntimeA3Meta {
  mode?: string
  cited_claims?: CitedClaim[]
  abstention?: string | null
  uncovered_warning?: string | null
  conflict_warning?: string | null
  authority_divergence_warning?: string | null
  warnings?: string[]
  citation_coverage_rate?: number | null
  total_duration_s?: number
  n_iterations?: number
  terminated_reason?: string
  iterations_trace?: IterationTrace[] | null
  runtime_version?: string
}

export default function RuntimeA3Panel({
  runtimeA3,
}: {
  runtimeA3?: RuntimeA3Meta | null
}) {
  const [showCitations, setShowCitations] = useState(false)
  const [showTrace, setShowTrace] = useState(false)
  // [SOURCE_VIEWER] cible courante du viewer PDF in-app (null = fermé)
  const [viewerTarget, setViewerTarget] = useState<SourceViewerTarget | null>(null)

  if (!runtimeA3) return null

  const citations = runtimeA3.cited_claims || []
  const trace = runtimeA3.iterations_trace || []
  const isAbstained =
    runtimeA3.mode === 'abstained' || !!runtimeA3.abstention
  const coverage = runtimeA3.citation_coverage_rate

  // Groupement des citations PAR DOCUMENT (chantier en-tête de nature, 10/06).
  // En-tête de groupe = [tag rôle] + titre + résumé → pré-filtrage des sources
  // sans ouvrir les fichiers. Ordre de 1ère apparition préservé ; chaque claim
  // garde sa position globale `_pos` pour la numérotation [n] et son click-to-source.
  type CitedClaimPos = CitedClaim & { _pos: number }
  const citationGroups: {
    docId: string | null
    title?: string | null
    role?: string | null
    summary?: string | null
    items: CitedClaimPos[]
  }[] = []
  const _groupIndexByKey = new Map<string, number>()
  citations.forEach((c, idx) => {
    const key = c.source_doc_id || `__nodoc_${idx}`
    if (!_groupIndexByKey.has(key)) {
      _groupIndexByKey.set(key, citationGroups.length)
      citationGroups.push({
        docId: c.source_doc_id ?? null,
        title: c.doc_title,
        role: c.source_role,
        summary: c.source_summary,
        items: [],
      })
    }
    citationGroups[_groupIndexByKey.get(key)!].items.push({ ...c, _pos: idx })
  })

  const openClaimSource = async (c: CitedClaim) => {
    // [SOURCE_VIEWER] branche in-app si actif, sinon onglet natif.
    if (c.source_doc_id && SOURCE_VIEWER_ENABLED) {
      setViewerTarget({
        docId: c.source_doc_id,
        page: c.page ?? undefined,
        quote: c.source_verbatim_quote || c.claim_verbatim,
        docTitle: c.doc_title || c.source_doc_id,
      })
      return
    }
    if (c.source_doc_id) {
      const { openSourceFile } = await import('@/lib/openSourceFile')
      await openSourceFile(c.source_doc_id, c.page ?? undefined)
    }
  }

  // Narration en langage clair, CALCULÉE depuis les données du run (pas figée) :
  // raconte le mécanisme de fiabilité sans jargon interne, lisible par un
  // non-technique (cf principe "langage clair" + besoin Armand).
  const nSources = citations.length
  const nAspects = trace.length
    ? Math.max(...trace.map((t) => t.n_sub_goals || 1))
    : 1
  const hasDivergence = !!runtimeA3.authority_divergence_warning
  const hasConflict = !!runtimeA3.conflict_warning || hasDivergence
  // Bras RAG classique (toggle KG éteint) : narration KG inadaptée → bandeau dédié
  const isClassicRag = runtimeA3.runtime_version === 'classic_rag'
  const reasoningSteps: { icon: any; color: string; text: string }[] = [
    {
      icon: FiSearch,
      color: 'blue.300',
      text:
        nAspects > 1
          ? `Votre question a été décomposée en ${nAspects} aspects, vérifiés séparément.`
          : `Le point clé de votre question a été identifié.`,
    },
    {
      icon: FiFileText,
      color: 'blue.300',
      text:
        nSources > 0
          ? `${nSources} source${nSources > 1 ? 's' : ''} pertinente${
              nSources > 1 ? 's' : ''
            } retenue${nSources > 1 ? 's' : ''} dans le corpus (citées ci-dessus).`
          : `Aucune source suffisamment pertinente n'a été trouvée dans le corpus.`,
    },
    hasConflict
      ? {
          icon: FiAlertTriangle,
          color: 'orange.300',
          text: `Une tension entre sources a été repérée — elle vous est signalée plutôt que tranchée en silence.`,
        }
      : nSources > 0
      ? {
          icon: FiCheckCircle,
          color: 'green.300',
          text: `Aucune contradiction détectée entre les sources retenues.`,
        }
      : {
          icon: FiFileText,
          color: 'text.secondary',
          text: `Pas de source à confronter.`,
        },
    isAbstained
      ? {
          icon: FiShield,
          color: 'orange.300',
          text: `Faute de couverture suffisante, le système n'invente pas : il indique ce que le corpus permet — ou non — d'affirmer.`,
        }
      : {
          icon: FiCheckCircle,
          color: 'green.300',
          text: `Les sources couvrent la question : chaque affirmation est reliée à sa source, sans extrapolation.`,
        },
  ]

  // Mode RAG seul : panneau minimal (pas de claims KG, citations [Source N] inline)
  if (isClassicRag) {
    return (
      <VStack spacing={2} align="stretch" w="full" mt={2}>
        <HStack spacing={2} fontSize="xs">
          <Badge colorScheme="purple" variant="subtle" fontSize="xs">
            RAG seul — Knowledge Graph désactivé
          </Badge>
          <Badge
            colorScheme={isAbstained ? 'orange' : 'gray'}
            variant="subtle"
            fontSize="xs"
          >
            {runtimeA3.mode || 'answer'}
          </Badge>
          {typeof runtimeA3.total_duration_s === 'number' && (
            <Text color="text.secondary">
              {runtimeA3.total_duration_s.toFixed(1)}s
            </Text>
          )}
        </HStack>
        <Text fontSize="xs" color="text.secondary">
          Réponse produite par recherche vectorielle directe (top-12 passages) +
          synthèse, sans Knowledge Graph : pas de vérification claim par claim,
          pas de détection de contradictions ni de lignée documentaire.
        </Text>
      </VStack>
    )
  }

  return (
    <VStack spacing={2} align="stretch" w="full" mt={2}>
      {/* Divergence entre autorités réglementaires — matérialisée en bandeau
          dédié (retour Fred 05/06 : la divergence inline passait inaperçue).
          Posé déterministiquement côté backend, JAMAIS sur une simple
          équivalence d'unités (cf value_equivalence). */}
      {hasDivergence && (
        <Box
          p={3}
          bg="rgba(239, 68, 68, 0.12)"
          borderRadius="md"
          border="1px solid"
          borderColor="red.500"
        >
          <HStack spacing={2} align="start">
            <Icon as={FiAlertTriangle} color="red.400" boxSize={5} mt="2px" />
            <VStack align="start" spacing={1}>
              <Text fontSize="sm" fontWeight="bold" color="red.300">
                Divergence entre autorités réglementaires
              </Text>
              <Text fontSize="xs" color="text.secondary">
                {runtimeA3.authority_divergence_warning} Les deux positions sont
                exposées dans la réponse ci-dessus — le système ne tranche pas à
                votre place.
              </Text>
            </VStack>
          </HStack>
        </Box>
      )}

      {/* Abstention / tension — le différenciateur clé : dire quand on ne sait pas */}
      {(runtimeA3.uncovered_warning || runtimeA3.conflict_warning) && (
        <Box
          p={3}
          bg="rgba(251, 191, 36, 0.1)"
          borderRadius="md"
          border="1px solid"
          borderColor="orange.500"
        >
          <HStack spacing={2} align="start">
            <Icon as={FiAlertTriangle} color="orange.400" boxSize={4} mt="2px" />
            <VStack align="start" spacing={1}>
              <Text fontSize="xs" fontWeight="semibold" color="orange.300">
                {isAbstained
                  ? 'Réponse prudente — limite signalée par le système'
                  : 'Limite signalée'}
              </Text>
              {runtimeA3.uncovered_warning && (
                <Text fontSize="xs" color="text.secondary">
                  {runtimeA3.uncovered_warning}
                </Text>
              )}
              {runtimeA3.conflict_warning && (
                <Text fontSize="xs" color="text.secondary">
                  {runtimeA3.conflict_warning}
                </Text>
              )}
            </VStack>
          </HStack>
        </Box>
      )}

      {/* Barre méta + bascules */}
      <HStack spacing={4} fontSize="xs" color="text.secondary" flexWrap="wrap">
        <Badge
          colorScheme={isAbstained ? 'orange' : 'green'}
          variant="subtle"
          fontSize="xs"
        >
          {runtimeA3.mode || 'answer'}
        </Badge>

        {citations.length > 0 && (
          <HStack
            spacing={1}
            cursor="pointer"
            onClick={() => setShowCitations((v) => !v)}
            _hover={{ color: 'text.primary' }}
          >
            <Icon as={showCitations ? FiChevronDown : FiChevronRight} />
            <Icon as={FiFileText} />
            <Text>
              {citations.length} source{citations.length > 1 ? 's' : ''} citée
              {citations.length > 1 ? 's' : ''}
            </Text>
          </HStack>
        )}

        {typeof coverage === 'number' && (
          <Text>couverture {Math.round(coverage * 100)}%</Text>
        )}

        {reasoningSteps.length > 0 && (
          <HStack
            spacing={1}
            cursor="pointer"
            onClick={() => setShowTrace((v) => !v)}
            _hover={{ color: 'text.primary' }}
          >
            <Icon as={showTrace ? FiChevronDown : FiChevronRight} />
            <Icon as={FiShield} />
            <Text>Comment cette réponse a été construite</Text>
          </HStack>
        )}
      </HStack>

      {/* Citations claim-level, GROUPÉES PAR DOCUMENT (en-tête de nature).
          Chaque groupe est coiffé d'un en-tête [tag rôle] + titre + résumé qui
          permet de pré-filtrer les sources sans ouvrir les fichiers. Le rôle/résumé
          sont best-effort : s'ils ne sont pas encore peuplés (avant ré-ingestion),
          l'en-tête dégrade en simple titre, sans erreur. */}
      <Collapse in={showCitations} animateOpacity>
        <VStack
          spacing={3}
          align="stretch"
          pl={3}
          borderLeft="2px solid"
          borderColor="border.active"
        >
          {citationGroups.map((g, gi) => (
            <Box key={g.docId || `nodoc-${gi}`} fontSize="xs">
              {/* En-tête de document */}
              <HStack spacing={2} align="baseline" flexWrap="wrap">
                {g.role ? (
                  <Badge
                    colorScheme="cyan"
                    variant="subtle"
                    fontSize="9px"
                    textTransform="none"
                  >
                    {g.role}
                  </Badge>
                ) : null}
                <Text fontWeight="semibold" color="text.primary">
                  {g.title || g.docId || 'Document'}
                </Text>
              </HStack>
              {g.summary ? (
                <Text color="text.secondary" mt="2px" noOfLines={2}>
                  {g.summary}
                </Text>
              ) : null}

              {/* Claims cités de ce document */}
              <VStack spacing={1} align="stretch" mt={1} pl={2}>
                {g.items.map((c) => {
                  const badge = lifecycleBadge(c)
                  return (
                    <Box key={c.claim_id || c._pos}>
                      <Text color="text.primary">
                        <Text as="span" color="text.secondary" fontWeight="semibold">
                          [{c.n ?? c._pos + 1}]{' '}
                        </Text>
                        “{c.claim_verbatim}”
                        {/* Phase C — badge bitemporel (en vigueur / obsolète) */}
                        {badge ? (
                          <Badge ml={2} colorScheme={badge.color} fontSize="9px" verticalAlign="middle" textTransform="none">
                            {badge.color === 'green' ? '✓ ' : '⚠ '}{badge.label}
                          </Badge>
                        ) : null}
                      </Text>
                      {/* Click-to-source. [SOURCE_VIEWER] : in-app si actif, sinon onglet. */}
                      {c.source_doc_id ? (
                        <Text
                          as="button"
                          color="brand.300"
                          mt="2px"
                          display="block"
                          textAlign="left"
                          textDecoration="underline"
                          _hover={{ color: 'brand.200' }}
                          onClick={() => openClaimSource(c)}
                        >
                          {c.page != null ? `p.${c.page}` : 'ouvrir la source'}
                          {SOURCE_VIEWER_ENABLED ? ' ⊕' : ' ↗'}
                        </Text>
                      ) : (
                        <Text color="text.secondary" mt="2px">
                          {c.page != null ? `p.${c.page}` : 'source non localisée'}
                        </Text>
                      )}
                    </Box>
                  )
                })}
              </VStack>
            </Box>
          ))}
        </VStack>
      </Collapse>

      {/* Comment cette réponse a été construite — langage clair, CALCULÉ depuis les
          données du run (pas de jargon interne ; lisible par un non-technique). */}
      <Collapse in={showTrace} animateOpacity>
        <VStack
          spacing={2}
          align="stretch"
          pl={3}
          borderLeft="2px solid"
          borderColor="border.active"
          fontSize="xs"
        >
          {reasoningSteps.map((s, i) => (
            <HStack key={i} spacing={2} align="start">
              <Icon as={s.icon} color={s.color} boxSize={3.5} mt="2px" />
              <Text color="text.secondary">{s.text}</Text>
            </HStack>
          ))}
        </VStack>
      </Collapse>

      {/* [SOURCE_VIEWER] viewer PDF in-app (Modal en portal) — module autonome */}
      <SourceViewer target={viewerTarget} onClose={() => setViewerTarget(null)} />
    </VStack>
  )
}
