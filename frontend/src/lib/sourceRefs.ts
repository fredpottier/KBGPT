/**
 * sourceRefs — pre-processeur des citations [[SOURCE:doc_id|page]] →
 * index numéroté style Wikipedia footnotes.
 *
 * Avant : "Les portes [[SOURCE:cs25_amdt_22_...|p.433]] et [[SOURCE:cs25_amdt_22_...|p.585]]"
 * Après : "Les portes [[REF:1]] et [[REF:1]]" + refs = [{docId, firstPage: 433}]
 *
 * Dédup par doc_id uniquement → un doc cité N fois = un seul numéro [N].
 * La page de la première occurrence est conservée dans `firstPage` pour
 * permettre le deep-link `#page=N` (RFC 3778) au clic — CH-05.5.
 */

export interface SourceRef {
  docId: string
  firstPage?: number
}

const SOURCE_PATTERN = /\[\[SOURCE:([^\]|]+?)(?:\|([^\]]+?))?\]\]/g
const PAGE_NUM_RE = /(\d+)/

function parsePageNumber(page: string | undefined): number | undefined {
  if (!page) return undefined
  const m = page.match(PAGE_NUM_RE)
  return m ? parseInt(m[1], 10) : undefined
}

export function indexAndReplaceSources(text: string): {
  text: string
  refs: SourceRef[]
} {
  if (!text) return { text: '', refs: [] }

  const seen = new Map<string, number>() // key = docId → index 1-based
  const refs: SourceRef[] = []

  const replaced = text.replace(SOURCE_PATTERN, (_full, docId, page) => {
    const did = String(docId || '').trim()
    if (!did) return ''
    let idx = seen.get(did)
    if (idx === undefined) {
      idx = refs.length + 1
      seen.set(did, idx)
      refs.push({ docId: did, firstPage: parsePageNumber(page) })
    }
    return `[[REF:${idx}]]`
  })

  return { text: replaced, refs }
}
