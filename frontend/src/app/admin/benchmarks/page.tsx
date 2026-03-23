'use client'

import { useEffect, useRef, useState } from 'react'
import {
  Box,
  HStack,
  VStack,
  Text,
  Badge,
  Spinner,
  SimpleGrid,
  Tooltip,
  Divider,
  Table,
  Thead,
  Tbody,
  Tr,
  Th,
  Td,
  Progress,
  Select,
} from '@chakra-ui/react'
import { FiBarChart2, FiInfo, FiTrendingUp, FiTrendingDown, FiMinus } from 'react-icons/fi'
import * as d3 from 'd3'

// ── Types ──────────────────────────────────────────────────────────────

interface TaskResult {
  task: string
  source: string
  system: string
  scores: Record<string, number>
  metadata: Record<string, unknown>
  judgments_count: number
}

interface BenchmarkRun {
  timestamp: string
  tasks: TaskResult[]
}

// ── Metric explanations ────────────────────────────────────────────────

interface MetricInfo {
  label: string
  description: string
  higherIsBetter: boolean
  frameworks: string[]  // Referentiels associes
}

const METRIC_EXPLANATIONS: Record<string, MetricInfo> = {
  // T1 — Provenance & Faithfulness
  factual_correctness_avg: { label: 'Exactitude factuelle', description: "La reponse contient-elle le fait attendu, meme reformule ? Note sur 100.", higherIsBetter: true, frameworks: ['RAGAS Faithfulness', 'AI Act Art.15 §3'] },
  citation_present_rate: { label: 'Citations presentes', description: "% de reponses citant au moins une source [Source N].", higherIsBetter: true, frameworks: ['ALCE Citation', 'AI Act Art.13 §1'] },
  correct_source_rate: { label: 'Source correcte', description: "% de reponses citant le BON document source. Provenance verifiable.", higherIsBetter: true, frameworks: ['ALCE Recall', 'NIST AI RMF GV-1.2'] },
  answer_relevant_rate: { label: 'Pertinence', description: "% de reponses pertinentes par rapport a la question posee.", higherIsBetter: true, frameworks: ['RAGAS Relevancy'] },
  answers_correctly_rate: { label: 'Reponse correcte', description: "% de reponses factuellement correctes ET pertinentes. Metrique combinee.", higherIsBetter: true, frameworks: ['RAGAS Answer Correctness'] },
  false_idk_rate: { label: 'Capacite de reponse', description: "% de cas ou le systeme repond quand l'information existe dans le corpus. 100% = ne refuse jamais a tort.", higherIsBetter: false, frameworks: ['NIST AI RMF MP-4.1', 'AI Act Art.15 §1'] },
  // T2 — Contradiction Detection
  both_sides_surfaced_rate: { label: 'Deux positions exposees', description: "% de cas ou les deux cotes d'une divergence sont mentionnes.", higherIsBetter: true, frameworks: ['AI Act Art.15 §4', 'NIST AI RMF GV-3.2'] },
  silent_arbitration_rate: { label: 'Neutralite (pas d\'arbitrage)', description: "% de cas ou le systeme presente les positions sans choisir un cote. 100% = jamais d'arbitrage silencieux.", higherIsBetter: false, frameworks: ['AI Act Art.14 §4', 'NIST AI RMF MG-2.4'] },
  tension_mentioned_rate: { label: 'Tension mentionnee', description: "% de cas ou la divergence/contradiction est explicitement signalee.", higherIsBetter: true, frameworks: ['AI Act Art.13 §1', 'NIST AI RMF GV-1.3'] },
  correct_tension_type_rate: { label: 'Type de tension correct', description: "% de cas ou le type (contradiction, evolution, nuance) est correctement identifie.", higherIsBetter: true, frameworks: ['Custom OSMOSIS'] },
  both_sourced_rate: { label: 'Deux positions sourcees', description: "% de cas ou les deux positions sont accompagnees de leurs sources.", higherIsBetter: true, frameworks: ['ALCE Citation F1', 'AI Act Art.13 §1'] },
  // T4 — Audit & Completeness
  topic_coverage_rate: { label: 'Couverture du sujet', description: "% de reponses couvrant le sujet principal demande.", higherIsBetter: true, frameworks: ['RAGAS Context Recall'] },
  sources_mentioned_rate: { label: 'Sources mentionnees', description: "% de reponses mentionnant les documents sources.", higherIsBetter: true, frameworks: ['AI Act Art.12 §1', 'NIST AI RMF GV-1.2'] },
  contradictions_flagged_rate: { label: 'Contradictions signalees', description: "% de reponses signalant les contradictions quand elles existent.", higherIsBetter: true, frameworks: ['AI Act Art.15 §4'] },
  comprehensiveness_rate: { label: 'Exhaustivite', description: "% de reponses jugees completes et suffisantes.", higherIsBetter: true, frameworks: ['RAGAS Answer Completeness'] },
  traceability_rate: { label: 'Tracabilite', description: "% de reponses ou chaque affirmation est tracable a un document.", higherIsBetter: true, frameworks: ['AI Act Art.12 §1-2', 'NIST AI RMF GV-4.1'] },
  completeness_avg: { label: 'Score completude', description: "Score global de completude de la reponse. Note sur 100.", higherIsBetter: true, frameworks: ['RAGAS Answer Completeness'] },
}

// Referentiels de conformite et leur signification
const FRAMEWORK_INFO: Record<string, { name: string; color: string; description: string }> = {
  'AI Act Art.12': { name: 'AI Act Art.12', color: '#818cf8', description: 'Enregistrement et journalisation — tracabilite des decisions' },
  'AI Act Art.13': { name: 'AI Act Art.13', color: '#818cf8', description: 'Transparence et information — le systeme doit etre comprehensible' },
  'AI Act Art.14': { name: 'AI Act Art.14', color: '#818cf8', description: 'Controle humain — eviter les biais et arbitrages non signales' },
  'AI Act Art.15': { name: 'AI Act Art.15', color: '#818cf8', description: 'Exactitude, robustesse et cybersecurite' },
  'NIST AI RMF': { name: 'NIST AI RMF', color: '#34d399', description: 'NIST AI Risk Management Framework — gouvernance et gestion des risques IA' },
  'RAGAS': { name: 'RAGAS', color: '#fb923c', description: 'Framework academique devaluation RAG (Retrieval-Augmented Generation)' },
  'ALCE': { name: 'ALCE', color: '#f472b6', description: 'Automatic LLM Citation Evaluation — benchmark de citation academique' },
  'Custom OSMOSIS': { name: 'OSMOSIS', color: '#5B7FFF', description: 'Metrique specifique OSMOSIS — detection et typage des tensions documentaires' },
}

const TASK_LABELS: Record<string, string> = {
  T1: 'T1 — Provenance & Citations',
  T2: 'T2 — Detection des Contradictions',
  T4: 'T4 — Audit & Completude',
}

const SOURCE_LABELS: Record<string, string> = {
  kg: 'Questions KG-derived',
  human: 'Questions humaines (doc-only)',
}

// ── Scoring weights per task (note sur 100) ────────────────────────────

