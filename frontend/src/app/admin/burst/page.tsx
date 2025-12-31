'use client'

/**
 * OSMOSE Burst Mode Admin Page
 *
 * Gestion du mode Burst pour ingestion massive via EC2 Spot
 * - Préparation batch de documents
 * - Démarrage/Arrêt infrastructure Spot
 * - Suivi progression et événements
 */

import {
  Box,
  Button,
  Grid,
  HStack,
  Icon,
  Text,
  VStack,
  Spinner,
  Center,
  Badge,
  Progress,
  useToast,
  SimpleGrid,
  Divider,
  Alert,
  AlertIcon,
  AlertTitle,
  AlertDescription,
  Table,
  Thead,
  Tbody,
  Tr,
  Th,
  Td,
  Tabs,
  TabList,
  TabPanels,
  Tab,
  TabPanel,
} from '@chakra-ui/react'
import { motion } from 'framer-motion'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  FiCloud,
  FiPlay,
  FiPause,
  FiRefreshCw,
  FiFile,
  FiClock,
  FiActivity,
  FiCheckCircle,
  FiXCircle,
  FiAlertTriangle,
  FiServer,
  FiCpu,
  FiZap,
  FiList,
  FiSettings,
  FiLoader,
} from 'react-icons/fi'

const MotionBox = motion(Box)

// Types
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
  total_documents: number
  documents_done: number
  documents_failed: number
  documents_pending: number
  progress_percent: number
  instance_ip: string | null
  instance_type: string | null
  interruption_count: number
  vllm_url: string | null
  embeddings_url: string | null
  created_at: string | null
  started_at: string | null
  instance_details?: InstanceDetails
}

interface BurstEvent {
  timestamp: string
  event_type: string
  message: string
  severity: string
  details: Record<string, any> | null
}

