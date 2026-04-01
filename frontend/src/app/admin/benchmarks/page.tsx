'use client'

import { useEffect, useState, useMemo, useCallback } from 'react'
import {
  Box,
  HStack,
  VStack,
  Text,
  Badge,
  Select,
  Table,
  Thead,
  Tbody,
  Tr,
  Th,
  Td,
  Progress,
  Collapse,
} from '@chakra-ui/react'
import {
  FiActivity,
  FiBarChart2,
  FiAlertTriangle,
  FiShield,
  FiGitMerge,
  FiTrendingUp,
  FiTrendingDown,
  FiMinus,
  FiChevronDown,
  FiChevronRight,
} from 'react-icons/fi'

import {
  ScoreGauge,
  MetricBar,
  LaunchPanel,
  QuestionDetailRow,
  OverviewTab,
  RobustnessTab,
} from '@/components/benchmarks'

// ── Design tokens ─────────────────────────────────────────────────────

const T = {
  bgBase: '#0a0a1a',
  bgCard: '#12122a',
  bgElevated: '#1a1a35',
  borderSubtle: '#1e1e3a',
  accentRagas: '#5B7FFF',
  accentContra: '#7C3AED',
  accentRobust: '#f97316',
  textPrimary: '#f8fafc',
  textSecondary: '#94a3b8',
  textMuted: '#475569',
  statusOk: '#22c55e',
  statusWarn: '#eab308',
  statusError: '#ef4444',
}

const API = ''  // Use Next.js proxy routes (relative paths)

// ── Types ─────────────────────────────────────────────────────────────

interface RagasReport {
  filename: string
  timestamp: string
  tag?: string
  description?: string
  profile?: string
  systems: Record<string, {
    label: string
    sample_count: number
    duration_s: number | null
    scores: Record<string, number>
    diagnostic: { level: string; message: string; color: string }
    worst_samples: Array<{ question: string; faithfulness: number | null; context_relevance: number | null }>
  }>
}

interface T2T5Report {
  filename: string
  timestamp: string
  tag?: string
  description?: string
  profile: string
  profile_label: string
  duration_s: number
  scores: Record<string, number>
  total_evaluated: number
}

interface RobustnessReport {
  filename: string
  timestamp: string
  tag?: string
  description?: string
  duration_s: number
  scores: Record<string, number>
  errors: number
  per_sample?: Array<{
    question_id: string
    question: string
    category: string
    answer?: string
    evaluation: Record<string, any>
  }>
}

interface RunProgress {
  phase: string
  progress: number
  total: number
  current_question?: string
}

type TabKey = 'overview' | 'ragas' | 'contradictions' | 'robustness' | 'comparison'

// ── Tab definitions ───────────────────────────────────────────────────

const TABS: { key: TabKey; label: string; Icon: React.ElementType; accent: string }[] = [
  { key: 'overview', label: 'Vue d\'ensemble', Icon: FiActivity, accent: T.accentRagas },
  { key: 'ragas', label: 'RAGAS', Icon: FiBarChart2, accent: T.accentRagas },
  { key: 'contradictions', label: 'Contradictions', Icon: FiAlertTriangle, accent: T.accentContra },
  { key: 'robustness', label: 'Robustesse', Icon: FiShield, accent: T.accentRobust },
  { key: 'comparison', label: 'Comparaison', Icon: FiGitMerge, accent: T.accentRagas },
]

const PROFILES = [
  { key: 'default', label: 'Defaut (100q)' },
  { key: 'quick', label: 'Quick (25q)' },
  { key: 'full', label: 'Full (275q)' },
]

// ── Helpers ───────────────────────────────────────────────────────────

