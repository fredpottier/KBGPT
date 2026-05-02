/**
 * sourceRefs — pre-processeur des citations [[SOURCE:doc_id|page]] →
 * index numéroté style Wikipedia footnotes.
 *
 * Avant : "Les portes [[SOURCE:cs25_amdt_22_...|p.433]] et [[SOURCE:cs25_amdt_22_...|p.585]]"
 * Après : "Les portes [[REF:1]] et [[REF:2]]" + refs = [
 *   {docId: "cs25_amdt_22_...", page: "p.433"},
 *   {docId: "cs25_amdt_22_...", page: "p.585"}
 * ]
 *
 * Dédup par (docId, page) — chaque combinaison unique a son numéro.
 * Permet le deep-link `#page=N` (RFC 3778) à la bonne page pour les PDFs.
 * Pour les formats sans deep-link (PPTX, DOCX), même comportement mais le
 * fragment est ignoré → page 1 pour tous (CH-05.5).
 */

export interface SourceRef {
  docId: string
  page?: string // ex: "p.433"
}

const SOURCE_PATTERN = /\[\[SOURCE:([^\]|]+?)(?:\|([^\]]+?))?\]\]/g

export function indexAndReplaceSources(text: string): {
  text: string
  refs: SourceRef[]
} {
  if (!text) return { text: '', refs: [] }

  const seen = new Map<string, number>() // key = "docId|page" → index 1-based
  const refs: SourceRef[] = []

  const replaced = text.replace(SOURCE_PATTERN, (_full, docId, page) => {
    const did = String(docId || '').trim()
    if (!did) return ''
    const pg = page ? String(page).trim() : undefined
    const key = `${did}|${pg || ''}`
    let idx = seen.get(key)
    if (idx === undefined) {
      idx = refs.length + 1
      seen.set(key, idx)
      refs.push({ docId: did, page: pg })
    }
    return `[[REF:${idx}]]`
  })

  return { text: replaced, refs }
}
