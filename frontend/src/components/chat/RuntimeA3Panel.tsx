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

interface CitedClaim {
  claim_id: string
  claim_verbatim: string
  doc_title?: string | null
  section_id?: string | null
  page?: number | null
  n?: number
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

  if (!runtimeA3) return null

  const citations = runtimeA3.cited_claims || []
  const trace = runtimeA3.iterations_trace || []
  const isAbstained =
    runtimeA3.mode === 'abstained' || !!runtimeA3.abstention
  const coverage = runtimeA3.citation_coverage_rate

  // Narration en langage clair, CALCULÉE depuis les données du run (pas figée) :
  // raconte le mécanisme de fiabilité sans jargon interne, lisible par un
  // non-technique (cf principe "langage clair" + besoin Armand).
  const nSources = citations.length
  const nAspects = trace.length
    ? Math.max(...trace.map((t) => t.n_sub_goals || 1))
    : 1
  const hasDivergence = !!runtimeA3.authority_divergence_warning
  const hasConflict = !!runtimeA3.conflict_warning || hasDivergence
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

      {/* Citations claim-level */}
      <Collapse in={showCitations} animateOpacity>
        <VStack
          spacing={2}
          align="stretch"
          pl={3}
          borderLeft="2px solid"
          borderColor="border.active"
        >
          {citations.map((c, i) => (
            <Box key={c.claim_id || i} fontSize="xs">
              <Text color="text.primary">
                <Text as="span" color="text.secondary" fontWeight="semibold">
                  [{c.n ?? i + 1}]{' '}
                </Text>
                “{c.claim_verbatim}”
              </Text>
              <Text color="text.secondary" mt="2px" pl={4}>
                {c.doc_title || 'Document'}
                {c.page != null ? ` · p.${c.page}` : ''}
              </Text>
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
    </VStack>
  )
}
