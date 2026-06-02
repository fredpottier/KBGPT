'use client'

import { useEffect, useMemo, useState } from 'react'
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
  Spinner,
  Icon,
  Wrap,
  WrapItem,
} from '@chakra-ui/react'
import {
  FiActivity,
  FiCheckCircle,
  FiAlertTriangle,
  FiXCircle,
  FiHelpCircle,
  FiClock,
  FiInfo,
  FiZap,
  FiGitMerge,
} from 'react-icons/fi'
import { ScoreGauge } from './ScoreGauge'

// ── Design tokens (alignés sur RuntimeV6Tab / page.tsx) ─────────────────
const T = {
  bgCard: 'var(--bg-surface)',
  bgElevated: 'var(--bg-surface-alt)',
  borderSubtle: 'var(--border-default)',
  textPrimary: 'var(--fg-primary)',
  textSecondary: 'var(--fg-secondary)',
  textMuted: 'var(--fg-muted)',
  accentOsm: '#5B7FFF',
  accentRag: '#94a3b8',
  accentConflict: '#7C3AED',
  statusOk: '#22c55e',
  statusWarn: '#eab308',
  statusError: '#ef4444',
}

// Cible vision sur la précision des références (exact_id_recall — 0.75-0.80)
const EIR_TARGET = 0.75
// Cible honnêteté (abstention juste) — bon réflexe répondre/refuser
const ABST_TARGET = 0.80

// ── Type (miroir backend /api/benchmarks/a38) ──────────────────────────
interface A38Run {
  filename: string
  arm: string
  timestamp: string
  total_duration_s?: number | null
  exact_id_recall_mean?: number | null
  n_with_expected_ids?: number | null
  abstention_correct_rate?: number | null
  C1_mean?: number | null
  C3_lifecycle_mean?: number | null
  judge_failure_rate?: number | null
  latency_p50_s?: number | null
  latency_p95_s?: number | null
  n_total?: number | null
  n_run_ok?: number | null
  gates?: Record<string, any>
  conflict_exposure_rate?: number | null
}

// Conserve la signature historique pour ne pas casser l'appelant — les props
// V3 (ragas/t2t5/robustness) ne sont plus utilisées : ce widget lit le gold-set.
interface OverviewTabProps {
  [k: string]: any
}

// Libellés clairs des « gates » (objectifs cibles ADR) — sans le code GA3-x.
const GATE_LABELS: Record<string, string> = {
  'GA3-5_C1': 'Qualité globale ≥ 75%',
  'GA3-6_C3_lifecycle': 'Évolution dans le temps ≥ 50%',
  'GA3-7_latency': 'Temps de réponse sous les seuils',
  'GA3-9_conflict_exposure': 'Contradictions signalées',
}

// ── Helpers ────────────────────────────────────────────────────────────
function fmtTs(ts: string): string {
  const m = ts.match(/^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})/)
  if (m) return `${m[3]}/${m[2]} ${m[4]}:${m[5]}`
  try { return new Date(ts).toLocaleString('fr-FR', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) }
  catch { return ts }
}
function pct(v: number | null | undefined): string {
  return v == null ? '--' : `${Math.round(v * 100)}%`
}
function deltaColor(d: number): string {
  return d > 0.01 ? T.statusOk : d < -0.01 ? T.statusError : T.textMuted
}
function fmtDeltaPp(d: number | null): string {
  if (d == null) return '--'
  const pp = Math.round(d * 100)
  return pp > 0 ? `+${pp} pts` : pp < 0 ? `${pp} pts` : '='
}
function armLabel(arm: string): string {
  return arm === 'osmosis' ? 'OSMOSIS' : arm === 'classic_rag' ? 'RAG classique' : arm
}

// ── Santé système (calculée depuis les données, jamais figée) ───────────
type HealthLevel = 'green' | 'yellow' | 'red' | 'unknown'
function computeHealth(osm: A38Run | null): HealthLevel {
  if (!osm) return 'unknown'
  const eir = osm.exact_id_recall_mean
  const abst = osm.abstention_correct_rate
  if (eir == null && abst == null) return 'unknown'
  const e = eir ?? 0, a = abst ?? 0
  if (e >= EIR_TARGET && a >= ABST_TARGET) return 'green'
  if (e >= 0.5 && a >= 0.6) return 'yellow'
  return 'red'
}
const healthConfig: Record<HealthLevel, { label: string; color: string; Icon: React.ElementType }> = {
  green: { label: 'Sain', color: '#22c55e', Icon: FiCheckCircle },
  yellow: { label: 'À surveiller', color: '#eab308', Icon: FiAlertTriangle },
  red: { label: 'Critique', color: '#ef4444', Icon: FiXCircle },
  unknown: { label: 'Pas de données', color: T.textMuted, Icon: FiActivity },
}

