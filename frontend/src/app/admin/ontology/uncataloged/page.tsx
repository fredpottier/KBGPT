"use client";

import { useState, useEffect } from "react";
import {
  Container,
  Heading,
  Button,
  Table,
  Thead,
  Tbody,
  Tr,
  Th,
  Td,
  Badge,
  IconButton,
  Spinner,
  Alert,
  AlertIcon,
  HStack,
  VStack,
  Text,
  useDisclosure,
  Modal,
  ModalOverlay,
  ModalContent,
  ModalHeader,
  ModalBody,
  ModalFooter,
  ModalCloseButton,
  FormControl,
  FormLabel,
  Input,
  Textarea,
  Box,
} from "@chakra-ui/react";
import { FiArrowLeft, FiRefreshCw, FiCheckCircle, FiXCircle } from "react-icons/fi";
import Link from "next/link";

interface UncatalogedEntity {
  raw_name: string;
  entity_type: string;
  occurrences: number;
  first_seen: string;
  last_seen: string;
  tenants: string[];
  suggested_entity_id: string | null;
}

export default function UncatalogedPage() {
  const [entities, setEntities] = useState<UncatalogedEntity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const { isOpen, onOpen, onClose } = useDisclosure();
  const [selectedEntity, setSelectedEntity] = useState<UncatalogedEntity | null>(null);
  const [formData, setFormData] = useState({
    entity_id: "",
    canonical_name: "",
    aliases: "",
    category: "",
    vendor: "",
  });

  useEffect(() => {
    loadUncataloged();
  }, []);

  const loadUncataloged = async () => {
    try {
      setLoading(true);
      const res = await fetch(`http://localhost:8000/api/ontology/uncataloged`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: UncatalogedEntity[] = await res.json();
      setEntities(data);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleOpenApprove = (entity: UncatalogedEntity) => {
    setSelectedEntity(entity);
    setFormData({
      entity_id: entity.suggested_entity_id || "",
      canonical_name: entity.raw_name,
      aliases: "",
      category: "",
      vendor: "",
    });
    onOpen();
  };

  const handleApprove = async () => {
    if (!selectedEntity) return;

    try {
      const aliases = formData.aliases.split(",").map((a) => a.trim()).filter((a) => a);

      await fetch(
        `http://localhost:8000/api/ontology/uncataloged/${selectedEntity.entity_type}/approve?raw_name=${encodeURIComponent(selectedEntity.raw_name)}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            entity_id: formData.entity_id,
            canonical_name: formData.canonical_name,
            aliases,
            category: formData.category || null,
            vendor: formData.vendor || null,
          }),
        }
      );

      alert(`✅ Entité approuvée: ${selectedEntity.raw_name}`);
      onClose();
      loadUncataloged();
    } catch (err: any) {
      alert(err.message);
    }
  };

  const handleReject = async (entity: UncatalogedEntity) => {
    if (!confirm(`Rejeter "${entity.raw_name}" ?`)) return;

    try {
      await fetch(
        `http://localhost:8000/api/ontology/uncataloged/${entity.entity_type}/reject?raw_name=${encodeURIComponent(entity.raw_name)}`,
        { method: "DELETE" }
      );
      alert(`❌ Entité rejetée`);
      loadUncataloged();
    } catch (err: any) {
      alert(err.message);
    }
  };

  if (loading) {
    return (
      <Container maxW="container.xl" py={8}>
        <Spinner size="xl" />
      </Container>
    );
  }

  return (
    <Container maxW="container.xl" py={8}>
      <VStack align="stretch" spacing={6}>
        <HStack justify="space-between">
          <HStack>
            <Link href="/admin/ontology">
              <IconButton aria-label="Retour" icon={<FiArrowLeft />} />
            </Link>
            <Heading size="lg">⚠️ Entités Non Cataloguées</Heading>
          </HStack>
          <Button leftIcon={<FiRefreshCw />} onClick={loadUncataloged}>
            Actualiser
          </Button>
        </HStack>

        {error && (
          <Alert status="error">
            <AlertIcon />
            {error}
          </Alert>
        )}

        {entities.length === 0 ? (
          <Alert status="success">
            <AlertIcon />
            ✅ Aucune entité non cataloguée ! Toutes les entités sont normalisées.
          </Alert>
        ) : (
          <>
            <Alert status="info">
              <AlertIcon />
              {entities.length} entité{entities.length > 1 ? "s" : ""} non cataloguée{entities.length > 1 ? "s" : ""} détectée{entities.length > 1 ? "s" : ""}.
            </Alert>

            <Box overflowX="auto" bg="white" borderRadius="md" border="1px" borderColor="gray.200">
              <Table>
                <Thead>
                  <Tr>
                    <Th>Nom Brut</Th>
                    <Th>Type</Th>
                    <Th>Occurrences</Th>
                    <Th>Première Détection</Th>
                    <Th>Tenants</Th>
                    <Th>Actions</Th>
                  </Tr>
                </Thead>
                <Tbody>
                  {entities.map((entity, idx) => (
                    <Tr key={idx}>
                      <Td>
                        <Text fontWeight="bold">{entity.raw_name}</Text>
                        {entity.suggested_entity_id && (
                          <Text fontSize="xs" color="gray.500">
                            Suggestion: {entity.suggested_entity_id}
                          </Text>
                        )}
                      </Td>
                      <Td>
                        <Badge colorScheme="blue">{entity.entity_type}</Badge>
                      </Td>
                      <Td>
                        <Badge colorScheme={entity.occurrences > 5 ? "red" : "gray"}>
                          {entity.occurrences}
                        </Badge>
                      </Td>
                      <Td fontSize="sm">
                        {new Date(entity.first_seen).toLocaleString("fr-FR")}
                      </Td>
                      <Td>
                        <HStack>
                          {entity.tenants.map((tenant) => (
                            <Badge key={tenant}>{tenant}</Badge>
                          ))}
                        </HStack>
                      </Td>
                      <Td>
                        <HStack>
                          <IconButton
                            aria-label="Approuver"
                            icon={<FiCheckCircle />}
                            size="sm"
                            colorScheme="green"
                            onClick={() => handleOpenApprove(entity)}
                          />
                          <IconButton
                            aria-label="Rejeter"
                            icon={<FiXCircle />}
                            size="sm"
                            colorScheme="red"
                            onClick={() => handleReject(entity)}
                          />
                        </HStack>
                      </Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>
            </Box>
          </>
        )}
      </VStack>

      <Modal isOpen={isOpen} onClose={onClose} size="lg">
        <ModalOverlay />
        <ModalContent>
          <ModalHeader>Approuver Entité Non Cataloguée</ModalHeader>
          <ModalCloseButton />
          <ModalBody>
            {selectedEntity && (
              <VStack spacing={4}>
                <Alert status="info">
                  <AlertIcon />
                  <Text fontSize="sm">
                    Nom brut : <strong>{selectedEntity.raw_name}</strong>
                    <br />
                    Ce nom sera automatiquement ajouté aux aliases.
                  </Text>
                </Alert>

                <FormControl isRequired>
                  <FormLabel>Entity ID</FormLabel>
                  <Input
                    value={formData.entity_id}
                    onChange={(e) =>
                      setFormData({ ...formData, entity_id: e.target.value.toUpperCase() })
                    }
                    placeholder="CUSTOM_LOAD_BALANCER"
                  />
                </FormControl>

                <FormControl isRequired>
                  <FormLabel>Nom Canonique</FormLabel>
                  <Input
                    value={formData.canonical_name}
                    onChange={(e) =>
                      setFormData({ ...formData, canonical_name: e.target.value })
                    }
                  />
                </FormControl>

                <FormControl>
                  <FormLabel>Aliases Additionnels</FormLabel>
                  <Textarea
                    value={formData.aliases}
                    onChange={(e) =>
                      setFormData({ ...formData, aliases: e.target.value })
                    }
                    placeholder="CLB, custom-lb"
                  />
                </FormControl>

                <FormControl>
                  <FormLabel>Catégorie</FormLabel>
                  <Input
                    value={formData.category}
                    onChange={(e) =>
                      setFormData({ ...formData, category: e.target.value })
                    }
                  />
                </FormControl>

                <FormControl>
                  <FormLabel>Vendor</FormLabel>
                  <Input
                    value={formData.vendor}
                    onChange={(e) =>
                      setFormData({ ...formData, vendor: e.target.value })
                    }
                  />
                </FormControl>
              </VStack>
            )}
          </ModalBody>
          <ModalFooter>
            <Button mr={3} onClick={onClose}>Annuler</Button>
            <Button
              colorScheme="green"
              onClick={handleApprove}
              isDisabled={!formData.entity_id || !formData.canonical_name}
            >
              Approuver et Ajouter
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
    </Container>
  );
}
