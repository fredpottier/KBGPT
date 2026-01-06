'use client'

/**
 * OSMOSE Burst Mode Admin Page - Compact Industrial Design
 * Gestion du mode Burst pour ingestion massive via EC2 Spot
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
  Progress,
  useToast,
  useDisclosure,
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
  Flex,
  IconButton,
  Tooltip,
  Grid,
  GridItem,
  Modal,
  ModalOverlay,
  ModalContent,
  ModalHeader,
  ModalBody,
  ModalFooter,
} from '@chakra-ui/react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  FiCloud,
  FiPlay,
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
  FiDollarSign,
  FiGlobe,
  FiBox,
} from 'react-icons/fi'

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
  const res = await fetch(`${API_BASE_URL}/api/burst/status`, { headers: getAuthHeaders() })
  if (!res.ok) throw new Error('Failed to fetch status')
  return res.json()
}

const fetchBurstEvents = async (): Promise<{ events: BurstEvent[]; total: number }> => {
  const res = await fetch(`${API_BASE_URL}/api/burst/events?limit=50`, { headers: getAuthHeaders() })
  if (!res.ok) throw new Error('Failed to fetch events')
  return res.json()
}

const fetchBurstDocuments = async (): Promise<{ documents: BurstDocument[]; total: number; done: number; failed: number; pending: number }> => {
  const res = await fetch(`${API_BASE_URL}/api/burst/documents`, { headers: getAuthHeaders() })
  if (!res.ok) throw new Error('Failed to fetch documents')
  return res.json()
}

const fetchBurstConfig = async (): Promise<BurstConfig> => {
  const res = await fetch(`${API_BASE_URL}/api/burst/config`, { headers: getAuthHeaders() })
  if (!res.ok) throw new Error('Failed to fetch config')
  return res.json()
}

const fetchInstanceDetails = async (): Promise<InstanceDetails | null> => {
  try {
    const res = await fetch(`${API_BASE_URL}/api/burst/instance-details`, { headers: getAuthHeaders() })
    if (!res.ok) return null
    return res.json()
  } catch { return null }
}

// Format uptime helper
const formatUptime = (seconds: number | null): string => {
  if (!seconds || seconds < 0) return '--'
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  if (hours > 0) return `${hours}h${minutes}m`
  return `${minutes}m`
}

// Status config
const getStatusConfig = (status: string) => {
  const configs: Record<string, { color: string; icon: any; label: string }> = {
    idle: { color: 'gray', icon: FiClock, label: 'Inactif' },
    preparing: { color: 'blue', icon: FiLoader, label: 'Préparation' },
    requesting_spot: { color: 'blue', icon: FiCloud, label: 'Demande Spot' },
    waiting_capacity: { color: 'yellow', icon: FiClock, label: 'Attente' },
    instance_starting: { color: 'yellow', icon: FiServer, label: 'Démarrage' },
    ready: { color: 'green', icon: FiCheckCircle, label: 'Prêt' },
    processing: { color: 'purple', icon: FiActivity, label: 'Traitement' },
    interrupted: { color: 'orange', icon: FiAlertTriangle, label: 'Interrompu' },
    resuming: { color: 'blue', icon: FiRefreshCw, label: 'Reprise' },
    completed: { color: 'green', icon: FiCheckCircle, label: 'Terminé' },
    failed: { color: 'red', icon: FiXCircle, label: 'Échec' },
    cancelled: { color: 'gray', icon: FiXCircle, label: 'Annulé' },
  }
  return configs[status] || { color: 'gray', icon: FiActivity, label: status }
}

// Service status component - "Initialisation" instead of "unhealthy"
const ServiceStatus = ({ label, status }: { label: string; status: string }) => {
  const isHealthy = status === 'healthy'
  const isStarting = status === 'starting'
  const displayStatus = isHealthy ? 'En ligne' : isStarting ? 'Démarrage...' : 'Initialisation...'
  const color = isHealthy ? 'green' : 'yellow'
  const icon = isHealthy ? FiCheckCircle : FiLoader

  return (
    <HStack spacing={2} px={2} py={1} bg={`${color}.900`} border="1px solid" borderColor={`${color}.700`} rounded="md">
      <Icon as={icon} boxSize={3} color={`${color}.400`} className={!isHealthy ? 'animate-spin' : ''} />
      <Text fontSize="xs" color={`${color}.300`} fontWeight="medium">{label}</Text>
      <Text fontSize="xs" color={`${color}.400`}>{displayStatus}</Text>
    </HStack>
  )
}

// Compact Instance Panel
const InstancePanel = ({ details, vllmUrl }: { details: InstanceDetails | null; vllmUrl: string | null }) => {
  if (!details || !details.public_ip) return null

  const estimatedCost = details.uptime_seconds && details.spot_price_hourly
    ? ((details.uptime_seconds / 3600) * details.spot_price_hourly).toFixed(2)
    : null

  return (
    <Box bg="whiteAlpha.50" border="2px solid" borderColor="green.600" rounded="lg" mb={3} overflow="hidden">
      {/* Header */}
      <Flex px={3} py={2} bg="green.900" justify="space-between" align="center">
        <HStack spacing={2}>
          <Icon as={FiServer} boxSize={4} color="green.400" />
          <Text fontSize="sm" fontWeight="bold" color="green.100">Instance EC2 Spot Active</Text>
          <Badge colorScheme="green" fontSize="xs">{details.instance_type}</Badge>
        </HStack>
        <HStack spacing={2}>
          <Badge colorScheme="green" variant="outline" fontSize="xs">
            <HStack spacing={1}>
              <Icon as={FiClock} boxSize={3} />
              <Text>{formatUptime(details.uptime_seconds)}</Text>
            </HStack>
          </Badge>
        </HStack>
      </Flex>

      {/* Content Grid */}
      <Grid templateColumns={{ base: 'repeat(2, 1fr)', md: 'repeat(4, 1fr)' }} gap={0}>
        <GridItem p={3} borderRight="1px solid" borderBottom="1px solid" borderColor="whiteAlpha.100">
          <Text fontSize="xs" color="text.muted">IP Publique</Text>
          <Text fontSize="sm" fontWeight="bold" fontFamily="mono" color="text.primary">{details.public_ip}</Text>
        </GridItem>

        <GridItem p={3} borderRight="1px solid" borderBottom="1px solid" borderColor="whiteAlpha.100">
          <Text fontSize="xs" color="text.muted">GPU</Text>
          <HStack spacing={1}>
            <Icon as={FiCpu} boxSize={3} color="purple.400" />
            <Text fontSize="sm" fontWeight="bold" color="text.primary">{details.gpu_type}</Text>
          </HStack>
          <Text fontSize="xs" color="text.muted">{details.gpu_memory_gb} GB VRAM</Text>
        </GridItem>

        <GridItem p={3} borderRight="1px solid" borderBottom="1px solid" borderColor="whiteAlpha.100">
          <Text fontSize="xs" color="text.muted">Prix Spot</Text>
          <Text fontSize="lg" fontWeight="bold" color="green.400">${details.spot_price_hourly?.toFixed(2)}/h</Text>
          {estimatedCost && <Text fontSize="xs" color="text.muted">Total: ~${estimatedCost}</Text>}
        </GridItem>

        <GridItem p={3} borderBottom="1px solid" borderColor="whiteAlpha.100">
          <Text fontSize="xs" color="text.muted">Zone</Text>
          <Text fontSize="sm" fontWeight="bold" color="text.primary">{details.availability_zone}</Text>
        </GridItem>
      </Grid>

      {/* Services Status - Embeddings FIRST, then vLLM */}
      <Flex px={3} py={2} gap={3} bg="whiteAlpha.50" flexWrap="wrap" align="center">
        <Text fontSize="xs" color="text.muted">Services:</Text>
        <ServiceStatus label="Embeddings" status={details.embeddings_status} />
        <ServiceStatus label="vLLM" status={details.vllm_status} />
      </Flex>

      {/* URLs Footer */}
      <Flex px={3} py={2} gap={4} fontSize="xs" color="text.muted" bg="whiteAlpha.30" flexWrap="wrap">
        <HStack spacing={1}>
          <Text>Embeddings:</Text>
          <Text color="brand.400" fontFamily="mono">http://{details.public_ip}:8001</Text>
        </HStack>
        <HStack spacing={1}>
          <Text>vLLM:</Text>
          <Text color="brand.400" fontFamily="mono">{vllmUrl || `http://${details.public_ip}:8000`}</Text>
        </HStack>
        {details.instance_id && (
          <HStack spacing={1}>
            <Text>ID:</Text>
            <Text color="text.secondary" fontFamily="mono">{details.instance_id}</Text>
          </HStack>
        )}
      </Flex>
    </Box>
  )
}

