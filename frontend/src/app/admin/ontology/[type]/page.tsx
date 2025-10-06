"use client";

import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  Box,
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
} from "@chakra-ui/react";
import { FiArrowLeft, FiPlus, FiEdit2, FiTrash2 } from "react-icons/fi";
import Link from "next/link";

interface Entity {
  entity_type: string;
  entity_id: string;
  canonical_name: string;
  aliases: string[];
  category: string | null;
  vendor: string | null;
}

export default function CatalogDetailPage() {
  const params = useParams();
  const router = useRouter();
  const entityType = (params.type as string || "").toUpperCase();

  const [entities, setEntities] = useState<Entity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const { isOpen, onOpen, onClose } = useDisclosure();
  const [editingEntity, setEditingEntity] = useState<Entity | null>(null);
  const [formData, setFormData] = useState({
    entity_id: "",
    canonical_name: "",
    aliases: "",
    category: "",
    vendor: "",
  });

  useEffect(() => {
    if (entityType) {
      loadEntities();
    }
  }, [entityType]);

  const loadEntities = async () => {
    try {
      setLoading(true);
      const res = await fetch(
        `http://localhost:8000/api/ontology/catalogs/${entityType}/entities`
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: Entity[] = await res.json();
      setEntities(data);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleOpenDialog = (entity?: Entity) => {
    if (entity) {
      setEditingEntity(entity);
      setFormData({
        entity_id: entity.entity_id,
        canonical_name: entity.canonical_name,
        aliases: entity.aliases.join(", "),
        category: entity.category || "",
        vendor: entity.vendor || "",
      });
    } else {
      setEditingEntity(null);
      setFormData({ entity_id: "", canonical_name: "", aliases: "", category: "", vendor: "" });
    }
    onOpen();
  };

  const handleSave = async () => {
    try {
      const aliases = formData.aliases.split(",").map((a) => a.trim()).filter((a) => a);

      if (editingEntity) {
        await fetch(
          `http://localhost:8000/api/ontology/catalogs/${entityType}/entities/${editingEntity.entity_id}`,
          {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              canonical_name: formData.canonical_name,
              aliases,
              category: formData.category || null,
              vendor: formData.vendor || null,
            }),
          }
        );
      } else {
        await fetch(`http://localhost:8000/api/ontology/catalogs/entities`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            entity_type: entityType,
            entity_id: formData.entity_id,
            canonical_name: formData.canonical_name,
            aliases,
            category: formData.category || null,
            vendor: formData.vendor || null,
          }),
        });
      }

      onClose();
      loadEntities();
    } catch (err: any) {
      alert(err.message);
    }
  };

  const handleDelete = async (entity: Entity) => {
    if (!confirm(`Supprimer "${entity.canonical_name}" ?`)) return;
    try {
      await fetch(
        `http://localhost:8000/api/ontology/catalogs/${entityType}/entities/${entity.entity_id}`,
        { method: "DELETE" }
      );
      loadEntities();
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
            <Heading size="lg">Catalogue : {entityType}</Heading>
          </HStack>
          <Button leftIcon={<FiPlus />} colorScheme="blue" onClick={() => handleOpenDialog()}>
            Nouvelle Entité
          </Button>
        </HStack>

        {error && (
          <Alert status="error">
            <AlertIcon />
            {error}
          </Alert>
        )}

        <Box overflowX="auto" bg="white" borderRadius="md" border="1px" borderColor="gray.200">
          <Table>
            <Thead>
              <Tr>
                <Th>Entity ID</Th>
                <Th>Nom Canonique</Th>
                <Th>Aliases</Th>
                <Th>Catégorie</Th>
                <Th>Vendor</Th>
                <Th>Actions</Th>
              </Tr>
            </Thead>
            <Tbody>
              {entities.map((entity) => (
                <Tr key={entity.entity_id}>
                  <Td fontFamily="mono" fontSize="sm">{entity.entity_id}</Td>
                  <Td fontWeight="bold">{entity.canonical_name}</Td>
                  <Td>
                    <HStack flexWrap="wrap">
                      {entity.aliases.slice(0, 3).map((alias, idx) => (
                        <Badge key={idx}>{alias}</Badge>
                      ))}
                      {entity.aliases.length > 3 && (
                        <Badge colorScheme="gray">+{entity.aliases.length - 3}</Badge>
                      )}
                    </HStack>
                  </Td>
                  <Td>{entity.category && <Badge colorScheme="blue">{entity.category}</Badge>}</Td>
                  <Td>{entity.vendor && <Badge variant="outline">{entity.vendor}</Badge>}</Td>
                  <Td>
                    <HStack>
                      <IconButton
                        aria-label="Modifier"
                        icon={<FiEdit2 />}
                        size="sm"
                        onClick={() => handleOpenDialog(entity)}
                      />
                      <IconButton
                        aria-label="Supprimer"
                        icon={<FiTrash2 />}
                        size="sm"
                        colorScheme="red"
                        onClick={() => handleDelete(entity)}
                      />
                    </HStack>
                  </Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        </Box>
      </VStack>

      <Modal isOpen={isOpen} onClose={onClose} size="lg">
        <ModalOverlay />
        <ModalContent>
          <ModalHeader>{editingEntity ? "Modifier Entité" : "Nouvelle Entité"}</ModalHeader>
          <ModalCloseButton />
          <ModalBody>
            <VStack spacing={4}>
              <FormControl isRequired>
                <FormLabel>Entity ID</FormLabel>
                <Input
                  value={formData.entity_id}
                  onChange={(e) => setFormData({ ...formData, entity_id: e.target.value.toUpperCase() })}
                  isDisabled={!!editingEntity}
                  placeholder="LOAD_BALANCER"
                />
              </FormControl>
              <FormControl isRequired>
                <FormLabel>Nom Canonique</FormLabel>
                <Input
                  value={formData.canonical_name}
                  onChange={(e) => setFormData({ ...formData, canonical_name: e.target.value })}
                />
              </FormControl>
              <FormControl>
                <FormLabel>Aliases (séparés par virgule)</FormLabel>
                <Textarea
                  value={formData.aliases}
                  onChange={(e) => setFormData({ ...formData, aliases: e.target.value })}
                  placeholder="LB, LoadBalancer, load-balancer"
                />
              </FormControl>
              <FormControl>
                <FormLabel>Catégorie</FormLabel>
                <Input
                  value={formData.category}
                  onChange={(e) => setFormData({ ...formData, category: e.target.value })}
                />
              </FormControl>
              <FormControl>
                <FormLabel>Vendor</FormLabel>
                <Input
                  value={formData.vendor}
                  onChange={(e) => setFormData({ ...formData, vendor: e.target.value })}
                />
              </FormControl>
            </VStack>
          </ModalBody>
          <ModalFooter>
            <Button mr={3} onClick={onClose}>Annuler</Button>
            <Button
              colorScheme="blue"
              onClick={handleSave}
              isDisabled={!formData.canonical_name || (!editingEntity && !formData.entity_id)}
            >
              {editingEntity ? "Modifier" : "Créer"}
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
    </Container>
  );
}
