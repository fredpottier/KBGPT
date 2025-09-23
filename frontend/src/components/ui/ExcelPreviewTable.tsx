'use client';

import {
  Table,
  Thead,
  Tbody,
  Tr,
  Th,
  Td,
  TableContainer,
  Box,
  Text,
  VStack,
  HStack,
  Badge,
  Button,
  Alert,
  AlertIcon,
  AlertTitle,
  AlertDescription,
  Slider,
  SliderTrack,
  SliderFilledTrack,
  SliderThumb,
  FormControl,
  FormLabel,
  Flex,
  IconButton,
} from '@chakra-ui/react';
import { useState } from 'react';
import { FiChevronLeft, FiChevronRight, FiChevronUp, FiChevronDown } from 'react-icons/fi';

interface ExcelPreviewTableProps {
  sheetData: {
    name: string;
    sample_data: string[][];
    available_columns: { letter: string; index: number; non_empty_count: number; is_mostly_empty?: boolean }[];
    total_rows: number;
    total_columns: number;
  };
  onColumnSelect: (questionColumn: string | null, answerColumn: string | null) => void;
}

export default function ExcelPreviewTable({ sheetData, onColumnSelect }: ExcelPreviewTableProps) {
  const [selectedQuestionColumn, setSelectedQuestionColumn] = useState<number | null>(null);
  const [selectedAnswerColumn, setSelectedAnswerColumn] = useState<number | null>(null);

  // Navigation states
  const [startRow, setStartRow] = useState(0);
  const [startColumn, setStartColumn] = useState(0);

  // Constants
  const ROWS_TO_DISPLAY = 20;
  const COLUMNS_TO_DISPLAY = Math.min(6, sheetData.total_columns); // Maximum 6 colonnes affichées

  const handleColumnClick = (columnIndex: number) => {
    if (selectedQuestionColumn === columnIndex) {
      // Déselectionner la colonne question
      setSelectedQuestionColumn(null);
      onColumnSelect(null, selectedAnswerColumn ? getColumnLetter(selectedAnswerColumn) : null);
    } else if (selectedAnswerColumn === columnIndex) {
      // Déselectionner la colonne réponse
      setSelectedAnswerColumn(null);
      onColumnSelect(selectedQuestionColumn ? getColumnLetter(selectedQuestionColumn) : null, null);
    } else if (selectedQuestionColumn === null) {
      // Sélectionner comme colonne question
      setSelectedQuestionColumn(columnIndex);
      onColumnSelect(getColumnLetter(columnIndex), selectedAnswerColumn ? getColumnLetter(selectedAnswerColumn) : null);
    } else if (selectedAnswerColumn === null) {
      // Sélectionner comme colonne réponse
      setSelectedAnswerColumn(columnIndex);
      onColumnSelect(getColumnLetter(selectedQuestionColumn), getColumnLetter(columnIndex));
    } else {
      // Les deux colonnes sont déjà sélectionnées, remplacer la première sélectionnée
      setSelectedQuestionColumn(columnIndex);
      setSelectedAnswerColumn(null);
      onColumnSelect(getColumnLetter(columnIndex), null);
    }
  };

  const getColumnLetter = (index: number): string => {
    return String.fromCharCode(65 + index); // A=65
  };

  const getColumnStyle = (columnIndex: number) => {
    if (selectedQuestionColumn === columnIndex) {
      return {
        backgroundColor: 'blue.100',
        borderColor: 'blue.500',
        borderWidth: '2px',
      };
    }
    if (selectedAnswerColumn === columnIndex) {
      return {
        backgroundColor: 'yellow.100',
        borderColor: 'yellow.500',
        borderWidth: '2px',
      };
    }
    return {
      cursor: 'pointer',
      _hover: { backgroundColor: 'gray.50' },
    };
  };

  const reset = () => {
    setSelectedQuestionColumn(null);
    setSelectedAnswerColumn(null);
    onColumnSelect(null, null);
  };

  const isValidSelection = selectedQuestionColumn !== null && selectedAnswerColumn !== null;

  return (
    <VStack spacing={4} align="stretch">
      {/* Instructions */}
      <Alert status="info">
        <AlertIcon />
        <Box>
          <AlertTitle>Sélection des colonnes</AlertTitle>
          <AlertDescription>
            Cliquez sur une colonne pour la sélectionner :
            <br />• <Badge colorScheme="blue">1er clic</Badge> = Colonne Questions
            <br />• <Badge colorScheme="yellow">2ème clic</Badge> = Colonne Réponses (peut être vide)
            <br />• <Badge colorScheme="orange" variant="outline">Colonnes vides</Badge> = Disponibles pour les réponses RFP
            <br />• Re-cliquer pour désélectionner
          </AlertDescription>
        </Box>
      </Alert>

      {/* Statut de sélection */}
      <HStack>
        <Text fontWeight="medium">Sélection actuelle :</Text>
        {selectedQuestionColumn !== null && (
          <Badge colorScheme="blue" variant="solid">
            Questions: {getColumnLetter(selectedQuestionColumn)}
          </Badge>
        )}
        {selectedAnswerColumn !== null && (
          <Badge colorScheme="yellow" variant="solid">
            Réponses: {getColumnLetter(selectedAnswerColumn)}
          </Badge>
        )}
        {(selectedQuestionColumn !== null || selectedAnswerColumn !== null) && (
          <Button size="xs" variant="outline" onClick={reset}>
            Réinitialiser
          </Button>
        )}
      </HStack>

      {/* Contrôles de navigation */}
      <Box border="1px" borderColor="gray.200" borderRadius="md" p={4} bg="gray.50">
        <VStack spacing={4}>
          <Text fontWeight="medium" color="gray.700">Navigation dans le tableau</Text>

          <Flex wrap="wrap" gap={6} justify="center" align="center">
            {/* Navigation lignes */}
            <HStack spacing={3} minW="200px">
              <Text fontSize="sm" fontWeight="medium">Lignes:</Text>
              <IconButton
                size="sm"
                aria-label="Lignes précédentes"
                icon={<FiChevronUp />}
                onClick={() => setStartRow(Math.max(0, startRow - ROWS_TO_DISPLAY))}
                isDisabled={startRow === 0}
              />
              <Text fontSize="sm" color="gray.600">
                {startRow + 1}-{Math.min(startRow + ROWS_TO_DISPLAY, sheetData.total_rows)} / {sheetData.total_rows}
              </Text>
              <IconButton
                size="sm"
                aria-label="Lignes suivantes"
                icon={<FiChevronDown />}
                onClick={() => setStartRow(Math.min(sheetData.total_rows - ROWS_TO_DISPLAY, startRow + ROWS_TO_DISPLAY))}
                isDisabled={startRow + ROWS_TO_DISPLAY >= sheetData.total_rows}
              />
            </HStack>

            {/* Navigation colonnes */}
            <HStack spacing={3} minW="200px">
              <Text fontSize="sm" fontWeight="medium">Colonnes:</Text>
              <IconButton
                size="sm"
                aria-label="Colonnes précédentes"
                icon={<FiChevronLeft />}
                onClick={() => setStartColumn(Math.max(0, startColumn - COLUMNS_TO_DISPLAY))}
                isDisabled={startColumn === 0}
              />
              <Text fontSize="sm" color="gray.600">
                {getColumnLetter(startColumn)}-{getColumnLetter(Math.min(startColumn + COLUMNS_TO_DISPLAY - 1, sheetData.total_columns - 1))} / {getColumnLetter(sheetData.total_columns - 1)}
              </Text>
              <IconButton
                size="sm"
                aria-label="Colonnes suivantes"
                icon={<FiChevronRight />}
                onClick={() => setStartColumn(Math.min(sheetData.total_columns - COLUMNS_TO_DISPLAY, startColumn + COLUMNS_TO_DISPLAY))}
                isDisabled={startColumn + COLUMNS_TO_DISPLAY >= sheetData.total_columns}
              />
            </HStack>
          </Flex>

          {/* Sliders pour navigation rapide */}
          <Flex wrap="wrap" gap={6} justify="center" align="center" width="100%">
            {/* Slider lignes */}
            <FormControl maxW="250px">
              <FormLabel fontSize="sm">Défilement lignes</FormLabel>
              <Slider
                value={startRow}
                min={0}
                max={Math.max(0, sheetData.total_rows - ROWS_TO_DISPLAY)}
                step={1}
                onChange={setStartRow}
              >
                <SliderTrack>
                  <SliderFilledTrack />
                </SliderTrack>
                <SliderThumb />
              </Slider>
            </FormControl>

            {/* Slider colonnes */}
            <FormControl maxW="250px">
              <FormLabel fontSize="sm">Défilement colonnes</FormLabel>
              <Slider
                value={startColumn}
                min={0}
                max={Math.max(0, sheetData.total_columns - COLUMNS_TO_DISPLAY)}
                step={1}
                onChange={setStartColumn}
              >
                <SliderTrack>
                  <SliderFilledTrack />
                </SliderTrack>
                <SliderThumb />
              </Slider>
            </FormControl>
          </Flex>
        </VStack>
      </Box>

      {/* Tableau de prévisualisation */}
      <Box border="1px" borderColor="gray.200" borderRadius="md" maxHeight="500px" overflowY="auto" overflowX="hidden">
        <TableContainer>
          <Table size="sm" variant="simple">
            <Thead>
              <Tr>
                <Th width="40px" position="sticky" top="0" bg="white" zIndex={1}>
                  #
                </Th>
                {Array.from({ length: Math.min(COLUMNS_TO_DISPLAY, sheetData.total_columns - startColumn) }, (_, i) => {
                  const index = startColumn + i;
                  const columnInfo = sheetData.available_columns.find(col => col.index === index);
                  const isAvailable = !!columnInfo;
                  const isMostlyEmpty = columnInfo?.is_mostly_empty || false;

                  return (
                    <Th
                      key={index}
                      position="sticky"
                      top="0"
                      bg="white"
                      zIndex={1}
                      cursor={isAvailable ? 'pointer' : 'default'}
                      onClick={isAvailable ? () => handleColumnClick(index) : undefined}
                      {...(isAvailable ? getColumnStyle(index) : { opacity: 0.5 })}
                      minWidth="120px"
                      maxWidth="150px"
                    >
                      <VStack spacing={1}>
                        <Text fontSize="sm" fontWeight="bold">
                          {getColumnLetter(index)}
                        </Text>
                        {isAvailable && isMostlyEmpty && (
                          <Text fontSize="xs" color="orange.500" fontWeight="medium">
                            (vide)
                          </Text>
                        )}
                      </VStack>
                    </Th>
                  );
                })}
              </Tr>
            </Thead>
            <Tbody>
              {sheetData.sample_data
                .slice(startRow, startRow + ROWS_TO_DISPLAY)
                .map((row, rowIndex) => (
                <Tr key={rowIndex}>
                  <Td fontWeight="medium" bg="gray.50">
                    {startRow + rowIndex + 1}
                  </Td>
                  {row
                    .slice(startColumn, startColumn + COLUMNS_TO_DISPLAY)
                    .map((cell, cellIndex) => {
                      const actualColumnIndex = startColumn + cellIndex;
                      return (
                        <Td
                          key={actualColumnIndex}
                          {...getColumnStyle(actualColumnIndex)}
                          onClick={() => {
                            const columnInfo = sheetData.available_columns.find(col => col.index === actualColumnIndex);
                            if (columnInfo) handleColumnClick(actualColumnIndex);
                          }}
                          maxWidth="150px"
                          overflow="hidden"
                          textOverflow="ellipsis"
                          whiteSpace="nowrap"
                        >
                          <Text fontSize="sm" title={cell}>
                            {cell}
                          </Text>
                        </Td>
                      );
                    })}
                </Tr>
              ))}
            </Tbody>
          </Table>
        </TableContainer>
      </Box>

      {/* Validation */}
      {isValidSelection && (
        <Alert status="success">
          <AlertIcon />
          <AlertTitle>Sélection valide !</AlertTitle>
          <AlertDescription>
            Questions dans la colonne {getColumnLetter(selectedQuestionColumn!)},
            Réponses dans la colonne {getColumnLetter(selectedAnswerColumn!)}.
          </AlertDescription>
        </Alert>
      )}
    </VStack>
  );
}