const SCORING_WEIGHTS: Record<string, Record<string, number>> = {
  T1: {
    factual_correctness_avg: 30,     // Le plus important : est-ce que la reponse est juste ?
    answers_correctly_rate: 25,       // Correct ET pertinent
    false_idk_rate: 20,               // Penalise les refus injustifies (inverse)
    citation_present_rate: 10,        // Cite ses sources
    correct_source_rate: 10,          // Cite le BON document
    answer_relevant_rate: 5,          // Pertinence de base
  },
  T2: {
    both_sides_surfaced_rate: 30,     // Expose les deux positions
    both_sourced_rate: 20,            // Les deux positions sont sourcees
    tension_mentioned_rate: 20,       // Mentionne la tension explicitement
    correct_tension_type_rate: 15,    // Type de tension correct
    silent_arbitration_rate: 15,      // Evite l'arbitrage silencieux (inverse)
  },
  T4: {
    topic_coverage_rate: 20,          // Couvre le sujet
    completeness_avg: 25,             // Score de completude
    traceability_rate: 20,            // Tracabilite des affirmations
    sources_mentioned_rate: 15,       // Mentionne les sources
    comprehensiveness_rate: 10,       // Exhaustivite
    contradictions_flagged_rate: 10,  // Signale les contradictions
  },
}

function computeScore100(scores: Record<string, number>, task: string): number {
  const weights = SCORING_WEIGHTS[task]
  if (!weights) return 0

  let totalScore = 0
  let totalWeight = 0

  for (const [metric, weight] of Object.entries(weights)) {
    const value = scores[metric]
    if (typeof value !== 'number') continue

    const info = METRIC_EXPLANATIONS[metric]
    // For inverted metrics (lower is better), flip the value
    const normalizedValue = info && !info.higherIsBetter ? (1 - value) : value
    totalScore += normalizedValue * weight
    totalWeight += weight
  }

  return totalWeight > 0 ? Math.round(totalScore / totalWeight * 100) : 0
}

function getScoreColor(score: number): string {
  if (score >= 70) return '#22c55e'
  if (score >= 50) return '#84cc16'
  if (score >= 30) return '#eab308'
  if (score >= 15) return '#f97316'
  return '#ef4444'
}

function getScoreLabel(score: number): string {
  if (score >= 70) return 'Excellent'
  if (score >= 50) return 'Bon'
  if (score >= 30) return 'Moyen'
  if (score >= 15) return 'Faible'
  return 'Insuffisant'
}

// ── Components ─────────────────────────────────────────────────────────

function FrameworkBadge({ framework }: { framework: string }) {
  // Trouver le referentiel parent
  const key = Object.keys(FRAMEWORK_INFO).find(k => framework.startsWith(k))
  const info = key ? FRAMEWORK_INFO[key] : null
  const color = info?.color || '#888'

  return (
    <Tooltip label={info?.description || framework} placement="top" hasArrow>
      <Badge
        fontSize="8px"
        bg={`${color}22`}
        color={color}
        border="1px solid"
        borderColor={`${color}44`}
        rounded="sm"
        px={1}
        cursor="help"
        fontWeight="normal"
      >
        {framework}
      </Badge>
    </Tooltip>
  )
}

function MetricCard({ label, value, description, higherIsBetter, frameworks = [] }: {
  label: string; value: number; description: string; higherIsBetter: boolean; frameworks?: string[]
}) {
  const pct = Math.round(value * 100)
  const isGood = higherIsBetter ? value >= 0.6 : value <= 0.3
  const isBad = higherIsBetter ? value < 0.3 : value > 0.6
  const color = isGood ? '#22c55e' : isBad ? '#ef4444' : '#eab308'

  return (
    <Tooltip label={description} placement="top" hasArrow>
      <Box
        bg="var(--bg-hover)"
        border="1px solid"
        borderColor="var(--border-subtle)"
        rounded="lg"
        p={3}
        cursor="help"
        _hover={{ borderColor: 'var(--border-subtle)', bg: 'var(--bg-hover)' }}
        transition="all 0.15s"
      >
        <HStack justify="space-between" mb={1}>
          <VStack align="start" spacing={0}>
            <Text fontSize="xs" color="var(--text-muted)" noOfLines={1}>{label}</Text>
            {frameworks.length > 0 && (
              <HStack spacing={0.5} flexWrap="wrap" mt={0.5}>
                {frameworks.map(f => <FrameworkBadge key={f} framework={f} />)}
              </HStack>
            )}
          </VStack>
          <Text fontSize="lg" fontWeight="bold" color={color}>
            {typeof value === 'number' ? `${pct}%` : '-'}
          </Text>
        </HStack>
        <Progress
          value={pct}
          size="xs"
          rounded="full"
          bg="var(--bg-hover)"
          sx={{ '& > div': { bg: color } }}
        />
      </Box>
    </Tooltip>
  )
}

