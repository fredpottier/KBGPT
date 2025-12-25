'use client'

/**
 * OSMOS Admin Settings - Dark Elegance Edition
 *
 * "System Control Center" - Premium system health and maintenance
 */

import {
  Box,
  Button,
  HStack,
  VStack,
  Text,
  Spinner,
  Center,
  Icon,
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
} from '@chakra-ui/react'
import { motion } from 'framer-motion'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import { useState } from 'react'
import {
  FiSettings,
  FiRefreshCw,
  FiDatabase,
  FiServer,
  FiHardDrive,
  FiCheckCircle,
  FiXCircle,
  FiAlertTriangle,
  FiTrash2,
  FiShield,
  FiZap,
} from 'react-icons/fi'

const MotionBox = motion(Box)

// Types
interface HealthComponent {
  status: string
  message: string
}

interface HealthResponse {
  success: boolean
  overall_status: string
  components: {
    qdrant: HealthComponent
    neo4j: HealthComponent
    redis: HealthComponent
    postgres: HealthComponent
  }
}

interface PurgeResult {
  success: boolean
  message: string
  points_deleted?: number
  nodes_deleted?: number
  relations_deleted?: number
  jobs_deleted?: number
  sessions_deleted?: number
  messages_deleted?: number
  files_deleted?: number
}

interface PurgeResponse {
  success: boolean
  message: string
  results: {
    qdrant: PurgeResult
    neo4j: PurgeResult
    redis: PurgeResult
    postgres: PurgeResult
    files: PurgeResult
  }
}

// Status Badge Component
const StatusBadge = ({ status }: { status: string }) => {
  const getConfig = (s: string) => {
    switch (s) {
      case 'healthy':
        return { color: 'green', bg: 'rgba(34, 197, 94, 0.15)', icon: FiCheckCircle, label: 'Operationnel' }
      case 'unhealthy':
        return { color: 'red', bg: 'rgba(239, 68, 68, 0.15)', icon: FiXCircle, label: 'Erreur' }
      default:
        return { color: 'gray', bg: 'rgba(156, 163, 175, 0.15)', icon: FiAlertTriangle, label: 'Inconnu' }
    }
  }

  const config = getConfig(status)

  return (
    <HStack
      px={3}
      py={1.5}
      bg={config.bg}
      rounded="full"
      spacing={2}
    >
      <Icon as={config.icon} boxSize={3.5} color={`${config.color}.400`} />
      <Text fontSize="xs" fontWeight="medium" color={`${config.color}.400`} textTransform="uppercase">
        {config.label}
      </Text>
    </HStack>
  )
}

// Component Health Card - Version compacte pour grille
const ComponentCard = ({
  name,
  description,
  icon,
  status,
  message,
  delay = 0,
}: {
  name: string
  description: string
  icon: any
  status: string
  message: string
  delay?: number
}) => (
  <MotionBox
    initial={{ opacity: 0, scale: 0.95 }}
    animate={{ opacity: 1, scale: 1 }}
    transition={{ duration: 0.3, delay }}
  >
    <Box
      bg="bg.secondary"
      border="1px solid"
      borderColor={status === 'healthy' ? 'rgba(34, 197, 94, 0.3)' : 'rgba(239, 68, 68, 0.3)'}
      rounded="xl"
      p={4}
      h="full"
      _hover={{
        borderColor: status === 'healthy' ? 'green.500' : 'red.500',
        transform: 'translateY(-2px)',
        boxShadow: status === 'healthy'
          ? '0 4px 20px rgba(34, 197, 94, 0.15)'
          : '0 4px 20px rgba(239, 68, 68, 0.15)',
      }}
      transition="all 0.2s"
    >
      {/* Header avec icône et status */}
      <HStack justify="space-between" align="center" mb={3}>
        <HStack spacing={2}>
          <Box
            w={8}
            h={8}
            rounded="lg"
            bg={status === 'healthy' ? 'rgba(34, 197, 94, 0.15)' : 'rgba(239, 68, 68, 0.15)'}
            display="flex"
            alignItems="center"
            justifyContent="center"
          >
            <Icon
              as={icon}
              boxSize={4}
              color={status === 'healthy' ? 'green.400' : 'red.400'}
            />
          </Box>
          <Text fontWeight="semibold" fontSize="sm" color="text.primary">
            {name}
          </Text>
        </HStack>
        <Box
          w={2.5}
          h={2.5}
          rounded="full"
          bg={status === 'healthy' ? 'green.400' : 'red.400'}
          boxShadow={status === 'healthy'
            ? '0 0 8px rgba(34, 197, 94, 0.6)'
            : '0 0 8px rgba(239, 68, 68, 0.6)'}
        />
      </HStack>

      {/* Message */}
      <Text fontSize="xs" color="text.muted" noOfLines={2}>
        {message}
      </Text>
    </Box>
  </MotionBox>
)

