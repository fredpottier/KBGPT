/**
 * Dark Elegance Theme - OSMOS
 *
 * Thème sombre premium inspiré de Linear/Raycast
 * Utilise les tokens centralisés pour faciliter les modifications
 */

import { extendTheme, type ThemeConfig } from '@chakra-ui/react'
import { palette, paletteLight, typography, radii, shadows, transitions, zIndices } from './tokens'

// Configuration du mode couleur
const config: ThemeConfig = {
  initialColorMode: 'dark',
  useSystemColorMode: false,
}

// Couleurs Chakra statiques (non-semantic — marches brand, accent, gray)
const colors = {

  // Brand/Accent (remplace l'ancien "brand")
  brand: {
    50: palette.accent.glow,
    100: '#dbeafe',
    200: '#bfdbfe',
    300: '#93c5fd',
    400: '#7B9AFF',
    500: palette.accent.primary,
    600: palette.accent.primaryMuted,
    700: '#3B5FC7',
    800: '#2D4A9E',
    900: '#1E3A7A',
  },

  // Accent secondaire (deep teal)
  accent: {
    50: '#f0fdfa',
    100: '#ccfbf1',
    200: '#99f6e4',
    300: '#5eead4',
    400: '#2dd4bf',
    500: palette.accent.secondary,
    600: palette.accent.secondaryMuted,
    700: '#0F766E',
    800: '#115E59',
    900: '#134E4A',
  },

  // Sémantiques
  success: {
    500: palette.semantic.success,
    600: palette.semantic.successMuted,
  },
  warning: {
    500: palette.semantic.warning,
    600: palette.semantic.warningMuted,
  },
  error: {
    500: palette.semantic.error,
    600: palette.semantic.errorMuted,
  },

  // Gray scale pour compatibilité Chakra
  gray: {
    50: '#fafafa',
    100: '#f4f4f5',
    200: '#e4e4e7',
    300: '#d4d4d8',
    400: '#a1a1aa',
    500: '#71717a',
    600: '#52525b',
    700: palette.dark[700],
    800: palette.dark[800],
    900: palette.dark[900],
  },
}

// Semantic tokens — pointent vers les CSS vars canoniques (multi-preset).
// Le preset actif (Fusion / Dark Elegance) est defini par data-preset sur <html>
// dans preset-vars.css (cf. PresetThemeProvider).
const semanticTokens = {
  colors: {
    // Surfaces (legacy + canonical)
    'bg.primary':   'var(--bg-canvas)',
    'bg.canvas':    'var(--bg-canvas)',
    'bg.secondary': 'var(--bg-surface)',
    'bg.surface':   'var(--bg-surface)',
    'bg.tertiary':  'var(--bg-surface-alt)',
    'bg.hover':     'var(--bg-hover)',
    'bg.active':    'var(--bg-surface-alt)',

    'surface.default': 'var(--bg-surface)',
    'surface.raised':  'var(--bg-surface-alt)',
    'surface.overlay': 'var(--bg-overlay)',

    // Borders
    'border.default': 'var(--border-default)',
    'border.muted':   'var(--border-faint)',
    'border.active':  'var(--border-strong)',

    // Texts (legacy + canonical)
    'text.primary':   'var(--fg-primary)',
    'fg.primary':     'var(--fg-primary)',
    'text.secondary': 'var(--fg-secondary)',
    'fg.secondary':   'var(--fg-secondary)',
    'text.muted':     'var(--fg-muted)',
    'fg.muted':       'var(--fg-muted)',
    'text.inverse':   'var(--fg-inverse)',
    'fg.inverse':     'var(--fg-inverse)',

    // Accent (suit le preset)
    'accent':         'var(--accent)',
    'accent.hover':   'var(--accent-hover)',
    'accent.soft':    'var(--accent-soft)',
    'accent.on':      'var(--accent-on)',
    // brand.* override pour ColorScheme="brand"
    'brand.50':       'var(--accent-soft)',
    'brand.400':      'var(--accent-hover)',
    'brand.500':      'var(--accent)',
    'brand.600':      'var(--accent-hover)',
  },
  radii: {
    none: 'var(--radius-none)',
    sm:   'var(--radius-sm)',
    md:   'var(--radius-md)',
    lg:   'var(--radius-md)',
    xl:   'var(--radius-md)',
    '2xl':'var(--radius-md)',
    full: 'var(--radius-pill)',
  },
}

// Styles globaux — minimaux. Le fond/text sont gérés par globals.css (var(--bg-canvas)).
// Évite que Chakra override les CSS vars du preset.
const styles = {
  global: {
    'html, body': {
      fontFamily: typography.fonts.body,
      lineHeight: typography.lineHeights.normal,
      WebkitFontSmoothing: 'antialiased',
      MozOsxFontSmoothing: 'grayscale',
    },
  },
}

