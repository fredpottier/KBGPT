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

/**
 * Ouvre le fichier source dans un nouveau tab.
 *
 * @param source doc_id ou URL absolue
 * @returns null si succès, sinon objet d'erreur (à utiliser pour toast)
 */
export async function openSourceFile(
  source: string,
): Promise<OpenSourceFileError | null> {
  if (!source) {
    return { message: 'Source vide' }
  }

  // URL absolue → ouvrir directement
  if (/^https?:\/\//i.test(source)) {
    window.open(source, '_blank', 'noopener,noreferrer')
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
    const url = URL.createObjectURL(blob)
    window.open(url, '_blank', 'noopener,noreferrer')
    // Libère l'objet URL après 60s (le tab a déjà chargé le PDF)
    setTimeout(() => URL.revokeObjectURL(url), 60_000)
    return null
  } catch (err) {
    return { message: (err as Error).message }
  }
}
