'use client'

import { ProtectedRoute } from '@/components/auth/ProtectedRoute'

export default function DocumentStatusLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <ProtectedRoute requireRole="viewer">
      {children}
    </ProtectedRoute>
  )
}
