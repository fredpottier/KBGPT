'use client'

/**
 * OSMOS Admin Dashboard - Dark Elegance Edition
 *
 * Premium system monitoring and quick actions
 */

import {
  Box,
  Grid,
  GridItem,
  HStack,
  Icon,
  Text,
  VStack,
  Spinner,
  Center,
  Flex,
  SimpleGrid,
} from '@chakra-ui/react'
import { motion } from 'framer-motion'
import { useQuery } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { api } from '@/lib/api'
import { MonitoringStats } from '@/types/api'
import {
  FiHome,
  FiFileText,
  FiMessageSquare,
  FiClock,
  FiAlertTriangle,
  FiCpu,
  FiHardDrive,
  FiDatabase,
  FiSettings,
  FiShare2,
  FiGlobe,
  FiArrowRight,
  FiActivity,
  FiZap,
  FiSliders,
  FiCloud,
} from 'react-icons/fi'

const MotionBox = motion(Box)

// Stat Card Component
const StatCard = ({
  title,
  value,
  subtitle,
  icon,
  color = 'brand',
  delay = 0,
}: {
  title: string
  value: string | number
  subtitle?: string
  icon: any
  color?: string
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
      p={5}
      position="relative"
      overflow="hidden"
      _hover={{
        borderColor: `${color}.500`,
        transform: 'translateY(-2px)',
        boxShadow: `0 0 20px rgba(99, 102, 241, 0.1)`,
      }}
      transition="all 0.2s"
    >
      <HStack spacing={4}>
        <Box
          w={12}
          h={12}
          rounded="xl"
          bg={`rgba(99, 102, 241, 0.15)`}
          display="flex"
          alignItems="center"
          justifyContent="center"
        >
          <Icon as={icon} boxSize={6} color={`${color}.400`} />
        </Box>
        <VStack align="start" spacing={0} flex={1}>
          <Text fontSize="xs" color="text.muted" textTransform="uppercase" letterSpacing="wide">
            {title}
          </Text>
          <Text fontSize="2xl" fontWeight="bold" color="text.primary">
            {value}
          </Text>
          {subtitle && (
            <Text fontSize="xs" color="text.muted">
              {subtitle}
            </Text>
          )}
        </VStack>
      </HStack>
    </Box>
  </MotionBox>
)

// Quick Action Button
const QuickActionButton = ({
  label,
  icon,
  href,
  color = 'brand',
  delay = 0,
}: {
  label: string
  icon: any
  href: string
  color?: string
  delay?: number
}) => {
  const router = useRouter()

  return (
    <MotionBox
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.3, delay }}
      as="button"
      onClick={() => router.push(href)}
      w="full"
    >
      <HStack
        p={4}
        bg="bg.tertiary"
        border="1px solid"
        borderColor="border.default"
        rounded="xl"
        justify="space-between"
        cursor="pointer"
        _hover={{
          bg: 'bg.hover',
          borderColor: `${color}.500`,
          transform: 'translateX(4px)',
        }}
        transition="all 0.2s"
      >
        <HStack spacing={3}>
          <Box
            w={10}
            h={10}
            rounded="lg"
            bg={`rgba(99, 102, 241, 0.1)`}
            display="flex"
            alignItems="center"
            justifyContent="center"
          >
            <Icon as={icon} boxSize={5} color={`${color}.400`} />
          </Box>
          <Text fontWeight="medium" color="text.primary">
            {label}
          </Text>
        </HStack>
        <Icon as={FiArrowRight} color="text.muted" />
      </HStack>
    </MotionBox>
  )
}

// Progress Bar Component
const ProgressBar = ({
  label,
  value,
  max,
  color = 'brand',
}: {
  label: string
  value: number
  max?: number
  color?: string
}) => {
  const percentage = max ? (value / max) * 100 : value
  const displayValue = max ? `${value}/${max}` : `${value.toFixed(1)}%`

  // Determine color based on percentage for resource usage
  const getColor = () => {
    if (!max) {
      if (percentage > 80) return 'red'
      if (percentage > 60) return 'orange'
      return 'green'
    }
    return color
  }

  const barColor = getColor()

  return (
    <Box>
      <HStack justify="space-between" mb={2}>
        <Text fontSize="sm" color="text.secondary">
          {label}
        </Text>
        <Text fontSize="sm" fontWeight="medium" color="text.primary">
          {displayValue}
        </Text>
      </HStack>
      <Box
        h="8px"
        bg="bg.tertiary"
        rounded="full"
        overflow="hidden"
      >
        <Box
          h="full"
          w={`${Math.min(percentage, 100)}%`}
          bg={`${barColor}.400`}
          rounded="full"
          transition="width 0.5s ease"
          boxShadow={`0 0 10px var(--chakra-colors-${barColor}-400)`}
        />
      </Box>
    </Box>
  )
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
      <Box p={5}>
        {children}
      </Box>
    </Box>
  </MotionBox>
)