interface BurstDocument {
  path: string
  name: string
  status: string
  started_at: string | null
  completed_at: string | null
  error: string | null
  chunks_count: number | null
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

// API Configuration
const API_BASE_URL = typeof window !== 'undefined'
  ? (process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000')
  : 'http://app:8000'

const getAuthHeaders = () => ({
  'Content-Type': 'application/json',
  Authorization: `Bearer ${localStorage.getItem('auth_token') || ''}`,
})

// API helpers
const fetchBurstStatus = async (): Promise<BurstStatus> => {
  const res = await fetch(`${API_BASE_URL}/api/burst/status`, {
    headers: getAuthHeaders(),
  })
  if (!res.ok) throw new Error('Failed to fetch status')
  return res.json()
}

const fetchBurstEvents = async (): Promise<{ events: BurstEvent[]; total: number }> => {
  const res = await fetch(`${API_BASE_URL}/api/burst/events?limit=50`, {
    headers: getAuthHeaders(),
  })
  if (!res.ok) throw new Error('Failed to fetch events')
  return res.json()
}

const fetchBurstDocuments = async (): Promise<{
  documents: BurstDocument[]
  total: number
  done: number
  failed: number
  pending: number
}> => {
  const res = await fetch(`${API_BASE_URL}/api/burst/documents`, {
    headers: getAuthHeaders(),
  })
  if (!res.ok) throw new Error('Failed to fetch documents')
  return res.json()
}

const fetchBurstConfig = async (): Promise<BurstConfig> => {
  const res = await fetch(`${API_BASE_URL}/api/burst/config`, {
    headers: getAuthHeaders(),
  })
  if (!res.ok) throw new Error('Failed to fetch config')
  return res.json()
}

const fetchInstanceDetails = async (): Promise<InstanceDetails | null> => {
  try {
    const res = await fetch(`${API_BASE_URL}/api/burst/instance-details`, {
      headers: getAuthHeaders(),
    })
    if (!res.ok) return null
    return res.json()
  } catch {
    return null
  }
}

// Status Badge Component
const StatusBadge = ({ status }: { status: string }) => {
  const getStatusConfig = (status: string) => {
    switch (status) {
      case 'idle':
        return { color: 'gray', icon: FiPause, label: 'Inactif' }
      case 'preparing':
        return { color: 'blue', icon: FiLoader, label: 'Préparation' }
      case 'requesting_spot':
        return { color: 'blue', icon: FiCloud, label: 'Demande Spot' }
      case 'waiting_capacity':
        return { color: 'yellow', icon: FiClock, label: 'Attente capacité' }
      case 'instance_starting':
        return { color: 'yellow', icon: FiServer, label: 'Démarrage' }
      case 'ready':
        return { color: 'green', icon: FiCheckCircle, label: 'Prêt' }
      case 'processing':
        return { color: 'purple', icon: FiActivity, label: 'Traitement' }
      case 'interrupted':
        return { color: 'orange', icon: FiAlertTriangle, label: 'Interrompu' }
      case 'resuming':
        return { color: 'blue', icon: FiRefreshCw, label: 'Reprise' }
      case 'completed':
        return { color: 'green', icon: FiCheckCircle, label: 'Terminé' }
      case 'failed':
        return { color: 'red', icon: FiXCircle, label: 'Échec' }
      case 'cancelled':
        return { color: 'gray', icon: FiXCircle, label: 'Annulé' }
      default:
        return { color: 'gray', icon: FiActivity, label: status }
    }
  }

  const config = getStatusConfig(status)

  return (
    <Badge
      colorScheme={config.color}
      display="flex"
      alignItems="center"
      gap={2}
      px={3}
      py={1}
      rounded="full"
      fontSize="sm"
    >
      <Icon as={config.icon} />
      {config.label}
    </Badge>
  )
}

// Severity Badge for events
const SeverityBadge = ({ severity }: { severity: string }) => {
  const colors: Record<string, string> = {
    debug: 'gray',
    info: 'blue',
    warning: 'orange',
    error: 'red',
  }
  return <Badge colorScheme={colors[severity] || 'gray'}>{severity}</Badge>
}

// Section Card
const SectionCard = ({
  title,
  icon,
  children,
  delay = 0,
}: {
  title: string
  icon: any
  children: React.ReactNode
  delay?: number
}) => (
  <MotionBox
    initial={{ opacity: 0, y: 20 }}
    animate={{ opacity: 1, y: 0 }}
    transition={{ duration: 0.4, delay }}
  >
    <Box
      bg="bg.secondary"
      border="1px solid"
      borderColor="border.default"
      rounded="xl"
      overflow="hidden"
    >
      <HStack
        px={5}
        py={4}
        borderBottom="1px solid"
        borderColor="border.default"
        bg="bg.tertiary"
      >
        <Icon as={icon} boxSize={5} color="brand.400" />
        <Text fontWeight="semibold" color="text.primary">
          {title}
        </Text>
      </HStack>
      <Box p={5}>{children}</Box>
    </Box>
  </MotionBox>
)

// Format uptime helper
const formatUptime = (seconds: number | null): string => {
  if (!seconds || seconds < 0) return '--'
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  if (hours > 0) return `${hours}h ${minutes}m`
  return `${minutes}m`
}

// Instance Info Panel Component
const InstanceInfoPanel = ({ details, vllmUrl }: { details: InstanceDetails | null; vllmUrl: string | null }) => {
  if (!details || !details.public_ip) return null

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'healthy': return 'green'
      case 'unhealthy': return 'red'
      case 'starting': return 'yellow'
      default: return 'gray'
    }
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'healthy': return FiCheckCircle
      case 'unhealthy': return FiXCircle
      case 'starting': return FiLoader
      default: return FiActivity
    }
  }

  // Calculer coût estimé
  const estimatedCost = details.uptime_seconds && details.spot_price_hourly
    ? ((details.uptime_seconds / 3600) * details.spot_price_hourly).toFixed(2)
    : null

  return (
    <MotionBox
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: 0.3 }}
      mb={6}
    >
      <Box
        bg="bg.secondary"
        border="2px solid"
        borderColor="green.500"
        rounded="xl"
        overflow="hidden"
      >
        {/* Header */}
        <HStack
          px={5}
          py={3}
          bg="green.900"
          borderBottom="1px solid"
          borderColor="green.700"
          justify="space-between"
        >
          <HStack spacing={3}>
            <Box
              w={8}
              h={8}
              rounded="lg"
              bg="green.500"
              display="flex"
              alignItems="center"
              justifyContent="center"
            >
              <Icon as={FiServer} boxSize={4} color="white" />
            </Box>
            <VStack align="start" spacing={0}>
              <Text fontWeight="bold" color="white">
                Instance EC2 Spot Active
              </Text>
              <Text fontSize="xs" color="green.200">
                {details.instance_type} • {details.availability_zone}
              </Text>
            </VStack>
          </HStack>
          <Badge colorScheme="green" fontSize="sm" px={3} py={1}>
            <HStack spacing={1}>
              <Icon as={FiClock} boxSize={3} />
              <Text>{formatUptime(details.uptime_seconds)}</Text>
            </HStack>
          </Badge>
        </HStack>

        {/* Content Grid */}
        <SimpleGrid columns={{ base: 2, md: 4, lg: 6 }} spacing={0}>
          {/* IP Publique */}
          <Box p={4} borderRight="1px solid" borderBottom="1px solid" borderColor="border.default">
            <Text fontSize="xs" color="text.muted" mb={1}>IP Publique</Text>
            <Text fontWeight="bold" color="text.primary" fontFamily="mono" fontSize="sm">
              {details.public_ip}
            </Text>
          </Box>

          {/* GPU */}
          <Box p={4} borderRight="1px solid" borderBottom="1px solid" borderColor="border.default">
            <Text fontSize="xs" color="text.muted" mb={1}>GPU</Text>
            <HStack>
              <Icon as={FiCpu} color="purple.400" />
              <Text fontWeight="bold" color="text.primary" fontSize="sm">
                {details.gpu_type}
              </Text>
            </HStack>
            <Text fontSize="xs" color="text.secondary">{details.gpu_memory_gb} GB VRAM</Text>
          </Box>

          {/* Prix Spot */}
          <Box p={4} borderRight="1px solid" borderBottom="1px solid" borderColor="border.default">
            <Text fontSize="xs" color="text.muted" mb={1}>Prix Spot</Text>
            <Text fontWeight="bold" color="green.400" fontSize="lg">
              ${details.spot_price_hourly?.toFixed(2)}/h
            </Text>
            {estimatedCost && (
              <Text fontSize="xs" color="text.secondary">Total: ~${estimatedCost}</Text>
            )}
          </Box>

          {/* vLLM Status */}
          <Box p={4} borderRight="1px solid" borderBottom="1px solid" borderColor="border.default">
            <Text fontSize="xs" color="text.muted" mb={1}>vLLM</Text>
            <HStack>
              <Icon as={getStatusIcon(details.vllm_status)} color={`${getStatusColor(details.vllm_status)}.400`} />
              <Text fontWeight="bold" color={`${getStatusColor(details.vllm_status)}.400`} fontSize="sm">
                {details.vllm_status === 'healthy' ? 'En ligne' : details.vllm_status}
              </Text>
            </HStack>
          </Box>

          {/* Embeddings Status */}
          <Box p={4} borderRight="1px solid" borderBottom="1px solid" borderColor="border.default">
            <Text fontSize="xs" color="text.muted" mb={1}>Embeddings</Text>
            <HStack>
              <Icon as={getStatusIcon(details.embeddings_status)} color={`${getStatusColor(details.embeddings_status)}.400`} />
              <Text fontWeight="bold" color={`${getStatusColor(details.embeddings_status)}.400`} fontSize="sm">
                {details.embeddings_status === 'healthy' ? 'En ligne' : details.embeddings_status}
              </Text>
            </HStack>
          </Box>

          {/* Uptime */}
          <Box p={4} borderBottom="1px solid" borderColor="border.default">
            <Text fontSize="xs" color="text.muted" mb={1}>Uptime</Text>
            <Text fontWeight="bold" color="text.primary" fontSize="lg">
              {formatUptime(details.uptime_seconds)}
            </Text>
          </Box>
        </SimpleGrid>

        {/* Footer with URLs */}
        <Box px={5} py={3} bg="bg.tertiary">
          <HStack spacing={6} flexWrap="wrap">
            <HStack>
              <Text fontSize="xs" color="text.muted">vLLM:</Text>
              <Text fontSize="xs" color="brand.400" fontFamily="mono">
                {vllmUrl || `http://${details.public_ip}:8000`}
              </Text>
            </HStack>
            <HStack>
              <Text fontSize="xs" color="text.muted">Embeddings:</Text>
              <Text fontSize="xs" color="brand.400" fontFamily="mono">
                http://{details.public_ip}:8001
              </Text>
            </HStack>
            {details.instance_id && (
              <HStack>
                <Text fontSize="xs" color="text.muted">Instance ID:</Text>
                <Text fontSize="xs" color="text.secondary" fontFamily="mono">
                  {details.instance_id}
                </Text>
              </HStack>
            )}
          </HStack>
        </Box>
      </Box>
    </MotionBox>
  )
}