function RadarChart({ data, width = 300, height = 300, highlight = null }: {
  data: { label: string; value: number; higherIsBetter: boolean; baselineValue?: number }[]
  width?: number
  height?: number
  highlight?: 'osmosis' | 'rag' | null
}) {
  const svgRef = useRef<SVGSVGElement>(null)
  const [theme, setTheme] = useState('dark')

  // Observer le changement de theme pour re-render le radar
  useEffect(() => {
    const el = document.documentElement
    setTheme(el.getAttribute('data-theme') || 'dark')
    const observer = new MutationObserver(() => {
      setTheme(el.getAttribute('data-theme') || 'dark')
    })
    observer.observe(el, { attributes: true, attributeFilter: ['data-theme'] })
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    if (!svgRef.current || data.length === 0) return

    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()

    const margin = 80
    const radius = Math.min(width, height) / 2 - margin
    const cx = width / 2
    const cy = height / 2
    const angleSlice = (Math.PI * 2) / data.length

    // Detect theme for colors
    const isDark = theme !== 'light'

    const g = svg.append('g').attr('transform', `translate(${cx},${cy})`)
    const gridColor = isDark ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.1)'
    const labelColor = isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.3)'
    const axisColor = isDark ? 'rgba(255,255,255,0.2)' : 'rgba(0,0,0,0.12)'
    const textColor = isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.6)'

    // Grid circles
    const levels = 5
    for (let i = 1; i <= levels; i++) {
      const r = (radius / levels) * i
      g.append('circle')
        .attr('r', r)
        .attr('fill', 'none')
        .attr('stroke', gridColor)
        .attr('stroke-dasharray', '2,3')

      g.append('text')
        .attr('x', 4)
        .attr('y', -r + 4)
        .attr('fill', labelColor)
        .attr('font-size', '9px')
        .text(`${(i / levels * 100).toFixed(0)}%`)
    }

    // Axes
    data.forEach((d, i) => {
      const angle = angleSlice * i - Math.PI / 2
      const x = Math.cos(angle) * radius
      const y = Math.sin(angle) * radius

      g.append('line')
        .attr('x1', 0).attr('y1', 0)
        .attr('x2', x).attr('y2', y)
        .attr('stroke', axisColor)

      // Label — nom
      const lx = Math.cos(angle) * (radius + 28)
      const ly = Math.sin(angle) * (radius + 28)
      const labelText = d.label
      g.append('text')
        .attr('x', lx)
        .attr('y', ly)
        .attr('text-anchor', Math.abs(lx) < 5 ? 'middle' : lx > 0 ? 'start' : 'end')
        .attr('dominant-baseline', 'middle')
        .attr('fill', textColor)
        .attr('font-size', '9px')
        .text(`${labelText}`)
    })

    // Highlight modifiers
    const osmDim = highlight === 'rag'
    const ragDim = highlight === 'osmosis'

    // Baseline polygon (RAG — orange, dessous)
    const hasBaseline = data.some(d => d.baselineValue !== undefined)
    if (hasBaseline) {
      const basePoints = data.map((d, i) => {
        const angle = angleSlice * i - Math.PI / 2
        const r = (d.baselineValue ?? 0) * radius
        return [Math.cos(angle) * r, Math.sin(angle) * r] as [number, number]
      })

      const ragFillOpacity = ragDim ? 0.05 : highlight === 'rag' ? 0.35 : isDark ? 0.12 : 0.15
      const ragStrokeOpacity = ragDim ? 0.3 : 1
      g.append('polygon')
        .attr('points', basePoints.map(p => p.join(',')).join(' '))
        .attr('fill', `rgba(249, 115, 22, ${ragFillOpacity})`)
        .attr('stroke', '#f97316')
        .attr('stroke-opacity', ragStrokeOpacity)
        .attr('stroke-width', highlight === 'rag' ? 2.5 : 1.5)
        .attr('stroke-dasharray', highlight === 'rag' ? 'none' : '4,3')

      basePoints.forEach((p) => {
        g.append('circle')
          .attr('cx', p[0])
          .attr('cy', p[1])
          .attr('r', highlight === 'rag' ? 4 : 3)
          .attr('fill', '#f97316')
          .attr('opacity', ragDim ? 0.3 : 1)
          .attr('stroke', highlight === 'rag' ? '#fff' : 'none')
          .attr('stroke-width', highlight === 'rag' ? 1 : 0)
      })
    }

    // OSMOSIS polygon (bleu, dessus)
    const points = data.map((d, i) => {
      const angle = angleSlice * i - Math.PI / 2
      const r = d.value * radius
      return [Math.cos(angle) * r, Math.sin(angle) * r] as [number, number]
    })

    const osmFillOpacity = osmDim ? 0.05 : highlight === 'osmosis' ? 0.35 : isDark ? 0.2 : 0.25
    const osmStrokeOpacity = osmDim ? 0.3 : 1
    g.append('polygon')
      .attr('points', points.map(p => p.join(',')).join(' '))
      .attr('fill', `rgba(91, 127, 255, ${osmFillOpacity})`)
      .attr('stroke', '#5B7FFF')
      .attr('stroke-opacity', osmStrokeOpacity)
      .attr('stroke-width', highlight === 'osmosis' ? 3 : 2)

    // Points OSMOSIS avec couleur par qualite
    points.forEach((p, i) => {
      const val = data[i].value
      const isGood = val >= 0.6
      const isBad = val < 0.3
      const color = isGood ? '#22c55e' : isBad ? '#ef4444' : '#eab308'

      g.append('circle')
        .attr('cx', p[0])
        .attr('cy', p[1])
        .attr('r', highlight === 'osmosis' ? 5 : 4)
        .attr('opacity', osmDim ? 0.3 : 1)
        .attr('fill', color)
        .attr('stroke', '#fff')
        .attr('stroke-width', 1)
    })
  }, [data, width, height, theme, highlight])

  return <svg ref={svgRef} width={width} height={height} />
}

function ComparisonBar({ label, osmosis, baseline, higherIsBetter, frameworks = [], onHover }: {
  label: string; osmosis: number; baseline: number; higherIsBetter: boolean; frameworks?: string[]
  onHover?: (system: 'osmosis' | 'rag' | null) => void
}) {
  const osmPct = Math.round(osmosis * 100)
  const basPct = Math.round(baseline * 100)
  const diff = osmosis - baseline
  const osmWins = higherIsBetter ? diff > 0.01 : diff < -0.01

  return (
    <Box mb={2}>
      <HStack justify="space-between" mb={1}>
        <VStack align="start" spacing={0}>
          <Text fontSize="xs" color="var(--text-muted)">{label}</Text>
          {frameworks.length > 0 && (
            <HStack spacing={0.5} flexWrap="wrap">
              {frameworks.slice(0, 2).map(f => <FrameworkBadge key={f} framework={f} />)}
            </HStack>
          )}
        </VStack>
        <HStack spacing={1}>
          {Math.abs(diff) > 0.01 ? (
            <Badge
              fontSize="10px"
              bg={osmWins ? 'green.900' : 'red.900'}
              color={osmWins ? 'green.300' : 'red.300'}
            >
              {osmWins ? 'OSMOSIS' : 'Baseline'} {(Math.abs(diff) * 100).toFixed(0)}pp
            </Badge>
          ) : (
            <Badge fontSize="10px" bg="gray.700" color="gray.300">TIE</Badge>
          )}
        </HStack>
      </HStack>
      <HStack spacing={2}>
        <Box flex={1} cursor="pointer"
          onMouseEnter={() => onHover?.('osmosis')}
          onMouseLeave={() => onHover?.(null)}>
          <HStack justify="space-between" mb={0.5}>
            <Text fontSize="10px" color="#5B7FFF">OSMOSIS</Text>
            <Text fontSize="10px" color="#5B7FFF" fontWeight="bold">{osmPct}%</Text>
          </HStack>
          <Progress value={osmPct} size="xs" rounded="full" bg="var(--bg-hover)"
            sx={{ '& > div': { bg: '#5B7FFF' } }} />
        </Box>
        <Box flex={1} cursor="pointer"
          onMouseEnter={() => onHover?.('rag')}
          onMouseLeave={() => onHover?.(null)}>
          <HStack justify="space-between" mb={0.5}>
            <Text fontSize="10px" color="#f97316">RAG</Text>
            <Text fontSize="10px" color="#f97316" fontWeight="bold">{basPct}%</Text>
          </HStack>
          <Progress value={basPct} size="xs" rounded="full" bg="var(--bg-hover)"
            sx={{ '& > div': { bg: '#f97316' } }} />
        </Box>
      </HStack>
    </Box>
  )
}

