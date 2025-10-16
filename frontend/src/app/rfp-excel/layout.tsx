'use client'

import { ProtectedRoute } from '@/components/auth/ProtectedRoute'

export default function RfpExcelLayout({
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
