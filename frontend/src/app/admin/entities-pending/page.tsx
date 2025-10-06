/**
 * Page Admin - Entités Pending (non cataloguées)
 *
 * Phase 4 - Frontend UI (Chakra UI)
 *
 * Liste les entités avec status=pending pour validation admin.
 */

'use client';

import { useState, useEffect } from 'react';
import {
  Box,
  Container,
  Heading,
  Text,
  Card,
  CardHeader,
  CardBody,
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
  Select,
  useToast,
  Stat,
  StatLabel,
  StatNumber,
  SimpleGrid,
} from "@chakra-ui/react";
import {
  FiCheckCircle,
  FiClock,
  FiFilter,
} from "react-icons/fi";

interface PendingEntity {
  uuid: string;
  name: string;
  entity_type: string;
  description?: string;
  source_document?: string;
  created_at: string;
  confidence: number;
}

export default function EntitiesPendingPage() {
  const [entities, setEntities] = useState<PendingEntity[]>([]);
  const [loading, setLoading] = useState(true);
  const [typeFilter, setTypeFilter] = useState<string>('');
  const [availableTypes, setAvailableTypes] = useState<string[]>([]);
  const toast = useToast();

  useEffect(() => {
    fetchAvailableTypes();
    fetchEntities();
  }, []);

  useEffect(() => {
    fetchEntities();
  }, [typeFilter]);

  const fetchAvailableTypes = async () => {
    try {
      const response = await fetch('/api/entity-types?status=all');
      const data = await response.json();
      const types = data.types.map((t: any) => t.type_name);
      setAvailableTypes(types);
    } catch (error) {
      console.error('Error fetching types:', error);
    }
  };

  const fetchEntities = async () => {
    setLoading(true);
    try {
      const url = typeFilter
        ? `/api/entities/pending?entity_type=${typeFilter}&limit=100`
        : '/api/entities/pending?limit=100';

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

  const handleApprove = async (entity: PendingEntity) => {
    try {
      const response = await fetch(`/api/entities/${entity.uuid}/approve`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Admin-Key': 'admin-dev-key-change-in-production',
          'X-Tenant-ID': 'default'
        },
        body: JSON.stringify({
          admin_email: 'admin@example.com',
          add_to_ontology: false
        })
      });

      if (response.ok) {
        toast({
          title: 'Entité approuvée',
          description: `"${entity.name}" a été approuvée`,
          status: 'success',
          duration: 2000,
        });
        fetchEntities();
      } else {
        const error = await response.json();
        throw new Error(error.detail);
      }
    } catch (error: any) {
      toast({
        title: 'Erreur',
        description: error.message,
        status: 'error',
        duration: 3000,
      });
    }
  };

  const handleReject = async (entity: PendingEntity) => {
    try {
      const response = await fetch(`/api/entities/${entity.uuid}`, {
        method: 'DELETE',
        headers: {
          'X-Admin-Key': 'admin-dev-key-change-in-production'
        }
      });

      if (response.ok) {
        toast({
          title: 'Entité supprimée',
          status: 'info',
          duration: 2000,
        });
        fetchEntities();
      } else {
        throw new Error('Deletion failed');
      }
    } catch (error) {
      toast({
        title: 'Erreur',
        description: 'Erreur lors de la suppression',
        status: 'error',
        duration: 3000,
      });
    }
  };

  const getConfidenceColor = (confidence: number) => {
    if (confidence >= 0.8) return 'green';
    if (confidence >= 0.6) return 'orange';
    return 'red';
  };

  // Group by type for stats
  const entityCountByType = entities.reduce((acc, entity) => {
    acc[entity.entity_type] = (acc[entity.entity_type] || 0) + 1;
    return acc;
  }, {} as Record<string, number>);

  if (loading && entities.length === 0) {
    return (
      <Container maxW="container.xl" py={8}>
        <VStack spacing={4}>
          <Spinner size="xl" />
          <Text>Chargement des entités...</Text>
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
            <Icon as={FiClock} mr={3} />
            Entités en Attente
          </Heading>
          <Badge colorScheme="yellow" fontSize="lg" px={3} py={1}>
            {entities.length} entité(s)
          </Badge>
        </Flex>

        {/* Stats by Type */}
        {Object.keys(entityCountByType).length > 0 && (
          <SimpleGrid columns={{ base: 2, md: 4, lg: 6 }} spacing={4}>
            {Object.entries(entityCountByType).map(([type, count]) => (
              <Card key={type} size="sm">
                <CardBody>
                  <Stat>
                    <StatLabel fontSize="xs">{type}</StatLabel>
                    <StatNumber fontSize="lg">{count}</StatNumber>
                  </Stat>
                </CardBody>
              </Card>
            ))}
          </SimpleGrid>
        )}

        {/* Filters */}
        <Card>
          <CardHeader>
            <Heading size="sm">
              <Icon as={FiFilter} mr={2} />
              Filtres
            </Heading>
          </CardHeader>
          <CardBody>
            <HStack>
              <Text fontWeight="bold">Type:</Text>
              <Select
                placeholder="Tous les types"
                value={typeFilter}
                onChange={(e) => setTypeFilter(e.target.value)}
                maxW="300px"
              >
                {availableTypes.map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </Select>
              {typeFilter && (
                <Button size="sm" onClick={() => setTypeFilter('')}>
                  Réinitialiser
                </Button>
              )}
            </HStack>
          </CardBody>
        </Card>

        {/* Empty State */}
        {!loading && entities.length === 0 && (
          <Alert status="success">
            <AlertIcon />
            Aucune entité en attente ! Toutes les entités ont été validées.
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
                    <Th>Nom</Th>
                    <Th>Type</Th>
                    <Th>Description</Th>
                    <Th>Confidence</Th>
                    <Th>Source</Th>
                    <Th>Créée le</Th>
                    <Th>Actions</Th>
                  </Tr>
                </Thead>
                <Tbody>
                  {entities.map((entity) => (
                    <Tr key={entity.uuid} _hover={{ bg: 'gray.50' }}>
                      <Td fontWeight="bold">{entity.name}</Td>
                      <Td>
                        <Badge colorScheme="blue">{entity.entity_type}</Badge>
                      </Td>
                      <Td maxW="300px" isTruncated>
                        <Text fontSize="sm" color="gray.600">
                          {entity.description || '-'}
                        </Text>
                      </Td>
                      <Td>
                        <Badge colorScheme={getConfidenceColor(entity.confidence)}>
                          {(entity.confidence * 100).toFixed(0)}%
                        </Badge>
                      </Td>
                      <Td fontSize="sm" maxW="200px" isTruncated>
                        {entity.source_document || '-'}
                      </Td>
                      <Td fontSize="sm">
                        {new Date(entity.created_at).toLocaleDateString()}
                      </Td>
                      <Td>
                        <HStack spacing={2}>
                          <Button
                            size="xs"
                            colorScheme="green"
                            leftIcon={<FiCheckCircle />}
                            onClick={() => handleApprove(entity)}
                          >
                            Valider
                          </Button>
                          <Button
                            size="xs"
                            colorScheme="red"
                            variant="outline"
                            onClick={() => handleReject(entity)}
                          >
                            Rejeter
                          </Button>
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
