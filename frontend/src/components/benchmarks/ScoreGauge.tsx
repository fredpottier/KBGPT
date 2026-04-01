'use client'

import { useEffect, useRef } from 'react'
import { Box, Text, VStack } from '@chakra-ui/react'
import * as d3 from 'd3'

interface ScoreGaugeProps {
  value: number       // 0.0 - 1.0
  label: string
  color?: string      // accent color
  size?: number       // diameter in px
  target?: number     // target value (0.0-1.0), shows a tick
}

export function ScoreGauge({ value, label, color = '#5B7FFF', size = 120, target }: ScoreGaugeProps) {
  const svgRef = useRef<SVGSVGElement>(null)

  const pct = Math.round(value * 100)
  const statusColor = pct >= 70 ? '#22c55e' : pct >= 50 ? '#eab308' : '#ef4444'

  useEffect(() => {
    if (!svgRef.current) return
    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()

    const cx = size / 2
    const cy = size / 2
    const radius = size / 2 - 12
    const strokeWidth = 10
    const startAngle = -Math.PI * 0.75
    const endAngle = Math.PI * 0.75
    const totalAngle = endAngle - startAngle

    const arc = d3.arc<any>()
      .innerRadius(radius - strokeWidth / 2)
      .outerRadius(radius + strokeWidth / 2)
      .startAngle(startAngle)
      .cornerRadius(strokeWidth / 2)

    const g = svg.append('g')
      .attr('transform', `translate(${cx}, ${cy})`)

    // Background arc
    g.append('path')
      .datum({ endAngle })
      .attr('d', arc as any)
      .attr('fill', '#1e1e3a')

    // Value arc (animated)
    const valueAngle = startAngle + totalAngle * Math.min(value, 1)
    const valueArc = g.append('path')
      .datum({ endAngle: startAngle })
      .attr('fill', color)

    valueArc.transition()
      .duration(800)
      .ease(d3.easeCubicOut)
      .attrTween('d', function (d: any) {
        const interpolate = d3.interpolate(startAngle, valueAngle)
        return function (t: number) {
          d.endAngle = interpolate(t)
          return (arc as any)(d)
        }
      })

    // Target tick
    if (target !== undefined) {
      const targetAngle = startAngle + totalAngle * target
      const tickInner = radius - strokeWidth - 4
      const tickOuter = radius + strokeWidth + 4
      g.append('line')
        .attr('x1', tickInner * Math.cos(targetAngle - Math.PI / 2))
        .attr('y1', tickInner * Math.sin(targetAngle - Math.PI / 2))
        .attr('x2', tickOuter * Math.cos(targetAngle - Math.PI / 2))
        .attr('y2', tickOuter * Math.sin(targetAngle - Math.PI / 2))
        .attr('stroke', '#64748b')
        .attr('stroke-width', 2)
    }

    // Center value
    g.append('text')
      .attr('text-anchor', 'middle')
      .attr('dy', '0.1em')
      .attr('fill', statusColor)
      .attr('font-family', "'Fira Code', monospace")
      .attr('font-size', `${size * 0.28}px`)
      .attr('font-weight', '700')
      .text(pct)

  }, [value, color, size, target, pct, statusColor])

  return (
    <VStack spacing={1}>
      <Box>
        <svg ref={svgRef} width={size} height={size * 0.75} />
      </Box>
      <Text
        fontSize="xs"
        fontWeight="600"
        color="var(--text-secondary, #94a3b8)"
        fontFamily="'Fira Sans', sans-serif"
        textAlign="center"
      >
        {label}
      </Text>
    </VStack>
  )
}
