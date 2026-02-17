'use client'

/**
 * OSMOSE Admin Backup & Restore - Dark Elegance Edition
 *
 * Sauvegarde et restauration complète du système
 */

import {
  Box,
  Button,
  Checkbox,
  HStack,
  VStack,
  Text,
  Spinner,
  Center,
  Icon,
  Input,
  useDisclosure,
  useToast,
  Modal,
  ModalOverlay,
  ModalContent,
  ModalHeader,
  ModalFooter,
  ModalBody,
  ModalCloseButton,
  SimpleGrid,
  Badge,
  Accordion,
  AccordionItem,
  AccordionButton,
  AccordionPanel,
  AccordionIcon,
  Table,
  Thead,
  Tbody,
  Tr,
  Th,
  Td,
} from '@chakra-ui/react'
import { motion } from 'framer-motion'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, useEffect } from 'react'
import { api } from '@/lib/api'
import {
  FiArchive,
  FiDownloadCloud,
  FiUploadCloud,
  FiTrash2,
  FiAlertTriangle,
  FiCheckCircle,
  FiDatabase,
  FiServer,
  FiHardDrive,
  FiFileText,
  FiClock,
  FiPackage,
  FiRefreshCw,
  FiXCircle,
  FiChevronRight,
} from 'react-icons/fi'

const MotionBox = motion(Box)

// Types
interface BackupSummary {
  name: string
  created_at: string
  size_bytes: number
  size_human: string
  industry: string
  domain_summary: string
  neo4j_nodes: number
  qdrant_points: number
  documents_count: number
  components_ok: number
  components_total: number
}

interface BackupManifest {
  backup_id: string
  name: string
  created_at: string
  duration_seconds: number
  size_bytes: number
  tenant_id: string
  osmose_version: string
  domain_context: { industry: string; domain_summary: string }
  components: {
    neo4j: any
    qdrant: any
    postgresql: any
    redis: any
    extraction_cache: any
  }
  imported_documents: Array<{ doc_id: string; primary_subject?: string }>
}

interface CurrentStats {
  neo4j_nodes: number
  neo4j_relationships: number
  neo4j_node_counts: Record<string, number>
  qdrant_collections: Record<string, number>
  qdrant_total_points: number
  postgres_sessions: number
  postgres_messages: number
  postgres_users: number
  redis_keys: number
  extraction_cache_files: number
  extraction_cache_size_bytes: number
  domain_context?: { industry: string; domain_summary: string }
  imported_documents: Array<{ doc_id: string; primary_subject?: string }>
}

interface JobStatus {
  job_id: string
  operation: string
  status: string
  name: string
  started_at: string
  progress: string
  error?: string
  log_lines: string[]
}

