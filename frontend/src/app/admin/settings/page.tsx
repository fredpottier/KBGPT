"use client";

import {
  Container,
  Heading,
  Text,
  VStack,
  Alert,
  AlertIcon,
  Card,
  CardHeader,
  CardBody,
  Button,
  HStack,
  Badge,
  useToast,
  useDisclosure,
  Modal,
  ModalOverlay,
  ModalContent,
  ModalHeader,
  ModalFooter,
  ModalBody,
  ModalCloseButton,
  Spinner,
  Box,
  Divider,
} from "@chakra-ui/react";
import { DeleteIcon, CheckCircleIcon, WarningIcon } from "@chakra-ui/icons";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import axios from "axios";
import { useState } from "react";

interface HealthComponent {
  status: string;
  message: string;
}

interface HealthResponse {
  success: boolean;
  overall_status: string;
  components: {
    qdrant: HealthComponent;
    neo4j: HealthComponent;
    redis: HealthComponent;
  };
}

interface PurgeResult {
  success: boolean;
  message: string;
  points_deleted?: number;
  nodes_deleted?: number;
  relations_deleted?: number;
  jobs_deleted?: number;
}

interface PurgeResponse {
  success: boolean;
  message: string;
  results: {
    qdrant: PurgeResult;
    neo4j: PurgeResult;
    redis: PurgeResult;
  };
}

