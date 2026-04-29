'use client';

import {
  FormControl,
  FormLabel,
  Select,
  Input,
  VStack,
  HStack,
  Button,
  Text,
  Alert,
  AlertIcon,
  AlertTitle,
  AlertDescription,
  Modal,
  ModalOverlay,
  ModalContent,
  ModalHeader,
  ModalFooter,
  ModalBody,
  ModalCloseButton,
  useDisclosure,
  Spinner,
  Badge,
  Box,
} from '@chakra-ui/react';
import { useState, useEffect, useCallback } from 'react';
import { useToast } from '@chakra-ui/react';
import { authService } from '@/lib/auth';

interface SAPSolution {
  name: string;
  id: string;
}

interface SAPSolutionSelectorProps {
  value: string;
  onChange: (value: string) => void;
  label?: string;
  placeholder?: string;
  isRequired?: boolean;
  onlyWithChunks?: boolean; // Nouveau prop pour filtrer les solutions avec chunks
  extendSearchToKb?: boolean; // Nouveau prop pour la recherche étendue
}

export default function SAPSolutionSelector({
  value,
  onChange,
  label = "Solution SAP",
  placeholder = "Sélectionner une solution...",
  isRequired = false,
  onlyWithChunks = false,
  extendSearchToKb = false
}: SAPSolutionSelectorProps) {
  const [solutions, setSolutions] = useState<SAPSolution[]>([]);
  const [isLoadingSolutions, setIsLoadingSolutions] = useState(true);
  const [customInput, setCustomInput] = useState('');
  const [isResolvingCustom, setIsResolvingCustom] = useState(false);
  const [resolvedSolution, setResolvedSolution] = useState<{
    canonical_name: string;
    solution_id: string;
    original_input: string;
  } | null>(null);

  const { isOpen, onOpen, onClose } = useDisclosure();
  const toast = useToast();

  const loadSolutions = useCallback(async () => {
    try {
      // Get JWT token from auth service
      const token = authService.getAccessToken();

      if (!token) {
        toast({
          title: 'Non authentifié',
          description: 'Veuillez vous reconnecter',
          status: 'error',
          duration: 3000,
        });
        setIsLoadingSolutions(false);
        return;
      }

      let endpoint = '/api/sap-solutions';

      if (onlyWithChunks) {
        endpoint = `/api/sap-solutions/with-chunks?extend_search=${extendSearchToKb}`;
      }

      const response = await fetch(endpoint, {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });

      if (!response.ok) {
        throw new Error('Erreur lors du chargement des solutions');
      }

      const data = await response.json();
      setSolutions(data.solutions || []);
    } catch (error) {
      console.error('Erreur chargement solutions:', error);
      toast({
        title: 'Erreur',
        description: 'Impossible de charger les solutions SAP',
        status: 'error',
        duration: 3000,
      });
    } finally {
      setIsLoadingSolutions(false);
    }
  }, [toast, onlyWithChunks, extendSearchToKb]);

  // Charger les solutions au montage
  useEffect(() => {
    loadSolutions();
  }, [loadSolutions]);

  const handleSolutionChange = (selectedValue: string) => {
    if (selectedValue === 'custom') {
      onOpen(); // Ouvrir la modal pour solution personnalisée
    } else {
      onChange(selectedValue);
    }
  };

  const handleCustomSolutionResolve = async () => {
    if (!customInput.trim()) {
      toast({
        title: 'Champ requis',
        description: 'Veuillez saisir le nom de la solution',
        status: 'warning',
        duration: 3000,
      });
      return;
    }

    setIsResolvingCustom(true);
    try {
      // Get JWT token from auth service
      const token = authService.getAccessToken();

      if (!token) {
        toast({
          title: 'Non authentifié',
          description: 'Veuillez vous reconnecter',
          status: 'error',
          duration: 3000,
        });
        setIsResolvingCustom(false);
        return;
      }

      const response = await fetch('/api/sap-solutions/resolve', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ solution_input: customInput }),
      });

      if (!response.ok) {
        throw new Error('Erreur lors de la résolution');
      }

      const data = await response.json();
      setResolvedSolution(data);

    } catch (error) {
      console.error('Erreur résolution:', error);
      toast({
        title: 'Erreur de résolution',
        description: 'Impossible de résoudre la solution SAP',
        status: 'error',
        duration: 3000,
      });
    } finally {
      setIsResolvingCustom(false);
    }
  };

  const handleConfirmCustomSolution = () => {
    if (resolvedSolution) {
      onChange(resolvedSolution.canonical_name);
      toast({
        title: 'Solution ajoutée',
        description: `"${resolvedSolution.canonical_name}" a été ajoutée à votre sélection`,
        status: 'success',
        duration: 3000,
      });

      // Recharger la liste des solutions pour inclure la nouvelle
      loadSolutions();
    }
    onClose();
    setCustomInput('');
    setResolvedSolution(null);
  };

  const handleCancelCustomSolution = () => {
    onClose();
    setCustomInput('');
    setResolvedSolution(null);
  };

  // Trouver la solution sélectionnée pour l'affichage
  const selectedSolution = solutions.find(s => s.name === value);

  return (
    <>
      <FormControl isRequired={isRequired}>
        <FormLabel>{label}</FormLabel>
        <VStack spacing={2} align="stretch">
          <Select
            value={selectedSolution ? selectedSolution.name : ''}
            onChange={(e) => handleSolutionChange(e.target.value)}
            placeholder={isLoadingSolutions ? "Chargement..." : placeholder}
            isDisabled={isLoadingSolutions}
          >
            {solutions.map((solution) => (
              <option key={solution.id} value={solution.name}>
                {solution.name}
              </option>
            ))}
            <option value="custom" style={{ fontStyle: 'italic', color: '#666' }}>
              ➕ Autre solution (non listée)
            </option>
          </Select>

          {isLoadingSolutions && (
            <HStack>
              <Spinner size="sm" />
              <Text fontSize="sm" color="fg.muted">
                Chargement des solutions SAP...
              </Text>
            </HStack>
          )}

          {value && (
            <Box p={2} bg="green.50" borderRadius="md" border="1px solid" borderColor="green.200">
              <Text fontSize="sm" color="green.700">
                <strong>Sélectionné :</strong> {value}
              </Text>
            </Box>
          )}
        </VStack>
      </FormControl>

      {/* Modal pour solution personnalisée */}
      <Modal isOpen={isOpen} onClose={handleCancelCustomSolution} size="lg">
        <ModalOverlay />
        <ModalContent>
          <ModalHeader>Ajouter une nouvelle solution SAP</ModalHeader>
          <ModalCloseButton />
          <ModalBody>
            <VStack spacing={4} align="stretch">
              <Alert status="info">
                <AlertIcon />
                <Box>
                  <AlertTitle>Solution non listée</AlertTitle>
                  <AlertDescription>
                    Saisissez le nom ou l'abréviation de la solution SAP.
                    Notre système utilisera l'IA pour trouver le nom officiel.
                  </AlertDescription>
                </Box>
              </Alert>

              <FormControl>
                <FormLabel>Nom de la solution</FormLabel>
                <Input
                  value={customInput}
                  onChange={(e) => setCustomInput(e.target.value)}
                  placeholder="Ex: S4H, SAP EWM, SuccessFactors..."
                  onKeyPress={(e) => {
                    if (e.key === 'Enter' && !isResolvingCustom) {
                      handleCustomSolutionResolve();
                    }
                  }}
                />
              </FormControl>

              {!resolvedSolution && (
                <Button
                  colorScheme="blue"
                  onClick={handleCustomSolutionResolve}
                  isLoading={isResolvingCustom}
                  loadingText="Résolution en cours..."
                  isDisabled={!customInput.trim()}
                >
                  🤖 Résoudre avec l'IA
                </Button>
              )}

              {resolvedSolution && (
                <Alert status="success">
                  <AlertIcon />
                  <Box>
                    <AlertTitle>Solution résolue !</AlertTitle>
                    <AlertDescription>
                      <strong>Saisie :</strong> {resolvedSolution.original_input}
                      <br />
                      <strong>Nom officiel :</strong> {resolvedSolution.canonical_name}
                      <br />
                      <Badge colorScheme="green" mt={1}>Nouvelle solution détectée</Badge>
                    </AlertDescription>
                  </Box>
                </Alert>
              )}
            </VStack>
          </ModalBody>

          <ModalFooter>
            <Button variant="ghost" mr={3} onClick={handleCancelCustomSolution}>
              Annuler
            </Button>
            {resolvedSolution && (
              <Button colorScheme="blue" onClick={handleConfirmCustomSolution}>
                Confirmer et utiliser
              </Button>
            )}
          </ModalFooter>
        </ModalContent>
      </Modal>
    </>
  );
}