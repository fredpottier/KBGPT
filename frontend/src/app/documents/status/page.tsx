'use client'

/**
 * KnowWhere Documents Status - Dark Elegance Edition
 *
 * Premium import tracking with real-time updates
 */

import {
  Box,
  Button,
  Text,
  VStack,
  HStack,
  Badge,
  Spinner,
  useToast,
  Flex,
  IconButton,
  Tooltip,
  Progress,
  Modal,
  ModalOverlay,
  ModalContent,
  ModalHeader,
  ModalFooter,
  ModalBody,
  ModalCloseButton,
  useDisclosure,
  Icon,
  Table,
  Thead,
  Tbody,
  Tr,
  Th,
  Td,
} from '@chakra-ui/react'
import { useState, useEffect, useCallback } from 'react'
import { RepeatIcon, DeleteIcon, WarningIcon } from '@chakra-ui/icons'
import { motion, AnimatePresence } from 'framer-motion'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import {
  FiDownload,
  FiActivity,
  FiClock,
  FiCheckCircle,
  FiXCircle,
  FiLoader,
  FiFile,
  FiFileText,
  FiImage,
  FiTrash2,
  FiRefreshCw,
  FiAlertTriangle,
  FiInbox,
} from 'react-icons/fi'

const MotionBox = motion(Box)

interface ImportRecord {
  uid: string
  filename: string
  status: string
  started_at: string
  completed_at?: string
  duration?: number
  chunks_inserted?: number
  client?: string
  topic?: string
  error_message?: string
  document_type?: string
  language?: string
  source_date?: string
  solution?: string
  import_type?: 'document' | 'excel_qa' | 'fill_rfp'
}

interface ActiveImport {
  uid: string
  filename: string
  status: string
  message?: string
  chunks_inserted?: number
  started_at: string
  current_step?: string
  progress?: number
  total_steps?: number
  step_message?: string
  progress_percentage?: number
  client?: string
}

// Status Badge Component
const StatusBadge = ({ status }: { status: string }) => {
  const getStatusConfig = (s: string) => {
    switch (s.toLowerCase()) {
      case 'completed':
      case 'done':
        return { color: 'green', bg: 'rgba(34, 197, 94, 0.15)', icon: FiCheckCircle, label: 'Termine' }
      case 'failed':
      case 'error':
        return { color: 'red', bg: 'rgba(239, 68, 68, 0.15)', icon: FiXCircle, label: 'Echec' }
      case 'processing':
      case 'in_progress':
        return { color: 'blue', bg: 'rgba(59, 130, 246, 0.15)', icon: FiLoader, label: 'En cours' }
      case 'pending':
      case 'queued':
        return { color: 'orange', bg: 'rgba(249, 115, 22, 0.15)', icon: FiClock, label: 'En attente' }
      default:
        return { color: 'gray', bg: 'rgba(156, 163, 175, 0.15)', icon: FiFile, label: status }
    }
  }

  const config = getStatusConfig(status)

  return (
    <HStack
      spacing={1.5}
      px={2.5}
      py={1}
      bg={config.bg}
      rounded="full"
      display="inline-flex"
    >
      <Icon as={config.icon} boxSize={3.5} color={`${config.color}.400`} />
      <Text fontSize="xs" fontWeight="medium" color={`${config.color}.400`}>
        {config.label}
      </Text>
    </HStack>
  )
}

// Type Badge Component
const TypeBadge = ({ record }: { record: ImportRecord }) => {
  const getTypeConfig = () => {
    if (record.import_type === 'excel_qa' || record.filename?.toLowerCase().endsWith('.xlsx')) {
      return { label: 'Excel Q/R', color: 'green', icon: FiFileText }
    }
    if (record.import_type === 'fill_rfp') {
      return { label: 'RFP', color: 'purple', icon: FiFileText }
    }
    if (record.filename?.toLowerCase().endsWith('.pptx')) {
      return { label: 'PPTX', color: 'orange', icon: FiImage }
    }
    if (record.filename?.toLowerCase().endsWith('.pdf')) {
      return { label: 'PDF', color: 'red', icon: FiFileText }
    }
    return { label: 'Document', color: 'gray', icon: FiFile }
  }

  const config = getTypeConfig()

  return (
    <HStack
      spacing={1.5}
      px={2}
      py={0.5}
      bg="bg.tertiary"
      border="1px solid"
      borderColor="border.default"
      rounded="md"
      display="inline-flex"
    >
      <Icon as={config.icon} boxSize={3} color={`${config.color}.400`} />
      <Text fontSize="xs" color="text.secondary">
        {config.label}
      </Text>
    </HStack>
  )
}

