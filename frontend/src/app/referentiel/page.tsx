'use client'

/**
 * Carte du Référentiel (#456) — anatomie documentaire du KG.
 *
 * Visualise les relations inter-documents calculées par le pipeline :
 * - fil de lignée (SUPERSEDES_DOC) avec preuve verbatim cliquable (PDF à la page) ;
 * - relations claim-à-claim agrégées par paire (épaisseur ∝ volume),
 *   cliquables → détail de la paire, survol → décomposition par type ;
 * - tensions CONTRADICTS avec verdict d'adjudication — ROUGE réservé aux confirmées ;
 * - registre des tensions : audit trail complet (verdict, raison, deux passages).
 *
 * Charte : 100 % variables CSS canoniques (--bg-surface, --fg-primary, --accent,
 * --warning-base pour le fil de lignée…) → fonctionne dans les 4 combinaisons
 * preset (fusion / dark-elegance) × mode (light / dark) sans code spécifique.
 */

import { useState, useEffect, useMemo, useRef, useCallback } from 'react'
import {
  Box, Flex, Heading, Text, Spinner, VStack, HStack, Icon, Button,
} from '@chakra-ui/react'
import { FiMap, FiX, FiExternalLink, FiShield, FiAlertTriangle } from 'react-icons/fi'
import { api } from '@/lib/api'
import { openSourceFile } from '@/lib/openSourceFile'

// ── Types (miroir backend /api/referentiel) ─────────────────────────────────

interface RefDocument {
  doc_id: string
  title: string
  authority: string | null
  status: 'in_force' | 'superseded' | 'external'
  n_claims: number
  n_withdrawn: number
  doc_date: string | null      // ISO — date documentaire (frise)
  date_source: 'claims' | 'cited' | null
}

interface RefLineage {
  superseder: string
  superseded: string
  scope: string | null
  detection: string | null
  evidence: string | null
  evidence_claim_id: string | null
  evidence_doc_id: string | null
  evidence_page: number | null
}

interface RefPair {
  doc_a: string
  doc_b: string
  relations: Record<string, number>
  n_relations: number
  tensions_examined: number
  tensions_confirmed: number
}

interface RefMap {
  summary: {
    n_documents: number
    n_lineages: number
    n_claims: number
    tensions_examined: number
    tensions_confirmed: number
  }
  documents: RefDocument[]
  lineage: RefLineage[]
  pairs: RefPair[]
}

interface RefTension {
  doc_a: string
  doc_b: string
  title_a: string
  title_b: string
  text_a: string
  text_b: string
  page_a: number | null
  page_b: number | null
  verdict: string | null
  reason: string | null
  method: string | null
}

interface RefTensions {
  total: number
  by_verdict: Record<string, number>
  items: RefTension[]
}

interface RefPairExample {
  text_a: string
  text_b: string
  doc_a: string
  doc_b: string
  page_a: number | null
  page_b: number | null
}

// ── Libellés français ───────────────────────────────────────────────────────

const REL_FR: Record<string, string> = {
  REFINES: 'raffine',
  COMPLEMENTS: 'complète',
  SPECIALIZES: 'spécialise',
  QUALIFIES: 'qualifie',
  CHAINS_TO: 'enchaîne vers',
  EVOLVES_TO: 'évolution',
  EVOLUTION_OF: 'évolution',
}

// Langage clair pour la décomposition par type (terme technique en infobulle)
const REL_EXPLAIN: Record<string, { label: string; desc: string }> = {
  REFINES:      { label: 'précise',          desc: 'l’un détaille ou affine une règle énoncée par l’autre' },
  QUALIFIES:    { label: 'conditionne',      desc: 'l’un ajoute des conditions ou limites d’application à l’autre' },
  COMPLEMENTS:  { label: 'complète',         desc: 'les deux couvrent des aspects voisins du même sujet' },
  SPECIALIZES:  { label: 'particularise',    desc: 'l’un applique une règle générale de l’autre à un cas précis' },
  CHAINS_TO:    { label: 'enchaîne',         desc: 'étapes successives d’une même procédure, réparties entre les deux' },
  EVOLVES_TO:   { label: 'fait évoluer',     desc: 'versions successives d’une même exigence' },
  EVOLUTION_OF: { label: 'fait évoluer',     desc: 'versions successives d’une même exigence' },
}

/** Phrase de synthèse CALCULÉE depuis la distribution des types — jamais
 *  écrite en dur (le texte explique comment lire, les données portent le
 *  verdict). `isLineage` : la paire est-elle reliée par une supersession ? */
function pairNatureFr(relations: Record<string, number>, isLineage: boolean): string | null {
  const total = Object.values(relations).reduce((s, v) => s + v, 0)
  if (!total) return null
  const share = (k: string) => (relations[k] ?? 0) / total
  if (isLineage) {
    return 'Ces deux documents sont les éditions successives d’un même texte : la nouvelle reformule, précise et encadre ce que disait l’ancienne.'
  }
  if (share('REFINES') + share('QUALIFIES') >= 0.5) {
    return 'Profil dominant : l’un précise et encadre les règles de l’autre — typique d’un guide d’application face à son texte de référence.'
  }
  if (share('COMPLEMENTS') >= 0.5) {
    return 'Profil dominant : deux textes qui se complètent — ils couvrent des facettes voisines du même sujet, sans se répéter.'
  }
  if (share('CHAINS_TO') >= 0.4) {
    return 'Profil dominant : une procédure répartie entre les deux documents — les étapes de l’un appellent celles de l’autre.'
  }
  return 'Relations variées : ces deux documents s’articulent de plusieurs manières — le détail par type ci-dessous, avec exemples.'
}

const VERDICT_FR: Record<string, { label: string; color: string; soft: string }> = {
  CONFIRMED:       { label: 'CONFIRMÉE',           color: 'var(--error-base)',   soft: 'var(--error-soft)' },
  DIFFERENT_SCOPE: { label: 'PORTÉES DIFFÉRENTES', color: 'var(--info-base)',    soft: 'var(--info-soft)' },
  EQUIVALENT:      { label: 'ÉQUIVALENCE',         color: 'var(--success-base)', soft: 'var(--success-soft)' },
  COMPLEMENTARY:   { label: 'COMPLÉMENTAIRES',     color: 'var(--accent)',       soft: 'var(--accent-soft)' },
  UNCLEAR:         { label: 'À REVOIR',            color: 'var(--fg-muted)',     soft: 'var(--bg-surface-alt)' },
  'NON_ADJUGÉ':    { label: 'NON ADJUGÉE',         color: 'var(--fg-muted)',     soft: 'var(--bg-surface-alt)' },
}

const fmtNum = (n: number) => n.toLocaleString('fr-FR')

function relBreakdownFr(relations: Record<string, number>): string {
  const parts = Object.entries(relations)
    .sort((a, b) => b[1] - a[1])
    .map(([k, v]) => `${v} ${REL_FR[k] ?? k.toLowerCase()}`)
  return parts.join(' · ')
}

function detectionFr(detection: string | null): string {
  if (detection === 'version_convention') return 'Lignée inférée par convention d’édition, corroborée par les dates de publication.'
  return 'Déclaration d’annulation extraite du document à l’ingestion.'
}

// ── Layout déterministe (chaînes de lignée = rangées, isolés = grille) ──────

interface NodePos extends RefDocument { x: number; y: number; r: number }

const COL_W = 248
const ROW_H = 168
const X0 = 150
const Y0 = 120
const GRID_COLS = 5

function computeLayout(docs: RefDocument[], lineage: RefLineage[]): { nodes: NodePos[]; w: number; h: number; chains: string[][] } {
  const byId = new Map(docs.map((d) => [d.doc_id, d]))
  // composantes connexes du graphe de lignée (non orienté), puis ordre ancien → récent
  const adj = new Map<string, Set<string>>()
  const supOf = new Map<string, string>() // superseded -> superseder
  for (const l of lineage) {
    if (!byId.has(l.superseder) || !byId.has(l.superseded)) continue
    if (!adj.has(l.superseder)) adj.set(l.superseder, new Set())
    if (!adj.has(l.superseded)) adj.set(l.superseded, new Set())
    adj.get(l.superseder)!.add(l.superseded)
    adj.get(l.superseded)!.add(l.superseder)
    supOf.set(l.superseded, l.superseder)
  }
  const visited = new Set<string>()
  const chains: string[][] = []
  for (const id of Array.from(adj.keys())) {
    if (visited.has(id)) continue
    // composante
    const comp: string[] = []
    const stack = [id]
    while (stack.length) {
      const cur = stack.pop()!
      if (visited.has(cur)) continue
      visited.add(cur)
      comp.push(cur)
      for (const nb of Array.from(adj.get(cur) ?? [])) if (!visited.has(nb)) stack.push(nb)
    }
    // ordonner : le plus ancien = jamais superséd eur dans la composante
    const compSet = new Set(comp)
    let oldest = comp.find((c) => !comp.some((o) => supOf.get(o) === c))
    if (!oldest) oldest = comp[0]
    const ordered = [oldest]
    let cur: string | undefined = oldest
    while (cur && ordered.length < comp.length) {
      const next: string | undefined = supOf.get(cur)
      if (!next || !compSet.has(next) || ordered.includes(next)) break
      ordered.push(next)
      cur = next
    }
    for (const c of comp) if (!ordered.includes(c)) ordered.push(c)
    chains.push(ordered)
  }
  chains.sort((a, b) => b.length - a.length)

  const maxClaims = Math.max(1, ...docs.map((d) => d.n_claims))
  const radius = (d: RefDocument) =>
    d.status === 'external' ? 14 : 17 + 26 * Math.sqrt(d.n_claims / maxClaims)

  const nodes: NodePos[] = []
  const placed = new Set<string>()
  let y = Y0
  for (const chain of chains) {
    chain.forEach((id, i) => {
      const d = byId.get(id)!
      nodes.push({ ...d, x: X0 + i * COL_W, y, r: radius(d) })
      placed.add(id)
    })
    y += ROW_H
  }
  // isolés : triés par volume, grille
  const singles = docs.filter((d) => !placed.has(d.doc_id)).sort((a, b) => b.n_claims - a.n_claims)
  y += 24
  singles.forEach((d, i) => {
    const col = i % GRID_COLS
    const row = Math.floor(i / GRID_COLS)
    nodes.push({ ...d, x: X0 + col * COL_W, y: y + row * ROW_H, r: radius(d) })
  })
  const w = Math.max(X0 + COL_W * Math.max(GRID_COLS, ...chains.map((c) => c.length)) + 40, 900)
  const h = y + ROW_H * Math.ceil(singles.length / GRID_COLS) + 60
  return { nodes, w, h, chains }
}