function TaskSection({ task, source, results }: {
  task: string; source: string; results: TaskResult[]
}) {
  const [highlightSystem, setHighlightSystem] = useState<'osmosis' | 'rag' | null>(null)
  const osmosis = results.find(r => r.system === 'osmosis')
  const baseline = results.find(r => r.system !== 'osmosis')

  if (!osmosis) return null

  const scores = Object.entries(osmosis.scores).filter(([k]) => k !== 'total_evaluated')

  // Normaliser : toutes les valeurs en "higher is better" pour affichage coherent
  const normalizeValue = (value: number, higherIsBetter: boolean) =>
    higherIsBetter ? value : (1 - value)

  const radarData = scores.map(([key, value]) => {
    const info = METRIC_EXPLANATIONS[key]
    const hib = info?.higherIsBetter ?? true
    const rawVal = typeof value === 'number' ? value : 0
    return {
      label: info?.label || key,
      value: normalizeValue(rawVal, hib),
      higherIsBetter: true, // Toujours true apres normalisation
      // Valeur RAG normalisee pour le 2eme polygone
      baselineValue: baseline
        ? normalizeValue(typeof baseline.scores[key] === 'number' ? baseline.scores[key] : 0, hib)
        : undefined,
    }
  })

  return (
    <Box
      bg="var(--bg-hover)"
      border="1px solid"
      borderColor="var(--border-subtle)"
      rounded="xl"
      p={5}
      mb={4}
    >
      <HStack mb={4} justify="space-between" flexWrap="wrap">
        <VStack align="start" spacing={0}>
          <Text fontSize="md" fontWeight="bold" color="var(--text-primary)">
            {TASK_LABELS[task] || task}
          </Text>
          <HStack spacing={2}>
            <Badge bg={source === 'kg' ? 'purple.900' : 'teal.900'}
              color={source === 'kg' ? 'purple.300' : 'teal.300'} fontSize="10px">
              {SOURCE_LABELS[source] || source}
            </Badge>
            <Text fontSize="xs" color="var(--text-muted)">
              {osmosis.judgments_count} questions evaluees
            </Text>
          </HStack>
        </VStack>
        <VerdictBadge scores={osmosis.scores} task={task} hasBaseline={!!baseline} />
      </HStack>

      <SimpleGrid columns={{ base: 1, lg: 2 }} spacing={6}>
        {/* Radar chart — valeurs brutes, couleurs par type */}
        <VStack spacing={1}>
          <RadarChart data={radarData} width={420} height={420} highlight={highlightSystem} />
          <HStack spacing={3} justify="center" flexWrap="wrap">
            <HStack spacing={1}><Box w={3} h={2} bg="#5B7FFF" rounded="sm" /><Text fontSize="9px" color="var(--text-muted)">OSMOSIS</Text></HStack>
            <HStack spacing={1}><Box w={3} h={2} bg="#f97316" rounded="sm" opacity={0.7} /><Text fontSize="9px" color="var(--text-muted)">RAG</Text></HStack>
            <Text fontSize="9px" color="var(--text-muted)" opacity={0.6}>|</Text>
            <HStack spacing={1}><Box w={2} h={2} rounded="full" bg="#22c55e" /><Text fontSize="9px" color="var(--text-muted)">Bon</Text></HStack>
            <HStack spacing={1}><Box w={2} h={2} rounded="full" bg="#eab308" /><Text fontSize="9px" color="var(--text-muted)">Moyen</Text></HStack>
            <HStack spacing={1}><Box w={2} h={2} rounded="full" bg="#ef4444" /><Text fontSize="9px" color="var(--text-muted)">Faible</Text></HStack>
          </HStack>
        </VStack>

        {/* Metrics comparatives */}
        <Box>
          {baseline ? (
            <VStack spacing={0} align="stretch">
              <Text fontSize="sm" fontWeight="bold" color="var(--text-primary)" mb={3}>
                OSMOSIS vs RAG Baseline
              </Text>
              {scores.map(([key, value]) => {
                const info = METRIC_EXPLANATIONS[key]
                const hib = info?.higherIsBetter ?? true
                const osmVal = typeof value === 'number' ? value : 0
                const ragVal = typeof baseline.scores[key] === 'number' ? baseline.scores[key] : 0
                return (
                  <ComparisonBar
                    key={key}
                    label={info?.label || key}
                    osmosis={hib ? osmVal : 1 - osmVal}
                    baseline={hib ? ragVal : 1 - ragVal}
                    higherIsBetter={true}
                    frameworks={info?.frameworks || []}
                    onHover={setHighlightSystem}
                  />
                )
              })}
            </VStack>
          ) : (
            <SimpleGrid columns={2} spacing={2}>
              {scores.map(([key, value]) => (
                <MetricCard
                  key={key}
                  label={METRIC_EXPLANATIONS[key]?.label || key}
                  value={typeof value === 'number' ? value : 0}
                  description={METRIC_EXPLANATIONS[key]?.description || ''}
                  higherIsBetter={METRIC_EXPLANATIONS[key]?.higherIsBetter ?? true}
                  frameworks={METRIC_EXPLANATIONS[key]?.frameworks || []}
                />
              ))}
            </SimpleGrid>
          )}
        </Box>
      </SimpleGrid>

      {/* Metric explanations */}
      <Box mt={4} pt={3} borderTop="1px solid" borderColor="var(--border-subtle)">
        <Text fontSize="xs" fontWeight="bold" color="var(--text-muted)" mb={2}>
          Guide des metriques
        </Text>
        <SimpleGrid columns={{ base: 1, md: 2 }} spacing={1}>
          {scores.map(([key]) => {
            const info = METRIC_EXPLANATIONS[key]
            if (!info) return null
            return (
              <VStack key={key} spacing={0.5} align="start">
                <HStack spacing={1} align="start">
                  <Box as={FiInfo} color="var(--text-muted)" mt={0.5} flexShrink={0} fontSize="10px" />
                  <Text fontSize="10px" color="var(--text-muted)" lineHeight="1.4">
                    <Text as="span" fontWeight="bold">{info.label}</Text>: {info.description}
                    {!info.higherIsBetter && ' (inverse : plus bas = mieux)'}
                  </Text>
                </HStack>
                {info.frameworks.length > 0 && (
                  <HStack spacing={0.5} ml={3} flexWrap="wrap">
                    {info.frameworks.map(f => <FrameworkBadge key={f} framework={f} />)}
                  </HStack>
                )}
              </VStack>
            )
          })}
        </SimpleGrid>
      </Box>
    </Box>
  )
}

function VerdictBadge({ scores, task, hasBaseline }: {
  scores: Record<string, number>; task: string; hasBaseline: boolean
}) {
  // Compute an overall quality verdict
  let goodCount = 0
  let totalCount = 0

  Object.entries(scores).forEach(([key, value]) => {
    if (key === 'total_evaluated' || typeof value !== 'number') return
    const info = METRIC_EXPLANATIONS[key]
    if (!info) return
    totalCount++
    if (info.higherIsBetter ? value >= 0.5 : value <= 0.3) goodCount++
  })

  const ratio = totalCount > 0 ? goodCount / totalCount : 0
  const verdict = ratio >= 0.7 ? 'Excellent' : ratio >= 0.4 ? 'Correct' : 'A ameliorer'
  const color = ratio >= 0.7 ? 'green' : ratio >= 0.4 ? 'yellow' : 'red'
  const icon = ratio >= 0.7 ? FiTrendingUp : ratio >= 0.4 ? FiMinus : FiTrendingDown

  return (
    <HStack
      bg={`${color}.900`}
      color={`${color}.300`}
      rounded="lg"
      px={3}
      py={1.5}
    >
      <Box as={icon} />
      <Text fontSize="sm" fontWeight="bold">{verdict}</Text>
      <Text fontSize="xs" opacity={0.7}>({goodCount}/{totalCount})</Text>
    </HStack>
  )
}

