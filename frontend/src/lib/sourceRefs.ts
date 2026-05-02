/**
 * sourceRefs — pre-processeur des citations [[SOURCE:doc_id|page]] →
 * index numéroté style Wikipedia footnotes.
 *
 * Avant : "Les portes [[SOURCE:cs25_amdt_22_8e69026c|p.433]] ..."
 * Après : "Les portes [[REF:1]] ..." + index = [{docId: "cs25_amdt_22_...", page: "p.433"}]
 *
 * Dédup par (doc_id, page) : si la même paire apparaît N fois, même numéro.
 * Si même doc avec pages différentes → numéros distincts.
 */

export interface SourceRef {
  docId: string
  page?: string
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