// Section Card
const SectionCard = ({
  title,
  subtitle,
  icon,
  children,
  variant = 'default',
  delay = 0,
}: {
  title: string
  subtitle?: string
  icon: any
  children: React.ReactNode
  variant?: 'default' | 'accent'
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
        <Box
          w={10}
          h={10}
          rounded="lg"
          bg={variant === 'accent' ? 'rgba(34, 197, 94, 0.15)' : 'rgba(99, 102, 241, 0.15)'}
          display="flex"
          alignItems="center"
          justifyContent="center"
        >
          <Icon as={icon} boxSize={5} color={variant === 'accent' ? 'green.400' : 'brand.400'} />
        </Box>
        <VStack align="start" spacing={0}>
          <Text fontWeight="semibold" color="text.primary">
            {title}
          </Text>
          {subtitle && (
            <Text fontSize="xs" color="text.muted">
              {subtitle}
            </Text>
          )}
        </VStack>
      </HStack>
      <Box p={5}>
        {children}
      </Box>
    </Box>
  </MotionBox>
)

// Status badge pour composants
const ComponentStatusBadge = ({ status }: { status: string }) => {
  const config: Record<string, { color: string; label: string }> = {
    success: { color: 'green', label: 'OK' },
    error: { color: 'red', label: 'Erreur' },
    skipped: { color: 'gray', label: 'Ignore' },
    pending: { color: 'yellow', label: 'En cours' },
  }
  const c = config[status] || config.pending
  return (
    <Badge colorScheme={c.color} fontSize="xs" rounded="md" px={2}>
      {c.label}
    </Badge>
  )
}

// Format date helper
const formatDate = (dateStr: string): string => {
  try {
    const d = new Date(dateStr)
    return d.toLocaleDateString('fr-FR', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return dateStr
  }
}

// Backup Card
const BackupCard = ({
  backup,
  onRestore,
  onDelete,
  onExpand,
  delay = 0,
}: {
  backup: BackupSummary
  onRestore: () => void
  onDelete: () => void
  onExpand: () => void
  delay?: number
}) => (
  <MotionBox
    initial={{ opacity: 0, y: 10 }}
    animate={{ opacity: 1, y: 0 }}
    transition={{ duration: 0.3, delay }}
  >
    <Box
      bg="bg.secondary"
      border="1px solid"
      borderColor="border.default"
      rounded="xl"
      p={4}
      _hover={{ borderColor: 'brand.500', transform: 'translateY(-1px)' }}
      transition="all 0.2s"
    >
      <HStack justify="space-between" mb={3}>
        <HStack spacing={3}>
          <Box
            w={10}
            h={10}
            rounded="lg"
            bg="rgba(99, 102, 241, 0.15)"
            display="flex"
            alignItems="center"
            justifyContent="center"
          >
            <Icon as={FiArchive} boxSize={5} color="brand.400" />
          </Box>
          <VStack align="start" spacing={0}>
            <Text fontWeight="bold" color="text.primary" fontSize="md">
              {backup.name}
            </Text>
            <HStack spacing={2}>
              <Text fontSize="xs" color="text.muted">
                {formatDate(backup.created_at)}
              </Text>
              {backup.industry && (
                <Badge colorScheme="purple" fontSize="2xs" rounded="md">
                  {backup.industry}
                </Badge>
              )}
            </HStack>
          </VStack>
        </HStack>
        <HStack spacing={2}>
          <Button
            size="sm"
            variant="ghost"
            onClick={onExpand}
            color="text.secondary"
            _hover={{ bg: 'bg.hover', color: 'text.primary' }}
          >
            Details
          </Button>
          <Button
            size="sm"
            leftIcon={<FiUploadCloud />}
            colorScheme="blue"
            variant="outline"
            onClick={onRestore}
          >
            Restaurer
          </Button>
          <Button
            size="sm"
            leftIcon={<FiTrash2 />}
            colorScheme="red"
            variant="ghost"
            onClick={onDelete}
          />
        </HStack>
      </HStack>

      {/* Stats résumées */}
      <SimpleGrid columns={4} spacing={3}>
        <HStack spacing={2}>
          <Icon as={FiServer} boxSize={3.5} color="text.muted" />
          <VStack align="start" spacing={0}>
            <Text fontSize="xs" color="text.muted">Neo4j</Text>
            <Text fontSize="sm" fontWeight="medium" color="text.primary">
              {backup.neo4j_nodes.toLocaleString()} nodes
            </Text>
          </VStack>
        </HStack>
        <HStack spacing={2}>
          <Icon as={FiDatabase} boxSize={3.5} color="text.muted" />
          <VStack align="start" spacing={0}>
            <Text fontSize="xs" color="text.muted">Qdrant</Text>
            <Text fontSize="sm" fontWeight="medium" color="text.primary">
              {backup.qdrant_points.toLocaleString()} pts
            </Text>
          </VStack>
        </HStack>
        <HStack spacing={2}>
          <Icon as={FiFileText} boxSize={3.5} color="text.muted" />
          <VStack align="start" spacing={0}>
            <Text fontSize="xs" color="text.muted">Documents</Text>
            <Text fontSize="sm" fontWeight="medium" color="text.primary">
              {backup.documents_count}
            </Text>
          </VStack>
        </HStack>
        <HStack spacing={2}>
          <Icon as={FiHardDrive} boxSize={3.5} color="text.muted" />
          <VStack align="start" spacing={0}>
            <Text fontSize="xs" color="text.muted">Taille</Text>
            <Text fontSize="sm" fontWeight="medium" color="text.primary">
              {backup.size_human}
            </Text>
          </VStack>
        </HStack>
      </SimpleGrid>

      {/* Indicateur composants */}
      <HStack mt={3} spacing={1}>
        {Array.from({ length: backup.components_total }).map((_, i) => (
          <Box
            key={i}
            h={1}
            flex={1}
            rounded="full"
            bg={i < backup.components_ok ? 'green.400' : 'red.400'}
          />
        ))}
        <Text fontSize="2xs" color="text.muted" ml={2}>
          {backup.components_ok}/{backup.components_total}
        </Text>
      </HStack>
    </Box>
  </MotionBox>
)

export default function BackupPage() {
  const toast = useToast()
  const queryClient = useQueryClient()
  const restoreModal = useDisclosure()
  const deleteModal = useDisclosure()
  const detailModal = useDisclosure()

  const [backupName, setBackupName] = useState(
    `backup_${new Date().toISOString().slice(0, 10).replace(/-/g, '')}`
  )
  const [includeCache, setIncludeCache] = useState(true)
  const [selectedBackup, setSelectedBackup] = useState<string>('')
  const [activeJobId, setActiveJobId] = useState<string | null>(null)

  // Query: liste des backups
  const { data: backupList, isLoading: isLoadingList } = useQuery({
    queryKey: ['backup', 'list'],
    queryFn: async () => {
      const res = await api.backup.list()
      return res.data as { backups: BackupSummary[]; total: number }
    },
    refetchInterval: 10000,
  })

  // Query: stats actuelles
  const { data: currentStats, isLoading: isLoadingStats } = useQuery({
    queryKey: ['backup', 'stats'],
    queryFn: async () => {
      const res = await api.backup.currentStats()
      return res.data as CurrentStats
    },
  })

  // Query: détail d'un backup sélectionné
  const { data: backupDetail } = useQuery({
    queryKey: ['backup', 'detail', selectedBackup],
    queryFn: async () => {
      if (!selectedBackup) return null
      const res = await api.backup.getDetail(selectedBackup)
      return res.data as BackupManifest
    },
    enabled: !!selectedBackup && detailModal.isOpen,
  })

  // Query: polling job status
  const { data: jobStatus } = useQuery({
    queryKey: ['backup', 'job', activeJobId],
    queryFn: async () => {
      if (!activeJobId) return null
      const res = await api.backup.jobStatus(activeJobId)
      return res.data as JobStatus
    },
    enabled: !!activeJobId,
    refetchInterval: activeJobId ? 2000 : false,
  })

  // Arrêter le polling quand le job est terminé
  useEffect(() => {
    if (jobStatus && (jobStatus.status === 'completed' || jobStatus.status === 'failed')) {
      queryClient.invalidateQueries({ queryKey: ['backup', 'list'] })
      if (jobStatus.status === 'completed') {
        toast({
          title: `${jobStatus.operation === 'backup' ? 'Backup' : 'Restauration'} termine`,
          status: 'success',
          duration: 5000,
        })
      } else {
        toast({
          title: 'Erreur',
          description: jobStatus.error || 'Operation echouee',
          status: 'error',
          duration: 5000,
        })
      }
      setActiveJobId(null)
    }
  }, [jobStatus, queryClient, toast])

  // Mutation: créer backup
  const createMutation = useMutation({
    mutationFn: async () => {
      const res = await api.backup.create(backupName, includeCache)
      if (!res.success) throw new Error(res.error || 'Erreur creation backup')
      return res.data as JobStatus
    },
    onSuccess: (data) => {
      setActiveJobId(data.job_id)
      toast({ title: 'Backup lance', description: `Job: ${data.job_id}`, status: 'info', duration: 3000 })
    },
    onError: (error: Error) => {
      toast({ title: 'Erreur', description: error.message, status: 'error', duration: 5000 })
    },
  })

  // Mutation: restaurer
  const restoreMutation = useMutation({
    mutationFn: async ({ name, autoBackup }: { name: string; autoBackup: boolean }) => {
      const res = await api.backup.restore(name, autoBackup)
      if (!res.success) throw new Error(res.error || 'Erreur restauration')
      return res.data as JobStatus
    },
    onSuccess: (data) => {
      restoreModal.onClose()
      setActiveJobId(data.job_id)
      toast({ title: 'Restauration lancee', description: `Job: ${data.job_id}`, status: 'info', duration: 3000 })
    },
    onError: (error: Error) => {
      toast({ title: 'Erreur', description: error.message, status: 'error', duration: 5000 })
    },
  })

  // Mutation: supprimer
  const deleteMutation = useMutation({
    mutationFn: async (name: string) => {
      const res = await api.backup.delete(name)
      if (!res.success) throw new Error(res.error || 'Erreur suppression')
      return res.data
    },
    onSuccess: () => {
      deleteModal.onClose()
      queryClient.invalidateQueries({ queryKey: ['backup', 'list'] })
      toast({ title: 'Backup supprime', status: 'success', duration: 3000 })
    },
    onError: (error: Error) => {
      toast({ title: 'Erreur', description: error.message, status: 'error', duration: 5000 })
    },
  })

  const [restoreAutoBackup, setRestoreAutoBackup] = useState(true)

  return (
    <Box maxW="1200px" mx="auto">
      {/* Header */}
      <MotionBox
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
        mb={8}
      >
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
            <Icon as={FiArchive} boxSize={5} color="white" />
          </Box>
          <VStack align="start" spacing={0}>
            <Text fontSize="2xl" fontWeight="bold" color="text.primary">
              Backup & Restore
            </Text>
            <Text color="text.secondary">
              Sauvegarde et restauration du systeme OSMOSE
            </Text>
          </VStack>
        </HStack>
      </MotionBox>

      <VStack spacing={6} align="stretch">
        {/* Job en cours */}
        {activeJobId && jobStatus && jobStatus.status === 'running' && (
          <MotionBox
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
          >
            <Box
              bg="rgba(99, 102, 241, 0.1)"
              border="1px solid"
              borderColor="brand.500"
              rounded="xl"
              p={5}
            >
              <HStack spacing={3} mb={3}>
                <Spinner size="sm" color="brand.400" />
                <Text fontWeight="semibold" color="brand.400">
                  {jobStatus.operation === 'backup' ? 'Backup' : 'Restauration'} en cours : {jobStatus.name}
                </Text>
              </HStack>
              {jobStatus.log_lines.length > 0 && (
                <Box
                  bg="bg.primary"
                  rounded="lg"
                  p={3}
                  maxH="150px"
                  overflowY="auto"
                  fontFamily="mono"
                  fontSize="xs"
                >
                  {jobStatus.log_lines.slice(-10).map((line, i) => (
                    <Text key={i} color="text.muted">{line}</Text>
                  ))}
                </Box>
              )}
            </Box>
          </MotionBox>
        )}

        {/* Section: Créer un backup */}
        <SectionCard
          title="Creer un Backup"
          subtitle="Sauvegarde complète de tous les composants"
          icon={FiDownloadCloud}
          variant="accent"
          delay={0.1}
        >
          <VStack spacing={4} align="stretch">
            {/* Stats actuelles */}
            {currentStats && (
              <Box bg="bg.tertiary" rounded="lg" p={4}>
                <Text fontSize="xs" color="text.muted" textTransform="uppercase" letterSpacing="wide" mb={2}>
                  Systeme actuel
                </Text>
                <SimpleGrid columns={{ base: 2, md: 4 }} spacing={4}>
                  <VStack align="start" spacing={0}>
                    <Text fontSize="lg" fontWeight="bold" color="text.primary">
                      {currentStats.neo4j_nodes.toLocaleString()}
                    </Text>
                    <Text fontSize="xs" color="text.muted">nodes Neo4j</Text>
                  </VStack>
                  <VStack align="start" spacing={0}>
                    <Text fontSize="lg" fontWeight="bold" color="text.primary">
                      {currentStats.qdrant_total_points.toLocaleString()}
                    </Text>
                    <Text fontSize="xs" color="text.muted">points Qdrant</Text>
                  </VStack>
                  <VStack align="start" spacing={0}>
                    <Text fontSize="lg" fontWeight="bold" color="text.primary">
                      {currentStats.imported_documents?.length || 0}
                    </Text>
                    <Text fontSize="xs" color="text.muted">documents</Text>
                  </VStack>
                  <VStack align="start" spacing={0}>
                    <Text fontSize="lg" fontWeight="bold" color="text.primary">
                      {currentStats.extraction_cache_files}
                    </Text>
                    <Text fontSize="xs" color="text.muted">fichiers cache</Text>
                  </VStack>
                </SimpleGrid>
                {currentStats.domain_context?.industry && (
                  <HStack mt={2}>
                    <Badge colorScheme="purple" fontSize="xs">{currentStats.domain_context.industry}</Badge>
                    <Text fontSize="xs" color="text.muted">{currentStats.domain_context.domain_summary}</Text>
                  </HStack>
                )}
              </Box>
            )}

            {/* Formulaire */}
            <HStack spacing={4}>
              <Box flex={1}>
                <Text fontSize="sm" color="text.secondary" mb={1}>Nom du backup</Text>
                <Input
                  value={backupName}
                  onChange={(e) => setBackupName(e.target.value)}
                  placeholder="backup_20260218"
                  bg="bg.tertiary"
                  border="1px solid"
                  borderColor="border.default"
                  _hover={{ borderColor: 'brand.500' }}
                  _focus={{ borderColor: 'brand.500', boxShadow: '0 0 0 1px var(--chakra-colors-brand-500)' }}
                  color="text.primary"
                />
              </Box>
              <VStack align="start" pt={6}>
                <Checkbox
                  isChecked={includeCache}
                  onChange={(e) => setIncludeCache(e.target.checked)}
                  colorScheme="brand"
                  size="md"
                >
                  <Text fontSize="sm" color="text.secondary">Inclure cache d'extraction</Text>
                </Checkbox>
              </VStack>
            </HStack>

            <Button
              leftIcon={<FiDownloadCloud />}
              colorScheme="green"
              size="lg"
              onClick={() => createMutation.mutate()}
              isLoading={createMutation.isPending || !!activeJobId}
              loadingText="Backup en cours..."
              isDisabled={!backupName.trim()}
              _hover={{
                transform: 'translateY(-2px)',
                boxShadow: '0 0 20px rgba(34, 197, 94, 0.3)',
              }}
              transition="all 0.2s"
            >
              Creer Backup
            </Button>
          </VStack>
        </SectionCard>

        {/* Section: Backups disponibles */}
        <SectionCard
          title="Backups Disponibles"
          subtitle={`${backupList?.total || 0} backup(s)`}
          icon={FiPackage}
          delay={0.2}
        >
          {isLoadingList ? (
            <Center py={8}>
              <VStack spacing={3}>
                <Spinner size="lg" color="brand.500" thickness="3px" />
                <Text color="text.muted" fontSize="sm">Chargement...</Text>
              </VStack>
            </Center>
          ) : backupList && backupList.backups.length > 0 ? (
            <VStack spacing={3} align="stretch">
              {backupList.backups.map((backup, i) => (
                <BackupCard
                  key={backup.name}
                  backup={backup}
                  delay={i * 0.05}
                  onRestore={() => {
                    setSelectedBackup(backup.name)
                    restoreModal.onOpen()
                  }}
                  onDelete={() => {
                    setSelectedBackup(backup.name)
                    deleteModal.onOpen()
                  }}
                  onExpand={() => {
                    setSelectedBackup(backup.name)
                    detailModal.onOpen()
                  }}
                />
              ))}
            </VStack>
          ) : (
            <Box bg="bg.tertiary" rounded="lg" p={8} textAlign="center">
              <Icon as={FiArchive} boxSize={10} color="text.muted" mb={3} />
              <Text color="text.muted">Aucun backup disponible</Text>
              <Text fontSize="sm" color="text.muted" mt={1}>
                Creez votre premier backup ci-dessus
              </Text>
            </Box>
          )}
        </SectionCard>
      </VStack>

      {/* Modal: Restauration */}
      <Modal isOpen={restoreModal.isOpen} onClose={restoreModal.onClose} isCentered size="lg">
        <ModalOverlay bg="rgba(0, 0, 0, 0.7)" backdropFilter="blur(4px)" />
        <ModalContent bg="bg.secondary" border="1px solid" borderColor="brand.500" rounded="xl" mx={4}>
          <ModalHeader color="text.primary" borderBottom="1px solid" borderColor="border.default">
            <HStack spacing={3}>
              <Icon as={FiUploadCloud} boxSize={5} color="brand.400" />
              <Text>Restaurer : {selectedBackup}</Text>
            </HStack>
          </ModalHeader>
          <ModalCloseButton color="text.muted" />
          <ModalBody py={6}>
            <VStack align="start" spacing={4}>
              <Box
                bg="rgba(251, 191, 36, 0.1)"
                border="1px solid"
                borderColor="orange.500"
                rounded="lg"
                p={4}
                w="full"
              >
                <HStack spacing={3}>
                  <Icon as={FiAlertTriangle} boxSize={5} color="orange.400" />
                  <Text color="orange.400" fontWeight="medium" fontSize="sm">
                    Cette operation va REMPLACER toutes les donnees actuelles par celles du backup.
                  </Text>
                </HStack>
              </Box>

              {currentStats && (
                <Box bg="bg.tertiary" rounded="lg" p={4} w="full">
                  <Text fontSize="sm" fontWeight="medium" color="text.primary" mb={2}>
                    Donnees actuelles qui seront ecrasees :
                  </Text>
                  <SimpleGrid columns={2} spacing={2}>
                    <Text fontSize="xs" color="text.muted">Neo4j: {currentStats.neo4j_nodes.toLocaleString()} nodes</Text>
                    <Text fontSize="xs" color="text.muted">Qdrant: {currentStats.qdrant_total_points.toLocaleString()} points</Text>
                    <Text fontSize="xs" color="text.muted">Sessions: {currentStats.postgres_sessions}</Text>
                    <Text fontSize="xs" color="text.muted">Redis: {currentStats.redis_keys} cles</Text>
                  </SimpleGrid>
                </Box>
              )}

              <Checkbox
                isChecked={restoreAutoBackup}
                onChange={(e) => setRestoreAutoBackup(e.target.checked)}
                colorScheme="green"
                size="md"
              >
                <VStack align="start" spacing={0} ml={1}>
                  <Text color="text.primary" fontWeight="medium" fontSize="sm">
                    Sauvegarder d'abord l'etat actuel
                  </Text>
                  <Text color="text.muted" fontSize="xs">
                    Cree un backup automatique avant la restauration (recommande)
                  </Text>
                </VStack>
              </Checkbox>
            </VStack>
          </ModalBody>
          <ModalFooter borderTop="1px solid" borderColor="border.default">
            <Button variant="ghost" mr={3} onClick={restoreModal.onClose} color="text.secondary">
              Annuler
            </Button>
            <Button
              colorScheme="blue"
              leftIcon={<FiUploadCloud />}
              onClick={() => restoreMutation.mutate({ name: selectedBackup, autoBackup: restoreAutoBackup })}
              isLoading={restoreMutation.isPending}
            >
              Restaurer
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>

      {/* Modal: Suppression */}
      <Modal isOpen={deleteModal.isOpen} onClose={deleteModal.onClose} isCentered>
        <ModalOverlay bg="rgba(0, 0, 0, 0.7)" backdropFilter="blur(4px)" />
        <ModalContent bg="bg.secondary" border="1px solid" borderColor="red.500" rounded="xl" mx={4}>
          <ModalHeader color="text.primary" borderBottom="1px solid" borderColor="border.default">
            <HStack spacing={3}>
              <Icon as={FiTrash2} boxSize={5} color="red.400" />
              <Text>Supprimer : {selectedBackup}</Text>
            </HStack>
          </ModalHeader>
          <ModalCloseButton color="text.muted" />
          <ModalBody py={6}>
            <Text color="text.primary">
              Etes-vous sur de vouloir supprimer le backup <Text as="span" fontWeight="bold" color="red.400">{selectedBackup}</Text> ?
            </Text>
            <Text fontSize="sm" color="text.muted" mt={2}>
              Cette action est irreversible.
            </Text>
          </ModalBody>
          <ModalFooter borderTop="1px solid" borderColor="border.default">
            <Button variant="ghost" mr={3} onClick={deleteModal.onClose} color="text.secondary">
              Annuler
            </Button>
            <Button
              bg="red.500"
              color="white"
              leftIcon={<FiTrash2 />}
              onClick={() => deleteMutation.mutate(selectedBackup)}
              isLoading={deleteMutation.isPending}
              _hover={{ bg: 'red.600' }}
            >
              Supprimer
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>

      {/* Modal: Détails */}
      <Modal isOpen={detailModal.isOpen} onClose={detailModal.onClose} size="xl">
        <ModalOverlay bg="rgba(0, 0, 0, 0.7)" backdropFilter="blur(4px)" />
        <ModalContent bg="bg.secondary" border="1px solid" borderColor="border.default" rounded="xl" mx={4} maxH="80vh" overflowY="auto">
          <ModalHeader color="text.primary" borderBottom="1px solid" borderColor="border.default">
            <HStack spacing={3}>
              <Icon as={FiPackage} boxSize={5} color="brand.400" />
              <Text>Details : {selectedBackup}</Text>
            </HStack>
          </ModalHeader>
          <ModalCloseButton color="text.muted" />
          <ModalBody py={6}>
            {backupDetail ? (
              <VStack spacing={4} align="stretch">
                {/* Meta */}
                <SimpleGrid columns={2} spacing={3}>
                  <Box bg="bg.tertiary" rounded="lg" p={3}>
                    <Text fontSize="xs" color="text.muted">Date</Text>
                    <Text fontSize="sm" color="text.primary">{formatDate(backupDetail.created_at)}</Text>
                  </Box>
                  <Box bg="bg.tertiary" rounded="lg" p={3}>
                    <Text fontSize="xs" color="text.muted">Duree</Text>
                    <Text fontSize="sm" color="text.primary">{backupDetail.duration_seconds.toFixed(1)}s</Text>
                  </Box>
                </SimpleGrid>

                {backupDetail.domain_context?.industry && (
                  <Box bg="bg.tertiary" rounded="lg" p={3}>
                    <Badge colorScheme="purple" mb={1}>{backupDetail.domain_context.industry}</Badge>
                    <Text fontSize="sm" color="text.muted">{backupDetail.domain_context.domain_summary}</Text>
                  </Box>
                )}

                {/* Composants */}
                <Accordion allowMultiple>
                  {/* Neo4j */}
                  <AccordionItem border="1px solid" borderColor="border.default" rounded="lg" mb={2}>
                    <AccordionButton>
                      <HStack flex="1" spacing={2}>
                        <Icon as={FiServer} boxSize={4} color="text.muted" />
                        <Text fontWeight="medium" color="text.primary">Neo4j</Text>
                      </HStack>
                      <ComponentStatusBadge status={backupDetail.components.neo4j?.status || 'pending'} />
                      <AccordionIcon ml={2} color="text.muted" />
                    </AccordionButton>
                    <AccordionPanel>
                      {backupDetail.components.neo4j?.node_counts && (
                        <Table size="sm" variant="unstyled">
                          <Thead>
                            <Tr>
                              <Th color="text.muted" fontSize="xs">Label</Th>
                              <Th color="text.muted" fontSize="xs" isNumeric>Count</Th>
                            </Tr>
                          </Thead>
                          <Tbody>
                            {Object.entries(backupDetail.components.neo4j.node_counts as Record<string, number>).map(([label, count]) => (
                              <Tr key={label}>
                                <Td color="text.secondary" fontSize="sm">{label}</Td>
                                <Td color="text.primary" fontSize="sm" isNumeric>{count.toLocaleString()}</Td>
                              </Tr>
                            ))}
                          </Tbody>
                        </Table>
                      )}
                      <Text fontSize="xs" color="text.muted" mt={2}>
                        Total: {backupDetail.components.neo4j?.total_nodes?.toLocaleString() || '?'} nodes,{' '}
                        {backupDetail.components.neo4j?.total_relationships?.toLocaleString() || '?'} relations
                      </Text>
                    </AccordionPanel>
                  </AccordionItem>

                  {/* Qdrant */}
                  <AccordionItem border="1px solid" borderColor="border.default" rounded="lg" mb={2}>
                    <AccordionButton>
                      <HStack flex="1" spacing={2}>
                        <Icon as={FiDatabase} boxSize={4} color="text.muted" />
                        <Text fontWeight="medium" color="text.primary">Qdrant</Text>
                      </HStack>
                      <ComponentStatusBadge status={backupDetail.components.qdrant?.status || 'pending'} />
                      <AccordionIcon ml={2} color="text.muted" />
                    </AccordionButton>
                    <AccordionPanel>
                      {backupDetail.components.qdrant?.collections && (
                        <Table size="sm" variant="unstyled">
                          <Thead>
                            <Tr>
                              <Th color="text.muted" fontSize="xs">Collection</Th>
                              <Th color="text.muted" fontSize="xs" isNumeric>Points</Th>
                            </Tr>
                          </Thead>
                          <Tbody>
                            {Object.entries(backupDetail.components.qdrant.collections as Record<string, any>).map(([name, info]: [string, any]) => (
                              <Tr key={name}>
                                <Td color="text.secondary" fontSize="sm" fontFamily="mono">{name}</Td>
                                <Td color="text.primary" fontSize="sm" isNumeric>{info.point_count?.toLocaleString() || 0}</Td>
                              </Tr>
                            ))}
                          </Tbody>
                        </Table>
                      )}
                    </AccordionPanel>
                  </AccordionItem>

                  {/* PostgreSQL */}
                  <AccordionItem border="1px solid" borderColor="border.default" rounded="lg" mb={2}>
                    <AccordionButton>
                      <HStack flex="1" spacing={2}>
                        <Icon as={FiDatabase} boxSize={4} color="text.muted" />
                        <Text fontWeight="medium" color="text.primary">PostgreSQL</Text>
                      </HStack>
                      <ComponentStatusBadge status={backupDetail.components.postgresql?.status || 'pending'} />
                      <AccordionIcon ml={2} color="text.muted" />
                    </AccordionButton>
                    <AccordionPanel>
                      {backupDetail.components.postgresql?.table_counts && (
                        <Table size="sm" variant="unstyled">
                          <Thead>
                            <Tr>
                              <Th color="text.muted" fontSize="xs">Table</Th>
                              <Th color="text.muted" fontSize="xs" isNumeric>Rows</Th>
                            </Tr>
                          </Thead>
                          <Tbody>
                            {Object.entries(backupDetail.components.postgresql.table_counts as Record<string, number>).map(([table, count]) => (
                              <Tr key={table}>
                                <Td color="text.secondary" fontSize="sm">{table}</Td>
                                <Td color="text.primary" fontSize="sm" isNumeric>{count}</Td>
                              </Tr>
                            ))}
                          </Tbody>
                        </Table>
                      )}
                    </AccordionPanel>
                  </AccordionItem>

                  {/* Redis */}
                  <AccordionItem border="1px solid" borderColor="border.default" rounded="lg" mb={2}>
                    <AccordionButton>
                      <HStack flex="1" spacing={2}>
                        <Icon as={FiHardDrive} boxSize={4} color="text.muted" />
                        <Text fontWeight="medium" color="text.primary">Redis</Text>
                      </HStack>
                      <ComponentStatusBadge status={backupDetail.components.redis?.status || 'pending'} />
                      <AccordionIcon ml={2} color="text.muted" />
                    </AccordionButton>
                    <AccordionPanel>
                      <Text fontSize="sm" color="text.muted">
                        Taille RDB: {backupDetail.components.redis?.size_bytes
                          ? `${(backupDetail.components.redis.size_bytes / 1024).toFixed(1)} KB`
                          : 'N/A'}
                      </Text>
                    </AccordionPanel>
                  </AccordionItem>

                  {/* Extraction Cache */}
                  <AccordionItem border="1px solid" borderColor="border.default" rounded="lg" mb={2}>
                    <AccordionButton>
                      <HStack flex="1" spacing={2}>
                        <Icon as={FiFileText} boxSize={4} color="text.muted" />
                        <Text fontWeight="medium" color="text.primary">Extraction Cache</Text>
                      </HStack>
                      <ComponentStatusBadge status={backupDetail.components.extraction_cache?.status || 'pending'} />
                      <AccordionIcon ml={2} color="text.muted" />
                    </AccordionButton>
                    <AccordionPanel>
                      <Text fontSize="sm" color="text.muted">
                        {backupDetail.components.extraction_cache?.file_count || 0} fichiers
                      </Text>
                    </AccordionPanel>
                  </AccordionItem>
                </Accordion>

                {/* Documents importés */}
                {backupDetail.imported_documents && backupDetail.imported_documents.length > 0 && (
                  <Box>
                    <Text fontSize="sm" fontWeight="medium" color="text.primary" mb={2}>
                      Documents importes ({backupDetail.imported_documents.length})
                    </Text>
                    <Box bg="bg.tertiary" rounded="lg" p={3} maxH="200px" overflowY="auto">
                      {backupDetail.imported_documents.map((doc, i) => (
                        <HStack key={i} spacing={2} py={1}>
                          <Icon as={FiChevronRight} boxSize={3} color="text.muted" />
                          <Text fontSize="xs" color="text.secondary" fontFamily="mono">{doc.doc_id}</Text>
                          {doc.primary_subject && (
                            <Text fontSize="xs" color="text.muted">- {doc.primary_subject}</Text>
                          )}
                        </HStack>
                      ))}
                    </Box>
                  </Box>
                )}
              </VStack>
            ) : (
              <Center py={8}>
                <Spinner size="lg" color="brand.500" />
              </Center>
            )}
          </ModalBody>
        </ModalContent>
      </Modal>
    </Box>
  )
}