// Composants avec styles dark mode
const components = {
  // Boutons
  Button: {
    baseStyle: {
      fontWeight: typography.fontWeights.medium,
      borderRadius: radii.lg,
      transition: transitions.normal,
    },
    variants: {
      // Bouton principal avec glow
      solid: {
        bg: 'brand.500',
        color: 'white',
        _hover: {
          bg: 'brand.400',
          boxShadow: shadows.glow.sm,
          transform: 'translateY(-1px)',
        },
        _active: {
          bg: 'brand.600',
          transform: 'translateY(0)',
        },
      },
      // Bouton ghost
      ghost: {
        color: 'text.secondary',
        _hover: {
          bg: 'bg.hover',
          color: 'text.primary',
        },
      },
      // Bouton outline
      outline: {
        borderColor: 'border.default',
        color: 'text.primary',
        _hover: {
          bg: 'bg.hover',
          borderColor: 'brand.500',
        },
      },
    },
    defaultProps: {
      variant: 'solid',
      colorScheme: 'brand',
    },
  },

  // Cartes
  Card: {
    baseStyle: {
      container: {
        bg: 'surface.default',
        borderRadius: radii.xl,
        border: '1px solid',
        borderColor: 'border.default',
        transition: transitions.normal,
        _hover: {
          borderColor: 'border.active',
          boxShadow: shadows.glow.sm,
        },
      },
    },
  },

  // Inputs
  Input: {
    variants: {
      outline: {
        field: {
          bg: 'bg.secondary',
          borderColor: 'border.default',
          borderRadius: radii.lg,
          color: 'text.primary',
          _placeholder: {
            color: 'text.muted',
          },
          _hover: {
            borderColor: 'border.muted',
          },
          _focus: {
            borderColor: 'brand.500',
            boxShadow: shadows.glow.sm,
          },
        },
      },
      filled: {
        field: {
          bg: 'bg.tertiary',
          borderColor: 'transparent',
          _hover: {
            bg: 'bg.hover',
          },
          _focus: {
            bg: 'bg.tertiary',
            borderColor: 'brand.500',
          },
        },
      },
    },
    defaultProps: {
      variant: 'outline',
    },
  },

  // Menus dropdown — bg.canvas pour eviter le contraste blanc en Fusion light
  Menu: {
    baseStyle: {
      list: {
        bg: 'bg.canvas',
        borderColor: 'border.default',
        borderRadius: 'md',
        boxShadow: 'lg',
        py: 2,
      },
      item: {
        bg: 'transparent',
        color: 'fg.primary',
        _hover: {
          bg: 'bg.hover',
        },
        _focus: {
          bg: 'bg.hover',
        },
      },
    },
  },

  // Modal
  Modal: {
    baseStyle: {
      overlay: {
        bg: 'blackAlpha.700',
        backdropFilter: 'blur(8px)',
      },
      dialog: {
        bg: 'surface.default',
        borderRadius: radii['2xl'],
        border: '1px solid',
        borderColor: 'border.default',
      },
      header: {
        color: 'text.primary',
      },
      body: {
        color: 'text.secondary',
      },
    },
  },

  // Tooltip
  Tooltip: {
    baseStyle: {
      bg: 'surface.raised',
      color: 'text.primary',
      borderRadius: radii.md,
      px: 3,
      py: 2,
      fontSize: 'sm',
      boxShadow: 'lg',
    },
  },

  // Badges
  Badge: {
    baseStyle: {
      borderRadius: radii.md,
      fontWeight: typography.fontWeights.medium,
      textTransform: 'none',
    },
    variants: {
      subtle: {
        bg: 'bg.hover',
        color: 'text.primary',
      },
      solid: {
        bg: 'brand.500',
        color: 'white',
      },
    },
  },

  // Spinner
  Spinner: {
    defaultProps: {
      color: 'brand.500',
    },
  },

  // Tabs
  Tabs: {
    variants: {
      line: {
        tab: {
          color: 'text.muted',
          _selected: {
            color: 'brand.400',
            borderColor: 'brand.400',
          },
          _hover: {
            color: 'text.primary',
          },
        },
      },
      enclosed: {
        tab: {
          bg: 'transparent',
          borderColor: 'border.default',
          _selected: {
            bg: 'surface.default',
            borderColor: 'brand.500',
            color: 'brand.400',
          },
        },
        tablist: {
          borderColor: 'border.default',
        },
      },
    },
  },

  // Accordion (pour panels expandables)
  Accordion: {
    baseStyle: {
      container: {
        borderColor: 'border.default',
      },
      button: {
        color: 'text.primary',
        _hover: {
          bg: 'bg.hover',
        },
        _expanded: {
          bg: 'bg.tertiary',
        },
      },
      panel: {
        bg: 'bg.secondary',
      },
    },
  },

  // Heading
  Heading: {
    baseStyle: {
      color: 'text.primary',
      fontWeight: typography.fontWeights.semibold,
    },
  },

  // Text
  Text: {
    baseStyle: {
      color: 'text.primary',
    },
  },

  // Link
  Link: {
    baseStyle: {
      color: 'brand.400',
      transition: transitions.fast,
      _hover: {
        color: 'brand.300',
        textDecoration: 'none',
      },
    },
  },

  // Divider
  Divider: {
    baseStyle: {
      borderColor: 'border.default',
    },
  },
}

// Export du thème complet
export const darkTheme = extendTheme({
  config,
  colors,
  semanticTokens,
  styles,
  components,
  fonts: typography.fonts,
  fontSizes: typography.fontSizes,
  fontWeights: typography.fontWeights,
  lineHeights: typography.lineHeights,
  radii,
  shadows: {
    ...shadows,
    outline: shadows.glow.sm,
  },
  zIndices,
})

export default darkTheme
