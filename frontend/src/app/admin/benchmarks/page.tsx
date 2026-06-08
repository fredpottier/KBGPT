'use client'

import { useEffect, useState, useMemo, useCallback } from 'react'
import {
  Box,
  HStack,
  VStack,
  Text,
  Badge,
  Table,
  Thead,
  Tbody,
  Tr,
  Th,
  Td,
  Progress,
  Collapse,
  SimpleGrid,
  Spinner,
} from '@chakra-ui/react'
import {
  FiActivity,
  FiBarChart2,
  FiAlertTriangle,
  FiShield,
  FiGitMerge,
  FiZap,
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
  RadarChart,
  RuntimeV6Tab,
} from '@/components/benchmarks'

// ── Design tokens ─────────────────────────────────────────────────────
// Tokens alignés sur les CSS variables canoniques du thème actif (preset-vars.css).
// Aucun fallback dark hardcodé : le thème light/dark gère lui-même.
const T = {
  bgBase: 'var(--bg-canvas)',
  bgCard: 'var(--bg-surface)',
  bgElevated: 'var(--bg-surface-alt)',
  borderSubtle: 'var(--border-default)',
  accentRagas: '#5B7FFF',
  accentContra: '#7C3AED',
  accentRobust: '#f97316',
  textPrimary: 'var(--fg-primary)',
  textSecondary: 'var(--fg-secondary)',
  textMuted: 'var(--fg-muted)',
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
  scores_rag?: Record<string, number> | null
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

type TabKey = 'runtime_v6' | 'overview'

// ── Tab definitions ───────────────────────────────────────────────────
// `group` distingue le bench décisionnel actuel (a38) des évaluateurs V3 legacy.

// Évaluateurs V3 legacy (RAGAS / Contradictions / Robustesse) retirés le 08/06/2026 :
// le bench décisionnel est le gold-set a38 (onglet Runtime v6). Code mort associé
// (state/fetch/panels) à balayer dans une passe dédiée.
const TABS: { key: TabKey; label: string; Icon: React.ElementType; accent: string; group: 'current' | 'archive' }[] = [
  { key: 'runtime_v6', label: 'Runtime v6', Icon: FiZap, accent: T.accentRagas, group: 'current' },
  { key: 'overview', label: 'Vue d\'ensemble', Icon: FiActivity, accent: T.accentRagas, group: 'current' },
]

const PROFILES = [
  { key: 'standard', label: 'Standard (100q)' },
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
  const [activeTab, setActiveTab] = useState<TabKey>('runtime_v6')

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

  // ── Comparison state (simplified) ────────────────────────────────────

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
      if (detail) setLatestRobustnessDetail({ ...detail, filename: latest.filename })
    }
  }, [])

  useEffect(() => {
    fetchAllLists()
  }, [fetchAllLists])

  // ── Progress polling (CH-30.14) ────────────────────────────────────
  // Poll les 3 endpoints en permanence pour détecter aussi les benchs lancés
  // hors-frontend (CLI, autre client, autre onglet). Auto-reconnect aux benchs
  // déjà en cours quand on charge la page. Détecte aussi les transitions
  // running → completed pour rafraîchir la liste des rapports.
  const [activeProgress, setActiveProgress] = useState<Record<string, RunProgress>>({})

  useEffect(() => {
    let cancelled = false
    const ALL_ENDPOINTS: Record<string, string> = {
      ragas: '/api/benchmarks/ragas/progress',
      t2t5: '/api/benchmarks/t2t5/progress',
      robustness: '/api/benchmarks/robustness/progress',
    }
    const isActive = (s: string | undefined): boolean =>
      s === 'running' || s === 'starting'
    let prevActive: Record<string, boolean> = {}

    async function pollOnce() {
      const next: Record<string, RunProgress> = {}
      const newActive: Record<string, boolean> = {}
      for (const [type, url] of Object.entries(ALL_ENDPOINTS)) {
        const p = await apiFetch<RunProgress & { status?: string }>(url)
        if (p) {
          next[type] = p
          newActive[type] = isActive((p as any).status)
        }
      }
      if (cancelled) return
      setActiveProgress(next)

      // Auto-reconnect si un bench est déjà en cours et qu'on n'avait pas runType set
      const firstActive = Object.entries(newActive).find(([_, a]) => a)?.[0]
      if (firstActive && !isRunning) {
        setIsRunning(true)
        setRunType(firstActive)
        setRunProgress(next[firstActive])
      } else if (isRunning && runType && !newActive[runType]) {
        // Le bench tracké explicitement vient de finir
        setIsRunning(false)
        setRunType(null)
        setRunProgress(null)
        fetchAllLists()
      } else if (isRunning && runType) {
        setRunProgress(next[runType])
      }

      // Refresh la liste des rapports dès qu'un bench passe de actif → fini
      const justFinished = Object.keys(prevActive).some(
        k => prevActive[k] && !newActive[k],
      )
      if (justFinished) {
        fetchAllLists()
      }
      prevActive = newActive
    }

    pollOnce()
    const interval = setInterval(pollOnce, 5000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [fetchAllLists, isRunning, runType])

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

    // fetch brut (et non apiFetch) pour conserver le détail HTTP en cas d'échec
    const resp = await fetch(`${API}${url}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ profile, tag: tag || undefined, description: description || undefined }),
    })
    if (!resp.ok) {
      const detail = await resp.text().catch(() => '')
      const msg = `Echec lancement ${benchType}: ${resp.status} ${detail}`
      console.error(msg)
      alert(msg)
      throw new Error(msg)
    }
  }, [])

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

  // Delta vs RAG pur : trouver le dernier run avec donnees RAG pour chaque benchmark
  const ragPurScores = useMemo(() => {
    // RAGAS : dernier run avec systems.baseline
    const ragasWithRag = [...ragasReports]
      .sort((a, b) => b.timestamp.localeCompare(a.timestamp))
      .find(r => r.systems?.baseline?.scores?.faithfulness != null)
    // T2/T5 : dernier run avec scores_rag
    const t2WithRag = [...t2t5Reports]
      .sort((a, b) => b.timestamp.localeCompare(a.timestamp))
      .find(r => r.scores_rag != null)
    return {
      ragasFaith: ragasWithRag?.systems?.baseline?.scores?.faithfulness ?? null,
      ragasCtxRel: ragasWithRag?.systems?.baseline?.scores?.context_relevance ?? null,
      t2BothSurfaced: t2WithRag?.scores_rag?.both_sides_surfaced ?? null,
    }
  }, [ragasReports, t2t5Reports])

  const recentRuns = useMemo(() => {
    const runs: Array<{ type: string; tag: string; score: number; delta: number | null; timestamp: string; filename: string; synthesis_model?: string }> = []

    // RAGAS : delta vs RAG pur faithfulness (si disponible)
    for (const r of ragasReports) {
      const s = r.systems?.osmosis?.scores?.faithfulness ?? 0
      const delta = ragPurScores.ragasFaith != null ? s - ragPurScores.ragasFaith : null
      runs.push({ type: 'ragas', tag: r.tag || '', score: s, delta, timestamp: r.timestamp, filename: r.filename, synthesis_model: (r as any).synthesis_model })
    }

    // T2/T5 : delta vs RAG pur both_sides_surfaced (si disponible)
    for (const r of t2t5Reports) {
      const s = r.scores?.both_sides_surfaced ?? 0
      const delta = ragPurScores.t2BothSurfaced != null ? s - ragPurScores.t2BothSurfaced : null
      runs.push({ type: 't2t5', tag: r.tag || '', score: s, delta, timestamp: r.timestamp, filename: r.filename, synthesis_model: (r as any).synthesis_model })
    }

    // Robustness : pas de RAG pur disponible, delta vs premier run
    const robSorted = [...robustnessReports].sort((a, b) => a.timestamp.localeCompare(b.timestamp))
    const baselineRobScore = robSorted[0]?.scores?.global_score ?? null
    for (const r of robustnessReports) {
      const s = r.scores?.global_score ?? 0
      const delta = baselineRobScore != null ? s - baselineRobScore : null
      runs.push({ type: 'robustness', tag: r.tag || '', score: s, delta, timestamp: r.timestamp, filename: r.filename, synthesis_model: (r as any).synthesis_model })
    }

    runs.sort((a, b) => b.timestamp.localeCompare(a.timestamp))
    return runs.slice(0, 5)
  }, [ragasReports, t2t5Reports, robustnessReports, ragPurScores])

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
        {TABS.map((tab, i) => {
          const isActive = activeTab === tab.key
          const accent = isActive ? (tab.group === 'current' ? T.accentRagas : T.textSecondary) : T.textMuted
          // Séparateur avant le premier onglet du groupe "archive"
          const showSep = tab.group === 'archive' && TABS[i - 1]?.group === 'current'
          return (
            <HStack key={tab.key} spacing={0} flexShrink={0}>
              {showSep && (
                <HStack spacing={1.5} px={3} borderLeft="1px solid" borderColor={T.borderSubtle} ml={2} h="20px" alignSelf="center">
                  <Text fontSize="9px" fontWeight="700" color={T.textMuted} textTransform="uppercase" letterSpacing="0.08em">
                    Archive V3
                  </Text>
                </HStack>
              )}
              <Box
                as="button"
                onClick={() => setActiveTab(tab.key)}
                px={5}
                py={3}
                borderBottom="2px solid"
                borderColor={isActive ? accent : 'transparent'}
                transition="all 0.2s"
                _hover={{ bg: T.bgElevated }}
                cursor="pointer"
                opacity={tab.group === 'archive' && !isActive ? 0.7 : 1}
              >
                <HStack spacing={2}>
                  <tab.Icon size={14} color={accent} />
                  <Text
                    fontSize="13px"
                    fontWeight={isActive ? '700' : '500'}
                    color={isActive ? T.textPrimary : T.textMuted}
                  >
                    {tab.label}
                  </Text>
                </HStack>
              </Box>
            </HStack>
          )
        })}
      </HStack>

      {/* CH-30.14 — Bandeau benchs actifs (détectés via polling permanent
          des 3 endpoints, peu importe d'où le bench a été lancé) */}
      {(() => {
        const active = Object.entries(activeProgress).filter(
          ([_, p]) => (p as any).status === 'running' || (p as any).status === 'starting',
        )
        if (active.length === 0) return null
        const labelMap: Record<string, { label: string; color: string }> = {
          ragas: { label: 'RAGAS', color: T.accentRagas },
          t2t5: { label: 'Contradictions (T2/T5)', color: T.accentContra },
          robustness: { label: 'Robustesse', color: T.accentRobust },
        }
        return (
          <Box mb={5} p={3} bg={T.bgCard} border="1px solid" borderColor={T.borderSubtle} rounded="lg">
            <HStack mb={2} spacing={2}>
              <Spinner size="xs" color={T.accentRagas} />
              <Text fontSize="13px" fontWeight="700" color={T.textPrimary}>
                {active.length} benchmark{active.length > 1 ? 's' : ''} en cours
              </Text>
            </HStack>
            <VStack spacing={2} align="stretch">
              {active.map(([type, p]) => {
                const cfg = labelMap[type] || { label: type, color: T.textMuted }
                const total = (p as any).total ?? 0
                const progress = (p as any).progress ?? 0
                const phase = (p as any).phase ?? ''
                const pct = total > 0 ? Math.round((progress / total) * 100) : 0
                return (
                  <Box key={type}>
                    <HStack justify="space-between" mb={1}>
                      <HStack spacing={2}>
                        <Badge fontSize="10px" bg={`${cfg.color}22`} color={cfg.color} px={1.5} rounded="sm">
                          {cfg.label}
                        </Badge>
                        <Text fontSize="11px" color={T.textMuted} fontFamily="'Fira Code', monospace">
                          {phase} · {progress}/{total}
                        </Text>
                      </HStack>
                      <Text fontSize="11px" fontWeight="700" color={cfg.color} fontFamily="'Fira Code', monospace">
                        {pct}%
                      </Text>
                    </HStack>
                    <Progress
                      value={pct}
                      size="xs"
                      rounded="full"
                      bg={T.borderSubtle}
                      sx={{ '& > div': { background: cfg.color } }}
                    />
                    {(p as any).current_question && (
                      <Text fontSize="10px" color={T.textMuted} mt={1} noOfLines={1}>
                        {(p as any).current_question}
                      </Text>
                    )}
                  </Box>
                )
              })}
            </VStack>
          </Box>
        )
      })()}

      {/* Tab content */}
      {activeTab === 'runtime_v6' && <RuntimeV6Tab />}

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

      {/* Onglets V3 legacy (ragas / contradictions / robustness) retirés — cf. TABS. */}

      {/* Onglet Comparaison supprime — deltas vs RAG pur dans chaque onglet */}
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
  const [profile, setProfile] = useState('standard')
  const [tag, setTag] = useState('')
  const [desc, setDesc] = useState('')
  const [expandedQ, setExpandedQ] = useState<number | null>(null)

  const sorted = useMemo(() =>
    [...reports].sort((a, b) => b.timestamp.localeCompare(a.timestamp)),
    [reports],
  )

  // RAG pur : trouver le dernier run qui contient systems.baseline (RAG pur)
  const ragPurRef = useMemo(() => {
    return [...reports]
      .sort((a, b) => b.timestamp.localeCompare(a.timestamp))
      .find(r => r.systems?.baseline?.scores?.faithfulness != null) ?? null
  }, [reports])

  const latest = sorted[0] ?? null
  const detail = latestDetail ?? latest
  const osm = detail?.systems?.osmosis
  const faithChunks = osm?.scores?.faithfulness ?? 0
  const faithTotal = osm?.scores?.faithfulness_total ?? null
  // Afficher faith_total si disponible (mesure correcte incluant le KG), sinon faith_chunks
  const faith = faithTotal ?? faithChunks
  const ctxRel = osm?.scores?.context_relevance ?? 0
  const diag = osm?.diagnostic

  // Delta vs RAG pur (au lieu du premier run historique)
  const baseFaith = ragPurRef?.systems?.baseline?.scores?.faithfulness ?? null
  const baseCtxRel = ragPurRef?.systems?.baseline?.scores?.context_relevance ?? null

  // Diagnostic badge config
  const diagLabel = diag?.level ?? 'Inconnu'
  const diagColor = diag?.color ?? T.textMuted

  const worstSamples = osm?.worst_samples ?? []

  return (
    <VStack spacing={6} align="stretch">
      {/* Gauges row */}
      <HStack spacing={6} align="start" flexWrap="wrap">
        <Card accent={T.accentContra} flex={1} minW="280px">
          <HStack spacing={6} align="center">
            <ScoreGauge value={ctxRel} label="Context Relevance" color={T.accentContra} size={130} target={0.80} />
            <VStack align="start" spacing={2} flex={1}>
              <Text fontSize="xs" fontWeight="700" color={T.accentContra} textTransform="uppercase">
                Pertinence du contexte
              </Text>
              {baseCtxRel != null && (
                <DeltaBadge current={ctxRel} baseline={baseCtxRel} />
              )}
              <Text fontSize="11px" color={T.textMuted}>
                {osm?.sample_count ?? '--'} questions evaluees
              </Text>
            </VStack>
          </HStack>
        </Card>

        <Card accent={T.accentRagas} flex={1} minW="280px">
          <HStack spacing={6} align="center">
            <ScoreGauge value={faith} label={faithTotal != null ? "Faith (total)" : "Faithfulness"} color={T.accentRagas} size={130} target={0.85} />
            <VStack align="start" spacing={2} flex={1}>
              <Text fontSize="xs" fontWeight="700" color={T.accentRagas} textTransform="uppercase">
                {faithTotal != null ? "Fidelite totale (chunks + KG)" : "Fidelite des reponses"}
              </Text>
              {baseFaith != null && (
                <DeltaBadge current={faith} baseline={baseFaith} />
              )}
              {faithTotal != null && (
                <Text fontSize="10px" color={T.textMuted}>
                  chunks seuls : {Math.round(faithChunks * 100)}%
                </Text>
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
                  const isBase = row === ragPurRef
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

const CONTRA_T2_METRICS = [
  { key: 'both_sides_surfaced', label: 'Deux cotes surfaces' },
  { key: 'tension_mentioned', label: 'Tension mentionnee' },
  { key: 'both_sources_cited', label: 'Sources citees' },
] as const

const CONTRA_T5_METRICS = [
  { key: 'chain_coverage', label: 'Couverture chaines' },
  { key: 'multi_doc_cited', label: 'Multi-doc cite' },
  { key: 'proactive_detection', label: 'Detection proactive' },
] as const

// Sub-métriques candidates pour chaque catégorie T5 (toutes ne sont pas pertinentes
// selon la catégorie — on filtre dynamiquement en regardant si la key existe dans scores).
const CONTRA_CAT_SUB_METRICS = ['chain_coverage', 'multi_doc_cited', 'proactive_detection'] as const

/** Format un slug `evolution_chronological` ou `cross_doc_chain` en label affichable. */
function _humanizeCategoryKey(key: string): string {
  if (!key) return ''
  const s = key.replace(/_/g, ' ').toLowerCase().trim()
  // Capitalize first letter only
  return s.charAt(0).toUpperCase() + s.slice(1)
}

/**
 * Extrait dynamiquement les catégories T5 présentes dans le rapport.
 * Cherche les keys de la forme `t5_<category>_count` (avec count > 0).
 * Retourne triées par count décroissant.
 */
function extractT5Categories(scores: Record<string, any> | null | undefined): { key: string; label: string; count: number }[] {
  if (!scores) return []
  const seen: { key: string; label: string; count: number }[] = []
  for (const k of Object.keys(scores)) {
    // Pattern: t5_<cat>_count — exclure les sub-métriques (`_chain_coverage`, `_multi_doc_cited`, `_proactive_detection`)
    const m = k.match(/^t5_(.+)_count$/)
    if (!m) continue
    const cat = m[1]
    // Exclure les keys qui ressemblent à des sub-métriques
    if (/_(chain_coverage|multi_doc_cited|proactive_detection)$/.test(cat)) continue
    const count = scores[k]
    if (typeof count !== 'number' || count <= 0) continue
    seen.push({ key: cat, label: _humanizeCategoryKey(cat), count })
  }
  seen.sort((a, b) => b.count - a.count)
  return seen
}

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
  const [profile, setProfile] = useState('standard')
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
  const ragScores = latest?.scores_rag ?? null

  // CH-30.13 — métriques applicables : exclure proactive_detection si aucune
  // question proactive_contradiction n'a été évaluée (count=0) — sinon le 0%
  // tire la moyenne globale vers le bas artificiellement.
  const proactiveCount = (scores.proactive_count as number | undefined) ?? 0
  const includeProactive = proactiveCount > 0

  const applicableT5Metrics = useMemo(
    () => CONTRA_T5_METRICS.filter(m => m.key !== 'proactive_detection' || includeProactive),
    [includeProactive],
  )
  const applicableMetrics = useMemo(
    () => [...CONTRA_T2_METRICS, ...applicableT5Metrics],
    [applicableT5Metrics],
  )

  // Radar data: combine T2 + T5 applicable metrics
  const radarData = useMemo(() => {
    return applicableMetrics.map(m => ({
      label: m.label,
      value: scores[m.key] ?? 0,
    }))
  }, [scores, applicableMetrics])

  // Score global T2/T5 — moyenne des métriques applicables uniquement
  const allMetricValues = applicableMetrics.map(m => scores[m.key] ?? 0)
  const globalScore = allMetricValues.length > 0 ? allMetricValues.reduce((a, b) => a + b, 0) / allMetricValues.length : 0
  const baseAllValues = applicableMetrics.map(m => baseScores[m.key] ?? 0)
  const baseGlobal = baseAllValues.length > 0 ? baseAllValues.reduce((a, b) => a + b, 0) / baseAllValues.length : 0

  // RAG global score (mêmes métriques applicables pour comparaison cohérente)
  const ragAllValues = ragScores ? applicableMetrics.map(m => ragScores[m.key] ?? 0) : []
  const ragGlobal = ragAllValues.length > 0 ? ragAllValues.reduce((a, b) => a + b, 0) / ragAllValues.length : null

  return (
    <VStack spacing={6} align="stretch">
      {/* Header: global score + info */}
      <HStack spacing={6} align="center" flexWrap="wrap">
        <ScoreGauge value={globalScore} label="Score global" color={T.accentContra} size={110} target={0.80} />
        <VStack align="start" spacing={1}>
          <Text fontSize="sm" fontWeight="700" color={T.textPrimary}>
            Contradictions — {latest?.tag || 'Dernier run'}
          </Text>
          <Text fontSize="xs" color={T.textMuted}>
            {scores.total_evaluated ?? (((scores.t2_count ?? 0) + (scores.t5_count ?? 0)) || '--')} questions
            {latest?.duration_s ? ` — ${Math.round(latest.duration_s)}s` : ''}
          </Text>
          {(ragGlobal != null || baseGlobal > 0) && (
            <DeltaBadge current={globalScore} baseline={ragGlobal ?? baseGlobal} />
          )}
        </VStack>
      </HStack>

      {/* OSMOSIS vs RAG comparison banner */}
      {ragScores && ragGlobal != null && (
        <Card accent="#22c55e">
          <Text fontSize="xs" fontWeight="700" color="#22c55e" textTransform="uppercase" mb={3}>
            OSMOSIS vs RAG pur
          </Text>
          <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
            {applicableMetrics.map(m => {
              const osmVal = scores[m.key] ?? 0
              const ragVal = ragScores[m.key] ?? 0
              const diff = Math.round((osmVal - ragVal) * 100)
              return (
                <HStack key={m.key} justify="space-between" px={2} py={1}
                  borderRadius="md" bg={diff > 0 ? 'rgba(34,197,94,0.06)' : diff < 0 ? 'rgba(239,68,68,0.06)' : 'transparent'}>
                  <Text fontSize="12px" color={T.textSecondary} minW="140px">{m.label}</Text>
                  <HStack spacing={3}>
                    <Text fontSize="12px" fontWeight="600" color={T.accentContra}>
                      {(osmVal * 100).toFixed(0)}%
                    </Text>
                    <Text fontSize="10px" color={T.textMuted}>vs</Text>
                    <Text fontSize="12px" color={T.textMuted}>
                      {(ragVal * 100).toFixed(0)}%
                    </Text>
                    <Text fontSize="12px" fontWeight="700"
                      color={diff > 0 ? '#22c55e' : diff < 0 ? '#ef4444' : T.textMuted}>
                      {diff > 0 ? '+' : ''}{diff}pp
                    </Text>
                  </HStack>
                </HStack>
              )
            })}
            <HStack justify="space-between" px={2} py={2} borderTop="1px solid" borderColor={T.borderSubtle}>
              <Text fontSize="12px" fontWeight="700" color={T.textPrimary}>Score global</Text>
              <HStack spacing={3}>
                <Text fontSize="13px" fontWeight="700" color={T.accentContra}>
                  {(globalScore * 100).toFixed(0)}%
                </Text>
                <Text fontSize="10px" color={T.textMuted}>vs</Text>
                <Text fontSize="13px" fontWeight="600" color={T.textMuted}>
                  {(ragGlobal * 100).toFixed(0)}%
                </Text>
                <Text fontSize="13px" fontWeight="700"
                  color={globalScore > ragGlobal ? '#22c55e' : '#ef4444'}>
                  {globalScore > ragGlobal ? '+' : ''}{Math.round((globalScore - ragGlobal) * 100)}pp
                </Text>
              </HStack>
            </HStack>
          </SimpleGrid>
        </Card>
      )}

      {/* Radar + Metric bars row */}
      <HStack spacing={6} align="start" flexWrap={{ base: 'wrap', lg: 'nowrap' }}>
        {/* Left: Radar */}
        <Card flexShrink={0}>
          <Text fontSize="sm" fontWeight="700" color={T.textPrimary} mb={3}>
            Radar T2/T5
          </Text>
          <RadarChart data={radarData} size={260} color={T.accentContra} />
        </Card>

        {/* Right: Metric bars */}
        <VStack spacing={4} align="stretch" flex={1} minW="300px">
          <Card accent={T.accentContra}>
            <Text fontSize="xs" fontWeight="700" color={T.accentContra} textTransform="uppercase" mb={3}>
              T2 — Detection de contradictions
            </Text>
            {CONTRA_T2_METRICS.map(m => {
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

          <Card accent={T.accentContra}>
            <Text fontSize="xs" fontWeight="700" color={T.accentContra} textTransform="uppercase" mb={3}>
              T5 — Chaines documentaires
            </Text>
            {CONTRA_T5_METRICS.map(m => {
              const isProactive = m.key === 'proactive_detection'
              const naForProactive = isProactive && !includeProactive
              const val = scores[m.key] ?? 0
              const baseVal = baseScores[m.key]
              const delta = baseVal != null ? Math.round((val - baseVal) * 100) : null
              return (
                <MetricBar
                  key={m.key}
                  label={naForProactive ? `${m.label} (N/A — pas de question proactive)` : m.label}
                  value={naForProactive ? null : val}
                  delta={naForProactive ? null : (delta !== 0 ? delta : null)}
                />
              )
            })}
          </Card>
        </VStack>
      </HStack>

      {/* Category breakdown with sub-metrics — domain-agnostic, lit dynamiquement
           les catégories T5 présentes dans le report (ex: aero V2 a 28 catégories
           comme `evolution_chronological`, SAP avait 3 canoniques). */}
      {(() => {
        const dynamicCats = extractT5Categories(scores)
        if (dynamicCats.length === 0) return null
        return (
          <Card>
            <HStack justify="space-between" align="baseline" mb={4}>
              <Text fontSize="sm" fontWeight="700" color={T.textPrimary}>
                Par catégorie (T5)
              </Text>
              <Text fontSize="11px" color={T.textMuted}>
                {dynamicCats.length} catégorie{dynamicCats.length > 1 ? 's' : ''} · {dynamicCats.reduce((a, c) => a + c.count, 0)} questions
              </Text>
            </HStack>
            {dynamicCats.map(cat => {
              // Pour chaque catégorie, ne montrer que les sub-métriques qui ont une key
              // non-undefined dans le report (filtre les métriques N/A pour cette catégorie).
              const presentSubs = CONTRA_CAT_SUB_METRICS.filter(sub => {
                const v = scores[`t5_${cat.key}_${sub}`]
                return typeof v === 'number'
              })
              if (presentSubs.length === 0) return null

              return (
                <Box key={cat.key} mb={4}>
                  <HStack justify="space-between" align="baseline" mb={2}>
                    <Text fontSize="12px" fontWeight="700" color={T.textSecondary}>
                      {cat.label}
                    </Text>
                    <Text fontSize="10px" color={T.textMuted} fontFamily="'Fira Code', monospace">
                      n={cat.count}
                    </Text>
                  </HStack>
                  {presentSubs.map(sub => {
                    const scoreKey = `t5_${cat.key}_${sub}`
                    const val = scores[scoreKey] ?? 0
                    const baseVal = baseScores[scoreKey]
                    const delta = baseVal != null && typeof baseVal === 'number'
                      ? Math.round((val - baseVal) * 100)
                      : null
                    return (
                      <MetricBar
                        key={scoreKey}
                        label={sub.replace(/_/g, ' ')}
                        value={val}
                        delta={delta !== 0 ? delta : null}
                      />
                    )
                  })}
                </Box>
              )
            })}
          </Card>
        )
      })()}

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

function ComparisonTab() {
  return (
    <VStack spacing={6} align="stretch">
      <Card>
        <VStack py={10} spacing={4}>
          <FiGitMerge size={32} color={T.textMuted} />
          <Text fontSize="sm" fontWeight="700" color={T.textPrimary}>
            Comparaison integree
          </Text>
          <Text fontSize="13px" color={T.textSecondary} textAlign="center" maxW="500px" lineHeight="1.7">
            La comparaison detaillee est disponible directement dans chaque onglet
            (RAGAS, Contradictions, Robustesse) via les deltas vs RAG pur dans les
            tableaux historiques.
          </Text>
          <Text fontSize="11px" color={T.textMuted} textAlign="center" maxW="450px">
            Chaque tableau historique affiche automatiquement les deltas par rapport au premier run (baseline).
            Les regressions et ameliorations sont visibles en un coup d&apos;oeil.
          </Text>
        </VStack>
      </Card>
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
      <Text fontSize="10px" color={T.textMuted}>vs RAG pur</Text>
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
