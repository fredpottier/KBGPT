'use client'

import { useEffect, useMemo, useState } from 'react'
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
  Tooltip,
  Spinner,
  Icon,
} from '@chakra-ui/react'
import {
  FiZap,
  FiClock,
  FiCheckCircle,
  FiXCircle,
  FiHelpCircle,
  FiAward,
  FiInfo,
} from 'react-icons/fi'
import { ScoreGauge } from './ScoreGauge'

// ── Design tokens (alignés sur page.tsx) ───────────────────────────────
const T = {
  bgCard: 'var(--bg-surface)',
  bgElevated: 'var(--bg-surface-alt)',
  borderSubtle: 'var(--border-default)',
  textPrimary: 'var(--fg-primary)',
  textSecondary: 'var(--fg-secondary)',
  textMuted: 'var(--fg-muted)',
  accentOsm: '#5B7FFF',
  accentRag: '#94a3b8',
  statusOk: '#22c55e',
  statusWarn: '#eab308',
  statusError: '#ef4444',
}

// Cible vision sur la précision des références (exact_id_recall — 0.75-0.80)
const EIR_TARGET = 0.75

// ── Types (miroir du backend /api/benchmarks/a38) ──────────────────────
interface PerTypeStat { n: number; mean: number; n_judge_failed?: number }
interface A38Run {
  filename: string
  arm: string
  timestamp: string
  config?: Record<string, any>
  total_duration_s?: number | null
  exact_id_recall_mean?: number | null
  n_with_expected_ids?: number | null
  abstention_correct_rate?: number | null
  exact_id_recall_per_type?: Record<string, PerTypeStat>
  abstention_rate_per_type?: Record<string, { n: number; rate: number }>
  C1_mean?: number | null
  C3_lifecycle_mean?: number | null
  per_type?: Record<string, PerTypeStat>
  judge_failure_rate?: number | null
  latency_p50_s?: number | null
  latency_p95_s?: number | null
  n_total?: number | null
  n_run_ok?: number | null
  gates?: Record<string, any>
  conflict_exposure_rate?: number | null
}

// ── Traductions « jargon → langage clair » ─────────────────────────────
// Chaque type de question expliqué pour un lecteur non technique.
const TYPE_INFO: Record<string, { label: string; help: string }> = {
  factual: { label: 'Factuelles', help: 'Une information précise et unique (un code, une valeur, un nom).' },
  list: { label: 'Listes', help: 'Énumérer plusieurs éléments (toutes les options, tous les rôles…).' },
  lifecycle: { label: 'Évolution dans le temps', help: 'Comment une solution a changé d’une version à l’autre.' },
  multi_hop: { label: 'Raisonnement multi-étapes', help: 'Croiser plusieurs informations pour bâtir la réponse.' },
  comparison: { label: 'Comparaisons', help: 'Comparer deux options, solutions ou versions.' },
  contextual: { label: 'Contextuelles', help: 'La réponse dépend du contexte précisé dans la question.' },
  false_premise: { label: 'Questions piège', help: 'La question contient une affirmation fausse — il faut la détecter, pas y répondre.' },
  unanswerable: { label: 'Hors périmètre', help: 'La réponse n’est pas dans les documents — il faut le reconnaître honnêtement.' },
}
const TYPE_ORDER = ['factual', 'list', 'lifecycle', 'multi_hop', 'comparison', 'contextual', 'false_premise', 'unanswerable']
// Familles : questions avec réponse attendue vs questions où il faut refuser/signaler.
const ANSWER_TYPES = ['factual', 'list', 'lifecycle', 'multi_hop', 'comparison', 'contextual']
const NOANSWER_TYPES = ['false_premise', 'unanswerable']
function typeLabel(t: string): string { return TYPE_INFO[t]?.label ?? t }
function typeHelp(t: string): string { return TYPE_INFO[t]?.help ?? '' }
function sortTypes(types: string[]): string[] {
  return [...types].sort((a, b) => {
    const ia = TYPE_ORDER.indexOf(a), ib = TYPE_ORDER.indexOf(b)
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib)
  })
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
function scoreColor(v: number): string {
  return v >= 0.7 ? T.statusOk : v >= 0.5 ? T.statusWarn : T.statusError
}
function deltaColor(d: number): string {
  return d > 0.01 ? T.statusOk : d < -0.01 ? T.statusError : T.textMuted
}
function fmtDeltaPp(d: number | null): string {
  if (d == null) return '--'
  const pp = Math.round(d * 100)
  return pp > 0 ? `+${pp} pts` : pp < 0 ? `${pp} pts` : '='
}

