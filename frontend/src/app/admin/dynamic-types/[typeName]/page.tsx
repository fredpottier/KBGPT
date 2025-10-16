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
import { fetchWithAuth } from '@/lib/fetchWithAuth';
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
  Radio,
  RadioGroup,
  Stack,
  Menu,
  MenuButton,
  MenuList,
  MenuItem,
  IconButton,
  Tooltip,
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
  FiMoreVertical,
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
  validated_entity_count?: number;
  description?: string;
  normalization_status?: string | null;
  normalization_job_id?: string | null;
  normalization_started_at?: string | null;
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
  const [initialFilterSet, setInitialFilterSet] = useState(false);
  const [selectedEntities, setSelectedEntities] = useState<Set<string>>(new Set());

  // Normalisation workflow
  const [showNormalization, setShowNormalization] = useState(false);
  const [generatingOntology, setGeneratingOntology] = useState(false);
  const [ontologyProposals, setOntologyProposals] = useState<OntologyProposal[]>([]);
  const [editingCanonical, setEditingCanonical] = useState<Record<string, string>>({});
  const [hasExistingOntology, setHasExistingOntology] = useState(false);
  const [checkingOntology, setCheckingOntology] = useState(false);

  // Job de normalisation en cours
  const [normalizationJobId, setNormalizationJobId] = useState<string | null>(null);
  const [normalizationStatus, setNormalizationStatus] = useState<'running' | 'completed' | 'failed' | null>(null);

  // Modal changement de type
  const { isOpen: isChangeTypeOpen, onOpen: onChangeTypeOpen, onClose: onChangeTypeClose } = useDisclosure();
  const [entityToChangeType, setEntityToChangeType] = useState<Entity | null>(null);
  const [newEntityType, setNewEntityType] = useState<string>('');
  const [availableTypes, setAvailableTypes] = useState<string[]>([]);
  const [typeInputMode, setTypeInputMode] = useState<'existing' | 'new'>('existing');

  // Option normalisation : inclure entités validées
  const [includeValidated, setIncludeValidated] = useState(false);

  // Snapshots pour rollback
  const [snapshots, setSnapshots] = useState<any[]>([]);
  const [loadingSnapshots, setLoadingSnapshots] = useState(false);
  const [showSnapshots, setShowSnapshots] = useState(false);

  // Modal merge types
  const { isOpen: isMergeTypeOpen, onOpen: onMergeTypeOpen, onClose: onMergeTypeClose } = useDisclosure();
  const [targetMergeType, setTargetMergeType] = useState<string>('');

  // Modal merge entity
  const { isOpen: isMergeEntityOpen, onOpen: onMergeEntityOpen, onClose: onMergeEntityClose } = useDisclosure();
  const [entityToMerge, setEntityToMerge] = useState<Entity | null>(null);
  const [targetEntityUuid, setTargetEntityUuid] = useState<string>('');
  const [mergeCanonicalName, setMergeCanonicalName] = useState<string>('');

  // Migration en masse
  const [bulkAction, setBulkAction] = useState<'approve' | 'merge' | 'change-type'>('approve');
  const [bulkTargetType, setBulkTargetType] = useState<string>('');
  const [bulkTypeInputMode, setBulkTypeInputMode] = useState<'existing' | 'new'>('existing');
  const [isBulkMigrating, setIsBulkMigrating] = useState(false);

  // Réinitialiser le filtre quand on change de type
  useEffect(() => {
    setStatusFilter('pending');
    setInitialFilterSet(false);
  }, [typeName]);

  useEffect(() => {
    fetchTypeInfo();
    fetchEntities();
    fetchAvailableTypes();
    // Ne pas charger les snapshots automatiquement - seulement quand l'utilisateur clique sur Rollback
  }, [typeName, statusFilter]);

  // Vérifier l'existence d'une ontologie et auto-charger si pending_review
  useEffect(() => {
    checkIfOntologyExists();
  }, [typeName]);

  // Auto-charger ontologie si normalization_status = 'pending_review'
  useEffect(() => {
    if (typeInfo?.normalization_status === 'pending_review' && !showNormalization) {
      console.log('[Auto-load] Normalisation pending_review détectée, chargement automatique...');
      loadExistingOntology();
    }
  }, [typeInfo?.normalization_status]);

  // Vérifier si une ontologie existe en cache (sans l'afficher automatiquement)
  const checkIfOntologyExists = async () => {
    try {
      const ontologyResponse = await fetchWithAuth(`/api/entity-types/${typeName}/ontology-proposal`, {
        // fetchWithAuth ajoute automatiquement le token
      });
      if (ontologyResponse.ok) {
        const ontologyData = await ontologyResponse.json();
        setHasExistingOntology(ontologyData.ontology && Object.keys(ontologyData.ontology).length > 0);
      } else {
        setHasExistingOntology(false);
      }
    } catch (error) {
      setHasExistingOntology(false);
    }
  };

  // Ajuster le filtre initial selon le nombre d'entités pending
  useEffect(() => {
    if (typeInfo && !initialFilterSet) {
      // Si aucune entité pending, basculer sur "all"
      if (typeInfo.pending_entity_count === 0 && typeInfo.entity_count > 0) {
        setStatusFilter('all');
      }
      setInitialFilterSet(true);
    }
  }, [typeInfo, initialFilterSet]);

  const fetchAvailableTypes = async () => {
    try {
      const response = await fetchWithAuth('/api/entity-types', {
        // fetchWithAuth ajoute automatiquement le token
      });
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
      const response = await fetchWithAuth(`/api/entity-types/${typeName}/snapshots`, {
        // fetchWithAuth ajoute automatiquement le token
      });
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

  // Note: fetchWithAuth() gère automatiquement l'ajout du JWT token

  const fetchTypeInfo = async () => {
    try {
      const response = await fetchWithAuth(`/api/entity-types/${typeName}`, {
        // fetchWithAuth ajoute automatiquement le token
      });
      if (response.ok) {
        const data = await response.json();
        // Calculer validated_entity_count si absent
        if (data.validated_entity_count === undefined) {
          data.validated_entity_count = Math.max(0, data.entity_count - data.pending_entity_count);
        }
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

      const response = await fetchWithAuth(url, {
        // fetchWithAuth ajoute automatiquement le token
      });
      const data = await response.json();

      // Trier par nom alphabétiquement
      const sortedEntities = (data.entities || []).sort((a: Entity, b: Entity) =>
        a.name.localeCompare(b.name, 'fr', { sensitivity: 'base' })
      );

      setEntities(sortedEntities);
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

  // Charger automatiquement l'ontologie disponible (si elle existe)
  const loadExistingOntology = async () => {
    setCheckingOntology(true);
    try {
      const ontologyResponse = await fetchWithAuth(`/api/entity-types/${typeName}/ontology-proposal`, {
        // fetchWithAuth ajoute automatiquement le token
      });

      if (ontologyResponse.ok) {
        const ontologyData = await ontologyResponse.json();

        // Calculer le preview avec l'ontologie disponible
        const previewResponse = await fetchWithAuth(`/api/entity-types/${typeName}/preview-normalization`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Admin-Key': 'admin-dev-key-change-in-production'
          },
          body: JSON.stringify({ ontology: ontologyData.ontology })
        });

        if (previewResponse.ok) {
          const previewData = await previewResponse.json();
          const mergeGroups = previewData.merge_groups || [];

          if (mergeGroups.length > 0) {
            setOntologyProposals(mergeGroups);
            setShowNormalization(true);
            setHasExistingOntology(true);

            console.log(`[Auto-load] Ontologie trouvée: ${mergeGroups.length} groupes`);
          }
        }
      }
    } catch (error) {
      // Pas d'ontologie disponible, c'est normal
      console.log('[Auto-load] Pas d\'ontologie disponible');
    } finally {
      setCheckingOntology(false);
    }
  };

  const handleCancelNormalization = async () => {
    try {
      const response = await fetchWithAuth(`/api/entity-types/${typeName}/ontology-proposal`, {
        method: 'DELETE',
        headers: {
          'Content-Type': 'application/json',
          'X-Admin-Key': 'admin-dev-key-change-in-production'
        }
      });

      if (response.ok) {
        // Réinitialiser l'état UI
        setShowNormalization(false);
        setOntologyProposals([]);
        setHasExistingOntology(false);

        // Recharger typeInfo pour mettre à jour normalization_status
        await fetchTypeInfo();

        toast({
          title: '✅ Normalisation annulée',
          description: 'Les propositions ont été supprimées',
          status: 'success',
          duration: 3000,
        });
      } else {
        throw new Error('Failed to cancel normalization');
      }
    } catch (error) {
      console.error('Error canceling normalization:', error);
      toast({
        title: 'Erreur',
        description: 'Impossible d\'annuler la normalisation',
        status: 'error',
        duration: 3000,
      });
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

    // Si une ontologie existe déjà, la charger au lieu de régénérer
    if (hasExistingOntology && !showNormalization) {
      await loadExistingOntology();
      return;
    }

    setGeneratingOntology(true);

    try {
      // Lancer génération ontologie (asynchrone)
      const response = await fetchWithAuth(`/api/entity-types/${typeName}/generate-ontology?include_validated=${includeValidated}`, {
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
      const entitiesCount = result.entities_count || 0;

      setGeneratingOntology(false);
      setHasExistingOntology(false); // Invalider l'ancienne ontologie

      toast({
        title: '✅ Génération lancée',
        description: `Traitement de ${entitiesCount} entités en cours. Rechargez la page dans quelques minutes pour voir les résultats.`,
        status: 'success',
        duration: 10000,
        isClosable: true,
      });

    } catch (error) {
      setGeneratingOntology(false);
      toast({
        title: 'Erreur',
        description: 'Erreur lors du lancement de la génération',
        status: 'error',
        duration: 5000,
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

  const handleMoveEntity = (sourceGroupKey: string, targetGroupKey: string, entityUuid: string) => {
    setOntologyProposals(prev => {
      const sourceGroup = prev.find(g => g.canonical_key === sourceGroupKey);
      const targetGroup = prev.find(g => g.canonical_key === targetGroupKey);
      const entityToMove = sourceGroup?.entities.find(e => e.uuid === entityUuid);

      if (!entityToMove || !targetGroup) return prev;

      // Déplacer l'entité vers le groupe cible
      return prev.map(group => {
        if (group.canonical_key === sourceGroupKey) {
          // Retirer l'entité du groupe source
          const newEntities = group.entities.filter(e => e.uuid !== entityUuid);
          // Si c'était le master et qu'il reste des entités, choisir un nouveau master
          const newMasterUuid = group.master_uuid === entityUuid && newEntities.length > 0
            ? newEntities[0].uuid
            : group.master_uuid;

          return {
            ...group,
            entities: newEntities,
            master_uuid: newMasterUuid
          };
        } else if (group.canonical_key === targetGroupKey) {
          // Ajouter l'entité au groupe cible
          return {
            ...group,
            entities: [
              ...group.entities,
              {
                ...entityToMove,
                selected: true, // Par défaut sélectionnée
                score: 80, // Score manuel
                auto_match: false,
                matched_via: 'manual_move'
              }
            ]
          };
        }
        return group;
      }).filter(group => group.entities.length > 0); // Supprimer groupes vides
    });

    toast({
      title: 'Entité déplacée',
      description: `L'entité a été déplacée vers le groupe cible`,
      status: 'success',
      duration: 2000,
    });
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
      const response = await fetchWithAuth(`/api/entity-types/${typeName}/normalize-entities`, {
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
        const response = await fetchWithAuth(`/api/jobs/${jobId}/status`, {
          // fetchWithAuth ajoute automatiquement le token
        });
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
      const response = await fetchWithAuth(`/api/entities/${uuid}/approve`, {
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
    setTypeInputMode('existing');
    onChangeTypeOpen();
  };

  const handleChangeTypeSubmit = async () => {
    if (!entityToChangeType || !newEntityType) return;

    try {
      const response = await fetchWithAuth(`/api/entities/${entityToChangeType.uuid}/change-type`, {
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
      const response = await fetchWithAuth(`/api/entity-types/${typeName}/undo-normalization`, {
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
          // Rafraîchir les snapshots seulement s'ils étaient affichés
          if (showSnapshots) {
            fetchSnapshots();
          }
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
      const response = await fetchWithAuth(`/api/entity-types/${typeName}/merge-into/${targetMergeType}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
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

  const handleOpenMergeEntity = (entity: Entity) => {
    setEntityToMerge(entity);
    setTargetEntityUuid('');
    setMergeCanonicalName('');
    onMergeEntityOpen();
  };

  const handleMergeEntitySubmit = async () => {
    if (!entityToMerge || !targetEntityUuid) return;

    try {
      const response = await fetchWithAuth(`/api/entities/${entityToMerge.uuid}/merge`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Admin-Key': 'admin-dev-key-change-in-production'
        },
        body: JSON.stringify({
          target_uuid: targetEntityUuid,
          canonical_name: mergeCanonicalName || null
        })
      });

      if (response.ok) {
        const data = await response.json();
        toast({
          title: 'Entités fusionnées',
          description: `${data.relations_transferred} relations transférées`,
          status: 'success',
          duration: 3000,
        });
        onMergeEntityClose();
        fetchEntities();
        fetchTypeInfo();
      } else {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.error || 'Merge failed');
      }
    } catch (error: any) {
      toast({
        title: 'Erreur fusion',
        description: error.message || 'Impossible de fusionner les entités',
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

  const handleBulkApprove = async () => {
    if (selectedEntities.size === 0) {
      toast({
        title: 'Aucune sélection',
        description: 'Sélectionnez au moins une entité à approuver',
        status: 'warning',
        duration: 3000,
      });
      return;
    }

    setIsBulkMigrating(true);
    try {
      const promises = Array.from(selectedEntities).map(uuid =>
        fetchWithAuth(`/api/entities/${uuid}/approve`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Admin-Key': 'admin-dev-key-change-in-production'
          },
          body: JSON.stringify({ admin_email: 'admin@example.com' })
        })
      );

      const results = await Promise.all(promises);
      const successCount = results.filter(r => r.ok).length;

      toast({
        title: 'Approbation réussie',
        description: `${successCount} entité(s) approuvée(s)`,
        status: 'success',
        duration: 4000,
      });

      setSelectedEntities(new Set());
      fetchEntities();
      fetchTypeInfo();
    } catch (error: any) {
      toast({
        title: 'Erreur approbation',
        description: error.message || 'Impossible d\'approuver les entités',
        status: 'error',
        duration: 5000,
      });
    } finally {
      setIsBulkMigrating(false);
    }
  };

  const handleBulkMerge = () => {
    if (selectedEntities.size < 2) {
      toast({
        title: 'Sélection insuffisante',
        description: 'Sélectionnez au moins 2 entités à fusionner',
        status: 'warning',
        duration: 3000,
      });
      return;
    }

    // Ouvrir la modal de fusion avec la première entité comme source
    const firstEntityUuid = Array.from(selectedEntities)[0];
    const firstEntity = entities.find(e => e.uuid === firstEntityUuid);
    if (firstEntity) {
      handleOpenMergeEntity(firstEntity);
      // Pré-sélectionner la deuxième entité comme target si possible
      const secondEntityUuid = Array.from(selectedEntities)[1];
      if (secondEntityUuid) {
        setTargetEntityUuid(secondEntityUuid);
      }
    }
  };

  const handleBulkMigrateSubmit = async () => {
    if (selectedEntities.size === 0 || !bulkTargetType) {
      toast({
        title: 'Sélection incomplète',
        description: 'Sélectionnez des entités et un type de destination',
        status: 'warning',
        duration: 3000,
      });
      return;
    }

    setIsBulkMigrating(true);
    try {
      const response = await fetchWithAuth('/api/entities/bulk-change-type', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Admin-Key': 'admin-dev-key-change-in-production'
        },
        body: JSON.stringify({
          entity_uuids: Array.from(selectedEntities),
          new_entity_type: bulkTargetType
        })
      });

      if (response.ok) {
        const data = await response.json();
        toast({
          title: 'Migration réussie',
          description: `${data.migrated_count} entités migrées vers ${bulkTargetType}`,
          status: 'success',
          duration: 4000,
        });
        setSelectedEntities(new Set());
        setBulkTargetType('');
        fetchEntities();
        fetchTypeInfo();
      } else {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.error || 'Migration failed');
      }
    } catch (error: any) {
      toast({
        title: 'Erreur migration',
        description: error.message || 'Impossible de migrer les entités',
        status: 'error',
        duration: 5000,
      });
    } finally {
      setIsBulkMigrating(false);
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
                  <StatNumber color="green.500">{typeInfo.validated_entity_count ?? 0}</StatNumber>
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
                          isLoading={generatingOntology || checkingOntology || typeInfo?.normalization_status === 'generating'}
                          loadingText={
                            typeInfo?.normalization_status === 'generating' ? '⏳ Génération en cours...' :
                            checkingOntology ? "Chargement..." :
                            "Génération..."
                          }
                          isDisabled={typeInfo?.normalization_status === 'generating'}
                        >
                          {typeInfo?.normalization_status === 'generating' ? '⏳ Génération en cours...' :
                           hasExistingOntology && !showNormalization ? '📥 Charger propositions existantes' :
                           showNormalization ? '🔄 Régénérer propositions' :
                           '🤖 Générer propositions canoniques'}
                        </Button>
                        {showNormalization && (
                          <Button
                            colorScheme="red"
                            variant="outline"
                            onClick={handleCancelNormalization}
                          >
                            🗑️ Annuler normalisation
                          </Button>
                        )}
                      </>
                    )}
                    <Button
                      colorScheme="teal"
                      variant="outline"
                      leftIcon={<Icon as={FiClock} />}
                      onClick={fetchSnapshots}
                      isLoading={loadingSnapshots}
                    >
                      {showSnapshots ? 'Masquer snapshots' : 'Rollback / Snapshots'}
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
                  <>
                    {/* Barre d'actions en masse */}
                    {selectedEntities.size > 0 && (
                      <Card bg="blue.50" borderColor="blue.200" borderWidth="2px" mb={4}>
                        <CardBody>
                          <Flex direction={{ base: 'column', md: 'row' }} gap={4} align="center" wrap="wrap">
                            <Badge colorScheme="blue" fontSize="md" px={3} py={1}>
                              {selectedEntities.size} entité(s) sélectionnée(s)
                            </Badge>

                            <Select
                              value={bulkAction}
                              onChange={(e) => {
                                setBulkAction(e.target.value as 'approve' | 'merge' | 'change-type');
                                setBulkTargetType('');
                              }}
                              maxW="200px"
                            >
                              <option value="approve">Approuver</option>
                              <option value="merge">Fusionner</option>
                              <option value="change-type">Changer type</option>
                            </Select>

                            {bulkAction === 'change-type' && (
                              <>
                                <RadioGroup
                                  value={bulkTypeInputMode}
                                  onChange={(value) => {
                                    setBulkTypeInputMode(value as 'existing' | 'new');
                                    setBulkTargetType('');
                                  }}
                                >
                                  <Stack direction="row" spacing={4}>
                                    <Radio value="existing">Type existant</Radio>
                                    <Radio value="new">Créer nouveau</Radio>
                                  </Stack>
                                </RadioGroup>

                                {bulkTypeInputMode === 'existing' ? (
                                  <Select
                                    placeholder="Sélectionnez le type de destination"
                                    value={bulkTargetType}
                                    onChange={(e) => setBulkTargetType(e.target.value)}
                                    maxW="300px"
                                  >
                                    {availableTypes
                                      .filter(t => t !== typeName)
                                      .map(type => (
                                        <option key={type} value={type}>{type}</option>
                                      ))
                                    }
                                  </Select>
                                ) : (
                                  <Input
                                    placeholder="ex: SERVICE, TECHNOLOGY..."
                                    value={bulkTargetType}
                                    onChange={(e) => setBulkTargetType(e.target.value.toUpperCase())}
                                    maxW="300px"
                                  />
                                )}
                              </>
                            )}

                            <HStack ml="auto">
                              {bulkAction === 'approve' && (
                                <Button
                                  colorScheme="green"
                                  leftIcon={<FiCheckCircle />}
                                  onClick={handleBulkApprove}
                                  isLoading={isBulkMigrating}
                                  loadingText="Approbation..."
                                >
                                  Approuver ({selectedEntities.size})
                                </Button>
                              )}
                              {bulkAction === 'merge' && (
                                <Button
                                  colorScheme="purple"
                                  leftIcon={<FiGitMerge />}
                                  onClick={handleBulkMerge}
                                  isDisabled={selectedEntities.size < 2}
                                >
                                  Fusionner ({selectedEntities.size})
                                </Button>
                              )}
                              {bulkAction === 'change-type' && (
                                <Button
                                  colorScheme="blue"
                                  leftIcon={<FiEdit2 />}
                                  onClick={handleBulkMigrateSubmit}
                                  isLoading={isBulkMigrating}
                                  loadingText="Migration..."
                                  isDisabled={!bulkTargetType}
                                >
                                  Migrer vers {bulkTargetType || '...'}
                                </Button>
                              )}
                              <Button
                                variant="ghost"
                                onClick={() => setSelectedEntities(new Set())}
                              >
                                Annuler
                              </Button>
                            </HStack>
                          </Flex>
                        </CardBody>
                      </Card>
                    )}

                    <Card>
                      <CardBody p={0}>
                        <Table variant="simple">
                          <Thead>
                            <Tr>
                              <Th width="50px">
                                <Checkbox
                                  isChecked={selectedEntities.size === entities.length && entities.length > 0}
                                  onChange={handleToggleAll}
                                  colorScheme="blue"
                                />
                              </Th>
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
                              <Td>
                                <Checkbox
                                  isChecked={selectedEntities.has(entity.uuid)}
                                  onChange={() => handleToggleEntity(entity.uuid)}
                                  colorScheme="blue"
                                />
                              </Td>
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
                              <Td maxW="300px">
                                <Tooltip label={entity.description || '-'} hasArrow placement="top">
                                  <Text
                                    fontSize="sm"
                                    color="gray.600"
                                    noOfLines={3}
                                    whiteSpace="normal"
                                  >
                                    {entity.description || '-'}
                                  </Text>
                                </Tooltip>
                              </Td>
                              <Td fontSize="sm" whiteSpace="nowrap">
                                {new Date(entity.created_at).toLocaleDateString('fr-FR')}
                              </Td>
                              <Td>
                                <Menu>
                                  <MenuButton
                                    as={IconButton}
                                    icon={<FiMoreVertical />}
                                    variant="ghost"
                                    size="sm"
                                    aria-label="Actions"
                                  />
                                  <MenuList>
                                    {entity.status === 'pending' && (
                                      <MenuItem
                                        icon={<FiCheckCircle />}
                                        onClick={() => handleApproveEntity(entity.uuid)}
                                      >
                                        Approuver
                                      </MenuItem>
                                    )}
                                    <MenuItem
                                      icon={<FiGitMerge />}
                                      onClick={() => handleOpenMergeEntity(entity)}
                                    >
                                      Fusionner
                                    </MenuItem>
                                    <MenuItem
                                      icon={<FiEdit2 />}
                                      onClick={() => handleOpenChangeType(entity)}
                                    >
                                      Changer type
                                    </MenuItem>
                                  </MenuList>
                                </Menu>
                              </Td>
                            </Tr>
                          ))}
                        </Tbody>
                      </Table>
                    </CardBody>
                  </Card>
                  </>
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
                                  <Th width="280px">Actions</Th>
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
                                      <HStack spacing={2}>
                                        <Select
                                          size="sm"
                                          placeholder="Déplacer vers..."
                                          onChange={(e) => {
                                            if (e.target.value) {
                                              handleMoveEntity(group.canonical_key, e.target.value, entity.uuid);
                                              e.target.value = ''; // Reset
                                            }
                                          }}
                                          maxW="150px"
                                        >
                                          {ontologyProposals
                                            .filter(g => g.canonical_key !== group.canonical_key)
                                            .map(g => (
                                              <option key={g.canonical_key} value={g.canonical_key}>
                                                {g.canonical_name}
                                              </option>
                                            ))
                                          }
                                        </Select>
                                        <Button
                                          size="sm"
                                          colorScheme="purple"
                                          variant="outline"
                                          onClick={() => handleExtractEntity(group.canonical_key, entity.uuid)}
                                          title="Extraire cette entité dans un groupe séparé"
                                        >
                                          Extraire
                                        </Button>
                                      </HStack>
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

                <RadioGroup
                  value={typeInputMode}
                  onChange={(value) => {
                    setTypeInputMode(value as 'existing' | 'new');
                    setNewEntityType('');
                  }}
                  mb={3}
                >
                  <Stack direction="row" spacing={4}>
                    <Radio value="existing">Type existant</Radio>
                    <Radio value="new">Créer nouveau type</Radio>
                  </Stack>
                </RadioGroup>

                {typeInputMode === 'existing' ? (
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
                ) : (
                  <Input
                    placeholder="ex: SERVICE, TECHNOLOGY..."
                    value={newEntityType}
                    onChange={(e) => setNewEntityType(e.target.value.toUpperCase())}
                    autoFocus
                  />
                )}
              </Box>

              <Alert status="info" variant="left-accent">
                <AlertIcon />
                <Text fontSize="sm">
                  {typeInputMode === 'new'
                    ? "Le nouveau type d'entité sera créé automatiquement lors du changement. L'entité sera la première de ce nouveau type."
                    : "L'entité sera déplacée vers le type sélectionné. Vous pourrez ensuite la normaliser avec les autres entités de ce type."
                  }
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

      {/* Modal Merge Entity */}
      <Modal isOpen={isMergeEntityOpen} onClose={onMergeEntityClose} size="lg">
        <ModalOverlay />
        <ModalContent>
          <ModalHeader>Fusionner deux entités</ModalHeader>
          <ModalCloseButton />
          <ModalBody>
            <VStack spacing={4} align="stretch">
              <Alert status="warning" variant="left-accent">
                <AlertIcon />
                <VStack align="start" spacing={1}>
                  <Text fontWeight="bold" fontSize="sm">⚠️ Fusion manuelle d'entités</Text>
                  <Text fontSize="xs">
                    L'entité source sera fusionnée dans l'entité cible.
                    Toutes les relations seront transférées et l'entité source sera supprimée.
                  </Text>
                </VStack>
              </Alert>

              <Box>
                <Text fontWeight="bold" mb={2}>Entité source (sera supprimée) :</Text>
                <Badge colorScheme="red" fontSize="md" px={3} py={1}>
                  {entityToMerge?.name}
                </Badge>
                {entityToMerge?.canonical_name && (
                  <Text fontSize="xs" color="gray.600" mt={1}>
                    Nom canonique : {entityToMerge.canonical_name}
                  </Text>
                )}
              </Box>

              <Box>
                <Text fontWeight="bold" mb={2}>Entité cible (sera conservée) :</Text>
                <Select
                  placeholder="Sélectionnez l'entité cible"
                  value={targetEntityUuid}
                  onChange={(e) => {
                    setTargetEntityUuid(e.target.value);
                    // Pré-remplir le nom canonique avec le nom de l'entité cible
                    const targetEntity = entities.find(ent => ent.uuid === e.target.value);
                    if (targetEntity) {
                      setMergeCanonicalName(targetEntity.canonical_name || targetEntity.name);
                    }
                  }}
                  size="md"
                >
                  {entities
                    .filter(e => e.uuid !== entityToMerge?.uuid)
                    .sort((a, b) => a.name.localeCompare(b.name, 'fr', { sensitivity: 'base' }))
                    .map(entity => (
                      <option key={entity.uuid} value={entity.uuid}>
                        {entity.name}
                        {entity.canonical_name ? ` (${entity.canonical_name})` : ''}
                      </option>
                    ))
                  }
                </Select>
              </Box>

              <Box>
                <Text fontWeight="bold" mb={2}>Nom canonique final (optionnel) :</Text>
                <Input
                  placeholder="Ex: SAP S/4HANA PCE"
                  value={mergeCanonicalName}
                  onChange={(e) => setMergeCanonicalName(e.target.value)}
                  size="md"
                />
                <Text fontSize="xs" color="gray.600" mt={1}>
                  Si non renseigné, conserve le nom actuel de l'entité cible
                </Text>
              </Box>

              <Alert status="info" variant="left-accent">
                <AlertIcon />
                <Text fontSize="sm">
                  Cette action transfère toutes les relations (entrantes et sortantes) de l'entité source vers l'entité cible,
                  puis supprime l'entité source.
                </Text>
              </Alert>
            </VStack>
          </ModalBody>

          <ModalFooter>
            <Button variant="ghost" mr={3} onClick={onMergeEntityClose}>
              Annuler
            </Button>
            <Button
              colorScheme="purple"
              leftIcon={<FiGitMerge />}
              onClick={handleMergeEntitySubmit}
              isDisabled={!targetEntityUuid}
            >
              Fusionner les entités
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
    </Container>
  );
}
