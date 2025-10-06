/**
 * Page Drill-Down - Entités d'un Type Spécifique
 *
 * Phase 5A - UX Refactoring (Chakra UI)
 *
 * Affiche toutes les entités d'un type donné avec actions:
 * - Approve individuel
 * - Bulk approve
 * - Génération ontologie (si type approved)
 */

'use client';

import { useState, useEffect } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import {
  Box,
  Container,
  Heading,
  Text,
  Card,
  CardHeader,
  CardBody,
  Stat,
  StatLabel,
  StatNumber,
  Badge,
  Button,
  Spinner,
  Alert,
  AlertIcon,
  HStack,
  VStack,
  Icon,
  Flex,
  Table,
  Thead,
  Tbody,
  Tr,
  Th,
  Td,
  Checkbox,
  useToast,
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  SimpleGrid,
  Divider,
} from "@chakra-ui/react";
import {
  FiLayers,
  FiCheckCircle,
  FiClock,
  FiArrowLeft,
  FiCheckSquare,
  FiCpu,
} from "react-icons/fi";

interface Entity {
  uuid: string;
  name: string;
  entity_type: string;
  status: string;
  description?: string;
  confidence?: number;
  source_document?: string;
  created_at: string;
  validated_at?: string;
  validated_by?: string;
}

interface TypeInfo {
  type_name: string;
  status: string;
  entity_count: number;
  pending_entity_count: number;
  validated_entity_count: number;
  description?: string;
}

