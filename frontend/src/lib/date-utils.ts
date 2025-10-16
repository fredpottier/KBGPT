/**
 * Utilitaires de formatage de dates avec support multilingue
 * Utilise l'API native Intl pour éviter les dépendances externes
 */

export type SupportedLocale = 'fr' | 'en' | 'es' | 'de'

/**
 * Formate une date en format relatif (il y a X jours, X hours ago, etc.)
 * Utilise Intl.RelativeTimeFormat pour le support multilingue natif
 *
 * @param date - Date à formater
 * @param locale - Locale (défaut: 'fr')
 * @returns Chaîne formatée (ex: "il y a 3 jours", "3 days ago")
 *
 * @example
 * formatDistanceToNow(new Date('2024-10-01'), 'fr') // "il y a 10 jours"
 * formatDistanceToNow(new Date('2024-10-01'), 'en') // "10 days ago"
 */
export function formatDistanceToNow(date: Date, locale: SupportedLocale = 'fr'): string {
  const now = new Date()
  const diffInSeconds = Math.floor((now.getTime() - date.getTime()) / 1000)

  const rtf = new Intl.RelativeTimeFormat(locale, {
    numeric: 'auto',  // "hier" au lieu de "il y a 1 jour"
    style: 'long'     // "il y a 3 jours" au lieu de "dans 3 j"
  })

  // Convertir en unité appropriée
  const absDiff = Math.abs(diffInSeconds)

  if (absDiff < 60) {
    return rtf.format(-Math.floor(diffInSeconds), 'second')
  }
  if (absDiff < 3600) {
    return rtf.format(-Math.floor(diffInSeconds / 60), 'minute')
  }
  if (absDiff < 86400) {
    return rtf.format(-Math.floor(diffInSeconds / 3600), 'hour')
  }
  if (absDiff < 2592000) { // ~30 jours
    return rtf.format(-Math.floor(diffInSeconds / 86400), 'day')
  }
  if (absDiff < 31536000) { // ~365 jours
    return rtf.format(-Math.floor(diffInSeconds / 2592000), 'month')
  }
  return rtf.format(-Math.floor(diffInSeconds / 31536000), 'year')
}

/**
 * Formate une date en format long localisé
 *
 * @example
 * formatDate(new Date('2024-10-11'), 'fr') // "11 octobre 2024"
 * formatDate(new Date('2024-10-11'), 'en') // "October 11, 2024"
 */
export function formatDate(date: Date, locale: SupportedLocale = 'fr'): string {
  return new Intl.DateTimeFormat(locale, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  }).format(date)
}

/**
 * Formate une date avec heure en format localisé
 *
 * @example
 * formatDateTime(new Date('2024-10-11T14:30'), 'fr') // "11 octobre 2024 à 14:30"
 * formatDateTime(new Date('2024-10-11T14:30'), 'en') // "October 11, 2024 at 2:30 PM"
 */
export function formatDateTime(date: Date, locale: SupportedLocale = 'fr'): string {
  return new Intl.DateTimeFormat(locale, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

/**
 * Formate une date en format court (11/10/2024)
 */
export function formatDateShort(date: Date, locale: SupportedLocale = 'fr'): string {
  return new Intl.DateTimeFormat(locale, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(date)
}
