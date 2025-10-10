/**
 * Page Admin - Gestion Types d'Entités Dynamiques
 *
 * Phase 4 - Frontend UI (Refactored with Chakra UI)
 * Phase 5A - UX Refactoring: Cards groupées + drill-down
 *
 * Affiche les entity types découverts par le LLM avec workflow approve/reject.
 */

'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import {
  Box,
  Container,
  Heading,
  Text,
  SimpleGrid,
  Card,
  CardHeader,
  CardBody,
  Stat,
  StatLabel,
  StatNumber,
  StatHelpText,
  Badge,
  Button,
  Spinner,
  Alert,
  AlertIcon,
  HStack,
  VStack,
  Icon,
  Flex,
  Input,
  Select,
  Table,
  Thead,
  Tbody,
  Tr,
  Th,
  Td,
  useToast,
  Tabs,
  TabList,
  TabPanels,
  Tab,
  TabPanel,
} from "@chakra-ui/react";
import { FiLayers, FiCheckCircle, FiXCircle, FiClock, FiUpload, FiDownload, FiGrid, FiList } from "react-icons/fi";

interface EntityType {
  id: number;
  type_name: string;
  status: string;
  entity_count: number;
  pending_entity_count: number;
  validated_entity_count: number;
  first_seen: string;
  discovered_by: string;
  description?: string;
}

