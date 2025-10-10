'use client'

import {
  Box,
  Card,
  CardBody,
  CardHeader,
  Grid,
  GridItem,
  HStack,
  Icon,
  Stat,
  StatLabel,
  StatNumber,
  StatHelpText,
  Text,
  VStack,
  Progress,
  Spinner,
  Center,
  Divider,
  Button,
  SimpleGrid,
} from '@chakra-ui/react'
import {
  ViewIcon,
  ChatIcon,
  TimeIcon,
  WarningIcon,
  SettingsIcon,
} from '@chakra-ui/icons'
import { useQuery } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { api } from '@/lib/api'
import { MonitoringStats } from '@/types/api'

const StatCard = ({
  title,
  value,
  subtitle,
  icon,
  color = 'blue',
}: {
  title: string
  value: string | number
  subtitle?: string
  icon: any
  color?: string
}) => (
  <Card>
    <CardBody>
      <HStack spacing={4}>
        <Box
          p={3}
          borderRadius="md"
          bg={`${color}.100`}
          color={`${color}.600`}
        >
          <Icon as={icon} boxSize={6} />
        </Box>
        <Stat>
          <StatLabel>{title}</StatLabel>
          <StatNumber>{value}</StatNumber>
          {subtitle && <StatHelpText>{subtitle}</StatHelpText>}
        </Stat>
      </HStack>
    </CardBody>
  </Card>
)