// Stat Card
const StatCard = ({
  label,
  value,
  icon,
  color = 'brand',
}: {
  label: string
  value: string | number
  icon: any
  color?: string
}) => (
  <Box
    p={4}
    bg="bg.tertiary"
    rounded="xl"
    border="1px solid"
    borderColor="border.default"
  >
    <HStack spacing={3}>
      <Box
        w={10}
        h={10}
        rounded="lg"
        bg={`${color}.500`}
        opacity={0.2}
        display="flex"
        alignItems="center"
        justifyContent="center"
      >
        <Icon as={icon} boxSize={5} color={`${color}.400`} />
      </Box>
      <VStack align="start" spacing={0}>
        <Text fontSize="2xl" fontWeight="bold" color="text.primary">
          {value}
        </Text>
        <Text fontSize="xs" color="text.muted">
          {label}
        </Text>
      </VStack>
    </HStack>
  </Box>
)

export default function BurstAdminPage() {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState(0)

  // Queries
  const {
    data: status,
    isLoading: statusLoading,
    refetch: refetchStatus,
  } = useQuery({
    queryKey: ['burst', 'status'],
    queryFn: fetchBurstStatus,
    refetchInterval: 5000, // Poll every 5 seconds
  })

  const { data: events } = useQuery({
    queryKey: ['burst', 'events'],
    queryFn: fetchBurstEvents,
    refetchInterval: 5000,
  })

  const { data: documents } = useQuery({
    queryKey: ['burst', 'documents'],
    queryFn: fetchBurstDocuments,
    refetchInterval: 5000,
  })

  const { data: config } = useQuery({
    queryKey: ['burst', 'config'],
    queryFn: fetchBurstConfig,
    staleTime: 60000,
  })

  // Instance details (only fetch when instance is active)
  const { data: instanceDetails } = useQuery({
    queryKey: ['burst', 'instance-details'],
    queryFn: fetchInstanceDetails,
    refetchInterval: 10000, // Refresh every 10s
    enabled: !!status?.instance_ip, // Only fetch when instance is running
  })

  // Mutations
  const prepareMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_BASE_URL}/api/burst/prepare`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({}),
      })
      if (!res.ok) throw new Error((await res.json()).detail || 'Failed')
      return res.json()
    },
    onSuccess: (data) => {
      toast({
        title: 'Batch préparé',
        description: data.message,
        status: 'success',
        duration: 5000,
      })
      queryClient.invalidateQueries({ queryKey: ['burst'] })
    },
    onError: (error: Error) => {
      toast({
        title: 'Erreur',
        description: error.message,
        status: 'error',
        duration: 5000,
      })
    },
  })

  const startMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_BASE_URL}/api/burst/start`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({}),
      })
      if (!res.ok) throw new Error((await res.json()).detail || 'Failed')
      return res.json()
    },
    onSuccess: (data) => {
      toast({
        title: 'Infrastructure démarrée',
        description: data.message,
        status: 'success',
        duration: 5000,
      })
      queryClient.invalidateQueries({ queryKey: ['burst'] })
    },
    onError: (error: Error) => {
      toast({
        title: 'Erreur',
        description: error.message,
        status: 'error',
        duration: 5000,
      })
    },
  })

  const processMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_BASE_URL}/api/burst/process`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({}),
      })
      if (!res.ok) throw new Error((await res.json()).detail || 'Failed')
      return res.json()
    },
    onSuccess: (data) => {
      toast({
        title: 'Traitement lancé',
        description: data.message,
        status: 'success',
        duration: 5000,
      })
      queryClient.invalidateQueries({ queryKey: ['burst'] })
    },
    onError: (error: Error) => {
      toast({
        title: 'Erreur',
        description: error.message,
        status: 'error',
        duration: 5000,
      })
    },
  })

  const cancelMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_BASE_URL}/api/burst/cancel`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({}),
      })
      if (!res.ok) throw new Error((await res.json()).detail || 'Failed')
      return res.json()
    },
    onSuccess: (data) => {
      toast({
        title: 'Batch annulé',
        description: data.message,
        status: 'info',
        duration: 5000,
      })
      queryClient.invalidateQueries({ queryKey: ['burst'] })
    },
    onError: (error: Error) => {
      toast({
        title: 'Erreur',
        description: error.message,
        status: 'error',
        duration: 5000,
      })
    },
  })

  if (statusLoading) {
    return (
      <Center h="400px">
        <VStack spacing={4}>
          <Spinner size="xl" color="brand.500" thickness="3px" />
          <Text color="text.muted">Chargement du mode Burst...</Text>
        </VStack>
      </Center>
    )
  }

  const isActive = status?.active
  const currentStatus = status?.status || 'idle'

  // États intermédiaires pendant le démarrage de l'infra
  const infraStartingStates = ['requesting_spot', 'waiting_capacity', 'instance_starting']
  const isInfraStarting = infraStartingStates.includes(currentStatus)

  // États terminaux qui permettent de repréparer un batch
  const terminalStates = ['idle', 'completed', 'failed', 'cancelled']

  // Logique des boutons
  const canPrepare = terminalStates.includes(currentStatus)
  const canStart = currentStatus === 'preparing'
  const canProcess = currentStatus === 'ready'
  const isProcessing = currentStatus === 'processing'
  const canCancel = isActive && !terminalStates.includes(currentStatus)

  return (
    <Box maxW="1400px" mx="auto">
      {/* Header */}
      <MotionBox
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
        mb={8}
      >
        <HStack spacing={4} justify="space-between" flexWrap="wrap">
          <HStack spacing={3}>
            <Box
              w={10}
              h={10}
              rounded="lg"
              bgGradient="linear(to-br, orange.500, yellow.400)"
              display="flex"
              alignItems="center"
              justifyContent="center"
              boxShadow="0 0 20px rgba(237, 137, 54, 0.3)"
            >
              <Icon as={FiZap} boxSize={5} color="white" />
            </Box>
            <VStack align="start" spacing={0}>
              <Text fontSize="2xl" fontWeight="bold" color="text.primary">
                Mode Burst
              </Text>
              <Text color="text.secondary">
                Ingestion massive via EC2 Spot
              </Text>
            </VStack>
          </HStack>

          <HStack spacing={3}>
            <StatusBadge status={status?.status || 'idle'} />
            <Button
              size="sm"
              leftIcon={<FiRefreshCw />}
              variant="ghost"
              onClick={() => refetchStatus()}
            >
              Actualiser
            </Button>
          </HStack>
        </HStack>
      </MotionBox>

      {/* Config Warning */}
      {config && !config.enabled && (
        <Alert status="warning" variant="left-accent" mb={6} rounded="xl" borderColor="orange.400">
          <AlertIcon />
          <Box>
            <AlertTitle>Mode Burst désactivé</AlertTitle>
            <AlertDescription>
              Définissez BURST_MODE_ENABLED=true dans les variables d'environnement pour activer le mode Burst.
            </AlertDescription>
          </Box>
        </Alert>
      )}

      {/* Action Buttons */}
      <MotionBox
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, delay: 0.1 }}
        mb={6}
      >
        <HStack
          p={4}
          bg="bg.secondary"
          border="1px solid"
          borderColor="border.default"
          rounded="xl"
          spacing={4}
          flexWrap="wrap"
        >
          <Button
            colorScheme="blue"
            leftIcon={<FiFile />}
            onClick={() => prepareMutation.mutate()}
            isLoading={prepareMutation.isPending}
            isDisabled={!canPrepare || isInfraStarting || isProcessing}
          >
            1. Préparer Batch
          </Button>

          <Button
            colorScheme="orange"
            leftIcon={isInfraStarting ? undefined : <FiCloud />}
            onClick={() => startMutation.mutate()}
            isLoading={startMutation.isPending || isInfraStarting}
            loadingText={isInfraStarting ? "Démarrage en cours..." : undefined}
            isDisabled={!canStart && !isInfraStarting}
          >
            2. Démarrer Infra
          </Button>

          <Button
            colorScheme="green"
            leftIcon={isProcessing ? undefined : <FiPlay />}
            onClick={() => processMutation.mutate()}
            isLoading={processMutation.isPending || isProcessing}
            loadingText={isProcessing ? "Traitement en cours..." : undefined}
            isDisabled={!canProcess && !isProcessing}
          >
            3. Lancer Traitement
          </Button>

          <Divider orientation="vertical" h={8} />

          <Button
            colorScheme="red"
            variant="outline"
            leftIcon={<FiXCircle />}
            onClick={() => cancelMutation.mutate()}
            isLoading={cancelMutation.isPending}
            isDisabled={!canCancel}
          >
            Annuler
          </Button>
        </HStack>
      </MotionBox>

      {/* Stats Grid */}
      {status && (
        <SimpleGrid columns={{ base: 2, md: 4 }} spacing={4} mb={6}>
          <StatCard
            label="Documents Total"
            value={status.total_documents}
            icon={FiFile}
          />
          <StatCard
            label="Terminés"
            value={status.documents_done}
            icon={FiCheckCircle}
            color="green"
          />
          <StatCard
            label="En attente"
            value={status.documents_pending}
            icon={FiClock}
            color="yellow"
          />
          <StatCard
            label="Échecs"
            value={status.documents_failed}
            icon={FiXCircle}
            color="red"
          />
        </SimpleGrid>
      )}

      {/* Progress */}
      {status && status.total_documents > 0 && (
        <MotionBox
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.2 }}
          mb={6}
        >
          <Box
            p={4}
            bg="bg.secondary"
            border="1px solid"
            borderColor="border.default"
            rounded="xl"
          >
            <HStack justify="space-between" mb={2}>
              <Text fontWeight="medium" color="text.primary">
                Progression
              </Text>
              <Text color="text.muted">
                {status.progress_percent.toFixed(1)}%
              </Text>
            </HStack>
            <Progress
              value={status.progress_percent}
              colorScheme={status.status === 'processing' ? 'purple' : 'green'}
              size="lg"
              rounded="full"
              hasStripe={status.status === 'processing'}
              isAnimated={status.status === 'processing'}
            />
          </Box>
        </MotionBox>
      )}

      {/* Instance Info Panel - Détails enrichis */}
      {status?.instance_ip && (
        <InstanceInfoPanel
          details={instanceDetails || null}
          vllmUrl={status.vllm_url}
        />
      )}

      {/* Alerte interruption si nécessaire */}
      {status?.interruption_count && status.interruption_count > 0 && (
        <Alert status="warning" variant="left-accent" mb={6} rounded="xl">
          <AlertIcon as={FiAlertTriangle} />
          <AlertDescription>
            {status.interruption_count} interruption(s) Spot détectée(s).
            L&apos;instance a été automatiquement remplacée.
          </AlertDescription>
        </Alert>
      )}

      {/* Tabs */}
      <Tabs
        index={activeTab}
        onChange={setActiveTab}
        variant="enclosed"
        colorScheme="brand"
      >
        <TabList>
          <Tab>
            <HStack spacing={2}>
              <Icon as={FiList} />
              <Text>Documents</Text>
            </HStack>
          </Tab>
          <Tab>
            <HStack spacing={2}>
              <Icon as={FiActivity} />
              <Text>Événements</Text>
            </HStack>
          </Tab>
          <Tab>
            <HStack spacing={2}>
              <Icon as={FiSettings} />
              <Text>Configuration</Text>
            </HStack>
          </Tab>
        </TabList>

        <TabPanels>
          {/* Documents Tab */}
          <TabPanel px={0}>
            <SectionCard title="Documents du Batch" icon={FiFile} delay={0.4}>
              {documents && documents.documents.length > 0 ? (
                <Box overflowX="auto">
                  <Table size="sm">
                    <Thead>
                      <Tr>
                        <Th>Nom</Th>
                        <Th>Statut</Th>
                        <Th>Chunks</Th>
                        <Th>Erreur</Th>
                      </Tr>
                    </Thead>
                    <Tbody>
                      {documents.documents.map((doc, idx) => (
                        <Tr key={idx}>
                          <Td>
                            <Text
                              maxW="300px"
                              isTruncated
                              title={doc.name}
                            >
                              {doc.name}
                            </Text>
                          </Td>
                          <Td>
                            <Badge
                              colorScheme={
                                doc.status === 'completed'
                                  ? 'green'
                                  : doc.status === 'failed'
                                    ? 'red'
                                    : doc.status === 'processing'
                                      ? 'purple'
                                      : 'gray'
                              }
                            >
                              {doc.status}
                            </Badge>
                          </Td>
                          <Td>{doc.chunks_count ?? '-'}</Td>
                          <Td>
                            {doc.error && (
                              <Text
                                color="red.400"
                                fontSize="xs"
                                maxW="200px"
                                isTruncated
                                title={doc.error}
                              >
                                {doc.error}
                              </Text>
                            )}
                          </Td>
                        </Tr>
                      ))}
                    </Tbody>
                  </Table>
                </Box>
              ) : (
                <Center py={8}>
                  <VStack spacing={2}>
                    <Icon as={FiFile} boxSize={8} color="text.muted" />
                    <Text color="text.muted">Aucun document dans le batch</Text>
                    <Text fontSize="sm" color="text.muted">
                      Placez des documents dans data/burst/pending/ puis cliquez "Préparer Batch"
                    </Text>
                  </VStack>
                </Center>
              )}
            </SectionCard>
          </TabPanel>

          {/* Events Tab */}
          <TabPanel px={0}>
            <SectionCard title="Timeline Événements" icon={FiActivity} delay={0.4}>
              {events && events.events.length > 0 ? (
                <VStack spacing={3} align="stretch" maxH="400px" overflowY="auto">
                  {events.events.map((event, idx) => (
                    <HStack
                      key={idx}
                      p={3}
                      bg="bg.tertiary"
                      rounded="lg"
                      spacing={4}
                    >
                      <VStack spacing={0} align="start" minW="140px">
                        <Text fontSize="xs" color="text.muted">
                          {new Date(event.timestamp).toLocaleTimeString()}
                        </Text>
                        <SeverityBadge severity={event.severity} />
                      </VStack>
                      <VStack spacing={0} align="start" flex={1}>
                        <Text fontSize="sm" fontWeight="medium" color="text.primary">
                          {event.event_type}
                        </Text>
                        <Text fontSize="sm" color="text.secondary">
                          {event.message}
                        </Text>
                      </VStack>
                    </HStack>
                  ))}
                </VStack>
              ) : (
                <Center py={8}>
                  <VStack spacing={2}>
                    <Icon as={FiActivity} boxSize={8} color="text.muted" />
                    <Text color="text.muted">Aucun événement</Text>
                  </VStack>
                </Center>
              )}
            </SectionCard>
          </TabPanel>

          {/* Config Tab */}
          <TabPanel px={0}>
            <SectionCard title="Configuration Burst" icon={FiSettings} delay={0.4}>
              {config ? (
                <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
                  <Box p={4} bg="bg.tertiary" rounded="lg">
                    <Text fontSize="xs" color="text.muted" mb={1}>
                      Région AWS
                    </Text>
                    <Text fontWeight="medium" color="text.primary">
                      {config.aws_region}
                    </Text>
                  </Box>

                  <Box p={4} bg="bg.tertiary" rounded="lg">
                    <Text fontSize="xs" color="text.muted" mb={1}>
                      Prix Spot Max
                    </Text>
                    <Text fontWeight="medium" color="text.primary">
                      ${config.spot_max_price}/h
                    </Text>
                  </Box>

                  <Box p={4} bg="bg.tertiary" rounded="lg">
                    <Text fontSize="xs" color="text.muted" mb={1}>
                      Types d'instances
                    </Text>
                    <HStack flexWrap="wrap">
                      {config.spot_instance_types.map((t) => (
                        <Badge key={t} colorScheme="blue">
                          {t}
                        </Badge>
                      ))}
                    </HStack>
                  </Box>

                  <Box p={4} bg="bg.tertiary" rounded="lg">
                    <Text fontSize="xs" color="text.muted" mb={1}>
                      Modèle vLLM
                    </Text>
                    <Text fontWeight="medium" color="text.primary" fontSize="sm">
                      {config.vllm_model}
                    </Text>
                  </Box>

                  <Box p={4} bg="bg.tertiary" rounded="lg">
                    <Text fontSize="xs" color="text.muted" mb={1}>
                      Modèle Embeddings
                    </Text>
                    <Text fontWeight="medium" color="text.primary" fontSize="sm">
                      {config.embeddings_model}
                    </Text>
                  </Box>

                  <Box p={4} bg="bg.tertiary" rounded="lg">
                    <Text fontSize="xs" color="text.muted" mb={1}>
                      Timeout Boot
                    </Text>
                    <Text fontWeight="medium" color="text.primary">
                      {config.instance_boot_timeout}s
                    </Text>
                  </Box>
                </SimpleGrid>
              ) : (
                <Center py={8}>
                  <Spinner />
                </Center>
              )}
            </SectionCard>
          </TabPanel>
        </TabPanels>
      </Tabs>
    </Box>
  )
}
