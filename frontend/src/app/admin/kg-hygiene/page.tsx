'use client'

/**
 * OSMOSE KG Hygiene — Admin page for Knowledge Graph cleanup and rollback.
 *
 * Features:
 * - Run Layer 1 (auto, high precision) and Layer 2 (LLM-driven, with PROPOSED)
 * - View/filter/sort all hygiene actions
 * - Approve/Reject PROPOSED actions
 * - Rollback APPLIED actions (one-click)
 * - Batch rollback
 * - Stats dashboard
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Box,
  Text,
  VStack,
  HStack,
  Button,
  useToast,
  Spinner,
  Center,
  Icon,
  Badge,
  Select,
  SimpleGrid,
  Table,
  Thead,
  Tbody,
  Tr,
  Th,
  Td,
  Checkbox,
  Code,
  Collapse,
  IconButton,
  Tooltip,
} from '@chakra-ui/react'
import { motion } from 'framer-motion'
import {
  FiFilter,
  FiPlay,
  FiEye,
  FiRotateCcw,
  FiCheck,
  FiX,
  FiChevronDown,
  FiChevronUp,
  FiAlertTriangle,
  FiActivity,
  FiTrash2,
  FiLayers,
  FiInfo,
} from 'react-icons/fi'
import { api } from '@/lib/api'

const MotionBox = motion(Box)

// Types
interface HygieneAction {
  action_id: string
  action_type: string
  target_node_id: string
  target_node_type: string
  before_state: Record<string, unknown>
  after_state: Record<string, unknown>
  layer: number
  confidence: number
  reason: string
  rule_name: string
  batch_id: string
  scope: string
  status: string
  decision_source: string
  applied_at: string | null
  rolled_back_at: string | null
  tenant_id: string
}

interface HygieneStats {
  total: number
  by_status: Record<string, number>
  by_layer: Record<string, number>
  by_type: Record<string, number>
}

// Status badge colors
const statusColor: Record<string, string> = {
  APPLIED: 'green',
  PROPOSED: 'orange',
  ROLLED_BACK: 'yellow',
  REJECTED: 'gray',
}

const typeColor: Record<string, string> = {
  SUPPRESS_ENTITY: 'red',
  HARD_DELETE_ENTITY: 'red',
  MERGE_CANONICAL: 'purple',
  SUPPRESS_AXIS: 'blue',
  MERGE_AXIS: 'blue',
}

// Stat Card
const StatCard = ({ title, value, color = 'brand' }: { title: string; value: number; color?: string }) => (
  <Box
    bg="bg.secondary"
    border="1px solid"
    borderColor="border.default"
    rounded="xl"
    p={4}
    textAlign="center"
  >
    <Text fontSize="xs" color="text.muted" textTransform="uppercase" letterSpacing="wide">
      {title}
    </Text>
    <Text fontSize="2xl" fontWeight="bold" color={`${color}.400`}>
      {value}
    </Text>
  </Box>
)

export default function KGHygienePage() {
  const toast = useToast()
  const [stats, setStats] = useState<HygieneStats | null>(null)
  const [actions, setActions] = useState<HygieneAction[]>([])
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(0)
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [layerFilter, setLayerFilter] = useState<string>('')
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [runProgress, setRunProgress] = useState<string | null>(null)
  const [isDryRunView, setIsDryRunView] = useState(false)
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const pageSize = 25

  // Load data
  const loadData = useCallback(async () => {
    setLoading(true)
    setIsDryRunView(false)
    try {
      const [statsRes, actionsRes] = await Promise.all([
        api.hygiene.stats(),
        api.hygiene.actions({
          status: statusFilter || undefined,
          layer: layerFilter ? parseInt(layerFilter) : undefined,
          limit: pageSize,
          offset: page * pageSize,
        }),
      ])

      if (statsRes.success) setStats(statsRes.data as HygieneStats)
      if (actionsRes.success) {
        const data = actionsRes.data as { actions: HygieneAction[]; total: number }
        setActions(data.actions || [])
        setTotal(data.total || 0)
      }
    } catch (error) {
      console.error('Error loading hygiene data:', error)
    } finally {
      setLoading(false)
    }
  }, [statusFilter, layerFilter, page])

  useEffect(() => {
    loadData()
  }, [loadData])

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current)
    }
  }, [])

  // Poll run status
  const pollRunStatus = useCallback(async (batchId: string, dryRun: boolean) => {
    try {
      const res = await api.hygiene.runStatus(batchId)
      if (!res.success) return

      const data = res.data as {
        status: string
        total_actions: number
        applied: number
        proposed: number
        actions?: HygieneAction[]
        errors?: string[]
        progress?: string
      }

      if (data.status === 'running') {
        setRunProgress(data.progress || 'En cours...')
        return // Continue polling
      }

      // Terminé — arrêter le polling
      if (pollingRef.current) {
        clearInterval(pollingRef.current)
        pollingRef.current = null
      }
      setRunning(false)
      setRunProgress(null)

      if (data.status === 'completed') {
        const desc = dryRun
          ? `${data.total_actions} problemes detectes (preview, aucune modification)`
          : `${data.total_actions} actions — ${data.applied} appliquees, ${data.proposed} en attente`
        toast({
          title: dryRun ? 'Dry Run termine' : 'Run termine',
          description: data.total_actions === 0 ? 'Aucun probleme detecte' : desc,
          status: data.total_actions === 0 ? 'info' : 'success',
          duration: 5000,
          position: 'top',
        })

        if (dryRun && data.actions && data.actions.length > 0) {
          setActions(data.actions)
          setTotal(data.total_actions)
          setIsDryRunView(true)
        } else {
          setIsDryRunView(false)
          loadData()
        }
      } else {
        toast({
          title: 'Run echoue',
          description: (data.errors || []).join(', ') || 'Erreur inconnue',
          status: 'error',
          duration: 5000,
          position: 'top',
        })
      }
    } catch (error) {
      console.error('Poll error:', error)
    }
  }, [loadData, toast])

  // Run hygiene (background + polling)
  const handleRun = async (layers: number[], dryRun: boolean) => {
    setRunning(true)
    setRunProgress('Lancement...')
    try {
      const res = await api.hygiene.run({ layers, dry_run: dryRun })
      if (res.success) {
        const data = res.data as { batch_id: string; status: string }
        // Start polling
        if (pollingRef.current) clearInterval(pollingRef.current)
        pollingRef.current = setInterval(() => pollRunStatus(data.batch_id, dryRun), 3000)
      } else {
        setRunning(false)
        setRunProgress(null)
        toast({ title: 'Erreur', description: 'Impossible de lancer le run', status: 'error', duration: 5000, position: 'top' })
      }
    } catch (error: unknown) {
      setRunning(false)
      setRunProgress(null)
      const msg = error instanceof Error ? error.message : 'Erreur inconnue'
      toast({ title: 'Erreur', description: msg, status: 'error', duration: 5000, position: 'top' })
    }
  }

  // Action handlers
  const handleRollback = async (actionId: string) => {
    try {
      const res = await api.hygiene.rollback(actionId)
      if (res.success) {
        toast({ title: 'Rollback effectue', status: 'success', duration: 3000, position: 'top' })
        loadData()
      }
    } catch (error: unknown) {
      const msg = error instanceof Error ? error.message : 'Erreur'
      toast({ title: 'Erreur rollback', description: msg, status: 'error', duration: 5000, position: 'top' })
    }
  }

  const handleApprove = async (actionId: string) => {
    try {
      const res = await api.hygiene.approve(actionId)
      if (res.data?.success) {
        toast({ title: 'Action approuvée et appliquée', status: 'success', duration: 3000, position: 'top' })
        loadData()
      } else {
        toast({ title: 'Approbation échouée', description: res.data?.detail || 'Erreur inconnue', status: 'warning', duration: 5000, position: 'top' })
      }
    } catch (error: unknown) {
      const msg = error instanceof Error ? error.message : 'Erreur'
      toast({ title: 'Erreur approbation', description: msg, status: 'error', duration: 5000, position: 'top' })
    }
  }

  const handleReject = async (actionId: string) => {
    try {
      const res = await api.hygiene.reject(actionId)
      if (res.data?.success) {
        toast({ title: 'Action rejetée', status: 'info', duration: 3000, position: 'top' })
        loadData()
      }
    } catch (error: unknown) {
      const msg = error instanceof Error ? error.message : 'Erreur'
      toast({ title: 'Erreur rejet', description: msg, status: 'error', duration: 5000, position: 'top' })
    }
  }

  const handleBulkApprove = async () => {
    if (selectedIds.size === 0) return
    let success = 0
    let errors = 0
    for (const actionId of selectedIds) {
      try {
        const res = await api.hygiene.approve(actionId)
        if (res.data?.success) success++
        else errors++
      } catch { errors++ }
    }
    toast({
      title: `Approbation en masse : ${success} appliquées, ${errors} erreurs`,
      status: errors === 0 ? 'success' : 'warning',
      duration: 5000,
      position: 'top',
    })
    setSelectedIds(new Set())
    loadData()
  }

  const handleBulkReject = async () => {
    if (selectedIds.size === 0) return
    let success = 0
    for (const actionId of selectedIds) {
      try {
        const res = await api.hygiene.reject(actionId)
        if (res.data?.success) success++
      } catch { /* ignore */ }
    }
    toast({
      title: `${success} actions rejetées`,
      status: 'info',
      duration: 3000,
      position: 'top',
    })
    setSelectedIds(new Set())
    loadData()
  }

  const handleBatchRollback = async () => {
    if (selectedIds.size === 0) return
    // Group by batch_id for efficiency
    const batchIds = Array.from(new Set(
      actions.filter(a => selectedIds.has(a.action_id)).map(a => a.batch_id)
    ))
    for (const batchId of batchIds) {
      try {
        await api.hygiene.rollbackBatch(batchId)
      } catch (error) {
        console.error('Batch rollback error:', error)
      }
    }
    toast({ title: 'Batch rollback termine', status: 'success', duration: 3000, position: 'top' })
    setSelectedIds(new Set())
    loadData()
  }

  const toggleSelect = (id: string) => {
    const next = new Set(selectedIds)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setSelectedIds(next)
  }

  const toggleSelectAll = () => {
    if (selectedIds.size === actions.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(actions.map(a => a.action_id)))
    }
  }

  if (loading && !stats) {
    return (
      <Center h="400px">
        <VStack spacing={4}>
          <Spinner size="xl" color="brand.500" thickness="3px" />
          <Text color="text.muted">Chargement KG Hygiene...</Text>
        </VStack>
      </Center>
    )
  }

  return (
    <Box maxW="1400px" mx="auto">
      {/* Header */}
      <MotionBox
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
        mb={6}
      >
        <HStack spacing={3}>
          <Box
            w={10} h={10} rounded="lg"
            bgGradient="linear(to-br, teal.500, green.400)"
            display="flex" alignItems="center" justifyContent="center"
            boxShadow="0 0 20px rgba(56, 178, 172, 0.3)"
          >
            <Icon as={FiFilter} boxSize={5} color="white" />
          </Box>
          <VStack align="start" spacing={0}>
            <Text fontSize="2xl" fontWeight="bold" color="text.primary">
              KG Hygiene
            </Text>
            <Text color="text.secondary">
              Nettoyage autonome du Knowledge Graph + Rollback
            </Text>
          </VStack>
        </HStack>
      </MotionBox>

      {/* Layer Guide */}
      <MotionBox
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, delay: 0.1 }}
        mb={4}
      >
        <Box
          p={4}
          bg="bg.secondary"
          border="1px solid"
          borderColor="border.default"
          rounded="xl"
        >
          <HStack mb={3} spacing={2}>
            <Icon as={FiInfo} color="text.muted" />
            <Text fontSize="sm" fontWeight="semibold" color="text.primary">
              Niveaux de nettoyage
            </Text>
          </HStack>
          <SimpleGrid columns={{ base: 1, md: 3 }} spacing={3}>
            <Box px={3} py={2} bg="bg.tertiary" rounded="md" borderLeft="3px solid" borderColor="green.400">
              <Text fontSize="xs" fontWeight="bold" color="green.400" mb={1}>Layer 1 — Nettoyage structurel</Text>
              <Text fontSize="xs" color="text.secondary">
                Supprime les artefacts structurels (Figure 1, Table 2), noms invalides et termes generiques.
                100% automatique, haute precision.
              </Text>
            </Box>
            <Box px={3} py={2} bg="bg.tertiary" rounded="md" borderLeft="3px solid" borderColor="orange.400">
              <Text fontSize="xs" fontWeight="bold" color="orange.400" mb={1}>Layer 2 — Deduplication concepts</Text>
              <Text fontSize="xs" color="text.secondary">
                Fusionne les doublons acronyme/nom complet (ex: PCT = Procalcitonin), detecte les entites singleton ou faibles.
                Auto-apply si haute confiance, sinon soumis a validation.
              </Text>
            </Box>
            <Box px={3} py={2} bg="bg.tertiary" rounded="md" borderLeft="3px solid" borderColor="purple.400">
              <Text fontSize="xs" fontWeight="bold" color="purple.400" mb={1}>Layer 3 — Axes d{"'"}applicabilite</Text>
              <Text fontSize="xs" color="text.secondary">
                Fusionne les axes redondants (doc_year dans publication_year), supprime les axes a faible valeur
                et detecte les axes mal nommes. Toujours soumis a validation.
              </Text>
            </Box>
          </SimpleGrid>
          <Text fontSize="xs" color="text.muted" mt={2}>
            <strong>Dry Run</strong> = preview sans modification. <strong>Run</strong> = applique les actions automatiques et propose les autres pour validation.
          </Text>
        </Box>
      </MotionBox>

      {/* Action Bar */}
      <MotionBox
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, delay: 0.15 }}
        mb={6}
      >
        <HStack
          p={4}
          bg="bg.secondary"
          border="1px solid"
          borderColor="border.default"
          rounded="xl"
          spacing={3}
          flexWrap="wrap"
        >
          <Button
            colorScheme="green"
            size="sm"
            variant="outline"
            leftIcon={<FiEye />}
            onClick={() => handleRun([1], true)}
            isLoading={running}
          >
            Preview L1
          </Button>
          <Button
            colorScheme="green"
            size="sm"
            leftIcon={<FiPlay />}
            onClick={() => handleRun([1], false)}
            isLoading={running}
          >
            Run L1
          </Button>
          <Button
            colorScheme="orange"
            size="sm"
            variant="outline"
            leftIcon={<FiEye />}
            onClick={() => handleRun([2], true)}
            isLoading={running}
          >
            Preview L2
          </Button>
          <Button
            colorScheme="orange"
            size="sm"
            leftIcon={<FiLayers />}
            onClick={() => handleRun([2], false)}
            isLoading={running}
          >
            Run L2
          </Button>
          <Button
            colorScheme="purple"
            size="sm"
            variant="outline"
            leftIcon={<FiEye />}
            onClick={() => handleRun([3], true)}
            isLoading={running}
          >
            Preview L3
          </Button>
          <Button
            colorScheme="purple"
            size="sm"
            leftIcon={<FiLayers />}
            onClick={() => handleRun([3], false)}
            isLoading={running}
          >
            Run L3
          </Button>

          {runProgress && (
            <HStack spacing={2} px={3} py={1} bg="rgba(99, 102, 241, 0.1)" rounded="md">
              <Spinner size="xs" color="brand.400" />
              <Text fontSize="sm" color="brand.400" fontWeight="medium">
                {runProgress}
              </Text>
            </HStack>
          )}

          <Box flex={1} />

          <Select
            size="sm"
            w="150px"
            placeholder="Status..."
            value={statusFilter}
            onChange={e => { setStatusFilter(e.target.value); setPage(0) }}
            bg="bg.tertiary"
            sx={{ '> option': { bg: 'bg.secondary', color: 'text.primary' } }}
          >
            <option value="APPLIED">Applied</option>
            <option value="PROPOSED">Proposed</option>
            <option value="ROLLED_BACK">Rolled Back</option>
            <option value="REJECTED">Rejected</option>
          </Select>

          <Select
            size="sm"
            w="120px"
            placeholder="Layer..."
            value={layerFilter}
            onChange={e => { setLayerFilter(e.target.value); setPage(0) }}
            bg="bg.tertiary"
            sx={{ '> option': { bg: 'bg.secondary', color: 'text.primary' } }}
          >
            <option value="1">L1 — Structurel</option>
            <option value="2">L2 — Concepts</option>
            <option value="3">L3 — Axes</option>
          </Select>

          {selectedIds.size > 0 && !isDryRunView && (
            <HStack spacing={2}>
              <Button
                colorScheme="green"
                size="sm"
                leftIcon={<FiCheck />}
                onClick={handleBulkApprove}
              >
                Approuver ({selectedIds.size})
              </Button>
              <Button
                colorScheme="orange"
                size="sm"
                variant="outline"
                leftIcon={<FiX />}
                onClick={handleBulkReject}
              >
                Rejeter ({selectedIds.size})
              </Button>
              <Button
                colorScheme="red"
                size="sm"
                variant="outline"
                leftIcon={<FiRotateCcw />}
                onClick={handleBatchRollback}
              >
                Rollback ({selectedIds.size})
              </Button>
            </HStack>
          )}
          {isDryRunView && (
            <Badge colorScheme="blue" variant="subtle" px={3} py={1}>
              Preview — aucune modification appliquee
            </Badge>
          )}
        </HStack>
      </MotionBox>

      {/* Stats Cards */}
      {stats && (
        <MotionBox
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.2 }}
          mb={6}
        >
          <SimpleGrid columns={{ base: 2, md: 4 }} spacing={4}>
            <StatCard title="Total" value={stats.total} color="brand" />
            <StatCard title="Applied" value={stats.by_status?.APPLIED || 0} color="green" />
            <StatCard title="Proposed" value={stats.by_status?.PROPOSED || 0} color="orange" />
            <StatCard title="Rolled Back" value={stats.by_status?.ROLLED_BACK || 0} color="yellow" />
          </SimpleGrid>
        </MotionBox>
      )}

      {/* Actions Table */}
      <MotionBox
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, delay: 0.3 }}
      >
        <Box
          bg="bg.secondary"
          border="1px solid"
          borderColor="border.default"
          rounded="xl"
          overflow="hidden"
        >
          <HStack px={5} py={3} borderBottom="1px solid" borderColor="border.default" bg="bg.tertiary">
            <Icon as={FiActivity} boxSize={5} color="brand.400" />
            <Text fontWeight="semibold" color="text.primary">
              Actions ({total})
            </Text>
            <Box flex={1} />
            {loading && <Spinner size="sm" color="brand.400" />}
          </HStack>

          {actions.length === 0 ? (
            <Center py={12}>
              <VStack spacing={2}>
                <Icon as={FiFilter} boxSize={8} color="text.muted" />
                <Text color="text.muted">Aucune action d'hygiene</Text>
                <Text fontSize="sm" color="text.muted">
                  Lancez un run Layer 1 ou Layer 2 pour detecter les problemes
                </Text>
              </VStack>
            </Center>
          ) : (
            <Box overflowX="auto">
              <Table size="sm">
                <Thead>
                  <Tr>
                    <Th w="40px">
                      <Checkbox
                        isChecked={selectedIds.size === actions.length && actions.length > 0}
                        onChange={toggleSelectAll}
                        colorScheme="brand"
                      />
                    </Th>
                    <Th>Type</Th>
                    <Th>Cible</Th>
                    <Th>Raison</Th>
                    <Th>L</Th>
                    <Th>Conf.</Th>
                    <Th>Status</Th>
                    <Th>Actions</Th>
                    <Th w="40px" />
                  </Tr>
                </Thead>
                <Tbody>
                  {actions.map(action => (
                    <>
                      <Tr
                        key={action.action_id}
                        opacity={action.status === 'REJECTED' ? 0.5 : action.status === 'ROLLED_BACK' ? 0.7 : 1}
                        textDecoration={action.status === 'ROLLED_BACK' ? 'line-through' : 'none'}
                        _hover={{ bg: 'bg.hover' }}
                      >
                        <Td>
                          {!isDryRunView && (
                            <Checkbox
                              isChecked={selectedIds.has(action.action_id)}
                              onChange={() => toggleSelect(action.action_id)}
                              colorScheme="brand"
                            />
                          )}
                        </Td>
                        <Td>
                          <Badge colorScheme={typeColor[action.action_type] || 'gray'} fontSize="xs">
                            {action.action_type.replace(/_/g, ' ')}
                          </Badge>
                        </Td>
                        <Td>
                          {(() => {
                            const after = action.after_state as Record<string, unknown>
                            const before = action.before_state as Record<string, unknown>

                            if (action.action_type === 'MERGE_CANONICAL') {
                              return (
                                <VStack align="start" spacing={1}>
                                  <HStack spacing={1} flexWrap="wrap">
                                    <Badge colorScheme="red" variant="subtle" fontSize="xs">
                                      {after?.target_name as string || action.target_node_id}
                                    </Badge>
                                    <Text fontSize="xs" color="text.muted">→</Text>
                                    <Badge colorScheme="green" variant="subtle" fontSize="xs">
                                      {after?.canonical_name as string || 'canonical'}
                                    </Badge>
                                  </HStack>
                                  {after?.acronym && (
                                    <Text fontSize="xs" color="text.muted">
                                      {after.acronym as string}
                                      {' = '}
                                      {after.canonical_name as string}
                                      {' '}
                                      <Badge colorScheme="purple" variant="outline" fontSize="2xs">
                                        {after.resolution_source_type as string}
                                      </Badge>
                                    </Text>
                                  )}
                                </VStack>
                              )
                            }

                            if (action.action_type === 'MERGE_AXIS') {
                              const sourceKey = (before?.source_axis_key || before?.node?.axis_key || action.target_node_id) as string
                              const targetKey = (before?.target_axis_key || after?.merge_target_id || '?') as string
                              const sourceDocs = (before?.source_doc_count || 0) as number
                              const targetDocs = (before?.target_doc_count || 0) as number
                              return (
                                <VStack align="start" spacing={1}>
                                  <HStack spacing={1} flexWrap="wrap">
                                    <Badge colorScheme="red" variant="subtle" fontSize="xs">
                                      {sourceKey}
                                    </Badge>
                                    <Text fontSize="xs" color="text.muted">→</Text>
                                    <Badge colorScheme="green" variant="subtle" fontSize="xs">
                                      {targetKey}
                                    </Badge>
                                  </HStack>
                                  <Text fontSize="xs" color="text.muted">
                                    {sourceDocs} doc(s) absorbé dans {targetDocs} doc(s)
                                  </Text>
                                </VStack>
                              )
                            }

                            return (
                              <VStack align="start" spacing={0}>
                                <Text fontSize="sm" fontWeight="medium" color="text.primary" maxW="250px" isTruncated>
                                  {after?.target_name as string || action.target_node_id}
                                </Text>
                                <Text fontSize="xs" color="text.muted">
                                  {action.target_node_type} &middot; {action.target_node_id}
                                </Text>
                              </VStack>
                            )
                          })()}
                        </Td>
                        <Td maxW="400px">
                          <Tooltip label={action.reason} placement="top-start" hasArrow openDelay={300}>
                            <Text fontSize="sm" color="text.secondary" noOfLines={2} cursor="help">
                              {action.reason}
                            </Text>
                          </Tooltip>
                        </Td>
                        <Td>
                          <Badge variant="outline" colorScheme={action.layer === 1 ? 'green' : 'orange'}>
                            L{action.layer}
                          </Badge>
                        </Td>
                        <Td>
                          <Text fontSize="sm" color="text.primary">
                            {(action.confidence * 100).toFixed(0)}%
                          </Text>
                        </Td>
                        <Td>
                          <Badge colorScheme={statusColor[action.status] || 'gray'}>
                            {action.status}
                          </Badge>
                        </Td>
                        <Td>
                          {isDryRunView ? (
                            <Badge colorScheme="blue" variant="subtle" fontSize="2xs">
                              preview
                            </Badge>
                          ) : (
                            <HStack spacing={1}>
                              {action.status === 'PROPOSED' && (
                                <>
                                  <Tooltip label="Approuver">
                                    <IconButton
                                      aria-label="Approve"
                                      icon={<FiCheck />}
                                      size="xs"
                                      colorScheme="green"
                                      variant="ghost"
                                      onClick={() => handleApprove(action.action_id)}
                                    />
                                  </Tooltip>
                                  <Tooltip label="Rejeter">
                                    <IconButton
                                      aria-label="Reject"
                                      icon={<FiX />}
                                      size="xs"
                                      colorScheme="red"
                                      variant="ghost"
                                      onClick={() => handleReject(action.action_id)}
                                    />
                                  </Tooltip>
                                </>
                              )}
                              {action.status === 'APPLIED' && (
                                <Tooltip label="Rollback">
                                  <IconButton
                                    aria-label="Rollback"
                                    icon={<FiRotateCcw />}
                                    size="xs"
                                    colorScheme="yellow"
                                    variant="ghost"
                                    onClick={() => handleRollback(action.action_id)}
                                  />
                                </Tooltip>
                              )}
                            </HStack>
                          )}
                        </Td>
                        <Td>
                          <IconButton
                            aria-label="Detail"
                            icon={expandedId === action.action_id ? <FiChevronUp /> : <FiChevronDown />}
                            size="xs"
                            variant="ghost"
                            onClick={() => setExpandedId(
                              expandedId === action.action_id ? null : action.action_id
                            )}
                          />
                        </Td>
                      </Tr>
                      {expandedId === action.action_id && (
                        <Tr key={`${action.action_id}-detail`}>
                          <Td colSpan={9} p={0}>
                            <Box p={4} bg="bg.tertiary" borderTop="1px solid" borderColor="border.default">
                              <SimpleGrid columns={{ base: 1, md: 3 }} spacing={4}>
                                <Box>
                                  <Text fontSize="xs" color="text.muted" mb={1} fontWeight="bold">
                                    Reason
                                  </Text>
                                  <Text fontSize="xs" color="text.secondary" mb={3}>
                                    {action.reason}
                                  </Text>
                                  <Text fontSize="xs" color="text.muted" mb={1} fontWeight="bold">
                                    Before State
                                  </Text>
                                  <Code
                                    display="block"
                                    whiteSpace="pre-wrap"
                                    p={3}
                                    rounded="md"
                                    fontSize="xs"
                                    bg="bg.secondary"
                                    color="text.primary"
                                    maxH="200px"
                                    overflowY="auto"
                                  >
                                    {JSON.stringify(action.before_state, null, 2)}
                                  </Code>
                                </Box>
                                <Box>
                                  <Text fontSize="xs" color="text.muted" mb={1} fontWeight="bold">
                                    After State
                                  </Text>
                                  <Code
                                    display="block"
                                    whiteSpace="pre-wrap"
                                    p={3}
                                    rounded="md"
                                    fontSize="xs"
                                    bg="bg.secondary"
                                    color="text.primary"
                                    maxH="200px"
                                    overflowY="auto"
                                  >
                                    {JSON.stringify(action.after_state, null, 2)}
                                  </Code>
                                </Box>
                                <Box>
                                  <Text fontSize="xs" color="text.muted" mb={1} fontWeight="bold">
                                    Metadata
                                  </Text>
                                  <VStack align="start" spacing={1} fontSize="xs" color="text.secondary">
                                    <Text>Rule: {action.rule_name}</Text>
                                    <Text>Batch: {action.batch_id}</Text>
                                    <Text>Scope: {action.scope}</Text>
                                    <Text>Source: {action.decision_source}</Text>
                                    {action.applied_at && <Text>Applied: {action.applied_at}</Text>}
                                    {action.rolled_back_at && <Text>Rolled back: {action.rolled_back_at}</Text>}
                                  </VStack>
                                </Box>
                              </SimpleGrid>
                            </Box>
                          </Td>
                        </Tr>
                      )}
                    </>
                  ))}
                </Tbody>
              </Table>
            </Box>
          )}

          {/* Pagination */}
          {total > pageSize && (
            <HStack px={5} py={3} borderTop="1px solid" borderColor="border.default" justify="space-between">
              <Text fontSize="sm" color="text.muted">
                Page {page + 1} / {Math.ceil(total / pageSize)}
              </Text>
              <HStack spacing={2}>
                <Button
                  size="xs"
                  variant="outline"
                  isDisabled={page === 0}
                  onClick={() => setPage(p => p - 1)}
                >
                  Precedent
                </Button>
                <Button
                  size="xs"
                  variant="outline"
                  isDisabled={(page + 1) * pageSize >= total}
                  onClick={() => setPage(p => p + 1)}
                >
                  Suivant
                </Button>
              </HStack>
            </HStack>
          )}
        </Box>
      </MotionBox>
    </Box>
  )
}
