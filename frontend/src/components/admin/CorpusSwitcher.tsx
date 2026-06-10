'use client'

/**
 * CorpusSwitcher — bascule du corpus actif global (chat + ingestion).
 *
 * Chantier CH_CORPUS_SWITCH : un seul bouton fait tourner TOUT le système sur le
 * tenant choisi (Neo4j propriété + Qdrant filtre payload, déjà câblés). Pratique
 * pour les démos (passer d'un corpus à l'autre) et pour ingérer un nouveau domaine.
 * Les imports en vol gardent leur tenant (estampillé à l'enqueue).
 *
 * Module additif/isolé : se monte d'un `<CorpusSwitcher />` dans la page admin.
 */

import { useState, useEffect } from 'react'
import {
  Box,
  HStack,
  VStack,
  Text,
  Icon,
  Badge,
  Select,
  Button,
  useToast,
} from '@chakra-ui/react'
import { FiLayers, FiCheck } from 'react-icons/fi'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'

interface TenantInfo {
  tenant_id: string
  n_claims: number
  n_docs: number
  is_own?: boolean
}

export default function CorpusSwitcher() {
  const toast = useToast()
  const qc = useQueryClient()
  const [selected, setSelected] = useState<string>('')

  const { data: activeData } = useQuery<any>({
    queryKey: ['admin', 'active-corpus'],
    queryFn: async () => (await api.activeCorpus.get()).data,
    refetchInterval: 15000,
  })
  const { data: tenantsData } = useQuery<any>({
    queryKey: ['admin', 'tenants'],
    queryFn: async () => (await api.tenants.list()).data,
  })

  const active: string = activeData?.active_corpus || 'default'
  const tenants: TenantInfo[] = tenantsData?.tenants || []

  // Initialise le sélecteur sur le corpus actif (une fois connu)
  useEffect(() => {
    if (active && !selected) setSelected(active)
  }, [active, selected])

  const switchMutation = useMutation({
    mutationFn: async (tenant_id: string) => (await api.activeCorpus.set(tenant_id)).data,
    onSuccess: (data: any) => {
      toast({
        title: 'Corpus actif basculé',
        description: `Tout le système tourne désormais sur « ${data.active_corpus} »`,
        status: 'success',
        duration: 4000,
      })
      qc.invalidateQueries({ queryKey: ['admin', 'active-corpus'] })
    },
    onError: (e: any) =>
      toast({
        title: 'Erreur',
        description: e?.response?.data?.detail || String(e),
        status: 'error',
        duration: 5000,
      }),
  })

  const dirty = !!selected && selected !== active
  const activeInfo = tenants.find((t) => t.tenant_id === active)

  return (
    <Box
      bg="bg.secondary"
      border="1px solid"
      borderColor="border.default"
      rounded="xl"
      overflow="hidden"
    >
      {/* Header */}
      <HStack px={5} py={4} borderBottom="1px solid" borderColor="border.default" bg="bg.tertiary">
        <Box
          w={10}
          h={10}
          rounded="lg"
          bg="rgba(99, 102, 241, 0.15)"
          display="flex"
          alignItems="center"
          justifyContent="center"
        >
          <Icon as={FiLayers} boxSize={5} color="brand.400" />
        </Box>
        <VStack align="start" spacing={0}>
          <Text fontWeight="semibold" color="text.primary">
            Corpus actif
          </Text>
          <Text fontSize="xs" color="text.muted">
            Chat et nouveaux imports tournent sur ce corpus
          </Text>
        </VStack>
      </HStack>

      {/* Body */}
      <Box p={5}>
        <VStack align="stretch" spacing={4}>
          {/* Corpus actif courant */}
          <HStack
            p={3}
            px={4}
            bg="rgba(99, 102, 241, 0.08)"
            border="1px solid"
            borderColor="border.default"
            rounded="lg"
            justify="space-between"
            flexWrap="wrap"
            gap={3}
          >
            <HStack spacing={3}>
              <Text fontSize="sm" color="text.secondary">
                Actuellement :
              </Text>
              <Badge colorScheme="brand" fontSize="sm" px={3} py={1} rounded="md">
                {active}
              </Badge>
              {activeInfo && (
                <Text fontSize="xs" color="text.muted">
                  {activeInfo.n_claims.toLocaleString()} claims · {activeInfo.n_docs} docs
                </Text>
              )}
            </HStack>
          </HStack>

          {/* Sélecteur + bascule */}
          <HStack spacing={3} flexWrap="wrap">
            <Text fontSize="sm" color="text.muted" minW="90px">
              Basculer sur :
            </Text>
            <Select
              size="sm"
              maxW="320px"
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
              bg="bg.secondary"
            >
              {tenants.map((t) => (
                <option key={t.tenant_id} value={t.tenant_id}>
                  {t.tenant_id} — {t.n_claims.toLocaleString()} claims · {t.n_docs} docs
                </option>
              ))}
              {/* garantit que le corpus actif figure même sans claims */}
              {!tenants.some((t) => t.tenant_id === active) && (
                <option value={active}>{active}</option>
              )}
            </Select>
            <Button
              size="sm"
              colorScheme="brand"
              leftIcon={<FiCheck />}
              isDisabled={!dirty}
              isLoading={switchMutation.isPending}
              onClick={() => switchMutation.mutate(selected)}
            >
              Activer
            </Button>
          </HStack>

          <Text fontSize="xs" color="text.muted">
            Les imports déjà en cours gardent leur corpus (estampillé au lancement). La
            bascule prend effet immédiatement pour le chat et les nouveaux dépôts dans
            <Text as="span" fontFamily="mono"> docs_in</Text>.
          </Text>
        </VStack>
      </Box>
    </Box>
  )
}
