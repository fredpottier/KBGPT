'use client'

/**
 * Legacy Pass 2 page - Redirect to new Enrichment page
 *
 * Cette page redirige automatiquement vers /admin/enrichment
 * qui contient la nouvelle interface Pass 2 + Pass 3 ADR-compliant.
 */

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { Center, Spinner, Text, VStack } from '@chakra-ui/react'

export default function Pass2RedirectPage() {
  const router = useRouter()

  useEffect(() => {
    router.replace('/admin/enrichment')
  }, [router])

  return (
    <Center h="200px">
      <VStack spacing={3}>
        <Spinner color="brand.500" />
        <Text fontSize="sm" color="text.muted">
          Redirection vers Enrichissement KG...
        </Text>
      </VStack>
    </Center>
  )
}
