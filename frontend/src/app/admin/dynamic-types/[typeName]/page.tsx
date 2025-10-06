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
  Modal,
  ModalOverlay,
  ModalContent,
  ModalHeader,
  ModalBody,
  ModalFooter,
  ModalCloseButton,
  useDisclosure,
  Select,
} from "@chakra-ui/react";
import {
  FiLayers,
  FiCheckCircle,
  FiArrowLeft,
  FiCheckSquare,
  FiCpu,
  FiEdit2,
  FiSave,
  FiClock,
  FiGitMerge,
} from "react-icons/fi";

interface Entity {
  uuid: string;
  name: string;
  entity_type: string;
  status: string;
  canonical_name?: string;  // Nom canonique après normalisation
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

  // Job de normalisation en cours
  const [normalizationJobId, setNormalizationJobId] = useState<string | null>(null);
  const [normalizationStatus, setNormalizationStatus] = useState<'running' | 'completed' | 'failed' | null>(null);

  // Modal changement de type
  const { isOpen: isChangeTypeOpen, onOpen: onChangeTypeOpen, onClose: onChangeTypeClose } = useDisclosure();
  const [entityToChangeType, setEntityToChangeType] = useState<Entity | null>(null);
  const [newEntityType, setNewEntityType] = useState<string>('');
  const [availableTypes, setAvailableTypes] = useState<string[]>([]);

  // Option normalisation : inclure entités validées
  const [includeValidated, setIncludeValidated] = useState(false);

  // Snapshots pour rollback
  const [snapshots, setSnapshots] = useState<any[]>([]);
  const [loadingSnapshots, setLoadingSnapshots] = useState(false);
  const [showSnapshots, setShowSnapshots] = useState(false);

  // Modal merge types
  const { isOpen: isMergeTypeOpen, onOpen: onMergeTypeOpen, onClose: onMergeTypeClose } = useDisclosure();
  const [targetMergeType, setTargetMergeType] = useState<string>('');

  useEffect(() => {
    fetchTypeInfo();
    fetchEntities();
    fetchAvailableTypes();
    fetchSnapshots();
  }, [typeName, statusFilter]);

  const fetchAvailableTypes = async () => {
    try {
      const response = await fetch('/api/entity-types');
      if (response.ok) {
        const data = await response.json();
        const types = data.types.map((t: any) => t.type_name);
        setAvailableTypes(types);
      }
    } catch (error) {
      console.error('Error fetching types:', error);
    }
  };