function formatTs(ts: string): string {
  try {
    const d = new Date(ts)
    return d.toLocaleDateString('fr-FR', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
  } catch {
    return ts
  }
}

function formatDelta(delta: number | null): { text: string; color: string; Icon: React.ElementType } {
  if (delta == null) return { text: '--', color: T.textMuted, Icon: FiMinus }
  const sign = delta > 0 ? '+' : ''
  const pct = `${sign}${(delta * 100).toFixed(1)}%`
  if (delta > 0.01) return { text: pct, color: T.statusOk, Icon: FiTrendingUp }
  if (delta < -0.01) return { text: pct, color: T.statusError, Icon: FiTrendingDown }
  return { text: pct, color: T.textMuted, Icon: FiMinus }
}

function scoreColor(v: number): string {
  const pct = Math.round(v * 100)
  return pct >= 70 ? T.statusOk : pct >= 50 ? T.statusWarn : T.statusError
}

async function apiFetch<R>(path: string, options?: RequestInit): Promise<R | null> {
  try {
    const res = await fetch(`${API}${path}`, options)
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}

// ── Card wrapper ──────────────────────────────────────────────────────

function Card({ children, accent, ...props }: { children: React.ReactNode; accent?: string; [k: string]: any }) {
  return (
    <Box
      bg={T.bgCard}
      border="1px solid"
      borderColor={T.borderSubtle}
      rounded="xl"
      p={5}
      position="relative"
      overflow="hidden"
      _before={accent ? {
        content: '""', position: 'absolute', top: 0, left: 0, right: 0, height: '2px', bg: accent, opacity: 0.7,
      } : undefined}
      {...props}
    >
      {children}
    </Box>
  )
}

// ══════════════════════════════════════════════════════════════════════
//  MAIN PAGE
// ══════════════════════════════════════════════════════════════════════

export default function BenchmarksPage() {
  // ── Tab state ───────────────────────────────────────────────────────
  const [activeTab, setActiveTab] = useState<TabKey>('overview')

  // ── Report lists ────────────────────────────────────────────────────
  const [ragasReports, setRagasReports] = useState<RagasReport[]>([])
  const [t2t5Reports, setT2t5Reports] = useState<T2T5Report[]>([])
  const [robustnessReports, setRobustnessReports] = useState<RobustnessReport[]>([])

  // ── Detailed reports (latest) ───────────────────────────────────────
  const [latestRagasDetail, setLatestRagasDetail] = useState<RagasReport | null>(null)
  const [latestRobustnessDetail, setLatestRobustnessDetail] = useState<RobustnessReport | null>(null)

  // ── Run state ───────────────────────────────────────────────────────
  const [isRunning, setIsRunning] = useState(false)
  const [runType, setRunType] = useState<string | null>(null)
  const [runProgress, setRunProgress] = useState<RunProgress | null>(null)

  // ── Comparison state ────────────────────────────────────────────────
  const [compRunA, setCompRunA] = useState<string>('')
  const [compRunB, setCompRunB] = useState<string>('')
  const [compDetailA, setCompDetailA] = useState<RagasReport | null>(null)
  const [compDetailB, setCompDetailB] = useState<RagasReport | null>(null)

  // ── Data fetching ───────────────────────────────────────────────────

  const fetchAllLists = useCallback(async () => {
    const [ragasData, t2t5Data, robustData] = await Promise.all([
      apiFetch<{ reports: RagasReport[] }>('/api/benchmarks/ragas'),
      apiFetch<{ reports: T2T5Report[] }>('/api/benchmarks/t2t5'),
      apiFetch<{ reports: RobustnessReport[] }>('/api/benchmarks/robustness'),
    ])
    const ragas = ragasData?.reports || []
    const t2t5 = t2t5Data?.reports || []
    const robust = robustData?.reports || []
    setRagasReports(ragas)
    setT2t5Reports(t2t5)
    setRobustnessReports(robust)

    // Fetch latest details
    if (ragas && ragas.length > 0) {
      const latest = [...ragas].sort((a, b) => b.timestamp.localeCompare(a.timestamp))[0]
      const detail = await apiFetch<RagasReport>(`/api/benchmarks/ragas/${encodeURIComponent(latest.filename)}`)
      if (detail) setLatestRagasDetail(detail)
    }
    if (robust && robust.length > 0) {
      const latest = [...robust].sort((a, b) => b.timestamp.localeCompare(a.timestamp))[0]
      const detail = await apiFetch<RobustnessReport>(`/api/benchmarks/robustness/${encodeURIComponent(latest.filename)}`)
      if (detail) setLatestRobustnessDetail(detail)
    }
  }, [])

  useEffect(() => {
    fetchAllLists()
  }, [fetchAllLists])

  // ── Progress polling ────────────────────────────────────────────────

  useEffect(() => {
    if (!isRunning || !runType) return
    const endpoints: Record<string, string> = {
      ragas: '/api/benchmarks/ragas/progress',
      t2t5: '/api/benchmarks/t2t5/progress',
      robustness: '/api/benchmarks/robustness/progress',
    }
    const url = endpoints[runType]
    if (!url) return

    const interval = setInterval(async () => {
      const prog = await apiFetch<RunProgress>(url)
      if (prog) {
        setRunProgress(prog)
        if (prog.phase === 'done' || prog.phase === 'error' || prog.phase === 'idle') {
          setIsRunning(false)
          setRunType(null)
          setRunProgress(null)
          fetchAllLists()
        }
      }
    }, 5000)

    return () => clearInterval(interval)
  }, [isRunning, runType, fetchAllLists])

  // ── Launch callback ─────────────────────────────────────────────────

  const handleLaunch = useCallback(async (benchType: string, profile: string, tag: string, description: string) => {
    const endpoints: Record<string, string> = {
      ragas: '/api/benchmarks/ragas/run',
      t2t5: '/api/benchmarks/t2t5/run',
      robustness: '/api/benchmarks/robustness/run',
    }
    const url = endpoints[benchType]
    if (!url) return

    setIsRunning(true)
    setRunType(benchType)
    setRunProgress({ phase: 'starting', progress: 0, total: 0 })

    await apiFetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ profile, tag: tag || undefined, description: description || undefined }),
    })
  }, [])

  // ── Comparison fetching ─────────────────────────────────────────────

  useEffect(() => {
    if (!compRunA) { setCompDetailA(null); return }
    apiFetch<RagasReport>(`/api/benchmarks/ragas/${encodeURIComponent(compRunA)}`).then(d => setCompDetailA(d))
  }, [compRunA])

  useEffect(() => {
    if (!compRunB) { setCompDetailB(null); return }
    apiFetch<RagasReport>(`/api/benchmarks/ragas/${encodeURIComponent(compRunB)}`).then(d => setCompDetailB(d))
  }, [compRunB])

  // ── Derived data ────────────────────────────────────────────────────

  const latestRagas = useMemo(() => {
    if (ragasReports.length === 0) return null
    return [...ragasReports].sort((a, b) => b.timestamp.localeCompare(a.timestamp))[0]
  }, [ragasReports])

  const latestT2t5 = useMemo(() => {
    if (t2t5Reports.length === 0) return null
    return [...t2t5Reports].sort((a, b) => b.timestamp.localeCompare(a.timestamp))[0]
  }, [t2t5Reports])

  const latestRobustness = useMemo(() => {
    if (robustnessReports.length === 0) return null
    return [...robustnessReports].sort((a, b) => b.timestamp.localeCompare(a.timestamp))[0]
  }, [robustnessReports])

  const recentRuns = useMemo(() => {
    const runs: Array<{ type: string; tag: string; score: number; delta: number | null; timestamp: string; filename: string; synthesis_model?: string }> = []

    const ragasSorted = [...ragasReports].sort((a, b) => a.timestamp.localeCompare(b.timestamp))
    const baselineRagasScore = ragasSorted[0]?.systems?.osmosis?.scores?.faithfulness ?? null

    for (const r of ragasReports) {
      const s = r.systems?.osmosis?.scores?.faithfulness ?? 0
      const delta = baselineRagasScore != null ? s - baselineRagasScore : null
      runs.push({ type: 'ragas', tag: r.tag || '', score: s, delta, timestamp: r.timestamp, filename: r.filename, synthesis_model: (r as any).synthesis_model })
    }

    const t2Sorted = [...t2t5Reports].sort((a, b) => a.timestamp.localeCompare(b.timestamp))
    const baselineT2Score = t2Sorted[0]?.scores?.both_sides_surfaced ?? null

    for (const r of t2t5Reports) {
      const s = r.scores?.both_sides_surfaced ?? 0
      const delta = baselineT2Score != null ? s - baselineT2Score : null
      runs.push({ type: 't2t5', tag: r.tag || '', score: s, delta, timestamp: r.timestamp, filename: r.filename, synthesis_model: (r as any).synthesis_model })
    }

    const robSorted = [...robustnessReports].sort((a, b) => a.timestamp.localeCompare(b.timestamp))
    const baselineRobScore = robSorted[0]?.scores?.global_score ?? null

    for (const r of robustnessReports) {
      const s = r.scores?.global_score ?? 0
      const delta = baselineRobScore != null ? s - baselineRobScore : null
      runs.push({ type: 'robustness', tag: r.tag || '', score: s, delta, timestamp: r.timestamp, filename: r.filename, synthesis_model: (r as any).synthesis_model })
    }

    runs.sort((a, b) => b.timestamp.localeCompare(a.timestamp))
    return runs.slice(0, 5)
  }, [ragasReports, t2t5Reports, robustnessReports])

  // ══════════════════════════════════════════════════════════════════════
  //  RENDER
  // ══════════════════════════════════════════════════════════════════════

  return (
    <Box minH="100vh" bg={T.bgBase} px={6} py={6}>
      {/* Header */}
      <HStack mb={6} spacing={3} align="center">
        <FiBarChart2 size={22} color={T.accentRagas} />
        <Text fontSize="xl" fontWeight="800" color={T.textPrimary}>
          Benchmark Dashboard
        </Text>
        <Badge
          fontSize="10px"
          bg={`${T.accentRagas}18`}
          color={T.accentRagas}
          px={2}
          rounded="md"
        >
          OSMOSIS
        </Badge>
      </HStack>

      {/* Tab bar */}
      <HStack
        spacing={0}
        mb={6}
        borderBottom="1px solid"
        borderColor={T.borderSubtle}
        overflowX="auto"
      >
        {TABS.map(tab => {
          const isActive = activeTab === tab.key
          return (
            <Box
              key={tab.key}
              as="button"
              onClick={() => setActiveTab(tab.key)}
              px={5}
              py={3}
              borderBottom="2px solid"
              borderColor={isActive ? tab.accent : 'transparent'}
              transition="all 0.2s"
              _hover={{ bg: T.bgElevated }}
              cursor="pointer"
              flexShrink={0}
            >
              <HStack spacing={2}>
                <tab.Icon size={14} color={isActive ? tab.accent : T.textMuted} />
                <Text
                  fontSize="13px"
                  fontWeight={isActive ? '700' : '500'}
                  color={isActive ? T.textPrimary : T.textMuted}
                >
                  {tab.label}
                </Text>
              </HStack>
            </Box>
          )
        })}
      </HStack>

      {/* Tab content */}
      {activeTab === 'overview' && (
        <OverviewTab
          ragasReport={latestRagas}
          t2t5Report={latestT2t5}
          robustnessReport={latestRobustness}
          recentRuns={recentRuns}
          onLaunch={handleLaunch}
          isRunning={isRunning}
          runProgress={runProgress}
        />
      )}

      {activeTab === 'ragas' && (
        <RagasTab
          reports={ragasReports}
          latestDetail={latestRagas}
          onLaunch={handleLaunch}
          isRunning={isRunning}
          runProgress={runProgress}
        />
      )}

      {activeTab === 'contradictions' && (
        <ContradictionsTab
          reports={t2t5Reports}
          onLaunch={handleLaunch}
          isRunning={isRunning}
          runProgress={runProgress}
        />
      )}

      {activeTab === 'robustness' && (
        <RobustnessTab
          reports={robustnessReports.map(r => {
            if (r.filename === latestRobustnessDetail?.filename && latestRobustnessDetail?.per_sample) {
              return { ...r, per_sample: latestRobustnessDetail.per_sample }
            }
            return r
          })}
          onLaunch={(profile, tag, description) => handleLaunch('robustness', profile, tag, description)}
          isRunning={isRunning && runType === 'robustness'}
          runProgress={runType === 'robustness' ? runProgress : null}
        />
      )}

      {activeTab === 'comparison' && (
        <ComparisonTab
          ragasReports={ragasReports}
          compRunA={compRunA}
          compRunB={compRunB}
          onSelectA={setCompRunA}
          onSelectB={setCompRunB}
          detailA={compDetailA}
          detailB={compDetailB}
        />
      )}
    </Box>
  )
}

