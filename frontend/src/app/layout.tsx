import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import './globals.css'
import { Providers } from './providers'
import MainLayout from '@/components/layout/MainLayout'

const inter = Inter({ subsets: ['latin'] })

export const metadata: Metadata = {
  title: 'SAP Knowledge Base',
  description: 'Intelligent document search and chat interface for SAP knowledge base',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <Providers>
          <MainLayout>
            {children}
          </MainLayout>
        </Providers>
      </body>
    </html>
  )
}