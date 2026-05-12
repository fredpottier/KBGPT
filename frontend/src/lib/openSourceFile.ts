/**
 * openSourceFile — ouvre le fichier source d'un document dans un nouveau tab.
 *
 * Si `source` est une URL absolue (`http://`/`https://`), ouvre directement.
 * Sinon (= doc_id type `cs25_amdt_28_32f1a9ac`), fetch authentifié vers
 * `/api/documents/source-file?doc_id=...` puis ouvre le blob.
 *
 * Centralisé dans CH-05.3 — utilisé par SourcePill (inline) et SourcesSection
 * (legacy bloc bas de réponse).
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export interface OpenSourceFileError {
  message: string
  status?: number
}

const PAGE_NUM_RE = /(\d+)/

function parsePageNumber(page: number | string | undefined): number | undefined {
  if (page === undefined || page === null) return undefined
  if (typeof page === 'number') return page > 0 ? page : undefined
  const m = page.match(PAGE_NUM_RE)
  if (!m) return undefined
  const n = parseInt(m[1], 10)
  return n > 0 ? n : undefined
}

/**
 * Ouvre le fichier source dans un nouveau tab.
 *
 * Pour les PDFs, append `#page=N` à l'URL (RFC 3778) si `page` est fourni →
 * le viewer PDF du navigateur ouvre directement à la bonne page (CH-05.5).
 *
 * @param source doc_id ou URL absolue
 * @param page numéro de page (1-based, accepte "p.42" ou 42) — PDF uniquement
 * @returns null si succès, sinon objet d'erreur (à utiliser pour toast)
 */
export async function openSourceFile(
  source: string,
  page?: number | string,
): Promise<OpenSourceFileError | null> {
  if (!source) {
    return { message: 'Source vide' }
  }

  const pageNum = parsePageNumber(page)
  // Construit le fragment #page=N pour les PDFs (RFC 3778)
  const pageFragment = pageNum ? `#page=${pageNum}` : ''

  // URL absolue → ouvrir directement (avec fragment si fourni)
  if (/^https?:\/\//i.test(source)) {
    window.open(source + pageFragment, '_blank', 'noopener,noreferrer')
    return null
  }

  // doc_id → fetch authentifié + blob
  const token =
    typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null
  const apiUrl = `${API_BASE_URL}/api/documents/source-file?doc_id=${encodeURIComponent(
    source,
  )}`

  try {
    const res = await fetch(apiUrl, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    if (!res.ok) {
      return { message: `HTTP ${res.status}`, status: res.status }
    }
    const blob = await res.blob()
    let url = URL.createObjectURL(blob)
    // Append #page=N uniquement pour les PDFs (les blobs Office ignorent)
    if (pageFragment && blob.type === 'application/pdf') {
      url += pageFragment
    }
    window.open(url, '_blank', 'noopener,noreferrer')
    // Libère l'objet URL après 60s (le tab a déjà chargé le PDF)
    setTimeout(() => URL.revokeObjectURL(url.split('#')[0]), 60_000)
    return null
  } catch (err) {
    return { message: (err as Error).message }
  }
}