export default function TypeEntitiesPage() {
  const params = useParams();
  const router = useRouter();
  const typeName = params.typeName as string;
  const toast = useToast();

  const [entities, setEntities] = useState<Entity[]>([]);
  const [typeInfo, setTypeInfo] = useState<TypeInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [selectedEntities, setSelectedEntities] = useState<Set<string>>(new Set());

  useEffect(() => {
    fetchTypeInfo();
    fetchEntities();
  }, [typeName, statusFilter]);

  const fetchTypeInfo = async () => {
    try {
      const response = await fetch(`/api/entity-types/${typeName}`);
      if (response.ok) {
        const data = await response.json();
        setTypeInfo(data);
      }
    } catch (error) {
      console.error('Error fetching type info:', error);
    }
  };

  const fetchEntities = async () => {
    setLoading(true);
    try {
      const url = statusFilter === 'all'
        ? `/api/entities?entity_type=${typeName}`
        : `/api/entities?entity_type=${typeName}&status=${statusFilter}`;

      const response = await fetch(url);
      const data = await response.json();
      setEntities(data.entities || []);
    } catch (error) {
      console.error('Error fetching entities:', error);
      toast({
        title: 'Erreur',
        description: 'Impossible de charger les entités',
        status: 'error',
        duration: 3000,
      });
    } finally {
      setLoading(false);
    }
  };

  const handleApproveEntity = async (uuid: string) => {
    try {
      const response = await fetch(`/api/entities/${uuid}/approve`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Admin-Key': 'admin-dev-key-change-in-production'
        },
        body: JSON.stringify({ admin_email: 'admin@example.com' })
      });

      if (response.ok) {
        toast({
          title: 'Entité approuvée',
          status: 'success',
          duration: 2000,
        });
        fetchEntities();
        fetchTypeInfo();
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

  const handleBulkApprove = async () => {
    if (selectedEntities.size === 0) {
      toast({
        title: 'Aucune sélection',
        description: 'Sélectionnez au moins une entité',
        status: 'warning',
        duration: 2000,
      });
      return;
    }

    let approved = 0;
    for (const uuid of selectedEntities) {
      try {
        const response = await fetch(`/api/entities/${uuid}/approve`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Admin-Key': 'admin-dev-key-change-in-production'
          },
          body: JSON.stringify({ admin_email: 'admin@example.com' })
        });

        if (response.ok) approved++;
      } catch (error) {
        console.error(`Error approving entity ${uuid}:`, error);
      }
    }

    toast({
      title: `${approved} entité(s) approuvée(s)`,
      status: 'success',
      duration: 3000,
    });

    setSelectedEntities(new Set());
    fetchEntities();
    fetchTypeInfo();
  };

  const handleGenerateOntology = async () => {
    if (!typeInfo || typeInfo.status !== 'approved') {
      toast({
        title: 'Type non approuvé',
        description: 'Le type doit être approuvé avant de générer l\'ontologie',
        status: 'warning',
        duration: 3000,
      });
      return;
    }

    try {
      const response = await fetch(`/api/entity-types/${typeName}/generate-ontology`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Admin-Key': 'admin-dev-key-change-in-production'
        },
        body: JSON.stringify({ model_preference: 'claude-sonnet' })
      });

      if (response.ok) {
        const result = await response.json();
        toast({
          title: 'Génération démarrée',
          description: `Job ID: ${result.job_id}`,
          status: 'info',
          duration: 5000,
        });
      } else {
        throw new Error('Generation failed');
      }
    } catch (error) {
      toast({
        title: 'Erreur',
        description: 'Erreur lors du lancement de la génération',
        status: 'error',
        duration: 3000,
      });
    }
  };

  const handleToggleEntity = (uuid: string) => {
    const newSelected = new Set(selectedEntities);
    if (newSelected.has(uuid)) {
      newSelected.delete(uuid);
    } else {
      newSelected.add(uuid);
    }
    setSelectedEntities(newSelected);
  };

  const handleToggleAll = () => {
    if (selectedEntities.size === entities.length) {
      setSelectedEntities(new Set());
    } else {
      setSelectedEntities(new Set(entities.map(e => e.uuid)));
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'pending': return 'yellow';
      case 'validated': return 'green';
      default: return 'gray';
    }
  };

  if (loading && !typeInfo) {
    return (
      <Container maxW="container.xl" py={8}>
        <VStack spacing={4}>
          <Spinner size="xl" />
          <Text>Chargement...</Text>
        </VStack>
      </Container>
    );
  }

  return (
    <Container maxW="container.xl" py={8}>
      <VStack spacing={6} align="stretch">
        {/* Breadcrumb */}
        <Breadcrumb>
          <BreadcrumbItem>
            <BreadcrumbLink as={Link} href="/admin/dynamic-types">
              <Icon as={FiArrowLeft} mr={2} />
              Types Dynamiques
            </BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbItem isCurrentPage>
            <BreadcrumbLink>{typeName}</BreadcrumbLink>
          </BreadcrumbItem>
        </Breadcrumb>

        {/* Type Info Card */}
        {typeInfo && (
          <Card borderWidth={2} borderColor={`${getStatusColor(typeInfo.status)}.300`}>
            <CardHeader>
              <Flex justify="space-between" align="center">
                <HStack>
                  <Icon as={FiLayers} boxSize={6} />
                  <Heading size="lg">{typeInfo.type_name}</Heading>
                </HStack>
                <Badge colorScheme={getStatusColor(typeInfo.status)} fontSize="md" px={3} py={1}>
                  {typeInfo.status}
                </Badge>
              </Flex>
            </CardHeader>

            <CardBody>
              <SimpleGrid columns={{ base: 1, md: 3 }} spacing={4}>
                <Stat>
                  <StatLabel>Total Entités</StatLabel>
                  <StatNumber>{typeInfo.entity_count}</StatNumber>
                </Stat>
                <Stat>
                  <StatLabel>En attente</StatLabel>
                  <StatNumber color="yellow.500">{typeInfo.pending_entity_count}</StatNumber>
                </Stat>
                <Stat>
                  <StatLabel>Validées</StatLabel>
                  <StatNumber color="green.500">{typeInfo.validated_entity_count}</StatNumber>
                </Stat>
              </SimpleGrid>

              {typeInfo.description && (
                <>
                  <Divider my={4} />
                  <Text color="gray.600">{typeInfo.description}</Text>
                </>
              )}
            </CardBody>
          </Card>
        )}

        {/* Actions Bar */}
        <Flex justify="space-between" align="center" flexWrap="wrap" gap={4}>
          {/* Filters */}
          <HStack>
            <Text fontWeight="bold">Filtre:</Text>
            <Button
              size="sm"
              variant={statusFilter === 'all' ? 'solid' : 'outline'}
              colorScheme="blue"
              onClick={() => setStatusFilter('all')}
            >
              Tous ({entities.length})
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
              variant={statusFilter === 'validated' ? 'solid' : 'outline'}
              colorScheme="green"
              onClick={() => setStatusFilter('validated')}
            >
              Validées
            </Button>
          </HStack>

          {/* Bulk Actions */}
          <HStack>
            {selectedEntities.size > 0 && (
              <>
                <Badge colorScheme="blue" fontSize="md" px={2}>
                  {selectedEntities.size} sélectionnée(s)
                </Badge>
                <Button
                  size="sm"
                  colorScheme="green"
                  leftIcon={<FiCheckSquare />}
                  onClick={handleBulkApprove}
                >
                  Approuver sélection
                </Button>
              </>
            )}

            {typeInfo?.status === 'approved' && (
              <Button
                size="sm"
                colorScheme="purple"
                leftIcon={<FiCpu />}
                onClick={handleGenerateOntology}
              >
                🤖 Générer Ontologie
              </Button>
            )}
          </HStack>
        </Flex>

        {/* Empty State */}
        {!loading && entities.length === 0 && (
          <Alert status="info">
            <AlertIcon />
            Aucune entité trouvée pour ce filtre.
          </Alert>
        )}

        {/* Loading State */}
        {loading && (
          <Flex justify="center" py={8}>
            <Spinner size="lg" />
          </Flex>
        )}

        {/* Entities Table */}
        {!loading && entities.length > 0 && (
          <Card>
            <CardBody p={0}>
              <Table variant="simple">
                <Thead>
                  <Tr>
                    <Th width="50px">
                      <Checkbox
                        isChecked={selectedEntities.size === entities.length}
                        isIndeterminate={selectedEntities.size > 0 && selectedEntities.size < entities.length}
                        onChange={handleToggleAll}
                      />
                    </Th>
                    <Th>Nom</Th>
                    <Th>Status</Th>
                    <Th>Description</Th>
                    <Th>Confidence</Th>
                    <Th>Créée le</Th>
                    <Th>Actions</Th>
                  </Tr>
                </Thead>
                <Tbody>
                  {entities.map((entity) => (
                    <Tr key={entity.uuid} _hover={{ bg: 'gray.50' }}>
                      <Td>
                        <Checkbox
                          isChecked={selectedEntities.has(entity.uuid)}
                          onChange={() => handleToggleEntity(entity.uuid)}
                        />
                      </Td>
                      <Td fontWeight="bold">{entity.name}</Td>
                      <Td>
                        <Badge colorScheme={getStatusColor(entity.status)}>
                          {entity.status}
                        </Badge>
                      </Td>
                      <Td maxW="300px" isTruncated>
                        <Text fontSize="sm" color="gray.600">
                          {entity.description || '-'}
                        </Text>
                      </Td>
                      <Td>
                        {entity.confidence ? (
                          <Badge colorScheme={entity.confidence > 0.8 ? 'green' : 'orange'}>
                            {(entity.confidence * 100).toFixed(0)}%
                          </Badge>
                        ) : '-'}
                      </Td>
                      <Td fontSize="sm">
                        {new Date(entity.created_at).toLocaleDateString()}
                      </Td>
                      <Td>
                        {entity.status === 'pending' && (
                          <Button
                            size="xs"
                            colorScheme="green"
                            leftIcon={<FiCheckCircle />}
                            onClick={() => handleApproveEntity(entity.uuid)}
                          >
                            Approuver
                          </Button>
                        )}
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
