import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import './globals.css'
import { Providers } from './providers'
import MainLayout from '@/components/layout/MainLayout'
import { PRESET_THEME_INIT_SCRIPT } from '@/theme/PresetThemeProvider'

const inter = Inter({ subsets: ['latin'] })

export const metadata: Metadata = {
  title: 'OSMOSIS - Le Cortex Documentaire',
  description: 'OSMOSE - Intelligence sémantique avancée pour la recherche documentaire',
  icons: {
    // Monogramme « Pore décentré » — SVG adaptatif light/dark, .ico en repli
    icon: [
      { url: '/favicon.svg', type: 'image/svg+xml' },
      { url: '/favicon.ico', sizes: 'any' },
    ],
  },
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* Anti-FOUC: applique data-preset/data-theme depuis localStorage avant le render React */}
        <script dangerouslySetInnerHTML={{ __html: PRESET_THEME_INIT_SCRIPT }} />
      </head>
      <body className={inter.className} suppressHydrationWarning>
        <Providers>
          <MainLayout>
            {children}
          </MainLayout>
        </Providers>
      </body>
    </html>
  )
}