// ── Petit composant infobulle « ? » ─────────────────────────────────────
function InfoLabel({ text, help }: { text: string; help: string }) {
  return (
    <HStack spacing={1}>
      <Text as="span">{text}</Text>
      <Tooltip label={help} fontSize="xs" maxW="280px" hasArrow placement="top">
        <Box as="span" display="inline-flex" cursor="help"><Icon as={FiInfo} boxSize="11px" color={T.textMuted} /></Box>
      </Tooltip>
    </HStack>
  )
}

function Card({ children, accent }: { children: React.ReactNode; accent?: string }) {
  return (
    <Box
      bg={T.bgCard} border="1px solid" borderColor={T.borderSubtle} rounded="xl" p={4}
      position="relative" overflow="hidden"
      _before={accent ? { content: '""', position: 'absolute', top: 0, left: 0, right: 0, height: '2px', bg: accent, opacity: 0.7 } : undefined}
    >
      {children}
    </Box>
  )
}

// ── Carte-pilier à jauge ─────────────────────────────────────────────────
function GaugePillar({ title, help, value, accent, target, foot, badge }: {
  title: string; help: string; value: number | null | undefined; accent: string
  target?: number; foot?: string; badge?: string
}) {
  return (
    <Card accent={accent}>
      <HStack justify="space-between" align="start" mb={1}>
        <Text fontSize="11px" fontWeight="700" color={accent} textTransform="uppercase" letterSpacing="0.04em">
          <InfoLabel text={title} help={help} />
        </Text>
        {badge && (
          <Badge fontSize="9px" bg={`${T.textMuted}1a`} color={T.textMuted} rounded="md" px={1.5}>{badge}</Badge>
        )}
      </HStack>
      <VStack spacing={1.5} py={1}>
        {value != null ? (
          <ScoreGauge value={value} label="" color={accent} size={92} target={target} />
        ) : (
          <Box h="70px" display="flex" alignItems="center"><Text fontSize="2xl" color={T.textMuted} fontFamily="'Fira Code', monospace">--</Text></Box>
        )}
        {foot && <Text fontSize="10px" color={T.textMuted} textAlign="center" lineHeight="1.3">{foot}</Text>}
      </VStack>
    </Card>
  )
}

// ── Carte-pilier à statistique (évite la jauge trompeuse, ex. taux conflits) ──
function StatPillar({ title, help, big, accent, foot, gate }: {
  title: string; help: string; big: string; accent: string; foot?: string; gate?: any
}) {
  const gp = gate?.passed
  const gc = gp === true ? T.statusOk : gp == null ? T.textMuted : T.statusError
  return (
    <Card accent={accent}>
      <Text fontSize="11px" fontWeight="700" color={accent} textTransform="uppercase" letterSpacing="0.04em" mb={1}>
        <InfoLabel text={title} help={help} />
      </Text>
      <VStack spacing={1.5} py={2} align="center" justify="center" minH="92px">
        <Text fontSize="34px" fontWeight="800" lineHeight="1" color={T.textPrimary} fontFamily="'Fira Code', monospace">{big}</Text>
        {foot && <Text fontSize="10px" color={T.textMuted} textAlign="center" lineHeight="1.3">{foot}</Text>}
        {gate != null && (
          <HStack spacing={1}>
            <Icon as={gp === true ? FiCheckCircle : gp == null ? FiHelpCircle : FiXCircle} boxSize="11px" color={gc} />
            <Text fontSize="10px" fontWeight="600" color={gc}>{gp === true ? 'objectif atteint' : gp == null ? 'non mesuré' : 'objectif non atteint'}</Text>
          </HStack>
        )}
      </VStack>
    </Card>
  )
}

