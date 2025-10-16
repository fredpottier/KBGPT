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
  Select,
  Grid,
  GridItem,
  Divider,
  Table,
  Thead,
  Tbody,
  Tr,
  Th,
  Td,
  Heading,
  Flex,
  Alert,
  AlertIcon,
  Tooltip,
} from '@chakra-ui/react'
import {
  ArrowBackIcon,
  WarningIcon,
  CheckCircleIcon,
  InfoIcon,
} from '@chakra-ui/icons'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useRouter } from 'next/navigation'

const DiffRow = ({
  label,
  value1,
  value2,
  isDifferent
}: {
  label: string
  value1: any
  value2: any
  isDifferent: boolean
}) => {
  return (
    <Tr bg={isDifferent ? 'yellow.50' : 'white'}>
      <Td fontWeight="medium" width="200px">
        {isDifferent && <Icon as={WarningIcon} color="orange.500" mr={2} boxSize={3} />}
        {label}
      </Td>
      <Td>
        <Text fontFamily={typeof value1 === 'string' && value1.length > 50 ? 'mono' : 'inherit'} fontSize="sm">
          {typeof value1 === 'object' ? JSON.stringify(value1, null, 2) : String(value1 || '-')}
        </Text>
      </Td>
      <Td>
        <Text fontFamily={typeof value2 === 'string' && value2.length > 50 ? 'mono' : 'inherit'} fontSize="sm">
          {typeof value2 === 'object' ? JSON.stringify(value2, null, 2) : String(value2 || '-')}
        </Text>
      </Td>
    </Tr>
  )
}

const MetadataDiffTable = ({ metadata1, metadata2 }: { metadata1: any; metadata2: any }) => {
  // Merge keys from both metadata objects
  const allKeys = Array.from(
    new Set([
      ...Object.keys(metadata1 || {}),
      ...Object.keys(metadata2 || {}),
    ])
  ).sort()

  if (allKeys.length === 0) {
    return (
      <Text color="gray.500" fontSize="sm">
        Aucune métadonnée à comparer
      </Text>
    )
  }

  return (
    <Table size="sm" variant="simple">
      <Thead>
        <Tr>
          <Th width="200px">Clé</Th>
          <Th>Version 1</Th>
          <Th>Version 2</Th>
        </Tr>
      </Thead>
      <Tbody>
        {allKeys.map((key) => {
          const val1 = metadata1?.[key]
          const val2 = metadata2?.[key]
          const isDifferent = JSON.stringify(val1) !== JSON.stringify(val2)
          return (
            <DiffRow
              key={key}
              label={key}
              value1={val1}
              value2={val2}
              isDifferent={isDifferent}
            />
          )
        })}
      </Tbody>
    </Table>
  )
}

