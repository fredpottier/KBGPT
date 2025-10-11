'use client'

import { createContext, useContext, useState, useEffect, ReactNode } from 'react'
import { SupportedLocale } from '@/lib/date-utils'

interface LocaleContextType {
  locale: SupportedLocale
  setLocale: (locale: SupportedLocale) => void
}

const LocaleContext = createContext<LocaleContextType | undefined>(undefined)

export function LocaleProvider({ children }: { children: ReactNode }) {
  // Détecter la langue du navigateur ou utiliser 'fr' par défaut
  const getInitialLocale = (): SupportedLocale => {
    if (typeof window === 'undefined') return 'fr'

    const saved = localStorage.getItem('locale') as SupportedLocale | null
    if (saved && ['fr', 'en', 'es', 'de'].includes(saved)) {
      return saved
    }

    const browserLocale = navigator.language.split('-')[0] as SupportedLocale
    return ['fr', 'en', 'es', 'de'].includes(browserLocale) ? browserLocale : 'fr'
  }

  const [locale, setLocaleState] = useState<SupportedLocale>(getInitialLocale())

  const setLocale = (newLocale: SupportedLocale) => {
    setLocaleState(newLocale)
    if (typeof window !== 'undefined') {
      localStorage.setItem('locale', newLocale)
    }
  }

  return (
    <LocaleContext.Provider value={{ locale, setLocale }}>
      {children}
    </LocaleContext.Provider>
  )
}

/**
 * Hook pour accéder à la locale courante et la modifier
 *
 * @example
 * const { locale, setLocale } = useLocale()
 * setLocale('en')
 */
export function useLocale() {
  const context = useContext(LocaleContext)
  if (context === undefined) {
    throw new Error('useLocale must be used within a LocaleProvider')
  }
  return context
}
