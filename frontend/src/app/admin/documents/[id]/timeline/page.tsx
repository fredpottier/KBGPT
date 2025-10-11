'use client'

import { use, useState } from 'react'
import {
  Box,
  Card,
  CardBody,
  CardHeader,
  VStack,
  HStack,
  Text,
  Badge,
  Icon,
  Spinner,
  Center,
  Button,
  Divider,
  Tooltip,
  Avatar,
  Flex,
  Heading,
  Switch,
  FormControl,
  FormLabel,
  Alert,
  AlertIcon,
  AlertTitle,
  AlertDescription,
} from '@chakra-ui/react'
import {
  TimeIcon,
  CheckCircleIcon,
  WarningIcon,
  ArrowBackIcon,
  ViewIcon,
} from '@chakra-ui/icons'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useRouter } from 'next/navigation'
import { formatDistanceToNow } from '@/lib/date-utils'
import { useLocale } from '@/contexts/LocaleContext'

interface TimelineItemProps {
  version: any
  isLatest: boolean
  isFirst: boolean
  onClick: () => void
}

const TimelineItem = ({ version, isLatest, isFirst, onClick }: TimelineItemProps) => {
  const { locale } = useLocale()
  const effectiveDate = new Date(version.effective_date)
  const createdAt = new Date(version.created_at)

  return (
    <HStack spacing={4} align="flex-start" position="relative" pb={isFirst ? 0 : 8}>
      {/* Timeline connector line */}
      {!isFirst && (
        <Box
          position="absolute"
          left="20px"
          top="-8"
          bottom="16"
          width="2px"
          bg="gray.200"
          zIndex={0}
        />
      )}

      {/* Timeline dot */}
      <Box position="relative" zIndex={1}>
        <Avatar
          size="sm"
          bg={isLatest ? 'green.500' : 'gray.400'}
          icon={<Icon as={isLatest ? CheckCircleIcon : TimeIcon} />}
        />
      </Box>

      {/* Timeline content card */}
      <Card flex={1} cursor="pointer" onClick={onClick} _hover={{ shadow: 'md' }}>
        <CardBody>
          <VStack align="stretch" spacing={3}>
            <HStack justify="space-between">
              <HStack spacing={3}>
                <Heading size="sm">{version.version_label}</Heading>
                {isLatest && (
                  <Badge colorScheme="green" fontSize="xs">
                    Version Actuelle
                  </Badge>
                )}
                {version.status === 'obsolete' && (
                  <Badge colorScheme="orange" fontSize="xs">
                    Obsolète
                  </Badge>
                )}
              </HStack>
              <Tooltip label="Voir détails">
                <Icon as={ViewIcon} color="gray.500" />
              </Tooltip>
            </HStack>

            <Divider />

            <HStack spacing={6} fontSize="sm" color="gray.600">
              <HStack>
                <Icon as={TimeIcon} />
                <Text>
                  {formatDistanceToNow(effectiveDate, locale)}
                </Text>
              </HStack>
              {version.author_name && (
                <Text fontWeight="medium">Par {version.author_name}</Text>
              )}
            </HStack>

            <Box fontSize="sm">
              <HStack spacing={4}>
                <Text>
                  <strong>Date effective:</strong>{' '}
                  {effectiveDate.toLocaleDateString('fr-FR')}
                </Text>
                <Text>
                  <strong>Taille:</strong>{' '}
                  {(version.file_size / 1024 / 1024).toFixed(2)} MB
                </Text>
              </HStack>
            </Box>

            {version.description && (
              <Text fontSize="sm" color="gray.700">
                {version.description}
              </Text>
            )}

            <HStack spacing={2} flexWrap="wrap">
              {version.metadata && Object.keys(version.metadata).length > 0 && (
                <>
                  {Object.entries(version.metadata)
                    .slice(0, 3)
                    .map(([key, value]) => (
                      <Badge key={key} variant="subtle" colorScheme="blue" fontSize="xs">
                        {key}: {String(value)}
                      </Badge>
                    ))}
                  {Object.keys(version.metadata).length > 3 && (
                    <Badge variant="subtle" colorScheme="gray" fontSize="xs">
                      +{Object.keys(version.metadata).length - 3} more
                    </Badge>
                  )}
                </>
              )}
            </HStack>

            <Text fontSize="xs" color="gray.500">
              Checksum: {version.checksum.substring(0, 16)}...
            </Text>
          </VStack>
        </CardBody>
      </Card>
    </HStack>
  )
}

