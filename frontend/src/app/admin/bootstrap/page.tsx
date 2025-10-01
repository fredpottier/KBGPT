'use client'

import {
  Box,
  Button,
  Heading,
  Text,
  VStack,
  HStack,
  FormControl,
  FormLabel,
  NumberInput,
  NumberInputField,
  NumberInputStepper,
  NumberIncrementStepper,
  NumberDecrementStepper,
  Input,
  Switch,
  Stat,
  StatLabel,
  StatNumber,
  StatHelpText,
  Progress,
  useToast,
  Badge,
  SimpleGrid,
  Card,
  CardBody,
  Divider,
  List,
  ListItem,
  ListIcon,
} from '@chakra-ui/react'
import { useState, useEffect } from 'react'
import { CheckCircleIcon, TimeIcon, WarningIcon } from '@chakra-ui/icons'

interface BootstrapConfig {
  min_occurrences: number
  min_confidence: number
  group_id?: string
  entity_types?: string[]
  dry_run: boolean
}

interface BootstrapResult {
  total_candidates: number
  promoted_seeds: number
  seed_ids: string[]
  duration_seconds: number
  dry_run: boolean
  by_entity_type: Record<string, number>
}

interface BootstrapProgress {
  status: string
  processed: number
  total: number
  promoted: number
  current_entity?: string
  started_at: string
  estimated_completion?: string
}

interface BootstrapEstimate {
  qualified_candidates: number
  by_entity_type: Record<string, number>
  estimated_duration_seconds: number
}

