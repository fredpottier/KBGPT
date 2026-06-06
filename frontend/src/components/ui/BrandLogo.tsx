/**
 * BrandLogo — monogramme OSMOSIS « Pore décentré ».
 *
 * Anneau (stroke 2.1) + point décentré (r 2.1, cx 15.2) sur une grille 24×24.
 * Le pore est décalé vers la droite : il signale la direction osmotique.
 *
 * Couleurs branchées sur les variables CSS canoniques → le logo suit
 * automatiquement le preset et le mode jour/nuit :
 * - anneau = var(--fg-primary)  (graphite en clair, papier en sombre)
 * - pore   = var(--accent)      (viridian #2E5D4E / #5EC28C en Fusion)
 * ce qui reproduit exactement les variantes canoniques de la charte
 * (doc de marque : brand-logo.html, 06/06/2026).
 *
 * `mono` force le pore à la couleur de l'anneau (tampon, filigrane, 1 couleur).
 */

interface BrandLogoProps {
  /** Taille en px (le SVG est carré). Défaut 32. */
  size?: number
  /** Variante mono-encre : pore = anneau. */
  mono?: boolean
  className?: string
}

export function BrandLogo({ size = 32, mono = false, className }: BrandLogoProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      role="img"
      aria-label="OSMOSIS"
      className={className}
      style={{ flexShrink: 0 }}
    >
      <circle cx="12" cy="12" r="9" fill="none" stroke="var(--fg-primary)" strokeWidth="2.1" />
      <circle cx="15.2" cy="12" r="2.1" fill={mono ? 'var(--fg-primary)' : 'var(--accent)'} />
    </svg>
  )
}

export default BrandLogo