export default function DocumentTimelinePage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = use(params)
  const router = useRouter()

  const {
    data: documentResponse,
    isLoading: isLoadingDoc,
    error: docError,
  } = useQuery({
    queryKey: ['documents', id],
    queryFn: () => api.documents.getById(id),
  })

  const {
    data: versionsResponse,
    isLoading: isLoadingVersions,
    error: versionsError,
  } = useQuery({
    queryKey: ['documents', id, 'versions'],
    queryFn: () => api.documents.getVersions(id),
  })

  const isLoading = isLoadingDoc || isLoadingVersions
  const error = docError || versionsError

  if (isLoading) {
    return (
      <Center h="400px">
        <Spinner size="xl" color="brand.500" />
      </Center>
    )
  }

  if (error || !documentResponse?.success || !versionsResponse?.success) {
    return (
      <Card>
        <CardBody>
          <Center py={12}>
            <VStack spacing={4}>
              <Icon as={WarningIcon} boxSize={12} color="red.500" />
              <Text fontSize="lg" color="red.500">
                Erreur lors du chargement du document
              </Text>
              <Button onClick={() => router.back()} leftIcon={<ArrowBackIcon />}>
                Retour
              </Button>
            </VStack>
          </Center>
        </CardBody>
      </Card>
    )
  }

  const document = documentResponse.data
  const allVersions = versionsResponse.data.versions || []

  // State for filters
  const [showActiveOnly, setShowActiveOnly] = useState(false)

  // Apply filters
  const versions = showActiveOnly
    ? allVersions.filter((v: any) => v.status !== 'obsolete' && v.is_latest !== false)
    : allVersions

  // Check if there are obsolete versions
  const hasObsoleteVersions = allVersions.some((v: any) => v.status === 'obsolete' || !v.is_latest)
  const filteredCount = allVersions.length - versions.length

  return (
    <VStack spacing={6} align="stretch">
      {/* Header */}
      <Flex justify="space-between" align="center">
        <Box>
          <HStack spacing={3} mb={2}>
            <Button
              size="sm"
              variant="ghost"
              leftIcon={<ArrowBackIcon />}
              onClick={() => router.back()}
            >
              Retour
            </Button>
          </HStack>
          <Heading size="lg">{document.title}</Heading>
          <Text color="gray.600" mt={2}>
            Timeline des versions du document
          </Text>
        </Box>
        <HStack spacing={3}>
          <Button
            size="sm"
            colorScheme="blue"
            onClick={() => router.push(`/admin/documents/${id}/compare`)}
          >
            Comparer les versions
          </Button>
        </HStack>
      </Flex>

      {/* Document Info Card */}
      <Card>
        <CardHeader>
          <Text fontSize="lg" fontWeight="semibold">
            Informations Document
          </Text>
        </CardHeader>
        <CardBody>
          <VStack align="stretch" spacing={2}>
            <HStack>
              <Text fontWeight="medium" w="150px">
                Type:
              </Text>
              <Badge colorScheme="purple">{document.document_type}</Badge>
            </HStack>
            <HStack>
              <Text fontWeight="medium" w="150px">
                Statut:
              </Text>
              <Badge
                colorScheme={
                  document.status === 'active'
                    ? 'green'
                    : document.status === 'archived'
                    ? 'gray'
                    : 'orange'
                }
              >
                {document.status}
              </Badge>
            </HStack>
            <HStack>
              <Text fontWeight="medium" w="150px">
                Versions totales:
              </Text>
              <Text>{versions.length}</Text>
            </HStack>
            {document.source_path && (
              <HStack>
                <Text fontWeight="medium" w="150px">
                  Chemin source:
                </Text>
                <Text fontSize="sm" fontFamily="mono" color="gray.600">
                  {document.source_path}
                </Text>
              </HStack>
            )}
          </VStack>
        </CardBody>
      </Card>

      {/* Timeline */}
      <Card>
        <CardHeader>
          <VStack align="stretch" spacing={3}>
            <HStack justify="space-between">
              <Text fontSize="lg" fontWeight="semibold">
                Historique des Versions
              </Text>
              <HStack spacing={3}>
                <Badge colorScheme="blue">{allVersions.length} version(s) totale(s)</Badge>
                {filteredCount > 0 && (
                  <Badge colorScheme="orange">{filteredCount} masquée(s)</Badge>
                )}
              </HStack>
            </HStack>

            {hasObsoleteVersions && (
              <HStack spacing={4}>
                <FormControl display="flex" alignItems="center" width="auto">
                  <FormLabel htmlFor="active-only" mb="0" fontSize="sm">
                    Afficher uniquement les versions actives
                  </FormLabel>
                  <Switch
                    id="active-only"
                    isChecked={showActiveOnly}
                    onChange={(e) => setShowActiveOnly(e.target.checked)}
                    colorScheme="blue"
                  />
                </FormControl>
                <Tooltip label="Masque les anciennes versions et versions obsolètes">
                  <Icon as={WarningIcon} color="gray.400" boxSize={4} />
                </Tooltip>
              </HStack>
            )}
          </VStack>
        </CardHeader>
        <CardBody>
          {versions.length === 0 ? (
            <Center py={8}>
              <Text color="gray.500">Aucune version trouvée</Text>
            </Center>
          ) : (
            <VStack align="stretch" spacing={0}>
              {versions.map((version: any, index: number) => (
                <TimelineItem
                  key={version.version_id}
                  version={version}
                  isLatest={version.is_latest}
                  isFirst={index === versions.length - 1}
                  onClick={() => {
                    // Navigate to version detail or open modal
                    console.log('Version clicked:', version.version_id)
                  }}
                />
              ))}
            </VStack>
          )}
        </CardBody>
      </Card>
    </VStack>
  )
}
