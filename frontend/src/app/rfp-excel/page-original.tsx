'use client';

import {
  Box,
  Container,
  Heading,
  Tab,
  TabList,
  TabPanel,
  TabPanels,
  Tabs,
  VStack,
  Text,
  Card,
  CardBody,
  Icon,
  HStack,
  Button,
  FormControl,
  FormLabel,
  Input,
  Select,
  Textarea,
  useToast,
  Alert,
  AlertIcon,
  AlertTitle,
  AlertDescription,
  Progress,
  Badge,
  Table,
  Thead,
  Tbody,
  Tr,
  Th,
  Td,
  TableContainer,
} from '@chakra-ui/react';
import { FiUpload, FiFileText, FiDownload, FiInfo } from 'react-icons/fi';
import { useState, useCallback } from 'react';
import { useDropzone } from 'react-dropzone';

interface ExcelFile {
  file: File;
  metadata: {
    solution: string;
    client: string;
    source_date: string;
    question_col: string;
    answer_col: string;
  };
}

interface RfpFile {
  file: File;
  metadata: {
    solution: string;
    client: string;
    source_date: string;
  };
}

export default function RfpExcelPage() {
  const [qaFiles, setQaFiles] = useState<ExcelFile[]>([]);
  const [rfpFiles, setRfpFiles] = useState<RfpFile[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const toast = useToast();

  // Import Q/A handlers
  const onQaDropAccepted = useCallback((acceptedFiles: File[]) => {
    const excelFiles = acceptedFiles.filter(file =>
      file.name.endsWith('.xlsx') || file.name.endsWith('.xls')
    );

    const newFiles: ExcelFile[] = excelFiles.map(file => ({
      file,
      metadata: {
        solution: '',
        client: '',
        source_date: new Date().toISOString().split('T')[0],
        question_col: 'A',
        answer_col: 'B',
      }
    }));

    setQaFiles(prev => [...prev, ...newFiles]);
  }, []);

  const qaDropzone = useDropzone({
    onDropAccepted: onQaDropAccepted,
    accept: {
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
      'application/vnd.ms-excel': ['.xls']
    },
    multiple: true
  });

  const updateQaMetadata = (index: number, field: string, value: string) => {
    setQaFiles(prev => prev.map((item, i) =>
      i === index
        ? { ...item, metadata: { ...item.metadata, [field]: value } }
        : item
    ));
  };

  const removeQaFile = (index: number) => {
    setQaFiles(prev => prev.filter((_, i) => i !== index));
  };

  const submitQaImport = async () => {
    if (qaFiles.length === 0) {
      toast({
        title: 'Aucun fichier',
        description: 'Veuillez d&apos;abord ajouter des fichiers Excel',
        status: 'warning',
        duration: 3000,
      });
      return;
    }

    const incompleteFiles = qaFiles.filter(f =>
      !f.metadata.solution || !f.metadata.client
    );

    if (incompleteFiles.length > 0) {
      toast({
        title: 'Métadonnées incomplètes',
        description: 'Veuillez remplir la solution et le client pour tous les fichiers',
        status: 'error',
        duration: 3000,
      });
      return;
    }

    setIsUploading(true);
    try {
      for (const qaFile of qaFiles) {
        const formData = new FormData();
        formData.append('file', qaFile.file);
        formData.append('metadata', JSON.stringify(qaFile.metadata));

        const response = await fetch('/api/documents/upload-qa-excel', {
          method: 'POST',
          body: formData,
        });

        if (!response.ok) {
          throw new Error(`Erreur pour ${qaFile.file.name}`);
        }
      }

      toast({
        title: 'Import réussi',
        description: `${qaFiles.length} fichier(s) Excel Q/A importé(s)`,
        status: 'success',
        duration: 5000,
      });

      setQaFiles([]);
    } catch (error) {
      toast({
        title: 'Erreur d&apos;import',
        description: error instanceof Error ? error.message : 'Erreur inconnue',
        status: 'error',
        duration: 5000,
      });
    } finally {
      setIsUploading(false);
    }
  };

  // Fill RFP handlers
  const onRfpDropAccepted = useCallback((acceptedFiles: File[]) => {
    const excelFiles = acceptedFiles.filter(file =>
      file.name.endsWith('.xlsx') || file.name.endsWith('.xls')
    );

    const newFiles: RfpFile[] = excelFiles.map(file => ({
      file,
      metadata: {
        solution: '',
        client: '',
        source_date: new Date().toISOString().split('T')[0],
      }
    }));

    setRfpFiles(prev => [...prev, ...newFiles]);
  }, []);

  const rfpDropzone = useDropzone({
    onDropAccepted: onRfpDropAccepted,
    accept: {
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
      'application/vnd.ms-excel': ['.xls']
    },
    multiple: true
  });

  const updateRfpMetadata = (index: number, field: string, value: string) => {
    setRfpFiles(prev => prev.map((item, i) =>
      i === index
        ? { ...item, metadata: { ...item.metadata, [field]: value } }
        : item
    ));
  };

  const removeRfpFile = (index: number) => {
    setRfpFiles(prev => prev.filter((_, i) => i !== index));
  };

  const submitRfpFill = async () => {
    if (rfpFiles.length === 0) {
      toast({
        title: 'Aucun fichier',
        description: 'Veuillez d&apos;abord ajouter des fichiers RFP',
        status: 'warning',
        duration: 3000,
      });
      return;
    }

    const incompleteFiles = rfpFiles.filter(f =>
      !f.metadata.solution || !f.metadata.client
    );

    if (incompleteFiles.length > 0) {
      toast({
        title: 'Métadonnées incomplètes',
        description: 'Veuillez remplir la solution et le client pour tous les fichiers',
        status: 'error',
        duration: 3000,
      });
      return;
    }

    setIsUploading(true);
    try {
      for (const rfpFile of rfpFiles) {
        const formData = new FormData();
        formData.append('file', rfpFile.file);
        formData.append('metadata', JSON.stringify(rfpFile.metadata));

        const response = await fetch('/api/documents/fill-rfp-excel', {
          method: 'POST',
          body: formData,
        });

        if (!response.ok) {
          throw new Error(`Erreur pour ${rfpFile.file.name}`);
        }
      }

      toast({
        title: 'Traitement réussi',
        description: `${rfpFiles.length} fichier(s) RFP traité(s)`,
        status: 'success',
        duration: 5000,
      });

      setRfpFiles([]);
    } catch (error) {
      toast({
        title: 'Erreur de traitement',
        description: error instanceof Error ? error.message : 'Erreur inconnue',
        status: 'error',
        duration: 5000,
      });
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <Container maxW="6xl" py={8}>
      <VStack spacing={6} align="stretch">
        <Box>
          <Heading size="lg" mb={2}>RFP Excel</Heading>
          <Text color="gray.600">
            Gestion des fichiers Excel pour les RFP - Questions/Réponses et remplissage automatique
          </Text>
        </Box>

        <Tabs variant="enclosed" colorScheme="blue">
          <TabList>
            <Tab>
              <Icon as={FiUpload} mr={2} />
              Import Questions/Réponses
            </Tab>
            <Tab>
              <Icon as={FiFileText} mr={2} />
              Remplir RFP vide
            </Tab>
          </TabList>

          <TabPanels>
            {/* Import Q/A Tab */}
            <TabPanel p={0} pt={6}>
              <VStack spacing={6} align="stretch">
                <Alert status="info">
                  <AlertIcon />
                  <Box>
                    <AlertTitle>Import de Questions/Réponses</AlertTitle>
                    <AlertDescription>
                      Importez des fichiers Excel contenant des paires questions/réponses pour enrichir la base de connaissances RFP.
                    </AlertDescription>
                  </Box>
                </Alert>

                {/* Upload Zone */}
                <Card>
                  <CardBody>
                    <Box
                      {...qaDropzone.getRootProps()}
                      border="2px dashed"
                      borderColor={qaDropzone.isDragActive ? "blue.400" : "gray.300"}
                      borderRadius="lg"
                      p={8}
                      textAlign="center"
                      cursor="pointer"
                      bg={qaDropzone.isDragActive ? "blue.50" : "gray.50"}
                      transition="all 0.2s"
                      _hover={{ borderColor: "blue.400", bg: "blue.50" }}
                    >
                      <input {...qaDropzone.getInputProps()} />
                      <VStack spacing={3}>
                        <Icon as={FiUpload} boxSize={8} color="blue.400" />
                        <Text fontWeight="medium">
                          {qaDropzone.isDragActive
                            ? "Déposez les fichiers Excel ici"
                            : "Glissez-déposez des fichiers Excel ou cliquez pour parcourir"}
                        </Text>
                        <Text fontSize="sm" color="gray.500">
                          Formats acceptés: .xlsx, .xls
                        </Text>
                      </VStack>
                    </Box>
                  </CardBody>
                </Card>

                {/* Files List */}
                {qaFiles.length > 0 && (
                  <Card>
                    <CardBody>
                      <Heading size="md" mb={4}>Fichiers à importer ({qaFiles.length})</Heading>
                      <TableContainer>
                        <Table size="sm">
                          <Thead>
                            <Tr>
                              <Th>Fichier</Th>
                              <Th>Solution SAP</Th>
                              <Th>Client</Th>
                              <Th>Date</Th>
                              <Th>Col. Question</Th>
                              <Th>Col. Réponse</Th>
                              <Th>Actions</Th>
                            </Tr>
                          </Thead>
                          <Tbody>
                            {qaFiles.map((qaFile, index) => (
                              <Tr key={index}>
                                <Td>
                                  <Badge colorScheme="green">{qaFile.file.name}</Badge>
                                </Td>
                                <Td>
                                  <Input
                                    size="sm"
                                    placeholder="SAP S/4HANA..."
                                    value={qaFile.metadata.solution}
                                    onChange={(e) => updateQaMetadata(index, 'solution', e.target.value)}
                                  />
                                </Td>
                                <Td>
                                  <Input
                                    size="sm"
                                    placeholder="Nom du client"
                                    value={qaFile.metadata.client}
                                    onChange={(e) => updateQaMetadata(index, 'client', e.target.value)}
                                  />
                                </Td>
                                <Td>
                                  <Input
                                    size="sm"
                                    type="date"
                                    value={qaFile.metadata.source_date}
                                    onChange={(e) => updateQaMetadata(index, 'source_date', e.target.value)}
                                  />
                                </Td>
                                <Td>
                                  <Select
                                    size="sm"
                                    value={qaFile.metadata.question_col}
                                    onChange={(e) => updateQaMetadata(index, 'question_col', e.target.value)}
                                  >
                                    {['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'].map(col => (
                                      <option key={col} value={col}>{col}</option>
                                    ))}
                                  </Select>
                                </Td>
                                <Td>
                                  <Select
                                    size="sm"
                                    value={qaFile.metadata.answer_col}
                                    onChange={(e) => updateQaMetadata(index, 'answer_col', e.target.value)}
                                  >
                                    {['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'].map(col => (
                                      <option key={col} value={col}>{col}</option>
                                    ))}
                                  </Select>
                                </Td>
                                <Td>
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    colorScheme="red"
                                    onClick={() => removeQaFile(index)}
                                  >
                                    Supprimer
                                  </Button>
                                </Td>
                              </Tr>
                            ))}
                          </Tbody>
                        </Table>
                      </TableContainer>

                      <HStack mt={4} justify="flex-end">
                        <Button
                          colorScheme="blue"
                          onClick={submitQaImport}
                          isLoading={isUploading}
                          loadingText="Import en cours..."
                        >
                          Importer {qaFiles.length} fichier(s)
                        </Button>
                      </HStack>
                    </CardBody>
                  </Card>
                )}
              </VStack>
            </TabPanel>

            {/* Fill RFP Tab */}
            <TabPanel p={0} pt={6}>
              <VStack spacing={6} align="stretch">
                <Alert status="info">
                  <AlertIcon />
                  <Box>
                    <AlertTitle>Remplissage automatique de RFP</AlertTitle>
                    <AlertDescription>
                      Uploadez des fichiers RFP vides et le système les remplira automatiquement en utilisant la base de connaissances.
                    </AlertDescription>
                  </Box>
                </Alert>

                {/* Upload Zone */}
                <Card>
                  <CardBody>
                    <Box
                      {...rfpDropzone.getRootProps()}
                      border="2px dashed"
                      borderColor={rfpDropzone.isDragActive ? "green.400" : "gray.300"}
                      borderRadius="lg"
                      p={8}
                      textAlign="center"
                      cursor="pointer"
                      bg={rfpDropzone.isDragActive ? "green.50" : "gray.50"}
                      transition="all 0.2s"
                      _hover={{ borderColor: "green.400", bg: "green.50" }}
                    >
                      <input {...rfpDropzone.getInputProps()} />
                      <VStack spacing={3}>
                        <Icon as={FiFileText} boxSize={8} color="green.400" />
                        <Text fontWeight="medium">
                          {rfpDropzone.isDragActive
                            ? "Déposez les fichiers RFP ici"
                            : "Glissez-déposez des fichiers RFP Excel ou cliquez pour parcourir"}
                        </Text>
                        <Text fontSize="sm" color="gray.500">
                          Formats acceptés: .xlsx, .xls
                        </Text>
                      </VStack>
                    </Box>
                  </CardBody>
                </Card>

                {/* Files List */}
                {rfpFiles.length > 0 && (
                  <Card>
                    <CardBody>
                      <Heading size="md" mb={4}>Fichiers RFP à traiter ({rfpFiles.length})</Heading>
                      <TableContainer>
                        <Table size="sm">
                          <Thead>
                            <Tr>
                              <Th>Fichier</Th>
                              <Th>Solution SAP</Th>
                              <Th>Client</Th>
                              <Th>Date</Th>
                              <Th>Actions</Th>
                            </Tr>
                          </Thead>
                          <Tbody>
                            {rfpFiles.map((rfpFile, index) => (
                              <Tr key={index}>
                                <Td>
                                  <Badge colorScheme="orange">{rfpFile.file.name}</Badge>
                                </Td>
                                <Td>
                                  <Input
                                    size="sm"
                                    placeholder="SAP S/4HANA..."
                                    value={rfpFile.metadata.solution}
                                    onChange={(e) => updateRfpMetadata(index, 'solution', e.target.value)}
                                  />
                                </Td>
                                <Td>
                                  <Input
                                    size="sm"
                                    placeholder="Nom du client"
                                    value={rfpFile.metadata.client}
                                    onChange={(e) => updateRfpMetadata(index, 'client', e.target.value)}
                                  />
                                </Td>
                                <Td>
                                  <Input
                                    size="sm"
                                    type="date"
                                    value={rfpFile.metadata.source_date}
                                    onChange={(e) => updateRfpMetadata(index, 'source_date', e.target.value)}
                                  />
                                </Td>
                                <Td>
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    colorScheme="red"
                                    onClick={() => removeRfpFile(index)}
                                  >
                                    Supprimer
                                  </Button>
                                </Td>
                              </Tr>
                            ))}
                          </Tbody>
                        </Table>
                      </TableContainer>

                      <HStack mt={4} justify="flex-end">
                        <Button
                          colorScheme="green"
                          onClick={submitRfpFill}
                          isLoading={isUploading}
                          loadingText="Traitement en cours..."
                        >
                          Traiter {rfpFiles.length} fichier(s)
                        </Button>
                      </HStack>
                    </CardBody>
                  </Card>
                )}

                <Alert status="warning">
                  <AlertIcon />
                  <Box>
                    <AlertTitle>Note importante</AlertTitle>
                    <AlertDescription>
                      Le système utilisera la recherche cascade : d&apos;abord dans la collection Q/A RFP, puis dans la base de connaissances générale si nécessaire.
                    </AlertDescription>
                  </Box>
                </Alert>
              </VStack>
            </TabPanel>
          </TabPanels>
        </Tabs>
      </VStack>
    </Container>
  );
}