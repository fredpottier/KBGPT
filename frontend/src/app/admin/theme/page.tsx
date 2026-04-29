'use client'

import { ALL_PRESETS, usePresetTheme, type ThemeMode, type ThemePreset } from '@/theme/PresetThemeProvider'

/**
 * Page admin /admin/theme
 *
 * Permet de basculer entre les presets (Dark Elegance / Fusion) et les modes (light/dark).
 * Le switch est immédiat et global. Persistance localStorage par utilisateur/device.
 */
export default function ThemeAdminPage() {
  const { preset, mode, setPreset, setMode } = usePresetTheme()

  return (
    <div
      style={{
        padding: 'var(--space-7)',
        maxWidth: 1100,
        margin: '0 auto',
        background: 'var(--bg-canvas)',
        minHeight: '100vh',
        color: 'var(--fg-primary)',
        fontFamily: 'var(--font-sans)',
      }}
    >
      <header style={{ marginBottom: 'var(--space-8)' }}>
        <p
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 'var(--text-xs)',
            letterSpacing: 'var(--tracking-mono)',
            color: 'var(--fg-muted)',
            textTransform: 'uppercase',
            marginBottom: 'var(--space-2)',
          }}
        >
          Admin · Theme
        </p>
        <h1
          style={{
            fontSize: 'var(--text-3xl)',
            fontWeight: 'var(--weight-semibold)',
            letterSpacing: 'var(--tracking-tight)',
            lineHeight: 'var(--leading-tight)',
            marginBottom: 'var(--space-3)',
          }}
        >
          Apparence
        </h1>
        <p
          style={{
            fontSize: 'var(--text-md)',
            color: 'var(--fg-secondary)',
            lineHeight: 'var(--leading-normal)',
            maxWidth: 720,
          }}
        >
          Choisissez le preset visuel et le mode (light/dark). La préférence est sauvegardée localement
          dans ce navigateur.
        </p>
      </header>

      {/* Section : Preset */}
      <section style={{ marginBottom: 'var(--space-9)' }}>
        <h2
          style={{
            fontSize: 'var(--text-lg)',
            fontWeight: 'var(--weight-semibold)',
            marginBottom: 'var(--space-4)',
          }}
        >
          Preset
        </h2>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
            gap: 'var(--space-4)',
          }}
        >
          {ALL_PRESETS.map((p) => {
            const active = p.id === preset
            return (
              <button
                key={p.id}
                onClick={() => setPreset(p.id as ThemePreset)}
                style={{
                  textAlign: 'left',
                  padding: 'var(--space-5)',
                  background: 'var(--bg-surface)',
                  border: `2px solid ${active ? 'var(--accent)' : 'var(--border-default)'}`,
                  borderRadius: 'var(--radius-md)',
                  cursor: 'pointer',
                  transition: `all var(--motion-base) var(--easing-standard)`,
                  boxShadow: active ? 'var(--shadow-md)' : 'var(--shadow-sm)',
                }}
              >
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    marginBottom: 'var(--space-3)',
                  }}
                >
                  <span
                    style={{
                      fontSize: 'var(--text-md)',
                      fontWeight: 'var(--weight-semibold)',
                      color: 'var(--fg-primary)',
                    }}
                  >
                    {p.label}
                  </span>
                  {active && (
                    <span
                      style={{
                        fontFamily: 'var(--font-mono)',
                        fontSize: 'var(--text-xs)',
                        letterSpacing: 'var(--tracking-mono)',
                        color: 'var(--accent-on)',
                        background: 'var(--accent)',
                        padding: '2px 8px',
                        borderRadius: 'var(--radius-sm)',
                        textTransform: 'uppercase',
                      }}
                    >
                      Actif
                    </span>
                  )}
                </div>
                <p
                  style={{
                    fontSize: 'var(--text-sm)',
                    color: 'var(--fg-secondary)',
                    lineHeight: 'var(--leading-normal)',
                  }}
                >
                  {p.description}
                </p>
              </button>
            )
          })}
        </div>
      </section>

      {/* Section : Mode */}
      <section style={{ marginBottom: 'var(--space-9)' }}>
        <h2
          style={{
            fontSize: 'var(--text-lg)',
            fontWeight: 'var(--weight-semibold)',
            marginBottom: 'var(--space-4)',
          }}
        >
          Mode
        </h2>
        <div style={{ display: 'flex', gap: 'var(--space-3)' }}>
          {(['light', 'dark'] as ThemeMode[]).map((m) => {
            const active = m === mode
            return (
              <button
                key={m}
                onClick={() => setMode(m)}
                style={{
                  padding: 'var(--space-3) var(--space-5)',
                  background: active ? 'var(--accent)' : 'var(--bg-surface)',
                  color: active ? 'var(--accent-on)' : 'var(--fg-primary)',
                  border: `1px solid ${active ? 'var(--accent)' : 'var(--border-default)'}`,
                  borderRadius: 'var(--radius-sm)',
                  fontSize: 'var(--text-sm)',
                  fontWeight: 'var(--weight-medium)',
                  cursor: 'pointer',
                  transition: `all var(--motion-fast) var(--easing-standard)`,
                  textTransform: 'capitalize',
                  minWidth: 100,
                }}
              >
                {m}
              </button>
            )
          })}
        </div>
      </section>

      {/* Section : Preview tokens */}
      <section style={{ marginBottom: 'var(--space-9)' }}>
        <h2
          style={{
            fontSize: 'var(--text-lg)',
            fontWeight: 'var(--weight-semibold)',
            marginBottom: 'var(--space-4)',
          }}
        >
          Preview — palette active
        </h2>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
            gap: 'var(--space-3)',
          }}
        >
          <Swatch label="bg-canvas" varName="--bg-canvas" />
          <Swatch label="bg-surface" varName="--bg-surface" />
          <Swatch label="bg-surface-alt" varName="--bg-surface-alt" />
          <Swatch label="accent" varName="--accent" />
          <Swatch label="accent-soft" varName="--accent-soft" />
          <Swatch label="success-base" varName="--success-base" />
          <Swatch label="warning-base" varName="--warning-base" />
          <Swatch label="error-base" varName="--error-base" />
          <Swatch label="info-base" varName="--info-base" />
          <Swatch label="border-default" varName="--border-default" />
          <Swatch label="border-strong" varName="--border-strong" />
        </div>
      </section>

      {/* Preview composants */}
      <section>
        <h2
          style={{
            fontSize: 'var(--text-lg)',
            fontWeight: 'var(--weight-semibold)',
            marginBottom: 'var(--space-4)',
          }}
        >
          Preview — composants
        </h2>
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: 'var(--space-3)',
            marginBottom: 'var(--space-5)',
          }}
        >
          <DemoButton variant="primary">Primary</DemoButton>
          <DemoButton variant="secondary">Secondary</DemoButton>
          <DemoButton variant="ghost">Ghost</DemoButton>
        </div>
        <div
          style={{
            padding: 'var(--space-5)',
            background: 'var(--bg-surface)',
            border: '1px solid var(--border-default)',
            borderRadius: 'var(--radius-md)',
            maxWidth: 600,
          }}
        >
          <p style={{ fontSize: 'var(--text-md)', fontWeight: 'var(--weight-semibold)', marginBottom: 'var(--space-2)' }}>
            Card surface
          </p>
          <p style={{ fontSize: 'var(--text-sm)', color: 'var(--fg-secondary)', marginBottom: 'var(--space-3)' }}>
            Texte secondaire dans une carte. Le rendu suit le preset et le mode courant.
          </p>
          <p style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)', color: 'var(--fg-muted)', letterSpacing: 'var(--tracking-mono)' }}>
            METADATA · {preset.toUpperCase()} · {mode.toUpperCase()}
          </p>
        </div>
      </section>
    </div>
  )
}

