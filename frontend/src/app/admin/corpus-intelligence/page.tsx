'use client'

/**
 * Corpus Intelligence — Analytical Observatory
 *
 * Two complementary views of the knowledge corpus:
 * - Heatmap: entity × document density matrix
 * - Bubble Chart: coverage vs contradictions vs importance
 */

import { useState, useEffect, useRef, useCallback } from 'react'
import {
  Box,
  Text,
  HStack,
  VStack,
  Spinner,
  Tabs,
  TabList,
  TabPanels,
  TabPanel,
  Tab,
  Icon,
  Badge,
  Tooltip as ChakraTooltip,
} from '@chakra-ui/react'
import { FiGrid, FiTarget } from 'react-icons/fi'
import { useRouter } from 'next/navigation'
import * as d3 from 'd3'

// ── API ────────────────────────────────────────────────────────────────

const API_BASE_URL = typeof window !== 'undefined'
  ? (process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000')
  : 'http://localhost:8000'

const getAuthHeaders = () => ({
  'Content-Type': 'application/json',
  Authorization: `Bearer ${localStorage.getItem('auth_token') || ''}`,
})

// ── Types ──────────────────────────────────────────────────────────────

interface HeatmapDoc {
  doc_id: string
  label: string
}

interface HeatmapCell {
  entity: string
  doc_id: string
  claims: number
}

interface HeatmapData {
  entities: string[]
  documents: HeatmapDoc[]
  matrix: HeatmapCell[]
  max_value: number
}

interface BubbleItem {
  name: string
  claims: number
  docs: number
  contradictions: number
  has_article: boolean
  slug: string | null
}

interface BubbleData {
  bubbles: BubbleItem[]
}

// ── Heatmap Component ──────────────────────────────────────────────────

function HeatmapView({ data }: { data: HeatmapData }) {
  const svgRef = useRef<SVGSVGElement>(null)
  const tooltipRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!svgRef.current || !data.entities.length) return

    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()

    const cellSize = 32
    const cellGap = 2
    const marginLeft = 220
    const marginTop = 180
    const marginRight = 20
    const marginBottom = 20

    const entities = data.entities
    const docs = data.documents

    const width = marginLeft + docs.length * (cellSize + cellGap) + marginRight
    const height = marginTop + entities.length * (cellSize + cellGap) + marginBottom

    svg
      .attr('width', width)
      .attr('height', height)

    // Index for fast lookup
    const cellIndex = new Map<string, number>()
    for (const cell of data.matrix) {
      cellIndex.set(`${cell.entity}::${cell.doc_id}`, cell.claims)
    }

    // Color scale — custom indigo gradient
    const colorScale = d3.scaleSequential()
      .domain([0, data.max_value])
      .interpolator((t: number) => {
        if (t === 0) return 'rgba(99, 102, 241, 0.03)'
        return d3.interpolateRgb('rgba(99, 102, 241, 0.12)', 'rgba(99, 102, 241, 0.95)')(t)
      })

    const g = svg.append('g')

    // Document labels (top, rotated)
    g.selectAll('.doc-label')
      .data(docs)
      .enter()
      .append('text')
      .attr('class', 'doc-label')
      .attr('x', 0)
      .attr('y', 0)
      .attr('transform', (_d: HeatmapDoc, i: number) =>
        `translate(${marginLeft + i * (cellSize + cellGap) + cellSize / 2}, ${marginTop - 8}) rotate(-50)`
      )
      .attr('text-anchor', 'start')
      .attr('fill', 'var(--text-muted)')
      .attr('font-size', '10px')
      .attr('font-family', 'var(--chakra-fonts-body)')
      .text((d: HeatmapDoc) => d.label.length > 35 ? d.label.slice(0, 32) + '...' : d.label)

    // Entity labels (left)
    g.selectAll('.entity-label')
      .data(entities)
      .enter()
      .append('text')
      .attr('class', 'entity-label')
      .attr('x', marginLeft - 10)
      .attr('y', (_d: string, i: number) => marginTop + i * (cellSize + cellGap) + cellSize / 2 + 4)
      .attr('text-anchor', 'end')
      .attr('fill', 'var(--text-primary)')
      .attr('font-size', '12px')
      .attr('font-weight', '500')
      .attr('font-family', 'var(--chakra-fonts-body)')
      .text((d: string) => d.length > 25 ? d.slice(0, 22) + '...' : d)

    // Calculer le top concept par document (cellule max de chaque colonne) → bordure jaune
    const topEntityPerDoc = new Map<string, { entity: string; value: number }>()
    for (let di = 0; di < docs.length; di++) {
      let maxVal = 0
      let maxEntity = ''
      for (let ei = 0; ei < entities.length; ei++) {
        const v = cellIndex.get(`${entities[ei]}::${docs[di].doc_id}`) || 0
        if (v > maxVal) { maxVal = v; maxEntity = entities[ei] }
      }
      if (maxVal > 0) {
        topEntityPerDoc.set(docs[di].doc_id, { entity: maxEntity, value: maxVal })
      }
    }

    // Calculer le top document par entité (cellule max de chaque ligne) → fond vert
    const topDocPerEntity = new Map<string, { doc_id: string; value: number }>()
    for (let ei = 0; ei < entities.length; ei++) {
      let maxVal = 0
      let maxDoc = ''
      for (let di = 0; di < docs.length; di++) {
        const v = cellIndex.get(`${entities[ei]}::${docs[di].doc_id}`) || 0
        if (v > maxVal) { maxVal = v; maxDoc = docs[di].doc_id }
      }
      if (maxVal > 0) {
        topDocPerEntity.set(entities[ei], { doc_id: maxDoc, value: maxVal })
      }
    }

    // Cells
    const tooltip = d3.select(tooltipRef.current)

    for (let ei = 0; ei < entities.length; ei++) {
      for (let di = 0; di < docs.length; di++) {
        const key = `${entities[ei]}::${docs[di].doc_id}`
        const value = cellIndex.get(key) || 0
        const isTopForDoc = topEntityPerDoc.get(docs[di].doc_id)?.entity === entities[ei] && value > 0
        const isTopForEntity = topDocPerEntity.get(entities[ei])?.doc_id === docs[di].doc_id && value > 0

        // Couleur de fond : vert si top doc pour ce concept, sinon indigo standard
        let cellFill = colorScale(value)
        if (isTopForEntity && value > 0) {
          const t = value / data.max_value
          cellFill = d3.interpolateRgb('rgba(34, 197, 94, 0.15)', 'rgba(34, 197, 94, 0.85)')(t)
        }

        // Bordure : jaune si top concept pour ce doc
        const strokeColor = isTopForDoc
          ? 'rgba(250, 204, 21, 0.8)'
          : value > 0 ? (isTopForEntity ? 'rgba(34, 197, 94, 0.3)' : 'rgba(99, 102, 241, 0.2)') : 'rgba(255,255,255,0.03)'
        const strokeWidth = isTopForDoc ? 2 : 0.5

        g.append('rect')
          .attr('x', marginLeft + di * (cellSize + cellGap))
          .attr('y', marginTop + ei * (cellSize + cellGap))
          .attr('width', cellSize)
          .attr('height', cellSize)
          .attr('rx', 3)
          .attr('fill', cellFill)
          .attr('stroke', strokeColor)
          .attr('stroke-width', strokeWidth)
          .style('cursor', value > 0 ? 'pointer' : 'default')
          .on('mouseenter', function (event: MouseEvent) {
            if (value === 0) return
            d3.select(this)
              .attr('stroke', isTopForDoc ? 'rgba(250, 204, 21, 1)' : isTopForEntity ? 'rgba(34, 197, 94, 0.8)' : 'rgba(99, 102, 241, 0.8)')
              .attr('stroke-width', 2.5)
            const labels: string[] = []
            if (isTopForDoc) labels.push('<div style="color:#facc15;font-size:10px;margin-top:4px">&#9733; Concept dominant de ce document</div>')
            if (isTopForEntity) labels.push('<div style="color:#22c55e;font-size:10px;margin-top:2px">&#9733; Document principal pour ce concept</div>')
            tooltip
              .style('opacity', '1')
              .style('left', `${event.pageX + 12}px`)
              .style('top', `${event.pageY - 40}px`)
              .html(`
                <div style="font-weight:600;color:#f4f4f5;margin-bottom:4px">${entities[ei]}</div>
                <div style="color:#a1a1aa;font-size:11px;margin-bottom:2px">${docs[di].label}</div>
                <div style="color:#818cf8;font-weight:700;font-size:14px">${value} claims</div>
                ${labels.join('')}
              `)
          })
          .on('mousemove', function (event: MouseEvent) {
            tooltip
              .style('left', `${event.pageX + 12}px`)
              .style('top', `${event.pageY - 40}px`)
          })
          .on('mouseleave', function () {
            d3.select(this)
              .attr('stroke', strokeColor)
              .attr('stroke-width', strokeWidth)
            tooltip.style('opacity', '0')
          })

        // Show number in cell if value > 0
        if (value > 0) {
          g.append('text')
            .attr('x', marginLeft + di * (cellSize + cellGap) + cellSize / 2)
            .attr('y', marginTop + ei * (cellSize + cellGap) + cellSize / 2 + 4)
            .attr('text-anchor', 'middle')
            .attr('fill', value > data.max_value * 0.5 ? '#f4f4f5' : 'rgba(244,244,245,0.5)')
            .attr('font-size', '10px')
            .attr('font-weight', '600')
            .attr('pointer-events', 'none')
            .text(value)
        }
      }
    }

    // Legend
    const legendWidth = 200
    const legendHeight = 12
    const legendX = marginLeft
    const legendY = height - 8

    const legendScale = d3.scaleLinear().domain([0, data.max_value]).range([0, legendWidth])
    const legendAxis = d3.axisBottom(legendScale).ticks(5).tickSize(4)

    const defs = svg.append('defs')
    const gradient = defs.append('linearGradient').attr('id', 'heatmap-legend')
    gradient.append('stop').attr('offset', '0%').attr('stop-color', 'rgba(99, 102, 241, 0.05)')
    gradient.append('stop').attr('offset', '100%').attr('stop-color', 'rgba(99, 102, 241, 0.95)')

    g.append('rect')
      .attr('x', legendX)
      .attr('y', legendY - legendHeight)
      .attr('width', legendWidth)
      .attr('height', legendHeight)
      .attr('rx', 3)
      .attr('fill', 'url(#heatmap-legend)')

    g.append('g')
      .attr('transform', `translate(${legendX}, ${legendY})`)
      .call(legendAxis)
      .selectAll('text')
      .attr('fill', 'var(--text-muted)')
      .attr('font-size', '9px')

    g.selectAll('.domain, .tick line').attr('stroke', 'var(--text-muted)')

    g.append('text')
      .attr('x', legendX + legendWidth + 10)
      .attr('y', legendY - 2)
      .attr('fill', 'var(--text-muted)')
      .attr('font-size', '10px')
      .text('claims')

  }, [data])

  return (
    <Box position="relative">
      <Box overflowX="auto" pb={4} css={{ '&::-webkit-scrollbar': { height: '6px' }, '&::-webkit-scrollbar-thumb': { background: 'rgba(99,102,241,0.3)', borderRadius: '3px' } }}>
        <svg ref={svgRef} />
      </Box>
      <Box
        ref={tooltipRef}
        position="fixed"
        bg="rgba(10, 10, 15, 0.95)"
        border="1px solid rgba(99, 102, 241, 0.3)"
        borderRadius="lg"
        px={3}
        py={2}
        pointerEvents="none"
        opacity={0}
        transition="opacity 0.15s"
        zIndex={9999}
        backdropFilter="blur(8px)"
        boxShadow="0 4px 20px rgba(0,0,0,0.5)"
      />
    </Box>
  )
}

