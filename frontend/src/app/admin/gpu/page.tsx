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
  const borderColor = isHealthy ? 'green.600' : isUnreachable ? 'red.600' : 'yellow.600'
  const bgColor = isHealthy ? 'green.900' : isUnreachable ? 'red.900' : 'yellow.900'
  const statusColor = isHealthy ? 'green.400' : isUnreachable ? 'red.400' : 'yellow.400'
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

  const { data: activeStacks } = useQuery({
    queryKey: ['gpu', 'active-stacks'],
    queryFn: fetchActiveStacks,
    staleTime: 30000,
  })

  // Uptime temps réel
  const realUptimeSeconds = useInstanceUptime(instanceDetails?.launch_time || null)

  // Mutations
  const startMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_BASE_URL}/api/burst/start-standalone`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({}),
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
          <IconButton
            aria-label="Refresh"
            icon={<FiRefreshCw />}
            size="sm"
            variant="ghost"
            onClick={() => queryClient.invalidateQueries({ queryKey: ['gpu'] })}
          />
        </HStack>
      </Flex>

      {/* ================================================================ */}
      {/* Boutons d'action */}
      {/* ================================================================ */}
      <Flex
        gap={2} mb={3} align="center"
        bg="whiteAlpha.50" rounded="lg" p={2}
        border="1px solid" borderColor="whiteAlpha.100"
      >
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
            borderColor={isActive ? 'red.600' : 'whiteAlpha.300'}
            color={isActive ? 'red.400' : 'text.secondary'}
            _hover={isActive ? { borderColor: 'red.400', bg: 'red.900' } : {}}
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
        <Box bg="whiteAlpha.50" border="2px solid" borderColor="green.600" rounded="lg" mb={3} overflow="hidden">
          <Flex px={3} py={2} bg="green.900" justify="space-between" align="center">
            <HStack spacing={2}>
              <Icon as={FiServer} boxSize={4} color="green.400" />
              <Text fontSize="sm" fontWeight="bold" color="green.100">Instance EC2</Text>
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
