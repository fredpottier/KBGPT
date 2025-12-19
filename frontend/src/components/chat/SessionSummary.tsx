'use client'

import { useState } from 'react'
import {
  Box,
  Button,
  Card,
  CardBody,
  CardHeader,
  Heading,
  HStack,
  Icon,
  List,
  ListItem,
  ListIcon,
  Modal,
  ModalOverlay,
  ModalContent,
  ModalHeader,
  ModalBody,
  ModalFooter,
  ModalCloseButton,
  Select,
  Spinner,
  Text,
  useDisclosure,
  useToast,
  VStack,
  Badge,
  Divider,
  Tooltip,
  IconButton,
} from '@chakra-ui/react'
import {
  CheckCircleIcon,
  InfoIcon,
  WarningIcon,
  TimeIcon,
  DocumentIcon,
} from '@chakra-ui/icons'
import { useMutation } from '@tanstack/react-query'
import { api } from '@/lib/api'

interface KeyPoint {
  point: string
  source?: string
}

interface SessionSummaryData {
  session_id: string
  title: string
  generated_at: string
  format: string
  context: string
  key_points: KeyPoint[]
  actions: string[]
  unexplored_areas: string[]
  question_count: number
  sources_count: number
  duration_minutes?: number
  concepts_explored: string[]
  full_text: string
}

interface SessionSummaryProps {
  sessionId: string
  sessionTitle?: string
}

