'use client'

/**
 * KG Health Cockpit — diagnostic intrinseque de la qualite du Knowledge Graph.
 *
 * Remplace l'ancien "Audit du Corpus" qui melangeait metriques editoriales
 * (articles a ecrire, blind spots) et sante structurelle. Cette page se
 * concentre exclusivement sur la sante du KG :
 *
 *  - Score global 0-100 pondere sur 4 familles
 *  - Provenance (tracabilite, diversite multi-source, canonicalisation)
 *  - Structure (linkage claim-facet, orphelins, resolution de sujet)
 *  - Distribution (entropie, richesse, absence de hub anormal)
 *  - Coherence (contradictions, composante geante, fraicheur Perspective)
 *
 * Actionables en bas de page : top docs mal extraits, entites dominantes,
 * fragmentation, couche Perspective.
 */

import { useState, useEffect, useCallback } from 'react'
import {
  Box,
  Text,
  VStack,
  HStack,
  SimpleGrid,
  Spinner,
  Icon,
} from '@chakra-ui/react'
import { FiActivity } from 'react-icons/fi'
import { HealthScoreCard } from '@/components/kg-health/HealthScoreCard'
import { FamilyCard } from '@/components/kg-health/FamilyCard'
import { ActionablesPanel } from '@/components/kg-health/ActionablesPanel'
import { DrilldownModal } from '@/components/kg-health/DrilldownModal'
import { KGHealthScoreResponse } from '@/components/kg-health/types'

const API_BASE_URL =
  typeof window !== 'undefined'
    ? process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'
    : 'http://localhost:8000'

const getAuthHeaders = () => ({
  'Content-Type': 'application/json',
  Authorization: `Bearer ${localStorage.getItem('auth_token') || ''}`,
})

export default function KGHealthPage() {
  const [data, setData] = useState<KGHealthScoreResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [drilldownKey, setDrilldownKey] = useState<string | null>(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API_BASE_URL}/api/kg-health/score`, {
        headers: getAuthHeaders(),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = (await res.json()) as KGHealthScoreResponse
      setData(json)
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
        <Text color="var(--text-muted)" fontSize="sm">
          Calcul du KG Health en cours...
        </Text>
      </VStack>
    )
  }

  if (error || !data) {
    return (
      <Box
        bg="rgba(239, 68, 68, 0.08)"
        border="1px solid rgba(239, 68, 68, 0.2)"
        borderRadius="xl"
        p={6}
      >
        <Text color="red.400">{error || 'Erreur inconnue'}</Text>
      </Box>
    )
  }

  return (
    <Box>
      {/* Header */}
      <VStack align="start" spacing={1} mb={6}>
        <HStack spacing={3}>
          <Icon as={FiActivity} color="brand.400" boxSize={5} />
          <Text fontSize="xl" fontWeight="700" color="var(--text-primary)">
            KG Health Cockpit
          </Text>
        </HStack>
        <Text fontSize="sm" color="var(--text-muted)">
          Diagnostic intrinseque de la qualite du Knowledge Graph (independant du corpus de questions)
        </Text>
      </VStack>

      {/* Score global + summary */}
      <HealthScoreCard data={data} />

      {/* 4 families */}
      <SimpleGrid columns={{ base: 1, xl: 2 }} spacing={4}>
        {data.families.map((family) => (
          <FamilyCard
            key={family.name}
            family={family}
            onDrilldown={(key) => setDrilldownKey(key)}
          />
        ))}
      </SimpleGrid>

      {/* Actionables */}
      <ActionablesPanel
        data={data.actionables}
        onDrilldown={(key) => setDrilldownKey(key)}
      />

      {/* Drilldown modal */}
      <DrilldownModal
        isOpen={drilldownKey !== null}
        onClose={() => setDrilldownKey(null)}
        drilldownKey={drilldownKey}
      />
    </Box>
  )
}
