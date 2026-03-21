'use client'

import { useEffect, useState, useCallback, useRef } from 'react'
import {
  Box,
  Heading,
  Text,
  SimpleGrid,
  Badge,
  Button,
  HStack,
  VStack,
  Spinner,
  useToast,
  Stat,
  StatLabel,
  StatNumber,
  StatHelpText,
  Icon,
  Input,
} from '@chakra-ui/react'
import {
  FiPackage, FiZap, FiRefreshCw, FiCheck, FiX,
  FiDownload, FiTrash2, FiUploadCloud, FiServer,
} from 'react-icons/fi'
import { api } from '@/lib/api'

interface PackInfo {
  name: string
  display_name: string
  description: string
  version: string
  priority: number
  is_active: boolean
  is_builtin: boolean
  container_state: string  // not_installed | installed | active | error
  entity_types: string[]
  ner_model: string
  ner_model_size_mb: number
}

interface PackStats {
  pack_name: string
  entities_created: number
  claims_linked: number
  aliases_resolved: number
  gazetteer_matches: number
  coverage_after: number | null
}

interface ReprocessStatus {
  state: string
  progress: number
  entities_created: number
  claims_linked: number
  error: string | null
}

const STATE_LABELS: Record<string, { label: string; color: string }> = {
  not_installed: { label: 'Non installé', color: 'gray' },
  installed: { label: 'Installé', color: 'blue' },
  active: { label: 'Container actif', color: 'green' },
  error: { label: 'Erreur', color: 'red' },
}

