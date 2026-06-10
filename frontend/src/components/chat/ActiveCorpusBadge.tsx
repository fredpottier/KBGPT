'use client'

/**
 * ActiveCorpusBadge — indique le corpus interrogé par le chat (CH_CORPUS_SWITCH).
 *
 * Utile en démo : on sait toujours sur quel corpus on pose des questions. Fail-soft
 * (rien affiché si l'info est indisponible). Le corpus se change dans Admin →
 * Configuration (CorpusSwitcher). Additif/isolé.
 */

import { Badge, Tooltip } from '@chakra-ui/react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'

export default function ActiveCorpusBadge() {
  const { data } = useQuery<any>({
    queryKey: ['admin', 'active-corpus'],
    queryFn: async () => (await api.activeCorpus.get()).data,
    refetchInterval: 20000,
    retry: false,
  })
  const corpus: string | undefined = data?.active_corpus
  if (!corpus) return null
  return (
    <Tooltip label="Corpus interrogé par le chat — modifiable dans Admin → Configuration">
      <Badge colorScheme="brand" variant="subtle" fontSize="xs" textTransform="none">
        Corpus : {corpus}
      </Badge>
    </Tooltip>
  )
}