export default function DynamicTypesPage() {
  const [types, setTypes] = useState<EntityType[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [viewMode, setViewMode] = useState<'cards' | 'table'>('cards');
  const toast = useToast();

  useEffect(() => {
    fetchTypes();
  }, [statusFilter]);

  const fetchTypes = async () => {
    setLoading(true);
    try {
      const url = statusFilter === 'all'
        ? '/api/entity-types'
        : `/api/entity-types?status=${statusFilter}`;

      // Get JWT token from localStorage
      const token = localStorage.getItem('auth_token');

      const response = await fetch(url, {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      });
      const data = await response.json();
      setTypes(data.types || []);
    } catch (error) {
      console.error('Error fetching types:', error);
      toast({
        title: 'Erreur',
        description: 'Impossible de charger les types',
        status: 'error',
        duration: 3000,
      });
    } finally {
      setLoading(false);
    }
  };

  const handleApprove = async (typeName: string) => {
    try {
      const response = await fetch(`/api/entity-types/${typeName}/approve`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Admin-Key': 'admin-dev-key-change-in-production'
        },
        body: JSON.stringify({ admin_email: 'admin@example.com' })
      });

      if (response.ok) {
        toast({
          title: 'Type approuvé',
          status: 'success',
          duration: 2000,
        });
        fetchTypes();
      } else {
        throw new Error('Approval failed');
      }
    } catch (error) {
      toast({
        title: 'Erreur',
        description: 'Erreur lors de l\'approbation',
        status: 'error',
        duration: 3000,
      });
    }
  };

  const handleReject = async (typeName: string) => {
    const reason = window.prompt('Raison du rejet ?');
    if (!reason) return;

    try {
      const response = await fetch(`/api/entity-types/${typeName}/reject`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Admin-Key': 'admin-dev-key-change-in-production'
        },
        body: JSON.stringify({
          admin_email: 'admin@example.com',
          rejection_reason: reason
        })
      });

      if (response.ok) {
        toast({
          title: 'Type rejeté',
          status: 'info',
          duration: 2000,
        });
        fetchTypes();
      } else {
        throw new Error('Rejection failed');
      }
    } catch (error) {
      toast({
        title: 'Erreur',
        description: 'Erreur lors du rejet',
        status: 'error',
        duration: 3000,
      });
    }
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      setUploadFile(file);
    }
  };

  const handleImportYAML = async () => {
    if (!uploadFile) return;

    setUploading(true);
    try {
      const formData = new FormData();
      formData.append('file', uploadFile);

      const response = await fetch('/api/entity-types/import-yaml', {
        method: 'POST',
        headers: {
          'X-Admin-Key': 'admin-dev-key-change-in-production'
        },
        body: formData
      });

      if (response.ok) {
        const result = await response.json();
        toast({
          title: 'Import réussi',
          description: `${result.imported_count} types importés`,
          status: 'success',
          duration: 3000,
        });
        setUploadFile(null);
        fetchTypes();
      } else {
        const error = await response.json();
        throw new Error(error.detail);
      }
    } catch (error: any) {
      toast({
        title: 'Erreur import',
        description: error.message,
        status: 'error',
        duration: 5000,
      });
    } finally {
      setUploading(false);
    }
  };

  const handleExportYAML = async (statusExport: string = 'approved') => {
    try {
      const url = `/api/entity-types/export-yaml?status=${statusExport}`;
      const response = await fetch(url);

      if (response.ok) {
        const blob = await response.blob();
        const downloadUrl = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = downloadUrl;
        a.download = `entity_types_${statusExport}_default.yaml`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(downloadUrl);

        toast({
          title: 'Export réussi',
          status: 'success',
          duration: 2000,
        });
      } else {
        throw new Error('Export failed');
      }
    } catch (error) {
      toast({
        title: 'Erreur export',
        status: 'error',
        duration: 3000,
      });
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'pending': return 'yellow';
      case 'approved': return 'green';
      case 'rejected': return 'red';
      default: return 'gray';
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'pending': return FiClock;
      case 'approved': return FiCheckCircle;
      case 'rejected': return FiXCircle;
      default: return FiLayers;
    }
  };

  if (loading) {
    return (
      <Container maxW="container.xl" py={8}>
        <VStack spacing={4}>
          <Spinner size="xl" />
          <Text>Chargement des types...</Text>
        </VStack>
      </Container>
    );
  }

  return (
    <Container maxW="container.xl" py={8}>
      <VStack spacing={6} align="stretch">
        {/* Header */}
        <Flex justify="space-between" align="center">
          <Heading size="lg">
            <Icon as={FiLayers} mr={3} />
            Types d'Entités Dynamiques
          </Heading>

          {/* Toggle View Mode */}
          <HStack>
            <Button
              size="sm"
              leftIcon={<FiGrid />}
              colorScheme={viewMode === 'cards' ? 'blue' : 'gray'}
              onClick={() => setViewMode('cards')}
            >
              Cards
            </Button>
            <Button
              size="sm"
              leftIcon={<FiList />}
              colorScheme={viewMode === 'table' ? 'blue' : 'gray'}
              onClick={() => setViewMode('table')}
            >
              Table
            </Button>
          </HStack>
        </Flex>

        {/* Import/Export Section */}
        <Card>
          <CardHeader>
            <Heading size="md">Import / Export YAML</Heading>
          </CardHeader>
          <CardBody>
            <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
              {/* Import */}
              <Box>
                <Text fontWeight="bold" mb={2}>
                  <Icon as={FiUpload} mr={2} />
                  Importer Ontologie YAML
                </Text>
                <HStack>
                  <Input
                    type="file"
                    accept=".yaml,.yml"
                    onChange={handleFileUpload}
                    size="sm"
                    disabled={uploading}
                  />
                  <Button
                    onClick={handleImportYAML}
                    isDisabled={!uploadFile || uploading}
                    isLoading={uploading}
                    colorScheme="blue"
                    size="sm"
                  >
                    Importer
                  </Button>
                </HStack>
              </Box>

              {/* Export */}
              <Box>
                <Text fontWeight="bold" mb={2}>
                  <Icon as={FiDownload} mr={2} />
                  Exporter Types
                </Text>
                <HStack>
                  <Select size="sm" id="exportStatus" defaultValue="approved">
                    <option value="approved">Approuvés</option>
                    <option value="pending">En attente</option>
                    <option value="all">Tous</option>
                  </Select>
                  <Button
                    onClick={() => {
                      const select = document.getElementById('exportStatus') as HTMLSelectElement;
                      handleExportYAML(select.value);
                    }}
                    colorScheme="green"
                    size="sm"
                  >
                    Exporter
                  </Button>
                </HStack>
              </Box>
            </SimpleGrid>
          </CardBody>
        </Card>

        {/* Filters */}
        <HStack>
          <Text fontWeight="bold">Filtre:</Text>
          <Button
            size="sm"
            variant={statusFilter === 'all' ? 'solid' : 'outline'}
            colorScheme="blue"
            onClick={() => setStatusFilter('all')}
          >
            Tous ({types.length})
          </Button>
          <Button
            size="sm"
            variant={statusFilter === 'pending' ? 'solid' : 'outline'}
            colorScheme="yellow"
            onClick={() => setStatusFilter('pending')}
          >
            En attente
          </Button>
          <Button
            size="sm"
            variant={statusFilter === 'approved' ? 'solid' : 'outline'}
            colorScheme="green"
            onClick={() => setStatusFilter('approved')}
          >
            Approuvés
          </Button>
          <Button
            size="sm"
            variant={statusFilter === 'rejected' ? 'solid' : 'outline'}
            colorScheme="red"
            onClick={() => setStatusFilter('rejected')}
          >
            Rejetés
          </Button>
        </HStack>

        {/* Empty State */}
        {types.length === 0 && (
          <Alert status="info">
            <AlertIcon />
            Aucun type trouvé pour ce filtre.
          </Alert>
        )}

        {/* Cards View */}
        {viewMode === 'cards' && types.length > 0 && (
          <SimpleGrid columns={{ base: 1, md: 2, lg: 3 }} spacing={4}>
            {types.map((type) => (
              <Card
                key={type.id}
                borderWidth={2}
                borderColor={`${getStatusColor(type.status)}.300`}
                _hover={{ shadow: 'lg', transform: 'translateY(-2px)' }}
                transition="all 0.2s"
              >
                <CardHeader pb={2}>
                  <Flex justify="space-between" align="center">
                    <HStack>
                      <Icon as={getStatusIcon(type.status)} boxSize={5} />
                      <Heading size="md">{type.type_name}</Heading>
                    </HStack>
                    <Badge colorScheme={getStatusColor(type.status)}>
                      {type.status}
                    </Badge>
                  </Flex>
                </CardHeader>

                <CardBody>
                  <VStack align="stretch" spacing={3}>
                    {/* Statistics */}
                    <SimpleGrid columns={3} spacing={2}>
                      <Stat size="sm">
                        <StatLabel fontSize="xs">Total</StatLabel>
                        <StatNumber fontSize="lg">{type.entity_count}</StatNumber>
                      </Stat>
                      <Stat size="sm">
                        <StatLabel fontSize="xs">En attente</StatLabel>
                        <StatNumber fontSize="lg" color="yellow.500">
                          {type.pending_entity_count}
                        </StatNumber>
                      </Stat>
                      <Stat size="sm">
                        <StatLabel fontSize="xs">Validés</StatLabel>
                        <StatNumber fontSize="lg" color="green.500">
                          {type.validated_entity_count}
                        </StatNumber>
                      </Stat>
                    </SimpleGrid>

                    {/* Description */}
                    {type.description && (
                      <Text fontSize="sm" color="gray.600">
                        {type.description}
                      </Text>
                    )}

                    {/* Metadata */}
                    <Text fontSize="xs" color="gray.500">
                      Découvert: {new Date(type.first_seen).toLocaleDateString()}
                      {' • '}
                      Par: {type.discovered_by}
                    </Text>

                    {/* Actions */}
                    <VStack spacing={2}>
                      <Link href={`/admin/dynamic-types/${type.type_name}`} style={{ width: '100%' }}>
                        <Button
                          size="sm"
                          colorScheme="blue"
                          variant="outline"
                          width="100%"
                        >
                          👁️ Voir entités ({type.entity_count})
                        </Button>
                      </Link>

                      {type.status === 'pending' && (
                        <HStack width="100%" spacing={2}>
                          <Button
                            size="sm"
                            colorScheme="green"
                            onClick={() => handleApprove(type.type_name)}
                            flex={1}
                          >
                            ✅ Approuver
                          </Button>
                          <Button
                            size="sm"
                            colorScheme="red"
                            onClick={() => handleReject(type.type_name)}
                            flex={1}
                          >
                            ❌ Rejeter
                          </Button>
                        </HStack>
                      )}
                    </VStack>
                  </VStack>
                </CardBody>
              </Card>
            ))}
          </SimpleGrid>
        )}

        {/* Table View */}
        {viewMode === 'table' && types.length > 0 && (
          <Card>
            <CardBody p={0}>
              <Table variant="simple">
                <Thead>
                  <Tr>
                    <Th>Type</Th>
                    <Th>Status</Th>
                    <Th isNumeric>Total</Th>
                    <Th isNumeric>En attente</Th>
                    <Th isNumeric>Validés</Th>
                    <Th>Découvert</Th>
                    <Th>Actions</Th>
                  </Tr>
                </Thead>
                <Tbody>
                  {types.map((type) => (
                    <Tr key={type.id}>
                      <Td fontWeight="bold">{type.type_name}</Td>
                      <Td>
                        <Badge colorScheme={getStatusColor(type.status)}>
                          {type.status}
                        </Badge>
                      </Td>
                      <Td isNumeric>{type.entity_count}</Td>
                      <Td isNumeric>
                        <Text color="yellow.500">{type.pending_entity_count}</Text>
                      </Td>
                      <Td isNumeric>
                        <Text color="green.500">{type.validated_entity_count}</Text>
                      </Td>
                      <Td fontSize="sm">
                        {new Date(type.first_seen).toLocaleDateString()}
                      </Td>
                      <Td>
                        <HStack spacing={2}>
                          <Link href={`/admin/dynamic-types/${type.type_name}`}>
                            <Button size="xs" colorScheme="blue" variant="outline">
                              Voir
                            </Button>
                          </Link>
                          {type.status === 'pending' && (
                            <>
                              <Button
                                size="xs"
                                colorScheme="green"
                                onClick={() => handleApprove(type.type_name)}
                              >
                                ✓
                              </Button>
                              <Button
                                size="xs"
                                colorScheme="red"
                                onClick={() => handleReject(type.type_name)}
                              >
                                ✗
                              </Button>
                            </>
                          )}
                        </HStack>
                      </Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>
            </CardBody>
          </Card>
        )}
      </VStack>
    </Container>
  );
}