export default function AdminBootstrapPage() {
  const [config, setConfig] = useState<BootstrapConfig>({
    min_occurrences: 10,
    min_confidence: 0.8,
    dry_run: true,
  })

  const [result, setResult] = useState<BootstrapResult | null>(null)
  const [progress, setProgress] = useState<BootstrapProgress | null>(null)
  const [estimate, setEstimate] = useState<BootstrapEstimate | null>(null)
  const [isRunning, setIsRunning] = useState(false)
  const [isEstimating, setIsEstimating] = useState(false)

  const toast = useToast()

  // Poll progress pendant l'exécution
  useEffect(() => {
    if (!isRunning) return

    const interval = setInterval(async () => {
      try {
        const response = await fetch('/api/canonicalization/bootstrap/progress')
        if (response.ok) {
          const progressData = await response.json()
          setProgress(progressData)

          if (progressData && progressData.status === 'completed') {
            setIsRunning(false)
          }
        }
      } catch (error) {
        console.error('Erreur polling progress:', error)
      }
    }, 1000) // Poll toutes les 1s

    return () => clearInterval(interval)
  }, [isRunning])

  const handleEstimate = async () => {
    setIsEstimating(true)
    try {
      const response = await fetch('/api/canonicalization/bootstrap/estimate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      })

      if (response.ok) {
        const estimateData = await response.json()
        setEstimate(estimateData)
        toast({
          title: 'Estimation réalisée',
          description: `${estimateData.qualified_candidates} entités seraient promues`,
          status: 'info',
          duration: 3000,
        })
      } else {
        throw new Error('Erreur estimation')
      }
    } catch (error) {
      toast({
        title: 'Erreur estimation',
        description: String(error),
        status: 'error',
        duration: 5000,
      })
    } finally {
      setIsEstimating(false)
    }
  }

  const handleBootstrap = async () => {
    setIsRunning(true)
    setResult(null)
    setProgress(null)

    try {
      const response = await fetch('/api/canonicalization/bootstrap', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      })

      if (response.ok) {
        const resultData = await response.json()
        setResult(resultData)
        toast({
          title: config.dry_run ? 'Simulation terminée' : 'Bootstrap terminé',
          description: `${resultData.promoted_seeds} entités ${config.dry_run ? 'seraient promues' : 'promues'} en ${resultData.duration_seconds.toFixed(2)}s`,
          status: 'success',
          duration: 5000,
        })
      } else {
        throw new Error('Erreur bootstrap')
      }
    } catch (error) {
      toast({
        title: 'Erreur bootstrap',
        description: String(error),
        status: 'error',
        duration: 5000,
      })
    } finally {
      setIsRunning(false)
    }
  }

  return (
    <VStack spacing={6} align="stretch">
      <Box>
        <Heading size="lg" mb={2}>
          Bootstrap Knowledge Graph
        </Heading>
        <Text color="gray.600">
          Auto-promotion des entités candidates fréquentes en entités seed canoniques
        </Text>
      </Box>

      {/* Configuration */}
      <Card>
        <CardBody>
          <Heading size="md" mb={4}>
            Configuration
          </Heading>

          <VStack spacing={4} align="stretch">
            <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
              <FormControl>
                <FormLabel>Occurrences minimales</FormLabel>
                <NumberInput
                  min={1}
                  max={100}
                  value={config.min_occurrences}
                  onChange={(_, value) =>
                    setConfig({ ...config, min_occurrences: value || 10 })
                  }
                >
                  <NumberInputField />
                  <NumberInputStepper>
                    <NumberIncrementStepper />
                    <NumberDecrementStepper />
                  </NumberInputStepper>
                </NumberInput>
                <Text fontSize="sm" color="gray.500" mt={1}>
                  Nombre minimum d&apos;occurrences requises
                </Text>
              </FormControl>

              <FormControl>
                <FormLabel>Confidence minimale</FormLabel>
                <NumberInput
                  min={0}
                  max={1}
                  step={0.05}
                  value={config.min_confidence}
                  onChange={(_, value) =>
                    setConfig({ ...config, min_confidence: value || 0.8 })
                  }
                >
                  <NumberInputField />
                  <NumberInputStepper>
                    <NumberIncrementStepper />
                    <NumberDecrementStepper />
                  </NumberInputStepper>
                </NumberInput>
                <Text fontSize="sm" color="gray.500" mt={1}>
                  Score de confiance minimum (0.0 - 1.0)
                </Text>
              </FormControl>

              <FormControl>
                <FormLabel>Groupe (optionnel)</FormLabel>
                <Input
                  placeholder="corporate"
                  value={config.group_id || ''}
                  onChange={(e) =>
                    setConfig({ ...config, group_id: e.target.value || undefined })
                  }
                />
                <Text fontSize="sm" color="gray.500" mt={1}>
                  Filtrer par groupe multi-tenant
                </Text>
              </FormControl>

              <FormControl display="flex" alignItems="center">
                <FormLabel mb={0}>
                  Mode simulation (dry run)
                </FormLabel>
                <Switch
                  isChecked={config.dry_run}
                  onChange={(e) =>
                    setConfig({ ...config, dry_run: e.target.checked })
                  }
                  colorScheme={config.dry_run ? 'gray' : 'green'}
                />
              </FormControl>
            </SimpleGrid>

            <HStack spacing={4}>
              <Button
                colorScheme="blue"
                onClick={handleEstimate}
                isLoading={isEstimating}
                isDisabled={isRunning}
              >
                Estimer
              </Button>

              <Button
                colorScheme={config.dry_run ? 'gray' : 'green'}
                onClick={handleBootstrap}
                isLoading={isRunning}
                isDisabled={isEstimating}
              >
                {config.dry_run ? 'Simuler Bootstrap' : 'Exécuter Bootstrap'}
              </Button>
            </HStack>
          </VStack>
        </CardBody>
      </Card>

      {/* Estimation */}
      {estimate && (
        <Card bg="blue.50">
          <CardBody>
            <Heading size="md" mb={4}>
              Estimation
            </Heading>

            <SimpleGrid columns={{ base: 1, md: 3 }} spacing={4}>
              <Stat>
                <StatLabel>Entités qualifiées</StatLabel>
                <StatNumber>{estimate.qualified_candidates}</StatNumber>
                <StatHelpText>Seraient promues</StatHelpText>
              </Stat>

              <Stat>
                <StatLabel>Durée estimée</StatLabel>
                <StatNumber>{estimate.estimated_duration_seconds.toFixed(2)}s</StatNumber>
                <StatHelpText>Temps d&apos;exécution</StatHelpText>
              </Stat>

              <Stat>
                <StatLabel>Types d&apos;entités</StatLabel>
                <StatNumber>{Object.keys(estimate.by_entity_type).length}</StatNumber>
                <StatHelpText>
                  {Object.entries(estimate.by_entity_type)
                    .map(([type, count]) => `${type}: ${count}`)
                    .join(', ')}
                </StatHelpText>
              </Stat>
            </SimpleGrid>
          </CardBody>
        </Card>
      )}

      {/* Progression */}
      {progress && isRunning && (
        <Card bg="yellow.50">
          <CardBody>
            <Heading size="md" mb={4}>
              Progression
              <Badge ml={2} colorScheme="yellow">
                {progress.status}
              </Badge>
            </Heading>

            <VStack spacing={4} align="stretch">
              <Progress
                value={(progress.processed / progress.total) * 100}
                colorScheme="blue"
                size="lg"
                hasStripe
                isAnimated
              />

              <SimpleGrid columns={{ base: 1, md: 4 }} spacing={4}>
                <Stat>
                  <StatLabel>Traitées</StatLabel>
                  <StatNumber>
                    {progress.processed} / {progress.total}
                  </StatNumber>
                </Stat>

                <Stat>
                  <StatLabel>Promues</StatLabel>
                  <StatNumber>{progress.promoted}</StatNumber>
                </Stat>

                <Stat>
                  <StatLabel>Entité courante</StatLabel>
                  <StatNumber fontSize="sm">
                    {progress.current_entity || '-'}
                  </StatNumber>
                </Stat>

                <Stat>
                  <StatLabel>Démarrée à</StatLabel>
                  <StatNumber fontSize="sm">
                    {new Date(progress.started_at).toLocaleTimeString()}
                  </StatNumber>
                </Stat>
              </SimpleGrid>
            </VStack>
          </CardBody>
        </Card>
      )}

      {/* Résultat */}
      {result && (
        <Card bg={result.dry_run ? 'gray.50' : 'green.50'}>
          <CardBody>
            <Heading size="md" mb={4}>
              Résultat
              <Badge ml={2} colorScheme={result.dry_run ? 'gray' : 'green'}>
                {result.dry_run ? 'Simulation' : 'Exécuté'}
              </Badge>
            </Heading>

            <SimpleGrid columns={{ base: 1, md: 4 }} spacing={4} mb={4}>
              <Stat>
                <StatLabel>Candidates analysées</StatLabel>
                <StatNumber>{result.total_candidates}</StatNumber>
              </Stat>

              <Stat>
                <StatLabel>Seeds {result.dry_run ? 'simulées' : 'promues'}</StatLabel>
                <StatNumber color="green.600">
                  {result.promoted_seeds}
                </StatNumber>
              </Stat>

              <Stat>
                <StatLabel>Durée</StatLabel>
                <StatNumber>{result.duration_seconds.toFixed(2)}s</StatNumber>
              </Stat>

              <Stat>
                <StatLabel>Taux de promotion</StatLabel>
                <StatNumber>
                  {result.total_candidates > 0
                    ? Math.round((result.promoted_seeds / result.total_candidates) * 100)
                    : 0}
                  %
                </StatNumber>
              </Stat>
            </SimpleGrid>

            {Object.keys(result.by_entity_type).length > 0 && (
              <>
                <Divider my={4} />
                <Heading size="sm" mb={3}>
                  Répartition par type
                </Heading>
                <List spacing={2}>
                  {Object.entries(result.by_entity_type).map(([type, count]) => (
                    <ListItem key={type}>
                      <HStack>
                        <ListIcon as={CheckCircleIcon} color="green.500" />
                        <Text fontWeight="medium">{type}</Text>
                        <Badge colorScheme="green">{count}</Badge>
                      </HStack>
                    </ListItem>
                  ))}
                </List>
              </>
            )}

            {result.seed_ids.length > 0 && result.seed_ids.length <= 10 && (
              <>
                <Divider my={4} />
                <Heading size="sm" mb={3}>
                  IDs des seeds {result.dry_run ? 'simulées' : 'créées'}
                </Heading>
                <List spacing={1}>
                  {result.seed_ids.map((id) => (
                    <ListItem key={id} fontSize="sm" fontFamily="mono">
                      {id}
                    </ListItem>
                  ))}
                </List>
              </>
            )}
          </CardBody>
        </Card>
      )}

      {/* Note Phase 3 */}
      <Card bg="orange.50" borderColor="orange.200">
        <CardBody>
          <HStack spacing={2} mb={2}>
            <WarningIcon color="orange.500" />
            <Heading size="sm">Note Phase 3</Heading>
          </HStack>
          <Text fontSize="sm" color="gray.700">
            Actuellement, aucune candidate n&apos;existe car l&apos;extraction automatique
            (Phase 3) n&apos;est pas encore implémentée. Le bootstrap retournera 0 entité
            promue. Une fois Phase 3 implémentée, les candidates seront extraites
            automatiquement depuis les documents et le bootstrap fonctionnera normalement.
          </Text>
        </CardBody>
      </Card>
    </VStack>
  )
}
