'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'

export default function DocumentsPage() {
  const router = useRouter()

  useEffect(() => {
    // Rediriger vers la page d'import par défaut
    router.replace('/documents/import')
  }, [router])

  return null
}