// Current Import Card
const CurrentImportCard = ({ currentImport }: { currentImport: ActiveImport }) => (
  <MotionBox
    initial={{ opacity: 0, y: 10 }}
    animate={{ opacity: 1, y: 0 }}
    transition={{ duration: 0.3 }}
  >
    <Box
      bg="rgba(59, 130, 246, 0.08)"
      border="1px solid"
      borderColor="rgba(59, 130, 246, 0.3)"
      rounded="xl"
      p={5}
      position="relative"
      overflow="hidden"
    >
      {/* Animated border */}
      <Box
        position="absolute"
        top={0}
        left={0}
        right={0}
        h="2px"
        bgGradient="linear(to-r, transparent, blue.400, transparent)"
        className="animate-pulse-glow"
      />

      <HStack justify="space-between" mb={4}>
        <VStack align="start" spacing={1} flex={1}>
          <HStack spacing={2}>
            <Box className="animate-pulse-glow">
              <Spinner size="sm" color="blue.400" />
            </Box>
            <Text fontWeight="semibold" color="text.primary">
              {currentImport.filename}
            </Text>
          </HStack>
          {currentImport.client && (
            <Text fontSize="sm" color="text.muted">
              Client: {currentImport.client}
            </Text>
          )}
          <Text fontSize="xs" color="text.muted">
            Demarre: {new Date(currentImport.started_at).toLocaleString('fr-FR')}
          </Text>
        </VStack>

        <StatusBadge status={currentImport.status} />
      </HStack>

      {/* Progress */}
      {currentImport.current_step && (
        <VStack spacing={2} align="stretch">
          <HStack justify="space-between">
            <Text fontSize="sm" color="blue.300" fontWeight="medium">
              {currentImport.current_step}
            </Text>
            {currentImport.progress_percentage !== undefined && (
              <Text fontSize="xs" color="text.muted">
                {currentImport.progress_percentage}%
              </Text>
            )}
          </HStack>

          {currentImport.progress_percentage !== undefined && (
            <Box
              h="6px"
              bg="bg.tertiary"
              rounded="full"
              overflow="hidden"
            >
              <Box
                h="full"
                w={`${currentImport.progress_percentage}%`}
                bg="blue.400"
                rounded="full"
                transition="width 0.5s ease"
                boxShadow="0 0 10px rgba(59, 130, 246, 0.5)"
              />
            </Box>
          )}

          {currentImport.step_message && (
            <Text fontSize="xs" color="text.muted">
              {currentImport.step_message}
            </Text>
          )}

          {currentImport.progress && currentImport.total_steps && (
            <Text fontSize="xs" color="text.muted">
              Etape {currentImport.progress} sur {currentImport.total_steps}
            </Text>
          )}
        </VStack>
      )}

      {currentImport.chunks_inserted !== undefined && currentImport.chunks_inserted > 0 && (
        <HStack mt={3} spacing={2}>
          <Icon as={FiCheckCircle} color="green.400" boxSize={4} />
          <Text fontSize="sm" color="green.400">
            {currentImport.chunks_inserted} chunks inseres
          </Text>
        </HStack>
      )}
    </Box>
  </MotionBox>
)

// Queued Import Item
const QueuedImportItem = ({ queuedImport, index }: { queuedImport: any; index: number }) => (
  <HStack
    key={queuedImport.uid}
    p={3}
    bg="bg.tertiary"
    border="1px solid"
    borderColor="border.default"
    rounded="lg"
    justify="space-between"
  >
    <HStack spacing={3}>
      <Box
        w={6}
        h={6}
        rounded="md"
        bg="rgba(249, 115, 22, 0.15)"
        display="flex"
        alignItems="center"
        justifyContent="center"
      >
        <Text fontSize="xs" fontWeight="bold" color="orange.400">
          {index + 1}
        </Text>
      </Box>
      <VStack align="start" spacing={0}>
        <Text fontSize="sm" fontWeight="medium" color="text.primary">
          {queuedImport.filename}
        </Text>
        {queuedImport.client && (
          <Text fontSize="xs" color="text.muted">
            {queuedImport.client}
          </Text>
        )}
      </VStack>
    </HStack>
    <StatusBadge status="pending" />
  </HStack>
)