export default function DomainPacksPage() {
  const [packs, setPacks] = useState<PackInfo[]>([])
  const [stats, setStats] = useState<Record<string, PackStats>>({})
  const [reprocessStatus, setReprocessStatus] = useState<ReprocessStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const [reprocessing, setReprocessing] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const toast = useToast()

  const loadPacks = useCallback(async () => {
    try {
      const res = await api.domainPacks.list()
      setPacks(res.data.packs || [])

      for (const pack of (res.data.packs || [])) {
        if (pack.is_active) {
          try {
            const statsRes = await api.domainPacks.stats(pack.name)
            setStats(prev => ({ ...prev, [pack.name]: statsRes.data }))
          } catch { /* Stats non disponibles */ }
        }
      }
    } catch {
      toast({ title: 'Erreur chargement packs', status: 'error', duration: 3000 })
    } finally {
      setLoading(false)
    }
  }, [toast])

  useEffect(() => { loadPacks() }, [loadPacks])

  // Polling reprocess
  useEffect(() => {
    if (!reprocessing) return
    const interval = setInterval(async () => {
      try {
        const res = await api.domainPacks.reprocessStatus()
        setReprocessStatus(res.data)
        if (res.data.state === 'completed' || res.data.state === 'failed') {
          setReprocessing(null)
          loadPacks()
          toast({
            title: res.data.state === 'completed'
              ? `Reprocessing terminé : ${res.data.entities_created} entités, ${res.data.claims_linked} liens`
              : `Reprocessing échoué : ${res.data.error}`,
            status: res.data.state === 'completed' ? 'success' : 'error',
            duration: 5000,
          })
        }
      } catch { /* Ignore */ }
    }, 3000)
    return () => clearInterval(interval)
  }, [reprocessing, loadPacks, toast])

  const doAction = async (action: string, packName: string, fn: () => Promise<any>) => {
    setActionLoading(`${action}:${packName}`)
    try {
      const res = await fn()
      const msg = res.data?.message || `${action} OK`
      toast({ title: msg, status: 'success', duration: 3000 })
      await loadPacks()
    } catch {
      toast({ title: `Erreur ${action}`, status: 'error', duration: 3000 })
    } finally {
      setActionLoading(null)
    }
  }

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setActionLoading('upload')
    try {
      const res = await api.domainPacks.upload(file)
      toast({
        title: res.data?.message || 'Pack uploadé',
        status: res.data?.success ? 'success' : 'error',
        duration: 5000,
      })
      await loadPacks()
    } catch {
      toast({ title: 'Erreur upload', status: 'error', duration: 3000 })
    } finally {
      setActionLoading(null)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  if (loading) {
    return (
      <Box textAlign="center" py={20}>
        <Spinner size="xl" color="brand.400" />
        <Text mt={4} color="text.secondary">Chargement des Domain Packs...</Text>
      </Box>
    )
  }

  return (
    <Box>
      {/* Header */}
      <VStack align="start" spacing={2} mb={8}>
        <HStack justify="space-between" w="full">
          <HStack>
            <Icon as={FiPackage} boxSize={6} color="brand.400" />
            <Heading size="lg" color="text.primary">Domain Packs</Heading>
          </HStack>
          <HStack>
            <Input
              ref={fileInputRef}
              type="file"
              accept=".osmpack,.zip"
              display="none"
              onChange={handleUpload}
            />
            <Button
              size="sm"
              leftIcon={<FiUploadCloud />}
              colorScheme="blue"
              variant="outline"
              onClick={() => fileInputRef.current?.click()}
              isLoading={actionLoading === 'upload'}
            >
              Installer un pack
            </Button>
          </HStack>
        </HStack>
        <Text color="text.secondary" maxW="700px">
          Packages NER autonomes (containers Docker). Chaque pack embarque son modèle
          et s'exécute indépendamment. Le core reste domain-agnostic.
        </Text>
      </VStack>

      {/* Packs Grid */}
      {packs.length === 0 ? (
        <Box p={8} bg="bg.secondary" rounded="xl" border="1px solid" borderColor="border.default" textAlign="center">
          <Text color="text.muted">Aucun Domain Pack disponible</Text>
        </Box>
      ) : (
        <SimpleGrid columns={{ base: 1, md: 2, lg: 3 }} spacing={6}>
          {packs.map((pack) => {
            const packStats = stats[pack.name]
            const stateInfo = STATE_LABELS[pack.container_state] || STATE_LABELS.not_installed
            const isReprocessing = reprocessing === pack.name
            const isLoading = (key: string) => actionLoading === `${key}:${pack.name}`

            return (
              <Box
                key={pack.name}
                p={6}
                bg="bg.secondary"
                rounded="xl"
                border="1px solid"
                borderColor={pack.is_active ? 'green.500' : 'border.default'}
                transition="all 0.2s"
                _hover={{ borderColor: pack.is_active ? 'green.400' : 'border.hover' }}
              >
                {/* Header */}
                <HStack justify="space-between" mb={3}>
                  <HStack>
                    <Icon
                      as={pack.container_state === 'active' ? FiServer : FiZap}
                      color={pack.is_active ? 'green.400' : 'text.muted'}
                    />
                    <Text fontWeight="semibold" color="text.primary">
                      {pack.display_name}
                    </Text>
                  </HStack>
                  <Badge colorScheme={stateInfo.color} variant="subtle" fontSize="xs">
                    {stateInfo.label}
                  </Badge>
                </HStack>

                {/* Description */}
                <Text fontSize="sm" color="text.secondary" mb={3} noOfLines={3}>
                  {pack.description}
                </Text>

                {/* Badges */}
                <HStack spacing={2} mb={4} flexWrap="wrap">
                  <Badge variant="outline" colorScheme="blue" fontSize="xs">v{pack.version}</Badge>
                  {pack.ner_model && (
                    <Badge variant="outline" colorScheme="purple" fontSize="xs">
                      {pack.ner_model}
                    </Badge>
                  )}
                  {pack.ner_model_size_mb > 0 && (
                    <Badge variant="outline" colorScheme="orange" fontSize="xs">
                      {pack.ner_model_size_mb} MB
                    </Badge>
                  )}
                  {pack.entity_types.map(t => (
                    <Badge key={t} variant="outline" colorScheme="teal" fontSize="xs">{t}</Badge>
                  ))}
                </HStack>

                {/* Stats (si actif) */}
                {pack.is_active && packStats && (
                  <SimpleGrid columns={2} spacing={3} mb={4}>
                    <Stat size="sm">
                      <StatLabel fontSize="xs" color="text.muted">Entites creees</StatLabel>
                      <StatNumber fontSize="lg" color="brand.400">
                        {packStats.entities_created.toLocaleString()}
                      </StatNumber>
                    </Stat>
                    <Stat size="sm">
                      <StatLabel fontSize="xs" color="text.muted">Claims liees</StatLabel>
                      <StatNumber fontSize="lg" color="green.400">
                        {packStats.claims_linked.toLocaleString()}
                      </StatNumber>
                    </Stat>
                    <Stat size="sm">
                      <StatLabel fontSize="xs" color="text.muted">Aliases resolus</StatLabel>
                      <StatNumber fontSize="lg" color="orange.400">
                        {(packStats.aliases_resolved || 0).toLocaleString()}
                      </StatNumber>
                      <StatHelpText fontSize="xs">entites renommees (ex: BTP → SAP Business Technology Platform)</StatHelpText>
                    </Stat>
                    <Stat size="sm">
                      <StatLabel fontSize="xs" color="text.muted">Gazetteer matchs</StatLabel>
                      <StatNumber fontSize="lg" color="purple.400">
                        {(packStats.gazetteer_matches || 0).toLocaleString()}
                      </StatNumber>
                      <StatHelpText fontSize="xs">entites reconnues dans le gazetteer</StatHelpText>
                    </Stat>
                    {packStats.coverage_after != null && (
                      <Stat size="sm" gridColumn="span 2">
                        <StatLabel fontSize="xs" color="text.muted">Couverture ABOUT</StatLabel>
                        <StatNumber fontSize="lg" color="text.primary">
                          {(packStats.coverage_after * 100).toFixed(1)}%
                        </StatNumber>
                        <StatHelpText fontSize="xs">des claims liées à une entité</StatHelpText>
                      </Stat>
                    )}
                  </SimpleGrid>
                )}

                {/* Reprocess progress */}
                {isReprocessing && reprocessStatus && (
                  <Box mb={4} p={3} bg="bg.tertiary" rounded="md">
                    <HStack>
                      <Spinner size="sm" color="brand.400" />
                      <Text fontSize="sm" color="text.secondary">
                        Reprocessing... {(reprocessStatus.progress * 100).toFixed(0)}%
                      </Text>
                    </HStack>
                  </Box>
                )}

                {/* Actions */}
                <VStack spacing={2} align="stretch">
                  {/* Install / Activate / Deactivate */}
                  {pack.container_state === 'not_installed' && (
                    <Button
                      size="sm" colorScheme="blue" leftIcon={<FiDownload />}
                      onClick={() => doAction('install', pack.name,
                        () => api.domainPacks.install(pack.name)
                      )}
                      isLoading={isLoading('install')}
                    >
                      Installer l'image
                    </Button>
                  )}

                  {(pack.container_state === 'installed' || pack.container_state === 'active') && (
                    <HStack spacing={2}>
                      <Button
                        size="sm" flex={1}
                        variant={pack.is_active ? 'outline' : 'solid'}
                        colorScheme={pack.is_active ? 'red' : 'green'}
                        leftIcon={pack.is_active ? <FiX /> : <FiCheck />}
                        onClick={() => doAction(
                          pack.is_active ? 'deactivate' : 'activate',
                          pack.name,
                          () => pack.is_active
                            ? api.domainPacks.deactivate(pack.name)
                            : api.domainPacks.activate(pack.name),
                        )}
                        isLoading={isLoading('activate') || isLoading('deactivate')}
                      >
                        {pack.is_active ? 'Désactiver' : 'Activer'}
                      </Button>

                      {pack.is_active && (
                        <Button
                          size="sm" variant="outline" colorScheme="blue"
                          leftIcon={<FiRefreshCw />}
                          onClick={() => {
                            setReprocessing(pack.name)
                            api.domainPacks.reprocess(pack.name)
                              .then(() => toast({ title: 'Reprocessing lancé', status: 'info', duration: 3000 }))
                              .catch(() => { setReprocessing(null); toast({ title: 'Erreur', status: 'error', duration: 3000 }) })
                          }}
                          isLoading={isReprocessing}
                        >
                          Reprocesser
                        </Button>
                      )}
                    </HStack>
                  )}

                  {/* Uninstall — désinstalle le container (pack reste dans la liste si builtin) */}
                  {pack.container_state !== 'not_installed' && !pack.is_active && (
                    <Button
                      size="xs" variant="ghost" colorScheme="red"
                      leftIcon={<FiTrash2 />}
                      onClick={() => doAction('uninstall', pack.name,
                        () => api.domainPacks.uninstall(pack.name)
                      )}
                      isLoading={isLoading('uninstall')}
                    >
                      Désinstaller
                    </Button>
                  )}

                  {/* Supprimer — uniquement pour les packs uploadés, quand désinstallé */}
                  {!pack.is_builtin && pack.container_state === 'not_installed' && (
                    <Button
                      size="xs" variant="ghost" colorScheme="red"
                      leftIcon={<FiTrash2 />}
                      onClick={() => doAction('delete', pack.name,
                        () => api.domainPacks.uninstall(pack.name)
                      )}
                      isLoading={isLoading('delete')}
                    >
                      Supprimer definitivement
                    </Button>
                  )}
                </VStack>
              </Box>
            )
          })}
        </SimpleGrid>
      )}
    </Box>
  )
}