export default function AdminSettingsPage() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const { isOpen, onOpen, onClose } = useDisclosure();
  const [purgeResults, setPurgeResults] = useState<PurgeResponse | null>(null);

  // Requête health check
  const { data: healthData, isLoading: isLoadingHealth, refetch: refetchHealth } = useQuery<HealthResponse>({
    queryKey: ["admin", "health"],
    queryFn: async () => {
      const response = await axios.get("/api/admin/health");
      return response.data;
    },
    refetchInterval: 10000, // Rafraîchir toutes les 10 secondes
  });

  // Mutation purge
  const purgeMutation = useMutation({
    mutationFn: async () => {
      const response = await axios.post<PurgeResponse>("/api/admin/purge-data");
      return response.data;
    },
    onSuccess: (data) => {
      setPurgeResults(data);

      if (data.success) {
        toast({
          title: "✅ Purge réussie",
          description: "Toutes les données d'ingestion ont été supprimées",
          status: "success",
          duration: 5000,
          isClosable: true,
        });
      } else {
        toast({
          title: "⚠️ Purge partielle",
          description: "Certains composants n'ont pas pu être purgés (voir détails)",
          status: "warning",
          duration: 7000,
          isClosable: true,
        });
      }

      // Rafraîchir health après purge
      refetchHealth();

      // Invalider queries liées aux données purgées
      queryClient.invalidateQueries({ queryKey: ["documents"] });
      queryClient.invalidateQueries({ queryKey: ["imports"] });
      queryClient.invalidateQueries({ queryKey: ["admin", "stats"] });
    },
    onError: (error: any) => {
      toast({
        title: "❌ Erreur de purge",
        description: error.response?.data?.error || "Échec de la purge",
        status: "error",
        duration: 5000,
        isClosable: true,
      });
    },
  });

  const handlePurgeConfirm = () => {
    onClose();
    purgeMutation.mutate();
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case "healthy":
        return "green";
      case "unhealthy":
        return "red";
      default:
        return "gray";
    }
  };

  return (
    <Container maxW="container.xl" py={8}>
      <VStack align="stretch" spacing={6}>
        <Heading size="lg">⚙️ Configuration Système</Heading>

        {/* Health Check Section */}
        <Card>
          <CardHeader>
            <HStack justify="space-between">
              <Heading size="md">État des Composants</Heading>
              <Button
                size="sm"
                onClick={() => refetchHealth()}
                isLoading={isLoadingHealth}
              >
                Rafraîchir
              </Button>
            </HStack>
          </CardHeader>
          <CardBody>
            {isLoadingHealth ? (
              <Spinner />
            ) : healthData ? (
              <VStack align="stretch" spacing={4}>
                <HStack>
                  <Text fontWeight="semibold">Statut global:</Text>
                  <Badge colorScheme={getStatusColor(healthData.overall_status)} fontSize="md">
                    {healthData.overall_status}
                  </Badge>
                </HStack>

                <Divider />

                {/* Qdrant */}
                <HStack justify="space-between">
                  <HStack>
                    <Text fontWeight="medium">Qdrant (Base vectorielle)</Text>
                    <Badge colorScheme={getStatusColor(healthData.components.qdrant.status)}>
                      {healthData.components.qdrant.status}
                    </Badge>
                  </HStack>
                  <Text fontSize="sm" color="gray.600">
                    {healthData.components.qdrant.message}
                  </Text>
                </HStack>

                {/* Neo4j */}
                <HStack justify="space-between">
                  <HStack>
                    <Text fontWeight="medium">Neo4j (Knowledge Graph)</Text>
                    <Badge colorScheme={getStatusColor(healthData.components.neo4j.status)}>
                      {healthData.components.neo4j.status}
                    </Badge>
                  </HStack>
                  <Text fontSize="sm" color="gray.600">
                    {healthData.components.neo4j.message}
                  </Text>
                </HStack>

                {/* Redis */}
                <HStack justify="space-between">
                  <HStack>
                    <Text fontWeight="medium">Redis (Queue jobs)</Text>
                    <Badge colorScheme={getStatusColor(healthData.components.redis.status)}>
                      {healthData.components.redis.status}
                    </Badge>
                  </HStack>
                  <Text fontSize="sm" color="gray.600">
                    {healthData.components.redis.message}
                  </Text>
                </HStack>
              </VStack>
            ) : (
              <Alert status="error">
                <AlertIcon />
                Impossible de récupérer l'état de santé
              </Alert>
            )}
          </CardBody>
        </Card>

        {/* Purge Section */}
        <Card borderColor="red.200" borderWidth="2px">
          <CardHeader>
            <Heading size="md" color="red.600">
              🚨 Zone Dangereuse
            </Heading>
          </CardHeader>
          <CardBody>
            <VStack align="stretch" spacing={4}>
              <Alert status="warning">
                <AlertIcon />
                <Box>
                  <Text fontWeight="semibold">Purge complète des données d'ingestion</Text>
                  <Text fontSize="sm" mt={1}>
                    Cette action supprimera TOUTES les données importées (Qdrant, Neo4j, Redis) mais préservera
                    les configurations (Types de documents, Types d'entités).
                  </Text>
                </Box>
              </Alert>

              <Box>
                <Text fontWeight="semibold" mb={2}>
                  Sera supprimé :
                </Text>
                <VStack align="start" spacing={1} pl={4}>
                  <Text fontSize="sm">• Tous les points vectoriels (Qdrant)</Text>
                  <Text fontSize="sm">• Tous les nodes et relations (Neo4j)</Text>
                  <Text fontSize="sm">• Toutes les queues et jobs (Redis)</Text>
                </VStack>
              </Box>

              <Box>
                <Text fontWeight="semibold" mb={2} color="green.600">
                  Sera préservé :
                </Text>
                <VStack align="start" spacing={1} pl={4}>
                  <Text fontSize="sm">• Types de documents (DocumentType)</Text>
                  <Text fontSize="sm">• Types d'entités (EntityTypeRegistry)</Text>
                  <Text fontSize="sm">• Configuration système</Text>
                </VStack>
              </Box>

              <Button
                leftIcon={<DeleteIcon />}
                colorScheme="red"
                onClick={onOpen}
                isLoading={purgeMutation.isPending}
                loadingText="Purge en cours..."
              >
                Purger toutes les données
              </Button>

              {/* Résultats de purge */}
              {purgeResults && (
                <Alert
                  status={purgeResults.success ? "success" : "warning"}
                  flexDirection="column"
                  alignItems="start"
                >
                  <HStack mb={2}>
                    <AlertIcon />
                    <Text fontWeight="semibold">{purgeResults.message}</Text>
                  </HStack>
                  <VStack align="start" spacing={1} pl={6} fontSize="sm">
                    <HStack>
                      {purgeResults.results.qdrant.success ? (
                        <CheckCircleIcon color="green.500" />
                      ) : (
                        <WarningIcon color="red.500" />
                      )}
                      <Text>
                        Qdrant: {purgeResults.results.qdrant.points_deleted} points supprimés
                      </Text>
                    </HStack>
                    <HStack>
                      {purgeResults.results.neo4j.success ? (
                        <CheckCircleIcon color="green.500" />
                      ) : (
                        <WarningIcon color="red.500" />
                      )}
                      <Text>
                        Neo4j: {purgeResults.results.neo4j.nodes_deleted} nodes,{" "}
                        {purgeResults.results.neo4j.relations_deleted} relations supprimés
                      </Text>
                    </HStack>
                    <HStack>
                      {purgeResults.results.redis.success ? (
                        <CheckCircleIcon color="green.500" />
                      ) : (
                        <WarningIcon color="red.500" />
                      )}
                      <Text>
                        Redis: {purgeResults.results.redis.jobs_deleted} jobs supprimés
                      </Text>
                    </HStack>
                  </VStack>
                </Alert>
              )}
            </VStack>
          </CardBody>
        </Card>
      </VStack>

      {/* Modal de confirmation */}
      <Modal isOpen={isOpen} onClose={onClose} isCentered>
        <ModalOverlay />
        <ModalContent>
          <ModalHeader>⚠️ Confirmation de purge</ModalHeader>
          <ModalCloseButton />
          <ModalBody>
            <VStack align="start" spacing={4}>
              <Text>
                Êtes-vous sûr de vouloir purger <strong>TOUTES</strong> les données d'ingestion ?
              </Text>
              <Alert status="error">
                <AlertIcon />
                Cette action est <strong>irréversible</strong> !
              </Alert>
              <Text fontSize="sm" color="gray.600">
                Vous devrez réimporter tous vos documents après cette opération.
              </Text>
            </VStack>
          </ModalBody>

          <ModalFooter>
            <Button variant="ghost" mr={3} onClick={onClose}>
              Annuler
            </Button>
            <Button colorScheme="red" onClick={handlePurgeConfirm}>
              Confirmer la purge
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
    </Container>
  );
}