// ══════════════════════════════════════════════════════════════════════
//  TAB 2: RAGAS
// ══════════════════════════════════════════════════════════════════════

function RagasTab({
  reports,
  latestDetail,
  onLaunch,
  isRunning,
  runProgress,
}: {
  reports: RagasReport[]
  latestDetail: RagasReport | null
  onLaunch: (benchType: string, profile: string, tag: string, description: string) => void
  isRunning: boolean
  runProgress: RunProgress | null
}) {
  const [profile, setProfile] = useState('default')
  const [tag, setTag] = useState('')
  const [desc, setDesc] = useState('')
  const [expandedQ, setExpandedQ] = useState<number | null>(null)

  const sorted = useMemo(() =>
    [...reports].sort((a, b) => b.timestamp.localeCompare(a.timestamp)),
    [reports],
  )

  const baseline = useMemo(() =>
    reports.length > 0 ? [...reports].sort((a, b) => a.timestamp.localeCompare(b.timestamp))[0] : null,
    [reports],
  )

  const latest = sorted[0] ?? null
  const detail = latestDetail ?? latest
  const osm = detail?.systems?.osmosis
  const faith = osm?.scores?.faithfulness ?? 0
  const ctxRel = osm?.scores?.context_relevance ?? 0
  const diag = osm?.diagnostic

  const baseFaith = baseline?.systems?.osmosis?.scores?.faithfulness ?? null
  const baseCtxRel = baseline?.systems?.osmosis?.scores?.context_relevance ?? null

  // Diagnostic badge config
  const diagLabel = diag?.level ?? 'Inconnu'
  const diagColor = diag?.color ?? T.textMuted

  const worstSamples = osm?.worst_samples ?? []

  return (
    <VStack spacing={6} align="stretch">
      {/* Gauges row */}
      <HStack spacing={6} align="start" flexWrap="wrap">
        <Card accent={T.accentRagas} flex={1} minW="280px">
          <HStack spacing={6} align="center">
            <ScoreGauge value={faith} label="Faithfulness" color={T.accentRagas} size={130} target={0.80} />
            <VStack align="start" spacing={2} flex={1}>
              <Text fontSize="xs" fontWeight="700" color={T.accentRagas} textTransform="uppercase">
                Fidelite des reponses
              </Text>
              {baseFaith != null && (
                <DeltaBadge current={faith} baseline={baseFaith} />
              )}
              <Text fontSize="11px" color={T.textMuted}>
                {osm?.sample_count ?? '--'} questions evaluees
              </Text>
            </VStack>
          </HStack>
        </Card>

        <Card accent={T.accentContra} flex={1} minW="280px">
          <HStack spacing={6} align="center">
            <ScoreGauge value={ctxRel} label="Context Relevance" color={T.accentContra} size={130} target={0.70} />
            <VStack align="start" spacing={2} flex={1}>
              <Text fontSize="xs" fontWeight="700" color={T.accentContra} textTransform="uppercase">
                Pertinence du contexte
              </Text>
              {baseCtxRel != null && (
                <DeltaBadge current={ctxRel} baseline={baseCtxRel} />
              )}
            </VStack>
          </HStack>
        </Card>

        {/* Diagnostic badge */}
        <Card flex={0} minW="200px">
          <VStack spacing={3} align="center" py={3}>
            <Text fontSize="xs" fontWeight="700" color={T.textMuted} textTransform="uppercase">
              Diagnostic
            </Text>
            <Badge
              fontSize="md"
              fontWeight="700"
              px={4}
              py={2}
              rounded="lg"
              bg={`${diagColor}18`}
              color={diagColor}
              border="1px solid"
              borderColor={`${diagColor}40`}
            >
              {diagLabel}
            </Badge>
            {diag?.message && (
              <Text fontSize="11px" color={T.textSecondary} textAlign="center" maxW="180px">
                {diag.message}
              </Text>
            )}
          </VStack>
        </Card>
      </HStack>

      {/* History table */}
      {sorted.length > 0 && (
        <Card>
          <Text fontSize="sm" fontWeight="700" color={T.textPrimary} mb={3}>
            Historique RAGAS
          </Text>
          <Box overflowX="auto">
            <Table size="sm" variant="unstyled">
              <Thead>
                <Tr borderBottom="1px solid" borderColor={T.borderSubtle}>
                  <Th color={T.textMuted} fontSize="10px" textTransform="uppercase" py={2}>Date</Th>
                  <Th color={T.textMuted} fontSize="10px" textTransform="uppercase" py={2}>Tag</Th>
                  <Th color={T.textMuted} fontSize="10px" textTransform="uppercase" py={2} isNumeric>Faithfulness</Th>
                  <Th color={T.textMuted} fontSize="10px" textTransform="uppercase" py={2} isNumeric>Ctx Rel.</Th>
                  <Th color={T.textMuted} fontSize="10px" textTransform="uppercase" py={2} isNumeric>Delta F.</Th>
                  <Th color={T.textMuted} fontSize="10px" textTransform="uppercase" py={2} isNumeric>Delta C.</Th>
                  <Th color={T.textMuted} fontSize="10px" textTransform="uppercase" py={2}>Description</Th>
                </Tr>
              </Thead>
              <Tbody>
                {sorted.map(row => {
                  const rowOsm = row.systems?.osmosis
                  const f = rowOsm?.scores?.faithfulness ?? 0
                  const c = rowOsm?.scores?.context_relevance ?? 0
                  const isBase = row === baseline
                  const dF = baseFaith != null ? f - baseFaith : null
                  const dC = baseCtxRel != null ? c - baseCtxRel : null

                  return (
                    <Tr
                      key={row.filename}
                      borderBottom="1px solid"
                      borderColor={T.borderSubtle}
                      bg={row === latest ? `${T.accentRagas}08` : 'transparent'}
                      _hover={{ bg: T.bgElevated }}
                    >
                      <Td py={2}>
                        <Text fontSize="12px" color={T.textSecondary} fontFamily="'Fira Code', monospace">
                          {formatTs(row.timestamp)}
                        </Text>
                      </Td>
                      <Td py={2}>
                        <HStack spacing={1}>
                          {row.tag && (
                            <Badge fontSize="10px" bg={`${T.accentRagas}18`} color={T.accentRagas} px={1.5} rounded="sm">
                              {row.tag}
                            </Badge>
                          )}
                          {isBase && (
                            <Badge fontSize="9px" bg={`${T.textMuted}30`} color={T.textMuted} px={1} rounded="sm">
                              baseline
                            </Badge>
                          )}
                        </HStack>
                      </Td>
                      <Td py={2} isNumeric>
                        <Text fontSize="13px" fontWeight="700" fontFamily="'Fira Code', monospace" color={scoreColor(f)}>
                          {Math.round(f * 100)}%
                        </Text>
                      </Td>
                      <Td py={2} isNumeric>
                        <Text fontSize="13px" fontWeight="700" fontFamily="'Fira Code', monospace" color={scoreColor(c)}>
                          {Math.round(c * 100)}%
                        </Text>
                      </Td>
                      <Td py={2} isNumeric>
                        {!isBase && dF != null ? <InlineDelta delta={dF} /> : <Text fontSize="11px" color={T.textMuted}>--</Text>}
                      </Td>
                      <Td py={2} isNumeric>
                        {!isBase && dC != null ? <InlineDelta delta={dC} /> : <Text fontSize="11px" color={T.textMuted}>--</Text>}
                      </Td>
                      <Td py={2}>
                        <Text fontSize="11px" color={T.textMuted} noOfLines={1} maxW="250px">
                          {row.description ?? '--'}
                        </Text>
                      </Td>
                    </Tr>
                  )
                })}
              </Tbody>
            </Table>
          </Box>
        </Card>
      )}

      {/* Worst samples */}
      {worstSamples.length > 0 && (
        <Card>
          <Text fontSize="sm" fontWeight="700" color={T.textPrimary} mb={3}>
            Pires echantillons
          </Text>
          <Text fontSize="11px" color={T.textMuted} mb={3}>
            {worstSamples.length} questions avec les plus bas scores
          </Text>
          {worstSamples.map((ws, idx) => (
            <Box
              key={idx}
              borderBottom="1px solid"
              borderColor={T.borderSubtle}
              _hover={{ bg: T.bgElevated }}
            >
              <HStack
                as="button"
                onClick={() => setExpandedQ(expandedQ === idx ? null : idx)}
                w="100%"
                px={3}
                py={2.5}
                spacing={3}
                cursor="pointer"
              >
                <Box
                  as={expandedQ === idx ? FiChevronDown : FiChevronRight}
                  color={T.textMuted}
                  fontSize="sm"
                  flexShrink={0}
                />
                <Badge
                  fontFamily="'Fira Code', monospace"
                  fontSize="11px"
                  fontWeight="700"
                  bg={`${scoreColor(ws.faithfulness ?? 0)}18`}
                  color={scoreColor(ws.faithfulness ?? 0)}
                  px={2}
                  rounded="md"
                  minW="42px"
                  textAlign="center"
                  flexShrink={0}
                >
                  {ws.faithfulness != null ? `${Math.round(ws.faithfulness * 100)}%` : '--'}
                </Badge>
                <Text fontSize="12px" color={T.textSecondary} flex={1} textAlign="left" noOfLines={1}>
                  {ws.question}
                </Text>
              </HStack>
              <Collapse in={expandedQ === idx} animateOpacity>
                <Box px={10} pb={3}>
                  <HStack spacing={4} flexWrap="wrap">
                    <Box>
                      <Text fontSize="10px" color={T.textMuted}>Faithfulness</Text>
                      <Text fontSize="13px" fontFamily="'Fira Code', monospace" fontWeight="700" color={scoreColor(ws.faithfulness ?? 0)}>
                        {ws.faithfulness != null ? `${Math.round(ws.faithfulness * 100)}%` : '--'}
                      </Text>
                    </Box>
                    <Box>
                      <Text fontSize="10px" color={T.textMuted}>Context Relevance</Text>
                      <Text fontSize="13px" fontFamily="'Fira Code', monospace" fontWeight="700" color={scoreColor(ws.context_relevance ?? 0)}>
                        {ws.context_relevance != null ? `${Math.round(ws.context_relevance * 100)}%` : '--'}
                      </Text>
                    </Box>
                  </HStack>
                </Box>
              </Collapse>
            </Box>
          ))}
        </Card>
      )}

      {/* Launch panel */}
      <LaunchPanel
        profiles={PROFILES}
        selectedProfile={profile}
        onProfileChange={setProfile}
        tag={tag}
        onTagChange={setTag}
        description={desc}
        onDescriptionChange={setDesc}
        onLaunch={() => onLaunch('ragas', profile, tag, desc)}
        benchTypes={[{ key: 'ragas', label: 'Lancer RAGAS', color: T.accentRagas }]}
        isRunning={isRunning}
        runProgress={runProgress ?? undefined}
      />
    </VStack>
  )
}