// Taux d'abstention moyen (pondéré par le nb de questions) sur un ensemble de types.
function weightedAbstention(run: A38Run | null, types: string[]): { rate: number | null; n: number } {
  if (!run) return { rate: null, n: 0 }
  let num = 0, den = 0
  for (const t of types) {
    const a = run.abstention_rate_per_type?.[t]
    if (a) { num += a.rate * a.n; den += a.n }
  }
  return { rate: den > 0 ? num / den : null, n: den }
}

// ── Petit libellé + infobulle « ? » ────────────────────────────────────
function InfoLabel({ text, help, ...rest }: { text: string; help: string; [k: string]: any }) {
  return (
    <HStack spacing={1} {...rest}>
      <Text as="span">{text}</Text>
      <Tooltip label={help} fontSize="xs" maxW="280px" hasArrow placement="top">
        <Box as="span" display="inline-flex" cursor="help"><Icon as={FiInfo} boxSize="11px" color={T.textMuted} /></Box>
      </Tooltip>
    </HStack>
  )
}

// ── Card wrapper ───────────────────────────────────────────────────────
function Card({ children, accent, ...props }: { children: React.ReactNode; accent?: string; [k: string]: any }) {
  return (
    <Box
      bg={T.bgCard} border="1px solid" borderColor={T.borderSubtle} rounded="xl" p={5}
      position="relative" overflow="hidden"
      _before={accent ? { content: '""', position: 'absolute', top: 0, left: 0, right: 0, height: '2px', bg: accent, opacity: 0.7 } : undefined}
      {...props}
    >
      {children}
    </Box>
  )
}

// ── Gate badge (objectif cible) ────────────────────────────────────────
function GateBadge({ gateKey, gate }: { gateKey: string; gate: any }) {
  const passed = gate?.passed
  const IconC = passed === true ? FiCheckCircle : passed == null ? FiHelpCircle : FiXCircle
  const color = passed === true ? T.statusOk : passed == null ? T.textMuted : T.statusError
  const label = GATE_LABELS[gateKey] ?? gateKey
  return (
    <Tooltip label={`${label} — ${passed === true ? 'atteint' : passed == null ? 'non mesuré' : 'non atteint'}`} fontSize="xs" hasArrow>
      <HStack spacing={1.5} bg={`${color}14`} border="1px solid" borderColor={`${color}33`} rounded="md" px={2} py={1}>
        <IconC size={12} color={color} />
        <Text fontSize="10px" fontWeight="600" color={color}>{label}</Text>
      </HStack>
    </Tooltip>
  )
}