function ScoringGrid({ run }: { run: BenchmarkRun }) {
  // Group tasks by task+source, compute scores per system
  const tasks = ['T1', 'T2', 'T4'] as const
  const sources = ['kg', 'human'] as const

  type ScoreEntry = {
    task: string
    source: string
    osmosis: number | null
    rag: number | null
    delta: number | null
    winner: 'osmosis' | 'rag' | 'tie' | null
  }

  const grid: ScoreEntry[] = []

  for (const task of tasks) {
    for (const source of sources) {
      const osmResult = run.tasks.find(t => t.system === 'osmosis' && t.task === task && t.source === source)
      const ragResult = run.tasks.find(t => t.system !== 'osmosis' && t.task === task && t.source === source)

      const osmScore = osmResult ? computeScore100(osmResult.scores, task) : null
      const ragScore = ragResult ? computeScore100(ragResult.scores, task) : null
      const delta = osmScore !== null && ragScore !== null ? osmScore - ragScore : null
      const winner = delta !== null ? (delta > 2 ? 'osmosis' : delta < -2 ? 'rag' : 'tie') : null

      if (osmScore !== null || ragScore !== null) {
        grid.push({ task, source, osmosis: osmScore, rag: ragScore, delta, winner })
      }
    }
  }

  // Compute overall scores
  const osmScores = grid.map(g => g.osmosis).filter((v): v is number => v !== null)
  const ragScores = grid.map(g => g.rag).filter((v): v is number => v !== null)
  const osmAvg = osmScores.length > 0 ? Math.round(osmScores.reduce((a, b) => a + b, 0) / osmScores.length) : null
  const ragAvg = ragScores.length > 0 ? Math.round(ragScores.reduce((a, b) => a + b, 0) / ragScores.length) : null

  const osmWins = grid.filter(g => g.winner === 'osmosis').length
  const ragWins = grid.filter(g => g.winner === 'rag').length
  const ties = grid.filter(g => g.winner === 'tie').length

  return (
    <Box
      bg="var(--bg-hover)"
      border="1px solid"
      borderColor="var(--border-subtle)"
      rounded="xl"
      p={5}
      mb={4}
    >
      <HStack mb={4}>
        <Box bg="linear-gradient(135deg, #5B7FFF, #7C3AED)" p={2} rounded="lg">
          <Box as={FiTrendingUp} color="white" fontSize="lg" />
        </Box>
        <VStack align="start" spacing={0}>
          <Text fontSize="md" fontWeight="bold" color="var(--text-primary)">
            Grille de Notation (sur 100)
          </Text>
          <Text fontSize="xs" color="var(--text-muted)">
            Score composite pondere par importance des metriques
          </Text>
        </VStack>
      </HStack>

      {/* Overall scores */}
      <SimpleGrid columns={{ base: 2, md: 4 }} spacing={3} mb={5}>
        <Box bg="var(--bg-hover)" border="1px solid" borderColor="var(--border-subtle)" rounded="lg" p={4} textAlign="center">
          <Text fontSize="3xl" fontWeight="bold" color={osmAvg !== null ? getScoreColor(osmAvg) : 'var(--text-muted)'}>
            {osmAvg !== null ? `${osmAvg}` : '-'}
          </Text>
          <Text fontSize="xs" color="#5B7FFF" fontWeight="bold">OSMOSIS</Text>
          <Text fontSize="10px" color="var(--text-muted)">{osmAvg !== null ? getScoreLabel(osmAvg) : ''}</Text>
        </Box>
        <Box bg="var(--bg-hover)" border="1px solid" borderColor="var(--border-subtle)" rounded="lg" p={4} textAlign="center">
          <Text fontSize="3xl" fontWeight="bold" color={ragAvg !== null ? getScoreColor(ragAvg) : 'var(--text-muted)'}>
            {ragAvg !== null ? `${ragAvg}` : '-'}
          </Text>
          <Text fontSize="xs" color="#f97316" fontWeight="bold">RAG Baseline</Text>
          <Text fontSize="10px" color="var(--text-muted)">{ragAvg !== null ? getScoreLabel(ragAvg) : ''}</Text>
        </Box>
        <Box bg="var(--bg-hover)" border="1px solid" borderColor="var(--border-subtle)" rounded="lg" p={4} textAlign="center">
          <Text fontSize="3xl" fontWeight="bold" color="var(--text-primary)">
            {osmWins}-{ragWins}
          </Text>
          <Text fontSize="xs" color="var(--text-muted)">Victoires (ties: {ties})</Text>
        </Box>
        <Box bg="var(--bg-hover)" border="1px solid" borderColor="var(--border-subtle)" rounded="lg" p={4} textAlign="center">
          <Text fontSize="3xl" fontWeight="bold" color={osmAvg !== null && ragAvg !== null ? (osmAvg > ragAvg ? '#22c55e' : '#ef4444') : 'var(--text-muted)'}>
            {osmAvg !== null && ragAvg !== null ? `${osmAvg - ragAvg > 0 ? '+' : ''}${osmAvg - ragAvg}` : '-'}
          </Text>
          <Text fontSize="xs" color="var(--text-muted)">Delta global</Text>
        </Box>
      </SimpleGrid>

      {/* Detailed grid */}
      <Box overflowX="auto">
        <Table size="sm">
          <Thead>
            <Tr>
              <Th color="var(--text-muted)" borderColor="var(--border-subtle)">Tache</Th>
              <Th color="var(--text-muted)" borderColor="var(--border-subtle)">Questions</Th>
              <Th color="#5B7FFF" borderColor="var(--border-subtle)" isNumeric>OSMOSIS</Th>
              <Th color="#f97316" borderColor="var(--border-subtle)" isNumeric>RAG</Th>
              <Th color="var(--text-muted)" borderColor="var(--border-subtle)" isNumeric>Delta</Th>
              <Th color="var(--text-muted)" borderColor="var(--border-subtle)">Verdict</Th>
            </Tr>
          </Thead>
          <Tbody>
            {grid.map((entry) => (
              <Tr key={`${entry.task}_${entry.source}`}>
                <Td borderColor="var(--border-subtle)">
                  <VStack align="start" spacing={0}>
                    <Text fontSize="xs" fontWeight="bold" color="var(--text-primary)">
                      {TASK_LABELS[entry.task] || entry.task}
                    </Text>
                    <Badge fontSize="9px" bg={entry.source === 'kg' ? 'purple.900' : 'teal.900'}
                      color={entry.source === 'kg' ? 'purple.300' : 'teal.300'}>
                      {SOURCE_LABELS[entry.source] || entry.source}
                    </Badge>
                  </VStack>
                </Td>
                <Td borderColor="var(--border-subtle)">
                  <Text fontSize="xs" color="var(--text-muted)">
                    {run.tasks.find(t => t.task === entry.task && t.source === entry.source)?.judgments_count || '-'}
                  </Text>
                </Td>
                <Td borderColor="var(--border-subtle)" isNumeric>
                  {entry.osmosis !== null ? (
                    <HStack justify="flex-end" spacing={1}>
                      <Text fontSize="sm" fontWeight="bold" color={getScoreColor(entry.osmosis)}>
                        {entry.osmosis}/100
                      </Text>
                    </HStack>
                  ) : <Text color="var(--text-muted)">-</Text>}
                </Td>
                <Td borderColor="var(--border-subtle)" isNumeric>
                  {entry.rag !== null ? (
                    <Text fontSize="sm" fontWeight="bold" color={getScoreColor(entry.rag)}>
                      {entry.rag}/100
                    </Text>
                  ) : <Text color="var(--text-muted)">-</Text>}
                </Td>
                <Td borderColor="var(--border-subtle)" isNumeric>
                  {entry.delta !== null ? (
                    <Text fontSize="sm" fontWeight="bold"
                      color={entry.delta > 0 ? '#22c55e' : entry.delta < 0 ? '#ef4444' : 'var(--text-muted)'}>
                      {entry.delta > 0 ? '+' : ''}{entry.delta}
                    </Text>
                  ) : <Text color="var(--text-muted)">-</Text>}
                </Td>
                <Td borderColor="var(--border-subtle)">
                  {entry.winner && (
                    <Badge fontSize="10px"
                      bg={entry.winner === 'osmosis' ? 'green.900' : entry.winner === 'rag' ? 'red.900' : 'gray.700'}
                      color={entry.winner === 'osmosis' ? 'green.300' : entry.winner === 'rag' ? 'red.300' : 'gray.300'}>
                      {entry.winner === 'osmosis' ? 'OSMOSIS' : entry.winner === 'rag' ? 'RAG' : 'EGAL'}
                    </Badge>
                  )}
                </Td>
              </Tr>
            ))}
          </Tbody>
        </Table>
      </Box>

      {/* Scoring methodology */}
      <Box mt={4} pt={3} borderTop="1px solid" borderColor="var(--border-subtle)">
        <Text fontSize="xs" fontWeight="bold" color="var(--text-muted)" mb={2}>
          Methodologie de notation
        </Text>
        <SimpleGrid columns={{ base: 1, md: 3 }} spacing={3}>
          {(['T1', 'T2', 'T4'] as const).map(task => {
            const weights = SCORING_WEIGHTS[task]
            if (!weights) return null
            return (
              <Box key={task} bg="var(--bg-hover)" rounded="md" p={2}>
                <Text fontSize="10px" fontWeight="bold" color="var(--text-primary)" mb={1}>
                  {TASK_LABELS[task]}
                </Text>
                {Object.entries(weights).map(([metric, weight]) => (
                  <HStack key={metric} justify="space-between">
                    <Text fontSize="9px" color="var(--text-muted)" noOfLines={1}>
                      {METRIC_EXPLANATIONS[metric]?.label || metric}
                    </Text>
                    <Text fontSize="9px" fontWeight="bold" color="var(--text-muted)">
                      {weight}%
                    </Text>
                  </HStack>
                ))}
              </Box>
            )
          })}
        </SimpleGrid>
      </Box>
    </Box>
  )
}

