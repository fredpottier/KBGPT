'use client'

import { useState, useMemo } from 'react'
import {
  Box,
  HStack,
  VStack,
  Text,
  Badge,
  Select,
  Button,
  Table,
  Thead,
  Tbody,
  Tr,
  Th,
  Td,
} from '@chakra-ui/react'
import { FiAlertTriangle, FiSearch, FiChevronDown } from 'react-icons/fi'

import { ScoreGauge } from '../benchmarks/ScoreGauge'
import { RadarChart } from '../benchmarks/RadarChart'
import { MetricBar } from '../benchmarks/MetricBar'
import { QuestionDetailRow } from '../benchmarks/QuestionDetailRow'
import { LaunchPanel } from '../benchmarks/LaunchPanel'

// ─── Design tokens ──────────────────────────────────────────────────
const BG_BASE = '#0a0a1a'
const BG_CARD = '#12122a'
const BG_ELEVATED = '#1a1a35'
const BORDER_SUBTLE = '#1e1e3a'
const ACCENT = '#f97316'
const TEXT_PRIMARY = '#f8fafc'
const TEXT_SECONDARY = '#94a3b8'
const TEXT_MUTED = '#475569'
const STATUS_OK = '#22c55e'
const STATUS_WARN = '#eab308'
const STATUS_ERROR = '#ef4444'

// ─── 10 categories ──────────────────────────────────────────────────
const CATEGORIES = [
  'false_premise',
  'unanswerable',
  'temporal_evolution',
  'causal_why',
  'hypothetical',
  'negation',
  'synthesis_large',
  'conditional',
  'set_list',
  'multi_hop',
] as const

type Category = (typeof CATEGORIES)[number]

const CATEGORY_LABELS: Record<Category, string> = {
  false_premise: 'Fausse premisse',
  unanswerable: 'Non-repondable',
  temporal_evolution: 'Temporel',
  causal_why: 'Causal (why)',
  hypothetical: 'Hypothetique',
  negation: 'Negation',
  synthesis_large: 'Synthese large',
  conditional: 'Conditionnel',
  set_list: 'Ensemble/liste',
  multi_hop: 'Multi-hop',
}

// ─── Types ──────────────────────────────────────────────────────────
interface Report {
  filename: string
  timestamp: string
  tag?: string
  description?: string
  duration_s: number
  scores: Record<string, number>
  per_sample?: Array<{
    question_id: string
    question: string
    category: string
    answer?: string
    evaluation: Record<string, any>
  }>
  errors: number
}

interface RobustnessTabProps {
  reports: Report[]
  onLaunch: (profile: string, tag: string, description: string) => void
  isRunning: boolean
  runProgress: any | null
}

const PAGE_SIZE = 20

// ─── Helpers ────────────────────────────────────────────────────────

function getLatestReport(reports: Report[]): Report | null {
  if (reports.length === 0) return null
  return reports.reduce((a, b) => (a.timestamp > b.timestamp ? a : b))
}

function getBaseline(reports: Report[]): Report | null {
  if (reports.length === 0) return null
  return reports.reduce((a, b) => (a.timestamp < b.timestamp ? a : b))
}

function computeCategoryScores(report: Report): Record<Category, { score: number; count: number }> {
  const result = {} as Record<Category, { score: number; count: number }>
  for (const cat of CATEGORIES) {
    // Prefer scores.{cat}_score from report-level scores
    const scoreKey = `${cat}_score`
    if (report.scores[scoreKey] !== undefined) {
      const samples = report.per_sample?.filter(s => s.category === cat) ?? []
      result[cat] = { score: report.scores[scoreKey], count: samples.length }
      continue
    }
    // Fallback: compute from per_sample
    const samples = report.per_sample?.filter(s => s.category === cat) ?? []
    if (samples.length === 0) {
      result[cat] = { score: 0, count: 0 }
    } else {
      const avg =
        samples.reduce((sum, s) => sum + (s.evaluation?.score ?? 0), 0) / samples.length
      result[cat] = { score: avg, count: samples.length }
    }
  }
  return result
}

function sampleScore(s: { evaluation: Record<string, any> }): number {
  return s.evaluation?.score ?? s.evaluation?.factual_score ?? 0
}

function formatDelta(delta: number): string {
  const pp = Math.round(delta * 100)
  if (pp === 0) return '='
  return pp > 0 ? `+${pp}` : `${pp}`
}

