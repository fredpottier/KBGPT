'use client'

import { useEffect, useState, useCallback } from 'react'
import {
  Box,
  Heading,
  Text,
  VStack,
  HStack,
  Button,
  Checkbox,
  Badge,
  Spinner,
  useToast,
  Icon,
  Progress,
  Divider,
} from '@chakra-ui/react'
import {
  FiPlay, FiCheck, FiX, FiClock, FiZap,
  FiRefreshCw, FiLayers, FiLink2, FiGrid, FiPackage,
} from 'react-icons/fi'
import { api } from '@/lib/api'

interface StepInfo {
  id: string
  name: string
  description: string
  order: number
  estimated_duration: string
  requires_llm: boolean
  requires_pack: boolean
  estimated_minutes: number | null
}

interface StepResult {
  step_id: string
  status: string
  message: string
  duration_s: number
  details: Record<string, unknown>
}

interface PipelineResult {
  steps: StepResult[]
  total_duration_s: number
  success_count: number
  error_count: number
}

const STEP_ICONS: Record<string, typeof FiRefreshCw> = {
  canonicalize: FiLayers,
  facets: FiGrid,
  cluster_cross_doc: FiLink2,
  chains_cross_doc: FiZap,
  domain_pack_reprocess: FiPackage,
}

export default function PostImportPage() {
  const [steps, setSteps] = useState<StepInfo[]>([])
  const [selectedSteps, setSelectedSteps] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [currentStep, setCurrentStep] = useState<string | null>(null)
  const [stepProgress, setStepProgress] = useState<number>(0)
  const [stepDetail, setStepDetail] = useState<string>('')
  const [completedSteps, setCompletedSteps] = useState<string[]>([])
  const [results, setResults] = useState<PipelineResult | null>(null)
  const toast = useToast()

  const loadSteps = useCallback(async () => {
    try {
      const [stepsRes, statusRes] = await Promise.all([
        api.postImport.steps(),
        api.postImport.status(),
      ])
      setSteps(stepsRes.data || [])

      // Reprendre un pipeline en cours
      const status = statusRes.data
      if (status.running) {
        setRunning(true)
        setCurrentStep(status.current_step || null)
        setCompletedSteps(status.completed_steps || [])
      } else if (status.results && status.results.length > 0) {
        // Afficher les résultats du dernier run
        setResults({
          steps: status.results,
          total_duration_s: status.results.reduce((s: number, r: StepResult) => s + r.duration_s, 0),
          success_count: status.results.filter((r: StepResult) => r.status === 'success').length,
          error_count: status.results.filter((r: StepResult) => r.status === 'error').length,
        })
        setCompletedSteps(status.completed_steps || [])
      }
    } catch {
      toast({ title: 'Erreur chargement étapes', status: 'error', duration: 3000 })
    } finally {
      setLoading(false)
    }
  }, [toast])

  useEffect(() => { loadSteps() }, [loadSteps])

  // Polling status pendant l'exécution
  useEffect(() => {
    if (!running) return
    const interval = setInterval(async () => {
      try {
        const res = await api.postImport.status()
        const data = res.data
        if (data.current_step) setCurrentStep(data.current_step)
        setStepProgress(data.step_progress || 0)
        setStepDetail(data.step_detail || '')
        if (data.completed_steps) setCompletedSteps(data.completed_steps || [])
        if (!data.running && data.results && data.results.length > 0) {
          setRunning(false)
          setCurrentStep(null)
          // Construire le résultat final
          setResults({
            steps: data.results,
            total_duration_s: data.results.reduce((s: number, r: StepResult) => s + r.duration_s, 0),
            success_count: data.results.filter((r: StepResult) => r.status === 'success').length,
            error_count: data.results.filter((r: StepResult) => r.status === 'error').length,
          })
          toast({
            title: 'Pipeline terminé',
            status: data.results.some((r: StepResult) => r.status === 'error') ? 'warning' : 'success',
            duration: 5000,
          })
        }
      } catch { /* ignore */ }
    }, 3000)
    return () => clearInterval(interval)
  }, [running, toast])

  const toggleStep = (stepId: string) => {
    const next = new Set(selectedSteps)
    if (next.has(stepId)) next.delete(stepId)
    else next.add(stepId)
    setSelectedSteps(next)
  }

  const selectAll = () => {
    if (selectedSteps.size === steps.length) {
      setSelectedSteps(new Set())
    } else {
      setSelectedSteps(new Set(steps.map(s => s.id)))
    }
  }

  const runPipeline = async () => {
    if (selectedSteps.size === 0) return
    setRunning(true)
    setResults(null)
    setCurrentStep(null)
    setCompletedSteps([])

    try {
      const res = await api.postImport.run(Array.from(selectedSteps))
      if (res.data?.success) {
        toast({
          title: `Pipeline lancé (${res.data.steps_queued?.length} étapes)`,
          status: 'info',
          duration: 3000,
        })
      } else {
        toast({ title: 'Erreur lancement', status: 'error', duration: 5000 })
        setRunning(false)
      }
    } catch (err) {
      toast({ title: 'Erreur pipeline', status: 'error', duration: 5000 })
      setRunning(false)
    }
  }

  const getStepStatus = (stepId: string): 'idle' | 'running' | 'done' | 'error' => {
    if (results) {
      const r = results.steps.find(s => s.step_id === stepId)
      if (r) return r.status === 'success' ? 'done' : 'error'
    }
    if (currentStep === stepId) return 'running'
    if (completedSteps.includes(stepId)) return 'done'
    return 'idle'
  }

  if (loading) {
    return (
      <Box textAlign="center" py={20}>
        <Spinner size="xl" color="brand.400" />
      </Box>
    )
  }

  const progress = results
    ? 100
    : steps.length > 0 && selectedSteps.size > 0
    ? (completedSteps.length / selectedSteps.size) * 100
    : 0

  return (
    <Box>
      {/* Header */}
      <VStack align="start" spacing={2} mb={6}>
        <HStack justify="space-between" w="full">
          <HStack>
            <Icon as={FiRefreshCw} boxSize={6} color="brand.400" />
            <Heading size="lg" color="text.primary">Post-Import</Heading>
          </HStack>
          <HStack spacing={3}>
            <Button
              size="sm"
              variant="outline"
              onClick={selectAll}
              isDisabled={running}
            >
              {selectedSteps.size === steps.length ? 'Tout désélectionner' : 'Tout sélectionner'}
            </Button>
            <Button
              size="sm"
              colorScheme="green"
              leftIcon={<FiPlay />}
              onClick={runPipeline}
              isLoading={running}
              loadingText="Exécution..."
              isDisabled={selectedSteps.size === 0 || running}
            >
              Exécuter ({selectedSteps.size})
            </Button>
            {selectedSteps.size > 0 && (() => {
              const totalMin = steps
                .filter(s => selectedSteps.has(s.id))
                .reduce((sum, s) => sum + (s.estimated_minutes || 0), 0)
              return totalMin > 0 ? (
                <Text fontSize="xs" color="brand.300">
                  ~{totalMin < 1 ? '<1' : Math.round(totalMin)} min estimées
                </Text>
              ) : null
            })()}
          </HStack>
        </HStack>
        <Text color="text.secondary" maxW="700px">
          Opérations d'enrichissement du Knowledge Graph après un import.
          Sélectionnez les étapes souhaitées — elles s'exécutent dans l'ordre optimal.
        </Text>
      </VStack>

      {/* Progress bar (pendant l'exécution) */}
      {running && (
        <Box mb={6}>
          <Progress
            value={progress}
            size="sm"
            colorScheme="brand"
            rounded="full"
            hasStripe
            isAnimated
          />
        </Box>
      )}

      {/* Steps */}
      <VStack spacing={3} align="stretch">
        {steps.map((step, index) => {
          const status = getStepStatus(step.id)
          const StepIcon = STEP_ICONS[step.id] || FiRefreshCw
          const result = results?.steps.find(s => s.step_id === step.id)

          return (
            <Box
              key={step.id}
              p={5}
              bg="bg.secondary"
              rounded="xl"
              border="2px solid"
              borderColor={
                status === 'running' ? 'blue.500' :
                status === 'done' ? 'green.500' :
                status === 'error' ? 'red.500' :
                selectedSteps.has(step.id) ? 'brand.500' :
                'border.default'
              }
              transition="all 0.2s"
              opacity={running && status === 'idle' && !selectedSteps.has(step.id) ? 0.5 : 1}
            >
              <HStack justify="space-between" align="start">
                <HStack spacing={4} align="start" flex={1}>
                  {/* Checkbox */}
                  <Checkbox
                    isChecked={selectedSteps.has(step.id)}
                    onChange={() => toggleStep(step.id)}
                    isDisabled={running}
                    mt={1}
                    colorScheme="brand"
                    size="lg"
                  />

                  {/* Step number */}
                  <Box
                    w="36px" h="36px"
                    rounded="full"
                    bg={
                      status === 'done' ? 'green.500' :
                      status === 'error' ? 'red.500' :
                      status === 'running' ? 'blue.500' :
                      'whiteAlpha.100'
                    }
                    display="flex" alignItems="center" justifyContent="center"
                    flexShrink={0}
                  >
                    {status === 'running' ? (
                      <Spinner size="sm" color="white" />
                    ) : status === 'done' ? (
                      <Icon as={FiCheck} color="white" />
                    ) : status === 'error' ? (
                      <Icon as={FiX} color="white" />
                    ) : (
                      <Text fontSize="sm" fontWeight="bold" color="text.muted">
                        {step.order}
                      </Text>
                    )}
                  </Box>

                  {/* Content */}
                  <VStack align="start" spacing={1} flex={1}>
                    <HStack>
                      <Icon as={StepIcon} color="brand.400" />
                      <Text fontWeight="semibold" color="text.primary">
                        {step.name}
                      </Text>
                      {step.requires_llm && (
                        <Badge colorScheme="purple" variant="subtle" fontSize="xs">LLM</Badge>
                      )}
                      {step.requires_pack && (
                        <Badge colorScheme="orange" variant="subtle" fontSize="xs">Pack requis</Badge>
                      )}
                    </HStack>
                    <Text fontSize="sm" color="text.secondary">
                      {step.description}
                    </Text>

                    {/* Step progress (pendant l'exécution) */}
                    {status === 'running' && (
                      <Box mt={2} w="full">
                        <HStack justify="space-between" mb={1}>
                          <Text fontSize="xs" color="brand.300" fontWeight="500">
                            {stepDetail || 'En cours...'}
                          </Text>
                          <Text fontSize="xs" color="brand.300" fontWeight="600">
                            {Math.round(stepProgress)}%
                          </Text>
                        </HStack>
                        <Progress
                          value={stepProgress}
                          size="xs"
                          colorScheme="brand"
                          rounded="full"
                          hasStripe
                          isAnimated
                        />
                      </Box>
                    )}

                    {/* Result details */}
                    {result && (
                      <Box mt={2} p={3} bg="bg.tertiary" rounded="md" w="full">
                        <HStack spacing={4} flexWrap="wrap">
                          <HStack>
                            <Icon
                              as={result.status === 'success' ? FiCheck : FiX}
                              color={result.status === 'success' ? 'green.400' : 'red.400'}
                            />
                            <Text fontSize="sm" color="text.primary">
                              {result.message}
                            </Text>
                          </HStack>
                          <Badge variant="outline" colorScheme="blue" fontSize="xs">
                            {result.duration_s}s
                          </Badge>
                          {Object.entries(result.details || {}).map(([k, v]) => (
                            <Text key={k} fontSize="xs" color="text.muted">
                              {k}: <Text as="span" color="text.secondary">{String(v)}</Text>
                            </Text>
                          ))}
                        </HStack>
                      </Box>
                    )}
                  </VStack>
                </HStack>

                {/* Duration estimate */}
                <HStack spacing={1} flexShrink={0}>
                  <Icon as={FiClock} color="text.muted" boxSize={3} />
                  <Text fontSize="xs" color={step.estimated_minutes ? "brand.300" : "text.muted"}>
                    {step.estimated_minutes
                      ? `~${step.estimated_minutes < 1 ? '<1' : step.estimated_minutes} min`
                      : step.estimated_duration}
                  </Text>
                </HStack>
              </HStack>
            </Box>
          )
        })}
      </VStack>

      {/* Final summary — tableau recapitulatif */}
      {results && (
        <Box mt={6} bg="bg.secondary" rounded="xl" border="1px solid" borderColor="border.default" overflow="hidden">
          <HStack justify="space-between" px={5} py={3} bg="rgba(99, 102, 241, 0.06)" borderBottom="1px solid" borderColor="border.default">
            <HStack spacing={3}>
              <Icon as={FiCheck} color="green.400" />
              <Text fontWeight="600" color="text.primary">Recapitulatif du pipeline</Text>
            </HStack>
            <HStack spacing={4}>
              <Badge colorScheme="green" fontSize="sm" px={3} py={1}>
                {results.success_count} reussie{results.success_count > 1 ? 's' : ''}
              </Badge>
              {results.error_count > 0 && (
                <Badge colorScheme="red" fontSize="sm" px={3} py={1}>
                  {results.error_count} erreur{results.error_count > 1 ? 's' : ''}
                </Badge>
              )}
              <Text fontSize="sm" color="text.muted">
                {Math.round(results.total_duration_s)}s au total
              </Text>
            </HStack>
          </HStack>

          <VStack spacing={0} align="stretch" divider={<Divider borderColor="border.default" />}>
            {results.steps.map((result) => {
              const step = steps.find(s => s.id === result.step_id)
              const StepIcon = STEP_ICONS[result.step_id] || FiRefreshCw
              const details = result.details || {}
              const detailEntries = Object.entries(details).filter(
                ([k]) => !['success', 'status', 'error'].includes(k)
              )

              return (
                <Box key={result.step_id} px={5} py={3}>
                  <HStack justify="space-between" mb={detailEntries.length > 0 ? 2 : 0}>
                    <HStack spacing={3}>
                      <Icon
                        as={result.status === 'success' ? FiCheck : FiX}
                        color={result.status === 'success' ? 'green.400' : 'red.400'}
                        boxSize={4}
                      />
                      <Icon as={StepIcon} color="brand.400" boxSize={4} />
                      <Text fontSize="sm" fontWeight="500" color="text.primary">
                        {step?.name || result.step_id}
                      </Text>
                    </HStack>
                    <HStack spacing={3}>
                      <Text fontSize="xs" color="text.muted">
                        {result.duration_s < 1 ? '<1' : Math.round(result.duration_s)}s
                      </Text>
                      <Badge
                        colorScheme={result.status === 'success' ? 'green' : 'red'}
                        variant="subtle"
                        fontSize="xs"
                      >
                        {result.status === 'success' ? 'OK' : 'Erreur'}
                      </Badge>
                    </HStack>
                  </HStack>

                  {/* Message */}
                  <Text fontSize="xs" color="text.secondary" ml={10} mb={detailEntries.length > 0 ? 2 : 0}>
                    {result.message}
                  </Text>

                  {/* Detail metrics in a clean grid */}
                  {detailEntries.length > 0 && (
                    <HStack spacing={4} ml={10} flexWrap="wrap">
                      {detailEntries.map(([key, value]) => {
                        // Formatter les cles pour la lisibilite
                        const label = key
                          .replace(/_/g, ' ')
                          .replace(/\b\w/g, c => c.toUpperCase())
                        return (
                          <HStack key={key} spacing={1}>
                            <Text fontSize="xs" color="text.muted">{label}:</Text>
                            <Text fontSize="xs" fontWeight="600" color="brand.300">
                              {typeof value === 'number' ? value.toLocaleString() : String(value)}
                            </Text>
                          </HStack>
                        )
                      })}
                    </HStack>
                  )}
                </Box>
              )
            })}
          </VStack>
        </Box>
      )}
    </Box>
  )
}