// Empty State Component
const EmptyState = () => (
  <MotionBox
    initial={{ opacity: 0 }}
    animate={{ opacity: 1 }}
    transition={{ duration: 0.5 }}
  >
    <VStack spacing={4} py={12}>
      <Box
        w={16}
        h={16}
        rounded="2xl"
        bg="bg.tertiary"
        display="flex"
        alignItems="center"
        justifyContent="center"
      >
        <Icon as={FiInbox} boxSize={8} color="text.muted" />
      </Box>
      <VStack spacing={1}>
        <Text fontWeight="medium" color="text.primary">
          Aucun import en cours
        </Text>
        <Text fontSize="sm" color="text.muted" textAlign="center">
          Les nouveaux imports apparaitront automatiquement ici
        </Text>
      </VStack>
    </VStack>
  </MotionBox>
)

export default function ImportStatusPage() {
  const [activeImports, setActiveImports] = useState<ActiveImport[]>([])
  const [pollingUIDs, setPollingUIDs] = useState<Set<string>>(new Set())
  const [deletingUID, setDeletingUID] = useState<string | null>(null)
  const [recordToDelete, setRecordToDelete] = useState<ImportRecord | null>(null)
  const [sortBy, setSortBy] = useState<keyof ImportRecord>('started_at')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')
  const { isOpen, onOpen, onClose } = useDisclosure()
  const toast = useToast()
  const queryClient = useQueryClient()

  // Fetch import history
  const { data: importHistory = [], isLoading, refetch } = useQuery({
    queryKey: ['import-history'],
    queryFn: async () => {
      const response = await api.imports.history()
      return response.data
    },
    refetchInterval: 5000,
    staleTime: 0,
    gcTime: 0,
  })

  // Fetch active imports
  const { data: apiActiveImports = [] } = useQuery({
    queryKey: ['active-imports'],
    queryFn: async () => {
      const response = await api.imports.active()
      return response.data
    },
    refetchInterval: 10000,
    staleTime: 0,
    gcTime: 0,
  })

  // Combine and categorize imports
  const combinedActiveImports = [
    ...apiActiveImports.map((imp: any) => ({ ...imp, source: 'api' })),
    ...activeImports.filter((imp: ImportRecord) => !apiActiveImports.find((api: any) => api.uid === imp.uid))
  ]

  const currentImportFromActive = combinedActiveImports.find((imp: any) =>
    imp.status === 'processing' || imp.status === 'in_progress'
  )
  const currentImportFromHistory = importHistory.find((imp: ImportRecord) =>
    imp.status === 'processing' || imp.status === 'in_progress'
  )
  const currentImport = currentImportFromActive || currentImportFromHistory

  const queuedImportsFromActive = combinedActiveImports.filter((imp: any) =>
    imp.status === 'pending' || imp.status === 'queued'
  )
  const queuedImportsFromHistory = importHistory.filter((imp: ImportRecord) =>
    imp.status === 'pending' || imp.status === 'queued'
  )

  const queuedImportsMap = new Map()
  queuedImportsFromHistory.forEach((imp: ImportRecord) => queuedImportsMap.set(imp.uid, imp))
  queuedImportsFromActive.forEach((imp: any) => queuedImportsMap.set(imp.uid, imp))
  const queuedImports = Array.from(queuedImportsMap.values())

  const historyImports = importHistory.filter((imp: ImportRecord) => {
    const isCompleted = imp.status === 'completed' || imp.status === 'done' || imp.status === 'failed'
    const isNotCurrentImport = !currentImport || imp.uid !== currentImport.uid
    const isNotInQueue = !queuedImports.some((queued: any) => queued.uid === imp.uid)
    return isCompleted && isNotCurrentImport && isNotInQueue
  })

  // Polling logic
  const checkImportStatus = async (uid: string) => {
    try {
      const response = await api.status.get(uid)
      return response.data
    } catch (error) {
      console.error(`Erreur lors de la verification du statut pour ${uid}:`, error)
      return null
    }
  }

  const startPolling = useCallback((activeImport: ActiveImport) => {
    if (pollingUIDs.has(activeImport.uid)) return

    setPollingUIDs(prev => {
      const newSet = new Set(prev)
      newSet.add(activeImport.uid)
      return newSet
    })

    const pollInterval = setInterval(async () => {
      const statusData = await checkImportStatus(activeImport.uid)

      if (statusData) {
        setActiveImports(prev =>
          prev.map(imp =>
            imp.uid === activeImport.uid ? { ...imp, ...statusData } : imp
          )
        )

        if (statusData.status === 'completed' || statusData.status === 'done' || statusData.status === 'failed') {
          clearInterval(pollInterval)
          setPollingUIDs(prev => {
            const newSet = new Set(prev)
            newSet.delete(activeImport.uid)
            return newSet
          })
          setActiveImports(prev => prev.filter((imp: ImportRecord) => imp.uid !== activeImport.uid))
          refetch()

          toast({
            title: statusData.status === 'failed' ? 'Echec de l\'import' : 'Import termine',
            description: statusData.status === 'failed'
              ? `Erreur lors du traitement de ${activeImport.filename}`
              : `${activeImport.filename} traite avec succes`,
            status: statusData.status === 'failed' ? 'error' : 'success',
            duration: 5000,
            isClosable: true,
            position: 'top',
          })
        }
      }
    }, 3000)

    setTimeout(() => {
      clearInterval(pollInterval)
      setPollingUIDs(prev => {
        const newSet = new Set(prev)
        newSet.delete(activeImport.uid)
        return newSet
      })
    }, 1800000)
  }, [pollingUIDs, toast, refetch])

  useEffect(() => {
    activeImports.forEach(activeImport => {
      if (!pollingUIDs.has(activeImport.uid) &&
          (activeImport.status === 'processing' || activeImport.status === 'in_progress')) {
        startPolling(activeImport)
      }
    })
  }, [activeImports]) // eslint-disable-line react-hooks/exhaustive-deps

  // Delete handlers
  const openDeleteModal = (record: ImportRecord) => {
    setRecordToDelete(record)
    onOpen()
  }

  const confirmDelete = async () => {
    if (!recordToDelete) return

    onClose()
    setDeletingUID(recordToDelete.uid)

    try {
      const response = await api.imports.delete(recordToDelete.uid)

      if (response.success) {
        toast({
          title: 'Import supprime',
          description: `L'import "${recordToDelete.filename}" a ete supprime`,
          status: 'success',
          duration: 5000,
          isClosable: true,
          position: 'top',
        })
        refetch()
        queryClient.invalidateQueries({ queryKey: ['import-history'] })
        queryClient.invalidateQueries({ queryKey: ['active-imports'] })
      }
    } catch (error: any) {
      console.error('Erreur lors de la suppression:', error)
      toast({
        title: 'Erreur de suppression',
        description: error.response?.data?.error || 'Impossible de supprimer l\'import',
        status: 'error',
        duration: 8000,
        isClosable: true,
        position: 'top',
      })
    } finally {
      setDeletingUID(null)
      setRecordToDelete(null)
    }
  }

  // Sorting
  const handleSort = (column: keyof ImportRecord) => {
    if (sortBy === column) {
      setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc')
    } else {
      setSortBy(column)
      setSortOrder('desc')
    }
  }

  const sortedHistoryImports = [...historyImports].sort((a, b) => {
    const aValue = a[sortBy] || ''
    const bValue = b[sortBy] || ''

    if (sortBy === 'started_at') {
      const aDate = new Date(aValue as string).getTime()
      const bDate = new Date(bValue as string).getTime()
      return sortOrder === 'asc' ? aDate - bDate : bDate - aDate
    }

    if (typeof aValue === 'string' && typeof bValue === 'string') {
      return sortOrder === 'asc' ? aValue.localeCompare(bValue) : bValue.localeCompare(aValue)
    }

    if (typeof aValue === 'number' && typeof bValue === 'number') {
      return sortOrder === 'asc' ? aValue - bValue : bValue - aValue
    }

    return 0
  })

  const formatDuration = (seconds?: number) => {
    if (!seconds) return '-'
    const minutes = Math.floor(seconds / 60)
    const remainingSeconds = seconds % 60
    return `${minutes}m ${remainingSeconds}s`
  }

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleString('fr-FR')
  }

  const getSolutionLabel = (record: ImportRecord) => {
    if (record.solution) return record.solution
    if (record.client) return record.client
    return '-'
  }

  // Sort indicator
  const SortIndicator = ({ column }: { column: keyof ImportRecord }) => (
    sortBy === column ? (
      <Text as="span" ml={1} color="brand.400">
        {sortOrder === 'asc' ? '↑' : '↓'}
      </Text>
    ) : null
  )

  return (
    <Box maxW="1200px" mx="auto">
      {/* Header */}
      <MotionBox
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
        mb={8}
      >
        <HStack justify="space-between" align="start">
          <VStack align="start" spacing={2}>
            <HStack spacing={3}>
              <Box
                w={10}
                h={10}
                rounded="lg"
                bgGradient="linear(to-br, brand.500, accent.400)"
                display="flex"
                alignItems="center"
                justifyContent="center"
                boxShadow="0 0 20px rgba(99, 102, 241, 0.3)"
              >
                <Icon as={FiActivity} boxSize={5} color="white" />
              </Box>
              <Text fontSize="2xl" fontWeight="bold" color="text.primary">
                Suivi des imports
              </Text>
            </HStack>
            <Text color="text.secondary" pl={13}>
              Visualisez les imports en cours et l'historique
            </Text>
          </VStack>

          <Tooltip label="Actualiser">
            <IconButton
              aria-label="Actualiser"
              icon={<Icon as={FiRefreshCw} />}
              size="sm"
              variant="ghost"
              color="text.muted"
              onClick={() => refetch()}
              isLoading={isLoading}
              _hover={{ color: 'text.primary', bg: 'bg.hover' }}
            />
          </Tooltip>
        </HStack>
      </MotionBox>

      <VStack spacing={6} align="stretch">
        {/* Current Import */}
        {currentImport && (
          <Box>
            <Text fontSize="sm" fontWeight="medium" color="text.muted" mb={3} textTransform="uppercase" letterSpacing="wide">
              Import en cours
            </Text>
            <CurrentImportCard currentImport={currentImport} />
          </Box>
        )}

        {/* Queued Imports */}
        {queuedImports.length > 0 && (
          <Box>
            <Text fontSize="sm" fontWeight="medium" color="text.muted" mb={3} textTransform="uppercase" letterSpacing="wide">
              En attente ({queuedImports.length})
            </Text>
            <VStack spacing={2} align="stretch">
              {queuedImports.map((queuedImport, index) => (
                <QueuedImportItem key={queuedImport.uid} queuedImport={queuedImport} index={index} />
              ))}
            </VStack>
          </Box>
        )}

        {/* Empty State */}
        {!currentImport && queuedImports.length === 0 && (
          <Box
            bg="bg.secondary"
            border="1px solid"
            borderColor="border.default"
            rounded="xl"
          >
            <EmptyState />
          </Box>
        )}

        {/* History */}
        <Box>
          <HStack justify="space-between" mb={3}>
            <Text fontSize="sm" fontWeight="medium" color="text.muted" textTransform="uppercase" letterSpacing="wide">
              Historique
            </Text>
            <Tooltip label="Synchroniser les imports orphelins">
              <IconButton
                aria-label="Synchroniser"
                icon={<Icon as={FiRefreshCw} />}
                size="xs"
                variant="ghost"
                color="text.muted"
                _hover={{ color: 'brand.400', bg: 'bg.hover' }}
                onClick={async () => {
                  try {
                    await api.imports.sync()
                    queryClient.invalidateQueries({ queryKey: ['import-history'] })
                    queryClient.invalidateQueries({ queryKey: ['active-imports'] })
                    toast({
                      title: 'Synchronisation effectuee',
                      status: 'success',
                      duration: 3000,
                      isClosable: true,
                      position: 'top',
                    })
                  } catch (error: any) {
                    toast({
                      title: 'Erreur de synchronisation',
                      description: error.response?.data?.error || 'Impossible de synchroniser',
                      status: 'error',
                      duration: 5000,
                      isClosable: true,
                      position: 'top',
                    })
                  }
                }}
              />
            </Tooltip>
          </HStack>

          <Box
            bg="bg.secondary"
            border="1px solid"
            borderColor="border.default"
            rounded="xl"
            overflow="hidden"
          >
            {isLoading ? (
              <Flex justify="center" p={12}>
                <Spinner size="lg" color="brand.500" />
              </Flex>
            ) : historyImports.length === 0 ? (
              <VStack py={12}>
                <Text color="text.muted">Aucun import dans l'historique</Text>
              </VStack>
            ) : (
              <Box overflowX="auto">
                <Table variant="unstyled" size="sm">
                  <Thead>
                    <Tr borderBottom="1px solid" borderColor="border.default">
                      <Th
                        color="text.muted"
                        fontSize="xs"
                        fontWeight="medium"
                        textTransform="uppercase"
                        letterSpacing="wide"
                        py={4}
                        cursor="pointer"
                        _hover={{ color: 'text.primary' }}
                        onClick={() => handleSort('filename')}
                      >
                        Fichier <SortIndicator column="filename" />
                      </Th>
                      <Th color="text.muted" fontSize="xs" fontWeight="medium" textTransform="uppercase" letterSpacing="wide" py={4}>
                        Type
                      </Th>
                      <Th
                        color="text.muted"
                        fontSize="xs"
                        fontWeight="medium"
                        textTransform="uppercase"
                        letterSpacing="wide"
                        py={4}
                        cursor="pointer"
                        _hover={{ color: 'text.primary' }}
                        onClick={() => handleSort('solution')}
                      >
                        Solution <SortIndicator column="solution" />
                      </Th>
                      <Th
                        color="text.muted"
                        fontSize="xs"
                        fontWeight="medium"
                        textTransform="uppercase"
                        letterSpacing="wide"
                        py={4}
                        cursor="pointer"
                        _hover={{ color: 'text.primary' }}
                        onClick={() => handleSort('status')}
                      >
                        Statut <SortIndicator column="status" />
                      </Th>
                      <Th
                        color="text.muted"
                        fontSize="xs"
                        fontWeight="medium"
                        textTransform="uppercase"
                        letterSpacing="wide"
                        py={4}
                        cursor="pointer"
                        _hover={{ color: 'text.primary' }}
                        onClick={() => handleSort('started_at')}
                      >
                        Date <SortIndicator column="started_at" />
                      </Th>
                      <Th
                        color="text.muted"
                        fontSize="xs"
                        fontWeight="medium"
                        textTransform="uppercase"
                        letterSpacing="wide"
                        py={4}
                        cursor="pointer"
                        _hover={{ color: 'text.primary' }}
                        onClick={() => handleSort('duration')}
                      >
                        Duree <SortIndicator column="duration" />
                      </Th>
                      <Th
                        color="text.muted"
                        fontSize="xs"
                        fontWeight="medium"
                        textTransform="uppercase"
                        letterSpacing="wide"
                        py={4}
                        cursor="pointer"
                        _hover={{ color: 'text.primary' }}
                        onClick={() => handleSort('chunks_inserted')}
                      >
                        Chunks <SortIndicator column="chunks_inserted" />
                      </Th>
                      <Th color="text.muted" fontSize="xs" fontWeight="medium" textTransform="uppercase" letterSpacing="wide" py={4}>
                        Actions
                      </Th>
                    </Tr>
                  </Thead>
                  <Tbody>
                    {sortedHistoryImports.map((record: ImportRecord) => (
                      <Tr
                        key={record.uid}
                        borderBottom="1px solid"
                        borderColor="border.default"
                        _hover={{ bg: 'bg.hover' }}
                        transition="background 0.15s"
                      >
                        <Td py={4}>
                          <VStack align="start" spacing={0.5}>
                            {record.import_type === 'fill_rfp' && record.status === 'completed' ? (
                              <Button
                                as="a"
                                href={`/api/downloads/filled-rfp/${record.uid}`}
                                download
                                variant="link"
                                color="brand.400"
                                fontWeight="medium"
                                size="sm"
                                p={0}
                                h="auto"
                                leftIcon={<Icon as={FiDownload} />}
                                _hover={{ color: 'brand.300' }}
                              >
                                {record.filename}
                              </Button>
                            ) : (
                              <Text fontWeight="medium" color="text.primary" fontSize="sm">
                                {record.filename}
                              </Text>
                            )}
                            <Text fontSize="xs" color="text.muted">
                              {record.uid.slice(0, 8)}...
                            </Text>
                          </VStack>
                        </Td>
                        <Td py={4}>
                          <TypeBadge record={record} />
                        </Td>
                        <Td py={4}>
                          <Text fontSize="sm" color="text.secondary">
                            {getSolutionLabel(record)}
                          </Text>
                        </Td>
                        <Td py={4}>
                          <VStack align="start" spacing={1}>
                            <StatusBadge status={record.status} />
                            {record.error_message && (
                              <Tooltip label={record.error_message}>
                                <HStack spacing={1} cursor="help">
                                  <Icon as={FiAlertTriangle} boxSize={3} color="red.400" />
                                  <Text fontSize="xs" color="red.400">Erreur</Text>
                                </HStack>
                              </Tooltip>
                            )}
                          </VStack>
                        </Td>
                        <Td py={4}>
                          <Text fontSize="sm" color="text.secondary">
                            {formatDate(record.started_at)}
                          </Text>
                        </Td>
                        <Td py={4}>
                          <Text fontSize="sm" color="text.secondary">
                            {formatDuration(record.duration)}
                          </Text>
                        </Td>
                        <Td py={4}>
                          <Text fontSize="sm" color="text.secondary">
                            {record.chunks_inserted || '-'}
                          </Text>
                        </Td>
                        <Td py={4}>
                          <Tooltip label="Supprimer l'import">
                            <IconButton
                              aria-label="Supprimer"
                              icon={<Icon as={FiTrash2} />}
                              size="sm"
                              variant="ghost"
                              color="text.muted"
                              isLoading={deletingUID === record.uid}
                              onClick={() => openDeleteModal(record)}
                              isDisabled={record.status === 'processing' || record.status === 'in_progress'}
                              _hover={{ color: 'red.400', bg: 'rgba(239, 68, 68, 0.1)' }}
                            />
                          </Tooltip>
                        </Td>
                      </Tr>
                    ))}
                  </Tbody>
                </Table>
              </Box>
            )}
          </Box>
        </Box>
      </VStack>

      {/* Delete Confirmation Modal */}
      <Modal isOpen={isOpen} onClose={onClose} size="lg" isCentered>
        <ModalOverlay bg="rgba(0, 0, 0, 0.7)" backdropFilter="blur(4px)" />
        <ModalContent
          bg="bg.secondary"
          border="1px solid"
          borderColor="border.default"
          rounded="xl"
        >
          <ModalHeader>
            <HStack spacing={3}>
              <Box
                w={10}
                h={10}
                rounded="lg"
                bg="rgba(239, 68, 68, 0.15)"
                display="flex"
                alignItems="center"
                justifyContent="center"
              >
                <Icon as={FiAlertTriangle} boxSize={5} color="red.400" />
              </Box>
              <Text color="text.primary">Confirmer la suppression</Text>
            </HStack>
          </ModalHeader>
          <ModalCloseButton color="text.muted" />
          <ModalBody>
            {recordToDelete && (
              <VStack align="start" spacing={4}>
                <Text color="text.secondary">
                  Etes-vous sur de vouloir supprimer completement l'import{' '}
                  <Text as="span" fontWeight="bold" color="red.400">
                    "{recordToDelete.filename}"
                  </Text>
                  ?
                </Text>

                <Box
                  w="full"
                  p={4}
                  bg="rgba(239, 68, 68, 0.08)"
                  border="1px solid"
                  borderColor="rgba(239, 68, 68, 0.2)"
                  rounded="lg"
                >
                  <HStack mb={2}>
                    <Icon as={FiAlertTriangle} color="red.400" />
                    <Text fontWeight="medium" color="red.400">
                      Action irreversible
                    </Text>
                  </HStack>
                  <Text fontSize="sm" color="text.secondary">
                    Tous les chunks, fichiers et metadonnees seront supprimes definitivement.
                  </Text>
                </Box>
              </VStack>
            )}
          </ModalBody>

          <ModalFooter gap={3}>
            <Button
              variant="ghost"
              onClick={onClose}
              color="text.secondary"
              _hover={{ bg: 'bg.hover' }}
            >
              Annuler
            </Button>
            <Button
              bg="red.500"
              color="white"
              onClick={confirmDelete}
              isLoading={deletingUID === recordToDelete?.uid}
              loadingText="Suppression..."
              _hover={{ bg: 'red.600' }}
            >
              Supprimer definitivement
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
    </Box>
  )
}