// ══════════════════════════════════════════════════════════════════════
//  TAB 3: CONTRADICTIONS (T2/T5)
// ══════════════════════════════════════════════════════════════════════

const CONTRA_METRICS = [
  { key: 'tension_mentioned', label: 'Tension mentionnee' },
  { key: 'both_sides_surfaced', label: 'Deux cotes surfaces' },
  { key: 'both_sources_cited', label: 'Sources citees' },
  { key: 'chain_coverage', label: 'Couverture chaines' },
  { key: 'multi_doc_cited', label: 'Multi-doc cite' },
  { key: 'proactive_detection', label: 'Detection proactive' },
] as const

const CONTRA_CATEGORIES = [
  { key: 'cross_doc_chain', label: 'Chaine cross-doc' },
  { key: 'proactive_contradiction', label: 'Contradiction proactive' },
  { key: 'multi_source_synthesis', label: 'Synthese multi-source' },
] as const

function ContradictionsTab({
  reports,
  onLaunch,
  isRunning,
  runProgress,
}: {
  reports: T2T5Report[]
  onLaunch: (benchType: string, profile: string, tag: string, description: string) => void
  isRunning: boolean
  runProgress: RunProgress | null
}) {
  const [profile, setProfile] = useState('default')
  const [tag, setTag] = useState('')
  const [desc, setDesc] = useState('')

  const sorted = useMemo(() =>
    [...reports].sort((a, b) => b.timestamp.localeCompare(a.timestamp)),
    [reports],
  )

  const baseline = useMemo(() =>
    reports.length > 0 ? [...reports].sort((a, b) => a.timestamp.localeCompare(b.timestamp))[0] : null,
    [reports],
  )

  const latest = sorted[0] ?? null
  const scores = latest?.scores ?? {}
  const baseScores = baseline?.scores ?? {}

  return (
    <VStack spacing={6} align="stretch">
      {/* Metric bars */}
      <Card accent={T.accentContra}>
        <Text fontSize="sm" fontWeight="700" color={T.textPrimary} mb={4}>
          Metriques principales
        </Text>
        {CONTRA_METRICS.map(m => {
          const val = scores[m.key] ?? 0
          const baseVal = baseScores[m.key]
          const delta = baseVal != null ? Math.round((val - baseVal) * 100) : null
          return (
            <MetricBar
              key={m.key}
              label={m.label}
              value={val}
              delta={delta !== 0 ? delta : null}
            />
          )
        })}
      </Card>

      {/* Category breakdown */}
      <Card>
        <Text fontSize="sm" fontWeight="700" color={T.textPrimary} mb={4}>
          Par categorie
        </Text>
        {CONTRA_CATEGORIES.map(cat => {
          const val = scores[`${cat.key}_score`] ?? scores[cat.key] ?? 0
          const baseVal = baseScores[`${cat.key}_score`] ?? baseScores[cat.key]
          const delta = baseVal != null ? Math.round((val - baseVal) * 100) : null
          return (
            <MetricBar
              key={cat.key}
              label={cat.label}
              value={val}
              delta={delta !== 0 ? delta : null}
            />
          )
        })}
      </Card>

      {/* History table */}
      {sorted.length > 0 && (
        <Card>
          <Text fontSize="sm" fontWeight="700" color={T.textPrimary} mb={3}>
            Historique T2/T5
          </Text>
          <Box overflowX="auto">
            <Table size="sm" variant="unstyled">
              <Thead>
                <Tr borderBottom="1px solid" borderColor={T.borderSubtle}>
                  <Th color={T.textMuted} fontSize="10px" textTransform="uppercase" py={2}>Date</Th>
                  <Th color={T.textMuted} fontSize="10px" textTransform="uppercase" py={2}>Tag</Th>
                  <Th color={T.textMuted} fontSize="10px" textTransform="uppercase" py={2} isNumeric>Both sides</Th>
                  <Th color={T.textMuted} fontSize="10px" textTransform="uppercase" py={2} isNumeric>Tension</Th>
                  <Th color={T.textMuted} fontSize="10px" textTransform="uppercase" py={2} isNumeric>Delta</Th>
                  <Th color={T.textMuted} fontSize="10px" textTransform="uppercase" py={2} isNumeric>Questions</Th>
                  <Th color={T.textMuted} fontSize="10px" textTransform="uppercase" py={2}>Description</Th>
                </Tr>
              </Thead>
              <Tbody>
                {sorted.map(row => {
                  const bs = row.scores?.both_sides_surfaced ?? 0
                  const tm = row.scores?.tension_mentioned ?? 0
                  const isBase = row === baseline
                  const baseBS = baseline?.scores?.both_sides_surfaced ?? 0
                  const delta = bs - baseBS

                  return (
                    <Tr
                      key={row.filename}
                      borderBottom="1px solid"
                      borderColor={T.borderSubtle}
                      bg={row === latest ? `${T.accentContra}08` : 'transparent'}
                      _hover={{ bg: T.bgElevated }}
                    >
                      <Td py={2}>
                        <Text fontSize="12px" color={T.textSecondary} fontFamily="'Fira Code', monospace">
                          {formatTs(row.timestamp)}
                        </Text>
                      </Td>
                      <Td py={2}>
                        <HStack spacing={1}>
                          {row.tag && (
                            <Badge fontSize="10px" bg={`${T.accentContra}18`} color={T.accentContra} px={1.5} rounded="sm">
                              {row.tag}
                            </Badge>
                          )}
                          {isBase && (
                            <Badge fontSize="9px" bg={`${T.textMuted}30`} color={T.textMuted} px={1} rounded="sm">
                              baseline
                            </Badge>
                          )}
                        </HStack>
                      </Td>
                      <Td py={2} isNumeric>
                        <Text fontSize="13px" fontWeight="700" fontFamily="'Fira Code', monospace" color={scoreColor(bs)}>
                          {Math.round(bs * 100)}%
                        </Text>
                      </Td>
                      <Td py={2} isNumeric>
                        <Text fontSize="13px" fontFamily="'Fira Code', monospace" color={scoreColor(tm)}>
                          {Math.round(tm * 100)}%
                        </Text>
                      </Td>
                      <Td py={2} isNumeric>
                        {!isBase ? <InlineDelta delta={delta} /> : <Text fontSize="11px" color={T.textMuted}>--</Text>}
                      </Td>
                      <Td py={2} isNumeric>
                        <Text fontSize="12px" color={T.textSecondary} fontFamily="'Fira Code', monospace">
                          {row.total_evaluated}
                        </Text>
                      </Td>
                      <Td py={2}>
                        <Text fontSize="11px" color={T.textMuted} noOfLines={1} maxW="250px">
                          {row.description ?? '--'}
                        </Text>
                      </Td>
                    </Tr>
                  )
                })}
              </Tbody>
            </Table>
          </Box>
        </Card>
      )}

      {/* Launch panel */}
      <LaunchPanel
        profiles={PROFILES}
        selectedProfile={profile}
        onProfileChange={setProfile}
        tag={tag}
        onTagChange={setTag}
        description={desc}
        onDescriptionChange={setDesc}
        onLaunch={() => onLaunch('t2t5', profile, tag, desc)}
        benchTypes={[{ key: 't2t5', label: 'Lancer Contradictions', color: T.accentContra }]}
        isRunning={isRunning}
        runProgress={runProgress ?? undefined}
      />
    </VStack>
  )
}

