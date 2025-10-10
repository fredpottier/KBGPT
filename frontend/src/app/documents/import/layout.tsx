'use client'

import { ProtectedRoute } from '@/components/auth/ProtectedRoute'

export default function DocumentImportLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <ProtectedRoute requireRole="editor">
      {children}
    </ProtectedRoute>
  )
}
