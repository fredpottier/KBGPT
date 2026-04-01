'use client'

import { useEffect, useRef } from 'react'
import { Box } from '@chakra-ui/react'
import * as d3 from 'd3'

interface RadarChartProps {
  data: { label: string; value: number }[]   // 0.0 - 1.0
  size?: number
  color?: string
}

export function RadarChart({ data, size = 240, color = '#f97316' }: RadarChartProps) {
  const svgRef = useRef<SVGSVGElement>(null)

  useEffect(() => {
    if (!svgRef.current || data.length === 0) return
    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()

    const cx = size / 2
    const cy = size / 2
    const radius = size / 2 - 40
    const n = data.length
    const angleSlice = (Math.PI * 2) / n

    const g = svg.append('g').attr('transform', `translate(${cx}, ${cy})`)

    // Grid circles (3 levels: 0.33, 0.66, 1.0)
    for (const level of [0.33, 0.66, 1.0]) {
      g.append('circle')
        .attr('r', radius * level)
        .attr('fill', 'none')
        .attr('stroke', '#1e1e3a')
        .attr('stroke-width', 1)
    }

    // Grid lines (axes)
    for (let i = 0; i < n; i++) {
      const angle = angleSlice * i - Math.PI / 2
      g.append('line')
        .attr('x1', 0).attr('y1', 0)
        .attr('x2', radius * Math.cos(angle))
        .attr('y2', radius * Math.sin(angle))
        .attr('stroke', '#1e1e3a')
        .attr('stroke-width', 1)
    }

    // Data polygon
    const points = data.map((d, i) => {
      const angle = angleSlice * i - Math.PI / 2
      const r = radius * Math.min(d.value, 1)
      return [r * Math.cos(angle), r * Math.sin(angle)] as [number, number]
    })

    // Fill
    g.append('polygon')
      .attr('points', points.map(p => p.join(',')).join(' '))
      .attr('fill', color)
      .attr('fill-opacity', 0.15)
      .attr('stroke', color)
      .attr('stroke-width', 2)

    // Data dots
    points.forEach((p, i) => {
      g.append('circle')
        .attr('cx', p[0])
        .attr('cy', p[1])
        .attr('r', 4)
        .attr('fill', color)
        .attr('stroke', '#0a0a1a')
        .attr('stroke-width', 2)
    })

    // Labels
    data.forEach((d, i) => {
      const angle = angleSlice * i - Math.PI / 2
      const labelRadius = radius + 24
      const x = labelRadius * Math.cos(angle)
      const y = labelRadius * Math.sin(angle)

      const pct = Math.round(d.value * 100)
      const statusColor = pct >= 70 ? '#22c55e' : pct >= 50 ? '#eab308' : '#ef4444'

      g.append('text')
        .attr('x', x)
        .attr('y', y)
        .attr('text-anchor', 'middle')
        .attr('dominant-baseline', 'central')
        .attr('fill', '#94a3b8')
        .attr('font-family', "'Fira Sans', sans-serif")
        .attr('font-size', '10px')
        .text(d.label.replace(/_/g, ' '))

      g.append('text')
        .attr('x', x)
        .attr('y', y + 12)
        .attr('text-anchor', 'middle')
        .attr('fill', statusColor)
        .attr('font-family', "'Fira Code', monospace")
        .attr('font-size', '11px')
        .attr('font-weight', '700')
        .text(`${pct}%`)
    })

  }, [data, size, color])

  return (
    <Box>
      <svg ref={svgRef} width={size} height={size} />
    </Box>
  )
}