function curvePath(a: { x: number; y: number }, b: { x: number; y: number }, sag = 0.13) {
  const mx = (a.x + b.x) / 2
  const my = (a.y + b.y) / 2
  const cx = mx - (b.y - a.y) * sag
  const cy = my + (b.x - a.x) * sag
  return { d: `M ${a.x} ${a.y} Q ${cx} ${cy} ${b.x} ${b.y}`, cx, cy }
}

const qMid = (a: { x: number; y: number }, c: { x: number; y: number }, b: { x: number; y: number }) => ({
  x: 0.25 * a.x + 0.5 * c.x + 0.25 * b.x,
  y: 0.25 * a.y + 0.5 * c.y + 0.25 * b.y,
})

// Seuil d'affichage des arêtes fines (anti-bouillie : 173 paires sur le corpus)
const EDGE_MIN_RELS = 5
const EDGE_MAX = 32

// ═════════════════════════════════════════════════════════════════════════════

export default function ReferentielPage() {
  const [mapData, setMapData] = useState<RefMap | null>(null)
  const [tensions, setTensions] = useState<RefTensions | null>(null)
  const [loading, setLoading] = useState(true)
  const [view, setView] = useState<'map' | 'timeline' | 'registry'>('map')
  const [filter, setFilter] = useState<'all' | 'alive' | 'dead' | 'lineage'>('all')
  const [selectedDoc, setSelectedDoc] = useState<string | null>(null)
  const [selectedPair, setSelectedPair] = useState<RefPair | null>(null)
  const [proof, setProof] = useState<RefLineage | null>(null)
  const [hover, setHover] = useState<{ x: number; y: number; text: string } | null>(null)
  // positions ajustées au drag (type Neo4j) — surchargent le layout déterministe
  const [positions, setPositions] = useState<Record<string, { x: number; y: number }>>({})
  // mode focus : double-clic sur un document → seul lui, ses voisins et leurs liens restent visibles
  const [focusDoc, setFocusDoc] = useState<string | null>(null)
  const [verdictFilter, setVerdictFilter] = useState<string | null>(null)
  // filtre du registre sur une paire de documents (posé par les pills / panneaux)
  const [pairFilter, setPairFilter] = useState<{ a: string; b: string } | null>(null)
  const [expanded, setExpanded] = useState<number | null>(null)
  const stageRef = useRef<HTMLDivElement>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  // drag en cours : id du nœud, offset curseur→centre, et si un vrai déplacement a eu lieu
  const dragRef = useRef<{ id: string; dx: number; dy: number; moved: boolean } | null>(null)

  // les index des lignes changent avec les filtres → referme la ligne dépliée
  useEffect(() => { setExpanded(null) }, [verdictFilter, pairFilter])

  // Échap : ferme preuve, puis panneau
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      setProof(null)
      setSelectedDoc(null)
      setSelectedPair(null)
      setFocusDoc(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    async function load() {
      try {
        const [m, t] = await Promise.all([
          api.referentiel.map(),
          api.referentiel.tensions(300),
        ])
        if (m.success && m.data) setMapData(m.data as RefMap)
        if (t.success && t.data) setTensions(t.data as RefTensions)
      } catch (err) {
        console.error('Referentiel load error:', err)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  const layout = useMemo(
    () => (mapData ? computeLayout(mapData.documents, mapData.lineage) : null),
    [mapData],
  )
  // positions effectives = layout déterministe + déplacements manuels
  const nodes = useMemo(
    () => (layout?.nodes ?? []).map((n) => ({ ...n, ...(positions[n.doc_id] ?? {}) })),
    [layout, positions],
  )
  const nodeById = useMemo(
    () => new Map(nodes.map((n) => [n.doc_id, n])),
    [nodes],
  )

  // ── Drag des nœuds (les arêtes/pills suivent : tout est dérivé des positions)
  const toSvgCoords = useCallback((e: { clientX: number; clientY: number }) => {
    const svg = svgRef.current
    if (!svg) return null
    const pt = svg.createSVGPoint()
    pt.x = e.clientX
    pt.y = e.clientY
    const ctm = svg.getScreenCTM()
    return ctm ? pt.matrixTransform(ctm.inverse()) : null
  }, [])

  const startDrag = useCallback((e: React.PointerEvent, node: NodePos) => {
    if (e.button !== 0) return
    const p = toSvgCoords(e)
    if (!p) return
    dragRef.current = { id: node.doc_id, dx: p.x - node.x, dy: p.y - node.y, moved: false }
    const onMove = (ev: PointerEvent) => {
      const d = dragRef.current
      const q = toSvgCoords(ev)
      if (!d || !q) return
      const nx = q.x - d.dx
      const ny = q.y - d.dy
      // seuil anti-tremblement : en dessous, ça reste un clic
      if (!d.moved && Math.hypot(nx - node.x, ny - node.y) < 4) return
      d.moved = true
      setPositions((prev) => ({ ...prev, [d.id]: { x: nx, y: ny } }))
    }
    const onUp = () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      // laisse le onClick lire `moved` avant de nettoyer
      setTimeout(() => { dragRef.current = null }, 0)
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }, [toSvgCoords])

  const drawnPairs = useMemo(() => {
    if (!mapData) return []
    return mapData.pairs
      .filter((p) => nodeById.has(p.doc_a) && nodeById.has(p.doc_b))
      .filter((p) => p.n_relations >= EDGE_MIN_RELS || p.tensions_confirmed > 0)
      .sort((a, b) => b.n_relations - a.n_relations)
      .slice(0, EDGE_MAX)
  }, [mapData, nodeById])

  const lineageDrawn = useMemo(
    () => (mapData?.lineage ?? []).filter((l) => nodeById.has(l.superseder) && nodeById.has(l.superseded)),
    [mapData, nodeById],
  )

  const inLineage = useMemo(() => {
    const s = new Set<string>()
    for (const l of lineageDrawn) { s.add(l.superseder); s.add(l.superseded) }
    return s
  }, [lineageDrawn])

  // voisinage du document en focus : sa lignée ENTIÈRE (toute la chaîne,
  // pas seulement le voisin direct) + les documents reliés par relations
  const focusSet = useMemo(() => {
    if (!focusDoc) return null
    const up = new Map<string, string>()
    const down = new Map<string, string>()
    for (const l of lineageDrawn) { up.set(l.superseded, l.superseder); down.set(l.superseder, l.superseded) }
    const s = new Set<string>([focusDoc])
    let cur = focusDoc
    while (down.has(cur)) { cur = down.get(cur)!; if (s.has(cur)) break; s.add(cur) }
    cur = focusDoc
    while (up.has(cur)) { cur = up.get(cur)!; if (s.has(cur)) break; s.add(cur) }
    for (const p of drawnPairs) {
      if (p.doc_a === focusDoc) s.add(p.doc_b)
      if (p.doc_b === focusDoc) s.add(p.doc_a)
    }
    return s
  }, [focusDoc, lineageDrawn, drawnPairs])
  // arête fine : gardée seulement si elle TOUCHE le document focalisé
  const focusEdge = (a: string, b: string) => !focusDoc || a === focusDoc || b === focusDoc
  // fil de lignée : gardé si ses deux extrémités sont dans le voisinage
  // (la chaîne complète reste visible, maillon par maillon)
  const focusLineage = (a: string, b: string) =>
    !focusSet || (focusSet.has(a) && focusSet.has(b))

  const chainOf = useCallback((id: string): string[] => {
    const up = new Map<string, string>()   // superseded -> superseder
    const down = new Map<string, string>() // superseder -> superseded
    for (const l of lineageDrawn) { up.set(l.superseded, l.superseder); down.set(l.superseder, l.superseded) }
    const chain = [id]
    let cur = id
    while (down.has(cur)) { cur = down.get(cur)!; if (chain.includes(cur)) break; chain.push(cur) }
    cur = id
    while (up.has(cur)) { cur = up.get(cur)!; if (chain.includes(cur)) break; chain.unshift(cur) }
    return chain.reverse() // chain était récent→ancien ; rendu attendu : ancien → récent
  }, [lineageDrawn])

  const showTooltip = useCallback((e: React.MouseEvent, text: string) => {
    const rect = stageRef.current?.getBoundingClientRect()
    if (!rect) return
    setHover({ x: e.clientX - rect.left + 14, y: e.clientY - rect.top + 10, text })
  }, [])

  if (loading) {
    return (
      <Flex direction="column" align="center" justify="center" minH="60vh" gap={4}>
        <Spinner size="xl" color="var(--accent)" />
        <Text color="var(--fg-secondary)">Construction de la carte du référentiel…</Text>
      </Flex>
    )
  }

  if (!mapData || !layout || mapData.documents.length === 0) {
    return (
      <Flex direction="column" align="center" justify="center" minH="60vh" gap={4}>
        <Icon as={FiMap} boxSize={12} color="var(--fg-muted)" />
        <Heading size="lg" color="var(--fg-primary)">Aucun document dans le référentiel</Heading>
        <Text color="var(--fg-secondary)">Importez des documents pour faire apparaître leur anatomie.</Text>
      </Flex>
    )
  }

  const S = mapData.summary
  const coherent = S.tensions_confirmed === 0
  // filtre paire d'abord (bidirectionnel), puis verdict ; les compteurs suivent la paire
  const pairItems = (tensions?.items ?? []).filter(
    (t) => !pairFilter
      || (t.doc_a === pairFilter.a && t.doc_b === pairFilter.b)
      || (t.doc_a === pairFilter.b && t.doc_b === pairFilter.a),
  )
  const verdictCounts: Record<string, number> = pairFilter
    ? pairItems.reduce((acc, t) => {
        const v = t.verdict ?? 'NON_ADJUGÉ'
        acc[v] = (acc[v] ?? 0) + 1
        return acc
      }, {} as Record<string, number>)
    : tensions?.by_verdict ?? {}
  const registryTotal = pairFilter ? pairItems.length : tensions?.total ?? 0
  const registryItems = pairItems.filter(
    (t) => !verdictFilter || (t.verdict ?? 'NON_ADJUGÉ') === verdictFilter,
  )

  const openRegistryForPair = (a: string, b: string) => {
    setPairFilter({ a, b })
    setVerdictFilter(null)
    setExpanded(null)
    setView('registry')
  }

  const visibleNode = (n: NodePos) => {
    if (filter === 'alive') return n.status === 'in_force'
    if (filter === 'dead') return n.status !== 'in_force'
    if (filter === 'lineage') return inLineage.has(n.doc_id)
    return true
  }

  return (
    <Box minH="calc(100vh - 64px)" bg="var(--bg-canvas)" position="relative" overflow="hidden">
      {/* Animations + styles SVG (couleurs = variables canoniques uniquement) */}
      <style>{`
        @keyframes ref-flow { to { stroke-dashoffset: -600; } }
        @keyframes ref-pop { from { opacity:0; transform:scale(.4); } to { opacity:1; transform:scale(1); } }
        @keyframes ref-fadeup { from { opacity:0; transform:translateY(10px); } to { opacity:1; transform:none; } }
        .ref-grid-bg {
          background:
            radial-gradient(1100px 600px at 28% 14%, var(--accent-glow, transparent), transparent 60%),
            repeating-linear-gradient(0deg, transparent 0 47px, color-mix(in srgb, var(--fg-primary) 4%, transparent) 47px 48px),
            repeating-linear-gradient(90deg, transparent 0 47px, color-mix(in srgb, var(--fg-primary) 4%, transparent) 47px 48px);
        }
        .ref-edge-rel { fill:none; stroke:var(--border-strong); opacity:.42; cursor:pointer; transition:opacity var(--motion-fast), stroke var(--motion-fast); }
        .ref-edge-rel:hover, .ref-edge-rel.lit { opacity:.95; stroke:var(--accent); }
        .ref-edge-rel.dim { opacity:.10; }
        .ref-edge-rel.confirmed { stroke:var(--error-base); opacity:.9; }
        .ref-edge-lineage {
          fill:none; stroke:var(--warning-base); stroke-width:2.6; cursor:pointer;
          filter:drop-shadow(0 0 6px var(--warning-soft));
          stroke-dasharray:7 5; animation:ref-flow 26s linear infinite;
          transition:stroke var(--motion-fast), opacity var(--motion-fast);
        }
        .ref-edge-lineage:hover { stroke-width:3.6; }
        .ref-edge-lineage.dim { opacity:.18; }
        .ref-edge-hit { fill:none; stroke:transparent; stroke-width:18; cursor:pointer; }
        .ref-node { cursor:grab; touch-action:none; }
        .ref-node:active { cursor:grabbing; }
        .ref-node circle.core { fill:var(--bg-surface-alt); transition:fill var(--motion-fast); }
        .ref-node circle.ring { fill:none; stroke-width:2.6; transition:stroke-width var(--motion-fast); }
        .ref-node.alive circle.ring { stroke:var(--success-base); }
        .ref-node.dead circle.ring { stroke:var(--fg-disabled); stroke-dasharray:4 4; }
        .ref-node.external circle.ring { stroke:var(--fg-disabled); stroke-dasharray:2 5; }
        .ref-node.external circle.core, .ref-node.dead circle.core { fill:var(--bg-surface); }
        .ref-node:hover circle.ring { stroke-width:4; }
        .ref-node.sel circle.ring { stroke:var(--warning-base); stroke-width:4; filter:drop-shadow(0 0 10px var(--warning-soft)); }
        .ref-node.fade { opacity:.15; }
        .ref-node, .ref-edge-rel, .ref-edge-lineage, .ref-pill { transition: opacity var(--motion-base, .2s); }
        .ref-hidden { opacity:0 !important; pointer-events:none !important; }
        .ref-nlabel { fill:var(--fg-primary); font-family:var(--font-sans); font-weight:600; font-size:12.5px; text-anchor:middle; pointer-events:none; }
        .ref-node.dead .ref-nlabel, .ref-node.external .ref-nlabel { fill:var(--fg-muted); }
        .ref-nsub { fill:var(--fg-muted); font-family:var(--font-mono); font-size:9.5px; text-anchor:middle; pointer-events:none; letter-spacing:.05em; }
        .ref-auth { font-family:var(--font-mono); font-size:8.5px; font-weight:600; text-anchor:middle; pointer-events:none; letter-spacing:.08em; }
        .ref-pill { cursor:pointer; }
        .ref-pill rect { fill:var(--bg-surface); stroke:var(--border-default); rx:9; }
        .ref-pill.confirmed rect { stroke:var(--error-base); }
        .ref-pill text { fill:var(--fg-secondary); font-family:var(--font-mono); font-size:9px; text-anchor:middle; pointer-events:none; }
        .ref-pill.confirmed text { fill:var(--error-base); }
        .ref-pill:hover rect { stroke:var(--accent); }
        .ref-pop { animation:ref-pop .55s cubic-bezier(.2,1.4,.4,1) both; }
        .ref-fadeup { animation:ref-fadeup .6s var(--easing-standard, ease) both; }
      `}</style>

      <Box className="ref-grid-bg" position="absolute" inset={0} pointerEvents="none" />

      {/* ── En-tête ── */}
      <Flex px={9} pt={6} align="flex-end" justify="space-between" position="relative" wrap="wrap" gap={4}>
        <Box className="ref-fadeup">
          <Text fontFamily="var(--font-mono)" fontSize="11px" letterSpacing=".32em" color="var(--fg-muted)" textTransform="uppercase">
            OSMOSIS · Intelligence documentaire
          </Text>
          <Heading size="xl" color="var(--fg-primary)" letterSpacing="-.01em" mt={1}>
            Carte du Référentiel
          </Heading>
          <Text color="var(--fg-secondary)" fontSize="13px" mt={1} maxW="540px">
            L&apos;anatomie de votre base documentaire : qui remplace qui, qui raffine quoi — et chaque lien porte{' '}
            <Box as="em" color="var(--warning-base)" fontStyle="normal">sa preuve</Box>.
          </Text>
        </Box>
        <Flex
          className="ref-fadeup"
          direction="column" align="center" gap={0.5}
          border="1px solid"
          borderColor={coherent ? 'var(--success-border)' : 'var(--error-border)'}
          borderRadius="12px" px={5} py={3}
          bg={coherent ? 'var(--success-soft)' : 'var(--error-soft)'}
          style={{ animationDelay: '.5s' }}
        >
          <Icon as={coherent ? FiShield : FiAlertTriangle} color={coherent ? 'var(--success-base)' : 'var(--error-base)'} boxSize={4} />
          <Text fontSize="11px" letterSpacing=".18em" textTransform="uppercase" fontWeight={700}
            color={coherent ? 'var(--success-base)' : 'var(--error-base)'}>
            {coherent ? 'Référentiel cohérent' : 'Contradictions confirmées'}
          </Text>
          <Text fontSize="11px" color="var(--fg-secondary)">
            {fmtNum(S.tensions_examined)} tensions examinées · {fmtNum(S.tensions_confirmed)} confirmée{S.tensions_confirmed > 1 ? 's' : ''}
          </Text>
        </Flex>
      </Flex>

      {/* ── Ruban de stats ── */}
      <Flex mx={9} mt={4} border="1px solid var(--border-default)" borderRadius="12px" overflow="hidden"
        bg="var(--bg-surface)" position="relative">
        {[
          { num: fmtNum(S.n_documents), lbl: 'Documents' },
          { num: fmtNum(S.n_lineages), lbl: 'Lignées prouvées', color: 'var(--warning-base)' },
          { num: fmtNum(S.n_claims), lbl: 'Faits extraits' },
          { num: fmtNum(S.tensions_examined), lbl: 'Tensions examinées' },
          { num: fmtNum(S.tensions_confirmed), lbl: 'Contradiction confirmée', color: coherent ? 'var(--success-base)' : 'var(--error-base)' },
        ].map((s, i) => (
          <Box key={s.lbl} className="ref-fadeup" flex={1} px={5} py={3}
            borderRight={i < 4 ? '1px solid var(--border-faint)' : 'none'}
            style={{ animationDelay: `${i * 0.08}s` }}>
            <Text fontSize="24px" fontWeight={600} lineHeight={1.1} color={s.color ?? 'var(--fg-primary)'}>{s.num}</Text>
            <Text fontSize="11px" color="var(--fg-muted)" letterSpacing=".06em" textTransform="uppercase" mt={0.5}>{s.lbl}</Text>
          </Box>
        ))}
      </Flex>

      {/* ── Onglets ── */}
      <HStack mx={9} mt={4} spacing={1.5} position="relative">
        {([['map', 'Carte'], ['timeline', 'Frise chronologique'], ['registry', 'Registre des tensions']] as const).map(([v, label]) => (
          <Button key={v} size="sm" variant="ghost"
            onClick={() => { setView(v); setProof(null); setPairFilter(null) }}
            color={view === v ? 'var(--fg-primary)' : 'var(--fg-secondary)'}
            bg={view === v ? 'var(--bg-surface)' : 'transparent'}
            border="1px solid"
            borderColor={view === v ? 'var(--border-default)' : 'transparent'}
            borderBottomColor={view === v ? 'var(--bg-surface)' : 'transparent'}
            borderRadius="9px 9px 0 0"
            fontWeight={600}
            _hover={{ color: 'var(--fg-primary)' }}>
            {label}
            {v === 'registry' && <Box as="span" ml={2} fontSize="10px" color="var(--fg-muted)" fontFamily="var(--font-mono)">{fmtNum(S.tensions_examined)}</Box>}
          </Button>
        ))}
      </HStack>

      {/* ── Scène ── */}
      <Box ref={stageRef} mx={9} mb={3} position="relative"
        border="1px solid var(--border-default)" borderRadius="0 12px 12px 12px"
        bg="var(--bg-surface)"
        h={view === 'registry' ? 'calc(100vh - 296px)' : 'calc(100vh - 348px)'}
        minH="440px" overflow="hidden">

        {view === 'map' && (
          <>
            {/* filtres */}
            <HStack position="absolute" top="14px" left="18px" zIndex={8} spacing={2}>
              {([['all', 'Tous'], ['alive', 'En vigueur'], ['dead', 'Annulés'], ['lineage', 'Lignées seules']] as const).map(([f, label]) => (
                <Box key={f} as="button" onClick={() => setFilter(f)}
                  fontSize="11.5px" fontWeight={600} letterSpacing=".03em"
                  color={filter === f ? 'var(--warning-base)' : 'var(--fg-secondary)'}
                  border="1px solid"
                  borderColor={filter === f ? 'var(--warning-border)' : 'var(--border-default)'}
                  bg={filter === f ? 'var(--warning-soft)' : 'var(--bg-surface)'}
                  borderRadius="20px" px={3} py={1.5}
                  _hover={{ color: 'var(--fg-primary)' }}>
                  {label}
                </Box>
              ))}
              {focusDoc && (
                <Box as="button" onClick={() => setFocusDoc(null)}
                  fontSize="11.5px" fontWeight={700} letterSpacing=".03em" whiteSpace="nowrap"
                  color="var(--accent)" border="1px solid var(--accent)"
                  bg="var(--accent-soft)" borderRadius="20px" px={3} py={1.5}
                  title="Sortir du focus (ou double-clic dans le vide / Échap)">
                  ◎ Focus : {nodeById.get(focusDoc)?.title ?? focusDoc}  ✕
                </Box>
              )}
              {Object.keys(positions).length > 0 && (
                <Box as="button" onClick={() => setPositions({})}
                  fontSize="11.5px" fontWeight={600} letterSpacing=".03em"
                  color="var(--fg-secondary)" border="1px dashed var(--border-default)"
                  bg="var(--bg-surface)" borderRadius="20px" px={3} py={1.5}
                  title="Revenir à la disposition automatique"
                  _hover={{ color: 'var(--fg-primary)' }}>
                  ⟲ Réorganiser
                </Box>
              )}
            </HStack>
            <Text position="absolute" top="18px" right="20px" zIndex={8} fontSize="11.5px"
              color="var(--fg-muted)" fontFamily="var(--font-mono)">
              clic : document · double-clic : isoler son voisinage · fil ambré : preuve · arête fine : détail
            </Text>

            {/* SVG carte (scrollable verticalement si grande) */}
            <Box position="absolute" inset={0} overflowY="auto" overflowX="hidden">
              <svg ref={svgRef} viewBox={`0 0 ${layout.w} ${layout.h}`} style={{ width: '100%', display: 'block' }}
                onClick={(e) => { if (e.target === e.currentTarget) { setSelectedDoc(null); setSelectedPair(null) } }}
                onDoubleClick={(e) => { if (e.target === e.currentTarget) setFocusDoc(null) }}>
                <defs>
                  <marker id="ref-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                    <path d="M 0 1 L 9 5 L 0 9 z" fill="var(--warning-base)" />
                  </marker>
                </defs>

                {/* arêtes fines (relations agrégées) */}
                {drawnPairs.map((p, i) => {
                  const a = nodeById.get(p.doc_a)!
                  const b = nodeById.get(p.doc_b)!
                  const c = curvePath(a, b)
                  const w = Math.max(1, Math.min(7, p.n_relations / 70))
                  const mid = qMid(a, { x: c.cx, y: c.cy }, b)
                  const tip = `${a.title} ↔ ${b.title} — ${p.n_relations} relations : ${relBreakdownFr(p.relations)}`
                  const dim = filter === 'lineage'
                  const lit = selectedDoc != null && (p.doc_a === selectedDoc || p.doc_b === selectedDoc)
                  const hid = !focusEdge(p.doc_a, p.doc_b)
                  return (
                    <g key={`${p.doc_a}|${p.doc_b}`}>
                      <path className={`ref-edge-rel ref-pop ${p.tensions_confirmed > 0 ? 'confirmed' : ''} ${dim ? 'dim' : ''} ${lit ? 'lit' : ''} ${hid ? 'ref-hidden' : ''}`}
                        d={c.d} strokeWidth={w} style={{ animationDelay: `${0.9 + i * 0.04}s` }}
                        onMouseMove={(e) => showTooltip(e, tip)}
                        onMouseLeave={() => setHover(null)}
                        onClick={() => { setSelectedPair(p); setSelectedDoc(null) }} />
                      {p.tensions_examined > 0 && !dim && (
                        <g className={`ref-pill ref-pop ${p.tensions_confirmed > 0 ? 'confirmed' : ''} ${hid ? 'ref-hidden' : ''}`}
                          style={{ animationDelay: `${1.3 + i * 0.04}s` }}
                          onClick={() => openRegistryForPair(p.doc_a, p.doc_b)}>
                          <rect x={mid.x - 64} y={mid.y - 11} width={128} height={20} />
                          <text x={mid.x} y={mid.y + 3.5}>
                            {p.tensions_examined} examinée{p.tensions_examined > 1 ? 's' : ''} · {p.tensions_confirmed} confirmée
                          </text>
                        </g>
                      )}
                    </g>
                  )
                })}

                {/* fil de lignée (ambre) */}
                {lineageDrawn.map((l, i) => {
                  const a = nodeById.get(l.superseder)!
                  const b = nodeById.get(l.superseded)!
                  const c = curvePath(b, a, 0.10) // flèche orientée vers le document courant
                  const dim = filter === 'alive' || filter === 'dead'
                  const hid = !focusLineage(l.superseder, l.superseded)
                  return (
                    <g key={`lin-${i}`}>
                      <path className={`ref-edge-lineage ${dim ? 'dim' : ''} ${hid ? 'ref-hidden' : ''}`} d={c.d}
                        markerEnd="url(#ref-arrow)" style={{ animationDelay: `${0.5 + i * 0.15}s` }} />
                      <path className={`ref-edge-hit ${hid ? 'ref-hidden' : ''}`} d={c.d}
                        onMouseMove={(e) => showTooltip(e, `${a.title} remplace ${b.title} — cliquez pour la preuve`)}
                        onMouseLeave={() => setHover(null)}
                        onClick={() => setProof(l)} />
                    </g>
                  )
                })}

                {/* nœuds documents (déplaçables — les arêtes suivent) */}
                {nodes.map((n, i) => {
                  const cls = n.status === 'in_force' ? 'alive' : n.status === 'external' ? 'external' : 'dead'
                  const authClass = (n.authority ?? '').toUpperCase()
                  const authColor = authClass === 'EASA' ? 'var(--info-base)' : authClass === 'FAA' ? 'var(--accent)' : 'var(--fg-muted)'
                  const sub = n.status === 'external'
                    ? 'réf. externe — non ingéré'
                    : `${n.status === 'superseded' ? '✝ annulé · ' : ''}${fmtNum(n.n_claims)} faits`
                  const hid = focusSet != null && !focusSet.has(n.doc_id)
                  return (
                    <g key={n.doc_id}
                      className={`ref-node ref-pop ${cls} ${selectedDoc === n.doc_id ? 'sel' : ''} ${visibleNode(n) ? '' : 'fade'} ${hid ? 'ref-hidden' : ''}`}
                      style={{ animationDelay: `${0.15 + i * 0.05}s`, transformOrigin: `${n.x}px ${n.y}px` }}
                      onPointerDown={(e) => startDrag(e, n)}
                      onClick={() => {
                        if (dragRef.current?.moved) return // c'était un drag, pas un clic
                        setSelectedDoc(n.doc_id); setSelectedPair(null)
                      }}
                      onDoubleClick={(e) => { e.stopPropagation(); setFocusDoc(n.doc_id) }}>
                      <circle className="core" cx={n.x} cy={n.y} r={n.r} />
                      <circle className="ring" cx={n.x} cy={n.y} r={n.r} />
                      {n.authority && (
                        <text className="ref-auth" x={n.x} y={n.y + 3.5} fill={authColor}>{n.authority}</text>
                      )}
                      <text className="ref-nlabel" x={n.x} y={n.y + n.r + 17}>{n.title}</text>
                      <text className="ref-nsub" x={n.x} y={n.y + n.r + 31}>{sub}</text>
                    </g>
                  )
                })}
              </svg>
            </Box>

          </>
        )}

        {/* ════════ Frise chronologique ════════ */}
        {view === 'timeline' && (
          <TimelineView
            docs={nodes}
            chains={layout.chains}
            selectedDoc={selectedDoc}
            onSelect={(id) => { setSelectedDoc(id); setSelectedPair(null) }}
          />
        )}

        {/* ── Éléments partagés carte + frise : tooltip, panneau, fiche preuve ── */}
        {view !== 'registry' && (
          <>
            {/* tooltip survol */}
            {hover && (
              <Box position="absolute" left={`${hover.x}px`} top={`${hover.y}px`} zIndex={30} pointerEvents="none"
                bg="var(--bg-surface)" border="1px solid var(--border-default)" borderRadius="8px"
                px={3} py={2} fontSize="11.5px" color="var(--fg-primary)" maxW="380px" boxShadow="var(--shadow-md)">
                {hover.text}
              </Box>
            )}

            {/* panneau latéral : document OU paire */}
            <Box position="absolute" top={0} right={0} bottom={0} w="390px" zIndex={12}
              bg="var(--bg-surface)" borderLeft="1px solid var(--border-default)"
              transform={selectedDoc || selectedPair ? 'none' : 'translateX(100%)'}
              transition="transform var(--motion-slow) var(--easing-emphasis, ease)"
              p={6} overflowY="auto" boxShadow="var(--shadow-lg)">
              <Button position="absolute" top="12px" right="12px" size="xs" variant="ghost"
                onClick={() => { setSelectedDoc(null); setSelectedPair(null) }}>
                <Icon as={FiX} />
              </Button>
              {selectedDoc && nodeById.has(selectedDoc) && (
                <DocPanel
                  node={nodeById.get(selectedDoc)!}
                  chain={chainOf(selectedDoc).map((id) => nodeById.get(id)).filter(Boolean) as NodePos[]}
                  lineage={lineageDrawn}
                  pairs={mapData.pairs.filter((p) => p.doc_a === selectedDoc || p.doc_b === selectedDoc)}
                  nodeById={nodeById}
                  onProof={setProof}
                  onRegistry={openRegistryForPair}
                />
              )}
              {selectedPair && (
                <PairPanel pair={selectedPair} nodeById={nodeById}
                  isLineage={lineageDrawn.some((l) =>
                    (l.superseder === selectedPair.doc_a && l.superseded === selectedPair.doc_b) ||
                    (l.superseder === selectedPair.doc_b && l.superseded === selectedPair.doc_a))}
                  onRegistry={() => openRegistryForPair(selectedPair.doc_a, selectedPair.doc_b)} />
              )}
            </Box>

            {/* fiche preuve (modale) */}
            {proof && (
              <Flex position="absolute" inset={0} zIndex={20} align="center" justify="center"
                bg="var(--bg-overlay)" backdropFilter="blur(3px)"
                onClick={(e) => { if (e.target === e.currentTarget) setProof(null) }}>
                <Box w="540px" maxW="92%" borderRadius="14px" position="relative"
                  bg="var(--bg-surface)" border="1px solid var(--warning-border)"
                  boxShadow="var(--shadow-modal)" px={8} py={7}>
                  <Button position="absolute" top="10px" right="10px" size="xs" variant="ghost" onClick={() => setProof(null)}>
                    <Icon as={FiX} />
                  </Button>
                  <Text fontFamily="var(--font-mono)" fontSize="10px" letterSpacing=".34em"
                    color="var(--warning-base)" textTransform="uppercase" mb={3}>
                    Preuve de supersession · extraite à l&apos;ingestion
                  </Text>
                  <Text fontSize="20px" fontWeight={600} mb={4} color="var(--fg-primary)">
                    <Box as="span" color="var(--warning-base)">{nodeById.get(proof.superseder)?.title}</Box>
                    {' '}remplace{' '}
                    <Box as="span" color="var(--fg-secondary)">{nodeById.get(proof.superseded)?.title}</Box>
                  </Text>
                  <Box fontFamily="var(--font-mono)" fontSize="12.5px" lineHeight={1.65} color="var(--fg-primary)"
                    bg="var(--warning-soft)" border="1px solid var(--warning-border)" borderRadius="9px" px={4} py={4}>
                    {proof.evidence || detectionFr(proof.detection)}
                  </Box>
                  <Flex justify="space-between" align="center" mt={4}>
                    <Text fontFamily="var(--font-mono)" fontSize="11.5px" color="var(--fg-secondary)">
                      {proof.evidence_doc_id ? (
                        <>Source : <Box as="b" color="var(--warning-base)">{nodeById.get(proof.evidence_doc_id)?.title ?? proof.evidence_doc_id}</Box>
                          {proof.evidence_page != null && <> · page {proof.evidence_page}</>}</>
                      ) : (
                        <>{detectionFr(proof.detection)}</>
                      )}
                    </Text>
                    {proof.evidence_doc_id && (
                      <Button size="sm" variant="outline" borderColor="var(--warning-border)" color="var(--warning-base)"
                        rightIcon={<FiExternalLink />}
                        onClick={() => openSourceFile(proof.evidence_doc_id!, proof.evidence_page ?? undefined)}>
                        Ouvrir le PDF à la page
                      </Button>
                    )}
                  </Flex>
                </Box>
              </Flex>
            )}
          </>
        )}

        {/* ════════ Registre des tensions ════════ */}
        {view === 'registry' && (
          <Box p={7} h="100%" overflowY="auto">
            <Flex align="flex-start" justify="space-between" mb={4} wrap="wrap" gap={3}>
              <Box>
                <Heading size="md" color="var(--fg-primary)">Registre des tensions</Heading>
                <Text color="var(--fg-secondary)" fontSize="12.5px" mt={1}>
                  Chaque paire signalée par le détecteur a été <b>relue dans ses passages sources</b> par
                  l&apos;adjudicateur. Verdict et raison tracés.
                </Text>
              </Box>
              <HStack spacing={2} wrap="wrap">
                {pairFilter && (
                  <Box as="button" onClick={() => setPairFilter(null)}
                    fontSize="11.5px" fontWeight={700} letterSpacing=".03em" whiteSpace="nowrap"
                    color="var(--warning-base)" border="1px solid var(--warning-border)"
                    bg="var(--warning-soft)" borderRadius="20px" px={3} py={1.5}
                    title="Retirer le filtre de paire">
                    {nodeById.get(pairFilter.a)?.title ?? pairFilter.a}
                    {' ↔ '}
                    {nodeById.get(pairFilter.b)?.title ?? pairFilter.b}
                    {'  ✕'}
                  </Box>
                )}
                <VerdictChip label={`Toutes · ${fmtNum(registryTotal)}`} active={!verdictFilter} onClick={() => setVerdictFilter(null)} />
                {Object.entries(verdictCounts).sort((a, b) => b[1] - a[1]).map(([v, n]) => (
                  <VerdictChip key={v} label={`${VERDICT_FR[v]?.label ?? v} · ${fmtNum(n)}`}
                    color={VERDICT_FR[v]?.color}
                    active={verdictFilter === v} onClick={() => setVerdictFilter(verdictFilter === v ? null : v)} />
                ))}
              </HStack>
            </Flex>

            {coherent && !pairFilter && (
              <Flex border="1px solid var(--success-border)" bg="var(--success-soft)" borderRadius="11px"
                px={5} py={4} gap={4} align="center" mb={5}>
                <Icon as={FiShield} color="var(--success-base)" boxSize={6} />
                <Box>
                  <Text fontWeight={700} color="var(--success-base)" fontSize="13px">
                    Aucune contradiction vive dans ce référentiel
                  </Text>
                  <Text color="var(--fg-secondary)" fontSize="12px" mt={0.5} lineHeight={1.5}>
                    {fmtNum(S.tensions_examined)} tensions candidates examinées en contexte — conversions d&apos;unités,
                    conditions d&apos;application différentes, compléments du même cadre ou citations historiques.
                    La prochaine vraie contradiction ingérée déclenchera seule l&apos;alerte, preuve à l&apos;appui.
                  </Text>
                </Box>
              </Flex>
            )}

            <Box as="table" w="100%" style={{ borderCollapse: 'collapse' }}>
              <Box as="thead">
                <Box as="tr">
                  {['Paire de documents', 'Verdict', 'Raison (adjudicateur)', 'Méthode'].map((h, i) => (
                    <Box as="th" key={h} textAlign="left" fontSize="10.5px" letterSpacing=".14em"
                      textTransform="uppercase" color="var(--fg-muted)" px={3} py={2.5}
                      borderBottom="1px solid var(--border-default)" fontWeight={600}
                      w={i === 0 ? '22%' : i === 1 ? '14%' : i === 3 ? '13%' : undefined}>
                      {h}
                    </Box>
                  ))}
                </Box>
              </Box>
              <Box as="tbody">
                {registryItems.map((t, i) => {
                  const v = VERDICT_FR[t.verdict ?? 'NON_ADJUGÉ'] ?? VERDICT_FR['NON_ADJUGÉ']
                  return (
                    <RegistryRow key={i} t={t} v={v} expanded={expanded === i}
                      onToggle={() => setExpanded(expanded === i ? null : i)} />
                  )
                })}
              </Box>
            </Box>
            {tensions && registryItems.length < (verdictFilter ? (verdictCounts[verdictFilter] ?? 0) : registryTotal) && (
              <Text py={4} color="var(--fg-muted)" fontSize="12px" fontFamily="var(--font-mono)">
                … {fmtNum((verdictFilter ? (verdictCounts[verdictFilter] ?? 0) : registryTotal) - registryItems.length)} autres paires examinées (300 premières affichées)
              </Text>
            )}
          </Box>
        )}
      </Box>

      {/* ── Légende (sous la scène, pour ne pas masquer le graphe) ── */}
      {view === 'map' && (
        <Flex mx={9} mb={5} px={4} py={2.5} gap={7} wrap="wrap" align="center"
          border="1px solid var(--border-faint)" borderRadius="10px"
          bg="var(--bg-surface)" fontSize="11.5px" color="var(--fg-secondary)" position="relative">
          <HStack><Box w="30px" borderTop="2.5px solid var(--warning-base)" /><Text fontSize="11.5px">Lignée de supersession — <Box as="i" color="var(--warning-base)" fontStyle="normal">cliquez pour la preuve</Box></Text></HStack>
          <HStack><Box w="30px" borderTop="1.5px solid var(--border-strong)" /><Text fontSize="11.5px">Relations entre faits — épaisseur ∝ volume</Text></HStack>
          <HStack><Box w="30px" borderTop="2.5px solid var(--error-base)" /><Text fontSize="11.5px">Tension <Box as="b" color="var(--error-base)">confirmée</Box>{coherent ? ' (aucune)' : ''}</Text></HStack>
          <HStack>
            <Box w="11px" h="11px" borderRadius="50%" border="2.5px solid var(--success-base)" bg="var(--bg-surface-alt)" />
            <Text fontSize="11.5px">En vigueur</Text>
            <Box w="11px" h="11px" borderRadius="50%" border="2.5px dashed var(--fg-disabled)" bg="var(--bg-surface)" ml={2} />
            <Text fontSize="11.5px">Annulé</Text>
          </HStack>
        </Flex>
      )}
      {view === 'timeline' && (
        <Flex mx={9} mb={5} px={4} py={2.5} gap={7} wrap="wrap" align="center"
          border="1px solid var(--border-faint)" borderRadius="10px"
          bg="var(--bg-surface)" fontSize="11.5px" color="var(--fg-secondary)" position="relative">
          <HStack><Box w="30px" borderTop="4px solid var(--success-base)" /><Text fontSize="11.5px">Période de validité du texte en vigueur</Text></HStack>
          <HStack><Box w="30px" borderTop="3px solid var(--border-strong)" opacity={0.6} /><Text fontSize="11.5px">Période révolue (jusqu&apos;au remplacement ✝)</Text></HStack>
          <HStack>
            <Box w="11px" h="11px" borderRadius="50%" border="2.5px dashed var(--warning-base)" bg="var(--bg-surface-alt)" />
            <Text fontSize="11.5px">Date inconnue — position interpolée, ordre garanti par la lignée</Text>
          </HStack>
        </Flex>
      )}
    </Box>
  )
}

// ── Frise chronologique ─────────────────────────────────────────────────────
//
// Documents sur un axe temporel (date documentaire = valid_from modal des
// faits, ou date citée par le remplaçant). Couloirs = chaînes de lignée ;
// barres = période de validité (un doc remplacé « vit » jusqu'à la date de
// son remplaçant ; l'en-vigueur court jusqu'à aujourd'hui). Les documents
// sans date mais dans une lignée sont positionnés par interpolation (ordre
// garanti, date inconnue) ; les autres vont sur l'étagère « non datés ».

const TL_W = 1400
const TL_PAD_L = 90
const TL_PAD_R = 130
const TL_TOP = 84
const TL_LANE_H = 96

const fmtDate = (iso: string) =>
  new Date(iso).toLocaleDateString('fr-FR', { month: 'short', year: 'numeric' })

function TimelineView({ docs, chains, selectedDoc, onSelect }: {
  docs: NodePos[]
  chains: string[][]
  selectedDoc: string | null
  onSelect: (id: string) => void
}) {
  const byId = useMemo(() => new Map(docs.map((d) => [d.doc_id, d])), [docs])

  const model = useMemo(() => {
    const now = Date.now()
    const dated = docs.filter((d) => d.doc_date)
    const tMin = dated.length ? Math.min(...dated.map((d) => Date.parse(d.doc_date!))) : now - 1
    const span = Math.max(1, now - tMin)
    const x = (t: number) => TL_PAD_L + ((t - tMin) / span) * (TL_W - TL_PAD_L - TL_PAD_R)
    const xToday = x(now)

    interface TLNode { doc: NodePos; x: number; dated: boolean }
    interface Lane { kind: 'chain' | 'singles'; nodes: TLNode[] }

    const inChain = new Set(chains.flat())
    const lanes: Lane[] = []

    // 1) chaînes de lignée (ordre ancien → récent) ; membres non datés interpolés
    for (const chain of chains) {
      const members = chain.map((id) => byId.get(id)).filter(Boolean) as NodePos[]
      const xs: (number | null)[] = members.map((d) => (d.doc_date ? x(Date.parse(d.doc_date)) : null))
      for (let i = 0; i < xs.length; i++) {
        if (xs[i] != null) continue
        const prev = xs.slice(0, i).filter((v) => v != null).pop() ?? null
        const next = xs.slice(i + 1).find((v) => v != null) ?? null
        xs[i] = prev != null && next != null ? (prev + next) / 2
          : prev != null ? Math.min(prev + 130, xToday - 40)
          : next != null ? Math.max(next - 130, TL_PAD_L)
          : TL_PAD_L + 130 * i
      }
      lanes.push({ kind: 'chain', nodes: members.map((d, i) => ({ doc: d, x: xs[i]!, dated: !!d.doc_date })) })
    }

    // 2) hors lignée datés : empaquetage glouton (évite le chevauchement des libellés)
    const singles = docs.filter((d) => !inChain.has(d.doc_id) && d.doc_date)
      .sort((a, b) => Date.parse(a.doc_date!) - Date.parse(b.doc_date!))
    const singleLanes: TLNode[][] = []
    for (const d of singles) {
      const px = x(Date.parse(d.doc_date!))
      let lane = singleLanes.find((l) => px - l[l.length - 1].x > 175)
      if (!lane) { lane = []; singleLanes.push(lane) }
      lane.push({ doc: d, x: px, dated: true })
    }
    for (const l of singleLanes) lanes.push({ kind: 'singles', nodes: l })

    // 3) étagère : hors lignée ET sans date — on n'invente rien
    const undated = docs.filter((d) => !inChain.has(d.doc_id) && !d.doc_date)

    // graduations (années rondes, pas adapté à l'étendue)
    const y0 = new Date(tMin).getFullYear()
    const y1 = new Date(now).getFullYear()
    const step = y1 - y0 > 30 ? 10 : 5
    const ticks: number[] = []
    for (let y = Math.ceil(y0 / step) * step; y <= y1; y += step) ticks.push(y)

    const shelfY = TL_TOP + lanes.length * TL_LANE_H + 46
    const height = shelfY + (undated.length ? 110 : 30)
    return { lanes, undated, ticks, x, xToday, height }
  }, [docs, chains, byId])

  const { lanes, undated, ticks, x, xToday, height } = model

  return (
    <>
      <Text position="absolute" top="18px" right="20px" zIndex={8} fontSize="11.5px"
        color="var(--fg-muted)" fontFamily="var(--font-mono)">
        barre verte : période de validité du texte en vigueur · clic : document
      </Text>
      <Box position="absolute" inset={0} overflowY="auto" overflowX="hidden">
        <svg viewBox={`0 0 ${TL_W} ${height}`} style={{ width: '100%', display: 'block' }}>
          {/* graduations années */}
          {ticks.map((y) => {
            const tx = x(Date.UTC(y, 0, 1))
            return (
              <g key={y}>
                <line x1={tx} y1={TL_TOP - 26} x2={tx} y2={height - 16}
                  stroke="var(--border-faint)" strokeWidth={1} />
                <text x={tx} y={TL_TOP - 34} textAnchor="middle"
                  fontFamily="var(--font-mono)" fontSize="11" fill="var(--fg-muted)">{y}</text>
              </g>
            )
          })}
          {/* aujourd'hui */}
          <line x1={xToday} y1={TL_TOP - 26} x2={xToday} y2={height - 16}
            stroke="var(--accent)" strokeWidth={1.5} strokeDasharray="5 4" opacity={0.8} />
          <text x={xToday} y={TL_TOP - 34} textAnchor="middle"
            fontFamily="var(--font-mono)" fontSize="11" fontWeight={700} fill="var(--accent)">aujourd&apos;hui</text>

          {/* couloirs */}
          {lanes.map((lane, li) => {
            const y = TL_TOP + li * TL_LANE_H + 40
            return (
              <g key={li}>
                {/* barres de période de validité (chaînes uniquement) */}
                {lane.kind === 'chain' && lane.nodes.map((n, i) => {
                  const next = lane.nodes[i + 1]
                  const xEnd = next ? next.x : xToday
                  const alive = !next && n.doc.status === 'in_force'
                  return (
                    <g key={`span-${n.doc.doc_id}`}>
                      <line x1={n.x} y1={y} x2={xEnd} y2={y}
                        stroke={alive ? 'var(--success-base)' : 'var(--border-strong)'}
                        strokeWidth={alive ? 4 : 3} opacity={alive ? 0.85 : 0.45}
                        strokeDasharray={n.dated && (next ? next.dated : true) ? undefined : '6 5'} />
                      {next && (
                        <text x={xEnd - 9} y={y - 8} fontSize="11" fill="var(--fg-muted)">✝</text>
                      )}
                      {alive && (
                        <text x={xToday + 8} y={y + 4} fontSize="10.5" fontFamily="var(--font-mono)"
                          fill="var(--success-base)">en vigueur</text>
                      )}
                    </g>
                  )
                })}
                {/* nœuds */}
                {lane.nodes.map((n) => {
                  const alive = n.doc.status === 'in_force'
                  const sub = n.dated
                    ? `${fmtDate(n.doc.doc_date!)}${n.doc.date_source === 'cited' ? ' · citée' : ''}`
                    : 'date inconnue'
                  return (
                    <g key={n.doc.doc_id} style={{ cursor: 'pointer' }} onClick={() => onSelect(n.doc.doc_id)}>
                      <circle cx={n.x} cy={y} r={11} fill="var(--bg-surface-alt)" />
                      <circle cx={n.x} cy={y} r={11} fill="none" strokeWidth={2.5}
                        stroke={alive ? 'var(--success-base)' : n.dated ? 'var(--fg-disabled)' : 'var(--warning-base)'}
                        strokeDasharray={!n.dated ? '3 4' : alive ? undefined : '4 4'}
                        style={selectedDoc === n.doc.doc_id ? { stroke: 'var(--warning-base)', strokeWidth: 4 } : undefined} />
                      <text x={n.x} y={y - 20} textAnchor="middle" fontFamily="var(--font-sans)"
                        fontWeight={600} fontSize="12" fill={alive ? 'var(--fg-primary)' : 'var(--fg-muted)'}>
                        {n.doc.title}
                      </text>
                      <text x={n.x} y={y + 27} textAnchor="middle" fontFamily="var(--font-mono)"
                        fontSize="9.5" fill="var(--fg-muted)">{sub}</text>
                    </g>
                  )
                })}
              </g>
            )
          })}

          {/* étagère des non datés */}
          {undated.length > 0 && (
            <g>
              <line x1={TL_PAD_L - 30} y1={TL_TOP + lanes.length * TL_LANE_H + 18}
                x2={TL_W - 40} y2={TL_TOP + lanes.length * TL_LANE_H + 18}
                stroke="var(--border-default)" strokeWidth={1} strokeDasharray="3 5" />
              <text x={TL_PAD_L - 30} y={TL_TOP + lanes.length * TL_LANE_H + 40}
                fontFamily="var(--font-mono)" fontSize="10.5" fill="var(--fg-muted)" letterSpacing=".12em">
                NON DATÉS — aucune date extraite ni citée, position chronologique inconnue
              </text>
              {undated.map((d, i) => {
                const ux = TL_PAD_L + 40 + i * 230
                const uy = TL_TOP + lanes.length * TL_LANE_H + 76
                return (
                  <g key={d.doc_id} style={{ cursor: 'pointer' }} onClick={() => onSelect(d.doc_id)}>
                    <circle cx={ux} cy={uy} r={10} fill="var(--bg-surface-alt)" />
                    <circle cx={ux} cy={uy} r={10} fill="none" strokeWidth={2.5}
                      stroke="var(--fg-disabled)" strokeDasharray="3 4"
                      style={selectedDoc === d.doc_id ? { stroke: 'var(--warning-base)', strokeWidth: 4 } : undefined} />
                    <text x={ux + 18} y={uy + 4} fontFamily="var(--font-sans)" fontWeight={600}
                      fontSize="11.5" fill="var(--fg-muted)">{d.title}</text>
                  </g>
                )
              })}
            </g>
          )}
        </svg>
      </Box>

    </>
  )
}

// ── Sous-composants ─────────────────────────────────────────────────────────

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <Text fontSize="11px" letterSpacing=".18em" textTransform="uppercase" color="var(--warning-base)"
      borderBottom="1px solid var(--border-default)" pb={2} mb={3} fontWeight={600}>
      {children}
    </Text>
  )
}

function DocPanel({ node, chain, lineage, pairs, nodeById, onProof, onRegistry }: {
  node: NodePos
  chain: NodePos[]
  lineage: RefLineage[]
  pairs: RefPair[]
  nodeById: Map<string, NodePos>
  onProof: (l: RefLineage) => void
  onRegistry: (docA: string, docB: string) => void
}) {
  const proof = lineage.find((l) => l.superseder === node.doc_id || l.superseded === node.doc_id)
  const tensionPairs = pairs.filter((p) => p.tensions_examined > 0)
  const totalT = tensionPairs.reduce((s, p) => s + p.tensions_examined, 0)
  const totalC = tensionPairs.reduce((s, p) => s + p.tensions_confirmed, 0)
  const alive = node.status === 'in_force'
  return (
    <>
      <Text fontFamily="var(--font-mono)" fontSize="10px" letterSpacing=".3em" color="var(--fg-muted)">DOCUMENT</Text>
      <Heading size="md" color="var(--fg-primary)" mt={1} pr={8}>{node.title}</Heading>
      <HStack mt={2} spacing={2}>
        <Box fontSize="11px" fontWeight={700} letterSpacing=".1em" textTransform="uppercase"
          borderRadius="6px" px={2.5} py={1}
          color={alive ? 'var(--success-base)' : 'var(--fg-muted)'}
          bg={alive ? 'var(--success-soft)' : 'var(--bg-surface-alt)'}
          border={alive ? '1px solid var(--success-border)' : '1px dashed var(--fg-disabled)'}>
          {alive ? '● En vigueur' : node.status === 'external' ? 'Réf. externe' : '✝ Annulé'}
        </Box>
        {node.authority && (
          <Box fontFamily="var(--font-mono)" fontSize="10px" letterSpacing=".12em" color="var(--info-base)"
            border="1px solid var(--info-border)" borderRadius="6px" px={2} py={1}>
            {node.authority}
          </Box>
        )}
      </HStack>
      <HStack mt={4} spacing={6}>
        <Box><Text fontSize="20px" fontWeight={600} color="var(--fg-primary)">{fmtNum(node.n_claims)}</Text>
          <Text fontSize="10.5px" color="var(--fg-muted)" textTransform="uppercase" letterSpacing=".08em">faits extraits</Text></Box>
        <Box><Text fontSize="20px" fontWeight={600} color="var(--fg-primary)">{fmtNum(totalT)}</Text>
          <Text fontSize="10.5px" color="var(--fg-muted)" textTransform="uppercase" letterSpacing=".08em">tensions examinées</Text></Box>
        <Box><Text fontSize="20px" fontWeight={600} color={totalC === 0 ? 'var(--success-base)' : 'var(--error-base)'}>{fmtNum(totalC)}</Text>
          <Text fontSize="10.5px" color="var(--fg-muted)" textTransform="uppercase" letterSpacing=".08em">confirmées</Text></Box>
      </HStack>

      <Box mt={5}>
        <SectionTitle>Position dans la lignée</SectionTitle>
        {chain.length > 1 ? (
          <Flex align="center" wrap="wrap" rowGap={2}>
            {chain.map((c, i) => (
              <Flex key={c.doc_id} align="center">
                <Box fontFamily="var(--font-mono)" fontSize="11px" px={2.5} py={1} borderRadius="7px"
                  border="1px solid"
                  borderColor={c.doc_id === node.doc_id ? 'var(--warning-border)' : c.status === 'in_force' ? 'var(--success-border)' : 'var(--border-default)'}
                  color={c.doc_id === node.doc_id ? 'var(--warning-base)' : c.status === 'in_force' ? 'var(--success-base)' : 'var(--fg-secondary)'}
                  bg={c.status === 'in_force' ? 'var(--success-soft)' : 'transparent'}
                  whiteSpace="nowrap">
                  {c.title}
                </Box>
                {i < chain.length - 1 && <Box color="var(--warning-base)" mx={1.5} fontSize="13px">→</Box>}
              </Flex>
            ))}
          </Flex>
        ) : (
          <Text color="var(--fg-muted)" fontSize="12px">Document hors lignée de supersession.</Text>
        )}
        {proof && (
          <Box fontSize="12px" color="var(--fg-secondary)" borderLeft="2px solid var(--warning-base)"
            pl={3} py={1.5} mt={3} fontStyle="italic" cursor="pointer" onClick={() => onProof(proof)}>
            « {(proof.evidence ?? detectionFr(proof.detection)).slice(0, 140)}{(proof.evidence ?? '').length > 140 ? '…' : ''} »
            <Text as="span" display="block" fontStyle="normal" fontFamily="var(--font-mono)" fontSize="10.5px"
              color="var(--warning-base)" mt={1}>
              ↳ voir la preuve {proof.evidence_page != null ? `· page ${proof.evidence_page} ` : ''}↗
            </Text>
          </Box>
        )}
      </Box>

      <Box mt={5}>
        <SectionTitle>Tensions avec d&apos;autres documents</SectionTitle>
        {tensionPairs.length > 0 ? tensionPairs
          .sort((a, b) => b.tensions_examined - a.tensions_examined)
          .slice(0, 8)
          .map((p) => {
            const otherId = p.doc_a === node.doc_id ? p.doc_b : p.doc_a
            const other = nodeById.get(otherId)
            return (
              <Box key={otherId} border="1px solid var(--border-faint)" borderRadius="9px" px={3} py={2.5} mb={2}
                bg="var(--bg-surface-alt)" cursor="pointer" onClick={() => onRegistry(node.doc_id, otherId)}
                _hover={{ borderColor: 'var(--border-default)' }}>
                <Flex justify="space-between" align="center">
                  <Text fontSize="12px" fontWeight={600} color="var(--fg-primary)">avec {other?.title ?? otherId}</Text>
                  <Text fontSize="11px" color={p.tensions_confirmed === 0 ? 'var(--success-base)' : 'var(--error-base)'}>
                    {p.tensions_confirmed === 0 ? '✓' : '⚠'} {p.tensions_confirmed} confirmée
                  </Text>
                </Flex>
                <Text fontSize="11.5px" color="var(--fg-secondary)" lineHeight={1.45} mt={1}>
                  {p.tensions_examined} paire{p.tensions_examined > 1 ? 's' : ''} examinée{p.tensions_examined > 1 ? 's' : ''} en contexte — détail dans le registre.
                </Text>
              </Box>
            )
          }) : (
          <Text color="var(--fg-muted)" fontSize="12px">Aucune tension détectée avec d&apos;autres documents.</Text>
        )}
      </Box>

      {node.status !== 'external' && (
        <Button mt={5} w="100%" rightIcon={<FiExternalLink />}
          onClick={() => openSourceFile(node.doc_id)}>
          Ouvrir le document source
        </Button>
      )}
    </>
  )
}

function PairPanel({ pair, nodeById, isLineage, onRegistry }: {
  pair: RefPair
  nodeById: Map<string, NodePos>
  isLineage: boolean
  onRegistry: () => void
}) {
  const a = nodeById.get(pair.doc_a)
  const b = nodeById.get(pair.doc_b)
  const entries = Object.entries(pair.relations).sort((x, y) => y[1] - x[1])
  const max = Math.max(1, ...entries.map(([, v]) => v))
  const nature = pairNatureFr(pair.relations, isLineage)
  // exemples verbatim par type (chargés au clic, mémorisés)
  const [openRel, setOpenRel] = useState<string | null>(null)
  const [examples, setExamples] = useState<Record<string, RefPairExample[] | 'loading'>>({})

  const toggleRel = async (rel: string) => {
    if (openRel === rel) { setOpenRel(null); return }
    setOpenRel(rel)
    if (examples[rel]) return
    setExamples((p) => ({ ...p, [rel]: 'loading' }))
    try {
      const res = await api.referentiel.pairExamples(pair.doc_a, pair.doc_b, rel)
      const data = (res.success && res.data ? (res.data as { items: RefPairExample[] }).items : [])
      setExamples((p) => ({ ...p, [rel]: data }))
    } catch {
      setExamples((p) => ({ ...p, [rel]: [] }))
    }
  }

  return (
    <>
      <Text fontFamily="var(--font-mono)" fontSize="10px" letterSpacing=".3em" color="var(--fg-muted)">RELATION ENTRE DOCUMENTS</Text>
      <Heading size="sm" color="var(--fg-primary)" mt={2} pr={8} lineHeight={1.4}>
        {a?.title} <Box as="span" color="var(--fg-muted)" fontFamily="var(--font-mono)" fontSize="11px" px={1}>↔</Box> {b?.title}
      </Heading>
      <Text fontSize="12px" color="var(--fg-secondary)" mt={2}>
        {fmtNum(pair.n_relations)} liens entre les faits des deux documents, détectés à l&apos;ingestion.
      </Text>
      {nature && (
        <Box mt={3} px={3} py={2.5} borderRadius="9px" bg="var(--accent-soft)"
          border="1px solid var(--border-faint)" fontSize="12px" color="var(--fg-primary)" lineHeight={1.5}>
          {nature}
        </Box>
      )}

      <Box mt={5}>
        <SectionTitle>Comment ils s&apos;articulent</SectionTitle>
        <Text fontSize="11px" color="var(--fg-muted)" mb={3} mt={-1}>
          Cliquez un type pour lire de vrais exemples, preuve à l&apos;appui.
        </Text>
        {entries.map(([k, v]) => {
          const ex = REL_EXPLAIN[k]
          const open = openRel === k
          const exData = examples[k]
          return (
            <Box key={k} mb={2.5}>
              <Box as="button" w="100%" textAlign="left" onClick={() => toggleRel(k)}
                _hover={{ bg: 'var(--bg-hover)' }} borderRadius="7px" px={2} py={1.5} mx={-2}
                title={`Relation technique : ${k}`}>
                <Flex justify="space-between" fontSize="12px" mb={1} align="baseline">
                  <Text color="var(--fg-primary)" fontWeight={600}>
                    {ex?.label ?? REL_FR[k] ?? k.toLowerCase()}
                    <Box as="span" color="var(--fg-muted)" fontWeight={400} ml={2} fontSize="11px">
                      {ex?.desc ?? ''}
                    </Box>
                  </Text>
                  <Text color="var(--fg-secondary)" fontFamily="var(--font-mono)" whiteSpace="nowrap" ml={2}>
                    {fmtNum(v)} {open ? '▾' : '▸'}
                  </Text>
                </Flex>
                <Box h="6px" borderRadius="3px" bg="var(--bg-surface-alt)" overflow="hidden">
                  <Box h="100%" w={`${(v / max) * 100}%`} bg="var(--accent)" borderRadius="3px" />
                </Box>
              </Box>
              {open && (
                <Box mt={2} mb={1}>
                  {exData === 'loading' && (
                    <Text fontSize="11.5px" color="var(--fg-muted)" px={2}>Chargement des exemples…</Text>
                  )}
                  {Array.isArray(exData) && exData.length === 0 && (
                    <Text fontSize="11.5px" color="var(--fg-muted)" px={2}>Aucun exemple disponible.</Text>
                  )}
                  {Array.isArray(exData) && exData.map((e, i) => (
                    <Box key={i} border="1px solid var(--border-faint)" borderRadius="8px" px={3} py={2.5} mb={2}
                      bg="var(--bg-surface-alt)" fontSize="11.5px" lineHeight={1.5}>
                      <Text color="var(--fg-primary)" cursor="pointer" title="Ouvrir le PDF à la page"
                        onClick={() => openSourceFile(e.doc_a, e.page_a ?? undefined)}>
                        <Box as="b" color="var(--accent)" fontFamily="var(--font-mono)" fontSize="9.5px" mr={1.5}>
                          {a?.title}{e.page_a != null ? ` · p.${e.page_a}` : ''} ↗
                        </Box>
                        « {e.text_a} »
                      </Text>
                      <Text color="var(--fg-secondary)" mt={1.5} cursor="pointer" title="Ouvrir le PDF à la page"
                        onClick={() => openSourceFile(e.doc_b, e.page_b ?? undefined)}>
                        <Box as="b" color="var(--info-base)" fontFamily="var(--font-mono)" fontSize="9.5px" mr={1.5}>
                          {b?.title}{e.page_b != null ? ` · p.${e.page_b}` : ''} ↗
                        </Box>
                        « {e.text_b} »
                      </Text>
                    </Box>
                  ))}
                </Box>
              )}
            </Box>
          )
        })}
        {entries.length === 0 && (
          <Text color="var(--fg-muted)" fontSize="12px">Pas de relation sémantique — uniquement des tensions examinées.</Text>
        )}
      </Box>

      <Box mt={5}>
        <SectionTitle>Tensions</SectionTitle>
        <Flex border="1px solid var(--border-faint)" borderRadius="9px" px={3} py={3} bg="var(--bg-surface-alt)"
          justify="space-between" align="center">
          <Text fontSize="12px" color="var(--fg-secondary)">
            {fmtNum(pair.tensions_examined)} examinée{pair.tensions_examined > 1 ? 's' : ''}
          </Text>
          <Text fontSize="12px" fontWeight={700}
            color={pair.tensions_confirmed === 0 ? 'var(--success-base)' : 'var(--error-base)'}>
            {pair.tensions_confirmed === 0 ? '✓ 0 confirmée' : `⚠ ${pair.tensions_confirmed} confirmée${pair.tensions_confirmed > 1 ? 's' : ''}`}
          </Text>
        </Flex>
        {pair.tensions_examined > 0 && (
          <Button mt={3} w="100%" variant="outline" size="sm" onClick={onRegistry}>
            Voir les verdicts dans le registre
          </Button>
        )}
      </Box>
    </>
  )
}

function VerdictChip({ label, color, active, onClick }: {
  label: string; color?: string; active: boolean; onClick: () => void
}) {
  return (
    <Box as="button" onClick={onClick}
      fontSize="11.5px" fontWeight={600} letterSpacing=".03em" whiteSpace="nowrap"
      color={active ? (color ?? 'var(--fg-primary)') : 'var(--fg-secondary)'}
      border="1px solid"
      borderColor={active ? (color ?? 'var(--border-strong)') : 'var(--border-default)'}
      bg="var(--bg-surface)" borderRadius="20px" px={3} py={1.5}
      _hover={{ color: color ?? 'var(--fg-primary)' }}>
      {label}
    </Box>
  )
}

function RegistryRow({ t, v, expanded, onToggle }: {
  t: RefTension
  v: { label: string; color: string; soft: string }
  expanded: boolean
  onToggle: () => void
}) {
  return (
    <>
      <Box as="tr" cursor="pointer" onClick={onToggle}
        _hover={{ bg: 'var(--bg-hover)' }} transition="background var(--motion-fast)">
        <Box as="td" px={3} py={3} borderBottom="1px solid var(--border-faint)" fontSize="12.5px"
          fontWeight={600} color="var(--fg-primary)" lineHeight={1.6} verticalAlign="top">
          {/* badges A/B : même mapping que les passages (la raison du juge cite « Statement A/B ») */}
          <Box as="span" fontFamily="var(--font-mono)" fontSize="9px" fontWeight={700} px={1.5} py={0.5}
            borderRadius="4px" mr={1.5} color="var(--accent)" border="1px solid var(--accent)"
            verticalAlign="middle">A</Box>
          {t.title_a}
          <Box as="span" color="var(--fg-muted)" fontFamily="var(--font-mono)" fontSize="10px" px={1.5}>VS</Box>
          <Box as="span" fontFamily="var(--font-mono)" fontSize="9px" fontWeight={700} px={1.5} py={0.5}
            borderRadius="4px" mr={1.5} color="var(--info-base)" border="1px solid var(--info-border)"
            verticalAlign="middle">B</Box>
          {t.title_b}
        </Box>
        <Box as="td" px={3} py={3} borderBottom="1px solid var(--border-faint)" verticalAlign="top">
          <Box as="span" fontFamily="var(--font-mono)" fontSize="9.5px" fontWeight={600} letterSpacing=".1em"
            px={2} py={1} borderRadius="5px" whiteSpace="nowrap"
            color={v.color} border={`1px solid ${v.color}`} bg={v.soft}
            display="inline-block" transform="rotate(-1.2deg)">
            {v.label}
          </Box>
        </Box>
        <Box as="td" px={3} py={3} borderBottom="1px solid var(--border-faint)" fontSize="12.5px"
          color="var(--fg-secondary)" lineHeight={1.5} verticalAlign="top">
          {t.reason || '—'}
        </Box>
        <Box as="td" px={3} py={3} borderBottom="1px solid var(--border-faint)"
          fontFamily="var(--font-mono)" fontSize="10px" color="var(--fg-muted)" whiteSpace="nowrap" verticalAlign="top">
          {t.method?.includes('doublecheck') ? 'Juge LLM ×2' : t.method?.startsWith('deterministic') ? 'Déterministe' : t.method?.startsWith('human') ? 'Revue humaine' : 'Juge LLM'}
        </Box>
      </Box>
      {expanded && (
        <Box as="tr">
          <Box as="td" colSpan={4} bg="var(--bg-surface-alt)" px={5} py={4}>
            <Flex gap={3.5} direction={{ base: 'column', lg: 'row' }}>
              {[
                { lbl: `PASSAGE A — ${t.title_a}${t.page_a != null ? ` · p.${t.page_a}` : ''}`, txt: t.text_a, doc: t.doc_a, page: t.page_a, border: 'var(--accent)' },
                { lbl: `PASSAGE B — ${t.title_b}${t.page_b != null ? ` · p.${t.page_b}` : ''}`, txt: t.text_b, doc: t.doc_b, page: t.page_b, border: 'var(--info-base)' },
              ].map((p) => (
                <Box key={p.lbl} flex={1} fontFamily="var(--font-mono)" fontSize="11px" lineHeight={1.6}
                  color="var(--fg-secondary)" border="1px solid var(--border-default)"
                  borderLeft={`3px solid ${p.border}`} borderRadius="8px" px={3.5} py={3}
                  cursor="pointer" title="Ouvrir le PDF à la page"
                  onClick={() => openSourceFile(p.doc, p.page ?? undefined)}>
                  <Text fontSize="10px" letterSpacing=".1em" color="var(--fg-primary)" fontWeight={700} mb={1.5}>{p.lbl} ↗</Text>
                  {p.txt}
                </Box>
              ))}
            </Flex>
          </Box>
        </Box>
      )}
    </>
  )
}
