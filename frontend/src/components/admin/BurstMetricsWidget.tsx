'use client'

/**
 * P5.3 — Cockpit widget burst local.
 *
 * Affiche en temps réel les métriques vLLM (throughput tok/s, KV cache, prefix cache,
 * requêtes en queue). Poll /api/burst/vllm_metrics chaque 2 secondes.
 *
 * Theme-aware via CSS variables.
 */

import { useEffect, useState } from 'react'
import {
  Box,
  HStack,
  VStack,
  Text,
  Stat,
  StatLabel,
  StatNumber,
  StatHelpText,
  Progress,
  Badge,
  Tooltip,
  Heading,
} from '@chakra-ui/react'

type VllmMetrics = {
  available: boolean
  vllm_url?: string | null
  model?: string | null
  prompt_throughput_toks_per_s: number
  generation_throughput_toks_per_s: number
  total_throughput_toks_per_s: number
  gpu_cache_usage_perc: number
  cpu_cache_usage_perc: number
  gpu_prefix_cache_hit_rate: number
  num_requests_running: number
  num_requests_waiting: number
  num_requests_swapped: number
  error?: string | null
}

const POLL_INTERVAL_MS = 2000

export function BurstMetricsWidget() {
  const [metrics, setMetrics] = useState<VllmMetrics | null>(null)
  const [history, setHistory] = useState<{ ts: number; total_tps: number }[]>([])

  useEffect(() => {
    let cancelled = false

    async function poll() {
      try {
        const res = await fetch('/api/burst/vllm_metrics')
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`)
        }
        const data: VllmMetrics = await res.json()
        if (cancelled) return
        setMetrics(data)
        if (data.available) {
          setHistory((h) => {
            const next = [...h, { ts: Date.now(), total_tps: data.total_throughput_toks_per_s }]
            // Garder 60 derniers points (2 minutes à 2s/point)
            return next.slice(-60)
          })
        }
      } catch (exc) {
        if (cancelled) return
        setMetrics({
          available: false,
          prompt_throughput_toks_per_s: 0,
          generation_throughput_toks_per_s: 0,
          total_throughput_toks_per_s: 0,
          gpu_cache_usage_perc: 0,
          cpu_cache_usage_perc: 0,
          gpu_prefix_cache_hit_rate: 0,
          num_requests_running: 0,
          num_requests_waiting: 0,
          num_requests_swapped: 0,
          error: exc instanceof Error ? exc.message : 'unknown',
        })
      }
    }

    poll()
    const interval = setInterval(poll, POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [])

  if (!metrics) {
    return (
      <Box p={4} borderWidth="1px" borderColor="var(--border)" rounded="md" bg="var(--bg-surface)">
        <Text fontSize="sm" color="var(--fg-muted)">Loading vLLM metrics…</Text>
      </Box>
    )
  }

  if (!metrics.available) {
    return (
      <Box p={4} borderWidth="1px" borderColor="orange.400" rounded="md" bg="var(--bg-surface)">
        <HStack>
          <Badge colorScheme="orange">vLLM offline</Badge>
          <Text fontSize="sm" color="var(--fg-muted)">{metrics.error}</Text>
        </HStack>
      </Box>
    )
  }

  const cacheColor = metrics.gpu_cache_usage_perc > 80 ? 'red' : metrics.gpu_cache_usage_perc > 50 ? 'yellow' : 'green'
  const totalActive = metrics.num_requests_running + metrics.num_requests_waiting

  // Mini sparkline ASCII pour la courbe throughput
  const maxTps = Math.max(...history.map((h) => h.total_tps), 1)
  const sparkChars = '▁▂▃▄▅▆▇█'
  const sparkline = history
    .slice(-30)
    .map((h) => sparkChars[Math.min(7, Math.floor((h.total_tps / maxTps) * 7))])
    .join('')

  return (
    <Box p={4} borderWidth="1px" borderColor="var(--border)" rounded="md" bg="var(--bg-surface)">
      <HStack justify="space-between" mb={3}>
        <Heading size="sm" color="var(--accent-base)">vLLM live</Heading>
        <HStack>
          <Badge colorScheme="green">online</Badge>
          {metrics.model && (
            <Tooltip label={metrics.vllm_url || ''}>
              <Badge variant="outline" fontSize="xs">{metrics.model.split('/').pop()}</Badge>
            </Tooltip>
          )}
        </HStack>
      </HStack>

      <HStack align="flex-start" spacing={6} flexWrap="wrap">
        {/* Throughput */}
        <Stat minW="160px">
          <StatLabel fontSize="xs" color="var(--fg-muted)">Throughput</StatLabel>
          <StatNumber fontSize="lg">{metrics.total_throughput_toks_per_s.toFixed(1)} tok/s</StatNumber>
          <StatHelpText fontSize="xs">
            prompt {metrics.prompt_throughput_toks_per_s.toFixed(1)} · gen {metrics.generation_throughput_toks_per_s.toFixed(1)}
          </StatHelpText>
        </Stat>

        {/* Cache */}
        <Stat minW="160px">
          <StatLabel fontSize="xs" color="var(--fg-muted)">GPU KV cache</StatLabel>
          <StatNumber fontSize="lg">{metrics.gpu_cache_usage_perc.toFixed(1)}%</StatNumber>
          <Progress value={metrics.gpu_cache_usage_perc} size="xs" colorScheme={cacheColor} mt={1} />
        </Stat>

        <Stat minW="160px">
          <StatLabel fontSize="xs" color="var(--fg-muted)">Prefix cache hit</StatLabel>
          <StatNumber fontSize="lg">{metrics.gpu_prefix_cache_hit_rate.toFixed(1)}%</StatNumber>
          <StatHelpText fontSize="xs">
            CPU cache {metrics.cpu_cache_usage_perc.toFixed(1)}%
          </StatHelpText>
        </Stat>

        {/* Queue */}
        <Stat minW="160px">
          <StatLabel fontSize="xs" color="var(--fg-muted)">Queue</StatLabel>
          <StatNumber fontSize="lg">{totalActive}</StatNumber>
          <StatHelpText fontSize="xs">
            running {metrics.num_requests_running} · wait {metrics.num_requests_waiting}
            {metrics.num_requests_swapped > 0 && ` · swap ${metrics.num_requests_swapped}`}
          </StatHelpText>
        </Stat>

        {/* Sparkline throughput */}
        {history.length > 5 && (
          <Box minW="240px">
            <Text fontSize="xs" color="var(--fg-muted)">Last 60s throughput</Text>
            <Text fontFamily="mono" fontSize="2xl" letterSpacing="-0.05em" color="var(--accent-base)">
              {sparkline}
            </Text>
            <Text fontSize="xs" color="var(--fg-muted)">peak {maxTps.toFixed(1)} tok/s</Text>
          </Box>
        )}
      </HStack>
    </Box>
  )
}
