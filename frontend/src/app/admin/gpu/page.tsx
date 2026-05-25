'use client'

/**
 * OSMOSE Infrastructure GPU Admin Page
 * Gestion de l'instance EC2 Spot GPU (vLLM + TEI) indépendamment du mode Burst
 */

import {
  Box,
  Button,
  HStack,
  Icon,
  Text,
  VStack,
  Spinner,
  Center,
  Badge,
  useToast,
  Flex,
  IconButton,
  Tooltip,
  Grid,
  GridItem,
  Menu,
  MenuButton,
  MenuList,
  MenuItem,
  Collapse,
  useDisclosure,
  Select,
} from '@chakra-ui/react'
import { ChevronDownIcon, ChevronUpIcon } from '@chakra-ui/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, useEffect } from 'react'
import {
  FiPlay,
  FiRefreshCw,
  FiClock,
  FiCheckCircle,
  FiXCircle,
  FiAlertTriangle,
  FiServer,
  FiCpu,
  FiZap,
  FiSettings,
  FiLoader,
  FiDollarSign,
  FiGlobe,
  FiBox,
  FiStopCircle,
  FiChevronDown,
} from 'react-icons/fi'

// ============================================================================
// Types
// ============================================================================

interface ServiceHealth {
  name: string
  status: string
  latency_ms: number | null
  url: string | null
  error: string | null
}

interface GpuHealthResponse {
  instance_ip: string | null
  services: ServiceHealth[]
  all_healthy: boolean
}

interface InstanceDetails {
  instance_id: string | null
  public_ip: string | null
  instance_type: string | null
  availability_zone: string | null
  spot_price_hourly: number | null
  uptime_seconds: number | null
  gpu_type: string | null
  gpu_memory_gb: number | null
  vllm_status: string
  embeddings_status: string
  ami_id: string | null
  launch_time: string | null
}

interface BurstStatus {
  active: boolean
  status: string
  batch_id: string | null
  instance_ip: string | null
  instance_type: string | null
  vllm_url: string | null
  embeddings_url: string | null
  started_at: string | null
}

interface ProvidersStatus {
  burst_mode_active: boolean
  llm_provider: string
  llm_endpoint: string | null
  llm_model: string | null
  embeddings_provider: string
  embeddings_endpoint: string | null
  health: Record<string, any>
}

interface BurstConfig {
  enabled: boolean
  aws_region: string
  spot_max_price: number
  spot_instance_types: string[]
  vllm_model: string
  embeddings_model: string
  vllm_port: number
  embeddings_port: number
  instance_boot_timeout: number
  max_retries: number
}

interface ActiveStack {
  stack_name: string
  status: string
  created: string | null
  spot_fleet_id: string | null
}

// CH-BURST.REL : AWS-as-source-of-truth
type DivergenceType = 'coherent' | 'zombie_local' | 'orphan_aws' | 'ip_mismatch' | 'both'

interface AwsTruth {
  aws: {
    instances_running: Array<{
      instance_id: string | null
      state: string | null
      public_ip: string | null
      instance_type: string | null
      availability_zone: string | null
      launch_time: string | null
    }>
    stacks_active: Array<{
      stack_name: string
      status: string
      created: string | null
    }>
    has_instance: boolean
    has_stack: boolean
  }
  local: {
    singleton_instance_ip: string | null
    singleton_instance_id: string | null
    singleton_stack_name: string | null
    redis_state_present: boolean
    redis_state_vllm_url: string | null
    redis_live_present: boolean
    redis_live_instance_ip: string | null
    file_present: boolean
    has_any_state: boolean
    best_known_ip: string | null
  }
  divergence_type: DivergenceType
  divergence_details: string
  can_start: boolean
  can_force_cleanup: boolean
  can_auto_resync: boolean
  computed_at: string
}

// ============================================================================
// API
// ============================================================================