function Swatch({ label, varName }: { label: string; varName: string }) {
  return (
    <div
      style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border-default)',
        borderRadius: 'var(--radius-sm)',
        padding: 'var(--space-3)',
      }}
    >
      <div
        style={{
          width: '100%',
          height: 56,
          background: `var(${varName})`,
          border: '1px solid var(--border-faint)',
          borderRadius: 'var(--radius-sm)',
          marginBottom: 'var(--space-2)',
        }}
      />
      <p style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)', color: 'var(--fg-muted)', letterSpacing: 'var(--tracking-mono)' }}>
        {label}
      </p>
    </div>
  )
}

function DemoButton({
  variant,
  children,
}: {
  variant: 'primary' | 'secondary' | 'ghost'
  children: React.ReactNode
}) {
  const styles: Record<string, React.CSSProperties> = {
    primary: {
      background: 'var(--accent)',
      color: 'var(--accent-on)',
      border: '1px solid var(--accent)',
    },
    secondary: {
      background: 'var(--bg-surface-alt)',
      color: 'var(--fg-primary)',
      border: '1px solid var(--border-default)',
    },
    ghost: {
      background: 'transparent',
      color: 'var(--accent)',
      border: '1px solid transparent',
    },
  }
  return (
    <button
      style={{
        ...styles[variant],
        padding: 'var(--space-2) var(--space-4)',
        borderRadius: 'var(--radius-sm)',
        fontSize: 'var(--text-sm)',
        fontWeight: 'var(--weight-medium)',
        cursor: 'pointer',
        transition: 'all var(--motion-fast) var(--easing-standard)',
      }}
    >
      {children}
    </button>
  )
}