function ConclusionSection({ runs }: { runs: BenchmarkRun[] }) {
  if (runs.length === 0) return null

  const run = runs[0]
  const osmTasks = run.tasks.filter(t => t.system === 'osmosis')
  const ragTasks = run.tasks.filter(t => t.system !== 'osmosis')
  const hasComparison = ragTasks.length > 0

  // Aggregate scores
  const avgScore = (tasks: TaskResult[], metric: string) => {
    const vals = tasks.map(t => t.scores[metric]).filter(v => typeof v === 'number')
    return vals.length > 0 ? vals.reduce((a, b) => a + b, 0) / vals.length : null
  }

  const osmFactual = avgScore(osmTasks.filter(t => t.task === 'T1'), 'factual_correctness_avg')
  const osmCitation = avgScore(osmTasks.filter(t => t.task === 'T1'), 'citation_present_rate')
  const osmFalseIdk = avgScore(osmTasks.filter(t => t.task === 'T1'), 'false_idk_rate')
  const osmBothSides = avgScore(osmTasks.filter(t => t.task === 'T2'), 'both_sides_surfaced_rate')
  const osmTension = avgScore(osmTasks.filter(t => t.task === 'T2'), 'tension_mentioned_rate')

  return (
    <Box
      bg="var(--bg-hover)"
      border="1px solid"
      borderColor="var(--border-subtle)"
      rounded="xl"
      p={5}
    >
      <HStack mb={3}>
        <Box
          bg="linear-gradient(135deg, #5B7FFF, #7C3AED)"
          p={2}
          rounded="lg"
        >
          <Box as={FiBarChart2} color="white" fontSize="lg" />
        </Box>
        <Text fontSize="md" fontWeight="bold" color="var(--text-primary)">
          Conclusion du Benchmark
        </Text>
      </HStack>

      <VStack align="stretch" spacing={3}>
        <Box>
          <Text fontSize="sm" fontWeight="bold" color="var(--text-primary)" mb={1}>
            Protocole
          </Text>
          <Text fontSize="xs" color="var(--text-muted)" lineHeight="1.6">
            Ce benchmark compare OSMOSIS (retrieval enrichi par Knowledge Graph + synthese LLM) contre un RAG baseline
            (meme collection vectorielle, meme LLM, mais SANS enrichissement KG). Les deux systemes utilisent le meme
            modele de synthese (GPT-4o-mini) pour garantir une comparaison equitable. Seul le retrieval et
            l'enrichissement contextuel different. Les questions sont de deux types : KG-derived (generees depuis le
            Knowledge Graph — avantage structurel potentiel pour OSMOSIS) et humaines (generees en lisant les documents
            bruts — test non biaise).
          </Text>
        </Box>

        {osmFactual !== null && (
          <Box>
            <Text fontSize="sm" fontWeight="bold" color="var(--text-primary)" mb={1}>
              T1 — Provenance & Citations
            </Text>
            <Text fontSize="xs" color="var(--text-muted)" lineHeight="1.6">
              Exactitude factuelle moyenne : <Text as="span" fontWeight="bold" color={osmFactual >= 0.5 ? '#22c55e' : '#eab308'}>{(osmFactual * 100).toFixed(0)}%</Text>.
              {osmCitation !== null && <> Citations presentes dans {(osmCitation * 100).toFixed(0)}% des reponses.</>}
              {osmFalseIdk !== null && osmFalseIdk > 0.3 && (
                <> Attention : taux de faux &quot;je ne sais pas&quot; eleve ({(osmFalseIdk * 100).toFixed(0)}%) — le systeme
                  refuse de repondre alors que l'information existe dans le corpus.</>
              )}
              {osmFalseIdk !== null && osmFalseIdk <= 0.3 && (
                <> Bon taux de reponse : seulement {(osmFalseIdk * 100).toFixed(0)}% de refus injustifies.</>
              )}
            </Text>
          </Box>
        )}

        {osmBothSides !== null && (
          <Box>
            <Text fontSize="sm" fontWeight="bold" color="var(--text-primary)" mb={1}>
              T2 — Detection des Contradictions
            </Text>
            <Text fontSize="xs" color="var(--text-muted)" lineHeight="1.6">
              Exposition des deux positions : <Text as="span" fontWeight="bold" color={osmBothSides >= 0.5 ? '#22c55e' : '#ef4444'}>{(osmBothSides * 100).toFixed(0)}%</Text>.
              {osmTension !== null && <> Mention explicite des tensions : {(osmTension * 100).toFixed(0)}%.</>}
              {osmBothSides < 0.3 && (
                <> C'est un point faible : le systeme tend a ne presenter qu'une seule position sans signaler les divergences entre documents.</>
              )}
            </Text>
          </Box>
        )}

        {!hasComparison && (
          <Box bg="yellow.900" rounded="md" p={3} border="1px solid" borderColor="yellow.700">
            <Text fontSize="xs" color="yellow.200" fontWeight="bold">
              RAG baseline non disponible
            </Text>
            <Text fontSize="xs" color="yellow.300" mt={1}>
              Le benchmark RAG baseline n'a pas encore ete execute avec succes. Les resultats ci-dessus montrent
              les performances OSMOSIS en absolu. Pour une comparaison relative, relancer le benchmark avec le
              RAG baseline actif.
            </Text>
          </Box>
        )}

        <Box bg="var(--bg-hover)" rounded="md" p={3}>
          <Text fontSize="xs" color="var(--text-muted)">
            <Text as="span" fontWeight="bold">Note methodologique</Text> : Les questions KG-derived sont generees
            a partir du Knowledge Graph (avantage potentiel pour OSMOSIS car le KG contient deja les claims).
            Les questions humaines sont generees en lisant uniquement les documents bruts, sans acces au KG —
            elles constituent un test plus equitable. Un ecart significatif entre les deux sets indique un biais
            potentiel dans les questions KG.
          </Text>
        </Box>
      </VStack>
    </Box>
  )
}

