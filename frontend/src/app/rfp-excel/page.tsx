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
  useToast,
  Alert,
  AlertIcon,
  AlertTitle,
  AlertDescription,
  Progress,
  Badge,
  Stepper,
  Step,
  StepIndicator,
  StepStatus,
  StepIcon,
  StepNumber,
  StepTitle,
  StepDescription,
  StepSeparator,
  useSteps,
  Spinner,
  Center,
  Checkbox,
} from '@chakra-ui/react';
import { FiUpload, FiFileText, FiDownload, FiInfo, FiEye, FiCheck } from 'react-icons/fi';
import { useState, useCallback } from 'react';
import { useDropzone } from 'react-dropzone';
import { useRouter } from 'next/navigation';
import ExcelPreviewTable from '@/components/ui/ExcelPreviewTable';
import SAPSolutionSelector from '@/components/ui/SAPSolutionSelector';
import { authService } from '@/lib/auth';
import { fetchWithAuth } from '@/lib/fetchWithAuth';

interface ExcelSheet {
  name: string;
  available_columns: { letter: string; index: number; non_empty_count: number }[];
  sample_data: string[][];
  total_rows: number;
  total_columns: number;
}

interface AnalysisResult {
  success: boolean;
  filename?: string;
  sheets: ExcelSheet[];
  column_headers?: string[];
  error?: string; // Pour les cas d'erreur
}

interface ExcelWorkflow {
  step: 'upload' | 'configure' | 'complete';
  file: File | null;
  analysisResult: AnalysisResult | null;
  selectedSheet: ExcelSheet | null;
  questionColumn: string | null;
  answerColumn: string | null;
  metadata: {
    solution: string;
    client: string;
    source_date: string;
  };
}