// Purge Result Item
const PurgeResultItem = ({
  label,
  success,
  details,
}: {
  label: string
  success: boolean
  details: string
}) => (
  <HStack spacing={3} py={2}>
    <Icon
      as={success ? FiCheckCircle : FiXCircle}
      boxSize={4}
      color={success ? 'green.400' : 'red.400'}
    />
    <Text fontSize="sm" color="text.secondary">
      <Text as="span" fontWeight="medium" color="text.primary">{label}:</Text>{' '}
      {details}
    </Text>
  </HStack>
)

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
  variant?: 'default' | 'danger'
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
      borderColor={variant === 'danger' ? 'red.500' : 'border.default'}
      rounded="xl"
      overflow="hidden"
      position="relative"
      _before={variant === 'danger' ? {
        content: '""',
        position: 'absolute',
        top: 0,
        left: 0,
        right: 0,
        height: '3px',
        bg: 'red.500',
      } : undefined}
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
          bg={variant === 'danger' ? 'rgba(239, 68, 68, 0.15)' : 'rgba(99, 102, 241, 0.15)'}
          display="flex"
          alignItems="center"
          justifyContent="center"
        >
          <Icon as={icon} boxSize={5} color={variant === 'danger' ? 'red.400' : 'brand.400'} />
        </Box>
        <VStack align="start" spacing={0}>
          <Text fontWeight="semibold" color={variant === 'danger' ? 'red.400' : 'text.primary'}>
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

