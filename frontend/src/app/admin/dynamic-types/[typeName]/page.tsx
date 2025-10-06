/**
 * Page Drill-Down - Entités d'un Type Spécifique avec Normalisation
 *
 * Phase 5B - Solution 3 Hybride - Normalisation LLM
 *
 * Workflow:
 * 1. Liste entités pending
 * 2. Bouton "Générer propositions" → LLM propose noms canoniques
 * 3. Admin review + édition manuelle
 * 4. Validation par groupe → Merge entités similaires
 */

'use client';

import { useState, useEffect } from 'react';
import { useParams } from 'next/navigation';
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
  Input,
  Tabs,
  TabList,
  TabPanels,
  Tab,
  TabPanel,
  Accordion,
  AccordionItem,
  AccordionButton,
  AccordionPanel,
  AccordionIcon,
} from "@chakra-ui/react";
import {
  FiLayers,
  FiCheckCircle,
  FiArrowLeft,
  FiCheckSquare,
  FiCpu,
  FiEdit2,
  FiSave,
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

interface OntologyProposal {
  canonical_key: string;
  canonical_name: string;
  entities: Array<{
    uuid: string;
    name: string;
    score: number;
    auto_match: boolean;
    selected: boolean;
  }>;
  master_uuid: string;
}

export default function TypeEntitiesPage() {
  const params = useParams();
  const typeName = params.typeName as string;
  const toast = useToast();

  const [entities, setEntities] = useState<Entity[]>([]);
  const [typeInfo, setTypeInfo] = useState<TypeInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<string>('pending');
  const [selectedEntities, setSelectedEntities] = useState<Set<string>>(new Set());

  // Normalisation workflow
  const [showNormalization, setShowNormalization] = useState(false);
  const [generatingOntology, setGeneratingOntology] = useState(false);
  const [ontologyProposals, setOntologyProposals] = useState<OntologyProposal[]>([]);
  const [editingCanonical, setEditingCanonical] = useState<Record<string, string>>({});

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

    setGeneratingOntology(true);

    try {
      // Step 1: Lancer génération ontologie
      const response = await fetch(`/api/entity-types/${typeName}/generate-ontology`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Admin-Key': 'admin-dev-key-change-in-production'
        },
        body: JSON.stringify({ model_preference: 'claude-sonnet' })
      });

      if (!response.ok) {
        throw new Error('Generation failed');
      }

      const result = await response.json();
      const jobId = result.job_id;

      toast({
        title: 'Génération démarrée',
        description: `Job ID: ${jobId}. Attente résultat...`,
        status: 'info',
        duration: 3000,
      });

      // Step 2: Polling job status
      let attempts = 0;
      const maxAttempts = 60; // 60 * 2s = 2 minutes max

      const pollJobStatus = async () => {
        try {
          const statusResponse = await fetch(`/api/jobs/${jobId}/status`);
          const statusData = await statusResponse.json();

          if (statusData.status === 'finished') {
            // Step 3: Récupérer ontologie générée
            const ontologyResponse = await fetch(`/api/entity-types/${typeName}/ontology-proposal`);
            const ontologyData = await ontologyResponse.json();

            // Step 4: Calculer preview normalisation
            const previewResponse = await fetch(`/api/entity-types/${typeName}/preview-normalization`, {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'X-Admin-Key': 'admin-dev-key-change-in-production'
              },
              body: JSON.stringify({ ontology: ontologyData.ontology })
            });

            const previewData = await previewResponse.json();
            setOntologyProposals(previewData.merge_groups || []);
            setShowNormalization(true);
            setGeneratingOntology(false);

            toast({
              title: 'Ontologie générée',
              description: `${previewData.summary.groups_proposed} groupes proposés`,
              status: 'success',
              duration: 3000,
            });

          } else if (statusData.status === 'failed') {
            throw new Error('Job failed');
          } else if (attempts < maxAttempts) {
            attempts++;
            setTimeout(pollJobStatus, 2000);
          } else {
            throw new Error('Timeout');
          }
        } catch (error) {
          console.error('Polling error:', error);
          setGeneratingOntology(false);
          toast({
            title: 'Erreur',
            description: 'Impossible de récupérer le résultat',
            status: 'error',
            duration: 3000,
          });
        }
      };

      await pollJobStatus();

    } catch (error) {
      setGeneratingOntology(false);
      toast({
        title: 'Erreur',
        description: 'Erreur lors de la génération',
        status: 'error',
        duration: 3000,
      });
    }
  };

  const handleEditCanonical = (canonicalKey: string, newValue: string) => {
    setEditingCanonical(prev => ({ ...prev, [canonicalKey]: newValue }));
  };

  const handleSaveCanonical = (canonicalKey: string) => {
    const newName = editingCanonical[canonicalKey];
    if (!newName) return;

    setOntologyProposals(prev =>
      prev.map(group =>
        group.canonical_key === canonicalKey
          ? { ...group, canonical_name: newName }
          : group
      )
    );

    setEditingCanonical(prev => {
      const updated = { ...prev };
      delete updated[canonicalKey];
      return updated;
    });

    toast({
      title: 'Nom canonique modifié',
      status: 'success',
      duration: 2000,
    });
  };

  const handleToggleEntityInGroup = (canonicalKey: string, entityUuid: string) => {
    setOntologyProposals(prev =>
      prev.map(group =>
        group.canonical_key === canonicalKey
          ? {
              ...group,
              entities: group.entities.map(e =>
                e.uuid === entityUuid ? { ...e, selected: !e.selected } : e
              )
            }
          : group
      )
    );
  };

  const handleValidateNormalization = async () => {
    // Filtrer uniquement les groupes avec au moins 2 entités sélectionnées
    const validGroups = ontologyProposals
      .filter(group => group.entities.filter(e => e.selected).length >= 2)
      .map(group => ({
        canonical_key: group.canonical_key,
        canonical_name: group.canonical_name,
        master_uuid: group.master_uuid,
        entities: group.entities.filter(e => e.selected)
      }));

    if (validGroups.length === 0) {
      toast({
        title: 'Aucun merge',
        description: 'Sélectionnez au moins 2 entités par groupe',
        status: 'warning',
        duration: 3000,
      });
      return;
    }

    try {
      const response = await fetch(`/api/entity-types/${typeName}/normalize-entities`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Admin-Key': 'admin-dev-key-change-in-production'
        },
        body: JSON.stringify({
          merge_groups: validGroups,
          create_snapshot: true
        })
      });

      if (!response.ok) {
        throw new Error('Normalization failed');
      }

      const result = await response.json();

      toast({
        title: 'Normalisation lancée',
        description: `Job ID: ${result.job_id}`,
        status: 'success',
        duration: 5000,
      });

      // Reset et reload
      setShowNormalization(false);
      setOntologyProposals([]);
      fetchEntities();
      fetchTypeInfo();

    } catch (error) {
      toast({
        title: 'Erreur',
        description: 'Erreur lors de la normalisation',
        status: 'error',
        duration: 3000,
      });
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

        {/* Tabs: Liste simple vs Normalisation */}
        <Tabs index={showNormalization ? 1 : 0}>
          <TabList>
            <Tab onClick={() => setShowNormalization(false)}>📋 Liste des entités</Tab>
            <Tab onClick={() => setShowNormalization(true)} isDisabled={ontologyProposals.length === 0}>
              🤖 Normalisation ({ontologyProposals.length} groupes)
            </Tab>
          </TabList>

          <TabPanels>
            {/* TAB 1: Liste simple */}
            <TabPanel>
              <VStack spacing={4} align="stretch">
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
                      Tous
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

                  {/* Actions */}
                  <HStack>
                    {typeInfo?.status === 'approved' && typeInfo.pending_entity_count > 0 && (
                      <Button
                        colorScheme="purple"
                        leftIcon={<FiCpu />}
                        onClick={handleGenerateOntology}
                        isLoading={generatingOntology}
                        loadingText="Génération..."
                      >
                        🤖 Générer propositions canoniques
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
            </TabPanel>

            {/* TAB 2: Normalisation */}
            <TabPanel>
              <VStack spacing={4} align="stretch">
                <Alert status="info">
                  <AlertIcon />
                  <Box>
                    <Text fontWeight="bold">Normalisation LLM</Text>
                    <Text fontSize="sm">
                      Le LLM a proposé {ontologyProposals.length} groupes de noms canoniques.
                      Éditez les propositions si nécessaire, sélectionnez les entités à merger, puis validez.
                    </Text>
                  </Box>
                </Alert>

                <Accordion allowMultiple>
                  {ontologyProposals.map((group, idx) => {
                    const selectedCount = group.entities.filter(e => e.selected).length;
                    const isEditing = editingCanonical[group.canonical_key] !== undefined;

                    return (
                      <AccordionItem key={group.canonical_key} borderWidth={2} mb={2}>
                        <h2>
                          <AccordionButton>
                            <Box flex="1" textAlign="left">
                              <HStack>
                                <Badge colorScheme="purple" fontSize="md">
                                  Groupe {idx + 1}
                                </Badge>
                                <Text fontWeight="bold" fontSize="lg">
                                  {group.canonical_name}
                                </Text>
                                <Badge colorScheme="blue">
                                  {selectedCount}/{group.entities.length} sélectionnées
                                </Badge>
                              </HStack>
                            </Box>
                            <AccordionIcon />
                          </AccordionButton>
                        </h2>
                        <AccordionPanel pb={4}>
                          <VStack spacing={4} align="stretch">
                            {/* Édition nom canonique */}
                            <HStack>
                              <Text fontWeight="bold" minW="150px">Nom canonique:</Text>
                              {isEditing ? (
                                <>
                                  <Input
                                    value={editingCanonical[group.canonical_key]}
                                    onChange={(e) => handleEditCanonical(group.canonical_key, e.target.value)}
                                    size="sm"
                                  />
                                  <Button
                                    size="sm"
                                    colorScheme="green"
                                    leftIcon={<FiSave />}
                                    onClick={() => handleSaveCanonical(group.canonical_key)}
                                  >
                                    Sauver
                                  </Button>
                                </>
                              ) : (
                                <>
                                  <Text>{group.canonical_name}</Text>
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    leftIcon={<FiEdit2 />}
                                    onClick={() => handleEditCanonical(group.canonical_key, group.canonical_name)}
                                  >
                                    Modifier
                                  </Button>
                                </>
                              )}
                            </HStack>

                            <Divider />

                            {/* Liste entités du groupe */}
                            <Table size="sm" variant="simple">
                              <Thead>
                                <Tr>
                                  <Th width="50px">Merger</Th>
                                  <Th>Nom actuel</Th>
                                  <Th>Score</Th>
                                  <Th>Auto-match</Th>
                                </Tr>
                              </Thead>
                              <Tbody>
                                {group.entities.map((entity) => (
                                  <Tr key={entity.uuid} bg={entity.selected ? 'blue.50' : 'white'}>
                                    <Td>
                                      <Checkbox
                                        isChecked={entity.selected}
                                        onChange={() => handleToggleEntityInGroup(group.canonical_key, entity.uuid)}
                                      />
                                    </Td>
                                    <Td fontWeight={entity.uuid === group.master_uuid ? 'bold' : 'normal'}>
                                      {entity.name}
                                      {entity.uuid === group.master_uuid && (
                                        <Badge ml={2} colorScheme="green">Master</Badge>
                                      )}
                                    </Td>
                                    <Td>
                                      <Badge colorScheme={entity.score >= 90 ? 'green' : 'orange'}>
                                        {entity.score}%
                                      </Badge>
                                    </Td>
                                    <Td>
                                      {entity.auto_match ? (
                                        <Badge colorScheme="green">✓ Auto</Badge>
                                      ) : (
                                        <Badge colorScheme="orange">⚠️ Manuel</Badge>
                                      )}
                                    </Td>
                                  </Tr>
                                ))}
                              </Tbody>
                            </Table>
                          </VStack>
                        </AccordionPanel>
                      </AccordionItem>
                    );
                  })}
                </Accordion>

                {/* Validation finale */}
                <Flex justify="flex-end" gap={4}>
                  <Button
                    variant="outline"
                    onClick={() => {
                      setShowNormalization(false);
                      setOntologyProposals([]);
                    }}
                  >
                    Annuler
                  </Button>
                  <Button
                    colorScheme="green"
                    leftIcon={<FiCheckSquare />}
                    onClick={handleValidateNormalization}
                  >
                    Valider la normalisation
                  </Button>
                </Flex>
              </VStack>
            </TabPanel>
          </TabPanels>
        </Tabs>
      </VStack>
    </Container>
  );
}