// ── Ligne comparative OSMOSIS vs RAG (barres empilées, pleine largeur) ──
function CompareRow({ label, help, osmVal, ragVal }: {
  label: string; help: string; osmVal: number | null | undefined; ragVal: number | null | undefined
}) {
  const delta = osmVal != null && ragVal != null ? osmVal - ragVal : null
  const Bar = ({ v, color, name }: { v: number | null | undefined; color: string; name: string }) => (
    <HStack spacing={2} w="100%">
      <Text fontSize="10px" color={T.textMuted} minW="92px" flexShrink={0}>{name}</Text>
      <Box flex={1} bg={T.bgElevated} rounded="full" h="14px" overflow="hidden">
        <Box h="100%" w={`${Math.round((v ?? 0) * 100)}%`} bg={color} rounded="full" transition="width .4s" />
      </Box>
      <Text fontSize="11px" fontWeight="700" fontFamily="'Fira Code', monospace" color={T.textSecondary} minW="38px" textAlign="right">{pct(v)}</Text>
    </HStack>
  )
  return (
    <Box>
      <HStack justify="space-between" mb={1.5}>
        <Text fontSize="12px" fontWeight="700" color={T.textPrimary}><InfoLabel text={label} help={help} /></Text>
        {delta != null && (
          <Text fontSize="11px" fontWeight="700" fontFamily="'Fira Code', monospace" color={deltaColor(delta)}>{fmtDeltaPp(delta)}</Text>
        )}
      </HStack>
      <VStack spacing={1}>
        <Bar v={osmVal} color={T.accentOsm} name="OSMOSIS" />
        <Bar v={ragVal} color={T.accentRag} name="RAG classique" />
      </VStack>
    </Box>
  )
}

