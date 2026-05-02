/**
 * sourceRefs — pre-processeur des citations [[SOURCE:doc_id|page]] →
 * index numéroté style Wikipedia footnotes.
 *
 * Avant : "Les portes [[SOURCE:cs25_amdt_22_...|p.433]] et [[SOURCE:cs25_amdt_22_...|p.585]]"
 * Après : "Les portes [[REF:1]] et [[REF:1]]" + refs = [{docId: "cs25_amdt_22_..."}]
 *
 * Dédup par doc_id uniquement (les pages sont ignorées car le viewer doc ne
 * supporte pas le deep-link à la page — feedback user 2026-05-02).
 * Le même doc cité N fois sur N pages différentes = un seul numéro [1].
 */

export interface SourceRef {
  docId: string
}

const SOURCE_PATTERN = /\[\[SOURCE:([^\]|]+?)(?:\|([^\]]+?))?\]\]/g

export function indexAndReplaceSources(text: string): {
  text: string
  refs: SourceRef[]
} {
  if (!text) return { text: '', refs: [] }

  const seen = new Map<string, number>() // key = docId → index 1-based
  const refs: SourceRef[] = []

  const replaced = text.replace(SOURCE_PATTERN, (_full, docId, _page) => {
    const did = String(docId || '').trim()
    if (!did) return ''
    let idx = seen.get(did)
    if (idx === undefined) {
      idx = refs.length + 1
      seen.set(did, idx)
      refs.push({ docId: did })
    }
    return `[[REF:${idx}]]`
  })

  return { text: replaced, refs }
}