export default function DocumentComparePage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = use(params)
  const router = useRouter()

  const [version1Id, setVersion1Id] = useState<string>('')
  const [version2Id, setVersion2Id] = useState<string>('')

  const {
    data: versionsResponse,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['documents', id, 'versions'],
    queryFn: () => api.documents.getVersions(id),
  })

  if (isLoading) {
    return (
      <Center h="400px">
        <Spinner size="xl" color="brand.500" />
      </Center>
    )
  }

  if (error || !versionsResponse?.success) {
    return (
      <Card>
        <CardBody>
          <Center py={12}>
            <VStack spacing={4}>
              <Icon as={WarningIcon} boxSize={12} color="red.500" />
              <Text fontSize="lg" color="red.500">
                Erreur lors du chargement des versions
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

  const versions = versionsResponse.data.versions || []

  // Find selected versions
  const selectedVersion1 = versions.find((v: any) => v.version_id === version1Id)
  const selectedVersion2 = versions.find((v: any) => v.version_id === version2Id)

  const canCompare = selectedVersion1 && selectedVersion2 && version1Id !== version2Id

  // Calculate differences
  const differences = canCompare ? {
    version_label: selectedVersion1.version_label !== selectedVersion2.version_label,
    effective_date: selectedVersion1.effective_date !== selectedVersion2.effective_date,
    checksum: selectedVersion1.checksum !== selectedVersion2.checksum,
    file_size: selectedVersion1.file_size !== selectedVersion2.file_size,
    author_name: selectedVersion1.author_name !== selectedVersion2.author_name,
    description: selectedVersion1.description !== selectedVersion2.description,
  } : {}

  const differenceCount = Object.values(differences).filter(Boolean).length

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
          <Heading size="lg">Comparaison de Versions</Heading>
          <Text color="gray.600" mt={2}>
            Comparez les différences entre deux versions du document
          </Text>
        </Box>
        <HStack spacing={3}>
          <Button
            size="sm"
            colorScheme="blue"
            onClick={() => router.push(`/admin/documents/${id}/timeline`)}
          >
            Voir Timeline
          </Button>
        </HStack>
      </Flex>

      {/* Version Selectors */}
      <Card>
        <CardHeader>
          <Text fontSize="lg" fontWeight="semibold">
            Sélection des Versions
          </Text>
        </CardHeader>
        <CardBody>
          <Grid templateColumns="repeat(2, 1fr)" gap={6}>
            <GridItem>
              <VStack align="stretch" spacing={2}>
                <Text fontWeight="medium">Version 1</Text>
                <Select
                  placeholder="Sélectionner une version..."
                  value={version1Id}
                  onChange={(e) => setVersion1Id(e.target.value)}
                >
                  {versions.map((version: any) => (
                    <option key={version.version_id} value={version.version_id}>
                      {version.version_label} -{' '}
                      {new Date(version.effective_date).toLocaleDateString('fr-FR')}
                      {version.is_latest && ' (Actuelle)'}
                    </option>
                  ))}
                </Select>
              </VStack>
            </GridItem>

            <GridItem>
              <VStack align="stretch" spacing={2}>
                <Text fontWeight="medium">Version 2</Text>
                <Select
                  placeholder="Sélectionner une version..."
                  value={version2Id}
                  onChange={(e) => setVersion2Id(e.target.value)}
                >
                  {versions.map((version: any) => (
                    <option key={version.version_id} value={version.version_id}>
                      {version.version_label} -{' '}
                      {new Date(version.effective_date).toLocaleDateString('fr-FR')}
                      {version.is_latest && ' (Actuelle)'}
                    </option>
                  ))}
                </Select>
              </VStack>
            </GridItem>
          </Grid>

          {canCompare && (
            <Alert status="success" mt={4} borderRadius="md">
              <AlertIcon />
              <Box>
                <Text fontWeight="medium">
                  {differenceCount} différence(s) détectée(s) entre les deux versions
                </Text>
              </Box>
            </Alert>
          )}

          {version1Id && version2Id && version1Id === version2Id && (
            <Alert status="warning" mt={4} borderRadius="md">
              <AlertIcon />
              Vous avez sélectionné la même version deux fois
            </Alert>
          )}
        </CardBody>
      </Card>

      {/* Comparison Results */}
      {canCompare && (
        <>
          {/* Version Info Side by Side */}
          <Card>
            <CardHeader>
              <HStack justify="space-between">
                <Text fontSize="lg" fontWeight="semibold">
                  Informations des Versions
                </Text>
                <Badge colorScheme={differenceCount > 0 ? 'orange' : 'green'}>
                  {differenceCount} changement(s)
                </Badge>
              </HStack>
            </CardHeader>
            <CardBody>
              <Table variant="simple" size="sm">
                <Thead>
                  <Tr>
                    <Th width="200px">Propriété</Th>
                    <Th>
                      <Badge colorScheme="blue">Version 1</Badge>
                      <Text fontSize="sm" mt={1}>
                        {selectedVersion1.version_label}
                      </Text>
                    </Th>
                    <Th>
                      <Badge colorScheme="purple">Version 2</Badge>
                      <Text fontSize="sm" mt={1}>
                        {selectedVersion2.version_label}
                      </Text>
                    </Th>
                  </Tr>
                </Thead>
                <Tbody>
                  <DiffRow
                    label="Libellé Version"
                    value1={selectedVersion1.version_label}
                    value2={selectedVersion2.version_label}
                    isDifferent={differences.version_label}
                  />
                  <DiffRow
                    label="Date Effective"
                    value1={new Date(selectedVersion1.effective_date).toLocaleString('fr-FR')}
                    value2={new Date(selectedVersion2.effective_date).toLocaleString('fr-FR')}
                    isDifferent={differences.effective_date}
                  />
                  <DiffRow
                    label="Auteur"
                    value1={selectedVersion1.author_name}
                    value2={selectedVersion2.author_name}
                    isDifferent={differences.author_name}
                  />
                  <DiffRow
                    label="Taille Fichier"
                    value1={`${(selectedVersion1.file_size / 1024 / 1024).toFixed(2)} MB`}
                    value2={`${(selectedVersion2.file_size / 1024 / 1024).toFixed(2)} MB`}
                    isDifferent={differences.file_size}
                  />
                  <DiffRow
                    label="Checksum (SHA256)"
                    value1={selectedVersion1.checksum.substring(0, 32) + '...'}
                    value2={selectedVersion2.checksum.substring(0, 32) + '...'}
                    isDifferent={differences.checksum}
                  />
                  <DiffRow
                    label="Description"
                    value1={selectedVersion1.description}
                    value2={selectedVersion2.description}
                    isDifferent={differences.description}
                  />
                  <DiffRow
                    label="Statut"
                    value1={
                      <Badge colorScheme={selectedVersion1.is_latest ? 'green' : 'gray'}>
                        {selectedVersion1.is_latest ? 'Version actuelle' : 'Ancienne version'}
                      </Badge>
                    }
                    value2={
                      <Badge colorScheme={selectedVersion2.is_latest ? 'green' : 'gray'}>
                        {selectedVersion2.is_latest ? 'Version actuelle' : 'Ancienne version'}
                      </Badge>
                    }
                    isDifferent={selectedVersion1.is_latest !== selectedVersion2.is_latest}
                  />
                  <DiffRow
                    label="Créé le"
                    value1={new Date(selectedVersion1.created_at).toLocaleString('fr-FR')}
                    value2={new Date(selectedVersion2.created_at).toLocaleString('fr-FR')}
                    isDifferent={selectedVersion1.created_at !== selectedVersion2.created_at}
                  />
                </Tbody>
              </Table>
            </CardBody>
          </Card>

          {/* Metadata Comparison */}
          <Card>
            <CardHeader>
              <HStack justify="space-between">
                <Text fontSize="lg" fontWeight="semibold">
                  Comparaison des Métadonnées
                </Text>
                <Tooltip label="Les lignes surlignées en jaune indiquent des différences">
                  <Icon as={InfoIcon} color="gray.500" />
                </Tooltip>
              </HStack>
            </CardHeader>
            <CardBody>
              <MetadataDiffTable
                metadata1={selectedVersion1.metadata}
                metadata2={selectedVersion2.metadata}
              />
            </CardBody>
          </Card>
        </>
      )}

      {/* Empty State */}
      {!canCompare && versions.length > 0 && (
        <Card>
          <CardBody>
            <Center py={12}>
              <VStack spacing={4}>
                <Icon as={InfoIcon} boxSize={12} color="blue.500" />
                <Text fontSize="lg" color="gray.600">
                  Sélectionnez deux versions différentes pour les comparer
                </Text>
              </VStack>
            </Center>
          </CardBody>
        </Card>
      )}

      {/* No versions available */}
      {versions.length === 0 && (
        <Card>
          <CardBody>
            <Center py={12}>
              <VStack spacing={4}>
                <Icon as={WarningIcon} boxSize={12} color="orange.500" />
                <Text fontSize="lg" color="gray.600">
                  Aucune version disponible pour ce document
                </Text>
              </VStack>
            </Center>
          </CardBody>
        </Card>
      )}
    </VStack>
  )
}
