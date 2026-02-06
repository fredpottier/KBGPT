'use client'

import {
  Box,
  VStack,
  HStack,
  Text,
  Badge,
  Divider,
  Button,
  Icon,
  Tabs,
  TabList,
  TabPanels,
  Tab,
  TabPanel,
  Textarea,
  useClipboard,
} from '@chakra-ui/react'
import { FiCopy, FiCheck, FiArrowRight, FiEdit3 } from 'react-icons/fi'
import type { CorrectionResult } from '@/types/verification'

interface CorrectionViewProps {
  original: string
  corrected: string
  changes: CorrectionResult['changes']
}

export function CorrectionView({ original, corrected, changes }: CorrectionViewProps) {
  const { hasCopied, onCopy } = useClipboard(corrected)

  return (
    <Box
      bg="bg.secondary"
      rounded="xl"
      border="1px solid"
      borderColor="border.default"
      overflow="hidden"
    >
      {/* Header */}
      <HStack
        justify="space-between"
        p={4}
        bg="bg.tertiary"
        borderBottom="1px solid"
        borderColor="border.default"
      >
        <HStack spacing={2}>
          <Icon as={FiEdit3} color="brand.500" />
          <Text fontWeight="bold" color="text.primary">
            Texte corrigé
          </Text>
          <Badge colorScheme="green" variant="subtle">
            {changes.length} correction{changes.length > 1 ? 's' : ''}
          </Badge>
        </HStack>
        <Button
          size="sm"
          leftIcon={hasCopied ? <FiCheck /> : <FiCopy />}
          onClick={onCopy}
          colorScheme={hasCopied ? 'green' : 'gray'}
          variant="outline"
        >
          {hasCopied ? 'Copié' : 'Copier'}
        </Button>
      </HStack>

      <Tabs variant="soft-rounded" colorScheme="brand" p={4}>
        <TabList mb={4}>
          <Tab>Texte corrigé</Tab>
          <Tab>Liste des corrections ({changes.length})</Tab>
          <Tab>Comparaison</Tab>
        </TabList>

        <TabPanels>
          {/* Corrected text */}
          <TabPanel p={0}>
            <Box
              bg="bg.primary"
              p={4}
              rounded="lg"
              border="1px solid"
              borderColor="border.default"
              maxH="400px"
              overflowY="auto"
            >
              <Text
                whiteSpace="pre-wrap"
                lineHeight="1.8"
                color="text.primary"
                fontSize="md"
              >
                {corrected}
              </Text>
            </Box>
          </TabPanel>

          {/* Changes list */}
          <TabPanel p={0}>
            <VStack align="stretch" spacing={3} maxH="400px" overflowY="auto">
              {changes.length > 0 ? (
                changes.map((change, i) => (
                  <Box
                    key={i}
                    p={3}
                    bg="bg.primary"
                    rounded="lg"
                    border="1px solid"
                    borderColor="border.default"
                  >
                    <HStack mb={2}>
                      <Badge colorScheme="gray" size="sm">#{i + 1}</Badge>
                    </HStack>

                    <VStack align="stretch" spacing={2}>
                      {/* Original */}
                      <Box>
                        <Text fontSize="xs" color="text.muted" mb={1}>
                          Original
                        </Text>
                        <Text
                          fontSize="sm"
                          color="red.400"
                          bg="rgba(239, 68, 68, 0.1)"
                          p={2}
                          rounded="md"
                          textDecoration="line-through"
                        >
                          {change.original}
                        </Text>
                      </Box>

                      <HStack justify="center" color="text.muted">
                        <Icon as={FiArrowRight} />
                      </HStack>

                      {/* Corrected */}
                      <Box>
                        <Text fontSize="xs" color="text.muted" mb={1}>
                          Corrigé
                        </Text>
                        <Text
                          fontSize="sm"
                          color="green.400"
                          bg="rgba(34, 197, 94, 0.1)"
                          p={2}
                          rounded="md"
                        >
                          {change.corrected}
                        </Text>
                      </Box>

                      {/* Reason */}
                      {change.reason && (
                        <Box>
                          <Text fontSize="xs" color="text.muted" mb={1}>
                            Raison
                          </Text>
                          <Text fontSize="sm" color="text.secondary" fontStyle="italic">
                            {change.reason}
                          </Text>
                        </Box>
                      )}
                    </VStack>
                  </Box>
                ))
              ) : (
                <Box p={4} textAlign="center" color="text.muted">
                  <Text>Aucune correction détaillée disponible.</Text>
                </Box>
              )}
            </VStack>
          </TabPanel>

          {/* Side by side comparison */}
          <TabPanel p={0}>
            <HStack align="stretch" spacing={4}>
              <Box flex="1">
                <Text fontSize="sm" fontWeight="semibold" color="text.muted" mb={2}>
                  Original
                </Text>
                <Box
                  bg="rgba(239, 68, 68, 0.05)"
                  p={3}
                  rounded="lg"
                  border="1px solid"
                  borderColor="red.200"
                  maxH="300px"
                  overflowY="auto"
                >
                  <Text
                    whiteSpace="pre-wrap"
                    lineHeight="1.7"
                    color="text.secondary"
                    fontSize="sm"
                  >
                    {original}
                  </Text>
                </Box>
              </Box>

              <Box flex="1">
                <Text fontSize="sm" fontWeight="semibold" color="text.muted" mb={2}>
                  Corrigé
                </Text>
                <Box
                  bg="rgba(34, 197, 94, 0.05)"
                  p={3}
                  rounded="lg"
                  border="1px solid"
                  borderColor="green.200"
                  maxH="300px"
                  overflowY="auto"
                >
                  <Text
                    whiteSpace="pre-wrap"
                    lineHeight="1.7"
                    color="text.primary"
                    fontSize="sm"
                  >
                    {corrected}
                  </Text>
                </Box>
              </Box>
            </HStack>
          </TabPanel>
        </TabPanels>
      </Tabs>
    </Box>
  )
}
