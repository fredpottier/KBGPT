'use client'

import {
  Box,
  Button,
  Card,
  CardBody,
  CardHeader,
  Heading,
  Text,
  VStack,
  HStack,
  Badge,
  Table,
  Thead,
  Tbody,
  Tr,
  Th,
  Td,
  Spinner,
  useToast,
  Alert,
  AlertIcon,
  AlertTitle,
  AlertDescription,
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
  List,
  ListItem,
  ListIcon,
  Icon,
} from '@chakra-ui/react'
import { useState, useEffect, useCallback } from 'react'
import { RepeatIcon, DeleteIcon, WarningIcon } from '@chakra-ui/icons'
import { FiDownload } from 'react-icons/fi'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'

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
  import_type?: 'document' | 'excel_qa' | 'fill_rfp' // Pour distinguer les types d'imports
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
}

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

  // Récupérer l'historique des imports
  const { data: importHistory = [], isLoading, refetch } = useQuery({
    queryKey: ['import-history'], // Fixed key
    queryFn: async () => {
      const response = await api.imports.history()
      return response.data
    },
    refetchInterval: 5000,
    staleTime: 0, // Always consider data stale
    gcTime: 0, // Don't cache at all (new React Query syntax)
  })

  // Récupérer les imports actifs depuis l'API
  const { data: apiActiveImports = [] } = useQuery({
    queryKey: ['active-imports'], // Fixed key
    queryFn: async () => {
      const response = await api.imports.active()
      return response.data
    },
    refetchInterval: 10000,
    staleTime: 0, // Always consider data stale
    gcTime: 0, // Don't cache at all
  })

  // Séparer les imports en 3 catégories
  const combinedActiveImports = [
    ...apiActiveImports.map((imp: any) => ({
      ...imp,
      source: 'api'
    })),
    ...activeImports.filter((imp: ImportRecord) => !apiActiveImports.find((api: any) => api.uid === imp.uid))
  ]

  // Import en cours (status = processing/in_progress) - chercher aussi dans l'historique
  const currentImportFromActive = combinedActiveImports.find((imp: any) =>
    imp.status === 'processing' || imp.status === 'in_progress'
  )
  const currentImportFromHistory = importHistory.find((imp: ImportRecord) =>
    imp.status === 'processing' || imp.status === 'in_progress'
  )
  const currentImport = currentImportFromActive || currentImportFromHistory

  // Imports en attente (status = pending/queued) - chercher aussi dans l'historique
  const queuedImportsFromActive = combinedActiveImports.filter((imp: any) =>
    imp.status === 'pending' || imp.status === 'queued'
  )
  const queuedImportsFromHistory = importHistory.filter((imp: ImportRecord) =>
    imp.status === 'pending' || imp.status === 'queued'
  )

  // Dédoublonner par UID (priorité aux données de /active)
  const queuedImportsMap = new Map()
  queuedImportsFromHistory.forEach((imp: ImportRecord) => queuedImportsMap.set(imp.uid, imp))
  queuedImportsFromActive.forEach((imp: any) => queuedImportsMap.set(imp.uid, imp)) // écrase si doublon
  const queuedImports = Array.from(queuedImportsMap.values())

  // Historique (tous les imports terminés ou ayant échoué)
  // Exclure explicitement les imports qui sont en cours ou en attente
  const historyImports = importHistory.filter((imp: ImportRecord) => {
    // Seulement les imports réellement terminés
    const isCompleted = imp.status === 'completed' || imp.status === 'done' || imp.status === 'failed'

    // Exclure l'import en cours (s'il y en a un)
    const isNotCurrentImport = !currentImport || imp.uid !== currentImport.uid

    // Exclure les imports en attente
    const isNotInQueue = !queuedImports.some((queued: any) => queued.uid === imp.uid)

    return isCompleted && isNotCurrentImport && isNotInQueue
  })


  // Fonction pour vérifier le statut d'un import actif
  const checkImportStatus = async (uid: string) => {
    try {
      const response = await api.status.get(uid)
      return response.data
    } catch (error) {
      console.error(`Erreur lors de la vérification du statut pour ${uid}:`, error)
      return null
    }
  }

  // Démarrer le polling pour un import
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
        // Mettre à jour l'import actif
        setActiveImports(prev =>
          prev.map(imp =>
            imp.uid === activeImport.uid
              ? { ...imp, ...statusData }
              : imp
          )
        )

        // Arrêter le polling si terminé
        if (statusData.status === 'completed' || statusData.status === 'done' || statusData.status === 'failed') {
          clearInterval(pollInterval)
          setPollingUIDs(prev => {
            const newSet = new Set(prev)
            newSet.delete(activeImport.uid)
            return newSet
          })

          // Retirer de la liste des imports actifs
          setActiveImports(prev => prev.filter((imp: ImportRecord) => imp.uid !== activeImport.uid))

          // Rafraîchir l'historique
          refetch()

          // Toast de notification
          if (statusData.status === 'completed' || statusData.status === 'done') {
            toast({
              title: 'Import terminé !',
              description: `${activeImport.filename} traité avec succès`,
              status: 'success',
              duration: 5000,
              isClosable: true,
            })
          } else if (statusData.status === 'failed') {
            toast({
              title: 'Échec de l\'import',
              description: `Erreur lors du traitement de ${activeImport.filename}`,
              status: 'error',
              duration: 8000,
              isClosable: true,
            })
          }
        }
      }
    }, 3000) // Vérifier toutes les 3 secondes

    // Timeout après 30 minutes
    setTimeout(() => {
      clearInterval(pollInterval)
      setPollingUIDs(prev => {
        const newSet = new Set(prev)
        newSet.delete(activeImport.uid)
        return newSet
      })
    }, 1800000) // 30 minutes
  }, [pollingUIDs, toast, refetch])

  // Fonction pour ouvrir le modal de confirmation
  const openDeleteModal = (record: ImportRecord) => {
    setRecordToDelete(record)
    onOpen()
  }

  // Fonction pour supprimer complètement un import
  const confirmDelete = async () => {
    if (!recordToDelete) return

    onClose()
    setDeletingUID(recordToDelete.uid)

    try {
      const response = await api.imports.delete(recordToDelete.uid)

      if (response.success) {
        toast({
          title: 'Import supprimé',
          description: `L'import "${recordToDelete.filename}" a été supprimé complètement`,
          status: 'success',
          duration: 5000,
          isClosable: true,
        })
        // Rafraîchir l'historique et les imports actifs
        refetch()

        // Invalider et refetch tous les caches React Query liés aux imports
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
      })
    } finally {
      setDeletingUID(null)
      setRecordToDelete(null)
    }
  }



  // Démarrer le polling pour tous les imports actifs au chargement
  useEffect(() => {
    activeImports.forEach(activeImport => {
      if (!pollingUIDs.has(activeImport.uid) &&
          (activeImport.status === 'processing' || activeImport.status === 'in_progress')) {
        startPolling(activeImport)
      }
    })
  }, [activeImports]) // eslint-disable-line react-hooks/exhaustive-deps

  const getStatusColor = (status: string) => {
    switch (status.toLowerCase()) {
      case 'completed':
      case 'done':
        return 'green'
      case 'failed':
      case 'error':
        return 'red'
      case 'processing':
      case 'in_progress':
        return 'blue'
      default:
        return 'yellow'
    }
  }

  const getStatusLabel = (status: string) => {
    switch (status.toLowerCase()) {
      case 'completed':
      case 'done':
        return 'Terminé'
      case 'failed':
      case 'error':
        return 'Échec'
      case 'processing':
      case 'in_progress':
        return 'En cours'
      case 'pending':
        return 'En attente'
      default:
        return status
    }
  }

  const formatDuration = (seconds?: number) => {
    if (!seconds) return '-'
    const minutes = Math.floor(seconds / 60)
    const remainingSeconds = seconds % 60
    return `${minutes}m ${remainingSeconds}s`
  }

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleString('fr-FR')
  }

  // Fonction pour gérer le tri des colonnes
  const handleSort = (column: keyof ImportRecord) => {
    if (sortBy === column) {
      setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc')
    } else {
      setSortBy(column)
      setSortOrder('desc')
    }
  }

  // Fonction pour trier les données d'historique
  const sortedHistoryImports = [...historyImports].sort((a, b) => {
    const aValue = a[sortBy] || ''
    const bValue = b[sortBy] || ''

    if (sortBy === 'started_at') {
      const aDate = new Date(aValue as string).getTime()
      const bDate = new Date(bValue as string).getTime()
      return sortOrder === 'asc' ? aDate - bDate : bDate - aDate
    }

    if (typeof aValue === 'string' && typeof bValue === 'string') {
      return sortOrder === 'asc'
        ? aValue.localeCompare(bValue)
        : bValue.localeCompare(aValue)
    }

    if (typeof aValue === 'number' && typeof bValue === 'number') {
      return sortOrder === 'asc' ? aValue - bValue : bValue - aValue
    }

    return 0
  })

  // Fonction pour déterminer le type d'import
  const getImportTypeLabel = (record: ImportRecord) => {
    if (record.import_type === 'excel_qa') return 'Excel Q/R'
    if (record.import_type === 'fill_rfp') return 'RFP Complété'
    if (record.filename?.toLowerCase().endsWith('.xlsx')) return 'Excel Q/R'
    if (record.filename?.toLowerCase().endsWith('.pptx')) return 'PPTX'
    if (record.filename?.toLowerCase().endsWith('.pdf')) return 'PDF'
    return 'Document'
  }

  // Fonction pour déterminer la solution
  const getSolutionLabel = (record: ImportRecord) => {
    if (record.solution) return record.solution
    if (record.client) return record.client
    return '-'
  }

  return (
    <VStack spacing={6} align="stretch" maxW="1200px" mx="auto">
      <Box>
        <Heading size="lg" mb={2}>
          Suivi des imports
        </Heading>
        <Text color="gray.600">
          Visualisez les imports en cours et l'historique des traitements
        </Text>
      </Box>

      {/* 1. Import en cours */}
      {currentImport && (
        <Card>
          <CardHeader>
            <Heading size="md">Import en cours</Heading>
          </CardHeader>
          <CardBody>
            <Box
              p={4}
              border="1px"
              borderColor="blue.200"
              borderRadius="md"
              bg="blue.50"
            >
              <HStack justify="space-between" mb={2}>
                <VStack align="start" spacing={1} flex={1}>
                  <Text fontWeight="semibold">{currentImport.filename}</Text>
                  <Text fontSize="sm" color="gray.600">
                    Client: {currentImport.client}
                  </Text>
                  <Text fontSize="sm" color="gray.600">
                    Démarré: {formatDate(currentImport.started_at)}
                  </Text>
                </VStack>
                <VStack align="end" spacing={1}>
                  <HStack>
                    <Spinner size="sm" color="blue.500" />
                    <Text fontSize="sm" color="blue.600">En cours...</Text>
                  </HStack>
                </VStack>
              </HStack>

              {/* Affichage de la progression détaillée */}
              {currentImport.current_step && (
                <Box mb={3} w="full">
                  <HStack justify="space-between" mb={2}>
                    <Text fontSize="sm" fontWeight="medium" color="blue.700">
                      {currentImport.current_step}
                    </Text>
                    {currentImport.progress_percentage !== undefined && (
                      <Text fontSize="xs" color="gray.600">
                        {currentImport.progress_percentage}%
                      </Text>
                    )}
                  </HStack>

                  {currentImport.progress_percentage !== undefined && (
                    <Progress
                      value={currentImport.progress_percentage}
                      size="sm"
                      colorScheme="blue"
                      bg="gray.100"
                      borderRadius="md"
                    />
                  )}

                  {currentImport.step_message && (
                    <Text fontSize="xs" color="gray.600" mt={1}>
                      {currentImport.step_message}
                    </Text>
                  )}

                  {currentImport.progress && currentImport.total_steps && (
                    <Text fontSize="xs" color="gray.500" mt={1}>
                      Étape {currentImport.progress} sur {currentImport.total_steps}
                    </Text>
                  )}
                </Box>
              )}

              {currentImport.chunks_inserted !== undefined && (
                <Text fontSize="sm" color="green.600">
                  ✅ {currentImport.chunks_inserted} chunks insérés
                </Text>
              )}
            </Box>
          </CardBody>
        </Card>
      )}

      {/* 2. Imports en attente */}
      {queuedImports.length > 0 && (
        <Card>
          <CardHeader>
            <Heading size="md">Imports en attente</Heading>
          </CardHeader>
          <CardBody>
            <VStack spacing={3} align="stretch">
              {queuedImports.map((queuedImport, index) => (
                <Box
                  key={queuedImport.uid}
                  p={3}
                  border="1px"
                  borderColor="orange.200"
                  borderRadius="md"
                  bg="orange.50"
                >
                  <HStack justify="space-between">
                    <VStack align="start" spacing={1} flex={1}>
                      <HStack>
                        <Badge colorScheme="orange" size="sm">#{index + 1}</Badge>
                        <Text fontWeight="semibold">{queuedImport.filename}</Text>
                      </HStack>
                      <Text fontSize="sm" color="gray.600">
                        Client: {queuedImport.client}
                      </Text>
                    </VStack>
                    <Badge colorScheme="orange">En attente</Badge>
                  </HStack>
                </Box>
              ))}
            </VStack>
          </CardBody>
        </Card>
      )}

      {/* Message si aucun import */}
      {!currentImport && queuedImports.length === 0 && (
        <Alert status="info">
          <AlertIcon />
          <Box>
            <AlertTitle>Aucun import en cours</AlertTitle>
            <AlertDescription>
              Les nouveaux imports apparaîtront automatiquement ici dès qu'ils seront lancés.
            </AlertDescription>
          </Box>
        </Alert>
      )}

      {/* 3. Historique des imports */}
      <Card>
        <CardHeader>
          <HStack justify="space-between">
            <Heading size="md">Historique des imports</Heading>
            <HStack spacing={2}>
              <Tooltip label="Synchroniser les imports orphelins">
                <IconButton
                  aria-label="Synchroniser"
                  icon={<RepeatIcon />}
                  size="sm"
                  colorScheme="blue"
                  variant="outline"
                  onClick={async () => {
                    try {
                      await api.imports.sync()
                      queryClient.invalidateQueries({ queryKey: ['import-history'] })
                      queryClient.invalidateQueries({ queryKey: ['active-imports'] })
                      toast({
                        title: 'Synchronisation effectuée',
                        description: 'Les imports orphelins ont été synchronisés',
                        status: 'success',
                        duration: 3000,
                        isClosable: true,
                      })
                    } catch (error: any) {
                      toast({
                        title: 'Erreur de synchronisation',
                        description: error.response?.data?.error || 'Impossible de synchroniser',
                        status: 'error',
                        duration: 5000,
                        isClosable: true,
                      })
                    }
                  }}
                />
              </Tooltip>
              <Tooltip label="Actualiser">
                <IconButton
                  aria-label="Actualiser"
                  icon={<RepeatIcon />}
                  size="sm"
                  onClick={() => refetch()}
                  isLoading={isLoading}
                />
              </Tooltip>
            </HStack>
          </HStack>
        </CardHeader>
        <CardBody>
          {isLoading ? (
            <Flex justify="center" p={8}>
              <Spinner size="lg" />
            </Flex>
          ) : historyImports.length === 0 ? (
            <Text color="gray.500" textAlign="center" py={8}>
              Aucun import dans l'historique
            </Text>
          ) : (
            <Box overflowX="auto">
              <Table variant="simple" size="sm">
                <Thead>
                  <Tr>
                    <Th
                      cursor="pointer"
                      _hover={{ bg: "gray.50" }}
                      onClick={() => handleSort('filename')}
                    >
                      Fichier {sortBy === 'filename' && (sortOrder === 'asc' ? '↑' : '↓')}
                    </Th>
                    <Th>Type</Th>
                    <Th
                      cursor="pointer"
                      _hover={{ bg: "gray.50" }}
                      onClick={() => handleSort('solution')}
                    >
                      Solution {sortBy === 'solution' && (sortOrder === 'asc' ? '↑' : '↓')}
                    </Th>
                    <Th
                      cursor="pointer"
                      _hover={{ bg: "gray.50" }}
                      onClick={() => handleSort('status')}
                    >
                      Statut {sortBy === 'status' && (sortOrder === 'asc' ? '↑' : '↓')}
                    </Th>
                    <Th
                      cursor="pointer"
                      _hover={{ bg: "gray.50" }}
                      onClick={() => handleSort('started_at')}
                    >
                      Démarré {sortBy === 'started_at' && (sortOrder === 'asc' ? '↑' : '↓')}
                    </Th>
                    <Th
                      cursor="pointer"
                      _hover={{ bg: "gray.50" }}
                      onClick={() => handleSort('duration')}
                    >
                      Durée {sortBy === 'duration' && (sortOrder === 'asc' ? '↑' : '↓')}
                    </Th>
                    <Th
                      cursor="pointer"
                      _hover={{ bg: "gray.50" }}
                      onClick={() => handleSort('chunks_inserted')}
                    >
                      Chunks {sortBy === 'chunks_inserted' && (sortOrder === 'asc' ? '↑' : '↓')}
                    </Th>
                    <Th>Actions</Th>
                  </Tr>
                </Thead>
                <Tbody>
                  {sortedHistoryImports.map((record: ImportRecord) => (
                    <Tr key={record.uid}>
                      <Td>
                        <VStack align="start" spacing={1}>
                          {record.import_type === 'fill_rfp' && record.status === 'completed' ? (
                            <Button
                              as="a"
                              href={`/api/downloads/filled-rfp/${record.uid}`}
                              download
                              variant="link"
                              colorScheme="blue"
                              fontWeight="medium"
                              size="sm"
                              p={0}
                              h="auto"
                              minH="auto"
                              leftIcon={<Icon as={FiDownload} />}
                            >
                              {record.filename}
                            </Button>
                          ) : (
                            <Text fontWeight="medium">{record.filename}</Text>
                          )}
                          <Text fontSize="xs" color="gray.500">
                            {record.uid}
                          </Text>
                        </VStack>
                      </Td>
                      <Td>
                        <Badge
                          colorScheme={
                            getImportTypeLabel(record) === 'Excel Q/R' ? 'green' :
                            getImportTypeLabel(record) === 'RFP Complété' ? 'purple' : 'blue'
                          }
                          variant="subtle"
                          fontSize="xs"
                        >
                          {getImportTypeLabel(record)}
                        </Badge>
                      </Td>
                      <Td>
                        <Text fontSize="sm" fontWeight="medium">
                          {getSolutionLabel(record)}
                        </Text>
                      </Td>
                      <Td>
                        <Badge colorScheme={getStatusColor(record.status)}>
                          {getStatusLabel(record.status)}
                        </Badge>
                        {record.error_message && (
                          <Tooltip label={record.error_message}>
                            <Text fontSize="xs" color="red.500" mt={1}>
                              Erreur
                            </Text>
                          </Tooltip>
                        )}
                      </Td>
                      <Td fontSize="sm">
                        {formatDate(record.started_at)}
                      </Td>
                      <Td fontSize="sm">
                        {formatDuration(record.duration)}
                      </Td>
                      <Td>
                        {record.chunks_inserted || '-'}
                      </Td>
                      <Td>
                        <Tooltip label={`Supprimer complètement l'import "${record.filename}"`}>
                          <IconButton
                            aria-label="Supprimer import"
                            icon={<DeleteIcon />}
                            size="sm"
                            colorScheme="red"
                            variant="ghost"
                            isLoading={deletingUID === record.uid}
                            onClick={() => openDeleteModal(record)}
                            isDisabled={record.status === 'processing' || record.status === 'in_progress'}
                          />
                        </Tooltip>
                      </Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>
            </Box>
          )}
        </CardBody>
      </Card>

      {/* Modal de confirmation de suppression */}
      <Modal isOpen={isOpen} onClose={onClose} size="lg">
        <ModalOverlay />
        <ModalContent>
          <ModalHeader>
            <HStack>
              <WarningIcon color="red.500" />
              <Text>Confirmer la suppression</Text>
            </HStack>
          </ModalHeader>
          <ModalCloseButton />
          <ModalBody>
            {recordToDelete && (
              <VStack align="start" spacing={4}>
                <Text fontSize="md">
                  Êtes-vous sûr de vouloir supprimer complètement l'import{' '}
                  <Text as="span" fontWeight="bold" color="red.600">
                    "{recordToDelete.filename}"
                  </Text>{' '}
                  ?
                </Text>

                <Alert status="warning" borderRadius="md">
                  <AlertIcon />
                  <Box>
                    <AlertTitle fontSize="sm">Cette action est irréversible !</AlertTitle>
                    <AlertDescription fontSize="sm">
                      Tous les éléments suivants seront supprimés définitivement.
                    </AlertDescription>
                  </Box>
                </Alert>

                <Box w="full">
                  <Text fontWeight="semibold" mb={2} color="gray.700">
                    Éléments qui seront supprimés :
                  </Text>
                  <List spacing={1} fontSize="sm">
                    <ListItem>
                      <ListIcon as={DeleteIcon} color="red.500" />
                      {recordToDelete.chunks_inserted || 0} chunks de la base vectorielle
                    </ListItem>
                    <ListItem>
                      <ListIcon as={DeleteIcon} color="red.500" />
                      Fichier PPTX traité
                    </ListItem>
                    <ListItem>
                      <ListIcon as={DeleteIcon} color="red.500" />
                      Fichier PDF généré
                    </ListItem>
                    <ListItem>
                      <ListIcon as={DeleteIcon} color="red.500" />
                      Images des slides
                    </ListItem>
                    <ListItem>
                      <ListIcon as={DeleteIcon} color="red.500" />
                      Images miniatures (thumbnails)
                    </ListItem>
                    <ListItem>
                      <ListIcon as={DeleteIcon} color="red.500" />
                      Enregistrement dans l'historique
                    </ListItem>
                  </List>
                </Box>
              </VStack>
            )}
          </ModalBody>

          <ModalFooter>
            <Button variant="ghost" mr={3} onClick={onClose}>
              Annuler
            </Button>
            <Button
              colorScheme="red"
              onClick={confirmDelete}
              isLoading={deletingUID === recordToDelete?.uid}
              loadingText="Suppression..."
            >
              Supprimer définitivement
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
    </VStack>
  )
}