// ── Main page ──────────────────────────────────────────────────────────

function ComparisonTab({ runs }: { runs: BenchmarkRun[] }) {
  const [leftRun, setLeftRun] = useState(0)
  const [rightRun, setRightRun] = useState(runs.length > 1 ? 1 : 0)

  const TASK_KEYS = ['T1_kg', 'T1_human', 'T2_kg', 'T2_human', 'T4_kg', 'T4_human']

  const buildRadarData = (run: BenchmarkRun, taskKey: string) => {
    const [task, source] = taskKey.split('_')
    const osmosis = run.tasks.find(t => t.system === 'osmosis' && t.task === task && t.source === source)
    const baseline = run.tasks.find(t => t.system !== 'osmosis' && t.task === task && t.source === source)
    if (!osmosis) return []

    const normalizeValue = (value: number, higherIsBetter: boolean) =>
      higherIsBetter ? value : (1 - value)

    return Object.entries(osmosis.scores)
      .filter(([k]) => k !== 'total_evaluated')
      .map(([key, value]) => {
        const info = METRIC_EXPLANATIONS[key]
        const hib = info?.higherIsBetter ?? true
        const rawVal = typeof value === 'number' ? value : 0
        return {
          label: info?.label || key,
          value: normalizeValue(rawVal, hib),
          higherIsBetter: true,
          baselineValue: baseline
            ? normalizeValue(typeof baseline.scores[key] === 'number' ? baseline.scores[key] : 0, hib)
            : undefined,
        }
      })
  }

  const formatRunLabel = (r: BenchmarkRun) =>
    `${r.timestamp.replace(/(\d{4})(\d{2})(\d{2})_?(.*)/, '$1-$2-$3 $4')} (${r.tasks.length} eval)`

  return (
    <Box>
      {/* Deux selecteurs cote a cote */}
      <SimpleGrid columns={2} spacing={4} mb={5}>
        <Box>
          <Text fontSize="xs" color="#5B7FFF" fontWeight="bold" mb={1}>Benchmark A (gauche)</Text>
          <Select size="sm" bg="var(--bg-hover)" borderColor="var(--border-subtle)"
            value={leftRun} onChange={e => setLeftRun(Number(e.target.value))}>
            {runs.map((r, i) => <option key={r.timestamp} value={i}>{formatRunLabel(r)}</option>)}
          </Select>
        </Box>
        <Box>
          <Text fontSize="xs" color="#f97316" fontWeight="bold" mb={1}>Benchmark B (droite)</Text>
          <Select size="sm" bg="var(--bg-hover)" borderColor="var(--border-subtle)"
            value={rightRun} onChange={e => setRightRun(Number(e.target.value))}>
            {runs.map((r, i) => <option key={r.timestamp} value={i}>{formatRunLabel(r)}</option>)}
          </Select>
        </Box>
      </SimpleGrid>

      {/* 6 radars en grille 2 colonnes */}
      {TASK_KEYS.map(taskKey => {
        const [task, source] = taskKey.split('_')
        const leftData = runs[leftRun] ? buildRadarData(runs[leftRun], taskKey) : []
        const rightData = runs[rightRun] ? buildRadarData(runs[rightRun], taskKey) : []

        if (leftData.length === 0 && rightData.length === 0) return null

        return (
          <Box key={taskKey} mb={4}>
            <HStack mb={2}>
              <Text fontSize="sm" fontWeight="bold" color="var(--text-primary)">
                {TASK_LABELS[task] || task}
              </Text>
              <Badge fontSize="9px" bg={source === 'kg' ? 'purple.900' : 'teal.900'}
                color={source === 'kg' ? 'purple.300' : 'teal.300'}>
                {SOURCE_LABELS[source] || source}
              </Badge>
            </HStack>
            <SimpleGrid columns={2} spacing={2}>
              <Box bg="var(--bg-hover)" border="1px solid" borderColor="var(--border-subtle)" rounded="lg" p={2} textAlign="center">
                <Text fontSize="10px" color="#5B7FFF" fontWeight="bold" mb={1}>
                  {runs[leftRun]?.timestamp || '-'}
                </Text>
                {leftData.length > 0 ? (
                  <RadarChart data={leftData} width={350} height={350} />
                ) : (
                  <Text fontSize="xs" color="var(--text-muted)" py={10}>Pas de donnees</Text>
                )}
              </Box>
              <Box bg="var(--bg-hover)" border="1px solid" borderColor="var(--border-subtle)" rounded="lg" p={2} textAlign="center">
                <Text fontSize="10px" color="#f97316" fontWeight="bold" mb={1}>
                  {runs[rightRun]?.timestamp || '-'}
                </Text>
                {rightData.length > 0 ? (
                  <RadarChart data={rightData} width={350} height={350} />
                ) : (
                  <Text fontSize="xs" color="var(--text-muted)" py={10}>Pas de donnees</Text>
                )}
              </Box>
            </SimpleGrid>
          </Box>
        )
      })}
    </Box>
  )
}