export default function RfpExcelPageImproved() {
  const [qaWorkflow, setQaWorkflow] = useState<ExcelWorkflow>({
    step: 'upload',
    file: null,
    analysisResult: null,
    selectedSheet: null,
    questionColumn: null,
    answerColumn: null,
    metadata: {
      solution: '',
      client: '',
      source_date: new Date().toISOString().split('T')[0],
    }
  });

  const [rfpWorkflow, setRfpWorkflow] = useState<ExcelWorkflow>({
    step: 'upload',
    file: null,
    analysisResult: null,
    selectedSheet: null,
    questionColumn: null,
    answerColumn: null,
    metadata: {
      solution: '',
      client: '',
      source_date: new Date().toISOString().split('T')[0],
    }
  });

  const [extendSearchToKb, setExtendSearchToKb] = useState<boolean>(false);
  const [solutionSelectorKey, setSolutionSelectorKey] = useState<number>(0);

  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isRedirecting, setIsRedirecting] = useState(false);
  const toast = useToast();
  const router = useRouter();

  const qaSteps = [
    { title: 'Upload', description: 'Analyser le fichier' },
    { title: 'Configuration', description: 'Sélectionner colonnes' },
    { title: 'Finalisation', description: 'Confirmer import' },
  ];

  const rfpSteps = [
    { title: 'Upload', description: 'Analyser le RFP vide' },
    { title: 'Configuration', description: 'Paramétrer recherche' },
    { title: 'Finalisation', description: 'Lancer remplissage' },
  ];

  const { activeStep: qaActiveStep } = useSteps({
    index: qaWorkflow.step === 'upload' ? 0 : qaWorkflow.step === 'configure' ? 1 : 2,
    count: qaSteps.length,
  });

  const { activeStep: rfpActiveStep } = useSteps({
    index: rfpWorkflow.step === 'upload' ? 0 : rfpWorkflow.step === 'configure' ? 1 : 2,
    count: rfpSteps.length,
  });

  // Analyse du fichier Excel
  const analyzeExcelFile = useCallback(async (file: File, workflowType: 'qa' | 'rfp') => {
    setIsAnalyzing(true);
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
        setIsAnalyzing(false);
        return;
      }

      const formData = new FormData();
      formData.append('file', file);

      const response = await fetchWithAuth('/api/documents/analyze-excel', {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        throw new Error('Erreur lors de l\'analyse du fichier');
      }

      const result: AnalysisResult = await response.json();

      if (!result.success) {
        throw new Error(result.error || 'Erreur d\'analyse');
      }

      const updateWorkflow = workflowType === 'qa' ? setQaWorkflow : setRfpWorkflow;
      updateWorkflow(prev => ({
        ...prev,
        step: 'configure',
        file,
        analysisResult: result,
        selectedSheet: result.sheets[0] || null,
      }));

      toast({
        title: 'Analyse réussie',
        description: `${result.sheets.length} onglet(s) analysé(s)`,
        status: 'success',
        duration: 3000,
      });

    } catch (error) {
      toast({
        title: 'Erreur d\'analyse',
        description: error instanceof Error ? error.message : 'Erreur inconnue',
        status: 'error',
        duration: 5000,
      });
    } finally {
      setIsAnalyzing(false);
    }
  }, [setQaWorkflow, setRfpWorkflow, toast]);

  // Upload Q/A handlers
  const onQaDropAccepted = useCallback((acceptedFiles: File[]) => {
    const excelFile = acceptedFiles.find(file =>
      file.name.endsWith('.xlsx') || file.name.endsWith('.xls')
    );

    if (excelFile) {
      analyzeExcelFile(excelFile, 'qa');
    }
  }, [analyzeExcelFile]);

  const qaDropzone = useDropzone({
    onDropAccepted: onQaDropAccepted,
    accept: {
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
      'application/vnd.ms-excel': ['.xls']
    },
    multiple: false
  });

  // RFP handlers
  const onRfpDropAccepted = useCallback((acceptedFiles: File[]) => {
    const excelFile = acceptedFiles.find(file =>
      file.name.endsWith('.xlsx') || file.name.endsWith('.xls')
    );

    if (excelFile) {
      analyzeExcelFile(excelFile, 'rfp');
    }
  }, [analyzeExcelFile]);

  const rfpDropzone = useDropzone({
    onDropAccepted: onRfpDropAccepted,
    accept: {
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
      'application/vnd.ms-excel': ['.xls']
    },
    multiple: false
  });

  // Sélection de feuille
  const handleSheetSelection = (sheetName: string, workflowType: 'qa' | 'rfp') => {
    const workflow = workflowType === 'qa' ? qaWorkflow : rfpWorkflow;
    const updateWorkflow = workflowType === 'qa' ? setQaWorkflow : setRfpWorkflow;

    const selectedSheet = workflow.analysisResult?.sheets.find(s => s.name === sheetName);
    if (selectedSheet) {
      updateWorkflow(prev => ({
        ...prev,
        selectedSheet,
        questionColumn: null,
        answerColumn: null,
      }));
    }
  };

  // Sélection de colonnes
  const handleColumnSelection = (questionColumn: string | null, answerColumn: string | null, workflowType: 'qa' | 'rfp') => {
    const updateWorkflow = workflowType === 'qa' ? setQaWorkflow : setRfpWorkflow;
    updateWorkflow(prev => ({
      ...prev,
      questionColumn,
      answerColumn,
    }));
  };

  // Mise à jour des métadonnées
  const updateMetadata = (field: string, value: string, workflowType: 'qa' | 'rfp') => {
    const updateWorkflow = workflowType === 'qa' ? setQaWorkflow : setRfpWorkflow;
    updateWorkflow(prev => ({
      ...prev,
      metadata: { ...prev.metadata, [field]: value }
    }));
  };

  // Finalisation
  const finalizeImport = async (workflowType: 'qa' | 'rfp') => {
    const workflow = workflowType === 'qa' ? qaWorkflow : rfpWorkflow;

    if (!workflow.file || !workflow.questionColumn || !workflow.answerColumn) {
      toast({
        title: 'Configuration incomplète',
        description: 'Veuillez sélectionner les colonnes et remplir les métadonnées',
        status: 'warning',
        duration: 3000,
      });
      return;
    }

    if (!workflow.metadata.solution || !workflow.metadata.client) {
      toast({
        title: 'Métadonnées incomplètes',
        description: 'Veuillez remplir la solution et le client',
        status: 'error',
        duration: 3000,
      });
      return;
    }

    setIsUploading(true);
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
        setIsUploading(false);
        return;
      }

      const formData = new FormData();
      formData.append('file', workflow.file);

      const metadata = {
        ...workflow.metadata,
        question_col: workflow.questionColumn,
        answer_col: workflow.answerColumn,
        sheet_name: workflow.selectedSheet?.name,
        ...(workflowType === 'rfp' && { extend_search_to_kb: extendSearchToKb })
      };

      formData.append('metadata', JSON.stringify(metadata));

      const endpoint = workflowType === 'qa'
        ? '/api/documents/upload-excel-qa'
        : '/api/documents/fill-rfp-excel';

      const response = await fetchWithAuth(endpoint, {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        throw new Error('Erreur lors du traitement');
      }

      toast({
        title: 'Traitement réussi',
        description: `Fichier ${workflowType === 'qa' ? 'Q/A importé' : 'RFP traité'}. Redirection vers le suivi...`,
        status: 'success',
        duration: 1500,
      });

      // Reset du workflow
      const updateWorkflow = workflowType === 'qa' ? setQaWorkflow : setRfpWorkflow;
      updateWorkflow({
        step: 'upload',
        file: null,
        analysisResult: null,
        selectedSheet: null,
        questionColumn: null,
        answerColumn: null,
        metadata: {
          solution: '',
          client: '',
          source_date: new Date().toISOString().split('T')[0],
        }
      });

      // Marquer la redirection et rediriger vers la page de suivi après un court délai
      setIsRedirecting(true);
      setTimeout(() => {
        router.push('/documents/status');
      }, 1500);

    } catch (error) {
      toast({
        title: 'Erreur de traitement',
        description: error instanceof Error ? error.message : 'Erreur inconnue',
        status: 'error',
        duration: 5000,
      });
    } finally {
      setIsUploading(false);
      setIsRedirecting(false);
    }
  };

  const resetWorkflow = (workflowType: 'qa' | 'rfp') => {
    const updateWorkflow = workflowType === 'qa' ? setQaWorkflow : setRfpWorkflow;
    updateWorkflow({
      step: 'upload',
      file: null,
      analysisResult: null,
      selectedSheet: null,
      questionColumn: null,
      answerColumn: null,
      metadata: {
        solution: '',
        client: '',
        source_date: new Date().toISOString().split('T')[0],
      }
    });
  };

  return (
    <Container maxW="7xl" py={8}>
      <VStack spacing={6} align="stretch">
        <Box>
          <Heading size="lg" mb={2}>RFP Excel</Heading>
          <Text color="gray.600">
            Analyse intelligente des fichiers Excel avec prévisualisation et sélection visuelle des colonnes
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
                {/* Stepper */}
                <Stepper index={qaActiveStep} colorScheme="blue">
                  {qaSteps.map((step, index) => (
                    <Step key={index}>
                      <StepIndicator>
                        <StepStatus
                          complete={<StepIcon />}
                          incomplete={<StepNumber />}
                          active={<StepNumber />}
                        />
                      </StepIndicator>
                      <Box flexShrink="0">
                        <StepTitle>{step.title}</StepTitle>
                        <StepDescription>{step.description}</StepDescription>
                      </Box>
                      <StepSeparator />
                    </Step>
                  ))}
                </Stepper>

                {/* Étape 1: Upload */}
                {qaWorkflow.step === 'upload' && (
                  <Card>
                    <CardBody>
                      <VStack spacing={4}>
                        <Alert status="info">
                          <AlertIcon />
                          <Box>
                            <AlertTitle>Analyse intelligente</AlertTitle>
                            <AlertDescription>
                              Le fichier sera analysé pour identifier automatiquement les onglets et colonnes disponibles.
                            </AlertDescription>
                          </Box>
                        </Alert>

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
                            {isAnalyzing ? (
                              <>
                                <Spinner size="lg" color="blue.400" />
                                <Text fontWeight="medium">Analyse en cours...</Text>
                              </>
                            ) : (
                              <>
                                <Icon as={FiUpload} boxSize={8} color="blue.400" />
                                <Text fontWeight="medium">
                                  {qaDropzone.isDragActive
                                    ? "Déposez le fichier Excel ici"
                                    : "Glissez-déposez un fichier Excel ou cliquez pour parcourir"}
                                </Text>
                              </>
                            )}
                            <Text fontSize="sm" color="gray.500">
                              Formats acceptés: .xlsx, .xls
                            </Text>
                          </VStack>
                        </Box>
                      </VStack>
                    </CardBody>
                  </Card>
                )}

                {/* Étape 2: Configuration */}
                {qaWorkflow.step === 'configure' && qaWorkflow.analysisResult && (
                  <Card>
                    <CardBody>
                      <VStack spacing={6}>
                        {/* Sélection d'onglet */}
                        <FormControl>
                          <FormLabel>Onglet à traiter</FormLabel>
                          <Select
                            value={qaWorkflow.selectedSheet?.name || ''}
                            onChange={(e) => handleSheetSelection(e.target.value, 'qa')}
                          >
                            {qaWorkflow.analysisResult.sheets.map((sheet) => (
                              <option key={sheet.name} value={sheet.name}>
                                {sheet.name} ({sheet.available_columns.length} colonnes disponibles, {sheet.total_rows} lignes)
                              </option>
                            ))}
                          </Select>
                        </FormControl>

                        {/* Métadonnées */}
                        <VStack spacing={4} align="stretch" width="full">
                          <SAPSolutionSelector
                            value={qaWorkflow.metadata.solution}
                            onChange={(value) => updateMetadata('solution', value, 'qa')}
                            label="Solution SAP"
                            placeholder="Sélectionner une solution SAP..."
                            isRequired={true}
                          />

                          <HStack spacing={4} align="start" width="full">
                            <FormControl>
                              <FormLabel>Client</FormLabel>
                              <Input
                                placeholder="Nom du client"
                                value={qaWorkflow.metadata.client}
                                onChange={(e) => updateMetadata('client', e.target.value, 'qa')}
                              />
                            </FormControl>
                            <FormControl>
                              <FormLabel>Date de création du fichier</FormLabel>
                              <Input
                                type="date"
                                value={qaWorkflow.metadata.source_date}
                                onChange={(e) => updateMetadata('source_date', e.target.value, 'qa')}
                              />
                            </FormControl>
                          </HStack>
                        </VStack>

                        {/* Prévisualisation et sélection des colonnes */}
                        {qaWorkflow.selectedSheet && (
                          <ExcelPreviewTable
                            sheetData={qaWorkflow.selectedSheet}
                            onColumnSelect={(questionCol, answerCol) =>
                              handleColumnSelection(questionCol, answerCol, 'qa')
                            }
                          />
                        )}

                        {/* Actions */}
                        <HStack justify="space-between" width="full">
                          <Button variant="outline" onClick={() => resetWorkflow('qa')}>
                            Recommencer
                          </Button>
                          <Button
                            colorScheme="blue"
                            onClick={() => finalizeImport('qa')}
                            isDisabled={!qaWorkflow.questionColumn || !qaWorkflow.answerColumn || !qaWorkflow.metadata.solution || !qaWorkflow.metadata.client || isRedirecting}
                            isLoading={isUploading || isRedirecting}
                            loadingText={isRedirecting ? "Redirection vers le suivi..." : "Import en cours..."}
                          >
                            Importer les Q/A
                          </Button>
                        </HStack>
                      </VStack>
                    </CardBody>
                  </Card>
                )}
              </VStack>
            </TabPanel>

            {/* Fill RFP Tab */}
            <TabPanel p={0} pt={6}>
              <VStack spacing={6} align="stretch">
                {/* Stepper RFP */}
                <Stepper index={rfpActiveStep} colorScheme="purple">
                  {rfpSteps.map((step, index) => (
                    <Step key={index}>
                      <StepIndicator>
                        <StepStatus
                          complete={<StepIcon />}
                          incomplete={<StepNumber />}
                          active={<StepNumber />}
                        />
                      </StepIndicator>
                      <Box flexShrink="0">
                        <StepTitle>{step.title}</StepTitle>
                        <StepDescription>{step.description}</StepDescription>
                      </Box>
                      <StepSeparator />
                    </Step>
                  ))}
                </Stepper>

                {/* Étape 1: Upload RFP */}
                {rfpWorkflow.step === 'upload' && (
                  <Card>
                    <CardBody>
                      <VStack spacing={4}>
                        <Alert status="info">
                          <AlertIcon />
                          <Box>
                            <AlertTitle>Remplissage automatique de RFP</AlertTitle>
                            <AlertDescription>
                              Uploadez un fichier Excel RFP vide avec des questions. Le système recherchera automatiquement les réponses dans votre base de connaissances.
                            </AlertDescription>
                          </Box>
                        </Alert>

                        <Box
                          {...rfpDropzone.getRootProps()}
                          border="2px dashed"
                          borderColor={rfpDropzone.isDragActive ? "purple.400" : "gray.300"}
                          borderRadius="lg"
                          p={8}
                          textAlign="center"
                          cursor="pointer"
                          bg={rfpDropzone.isDragActive ? "purple.50" : "gray.50"}
                          transition="all 0.2s"
                          _hover={{ borderColor: "purple.400", bg: "purple.50" }}
                        >
                          <input {...rfpDropzone.getInputProps()} />
                          <VStack spacing={3}>
                            {isAnalyzing ? (
                              <>
                                <Spinner size="lg" color="purple.400" />
                                <Text fontWeight="medium">Analyse en cours...</Text>
                              </>
                            ) : (
                              <>
                                <Icon as={FiFileText} boxSize={8} color="purple.400" />
                                <Text fontWeight="medium">
                                  {rfpDropzone.isDragActive
                                    ? "Déposez le fichier RFP Excel ici"
                                    : "Glissez-déposez un RFP Excel vide ou cliquez pour parcourir"}
                                </Text>
                              </>
                            )}
                            <Text fontSize="sm" color="gray.500">
                              Formats acceptés: .xlsx, .xls
                            </Text>
                          </VStack>
                        </Box>
                      </VStack>
                    </CardBody>
                  </Card>
                )}

                {/* Étape 2: Configuration RFP */}
                {rfpWorkflow.step === 'configure' && rfpWorkflow.analysisResult && (
                  <Card>
                    <CardBody>
                      <VStack spacing={6}>
                        {/* Sélection d'onglet */}
                        <FormControl>
                          <FormLabel>Onglet à traiter</FormLabel>
                          <Select
                            value={rfpWorkflow.selectedSheet?.name || ''}
                            onChange={(e) => handleSheetSelection(e.target.value, 'rfp')}
                          >
                            {rfpWorkflow.analysisResult.sheets.map((sheet) => (
                              <option key={sheet.name} value={sheet.name}>
                                {sheet.name} ({sheet.available_columns.length} colonnes disponibles, {sheet.total_rows} lignes)
                              </option>
                            ))}
                          </Select>
                        </FormControl>

                        {/* Métadonnées avec SolutionSelector filtré */}
                        <VStack spacing={4} align="stretch" width="full">
                          <HStack spacing={4} align="start" width="full">
                            <FormControl>
                              <FormLabel>Client</FormLabel>
                              <Input
                                placeholder="Nom du client"
                                value={rfpWorkflow.metadata.client}
                                onChange={(e) => updateMetadata('client', e.target.value, 'rfp')}
                              />
                            </FormControl>
                            <FormControl>
                              <FormLabel>Date de création du RFP</FormLabel>
                              <Input
                                type="date"
                                value={rfpWorkflow.metadata.source_date}
                                onChange={(e) => updateMetadata('source_date', e.target.value, 'rfp')}
                              />
                            </FormControl>
                          </HStack>

                          <SAPSolutionSelector
                            key={solutionSelectorKey}
                            value={rfpWorkflow.metadata.solution}
                            onChange={(value) => updateMetadata('solution', value, 'rfp')}
                            label="Solution SAP (avec base de connaissances)"
                            placeholder="Sélectionner une solution SAP..."
                            isRequired={true}
                            onlyWithChunks={true}
                            extendSearchToKb={extendSearchToKb}
                          />

                          {/* Option de recherche étendue */}
                          <Card bg="purple.50" borderColor="purple.200">
                            <CardBody>
                              <VStack spacing={3} align="stretch">
                                <Text fontWeight="medium" color="purple.700">Options de recherche</Text>
                                <Checkbox
                                  isChecked={extendSearchToKb}
                                  onChange={(e) => {
                                    setExtendSearchToKb(e.target.checked);
                                    setSolutionSelectorKey(prev => prev + 1); // Force le rechargement du SolutionSelector
                                  }}
                                  colorScheme="purple"
                                >
                                  <VStack align="start" spacing={1}>
                                    <Text fontSize="sm" fontWeight="medium">
                                      Étendre la recherche à la base de connaissances générale
                                    </Text>
                                    <Text fontSize="xs" color="gray.600">
                                      Par défaut, seules les Q/A RFP sont utilisées. Cochez pour inclure tous les documents.
                                    </Text>
                                  </VStack>
                                </Checkbox>
                              </VStack>
                            </CardBody>
                          </Card>
                        </VStack>

                        {/* Prévisualisation et sélection des colonnes */}
                        {rfpWorkflow.selectedSheet && (
                          <ExcelPreviewTable
                            sheetData={rfpWorkflow.selectedSheet}
                            onColumnSelect={(questionCol, answerCol) =>
                              handleColumnSelection(questionCol, answerCol, 'rfp')
                            }
                          />
                        )}

                        {/* Actions */}
                        <HStack justify="space-between" width="full">
                          <Button variant="outline" onClick={() => resetWorkflow('rfp')}>
                            Recommencer
                          </Button>
                          <Button
                            colorScheme="purple"
                            onClick={() => finalizeImport('rfp')}
                            isDisabled={!rfpWorkflow.questionColumn || !rfpWorkflow.answerColumn || !rfpWorkflow.metadata.solution || !rfpWorkflow.metadata.client || isRedirecting}
                            isLoading={isUploading || isRedirecting}
                            loadingText={isRedirecting ? "Redirection vers le suivi..." : "Lancement du remplissage..."}
                          >
                            Lancer le remplissage RFP
                          </Button>
                        </HStack>
                      </VStack>
                    </CardBody>
                  </Card>
                )}
              </VStack>
            </TabPanel>
          </TabPanels>
        </Tabs>
      </VStack>
    </Container>
  );
}