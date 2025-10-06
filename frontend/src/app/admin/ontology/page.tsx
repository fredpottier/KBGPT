"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
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
} from "@chakra-ui/react";
import { FiPackage, FiCpu, FiCode, FiUsers, FiUser, FiZap } from "react-icons/fi";

interface CatalogStats {
  entity_type: string;
  total_entities: number;
  total_aliases: number;
  categories: Record<string, number>;
  vendors: Record<string, number>;
}

const ENTITY_TYPES = [
  {
    type: "SOLUTION",
    label: "Solutions",
    icon: FiPackage,
    color: "blue",
    description: "Solutions logicielles (ERP, CRM, etc.)",
  },
  {
    type: "COMPONENT",
    label: "Composants",
    icon: FiCpu,
    color: "green",
    description: "Composants techniques (Load Balancer, API Gateway)",
  },
  {
    type: "TECHNOLOGY",
    label: "Technologies",
    icon: FiCode,
    color: "orange",
    description: "Technologies et frameworks (Kubernetes, React)",
  },
  {
    type: "ORGANIZATION",
    label: "Organisations",
    icon: FiUsers,
    color: "purple",
    description: "Entreprises (SAP, Microsoft, AWS)",
  },
  {
    type: "PERSON",
    label: "Rôles",
    icon: FiUser,
    color: "pink",
    description: "Rôles et postes (Architect, Developer)",
  },
  {
    type: "CONCEPT",
    label: "Concepts",
    icon: FiZap,
    color: "teal",
    description: "Concepts business/techniques (Microservices, DevOps)",
  },
];

export default function OntologyPage() {
  const [statsMap, setStatsMap] = useState<Record<string, CatalogStats>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadAllStats();
  }, []);

  const loadAllStats = async () => {
    try {
      setLoading(true);
      setError(null);

      const promises = ENTITY_TYPES.map(async (entityType) => {
        const res = await fetch(
          `http://localhost:8000/api/ontology/catalogs/${entityType.type}/statistics`
        );
        if (!res.ok) {
          throw new Error(`Failed to load ${entityType.type} stats`);
        }
        const stats: CatalogStats = await res.json();
        return { type: entityType.type, stats };
      });

      const results = await Promise.all(promises);

      const newStatsMap: Record<string, CatalogStats> = {};
      results.forEach(({ type, stats }) => {
        newStatsMap[type] = stats;
      });

      setStatsMap(newStatsMap);
    } catch (err: any) {
      setError(err.message || "Erreur chargement statistiques");
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <Container maxW="container.xl" py={8}>
        <Heading mb={4}>📚 Gestion des Ontologies</Heading>
        <Spinner size="xl" />
      </Container>
    );
  }

  if (error) {
    return (
      <Container maxW="container.xl" py={8}>
        <Heading mb={4}>📚 Gestion des Ontologies</Heading>
        <Alert status="error">
          <AlertIcon />
          {error}
        </Alert>
      </Container>
    );
  }

  return (
    <Container maxW="container.xl" py={8}>
      <VStack align="stretch" spacing={6}>
        <Box>
          <Heading size="lg" mb={2}>📚 Gestion des Catalogues d'Ontologies</Heading>
          <Text color="gray.600" mb={4}>
            Gérer les catalogues de normalisation des entités du Knowledge Graph.
            Chaque catalogue contient les noms canoniques et aliases pour éviter les doublons.
          </Text>
          <Link href="/admin/ontology/uncataloged">
            <Button colorScheme="orange" size="sm">
              ⚠️ Voir Entités Non Cataloguées
            </Button>
          </Link>
        </Box>

        <SimpleGrid columns={{ base: 1, md: 2, lg: 3 }} spacing={6}>
          {ENTITY_TYPES.map((entityType) => {
            const stats = statsMap[entityType.type];

            return (
              <Link
                key={entityType.type}
                href={`/admin/ontology/${entityType.type.toLowerCase()}`}
              >
                <Card
                  _hover={{
                    transform: "translateY(-4px)",
                    shadow: "lg",
                    borderColor: `${entityType.color}.500`,
                  }}
                  transition="all 0.2s"
                  cursor="pointer"
                  borderTop="4px"
                  borderColor={`${entityType.color}.500`}
                >
                  <CardHeader>
                    <HStack>
                      <Icon as={entityType.icon} boxSize={8} color={`${entityType.color}.500`} />
                      <VStack align="start" spacing={0}>
                        <Heading size="md">{entityType.label}</Heading>
                        <Text fontSize="sm" color="gray.600">
                          {entityType.description}
                        </Text>
                      </VStack>
                    </HStack>
                  </CardHeader>
                  <CardBody>
                    {stats ? (
                      <VStack align="stretch" spacing={3}>
                        <Stat>
                          <StatLabel>Entités</StatLabel>
                          <StatNumber>{stats.total_entities}</StatNumber>
                        </Stat>
                        <Stat>
                          <StatLabel>Aliases</StatLabel>
                          <StatNumber>{stats.total_aliases}</StatNumber>
                        </Stat>
                        {Object.keys(stats.categories).length > 0 && (
                          <Box>
                            <Text fontSize="sm" color="gray.600" mb={1}>
                              Top Catégories :
                            </Text>
                            <HStack flexWrap="wrap">
                              {Object.entries(stats.categories)
                                .slice(0, 3)
                                .map(([category, count]) => (
                                  <Badge key={category} colorScheme={entityType.color}>
                                    {category} ({count})
                                  </Badge>
                                ))}
                            </HStack>
                          </Box>
                        )}
                      </VStack>
                    ) : (
                      <Text color="gray.500">Aucune statistique disponible</Text>
                    )}
                  </CardBody>
                </Card>
              </Link>
            );
          })}
        </SimpleGrid>
      </VStack>
    </Container>
  );
}