export default function AdminDashboard() {
  const router = useRouter()

  const {
    data: statsResponse,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['admin', 'stats'],
    queryFn: () => api.admin.monitoring.stats(),
    refetchInterval: 30000, // Refresh every 30 seconds
  })

  if (isLoading) {
    return (
      <Center h="400px">
        <Spinner size="xl" color="brand.500" />
      </Center>
    )
  }

  if (error || !statsResponse?.success) {
    return (
      <Card>
        <CardBody>
          <Center py={12}>
            <VStack spacing={4}>
              <Icon as={WarningIcon} boxSize={12} color="red.500" />
              <Text fontSize="lg" color="red.500">
                Failed to load dashboard statistics
              </Text>
              <Text fontSize="sm" color="gray.500">
                Please check your connection and try again
              </Text>
            </VStack>
          </Center>
        </CardBody>
      </Card>
    )
  }

  const stats: MonitoringStats = statsResponse.data as MonitoringStats

  const formatUptime = (seconds: number) => {
    const days = Math.floor(seconds / (24 * 3600))
    const hours = Math.floor((seconds % (24 * 3600)) / 3600)
    const minutes = Math.floor((seconds % 3600) / 60)

    if (days > 0) return `${days}d ${hours}h ${minutes}m`
    if (hours > 0) return `${hours}h ${minutes}m`
    return `${minutes}m`
  }

  const formatBytes = (bytes: number) => {
    if (bytes === 0) return '0 B'
    const k = 1024
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
  }

  return (
    <VStack spacing={6} align="stretch">
      <Box>
        <Text fontSize="2xl" fontWeight="bold">
          Dashboard Administration
        </Text>
        <Text color="gray.600" mt={2}>
          Vue d'ensemble du système SAP Knowledge Base
        </Text>
      </Box>

      {/* Quick Access */}
      <Card>
        <CardHeader>
          <Text fontSize="lg" fontWeight="semibold">
            Accès Rapides
          </Text>
        </CardHeader>
        <CardBody>
          <SimpleGrid columns={{ base: 1, md: 2, lg: 4 }} spacing={4}>
            <Button
              leftIcon={<ViewIcon />}
              onClick={() => router.push('/admin/documents')}
              colorScheme="blue"
              variant="outline"
              justifyContent="flex-start"
            >
              Gestion Documents
            </Button>
            <Button
              leftIcon={<SettingsIcon />}
              onClick={() => router.push('/admin/document-types')}
              colorScheme="purple"
              variant="outline"
              justifyContent="flex-start"
            >
              Types de Documents
            </Button>
            <Button
              leftIcon={<SettingsIcon />}
              onClick={() => router.push('/admin/dynamic-types')}
              colorScheme="orange"
              variant="outline"
              justifyContent="flex-start"
            >
              Types d'Entités
            </Button>
            <Button
              leftIcon={<SettingsIcon />}
              onClick={() => router.push('/admin/settings')}
              colorScheme="gray"
              variant="outline"
              justifyContent="flex-start"
            >
              Paramètres
            </Button>
          </SimpleGrid>
        </CardBody>
      </Card>

      {/* Statistics Cards */}
      <Grid templateColumns="repeat(auto-fit, minmax(250px, 1fr))" gap={6}>
        <StatCard
          title="Total Documents"
          value={stats.documents.total}
          subtitle={`${stats.documents.processed} processed`}
          icon={ViewIcon}
          color="blue"
        />
        <StatCard
          title="Chat Messages"
          value={stats.chats.total_messages}
          subtitle={`${stats.chats.active_conversations} active conversations`}
          icon={ChatIcon}
          color="green"
        />
        <StatCard
          title="System Uptime"
          value={formatUptime(stats.system.uptime)}
          subtitle="Hours online"
          icon={TimeIcon}
          color="purple"
        />
        <StatCard
          title="Pending Documents"
          value={stats.documents.pending}
          subtitle={stats.documents.failed > 0 ? `${stats.documents.failed} failed` : ''}
          icon={WarningIcon}
          color={stats.documents.pending > 10 ? 'orange' : 'gray'}
        />
      </Grid>

      <Grid templateColumns="repeat(auto-fit, minmax(400px, 1fr))" gap={6}>
        {/* Document Processing Status */}
        <Card>
          <CardHeader>
            <Text fontSize="lg" fontWeight="semibold">
              Document Processing
            </Text>
          </CardHeader>
          <CardBody>
            <VStack spacing={4} align="stretch">
              <Box>
                <HStack justify="space-between" mb={2}>
                  <Text fontSize="sm">Completed</Text>
                  <Text fontSize="sm" fontWeight="medium">
                    {stats.documents.processed}/{stats.documents.total}
                  </Text>
                </HStack>
                <Progress
                  value={(stats.documents.processed / stats.documents.total) * 100}
                  colorScheme="green"
                  size="sm"
                />
              </Box>

              <Box>
                <HStack justify="space-between" mb={2}>
                  <Text fontSize="sm">Pending</Text>
                  <Text fontSize="sm" fontWeight="medium">
                    {stats.documents.pending}
                  </Text>
                </HStack>
                <Progress
                  value={(stats.documents.pending / stats.documents.total) * 100}
                  colorScheme="yellow"
                  size="sm"
                />
              </Box>

              {stats.documents.failed > 0 && (
                <Box>
                  <HStack justify="space-between" mb={2}>
                    <Text fontSize="sm">Failed</Text>
                    <Text fontSize="sm" fontWeight="medium">
                      {stats.documents.failed}
                    </Text>
                  </HStack>
                  <Progress
                    value={(stats.documents.failed / stats.documents.total) * 100}
                    colorScheme="red"
                    size="sm"
                  />
                </Box>
              )}
            </VStack>
          </CardBody>
        </Card>

        {/* System Resources */}
        <Card>
          <CardHeader>
            <Text fontSize="lg" fontWeight="semibold">
              System Resources
            </Text>
          </CardHeader>
          <CardBody>
            <VStack spacing={4} align="stretch">
              <Box>
                <HStack justify="space-between" mb={2}>
                  <Text fontSize="sm">CPU Usage</Text>
                  <Text fontSize="sm" fontWeight="medium">
                    {stats.system.cpu_usage.toFixed(1)}%
                  </Text>
                </HStack>
                <Progress
                  value={stats.system.cpu_usage}
                  colorScheme={stats.system.cpu_usage > 80 ? 'red' : stats.system.cpu_usage > 60 ? 'yellow' : 'green'}
                  size="sm"
                />
              </Box>

              <Box>
                <HStack justify="space-between" mb={2}>
                  <Text fontSize="sm">Memory Usage</Text>
                  <Text fontSize="sm" fontWeight="medium">
                    {stats.system.memory_usage.toFixed(1)}%
                  </Text>
                </HStack>
                <Progress
                  value={stats.system.memory_usage}
                  colorScheme={stats.system.memory_usage > 80 ? 'red' : stats.system.memory_usage > 60 ? 'yellow' : 'green'}
                  size="sm"
                />
              </Box>

              <Box>
                <HStack justify="space-between" mb={2}>
                  <Text fontSize="sm">Disk Usage</Text>
                  <Text fontSize="sm" fontWeight="medium">
                    {stats.system.disk_usage.toFixed(1)}%
                  </Text>
                </HStack>
                <Progress
                  value={stats.system.disk_usage}
                  colorScheme={stats.system.disk_usage > 80 ? 'red' : stats.system.disk_usage > 60 ? 'yellow' : 'green'}
                  size="sm"
                />
              </Box>
            </VStack>
          </CardBody>
        </Card>

        {/* Chat Performance */}
        <GridItem colSpan={{ base: 1, md: 2 }}>
          <Card>
            <CardHeader>
              <Text fontSize="lg" fontWeight="semibold">
                Chat Performance
              </Text>
            </CardHeader>
            <CardBody>
              <HStack spacing={8} justify="space-around">
                <VStack>
                  <Text fontSize="2xl" fontWeight="bold" color="blue.500">
                    {stats.chats.total_messages}
                  </Text>
                  <Text fontSize="sm" color="gray.600">
                    Total Messages
                  </Text>
                </VStack>
                <Divider orientation="vertical" h="60px" />
                <VStack>
                  <Text fontSize="2xl" fontWeight="bold" color="green.500">
                    {stats.chats.active_conversations}
                  </Text>
                  <Text fontSize="sm" color="gray.600">
                    Active Conversations
                  </Text>
                </VStack>
                <Divider orientation="vertical" h="60px" />
                <VStack>
                  <Text fontSize="2xl" fontWeight="bold" color="purple.500">
                    {stats.chats.average_response_time.toFixed(1)}s
                  </Text>
                  <Text fontSize="sm" color="gray.600">
                    Avg Response Time
                  </Text>
                </VStack>
              </HStack>
            </CardBody>
          </Card>
        </GridItem>
      </Grid>
    </VStack>
  )
}