// ══════════════════════════════════════════════════════════════════════
export function RuntimeV6Tab() {
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
          <FiZap size={28} color={T.textMuted} />
          <Text fontWeight="700" color={T.textPrimary}>Aucun test trouvé</Text>
          <Text fontSize="13px" color={T.textSecondary} textAlign="center" maxW="520px">
            Lance une évaluation en ligne de commande :<br />
            <Text as="span" fontFamily="'Fira Code', monospace" fontSize="11px">docker exec knowbase-app python scripts/bench_a38_runtime_v6.py</Text>
          </Text>
        </VStack>
      </Card>
    )
  }

  const ref = osm ?? rag!
  const nTotal = ref.n_total ?? 50

  return (
    <VStack spacing={6} align="stretch">
      {/* ── Bandeau explicatif du test ── */}
      <Box bg={T.bgElevated} border="1px solid" borderColor={T.borderSubtle} rounded="lg" px={4} py={3}>
        <HStack spacing={2} align="start">
          <Box pt="2px"><FiInfo size={15} color={T.accentOsm} /></Box>
          <Text fontSize="13px" color={T.textSecondary} lineHeight="1.6">
            <Text as="span" fontWeight="700" color={T.textPrimary}>Comment lire cette page.</Text>{' '}
            On pose à OSMOSIS une batterie de <b>{nTotal} questions de test</b> dont on connaît déjà la bonne réponse,
            puis on mesure la qualité de ses réponses. Chaque indicateur ci-dessous répond à une question simple —
            survolez le <Icon as={FiInfo} boxSize="11px" mb="-1px" color={T.textMuted} /> pour le détail. La barre la plus
            importante est la comparaison avec un moteur de recherche classique.
          </Text>
        </HStack>
      </Box>

      {/* ── Indicateurs clés (langage clair) ── */}
      <Card accent={T.accentOsm}>
        <HStack justify="space-between" align="baseline" mb={4}>
          <HStack spacing={2}>
            <FiZap size={16} color={T.accentOsm} />
            <Text fontSize="sm" fontWeight="800" color={T.textPrimary}>OSMOSIS — qualité des réponses</Text>
          </HStack>
          <HStack spacing={1}><FiClock size={11} color={T.textMuted} /><Text fontSize="11px" color={T.textMuted}>testé le {fmtTs(ref.timestamp)}</Text></HStack>
        </HStack>

        <HStack spacing={8} align="start" flexWrap="wrap">
          <VStack spacing={1} maxW="180px">
            <ScoreGauge value={ref.exact_id_recall_mean ?? 0} label="" color={T.accentOsm} size={140} target={EIR_TARGET} />
            <Text fontSize="13px" fontWeight="700" color={T.textPrimary} textAlign="center">Précision des références</Text>
            <Text fontSize="11px" color={T.textMuted} textAlign="center">
              Donne-t-il les bons codes, transactions et identifiants ? <b>Cible {Math.round(EIR_TARGET * 100)}%.</b>
            </Text>
            <Text fontSize="9px" color={T.textMuted} mt={1}>(mesure exacte, sans IA)</Text>
          </VStack>

          <VStack spacing={1} maxW="180px">
            <ScoreGauge value={ref.abstention_correct_rate ?? 0} label="" color="#7C3AED" size={140} target={0.9} />
            <Text fontSize="13px" fontWeight="700" color={T.textPrimary} textAlign="center">Honnêteté</Text>
            <Text fontSize="11px" color={T.textMuted} textAlign="center">
              Répond quand il sait, et reconnaît quand l’info n’est pas dans les documents.
            </Text>
            <Text fontSize="9px" color={T.textMuted} mt={1}>(mesure exacte, sans IA)</Text>
          </VStack>

          <VStack align="start" spacing={3} flex={1} minW="240px" pt={2}>
            <HStack spacing={8} align="start">
              <VStack align="start" spacing={0}>
                <InfoLabel text="Qualité globale" help="Une seconde IA juge si la réponse correspond à la bonne réponse attendue. Indicatif : ce juge se trompe parfois (±30%), on s’y fie moins qu’aux mesures exactes." fontSize="10px" color={T.textMuted} textTransform="uppercase" />
                <Text fontSize="lg" fontWeight="700" fontFamily="'Fira Code', monospace" color={T.textSecondary}>{pct(ref.C1_mean)}</Text>
                <Text fontSize="9px" color={T.textMuted}>évaluée par IA (indicatif)</Text>
              </VStack>
              <VStack align="start" spacing={0}>
                <InfoLabel text="Temps de réponse" help="Temps médian (p50) et temps des 5% les plus lents (p95) pour produire une réponse." fontSize="10px" color={T.textMuted} textTransform="uppercase" />
                <Text fontSize="lg" fontWeight="700" fontFamily="'Fira Code', monospace" color={T.textSecondary}>
                  {ref.latency_p50_s != null ? `${Math.round(ref.latency_p50_s)}s` : '--'}
                </Text>
                <Text fontSize="9px" color={T.textMuted}>en moyenne</Text>
              </VStack>
            </HStack>
            {ref.gates && Object.keys(ref.gates).length > 0 && (
              <Box>
                <Text fontSize="10px" color={T.textMuted} textTransform="uppercase" mb={1.5}>Objectifs cibles</Text>
                <HStack spacing={2} flexWrap="wrap">
                  {Object.entries(ref.gates).map(([k, g]) => <GateBadge key={k} gateKey={k} gate={g} />)}
                </HStack>
              </Box>
            )}
          </VStack>
        </HStack>
      </Card>

      {/* ── OSMOSIS vs moteur de recherche classique ── */}
      {osm && rag ? (
        <Card accent={T.statusOk}>
          <HStack spacing={2} mb={1}>
            <FiAward size={15} color={T.statusOk} />
            <Text fontSize="sm" fontWeight="800" color={T.textPrimary}>OSMOSIS vs un moteur de recherche classique</Text>
          </HStack>
          <Text fontSize="12px" color={T.textSecondary} mb={3} lineHeight="1.6">
            Même corpus, mêmes questions, même IA de rédaction. La seule différence : le moteur classique se contente de
            chercher des passages de texte ressemblants, là où OSMOSIS s’appuie sur une base de connaissances structurée.
          </Text>

          {/* Synthèse chiffrée (entièrement recalculée à chaque test — aucune
              interprétation figée : seuls les nombres parlent). */}
          <Box bg={`${T.statusOk}10`} border="1px solid" borderColor={`${T.statusOk}33`} rounded="md" px={4} py={3} mb={4}>
            <Text fontSize="13px" color={T.textPrimary} lineHeight="1.7">
              👉 Sur ces <b>{nTotal} questions</b> : OSMOSIS adopte le bon comportement répondre/s’abstenir{' '}
              <b>{pct(osm.abstention_correct_rate)}</b> du temps (moteur classique : <b>{pct(rag.abstention_correct_rate)}</b>),
              et cite les bonnes références <b>{pct(osm.exact_id_recall_mean)}</b> du temps (moteur classique :{' '}
              <b>{pct(rag.exact_id_recall_mean)}</b>).
            </Text>
          </Box>

          <Box overflowX="auto">
            <Table size="sm" variant="unstyled">
              <Thead>
                <Tr borderBottom="1px solid" borderColor={T.borderSubtle}>
                  <Th color={T.textMuted} fontSize="10px" py={2} textTransform="none">Ce qu’on mesure</Th>
                  <Th color={T.accentOsm} fontSize="10px" py={2} isNumeric>OSMOSIS</Th>
                  <Th color={T.textMuted} fontSize="10px" py={2} isNumeric textTransform="none">Moteur classique</Th>
                  <Th color={T.textMuted} fontSize="10px" py={2} isNumeric>Écart</Th>
                </Tr>
              </Thead>
              <Tbody>
                {([
                  ['Précision des références', 'Donne-t-il les bons codes / identifiants ?', osm.exact_id_recall_mean, rag.exact_id_recall_mean],
                  ['Honnêteté', 'Répond s’il sait, s’abstient sinon', osm.abstention_correct_rate, rag.abstention_correct_rate],
                  ['Qualité globale (IA)', 'Jugée par une IA — indicatif', osm.C1_mean, rag.C1_mean],
                ] as [string, string, number | null | undefined, number | null | undefined][]).map(([label, help, o, r]) => {
                  const d = o != null && r != null ? o - r : null
                  return (
                    <Tr key={label} borderBottom="1px solid" borderColor={T.borderSubtle}>
                      <Td py={2}><InfoLabel text={label} help={help} fontSize="12px" fontWeight="600" color={T.textSecondary} /></Td>
                      <Td py={2} isNumeric><Text fontSize="13px" fontWeight="700" fontFamily="'Fira Code', monospace" color={o != null ? scoreColor(o) : T.textMuted}>{pct(o)}</Text></Td>
                      <Td py={2} isNumeric><Text fontSize="13px" fontFamily="'Fira Code', monospace" color={r != null ? scoreColor(r) : T.textMuted}>{pct(r)}</Text></Td>
                      <Td py={2} isNumeric><Text fontSize="12px" fontWeight="700" fontFamily="'Fira Code', monospace" color={d != null ? deltaColor(d) : T.textMuted}>{fmtDeltaPp(d)}</Text></Td>
                    </Tr>
                  )
                })}
                <Tr>
                  <Td py={2}><Text fontSize="12px" color={T.textMuted}>Temps de réponse</Text></Td>
                  <Td py={2} isNumeric><Text fontSize="12px" fontFamily="'Fira Code', monospace" color={T.textMuted}>{osm.latency_p50_s != null ? `${Math.round(osm.latency_p50_s)}s` : '--'}</Text></Td>
                  <Td py={2} isNumeric><Text fontSize="12px" fontFamily="'Fira Code', monospace" color={T.statusOk}>{rag.latency_p50_s != null ? `${Math.round(rag.latency_p50_s)}s` : '--'}</Text></Td>
                  <Td py={2} isNumeric><Text fontSize="11px" color={T.textMuted}>classique + rapide</Text></Td>
                </Tr>
              </Tbody>
            </Table>
          </Box>
          <Text fontSize="11px" color={T.textMuted} mt={3} lineHeight="1.6">
            Comment lire : sur les questions pièges et hors-périmètre, un système qui refuse souvent obtient un bon score
            sans nécessairement « comprendre » la question. La ligne « Honnêteté » corrige ce biais — elle vérifie qu’un
            système répond bien <i>quand il le faut</i>. Comparez toujours les deux ensemble.
          </Text>
        </Card>
      ) : (
        <Card>
          <Text fontSize="13px" color={T.textMuted}>
            Comparaison avec le moteur classique non disponible — lance <Text as="span" fontFamily="'Fira Code', monospace" fontSize="11px">scripts/bench_a38_classic_rag.py</Text>.
          </Text>
        </Card>
      )}

      {/* ── Famille 1 : questions avec une réponse attendue ── */}
      <Card>
        <Text fontSize="sm" fontWeight="700" color={T.textPrimary} mb={1}>Questions avec une réponse attendue</Text>
        <Text fontSize="12px" color={T.textSecondary} mb={3}>
          Ici, bien répondre = donner la bonne information précise. On regarde la précision des références et la qualité jugée.
        </Text>
        <Box overflowX="auto">
          <Table size="sm" variant="unstyled">
            <Thead>
              <Tr borderBottom="1px solid" borderColor={T.borderSubtle}>
                <Th color={T.textMuted} fontSize="10px" py={2} textTransform="none">Type de question</Th>
                <Th color={T.textMuted} fontSize="10px" py={2} isNumeric>Nb</Th>
                <Th color={T.accentOsm} fontSize="10px" py={2} isNumeric textTransform="none">Précision réf. (OSMOSIS)</Th>
                {rag && <Th color={T.textMuted} fontSize="10px" py={2} isNumeric textTransform="none">(classique)</Th>}
                <Th color={T.accentOsm} fontSize="10px" py={2} isNumeric textTransform="none">Qualité IA (OSMOSIS)</Th>
                {rag && <Th color={T.textMuted} fontSize="10px" py={2} isNumeric textTransform="none">(classique)</Th>}
              </Tr>
            </Thead>
            <Tbody>
              {sortTypes(Object.keys(ref.per_type ?? {})).filter(t => ANSWER_TYPES.includes(t)).map(t => {
                const oEir = osm?.exact_id_recall_per_type?.[t]?.mean
                const rEir = rag?.exact_id_recall_per_type?.[t]?.mean
                const oC1 = osm?.per_type?.[t]?.mean
                const rC1 = rag?.per_type?.[t]?.mean
                const n = ref.per_type?.[t]?.n ?? 0
                return (
                  <Tr key={t} borderBottom="1px solid" borderColor={T.borderSubtle} _hover={{ bg: T.bgElevated }}>
                    <Td py={2}><InfoLabel text={typeLabel(t)} help={typeHelp(t)} fontSize="12px" fontWeight="600" color={T.textSecondary} /></Td>
                    <Td py={2} isNumeric><Text fontSize="11px" color={T.textMuted} fontFamily="'Fira Code', monospace">{n}</Text></Td>
                    <Td py={2} isNumeric><Text fontSize="12px" fontWeight="700" fontFamily="'Fira Code', monospace" color={oEir != null ? scoreColor(oEir) : T.textMuted}>{oEir != null ? pct(oEir) : '—'}</Text></Td>
                    {rag && <Td py={2} isNumeric><Text fontSize="12px" fontFamily="'Fira Code', monospace" color={rEir != null ? scoreColor(rEir) : T.textMuted}>{rEir != null ? pct(rEir) : '—'}</Text></Td>}
                    <Td py={2} isNumeric><Text fontSize="12px" fontFamily="'Fira Code', monospace" color={oC1 != null ? scoreColor(oC1) : T.textMuted}>{oC1 != null ? pct(oC1) : '—'}</Text></Td>
                    {rag && <Td py={2} isNumeric><Text fontSize="12px" fontFamily="'Fira Code', monospace" color={rC1 != null ? scoreColor(rC1) : T.textMuted}>{rC1 != null ? pct(rC1) : '—'}</Text></Td>}
                  </Tr>
                )
              })}
            </Tbody>
          </Table>
        </Box>
        <Text fontSize="10px" color={T.textMuted} mt={2}>
          « Précision réf. » = mesure exacte (sans IA). « Qualité IA » = jugée par une IA, indicative. Un « — » = ce type
          n’attend pas d’identifiant précis.
        </Text>
      </Card>

      {/* ── Famille 2 : l'arbitrage répondre / s'abstenir (auto-porteur) ── */}
      {NOANSWER_TYPES.some(t => ref.per_type?.[t]) && (() => {
        // Les deux faces du bon arbitrage, calculées depuis les données du run.
        const oRefuse = weightedAbstention(osm, NOANSWER_TYPES)
        const rRefuse = weightedAbstention(rag, NOANSWER_TYPES)
        const oAnsAb = weightedAbstention(osm, ANSWER_TYPES)
        const rAnsAb = weightedAbstention(rag, ANSWER_TYPES)
        const oAnswer = oAnsAb.rate != null ? 1 - oAnsAb.rate : null
        const rAnswer = rAnsAb.rate != null ? 1 - rAnsAb.rate : null
        const cell = (v: number | null) => (
          <Text fontSize="14px" fontWeight="700" fontFamily="'Fira Code', monospace" color={v != null ? scoreColor(v) : T.textMuted}>{v != null ? pct(v) : '—'}</Text>
        )
        return (
          <Card accent={T.statusWarn}>
            <Text fontSize="sm" fontWeight="700" color={T.textPrimary} mb={1}>Sait-il s’abstenir… sans tout refuser ?</Text>
            <Text fontSize="12px" color={T.textSecondary} mb={4} lineHeight="1.6">
              Un bon système doit réussir <b>les deux lignes à la fois</b> : refuser les questions pièges / hors-périmètre,
              <b> et</b> répondre aux vraies questions. Refuser systématiquement gonfle la 1<sup>re</sup> ligne au prix de
              la 2<sup>de</sup> — d’où l’importance de les lire ensemble. Sur chaque ligne, <b>plus haut = mieux</b> (vert).
            </Text>
            <Box overflowX="auto">
              <Table size="sm" variant="unstyled">
                <Thead>
                  <Tr borderBottom="1px solid" borderColor={T.borderSubtle}>
                    <Th color={T.textMuted} fontSize="10px" py={2} textTransform="none">Le bon arbitrage</Th>
                    <Th color={T.accentOsm} fontSize="10px" py={2} isNumeric>OSMOSIS</Th>
                    {rag && <Th color={T.textMuted} fontSize="10px" py={2} isNumeric textTransform="none">Moteur classique</Th>}
                  </Tr>
                </Thead>
                <Tbody>
                  <Tr borderBottom="1px solid" borderColor={T.borderSubtle}>
                    <Td py={3}>
                      <InfoLabel text={`✋ Refuse quand il le faut`} help="Questions pièges (fausse affirmation à détecter) et hors-périmètre (info absente des documents). Refuser/signaler est le bon comportement." fontSize="12px" fontWeight="600" color={T.textSecondary} />
                      <Text fontSize="10px" color={T.textMuted}>questions pièges & hors-périmètre ({oRefuse.n} q)</Text>
                    </Td>
                    <Td py={3} isNumeric>{cell(oRefuse.rate)}</Td>
                    {rag && <Td py={3} isNumeric>{cell(rRefuse.rate)}</Td>}
                  </Tr>
                  <Tr>
                    <Td py={3}>
                      <InfoLabel text={`💬 Répond quand il le faut`} help="Questions qui ont une vraie réponse dans les documents. Ici, s'abstenir est un échec — il faut répondre." fontSize="12px" fontWeight="600" color={T.textSecondary} />
                      <Text fontSize="10px" color={T.textMuted}>questions répondables ({oAnsAb.n} q)</Text>
                    </Td>
                    <Td py={3} isNumeric>{cell(oAnswer)}</Td>
                    {rag && <Td py={3} isNumeric>{cell(rAnswer)}</Td>}
                  </Tr>
                </Tbody>
              </Table>
            </Box>
            <Text fontSize="11px" color={T.textMuted} mt={3} lineHeight="1.6">
              Un <b>100%</b> sur la 1<sup>re</sup> ligne n’est PAS un bon signe s’il s’accompagne d’un score faible sur la
              2<sup>de</sup> : cela veut dire que le système refuse <i>tout</i>, y compris ce qu’il devrait traiter.
            </Text>
          </Card>
        )
      })()}

      {/* ── Historique des tests ── */}
      <Card>
        <Text fontSize="sm" fontWeight="700" color={T.textPrimary} mb={1}>Historique des tests</Text>
        <Text fontSize="12px" color={T.textSecondary} mb={3}>Chaque ligne est une exécution de la batterie de test, la plus récente en haut.</Text>
        <Box overflowX="auto">
          <Table size="sm" variant="unstyled">
            <Thead>
              <Tr borderBottom="1px solid" borderColor={T.borderSubtle}>
                <Th color={T.textMuted} fontSize="10px" py={2}>Date</Th>
                <Th color={T.textMuted} fontSize="10px" py={2} textTransform="none">Système</Th>
                <Th color={T.textMuted} fontSize="10px" py={2} isNumeric textTransform="none">Précision réf.</Th>
                <Th color={T.textMuted} fontSize="10px" py={2} isNumeric>Honnêteté</Th>
                <Th color={T.textMuted} fontSize="10px" py={2} isNumeric textTransform="none">Qualité IA</Th>
                <Th color={T.textMuted} fontSize="10px" py={2} isNumeric textTransform="none">Nb&nbsp;Q</Th>
              </Tr>
            </Thead>
            <Tbody>
              {runs.map(r => {
                const isOsm = r.arm === 'osmosis'
                return (
                  <Tr key={r.filename} borderBottom="1px solid" borderColor={T.borderSubtle} _hover={{ bg: T.bgElevated }}>
                    <Td py={2}><Text fontSize="12px" color={T.textSecondary} fontFamily="'Fira Code', monospace">{fmtTs(r.timestamp)}</Text></Td>
                    <Td py={2}><Badge fontSize="10px" bg={isOsm ? `${T.accentOsm}18` : `${T.accentRag}22`} color={isOsm ? T.accentOsm : T.textSecondary} px={1.5} rounded="sm">{isOsm ? 'OSMOSIS' : 'classique'}</Badge></Td>
                    <Td py={2} isNumeric><Text fontSize="12px" fontWeight="700" fontFamily="'Fira Code', monospace" color={r.exact_id_recall_mean != null ? scoreColor(r.exact_id_recall_mean) : T.textMuted}>{pct(r.exact_id_recall_mean)}</Text></Td>
                    <Td py={2} isNumeric><Text fontSize="12px" fontFamily="'Fira Code', monospace" color={r.abstention_correct_rate != null ? scoreColor(r.abstention_correct_rate) : T.textMuted}>{pct(r.abstention_correct_rate)}</Text></Td>
                    <Td py={2} isNumeric><Text fontSize="12px" fontFamily="'Fira Code', monospace" color={T.textMuted}>{pct(r.C1_mean)}</Text></Td>
                    <Td py={2} isNumeric><Text fontSize="11px" color={T.textMuted} fontFamily="'Fira Code', monospace">{r.n_total ?? '--'}</Text></Td>
                  </Tr>
                )
              })}
            </Tbody>
          </Table>
        </Box>
      </Card>
    </VStack>
  )
}
