'use client'

import { useState } from 'react'
import {
  Box,
  HStack,
  VStack,
  Text,
  Badge,
  SimpleGrid,
  Table,
  Thead,
  Tbody,
  Tr,
  Th,
  Td,
  Tooltip,
} from '@chakra-ui/react'
import {
  FiTrendingUp,
  FiTrendingDown,
  FiMinus,
  FiActivity,
  FiClock,
  FiCheckCircle,
  FiAlertTriangle,
  FiXCircle,
} from 'react-icons/fi'
import { ScoreGauge } from '../benchmarks/ScoreGauge'
import { LaunchPanel } from '../benchmarks/LaunchPanel'

// ── Types ──────────────────────────────────────────────────────────────

interface OverviewTabProps {
  ragasReport: any | null
  t2t5Report: any | null
  robustnessReport: any | null
  recentRuns: Array<{
    type: string
    tag: string
    score: number
    delta: number | null
    timestamp: string
    filename: string
    synthesis_model?: string
  }>
  onLaunch: (benchType: string, profile: string, tag: string, description: string) => void
  isRunning: boolean
  runProgress: any | null
}

// ── Design tokens ──────────────────────────────────────────────────────

const tokens = {
  bgBase: '#0a0a1a',
  bgCard: '#12122a',
  bgElevated: '#1a1a35',
  borderSubtle: '#1e1e3a',
  textPrimary: '#f8fafc',
  textSecondary: '#94a3b8',
  textMuted: '#475569',
  accentBlue: '#5B7FFF',
  accentPurple: '#7C3AED',
  accentOrange: '#f97316',
}

// ── Helpers ────────────────────────────────────────────────────────────

function extractScore(report: any, path: string[]): number | null {
  if (!report) return null
  let obj = report
  for (const key of path) {
    if (obj == null || typeof obj !== 'object') return null
    obj = obj[key]
  }
  return typeof obj === 'number' ? obj : null
}