export default function AdminDashboard() {
  const {
    data: statsResponse,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['admin', 'stats'],
    queryFn: () => api.admin.monitoring.stats(),
    refetchInterval: 30000,
  })

  if (isLoading) {
    return (
      <Center h="400px">
        <VStack spacing={4}>
          <Spinner size="xl" color="brand.500" thickness="3px" />
          <Text color="text.muted">Chargement des statistiques...</Text>
        </VStack>
      </Center>
    )
  }

  if (error || !statsResponse?.success) {
    return (
      <Center h="400px">
        <MotionBox
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.3 }}
        >
          <Box
            bg="rgba(239, 68, 68, 0.1)"
            border="1px solid"
            borderColor="red.500"
            rounded="xl"
            p={8}
            textAlign="center"
          >
            <Icon as={FiAlertTriangle} boxSize={12} color="red.400" mb={4} />
            <Text fontSize="lg" fontWeight="medium" color="red.400" mb={2}>
              Erreur de chargement
            </Text>
            <Text fontSize="sm" color="text.muted">
              Impossible de charger les statistiques du systeme
            </Text>
          </Box>
        </MotionBox>
      </Center>
    )
  }

  const stats: MonitoringStats = statsResponse.data as MonitoringStats

  const formatUptime = (seconds: number) => {
    const days = Math.floor(seconds / (24 * 3600))
    const hours = Math.floor((seconds % (24 * 3600)) / 3600)
    const minutes = Math.floor((seconds % 3600) / 60)

    if (days > 0) return `${days}j ${hours}h`
    if (hours > 0) return `${hours}h ${minutes}m`
    return `${minutes}m`
  }

  return (
    <Box maxW="1400px" mx="auto">
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
            <Icon as={FiHome} boxSize={5} color="white" />
          </Box>
          <VStack align="start" spacing={0}>
            <Text fontSize="2xl" fontWeight="bold" color="text.primary">
              Dashboard Administration
            </Text>
            <Text color="text.secondary">
              Vue d'ensemble du systeme OSMOS
            </Text>
          </VStack>
        </HStack>
      </MotionBox>

      <Grid templateColumns={{ base: '1fr', lg: '1fr 300px' }} gap={6}>
        {/* Main Content */}
        <VStack spacing={6} align="stretch">
          {/* Statistics Cards */}
          <SimpleGrid columns={{ base: 1, md: 2, xl: 4 }} spacing={4}>
            <StatCard
              title="Documents"
              value={stats.documents.total}
              subtitle={`${stats.documents.processed} traites`}
              icon={FiFileText}
              delay={0}
            />
            <StatCard
              title="Messages"
              value={stats.chats.total_messages}
              subtitle={`${stats.chats.active_conversations} conversations`}
              icon={FiMessageSquare}
              color="green"
              delay={0.1}
            />
            <StatCard
              title="Uptime"
              value={formatUptime(stats.system.uptime)}
              subtitle="En ligne"
              icon={FiClock}
              color="purple"
              delay={0.2}
            />
            <StatCard
              title="En attente"
              value={stats.documents.pending}
              subtitle={stats.documents.failed > 0 ? `${stats.documents.failed} echecs` : undefined}
              icon={FiActivity}
              color={stats.documents.pending > 10 ? 'orange' : 'gray'}
              delay={0.3}
            />
          </SimpleGrid>

          {/* Document Processing & System Resources */}
          <Grid templateColumns={{ base: '1fr', md: '1fr 1fr' }} gap={6}>
            <SectionCard title="Traitement Documents" icon={FiDatabase} delay={0.4}>
              <VStack spacing={4} align="stretch">
                <ProgressBar
                  label="Traites"
                  value={stats.documents.processed}
                  max={stats.documents.total}
                  color="green"
                />
                <ProgressBar
                  label="En attente"
                  value={stats.documents.pending}
                  max={stats.documents.total}
                  color="orange"
                />
                {stats.documents.failed > 0 && (
                  <ProgressBar
                    label="Echecs"
                    value={stats.documents.failed}
                    max={stats.documents.total}
                    color="red"
                  />
                )}
              </VStack>
            </SectionCard>

            <SectionCard title="Ressources Systeme" icon={FiCpu} delay={0.5}>
              <VStack spacing={4} align="stretch">
                <ProgressBar
                  label="CPU"
                  value={stats.system.cpu_usage}
                />
                <ProgressBar
                  label="Memoire"
                  value={stats.system.memory_usage}
                />
                <ProgressBar
                  label="Disque"
                  value={stats.system.disk_usage}
                />
              </VStack>
            </SectionCard>
          </Grid>

          {/* Chat Performance */}
          <SectionCard title="Performance Chat" icon={FiZap} delay={0.6}>
            <SimpleGrid columns={{ base: 1, md: 3 }} spacing={6}>
              <VStack
                p={4}
                bg="bg.tertiary"
                rounded="xl"
                spacing={1}
              >
                <Text fontSize="3xl" fontWeight="bold" color="brand.400">
                  {stats.chats.total_messages}
                </Text>
                <Text fontSize="sm" color="text.muted">
                  Messages totaux
                </Text>
              </VStack>

              <VStack
                p={4}
                bg="bg.tertiary"
                rounded="xl"
                spacing={1}
              >
                <Text fontSize="3xl" fontWeight="bold" color="green.400">
                  {stats.chats.active_conversations}
                </Text>
                <Text fontSize="sm" color="text.muted">
                  Conversations actives
                </Text>
              </VStack>

              <VStack
                p={4}
                bg="bg.tertiary"
                rounded="xl"
                spacing={1}
              >
                <Text fontSize="3xl" fontWeight="bold" color="accent.400">
                  {stats.chats.average_response_time.toFixed(1)}s
                </Text>
                <Text fontSize="sm" color="text.muted">
                  Temps de reponse moyen
                </Text>
              </VStack>
            </SimpleGrid>
          </SectionCard>
        </VStack>

        {/* Sidebar - Quick Actions */}
        <VStack spacing={6} align="stretch">
          <MotionBox
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.4, delay: 0.3 }}
          >
            <Text
              fontSize="sm"
              fontWeight="medium"
              color="text.muted"
              textTransform="uppercase"
              letterSpacing="wide"
              mb={3}
            >
              Acces Rapides
            </Text>

            <VStack spacing={3} align="stretch">
              <QuickActionButton
                label="Domain Context"
                icon={FiGlobe}
                href="/admin/domain-context"
                delay={0.4}
              />
              <QuickActionButton
                label="Living Ontology"
                icon={FiShare2}
                href="/admin/living-ontology"
                color="accent"
                delay={0.5}
              />
              <QuickActionButton
                label="Profil Visibilite"
                icon={FiSliders}
                href="/admin/visibility-profile"
                color="purple"
                delay={0.55}
              />
              <QuickActionButton
                label="Mode Burst"
                icon={FiCloud}
                href="/admin/burst"
                color="orange"
                delay={0.6}
              />
              <QuickActionButton
                label="Configuration"
                icon={FiSettings}
                href="/admin/settings"
                delay={0.65}
              />
            </VStack>
          </MotionBox>

          {/* System Status */}
          <MotionBox
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.4, delay: 0.5 }}
          >
            <Text
              fontSize="sm"
              fontWeight="medium"
              color="text.muted"
              textTransform="uppercase"
              letterSpacing="wide"
              mb={3}
            >
              Etat du Systeme
            </Text>

            <Box
              bg="bg.secondary"
              border="1px solid"
              borderColor="border.default"
              rounded="xl"
              p={4}
            >
              <VStack spacing={3} align="stretch">
                <HStack justify="space-between">
                  <HStack spacing={2}>
                    <Box w={2} h={2} rounded="full" bg="green.400" />
                    <Text fontSize="sm" color="text.secondary">API Backend</Text>
                  </HStack>
                  <Text fontSize="xs" color="green.400">Operationnel</Text>
                </HStack>

                <HStack justify="space-between">
                  <HStack spacing={2}>
                    <Box w={2} h={2} rounded="full" bg="green.400" />
                    <Text fontSize="sm" color="text.secondary">Neo4j</Text>
                  </HStack>
                  <Text fontSize="xs" color="green.400">Connecte</Text>
                </HStack>

                <HStack justify="space-between">
                  <HStack spacing={2}>
                    <Box w={2} h={2} rounded="full" bg="green.400" />
                    <Text fontSize="sm" color="text.secondary">Qdrant</Text>
                  </HStack>
                  <Text fontSize="xs" color="green.400">Connecte</Text>
                </HStack>

                <HStack justify="space-between">
                  <HStack spacing={2}>
                    <Box w={2} h={2} rounded="full" bg="green.400" />
                    <Text fontSize="sm" color="text.secondary">Redis</Text>
                  </HStack>
                  <Text fontSize="xs" color="green.400">Actif</Text>
                </HStack>
              </VStack>
            </Box>
          </MotionBox>
        </VStack>
      </Grid>
    </Box>
  )
}