function formatTs(ts: string): string {
  try {
    const d = new Date(ts)
    return d.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' })
      + ' ' + d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
  } catch {
    return ts
  }
}

// ─── Component ──────────────────────────────────────────────────────

export function RobustnessTab({ reports, onLaunch, isRunning, runProgress }: RobustnessTabProps) {
  const [categoryFilter, setCategoryFilter] = useState<string>('all')
  const [passFailFilter, setPassFailFilter] = useState<string>('all')
  const [searchQuery, setSearchQuery] = useState('')
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE)

  // Launch panel state
  const [launchProfile, setLaunchProfile] = useState('default')
  const [launchTag, setLaunchTag] = useState('')
  const [launchDesc, setLaunchDesc] = useState('')

  const latest = useMemo(() => getLatestReport(reports), [reports])
  const baseline = useMemo(() => getBaseline(reports), [reports])
  const catScores = useMemo(() => (latest ? computeCategoryScores(latest) : null), [latest])
  const baselineCatScores = useMemo(
    () => (baseline && baseline !== latest ? computeCategoryScores(baseline) : null),
    [baseline, latest],
  )

  // Radar data
  const radarData = useMemo(() => {
    if (!catScores) return []
    return CATEGORIES.map(c => ({
      label: CATEGORY_LABELS[c],
      value: catScores[c].score,
    }))
  }, [catScores])

  // Sorted category bars (desc)
  const sortedCategories = useMemo(() => {
    if (!catScores) return []
    return [...CATEGORIES].sort((a, b) => catScores[b].score - catScores[a].score)
  }, [catScores])

  // Per-sample filtering + sorting
  const filteredSamples = useMemo(() => {
    if (!latest?.per_sample) return []
    let samples = [...latest.per_sample]

    if (categoryFilter !== 'all') {
      samples = samples.filter(s => s.category === categoryFilter)
    }
    if (passFailFilter === 'pass') {
      samples = samples.filter(s => sampleScore(s) >= 0.5)
    } else if (passFailFilter === 'fail') {
      samples = samples.filter(s => sampleScore(s) < 0.5)
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase()
      samples = samples.filter(
        s =>
          s.question.toLowerCase().includes(q) ||
          s.question_id.toLowerCase().includes(q) ||
          (s.answer ?? '').toLowerCase().includes(q),
      )
    }

    // Sort worst first
    samples.sort((a, b) => sampleScore(a) - sampleScore(b))
    return samples
  }, [latest, categoryFilter, passFailFilter, searchQuery])

  const visibleSamples = filteredSamples.slice(0, visibleCount)
  const hasMore = visibleCount < filteredSamples.length

  const globalScore = latest?.scores?.global_score ?? 0
  const totalQuestions = latest?.per_sample?.length ?? 0
  const totalErrors = latest?.errors ?? 0

  // History table rows (all reports sorted by timestamp desc)
  const historyRows = useMemo(() => {
    return [...reports].sort((a, b) => b.timestamp.localeCompare(a.timestamp))
  }, [reports])

  return (
    <VStack align="stretch" spacing={6} w="100%">
      {/* ─── Top row: Score Gauge + stats ────────────────────────── */}
      <HStack spacing={6} align="center" flexWrap="wrap">
        <ScoreGauge
          value={globalScore}
          label="Score Robustesse"
          color={ACCENT}
          size={140}
        />

        <VStack align="start" spacing={2}>
          <HStack spacing={3}>
            <Badge
              fontSize="13px"
              fontFamily="'Fira Code', monospace"
              bg={`${ACCENT}18`}
              color={ACCENT}
              border="1px solid"
              borderColor={`${ACCENT}40`}
              px={3}
              py={1}
              rounded="md"
            >
              {totalQuestions} questions
            </Badge>
            {totalErrors > 0 && (
              <Badge
                fontSize="13px"
                fontFamily="'Fira Code', monospace"
                bg={`${STATUS_ERROR}18`}
                color={STATUS_ERROR}
                border="1px solid"
                borderColor={`${STATUS_ERROR}40`}
                px={3}
                py={1}
                rounded="md"
              >
                <HStack spacing={1}>
                  <Box as={FiAlertTriangle} />
                  <Text>{totalErrors} erreurs</Text>
                </HStack>
              </Badge>
            )}
          </HStack>

          {latest?.tag && (
            <Text fontSize="12px" color={TEXT_MUTED}>
              Tag: <Text as="span" color={TEXT_SECONDARY} fontFamily="'Fira Code', monospace">{latest.tag}</Text>
            </Text>
          )}
          {latest?.timestamp && (
            <Text fontSize="11px" color={TEXT_MUTED}>
              {formatTs(latest.timestamp)} — {Math.round(latest.duration_s)}s
            </Text>
          )}
        </VStack>
      </HStack>

      {/* ─── Radar + MetricBars row ──────────────────────────────── */}
      {catScores && (
        <HStack spacing={6} align="start" flexWrap={{ base: 'wrap', lg: 'nowrap' }}>
          {/* Left: Radar */}
          <Box
            bg={BG_CARD}
            border="1px solid"
            borderColor={BORDER_SUBTLE}
            rounded="lg"
            p={4}
            flexShrink={0}
          >
            <Text fontSize="sm" fontWeight="700" color={TEXT_PRIMARY} mb={3}>
              Radar des categories
            </Text>
            <RadarChart data={radarData} size={300} color={ACCENT} />
          </Box>

          {/* Right: MetricBars */}
          <Box
            bg={BG_CARD}
            border="1px solid"
            borderColor={BORDER_SUBTLE}
            rounded="lg"
            p={4}
            flex={1}
            minW="300px"
          >
            <Text fontSize="sm" fontWeight="700" color={TEXT_PRIMARY} mb={3}>
              Scores par categorie
            </Text>
            {sortedCategories.map(cat => {
              const delta =
                baselineCatScores && baselineCatScores[cat]
                  ? Math.round((catScores[cat].score - baselineCatScores[cat].score) * 100)
                  : undefined
              return (
                <MetricBar
                  key={cat}
                  label={CATEGORY_LABELS[cat]}
                  value={catScores[cat].score}
                  count={catScores[cat].count}
                  delta={delta !== undefined && delta !== 0 ? delta : null}
                />
              )
            })}
          </Box>
        </HStack>
      )}

      {/* ─── Filter bar ──────────────────────────────────────────── */}
      <Box
        bg={BG_CARD}
        border="1px solid"
        borderColor={BORDER_SUBTLE}
        rounded="lg"
        px={4}
        py={3}
      >
        <HStack spacing={4} flexWrap="wrap">
          {/* Category dropdown */}
          <Box>
            <Text fontSize="10px" color={TEXT_MUTED} mb={1}>Categorie</Text>
            <Select
              size="sm"
              value={categoryFilter}
              onChange={e => { setCategoryFilter(e.target.value); setVisibleCount(PAGE_SIZE) }}
              bg={BG_BASE}
              borderColor={BORDER_SUBTLE}
              color={TEXT_PRIMARY}
              maxW="200px"
              icon={<FiChevronDown />}
            >
              <option value="all">Toutes ({totalQuestions})</option>
              {CATEGORIES.map(cat => {
                const count = catScores?.[cat]?.count ?? 0
                return (
                  <option key={cat} value={cat}>
                    {CATEGORY_LABELS[cat]} ({count})
                  </option>
                )
              })}
            </Select>
          </Box>

          {/* Pass/Fail filter */}
          <Box>
            <Text fontSize="10px" color={TEXT_MUTED} mb={1}>Statut</Text>
            <Select
              size="sm"
              value={passFailFilter}
              onChange={e => { setPassFailFilter(e.target.value); setVisibleCount(PAGE_SIZE) }}
              bg={BG_BASE}
              borderColor={BORDER_SUBTLE}
              color={TEXT_PRIMARY}
              maxW="160px"
              icon={<FiChevronDown />}
            >
              <option value="all">Tous</option>
              <option value="pass">OK uniquement</option>
              <option value="fail">ECHEC uniquement</option>
            </Select>
          </Box>

          {/* Search */}
          <Box flex={1} minW="200px">
            <Text fontSize="10px" color={TEXT_MUTED} mb={1}>Recherche</Text>
            <HStack
              bg={BG_BASE}
              border="1px solid"
              borderColor={BORDER_SUBTLE}
              rounded="md"
              px={3}
              py={1}
            >
              <Box as={FiSearch} color={TEXT_MUTED} fontSize="sm" flexShrink={0} />
              <Box
                as="input"
                type="text"
                value={searchQuery}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                  setSearchQuery(e.target.value)
                  setVisibleCount(PAGE_SIZE)
                }}
                placeholder="Rechercher une question..."
                bg="transparent"
                border="none"
                outline="none"
                fontSize="sm"
                color={TEXT_PRIMARY}
                w="100%"
                _placeholder={{ color: TEXT_MUTED, opacity: 0.5 }}
              />
            </HStack>
          </Box>

          {/* Result count */}
          <Box alignSelf="end" pb={1}>
            <Text fontSize="11px" color={TEXT_MUTED} fontFamily="'Fira Code', monospace">
              {filteredSamples.length} resultat{filteredSamples.length !== 1 ? 's' : ''}
            </Text>
          </Box>
        </HStack>
      </Box>

      {/* ─── Question list ───────────────────────────────────────── */}
      <Box
        bg={BG_CARD}
        border="1px solid"
        borderColor={BORDER_SUBTLE}
        rounded="lg"
        overflow="hidden"
      >
        <Box px={4} py={3} borderBottom="1px solid" borderColor={BORDER_SUBTLE}>
          <Text fontSize="sm" fontWeight="700" color={TEXT_PRIMARY}>
            Detail des questions
          </Text>
          <Text fontSize="11px" color={TEXT_MUTED}>
            Triees par score croissant (pires en premier)
          </Text>
        </Box>

        {visibleSamples.length === 0 ? (
          <Box px={4} py={8} textAlign="center">
            <Text fontSize="13px" color={TEXT_MUTED}>
              Aucune question correspondant aux filtres
            </Text>
          </Box>
        ) : (
          <>
            {visibleSamples.map(s => (
              <QuestionDetailRow
                key={s.question_id}
                questionId={s.question_id}
                question={s.question}
                category={s.category}
                score={sampleScore(s)}
                answer={s.answer}
                evaluation={s.evaluation}
                groundTruth={s.evaluation?.ground_truth ?? s.evaluation}
                accentColor={ACCENT}
              />
            ))}

            {hasMore && (
              <Box textAlign="center" py={3} borderTop="1px solid" borderColor={BORDER_SUBTLE}>
                <Button
                  size="sm"
                  variant="ghost"
                  color={ACCENT}
                  _hover={{ bg: `${ACCENT}18` }}
                  onClick={() => setVisibleCount(prev => prev + PAGE_SIZE)}
                >
                  Afficher plus ({filteredSamples.length - visibleCount} restantes)
                </Button>
              </Box>
            )}
          </>
        )}
      </Box>

      {/* ─── History table ───────────────────────────────────────── */}
      {historyRows.length > 1 && (
        <Box
          bg={BG_CARD}
          border="1px solid"
          borderColor={BORDER_SUBTLE}
          rounded="lg"
          overflow="hidden"
        >
          <Box px={4} py={3} borderBottom="1px solid" borderColor={BORDER_SUBTLE}>
            <Text fontSize="sm" fontWeight="700" color={TEXT_PRIMARY}>
              Historique des runs
            </Text>
          </Box>
          <Box overflowX="auto">
            <Table size="sm" variant="unstyled">
              <Thead>
                <Tr borderBottom="1px solid" borderColor={BORDER_SUBTLE}>
                  <Th color={TEXT_MUTED} fontSize="10px" fontWeight="600" textTransform="uppercase" py={2}>
                    Date
                  </Th>
                  <Th color={TEXT_MUTED} fontSize="10px" fontWeight="600" textTransform="uppercase" py={2}>
                    Tag
                  </Th>
                  <Th color={TEXT_MUTED} fontSize="10px" fontWeight="600" textTransform="uppercase" py={2} isNumeric>
                    Score
                  </Th>
                  <Th color={TEXT_MUTED} fontSize="10px" fontWeight="600" textTransform="uppercase" py={2} isNumeric>
                    Delta
                  </Th>
                  <Th color={TEXT_MUTED} fontSize="10px" fontWeight="600" textTransform="uppercase" py={2} isNumeric>
                    Questions
                  </Th>
                  <Th color={TEXT_MUTED} fontSize="10px" fontWeight="600" textTransform="uppercase" py={2} isNumeric>
                    Erreurs
                  </Th>
                  <Th color={TEXT_MUTED} fontSize="10px" fontWeight="600" textTransform="uppercase" py={2} isNumeric>
                    Duree
                  </Th>
                  <Th color={TEXT_MUTED} fontSize="10px" fontWeight="600" textTransform="uppercase" py={2}>
                    Description
                  </Th>
                </Tr>
              </Thead>
              <Tbody>
                {historyRows.map((row, idx) => {
                  const score = row.scores?.global_score ?? 0
                  const pct = Math.round(score * 100)
                  const scoreColor = pct >= 70 ? STATUS_OK : pct >= 50 ? STATUS_WARN : STATUS_ERROR
                  const baselineScore = baseline?.scores?.global_score ?? 0
                  const delta = score - baselineScore
                  const isBaseline = row === baseline
                  const isLatest = row === latest

                  return (
                    <Tr
                      key={row.filename}
                      borderBottom="1px solid"
                      borderColor={BORDER_SUBTLE}
                      bg={isLatest ? `${ACCENT}08` : 'transparent'}
                      _hover={{ bg: BG_ELEVATED }}
                    >
                      <Td py={2}>
                        <Text fontSize="12px" color={TEXT_SECONDARY} fontFamily="'Fira Code', monospace">
                          {formatTs(row.timestamp)}
                        </Text>
                      </Td>
                      <Td py={2}>
                        <HStack spacing={1}>
                          {row.tag && (
                            <Badge
                              fontSize="10px"
                              bg={`${ACCENT}18`}
                              color={ACCENT}
                              px={1.5}
                              rounded="sm"
                            >
                              {row.tag}
                            </Badge>
                          )}
                          {isBaseline && (
                            <Badge
                              fontSize="9px"
                              bg={`${TEXT_MUTED}30`}
                              color={TEXT_MUTED}
                              px={1}
                              rounded="sm"
                            >
                              ref
                            </Badge>
                          )}
                        </HStack>
                      </Td>
                      <Td py={2} isNumeric>
                        <Text
                          fontSize="13px"
                          fontWeight="700"
                          fontFamily="'Fira Code', monospace"
                          color={scoreColor}
                        >
                          {pct}%
                        </Text>
                      </Td>
                      <Td py={2} isNumeric>
                        {!isBaseline ? (
                          <Text
                            fontSize="12px"
                            fontFamily="'Fira Code', monospace"
                            color={delta > 0 ? STATUS_OK : delta < 0 ? STATUS_ERROR : TEXT_MUTED}
                          >
                            {formatDelta(delta)}
                          </Text>
                        ) : (
                          <Text fontSize="11px" color={TEXT_MUTED}>--</Text>
                        )}
                      </Td>
                      <Td py={2} isNumeric>
                        <Text fontSize="12px" color={TEXT_SECONDARY} fontFamily="'Fira Code', monospace">
                          {row.per_sample?.length ?? '?'}
                        </Text>
                      </Td>
                      <Td py={2} isNumeric>
                        <Text
                          fontSize="12px"
                          fontFamily="'Fira Code', monospace"
                          color={row.errors > 0 ? STATUS_ERROR : TEXT_MUTED}
                        >
                          {row.errors}
                        </Text>
                      </Td>
                      <Td py={2} isNumeric>
                        <Text fontSize="12px" color={TEXT_MUTED} fontFamily="'Fira Code', monospace">
                          {Math.round(row.duration_s)}s
                        </Text>
                      </Td>
                      <Td py={2}>
                        <Text fontSize="11px" color={TEXT_MUTED} noOfLines={1} maxW="250px">
                          {row.description ?? '--'}
                        </Text>
                      </Td>
                    </Tr>
                  )
                })}
              </Tbody>
            </Table>
          </Box>
        </Box>
      )}

      {/* ─── Launch panel ────────────────────────────────────────── */}
      <LaunchPanel
        profiles={[
          { key: 'default', label: 'Defaut (100q)' },
          { key: 'quick', label: 'Rapide (20q)' },
          { key: 'full', label: 'Complet (275q)' },
        ]}
        selectedProfile={launchProfile}
        onProfileChange={setLaunchProfile}
        tag={launchTag}
        onTagChange={setLaunchTag}
        description={launchDesc}
        onDescriptionChange={setLaunchDesc}
        onLaunch={() => onLaunch(launchProfile, launchTag, launchDesc)}
        benchTypes={[
          { key: 'robustness', label: 'Lancer Robustesse', color: ACCENT },
        ]}
        isRunning={isRunning}
        runProgress={runProgress}
        accentColor={ACCENT}
      />
    </VStack>
  )
}