function formatTimestamp(ts: string | undefined | null): string {
  if (!ts) return '--'
  try {
    const d = new Date(ts)
    return d.toLocaleDateString('fr-FR', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
  } catch {
    return ts
  }
}

function formatDelta(delta: number | null): { text: string; color: string; Icon: React.ElementType } {
  if (delta == null) return { text: '--', color: tokens.textMuted, Icon: FiMinus }
  const sign = delta > 0 ? '+' : ''
  const pct = `${sign}${(delta * 100).toFixed(1)}%`
  if (delta > 0.01) return { text: pct, color: '#22c55e', Icon: FiTrendingUp }
  if (delta < -0.01) return { text: pct, color: '#ef4444', Icon: FiTrendingDown }
  return { text: pct, color: tokens.textMuted, Icon: FiMinus }
}

function benchTypeLabel(type: string): { label: string; color: string } {
  switch (type) {
    case 'ragas': return { label: 'RAGAS', color: tokens.accentBlue }
    case 't2t5': return { label: 'Contradictions', color: tokens.accentPurple }
    case 'robustness': return { label: 'Robustesse', color: tokens.accentOrange }
    default: return { label: type, color: tokens.textSecondary }
  }
}

type HealthLevel = 'green' | 'yellow' | 'red' | 'unknown'

function computeSystemHealth(scores: (number | null)[]): HealthLevel {
  const valid = scores.filter((s): s is number => s != null)
  if (valid.length === 0) return 'unknown'
  if (valid.some(s => s < 0.50)) return 'red'
  if (valid.some(s => s < 0.65)) return 'yellow'
  return 'green'
}

const healthConfig: Record<HealthLevel, { label: string; color: string; bg: string; Icon: React.ElementType }> = {
  green: { label: 'Sain', color: '#22c55e', bg: '#22c55e18', Icon: FiCheckCircle },
  yellow: { label: 'Attention', color: '#eab308', bg: '#eab30818', Icon: FiAlertTriangle },
  red: { label: 'Critique', color: '#ef4444', bg: '#ef444418', Icon: FiXCircle },
  unknown: { label: 'Pas de donnees', color: tokens.textMuted, bg: `${tokens.textMuted}18`, Icon: FiActivity },
}

// ── Score Card ─────────────────────────────────────────────────────────

function ScoreCard({
  title,
  mainScore,
  mainLabel,
  accent,
  secondaryLines,
  delta,
  timestamp,
  target,
}: {
  title: string
  mainScore: number | null
  mainLabel: string
  accent: string
  secondaryLines: { label: string; value: string }[]
  delta: number | null
  timestamp: string | undefined | null
  target?: number
}) {
  const deltaInfo = formatDelta(delta)

  return (
    <Box
      bg={tokens.bgCard}
      border="1px solid"
      borderColor={tokens.borderSubtle}
      rounded="xl"
      p={5}
      position="relative"
      overflow="hidden"
      _before={{
        content: '""',
        position: 'absolute',
        top: 0,
        left: 0,
        right: 0,
        height: '2px',
        bg: accent,
        opacity: 0.7,
      }}
    >
      <Text
        fontSize="xs"
        fontWeight="700"
        color={accent}
        textTransform="uppercase"
        letterSpacing="0.05em"
        mb={3}
      >
        {title}
      </Text>

      <HStack spacing={4} align="center" mb={3}>
        <Box flexShrink={0}>
          {mainScore != null ? (
            <ScoreGauge value={mainScore} label={mainLabel} color={accent} size={110} target={target} />
          ) : (
            <VStack spacing={1}>
              <Box
                w="110px"
                h="82px"
                display="flex"
                alignItems="center"
                justifyContent="center"
              >
                <Text
                  fontFamily="'Fira Code', monospace"
                  fontSize="2xl"
                  fontWeight="700"
                  color={tokens.textMuted}
                >
                  --
                </Text>
              </Box>
              <Text fontSize="xs" color={tokens.textSecondary}>{mainLabel}</Text>
            </VStack>
          )}
        </Box>

        <VStack align="start" spacing={1.5} flex={1} minW={0}>
          {secondaryLines.map((line, i) => (
            <HStack key={i} spacing={2} w="100%">
              <Text
                fontSize="11px"
                color={tokens.textMuted}
                whiteSpace="nowrap"
                minW="90px"
              >
                {line.label}
              </Text>
              <Text
                fontSize="12px"
                fontFamily="'Fira Code', monospace"
                fontWeight="600"
                color={tokens.textSecondary}
              >
                {line.value}
              </Text>
            </HStack>
          ))}

          <HStack spacing={1.5} mt={1}>
            <deltaInfo.Icon size={12} color={deltaInfo.color} />
            <Text
              fontSize="11px"
              fontFamily="'Fira Code', monospace"
              fontWeight="600"
              color={deltaInfo.color}
            >
              {deltaInfo.text}
            </Text>
            <Text fontSize="10px" color={tokens.textMuted}>vs baseline</Text>
          </HStack>
        </VStack>
      </HStack>

      <HStack spacing={1} mt={1}>
        <FiClock size={10} color={tokens.textMuted} />
        <Text fontSize="10px" color={tokens.textMuted}>
          {formatTimestamp(timestamp)}
        </Text>
      </HStack>
    </Box>
  )
}

// ── Health Pill ────────────────────────────────────────────────────────

function HealthPill({ level }: { level: HealthLevel }) {
  const cfg = healthConfig[level]
  return (
    <HStack
      spacing={2}
      bg={cfg.bg}
      border="1px solid"
      borderColor={`${cfg.color}30`}
      rounded="full"
      px={4}
      py={1.5}
    >
      <cfg.Icon size={14} color={cfg.color} />
      <Text fontSize="xs" fontWeight="700" color={cfg.color}>
        Systeme: {cfg.label}
      </Text>
    </HStack>
  )
}

// ── Recent Runs Table ──────────────────────────────────────────────────

function RecentRunsTable({ runs }: { runs: OverviewTabProps['recentRuns'] }) {
  if (!runs || runs.length === 0) {
    return (
      <Box
        bg={tokens.bgCard}
        border="1px solid"
        borderColor={tokens.borderSubtle}
        rounded="xl"
        p={5}
      >
        <Text fontSize="sm" fontWeight="700" color={tokens.textPrimary} mb={3}>
          Derniers runs
        </Text>
        <Text fontSize="xs" color={tokens.textMuted} textAlign="center" py={6}>
          Aucun run enregistre
        </Text>
      </Box>
    )
  }

  return (
    <Box
      bg={tokens.bgCard}
      border="1px solid"
      borderColor={tokens.borderSubtle}
      rounded="xl"
      p={5}
      overflowX="auto"
    >
      <Text fontSize="sm" fontWeight="700" color={tokens.textPrimary} mb={3}>
        Derniers runs
      </Text>
      <Table size="sm" variant="unstyled">
        <Thead>
          <Tr>
            <Th color={tokens.textMuted} fontSize="10px" textTransform="uppercase" borderBottom="1px solid" borderColor={tokens.borderSubtle} pb={2}>
              Type
            </Th>
            <Th color={tokens.textMuted} fontSize="10px" textTransform="uppercase" borderBottom="1px solid" borderColor={tokens.borderSubtle} pb={2}>
              Tag
            </Th>
            <Th color={tokens.textMuted} fontSize="10px" textTransform="uppercase" borderBottom="1px solid" borderColor={tokens.borderSubtle} pb={2} isNumeric>
              Score
            </Th>
            <Th color={tokens.textMuted} fontSize="10px" textTransform="uppercase" borderBottom="1px solid" borderColor={tokens.borderSubtle} pb={2} isNumeric>
              Delta
            </Th>
            <Th color={tokens.textMuted} fontSize="10px" textTransform="uppercase" borderBottom="1px solid" borderColor={tokens.borderSubtle} pb={2}>
              Modele
            </Th>
            <Th color={tokens.textMuted} fontSize="10px" textTransform="uppercase" borderBottom="1px solid" borderColor={tokens.borderSubtle} pb={2}>
              Date
            </Th>
          </Tr>
        </Thead>
        <Tbody>
          {runs.slice(0, 5).map((run, i) => {
            const bt = benchTypeLabel(run.type)
            const deltaInfo = formatDelta(run.delta)
            return (
              <Tr key={`${run.filename}-${i}`} _hover={{ bg: tokens.bgElevated }}>
                <Td borderBottom="1px solid" borderColor={tokens.borderSubtle} py={2.5}>
                  <Badge
                    fontSize="10px"
                    fontWeight="700"
                    bg={`${bt.color}18`}
                    color={bt.color}
                    border="1px solid"
                    borderColor={`${bt.color}30`}
                    px={2}
                    py={0.5}
                    rounded="md"
                  >
                    {bt.label}
                  </Badge>
                </Td>
                <Td borderBottom="1px solid" borderColor={tokens.borderSubtle} py={2.5}>
                  <Tooltip label={run.filename} fontSize="xs" bg={tokens.bgElevated} color={tokens.textPrimary}>
                    <Text
                      fontSize="xs"
                      fontFamily="'Fira Code', monospace"
                      color={tokens.textSecondary}
                      maxW="140px"
                      isTruncated
                    >
                      {run.tag || '--'}
                    </Text>
                  </Tooltip>
                </Td>
                <Td isNumeric borderBottom="1px solid" borderColor={tokens.borderSubtle} py={2.5}>
                  <Text
                    fontSize="xs"
                    fontFamily="'Fira Code', monospace"
                    fontWeight="700"
                    color={tokens.textPrimary}
                  >
                    {(run.score * 100).toFixed(1)}%
                  </Text>
                </Td>
                <Td isNumeric borderBottom="1px solid" borderColor={tokens.borderSubtle} py={2.5}>
                  <HStack spacing={1} justify="flex-end">
                    <deltaInfo.Icon size={11} color={deltaInfo.color} />
                    <Text
                      fontSize="11px"
                      fontFamily="'Fira Code', monospace"
                      fontWeight="600"
                      color={deltaInfo.color}
                    >
                      {deltaInfo.text}
                    </Text>
                  </HStack>
                </Td>
                <Td borderBottom="1px solid" borderColor={tokens.borderSubtle} py={2.5}>
                  <Text fontSize="10px" fontFamily="'Fira Code', monospace" color={tokens.textMuted}>
                    {run.synthesis_model ? run.synthesis_model.replace('claude-haiku-4-5-20251001', 'Haiku').replace('gpt-4o-mini', '4o-mini') : '-'}
                  </Text>
                </Td>
                <Td borderBottom="1px solid" borderColor={tokens.borderSubtle} py={2.5}>
                  <Text fontSize="11px" color={tokens.textMuted}>
                    {formatTimestamp(run.timestamp)}
                  </Text>
                </Td>
              </Tr>
            )
          })}
        </Tbody>
      </Table>
    </Box>
  )
}

// ── Main Component ─────────────────────────────────────────────────────

const BENCH_TYPES = [
  { key: 'ragas', label: 'RAGAS', color: tokens.accentBlue },
  { key: 't2t5', label: 'Contradictions', color: tokens.accentPurple },
  { key: 'robustness', label: 'Robustesse', color: tokens.accentOrange },
]

const PROFILES = [
  { key: 'default', label: 'Defaut (100q)' },
  { key: 'quick', label: 'Quick (25q)' },
  { key: 'full', label: 'Full (275q)' },
]

export function OverviewTab({
  ragasReport,
  t2t5Report,
  robustnessReport,
  recentRuns,
  onLaunch,
  isRunning,
  runProgress,
}: OverviewTabProps) {
  const [selectedProfile, setSelectedProfile] = useState('default')
  const [tag, setTag] = useState('')
  const [description, setDescription] = useState('')

  // ── Extract scores ──────────────────────────────────────────────────

  const ragasFaithfulness = extractScore(ragasReport, ['systems', 'osmosis', 'scores', 'faithfulness'])
  const ragasContextRelevance = extractScore(ragasReport, ['systems', 'osmosis', 'scores', 'context_relevance'])
  const ragasSampleCount = ragasReport?.systems?.osmosis?.sample_count
  const ragasDiagnostic = ragasReport?.systems?.osmosis?.diagnostic

  const t2BothSides = extractScore(t2t5Report, ['scores', 'both_sides_surfaced'])
  const t2TensionMentioned = extractScore(t2t5Report, ['scores', 'tension_mentioned'])
  const t2BalancedConclusion = extractScore(t2t5Report, ['scores', 'balanced_conclusion'])

  const robGlobal = extractScore(robustnessReport, ['scores', 'global_score'])
  const robParaphrase = extractScore(robustnessReport, ['scores', 'paraphrase_score'])
  const robNegation = extractScore(robustnessReport, ['scores', 'negation_score'])

  // ── Compute deltas vs baseline (from recentRuns) ────────────────────

  function latestDelta(type: string): number | null {
    const run = recentRuns?.find(r => r.type === type)
    return run?.delta ?? null
  }

  // ── System health ───────────────────────────────────────────────────

  const healthLevel = computeSystemHealth([ragasFaithfulness, t2BothSides, robGlobal])

  // ── Render ──────────────────────────────────────────────────────────

  return (
    <VStack spacing={5} align="stretch" w="100%">
      {/* Health pill + titre */}
      <HStack justify="space-between" align="center">
        <Text fontSize="md" fontWeight="700" color={tokens.textPrimary}>
          Vue d&apos;ensemble
        </Text>
        <HealthPill level={healthLevel} />
      </HStack>

      {/* Score Cards */}
      <SimpleGrid columns={{ base: 1, md: 3 }} spacing={4}>
        <ScoreCard
          title="RAGAS Fidelite"
          mainScore={ragasFaithfulness}
          mainLabel="Faithfulness"
          accent={tokens.accentBlue}
          target={0.80}
          delta={latestDelta('ragas')}
          timestamp={ragasReport?.timestamp}
          secondaryLines={[
            {
              label: 'Ctx relevance',
              value: ragasContextRelevance != null ? `${(ragasContextRelevance * 100).toFixed(1)}%` : '--',
            },
            {
              label: 'Questions',
              value: ragasSampleCount != null ? String(ragasSampleCount) : '--',
            },
            {
              label: 'Diagnostic',
              value: ragasDiagnostic?.level ?? '--',
            },
          ]}
        />

        <ScoreCard
          title="Contradictions"
          mainScore={t2BothSides}
          mainLabel="Both sides"
          accent={tokens.accentPurple}
          target={0.70}
          delta={latestDelta('t2t5')}
          timestamp={t2t5Report?.timestamp}
          secondaryLines={[
            {
              label: 'Tension',
              value: t2TensionMentioned != null ? `${(t2TensionMentioned * 100).toFixed(1)}%` : '--',
            },
            {
              label: 'Conclusion eq.',
              value: t2BalancedConclusion != null ? `${(t2BalancedConclusion * 100).toFixed(1)}%` : '--',
            },
          ]}
        />

        <ScoreCard
          title="Robustesse"
          mainScore={robGlobal}
          mainLabel="Global"
          accent={tokens.accentOrange}
          target={0.75}
          delta={latestDelta('robustness')}
          timestamp={robustnessReport?.timestamp}
          secondaryLines={[
            {
              label: 'Paraphrase',
              value: robParaphrase != null ? `${(robParaphrase * 100).toFixed(1)}%` : '--',
            },
            {
              label: 'Negation',
              value: robNegation != null ? `${(robNegation * 100).toFixed(1)}%` : '--',
            },
          ]}
        />
      </SimpleGrid>

      {/* Recent Runs */}
      <RecentRunsTable runs={recentRuns} />

      {/* Quick Launch */}
      <LaunchPanel
        profiles={PROFILES}
        selectedProfile={selectedProfile}
        onProfileChange={setSelectedProfile}
        tag={tag}
        onTagChange={setTag}
        description={description}
        onDescriptionChange={setDescription}
        onLaunch={(benchType) => onLaunch(benchType, selectedProfile, tag, description)}
        benchTypes={BENCH_TYPES}
        isRunning={isRunning}
        runProgress={runProgress}
        onLaunchAll={async () => {
          for (const bt of ['ragas', 't2t5', 'robustness']) {
            onLaunch(bt, selectedProfile, tag, description)
            // Small delay so each request is dispatched
            await new Promise(r => setTimeout(r, 500))
          }
        }}
      />
    </VStack>
  )
}