// ── Bubble Chart Component ─────────────────────────────────────────────

function BubbleChartView({ data }: { data: BubbleData }) {
  const svgRef = useRef<SVGSVGElement>(null)
  const tooltipRef = useRef<HTMLDivElement>(null)
  const router = useRouter()

  useEffect(() => {
    if (!svgRef.current || !data.bubbles.length) return

    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()

    const width = 900
    const height = 560
    const margin = { top: 40, right: 50, bottom: 60, left: 80 }
    const innerW = width - margin.left - margin.right
    const innerH = height - margin.top - margin.bottom

    svg.attr('width', width).attr('height', height)

    // Enrich bubbles with density (claims / docs)
    const enriched = data.bubbles.map(b => ({
      ...b,
      density: b.docs > 0 ? b.claims / b.docs : 0,
    }))

    // Scales
    const maxDocs = d3.max(enriched, d => d.docs) || 10
    const maxDensity = d3.max(enriched, d => d.density) || 50
    const maxClaims = d3.max(enriched, d => d.claims) || 100
    const maxContra = d3.max(enriched, d => d.contradictions) || 1
    const medianClaims = d3.median(enriched, d => d.claims) || 50

    const xScale = d3.scaleLinear().domain([0, maxDocs * 1.15]).range([0, innerW])
    const yScale = d3.scaleLinear().domain([0, maxDensity * 1.15]).range([innerH, 0])
    const rScale = d3.scaleSqrt().domain([0, maxClaims]).range([6, 45])

    // Color: 0 contradictions → indigo, >0 → orange → red
    const contraColorScale = (contradictions: number) => {
      if (contradictions === 0) return { fill: 'rgba(99, 102, 241, 0.3)', stroke: 'rgba(99, 102, 241, 0.6)' }
      const t = Math.min(contradictions / Math.max(maxContra, 1), 1)
      if (t < 0.5) return { fill: 'rgba(249, 115, 22, 0.35)', stroke: 'rgba(249, 115, 22, 0.7)' }
      return { fill: 'rgba(239, 68, 68, 0.4)', stroke: 'rgba(239, 68, 68, 0.75)' }
    }

    const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`)

    // Quadrant backgrounds
    const midX = innerW / 2
    const midY = innerH / 2

    const quadrants = [
      { x: 0, y: 0, w: midX, h: midY, label: 'Concepts concentres', color: 'rgba(168, 85, 247, 0.04)', textColor: 'rgba(168, 85, 247, 0.2)' },
      { x: midX, y: 0, w: midX, h: midY, label: 'Concepts dominants', color: 'rgba(34, 197, 94, 0.04)', textColor: 'rgba(34, 197, 94, 0.2)' },
      { x: 0, y: midY, w: midX, h: midY, label: 'Mineurs', color: 'rgba(113, 113, 122, 0.03)', textColor: 'rgba(113, 113, 122, 0.15)' },
      { x: midX, y: midY, w: midX, h: midY, label: 'Large couverture', color: 'rgba(59, 130, 246, 0.04)', textColor: 'rgba(59, 130, 246, 0.2)' },
    ]

    for (const q of quadrants) {
      g.append('rect')
        .attr('x', q.x).attr('y', q.y)
        .attr('width', q.w).attr('height', q.h)
        .attr('fill', q.color)
        .attr('rx', 4)

      g.append('text')
        .attr('x', q.x + q.w / 2)
        .attr('y', q.y + 24)
        .attr('text-anchor', 'middle')
        .attr('fill', q.textColor)
        .attr('font-size', '11px')
        .attr('font-weight', '600')
        .attr('font-family', 'var(--chakra-fonts-body)')
        .text(q.label)
    }

    // Grid lines
    const xAxis = d3.axisBottom(xScale).ticks(8).tickSize(-innerH)
    const yAxis = d3.axisLeft(yScale).ticks(6).tickSize(-innerW)

    g.append('g')
      .attr('transform', `translate(0,${innerH})`)
      .call(xAxis)
      .selectAll('text').attr('fill', 'var(--text-muted)').attr('font-size', '10px')

    g.append('g')
      .call(yAxis)
      .selectAll('text').attr('fill', 'var(--text-muted)').attr('font-size', '10px')

    g.selectAll('.tick line')
      .attr('stroke', 'rgba(255,255,255,0.05)')
      .attr('stroke-dasharray', '2,3')

    g.selectAll('.domain').attr('stroke', 'rgba(255,255,255,0.1)')

    // Axis labels
    svg.append('text')
      .attr('x', margin.left + innerW / 2)
      .attr('y', height - 10)
      .attr('text-anchor', 'middle')
      .attr('fill', 'var(--text-muted)')
      .attr('font-size', '12px')
      .text('Couverture (nombre de sources)')

    svg.append('text')
      .attr('transform', `translate(16, ${margin.top + innerH / 2}) rotate(-90)`)
      .attr('text-anchor', 'middle')
      .attr('fill', 'var(--text-muted)')
      .attr('font-size', '12px')
      .text('Densite (claims par source)')

    // Tooltip
    const tooltip = d3.select(tooltipRef.current)

    // Sort bubbles: larger drawn first (smaller on top)
    const sortedBubbles = [...enriched].sort((a, b) => b.claims - a.claims)

    // Bubbles
    const bubbleGroups = g.selectAll('.bubble-group')
      .data(sortedBubbles)
      .enter()
      .append('g')
      .attr('class', 'bubble-group')
      .style('cursor', (d: any) => d.has_article ? 'pointer' : 'default')
      .on('click', (_event: MouseEvent, d: any) => {
        if (d.has_article && d.slug) {
          router.push(`/wiki/${d.slug}`)
        }
      })

    bubbleGroups.append('circle')
      .attr('cx', (d: any) => xScale(d.docs))
      .attr('cy', (d: any) => yScale(d.density))
      .attr('r', (d: any) => rScale(d.claims))
      .attr('fill', (d: any) => contraColorScale(d.contradictions).fill)
      .attr('stroke', (d: any) => contraColorScale(d.contradictions).stroke)
      .attr('stroke-width', 1.5)
      .on('mouseenter', function (event: MouseEvent, d: any) {
        d3.select(this)
          .transition().duration(150)
          .attr('stroke-width', 3)
          .attr('fill-opacity', 0.8)
        tooltip
          .style('opacity', '1')
          .style('left', `${event.pageX + 14}px`)
          .style('top', `${event.pageY - 60}px`)
          .html(`
            <div style="font-weight:700;color:#f4f4f5;margin-bottom:6px;font-size:14px">${d.name}</div>
            <div style="display:grid;grid-template-columns:auto 1fr;gap:4px 12px;font-size:12px">
              <span style="color:#818cf8;font-weight:600">${d.claims}</span>
              <span style="color:#a1a1aa">claims</span>
              <span style="color:#22c55e;font-weight:600">${d.docs}</span>
              <span style="color:#a1a1aa">sources</span>
              <span style="color:#a78bfa;font-weight:600">${d.density.toFixed(1)}</span>
              <span style="color:#a1a1aa">claims/source</span>
              <span style="color:${d.contradictions > 0 ? '#f59e0b' : '#71717a'};font-weight:700;font-size:13px">${d.contradictions}</span>
              <span style="color:${d.contradictions > 0 ? '#f59e0b' : '#a1a1aa'}">${d.contradictions > 0 ? 'contradictions !' : 'contradictions'}</span>
            </div>
            ${d.has_article ? '<div style="margin-top:8px;color:#818cf8;font-size:11px">Cliquer pour voir l\'article</div>' : ''}
          `)
      })
      .on('mousemove', function (event: MouseEvent) {
        tooltip
          .style('left', `${event.pageX + 14}px`)
          .style('top', `${event.pageY - 60}px`)
      })
      .on('mouseleave', function (_event: MouseEvent, d: any) {
        d3.select(this)
          .transition().duration(150)
          .attr('stroke-width', 1.5)
          .attr('fill-opacity', 1)
        tooltip.style('opacity', '0')
      })

    // Contradiction glow effect for bubbles with contradictions
    bubbleGroups
      .filter((d: any) => d.contradictions > 0)
      .insert('circle', ':first-child')
      .attr('cx', (d: any) => xScale(d.docs))
      .attr('cy', (d: any) => yScale(d.density))
      .attr('r', (d: any) => rScale(d.claims) + 4)
      .attr('fill', 'none')
      .attr('stroke', (d: any) => d.contradictions >= maxContra * 0.5 ? 'rgba(239, 68, 68, 0.3)' : 'rgba(249, 115, 22, 0.25)')
      .attr('stroke-width', 2)
      .attr('stroke-dasharray', '4,3')
      .attr('pointer-events', 'none')

    // Labels for large bubbles
    bubbleGroups
      .filter((d: any) => d.claims >= medianClaims)
      .append('text')
      .attr('x', (d: any) => xScale(d.docs))
      .attr('y', (d: any) => yScale(d.density) + 4)
      .attr('text-anchor', 'middle')
      .attr('fill', 'var(--text-primary)')
      .attr('font-size', (d: any) => d.claims > medianClaims * 3 ? '11px' : '9px')
      .attr('font-weight', '600')
      .attr('pointer-events', 'none')
      .text((d: any) => d.name.length > 18 ? d.name.slice(0, 15) + '...' : d.name)

  }, [data, router])

  return (
    <Box position="relative">
      <Box overflowX="auto" pb={4} css={{ '&::-webkit-scrollbar': { height: '6px' }, '&::-webkit-scrollbar-thumb': { background: 'rgba(99,102,241,0.3)', borderRadius: '3px' } }}>
        <svg ref={svgRef} style={{ minWidth: '900px' }} />
      </Box>
      {/* Legend */}
      <HStack spacing={6} mt={2} px={4} justify="center" flexWrap="wrap">
        <HStack spacing={2}>
          <Box w="12px" h="12px" borderRadius="full" bg="rgba(99, 102, 241, 0.4)" border="1.5px solid rgba(99, 102, 241, 0.7)" />
          <Text fontSize="xs" color="var(--text-muted)">Aucune contradiction</Text>
        </HStack>
        <HStack spacing={2}>
          <Box w="12px" h="12px" borderRadius="full" bg="rgba(249, 115, 22, 0.4)" border="1.5px solid rgba(249, 115, 22, 0.7)" />
          <Text fontSize="xs" color="var(--text-muted)">Contradictions moderees</Text>
        </HStack>
        <HStack spacing={2}>
          <Box w="12px" h="12px" borderRadius="full" bg="rgba(239, 68, 68, 0.4)" border="1.5px solid rgba(239, 68, 68, 0.75)" />
          <Text fontSize="xs" color="var(--text-muted)">Contradictions elevees</Text>
        </HStack>
        <Text fontSize="xs" color="var(--text-muted)">Taille = nombre de claims</Text>
      </HStack>
      <Box
        ref={tooltipRef}
        position="fixed"
        bg="rgba(10, 10, 15, 0.95)"
        border="1px solid rgba(99, 102, 241, 0.3)"
        borderRadius="lg"
        px={4}
        py={3}
        pointerEvents="none"
        opacity={0}
        transition="opacity 0.15s"
        zIndex={9999}
        backdropFilter="blur(8px)"
        boxShadow="0 8px 32px rgba(0,0,0,0.6)"
        minW="180px"
      />
    </Box>
  )
}

// ── Main Page ──────────────────────────────────────────────────────────

export default function CorpusIntelligencePage() {
  const [heatmapData, setHeatmapData] = useState<HeatmapData | null>(null)
  const [bubbleData, setBubbleData] = useState<BubbleData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState(0)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [heatRes, bubbleRes] = await Promise.all([
        fetch(`${API_BASE_URL}/api/corpus-intelligence/heatmap`, { headers: getAuthHeaders() }),
        fetch(`${API_BASE_URL}/api/corpus-intelligence/bubble`, { headers: getAuthHeaders() }),
      ])

      if (!heatRes.ok || !bubbleRes.ok) {
        throw new Error('Erreur lors du chargement des donnees')
      }

      const [heatJson, bubbleJson] = await Promise.all([heatRes.json(), bubbleRes.json()])
      setHeatmapData(heatJson)
      setBubbleData(bubbleJson)
    } catch (err: any) {
      setError(err.message || 'Erreur inconnue')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  if (loading) {
    return (
      <VStack py={20} spacing={4}>
        <Spinner size="lg" color="brand.400" thickness="3px" />
        <Text color="var(--text-muted)" fontSize="sm">Analyse du corpus en cours...</Text>
      </VStack>
    )
  }

  if (error) {
    return (
      <Box bg="rgba(239, 68, 68, 0.08)" border="1px solid rgba(239, 68, 68, 0.2)" borderRadius="xl" p={6} mx={4}>
        <Text color="red.400" fontWeight="600">Erreur</Text>
        <Text color="var(--text-muted)" fontSize="sm" mt={1}>{error}</Text>
      </Box>
    )
  }

  return (
    <Box>
      {/* Header */}
      <VStack align="start" spacing={1} mb={6}>
        <Text fontSize="xl" fontWeight="700" color="var(--text-primary)">
          Corpus Intelligence
        </Text>
        <Text fontSize="sm" color="var(--text-muted)">
          Analyse visuelle de la couverture et des tensions du corpus
        </Text>
      </VStack>

      {/* Stats badges */}
      {bubbleData && heatmapData && (
        <HStack spacing={4} mb={6} flexWrap="wrap">
          <Badge px={3} py={1} borderRadius="md" bg="rgba(99, 102, 241, 0.1)" color="brand.300" fontSize="xs">
            {heatmapData.entities.length} concepts
          </Badge>
          <Badge px={3} py={1} borderRadius="md" bg="rgba(34, 197, 94, 0.1)" color="green.300" fontSize="xs">
            {heatmapData.documents.length} documents
          </Badge>
          <Badge px={3} py={1} borderRadius="md" bg="rgba(249, 115, 22, 0.1)" color="orange.300" fontSize="xs">
            {bubbleData.bubbles.filter(b => b.contradictions > 0).length} concepts en tension
          </Badge>
          <Badge px={3} py={1} borderRadius="md" bg="rgba(168, 85, 247, 0.1)" color="purple.300" fontSize="xs">
            {bubbleData.bubbles.filter(b => b.has_article).length} avec article
          </Badge>
        </HStack>
      )}

      {/* Tabs */}
      <Tabs
        index={activeTab}
        onChange={setActiveTab}
        variant="soft-rounded"
        colorScheme="brand"
      >
        <TabList mb={6} gap={2}>
          <Tab
            fontSize="sm"
            fontWeight="600"
            color="var(--text-muted)"
            _selected={{ color: 'white', bg: 'rgba(99, 102, 241, 0.2)', borderColor: 'brand.500' }}
            borderWidth="1px"
            borderColor="transparent"
          >
            <Icon as={FiGrid} mr={2} />
            Couverture du corpus
          </Tab>
          <Tab
            fontSize="sm"
            fontWeight="600"
            color="var(--text-muted)"
            _selected={{ color: 'white', bg: 'rgba(99, 102, 241, 0.2)', borderColor: 'brand.500' }}
            borderWidth="1px"
            borderColor="transparent"
          >
            <Icon as={FiTarget} mr={2} />
            Risques et opportunites
          </Tab>
        </TabList>

        <TabPanels>
          <TabPanel p={0}>
            <Box
              bg="var(--bg-secondary)"
              borderRadius="xl"
              borderWidth="1px"
              borderColor="var(--border-default)"
              p={4}
              overflow="hidden"
            >
              <Text fontSize="xs" color="var(--text-muted)" mb={4} fontWeight="500">
                Densite de claims par concept et document source — les zones chaudes indiquent une couverture dense.
                Les cellules <Text as="span" color="green.400" fontWeight="600">vertes</Text> indiquent le document principal pour chaque concept.
                Les cellules a <Text as="span" color="yellow.400" fontWeight="600">bordure doree</Text> indiquent le concept dominant de chaque document.
              </Text>
              {heatmapData && <HeatmapView data={heatmapData} />}
            </Box>
          </TabPanel>

          <TabPanel p={0}>
            <Box
              bg="var(--bg-secondary)"
              borderRadius="xl"
              borderWidth="1px"
              borderColor="var(--border-default)"
              p={4}
              overflow="hidden"
            >
              <Text fontSize="xs" color="var(--text-muted)" mb={4} fontWeight="500">
                Chaque bulle represente un concept — X = nombre de sources, Y = densite (claims/source), taille = importance, couleur = contradictions
              </Text>
              {bubbleData && <BubbleChartView data={bubbleData} />}
            </Box>
          </TabPanel>
        </TabPanels>
      </Tabs>
    </Box>
  )
}