export default function BenchmarksPage() {
  const [runs, setRuns] = useState<BenchmarkRun[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedRun, setSelectedRun] = useState(0)
  const [activeTab, setActiveTab] = useState<'results' | 'compare'>('results')

  useEffect(() => {
    fetch('/api/benchmarks')
      .then(r => r.json())
      .then(data => {
        setRuns(data.runs || [])
        if (data.error) setError(data.error)
        setLoading(false)
      })
      .catch(e => {
        setError(String(e))
        setLoading(false)
      })
  }, [])

  if (loading) {
    return (
      <Box maxW="1200px" mx="auto" p={3} textAlign="center" py={20}>
        <Spinner size="lg" color="brand.400" />
        <Text mt={3} color="var(--text-muted)">Chargement des resultats...</Text>
      </Box>
    )
  }

  const run = runs[selectedRun]

  // Group tasks by task+source
  const taskGroups: Record<string, TaskResult[]> = {}
  if (run) {
    for (const t of run.tasks) {
      const key = `${t.task}_${t.source}`
      if (!taskGroups[key]) taskGroups[key] = []
      taskGroups[key].push(t)
    }
  }

  // Sort: T1_kg, T1_human, T2_kg, T2_human, T4_kg, T4_human
  const sortedKeys = Object.keys(taskGroups).sort()

  return (
    <Box maxW="1200px" mx="auto" p={3}>
      {/* Header */}
      <HStack spacing={3} mb={5}>
        <Box
          bg="linear-gradient(135deg, #5B7FFF, #7C3AED)"
          w={8} h={8}
          rounded="lg"
          display="flex"
          alignItems="center"
          justifyContent="center"
        >
          <Box as={FiBarChart2} color="white" fontSize="md" />
        </Box>
        <VStack align="start" spacing={0}>
          <Text fontSize="lg" fontWeight="bold" color="var(--text-primary)">
            Benchmark OSMOSIS
          </Text>
          <Text fontSize="xs" color="var(--text-muted)">
            Evaluation comparative — Provenance, Contradictions, Audit
          </Text>
        </VStack>
      </HStack>

      {/* Tabs */}
      {runs.length > 0 && (
        <HStack spacing={0} mb={4}>
          <Box as="button" px={4} py={2} fontSize="sm" fontWeight="bold" rounded="lg" roundedRight="none"
            bg={activeTab === 'results' ? '#5B7FFF' : 'var(--bg-hover)'}
            color={activeTab === 'results' ? 'white' : 'var(--text-muted)'}
            onClick={() => setActiveTab('results')}
            _hover={{ opacity: 0.8 }}>
            Resultats
          </Box>
          <Box as="button" px={4} py={2} fontSize="sm" fontWeight="bold" rounded="lg" roundedLeft="none"
            bg={activeTab === 'compare' ? '#5B7FFF' : 'var(--bg-hover)'}
            color={activeTab === 'compare' ? 'white' : 'var(--text-muted)'}
            onClick={() => setActiveTab('compare')}
            _hover={{ opacity: 0.8 }}>
            Comparaison
          </Box>
        </HStack>
      )}

      {runs.length === 0 ? (
        <Box
          bg="var(--bg-hover)"
          border="1px solid"
          borderColor="var(--border-subtle)"
          rounded="xl"
          p={8}
          textAlign="center"
        >
          <Text color="var(--text-muted)">
            Aucun resultat de benchmark disponible.
          </Text>
          <Text fontSize="xs" color="var(--text-muted)" mt={2}>
            Lancez le benchmark avec : python benchmark/run_benchmark.py --full --include-human
          </Text>
        </Box>
      ) : activeTab === 'compare' ? (
        <ComparisonTab runs={runs} />
      ) : (
        <>
          {/* Run selector */}
          {runs.length > 1 && (
            <HStack mb={4}>
              <Text fontSize="xs" color="var(--text-muted)">Run :</Text>
              <Select
                size="xs"
                maxW="300px"
                bg="var(--bg-hover)"
                borderColor="var(--border-subtle)"
                value={selectedRun}
                onChange={e => setSelectedRun(Number(e.target.value))}
              >
                {runs.map((r, i) => (
                  <option key={r.timestamp} value={i}>
                    {r.timestamp.replace(/(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})/, '$1-$2-$3 $4:$5:$6')}
                    {' '}({r.tasks.length} evaluations)
                  </option>
                ))}
              </Select>
            </HStack>
          )}

          {/* Summary stats */}
          {run && (
            <SimpleGrid columns={{ base: 2, md: 4 }} spacing={3} mb={5}>
              <Box bg="var(--bg-hover)" border="1px solid" borderColor="var(--border-subtle)" rounded="lg" p={3} textAlign="center">
                <Text fontSize="2xl" fontWeight="bold" color="#5B7FFF">{run.tasks.filter(t => t.system === 'osmosis').length}</Text>
                <Text fontSize="xs" color="var(--text-muted)">Evaluations OSMOSIS</Text>
              </Box>
              <Box bg="var(--bg-hover)" border="1px solid" borderColor="var(--border-subtle)" rounded="lg" p={3} textAlign="center">
                <Text fontSize="2xl" fontWeight="bold" color="#f97316">{run.tasks.filter(t => t.system !== 'osmosis').length}</Text>
                <Text fontSize="xs" color="var(--text-muted)">Evaluations RAG</Text>
              </Box>
              <Box bg="var(--bg-hover)" border="1px solid" borderColor="var(--border-subtle)" rounded="lg" p={3} textAlign="center">
                <Text fontSize="2xl" fontWeight="bold" color="var(--text-primary)">
                  {run.tasks.reduce((s, t) => s + t.judgments_count, 0)}
                </Text>
                <Text fontSize="xs" color="var(--text-muted)">Questions evaluees</Text>
              </Box>
              <Box bg="var(--bg-hover)" border="1px solid" borderColor="var(--border-subtle)" rounded="lg" p={3} textAlign="center">
                <Text fontSize="2xl" fontWeight="bold" color="var(--text-primary)">
                  {new Set(run.tasks.map(t => t.task)).size}
                </Text>
                <Text fontSize="xs" color="var(--text-muted)">Taches evaluees</Text>
              </Box>
            </SimpleGrid>
          )}

          {/* Referentiels evalues */}
          <Box
            bg="var(--bg-hover)"
            border="1px solid"
            borderColor="var(--border-subtle)"
            rounded="xl"
            p={4}
            mb={4}
          >
            <Text fontSize="sm" fontWeight="bold" color="var(--text-primary)" mb={3}>
              Referentiels de conformite evalues
            </Text>
            <SimpleGrid columns={{ base: 2, md: 4 }} spacing={3}>
              {Object.entries(FRAMEWORK_INFO).map(([key, info]) => {
                // Compter combien de metriques utilisent ce referentiel
                const metricCount = Object.values(METRIC_EXPLANATIONS).filter(
                  m => m.frameworks.some(f => f.startsWith(key))
                ).length
                if (metricCount === 0) return null
                return (
                  <HStack
                    key={key}
                    bg={`${info.color}11`}
                    border="1px solid"
                    borderColor={`${info.color}33`}
                    rounded="md"
                    p={2}
                    spacing={2}
                  >
                    <Box w={1} h={8} bg={info.color} rounded="full" flexShrink={0} />
                    <VStack align="start" spacing={0}>
                      <Text fontSize="xs" fontWeight="bold" color={info.color}>
                        {info.name}
                      </Text>
                      <Text fontSize="9px" color="var(--text-muted)" noOfLines={2}>
                        {info.description}
                      </Text>
                      <Text fontSize="9px" color="var(--text-muted)">
                        {metricCount} metriques
                      </Text>
                    </VStack>
                  </HStack>
                )
              })}
            </SimpleGrid>
          </Box>

          {/* Task sections */}
          {sortedKeys.map(key => {
            const results = taskGroups[key]
            const [task, source] = key.split('_')
            return (
              <TaskSection
                key={key}
                task={task}
                source={source}
                results={results}
              />
            )
          })}

          {/* Scoring Grid */}
          <ScoringGrid run={run} />

          {/* Conclusion */}
          <ConclusionSection runs={[run]} />
        </>
      )}
    </Box>
  )
}
