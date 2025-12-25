/**
 * Dark Elegance Theme - OSMOS
 *
 * Thème sombre premium inspiré de Linear/Raycast
 * Utilise les tokens centralisés pour faciliter les modifications
 */

import { extendTheme, type ThemeConfig } from '@chakra-ui/react'
import { palette, typography, radii, shadows, transitions, zIndices } from './tokens'

// Configuration du mode couleur
const config: ThemeConfig = {
  initialColorMode: 'dark',
  useSystemColorMode: false,
}

// Couleurs Chakra mappées depuis les tokens
const colors = {
  // Fond principal
  bg: {
    primary: palette.dark[900],
    secondary: palette.dark[800],
    tertiary: palette.dark[700],
    hover: palette.dark[600],
    active: palette.dark[500],
  },

  // Surfaces (cartes, modals, etc.)
  surface: {
    default: palette.dark[700],
    raised: palette.dark[600],
    overlay: palette.dark[800],
  },

  // Borders
  border: {
    default: palette.dark[400],
    muted: palette.dark[500],
    active: palette.accent.primary,
  },

  // Textes
  text: palette.text,

  // Brand/Accent (remplace l'ancien "brand")
  brand: {
    50: palette.accent.glow,
    100: '#e0e7ff',
    200: '#c7d2fe',
    300: '#a5b4fc',
    400: '#818cf8',
    500: palette.accent.primary,
    600: palette.accent.primaryMuted,
    700: '#4338ca',
    800: '#3730a3',
    900: '#312e81',
  },

  // Accent secondaire (cyan)
  accent: {
    50: '#ecfeff',
    100: '#cffafe',
    200: '#a5f3fc',
    300: '#67e8f9',
    400: palette.accent.secondary,
    500: '#06b6d4',
    600: '#0891b2',
    700: '#0e7490',
    800: '#155e75',
    900: '#164e63',
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

// Styles globaux
const styles = {
  global: {
    'html, body': {
      bg: 'bg.primary',
      color: 'text.primary',
      fontFamily: typography.fonts.body,
      lineHeight: typography.lineHeights.normal,
      WebkitFontSmoothing: 'antialiased',
      MozOsxFontSmoothing: 'grayscale',
    },

    // Scrollbar custom
    '::-webkit-scrollbar': {
      width: '8px',
      height: '8px',
    },
    '::-webkit-scrollbar-track': {
      bg: 'bg.secondary',
    },
    '::-webkit-scrollbar-thumb': {
      bg: 'border.default',
      borderRadius: 'full',
      '&:hover': {
        bg: 'border.active',
      },
    },

    // Selection
    '::selection': {
      bg: 'brand.500',
      color: 'white',
    },

    // Focus visible
    '*:focus-visible': {
      outline: 'none',
      boxShadow: shadows.glow.md,
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

  // Menus dropdown
  Menu: {
    baseStyle: {
      list: {
        bg: 'surface.default',
        borderColor: 'border.default',
        borderRadius: radii.xl,
        boxShadow: 'xl',
        py: 2,
      },
      item: {
        bg: 'transparent',
        color: 'text.primary',
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