export default function BurstAdminPage() {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState(0)

  // Queries
  const { data: status, isLoading: statusLoading, refetch: refetchStatus } = useQuery({
    queryKey: ['burst', 'status'],
    queryFn: fetchBurstStatus,
    refetchInterval: 5000,
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

  const { data: instanceDetails } = useQuery({
    queryKey: ['burst', 'instance-details'],
    queryFn: fetchInstanceDetails,
    refetchInterval: 10000,
    enabled: !!status?.instance_ip,
  })

  // Mutations
  const prepareMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_BASE_URL}/api/burst/prepare`, { method: 'POST', headers: getAuthHeaders(), body: JSON.stringify({}) })
      if (!res.ok) throw new Error((await res.json()).detail || 'Failed')
      return res.json()
    },
    onSuccess: (data) => { toast({ title: 'Batch préparé', description: data.message, status: 'success', duration: 3000 }); queryClient.invalidateQueries({ queryKey: ['burst'] }) },
    onError: (error: Error) => { toast({ title: 'Erreur', description: error.message, status: 'error', duration: 3000 }) },
  })

  const startMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_BASE_URL}/api/burst/start`, { method: 'POST', headers: getAuthHeaders(), body: JSON.stringify({}) })
      if (!res.ok) throw new Error((await res.json()).detail || 'Failed')
      return res.json()
    },
    onSuccess: (data) => { toast({ title: 'Infrastructure démarrée', description: data.message, status: 'success', duration: 3000 }); queryClient.invalidateQueries({ queryKey: ['burst'] }) },
    onError: (error: Error) => { toast({ title: 'Erreur', description: error.message, status: 'error', duration: 3000 }) },
  })

  const processMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_BASE_URL}/api/burst/process`, { method: 'POST', headers: getAuthHeaders(), body: JSON.stringify({}) })
      if (!res.ok) throw new Error((await res.json()).detail || 'Failed')
      return res.json()
    },
    onSuccess: (data) => { toast({ title: 'Traitement lancé', description: data.message, status: 'success', duration: 3000 }); queryClient.invalidateQueries({ queryKey: ['burst'] }) },
    onError: (error: Error) => { toast({ title: 'Erreur', description: error.message, status: 'error', duration: 3000 }) },
  })

  const cancelMutation = useMutation({
    mutationFn: async (terminateInfrastructure: boolean) => {
      const res = await fetch(`${API_BASE_URL}/api/burst/cancel`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({ terminate_infrastructure: terminateInfrastructure })
      })
      if (!res.ok) throw new Error((await res.json()).detail || 'Failed')
      return res.json()
    },
    onSuccess: (data) => {
      toast({
        title: data.infrastructure_terminated ? 'Tout annulé' : 'Traitement arrêté',
        description: data.message,
        status: 'info',
        duration: 4000
      })
      queryClient.invalidateQueries({ queryKey: ['burst'] })
    },
    onError: (error: Error) => { toast({ title: 'Erreur', description: error.message, status: 'error', duration: 3000 }) },
  })

  // Modal pour choix d'annulation
  const { isOpen: isCancelModalOpen, onOpen: openCancelModal, onClose: closeCancelModal } = useDisclosure()

  const handleCancelClick = () => {
    // Si on est en traitement ou ready avec infrastructure, proposer le choix
    if (status?.instance_ip && (isProcessing || currentStatus === 'ready')) {
      openCancelModal()
    } else {
      // Sinon, annulation directe (pas d'infra à conserver)
      cancelMutation.mutate(true)
    }
  }

  const handleCancelProcessingOnly = () => {
    closeCancelModal()
    cancelMutation.mutate(false) // Garde l'infrastructure
  }

  const handleCancelAll = () => {
    closeCancelModal()
    cancelMutation.mutate(true) // Détruit tout
  }

  if (statusLoading) {
    return <Center h="200px"><Spinner size="md" color="brand.500" /></Center>
  }

  const currentStatus = status?.status || 'idle'
  const statusConfig = getStatusConfig(currentStatus)
  const infraStartingStates = ['requesting_spot', 'waiting_capacity', 'instance_starting']
  const isInfraStarting = infraStartingStates.includes(currentStatus)
  const terminalStates = ['idle', 'completed', 'failed', 'cancelled']
  const canPrepare = terminalStates.includes(currentStatus)
  const canStart = currentStatus === 'preparing'
  const canProcess = currentStatus === 'ready'
  const isProcessing = currentStatus === 'processing'
  const canCancel = status?.active && !terminalStates.includes(currentStatus)

  return (
    <Box maxW="1400px" mx="auto" p={3}>
      {/* Header */}
      <Flex justify="space-between" align="center" mb={3}>
        <HStack spacing={3}>
          <Box w={8} h={8} rounded="lg" bgGradient="linear(to-br, orange.500, yellow.400)" display="flex" alignItems="center" justifyContent="center">
            <Icon as={FiZap} boxSize={4} color="white" />
          </Box>
          <Box>
            <Text fontSize="lg" fontWeight="bold" color="text.primary" lineHeight={1}>Mode Burst</Text>
            <Text fontSize="xs" color="text.muted">Ingestion massive via EC2 Spot</Text>
          </Box>
        </HStack>
        <HStack spacing={2}>
          <Badge colorScheme={statusConfig.color} display="flex" alignItems="center" gap={1} px={2} py={1} rounded="md">
            <Icon as={statusConfig.icon} boxSize={3} />
            {statusConfig.label}
          </Badge>
          <IconButton aria-label="Refresh" icon={<FiRefreshCw />} size="sm" variant="ghost" onClick={() => refetchStatus()} />
        </HStack>
      </Flex>

      {/* Config Warning */}
      {config && !config.enabled && (
        <Box bg="orange.900" border="1px solid" borderColor="orange.600" rounded="lg" px={3} py={2} mb={3}>
          <HStack spacing={2}>
            <Icon as={FiAlertTriangle} color="orange.400" />
            <Text fontSize="sm" color="orange.200">Mode Burst désactivé - Définissez BURST_MODE_ENABLED=true</Text>
          </HStack>
        </Box>
      )}

      {/* Action Buttons + Document Counters on same line */}
      <Flex gap={2} mb={3} flexWrap="wrap" align="center" justify="space-between" bg="whiteAlpha.50" rounded="lg" p={2} border="1px solid" borderColor="whiteAlpha.100">
        {/* Left: Action Buttons - Nav color theme (indigo family) */}
        <HStack spacing={2} flexWrap="wrap">
          <Button
            size="sm"
            leftIcon={<FiFile />}
            onClick={() => prepareMutation.mutate()}
            isLoading={prepareMutation.isPending}
            isDisabled={!canPrepare || isInfraStarting || isProcessing}
            bg={canPrepare ? '#6366F1' : '#4338CA'}
            color="white"
            opacity={canPrepare ? 1 : 0.7}
            _hover={canPrepare ? { bg: '#818CF8', transform: 'translateY(-1px)', boxShadow: '0 0 15px rgba(99, 102, 241, 0.5)' } : {}}
            _disabled={{ bg: '#4338CA', color: 'whiteAlpha.700', opacity: 0.7, cursor: 'not-allowed' }}
            transition="all 0.2s cubic-bezier(0.4, 0, 0.2, 1)"
          >
            1. Préparer
          </Button>
          <Button
            size="sm"
            leftIcon={isInfraStarting ? undefined : <FiCloud />}
            onClick={() => startMutation.mutate()}
            isLoading={startMutation.isPending || isInfraStarting}
            loadingText="Démarrage..."
            isDisabled={!canStart && !isInfraStarting}
            bg={(canStart || isInfraStarting) ? '#6366F1' : '#4338CA'}
            color="white"
            opacity={(canStart || isInfraStarting) ? 1 : 0.7}
            _hover={(canStart || isInfraStarting) ? { bg: '#818CF8', transform: 'translateY(-1px)', boxShadow: '0 0 15px rgba(99, 102, 241, 0.5)' } : {}}
            _disabled={{ bg: '#4338CA', color: 'whiteAlpha.700', opacity: 0.7, cursor: 'not-allowed' }}
            transition="all 0.2s cubic-bezier(0.4, 0, 0.2, 1)"
          >
            2. Démarrer
          </Button>
          <Button
            size="sm"
            leftIcon={isProcessing ? undefined : <FiPlay />}
            onClick={() => processMutation.mutate()}
            isLoading={processMutation.isPending || isProcessing}
            loadingText="Traitement..."
            isDisabled={!canProcess && !isProcessing}
            bg={(canProcess || isProcessing) ? '#6366F1' : '#4338CA'}
            color="white"
            opacity={(canProcess || isProcessing) ? 1 : 0.7}
            _hover={(canProcess || isProcessing) ? { bg: '#818CF8', transform: 'translateY(-1px)', boxShadow: '0 0 15px rgba(99, 102, 241, 0.5)' } : {}}
            _disabled={{ bg: '#4338CA', color: 'whiteAlpha.700', opacity: 0.7, cursor: 'not-allowed' }}
            transition="all 0.2s cubic-bezier(0.4, 0, 0.2, 1)"
          >
            3. Traiter
          </Button>
          <Box w="1px" h={6} bgGradient="linear(to-b, transparent, whiteAlpha.400, transparent)" />
          <Button
            size="sm"
            variant="outline"
            leftIcon={<FiXCircle />}
            onClick={handleCancelClick}
            isLoading={cancelMutation.isPending}
            isDisabled={!canCancel}
            borderColor="whiteAlpha.300"
            color="text.secondary"
            _hover={{ borderColor: '#4338CA', color: '#4338CA', transform: 'translateY(-1px)' }}
            _disabled={{ borderColor: 'whiteAlpha.100', color: 'whiteAlpha.300', cursor: 'not-allowed' }}
            transition="all 0.2s cubic-bezier(0.4, 0, 0.2, 1)"
          >
            Annuler
          </Button>
        </HStack>

        {/* Right: Document Counters - pill style like pass2 */}
        {status && (
          <HStack spacing={2} flexWrap="wrap">
            <HStack spacing={1.5} px={2} py={1} bg="whiteAlpha.50" rounded="md">
              <Icon as={FiFile} boxSize={3} color="blue.400" />
              <Text fontSize="xs" fontWeight="bold" color="text.primary" fontFamily="mono">{status.total_documents}</Text>
              <Text fontSize="xs" color="text.muted">Total</Text>
            </HStack>
            <HStack spacing={1.5} px={2} py={1} bg="whiteAlpha.50" rounded="md">
              <Icon as={FiCheckCircle} boxSize={3} color="green.400" />
              <Text fontSize="xs" fontWeight="bold" color="text.primary" fontFamily="mono">{status.documents_done}</Text>
              <Text fontSize="xs" color="text.muted">Terminés</Text>
            </HStack>
            <HStack spacing={1.5} px={2} py={1} bg="whiteAlpha.50" rounded="md">
              <Icon as={FiClock} boxSize={3} color="yellow.400" />
              <Text fontSize="xs" fontWeight="bold" color="text.primary" fontFamily="mono">{status.documents_pending}</Text>
              <Text fontSize="xs" color="text.muted">En attente</Text>
            </HStack>
            <HStack spacing={1.5} px={2} py={1} bg="whiteAlpha.50" rounded="md">
              <Icon as={FiXCircle} boxSize={3} color="red.400" />
              <Text fontSize="xs" fontWeight="bold" color="text.primary" fontFamily="mono">{status.documents_failed}</Text>
              <Text fontSize="xs" color="text.muted">Échecs</Text>
            </HStack>
          </HStack>
        )}
      </Flex>

      {/* Progress Bar - only when documents exist */}
      {status && status.total_documents > 0 && (
        <Box bg="whiteAlpha.50" rounded="lg" p={2} mb={3} border="1px solid" borderColor="whiteAlpha.100">
          <Flex justify="space-between" align="center" mb={1}>
            <Text fontSize="xs" color="text.muted">Progression</Text>
            <Text fontSize="xs" fontWeight="bold" fontFamily="mono" color="text.primary">{status.progress_percent.toFixed(1)}%</Text>
          </Flex>
          <Progress value={status.progress_percent} size="sm" colorScheme={isProcessing ? 'purple' : 'green'} rounded="full" hasStripe={isProcessing} isAnimated={isProcessing} />
        </Box>
      )}

      {/* Instance Panel */}
      {status?.instance_ip && <InstancePanel details={instanceDetails || null} vllmUrl={status.vllm_url} />}

      {/* Interruption Alert */}
      {status?.interruption_count && status.interruption_count > 0 && (
        <Box bg="orange.900" border="1px solid" borderColor="orange.600" rounded="lg" px={3} py={2} mb={3}>
          <HStack spacing={2}>
            <Icon as={FiAlertTriangle} color="orange.400" />
            <Text fontSize="sm" color="orange.200">{status.interruption_count} interruption(s) Spot - Instance automatiquement remplacée</Text>
          </HStack>
        </Box>
      )}

      {/* Tabs */}
      <Tabs index={activeTab} onChange={setActiveTab} variant="enclosed" colorScheme="brand" size="sm">
        <TabList>
          <Tab><HStack spacing={1}><Icon as={FiList} boxSize={3} /><Text fontSize="sm">Documents</Text></HStack></Tab>
          <Tab><HStack spacing={1}><Icon as={FiActivity} boxSize={3} /><Text fontSize="sm">Événements</Text></HStack></Tab>
          <Tab><HStack spacing={1}><Icon as={FiSettings} boxSize={3} /><Text fontSize="sm">Config</Text></HStack></Tab>
        </TabList>

        <TabPanels>
          {/* Documents Tab */}
          <TabPanel px={0} py={3}>
            <Box bg="whiteAlpha.50" rounded="lg" overflow="hidden" border="1px solid" borderColor="whiteAlpha.100">
              {documents && documents.documents.length > 0 ? (
                <Table size="sm" variant="unstyled">
                  <Thead>
                    <Tr borderBottom="1px solid" borderColor="whiteAlpha.100">
                      <Th py={2} px={3} color="text.muted" fontSize="xs">Nom</Th>
                      <Th py={2} px={3} color="text.muted" fontSize="xs" textAlign="center">Statut</Th>
                      <Th py={2} px={3} color="text.muted" fontSize="xs" isNumeric>Chunks</Th>
                      <Th py={2} px={3} color="text.muted" fontSize="xs">Erreur</Th>
                    </Tr>
                  </Thead>
                  <Tbody>
                    {documents.documents.map((doc, idx) => (
                      <Tr key={idx} borderBottom="1px solid" borderColor="whiteAlpha.50" _hover={{ bg: 'whiteAlpha.50' }}>
                        <Td py={2} px={3}>
                          <Text fontSize="sm" color="text.primary" noOfLines={1}>{doc.name}</Text>
                        </Td>
                        <Td py={2} px={3} textAlign="center">
                          <Badge size="sm" colorScheme={doc.status === 'completed' ? 'green' : doc.status === 'failed' ? 'red' : doc.status === 'processing' ? 'purple' : 'gray'} fontSize="xs">
                            {doc.status}
                          </Badge>
                        </Td>
                        <Td py={2} px={3} isNumeric>
                          <Text fontSize="sm" fontFamily="mono" color="text.muted">{doc.chunks_count ?? '-'}</Text>
                        </Td>
                        <Td py={2} px={3}>
                          {doc.error && <Text fontSize="xs" color="red.400" noOfLines={1}>{doc.error}</Text>}
                        </Td>
                      </Tr>
                    ))}
                  </Tbody>
                </Table>
              ) : (
                <Center py={6}>
                  <VStack spacing={1}>
                    <Icon as={FiFile} boxSize={6} color="text.muted" />
                    <Text fontSize="sm" color="text.muted">Aucun document</Text>
                    <Text fontSize="xs" color="text.muted">Placez des documents dans data/burst/pending/</Text>
                  </VStack>
                </Center>
              )}
            </Box>
          </TabPanel>

          {/* Events Tab */}
          <TabPanel px={0} py={3}>
            <Box bg="whiteAlpha.50" rounded="lg" border="1px solid" borderColor="whiteAlpha.100" maxH="300px" overflowY="auto">
              {events && events.events.length > 0 ? (
                <VStack spacing={0} align="stretch">
                  {events.events.map((event, idx) => (
                    <HStack key={idx} px={3} py={2} borderBottom="1px solid" borderColor="whiteAlpha.50" spacing={3} _last={{ border: 'none' }}>
                      <Text fontSize="xs" color="text.muted" fontFamily="mono" w="60px" flexShrink={0}>
                        {new Date(event.timestamp).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                      </Text>
                      <Badge size="sm" colorScheme={event.severity === 'error' ? 'red' : event.severity === 'warning' ? 'orange' : 'blue'} fontSize="xs" w="50px" textAlign="center">
                        {event.severity}
                      </Badge>
                      <Box flex={1} minW={0}>
                        <Text fontSize="xs" fontWeight="medium" color="text.primary">{event.event_type}</Text>
                        <Text fontSize="xs" color="text.muted" noOfLines={1}>{event.message}</Text>
                      </Box>
                    </HStack>
                  ))}
                </VStack>
              ) : (
                <Center py={6}>
                  <VStack spacing={1}>
                    <Icon as={FiActivity} boxSize={6} color="text.muted" />
                    <Text fontSize="sm" color="text.muted">Aucun événement</Text>
                  </VStack>
                </Center>
              )}
            </Box>
          </TabPanel>

          {/* Config Tab */}
          <TabPanel px={0} py={3}>
            {config ? (
              <Grid templateColumns={{ base: 'repeat(2, 1fr)', md: 'repeat(3, 1fr)' }} gap={2}>
                <Box bg="whiteAlpha.50" rounded="lg" p={3} border="1px solid" borderColor="whiteAlpha.100">
                  <HStack spacing={1} mb={1}><Icon as={FiGlobe} boxSize={3} color="blue.400" /><Text fontSize="xs" color="text.muted">Région AWS</Text></HStack>
                  <Text fontSize="sm" fontWeight="bold" color="text.primary">{config.aws_region}</Text>
                </Box>
                <Box bg="whiteAlpha.50" rounded="lg" p={3} border="1px solid" borderColor="whiteAlpha.100">
                  <HStack spacing={1} mb={1}><Icon as={FiDollarSign} boxSize={3} color="green.400" /><Text fontSize="xs" color="text.muted">Prix Max</Text></HStack>
                  <Text fontSize="sm" fontWeight="bold" color="text.primary">${config.spot_max_price}/h</Text>
                </Box>
                <Box bg="whiteAlpha.50" rounded="lg" p={3} border="1px solid" borderColor="whiteAlpha.100">
                  <HStack spacing={1} mb={1}><Icon as={FiServer} boxSize={3} color="purple.400" /><Text fontSize="xs" color="text.muted">Instances</Text></HStack>
                  <Flex gap={1} flexWrap="wrap">
                    {config.spot_instance_types.map((t) => <Badge key={t} size="sm" colorScheme="purple" fontSize="xs">{t}</Badge>)}
                  </Flex>
                </Box>
                <Box bg="whiteAlpha.50" rounded="lg" p={3} border="1px solid" borderColor="whiteAlpha.100">
                  <HStack spacing={1} mb={1}><Icon as={FiCpu} boxSize={3} color="orange.400" /><Text fontSize="xs" color="text.muted">Modèle vLLM</Text></HStack>
                  <Text fontSize="xs" fontWeight="bold" color="text.primary" noOfLines={1}>{config.vllm_model}</Text>
                </Box>
                <Box bg="whiteAlpha.50" rounded="lg" p={3} border="1px solid" borderColor="whiteAlpha.100">
                  <HStack spacing={1} mb={1}><Icon as={FiBox} boxSize={3} color="cyan.400" /><Text fontSize="xs" color="text.muted">Modèle Embeddings</Text></HStack>
                  <Text fontSize="xs" fontWeight="bold" color="text.primary" noOfLines={1}>{config.embeddings_model}</Text>
                </Box>
                <Box bg="whiteAlpha.50" rounded="lg" p={3} border="1px solid" borderColor="whiteAlpha.100">
                  <HStack spacing={1} mb={1}><Icon as={FiClock} boxSize={3} color="yellow.400" /><Text fontSize="xs" color="text.muted">Timeout Boot</Text></HStack>
                  <Text fontSize="sm" fontWeight="bold" color="text.primary">{config.instance_boot_timeout}s</Text>
                </Box>
              </Grid>
            ) : (
              <Center py={6}><Spinner size="sm" /></Center>
            )}
          </TabPanel>
        </TabPanels>
      </Tabs>

      {/* Modal de confirmation d'annulation */}
      <Modal isOpen={isCancelModalOpen} onClose={closeCancelModal} isCentered size="md">
        <ModalOverlay bg="blackAlpha.700" backdropFilter="blur(4px)" />
        <ModalContent bg="surface.default" border="1px solid" borderColor="whiteAlpha.200" rounded="xl">
          <ModalHeader pb={2}>
            <HStack spacing={2}>
              <Box w={8} h={8} rounded="lg" bgGradient="linear(to-br, #4338CA, #0891B2)" display="flex" alignItems="center" justifyContent="center">
                <Icon as={FiAlertTriangle} boxSize={4} color="white" />
              </Box>
              <Text fontSize="lg" fontWeight="bold" color="text.primary">Annuler le batch ?</Text>
            </HStack>
          </ModalHeader>
          <ModalBody>
            <Text fontSize="sm" color="text.muted" mb={4}>
              Une instance EC2 Spot est active. Que souhaitez-vous faire ?
            </Text>

            <VStack spacing={3} align="stretch">
              {/* Option 1: Arrêter traitement uniquement - Cyan theme */}
              <Box
                as="button"
                onClick={handleCancelProcessingOnly}
                p={3}
                bg="whiteAlpha.50"
                border="1px solid"
                borderColor="whiteAlpha.200"
                rounded="lg"
                textAlign="left"
                position="relative"
                overflow="hidden"
                _hover={{
                  borderColor: '#0891B2',
                  boxShadow: '0 0 15px rgba(8, 145, 178, 0.3)',
                  transform: 'translateY(-1px)',
                }}
                transition="all 0.2s cubic-bezier(0.4, 0, 0.2, 1)"
              >
                <HStack spacing={2} mb={1}>
                  <Icon as={FiXCircle} color="#0891B2" />
                  <Text fontWeight="bold" color="text.primary">Arrêter le traitement</Text>
                  <Badge colorScheme="cyan" fontSize="xs" ml="auto">Recommandé</Badge>
                </HStack>
                <Text fontSize="xs" color="text.muted">
                  L'instance EC2 reste active. Relancez un traitement immédiatement sans attendre le boot (~5-10 min).
                </Text>
              </Box>

              {/* Séparateur */}
              <HStack spacing={3}>
                <Box flex={1} h="1px" bgGradient="linear(to-r, transparent, whiteAlpha.300)" />
                <Text fontSize="xs" color="text.muted">ou</Text>
                <Box flex={1} h="1px" bgGradient="linear(to-l, transparent, whiteAlpha.300)" />
              </HStack>

              {/* Option 2: Tout annuler - Indigo theme */}
              <Box
                as="button"
                onClick={handleCancelAll}
                p={3}
                bg="whiteAlpha.50"
                border="1px solid"
                borderColor="whiteAlpha.200"
                rounded="lg"
                textAlign="left"
                _hover={{
                  borderColor: '#4338CA',
                  boxShadow: '0 0 15px rgba(67, 56, 202, 0.3)',
                  transform: 'translateY(-1px)',
                }}
                transition="all 0.2s cubic-bezier(0.4, 0, 0.2, 1)"
              >
                <HStack spacing={2} mb={1}>
                  <Icon as={FiServer} color="#4338CA" />
                  <Text fontWeight="bold" color="text.primary">Tout annuler</Text>
                </HStack>
                <Text fontSize="xs" color="text.muted">
                  Arrête le traitement ET détruit l'instance EC2. Les coûts Spot s'arrêtent immédiatement.
                </Text>
              </Box>
            </VStack>
          </ModalBody>
          <ModalFooter pt={3} borderTop="1px solid" borderColor="whiteAlpha.100">
            <Button size="sm" variant="ghost" color="text.muted" onClick={closeCancelModal}>
              Retour
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
    </Box>
  )
}
