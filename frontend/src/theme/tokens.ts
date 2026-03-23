/**
 * Design Tokens - OSMOS
 *
 * Tokens de design centralisés pour faciliter le changement de thème.
 * Ces tokens sont utilisés par les thèmes dark et light.
 */

// Palette de base "Dark Elegance" — charcoal (pas near-black) pour confort visuel
export const palette = {
  // Fonds — remontés pour réduire la fatigue visuelle (charcoal > near-black)
  dark: {
    900: '#111118',    // Fond principal (was #0a0a0f — trop noir)
    800: '#171724',    // Fond élevé (was #12121a)
    700: '#1e1e32',    // Surfaces/cartes (was #1a1a2e)
    600: '#2a2a40',    // Surfaces hover (was #252538)
    500: '#35355a',    // Borders actives (was #2f2f45)
    400: '#454570',    // Borders (was #3d3d5c)
  },

  // Textes — muted remonté pour WCAG AA (4.5:1 minimum)
  text: {
    primary: '#f4f4f5',      // Texte principal
    secondary: '#a1a1aa',    // Texte secondaire
    muted: '#8b8b95',        // Texte atténué (was #71717a — 3.2:1, now ~5.2:1)
    inverse: '#18181b',      // Texte sur fond clair
  },

  // Accents - Blue-slate (plus credible enterprise) + Teal secondaire
  accent: {
    primary: '#5B7FFF',      // Blue-slate (was #6366f1 indigo — trop SaaS générique)
    primaryHover: '#7B9AFF', // Blue-slate hover
    primaryMuted: '#4A6AE5', // Blue-slate sombre

    secondary: '#0D9488',    // Deep teal (was #22d3ee cyan — trop flashy)
    secondaryHover: '#14B8A6',
    secondaryMuted: '#0F766E',

    glow: 'rgba(91, 127, 255, 0.15)', // Glow effect
    glowStrong: 'rgba(91, 127, 255, 0.3)',
  },

  // Sémantiques
  semantic: {
    success: '#22c55e',
    successMuted: '#16a34a',
    warning: '#f59e0b',
    warningMuted: '#d97706',
    error: '#ef4444',
    errorMuted: '#dc2626',
    info: '#3b82f6',
    infoMuted: '#2563eb',
  },

  // Overlays
  overlay: {
    light: 'rgba(255, 255, 255, 0.05)',
    medium: 'rgba(255, 255, 255, 0.1)',
    dark: 'rgba(0, 0, 0, 0.5)',
  },
}

// Palette Light mode — clean, professionnelle, pas fade
export const paletteLight = {
  dark: {
    900: '#ffffff',
    800: '#f8f9fb',
    700: '#f1f3f5',
    600: '#e5e7eb',
    500: '#d1d5db',
    400: '#9ca3af',
  },

  text: {
    primary: '#111827',
    secondary: '#4b5563',
    muted: '#6b7280',
    inverse: '#f4f4f5',
  },

  accent: palette.accent, // Mêmes accents blue-slate
  semantic: palette.semantic,

  overlay: {
    light: 'rgba(0, 0, 0, 0.02)',
    medium: 'rgba(0, 0, 0, 0.06)',
    dark: 'rgba(0, 0, 0, 0.3)',
  },
}

// Typography
export const typography = {
  fonts: {
    heading: '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    body: '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    mono: '"JetBrains Mono", "Fira Code", monospace',
  },

  fontSizes: {
    xs: '0.75rem',
    sm: '0.875rem',
    md: '1rem',
    lg: '1.125rem',
    xl: '1.25rem',
    '2xl': '1.5rem',
    '3xl': '1.875rem',
    '4xl': '2.25rem',
  },

  fontWeights: {
    normal: 400,
    medium: 500,
    semibold: 600,
    bold: 700,
  },

  lineHeights: {
    tight: 1.25,
    normal: 1.5,
    relaxed: 1.75,
  },
}

// Spacing (8px base)
export const spacing = {
  px: '1px',
  0: '0',
  0.5: '0.125rem',
  1: '0.25rem',
  2: '0.5rem',
  3: '0.75rem',
  4: '1rem',
  5: '1.25rem',
  6: '1.5rem',
  8: '2rem',
  10: '2.5rem',
  12: '3rem',
  16: '4rem',
  20: '5rem',
  24: '6rem',
}

// Border radius
export const radii = {
  none: '0',
  sm: '0.25rem',
  md: '0.375rem',
  lg: '0.5rem',
  xl: '0.75rem',
  '2xl': '1rem',
  '3xl': '1.5rem',
  full: '9999px',
}

// Shadows (style glow pour dark mode)
export const shadows = {
  sm: '0 1px 2px 0 rgba(0, 0, 0, 0.05)',
  md: '0 4px 6px -1px rgba(0, 0, 0, 0.1)',
  lg: '0 10px 15px -3px rgba(0, 0, 0, 0.1)',
  xl: '0 20px 25px -5px rgba(0, 0, 0, 0.1)',

  // Glow effects pour dark mode
  glow: {
    sm: `0 0 10px ${palette.accent.glow}`,
    md: `0 0 20px ${palette.accent.glow}`,
    lg: `0 0 30px ${palette.accent.glowStrong}`,
    accent: `0 0 20px ${palette.accent.glow}, 0 0 40px ${palette.accent.glow}`,
  },

  // Inner shadows
  inner: 'inset 0 2px 4px 0 rgba(0, 0, 0, 0.05)',
}

// Transitions
export const transitions = {
  fast: '150ms cubic-bezier(0.4, 0, 0.2, 1)',
  normal: '200ms cubic-bezier(0.4, 0, 0.2, 1)',
  slow: '300ms cubic-bezier(0.4, 0, 0.2, 1)',

  // Spring-like pour interactions premium
  spring: '300ms cubic-bezier(0.34, 1.56, 0.64, 1)',

  // Easing functions
  easing: {
    easeIn: 'cubic-bezier(0.4, 0, 1, 1)',
    easeOut: 'cubic-bezier(0, 0, 0.2, 1)',
    easeInOut: 'cubic-bezier(0.4, 0, 0.2, 1)',
  },
}

// Z-index scale
export const zIndices = {
  hide: -1,
  auto: 'auto',
  base: 0,
  docked: 10,
  dropdown: 1000,
  sticky: 1100,
  banner: 1200,
  overlay: 1300,
  modal: 1400,
  popover: 1500,
  toast: 1700,
  tooltip: 1800,
}

// Breakpoints
export const breakpoints = {
  sm: '640px',
  md: '768px',
  lg: '1024px',
  xl: '1280px',
  '2xl': '1536px',
}