const API_BASE_URL = typeof window !== 'undefined'
  ? (process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000')
  : 'http://app:8000'

const getAuthHeaders = () => ({
  'Content-Type': 'application/json',
  Authorization: `Bearer ${localStorage.getItem('auth_token') || ''}`,
})

const fetchBurstStatus = async (): Promise<BurstStatus> => {
  const res = await fetch(`${API_BASE_URL}/api/burst/status`, { headers: getAuthHeaders() })
  if (!res.ok) throw new Error('Failed to fetch status')
  return res.json()
}

const fetchGpuHealth = async (): Promise<GpuHealthResponse> => {
  const res = await fetch(`${API_BASE_URL}/api/gpu/health`, { headers: getAuthHeaders() })
  if (!res.ok) throw new Error('Failed to fetch GPU health')
  return res.json()
}

const fetchInstanceDetails = async (): Promise<InstanceDetails | null> => {
  try {
    const res = await fetch(`${API_BASE_URL}/api/burst/instance-details`, { headers: getAuthHeaders() })
    if (!res.ok) return null
    return res.json()
  } catch { return null }
}

const fetchProviders = async (): Promise<ProvidersStatus> => {
  const res = await fetch(`${API_BASE_URL}/api/burst/providers`, { headers: getAuthHeaders() })
  if (!res.ok) throw new Error('Failed to fetch providers')
  return res.json()
}

const fetchBurstConfig = async (): Promise<BurstConfig> => {
  const res = await fetch(`${API_BASE_URL}/api/burst/config`, { headers: getAuthHeaders() })
  if (!res.ok) throw new Error('Failed to fetch config')
  return res.json()
}

const fetchActiveStacks = async (): Promise<{ stacks: ActiveStack[]; count: number }> => {
  const res = await fetch(`${API_BASE_URL}/api/burst/active-stacks`, { headers: getAuthHeaders() })
  if (!res.ok) throw new Error('Failed to fetch active stacks')
  return res.json()
}

// CH-BURST.REL : AWS-as-source-of-truth + dézombie
const fetchAwsTruth = async (): Promise<AwsTruth> => {
  const res = await fetch(`${API_BASE_URL}/api/burst/aws-truth`, { headers: getAuthHeaders() })
  if (!res.ok) throw new Error((await res.json()).detail || 'Failed to fetch AWS truth')
  return res.json()
}

const postAutoResync = async (): Promise<any> => {
  const res = await fetch(`${API_BASE_URL}/api/burst/auto-resync`, {
    method: 'POST',
    headers: getAuthHeaders(),
  })
  if (!res.ok) throw new Error((await res.json()).detail || 'Auto-resync failed')
  return res.json()
}

const postForceCleanup = async (body: {
  clean_local: boolean
  clean_aws_orphans: boolean
}): Promise<any> => {
  const res = await fetch(`${API_BASE_URL}/api/burst/force-cleanup`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error((await res.json()).detail || 'Force cleanup failed')
  return res.json()
}

// ============================================================================
// Helpers
// ============================================================================

const formatUptime = (seconds: number | null): string => {
  if (!seconds || seconds < 0) return '--'
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const secs = seconds % 60
  if (hours > 0) return `${hours}h${String(minutes).padStart(2, '0')}m`
  if (minutes > 0) return `${minutes}m${String(secs).padStart(2, '0')}s`
  return `${secs}s`
}

// Hook pour calculer l'uptime en temps réel depuis launch_time
const useInstanceUptime = (launchTime: string | null) => {
  const [uptimeSeconds, setUptimeSeconds] = useState<number>(0)

  useEffect(() => {
    if (!launchTime) {
      setUptimeSeconds(0)
      return
    }

    const calculateUptime = () => {
      const launchDate = new Date(launchTime)
      const now = new Date()
      const diffMs = now.getTime() - launchDate.getTime()
      setUptimeSeconds(Math.max(0, Math.floor(diffMs / 1000)))
    }

    calculateUptime()
    const interval = setInterval(calculateUptime, 1000)
    return () => clearInterval(interval)
  }, [launchTime])

  return uptimeSeconds
}

const getGlobalStatus = (burstStatus: string, hasInstance: boolean) => {
  if (burstStatus === 'ready' || burstStatus === 'processing') {
    return { color: 'green', label: 'Actif', icon: FiCheckCircle }
  }
  if (['requesting_spot', 'waiting_capacity', 'instance_starting'].includes(burstStatus)) {
    return { color: 'yellow', label: 'Démarrage...', icon: FiLoader }
  }
  if (hasInstance) {
    return { color: 'green', label: 'Instance active', icon: FiServer }
  }
  return { color: 'gray', label: 'Inactif', icon: FiStopCircle }
}

// ============================================================================
// Composants
// ============================================================================

const ServiceCard = ({
  service,
  onRestart,
  isRestarting,
}: {
  service: ServiceHealth
  onRestart: (name: string) => void
  isRestarting: boolean
}) => {
  const isHealthy = service.status === 'healthy'
  const isUnreachable = service.status === 'unreachable'
  const borderColor = isHealthy ? 'green.500' : isUnreachable ? 'red.500' : 'yellow.500'
  const bgColor = isHealthy ? 'rgba(34, 197, 94, 0.08)' : isUnreachable ? 'rgba(239, 68, 68, 0.08)' : 'rgba(234, 179, 8, 0.08)'
  const statusColor = isHealthy ? 'green.500' : isUnreachable ? 'red.500' : 'yellow.500'
  const statusIcon = isHealthy ? FiCheckCircle : isUnreachable ? FiXCircle : FiAlertTriangle
  const displayName = service.name === 'vllm' ? 'vLLM' : 'TEI'
  const port = service.name === 'vllm' ? '8000' : '8001'

  return (
    <Box
      bg="whiteAlpha.50"
      border="2px solid"
      borderColor={borderColor}
      rounded="lg"
      overflow="hidden"
      flex={1}
      minW="200px"
    >
      {/* Header */}
      <Flex px={3} py={2} bg={bgColor} justify="space-between" align="center">
        <HStack spacing={2}>
          <Text fontSize="sm" fontWeight="bold" color="text.primary">{displayName}</Text>
          <Icon as={statusIcon} boxSize={4} color={statusColor} />
        </HStack>
        <Badge
          colorScheme={isHealthy ? 'green' : isUnreachable ? 'red' : 'yellow'}
          fontSize="xs"
        >
          {isHealthy ? 'En ligne' : isUnreachable ? 'Inaccessible' : 'Dégradé'}
        </Badge>
      </Flex>

      {/* Content */}
      <VStack spacing={2} p={3} align="stretch">
        <HStack justify="space-between">
          <Text fontSize="xs" color="text.muted">Latence</Text>
          <Text fontSize="sm" fontWeight="bold" fontFamily="mono" color="text.primary">
            {service.latency_ms !== null ? `${service.latency_ms}ms` : '--'}
          </Text>
        </HStack>
        <HStack justify="space-between">
          <Text fontSize="xs" color="text.muted">Port</Text>
          <Text fontSize="sm" fontFamily="mono" color="text.muted">{port}</Text>
        </HStack>

        {service.error && (
          <Text fontSize="xs" color="red.400" noOfLines={2}>{service.error}</Text>
        )}

        <Button
          size="xs"
          variant="outline"
          leftIcon={<FiRefreshCw />}
          onClick={() => onRestart(service.name === 'vllm' ? 'vllm' : 'tei')}
          isLoading={isRestarting}
          borderColor="whiteAlpha.300"
          color="text.secondary"
          _hover={{ borderColor: '#4338CA', color: '#4338CA' }}
          transition="all 0.2s"
        >
          Restart {displayName}
        </Button>
      </VStack>
    </Box>
  )
}

// ============================================================================
// Page principale
// ============================================================================

export default function GpuAdminPage() {
  const toast = useToast()
  const queryClient = useQueryClient()
  const { isOpen: isConfigOpen, onToggle: toggleConfig } = useDisclosure()
  const [restartingService, setRestartingService] = useState<string | null>(null)

  // Queries
  const { data: burstStatus, isLoading: statusLoading } = useQuery({
    queryKey: ['gpu', 'burst-status'],
    queryFn: fetchBurstStatus,
    refetchInterval: 5000,
  })

  const hasInstance = !!burstStatus?.instance_ip

  const { data: gpuHealth } = useQuery({
    queryKey: ['gpu', 'health'],
    queryFn: fetchGpuHealth,
    refetchInterval: 5000,
  })

  const { data: instanceDetails } = useQuery({
    queryKey: ['gpu', 'instance-details'],
    queryFn: fetchInstanceDetails,
    refetchInterval: 10000,
    enabled: hasInstance,
  })

  const { data: providers } = useQuery({
    queryKey: ['gpu', 'providers'],
    queryFn: fetchProviders,
    refetchInterval: 10000,
  })

  const { data: config } = useQuery({
    queryKey: ['gpu', 'config'],
    queryFn: fetchBurstConfig,
    staleTime: 60000,
  })

  // CH-BURST.REL : source de vérité AWS + divergence detection
  // refetchOnMount: 'always' → check AWS à chaque arrivée sur la page
  // refetchInterval: 300000 (5 min) → détecte respawn AWS en arrière-plan
  const { data: awsTruth, refetch: refetchAwsTruth } = useQuery({
    queryKey: ['gpu', 'aws-truth'],
    queryFn: fetchAwsTruth,
    refetchOnMount: 'always',
    refetchInterval: 300000,
  })

  // Auto-resync silencieux quand ip_mismatch détecté (spot interruption + respawn)
  const autoResyncMutation = useMutation({
    mutationFn: postAutoResync,
    onSuccess: (data) => {
      if (data.resynced) {
        toast({
          title: 'Instance remplacée par AWS',
          description: `Spot interruption détectée. IP locale ${data.old_ip} → IP AWS ${data.new_ip}. Worker notifié.`,
          status: 'info',
          duration: 6000,
        })
        queryClient.invalidateQueries({ queryKey: ['gpu'] })
      }
    },
    onError: (error: Error) => {
      toast({ title: 'Auto-resync échoué', description: error.message, status: 'error', duration: 4000 })
    },
  })

  useEffect(() => {
    if (awsTruth?.can_auto_resync && !autoResyncMutation.isPending) {
      autoResyncMutation.mutate()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [awsTruth?.can_auto_resync, awsTruth?.computed_at])

  // Force cleanup mutation (utilisateur explicite via modal)
  const [cleanupOptions, setCleanupOptions] = useState({
    clean_local: true,
    clean_aws_orphans: false,
  })
  const { isOpen: isCleanupOpen, onOpen: openCleanup, onClose: closeCleanup } = useDisclosure()

  const forceCleanupMutation = useMutation({
    mutationFn: postForceCleanup,
    onSuccess: (data) => {
      const parts = []
      if (data.clean_local_done) parts.push('local purgé')
      if (data.stacks_deleted?.length) parts.push(`${data.stacks_deleted.length} stack(s) supprimée(s)`)
      toast({
        title: 'Nettoyage effectué',
        description: parts.length ? parts.join(' + ') : 'Aucune action requise',
        status: 'success',
        duration: 5000,
      })
      queryClient.invalidateQueries({ queryKey: ['gpu'] })
      closeCleanup()
    },
    onError: (error: Error) => {
      toast({ title: 'Nettoyage échoué', description: error.message, status: 'error', duration: 4000 })
    },
  })

  const { data: activeStacks } = useQuery({
    queryKey: ['gpu', 'active-stacks'],
    queryFn: fetchActiveStacks,
    staleTime: 30000,
  })

  // Uptime temps réel
  const realUptimeSeconds = useInstanceUptime(instanceDetails?.launch_time || null)

  // Phase B : sélecteur de profil burst (A=g6+14B+TEI EC2 / B=g6e+72B+TEI local)
  const [selectedProfile, setSelectedProfile] = useState<string>('profile_a')
  const { data: burstProfiles } = useQuery({
    queryKey: ['burst-profiles'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/api/burst/profiles`, { headers: getAuthHeaders() })
      if (!res.ok) return { profiles: [], default: 'profile_a' }
      return res.json()
    },
    staleTime: 300000,
  })

  // Mutations
  const startMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_BASE_URL}/api/burst/start-standalone`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({ profile: selectedProfile }),
      })
      if (!res.ok) throw new Error((await res.json()).detail || 'Failed')
      return res.json()
    },
    onSuccess: (data) => {
      toast({ title: 'EC2 lancée', description: data.message, status: 'success', duration: 4000 })
      queryClient.invalidateQueries({ queryKey: ['gpu'] })
    },
    onError: (error: Error) => {
      toast({ title: 'Erreur', description: error.message, status: 'error', duration: 4000 })
    },
  })

  const stopMutation = useMutation({
    mutationFn: async (terminate: boolean) => {
      const res = await fetch(`${API_BASE_URL}/api/burst/stop-standalone`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({ terminate_infrastructure: terminate }),
      })
      if (!res.ok) throw new Error((await res.json()).detail || 'Failed')
      return res.json()
    },
    onSuccess: (data) => {
      toast({
        title: data.infrastructure_terminated ? 'Stack détruite' : 'Fleet en veille',
        description: data.message,
        status: 'info',
        duration: 4000,
      })
      queryClient.invalidateQueries({ queryKey: ['gpu'] })
    },
    onError: (error: Error) => {
      toast({ title: 'Erreur', description: error.message, status: 'error', duration: 4000 })
    },
  })

  const restartServiceMutation = useMutation({
    mutationFn: async (service: string) => {
      setRestartingService(service)
      const res = await fetch(`${API_BASE_URL}/api/gpu/restart-service`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({ service }),
      })
      if (!res.ok) throw new Error((await res.json()).detail || 'Failed')
      return res.json()
    },
    onSuccess: (data) => {
      toast({
        title: data.success ? 'Service redémarré' : 'Restart échoué',
        description: data.message,
        status: data.success ? 'success' : 'warning',
        duration: 5000,
      })
      setRestartingService(null)
      queryClient.invalidateQueries({ queryKey: ['gpu'] })
    },
    onError: (error: Error) => {
      toast({ title: 'Erreur', description: error.message, status: 'error', duration: 4000 })
      setRestartingService(null)
    },
  })

  if (statusLoading) {
    return <Center h="200px"><Spinner size="md" color="brand.500" /></Center>
  }

  const currentStatus = burstStatus?.status || 'idle'
  const isStarting = ['requesting_spot', 'waiting_capacity', 'instance_starting'].includes(currentStatus)
  const isActive = hasInstance || currentStatus === 'ready' || currentStatus === 'processing'
  const globalStatus = getGlobalStatus(currentStatus, hasInstance)

  // Coût estimé
  const uptimeMinutes = Math.floor(realUptimeSeconds / 60)
  const estimatedCost = uptimeMinutes > 0 && instanceDetails?.spot_price_hourly
    ? ((uptimeMinutes / 60) * instanceDetails.spot_price_hourly).toFixed(3)
    : null

  return (
    <Box maxW="1400px" mx="auto" p={3}>
      {/* ================================================================ */}
      {/* Header */}
      {/* ================================================================ */}
      <Flex justify="space-between" align="center" mb={3}>
        <HStack spacing={3}>
          <Box
            w={8} h={8} rounded="lg"
            bgGradient="linear(to-br, purple.500, cyan.400)"
            display="flex" alignItems="center" justifyContent="center"
          >
            <Icon as={FiCpu} boxSize={4} color="white" />
          </Box>
          <Box>
            <Text fontSize="lg" fontWeight="bold" color="text.primary" lineHeight={1}>
              Infrastructure GPU
            </Text>
            <Text fontSize="xs" color="text.muted">
              Gestion de l'instance EC2 Spot GPU
            </Text>
          </Box>
        </HStack>
        <HStack spacing={2}>
          <Badge
            colorScheme={globalStatus.color}
            display="flex" alignItems="center" gap={1}
            px={2} py={1} rounded="md"
          >
            <Icon as={globalStatus.icon} boxSize={3} />
            {globalStatus.label}
          </Badge>
          <Tooltip label="Vérifier l'état réel sur AWS (source de vérité)">
            <IconButton
              aria-label="Refresh"
              icon={<FiRefreshCw />}
              size="sm"
              variant="ghost"
              onClick={async () => {
                queryClient.invalidateQueries({ queryKey: ['gpu'] })
                const { data } = await refetchAwsTruth()
                if (!data) {
                  toast({
                    title: 'Vérification AWS',
                    description: 'Impossible de joindre AWS',
                    status: 'warning',
                    duration: 3000,
                  })
                  return
                }
                const nbInstances = data.aws.instances_running.length
                const nbStacks = data.aws.stacks_active.length
                if (data.divergence_type === 'coherent') {
                  if (nbInstances === 0 && nbStacks === 0) {
                    toast({
                      title: 'État confirmé',
                      description: 'Aucune instance EC2 active sur AWS',
                      status: 'success',
                      duration: 3000,
                    })
                  } else {
                    const ip = data.aws.instances_running[0]?.public_ip || '?'
                    toast({
                      title: 'État confirmé',
                      description: `${nbInstances} instance(s) active(s) • IP ${ip}`,
                      status: 'success',
                      duration: 3000,
                    })
                  }
                } else if (data.divergence_type === 'ip_mismatch') {
                  toast({
                    title: 'IP a changé sur AWS',
                    description: 'Auto-resync en cours…',
                    status: 'info',
                    duration: 3000,
                  })
                } else {
                  toast({
                    title: 'Divergence détectée',
                    description: data.divergence_details,
                    status: 'warning',
                    duration: 4000,
                  })
                }
              }}
            />
          </Tooltip>
        </HStack>
      </Flex>

      {/* ================================================================ */}
      {/* CH-BURST.REL : Banner divergence AWS ↔ local */}
      {/* ================================================================ */}
      {awsTruth && awsTruth.divergence_type !== 'coherent' && awsTruth.divergence_type !== 'ip_mismatch' && (
        <Box
          mb={3} p={3} rounded="md"
          bg="orange.900" borderLeft="4px solid" borderColor="orange.400"
        >
          <HStack justify="space-between" align="start">
            <Box flex={1}>
              <HStack mb={1}>
                <Icon as={FiAlertTriangle} color="orange.300" />
                <Text fontWeight="bold" color="orange.100">
                  Divergence détectée : {awsTruth.divergence_type.replace('_', ' ')}
                </Text>
              </HStack>
              <Text fontSize="sm" color="orange.50" mb={2}>
                {awsTruth.divergence_details}
              </Text>
              {awsTruth.local.best_known_ip && (
                <Text fontSize="xs" color="orange.200" fontFamily="mono">
                  Local pense : {awsTruth.local.best_known_ip} •
                  AWS instances : {awsTruth.aws.instances_running.length} •
                  AWS stacks : {awsTruth.aws.stacks_active.length}
                </Text>
              )}
            </Box>
            <Button
              size="sm" colorScheme="orange" variant="solid"
              onClick={() => {
                // Pré-cocher selon le type de divergence
                if (awsTruth.divergence_type === 'zombie_local') {
                  setCleanupOptions({ clean_local: true, clean_aws_orphans: false })
                } else if (awsTruth.divergence_type === 'orphan_aws') {
                  setCleanupOptions({ clean_local: true, clean_aws_orphans: true })
                } else {
                  setCleanupOptions({ clean_local: true, clean_aws_orphans: true })
                }
                openCleanup()
              }}
            >
              Forcer le nettoyage
            </Button>
          </HStack>
        </Box>
      )}

      {/* Modal Forcer le nettoyage */}
      {isCleanupOpen && (
        <Box
          position="fixed" top={0} left={0} right={0} bottom={0}
          bg="blackAlpha.700" zIndex={1000}
          display="flex" alignItems="center" justifyContent="center"
          onClick={closeCleanup}
        >
          <Box
            bg="gray.800" rounded="lg" p={5} maxW="500px" w="90%"
            border="1px solid" borderColor="whiteAlpha.300"
            onClick={(e) => e.stopPropagation()}
          >
            <Text fontSize="lg" fontWeight="bold" mb={3} color="text.primary">
              Forcer le nettoyage
            </Text>
            <Text fontSize="sm" color="text.secondary" mb={4}>
              Choisis ce que tu veux nettoyer. Recommandation pré-cochée selon
              le type de divergence détecté.
            </Text>

            <VStack align="start" spacing={3} mb={4}>
              <label style={{ display: 'flex', alignItems: 'flex-start', gap: 8, cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={cleanupOptions.clean_local}
                  onChange={(e) => setCleanupOptions({ ...cleanupOptions, clean_local: e.target.checked })}
                  style={{ marginTop: 4 }}
                />
                <Box>
                  <Text fontSize="sm" fontWeight="bold" color="text.primary">État local</Text>
                  <Text fontSize="xs" color="text.muted">
                    Reset singleton FastAPI + purge Redis (state + state:live) + delete fichier .burst_state.json
                  </Text>
                </Box>
              </label>

              <label style={{ display: 'flex', alignItems: 'flex-start', gap: 8, cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={cleanupOptions.clean_aws_orphans}
                  onChange={(e) => setCleanupOptions({ ...cleanupOptions, clean_aws_orphans: e.target.checked })}
                  style={{ marginTop: 4 }}
                />
                <Box>
                  <Text fontSize="sm" fontWeight="bold" color="text.primary">
                    Stack(s) AWS orpheline(s) {awsTruth?.aws.stacks_active.length ? `(${awsTruth.aws.stacks_active.length})` : ''}
                  </Text>
                  <Text fontSize="xs" color="text.muted">
                    delete_stack pour chaque knowwhere-burst-* détecté sur AWS (irréversible, ~1-2 min de teardown AWS)
                  </Text>
                  {awsTruth?.aws.stacks_active.map(s => (
                    <Text key={s.stack_name} fontSize="xs" color="orange.300" fontFamily="mono" mt={1}>
                      • {s.stack_name} ({s.status})
                    </Text>
                  ))}
                </Box>
              </label>
            </VStack>

            <HStack justify="flex-end" spacing={2}>
              <Button size="sm" variant="ghost" onClick={closeCleanup}>
                Annuler
              </Button>
              <Button
                size="sm" colorScheme="orange"
                isLoading={forceCleanupMutation.isPending}
                isDisabled={!cleanupOptions.clean_local && !cleanupOptions.clean_aws_orphans}
                onClick={() => forceCleanupMutation.mutate(cleanupOptions)}
              >
                Exécuter le nettoyage
              </Button>
            </HStack>
          </Box>
        </Box>
      )}

      {/* ================================================================ */}
      {/* Boutons d'action */}
      {/* ================================================================ */}
      <Flex
        gap={2} mb={3} align="center"
        bg="whiteAlpha.50" rounded="lg" p={2}
        border="1px solid" borderColor="whiteAlpha.100"
      >
        <Tooltip
          label={
            (burstProfiles?.profiles || []).find((p: any) => p.id === selectedProfile)?.label
            || 'Profil burst'
          }
          placement="top"
        >
          <Select
            size="sm"
            value={selectedProfile}
            onChange={(e) => setSelectedProfile(e.target.value)}
            isDisabled={isActive && !isStarting}
            maxW="240px"
            bg="whiteAlpha.100"
            borderColor="whiteAlpha.200"
            color="white"
          >
            {(burstProfiles?.profiles || [{ id: 'profile_a', label: 'g6 · 14B + TEI EC2' }]).map((p: any) => (
              <option key={p.id} value={p.id} style={{ color: '#000' }}>
                {p.id === 'profile_a' ? 'A' : 'B'} — {p.label}
              </option>
            ))}
          </Select>
        </Tooltip>

        <Button
          size="sm"
          leftIcon={isStarting ? undefined : <FiPlay />}
          onClick={() => startMutation.mutate()}
          isLoading={startMutation.isPending || isStarting}
          loadingText="Démarrage..."
          isDisabled={isActive && !isStarting}
          bg={!isActive ? '#6366F1' : '#4338CA'}
          color="white"
          opacity={!isActive ? 1 : 0.7}
          _hover={!isActive ? { bg: '#818CF8', transform: 'translateY(-1px)', boxShadow: '0 0 15px rgba(99, 102, 241, 0.5)' } : {}}
          _disabled={{ bg: '#4338CA', color: 'whiteAlpha.700', opacity: 0.7, cursor: 'not-allowed' }}
          transition="all 0.2s cubic-bezier(0.4, 0, 0.2, 1)"
        >
          Démarrer EC2
        </Button>

        <Menu>
          <MenuButton
            as={Button}
            size="sm"
            rightIcon={<FiChevronDown />}
            variant="outline"
            isDisabled={!isActive}
            borderColor={isActive ? 'red.500' : 'border.default'}
            color={isActive ? 'red.500' : 'text.secondary'}
            _hover={isActive ? { borderColor: 'red.400', bg: 'rgba(239, 68, 68, 0.08)' } : {}}
            _disabled={{ borderColor: 'whiteAlpha.100', color: 'whiteAlpha.300', cursor: 'not-allowed' }}
            transition="all 0.2s"
          >
            Arrêter EC2
          </MenuButton>
          <MenuList
            bg="surface.default"
            borderColor="border.default"
            rounded="xl"
            shadow="xl"
          >
            <MenuItem
              onClick={() => stopMutation.mutate(false)}
              _hover={{ bg: 'bg.hover' }}
              icon={<Icon as={FiStopCircle} color="yellow.400" />}
            >
              <Box>
                <Text fontSize="sm" fontWeight="medium">Hibernation (fleet=0)</Text>
                <Text fontSize="xs" color="text.muted">Redémarrage rapide (~1-2 min)</Text>
              </Box>
            </MenuItem>
            <MenuItem
              onClick={() => stopMutation.mutate(true)}
              _hover={{ bg: 'bg.hover' }}
              icon={<Icon as={FiXCircle} color="red.400" />}
            >
              <Box>
                <Text fontSize="sm" fontWeight="medium">Destruction stack</Text>
                <Text fontSize="xs" color="text.muted">Arrêt complet, coûts à 0</Text>
              </Box>
            </MenuItem>
          </MenuList>
        </Menu>

        {/* Stacks reconnexion */}
        {activeStacks && activeStacks.count > 0 && !hasInstance && (
          <Badge colorScheme="blue" px={2} py={1} rounded="md" fontSize="xs">
            {activeStacks.count} stack(s) active(s) - reconnexion possible via Burst
          </Badge>
        )}
      </Flex>

      {/* ================================================================ */}
      {/* Section Instance EC2 */}
      {/* ================================================================ */}
      {hasInstance && instanceDetails ? (
        <Box bg="bg.secondary" border="2px solid" borderColor="green.500" rounded="lg" mb={3} overflow="hidden">
          <Flex px={3} py={2} bg="rgba(34, 197, 94, 0.1)" justify="space-between" align="center">
            <HStack spacing={2}>
              <Icon as={FiServer} boxSize={4} color="green.500" />
              <Text fontSize="sm" fontWeight="bold" color="text.primary">Instance EC2</Text>
              <Badge colorScheme="green" fontSize="xs">{instanceDetails.instance_type}</Badge>
            </HStack>
            <Tooltip
              label={`Lancée: ${instanceDetails.launch_time ? new Date(instanceDetails.launch_time).toLocaleString('fr-FR') : 'N/A'}`}
              placement="top"
            >
              <Badge colorScheme="green" variant="outline" fontSize="xs">
                <HStack spacing={1}>
                  <Icon as={FiClock} boxSize={3} />
                  <Text>{formatUptime(realUptimeSeconds)}</Text>
                </HStack>
              </Badge>
            </Tooltip>
          </Flex>

          <Grid templateColumns={{ base: 'repeat(2, 1fr)', md: 'repeat(4, 1fr)' }} gap={0}>
            <GridItem p={3} borderRight="1px solid" borderBottom="1px solid" borderColor="whiteAlpha.100">
              <Text fontSize="xs" color="text.muted">IP Publique</Text>
              <Text fontSize="sm" fontWeight="bold" fontFamily="mono" color="text.primary">
                {instanceDetails.public_ip}
              </Text>
            </GridItem>
            <GridItem p={3} borderRight="1px solid" borderBottom="1px solid" borderColor="whiteAlpha.100">
              <Text fontSize="xs" color="text.muted">GPU</Text>
              <HStack spacing={1}>
                <Icon as={FiCpu} boxSize={3} color="purple.400" />
                <Text fontSize="sm" fontWeight="bold" color="text.primary">{instanceDetails.gpu_type}</Text>
              </HStack>
              <Text fontSize="xs" color="text.muted">{instanceDetails.gpu_memory_gb} GB VRAM</Text>
            </GridItem>
            <GridItem p={3} borderRight="1px solid" borderBottom="1px solid" borderColor="whiteAlpha.100">
              <Text fontSize="xs" color="text.muted">Prix Spot</Text>
              <Text fontSize="sm" fontWeight="bold" color="green.400">
                ${instanceDetails.spot_price_hourly?.toFixed(3)}/h
              </Text>
            </GridItem>
            <GridItem p={3} borderBottom="1px solid" borderColor="whiteAlpha.100">
              <Tooltip label="Coût estimé depuis le lancement" placement="top">
                <Box>
                  <HStack spacing={1}>
                    <Icon as={FiDollarSign} boxSize={3} color="yellow.400" />
                    <Text fontSize="xs" color="text.muted">Coût session</Text>
                  </HStack>
                  <Text fontSize="lg" fontWeight="bold" color="yellow.400">
                    {estimatedCost ? `$${estimatedCost}` : '--'}
                  </Text>
                  <Text fontSize="xs" color="text.muted">{instanceDetails.availability_zone}</Text>
                </Box>
              </Tooltip>
            </GridItem>
          </Grid>
        </Box>
      ) : !hasInstance && !isStarting ? (
        <Box
          bg="whiteAlpha.50" border="1px solid" borderColor="whiteAlpha.100"
          rounded="lg" mb={3} p={6}
        >
          <Center>
            <VStack spacing={2}>
              <Icon as={FiServer} boxSize={8} color="text.muted" />
              <Text fontSize="sm" color="text.muted">Aucune instance EC2 active</Text>
              <Text fontSize="xs" color="text.muted">
                Cliquez sur "Démarrer EC2" pour lancer une instance GPU
              </Text>
            </VStack>
          </Center>
        </Box>
      ) : null}

      {/* ================================================================ */}
      {/* Section Services (vLLM + TEI) */}
      {/* ================================================================ */}
      {hasInstance && (
        <Box mb={3}>
          <Text fontSize="sm" fontWeight="bold" color="text.primary" mb={2}>
            Services
          </Text>
          <Flex gap={3} flexWrap="wrap">
            {gpuHealth && gpuHealth.services.length > 0 ? (
              gpuHealth.services.map((svc) => (
                <ServiceCard
                  key={svc.name}
                  service={svc}
                  onRestart={(name) => restartServiceMutation.mutate(name)}
                  isRestarting={restartingService === svc.name}
                />
              ))
            ) : (
              <>
                <ServiceCard
                  service={{ name: 'vllm', status: 'unreachable', latency_ms: null, url: null, error: 'Chargement...' }}
                  onRestart={(name) => restartServiceMutation.mutate(name)}
                  isRestarting={restartingService === 'vllm'}
                />
                <ServiceCard
                  service={{ name: 'tei', status: 'unreachable', latency_ms: null, url: null, error: 'Chargement...' }}
                  onRestart={(name) => restartServiceMutation.mutate(name)}
                  isRestarting={restartingService === 'tei'}
                />
              </>
            )}
          </Flex>
        </Box>
      )}

      {/* ================================================================ */}
      {/* Section Routing IA */}
      {/* ================================================================ */}
      {providers && (
        <Box
          bg="whiteAlpha.50" border="1px solid" borderColor="whiteAlpha.100"
          rounded="lg" mb={3} overflow="hidden"
        >
          <Flex px={3} py={2} bg="whiteAlpha.50" borderBottom="1px solid" borderColor="whiteAlpha.100">
            <HStack spacing={2}>
              <Icon as={FiZap} boxSize={3} color="purple.400" />
              <Text fontSize="sm" fontWeight="bold" color="text.primary">Routing IA</Text>
            </HStack>
          </Flex>

          <VStack spacing={0} align="stretch">
            {/* LLM */}
            <Flex px={3} py={2} justify="space-between" align="center" borderBottom="1px solid" borderColor="whiteAlpha.50">
              <HStack spacing={2}>
                <Text fontSize="sm" color="text.muted" w="100px">LLM</Text>
                <Text fontSize="sm" fontWeight="medium" color="text.primary">
                  {providers.llm_provider === 'burst' ? 'vLLM EC2' : providers.llm_provider === 'local' ? 'OpenAI / Anthropic' : providers.llm_provider}
                </Text>
              </HStack>
              <Badge
                colorScheme={providers.llm_provider === 'burst' ? 'green' : 'gray'}
                fontSize="xs"
              >
                {providers.llm_provider === 'burst' ? 'Burst actif' : 'Normal'}
              </Badge>
            </Flex>

            {/* Embeddings */}
            <Flex px={3} py={2} justify="space-between" align="center" borderBottom="1px solid" borderColor="whiteAlpha.50">
              <HStack spacing={2}>
                <Text fontSize="sm" color="text.muted" w="100px">Embeddings</Text>
                <Text fontSize="sm" fontWeight="medium" color="text.primary">
                  {providers.embeddings_provider === 'burst' ? 'TEI EC2' : providers.embeddings_provider === 'local' ? 'OpenAI' : providers.embeddings_provider}
                </Text>
              </HStack>
              <Badge
                colorScheme={providers.embeddings_provider === 'burst' ? 'green' : 'gray'}
                fontSize="xs"
              >
                {providers.embeddings_provider === 'burst' ? 'Burst actif' : 'Normal'}
              </Badge>
            </Flex>

            {/* Vision */}
            <Flex px={3} py={2} justify="space-between" align="center">
              <HStack spacing={2}>
                <Text fontSize="sm" color="text.muted" w="100px">Vision</Text>
                <Text fontSize="sm" fontWeight="medium" color="text.primary">OpenAI</Text>
              </HStack>
              <Badge colorScheme="gray" fontSize="xs">Normal</Badge>
            </Flex>
          </VStack>
        </Box>
      )}

      {/* ================================================================ */}
      {/* Section Configuration AWS (repliable) */}
      {/* ================================================================ */}
      {config && (
        <Box
          bg="whiteAlpha.50" border="1px solid" borderColor="whiteAlpha.100"
          rounded="lg" overflow="hidden"
        >
          <Flex
            px={3} py={2}
            justify="space-between" align="center"
            cursor="pointer"
            onClick={toggleConfig}
            _hover={{ bg: 'whiteAlpha.100' }}
            transition="all 0.15s"
          >
            <HStack spacing={2}>
              <Icon as={FiSettings} boxSize={3} color="text.muted" />
              <Text fontSize="sm" fontWeight="bold" color="text.primary">Configuration AWS</Text>
            </HStack>
            <Icon as={isConfigOpen ? ChevronUpIcon : ChevronDownIcon} color="text.muted" />
          </Flex>

          <Collapse in={isConfigOpen} animateOpacity>
            <Grid
              templateColumns={{ base: 'repeat(2, 1fr)', md: 'repeat(3, 1fr)' }}
              gap={2} p={3}
              borderTop="1px solid" borderColor="whiteAlpha.100"
            >
              <Box bg="whiteAlpha.50" rounded="lg" p={3} border="1px solid" borderColor="whiteAlpha.100">
                <HStack spacing={1} mb={1}>
                  <Icon as={FiGlobe} boxSize={3} color="blue.400" />
                  <Text fontSize="xs" color="text.muted">Région AWS</Text>
                </HStack>
                <Text fontSize="sm" fontWeight="bold" color="text.primary">{config.aws_region}</Text>
              </Box>
              <Box bg="whiteAlpha.50" rounded="lg" p={3} border="1px solid" borderColor="whiteAlpha.100">
                <HStack spacing={1} mb={1}>
                  <Icon as={FiDollarSign} boxSize={3} color="green.400" />
                  <Text fontSize="xs" color="text.muted">Prix Max</Text>
                </HStack>
                <Text fontSize="sm" fontWeight="bold" color="text.primary">${config.spot_max_price}/h</Text>
              </Box>
              <Box bg="whiteAlpha.50" rounded="lg" p={3} border="1px solid" borderColor="whiteAlpha.100">
                <HStack spacing={1} mb={1}>
                  <Icon as={FiServer} boxSize={3} color="purple.400" />
                  <Text fontSize="xs" color="text.muted">Instances</Text>
                </HStack>
                <Flex gap={1} flexWrap="wrap">
                  {config.spot_instance_types.map((t) => (
                    <Badge key={t} size="sm" colorScheme="purple" fontSize="xs">{t}</Badge>
                  ))}
                </Flex>
              </Box>
              <Box bg="whiteAlpha.50" rounded="lg" p={3} border="1px solid" borderColor="whiteAlpha.100">
                <HStack spacing={1} mb={1}>
                  <Icon as={FiCpu} boxSize={3} color="orange.400" />
                  <Text fontSize="xs" color="text.muted">Modèle vLLM</Text>
                </HStack>
                <Text fontSize="xs" fontWeight="bold" color="text.primary" noOfLines={1}>{config.vllm_model}</Text>
              </Box>
              <Box bg="whiteAlpha.50" rounded="lg" p={3} border="1px solid" borderColor="whiteAlpha.100">
                <HStack spacing={1} mb={1}>
                  <Icon as={FiBox} boxSize={3} color="cyan.400" />
                  <Text fontSize="xs" color="text.muted">Modèle Embeddings</Text>
                </HStack>
                <Text fontSize="xs" fontWeight="bold" color="text.primary" noOfLines={1}>{config.embeddings_model}</Text>
              </Box>
              <Box bg="whiteAlpha.50" rounded="lg" p={3} border="1px solid" borderColor="whiteAlpha.100">
                <HStack spacing={1} mb={1}>
                  <Icon as={FiClock} boxSize={3} color="yellow.400" />
                  <Text fontSize="xs" color="text.muted">Timeout Boot</Text>
                </HStack>
                <Text fontSize="sm" fontWeight="bold" color="text.primary">{config.instance_boot_timeout}s</Text>
              </Box>
            </Grid>
          </Collapse>
        </Box>
      )}
    </Box>
  )
}