export default function AdminSettingsPage() {
  const toast = useToast()
  const queryClient = useQueryClient()
  const { isOpen, onOpen, onClose } = useDisclosure()
  const [purgeResults, setPurgeResults] = useState<PurgeResponse | null>(null)

  // Health check query
  const {
    data: healthData,
    isLoading: isLoadingHealth,
    refetch: refetchHealth,
  } = useQuery<HealthResponse>({
    queryKey: ['admin', 'health'],
    queryFn: async () => {
      const token = localStorage.getItem('auth_token')
      const response = await axios.get('/api/admin/health', {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      })
      return response.data
    },
    refetchInterval: 10000,
  })

  // Purge mutation
  const purgeMutation = useMutation({
    mutationFn: async () => {
      const token = localStorage.getItem('auth_token')
      const response = await axios.post<PurgeResponse>(
        '/api/admin/purge-data',
        {},
        {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        }
      )
      return response.data
    },
    onSuccess: (data) => {
      setPurgeResults(data)

      if (data.success) {
        toast({
          title: 'Purge reussie',
          description: 'Toutes les donnees d\'ingestion ont ete supprimees',
          status: 'success',
          duration: 5000,
          isClosable: true,
        })
      } else {
        toast({
          title: 'Purge partielle',
          description: 'Certains composants n\'ont pas pu etre purges',
          status: 'warning',
          duration: 7000,
          isClosable: true,
        })
      }

      refetchHealth()
      queryClient.invalidateQueries({ queryKey: ['documents'] })
      queryClient.invalidateQueries({ queryKey: ['imports'] })
      queryClient.invalidateQueries({ queryKey: ['admin', 'stats'] })
    },
    onError: (error: any) => {
      toast({
        title: 'Erreur de purge',
        description: error.response?.data?.error || 'Echec de la purge',
        status: 'error',
        duration: 5000,
        isClosable: true,
      })
    },
  })

  const handlePurgeConfirm = () => {
    onClose()
    purgeMutation.mutate()
  }

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
            <Icon as={FiSettings} boxSize={5} color="white" />
          </Box>
          <VStack align="start" spacing={0}>
            <Text fontSize="2xl" fontWeight="bold" color="text.primary">
              Configuration Systeme
            </Text>
            <Text color="text.secondary">
              Sante des services et maintenance
            </Text>
          </VStack>
        </HStack>
      </MotionBox>

      <VStack spacing={6} align="stretch">
        {/* Health Check Section */}
        <SectionCard
          title="Etat des Composants"
          subtitle="Surveillance en temps reel"
          icon={FiZap}
          delay={0.1}
        >
          <VStack spacing={4} align="stretch">
            {/* Overall Status */}
            <HStack justify="space-between" mb={2}>
              <HStack spacing={2}>
                <Icon as={FiShield} boxSize={5} color="text.muted" />
                <Text fontWeight="medium" color="text.primary">
                  Statut Global
                </Text>
              </HStack>
              <HStack spacing={3}>
                {healthData && (
                  <StatusBadge status={healthData.overall_status} />
                )}
                <Button
                  size="sm"
                  variant="ghost"
                  leftIcon={<FiRefreshCw />}
                  onClick={() => refetchHealth()}
                  isLoading={isLoadingHealth}
                  color="text.secondary"
                  _hover={{ bg: 'bg.hover', color: 'text.primary' }}
                >
                  Rafraichir
                </Button>
              </HStack>
            </HStack>

            {/* Component Cards */}
            {isLoadingHealth ? (
              <Center py={8}>
                <VStack spacing={3}>
                  <Spinner size="lg" color="brand.500" thickness="3px" />
                  <Text color="text.muted" fontSize="sm">Verification des services...</Text>
                </VStack>
              </Center>
            ) : healthData ? (
              <SimpleGrid columns={{ base: 1, sm: 2, lg: 4 }} spacing={4}>
                <ComponentCard
                  name="Qdrant"
                  description="Base vectorielle"
                  icon={FiDatabase}
                  status={healthData.components.qdrant.status}
                  message={healthData.components.qdrant.message}
                  delay={0.1}
                />
                <ComponentCard
                  name="Neo4j"
                  description="Knowledge Graph"
                  icon={FiServer}
                  status={healthData.components.neo4j.status}
                  message={healthData.components.neo4j.message}
                  delay={0.15}
                />
                <ComponentCard
                  name="Redis"
                  description="Queue de jobs"
                  icon={FiHardDrive}
                  status={healthData.components.redis.status}
                  message={healthData.components.redis.message}
                  delay={0.2}
                />
                {healthData.components.postgres && (
                  <ComponentCard
                    name="PostgreSQL"
                    description="Base relationnelle"
                    icon={FiDatabase}
                    status={healthData.components.postgres.status}
                    message={healthData.components.postgres.message}
                    delay={0.25}
                  />
                )}
              </SimpleGrid>
            ) : (
              <Box
                bg="rgba(239, 68, 68, 0.1)"
                border="1px solid"
                borderColor="red.500"
                rounded="lg"
                p={4}
              >
                <HStack spacing={3}>
                  <Icon as={FiAlertTriangle} boxSize={5} color="red.400" />
                  <Text color="red.400">
                    Impossible de recuperer l'etat de sante des services
                  </Text>
                </HStack>
              </Box>
            )}
          </VStack>
        </SectionCard>

        {/* Danger Zone Section */}
        <SectionCard
          title="Zone Dangereuse"
          subtitle="Actions irreversibles"
          icon={FiAlertTriangle}
          variant="danger"
          delay={0.5}
        >
          <VStack spacing={5} align="stretch">
            {/* Warning Alert */}
            <Box
              bg="rgba(251, 191, 36, 0.1)"
              border="1px solid"
              borderColor="orange.500"
              rounded="lg"
              p={4}
            >
              <HStack align="start" spacing={3}>
                <Icon as={FiAlertTriangle} boxSize={5} color="orange.400" mt={0.5} />
                <VStack align="start" spacing={1}>
                  <Text fontWeight="semibold" color="orange.400">
                    Purge complete des donnees d'ingestion
                  </Text>
                  <Text fontSize="sm" color="text.secondary">
                    Cette action supprimera TOUTES les donnees importees (Qdrant, Neo4j metier, Redis)
                    mais preservera les configurations (Types de documents, Types d'entites, Ontologies).
                  </Text>
                </VStack>
              </HStack>
            </Box>

            {/* What will be deleted */}
            <Box
              bg="bg.tertiary"
              rounded="lg"
              p={4}
            >
              <Text fontWeight="semibold" color="red.400" mb={3}>
                Sera supprime :
              </Text>
              <VStack align="start" spacing={2} pl={2}>
                <HStack spacing={2}>
                  <Box w={1.5} h={1.5} rounded="full" bg="red.400" />
                  <Text fontSize="sm" color="text.secondary">Tous les points vectoriels (Qdrant)</Text>
                </HStack>
                <HStack spacing={2}>
                  <Box w={1.5} h={1.5} rounded="full" bg="red.400" />
                  <Text fontSize="sm" color="text.secondary">Tous les nodes metier (Neo4j : Entity, Episode, Fact, Relation, Claims)</Text>
                </HStack>
                <HStack spacing={2}>
                  <Box w={1.5} h={1.5} rounded="full" bg="red.400" />
                  <Text fontSize="sm" color="text.secondary">Toutes les queues et jobs (Redis)</Text>
                </HStack>
                <HStack spacing={2}>
                  <Box w={1.5} h={1.5} rounded="full" bg="red.400" />
                  <Text fontSize="sm" color="text.secondary">Historique conversations (PostgreSQL : sessions, messages)</Text>
                </HStack>
                <HStack spacing={2}>
                  <Box w={1.5} h={1.5} rounded="full" bg="red.400" />
                  <Text fontSize="sm" color="text.secondary">Fichiers traites (docs_in, docs_done, status)</Text>
                </HStack>
              </VStack>
            </Box>

            {/* What will be preserved */}
            <Box
              bg="bg.tertiary"
              rounded="lg"
              p={4}
            >
              <Text fontWeight="semibold" color="green.400" mb={3}>
                Sera preserve :
              </Text>
              <VStack align="start" spacing={2} pl={2}>
                <HStack spacing={2}>
                  <Box w={1.5} h={1.5} rounded="full" bg="green.400" />
                  <Text fontSize="sm" color="text.secondary">Types de documents (DocumentType)</Text>
                </HStack>
                <HStack spacing={2}>
                  <Box w={1.5} h={1.5} rounded="full" bg="green.400" />
                  <Text fontSize="sm" color="text.secondary">Types d'entites (EntityTypeRegistry)</Text>
                </HStack>
                <HStack spacing={2}>
                  <Box w={1.5} h={1.5} rounded="full" bg="green.400" />
                  <Text fontSize="sm" color="text.secondary">Ontologies Neo4j (OntologyEntity, OntologyAlias)</Text>
                </HStack>
                <HStack spacing={2}>
                  <Box w={1.5} h={1.5} rounded="full" bg="green.400" />
                  <Text fontSize="sm" color="text.secondary">Cache d'extraction LLM (extraction_cache/*.knowcache.json)</Text>
                </HStack>
                <HStack spacing={2}>
                  <Box w={1.5} h={1.5} rounded="full" bg="green.400" />
                  <Text fontSize="sm" color="text.secondary">Domain Context (configuration metier globale)</Text>
                </HStack>
                <HStack spacing={2}>
                  <Box w={1.5} h={1.5} rounded="full" bg="green.400" />
                  <Text fontSize="sm" color="text.secondary">Comptes utilisateurs et audit logs</Text>
                </HStack>
              </VStack>
            </Box>

            {/* Purge Button */}
            <Button
              leftIcon={<FiTrash2 />}
              bg="red.500"
              color="white"
              size="lg"
              onClick={onOpen}
              isLoading={purgeMutation.isPending}
              loadingText="Purge en cours..."
              _hover={{
                bg: 'red.600',
                transform: 'translateY(-2px)',
                boxShadow: '0 0 20px rgba(239, 68, 68, 0.4)',
              }}
              _active={{
                transform: 'translateY(0)',
              }}
              transition="all 0.2s"
            >
              Purger toutes les donnees
            </Button>

            {/* Purge Results */}
            {purgeResults && (
              <MotionBox
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3 }}
              >
                <Box
                  bg={purgeResults.success ? 'rgba(34, 197, 94, 0.1)' : 'rgba(251, 191, 36, 0.1)'}
                  border="1px solid"
                  borderColor={purgeResults.success ? 'green.500' : 'orange.500'}
                  rounded="lg"
                  p={4}
                >
                  <HStack spacing={3} mb={3}>
                    <Icon
                      as={purgeResults.success ? FiCheckCircle : FiAlertTriangle}
                      boxSize={5}
                      color={purgeResults.success ? 'green.400' : 'orange.400'}
                    />
                    <Text fontWeight="semibold" color={purgeResults.success ? 'green.400' : 'orange.400'}>
                      {purgeResults.message}
                    </Text>
                  </HStack>
                  <VStack align="stretch" spacing={0} pl={8}>
                    <PurgeResultItem
                      label="Qdrant"
                      success={purgeResults.results.qdrant.success}
                      details={`${purgeResults.results.qdrant.points_deleted || 0} points supprimes`}
                    />
                    <PurgeResultItem
                      label="Neo4j"
                      success={purgeResults.results.neo4j.success}
                      details={`${purgeResults.results.neo4j.nodes_deleted || 0} nodes, ${purgeResults.results.neo4j.relations_deleted || 0} relations supprimes`}
                    />
                    <PurgeResultItem
                      label="Redis"
                      success={purgeResults.results.redis.success}
                      details={`${purgeResults.results.redis.jobs_deleted || 0} jobs supprimes`}
                    />
                    <PurgeResultItem
                      label="PostgreSQL"
                      success={purgeResults.results.postgres?.success || false}
                      details={`${purgeResults.results.postgres?.sessions_deleted || 0} sessions, ${purgeResults.results.postgres?.messages_deleted || 0} messages supprimes`}
                    />
                    <PurgeResultItem
                      label="Fichiers"
                      success={purgeResults.results.files?.success || false}
                      details={`${purgeResults.results.files?.files_deleted || 0} fichiers supprimes`}
                    />
                  </VStack>
                </Box>
              </MotionBox>
            )}
          </VStack>
        </SectionCard>
      </VStack>

      {/* Confirmation Modal */}
      <Modal isOpen={isOpen} onClose={onClose} isCentered>
        <ModalOverlay bg="rgba(0, 0, 0, 0.7)" backdropFilter="blur(4px)" />
        <ModalContent
          bg="bg.secondary"
          border="1px solid"
          borderColor="red.500"
          rounded="xl"
          mx={4}
        >
          <ModalHeader color="text.primary" borderBottom="1px solid" borderColor="border.default">
            <HStack spacing={3}>
              <Icon as={FiAlertTriangle} boxSize={5} color="red.400" />
              <Text>Confirmation de purge</Text>
            </HStack>
          </ModalHeader>
          <ModalCloseButton color="text.muted" />
          <ModalBody py={6}>
            <VStack align="start" spacing={4}>
              <Text color="text.primary">
                Etes-vous sur de vouloir purger <Text as="span" fontWeight="bold" color="red.400">TOUTES</Text> les donnees d'ingestion ?
              </Text>
              <Box
                bg="rgba(239, 68, 68, 0.1)"
                border="1px solid"
                borderColor="red.500"
                rounded="lg"
                p={4}
                w="full"
              >
                <HStack spacing={3}>
                  <Icon as={FiAlertTriangle} boxSize={5} color="red.400" />
                  <Text color="red.400" fontWeight="medium">
                    Cette action est irreversible !
                  </Text>
                </HStack>
              </Box>
              <Text fontSize="sm" color="text.muted">
                Vous devrez reimporter tous vos documents apres cette operation.
              </Text>
            </VStack>
          </ModalBody>

          <ModalFooter borderTop="1px solid" borderColor="border.default">
            <Button
              variant="ghost"
              mr={3}
              onClick={onClose}
              color="text.secondary"
              _hover={{ bg: 'bg.hover', color: 'text.primary' }}
            >
              Annuler
            </Button>
            <Button
              bg="red.500"
              color="white"
              onClick={handlePurgeConfirm}
              leftIcon={<FiTrash2 />}
              _hover={{
                bg: 'red.600',
                boxShadow: '0 0 15px rgba(239, 68, 68, 0.4)',
              }}
            >
              Confirmer la purge
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
    </Box>
  )
}