export default function SessionSummary({ sessionId, sessionTitle }: SessionSummaryProps) {
  const { isOpen, onOpen, onClose } = useDisclosure()
  const [format, setFormat] = useState<'business' | 'technical' | 'executive'>('business')
  const [summary, setSummary] = useState<SessionSummaryData | null>(null)
  const toast = useToast()

  const summaryMutation = useMutation({
    mutationFn: () => api.sessions.generateSummary(sessionId, format),
    onSuccess: (response) => {
      if (response.success && response.data) {
        setSummary(response.data as SessionSummaryData)
      } else {
        toast({
          title: 'Erreur',
          description: response.error || 'Impossible de generer le resume',
          status: 'error',
          duration: 3000,
        })
      }
    },
    onError: (error: any) => {
      toast({
        title: 'Erreur',
        description: error.message || 'Erreur lors de la generation',
        status: 'error',
        duration: 3000,
      })
    },
  })

  const handleOpenModal = () => {
    // Ouvre le modal sans lancer la génération - laisse l'utilisateur choisir le format
    setSummary(null)
    onOpen()
  }

  const handleFormatChange = (newFormat: 'business' | 'technical' | 'executive') => {
    setFormat(newFormat)
    // Ne pas lancer automatiquement - attendre le clic sur Générer
  }

  const handleGenerate = () => {
    setSummary(null)
    summaryMutation.mutate()
  }

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleString('fr-FR', {
      day: 'numeric',
      month: 'long',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  return (
    <>
      <Tooltip label="Generer un compte-rendu de la conversation">
        <IconButton
          aria-label="Generate summary"
          icon={<InfoIcon />}
          size="sm"
          variant="ghost"
          onClick={handleOpenModal}
        />
      </Tooltip>

      <Modal isOpen={isOpen} onClose={onClose} size="xl" scrollBehavior="inside">
        <ModalOverlay />
        <ModalContent maxW="800px">
          <ModalHeader>
            <HStack justify="space-between" align="center">
              <Text>Compte-rendu de session</Text>
              <Select
                value={format}
                onChange={(e) => handleFormatChange(e.target.value as any)}
                size="sm"
                w="150px"
                isDisabled={summaryMutation.isPending}
              >
                <option value="business">Business</option>
                <option value="technical">Technique</option>
                <option value="executive">Executive</option>
              </Select>
            </HStack>
          </ModalHeader>
          <ModalCloseButton />

          <ModalBody>
            {summaryMutation.isPending ? (
              <VStack py={10} spacing={4}>
                <Spinner size="xl" color="blue.500" />
                <Text color="gray.500">Generation du resume en cours...</Text>
                <Text fontSize="sm" color="gray.400">
                  Analyse de la conversation et extraction des points cles
                </Text>
              </VStack>
            ) : summary ? (
              <VStack spacing={6} align="stretch">
                {/* Bouton pour changer de format et régénérer */}
                <Button
                  size="sm"
                  variant="outline"
                  colorScheme="blue"
                  onClick={handleGenerate}
                  isLoading={summaryMutation.isPending}
                  alignSelf="flex-end"
                >
                  Regenerer avec ce format
                </Button>

                {/* Metadata badges */}
                <HStack spacing={2} flexWrap="wrap">
                  <Badge colorScheme="blue">
                    {summary.question_count} question{summary.question_count > 1 ? 's' : ''}
                  </Badge>
                  <Badge colorScheme="green">
                    {summary.sources_count} source{summary.sources_count > 1 ? 's' : ''}
                  </Badge>
                  {summary.duration_minutes && (
                    <Badge colorScheme="purple">
                      {summary.duration_minutes} min
                    </Badge>
                  )}
                  <Badge colorScheme="gray" textTransform="capitalize">
                    {summary.format}
                  </Badge>
                </HStack>

                {/* Context */}
                <Card variant="outline" size="sm">
                  <CardHeader pb={2}>
                    <Heading size="sm">Contexte</Heading>
                  </CardHeader>
                  <CardBody pt={0}>
                    <Text>{summary.context}</Text>
                  </CardBody>
                </Card>

                {/* Key Points */}
                {summary.key_points.length > 0 && (
                  <Card variant="outline" size="sm">
                    <CardHeader pb={2}>
                      <Heading size="sm">Points Cles</Heading>
                    </CardHeader>
                    <CardBody pt={0}>
                      <List spacing={2}>
                        {summary.key_points.map((kp, idx) => (
                          <ListItem key={idx}>
                            <HStack align="flex-start">
                              <ListIcon as={CheckCircleIcon} color="green.500" mt={1} />
                              <Box>
                                <Text>{kp.point}</Text>
                                {kp.source && (
                                  <Text fontSize="xs" color="gray.500" fontStyle="italic">
                                    Source: {kp.source}
                                  </Text>
                                )}
                              </Box>
                            </HStack>
                          </ListItem>
                        ))}
                      </List>
                    </CardBody>
                  </Card>
                )}

                {/* Actions */}
                {summary.actions.length > 0 && (
                  <Card variant="outline" size="sm">
                    <CardHeader pb={2}>
                      <Heading size="sm">Actions Recommandees</Heading>
                    </CardHeader>
                    <CardBody pt={0}>
                      <List spacing={2}>
                        {summary.actions.map((action, idx) => (
                          <ListItem key={idx}>
                            <HStack align="flex-start">
                              <ListIcon as={WarningIcon} color="orange.500" mt={1} />
                              <Text>{action}</Text>
                            </HStack>
                          </ListItem>
                        ))}
                      </List>
                    </CardBody>
                  </Card>
                )}

                {/* Unexplored Areas */}
                {summary.unexplored_areas.length > 0 && (
                  <Card variant="outline" size="sm">
                    <CardHeader pb={2}>
                      <Heading size="sm">Zones a Explorer</Heading>
                    </CardHeader>
                    <CardBody pt={0}>
                      <List spacing={2}>
                        {summary.unexplored_areas.map((area, idx) => (
                          <ListItem key={idx}>
                            <HStack align="flex-start">
                              <ListIcon as={InfoIcon} color="blue.500" mt={1} />
                              <Text>{area}</Text>
                            </HStack>
                          </ListItem>
                        ))}
                      </List>
                    </CardBody>
                  </Card>
                )}

                {/* Topics explored */}
                {summary.concepts_explored.length > 0 && (
                  <Box>
                    <Text fontWeight="medium" fontSize="sm" mb={2}>
                      Topics explores:
                    </Text>
                    <HStack spacing={2} flexWrap="wrap">
                      {summary.concepts_explored.map((concept, idx) => (
                        <Badge key={idx} colorScheme="teal" variant="subtle">
                          {concept}
                        </Badge>
                      ))}
                    </HStack>
                  </Box>
                )}

                {/* Generation info */}
                <Text fontSize="xs" color="gray.400" textAlign="right">
                  Genere le {formatDate(summary.generated_at)}
                </Text>
              </VStack>
            ) : (
              <VStack py={8} spacing={6}>
                <Text color="gray.600" textAlign="center">
                  Choisissez le format de compte-rendu souhaite puis cliquez sur <strong>Generer</strong>
                </Text>
                <VStack spacing={3} align="stretch" w="full" maxW="400px">
                  <Box
                    p={4}
                    borderWidth={format === 'business' ? '2px' : '1px'}
                    borderColor={format === 'business' ? 'blue.500' : 'gray.200'}
                    borderRadius="md"
                    cursor="pointer"
                    onClick={() => setFormat('business')}
                    bg={format === 'business' ? 'blue.50' : 'white'}
                    _hover={{ borderColor: 'blue.300' }}
                  >
                    <Text fontWeight="semibold">Business</Text>
                    <Text fontSize="sm" color="gray.500">
                      Points cles, actions recommandees, vue synthetique
                    </Text>
                  </Box>
                  <Box
                    p={4}
                    borderWidth={format === 'technical' ? '2px' : '1px'}
                    borderColor={format === 'technical' ? 'blue.500' : 'gray.200'}
                    borderRadius="md"
                    cursor="pointer"
                    onClick={() => setFormat('technical')}
                    bg={format === 'technical' ? 'blue.50' : 'white'}
                    _hover={{ borderColor: 'blue.300' }}
                  >
                    <Text fontWeight="semibold">Technique</Text>
                    <Text fontSize="sm" color="gray.500">
                      Details techniques, sources, references documentaires
                    </Text>
                  </Box>
                  <Box
                    p={4}
                    borderWidth={format === 'executive' ? '2px' : '1px'}
                    borderColor={format === 'executive' ? 'blue.500' : 'gray.200'}
                    borderRadius="md"
                    cursor="pointer"
                    onClick={() => setFormat('executive')}
                    bg={format === 'executive' ? 'blue.50' : 'white'}
                    _hover={{ borderColor: 'blue.300' }}
                  >
                    <Text fontWeight="semibold">Executive</Text>
                    <Text fontSize="sm" color="gray.500">
                      Resume ultra-concis pour decision rapide
                    </Text>
                  </Box>
                </VStack>
              </VStack>
            )}
          </ModalBody>

          <ModalFooter>
            <HStack spacing={3}>
              <Button variant="ghost" onClick={onClose}>
                Fermer
              </Button>
              <Button
                colorScheme="blue"
                onClick={handleGenerate}
                isLoading={summaryMutation.isPending}
                isDisabled={summaryMutation.isPending}
              >
                {summary ? 'Regenerer' : 'Generer'}
              </Button>
            </HStack>
          </ModalFooter>
        </ModalContent>
      </Modal>
    </>
  )
}
