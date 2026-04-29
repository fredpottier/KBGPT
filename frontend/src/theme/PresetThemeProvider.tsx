'use client'

/**
 * PresetThemeProvider — multi-preset (Dark Elegance / Fusion) × multi-mode (light / dark).
 *
 * Pose les attributs `data-preset` et `data-theme` sur <html>.
 * Persiste le choix utilisateur en localStorage.
 *
 * Default : preset=fusion, mode=light.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

export type ThemePreset = 'fusion' | 'dark-elegance'
export type ThemeMode = 'light' | 'dark'

const STORAGE_KEY_PRESET = 'osmosis.theme.preset'
const STORAGE_KEY_MODE = 'osmosis.theme.mode'

const DEFAULT_PRESET: ThemePreset = 'fusion'
const DEFAULT_MODE: ThemeMode = 'light'

interface PresetThemeContextValue {
  preset: ThemePreset
  mode: ThemeMode
  setPreset: (p: ThemePreset) => void
  setMode: (m: ThemeMode) => void
  toggleMode: () => void
}

const PresetThemeContext = createContext<PresetThemeContextValue | null>(null)

export const ALL_PRESETS: { id: ThemePreset; label: string; description: string }[] = [
  {
    id: 'fusion',
    label: 'Fusion',
    description: 'Light canonique, Graphite + Paper + Viridian — sobre et institutionnel',
  },
  {
    id: 'dark-elegance',
    label: 'Dark Elegance',
    description: 'Charcoal + Blue-slate + Teal — design d\'origine, dark first',
  },
]

function readStoredPreset(): ThemePreset {
  if (typeof window === 'undefined') return DEFAULT_PRESET
  const v = window.localStorage.getItem(STORAGE_KEY_PRESET)
  return v === 'dark-elegance' || v === 'fusion' ? v : DEFAULT_PRESET
}

function readStoredMode(): ThemeMode {
  if (typeof window === 'undefined') return DEFAULT_MODE
  const v = window.localStorage.getItem(STORAGE_KEY_MODE)
  return v === 'light' || v === 'dark' ? v : DEFAULT_MODE
}

function applyHtmlAttrs(preset: ThemePreset, mode: ThemeMode) {
  if (typeof document === 'undefined') return
  const html = document.documentElement
  html.setAttribute('data-preset', preset)
  html.setAttribute('data-theme', mode)
}

export function PresetThemeProvider({ children }: { children: ReactNode }) {
  const [preset, setPresetState] = useState<ThemePreset>(DEFAULT_PRESET)
  const [mode, setModeState] = useState<ThemeMode>(DEFAULT_MODE)

  // Mount : read storage and apply
  useEffect(() => {
    const p = readStoredPreset()
    const m = readStoredMode()
    setPresetState(p)
    setModeState(m)
    applyHtmlAttrs(p, m)
  }, [])

  const setPreset = useCallback((p: ThemePreset) => {
    setPresetState(p)
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(STORAGE_KEY_PRESET, p)
    }
    applyHtmlAttrs(p, mode)
  }, [mode])

  const setMode = useCallback((m: ThemeMode) => {
    setModeState(m)
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(STORAGE_KEY_MODE, m)
    }
    applyHtmlAttrs(preset, m)
  }, [preset])

  const toggleMode = useCallback(() => {
    setMode(mode === 'light' ? 'dark' : 'light')
  }, [mode, setMode])

  const value = useMemo<PresetThemeContextValue>(
    () => ({ preset, mode, setPreset, setMode, toggleMode }),
    [preset, mode, setPreset, setMode, toggleMode],
  )

  return (
    <PresetThemeContext.Provider value={value}>
      {children}
    </PresetThemeContext.Provider>
  )
}

export function usePresetTheme(): PresetThemeContextValue {
  const ctx = useContext(PresetThemeContext)
  if (!ctx) {
    throw new Error('usePresetTheme must be used within PresetThemeProvider')
  }
  return ctx
}

/**
 * Script anti-FOUC : à injecter en haut du <head> (via dangerouslySetInnerHTML)
 * pour appliquer preset+mode AVANT le rendering React (évite le flash).
 */
export const PRESET_THEME_INIT_SCRIPT = `
(function() {
  try {
    var p = localStorage.getItem('${STORAGE_KEY_PRESET}');
    var m = localStorage.getItem('${STORAGE_KEY_MODE}');
    if (p !== 'fusion' && p !== 'dark-elegance') p = '${DEFAULT_PRESET}';
    if (m !== 'light' && m !== 'dark') m = '${DEFAULT_MODE}';
    document.documentElement.setAttribute('data-preset', p);
    document.documentElement.setAttribute('data-theme', m);
  } catch (e) {}
})();
`