// ══════════════════════════════════════════════════════════════════════
//  TAB 5: COMPARAISON
// ══════════════════════════════════════════════════════════════════════

function ComparisonTab({
  ragasReports,
  compRunA,
  compRunB,
  onSelectA,
  onSelectB,
  detailA,
  detailB,
}: {
  ragasReports: RagasReport[]
  compRunA: string
  compRunB: string
  onSelectA: (v: string) => void
  onSelectB: (v: string) => void
  detailA: RagasReport | null
  detailB: RagasReport | null
}) {
  const sorted = useMemo(() =>
    [...ragasReports].sort((a, b) => b.timestamp.localeCompare(a.timestamp)),
    [ragasReports],
  )

  const osmA = detailA?.systems?.osmosis
  const osmB = detailB?.systems?.osmosis
  const scoresA = osmA?.scores ?? {}
  const scoresB = osmB?.scores ?? {}

  // Collect all metric keys
  const allMetrics = useMemo(() => {
    const keys = new Set<string>()
    for (const k of Object.keys(scoresA)) keys.add(k)
    for (const k of Object.keys(scoresB)) keys.add(k)
    return Array.from(keys).sort()
  }, [scoresA, scoresB])

  // Regressions / improvements
  const diffs = useMemo(() => {
    if (!osmA || !osmB) return []
    return allMetrics.map(m => ({
      metric: m,
      a: scoresA[m] ?? 0,
      b: scoresB[m] ?? 0,
      delta: (scoresB[m] ?? 0) - (scoresA[m] ?? 0),
    })).sort((x, y) => x.delta - y.delta)
  }, [osmA, osmB, allMetrics, scoresA, scoresB])

  const regressions = diffs.filter(d => d.delta < -0.01)
  const improvements = diffs.filter(d => d.delta > 0.01)

  return (
    <VStack spacing={6} align="stretch">
      {/* Selection row */}
      <Card>
        <Text fontSize="sm" fontWeight="700" color={T.textPrimary} mb={4}>
          Selectionner deux runs RAGAS
        </Text>
        <HStack spacing={6} flexWrap="wrap">
          <Box flex={1} minW="250px">
            <Text fontSize="11px" color={T.textMuted} mb={1}>Run A (reference)</Text>
            <Select
              size="sm"
              value={compRunA}
              onChange={e => onSelectA(e.target.value)}
              bg={T.bgBase}
              borderColor={T.borderSubtle}
              color={T.textPrimary}
              placeholder="-- Selectionner --"
            >
              {sorted.map(r => (
                <option key={r.filename} value={r.filename}>
                  {formatTs(r.timestamp)} {r.tag ? `[${r.tag}]` : ''} - F:{Math.round((r.systems?.osmosis?.scores?.faithfulness ?? 0) * 100)}%
                </option>
              ))}
            </Select>
          </Box>
          <Box flex={1} minW="250px">
            <Text fontSize="11px" color={T.textMuted} mb={1}>Run B (nouveau)</Text>
            <Select
              size="sm"
              value={compRunB}
              onChange={e => onSelectB(e.target.value)}
              bg={T.bgBase}
              borderColor={T.borderSubtle}
              color={T.textPrimary}
              placeholder="-- Selectionner --"
            >
              {sorted.map(r => (
                <option key={r.filename} value={r.filename}>
                  {formatTs(r.timestamp)} {r.tag ? `[${r.tag}]` : ''} - F:{Math.round((r.systems?.osmosis?.scores?.faithfulness ?? 0) * 100)}%
                </option>
              ))}
            </Select>
          </Box>
        </HStack>
      </Card>

      {/* Side-by-side comparison */}
      {osmA && osmB && (
        <>
          <Card>
            <Text fontSize="sm" fontWeight="700" color={T.textPrimary} mb={3}>
              Comparaison des metriques
            </Text>
            <Box overflowX="auto">
              <Table size="sm" variant="unstyled">
                <Thead>
                  <Tr borderBottom="1px solid" borderColor={T.borderSubtle}>
                    <Th color={T.textMuted} fontSize="10px" textTransform="uppercase" py={2}>Metrique</Th>
                    <Th color={T.textMuted} fontSize="10px" textTransform="uppercase" py={2} isNumeric>
                      Run A {detailA?.tag && `(${detailA.tag})`}
                    </Th>
                    <Th color={T.textMuted} fontSize="10px" textTransform="uppercase" py={2} isNumeric>
                      Run B {detailB?.tag && `(${detailB.tag})`}
                    </Th>
                    <Th color={T.textMuted} fontSize="10px" textTransform="uppercase" py={2} isNumeric>Delta</Th>
                  </Tr>
                </Thead>
                <Tbody>
                  {allMetrics.map(m => {
                    const a = scoresA[m] ?? 0
                    const b = scoresB[m] ?? 0
                    const d = b - a
                    return (
                      <Tr key={m} borderBottom="1px solid" borderColor={T.borderSubtle} _hover={{ bg: T.bgElevated }}>
                        <Td py={2}>
                          <Text fontSize="12px" color={T.textSecondary}>
                            {m.replace(/_/g, ' ')}
                          </Text>
                        </Td>
                        <Td py={2} isNumeric>
                          <Text fontSize="13px" fontFamily="'Fira Code', monospace" fontWeight="600" color={scoreColor(a)}>
                            {Math.round(a * 100)}%
                          </Text>
                        </Td>
                        <Td py={2} isNumeric>
                          <Text fontSize="13px" fontFamily="'Fira Code', monospace" fontWeight="600" color={scoreColor(b)}>
                            {Math.round(b * 100)}%
                          </Text>
                        </Td>
                        <Td py={2} isNumeric>
                          <InlineDelta delta={d} />
                        </Td>
                      </Tr>
                    )
                  })}
                </Tbody>
              </Table>
            </Box>
          </Card>

          {/* Regressions */}
          {regressions.length > 0 && (
            <Card accent={T.statusError}>
              <Text fontSize="sm" fontWeight="700" color={T.statusError} mb={3}>
                Regressions ({regressions.length})
              </Text>
              {regressions.map(d => (
                <HStack key={d.metric} spacing={3} py={1.5} borderBottom="1px solid" borderColor={T.borderSubtle}>
                  <FiTrendingDown size={14} color={T.statusError} />
                  <Text fontSize="12px" color={T.textSecondary} flex={1}>
                    {d.metric.replace(/_/g, ' ')}
                  </Text>
                  <Text fontSize="12px" fontFamily="'Fira Code', monospace" color={T.statusError}>
                    {Math.round(d.a * 100)}% &rarr; {Math.round(d.b * 100)}% ({Math.round(d.delta * 100) > 0 ? '+' : ''}{Math.round(d.delta * 100)}pp)
                  </Text>
                </HStack>
              ))}
            </Card>
          )}

          {/* Improvements */}
          {improvements.length > 0 && (
            <Card accent={T.statusOk}>
              <Text fontSize="sm" fontWeight="700" color={T.statusOk} mb={3}>
                Ameliorations ({improvements.length})
              </Text>
              {improvements.map(d => (
                <HStack key={d.metric} spacing={3} py={1.5} borderBottom="1px solid" borderColor={T.borderSubtle}>
                  <FiTrendingUp size={14} color={T.statusOk} />
                  <Text fontSize="12px" color={T.textSecondary} flex={1}>
                    {d.metric.replace(/_/g, ' ')}
                  </Text>
                  <Text fontSize="12px" fontFamily="'Fira Code', monospace" color={T.statusOk}>
                    {Math.round(d.a * 100)}% &rarr; {Math.round(d.b * 100)}% (+{Math.round(d.delta * 100)}pp)
                  </Text>
                </HStack>
              ))}
            </Card>
          )}
        </>
      )}

      {/* Empty state */}
      {(!compRunA || !compRunB) && (
        <Card>
          <VStack py={10} spacing={3}>
            <FiGitMerge size={32} color={T.textMuted} />
            <Text fontSize="sm" color={T.textMuted} textAlign="center">
              Selectionnez deux runs RAGAS pour comparer leurs metriques
            </Text>
          </VStack>
        </Card>
      )}
    </VStack>
  )
}

// ══════════════════════════════════════════════════════════════════════
//  SHARED MICRO-COMPONENTS
// ══════════════════════════════════════════════════════════════════════

function DeltaBadge({ current, baseline }: { current: number; baseline: number }) {
  const delta = current - baseline
  const info = formatDelta(delta)
  return (
    <HStack spacing={1}>
      <info.Icon size={12} color={info.color} />
      <Text fontSize="11px" fontFamily="'Fira Code', monospace" fontWeight="600" color={info.color}>
        {info.text}
      </Text>
      <Text fontSize="10px" color={T.textMuted}>vs baseline</Text>
    </HStack>
  )
}

function InlineDelta({ delta }: { delta: number }) {
  const pp = Math.round(delta * 100)
  const color = pp > 0 ? T.statusOk : pp < 0 ? T.statusError : T.textMuted
  const text = pp === 0 ? '=' : pp > 0 ? `+${pp}` : `${pp}`
  return (
    <Text fontSize="12px" fontFamily="'Fira Code', monospace" fontWeight="600" color={color}>
      {text}
    </Text>
  )
}
