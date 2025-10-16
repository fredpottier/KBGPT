'use client'

import { ProtectedRoute } from '@/components/auth/ProtectedRoute'

export default function DocumentUploadLayout({
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