// ══════════════════════════════════════════════════════════════════════
export function OverviewTab(_props: OverviewTabProps) {
  const [runs, setRuns] = useState<A38Run[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const res = await fetch('/api/benchmarks/a38', { cache: 'no-store' })
        const data = await res.json()
        if (!cancelled) setRuns(data?.runs ?? [])
      } catch { if (!cancelled) setRuns([]) }
      finally { if (!cancelled) setLoading(false) }
    })()
    return () => { cancelled = true }
  }, [])

  const osm = useMemo(() => runs.find(r => r.arm === 'osmosis') ?? null, [runs])
  const rag = useMemo(() => runs.find(r => r.arm === 'classic_rag') ?? null, [runs])

  if (loading) {
    return <HStack py={10} justify="center"><Spinner color={T.accentOsm} /><Text color={T.textMuted}>Chargement…</Text></HStack>
  }
  if (!osm && !rag) {
    return (
      <Card>
        <VStack py={8} spacing={3}>
          <FiZap size={26} color={T.textMuted} />
          <Text fontWeight="700" color={T.textPrimary}>Aucun test gold-set trouvé</Text>
          <Text fontSize="13px" color={T.textSecondary} textAlign="center" maxW="520px">
            Lancez une évaluation :<br />
            <Text as="span" fontFamily="'Fira Code', monospace" fontSize="11px">docker exec knowbase-app python scripts/bench_a38_runtime_v6.py</Text>
          </Text>
        </VStack>
      </Card>
    )
  }

  const ref = osm ?? rag!
  const nTotal = ref.n_total ?? 50
  const health = computeHealth(osm)
  const hc = healthConfig[health]
  const gates = osm?.gates ?? {}
  const confRate = osm?.conflict_exposure_rate
  const lat = osm?.gates?.['GA3-7_latency']

  return (
    <VStack spacing={5} align="stretch" w="100%">
      {/* En-tête + santé (calculée) */}
      <HStack justify="space-between" align="center" flexWrap="wrap" rowGap={2}>
        <Text fontSize="md" fontWeight="800" color={T.textPrimary}>Vue d&apos;ensemble — Qualité OSMOSIS</Text>
        <HStack spacing={3}>
          <Text fontSize="10px" color={T.textMuted}>gold-set · {nTotal} questions</Text>
          <HStack spacing={1.5} bg={`${hc.color}14`} border="1px solid" borderColor={`${hc.color}33`} rounded="full" px={3} py={1}>
            <Icon as={hc.Icon} boxSize="13px" color={hc.color} />
            <Text fontSize="xs" fontWeight="700" color={hc.color}>Système : {hc.label}</Text>
          </HStack>
        </HStack>
      </HStack>

      {/* 4 piliers — responsive : 1 col (mobile) → 2×2 → 4×1 (très large) */}
      <SimpleGrid columns={{ base: 1, sm: 2, '2xl': 4 }} spacing={3}>
        <GaugePillar
          title="Précision des références"
          help="exact_id_recall — part des codes/identifiants attendus (transactions, n° de norme, dates) effectivement retrouvés dans la réponse. Mesure déterministe, sans IA."
          value={osm?.exact_id_recall_mean}
          accent={T.accentOsm}
          target={EIR_TARGET}
          foot={osm?.n_with_expected_ids != null ? `sur ${osm.n_with_expected_ids} questions à identifiants` : undefined}
        />
        <GaugePillar
          title="Honnêteté"
          help="abstention_correct — répond quand l'information est dans le corpus, s'abstient quand elle n'y est pas. Le bon réflexe répondre/refuser au bon moment."
          value={osm?.abstention_correct_rate}
          accent={T.statusOk}
          target={ABST_TARGET}
          foot="abstention juste"
        />
        <StatPillar
          title="Contradictions exposées"
          help="conflict_exposure — part des questions où des sources se contredisent (ex. FAA vs EASA) pour lesquelles OSMOSIS met le désaccord en avant au lieu de trancher arbitrairement."
          big={pct(confRate)}
          accent={T.accentConflict}
          foot="désaccords entre sources signalés"
          gate={gates['GA3-9_conflict_exposure']}
        />
        <GaugePillar
          title="Qualité jugée"
          help="C1 — qualité globale de la réponse estimée par un juge IA. Indicateur secondaire (bruité) : piloter au déterministe ci-contre, pas à ce score."
          value={osm?.C1_mean}
          accent={T.statusWarn}
          badge="juge IA"
          foot={osm?.C3_lifecycle_mean != null ? `évolution dans le temps : ${pct(osm.C3_lifecycle_mean)}` : undefined}
        />
      </SimpleGrid>

      {/* Objectifs (gates) + latence — badges qui s'enroulent (largeur contrainte) */}
      {(Object.keys(gates).length > 0 || lat) && (
        <Card>
          <Text fontSize="11px" fontWeight="700" color={T.textMuted} textTransform="uppercase" letterSpacing="0.04em" mb={2}>
            Objectifs cibles
          </Text>
          <Wrap spacing={2}>
            {Object.entries(gates).map(([k, g]: [string, any]) => {
              const gp = g?.passed
              const color = gp === true ? T.statusOk : gp == null ? T.textMuted : T.statusError
              const IconC = gp === true ? FiCheckCircle : gp == null ? FiHelpCircle : FiXCircle
              return (
                <WrapItem key={k}>
                  <Tooltip label={`${GATE_LABELS[k] ?? k} — ${gp === true ? 'atteint' : gp == null ? 'non mesuré' : 'non atteint'}`} fontSize="xs" hasArrow>
                    <HStack spacing={1.5} bg={`${color}14`} border="1px solid" borderColor={`${color}33`} rounded="md" px={2} py={1}>
                      <Icon as={IconC} boxSize="12px" color={color} />
                      <Text fontSize="10px" fontWeight="600" color={color}>{GATE_LABELS[k] ?? k}</Text>
                    </HStack>
                  </Tooltip>
                </WrapItem>
              )
            })}
            {(osm?.latency_p50_s != null) && (
              <WrapItem>
                <HStack spacing={1.5} bg={T.bgElevated} border="1px solid" borderColor={T.borderSubtle} rounded="md" px={2} py={1}>
                  <Icon as={FiClock} boxSize="12px" color={T.textMuted} />
                  <Text fontSize="10px" fontWeight="600" color={T.textSecondary}>
                    Latence p50 {osm.latency_p50_s!.toFixed(0)}s · p95 {osm.latency_p95_s != null ? `${osm.latency_p95_s.toFixed(0)}s` : '--'}
                  </Text>
                </HStack>
              </WrapItem>
            )}
          </Wrap>
        </Card>
      )}

      {/* OSMOSIS vs RAG classique — la preuve de valeur */}
      {rag && (
        <Card accent={T.accentOsm}>
          <HStack spacing={2} mb={3}>
            <FiGitMerge size={14} color={T.accentOsm} />
            <Text fontSize="13px" fontWeight="800" color={T.textPrimary}>OSMOSIS vs moteur de recherche classique</Text>
          </HStack>
          <VStack spacing={3.5} align="stretch">
            <CompareRow
              label="Précision des références"
              help="À architecture de réponse identique, seul le moteur de récupération change. Le KG d'OSMOSIS retrouve les bons identifiants là où un RAG par chunks échoue."
              osmVal={osm?.exact_id_recall_mean}
              ragVal={rag.exact_id_recall_mean}
            />
            <CompareRow
              label="Honnêteté (abstention juste)"
              help="Un RAG classique s'abstient souvent à tort (le chunk n'a pas le fait précis) ; OSMOSIS répond quand le KG contient le fait, et s'abstient seulement quand il est absent."
              osmVal={osm?.abstention_correct_rate}
              ragVal={rag.abstention_correct_rate}
            />
          </VStack>
        </Card>
      )}

      {/* Derniers runs */}
      <Card>
        <Text fontSize="13px" fontWeight="700" color={T.textPrimary} mb={2}>Derniers tests</Text>
        <Box overflowX="auto">
          <Table size="sm" variant="unstyled" minW="540px">
            <Thead>
              <Tr>
                {['Test', 'Précision réfs', 'Honnêteté', 'Qualité (IA)', 'Latence p50', 'Date'].map((h, i) => (
                  <Th key={h} color={T.textMuted} fontSize="9px" textTransform="uppercase" borderBottom="1px solid" borderColor={T.borderSubtle} pb={2} isNumeric={i > 0 && i < 5}>
                    {h}
                  </Th>
                ))}
              </Tr>
            </Thead>
            <Tbody>
              {runs.slice(0, 6).map((r, i) => (
                <Tr key={`${r.filename}-${i}`} _hover={{ bg: T.bgElevated }}>
                  <Td borderBottom="1px solid" borderColor={T.borderSubtle} py={2}>
                    <Badge fontSize="10px" fontWeight="700"
                      bg={`${r.arm === 'osmosis' ? T.accentOsm : T.accentRag}1a`}
                      color={r.arm === 'osmosis' ? T.accentOsm : T.accentRag}
                      rounded="md" px={2}>
                      {armLabel(r.arm)}
                    </Badge>
                  </Td>
                  <Td isNumeric borderBottom="1px solid" borderColor={T.borderSubtle} py={2}>
                    <Text fontSize="xs" fontFamily="'Fira Code', monospace" fontWeight="700" color={T.textPrimary}>{pct(r.exact_id_recall_mean)}</Text>
                  </Td>
                  <Td isNumeric borderBottom="1px solid" borderColor={T.borderSubtle} py={2}>
                    <Text fontSize="xs" fontFamily="'Fira Code', monospace" color={T.textSecondary}>{pct(r.abstention_correct_rate)}</Text>
                  </Td>
                  <Td isNumeric borderBottom="1px solid" borderColor={T.borderSubtle} py={2}>
                    <Text fontSize="xs" fontFamily="'Fira Code', monospace" color={T.textMuted}>{r.C1_mean != null ? r.C1_mean.toFixed(2) : '--'}</Text>
                  </Td>
                  <Td isNumeric borderBottom="1px solid" borderColor={T.borderSubtle} py={2}>
                    <Text fontSize="xs" fontFamily="'Fira Code', monospace" color={T.textMuted}>{r.latency_p50_s != null ? `${r.latency_p50_s.toFixed(0)}s` : '--'}</Text>
                  </Td>
                  <Td borderBottom="1px solid" borderColor={T.borderSubtle} py={2}>
                    <Text fontSize="11px" color={T.textMuted}>{fmtTs(r.timestamp)}</Text>
                  </Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        </Box>
      </Card>

      {/* Note méthodo (intemporelle) */}
      <HStack spacing={2} align="start" px={1}>
        <Box pt="2px"><FiInfo size={13} color={T.textMuted} /></Box>
        <Text fontSize="11px" color={T.textMuted} lineHeight="1.6">
          Indicateurs mesurés sur le gold-set (questions dont la bonne réponse est connue). Les deux mesures
          déterministes — précision des références et honnêteté — priment ; la « qualité jugée » par IA est
          indicative. Le détail par type de question est dans l&apos;onglet <b>Runtime v6</b>.
        </Text>
      </HStack>
    </VStack>
  )
}