  const fetchSnapshots = async () => {
    if (showSnapshots) {
      // Si déjà affiché, on masque
      setShowSnapshots(false);
      return;
    }

    // Sinon on charge et affiche
    setLoadingSnapshots(true);
    try {
      const response = await fetch(`/api/entity-types/${typeName}/snapshots`);
      if (response.ok) {
        const data = await response.json();
        setSnapshots(data.snapshots || []);
        setShowSnapshots(true);
      }
    } catch (error) {
      console.error('Error fetching snapshots:', error);
    } finally {
      setLoadingSnapshots(false);
    }
  };

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
      const response = await fetch(`/api/entity-types/${typeName}/generate-ontology?include_validated=${includeValidated}`, {
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

  const handleExtractEntity = (canonicalKey: string, entityUuid: string) => {
    setOntologyProposals(prev => {
      // Trouver l'entité à extraire
      const sourceGroup = prev.find(g => g.canonical_key === canonicalKey);
      const entityToExtract = sourceGroup?.entities.find(e => e.uuid === entityUuid);

      if (!entityToExtract) return prev;

      // Créer nouveau groupe avec cette entité seule
      const newGroup = {
        canonical_key: `${entityToExtract.name.replace(/\s+/g, '_').replace(/[\/\\]/g, '_').toUpperCase()}_SOLO`,
        canonical_name: entityToExtract.name, // Garde son nom actuel
        description: entityToExtract.description || '',
        confidence: 1.0,
        entities: [{
          ...entityToExtract,
          score: 100,
          auto_match: true,
          selected: true,
          matched_via: 'extracted'
        }],
        master_uuid: entityUuid
      };

      // Retirer l'entité du groupe source et ajouter le nouveau groupe
      return [
        ...prev.map(group =>
          group.canonical_key === canonicalKey
            ? {
                ...group,
                entities: group.entities.filter(e => e.uuid !== entityUuid),
                // Si c'était le master, choisir un nouveau master
                master_uuid: group.master_uuid === entityUuid && group.entities.length > 1
                  ? group.entities.find(e => e.uuid !== entityUuid)!.uuid
                  : group.master_uuid
              }
            : group
        ).filter(group => group.entities.length > 0), // Supprimer groupes vides
        newGroup
      ];
    });

    toast({
      title: 'Entité extraite',
      description: 'L\'entité a été extraite dans un nouveau groupe individuel',
      status: 'success',
      duration: 3000,
    });
  };

  const handleValidateNormalization = async () => {
    // Filtrer uniquement les groupes avec au moins 1 entité sélectionnée
    // Les groupes vides (0 sélection) sont ignorés = pas de normalisation pour ce groupe
    const validGroups = ontologyProposals
      .filter(group => group.entities.filter(e => e.selected).length >= 1)
      .map(group => ({
        canonical_key: group.canonical_key,
        canonical_name: group.canonical_name,
        master_uuid: group.master_uuid,
        entities: group.entities.filter(e => e.selected)
      }));

    // Si TOUS les groupes sont vides, afficher avertissement
    if (validGroups.length === 0) {
      toast({
        title: 'Aucun groupe sélectionné',
        description: 'Vous avez désélectionné toutes les entités. Aucune normalisation ne sera effectuée.',
        status: 'info',
        duration: 4000,
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

      // Démarrer le polling du job
      setNormalizationJobId(result.job_id);
      setNormalizationStatus('running');
      setShowNormalization(false);
      setOntologyProposals([]);

      toast({
        title: 'Normalisation lancée',
        description: `Job en cours d'exécution...`,
        status: 'info',
        duration: 3000,
      });

      // Démarrer le polling
      pollNormalizationJob(result.job_id);
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

  const pollNormalizationJob = async (jobId: string) => {
    let attempts = 0;
    const maxAttempts = 90; // 90 * 2s = 3 minutes max

    const poll = async () => {
      try {
        const response = await fetch(`/api/jobs/${jobId}/status`);
        const data = await response.json();

        if (data.status === 'finished') {
          setNormalizationStatus('completed');
          setNormalizationJobId(null);

          toast({
            title: 'Normalisation terminée',
            description: `${data.result?.entities_merged || 0} entités mergées`,
            status: 'success',
            duration: 5000,
          });

          // Reload entities et type info
          fetchEntities();
          fetchTypeInfo();

        } else if (data.status === 'failed') {
          setNormalizationStatus('failed');
          setNormalizationJobId(null);

          toast({
            title: 'Normalisation échouée',
            description: 'Une erreur est survenue',
            status: 'error',
            duration: 5000,
          });

        } else if (attempts < maxAttempts) {
          attempts++;
          setTimeout(poll, 2000); // Retry après 2s
        } else {
          setNormalizationStatus('failed');
          setNormalizationJobId(null);

          toast({
            title: 'Timeout',
            description: 'Le job prend trop de temps',
            status: 'warning',
            duration: 5000,
          });
        }
      } catch (error) {
        console.error('Job polling error:', error);
        setTimeout(poll, 2000);
      }
    };

    poll();
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

  const handleOpenChangeType = (entity: Entity) => {
    setEntityToChangeType(entity);
    setNewEntityType('');
    onChangeTypeOpen();
  };

  const handleChangeTypeSubmit = async () => {
    if (!entityToChangeType || !newEntityType) return;

    try {
      const response = await fetch(`/api/entities/${entityToChangeType.uuid}/change-type`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          'X-Admin-Key': 'admin-dev-key-change-in-production'
        },
        body: JSON.stringify({ new_entity_type: newEntityType })
      });

      if (response.ok) {
        toast({
          title: 'Type changé',
          description: `L'entité a été déplacée vers ${newEntityType}`,
          status: 'success',
          duration: 3000,
        });
        onChangeTypeClose();
        fetchEntities();
        fetchTypeInfo();
      } else {
        throw new Error('Change type failed');
      }
    } catch (error) {
      toast({
        title: 'Erreur',
        description: 'Erreur lors du changement de type',
        status: 'error',
        duration: 3000,
      });
    }
  };

  const handleRollback = async (snapshotId: string) => {
    try {
      const response = await fetch(`/api/entity-types/${typeName}/undo-normalization`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Admin-Key': 'admin-dev-key-change-in-production'
        },
        body: JSON.stringify({ snapshot_id: snapshotId })
      });

      if (response.ok) {
        const data = await response.json();
        toast({
          title: 'Rollback lancé',
          description: `Job ${data.job_id} en cours...`,
          status: 'info',
          duration: 3000,
        });
        // Rafraîchir après quelques secondes
        setTimeout(() => {
          fetchEntities();
          fetchTypeInfo();
          fetchSnapshots();
        }, 3000);
      } else {
        throw new Error('Rollback failed');
      }
    } catch (error) {
      toast({
        title: 'Erreur rollback',
        description: 'Impossible d\'annuler la normalisation',
        status: 'error',
        duration: 3000,
      });
    }
  };

  const handleMergeTypes = async () => {
    if (!targetMergeType) return;

    try {
      const response = await fetch(`/api/entity-types/${typeName}/merge-into/${targetMergeType}`, {
        method: 'POST',
        headers: {
          'X-Admin-Key': 'admin-dev-key-change-in-production'
        }
      });

      if (response.ok) {
        const data = await response.json();
        toast({
          title: 'Types fusionnés',
          description: `${data.entities_transferred} entités transférées vers ${targetMergeType}`,
          status: 'success',
          duration: 4000,
        });
        onMergeTypeClose();
        // Rediriger vers le type cible
        window.location.href = `/admin/dynamic-types/${targetMergeType}`;
      } else {
        throw new Error('Merge failed');
      }
    } catch (error) {
      toast({
        title: 'Erreur fusion',
        description: 'Impossible de fusionner les types',
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

        {/* Indicateur Job de Normalisation */}
        {normalizationJobId && normalizationStatus === 'running' && (
          <Alert status="info" variant="left-accent">
            <AlertIcon as={Spinner} />
            <VStack align="start" spacing={1} flex="1">
              <Text fontWeight="bold">Normalisation en cours...</Text>
              <Text fontSize="sm">Job ID: {normalizationJobId}</Text>
            </VStack>
          </Alert>
        )}

        {normalizationStatus === 'completed' && (
          <Alert status="success" variant="left-accent">
            <AlertIcon />
            <Text fontWeight="bold">Normalisation terminée avec succès !</Text>
          </Alert>
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
                  <HStack spacing={4}>
                    {typeInfo?.status === 'approved' && typeInfo.pending_entity_count > 0 && (
                      <>
                        <Checkbox
                          isChecked={includeValidated}
                          onChange={(e) => setIncludeValidated(e.target.checked)}
                          colorScheme="orange"
                        >
                          <Text fontSize="sm" color={includeValidated ? "orange.600" : "gray.600"}>
                            Inclure entités validées
                            {includeValidated && " ⚠️"}
                          </Text>
                        </Checkbox>
                        <Button
                          colorScheme="purple"
                          leftIcon={<FiCpu />}
                          onClick={handleGenerateOntology}
                          isLoading={generatingOntology}
                          loadingText="Génération..."
                        >
                          🤖 Générer propositions canoniques
                        </Button>
                      </>
                    )}
                    <Button
                      colorScheme="teal"
                      variant="outline"
                      leftIcon={<Icon as={FiClock} />}
                      onClick={fetchSnapshots}
                      isLoading={loadingSnapshots}
                    >
                      Rollback
                    </Button>
                    <Button
                      colorScheme="orange"
                      variant="outline"
                      leftIcon={<Icon as={FiGitMerge} />}
                      onClick={onMergeTypeOpen}
                    >
                      Fusionner type
                    </Button>
                  </HStack>
                </Flex>

                {/* Snapshots Section */}
                {showSnapshots && snapshots.length > 0 && (
                  <Card borderWidth={1} borderColor="teal.200">
                    <CardHeader>
                      <HStack>
                        <Icon as={FiClock} color="teal.500" />
                        <Heading size="sm">Snapshots disponibles pour rollback</Heading>
                      </HStack>
                    </CardHeader>
                    <CardBody>
                      <VStack align="stretch" spacing={3}>
                        {snapshots.map((snapshot) => (
                          <Flex
                            key={snapshot.snapshot_id}
                            justify="space-between"
                            align="center"
                            p={3}
                            borderWidth={1}
                            borderRadius="md"
                            bg={snapshot.is_expired ? "gray.50" : "white"}
                          >
                            <VStack align="start" spacing={1}>
                              <Text fontWeight="bold" fontSize="sm">
                                {new Date(snapshot.created_at).toLocaleString('fr-FR')}
                              </Text>
                              <Text fontSize="xs" color="gray.600">
                                {snapshot.entities_count} entités • Expire: {new Date(snapshot.expires_at).toLocaleString('fr-FR')}
                              </Text>
                              {snapshot.restored && (
                                <Badge colorScheme="green" fontSize="xs">Déjà restauré</Badge>
                              )}
                              {snapshot.is_expired && (
                                <Badge colorScheme="red" fontSize="xs">Expiré</Badge>
                              )}
                            </VStack>
                            <Button
                              size="sm"
                              colorScheme="teal"
                              onClick={() => handleRollback(snapshot.snapshot_id)}
                              isDisabled={snapshot.is_expired || snapshot.restored || !snapshot.can_rollback}
                            >
                              Restaurer
                            </Button>
                          </Flex>
                        ))}
                      </VStack>
                    </CardBody>
                  </Card>
                )}

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
                            <Th maxW="200px">Nom canonique</Th>
                            <Th>Status</Th>
                            <Th>Description</Th>
                            <Th>Créée le</Th>
                            <Th>Actions</Th>
                          </Tr>
                        </Thead>
                        <Tbody>
                          {entities.map((entity) => (
                            <Tr key={entity.uuid} _hover={{ bg: 'gray.50' }}>
                              <Td fontWeight="bold">{entity.name}</Td>
                              <Td maxW="200px">
                                {entity.canonical_name ? (
                                  <Badge colorScheme="purple" variant="subtle" whiteSpace="normal" wordBreak="break-word">
                                    {entity.canonical_name}
                                  </Badge>
                                ) : (
                                  <Text fontSize="sm" color="gray.400">-</Text>
                                )}
                              </Td>
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
                              <Td fontSize="sm" whiteSpace="nowrap">
                                {new Date(entity.created_at).toLocaleDateString('fr-FR')}
                              </Td>
                              <Td>
                                <HStack spacing={2}>
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
                                  <Button
                                    size="xs"
                                    colorScheme="blue"
                                    variant="outline"
                                    leftIcon={<FiEdit2 />}
                                    onClick={() => handleOpenChangeType(entity)}
                                  >
                                    Changer type
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
                                  <Th width="120px">Actions</Th>
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
                                    <Td>
                                      <Button
                                        size="sm"
                                        colorScheme="purple"
                                        variant="outline"
                                        onClick={() => handleExtractEntity(group.canonical_key, entity.uuid)}
                                        title="Extraire cette entité dans un groupe séparé"
                                      >
                                        Extraire
                                      </Button>
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

      {/* Modal Changement de Type */}
      <Modal isOpen={isChangeTypeOpen} onClose={onChangeTypeClose}>
        <ModalOverlay />
        <ModalContent>
          <ModalHeader>Changer le type de l'entité</ModalHeader>
          <ModalCloseButton />
          <ModalBody>
            <VStack spacing={4} align="stretch">
              <Box>
                <Text fontWeight="bold" mb={2}>Entité :</Text>
                <Text>{entityToChangeType?.name}</Text>
                <Badge colorScheme="blue" mt={1}>
                  Type actuel : {entityToChangeType?.entity_type}
                </Badge>
              </Box>

              <Box>
                <Text fontWeight="bold" mb={2}>Nouveau type :</Text>
                <Select
                  placeholder="Sélectionnez un type"
                  value={newEntityType}
                  onChange={(e) => setNewEntityType(e.target.value)}
                >
                  {availableTypes
                    .filter(t => t !== entityToChangeType?.entity_type)
                    .map(type => (
                      <option key={type} value={type}>{type}</option>
                    ))
                  }
                </Select>
              </Box>

              <Alert status="info" variant="left-accent">
                <AlertIcon />
                <Text fontSize="sm">
                  L'entité sera déplacée vers le type sélectionné.
                  Vous pourrez ensuite la normaliser avec les autres entités de ce type.
                </Text>
              </Alert>
            </VStack>
          </ModalBody>

          <ModalFooter>
            <Button variant="ghost" mr={3} onClick={onChangeTypeClose}>
              Annuler
            </Button>
            <Button
              colorScheme="blue"
              onClick={handleChangeTypeSubmit}
              isDisabled={!newEntityType}
            >
              Changer le type
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>

      {/* Modal Merge Types */}
      <Modal isOpen={isMergeTypeOpen} onClose={onMergeTypeClose} size="lg">
        <ModalOverlay />
        <ModalContent>
          <ModalHeader>Fusionner ce type dans un autre</ModalHeader>
          <ModalCloseButton />
          <ModalBody>
            <VStack spacing={4} align="stretch">
              <Alert status="warning" variant="left-accent">
                <AlertIcon />
                <VStack align="start" spacing={1}>
                  <Text fontWeight="bold" fontSize="sm">⚠️ Attention : Action définitive</Text>
                  <Text fontSize="xs">
                    Toutes les entités de <Badge colorScheme="orange">{typeName}</Badge> seront transférées vers le type cible.
                    Le type <Badge colorScheme="orange">{typeName}</Badge> sera supprimé du registre.
                  </Text>
                </VStack>
              </Alert>

              <Box>
                <Text fontWeight="bold" mb={2}>Type source (sera supprimé) :</Text>
                <Badge colorScheme="red" fontSize="md" px={3} py={1}>
                  {typeName}
                </Badge>
                <Text fontSize="sm" color="gray.600" mt={1}>
                  {typeInfo?.entity_count} entités à transférer
                </Text>
              </Box>

              <Box>
                <Text fontWeight="bold" mb={2}>Type cible (recevra toutes les entités) :</Text>
                <Select
                  placeholder="Sélectionnez le type cible"
                  value={targetMergeType}
                  onChange={(e) => setTargetMergeType(e.target.value)}
                  size="md"
                >
                  {availableTypes
                    .filter(t => t !== typeName)
                    .map(type => (
                      <option key={type} value={type}>{type}</option>
                    ))
                  }
                </Select>
              </Box>

              <Alert status="info" variant="left-accent">
                <AlertIcon />
                <Text fontSize="sm">
                  Un snapshot sera créé pour permettre le rollback (TTL 24h).
                  Après la fusion, vous pourrez normaliser les entités transférées.
                </Text>
              </Alert>
            </VStack>
          </ModalBody>

          <ModalFooter>
            <Button variant="ghost" mr={3} onClick={onMergeTypeClose}>
              Annuler
            </Button>
            <Button
              colorScheme="orange"
              onClick={handleMergeTypes}
              isDisabled={!targetMergeType}
            >
              Fusionner les types
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
    </Container>
  );
}
